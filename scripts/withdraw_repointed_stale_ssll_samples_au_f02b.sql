-- ════════════════════════════════════════════════════════════════════
-- AU-F02b ④ · 撤回三省六部里「旧帖内容、挂着新帖 note_id」的通道 1 样本 (owner 看过之后, 在 Supabase SQL editor 整份跑)
-- ════════════════════════════════════════════════════════════════════
--
-- ⚠️ 这份会动三省六部 (外部下游) 的数据, 要 owner 先看再跑。
-- ⚠️ 要先跑删旧帖评论那份 (scripts/cleanup_repointed_stale_comments_au_f02b.sql): 重推时热评从 comments 表取,
--    旧帖的评论还在的话, 重推出去的样本还是带着旧帖的热评。这份文件开头会检查, 没先跑就报错、什么都不改。
--    所以这份跟着那份走: owner 不同意删旧帖评论 (那份改的是 D-119 #15) 的话, 这份也不跑,
--    verify #109、#110 的期望都改成当时的读数。
--
-- 背景: 飞书里有些记录被运营整条改成了另一篇帖 (同一次改动里链接和账号一起换了; 审计 F02, D-137)。
--   改指之前, 通道 1 已经把旧帖推进了三省六部 (public.reference_samples)。推送只在第一次推, 不跟着帖子变,
--   所以这些样本里的正文、热评还是旧帖的, 却标着现在这篇的 note_id。
--
-- 怎么认 (和 verify_supabase_state.sql #110 同一条规则):
--   · 这篇在 audit_log 里有过一次 UPDATE, 同时改了 publish_url 和 account_id
--     (链接去掉首尾空白之后前后都不空、不一样; 改指的认法和删评论那份一字不差);
--   · 样本是在这篇最后一次改指之前推的;
--   · 样本正文和这篇现在的正文不一样。
--   对照: 没改指过的篇, 样本正文 290 / 294 和现在的正文一样 (11-25 读数; 每晚新推会让它变, 不一样的一直是 4 个);
--   改指之后才推的 5 篇也一样 (OKMAN 4、SPX 1)。
--   这 29 篇都还有随贴评论原文, 改指时发布时间也换了, 所以它们的旧帖评论都在删评论那份的范围里。
--
-- 11-25 生产只读 dry-run (跑之前的数): 会撤 29 个样本, 全在 OKMAN_phase1 (改指过的 319 篇里推过的 33 篇中, 改指前推的 29 篇)。
--   别的项目 0。
--
-- 改什么 (写序同 sync_truth_vault_baokuan_to_sanshengliubu.py 的 _retract_one: 先清标记、再删样本):
--   ① 这几篇笔记的 synced_to_ssll_at / synced_ssll_reference_sample_id 清空;
--   ② 删掉这几个样本。
--   先把样本整行、笔记的两列原值备份进 truth_vault.backup_repoint_stale_ssll_samples_20261125 和
--   truth_vault.backup_repoint_stale_ssll_marks_20261125 (已登记在 docs/backup-registry.md; 回滚写在表注释里)。
-- 之后会发生什么: 下一晚通道 1 会按现在的帖把仍是爆 / 大爆的那几篇重新推进去 (正文和热评都是新帖的)。
--   ⚠️ 大批首推闸: 一晚新推超过 30 篇整步不推、daily-sync 那一步红 (D-130)。这 29 篇加上当晚别的新篇超过 30 时,
--   看过名单后用 daily-sync 的 allow_bulk_ssll_push 放行一次。
-- 不改什么: 别的样本、笔记的其他列、评论。
--
-- 可以重跑: 第二次跑时规则找不到样本, 什么都不改, 备份表也不多行。
-- 跑完看最后一个 SELECT: stale_left = 0, backed_up_samples ≈ 29, backed_up_marks ≈ 29, marks_not_cleared = 0
--   (第二天通道 1 重推之后 marks_not_cleared 会变成重推的篇数, 那是正常的)。
-- ════════════════════════════════════════════════════════════════════

BEGIN;

-- 0. 这一次要撤的样本
CREATE TEMP TABLE _stale_ssll ON COMMIT DROP AS
WITH rp AS (
    SELECT a.row_id AS note_id, max(a.occurred_at) AS last_rp, bool_or(a.changed_cols ? 'publish_time') AS pt_changed
    FROM truth_vault.audit_log a
    WHERE a.schema_name = 'truth_vault' AND a.table_name = 'notes' AND a.operation = 'UPDATE'
      AND a.changed_cols ? 'publish_url' AND a.changed_cols ? 'account_id'
      AND btrim(coalesce(a.changed_cols->'publish_url'->>0, ''), E' \t\r\n') <> ''
      AND btrim(coalesce(a.changed_cols->'publish_url'->>1, ''), E' \t\r\n') <> ''
      AND btrim(a.changed_cols->'publish_url'->>0, E' \t\r\n') IS DISTINCT FROM btrim(a.changed_cols->'publish_url'->>1, E' \t\r\n')
    GROUP BY a.row_id
)
SELECT r.id AS sample_id, rp.note_id
FROM rp
JOIN truth_vault.notes n ON n.note_id = rp.note_id
JOIN public.reference_samples r ON r.source_truth_vault_note_id = rp.note_id
WHERE r.created_at < (rp.last_rp AT TIME ZONE 'UTC')
  AND r.post_body IS DISTINCT FROM n.raw_content;

-- 0b. 旧帖评论还在就不撤 (先跑 cleanup_repointed_stale_comments_au_f02b.sql)
DO $$
DECLARE cnt BIGINT;
BEGIN
    WITH rp AS (
        SELECT a.row_id AS note_id, max(a.occurred_at) AS last_rp, bool_or(a.changed_cols ? 'publish_time') AS pt_changed
        FROM truth_vault.audit_log a
        WHERE a.schema_name = 'truth_vault' AND a.table_name = 'notes' AND a.operation = 'UPDATE'
          AND a.changed_cols ? 'publish_url' AND a.changed_cols ? 'account_id'
          AND btrim(coalesce(a.changed_cols->'publish_url'->>0, ''), E' \t\r\n') <> ''
          AND btrim(coalesce(a.changed_cols->'publish_url'->>1, ''), E' \t\r\n') <> ''
          AND btrim(a.changed_cols->'publish_url'->>0, E' \t\r\n') IS DISTINCT FROM btrim(a.changed_cols->'publish_url'->>1, E' \t\r\n')
        GROUP BY a.row_id
    )
    SELECT count(*) INTO cnt
    FROM rp JOIN truth_vault.notes n ON n.note_id = rp.note_id
    JOIN truth_vault.comments c ON c.note_id = rp.note_id
    WHERE rp.note_id IN (SELECT note_id FROM _stale_ssll)
      AND c.source IS NULL AND c.created_at < rp.last_rp
      AND (n.raw_extra ? '_comment_text' OR n.raw_extra ? '_comment_text_persona' OR rp.pt_changed)
      AND position(btrim(c.content) IN coalesce(n.raw_extra->>'_comment_text', '') || E'\n'
                                       || coalesce(n.raw_extra->>'_comment_text_persona', '')) = 0;
    IF cnt > 0 THEN
        RAISE EXCEPTION '这几篇上还有 % 条旧帖评论: 先跑 scripts/cleanup_repointed_stale_comments_au_f02b.sql (owner 同意删旧帖评论才能跑), 不然重推出去的样本还带着旧帖的热评。这次什么都没改。', cnt;
    END IF;
END $$;

-- 1. 备份 (放在 truth_vault 下: public 的默认授权会把新表给 anon)
CREATE TABLE IF NOT EXISTS truth_vault.backup_repoint_stale_ssll_samples_20261125 (LIKE public.reference_samples);
CREATE TABLE IF NOT EXISTS truth_vault.backup_repoint_stale_ssll_marks_20261125 AS
    SELECT note_id, synced_to_ssll_at, synced_ssll_reference_sample_id FROM truth_vault.notes WHERE false;
ALTER TABLE truth_vault.backup_repoint_stale_ssll_samples_20261125 ENABLE ROW LEVEL SECURITY;
ALTER TABLE truth_vault.backup_repoint_stale_ssll_marks_20261125 ENABLE ROW LEVEL SECURITY;
DO $$
DECLARE r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON truth_vault.backup_repoint_stale_ssll_samples_20261125 FROM %I', r);
            EXECUTE format('REVOKE ALL ON truth_vault.backup_repoint_stale_ssll_marks_20261125 FROM %I', r);
        END IF;
    END LOOP;
END $$;

INSERT INTO truth_vault.backup_repoint_stale_ssll_samples_20261125
SELECT r.* FROM public.reference_samples r
WHERE r.id IN (SELECT sample_id FROM _stale_ssll)
  AND NOT EXISTS (SELECT 1 FROM truth_vault.backup_repoint_stale_ssll_samples_20261125 b WHERE b.id = r.id);

INSERT INTO truth_vault.backup_repoint_stale_ssll_marks_20261125
SELECT n.note_id, n.synced_to_ssll_at, n.synced_ssll_reference_sample_id FROM truth_vault.notes n
WHERE n.note_id IN (SELECT note_id FROM _stale_ssll)
  AND NOT EXISTS (SELECT 1 FROM truth_vault.backup_repoint_stale_ssll_marks_20261125 b WHERE b.note_id = n.note_id);

COMMENT ON TABLE truth_vault.backup_repoint_stale_ssll_samples_20261125 IS
  'AU-F02b ④ (2026-11-25): 三省六部里旧帖内容、挂着改指后 note_id 的通道 1 样本, 撤之前的整行。回滚 (先这张、再标记那张): '
  'INSERT INTO public.reference_samples SELECT * FROM truth_vault.backup_repoint_stale_ssll_samples_20261125 '
  'ON CONFLICT (id) DO NOTHING; 登记在 docs/backup-registry.md (D-136: 留着, 不删)。';
COMMENT ON TABLE truth_vault.backup_repoint_stale_ssll_marks_20261125 IS
  'AU-F02b ④ (2026-11-25): 上面那批样本对应笔记的通道 1 标记原值。回滚: UPDATE truth_vault.notes n SET '
  'synced_to_ssll_at = b.synced_to_ssll_at, synced_ssll_reference_sample_id = b.synced_ssll_reference_sample_id '
  'FROM truth_vault.backup_repoint_stale_ssll_marks_20261125 b WHERE n.note_id = b.note_id;';

-- 2. 先清标记、再删样本
UPDATE truth_vault.notes
SET synced_to_ssll_at = NULL, synced_ssll_reference_sample_id = NULL
WHERE note_id IN (SELECT note_id FROM _stale_ssll);
DELETE FROM public.reference_samples WHERE id IN (SELECT sample_id FROM _stale_ssll);

COMMIT;

-- 3. 回读
WITH rp AS (
    SELECT a.row_id AS note_id, max(a.occurred_at) AS last_rp, bool_or(a.changed_cols ? 'publish_time') AS pt_changed
    FROM truth_vault.audit_log a
    WHERE a.schema_name = 'truth_vault' AND a.table_name = 'notes' AND a.operation = 'UPDATE'
      AND a.changed_cols ? 'publish_url' AND a.changed_cols ? 'account_id'
      AND btrim(coalesce(a.changed_cols->'publish_url'->>0, ''), E' \t\r\n') <> ''
      AND btrim(coalesce(a.changed_cols->'publish_url'->>1, ''), E' \t\r\n') <> ''
      AND btrim(a.changed_cols->'publish_url'->>0, E' \t\r\n') IS DISTINCT FROM btrim(a.changed_cols->'publish_url'->>1, E' \t\r\n')
    GROUP BY a.row_id
)
SELECT
    (SELECT count(*) FROM rp JOIN truth_vault.notes n ON n.note_id = rp.note_id
       JOIN public.reference_samples r ON r.source_truth_vault_note_id = rp.note_id
      WHERE r.created_at < (rp.last_rp AT TIME ZONE 'UTC') AND r.post_body IS DISTINCT FROM n.raw_content) AS stale_left,
    (SELECT count(*) FROM truth_vault.backup_repoint_stale_ssll_samples_20261125) AS backed_up_samples,
    (SELECT count(*) FROM truth_vault.backup_repoint_stale_ssll_marks_20261125) AS backed_up_marks,
    (SELECT count(*) FROM truth_vault.notes n JOIN truth_vault.backup_repoint_stale_ssll_marks_20261125 b USING (note_id)
      WHERE n.synced_to_ssll_at IS NOT NULL) AS marks_not_cleared;
