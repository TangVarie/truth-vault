#!/usr/bin/env python3
"""Completed-scan regressions using the real ingestion main and in-memory I/O.

SQL transaction/concurrent completion behavior is separately exercised by
check_sync_runs.sql against PostgreSQL in CI. No external clients are used.

D-153 additions:
  · v1.25 not applied (missing RPC) → the sync ingests exactly as before v1.25 (old stamp-based
    reconciliation), warns once, scan_completed=0; a transient begin error is NOT "apply the migration";
  · metric / account write failures do not block scan completion (they still turn the run red);
  · the source-level guards of the removed COR-011 CI block that had no behavioural replacement
    (report-only reconciliation, downstream impact list, first-deploy list in scripts/README.md).
"""
from __future__ import annotations

import contextlib
import inspect
import io
import json
import logging
import os
import pathlib
import sys
from unittest.mock import patch

import sync_feishu_notes_to_truth_vault as sync


class Query:
    def __init__(self, db, table):
        self.db, self.table = db, table
    def __getattr__(self, name):
        return lambda *a, **k: self


class Database:
    def __init__(self):
        self.runs, self.notes, self.presence = {}, {}, {}
        self.fail_writes = set()
        self.fail_begin = self.fail_complete = False   # fail_begin: False | 'missing' | 'transient'
        self.legacy_reads = 0
    def schema(self, name):
        return self
    def table(self, name):
        return Query(self, name)
    def rpc(self, name, payload):
        def execute():
            run_id = payload['p_run_id']
            if name == 'begin_note_sync':
                if self.fail_begin == 'missing':
                    raise RuntimeError("{'code': 'PGRST202', 'message': 'Could not find the function "
                                       "truth_vault.begin_note_sync(p_project_id, p_run_id) in the schema cache'}")
                if self.fail_begin:
                    raise RuntimeError('synthetic connection reset by peer')
                self.runs[run_id] = dict(seq=len(self.runs)+1, completed=False)
            elif name == 'complete_note_sync':
                if self.fail_complete:
                    raise RuntimeError('injected completion rollback')
                run = self.runs[run_id]
                for note_id in set(payload['p_note_ids']) | set(payload.get('p_seen_failed_note_ids', [])):
                    self.presence[note_id] = max(run['seq'], self.presence.get(note_id, 0))
                run['completed'] = True
            else:
                raise AssertionError(name)
            return type('Response', (), {'data': 1})()
        return type('RPC', (), {'execute': staticmethod(execute)})()
    def write(self, _, notes, **kwargs):
        written = set()
        for note in notes:
            if note['note_id'] not in self.fail_writes:
                self.notes[note['note_id']] = dict(note)
                written.add(note['note_id'])
        return written
    def vanished(self):
        latest = max((r['seq'] for r in self.runs.values() if r['completed']), default=0)
        return {n for n, seq in self.presence.items() if seq < latest}
    def pages(self, query, **kwargs):
        if query.table == 'v_notes_vanished':
            return [dict(note_id=n, last_seen_run_id='completed', tier='趴') for n in sorted(self.vanished())]
        if query.table == 'notes' and self.fail_begin == 'missing':
            # The pre-v1.25 reconciliation reads the per-note stamps straight from notes.
            self.legacy_reads += 1
            return [dict(note_id='AUDIT_gone', tier='趴', last_seen_run_id='an-older-run', last_seen_at='2000-01-01T00:00:00+00:00'),
                    dict(note_id='AUDIT_never', tier='趴', last_seen_run_id=None, last_seen_at=None)]
        return []
    def completed(self):
        return sum(r['completed'] for r in self.runs.values())


LAST_LOG = ['']


