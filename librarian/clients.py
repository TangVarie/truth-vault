"""librarian/clients.py — 自包含的 Supabase / Anthropic 客户端 + 小工具。

故意【不】import scripts/_common: 本服务要独立部署到 Railway, 不该依赖 TV sync
脚本的目录布局。get_supabase / call_anthropic 与 scripts 里同名逻辑略有重复,
是刻意的 deploy 独立性取舍 (未来可抽一个共享小包)。
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone

logger = logging.getLogger("flywheel_librarian")


def iso_now() -> str:
    """Naive-UTC ISO (匹配本仓 TIMESTAMP WITHOUT TIME ZONE 约定)。"""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def get_supabase():
    """service_role Supabase client (绕 RLS; 馆员只读策展库 + 读写缓存表)。"""
    from supabase import create_client  # lazy import

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    if key.startswith("sb_publishable_") or "anon" in key.lower():
        raise RuntimeError(
            "SUPABASE_SERVICE_ROLE_KEY looks like a publishable/anon key; "
            "the librarian service needs a service_role secret."
        )
    return create_client(url, key)


def parse_json(text: str):
    """Strip stray ``` fences and parse JSON. Returns None on failure."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.endswith("```"):
            t = t.rsplit("```", 1)[0]
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        return None


def call_anthropic(prompt: str, model: str, *, system=None, max_tokens: int = 1500,
                   max_attempts: int = 3) -> str:
    """One Anthropic call with exponential-backoff retry on transient errors.

    Lazy-imports anthropic so --dry-run works without the SDK.

    ``system``: 可传 str, 或带 cache_control 的 block 列表 ``[{type,text,cache_control}]``
    以启用 Anthropic prompt caching(稳定大前缀缓存, 省 ~90% 成本/延迟)。

    支持中转站 / 第三方 API 网关: 若设了环境变量 ANTHROPIC_BASE_URL, 就作为 base_url
    传给 SDK(api_key 用 ANTHROPIC_API_KEY)。这跟 autowriter 的
    clients.get_anthropic_client 同一约定 —— 帆谷用中转站访问 Claude; 不设则走官方 endpoint。
    """
    import anthropic  # lazy import

    kwargs: dict = {}
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        kwargs["api_key"] = api_key
    base_url = os.environ.get("ANTHROPIC_BASE_URL")  # 中转站; 空 = 官方 endpoint
    if base_url:
        kwargs["base_url"] = base_url
    client = anthropic.Anthropic(**kwargs)
    retryable = tuple(
        c for c in (
            getattr(anthropic, "RateLimitError", None),
            getattr(anthropic, "APIConnectionError", None),
            getattr(anthropic, "APITimeoutError", None),
            getattr(anthropic, "InternalServerError", None),
        ) if c is not None
    )

    def _run(sys_val) -> str:
        for attempt in range(max_attempts):
            try:
                create_kwargs: dict = {
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": [{"role": "user", "content": prompt}],
                }
                if sys_val is not None:   # str 或带 cache_control 的 block 列表 → prompt caching
                    create_kwargs["system"] = sys_val
                msg = client.messages.create(**create_kwargs)
                return "".join(
                    b.text for b in msg.content if getattr(b, "type", None) == "text"
                )
            except Exception as exc:
                # 中转站常见 502/529(overloaded): 用 APIStatusError.status_code + 关键词兜底。
                ase = getattr(anthropic, "APIStatusError", None)
                status = getattr(exc, "status_code", None)
                transient = (
                    (retryable and isinstance(exc, retryable))
                    or (ase is not None and isinstance(exc, ase)
                        and status in (429, 502, 503, 504, 529))
                    or any(s in str(exc).lower()
                           for s in ("429", "502", "503", "504", "529",
                                     "timeout", "connection", "overloaded"))
                )
                if not transient or attempt == max_attempts - 1:
                    raise
                time.sleep(2 ** (attempt + 1))
        raise RuntimeError("call_anthropic exhausted retries without raising")

    try:
        return _run(system)
    except Exception:
        # cache_control 降级:带 prompt caching 块的请求失败时,去掉 cache_control 用纯 system
        # 再试一次。很多中转站/转卖通道【不支持 Anthropic prompt caching】(透传 cache_control
        # 会 400/被通道吞)—— 这正是"同一通道 worker(纯 system)能跑、librarian(带缓存块)
        # 失败"的差异点。注:余额不足/鉴权/模型不存在这类错误,纯 system 也会同样失败 → 仍会
        # 抛出,不会被本降级掩盖(只损失缓存省钱,不改变内容/结果)。
        if isinstance(system, list):
            logger.warning(
                "带 cache_control 的馆员调用失败,去掉缓存块用纯 system 重试一次"
                "(疑似该中转站通道不支持 prompt caching)"
            )
            return _run(_flatten_system_blocks(system))
        raise


def _flatten_system_blocks(system) -> str:
    """把带 cache_control 的 system block 列表压成纯字符串(丢掉 prompt caching)。
    内容不变,只是不再享受 Anthropic 缓存 —— 用于通道不支持 cache_control 时降级。"""
    if not isinstance(system, list):
        return system
    parts = [
        (b.get("text", "") if isinstance(b, dict) else str(b))
        for b in system
    ]
    return "\n\n".join(p for p in parts if p)
