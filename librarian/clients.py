"""librarian/clients.py — 自包含的 Supabase / Anthropic 客户端 + 小工具。

故意【不】import scripts/_common: 本服务要独立部署到 Railway, 不该依赖 TV sync
脚本的目录布局。get_supabase / call_anthropic 与 scripts 里同名逻辑略有重复,
是刻意的 deploy 独立性取舍 (未来可抽一个共享小包)。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import relay_failover  # repo root, stdlib only (same home and reason as service_auth.py)
except ImportError:        # run as a script: sys.path[0] is the script's dir, the repo root is not on sys.path
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    import relay_failover  # noqa: E402

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


# prompt caching 降级计数 (2026-10-08 审计 C-02): 以前降级只打一行 warning 进 Railway stdout, 没人看;
# 于是"这个中转站根本不支持 cache_control、每次都在多付一倍 input token"这件事可以持续几个月。
# 进程内计数, /health 回显 (重启清零 —— 它答的是"这个实例最近有没有在降级", 不是历史总量)。
PROMPT_CACHE_FALLBACKS: dict = {"count": 0, "last_at": None, "last_error": ""}
# 实际缓存读写 (2026-10-12): 降级计数只抓得到"网关拒收 cache_control"; 网关静默丢掉标记、或轮转到不同上游
# 账号时它恒为 0。按 usage 累加, /health 回显 (同进程、重启清零)。判读见 scripts/annotate_essence_pass.py。
PROMPT_CACHE_USAGE: dict = {"calls": 0, "input": 0, "cache_write": 0, "cache_read": 0, "output": 0}


def _record_usage(msg) -> None:
    u = getattr(msg, "usage", None)
    if u is None:
        return
    PROMPT_CACHE_USAGE["calls"] += 1
    for key, attr in (("input", "input_tokens"), ("cache_write", "cache_creation_input_tokens"),
                      ("cache_read", "cache_read_input_tokens"), ("output", "output_tokens")):
        PROMPT_CACHE_USAGE[key] += int(getattr(u, attr, 0) or 0)


def _note_cache_fallback(exc: BaseException) -> None:
    PROMPT_CACHE_FALLBACKS["count"] += 1
    PROMPT_CACHE_FALLBACKS["last_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # 只记异常**类型**, 不记 str(exc): 这个 dict 会被没鉴权的 /health 原样回显, 而 SDK / 网关异常的文本里可能带
    # 请求 URL、租户路径、query 里的凭据 —— 它不经 SecretMaskingFormatter (codex review on #169, P1)。
    # 真正的错误文本在日志里 (那条过掩码)。
    PROMPT_CACHE_FALLBACKS["last_error"] = type(exc).__name__


def prompt_cache_enabled() -> bool:
    """要不要把带 ``cache_control`` 的 system 块原样发出去。D-113 (2026-10-16) 起默认【不发】, 压成纯字符串。
    理由同 scripts/annotate_essence_pass.prompt_cache_enabled: 中转站按请求轮转上游账号, 缓存写了读不回来,
    按官方计价反而更贵。换了能粘住同一上游账号的通道再设 ``PROMPT_CACHE_ENABLED=1``。"""
    return (os.environ.get("PROMPT_CACHE_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")


# ── 一次借阅在模型这头最多等多久 (审计 11-02 F09 / AU-F09) ─────────────────────
# 以前: SDK 自己重试 2 次 (默认) 套在这里的 3 次尝试外面, 单次默认限时 600 秒, 整轮没有上限 —— 中转站挂住的时候一次
# 冷借阅能拖上几分钟, 而写作台那头最多等 60 秒。现在重试只留 _run 这一层 (SDK 一律 max_retries=0), 单次限时, 整轮封顶。
CALL_TIMEOUT_S = 45.0       # 单次调用: 没配备用站时的主站、备用站
PRIMARY_TIMEOUT_S = 22.0    # 配了备用站时主站只等这么久就切 (原 30 秒, 是照夜跑定的; RELAY_PRIMARY_TIMEOUT_S 可改)。
#                             正常冷选卡 11-19 秒; 主站挂住时 22 + 备用站约 15 ≈ 37 秒拿到卡 (原来 45 秒)
REQUEST_BUDGET_S = 60.0     # 整轮 (各次尝试 + 切备用站 + 退避) 的上限。不许低于 60: 写作台 open_project 起的那次借阅在后台
#                             等满 60 秒, 慢的也要选完写进缓存, 接着来的 borrow_lessons 才拿得到卡
MIN_CALL_S = 10.0           # 整轮剩不到这么久就不再重试: 冷选卡最快也要 10 秒出头, 发了多半白付一次


def _mono() -> float:       # 整轮时限用的钟; 检查脚本会换掉它
    return time.monotonic()


def call_anthropic(prompt: str, model: str, *, system=None, max_tokens: int = 1500,
                   max_attempts: int = 3) -> str:
    """One Anthropic call with exponential-backoff retry on transient errors.

    时限 (AU-F09, 上面四个常数): 整轮最多 REQUEST_BUDGET_S; 每次调用的限时 = 调用点自己的上限和整轮剩下的时间里
    小的那个; 重试只在整轮还放得下一次完整尝试时才做 (配了备用站: 主站限时 + MIN_CALL_S; 没配: MIN_CALL_S)。

    Lazy-imports anthropic so --dry-run works without the SDK.

    ``system``: 可传 str, 或带 cache_control 的 block 列表 ``[{type,text,cache_control}]``
    以启用 Anthropic prompt caching(稳定大前缀缓存, 省 ~90% 成本/延迟)。

    支持中转站 / 第三方 API 网关: 若设了环境变量 ANTHROPIC_BASE_URL, 就作为 base_url
    传给 SDK(api_key 用 ANTHROPIC_API_KEY)。这跟 autowriter 的
    clients.get_anthropic_client 同一约定 —— 帆谷用中转站访问 Claude; 不设则走官方 endpoint。

    备用中转站 (D-148, relay_failover.py): ANTHROPIC_BASE_URL_BACKUP + ANTHROPIC_API_KEY_BACKUP 都配了才生效; 没配
    (或 RELAY_FORCE=primary) → 只打主站 (限时 CALL_TIMEOUT_S)。配了 → 每次尝试先打主站 (只给一次机会、限时
    PRIMARY_TIMEOUT_S), 超时 / 连不上 / 429 / 5xx / 401-404 → 这一次改打备用站 (限时 CALL_TIMEOUT_S); 连续 2 次失败 →
    熔断直接走备用站。「成功但慢」的门槛 (25 秒, RELAY_SLOW_S) 在主站限时 22 秒之下用不上 (超时先到), 把
    RELAY_PRIMARY_TIMEOUT_S 调到 25 以上才生效。
    """
    import anthropic  # lazy import

    deadline = _mono() + REQUEST_BUDGET_S

    def _left() -> float:
        return deadline - _mono()

    def _limit(site_s: float) -> float:
        return max(1.0, min(site_s, _left()))

    kwargs: dict = {"max_retries": 0}     # AU-F09: 重试只留 _run 一层
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        kwargs["api_key"] = api_key
    base_url = os.environ.get("ANTHROPIC_BASE_URL")  # 中转站; 空 = 官方 endpoint
    if base_url:
        kwargs["base_url"] = base_url
    relay_mode = relay_failover.mode()
    if relay_mode == relay_failover.MODE_PRIMARY_ONLY:
        client = anthropic.Anthropic(**kwargs, timeout=CALL_TIMEOUT_S)
        attempt_needs = MIN_CALL_S

        def _create(kw: dict):
            return client.messages.create(**kw, timeout=_limit(CALL_TIMEOUT_S))
    else:
        primary_timeout = relay_failover.primary_timeout_s(PRIMARY_TIMEOUT_S)
        slow = relay_failover.slow_s(25.0)
        # 一次尝试 = 主站 (最多 primary_timeout) + 可能切到备用站: 留得出这么多才重试, 切过去时备用站至少还有 MIN_CALL_S
        attempt_needs = MIN_CALL_S + (primary_timeout if relay_mode == relay_failover.MODE_AUTO else 0.0)
        built: dict = {}

        def _client(target: str):
            if target not in built:
                built[target] = (anthropic.Anthropic(**kwargs, timeout=primary_timeout) if target == "primary"
                                 else relay_failover.sdk_backup_client(anthropic, max_retries=0, timeout=CALL_TIMEOUT_S))
            return built[target]

        def _unit(target: str, kw: dict):
            site_s = primary_timeout if target == "primary" else CALL_TIMEOUT_S
            return _client(target).messages.create(**kw, timeout=_limit(site_s))

        def _create(kw: dict):
            return relay_failover.call(lambda target: _unit(target, kw),
                                       relay_mode=relay_mode, primary_url=base_url or "", slow_after_s=slow)
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
                msg = _create(create_kwargs)
                _record_usage(msg)
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
                pause = 2 ** (attempt + 1)
                if _left() - pause < attempt_needs:   # AU-F09: 整轮时限里放不下再来一次
                    raise
                time.sleep(pause)
        raise RuntimeError("call_anthropic exhausted retries without raising")

    if isinstance(system, list) and not prompt_cache_enabled():
        system = _flatten_system_blocks(system)   # D-113: 内容不变, 只去掉缓存标记
    try:
        return _run(system)
    except Exception as exc:
        # cache_control 降级:带 prompt caching 块的请求失败时,去掉 cache_control 用纯 system
        # 再试一次。很多中转站/转卖通道【不支持 Anthropic prompt caching】(透传 cache_control
        # 会 400/被通道吞)—— 这正是"同一通道 worker(纯 system)能跑、librarian(带缓存块)
        # 失败"的差异点。注:余额不足/鉴权/模型不存在这类错误,纯 system 也会同样失败 → 仍会
        # 抛出,不会被本降级掩盖(只损失缓存省钱,不改变内容/结果)。
        if isinstance(system, list) and _left() >= attempt_needs:
            _note_cache_fallback(exc)
            logger.warning(
                "带 cache_control 的馆员调用失败(%s: %s),去掉缓存块用纯 system 重试一次"
                "(疑似该中转站通道不支持 prompt caching; 本实例累计 %d 次, /health 的 config.prompt_cache_fallbacks 可查)",
                type(exc).__name__, str(exc)[:200], PROMPT_CACHE_FALLBACKS["count"],
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