def run(db, ids, *args, fetch_fail=False, fail_records=(), metrics=(0, []), accounts=()):
    class Feishu:
        def __init__(self, *a): pass
        def list_records(self, *a):
            for note_id in ids:
                yield dict(record_id=note_id, fields={'body': 'synthetic'})
            if fetch_fail:
                raise RuntimeError('injected later-page failure')
    mapping = dict(project_id='AUDIT', platform='xiaohongshu', field_mapping={'body': 'raw_content'},
                   sync_config={'feishu_app_token': 'synthetic', 'feishu_table_id': 'synthetic'})
    def transform(_, record_id, fields):
        if record_id in fail_records:
            raise ValueError('synthetic malformed observed row')
        return dict(note_id='AUDIT_'+record_id, project_id='AUDIT', raw_content='synthetic'), None, []
    mocks = dict(FeishuClient=Feishu, get_supabase_client=lambda: db,
                 load_mapping=lambda _: mapping, assert_db_schema_ready=lambda _: None,
                 ensure_project_exists=lambda *a: None, fetch_acknowledged_quarantine=lambda *a: set(),
                 ensure_accounts_batch=lambda *a, **k: list(accounts), upsert_notes_batch=db.write,
                 upsert_metrics_batch=lambda *a, **k: metrics, update_project_date_range=lambda *a: None,
                 _detect_missing_core_columns=lambda *a: [], _detect_missing_capabilities=lambda *a: [],
                 _current_tiers=lambda *a: {}, risk_source_columns=lambda *a: {},
                 prepare_content_layer=lambda *a: True, transform_row=transform, fetch_all_pages=db.pages)
    log = io.StringIO()
    handler = logging.StreamHandler(log)
    old_handlers = list(sync.logger.handlers)
    sync.logger.handlers = [handler]
    try:
        with patch.multiple(sync, **mocks), patch.object(sys, 'argv', ['sync', 'AUDIT', *args]), \
             patch.dict(os.environ, {'FEISHU_APP_ID': 'synthetic', 'FEISHU_APP_SECRET': 'synthetic'}), \
             contextlib.redirect_stdout(io.StringIO()):
            rc = sync.main()
    finally:
        sync.logger.handlers = old_handlers
    LAST_LOG[0] = log.getvalue()
    done = [line.split('Done: ', 1)[1] for line in log.getvalue().splitlines() if 'Done: ' in line]
    return rc, json.loads(done[-1]) if done else {}


def check_source_guards():
    """The parts of the removed COR-011 CI block that the behavioural test above cannot see."""
    src = inspect.getsource(sync.main)
    # One criterion, computed once, shared by stamping and reconciliation.
    assert src.count("full_scan = ") == 1, "full_scan 被算了不止一次"
    assert "full_scan = (not truncated_by_limit) and (not fetch_failed)" in src and "records_all_ok" in src
    assert "writes_all_ok = len(written_ids) == len(pending_notes)\n" in src, \
        "对账 / 账本只看 note 写全没有; 指标和账号的失败不许挡 (D-153)"
    # Report-only: notes has six ON DELETE CASCADE children and rows already pushed to another database.
    recon = src[src.index("对账: 这次完整扫描没见到的"):]
    for forbidden in (".delete(", '"is_deleted"', '"deleted_at"', "tombstone", '.update({"tier"'):
        assert forbidden not in recon, f"对账里出现了 {forbidden!r} —— 这次刻意只报不删"
    # Downstream impact is reported with the vanished list, lesson cards included (CASCADE on note).
    for col in ("synced_to_ssll_at", "synced_to_aw_at", "essence_annotated_at", "flywheel_lesson_annotations"):
        assert col in recon, f"对账没报 {col} —— 清理时不知道要先撤什么"
    # Pre-v1.25 path kept whole: NULL counts as "not this run", concurrent stamps excluded, never-seen apart.
    for needle in ("last_seen_run_id.is.null", "last_seen_run_id.neq.", 'last_seen_at"] >= run_started_at',
                   "missing = [r for r in missing", 'not r.get("last_seen_run_id")'):
        assert needle in recon, f"账本没建时的老对账缺了: {needle}"
    stamp = src[src.index("if full_scan:"):]
    assert "_iso_now_tz()" in stamp, "last_seen_at(TIMESTAMPTZ)用了 naive 的 _iso_now()"
    # Deployment contract: every column / object the sync writes has a migration in the first-deploy list.
    readme = (pathlib.Path(__file__).resolve().parent / "README.md").read_text(encoding="utf-8")
    step0 = readme[readme.index("第一次部署"):readme.index("Step 1")]
    for col in ("last_seen_at", "last_seen_run_id"):
        assert col in src, f"脚本不再写 {col}? 那这条断言该改了"
    for name in ("notes_v1_9", "notes_v1_25_sync_runs.sql", "notes_v1_26_feature_failure_recovery.sql"):
        assert name in step0, f"{name} 不在 scripts/README.md 的首次部署清单里"
    # The ledger is optional until the owner runs v1.25: it must never be a hard schema requirement again.
    for table in ("note_sync_runs", "note_sync_presence"):
        assert table not in _required_columns(), f"{table} 进了 _REQUIRED_COLUMNS —— 没跑迁移的库上整条同步会被挡 (owner 11-02)"


def _required_columns():
    import _common
    return _common._REQUIRED_COLUMNS


