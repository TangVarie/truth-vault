"""三个 FastAPI 服务共用的鉴权闸（跨库审计 2026-08-24 SUP-001）。

── 治的是什么 ────────────────────────────────────────────────────────────

librarian / onboarder / worker 三个服务原来各有一份一模一样的 ``_check_auth``：

    expected = os.environ.get("XXX_API_KEY")
    if not expected:
        return                       # 未配 = dev 模式, 放行

也就是说 **secret 漏配 = 端点对全世界敞开**。而这三个服务手里有什么：

  · librarian —— service-role 客户端读 lesson cards，且每次 miss 都打一次 LLM；
  · onboarder —— 未信任输入进模型，还会改写 mappings/*.yaml；
  · worker    —— 拿 service-role 凭据 **subprocess 跑仓库里的脚本**。

漏配不是假想: 改环境变量名、迁移 Railway service、新建 staging 环境，任何
一次都可能少一个 key，而**没有任何症状** —— 服务照常 200，日志照常干净。

── 为什么 /health 自曝不算修好 ──────────────────────────────────────────

原来的做法是 fail-open + 在 ``/health`` 里把 ``auth.ok=False`` 报出来。那个
自曝是**对的、要保留**，但它不是防线: 没有人会在事故之前去读 /health。真正
的防线只能是"没配就不干活"。

autowriter 那边的 deskcore 已经在 2026-08 走过同一条路(审计 ROB-003 /
SUP-002)，最后落在 fail-closed + 一个**显式的**匿名开关上。两个仓的同类
组件口径应该一致，否则"我们的服务默认安全吗"这个问题没有统一答案。

── 现在的三态 ────────────────────────────────────────────────────────────

  1. 配了 ``<SVC>_API_KEY``          → 正常校验                    (secure)
  2. 没配，也没开匿名                → **一律 401**                (locked)
  3. 没配，但显式设了
     ``<SVC>_ALLOW_ANONYMOUS=1``     → 放行，且 /health 大声说明   (anonymous)

第 3 态是给本地开发和一次性调试留的。它必须是**显式**的：一个人写下
``ALLOW_ANONYMOUS=1`` 的时候知道自己在做什么，而"忘了配 key"的人不知道。
这就是这次改动的全部内容 —— 把默认值从"敞开"换成"锁上"。
"""

from __future__ import annotations

import hmac
import os

# ⚠️ 只列**真的存在**的名字。这里曾经写着 ``AuthDecision`` —— 一个早期设计留下的
#    类名, 后来没实现。``from service_auth import *`` 会直接 AttributeError,
#    而这个模块是三个服务共用的鉴权闸, 导入炸掉就是三个服务一起起不来。
#    (codex review) CI 里有一条断言 __all__ 里每个名字都能取到。
__all__ = ["resolve", "auth_health", "AuthError"]

# 匿名开关认这些值。刻意收得很窄: "0" / "false" / 空字符串 / 随手写的 "no"
# 都不算开 —— 半开的鉴权比明确的开或关都危险。
_TRUTHY = frozenset({"1", "true", "yes", "on"})


class AuthError(Exception):
    """鉴权不通过。调用方负责翻成 HTTP 401（各服务用自己的 HTTPException）。"""


def _anonymous_allowed(prefix: str) -> bool:
    return (os.environ.get(f"{prefix}_ALLOW_ANONYMOUS") or "").strip().lower() in _TRUTHY


