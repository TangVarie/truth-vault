-- ════════════════════════════════════════════════════════════════════
-- autowriter-migrations/009_fix_batch_item_counts_and_version_uniq.sql
-- ════════════════════════════════════════════════════════════════════
--
-- 升级迁移 (不是 fresh install 基线)。修复审计 COR-005 / COR-010。
--
-- 为什么单独一条迁移:
--   RUNBOOK 把 007 定为「场景 C · fresh install」脚本; 场景 A/B 只跑 001–003。
--   而生产已经完成过 007 —— 已经部署的 autowriter schema 不会再重跑 007, 于是:
--     - COR-005: 旧库上的 batch_item_counts 仍是 `FROM items` + `SET search_path=''`,
--       一调用就 relation "items" does not exist;
--     - COR-010: 旧库上的 versions 没有 (item_id, version_num) 唯一约束, 仍可能
--       出现重复版本号 → best_version_id 歧义。
--   所以这两个修复不能只写进 007 基线, 必须有一条可对已部署库单独执行的增量迁移。
--
-- 部署:
--   在已经跑过 007(或 001–003 组装)的共享 Supabase 上执行:
--     psql -d <shared_supabase> -f 009_fix_batch_item_counts_and_version_uniq.sql
--   或在 Supabase Dashboard → SQL Editor 粘贴执行。
--   fresh install(场景 C 跑 007)已经内置了这两个修复, 本迁移是幂等 no-op。
--
-- 幂等: 函数用 CREATE OR REPLACE; 唯一索引用 IF NOT EXISTS。可安全重跑。
-- 失败模式: 若 versions 里已存在重复 (item_id, version_num), CREATE UNIQUE INDEX
--   会报错 —— 本脚本先检测重复并列出, 由运营决定保哪条再重跑。
-- ════════════════════════════════════════════════════════════════════

BEGIN;

-- ── 1. COR-005: batch_item_counts 清空 search_path 后必须用 schema 限定表名 ──
--   原函数 `FROM items` 在 `SET search_path = ''` 下无法解析, 一调用就报错。
CREATE OR REPLACE FUNCTION autowriter.batch_item_counts(batch_ids UUID[])
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
SET search_path = ''
AS $$
    SELECT
        i.batch_id,
        COUNT(*)                                                AS total,
        COUNT(*) FILTER (WHERE i.status = 'approved')           AS approved,
        COUNT(*) FILTER (WHERE i.status = 'pending')            AS pending,
        COUNT(*) FILTER (WHERE i.status = 'needs_revision')     AS needs_revision
    FROM autowriter.items i
    WHERE i.batch_id = ANY(batch_ids)
    GROUP BY i.batch_id;
$$;
GRANT EXECUTE ON FUNCTION autowriter.batch_item_counts(UUID[]) TO authenticated, service_role;

-- ── 2. COR-010: versions 加 (item_id, version_num) 唯一约束 ──
--   应用层"先查后插"在并发下有竞态窗口, 会撞出重复 version_num。唯一索引在
--   数据库层做最后一道关。先检测重复(不擅自删), 再建唯一索引。
DO $$
DECLARE
    dup_count INTEGER;
    sample_item UUID;
    sample_ver INTEGER;
BEGIN
    SELECT COUNT(*) INTO dup_count
    FROM (
        SELECT item_id, version_num
        FROM autowriter.versions
        GROUP BY item_id, version_num
        HAVING COUNT(*) > 1
    ) dups;

    IF dup_count > 0 THEN
        SELECT item_id, version_num INTO sample_item, sample_ver
        FROM autowriter.versions
        GROUP BY item_id, version_num
        HAVING COUNT(*) > 1
        LIMIT 1;

        RAISE EXCEPTION
            'Cannot create UNIQUE index: % duplicate (item_id, version_num) rows '
            'exist (e.g. item_id=% version_num=%). Decide which row to keep, DELETE '
            'the others, then re-run this migration. Inspect with: '
            'SELECT item_id, version_num, COUNT(*), array_agg(id) FROM autowriter.versions '
            'GROUP BY item_id, version_num HAVING COUNT(*) > 1;',
            dup_count, sample_item, sample_ver;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS versions_item_version_uniq
    ON autowriter.versions (item_id, version_num);

-- ── 3. 校验: 唯一索引必须存在且真的 unique ──
DO $$
DECLARE
    is_unique BOOLEAN;
BEGIN
    SELECT i.indisunique INTO is_unique
    FROM pg_index i
    JOIN pg_class c ON c.oid = i.indexrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'autowriter'
      AND c.relname = 'versions_item_version_uniq';

    IF is_unique IS NULL THEN
        RAISE EXCEPTION
            'autowriter-migrations/009 failed: versions_item_version_uniq not present.';
    END IF;
    IF NOT is_unique THEN
        RAISE EXCEPTION
            'autowriter-migrations/009 failed: versions_item_version_uniq exists but '
            'indisunique=false. DROP it manually and re-run.';
    END IF;
    RAISE NOTICE 'autowriter-migrations/009 OK: batch_item_counts qualified + versions UNIQUE';
END $$;

COMMIT;