def main():
    db = Database()
    assert run(db, ['a', 'b'])[0] == 0 and db.completed() == 1
    rc, stats = run(db, [])
    assert rc == 0 and stats['scan_completed'] == 1 and stats['reconcile_vanished'] == 2
    assert db.vanished() == {'AUDIT_a', 'AUDIT_b'}, 'empty successful scan must advance'

    db = Database()
    assert run(db, ['a', 'b'])[0] == 0
    db.fail_writes = {'AUDIT_b'}
    assert run(db, ['a', 'b'])[0] == 1 and db.completed() == 1
    assert not db.vanished(), 'partial note write must not publish a false deletion'
    db.fail_writes.clear()
    assert run(db, ['a', 'b'], '--limit', '10')[0] == 0 and db.completed() == 1
    assert run(db, ['a'], fetch_fail=True)[0] == 1 and db.completed() == 1
    assert run(db, ['a'], '--dry-run')[0] == 0 and db.completed() == 1
    db.fail_complete = True
    assert run(db, ['a'])[0] == 1 and db.completed() == 1
    db.fail_complete = False
    assert run(db, ['a'])[0] == 0 and db.vanished() == {'AUDIT_b'}
    # Every Done line carries scan_completed, also when nothing was completed (T7).
    for extra in (['--limit', '10'], ['--dry-run']):
        assert run(db, ['a'], *extra)[1]['scan_completed'] == 0

    # ── v1.25 not applied yet (owner rule 11-02): ingest exactly as before, warn once, scan_completed=0 ──
    import _common
    _common._MISSING_DB_OBJECT_WARNED.discard('notes_v1_25')
    db.fail_begin = 'missing'
    completed_before, presence_before = db.completed(), dict(db.presence)
    warnings = 0
    for ids in (['a', 'c'], ['a', 'c', 'd']):
        rc, stats = run(db, ids)
        assert rc == 0 and stats['scan_completed'] == 0, (rc, stats)
        assert stats['upserted'] == len(ids) and 'AUDIT_c' in db.notes, 'notes must still be ingested without the migration'
        assert db.notes['AUDIT_c'].get('last_seen_run_id'), 'the pre-v1.25 path still stamps a full scan'
        # the old stamp-based reconciliation ran: vanished vs never-seen kept apart, as on origin/main
        assert stats['reconcile_vanished'] == 1 and stats['reconcile_never_seen'] == 1, stats
        warnings += LAST_LOG[0].count(sync.LEDGER_MIGRATION)
    assert db.legacy_reads == 2 and warnings == 1, (db.legacy_reads, warnings)
    assert db.completed() == completed_before and db.presence == presence_before, 'no ledger write without the ledger'
    # ── a transient begin error is not "apply the migration": red, notes still ingested, no reconciliation ──
    db.fail_begin = 'transient'
    reads = db.legacy_reads
    rc, stats = run(db, ['a', 'e'])
    assert rc == 1 and stats['scan_completed'] == 0 and stats['errors'] == 1 and 'AUDIT_e' in db.notes, (rc, stats)
    assert sync.LEDGER_MIGRATION not in LAST_LOG[0] and 'connection reset' in LAST_LOG[0]
    assert db.legacy_reads == reads and 'reconcile_vanished' not in stats
    db.fail_begin = False

    # ── metric / account write failures: red, counted, but the scan still completes (T7) ──
    db = Database()
    assert run(db, ['a', 'b'])[0] == 0
    rc, stats = run(db, ['a'], metrics=(0, ['AUDIT_a']), accounts=['acct'])
    assert rc == 1 and stats['metrics_failed'] == 1 and stats['accounts_failed'] == 1, stats
    assert stats['scan_completed'] == 1 and db.vanished() == {'AUDIT_b'}, 'membership evidence needs the notes only'
    assert '指标 1 条 / 账号 1 个没写成' in LAST_LOG[0]
    # D-058 probe saw no existing failed note. An older concurrent scan may
    # create it before or after this run completes; both orderings retain the
    # newer observation rather than incorrectly declaring it absent.
    class InterleavingDatabase(Database):
        inject_before = False
        def write(self, _, notes, **kwargs):
            if self.inject_before:
                self.inject_before = False
                self.notes['AUDIT_bad'] = dict(note_id='AUDIT_bad', project_id='AUDIT')
                self.rpc('complete_note_sync', dict(p_run_id='older', p_note_ids=['AUDIT_a','AUDIT_bad'])).execute()
            return super().write(_, notes, **kwargs)
    for earlier_insert in (True, False):
        db = InterleavingDatabase()
        assert run(db, ['a'])[0] == 0
        db.runs['older'] = dict(seq=2, completed=False)
        db.inject_before = earlier_insert
        rc, stats = run(db, ['a','bad'], fail_records={'bad'})
        assert rc == 1 and stats['scan_completed'] == 1
        if not earlier_insert:
            assert 'AUDIT_bad' not in db.notes and 'AUDIT_bad' in db.presence
            db.notes['AUDIT_bad'] = dict(note_id='AUDIT_bad',project_id='AUDIT')
            db.rpc('complete_note_sync',dict(p_run_id='older',p_note_ids=['AUDIT_a','AUDIT_bad'])).execute()
        assert 'AUDIT_bad' not in db.vanished(), 'a row observed by newer scan became falsely absent'
    check_source_guards()
    print('completed scan main: empty / partial / limit / later page / dry-run / rollback / recovery / '
          'missing migration = old path + one warning / transient begin error / metric failure / COR-011 source guards passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
