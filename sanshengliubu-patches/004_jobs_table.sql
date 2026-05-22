-- ════════════════════════════════════════════════════════════════════
-- sanshengliubu-patches/004_jobs_table.sql
-- ════════════════════════════════════════════════════════════════════
--
-- 2026-05-22 audit R-018 修复 · 用持久 jobs 表替代 pipeline orchestrator 的
-- daemon thread
--
-- 背景:
--   sanshengliubu/pipeline/orchestrator.py:3621 用
--   threading.Thread(daemon=True) 跑 pipeline run (多阶段 LLM 流水线).
--   Streamlit 重启 / 容器 rolling restart / OOM 时 thread 直接死,
--   pipeline_runs.status 留在 'running', 用户没办法恢复或继续.
--
-- 解决路线: 同 autowriter R-018 (见 autowriter-migrations/008_jobs_table.sql).
--   Streamlit UI insert job; worker process 领 + 心跳 + 完成; sweeper 收死 job.
--
-- 这个 patch 写 sanshengliubu 这边的 jobs 表. AutoWriter 那边走另一份
-- migration. 两边 schema 99% 一样, 只差 kind 注释 (sanshengliubu 是 pipeline /
-- stage 而非 generate_batch).
--
-- 详细 worker 进程设计 见 truth-vault/docs/10-sister-repo-followups.md § "R-018".
--
-- 前置:
--   sanshengliubu 的 public schema 必须存在 (sanshengliubu/db/schema.sql 已跑).
--   pgcrypto 或 PG 16+ 必须 (用 gen_random_uuid).
--
-- 部署:
--   psql -d <sanshengliubu_db> -f 004_jobs_table.sql
--   或 Supabase SQL Editor 粘贴执行.
--
-- 幂等: 重复执行不报错.
--
-- 与 R-019 (多租户 RLS) 的关系:
--   - 走单租户: 本 patch 的 jobs RLS 用 user_id = auth.uid(), 没问题
--   - 走多租户 (005_multi_tenant_workspaces.sql): 跑 005 之前先跑 004,
--     之后 005 会给 jobs 表加 workspace_id 列和 workspace-scoped policy
-- ════════════════════════════════════════════════════════════════════

BEGIN;

-- ── 1. jobs 表 ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- handler 选择.
    --   'pipeline_run'      — 现 orchestrator._thread_target 包的整流水线
    --   'stage_rerun'       — 单 stage 重跑 (用户在 pipeline_detail 页选)
    --   'evidence_refresh'  — reference_samples 从外部源同步
    --   'noop'              — phase 1 烟雾测试
    kind TEXT NOT NULL,

    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    priority INTEGER NOT NULL DEFAULT 0,

    -- 状态机.
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN (
            'pending', 'claimed', 'running',
            'success', 'failed', 'timeout', 'cancelled'
        )),

    user_id UUID,
    project_id UUID,

    -- pipeline_run 专用关联: 让 orchestrator 的现有 UI 仍能按 pipeline_run_id
    -- 查到对应 job 状态. payload 里也存了一份, 这里冗余成顶级列是为了 index.
    pipeline_run_id UUID,

    claimed_by TEXT,
    claimed_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,

    progress_pct INTEGER NOT NULL DEFAULT 0
        CHECK (progress_pct BETWEEN 0 AND 100),
    progress_message TEXT,
    -- 流水线特有: 当前在哪个 stage (stage_logs.stage_name 之一). 让 UI 比单
    -- progress_pct 更清楚定位.
    current_stage TEXT,

    result JSONB,
    error_text TEXT,

    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    next_retry_at TIMESTAMPTZ,

    -- pipeline 一般要 30-60 分钟, 比 autowriter 的单版本生成长. 上限 2 小时.
    max_runtime_seconds INTEGER NOT NULL DEFAULT 7200,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.jobs IS
'2026-05-22 audit R-018: persistent job queue replacing pipeline orchestrator '
'daemon thread. Streamlit UI inserts; worker process(es) claim + execute + '
'heartbeat. See truth-vault docs/10-sister-repo-followups.md for worker design.';


