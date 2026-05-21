-- ════════════════════════════════════════════════════════════════════
-- autowriter-migrations/002_add_external_source.sql
-- ════════════════════════════════════════════════════════════════════
--
-- P1 Sprint 1.1: 给 autowriter.items 加 external_source / external_source_id
-- 列, 作为 Truth Vault 通道 2 sync 的强幂等键.
--
-- 没有这两列, sync 脚本 (sync_truth_vault_baokuan_to_autowriter_items.py)
-- 重跑会触发重复 INSERT.
--
-- 2026-05-21 update — per-user UNIQUE 模式:
--   autowriter 仓库的 db.py bootstrap 后来把唯一约束改成
--   (user_id, external_source, external_source_id) 以支持多租户 (RLS 是
--   行级, UNIQUE 是表级——只对 external_source/external_source_id 全局唯一
--   会导致两个用户同步同一条上游记录时第二个直接撞键). 本文件随之更新, 既
--   在 fresh 部署直接建 per-user 索引, 也对已跑过旧版的环境做自愈 DROP +
--   重建. 跑过旧版的 operator 不需要回滚, 直接重跑本文件即可.
--
-- 部署:
--   psql -d <shared_supabase> -f 002_add_external_source.sql
--
-- 幂等: ADD COLUMN IF NOT EXISTS / DROP IF EXISTS + CREATE IF NOT EXISTS.
-- ════════════════════════════════════════════════════════════════════

-- 1. external_source: 数据来源标识, 'truth_vault' 标识 TV sync 写入的 item
ALTER TABLE autowriter.items
    ADD COLUMN IF NOT EXISTS external_source TEXT;

-- 2. external_source_id: 外部系统中的唯一标识. TV sync 写入 notes.note_id
ALTER TABLE autowriter.items
    ADD COLUMN IF NOT EXISTS external_source_id TEXT;

-- 3. 自愈: 如果旧版本 (PR 初版) 跑过, 会有一个全局 items_external_source_uniq.
--    新约定按 user_id 分租户, 所以先 DROP 旧索引, 再建新的 per-user 索引.
--    跑在 fresh 环境上 DROP IF EXISTS 是 no-op, 跑在升级环境上才会真正 DROP.
DROP INDEX IF EXISTS autowriter.items_external_source_uniq;

-- 4. Partial UNIQUE INDEX per user: 只对 external_source IS NOT NULL 的行
--    强制 (user_id, external_source, external_source_id) 唯一.
--    autowriter 自己生产的 items (external_source = NULL) 完全不受影响.
CREATE UNIQUE INDEX IF NOT EXISTS items_external_source_per_user_uniq
    ON autowriter.items (user_id, external_source, external_source_id)
    WHERE external_source IS NOT NULL;

COMMENT ON COLUMN autowriter.items.external_source IS
    'Data source identifier. NULL for autowriter-generated items. '
    '''truth_vault'' for items synced by '
    'truth-vault/scripts/sync_truth_vault_baokuan_to_autowriter_items.py.';

COMMENT ON COLUMN autowriter.items.external_source_id IS
    'Foreign key into the external system. For TV sync, this is '
    'truth_vault.notes.note_id (e.g. NUC_phase1_recXXX). '
    'Paired with user_id + external_source as the per-user idempotency key.';

-- 校验
DO $$
BEGIN
    -- 列存在
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'autowriter' AND table_name = 'items'
        AND column_name = 'external_source'
    ) THEN
        RAISE EXCEPTION 'Migration failed: external_source column not present';
    END IF;

    -- per-user 索引存在
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE schemaname = 'autowriter'
          AND indexname  = 'items_external_source_per_user_uniq'
    ) THEN
        RAISE EXCEPTION
            'Migration failed: per-user unique index not created';
    END IF;

    -- 旧的全局索引不应再存在
    IF EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE schemaname = 'autowriter'
          AND indexname  = 'items_external_source_uniq'
    ) THEN
        RAISE EXCEPTION
            'Migration failed: stale global index items_external_source_uniq '
            'still present (should have been dropped). Re-run this file.';
    END IF;
    RAISE NOTICE '002 migration OK (per-user unique index in place)';
END $$;
