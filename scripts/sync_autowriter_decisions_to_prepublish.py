"""
sync_autowriter_decisions_to_prepublish.py
═══════════════════════════════════════════════════════════════════════════

把 autowriter.items 上的运营审稿决定（approved / needs_revision）反向同步
到 truth_vault.prepublish_evaluations，作为人类 evaluator 的判断日志。

为什么需要这个:
    prepublish_evaluations 表 schema 已经存在（D-025），但目前没有任何
    sync 写入它，所以 v_evaluator_calibration view 永远空。把 autowriter
    侧的人工 approved / needs_revision 决定归档进来，至少能算出"运营批准
    了 N 个 items"这一基线统计，为以后接 LLM critic / model evaluator
    时的 "pred vs actual" 校准打地基。

限制 (诚实):
    - 我们只能拿到运营的 "pass / revise" 决定，拿不到他们的 "predict
      tier_class" 因为运营没在 UI 里给预测。所以 pred_tier_class = NULL。
    - actual_tier 也无法立刻填，要等到从 autowriter item 生成的内容**最终
      投放 + 被飞书 sync 回 TV** 才能反推。目前 TV 没有这条 autowriter_item
      → tv_note_id 的 lineage（飞书表里没有这一列），所以 actual_tier
      恒为 NULL，was_correct 一直是 NULL。
    - 总之: v_evaluator_calibration 在这个脚本跑完之后还是空，但 raw 数据
      已经在表里了, 哪天接通 lineage 就能反推过去.

幂等性:
    每个 (autowriter_item_id, evaluator_type='human') 元组只写一次。重跑
    会跳过已经有 prepublish_evaluations 行的 items。

    2026-05-22 audit P1/P2-4 加强: schemas/notes_v1_2.sql 现在带 partial
    UNIQUE INDEX (autowriter_item_id, evaluator_type) WHERE evaluator_type
    ='human' AND autowriter_item_id IS NOT NULL. 应用层去重照旧 (避免读后
    才发现冲突的高耗 round-trip), 但即便两个 worker 同时跑, DB 层会拒第
    二个 INSERT 而不是写两行. 脚本现在会把 23505 转成 info 级 "race"
    日志, 不当 error 计.

迟到决策 (audit P1/P2-4 已知局限):
    autowriter.items 没有 updated_at 列, 我们只能按 created_at 过滤.
    --since-days 默认从 90 改为 365, 这样一年内人工才改状态的旧 item
    仍能被回收. 长期 deployment 仍可能漏 1+ 年前创建的 item; 临时全扫
    用 --since-days 0 (或 cron 每月跑一次 --since-days 0).

用法:
    python sync_autowriter_decisions_to_prepublish.py
    python sync_autowriter_decisions_to_prepublish.py --dry-run
    python sync_autowriter_decisions_to_prepublish.py --since-days 0   # 全扫

环境变量:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

from _common import fetch_all_pages, get_supabase_client, setup_logger, _iso_now


logger = setup_logger("sync_aw_decisions")


# autowriter.items.status → prepublish_evaluations.decision mapping.
# 'pending' is unmapped (no decision yet) so those items are skipped.
_STATUS_TO_DECISION = {
    "approved": "pass",
    "needs_revision": "revise",
}


def fetch_pending_decisions(sb, since_iso: str | None) -> list[dict]:
    """Find autowriter items with a status that maps to a decision, that
    don't yet have a 'human' prepublish_evaluations row.

    Returns list of dicts with: id (item_id), status, user_id, created_at.
    """
    # autowriter.items has no `updated_at` column (see autowriter db.py items
    # DDL; only created_at exists). Selecting it would make PostgREST 400 with
    # "column items.updated_at does not exist". We use created_at as the time
    # filter — coarse but always present; the NOT-EXISTS filter below stops
    # us from creating duplicate evaluation rows on re-runs.
    q = (
        sb.schema("autowriter")
        .table("items")
        .select("id, status, user_id, created_at")
        .in_("status", list(_STATUS_TO_DECISION.keys()))
    )
    if since_iso:
        q = q.gte("created_at", since_iso)
    rows = fetch_all_pages(q)

    # Exclude items that already have a 'human' eval row.
    if not rows:
        return []
    item_ids = [r["id"] for r in rows]
    existing = fetch_all_pages(
        sb.schema("truth_vault")
        .table("prepublish_evaluations")
        .select("autowriter_item_id")
        .eq("evaluator_type", "human")
        .in_("autowriter_item_id", item_ids)
    )
    existing_ids = {r["autowriter_item_id"] for r in existing}
    return [r for r in rows if r["id"] not in existing_ids]


def _is_duplicate_error(exc: Exception) -> bool:
    """Detect SQLSTATE 23505 (unique_violation) from supabase-py errors."""
    code = getattr(exc, "code", None) or getattr(exc, "pgcode", None)
    if code == "23505":
        return True
    msg = str(exc)
    return "23505" in msg or "duplicate key value violates" in msg


def insert_evaluation(sb, item: dict, dry_run: bool = False) -> bool:
    """Insert one prepublish_evaluations row.

    Returns True if the row was inserted, False if it was already present
    (race recovery via 23505). The application-level NOT EXISTS pre-filter
    catches most repeats, but two concurrent runs of this script (e.g., a
    manual run overlapping with cron) can both pass the pre-filter and
    both attempt the INSERT. With the new partial UNIQUE index
    (schemas/notes_v1_2.sql: idx_tv_evals_aw_item_evaluator_uniq), the
    loser gets 23505; we treat that as success-by-other-worker, not error.
    """
    decision = _STATUS_TO_DECISION[item["status"]]
    row = {
        "autowriter_item_id": item["id"],
        "evaluator_type": "human",
        "evaluator_id": str(item.get("user_id") or ""),
        "decision": decision,
        # score_json / reasoning / pred_tier_class / actual_tier all NULL —
        # see module docstring "限制" for the lineage gap that prevents
        # filling these.
        "created_at": _iso_now(),
    }
    if dry_run:
        logger.info("[dry-run] would insert evaluation %s", row)
        return True
    try:
        (
            sb.schema("truth_vault")
            .table("prepublish_evaluations")
            .insert(row)
            .execute()
        )
        return True
    except Exception as exc:
        if _is_duplicate_error(exc):
            logger.info(
                "race: prepublish_evaluations row for item %s already exists "
                "(probably another worker wrote it between our SELECT and INSERT). "
                "Treating as success.",
                item["id"],
            )
            return False
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--since-days", type=int, default=365,
        help="Only sync items created within the last N days (default 365 — "
             "2026-05-22 audit P1/P2-4 bumped from 90, since autowriter.items "
             "has no updated_at and we can't otherwise tell a 91-day-old item "
             "got its decision changed today). Set 0 to scan everything; safe "
             "but slower on aged deployments, run monthly as a catch-all.",
    )
    args = parser.parse_args()

    since_iso = None
    if args.since_days > 0:
        since_iso = (
            datetime.now(timezone.utc) - timedelta(days=args.since_days)
        ).replace(tzinfo=None).isoformat(timespec="seconds")

    sb = get_supabase_client()
    pending = fetch_pending_decisions(sb, since_iso)
    logger.info("Found %d autowriter items with new human decisions to archive",
                len(pending))

    stats = {"pass": 0, "revise": 0, "race_skipped": 0, "errors": 0}
    for item in pending:
        try:
            inserted = insert_evaluation(sb, item, dry_run=args.dry_run)
            if inserted:
                stats[_STATUS_TO_DECISION[item["status"]]] += 1
            else:
                # 23505 race recovery — another worker wrote it. Not an error,
                # but track separately so ops can spot abnormal contention.
                stats["race_skipped"] += 1
        except Exception as exc:
            logger.exception("item_id=%s failed: %s", item["id"], exc)
            stats["errors"] += 1

    logger.info("Done: %s", json.dumps(stats, ensure_ascii=False))
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
