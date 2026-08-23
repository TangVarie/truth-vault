"""worker/app.py — FastAPI 端点(部署在 Railway)。

为什么在 Railway:它连得上中转站(实测 GitHub Actions 海外 runner 连不上,connect=0)。
这些任务本来在 daily-sync(GitHub Actions)里直接跑 scripts/*.py,因连不上网关而失败;
搬到 Railway 后由 GitHub daily-sync 调本服务端点触发(保留 GitHub 的失败→邮件告警)。

  POST /annotate-essence  body={project, limit?, dry_run?, reannotate?}
  POST /curate            body={project?, limit?, dry_run?}
  GET  /health            → {ok, service, auth{ok,required,mode}, config{...}, running[]}

并发: 每个脚本同一时刻只跑一个(_script_lock)。抢不到锁 → **409** + detail 说明,
     调用方当【幂等瞬时失败】处理、下轮再来(见 _script_lock docstring)。

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
import threading
from contextlib import contextmanager
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

# 每脚本互斥锁 —— 同一个脚本同一时刻只准跑一个进程。
#
# 为什么需要: daily-sync.yml:181 和 backfill-essence.yml:118 打的是【同一个】
# /annotate-essence。annotate_essence_pass.py 开工时 SELECT `essence_annotated_at
# IS NULL` 拿一批, 两个 run 同时跑就会各自快照【同一批】笔记 → 重复烧 LLM、且
# 非确定性地互相覆盖 essence。backfill-essence.yml:30 的 concurrency group 只挡
# backfill 自己(而且是 per-project), 挡不住跨 workflow 相撞 —— 那道闸只在 GitHub
# 侧, 而真正被共享的资源是 worker 这一个进程, 所以锁必须落在这里。
#
# 语义: 非阻塞。抢不到 → 409 + busy=true, 调用方按【幂等瞬时失败】处理下轮再来
# (daily-sync.yml worker_fail_kind() 已把 409 归入 transient; backfill 本就对
# 非 200 退避重试)。绝不阻塞等待 —— 一等就撞 Railway 边缘 ~5min 超时, 白占连接。
#
# ⚠️ 边界: 这是【进程内】锁, 只在 Railway 单实例下成立(当前部署即单实例)。
#    真要多副本, 得换成 Postgres advisory lock —— 那时把本函数换掉即可, 调用方
#    契约(409 busy)不用动。
_SCRIPT_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


@contextmanager
def _script_lock(script: str):
    """非阻塞地独占 <script>;已有人在跑就抛 409。"""
    with _LOCKS_GUARD:
        lock = _SCRIPT_LOCKS.setdefault(script, threading.Lock())
    if not lock.acquire(blocking=False):
        logger.warning("busy: %s already running, rejecting with 409", script)
        raise HTTPException(
            status_code=409,
            detail=f"{script} is already running; retry later (work is idempotent)",
        )
    try:
        yield
    finally:
        lock.release()


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
        with _script_lock(script):
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


def _running_scripts() -> list[str]:
    """当前持锁(=正在跑)的脚本名。

    ⚠️ 必须在 _LOCKS_GUARD 下先【快照】再判 locked(): _script_lock() 会对
    _SCRIPT_LOCKS 做 setdefault, 那是**插入**。边插边遍历同一个 dict, CPython
    会抛 RuntimeError: dictionary changed size during iteration —— 于是
    /health 变 500, Railway 健康检查失败把容器重启。最容易撞上的正是冷启动:
    Railway 在探活, 第一个 job 同时进来 (codex PR#104 review)。
    """
    with _LOCKS_GUARD:
        snapshot = list(_SCRIPT_LOCKS.items())
    return sorted(name for name, lk in snapshot if lk.locked())


def _safe_origin(url: str | None) -> str | None:
    """把 URL 削成 scheme://host[:port], 丢掉 userinfo / path / query。

    为什么: /health **没有鉴权**(它得让 Railway 探活), 而 ANTHROPIC_BASE_URL
    指向中转站, 可能带租户路径、query 里的凭据、甚至 user:pass@ 形式的
    URI userinfo。原样回显等于把它们发给任何一个匿名调用方 —— 这和本端点
    自己承诺的"只报有没有配、不报值"直接矛盾 (codex PR#104 review)。
    保留 host 是因为诊断价值全在这: 一眼看出指的是中转站还是 api.anthropic.com。
    解析失败不猜, 返回 "(unparseable)" —— 绝不 fallback 回原值。
    """
    if not url:
        return None
    try:
        from urllib.parse import urlsplit
        parts = urlsplit(url)
        if not parts.hostname:
            return "(unparseable)"
        host = parts.hostname
        # urlsplit().hostname 会把 IPv6 字面量的方括号剥掉, 直接拼端口就成了
        # https://2001:db8::1:8443 —— 既不合法也分不清哪段是端口。补回括号。
        # (codex PR#104 review)
        if ":" in host:
            host = f"[{host}]"
        origin = f"{parts.scheme}://{host}" if parts.scheme else host
        if parts.port:
            origin = f"{origin}:{parts.port}"
        return origin
    except Exception:
        return "(unparseable)"


@app.get("/health")
def health() -> dict:
    """健康检查 + 【配置自曝】。

    为什么要曝鉴权状态: _check_auth() 在没配 WORKER_API_KEY 时【静默放行】(dev 模式)。
    这在本地是便利, 在 Railway 上就是"公网裸奔但看着一切正常" —— 而且没有任何地方
    看得出来。docs/19:180-200 记过同型事故(配置错被 except 吞掉, 外面永远 200)。
    所以这里把已解析到的配置回显出来, 让配漏当场可见。

    ⚠️ 只回显【有没有配】, 绝不回显 key 本身。
    ⚠️ 保持 ok=True 不变 —— Railway healthcheck 靠它, 未配 key 不该让容器起不来
       (仍是有意的 dev 模式)。要看的是 auth.ok。
    """
    has_key = bool(os.environ.get("WORKER_API_KEY"))
    return {
        "ok": True,
        "service": "tv-worker",
        "auth": {
            # ok=False = 谁都能调这个 worker(会烧 LLM 额度)。生产上应为 True。
            "ok": has_key,
            "required": has_key,
            "mode": "X-Worker-Key" if has_key else "open (dev — WORKER_API_KEY 未配, 任何人可调)",
        },
        "config": {
            "run_timeout_s": _RUN_TIMEOUT_S,
            "scripts_dir_ok": _SCRIPTS_DIR.is_dir(),
            "supabase_url": bool(os.environ.get("SUPABASE_URL")),
            "supabase_service_role_key": bool(os.environ.get("SUPABASE_SERVICE_ROLE_KEY")),
            "anthropic_api_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
            # 只回显 scheme://host[:port] —— 见 _safe_origin()。
            "anthropic_base_url_origin": _safe_origin(os.environ.get("ANTHROPIC_BASE_URL")),
            "essence_model": os.environ.get("ESSENCE_MODEL") or "claude-sonnet-4-6 (default)",
        },
        "running": _running_scripts(),
    }


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
