"""librarian/app.py — FastAPI 端点, aw/ssll 写稿时调它借阅经验卡 (D-038 / docs/14)。

  POST /librarian   body = brief(JSON)  → {"selected": [ {source_note_id, why_relevant,
                                            borrow_what, hook_type, structure, ...}, ... ]}
  GET  /health      → {"ok": true}      (Railway healthcheck)

鉴权: 若设了环境变量 LIBRARIAN_API_KEY, 请求须带 header `X-Librarian-Key: <key>`;
      没设则放行(本地/dev)。service_role 只在服务端, 绝不下发给调用方 —— 调用方只发
      brief、收 selected。

降级: 任何内部错误都返回 {"selected": []}(消费方据此回退到自有正例), 不抛 500 阻塞写稿。
      鉴权失败 → 401; body 不是 JSON object → 400。

部署 (Railway): root = repo 根 (让 `librarian` 包可导入),
  build:  pip install -r librarian/requirements.txt
  start:  uvicorn librarian.app:app --host 0.0.0.0 --port $PORT
  env:    SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY / ANTHROPIC_API_KEY /
          FLYWHEEL_LIBRARIAN_MODEL(可选) / LIBRARIAN_API_KEY(鉴权, 生产建议设)
  见 repo 根 railway.json。
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Header, HTTPException, Request

from .core import librarian_select

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("librarian")

app = FastAPI(title="Flywheel Librarian", version="1")


def _check_auth(provided: str | None) -> None:
    expected = os.environ.get("LIBRARIAN_API_KEY")
    if not expected:
        return  # 未配 = dev 模式, 放行
    if provided != expected:
        raise HTTPException(status_code=401, detail="invalid or missing X-Librarian-Key")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "flywheel-librarian"}


@app.post("/librarian")
async def librarian(
    request: Request,
    x_librarian_key: str | None = Header(default=None),
) -> dict:
    _check_auth(x_librarian_key)

    try:
        brief = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="body must be a JSON brief")
    if not isinstance(brief, dict):
        raise HTTPException(status_code=400, detail="brief must be a JSON object")

    try:
        selected = librarian_select(brief)
        # librarian_select 在空库/LLM 失败时已返回 []; 这里再兜一层结构保证。
        if not isinstance(selected, list):
            selected = []
    except Exception:
        logger.exception("librarian_select crashed; returning [] for graceful fallback")
        selected = []

    return {"selected": selected}
