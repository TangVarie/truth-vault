-- ════════════════════════════════════════════════════════════════════
-- autowriter-migrations/007_fresh_install_autowriter_schema.sql
-- ════════════════════════════════════════════════════════════════════
--
-- 场景 C · 在共享 Supabase 上从零创建 autowriter schema + 表
--
-- 跟 001 互补:
--   - 001 适用场景 A: autowriter 表已在 public schema → ALTER TABLE SET
--     SCHEMA 搬迁 (不重建表, 数据保留)
--   - 007 适用场景 C: 共享 Supabase 上从来没装过 autowriter → 现场 CREATE
--     TABLE / RLS / GRANT / RPC. 数据要么后续从老 Supabase 迁过来 (走
--     scripts/migrate_autowriter_data_across_supabase.py), 要么 fresh start
--
-- 内容来自 autowriter 仓库 db.py::CREATE_TABLES_SQL (2026-05-21 snapshot,
-- 已包含 TV 集成所需的 external_source / external_source_id /
-- example_label_proposal 列 + per-user unique index, 跑完 007 后无需再跑
-- 002/003). 后续 autowriter 仓库改 DDL 时, 同步更新本文件.
--
-- 部署:
--   psql -d <shared_supabase> -f 007_fresh_install_autowriter_schema.sql
-- 或 Supabase Dashboard → SQL Editor 粘贴执行.
--
-- 还需要在 Dashboard 操作:
--   Settings → API → Exposed schemas → 添加 'autowriter'
--   (PostgREST 才会暴露这些表给 autowriter app)
--
-- 幂等: 全部 IF NOT EXISTS / DROP+CREATE policy / OR REPLACE function.
-- 跑过 001/002/003 的环境再跑 007 也安全 (no-op + 自愈补缺).
-- ════════════════════════════════════════════════════════════════════

-- 1. Schema
CREATE SCHEMA IF NOT EXISTS autowriter;

-- 2. Schema USAGE grants (Supabase 3 角色)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA autowriter TO anon';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA autowriter TO authenticated';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA autowriter TO service_role';
    END IF;
END $$;

-- 3. 必需扩展
--   Supabase 把扩展函数装在独立的 `extensions` schema, 所以下面 SET LOCAL
--   search_path 必须把 extensions 包进去, 否则 uuid_generate_v4() / vector()
--   会报 42883 function does not exist.
CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;

-- ── 切到 autowriter schema 执行后面所有 CREATE TABLE / INDEX / POLICY ──
-- SET LOCAL: 仅在当前 transaction/migration block 内生效, 不污染会话.
-- extensions: 让 uuid_generate_v4() / vector(768) 这些函数/类型可以无前缀使用.
SET LOCAL search_path TO autowriter, public, extensions, pg_catalog;


-- ════════════════════════════════════════════════════════════════════
-- Tables (uses unqualified names; search_path 引导到 autowriter)
-- ════════════════════════════════════════════════════════════════════

