-- check_shelf_account_prior.sql —— G-06 (notes_v1_34) 书架账号先验的行为夹具。CI sql job 在 v1_34 套两遍之后跑一次。
-- 全在一个事务里, 最后 ROLLBACK, 不留行。断言失败 → RAISE EXCEPTION → psql (ON_ERROR_STOP) 非零退出。
--
-- 夹具 (项目 CI_G06A, 趴中位 = 5):
--   acc_b 三篇趴 (互动 5)                                      → 只进项目基线
--   acc_a 更早: h1 干净爆 · h2 趴 · h3 数值推断爆 · h4 synthetic 爆 · h5 铺评工单爆 · h6 互动 4 (≤ 趴中位) 的爆
--         同一账号在 CI_G06Z 也有一篇更早的趴 (账号跨项目算)
--   card  acc_a 的大爆 (03-01) —— 被测的卡; same = 同一时刻发的另一篇爆; later = 之后的趴
--   fresh  新账号的爆 → 没有更早标签 → 先验 = 项目基线;  noacct 没账号的爆 → 同
--   v_l2_labels 里 CI_G06A 有 10 行 (3 趴 + h1 + h2 + card + same + later + fresh + noacct), 正例 5 → 项目基线 0.5
--   card 的更早标签: h1 (1)、h2 (0)、Z 那篇趴 (0) → n_prev = 3, pos_prev = 1 → (1 + 10×0.5) / (3 + 10) = 6/13
--   zref   CI_G06Z 的参考卡 (Z 只有趴, 没正例) → 先验 = 全库平均 y;  qref 项目根本不在 v_l2_labels → 同
--   CI_G06R 只测准入 (同 v1_14 的六条边界): both 两路都有的大爆不上; boost 只有起量后干预的大爆、empty 有 flags 没 routes 的爆、
--   tref 铺评工单的参考、synref synthetic 的参考照常上; infer 数值推断的参考不上。
-- (0) 书架上 CI_G06* 的卡正好是这 12 张: A 的 h1 h6 card same fresh noacct、Z 的 zref、Q 的 qref、R 的 boost empty tref synref。
--   v1_34 整段抄了一遍 v1_14 的准入, 而 v1.14 的准入夹具在 v1_34 之前跑; 这一条在 v1_34 之后把准入再钉一遍。
-- 反证 (改坏之后必须红): < 改成 <= → card 多算 same 和自己; 不走 v_l2_labels 直接读 notes → h3–h6 混进来;
--   去掉 n_pos > 0 的兜底 → zref 的先验变 0; 账号项写成 0.3 × prior → 弱账号反而往后排, (5) 的方向断言红;
--   LEFT JOIN proj_base 改成 JOIN → qref 没了; 去掉铺评工单 / synthetic / 数值推断那一条 → h5 / h4 / h3 冒出来;
--   准入去掉参考 → zref qref tref synref 没了: 都是 (0) 红。
BEGIN;
INSERT INTO truth_vault.projects (project_id, brand, product, category) VALUES
  ('CI_G06A', 'b', 'p', '其他'), ('CI_G06Z', 'b', 'p', '其他'), ('CI_G06Q', 'b', 'p', '其他'), ('CI_G06R', 'b', 'p', '其他')
  ON CONFLICT DO NOTHING;
