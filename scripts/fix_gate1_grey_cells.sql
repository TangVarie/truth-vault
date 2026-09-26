-- ════════════════════════════════════════════════════════════════════
-- scripts/fix_gate1_grey_cells.sql · 一次性数据修复（D-085, 2026-09-24）
-- ════════════════════════════════════════════════════════════════════
--
-- 修什么: 闸一 C 表 (extractor = jev:1.13.0-C, run_tag = gate1-20260928) 里 NUC_phase1_recv46LaDAdFFc
--   那 11 个灰格的答案。名单 (data-analysis/gate1-human-sample-2026-09-28.csv 第 90 行) 说这 11 题
--   这篇【不问】—— 正文不足 20 个可见字, TV 自己的 pass 对这 11 题记的是 NULL + text_too_short;
--   但 build_gate1_human_sheets.py 用 "|" 拼名单、ingest_gate1_answers.py 用 "," 拆, 11 个题号被拆成
--   一个认不出的长串, 灰格校验两个方向都失效, Jev 在灰格里填的答案原样入了库 (C 表 1000 行, 应为 989;
--   D-081 记的 999 / 999 / 1000 就是这么来的)。脚本已修 (D-085), 这里修已经落库的那 11 行。
--
-- 怎么修: 按 TV 账本「无效行」的口径标掉 —— answer / prob 置 NULL, invalid_reason = 'text_too_short'
--   (与 TV 自己的 pass 对同一篇同一题给的原因同一个值, 读账本的人和脚本按现有闭集就读得懂)。
--   不删行: 来历留在本文件与 D-085。原来的答案改之前逐行 RAISE NOTICE 打出来 (执行日志就是备份)。
--   只动这一篇 × 这一个 extractor × 这一个 run_tag × 这 11 题; A / B 两张表 (单灰格那篇按 "," 拆也对)
--   和 TV 自己的行一行不碰。
--
-- 幂等: 只改 answer IS NOT NULL 的行; 第二遍 0 行 (NOTICE 会说「已修过」)。
-- 保险: 要改的行 > 11 就整份回滚、什么都不改 —— 说明库里的形状和 D-081 记的不一样, 先人工看。
--
-- 谁来跑、怎么跑 (owner; 本仓 CI 不跑它, 也不要接进任何 workflow):
--   Supabase SQL 编辑器 / MCP execute_sql 整份贴进去执行, 或
--   psql -d <shared_supabase> -v ON_ERROR_STOP=1 -f scripts/fix_gate1_grey_cells.sql
--   跑完看 NOTICE: 第一遍「标掉 11 行」, 第二遍「0 行 (已修过 11 行)」。
--   事后核对: SELECT count(*) FROM truth_vault.note_feature_answers
--             WHERE extractor = 'jev:1.13.0-C' AND run_tag = 'gate1-20260928' AND answer IS NOT NULL;   -- 期望 989
-- 前置: notes_v1_13 (表在)。与 v1_17 / v1_18 无先后。
-- ════════════════════════════════════════════════════════════════════

DO $$
DECLARE
    v_subject   CONSTANT text   := 'NUC_phase1_recv46LaDAdFFc';
    v_extractor CONSTANT text   := 'jev:1.13.0-C';
    v_run_tag   CONSTANT text   := 'gate1-20260928';
    v_reason    CONSTANT text   := 'text_too_short';
    -- 名单第 90 行 skipped_questions 原样 (11 题)
    v_qs        CONSTANT text[] := ARRAY['opening_type', 'has_specific_time', 'has_specific_place',
                                         'has_direct_quote', 'has_body_sensation', 'ending_asks_reader',
                                         'withholds_product_name', 'own_experience', 'turning_point',
                                         'judged_by_others', 'negative_outcome_happened'];
    r        record;
    n_todo   int;
    n_done   int;
    n_fixed  int;
BEGIN
    SELECT count(*) FILTER (WHERE answer IS NOT NULL),
           count(*) FILTER (WHERE answer IS NULL AND invalid_reason = v_reason)
      INTO n_todo, n_done
      FROM truth_vault.note_feature_answers
     WHERE subject_type = 'note' AND subject_id = v_subject
       AND extractor = v_extractor AND run_tag = v_run_tag
       AND question_id = ANY (v_qs);

    IF n_todo > array_length(v_qs, 1) THEN
        RAISE EXCEPTION 'gate1 灰格修复: 要改 % 行, 超过预期的 % 行 —— 库里的形状和 D-081 记的不一样, 什么都没改, 先人工核对',
                        n_todo, array_length(v_qs, 1);
    END IF;

    FOR r IN
        SELECT question_id, question_version, answer, prob
          FROM truth_vault.note_feature_answers
         WHERE subject_type = 'note' AND subject_id = v_subject
           AND extractor = v_extractor AND run_tag = v_run_tag
           AND question_id = ANY (v_qs) AND answer IS NOT NULL
         ORDER BY question_id, question_version
    LOOP
        RAISE NOTICE 'gate1 灰格修复: % v% 原答 % (prob %) → NULL / %',
                     r.question_id, r.question_version, r.answer, r.prob, v_reason;
    END LOOP;

    UPDATE truth_vault.note_feature_answers
       SET answer = NULL, prob = NULL, invalid_reason = v_reason
     WHERE subject_type = 'note' AND subject_id = v_subject
       AND extractor = v_extractor AND run_tag = v_run_tag
       AND question_id = ANY (v_qs) AND answer IS NOT NULL;
    GET DIAGNOSTICS n_fixed = ROW_COUNT;

    RAISE NOTICE 'gate1 灰格修复 (D-085): 标掉 % 行 (之前已修过 % 行); % × % × %',
                 n_fixed, n_done, v_subject, v_extractor, v_run_tag;
END $$;
