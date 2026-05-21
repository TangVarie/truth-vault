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

-- Supabase 把扩展函数装在独立 `extensions` schema. 没把 extensions 加进
-- search_path 的话 uuid_generate_v4() 会 42883 function does not exist.
-- WITH SCHEMA extensions 仅在 fresh install 时生效; 已部署环境 CREATE
-- EXTENSION IF NOT EXISTS 是 no-op, schema 位置维持原状.
-- 先 CREATE SCHEMA IF NOT EXISTS extensions: Supabase 早就有 (no-op),
-- 但 CI / 裸 Postgres 默认没有, 不显式建会让 WITH SCHEMA extensions
-- 报 42P01 "schema extensions does not exist".
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA extensions;
CREATE SCHEMA IF NOT EXISTS truth_vault;

SET search_path TO truth_vault, public, extensions;


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
    -- 删除了 last_baokuan_sync_to_ssll_at / last_baokuan_sync_to_aw_at:
    -- 没有任何 sync 脚本会更新它们 (sync 脚本只动 notes 行级的 synced_to_*_at).
    -- v_flywheel_sync_status view 改用 MAX(n.synced_to_*_at) 动态计算这两个值,
    -- 见本文件末尾 view 定义.

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 兼容已部署 schema: 老库可能有这两列, 强制清掉避免 view 引用混乱
ALTER TABLE truth_vault.projects DROP COLUMN IF EXISTS last_baokuan_sync_to_ssll_at;
ALTER TABLE truth_vault.projects DROP COLUMN IF EXISTS last_baokuan_sync_to_aw_at;

CREATE INDEX IF NOT EXISTS idx_tv_projects_brand ON truth_vault.projects(brand);
CREATE INDEX IF NOT EXISTS idx_tv_projects_category ON truth_vault.projects(category);

-- ⚠️ projects.{total_notes, notes_with_data, notes_with_tier,
-- notes_with_essence, notes_with_actual_audience, last_sync_at}
-- 也是缓存列，目前无维护任务。聚合统计请用 v_project_tier_summary /
-- v_data_health / v_flywheel_sync_status。同 R-006。
COMMENT ON COLUMN truth_vault.projects.total_notes IS
    'CACHE-ONLY · 未自动维护; 用 v_project_tier_summary.total_notes';
COMMENT ON COLUMN truth_vault.projects.notes_with_data IS
    'CACHE-ONLY · 未自动维护';
COMMENT ON COLUMN truth_vault.projects.notes_with_tier IS
    'CACHE-ONLY · 未自动维护; 用 v_data_health.tier_coverage_rate';
COMMENT ON COLUMN truth_vault.projects.notes_with_essence IS
    'CACHE-ONLY · 未自动维护; 用 v_data_health.essence_coverage_rate';
COMMENT ON COLUMN truth_vault.projects.notes_with_actual_audience IS
    'CACHE-ONLY · 未自动维护';
COMMENT ON COLUMN truth_vault.projects.last_sync_at IS
    'CACHE-ONLY · 未自动维护; 用 v_flywheel_sync_status.last_baokuan_sync_to_*_at';


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

-- ⚠️ accounts.{total_notes_count, bao_count, dabao_count, fengkong_count,
-- deleted_count, personal_bao_rate} 当前是缓存列，没有触发器或后台 job 维护。
-- 真实的 per-account 聚合统计在 v_top_performing_accounts 里 live-compute
-- 出来（按 truth_vault.notes 汇总）。在 cache 维护 job 落地之前，请直接读
-- view；这些列只用于历史快照场景（操作员人工写入备份）。详见 RISKS.md R-006。
COMMENT ON COLUMN truth_vault.accounts.total_notes_count IS
    'CACHE-ONLY · 未自动维护; 用 v_top_performing_accounts.total_notes_count';
COMMENT ON COLUMN truth_vault.accounts.bao_count IS
    'CACHE-ONLY · 未自动维护; 用 v_top_performing_accounts.total_bao';
COMMENT ON COLUMN truth_vault.accounts.dabao_count IS
    'CACHE-ONLY · 未自动维护';
