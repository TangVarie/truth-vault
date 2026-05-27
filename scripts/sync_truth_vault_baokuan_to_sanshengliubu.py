"""
sync_truth_vault_baokuan_to_sanshengliubu.py
═══════════════════════════════════════════════════════════════════════════

把 Truth Vault 中 tier ∈ ('爆', '大爆', '参考') 的笔记 sync 到
public.reference_samples（sanshengliubu 保持在 public schema，D-024）。
注入到 vibe_rewriter 的高权重检索池。

用法:
    python sync_truth_vault_baokuan_to_sanshengliubu.py
    python sync_truth_vault_baokuan_to_sanshengliubu.py --project NUC_phase1
    python sync_truth_vault_baokuan_to_sanshengliubu.py --dry-run

幂等性:
    主键: public.reference_samples.source_truth_vault_note_id（专门加的
          干净索引列，由 sanshengliubu-patches/001_add_source_tv_note_id.sql
          创建）。这是判断「已 sync」的正式幂等键，preflight_check 会拒绝
          没有该列的部署。
    Fallback: 仅对历史行（migration 之前 insert 的 row）会回退到
          ai_analysis->>'_truth_vault_note_id'。新写入一律两个都填，未来
          可以把 fallback 路径删掉。
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


# TV canonical platform key (English, see schemas/notes_v1_2.sql) → sanshengliubu
# UI display name (Chinese, see sanshengliubu pipeline/config.py:DEFAULT_PLATFORM and
# pages/2_new_project.py 平台选项). sanshengliubu 的 list_reference_packs 用
# `.eq("platform", platform)` 精确过滤，其中 platform 来自项目配置（中文）。
# 不翻译就会导致 TV 写入 'xiaohongshu' 而 sanshengliubu 检索 '小红书' 永远空。
_PLATFORM_EN_TO_SSLL: dict[str, str] = {
    "xiaohongshu": "小红书",
    "douyin":      "抖音",
    "weibo":       "微博",
    "bilibili":    "B站",
    "kuaishou":    "快手",
}

# 2026-05-22 audit P2: 老版本不在 dict 里的平台会 silent fallback 写英文,
# sanshengliubu 用中文检索时永远空, 飞轮静默漂移. 改成显式白名单 (中+英)
# + 未知平台立刻报错. 加新平台必须先在两边都加, 防漏。
_PLATFORM_ALLOWED_ZH: frozenset[str] = frozenset(_PLATFORM_EN_TO_SSLL.values())


def _platform_for_ssll(en_or_zh: str | None) -> str:
    """Map TV's canonical English platform key to sanshengliubu's display name.

    - None / 空 → 默认 "小红书" (TV 单一品类目前都跑小红书)
    - 已知 英文 (xiaohongshu / douyin / ...) → 翻译成对应中文
    - 已知 中文 (小红书 / 抖音 / ...) → 直接放过
    - 其他 → ValueError. 不再 silent fallback, 防"看似在跑实际飞轮断"。

    新增平台时:
      1. 这里 _PLATFORM_EN_TO_SSLL 加一行
      2. sanshengliubu 仓那边确认新平台在 list_reference_packs 检索逻辑里有处理
      3. truth-vault docs/03-mapping-protocol.md platform 枚举更新
    """
    if not en_or_zh:
        return "小红书"
    if en_or_zh in _PLATFORM_EN_TO_SSLL:
        return _PLATFORM_EN_TO_SSLL[en_or_zh]
    if en_or_zh in _PLATFORM_ALLOWED_ZH:
        return en_or_zh
    raise ValueError(
        f"Unknown platform {en_or_zh!r}. Add it to _PLATFORM_EN_TO_SSLL "
        "in this file AND confirm sanshengliubu list_reference_packs handles it. "
        f"Currently allowed: en={sorted(_PLATFORM_EN_TO_SSLL.keys())}, "
        f"zh={sorted(_PLATFORM_ALLOWED_ZH)}"
    )


def fetch_pending_baokuan(
    sb,
    project_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Query Truth Vault for baokuan notes not yet synced to sanshengliubu.

    Eligibility filters (matching通道 2 D-036 data-hygiene rules):
      - tier ∈ ('爆','大爆','参考')                       爆款 + 运营标的参考级 (参考权重低)
      - tier_source != '数值推断'                          排除未人工 confirm 的自动 tier
                                                          (运营要把某条数值推断的 row
                                                          重新纳入 sync, 改 tier_source 为
                                                          '人工补录': UPDATE notes SET
                                                          tier_source='人工补录' WHERE
                                                          note_id=...)
      - publish_time within 12 months                     不持续推过气审美进 ssll
                                                          的 reference_samples
      - synced_to_ssll_at IS NULL                         未同步
      - data_quality_flags.synthetic != true              排除伪爆贴 (WTG「笔记状态」
                                                          含"关注"的人工假数据). 和通道 2
                                                          v_autowriter_injection_candidates
                                                          的 synthetic 排除对齐, 防假
                                                          指标的爆款污染两条飞轮.

    Paginates explicitly. Supabase's PostgREST defaults to 1000 rows/response;
    once enough projects onboard, unsynced 爆款 will cross that boundary and
    silent truncation would leak baokuan from the flywheel.
    """
    from datetime import datetime, timedelta, timezone
    twelve_months_ago = (
        datetime.now(timezone.utc) - timedelta(days=365)
    ).replace(tzinfo=None).isoformat(timespec="seconds")

    q = (
        sb.schema("truth_vault")
        .table("notes")
        .select("note_id, project_id, raw_content, hit_blue_keywords, "
                "tier, tier_source, intent, publish_url, publish_time, "
                "target_audience, data_quality_flags, projects(category, brand, platform)")
        .in_("tier", ["爆", "大爆", "参考"])
        .neq("tier_source", "数值推断")
        .gte("publish_time", twelve_months_ago)
        .is_("synced_to_ssll_at", None)
    )
    if project_filter:
        q = q.eq("project_id", project_filter)
    rows = fetch_all_pages(q)
    # 排除伪爆贴 (synthetic). 在 Python 过滤而非 PostgREST: JSONB ->>'synthetic'
    # 为 NULL (绝大多数正常行) 时, PostgREST 的 neq.true 会把 NULL 也滤掉 (NULL
    # <> 'true' = NULL = 不通过), 反而漏掉正常行. Python 端显式判 True 最稳.
    return [
        r for r in rows
        if not (isinstance(r.get("data_quality_flags"), dict)
                and r["data_quality_flags"].get("synthetic") is True)
    ]


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

    Schema source of truth: sanshengliubu's db/schema.sql + db/migrations/
    005_reference_samples_v2.sql. The live v2 columns vibe_rewriter actually
    reads (see pipeline/retrieve_samples._shape_for_rewriter) are:

        id, platform, category, post_title, post_body, top_comments,
        ai_analysis

    Plus the canonical write path (db/supabase_client.save_reference_pack)
    also writes title, source_type, content_text (legacy mirror), tags,
    quality_score.

    Anything NOT in that schema (brand, source_url, target_audience,
    hit_keywords — fields TV cares about but ssll doesn't have columns
    for) goes into ai_analysis under leading-underscore TV-injected keys.

    top_comments shape: live ssll schema is JSONB array of {text, likes?}
    dicts (vibe_rewriter passes the list verbatim to the prompt; extra
    keys are tolerated). truth_vault.comments has no `likes` column, so
    we emit {text, role, pinned} — `role` and `pinned` are extra
    metadata that the prompt may or may not use but don't hurt.
    """
    proj = note.get("projects") or {}
    tier = note.get("tier")
    # tier → quality_score is sanshengliubu's own column (INTEGER) used
    # for "优质优先" sample retrieval ordering.  爆=100, 大爆=200 puts
    # TV-injected samples comfortably above any default 0.
    quality_score = {"爆": 100, "大爆": 200}.get(tier, 0)

    # Comments as [{text, role, pinned}, …] — the shape vibe_rewriter
    # expects (see pipeline/agents/reference_pack_analyzer docstring:
    # `top_comments: [{"text": "...", "likes": 123}, ...]`). `likes`
    # isn't tracked in truth_vault.comments; we omit it rather than
    # invent a fake number.
    top_comments = [
        {
            "text": c.get("content"),
            "role": c.get("comment_role"),
            "pinned": bool(c.get("is_pinned")),
        }
        for c in comments
        if c.get("content")
    ]

    ai_analysis = {
        # Cross-system lineage (leading underscore = TV-injected, not ssll-native).
        "_truth_vault_note_id": note["note_id"],           # idempotency key (also top-level column)
        "_truth_vault_project_id": note["project_id"],
        "_truth_vault_tier": tier,
        "_truth_vault_intent": note.get("intent"),
        "_truth_vault_quality_score": quality_score,
        # TV-specific metadata that ssll's reference_samples schema has no
        # top-level home for. Stash here so any TV-side downstream (e.g.
        # an Analytics view that joins by sample_id) can still see them.
        "_truth_vault_brand": proj.get("brand"),
        "_truth_vault_source_url": note.get("publish_url"),
        "_truth_vault_target_audience": note.get("target_audience"),
        "_truth_vault_hit_blue_keywords": note.get("hit_blue_keywords") or [],
    }

    raw_content = note.get("raw_content") or ""
    # Use the first line / first 80 chars as a synthetic title — TV notes
    # don't carry an original post title, so this is the best approximation.
    # 80 chars is what ssll's own save_reference_pack uses.
    synthetic_title = raw_content.split("\n", 1)[0][:80] or "未命名样本"

    return {
        "id": str(uuid.uuid4()),
        # ── Top-level columns ssll's vibe_rewriter actually reads ──
        "post_title": synthetic_title,
        "post_body":  raw_content,
        "top_comments": top_comments,
        # platform: write sanshengliubu's display value (中文) so its
        # list_reference_packs filter `.eq("platform", "小红书")` finds us.
        "platform":   _platform_for_ssll(proj.get("platform") or note.get("platform")),
        "category":   proj.get("category"),
        "ai_analysis": ai_analysis,
        # ── Other top-level columns the canonical write path sets ──
        "title":        synthetic_title,
        # source_type: sanshengliubu list_reference_packs filters
        # `.eq("source_type", "pack")` — writing 'pack' is required for
        # TV samples to appear in vibe_rewriter retrieval. The TV-origin
        # discriminator stays in `tags` below and in `source_truth_vault_note_id`.
        "source_type":  "pack",
        "content_text": raw_content,          # legacy mirror; pre-v2 readers still see it
        "tags": ["truth_vault_sync"] + ([tier] if tier else []),
        "quality_score": quality_score,
        # ── Lineage / idempotency key (added by
        #    sanshengliubu-patches/001_add_source_tv_note_id.sql) ──
        # Without 001, idx_reference_samples_tv_note stays empty and
        # existing_ssll_sample_id() falls back to the slower JSON path.
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

    Required columns are the v2 reference_samples columns
    (db/migrations/005_reference_samples_v2.sql) plus the TV-injected
    lineage key (sanshengliubu-patches/001_add_source_tv_note_id.sql).
    If sanshengliubu renames any of these, update this list,
    build_reference_sample(), and docs/09-system-integration.md in one
    commit.
    """
    required = (
        "id, title, source_type, content_text, post_title, post_body, "
        "top_comments, platform, category, ai_analysis, quality_score, "
        "tags, source_truth_vault_note_id, created_at"
    )
    try:
        sb.schema("public").table("reference_samples").select(required).limit(0).execute()
    except Exception as exc:
        msg = str(exc)
        raise RuntimeError(
            "public.reference_samples preflight failed. The live sanshengliubu "
            "schema is missing one of the columns this script writes. Confirm "
            "sanshengliubu-patches/001_add_source_tv_note_id.sql has been run, "
            "and that sanshengliubu's own db/migrations/005_reference_samples_v2.sql "
            "(the v2 'evidence pack' columns: post_title / post_body / "
            "top_comments / platform / category / ai_analysis / quality_score) "
            f"has also been applied. Underlying error: {msg}"
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

    Two separate queries instead of an OR clause: PostgREST's `or=` is a
    comma-separated string filter, so embedding the raw note_id (which is
    f"{project_id}_{feishu_record_id}") meant a comma or '.' in the value
    could break the parser. Two `.eq()` queries are safer and the cost
    (a second round trip on the rare fallback) is negligible — the index
    on source_truth_vault_note_id makes the first probe ~free, and the
    second probe (the JSON path) runs only when the new column is empty.
    """
    primary = (
        sb.schema("public")
        .table("reference_samples")
        .select("id")
        .eq("source_truth_vault_note_id", note_id)
        .limit(1)
        .execute()
    )
    if primary.data:
        return primary.data[0]["id"]

    fallback = (
        sb.schema("public")
        .table("reference_samples")
        .select("id")
        .eq("ai_analysis->>_truth_vault_note_id", note_id)
        .limit(1)
        .execute()
    )
    if fallback.data:
        return fallback.data[0]["id"]
    return None


def _is_duplicate_error(exc: Exception) -> bool:
    """Detect Postgres unique-constraint violations from supabase-py.

    Same heuristic as the AutoWriter sync script: checks SQLSTATE 23505 in
    multiple possible attribute locations because supabase-py wraps the
    PostgREST error inconsistently across versions.
    """
    code = getattr(exc, "code", None) or getattr(exc, "pgcode", None)
    if code == "23505":
        return True
    msg = str(exc)
    return "23505" in msg or "duplicate key value violates" in msg


def insert_reference_sample(sb, sample: dict, dry_run: bool = False) -> str:
    """Insert a reference_samples row, recovering from concurrent dupes.

    2026-05-22 audit P1-3 update: the existing_ssll_sample_id() check runs
    before this in main(), but it's a separate query — a concurrent worker
    could insert the same source_truth_vault_note_id between our SELECT and
    INSERT. With the new partial UNIQUE index
    (sanshengliubu-patches/003), that race now surfaces as 23505 instead
    of silent duplicate rows. We catch it here and recover by looking up
    the winning row's id, so the caller's mark_synced() still gets a real
    sample_id to write back to truth_vault.notes.
    """
    note_id = sample.get("source_truth_vault_note_id")
    if dry_run:
        logger.info("[dry-run] would insert reference_sample id=%s for note %s",
                    sample["id"], note_id or "(no note id)")
        return sample["id"]
    try:
        (
            sb.schema("public")
            .table("reference_samples")
            .insert(sample)
            .execute()
        )
        return sample["id"]
    except Exception as exc:
        if not _is_duplicate_error(exc):
            raise
        # Race recovery: another worker won. Look up its id by the canonical
        # idempotency key so we still return a real UUID to the caller.
        if not note_id:
            # The dup wasn't on our key but on something else (e.g., primary
            # key collision from a re-used uuid). Re-raise so we don't claim
            # success for a row we didn't write.
            raise
        existing = (
            sb.schema("public")
            .table("reference_samples")
            .select("id")
            .eq("source_truth_vault_note_id", note_id)
            .limit(1)
            .execute()
        )
        if not existing.data:
            # 23505 said dup but the lookup found nothing — schema drift or
            # the row was deleted between INSERT and SELECT. Re-raise.
            raise
        winner_id = existing.data[0]["id"]
        logger.info(
            "race recovery: concurrent run inserted reference_sample %s for "
            "note %s first; treating as success", winner_id, note_id,
        )
        return winner_id


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
