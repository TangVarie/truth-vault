"""F03 regressions through real main()/parser. In-memory I/O; no external clients.
SQL conflict handling/attempt limits/grants are separately exercised in the paired .sql file.
"""
from __future__ import annotations
import json
import logging
import os
import re
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import annotate_feature_pass as A
import feature_bank as F


def key(row):
    return tuple(row[k] for k in ('subject_type','subject_id','question_id','question_version','extractor','run_tag'))


class Query:
    def __init__(self, db, table=None, rpc=None, params=None):
        self.db, self.name, self.rpc_name, self.params = db, table, rpc, params
        self.filters, self.bounds, self.payload = [], (0, 10**9), None
    def select(self, *a, **k): return self
    def eq(self, k, v): self.filters.append(lambda r:r.get(k)==v); return self
    def like(self, k, v):
        pattern='^'+''.join('.*' if c=='%' else '.' if c=='_' else re.escape(c) for c in v)+'$'
        self.filters.append(lambda r:bool(re.match(pattern,str(r.get(k,''))))); return self
    def order(self, *a, **k): return self
    def range(self, a, b): self.bounds=(a,b); return self
    def upsert(self, rows, **kw): self.payload=rows; return self
    def execute(self):
        if self.rpc_name: return SimpleNamespace(data=self.db.rpc_call(self.rpc_name,self.params))
        if self.name not in self.db.rows:
            if self.db.transient: raise RuntimeError('synthetic connection reset')
            raise RuntimeError("{'code': 'PGRST205', 'message': \"Could not find the table 'truth_vault.%s' in the schema cache\"}" % self.name)
        if self.payload is not None:
            rows=self.payload if isinstance(self.payload,list) else [self.payload]
            self.db.rows[self.name].extend(dict(r) for r in rows)
            return SimpleNamespace(data=rows)
        rows=[r for r in self.db.rows[self.name] if all(f(r) for f in self.filters)]
        a,b=self.bounds
        return SimpleNamespace(data=rows[a:b+1])


class Store:
    def __init__(self):
        self.rows={'notes':[dict(note_id='AUDIT_1',project_id='AUDIT',title='Synthetic title',
                                raw_content='Synthetic body sentence. '*15+'\n\nSynthetic ending question?',projects={})],
                   'note_features':[],'note_feature_answers':[],'feature_annotation_failures':[]}
        self.transient=False
    def schema(self, *a): return self
    def table(self, name): return Query(self,table=name)
    def rpc(self,name,params): return Query(self,rpc=name,params=params)
    def rpc_call(self,name,p):
        # Mirrors schemas/notes_v1_26_feature_failure_recovery.sql; the SQL itself is exercised by the paired .sql file.
        if 'feature_annotation_failures' not in self.rows:
            if self.transient: raise RuntimeError('synthetic connection reset')
            raise RuntimeError("{'code': 'PGRST202', 'message': 'Could not find the function truth_vault.%s in the schema cache'}" % name)
        if name=='write_feature_answers_preserving_valid':
            for row in p['p_rows']:
                old=next((r for r in self.rows['note_feature_answers'] if key(r)==key(row)),None)
                if old is None:self.rows['note_feature_answers'].append(dict(row))
                elif row['answer'] is not None or old['answer'] is None:old.update(row)
            return len(p['p_rows'])
        match=lambda r:all(r[k[2:]]==p[k] for k in ('p_subject_id','p_bank_sha256','p_extractor','p_run_tag'))
        queue=self.rows['feature_annotation_failures']
        row=next((r for r in queue if match(r)),None)
        now=datetime.now(timezone.utc)
        if name=='claim_feature_annotation_attempt':
            if row is None:
                row=dict(id=max([r['id'] for r in queue],default=0)+1,subject_id=p['p_subject_id'],project_id=p['p_project_id'],
                         bank_sha256=p['p_bank_sha256'],extractor=p['p_extractor'],run_tag=p['p_run_tag'],attempts=0)
                queue.append(row)
            elif not p['p_replay'] and A.retry_state(row)!='ready':return None
            # A claim is a 20-hour lease and does not consume an attempt.
            row.update(claim_token=str(uuid.uuid4()),next_retry_at=(now+timedelta(hours=20)).isoformat(),last_error='in_progress')
            return row['claim_token']
        if name=='finish_feature_annotation_attempt':
            if row is not None and row['claim_token']==p['p_claim_token']:
                if p['p_success']:
                    queue[:]=[r for r in queue if not (r['subject_id']==row['subject_id'] and r['bank_sha256']==row['bank_sha256']
                              and r['run_tag']==row['run_tag'] and (r is row or r['extractor'].startswith('llm:')))]
                elif p['p_consume']:
                    row.update(attempts=row['attempts']+1,last_error=p['p_error'],
                               next_retry_at=(now+timedelta(hours=20 if row['attempts']==0 else 44)).isoformat())
                else:row.update(last_error=p['p_error'],next_retry_at=now.isoformat())
            return None
        raise AssertionError(name)


