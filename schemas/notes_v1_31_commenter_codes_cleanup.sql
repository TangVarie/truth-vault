-- truth_vault v1.31 · 删掉「随贴评论素人」变成的假评论 (列体检 2026-11-25 §3a #1) —— owner 在 SQL editor 跑, 一次跑完整个文件
-- ════════════════════════════════════════════════════════════════════
-- 改什么:
--   B 族表的「随贴评论素人」填的是发这条随贴评论的素人编号, 不是评论。以前评论同步把它和随贴评论拼在一起解析,
--   纯数字的编号被丢掉, 带字母的编号成了一条「素人」评论。生产 11-25 只读: 29 行, 全是运营贴的那一路 (source 为空),
--   每篇正好一行、排在最后一条:
--       NRT_phase2 12 行 · NRT_phase3 4 行 · NUC_phase1 13 行 (HXZ_FB / HXZ_QD 0 行: 它们的编号全是纯数字)
--   judge 给这 29 行打过分 (shadow-comments 两次跑), note_feature_answers 里 subject_type = comment 的账本行 270 行:
--       NRT_phase2 108 · NRT_phase3 36 · NUC_phase1 126
--   本文件: 先把这 29 行评论和 270 行账本整行备份, 再删掉。别的评论、别的账本行一行不碰。
-- 怎么认 (全部满足才算):
--   · 项目是 HXZ_FB / HXZ_QD / NRT_phase2 / NRT_phase3 / NUC_phase1;
--   · 这一篇 raw_extra 里的素人编号 (旧键 _comment_text_persona, 或新键 _commenter_codes 里的任一个) 不是纯数字;
--   · 评论是运营贴的那一路 (source 为空)、角色是 素人、正文去掉首尾空白之后正好等于这个编号;
--   · 这个编号在这一篇的随贴评论原文 (_comment_text) 里一次都没出现 (出现了就可能真是一条评论, 不删)。
-- 代码那一半 (同一个 PR): mapping 把这一列映成 _commenter_codes, 评论同步不再读它, 所以删掉之后不会再长回来。
--   请在代码合并之后跑 (合并之前跑也不出错, 但有人手动跑旧代码的评论同步, 这 29 行会以新 id 再插回来)。
-- 安全重跑: 备份只补没备份过的行; 删过的行再跑一遍认不到了, 什么都不做。重跑结果一样。
-- 前提: v1_27 跑过 (comments.source 列; 生产 11-16 已跑)。
-- 备份: truth_vault.backup_comments_commenter_20261125 / truth_vault.backup_nfa_commenter_20261125。
--   回滚 SQL 写在两张表的 COMMENT 里。按 D-136 备份都留着, 不删; 请登记到 S-02 的备份登记 (verify #92)。
-- 跑完看最后两段回读: 应剩 0 行假评论、0 行悬空账本; 备份表 29 行 / 270 行。
-- ════════════════════════════════════════════════════════════════════

BEGIN;

-- ── 1. 认出假评论 (判据只写这一处: 删之前认一遍, 删之后同一个视图再认一遍) ─────────────────────
CREATE OR REPLACE TEMP VIEW c31_match AS
SELECT DISTINCT c.comment_id, c.note_id, c.project_id
FROM truth_vault.notes n
JOIN truth_vault.comments c
  ON c.note_id = n.note_id AND c.source IS NULL AND c.comment_role = '素人'
CROSS JOIN LATERAL (
    SELECT btrim(n.raw_extra ->> '_comment_text_persona') AS code
    UNION
    SELECT btrim(x)
    FROM jsonb_array_elements_text(
        CASE WHEN jsonb_typeof(n.raw_extra -> '_commenter_codes') = 'array'
             THEN n.raw_extra -> '_commenter_codes' ELSE '[]'::jsonb END) AS x
) k
WHERE n.project_id IN ('HXZ_FB', 'HXZ_QD', 'NRT_phase2', 'NRT_phase3', 'NUC_phase1')
  AND k.code IS NOT NULL AND k.code <> ''
  AND k.code !~ '^[0-9]+[.、]?$'
  AND btrim(c.content) = k.code
  AND position(k.code IN coalesce(n.raw_extra ->> '_comment_text', '')) = 0;

CREATE TEMP TABLE c31_fake ON COMMIT DROP AS SELECT * FROM c31_match;

-- 跑之前: 要删多少 (按项目)
SELECT 'before' AS step, project_id, count(*) AS fake_comments,
       (SELECT count(*) FROM truth_vault.note_feature_answers a
         WHERE a.subject_type = 'comment' AND a.subject_id IN (SELECT comment_id FROM c31_fake f2 WHERE f2.project_id = f.project_id)
       ) AS answer_rows
FROM c31_fake f
GROUP BY project_id
ORDER BY project_id;

-- ── 2. 备份 (只补没备份过的行) ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS truth_vault.backup_comments_commenter_20261125 AS
SELECT * FROM truth_vault.comments WHERE false;
INSERT INTO truth_vault.backup_comments_commenter_20261125
SELECT c.* FROM truth_vault.comments c
WHERE c.comment_id IN (SELECT comment_id FROM c31_fake)
  AND NOT EXISTS (SELECT 1 FROM truth_vault.backup_comments_commenter_20261125 b WHERE b.comment_id = c.comment_id);

CREATE TABLE IF NOT EXISTS truth_vault.backup_nfa_commenter_20261125 AS
SELECT * FROM truth_vault.note_feature_answers WHERE false;
INSERT INTO truth_vault.backup_nfa_commenter_20261125
SELECT a.* FROM truth_vault.note_feature_answers a
WHERE a.subject_type = 'comment' AND a.subject_id IN (SELECT comment_id FROM c31_fake)
  AND NOT EXISTS (SELECT 1 FROM truth_vault.backup_nfa_commenter_20261125 b
                  WHERE b.subject_type = a.subject_type AND b.subject_id = a.subject_id
                    AND b.question_id = a.question_id AND b.question_version = a.question_version
                    AND b.extractor = a.extractor AND b.run_tag = a.run_tag);

COMMENT ON TABLE truth_vault.backup_comments_commenter_20261125 IS
    '列体检 2026-11-25 §3a #1 (v1_31): 「随贴评论素人」(素人编号) 被当成评论灌进来的假评论, 删前整行快照。'
    '回滚: INSERT INTO truth_vault.comments SELECT * FROM truth_vault.backup_comments_commenter_20261125 b '
    'WHERE NOT EXISTS (SELECT 1 FROM truth_vault.comments c WHERE c.comment_id = b.comment_id); '
    '(要先回滚评论、再回滚 backup_nfa_commenter_20261125。) 按 D-136 留着不删, 登记在 S-02。';
COMMENT ON TABLE truth_vault.backup_nfa_commenter_20261125 IS
    '列体检 2026-11-25 §3a #1 (v1_31): judge 给那批假评论打的分 (note_feature_answers, subject_type = comment), 删前整行快照。'
    '回滚 (先回滚 backup_comments_commenter_20261125): INSERT INTO truth_vault.note_feature_answers '
    'SELECT * FROM truth_vault.backup_nfa_commenter_20261125 ON CONFLICT DO NOTHING; 按 D-136 留着不删, 登记在 S-02。';

-- ── 3. 删: 先删账本 (没有外键), 再删评论 (楼中楼的子评论 ON DELETE SET NULL; 11-25 是 0 条) ─────────────
DELETE FROM truth_vault.note_feature_answers
WHERE subject_type = 'comment' AND subject_id IN (SELECT comment_id FROM c31_fake);
DELETE FROM truth_vault.comments
WHERE comment_id IN (SELECT comment_id FROM c31_fake);

-- ── 4. 回读 ───────────────────────────────────────────────────────────
-- ① 删完还剩几行 (应 0): 同一个视图再认一遍
SELECT 'after' AS step, count(*) AS fake_comments_left FROM c31_match;
-- ② 悬空的评论账本 (应 0; 同 verify #85 的口径)
SELECT 'after' AS step, count(*) AS dangling_comment_answers
FROM truth_vault.note_feature_answers a
LEFT JOIN truth_vault.comments c ON c.comment_id = a.subject_id
WHERE a.subject_type = 'comment' AND c.comment_id IS NULL AND a.subject_id NOT LIKE '%\_lcd%'
  AND a.subject_id IN (SELECT comment_id FROM truth_vault.backup_comments_commenter_20261125);
-- ③ 备份表行数 (第一次跑完应 29 / 270, 之后一直是这两个数)
SELECT 'backup' AS step,
       (SELECT count(*) FROM truth_vault.backup_comments_commenter_20261125) AS backup_comments,
       (SELECT count(*) FROM truth_vault.backup_nfa_commenter_20261125) AS backup_answer_rows;

COMMIT;
