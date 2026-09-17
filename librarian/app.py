"""librarian/app.py — FastAPI 端点, aw/ssll 写稿时调它借阅经验卡 (D-038 / docs/14)。

  POST /librarian   body = brief(JSON)  → {"selected": [ {source_note_id, why_relevant,
                                            borrow_what, hook_type, structure, ...}, ... ]}
  GET  /health      → {"ok": true}      (Railway healthcheck)

鉴权: 若设了环境变量 LIBRARIAN_API_KEY, 请求须带 header `X-Librarian-Key: <key>`;
      没设则放行(本地/dev)。service_role 只在服务端, 绝不下发给调用方 —— 调用方只发
      brief、收 selected。

降级: 任何内部错误都返回 {"selected": []}(消费方据此回退到自有正例), 不抛 500 阻塞写稿。
      2026-09-17(TV-06) 起同时返回 `status`: ok / no_match / degraded / error ——
      降级照旧不抛 500, 但调用方能分出"没有相关卡"和"服务出问题了"。
      鉴权失败 → 401; body 不是 JSON object → 400。

部署 (Railway): root = repo 根 (让 `librarian` 包可导入),
  build:  pip install -r librarian/requirements.txt
  start:  uvicorn librarian.app:app --host 0.0.0.0 --port $PORT
  env:    SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY / ANTHROPIC_API_KEY /
          ANTHROPIC_BASE_URL(中转站/第三方网关, 可选; 不设走官方) /
          FLYWHEEL_LIBRARIAN_MODEL(可选, 默认 claude-sonnet-4-6) /
          LIBRARIAN_API_KEY(鉴权, 生产建议设)
  见 repo 根 railway.json。
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Header, HTTPException, Request

from starlette.concurrency import run_in_threadpool

from .core import (STATUS_DEGRADED, librarian_select_detailed)

STATUS_ERROR = "error"   # 应用层崩溃(core 之外), 与 core 的 degraded 区分开

# 仓库根的共享鉴权闸(跨库审计 SUP-001)。三个服务的 Railway root 都是 repo
# 根(见各自 railway.json 的 startCommand `uvicorn <svc>.app:app`), 所以顶层
# 模块对三边都可导入; 它只用标准库, 不给任何一个服务加依赖。
import service_auth

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("librarian")

app = FastAPI(title="Flywheel Librarian", version="1")


def _check_auth(provided: str | None) -> None:
    """没配 key 就**一律 401**, 不再静默放行(跨库审计 SUP-001)。

    判据统一在仓库根的 ``service_auth`` 里 —— 三个服务原来各存一份
    一模一样的实现, 而它们守的是同一条安全不变量: 漂了就意味着某个
    服务悄悄还开着, 且没有任何症状。
    """
    try:
        service_auth.resolve("LIBRARIAN", provided, header="X-Librarian-Key")
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
        "service": "flywheel-librarian",
        "auth": service_auth.auth_health("LIBRARIAN", header="X-Librarian-Key"),
    }


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

    # TV-06: ① 同步的选卡流程(同步 DB + 同步模型请求)不能直接在 async 路由里跑 ——
    #   它会占住事件循环, 一次慢调用把同进程的其它请求一起拖住。挪进线程池。
    #   ② status 字段让调用方分得出"没有相关卡"和"服务出问题了" —— 之前两者都是
    #   HTTP 200 + 空 selected, 完全一样。selected 的形状不变, 老消费方不受影响。
    try:
        selected, status = await run_in_threadpool(librarian_select_detailed, brief)
        if not isinstance(selected, list):
            selected, status = [], STATUS_DEGRADED
    except Exception:
        logger.exception("librarian_select crashed; returning [] for graceful fallback")
        selected, status = [], STATUS_ERROR

    return {"selected": selected, "status": status}
