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
    重跑流程是 INSERT → 抓 23505 重复键错误 → SELECT 已有 item.id →
    继续 _ensure_version_and_link()。这个流程比 ON CONFLICT DO NOTHING
    更可控的地方在于：dedup 命中时仍然能验证 version + best_version_id
    链接是否完整（修 Round 2 review 里 P0 的 "phantom items" 问题）。
    最终结果对调用方是一样的：notes.synced_to_aw_at + synced_autowriter_item_id
    都会写回，无论本次 INSERT 是新建还是仅恢复孤儿 item。

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


def _ensure_version_and_link(
    sb,
    note: dict,
    item_id: str,
) -> str:
    """Ensure item has at least one version + best_version_id set.

    Idempotent: if a version already exists for this item, return its id
    (and only update best_version_id if it's not already pointing at it).
    Used both by the happy path (after creating a fresh item) AND by the
    dedup-recovery path: a prior run could have inserted the item but
    crashed before the version insert succeeded — leaving "phantom items"
    that, on rerun, would just be marked synced without ever getting a
    version. That used to be the user's #2 P0 issue.

    Returns the version_id that ends up linked as best_version_id.
    """
    existing_v = (
        sb.schema("autowriter")
        .table("versions")
        .select("id")
        .eq("item_id", item_id)
        .limit(1)
        .execute()
    )
    if existing_v.data:
        version_id = existing_v.data[0]["id"]
        # belt-and-suspenders: ensure best_version_id is set
        sb.schema("autowriter").table("items").update(
            {"best_version_id": version_id}
        ).eq("id", item_id).is_("best_version_id", None).execute()
        return version_id

    version_id = str(uuid.uuid4())
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
    (
        sb.schema("autowriter")
        .table("items")
        .update({"best_version_id": version_id})
        .eq("id", item_id)
        .execute()
    )
    return version_id


def _is_duplicate_error(exc: Exception) -> bool:
    """Detect Postgres unique-constraint violations from supabase-py.

    supabase-py wraps PostgREST errors; the SQLSTATE 23505 ends up either
    in str(exc) or in exc.code. We check both rather than relying on the
    fragile substring scan the old code used (which was easy to false-
    positive on words like "duplicate" appearing in unrelated error text).
    """
    code = getattr(exc, "code", None) or getattr(exc, "pgcode", None)
    if code == "23505":
        return True
    msg = str(exc)
    return "23505" in msg or "duplicate key value violates" in msg


def insert_synced_item(
    sb,
    note: dict,
    batch_id: str,
    sync_user_id: str,
    dry_run: bool = False,
) -> tuple[str | None, bool]:
    """Insert the autowriter.items row + version row, idempotently.

    Returns (item_id, is_new):
        - (uuid_str, True)   newly inserted (both item and version)
        - (uuid_str, False)  item already existed; we still verify that
                             a version + best_version_id are linked, and
                             create them if not (orphan recovery).
        - (None, False)      genuine error (re-raised before returning).
    """
    item_id = str(uuid.uuid4())

    if dry_run:
        logger.info(
            "[dry-run] would insert item %s for note %s (external_source_id=%s)",
            item_id, note["note_id"], note["note_id"],
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
        is_new = True
    except Exception as exc:
        if not _is_duplicate_error(exc):
            raise
        # Dedup hit. Look up the existing item_id so we can:
        #   1. write a real UUID into truth_vault.notes.synced_autowriter_item_id
        #   2. verify the version + best_version_id link exist (orphan recovery)
        existing = (
            sb.schema("autowriter")
            .table("items")
            .select("id, best_version_id")
            .eq("external_source", "truth_vault")
            .eq("external_source_id", note["note_id"])
            .limit(1)
            .execute()
        )
        if not existing.data:
            # Theoretically impossible: insert said dup, but query finds nothing.
            # Re-raise so the operator notices the schema/index drift.
            raise
        item_id = existing.data[0]["id"]
        logger.info(
            "Item already exists for note %s → %s (verifying version link)",
            note["note_id"], item_id,
        )
        is_new = False

    # 2 + 3. Ensure version + best_version_id. Idempotent — runs whether
    #        item was freshly inserted OR we recovered from a prior crash.
    _ensure_version_and_link(sb, note, item_id)
    return item_id, is_new


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
    # Validate the UUID up-front; otherwise the first INSERT 100 baokuan in
    # would fail with a confusing Postgres cast error.
    try:
        uuid.UUID(sync_user_id)
    except (ValueError, AttributeError):
        logger.error(
            "AUTOWRITER_SYNC_USER_ID=%r is not a valid UUID. Expected the UUID "
            "of a user row in auth.users (the service account that 'owns' "
            "TV-synced items in autowriter).",
            sync_user_id,
        )
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