def _key_matches(provided: str | None, expected: str) -> bool:
    """恒定时间比对。

    ``provided != expected`` 会在**第一个不同的字节**处短路, 于是比对耗时泄露
    「猜对了前几个字符」—— 攻击者可以按字节把 key 试出来, 而不必穷举整个空间。
    三份旧实现都是裸 ``!=``; 这次把判据收敛成一处, 正好是把它换成
    ``hmac.compare_digest`` 的时候: 一个地方对了, 三个服务就都对了。

    远程 HTTP 上要利用这个侧信道很难(网络抖动淹没了纳秒级差异), 但难不等于
    没有, 而代价只有一次 encode。**这个函数唯一的职责就是比密钥**, 在这里留
    一个已知不安全的比较没有任何理由。

    ``compare_digest`` 只接受同类型且(对 str 而言)全 ASCII 的参数, 所以统一
    encode 成 bytes —— key 里出现非 ASCII 时裸传 str 会抛 TypeError, 那会变成
    500 而不是 401。
    """
    if provided is None:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def resolve(prefix: str, provided: str | None, *, header: str) -> str:
    """校验一次调用。返回本次的模式名; 不通过就抛 ``AuthError``。

    ``prefix`` 是环境变量前缀(``LIBRARIAN`` / ``ONBOARDER`` / ``WORKER``)，
    ``header`` 只用于错误文案，让调用方一眼看出该带哪个头。
    """
    expected = os.environ.get(f"{prefix}_API_KEY")
    if expected:
        if not _key_matches(provided, expected):
            raise AuthError(f"invalid or missing {header}")
        return "key"

    if _anonymous_allowed(prefix):
        return "anonymous"

    # ⚠️ 这里**不能**退回放行。见模块 docstring。
    raise AuthError(
        f"server auth not configured: {prefix}_API_KEY 未配。本服务持 "
        f"service-role 凭据, 匿名放行等于把它交给公网, 所以默认一律拒绝。"
        f"本地开发请显式设 {prefix}_ALLOW_ANONYMOUS=1。")


def auth_health(prefix: str, *, header: str) -> dict:
    """给 ``/health`` 回显的鉴权状态。

    ``ok`` 的含义是"这个服务现在是安全的": 配了 key 才算。显式匿名模式
    ``ok=False`` —— 它能跑, 但它不安全, 而 /health 不该把这两件事混为一谈。

    ⚠️ ``anonymous_allowed`` 报的是**当前真的会不会放行匿名**, 不是"那个环境
    变量设没设"。两者在 key 和开关**同时存在**时会分叉: ``resolve`` 先看 key,
    所以匿名并不生效, 而以前这里照实回 True —— /health 说"任何人可调", 实际
    每个不带 key 的请求都 401。运维照着它排查会往完全错的方向走。(codex review)

    但**光把它算成 False 又会丢掉一条真信息**: 生产上留着一个失效的
    ``ALLOW_ANONYMOUS``, 等哪天有人拿掉 key(轮换、迁移、清理环境变量), 它会
    **静默生效**, 服务从 401 变成全开而没有任何动静。所以那种情况在 ``mode``
    里明说, 并单独回一个 ``anonymous_flag_set`` —— 生效与否和设没设是两件事,
    分成两个字段说, 不要挤在一个布尔里。
    """
    has_key = bool(os.environ.get(f"{prefix}_API_KEY"))
    flag_set = _anonymous_allowed(prefix)
    effective_anon = flag_set and not has_key

    if has_key:
        mode = header
        if flag_set:
            mode += (f" ⚠️ {prefix}_ALLOW_ANONYMOUS 也设着 —— 当前被 key 压住不生效, "
                     f"但一旦 {prefix}_API_KEY 被拿掉它就会静默放开。建议删掉。")
    elif effective_anon:
        mode = (f"anonymous (显式设了 {prefix}_ALLOW_ANONYMOUS —— "
                f"任何人可调, 别用在公网)")
    else:
        mode = (f"locked ({prefix}_API_KEY 未配且未开匿名 —— 所有业务请求 401; "
                f"配上 key, 或本地开发设 {prefix}_ALLOW_ANONYMOUS=1)")
    return {
        "ok": has_key,
        "required": has_key,
        # 生效与否
        "anonymous_allowed": effective_anon,
        # 设没设(即使当前不生效) —— 留着它才能发现"拿掉 key 就会开门"这种配置
        "anonymous_flag_set": flag_set,
        "mode": mode,
    }
