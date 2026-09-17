-- truth_vault v1.12 · 判爆只看评论数 (D-062, 2026-09-17 运营对齐)
-- ════════════════════════════════════════════════════════════════════
-- 运营口径(data-analysis/ops-answers-2026-09-17.md Q1):
--   爆贴【只看评论数】, 全项目统一: 爆 ≥ 50 / 大爆 ≥ 100 / 评估中 20~50 / 趴 < 20。
--   有评论数的 5 个项目逐行验过, 运营手标与这个门槛几乎全对上。
--
-- 五件事:
--   1. notes 加 comments_count —— 判爆的唯一依据此前只以 raw_extra 键存在
--      (「实时数据.评论数」/「评论数」), 库里没有 typed 列。
--   2. tier CHECK 加 '评估中' —— 它是 20~50 条评论的正式档位, 不是"还没下结论";
--      此前 16 张表的 mapping 都把它映成 '未知'。
--   3. 回填【只在首次升级时跑一次】: 把 D-062 之前按互动量推断的行退回"没有推断"。
--      旧的数值推断按【互动量】过项目阈值升 tier, 和运营的尺子(评论数)不是一把;
--      43 条里 12 条来自评估中(按口径根本不是爆), 其余 31 条没有状态列可依。
--      退回之后由同步脚本用新尺子(comments_count ≥50/≥100)重新推断 —— 迁移里【不】
--      重写一遍推断规则, 那是 D-061 里回填 SQL 与 _provenance() 分叉的老毛病。
--      ⚠️ 新引擎推出来的行同样是 tier_source='数值推断', 光看这个标签分不出新旧
--      (codex review on #130, P1): 第一版无条件清所有 数值推断 行, 重跑一次就会把
--      TGV 按评论数推回来的 爆/大爆 清掉, 而 TGV 是 on-demand 表, 会一直错下去。
--      所以回填以「comments_count 列此前不存在」为判据 —— 这一列是本迁移加的:
--      它不在 = 库还在 D-062 之前 = 所有 数值推断 行都是旧尺子的, 回填;
--      它在   = 本迁移已经应用过, 回填【跳过】, 重跑只刷 CHECK / 注释 / 阈值 / 视图。
--   4. projects.tier_thresholds 清空 —— mapping 里的键已删, 但 ensure_project_exists()
--      对 None 值不写(只更新送了的列), 旧值会一直留在库里(codex review on #130, P2)。
--      mapping_config 快照里的同名键一并剥掉。列本身保留(值恒 NULL), 不破坏旧查询。
--   5. v_tier_discrepancy 改成评论数口径 —— 它此前按 projects.tier_thresholds × 互动量
--      算"人工标注 vs 数值矛盾", 尺子作废后它对着生产吐了 175 条过期结论。
--      门槛 50/100 与引擎 _COMMENT_TIER_BAO/_DABAO 是同一对数字, CI 两边都钉着;
--      它是只读复核视图、不是第二个写入口, 所以允许在这里再写一遍数字。
--
-- 幂等: 可重跑。1/2/4/5 天然幂等; 3 只在首次升级时执行一次(判据见上)。
-- 应用顺序: 在 notes_v1_3_reference_tier.sql 之后(它最后一次定义 tier CHECK);
--           在 notes_v1_2_tier_discrepancy_view.sql 之后(本文件重定义那个视图)。
-- ════════════════════════════════════════════════════════════════════

-- ── 1 + 2 + 3. 评论数列 · tier CHECK · 首次升级时的回填 ──
-- 三步放同一个 DO 块: "列此前存不存在"必须在 ADD COLUMN 之前测, 回填又必须在 CHECK
-- 放开 评估中 之后跑, 所以顺序是 测 → 加列 → 改 CHECK → (首次才)回填。
DO $$
DECLARE
    fresh    BOOLEAN;
    n_pinggu INT := 0;
    n_other  INT := 0;
    n_none   INT := 0;
BEGIN
    SELECT NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'truth_vault' AND table_name = 'notes'
           AND column_name = 'comments_count'
    ) INTO fresh;

    ALTER TABLE truth_vault.notes ADD COLUMN IF NOT EXISTS comments_count INTEGER;

    ALTER TABLE truth_vault.notes DROP CONSTRAINT IF EXISTS notes_tier_check;
    ALTER TABLE truth_vault.notes ADD CONSTRAINT notes_tier_check
        CHECK (tier IN ('趴', '预备', '评估中', '爆', '大爆', '参考', '风控', '删除', '未知', '数据异常'));

    IF NOT fresh THEN
        RAISE NOTICE 'D-062 回填: comments_count 已存在 → 本迁移此前应用过, 回填跳过(新引擎按评论数推出的 数值推断 行不动)';
        RETURN;
    END IF;

    -- 回填(仅首次): 旧的按互动量数值推断 → 退回"没有推断"
    --   · 状态列里写着 评估中 的 → tier=评估中, tier_source=状态字段 (等价于 mapping 修好后同步会写的值)
    --   · 状态列在场但不是评估中 的 → tier=未知, tier_source=状态字段 (生产上当时 0 行, 为完备保留)
    --   · 压根没有状态列的 → tier=NULL, tier_source=NULL (同步对"无状态、无推断"的行就是这么写的)
    --   同步脚本下一轮会按 comments_count 重新推断 —— 有评论数的项目(TGV 14 条评论数 ≥203)会回到
    --   爆/大爆, 没有评论数的(TXQ/HXZ)按新口径就是不推断。
    UPDATE truth_vault.notes
       SET tier = '评估中', tier_source = '状态字段'
     WHERE tier_source = '数值推断'
       AND raw_extra->>'_tier_source_raw' ILIKE '%评估中%';
    GET DIAGNOSTICS n_pinggu = ROW_COUNT;

    UPDATE truth_vault.notes
       SET tier = '未知', tier_source = '状态字段'
     WHERE tier_source = '数值推断'
       AND raw_extra ? '_tier_source_raw';
    GET DIAGNOSTICS n_other = ROW_COUNT;

    UPDATE truth_vault.notes
       SET tier = NULL, tier_source = NULL
     WHERE tier_source = '数值推断';
    GET DIAGNOSTICS n_none = ROW_COUNT;

    RAISE NOTICE 'D-062 回填(首次升级): 数值推断 → 评估中 % 行 / 未知 % 行 / 无状态 % 行 (下一轮同步按评论数重推)',
                 n_pinggu, n_other, n_none;
END $$;

COMMENT ON COLUMN truth_vault.notes.comments_count IS
    '帖子当前总评论数(巡查机器人抓的实时值, 含运营自己铺的评论 —— 运营 2026-09-17 确认)。'
    '判爆的唯一依据: ≥50 爆 / ≥100 大爆。来源列: 实时数据.评论数 / 评论数。'
    '⚠️ 与 interactions 不同步: 互动量是数据回收时的快照, 评论数是实时的。';
COMMENT ON COLUMN truth_vault.notes.tier IS
    '爆款分级。运营口径(D-062): 只看评论数, 爆≥50 / 大爆≥100 / 评估中 20~50 / 趴<20, 全项目统一。'
    '评估中 是正式档位(2026-09-17 前被映成 未知)。参考 = 运营人工挑的, 不计爆款统计。';

-- ── 4. 项目级互动量阈值清空 ──
UPDATE truth_vault.projects
   SET tier_thresholds = NULL
 WHERE tier_thresholds IS NOT NULL;
UPDATE truth_vault.projects
   SET mapping_config = mapping_config - 'tier_thresholds'
 WHERE mapping_config ? 'tier_thresholds';
COMMENT ON COLUMN truth_vault.projects.tier_thresholds IS
    '已废(D-062, 2026-09-17): 判爆只看评论数、全项目统一(爆≥50 / 大爆≥100), 项目级互动量阈值'
    '不再有意义。列保留只为不破坏旧查询, 值恒为 NULL; 同步脚本不再写它, yaml 校验拒绝这个键。';

-- ── 5. v_tier_discrepancy 改口径: 人工标的 tier vs 评论数门槛 ──
-- 列集变了(th_bao/th_dabao 没了, 加 comments_count), CREATE OR REPLACE 不允许改列, 所以 DROP 重建。
-- 三类矛盾(与旧版同名, 语义换成评论数):
--   over_marked       标了 爆/大爆, 但评论数连 50 都没到
--   over_marked_soft  标了 大爆, 但评论数只到 爆 级(50~99)
--   under_marked      标了 趴 或 评估中, 但评论数已到 爆/大爆 级 —— 引擎【不会】越过这两个正式
--                     档位去推断(只在没标 / 未知 时推), 所以这类漏标只有这里能看见
-- 范围: 只看人工标注来源(状态字段/备注字段/人工补录)且有评论数的行; 数值推断/数据异常按定义不矛盾。
DROP VIEW IF EXISTS truth_vault.v_tier_discrepancy;
CREATE VIEW truth_vault.v_tier_discrepancy AS
WITH base AS (
    SELECT
        n.note_id,
        n.project_id,
        n.tier                                   AS marked_tier,
        n.tier_source,
        n.comments_count,
        n.interactions,
        n.publish_url,
        n.publish_time,
        n.data_quality_flags ->> 'synthetic'     AS synthetic
    FROM truth_vault.notes n
    WHERE n.tier_source IN ('状态字段', '备注字段', '人工补录')
      AND n.comments_count IS NOT NULL
),
scored AS (
    SELECT
        *,
        CASE
            WHEN comments_count >= 100 THEN '大爆'
            WHEN comments_count >= 50  THEN '爆'
            ELSE '趴'
        END AS numeric_implied_tier
    FROM base
)
SELECT
    note_id,
    project_id,
    marked_tier,
    numeric_implied_tier,
    tier_source,
    comments_count,
    interactions,
    synthetic,
    publish_url,
    publish_time,
    CASE
        WHEN marked_tier IN ('爆', '大爆')   AND numeric_implied_tier = '趴'            THEN 'over_marked'
        WHEN marked_tier = '大爆'            AND numeric_implied_tier = '爆'            THEN 'over_marked_soft'
        WHEN marked_tier IN ('趴', '评估中') AND numeric_implied_tier IN ('爆', '大爆') THEN 'under_marked'
    END AS discrepancy_type
FROM scored
WHERE (marked_tier IN ('爆', '大爆')   AND numeric_implied_tier = '趴')
   OR (marked_tier = '大爆'            AND numeric_implied_tier = '爆')
   OR (marked_tier IN ('趴', '评估中') AND numeric_implied_tier IN ('爆', '大爆'));

COMMENT ON VIEW truth_vault.v_tier_discrepancy IS
    '标注质量复核(D-062 评论数口径): 人工标的 tier 与评论数门槛(爆≥50 / 大爆≥100)矛盾的笔记 '
    '(over_marked / over_marked_soft / under_marked)。只暴露不自动改; 复核后在飞书改状态或走人工补录 (tier_source=人工补录)。'
    '互动量列只作参考, 不参与判定。';
