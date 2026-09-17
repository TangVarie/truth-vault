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
--
-- ⚠️ 但【不能】简单去掉谓词扩到全类型。第一版就是那么写的, CI 直接炸:
--      ERROR: could not create unique index "idx_tv_evals_aw_item_evaluator_uniq"
--    因为同一条 item 有【两条 persona 评价】(evaluator_id = p1 / p2)。
--    那不是脏数据 —— 多个 persona 各自评同一条稿本来就是这张表的预期用法,
--    critic / model 同理。原索引只覆盖 human, 正是因为【只有 human 这一类
--    "一条 item 最多一条"】, 而当时只有 human 会被写入。
--    "收紧约束总是更安全"是个错觉: 收紧会把本来合法的数据判成非法。
--
-- 所以谓词从"只有 human"扩成"本同步会写的那三类", 不多不少:
--   · 这三类每条 item 至多一行(AW 的 decision_source 每条 item 只有一个值),
--     所以唯一性是它们的真实语义;
--   · persona / critic / model / autowriter_select_best 不受影响, 照旧可以多行。
-- 相对原索引是严格加强(human 的保护一点没少), 对其余类型则一点没动。
--
-- 索引名保持不变 —— scripts/verify_supabase_state.sql 按这个名字断言它存在。
DROP INDEX IF EXISTS truth_vault.idx_tv_evals_aw_item_evaluator_uniq;

CREATE UNIQUE INDEX idx_tv_evals_aw_item_evaluator_uniq
    ON truth_vault.prepublish_evaluations (autowriter_item_id, evaluator_type)
    WHERE autowriter_item_id IS NOT NULL
      AND evaluator_type IN ('human', 'rule_based', 'unverified');

-- ── ③ 回填: 把同步管的三类 evaluator 行对齐到 AW 的真实来源 ────────────────
-- 只动【本同步拥有的三类】(human / rule_based / unverified) 且 join 得上 AW item 的行。
-- persona / critic / model 是别的链路写的, 一概不碰。
--
-- ⚠️ 映射必须和 scripts/sync_autowriter_decisions_to_prepublish.py 的 _provenance()
--    【逐字一致】(codex review P2)。第一版写成 `decision_source IS NOT NULL AND
--    <> 'human' → rule_based`, 于是空串 / 纯空格 / 没见过的新取值(比如某天 AW 加的
--    'auto_v2')全被当成 rule_based, 而同步脚本对同一个值给的是 unverified ——
--    同一条 item 归到哪一类, 取决于是迁移先跑还是同步先跑。而且一旦写成
--    rule_based 就再也修不回来: 老的四条分支都只看 evaluator_type='human' 的行。
--    所以这里改成【按目标态收敛】: 算出该是什么, 和现状不同就改。天然幂等,
--    也天然可自愈 —— 被上一版写歪的行, 再跑一次就纠正了。
--
-- ⚠️ 判据必须是【那三列在不在】, 不能只判表在不在。
--    CI 的 autowriter.items 是个 stub(id/status/example_label/user_id + 002/003 加的几列),
--    表【在】但三列【不在】—— 只判表存在的话, 下面 UPDATE 引用 i.decision_source 会直接
--    ERROR: column does not exist, 把整个 sql job 打红。
--    生产上三列齐备, 照常执行。这跟同步脚本的降级哲学是同一条: 读不到来源就别猜。
DO $$
DECLARE
    n_updated INT := 0;
    n_blocked INT := 0;
    has_cols  BOOLEAN;
