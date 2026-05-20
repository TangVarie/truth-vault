-- ════════════════════════════════════════════════════════════════════
-- Truth Vault · Schema v1.2 (Session #7 简化版)
-- ════════════════════════════════════════════════════════════════════
-- 
-- v1.1 → v1.2 调整（基于 Session #7 代码审查后的 D-025）:
--   ❌ 删除 prompt_versions（数据在 public.outputs，FK 引用即可）
--   ❌ 删除 generation_runs（数据在 public.pipeline_runs / autowriter.batches）
--   ❌ 删除 content_candidates（数据在 autowriter.items / versions）
--   ✅ 保留 prepublish_evaluations（简化版，仅 evaluator 校准）
--   ✅ notes 表新增跨系统 FK 字段
--   ✅ 跨 schema view 拆到 notes_v1_2_cross_schema_views.sql（D-029 部署顺序修复）
-- 
-- 部署假设: 共享 Supabase 实例（D-024）
--   - public schema: sanshengliubu 表（不动）
--   - autowriter schema: autowriter 表（迁移自 public）
--   - truth_vault schema: 本文件创建的所有表
-- 
-- 直接在 Supabase SQL Editor 执行（先 CREATE SCHEMA truth_vault）。
-- ════════════════════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE SCHEMA IF NOT EXISTS truth_vault;

SET search_path TO truth_vault, public;


-- ════════════════════════════════════════════════════════════════════
-- 1. projects
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS truth_vault.projects (
    project_id TEXT PRIMARY KEY,
    brand TEXT NOT NULL,
    product TEXT NOT NULL,
    -- category 受控词表 v1 (见 docs/05-controlled-vocab.md §9). 强制 enum
    -- 以避免 sanshengliubu 通道 1 sync 因品类拼写不一退化到 platform-only
    -- 检索。新品类需先升级词表再加入 CHECK.
    category TEXT NOT NULL CHECK (category IN (
        '处方药', 'OTC药', '保健品', '医疗器械',
        '美妆', '个护', '酒类', '食品饮料', '母婴',
        '3C数码', '家居家电', '服饰鞋包', '教育', '其他'
    )),
    platform TEXT NOT NULL DEFAULT 'xiaohongshu',
    schema_family TEXT CHECK (schema_family IN ('A', 'B', 'C')),

    start_date DATE,
    end_date DATE,

    mapping_config JSONB,
    -- tier_thresholds 没有 DEFAULT — yaml 必须显式声明 (NUC_phase1 用
    -- 150/700, NRT_phase3 用 200/1500). 早期 SQL default 是 100/1000,
    -- 但 stale defaults 会让没在 yaml 写阈值的项目拿到错的兜底.
    tier_thresholds JSONB,
    
    -- D-024 跨系统映射（手动维护）
    mapping_to_autowriter_project_id UUID,  -- 对应 autowriter.projects.id
    mapping_to_sanshengliubu_project_id UUID,  -- 对应 public.projects.id (sanshengliubu)
    
    -- 衍生统计
    total_notes INT DEFAULT 0,
    notes_with_data INT DEFAULT 0,
    notes_with_tier INT DEFAULT 0,
    notes_with_essence INT DEFAULT 0,
    notes_with_actual_audience INT DEFAULT 0,
    last_sync_at TIMESTAMP,
    last_baokuan_sync_to_ssll_at TIMESTAMP,
    last_baokuan_sync_to_aw_at TIMESTAMP,
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tv_projects_brand ON truth_vault.projects(brand);
CREATE INDEX IF NOT EXISTS idx_tv_projects_category ON truth_vault.projects(category);


-- ════════════════════════════════════════════════════════════════════
-- 2. accounts (D-020)
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS truth_vault.accounts (
    account_id TEXT PRIMARY KEY,  -- 帆谷素人编号
    platform TEXT NOT NULL DEFAULT 'xiaohongshu',
    owner_type TEXT DEFAULT '素人' 
        CHECK (owner_type IN ('素人', 'KOC', 'KOL', 'brand')),
    
    total_notes_count INT DEFAULT 0,
    bao_count INT DEFAULT 0,
    dabao_count INT DEFAULT 0,
    fengkong_count INT DEFAULT 0,
    deleted_count INT DEFAULT 0,
    personal_bao_rate FLOAT,
    
    first_seen_at TIMESTAMP,
    last_publish_at TIMESTAMP,
    account_memo TEXT,  -- 原 notes_text，改名避免与 notes 表混淆
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tv_accounts_bao_rate ON truth_vault.accounts(personal_bao_rate DESC);


CREATE TABLE IF NOT EXISTS truth_vault.account_snapshots (
    snapshot_id TEXT PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,
    account_id TEXT NOT NULL REFERENCES truth_vault.accounts(account_id) ON DELETE CASCADE,
    snapshot_at TIMESTAMP NOT NULL,
    
    followers INT,
    avg_reads_30d INT,
    avg_interactions_30d INT,
    median_interactions_recent_10 INT,
    
    account_health_status TEXT,
    source TEXT
);

CREATE INDEX IF NOT EXISTS idx_tv_account_snapshots_account 
    ON truth_vault.account_snapshots(account_id, snapshot_at DESC);


-- ════════════════════════════════════════════════════════════════════
-- 3. notes (核心表 · v1.2)
-- ════════════════════════════════════════════════════════════════════
-- 
-- 注：原 v1.1 的 source_candidate_id 字段被简化为
-- source_autowriter_item_id + source_autowriter_version_id 跨 schema FK

CREATE TABLE IF NOT EXISTS truth_vault.notes (
    note_id TEXT PRIMARY KEY,  -- 生成规则: {project_id}_{feishu_record_id}
    project_id TEXT NOT NULL REFERENCES truth_vault.projects(project_id) ON DELETE CASCADE,
    
    -- D-020: 账号 FK
    account_id TEXT REFERENCES truth_vault.accounts(account_id),
    
    -- D-025: 跨系统 FK（替代 v1.1 的 source_candidate_id）
    -- 这些 FK 指向其他 schema 的表，Supabase 共享实例下可以 JOIN
    source_sanshengliubu_output_id UUID,  -- → public.outputs.id
    source_autowriter_item_id UUID,       -- → autowriter.items.id
    source_autowriter_version_id UUID,    -- → autowriter.versions.id
    -- 注: 不设置 REFERENCES 约束（跨 schema FK 约束有部署灵活性问题）
    -- 通过应用层 + view 保证一致性
    
    -- ── Layer 1 · SURFACE ──
    title TEXT,
    body TEXT,
    hashtags TEXT[],
    raw_content TEXT NOT NULL,
    
    intent TEXT CHECK (intent IN ('traffic', 'conversion', 'educational', 'mixed', 'other')),
    content_format TEXT,
    
    -- ── Layer 2 · ESSENCE (D-017: 主表用 prediction_feature 模式) ──
    emotional_lever TEXT,
    emotional_valence TEXT CHECK (emotional_valence IN ('positive', 'negative', 'neutral')),
    emotional_intensity TEXT CHECK (emotional_intensity IN ('low', 'medium', 'high')),
    human_truth_archetype TEXT[],
    trend_dependencies TEXT[],
    
    -- ── Layer 3 · AUDIENCE ──
    target_audience TEXT[],
    inferred_audience_profile JSONB,
    actual_audience_data JSONB,
    
    user_pain_point TEXT,
    product_focus TEXT,
    direction_subtype TEXT,  -- D-014 LLM 子分类
    
    -- ── 投放元数据 ──
    publish_time TIMESTAMP,
    publish_url TEXT,
    target_blue_keywords TEXT[],
    
    -- ── 数据回收（最新值，历史进 metric_snapshots）──
    impressions INT,
    reads INT,
    interactions INT,
    hit_blue_keywords TEXT[],
    
    read_rate FLOAT GENERATED ALWAYS AS (
        CASE WHEN impressions > 0 AND impressions IS NOT NULL 
             THEN reads::FLOAT / impressions ELSE NULL END
    ) STORED,
    interaction_rate FLOAT GENERATED ALWAYS AS (
        CASE WHEN reads > 0 AND reads IS NOT NULL 
             THEN interactions::FLOAT / reads ELSE NULL END
    ) STORED,
    
    -- ── 人工标签 ──
    tier TEXT CHECK (tier IN ('趴', '预备', '爆', '大爆', '风控', '删除', '未知', '数据异常')),
    tier_source TEXT 
        CHECK (tier_source IN ('状态字段', '备注字段', '数值推断', '人工补录', '未标注', '数据异常')),
    data_quality_status TEXT,
    data_quality_flags JSONB,  -- D-013
    
    -- ── 控评/合规 ──
    pinned_comment TEXT,
    has_compliance_issue BOOLEAN DEFAULT FALSE,
    compliance_notes TEXT,
    
    -- ── 标注元数据 ──
    essence_annotated_by TEXT,
    essence_annotated_at TIMESTAMP,
    essence_vocab_version TEXT,
    essence_annotation_mode TEXT 
        CHECK (essence_annotation_mode IN ('prediction_feature', 'posthoc_explanation')),
    
    audience_inferred_at TIMESTAMP,
    audience_actual_synced_at TIMESTAMP,
    
    -- ── D-024 双通道 sync 状态追踪 ──
    synced_to_ssll_at TIMESTAMP,            -- 同步到 sanshengliubu.reference_samples
    synced_to_aw_at TIMESTAMP,              -- 同步到 autowriter.items
    synced_ssll_reference_sample_id UUID,   -- sanshengliubu.reference_samples.id (synced)
    synced_autowriter_item_id UUID,         -- autowriter.items.id (synced; example_label='positive')
    
    -- ── 元数据 ──
    raw_extra JSONB,
    era_tag TEXT,
    
    -- ── Ingest 追溯（sync 脚本写入）──
    -- 飞书 record_id: 同一项目下唯一，可以反向定位飞书表里的具体行
    -- (note_id = f"{project_id}_{feishu_record_id}"，所以理论上能从 note_id 解析，
    --  但飞书 record_id 长度不固定且可能含 '_', 单独存一列更稳妥)
    feishu_record_id TEXT,
    -- 平台标识，未来支持非小红书时不用迁移 schema
    platform TEXT NOT NULL DEFAULT 'xiaohongshu',
    -- 第一次被 ingest 到 TV 的时间（区别于 created_at 在某些 UPSERT 后会更新）
    ingested_at TIMESTAMP DEFAULT NOW(),
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 兼容已部署 schema（无这 3 列）—— idempotent
ALTER TABLE truth_vault.notes ADD COLUMN IF NOT EXISTS feishu_record_id TEXT;
ALTER TABLE truth_vault.notes ADD COLUMN IF NOT EXISTS platform TEXT NOT NULL DEFAULT 'xiaohongshu';
ALTER TABLE truth_vault.notes ADD COLUMN IF NOT EXISTS ingested_at TIMESTAMP DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_tv_notes_project ON truth_vault.notes(project_id);
CREATE INDEX IF NOT EXISTS idx_tv_notes_account ON truth_vault.notes(account_id);
CREATE INDEX IF NOT EXISTS idx_tv_notes_ssll_output ON truth_vault.notes(source_sanshengliubu_output_id);
CREATE INDEX IF NOT EXISTS idx_tv_notes_aw_item ON truth_vault.notes(source_autowriter_item_id);
CREATE INDEX IF NOT EXISTS idx_tv_notes_publish_time ON truth_vault.notes(publish_time);
CREATE INDEX IF NOT EXISTS idx_tv_notes_tier ON truth_vault.notes(tier);
CREATE INDEX IF NOT EXISTS idx_tv_notes_intent ON truth_vault.notes(intent);
CREATE INDEX IF NOT EXISTS idx_tv_notes_content_format ON truth_vault.notes(content_format);
CREATE INDEX IF NOT EXISTS idx_tv_notes_essence_lever ON truth_vault.notes(emotional_lever);
CREATE INDEX IF NOT EXISTS idx_tv_notes_era ON truth_vault.notes(era_tag);
CREATE INDEX IF NOT EXISTS idx_tv_notes_url ON truth_vault.notes(publish_url);
CREATE INDEX IF NOT EXISTS idx_tv_notes_baokuan_unsynced 
    ON truth_vault.notes(tier, synced_to_ssll_at, synced_to_aw_at) 
    WHERE tier IN ('爆', '大爆');
-- sync 脚本反查/重试时按 (project, feishu_record_id) 定位
CREATE INDEX IF NOT EXISTS idx_tv_notes_feishu_record 
    ON truth_vault.notes(project_id, feishu_record_id);

CREATE INDEX IF NOT EXISTS idx_tv_notes_audience ON truth_vault.notes USING GIN(target_audience);
CREATE INDEX IF NOT EXISTS idx_tv_notes_archetype ON truth_vault.notes USING GIN(human_truth_archetype);
CREATE INDEX IF NOT EXISTS idx_tv_notes_hashtags ON truth_vault.notes USING GIN(hashtags);
CREATE INDEX IF NOT EXISTS idx_tv_notes_quality_flags ON truth_vault.notes USING GIN(data_quality_flags);


-- ════════════════════════════════════════════════════════════════════
-- 4. metric_snapshots (D-018, P2 hardened)
-- ════════════════════════════════════════════════════════════════════
-- 
-- P2 changes (audit issue 八):
--   - window_label: 显式标记快照属于哪个时间窗（2h/24h/72h/7d/14d/final/ad_hoc）
--     这比从 publish_time + collected_at 反算 hours 更稳，因为 publish_time
--     在历史数据里经常缺失或格式不一。
--   - hours_since_publish: 冗余列，方便建模时按整数小时数对齐。
--   - source: 必填，标识快照来源（manual / puyuan / xhs_scraper / ad_hoc 等）
--   - UNIQUE(note_id, window_label, source) 防止同一窗口被重复采集

CREATE TABLE IF NOT EXISTS truth_vault.metric_snapshots (
    snapshot_id TEXT PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,
    note_id TEXT NOT NULL REFERENCES truth_vault.notes(note_id) ON DELETE CASCADE,
    collected_at TIMESTAMP NOT NULL,
    
    -- ── 时间窗口标签（P2 八）──
    window_label TEXT NOT NULL DEFAULT 'ad_hoc'
        CHECK (window_label IN ('2h', '24h', '72h', '7d', '14d', '30d', 'final', 'ad_hoc')),
    hours_since_publish INT,   -- 冗余但稳定（publish_time 历史数据缺失/格式不一）
    
    impressions INT,
    reads INT,
    interactions INT,
    likes INT,
    saves INT,
    shares INT,
    comments_count INT,
    
    hit_blue_keywords TEXT[],
    search_rank INT,
    keyword_rank INT,
    
    notes TEXT,
    source TEXT NOT NULL DEFAULT 'ad_hoc',  -- 'manual' / 'puyuan' / 'xhs_scraper' / 'ad_hoc'
    
    -- 防重复采集：同一笔记的同一窗口、同一来源只能存一次
    -- 重新采集要么 UPDATE 已有行，要么先 DELETE 再 INSERT
    UNIQUE (note_id, window_label, source)
);

CREATE INDEX IF NOT EXISTS idx_tv_snapshots_note 
    ON truth_vault.metric_snapshots(note_id, collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_tv_snapshots_window 
    ON truth_vault.metric_snapshots(note_id, window_label);


-- ════════════════════════════════════════════════════════════════════
-- 5. posthoc_analyses (D-017 · 复盘独立存)
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS truth_vault.posthoc_analyses (
    analysis_id TEXT PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,
    note_id TEXT NOT NULL REFERENCES truth_vault.notes(note_id) ON DELETE CASCADE,
    
    analysis_mode TEXT 
        CHECK (analysis_mode IN ('success_pattern', 'failure_pattern', 'attribution', 'counter_factual')),
    
    attribution_explanation TEXT,
    contributing_factors JSONB,
    counter_factual TEXT,
    
    analyzed_by TEXT,
    analyzed_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tv_posthoc_note ON truth_vault.posthoc_analyses(note_id);


-- ════════════════════════════════════════════════════════════════════
-- 6. prepublish_evaluations (D-025 简化版)
-- ════════════════════════════════════════════════════════════════════
-- 
-- v1.1 中的 candidate_id FK 改为指向 autowriter.items.id（跨 schema）
-- 仅用于追踪 evaluator 准确率，不复制内容
-- autowriter._select_best_drafts 的隐式评审在 sync 时反推存入这里

CREATE TABLE IF NOT EXISTS truth_vault.prepublish_evaluations (
    evaluation_id TEXT PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,
    autowriter_item_id UUID NOT NULL,  -- → autowriter.items.id
    
    evaluator_type TEXT NOT NULL 
        CHECK (evaluator_type IN ('persona', 'critic', 'human', 'model', 'rule_based', 'autowriter_select_best')),
    evaluator_id TEXT,
    
    score_json JSONB,
    decision TEXT NOT NULL 
        CHECK (decision IN ('pass', 'revise', 'reject', 'publish')),
    reasoning TEXT,
    
    -- 后续从 truth_vault.notes.tier 反推 evaluator 准确率
    pred_tier_class TEXT,  -- 预测的 tier 等级
    actual_tier TEXT,      -- 实际 tier（事后填）
    was_correct BOOLEAN GENERATED ALWAYS AS (
        CASE 
            WHEN pred_tier_class IS NULL OR actual_tier IS NULL THEN NULL
            ELSE pred_tier_class = actual_tier 
        END
    ) STORED,
    
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tv_evals_aw_item ON truth_vault.prepublish_evaluations(autowriter_item_id);
CREATE INDEX IF NOT EXISTS idx_tv_evals_evaluator 
    ON truth_vault.prepublish_evaluations(evaluator_type, evaluator_id);


-- ════════════════════════════════════════════════════════════════════
-- 7. quality_review_decisions (D-013)
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS truth_vault.quality_review_decisions (
    review_id TEXT PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,
    note_id TEXT NOT NULL REFERENCES truth_vault.notes(note_id) ON DELETE CASCADE,
    
    flag_type TEXT,
    reviewer TEXT,
    decision TEXT 
        CHECK (decision IN ('真错标', 'LLM错判', '边界case', '需复查')),
    action_taken TEXT,
    notes TEXT,
    
    reviewed_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tv_quality_review_note ON truth_vault.quality_review_decisions(note_id);


-- ════════════════════════════════════════════════════════════════════
-- 8. comments (D-022 升级)
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS truth_vault.comments (
    comment_id TEXT PRIMARY KEY,
    note_id TEXT NOT NULL REFERENCES truth_vault.notes(note_id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES truth_vault.projects(project_id) ON DELETE CASCADE,
    
    content TEXT NOT NULL,
    
    -- ON DELETE SET NULL: if a parent comment is purged (e.g. an entire
    -- thread cascades from a notes delete), keep the child rows in place
    -- but break the hierarchy link. Default NO ACTION would FK-violate
    -- and block any bulk delete that touches a thread out-of-order.
    parent_comment_id TEXT REFERENCES truth_vault.comments(comment_id) ON DELETE SET NULL,
    comment_order INT,
    comment_time TIMESTAMP,
    
    comment_role TEXT 
        CHECK (comment_role IN ('贴主', '素人', '路人', '运营', '未知')),
    is_scripted BOOLEAN,
    comment_intent TEXT
        CHECK (comment_intent IN ('补充信息', '反驳质疑', '蓝词植入', '共鸣扩散', '引导私信', '其他')),
    
    comment_type TEXT 
        CHECK (comment_type IN ('贴主评论', '素人评论', '控评植入', '其他')),
    
    is_displayed BOOLEAN,
    is_pinned BOOLEAN DEFAULT FALSE,
    
    contains_blue_keyword BOOLEAN,
    blue_keywords_matched TEXT[],
    raw_extra JSONB,
    
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tv_comments_note ON truth_vault.comments(note_id);
CREATE INDEX IF NOT EXISTS idx_tv_comments_project ON truth_vault.comments(project_id);
CREATE INDEX IF NOT EXISTS idx_tv_comments_parent ON truth_vault.comments(parent_comment_id);
CREATE INDEX IF NOT EXISTS idx_tv_comments_role ON truth_vault.comments(comment_role);


-- ════════════════════════════════════════════════════════════════════
-- 9. notes_archive (无 tier 笔记)
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS truth_vault.notes_archive (
    archive_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES truth_vault.projects(project_id) ON DELETE CASCADE,
    account_id TEXT REFERENCES truth_vault.accounts(account_id),  -- D-030: 允许跨 archive/notes 的素人分析
    
    raw_content TEXT NOT NULL,
    title TEXT,
    body TEXT,
    intent TEXT,
    publish_time TIMESTAMP,
    publish_url TEXT,
    raw_extra JSONB,
    
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tv_archive_project ON truth_vault.notes_archive(project_id);
CREATE INDEX IF NOT EXISTS idx_tv_archive_publish_time ON truth_vault.notes_archive(publish_time);


-- ════════════════════════════════════════════════════════════════════
-- 10. audience_calibrations
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS truth_vault.audience_calibrations (
    calibration_id TEXT PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,
    note_id TEXT NOT NULL REFERENCES truth_vault.notes(note_id) ON DELETE CASCADE,
    
    age_inferred TEXT,
    age_actual TEXT,
    age_match BOOLEAN,
    
    gender_inferred TEXT,
    gender_actual TEXT,
    gender_match BOOLEAN,
    
    city_inferred TEXT[],
    city_actual TEXT,
    city_match BOOLEAN,
    
    calibrated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tv_calibrations_note ON truth_vault.audience_calibrations(note_id);


-- ════════════════════════════════════════════════════════════════════
-- 11. undeclared_fields_quarantine (D-021)
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS truth_vault.undeclared_fields_quarantine (
    quarantine_id TEXT PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,
    project_id TEXT NOT NULL REFERENCES truth_vault.projects(project_id),
    
    -- 飞书原始 record_id, 方便回到飞书表里找到那行
    feishu_record_id TEXT,
    
    raw_row JSONB NOT NULL,
    undeclared_field_names TEXT[] NOT NULL,
    
    -- 隔离原因 (默认是未声明字段; 未来可能有其他规则触发, 例如必填字段缺失)
    reason TEXT NOT NULL DEFAULT 'undeclared_fields',
    
    status TEXT DEFAULT 'pending' 
        CHECK (status IN ('pending', 'reviewed', 'resolved', 'rejected')),
    review_decision TEXT,
    reviewed_by TEXT,
    reviewed_at TIMESTAMP,
    
    quarantined_at TIMESTAMP DEFAULT NOW()
);

-- 兼容已部署的 schema (无 feishu_record_id / reason 列)
ALTER TABLE truth_vault.undeclared_fields_quarantine 
    ADD COLUMN IF NOT EXISTS feishu_record_id TEXT;
ALTER TABLE truth_vault.undeclared_fields_quarantine 
    ADD COLUMN IF NOT EXISTS reason TEXT NOT NULL DEFAULT 'undeclared_fields';

CREATE INDEX IF NOT EXISTS idx_tv_quarantine_project ON truth_vault.undeclared_fields_quarantine(project_id);
CREATE INDEX IF NOT EXISTS idx_tv_quarantine_status ON truth_vault.undeclared_fields_quarantine(status);
CREATE INDEX IF NOT EXISTS idx_tv_quarantine_feishu ON truth_vault.undeclared_fields_quarantine(feishu_record_id);


-- ════════════════════════════════════════════════════════════════════
-- 12. note_features (阶段 1 末期启用)
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS truth_vault.note_features (
    note_id TEXT PRIMARY KEY REFERENCES truth_vault.notes(note_id) ON DELETE CASCADE,
    
    title_len INT,
    body_len INT,
    hashtag_count INT,
    mention_count INT,
    
    opener_type TEXT,
    title_hook_type TEXT,
    has_specific_scene BOOLEAN,
    has_dialogue BOOLEAN,
    
    compliance_red_flags TEXT[],
    ai_smell_score INT,
    
    extracted_at TIMESTAMP,
    extractor_version TEXT
);


-- ════════════════════════════════════════════════════════════════════
-- Triggers
-- ════════════════════════════════════════════════════════════════════

CREATE OR REPLACE FUNCTION truth_vault.fill_era_tag() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.publish_time IS NOT NULL THEN
        NEW.era_tag := EXTRACT(YEAR FROM NEW.publish_time)::TEXT 
                       || ' Q' 
                       || EXTRACT(QUARTER FROM NEW.publish_time)::TEXT;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tv_notes_set_era ON truth_vault.notes;
CREATE TRIGGER tv_notes_set_era 
BEFORE INSERT OR UPDATE OF publish_time ON truth_vault.notes
FOR EACH ROW EXECUTE FUNCTION truth_vault.fill_era_tag();


CREATE OR REPLACE FUNCTION truth_vault.set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tv_projects_updated_at ON truth_vault.projects;
CREATE TRIGGER tv_projects_updated_at 
BEFORE UPDATE ON truth_vault.projects
FOR EACH ROW EXECUTE FUNCTION truth_vault.set_updated_at();

DROP TRIGGER IF EXISTS tv_notes_updated_at ON truth_vault.notes;
CREATE TRIGGER tv_notes_updated_at 
BEFORE UPDATE ON truth_vault.notes
FOR EACH ROW EXECUTE FUNCTION truth_vault.set_updated_at();

DROP TRIGGER IF EXISTS tv_accounts_updated_at ON truth_vault.accounts;
CREATE TRIGGER tv_accounts_updated_at 
BEFORE UPDATE ON truth_vault.accounts
FOR EACH ROW EXECUTE FUNCTION truth_vault.set_updated_at();


-- ════════════════════════════════════════════════════════════════════
-- Views · 跨 schema 飞轮反馈数据源
-- ════════════════════════════════════════════════════════════════════
-- 
-- 这些 view 替代 v1.1 的 v_prompt_performance / v_model_comparison
-- 数据通过 join 现存系统的表得到，而不是从 truth_vault 自己的表


-- ── 项目 tier 分布（基础统计）──
CREATE OR REPLACE VIEW truth_vault.v_project_tier_summary AS
SELECT 
    p.project_id, p.brand, p.category,
    COUNT(n.note_id) as total_notes,
    SUM(CASE WHEN n.tier = '趴' THEN 1 ELSE 0 END) as count_pa,
    SUM(CASE WHEN n.tier = '爆' THEN 1 ELSE 0 END) as count_bao,
    SUM(CASE WHEN n.tier = '大爆' THEN 1 ELSE 0 END) as count_dabao,
    SUM(CASE WHEN n.tier IS NOT NULL THEN 1 ELSE 0 END) as count_labeled,
    AVG(n.interactions) FILTER (WHERE n.tier = '爆') as avg_interactions_bao
FROM truth_vault.projects p
LEFT JOIN truth_vault.notes n ON p.project_id = n.project_id
GROUP BY p.project_id, p.brand, p.category;


-- ── 数据健康度 ──
CREATE OR REPLACE VIEW truth_vault.v_data_health AS
SELECT 
    p.project_id, p.brand,
    COUNT(n.note_id) as total,
    SUM(CASE WHEN n.impressions IS NOT NULL THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(n.note_id), 0) as data_recovery_rate,
    SUM(CASE WHEN n.tier IS NOT NULL THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(n.note_id), 0) as tier_coverage_rate,
    SUM(CASE WHEN n.emotional_lever IS NOT NULL THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(n.note_id), 0) as essence_coverage_rate,
    SUM(CASE WHEN n.account_id IS NOT NULL THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(n.note_id), 0) as account_link_rate,
    SUM(CASE WHEN n.synced_to_ssll_at IS NOT NULL THEN 1 ELSE 0 END) as synced_to_ssll,
    SUM(CASE WHEN n.synced_to_aw_at IS NOT NULL THEN 1 ELSE 0 END) as synced_to_aw
FROM truth_vault.projects p
LEFT JOIN truth_vault.notes n ON p.project_id = n.project_id
GROUP BY p.project_id, p.brand;


-- ── 跨项目高爆率素人 (D-020) ──
-- Computes derived stats LIVE from notes rather than depending on the
-- accounts.total_notes_count / bao_count / personal_bao_rate cache, which
-- has no maintenance trigger yet. As soon as a backfill job is in place
-- to keep the cached columns fresh, switch back to reading them directly.
CREATE OR REPLACE VIEW truth_vault.v_top_performing_accounts AS
WITH per_account AS (
    SELECT
        n.account_id,
        COUNT(*)                                                              AS total_notes,
        SUM(CASE WHEN n.tier = '爆'   THEN 1 ELSE 0 END)                       AS bao_count,
        SUM(CASE WHEN n.tier = '大爆' THEN 1 ELSE 0 END)                       AS dabao_count,
        SUM(CASE WHEN n.tier IN ('爆','大爆') THEN 1 ELSE 0 END)::FLOAT
            / NULLIF(SUM(CASE WHEN n.tier IS NOT NULL THEN 1 ELSE 0 END), 0)   AS personal_bao_rate,
        array_agg(DISTINCT n.project_id)                                       AS projects_engaged
    FROM truth_vault.notes n
    WHERE n.account_id IS NOT NULL
    GROUP BY n.account_id
)
SELECT
    a.account_id,
    p.total_notes                       AS total_notes_count,
    p.bao_count + p.dabao_count         AS total_bao,
    p.personal_bao_rate,
    p.projects_engaged
FROM truth_vault.accounts a
JOIN per_account p ON p.account_id = a.account_id
WHERE p.total_notes >= 5
ORDER BY p.personal_bao_rate DESC NULLS LAST;


-- ════════════════════════════════════════════════════════════════════
-- 跨 schema views → 见 notes_v1_2_cross_schema_views.sql
-- ════════════════════════════════════════════════════════════════════
-- 
-- v_prompt_performance 和 v_model_comparison 依赖 public.outputs /
-- autowriter.versions 等外部 schema 的表。
-- 为避免部署顺序依赖（D-029），这些 view 拆到独立文件：
--   schemas/notes_v1_2_cross_schema_views.sql
-- 
-- 在 autowriter 迁移到 autowriter schema 之后再执行该文件。


-- ── Evaluator 校准 (D-013 + D-025) ──
CREATE OR REPLACE VIEW truth_vault.v_evaluator_calibration AS
SELECT 
    e.evaluator_type,
    e.evaluator_id,
    COUNT(*) AS total_evaluations,
    SUM(CASE WHEN e.was_correct THEN 1 ELSE 0 END) AS correct_predictions,
    AVG(CASE WHEN e.was_correct THEN 1.0 ELSE 0.0 END) AS accuracy_rate,
    -- 分别看 pass / reject 的准确率
    SUM(CASE WHEN e.decision = 'pass' AND e.actual_tier IN ('爆','大爆') THEN 1 ELSE 0 END)::FLOAT 
        / NULLIF(SUM(CASE WHEN e.decision = 'pass' THEN 1 ELSE 0 END), 0) AS pass_pred_bao_rate,
    SUM(CASE WHEN e.decision = 'reject' AND e.actual_tier IN ('爆','大爆') THEN 1 ELSE 0 END)::FLOAT 
        / NULLIF(SUM(CASE WHEN e.decision = 'reject' THEN 1 ELSE 0 END), 0) AS reject_pred_bao_rate
FROM truth_vault.prepublish_evaluations e
WHERE e.was_correct IS NOT NULL
GROUP BY e.evaluator_type, e.evaluator_id;


-- ── 飞轮 sync 状态监控 ──
CREATE OR REPLACE VIEW truth_vault.v_flywheel_sync_status AS
SELECT 
    p.project_id, p.brand,
    -- 爆款总数
    SUM(CASE WHEN n.tier IN ('爆', '大爆') THEN 1 ELSE 0 END) AS total_baokuan,
    -- 已 sync 到 sanshengliubu
    SUM(CASE WHEN n.tier IN ('爆', '大爆') AND n.synced_to_ssll_at IS NOT NULL THEN 1 ELSE 0 END) AS synced_to_ssll,
    -- 已 sync 到 autowriter
    SUM(CASE WHEN n.tier IN ('爆', '大爆') AND n.synced_to_aw_at IS NOT NULL THEN 1 ELSE 0 END) AS synced_to_aw,
    -- 待 sync
    SUM(CASE WHEN n.tier IN ('爆', '大爆') AND n.synced_to_ssll_at IS NULL THEN 1 ELSE 0 END) AS pending_ssll_sync,
    SUM(CASE WHEN n.tier IN ('爆', '大爆') AND n.synced_to_aw_at IS NULL THEN 1 ELSE 0 END) AS pending_aw_sync,
    p.last_baokuan_sync_to_ssll_at,
    p.last_baokuan_sync_to_aw_at
FROM truth_vault.projects p
LEFT JOIN truth_vault.notes n ON p.project_id = n.project_id
GROUP BY p.project_id, p.brand, p.last_baokuan_sync_to_ssll_at, p.last_baokuan_sync_to_aw_at;


-- ════════════════════════════════════════════════════════════════════
-- 完成
-- ════════════════════════════════════════════════════════════════════
-- 
-- 部署步骤（D-029 顺序）：
-- 1. 执行本文件（notes_v1_2.sql）—— 创建 truth_vault schema + 所有表 + 内部 views
-- 2. sanshengliubu 在 public schema 部署（已有，不动）
-- 3. autowriter 迁移到 autowriter schema（避免 public.projects 冲突）
-- 4. 三个 schema 就绪后，执行 notes_v1_2_cross_schema_views.sql
-- 5. 运行 sync 脚本（详见 docs/09-system-integration.md）
