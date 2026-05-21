-- ════════════════════════════════════════════════════════════════════
-- sanshengliubu-patches/003_strengthen_tv_note_id_unique.sql
-- ════════════════════════════════════════════════════════════════════
--
-- 2026-05-22 audit P1-3 修复 · 把旧 partial INDEX 升级成 partial UNIQUE INDEX
--
-- 背景:
--   sanshengliubu-patches/001_add_source_tv_note_id.sql 的旧版本只建了普通
--   index (idx_reference_samples_tv_note). 应用层 (TV sync 脚本) 在 INSERT
--   前 SELECT 一次去重, 但在并发下不是 race-free 的:
--     - cron 和 manual run 同时跑
--     - 两个 worker 各跑一个项目, 偶然命中同一个跨项目笔记
--     - retry 逻辑在错误处理后没正确 dedupe
--   都会导致重复 reference pack 进入 sanshengliubu 库, 把 vibe_rewriter 的
--   sample pool 污染. 必须在 DB 层加 UNIQUE 约束做最后一道关.
--
--   新 (2026-05-22) 版 001 写入新命名 idx_reference_samples_tv_note_id_unique;
--   fresh install 的 ssll db/schema.sql 也是这个命名. 本 003 让历史 ssll 库
--   也升级到 UNIQUE.
--
-- 部署:
--   在已经跑过老版 001 (普通 index) 的 sanshengliubu 库上跑:
--     psql -d <sanshengliubu_db> -f 003_strengthen_tv_note_id_unique.sql
--
--   或在 Supabase SQL Editor 粘贴执行.
--
-- 幂等: 安全重跑. 如果已经是 unique 了 (新版 001 装过, 或本 003 跑过), 就跳过.
--
-- 失败模式:
--   - 如果库里有重复 source_truth_vault_note_id 的行 (旧 sync 已经污染过),
--     CREATE UNIQUE INDEX 会报错. 本脚本会先输出重复行清单让你手工处理,
--     然后才尝试建 UNIQUE.
-- ════════════════════════════════════════════════════════════════════

BEGIN;

-- 1. 先检测有没有重复. 有的话报清单, 不直接删 (运营得自己决定保哪条).
DO $$
DECLARE
    dup_count INTEGER;
    sample_dup_id TEXT;
BEGIN
    SELECT COUNT(*) INTO dup_count
    FROM (
        SELECT source_truth_vault_note_id
        FROM public.reference_samples
        WHERE source_truth_vault_note_id IS NOT NULL
        GROUP BY source_truth_vault_note_id
        HAVING COUNT(*) > 1
    ) dups;

    IF dup_count > 0 THEN
        SELECT source_truth_vault_note_id INTO sample_dup_id
        FROM public.reference_samples
        WHERE source_truth_vault_note_id IS NOT NULL
        GROUP BY source_truth_vault_note_id
        HAVING COUNT(*) > 1
        LIMIT 1;

        RAISE EXCEPTION
            'Cannot create UNIQUE index: % duplicate source_truth_vault_note_id '
            'rows exist (e.g., %). Run this query to inspect: '
            'SELECT source_truth_vault_note_id, COUNT(*), array_agg(id) '
            'FROM public.reference_samples WHERE source_truth_vault_note_id '
            'IS NOT NULL GROUP BY 1 HAVING COUNT(*) > 1; '
            'Decide which row to keep, DELETE the others, then re-run this migration.',
            dup_count, sample_dup_id;
    END IF;
END $$;

-- 2. 建新 unique index. IF NOT EXISTS 让重复跑安全.
CREATE UNIQUE INDEX IF NOT EXISTS idx_reference_samples_tv_note_id_unique
    ON public.reference_samples (source_truth_vault_note_id)
    WHERE source_truth_vault_note_id IS NOT NULL;

-- 3. 老命名 index 留着 (兼容性). 它对 query plan 不会有反作用, 因为新 unique
--    index 已覆盖所有查询路径; PG planner 会选成本更低的一个. 真要删的话
--    单独跑一行: DROP INDEX IF EXISTS public.idx_reference_samples_tv_note;
--    但不建议自动 drop, 因为如果其他 query 名字硬编码引用了它, 会突然变慢.

-- 4. 校验: 新 unique index 必须存在, 且 indisunique = true.
DO $$
DECLARE
    is_unique BOOLEAN;
BEGIN
    SELECT i.indisunique INTO is_unique
    FROM pg_index i
    JOIN pg_class c ON c.oid = i.indexrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relname = 'idx_reference_samples_tv_note_id_unique';

    IF is_unique IS NULL THEN
        RAISE EXCEPTION
            'Migration 003 failed: idx_reference_samples_tv_note_id_unique '
            'not present after CREATE.';
    END IF;
    IF NOT is_unique THEN
        RAISE EXCEPTION
            'Migration 003 failed: idx_reference_samples_tv_note_id_unique '
            'exists but indisunique=false (probably created by old 001 patch). '
            'Drop it manually and re-run: '
            'DROP INDEX IF EXISTS public.idx_reference_samples_tv_note_id_unique;';
    END IF;
    RAISE NOTICE 'sanshengliubu-patches/003 OK: idx_reference_samples_tv_note_id_unique is UNIQUE';
END $$;

COMMIT;
