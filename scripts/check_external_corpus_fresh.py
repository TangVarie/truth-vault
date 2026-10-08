#!/usr/bin/env python3
"""
check_external_corpus_fresh.py
═══════════════════════════════════════════════════════════════════════════

外部语料 (Jev 仓的 external-corpus.yml, 每周一 03:07 UTC) 这周有没有进 TV 账本? —— 只读, 不写库。

2026-10-08 审计 (B-23 / A-08): 那条周跑 9-28、10-05 两次红没人收; 更坏的是"绿但空"——写库失败而 job 绿
(10-08 已改成红, Jev#6)、或者全被分诊拒掉——在哪都看不见: TV 这边没有一盏灯看 external_notes 的新鲜度。
本脚本就是那盏灯 (docs/29 登记为 EXTERNAL_CORPUS_CHECK_DONE)。

判据只有一条 (docs/29 规矩 4: 设下限, 不做比例启发式):
    truth_vault.external_notes 里最新一行的 fetched_at 比现在早超过 --max-age-days (默认 8) 天 → rc=1。
    周更 + 一天余量; GitHub 定时漂几小时不该红。表是空的 → rc=2 (判不了, 从没进过货)。
修在 Jev 仓 (TikHub 密钥 / UA / 详情解析 / 写库), TV 这边红了也改不好 —— 所以 advisory 不拖红。

⚠️ 和登记册里其它哨兵灯同一个约定: 正常跑完末尾必打一行 `EXTERNAL_CORPUS_CHECK_DONE rc=<码>`;
daily-sync.yml 靠有没有这一行判定崩溃, 不靠退出码。

用法:
    python check_external_corpus_fresh.py                  # 默认 8 天
    python check_external_corpus_fresh.py --max-age-days 15
    python check_external_corpus_fresh.py --selftest       # CI: report() 的四种形状 (不连库)
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

DEFAULT_MAX_AGE_DAYS = 8


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def report(latest_fetched_at: Optional[str], n_rows: int, now: datetime, max_age_days: int) -> int:
    """纯函数: 0 = 新鲜, 1 = 过期 (超过 max_age_days), 2 = 判不了 (表空 / 时间认不出)。只打印, 不碰库。"""
    print(f"外部语料新鲜度 · external_notes {n_rows} 行 · 阈值 {max_age_days} 天")
    if n_rows == 0:
        print("  ⚠️  external_notes 是空的: 外部语料从没进过账本 (Jev 仓 external-corpus.yml 一次都没写成功?)")
        return 2
    dt = _parse(latest_fetched_at)
    if dt is None:
        print(f"  ⚠️  最新一行的 fetched_at 认不出: {latest_fetched_at!r}")
        return 2
    age = now - dt
    days = age.total_seconds() / 86400
    if age > timedelta(days=max_age_days):
        print(f"  🔴 最新一批是 {dt.isoformat(timespec='minutes')}, 已经 {days:.1f} 天没进新货 (> {max_age_days} 天)。"
              " 去 Jev 仓看 external-corpus 最近一次 run: 红了是抓取 / 写库失败; 绿但没新行是分诊全拒或缓存状态问题。修在 Jev 仓。")
        return 1
    print(f"  ✅ 最新一批 {dt.isoformat(timespec='minutes')}, {days:.1f} 天前")
    return 0


def gather(sb) -> tuple[Optional[str], int]:
    """最新 fetched_at 与行数 (两条小查询, 不翻全表)。"""
    latest = (sb.schema("truth_vault").table("external_notes").select("fetched_at")
              .order("fetched_at", desc=True).limit(1).execute()).data or []
    cnt = sb.schema("truth_vault").table("external_notes").select("note_id", count="exact").limit(1).execute()
    n = cnt.count if getattr(cnt, "count", None) is not None else (1 if latest else 0)
    return (latest[0].get("fetched_at") if latest else None), int(n or 0)


def selftest() -> int:
    now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
    assert report("2026-10-06T05:13:02+00:00", 200, now, 8) == 0, "2 天前 → 新鲜"
    assert report("2026-09-28T03:00:00Z", 200, now, 8) == 1, "10 天前 → 过期"
    assert report("2026-10-01T03:00:00", 200, now, 8) == 0, "naive 时间按 UTC, 7 天前 → 仍新鲜 (周更 + 1 天余量)"
    assert report(None, 0, now, 8) == 2, "表空 → 判不了"
    assert report("not a date", 3, now, 8) == 2, "认不出 → 判不了"
    print("  ✓ selftest: 新鲜 / 过期 / naive / 表空 / 认不出 五种形状")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[4])
    parser.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS)
    parser.add_argument("--selftest", action="store_true", help="不连库, 只测 report()")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if args.max_age_days < 1:
        print("--max-age-days 必须 >= 1")
        return 2
    from _common import get_supabase_client  # 局部 import: --selftest 在裸环境里也能跑
    sb = get_supabase_client()
    latest, n = gather(sb)
    rc = report(latest, n, datetime.now(timezone.utc), args.max_age_days)
    # ⚠️ 哨兵行: daily-sync.yml 靠它区分"跑完了"和"崩了"。
    print(f"EXTERNAL_CORPUS_CHECK_DONE rc={rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
