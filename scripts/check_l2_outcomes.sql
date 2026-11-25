-- check_l2_outcomes.sql —— W-64 ① (notes_v1_35) v_l2_outcomes 的边界夹具。CI sql job 在 v1_35 套两遍之后跑一次。
-- 全在一个事务里, 最后 ROLLBACK。断言失败 → RAISE EXCEPTION → psql (ON_ERROR_STOP) 非零退出。
--
-- 项目 CI_L2OA: 31 篇可比的帖 (小红书、有阅读、发布满 14 天), 阅读 1..31 → 中位数 16、75 分位 23.5
--   a16 阅读正好 16 (等于中位数) → 0;  a17 → 1;  a24 → top-quartile 1、a23 → 0
--   a30 是数值推断的爆 (被 v_l2_labels 洗掉) → y_hit NULL, 阅读口径照算 (= 1)
--   dy  抖音 (没有阅读口径) → NULL;  young 发布 3 天 → NULL;  noreads 没有阅读 → NULL
--   paid 投流 / synth synthetic / ref 参考 → 不在视图里
-- 项目 CI_L2OB: 只有 5 篇可比的帖 → 阅读口径全 NULL
-- 评论: a01 运营贴 2 行 + 明细 3 行 (1 铺的、1 贴主、1 读者) + 快照 2 行 → seeded 2、reader 1 (有明细就用明细)
--       a02 只有快照 (1 读者、1 铺的) → reader 1;  a03 没爬过 → reader NULL、seeded 0
-- 反证 (改坏之后必须红): > 改成 >= → a16 变 1; 去掉 n_comparable >= 30 → CI_L2OB 有值; 不排 paid → paid 冒出来;
--   reader 两种来源相加 → a01 变 3; 给 anon 授权 → 最后一条红。
BEGIN;
INSERT INTO truth_vault.projects (project_id, brand, product, category) VALUES
  ('CI_L2OA', 'b', 'p', '其他'), ('CI_L2OB', 'b', 'p', '其他') ON CONFLICT DO NOTHING;
INSERT INTO truth_vault.notes (note_id, project_id, raw_content, tier, tier_source, publish_time, platform, reads, data_quality_flags)
SELECT 'CI_L2OA_a' || lpad(i::text, 2, '0'), 'CI_L2OA', 'c',
       CASE WHEN i IN (17, 24, 30) THEN '爆' ELSE '趴' END,
       CASE WHEN i = 30 THEN '数值推断' ELSE '状态字段' END,
       '2026-03-01'::timestamp + (i || ' hours')::interval, 'xiaohongshu', i, NULL
FROM generate_series(1, 31) AS i;
INSERT INTO truth_vault.notes (note_id, project_id, raw_content, tier, tier_source, publish_time, platform, reads, data_quality_flags) VALUES
  ('CI_L2OA_dy',      'CI_L2OA', 'c', '爆', '状态字段', '2026-03-02', 'douyin',      100,  NULL),
  ('CI_L2OA_young',   'CI_L2OA', 'c', '趴', '状态字段', now()::timestamp - interval '3 days', 'xiaohongshu', 100, NULL),
  ('CI_L2OA_noreads', 'CI_L2OA', 'c', '趴', '状态字段', '2026-03-02', 'xiaohongshu', NULL, NULL),
  ('CI_L2OA_paid',    'CI_L2OA', 'c', '爆', '状态字段', '2026-03-02', 'xiaohongshu', 100,  '{"paid_promoted": true}'),
  ('CI_L2OA_synth',   'CI_L2OA', 'c', '爆', '状态字段', '2026-03-02', 'xiaohongshu', 100,  '{"synthetic": true}'),
  ('CI_L2OA_ref',     'CI_L2OA', 'c', '参考', '状态字段', '2026-03-02', 'xiaohongshu', 100, NULL);
INSERT INTO truth_vault.notes (note_id, project_id, raw_content, tier, tier_source, publish_time, platform, reads)
SELECT 'CI_L2OB_b' || i, 'CI_L2OB', 'c', '趴', '状态字段', '2026-03-01', 'xiaohongshu', i * 10 FROM generate_series(1, 5) AS i;
INSERT INTO truth_vault.comments (comment_id, note_id, project_id, content, source, is_scripted, comment_role) VALUES
  ('ci_l2o_c1', 'CI_L2OA_a01', 'CI_L2OA', 'x', NULL,                NULL, NULL),
  ('ci_l2o_c2', 'CI_L2OA_a01', 'CI_L2OA', 'x', NULL,                NULL, NULL),
  ('ci_l2o_c3', 'CI_L2OA_a01', 'CI_L2OA', 'x', 'linkcheck_records', true, NULL),
  ('ci_l2o_c4', 'CI_L2OA_a01', 'CI_L2OA', 'x', 'linkcheck_records', NULL, '贴主'),
  ('ci_l2o_c5', 'CI_L2OA_a01', 'CI_L2OA', 'x', 'linkcheck_records', NULL, NULL),
  ('ci_l2o_c6', 'CI_L2OA_a01', 'CI_L2OA', 'x', 'linkcheck_digest',  NULL, NULL),
  ('ci_l2o_c7', 'CI_L2OA_a01', 'CI_L2OA', 'x', 'linkcheck_digest',  NULL, NULL),
  ('ci_l2o_c8', 'CI_L2OA_a02', 'CI_L2OA', 'x', 'linkcheck_digest',  NULL, NULL),
  ('ci_l2o_c9', 'CI_L2OA_a02', 'CI_L2OA', 'x', 'linkcheck_digest',  true, NULL);

