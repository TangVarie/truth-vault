#!/usr/bin/env python3
"""CI 守卫: secret 掩码真的挂在 logger 出口上 (2026-10-08 审计 B-11, RISKS R-023 的后记)。

R-023 2026-05-22 记着 "TV: mask_secrets() 已关闭", 而 mask_secrets 从那天起**零调用点**:
setup_logger 用的是普通 Formatter, supabase-py 异常里的 bearer / URL 原样进 Actions 日志。
这里不测 mask_secrets 的正则 (那是它自己的事), 测的是**出口**: 经 setup_logger 建的 logger,
消息、%-参数、traceback 三条路都得被掩掉; 顺带钉住"源码里至少有一个非定义处引用它"。

  §1 消息里的 JWT / sb_secret / sk-ant 被掩
  §2 %-参数里的 key 被掩 (调用方 logger.info("key=%s", key) 这种最常见)
  §3 logger.exception 的 traceback 里 (异常文本带 key) 被掩
  §4 _common.py 里 mask_secrets 的引用 ≥ 1 处不是定义 (再变成死代码就红)
  §5 不走 setup_logger 的 handler 不受影响 (说清挡不住什么, 不假装全覆盖)
  §6 print() 不直接打异常文本 (2026-11-25 S-09, D-095 补): 扫 scripts/ onboarder/ worker/ librarian/,
     `except … as X:` 里的 print(...) 用到 X 时必须包在 mask_secrets(...) 里; 只用 type(X) / X.name 不算。
     反证: 去掉一处包装 → 红。

§6 挡不住的:
  · 先把异常存进别的变量再打 (msg = str(exc); print(msg))、或在 except 外面打。
  · sys.stdout / sys.stderr.write、logging 以外自建的 handler、写进文件或 PR 正文的异常文本。
  · 不故意全局包 sys.stdout: 正常输出里也会有 eyJ 开头的 base64-JSON, 全局打码会悄悄改掉它们。
"""
from __future__ import annotations

import ast
import io
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

JWT = "eyJ" + "a" * 30 + "." + "b" * 30 + "." + "c" * 30
SB = "sb_secret_" + "Q" * 40
ANT = "sk-ant-" + "z" * 40


def _logger_with_buffer(name: str):
    lg = C.setup_logger(name)
    buf = io.StringIO()
    # 把 setup_logger 装的那个 handler 的流换成内存: 测的正是它的 formatter
    h = lg.handlers[0]
    h.stream = buf
    return lg, buf


ROOT = Path(__file__).resolve().parent.parent
PRINT_SCAN_DIRS = ("scripts", "onboarder", "worker", "librarian")
SAFE_ATTRS = {"name", "__class__"}   # ImportError.name 是模块名; 类名不带文本


def unmasked_exception_prints(src: str) -> list[tuple[int, str]]:
    """`except … as X:` 里, print(...) 用到 X 却没包 mask_secrets 的地方: [(行号, X)]。"""
    tree = ast.parse(src)
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for ch in ast.iter_child_nodes(node):
            parents[id(ch)] = node

    def safe(name_node: ast.Name, stop: ast.AST) -> bool:
        cur = name_node
        while cur is not stop:
            par = parents.get(id(cur))
            if par is None:
                return False
            if isinstance(par, ast.Call):
                fn = par.func
                fname = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
                if fname == "mask_secrets":
                    return True
                if fname == "type" and cur in par.args:
                    return True
            if isinstance(par, ast.Attribute) and par.value is cur and par.attr in SAFE_ATTRS:
                return True
            cur = par
        return False

    hits: list[tuple[int, str]] = []
    for h in ast.walk(tree):
        if not (isinstance(h, ast.ExceptHandler) and h.name):
            continue
        for st in h.body:
            for call in ast.walk(st):
                if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "print"):
                    continue
                for n in ast.walk(call):
                    if isinstance(n, ast.Name) and n.id == h.name and not safe(n, call):
                        hits.append((call.lineno, h.name))
                        break
    return sorted(set(hits))


