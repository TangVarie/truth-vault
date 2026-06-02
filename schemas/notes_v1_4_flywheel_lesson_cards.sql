-- truth_vault v1.4 · 飞轮策展库 (pull / 图书馆 + LLM 馆员 的"书架")
-- ════════════════════════════════════════════════════════════════════
-- 背景 (D-038 / docs/14): 通道2 从 push 改为 pull —— TV 当策展图书馆, aw/ssll
--   写稿时向 LLM 馆员借阅匹配的爆款经验。本迁移建"书架"的两件:
--     1. flywheel_lesson_annotations · 管家(LLM)入库时提炼的"经验卡"字段
--        (hook_type / structure / why_it_worked / transferable_tactic),
--        由 curate_flywheel_lessons.py (策展 pass) 写入; prompt 见 prompts/flywheel_curator.md。
--     2. v_flywheel_lesson_cards · 馆员读的视图: 把合格爆款(notes) + essence
--        + 经验卡 + rank_score 组装成一张张"卡"。
--
-- 与 push (v_autowriter_injection_candidates) 的关键差异:
--   * 故意【不】要求 mapping_to_autowriter_project_id —— pull 不做 per-project
--     预路由, 这正是 D-038 改 pull 要消灭的那一坨复杂度。
--   * rank_score 复用注入打分【同一公式】(recency + tier + tier_source +
--     account_bao_rate), 让馆员"借到的是好书且新"(吸收 D-036)。
--   * tier 纳入 爆/大爆/参考 (与 v1.3 一致; 参考权重 +0.15)。
--
-- 经验卡为何独立建表 (不加列到 notes): 仿 note_features (按 note_id 一行的
--   特征表) 的范式 —— 策展字段稀疏(只对爆/大爆/参考算) + 生命周期独立(LLM
--   策展 pass 维护), 不污染已经很宽的 notes 主表。
--
-- 本迁移在 notes_v1_2.sql + notes_v1_3_reference_tier.sql 之后应用。
-- ════════════════════════════════════════════════════════════════════

