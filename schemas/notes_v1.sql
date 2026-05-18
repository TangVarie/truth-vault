-- ════════════════════════════════════════════════════════════════════
-- Truth Vault · Schema v1.0
-- ════════════════════════════════════════════════════════════════════
-- 
-- 直接在 Supabase SQL Editor 里执行。
-- 包含: 建表 + 索引 + 触发器
-- 不包含: RLS 策略（部署到 production 时另外配）
-- 
-- 字段说明请参见 docs/02-schema-v1.md
-- ════════════════════════════════════════════════════════════════════

-- ════════════════════════════════════════════════════════════════════
-- Extensions
-- ════════════════════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
-- pgvector 在阶段 3 启用，启动期先不开
-- CREATE EXTENSION IF NOT EXISTS vector;

-- ════════════════════════════════════════════════════════════════════
-- Table: projects
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    brand TEXT NOT NULL,
    product TEXT NOT NULL,
    category TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'xiaohongshu',
    schema_family TEXT CHECK (schema_family IN ('A', 'B', 'C')),
    
    start_date DATE,
    end_date DATE,
    
    -- Onboarding 配置（mappings/<project_id>.yaml 内容）
    mapping_config JSONB,
    
    -- 项目级 tier 阈值
    tier_thresholds JSONB DEFAULT '{"爆": 100, "大爆": 1000}'::jsonb,
    
    -- 健康度元数据
    total_notes INT DEFAULT 0,
    notes_with_data INT DEFAULT 0,
    notes_with_tier INT DEFAULT 0,
    notes_with_essence INT DEFAULT 0,
    notes_with_actual_audience INT DEFAULT 0,
    last_sync_at TIMESTAMP,
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_projects_brand ON projects(brand);
CREATE INDEX IF NOT EXISTS idx_projects_category ON projects(category);

