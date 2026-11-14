-- v1.26 · F03 (D-153): bounded feature annotation recovery and atomic preservation of valid answers.
-- Apply after v1.13/v1.17, once, at any time relative to the code merge: a worker that finds these
-- objects missing warns once and annotates as it did before v1.26. Safe to re-run.
-- No model calls. Historical all-invalid snapshots are queued, not deleted: each queued note is
-- re-annotated (paid) once by the following nightlies, within the nightly budget.
BEGIN;
CREATE TABLE IF NOT EXISTS truth_vault.feature_annotation_failures (
    id BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
    subject_id TEXT NOT NULL REFERENCES truth_vault.notes(note_id) ON DELETE CASCADE,
    project_id TEXT NOT NULL,
    bank_sha256 TEXT NOT NULL,
    extractor TEXT NOT NULL,
    run_tag TEXT NOT NULL,
    claim_token UUID NOT NULL DEFAULT gen_random_uuid(),
    attempts INT NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_retry_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error TEXT NOT NULL DEFAULT 'pending',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (subject_id, bank_sha256, extractor, run_tag)
);
ALTER TABLE truth_vault.feature_annotation_failures ENABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS idx_feature_annotation_failures_project
    ON truth_vault.feature_annotation_failures (project_id,bank_sha256,extractor,run_tag);
REVOKE ALL ON truth_vault.feature_annotation_failures FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON truth_vault.feature_annotation_failures TO service_role;
GRANT USAGE, SELECT ON SEQUENCE truth_vault.feature_annotation_failures_id_seq TO service_role;

-- Old versions used marker presence even when every model answer was invalid.
-- Exclude genuine no-input/not-applicable snapshots. Idempotent: never reset existing attempts.
INSERT INTO truth_vault.feature_annotation_failures
    (subject_id, project_id, bank_sha256, extractor, run_tag, last_error)
SELECT a.subject_id, n.project_id, a.bank_sha256, a.extractor, a.run_tag, 'legacy_all_invalid'
FROM truth_vault.note_feature_answers a
JOIN truth_vault.notes n ON n.note_id = a.subject_id
WHERE a.subject_type = 'note' AND a.extractor LIKE 'llm:%'
  -- Already answered under another model label for the same snapshot: not a failure. Without
  -- this, re-running the file would re-queue (and re-pay) notes the queue has already cleared.
  AND NOT EXISTS (
      SELECT 1 FROM truth_vault.note_feature_answers v
      WHERE v.subject_type = 'note' AND v.subject_id = a.subject_id AND v.bank_sha256 = a.bank_sha256
        AND v.run_tag = a.run_tag AND v.extractor LIKE 'llm:%' AND v.answer IS NOT NULL)
GROUP BY a.subject_id, n.project_id, a.bank_sha256, a.extractor, a.run_tag
HAVING NOT bool_or(a.answer IS NOT NULL)
   AND bool_or(a.question_id IN ('has_specific_time', 'reader_ask_form'))
   AND bool_or(a.invalid_reason IN ('json_parse_failed','missing','evidence_not_found','out_of_vocab','gateway_filtered'))
ON CONFLICT (subject_id, bank_sha256, extractor, run_tag) DO NOTHING;

-- Reserve before paying for inference. A claim is a 20-hour lease and does NOT consume
-- an attempt: only finish(..., p_consume => true), i.e. "the model was asked and every
-- answer was invalid", does. A killed worker leaves last_error='in_progress'; the lease
-- simply runs out and the next nightly may claim again with the budget untouched.
-- After a counted failure the row waits about 20h, then about 44h (the nightly runs every
-- 24h, so the next / the one after next nightly is eligible); after the third counted
-- failure only an explicit replay is allowed.
CREATE OR REPLACE FUNCTION truth_vault.claim_feature_annotation_attempt(
    p_subject_id TEXT, p_project_id TEXT, p_bank_sha256 TEXT,
    p_extractor TEXT, p_run_tag TEXT, p_replay BOOLEAN DEFAULT false
) RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE claimed UUID;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM truth_vault.notes WHERE note_id=p_subject_id AND project_id=p_project_id) THEN
        RAISE EXCEPTION 'feature subject/project mismatch';
    END IF;
    INSERT INTO truth_vault.feature_annotation_failures AS f
        (subject_id, project_id, bank_sha256, extractor, run_tag, attempts, next_retry_at, last_error)
    VALUES (p_subject_id, p_project_id, p_bank_sha256, p_extractor, p_run_tag, 0, now()+interval '20 hours', 'in_progress')
    ON CONFLICT (subject_id, bank_sha256, extractor, run_tag) DO UPDATE
       SET next_retry_at=now()+interval '20 hours',
           claim_token=gen_random_uuid(), last_error='in_progress', updated_at=now()
     WHERE p_replay OR (f.attempts<3 AND f.next_retry_at<=now())
    RETURNING claim_token INTO claimed;
    RETURN claimed;
END $$;