INSERT INTO truth_vault.accounts (account_id) VALUES ('ci_g06_a'), ('ci_g06_b'), ('ci_g06_c'), ('ci_g06_z') ON CONFLICT DO NOTHING;
INSERT INTO truth_vault.notes (note_id, project_id, account_id, raw_content, tier, tier_source, publish_time, interactions, data_quality_flags) VALUES
  ('CI_G06A_pb1',   'CI_G06A', 'ci_g06_b', 'c', '趴',   '状态字段', '2026-01-01', 5,   NULL),
  ('CI_G06A_pb2',   'CI_G06A', 'ci_g06_b', 'c', '趴',   '状态字段', '2026-01-02', 5,   NULL),
  ('CI_G06A_pb3',   'CI_G06A', 'ci_g06_b', 'c', '趴',   '状态字段', '2026-01-03', 5,   NULL),
  ('CI_G06A_h1',    'CI_G06A', 'ci_g06_a', 'c', '爆',   '状态字段', '2026-02-01', 100, NULL),
  ('CI_G06A_h2',    'CI_G06A', 'ci_g06_a', 'c', '趴',   '状态字段', '2026-02-02', 5,   NULL),
  ('CI_G06A_h3',    'CI_G06A', 'ci_g06_a', 'c', '爆',   '数值推断', '2026-02-03', 100, NULL),
  ('CI_G06A_h4',    'CI_G06A', 'ci_g06_a', 'c', '爆',   '状态字段', '2026-02-04', 100, '{"synthetic": true}'),
  ('CI_G06A_h5',    'CI_G06A', 'ci_g06_a', 'c', '爆',   '状态字段', '2026-02-05', 100, '{"comment_maintained": true, "comment_maintained_routes": ["铺评工单"]}'),
  ('CI_G06A_h6',    'CI_G06A', 'ci_g06_a', 'c', '爆',   '状态字段', '2026-02-06', 4,   NULL),
  ('CI_G06Z_acc_a', 'CI_G06Z', 'ci_g06_a', 'c', '趴',   '状态字段', '2026-02-10', 5,   NULL),
  ('CI_G06A_card',  'CI_G06A', 'ci_g06_a', 'c', '大爆', '状态字段', '2026-03-01', 200, NULL),
  ('CI_G06A_same',  'CI_G06A', 'ci_g06_a', 'c', '爆',   '状态字段', '2026-03-01', 150, NULL),
  ('CI_G06A_later', 'CI_G06A', 'ci_g06_a', 'c', '趴',   '状态字段', '2026-04-01', 5,   NULL),
  ('CI_G06A_fresh', 'CI_G06A', 'ci_g06_c', 'c', '爆',   '状态字段', '2026-05-01', 100, NULL),
  ('CI_G06A_noacct','CI_G06A', NULL,       'c', '爆',   '状态字段', '2026-05-02', 100, NULL),
  ('CI_G06Z_pa',    'CI_G06Z', NULL,       'c', '趴',   '状态字段', '2026-01-05', 5,   NULL),
  ('CI_G06Z_zref',  'CI_G06Z', 'ci_g06_z', 'c', '参考', '状态字段', '2026-06-01', NULL, NULL),
  ('CI_G06Q_qref',  'CI_G06Q', NULL,       'c', '参考', '状态字段', '2026-06-02', NULL, NULL),
  ('CI_G06R_both',  'CI_G06R', NULL,       'c', '大爆', '状态字段', '2026-07-01', 100, '{"comment_maintained": true, "comment_maintained_routes": ["起量后干预", "铺评工单"]}'),
  ('CI_G06R_boost', 'CI_G06R', NULL,       'c', '大爆', '状态字段', '2026-07-01', 100, '{"comment_maintained": true, "comment_maintained_routes": ["起量后干预"]}'),
  ('CI_G06R_empty', 'CI_G06R', NULL,       'c', '爆',   '状态字段', '2026-07-01', 100, '{"comment_maintained": false}'),
  ('CI_G06R_tref',  'CI_G06R', NULL,       'c', '参考', '状态字段', '2026-07-01', NULL, '{"comment_maintained": true, "comment_maintained_routes": ["铺评工单"]}'),
  ('CI_G06R_synref','CI_G06R', NULL,       'c', '参考', '状态字段', '2026-07-01', NULL, '{"synthetic": true}'),
  ('CI_G06R_infer', 'CI_G06R', NULL,       'c', '参考', '数值推断', '2026-07-01', NULL, NULL);

DO $$
DECLARE
  r record;
  g double precision;
  v14 text[] := ARRAY['source_note_id','project_id','brand','category','platform','tier','tier_source','publish_time',
                      'emotional_lever','target_audience','user_pain_point','content_format','hit_blue_keywords',
                      'hook_type','structure','why_it_worked','transferable_tactic','curated_at','is_curated',
                      'raw_excerpt','recency_weight','account_bao_rate','rank_score','synthetic'];
  cols text[];
  got text[];
  want text[] := ARRAY['CI_G06A_h1', 'CI_G06A_h6', 'CI_G06A_card', 'CI_G06A_same', 'CI_G06A_fresh', 'CI_G06A_noacct',
                       'CI_G06Z_zref', 'CI_G06Q_qref', 'CI_G06R_boost', 'CI_G06R_empty', 'CI_G06R_tref', 'CI_G06R_synref'];