-- ── 2. 索引 ──────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_jobs_pending_queue
    ON public.jobs (priority DESC, created_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_jobs_user_recent
    ON public.jobs (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_jobs_project_recent
    ON public.jobs (project_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_jobs_heartbeat_sweep
    ON public.jobs (heartbeat_at)
    WHERE status IN ('claimed', 'running');

-- pipeline_runs 详情页按 run_id 反查 job
CREATE INDEX IF NOT EXISTS idx_jobs_pipeline_run
    ON public.jobs (pipeline_run_id)
    WHERE pipeline_run_id IS NOT NULL;


-- ── 3. updated_at trigger ────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public._jobs_touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS jobs_touch_updated_at ON public.jobs;
CREATE TRIGGER jobs_touch_updated_at
    BEFORE UPDATE ON public.jobs
    FOR EACH ROW
    EXECUTE FUNCTION public._jobs_touch_updated_at();


-- ── 4. 原子领取 RPC ──────────────────────────────────────────────────
-- 见 autowriter-migrations/008_jobs_table.sql 同名函数的注释.
CREATE OR REPLACE FUNCTION public.claim_one_job(
    _worker_id TEXT,
    _kinds TEXT[] DEFAULT NULL
)
RETURNS SETOF public.jobs AS $$
DECLARE
    claimed_id UUID;
BEGIN
    SELECT id INTO claimed_id
    FROM public.jobs
    WHERE status = 'pending'
      AND (next_retry_at IS NULL OR next_retry_at < now())
      AND (_kinds IS NULL OR kind = ANY(_kinds))
    ORDER BY priority DESC, created_at
    LIMIT 1
    FOR UPDATE SKIP LOCKED;

    IF claimed_id IS NULL THEN
        RETURN;
    END IF;

    RETURN QUERY
    UPDATE public.jobs
    SET status = 'running',
        claimed_by = _worker_id,
        claimed_at = now(),
        heartbeat_at = now(),
        started_at = now(),
        attempts = attempts + 1
    WHERE id = claimed_id
    RETURNING *;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;


-- ── 4b. claim_one_job 权限收紧 (2026-05-22 audit P1) ────────────────
-- PG 函数默认对 PUBLIC 开放 EXECUTE. 这个函数是 SECURITY DEFINER 且会写
-- jobs 表 (status / claimed_by / attempts), 不加约束的话任何能 hit RPC 的
-- 角色 (anon / authenticated) 都能 claim 别人的 job, 破坏队列完整性.
-- worker 应该用 service_role key 调用, 这里 REVOKE PUBLIC + 仅 GRANT service_role.
REVOKE EXECUTE ON FUNCTION public.claim_one_job(TEXT, TEXT[]) FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        EXECUTE 'GRANT EXECUTE ON FUNCTION public.claim_one_job(TEXT, TEXT[]) TO service_role';
    END IF;
END $$;


-- ── 5. RLS ───────────────────────────────────────────────────────────
-- 单租户场景: 用户能看到所有 jobs (sanshengliubu 现 schema 5 张主表都没 RLS,
-- jobs 跟着走单租户假设, RLS enable 但 policy 放宽). 多租户场景: 跑
-- 005_multi_tenant_workspaces.sql 后会被替换成 workspace-scoped policy.
--
-- 2026-05-22 audit P2: 旧的 jobs_owner_or_anon (FOR ALL) 让 authenticated 角色
-- 能 UPDATE/DELETE 任意 job (含别人的), 在多用户单租户部署里可被互相 cancel.
-- 拆成: SELECT 给所有 authenticated (保留"团队都能看"的单租户语义),
-- INSERT/UPDATE/DELETE 仅限自己的行 (user_id = auth.uid()).
-- service_role 仍绕 RLS (worker 进程用).
ALTER TABLE public.jobs ENABLE ROW LEVEL SECURITY;

-- 清掉旧 policy (老 P2 版本) 和新 policy (本 patch 重跑时)
DROP POLICY IF EXISTS jobs_owner_or_anon ON public.jobs;
DROP POLICY IF EXISTS jobs_select_team   ON public.jobs;
DROP POLICY IF EXISTS jobs_insert_owner  ON public.jobs;
DROP POLICY IF EXISTS jobs_update_owner  ON public.jobs;
DROP POLICY IF EXISTS jobs_delete_owner  ON public.jobs;

-- 读: 单租户假设保留 "所有 authenticated 都能看", anon/历史行 (user_id NULL)
-- 也放过. service_role 绕 RLS 不走这里.
CREATE POLICY jobs_select_team ON public.jobs
    FOR SELECT
    USING (
        user_id IS NULL OR user_id = auth.uid()
        OR auth.role() = 'authenticated'
    );

-- 写: 只能动自己的 job. NEW row 必须挂自己 user_id; OLD row 必须是自己的.
CREATE POLICY jobs_insert_owner ON public.jobs
    FOR INSERT
    WITH CHECK (user_id = auth.uid());

CREATE POLICY jobs_update_owner ON public.jobs
    FOR UPDATE
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

CREATE POLICY jobs_delete_owner ON public.jobs
    FOR DELETE
    USING (user_id = auth.uid());


-- ── 6. 校验 ──────────────────────────────────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'jobs'
    ) THEN
        RAISE EXCEPTION '004 migration failed: public.jobs not present';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = 'public' AND p.proname = 'claim_one_job'
    ) THEN
        RAISE EXCEPTION '004 migration failed: claim_one_job() not present';
    END IF;
    RAISE NOTICE 'sanshengliubu-patches/004 OK: jobs table + claim RPC + RLS in place';
END $$;

COMMIT;
