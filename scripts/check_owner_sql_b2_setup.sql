-- check_owner_sql_b2_setup.sql · 两份 owner 数据 SQL (v1_31 / v1_33, 列体检 2026-11-25 / I-17) 的夹具: 只铺数据。
-- CI 的 sql job 一行 (在仓库根目录; 中间两个 -f 是两份 owner SQL 的第一遍, 批 1 的部署清单守卫 §3 认 `-f schemas/...`):
--   psql -v ON_ERROR_STOP=1 -q -f scripts/check_owner_sql_b2_setup.sql -f schemas/notes_v1_31_commenter_codes_cleanup.sql \
--        -f schemas/notes_v1_33_direction_switch_restore.sql -f scripts/check_owner_sql_b2.sql
-- 核对、第二遍、收尾都在 check_owner_sql_b2.sql 里 (那份的文件头写了每篇夹具要钉什么)。
-- 夹具用真的项目号 (owner SQL 里写死了项目), 行号全带 CIB2 前缀。

\set QUIET on
\set ON_ERROR_STOP 1

INSERT INTO truth_vault.projects (project_id, brand, product, category) VALUES
    ('NUC_phase1', 'b', 'p', '保健品'), ('NRT_phase2', 'b', 'p', '保健品'), ('HXZ_FB', 'b', 'p', '美妆'),
    ('BJS_phase2', 'b', 'p', '保健品'), ('HATHERINE_phase1', 'b', 'p', '个护'), ('SPX_phase1', 'b', 'p', '保健品')
ON CONFLICT (project_id) DO NOTHING;

-- ═══ v1_31 夹具 ═══════════════════════════════════════════════════════
INSERT INTO truth_vault.notes (note_id, project_id, raw_content, raw_extra) VALUES
  ('CIB2_n1', 'NUC_phase1', 'c', '{"_comment_text": "1. 用户A: 好用", "_comment_text_persona": "12a"}'),
  ('CIB2_n2', 'NUC_phase1', 'c', '{"_comment_text": "1. 12a 说的对", "_comment_text_persona": "12a"}'),
  ('CIB2_n3', 'NRT_phase2', 'c', '{"_comment_text": "好用", "_commenter_codes": ["7b"]}'),
  ('CIB2_n4', 'HXZ_FB',     'c', '{"_comment_text": "好用", "_comment_text_persona": "15"}'),
  ('CIB2_n5', 'NUC_phase1', 'c', '{"_comment_text": "好用", "_comment_text_persona": "9c"}'),
  ('CIB2_n6', 'BJS_phase2', 'c', '{"_comment_text": "好用", "_comment_text_persona": "x9"}');
INSERT INTO truth_vault.comments (comment_id, note_id, project_id, content, comment_role, comment_order, source) VALUES
  ('CIB2_n1_c1', 'CIB2_n1', 'NUC_phase1', '好用', '素人', 1, NULL),
  ('CIB2_n1_c2', 'CIB2_n1', 'NUC_phase1', '12a',  '素人', 2, NULL),     -- 假评论 (旧键)
  ('CIB2_n2_c1', 'CIB2_n2', 'NUC_phase1', '12a',  '素人', 1, NULL),     -- 编号在原文里出现过: 不删
  ('CIB2_n3_c1', 'CIB2_n3', 'NRT_phase2', '7b',   '素人', 1, NULL),     -- 假评论 (新键)
  ('CIB2_n4_c1', 'CIB2_n4', 'HXZ_FB',     '15',   '素人', 1, NULL),     -- 纯数字: 不删
  ('CIB2_n5_c1', 'CIB2_n5', 'NUC_phase1', '9c',   '素人', 1, 'linkcheck_digest'),   -- 巡查来的: 不删
  ('CIB2_n6_c1', 'CIB2_n6', 'BJS_phase2', 'x9',   '素人', 1, NULL);     -- 别的项目: 不删
INSERT INTO truth_vault.note_feature_answers
    (subject_type, subject_id, question_id, question_version, bank_version, bank_sha256, extractor, run_tag, answer) VALUES
  ('comment', 'CIB2_n1_c2', 'q1', 1, 'v', 's', 'jev:x', 'shadow', '是'),
  ('comment', 'CIB2_n1_c2', 'q2', 1, 'v', 's', 'jev:x', 'shadow', '否'),
  ('comment', 'CIB2_n1_c1', 'q1', 1, 'v', 's', 'jev:x', 'shadow', '是');

