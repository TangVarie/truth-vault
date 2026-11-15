-- check_reader_comments_observations.sql —— schemas/notes_v1_27_reader_comments_observations.sql 的 CI 夹具 (D-155; ci.yml sql job 调,
-- 迁移已经跑过两遍之后)。psql -v ON_ERROR_STOP=1 -f scripts/check_reader_comments_observations.sql, 在仓库根目录跑 (\i 用相对路径)。
-- 夹具全是合成的 (CI_V27 前缀), 最后删干净 (含 audit_log)。
--
-- 守的是:
--   · comments 三列在、可空、老写法 (不带这三列) 照样写得进; 重跑迁移不动已有行的值。
--   · v_note_observations: 只出四个指标至少一个变了的北京日; 同一天改两次留最后一次; 没变的指标带着上一次的值和上一次变的那天;
--     audit 里没改过的指标用之后第一次改它那行的旧值、「哪天变的」是 NULL。
--   · 评论数的观测时刻: 「巡查状态」= 正常 才用「最近检查时间」; 巡查失败那几天是 NULL (哪怕「最近检查时间」推进了);
--     有「评论数观测时间」(顶层或 _undeclared) 就用它。
--   · metric_snapshots 的两列注释说了「不是量到的时刻」。
-- 反证 (改坏迁移之后必须红):
--   · 视图里去掉 w2.st #>> '{}' = '正常' 那个条件 → 「巡查失败那天观测时刻应为空」红;
--   · 两个 CASE 调换先后 (先看最近检查时间) → 「有评论数观测时间就用它」红;
--   · dl 的 ORDER BY 去掉 occurred_at DESC → 「同一天改两次留最后一次」红;
--   · w2 里去掉 ELSE w1.imp_fo → 「没改过的指标用之后第一次的旧值」红;
--   · 最后的 WHERE 去掉 → 「只有巡查列变了的那天不该出行」红。

INSERT INTO truth_vault.projects (project_id, brand, product, category) VALUES ('CI_V27', 'b', 'p', '保健品');
INSERT INTO truth_vault.notes (note_id, project_id, raw_content) VALUES
    ('CI_V27_a', 'CI_V27', '合成正文甲'), ('CI_V27_b', 'CI_V27', '合成正文乙');

-- ── comments 三列 ──
INSERT INTO truth_vault.comments (comment_id, note_id, project_id, content, comment_role)
    VALUES ('CI_V27_a_c1', 'CI_V27_a', 'CI_V27', '合成的运营评论', '素人');
INSERT INTO truth_vault.comments (comment_id, note_id, project_id, content, comment_role, source, is_truncated, observed_at, is_scripted)
    VALUES ('CI_V27_a_lcd1', 'CI_V27_a', 'CI_V27', '合成的读者评论', '路人', 'linkcheck_digest', true, '2026-11-02 08:00+00', NULL);

DO $$
DECLARE
    bad text;
BEGIN
    SELECT string_agg(column_name || ':' || data_type || ':' || is_nullable, ',' ORDER BY column_name) INTO bad
      FROM information_schema.columns
     WHERE table_schema = 'truth_vault' AND table_name = 'comments' AND column_name IN ('source', 'is_truncated', 'observed_at');
    IF bad IS DISTINCT FROM 'is_truncated:boolean:YES,observed_at:timestamp with time zone:YES,source:text:YES' THEN
        RAISE EXCEPTION 'v1.27: comments 三列不对 [%]', bad;
    END IF;
    IF (SELECT source FROM truth_vault.comments WHERE comment_id = 'CI_V27_a_c1') IS NOT NULL THEN
        RAISE EXCEPTION 'v1.27: 老写法写进去的行 source 应为空';
    END IF;
    IF coalesce(col_description('truth_vault.metric_snapshots'::regclass,
                                (SELECT attnum FROM pg_attribute WHERE attrelid = 'truth_vault.metric_snapshots'::regclass
                                                                   AND attname = 'collected_at')), '') NOT LIKE '%不是%'
       OR coalesce(col_description('truth_vault.metric_snapshots'::regclass,
                                   (SELECT attnum FROM pg_attribute WHERE attrelid = 'truth_vault.metric_snapshots'::regclass
                                                                      AND attname = 'window_label')), '') NOT LIKE '%不是%' THEN
        RAISE EXCEPTION 'v1.27: metric_snapshots 的 collected_at / window_label 注释没说它不是量到的时刻';
    END IF;
END $$;

