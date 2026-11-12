#!/usr/bin/env python3
"""CI 守卫: 备用中转站 (D-148, 仓库根 relay_failover.py) —— 没配备用站时行为一字不变; 配了时主站出事自动切。

由 check_prompt_cache_fallback.py 用子进程跑 (ci.yml 那一步原样不动), 也可以单独跑。假的 anthropic 模块、
假地址 (*.invalid)、假 key, 不碰网络、不读真 secret。

  §1 共享核心 (spec §16 C1-C12): 模式表 · 数值解析 · 切不切的判据 · describe · 熔断文件名 · 熔断状态机 ·
     坏文件 / 写不了 · 多进程计数 · call() · summary / health 的键
  §2 没配备用站 (四种配置) = 老路: 客户端构造参数、请求参数、重试次数一字不变; 不建熔断文件、不计数、不出日志
     (馆员例外, AU-F09: 没配也是 SDK max_retries=0 + 单次限时 45 秒; 自己那层 3 次重试不变)
  §3 essence call_claude 切换: 主站超时 → 备用站; 主站 / 备用站各自的构造参数; 该切的状态码切、400 类不切;
     缓存块被拒 (400) 不切
  §4 D-125 中转站敏感词拦截: 不切、不算熔断失败、原异常原样抛 (特征层照旧判 gateway_filtered)
  §5 熔断跨调用: 连续 2 次失败 → 直接走备用; 冷却后试一次主站, 好了合上、不好再开; 慢 (>25 秒) 也算失败
  §6 RELAY_FORCE: backup = 只走备用 / 没配备用站时 backup 不生效 + 一行提示 / 认不出的值 = 自动 + 一行提示
  §7 librarian call_anthropic 切换 (主站限时 22 秒, 备用站 45 秒, 都是 max_retries=0) + 整轮时限 60 秒 (AU-F09):
     主站挂住 → 第 22 秒切、备用站拿剩下的 38 秒; 两边都挂 → 第 60 秒抛、不再试; 快失败照旧试 3 次;
     整轮放不下一次完整尝试 (主站 22 + 10) 就不重试; 没配备用站: 45 秒 + 剩下的 13 秒; 缓存块降级也不许超出整轮
     RELAY_PRIMARY_TIMEOUT_S 超过 40 按 40 (整轮 60 - 2 × 10): 调到 55 / 600 也照旧重试、照旧降级、备用站还有 20 秒;
     主站 25.5 秒才答完的在 22 秒被切 (调到 30 才等得到); 限时按「没有新字节」算, 一直滴字节的调用不封顶 (README 写明)
  §8 onboarder call_anthropic: 流式中途断 → 整段在备用站重来 (不拼半截; 含真 SDK 原样抛的 httpx ReadTimeout /
     RemoteProtocolError); 524 也切; 非流式限时 600 秒
  §9 三个服务的 /health 带 relay 块: 只有布尔 / 枚举 / 计数, 不漏备用站地址或任何 key; 出错也不 500;
     馆员多一个 select 块 (AU-F09): 在飞合并计数 + 现在生效的三个时限
  §10 日志卫生: 以上全部日志 + 退出汇总行里没有地址、key、中转站报错原文
  §11 Done 行: essence / 特征层 / 策展 / 评论归线 只在配了备用站时带 relay 汇总
  §12 脚本直接跑 (仓库根不在 sys.path) 也 import 得到 relay_failover
"""
from __future__ import annotations

import contextlib
import http.client
import inspect
import io
import json
import logging
import os
import re
import ssl
import subprocess
import sys
import tempfile
import time
import types
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

P = "https://primary-host.invalid"
BU = "https://backup-host.invalid"
K = "sk-test-primary-0123456789"
BK = "sk-test-backup-0123456789"
HK = "sk-test-backup-haiku-0123456789"   # 备用站 Haiku 专用通道钥匙 (D-148 补)
SENTINEL = "BALANCE-SENTINEL-余额"
LEAKS = ("primary-host.invalid", "backup-host.invalid", K, BK, HK, "BALANCE-SENTINEL")
BASE = {"ANTHROPIC_API_KEY": K, "ANTHROPIC_BASE_URL": P}
BOTH = {"ANTHROPIC_BASE_URL_BACKUP": BU, "ANTHROPIC_API_KEY_BACKUP": BK}


def _scrub_env() -> None:
    for k in list(os.environ):
        if k.startswith(("ANTHROPIC_", "RELAY_")) or k in ("PROMPT_CACHE_ENABLED", "ONBOARDER_STREAM"):
            os.environ.pop(k, None)


_scrub_env()   # 开发机上的真 key / 真地址 / RELAY_FORCE 不许影响本检查

# ── 假 anthropic 模块 ──────────────────────────────────────────────────────

A = types.ModuleType("anthropic")


class APIError(Exception):
    pass


class APIConnectionError(APIError):
    def __init__(self, message: str | None = None):
        super().__init__(message or f"Connection error. {SENTINEL}")


class APITimeoutError(APIConnectionError):
    def __init__(self, message: str | None = None):
        super().__init__(message or f"Request timed out. {SENTINEL}")


_ETYPE = {400: "invalid_request_error", 401: "authentication_error", 402: "billing_error",
          403: "permission_error", 404: "not_found_error", 408: "timeout_error", 413: "request_too_large",
          429: "rate_limit_error", 529: "overloaded_error"}


class APIStatusError(APIError):
    def __init__(self, status_code: int, message: str = "", error_type: str | None = None):
        super().__init__(f"Error code: {status_code} - {message} {SENTINEL}")
        self.status_code = status_code
        et = error_type or _ETYPE.get(status_code) or ("api_error" if status_code >= 500 else "invalid_request_error")
        self.body = {"type": "error", "error": {"type": et, "message": f"{message} {SENTINEL}"}}


class BadRequestError(APIStatusError):
    pass


class RateLimitError(APIStatusError):
    pass


class InternalServerError(APIStatusError):
    pass


# 真 SDK 流开了之后读到一半卡住 / 断开时, 抛的是 httpx 的原样异常 (实测 anthropic 0.103.1), 不是 APITimeoutError。
# 假的同名层级 (类名和 httpx 一样), 核心按类名判、onboarder 按 MRO 里的 TransportError 认。
class TransportError(Exception):
    pass


class TimeoutException(TransportError):
    pass


class ReadTimeout(TimeoutException):
    pass


class ProtocolError(TransportError):
    pass


class RemoteProtocolError(ProtocolError):
    pass


def status_exc(st: int, message: str = "") -> APIStatusError:
    cls = (BadRequestError if st == 400 else RateLimitError if st == 429
           else InternalServerError if st >= 500 else APIStatusError)
    return cls(st, message)


BUILT: list = []        # 每次 Anthropic(**kw) 的 kw, 按顺序
INSTANCES: list = []
CALLS: list = []        # (relay, "create"|"stream", kwargs)
SCRIPT: dict = {"primary": [], "backup": []}
DEFAULT_TEXT = {"primary": "text-from-primary", "backup": "text-from-backup"}
CLOCK = [0.0]           # relay_failover._mono
NOW = [1_800_000_000.0]  # relay_failover._now


def _relay_of(kw: dict) -> str:
    return "backup" if kw.get("base_url") == BU else "primary"


def _next(relay: str, kw: dict):
    q = SCRIPT[relay]
    out = q.pop(0) if q else DEFAULT_TEXT[relay]
    if callable(out) and not isinstance(out, BaseException):
        out = out(kw)
    return out


def slow(seconds: float, text: str):
    def f(_kw):
        CLOCK[0] += seconds
        return text
    return f


class _Msg:
    def __init__(self, text: str):
        self.content = [types.SimpleNamespace(type="text", text=text)]
        self.stop_reason = "end_turn"
        self.usage = types.SimpleNamespace(input_tokens=10, cache_creation_input_tokens=0,
                                           cache_read_input_tokens=0, output_tokens=5)


class _Stream:
    def __init__(self, chunks, exc):
        self._chunks, self._exc = list(chunks), exc

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def text_stream(self):
        def gen():
            yield from self._chunks
            if self._exc is not None:
                raise self._exc
        return gen()


class _Messages:
    def __init__(self, relay: str):
        self.relay = relay

    def create(self, **kw):
        CALLS.append((self.relay, "create", kw))
        out = _next(self.relay, kw)
        if isinstance(out, BaseException):
            raise out
        if isinstance(out, tuple):
            chunks, exc = out
            if exc is not None:
                raise exc
            out = "".join(chunks)
        return _Msg(out)

    def stream(self, **kw):
        CALLS.append((self.relay, "stream", kw))
        out = _next(self.relay, kw)
        if isinstance(out, BaseException):
            raise out                      # 开流就失败 (状态码 / 连不上)
        if isinstance(out, tuple):
            return _Stream(*out)           # (chunks, 中途抛的异常 or None)
        half = len(out) // 2
        return _Stream([out[:half], out[half:]], None)


class _Anthropic:
    def __init__(self, **kw):
        BUILT.append(dict(kw))
        INSTANCES.append(self)
        self.relay = _relay_of(kw)
        self.auth_token = "tok-from-env"   # 新版 SDK 会从 ANTHROPIC_AUTH_TOKEN 读; 备用站客户端必须清掉
        self.messages = _Messages(self.relay)


for _n, _o in dict(Anthropic=_Anthropic, APIError=APIError, APIConnectionError=APIConnectionError,
                   APITimeoutError=APITimeoutError, APIStatusError=APIStatusError, BadRequestError=BadRequestError,
                   RateLimitError=RateLimitError, InternalServerError=InternalServerError).items():
    setattr(A, _n, _o)
