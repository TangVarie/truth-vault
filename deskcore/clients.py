"""deskcore/clients.py — 自包含的 Supabase / embedding / librarian 客户端。

故意【不】import scripts/_common 也不 import librarian/: 本服务要独立部署到
Railway。与 librarian/clients.py 的重复是刻意的 deploy 独立性取舍, 跟那边同一
个约定(见 librarian/clients.py 的模块 docstring)。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from datetime import datetime, timezone

logger = logging.getLogger("deskcore")

# autowriter 历史向量全部由 Gemini text-embedding-004 产出(768d), 存量在
# autowriter.versions.embedding。换模型会让全部历史向量作废需重算, 所以沿用。
EMBEDDING_MODEL = "text-embedding-004"
EMBEDDING_DIM = 768


def iso_now() -> str:
    """Aware-UTC ISO。deskcore 新建的表都是 TIMESTAMPTZ, 与 truth_vault 的
    naive TIMESTAMP 约定不同 —— 这里【必须】带时区, 别照抄 librarian 的 iso_now。
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Supabase ─────────────────────────────────────────────────────────

def get_supabase():
    """service_role client, schema 固定指向 autowriter。

    ClientOptions(schema='autowriter') 让所有 .table(...) 透明指向 autowriter
    schema —— 这是 autowriter 仓 get_client() 的同款做法(RUNBOOK.md:85-92)。
    不设的话会写到不存在的 public.items 并返回 404。
    """
    from supabase import create_client  # lazy import
    from supabase.client import ClientOptions

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    if key.startswith("sb_publishable_") or "anon" in key.lower():
        raise RuntimeError(
            "SUPABASE_SERVICE_ROLE_KEY looks like a publishable/anon key; "
            "deskcore needs a service_role secret."
        )
    return create_client(url, key, options=ClientOptions(schema="autowriter"))


def get_supabase_public():
    """同一个库但 schema=public —— 只用于读 truth_vault 的看板视图(如果需要)。

    默认不用; 飞轮经验卡走 librarian HTTP, 不直连 truth_vault。
    """
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    return create_client(url, key)


# ── Embedding (Gemini) ───────────────────────────────────────────────

_genai_client = None
_genai_tried = False


def _get_genai():
    """单例 Gemini client; 未配 GOOGLE_API_KEY 或 SDK 缺失时返回 None。"""
    global _genai_client, _genai_tried
    if _genai_tried:
        return _genai_client
    _genai_tried = True
    key = os.environ.get("GOOGLE_API_KEY")
    if not key:
        logger.warning("GOOGLE_API_KEY not set; semantic dedup will fall back to deterministic only")
        return None
    try:
        from google import genai  # lazy import
        _genai_client = genai.Client(api_key=key)
    except Exception:
        logger.exception("failed to construct genai client")
        _genai_client = None
    return _genai_client


def embeddings_available() -> bool:
    return _get_genai() is not None


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """一次拿一批 embedding; 失败返回 None(调用方降级到确定性查重)。

    输入截到 1024 字 —— 标题和开头都远小于这个, 防畸形正文撑爆单次 payload。
    """
    if not texts:
        return []
    client = _get_genai()
    if client is None:
        return None
    safe = [(t or "")[:1024] for t in texts]
    try:
        resp = client.models.embed_content(model=EMBEDDING_MODEL, contents=safe)
    except Exception:
        logger.exception("embed_content failed")
        return None
    try:
        out: list[list[float]] = []
        for e in resp.embeddings:
            vals = getattr(e, "values", None) or getattr(e, "embedding", None)
            if vals is None:
                return None
            out.append(list(vals))
        return out
    except Exception:
        logger.exception("failed to unpack embeddings response")
        return None


def cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度; 退化输入返回 0.0。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na ** 0.5 * nb ** 0.5)


# ── 文本指纹 (确定性, 不依赖任何外部服务) ─────────────────────────────

_PUNCT_RE = re.compile(r"[\s，。！？、；：""''《》（）()\[\]…—~·,.!?;:'\"\-_/\\|+*#@$%^&]+")


def normalize_text(text: str) -> str:
    """去标点空白后的规范化串, 用于确定性比对。"""
    return _PUNCT_RE.sub("", text or "")


def opening_of(body: str, n: int = 25) -> str:
    """正文首个非空行前 n 字 —— 与 autowriter db.py:1583 的口径一致。"""
    for line in (body or "").splitlines():
        s = line.strip()
        if s:
            return s[:n]
    return ""


