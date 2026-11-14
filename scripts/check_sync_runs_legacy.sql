-- PostgreSQL regression for the v1.25 legacy baseline (D-153). Needs scripts/seed_sync_runs_legacy.sql
-- to have run before the FIRST apply of schemas/notes_v1_25_sync_runs.sql; run this after the second
-- apply. Asserts, then deletes its synthetic rows (committed, so later CI steps see a clean database).
BEGIN;
DO $$
DECLARE v RECORD; stamp TIMESTAMPTZ;
BEGIN
    -- Applied twice: still exactly the two legacy runs, and none for a never-stamped project.
    IF (SELECT count(*) FROM truth_vault.note_sync_runs WHERE project_id='CI_V25_LEGACY') <> 2
       OR EXISTS(SELECT 1 FROM truth_vault.note_sync_runs WHERE project_id='CI_V25_LEGACY_ND') THEN
        RAISE EXCEPTION 'legacy baseline is not idempotent or invented a scan for a never-stamped project';
    END IF;
    -- Classification carried over exactly: only the note the latest legacy run did not see.
    IF (SELECT array_agg(note_id ORDER BY note_id) FROM truth_vault.v_notes_vanished
        WHERE project_id IN ('CI_V25_LEGACY','CI_V25_LEGACY_ND')) IS DISTINCT FROM ARRAY['CI_V25_LEGACY_gone'] THEN
        RAISE EXCEPTION 'legacy baseline changed which notes count as vanished';
    END IF;
    SELECT last_seen_at INTO stamp FROM truth_vault.notes WHERE note_id='CI_V25_LEGACY_gone';
    SELECT * INTO v FROM truth_vault.v_notes_vanished WHERE note_id='CI_V25_LEGACY_gone';
    -- The real last-seen time survives the migration (the desk's 36-hour grace reads this gap).
    IF v.last_seen_at IS DISTINCT FROM stamp OR v.last_seen_run_id <> 'legacy:older:CI_V25_LEGACY' THEN
        RAISE EXCEPTION 'legacy last_seen_at replaced by the migration clock: % vs %', v.last_seen_at, stamp;
    END IF;
    IF v.latest_seen_at - v.last_seen_at < interval '18 days' OR v.latest_seen_at - v.last_seen_at > interval '20 days' THEN
        RAISE EXCEPTION 'legacy gap lost: % (expected about 19 days)', v.latest_seen_at - v.last_seen_at;
    END IF;
    -- First real scan after the migration: the gap is still measured from the real stamp.
    PERFORM truth_vault.begin_note_sync('CI_V25_LEGACY','CI_V25_LEGACY_first');
    PERFORM truth_vault.complete_note_sync('CI_V25_LEGACY_first',ARRAY['CI_V25_LEGACY_live','CI_V25_LEGACY_never']);
    SELECT * INTO v FROM truth_vault.v_notes_vanished WHERE note_id='CI_V25_LEGACY_gone';
    IF v.last_seen_at IS DISTINCT FROM stamp OR v.latest_seen_at - v.last_seen_at < interval '18 days' THEN
        RAISE EXCEPTION 'gap collapsed after the first post-migration scan: %', v.latest_seen_at - v.last_seen_at;
    END IF;
    IF (SELECT count(*) FROM truth_vault.v_notes_vanished WHERE project_id='CI_V25_LEGACY') <> 1 THEN
        RAISE EXCEPTION 'first post-migration scan misclassified legacy notes';
    END IF;
    -- A note seen by a real (non-legacy) run reports that run's start, not a stale per-note stamp.
    PERFORM truth_vault.begin_note_sync('CI_V25_LEGACY','CI_V25_LEGACY_second');
    PERFORM truth_vault.complete_note_sync('CI_V25_LEGACY_second',ARRAY['CI_V25_LEGACY_never']);
    SELECT * INTO v FROM truth_vault.v_notes_vanished WHERE note_id='CI_V25_LEGACY_live';
    IF v.last_seen_run_id <> 'CI_V25_LEGACY_first'
       OR v.last_seen_at IS DISTINCT FROM (SELECT started_at FROM truth_vault.note_sync_runs WHERE run_id='CI_V25_LEGACY_first') THEN
        RAISE EXCEPTION 'non-legacy last_seen_at must be the run start';
    END IF;
END $$;
DELETE FROM truth_vault.note_sync_presence WHERE project_id IN ('CI_V25_LEGACY','CI_V25_LEGACY_ND');
DELETE FROM truth_vault.note_sync_runs WHERE project_id IN ('CI_V25_LEGACY','CI_V25_LEGACY_ND');
DELETE FROM truth_vault.notes WHERE project_id IN ('CI_V25_LEGACY','CI_V25_LEGACY_ND');
DELETE FROM truth_vault.projects WHERE project_id IN ('CI_V25_LEGACY','CI_V25_LEGACY_ND');
COMMIT;