-- 1. 经验卡注解表 (管家 LLM 策展产出; 按 note_id 一行, 仿 note_features 模式)
CREATE TABLE IF NOT EXISTS truth_vault.flywheel_lesson_annotations (
    note_id TEXT PRIMARY KEY REFERENCES truth_vault.notes(note_id) ON DELETE CASCADE,

    hook_type           TEXT,   -- 钩子类型 (痛点共鸣/反差/福利/悬念/身份认同…)
    structure           TEXT,   -- 结构骨架 (开场→铺陈→转折→CTA→评论区设计)
    why_it_worked       TEXT,   -- 为什么爆 (1-2 句可迁移的经验)
    transferable_tactic TEXT,   -- 可直接借走的具体手法

    curated_by      TEXT,        -- 策展模型 id (如 claude-sonnet-4-6)
    curator_version TEXT,        -- 策展 prompt/spec 版本 (flywheel_curator vX)
    curated_at      TIMESTAMP DEFAULT NOW(),
    -- updated_at: 馆员缓存失效用 (library_version = max(updated_at), docs/14 §4.2)。
    -- DEFAULT 只在 INSERT 生效、UPDATE 时不变, 所以【重策展】(upsert 的 DO UPDATE)
    -- 必须靠下方 BEFORE UPDATE 触发器刷新, 不能指望写入方记得 (PR#28 review r3333039971)。
    updated_at      TIMESTAMP DEFAULT NOW()
);

-- 退役/新鲜度 + 缓存版本: 馆员按 updated_at 判断卡是否过期, 并算 library_version。
CREATE INDEX IF NOT EXISTS idx_tv_lesson_updated_at
    ON truth_vault.flywheel_lesson_annotations(updated_at);

-- updated_at 自动刷新 (复用 notes_v1_2.sql 已定义的 truth_vault.set_updated_at()):
-- 重策展走 upsert 的 DO UPDATE → BEFORE UPDATE 触发器把 updated_at 置 NOW(),
-- 馆员缓存据此可靠失效。幂等: DROP IF EXISTS 后重建。
DROP TRIGGER IF EXISTS tv_lesson_updated_at ON truth_vault.flywheel_lesson_annotations;
CREATE TRIGGER tv_lesson_updated_at
BEFORE UPDATE ON truth_vault.flywheel_lesson_annotations
FOR EACH ROW EXECUTE FUNCTION truth_vault.set_updated_at();

-- 2. 策展库视图: 馆员按 brief 借阅的"经验卡"
--    eligibility 同注入候选, 但【去掉 aw 映射要求】(pull 不预路由)。
--    LEFT JOIN 注解表 —— 未策展的爆款也出现(经验卡字段为 NULL), 馆员仍能用
--    raw_excerpt + essence 兜底, 不必等策展 pass 跑完才有料。
CREATE OR REPLACE VIEW truth_vault.v_flywheel_lesson_cards AS
WITH eligible AS (
    SELECT
        n.note_id, n.project_id, n.raw_content, n.account_id,
        n.tier, n.tier_source, n.publish_time, n.platform,
        n.emotional_lever, n.target_audience, n.user_pain_point, n.content_format,
        n.hit_blue_keywords,
        p.brand, p.category,
        GREATEST(0::double precision,
            (1.0 - EXTRACT(epoch FROM now()::timestamp without time zone - n.publish_time)
                   / (86400.0 * 365.0))::double precision) AS recency_weight
    FROM truth_vault.notes n
    JOIN truth_vault.projects p ON p.project_id = n.project_id
    WHERE n.tier = ANY (ARRAY['爆', '大爆', '参考'])
      AND n.tier_source IS DISTINCT FROM '数值推断'
      AND n.publish_time IS NOT NULL
      AND n.publish_time > (now() - '1 year'::interval)::timestamp without time zone
      -- synthetic(伪爆贴, 指标造假)【无差别排除】所有 tier(含参考) —— 馆员是
      -- "教 LLM 这条为什么有效"的高权重学习面, 不能拿造假指标的内容当真经验喂模型
      -- (PR#28 review r3333039948)。与 push 的 v_autowriter_injection_candidates 一致
      -- (都排除 synthetic)。注: 通道1 ssll 对 参考 放行 synthetic 是因为那只是"证据包"、
      -- 不是"已验证经验"; 本视图等同通道2 的学习面, 从严。
      AND (n.data_quality_flags ->> 'synthetic') IS DISTINCT FROM 'true'
      -- ⚠️ 故意【不】加 p.mapping_to_autowriter_project_id IS NOT NULL ——
      --    pull 不做 per-project 预路由 (D-038 改 pull 要消灭的复杂度)。
)
SELECT
    -- 导出为 source_note_id (对齐 docs/14 §4.1 + lineage 契约 docs/10; 馆员/反向
    -- 归因按此列取) —— PR#28 review r3333039964。
    e.note_id AS source_note_id,
    e.project_id, e.brand, e.category, e.platform,
    e.tier, e.tier_source, e.publish_time,
    -- essence (来自 notes, annotate_essence_pass 已标)
    e.emotional_lever, e.target_audience, e.user_pain_point, e.content_format,
    e.hit_blue_keywords,
    -- 经验卡 (来自策展 pass; 未策展时 NULL, 馆员用 raw_excerpt + essence 兜底)
    la.hook_type, la.structure, la.why_it_worked, la.transferable_tactic,
    la.curated_at,
    (la.note_id IS NOT NULL) AS is_curated,
    -- 原文片段供仿写 (截断防 prompt 爆)
    left(e.raw_content, 600) AS raw_excerpt,
    -- rank_score: 复用注入打分公式 (recency + tier + tier_source + account_bao_rate)
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
        + COALESCE(a.personal_bao_rate, 0.3::double precision) * 0.3::double precision AS rank_score
FROM eligible e
LEFT JOIN truth_vault.flywheel_lesson_annotations la ON la.note_id = e.note_id
LEFT JOIN truth_vault.v_top_performing_accounts a   ON a.account_id = e.account_id;

-- 3. RLS: 与其它 truth_vault 表一致。本表是后台策展数据, 只由 sync/策展 pass/
--    馆员服务用 service_role 读写 (service_role 绕过 RLS); 不开放给 anon/登录用户。
ALTER TABLE truth_vault.flywheel_lesson_annotations ENABLE ROW LEVEL SECURITY;
