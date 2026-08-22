"""deskcore/app.py — 写作台内核服务 (D-041)。

三个入口, 同一套 tools:
  1. MCP over streamable HTTP   /mcp        ← WorkBuddy / Claude Code / CodeBuddy
  2. 纯 REST                     POST /tool/{name}   ← 兜底 + 自测 + 不支持 MCP 的平台
  3. CLI                        deskcore/cli.py     ← 本地 dry-run

鉴权与身份 (X-Deskcore-Key → user_id, 见 identity.py):
  key 支持三种传法, 优先级从高到低 ——
    a) header  X-Deskcore-Key: <key>
    b) header  Authorization: Bearer <key>
    c) query   ?key=<key>
  之所以要三种: WorkBuddy 的 HTTP MCP 能不能配自定义 header, 官方更新日志
  只说了支持 HTTP MCP 和 OAuth, 没有权威文档(docs/27 未决点 1)。留 b/c 两条
  退路, 免得协议层卡住整个方案。

降级:
  读类工具出错 → 返回带 error 的可用结构 + 服务端 logger.exception 留痕。
  check_drafts 例外 → 出错抛 500。查重静默放行 = 重演 autowriter
  ENABLE_DEDUP_REGEN 默认关着的老问题。

部署 (Railway): root = repo 根 (让 `deskcore` 包可导入)
  build:  pip install -r deskcore/requirements.txt
  start:  uvicorn deskcore.app:app --host 0.0.0.0 --port $PORT
  env:    SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY
          GOOGLE_API_KEY            (embedding; 不设则查重降级为纯确定性)
          ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL
          DESKCORE_MODEL            (默认 claude-sonnet-4-6)
          DESKCORE_KEYS 或 DESKCORE_API_KEY + DESKCORE_DEFAULT_USER_ID
          LIBRARIAN_URL / LIBRARIAN_API_KEY  (借爆款经验卡; 不设则跳过)
  见 deskcore/railway.json。
"""

from __future__ import annotations

import contextvars
import logging
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from . import clients, identity, tools

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("deskcore")

SERVICE = "deskcore"
VERSION = "1"

# 当前请求的调用者。MCP 的 ASGI 子应用拿不到 FastAPI 的依赖注入, 用 contextvar
# 在中间件里塞、在工具里取, 是最省事且线程/协程安全的做法。
_caller: contextvars.ContextVar[identity.Caller] = contextvars.ContextVar(
    "deskcore_caller", default=identity.Caller(None, "anonymous", False))


def _extract_key(request: Request) -> str | None:
    key = request.headers.get("x-deskcore-key")
    if key:
        return key
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.query_params.get("key")


def _call_tool(name: str, args: dict) -> object:
    """统一的工具调用入口: 注入 _user_id, 转发到 tools.TOOLS。"""
    entry = tools.TOOLS.get(name)
    if entry is None:
        raise KeyError(name)
    fn, needs_user = entry
    kwargs = dict(args or {})
    kwargs.pop("_user_id", None)  # 不允许调用方伪造身份
    if needs_user:
        kwargs["_user_id"] = _caller.get().user_id
    return fn(**kwargs)


# ── FastAPI ──────────────────────────────────────────────────────────

app = FastAPI(title="Deskcore · 写作台内核", version=VERSION)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # /health 不鉴权 —— Railway 健康检查不会带 key。
    if request.url.path.rstrip("/") in ("/health", ""):
        return await call_next(request)
    try:
        caller = identity.resolve(_extract_key(request))
    except identity.AuthError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=401)
    token = _caller.set(caller)
    try:
        return await call_next(request)
    finally:
        _caller.reset(token)


