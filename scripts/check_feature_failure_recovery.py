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
        if self.name not in self.db.rows: raise RuntimeError('synthetic missing migration')
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
    def schema(self, *a): return self
    def table(self, name): return Query(self,table=name)
    def rpc(self,name,params): return Query(self,rpc=name,params=params)
    def rpc_call(self,name,p):
        if name=='write_feature_answers_preserving_valid':
            for row in p['p_rows']:
                old=next((r for r in self.rows['note_feature_answers'] if key(r)==key(row)),None)
                if old is None:self.rows['note_feature_answers'].append(dict(row))
                elif row['answer'] is not None or old['answer'] is None:old.update(row)
            return len(p['p_rows'])
        match=lambda r:all(r[k[2:]]==p[k] for k in ('p_subject_id','p_bank_sha256','p_extractor','p_run_tag'))
        queue=self.rows['feature_annotation_failures']
        row=next((r for r in queue if match(r)),None)
        if name=='claim_feature_annotation_attempt':
            if row is None:
                row=dict(id=len(queue)+1,subject_id=p['p_subject_id'],project_id=p['p_project_id'],
                         bank_sha256=p['p_bank_sha256'],extractor=p['p_extractor'],run_tag=p['p_run_tag'],attempts=0)
                queue.append(row)
            elif not p['p_replay'] and A.retry_state(row)!='ready':return None
            row.update(claim_token=str(uuid.uuid4()),attempts=row['attempts']+1,next_retry_at=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat(),last_error='in_progress')
            return row['claim_token']
        if name=='finish_feature_annotation_attempt':
            if row is not None and row['claim_token']==p['p_claim_token']:
                if p['p_success']:queue.remove(row)
                else:row['last_error']=p['p_error']
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


def main():
    store=Store();calls=[]; messages=[]
    class Handler(logging.Handler):
        def emit(self,record):messages.append(record.getMessage())
    handler=Handler();A.logger.addHandler(handler)
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,ANTHROPIC_API_KEY='synthetic'), \
         patch.object(A,'get_supabase_client',return_value=store), \
         patch.object(A,'load_mapping',return_value={'title_extraction':'column'}), \
         patch.object(A,'_llm',side_effect=lambda *a:(calls.append(1) or 'not JSON')):
        argv=['AUDIT','--qps','0','--model','synthetic','--limit','1','--failed-queue',tmp+'/failed.jsonl']
        assert A.main(argv)==1 and len(calls)==32
        assert not store.rows['note_feature_answers'], 'zero useful model answers may not write a completion marker'
        assert any('"model_valid_rate": 0.0' in m for m in messages)
        assert A.main(argv)==1 and len(calls)==32, 'backoff must not pay for another 32 calls'
        # Due retries are bounded. Every later automatic pass surfaces quarantine without inference.
        for expected in (2,3):
            store.rows['feature_annotation_failures'][0]['next_retry_at']='2000-01-01T00:00:00+00:00'
            assert A.main(argv)==1 and store.rows['feature_annotation_failures'][0]['attempts']==expected
        paid=len(calls)
        store.rows['feature_annotation_failures'][0]['next_retry_at']='2000-01-01T00:00:00+00:00'
        assert A.main(argv)==1 and len(calls)==paid
        # Explicit replay performs one caller-requested pass and clears recovery only on success.
        with patch.object(A,'_llm',side_effect=good_llm(calls)):
            assert A.main(argv+['--reannotate'])==0
        assert not store.rows['feature_annotation_failures']
        assert len(store.rows['note_feature_answers'])==31
        paid=len(calls)
        assert A.main(argv)==0 and len(calls)==paid
        # A historical all-NULL marker with an imported queue item cannot remain "done".
        marker=next(r for r in store.rows['note_feature_answers'] if r['question_id']==A.DONE_MARKER_QUESTION)
        store.rows['feature_annotation_failures'].append(dict(id=99,subject_id='AUDIT_1',project_id='AUDIT',
            bank_sha256=marker['bank_sha256'],extractor=marker['extractor'],run_tag='primary',attempts=0,
            next_retry_at='2000-01-01T00:00:00+00:00',last_error='legacy_all_invalid'))
        assert A.fetch_done_ids(store,'AUDIT',extractor='llm:synthetic')==set()
        marker['bank_sha256']='older-valid-sha'
        assert A.fetch_done_ids(store,'AUDIT',extractor='llm:synthetic')==set(), 'an older valid marker cannot hide a failed current snapshot'
        # Invalid rows from a partial reannotation must still go through the preserving RPC.
        invalid=dict(marker,answer=None,invalid_reason='json_parse_failed')
        A.write_answers(store,[invalid],False)
        assert marker['answer'] is not None
        # Missing recovery schema stops before inference, with the deployment migration named.
        del store.rows['feature_annotation_failures']
        paid=len(calls)
        assert A.main(argv)==2 and len(calls)==paid
        assert any(A.RECOVERY_MIGRATION in m for m in messages)
        # Actual no-input scopes skip model questions; this is not a bad model response.
        empty=Store();empty.rows['notes'][0].update(title='',raw_content='')
        paid=len(calls)
        with patch.object(A,'get_supabase_client',return_value=empty):
            assert A.main(argv)==0 and len(calls)==paid
        assert not empty.rows['feature_annotation_failures']
    A.logger.removeHandler(handler)
    print('✓ F03: real main two-pass failure, bounded retries, explicit recovery, legacy marker, valid preservation, missing-schema refusal')
    return 0


if __name__=='__main__':raise SystemExit(main())
