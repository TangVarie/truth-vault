-- ════════════════════════════════════════════════════════════════════
-- sanshengliubu-patches/001_add_source_tv_note_id.sql
-- ════════════════════════════════════════════════════════════════════
--
-- 必做前置 (D-024 通道 1):
--   在 sanshengliubu 的 public.reference_samples 表上加一列
--   source_truth_vault_note_id，作为 Truth Vault 通道 1 sync 的反向追溯键
--   + 幂等键。
--
-- 必须先于 sanshengliubu 集成 patch 跑，也必须先于 truth-vault/scripts/
-- sync_truth_vault_baokuan_to_sanshengliubu.py 跑 (脚本会无条件写入此列;
-- preflight_check() 启动时会校验列存在)。
--
-- 类型 TEXT (不是 UUID): truth_vault.notes.note_id 是 TEXT, 规则
-- f"{project_id}_{feishu_record_id}".
--
-- 部署:
--   psql -d <sanshengliubu_db> -f 001_add_source_tv_note_id.sql
-- 或在 Supabase SQL Editor 粘贴执行.
--
-- 幂等: 重复执行不报错; 列已存在时跳过.
-- ════════════════════════════════════════════════════════════════════

-- 1. 加列
ALTER TABLE public.reference_samples
    ADD COLUMN IF NOT EXISTS source_truth_vault_note_id TEXT;

-- 2. 加索引 (sync 脚本的幂等查询走这个).
--
-- 2026-05-22 audit P1-3 修复: 必须是 UNIQUE INDEX, 不能只是 INDEX.
-- 旧版只是普通 index, 在 cron / 手动并发跑时会插重复 reference pack.
-- (TV sync 脚本本身做应用层去重, 但应用层去重在并发下不是 race-free 的;
-- 必须在 DB 层有 UNIQUE 约束做最后一道关.)
-- partial: 只对非 NULL 行加约束, 不影响 sanshengliubu 自建样本.
CREATE UNIQUE INDEX IF NOT EXISTS idx_reference_samples_tv_note_id_unique
    ON public.reference_samples (source_truth_vault_note_id)
    WHERE source_truth_vault_note_id IS NOT NULL;

-- 老命名兼容: 之前装过 001 旧版本的库可能已经有 idx_reference_samples_tv_note
-- (非 unique). 让它和新名共存或换名是 003 migration 的工作 — 见
-- sanshengliubu-patches/003_strengthen_tv_note_id_unique.sql.

-- 3. (可选) 加注释,方便后续 schema 漫游识别意图
COMMENT ON COLUMN public.reference_samples.source_truth_vault_note_id IS
    'Truth Vault notes.note_id (e.g. NUC_phase1_recXXX). Set by TV sync. '
    'Idempotency key for sync_truth_vault_baokuan_to_sanshengliubu.py. '
    'ai_analysis->>_truth_vault_note_id is the legacy fallback for rows '
    'imported before this column existed.';

-- 4. 校验
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
        AND table_name = 'reference_samples'
        AND column_name = 'source_truth_vault_note_id'
    ) THEN
        RAISE EXCEPTION 'Migration failed: column not present after ALTER';
    END IF;
END $$;
