#!/usr/bin/env python3
"""CI 守卫: verify_supabase_state.sql #92 / #92b 和备份登记册 docs/backup-registry.md 对得上 (S-02, D-136)。

#92 原来数「名字带日期、过了 30 天的备份表」, 提示「> 0 = 该 drop 了」; D-136 之后备份都留着, 它就一直 > 0、越来越大,
而且看不见 autowriter._bak_MMDD_* 这种名字。11-25 改成数「名字像备份、却没登记的表」, 期望 0。

  §1 #92 和 #92b 用同一条「名字像备份」的规则, 它认得 _bak_1111_x、backup_x_20261009、x_20261009, 不认 notes
  §2 #92 的 VALUES 列表 = 登记册表格第一列, 一条不差、不重复; 每条都是 ^…$ 整串、能编译
  §3 truth_vault.backup_d129_ids_20261026 仍单独除外 (闸二按它定半区, D-128 补记), 也在登记册里
  §4 #92 的提示不再说「该 drop」(D-136: 不删); #92b 期望 0
  §5 一张没登记的 _bak_ 表 (合成名) 规则认得出来、登记册里的规则一条也配不上它
  §6 登记册「来源」里点名的 scripts/ 文件都在盘上
  反证 (每次都跑): 删一条 VALUES / 提示写回「该 drop」/ 名字规则去掉 _bak_ 那一支 → 红

#92 在真库上怎么数, 由 scripts/check_verify_rows_pg.py (ci.yml sql job) 跑。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERIFY = ROOT / "scripts" / "verify_supabase_state.sql"
REGISTRY = ROOT / "docs" / "backup-registry.md"
NAME_RULE = "(backup|^_bak_[0-9]{4}_|_20[0-9]{6}$)"
D129 = "('truth_vault', 'backup_d129_ids_20261026')"


def row(sql: str, ord_: str) -> str:
    m = re.search(rf"SELECT '{ord_}',.*?(?=\nUNION ALL\n|\n\)\nSELECT\n)", sql, re.S)
    return m.group(0) if m else ""


def sql_patterns(r92: str) -> list[str]:
    m = re.search(r"VALUES\s*(.*?)\n\s*\)\n", r92, re.S)
    return re.findall(r"\('(\^[^']*)'\)", m.group(1)) if m else []


def doc_patterns(doc: str) -> list[str]:
    out = []
    for ln in doc.splitlines():
        m = re.match(r"\|\s*`(\^.*?\$)`\s*\|", ln)
        if m:
            out.append(m.group(1).replace("\\|", "|"))
    return out


def check(sql: str, doc: str) -> list[str]:
    fails: list[str] = []
    r92, r92b = row(sql, "92"), row(sql, "92b")
    if not r92 or not r92b:
        return ["verify_supabase_state.sql 里找不到 #92 或 #92b"]
    # §1
    for name, r in (("#92", r92), ("#92b", r92b)):
        if f"c.relname ~ '{NAME_RULE}'" not in r:
            fails.append(f"§1 {name} 的名字规则不是 {NAME_RULE}")
    rule = re.compile(NAME_RULE)
    for ok in ("_bak_1111_x", "backup_x_20261009", "x_20261009", "reference_samples_backup_tv_stale_20261008"):
        if not rule.search(ok):
            fails.append(f"§1 名字规则认不出 {ok}")
    for no in ("notes", "comments", "bak_1111_x"):
        if rule.search(no):
            fails.append(f"§1 名字规则把 {no} 也当成备份")
    # §2
    sp, dp = sql_patterns(r92), doc_patterns(doc)
    if not sp:
        fails.append("§2 #92 里找不到 VALUES 列表")
    if not dp:
        fails.append("§2 docs/backup-registry.md 里找不到规则表")
    for name, pats in (("#92", sp), ("登记册", dp)):
        dup = sorted({p for p in pats if pats.count(p) > 1})
        if dup:
            fails.append(f"§2 {name} 里重复了 {dup}")
    only_sql, only_doc = sorted(set(sp) - set(dp)), sorted(set(dp) - set(sp))
    if only_sql:
        fails.append(f"§2 只在 #92 里、登记册没有: {only_sql}")
    if only_doc:
        fails.append(f"§2 只在登记册里、#92 没有: {only_doc}")
    for p in sp:
        if not (p.startswith("^") and p.endswith("$")):
            fails.append(f"§2 规则要整串匹配 (^…$): {p}")
        try:
            re.compile(p)
        except re.error as exc:
            fails.append(f"§2 规则编译不了 {p}: {exc}")
    # §3
    if f"(n.nspname, c.relname) <> {D129}" not in r92:
        fails.append("§3 #92 没把 truth_vault.backup_d129_ids_20261026 单独除外")
    if not any(re.fullmatch(p, "truth_vault.backup_d129_ids_20261026") for p in dp if _ok(p)):
        fails.append("§3 登记册里没有 truth_vault.backup_d129_ids_20261026")
    # §4
    if "该 drop" in r92 or "该drop" in r92:
        fails.append("§4 #92 的提示还在说「该 drop」(D-136: 备份都留着)")
    if "\n    '0',\n" not in r92b:
        fails.append("§4 #92b 的期望要是 0")
    # §5
    probe = "autowriter._bak_1199_ci_unregistered"
    if not rule.search(probe.split(".", 1)[1]):
        fails.append(f"§5 名字规则认不出 {probe}")
    hit = [p for p in sp if _ok(p) and re.fullmatch(p, probe)]
    if hit:
        fails.append(f"§5 合成的没登记表 {probe} 被这些规则配上了 (规则太宽): {hit}")
    # §6
    for path in sorted(set(re.findall(r"`(scripts/[A-Za-z0-9_./-]+)`", doc))):
        if not (ROOT / path).exists():
            fails.append(f"§6 登记册点名的 {path} 不在盘上")
    return fails


def _ok(p: str) -> bool:
    try:
        re.compile(p)
        return True
    except re.error:
        return False


def main() -> int:
    sql = VERIFY.read_text(encoding="utf-8")
    doc = REGISTRY.read_text(encoding="utf-8")
    fails = check(sql, doc)
    # 反证: 改坏之后必须红
    r92 = row(sql, "92")
    first = re.search(r"\n\s*\('\^[^']*'\),", r92)
    cases = {
        "#92 删掉一条 VALUES": sql.replace(first.group(0), "", 1) if first else None,
        "#92 提示写回「该 drop」": sql.replace(r92, r92.replace("'0',\n", "'0',\n    '> 0 = 该 drop 了' ||\n", 1), 1),
        "名字规则去掉 _bak_ 那一支": sql.replace(r92, r92.replace(NAME_RULE, "(backup|_20[0-9]{6}$)", 1), 1),
    }
    for name, bad in cases.items():
        if bad is None or not check(bad, doc):
            fails.append(f"反证没红: {name}")
    for f in fails:
        print("  ❌", f)
    if fails:
        print(f"❌ 备份登记: {len(fails)} 条不过 (scripts/verify_supabase_state.sql #92 / #92b, docs/backup-registry.md)")
        return 1
    print(f"✅ 备份登记: #92 和登记册 {len(sql_patterns(r92))} 条规则一致 · 名字规则 / d129 除外 / 提示 / #92b 都对 · "
          f"{len(cases)} 条反证都红了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
