-- ════════════════════════════════════════════════════════════════════
-- autowriter-migrations/008_jobs_table.sql
-- ════════════════════════════════════════════════════════════════════
--
-- 2026-05-22 audit R-018 修复 · 用持久 jobs 表替代 daemon thread
--
-- 背景:
--   autowriter/app.py 现在用两条 daemon thread 跑后台任务:
--     - _queue_worker      (app.py:3007)  batch 生成
--     - _quick_gen_worker  (app.py:3318)  单版本快速生成
--   Streamlit 进程重启 / OOM kill / 容器滚动发布时这两条 thread 直接死.
--   autowriter.batches/items 上的状态停留在 running, UI 永远转圈, 用户看到
--   "偶发卡死". 长期运行时这种问题比普通 bug 更难排查.
--
-- 解决路线:
--   1. 任务状态写进 DB (本 migration 建 jobs 表)
--   2. Streamlit UI 只 INSERT job + 轮询状态展示
--   3. 独立 worker process (long-running Python) 领取 + 心跳 + 完成
--   4. dead-job sweeper 把 heartbeat 超时的 job 退回 pending 重试
--
-- 详细 worker 进程设计 / Streamlit 改造 / 部署形态 见
-- truth-vault/docs/10-sister-repo-followups.md § "R-018".
--
-- 部署:
--   psql -d <shared_supabase> -f 008_jobs_table.sql
--   或 Supabase SQL Editor 粘贴执行.
--
-- 幂等: 重复执行不报错. 列/索引/policy 都用 IF NOT EXISTS.
--
-- 回滚 (不推荐, 会丢所有 in-flight job 状态):
--   DROP TABLE IF EXISTS autowriter.jobs CASCADE;
--   DROP FUNCTION IF EXISTS autowriter.claim_one_job(TEXT);
--   DROP FUNCTION IF EXISTS autowriter._jobs_touch_updated_at();
-- ════════════════════════════════════════════════════════════════════

BEGIN;

-- ── 1. jobs 表 ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS autowriter.jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- handler 选择. 每个 worker 注册自己处理的 kind. 加新 kind 不需要重启
    -- 已有 worker (它们 SELECT WHERE kind IN (...) 自己关心的).
    --   'generate_batch'    — 现 _queue_worker 的批量生成
    --   'quick_gen'         — 现 _quick_gen_worker 的单版本生成
    --   'memory_refresh'    — memory_manager 后台刷新
    --   'extract_negative'  — 批量负样本候选抽取 (现在是手动跑的脚本)
    --   'noop'              — 烟雾测试用; phase 1 deploy 时 worker 先跑这个验证基础设施
    kind TEXT NOT NULL,

    -- handler 入参. 不在 DB 层 validate; handler 自己 schema check.
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- 队列优先级. 高 = 先服务. 负数留给后台任务 (yield 给用户实时操作).
    priority INTEGER NOT NULL DEFAULT 0,

    -- 工作流状态机. 状态迁移图 (见 docs/10):
    --   pending → claimed → running → success
    --                            ↘ → failed
    --                            ↘ → timeout (heartbeat sweeper 触发)
    --   pending → cancelled (用户从 UI 取消)
    --   timeout/failed → pending (attempts < max_attempts 时 sweeper 退回)
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN (
            'pending', 'claimed', 'running',
            'success', 'failed', 'timeout', 'cancelled'
        )),

    -- 所有权. user_id = 创建者 (Streamlit session user); project_id 冗余用于
    -- "我的项目下所有 jobs" 这种 UI 查询.
    user_id UUID,
    project_id UUID,

    -- worker 簿记. claimed_by 形如 "aw-worker-pod1-pid12345"; 用于排错时定位
    -- 是哪个 worker 卡住的.
    claimed_by TEXT,
    claimed_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,

    -- 进度. handler 在长任务里定期 UPDATE 这两列. UI 可以画 progress bar +
    -- 显示最新日志行. 不强制更新 — 短任务可以一次跳到 100.
    progress_pct INTEGER NOT NULL DEFAULT 0
        CHECK (progress_pct BETWEEN 0 AND 100),
    progress_message TEXT,

    -- 终态. result JSONB 是 handler 自定义成功输出 (batch_id, item_ids 之类
    -- UI 要展示的); error_text 是 Python traceback (失败时).
    result JSONB,
    error_text TEXT,

    -- 重试策略.
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    next_retry_at TIMESTAMPTZ,

    -- 超时. sweeper 把 (running OR claimed) 且 started_at + max_runtime_seconds
    -- < now() 的 job 转 timeout 状态.
    max_runtime_seconds INTEGER NOT NULL DEFAULT 1800,    -- 30 分钟默认

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE autowriter.jobs IS
'2026-05-22 audit R-018: persistent job queue replacing in-process daemon threads. '
'Streamlit UI inserts; worker process(es) claim + execute + heartbeat. '
'See truth-vault docs/10-sister-repo-followups.md for worker design.';


