-- PostgreSQL regression for the v1.26 legacy import (D-153). Needs
-- scripts/seed_feature_recovery_legacy.sql to have run before the FIRST apply of
-- schemas/notes_v1_26_feature_failure_recovery.sql; run this after the second apply.
-- Asserts, then deletes its synthetic rows (committed).
BEGIN;
DO $$
DECLARE tok UUID;
BEGIN
    -- Only the all-invalid snapshot is queued; applied twice it is still one row with a fresh budget.
    IF (SELECT array_agg(subject_id || '|' || extractor || '|' || attempts || '|' || last_error ORDER BY subject_id)
        FROM truth_vault.feature_annotation_failures WHERE project_id='CI_V26_LEGACY')
       IS DISTINCT FROM ARRAY['CI_V26_LEGACY_bad|llm:ci-old|0|legacy_all_invalid'] THEN
        RAISE EXCEPTION 'legacy import queued the wrong snapshots: %',
            (SELECT array_agg(subject_id || '|' || extractor) FROM truth_vault.feature_annotation_failures WHERE project_id='CI_V26_LEGACY');
    END IF;
    -- The worker now runs under another model label. Its success must clear the legacy row too,
    -- otherwise the note stays "not done" and is re-annotated (paid) every night.
    tok := truth_vault.claim_feature_annotation_attempt('CI_V26_LEGACY_bad','CI_V26_LEGACY','ci-sha','llm:ci-new','primary');
    IF tok IS NULL THEN RAISE EXCEPTION 'claim under the current model label failed'; END IF;
    IF (SELECT count(*) FROM truth_vault.feature_annotation_failures WHERE subject_id='CI_V26_LEGACY_bad') <> 2 THEN
        RAISE EXCEPTION 'expected the legacy row and the claimed row';
    END IF;
    INSERT INTO truth_vault.note_feature_answers
        (subject_type,subject_id,question_id,question_version,bank_version,bank_sha256,extractor,run_tag,answer)
    VALUES ('note','CI_V26_LEGACY_bad','has_specific_time',1,'ci','ci-sha','llm:ci-new','primary','否');
    PERFORM truth_vault.finish_feature_annotation_attempt('CI_V26_LEGACY_bad','ci-sha','llm:ci-new','primary',tok,true,'');
    IF EXISTS(SELECT 1 FROM truth_vault.feature_annotation_failures WHERE subject_id='CI_V26_LEGACY_bad') THEN
        RAISE EXCEPTION 'success under another model label left a queue row behind (endless nightly re-annotation)';
    END IF;
END $$;
COMMIT;
-- Re-running the migration after the queue has been cleared must not re-queue (and re-pay) the note:
-- the old all-NULL rows are still in note_feature_answers, but the snapshot is answered now.
\ir ../schemas/notes_v1_26_feature_failure_recovery.sql
BEGIN;
DO $$
BEGIN
    IF EXISTS(SELECT 1 FROM truth_vault.feature_annotation_failures WHERE project_id='CI_V26_LEGACY') THEN
        RAISE EXCEPTION 're-running v1.26 re-queued an already answered note';
    END IF;
END $$;
DELETE FROM truth_vault.note_feature_answers WHERE subject_id LIKE 'CI\_V26\_LEGACY\_%';
DELETE FROM truth_vault.notes WHERE project_id='CI_V26_LEGACY';
DELETE FROM truth_vault.projects WHERE project_id='CI_V26_LEGACY';
COMMIT;
