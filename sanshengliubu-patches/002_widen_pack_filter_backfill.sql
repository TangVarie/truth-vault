-- ════════════════════════════════════════════════════════════════════
-- sanshengliubu-patches/002_widen_pack_filter_backfill.sql
-- ════════════════════════════════════════════════════════════════════
--
-- 2026-05-21 audit fix · 通道 1 静默断开 backfill
--
-- 背景:
--   旧版 truth-vault/scripts/sync_truth_vault_baokuan_to_sanshengliubu.py 写入
--   reference_samples 时 source_type='truth_vault_sync' + platform='xiaohongshu'.
--   sanshengliubu 的 list_reference_packs() 用
--     .eq("source_type", "pack").eq("platform", "小红书")
--   精确过滤, 所以这些行从来不会进入 vibe_rewriter 的检索池——飞轮第一段
--   静默空转.
--
--   2026-05-21 sync 脚本改为写 source_type='pack' + platform='小红书'
--   (中文 display value). 本 backfill 把历史行也修正成新约定.
--
-- 前置:
--   先在 sync 脚本侧应用 commit (源文件 source_type='pack' /
--   platform='小红书' 已生效), 否则下一次 sync 又会写回 'truth_vault_sync'.
--
-- 部署:
--   psql -d <sanshengliubu_db> -f 002_widen_pack_filter_backfill.sql
--
-- 幂等: 用 WHERE source_type='truth_vault_sync' 限定, 重跑 0 行受影响.
-- 回滚: 见底部.
-- ════════════════════════════════════════════════════════════════════

BEGIN;

-- 1. source_type: 'truth_vault_sync' → 'pack'
--    TV 来源标识保留在 tags (已含 'truth_vault_sync') + source_truth_vault_note_id.
UPDATE public.reference_samples
SET source_type = 'pack'
WHERE source_type = 'truth_vault_sync';

-- 2. platform: 英文 canonical → sanshengliubu 中文 display.
--    只动 TV 来源行 (用 tags 数组识别), 避免误改 sanshengliubu 自己创建的行.
UPDATE public.reference_samples
SET platform = CASE platform
    WHEN 'xiaohongshu' THEN '小红书'
    WHEN 'douyin'      THEN '抖音'
    WHEN 'weibo'       THEN '微博'
    WHEN 'bilibili'    THEN 'B站'
    WHEN 'kuaishou'    THEN '快手'
    ELSE platform
END
WHERE 'truth_vault_sync' = ANY(tags)
  AND platform IN ('xiaohongshu','douyin','weibo','bilibili','kuaishou');

-- 校验
DO $$
DECLARE
    leftover INTEGER;
BEGIN
    SELECT COUNT(*) INTO leftover
    FROM public.reference_samples
    WHERE source_type = 'truth_vault_sync';
    IF leftover > 0 THEN
        RAISE EXCEPTION
            'Backfill incomplete: % rows still have source_type=truth_vault_sync',
            leftover;
    END IF;
    RAISE NOTICE 'sanshengliubu-patches/002 backfill complete';
END $$;

COMMIT;

-- ──────────────────────────────────────────────────────────────────
-- 回滚 (仅在 sync 脚本也回滚到旧约定时才需要):
--   UPDATE public.reference_samples
--   SET source_type='truth_vault_sync'
--   WHERE 'truth_vault_sync' = ANY(tags) AND source_type='pack';
--
--   UPDATE public.reference_samples
--   SET platform = CASE platform
--       WHEN '小红书' THEN 'xiaohongshu'
--       WHEN '抖音' THEN 'douyin'
--       WHEN '微博' THEN 'weibo'
--       WHEN 'B站' THEN 'bilibili'
--       WHEN '快手' THEN 'kuaishou'
--       ELSE platform
--   END
--   WHERE 'truth_vault_sync' = ANY(tags)
--     AND platform IN ('小红书','抖音','微博','B站','快手');
-- ──────────────────────────────────────────────────────────────────
