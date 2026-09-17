-- ═══════════════════════════════════════════════════════════════════════════
-- notes v1.11 · 评价来源可追溯 (TV-01)
-- ═══════════════════════════════════════════════════════════════════════════
-- 2026-09-17 外部评测 TV-01 (P1):
--   sync_autowriter_decisions_to_prepublish.py 把【所有】AW 决策一律写成
--   evaluator_type='human', 且 evaluator_id 填的是稿件 owner(作者), 不是审稿人。
--   AW 侧 autowriter.items 其实已有 decision_source / reviewer_id / decided_at
--   三列, TV 一个都没读。
--
-- 生产实况核过(2026-09-17): 598 条评价【全部】evaluator_type='human',
--   而 AW 侧对应 598 条 item 的 decision_source 【全部为 NULL】。
--   → 所以"机器判定被洗成人工"这件事目前【还没真的发生】(AW 还没开始写那一列),
--     真实情况是另一种坏: 598 条的来源其实【未知】, 却都署名人工、且署到了作者头上。
--   → 评测给的处置是对的: 历史 NULL 归入「待核验」, 不整体补成 human。
--
-- 本迁移做三件事:
--   ① evaluator_type 增加 'unverified' 一档 —— 「来源未核实」不是「人工」;
--   ② 唯一索引从【只管 human】扩到【全类型】—— 原索引只在 evaluator_type='human'
--      时生效, 一旦开始写 rule_based / unverified 行, 并发写就没有 DB 层防线了;
--   ③ 回填: 对应 AW item 的 decision_source 为 NULL 的 human 行 → unverified。
--
-- 幂等: 三步都可重复执行。CI 会连跑两遍。
-- ═══════════════════════════════════════════════════════════════════════════

-- ── ① evaluator_type 增加 'unverified' ────────────────────────────────────
-- 'rule_based' 早就在允许集里, 机器判定(auto_hard_rule / auto_dedup / system)
-- 直接复用它, 不需要新增。缺的只有"来源未知"这一档。
ALTER TABLE truth_vault.prepublish_evaluations
    DROP CONSTRAINT IF EXISTS prepublish_evaluations_evaluator_type_check;

ALTER TABLE truth_vault.prepublish_evaluations
    ADD CONSTRAINT prepublish_evaluations_evaluator_type_check
    CHECK (evaluator_type IN (
        'persona', 'critic', 'human', 'model', 'rule_based',
        'autowriter_select_best',
        'unverified'   -- 2026-09-17 TV-01: 决策来源缺失/无法识别, 待核验
    ));

-- ── ② 唯一索引扩到全类型 ──────────────────────────────────────────────────
-- 原定义(2026-05-22 audit P1/P2-4):
--   CREATE UNIQUE INDEX ... (autowriter_item_id, evaluator_type)
--   WHERE autowriter_item_id IS NOT NULL AND evaluator_type = 'human'
-- 当时全表只写 human, 所以够用。现在同步会写 human / rule_based / unverified
-- 三类, 谓词里的 evaluator_type='human' 会让另外两类【完全没有并发防线】。
-- 去掉那个条件即可: 键仍是 (item_id, evaluator_type), 所以同一条 item 依然允许
-- 并存不同类型的评价(比如人工 + 未来的 model critic), 只是同类型不许重复。
--
-- 索引名保持不变 —— scripts/verify_supabase_state.sql 按这个名字断言它存在。
DROP INDEX IF EXISTS truth_vault.idx_tv_evals_aw_item_evaluator_uniq;

CREATE UNIQUE INDEX idx_tv_evals_aw_item_evaluator_uniq
    ON truth_vault.prepublish_evaluations (autowriter_item_id, evaluator_type)
    WHERE autowriter_item_id IS NOT NULL;

-- ── ③ 回填历史 human 行 ───────────────────────────────────────────────────
-- 只回填【能证明来源未知】的行: 对应 AW item 的 decision_source IS NULL。
-- 不盲扫全表改 —— 万一以后有别的路径写进真正的人工评价, 不能一起误伤。
--
-- ⚠️ 判据必须是【那三列在不在】, 不能只判表在不在。
--    CI 的 autowriter.items 是个 stub(id/status/example_label/user_id + 002/003 加的几列),
--    表【在】但三列【不在】—— 只判表存在的话, 下面 UPDATE 引用 i.decision_source 会直接
--    ERROR: column does not exist, 把整个 sql job 打红。
--    生产上三列齐备, 照常执行。这跟同步脚本的降级哲学是同一条: 读不到来源就别猜。
DO $$
DECLARE
    n_updated INT := 0;
    has_cols BOOLEAN;
