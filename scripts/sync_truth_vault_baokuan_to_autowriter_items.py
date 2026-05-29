"""
sync_truth_vault_baokuan_to_autowriter_items.py
═══════════════════════════════════════════════════════════════════════════

把 Truth Vault 中筛选过的爆款 sync 到 autowriter.items，打标
example_label='positive'，注入 autowriter `memory.build_system_prompt` 的
few-shot pool（autowriter 的 `list_example_items` 会按 created_at DESC 取
前 5 个作为 P1 段的"优质正案例"）。

候选选择由 `truth_vault.v_autowriter_injection_candidates` view 决定 ——
view 内含 eligibility filter (tier / tier_source / recency / aw 项目映射)
和加权 injection_score。本脚本读 view、按 score DESC 取候选、在 Python 端
应用 diversity 软约束（avoid 同一 emotional_lever 占满 N slot）、然后只 sync
top N per run（默认 5），让 autowriter 的 `[:5]` 自然窗口反映"当前最值得借鉴"
而非"全量历史顺次填"。低分候选不会被丢失 —— 下一轮如果它仍处于 top N
位置就会同步, 否则随 recency 自然降权直到 publish_time 过 12 个月被
filter 出局。

退役 (D-036 配套): 同一脚本末尾会跑 retire_stale_autowriter_examples，
清掉 TV-synced items 中 created_at 早于 6 个月的 example_label，让老
样本从 autowriter 的 positive_examples pool 中静默退出（行不删，仅
example_label 置 NULL — autowriter 不再注入但历史依旧可查）。

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
    python sync_truth_vault_baokuan_to_autowriter_items.py --skip-retire   # 只 sync 不退役

环境变量:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY            (必须用 service_role，绕过 RLS)
    AUTOWRITER_SYNC_USER_ID              (UUID, 已弃用 ⚠️ — 现在 sync 自动用
                                          autowriter.projects.owner_id 作为
                                          batches/items.user_id, 真实用户在登录
                                          后才能透过 RLS 看到 TV-synced rows;
                                          仅当 projects.owner_id 缺失 (异常)
                                          时回退到这个值。新部署不再需要配)
    AUTOWRITER_INJECTION_MAX_PER_PROJECT (默认 5; 每个 autowriter 项目每轮最多
                                          sync N 个高分候选. 2026-05-22 audit
                                          P1-2 修复: 旧的 MAX_PER_RUN 是全局上限,
                                          多项目时会让大项目独占名额、小项目饥饿)
    AUTOWRITER_INJECTION_GLOBAL_CAP      (默认 0=不限; 跨所有项目的硬上限. 设为 N>0
                                          会在 per-project 选完后用 round-robin
                                          按分数轮询裁到 N 条以内)
    AUTOWRITER_INJECTION_MAX_PER_RUN     (DEPRECATED: 兼容旧 cron 用, 现作为
                                          MAX_PER_PROJECT 的别名读取)
    AUTOWRITER_INJECTION_MIN_SCORE       (默认 0.5; 低于此 score 的候选不 sync)
    AUTOWRITER_INJECTION_MIN_LEVERS      (默认 3; diversity 软目标 — 在条件允许时
                                          确保 top N 至少覆盖 N 个不同 emotional_lever)
    AUTOWRITER_EXAMPLE_MAX_AGE_DAYS      (默认 180; 退役 cutoff)

RLS 兼容性 (audit 2026-05-21):
    autowriter.batches / items 的 RLS policy 形如
    `USING (user_id = auth.uid())`。如果 TV sync 写入一个 service account
    的 user_id，普通登录用户读取时 RLS 会把这些行隐藏，导致 autowriter
    的 list_example_items() 取不到 TV-synced positive examples，飞轮静默
    断开。本脚本现在每个 aw_project 自动查询 owner_id 并把它作为
    batches/items.user_id 写入，让 project owner 用自己的 JWT 就能读到。
    历史 TV-synced rows 的 user_id 需用 autowriter-migrations/006_backfill_
    tv_synced_user_id.sql 批量修正。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from _common import fetch_all_pages, get_supabase_client, setup_logger, _iso_now


logger = setup_logger("sync_tv_baokuan_to_aw")


SPECIAL_BATCH_TACTIC = "truth_vault_synced"
SPECIAL_BATCH_AI_ENGINE = "truth_vault_sync"  # versions.ai_engine 用，v_model_comparison 会排除

# Tunables — env-var configurable so ops can adjust without touching code.
#
# 2026-05-22 audit P1-2 fix: the cap is now per-autowriter-project, not global.
# AUTOWRITER_INJECTION_MAX_PER_RUN is kept as a deprecated alias so existing
# cron envs don't silently break, but new ops should use
# AUTOWRITER_INJECTION_MAX_PER_PROJECT. With the global cap, high-volume
# projects could occupy all 5 daily slots and starve smaller projects of
# few-shot examples. Per-project quotas guarantee each mapped project gets
# its own fair share; aggregate cap is enforced by --global-cap (default
# unbounded since per-project quota already caps total at quota × N projects).
# 2026-05-22 audit P1 (codex PR #14 discussion_r3286552079):
# GitHub Actions 把"未配的 secret"渲染成空字符串而不是 unset env.
# 标准 os.environ.get(name, default) 拿到空串会跳过 default 返回 ""，
# 再 int("") / float("") 直接 ValueError. 用 helper 把 "" / 空白当作 unset
# 才安全 — workflow 写 secrets.X 时 default 也照样生效.
def _env_int(name: str, default: int, *, fallback_envs: tuple[str, ...] = ()) -> int:
    val = os.environ.get(name, "").strip()
    if val:
        return int(val)
    for fb in fallback_envs:
        fb_val = os.environ.get(fb, "").strip()
        if fb_val:
            return int(fb_val)
    return default


def _env_float(name: str, default: float) -> float:
    val = os.environ.get(name, "").strip()
    return float(val) if val else default


DEFAULT_INJECTION_MAX_PER_PROJECT = _env_int(
    "AUTOWRITER_INJECTION_MAX_PER_PROJECT",
    5,
    fallback_envs=("AUTOWRITER_INJECTION_MAX_PER_RUN",),
)
DEFAULT_INJECTION_GLOBAL_CAP = _env_int("AUTOWRITER_INJECTION_GLOBAL_CAP", 0)  # 0 = unbounded
DEFAULT_INJECTION_MIN_SCORE = _env_float("AUTOWRITER_INJECTION_MIN_SCORE", 0.5)
DEFAULT_INJECTION_MIN_LEVERS = _env_int("AUTOWRITER_INJECTION_MIN_LEVERS", 3)
DEFAULT_EXAMPLE_MAX_AGE_DAYS = _env_int("AUTOWRITER_EXAMPLE_MAX_AGE_DAYS", 180)


def resolve_aw_project_owner(sb, aw_project_id: str) -> str:
    """Return autowriter.projects.owner_id for the given aw_project_id.

    Why this matters (audit 2026-05-21 P0 #3): batches/items RLS is
    `USING (user_id = auth.uid())`. If TV sync writes a service-account
    user_id, normal users authenticated with their own JWT never see the
    synced rows, so list_example_items() returns nothing and the flywheel
    is silently broken. Writing project.owner_id as user_id makes RLS
    pass for the project owner.

    Raises RuntimeError if the project is missing or has NULL owner_id —
    autowriter.projects.owner_id is NOT NULL in the live schema, so NULL
    here means schema corruption and we refuse to fall through to a
    bogus user_id silently.
    """
    res = (
        sb.schema("autowriter")
        .table("projects")
        .select("owner_id")
        .eq("id", aw_project_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise RuntimeError(
            f"aw_project_id={aw_project_id} not found in autowriter.projects "
            "— cannot determine owner_id for TV sync. Check truth_vault "
            "project mapping_to_autowriter_project_id points at a real project."
        )
    owner_id = res.data[0].get("owner_id")
    if not owner_id:
        raise RuntimeError(
            f"aw_project_id={aw_project_id} has NULL owner_id — violates "
            "autowriter.projects.owner_id NOT NULL invariant. Fix the project "
            "row before re-running sync."
        )
    return owner_id


def fetch_injection_candidates(sb, project_filter: str | None = None) -> list[dict]:
    """Pull pending baokuan from the ranking view, ordered by score DESC.

    Reads `truth_vault.v_autowriter_injection_candidates` which has the
    eligibility filters baked in (tier IN ('爆','大爆'), tier_source !=
    '数值推断', publish_time within 12 months, project has aw mapping).
    Adds `synced_to_aw_at IS NULL` here since the view doesn't filter on
    sync state (it's a candidate pool, not a queue).

    Paginated explicitly — even with the 12-month + tier filters, a
    long-running deployment will eventually have hundreds of pending
    rows; the 1000-row PostgREST default would truncate silently.
    """
    q = (
        sb.schema("truth_vault")
        .table("v_autowriter_injection_candidates")
        .select(
            "note_id, project_id, raw_content, hit_blue_keywords, tier, "
            "tier_source, emotional_lever, target_audience, publish_time, "
            "synced_to_aw_at, account_id, brand, category, "
            "mapping_to_autowriter_project_id, "
            "recency_weight, account_bao_rate, injection_score"
        )
        .is_("synced_to_aw_at", None)
    )
    if project_filter:
        q = q.eq("project_id", project_filter)
    # PostgREST honors ORDER BY on a view. View output isn't materialized; the
    # score expression is computed at query time.
    rows = fetch_all_pages(q.order("injection_score", desc=True))
    # Map mapping_to_autowriter_project_id → aw_project_id for downstream
    # code that doesn't want the long name.
    for r in rows:
        r["aw_project_id"] = r["mapping_to_autowriter_project_id"]
    return rows


def apply_diversity_filter(
    candidates: list[dict],
    max_n: int = DEFAULT_INJECTION_MAX_PER_PROJECT,
    min_levers: int = DEFAULT_INJECTION_MIN_LEVERS,
) -> list[dict]:
    """Pick at most `max_n` candidates from the score-sorted list, prioritising
    coverage across distinct emotional_lever values.

    Two-pass strategy:
      1. First pass: walk the score-sorted list, accept each item only if its
         lever hasn't been seen yet (or if it has no lever — essence-unannotated
         rows still flow through, they just don't contribute to diversity).
      2. Second pass: if we don't have max_n yet (e.g. fewer distinct levers
         than max_n available), fill remaining slots by score order.

    The result is: top N by score whenever diversity allows, but a single
    very dominant lever can take >1 slot if it's also the only one available.
    When essence annotation isn't filled in (early-Sprint state), `levers_seen`
    stays empty and the function degenerates to a plain top-N-by-score.

    `min_levers` is currently advisory — we don't reject runs that fall short
    (which would block sync entirely when a project only has 1 lever). It's
    surfaced in logging so the operator can spot saturation as it builds.
    """
    if not candidates:
        return []

    picked: list[dict] = []
    picked_ids: set[str] = set()
    levers_seen: set[str] = set()

    # Pass 1: prefer new levers
    for c in candidates:
        if len(picked) >= max_n:
            break
        lever = c.get("emotional_lever")
        if lever is None or lever not in levers_seen:
            picked.append(c)
            picked_ids.add(c["note_id"])
            if lever:
                levers_seen.add(lever)

    # Pass 2: fill any remaining slots by raw score order
    if len(picked) < max_n:
        for c in candidates:
            if len(picked) >= max_n:
                break
            if c["note_id"] not in picked_ids:
                picked.append(c)
                picked_ids.add(c["note_id"])

    if levers_seen and len(levers_seen) < min_levers:
        logger.warning(
            "diversity advisory: top %d picks cover only %d distinct emotional_lever "
            "(target ≥ %d). Pool may be saturated; consider widening the project's "
            "content angle or lowering min_levers temporarily.",
            len(picked), len(levers_seen), min_levers,
        )

    return picked


def retire_stale_autowriter_examples(
    sb,
    max_age_days: int = DEFAULT_EXAMPLE_MAX_AGE_DAYS,
    dry_run: bool = False,
) -> int:
    """Clear example_label on TV-synced items older than max_age_days.

    Stops old baokuan from forever occupying autowriter's positive_examples
    pool. We don't delete the rows (they're audit/lineage artifacts) — just
    clear the label so `list_example_items` stops returning them.

    Idempotent: re-running on an already-retired row is a no-op (label is
    already NULL so the WHERE clause excludes it).

    Returns the number of items affected. Logs in detail for the first few
    so operators can see what's rotating out.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).replace(tzinfo=None)
    cutoff_iso = cutoff.isoformat(timespec="seconds")

    sel = (
        sb.schema("autowriter")
        .table("items")
        .select("id, external_source_id, created_at")
        .eq("external_source", "truth_vault")
        .eq("example_label", "positive")
        .lt("created_at", cutoff_iso)
        .execute()
    )
    candidates = sel.data or []

    if not candidates:
        logger.info(
            "No stale TV-synced positive examples to retire (cutoff=%s, max_age=%d days)",
            cutoff_iso, max_age_days,
        )
        return 0

    logger.info(
        "Retiring %d stale TV-synced positive examples (created < %s)",
        len(candidates), cutoff_iso,
    )
    for c in candidates[:5]:
        logger.info("  retiring %s (created %s)", c["external_source_id"], c["created_at"])
    if len(candidates) > 5:
        logger.info("  ... and %d more", len(candidates) - 5)

    if dry_run:
        return len(candidates)

    (
        sb.schema("autowriter")
        .table("items")
        .update({"example_label": None})
        .eq("external_source", "truth_vault")
        .eq("example_label", "positive")
        .lt("created_at", cutoff_iso)
        .execute()
    )
    return len(candidates)


