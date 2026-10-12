#!/usr/bin/env python3
"""CI 守卫: prompt caching 降级要被数出来、在外面看得见 (2026-10-08 审计 C-02)。

以前 librarian/clients.py 与 annotate_essence_pass.py 的降级都只打一行 warning 进 Railway stdout; 中转站不支持
cache_control 的话每次调用都在多付一倍 input token, 持续几个月没人知道。

  §1 librarian.call_anthropic: 带 cache_control 块失败 → 用纯 system 重试成功 → 计数 +1; 纯 system 调用不计
  §2 essence.call_claude: 同上 (cached_system 路径)
  §3 librarian /health 回显 config.prompt_cache_fallbacks (同进程计数)
  §4 essence 的 Done 行 stats 带 prompt_cache_fallbacks
  §5 真错误 (纯 system 也失败) 仍抛出 —— 降级不掩盖余额 / 鉴权 / 模型不存在
  §6 实际缓存读写按 usage 累加 (2026-10-12): essence.call_claude 与 librarian.call_anthropic 各自记 calls /
     input / cache_write / cache_read / output; read_share = cache_read / 总输入; 特征层与 essence 的 Done 行、
     librarian /health 都带出去 —— 网关静默丢掉 cache_control 时降级计数恒 0, 只有这几个数看得出来
用假的 anthropic 模块, 不碰网络。
"""
from __future__ import annotations

import inspect
import os
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))


class _Msg:
    def __init__(self, text, cached=False):
        self.content = [types.SimpleNamespace(type="text", text=text)]
        # 带缓存块的那次: 假装读到 900 个缓存 token; 纯 system: 全算普通输入
        self.usage = types.SimpleNamespace(input_tokens=100 if cached else 1000,
                                           cache_creation_input_tokens=0,
                                           cache_read_input_tokens=900 if cached else 0,
                                           output_tokens=50)


class _Messages:
    def __init__(self, fail_plain=False):
        self.fail_plain = fail_plain

    def create(self, **kw):
        sysv = kw.get("system")
        if isinstance(sysv, list) and _CACHE_OK["v"]:
            return _Msg("ok:cached", cached=True)
        if isinstance(sysv, list):
            raise RuntimeError("400 bad request: cache_control not supported by this gateway")   # 非瞬时 → 不重试
        if self.fail_plain:
            raise RuntimeError("401 invalid api key")
        return _Msg("ok:" + ("sys" if sysv else "nosys"))


_FAIL_PLAIN = {"v": False}
_CACHE_OK = {"v": False}


class _Anthropic:
    def __init__(self, **kw):
        self.messages = _Messages(fail_plain=_FAIL_PLAIN["v"])


