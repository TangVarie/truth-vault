-- truth_vault v1.6 · 修 v_flywheel_sync_status 的 pending_* 误报
-- ════════════════════════════════════════════════════════════════════
-- 问题 (2026-06-04):pending_ssll_sync / pending_aw_sync / pending_reference_* 只判
--   "tier 对 + 还没 synced",没套真正 sync 用的资格闸 → 把【数值推断】tier 的爆款也算进
--   "待同步",但它们永远不会被同步(channel-1 sync 要求 tier_source != '数值推断';
--   且 synthetic 的爆/大爆 也被排除)。运营看 v_flywheel_sync_status 会误以为"N 条卡住了"
--   (实测 WTG: pending_ssll_sync=3,实际那 3 条全是数值推断、永不同步)。
-- 修:pending_* 加上和 sync 一致的资格条件 —— tier_source != 数值推断;爆/大爆再排 synthetic
--   (参考允许 synthetic,见 docs/13 / v1.4 通道1 口径)。total_baokuan / synced_* /
--   total_reference 等【统计 / 已同步】列【不变】(业务口径:total_baokuan 仍 = 爆/大爆)。
-- 本迁移 supersede notes_v1_3 里的该视图定义;CREATE OR REPLACE,列集与顺序不变。
-- 在 notes_v1_2 → v1_3 之后应用。
-- ════════════════════════════════════════════════════════════════════

CREATE OR REPLACE VIEW truth_vault.v_flywheel_sync_status AS
SELECT
    p.project_id,
    p.brand,
    sum(CASE WHEN n.tier = ANY (ARRAY['爆', '大爆']) THEN 1 ELSE 0 END) AS total_baokuan,
    sum(CASE WHEN n.tier = ANY (ARRAY['爆', '大爆']) AND n.synced_to_ssll_at IS NOT NULL THEN 1 ELSE 0 END) AS synced_to_ssll,
    sum(CASE WHEN n.tier = ANY (ARRAY['爆', '大爆']) AND n.synced_to_aw_at IS NOT NULL THEN 1 ELSE 0 END) AS synced_to_aw,
    -- pending 只算【真会被同步】的:tier_source 非数值推断,且爆/大爆排 synthetic(对齐 channel-1 sync)
    sum(CASE WHEN n.tier = ANY (ARRAY['爆', '大爆']) AND n.synced_to_ssll_at IS NULL
                  AND n.tier_source IS DISTINCT FROM '数值推断'
                  AND (n.data_quality_flags ->> 'synthetic') IS DISTINCT FROM 'true'
             THEN 1 ELSE 0 END) AS pending_ssll_sync,
    sum(CASE WHEN n.tier = ANY (ARRAY['爆', '大爆']) AND n.synced_to_aw_at IS NULL
                  AND n.tier_source IS DISTINCT FROM '数值推断'
                  AND (n.data_quality_flags ->> 'synthetic') IS DISTINCT FROM 'true'
             THEN 1 ELSE 0 END) AS pending_aw_sync,
    max(n.synced_to_ssll_at) FILTER (WHERE n.tier = ANY (ARRAY['爆', '大爆'])) AS last_baokuan_sync_to_ssll_at,
    max(n.synced_to_aw_at)   FILTER (WHERE n.tier = ANY (ARRAY['爆', '大爆'])) AS last_baokuan_sync_to_aw_at,
    -- 参考级 (与爆款分开, 不进 total_baokuan)
    sum(CASE WHEN n.tier = '参考' THEN 1 ELSE 0 END) AS total_reference,
    sum(CASE WHEN n.tier = '参考' AND n.synced_to_ssll_at IS NOT NULL THEN 1 ELSE 0 END) AS synced_reference_to_ssll,
    -- 参考 pending 同样套资格闸(tier_source 非数值推断;参考允许 synthetic,故不排 synthetic)
    sum(CASE WHEN n.tier = '参考' AND n.synced_to_ssll_at IS NULL
                  AND n.tier_source IS DISTINCT FROM '数值推断'
             THEN 1 ELSE 0 END) AS pending_reference_ssll,
    sum(CASE WHEN n.tier = '参考' AND n.synced_to_aw_at IS NOT NULL THEN 1 ELSE 0 END) AS synced_reference_to_aw,
    sum(CASE WHEN n.tier = '参考' AND n.synced_to_aw_at IS NULL
                  AND n.tier_source IS DISTINCT FROM '数值推断'
             THEN 1 ELSE 0 END) AS pending_reference_aw
FROM truth_vault.projects p
LEFT JOIN truth_vault.notes n ON p.project_id = n.project_id
GROUP BY p.project_id, p.brand;
