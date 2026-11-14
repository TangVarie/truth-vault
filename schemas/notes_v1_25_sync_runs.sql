-- v1.25: trustworthy completed Feishu scans, including an empty scan (audit F04, D-153).
-- Apply after v1.21, once, any time AFTER the code that writes the ledger is merged: until then
-- that code finds these objects missing, warns and keeps the pre-v1.25 behaviour. Safe to re-run.
-- Do not apply it before that merge: nothing errors or turns red, but this file switches
-- v_notes_vanished to the ledger while older code never commits a new scan, so the vanished
-- list stops updating until the merge plus one completed full sync.
-- No production execution is performed by application deploys.
-- Legacy last_seen columns remain diagnostic only. Completion and membership commit
-- atomically; run_seq is allocated BEFORE fetching, so a late older run cannot
-- supersede a newer completed scan or overwrite its membership.
BEGIN;
CREATE TABLE IF NOT EXISTS truth_vault.note_sync_runs (
    run_seq BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    project_id TEXT NOT NULL REFERENCES truth_vault.projects(project_id),
    started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    completed_at TIMESTAMPTZ,
    seen_count INTEGER,
    members_sha TEXT,
    CHECK ((completed_at IS NULL AND seen_count IS NULL)
        OR (completed_at IS NOT NULL AND seen_count >= 0))
);
CREATE INDEX IF NOT EXISTS note_sync_runs_completed_idx
    ON truth_vault.note_sync_runs(project_id, run_seq DESC) WHERE completed_at IS NOT NULL;
CREATE TABLE IF NOT EXISTS truth_vault.note_sync_presence (
    note_id TEXT PRIMARY KEY, -- source observation may precede a successful note write
    project_id TEXT NOT NULL REFERENCES truth_vault.projects(project_id),
    last_seen_run_seq BIGINT NOT NULL REFERENCES truth_vault.note_sync_runs(run_seq)
);
-- Upgrade an earlier candidate too: this is source-observation metadata, not a
-- notes child. An observed failed row may be inserted by an older concurrent run.
ALTER TABLE truth_vault.note_sync_presence DROP CONSTRAINT IF EXISTS note_sync_presence_note_id_fkey;
CREATE INDEX IF NOT EXISTS note_sync_presence_project_idx
    ON truth_vault.note_sync_presence(project_id, last_seen_run_seq);
ALTER TABLE truth_vault.note_sync_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE truth_vault.note_sync_presence ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON truth_vault.note_sync_runs, truth_vault.note_sync_presence FROM PUBLIC;

CREATE OR REPLACE FUNCTION truth_vault.begin_note_sync(p_project_id TEXT, p_run_id TEXT)
RETURNS BIGINT LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE r truth_vault.note_sync_runs;
BEGIN
    IF p_run_id IS NULL OR length(p_run_id) = 0 THEN RAISE EXCEPTION 'run_id required'; END IF;
    INSERT INTO truth_vault.note_sync_runs(run_id, project_id)
        VALUES(p_run_id, p_project_id) ON CONFLICT(run_id) DO NOTHING;
    SELECT * INTO STRICT r FROM truth_vault.note_sync_runs WHERE run_id = p_run_id;
    IF r.project_id <> p_project_id THEN RAISE EXCEPTION 'run project mismatch'; END IF;
    RETURN r.run_seq;
END $$;

