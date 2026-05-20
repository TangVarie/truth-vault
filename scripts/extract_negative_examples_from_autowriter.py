"""
extract_negative_examples_from_autowriter.py
═══════════════════════════════════════════════════════════════════════════

一次性脚本: 扫 autowriter 历史数据，识别 negative example 候选，
写入 autowriter.items.example_label_proposal（NOT 直接 example_label）。
用户在 Memory Manager UI 审核后才落 example_label='negative'。

三个来源 (P2 修正版，audit 四):
    A. 用户手动重写 AI 版    (强信号 → negative_manual_rewrite)
    B. 用户反馈触发改写       (中信号 → negative_feedback_iter)
    C. 同 batch 部分通过部分卡 (弱信号 → negative_batch_rejected)

优先级 A > B > C: 同一 item 被多个来源命中时，只保留高优先级的标签。

用法:
    python extract_negative_examples_from_autowriter.py
    python extract_negative_examples_from_autowriter.py --project <aw_project_id>
    python extract_negative_examples_from_autowriter.py --dry-run

幂等性:
    脚本只会给当前 example_label_proposal IS NULL 且 example_label IS NULL
    的 item 打 proposal 标。已被用户 review 过（例如打成 negative 或被忽略
    清空）的 item 不会被覆盖。

环境变量:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY       (必须用 service_role，绕过 RLS)
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Set

from _common import fetch_all_pages, get_supabase_client, setup_logger


logger = setup_logger("extract_negative")


# ─────────────────────────────────────────────────────────────────────────
# Source A · 用户手动重写过 AI 版
# ─────────────────────────────────────────────────────────────────────────
#
# 信号: 某 item 有 ai_engine='manual' 的 version，意味着用户手动重写过。
# Negative candidate: 该 manual version 的"前一版"（version_num 紧邻前一个
# 且 ai_engine != 'manual'），是被替换的 AI 输出。
# 我们只标 item_id, 不标具体版本——因为 example_label 是 item 级的。

def query_source_a(sb, aw_project_id: str | None = None) -> Set[str]:
    """Return item_ids where a *prior* AI version was replaced by a manual rewrite.

    Correctness note: it's not enough to check "this item has a manual
    version AND any non-manual version" — an item could be `AI@v1 →
    manual@v2 → AI@v3` (operator manual-edited then asked for another AI
    pass). v3 is not negative; v1 is. We need a non-manual version whose
    version_num is *less than* the earliest manual version_num to claim
    "AI was replaced by manual." Pull (item_id, version_num, ai_engine)
    triples and decide in Python.
    """
    q = (
        sb.schema("autowriter")
        .table("versions")
        .select("item_id, version_num, ai_engine, "
                "items!inner(batches!inner(project_id))")
    )
    if aw_project_id:
        q = q.eq("items.batches.project_id", aw_project_id)
    rows = fetch_all_pages(q)

    by_item: dict[str, list[tuple[int, str]]] = {}
    for r in rows:
        item_id = r.get("item_id")
        v_num = r.get("version_num")
        engine = r.get("ai_engine")
        if not item_id or v_num is None:
            continue
        by_item.setdefault(item_id, []).append((v_num, engine))

    confirmed: Set[str] = set()
    for item_id, versions in by_item.items():
        # earliest manual version on this item
        manual_versions = [v for v, e in versions if e == "manual"]
        if not manual_versions:
            continue
        first_manual = min(manual_versions)
        # any non-manual version strictly before first_manual
        has_prior_ai = any(
            e != "manual" and v < first_manual for v, e in versions
        )
        if has_prior_ai:
            confirmed.add(item_id)
    return confirmed


# ─────────────────────────────────────────────────────────────────────────
# Source B · 用户反馈触发的迭代
# ─────────────────────────────────────────────────────────────────────────
#
# 信号: 某 version 的 feedback 字段非空，且不是 '手动精修'（那是来源 A），
# 也不是 ai_engine='manual'。  feedback 挂在"新版本"上（v_revised），其
# 上一版（v_original）是被替换的 AI 输出 = negative candidate.

def query_source_b(sb, aw_project_id: str | None = None) -> Set[str]:
    """Return item_ids that have at least one revised-by-feedback iteration."""
    q = (
        sb.schema("autowriter")
        .table("versions")
        .select("item_id, feedback, ai_engine, "
                "items!inner(batches!inner(project_id))")
        .not_.is_("feedback", None)
        .neq("ai_engine", "manual")
    )
    if aw_project_id:
        q = q.eq("items.batches.project_id", aw_project_id)
    rows = fetch_all_pages(q)

    return {
        r["item_id"] for r in rows
        if r.get("item_id") and (r.get("feedback") or "").strip() != "手动精修"
    }


# ─────────────────────────────────────────────────────────────────────────
# Source C · 同 batch 部分通过部分卡 needs_revision (弱信号)
# ─────────────────────────────────────────────────────────────────────────

def query_source_c(sb, aw_project_id: str | None = None) -> Set[str]:
    """Return item_ids that are needs_revision in a batch where at least one
    other item got approved.  Excludes items already covered by A or B."""
    # 1. Find batches where status='approved' coexists with status='needs_revision'
    q_pending = (
        sb.schema("autowriter")
        .table("items")
        .select("id, batch_id, batches!inner(project_id)")
        .eq("status", "needs_revision")
    )
    if aw_project_id:
        q_pending = q_pending.eq("batches.project_id", aw_project_id)
    pending_rows = fetch_all_pages(q_pending)
    pending_by_batch: dict[str, list[str]] = {}
    for r in pending_rows:
        pending_by_batch.setdefault(r["batch_id"], []).append(r["id"])

    if not pending_by_batch:
        return set()

    # 2. For each batch, check if any item is approved.
    # Note: select returns one row per approved item, so a batch with many
    # approved items can push us over the PostgREST default cap. Paginate.
    candidate_items: Set[str] = set()
    batch_ids = list(pending_by_batch.keys())
    for batch in _batched(batch_ids, 50):
        q_approved = (
            sb.schema("autowriter")
            .table("items")
            .select("batch_id")
            .in_("batch_id", list(batch))
            .eq("status", "approved")
        )
        approved_batches = {r["batch_id"] for r in fetch_all_pages(q_approved)}
        for b in batch:
            if b in approved_batches:
                candidate_items.update(pending_by_batch[b])

    return candidate_items


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────

def _batched(items, size: int):
    items = list(items)
    for i in range(0, len(items), size):
        yield items[i : i + size]


def fetch_already_reviewed(sb, aw_project_id: str | None = None) -> Set[str]:
    """Item_ids already touched: either example_label is set, OR proposal is
    set (might be in-progress review).  Skip these to be idempotent.

    Builds a fresh query per pass (chained builders aren't safe to reuse
    after .not_.is_() is applied).  Paginates each pass to avoid silent
    truncation once the autowriter history grows past 1000 reviewed items.
    """
    seen: Set[str] = set()
    for col in ("example_label", "example_label_proposal"):
        q = sb.schema("autowriter").table("items").select(
            "id, batches!inner(project_id)"
        ).not_.is_(col, None)
        if aw_project_id:
            q = q.eq("batches.project_id", aw_project_id)
        for r in fetch_all_pages(q):
            seen.add(r["id"])
    return seen


def apply_proposal(sb, item_id: str, label: str, dry_run: bool = False) -> None:
    if dry_run:
        return
    (
        sb.schema("autowriter")
        .table("items")
        .update({"example_label_proposal": label})
        .eq("id", item_id)
        .execute()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", help="Only scan this autowriter project_id (UUID)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sb = get_supabase_client()
    already = fetch_already_reviewed(sb, args.project)
    logger.info("Skipping %d already-touched items (example_label or "
                "example_label_proposal already set)", len(already))

    a = query_source_a(sb, args.project)
    b = query_source_b(sb, args.project)
    c = query_source_c(sb, args.project)

    # Apply with A > B > C priority
    counts = {"A": 0, "B": 0, "C": 0}
    for item_id in a - already:
        apply_proposal(sb, item_id, "negative_manual_rewrite", args.dry_run)
        counts["A"] += 1
    for item_id in (b - a - already):
        apply_proposal(sb, item_id, "negative_feedback_iter", args.dry_run)
        counts["B"] += 1
    for item_id in (c - a - b - already):
        apply_proposal(sb, item_id, "negative_batch_rejected", args.dry_run)
        counts["C"] += 1

    total = sum(counts.values())
    logger.info("Source A (manual rewrite):  %d candidates (high confidence)", counts["A"])
    logger.info("Source B (feedback iter):   %d candidates (medium)", counts["B"])
    logger.info("Source C (batch rejected):  %d candidates (low — review carefully)", counts["C"])
    logger.info("Total proposals written:    %d", total)
    logger.info("用户需在 autowriter Memory Manager UI 中 review，"
                "确认的 item 会从 example_label_proposal 移动到 example_label='negative'。")
    logger.info("Result: %s", json.dumps(counts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
