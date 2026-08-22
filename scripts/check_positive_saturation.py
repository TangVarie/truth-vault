"""
check_positive_saturation.py
═══════════════════════════════════════════════════════════════════════════

读 truth_vault.v_autowriter_positive_pool_saturation, 显示每个 autowriter
项目当前正在被注入 build_system_prompt 的 5 条 positive 样本的 lever
分布情况. 单 lever 占比 > 0.6 的项目会被标红 — 这意味着 autowriter 学到
的 vibe 已经趋同, 受众容易疲劳.

不写库, 不告警, 只 print. 想要 cron 自动告警时, 在 daily-sync.yml 加一步
跑这个脚本并 set-output 之类即可.

⚠️ 2026-08-22 (D-041) 修了一个让本脚本从上线起就没真正生效过的盲点:
view 原来只统计 external_source='truth_vault' 的正例, 而 push 通道从没真跑过
(那列生产库里全 NULL), 于是本脚本【永远】打印 "No active positive examples".
它测不到运营自己手标的 native 正例 —— 而那才是真正在注入 prompt 的池子.
修复见 schemas/notes_v1_8_positive_pool_saturation_fix.sql.

native 正例没有 external_source_id, join 不到 truth_vault.notes, 所以拿不到
emotional_lever. 本脚本现在会把"池子里几条 / 其中几条能测多样性"分开报,
测不了就直说测不了, 不再显示成"健康".

用法:
    python check_positive_saturation.py
    python check_positive_saturation.py --threshold 0.5   # 更严的告警线

退出码:
    0 = 所有池子都测过且都在阈值下(真健康)
    1 = 至少一个池子饱和
    2 = 至少一个池子【测不了】(正例没标 essence, 拿不到 lever) —— 不是健康,
        只是没数据。cron/运维不要把它当 0 处理。

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
        logger.info(
            "No positive examples labeled in any autowriter project. "
            "(v1_8 起本脚本已统计 native 正例; 仍为空 = 确实一条都没标过, "
            "而不是老版本那个 external_source 盲点.)")
        return 0

    warnings = 0
    print()
    print("=" * 96)
    print(f"  Positive pool saturation · {len(rows)} autowriter project(s) · threshold={args.threshold}")
    print("=" * 96)
    print(f"  {'aw_project_id':<40} {'pool':<5} {'meas':<5} {'levers':<7} "
          f"{'top_n':<6} {'ratio':<6}  status")
    print("  " + "-" * 92)
    for r in rows:
        ratio = r.get("dominant_lever_ratio")
        measurable = r.get("lever_measurable_count")
        # ratio 为 NULL = 一条都测不到 lever(native 正例没有 essence 标注),
        # 这【不是健康】, 是测不了. 单独标出来, 别混进 ok.
        unmeasurable = (ratio is None or not measurable)
        warn = (ratio is not None and ratio >= args.threshold)
        if warn:
            warnings += 1
        if unmeasurable:
            flag = "— 无法评估(正例未标 essence)"
        elif warn:
            flag = "⚠ SATURATED"
        else:
            flag = "ok"
        ratio_txt = f"{ratio:<6.2f}" if ratio is not None else f"{'n/a':<6}"
        print(
            f"  {r['aw_project_id']:<40} "
            f"{r['active_positive_count']:<5} "
            f"{measurable or 0:<5} "
            f"{r['distinct_lever_count'] or 0:<7} "
            f"{r['top_lever_count']:<6} "
            f"{ratio_txt}  {flag}"
        )
        if r.get("lever_distribution"):
            print(f"  {'':40}   levers: {r['lever_distribution']}")

    unmeasurable_n = sum(
        1 for r in rows
        if r.get("dominant_lever_ratio") is None or not r.get("lever_measurable_count")
    )
    print()
    if unmeasurable_n:
        print(f"  — {unmeasurable_n} 个池子无法评估多样性: 这些正例是运营在 aw "
              "手标的 native 条目, 没有对应的 truth_vault.notes 记录, 取不到 "
              "emotional_lever. 想让它可测, 需要给这些正例补 essence 标注。")
    if warnings:
        print(f"  ⚠ {warnings} pool(s) over threshold {args.threshold}. "
              "Consider widening content angles or running essence annotation "
              "to make diversity filter more effective.")
        return 1
    if unmeasurable_n:
        # ⚠️ 不能在这里打 "✓ All under threshold" 然后 return 0。
        # "没测到" 不是 "健康" —— 而 native-only 恰恰是这个 view 修完之后的
        # 常态(见 v1_8 的说明), 所以这条路径是主路径不是边角。cron 或运维只看
        # 退出码的话, 会把"一条都没测到"读成"多样性很好", 正是 v1_8 要暴露的
        # 那个假阴性又原样回来了。用一个区别于 0/1 的退出码。
        print(f"  ⊘ 有 {unmeasurable_n} 个池子测不了, 无法判定是否饱和 —— "
              "这【不是】健康, 只是没数据。给这些正例补 essence 标注才能评估。")
        print("    (exit 2 = 无法评估; exit 1 = 确实饱和; exit 0 = 测过且健康)")
        return 2
    print(f"  ✓ All {len(rows)} pool(s) measured and under threshold {args.threshold}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
