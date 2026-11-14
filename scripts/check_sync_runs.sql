-- PostgreSQL behavior regression for v1.25. Synthetic records, rollback at end.
BEGIN;
INSERT INTO truth_vault.projects(project_id,brand,product,category)
VALUES('CI_V25','synthetic','synthetic','其他'),('CI_V25_OTHER','synthetic','synthetic','其他');
INSERT INTO truth_vault.notes(note_id,project_id,raw_content) VALUES
('CI_V25_a','CI_V25','synthetic'),('CI_V25_b','CI_V25','synthetic'),
('CI_V25_unknown','CI_V25','synthetic'),('CI_V25_other','CI_V25_OTHER','synthetic');
SELECT truth_vault.begin_note_sync('CI_V25','CI_V25_base');
SELECT truth_vault.complete_note_sync('CI_V25_base',ARRAY['CI_V25_a','CI_V25_b']);
SELECT truth_vault.complete_note_sync('CI_V25_base',ARRAY['CI_V25_b','CI_V25_a']); -- idempotent, order irrelevant
SELECT truth_vault.begin_note_sync('CI_V25','CI_V25_failed');
-- Simulate a partially written scan changing legacy stamps. This must not be deletion evidence.
UPDATE truth_vault.notes SET last_seen_run_id='CI_V25_failed',last_seen_at=clock_timestamp() WHERE note_id='CI_V25_a';
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM truth_vault.v_notes_vanished WHERE project_id='CI_V25') THEN
  RAISE EXCEPTION 'incomplete scan published';
 END IF;
 BEGIN
  PERFORM truth_vault.complete_note_sync('CI_V25_base',ARRAY['CI_V25_a','CI_V25_unknown']);
  RAISE EXCEPTION 'changed completed payload accepted';
 EXCEPTION WHEN OTHERS THEN
  IF SQLERRM='changed completed payload accepted' THEN RAISE; END IF;
 END;
END $$;
SELECT truth_vault.begin_note_sync('CI_V25','CI_V25_older');
SELECT truth_vault.begin_note_sync('CI_V25','CI_V25_newer');
SELECT truth_vault.complete_note_sync('CI_V25_newer',ARRAY['CI_V25_a']);
SELECT truth_vault.complete_note_sync('CI_V25_older',ARRAY['CI_V25_a','CI_V25_b']);
DO $$ BEGIN
 IF (SELECT array_agg(note_id ORDER BY note_id) FROM truth_vault.v_notes_vanished WHERE project_id='CI_V25')
    IS DISTINCT FROM ARRAY['CI_V25_b'] THEN RAISE EXCEPTION 'older completion superseded newer snapshot'; END IF;
END $$;
SELECT truth_vault.begin_note_sync('CI_V25','CI_V25_empty');
SELECT truth_vault.complete_note_sync('CI_V25_empty',ARRAY[]::TEXT[]);
SELECT truth_vault.begin_note_sync('CI_V25','CI_V25_bad_member');
DO $$ BEGIN
 IF (SELECT array_agg(note_id ORDER BY note_id) FROM truth_vault.v_notes_vanished WHERE project_id='CI_V25')
    IS DISTINCT FROM ARRAY['CI_V25_a','CI_V25_b'] THEN RAISE EXCEPTION 'empty scan or never-seen exclusion failed'; END IF;
 BEGIN
  PERFORM truth_vault.complete_note_sync('CI_V25_bad_member',ARRAY['CI_V25_other']);
  RAISE EXCEPTION 'cross-project member accepted';
 EXCEPTION WHEN OTHERS THEN
  IF SQLERRM='cross-project member accepted' THEN RAISE; END IF;
 END;
 IF (SELECT completed_at FROM truth_vault.note_sync_runs WHERE run_id='CI_V25_bad_member') IS NOT NULL THEN
  RAISE EXCEPTION 'failed completion partially advanced'; END IF;
END $$;
-- Force failure AFTER presence writes, proving statement rollback covers both tables.
CREATE FUNCTION public.ci_v25_reject_completion() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN IF NEW.run_id='CI_V25_rollback' THEN RAISE EXCEPTION 'injected completion error'; END IF; RETURN NEW; END $$;
CREATE TRIGGER ci_v25_reject BEFORE UPDATE ON truth_vault.note_sync_runs
 FOR EACH ROW EXECUTE FUNCTION public.ci_v25_reject_completion();
SELECT truth_vault.begin_note_sync('CI_V25','CI_V25_rollback');
DO $$ BEGIN
 BEGIN
  PERFORM truth_vault.complete_note_sync('CI_V25_rollback',ARRAY['CI_V25_a']);
  RAISE EXCEPTION 'injected completion failure not raised';
 EXCEPTION WHEN OTHERS THEN
  IF SQLERRM <> 'injected completion error' THEN RAISE; END IF;
 END;
 IF (SELECT completed_at FROM truth_vault.note_sync_runs WHERE run_id='CI_V25_rollback') IS NOT NULL
 OR (SELECT array_agg(note_id ORDER BY note_id) FROM truth_vault.v_notes_vanished WHERE project_id='CI_V25')
    IS DISTINCT FROM ARRAY['CI_V25_a','CI_V25_b'] THEN RAISE EXCEPTION 'completion rollback leaked membership'; END IF;
