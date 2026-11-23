#!/usr/bin/env python3
"""Cross-repo silent-stall detector (I-39 follow-up).

Detects projects where writers are actively delivering drafts in `autowriter`
within the last N days, yet `truth_vault.notes` has ingested zero new notes in
the same window (e.g., operations moved publishing to a new Feishu table while
daily-sync kept succeeding against the old table).

Read-only, counts and project codes only (no titles, draft text, URLs, or secrets).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional


@dataclass(frozen=True)
class StallFinding:
    project_code: str
    aw_batches_in_window: int
    tv_notes_in_window: int
    days_since_last_tv_note: Optional[int]
    last_aw_batch_date: str
    last_tv_note_date: Optional[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_code": self.project_code,
            "aw_batches_in_window": self.aw_batches_in_window,
            "tv_notes_in_window": self.tv_notes_in_window,
            "days_since_last_tv_note": self.days_since_last_tv_note,
            "last_aw_batch_date": self.last_aw_batch_date,
            "last_tv_note_date": self.last_tv_note_date,
        }


def parse_utc(value: Any) -> Optional[datetime]:
    """Parse ISO-8601 timestamp or datetime into timezone-aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    raw = str(value).strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def find_stalled_projects(
    aw_batches: Iterable[dict[str, Any]],
    tv_notes: Iterable[dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    window_days: int = 14,
    min_aw_batches: int = 1,
    ignore_projects: Iterable[str] = (),
) -> list[StallFinding]:
    """Return projects with recent autowriter batches but zero recent truth_vault notes.

    `aw_batches`: items with `project_code` (or `tv_project_id`) and `created_at`.
    `tv_notes`: items with `project_id` and `created_at` (optional `publish_time`).
    """
    ref_now = parse_utc(now) if now is not None else datetime.now(timezone.utc)
    assert ref_now is not None
    cutoff = ref_now - timedelta(days=max(1, int(window_days)))
    ignored = {str(p).strip() for p in ignore_projects if str(p).strip()}

    aw_counts: dict[str, int] = {}
    aw_latest: dict[str, datetime] = {}
    for row in aw_batches:
        code = str(row.get("project_code") or row.get("tv_project_id") or "").strip()
        if not code or code in ignored:
            continue
        ts = parse_utc(row.get("created_at"))
        if ts is None or ts < cutoff:
            continue
        aw_counts[code] = aw_counts.get(code, 0) + 1
        if code not in aw_latest or ts > aw_latest[code]:
            aw_latest[code] = ts

    tv_in_window: dict[str, int] = {}
    tv_latest: dict[str, datetime] = {}
    for row in tv_notes:
        code = str(row.get("project_id") or "").strip()
        if not code or code in ignored:
            continue
        ts_ingested = parse_utc(row.get("ingested_at"))
        ts_created = parse_utc(row.get("created_at"))
        ts_pub = parse_utc(row.get("publish_time"))
        ts_ingest = ts_ingested if ts_ingested is not None else ts_created
        if ts_pub is not None and ts_pub > ref_now + timedelta(days=1):
            ts_pub = None
        candidates = [t for t in (ts_ingest, ts_pub) if t is not None]
        if not candidates:
            continue
        best = max(candidates)
        if code not in tv_latest or best > tv_latest[code]:
            tv_latest[code] = best
        if best >= cutoff:
            tv_in_window[code] = tv_in_window.get(code, 0) + 1

    findings: list[StallFinding] = []
    for code, count in sorted(aw_counts.items()):
        if count < max(1, int(min_aw_batches)):
            continue
        if tv_in_window.get(code, 0) > 0:
            continue
        last_tv = tv_latest.get(code)
        days_since = max(0, int((ref_now - last_tv).total_seconds() // 86400)) if last_tv is not None else None
        findings.append(
            StallFinding(
                project_code=code,
                aw_batches_in_window=count,
                tv_notes_in_window=0,
                days_since_last_tv_note=days_since,
                last_aw_batch_date=aw_latest[code].strftime("%Y-%m-%d"),
                last_tv_note_date=last_tv.strftime("%Y-%m-%d") if last_tv is not None else None,
            )
        )
    return findings


def format_report(findings: list[StallFinding], *, window_days: int) -> str:
    """Format a counts-only human-readable summary safe for public Actions logs."""
    if not findings:
        return f"OK: 0 stalled projects in the last {window_days}d (all active writing projects have recent TV notes)."
    lines = [f"WARN: {len(findings)} project(s) had autowriter deliveries in the last {window_days}d but 0 new TV notes:"]
    for f in findings:
        last_tv = (
            f"{f.last_tv_note_date} ({f.days_since_last_tv_note}d ago)"
            if f.last_tv_note_date is not None
            else "never"
        )
        lines.append(
            f"  - {f.project_code}: aw_batches={f.aw_batches_in_window} (last {f.last_aw_batch_date}), "
            f"tv_notes_{window_days}d=0, last_tv_note={last_tv}"
        )
    return "\n".join(lines)


def _fetch_all_pages(query_fn, *, page_size: int = 1000) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    offset = 0
    while True:
        res = query_fn(offset, offset + page_size - 1).execute()
        rows = list(res.data or [])
        out.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
    return out


def fetch_from_supabase(sb: Any, *, now: datetime, window_days: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read-only fetch of mapped autowriter batches and truth_vault note timestamps."""
    cutoff_iso = (now - timedelta(days=max(1, int(window_days)))).isoformat()
    proj_map_rows = _fetch_all_pages(
        lambda lo, hi: sb.schema("autowriter")
        .table("tv_project_map")
        .select("tv_project_id, project_id")
        .order("tv_project_id")
        .order("project_id")
        .range(lo, hi)
    )
    aw_to_tv: dict[str, set[str]] = {}
    for r in proj_map_rows:
        aw_pid = str(r.get("project_id") or "").strip()
        tv_code = str(r.get("tv_project_id") or "").strip()
        if aw_pid and tv_code:
            aw_to_tv.setdefault(aw_pid, set()).add(tv_code)
    if not aw_to_tv:
        return [], []

    raw_batches = _fetch_all_pages(
        lambda lo, hi: sb.schema("autowriter")
        .table("batches")
        .select("id, project_id, created_at")
        .gte("created_at", cutoff_iso)
        .order("id")
        .range(lo, hi)
    )
    aw_batches = []
    active_tv_codes: set[str] = set()
    for b in raw_batches:
        tv_codes = aw_to_tv.get(str(b.get("project_id") or "").strip())
        if not tv_codes:
            continue
        for tv_code in sorted(tv_codes):
            aw_batches.append({"project_code": tv_code, "created_at": b.get("created_at")})
            active_tv_codes.add(tv_code)

    if not active_tv_codes:
        return [], []

    tv_notes = _fetch_all_pages(
        lambda lo, hi: sb.schema("truth_vault")
        .table("notes")
        .select("note_id, project_id, ingested_at, created_at, publish_time")
        .in_("project_id", sorted(active_tv_codes))
        .order("note_id")
        .range(lo, hi)
    )
    return aw_batches, tv_notes


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Detect projects with recent autowriter batches but 0 new TV notes.")
    parser.add_argument("--window-days", type=int, default=14)
    parser.add_argument("--min-aw-batches", type=int, default=1)
    parser.add_argument("--ignore", default="", help="Comma-separated project codes to ignore.")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--fail-on-stall", action="store_true")
    args = parser.parse_args(argv)

    url = (os.environ.get("SUPABASE_URL") or "").strip()
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not (url and key):
        print("SKIP: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not configured (read-only check skipped).")
        return 0

    try:
        from supabase import create_client

        sb = create_client(url, key)
        now = datetime.now(timezone.utc)
        aw_batches, tv_notes = fetch_from_supabase(sb, now=now, window_days=args.window_days)
    except Exception as exc:  # noqa: BLE001 — fail-open if autowriter schema is unavailable (D-153)
        print(f"SKIP: cross-repo stall check unavailable ({type(exc).__name__})")
        return 0

    ignore = [s.strip() for s in args.ignore.split(",") if s.strip()]
    findings = find_stalled_projects(
        aw_batches,
        tv_notes,
        now=now,
        window_days=args.window_days,
        min_aw_batches=args.min_aw_batches,
        ignore_projects=ignore,
    )
    if args.as_json:
        print(json.dumps({"window_days": args.window_days, "stalled": [f.as_dict() for f in findings]}, ensure_ascii=False))
    else:
        print(format_report(findings, window_days=args.window_days))
    if args.fail_on_stall and findings:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