BEGIN
    SELECT count(*) = 3 INTO has_cols
      FROM information_schema.columns
     WHERE table_schema = 'autowriter' AND table_name = 'items'
       AND column_name IN ('decision_source', 'reviewer_id', 'decided_at');

    IF has_cols THEN
        -- (a) 来源未知 → unverified, 且清掉 evaluator_id。
        --     作者不是审稿人: 留着 owner 等于继续声称"这条是他评的"。
        UPDATE truth_vault.prepublish_evaluations e
           SET evaluator_type = 'unverified',
               evaluator_id   = NULL
          FROM autowriter.items i
         WHERE e.autowriter_item_id = i.id
           AND e.evaluator_type = 'human'
           AND i.decision_source IS NULL;
        GET DIAGNOSTICS n_updated = ROW_COUNT;
        RAISE NOTICE 'TV-01 回填(a) 来源未知: % 行 human → unverified', n_updated;

        -- (b) 来源已知【且不是人工】→ rule_based, evaluator_id 记具体规则名。
        --     生产上今天没有这种行(598 条源全空), 但只修"今天恰好存在的那一种"不够 ——
        --     AW 哪天补写了 decision_source 再跑本迁移, 这批必须也能被纠正,
        --     否则机器判定会以人工身份永久留在校准表里。
        UPDATE truth_vault.prepublish_evaluations e
           SET evaluator_type = 'rule_based',
               evaluator_id   = i.decision_source
          FROM autowriter.items i
         WHERE e.autowriter_item_id = i.id
           AND e.evaluator_type = 'human'
           AND i.decision_source IS NOT NULL
           AND i.decision_source <> 'human';
        GET DIAGNOSTICS n_updated = ROW_COUNT;
        RAISE NOTICE 'TV-01 回填(b) 机器判定: % 行 human → rule_based', n_updated;

        -- (c) 确实是人工, 但 evaluator_id 填的是作者 → 换成真正的 reviewer。
        --     只在 reviewer_id 在场时改; 缺 reviewer 的人工决定留在 human 但把
        --     evaluator_id 清掉 —— 宁可"人工但不知是谁", 不要"错认成作者审的"。
        UPDATE truth_vault.prepublish_evaluations e
           SET evaluator_id = i.reviewer_id::TEXT
          FROM autowriter.items i
         WHERE e.autowriter_item_id = i.id
           AND e.evaluator_type = 'human'
           AND i.decision_source = 'human'
           AND i.reviewer_id IS NOT NULL
           AND e.evaluator_id IS DISTINCT FROM i.reviewer_id::TEXT;
        GET DIAGNOSTICS n_updated = ROW_COUNT;
        RAISE NOTICE 'TV-01 回填(c) 审稿人归位: % 行 evaluator_id 作者 → reviewer', n_updated;

        UPDATE truth_vault.prepublish_evaluations e
           SET evaluator_id = NULL
          FROM autowriter.items i
         WHERE e.autowriter_item_id = i.id
           AND e.evaluator_type = 'human'
           AND i.decision_source = 'human'
           AND i.reviewer_id IS NULL
           AND e.evaluator_id IS NOT NULL;
        GET DIAGNOSTICS n_updated = ROW_COUNT;
        RAISE NOTICE 'TV-01 回填(d) 人工但无 reviewer: % 行 evaluator_id 清空', n_updated;
    ELSE
        RAISE NOTICE 'TV-01 回填: 跳过 —— autowriter.items 没有 decision_source/reviewer_id/decided_at '
                     '三列(CI stub 或未跑 AW 的 deskcore 迁移)。历史行维持原状, 不猜来源。';
    END IF;
END $$;

COMMENT ON COLUMN truth_vault.prepublish_evaluations.evaluator_type IS
    '评价来源类别。human=已核实的人工审稿(evaluator_id 必须是 reviewer 而非作者); '
    'rule_based=机器判定(auto_hard_rule/auto_dedup/system, evaluator_id 记具体规则名); '
    'unverified=来源缺失或无法识别, 待核验 —— 【不得】当作人工评价统计。';
