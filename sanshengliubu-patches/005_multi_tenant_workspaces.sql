-- ════════════════════════════════════════════════════════════════════
-- sanshengliubu-patches/005_multi_tenant_workspaces.sql
-- ════════════════════════════════════════════════════════════════════
--
-- 2026-05-22 audit R-019 (Option B) · 多租户 workspaces + RLS
--
-- ⚠️ 仅在你确认要走多租户路线时跑. 单租户 MVP 不需要这个, 见
-- sanshengliubu-patches/README.md "R-019 单租户假设声明" 选项.
--
-- 背景:
--   sanshengliubu/db/schema.sql 显式 ALTER TABLE ... DISABLE ROW LEVEL SECURITY
--   对 5 张主表 (projects / pipeline_runs / stage_logs / outputs /
--   reference_samples). 单租户 MVP 没问题, 但多客户/多品牌共用同一个 Supabase
--   时所有数据跨 workspace 互可见.
--
-- 本 patch 做什么:
--   1. 加 workspaces + workspace_users 两张新表
--   2. 给 5 张主表 (+ 004 加的 jobs) 加 workspace_id 列
--   3. 把现有行 backfill 到 'default' workspace
--   4. SET NOT NULL
--   5. ENABLE ROW LEVEL SECURITY, 给 workspace-member-only policy
--
-- TV 通道 1 sync 不受影响: 它用 service_role key, 绕 RLS. 但 sync 脚本写
-- reference_samples 时需要 set workspace_id; 改动见
-- truth-vault/docs/10-sister-repo-followups.md § "R-019 Option B 代码改造".
--
-- 不可轻易回滚: 跑完之后回到无 RLS 需要手工 DISABLE ROW LEVEL SECURITY +
-- DROP COLUMN workspace_id; 中间窗口前端会读不到数据. 在 staging 跑过、
-- 确认前端登录链路兼容、确认 workspace_users 至少有一行映射用户 → 默认 workspace
-- 之后再上生产.
--
-- 前置:
--   - sanshengliubu-patches/001_add_source_tv_note_id.sql 已跑
--   - sanshengliubu-patches/003_strengthen_tv_note_id_unique.sql 已跑
--   - sanshengliubu-patches/004_jobs_table.sql 已跑 (本 patch 也给 jobs 加 RLS)
--   - sanshengliubu 自己的 db/schema.sql 已 baseline
--
-- 部署:
--   psql -d <sanshengliubu_db> -f 005_multi_tenant_workspaces.sql
--
-- 幂等: 重复执行不报错; 但 backfill UPDATE 在第二次跑时是 0 行 (因为 NOT NULL
-- 已生效, 没有 workspace_id IS NULL 的行).
-- ════════════════════════════════════════════════════════════════════

BEGIN;

-- ── 1. workspaces + workspace_users ─────────────────────────────────
CREATE TABLE IF NOT EXISTS public.workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    -- 业务字段示例: 客户公司名、品牌簇、所属销售. 按需扩展.
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at TIMESTAMPTZ   -- 软删除; NULL = active
);

