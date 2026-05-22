"""
sync_feishu_notes_to_truth_vault.py
═══════════════════════════════════════════════════════════════════════════

把指定项目的飞书多维表格数据 sync 到 truth_vault.notes。

用法:
    python sync_feishu_notes_to_truth_vault.py NUC_phase1
    python sync_feishu_notes_to_truth_vault.py NRT_phase3 --dry-run
    python sync_feishu_notes_to_truth_vault.py NUC_phase1 --limit 10

环境变量:
    SUPABASE_URL                    （共享 Supabase 实例 URL）
    SUPABASE_SERVICE_ROLE_KEY       （service_role，绕过 RLS）
    FEISHU_APP_ID                   （飞书应用 ID）
    FEISHU_APP_SECRET               （飞书应用 Secret）

mapping yaml 必须包含 sync_config 段提供飞书表定位:
    sync_config:
      feishu_app_token: bascnXXXXXXXXXXXXX
      feishu_table_id:  tblXXXXXXXXXX
      feishu_view_id:   vewXXXXXXXXXX   # 可选；不填用 default view

幂等性:
    note_id 是 PRIMARY KEY (= f"{project_id}_{feishu_record_id}")，
    使用 UPSERT (insert ... on_conflict='note_id') 重跑安全。
    指标会重新写一份 metric_snapshot（window_label='ad_hoc'），
    UNIQUE(note_id, window_label, source='feishu_import') 防重复。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Iterator

import requests
from supabase import Client

from _common import (
    ensure_account_exists,
    ensure_project_exists,
    extract_tier,
    get_supabase_client,
    load_mapping,
    make_note_id,
    map_intent,
    parse_array,
    parse_numeric,
    parse_feishu_date,
    quarantine_record,
    setup_logger,
    update_project_date_range,
    _iso_now,
)


logger = setup_logger("sync_feishu_notes")


# ═════════════════════════════════════════════════════════════════════════
# Feishu Bitable client
# ═════════════════════════════════════════════════════════════════════════

class FeishuClient:
    """Minimal Feishu Bitable read-only client.

    Caches tenant_access_token until it expires.  Not thread-safe, single
    process only.  For higher throughput see Feishu Open API rate limits
    (default 50 QPS per app for Bitable read).
    """

    AUTH_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    BITABLE_RECORDS_URL = (
        "https://open.feishu.cn/open-apis/bitable/v1/apps/"
        "{app_token}/tables/{table_id}/records"
    )

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self._token: str | None = None
        self._token_expires_at: float = 0

    def _ensure_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        r = requests.post(
            self.AUTH_URL,
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Feishu auth failed: {data}")
        self._token = data["tenant_access_token"]
        self._token_expires_at = time.time() + data.get("expire", 7200)
        return self._token

    def _get_with_retry(
        self,
        url: str,
        headers: dict,
        params: dict,
        *,
        max_attempts: int = 3,
    ) -> "requests.Response":
        """GET with bounded retries on transient errors.

        Retry policy:
          - 401 → refresh token, retry once (existing behavior)
          - 5xx, Timeout, ConnectionError → exponential backoff 1/2/4s, max 3 tries
          - Other 4xx (404 / 422 / etc) → return immediately, caller raises
        """
        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                r = requests.get(url, headers=headers, params=params, timeout=30)
                if r.status_code == 401 and attempt == 0:
                    # token expired mid-pagination; refresh and retry once
                    self._token = None
                    new_token = self._ensure_token()
                    headers = dict(headers)
                    headers["Authorization"] = f"Bearer {new_token}"
                    continue
                if 500 <= r.status_code < 600:
                    if attempt == max_attempts - 1:
                        return r  # let caller raise via raise_for_status
                    wait = 2 ** attempt
                    time.sleep(wait)
                    continue
                return r
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_exc = exc
                if attempt == max_attempts - 1:
                    raise
                wait = 2 ** attempt
                time.sleep(wait)
        # Unreachable: above loop either returns or raises
        if last_exc:
            raise last_exc
        raise RuntimeError("_get_with_retry exhausted retries without raising")

    def list_records(
        self,
        app_token: str,
        table_id: str,
        view_id: str | None = None,
        page_size: int = 100,
    ) -> Iterator[dict[str, Any]]:
        """Yield records from a Feishu Bitable, paginating through all pages.

        Each yielded dict has at least:
            record_id: str         (飞书自动 ID, used as feishu_record_id)
            fields: dict           (列名 → 单元格值; 飞书 API 原生格式)

        2026-05-22 audit P1: GET 在 5xx / 网络异常时, 老代码直接 raise_for_status,
        飞书侧瞬时抖动会中断整个 sync. 加 _get_with_retry: 401 刷 token (一次),
        5xx / Timeout / ConnectionError 指数退避 (1/2/4s), 最多 3 次.
        硬性 4xx (404 / 422) 仍 fail-fast 因为重试也是同样错.
        """
        token = self._ensure_token()
        url = self.BITABLE_RECORDS_URL.format(app_token=app_token, table_id=table_id)
        headers = {"Authorization": f"Bearer {token}"}
        params: dict[str, Any] = {"page_size": page_size}
        if view_id:
            params["view_id"] = view_id

        while True:
            r = self._get_with_retry(url, headers, params)
            r.raise_for_status()
            data = r.json()
            if data.get("code") != 0:
                raise RuntimeError(f"Feishu list_records error: {data}")

            for item in data["data"].get("items", []):
                yield item

            if not data["data"].get("has_more"):
                break
            params["page_token"] = data["data"]["page_token"]
            # gentle rate limit
            time.sleep(0.1)


# ═════════════════════════════════════════════════════════════════════════
# Mapping-driven row transformation
# ═════════════════════════════════════════════════════════════════════════

def transform_row(
    mapping: dict,
    feishu_record_id: str,
    raw_fields: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Transform a Feishu row into:
        - note_dict: row ready for truth_vault.notes UPSERT
        - metric_dict: row ready for truth_vault.metric_snapshots INSERT (or None)
        - undeclared_fields: column names not in field_mapping AND not in
          project_specific_fields_to_raw_extra; trigger quarantine if non-empty.
    """
    field_mapping = mapping["field_mapping"]
    fields_to_raw_extra = set(mapping.get("project_specific_fields_to_raw_extra", []))
    declared = set(field_mapping.keys()) | fields_to_raw_extra

    # Allow control fields that are always present in Feishu API responses
    # but not user-defined columns
    ignored_meta_keys = {"_record_id", "_created_time", "_last_modified_time"}

    undeclared: list[str] = [
        col for col in raw_fields.keys()
        if col not in declared and col not in ignored_meta_keys
    ]

    note: dict[str, Any] = {
        "note_id": make_note_id(mapping["project_id"], feishu_record_id),
        "project_id": mapping["project_id"],
        "platform": mapping.get("platform", "xiaohongshu"),
        "feishu_record_id": feishu_record_id,
        # ingested_at intentionally NOT set here. The schema sets
        # DEFAULT NOW() on insert, and a BEFORE UPDATE trigger
        # (preserve_ingested_at) reverts it on every UPSERT-as-update.
        # Setting it client-side would let the trigger silently overwrite
        # what we send, which is wasteful and confusing.
    }
    intermediates: dict[str, Any] = {}
    raw_extra: dict[str, Any] = {}

    for feishu_col, schema_target in field_mapping.items():
        if feishu_col not in raw_fields:
            continue
        value = raw_fields[feishu_col]
        if schema_target.startswith("_"):
            intermediates[schema_target] = value
        else:
            note[schema_target] = _coerce_value(schema_target, value)

    # Project-specific allowlist → raw_extra
    for feishu_col in fields_to_raw_extra:
        if feishu_col in raw_fields:
            raw_extra[feishu_col] = raw_fields[feishu_col]
    if raw_extra:
        note["raw_extra"] = raw_extra

    # ── Secondary processing per mapping ──
    consumed_intermediates: set[str] = set()

    # tier_extraction: A/B families map 「状态」→ _status_raw; C family (TGV/QSHG)
    # maps 「备注」→ _note_for_tier. Pick the intermediate based on the yaml's
    # `tier_extraction.source` ("状态字段" or "备注字段"). Bug fix: previously
    # only _status_raw was checked, which silently dropped tier for C-family
    # projects (TGV_1's 47 「新爆」 records would end up tier=NULL).
    tier_extraction = mapping.get("tier_extraction") or {}
    tier_source = tier_extraction.get("source", "状态字段")
    tier_intermediate_key = (
        "_note_for_tier" if tier_source == "备注字段" else "_status_raw"
    )
    if tier_intermediate_key in intermediates and tier_extraction.get("rules"):
        note["tier"] = extract_tier(
            intermediates[tier_intermediate_key],
            tier_extraction["rules"],
        )
        # Track tier_source so downstream views can distinguish 状态字段 vs 备注字段
        # vs 数值推断 (the latter still TODO — see numeric fallback).
        note["tier_source"] = tier_source
        consumed_intermediates.add(tier_intermediate_key)
    if "_intent_raw" in intermediates and "intent_mapping" in mapping:
        note["intent"] = map_intent(
            intermediates["_intent_raw"],
            mapping["intent_mapping"],
        )
        consumed_intermediates.add("_intent_raw")
    if "_direction_raw" in intermediates:
        raw_dir = intermediates["_direction_raw"]
        # Always keep the raw value in raw_extra for traceability/annotation
        note.setdefault("raw_extra", {})["_direction_raw"] = raw_dir
        consumed_intermediates.add("_direction_raw")

        # Apply the deterministic portion of direction_decomposition. For
        # single-direction configs (no sub_directions), we can lift
        # content_format / target_audience / user_pain_point / product_focus
        # and intent_override straight from the yaml — no LLM needed. Configs
        # with sub_directions (NUC_phase1's nutritional / surgery branches)
        # still require LLM sub-classification and are skipped here; the
        # raw direction stays in raw_extra so an annotation pass can resolve
        # it. excluded_directions is honored as 'quarantine via tier_source'.
        decomposition = (mapping.get("direction_decomposition") or {}).get(raw_dir)
        if decomposition is not None and "sub_directions" not in decomposition:
            for col in ("content_format", "target_audience",
                        "user_pain_point", "product_focus"):
                val = decomposition.get(col)
                if val is not None and col not in note:
                    note[col] = val
            if decomposition.get("intent_override") is not None:
                note["intent"] = decomposition["intent_override"]

        # Honor excluded_directions (NRT_phase3's "女性自发, 男性自发" anomaly):
        # mark as data-anomalous so downstream training queries filter it out
        # without losing the row.
        for excluded in (mapping.get("excluded_directions") or []):
            if excluded.get("direction") == raw_dir:
                note["tier"] = "数据异常"
                note["tier_source"] = "数据异常"
                break

    # ── Numeric tier fallback (Gap 1) ──
    # When no text-based rule fired (tier is None) OR the status mapped to
    # the placeholder "未知" (e.g. NUC's "评估中" → "未知"), assign a tier by
    # threshold if interactions data already shows a clear hit. Without the
    # "未知" check, an operator-pending row whose data already qualifies for
    # 爆/大爆 would stay 未知 forever and never reach the flywheel downstream.
    # tier_source is overwritten to '数值推断' only when we actually promote.
    existing_tier = note.get("tier")
    if existing_tier in (None, "未知") and note.get("interactions") is not None:
        thresholds = mapping.get("tier_thresholds") or {}
        n_interactions = note["interactions"]
        if "大爆" in thresholds and n_interactions >= thresholds["大爆"]:
            note["tier"] = "大爆"
            note["tier_source"] = "数值推断"
        elif "爆" in thresholds and n_interactions >= thresholds["爆"]:
            note["tier"] = "爆"
            note["tier_source"] = "数值推断"

    # Any intermediate that wasn't consumed above (e.g. _account_name,
    # _account_followers, _comment_text, _comment_text_persona) goes to
    # raw_extra so it doesn't get silently dropped.  Future code can
    # process them out of intermediates and write to dedicated tables
    # (e.g. accounts / account_snapshots / comments).
    leftover = {k: v for k, v in intermediates.items() if k not in consumed_intermediates}
    if leftover:
        note.setdefault("raw_extra", {}).update(leftover)

    # ── metric_snapshot from impressions/reads/interactions ──
    # Two-tier split: NOTES_AND_METRIC cols are valid on truth_vault.notes AND
    # also fan out to metric_snapshots. METRIC_ONLY cols (likes/saves/shares/
    # comments_count/search_rank/keyword_rank) don't exist on truth_vault.notes
    # — if they ever sneak into the note payload (because a mapping yaml
    # eventually targets them directly), the notes UPSERT would fail with
    # "column does not exist". Strip them out of `note` before returning so
    # the structural boundary is enforced at the transformer, not by hope.
    metric: dict[str, Any] = {}
    notes_and_metric_cols = ("impressions", "reads", "interactions", "hit_blue_keywords")
    metric_only_cols = ("likes", "saves", "shares", "comments_count",
                        "search_rank", "keyword_rank")
    all_metric_cols = notes_and_metric_cols + metric_only_cols
    if any(c in note for c in all_metric_cols):
        # Compute hours_since_publish + best-fit window_label from publish_time
        # if it's available. Doing this here means even runs that only stamp
        # 'ad_hoc' get a usable bucket label for time-series aggregation later
        # (e.g. group by COALESCE(window_label,'ad_hoc') for a histogram-style
        # view of "interactions at +24h vs +7d"). Note: this is best-effort —
        # the canonical time-series flow requires multiple sync passes per
        # note at the actual windows, which the operator doesn't yet do.
        # 详见 CURRENT_STATE.md 延后清单 § metric_snapshots 时序回收.
        publish_time = note.get("publish_time")
        hours_since_publish, window_label = _derive_metric_window(publish_time)
        metric = {
            "note_id": note["note_id"],
            "collected_at": _iso_now(),
            "window_label": window_label,    # heuristic from hours_since_publish or 'ad_hoc'
            "source": "feishu_import",
            **{c: note[c] for c in all_metric_cols if c in note},
        }
        if hours_since_publish is not None:
            metric["hours_since_publish"] = hours_since_publish
    for c in metric_only_cols:
        note.pop(c, None)

    return note, metric, undeclared


