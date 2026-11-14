#!/usr/bin/env python3
"""Run the real workflow shell loop with worker I/O executing real annotation main (D-153).

The worker transport, database and model are in-memory synthetic fixtures. State
persists between shell requests; real curl/network clients are never invoked.
"""
from __future__ import annotations

import io
import json
import logging
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
from unittest.mock import patch

import yaml
import annotate_feature_pass as A
import feature_bank as F
from check_feature_failure_recovery import Store, good_llm
from feature_batch_state import classify

ROOT = Path(__file__).resolve().parent.parent


def fixture(mode, healthy):
    store = Store()
    base = store.rows['notes'].pop()
    store.rows['notes'] = [dict(base, note_id=f'AUDIT_h{i}') for i in range(healthy)]
    if mode == 'no_migration':    # v1.26 not applied: the queue table and its functions do not exist
        del store.rows['feature_annotation_failures']
    elif mode != 'new_invalid':
        store.rows['notes'].insert(0, dict(base, note_id='AUDIT_blocked'))
        store.rows['feature_annotation_failures'] = [dict(id=1,subject_id='AUDIT_blocked',project_id='AUDIT',
            bank_sha256=F.load_bank()['_sha256'],extractor='llm:synthetic',run_tag='primary',attempts=3,
            next_retry_at='2999-01-01T00:00:00+00:00',last_error='all_model_answers_invalid')]
    return dict(rows=store.rows, mode=mode, model_calls=0, worker_calls=0)


def fake_transport(kind, args):
    path = Path(os.environ['AUDIT_FEATURE_STATE'])
    state = json.loads(path.read_text())
    store = Store(); store.rows = state['rows']
    if kind == '--fake-count':       # the real count script, on the in-memory store
        import count_unannotated_features as C
        with patch.object(C, 'get_supabase_client', return_value=store):
            return C.main(['AUDIT'])
    if kind == '--fake-report':      # the real backlog report, on the in-memory store
        import feature_recovery_report as R
        with patch.object(R, 'get_supabase_client', return_value=store):
            return R.main(args)
    payload = json.loads(args[args.index('-d')+1])
    calls = []
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    old_handlers = A.logger.handlers; A.logger.handlers = [handler]
    llm = good_llm(calls) if state['mode'] != 'new_invalid' else lambda *a:(calls.append(1) or 'not JSON')
    if state['mode'] == 'api_failure':
        def llm(*args):
            calls.append(1)
            raise RuntimeError('synthetic API failure')
    try:
        with patch.dict(os.environ,ANTHROPIC_API_KEY='synthetic'), \
             patch.object(A,'get_supabase_client',return_value=store), \
             patch.object(A,'load_mapping',return_value={'title_extraction':'column'}), \
             patch.object(A,'_llm',side_effect=llm):
            rc=A.main(['AUDIT','--qps','0','--model','synthetic','--limit',str(payload['limit']),
                       '--failed-queue',str(path)+'.failed.jsonl'])
    finally:
        A.logger.handlers = old_handlers
    state.update(rows=store.rows, model_calls=state['model_calls']+len(calls), worker_calls=state['worker_calls']+1)
    path.write_text(json.dumps(state))
    result=dict(ok=rc==0,returncode=rc,stdout_tail=output.getvalue()[-8000:],stderr_tail='')
    Path(args[args.index('-o')+1]).write_text(json.dumps(result))
    print('200',end='')
    return 0


def run_shell(mode, healthy, budget):
    workflow=yaml.safe_load((ROOT/'.github/workflows/features-sync.yml').read_text())
    shell=next(s['run'] for s in workflow['jobs']['features']['steps'] if s.get('id')=='features_sync')
    shell=re.sub(r'\$\{\{.*?\}\}',lambda m:'false' if 'dry_run' in m[0] else 'synthetic',shell)
    with tempfile.TemporaryDirectory() as tmp:
        base=Path(tmp); scripts=base/'scripts'; scripts.mkdir(); (base/'mappings').mkdir()
        (base/'mappings/AUDIT.yaml').write_text('project_id: AUDIT\n')
        (scripts/'feature_batch_state.py').symlink_to(ROOT/'scripts/feature_batch_state.py')
        bin_dir=base/'bin';bin_dir.mkdir()
        real=shlex.quote(sys.executable); here=shlex.quote(str(Path(__file__).resolve()))
        python=bin_dir/'python'
        python.write_text(f'''#!/bin/bash
case "$1" in
 skip_on_cron.py) exit 1 ;;
 count_unannotated_features.py) exec {real} {here} --fake-count ;;
 feature_recovery_report.py) shift; exec {real} {here} --fake-report "$@" ;;
 *) exec {real} "$@" ;;
esac
''')
        curl=bin_dir/'curl';curl.write_text(f'#!/bin/bash\nexec {real} {here} --fake-curl "$@"\n')
        python.chmod(0o755);curl.chmod(0o755)
        state=base/'state.json';state.write_text(json.dumps(fixture(mode,healthy)))
        env={k:os.environ[k] for k in ('HOME','LANG','PYTHONPATH','PYTHONDONTWRITEBYTECODE') if k in os.environ}
        env.update(PATH=str(bin_dir)+os.pathsep+os.environ['PATH'],AUDIT_FEATURE_STATE=str(state),
                   FEATURE_LIMIT=str(budget),PROJECT_FILTER='AUDIT',WORKER_URL='https://audit.invalid',WORKER_API_KEY='synthetic')
        proc=subprocess.run(['bash','-e','-o','pipefail','-c',shell],cwd=scripts,env=env,text=True,capture_output=True,timeout=60)
        final=json.loads(state.read_text())
        return final,proc.returncode,proc.stdout+proc.stderr


