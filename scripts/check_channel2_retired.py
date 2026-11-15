#!/usr/bin/env python3
"""通道 2 push (TV 爆款 → autowriter.items) 已退役 (D-038): 脚本留着备查, 真跑要显式放行 (D-154, 外部评审 E2)。

断行为不断源码 (D-051): 真的驱动 sync_truth_vault_baokuan_to_autowriter_items.main(), 连库 / 读候选 / 退役旧标三处打桩。
  §1 不带 --dry-run、不带放行开关 → 退出码 2, 库一次都不连 (连环境变量都不读)
  §2 --dry-run 照常跑 (不需要放行开关), 往下走到读候选; 写库的函数拿到的都是 dry_run=True
  §3 带 --i-know-channel2-is-retired 的真跑照旧放行 (脚本没被改坏, 只是多了一道确认)
  §4 文档里的真跑步骤标了「已退役」: scripts/README.md、autowriter-migrations/RUNBOOK.md、MIGRATION_PLAN.md、
     docs/13-flywheel-activation-runbook.md; verify_supabase_state.sql #53 不再把它当修法
  §5 夜跑 (daily-sync.yml) 里没有这一步

反证 (11-15 实跑, 都红): ① 去掉护栏 → §1; ② 护栏不看 --dry-run (dry-run 也拒) → §2; ③ 放行开关不管用 → §3。

跑法: cd scripts && python check_channel2_retired.py
"""
from __future__ import annotations

import logging
import pathlib
import sys

import sync_truth_vault_baokuan_to_autowriter_items as s

ROOT = pathlib.Path(__file__).resolve().parent.parent
FLAG = s.RETIRED_OVERRIDE_FLAG
assert FLAG == "--i-know-channel2-is-retired", FLAG

calls: list = []


def run(*argv: str) -> int:
    calls.clear()
    s.get_supabase_client = lambda: calls.append("connect") or object()
    s.fetch_injection_candidates = lambda sb, project_filter=None: calls.append(("candidates", project_filter)) or []
    s.retire_stale_autowriter_examples = lambda sb, dry_run=False: calls.append(("retire", dry_run)) or 0
    old_argv, old_level = sys.argv, s.logger.level
    s.logger.setLevel(logging.CRITICAL)      # 被拒绝的那一行 ERROR 是故意的, 不进 CI 输出
    try:
        sys.argv = ["sync_truth_vault_baokuan_to_autowriter_items.py", *argv]
        return s.main()
    finally:
        sys.argv = old_argv
        s.logger.setLevel(old_level)


# §1
for argv in ((), ("--project", "P"), ("--skip-retire",), ("--max-per-project", "3")):
    rc = run(*argv)
    assert rc == 2 and calls == [], f"真跑没带放行开关必须被拒绝、库一次都不连: argv={argv} rc={rc} calls={calls}"
print("✓ §1 不带 --dry-run 也不带放行开关: 退出码 2, 一行不写、库不连")

# §2
rc = run("--dry-run", "--project", "P")
assert rc == 0 and calls == ["connect", ("candidates", "P"), ("retire", True)], f"--dry-run 照常跑: rc={rc} calls={calls}"
print("✓ §2 --dry-run 不需要放行开关, 照常跑到底 (退役旧标那一步拿到的也是 dry_run=True)")

# §3
rc = run(FLAG)
assert rc == 0 and calls == ["connect", ("candidates", None), ("retire", False)], f"放行开关: rc={rc} calls={calls}"
rc = run(FLAG, "--skip-retire")
assert rc == 0 and calls == ["connect", ("candidates", None)], f"放行 + --skip-retire: rc={rc} calls={calls}"
print(f"✓ §3 带 {FLAG} 的真跑照旧放行")

# §4
for rel in ("scripts/README.md", "autowriter-migrations/RUNBOOK.md", "MIGRATION_PLAN.md",
            "docs/13-flywheel-activation-runbook.md"):
    text = (ROOT / rel).read_text(encoding="utf-8")
    name = "sync_truth_vault_baokuan_to_autowriter_items.py"
    assert name in text and "已退役" in text and "D-038" in text, f"{rel}: 提到这个脚本的地方要标「已退役 (D-038)」"
    for ln in text.splitlines():
        cmd = ln.strip().lstrip("$ ").strip()
        if cmd.startswith(("python " + name, "python scripts/" + name)) and "--dry-run" not in cmd:
            assert FLAG in cmd, f"{rel}: 还有一条不带 --dry-run、也不带放行开关的真跑命令: {ln.strip()}"
verify = (ROOT / "scripts" / "verify_supabase_state.sql").read_text(encoding="utf-8")
i = verify.find("SELECT '53',")
block = verify[i:verify.find("UNION ALL", i)]
assert i >= 0 and "python scripts/sync_truth_vault_baokuan_to_autowriter_items.py" not in block and "已退役" in block, \
    "verify_supabase_state.sql #53 不该再把这个脚本当修法 (不懂工程的人照着跑的就是这一格)"
print("✓ §4 README / RUNBOOK / MIGRATION_PLAN / docs/13 的真跑步骤标了已退役; verify #53 不再指向它")

# §5
wf = (ROOT / ".github" / "workflows" / "daily-sync.yml").read_text(encoding="utf-8")
runs = [ln for ln in wf.splitlines() if "sync_truth_vault_baokuan_to_autowriter_items.py" in ln and not ln.strip().startswith("#")]
assert not runs, f"夜跑里不该有这一步: {runs}"
print("✓ §5 夜跑里没有这一步")

print("\ncheck_channel2_retired: all checks passed")