BEGIN
    SELECT count(*) = 3 INTO has_cols
      FROM information_schema.columns
     WHERE table_schema = 'autowriter' AND table_name = 'items'
       AND column_name IN ('decision_source', 'reviewer_id', 'decided_at');

    IF has_cols THEN
        -- target: _provenance() 的 SQL 镜像。s = 去空白后的 decision_source。
        --   s 为空        → ('unverified', NULL)          来源未知, 不猜, 也不留作者
        --   s = 'human'   → ('human', reviewer_id)        人审; 无 reviewer 则留空
        --   s ∈ 机器三种  → ('rule_based', s)             记具体规则名, 可分开统计
        --   其余          → ('unverified', s)             没见过的新取值: 不猜, 但留痕
        WITH target AS (
            SELECT e.evaluation_id,
                   CASE WHEN s.v IS NULL             THEN 'unverified'
                        WHEN s.v = 'human'           THEN 'human'
                        WHEN s.v IN ('auto_hard_rule', 'auto_dedup', 'system')
                                                     THEN 'rule_based'
                        ELSE 'unverified' END           AS want_type,
                   CASE WHEN s.v IS NULL             THEN NULL
                        WHEN s.v = 'human'           THEN i.reviewer_id::TEXT
                        ELSE s.v END                    AS want_id
              FROM truth_vault.prepublish_evaluations e
              JOIN autowriter.items i ON i.id = e.autowriter_item_id
              CROSS JOIN LATERAL (SELECT nullif(btrim(i.decision_source), '') AS v) s
             WHERE e.evaluator_type IN ('human', 'rule_based', 'unverified')
        ),
        -- 同一条 item 的目标类型若已被【另一行】占着, 改过去会撞唯一索引。
        -- 这种行是历史脏数据(同步的就地升级路径不会造出来), 只报数不硬改,
        -- 免得整个迁移因为一条脏数据回滚。
        todo AS (
            SELECT t.* FROM target t
              JOIN truth_vault.prepublish_evaluations e USING (evaluation_id)
             WHERE (e.evaluator_type, e.evaluator_id)
                   IS DISTINCT FROM (t.want_type, t.want_id)
               AND NOT EXISTS (
                     SELECT 1 FROM truth_vault.prepublish_evaluations x
                      WHERE x.autowriter_item_id = e.autowriter_item_id
                        AND x.evaluator_type     = t.want_type
                        AND x.evaluation_id     <> e.evaluation_id)
        )
        UPDATE truth_vault.prepublish_evaluations e
           SET evaluator_type = todo.want_type,
               evaluator_id   = todo.want_id
          FROM todo
         WHERE e.evaluation_id = todo.evaluation_id;
        GET DIAGNOSTICS n_updated = ROW_COUNT;
        RAISE NOTICE 'TV-01 回填: % 行对齐到 AW 真实来源', n_updated;

        SELECT count(*) INTO n_blocked
          FROM truth_vault.prepublish_evaluations e
          JOIN autowriter.items i ON i.id = e.autowriter_item_id
          CROSS JOIN LATERAL (SELECT nullif(btrim(i.decision_source), '') AS v) s
          CROSS JOIN LATERAL (SELECT CASE
                        WHEN s.v IS NULL   THEN 'unverified'
                        WHEN s.v = 'human' THEN 'human'
                        WHEN s.v IN ('auto_hard_rule', 'auto_dedup', 'system')
                                           THEN 'rule_based'
                        ELSE 'unverified' END AS want_type) w
         WHERE e.evaluator_type IN ('human', 'rule_based', 'unverified')
           AND e.evaluator_type <> w.want_type
           AND EXISTS (SELECT 1 FROM truth_vault.prepublish_evaluations x
                        WHERE x.autowriter_item_id = e.autowriter_item_id
                          AND x.evaluator_type     = w.want_type
                          AND x.evaluation_id     <> e.evaluation_id);
        IF n_blocked > 0 THEN
            RAISE WARNING 'TV-01 回填: % 行没能对齐 —— 目标类型已被同一 item 的另一行占着, '
                          '属历史脏数据, 需人工判定留哪条。', n_blocked;
        END IF;
    ELSE
        RAISE NOTICE 'TV-01 回填: 跳过 —— autowriter.items 没有 decision_source/reviewer_id/decided_at '
                     '三列(CI stub 或未跑 AW 的 deskcore 迁移)。历史行维持原状, 不猜来源。';
    END IF;
END $$;

COMMENT ON COLUMN truth_vault.prepublish_evaluations.evaluator_type IS
    '评价来源类别。human=已核实的人工审稿(evaluator_id 必须是 reviewer 而非作者); '
    'rule_based=机器判定(auto_hard_rule/auto_dedup/system, evaluator_id 记具体规则名); '
    'unverified=来源缺失或无法识别, 待核验 —— 【不得】当作人工评价统计。';
