"""
sync_truth_vault_baokuan_to_sanshengliubu.py
═══════════════════════════════════════════════════════════════════════════

把 Truth Vault 中 tier ∈ ('爆', '大爆') 的爆款笔记 sync 到
public.reference_samples（sanshengliubu 保持在 public schema，D-024）。
注入到 vibe_rewriter 的高权重检索池。

用法:
    python sync_truth_vault_baokuan_to_sanshengliubu.py
    python sync_truth_vault_baokuan_to_sanshengliubu.py --project NUC_phase1
    python sync_truth_vault_baokuan_to_sanshengliubu.py --dry-run

幂等性:
    public.reference_samples 表里通过
    ai_analysis->>'_truth_vault_note_id' = notes.note_id 来判断"已 sync"。
    重跑只会处理新出现的爆款。

环境变量:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY       (必须用 service_role，绕过 RLS)
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from typing import Any

from _common import fetch_all_pages, get_supabase_client, setup_logger, _iso_now


logger = setup_logger("sync_tv_baokuan_to_ssll")


def fetch_pending_baokuan(
    sb,
    project_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Query Truth Vault for baokuan notes not yet synced to sanshengliubu.

    Paginates explicitly. Supabase's PostgREST defaults to 1000 rows/response;
    once enough projects onboard, unsynced 爆款 will cross that boundary and
    silent truncation would leak baokuan from the flywheel.
    """
    q = (
        sb.schema("truth_vault")
        .table("notes")
        .select("note_id, project_id, raw_content, hit_blue_keywords, "
                "tier, intent, publish_url, target_audience, "
                "projects(category, brand, platform)")
        .in_("tier", ["爆", "大爆"])
        .is_("synced_to_ssll_at", None)  # not yet synced
    )
    if project_filter:
        q = q.eq("project_id", project_filter)
    return fetch_all_pages(q)


def fetch_top_comments(sb, note_id: str, limit: int = 5) -> list[dict[str, Any]]:
    """Pull top N comments to embed as evidence in the reference pack.

    The truth_vault.comments schema does NOT have likes/sentiment columns
    (those were in an older draft; current schema in schemas/notes_v1_2.sql
    only stores content + comment_role + comment_type + is_pinned +
    contains_blue_keyword + blue_keywords_matched).  We order by pinned
    status first (pinned comments are usually high-signal), then by
    comment_order as a stable tie-breaker.

    Returns dicts with 'content' (not 'text'), 'comment_role', 'is_pinned'.
    """
    res = (
        sb.schema("truth_vault")
        .table("comments")
        .select("content, comment_role, is_pinned, contains_blue_keyword, "
                "blue_keywords_matched, comment_order")
        .eq("note_id", note_id)
        .order("is_pinned", desc=True)
        .order("comment_order", desc=False)
        .limit(limit)
        .execute()
    )
    return res.data or []


