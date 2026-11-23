#!/usr/bin/env python3
"""Unit tests for scripts/check_cross_repo_stall.py (synthetic fixtures only)."""

from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_cross_repo_stall as stall


def test_detects_silent_table_switch_and_skips_active_or_quiet():
    now = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    aw_batches = [
        # Active project: delivering & syncing normally
        {"project_code": "PROJ_OK", "created_at": "2026-11-20T08:00:00Z"},
        # Silent stall (I-39 pattern): 2 recent deliveries, last TV note 31 days ago
        {"project_code": "PROJ_MOVED", "created_at": "2026-11-17T10:00:00+08:00"},
        {"project_code": "PROJ_MOVED", "created_at": "2026-11-23T06:00:00Z"},
        # Never synced in TV yet
        {"project_code": "PROJ_NEW", "created_at": "2026-11-22T01:00:00Z"},
        # Old batch outside 14d window -> should not trigger
        {"project_code": "PROJ_DONE", "created_at": "2026-10-01T00:00:00Z"},
    ]
    tv_notes = [
        {"project_id": "PROJ_OK", "created_at": "2026-11-21T02:00:00Z", "publish_time": "2026-11-20T12:00:00+08:00"},
        {"project_id": "PROJ_MOVED", "created_at": "2026-10-23T09:00:00Z", "publish_time": "2026-10-22T12:00:00+08:00"},
        {"project_id": "PROJ_DONE", "created_at": "2026-10-02T00:00:00Z"},
    ]

    findings = stall.find_stalled_projects(aw_batches, tv_notes, now=now, window_days=14)
    by_code = {f.project_code: f for f in findings}
    assert set(by_code) == {"PROJ_MOVED", "PROJ_NEW"}

    moved = by_code["PROJ_MOVED"]
    assert moved.aw_batches_in_window == 2
    assert moved.tv_notes_in_window == 0
    assert moved.days_since_last_tv_note == 31
    assert moved.last_tv_note_date == "2026-10-23"
    assert moved.last_aw_batch_date == "2026-11-23"

    new_proj = by_code["PROJ_NEW"]
    assert new_proj.days_since_last_tv_note is None
    assert new_proj.last_tv_note_date is None

    # min_aw_batches & ignore_projects filters
    filtered = stall.find_stalled_projects(
        aw_batches,
        tv_notes,
        now=now,
        window_days=14,
        min_aw_batches=2,
        ignore_projects=["PROJ_NEW"],
    )
    assert [f.project_code for f in filtered] == ["PROJ_MOVED"]


def test_naive_timestamp_and_counts_only_format():
    now = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    findings = stall.find_stalled_projects(
        [{"project_code": "SYNTH_A", "created_at": "2026-11-22T10:00:00"}],
        [{"project_id": "SYNTH_A", "created_at": "2026-10-15T10:00:00"}],
        now=now,
        window_days=14,
    )
    assert len(findings) == 1
    report = stall.format_report(findings, window_days=14)
    assert "SYNTH_A" in report and "aw_batches=1" in report and "tv_notes_14d=0" in report
    assert "OK: 0 stalled" in stall.format_report([], window_days=14)


def test_publish_time_in_window_counts_as_recent():
    now = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    findings = stall.find_stalled_projects(
        [{"project_code": "SYNTH_B", "created_at": "2026-11-20T00:00:00Z"}],
        [{"project_id": "SYNTH_B", "created_at": "2026-10-01T00:00:00Z", "publish_time": "2026-11-19T00:00:00Z"}],
        now=now,
        window_days=14,
    )
    assert findings == []
    # Future publish_time typo (COR-024 pattern) must not mask a silent stall
    typo_findings = stall.find_stalled_projects(
        [{"project_code": "SYNTH_TYPO", "created_at": "2026-11-20T00:00:00Z"}],
        [{"project_id": "SYNTH_TYPO", "ingested_at": "2026-10-01T00:00:00Z", "publish_time": "2028-01-01T00:00:00Z"}],
        now=now,
        window_days=14,
    )
    assert [f.project_code for f in typo_findings] == ["SYNTH_TYPO"]


def test_fetch_from_supabase_schema_and_mapping():
    now = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    seen_queries: list[tuple[str, str, str, list[str]]] = []

    class _FakeResp:
        def __init__(self, data):
            self.data = data

    class _FakeQuery:
        def __init__(self, schema_name: str, table_name: str, rows: list[dict]):
            self.schema_name = schema_name
            self.table_name = table_name
            self.rows = rows
            self.cols = ""
            self.orders: list[str] = []
            self.lo = 0
            self.hi = 999

        def select(self, cols: str):
            self.cols = cols
            return self

        def gte(self, _col: str, _val: str):
            return self

        def in_(self, col: str, vals: list[str]):
            allowed = set(vals)
            self.rows = [r for r in self.rows if r.get(col) in allowed]
            return self

        def order(self, col: str):
            self.orders.append(col)
            return self

        def range(self, lo: int, hi: int):
            self.lo = lo
            self.hi = hi
            return self

        def execute(self):
            seen_queries.append((self.schema_name, self.table_name, self.cols, list(self.orders)))
            return _FakeResp(self.rows[self.lo : self.hi + 1])

    class _FakeSchema:
        def __init__(self, name: str, tables: dict[str, list[dict]]):
            self.name = name
            self.tables = tables

        def table(self, table_name: str):
            return _FakeQuery(self.name, table_name, list(self.tables[table_name]))

    class _FakeSB:
        def __init__(self, data):
            self.data = data

        def schema(self, name: str):
            return _FakeSchema(name, self.data[name])

    sb = _FakeSB(
        {
            "autowriter": {
                "tv_project_map": [
                    {"tv_project_id": "TV_STALL", "project_id": "aw-1"},
                    {"tv_project_id": "TV_ACTIVE", "project_id": "aw-2"},
                ],
                "batches": [
                    {"id": "b1", "project_id": "aw-1", "created_at": "2026-11-22T00:00:00Z"},
                    {"id": "b2", "project_id": "aw-2", "created_at": "2026-11-22T00:00:00Z"},
                ],
            },
            "truth_vault": {
                "notes": [
                    {
                        "note_id": "n1",
                        "project_id": "TV_STALL",
                        "ingested_at": "2026-10-10T00:00:00Z",
                        "created_at": "2026-11-22T00:00:00Z",  # upsert-touched created_at must not mask old ingested_at
                        "publish_time": None,
                    },
                    {
                        "note_id": "n2",
                        "project_id": "TV_ACTIVE",
                        "ingested_at": "2026-11-21T00:00:00Z",
                        "created_at": "2026-11-21T00:00:00Z",
                        "publish_time": None,
                    },
                ],
            },
        }
    )

    aw_batches, tv_notes = stall.fetch_from_supabase(sb, now=now, window_days=14)
    findings = stall.find_stalled_projects(aw_batches, tv_notes, now=now, window_days=14)
    assert [f.project_code for f in findings] == ["TV_STALL"]
    assert seen_queries == [
        ("autowriter", "tv_project_map", "tv_project_id, project_id", ["tv_project_id", "project_id"]),
        ("autowriter", "batches", "id, project_id, created_at", ["id"]),
        ("truth_vault", "notes", "note_id, project_id, ingested_at, created_at, publish_time", ["note_id"]),
    ]


if __name__ == "__main__":
    test_detects_silent_table_switch_and_skips_active_or_quiet()
    test_naive_timestamp_and_counts_only_format()
    test_publish_time_in_window_counts_as_recent()
    test_fetch_from_supabase_schema_and_mapping()
    print("ALL check_cross_repo_stall tests PASSED")
