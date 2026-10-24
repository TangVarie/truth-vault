#!/usr/bin/env python3
"""scripts/prune_librarian_cache.py — 清理 truth_vault.flywheel_librarian_cache 里
长期没被命中的旧缓存行(TTL / LRU 式)。

为什么需要:cache_key 含 library_version(= 经验卡 max(curated_at)),书架一更新,旧
library_version 的 key 自然 miss、再也不会命中 —— 这些死行只会无限累积。v1.5 的 schema
注释和 librarian/core 都说"按 created_at/last_hit_at 定期 prune",但此前没有脚本真去删。
本脚本补上,并由 daily-sync 每日 advisory 跑一次。

判定:put_cache 写入时即把 last_hit_at 置为 now、命中时刷新 → last_hit_at 反映"最近活跃"。
删掉 last_hit_at 超过 TTL 天的行(并防御性清掉极少数 last_hit_at 为 NULL、created_at 也老的行)。

  python prune_librarian_cache.py [--ttl-days 30] [--dry-run]
  python prune_librarian_cache.py --delivery-only [--dry-run]

--delivery-only (D-116): 不看 TTL, 作废所有带已验证规律下发的缓存行 (library_version 里有 ":dl")。
backfill-features 拿 run_tag=primary 重抽答案 (reannotate) 之后跑: 规律命中是按 primary 答案算的, 重抽改了答案却
不改书架 / 批准层 / 闸二标签, 版本串不变, 旧缓存会一直回旧的命中标记 (codex review on #195)。
作废 = 把 selected 清成 NULL、行留着 (D-126): 馆员 get_cache 拿到 NULL 当没命中、重挑后按 cache_key 覆盖; 行留着是因为
通道 2 借阅流量灯 (check_librarian_traffic) 靠这张表的 last_hit_at 数写作台来借过几次 —— 以前整行删掉, 10-23 一次
重抽把 10-22 写作台的 3 次借阅一起删了, 第二天那盏灯就报「通道 2 暗着」。过期行照旧由 TTL 清理删。
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from _common import get_supabase_client, setup_logger

logger = setup_logger("prune_librarian_cache")


def _count(query) -> int:
    res = query.execute()
    return res.count if res.count is not None else len(res.data or [])


DELIVERY_MARK = "%:dl%"   # librarian/core.py library_version(): 有规律下发时版本串带 ":dl<批准层摘要>"


def prune_delivery(sb, *, dry_run: bool = False) -> int:
    def tbl():
        return sb.schema("truth_vault").table("flywheel_librarian_cache")
    n = _count(tbl().select("cache_key", count="exact").like("library_version", DELIVERY_MARK)
               .not_.is_("selected", "null").limit(1))
    if dry_run:
        logger.info("[dry-run] 会作废 %d 行带规律下发的馆员缓存", n)
        return 0
    if n:
        tbl().update({"selected": None}).like("library_version", DELIVERY_MARK).not_.is_("selected", "null").execute()
    logger.info("已作废 %d 行带规律下发的馆员缓存 (primary 答案重抽过, 命中标记要重算; selected 清空、行留着给借阅流量灯数)", n)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ttl-days", type=int, default=30,
                    help="删掉超过 N 天没命中的缓存行(默认 30)")
    ap.add_argument("--dry-run", action="store_true", help="只数不删")
    ap.add_argument("--delivery-only", action="store_true",
                    help="不看 TTL, 只删带已验证规律下发的行 (library_version 含 ':dl'); 重抽 primary 答案之后用")
    args = ap.parse_args()
    if args.ttl_days < 1:
        logger.error("--ttl-days 必须 >= 1")
        return 2
    if args.delivery_only:
        return prune_delivery(get_supabase_client(), dry_run=args.dry_run)

    # naive-UTC,匹配本仓 TIMESTAMP WITHOUT TIME ZONE 约定
    cutoff = (datetime.now(timezone.utc).replace(tzinfo=None)
              - timedelta(days=args.ttl_days)).isoformat(timespec="seconds")
    sb = get_supabase_client()

    def tbl():
        return sb.schema("truth_vault").table("flywheel_librarian_cache")

    # 主清理:last_hit_at 老于 cutoff(put_cache 必写、命中刷新,实际行都有值)
    n_stale = _count(tbl().select("cache_key", count="exact").lt("last_hit_at", cutoff).limit(1))
    # 防御:极少数 last_hit_at 为 NULL 的行,按 created_at 兜底
    n_null = _count(tbl().select("cache_key", count="exact")
                    .is_("last_hit_at", "null").lt("created_at", cutoff).limit(1))
    total = n_stale + n_null

    if args.dry_run:
        logger.info("[dry-run] 会清理 %d 行 (stale=%d, null_last_hit=%d; cutoff=%s)",
                    total, n_stale, n_null, cutoff)
        return 0
    if total == 0:
        logger.info("没有可清理的旧馆员缓存行 (cutoff=%s, ttl=%dd)", cutoff, args.ttl_days)
        return 0

    if n_stale:
        tbl().delete().lt("last_hit_at", cutoff).execute()
    if n_null:
        tbl().delete().is_("last_hit_at", "null").lt("created_at", cutoff).execute()
    logger.info("已清理 %d 行旧馆员缓存 (stale=%d, null_last_hit=%d; cutoff=%s, ttl=%dd)",
                total, n_stale, n_null, cutoff, args.ttl_days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