BEGIN
  -- (0) 准入: CI_G06* 上架的卡正好是 want 这 12 张 (多一张、少一张都红)
  SELECT array_agg(source_note_id::text ORDER BY source_note_id COLLATE "C") INTO got
  FROM truth_vault.v_flywheel_lesson_cards WHERE source_note_id LIKE 'CI\_G06%';
  IF got IS DISTINCT FROM (SELECT array_agg(x ORDER BY x COLLATE "C") FROM unnest(want) x) THEN
    RAISE EXCEPTION '书架准入不对 (v1_34 抄 v1_14 的准入抄坏了?): 实得 %', got;
  END IF;
  -- (6) v1_14 的 24 列一个不少、顺序不变, 新列只在末尾
  SELECT array_agg(column_name::text ORDER BY ordinal_position) INTO cols
  FROM information_schema.columns WHERE table_schema = 'truth_vault' AND table_name = 'v_flywheel_lesson_cards';
  IF cols[1:24] IS DISTINCT FROM v14 OR cols[25:] IS DISTINCT FROM ARRAY['account_prior','account_prior_n'] THEN
    RAISE EXCEPTION 'v_flywheel_lesson_cards 的列变了: %', cols;
  END IF;
  -- (2) 清洗掉的不进 v_l2_labels → CI_G06A 10 行、正例 5
  IF (SELECT count(*) || '/' || sum(y) FROM truth_vault.v_l2_labels WHERE project_id = 'CI_G06A') <> '10/5' THEN
    RAISE EXCEPTION '夹具前提不对: CI_G06A 在 v_l2_labels 里应是 10 行 5 正例';
  END IF;
  -- (1)(2)(3) card: 只数严格更早的 3 篇 (跨项目), 收缩值手算 6/13
  SELECT * INTO r FROM truth_vault.v_flywheel_lesson_cards WHERE source_note_id = 'CI_G06A_card';
  IF r.account_prior_n <> 3 OR abs(r.account_prior - 6.0 / 13.0) > 1e-9 THEN
    RAISE EXCEPTION 'card: n_prev=% prior=% (期望 3 / %)', r.account_prior_n, r.account_prior, 6.0 / 13.0;
  END IF;
  IF abs(r.rank_score - r.recency_weight - 0.7 - 0.3 * (1 - 6.0 / 13.0)) > 1e-9 THEN
    RAISE EXCEPTION 'card: rank_score 的账号项不是 0.3 × (1 − 先验)';
  END IF;
  -- same: 同一时刻发的 card 不算它的「更早」, 反过来也一样
  SELECT * INTO r FROM truth_vault.v_flywheel_lesson_cards WHERE source_note_id = 'CI_G06A_same';
  IF r.account_prior_n <> 3 THEN RAISE EXCEPTION 'same: n_prev=% (期望 3, 同一时刻的 card 不算)', r.account_prior_n; END IF;
  -- (4) 没有更早标签 / 没账号 → 项目基线 0.5
  FOR r IN SELECT * FROM truth_vault.v_flywheel_lesson_cards WHERE source_note_id IN ('CI_G06A_fresh', 'CI_G06A_noacct') LOOP
    IF r.account_prior_n <> 0 OR abs(r.account_prior - 0.5) > 1e-9 THEN
      RAISE EXCEPTION '%: n_prev=% prior=% (期望 0 / 0.5)', r.source_note_id, r.account_prior_n, r.account_prior;
    END IF;
  END LOOP;
  -- (4) 项目没有正例 / 不在 v_l2_labels → 全库平均
  SELECT avg(y)::double precision INTO g FROM truth_vault.v_l2_labels;
  FOR r IN SELECT * FROM truth_vault.v_flywheel_lesson_cards WHERE source_note_id IN ('CI_G06Z_zref', 'CI_G06Q_qref') LOOP
    IF abs(r.account_prior - g) > 1e-9 OR r.account_prior = 0 THEN
      RAISE EXCEPTION '%: prior=% (期望全库平均 %)', r.source_note_id, r.account_prior, g;
    END IF;
  END LOOP;
  -- (5) 整架: rank_score 不空, 账号项在 [0, 0.3]; 方向: 先验低 (弱账号) 的账号项更大
  IF EXISTS (SELECT 1 FROM truth_vault.v_flywheel_lesson_cards
             WHERE rank_score IS NULL OR account_prior IS NULL OR account_prior < 0 OR account_prior > 1) THEN
    RAISE EXCEPTION 'rank_score 有空值或账号先验越界';
  END IF;
  -- fresh (爆 0.3 + 状态字段 0.2, 先验 0.5) 对 card (大爆 0.5 + 0.2, 先验 0.46): 去掉这两项, 先验低的 card 账号项更大
  IF NOT (SELECT (c.rank_score - c.recency_weight - 0.7) > (f.rank_score - f.recency_weight - 0.5)
          FROM truth_vault.v_flywheel_lesson_cards f, truth_vault.v_flywheel_lesson_cards c
          WHERE f.source_note_id = 'CI_G06A_fresh' AND c.source_note_id = 'CI_G06A_card') THEN
    RAISE EXCEPTION '方向反了: 先验低的 card 账号项应大于先验高的 fresh';
  END IF;
  RAISE NOTICE '  ✓ v1.34 书架账号先验: 准入同 v1_14 (12 张一张不多一张不少); 只数严格更早、清洗后、跨项目的标签; m=10 收缩手算对; 无历史 → 项目基线; 项目无正例 → 全库平均; 不空、不越界、方向对; v1_14 的 24 列不变';
END $$;
ROLLBACK;