-- ════════════════════════════════════════════════════════════════════
-- Table: notes (核心表)
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS notes (
    -- ── 标识 ──
    note_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    
    -- ════════════════════════════════════════
    -- Layer 1 · SURFACE
    -- ════════════════════════════════════════
    
    title TEXT,
    body TEXT,
    hashtags TEXT[],
    raw_content TEXT NOT NULL,
    
    intent TEXT CHECK (intent IN ('traffic', 'conversion', 'educational', 'mixed', 'other')),
    content_format TEXT,
    
    -- ════════════════════════════════════════
    -- Layer 2 · ESSENCE (允许 onboarding 时延迟填充)
    -- ════════════════════════════════════════
    
    emotional_lever TEXT,
    emotional_valence TEXT CHECK (emotional_valence IN ('positive', 'negative', 'neutral')),
    emotional_intensity TEXT CHECK (emotional_intensity IN ('low', 'medium', 'high')),
    human_truth_archetype TEXT[],
    trend_dependencies TEXT[],
    
    -- ════════════════════════════════════════
    -- Layer 3 · AUDIENCE
    -- ════════════════════════════════════════
    
    target_audience TEXT[],
    inferred_audience_profile JSONB,
    actual_audience_data JSONB,
    
    -- 项目专属维度（方向拆解结果）
    user_pain_point TEXT,
    product_focus TEXT,
    
    -- ════════════════════════════════════════
    -- 投放元数据
    -- ════════════════════════════════════════
    
    account_name TEXT,
    account_followers INT,
    publish_time TIMESTAMP,
    publish_url TEXT,
    target_blue_keywords TEXT[],
    
    -- ════════════════════════════════════════
    -- 数据回收
    -- ════════════════════════════════════════
    
    impressions INT,
    reads INT,
    interactions INT,
    hit_blue_keywords TEXT[],
    
    -- 衍生数值（自动计算）
    read_rate FLOAT GENERATED ALWAYS AS (
        CASE WHEN impressions > 0 AND impressions IS NOT NULL THEN reads::FLOAT / impressions ELSE NULL END
    ) STORED,
    interaction_rate FLOAT GENERATED ALWAYS AS (
        CASE WHEN reads > 0 AND reads IS NOT NULL THEN interactions::FLOAT / reads ELSE NULL END
    ) STORED,
    
    -- ════════════════════════════════════════
    -- 人工标签（金标准）
    -- ════════════════════════════════════════
    
    tier TEXT CHECK (tier IN ('趴', '预备', '爆', '大爆', '风控', '删除', '未知')),
    tier_source TEXT CHECK (tier_source IN ('状态字段', '备注字段', '数值推断', '人工补录', '未标注')),
    data_quality_status TEXT,
    
    -- ════════════════════════════════════════
    -- 控评/合规
    -- ════════════════════════════════════════
    
    pinned_comment TEXT,
    has_compliance_issue BOOLEAN DEFAULT FALSE,
    compliance_notes TEXT,
    
    -- ════════════════════════════════════════
    -- 标注元数据
    -- ════════════════════════════════════════
    
    essence_annotated_by TEXT,
    essence_annotated_at TIMESTAMP,
    essence_vocab_version TEXT,
    
    audience_inferred_at TIMESTAMP,
    audience_actual_synced_at TIMESTAMP,
    
    -- ════════════════════════════════════════
    -- 元数据
    -- ════════════════════════════════════════
    
    raw_extra JSONB,
    era_tag TEXT,
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_notes_project ON notes(project_id);
CREATE INDEX IF NOT EXISTS idx_notes_publish_time ON notes(publish_time);
CREATE INDEX IF NOT EXISTS idx_notes_tier ON notes(tier);
CREATE INDEX IF NOT EXISTS idx_notes_intent ON notes(intent);
CREATE INDEX IF NOT EXISTS idx_notes_content_format ON notes(content_format);
CREATE INDEX IF NOT EXISTS idx_notes_essence_lever ON notes(emotional_lever);
CREATE INDEX IF NOT EXISTS idx_notes_era ON notes(era_tag);
CREATE INDEX IF NOT EXISTS idx_notes_url ON notes(publish_url);

-- GIN 索引用于数组字段
CREATE INDEX IF NOT EXISTS idx_notes_audience ON notes USING GIN(target_audience);
CREATE INDEX IF NOT EXISTS idx_notes_archetype ON notes USING GIN(human_truth_archetype);
CREATE INDEX IF NOT EXISTS idx_notes_hashtags ON notes USING GIN(hashtags);
CREATE INDEX IF NOT EXISTS idx_notes_target_blue ON notes USING GIN(target_blue_keywords);
CREATE INDEX IF NOT EXISTS idx_notes_hit_blue ON notes USING GIN(hit_blue_keywords);

-- ════════════════════════════════════════════════════════════════════
-- Triggers: 自动填充 era_tag
-- ════════════════════════════════════════════════════════════════════

CREATE OR REPLACE FUNCTION fill_era_tag() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.publish_time IS NOT NULL THEN
        NEW.era_tag := EXTRACT(YEAR FROM NEW.publish_time)::TEXT 
                       || ' Q' 
                       || EXTRACT(QUARTER FROM NEW.publish_time)::TEXT;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS notes_set_era ON notes;
CREATE TRIGGER notes_set_era 
BEFORE INSERT OR UPDATE OF publish_time ON notes
FOR EACH ROW EXECUTE FUNCTION fill_era_tag();

-- ════════════════════════════════════════════════════════════════════
-- Triggers: updated_at 自动更新
-- ════════════════════════════════════════════════════════════════════

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS projects_updated_at ON projects;
CREATE TRIGGER projects_updated_at 
BEFORE UPDATE ON projects
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS notes_updated_at ON notes;
CREATE TRIGGER notes_updated_at 
BEFORE UPDATE ON notes
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ════════════════════════════════════════════════════════════════════
-- Table: comments
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS comments (
    comment_id TEXT PRIMARY KEY,
    note_id TEXT NOT NULL REFERENCES notes(note_id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    
    content TEXT NOT NULL,
    comment_type TEXT CHECK (comment_type IN ('贴主评论', '素人评论', '控评植入', '其他')),
    
    is_displayed BOOLEAN,
    is_pinned BOOLEAN DEFAULT FALSE,
    
    contains_blue_keyword BOOLEAN,
    blue_keywords_matched TEXT[],
    
    raw_extra JSONB,
    
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_comments_note ON comments(note_id);
CREATE INDEX IF NOT EXISTS idx_comments_project ON comments(project_id);
CREATE INDEX IF NOT EXISTS idx_comments_type ON comments(comment_type);

-- ════════════════════════════════════════════════════════════════════
-- Table: notes_archive (QSHG_1 等无 tier 笔记)
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS notes_archive (
    archive_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    
    raw_content TEXT NOT NULL,
    title TEXT,
    body TEXT,
    
    intent TEXT,
    publish_time TIMESTAMP,
    publish_url TEXT,
    
    raw_extra JSONB,
    
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_archive_project ON notes_archive(project_id);

-- ════════════════════════════════════════════════════════════════════
-- Table: note_features (阶段 1 末期启用)
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS note_features (
    note_id TEXT PRIMARY KEY REFERENCES notes(note_id) ON DELETE CASCADE,
    
    -- 词法特征
    title_len INT,
    body_len INT,
    hashtag_count INT,
    mention_count INT,
    mention_position_first INT,
    has_number_in_title BOOLEAN,
    has_emoji_in_title BOOLEAN,
    has_question_in_title BOOLEAN,
    
    -- LLM 抽取
    opener_type TEXT,
    title_hook_type TEXT,
    has_specific_scene BOOLEAN,
    has_dialogue BOOLEAN,
    has_self_deprecation BOOLEAN,
    
    -- 风险信号
    compliance_red_flags TEXT[],
    ai_smell_score INT,
    
    -- 元数据
    extracted_at TIMESTAMP,
    extractor_version TEXT
);

-- ════════════════════════════════════════════════════════════════════
-- Table: calibration_records (audience 校准日志)
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS audience_calibrations (
    calibration_id TEXT PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,
    note_id TEXT NOT NULL REFERENCES notes(note_id) ON DELETE CASCADE,
    
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

CREATE INDEX IF NOT EXISTS idx_calibrations_note ON audience_calibrations(note_id);

-- ════════════════════════════════════════════════════════════════════
-- Views: 常用查询视图
-- ════════════════════════════════════════════════════════════════════

-- 项目级别的 tier 分布
CREATE OR REPLACE VIEW v_project_tier_summary AS
SELECT 
    p.project_id,
    p.brand,
    p.category,
    COUNT(n.note_id) as total_notes,
    SUM(CASE WHEN n.tier = '趴' THEN 1 ELSE 0 END) as count_pa,
    SUM(CASE WHEN n.tier = '爆' THEN 1 ELSE 0 END) as count_bao,
    SUM(CASE WHEN n.tier = '大爆' THEN 1 ELSE 0 END) as count_dabao,
    SUM(CASE WHEN n.tier = '风控' THEN 1 ELSE 0 END) as count_fengkong,
    SUM(CASE WHEN n.tier IS NOT NULL THEN 1 ELSE 0 END) as count_labeled,
    AVG(n.interactions) FILTER (WHERE n.tier = '爆') as avg_interactions_bao,
    AVG(n.interactions) FILTER (WHERE n.tier = '趴') as avg_interactions_pa
FROM projects p
LEFT JOIN notes n ON p.project_id = n.project_id
GROUP BY p.project_id, p.brand, p.category;

-- 数据健康度
CREATE OR REPLACE VIEW v_data_health AS
SELECT 
    p.project_id,
    p.brand,
    COUNT(n.note_id) as total,
    SUM(CASE WHEN n.impressions IS NOT NULL THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(n.note_id), 0) as data_recovery_rate,
    SUM(CASE WHEN n.tier IS NOT NULL THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(n.note_id), 0) as tier_coverage_rate,
    SUM(CASE WHEN n.emotional_lever IS NOT NULL THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(n.note_id), 0) as essence_coverage_rate,
    SUM(CASE WHEN n.actual_audience_data IS NOT NULL THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(n.note_id), 0) as audience_coverage_rate
FROM projects p
LEFT JOIN notes n ON p.project_id = n.project_id
GROUP BY p.project_id, p.brand;

-- ════════════════════════════════════════════════════════════════════
-- 初始化样本数据（可选 - 用于测试）
-- ════════════════════════════════════════════════════════════════════
-- 
-- INSERT INTO projects (project_id, brand, product, category, schema_family) VALUES
-- ('NUC_phase1', '大象集团', 'Nucare 全营养液体', '保健品', 'B');
-- 
-- 完整 onboarding 见 mappings/NUC_phase1.yaml + docs/04-onboarding-sop.md
-- ════════════════════════════════════════════════════════════════════