-- ═══ v1_33 夹具 ═══════════════════════════════════════════════════════
INSERT INTO truth_vault.notes (note_id, project_id, raw_content, raw_extra, content_format, target_audience, user_pain_point) VALUES
  ('CIB2_b1', 'BJS_phase2', 'c', '{"_direction_raw": ["成人款"]}',         '场景植入', '{宝妈,通用}', 'p'),
  ('CIB2_b2', 'BJS_phase2', 'c', '{"_direction_raw": ["提问贴", "成人款"]}', '提问求助', '{宝妈,通用}', 'p'),
  ('CIB2_b3', 'BJS_phase2', 'c', '{"_direction_raw": ["儿童款"]}',         '场景植入', '{宝妈,通用}', 'p'),
  ('CIB2_b4', 'BJS_phase2', 'c', '{"_direction_raw": ["成人款"]}',         '情感叙事', NULL, NULL),
  ('CIB2_h1', 'HATHERINE_phase1', 'c', '{"_direction_raw": "流量-长痘提问"}', '直给推荐', '{通用}', 'p'),
  ('CIB2_s1', 'SPX_phase1', 'c', '{"_direction_raw": "方向三圈内观察"}',    '提问求助', '{通用}', NULL),
  ('CIB2_b5', 'BJS_phase2', 'c', '{"_direction_raw": ["成人款"]}',         '反差破圈', NULL, NULL),
  ('CIB2_b6', 'BJS_phase2', 'c', '{"_direction_raw": ["儿童款"]}',         '场景植入', '{宝妈}', NULL),
  ('CIB2_b7', 'BJS_phase2', 'c', '{"_direction_raw": ["成人款"]}',         '场景植入', NULL, NULL);
