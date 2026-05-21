-- ════════════════════════════════════════════════════════════════════
-- autowriter-migrations/006_backfill_tv_synced_user_id.sql
-- ════════════════════════════════════════════════════════════════════
--
-- 2026-05-21 audit fix · 通道 2 RLS 静默断开 backfill
--
-- 背景:
--   旧版 truth-vault/scripts/sync_truth_vault_baokuan_to_autowriter_items.py
--   要求 env var AUTOWRITER_SYNC_USER_ID, 用它做 batches/items.user_id.
--
--   autowriter 的 RLS:
--     CREATE POLICY items_owner ON autowriter.items
--         USING (user_id = auth.uid());
--     CREATE POLICY batches_owner ON autowriter.batches
--         USING (user_id = auth.uid());
--
--   于是普通用户 (auth.uid() = project owner) 用自己的 JWT 读 items 时,
--   service-account 写入的 TV-synced rows 永远被 RLS 滤掉, list_example_items
--   返回空, build_system_prompt 拿不到 positive examples, 飞轮断.
--
--   2026-05-21 sync 脚本改为查 autowriter.projects.owner_id 并写入
--   batches/items.user_id. 本 backfill 把历史 TV-synced 行修正成新约定.
--
-- 前置:
--   先在 truth-vault sync 脚本侧应用 commit (resolve_aw_project_owner 已生效).
--   002 / 003 migrations 已应用 (external_source 列存在).
--
-- 部署:
--   psql -d <shared_supabase> -f 006_backfill_tv_synced_user_id.sql
--
-- 幂等: 只 UPDATE WHERE user_id 与目标 owner_id 不一致. 重跑 0 行.
-- ════════════════════════════════════════════════════════════════════

BEGIN;

-- 1. items.user_id ← projects.owner_id (via batches.project_id)
WITH target AS (
    SELECT
        i.id                AS item_id,
        p.owner_id          AS desired_user_id
    FROM autowriter.items     i
    JOIN autowriter.batches   b ON b.id = i.batch_id
    JOIN autowriter.projects  p ON p.id = b.project_id
    WHERE i.external_source = 'truth_vault'
      AND p.owner_id IS NOT NULL
      AND p.owner_id <> i.user_id
)
UPDATE autowriter.items i
SET user_id = t.desired_user_id
FROM target t
WHERE i.id = t.item_id;

-- 2. batches.user_id ← projects.owner_id (only TV-synced special batches)
WITH target AS (
    SELECT
        b.id                AS batch_id,
        p.owner_id          AS desired_user_id
    FROM autowriter.batches  b
    JOIN autowriter.projects p ON p.id = b.project_id
    WHERE b.tactic = 'truth_vault_synced'
      AND p.owner_id IS NOT NULL
      AND p.owner_id <> b.user_id
)
UPDATE autowriter.batches b
SET user_id = t.desired_user_id
FROM target t
WHERE b.id = t.batch_id;

-- 校验: 不应再有 TV-synced item 的 user_id 与 project owner 不一致
DO $$
DECLARE
    mismatched INTEGER;
BEGIN
    SELECT COUNT(*) INTO mismatched
    FROM autowriter.items     i
    JOIN autowriter.batches   b ON b.id = i.batch_id
    JOIN autowriter.projects  p ON p.id = b.project_id
    WHERE i.external_source = 'truth_vault'
      AND p.owner_id IS NOT NULL
      AND p.owner_id <> i.user_id;

    IF mismatched > 0 THEN
        RAISE EXCEPTION
            'Backfill incomplete: % TV-synced items still have user_id != project owner',
            mismatched;
    END IF;
    RAISE NOTICE 'autowriter-migrations/006 backfill complete';
END $$;

COMMIT;
