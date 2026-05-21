"""
check_positive_saturation.py
═══════════════════════════════════════════════════════════════════════════

读 truth_vault.v_autowriter_positive_pool_saturation, 显示每个 autowriter
项目当前正在被注入 build_system_prompt 的 5 条 positive 样本的 lever
分布情况. 单 lever 占比 > 0.6 的项目会被标红 — 这意味着 autowriter 学到
的 vibe 已经趋同, 受众容易疲劳.

不写库, 不告警, 只 print. 想要 cron 自动告警时, 在 daily-sync.yml 加一步
跑这个脚本并 set-output 之类即可.

用法:
    python check_positive_saturation.py
    python check_positive_saturation.py --threshold 0.5   # 更严的告警线

触发条件 (来自延后清单 🟡 慢性病): 第一次手动 review 时观察到 "近 1 个月
positive items 80%+ 都是同一种调性". 这个脚本能在你"感觉到"之前先看到.
"""

from __future__ import annotations

import argparse
import sys

from _common import get_supabase_client, setup_logger


logger = setup_logger("check_positive_saturation")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--threshold", type=float, default=0.6,
                        help="dominant_lever_ratio above this triggers a warning (default 0.6)")
    args = parser.parse_args()

    sb = get_supabase_client()
    rows = (
        sb.schema("truth_vault")
        .table("v_autowriter_positive_pool_saturation")
        .select("*")
        .execute()
    ).data or []

    if not rows:
        logger.info("No active positive examples in any autowriter project.")
        return 0

    warnings = 0
    print()
    print("=" * 96)
    print(f"  Positive pool saturation · {len(rows)} autowriter project(s) · threshold={args.threshold}")
    print("=" * 96)
    print(f"  {'aw_project_id':<40} {'count':<6} {'levers':<7} {'top_n':<6} {'ratio':<6}  status")
    print("  " + "-" * 92)
    for r in rows:
        ratio = r.get("dominant_lever_ratio")
        warn = (ratio is not None and ratio >= args.threshold)
        if warn:
            warnings += 1
        flag = "⚠ SATURATED" if warn else "ok"
        print(
            f"  {r['aw_project_id']:<40} "
            f"{r['active_positive_count']:<6} "
            f"{r['distinct_lever_count'] or 0:<7} "
            f"{r['top_lever_count']:<6} "
            f"{(ratio if ratio is not None else 0):<6.2f}  {flag}"
        )
        if r.get("lever_distribution"):
            print(f"  {'':40}   levers: {r['lever_distribution']}")

    print()
    if warnings:
        print(f"  ⚠ {warnings} project(s) over threshold {args.threshold}. "
              "Consider widening content angles or running essence annotation "
              "to make diversity filter more effective.")
        return 1
    print(f"  ✓ All projects under threshold {args.threshold}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
