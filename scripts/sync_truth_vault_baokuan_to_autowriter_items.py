"""
sync_truth_vault_baokuan_to_autowriter_items.py
═══════════════════════════════════════════════════════════════════════════

把 Truth Vault 中 tier ∈ ('爆','大爆') 的爆款 sync 到 autowriter.items，
打标 example_label='positive'，注入 build_system_prompt 的 few-shot pool。

需要 truth_vault.projects 表里有 mapping_to_autowriter_project_id 列，
指向 autowriter.projects.id。没有 mapping 的 TV 项目跳过。

幂等性:
    autowriter.items 有 partial UNIQUE INDEX(external_source, external_source_id)
    WHERE external_source IS NOT NULL（P1 Sprint 1.1 加的强幂等键）。
    INSERT 用 ON CONFLICT ... DO NOTHING 保证重跑不重复插入。

用法:
    python sync_truth_vault_baokuan_to_autowriter_items.py
    python sync_truth_vault_baokuan_to_autowriter_items.py --project NUC_phase1
    python sync_truth_vault_baokuan_to_autowriter_items.py --dry-run

环境变量:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY       (必须用 service_role，绕过 RLS)
    AUTOWRITER_SYNC_USER_ID         (UUID, 用于填 autowriter.items.user_id;
                                     建议建一个专门的 service account)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from typing import Any

from _common import fetch_all_pages, get_supabase_client, setup_logger, _iso_now


logger = setup_logger("sync_tv_baokuan_to_aw")


SPECIAL_BATCH_TACTIC = "truth_vault_synced"
SPECIAL_BATCH_AI_ENGINE = "truth_vault_sync"  # versions.ai_engine 用，v_model_comparison 会排除


def fetch_pending_baokuan_with_aw_project(sb, project_filter: str | None = None):
    """Pull baokuan from TV joined with the aw_project_id mapping.

    Paginated explicitly to avoid Supabase's 1000-row default cap silently
    truncating the candidate set once unsynced 爆款 accumulate across
    projects.
    """
    q = (
        sb.schema("truth_vault")
        .table("notes")
        .select(
            "note_id, project_id, raw_content, hit_blue_keywords, tier, "
            "projects(category, brand, mapping_to_autowriter_project_id)"
        )
        .in_("tier", ["爆", "大爆"])
        .is_("synced_to_aw_at", None)
    )
    if project_filter:
        q = q.eq("project_id", project_filter)
    rows = fetch_all_pages(q)
    # filter out rows where the project hasn't been mapped to autowriter yet
    keepable = []
    skipped_no_mapping = 0
    for r in rows:
        proj = r.get("projects") or {}
        if proj.get("mapping_to_autowriter_project_id"):
            r["aw_project_id"] = proj["mapping_to_autowriter_project_id"]
            keepable.append(r)
        else:
            skipped_no_mapping += 1
    if skipped_no_mapping:
        logger.info(
            "Skipping %d baokuan without truth_vault.projects."
            "mapping_to_autowriter_project_id set",
            skipped_no_mapping,
        )
    return keepable


def ensure_special_batch(sb, aw_project_id: str, sync_user_id: str,
                        dry_run: bool = False) -> str:
    """Find or create the per-project 'truth_vault_synced' batch.

    Returns the batch id.  We use a stable deterministic UUID seeded on
    aw_project_id so re-runs across machines produce the same batch_id;
    avoids ON CONFLICT plumbing on a table that doesn't yet have a unique
    constraint on (project_id, tactic).
    """
    # Deterministic UUID5 based on project_id + tactic
    namespace = uuid.UUID("00000000-0000-0000-0000-000000000000")
    batch_id = str(uuid.uuid5(namespace, f"{aw_project_id}:{SPECIAL_BATCH_TACTIC}"))

    if dry_run:
        logger.info("[dry-run] would ensure batch %s exists for project %s",
                    batch_id, aw_project_id)
        return batch_id

    # Try to find the batch first; if missing, create it
    existing = (
        sb.schema("autowriter")
        .table("batches")
        .select("id")
        .eq("id", batch_id)
        .execute()
    )
    if existing.data:
        return batch_id

    # Create
    (
        sb.schema("autowriter")
        .table("batches")
        .insert({
            "id": batch_id,
            "project_id": aw_project_id,
            "tactic": SPECIAL_BATCH_TACTIC,
            "params": {"source": "truth_vault_sync"},
            "ai_engines": [SPECIAL_BATCH_AI_ENGINE],
            "user_id": sync_user_id,
            "created_at": _iso_now(),
        })
        .execute()
    )
    logger.info("Created special batch %s for project %s",
                batch_id, aw_project_id)
    return batch_id


def insert_synced_item(
    sb,
    note: dict,
    batch_id: str,
    sync_user_id: str,
    dry_run: bool = False,
) -> tuple[str | None, bool]:
    """Insert the autowriter.items row + version row.

    Returns (item_id, is_new):
        - (uuid_str, True)   newly inserted
        - (uuid_str, False)  already existed (dedup hit; we look up the
                             existing item_id so caller can still write it
                             into truth_vault.notes.synced_autowriter_item_id
                             which is a UUID column)
        - (None, False)      genuine error (re-raised before returning here)
    """
    item_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())

    if dry_run:
        logger.info(
            "[dry-run] would insert item %s + version %s for note %s "
            "(external_source_id=%s)",
            item_id, version_id, note["note_id"], note["note_id"],
        )
        return item_id, True

    # 1. Insert item (idempotent via external_source unique index)
    try:
        (
            sb.schema("autowriter")
            .table("items")
            .insert({
                "id": item_id,
                "batch_id": batch_id,
                "status": "approved",
                "example_label": "positive",
                "external_source": "truth_vault",
                "external_source_id": note["note_id"],   # ⭐ idempotency key
                "user_id": sync_user_id,
                "created_at": _iso_now(),
            })
            .execute()
        )
    except Exception as exc:
        msg = str(exc).lower()
        if "duplicate" in msg or "unique" in msg or "23505" in msg:
            # Already synced. Look up the existing item_id so mark_synced
            # can write a real UUID into truth_vault.notes (audit issue 4).
            existing = (
                sb.schema("autowriter")
                .table("items")
                .select("id")
                .eq("external_source", "truth_vault")
                .eq("external_source_id", note["note_id"])
                .limit(1)
                .execute()
            )
            if existing.data:
                existing_id = existing.data[0]["id"]
                logger.info("Already synced (external_source_id=%s) → %s",
                            note["note_id"], existing_id)
                return existing_id, False
            # Theoretically impossible: insert said dup, but query finds nothing.
            # Re-raise so the operator notices the schema/index drift.
            raise
        raise

    # 2. Insert version
    (
        sb.schema("autowriter")
        .table("versions")
        .insert({
            "id": version_id,
            "item_id": item_id,
            "version_num": 1,
            "ai_engine": SPECIAL_BATCH_AI_ENGINE,
            "title": (note.get("raw_content") or "")[:60],
            "body": note.get("raw_content"),
            "keywords": note.get("hit_blue_keywords") or [],
            "feedback": None,
            "images": [],
            "token_usage": {},
            "created_at": _iso_now(),
        })
        .execute()
    )

    # 3. Link best_version_id
    (
        sb.schema("autowriter")
        .table("items")
        .update({"best_version_id": version_id})
        .eq("id", item_id)
        .execute()
    )
    return item_id, True


def mark_synced(sb, note_id: str, item_id: str, dry_run: bool = False) -> None:
    if dry_run:
        logger.info("[dry-run] would mark note %s → aw item %s", note_id, item_id)
        return
    (
        sb.schema("truth_vault")
        .table("notes")
        .update({
            "synced_to_aw_at": _iso_now(),
            "synced_autowriter_item_id": item_id,
        })
        .eq("note_id", note_id)
        .execute()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    sync_user_id = os.environ.get("AUTOWRITER_SYNC_USER_ID")
    if not sync_user_id:
        logger.error("AUTOWRITER_SYNC_USER_ID env var is required (UUID of the "
                     "service account that 'owns' synced items).")
        return 2

    sb = get_supabase_client()
    pending = fetch_pending_baokuan_with_aw_project(sb, project_filter=args.project)
    logger.info("Found %d baokuan pending sync to autowriter", len(pending))

    # Group by aw_project_id so we create each special batch only once
    batch_cache: dict[str, str] = {}
    stats = {"synced": 0, "deduped": 0, "errors": 0}

    for i, note in enumerate(pending):
        if args.limit and i >= args.limit:
            break
        aw_proj = note["aw_project_id"]
        try:
            if aw_proj not in batch_cache:
                batch_cache[aw_proj] = ensure_special_batch(
                    sb, aw_proj, sync_user_id, dry_run=args.dry_run,
                )
            item_id, is_new = insert_synced_item(
                sb, note, batch_cache[aw_proj], sync_user_id, dry_run=args.dry_run,
            )
            # Always write the real UUID back to truth_vault.notes — whether
            # this run inserted the item or just looked up an existing one.
            # synced_autowriter_item_id is a UUID column, so we cannot pass
            # a sentinel string like '(deduped)' (audit issue 4).
            mark_synced(sb, note["note_id"], item_id, dry_run=args.dry_run)
            if is_new:
                stats["synced"] += 1
                logger.info("Synced %s (tier=%s) → aw item %s",
                            note["note_id"], note["tier"], item_id)
            else:
                stats["deduped"] += 1
        except Exception as exc:
            logger.exception("note_id=%s failed: %s", note["note_id"], exc)
            stats["errors"] += 1

    logger.info("Done: %s", json.dumps(stats, ensure_ascii=False))
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
