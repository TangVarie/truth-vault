-- check_owner_sql_b2.sql · 两份 owner 数据 SQL 的夹具测试 (列体检 2026-11-25 / I-17)。CI 的 sql job 在 v1_24 / v1_27 之后跑一行:
--   psql -v ON_ERROR_STOP=1 -q -f scripts/check_owner_sql_b2_setup.sql -f schemas/notes_v1_31_commenter_codes_cleanup.sql \
--        -f schemas/notes_v1_33_direction_switch_restore.sql -f scripts/check_owner_sql_b2.sql
-- setup 铺夹具, 中间两个 -f 是两份 owner SQL 的第一遍 (批 1 的部署清单守卫 §3 要在 ci.yml 里看到 `-f schemas/...`);
-- 本文件记下第一遍的备份时刻, 用 \i 把两份各再跑一遍 (幂等), 然后核对, 最后删干净, 三张备份表也 drop 掉。
-- 单独跑本文件会红 (没有夹具)。
--
-- v1_31 (假评论): 认得出 旧键 _comment_text_persona 和新键 _commenter_codes 里的带字母编号; 编号在随贴评论原文里出现过的、
--   纯数字的、巡查来的 (source 不为空)、别的项目的 一行不碰; 账本行跟着删、别的账本行不碰; 备份 2 行评论 + 2 行账本;
--   跑第二遍什么都不变。
-- v1_33 (I-17 Step 2): BJS_phase2 只剩款式标、旧方向抬得了、库里是旧方向的值、essence 改过 → 换成 essence 的值 (b1);
--   「提问贴 + 款」抬得了 → 不碰 (b2); essence 那一次没改 content_format → 不换、只备份 (b3); 库里已经是 essence 的值 → 不碰 (b4);
--   库里的值不是旧方向抬的值 (后来手改过) → 不碰、不备份 (b5); 两次改方向 + 两次 essence 写 → 认最后一次改方向、
--   essence 最后一次写的值 (b6); 早一次 essence 改过、最后一次没改 → 不换 (b7); HATHERINE 单值方向同样认 (h1);
--   备份只补一次 (第二遍 backed_up_at 不变)。
-- 反证 (11-25 实跑 16 条, 改坏之后都红):
--   v1_31: 去掉「编号在原文里出现过就不删」/ 去掉 source 为空 / 纯数字也删 / 不限项目 / 账本不限假评论 /
--          不认新键 _commenter_codes → ① 红;
--   v1_33: 去掉 i17_ign → b2 被换, ② 红; 去掉「库里的值 = 旧方向抬的值」→ b5 被换, ② 红;
--          essence 取最早一次写 → b6 换成 认知重构, ② 红; 取第一次改方向 → b6 不换, ② 红;
--          essence 只看改过 content_format 的那几次 → b7 被换, ② 红; 不看 essence 那次改没改 → b3 / b7 换成 NULL, ② 红;
--          备份每遍都插 → ③ 红; 顺手清人群 → ② 红。
--   v1_32 那两条 (夹具不设 want_flag / flag 改回 unknown) 在 check_paid_boost_v1_32.sql 那一步红。

\set QUIET on
\set ON_ERROR_STOP 1

CREATE TEMP TABLE cib2_first AS SELECT note_id, backed_up_at FROM truth_vault.backup_notes_i17_20261125;
\i schemas/notes_v1_31_commenter_codes_cleanup.sql
\i schemas/notes_v1_33_direction_switch_restore.sql

DO $$
DECLARE left_ids text[];
BEGIN
    SELECT array_agg(comment_id ORDER BY comment_id) INTO left_ids FROM truth_vault.comments WHERE comment_id LIKE 'CIB2\_%';
    IF left_ids IS DISTINCT FROM ARRAY['CIB2_n1_c1', 'CIB2_n2_c1', 'CIB2_n4_c1', 'CIB2_n5_c1', 'CIB2_n6_c1'] THEN
        RAISE EXCEPTION '① v1_31 删错了: 剩下 %', left_ids;
    END IF;
    IF (SELECT count(*) FROM truth_vault.note_feature_answers WHERE subject_id LIKE 'CIB2\_%') <> 1
       OR NOT EXISTS (SELECT 1 FROM truth_vault.note_feature_answers WHERE subject_id = 'CIB2_n1_c1') THEN
        RAISE EXCEPTION '① v1_31 账本: 只该删假评论那两行';
    END IF;
    IF (SELECT count(*) FROM truth_vault.backup_comments_commenter_20261125) <> 2
       OR (SELECT count(*) FROM truth_vault.backup_nfa_commenter_20261125) <> 2 THEN
        RAISE EXCEPTION '① v1_31 备份该是 2 行评论 + 2 行账本 (跑两遍也一样)';
    END IF;
    IF obj_description('truth_vault.backup_comments_commenter_20261125'::regclass) NOT LIKE '%回滚%' THEN
        RAISE EXCEPTION '① v1_31 备份表要有回滚 SQL 的 COMMENT';
    END IF;
    RAISE NOTICE '✓ v1_31: 新旧两个键的带字母编号删掉 (2 行), 原文里有的 / 纯数字 / 巡查来的 / 别的项目不碰; 账本跟着删 2 行; 跑两遍一样';
