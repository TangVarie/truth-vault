-- truth_vault v1.6 · 修 v_flywheel_sync_status 的 pending_* 误报(对齐各 sync 的真实过滤)
-- ════════════════════════════════════════════════════════════════════
-- 问题(2026-06-04 codex PR#47 review):pending_* 没和真正 sync 用的过滤【完全】对齐 →
--   把永远不会被同步的行也算"待同步",仍会产生"卡住"假象。四处对齐:
--   1) tier_source:ssll sync 用 .neq('数值推断') = SQL `<>`(NULL 也被排除),不能用
--      IS DISTINCT FROM(那会把 NULL tier_source 当合格、误报 pending)。
--   2) publish_time:ssll/aw 都要 publish_time 在 12 个月内(NULL 也排除)。
--   3) synthetic:爆/大爆 排 synthetic;参考允许 synthetic(通道1 口径,见 docs/13)。
--   4) aw 侧:还要 mapping_to_autowriter_project_id 非空、且排所有 synthetic(含参考)——
--      直接【复用权威视图 v_autowriter_injection_candidates 的成员资格】,零漂移
--      (它已封装 mapping/publish_time/tier_source/synthetic 全部 aw 资格闸)。
-- total_baokuan / synced_* / total_reference 等【统计 / 已同步】列【不变】(业务口径)。
-- CREATE OR REPLACE,列集与顺序不变;在 notes_v1_2 → v1_3 之后应用。
-- ════════════════════════════════════════════════════════════════════

CREATE OR REPLACE VIEW truth_vault.v_flywheel_sync_status AS
SELECT
    p.project_id,
    p.brand,
    sum(CASE WHEN n.tier = ANY (ARRAY['爆', '大爆']) THEN 1 ELSE 0 END) AS total_baokuan,
    sum(CASE WHEN n.tier = ANY (ARRAY['爆', '大爆']) AND n.synced_to_ssll_at IS NOT NULL THEN 1 ELSE 0 END) AS synced_to_ssll,
    sum(CASE WHEN n.tier = ANY (ARRAY['爆', '大爆']) AND n.synced_to_aw_at IS NOT NULL THEN 1 ELSE 0 END) AS synced_to_aw,
    -- pending_ssll(爆/大爆):严格对齐 sync_truth_vault_baokuan_to_sanshengliubu.fetch_pending_baokuan ——
    --   tier_source <> '数值推断'(.neq,连 NULL 一起排)· publish_time 12 个月内(连 NULL 一起排)· 排 synthetic
    sum(CASE WHEN n.tier = ANY (ARRAY['爆', '大爆']) AND n.synced_to_ssll_at IS NULL
                  AND n.tier_source <> '数值推断'
                  AND n.publish_time >= (now() - '1 year'::interval)::timestamp without time zone
                  AND (n.data_quality_flags ->> 'synthetic') IS DISTINCT FROM 'true'
             THEN 1 ELSE 0 END) AS pending_ssll_sync,
    -- pending_aw(爆/大爆):复用 v_autowriter_injection_candidates 成员资格(零漂移)
    sum(CASE WHEN inj.note_id IS NOT NULL AND inj.tier = ANY (ARRAY['爆', '大爆']) AND n.synced_to_aw_at IS NULL
             THEN 1 ELSE 0 END) AS pending_aw_sync,
    max(n.synced_to_ssll_at) FILTER (WHERE n.tier = ANY (ARRAY['爆', '大爆'])) AS last_baokuan_sync_to_ssll_at,
    max(n.synced_to_aw_at)   FILTER (WHERE n.tier = ANY (ARRAY['爆', '大爆'])) AS last_baokuan_sync_to_aw_at,
    -- 参考级 (与爆款分开, 不进 total_baokuan)
    sum(CASE WHEN n.tier = '参考' THEN 1 ELSE 0 END) AS total_reference,
    sum(CASE WHEN n.tier = '参考' AND n.synced_to_ssll_at IS NOT NULL THEN 1 ELSE 0 END) AS synced_reference_to_ssll,
    -- pending_reference_ssll(参考):同 ssll 闸,但参考允许 synthetic(故不排 synthetic)
    sum(CASE WHEN n.tier = '参考' AND n.synced_to_ssll_at IS NULL
                  AND n.tier_source <> '数值推断'
                  AND n.publish_time >= (now() - '1 year'::interval)::timestamp without time zone
             THEN 1 ELSE 0 END) AS pending_reference_ssll,
    sum(CASE WHEN n.tier = '参考' AND n.synced_to_aw_at IS NOT NULL THEN 1 ELSE 0 END) AS synced_reference_to_aw,
    -- pending_reference_aw(参考):复用 v_autowriter_injection_candidates(注:该视图排所有 synthetic,
    --   含 synthetic 参考 → aw 注入资格比 ssll 严,这是 aw 注入视图既有口径)
    sum(CASE WHEN inj.note_id IS NOT NULL AND inj.tier = '参考' AND n.synced_to_aw_at IS NULL
             THEN 1 ELSE 0 END) AS pending_reference_aw
FROM truth_vault.projects p
LEFT JOIN truth_vault.notes n ON p.project_id = n.project_id
LEFT JOIN truth_vault.v_autowriter_injection_candidates inj ON inj.note_id = n.note_id
GROUP BY p.project_id, p.brand;
