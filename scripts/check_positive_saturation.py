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
    0 = 所有池子【全部条目】都测过且都在阈值下(真健康)
    1 = 至少一个池子饱和
    2 = 至少一个池子【没测全】(部分或全部正例没标 essence, 拿不到 lever) ——
        不是健康, 只是没数据。cron/运维不要把它当 0 处理。

⚠️ 光看退出码分不出"确实饱和(1)"和"脚本崩了(Python 也是 1)"。所以正常跑完时
main() 末尾必打一行 `SATURATION_CHECK_DONE rc=<码>`; daily-sync.yml 靠有没有这
一行判定崩溃, 不靠退出码。改这个约定要同步改那边的 grep。

⚠️ 2 的判据是【测全】而不是【测到过】: 5 条里只有 2 条能测, ratio 是拿那 2 条
算的, 另外 3 条完全未知、可能全是同一个 lever。那种情况报 ok 就违背了"退出 0
表示每个池子都测过"这个承诺。

触发条件 (来自延后清单 🟡 慢性病): 第一次手动 review 时观察到 "近 1 个月
positive items 80%+ 都是同一种调性". 这个脚本能在你"感觉到"之前先看到.
"""

from __future__ import annotations

import argparse
import sys

# ⚠️ 故意【不】在模块顶层 import _common: 那会拖进 supabase / yaml。
# report() 下面是纯函数、只用 stdlib, 这样 CI 的冒烟测试(ci.yml "saturation
# 渲染路径冒烟测试")能在裸环境里直接 import 本模块跑渲染路径。
# 本脚本在 daily-sync.yml 里是 `|| true` 调用的, 渲染路径里一个 NameError 会被
# 完全吞掉 —— 2026-08-22 就真发生过一次(pool_n 未赋值), 而它吞掉的恰好是
# v1_8 专门修的那个盲点。所以渲染路径必须能被离线测到。别把 import 挪回顶层。


def report(rows: list[dict], threshold: float) -> int:
    """把 view 的行渲染成报告并返回退出码。纯函数, 不碰网络 —— 见上方注释。

    退出码语义见模块 docstring: 0=全部测过且健康 / 1=至少一个饱和 / 2=至少一个没测全。
    """
    if not rows:
        print(
            "No positive examples labeled in any autowriter project. "
            "(v1_8 起本脚本已统计 native 正例; 仍为空 = 确实一条都没标过, "
            "而不是老版本那个 external_source 盲点.)")
        return 0

    warnings = 0
    print()
    print("=" * 96)
    print(f"  Positive pool saturation · {len(rows)} autowriter project(s) · threshold={threshold}")
    print("=" * 96)
    # ⚠️ 必须打 pool_user_id: view 现在【按 project × user 分区】, 同一个项目
    # 会出现多行。只打 project 的话, 一个饱和的私有池和一个健康的私有池看起来
    # 就是两行重复的项目, 没法知道该找谁去改 —— per-user 监控就白做了。
    print(f"  {'aw_project_id':<38} {'user':<10} {'pool':<5} {'meas':<5} "
          f"{'levers':<7} {'top_n':<6} {'ratio':<6}  status")
    print("  " + "-" * 104)
    for r in rows:
        ratio = r.get("dominant_lever_ratio")
        # ⚠️ 这两个 `or 0` 不是防御性冗余: view 里 measurable / pool_n 都可能
        # 回 NULL(一条都 join 不到 notes 时), 而下面 f"{x:<5}" 对 None 会抛
        # TypeError。别删。
        measurable = r.get("lever_measurable_count") or 0
        pool_n = r.get("active_positive_count") or 0
        # ⚠️ 判据是【测全】不是【测到过】: 池子里 5 条、只有 2 条能测出 lever 时,
        # ratio 只代表那 2 条, 另外 3 条完全未知、可能全是同一个 lever。所以
        # measurable < pool_n 也算没测全 —— 否则文件头 "退出 0 = 所有池子全部
        # 条目都测过" 这个承诺是假的, v1_8 要暴露的假阴性就原样回来了。
        # 这一行必须和下面 unmeasurable_n 的判据完全一致。
        unmeasurable = (ratio is None or measurable < pool_n)
        warn = (ratio is not None and ratio >= threshold)
        if warn:
            warnings += 1
        if unmeasurable:
            flag = f"— 无法评估(仅 {measurable}/{pool_n} 条可测 essence)"
        elif warn:
            flag = "⚠ SATURATED"
        else:
            flag = "ok"
        ratio_txt = f"{ratio:<6.2f}" if ratio is not None else f"{'n/a':<6}"
        uid = r.get("pool_user_id")
        uid_txt = (str(uid)[:8] if uid else "(无归属)")
        print(
            f"  {str(r['aw_project_id']):<38} "
            f"{uid_txt:<10} "
            f"{pool_n:<5} "
            f"{measurable:<5} "
            f"{r['distinct_lever_count'] or 0:<7} "
            f"{r['top_lever_count']:<6} "
            f"{ratio_txt}  {flag}"
        )
        if r.get("lever_distribution"):
            print(f"  {'':38}   levers: {r['lever_distribution']}")

    unmeasurable_n = sum(
        1 for r in rows
        if r.get("dominant_lever_ratio") is None
        or (r.get("lever_measurable_count") or 0) < (r.get("active_positive_count") or 0)
    )
    print()
    if unmeasurable_n:
        print(f"  — {unmeasurable_n} 个池子没测全: 池子里有运营在 aw 手标的 native "
              "条目, 它们没有对应的 truth_vault.notes 记录, 取不到 emotional_lever。"
              "想让它可测, 需要给这些正例补 essence 标注。")
        for r in rows:
            m = r.get("lever_measurable_count") or 0
            n = r.get("active_positive_count") or 0
            if r.get("dominant_lever_ratio") is None or m < n:
                uid = r.get("pool_user_id")
                print(f"      · {r['aw_project_id']} / user "
                      f"{str(uid)[:8] if uid else '(无归属)'}: {m}/{n} 条可测")
    if warnings:
        print(f"  ⚠ {warnings} pool(s) over threshold {threshold}. "
              "Consider widening content angles or running essence annotation "
              "to make diversity filter more effective.")
        return 1
    if unmeasurable_n:
        # ⚠️ 不能在这里打 "✓ All under threshold" 然后 return 0。
        # "没测到" 不是 "健康" —— 而 native-only 恰恰是这个 view 修完之后的
        # 常态(见 v1_8 的说明), 所以这条路径是主路径不是边角。cron 或运维只看
        # 退出码的话, 会把"一条都没测到"读成"多样性很好", 正是 v1_8 要暴露的
        # 那个假阴性又原样回来了。用一个区别于 0/1 的退出码。
        print(f"  ⊘ 有 {unmeasurable_n} 个池子没测全, 无法判定是否饱和 —— "
              "这【不是】健康, 只是没数据。给这些正例补 essence 标注才能评估。")
        print("    (exit 2 = 没测全; exit 1 = 确实饱和; exit 0 = 全部测过且健康)")
        return 2
    print(f"  ✓ All {len(rows)} pool(s) measured and under threshold {threshold}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--threshold", type=float, default=0.6,
                        help="dominant_lever_ratio above this triggers a warning (default 0.6)")
    args = parser.parse_args()

    from _common import get_supabase_client  # 局部 import, 理由见 report() 上方

    sb = get_supabase_client()
    rows = (
        sb.schema("truth_vault")
        .table("v_autowriter_positive_pool_saturation")
        .select("*")
        .execute()
    ).data or []
    rc = report(rows, args.threshold)
    # ⚠️ 哨兵行, daily-sync.yml 靠它区分"跑完了"和"崩了"。
    # 本脚本在那边是 `|| true` 调的, 而 Python 崩溃的退出码也是 1 —— 和本脚本
    # "确实饱和"的 1 撞车, 光看退出码分不出来。所以约定: 正常跑完必打这一行,
    # 没打 = 崩了。改退出码语义时记得同步 daily-sync.yml 里那段 grep。
    print(f"SATURATION_CHECK_DONE rc={rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
