-- Local PostgreSQL regression, synthetic fixtures only. Run after v1.26; rolls back all rows.
BEGIN;
INSERT INTO truth_vault.projects (project_id,brand,product,category,platform)
VALUES ('AUDIT_F03','synthetic','synthetic','其他','xiaohongshu');
INSERT INTO truth_vault.notes (note_id,project_id,platform,raw_content)
VALUES ('AUDIT_F03_n','AUDIT_F03','xiaohongshu','synthetic feature recovery fixture');
DO $$
DECLARE a UUID; b UUID; first_claim UUID; payload JSONB; written INT;
BEGIN
    a := truth_vault.claim_feature_annotation_attempt('AUDIT_F03_n','AUDIT_F03','audit-sha','llm:audit','audit');
    IF a IS NULL THEN RAISE EXCEPTION 'first claim failed'; END IF;
    first_claim := a;
    b := truth_vault.claim_feature_annotation_attempt('AUDIT_F03_n','AUDIT_F03','audit-sha','llm:audit','audit');
    IF b IS NOT NULL THEN RAISE EXCEPTION 'same snapshot can be claimed twice during backoff'; END IF;
    PERFORM truth_vault.finish_feature_annotation_attempt('AUDIT_F03_n','audit-sha','llm:audit','audit',a,false,'all_model_answers_invalid');
    UPDATE truth_vault.feature_annotation_failures SET next_retry_at=now()-interval '1 second' WHERE subject_id='AUDIT_F03_n';
    a := truth_vault.claim_feature_annotation_attempt('AUDIT_F03_n','AUDIT_F03','audit-sha','llm:audit','audit');
    IF a IS NULL OR a=first_claim THEN RAISE EXCEPTION 'retry claim did not advance'; END IF;
    -- An older request completing late may not remove the newer attempt's recovery state.
    PERFORM truth_vault.finish_feature_annotation_attempt('AUDIT_F03_n','audit-sha','llm:audit','audit',first_claim,true,'');
    IF NOT EXISTS(SELECT 1 FROM truth_vault.feature_annotation_failures WHERE subject_id='AUDIT_F03_n' AND attempts=2) THEN
        RAISE EXCEPTION 'stale success deleted newer attempt';
    END IF;
    UPDATE truth_vault.feature_annotation_failures SET next_retry_at=now()-interval '1 second' WHERE subject_id='AUDIT_F03_n';
    a := truth_vault.claim_feature_annotation_attempt('AUDIT_F03_n','AUDIT_F03','audit-sha','llm:audit','audit');
    UPDATE truth_vault.feature_annotation_failures SET next_retry_at=now()-interval '1 second' WHERE subject_id='AUDIT_F03_n';
    b := truth_vault.claim_feature_annotation_attempt('AUDIT_F03_n','AUDIT_F03','audit-sha','llm:audit','audit');
    IF a IS NULL OR b IS NOT NULL THEN RAISE EXCEPTION 'automatic retry budget not bounded'; END IF;
    a := truth_vault.claim_feature_annotation_attempt('AUDIT_F03_n','AUDIT_F03','audit-sha','llm:audit','audit',true);
    IF a IS NULL THEN RAISE EXCEPTION 'explicit replay unavailable'; END IF;
    PERFORM truth_vault.finish_feature_annotation_attempt('AUDIT_F03_n','audit-sha','llm:audit','audit',a,true,'');
    IF EXISTS(SELECT 1 FROM truth_vault.feature_annotation_failures WHERE subject_id='AUDIT_F03_n') THEN
        RAISE EXCEPTION 'successful replay did not clear queue';
    END IF;
    a := truth_vault.claim_feature_annotation_attempt('AUDIT_F03_n','AUDIT_F03','audit-sha','llm:audit','audit');
    PERFORM truth_vault.finish_feature_annotation_attempt('AUDIT_F03_n','audit-sha','llm:audit','audit',first_claim,true,'');
    IF NOT EXISTS(SELECT 1 FROM truth_vault.feature_annotation_failures WHERE subject_id='AUDIT_F03_n' AND claim_token=a) THEN
        RAISE EXCEPTION 'stale success cleared a recreated queue row';
    END IF;
    PERFORM truth_vault.finish_feature_annotation_attempt('AUDIT_F03_n','audit-sha','llm:audit','audit',a,true,'');
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
