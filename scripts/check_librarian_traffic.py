"""
check_librarian_traffic.py
═══════════════════════════════════════════════════════════════════════════

通道 2(TV → 写作台, pull / LLM 馆员, D-038)有没有人来借? —— 只读, 不写库。

2026-09-17 复核(D-063)发现这条通道暗了三个月没人知道: 30 天里写作台生成了 82 个
batch / 713 个版本, 馆员只收到 8 个 brief、集中在 3 天, 最重的三天一次都没调。
两边都不会红 —— aw 那边馆员客户端是 fail-open(任何失败静默返 `[]`, 包括
LIBRARIAN_URL / LIBRARIAN_API_KEY 没配), TV 这边夜跑的飞轮状态只印 →ssll。
本脚本就是给通道 2 装的那盏灯。

判据只有一条(故意不做比例启发式):
    窗口内写作台有 batch, 而馆员缓存零流量 → 通道暗着(rc=1)。
为什么不做比例: 缓存按 brief 摘要去重, 同一个 brief 反复命中只刷 last_hit_at 一次,
"brief 数 / batch 数"天然偏低, 拿比例告警会天天红(D-053: 天天红的 CI 等于没有 CI)。
"零 vs 非零"抓的正是复核里看到的形状(一天 15 个 batch、0 次借阅)。

数据来源:
    写作台生成量 = autowriter.batches(created_at 在窗口内), versions 只作参考
    馆员流量     = truth_vault.flywheel_librarian_cache(last_hit_at 在窗口内; 新 brief 的
                   last_hit_at = created_at, 重复命中只刷 last_hit_at)
                   ⚠️ 只数写作台的两个 consumer(autowriter / deskcore, 见 _DESK_CONSUMERS)。
                   馆员是共享服务: ssll(R-033 可选升级)、docs/19 的诊断 curl 也会打它, 那些流量
                   不能替写作台"证明通着"(codex review on #133)。别的 consumer 照印, 不计。
    ⚠️ 缓存表由 prune_librarian_cache.py 按 30 天 TTL 清理, 本脚本窗口远在其内。

窗口: 默认 48 小时, 故意比每日 cron 长一倍 —— 夜跑 02:00 若被排队/漏跑一天, 24h 窗口会留下
    没人评估过的空档(codex review on #133); 48h 让每个 batch 至少被看两次, 漏一天也补得上。
    "零 vs 非零"的判据不因窗口变长而变软: 暗着就是暗着。

用法:
    python check_librarian_traffic.py                 # 默认看过去 48 小时(+7 天参考)
    python check_librarian_traffic.py --window-hours 72

退出码:
    0 = 窗口内没生成(无从判)或 生成了且馆员有流量
    1 = 窗口内有生成、馆员零流量 —— 通道 2 暗着(修在 aw 仓, 见 docs/27)
⚠️ 和 check_positive_saturation.py 同一个约定: 正常跑完末尾必打一行
`LIBRARIAN_TRAFFIC_CHECK_DONE rc=<码>`; daily-sync.yml 靠有没有这一行判定崩溃,
不靠退出码(Python 崩溃也是 1)。改这个约定要同步改那边的 grep。
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

# ⚠️ 故意【不】在模块顶层 import _common(会拖进 supabase / yaml)。report() 是纯函数,
# CI 在裸环境里直接 import 本模块测它 —— 同 check_positive_saturation.py 的理由。

# 写作台的两个 consumer 值: aw 主路径(librarian_client 填 "autowriter") / deskcore MCP 路径。
# 只有它们的流量算"写作台来借了"。改 aw 那边的 consumer 值要同步改这里。
_DESK_CONSUMERS: tuple[str, ...] = ("autowriter", "deskcore")
# 默认窗口必须 > 24h(cron 间隔), 与相邻两次夜跑重叠 —— CI 钉着这一点。
DEFAULT_WINDOW_HOURS = 48


def report(stats: dict, window_hours: int) -> int:
    """把 gather() 的统计渲染成报告并返回退出码。纯函数, 不碰网络。"""
    b = stats["aw_batches"]
    v = stats.get("aw_versions", 0)
    hits = stats["lib_hits"]
    new = stats.get("lib_new_briefs", 0)
    by_consumer = stats.get("lib_by_consumer") or {}
    b7, hits7 = stats.get("aw_batches_7d", 0), stats.get("lib_hits_7d", 0)

    print()
    print("=" * 84)
    print(f"  通道 2 借阅流量 · 过去 {window_hours}h · 写作台 batch={b} (版本 {v}) · "
          f"馆员流量={hits} (其中新 brief {new})")
    print("=" * 84)
    if by_consumer:
        print("  按 consumer(只有 " + "/".join(_DESK_CONSUMERS) + " 算写作台): "
              + ", ".join(f"{k}={n}" for k, n in sorted(by_consumer.items())))
    print(f"  7 天参考: 写作台 batch={b7} · 写作台借阅={hits7}")
    others = sum(n for k, n in by_consumer.items() if k not in _DESK_CONSUMERS)

    if b == 0:
        print("  · 窗口内写作台没有生成, 通道 2 无从判定(不是健康, 是没活) —— ok")
        return 0
    if hits == 0:
        msg = (f"写作台过去 {window_hours}h 生成了 {b} 个 batch, 馆员一次都没被写作台调过"
               + (f"(馆员另有 {others} 次来自别的消费方, 不算)" if others else "")
               + f" —— 通道 2(TV → 写作台经验卡)暗着。修在 autowriter 仓: 生成主路径没接 "
               f"librarian_client, 或部署缺 LIBRARIAN_URL / LIBRARIAN_API_KEY(fail-open 静默返 [])。"
               f"接线说明见 docs/27。")
        print(f"  ⚠ {msg}")
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print(f"::warning title=通道 2 暗着(写作台生成了但没来借)::{msg}", flush=True)
        return 1
    print(f"  ✓ 写作台在生成({b} batch), 也在向馆员借({hits}) —— 通道 2 通着")
    return 0


def gather(sb, since_iso: str, since7_iso: str) -> dict:
    """读两边的计数。只 count, 不拉行。"""
    def _count(schema: str, table: str, col: str, since: str) -> int:
        res = (sb.schema(schema).table(table)
               .select("*", count="exact", head=True)
               .gte(col, since)
               .execute())
        return int(res.count or 0)

    rows = (sb.schema("truth_vault").table("flywheel_librarian_cache")
            .select("consumer, created_at, last_hit_at")
            .gte("last_hit_at", since_iso)
            .execute()).data or []
    by_consumer: dict[str, int] = {}
    for r in rows:
        by_consumer[r.get("consumer") or "?"] = by_consumer.get(r.get("consumer") or "?", 0) + 1
    # 只有写作台的 consumer 算数(理由见文件头); 别的照印在 by_consumer 里, 不计入 hits。
    desk = [r for r in rows if (r.get("consumer") or "") in _DESK_CONSUMERS]
    res7 = (sb.schema("truth_vault").table("flywheel_librarian_cache")
            .select("*", count="exact", head=True)
            .gte("last_hit_at", since7_iso)
            .in_("consumer", list(_DESK_CONSUMERS))
            .execute())
    return {
        "aw_batches": _count("autowriter", "batches", "created_at", since_iso),
        "aw_versions": _count("autowriter", "versions", "created_at", since_iso),
        "lib_hits": len(desk),
        "lib_new_briefs": sum(1 for r in desk if (r.get("created_at") or "") >= since_iso),
        "lib_by_consumer": by_consumer,
        "aw_batches_7d": _count("autowriter", "batches", "created_at", since7_iso),
        "lib_hits_7d": int(res7.count or 0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--window-hours", type=int, default=DEFAULT_WINDOW_HOURS,
                        help=f"看过去多少小时的生成与借阅(默认 {DEFAULT_WINDOW_HOURS}, 与每日 cron 重叠)")
    args = parser.parse_args()
    if args.window_hours < 1:
        print("--window-hours 必须 >= 1")
        return 2
    now = datetime.now(timezone.utc)
    since = (now - timedelta(hours=args.window_hours)).replace(tzinfo=None).isoformat(timespec="seconds")
    since7 = (now - timedelta(days=7)).replace(tzinfo=None).isoformat(timespec="seconds")

    from _common import get_supabase_client  # 局部 import, 理由见文件头
    sb = get_supabase_client()
    stats = gather(sb, since, since7)
    rc = report(stats, args.window_hours)
    # ⚠️ 哨兵行: daily-sync.yml 靠它区分"跑完了"和"崩了"(那边是 `|| true` 调的)。
    print(f"LIBRARIAN_TRAFFIC_CHECK_DONE rc={rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