@app.get("/health")
def health() -> dict:
    """回显实际解析到的配置。

    ⚠️ 这个回显是【刻意的】: 三个 Railway 服务的模型 env 变量名各不相同
    (worker=ESSENCE_MODEL / librarian=FLYWHEEL_LIBRARIAN_MODEL /
    autowriter=CLAUDE_MODEL), 已经害过一次 —— librarian 忘了配, 每次 LLM 调用
    失败降级成 [], 外面看永远 200, 查了很久(docs/19:180-200)。让配错当场可见。
    """
    lib_ok, lib_note = clients.librarian_reachable()
    db_ok, db_note = True, "ok"
    try:
        clients.get_supabase().table("projects").select("id").limit(1).execute()
    except Exception as exc:  # noqa: BLE001
        db_ok, db_note = False, f"{type(exc).__name__}: {exc}"[:160]
    return {
        "ok": db_ok,
        "service": SERVICE,
        "version": VERSION,
        "tools": sorted(tools.TOOLS),
        "config": {
            "model": os.environ.get("DESKCORE_MODEL", "claude-sonnet-4-6"),
            "anthropic_base_url": os.environ.get("ANTHROPIC_BASE_URL") or "(official)",
            "supabase": {"ok": db_ok, "note": db_note},
            "embeddings": {
                "ok": clients.embeddings_available(),
                "model": clients.EMBEDDING_MODEL,
                "note": ("ok" if clients.embeddings_available()
                         else "GOOGLE_API_KEY 未配 —— 查重会降级为纯确定性, "
                              "同角度换说法的标题可能漏过"),
            },
            "librarian": {"ok": lib_ok, "note": lib_note},
            "auth": {
                "configured": identity.auth_configured(),
                "note": ("ok" if identity.auth_configured()
                         else "未配鉴权 = dev 模式全放行; 生产必须配 "
                              "DESKCORE_KEYS 或 DESKCORE_API_KEY"),
            },
        },
    }


@app.get("/tools")
def list_tools() -> dict:
    """工具清单 + 说明, 给不支持 MCP 的平台看。"""
    return {"tools": [
        {"name": n, "description": (f.__doc__ or "").strip(),
         "needs_identity": needs}
        for n, (f, needs) in sorted(tools.TOOLS.items())
    ]}


@app.post("/tool/{name}")
async def rest_tool(name: str, request: Request):
    """纯 REST 调用通道。body = 工具参数的 JSON object。

    存在理由: ① 自测(curl 就能验) ② MCP 协议层万一在某个平台上不通的退路。
    """
    if name not in tools.TOOLS:
        raise HTTPException(status_code=404, detail=f"unknown tool: {name}")
    try:
        args = await request.json()
    except Exception:
        args = {}
    if not isinstance(args, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    try:
        return {"result": _call_tool(name, args)}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        # check_drafts 走到这里 = 查重真的挂了, 必须 500 不能装作没事。
        logger.exception("tool %s failed", name)
        raise HTTPException(status_code=500,
                            detail=f"{type(exc).__name__}: {exc}"[:300])


# ── MCP ──────────────────────────────────────────────────────────────
# 用官方 SDK 的 FastMCP, 把每个工具注册一遍。SDK 缺失时服务照常起(REST 可用),
# 只是 /mcp 不挂 —— 免得一个可选依赖把整个服务拖down。

def _register_mcp():
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        logger.warning("mcp SDK not available; /mcp endpoint disabled "
                       "(REST /tool/{name} still works)")
        return None

    mcp = FastMCP(name="deskcore", stateless_http=True, json_response=True)

    def _make(name: str, fn, needs_user: bool):
        # 用闭包包一层, 把 _user_id 从签名里摘掉再注册 —— 模型不该看到它,
        # 也不该能传它。
        import functools
        import inspect

        sig = inspect.signature(fn)
        params = [p for k, p in sig.parameters.items() if not k.startswith("_")]

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            kwargs.pop("_user_id", None)
            if needs_user:
                kwargs["_user_id"] = _caller.get().user_id
            return fn(*args, **kwargs)

        wrapper.__signature__ = sig.replace(parameters=params)
        return wrapper

    for name, (fn, needs_user) in tools.TOOLS.items():
        mcp.add_tool(_make(name, fn, needs_user), name=name,
                     description=(fn.__doc__ or "").strip())
    return mcp


_mcp = _register_mcp()
if _mcp is not None:
    # streamable HTTP 子应用挂在 /mcp。中间件已经在外层 FastAPI 上, 子应用
    # 请求同样会先过 auth_middleware, 所以 _caller 在工具里取得到。
    app.mount("/mcp", _mcp.streamable_http_app())