-- An earlier candidate of this file had a 7-argument finish; keep one signature only.
DROP FUNCTION IF EXISTS truth_vault.finish_feature_annotation_attempt(TEXT,TEXT,TEXT,TEXT,UUID,BOOLEAN,TEXT);
-- p_success: the note is answered. Clear the claimed row AND every queue row of the same
--   subject + bank sha + run_tag under any model label ('llm:%', the nightly's done-rule).
--   Otherwise a legacy row imported under an older model label would keep the note
--   "not done" forever and it would be re-annotated (paid) every night.
-- NOT p_success, p_consume: counted failure (every model answer invalid) -> attempts+1, back off.
-- NOT p_success, NOT p_consume: infrastructure failure (API error, write rejected, hygiene
--   abort) -> release the lease now, attempts untouched.
-- Only the holder of the current claim_token may change anything.
CREATE OR REPLACE FUNCTION truth_vault.finish_feature_annotation_attempt(
    p_subject_id TEXT, p_bank_sha256 TEXT, p_extractor TEXT, p_run_tag TEXT,
    p_claim_token UUID, p_success BOOLEAN, p_error TEXT DEFAULT '', p_consume BOOLEAN DEFAULT false
) RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    IF p_success THEN
        DELETE FROM truth_vault.feature_annotation_failures
         WHERE subject_id=p_subject_id AND bank_sha256=p_bank_sha256 AND extractor=p_extractor
           AND run_tag=p_run_tag AND claim_token=p_claim_token;
        IF FOUND AND p_extractor LIKE 'llm:%' THEN
            DELETE FROM truth_vault.feature_annotation_failures
             WHERE subject_id=p_subject_id AND bank_sha256=p_bank_sha256 AND run_tag=p_run_tag
               AND extractor LIKE 'llm:%';
        END IF;
    ELSIF p_consume THEN
        UPDATE truth_vault.feature_annotation_failures
           SET attempts=attempts+1,
               next_retry_at=now()+CASE WHEN attempts=0 THEN interval '20 hours' ELSE interval '44 hours' END,
               last_error=left(p_error,100), updated_at=now()
         WHERE subject_id=p_subject_id AND bank_sha256=p_bank_sha256 AND extractor=p_extractor
           AND run_tag=p_run_tag AND claim_token=p_claim_token;
    ELSE
        UPDATE truth_vault.feature_annotation_failures
           SET next_retry_at=now(), last_error=left(p_error,100), updated_at=now()
         WHERE subject_id=p_subject_id AND bank_sha256=p_bank_sha256 AND extractor=p_extractor
           AND run_tag=p_run_tag AND claim_token=p_claim_token;
    END IF;
END $$;

-- One statement/transaction: an invalid reannotation cannot overwrite an existing valid answer,
-- even if another annotator writes the valid answer between the caller's read and this RPC.
CREATE OR REPLACE FUNCTION truth_vault.write_feature_answers_preserving_valid(p_rows JSONB)
RETURNS INT LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE changed INT;
BEGIN
    IF jsonb_typeof(p_rows) <> 'array' THEN RAISE EXCEPTION 'feature rows must be an array'; END IF;
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(p_rows) r WHERE r->>'subject_type' IS DISTINCT FROM 'note') THEN
        RAISE EXCEPTION 'feature writer only accepts note subjects';
    END IF;
    INSERT INTO truth_vault.note_feature_answers AS old
        (subject_type,subject_id,question_id,question_version,bank_version,bank_sha256,
         extractor,run_tag,answer,evidence,prob,invalid_reason,extracted_at)
    SELECT subject_type,subject_id,question_id,question_version,bank_version,bank_sha256,
           extractor,run_tag,answer,evidence,prob,invalid_reason,coalesce(extracted_at,now())
    FROM jsonb_populate_recordset(NULL::truth_vault.note_feature_answers,p_rows)
    ON CONFLICT (subject_type,subject_id,question_id,question_version,extractor,run_tag)
    DO UPDATE SET bank_version=excluded.bank_version, bank_sha256=excluded.bank_sha256,
                  answer=excluded.answer, evidence=excluded.evidence, prob=excluded.prob,
                  invalid_reason=excluded.invalid_reason, extracted_at=excluded.extracted_at
    WHERE excluded.answer IS NOT NULL OR old.answer IS NULL;
    GET DIAGNOSTICS changed = ROW_COUNT;
    RETURN changed;
END $$;

REVOKE ALL ON FUNCTION truth_vault.claim_feature_annotation_attempt(TEXT,TEXT,TEXT,TEXT,TEXT,BOOLEAN) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION truth_vault.finish_feature_annotation_attempt(TEXT,TEXT,TEXT,TEXT,UUID,BOOLEAN,TEXT,BOOLEAN) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION truth_vault.write_feature_answers_preserving_valid(JSONB) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION truth_vault.claim_feature_annotation_attempt(TEXT,TEXT,TEXT,TEXT,TEXT,BOOLEAN) TO service_role;
GRANT EXECUTE ON FUNCTION truth_vault.finish_feature_annotation_attempt(TEXT,TEXT,TEXT,TEXT,UUID,BOOLEAN,TEXT,BOOLEAN) TO service_role;
GRANT EXECUTE ON FUNCTION truth_vault.write_feature_answers_preserving_valid(JSONB) TO service_role;
COMMIT;