CREATE TABLE IF NOT EXISTS public.workspace_users (
    workspace_id UUID NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    role TEXT NOT NULL DEFAULT 'member'
        CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
    invited_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    invited_by UUID,
    PRIMARY KEY (workspace_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_workspace_users_user
    ON public.workspace_users (user_id);


-- ── 2. 默认 workspace (backfill 用) ─────────────────────────────────
INSERT INTO public.workspaces (id, name, description)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'default',
    'Auto-created by 005 migration for backfill of pre-existing rows.'
)
ON CONFLICT (id) DO NOTHING;

-- ⚠️ 你必须手工把当前所有用户加进默认 workspace, 否则 RLS 一打开他们就读不到
-- 数据! 跑完本 patch 后立即跑 (按你实际 user_id 替换):
--
--   INSERT INTO public.workspace_users (workspace_id, user_id, role)
--   SELECT '00000000-0000-0000-0000-000000000001', id, 'owner'
--   FROM auth.users
--   ON CONFLICT DO NOTHING;
--
-- 上面这条不放在 migration 里跑是因为 auth.users 在不同 Supabase project 上
-- 状态差很多, 要看你实际有几个用户. 操作完之后用下面的 verify SQL 核.


-- ── 3. 给所有需要 scope 的表加 workspace_id 列 ──────────────────────
ALTER TABLE public.projects
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES public.workspaces(id);
ALTER TABLE public.pipeline_runs
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES public.workspaces(id);
ALTER TABLE public.stage_logs
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES public.workspaces(id);
ALTER TABLE public.outputs
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES public.workspaces(id);
ALTER TABLE public.reference_samples
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES public.workspaces(id);
ALTER TABLE public.jobs
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES public.workspaces(id);


-- ── 4. backfill 到默认 workspace ─────────────────────────────────────
UPDATE public.projects
    SET workspace_id = '00000000-0000-0000-0000-000000000001'
    WHERE workspace_id IS NULL;
UPDATE public.pipeline_runs
    SET workspace_id = '00000000-0000-0000-0000-000000000001'
    WHERE workspace_id IS NULL;
UPDATE public.stage_logs
    SET workspace_id = '00000000-0000-0000-0000-000000000001'
    WHERE workspace_id IS NULL;
UPDATE public.outputs
    SET workspace_id = '00000000-0000-0000-0000-000000000001'
    WHERE workspace_id IS NULL;
UPDATE public.reference_samples
    SET workspace_id = '00000000-0000-0000-0000-000000000001'
    WHERE workspace_id IS NULL;
UPDATE public.jobs
    SET workspace_id = '00000000-0000-0000-0000-000000000001'
    WHERE workspace_id IS NULL;


-- ── 5. SET NOT NULL (拒绝以后不带 workspace_id 的 INSERT) ───────────
ALTER TABLE public.projects          ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE public.pipeline_runs     ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE public.stage_logs        ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE public.outputs           ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE public.reference_samples ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE public.jobs              ALTER COLUMN workspace_id SET NOT NULL;


-- ── 6. RLS index (policy 用 IN (subquery) 走这个) ───────────────────
CREATE INDEX IF NOT EXISTS idx_projects_workspace
    ON public.projects (workspace_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_workspace
    ON public.pipeline_runs (workspace_id);
CREATE INDEX IF NOT EXISTS idx_stage_logs_workspace
    ON public.stage_logs (workspace_id);
CREATE INDEX IF NOT EXISTS idx_outputs_workspace
    ON public.outputs (workspace_id);
CREATE INDEX IF NOT EXISTS idx_reference_samples_workspace
    ON public.reference_samples (workspace_id);
CREATE INDEX IF NOT EXISTS idx_jobs_workspace
    ON public.jobs (workspace_id);


-- ── 7. helper function: current_workspace_ids() ─────────────────────
-- 让 RLS policy 写起来短. STABLE 让 PG planner 可以 cache 函数结果在
-- 单 query 内的多次调用 (RLS policy 每行求值一次, 这个 cache 重要).
CREATE OR REPLACE FUNCTION public.current_workspace_ids()
RETURNS SETOF UUID AS $$
    SELECT workspace_id FROM public.workspace_users WHERE user_id = auth.uid()
$$ LANGUAGE SQL STABLE SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION public.current_workspace_ids() TO authenticated;


-- ── 8. ENABLE RLS + policy ──────────────────────────────────────────
-- 先把 schema.sql 里的 DISABLE 推翻
ALTER TABLE public.projects          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pipeline_runs     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stage_logs        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.outputs           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reference_samples ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.workspaces        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workspace_users   ENABLE ROW LEVEL SECURITY;

-- 主表 policy: 你是该 workspace 的 member 才能 SELECT/INSERT/UPDATE/DELETE
DROP POLICY IF EXISTS projects_workspace_member ON public.projects;
CREATE POLICY projects_workspace_member ON public.projects
    FOR ALL TO authenticated
    USING (workspace_id IN (SELECT public.current_workspace_ids()))
    WITH CHECK (workspace_id IN (SELECT public.current_workspace_ids()));

DROP POLICY IF EXISTS pipeline_runs_workspace_member ON public.pipeline_runs;
CREATE POLICY pipeline_runs_workspace_member ON public.pipeline_runs
    FOR ALL TO authenticated
    USING (workspace_id IN (SELECT public.current_workspace_ids()))
    WITH CHECK (workspace_id IN (SELECT public.current_workspace_ids()));

DROP POLICY IF EXISTS stage_logs_workspace_member ON public.stage_logs;
CREATE POLICY stage_logs_workspace_member ON public.stage_logs
    FOR ALL TO authenticated
    USING (workspace_id IN (SELECT public.current_workspace_ids()))
    WITH CHECK (workspace_id IN (SELECT public.current_workspace_ids()));

DROP POLICY IF EXISTS outputs_workspace_member ON public.outputs;
CREATE POLICY outputs_workspace_member ON public.outputs
    FOR ALL TO authenticated
    USING (workspace_id IN (SELECT public.current_workspace_ids()))
    WITH CHECK (workspace_id IN (SELECT public.current_workspace_ids()));

DROP POLICY IF EXISTS reference_samples_workspace_member ON public.reference_samples;
CREATE POLICY reference_samples_workspace_member ON public.reference_samples
    FOR ALL TO authenticated
    USING (workspace_id IN (SELECT public.current_workspace_ids()))
    WITH CHECK (workspace_id IN (SELECT public.current_workspace_ids()));

-- jobs 把 004 那条 owner_or_anon policy 替换成 workspace-scoped
DROP POLICY IF EXISTS jobs_owner_or_anon ON public.jobs;
DROP POLICY IF EXISTS jobs_workspace_member ON public.jobs;
CREATE POLICY jobs_workspace_member ON public.jobs
    FOR ALL TO authenticated
    USING (workspace_id IN (SELECT public.current_workspace_ids()))
    WITH CHECK (workspace_id IN (SELECT public.current_workspace_ids()));

-- workspaces 表 policy: 你是该 workspace 的 member 才能看见这个 workspace
DROP POLICY IF EXISTS workspaces_member ON public.workspaces;
CREATE POLICY workspaces_member ON public.workspaces
    FOR ALL TO authenticated
    USING (id IN (SELECT public.current_workspace_ids()));

-- workspace_users 表 policy: 你只能看到自己所在 workspace 的成员关系
DROP POLICY IF EXISTS workspace_users_self ON public.workspace_users;
CREATE POLICY workspace_users_self ON public.workspace_users
    FOR ALL TO authenticated
    USING (workspace_id IN (SELECT public.current_workspace_ids()));


-- ── 9. 校验 ──────────────────────────────────────────────────────────
DO $$
DECLARE
    rls_off_count INT;
    null_ws_count INT;
BEGIN
    -- 9.1 所有 6 张主表 RLS 必须开
    SELECT COUNT(*) INTO rls_off_count
    FROM pg_class c
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE n.nspname = 'public'
      AND c.relname IN ('projects','pipeline_runs','stage_logs',
                        'outputs','reference_samples','jobs')
      AND c.relrowsecurity = false;
    IF rls_off_count > 0 THEN
        RAISE EXCEPTION
            '005 migration failed: % main tables still have RLS disabled',
            rls_off_count;
    END IF;

    -- 9.2 backfill 必须完整
    SELECT COUNT(*) INTO null_ws_count
    FROM public.projects WHERE workspace_id IS NULL;
    IF null_ws_count > 0 THEN
        RAISE EXCEPTION '005 migration failed: projects.workspace_id NULL count=%', null_ws_count;
    END IF;

    -- 9.3 默认 workspace 必须存在 (后面要往里加用户)
    IF NOT EXISTS (SELECT 1 FROM public.workspaces
                   WHERE id = '00000000-0000-0000-0000-000000000001') THEN
        RAISE EXCEPTION '005 migration failed: default workspace missing';
    END IF;

    RAISE NOTICE 'sanshengliubu-patches/005 OK: multi-tenant RLS enabled. '
                 'IMPORTANT: now manually INSERT workspace_users rows for each '
                 'existing user; otherwise their JWT will see 0 rows.';
END $$;

COMMIT;
