#!/usr/bin/env python3
"""Run the real workflow shell loop with worker I/O executing real annotation main.

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
    if mode != 'new_invalid':
        store.rows['notes'].insert(0, dict(base, note_id='AUDIT_blocked'))
        store.rows['feature_annotation_failures'] = [dict(id=1,subject_id='AUDIT_blocked',project_id='AUDIT',
            bank_sha256=F.load_bank()['_sha256'],extractor='llm:synthetic',run_tag='primary',attempts=3,
            next_retry_at='2999-01-01T00:00:00+00:00',last_error='all_model_answers_invalid')]
    return dict(rows=store.rows, mode=mode, model_calls=0, worker_calls=0)


def fake_transport(kind, args):
    path = Path(os.environ['AUDIT_FEATURE_STATE'])
    state = json.loads(path.read_text())
    store = Store(); store.rows = state['rows']
    if kind == '--fake-count':
        done = A.fetch_done_ids(store, 'AUDIT')
        print(len({n['note_id'] for n in store.rows['notes']} - done))
        return 0
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
        assert proc.returncode==1, proc.stdout+proc.stderr
        if mode != 'api_failure':
            assert '::error::features 恢复仍未完成' in proc.stdout, proc.stdout+proc.stderr
        return final,proc.stdout


def main():
    progress,out=run_shell('historical',4,4)
    assert progress['worker_calls']==2 and progress['model_calls']==24, (progress['worker_calls'],progress['model_calls'],out)
    completed={r['subject_id'] for r in progress['rows']['note_feature_answers'] if r['question_id']==A.DONE_MARKER_QUESTION}
    assert completed=={f'AUDIT_h{i}' for i in range(4)}, completed
    only,_=run_shell('historical',0,4)
    assert only['worker_calls']==1 and only['model_calls']==0
    fresh,_=run_shell('new_invalid',6,6)
    assert fresh['worker_calls']==1 and fresh['model_calls']==64, (fresh['worker_calls'],fresh['model_calls'])
    api,_=run_shell('api_failure',4,4)
    assert api['worker_calls']==1 and api['model_calls']>0, 'API failures must still stop the project'
    # A malformed/incomplete worker response can never obtain the continue classification.
    assert classify(dict(ok=False,returncode=1,stdout_tail='Done: {}'),'0','200',2)[0]=='other'
    print('features-sync real shell: historical quarantine permits full healthy budget but stays red; quarantine-only costs zero; new invalid batch stops')
    return 0


if __name__=='__main__':
    raise SystemExit(fake_transport(sys.argv[1],sys.argv[2:]) if len(sys.argv)>1 else main())
