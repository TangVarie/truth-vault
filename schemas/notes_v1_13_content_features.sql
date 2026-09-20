-- ════════════════════════════════════════════════════════════════════
-- truth_vault v1.13 · 内容特征层（docs/28 · D-065 / D-070 P1）
-- ════════════════════════════════════════════════════════════════════
-- 三张表 + 一个视图, 全部幂等（IF NOT EXISTS / OR REPLACE）, CI 连跑两遍。
--   note_feature_answers  Layer 1 · 原子问题的答案（事实, 不是判断; D-004 extract_features）
--   feature_validation    闸二结论 · 每个特征值一行（validated / no_signal / reversed / ...）
--   content_scores        Layer 2 · 打分器输出（D-004: 管家没有 score, 所以不在 Layer 1）
--   (v_l2_labels          由 notes_v1_15 提供, 本迁移只读, 见第 4 节)
--   v_feature_contrast    每个项目 × 每个特征值的 2×2 计数, 闸二的输入
-- 不建跨 schema 外键: subject_id 可能指 autowriter.versions（同 D-064 的做法, 悬空靠
-- verify_supabase_state.sql #83 查）。
--
-- 部署: 必须在 notes_v1_15 之后（v_feature_contrast 读 v_l2_labels）。
--   psql -d <shared_supabase> -f notes_v1_13_content_features.sql
-- 编号说明: 13 是草案编号（docs/28 附录 A）, 落仓晚于 v1_14 / v1_15, 编号不改。
-- ════════════════════════════════════════════════════════════════════

-- 1. 原子问题答案 ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS truth_vault.note_feature_answers (
    subject_type     TEXT NOT NULL CHECK (subject_type IN ('note', 'aw_version')),
    subject_id       TEXT NOT NULL,   -- note → notes.note_id; aw_version → autowriter.versions.id::text
    question_id      TEXT NOT NULL,   -- 问题库里的 id
    question_version INT  NOT NULL,   -- 改题 = 版本 +1, 旧答案保留不覆盖
    bank_version     TEXT NOT NULL,   -- 'fq-v0.1'
    bank_sha256      TEXT NOT NULL,   -- 跑的时候对问题库文件算的校验和（同 D-041 的纪律）
    extractor        TEXT NOT NULL,   -- 'code:v1' / 'llm:<模型>' / 'jev:<模型>' / 'human:<人>'
    run_tag          TEXT NOT NULL DEFAULT 'primary',  -- 只有 primary 进分析; retest-* / gate1-* 只给闸一
    answer           TEXT,            -- 闭集取值; NULL = 无效, 原因见 invalid_reason
    evidence         TEXT,            -- 答「是」时引用的原文片段; 代码校验它必须是原文子串
    prob             REAL,            -- 有概率才填（Jev / 多次采样的一致率）, 否则 NULL
    invalid_reason   TEXT,            -- evidence_not_found / out_of_vocab / text_too_short / ...
    extracted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (subject_type, subject_id, question_id, question_version, extractor, run_tag)
);
CREATE INDEX IF NOT EXISTS idx_tv_nfa_question
    ON truth_vault.note_feature_answers (question_id, question_version, answer);
ALTER TABLE truth_vault.note_feature_answers ENABLE ROW LEVEL SECURITY;

-- 2. 闸二结论 ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS truth_vault.feature_validation (
    question_id           TEXT NOT NULL,
    question_version      INT  NOT NULL,
    answer                TEXT NOT NULL,  -- bool 题只登记「是」; choice 题每个取值一行
    bank_version          TEXT NOT NULL,
    gate2_run             TEXT NOT NULL,  -- 'gate2-2026-10-xx'
    status                TEXT NOT NULL CHECK (status IN
                              ('validated',     -- 过了闸二全部判据
                               'no_signal',     -- 置信区间跨 1
                               'reversed',      -- 显著, 但和预注册方向相反: 不自动用, 拿来讨论
                               'confounded',    -- 加上账号先验分层后方向变了或效应缩了 30% 以上
                               'unreliable',    -- 闸一没过（测不准）
                               'insufficient')),-- 有这个取值的笔记 < 30 条, 或大项目 < 3 个
    hypothesis            TEXT CHECK (hypothesis IN ('+', '-', '?', '0')),  -- 预注册方向（'0' = 占位题）
    mh_odds_ratio         REAL,           -- 按项目分层合并的优势比
    ci_low                REAL,
    ci_high               REAL,
    q_value               REAL,           -- BH 校正后
    big_projects_same_dir INT,            -- 大项目里与预注册方向一致的个数
    big_projects_n        INT,
    summary               TEXT,           -- 给人读的一句话, 如「5 个项目 4 个同向, 项目内爆率 9.1% vs 5.2%」
    decided_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (question_id, question_version, answer, gate2_run)
);
ALTER TABLE truth_vault.feature_validation ENABLE ROW LEVEL SECURITY;

