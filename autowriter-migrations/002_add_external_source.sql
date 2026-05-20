-- ════════════════════════════════════════════════════════════════════
-- autowriter-migrations/002_add_external_source.sql
-- ════════════════════════════════════════════════════════════════════
--
-- P1 Sprint 1.1: 给 autowriter.items 加 external_source / external_source_id
-- 列, 作为 Truth Vault 通道 2 sync 的强幂等键.
--
-- 没有这两列, sync 脚本 (sync_truth_vault_baokuan_to_autowriter_items.py)
-- 重跑会触发重复 INSERT, 因为它依赖 ON CONFLICT (external_source,
-- external_source_id) DO NOTHING.
--
-- 部署:
--   psql -d <shared_supabase> -f 002_add_external_source.sql
--
-- 幂等: ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS.
-- ════════════════════════════════════════════════════════════════════

-- 1. external_source: 数据来源标识, 'truth_vault' 标识 TV sync 写入的 item
ALTER TABLE autowriter.items
    ADD COLUMN IF NOT EXISTS external_source TEXT;

-- 2. external_source_id: 外部系统中的唯一标识. TV sync 写入 notes.note_id
ALTER TABLE autowriter.items
    ADD COLUMN IF NOT EXISTS external_source_id TEXT;

-- 3. Partial UNIQUE INDEX: 只对 external_source IS NOT NULL 的行强制唯一.
--    这避免影响 autowriter 自己生产的 items (它们 external_source = NULL).
CREATE UNIQUE INDEX IF NOT EXISTS items_external_source_uniq
    ON autowriter.items (external_source, external_source_id)
    WHERE external_source IS NOT NULL;

COMMENT ON COLUMN autowriter.items.external_source IS
    'Data source identifier. NULL for autowriter-generated items. '
    '''truth_vault'' for items synced by '
    'truth-vault/scripts/sync_truth_vault_baokuan_to_autowriter_items.py.';

COMMENT ON COLUMN autowriter.items.external_source_id IS
    'Foreign key into the external system. For TV sync, this is '
    'truth_vault.notes.note_id (e.g. NUC_phase1_recXXX). '
    'Paired with external_source as the idempotency key for TV sync.';

-- 校验
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'autowriter' AND table_name = 'items'
        AND column_name = 'external_source'
    ) THEN
        RAISE EXCEPTION 'Migration failed: external_source not present';
    END IF;
END $$;
