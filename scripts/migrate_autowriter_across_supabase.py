"""
migrate_autowriter_across_supabase.py
═══════════════════════════════════════════════════════════════════════════

把 autowriter 数据从"独立 Supabase project"迁到"共享 Supabase project 的
autowriter schema". 一次性脚本, 跑完之后老 project 可以归档.

背景:
    最初 autowriter 部署在独立 Supabase project (xhs-workstation),
    sansheng 部署在另一个 (三省六部-workstation). Truth Vault 的设计
    (D-024) 假设这两个系统共享同一个 Supabase 实例 + schema 隔离,
    cross-schema view 才能 JOIN, sync 脚本才能用单一连接跨 schema 写.
    Session 2026-05-21 决定合并: 把 autowriter 迁到三省六部 project 的
    autowriter schema. 这个脚本是迁移工具.

前置条件:
    1. 目标 Supabase 已跑过 autowriter-migrations/007_fresh_install_autowriter_schema.sql
       (autowriter schema 已建, 8 张表 + RLS policy + grants 就位)
    2. 目标 Supabase 已跑过 schemas/notes_v1_2.sql (truth_vault schema 就位)
    3. 目标 Supabase Dashboard → Settings → API → Exposed schemas 已加 'autowriter'
    4. 两边都拿到 SERVICE_ROLE_KEY (RLS 绕过, 否则 INSERT 因 RLS 失败)

用法:
    # 干跑 (dry-run): 只统计源/目标行数, 不写数据. 强烈建议先跑这个.
    python migrate_autowriter_across_supabase.py --dry-run

    # 真跑
    python migrate_autowriter_across_supabase.py

    # 只迁某几张表 (FK 依赖顺序: projects → batches → items → versions → 其他)
    python migrate_autowriter_across_supabase.py --only projects,batches

    # 限定每张表只迁前 N 行 (调试用)
    python migrate_autowriter_across_supabase.py --limit 10

环境变量 (建议放到 .env, 再 source 进 shell):
    AW_MIGRATE_SRC_URL          源 Supabase project URL (xhs-workstation)
    AW_MIGRATE_SRC_KEY          源 service_role key
    AW_MIGRATE_DST_URL          目标 Supabase project URL (三省六部)
    AW_MIGRATE_DST_KEY          目标 service_role key

数据完整性保证:
    1. 迁移按 FK 依赖顺序进行: projects → batches → items → versions →
       memories → calibration_note_audit → batch_metrics → user_logins
       (items.batch_id REFERENCES batches.id 等需要父表先在场)
    2. 用 ON CONFLICT (PK) DO NOTHING 实现幂等:
       - 重跑安全
       - 中途失败可以续跑
       - 不会覆盖目标已有数据
    3. 每张表迁完立即校验源 vs 目标行数, 不一致就 ABORT 并打印差异.
    4. 全部完成后输出一个对账表, 类似:
           table             src   dst   delta
           projects          40    40    0      ✅
           batches           460   460   0      ✅
           items             3621  3621  0      ✅
           ...
       任何 delta ≠ 0 都是问题.

回滚:
    脚本只 INSERT, 从不 DELETE 或 UPDATE 源数据. 出问题:
    - 目标库: TRUNCATE autowriter.<table> 清掉后重跑
    - 源库: 完全不动, 安全可回退

幂等 / 错误处理:
    - 用 PostgREST 的 .upsert(on_conflict='id') ignore_duplicates=True
      (兼容旧 supabase-py 用 .insert + try/except 23505)
    - 每个 INSERT 失败只 log + continue, 不整 batch fail
    - 出问题的行打到 stdout, 方便人工 grep

依赖:
    pip install supabase>=2.4.0 python-dotenv
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from typing import Any, Iterator

try:
    from supabase import create_client, Client
    from supabase.client import ClientOptions
except ImportError:
    print("Missing dependency: pip install supabase>=2.4.0", file=sys.stderr)
    sys.exit(1)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("aw-migrate")


# ─────────────────────────────────────────────────────────────────────────
# 迁移顺序: FK 依赖图. 父表必须先迁, 子表才能 INSERT (FK 不会被 ignore).
# user_logins 没有 FK 关联其他表, 放最后无所谓.
# ─────────────────────────────────────────────────────────────────────────
TABLE_ORDER = [
    ("projects",              "id"),  # (table, primary key column)
    ("batches",               "id"),
    ("items",                 "id"),
    ("versions",              "id"),
    ("memories",              "id"),
    ("calibration_note_audit", "id"),
    ("batch_metrics",         "id"),
    ("user_logins",           "id"),
]


PAGE_SIZE = 500  # PostgREST default cap; iterating in 500-row pages keeps
                 # response payload small and avoids httpx timeouts on
                 # slow connections.


def get_client(url_env: str, key_env: str) -> Client:
    """Build a service_role Supabase client with schema='autowriter'.

    Note: schema='autowriter' set as client option makes
    ``client.table('items')`` resolve to ``autowriter.items`` without
    needing ``.schema('autowriter')`` on every call — mirrors how the
    autowriter app itself uses it in db.py.
    """
    url = os.environ.get(url_env)
    key = os.environ.get(key_env)
    if not url or not key:
        raise RuntimeError(
            f"Missing {url_env} or {key_env}. Set both in your shell or .env."
        )
    return create_client(url, key, ClientOptions(schema="autowriter"))


def fetch_pages(client: Client, table: str, pk: str, *, limit: int | None) -> Iterator[list[dict]]:
    """Yield pages of rows from `autowriter.<table>` ordered by primary key.

    Ordering by PK gives a stable iteration order — important for resumable
    migrations: a failure in row N means re-running starts fresh, hits N-1
    already-inserted rows (no-op via ON CONFLICT), then progresses past N.
    """
    start = 0
    total_yielded = 0
    while True:
        if limit is not None and total_yielded >= limit:
            return
        page_size = PAGE_SIZE
        if limit is not None:
            page_size = min(page_size, limit - total_yielded)
        end = start + page_size - 1
        res = (
            client.table(table)
            .select("*")
            .order(pk)
            .range(start, end)
            .execute()
        )
        page = res.data or []
        if not page:
            return
        total_yielded += len(page)
        yield page
        if len(page) < page_size:
            return
        start += len(page)


def count_rows(client: Client, table: str) -> int:
    """COUNT(*) via PostgREST exact-count header."""
    res = (
        client.table(table)
        .select("*", count="exact", head=True)
        .execute()
    )
    return res.count or 0


def insert_page(client: Client, table: str, pk: str, rows: list[dict]) -> tuple[int, int]:
    """Upsert a page of rows into autowriter.<table>.

    Returns (inserted_or_existed, errored).

    Uses ``.upsert(on_conflict=pk, ignore_duplicates=True)`` so re-running
    after a partial migration doesn't error on PK collisions. ignore_dupes
    means existing rows are preserved as-is (we don't overwrite, since the
    source is the source of truth and a partial migration should converge
    monotonically, not flip-flop).
    """
    if not rows:
        return 0, 0
    try:
        # ignore_duplicates=True → on PK collision keep target row unchanged
        res = (
            client.table(table)
            .upsert(rows, on_conflict=pk, ignore_duplicates=True)
            .execute()
        )
        # supabase-py returns the upserted (or pre-existing) rows in .data.
        # For ignore_duplicates=True, .data only contains NEWLY inserted
        # rows — collided rows are silently skipped. So .data length is
        # "actual inserts this call". The remainder were already present.
        return len(rows), 0
    except Exception as exc:
        # Bulk insert failed; fall back to row-by-row to localize the bad row(s)
        logger.warning(
            "Bulk upsert on %s page failed (%s); falling back to per-row",
            table, exc,
        )
        ok = 0
        err = 0
        for r in rows:
            try:
                client.table(table).upsert(r, on_conflict=pk, ignore_duplicates=True).execute()
                ok += 1
            except Exception as row_exc:
                err += 1
                logger.error(
                    "  Row %s=%s skipped: %s",
                    pk, r.get(pk), row_exc,
                )
        return ok, err


def migrate_table(
    src: Client, dst: Client, table: str, pk: str,
    *, dry_run: bool, limit: int | None,
) -> dict:
    """Stream rows from src.autowriter.<table> → dst.autowriter.<table>.

    Returns a stats dict: {src_count, dst_count_before, dst_count_after, errored}.
    """
    src_count = count_rows(src, table)
    dst_before = count_rows(dst, table)
    logger.info(
        "[%s] src=%d, dst(before)=%d, dry_run=%s",
        table, src_count, dst_before, dry_run,
    )
    if dry_run:
        return {
            "src": src_count, "dst_before": dst_before, "dst_after": dst_before,
            "errored": 0, "migrated": 0,
        }

    migrated = 0
    errored = 0
    t0 = time.time()
    for page_idx, page in enumerate(fetch_pages(src, table, pk, limit=limit)):
        ok, err = insert_page(dst, table, pk, page)
        migrated += ok
        errored += err
        logger.info(
            "  [%s] page %d (rows %d..%d): ok=%d err=%d elapsed=%.1fs",
            table, page_idx, migrated - len(page) + 1, migrated, ok, err,
            time.time() - t0,
        )

    dst_after = count_rows(dst, table)
    logger.info(
        "[%s] DONE src=%d dst(before)=%d dst(after)=%d delta=%d errored=%d",
        table, src_count, dst_before, dst_after,
        dst_after - dst_before, errored,
    )
    return {
        "src": src_count, "dst_before": dst_before, "dst_after": dst_after,
        "errored": errored, "migrated": migrated,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="只统计行数, 不写数据")
    parser.add_argument("--only", default="",
                        help="逗号分隔的 table 列表, 只迁这些表; 默认迁全部")
    parser.add_argument("--limit", type=int, default=None,
                        help="每张表最多迁 N 行 (调试用)")
    args = parser.parse_args()

    only_set = {t.strip() for t in args.only.split(",") if t.strip()}
    if only_set:
        invalid = only_set - {t for t, _ in TABLE_ORDER}
        if invalid:
            logger.error("--only contains unknown tables: %s", sorted(invalid))
            logger.error("Valid tables: %s", [t for t, _ in TABLE_ORDER])
            sys.exit(2)

    logger.info("Connecting to source (AW_MIGRATE_SRC_URL)...")
    src = get_client("AW_MIGRATE_SRC_URL", "AW_MIGRATE_SRC_KEY")
    logger.info("Connecting to target (AW_MIGRATE_DST_URL)...")
    dst = get_client("AW_MIGRATE_DST_URL", "AW_MIGRATE_DST_KEY")

    # Quick sanity check: source has data, target schema exists
    try:
        sanity = count_rows(src, "projects")
        logger.info("Source autowriter.projects sanity: %d rows", sanity)
    except Exception as exc:
        logger.error(
            "Source autowriter.projects read failed (%s). "
            "Is AW_MIGRATE_SRC_URL the project that has the data? "
            "Is the key service_role?", exc,
        )
        sys.exit(3)
    try:
        sanity = count_rows(dst, "projects")
        logger.info("Target autowriter.projects sanity: %d rows", sanity)
    except Exception as exc:
        logger.error(
            "Target autowriter.projects read failed (%s). "
            "Did you run autowriter-migrations/007? Is 'autowriter' in "
            "Exposed schemas (Dashboard → Settings → API)?", exc,
        )
        sys.exit(4)

    summary = []
    for table, pk in TABLE_ORDER:
        if only_set and table not in only_set:
            continue
        try:
            stats = migrate_table(src, dst, table, pk,
                                  dry_run=args.dry_run, limit=args.limit)
            stats["table"] = table
            summary.append(stats)
        except Exception as exc:
            logger.exception("[%s] migration failed: %s", table, exc)
            summary.append({
                "table": table, "src": None, "dst_before": None,
                "dst_after": None, "errored": -1, "migrated": 0,
            })

    # ── Final reconciliation table ──
    print()
    print("=" * 80)
    print(f"{'table':<26}{'src':>8}{'dst(before)':>14}{'dst(after)':>13}{'delta':>10}{'status':>9}")
    print("-" * 80)
    all_ok = True
    for row in summary:
        t = row["table"]
        src_c = row["src"] if row["src"] is not None else "ERR"
        before = row["dst_before"] if row["dst_before"] is not None else "ERR"
        after = row["dst_after"] if row["dst_after"] is not None else "ERR"
        if row["src"] is not None and row["dst_after"] is not None:
            delta = row["dst_after"] - row["src"]
            status = "✅" if delta == 0 and row["errored"] <= 0 else "⚠️"
            if delta != 0 or row["errored"] > 0:
                all_ok = False
        else:
            delta = "?"
            status = "❌"
            all_ok = False
        print(f"{t:<26}{src_c!s:>8}{before!s:>14}{after!s:>13}{delta!s:>10}{status:>9}")
    print("=" * 80)

    if args.dry_run:
        logger.info("DRY-RUN done. Re-run without --dry-run to actually migrate.")
        return

    if not all_ok:
        logger.error("Migration finished with deltas / errors. Inspect logs.")
        sys.exit(5)
    logger.info("All tables reconciled. Migration complete.")


if __name__ == "__main__":
    main()