def good_llm(calls):
    idx=F.question_index(F.load_bank())
    def good(system,user,model):
        calls.append(1)
        qids=[line.split(' · ')[0].split('. ',1)[1] for line in system.splitlines() if ' · 看【' in line]
        rows=[dict(id=q,answer='否' if idx[q]['type']=='bool' else '未出现' if q=='product_role' else F.closed_set(idx[q])[0],evidence='') for q in qids]
        return json.dumps(dict(answers=rows),ensure_ascii=False)
    return good


DUE='2000-01-01T00:00:00+00:00'


def main():
    store=Store();calls=[]; messages=[]
    class Handler(logging.Handler):
        def emit(self,record):messages.append(record.getMessage())
    handler=Handler();A.logger.addHandler(handler)
    queue=lambda:store.rows['feature_annotation_failures']
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,ANTHROPIC_API_KEY='synthetic'), \
         patch.object(A,'get_supabase_client',side_effect=lambda:store), \
         patch.object(A,'load_mapping',return_value={'title_extraction':'column'}), \
         patch.object(A,'_llm',side_effect=lambda *a:(calls.append(1) or 'not JSON')):
        argv=['AUDIT','--qps','0','--model','synthetic','--limit','1','--failed-queue',tmp+'/failed.jsonl']
        # ── 1. A new all-invalid note: red THIS run, no completion marker, one counted attempt. ──
        assert A.main(argv)==1 and len(calls)==32
        assert not store.rows['note_feature_answers'], 'zero useful model answers may not write a completion marker'
        assert any('"model_valid_rate": 0.0' in m for m in messages)
        assert queue()[0]['attempts']==1 and queue()[0]['last_error']==A.ERR_MODEL_INVALID
        wait=datetime.fromisoformat(queue()[0]['next_retry_at'])-datetime.now(timezone.utc)
        assert timedelta(hours=19)<wait<timedelta(hours=21), 'first back-off must leave the next nightly (24h later) eligible'
        # ── 2. Standing backlog is reported, costs nothing and is NOT red (T4). ──
        assert A.main(argv)==0 and len(calls)==32, 'a waiting note must not be paid for again or turn the run red'
        assert any('"retry_deferred": 1' in m for m in messages)
        # ── 3. Counted failures are bounded at three; the second back-off is about 44h. ──
        for expected in (2,3):
            queue()[0]['next_retry_at']=DUE
            assert A.main(argv)==1 and queue()[0]['attempts']==expected
            if expected==2:
                wait=datetime.fromisoformat(queue()[0]['next_retry_at'])-datetime.now(timezone.utc)
                assert timedelta(hours=43)<wait<timedelta(hours=45)
        paid=len(calls)
        queue()[0]['next_retry_at']=DUE
        messages.clear()
        assert A.main(argv)==0 and len(calls)==paid, 'a quarantined note is never retried automatically and is not red'
        assert any('"retry_quarantined": 1' in m for m in messages)
        # ── 4. Explicit replay performs one caller-requested pass and clears recovery only on success. ──
        with patch.object(A,'_llm',side_effect=good_llm(calls)):
            assert A.main(argv+['--reannotate'])==0
        assert not queue()
        assert len(store.rows['note_feature_answers'])==31
        paid=len(calls)
        assert A.main(argv)==0 and len(calls)==paid
        # ── 5. A historical all-NULL marker with an imported queue item cannot remain "done". ──
        marker=next(r for r in store.rows['note_feature_answers'] if r['question_id']==A.DONE_MARKER_QUESTION)
        queue().append(dict(id=99,subject_id='AUDIT_1',project_id='AUDIT',
            bank_sha256=marker['bank_sha256'],extractor=marker['extractor'],run_tag='primary',attempts=0,
            next_retry_at=DUE,last_error='legacy_all_invalid'))
        assert A.fetch_done_ids(store,'AUDIT',extractor='llm:synthetic')==set()
        marker['bank_sha256']='older-valid-sha'
        assert A.fetch_done_ids(store,'AUDIT',extractor='llm:synthetic')==set(), 'an older valid marker cannot hide a failed current snapshot'
        # Invalid rows from a partial reannotation must still go through the preserving RPC.
        invalid=dict(marker,answer=None,invalid_reason='json_parse_failed')
        A.write_answers(store,[invalid],False)
        assert marker['answer'] is not None
        queue().clear()

        # ── 6. T1: a legacy queue row under ANOTHER model label (production switched models). ──
        # The nightly sends no --model: done-rule is llm:%, the worker writes llm:<FEATURE_MODEL>.
        nightly=['AUDIT','--qps','0','--limit','1','--failed-queue',tmp+'/failed.jsonl']
        sha=F.load_bank()['_sha256']
        with patch.dict(os.environ,FEATURE_MODEL='synthetic-new'):
            store.rows['note_feature_answers'].clear()
            store.rows['note_feature_answers'].append(dict(marker,extractor='llm:synthetic-old',answer=None,
                                                           invalid_reason='json_parse_failed',bank_sha256=sha))
            queue().append(dict(id=7,subject_id='AUDIT_1',project_id='AUDIT',bank_sha256=sha,extractor='llm:synthetic-old',
                                run_tag='primary',attempts=0,next_retry_at=DUE,last_error='legacy_all_invalid'))
            paid=len(calls)
            with patch.object(A,'_llm',side_effect=good_llm(calls)):
                assert A.main(nightly)==0 and len(calls)>paid, 'the legacy note must be re-annotated once'
                assert not queue(), 'success must clear the queue row under the other model label too'
                paid=len(calls)
                for _ in range(2):
                    assert A.main(nightly)==0 and len(calls)==paid, 'second run must make 0 model calls (no nightly re-pay loop)'
            import count_unannotated_features as C
            with patch.object(C,'get_supabase_client',return_value=store):
                assert C.count_remaining('AUDIT')==0
            # A quarantined row under the old label still blocks automatic retries under the new one,
            # and the count the nightly uses says "nothing to do" (no worker call, no spend).
            store.rows['note_feature_answers'].clear()
            queue().append(dict(id=8,subject_id='AUDIT_1',project_id='AUDIT',bank_sha256=sha,extractor='llm:synthetic-old',
                                run_tag='primary',attempts=3,next_retry_at=DUE,last_error=A.ERR_MODEL_INVALID))
            with patch.object(A,'_llm',side_effect=good_llm(calls)):
                assert A.main(nightly)==0 and len(calls)==paid
            with patch.object(C,'get_supabase_client',return_value=store):
                assert C.count_remaining('AUDIT')==0, 'blocked backlog is not "work the worker can do now"'
            queue().clear()

        # ── 7. T3: infrastructure failures release the claim and never consume the retry budget. ──
        def api_down(*a):
            calls.append(1); raise RuntimeError('synthetic API failure')
        with patch.object(A,'_llm',side_effect=api_down):
            for _ in range(5):                       # five bad nights in a row
                assert A.main(argv)==1               # origin/main rule: systemic and nothing succeeded
                assert queue()[0]['attempts']==0 and queue()[0]['last_error']=='systemic'
                assert A.retry_state(queue()[0])=='ready', 'an API failure must leave the note eligible for the next run'
        class RejectingStore(Store):
            def rpc_call(self,name,p):
                if name=='write_feature_answers_preserving_valid':raise RuntimeError('synthetic constraint violation')
                return super().rpc_call(name,p)
        rejecting=RejectingStore()
        with patch.object(A,'get_supabase_client',side_effect=lambda:rejecting), patch.object(A,'_llm',side_effect=good_llm(calls)):
            assert A.main(argv)==1
        row=rejecting.rows['feature_annotation_failures'][0]
        assert row['attempts']==0 and row['last_error']=='write_rejected' and A.retry_state(row)=='ready'
        assert not rejecting.rows['note_feature_answers'], 'a non-missing write error must not fall back to a plain upsert'
        # One transient error on the claim RPC costs that one note, not the batch: no model call for it, no
        # attempt counted, the rest of the batch is annotated and the Done line is still printed.
        class FlakyClaim(Store):
            blips=1
            def rpc_call(self,name,p):
                if name=='claim_feature_annotation_attempt' and self.blips:
                    self.blips-=1; raise RuntimeError('synthetic 502 on claim')
                return super().rpc_call(name,p)
        flaky=FlakyClaim(); flaky.rows['notes'].append(dict(flaky.rows['notes'][0],note_id='AUDIT_2'))
        two=['--limit' if a=='--limit' else a for a in argv]; two[two.index('--limit')+1]='2'
        messages.clear(); paid=len(calls)
        with patch.object(A,'get_supabase_client',side_effect=lambda:flaky), patch.object(A,'_llm',side_effect=good_llm(calls)):
            assert A.main(two)==0, 'a claim blip on one note must not fail a batch whose other note succeeded'
        assert len(calls)==paid+6, 'the note whose claim failed is not sent to the model; the other one is'
        done_line=next(m for m in messages if m.startswith('Done: '))
        assert '"ok": 1' in done_line and '"failed": 1' in done_line and '"systemic_failed": 1' in done_line, done_line
        assert not flaky.rows['feature_annotation_failures'], 'no queue row may be left behind by a failed claim'
        assert 'claim_failed' in open(tmp+'/failed.jsonl').read()
        assert not any(A.RECOVERY_MIGRATION in m for m in messages), 'a transient claim error is not "apply the migration"'
        flaky.blips=99; flaky.rows['notes'].append(dict(flaky.rows['notes'][0],note_id='AUDIT_3'))
        with patch.object(A,'get_supabase_client',side_effect=lambda:flaky), patch.object(A,'_llm',side_effect=good_llm(calls)):
            assert A.main(two)==1 and len(calls)==paid+6, 'when every claim fails the run is still red (real outage), at no model cost'
        # A killed worker leaves 'in_progress': the lease expires by itself, the budget is untouched.
        killed=dict(queue()[0],last_error='in_progress',next_retry_at=(datetime.now(timezone.utc)+timedelta(hours=20)).isoformat())
        assert A.retry_state(killed)=='deferred'
        killed['next_retry_at']=DUE
        assert A.retry_state(killed)=='ready' and killed['attempts']==0
        with patch.object(A,'_llm',side_effect=good_llm(calls)):
            assert A.main(argv)==0 and not queue()

        # ── 8. T2: v1.26 not applied yet → one warning, then exactly the pre-v1.26 behaviour. ──
        bare=Store(); del bare.rows['feature_annotation_failures']
        messages.clear()
        import _common
        _common._MISSING_DB_OBJECT_WARNED.discard('notes_v1_26')
        with patch.object(A,'get_supabase_client',side_effect=lambda:bare):
            paid=len(calls)
            assert A.main(argv)==0 and len(calls)==paid+32, 'without the migration the note is annotated as before'
            # origin/main: an all-invalid note still lands its rows (marker included) through a plain upsert
            assert len(bare.rows['note_feature_answers'])==31 and all(r['answer'] is None or r['extractor']=='code:v1'
                                                                      for r in bare.rows['note_feature_answers'])
            assert A.main(argv)==0 and len(calls)==paid+32, 'and it is done afterwards, as on origin/main'
        warned=[m for m in messages if A.RECOVERY_MIGRATION in m]
        assert len(warned)==1, f'missing migration must warn exactly once, got {len(warned)}'
        # Any other error is NOT described as "apply the migration" and is not swallowed.
        bare=Store(); del bare.rows['feature_annotation_failures']; bare.transient=True
        messages.clear()
        with patch.object(A,'get_supabase_client',side_effect=lambda:bare):
            try:
                A.main(argv); raise AssertionError('a transient queue read error must not be swallowed')
            except RuntimeError as exc:
                assert 'connection reset' in str(exc)
        assert not any(A.RECOVERY_MIGRATION in m for m in messages)
        # The nightly page gets one annotation from the backlog report (the worker's own warning stays in the
        # worker log), and the count script keeps stdout for the number alone.
        import contextlib, io, sys
        import count_unannotated_features as C
        import feature_recovery_report as R
        bare=Store(); del bare.rows['feature_annotation_failures']
        _common._MISSING_DB_OBJECT_WARNED.discard('notes_v1_26')
        out=io.StringIO()
        with patch.object(R,'get_supabase_client',return_value=bare), contextlib.redirect_stdout(out):
            assert R.main(['AUDIT'])==0
        assert out.getvalue().count('::warning title=迁移还没跑 (notes_v1_26)::')==1 and A.RECOVERY_MIGRATION in out.getvalue()
        bare.transient=True; out=io.StringIO()
        with patch.object(R,'get_supabase_client',return_value=bare), contextlib.redirect_stdout(out):
            assert R.main(['AUDIT'])==0
        assert '迁移' not in out.getvalue() and '没读到' in out.getvalue(), 'a transient read error is not "apply the migration"'
        bare.transient=False; out=io.StringIO()
        _common._MISSING_DB_OBJECT_WARNED.discard('notes_v1_26')
        with patch.object(C,'get_supabase_client',return_value=bare), contextlib.redirect_stdout(out):
            stdout_handler=logging.StreamHandler(sys.stdout); A.logger.addHandler(stdout_handler)   # what setup_logger installs
            try:
                assert C.main(['AUDIT'])==0
            finally:
                A.logger.removeHandler(stdout_handler)
        assert any(A.RECOVERY_MIGRATION in m for m in messages), 'the warning is still logged (to stderr), not dropped'
        assert out.getvalue()=='1\n', f'count stdout must be the bare number, got {out.getvalue()!r}'

        # ── 9. Actual no-input scopes skip model questions; this is not a bad model response. ──
        empty=Store();empty.rows['notes'][0].update(title='',raw_content='')
        paid=len(calls)
        with patch.object(A,'get_supabase_client',side_effect=lambda:empty):
            assert A.main(argv)==0 and len(calls)==paid
        assert not empty.rows['feature_annotation_failures']
    A.logger.removeHandler(handler)
    print('✓ F03 / D-153: new all-invalid is red once; backlog is reported not red; 20h/44h back-off; bounded at 3; replay; '
          'other-model-label row cleared (0 calls on 2nd run); infra failures keep the budget; a claim blip costs one note; missing v1.26 = old behaviour + 1 warning, count stays a bare number')
    return 0


if __name__=='__main__':raise SystemExit(main())