-- 3. 打分器输出（Layer 2）───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS truth_vault.content_scores (
    subject_type    TEXT NOT NULL CHECK (subject_type IN ('note', 'aw_version')),
    subject_id      TEXT NOT NULL,
    project_id      TEXT NOT NULL,
    scorer_version  TEXT NOT NULL,        -- 冻结的打分器: 权重快照 + bank_version + 切点
    score           REAL NOT NULL,
    pct_in_project  REAL CHECK (pct_in_project >= 0 AND pct_in_project <= 1),  -- 0 = 最差
    cutpoints       TEXT NOT NULL CHECK (cutpoints IN ('project', 'pooled')),  -- 新项目没历史就用全库
    shadow          BOOLEAN NOT NULL DEFAULT TRUE,   -- 影子期只记不用
    scored_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (subject_type, subject_id, scorer_version)
);
ALTER TABLE truth_vault.content_scores ENABLE ROW LEVEL SECURITY;

-- 4. 标签口径 ─────────────────────────────────────────────────────
-- ⚠️ v_l2_labels 不在本迁移里定义。它由 notes_v1_15_l2_labels.sql 提供 (D-067, 生产 09-19 已 apply),
--    本迁移只读它。草案第一版曾在这里逐字照搬 l2-feasibility §8.6 的 d (带 a/b/c/d 四处问题),
--    已删: v1_13 若再 CREATE OR REPLACE 它, 会把生产上修好的口径盖回去 (codex review on #139)。

-- 5. 闸二输入: 每个项目 × 每个特征值的 2×2 ─────────────────────────
-- a = 有这个特征值且爆  b = 有且趴  c = 没有且爆  d = 没有且趴
-- 「没有」= 同一道题答了别的值; 答案无效（NULL）的行不进分母。
-- ⚠️ bank_sha256 必须在分组键和输出里 (codex review on #141): 问题库文件改过之后、
--    重标只跑了一半时, 同一个 (question_version, bank_version, extractor) 下会同时存在
--    两份校验和的答案; 不分组就被静默汇到一起, 而闸二预注册承诺的是「这一跑的快照」
--    (docs/28 §6.2), 附录 B 的查询得能按校验和挑出恰好一份冻结的库。
CREATE OR REPLACE VIEW truth_vault.v_feature_contrast AS
WITH ans AS (
    SELECT a.subject_id AS note_id, a.question_id, a.question_version,
           a.bank_version, a.bank_sha256, a.extractor, a.answer
    FROM truth_vault.note_feature_answers a
    WHERE a.subject_type = 'note' AND a.run_tag = 'primary' AND a.answer IS NOT NULL
), lab AS (
    SELECT l.note_id, l.project_id, l.y, ans.question_id, ans.question_version,
           ans.bank_version, ans.bank_sha256, ans.extractor, ans.answer
    FROM truth_vault.v_l2_labels l
    JOIN ans USING (note_id)
), vals AS (
    SELECT DISTINCT question_id, question_version, bank_version, bank_sha256, extractor, answer AS value
    FROM lab
)
SELECT l.project_id, v.question_id, v.question_version, v.bank_version, v.bank_sha256, v.extractor, v.value,
       count(*) FILTER (WHERE l.answer =  v.value AND l.y = 1) AS a,
       count(*) FILTER (WHERE l.answer =  v.value AND l.y = 0) AS b,
       count(*) FILTER (WHERE l.answer <> v.value AND l.y = 1) AS c,
       count(*) FILTER (WHERE l.answer <> v.value AND l.y = 0) AS d
FROM vals v
JOIN lab l USING (question_id, question_version, bank_version, bank_sha256, extractor)
GROUP BY 1, 2, 3, 4, 5, 6, 7;

-- 6. note_features 的分工（docs/28 §4.4, D-065 续 第 4 条）─────────────
-- 数值原值仍写 note_features 现有四列 (title_len / body_len / hashtag_count / mention_count);
-- 分档值与模型答案进 note_feature_answers。下面六列被问题库取代, 只加 COMMENT, 不删。
COMMENT ON COLUMN truth_vault.note_features.opener_type          IS '弃用 (D-065): 由 note_feature_answers.opening_type 取代, 从未被写过, 保留不删';
COMMENT ON COLUMN truth_vault.note_features.title_hook_type      IS '弃用 (D-065): 由 note_feature_answers.title_is_question 等标题题取代, 保留不删';
COMMENT ON COLUMN truth_vault.note_features.has_specific_scene   IS '弃用 (D-065): 由 note_feature_answers.has_specific_place 取代, 保留不删';
COMMENT ON COLUMN truth_vault.note_features.has_dialogue         IS '弃用 (D-065): 由 note_feature_answers.has_direct_quote 取代, 保留不删';
COMMENT ON COLUMN truth_vault.note_features.compliance_red_flags IS '弃用 (D-065): 合规观察走 note_feature_answers.efficacy_promise (永不下发), 保留不删';
COMMENT ON COLUMN truth_vault.note_features.ai_smell_score       IS '弃用 (D-065): 不做自由打分 (R-003), 保留不删';