# Mapping of (lower, upper) hours-since-publish bounds → canonical
# window_label per schemas/notes_v1_2.sql CHECK constraint. Bounds are
# inclusive at the lower edge, exclusive at the upper. Any value outside
# all bounds falls back to 'ad_hoc'.
_WINDOW_BOUNDS = (
    (0,    3,   "2h"),       # 0-3h → 2h window
    (3,    36,  "24h"),      # 3-36h → 24h window
    (36,   120, "72h"),      # 36-120h → 72h window
    (120,  240, "7d"),       # 120-240h ≈ 5-10d → 7d window
    (240,  504, "14d"),      # 240-504h ≈ 10-21d → 14d window
    (504,  1080,"30d"),      # 504-1080h ≈ 21-45d → 30d window
    (1080, 365*24, "final"), # 45d-1y → final
)


def _derive_metric_window(publish_time_iso: str | None) -> tuple[int | None, str]:
    """Return (hours_since_publish, window_label) for a metric snapshot.

    publish_time is a naive UTC ISO string (per project convention). When
    it's missing or unparseable, returns (None, 'ad_hoc') — the historical
    backward-compatible behavior. Bucketing is purely heuristic; see
    _WINDOW_BOUNDS for the cutoffs.
    """
    if not publish_time_iso:
        return None, "ad_hoc"
    try:
        from datetime import datetime as _dt
        pt = _dt.fromisoformat(str(publish_time_iso).replace("Z", "+00:00"))
        if pt.tzinfo is not None:
            pt = pt.replace(tzinfo=None)
        delta = _dt.utcnow() - pt
    except (ValueError, TypeError):
        return None, "ad_hoc"
    hrs = int(delta.total_seconds() // 3600)
    if hrs < 0:
        # Future publish_time — operator typo or pre-scheduled note. Don't
        # claim a window, just record the (impossible) hour count so it's
        # visible in queries.
        return hrs, "ad_hoc"
    for lo, hi, label in _WINDOW_BOUNDS:
        if lo <= hrs < hi:
            return hrs, label
    return hrs, "ad_hoc"


_NUMERIC_COLS = {
    "impressions", "reads", "interactions",
    "likes", "saves", "shares", "comments_count",
    "search_rank", "keyword_rank",
}

# Columns whose schema type is TEXT[] — must be parsed as arrays even if
# Feishu returned a comma-separated string (some Bitable columns are plain
# text, not multi-select).  parse_array() handles both shapes uniformly.
# This set should mirror every TEXT[] column in truth_vault.notes so we
# don't ship a string into a TEXT[] column even if a project's mapping
# yaml maps directly there (audit round 5 issue #2).
_ARRAY_COLS = {
    "hit_blue_keywords", "target_blue_keywords",
    "hashtags", "tags",
    "target_audience",
    "human_truth_archetype",
    "trend_dependencies",
}


def _coerce_value(target_col: str, value: Any) -> Any:
    """Cast Feishu cell values to types friendly to Postgres.

    Feishu returns:
      - Text/Number cells: str/int/float/None
      - Multi-select / link cells: list of dicts with 'text' key
      - Date cells: int (milliseconds since epoch)
    We collapse the obvious cases.  Extend per project as needed.

    For numeric columns we apply parse_numeric (handles Chinese commas,
    full-width digits, '/' / '-' / '无' sentinel tokens).  For array
    columns we apply parse_array (handles both list[dict{text}] and
    delimiter-separated text strings).  For publish_time we apply
    parse_feishu_date (accepts ms epoch or ISO string).
    """
    if value is None:
        return None

    # Numeric columns — parse robustly, may return None for sentinel values
    if target_col in _NUMERIC_COLS:
        n = parse_numeric(value)
        if n is None:
            return None
        # If the column is INT-shaped, cast.  Postgres will round/error
        # on non-integer values anyway; cast here for clarity.
        return int(n) if n == int(n) else n

    # Array columns — must be list[str] for TEXT[] target.
    # Handle both list[dict{text:...}] AND "a, b, c" / "a\nb\nc" strings
    # (some Bitable columns are plain text, not multi-select).
    if target_col in _ARRAY_COLS:
        return parse_array(value)

    # Date column — handle 飞书 ms epoch
    if target_col == "publish_time":
        return parse_feishu_date(value)

    # Multi-select / link / attachment cells: list of dicts with 'text'
    # (for non-array target columns we collapse to a comma-separated string)
    if isinstance(value, list):
        if all(isinstance(x, dict) and "text" in x for x in value):
            return ", ".join(x["text"] for x in value)
        return value

    # Single-select / user cell: dict with 'text'
    if isinstance(value, dict) and "text" in value:
        return value["text"]

    return value


# ═════════════════════════════════════════════════════════════════════════
# Upsert into truth_vault
# ═════════════════════════════════════════════════════════════════════════

def upsert_note(client: Client, note: dict[str, Any], dry_run: bool = False) -> None:
    if dry_run:
        logger.info("[dry-run] would upsert note_id=%s", note["note_id"])
        return
    (
        client.schema("truth_vault")
        .table("notes")
        .upsert(note, on_conflict="note_id")
        .execute()
    )


def upsert_metric(client: Client, metric: dict[str, Any], dry_run: bool = False) -> None:
    if not metric:
        return
    if dry_run:
        logger.info(
            "[dry-run] would upsert metric_snapshot note_id=%s window=%s",
            metric["note_id"], metric["window_label"],
        )
        return
    # UNIQUE(note_id, window_label, source) lets us upsert on the composite key
    (
        client.schema("truth_vault")
        .table("metric_snapshots")
        .upsert(metric, on_conflict="note_id,window_label,source")
        .execute()
    )


# ═════════════════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════════════════

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project_id", help="e.g. NUC_phase1")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print actions without writing to Supabase")
    parser.add_argument("--limit", type=int, default=0,
                        help="Stop after N records (debug)")
    args = parser.parse_args()

    mapping = load_mapping(args.project_id)
    sync_config = mapping.get("sync_config") or {}

    # source_type discriminator: this script only handles feishu_api.
    # manual_xlsx ingest is not in scope — would require a different
    # ingest path (read .xlsx → coerce → upsert).  Fail fast and loud
    # so the operator doesn't run this script against a manual project.
    source_type = sync_config.get("source_type", "feishu_api")
    if source_type != "feishu_api":
        logger.error(
            "Mapping yaml has sync_config.source_type=%r. This script only "
            "handles 'feishu_api'.  For 'manual_xlsx' projects you need a "
            "separate ingest path (not included in this package).",
            source_type,
        )
        return 2

    app_token = sync_config.get("feishu_app_token") or os.environ.get("FEISHU_APP_TOKEN")
    table_id  = sync_config.get("feishu_table_id")  or os.environ.get("FEISHU_TABLE_ID")
    view_id   = sync_config.get("feishu_view_id")
    if not app_token or not table_id:
        logger.error(
            "Missing feishu_app_token / feishu_table_id. Set them in "
            "mapping yaml's sync_config block, or pass FEISHU_APP_TOKEN / "
            "FEISHU_TABLE_ID env vars."
        )
        return 2

    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        logger.error("FEISHU_APP_ID and FEISHU_APP_SECRET env vars must be set.")
        return 2

    fs = FeishuClient(app_id, app_secret)
    sb = get_supabase_client()

    # Make sure truth_vault.projects has the row before any notes go in —
    # `notes.project_id` has a FK to it and would reject every insert
    # without this (audit issue 2 from session #8 round 4).
    if not args.dry_run:
        ensure_project_exists(sb, mapping)

    stats = {"total": 0, "upserted": 0, "quarantined": 0, "errors": 0}
    for item in fs.list_records(app_token, table_id, view_id):
        if args.limit and stats["total"] >= args.limit:
            break
        stats["total"] += 1
        feishu_record_id = item.get("record_id", "")
        raw_fields = item.get("fields", {})
        try:
            note, metric, undeclared = transform_row(mapping, feishu_record_id, raw_fields)
            if undeclared:
                logger.warning(
                    "record_id=%s has undeclared fields: %s → quarantine",
                    feishu_record_id, undeclared,
                )
                if not args.dry_run:
                    quarantine_record(
                        sb, mapping["project_id"], feishu_record_id,
                        raw_fields, undeclared, reason="undeclared_fields",
                    )
                stats["quarantined"] += 1
                continue  # Don't upsert; require human review first

            # Required-field check: truth_vault.notes has NOT NULL constraints
            # on raw_content (the actual note text), and INSERT would crash
            # mid-batch if a row from Feishu is blank or malformed.  Quarantine
            # instead so the operator sees the problematic row alongside the
            # undeclared-fields cases, rather than the whole sync failing.
            REQUIRED_NOTE_FIELDS = ("raw_content",)
            missing = [c for c in REQUIRED_NOTE_FIELDS if not note.get(c)]
            if missing:
                logger.warning(
                    "record_id=%s missing required fields: %s → quarantine",
                    feishu_record_id, missing,
                )
                if not args.dry_run:
                    quarantine_record(
                        sb, mapping["project_id"], feishu_record_id,
                        raw_fields, missing,
                        reason=f"missing_required:{','.join(missing)}",
                    )
                stats["quarantined"] += 1
                continue

            # Ensure the account row exists before inserting the note —
            # notes.account_id has a FK to accounts.account_id; without
            # this upsert, the insert below would fail with FK violation
            # for any new 素人编号 (audit issue 2).
            if not args.dry_run:
                ensure_account_exists(
                    sb,
                    note.get("account_id"),
                    platform=note.get("platform", "xiaohongshu"),
                )
            upsert_note(sb, note, dry_run=args.dry_run)
            upsert_metric(sb, metric, dry_run=args.dry_run)
            stats["upserted"] += 1
        except Exception as exc:
            logger.exception("record_id=%s failed: %s", feishu_record_id, exc)
            stats["errors"] += 1

    # Roll up project-level date range from the freshly synced notes. The yaml
    # placeholders (auto_from_publish_time_min/max) aren't DATE-castable, so
    # this is the only path that keeps projects.start_date/end_date honest.
    if not args.dry_run:
        try:
            update_project_date_range(sb, mapping["project_id"])
        except Exception as exc:
            logger.warning("update_project_date_range failed for %s: %s",
                           mapping["project_id"], exc)

    logger.info("Done: %s", json.dumps(stats, ensure_ascii=False))
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
