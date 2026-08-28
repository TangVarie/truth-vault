"""onboarder/app.py — FastAPI 端点(部署在 Railway)。

为什么在 Railway:它连得上中转站 + 飞书(实测 GitHub Actions 连不上中转站)。
分工:本服务只【产草稿】,不碰 git;git/PR 由 GitHub Action(onboard-table.yml)做。

  POST /onboard  body={project_id, (url | app_token+table_id), sample_n?, model?}
                 → {mapping_yaml, review_brief, errors, uncovered, pending, is_error,
                    app_token, table_id}
  GET  /health   → {"ok": true}

批量(多张表)**不在这里** —— 见 `onboarder/batch.py`:它在调用方(GH runner / 本地)
逐表打这个端点。故意不做服务端批量端点,理由三条:① 单表就已逼近网关/代理的请求
超时(全表 distinct 扫描 + 16k 输出),串起 N 张必超;② Railway 重启会丢内存里的
批次状态;③ 逐表独立请求天然做到"一张挂了不拖垮整批",且不新增鉴权面。

鉴权:设了 ONBOARDER_API_KEY 则请求须带 header `X-Onboarder-Key: <key>`;没设则放行(dev)。

部署(Railway · 新建一个 service,与 librarian 并存):
  root = repo 根(让 `onboarder` 包可导入)
  build: pip install -r onboarder/requirements.txt
  start: uvicorn onboarder.app:app --host 0.0.0.0 --port $PORT
  healthcheck: /health
  env:   ANTHROPIC_BASE_URL / ANTHROPIC_API_KEY(用【能跑通的那条通道】)/
         FEISHU_APP_ID / FEISHU_APP_SECRET / ONBOARDER_API_KEY(鉴权,建议设)/
         ONBOARDER_MODEL(可选,默认 claude-sonnet-4-6)
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Header, HTTPException, Request

from . import core

# 仓库根的共享鉴权闸(跨库审计 SUP-001)。三个服务的 Railway root 都是 repo
# 根(见各自 railway.json 的 startCommand `uvicorn <svc>.app:app`), 所以顶层
# 模块对三边都可导入; 它只用标准库, 不给任何一个服务加依赖。
import service_auth

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("onboarder")

app = FastAPI(title="Truth Vault Onboarder", version="1")


def _check_auth(provided: str | None) -> None:
    """没配 key 就**一律 401**, 不再静默放行(跨库审计 SUP-001)。

    判据统一在仓库根的 ``service_auth`` 里 —— 三个服务原来各存一份
    一模一样的实现, 而它们守的是同一条安全不变量: 漂了就意味着某个
    服务悄悄还开着, 且没有任何症状。
    """
    try:
        service_auth.resolve("ONBOARDER", provided, header="X-Onboarder-Key")
    except service_auth.AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.get("/health")
def health() -> dict:
    """健康检查 + 鉴权状态自曝(跨库审计 SUP-001 / ROB-004)。

    原来只回 ``{"ok": True}`` —— 也就是说"key 漏配了"这件事在外面完全看不见。
    worker 早就在回显了, 这两个补齐, 三个服务口径一致。

    ⚠️ 自曝**不是防线**: 防线是 _check_auth 的 fail-closed(没配 key 且没显式开
       匿名就一律 401)。自曝的价值是让运维知道"为什么全在 401"。
    ⚠️ ``ok`` 保持恒 True —— Railway 的 healthcheckPath 指着它, 配置不全不该让
       容器起不来(重启治不好配置, 只会变成重启风暴)。要看的是 ``auth.ok``。
    """
    return {
        "ok": True,
        "service": "onboarder",
        "auth": service_auth.auth_health("ONBOARDER", header="X-Onboarder-Key"),
    }


@app.post("/onboard")
async def onboard(
    request: Request,
    x_onboarder_key: str | None = Header(default=None),
) -> dict:
    _check_auth(x_onboarder_key)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="body must be JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    if not body.get("project_id"):
        raise HTTPException(status_code=400, detail="missing required field: project_id")
    # 表标识二选一:一条飞书链接(url,含 /wiki/ 形态)或 app_token + table_id。
    # 批量入口给的是链接 —— 运营手里只有链接, 抠 id 那一步本来就是人肉的。
    if not body.get("url") and not (body.get("app_token") and body.get("table_id")):
        raise HTTPException(
            status_code=400,
            detail="missing table ref: 给 url(飞书链接)或 app_token + table_id",
        )

    try:
        res = core.draft(
            project_id=body["project_id"],
            app_token=body.get("app_token"),
            table_id=body.get("table_id"),
            url=body.get("url"),
            sample_n=int(body.get("sample_n", 30) or 30),
            model=body.get("model") or core.DEFAULT_MODEL,
        )
    except ValueError as exc:
        # LinkError 是 ValueError 的子类; sample_n 转 int 失败也落这里。
        # 都是**调用方的**输入问题 —— 400 而不是 500, 否则批量那侧会把它当服务
        # 故障去重试, 而重试一万次也还是那条坏链接。
        raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("draft crashed")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")

    if "mapping_yaml" not in res:
        # 模型没产出可解析的 mapping —— 让调用方看到失败(非 200)
        raise HTTPException(status_code=502, detail=res.get("reason", "draft failed"))
    return res
