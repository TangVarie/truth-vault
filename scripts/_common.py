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

import base64
import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml
from supabase import create_client, Client
from supabase.client import ClientOptions


# ─────────────────────────────────────────────────────────────────────────
# Client creation
# ─────────────────────────────────────────────────────────────────────────

def _jwt_role_or_none(token: str) -> Optional[str]:
    """Decode the role claim from a Supabase JWT without verifying signature.

    Supabase issues HS256 JWTs whose payload contains `{"role": "anon"}` or
    `{"role": "service_role"}` (plus iss/iat/exp). We only need to read the
    role to refuse anon keys — signature verification belongs on the server
    side, not in a CLI sync script. base64url decode of payload is enough.
    Returns None if anything about the token doesn't look like a JWT.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload_b64 = parts[1]
    padding = "=" * (-len(payload_b64) % 4)
    try:
        payload_bytes = base64.urlsafe_b64decode(payload_b64 + padding)
        payload = json.loads(payload_bytes)
    except (ValueError, json.JSONDecodeError):
        return None
    role = payload.get("role")
    return role if isinstance(role, str) else None


# Supabase 2024+ "API keys" format. The role is encoded in the prefix:
#   sb_secret_*      → server-only, equivalent to legacy service_role JWT
#   sb_publishable_* → client-safe, equivalent to legacy anon JWT
# These are NOT JWTs (no dots, opaque payload), so _jwt_role_or_none returns
# None for them. We have to recognize the prefix to validate role.
_SB_SECRET_PREFIX = "sb_secret_"
_SB_PUBLISHABLE_PREFIX = "sb_publishable_"


def get_supabase_client() -> Client:
    """Return a Supabase client using SERVICE_ROLE_KEY (RLS bypass).

    Sync scripts MUST use service_role; they perform system-level operations
    that write to multiple users' rows. See docs/09-system-integration.md
    "TV sync 脚本必须用 SERVICE ROLE KEY" for the security rationale.

    Accepts both key formats:
      - Legacy: long HS256 JWT (role=service_role in payload)
      - New (2024+): opaque token prefixed with `sb_secret_`

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

    # 1. New-format API key — the role is in the prefix. Bail early before
    #    trying JWT decode (these are opaque, not JWTs).
    if key.startswith(_SB_PUBLISHABLE_PREFIX):
        raise RuntimeError(
            "SUPABASE_SERVICE_ROLE_KEY starts with 'sb_publishable_' — that's "
            "a publishable (anon-equivalent) key. Sync scripts need a secret "
            "key (starts with 'sb_secret_'). Check Supabase Dashboard → "
            "Settings → API."
        )
    if key.startswith(_SB_SECRET_PREFIX):
        return create_client(url, key, ClientOptions(schema=None))

    # 2. Legacy JWT format — decode payload and check the role claim.
    role = _jwt_role_or_none(key)
    if role is not None:
        if role != "service_role":
            raise RuntimeError(
                f"SUPABASE_SERVICE_ROLE_KEY has role={role!r}, expected 'service_role'. "
                "Sync scripts need service_role to bypass RLS. Check Supabase "
                "Dashboard → Settings → API → service_role secret."
            )
        return create_client(url, key, ClientOptions(schema=None))

    # 3. Neither prefix matched, and not a JWT — last-resort guardrail
    #    against pasting an obviously wrong value (empty / "your-key-here" /
    #    accidentally pasted publishable). We're deliberately permissive
    #    here because Supabase may introduce more formats in the future;
    #    only the most obvious mistakes get rejected.
    if "anon" in key.lower() or len(key) < 20:
        raise RuntimeError(
            "SUPABASE_SERVICE_ROLE_KEY doesn't look like a known Supabase key "
            "format (not a JWT, not sb_secret_*, and is suspiciously short or "
            "contains 'anon'). Check Supabase Dashboard → Settings → API."
        )
    return create_client(url, key, ClientOptions(schema=None))  # no default schema


# ─────────────────────────────────────────────────────────────────────────
# Mapping yaml
# ─────────────────────────────────────────────────────────────────────────

_MAPPINGS_DIR = Path(__file__).resolve().parent.parent / "mappings"


_ALLOWED_TIER_SOURCES = {"状态字段", "备注字段"}