sys.modules["anthropic"] = A

# ── 日志捕获 (根 logger, DEBUG) ────────────────────────────────────────────


class _Cap(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records: list = []

    def emit(self, record):
        self.records.append(record)


CAP = _Cap()
logging.getLogger().addHandler(CAP)
logging.getLogger().setLevel(logging.DEBUG)


def mark() -> int:
    return len(CAP.records)


def relay_lines(since: int = 0) -> list[str]:
    return [r.getMessage() for r in CAP.records[since:] if r.name == "relay"]


def all_log_text() -> str:
    out = []
    for r in CAP.records:
        try:
            out.append(r.getMessage())
        except Exception:  # noqa: BLE001
            out.append(str(r.msg))
    return "\n".join(out)


# ── 被测模块 ───────────────────────────────────────────────────────────────

import relay_failover as R  # noqa: E402
import _common  # noqa: E402
import annotate_essence_pass as E  # noqa: E402
from librarian import clients as LC  # noqa: E402
from onboarder import clients as OC  # noqa: E402

PO, AUTO, BO = R.MODE_PRIMARY_ONLY, R.MODE_AUTO, R.MODE_BACKUP_ONLY


class _NoSleep:
    """被测模块里的 time: sleep 不睡 (只记下来), 其余照旧。"""

    def __init__(self):
        self.sleeps: list = []

    def sleep(self, s):
        self.sleeps.append(s)

    def __getattr__(self, name):
        return getattr(time, name)


class _TickSleep(_NoSleep):
    """馆员的 time: sleep 不睡, 但把假钟拨过去 —— 整轮时限 (AU-F09) 把退避也算在内。"""

    def sleep(self, s):
        super().sleep(s)
        CLOCK[0] += s


NOSLEEP = _NoSleep()
for _m in (E, OC):
    _m.time = NOSLEEP
TICK = _TickSleep()
LC.time = TICK

_BASE_TMP = tempfile.TemporaryDirectory(prefix="relay_check_")
_SECTION = [0]
STDERR = io.StringIO()
EXTRA_TEXT: list[str] = []   # 子进程 stderr 之类, 一并查卫生
FAILS: list[str] = []


def _show(msg: str) -> str:
    """打到 CI 输出的说明里也不带假地址 / 假 key 原文 (换成 P / BU / K / BK), 免得被当成真值看。"""
    for raw, alias in ((HK, "HK"), (K, "K"), (BK, "BK"), (P, "P"), (BU, "BU")):
        msg = msg.replace(raw, alias)
    return msg


def check(cond, msg: str) -> bool:
    msg = _show(msg)
    if cond:
        print(f"  ✓ {msg}")
    else:
        print(f"  ❌ {msg}")
        FAILS.append(msg)
    return bool(cond)


def fresh(**env) -> str:
    """每个小节一个干净现场: env、计数、warn-once、熔断状态 (新的临时目录)、假客户端记录、两个钟。"""
    _scrub_env()
    for k, v in env.items():
        os.environ[k] = v
    R._reset_for_tests()
    _SECTION[0] += 1
    d = os.path.join(_BASE_TMP.name, f"s{_SECTION[0]}")
    os.makedirs(d, exist_ok=True)
    tempfile.tempdir = d
    BUILT.clear()
    INSTANCES.clear()
    CALLS.clear()
    SCRIPT["primary"].clear()
    SCRIPT["backup"].clear()
    CLOCK[0] = 0.0
    NOW[0] = 1_800_000_000.0
    R._mono = lambda: CLOCK[0]
    R._now = lambda: NOW[0]
    LC._mono = lambda: CLOCK[0]      # 馆员整轮时限的钟 (AU-F09) 和核心用同一只假钟
    TICK.sleeps.clear()
    return d


def breaker_files(d: str | None = None) -> list[str]:
    d = d or tempfile.gettempdir()
    return sorted(n for n in os.listdir(d) if n.startswith("relay_breaker_"))


def raises(fn):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        return exc
    return None


def zero_counts() -> dict:
    return dict.fromkeys(R.COUNTER_KEYS, 0)


def counts_with(**kw) -> dict:
    return {**zero_counts(), **kw}


def relays_built() -> list[str]:
    return [_relay_of(b) for b in BUILT]


# ── §1 共享核心 ───────────────────────────────────────────────────────────

def sec1_core() -> None:
    print("§1 共享核心 (C1-C12)")
    # C1 模式表
    def mode_with(**env):
        fresh(**env)
        return R.mode()

    check(mode_with() == PO, "C1 都没配 → primary_only")
    check(mode_with(ANTHROPIC_BASE_URL_BACKUP=BU) == PO, "C1 只配了备用地址 → primary_only")
    check(mode_with(ANTHROPIC_API_KEY_BACKUP=BK) == PO, "C1 只配了备用 key → primary_only")
    check(mode_with(ANTHROPIC_BASE_URL_BACKUP="   ", ANTHROPIC_API_KEY_BACKUP=BK) == PO, "C1 备用地址全是空白 → primary_only")
    check(mode_with(ANTHROPIC_BASE_URL_BACKUP=BU, ANTHROPIC_API_KEY_BACKUP=" \t") == PO, "C1 备用 key 全是空白 → primary_only")
    check(mode_with(**BOTH) == AUTO, "C1 两个都配 → auto")
    check(mode_with(**BOTH, RELAY_FORCE="AUTO ") == AUTO, "C1 RELAY_FORCE='AUTO ' → auto")
    check(mode_with(**BOTH, RELAY_FORCE="primary") == PO, "C1 RELAY_FORCE=primary → primary_only")
    check(mode_with(**BOTH, RELAY_FORCE=" Backup") == BO, "C1 RELAY_FORCE=' Backup' → backup_only")
    fresh(RELAY_FORCE="backup")
    m = mark()
    got = (R.mode(), R.mode())
    warn = [x for x in relay_lines(m) if x == "relay: RELAY_FORCE=backup but no backup relay is configured; using primary"]
    check(got == (PO, PO) and len(warn) == 1, f"C1 没配备用站却 RELAY_FORCE=backup → primary_only + 只提示一次 ({got}, {len(warn)} 行)")
    fresh(**BOTH, RELAY_FORCE="zzz")
    m = mark()
    got = (R.mode(), R.mode())
    warn = [x for x in relay_lines(m) if "RELAY_FORCE not recognized" in x]
    check(got == (AUTO, AUTO) and len(warn) == 1, "C1 RELAY_FORCE=zzz → auto + 只提示一次")
    fresh()
    check(R.mode(configured=True) == AUTO and R.mode(configured=False) == PO, "C1 mode(configured=) 由调用方给 (Jev 用)")

    # C2 数值解析
    for raw, want in [("", 60.0), ("20", 20.0), ("1", 5.0), ("9999", 600.0), ("abc", 60.0), ("nan", 60.0)]:
        fresh(RELAY_PRIMARY_TIMEOUT_S=raw)
        got = R.primary_timeout_s(60.0)
        check(got == want and isinstance(got, float), f"C2 RELAY_PRIMARY_TIMEOUT_S={raw!r} → {want} (得到 {got})")
    for raw, want in [("2.5", 2), ("0", 1), ("50", 20), ("", 2), ("3", 3)]:
        fresh(RELAY_BREAKER_FAILS=raw)
        got = R.breaker_fails()
        check(got == want and isinstance(got, int), f"C2 RELAY_BREAKER_FAILS={raw!r} → {want} (得到 {got})")
    for raw, want in [("10", 30.0), ("", 1200.0), ("100000", 86400.0)]:
        fresh(RELAY_BREAKER_COOLDOWN_S=raw)
        check(R.breaker_cooldown_s() == want, f"C2 RELAY_BREAKER_COOLDOWN_S={raw!r} → {want}")
    for raw, want in [("0", 0.0), ("-5", 0.0), ("", 25.0), ("700", 600.0)]:
        fresh(RELAY_SLOW_S=raw)
        check(R.slow_s(25.0) == want, f"C2 RELAY_SLOW_S={raw!r} → {want}")

    # C3 切不切
    fresh()
    yes = [(f"HTTP {s}", status_exc(s)) for s in
           (401, 402, 403, 404, 408, 409, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524, 529)]
    yes += [("APITimeoutError", APITimeoutError()), ("APIConnectionError", APIConnectionError()),
            ("TimeoutError", TimeoutError()), ("ConnectionResetError", ConnectionResetError()),
            ("URLError (非 HTTP)", urllib.error.URLError(ConnectionRefusedError())),
            ("RemoteDisconnected", http.client.RemoteDisconnected("x")),
            ("IncompleteRead", http.client.IncompleteRead(b"")), ("SSLError", ssl.SSLError()),
            ("JSONDecodeError", json.JSONDecodeError("x", "<html>", 0)),
            ("HTTPError 503 (code 属性)", urllib.error.HTTPError(P + "/v1/messages", 503, "x", {}, None))]
    st200 = APIError(f"stream error {SENTINEL}")
    st200.status_code = 200
    st200.body = {"type": "error", "error": {"type": "overloaded_error"}}
    yes.append(("HTTP 200 + error.type=overloaded_error", st200))
    bad = [label for label, exc in yes if not R.is_failover_worthy(exc)]
    check(not bad, f"C3 该切的都切: {len(yes)} 种" + (f" —— 漏了 {bad}" if bad else ""))
    no = [(f"HTTP {s}", status_exc(s)) for s in (400, 405, 413, 415, 422)]
    no += [("ValueError", ValueError("x")), ("KeyError", KeyError("x")),
           ("RuntimeError('connection timeout')", RuntimeError("connection timeout")),
           ("HTTPError 400", urllib.error.HTTPError(P, 400, "x", {}, None))]
    filtered_timeout = APITimeoutError(f"sensitive_words_detected {SENTINEL}")
    no += [("500 sensitive_words_detected", InternalServerError(500, "sensitive_words_detected")),
           ("529 sensitive_words_detected", InternalServerError(529, "sensitive_words_detected")),
           ("APITimeoutError sensitive_words_detected", filtered_timeout)]
    bad = [label for label, exc in no if R.is_failover_worthy(exc)]
    check(not bad, f"C3 不该切的都不切 (含 D-125 敏感词, 不按报错文字猜): {len(no)} 种" + (f" —— 错切了 {bad}" if bad else ""))
    check(R.status_of(types.SimpleNamespace(status_code=True)) is None and R.status_of(types.SimpleNamespace(code=99)) is None,
          "C3 status_of 不收 bool / 越界")

    # C4 describe
    d = (R.describe(status_exc(529)), R.describe(APITimeoutError()), R.describe(status_exc(401)))
    check(d == ("HTTP 529 overloaded_error", "APITimeoutError", "HTTP 401"), f"C4 describe 只出状态码 / 类名 / error.type: {d}")

    # C5 熔断文件名
    a = {R.state_path(u) for u in (P + "/", P + "/v1", f" {P}/v1/ ", P)}
    check(len(a) == 1, "C5 同一主站的几种写法 (尾斜杠 / /v1 / 空白) 落同一个文件")
    check(R.state_path("https://other-host.invalid") not in a, "C5 换主站 → 换文件")
    name = os.path.basename(next(iter(a)))
    check("primary-host" not in name and "http" not in name and re.fullmatch(r"relay_breaker_[0-9a-f]{16}\.json", name),
          f"C5 文件名里没有地址: {name}")
    check(R.state_path("") == R.state_path(None) == R.state_path(R.OFFICIAL_BASE_URL), "C5 没设主站 = 官方地址那个文件")

    # C6 熔断状态机
    fresh(**BOTH)
    path = R.state_path(P)
    m = mark()
    R._record(path, "fail", False, "HTTP 503")
    check(R.breaker_state(P) == "closed", "C6 1 次失败: 还合着")
    R._record(path, "fail", False, "HTTP 503")
    check(R.breaker_state(P) == "open", "C6 连续 2 次失败: 熔断")
    opens = [x for x in relay_lines(m) if x == "relay: breaker open for 1200s after 2 consecutive primary failures "
                                               "(last: HTTP 503); calls go straight to backup"]
    check(len(opens) == 1, "C6 熔断打一行 (原样)")
    with open(path, encoding="utf-8") as f:
        st = json.load(f)
    check(st == {"v": 1, "fails": 2, "opened_at": NOW[0], "probe_at": None}, f"C6 文件内容只有计数和时间: {st}")
    check(R._decide(path, 1200.0) == "skip", "C6 熔断期间: skip")
    NOW[0] += 1199
    check(R._decide(path, 1200.0) == "skip", "C6 冷却差 1 秒: 仍 skip")
    NOW[0] += 1
    check(R.breaker_state(P) == "half_open", "C6 到点: half_open")
    check((R._decide(path, 1200.0), R._decide(path, 1200.0)) == ("probe", "skip"), "C6 half_open: 第一个去试主站, 第二个 skip")
    NOW[0] += 601
    check(R._decide(path, 1200.0) == "probe", "C6 试探认领 600 秒过期 → 再放一个")
    m = mark()
    R._record(path, "ok", True, "")
    check(R.breaker_state(P) == "closed" and "relay: breaker closed (primary ok again)" in relay_lines(m),
          "C6 试探成功: 合上 + 打一行")
    R._record(path, "fail", False, "x")
    R._record(path, "fail", False, "x")
    NOW[0] += 1300
    check(R._decide(path, 1200.0) == "probe", "C6 再次熔断后到点 → probe")
    R._record(path, "fail", True, "HTTP 529 overloaded_error")
    st = R._load(path)
    check(R.breaker_state(P) == "open" and st["opened_at"] == NOW[0] and st["probe_at"] is None,
          "C6 试探失败: 重新熔断, opened_at 换成现在")
    NOW[0] += 1300
    first = (R._decide(path, 1200.0), R._decide(path, 1200.0))
    R._record(path, "neutral", True, "")
    check(first == ("probe", "skip") and R._decide(path, 1200.0) == "probe", "C6 试探遇到不切的错误 (neutral): 放掉认领")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"v": 1, "fails": 2, "opened_at": NOW[0] + 1000, "probe_at": None}, f)
    check(R.breaker_state(P) == "half_open" and R._decide(path, 1200.0) == "probe", "C6 opened_at 在未来 (钟漂 / 坏数据) → half_open")
    fresh(**BOTH, RELAY_BREAKER_FAILS="1")
    R._record(R.state_path(P), "fail", False, "x")
    check(R.breaker_state(P) == "open", "C6 RELAY_BREAKER_FAILS=1: 1 次就熔断")
    fresh(**BOTH)
    path = R.state_path(P)
    R._record(path, "fail", False, "x")
    R._record(path, "ok", False, "")
    R._record(path, "fail", False, "x")
    check(R.breaker_state(P) == "closed", "C6 中间成功一次 = 计数清零 (要「连续」2 次)")

    # C7 坏文件
    for content in ("{x", "[]", '{"v":2}', '{"v":1,"fails":"x","opened_at":"y"}', ""):
        fresh(**BOTH)
        path = R.state_path(P)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        ok_closed = R.breaker_state(P) == "closed"
        R._record(path, "fail", False, "x")
        try:
            with open(path, encoding="utf-8") as f:
                st = json.load(f)
        except Exception:  # noqa: BLE001
            st = None
        check(ok_closed and isinstance(st, dict) and st.get("v") == 1 and st.get("fails") == 1,
              f"C7 坏文件 {content!r}: 当合着读, 下次写回合法 JSON")
    fresh(**BOTH)
    tempfile.tempdir = os.path.join(_BASE_TMP.name, "does-not-exist", "x")
    path = R.state_path(P)
    e = raises(lambda: (R._record(path, "fail", False, "x"), R._record(path, "fail", False, "x")))
    check(e is None and R.breaker_state(P) == "open" and not os.path.exists(path),
          "C7 临时目录写不了: 不抛, 用本进程内存里的状态")

    # C8 多进程
    d = fresh(**BOTH)
    path = R.state_path(P)
    code = ("import sys; sys.path.insert(0, %r)\nimport relay_failover as R\n"
            "for _ in range(50):\n    R._record(R.state_path(%r), 'fail', False, 'HTTP 503')\n") % (str(ROOT), P)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC_", "RELAY_"))}
    env["TMPDIR"] = d
    procs = [subprocess.Popen([sys.executable, "-c", code], env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True) for _ in range(4)]
    outs = [p.communicate(timeout=120) for p in procs]
    EXTRA_TEXT.extend(o + e for o, e in outs)
    rcs = [p.returncode for p in procs]
    try:
        with open(path, encoding="utf-8") as f:
            st = json.load(f)
    except Exception as exc:  # noqa: BLE001
        st = {"error": type(exc).__name__}
    check(rcs == [0, 0, 0, 0] and st.get("fails") == 200, f"C8 4 个进程 × 50 次失败 = 200 (得到 {st.get('fails')}, rc={rcs})")
    opened_lines = sum(e.count("relay: breaker open for") for _o, e in outs)
    check(opened_lines == 1, f"C8 跨进程只熔断一次 ({opened_lines} 行)")

    # C9 call()
    def make_unit(outcomes: dict, seen: list):
        def unit(target):
            seen.append(target)
            out = outcomes[target].pop(0) if outcomes[target] else f"{target}-result"
            if callable(out) and not isinstance(out, BaseException):
                out = out(None)
            if isinstance(out, BaseException):
                raise out
            return out
        return unit

    fresh(**BOTH)
    seen: list = []
    r = R.call(make_unit({"primary": [], "backup": []}, seen), relay_mode=AUTO, primary_url=P, slow_after_s=25.0)
    check(r == "primary-result" and seen == ["primary"] and R.counts() == counts_with(primary_ok=1), "C9 主站快速成功")
    fresh(**BOTH)
    seen = []
    u = make_unit({"primary": [slow(26, "slow-1"), slow(26, "slow-2")], "backup": []}, seen)
    r1 = R.call(u, relay_mode=AUTO, primary_url=P, slow_after_s=25.0)
    state1 = R.breaker_state(P)
    r2 = R.call(u, relay_mode=AUTO, primary_url=P, slow_after_s=25.0)
    check((r1, r2) == ("slow-1", "slow-2") and state1 == "closed" and R.breaker_state(P) == "open"
          and R.counts() == counts_with(primary_ok=2, primary_slow=2),
          "C9 慢成功: 结果照用, 计 primary_slow; 连续 2 次 → 熔断")
    fresh(**BOTH)
    seen = []
    r = R.call(make_unit({"primary": [slow(200, "s")], "backup": []}, seen), relay_mode=AUTO, primary_url=P,
               slow_after_s=lambda: 0.0)
    check(r == "s" and R.counts()["primary_slow"] == 0, "C9 slow_after_s 可以是函数, 0 = 不按慢判 (流式)")
    fresh(**BOTH)
    seen = []
    r = R.call(make_unit({"primary": [APITimeoutError()], "backup": []}, seen), relay_mode=AUTO, primary_url=P)
    check(r == "backup-result" and seen == ["primary", "backup"]
          and R.counts() == counts_with(primary_fail=1, backup_ok=1), "C9 主站超时 → 同一次改打备用站")
    fresh(**BOTH)
    seen = []
    b_exc = status_exc(503)
    got = raises(lambda: R.call(make_unit({"primary": [APITimeoutError()], "backup": [b_exc]}, seen),
                                relay_mode=AUTO, primary_url=P))
    check(got is b_exc and got.__context__ is None and got.__cause__ is None
          and R.counts() == counts_with(primary_fail=1, backup_fail=1),
          "C9 备用站也挂: 原样抛备用站的异常, 不挂主站的 __context__")
    fresh(**BOTH)
    seen = []
    v_exc = ValueError("parse")
    got = raises(lambda: R.call(make_unit({"primary": [v_exc], "backup": []}, seen), relay_mode=AUTO, primary_url=P))
    check(got is v_exc and seen == ["primary"] and R.counts() == zero_counts(), "C9 不切的错误: 原对象抛出, 不碰备用站")
    d = fresh(**BOTH)
    seen = []
    r = R.call(make_unit({"primary": [], "backup": []}, seen), relay_mode=BO, primary_url=P)
    check(r == "backup-result" and seen == ["backup"] and not breaker_files(d), "C9 backup_only: 不碰主站、不建熔断文件")
    fresh()
    got = raises(lambda: R.call(lambda t: t, relay_mode=PO, primary_url=P))
    check(isinstance(got, ValueError), "C9 primary_only 不许走 call()")

    # C11 summary 的键
    fresh(**BOTH)
    s = R.summary(P)
    check(set(s) == {"mode", *R.COUNTER_KEYS, "breaker"} and "ok" not in s and "failed" not in s,
          f"C11 summary 的键: {sorted(s)}")
    dumped = json.dumps(s)
    check(not re.search(r'"ok": *\d', dumped) and not re.search(r'"failed": *\d', dumped),
          "C11 workflow 的 grep '\"ok\": N' / '\"failed\": N' 不会误中")

    # C12 health
    d = fresh()
    h = R.health()
    check(set(h) == {"relay_mode", "relay_backup_configured", "relay_force", "relay_breaker", "relay_counts"}
          and h["relay_mode"] == PO and h["relay_breaker"] == "off" and h["relay_backup_configured"] is False
          and h["relay_force"] == "auto" and h["relay_counts"] == zero_counts(), f"C12 没配: {h}")
    check(not breaker_files(d), "C12 primary_only 不建熔断文件")
    check("relay_counts" not in R.health(include_counts=False), "C12 include_counts=False 不带计数")
    fresh(**BOTH)
    h = R.health()
    check(h["relay_mode"] == AUTO and h["relay_backup_configured"] is True and h["relay_breaker"] == "closed"
          and all(isinstance(v, int) for v in h["relay_counts"].values()), f"C12 配了: {h}")
    fresh(**BOTH, RELAY_FORCE="backup")
    h = R.health()
    check(h["relay_mode"] == BO and h["relay_force"] == "backup" and h["relay_breaker"] == "off", f"C12 只走备用: {h}")


