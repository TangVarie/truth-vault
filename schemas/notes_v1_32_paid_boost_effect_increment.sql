-- truth_vault v1.32 · 投流证据链: 「维护效果」的口径标成 increment (G-15 的那一处小改, 2026-11-25)
-- ════════════════════════════════════════════════════════════════════
-- 改什么: 只重建一个视图 truth_vault.v_paid_boost_events。ops_effect_metric_flag 从一律 unknown 改成 increment。
--   别的列、行数、列的顺序和类型都不变; 别的视图、函数、表一概不动。
-- 为什么: D-133 第 5 条写「metric_flag 一律 unknown, 等运营答 O-06」。11-02 对旧答复时发现运营 09-17 / 09-22 早答了:
--   「维护效果」= 投流后的曝光增量, 12h 是读数的时刻 (D-136 第 5 条; OPEN-ITEMS G-15 / O-06)。列体检 11-25 §3a #4。
-- 排除: XIWU_phase2 有 1 行「维护情况」= 一轮维护 / 二轮维护,「维护效果」= 20条评论 / +20条评论 —— 是铺评条数, 不是投流。
--   它不是纯数字, 在 v_paid_marker_elements 里是 ops_effect_not_numeric, 本来就不进事件, 所以也不会被标成 increment。
--   CI 夹具 scripts/check_paid_boost_v1_32.sql 钉着这一条。
-- 生产只读 (11-25): 事件 47 行 (43 篇)。其中 37 行 (33 篇) 有 ops_effect_raw, flag 从 unknown 变 increment; 其余 10 行 (🍟 事件) 仍是 NULL。
--   行数不变。读这一列的只有人和读数报告 (v_paid_boost_evidence 原样转出), 没有代码按它分支。
-- 安全重跑: 只有 CREATE OR REPLACE VIEW 和 COMMENT, 跑几遍结果都一样; 不写任何表, 不用备份。
-- 顺序: 在 notes_v1_22 之后跑。以后谁重跑了 v1_22 (它会把 flag 改回 unknown), 要再跑一遍本文件。
-- 回滚: 重跑 schemas/notes_v1_22_paid_boost_evidence.sql (只建函数和视图, 幂等)。
-- 跑完回读 (文件末尾自带): flag 的取值分布; increment 的行数应等于有 ops_effect_raw 的行数。
-- ════════════════════════════════════════════════════════════════════

