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

import os

__all__ = ["AuthDecision", "resolve", "auth_health", "AuthError"]

# 匿名开关认这些值。刻意收得很窄: "0" / "false" / 空字符串 / 随手写的 "no"
# 都不算开 —— 半开的鉴权比明确的开或关都危险。
_TRUTHY = frozenset({"1", "true", "yes", "on"})


class AuthError(Exception):
    """鉴权不通过。调用方负责翻成 HTTP 401（各服务用自己的 HTTPException）。"""


def _anonymous_allowed(prefix: str) -> bool:
    return (os.environ.get(f"{prefix}_ALLOW_ANONYMOUS") or "").strip().lower() in _TRUTHY


def resolve(prefix: str, provided: str | None, *, header: str) -> str:
    """校验一次调用。返回本次的模式名; 不通过就抛 ``AuthError``。

    ``prefix`` 是环境变量前缀(``LIBRARIAN`` / ``ONBOARDER`` / ``WORKER``)，
    ``header`` 只用于错误文案，让调用方一眼看出该带哪个头。
    """
    expected = os.environ.get(f"{prefix}_API_KEY")
    if expected:
        if provided != expected:
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
    """
    has_key = bool(os.environ.get(f"{prefix}_API_KEY"))
    anon = _anonymous_allowed(prefix)
    if has_key:
        mode = header
    elif anon:
        mode = (f"anonymous (显式设了 {prefix}_ALLOW_ANONYMOUS —— "
                f"任何人可调, 别用在公网)")
    else:
        mode = (f"locked ({prefix}_API_KEY 未配且未开匿名 —— 所有业务请求 401; "
                f"配上 key, 或本地开发设 {prefix}_ALLOW_ANONYMOUS=1)")
    return {
        "ok": has_key,
        "required": has_key,
        "anonymous_allowed": anon,
        "mode": mode,
    }
