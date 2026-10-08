-- truth_vault v1.19 · v_flywheel_sync_status: pending 只数真会推的, 加「被闸挡的」与「推出去后不合格的」两列
-- ════════════════════════════════════════════════════════════════════
-- 背景 (D-086 / D-087):
--   · OKMAN 08-18 飞书状态列整批误标为 爆 → 当晚通道 1 推进 ssll 284 条处方药参照 → 08-19 改回。
--     这张视图只数「现在是 爆/大爆 且已同步」, OKMAN 一直显示 37/0, 7 周没人看见。
--   · pending_ssll_sync 把被 D-068 闸挡掉的「铺评工单」也算成"待推" (10-08 实查: 69 = 全是铺评工单),
--     看板上像通道 1 卡住了, 其实是正确地没推。
-- 改三处 (CREATE OR REPLACE VIEW; 既有列集与顺序【不变】, 新列追加在末尾, 老消费者不受影响):
--   1) pending_ssll_sync 加排「铺评工单」—— 与 fetch_pending_baokuan / metric_tier_untrustworthy_reason 对齐 (D-068);
--   2) 新列 gated_ssll_sync: 爆/大爆、未同步、其余资格都够、只因 synthetic / 铺评工单 被挡 —— "没推是对的";
--   3) 新列 stale_in_ssll: synced_to_ssll_at 非空、但【现在】不满足 push 判据 (tier 不在 爆/大爆/参考, 或
--      tier_source 退回 数值推断/NULL, 或 爆/大爆 指标不可信) —— 回收 (retract_stale_synthetic_from_ssll,
--      D-087) 每晚会清, 非零 = 回收没跑或跑挂了。不按 publish_time 判: 推进去之后变老不是推错 (同回收口径)。
-- 判据与 scripts/sync_truth_vault_baokuan_to_sanshengliubu.ssll_eligibility_reason() 同一份; CI 守卫钉着
-- 两边的字面量 (铺评工单) 一致。
-- 在 notes_v1_18 之后应用 (链尾; 只改视图, 依赖 v1_6 的列集与 v1_10 的 v_autowriter_injection_candidates)。
-- ════════════════════════════════════════════════════════════════════

CREATE OR REPLACE VIEW truth_vault.v_flywheel_sync_status AS
SELECT
    p.project_id,
    p.brand,
    sum(CASE WHEN n.tier = ANY (ARRAY['爆', '大爆']) THEN 1 ELSE 0 END) AS total_baokuan,
    sum(CASE WHEN n.tier = ANY (ARRAY['爆', '大爆']) AND n.synced_to_ssll_at IS NOT NULL THEN 1 ELSE 0 END) AS synced_to_ssll,
    sum(CASE WHEN n.tier = ANY (ARRAY['爆', '大爆']) AND n.synced_to_aw_at IS NOT NULL THEN 1 ELSE 0 END) AS synced_to_aw,
    -- pending_ssll(爆/大爆):严格对齐 fetch_pending_baokuan ——
    --   tier_source <> '数值推断'(.neq,连 NULL 一起排)· publish_time 12 个月内(连 NULL 一起排)
    --   · 排 synthetic · 排「铺评工单」(v1.19, D-068 之后 push 本来就不推它们)
    sum(CASE WHEN n.tier = ANY (ARRAY['爆', '大爆']) AND n.synced_to_ssll_at IS NULL
                  AND n.tier_source <> '数值推断'
                  AND n.publish_time >= (now() - '1 year'::interval)::timestamp without time zone
                  AND (n.data_quality_flags ->> 'synthetic') IS DISTINCT FROM 'true'
                  AND NOT (COALESCE(n.data_quality_flags -> 'comment_maintained_routes', '[]'::jsonb) ? '铺评工单')
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
             THEN 1 ELSE 0 END) AS pending_reference_aw,
    -- v1.19 ↓ 新列追加在末尾
    -- gated_ssll_sync(爆/大爆):资格都够、只因指标不可信被 D-068 的闸挡住 —— "没推是对的", 不是积压
    sum(CASE WHEN n.tier = ANY (ARRAY['爆', '大爆']) AND n.synced_to_ssll_at IS NULL
                  AND n.tier_source <> '数值推断'
                  AND n.publish_time >= (now() - '1 year'::interval)::timestamp without time zone
                  AND ((n.data_quality_flags ->> 'synthetic') = 'true'
                       OR COALESCE(n.data_quality_flags -> 'comment_maintained_routes', '[]'::jsonb) ? '铺评工单')
             THEN 1 ELSE 0 END) AS gated_ssll_sync,
    -- stale_in_ssll(任意 tier):标着已推进 ssll, 但现在不满足 push 判据 —— 回收每晚清, 非零要人看
    sum(CASE WHEN n.synced_to_ssll_at IS NOT NULL
                  AND (n.tier IS NULL
                       OR n.tier <> ALL (ARRAY['爆', '大爆', '参考'])
                       OR n.tier_source IS NULL
                       OR n.tier_source = '数值推断'
                       OR (n.tier = ANY (ARRAY['爆', '大爆'])
                           AND ((n.data_quality_flags ->> 'synthetic') = 'true'
                                OR COALESCE(n.data_quality_flags -> 'comment_maintained_routes', '[]'::jsonb) ? '铺评工单')))
             THEN 1 ELSE 0 END) AS stale_in_ssll
FROM truth_vault.projects p
LEFT JOIN truth_vault.notes n ON p.project_id = n.project_id
LEFT JOIN truth_vault.v_autowriter_injection_candidates inj ON inj.note_id = n.note_id
GROUP BY p.project_id, p.brand;