-- audit_log: essence 那一次 (t1) + 改方向那一次 (t2)。直接写, 不靠触发器, 时刻和内容都定死。
INSERT INTO truth_vault.audit_log (schema_name, table_name, row_id, operation, changed_cols, occurred_at) VALUES
  ('truth_vault', 'notes', 'CIB2_b1', 'UPDATE', '{"essence_annotated_at": [null, "2026-11-01"], "content_format": ["场景植入", "情感叙事"]}', '2026-11-01 10:00'),
  ('truth_vault', 'notes', 'CIB2_b1', 'UPDATE', '{"content_format": ["情感叙事", "场景植入"]}', '2026-11-02 10:00'),
  ('truth_vault', 'notes', 'CIB2_b1', 'UPDATE', '{"raw_extra": [{"_direction_raw": "好物分享-产品贴"}, {"_direction_raw": ["成人款"]}]}', '2026-11-21 10:00'),
  ('truth_vault', 'notes', 'CIB2_b2', 'UPDATE', '{"essence_annotated_at": [null, "2026-11-01"], "content_format": ["提问求助", "情感叙事"]}', '2026-11-01 10:00'),
  ('truth_vault', 'notes', 'CIB2_b2', 'UPDATE', '{"raw_extra": [{"_direction_raw": "提问贴"}, {"_direction_raw": ["提问贴", "成人款"]}]}', '2026-11-21 10:00'),
  ('truth_vault', 'notes', 'CIB2_b3', 'UPDATE', '{"essence_annotated_at": [null, "2026-11-01"], "emotional_lever": [null, "x"]}', '2026-11-01 10:00'),
  ('truth_vault', 'notes', 'CIB2_b3', 'UPDATE', '{"raw_extra": [{"_direction_raw": "好物分享-产品贴"}, {"_direction_raw": ["儿童款"]}]}', '2026-11-21 10:00'),
  ('truth_vault', 'notes', 'CIB2_b4', 'UPDATE', '{"essence_annotated_at": [null, "2026-11-01"], "content_format": ["场景植入", "情感叙事"]}', '2026-11-01 10:00'),
  ('truth_vault', 'notes', 'CIB2_b4', 'UPDATE', '{"raw_extra": [{"_direction_raw": "好物分享-产品贴"}, {"_direction_raw": ["成人款"]}]}', '2026-11-21 10:00'),
  ('truth_vault', 'notes', 'CIB2_h1', 'UPDATE', '{"essence_annotated_at": [null, "2026-10-01"], "content_format": ["直给推荐", "教程攻略"]}', '2026-10-01 10:00'),
  ('truth_vault', 'notes', 'CIB2_h1', 'UPDATE', '{"raw_extra": [{"_direction_raw": "产品-全家桶"}, {"_direction_raw": "流量-长痘提问"}]}', '2026-10-20 10:00'),
  -- b5: 库里的值不是旧方向抬的值 (essence 之后有人手改过) → 不碰、不备份。
  ('truth_vault', 'notes', 'CIB2_b5', 'UPDATE', '{"essence_annotated_at": [null, "2026-11-01"], "content_format": ["场景植入", "情感叙事"]}', '2026-11-01 10:00'),
  ('truth_vault', 'notes', 'CIB2_b5', 'UPDATE', '{"content_format": ["情感叙事", "反差破圈"]}', '2026-11-03 10:00'),
  ('truth_vault', 'notes', 'CIB2_b5', 'UPDATE', '{"raw_extra": [{"_direction_raw": "好物分享-产品贴"}, {"_direction_raw": ["成人款"]}]}', '2026-11-21 10:00'),
  -- b6: 两次改方向 (提问贴 → 好物分享-产品贴 → 儿童款)、两次 essence 写 (认知重构, 后来 情感叙事), 每次都被夜跑盖回 场景植入。
  --     要认最后一次改方向 (旧方向 = 好物分享-产品贴, 抬 场景植入 = 库里的值) 和 essence 最后一次写 (情感叙事)。
  ('truth_vault', 'notes', 'CIB2_b6', 'UPDATE', '{"raw_extra": [{"_direction_raw": "提问贴"}, {"_direction_raw": "好物分享-产品贴"}]}', '2026-09-01 10:00'),
  ('truth_vault', 'notes', 'CIB2_b6', 'UPDATE', '{"essence_annotated_at": [null, "2026-09-10"], "content_format": ["场景植入", "认知重构"]}', '2026-09-10 10:00'),
  ('truth_vault', 'notes', 'CIB2_b6', 'UPDATE', '{"content_format": ["认知重构", "场景植入"]}', '2026-09-11 10:00'),
  ('truth_vault', 'notes', 'CIB2_b6', 'UPDATE', '{"essence_annotated_at": ["2026-09-10", "2026-11-05"], "content_format": ["场景植入", "情感叙事"]}', '2026-11-05 10:00'),
  ('truth_vault', 'notes', 'CIB2_b6', 'UPDATE', '{"content_format": ["情感叙事", "场景植入"]}', '2026-11-06 10:00'),
  ('truth_vault', 'notes', 'CIB2_b6', 'UPDATE', '{"raw_extra": [{"_direction_raw": "好物分享-产品贴"}, {"_direction_raw": ["儿童款"]}]}', '2026-11-21 10:00'),
  -- b7: 早一次 essence 改过 (认知重构), 最后一次 essence 没改 (它那时的判断 = 场景植入) → 不换。
  ('truth_vault', 'notes', 'CIB2_b7', 'UPDATE', '{"essence_annotated_at": [null, "2026-09-10"], "content_format": ["场景植入", "认知重构"]}', '2026-09-10 10:00'),
  ('truth_vault', 'notes', 'CIB2_b7', 'UPDATE', '{"content_format": ["认知重构", "场景植入"]}', '2026-09-11 10:00'),
  ('truth_vault', 'notes', 'CIB2_b7', 'UPDATE', '{"essence_annotated_at": ["2026-09-10", "2026-11-05"], "emotional_lever": ["x", "y"]}', '2026-11-05 10:00'),
  ('truth_vault', 'notes', 'CIB2_b7', 'UPDATE', '{"raw_extra": [{"_direction_raw": "好物分享-产品贴"}, {"_direction_raw": ["成人款"]}]}', '2026-11-21 10:00');
