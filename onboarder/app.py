"""onboarder/app.py — FastAPI 端点(部署在 Railway)。

为什么在 Railway:它连得上中转站 + 飞书(实测 GitHub Actions 连不上中转站)。
分工:本服务只【产草稿】,不碰 git;git/PR 由 GitHub Action(onboard-table.yml)做。

  POST /onboard  body={project_id, app_token, table_id, sample_n?, model?}
                 → {mapping_yaml, review_brief, errors, uncovered, pending, is_error}
  GET  /health   → {"ok": true}

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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("onboarder")

app = FastAPI(title="Truth Vault Onboarder", version="1")


def _check_auth(provided: str | None) -> None:
    expected = os.environ.get("ONBOARDER_API_KEY")
    if not expected:
        return  # 未配 = dev 模式, 放行
    if provided != expected:
        raise HTTPException(status_code=401, detail="invalid or missing X-Onboarder-Key")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "onboarder"}


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
    for k in ("project_id", "app_token", "table_id"):
        if not body.get(k):
            raise HTTPException(status_code=400, detail=f"missing required field: {k}")

    try:
        res = core.draft(
            project_id=body["project_id"],
            app_token=body["app_token"],
            table_id=body["table_id"],
            sample_n=int(body.get("sample_n", 30) or 30),
            model=body.get("model") or core.DEFAULT_MODEL,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("draft crashed")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")

    if "mapping_yaml" not in res:
        # 模型没产出可解析的 mapping —— 让调用方看到失败(非 200)
        raise HTTPException(status_code=502, detail=res.get("reason", "draft failed"))
    return res
