"""librarian/clients.py — 自包含的 Supabase / Anthropic 客户端 + 小工具。

故意【不】import scripts/_common: 本服务要独立部署到 Railway, 不该依赖 TV sync
脚本的目录布局。get_supabase / call_anthropic 与 scripts 里同名逻辑略有重复,
是刻意的 deploy 独立性取舍 (未来可抽一个共享小包)。
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone


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


def call_anthropic(prompt: str, model: str, *, max_tokens: int = 1500,
                   max_attempts: int = 3) -> str:
    """One Anthropic call with exponential-backoff retry on transient errors.

    Lazy-imports anthropic so --dry-run works without the SDK. Mirrors the
    retry policy in scripts/annotate_essence_pass.call_claude (kept separate
    for deploy independence).
    """
    import anthropic  # lazy import

    client = anthropic.Anthropic()
    retryable = tuple(
        c for c in (
            getattr(anthropic, "RateLimitError", None),
            getattr(anthropic, "APIConnectionError", None),
            getattr(anthropic, "APITimeoutError", None),
            getattr(anthropic, "InternalServerError", None),
        ) if c is not None
    )
    for attempt in range(max_attempts):
        try:
            msg = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(
                b.text for b in msg.content if getattr(b, "type", None) == "text"
            )
        except Exception as exc:
            transient = (
                (retryable and isinstance(exc, retryable))
                or any(s in str(exc).lower()
                       for s in ("429", "503", "504", "timeout", "connection"))
            )
            if not transient or attempt == max_attempts - 1:
                raise
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError("call_anthropic exhausted retries without raising")