# ── §2 没配备用站 = 老路 ───────────────────────────────────────────────────

PARITY_CONFIGS = [
    ("没配", {}),
    ("只有备用地址", {"ANTHROPIC_BASE_URL_BACKUP": BU}),
    ("只有备用 key", {"ANTHROPIC_API_KEY_BACKUP": BK}),
    ("都配 + RELAY_FORCE=primary", {**BOTH, "RELAY_FORCE": "primary"}),
]


def parity_once(label: str, cfg: dict) -> None:
    m = mark()
    dirs = []
    probs = []

    def ctx(**extra):
        d = fresh(**cfg, **extra)
        dirs.append(d)
        return d

    # essence
    ctx(**BASE)
    out = E.call_claude("p", "m")
    if out != "text-from-primary" or BUILT != [{"base_url": P}] or set(CALLS[0][2]) != {"model", "max_tokens", "messages"}:
        probs.append(f"essence 构造 / 请求参数变了: {BUILT} {sorted(CALLS[0][2]) if CALLS else None}")
    ctx(ANTHROPIC_API_KEY=K)
    E.call_claude("p", "m", cached_system="S")
    if BUILT != [{}] or set(CALLS[0][2]) != {"model", "max_tokens", "messages", "system"} or CALLS[0][2]["system"] != "S":
        probs.append(f"essence (没设主站地址, 带 system) 变了: {BUILT}")
    ctx(**BASE)
    SCRIPT["primary"].extend([RateLimitError(429), RateLimitError(429), RateLimitError(429)])
    got = raises(lambda: E.call_claude("p", "m"))
    if not isinstance(got, RateLimitError) or len(CALLS) != 3 or len(BUILT) != 1:
        probs.append(f"essence 429 应重试到 3 次: calls={len(CALLS)}")
    ctx(**BASE)
    SCRIPT["primary"].append(BadRequestError(400))
    got = raises(lambda: E.call_claude("p", "m"))
    if not isinstance(got, BadRequestError) or len(CALLS) != 1:
        probs.append(f"essence 400 应 1 次就抛: calls={len(CALLS)}")
    # librarian (AU-F09: 没配备用站也是 max_retries=0 + 单次限时 45 秒; 重试还是自己那一层 3 次)
    ctx(**BASE)
    out = LC.call_anthropic("p", "m")
    if out != "text-from-primary" or BUILT != [{"max_retries": 0, "api_key": K, "base_url": P, "timeout": 45.0}] \
            or set(CALLS[0][2]) != {"model", "max_tokens", "messages", "timeout"} or CALLS[0][2]["timeout"] != 45.0:
        probs.append(f"librarian 构造 / 请求参数变了: {BUILT} {sorted(CALLS[0][2]) if CALLS else None}")
    ctx(**BASE)
    SCRIPT["primary"].extend([RateLimitError(429), RateLimitError(429), RateLimitError(429)])
    got = raises(lambda: LC.call_anthropic("p", "m"))
    if not isinstance(got, RateLimitError) or len(CALLS) != 3 or len(BUILT) != 1 or TICK.sleeps != [2, 4]:
        probs.append(f"librarian 429 应重试到 3 次 (退避 2 / 4 秒): calls={len(CALLS)} sleeps={TICK.sleeps}")
    # onboarder
    ctx(**BASE)
    out = OC.call_anthropic("p", "m")
    if out != "text-from-primary" or BUILT != [{"max_retries": 0, "api_key": K, "base_url": P}] or CALLS[0][1] != "stream":
        probs.append(f"onboarder 构造参数 / 流式变了: {BUILT}")
    ctx(**BASE)
    SCRIPT["primary"].append(status_exc(524))
    got = raises(lambda: OC.call_anthropic("p", "m"))
    if not (isinstance(got, RuntimeError) and "网关超时" in str(got)) or len(CALLS) != 1:
        probs.append(f"onboarder 524 应 1 次就给诊断: {type(got).__name__} calls={len(CALLS)}")
    if any("timeout" in b for b in BUILT):
        probs.append("出现了 timeout 参数")
    leftovers = [d for d in dirs if breaker_files(d)]
    if leftovers:
        probs.append("建了熔断文件")
    if R.counts() != zero_counts():
        probs.append(f"计数不是 0: {R.counts()}")
    if relay_lines(m):
        probs.append(f"relay 日志不该有: {relay_lines(m)}")
    check(not probs, f"§2 [{label}] 老路一字不变 (essence / librarian / onboarder)" + (f": {probs}" if probs else ""))