END $$;
DO $$ DECLARE role_name TEXT;
BEGIN
 FOREACH role_name IN ARRAY ARRAY['anon','authenticated'] LOOP
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=role_name) AND (
    has_function_privilege(role_name,'truth_vault.begin_note_sync(text,text)','EXECUTE') OR
    has_function_privilege(role_name,'truth_vault.complete_note_sync(text,text[],text[])','EXECUTE')) THEN
    RAISE EXCEPTION 'untrusted role can publish scans: %',role_name;
  END IF;
 END LOOP;
END $$;
-- A malformed/new source row is observation evidence even before its business
-- note exists. Preserve D-058 while preventing the existence-probe race.
INSERT INTO truth_vault.projects(project_id,brand,product,category)
VALUES('CI_V25_RACE_FAILED','synthetic','synthetic','其他');
INSERT INTO truth_vault.notes(note_id,project_id,raw_content)
VALUES('CI_V25_RACE_FAILED_a','CI_V25_RACE_FAILED','synthetic');
SELECT truth_vault.begin_note_sync('CI_V25_RACE_FAILED','CI_V25_FAILED_old1');
SELECT truth_vault.begin_note_sync('CI_V25_RACE_FAILED','CI_V25_FAILED_new1');
SELECT truth_vault.complete_note_sync('CI_V25_FAILED_new1',ARRAY['CI_V25_RACE_FAILED_a'],ARRAY['CI_V25_RACE_FAILED_bad1']);
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM truth_vault.note_sync_presence WHERE note_id='CI_V25_RACE_FAILED_bad1')
 OR (SELECT seen_count FROM truth_vault.note_sync_runs WHERE run_id='CI_V25_FAILED_new1') <> 2 THEN
  RAISE EXCEPTION 'failed observation was lost before note insertion'; END IF;
END $$;
INSERT INTO truth_vault.notes(note_id,project_id,raw_content)
VALUES('CI_V25_RACE_FAILED_bad1','CI_V25_RACE_FAILED','synthetic');
SELECT truth_vault.complete_note_sync('CI_V25_FAILED_old1',ARRAY['CI_V25_RACE_FAILED_a','CI_V25_RACE_FAILED_bad1']);
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM truth_vault.v_notes_vanished WHERE project_id='CI_V25_RACE_FAILED') THEN
  RAISE EXCEPTION 'older insertion after newer completion became false deletion'; END IF;
END $$;
SELECT truth_vault.begin_note_sync('CI_V25_RACE_FAILED','CI_V25_FAILED_old2');
SELECT truth_vault.begin_note_sync('CI_V25_RACE_FAILED','CI_V25_FAILED_new2');
INSERT INTO truth_vault.notes(note_id,project_id,raw_content)
VALUES('CI_V25_RACE_FAILED_bad2','CI_V25_RACE_FAILED','synthetic');
SELECT truth_vault.complete_note_sync('CI_V25_FAILED_old2',ARRAY['CI_V25_RACE_FAILED_a','CI_V25_RACE_FAILED_bad1','CI_V25_RACE_FAILED_bad2']);
SELECT truth_vault.complete_note_sync('CI_V25_FAILED_new2',ARRAY['CI_V25_RACE_FAILED_a','CI_V25_RACE_FAILED_bad1'],ARRAY['CI_V25_RACE_FAILED_bad2']);
DO $$ DECLARE bad TEXT[];
BEGIN
 IF EXISTS(SELECT 1 FROM truth_vault.v_notes_vanished WHERE project_id='CI_V25_RACE_FAILED') THEN
  RAISE EXCEPTION 'older insertion before newer completion became false deletion'; END IF;
 FOR bad IN SELECT ARRAY['wrong_project_id'] UNION ALL SELECT ARRAY['CI_V25_new',NULL]
            UNION ALL SELECT ARRAY['CI_V25_new','CI_V25_new'] LOOP
  BEGIN
   PERFORM truth_vault.complete_note_sync('CI_V25_bad_member',ARRAY[]::TEXT[],bad);
   RAISE EXCEPTION 'invalid failed observation accepted';
  EXCEPTION WHEN OTHERS THEN
   IF SQLERRM='invalid failed observation accepted' THEN RAISE; END IF;
  END;
 END LOOP;
 IF to_regprocedure('truth_vault.complete_note_sync(text,text[])') IS NOT NULL THEN
  RAISE EXCEPTION 'obsolete overload left behind'; END IF;
END $$;
ROLLBACK;
