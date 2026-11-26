-- ════════════════════════════════════════════════════════════════════
-- truth_vault v1.29 · 闸三的分记下「用的是哪份正文」(AU-F02b ②, 外部审计 11-02 F02, D-137)
-- ════════════════════════════════════════════════════════════════════
--
-- 改什么: 给 truth_vault.content_scores 加一列可空的 input_sha (TEXT), 加一句列注释。只做这两件。
--   以后夜跑闸三 (gate3_score.py) 每打一条分, 顺手记下这篇在打分那一刻的 notes.essence_content_sha,
--   也就是打分用的 essence 标签是从哪份正文标出来的。以后正文改了、essence 重标了, 比一下这两个 sha
--   就知道这条分用的是旧正文 (闸三「入库即打分」, 分不重打, D-118)。
--
-- 不改什么:
--   · 已有的行一行不动: 今天的约 909 行 input_sha 都是空, 不回填 (D-137 §6 的敏感度检查从 audit_log 还原正文, 不靠这一列)。
--   · 不加约束、不加索引、不改打分器、不改冻结文件, 写作台和看板都不读这张表的这一列。
--   · 不改任何已有的数据, 所以不需要备份。
--
-- 怎么跑: owner 在 Supabase SQL editor 整份跑一次。可以重跑 (ADD COLUMN IF NOT EXISTS; COMMENT 重复执行只是覆盖同一句)。
--   先合代码还是先跑都行: 没跑之前 gate3_score.py 写库时报「没有这一列」, 喊一次 warning、去掉这一列重写, 照旧打分。
-- 跑完看最后一个 SELECT: has_input_sha = true; rows_total 是现有行数, rows_with_sha = 0 (第二天夜跑之后才开始有)。
-- 之后对照 verify_supabase_state.sql #108 (第一条带 input_sha 的分之后, 还有空 input_sha 的行数; 应为 0)。
-- ════════════════════════════════════════════════════════════════════

ALTER TABLE truth_vault.content_scores ADD COLUMN IF NOT EXISTS input_sha TEXT;

COMMENT ON COLUMN truth_vault.content_scores.input_sha IS
  '打分那一刻这篇的 notes.essence_content_sha (打分用的 essence 标签来自哪份正文)。gate3_score.py 写; '
  'v1_29 之前打的分为空, 不回填。和 notes.essence_content_sha 不同 = 正文后来改过 (AU-F02b ②, D-137)。';

-- 回读
SELECT
  EXISTS (SELECT 1 FROM information_schema.columns
          WHERE table_schema = 'truth_vault' AND table_name = 'content_scores' AND column_name = 'input_sha') AS has_input_sha,
  (SELECT count(*) FROM truth_vault.content_scores) AS rows_total,
  (SELECT count(*) FROM truth_vault.content_scores WHERE input_sha IS NOT NULL) AS rows_with_sha;