def main():
    # Standing backlog (one quarantined note) + 4 healthy notes: healthy notes use the whole budget,
    # the job is GREEN, and the backlog is one ::warning:: with counts (D-153 / T4).
    progress,rc,out=run_shell('historical',4,4)
    assert rc==0, out
    assert progress['worker_calls']==2 and progress['model_calls']==24, (progress['worker_calls'],progress['model_calls'],out)
    completed={r['subject_id'] for r in progress['rows']['note_feature_answers'] if r['question_id']==A.DONE_MARKER_QUESTION}
    assert completed=={f'AUDIT_h{i}' for i in range(4)}, completed
    assert '::warning::features 恢复队列存量' in out and '已隔离 1 篇' in out and '::error::' not in out, out
    # Backlog only: nothing can progress → no worker call, no model spend, still green, still reported.
    only,rc,out=run_shell('historical',0,4)
    assert rc==0 and only['worker_calls']==0 and only['model_calls']==0, (rc,only['worker_calls'],out)
    assert '已隔离 1 篇' in out and '::error::' not in out, out
    # A NEW all-invalid batch in this run: red, the project stops, the chunk is not re-sent.
    fresh,rc,out=run_shell('new_invalid',6,6)
    assert rc==1 and fresh['worker_calls']==1 and fresh['model_calls']==64, (rc,fresh['worker_calls'],fresh['model_calls'],out)
    assert '模型题零有效' in out and len(fresh['rows']['feature_annotation_failures'])==2, out
    assert all(r['attempts']==1 for r in fresh['rows']['feature_annotation_failures'])
    # API failure: unchanged origin/main rule (first batch systemic → red), and no retry budget is consumed.
    api,rc,out=run_shell('api_failure',4,4)
    assert rc==1 and api['worker_calls']==1 and api['model_calls']>0, 'API failures must still stop the project'
    assert all(r['attempts']==0 or r['subject_id']=='AUDIT_blocked' for r in api['rows']['feature_annotation_failures'])
    # v1.26 not applied yet (code merged first): the count on stdout is still a bare number, so a finished
    # project stops after one batch instead of burning the whole budget on empty worker calls; the nightly
    # shows exactly one missing-migration annotation and stays green.
    bare,rc,out=run_shell('no_migration',1,24)
    assert rc==0, out
    assert bare['worker_calls']==1 and bare['model_calls']==6, (bare['worker_calls'],bare['model_calls'],out)
    assert '已全部抽完' in out and '::error::' not in out, out
    assert out.count('::warning title=迁移还没跑 (notes_v1_26)::')==1, out
    assert 'feature_annotation_failures' not in bare['rows']
    # Classifier: malformed / incomplete / old-worker output is always "other" (existing handling applies).
    done=lambda **k:'Done: '+json.dumps(dict(dict(ok=0,model_no_valid=0,retry_deferred=0,retry_quarantined=0),**k))
    assert classify(dict(ok=False,returncode=1,stdout_tail='Done: {}'),'0','200')[0]=='other'
    assert classify(dict(ok=True,returncode=0,stdout_tail=done(ok=2)),'0','200')[0]=='other'
    assert classify(dict(ok=True,returncode=0,stdout_tail=done(ok=2,retry_quarantined=3)),'0','200')==('backlog',2,0,3,0)
    assert classify(dict(ok=False,returncode=1,stdout_tail=done(ok=1,model_no_valid=1)),'0','200')==('model_invalid',1,0,0,1)
    assert classify(dict(ok=True,returncode=0,stdout_tail=done(retry_deferred=1)),'0','502')[0]=='other'
    assert classify(dict(ok=True,returncode=0,timed_out=True,stdout_tail=done(model_no_valid=1)),'0','200')[0]=='other'
    # backfill-features uses the same classifier in both loops and never re-sends a zero-valid chunk.
    backfill=(ROOT/'.github/workflows/backfill-features.yml').read_text()
    assert backfill.count('python feature_batch_state.py /tmp/b.json')==2, 'both backfill loops must classify the batch'
    for loop in backfill.split('for attempt in 1 2 3 4 5 6; do')[1:]:
        body=loop[:loop.index('sleep 60')]
        assert 'model_invalid' in body and 'break' in body[body.index('model_invalid'):], 'zero-valid chunk must leave the retry loop'
    assert 'python feature_recovery_report.py "$PROJECT"' in backfill
    print('features-sync real shell: standing backlog is a warning (green) and healthy notes use the full budget; '
          'backlog-only costs zero calls; a new zero-valid batch is red and not re-sent; without v1.26 a finished project stops after one batch; backfill uses the same classifier')
    return 0


if __name__=='__main__':
    raise SystemExit(fake_transport(sys.argv[1],sys.argv[2:]) if len(sys.argv)>1 else main())
