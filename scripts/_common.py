"""
Shared utilities for Truth Vault sync scripts.

Centralises:
  - Supabase client creation (always service_role; cross-schema explicit)
  - Mapping yaml loading + validation
  - Tier extraction / intent mapping rule engines
  - Quarantine helper for undeclared fields
  - Logging setup
"""

from __future__ import annotations

import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml
from supabase import create_client, Client
from supabase.client import ClientOptions


# ─────────────────────────────────────────────────────────────────────────
# Client creation
# ─────────────────────────────────────────────────────────────────────────

def get_supabase_client() -> Client:
    """Return a Supabase client using SERVICE_ROLE_KEY (RLS bypass).

    Sync scripts MUST use service_role; they perform system-level operations
    that write to multiple users' rows. See docs/09-system-integration.md
    "TV sync 脚本必须用 SERVICE ROLE KEY" for the security rationale.

    The client has no default schema set — every call must explicitly use
    .schema('truth_vault') / .schema('autowriter') / .schema('public').
    This is intentional: forgetting .schema() should fail loudly with 404
    rather than silently writing to the wrong place.
    """
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY env vars must be set. "
            "See scripts/.env.example for the full list."
        )
    if "anon" in key.lower() or len(key) < 100:
        # service_role JWTs are long; anon keys are short and contain 'anon' in payload.
        # Heuristic, not bulletproof — Supabase doesn't expose role in key text directly,
        # but the length check catches the most common mistake (pasting anon).
        raise RuntimeError(
            "SUPABASE_SERVICE_ROLE_KEY looks like an anon key. Service role keys "
            "are ~200+ chars. Check Supabase Dashboard → Settings → API → "
            "service_role secret."
        )
    return create_client(url, key, ClientOptions(schema=None))  # no default schema


# ─────────────────────────────────────────────────────────────────────────
# Mapping yaml
# ─────────────────────────────────────────────────────────────────────────

_MAPPINGS_DIR = Path(__file__).resolve().parent.parent / "mappings"


def load_mapping(project_id: str) -> dict:
    """Load `mappings/<project_id>.yaml`. Validates required keys exist."""
    path = _MAPPINGS_DIR / f"{project_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Mapping yaml not found: {path}")
    with open(path, encoding="utf-8") as f:
        m = yaml.safe_load(f)
    required = {"project_id", "field_mapping"}
    missing = required - set(m.keys())
    if missing:
        raise ValueError(f"{path}: missing required keys: {missing}")
    if m["project_id"] != project_id:
        raise ValueError(
            f"{path}: project_id in yaml ({m['project_id']!r}) "
            f"does not match filename ({project_id!r})"
        )
    return m


# ─────────────────────────────────────────────────────────────────────────
# Tier / intent / direction rule engines
# ─────────────────────────────────────────────────────────────────────────

def extract_tier(raw_status: Optional[str], rules: list[dict]) -> Optional[str]:
    """Apply tier_extraction.rules from mapping yaml to a raw 状态 string."""
    if raw_status is None:
        return _default_tier(rules)
    text = str(raw_status)
    for rule in rules:
        if "match_contains" in rule:
            for needle in rule["match_contains"]:
                if needle in text:
                    return rule.get("tier")
    return _default_tier(rules)


def _default_tier(rules: list[dict]) -> Optional[str]:
    for r in rules:
        if "default" in r:
            return r["default"]
    return None


def map_intent(raw_intent: Optional[str], mapping: dict) -> Optional[str]:
    """Apply intent_mapping from mapping yaml. None passes through."""
    if raw_intent is None:
        return None
    return mapping.get(raw_intent, raw_intent)


# ─────────────────────────────────────────────────────────────────────────
# Note ID generator
# ─────────────────────────────────────────────────────────────────────────

def make_note_id(project_id: str, feishu_record_id: str) -> str:
    """truth_vault.notes.note_id rule (see docs/02-schema-v1.md):
        f"{project_id}_{feishu_record_id}"
    """
    return f"{project_id}_{feishu_record_id}"


# ─────────────────────────────────────────────────────────────────────────
# Value coercion · numeric + date
# ─────────────────────────────────────────────────────────────────────────
#
# 飞书 Bitable 单元格的实际值五花八门：
#   - 数值字段（曝光量 / 阅读量 / 互动量等）可能出现:
#       "/" "-" "" "无" "N/A" "暂无"  → 应转 None
#       "1,234"  "1，234"  "１２３"   → 千位分隔/全角，应转 1234/123
#       1234 1234.0                  → 直接接受
#   - 日期字段（publish_time）飞书 API 返回毫秒时间戳（int），需转 ISO
#
# 这两个清洗逻辑由 docs/03-mapping-protocol.md Step 4.5 规定。

_NUMERIC_NULL_TOKENS = {"", "/", "-", "—", "无", "暂无", "/无", "N/A", "n/a", "null", "NULL", "None"}


