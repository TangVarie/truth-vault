-- Local PostgreSQL regression, synthetic fixtures only. Run after v1.26; rolls back all rows.
-- D-153: a claim is a lease and consumes nothing; only a counted failure (p_consume) does; back-off 20h / 44h;
-- a success clears the queue rows of the same snapshot under every llm:* label.
BEGIN;
INSERT INTO truth_vault.projects (project_id,brand,product,category,platform)
VALUES ('AUDIT_F03','synthetic','synthetic','其他','xiaohongshu');
INSERT INTO truth_vault.notes (note_id,project_id,platform,raw_content)
VALUES ('AUDIT_F03_n','AUDIT_F03','xiaohongshu','synthetic feature recovery fixture');
DO $$
DECLARE a UUID; b UUID; first_claim UUID; payload JSONB; written INT; r RECORD;
BEGIN
    a := truth_vault.claim_feature_annotation_attempt('AUDIT_F03_n','AUDIT_F03','audit-sha','llm:audit','audit');
    IF a IS NULL THEN RAISE EXCEPTION 'first claim failed'; END IF;
    first_claim := a;
    b := truth_vault.claim_feature_annotation_attempt('AUDIT_F03_n','AUDIT_F03','audit-sha','llm:audit','audit');
    IF b IS NOT NULL THEN RAISE EXCEPTION 'same snapshot can be claimed twice while the lease is held'; END IF;
    -- A claim alone (a worker killed mid-run leaves exactly this) consumes nothing and expires by itself.
    SELECT * INTO r FROM truth_vault.feature_annotation_failures WHERE subject_id='AUDIT_F03_n';
    IF r.attempts <> 0 OR r.last_error <> 'in_progress'
       OR r.next_retry_at NOT BETWEEN now()+interval '19 hours' AND now()+interval '21 hours' THEN
        RAISE EXCEPTION 'claim must be a ~20h lease that consumes no attempt: % % %', r.attempts, r.last_error, r.next_retry_at;
    END IF;
    -- Infrastructure failures release the claim at once and consume nothing, however often they happen.
    FOR i IN 1..5 LOOP
        PERFORM truth_vault.finish_feature_annotation_attempt('AUDIT_F03_n','audit-sha','llm:audit','audit',a,false,'systemic');
        SELECT * INTO r FROM truth_vault.feature_annotation_failures WHERE subject_id='AUDIT_F03_n';
        IF r.attempts <> 0 OR r.next_retry_at > now() OR r.last_error <> 'systemic' THEN
            RAISE EXCEPTION 'infrastructure failure consumed the retry budget or kept the note waiting';
        END IF;
        a := truth_vault.claim_feature_annotation_attempt('AUDIT_F03_n','AUDIT_F03','audit-sha','llm:audit','audit');
        IF a IS NULL THEN RAISE EXCEPTION 'released claim could not be taken again'; END IF;
    END LOOP;
    first_claim := a;
    -- Counted failure #1: back off about 20 hours (the nightly runs every 24h, so the next one is eligible).
    PERFORM truth_vault.finish_feature_annotation_attempt('AUDIT_F03_n','audit-sha','llm:audit','audit',a,false,'all_model_answers_invalid',true);
    SELECT * INTO r FROM truth_vault.feature_annotation_failures WHERE subject_id='AUDIT_F03_n';
    IF r.attempts <> 1 OR r.next_retry_at NOT BETWEEN now()+interval '19 hours' AND now()+interval '21 hours' THEN
        RAISE EXCEPTION 'first counted failure: attempts=% next=%', r.attempts, r.next_retry_at;
    END IF;
    IF truth_vault.claim_feature_annotation_attempt('AUDIT_F03_n','AUDIT_F03','audit-sha','llm:audit','audit') IS NOT NULL THEN
        RAISE EXCEPTION 'claim allowed during back-off';
    END IF;
    UPDATE truth_vault.feature_annotation_failures SET next_retry_at=now()-interval '1 second' WHERE subject_id='AUDIT_F03_n';
    a := truth_vault.claim_feature_annotation_attempt('AUDIT_F03_n','AUDIT_F03','audit-sha','llm:audit','audit');
    IF a IS NULL OR a=first_claim THEN RAISE EXCEPTION 'retry claim did not advance'; END IF;
    -- An older request completing late may not change the newer attempt's recovery state.
    PERFORM truth_vault.finish_feature_annotation_attempt('AUDIT_F03_n','audit-sha','llm:audit','audit',first_claim,true,'');
    PERFORM truth_vault.finish_feature_annotation_attempt('AUDIT_F03_n','audit-sha','llm:audit','audit',first_claim,false,'all_model_answers_invalid',true);
    IF NOT EXISTS(SELECT 1 FROM truth_vault.feature_annotation_failures WHERE subject_id='AUDIT_F03_n' AND attempts=1 AND claim_token=a) THEN
        RAISE EXCEPTION 'stale finish changed the newer attempt';
    END IF;
    -- Counted failure #2: about 44 hours. #3: quarantined, no automatic claim any more.
    PERFORM truth_vault.finish_feature_annotation_attempt('AUDIT_F03_n','audit-sha','llm:audit','audit',a,false,'all_model_answers_invalid',true);
    SELECT * INTO r FROM truth_vault.feature_annotation_failures WHERE subject_id='AUDIT_F03_n';
    IF r.attempts <> 2 OR r.next_retry_at NOT BETWEEN now()+interval '43 hours' AND now()+interval '45 hours' THEN
        RAISE EXCEPTION 'second counted failure: attempts=% next=%', r.attempts, r.next_retry_at;
    END IF;
    UPDATE truth_vault.feature_annotation_failures SET next_retry_at=now()-interval '1 second' WHERE subject_id='AUDIT_F03_n';
    a := truth_vault.claim_feature_annotation_attempt('AUDIT_F03_n','AUDIT_F03','audit-sha','llm:audit','audit');
    PERFORM truth_vault.finish_feature_annotation_attempt('AUDIT_F03_n','audit-sha','llm:audit','audit',a,false,'all_model_answers_invalid',true);
    UPDATE truth_vault.feature_annotation_failures SET next_retry_at=now()-interval '1 second' WHERE subject_id='AUDIT_F03_n';
    b := truth_vault.claim_feature_annotation_attempt('AUDIT_F03_n','AUDIT_F03','audit-sha','llm:audit','audit');
    IF a IS NULL OR b IS NOT NULL OR (SELECT attempts FROM truth_vault.feature_annotation_failures WHERE subject_id='AUDIT_F03_n') <> 3 THEN
        RAISE EXCEPTION 'automatic retry budget not bounded at three counted failures';
    END IF;
    a := truth_vault.claim_feature_annotation_attempt('AUDIT_F03_n','AUDIT_F03','audit-sha','llm:audit','audit',true);
    IF a IS NULL THEN RAISE EXCEPTION 'explicit replay unavailable'; END IF;
    -- T1: rows of the same snapshot under other model labels go with a success; other snapshots stay.
    INSERT INTO truth_vault.feature_annotation_failures(subject_id,project_id,bank_sha256,extractor,run_tag,last_error) VALUES
        ('AUDIT_F03_n','AUDIT_F03','audit-sha','llm:older-model','audit','legacy_all_invalid'),
        ('AUDIT_F03_n','AUDIT_F03','other-sha','llm:older-model','audit','legacy_all_invalid'),
        ('AUDIT_F03_n','AUDIT_F03','audit-sha','llm:older-model','other-tag','legacy_all_invalid'),
        ('AUDIT_F03_n','AUDIT_F03','audit-sha','jev:other','audit','legacy_all_invalid');
    PERFORM truth_vault.finish_feature_annotation_attempt('AUDIT_F03_n','audit-sha','llm:audit','audit',a,true,'');
    IF (SELECT array_agg(bank_sha256 || '|' || extractor || '|' || run_tag ORDER BY bank_sha256, extractor, run_tag)
        FROM truth_vault.feature_annotation_failures WHERE subject_id='AUDIT_F03_n')
       IS DISTINCT FROM ARRAY['audit-sha|jev:other|audit','audit-sha|llm:older-model|other-tag','other-sha|llm:older-model|audit'] THEN
        RAISE EXCEPTION 'success must clear every llm:* row of the same subject + bank sha + run_tag, and nothing else: %',
            (SELECT array_agg(bank_sha256 || '|' || extractor || '|' || run_tag) FROM truth_vault.feature_annotation_failures WHERE subject_id='AUDIT_F03_n');
    END IF;
    DELETE FROM truth_vault.feature_annotation_failures WHERE subject_id='AUDIT_F03_n';
    a := truth_vault.claim_feature_annotation_attempt('AUDIT_F03_n','AUDIT_F03','audit-sha','llm:audit','audit');
    INSERT INTO truth_vault.feature_annotation_failures(subject_id,project_id,bank_sha256,extractor,run_tag,last_error)
        VALUES ('AUDIT_F03_n','AUDIT_F03','audit-sha','llm:older-model','audit','legacy_all_invalid');
    PERFORM truth_vault.finish_feature_annotation_attempt('AUDIT_F03_n','audit-sha','llm:audit','audit',first_claim,true,'');
    IF (SELECT count(*) FROM truth_vault.feature_annotation_failures WHERE subject_id='AUDIT_F03_n') <> 2 THEN
        RAISE EXCEPTION 'stale success cleared a recreated queue row or its siblings';
    END IF;
    PERFORM truth_vault.finish_feature_annotation_attempt('AUDIT_F03_n','audit-sha','llm:audit','audit',a,true,'');
    IF to_regprocedure('truth_vault.finish_feature_annotation_attempt(text,text,text,text,uuid,boolean,text)') IS NOT NULL THEN
        RAISE EXCEPTION 'obsolete 7-argument finish left behind';
    END IF;
    payload := '[{"subject_type":"note","subject_id":"AUDIT_F03_n","question_id":"audit-question","question_version":1,"bank_version":"audit","bank_sha256":"audit-sha","extractor":"llm:audit","run_tag":"audit","answer":"是","evidence":"synthetic"}]';
    written := truth_vault.write_feature_answers_preserving_valid(payload);
    IF written <> 1 THEN RAISE EXCEPTION 'valid insert failed'; END IF;
    payload := jsonb_set(jsonb_set(payload,'{0,answer}','null'::jsonb),'{0,invalid_reason}','"json_parse_failed"'::jsonb);
    written := truth_vault.write_feature_answers_preserving_valid(payload);
    IF written <> 0 OR NOT EXISTS(SELECT 1 FROM truth_vault.note_feature_answers WHERE subject_id='AUDIT_F03_n' AND answer='是' AND invalid_reason IS NULL) THEN
        RAISE EXCEPTION 'invalid retry overwrote a valid answer';
    END IF;
    -- A valid reannotation may still update the same PK.
    payload := jsonb_set(jsonb_set(payload,'{0,answer}','"否"'::jsonb),'{0,invalid_reason}','null'::jsonb);
    PERFORM truth_vault.write_feature_answers_preserving_valid(payload);
    IF NOT EXISTS(SELECT 1 FROM truth_vault.note_feature_answers WHERE subject_id='AUDIT_F03_n' AND answer='否') THEN
        RAISE EXCEPTION 'valid replacement incorrectly blocked';
    END IF;
    IF has_function_privilege('anon','truth_vault.claim_feature_annotation_attempt(text,text,text,text,text,boolean)','EXECUTE')
       OR has_function_privilege('authenticated','truth_vault.write_feature_answers_preserving_valid(jsonb)','EXECUTE')
       OR NOT has_function_privilege('service_role','truth_vault.write_feature_answers_preserving_valid(jsonb)','EXECUTE') THEN
        RAISE EXCEPTION 'recovery RPC grants are not service-only';
    END IF;
END $$;
ROLLBACK;