def ensure_special_batch(sb, aw_project_id: str, project_user_id: str,
                        dry_run: bool = False) -> str:
    """Find or create the per-project 'truth_vault_synced' batch.

    project_user_id is normally autowriter.projects.owner_id (resolved by
    resolve_aw_project_owner) so the resulting batch is RLS-visible to the
    project owner. See module docstring "RLS 兼容性".

    Returns the batch id.  We use a stable deterministic UUID seeded on
    aw_project_id so re-runs across machines produce the same batch_id;
    avoids ON CONFLICT plumbing on a table that doesn't yet have a unique
    constraint on (project_id, tactic).

    Self-heal (2026-05-22 audit P0/P1-1): if the batch already exists but its
    user_id doesn't match the current project owner (i.e., upgrade from an
    old install where TV sync wrote a service-account UUID), we UPDATE it
    here. AutoWriter's list_example_items() filters via batches!inner
    (project_id) — when RLS hides the batch row from the owner's JWT, the
    embedded join filters out all items in the batch, even items whose
    user_id is correct. Without this self-heal we'd be relying on operators
    to remember to run autowriter-migrations/006_backfill_tv_synced_user_id.sql
    after upgrading, and we'd silently fail on missed installs.
    """
    # Deterministic UUID5 based on project_id + tactic
    namespace = uuid.UUID("00000000-0000-0000-0000-000000000000")
    batch_id = str(uuid.uuid5(namespace, f"{aw_project_id}:{SPECIAL_BATCH_TACTIC}"))

    if dry_run:
        logger.info("[dry-run] would ensure batch %s exists for project %s",
                    batch_id, aw_project_id)
        return batch_id

    # Try to find the batch first; if missing, create it. Select user_id
    # and project_id so we can detect drift from the current canonical
    # (project_user_id, aw_project_id) tuple.
    existing = (
        sb.schema("autowriter")
        .table("batches")
        .select("id, user_id, project_id")
        .eq("id", batch_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        row = existing.data[0]
        existing_user = row.get("user_id")
        existing_proj = row.get("project_id")

        repair: dict[str, Any] = {}
        if existing_user != project_user_id:
            repair["user_id"] = project_user_id
            logger.warning(
                "special batch %s has stale user_id=%s; self-healing to "
                "project owner_id=%s (resolves RLS visibility for owner JWT). "
                "This typically means an upgraded library never ran "
                "autowriter-migrations/006_backfill_tv_synced_user_id.sql.",
                batch_id, existing_user, project_user_id,
            )
        if existing_proj != aw_project_id:
            # This would be schema corruption: same UUID5 keyed batch but
            # pointing at a different project. Refuse to silently rewrite.
            raise RuntimeError(
                f"special batch {batch_id} has project_id={existing_proj} "
                f"but UUID5 derivation expects {aw_project_id} — schema "
                "corruption, refuse to update. Investigate manually."
            )
        if repair:
            res = (
                sb.schema("autowriter")
                .table("batches")
                .update(repair)
                .eq("id", batch_id)
                .execute()
            )
            if not (res.data or []):
                raise RuntimeError(
                    f"failed to self-heal batch {batch_id} user_id — "
                    "UPDATE matched no rows (RLS or row vanished). "
                    "Manual fix required."
                )
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
            "user_id": project_user_id,
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

    Reconciliation rule for best_version_id:
      - already points to a real version on this item → keep it
      - NULL or stale (points to a deleted/foreign UUID) → re-link to a
        real version on this item and log
    The old "UPDATE ... WHERE best_version_id IS NULL" silently no-op'd
    on stale pointers; the caller would then write a version_id back to
    truth_vault that didn't match the autowriter side, corrupting lineage.

    Returns the version_id that ends up linked as best_version_id.
    """
    item_state = (
        sb.schema("autowriter")
        .table("items")
        .select("best_version_id")
        .eq("id", item_id)
        .limit(1)
        .execute()
    )
    current_best = (
        item_state.data[0]["best_version_id"] if item_state.data else None
    )

    existing_versions = (
        sb.schema("autowriter")
        .table("versions")
        .select("id")
        .eq("item_id", item_id)
        .execute()
    ).data or []
    existing_ids = {v["id"] for v in existing_versions}

    if existing_versions:
        if current_best in existing_ids:
            return current_best
        chosen = existing_versions[0]["id"]
        if current_best is not None:
            logger.warning(
                "item %s has stale best_version_id=%s (not in %d existing "
                "versions); re-linking to %s",
                item_id, current_best, len(existing_versions), chosen,
            )
        res = (
            sb.schema("autowriter")
            .table("items")
            .update({"best_version_id": chosen})
            .eq("id", item_id)
            .execute()
        )
        # supabase-py returns the updated row(s); empty list means the WHERE
        # matched no rows, which here would mean the item disappeared
        # between our two queries. Surface this so the caller can see it
        # instead of marking the note synced against a deleted item.
        if not (res.data or []):
            raise RuntimeError(
                f"item_id={item_id} vanished between read and best_version_id "
                "update — refusing to mark note synced against a missing item"
            )
        return chosen

    # 2026-05-22 audit P2 race window 收窄: 上面 SELECT 后到这里 INSERT 之间,
    # 另一个 worker 可能已经创建了 version. 重查一次, 已经有就直接用别人那条
    # (不再 INSERT, 避免给同一 item 重复插 version 行 / 留下孤儿 version).
    # 注: autowriter.versions 对 (item_id, version_num) 没有唯一约束, 所以这里靠
    # 应用层重查防重复, 不是靠 DB 唯一键 (早期注释误称撞唯一键, 已更正).
    recheck = (
        sb.schema("autowriter")
        .table("versions")
        .select("id")
        .eq("item_id", item_id)
        .limit(1)
        .execute()
    ).data or []
    if recheck:
        chosen = recheck[0]["id"]
        logger.info(
            "item %s: another worker just created version %s; reusing it",
            item_id, chosen,
        )
        res = (
            sb.schema("autowriter")
            .table("items")
            .update({"best_version_id": chosen})
            .eq("id", item_id)
            .execute()
        )
        if not (res.data or []):
            raise RuntimeError(
                f"item_id={item_id} vanished between recheck and best_version_id "
                "update — refusing to mark note synced against a missing item"
            )
        return chosen

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
    res = (
        sb.schema("autowriter")
        .table("items")
        .update({"best_version_id": version_id})
        .eq("id", item_id)
        .execute()
    )
    if not (res.data or []):
        raise RuntimeError(
            f"item_id={item_id} vanished between version insert and "
            "best_version_id link — leaves orphan version, refusing to "
            "mark note synced"
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
    project_user_id: str,
    dry_run: bool = False,
) -> tuple[str | None, bool]:
    """Insert the autowriter.items row + version row, idempotently.

    project_user_id is normally autowriter.projects.owner_id so the row is
    RLS-visible to the project owner. See module docstring "RLS 兼容性".

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
                "user_id": project_user_id,
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
        # Filter by user_id to align with autowriter's per-user unique index
        # (autowriter db.py: items_external_source_per_user_uniq). Without
        # user_id filter, a stale row from a previous service-account sync
        # could be returned and we'd write the wrong UUID back. Pre-006
        # backfill rows have stale user_id; run 006 first so the lookup hits
        # the current project_user_id row.
        existing = (
            sb.schema("autowriter")
            .table("items")
            .select("id, best_version_id")
            .eq("user_id", project_user_id)
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
    parser.add_argument(
        "--max-per-project", type=int, default=DEFAULT_INJECTION_MAX_PER_PROJECT,
        help="Sync at most N high-score candidates per autowriter project per "
             "run (default: env AUTOWRITER_INJECTION_MAX_PER_PROJECT or "
             "AUTOWRITER_INJECTION_MAX_PER_RUN or 5). Each project gets its "
             "own diversity filter pass and quota; no project starves another.",
    )
    parser.add_argument(
        "--max-per-run", type=int, default=None,
        help="DEPRECATED (2026-05-22 audit P1-2): was a global cap. Now treated "
             "as alias for --max-per-project (since the global cap was the "
             "source of project-starvation bugs). Use --global-cap if you "
             "actually want a hard aggregate ceiling across all projects.",
    )
    parser.add_argument(
        "--global-cap", type=int, default=DEFAULT_INJECTION_GLOBAL_CAP,
        help="Hard ceiling on total candidates synced across all projects this "
             "run (default: env AUTOWRITER_INJECTION_GLOBAL_CAP or 0 = unbounded). "
             "When set > 0, after per-project picks are made, we round-robin "
             "across projects in descending score order and stop at this cap. "
             "Set this if you want to bound total cost/quota even when many "
             "new projects come online.",
    )
    parser.add_argument(
        "--min-score", type=float, default=DEFAULT_INJECTION_MIN_SCORE,
        help="Skip candidates with injection_score below this. Default 0.5.",
    )
    parser.add_argument(
        "--skip-retire", action="store_true",
        help="Skip the post-sync retire pass (the one that clears example_label "
             "on TV-synced items older than 6 months).",
    )
    args = parser.parse_args()

    # Handle deprecated --max-per-run alias.
    if args.max_per_run is not None:
        if args.max_per_project != DEFAULT_INJECTION_MAX_PER_PROJECT:
            logger.warning(
                "both --max-per-run (=%d) and --max-per-project (=%d) supplied; "
                "--max-per-project takes precedence. Remove --max-per-run from cron.",
                args.max_per_run, args.max_per_project,
            )
        else:
            args.max_per_project = args.max_per_run
            logger.warning(
                "--max-per-run is deprecated (2026-05-22 audit P1-2) — treating "
                "as --max-per-project=%d. Please update cron/Actions to use "
                "--max-per-project explicitly.",
                args.max_per_run,
            )

    # AUTOWRITER_SYNC_USER_ID is now a fallback only — see module docstring
    # "RLS 兼容性". We use autowriter.projects.owner_id as the canonical
    # user_id so RLS lets the project owner read TV-synced rows.
    fallback_user_id = os.environ.get("AUTOWRITER_SYNC_USER_ID")
    if fallback_user_id:
        try:
            uuid.UUID(fallback_user_id)
        except (ValueError, AttributeError):
            logger.error(
                "AUTOWRITER_SYNC_USER_ID=%r is not a valid UUID (used only as "
                "fallback when projects.owner_id lookup fails).",
                fallback_user_id,
            )
            return 2
        logger.info(
            "AUTOWRITER_SYNC_USER_ID is set but only used as fallback; "
            "default behaviour is to write project owner_id (RLS-compatible)."
        )

    sb = get_supabase_client()
    candidates = fetch_injection_candidates(sb, project_filter=args.project)
    logger.info(
        "Found %d eligible candidates (view-filtered: tier∈爆/大爆, tier_source!='数值推断', "
        "publish_time within 12m, project has aw mapping)",
        len(candidates),
    )

    # Min-score gate: candidates below threshold stay pending across runs.
    # If the project's quality bar is genuinely lower we should re-tune the
    # min-score, not bypass it case by case.
    above_threshold = [c for c in candidates if c["injection_score"] >= args.min_score]
    if len(above_threshold) < len(candidates):
        logger.info(
            "Filtered out %d candidates below min_score=%.2f",
            len(candidates) - len(above_threshold), args.min_score,
        )

    # Per-project diversity pick + per-project cap (2026-05-22 audit P1-2).
    # Group candidates by aw_project_id so each project gets its own diversity
    # pass; this prevents a high-volume project from occupying the entire
    # global slate. Old behavior: apply_diversity_filter on the flat list,
    # which silently starved smaller projects when scores tilted toward one.
    by_project: dict[str, list[dict]] = {}
    for c in above_threshold:
        by_project.setdefault(c["aw_project_id"], []).append(c)

    selected: list[dict] = []
    per_project_log: dict[str, tuple[int, int]] = {}  # aw_proj → (picked, pool)
    for aw_proj, pool in by_project.items():
        # The view returns score-sorted overall; we re-sort within the project
        # bucket so per-project diversity_filter sees its own top picks first.
        pool.sort(key=lambda r: r["injection_score"], reverse=True)
        picks = apply_diversity_filter(pool, max_n=args.max_per_project)
        selected.extend(picks)
        per_project_log[aw_proj] = (len(picks), len(pool))

    # Optional global cap. When set, we sort the union by score and trim, but
    # we sort within each project first so the cut preserves per-project fairness:
    # if global_cap=10 and 3 projects each picked 5, the cut should leave
    # 4/3/3 (or similar round-robin), not 5/5/0.
    if args.global_cap > 0 and len(selected) > args.global_cap:
        # Round-robin by descending score within each project; take in waves
        # until we hit the cap.
        per_proj_queues: list[list[dict]] = [
            sorted(by_project[p], key=lambda r: r["injection_score"], reverse=True)
            for p in by_project
        ]
        # Filter each queue to only items we already selected (project picks)
        selected_ids = {c["note_id"] for c in selected}
        per_proj_queues = [
            [c for c in q if c["note_id"] in selected_ids] for q in per_proj_queues
        ]
        rr_selected: list[dict] = []
        idx = 0
        while len(rr_selected) < args.global_cap:
            advanced = False
            for q in per_proj_queues:
                if idx < len(q) and len(rr_selected) < args.global_cap:
                    rr_selected.append(q[idx])
                    advanced = True
            if not advanced:
                break
            idx += 1
        logger.info(
            "Global cap %d applied: %d → %d selected (round-robin by project).",
            args.global_cap, len(selected), len(rr_selected),
        )
        selected = rr_selected

    # Log per-project selection so operators can spot starved projects
    # (e.g., aw_proj=X pool=80 picked=5 means project X has lots of pending,
    # which is healthy; pool=0 picked=0 means truly nothing eligible).
    for aw_proj, (picked, pool) in per_project_log.items():
        logger.info(
            "  aw_project=%s: picked=%d / pool=%d (cap=%d)",
            aw_proj, picked, pool, args.max_per_project,
        )
    logger.info(
        "Selected %d candidates across %d projects (per-project cap=%d, global_cap=%s)",
        len(selected), len(by_project), args.max_per_project,
        args.global_cap if args.global_cap > 0 else "unbounded",
    )

    # Group by aw_project_id so we create each special batch only once.
    # owner_cache is keyed by aw_project_id so we only query projects.owner_id
    # once per project per run, even if many baokuan map to the same project.
    batch_cache: dict[str, str] = {}
    owner_cache: dict[str, str] = {}
    stats = {"synced": 0, "deduped": 0, "errors": 0, "retired": 0}

    for note in selected:
        aw_proj = note["aw_project_id"]
        try:
            if aw_proj not in owner_cache:
                try:
                    owner_cache[aw_proj] = resolve_aw_project_owner(sb, aw_proj)
                except RuntimeError as exc:
                    if fallback_user_id:
                        logger.warning(
                            "owner_id lookup failed for project %s (%s); "
                            "falling back to AUTOWRITER_SYNC_USER_ID. Items "
                            "written this run will be invisible to project "
                            "owner under RLS until owner_id is restored.",
                            aw_proj, exc,
                        )
                        owner_cache[aw_proj] = fallback_user_id
                    else:
                        raise
            project_user_id = owner_cache[aw_proj]
            if aw_proj not in batch_cache:
                batch_cache[aw_proj] = ensure_special_batch(
                    sb, aw_proj, project_user_id, dry_run=args.dry_run,
                )
            item_id, is_new = insert_synced_item(
                sb, note, batch_cache[aw_proj], project_user_id, dry_run=args.dry_run,
            )
            # Always write the real UUID back to truth_vault.notes — whether
            # this run inserted the item or just looked up an existing one.
            # synced_autowriter_item_id is a UUID column, so we cannot pass
            # a sentinel string like '(deduped)' (audit issue 4).
            mark_synced(sb, note["note_id"], item_id, dry_run=args.dry_run)
            if is_new:
                stats["synced"] += 1
                logger.info(
                    "Synced %s (tier=%s, score=%.2f, lever=%s) → aw item %s",
                    note["note_id"], note["tier"], note["injection_score"],
                    note.get("emotional_lever") or "?", item_id,
                )
            else:
                stats["deduped"] += 1
        except Exception as exc:
            logger.exception("note_id=%s failed: %s", note["note_id"], exc)
            stats["errors"] += 1

    # Post-sync: retire old TV-synced positive examples so autowriter doesn't
    # forever serve stale baokuan to its prompt.
    if not args.skip_retire:
        try:
            stats["retired"] = retire_stale_autowriter_examples(sb, dry_run=args.dry_run)
        except Exception as exc:
            logger.exception("retire pass failed (sync results unaffected): %s", exc)

    logger.info("Done: %s", json.dumps(stats, ensure_ascii=False))
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