def sec2_parity() -> None:
    print("§2 没配备用站 = 老路")
    for label, cfg in PARITY_CONFIGS:
        parity_once(label, cfg)


# ── §3 essence 切换 ────────────────────────────────────────────────────────

FIRST_FAILOVER_RE = re.compile(r"^relay: primary failed \(([^)]*)\); failing over to backup$")


def sec3_essence() -> None:
    print("§3 essence call_claude 切换")
    fresh(**BASE, **BOTH)
    m = mark()
    SCRIPT["primary"].append(APITimeoutError())
    out = E.call_claude("p", "m")
    check(out == "text-from-backup", "主站超时 → 拿到备用站的结果")
    check(BUILT == [{"base_url": P, "max_retries": 0, "timeout": 60.0}, {"api_key": BK, "base_url": BU}],
          f"主站: 老参数 + max_retries=0 + timeout=60; 备用站: 显式 key + 地址, SDK 默认重试 ({BUILT})")
    check(INSTANCES[1].auth_token is None and INSTANCES[0].auth_token == "tok-from-env", "备用站客户端清掉 auth_token")
    check(len(CALLS) == 2 and CALLS[0][2] == CALLS[1][2], "备用站收到的请求和主站一模一样 (模型名 / prompt 不变)")
    check(R.counts() == counts_with(primary_fail=1, backup_ok=1), f"计数: {R.counts()}")
    SCRIPT["primary"].append(APITimeoutError())
    E.call_claude("p", "m")
    firsts = [x for x in relay_lines(m) if FIRST_FAILOVER_RE.match(x)]
    check(firsts == ["relay: primary failed (APITimeoutError); failing over to backup"], f"第一次切换打一行, 只打一次: {firsts}")

    for extra, mt, want in [({}, 8000, 150.0), ({"RELAY_PRIMARY_TIMEOUT_S": "20"}, 2000, 20.0),
                            ({"RELAY_PRIMARY_TIMEOUT_S": "abc"}, 2000, 60.0)]:
        fresh(**BASE, **BOTH, **extra)
        E.call_claude("p", "m", max_tokens=mt)
        check(BUILT and BUILT[0].get("timeout") == want, f"主站限时: max_tokens={mt} {extra} → {want}")

    missed = []
    for st in (401, 402, 403, 404, 408, 409, 429, 500, 502, 503, 504, 520, 522, 524, 529):
        fresh(**BASE, **BOTH)
        SCRIPT["primary"].append(status_exc(st))
        try:
            out = E.call_claude("p", "m")
        except Exception as exc:  # noqa: BLE001
            out = type(exc).__name__
        if out != "text-from-backup" or R.counts()["primary_fail"] != 1:
            missed.append(st)
    check(not missed, "主站 401/402/403/404/408/409/429/5xx/52x/529 → 切备用站" + (f" (没切: {missed})" if missed else ""))
    wrong = []
    for st in (400, 413, 422):
        fresh(**BASE, **BOTH)
        exc = status_exc(st)
        SCRIPT["primary"].append(exc)
        got = raises(lambda: E.call_claude("p", "m"))
        if got is not exc or "backup" in relays_built() or len(CALLS) != 1:
            wrong.append(st)
    check(not wrong, "主站 400/413/422 → 原样抛, 不建备用站客户端" + (f" (错: {wrong})" if wrong else ""))

    fresh(**BASE, **BOTH, PROMPT_CACHE_ENABLED="1")

    def cache_reject(kw):
        if isinstance(kw.get("system"), list):
            return BadRequestError(400, "cache_control not supported")
        return "plain-ok"
    SCRIPT["primary"].extend([cache_reject, cache_reject])
    out = E.call_claude("p", "m", cached_system="S")
    check(out == "plain-ok" and relays_built() == ["primary"] and [c[0] for c in CALLS] == ["primary", "primary"]
          and CALLS[1][2].get("system") == "S", "缓存块被拒 (400) 不切; 纯 system 重来还是打主站")


