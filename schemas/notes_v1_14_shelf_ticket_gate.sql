-- ════════════════════════════════════════════════════════════════════
-- truth_vault v1.14 · 书架准入挡「铺评工单」爆贴 (D-060 route → 书架; docs/28 §7.2)
-- ════════════════════════════════════════════════════════════════════
--
-- 升级迁移 (不是 fresh install 基线)。只重建一个视图: v_flywheel_lesson_cards。
--
-- 为什么:
--   书架准入 (v1_4 建, v1_10 重建) 挡了 tier_source = '数值推断' 和 synthetic 的 爆/大爆,
--   但【没挡】D-060 引擎写进 data_quality_flags.comment_maintained_routes 的「铺评工单」
--   这一路。signal-definitions §八 的口径是: 铺评工单 = 评论数可能是铺出来的, 剔出 L2
--   正例; 只剔这一条 route, 【不剔】「起量后干预」(那是真赢家起量后运营回去改评, 果不是因)。
--   书架借的是「爆了的内容经验」, 铺评过线的贴根本没爆 —— 生产实查 (2026-09-19):
--   书架 353 张卡里 41 张是铺评工单爆贴 (TUGE 40 / RIO 1), 其中 31 张已策展成经验卡,
--   TUGE 那 40 条互动中位数 6、评论中位数 51 (刚好跨过 50 的爆线)。它们正在教写作台。
--
-- 怎么改: eligible 里加一条, 读引擎写好的 comment_maintained_routes ——
--   它同时认顶层列和 raw_extra._undeclared (D-060 / D-055), 视图里【不】再写一遍列名判据,
--   判据只能有一份, 住在引擎里 (D-062 续 的教训)。
--   COALESCE 到 '[]' 保证键不存在的行 (D-060 之前入库、没被引擎重判过的) 照常进。
--   只挡【指标型 tier】(爆/大爆), 同 synthetic 的处理: 「参考」是人工内容判断, 放行。
--
-- 部署: 在已经跑过 notes_v1_4 (+ v1_10) 的库上执行
--     psql -d <shared_supabase> -f notes_v1_14_shelf_ticket_gate.sql
--   必须在 v1_10 之后 —— 两者都整体重建这个视图, 后跑的赢。本文件含 v1_10 的全部内容
--   (era 清空的函数不在此重复, 那个不受影响)。
--
-- 幂等: CREATE OR REPLACE, 列集与 v1_10 完全一致 (不加列、不改类型), 可安全重跑。
-- ════════════════════════════════════════════════════════════════════

CREATE OR REPLACE VIEW truth_vault.v_flywheel_lesson_cards AS
WITH eligible AS (
    SELECT
        n.note_id, n.project_id, n.raw_content, n.account_id,
        n.tier, n.tier_source, n.publish_time, n.platform,
        n.emotional_lever, n.target_audience, n.user_pain_point, n.content_format,
        n.hit_blue_keywords, n.data_quality_flags,
        p.brand, p.category,
        -- essence 半衰期 5 年 + COR-024 未来日期夹到 [0,1] (同 v1_10, 原样保留)
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
      -- v1.14: 铺评工单 (D-060 route) 的 爆/大爆 不上书架。读引擎写的 routes, 不重写判据。
      AND NOT (COALESCE(n.data_quality_flags -> 'comment_maintained_routes', '[]'::jsonb) ? '铺评工单'
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
