-- ════════════════════════════════════════════════════════════════════
-- truth_vault v1.10 · 审计 COR-024 升级迁移 (era 清空 + 未来日期衰减夹取)
-- ════════════════════════════════════════════════════════════════════
--
-- 升级迁移 (不是 fresh install 基线)。修复审计 COR-024。
--
-- 为什么单独一条迁移:
--   这两个修复分别改在 notes_v1_2.sql 的 fill_era_tag() 触发器和
--   notes_v1_4_flywheel_lesson_cards.sql 的 v_flywheel_lesson_cards 视图里。
--   但已部署环境早就跑过 v1_2 / v1_4, 首次部署清单不重跑历史迁移, 于是:
--     - publish_time 被清空时 era_tag 仍残留旧时代标签;
--     - 未来 publish_time 的 essence 衰减 recency_weight 仍可能 > 1、rank 越界。
--   所以必须有一条可对已部署库单独执行的增量迁移。
--
-- 部署:
--   在已经跑过 notes_v1_2 + notes_v1_4 的库上执行:
--     psql -d <shared_supabase> -f notes_v1_10_era_clear_and_decay_clamp.sql
--   或在 Supabase Dashboard → SQL Editor 粘贴执行。
--
-- 幂等: 函数与视图都用 CREATE OR REPLACE, 可安全重跑。
-- ════════════════════════════════════════════════════════════════════

-- ── 1. COR-024: publish_time 清空时同步清空 era_tag ──
--   原触发器只处理 NOT NULL 分支, publish_time 一旦变 NULL, era_tag 残留旧标签。
CREATE OR REPLACE FUNCTION truth_vault.fill_era_tag() RETURNS TRIGGER
    LANGUAGE plpgsql
    SET search_path = ''
AS $$
BEGIN
    IF NEW.publish_time IS NOT NULL THEN
        NEW.era_tag := EXTRACT(YEAR FROM NEW.publish_time)::TEXT
                       || ' Q'
                       || EXTRACT(QUARTER FROM NEW.publish_time)::TEXT;
    ELSE
        NEW.era_tag := NULL;
    END IF;
    RETURN NEW;
END;
$$;

-- ── 2. COR-024: 未来 publish_time 的衰减夹到 [0,1] ──
--   未来日期使 age_months 为负 → power(0.5, 负数) > 1 → rank_score 越界。
--   LEAST(..., 1.0) 让未来日期不再反超当下爆款; 过去日期 power < 1, 原值不变。
CREATE OR REPLACE VIEW truth_vault.v_flywheel_lesson_cards AS
WITH eligible AS (
    SELECT
        n.note_id, n.project_id, n.raw_content, n.account_id,
        n.tier, n.tier_source, n.publish_time, n.platform,
        n.emotional_lever, n.target_audience, n.user_pain_point, n.content_format,
        n.hit_blue_keywords, n.data_quality_flags,
        p.brand, p.category,
        LEAST(1.0::double precision,
              power(0.5::double precision,
                    (EXTRACT(epoch FROM now()::timestamp without time zone - n.publish_time)
                     / (86400.0 * 30.0 * 60.0))::double precision)) AS recency_weight
    FROM truth_vault.notes n
    JOIN truth_vault.projects p ON p.project_id = n.project_id
    WHERE n.tier = ANY (ARRAY['爆', '大爆', '参考'])
      AND n.tier_source IS DISTINCT FROM '数值推断'
      AND n.publish_time IS NOT NULL
      AND NOT (COALESCE(n.data_quality_flags ->> 'synthetic', 'false') = 'true'
               AND n.tier = ANY (ARRAY['爆', '大爆']))
)
SELECT
    e.note_id AS source_note_id,
    e.project_id, e.brand, e.category, e.platform,
    e.tier, e.tier_source, e.publish_time,
    e.emotional_lever, e.target_audience, e.user_pain_point, e.content_format,
    e.hit_blue_keywords,
    la.hook_type, la.structure, la.why_it_worked, la.transferable_tactic,
    la.curated_at,
    (la.note_id IS NOT NULL) AS is_curated,
    left(e.raw_content, 600) AS raw_excerpt,
    e.recency_weight,
    COALESCE(a.personal_bao_rate, 0.3::double precision) AS account_bao_rate,
    e.recency_weight
        + CASE e.tier
            WHEN '大爆' THEN 0.5
            WHEN '爆'   THEN 0.3
            WHEN '参考' THEN 0.15
            ELSE 0
          END::double precision
        + CASE e.tier_source
            WHEN '状态字段' THEN 0.2
            WHEN '备注字段' THEN 0.2
            WHEN '人工补录' THEN 0.2
            ELSE 0
          END::double precision
        + COALESCE(a.personal_bao_rate, 0.3::double precision) * 0.3::double precision AS rank_score,
    (COALESCE(e.data_quality_flags ->> 'synthetic', 'false') = 'true') AS synthetic
FROM eligible e
LEFT JOIN truth_vault.flywheel_lesson_annotations la ON la.note_id = e.note_id
LEFT JOIN truth_vault.v_top_performing_accounts a   ON a.account_id = e.account_id;