def build_reference_sample(note: dict, comments: list[dict]) -> dict:
    """Map a Truth Vault note into a sanshengliubu.reference_samples row.

    Returns the dict to INSERT (id is generated here in Python, not DB).
    The schema of public.reference_samples is owned by sanshengliubu; we
    write the columns it expects.  ai_analysis is JSONB and we put the
    cross-system lineage in there under leading-underscore keys to avoid
    colliding with sanshengliubu's own ai_analysis sub-keys.

    ⚠️ Schema reconciliation pending: docs/09-system-integration.md once
    spec'd the column mapping as post_title / post_body / quality_score;
    the live sanshengliubu schema this script targets uses title /
    content / no quality_score (verified against the v0.30.10 codebase
    referenced in Session #7). If the actual live schema differs from
    what's here, the insert will 400 — see preflight_check() at startup.
    The doc has been updated to match this column set as the source of
    truth; if sanshengliubu ever renames these columns, update both
    sides simultaneously.
    """
    proj = note.get("projects") or {}
    tier = note.get("tier")
    # tier → quality_score mapping documented in doc 09 §"通道 1 数据映射".
    # Kept in ai_analysis so any sanshengliubu downstream consumer that
    # ranks by quality has a numeric handle regardless of whether the
    # reference_samples table itself exposes a quality_score column.
    quality_score = {"爆": 100, "大爆": 200}.get(tier, 0)
    ai_analysis = {
        # ── Cross-system lineage (leading underscore = TV-injected, not ssll-native) ──
        "_truth_vault_note_id": note["note_id"],           # idempotency key
        "_truth_vault_project_id": note["project_id"],
        "_truth_vault_tier": tier,
        "_truth_vault_intent": note.get("intent"),
        "_truth_vault_quality_score": quality_score,
        # ── Comment evidence (sanshengliubu vibe_rewriter reads these) ──
        # Schema reference: comments.content is the text (not 'text');
        # there's no likes/sentiment in the current schema.
        "top_comments": [c.get("content") for c in comments if c.get("content")],
        "top_comment_roles": [c.get("comment_role") for c in comments],
        "top_comments_pinned": [bool(c.get("is_pinned")) for c in comments],
    }
    return {
        "id": str(uuid.uuid4()),
        "title": (note.get("raw_content") or "")[:60],   # sanshengliubu convention
        "content": note.get("raw_content"),
        "platform": proj.get("platform") or note.get("platform") or "xiaohongshu",
        "category": proj.get("category"),
        "brand": proj.get("brand"),
        "tags": ["truth_vault_sync", note["tier"]],
        "source_url": note.get("publish_url"),
        "target_audience": note.get("target_audience"),
        "hit_keywords": note.get("hit_blue_keywords") or [],
        "ai_analysis": ai_analysis,
        # Clean idempotency / lineage key — column added by
        # sanshengliubu-patches/001_add_source_tv_note_id.sql (REQUIRED).
        # Without this, the index idx_reference_samples_tv_note stays empty
        # and existing_ssll_sample_id() falls back to the slower JSON path.
        "source_truth_vault_note_id": note["note_id"],
        "created_at": _iso_now(),
    }


def preflight_check(sb) -> None:
    """Fail fast if public.reference_samples is missing required columns.

    Runs once at startup. Issues a no-data SELECT with a tight column list;
    Supabase/PostgREST returns 400 with 'column X does not exist' if any
    column is absent. Catching this here (with a curated error message)
    is friendlier than letting the first INSERT explode mid-loop and
    leaving half the run un-synced.

    Required columns: see build_reference_sample() for what we write. If
    the live sanshengliubu schema renames any of them, update both this
    list and build_reference_sample() in one commit, plus
    docs/09-system-integration.md.
    """
    required = (
        "id, title, content, platform, category, brand, tags, source_url, "
        "target_audience, hit_keywords, ai_analysis, "
        "source_truth_vault_note_id, created_at"
    )
    try:
        sb.schema("public").table("reference_samples").select(required).limit(0).execute()
    except Exception as exc:
        msg = str(exc)
        raise RuntimeError(
            "public.reference_samples preflight failed. The live sanshengliubu "
            "schema is missing one of the columns this script writes. Confirm "
            "sanshengliubu-patches/001_add_source_tv_note_id.sql has been run, "
            "and that the column list in build_reference_sample() matches what "
            f"ssll expects. Underlying error: {msg}"
        ) from exc


