-- CI / local disposable PostgreSQL only. Run BEFORE the first notes_v1_26_feature_failure_recovery.sql
-- apply: answer snapshots as older workers left them, so the migration's legacy import has something
-- to decide on. scripts/check_feature_failure_recovery_legacy.sql asserts and deletes them again.
-- Synthetic records only.
INSERT INTO truth_vault.projects(project_id,brand,product,category)
VALUES('CI_V26_LEGACY','synthetic','synthetic','其他') ON CONFLICT DO NOTHING;
INSERT INTO truth_vault.notes(note_id,project_id,raw_content) VALUES
 ('CI_V26_LEGACY_bad','CI_V26_LEGACY','synthetic'),       -- every model answer invalid            → queued
 ('CI_V26_LEGACY_relabel','CI_V26_LEGACY','synthetic'),   -- invalid under the old model label,
                                                          -- answered under the current one        → not queued
 ('CI_V26_LEGACY_good','CI_V26_LEGACY','synthetic'),      -- answered                              → not queued
 ('CI_V26_LEGACY_noinput','CI_V26_LEGACY','synthetic')    -- nothing to ask (no model failure)     → not queued
ON CONFLICT DO NOTHING;
INSERT INTO truth_vault.note_feature_answers
    (subject_type,subject_id,question_id,question_version,bank_version,bank_sha256,extractor,run_tag,answer,invalid_reason) VALUES
 ('note','CI_V26_LEGACY_bad','has_specific_time',1,'ci','ci-sha','llm:ci-old','primary',NULL,'json_parse_failed'),
 ('note','CI_V26_LEGACY_bad','title_is_question',1,'ci','ci-sha','llm:ci-old','primary',NULL,'json_parse_failed'),
 ('note','CI_V26_LEGACY_relabel','has_specific_time',1,'ci','ci-sha','llm:ci-old','primary',NULL,'json_parse_failed'),
 ('note','CI_V26_LEGACY_relabel','has_specific_time',1,'ci','ci-sha','llm:ci-new','primary','否',NULL),
 ('note','CI_V26_LEGACY_good','has_specific_time',1,'ci','ci-sha','llm:ci-old','primary','是',NULL),
 ('note','CI_V26_LEGACY_good','title_is_question',1,'ci','ci-sha','llm:ci-old','primary',NULL,'out_of_vocab'),
 ('note','CI_V26_LEGACY_noinput','has_specific_time',1,'ci','ci-sha','llm:ci-old','primary',NULL,'text_too_short')
ON CONFLICT DO NOTHING;
