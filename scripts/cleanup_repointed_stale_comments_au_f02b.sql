-- ════════════════════════════════════════════════════════════════════
-- AU-F02b ④ · 删掉「整条记录改指到另一篇帖」之后留下的旧帖评论 (owner 在 Supabase SQL editor 整份跑)
-- ════════════════════════════════════════════════════════════════════
--
-- ⚠️ 这份改的是 D-119 第 15 条 (I-09 关闭时定的), owner 点头才跑。
--   D-119 #15: 运营从飞书删掉的评论留着, 不删、不加标; 理由是飞书里没了不等于平台上没有过;
--   评论构成进闸二时, 要报一次去掉这批之后的敏感性结果 (记在 J-02)。当时点名 OKMAN 768、LNKT 244。
--   OKMAN 那 768 条, 就是这份要处理的这批: OKMAN 现在源里找不到的运营评论 778 条, 全在改指过的篇上。
--   新证据: 它们不是「平台上没了」, 是改指之前那篇帖的评论。这份要删的 765 条里, 752 条在另一篇 OKMAN 笔记
--   现在的随贴评论里原样找得到。所以跑这份 = 对改指过的 OKMAN 篇修订 D-119 #15 (D-173)。
--   LNKT 244 条和别的项目照 D-119 #15 留着, 这份不碰。
--
-- 背景: 飞书里有些记录被运营整条改成了另一篇帖 (同一次改动里链接和账号一起换了; 审计 F02, D-137)。
--   笔记本身是对的 (同步按现在的飞书行重写)。但运营贴的评论 (comments.source 为空的行) 只加不删:
--   旧帖那几条评论还挂在这个 note_id 上, Jev 也给它们判过分。按篇统计评论构成、通道 1 带的热评都会混进旧帖的评论。
--
-- 怎么认「旧帖的评论」(和 verify_supabase_state.sql #109 同一条规则, 三条都要满足):
--   ① 改指: 这篇在 audit_log 里有过一次 UPDATE, 同时改了 publish_url 和 account_id;
--      链接去掉首尾空白之后前后都不空、不一样 (只差空白的不算)。
--   ② 评论是运营贴的 (source 为空), 入库早于这篇最后一次改指, 正文在这篇现在的随贴评论原文里找不到。
--   ③ 这篇现在还有随贴评论原文 (raw_extra 里有 _comment_text 或 _comment_text_persona 键),
--      或者改指那几次里有一次连发布时间也换了。
--   为什么要第 ③ 条: 没有原文键的篇, 「找不到」只说明源清空了, 证明不了评论是旧帖的。
--   同步对「源清空」的篇只报不删 (TUGE 没改指的篇里就有 34 条这样的)。
--
-- 对照 (只看还有原文键的篇):
--   没改指的 OKMAN 篇 25 / 25 能找到; 改指之后才入库的 OKMAN 评论 372 / 372 能找到;
--   改指过的另 7 个项目里没改指的篇 2,588 / 2,650 (98%) 能找到, 找不到的就是 D-119 #15 留着的那批。
--   没有原文键的篇一条都找不到 (OKMAN 改指篇 148、TUGE 没改指篇 34、SPX 24 等), 所以才有第 ③ 条。
--
-- 11-25 生产只读 dry-run (跑之前的数):
--   改指过的篇 356 (OKMAN_phase1 319, 另 7 个项目共 37)。按原始链接比是 365: 多出的 9 篇 (ANSHEN 8、TUGE 1)
--     前后链接只差空白, 不算改指。
--   满足 ① ② 的评论 781 行 / 248 篇。其中满足 ③、这份会删的 765 行 / 242 篇, 全在 OKMAN_phase1:
--     · 还有原文键的 197 篇上 630 行;
--     · 没有原文键、改指时发布时间也换了的 45 篇上 135 行。
--   不满足 ③、这份不删的 16 行 / 6 篇: OKMAN 13 行 / 3 篇, TUGE_phase1 3 行 / 3 篇。这 6 篇没有原文键,
--     改指那次发布时间也没换 (TUGE 那 3 篇是 09-16 改的)。和同步「源清空只报不删」一样留着, 要不要删由 owner 另定。
--   删完之后有 45 篇 (都是 OKMAN) 一条运营评论都不剩: 它们现在没有随贴评论原文, 旧帖的评论本来就不是它们的。
--   765 条都有 Jev 的评论判分 (note_feature_answers, subject_type = comment), 一起删: 6,885 行 (每条 9 行)。
--   这些判分全来自 10-16 J-02 全量 shadow (run_tag shadow-comments-38868417905)。J-02 记下的那次总数
--     (9,766 条; 读者侧 68,362 行、运营侧 19,532 行) 跑完之后在表里对不上了: 少 765 条、读者侧 5,355 行、
--     运营侧 1,530 行。原行都在下面两张备份表里。
--   没有别的评论挂在它们下面 (parent_comment_id 指向它们的 0 行)。读者评论 (巡查来的, source 不为空) 不动。
--
-- 改什么: 删这些评论行和它们的评论判分行。先整行备份进两张表:
--   truth_vault.backup_repoint_stale_comments_20261125、truth_vault.backup_repoint_stale_comment_judge_20261125
--   (已登记在 docs/backup-registry.md; 回滚写在表注释里)。
-- 不改什么: 笔记本身、读者评论、没改指过的篇、上面那 16 行、通道 1 样本 (那是另一份文件
--   scripts/withdraw_repointed_stale_ssll_samples_au_f02b.sql, 因为会动三省六部, 要单独看)。
-- 之后: 夜跑的评论同步按 (角色, 正文) 配对, 现在的原文里没有这些评论, 不会再加回来。
--
-- 可以重跑: 第二次跑时规则找不到行, 什么都不删, 备份表也不多行。
-- 跑完看最后一个 SELECT: stale_left = 0; backed_up_comments ≈ 765, backed_up_judge_rows ≈ 6,885;
--   kept_no_source_text ≈ 16 (上面留着的那 16 行); judge_rows_without_comment = 0。
-- ════════════════════════════════════════════════════════════════════

BEGIN;

-- 0. 这一次要删的评论
CREATE TEMP TABLE _stale_comments ON COMMIT DROP AS
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
SELECT c.comment_id
FROM rp
JOIN truth_vault.notes n ON n.note_id = rp.note_id
JOIN truth_vault.comments c ON c.note_id = rp.note_id
WHERE c.source IS NULL AND c.created_at < rp.last_rp
  AND (n.raw_extra ? '_comment_text' OR n.raw_extra ? '_comment_text_persona' OR rp.pt_changed)
  AND position(btrim(c.content) IN coalesce(n.raw_extra->>'_comment_text', '') || E'\n'
                                   || coalesce(n.raw_extra->>'_comment_text_persona', '')) = 0;

-- 1. 备份 (整行; 按主键去重, 重跑不多行)
CREATE TABLE IF NOT EXISTS truth_vault.backup_repoint_stale_comments_20261125 (LIKE truth_vault.comments);
CREATE TABLE IF NOT EXISTS truth_vault.backup_repoint_stale_comment_judge_20261125 (LIKE truth_vault.note_feature_answers);
ALTER TABLE truth_vault.backup_repoint_stale_comments_20261125 ENABLE ROW LEVEL SECURITY;
ALTER TABLE truth_vault.backup_repoint_stale_comment_judge_20261125 ENABLE ROW LEVEL SECURITY;
DO $$
DECLARE r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON truth_vault.backup_repoint_stale_comments_20261125 FROM %I', r);
            EXECUTE format('REVOKE ALL ON truth_vault.backup_repoint_stale_comment_judge_20261125 FROM %I', r);
        END IF;
    END LOOP;
END $$;

INSERT INTO truth_vault.backup_repoint_stale_comments_20261125
SELECT c.* FROM truth_vault.comments c
WHERE c.comment_id IN (SELECT comment_id FROM _stale_comments)
  AND NOT EXISTS (SELECT 1 FROM truth_vault.backup_repoint_stale_comments_20261125 b WHERE b.comment_id = c.comment_id);

INSERT INTO truth_vault.backup_repoint_stale_comment_judge_20261125
SELECT a.* FROM truth_vault.note_feature_answers a
WHERE a.subject_type = 'comment' AND a.subject_id IN (SELECT comment_id FROM _stale_comments)
  AND NOT EXISTS (SELECT 1 FROM truth_vault.backup_repoint_stale_comment_judge_20261125 b
                  WHERE (b.subject_type, b.subject_id, b.question_id, b.question_version, b.extractor, b.run_tag)
                      = (a.subject_type, a.subject_id, a.question_id, a.question_version, a.extractor, a.run_tag));

COMMENT ON TABLE truth_vault.backup_repoint_stale_comments_20261125 IS
  'AU-F02b ④ (2026-11-25): 整条记录改指到另一篇帖之后留下的旧帖运营评论, 删之前的整行 (D-173 修订 D-119 #15)。'
  'J-02 要报「带上这批」的敏感性结果时从这里读。回滚 (先这张、再判分那张): '
  'INSERT INTO truth_vault.comments SELECT * FROM truth_vault.backup_repoint_stale_comments_20261125 '
  'ON CONFLICT (comment_id) DO NOTHING; 登记在 docs/backup-registry.md (D-136: 留着, 不删)。';
COMMENT ON TABLE truth_vault.backup_repoint_stale_comment_judge_20261125 IS
  'AU-F02b ④ (2026-11-25): 上面那批旧帖评论的 Jev 评论判分行 (note_feature_answers, subject_type = comment), 删之前的整行; '
  '全是 10-16 J-02 全量 shadow 的行。回滚 (评论先回去之后): INSERT INTO truth_vault.note_feature_answers SELECT * FROM '
  'truth_vault.backup_repoint_stale_comment_judge_20261125 ON CONFLICT DO NOTHING;';

-- 2. 删 (先判分行, 再评论)
DELETE FROM truth_vault.note_feature_answers a
WHERE a.subject_type = 'comment' AND a.subject_id IN (SELECT comment_id FROM _stale_comments);
DELETE FROM truth_vault.comments c
WHERE c.comment_id IN (SELECT comment_id FROM _stale_comments);

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
), old AS (
    SELECT c.comment_id, (n.raw_extra ? '_comment_text' OR n.raw_extra ? '_comment_text_persona' OR rp.pt_changed) AS rule3
    FROM rp JOIN truth_vault.notes n ON n.note_id = rp.note_id
    JOIN truth_vault.comments c ON c.note_id = rp.note_id
    WHERE c.source IS NULL AND c.created_at < rp.last_rp
      AND position(btrim(c.content) IN coalesce(n.raw_extra->>'_comment_text', '') || E'\n'
                                       || coalesce(n.raw_extra->>'_comment_text_persona', '')) = 0
)
SELECT
    (SELECT count(*) FROM old WHERE rule3) AS stale_left,
    (SELECT count(*) FROM truth_vault.backup_repoint_stale_comments_20261125) AS backed_up_comments,
    (SELECT count(*) FROM truth_vault.backup_repoint_stale_comment_judge_20261125) AS backed_up_judge_rows,
    (SELECT count(*) FROM old WHERE rule3 IS NOT TRUE) AS kept_no_source_text,
    (SELECT count(*) FROM truth_vault.note_feature_answers a
      WHERE a.subject_type = 'comment'
        AND NOT EXISTS (SELECT 1 FROM truth_vault.comments c WHERE c.comment_id = a.subject_id)) AS judge_rows_without_comment;