def check_prints() -> list[str]:
    fails: list[str] = []
    n_files = 0
    for d in PRINT_SCAN_DIRS:
        for p in sorted((ROOT / d).rglob("*.py")):
            n_files += 1
            for line, name in unmasked_exception_prints(p.read_text(encoding="utf-8")):
                fails.append(f"§6 {p.relative_to(ROOT)}:{line} print 直接用了异常 {name}; "
                             f"改成 mask_secrets(str({name})) (secret_mask.py)")
    # 反证: 去掉一处包装必须红
    probe = ROOT / "scripts" / "backfill_content_layer.py"
    src = probe.read_text(encoding="utf-8")
    if "mask_secrets(str(exc))" not in src:
        fails.append("§6 反证用的 backfill_content_layer.py 里找不到 mask_secrets(str(exc)) —— 反证失效, 换一个文件")
    elif not unmasked_exception_prints(src.replace("mask_secrets(str(exc))", "str(exc)", 1)):
        fails.append("§6 反证没红: 去掉 backfill_content_layer.py 的一处 mask_secrets 之后扫描没发现")
    if n_files < 50:
        fails.append(f"§6 只扫到 {n_files} 个 .py, 目录结构变了? 扫描在空转")
    return fails


def main() -> int:
    fails: list[str] = []

    # §1 消息里的 secret
    lg, buf = _logger_with_buffer("check_mask_1")
    lg.info(f"token {JWT} and {SB} and {ANT}")
    out = buf.getvalue()
    for s in (JWT, SB, ANT):
        if s in out:
            fails.append(f"§1 消息里的 secret 原样出去了: {s[:12]}…")
    if out.count("***REDACTED***") < 3:
        fails.append(f"§1 期望 3 处 REDACTED, 实际 {out.count('***REDACTED***')}")

    # §2 %-参数
    lg, buf = _logger_with_buffer("check_mask_2")
    lg.warning("auth failed for key=%s", SB)
    if SB in buf.getvalue() or "***REDACTED***" not in buf.getvalue():
        fails.append("§2 %-参数里的 key 没被掩")

    # §3 traceback
    lg, buf = _logger_with_buffer("check_mask_3")
    try:
        raise RuntimeError(f"401 Unauthorized: Bearer {JWT}")
    except RuntimeError:
        lg.exception("supabase call failed")
    out = buf.getvalue()
    if "Traceback" not in out:
        fails.append("§3 logger.exception 没打 traceback (测试本身坏了)")
    if JWT in out:
        fails.append("§3 traceback 里的 JWT 原样出去了")

    # §4 源码引用
    src = (Path(__file__).resolve().parent / "_common.py").read_text(encoding="utf-8")
    refs = [m.start() for m in re.finditer(r"\bmask_secrets\b", src)]
    non_def = [p for p in refs if not src[max(0, p - 4):p].endswith("def ")]
    # 去掉 docstring / 注释里的提及: 只认代码行 (行首去空白后不以 # 开头、且不在三引号串里粗判)
    code_refs = 0
    for line in src.splitlines():
        s = line.strip()
        if s.startswith("#") or s.startswith("def mask_secrets"):
            continue
        if "mask_secrets(" in s and not s.startswith(('"""', "'''")):
            code_refs += 1
    if code_refs < 1:
        fails.append(f"§4 _common.py 里 mask_secrets 没有代码引用 (非定义引用 {len(non_def)} 处, 代码调用 {code_refs})"
                     " —— 它又成死代码了")

    # §5 挡不住什么: 自建 handler 不经 formatter
    raw = logging.getLogger("check_mask_raw")
    rb = io.StringIO()
    rh = logging.StreamHandler(rb)
    raw.addHandler(rh)
    raw.setLevel(logging.INFO)
    raw.propagate = False
    raw.info(SB)
    if SB not in rb.getvalue():
        fails.append("§5 自建 handler 不该被掩 (测试假设变了: 若全局 root 也挂了掩码, 更新本节)")

    # §6 print() 不直接打异常文本
    fails += check_prints()

    for f in fails:
        print("  ❌", f)
    if fails:
        print(f"❌ secret masking: {len(fails)} 条不过")
        return 1
    print("✅ secret masking: §1 消息 · §2 %-参数 · §3 traceback · §4 源码引用 · §5 边界 · §6 print 六节全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