# ── §4 D-125 ───────────────────────────────────────────────────────────────

def sec4_d125() -> None:
    print("§4 D-125 中转站敏感词拦截")
    fresh(**BASE, **BOTH)
    exc = InternalServerError(500, "sensitive_words_detected")
    SCRIPT["primary"].extend([exc, exc, exc])
    got = raises(lambda: E.call_claude("p", "m"))
    check(got is exc and _common.is_gateway_filtered(got), "原异常对象原样抛, is_gateway_filtered 照旧认得")
    check("backup" not in relays_built() and all(c[0] == "primary" for c in CALLS), "不建备用站客户端、不打备用站")
    check(R._load(R.state_path(P))["fails"] == 0 and R.breaker_state(P) == "closed", "不算熔断失败")
    check(R.counts()["primary_fail"] == 0, "不计 primary_fail")
    import annotate_feature_pass as F
    check(F._api_failure(got)[1] == "gateway_filtered", "特征层照旧判 gateway_filtered (记 NULL)")
    check(set(R.GATEWAY_FILTER_MARKERS) >= set(_common.GATEWAY_FILTER_MARKERS), "核心的拦截标记覆盖 _common 的")


# ── §5 熔断跨调用 ──────────────────────────────────────────────────────────

def sec5_breaker() -> None:
    print("§5 熔断跨调用")
    fresh(**BASE, **BOTH)
    SCRIPT["primary"].extend([APITimeoutError(), APITimeoutError()])
    outs = [E.call_claude("p", "m"), E.call_claude("p", "m")]
    check(outs == ["text-from-backup"] * 2 and R.breaker_state(P) == "open", "连续 2 次主站超时 → 熔断")
    n = len(BUILT)
    out = E.call_claude("p", "m")
    check(out == "text-from-backup" and relays_built()[n:] == ["backup"] and R.counts()["breaker_open_skips"] == 1,
          "熔断期间: 不建主站客户端, 直接走备用 (breaker_open_skips=1)")
    NOW[0] += 1201
    SCRIPT["primary"].append("primary-again")
    m = mark()
    out = E.call_claude("p", "m")
    check(out == "primary-again" and R.breaker_state(P) == "closed"
          and "relay: breaker closed (primary ok again)" in relay_lines(m), "冷却到点: 试一次主站, 好了合上 + 打一行")
    SCRIPT["primary"].extend([APITimeoutError(), APITimeoutError()])
    E.call_claude("p", "m")
    E.call_claude("p", "m")
    NOW[0] += 1201
    SCRIPT["primary"].append(APITimeoutError())
    out = E.call_claude("p", "m")
    st = R._load(R.state_path(P))
    check(out == "text-from-backup" and R.breaker_state(P) == "open" and st["opened_at"] == NOW[0],
          "试探失败: 这次照样拿备用站结果, 重新熔断 20 分钟")

    fresh(**BASE, **BOTH)
    SCRIPT["primary"].append(slow(26, "slow-1"))
    out = E.call_claude("p", "m")
    check(out == "slow-1" and R.counts() == counts_with(primary_ok=1, primary_slow=1) and R.breaker_state(P) == "closed",
          "主站 26 秒才回: 结果照用, 计 primary_slow")
    SCRIPT["primary"].append(slow(26, "slow-2"))
    out = E.call_claude("p", "m")
    check(out == "slow-2" and R.breaker_state(P) == "open", "连续 2 次慢 → 熔断 (第二次的结果照用)")
    n = len(BUILT)
    out = E.call_claude("p", "m")
    check(out == "text-from-backup" and relays_built()[n:] == ["backup"], "熔断后下一次直接走备用站")
    fresh(**BASE, **BOTH)
    SCRIPT["primary"].extend([slow(26, "a"), slow(26, "b")])
    E.call_claude("p", "m", max_tokens=8000)
    E.call_claude("p", "m", max_tokens=8000)
    check(R.counts()["primary_slow"] == 0 and R.breaker_state(P) == "closed", "遮挡词 (max_tokens 8000) 26 秒不算慢 (门槛 60)")
    fresh(**BASE, **BOTH, RELAY_SLOW_S="0")
    SCRIPT["primary"].extend([slow(300, "a"), slow(300, "b")])
    E.call_claude("p", "m")
    E.call_claude("p", "m")
    check(R.counts()["primary_slow"] == 0 and R.breaker_state(P) == "closed", "RELAY_SLOW_S=0: 不按慢判")


# ── §6 RELAY_FORCE ─────────────────────────────────────────────────────────

def sec6_force() -> None:
    print("§6 RELAY_FORCE")
    d = fresh(**BASE, **BOTH, RELAY_FORCE="backup")
    out = E.call_claude("p", "m")
    LC.call_anthropic("p", "m")
    OC.call_anthropic("p", "m")
    check(out == "text-from-backup" and BUILT == [{"api_key": BK, "base_url": BU},
                                                  {"api_key": BK, "base_url": BU, "max_retries": 0, "timeout": 45.0},
                                                  {"api_key": BK, "base_url": BU, "max_retries": 0}],
          f"backup: 三处都只建备用站客户端 ({BUILT})")
    check(not breaker_files(d) and R.counts() == counts_with(backup_ok=3), "backup: 不碰熔断, 计 backup_ok")
    fresh(**BASE, **BOTH, RELAY_FORCE="backup")
    SCRIPT["backup"].extend([status_exc(503)] * 3)
    got = raises(lambda: E.call_claude("p", "m"))
    check(isinstance(got, InternalServerError) and len(CALLS) == 3 and R.counts()["backup_fail"] == 3,
          "backup 也挂: essence 照老规矩重试 3 次后抛")
    fresh(**BASE, RELAY_FORCE="backup")
    m = mark()
    E.call_claude("p", "m")
    E.call_claude("p", "m")
    warn = [x for x in relay_lines(m) if "RELAY_FORCE=backup but no backup relay is configured" in x]
    check(BUILT == [{"base_url": P}, {"base_url": P}] and len(warn) == 1, "没配备用站却设 backup: 走老路 + 只提示一次")
    fresh(**BASE, **BOTH, RELAY_FORCE="zzz")
    m = mark()
    SCRIPT["primary"].append(APITimeoutError())
    out = E.call_claude("p", "m")
    E.call_claude("p", "m")
    warn = [x for x in relay_lines(m) if "RELAY_FORCE not recognized" in x]
    check(out == "text-from-backup" and len(warn) == 1, "认不出的 RELAY_FORCE: 按自动 + 只提示一次")


# ── §7 librarian ───────────────────────────────────────────────────────────

def hang(kw):
    """假的「挂住」: 把钟拨过这次调用拿到的限时, 再超时 (真 SDK 到点抛 APITimeoutError)。"""
    CLOCK[0] += kw["timeout"]
    return APITimeoutError()


def timeouts() -> list:
    return [c[2].get("timeout") for c in CALLS]


def answers_at(seconds: float, text: str):
    """假的「第 N 秒才答完」: 认这次调用拿到的限时 —— 限时先到就超时 (真 SDK 也是), 否则到点返回。"""
    def f(kw):
        if seconds > kw["timeout"]:
            CLOCK[0] += kw["timeout"]
            return APITimeoutError()
        CLOCK[0] += seconds
        return text
    return f