def parse_array(value: Any) -> Optional[list]:
    """Convert a Feishu cell value to a list[str] suitable for PG TEXT[].

    The complication: 飞书表的 "关键词 / 蓝词记录" 这类字段可能是
        - 多选 cell  → list[dict{text: ...}]   (preferred)
        - 单行文本  → str "营养液, 全营养, 控糖"
        - 多行文本  → str "营养液\\n全营养\\n控糖"
        - 数组       → list[str]   (some Bitable variants)
        - 空 / "无" / "/"  → None

    We accept all of the above and emit list[str]. Returning None lets the
    caller leave the column unset; returning [] is a valid empty array if
    that's what makes sense for the column.

    Splitters: , 、 / ， \\n  (Chinese & English comma, ideographic comma,
    slash, newline).  All trimmed; empties dropped.
    """
    if value is None:
        return None
    if isinstance(value, list):
        if not value:
            return []
        if all(isinstance(x, dict) and "text" in x for x in value):
            return [str(x["text"]).strip() for x in value if x.get("text")]
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str):
        s = value.strip()
        if not s or s in _NUMERIC_NULL_TOKENS:
            return None
        parts = re.split(r"[,，、/\n]+", s)
        return [p.strip() for p in parts if p.strip()]
    # int/float/bool/dict: stringify
    return [str(value)]


