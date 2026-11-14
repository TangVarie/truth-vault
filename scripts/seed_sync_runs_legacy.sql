-- CI / local disposable PostgreSQL only. Run BEFORE the first notes_v1_25_sync_runs.sql apply:
-- rows that were stamped by the pre-v1.25 sync, so the migration's legacy baseline has something
-- to import. scripts/check_sync_runs_legacy.sql asserts on them and deletes them again.
-- Synthetic records only.
INSERT INTO truth_vault.projects(project_id,brand,product,category)
VALUES('CI_V25_LEGACY','synthetic','synthetic','其他'),('CI_V25_LEGACY_ND','synthetic','synthetic','其他')
ON CONFLICT DO NOTHING;
INSERT INTO truth_vault.notes(note_id,project_id,raw_content,last_seen_run_id,last_seen_at) VALUES
 ('CI_V25_LEGACY_live','CI_V25_LEGACY','synthetic','ci-legacy-r9',now()-interval '1 hour'),
 ('CI_V25_LEGACY_gone','CI_V25_LEGACY','synthetic','ci-legacy-r1',now()-interval '19 days'),
 ('CI_V25_LEGACY_never','CI_V25_LEGACY','synthetic',NULL,NULL),
 ('CI_V25_LEGACY_ND_a','CI_V25_LEGACY_ND','synthetic',NULL,NULL)   -- on_demand project: never stamped
ON CONFLICT DO NOTHING;
