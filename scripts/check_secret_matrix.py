#!/usr/bin/env python3
"""CI 守卫: TV workflow 用到的每个 secret 都在 RISKS.md R-032 的「密钥 → 持有者」矩阵里 (S-05)。

只看变量名, 不碰值。轮换一把钥匙时照这张表一行一行换; 新加的 workflow 用了某个 secret
却没写进表, 轮换时就会漏掉它, 夜跑悄悄坏掉。

  §1 .github/workflows/*.yml 里每个 `secrets.X` (去掉 GITHUB_TOKEN 和 *_URL) 在 R-032 这一节里出现
  §2 矩阵里第一格写了 `X` 的那一行, TV Actions 那一格写了用到 X 的每个 workflow (按文件名, 不带 .yml)
  反证 (每次都跑; --selftest 只跑反证): 删掉一行 / 格里少写一个 workflow / 多一个没登记的 secret → 红

挡不住的: 另外三个库的 workflow 和所有 Railway 服务 (TV 的 CI 看不到),
那边靠 docs/handoff-2026-11-22-four-repos.md §4.1 的清单; 也挡不住矩阵里写了、其实早就不用的旧条目。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {"GITHUB_TOKEN"}
SECRET = re.compile(r"secrets\.([A-Z][A-Z0-9_]*)")


def workflow_secrets(wf_dir: Path) -> dict[str, set[str]]:
    """secret 名 → 用它的 workflow (文件名去掉 .yml)。"""
    out: dict[str, set[str]] = {}
    for p in sorted(wf_dir.glob("*.yml")):
        for name in set(SECRET.findall(p.read_text(encoding="utf-8"))):
            if name in SKIP or name.endswith("_URL"):
                continue
            out.setdefault(name, set()).add(p.stem)
    return out


def r032_section(risks: str) -> str:
    m = re.search(r"### R-032 .*?(?=\n### R-|\Z)", risks, re.S)
    return m.group(0) if m else ""


def check(used: dict[str, set[str]], section: str) -> list[str]:
    if not section:
        return ["RISKS.md 里找不到「### R-032」这一节"]
    fails: list[str] = []
    rows = [ln for ln in section.splitlines() if ln.startswith("| `")]
    if not rows:
        return ["R-032 里找不到矩阵 (以「| `」开头的表格行)"]
    for name, wfs in sorted(used.items()):
        if not re.search(rf"(?<![A-Z0-9_]){name}(?![A-Z0-9_])", section):
            fails.append(f"§1 {name} 没在 R-032 里 (用到它的 workflow: {sorted(wfs)})")
            continue
        row = next((r for r in rows if f"`{name}`" in r.split("|")[1]), None)
        if row is None:
            fails.append(f"§2 R-032 矩阵里没有第一格写着 `{name}` 的那一行")
            continue
        tv_cell = row.split("|")[2]
        missing = sorted(w for w in wfs if not re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", tv_cell))
        if missing:
            fails.append(f"§2 `{name}` 那一行的 TV Actions 格没写这些 workflow: {missing}")
    return fails


def selftest(used: dict[str, set[str]], section: str) -> int:
    base = check(used, section)
    if base:
        print("❌ selftest: 本仓本身就不过, 先修本仓:\n  " + "\n  ".join(base))
        return 1
    srv = "SUPABASE_SERVICE_ROLE_KEY"
    row = next(r for r in section.splitlines() if r.startswith(f"| `{srv}`"))
    cases = {
        "workflow 用了一个矩阵里没有的 secret": ({**used, "CI_PROBE_NEW_KEY": {"daily-sync"}}, section, "§1"),
        "service_role 那一行的 TV Actions 格少写 gate2-run": (
            used, section.replace(row, row.replace(" · gate2-run", "", 1)), "§2"),
        "service_role 那一行整行删掉 (名字还在别处出现)": (
            used, section.replace(row + "\n", "", 1), "§2"),
    }
    bad = 0
    for name, (u, sec, want) in cases.items():
        got = check(u, sec)
        if any(g.startswith(want) for g in got):
            print(f"  ✓ 反证红了: {name} ({want})")
        else:
            print(f"  ❌ 反证没红: {name} (期望 {want}, 实际 {got})")
            bad += 1
    if bad:
        return 1
    print(f"✅ secret 矩阵 selftest: {len(cases)} 条反证都红了")
    return 0


def main() -> int:
    used = workflow_secrets(ROOT / ".github" / "workflows")
    section = r032_section((ROOT / "RISKS.md").read_text(encoding="utf-8"))
    if "--selftest" in sys.argv[1:]:
        return selftest(used, section)
    fails = check(used, section)
    for f in fails:
        print("  ❌", f)
    if fails:
        print(f"❌ secret 矩阵: {len(fails)} 条不过 —— 改 RISKS.md R-032 的矩阵和轮换步骤 ② (只写变量名)")
        return 1
    n_pairs = sum(len(v) for v in used.values())
    print(f"✅ secret 矩阵: TV workflow 用到的 {len(used)} 个 secret ({n_pairs} 处使用) 都在 R-032 里, 行里写了对应的 workflow")
    return selftest(used, section)   # 反证每次都跑 (CI 只调一行)


if __name__ == "__main__":
    sys.exit(main())