COMMENT ON COLUMN truth_vault.accounts.fengkong_count IS
    'CACHE-ONLY · 未自动维护';
COMMENT ON COLUMN truth_vault.accounts.deleted_count IS
    'CACHE-ONLY · 未自动维护';
COMMENT ON COLUMN truth_vault.accounts.personal_bao_rate IS
    'CACHE-ONLY · 未自动维护; 用 v_top_performing_accounts.personal_bao_rate';


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
-- 时间窗口聚合查询 (例 "过去 7 天的 7d window 快照" 用于 dashboard
-- + alerting): 这种 SQL 没有 note_id 前缀,会让上两个索引失效,导致
-- 全表扫. 加 (window_label, collected_at DESC) 覆盖该模式.
CREATE INDEX IF NOT EXISTS idx_tv_snapshots_window_time
    ON truth_vault.metric_snapshots(window_label, collected_at DESC);


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

-- 2026-05-22 audit P1/P2-4: partial UNIQUE 防 decision sync 并发写重复.
-- sync_autowriter_decisions_to_prepublish.py 的文档承诺 "每个 (autowriter_item_id,
-- evaluator_type='human') 元组只写一次", 但旧 schema 只有普通 index, 多 worker
-- 并发跑或者 retry 重叠时会插重复. evaluator_type='persona'/'critic'/'model'
-- 等 LLM evaluator 未来可能多次评分 (不同时间点的回顾打分), 所以约束限定在
-- evaluator_type='human' 的范围, 不影响 LLM 评估走多行历史的设计.
CREATE UNIQUE INDEX IF NOT EXISTS idx_tv_evals_aw_item_evaluator_uniq
    ON truth_vault.prepublish_evaluations (autowriter_item_id, evaluator_type)
    WHERE autowriter_item_id IS NOT NULL
      AND evaluator_type = 'human';


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

-- 幂等性: 同一 (project, feishu_record, reason) 三元组只保留一行。re-sync 一个
-- 仍带未声明字段的飞书记录不再叠加 quarantine 行。先去重已部署库里的历史
-- 重复行 (按 quarantined_at 保留最新), 再加 UNIQUE。
WITH ranked AS (
    SELECT quarantine_id,
           ROW_NUMBER() OVER (
               PARTITION BY project_id, feishu_record_id, reason
               ORDER BY quarantined_at DESC, quarantine_id DESC
           ) AS rn
    FROM truth_vault.undeclared_fields_quarantine
    WHERE feishu_record_id IS NOT NULL
)
DELETE FROM truth_vault.undeclared_fields_quarantine
WHERE quarantine_id IN (SELECT quarantine_id FROM ranked WHERE rn > 1);

-- 历史版本曾用 ADD CONSTRAINT UNIQUE (...); 但 SQL UNIQUE 把 NULL 视为不相等,
-- feishu_record_id 为 NULL 的行会无限堆积. 改成 partial UNIQUE INDEX,
-- 只在 feishu_record_id 非空时去重 (这正是有意义的场景). 匿名行 (NULL
-- feishu_record_id) 无法跨 run 关联, 重复是无害的且原本就不该出现.
ALTER TABLE truth_vault.undeclared_fields_quarantine
    DROP CONSTRAINT IF EXISTS uq_quarantine_project_record_reason;

CREATE UNIQUE INDEX IF NOT EXISTS uq_quarantine_project_record_reason
    ON truth_vault.undeclared_fields_quarantine
    (project_id, feishu_record_id, reason)
    WHERE feishu_record_id IS NOT NULL;


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
-- Audit log (D-036 配套): 谁 / 何时 / 改了哪行 / 改了哪些字段
-- ════════════════════════════════════════════════════════════════════
--
-- 触发条件 (来自 CURRENT_STATE.md 延后清单 🟡 慢性病): "真出现过一次
-- 误操作污染生产; 或合规要求审计". 这个 table + trigger 是为了在
-- 真发生之前就把基础设施铺好, 之后不用再去回溯 sync log 找 "谁动的".
--
-- 设计原则:
--   - 只记 truth_vault schema 的写入 (跨 schema 写需要分别在 ssll / aw
--     schema 里也建审计, 但那两个 schema 不是我们维护的; 留待 ssll/aw
--     的运维者各自决定)
--   - 记 row_id (PK) + operation (INSERT/UPDATE/DELETE) + timestamp +
--     session_user (Postgres role) + application_name (PostgREST 透传)
--   - changed_cols 用 jsonb {col: [old_val, new_val]} 形式, 只在 UPDATE
--     时填; INSERT / DELETE 填整行
--   - 30 天 retention (后台任务 / 手动 DELETE 都可以)