def sec7_librarian() -> None:
    print("§7 librarian call_anthropic")
    fresh(**BASE, **BOTH)
    SCRIPT["primary"].append(APIConnectionError())
    out = LC.call_anthropic("p", "m")
    check(out == "text-from-backup", "主站连不上 → 备用站")
    check(BUILT == [{"max_retries": 0, "api_key": K, "base_url": P, "timeout": 22.0},
                    {"api_key": BK, "base_url": BU, "max_retries": 0, "timeout": 45.0}],
          f"主站限时 22 秒, 备用站 45 秒, 两边 SDK 都不重试 ({BUILT})")
    fresh(**BASE, **BOTH, RELAY_PRIMARY_TIMEOUT_S="30")
    SCRIPT["primary"].append(slow(26, "slow"))
    out = LC.call_anthropic("p", "m")
    check(out == "slow" and R.counts()["primary_slow"] == 1 and BUILT[0]["timeout"] == 30.0 and timeouts() == [30.0],
          "RELAY_PRIMARY_TIMEOUT_S=30 照认; 这时馆员 26 秒算慢 (门槛 25)")
    fresh(**BASE, **BOTH)
    SCRIPT["primary"].append(BadRequestError(400))
    got = raises(lambda: LC.call_anthropic("p", "m"))
    check(isinstance(got, BadRequestError) and "backup" not in relays_built(), "馆员 400 不切")

    # AU-F09 整轮时限 60 秒: 每次调用的限时 = 自己的上限和整轮剩下的时间里小的那个
    check(LC.REQUEST_BUDGET_S >= 60.0 and LC.PRIMARY_TIMEOUT_S + LC.MIN_CALL_S <= LC.REQUEST_BUDGET_S
          and LC.PRIMARY_TIMEOUT_S < LC.CALL_TIMEOUT_S <= LC.REQUEST_BUDGET_S,
          "整轮时限不低于 60 秒 (写作台后台借阅等 60 秒, 要让慢的那次填上缓存), 主站限时 < 单次限时 ≤ 整轮")
    fresh(**BASE, **BOTH)
    SCRIPT["primary"].append(hang)
    SCRIPT["backup"].append(slow(15, "cards"))
    out = LC.call_anthropic("p", "m")
    check(out == "cards" and timeouts() == [22.0, 38.0] and CLOCK[0] == 37.0,
          f"主站挂住: 第 22 秒切, 备用站拿整轮剩下的 38 秒, 第 37 秒拿到卡 ({timeouts()}, t={CLOCK[0]})")
    fresh(**BASE, **BOTH)
    SCRIPT["primary"].append(hang)
    SCRIPT["backup"].append(hang)
    got = raises(lambda: LC.call_anthropic("p", "m"))
    check(isinstance(got, APITimeoutError) and CLOCK[0] == 60.0 and len(CALLS) == 2 and TICK.sleeps == [],
          f"两边都挂住: 第 60 秒抛出去, 不再试 (t={CLOCK[0]}, {len(CALLS)} 次调用, 退避 {TICK.sleeps})")
    fresh(**BASE, **BOTH)
    SCRIPT["primary"].extend([status_exc(503)] * 2)
    SCRIPT["backup"].extend([status_exc(503)] * 3)
    got = raises(lambda: LC.call_anthropic("p", "m"))
    check(isinstance(got, InternalServerError) and [c[0] for c in CALLS] == ["primary", "backup", "primary", "backup", "backup"]
          and TICK.sleeps == [2, 4], f"两边都秒回 503: 照旧试 3 次 (第 3 次熔断已开, 直接备用站), 退避 2 / 4 秒 ({TICK.sleeps})")
    fresh(**BASE, **BOTH)
    SCRIPT["primary"].append(status_exc(503))
    SCRIPT["backup"].append(hang)
    got = raises(lambda: LC.call_anthropic("p", "m"))
    check(isinstance(got, APITimeoutError) and timeouts() == [22.0, 45.0] and len(CALLS) == 2 and TICK.sleeps == [],
          f"主站秒回 503、备用站挂满 45 秒: 整轮只剩 15 秒, 放不下主站 22 + 10, 不重试 ({len(CALLS)} 次调用)")
    fresh(**BASE)
    SCRIPT["primary"].append(hang)
    out = LC.call_anthropic("p", "m")
    check(out == "text-from-primary" and timeouts() == [45.0, 13.0] and TICK.sleeps == [2],
          f"没配备用站: 第一次挂满 45 秒, 退避 2 秒, 第二次只给剩下的 13 秒 ({timeouts()})")
    fresh(**BASE)
    SCRIPT["primary"].extend([hang, hang, hang])
    got = raises(lambda: LC.call_anthropic("p", "m"))
    check(isinstance(got, APITimeoutError) and CLOCK[0] == 60.0 and len(CALLS) == 2,
          f"没配备用站、一直挂住: 第 60 秒抛出去, 没有第三次 (t={CLOCK[0]}, {len(CALLS)} 次调用)")
    fresh(**BASE, PROMPT_CACHE_ENABLED="1")
    before = LC.PROMPT_CACHE_FALLBACKS["count"]
    SCRIPT["primary"].extend([hang, hang, hang])
    blocks = [{"type": "text", "text": "S", "cache_control": {"type": "ephemeral"}}]
    got = raises(lambda: LC.call_anthropic("p", "m", system=blocks))
    check(isinstance(got, APITimeoutError) and CLOCK[0] == 60.0 and len(CALLS) == 2
          and LC.PROMPT_CACHE_FALLBACKS["count"] == before,
          f"带缓存块的调用把整轮用完了: 不再去掉缓存块重来一遍 (t={CLOCK[0]}, {len(CALLS)} 次调用)")

    # RELAY_PRIMARY_TIMEOUT_S 调大 (核心认 5..600; 别的调用点默认 60 / 150): 馆员这头超过「整轮 - 2 × MIN_CALL_S」按它算,
    # 不然「主站限时 + 10」永远放不进 60 秒 —— 不重试、不降级, 60 以上备用站只剩 1 秒 (11-11 审查 R1)
    cap = LC.REQUEST_BUDGET_S - 2 * LC.MIN_CALL_S
    fresh(**BASE, **BOTH, RELAY_PRIMARY_TIMEOUT_S="55")
    SCRIPT["primary"].append(status_exc(529))
    SCRIPT["backup"].append(status_exc(529))
    out = raises(lambda: LC.call_anthropic("p", "m")) or "returned"
    check(out == "returned" and [c[0] for c in CALLS] == ["primary", "backup", "primary"] and TICK.sleeps == [2]
          and timeouts()[:1] == [cap] and BUILT[0]["timeout"] == cap == 40.0,
          f"RELAY_PRIMARY_TIMEOUT_S=55: 主站按 40 秒算, 两边各 529 一次照旧重试 "
          f"({type(out).__name__}, {[c[0] for c in CALLS]}, 限时 {timeouts()[:1]}, 退避 {TICK.sleeps})")
    fresh(**BASE, **BOTH, RELAY_PRIMARY_TIMEOUT_S="55", PROMPT_CACHE_ENABLED="1")
    before = LC.PROMPT_CACHE_FALLBACKS["count"]
    rejected = BadRequestError(400)
    rejected.args = ("Error code: 400 - cache_control is not supported",)   # 馆员降级那行 warning 本来就带报错开头 (过掩码),
    SCRIPT["primary"].append(rejected)                                      # 这里不带哨兵, 免得 §10 把它当成核心漏的
    out = raises(lambda: LC.call_anthropic("p", "m", system=blocks)) or "returned"
    check(out == "returned" and len(CALLS) == 2 and isinstance(CALLS[-1][2].get("system"), str)
          and LC.PROMPT_CACHE_FALLBACKS["count"] == before + 1,
          f"RELAY_PRIMARY_TIMEOUT_S=55: 缓存块被拒 (400) 照旧去掉缓存块再来一次 ({type(out).__name__}, {len(CALLS)} 次调用)")
    fresh(**BASE, **BOTH, RELAY_PRIMARY_TIMEOUT_S="600")
    SCRIPT["primary"].append(hang)
    SCRIPT["backup"].append(slow(15, "cards"))
    out = raises(lambda: LC.call_anthropic("p", "m")) or "returned"
    check(out == "returned" and timeouts() == [40.0, 20.0] and CLOCK[0] == 55.0,
          f"RELAY_PRIMARY_TIMEOUT_S=600: 主站挂住第 40 秒切, 备用站还有 20 秒 (不是 1 秒), 第 55 秒拿到卡 ({timeouts()}, t={CLOCK[0]})")

    # 22 秒是有意的取舍 (11-11 审查 R2): 主站本来 25.5 秒能答完的也被切到备用站, 37 秒才拿到卡; 调到 30 等得到, 代价是挂住时 45 秒
    fresh(**BASE, **BOTH)
    SCRIPT["primary"].append(answers_at(25.5, "late-primary"))
    SCRIPT["backup"].append(slow(15, "cards"))
    out = LC.call_anthropic("p", "m")
    check(out == "cards" and timeouts() == [22.0, 38.0] and CLOCK[0] == 37.0,
          f"主站 25.5 秒才答完: 默认 22 秒被切, 第 37 秒从备用站拿到卡 ({out}, t={CLOCK[0]})")
    fresh(**BASE, **BOTH, RELAY_PRIMARY_TIMEOUT_S="30")
    SCRIPT["primary"].append(answers_at(25.5, "late-primary"))
    out = LC.call_anthropic("p", "m")
    t_slow = CLOCK[0]
    fresh(**BASE, **BOTH, RELAY_PRIMARY_TIMEOUT_S="30")
    SCRIPT["primary"].append(hang)
    SCRIPT["backup"].append(slow(15, "cards"))
    LC.call_anthropic("p", "m")
    check(out == "late-primary" and t_slow == 25.5 and CLOCK[0] == 45.0,
          f"RELAY_PRIMARY_TIMEOUT_S=30: 25.5 秒那次等得到 (t={t_slow}); 代价是主站挂住时第 45 秒才拿到卡 (t={CLOCK[0]})")

    # 限时是「这么久没收到新字节」(httpx 按每次读算), 不是墙上时钟 (11-11 审查 R3): 假 SDK 里「过了限时还正常返回」
    # 就是对方一直在滴字节。这种调用不会被掐, 也不切备用站 —— 已知边界, 文档要照实写, 不许再说「最多 60 秒」不带条件。
    fresh(**BASE, **BOTH)
    SCRIPT["primary"].append(slow(70, "dripped"))
    out = LC.call_anthropic("p", "m")
    check(out == "dripped" and CLOCK[0] == 70.0 and [c[0] for c in CALLS] == ["primary"],
          f"一直滴字节的主站: 70 秒后照样从主站返回, 整轮超过 60 秒 (已知边界; t={CLOCK[0]})")
    readme = (Path(LC.__file__).resolve().parent / "README.md").read_text(encoding="utf-8")
    limits = next((b for b in readme.split("\n- ") if b.startswith("**时限**")), "")
    src = Path(LC.__file__).read_text(encoding="utf-8")
    missing = [w for w, text in (("没有新字节", limits), ("没有新字节", src), ("22-30 秒", limits), ("按 40", limits))
               if w not in text]
    check(limits and not missing,
          "README「时限」和 clients.py 写明: 限时按没有新字节算 · 22-30 秒答完的也被切 · RELAY_PRIMARY_TIMEOUT_S 超过 40 按 40"
          + (f" (缺 {missing})" if missing else ""))


