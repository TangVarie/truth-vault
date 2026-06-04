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
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from _common import get_supabase_client, setup_logger

logger = setup_logger("prune_librarian_cache")


def _count(query) -> int:
    res = query.execute()
    return res.count if res.count is not None else len(res.data or [])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ttl-days", type=int, default=30,
                    help="删掉超过 N 天没命中的缓存行(默认 30)")
    ap.add_argument("--dry-run", action="store_true", help="只数不删")
    args = ap.parse_args()
    if args.ttl_days < 1:
        logger.error("--ttl-days 必须 >= 1")
        return 2

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