-- ── v_note_observations: 触发器给夹具行记的 audit 删掉, 按时间线手写 (occurred_at 是 UTC 无时区, 同生产) ──
DELETE FROM truth_vault.audit_log WHERE row_id LIKE 'CI\_V27%';
-- 毫秒: 11-01 09:00Z = 1793523600000 · 11-02 08:00Z = 1793606400000 · 11-03 08:00Z = 1793692800000
--       11-05 03:00Z = 1793847600000 · 11-05 06:00Z = 1793858400000
INSERT INTO truth_vault.audit_log (schema_name, table_name, row_id, operation, changed_cols, occurred_at) VALUES
    -- 甲 · 11-01 入库: 评论数 5, 巡查正常
    ('truth_vault', 'notes', 'CI_V27_a', 'INSERT',
     '{"note_id": "CI_V27_a", "comments_count": 5, "impressions": null, "reads": null, "interactions": null,
       "raw_extra": {"巡查状态": "正常", "最近检查时间": 1793523600000}}', '2026-11-01 10:00'),
    -- 甲 · 11-02 评论数 5 → 9, 巡查正常, 检查时间推进
    ('truth_vault', 'notes', 'CI_V27_a', 'UPDATE',
     '{"comments_count": [5, 9],
       "raw_extra": [{"巡查状态": "正常", "最近检查时间": 1793523600000}, {"巡查状态": "正常", "最近检查时间": 1793606400000}]}',
     '2026-11-02 10:00'),
    -- 甲 · 11-03 只有巡查列变: 刷新失败, 检查时间照样推进 → 这天不该出行
    ('truth_vault', 'notes', 'CI_V27_a', 'UPDATE',
     '{"raw_extra": [{"巡查状态": "正常", "最近检查时间": 1793606400000}, {"巡查状态": "刷新失败", "最近检查时间": 1793692800000}]}',
     '2026-11-03 10:00'),
    -- 甲 · 11-04 运营截图读出曝光 / 阅读; raw_extra 没变
    ('truth_vault', 'notes', 'CI_V27_a', 'UPDATE', '{"impressions": [null, 600], "reads": [null, 43]}', '2026-11-04 10:00'),
    -- 甲 · 11-05 同一天改两次 (9 → 11 → 12); 第二次带「评论数观测时间」(在 _undeclared 里), 巡查恢复正常
    ('truth_vault', 'notes', 'CI_V27_a', 'UPDATE', '{"comments_count": [9, 11]}', '2026-11-05 02:00'),
    ('truth_vault', 'notes', 'CI_V27_a', 'UPDATE',
     '{"comments_count": [11, 12],
       "raw_extra": [{"巡查状态": "刷新失败", "最近检查时间": 1793692800000},
                     {"巡查状态": "正常", "最近检查时间": 1793858400000, "_undeclared": {"评论数观测时间": 1793847600000}}]}',
     '2026-11-05 10:00'),
    -- 乙 · audit 里没有入库那一行: 11-02 互动 3 → 7; 11-04 曝光 100 → 150
    ('truth_vault', 'notes', 'CI_V27_b', 'UPDATE', '{"interactions": [3, 7]}', '2026-11-02 10:00'),
    ('truth_vault', 'notes', 'CI_V27_b', 'UPDATE', '{"impressions": [100, 150]}', '2026-11-04 10:00');

CREATE TEMP TABLE ci_v27_got AS
SELECT note_id || '|' || cn_day || '|' || array_to_string(changed_today, '+')
       || '|cc=' || coalesce(comments_count::text, '-') || '@' || coalesce(comments_changed_cn_day::text, '-')
       || '|obs=' || coalesce(to_char(comments_observed_at_cn, 'MM-DD HH24:MI'), '-') || '/' || coalesce(comments_observed_source, '-')
       || '|st=' || coalesce(patrol_status, '-')
       || '|imp=' || coalesce(impressions::text, '-') || '@' || coalesce(impressions_changed_cn_day::text, '-')
       || '|rd=' || coalesce(reads::text, '-') || '@' || coalesce(reads_changed_cn_day::text, '-')
       || '|it=' || coalesce(interactions::text, '-') || '@' || coalesce(interactions_changed_cn_day::text, '-') AS line,
       note_id, cn_day
FROM truth_vault.v_note_observations WHERE note_id LIKE 'CI\_V27%';