def sha16(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def ngram_hashes(text: str, n: int = 4, cap: int = 200) -> list[str]:
    """正文 n 字 shingle 的 hash 集合(去重、有上限)。

    对齐 human-writing/scripts/check_prose.py 的跨篇四字串检测: 两篇共享大量
    四字串 = 模板化, 哪怕换了词也能抓出来。cap 是防长文把行撑爆。
    """
    norm = normalize_text(text)
    if len(norm) < n:
        return []
    grams = {norm[i:i + n] for i in range(len(norm) - n + 1)}
    hashed = sorted(sha16(g) for g in grams)
    if len(hashed) <= cap:
        return hashed
    # 均匀采样而不是取前 cap 个 —— 取前 N 会让所有长文只比开头。
    step = len(hashed) / cap
    return [hashed[int(i * step)] for i in range(cap)]


# ── librarian 转调 ───────────────────────────────────────────────────

def fetch_flywheel_lessons(brief: dict, timeout: float | None = None) -> list[dict]:
    """向 TV 馆员借经验卡。任何异常/超时/未配 → []（绝不阻塞写稿）。

    这是 docs/19 的「降级铁律」: 空库/出错一律给可用结构, 消费方当"这次没
    飞轮料"处理。但【每次降级必须留痕】—— docs/19:180-200 记过一次事故:
    librarian 模型 env 变量名配错, 每次 LLM 调用失败被 except 吞掉降级成 [],
    外面看永远是 200, 查了很久。
    """
    import httpx  # lazy import

    url = os.environ.get("LIBRARIAN_URL")
    key = os.environ.get("LIBRARIAN_API_KEY")
    if not url:
        logger.info("LIBRARIAN_URL not set; skipping flywheel lessons")
        return []
    # 默认 20s 而不是 aw 那边的 8s —— docs/22:54 记过 8 秒偏小, 覆盖不了
    # 缓存未命中时的 LLM 选卡 + 冷启动。
    if timeout is None:
        timeout = float(os.environ.get("LIBRARIAN_TIMEOUT_SEC", "20"))
    headers = {"content-type": "application/json"}
    if key:
        headers["X-Librarian-Key"] = key
    try:
        resp = httpx.post(
            url.rstrip("/") + "/librarian",
            json=brief, headers=headers, timeout=timeout,
        )
        if resp.status_code != 200:
            logger.warning("librarian returned HTTP %s: %s",
                           resp.status_code, resp.text[:200])
            return []
        data = resp.json()
    except Exception:
        logger.exception("librarian call failed; returning [] (writing continues)")
        return []
    selected = data.get("selected") if isinstance(data, dict) else None
    if not isinstance(selected, list):
        logger.warning("librarian returned unexpected shape: %r", type(selected))
        return []
    return selected


def librarian_reachable() -> tuple[bool, str]:
    """给 /health 用: librarian 通不通。返回 (ok, 说明)。"""
    import httpx

    url = os.environ.get("LIBRARIAN_URL")
    if not url:
        return False, "LIBRARIAN_URL not set"
    try:
        r = httpx.get(url.rstrip("/") + "/health", timeout=5.0)
        return r.status_code == 200, f"HTTP {r.status_code}"
    except Exception as exc:
        return False, str(exc)[:120]


# ── Anthropic (调校笔记萃取用) ────────────────────────────────────────

def call_anthropic(prompt: str, model: str, *, system=None,
                   max_tokens: int = 2000, max_attempts: int = 3) -> str:
    """一次 Anthropic 调用 + 指数退避重试。走中转站(ANTHROPIC_BASE_URL)。

    ⚠️ 模型 env 用 DESKCORE_MODEL —— 三个 Railway 服务的模型变量名各不相同
    (worker=ESSENCE_MODEL / librarian=FLYWHEEL_LIBRARIAN_MODEL /
    autowriter=CLAUDE_MODEL), 已经害过一次(docs/19:180-200)。/health 会回显
    实际解析到的模型名, 让配错当场可见。
    """
    import anthropic  # lazy import

    kwargs: dict = {}
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        kwargs["api_key"] = api_key
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
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

    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            params: dict = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system:
                params["system"] = system
            resp = client.messages.create(**params)
            return "".join(
                getattr(b, "text", "") for b in resp.content
                if getattr(b, "type", "") == "text"
            )
        except Exception as exc:  # noqa: BLE001 — 要按内容判 transient
            last_exc = exc
            status = getattr(exc, "status_code", None)
            msg = str(exc).lower()
            transient = (
                isinstance(exc, retryable)
                or status in (429, 502, 503, 504, 529)
                or "timeout" in msg or "connection" in msg or "overloaded" in msg
            )
            if not transient or attempt == max_attempts - 1:
                raise
            time.sleep(2 ** (attempt + 1))
    raise last_exc  # pragma: no cover — 循环必然 return 或 raise