DROP FUNCTION IF EXISTS truth_vault.complete_note_sync(TEXT,TEXT[]);
CREATE OR REPLACE FUNCTION truth_vault.complete_note_sync(
    p_run_id TEXT, p_note_ids TEXT[], p_seen_failed_note_ids TEXT[] DEFAULT ARRAY[]::TEXT[]
)
RETURNS BIGINT LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE r truth_vault.note_sync_runs; expected INTEGER; actual INTEGER; payload_sha TEXT; observed TEXT[];
BEGIN
    SELECT * INTO STRICT r FROM truth_vault.note_sync_runs WHERE run_id = p_run_id FOR UPDATE;
    IF p_note_ids IS NULL THEN RAISE EXCEPTION 'complete scan membership required (empty array allowed)'; END IF;
    SELECT count(DISTINCT id) INTO expected FROM unnest(p_note_ids) id;
    IF expected <> cardinality(p_note_ids) THEN RAISE EXCEPTION 'duplicate/null member'; END IF;
    SELECT count(*) INTO actual FROM truth_vault.notes
        WHERE project_id = r.project_id AND note_id = ANY(p_note_ids);
    IF actual <> expected THEN RAISE EXCEPTION 'scan members missing or in another project'; END IF;
    IF p_seen_failed_note_ids IS NULL THEN RAISE EXCEPTION 'failed observations must be an array'; END IF;
    SELECT count(DISTINCT id) INTO actual FROM unnest(p_seen_failed_note_ids) id;
    IF actual <> cardinality(p_seen_failed_note_ids) OR EXISTS(
        SELECT 1 FROM unnest(p_seen_failed_note_ids) id
        WHERE left(id,length(r.project_id)+1) <> r.project_id || '_'
           OR length(id) <= length(r.project_id)+1
    ) THEN RAISE EXCEPTION 'invalid failed-observation member'; END IF;
    IF EXISTS(SELECT 1 FROM truth_vault.notes WHERE note_id=ANY(p_seen_failed_note_ids) AND project_id<>r.project_id) THEN
        RAISE EXCEPTION 'failed observation belongs to another project';
    END IF;
    SELECT ARRAY(SELECT DISTINCT id FROM unnest(p_note_ids || p_seen_failed_note_ids) id ORDER BY id) INTO observed;
    expected := cardinality(observed);
    SELECT md5(array_to_json(array_agg(id ORDER BY id))::text) INTO payload_sha FROM unnest(observed) id;
    payload_sha := coalesce(payload_sha, md5('[]'));
    IF r.completed_at IS NOT NULL THEN
        IF r.seen_count <> expected OR r.members_sha IS DISTINCT FROM payload_sha THEN RAISE EXCEPTION 'completed scan membership changed'; END IF;
        RETURN r.run_seq; -- retry after a lost HTTP response; completion is idempotent
    END IF;
    INSERT INTO truth_vault.note_sync_presence(note_id, project_id, last_seen_run_seq)
        SELECT id, r.project_id, r.run_seq FROM unnest(observed) id
        ON CONFLICT(note_id) DO UPDATE SET last_seen_run_seq = greatest(
            truth_vault.note_sync_presence.last_seen_run_seq, EXCLUDED.last_seen_run_seq);
    UPDATE truth_vault.note_sync_runs SET completed_at = clock_timestamp(), seen_count = expected, members_sha = payload_sha
        WHERE run_seq = r.run_seq;
    RETURN r.run_seq;