CREATE OR REPLACE VIEW truth_vault.v_paid_boost_events AS
WITH el AS MATERIALIZED (
    SELECT * FROM truth_vault.v_paid_marker_elements
    WHERE outcome = 'event' OR (class = 'ops_date' AND outcome = 'excluded')
),
ev AS (
    SELECT note_id, project_id, parsed_date AS boost_date,
           array_agg(DISTINCT CASE WHEN class = 'paid_dated' THEN '🍟前日期' ELSE '维护时间' END) AS date_sources,
           array_agg(DISTINCT year_rule) AS year_rules,
           array_agg(DISTINCT source_col) AS marker_cols,
           array_agg(raw_elem ORDER BY source_col, ord) AS marker_raw,
           jsonb_agg(paired_effect ORDER BY ord) FILTER (WHERE paired_effect IS NOT NULL) AS ops_effect_raw,
           array_agg(paired_effect_txt ORDER BY ord) FILTER (WHERE paired_effect_txt IS NOT NULL) AS ops_effect_txt,
           min(first_seen_cn_day) AS first_seen_cn_day
    FROM el
    WHERE outcome = 'event'
    GROUP BY note_id, project_id, parsed_date
),
unpaired AS (
    SELECT DISTINCT note_id, parsed_date
    FROM el
    WHERE class = 'ops_date' AND outcome = 'excluded' AND parsed_date IS NOT NULL
),
x AS (
    SELECT ev.*, n.impressions, n.data_quality_flags,
           (n.publish_time + interval '8 hours')::date AS publish_cn_date,
           truth_vault.tv_raw_cell(n.raw_extra, '起量时间') AS takeoff_cell,
           (now() AT TIME ZONE 'Asia/Shanghai')::date AS today_cn,
           CASE WHEN cardinality(ev.ops_effect_txt) = 1 THEN ev.ops_effect_txt[1]::numeric END AS ops_effect_value
    FROM ev
    JOIN truth_vault.notes n ON n.note_id = ev.note_id
)
SELECT x.note_id || '@' || to_char(x.boost_date, 'YYYY-MM-DD') AS event_id,
       x.note_id, x.project_id, x.boost_date,
       x.date_sources, x.year_rules, x.marker_cols, x.marker_raw,
       x.publish_cn_date,
       x.boost_date - x.publish_cn_date AS days_after_publish,
       x.first_seen_cn_day,
       tk.d AS takeoff_cn_date,
       CASE WHEN x.takeoff_cell IS NULL THEN 'missing'
            WHEN tk.problem IS NOT NULL THEN 'invalid:' || tk.problem
            WHEN tk.d < x.boost_date THEN 'before'
            WHEN tk.d <= x.boost_date + 7 THEN 'in_window'
            ELSE 'after' END AS takeoff_vs_window,
       CASE x.data_quality_flags -> 'paid_promoted'
            WHEN 'true'::jsonb THEN 'yes' WHEN 'false'::jsonb THEN 'no' ELSE 'unknown' END AS paid_promoted_state,
       CASE WHEN jsonb_typeof(x.data_quality_flags -> 'comment_maintained_seeded') = 'number'
            THEN (x.data_quality_flags ->> 'comment_maintained_seeded')::numeric END AS comment_maintained_seeded,
       EXISTS (SELECT 1 FROM unpaired u WHERE u.note_id = x.note_id AND u.parsed_date = x.boost_date) AS ops_date_agrees,
       x.note_id IN (SELECT v.note_id FROM truth_vault.v_notes_vanished v) AS vanished,
       -- ops_* 自成一块: 运营自报的「维护效果」, 不进任何增量 (口径见下面 11-02 那条)
       x.ops_effect_raw,
       x.ops_effect_value,
       -- 11-02 运营口径 (O-06 关, D-136 第 5 条): 「维护效果」= 投流后的曝光增量, 12h 是读数的时刻, 不是另一种口径。
       -- ops_effect_raw 只收「配上了日期的纯数字」, 所以 XIWU_phase2 那行「一轮 / 二轮维护」+「20条评论」(铺评条数) 进不来,
       -- 这里不用另写排除 (它在元素视图里是 ops_effect_not_numeric)。
       CASE WHEN x.ops_effect_raw IS NULL THEN NULL ELSE 'increment' END AS ops_effect_metric_flag,
       CASE WHEN x.ops_effect_value IS NULL THEN NULL
            WHEN x.impressions IS NULL THEN 'impressions_missing'
            WHEN x.ops_effect_value > x.impressions THEN 'exceeds'
            ELSE 'ok' END AS ops_effect_vs_current_impressions
FROM x
LEFT JOIN LATERAL truth_vault.tv_parse_ops_date(x.takeoff_cell, x.publish_cn_date, x.today_cn) AS tk ON x.takeoff_cell IS NOT NULL;

COMMENT ON VIEW truth_vault.v_paid_boost_events IS
    '投流证据链 F1 (D-133): 一篇一个投流日一行, event_id = note_id@日期。日期来源 🍟前日期 / 维护时间 (配数字效果); '
    'paid_promoted_state 照抄 data_quality_flags (缺键 = unknown); ops_* 是运营自报的维护效果 = 投流后的曝光增量 '
    '(metric_flag = increment, 11-02 口径, v1_32; 铺评条数那种不是纯数字的进不来), 只并排给, 不进前后读数的增量。';

-- ── 回读 ─────────────────────────────────────────────────────────────
SELECT coalesce(ops_effect_metric_flag, '(NULL)') AS ops_effect_metric_flag, count(*) AS events,
       count(*) FILTER (WHERE ops_effect_raw IS NOT NULL) AS with_ops_effect
FROM truth_vault.v_paid_boost_events
GROUP BY 1 ORDER BY 1;
