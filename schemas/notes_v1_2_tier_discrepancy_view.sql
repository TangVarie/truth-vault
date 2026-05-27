-- truth_vault.v_tier_discrepancy
-- ════════════════════════════════════════════════════════════════════
-- 标注质量复核 gate (2026-05-27)
--
-- 背景: 系统默认信任运营在飞书「流量状态」里的人工标注 (tier_source=状态字段
-- 永远优先, 数值推断只在没标时兜底, 从不覆盖人工标注). 这是有意的 —— "爆款"是
-- 人的判断, 不只是数字. 但人会手滑/标准不一致. 这个视图不自动改 tier (人仍是
-- source of truth), 只把"人工标的 tier"与"按项目 tier_thresholds 用互动量推断的
-- tier"明显矛盾的笔记暴露出来, 供人工复核。
--
-- 三类矛盾:
--   over_marked       标了 爆/大爆, 但互动连「爆」门槛都没到 (疑似高标)
--   over_marked_soft  标了 大爆, 但互动只到「爆」级 (轻微高标)
--   under_marked      标了 趴(无水花), 但互动达到「爆/大爆」级 (疑似漏标真爆款)
--
-- 范围: 只看人工标注来源 (状态字段/备注字段/人工补录); 数值推断/数据异常按定义
-- 不会矛盾, 排除。仅对在 yaml 里声明了 tier_thresholds 的项目生效。
-- ════════════════════════════════════════════════════════════════════

CREATE OR REPLACE VIEW truth_vault.v_tier_discrepancy AS
WITH base AS (
    SELECT
        n.note_id,
        n.project_id,
        n.tier                                   AS marked_tier,
        n.tier_source,
        n.interactions,
        n.publish_url,
        n.publish_time,
        n.data_quality_flags ->> 'synthetic'     AS synthetic,
        (p.tier_thresholds ->> '爆')::numeric    AS th_bao,
        (p.tier_thresholds ->> '大爆')::numeric  AS th_dabao
    FROM truth_vault.notes n
    JOIN truth_vault.projects p ON p.project_id = n.project_id
    WHERE n.tier_source IN ('状态字段', '备注字段', '人工补录')
      AND n.interactions IS NOT NULL
      AND (p.tier_thresholds ->> '爆') IS NOT NULL
),
scored AS (
    SELECT
        *,
        CASE
            WHEN th_dabao IS NOT NULL AND interactions >= th_dabao THEN '大爆'
            WHEN interactions >= th_bao                            THEN '爆'
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
    interactions,
    th_bao,
    th_dabao,
    synthetic,
    publish_url,
    publish_time,
    CASE
        WHEN marked_tier IN ('爆', '大爆') AND numeric_implied_tier = '趴'         THEN 'over_marked'
        WHEN marked_tier = '大爆'          AND numeric_implied_tier = '爆'         THEN 'over_marked_soft'
        WHEN marked_tier = '趴'            AND numeric_implied_tier IN ('爆', '大爆') THEN 'under_marked'
    END AS discrepancy_type
FROM scored
WHERE (marked_tier IN ('爆', '大爆') AND numeric_implied_tier = '趴')
   OR (marked_tier = '大爆'          AND numeric_implied_tier = '爆')
   OR (marked_tier = '趴'            AND numeric_implied_tier IN ('爆', '大爆'));

COMMENT ON VIEW truth_vault.v_tier_discrepancy IS
    '标注质量复核: 人工标的 tier 与互动量门槛推断 tier 矛盾的笔记 (over_marked / over_marked_soft / under_marked). 只暴露不自动改; 复核后在飞书改状态或走人工补录 (tier_source=人工补录)。';
