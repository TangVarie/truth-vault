-- ════════════════════════════════════════════════════════════════════
-- Truth Vault · 跨 Schema Views (v1.2)
-- ════════════════════════════════════════════════════════════════════
--
-- ⚠️ 部署顺序: 本文件必须在以下条件满足后才能执行:
--   1. truth_vault schema 已创建（notes_v1_2.sql 已执行）
--   2. public schema 含 sanshengliubu 表（outputs / pipeline_runs）
--   3. autowriter schema 已创建且含 versions / items 表
--
-- 如果 autowriter 尚未迁移到独立 schema，先跳过本文件。
-- 迁移完成后再执行。views 是 CREATE OR REPLACE，可安全重跑。
-- ════════════════════════════════════════════════════════════════════

SET search_path TO truth_vault, public;


-- ── Prompt 表现追溯 (D-016 简化版) ──
-- 把 sanshengliubu.outputs 和 truth_vault.notes 关联，反推 prompt 表现
CREATE OR REPLACE VIEW truth_vault.v_prompt_performance AS
SELECT 
    o.id AS prompt_id,
    o.run_id,
    o.version,
    pr.project_id AS ssll_project_id,
    pr.completed_at,
    COUNT(DISTINCT n.note_id) AS related_notes_count,
    SUM(CASE WHEN n.tier = '爆' THEN 1 ELSE 0 END) AS bao_count,
    SUM(CASE WHEN n.tier = '大爆' THEN 1 ELSE 0 END) AS dabao_count,
    CASE WHEN COUNT(DISTINCT n.note_id) > 0
        THEN (SUM(CASE WHEN n.tier IN ('爆', '大爆') THEN 1 ELSE 0 END))::FLOAT 
             / COUNT(DISTINCT n.note_id)
        ELSE NULL END AS bao_rate
FROM public.outputs o
LEFT JOIN public.pipeline_runs pr ON o.run_id = pr.id
LEFT JOIN truth_vault.notes n ON n.source_sanshengliubu_output_id = o.id
GROUP BY o.id, o.run_id, o.version, pr.project_id, pr.completed_at;


-- ── 模型胜率 (Claude vs Gemini vs DeepSeek) ──
-- 通过 autowriter.versions.ai_engine + Truth Vault notes.tier 反推
CREATE OR REPLACE VIEW truth_vault.v_model_comparison AS
SELECT 
    v.ai_engine,
    n.project_id,
    COUNT(*) AS total_versions_used,
    SUM(CASE WHEN n.tier = '爆' THEN 1 ELSE 0 END) AS bao_count,
    SUM(CASE WHEN n.tier = '大爆' THEN 1 ELSE 0 END) AS dabao_count,
    AVG(n.interactions) AS avg_interactions,
    CASE WHEN COUNT(*) > 0
        THEN (SUM(CASE WHEN n.tier IN ('爆', '大爆') THEN 1 ELSE 0 END))::FLOAT / COUNT(*)
        ELSE NULL END AS bao_rate
FROM autowriter.versions v
JOIN autowriter.items i ON v.item_id = i.id
JOIN truth_vault.notes n ON n.source_autowriter_version_id = v.id
WHERE v.ai_engine != 'truth_vault_sync'  -- 排除 Truth Vault 回写的 fake version
GROUP BY v.ai_engine, n.project_id;