-- ── 2. 索引 ──────────────────────────────────────────────────────────
-- claim_one_job() 走的路径: WHERE status='pending' ORDER BY priority DESC, created_at
CREATE INDEX IF NOT EXISTS idx_jobs_pending_queue
    ON autowriter.jobs (priority DESC, created_at)
    WHERE status = 'pending';

-- "我的所有 jobs" UI 查询
CREATE INDEX IF NOT EXISTS idx_jobs_user_recent
    ON autowriter.jobs (user_id, created_at DESC);

-- "项目下所有 jobs" UI 查询
CREATE INDEX IF NOT EXISTS idx_jobs_project_recent
    ON autowriter.jobs (project_id, created_at DESC);

-- sweeper 路径: WHERE status IN (claimed, running) AND heartbeat_at < cutoff
CREATE INDEX IF NOT EXISTS idx_jobs_heartbeat_sweep
    ON autowriter.jobs (heartbeat_at)
    WHERE status IN ('claimed', 'running');


-- ── 3. updated_at 自动更新 trigger ──────────────────────────────────
CREATE OR REPLACE FUNCTION autowriter._jobs_touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS jobs_touch_updated_at ON autowriter.jobs;
CREATE TRIGGER jobs_touch_updated_at
    BEFORE UPDATE ON autowriter.jobs
    FOR EACH ROW
    EXECUTE FUNCTION autowriter._jobs_touch_updated_at();


-- ── 4. 原子领取 RPC ──────────────────────────────────────────────────
-- 为什么要 RPC: PostgREST 上 UPDATE ... ORDER BY LIMIT 1 RETURNING 不可
-- 直接用. 多 worker 并发跑时不能用 "SELECT id, 再 UPDATE WHERE id=X" 这种
-- 两步, 否则两个 worker 会拿到同一个 id (race window).
-- SELECT ... FOR UPDATE SKIP LOCKED 是标准做法: 一个事务里锁住一行,
-- 别的事务跳过这一行去找下一个. 配合 UPDATE 在同一事务里完成原子认领.
CREATE OR REPLACE FUNCTION autowriter.claim_one_job(
    _worker_id TEXT,
    _kinds TEXT[] DEFAULT NULL    -- NULL = 所有 kind; 传数组只领指定 kind
)
RETURNS SETOF autowriter.jobs AS $$
DECLARE
    claimed_id UUID;
BEGIN
    SELECT id INTO claimed_id
    FROM autowriter.jobs
    WHERE status = 'pending'
      AND (next_retry_at IS NULL OR next_retry_at < now())
      AND (_kinds IS NULL OR kind = ANY(_kinds))
    ORDER BY priority DESC, created_at
    LIMIT 1
    FOR UPDATE SKIP LOCKED;

    IF claimed_id IS NULL THEN
        RETURN;   -- 队列空, 返回 0 行
    END IF;

    RETURN QUERY
    UPDATE autowriter.jobs
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

COMMENT ON FUNCTION autowriter.claim_one_job(TEXT, TEXT[]) IS
'Atomically claim one pending job from the queue. SKIP LOCKED so concurrent '
'workers don''t collide. Returns 0 rows when queue empty. SECURITY DEFINER '
'so it can be called via PostgREST RPC by worker''s service_role JWT.';


-- ── 5. RLS policy ────────────────────────────────────────────────────
-- 用户只能看自己的 jobs. Worker 必须用 service_role key (绕 RLS).
ALTER TABLE autowriter.jobs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS jobs_owner ON autowriter.jobs;
CREATE POLICY jobs_owner ON autowriter.jobs
    FOR ALL
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());


-- ── 6. 校验 ──────────────────────────────────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'autowriter' AND table_name = 'jobs'
    ) THEN
        RAISE EXCEPTION '008 migration failed: autowriter.jobs not present';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = 'autowriter' AND p.proname = 'claim_one_job'
    ) THEN
        RAISE EXCEPTION '008 migration failed: claim_one_job() not present';
    END IF;
    RAISE NOTICE 'autowriter-migrations/008 OK: jobs table + claim RPC + RLS in place';
END $$;

COMMIT;