def parse_numeric(value: Any) -> Optional[float]:
    """Robustly convert a Feishu cell value to a number, or None if it's
    one of the conventional 'no data' tokens.

    Accepts:
        - int / float                  → unchanged
        - str "1,234"  "1，234"          → 1234.0 (Chinese/English thousands)
        - str "１２３"                    → 123.0 (full-width digits)
        - str "/" "-" "" "无" "N/A" ... → None
        - None                          → None
        - list/dict (non-numeric)       → None

    Returns float because numeric Feishu cells can be decimal.  Cast to int
    at write time if the target column is INT.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s in _NUMERIC_NULL_TOKENS:
        return None
    # Normalize: drop thousands separators (both CN ， and EN ,) + convert
    # full-width digits to ASCII via str.translate.
    fullwidth = str.maketrans("０１２３４５６７８９．", "0123456789.")
    s2 = s.translate(fullwidth).replace(",", "").replace("，", "")
    try:
        return float(s2)
    except ValueError:
        return None


def parse_feishu_date(value: Any) -> Optional[str]:
    """Convert a Feishu Bitable date cell to a Postgres-friendly ISO string.

    Feishu returns dates as int milliseconds since epoch.  This function
    accepts that, plus strings that already look like ISO timestamps
    (passes them through unchanged after stripping).  Returns None for
    empty/invalid values rather than letting them crash the INSERT.
    """
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        if not s or s in _NUMERIC_NULL_TOKENS:
            return None
        return s  # caller's problem if format is bad; Postgres will reject
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Heuristic: > 10**12 means milliseconds (since 2001-09-09 in ms);
        # smaller means seconds (since 2286-11-20 in s, which is far future,
        # so treating it as seconds is reasonable as a backup).
        ts = float(value)
        if ts > 10**12:
            ts = ts / 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")
        except (OSError, OverflowError, ValueError):
            return None
    return None




def quarantine_record(
    client: Client,
    project_id: str,
    feishu_record_id: str,
    raw_row: dict[str, Any],
    undeclared_fields: list[str],
    reason: str = "undeclared_fields",
) -> None:
    """Write the entire raw row to truth_vault.undeclared_fields_quarantine
    instead of silently dropping new/unknown fields. See D-021.

    Column names match the schema in notes_v1_2.sql exactly —
    'undeclared_field_names' (not 'undeclared_fields'), and the optional
    'feishu_record_id' / 'reason' columns (added to schema for debug value).
    If you are running against a schema where those two columns are missing,
    re-run notes_v1_2.sql; it has idempotent ALTER TABLE IF NOT EXISTS lines
    that add them.
    """
    client.schema("truth_vault").table("undeclared_fields_quarantine").insert({
        "project_id": project_id,
        "feishu_record_id": feishu_record_id,
        "raw_row": raw_row,
        "undeclared_field_names": undeclared_fields,
        "reason": reason,
        "status": "pending",
        "quarantined_at": _iso_now(),
    }).execute()


def ensure_account_exists(
    client: Client,
    account_id: Optional[str],
    platform: str = "xiaohongshu",
    owner_type: str = "素人",
) -> None:
    """UPSERT a row into truth_vault.accounts so subsequent notes inserts
    don't get rejected by the FK constraint
    `notes.account_id REFERENCES accounts(account_id)`.

    Called by sync_feishu_notes_to_truth_vault.py before each note upsert.
    Idempotent (on_conflict=account_id). Skips silently if account_id is
    None or empty (the note will be inserted without account_id, which is
    allowed because the FK is nullable).

    Owner_type default '素人' matches the Truth Vault docs convention for
    飞书素人编号 — KOC/KOL/brand accounts come from different ingest paths.
    """
    if not account_id:
        return
    (
        client.schema("truth_vault")
        .table("accounts")
        .upsert(
            {
                "account_id": account_id,
                "platform": platform,
                "owner_type": owner_type,
                "first_seen_at": _iso_now(),
            },
            on_conflict="account_id",
            # Don't overwrite existing first_seen_at on conflict — Supabase
            # upsert with default behavior would; instead use ignore_duplicates
            # so we keep the original first_seen_at the first time we saw it.
            ignore_duplicates=True,
        )
        .execute()
    )


def ensure_project_exists(client: Client, mapping: dict) -> None:
    """UPSERT a row into truth_vault.projects from the mapping yaml.

    Called by sync_feishu_notes_to_truth_vault.py before any notes are
    inserted.  Without this, the very first sync on a fresh deployment
    would fail with FK violation
    (`notes.project_id REFERENCES projects(project_id)`).

    Strategy: we only fill the columns that the mapping yaml owns
    (project_id, brand, product, category, platform, schema_family,
    tier_thresholds, mapping_config snapshot).  Cross-system mapping
    columns (mapping_to_autowriter_project_id /
    mapping_to_sanshengliubu_project_id) are NOT touched here — they're
    maintained manually post-onboarding and must not be clobbered by a
    re-sync.  ignore_duplicates=True ensures repeat runs don't overwrite
    those fields once they're set.
    """
    project_id = mapping.get("project_id")
    if not project_id:
        raise ValueError("mapping yaml is missing required field: project_id")

    # Subset of the yaml that's safe to snapshot into projects.mapping_config JSONB
    # for traceability.  We strip out big or sensitive sections.
    mapping_snapshot = {
        k: v for k, v in mapping.items()
        if k in {
            "version", "schema_family", "intent_mapping",
            "tier_extraction", "tier_thresholds", "data_supplement_needed",
            "project_specific_fields_to_raw_extra",
        }
    }

    row = {
        "project_id":     project_id,
        "brand":          mapping.get("brand") or "(未填)",
        "product":        mapping.get("product") or "(未填)",
        "category":       mapping.get("category") or "其他",
        "platform":       mapping.get("platform", "xiaohongshu"),
        "schema_family":  mapping.get("schema_family"),
        "tier_thresholds": mapping.get("tier_thresholds") or None,
        "mapping_config": mapping_snapshot,
    }
    # Trim None values that would violate NOT NULL CHECKs (brand/product/category
    # are NOT NULL).  Defaults above cover that, so this is belt-and-suspenders.
    row = {k: v for k, v in row.items() if v is not None}

    (
        client.schema("truth_vault")
        .table("projects")
        .upsert(row, on_conflict="project_id", ignore_duplicates=True)
        .execute()
    )


# ─────────────────────────────────────────────────────────────────────────
# Pagination helper
# ─────────────────────────────────────────────────────────────────────────

# Supabase PostgREST default response cap. Configurable in Settings → API →
# Max Rows; production default is 1000 unless changed. If we want to avoid
# silently truncating large result sets, every "fetch all" path needs to
# loop until the page is short.
_DEFAULT_PAGE_SIZE = 1000


def fetch_all_pages(query_builder, page_size: int = _DEFAULT_PAGE_SIZE) -> list:
    """Drain a Supabase PostgREST query across all pages.

    Usage:
        rows = fetch_all_pages(
            sb.schema("truth_vault").table("notes")
              .select("note_id, ...")
              .in_("tier", ["爆", "大爆"])
        )

    The query_builder is a chained PostgREST builder *before* .execute().
    We attach .range(start, end) per page and assemble the full list.
    A short page (fewer rows than page_size) terminates the loop. If a
    page comes back exactly page_size, we keep going — the cost of one
    extra empty fetch is cheap and avoids missed rows at the boundary.
    """
    rows: list = []
    start = 0
    while True:
        end = start + page_size - 1
        res = query_builder.range(start, end).execute()
        page = res.data or []
        rows.extend(page)
        if len(page) < page_size:
            return rows
        start += page_size


# ─────────────────────────────────────────────────────────────────────────
# Time helpers
# ─────────────────────────────────────────────────────────────────────────

def _iso_now() -> str:
    """UTC ISO timestamp, suitable for PostgREST TIMESTAMP columns.

    The schema uses `TIMESTAMP WITHOUT TIME ZONE` (not TIMESTAMPTZ), so we
    emit a naive UTC string. If we included the `+00:00` suffix, Postgres
    would silently strip the timezone on insert and downstream readers
    would have no way to know the value is UTC. Naive UTC + a project
    convention ("all timestamps are UTC") is more predictable until/unless
    the schema migrates to TIMESTAMPTZ.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


# ─────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────

def setup_logger(name: str, level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s · %(message)s")
    )
    logger.addHandler(h)
    return logger