END $$;

DO $$
DECLARE got jsonb; bk text[];
BEGIN
    SELECT jsonb_object_agg(note_id, content_format) INTO got FROM truth_vault.notes WHERE note_id LIKE 'CIB2\_b%' OR note_id LIKE 'CIB2\_h%' OR note_id LIKE 'CIB2\_s%';
    IF got IS DISTINCT FROM '{"CIB2_b1": "情感叙事", "CIB2_b2": "提问求助", "CIB2_b3": "场景植入", "CIB2_b4": "情感叙事",
                              "CIB2_b5": "反差破圈", "CIB2_b6": "情感叙事", "CIB2_b7": "场景植入",
                              "CIB2_h1": "教程攻略", "CIB2_s1": "提问求助"}'::jsonb THEN
        RAISE EXCEPTION '② v1_33 content_format 不对: %', got;
    END IF;
    IF EXISTS (SELECT 1 FROM truth_vault.notes WHERE note_id IN ('CIB2_b1', 'CIB2_b3', 'CIB2_h1', 'CIB2_s1')
                AND target_audience IS NULL) THEN
        RAISE EXCEPTION '② v1_33 不该动人群 (那是夜跑的事)';
    END IF;
    SELECT array_agg(note_id || ':' || reason ORDER BY note_id) INTO bk FROM truth_vault.backup_notes_i17_20261125;
    IF bk IS DISTINCT FROM ARRAY['CIB2_b1:content_format_restore+profile_clear_next_nightly', 'CIB2_b3:profile_clear_next_nightly',
                                 'CIB2_b6:content_format_restore+profile_clear_next_nightly',
                                 'CIB2_h1:content_format_restore+profile_clear_next_nightly', 'CIB2_s1:profile_clear_next_nightly'] THEN
        RAISE EXCEPTION '③ v1_33 备份不对: %', bk;
    END IF;
    IF EXISTS (SELECT 1 FROM truth_vault.backup_notes_i17_20261125 b WHERE note_id = 'CIB2_b1'
                AND (content_format <> '场景植入' OR target_audience <> '{宝妈,通用}' OR user_pain_point <> 'p')) THEN
        RAISE EXCEPTION '③ v1_33 备份要存改之前的值';
    END IF;
    IF EXISTS (SELECT 1 FROM truth_vault.backup_notes_i17_20261125 b JOIN cib2_first f USING (note_id)
                WHERE b.backed_up_at IS DISTINCT FROM f.backed_up_at)
       OR (SELECT count(*) FROM cib2_first) <> 5 THEN
        RAISE EXCEPTION '③ v1_33 跑第二遍不该覆盖第一次的备份';
    END IF;
    RAISE NOTICE '✓ v1_33: 款式标去掉之后抬不了 + 旧方向的值 + essence 改过 → 换回 (BJS 多选 / HATHERINE 单值; 认最后一次改方向和最后一次 essence); 抬得了的 / essence 最后没改的 / 已是 essence 的 / 库里不是旧方向值的不换; 备份 5 篇只补一次';
END $$;

-- ═══ 收尾 ═══════════════════════════════════════════════════════════════
DELETE FROM truth_vault.note_feature_answers WHERE subject_id LIKE 'CIB2\_%';
DELETE FROM truth_vault.comments WHERE comment_id LIKE 'CIB2\_%';
DELETE FROM truth_vault.notes WHERE note_id LIKE 'CIB2\_%';
DELETE FROM truth_vault.audit_log WHERE row_id LIKE 'CIB2\_%';
DROP TABLE truth_vault.backup_comments_commenter_20261125;
DROP TABLE truth_vault.backup_nfa_commenter_20261125;
DROP TABLE truth_vault.backup_notes_i17_20261125;
DELETE FROM truth_vault.audit_log WHERE table_name = 'projects'
   AND row_id IN ('NUC_phase1', 'NRT_phase2', 'HXZ_FB', 'BJS_phase2', 'HATHERINE_phase1', 'SPX_phase1');
DELETE FROM truth_vault.projects WHERE project_id IN ('NUC_phase1', 'NRT_phase2', 'HXZ_FB', 'BJS_phase2', 'HATHERINE_phase1', 'SPX_phase1')
   AND NOT EXISTS (SELECT 1 FROM truth_vault.notes n WHERE n.project_id = projects.project_id);
DO $$ BEGIN RAISE NOTICE '✓ check_owner_sql_b2.sql: all checks passed (夹具已清)'; END $$;