CREATE TABLE IF NOT EXISTS truth_vault.audit_log (
    audit_id      BIGSERIAL PRIMARY KEY,
    schema_name   TEXT NOT NULL,
    table_name    TEXT NOT NULL,
    row_id        TEXT,                    -- PK as TEXT (notes.note_id is text, items.id is uuid → text)
    operation     TEXT NOT NULL CHECK (operation IN ('INSERT','UPDATE','DELETE')),
    changed_cols  JSONB,                   -- {col: [old, new]} on UPDATE, full row on INSERT, deleted row on DELETE
    actor_user    TEXT,                    -- session_user; for service_role this is 'service_role'
    application   TEXT,                    -- application_name from connection
    occurred_at   TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tv_audit_table_time
    ON truth_vault.audit_log(table_name, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_tv_audit_row
    ON truth_vault.audit_log(schema_name, table_name, row_id, occurred_at DESC);

-- SET search_path = '': Supabase advisor "Function Search Path Mutable" 修法.
-- 函数体所有表引用都 fully qualified (truth_vault.audit_log), 系统函数
-- (COALESCE/to_jsonb/jsonb_*) 来自 pg_catalog 永远隐式可用. 安全清晰.
CREATE OR REPLACE FUNCTION truth_vault.audit_row_change() RETURNS TRIGGER
    LANGUAGE plpgsql
    SET search_path = ''
AS $$
DECLARE
    pk_value TEXT;
    changed JSONB;
    actor TEXT;
    app TEXT;
BEGIN
    -- Best-effort actor identification. service_role token surfaces as
    -- 'service_role' here. PostgREST sets application_name on the conn.
    actor := COALESCE(current_setting('request.jwt.claim.role', true),
                      session_user::TEXT,
                      'unknown');
    app := COALESCE(current_setting('application_name', true), '');

    -- Resolve PK as TEXT (table-specific; only the tables we wire up here)
    IF TG_TABLE_NAME = 'notes' THEN
        IF TG_OP = 'DELETE' THEN pk_value := OLD.note_id;
        ELSE pk_value := NEW.note_id;
        END IF;
    ELSIF TG_TABLE_NAME = 'projects' THEN
        IF TG_OP = 'DELETE' THEN pk_value := OLD.project_id;
        ELSE pk_value := NEW.project_id;
        END IF;
    ELSE
        pk_value := NULL;   -- unrecognized table; just log without row_id
    END IF;

    -- changed_cols: full row on INSERT/DELETE; diff on UPDATE
    IF TG_OP = 'INSERT' THEN
        changed := to_jsonb(NEW);
    ELSIF TG_OP = 'DELETE' THEN
        changed := to_jsonb(OLD);
    ELSE  -- UPDATE
        SELECT jsonb_object_agg(key, jsonb_build_array(old_val, new_val))
        INTO changed
        FROM (
            SELECT key, old_val, new_val
            FROM jsonb_each(to_jsonb(OLD)) AS o(key, old_val)
            JOIN jsonb_each(to_jsonb(NEW)) AS n(key, new_val) USING (key)
            WHERE old_val IS DISTINCT FROM new_val
        ) diff;
        -- No changes? Skip the log row to keep noise down.
        IF changed IS NULL THEN
            RETURN NEW;
        END IF;
    END IF;

    INSERT INTO truth_vault.audit_log
        (schema_name, table_name, row_id, operation, changed_cols, actor_user, application)
    VALUES
        (TG_TABLE_SCHEMA, TG_TABLE_NAME, pk_value, TG_OP, changed, actor, app);

    RETURN COALESCE(NEW, OLD);
END;
$$;

-- Wire to the two highest-value writeable tables (notes + projects). Other
-- tables can be added later; we don't audit comments/snapshots etc. because
-- they're append-mostly and the volume would crowd the log without value.
DROP TRIGGER IF EXISTS tv_audit_notes ON truth_vault.notes;
CREATE TRIGGER tv_audit_notes
AFTER INSERT OR UPDATE OR DELETE ON truth_vault.notes
FOR EACH ROW EXECUTE FUNCTION truth_vault.audit_row_change();

DROP TRIGGER IF EXISTS tv_audit_projects ON truth_vault.projects;
CREATE TRIGGER tv_audit_projects
AFTER INSERT OR UPDATE OR DELETE ON truth_vault.projects
FOR EACH ROW EXECUTE FUNCTION truth_vault.audit_row_change();


-- ════════════════════════════════════════════════════════════════════
-- Triggers
-- ════════════════════════════════════════════════════════════════════

CREATE OR REPLACE FUNCTION truth_vault.fill_era_tag() RETURNS TRIGGER
    LANGUAGE plpgsql
    SET search_path = ''
AS $$
BEGIN
    IF NEW.publish_time IS NOT NULL THEN
        NEW.era_tag := EXTRACT(YEAR FROM NEW.publish_time)::TEXT
                       || ' Q'
                       || EXTRACT(QUARTER FROM NEW.publish_time)::TEXT;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS tv_notes_set_era ON truth_vault.notes;
CREATE TRIGGER tv_notes_set_era 
BEFORE INSERT OR UPDATE OF publish_time ON truth_vault.notes
FOR EACH ROW EXECUTE FUNCTION truth_vault.fill_era_tag();


CREATE OR REPLACE FUNCTION truth_vault.set_updated_at() RETURNS TRIGGER
    LANGUAGE plpgsql
    SET search_path = ''
AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;


-- ingested_at 语义是"第一次 ingest 时间"——UPSERT 时不应被覆盖。
-- 客户端 (sync_feishu_notes) 每次 UPSERT 都会带 ingested_at = NOW()，
-- 这个 BEFORE UPDATE trigger 强制还原成 OLD 值，让 schema 语义独立于
-- 客户端实现。新插入时 trigger 不触发，DEFAULT NOW() 正常生效。
CREATE OR REPLACE FUNCTION truth_vault.preserve_ingested_at() RETURNS TRIGGER
    LANGUAGE plpgsql
    SET search_path = ''
AS $$
BEGIN
    IF OLD.ingested_at IS NOT NULL THEN
        NEW.ingested_at := OLD.ingested_at;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS tv_notes_preserve_ingested_at ON truth_vault.notes;
CREATE TRIGGER tv_notes_preserve_ingested_at
BEFORE UPDATE ON truth_vault.notes
FOR EACH ROW EXECUTE FUNCTION truth_vault.preserve_ingested_at();

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
-- last_baokuan_sync_to_{ssll,aw}_at 改用 MAX() 动态计算 (从 notes 行级 timestamp 聚合)
-- 不再依赖 projects 表的冗余缓存列 (那两列从来没被任何 sync 脚本更新).
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
    -- 最近一次爆款 sync 时间 (从 notes 行级聚合)
    MAX(n.synced_to_ssll_at) FILTER (WHERE n.tier IN ('爆', '大爆')) AS last_baokuan_sync_to_ssll_at,
    MAX(n.synced_to_aw_at)   FILTER (WHERE n.tier IN ('爆', '大爆')) AS last_baokuan_sync_to_aw_at
FROM truth_vault.projects p
LEFT JOIN truth_vault.notes n ON p.project_id = n.project_id
GROUP BY p.project_id, p.brand;


-- ── autowriter 注入候选 + 评分 (D-036) ──
-- 通道 2 sync 的 single source of truth: 哪条 baokuan 进 autowriter.items
-- 由本 view 决定. sync 脚本读这个 view, 取 injection_score DESC, 加 Python
-- 端的 diversity 后再写 autowriter.items.
--
-- 设计原则:
--   - 全部用 TV 已经标过的字段做 weighted sum, 不引入新维度也不引入模型
--   - 想调权重就改本 view, 不需要碰 sync 脚本
--   - 想增删 eligibility filter 也是改本 view, 改完整个 pipeline 一致
--
-- Eligibility:
--   - tier ∈ ('爆','大爆')                             仅同步爆款
--   - tier_source != '数值推断'                         排除未人工 confirm 的自动 tier
--                                                       (运营要把某条数值推断的 row 重新
--                                                        纳入候选, 改 tier_source 为
--                                                        '人工补录' 即可: UPDATE notes
--                                                        SET tier_source='人工补录'
--                                                        WHERE note_id=...)
--   - publish_time within 12 months                     不持续注入过气审美 / 半衰期约束
--   - projects.mapping_to_autowriter_project_id NOT NULL  必须有 aw 项目映射
--
-- Score 组成 (各项独立可调):
--   recency_weight       近期权重 (12 月内线性衰减, 范围 [0, 1])
--   tier_weight          大爆 +0.5 / 爆 +0.3
--   tier_source_weight   人工标 +0.2 / 数值推断 0
--   account_weight       账号历史爆率 * 0.3 (无账号映射时回退 0.3 中性)
-- 满分约 2.0 / 中位 0.5-0.8 / 强候选 1.0+
CREATE OR REPLACE VIEW truth_vault.v_autowriter_injection_candidates AS
WITH eligible AS (
  SELECT
    n.note_id, n.project_id,
    n.raw_content, n.hit_blue_keywords, n.tier, n.tier_source,
    n.emotional_lever, n.target_audience, n.publish_time,
    n.account_id, n.synced_to_aw_at,
    p.brand, p.category,
    p.mapping_to_autowriter_project_id,
    -- recency: TIMESTAMP 列按 naive UTC 处理 (项目惯例), 转成 epoch 秒后归一化
    GREATEST(
        0::FLOAT,
        1.0 - EXTRACT(EPOCH FROM (NOW()::TIMESTAMP - n.publish_time)) / (86400.0 * 365.0)
    ) AS recency_weight
  FROM truth_vault.notes n
  JOIN truth_vault.projects p ON p.project_id = n.project_id
  WHERE n.tier IN ('爆','大爆')
    AND n.tier_source IS DISTINCT FROM '数值推断'
    AND n.publish_time IS NOT NULL
    AND n.publish_time > (NOW() - INTERVAL '12 months')::TIMESTAMP
    AND p.mapping_to_autowriter_project_id IS NOT NULL
)
SELECT
  e.note_id, e.project_id, e.raw_content, e.hit_blue_keywords,
  e.tier, e.tier_source, e.emotional_lever, e.target_audience,
  e.publish_time, e.synced_to_aw_at, e.account_id,
  e.brand, e.category, e.mapping_to_autowriter_project_id,
  e.recency_weight,
  COALESCE(a.personal_bao_rate, 0.3) AS account_bao_rate,
  (
    e.recency_weight
    + CASE e.tier WHEN '大爆' THEN 0.5 WHEN '爆' THEN 0.3 ELSE 0 END
    + CASE e.tier_source
        WHEN '状态字段' THEN 0.2
        WHEN '备注字段' THEN 0.2
        WHEN '人工补录' THEN 0.2
        ELSE 0
      END
    + COALESCE(a.personal_bao_rate, 0.3) * 0.3
  ) AS injection_score
FROM eligible e
LEFT JOIN truth_vault.v_top_performing_accounts a ON a.account_id = e.account_id;


-- ════════════════════════════════════════════════════════════════════
-- GRANT + RLS · service_role 全权, anon/authenticated 默认 deny
-- ════════════════════════════════════════════════════════════════════
--
-- TV 是内部数据基础设施, 所有访问应该走 service_role (sync 脚本 /
-- 后台 job / admin 工具). anon 和 authenticated 永远不应该直接读 TV.
--
-- 设计:
--   - service_role: USAGE on schema + ALL on tables/sequences. 因为
--     service_role.rolbypassrls=true, RLS 开关对它无影响.
--   - anon + authenticated: 没 USAGE, 没 grant, RLS 再做兜底.
--     三重 deny: 进不来 schema → 进得来也读不了表 → 读得到也被 RLS 挡.
--   - ALTER DEFAULT PRIVILEGES: 未来在 truth_vault 里新建表会自动
--     继承 service_role 的 grant, 不需要每次手动补.
--   - 14 张表 ENABLE RLS 不加 policy = "deny all" for non-bypass roles.
--     未来如果要做 "内部用户登录后查 TV 数据" 的功能, 再单独加 policy.
--
-- 跨 schema views (notes_v1_2_cross_schema_views.sql 里那些) 跟 PG view
-- 一致: view 用 caller 权限 + view 定义者 (或 SECURITY DEFINER) 决定底层
-- 表访问. 默认 SECURITY INVOKER, 所以 service_role caller 透传 BYPASSRLS,
-- anon caller 被挡. 跟原设计一致.

-- service_role 用本 schema 的能力
-- 包在 DO + IF EXISTS 里: Supabase 上 service_role 必有, 裸 Postgres (CI /
-- 自托管 PG) 没有这个角色, 直接 GRANT 会 ERROR role does not exist.
-- 跟 autowriter-migrations/001 / 007 同样模式.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA truth_vault TO service_role';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA truth_vault TO service_role';
        EXECUTE 'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA truth_vault TO service_role';
        -- 未来在 truth_vault 里新建的表/序列自动继承 service_role 权限
        EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA truth_vault GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO service_role';
        EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA truth_vault GRANT USAGE, SELECT ON SEQUENCES TO service_role';
    END IF;
END $$;

-- 14 张表 ENABLE RLS (不加 policy = 对 anon/authenticated 默认 deny;
-- service_role rolbypassrls=true 不受影响)
ALTER TABLE truth_vault.projects                     ENABLE ROW LEVEL SECURITY;
ALTER TABLE truth_vault.accounts                     ENABLE ROW LEVEL SECURITY;
ALTER TABLE truth_vault.account_snapshots            ENABLE ROW LEVEL SECURITY;
ALTER TABLE truth_vault.notes                        ENABLE ROW LEVEL SECURITY;
ALTER TABLE truth_vault.metric_snapshots             ENABLE ROW LEVEL SECURITY;
ALTER TABLE truth_vault.posthoc_analyses             ENABLE ROW LEVEL SECURITY;
ALTER TABLE truth_vault.prepublish_evaluations       ENABLE ROW LEVEL SECURITY;
ALTER TABLE truth_vault.quality_review_decisions     ENABLE ROW LEVEL SECURITY;
ALTER TABLE truth_vault.comments                     ENABLE ROW LEVEL SECURITY;
ALTER TABLE truth_vault.notes_archive                ENABLE ROW LEVEL SECURITY;
ALTER TABLE truth_vault.audience_calibrations        ENABLE ROW LEVEL SECURITY;
ALTER TABLE truth_vault.undeclared_fields_quarantine ENABLE ROW LEVEL SECURITY;
ALTER TABLE truth_vault.note_features                ENABLE ROW LEVEL SECURITY;
ALTER TABLE truth_vault.audit_log                    ENABLE ROW LEVEL SECURITY;


-- ════════════════════════════════════════════════════════════════════
-- 完成
-- ════════════════════════════════════════════════════════════════════
--
-- 部署步骤（D-029 顺序）：
-- 1. 执行本文件（notes_v1_2.sql）—— 创建 truth_vault schema + 所有表 + 内部 views
--    + GRANT to service_role + ENABLE RLS
-- 2. sanshengliubu 在 public schema 部署（已有，不动）
-- 3. autowriter 迁移到 autowriter schema（避免 public.projects 冲突）
-- 4. 三个 schema 就绪后，执行 notes_v1_2_cross_schema_views.sql
-- 5. 在 Supabase Dashboard → Settings → API → Exposed schemas 把
--    truth_vault 加进去 (PostgREST 才会注册这个 schema, 否则 sync 脚本
--    用 Accept-Profile: truth_vault 报 406 Not Acceptable)
-- 6. 运行 sync 脚本（详见 docs/09-system-integration.md）
