-- notes_v1_20 · evaluator_type 加 'human_via_agent'（审计 A-01, D-102, 2026-10-09）
--
-- 为什么: deskcore 的 review_drafts 写的决定是【模型替用户记的】。实查 32 条 decision_source='human' 全嵌在模型自己的
-- 工具链里 (check → commit → review → export, commit 后 10–27 s 整批通过), 库里分不出是人说的还是模型自作主张。
-- aw 侧 (migration 012) 起 MCP 工具一律写 decision_source='human_via_agent' (+ decision_note 用户原话 + decided_within_s),
-- 'human' 只留给 Streamlit 真人点击。TV 这边原样映成 evaluator_type='human_via_agent':
--   · 不是人审真值 —— 真值 / 校准只认 'human';
--   · 也不是机器判定 —— 不混进 rule_based;
--   · evaluator_id 记 reviewer (= 作者本人, 这是该类型的语义)。
-- 幂等。不回填历史 (那 32 条由 aw 侧按证据改标, 夜跑同步会自己收敛到新类型)。
BEGIN;

ALTER TABLE truth_vault.prepublish_evaluations
    DROP CONSTRAINT IF EXISTS prepublish_evaluations_evaluator_type_check;
ALTER TABLE truth_vault.prepublish_evaluations
    ADD CONSTRAINT prepublish_evaluations_evaluator_type_check
    CHECK (evaluator_type IN (
        'persona', 'critic', 'human', 'model', 'rule_based',
        'autowriter_select_best',
        'unverified',        -- v1.11 (2026-09-17): 来源缺失/无法识别, 待核验
        'human_via_agent'    -- v1.20 (2026-10-09): 模型替用户记的决定 (deskcore review_drafts), 不当人审真值
    ));

-- 唯一索引谓词扩到同步拥有的四类 (v1.11 的理由不变: 这几类每条 item 至多一行; persona / critic / model 照旧可多行)。
-- 索引名保持不变 —— scripts/verify_supabase_state.sql 按这个名字断言它存在。
DROP INDEX IF EXISTS truth_vault.idx_tv_evals_aw_item_evaluator_uniq;
CREATE UNIQUE INDEX idx_tv_evals_aw_item_evaluator_uniq
    ON truth_vault.prepublish_evaluations (autowriter_item_id, evaluator_type)
    WHERE autowriter_item_id IS NOT NULL
      AND evaluator_type IN ('human', 'rule_based', 'unverified', 'human_via_agent');

COMMENT ON CONSTRAINT prepublish_evaluations_evaluator_type_check ON truth_vault.prepublish_evaluations IS
    'human = 真人点击 (Streamlit); human_via_agent = 模型替用户记的 (deskcore review_drafts, 带 decision_note); rule_based = 机器规则; unverified = 来源未知。真值只认 human (D-102)。';

COMMIT;
