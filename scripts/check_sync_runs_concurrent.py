#!/usr/bin/env python3
"""Real two-session PostgreSQL completion race, only on disposable local CI DBs."""
import os
import subprocess
import time
import uuid


def main():
    if os.environ.get('PGHOST', '') not in ('', 'localhost', '127.0.0.1') or os.environ.get('PGDATABASE') not in ('tv_ci', 'tv_repair', 'tv_full_ci'):
        raise SystemExit('This regression requires a disposable local tv_ci/tv_repair/tv_full_ci database')
    cmd = ['psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1']
    tag = 'CI_V25_RACE_' + uuid.uuid4().hex[:10]
    older, newer, a, b = [tag+s for s in ('_old', '_new', '_a', '_b')]
    app = tag+'_waiting'
    def sql(text):
        res = subprocess.run(cmd, input=text, text=True, capture_output=True, timeout=15)
        if res.returncode:
            raise AssertionError(res.stderr)
        return res.stdout.strip()
    sql(f"INSERT INTO truth_vault.projects(project_id,brand,product,category) VALUES('{tag}','synthetic','synthetic','其他');"
        f"INSERT INTO truth_vault.notes(note_id,project_id,raw_content) VALUES('{a}','{tag}','synthetic'),('{b}','{tag}','synthetic');"
        f"SELECT truth_vault.begin_note_sync('{tag}','{older}');SELECT truth_vault.begin_note_sync('{tag}','{newer}');")
    holder = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    waiting = None
    try:
        holder.stdin.write(f"BEGIN; SELECT truth_vault.complete_note_sync('{newer}',ARRAY['{a}']);\n\\echo HELD\n")
        holder.stdin.flush()
        while holder.stdout.readline().strip() != 'HELD':
            if holder.poll() is not None:
                raise AssertionError(holder.stderr.read())
        waiting = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        waiting.stdin.write(f"SET application_name='{app}';SELECT truth_vault.complete_note_sync('{older}',ARRAY['{a}','{b}']);\n")
        waiting.stdin.close()
        for _ in range(50):
            if sql(f"SELECT count(*) FROM pg_stat_activity WHERE application_name='{app}' AND wait_event_type='Lock';") == '1':
                break
            time.sleep(.05)
        else:
            raise AssertionError('test did not actually overlap completion row locks')
        holder.stdin.write('COMMIT;\n'); holder.stdin.close()
        assert holder.wait(timeout=10) == 0, holder.stderr.read()
        assert waiting.wait(timeout=10) == 0, waiting.stderr.read()
        got = sql(f"SELECT note_id FROM truth_vault.v_notes_vanished WHERE project_id='{tag}' ORDER BY note_id;")
        assert got == b, f'late old completion changed latest membership: {got!r}'
        print('completed scan: real concurrent completions waited on row lock and retained newer snapshot')
    finally:
        if holder.poll() is None: holder.kill(); holder.wait()
        if waiting is not None and waiting.poll() is None: waiting.kill(); waiting.wait()
        sql(f"DELETE FROM truth_vault.note_sync_presence WHERE project_id='{tag}';DELETE FROM truth_vault.notes WHERE project_id='{tag}';DELETE FROM truth_vault.note_sync_runs WHERE project_id='{tag}';DELETE FROM truth_vault.projects WHERE project_id='{tag}';")


if __name__ == '__main__':
    main()