END $$;
REVOKE ALL ON FUNCTION truth_vault.begin_note_sync(TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION truth_vault.complete_note_sync(TEXT,TEXT[],TEXT[]) FROM PUBLIC;
DO $$ DECLARE role_name TEXT;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
            EXECUTE format('REVOKE ALL ON truth_vault.note_sync_runs, truth_vault.note_sync_presence FROM %I',role_name);
            EXECUTE format('REVOKE ALL ON FUNCTION truth_vault.begin_note_sync(TEXT,TEXT), truth_vault.complete_note_sync(TEXT,TEXT[],TEXT[]) FROM %I',role_name);
        END IF;
    END LOOP;
    IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
        GRANT SELECT ON truth_vault.note_sync_runs, truth_vault.note_sync_presence TO service_role;
        GRANT EXECUTE ON FUNCTION truth_vault.begin_note_sync(TEXT,TEXT), truth_vault.complete_note_sync(TEXT,TEXT[],TEXT[]) TO service_role;
    END IF;
END $$;

-- Preserve the legacy view's existing classifications at upgrade. This does not
-- invent evidence for never-seen notes or reconstruct old failed/empty scans.
-- A new successful full scan is the first authoritative post-upgrade snapshot.
-- The two legacy runs carry the real stamp times (not the migration clock), and the
-- view below reports a legacy-seen note's own notes.last_seen_at: the desk's 36-hour
-- grace test reads latest_seen_at - last_seen_at and must not see a zero gap.
DO $$ DECLARE p RECORD; older BIGINT; current_seq BIGINT;
BEGIN
    FOR p IN
        SELECT DISTINCT ON(n.project_id) n.project_id,n.last_seen_run_id,n.last_seen_at
        FROM truth_vault.notes n
        WHERE n.last_seen_run_id IS NOT NULL AND NOT EXISTS(
            SELECT 1 FROM truth_vault.note_sync_runs r WHERE r.project_id=n.project_id)
        ORDER BY n.project_id,n.last_seen_at DESC,n.note_id
    LOOP
        INSERT INTO truth_vault.note_sync_runs(run_id,project_id,started_at,completed_at,seen_count)
            VALUES('legacy:older:'||p.project_id,p.project_id,
                coalesce((SELECT min(last_seen_at) FROM truth_vault.notes WHERE project_id=p.project_id AND last_seen_run_id IS NOT NULL AND last_seen_run_id<>p.last_seen_run_id),p.last_seen_at),
                clock_timestamp(),
                (SELECT count(*) FROM truth_vault.notes WHERE project_id=p.project_id AND last_seen_run_id IS NOT NULL AND last_seen_run_id<>p.last_seen_run_id)) RETURNING run_seq INTO older;
        INSERT INTO truth_vault.note_sync_runs(run_id,project_id,started_at,completed_at,seen_count)
            VALUES('legacy:current:'||p.project_id,p.project_id,p.last_seen_at,clock_timestamp(),
                (SELECT count(*) FROM truth_vault.notes WHERE project_id=p.project_id AND last_seen_run_id=p.last_seen_run_id))
            RETURNING run_seq INTO current_seq;
        INSERT INTO truth_vault.note_sync_presence(note_id,project_id,last_seen_run_seq)
            SELECT note_id,project_id,CASE WHEN last_seen_run_id=p.last_seen_run_id THEN current_seq ELSE older END
            FROM truth_vault.notes WHERE project_id=p.project_id AND last_seen_run_id IS NOT NULL;
    END LOOP;
END $$;

CREATE OR REPLACE VIEW truth_vault.v_notes_vanished AS
WITH latest AS (
    SELECT DISTINCT ON(project_id) project_id,run_seq,run_id,started_at
    FROM truth_vault.note_sync_runs WHERE completed_at IS NOT NULL
    ORDER BY project_id,run_seq DESC
)
SELECT n.note_id,n.project_id,n.tier,n.publish_url,
    seen.run_id AS last_seen_run_id,
    CASE WHEN seen.run_id LIKE 'legacy:%' THEN n.last_seen_at ELSE seen.started_at END AS last_seen_at,
    latest.run_id AS latest_run_id,latest.started_at AS latest_seen_at,
    n.synced_to_ssll_at,n.synced_to_aw_at,n.essence_annotated_at,
    EXISTS(SELECT 1 FROM truth_vault.flywheel_lesson_annotations c WHERE c.note_id=n.note_id) AS has_lesson_card
FROM truth_vault.notes n
JOIN truth_vault.note_sync_presence presence ON presence.note_id=n.note_id AND presence.project_id=n.project_id
JOIN truth_vault.note_sync_runs seen ON seen.run_seq=presence.last_seen_run_seq AND seen.completed_at IS NOT NULL
JOIN latest ON latest.project_id=n.project_id
WHERE presence.last_seen_run_seq < latest.run_seq;
COMMENT ON VIEW truth_vault.v_notes_vanished IS
    'Absent from latest COMPLETED full scan (v1.25). Empty scans advance; incomplete scans do not. Never-confirmed notes excluded.';
COMMIT;
