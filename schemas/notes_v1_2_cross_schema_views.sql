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


-- ── autowriter positive pool 饱和度监控 ──
-- 取每个 autowriter project 当前 list_example_items 实际会注入的 5 条
-- (按 created_at DESC, label='positive', external_source='truth_vault'),
-- 计算 emotional_lever 多样性. 如果同一种 lever 占满多个 slot, 注入会过度
-- 同质, 受众容易疲劳.
--
-- 不告警, 只暴露数据: scripts/check_positive_saturation.py 读这个 view
-- 出人眼可看的 markdown. 想全自动告警时, 改 daily-sync.yml 加一步即可.
--
-- 字段含义:
--   active_positive_count   — 当前 list_example_items 实际会注入的条数 (≤5)
--   lever_distribution      — 这 ≤5 条覆盖到的 emotional_lever 集合
--   distinct_lever_count    — 多少种不同 lever
--   top_lever_count         — 最常见的 lever 在这 ≤5 条里出现几次
--   dominant_lever_ratio    — top_lever_count / active_positive_count
--                              (> 0.6 = 严重饱和; > 0.8 = 单一 lever 主导)
CREATE OR REPLACE VIEW truth_vault.v_autowriter_positive_pool_saturation AS
WITH top_5 AS (
    SELECT
        b.project_id AS aw_project_id,
        i.external_source_id AS tv_note_id,
        n.emotional_lever,
        ROW_NUMBER() OVER (
            PARTITION BY b.project_id ORDER BY i.created_at DESC
        ) AS rn
    FROM autowriter.items i
    JOIN autowriter.batches b ON b.id = i.batch_id
    LEFT JOIN truth_vault.notes n ON n.note_id = i.external_source_id
    WHERE i.example_label = 'positive'
      AND i.external_source = 'truth_vault'
),
in_pool AS (
    SELECT * FROM top_5 WHERE rn <= 5
),
lever_counts AS (
    SELECT aw_project_id, emotional_lever, COUNT(*) AS cnt
    FROM in_pool
    WHERE emotional_lever IS NOT NULL
    GROUP BY aw_project_id, emotional_lever
),
per_project_top_lever AS (
    SELECT aw_project_id, MAX(cnt) AS top_lever_count
    FROM lever_counts
    GROUP BY aw_project_id
)
SELECT
    p.aw_project_id,
    COUNT(*)::INT AS active_positive_count,
    array_agg(DISTINCT p.emotional_lever)
        FILTER (WHERE p.emotional_lever IS NOT NULL) AS lever_distribution,
    COUNT(DISTINCT p.emotional_lever)
        FILTER (WHERE p.emotional_lever IS NOT NULL)::INT AS distinct_lever_count,
    COALESCE(MAX(t.top_lever_count), 0)::INT AS top_lever_count,
    CASE WHEN COUNT(*) > 0
         THEN ROUND((COALESCE(MAX(t.top_lever_count), 0)::numeric / COUNT(*)::numeric), 2)
         ELSE NULL
    END AS dominant_lever_ratio
FROM in_pool p
LEFT JOIN per_project_top_lever t ON t.aw_project_id = p.aw_project_id
GROUP BY p.aw_project_id;
