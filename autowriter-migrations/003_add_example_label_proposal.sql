-- ════════════════════════════════════════════════════════════════════
-- autowriter-migrations/003_add_example_label_proposal.sql
-- ════════════════════════════════════════════════════════════════════
--
-- P2 (D-027): 给 autowriter.items 加 example_label_proposal 列, 作为
-- negative example 候选队列.
--
-- 用法:
--   - extract_negative_examples_from_autowriter.py 把候选 item_id 写入
--     example_label_proposal (例如 'negative_manual_rewrite')
--   - autowriter Memory Manager UI 加 "负例候选审核" tab 拉取这些行
--   - 用户在 UI 中 "确认为负例" → example_label='negative',
--     example_label_proposal=NULL
--   - autowriter build_system_prompt 只看 example_label, 不看 proposal,
--     所以候选不会污染 negative pool — 强制人工 review 前置
--
-- 部署:
--   psql -d <shared_supabase> -f 003_add_example_label_proposal.sql
-- ════════════════════════════════════════════════════════════════════

ALTER TABLE autowriter.items
    ADD COLUMN IF NOT EXISTS example_label_proposal TEXT
    CHECK (example_label_proposal IS NULL OR example_label_proposal IN (
        'negative_manual_rewrite',  -- 来源 A: 用户手动重写过 AI 版 (高置信)
        'negative_feedback_iter',   -- 来源 B: 用户给 feedback 后 AI 重生成过 (中)
        'negative_batch_rejected'   -- 来源 C: 同 batch 有 approved, 本 item 卡 (低)
    ));

CREATE INDEX IF NOT EXISTS items_proposal_idx
    ON autowriter.items (example_label_proposal)
    WHERE example_label_proposal IS NOT NULL;

COMMENT ON COLUMN autowriter.items.example_label_proposal IS
    'Negative-example candidate label, written by '
    'truth-vault/scripts/extract_negative_examples_from_autowriter.py. '
    'Read by autowriter Memory Manager UI for human review. '
    'Once reviewed, the UI moves the value into example_label (or clears '
    'it on dismiss). build_system_prompt does NOT read this column, so '
    'unreviewed candidates do not flow into the few-shot pool.';

-- 校验
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'autowriter' AND table_name = 'items'
        AND column_name = 'example_label_proposal'
    ) THEN
        RAISE EXCEPTION 'Migration failed: example_label_proposal not present';
    END IF;
END $$;