DO $$
DECLARE
    got text;
    want text[] := ARRAY[
        -- 入库那天: 四项都算「变了」; 巡查正常 → 观测时刻 = 最近检查时间 (11-01 09:00Z = 北京 17:00)
        'CI_V27_a|2026-11-01|comments_count+impressions+reads+interactions|cc=5@2026-11-01|obs=11-01 17:00/最近检查时间(巡查状态=正常)|st=正常|imp=-@2026-11-01|rd=-@2026-11-01|it=-@2026-11-01',
        'CI_V27_a|2026-11-02|comments_count|cc=9@2026-11-02|obs=11-02 16:00/最近检查时间(巡查状态=正常)|st=正常|imp=-@2026-11-01|rd=-@2026-11-01|it=-@2026-11-01',
        -- 11-03 不出行。11-04: 评论数还是 11-02 的 9; 那一刻巡查是失败的 → 观测时刻空
        'CI_V27_a|2026-11-04|impressions+reads|cc=9@2026-11-02|obs=-/-|st=刷新失败|imp=600@2026-11-04|rd=43@2026-11-04|it=-@2026-11-01',
        -- 11-05: 留最后一次 (12); 有「评论数观测时间」(11-05 03:00Z = 北京 11:00) 就用它, 不用最近检查时间 (北京 14:00)
        'CI_V27_a|2026-11-05|comments_count|cc=12@2026-11-05|obs=11-05 11:00/评论数观测时间|st=正常|imp=600@2026-11-04|rd=43@2026-11-04|it=-@2026-11-01',
        -- 乙: 11-02 那天曝光在 audit 里还没改过 → 用 11-04 那行的旧值 100, 「哪天变的」空; 没有巡查列 → 观测时刻空
        'CI_V27_b|2026-11-02|interactions|cc=-@-|obs=-/-|st=-|imp=100@-|rd=-@-|it=7@2026-11-02',
        'CI_V27_b|2026-11-04|impressions|cc=-@-|obs=-/-|st=-|imp=150@2026-11-04|rd=-@-|it=7@2026-11-02'];
    i int;
BEGIN
    SELECT string_agg(line, E'\n' ORDER BY note_id, cn_day) INTO got FROM ci_v27_got;
    IF got IS DISTINCT FROM array_to_string(want, E'\n') THEN
        FOR i IN 1 .. array_length(want, 1) LOOP
            IF NOT EXISTS (SELECT 1 FROM ci_v27_got WHERE line = want[i]) THEN
                RAISE WARNING 'v1.27 缺这一行: %', want[i];
            END IF;
        END LOOP;
        RAISE EXCEPTION E'v1.27: v_note_observations 对不上 (只有巡查列变了的那天不该出行 / 同一天改两次留最后一次 / '
                        '巡查失败那天观测时刻应为空 / 有评论数观测时间就用它 / 没改过的指标用之后第一次的旧值)。实际:\n%', got;
    END IF;
END $$;

\i schemas/notes_v1_27_reader_comments_observations.sql

DO $$
DECLARE
    got text;
BEGIN
    SELECT string_agg(comment_id || ':' || coalesce(source, '-') || ':' || coalesce(is_truncated::text, '-')
                      || ':' || coalesce(to_char(observed_at AT TIME ZONE 'UTC', 'MM-DD HH24:MI'), '-'), ',' ORDER BY comment_id)
      INTO got FROM truth_vault.comments WHERE note_id = 'CI_V27_a';
    IF got IS DISTINCT FROM 'CI_V27_a_c1:-:-:-,CI_V27_a_lcd1:linkcheck_digest:true:11-02 08:00' THEN
        RAISE EXCEPTION 'v1.27: 重跑迁移改了已有评论行 [%]', got;
    END IF;
    IF (SELECT count(*) FROM truth_vault.v_note_observations WHERE note_id LIKE 'CI\_V27%') <> 6 THEN
        RAISE EXCEPTION 'v1.27: 重跑迁移之后视图行数变了';
    END IF;
    DELETE FROM truth_vault.notes WHERE project_id = 'CI_V27';
    DELETE FROM truth_vault.projects WHERE project_id = 'CI_V27';
    DELETE FROM truth_vault.audit_log WHERE row_id LIKE 'CI\_V27%';
    IF EXISTS (SELECT 1 FROM truth_vault.comments WHERE comment_id LIKE 'CI\_V27%')
       OR EXISTS (SELECT 1 FROM truth_vault.audit_log WHERE row_id LIKE 'CI\_V27%') THEN
        RAISE EXCEPTION 'v1.27: 夹具没删干净';
    END IF;
    RAISE NOTICE '✓ v1.27: comments 三列可空、老写法照写、重跑不动已有行; v_note_observations 只出指标变了的天、留当天最后一次、'
                 '巡查失败不给观测时刻、有评论数观测时间优先、没改过的指标用之后第一次的旧值; metric_snapshots 注释已改';
END $$;
