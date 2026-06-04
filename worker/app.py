"""worker/app.py — FastAPI 端点(部署在 Railway)。

为什么在 Railway:它连得上中转站(实测 GitHub Actions 海外 runner 连不上,connect=0)。
这些任务本来在 daily-sync(GitHub Actions)里直接跑 scripts/*.py,因连不上网关而失败;
搬到 Railway 后由 GitHub daily-sync 调本服务端点触发(保留 GitHub 的失败→邮件告警)。

  POST /annotate-essence  body={project, limit?, dry_run?, reannotate?}
  POST /curate            body={project?, limit?, dry_run?}
  GET  /health

实现:subprocess 跑【现有的、已验证的】scripts/annotate_essence_pass.py /
     curate_flywheel_lessons.py —— 不重写标注逻辑,只换运行环境(Railway 连得上网关)。
     脚本本就读 ANTHROPIC_BASE_URL/KEY + ESSENCE_MODEL,按 essence_annotated_at IS NULL
     续作、幂等;跑不完下一轮 cron 接着跑。
返回 200 + {ok, returncode, stdout_tail, stderr_tail};returncode!=0 时 ok=false,
由 daily-sync 判该步失败(聚合 → 整 workflow 红 → GitHub 发邮件)。

鉴权:设了 WORKER_API_KEY 则请求须带 header `X-Worker-Key: <key>`;没设则放行(dev)。

部署(Railway · 新建一个 service,与 librarian/onboarder 并存):
  root = repo 根(让 subprocess 能找到 scripts/)
  build: pip install -r worker/requirements.txt
  start: uvicorn worker.app:app --host 0.0.0.0 --port $PORT
  healthcheck: /health
  env:  SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY /
        ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL(用【能跑通的那条通道】)/
        ESSENCE_MODEL(可选,默认 claude-sonnet-4-6)/ WORKER_API_KEY(鉴权,建议设)/
        WORKER_RUN_TIMEOUT_S(可选,单次 subprocess 硬超时,默认 900)
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tv-worker")

app = FastAPI(title="Truth Vault Worker", version="1")

# repo 根 = worker/ 的上一级;scripts/ 在它下面。
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"

# 单次 subprocess 的硬超时(秒)。essence 默认 --limit 50,约几分钟内完成;
# 跑不完下一轮 cron 接着跑(脚本按 essence_annotated_at IS NULL 续作,幂等)。
# 若 Railway HTTP 边缘超时(部分套餐 ~5min),把 daily-sync 的 limit 调小即可。
_RUN_TIMEOUT_S = int(os.environ.get("WORKER_RUN_TIMEOUT_S", "900"))
_TAIL = 4000  # 回传给调用方的 stdout/stderr 末尾字节数(控响应体)


def _check_auth(provided: str | None) -> None:
    expected = os.environ.get("WORKER_API_KEY")
    if not expected:
        return  # 未配 = dev 模式,放行
    if provided != expected:
        raise HTTPException(status_code=401, detail="invalid or missing X-Worker-Key")


def _run(script: str, args: list[str]) -> dict:
    """跑 scripts/<script> <args>,捕获输出。

    env 继承本进程(Railway 上配了 SUPABASE_* / ANTHROPIC_*)。脚本用
    `from _common import ...`,靠 sys.path[0]=脚本所在目录解析;mappings/ 由
    _common 的 `Path(__file__)...` 定位,与 cwd 无关。

    ⚠️ 这是【阻塞】函数(subprocess.run 同步等子进程)。**必须经 run_in_threadpool
    在线程里跑**,绝不能在 async 端点里直接调用 —— 否则一次几分钟的 essence 会把
    事件循环堵死,/health 失联 → Railway 健康检查超时把容器重启 → 杀掉本次 run
    (实测:50 条/轮在 ~301s 被重启,只标了 23 条)。
    """
    path = _SCRIPTS_DIR / script
    if not path.exists():
        raise HTTPException(status_code=500, detail=f"script not found: {path}")
    cmd = [sys.executable, str(path), *args]
    logger.info("run: %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd, cwd=str(_REPO_ROOT), capture_output=True, text=True,
            timeout=_RUN_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        logger.warning("timeout after %ss: %s %s", _RUN_TIMEOUT_S, script, args)
        partial = exc.stdout if isinstance(exc.stdout, str) else ""
        return {
            "ok": False, "returncode": 124, "timed_out": True,
            "stdout_tail": partial[-_TAIL:],
            "stderr_tail": f"timeout after {_RUN_TIMEOUT_S}s "
                           f"(调小 daily-sync 的 limit 或调大 WORKER_RUN_TIMEOUT_S)",
        }
    if proc.returncode != 0:
        logger.warning("non-zero exit %s: %s %s", proc.returncode, script, args)
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-_TAIL:],
        "stderr_tail": proc.stderr[-_TAIL:],
    }


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="body must be JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    return body


def _limit_arg(body: dict, default: int = 50) -> str:
    try:
        n = int(body.get("limit", default) or default)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="limit must be an integer")
    if n <= 0:
        raise HTTPException(status_code=400, detail="limit must be positive")
    return str(n)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "tv-worker"}


@app.post("/annotate-essence")
async def annotate_essence(
    request: Request,
    x_worker_key: str | None = Header(default=None),
) -> dict:
    _check_auth(x_worker_key)
    body = await _json_body(request)
    project = body.get("project")
    if not project:
        raise HTTPException(status_code=400, detail="missing required field: project")
    args = [str(project), "--limit", _limit_arg(body)]
    if body.get("dry_run"):
        args.append("--dry-run")
    if body.get("reannotate"):
        args.append("--reannotate")
    # 线程池跑阻塞 subprocess,别堵事件循环(见 _run docstring)。
    res = await run_in_threadpool(_run, "annotate_essence_pass.py", args)
    res["action"] = "annotate-essence"
    res["project"] = project
    return res


@app.post("/curate")
async def curate(
    request: Request,
    x_worker_key: str | None = Header(default=None),
) -> dict:
    _check_auth(x_worker_key)
    body = await _json_body(request)
    args = ["--limit", _limit_arg(body)]
    if body.get("project"):
        args += ["--project", str(body["project"])]
    if body.get("dry_run"):
        args.append("--dry-run")
    # 线程池跑阻塞 subprocess,别堵事件循环(见 _run docstring)。
    res = await run_in_threadpool(_run, "curate_flywheel_lessons.py", args)
    res["action"] = "curate"
    res["project"] = body.get("project")
    return res