DO $$
DECLARE
  got text;
  want text;
BEGIN
  SELECT string_agg(replace(note_id, 'CI_L2OA_', '') || '=' || COALESCE(y_hit::text, '-') || '/' || COALESCE(y_reads_median::text, '-')
                    || '/' || COALESCE(y_reads_top_quartile::text, '-'), ' ' ORDER BY note_id COLLATE "C")
    INTO got FROM truth_vault.v_l2_outcomes
   WHERE note_id IN ('CI_L2OA_a16', 'CI_L2OA_a17', 'CI_L2OA_a23', 'CI_L2OA_a24', 'CI_L2OA_a30',
                     'CI_L2OA_dy', 'CI_L2OA_young', 'CI_L2OA_noreads', 'CI_L2OA_paid', 'CI_L2OA_synth', 'CI_L2OA_ref');
  want := 'a16=0/0/0 a17=1/1/0 a23=0/1/0 a24=1/1/1 a30=-/1/1 dy=1/-/- noreads=0/-/- young=0/-/-';
  IF got IS DISTINCT FROM want THEN
    RAISE EXCEPTION 'v_l2_outcomes 边界行不对: 期望 [%] 实得 [%]', want, got;
  END IF;
  IF (SELECT count(*) FROM truth_vault.v_l2_outcomes WHERE project_id = 'CI_L2OA' AND y_reads_median IS NOT NULL) <> 31 THEN
    RAISE EXCEPTION 'CI_L2OA 应有 31 篇带阅读口径';
  END IF;
  IF EXISTS (SELECT 1 FROM truth_vault.v_l2_outcomes WHERE project_id = 'CI_L2OB'
             AND (y_reads_median IS NOT NULL OR reads_pct_in_project IS NOT NULL OR y_reads_top_quartile IS NOT NULL)) THEN
    RAISE EXCEPTION '可比的帖不到 30 篇的项目不该有阅读口径';
  END IF;
  IF (SELECT reads_pct_in_project FROM truth_vault.v_l2_outcomes WHERE note_id = 'CI_L2OA_a31') <> 1
     OR (SELECT reads_pct_in_project FROM truth_vault.v_l2_outcomes WHERE note_id = 'CI_L2OA_a01') <> 0 THEN
    RAISE EXCEPTION 'reads_pct_in_project 两端应是 0 和 1';
  END IF;
  SELECT string_agg(replace(note_id, 'CI_L2OA_', '') || '=' || seeded_comment_rows || '/' || COALESCE(reader_comment_rows::text, '-'), ' '
                    ORDER BY note_id COLLATE "C")
    INTO got FROM truth_vault.v_l2_outcomes WHERE note_id IN ('CI_L2OA_a01', 'CI_L2OA_a02', 'CI_L2OA_a03');
  want := 'a01=2/1 a02=0/1 a03=0/-';
  IF got IS DISTINCT FROM want THEN
    RAISE EXCEPTION '评论诊断列不对: 期望 [%] 实得 [%]', want, got;
  END IF;
  IF has_table_privilege('anon', 'truth_vault.v_l2_outcomes', 'SELECT')
     OR has_table_privilege('authenticated', 'truth_vault.v_l2_outcomes', 'SELECT')
     OR NOT has_table_privilege('service_role', 'truth_vault.v_l2_outcomes', 'SELECT') THEN
    RAISE EXCEPTION 'v_l2_outcomes 的读权限不对: 只给 service_role, 不给 anon / authenticated';
  END IF;
  RAISE NOTICE '  ✓ v1.35 v_l2_outcomes: 中位数相等算 0 / 75 分位 / 洗掉的爆照算阅读口径 / 抖音、没满 14 天、没阅读 → NULL / 投流、synthetic、参考不在 / 不到 30 篇 → NULL / 评论诊断列 / 只给 service_role';
END $$;
ROLLBACK;
