-- 书架账号项换前换后对照 (G-06, 只读)。在 notes_v1_34 跑过之后用: 旧排序从视图自己的两列反推
-- (旧账号项 = account_bao_rate × 0.3, 新账号项 = 0.3 × (1 − account_prior)), 不用另存旧视图。
-- 只出计数、名次和项目代号, 不出帖子 id 和正文。馆员常驻 = 前 8 张 (librarian/core.py SHORTLIST_GLOBAL_KEEP)。
-- 11-25 在生产只读试算 (v1_34 还没跑, 新排序按文件里的视图定义现算) 的结果记在 G-06 的 D 条目里。
WITH v AS (
    SELECT source_note_id, project_id, tier, account_prior, account_prior_n, account_bao_rate,
           rank_score                                                                  AS rs_new,
           rank_score - 0.3 * (1 - account_prior) + account_bao_rate * 0.3             AS rs_old
    FROM truth_vault.v_flywheel_lesson_cards
),
r AS (
    SELECT *, row_number() OVER (ORDER BY rs_old DESC, source_note_id) AS rk_old,
              row_number() OVER (ORDER BY rs_new DESC, source_note_id) AS rk_new
    FROM v
)
SELECT * FROM (
SELECT 'summary' AS part, NULL::bigint AS rk_old, NULL::bigint AS rk_new, NULL AS project_id, NULL AS tier,
       json_build_object('cards', count(*),
                         'top20_kept', count(*) FILTER (WHERE rk_old <= 20 AND rk_new <= 20),
                         'top8_kept',  count(*) FILTER (WHERE rk_old <= 8 AND rk_new <= 8),
                         'mean_move',  round(avg(abs(rk_old - rk_new)), 1),
                         'max_move',   max(abs(rk_old - rk_new)),
                         'moved_gt50', count(*) FILTER (WHERE abs(rk_old - rk_new) > 50),
                         'no_earlier_labels', count(*) FILTER (WHERE account_prior_n = 0))::text AS detail
FROM r
UNION ALL
SELECT 'top20_old', rk_old, rk_new, project_id, tier,
       json_build_object('n_prev', account_prior_n, 'prior', round(account_prior::numeric, 3))::text
FROM r WHERE rk_old <= 20
UNION ALL
SELECT 'top20_new', rk_old, rk_new, project_id, tier,
       json_build_object('n_prev', account_prior_n, 'prior', round(account_prior::numeric, 3))::text
FROM r WHERE rk_new <= 20
) t
ORDER BY part, CASE WHEN part = 'top20_old' THEN rk_old ELSE rk_new END;