# ── §8 onboarder ───────────────────────────────────────────────────────────

def sec8_onboarder() -> None:
    print("§8 onboarder call_anthropic")
    fresh(**BASE, **BOTH)
    SCRIPT["primary"].append((["half-", "way-"], APITimeoutError()))
    SCRIPT["backup"].append((["full ", "backup ", "text"], None))
    out = OC.call_anthropic("p", "m")
    check(out == "full backup text", f"流式中途断 → 整段在备用站重来, 不拼半截 ({out!r})")
    check(BUILT == [{"max_retries": 0, "api_key": K, "base_url": P, "timeout": 90.0},
                    {"api_key": BK, "base_url": BU, "max_retries": 0}], f"主站 90 秒 (没新字节), 备用站 max_retries=0 ({BUILT})")
    check([c[1] for c in CALLS] == ["stream", "stream"], "两边都是流式")
    # 真 SDK: 流读到一半卡住 → httpx.ReadTimeout, 断开 → httpx.RemoteProtocolError (都不是 APITimeoutError)
    for exc, label in ((ReadTimeout(f"timed out {SENTINEL}"), "TimeoutError"),
                       (RemoteProtocolError(f"peer closed connection {SENTINEL}"), "ConnectionError")):
        fresh(**BASE, **BOTH)
        m = mark()
        SCRIPT["primary"].append((["half-"], exc))
        SCRIPT["backup"].append((["full ", "backup"], None))
        try:
            out = OC.call_anthropic("p", "m")
        except Exception as e:  # noqa: BLE001
            out = f"raised {type(e).__name__}"
        firsts = [x for x in relay_lines(m) if FIRST_FAILOVER_RE.match(x)]
        check(out == "full backup" and R.counts() == counts_with(primary_fail=1, backup_ok=1)
              and firsts == [f"relay: primary failed ({label}); failing over to backup"],
              f"真 SDK 的流中途 {type(exc).__name__} (httpx 原样异常) → 也切备用站, 只记类名 {label}")
    fresh(**BASE, **BOTH)
    SCRIPT["primary"].extend([(["a"], ReadTimeout("x")), (["b"], ReadTimeout("x"))])
    e1 = raises(lambda: OC.call_anthropic("p", "m"))
    e2 = raises(lambda: OC.call_anthropic("p", "m"))
    check(e1 is None and e2 is None and R.breaker_state(P) == "open", "主站流连续 2 次中途卡住 → 熔断")
    fresh(**BASE, **BOTH, RELAY_FORCE="backup")
    b_exc = ReadTimeout(f"timed out {SENTINEL}")
    SCRIPT["backup"].append((["half-"], b_exc))
    got = raises(lambda: OC.call_anthropic("p", "m"))
    check(got is b_exc and len(CALLS) == 1, "备用站那一路的 httpx 异常原样抛 (不换类、和老路一样不重试)")
    fresh(**BASE)
    p_exc = ReadTimeout(f"timed out {SENTINEL}")
    SCRIPT["primary"].append((["half-"], p_exc))
    got = raises(lambda: OC.call_anthropic("p", "m"))
    check(got is p_exc and relays_built() == ["primary"] and R.counts() == zero_counts(),
          "没配备用站: 主站流中途的 httpx 异常原样抛 (老路一字不变)")
    fresh(**BASE, **BOTH)
    SCRIPT["primary"].append(status_exc(524))
    out = OC.call_anthropic("p", "m")
    check(out == "text-from-backup" and R.counts() == counts_with(primary_fail=1, backup_ok=1), "主站 524 → 切备用站")
    fresh(**BASE, **BOTH)
    SCRIPT["primary"].append(status_exc(524))
    SCRIPT["backup"].append(status_exc(524))
    got = raises(lambda: OC.call_anthropic("p", "m"))
    check(isinstance(got, RuntimeError) and "网关超时" in str(got) and len(CALLS) == 2, "两边都 524: 照旧给诊断, 不空转")
    fresh(**BASE, **BOTH, ONBOARDER_STREAM="0")
    OC.call_anthropic("p", "m")
    check(BUILT and BUILT[0].get("timeout") == 600.0 and CALLS[0][1] == "create", "非流式: 主站限时 600 秒")
    fresh(**BASE, **BOTH)
    SCRIPT["primary"].append(slow(200, "long stream"))
    out = OC.call_anthropic("p", "m")
    check(out == "long stream" and R.counts()["primary_slow"] == 0, "流式不按慢判")


# ── §9 /health ─────────────────────────────────────────────────────────────

def sec9_health() -> None:
    print("§9 /health 的 relay 块")
    try:
        from fastapi.testclient import TestClient
        import worker.app as W
        from librarian import app as LA
        from onboarder import app as OA
    except ImportError as exc:
        print(f"  ⚠️ §9 跳过 (import 失败: {type(exc).__name__}); CI 的 python job 装了服务依赖, 那里会跑")
        return
    keys = {"relay_mode", "relay_backup_configured", "relay_force", "relay_breaker"}
    for name, mod, with_counts in (("worker", W, False), ("librarian", LA, True), ("onboarder", OA, True)):
        fresh(**BASE, **BOTH)
        r = TestClient(mod.app).get("/health")
        body = r.json() if r.status_code == 200 else {}
        rel = body.get("relay") or {}
        want = keys | ({"relay_counts"} if with_counts else set())
        typed = (rel.get("relay_mode") == AUTO and rel.get("relay_backup_configured") is True
                 and rel.get("relay_force") == "auto" and rel.get("relay_breaker") == "closed")
        if with_counts:
            typed = typed and set(rel.get("relay_counts") or {}) == set(R.COUNTER_KEYS) and all(
                isinstance(v, int) and not isinstance(v, bool) for v in rel["relay_counts"].values())
        check(r.status_code == 200 and set(rel) == want and typed, f"{name}: relay 的键与类型 ({rel})")
        dump = json.dumps(body, ensure_ascii=False)
        leaked = [x for x in ("backup-host.invalid", K, BK) if x in dump]
        if name != "worker":                     # worker 的 anthropic_base_url_origin 是早就有的 (ci.yml 钉着)
            leaked += [x for x in ("primary-host.invalid",) if x in dump]
        check(not leaked, f"{name}: /health 不漏地址 / key" + (f" (漏了 {len(leaked)} 项)" if leaked else ""))
        EXTRA_TEXT.append(dump if name != "worker" else dump.replace(P, ""))
    fresh(**BASE)
    rel = TestClient(LA.app).get("/health").json().get("relay")
    check(rel and rel["relay_mode"] == PO and rel["relay_breaker"] == "off" and rel["relay_backup_configured"] is False,
          "没配: relay_mode=primary_only, relay_breaker=off")
    fresh(**BASE, **BOTH, RELAY_PRIMARY_TIMEOUT_S="30")
    sel = TestClient(LA.app).get("/health").json().get("select") or {}
    gate = sel.pop("return_gate", None)        # D-151: 回流闸的子块单独核 (下面), AU-F09 那几个键照旧只有数
    paid = sel.pop("paid_boost", None)         # D-151 第 13 条: 投流标注的子块也单独核
    check(set(sel) == {"merged", "wait_timeouts", "primary_timeout_s", "call_timeout_s", "request_budget_s"}
          and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in sel.values())
          and (sel["primary_timeout_s"], sel["call_timeout_s"], sel["request_budget_s"]) == (30.0, 45.0, 60.0),
          f"librarian: select 块 (AU-F09) 只有数, 主站限时回显的是生效值 ({sel})")
    # 这个进程里没借过卡: on 回显的是现在生效的开关 (代码默认, LIBRARIAN_RETURN_GATE 设了听它的), 一次库都没读过
    from librarian import core as LC  # noqa: E402
    check(isinstance(gate, dict)
          and set(gate) == {"on", "read_age_s", "read_ok", "columns", "read_errors", "verdicts", "unreadable",
                            "would_drop", "brands_kept"}
          and all(v is None or isinstance(v, (bool, int)) for v in gate.values())
          and gate["on"] is LC.return_gate_enabled() and gate["read_age_s"] is None and gate["read_ok"] is None
          and (gate["would_drop"], gate["brands_kept"], gate["read_errors"]) == (0, 0, 0),
          f"librarian: select.return_gate (D-151) 只有布尔 / 整数 / None, 没读过库时不报数 ({gate})")
    # 这个进程里没借过卡: 投流起量的帖一次都没读过, 计数都是 0 / None
    check(isinstance(paid, dict)
          and set(paid) == {"read_age_s", "read_ok", "read_errors", "flagged", "events", "labelled"}
          and all(v is None or isinstance(v, (bool, int)) for v in paid.values())
          and (paid["read_age_s"], paid["read_ok"], paid["flagged"], paid["events"]) == (None, None, None, None)
          and (paid["read_errors"], paid["labelled"]) == (0, 0),
          f"librarian: select.paid_boost (D-151 第 13 条) 只有布尔 / 整数 / None, 没读过库时不报数 ({paid})")
    fresh(**BASE, **BOTH, RELAY_PRIMARY_TIMEOUT_S="55")
    sel = TestClient(LA.app).get("/health").json().get("select") or {}
    check(sel.get("primary_timeout_s") == 40.0,
          f"librarian: RELAY_PRIMARY_TIMEOUT_S=55 时回显的是真在用的 40, 不是 55 ({sel.get('primary_timeout_s')})")
    real = R.health

    def boom(**_kw):
        raise RuntimeError(f"boom {SENTINEL}")
    R.health = boom
    try:
        rs = [TestClient(mod.app).get("/health") for mod in (W, LA, OA)]
    finally:
        R.health = real
    check(all(r.status_code == 200 and r.json().get("relay") == {"relay_error": "RuntimeError"} for r in rs),
          "relay 块出错: /health 照样 200, 只报异常类型")