-- Projects
CREATE TABLE IF NOT EXISTS projects (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name         TEXT NOT NULL,
    brand        TEXT,
    system_prompt TEXT,
    system_prompt_tone TEXT,
    system_prompt_exec TEXT,
    tactics      JSONB DEFAULT '[]'::jsonb,
    reference_files JSONB DEFAULT '[]'::jsonb,
    default_params  JSONB DEFAULT '{}'::jsonb,
    owner_id     UUID NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS projects_owner ON projects;
CREATE POLICY projects_owner ON projects
    USING (owner_id = auth.uid());
ALTER TABLE projects ADD COLUMN IF NOT EXISTS system_prompt_tone TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS system_prompt_exec TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS calibration_notes TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS custom_roles JSONB DEFAULT '[]'::jsonb;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS
    semantic_dedup_threshold REAL NULL
    CHECK (semantic_dedup_threshold IS NULL
           OR (semantic_dedup_threshold >= 0.80 AND semantic_dedup_threshold <= 0.99));
ALTER TABLE projects ADD COLUMN IF NOT EXISTS
    queue_strategy TEXT NULL
    CHECK (queue_strategy IS NULL OR queue_strategy IN ('stable','throughput'));

-- Batches
CREATE TABLE IF NOT EXISTS batches (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id     UUID REFERENCES projects(id) ON DELETE CASCADE,
    tactic         TEXT,
    params         JSONB DEFAULT '{}'::jsonb,
    ai_engines     JSONB DEFAULT '["claude"]'::jsonb,
    user_id        UUID NOT NULL,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE batches
    ADD COLUMN IF NOT EXISTS auto_calibrated_at TIMESTAMPTZ NULL;
ALTER TABLE batches ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS batches_owner ON batches;
CREATE POLICY batches_owner ON batches
    USING (user_id = auth.uid());

-- Items
CREATE TABLE IF NOT EXISTS items (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    batch_id        UUID REFERENCES batches(id) ON DELETE CASCADE,
    status          TEXT DEFAULT 'pending' CHECK (status IN ('pending','approved','needs_revision')),
    best_version_id UUID,
    user_id         UUID NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE items ADD COLUMN IF NOT EXISTS ai_review_notes TEXT;
ALTER TABLE items ADD COLUMN IF NOT EXISTS feedback_draft TEXT;
ALTER TABLE items ADD COLUMN IF NOT EXISTS manual_edit_draft JSONB;
ALTER TABLE items ADD COLUMN IF NOT EXISTS example_label TEXT
    CHECK (example_label IN ('positive', 'negative'));
ALTER TABLE items ADD COLUMN IF NOT EXISTS external_source TEXT;
ALTER TABLE items ADD COLUMN IF NOT EXISTS external_source_id TEXT;
ALTER TABLE items ADD COLUMN IF NOT EXISTS example_label_proposal TEXT
    CHECK (example_label_proposal IS NULL OR example_label_proposal IN (
        'negative_manual_rewrite',
        'negative_feedback_iter',
        'negative_batch_rejected'
    ));
DROP INDEX IF EXISTS items_external_source_uniq;
CREATE UNIQUE INDEX IF NOT EXISTS items_external_source_per_user_uniq
    ON items (user_id, external_source, external_source_id)
    WHERE external_source IS NOT NULL;
CREATE INDEX IF NOT EXISTS items_proposal_idx
    ON items (example_label_proposal)
    WHERE example_label_proposal IS NOT NULL;
ALTER TABLE items ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS items_owner ON items;
CREATE POLICY items_owner ON items
    USING (user_id = auth.uid());

-- Versions
CREATE TABLE IF NOT EXISTS versions (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    item_id     UUID REFERENCES items(id) ON DELETE CASCADE,
    version_num INTEGER NOT NULL DEFAULT 1,
    ai_engine   TEXT NOT NULL,
    title       TEXT,
    body        TEXT,
    keywords    JSONB DEFAULT '[]'::jsonb,
    feedback    TEXT,
    images      JSONB DEFAULT '[]'::jsonb,
    token_usage JSONB DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE versions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS versions_owner ON versions;
CREATE POLICY versions_owner ON versions
    USING (
        item_id IN (SELECT id FROM items WHERE user_id = auth.uid())
    );
ALTER TABLE versions ADD COLUMN IF NOT EXISTS embedding vector(768);
CREATE INDEX IF NOT EXISTS versions_embedding_idx
    ON versions USING ivfflat (embedding vector_cosine_ops);

-- Memories
CREATE TABLE IF NOT EXISTS memories (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    scope           TEXT NOT NULL CHECK (scope IN ('project','global')),
    project_id      UUID REFERENCES projects(id) ON DELETE CASCADE,
    content         TEXT NOT NULL,
    source_feedback TEXT,
    frequency       INTEGER DEFAULT 1,
    status          TEXT DEFAULT 'candidate' CHECK (status IN ('candidate','confirmed')),
    user_id         UUID NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE memories
    ADD COLUMN IF NOT EXISTS memory_type TEXT NOT NULL DEFAULT 'rule'
        CHECK (memory_type IN ('rule','note','session'));
ALTER TABLE memories
    ADD COLUMN IF NOT EXISTS source_batch_id UUID REFERENCES batches(id) ON DELETE SET NULL;
ALTER TABLE memories
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ NULL;
ALTER TABLE memories
    ADD COLUMN IF NOT EXISTS severity TEXT NOT NULL DEFAULT 'soft'
        CHECK (severity IN ('hard','soft'));
ALTER TABLE memories
    ADD COLUMN IF NOT EXISTS applicability TEXT NULL;
ALTER TABLE memories
    ADD COLUMN IF NOT EXISTS muted_until TIMESTAMPTZ NULL;
CREATE INDEX IF NOT EXISTS memories_session_idx
    ON memories(user_id, memory_type, expires_at)
    WHERE memory_type = 'session';
ALTER TABLE memories ADD COLUMN IF NOT EXISTS embedding vector(768);
ALTER TABLE memories ADD COLUMN IF NOT EXISTS
    rule_kind TEXT NULL
    CHECK (rule_kind IS NULL OR rule_kind IN
        ('forbidden_word','required_phrase','max_len','forbidden_regex','free_text'));
ALTER TABLE memories ADD COLUMN IF NOT EXISTS rule_payload JSONB NULL;
CREATE INDEX IF NOT EXISTS memories_rule_kind_idx
    ON memories(user_id, rule_kind) WHERE rule_kind IS NOT NULL;
ALTER TABLE memories ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS memories_owner ON memories;
CREATE POLICY memories_owner ON memories
    USING (user_id = auth.uid());

-- Calibration audit
CREATE TABLE IF NOT EXISTS calibration_note_audit (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id    UUID REFERENCES projects(id) ON DELETE CASCADE,
    source        TEXT,
    before_text   TEXT,
    append_lines  JSONB DEFAULT '[]'::jsonb,
    after_text    TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE calibration_note_audit ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS calibration_note_audit_owner ON calibration_note_audit;
CREATE POLICY calibration_note_audit_owner ON calibration_note_audit
    USING (
        project_id IN (SELECT id FROM projects WHERE owner_id = auth.uid())
    );
CREATE INDEX IF NOT EXISTS calibration_note_audit_project_idx
    ON calibration_note_audit(project_id, created_at DESC);

-- Batch metrics
CREATE TABLE IF NOT EXISTS batch_metrics (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    batch_id     UUID REFERENCES batches(id) ON DELETE CASCADE,
    project_id   UUID REFERENCES projects(id) ON DELETE CASCADE,
    user_id      UUID NOT NULL,
    phase_ms     JSONB DEFAULT '{}'::jsonb,
    counters     JSONB DEFAULT '{}'::jsonb,
    meta         JSONB DEFAULT '{}'::jsonb,
    injection    JSONB DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE batch_metrics ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS batch_metrics_owner ON batch_metrics;
CREATE POLICY batch_metrics_owner ON batch_metrics
    USING (user_id = auth.uid());
CREATE INDEX IF NOT EXISTS batch_metrics_project_idx
    ON batch_metrics(project_id, created_at DESC);

-- User logins (append-only audit)
CREATE TABLE IF NOT EXISTS user_logins (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL,
    ip          TEXT,
    user_agent  TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE user_logins ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS user_logins_owner ON user_logins;
DROP POLICY IF EXISTS user_logins_select_own ON user_logins;
DROP POLICY IF EXISTS user_logins_insert_own ON user_logins;
CREATE POLICY user_logins_select_own ON user_logins
    FOR SELECT USING (user_id = auth.uid());
CREATE POLICY user_logins_insert_own ON user_logins
    FOR INSERT WITH CHECK (user_id = auth.uid());
CREATE INDEX IF NOT EXISTS user_logins_user_idx
    ON user_logins(user_id, created_at DESC);


-- ════════════════════════════════════════════════════════════════════
-- Data API grants
-- ════════════════════════════════════════════════════════════════════
GRANT SELECT, INSERT, UPDATE, DELETE ON
    projects, batches, items, versions, memories,
    calibration_note_audit, batch_metrics
    TO authenticated;
GRANT SELECT, INSERT ON user_logins TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON
    projects, batches, items, versions, memories,
    calibration_note_audit, batch_metrics, user_logins
    TO service_role;


-- ════════════════════════════════════════════════════════════════════
-- RPC: batch_item_counts (server-side aggregation)
-- ════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION batch_item_counts(batch_ids UUID[])
RETURNS TABLE(
    batch_id        UUID,
    total           BIGINT,
    approved        BIGINT,
    pending         BIGINT,
    needs_revision  BIGINT
)
LANGUAGE sql
STABLE
SECURITY INVOKER
AS $$
    SELECT
        i.batch_id,
        COUNT(*)                                                AS total,
        COUNT(*) FILTER (WHERE i.status = 'approved')           AS approved,
        COUNT(*) FILTER (WHERE i.status = 'pending')            AS pending,
        COUNT(*) FILTER (WHERE i.status = 'needs_revision')     AS needs_revision
    FROM items i
    WHERE i.batch_id = ANY(batch_ids)
    GROUP BY i.batch_id;
$$;
GRANT EXECUTE ON FUNCTION batch_item_counts(UUID[]) TO authenticated, service_role;


-- ════════════════════════════════════════════════════════════════════
-- 校验: 跑完后 8 张表 + 关键索引 + RLS policy 都要在
-- ════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    expected_tables TEXT[] := ARRAY[
        'projects','batches','items','versions','memories',
        'calibration_note_audit','batch_metrics','user_logins'
    ];
    tbl TEXT;
    missing INT := 0;
BEGIN
    FOREACH tbl IN ARRAY expected_tables
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'autowriter' AND table_name = tbl
        ) THEN
            RAISE WARNING 'Missing autowriter.%', tbl;
            missing := missing + 1;
        END IF;
    END LOOP;
    IF missing > 0 THEN
        RAISE EXCEPTION '007 incomplete: % autowriter tables missing', missing;
    END IF;

    -- TV-integration 列必须在 (items)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='autowriter' AND table_name='items'
          AND column_name IN ('external_source','external_source_id',
                              'example_label','example_label_proposal')
        HAVING COUNT(*) = 4
    ) THEN
        RAISE EXCEPTION '007 incomplete: items 缺少 TV 集成列 (4 列必须齐)';
    END IF;

    -- per-user unique index 必须在
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE schemaname='autowriter'
          AND indexname='items_external_source_per_user_uniq'
    ) THEN
        RAISE EXCEPTION '007 incomplete: per-user unique index 未建';
    END IF;

    RAISE NOTICE '007 OK: autowriter schema + 8 tables + TV-integration columns 全部就位';
END $$;
