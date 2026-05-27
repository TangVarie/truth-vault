-- truth_vault v1.3 · 新增 tier「参考」
-- ════════════════════════════════════════════════════════════════════
-- 业务规则 (2026-05-27, Ziao):
--   产品贴一般够不到爆贴标准。但若运营觉得某篇值得后续参考, 在飞书「流量状态」
--   列填「参考」。这类笔记**也进飞轮被调用**(ssll 参照库 + autowriter 注入),
--   但**不计入爆款统计**(total_baokuan 仍只算 爆/大爆), 以免污染爆贴标准。
--
-- 通道与权重 (Ziao 选定): 参考 进 ssll + autowriter 两条通道; 在 autowriter
--   注入打分里权重低于爆款 (大爆 +0.5 / 爆 +0.3 / 参考 +0.15)。
--
-- 本迁移在 notes_v1_2.sql 之后应用, supersede 其中的两个视图定义。
-- ════════════════════════════════════════════════════════════════════

-- 1. tier CHECK 加入 '参考'
ALTER TABLE truth_vault.notes DROP CONSTRAINT IF EXISTS notes_tier_check;
ALTER TABLE truth_vault.notes ADD CONSTRAINT notes_tier_check
    CHECK (tier IN ('趴', '预备', '爆', '大爆', '参考', '风控', '删除', '未知', '数据异常'));

-- 2. autowriter 注入候选: 纳入 参考 (权重 +0.15, 低于爆款)
CREATE OR REPLACE VIEW truth_vault.v_autowriter_injection_candidates AS
WITH eligible AS (
    SELECT
        n.note_id, n.project_id, n.raw_content, n.hit_blue_keywords,
        n.tier, n.tier_source, n.emotional_lever, n.target_audience,
        n.publish_time, n.account_id, n.synced_to_aw_at,
        p.brand, p.category, p.mapping_to_autowriter_project_id,
        GREATEST(0::double precision,
            (1.0 - EXTRACT(epoch FROM now()::timestamp without time zone - n.publish_time)
                   / (86400.0 * 365.0))::double precision) AS recency_weight
    FROM truth_vault.notes n
    JOIN truth_vault.projects p ON p.project_id = n.project_id
    WHERE n.tier = ANY (ARRAY['爆', '大爆', '参考'])
      AND n.tier_source IS DISTINCT FROM '数值推断'
      AND n.publish_time IS NOT NULL
      AND n.publish_time > (now() - '1 year'::interval)::timestamp without time zone
      AND p.mapping_to_autowriter_project_id IS NOT NULL
      AND (n.data_quality_flags ->> 'synthetic') IS DISTINCT FROM 'true'
)
SELECT
    e.note_id, e.project_id, e.raw_content, e.hit_blue_keywords, e.tier, e.tier_source,
    e.emotional_lever, e.target_audience, e.publish_time, e.synced_to_aw_at, e.account_id,
    e.brand, e.category, e.mapping_to_autowriter_project_id, e.recency_weight,
    COALESCE(a.personal_bao_rate, 0.3::double precision) AS account_bao_rate,
    e.recency_weight
        + CASE e.tier
            WHEN '大爆' THEN 0.5
            WHEN '爆'  THEN 0.3
            WHEN '参考' THEN 0.15
            ELSE 0
          END::double precision
        + CASE e.tier_source
            WHEN '状态字段' THEN 0.2
            WHEN '备注字段' THEN 0.2
            WHEN '人工补录' THEN 0.2
            ELSE 0
          END::double precision
        + COALESCE(a.personal_bao_rate, 0.3::double precision) * 0.3::double precision AS injection_score
FROM eligible e
LEFT JOIN truth_vault.v_top_performing_accounts a ON a.account_id = e.account_id;

-- 3. 飞轮状态: 爆款统计不变 (total_baokuan = 爆/大爆); 新增 参考级 的独立计数
CREATE OR REPLACE VIEW truth_vault.v_flywheel_sync_status AS
SELECT
    p.project_id,
    p.brand,
    sum(CASE WHEN n.tier = ANY (ARRAY['爆', '大爆']) THEN 1 ELSE 0 END) AS total_baokuan,
    sum(CASE WHEN n.tier = ANY (ARRAY['爆', '大爆']) AND n.synced_to_ssll_at IS NOT NULL THEN 1 ELSE 0 END) AS synced_to_ssll,
    sum(CASE WHEN n.tier = ANY (ARRAY['爆', '大爆']) AND n.synced_to_aw_at IS NOT NULL THEN 1 ELSE 0 END) AS synced_to_aw,
    sum(CASE WHEN n.tier = ANY (ARRAY['爆', '大爆']) AND n.synced_to_ssll_at IS NULL THEN 1 ELSE 0 END) AS pending_ssll_sync,
    sum(CASE WHEN n.tier = ANY (ARRAY['爆', '大爆']) AND n.synced_to_aw_at IS NULL THEN 1 ELSE 0 END) AS pending_aw_sync,
    max(n.synced_to_ssll_at) FILTER (WHERE n.tier = ANY (ARRAY['爆', '大爆'])) AS last_baokuan_sync_to_ssll_at,
    max(n.synced_to_aw_at)   FILTER (WHERE n.tier = ANY (ARRAY['爆', '大爆'])) AS last_baokuan_sync_to_aw_at,
    -- 参考级 (与爆款分开, 不进 total_baokuan; CREATE OR REPLACE 要求新列追加在末尾)
    sum(CASE WHEN n.tier = '参考' THEN 1 ELSE 0 END) AS total_reference,
    sum(CASE WHEN n.tier = '参考' AND n.synced_to_ssll_at IS NOT NULL THEN 1 ELSE 0 END) AS synced_reference_to_ssll,
    sum(CASE WHEN n.tier = '参考' AND n.synced_to_ssll_at IS NULL THEN 1 ELSE 0 END) AS pending_reference_ssll,
    sum(CASE WHEN n.tier = '参考' AND n.synced_to_aw_at IS NOT NULL THEN 1 ELSE 0 END) AS synced_reference_to_aw,
    sum(CASE WHEN n.tier = '参考' AND n.synced_to_aw_at IS NULL THEN 1 ELSE 0 END) AS pending_reference_aw
FROM truth_vault.projects p
LEFT JOIN truth_vault.notes n ON p.project_id = n.project_id
GROUP BY p.project_id, p.brand;