def main() -> int:
    fake = types.ModuleType("anthropic")
    fake.Anthropic = _Anthropic
    sys.modules["anthropic"] = fake
    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test")
    fails: list[str] = []

    from librarian import clients as C
    import annotate_essence_pass as E

    # §1
    before = C.PROMPT_CACHE_FALLBACKS["count"]
    out = C.call_anthropic("p", "m", system=[{"type": "text", "text": "S", "cache_control": {"type": "ephemeral"}}])
    if out != "ok:sys" or C.PROMPT_CACHE_FALLBACKS["count"] != before + 1:
        fails.append(f"§1 降级后应成功且计数 +1: out={out!r} count={C.PROMPT_CACHE_FALLBACKS['count']}")
    if not C.PROMPT_CACHE_FALLBACKS["last_error"].startswith("RuntimeError"):
        fails.append("§1 last_error 要记类型 + 片段")
    C.call_anthropic("p", "m", system="S")
    if C.PROMPT_CACHE_FALLBACKS["count"] != before + 1:
        fails.append("§1 纯 system 调用不该计降级")

    # §2
    b2 = E.PROMPT_CACHE_FALLBACKS["count"]
    out2 = E.call_claude("p", "m", cached_system="S")
    if out2 != "ok:sys" or E.PROMPT_CACHE_FALLBACKS["count"] != b2 + 1:
        fails.append(f"§2 essence 降级后应成功且计数 +1: out={out2!r} count={E.PROMPT_CACHE_FALLBACKS['count']}")
    E.call_claude("p", "m")
    if E.PROMPT_CACHE_FALLBACKS["count"] != b2 + 1:
        fails.append("§2 无 system 调用不该计降级")

    # §3
    try:
        from fastapi.testclient import TestClient
        from librarian import app as A
        h = TestClient(A.app).get("/health").json()
        got = (h.get("config") or {}).get("prompt_cache_fallbacks") or {}
        if got.get("count") != C.PROMPT_CACHE_FALLBACKS["count"]:
            fails.append(f"§3 /health 没回显降级计数: {h}")
    except ImportError as exc:
        print(f"  ⚠️ §3 跳过 (import 失败: {exc}); CI 的 python job 装了 librarian 依赖, 那里会跑")

    # §4
    if '"prompt_cache_fallbacks"' not in inspect.getsource(E.main):
        fails.append("§4 essence 的 Done 行 stats 没带 prompt_cache_fallbacks")

    # §5
    _FAIL_PLAIN["v"] = True
    try:
        C.call_anthropic("p", "m", system=[{"type": "text", "text": "S", "cache_control": {"type": "ephemeral"}}])
        fails.append("§5 纯 system 也失败时必须抛出, 不能被降级掩盖")
    except RuntimeError:
        pass
    finally:
        _FAIL_PLAIN["v"] = False

    # §6
    _CACHE_OK["v"] = True
    try:
        u0 = dict(E.PROMPT_CACHE_USAGE)
        out6 = E.call_claude("p", "m", cached_system="S")
        u1 = E.PROMPT_CACHE_USAGE
        if out6 != "ok:cached" or u1["calls"] != u0["calls"] + 1 or u1["cache_read"] != u0["cache_read"] + 900 \
                or u1["input"] != u0["input"] + 100 or u1["output"] != u0["output"] + 50:
            fails.append(f"§6 essence 没按 usage 累加: {u0} → {dict(u1)}")
        summ = E.prompt_cache_summary()
        tot = summ["input"] + summ["cache_write"] + summ["cache_read"]
        if summ.get("read_share") != (round(summ["cache_read"] / tot, 3) if tot else None) or "fallbacks" not in summ:
            fails.append(f"§6 prompt_cache_summary 口径不对: {summ}")
        l0 = C.PROMPT_CACHE_USAGE["cache_read"]
        C.call_anthropic("p", "m", system=[{"type": "text", "text": "S", "cache_control": {"type": "ephemeral"}}])
        if C.PROMPT_CACHE_USAGE["cache_read"] != l0 + 900:
            fails.append(f"§6 librarian 没按 usage 累加: {C.PROMPT_CACHE_USAGE}")
    finally:
        _CACHE_OK["v"] = False
    if '"prompt_cache"' not in inspect.getsource(E.main):
        fails.append("§6 essence 的 Done 行没带 prompt_cache")
    import annotate_feature_pass as F
    if 'prompt_cache_summary()' not in inspect.getsource(F.main):
        fails.append("§6 特征层的 Done 行没带 prompt_cache")
    if 'PROMPT_CACHE_USAGE' not in Path(HERE.parent / "librarian" / "app.py").read_text(encoding="utf-8"):
        fails.append("§6 librarian /health 没回显 prompt_cache_usage")

    for f in fails:
        print("  ❌", f)
    if fails:
        print(f"❌ prompt cache fallback: {len(fails)} 条不过")
        return 1
    print("✅ prompt cache fallback: §1 馆员计数 · §2 essence 计数 · §3 /health · §4 Done 行 · §5 真错误仍抛 · §6 实际缓存读写 全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
