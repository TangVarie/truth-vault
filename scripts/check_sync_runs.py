#!/usr/bin/env python3
"""Completed-scan regressions using the real ingestion main and in-memory I/O.

SQL transaction/concurrent completion behavior is separately exercised by
check_sync_runs.sql against PostgreSQL in CI. No external clients are used.
"""
from __future__ import annotations

import contextlib
import io
import json
import logging
import os
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
        self.fail_begin = self.fail_complete = False
    def schema(self, name):
        return self
    def table(self, name):
        return Query(self, name)
    def rpc(self, name, payload):
        def execute():
            run_id = payload['p_run_id']
            if name == 'begin_note_sync':
                if self.fail_begin:
                    raise RuntimeError('missing RPC')
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
        return []
    def completed(self):
        return sum(r['completed'] for r in self.runs.values())


def run(db, ids, *args, fetch_fail=False, fail_records=()):
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
                 ensure_accounts_batch=lambda *a, **k: [], upsert_notes_batch=db.write,
                 upsert_metrics_batch=lambda *a, **k: (0, []), update_project_date_range=lambda *a: None,
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
    done = [line.split('Done: ', 1)[1] for line in log.getvalue().splitlines() if 'Done: ' in line]
    return rc, json.loads(done[-1]) if done else {}


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
    db.fail_begin = True
    before = dict(db.notes)
    assert run(db, ['c'])[0] == 2 and db.notes == before, 'missing migration must fail before writes'
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
    print('completed scan main: empty / partial / limit / later page / dry-run / rollback / recovery / missing schema passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