# ── §10 日志卫生 / §11 Done 行 / §12 import ───────────────────────────────

def sec10_hygiene() -> None:
    print("§10 日志卫生")
    fresh(**BASE, **BOTH)
    # 第 1 次尝试: 主站 402 → 备用站 503 → essence 照老规矩重试; 第 2 次: 主站又 402 → 熔断 → 备用站成功
    SCRIPT["primary"].extend([status_exc(402, "insufficient balance"), status_exc(402, "insufficient balance")])
    SCRIPT["backup"].extend([status_exc(503, "upstream overloaded"), "ok"])
    out = E.call_claude("p", "m")
    m = mark()
    R._emit_summary()
    summ = [x for x in relay_lines(m) if x.startswith("relay summary: ")]
    try:
        parsed = json.loads(summ[0][len("relay summary: "):]) if summ else None
    except ValueError:
        parsed = None
    check(out == "ok" and parsed is not None and parsed.get("primary_fail") == 2 and parsed.get("backup_fail") == 1
          and parsed.get("backup_ok") == 1 and parsed.get("breaker") == "open"
          and set(parsed) == {"mode", *R.COUNTER_KEYS, "breaker"}, f"退出汇总行: {summ[:1]}")
    text = "\n".join([all_log_text(), STDERR.getvalue(), *EXTRA_TEXT])
    hits = [x for x in LEAKS if x in text]
    check(not hits, f"所有日志 / stderr / 子进程输出 / 汇总里没有地址、key、报错原文 (共 {len(CAP.records)} 条日志)"
          + (f" —— 漏了 {len(hits)} 项" if hits else ""))
    relay_msgs = set(relay_lines())
    allowed = (re.compile(r"^relay: primary failed \((HTTP \d{3}( [a-z_]+)?|[A-Za-z]+)\); failing over to backup$"),
               re.compile(r"^relay: breaker open for \d+s after \d+ consecutive primary failures \(last: [^)]*\); "
                          r"calls go straight to backup$"),
               re.compile(r"^relay: breaker closed \(primary ok again\)$"),
               re.compile(r"^relay: RELAY_FORCE=backup but no backup relay is configured; using primary$"),
               re.compile(r"^relay: RELAY_FORCE not recognized \(expected primary, backup or empty\); using auto$"),
               re.compile(r"^relay: ANTHROPIC_CUSTOM_HEADERS is set; some SDK versions also send it to the backup relay$"),
               re.compile(r"^relay summary: \{.*\}$"))
    odd = [x for x in relay_msgs if not any(p.match(x) for p in allowed)]
    check(not odd, f"relay 日志只有固定几种句式 ({len(relay_msgs)} 种)" + (f": {odd}" if odd else ""))


def sec11_done_lines() -> None:
    print("§11 Done 行带 relay 汇总 (只在配了备用站时)")
    import annotate_comment_threading as CT
    import annotate_feature_pass as F
    import curate_flywheel_lessons as CU
    for name, fn in (("essence", E.main), ("特征层", F.main), ("策展", CU.main), ("评论归线", CT.main)):
        src = inspect.getsource(fn)
        i = src.find('stats["relay"]')
        ok = (i > 0 and "summary()" in src[i:i + 80] and "MODE_PRIMARY_ONLY" in src[max(0, i - 200):i]
              and src.find('logger.info("Done: %s"') > i)
        check(ok, f"{name}: Done 行前 `if mode != primary_only: stats['relay'] = summary()`")


def sec12_import_guard() -> None:
    print("§12 脚本直接跑也 import 得到 relay_failover")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC_", "RELAY_")) and k != "PYTHONPATH"}
    for cwd, mod in ((HERE, "annotate_essence_pass"), (ROOT / "librarian", "clients"), (ROOT / "onboarder", "clients")):
        p = subprocess.run([sys.executable, "-c", f"import {mod} as m; print(m.relay_failover.mode())"],
                           cwd=str(cwd), env=env, capture_output=True, text=True, timeout=120)
        EXTRA_TEXT.append(p.stdout + p.stderr)
        check(p.returncode == 0 and p.stdout.strip().endswith(PO),
              f"{cwd.name}/{mod}.py (仓库根不在 sys.path): rc={p.returncode}")


# ── §13 备用站 Haiku 专用钥匙 (D-148 补, 11-10) ─────────────────────────────

def sec13_haiku_key() -> None:
    print("§13 备用站 Haiku 专用钥匙")
    H = {"ANTHROPIC_API_KEY_BACKUP_HAIKU": HK}
    fresh(**BASE, **BOTH, **H)
    SCRIPT["primary"].append(APITimeoutError())
    out = E.call_claude("p", "claude-haiku-5-5")
    check(out == "text-from-backup" and BUILT[1:] == [{"api_key": HK, "base_url": BU}],
          f"haiku 模型主站超时 → 备用站用 Haiku 专用钥匙, 地址照旧 ({BUILT[1:]})")
    check(INSTANCES[1].auth_token is None, "Haiku 专用钥匙的客户端也清掉 auth_token")
    check(CALLS[1][2].get("model") == "claude-haiku-5-5", "发到备用站的模型名不变")

    fresh(**BASE, **BOTH, **H)
    SCRIPT["primary"].append(APITimeoutError())
    E.call_claude("p", "claude-sonnet-5-5")
    check(BUILT[1:] == [{"api_key": BK, "base_url": BU}], f"非 haiku 模型照旧用通用备用钥匙 ({BUILT[1:]})")

    for env, why in (({}, "没设 Haiku 专用钥匙"), ({"ANTHROPIC_API_KEY_BACKUP_HAIKU": "  "}, "只填了空白")):
        fresh(**BASE, **BOTH, **env)
        SCRIPT["primary"].append(APITimeoutError())
        E.call_claude("p", "claude-haiku-5-5")
        check(BUILT[1:] == [{"api_key": BK, "base_url": BU}], f"{why} → haiku 也用通用备用钥匙 ({BUILT[1:]})")

    fresh(**BASE, **BOTH, **H, RELAY_FORCE="backup")
    out = E.call_claude("p", "claude-haiku-5-5")
    check(out == "text-from-backup" and BUILT == [{"api_key": HK, "base_url": BU}] and relays_built() == ["backup"],
          f"RELAY_FORCE=backup + haiku → 只建备用站客户端, 用专用钥匙 ({BUILT})")

    fresh(**BASE, **H)
    out = E.call_claude("p", "claude-haiku-5-5")
    check(out == "text-from-primary" and BUILT == [{"base_url": P}],
          f"只设 Haiku 专用钥匙、没配备用站 = 老路, 不碰这把钥匙 ({BUILT})")


def main() -> int:
    with contextlib.redirect_stderr(STDERR):
        sec1_core()
        sec2_parity()
        sec3_essence()
        sec4_d125()
        sec5_breaker()
        sec6_force()
        sec7_librarian()
        sec8_onboarder()
        sec9_health()
        sec13_haiku_key()
    sec10_hygiene()
    sec11_done_lines()
    sec12_import_guard()
    R._reset_for_tests()       # 别在退出时再打一行汇总
    tempfile.tempdir = None
    logging.getLogger().removeHandler(CAP)
    if FAILS:
        print(f"❌ 备用中转站 (D-148): {len(FAILS)} 条不过")
        for f in FAILS:
            print("  ❌", f)
        return 1
    print("✅ 备用中转站 (D-148): §1 核心 · §2 没配=老路 · §3 essence 切换 · §4 D-125 不切 · §5 熔断 · §6 RELAY_FORCE · "
          "§7 馆员 · §8 上表 · §9 /health · §10 日志卫生 · §11 Done 行 · §12 import · §13 Haiku 专用钥匙 全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