def existing_ssll_sample_id(sb, note_id: str) -> str | None:
    """Return the public.reference_samples.id already linked to this TV note,
    or None if no such sample exists.

    Why this exists (audit issue · sub-3):
        The main path uses notes.synced_to_ssll_at IS NULL to find work.
        But there's a race: insert_reference_sample succeeded, then
        mark_synced (UPDATE truth_vault.notes) failed for any reason
        (network blip, process killed, RLS hiccup).  On next run, the
        note is still "pending" so we'd insert a SECOND reference_sample.

        This function is the belt-and-suspenders check: before inserting,
        query reference_samples for the canonical key
        (source_truth_vault_note_id, also kept in ai_analysis for legacy
        rows).  If we find a row, we skip insert and only run mark_synced.
    """
    # Path A: clean column (added by sanshengliubu-patches/001_add_source_tv_note_id.sql)
    res = (
        sb.schema("public")
        .table("reference_samples")
        .select("id")
        .eq("source_truth_vault_note_id", note_id)
        .limit(1)
        .execute()
    )
    if res.data:
        return res.data[0]["id"]

    # Path B: fallback for any rows imported before the column was added —
    # check the JSON-embedded copy of the same key in ai_analysis.
    res = (
        sb.schema("public")
        .table("reference_samples")
        .select("id")
        .filter("ai_analysis->>_truth_vault_note_id", "eq", note_id)
        .limit(1)
        .execute()
    )
    if res.data:
        return res.data[0]["id"]
    return None


def insert_reference_sample(sb, sample: dict, dry_run: bool = False) -> str:
    if dry_run:
        logger.info("[dry-run] would insert reference_sample id=%s for note %s",
                    sample["id"], sample["ai_analysis"]["_truth_vault_note_id"])
        return sample["id"]
    # public.reference_samples — sanshengliubu's schema, explicit
    (
        sb.schema("public")
        .table("reference_samples")
        .insert(sample)
        .execute()
    )
    return sample["id"]


def mark_synced(sb, note_id: str, sample_id: str, dry_run: bool = False) -> None:
    """Update truth_vault.notes with sync state for backward traceability."""
    if dry_run:
        logger.info("[dry-run] would mark note %s synced to ssll sample %s",
                    note_id, sample_id)
        return
    (
        sb.schema("truth_vault")
        .table("notes")
        .update({
            "synced_to_ssll_at": _iso_now(),
            "synced_ssll_reference_sample_id": sample_id,
        })
        .eq("note_id", note_id)
        .execute()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", help="Only sync this project (e.g. NUC_phase1)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0,
                        help="Stop after N notes (debug)")
    args = parser.parse_args()

    sb = get_supabase_client()
    if not args.dry_run:
        preflight_check(sb)
    pending = fetch_pending_baokuan(sb, project_filter=args.project)
    logger.info("Found %d baokuan pending sync to sanshengliubu", len(pending))

    stats = {"synced": 0, "recovered": 0, "errors": 0}
    for i, note in enumerate(pending):
        if args.limit and i >= args.limit:
            break
        try:
            # Belt-and-suspenders: ref_samples may already have a row for
            # this TV note (previous run inserted then crashed before
            # mark_synced ran).  In that case skip insert, just write the
            # synced state back.  See existing_ssll_sample_id() docstring.
            existing_id = existing_ssll_sample_id(sb, note["note_id"])
            if existing_id is not None:
                mark_synced(sb, note["note_id"], existing_id, dry_run=args.dry_run)
                stats["recovered"] += 1
                logger.info(
                    "Recovered orphan: ssll sample %s already existed for "
                    "TV note %s; only marking synced",
                    existing_id, note["note_id"],
                )
                continue

            comments = fetch_top_comments(sb, note["note_id"], limit=5)
            sample = build_reference_sample(note, comments)
            sample_id = insert_reference_sample(sb, sample, dry_run=args.dry_run)
            mark_synced(sb, note["note_id"], sample_id, dry_run=args.dry_run)
            stats["synced"] += 1
            logger.info("Synced %s (tier=%s, project=%s) → ssll %s",
                        note["note_id"], note["tier"], note["project_id"], sample_id)
        except Exception as exc:
            logger.exception("note_id=%s failed: %s", note["note_id"], exc)
            stats["errors"] += 1

    logger.info("Done: %s", json.dumps(stats, ensure_ascii=False))
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
