-- ════════════════════════════════════════════════════════════════════
-- autowriter-migrations/001_create_autowriter_schema.sql
-- ════════════════════════════════════════════════════════════════════
--
-- 把 autowriter 5 张表从 public schema 迁到独立 autowriter schema
-- (D-024 共享 Supabase + schema 隔离). 这避免与 sanshengliubu 的
-- public.projects 命名冲突.
--
-- 表清单 (autowriter):
--   - projects, batches, items, versions, memories
--
-- 部署顺序:
--   1. 在共享 Supabase 实例上跑本文件 (CREATE SCHEMA + 迁移)
--   2. 跑 002_add_external_source.sql (P1 Sprint 1.1 idempotency key)
--   3. 跑 003_add_example_label_proposal.sql (P2 negative review queue)
--   4. autowriter codebase 把 get_client() 改成 ClientOptions(schema='autowriter')
--   5. 在 Supabase Dashboard → Settings → API → Exposed schemas 加
--      'autowriter' (PostgREST 才会暴露这些表)
--
-- 重要: 仅在场景 A (autowriter 仍在 public schema, 需要迁移) 跑此文件.
-- 场景 B (autowriter 已经在独立 schema) 跳过此文件, 从 002 开始.
-- 完整 RUNBOOK 见 docs/09-system-integration.md.
--
-- 幂等: 全部 IF NOT EXISTS / IF EXISTS, 重复执行安全.
-- ════════════════════════════════════════════════════════════════════

CREATE SCHEMA IF NOT EXISTS autowriter;

-- 迁移 5 张表 (假设它们当前在 public schema). 如果表不在 public 而是已经在
-- autowriter, ALTER TABLE SET SCHEMA 会报错 — 用 information_schema 兜底.
DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY['projects', 'batches', 'items', 'versions', 'memories']
    LOOP
        IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = tbl
        ) AND NOT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'autowriter' AND table_name = tbl
        ) THEN
            EXECUTE format('ALTER TABLE public.%I SET SCHEMA autowriter', tbl);
            RAISE NOTICE 'Moved public.% → autowriter.%', tbl, tbl;
        ELSE
            RAISE NOTICE 'Skip %: not in public or already in autowriter', tbl;
        END IF;
    END LOOP;
END $$;

-- uuid-ossp 用于 autowriter 表的 UUID 默认值 (生产 schema 已开)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ⚠️ Auth / RLS 提示:
--   autowriter 的 RLS policy 用 auth.uid() = owner_id / user_id 模式.
--   迁移到新 schema 后, policy 自动跟着迁过来, 不需要重建.
--   但 Supabase Dashboard 默认只暴露 public; 必须手动把 autowriter 加进
--   Exposed schemas 列表, 否则 PostgREST 返回 404.

-- 校验
DO $$
DECLARE
    expected_tables TEXT[] := ARRAY['projects', 'batches', 'items', 'versions', 'memories'];
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
        RAISE WARNING 'autowriter schema migration incomplete: % tables missing', missing;
    ELSE
        RAISE NOTICE 'autowriter schema migration OK';
    END IF;
END $$;
