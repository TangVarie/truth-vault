-- truth_vault v1.7 · 注入候选 recency 升级为 surface 三级时间衰减 (D-009)
-- ════════════════════════════════════════════════════════════════════
-- 背景 (D-009 / docs/05 §7 + §「时间衰减权重的工程实现(v0.2 三级分层)」:349-386):
--   surface 层的时间衰减【不该一视同仁】—— 它按 trend_dependencies 分三档:
--     · 通用 (不依赖时代)        → 半衰期 60 月 (5 年): 纯人性话术结构, 穿越周期
--     · 时代语言范式 (且无短期标签) → 半衰期 30 月 (2.5 年): 结构性话术模式, 比具体词持久
--     · 当代流行词 / 任一短期标签  → 半衰期  9 月: "绝绝子"型, 快过期
--     · 其余 (含未标 essence/NULL) → 半衰期 12 月 (1 年, docs/05 默认档)
--   recency = 0.5 ^ (age_months / 半衰期)。意义 (docs/05:386): 3 年前的"绝绝子型" surface
--   权重≈0.1(没用了), 但 3 年前的"通用型"≈0.7(依然有效)——【识别哪些老样本话术结构
--   仍有效、提取范式而不是抄词】, 是"引领新话术"的算法基础。
--
-- 之前的实现 (notes_v1_3_reference_tier.sql): recency = 线性 1 - age/365, 【对所有 surface
--   一视同仁、完全不读 trend_dependencies】(handover docs/21 §5 P3 登记的设计-代码缺口)。
--   本迁移把它换成 docs/05 的三级指数衰减; 阈值/权重加成 (大爆+0.5 / 爆+0.3 / 参考+0.15 /
--   tier_source+0.2 / account_bao*0.3) 全部【不变】, 只改 recency_weight 这一项的算法。
--
-- ⚠️ 故意【保留不动】的两点 (与 essence 书架 v1.4 故意不同):
--   1. publish_time > now()-1 年【硬窗】保留 —— 注入/ssll 喂的是 vibe_rewriter 的仿写【审美】
--      = surface 消费方, 不持续推过气审美 (handover §2, 策略 lead Ziao 确认)。三级衰减在窗【内】
--      做精排 (窗内: 通用 11 月≈0.88 vs 流行词 11 月≈0.40, 2x 差距 → 有效重排候选)。
--      —— 注: 若日后要让"通用型 surface"也穿越 1 年窗 (享受 5 年半衰期的全部价值), 那是【放宽窗】
--      的策略决定, 需 Ziao 拍板, 不在本迁移内擅动。
--   2. 书架 v_flywheel_lesson_cards (essence, 半衰期固定 5 年、无硬切) 不在此处, 不受影响。
--
-- CREATE OR REPLACE: 输出列集/顺序/类型【与 v1_3 完全一致】(recency_weight / injection_score
--   仍 double precision), 故依赖它的 v_flywheel_sync_status (v1.6, LEFT JOIN inj.note_id/tier)
--   不受影响。在 notes_v1_2 → v1_3 (→ v1_4 → v1_6) 之后应用。
-- ════════════════════════════════════════════════════════════════════

CREATE OR REPLACE VIEW truth_vault.v_autowriter_injection_candidates AS
WITH eligible AS (
    SELECT
        n.note_id, n.project_id, n.raw_content, n.hit_blue_keywords,
        n.tier, n.tier_source, n.emotional_lever, n.target_audience,
        n.publish_time, n.account_id, n.synced_to_aw_at,
        p.brand, p.category, p.mapping_to_autowriter_project_id,
        -- surface 三级衰减 (D-009 / docs/05:353-383, 一字对齐工程伪代码):
        --   半衰期(月) 按 trend_dependencies 取档; age_months = epoch/(86400*30);
        --   recency = 0.5 ^ (age_months / 半衰期)。SHORT_TERM_DEPS(短期集, docs/05:380-383)=
        --   {特定平台事件,特定IP引用,时事热点,季节性事件,节日,当代流行词}; 行业事件/平台话术【不在】
        --   短期集(落 12 月默认档)。NULL/未标 essence 的 trend_dependencies → 全部 WHEN 为 NULL →
        --   ELSE 12 月(= docs/05 默认 surface_halflife)。double precision 保列类型不变。
        power(0.5::double precision,
              (EXTRACT(epoch FROM now()::timestamp without time zone - n.publish_time)
               / (86400.0 * 30.0 *
                  CASE
                    WHEN '通用' = ANY (n.trend_dependencies) THEN 60.0
                    WHEN '时代语言范式' = ANY (n.trend_dependencies)
                         AND NOT (n.trend_dependencies && ARRAY['特定平台事件','特定IP引用','时事热点','季节性事件','节日','当代流行词']::text[])
                         THEN 30.0
                    WHEN n.trend_dependencies && ARRAY['特定平台事件','特定IP引用','时事热点','季节性事件','节日','当代流行词']::text[]
                         THEN 9.0
                    ELSE 12.0
                  END
                 ))::double precision) AS recency_weight
    FROM truth_vault.notes n
    JOIN truth_vault.projects p ON p.project_id = n.project_id
    WHERE n.tier = ANY (ARRAY['爆', '大爆', '参考'])
      AND n.tier_source IS DISTINCT FROM '数值推断'
      AND n.publish_time IS NOT NULL
      -- ⚠️ 1 年硬窗【保留】(见文件头 §1): 注入/ssll 是 surface/审美消费方, 不推过气审美。
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