def load_mapping(project_id: str) -> dict:
    """Load `mappings/<project_id>.yaml`. Validates required keys exist
    and that any closed-set fields (e.g. tier_extraction.source) have
    legal values.
    """
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
    # tier_extraction.source picks which intermediate (_status_raw vs
    # _note_for_tier) the rule engine reads. A typo in the yaml ("souce",
    # "状态") used to silently fall back to "状态字段" via .get(default),
    # which means C-family projects (TGV/QSHG that map 备注→_note_for_tier)
    # would silently drop their tier. Reject unknown values here instead.
    tier_extraction = m.get("tier_extraction") or {}
    if "source" in tier_extraction:
        src = tier_extraction["source"]
        if src not in _ALLOWED_TIER_SOURCES:
            raise ValueError(
                f"{path}: tier_extraction.source={src!r} not in "
                f"{sorted(_ALLOWED_TIER_SOURCES)}. Check for typos."
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


def parse_audience_analysis(value: Any) -> Optional[dict]:
    """Parse 半结构化「观众分析」文本 → structured dict for notes.actual_audience_data.

    WTG ROC素人分发表 的「观众分析」列格式 (；分段, ：分键值):
      "性别分布：男性4%，女性96%；年龄分布：<18占2%，18-24占5%，25-34占45%；
       城市分布：上海11%，北京5%；阅读时长：14.7秒"
    空段 ("性别分布：" 或 "性别分布：无") 跳过. 返回只含有数据的键 + _raw 原文;
    全空 / None / 非字符串 → None (不写 actual_audience_data).

    输出形状 (供 actual_audience_data JSONB):
      {"gender": {"男性": 4.0, "女性": 96.0},
       "age": {"<18": 2.0, ...}, "city": {"上海": 11.0, ...},
       "read_duration_sec": 14.7, "_raw": "原文"}

    这是确定性解析 (不用 LLM). 飞书「观众分析」格式若变, 改这里的分段/键判断.
    """
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None

    def _parse_pairs(s: str) -> dict:
        # "男性4%，女性96%" / "<18占2%，18-24占5%" → {name: pct_float}
        out: dict[str, float] = {}
        for part in re.split(r"[，,]", s):
            part = part.strip()
            if not part or part in ("无", "-"):
                continue
            m = re.match(r"^(.+?)占?(\d+(?:\.\d+)?)\s*%?$", part)
            if m:
                try:
                    out[m.group(1).strip()] = float(m.group(2))
                except ValueError:
                    pass
        return out

    result: dict[str, Any] = {}
    for sec in re.split(r"[；;]", text):
        parts = re.split(r"[：:]", sec.strip(), maxsplit=1)
        if len(parts) != 2:
            continue
        key, val = parts[0].strip(), parts[1].strip()
        if not val or val == "无":
            continue
        if key.startswith("性别"):
            d = _parse_pairs(val)
            if d:
                result["gender"] = d
        elif key.startswith("年龄"):
            d = _parse_pairs(val)
            if d:
                result["age"] = d
        elif key.startswith("城市"):
            d = _parse_pairs(val)
            if d:
                result["city"] = d
        elif key.startswith("阅读时长"):
            mnum = re.search(r"(\d+(?:\.\d+)?)", val)
            if mnum:
                result["read_duration_sec"] = float(mnum.group(1))
    if not result:
        return None
    result["_raw"] = text[:500]
    return result


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

    Idempotent on (project_id, feishu_record_id, reason) — repeated runs of
    sync_feishu on a row that still has undeclared fields don't pile up rows
    in the quarantine table. The schema's UNIQUE constraint (added in
    notes_v1_2.sql) backs this, and ignore_duplicates=True preserves any
    reviewer state (status/review_decision/reviewed_by) that an operator
    has already set on the first-seen quarantine row.
    """
    (
        client.schema("truth_vault")
        .table("undeclared_fields_quarantine")
        .upsert(
            {
                "project_id": project_id,
                "feishu_record_id": feishu_record_id,
                "raw_row": raw_row,
                "undeclared_field_names": undeclared_fields,
                "reason": reason,
                "status": "pending",
                "quarantined_at": _iso_now(),
            },
            on_conflict="project_id,feishu_record_id,reason",
            ignore_duplicates=True,
        )
        .execute()
    )


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

    Update semantics (split mapping-owned vs manually-curated):
      • mapping-owned fields (brand / product / category / platform /
        schema_family / tier_thresholds / mapping_config) ARE updated on
        re-sync. The yaml is the source of truth — if NRT_phase2's category
        flips from 处方药 to OTC药 (vocab v1 §9), the DB row should reflect
        that on the next sync.
      • cross-system mapping columns (mapping_to_autowriter_project_id /
        mapping_to_sanshengliubu_project_id) are manually maintained post-
        onboarding and MUST NOT be overwritten. We achieve this by simply
        not including them in `row` — Supabase upsert only touches columns
        sent in the payload, so absent keys preserve whatever's in the DB.
      • derived stats (total_notes / notes_with_data / etc) are likewise
        never sent here.
      • start_date / end_date are computed from notes.publish_time via
        update_project_date_range() called at the end of sync, not from
        the yaml (the yaml has placeholder strings like
        'auto_from_publish_time_min' that aren't DATE-castable).
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

    # ignore_duplicates omitted → default UPDATE-on-conflict. Updates every
    # column present in `row`; columns absent from `row` (the cross-system
    # mapping cols, derived stats, start/end dates, created_at) are preserved.
    (
        client.schema("truth_vault")
        .table("projects")
        .upsert(row, on_conflict="project_id")
        .execute()
    )


def update_project_date_range(client: Client, project_id: str) -> None:
    """Compute and write projects.start_date / end_date from notes.publish_time.

    The mapping yaml carries `start_date: auto_from_publish_time_min` placeholders
    that aren't database-castable, so ensure_project_exists() can't fill them.
    Run this at the END of sync (after all notes are upserted) to keep the
    project-level date range honest.

    No-op if the project has no notes with publish_time set yet.

    2026-05-22 audit P1: 老版本是两次独立 SELECT + 一次 UPDATE 三步, 中间没
    事务保护. 同一时刻另一个 sync_feishu 写入新 note, 可能让 start_date >
    end_date (查 earliest 时数据是 A, 查 latest 时数据更新成 B). 改成单条
    AGGREGATE: client 端 fetch 完所有 publish_time 再算 min/max, 一次 UPDATE.
    PostgREST 不支持 SELECT MIN/MAX 子查询 + UPDATE 的原子写, 但 client 端
    one-shot 算完已经把 race window 关掉了 (要 race, 得在 fetch 那一瞬间
    insert; 而 insert 走 upsert + 不动 start/end_date 列, 不会产生 start>end).
    """
    # 一次 fetch 拿到所有 publish_time. 行数大时 fetch_all_pages 自动分页.
    rows = fetch_all_pages(
        client.schema("truth_vault").table("notes")
        .select("publish_time")
        .eq("project_id", project_id)
        .not_.is_("publish_time", None)
    )
    if not rows:
        return
    times = [str(r["publish_time"])[:10] for r in rows if r.get("publish_time")]
    if not times:
        return
    update = {
        "start_date": min(times),
        "end_date":   max(times),
    }
    (
        client.schema("truth_vault")
        .table("projects")
        .update(update)
        .eq("project_id", project_id)
        .execute()
    )


# ─────────────────────────────────────────────────────────────────────────
# Secret masking (2026-05-22 audit P3)
# ─────────────────────────────────────────────────────────────────────────

import re as _re

# 已知 secret 前缀正则. 加新格式时往这里加, 让 mask_secrets 覆盖所有 logger.
_SECRET_PATTERNS = [
    _re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),       # Anthropic
    _re.compile(r"sb_secret_[A-Za-z0-9]{20,}"),       # Supabase 2024+
    _re.compile(r"sbp_[A-Za-z0-9]{20,}"),             # Supabase service token
    _re.compile(r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}"),  # JWT
    _re.compile(r"AIza[A-Za-z0-9_\-]{20,}"),          # Google API key
    _re.compile(r"sk-proj-[A-Za-z0-9_\-]{20,}"),      # OpenAI
    _re.compile(r"sk-[A-Za-z0-9]{40,}"),              # OpenAI 老格式
]


def mask_secrets(s: str) -> str:
    """Mask known secret patterns in a string before logging it.

    Logger formatters / exception handlers / telemetry events should pipe
    user-visible strings through this before writing. Conservative — won't
    catch every secret shape, but catches Anthropic / Supabase / Google /
    OpenAI / JWT default formats.

    For exception messages from supabase-py / requests that may include
    bearer tokens in URLs or stacktrace, pass `mask_secrets(str(exc))`.
    """
    if not isinstance(s, str) or not s:
        return s
    for pat in _SECRET_PATTERNS:
        s = pat.sub("***REDACTED***", s)
    return s


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
