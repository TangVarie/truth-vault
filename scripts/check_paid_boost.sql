-- check_paid_boost.sql · 投流证据链 F1/F2 的 SQL 侧守卫 (D-133)。CI 的 sql job 在 v1_22 apply 两遍之后跑:
--   psql -v ON_ERROR_STOP=1 -v cases="$(cat scripts/check_paid_boost_cases.json)" -f scripts/check_paid_boost.sql
-- 夹具和 scripts/check_paid_boost.py 共用一份 (Python 判据 / transform_row 跑同一批格子和整行)。
-- 任何一条对不上 → RAISE EXCEPTION → psql 非零退出 → 这一步红。夹具行全带 CI_V22 前缀, 最后删干净 (含 audit_log)。
--
-- (a) 元素判据 parity: 每个格子拆元素 + 定类 + 解析日期, 和夹具写的一致 (同一份 JSON, Python 那边逐字比过常量)
-- (b) 事件集合、隔离集合【逐条相等】(多一条少一条都红)
-- (c) 划分: 夹具里 paid_promoted=true 的每一篇, 不在事件里就在隔离里
-- (d) 陷阱 (RIO 帐号昵称 / ANSHEN 现版 + 历史版评论区快照 / XIWU_phase2 评论区快照 / NUC 标题正文 / paid_promoted_reason) 三张视图 0 行
-- (e) 反证: 同一批陷阱用「整块转文本搜 🍟」去扫, 6 篇全中 —— (d) 的 0 行不是因为夹具里本来就没有 🍟
-- (f) F2 时间线: 同日两次读取最后那次 · 投流当天不当基线 · D+1 ok · D+3 只有非完整同步的写 = 缺 · D+7 清空 = value_null ·
--     INSERT 带空键不算基线读数 · 9-18 之前 _undeclared 的「实时数据.评论数」(含数字字符串) · 曝光没变 / 只换 tmp_url = 没重截 ·
--     曝光变了 + 新 file_token = 给值和新 token · v1_9 之前的写 = pre_v1_9_any_write · 进库晚于投流日 = before_history ·
--     最近的投流 = not_due · missing 的值一律 NULL, 夹具里没有一个 0

\set QUIET on
CREATE TEMP TABLE pb_cases AS SELECT :'cases'::jsonb AS j;

-- ═══ (a) 元素判据 parity ═══════════════════════════════════════════════
DO $$
DECLARE
    e jsonb;
    got jsonb;
    want jsonb;
    r record;
    bad text[] := '{}';
    n_dates int := 0;
BEGIN
    FOR e IN SELECT x FROM pb_cases, jsonb_array_elements(j -> 'elements') AS x LOOP
        IF e ->> 'col' = '_tier_source_raw' THEN
            SELECT coalesce(jsonb_agg(jsonb_build_array(x.txt, truth_vault.tv_classify_paid_element(e ->> 'col', x.txt)) ORDER BY x.ord), '[]')
              INTO got FROM truth_vault.tv_pyrepr_elements(e ->> 'tier_repr') x;
        ELSE
            SELECT coalesce(jsonb_agg(jsonb_build_array(x.txt, truth_vault.tv_classify_paid_element(e ->> 'col', x.txt)) ORDER BY x.ord), '[]')
              INTO got FROM truth_vault.tv_cell_elements(e -> 'cell') x;
        END IF;
        SELECT coalesce(jsonb_agg(jsonb_build_array(w -> 0, w -> 1) ORDER BY o), '[]')
          INTO want FROM jsonb_array_elements(e -> 'expect') WITH ORDINALITY AS t(w, o);
        IF got IS DISTINCT FROM want THEN
            bad := bad || format('%s: 期望 %s 实得 %s', e ->> 'id', want, got);
        END IF;
        -- 带日期的类: 解析结果 (日期 / 问题 / 年份规则) 也要对上
        FOR r IN
            SELECT t.w, p.d, p.year_rule, p.problem
            FROM jsonb_array_elements(e -> 'expect') WITH ORDINALITY AS t(w, o)
            JOIN truth_vault.tv_cell_elements(e -> 'cell') x ON x.ord = t.o
            CROSS JOIN LATERAL truth_vault.tv_parse_ops_date(x.elem, (e ->> 'anchor')::date, (e ->> 'today')::date) p
            WHERE jsonb_array_length(t.w) > 2 AND e ->> 'col' <> '_tier_source_raw'
        LOOP
            n_dates := n_dates + 1;
            IF r.d IS DISTINCT FROM (r.w ->> 2)::date OR r.problem IS DISTINCT FROM (r.w ->> 3)
               OR r.year_rule IS DISTINCT FROM (r.w ->> 4) THEN
                bad := bad || format('%s: 「%s」期望 (%s, %s, %s) 实得 (%s, %s, %s)', e ->> 'id', r.w ->> 0,
                                     r.w ->> 2, r.w ->> 3, r.w ->> 4, r.d, r.problem, r.year_rule);
            END IF;
        END LOOP;
    END LOOP;
    IF cardinality(bad) > 0 THEN
        RAISE EXCEPTION E'(a) 元素判据和夹具 (= Python) 不一致:\n%', array_to_string(bad, E'\n');
    END IF;
    IF n_dates < 15 THEN
        RAISE EXCEPTION '(a) 只核了 % 个日期, 夹具里的日期例子没跑到 (空跑)', n_dates;
    END IF;
    RAISE NOTICE '✓ (a) 元素判据: % 个格子拆元素 + 定类和 Python 同一份夹具一致, % 个日期解析对上', (SELECT jsonb_array_length(j -> 'elements') FROM pb_cases), n_dates;
END $$;

-- ═══ 夹具: F1 整行 (CI_V22A_*) —— raw_extra 的拼法和 check_paid_boost.py 的 sql_fixture_raw_extra 一致 ═══
INSERT INTO truth_vault.projects (project_id, brand, product, category) VALUES ('CI_V22', 'b', 'p', '保健品');
INSERT INTO truth_vault.notes (note_id, project_id, title, raw_content, publish_time, raw_extra, data_quality_flags)
SELECT 'CI_V22A_' || (n ->> 'id'), 'CI_V22',
       n -> 'fields' ->> '标题',
       coalesce(n -> 'fields' ->> '文案', 'c'),
       (n ->> 'publish')::date::timestamp - interval '8 hours',
       (SELECT coalesce(jsonb_object_agg(f.key, f.value), '{}')
          FROM jsonb_each(n -> 'fields') f
         WHERE (n -> 'declared') ? f.key)
       || coalesce((SELECT jsonb_build_object('_undeclared', jsonb_object_agg(f.key, f.value))
                      FROM jsonb_each(n -> 'fields') f
                     WHERE NOT (n -> 'declared') ? f.key AND f.key NOT IN ('标题', '文案', '互动量', '状态')
                    HAVING count(*) > 0), '{}')
       || CASE WHEN jsonb_typeof(n -> 'tier_repr') = 'string'
               THEN jsonb_build_object('_tier_source_raw', n ->> 'tier_repr') ELSE '{}' END,
       coalesce(n -> 'dqf_override',
                CASE WHEN jsonb_typeof(n -> 'expect_paid') = 'boolean'
                     THEN jsonb_build_object('paid_promoted', n -> 'expect_paid') END)
FROM pb_cases, jsonb_array_elements(j -> 'notes') AS n;
-- 最近的投流日期在未来 (显式年月日, 不随日历漂): 隔离 date_in_future
INSERT INTO truth_vault.notes (note_id, project_id, raw_content, publish_time, raw_extra) VALUES
  ('CI_V22A_future', 'CI_V22', 'c', (now() AT TIME ZONE 'UTC') - interval '1 day',
   jsonb_build_object('维护时间', jsonb_build_array(to_char((now() AT TIME ZONE 'Asia/Shanghai')::date + 30, 'YYYY/MM/DD')),
                      '维护效果', jsonb_build_array('100')));
-- 触发器给夹具行记的 audit 删掉, 下面按时间线手写 (occurred_at 显式给, 和生产一样是 UTC 无时区)
DELETE FROM truth_vault.audit_log WHERE row_id LIKE 'CI_V22%';
INSERT INTO truth_vault.audit_log (schema_name, table_name, row_id, operation, changed_cols, occurred_at)
SELECT 'truth_vault', 'notes', 'CI_V22A_' || (n ->> 'id'), 'INSERT',
       jsonb_build_object('note_id', 'CI_V22A_' || (n ->> 'id'), 'raw_extra', nt.raw_extra), (n ->> 'first_seen_at')::timestamp
FROM pb_cases, jsonb_array_elements(j -> 'notes') AS n
JOIN truth_vault.notes nt ON nt.note_id = 'CI_V22A_' || (n ->> 'id')
WHERE n ? 'first_seen_at';
-- ANSHEN 历史版: 评论区快照 09-21 带过 🍟, 09-29 换成现版
INSERT INTO truth_vault.audit_log (schema_name, table_name, row_id, operation, changed_cols, occurred_at)
SELECT 'truth_vault', 'notes', 'CI_V22A_' || (n ->> 'id'), 'UPDATE',
       jsonb_build_object('raw_extra', jsonb_build_array('{}'::jsonb, n -> 'history_raw_extra')), timestamp '2026-09-21 07:00'
FROM pb_cases, jsonb_array_elements(j -> 'notes') AS n WHERE n ? 'history_raw_extra'
UNION ALL
SELECT 'truth_vault', 'notes', 'CI_V22A_' || (n ->> 'id'), 'UPDATE',
       jsonb_build_object('raw_extra', jsonb_build_array(n -> 'history_raw_extra', jsonb_build_object('评论区快照', n -> 'fields' -> '评论区快照'))),
       timestamp '2026-09-29 07:00'
FROM pb_cases, jsonb_array_elements(j -> 'notes') AS n WHERE n ? 'history_raw_extra';

-- ═══ (b)(c)(d)(e) F1 视图 ═══════════════════════════════════════════════
DO $$
DECLARE
    got text;
    want text;
    n_trap int;
    n_trap_blob int;
BEGIN
    -- (b) 事件集合逐条相等
    SELECT string_agg(note_id || '@' || boost_date, ',' ORDER BY note_id, boost_date) INTO got
      FROM truth_vault.v_paid_boost_events WHERE note_id LIKE 'CI\_V22A\_%';
    SELECT string_agg('CI_V22A_' || (n ->> 'id') || '@' || d, ',' ORDER BY 'CI_V22A_' || (n ->> 'id'), d) INTO want
      FROM pb_cases, jsonb_array_elements(j -> 'notes') AS n, jsonb_array_elements_text(n -> 'expect_events') AS d;
    IF got IS DISTINCT FROM want THEN
        RAISE EXCEPTION E'(b) 事件集合不对\n期望 %\n实得 %', want, got;
    END IF;
    -- (b) 隔离集合逐条相等 (列 / 原值 / 原因); 外加 SQL 自己造的「未来日期」那篇
    SELECT string_agg(note_id || '|' || source_col || '|' || raw_elem || '|' || reason, E'\n' ORDER BY note_id, source_col, raw_elem) INTO got
      FROM truth_vault.v_paid_boost_quarantine WHERE note_id LIKE 'CI\_V22A\_%';
    SELECT string_agg(x, E'\n' ORDER BY x) INTO want FROM (
        SELECT 'CI_V22A_' || (n ->> 'id') || '|' || (q ->> 0) || '|' || (q ->> 1) || '|' || (q ->> 2) AS x
          FROM pb_cases, jsonb_array_elements(j -> 'notes') AS n, jsonb_array_elements(n -> 'expect_quarantine') AS q
        UNION ALL
        SELECT 'CI_V22A_future|维护时间|' || to_char((now() AT TIME ZONE 'Asia/Shanghai')::date + 30, 'YYYY/MM/DD') || '|date_in_future'
    ) s;
    IF got IS DISTINCT FROM want THEN
        RAISE EXCEPTION E'(b) 隔离集合不对\n期望\n%\n实得\n%', want, got;
    END IF;
    -- (c) 划分: paid_promoted=true 的篇不在事件里就在隔离里
    SELECT string_agg(n.note_id, ',') INTO got
      FROM truth_vault.notes n
     WHERE n.note_id LIKE 'CI\_V22A\_%' AND n.data_quality_flags -> 'paid_promoted' = 'true'::jsonb
       AND n.note_id NOT IN (SELECT note_id FROM truth_vault.v_paid_boost_events)
       AND n.note_id NOT IN (SELECT note_id FROM truth_vault.v_paid_boost_quarantine);
    IF got IS NOT NULL THEN
        RAISE EXCEPTION '(c) paid_promoted=true 却既不在事件也不在隔离: %', got;
    END IF;
    -- (d) 陷阱三张视图 0 行
    SELECT string_agg(DISTINCT x.note_id, ',') INTO got FROM (
        SELECT note_id FROM truth_vault.v_paid_marker_elements
        UNION ALL SELECT note_id FROM truth_vault.v_paid_boost_events
        UNION ALL SELECT note_id FROM truth_vault.v_paid_boost_quarantine) x
     WHERE x.note_id IN (SELECT 'CI_V22A_' || (n ->> 'id') FROM pb_cases, jsonb_array_elements(j -> 'notes') AS n
                          WHERE (n ->> 'trap')::boolean);
    IF got IS NOT NULL THEN
        RAISE EXCEPTION '(d) 白名单外的 🍟 进了视图 (整块扫回来了?): %', got;
    END IF;
    -- (e) 反证: 同一批陷阱按「整块转文本搜 🍟」扫 —— 必须全中, 否则 (d) 的 0 行说明不了什么
    SELECT count(*) INTO n_trap FROM pb_cases, jsonb_array_elements(j -> 'notes') AS n WHERE (n ->> 'trap')::boolean;
    SELECT count(*) INTO n_trap_blob
      FROM truth_vault.notes nt
     WHERE nt.note_id IN (SELECT 'CI_V22A_' || (n ->> 'id') FROM pb_cases, jsonb_array_elements(j -> 'notes') AS n
                           WHERE (n ->> 'trap')::boolean)
       AND (nt.raw_extra::text LIKE '%🍟%' OR nt.data_quality_flags::text LIKE '%🍟%'
            OR coalesce(nt.title, '') || nt.raw_content LIKE '%🍟%'
            OR EXISTS (SELECT 1 FROM truth_vault.audit_log a WHERE a.row_id = nt.note_id AND a.changed_cols::text LIKE '%🍟%'));
    IF n_trap < 6 OR n_trap_blob <> n_trap THEN
        RAISE EXCEPTION '(e) 反证不成立: 陷阱 % 篇, 整块扫 🍟 只扫中 % 篇', n_trap, n_trap_blob;
    END IF;
    -- 事件行上的几列
    PERFORM 1 FROM truth_vault.v_paid_boost_events
     WHERE note_id = 'CI_V22A_bjs_dup' AND date_sources = ARRAY['🍟前日期'] AND marker_cols = ARRAY['关注情况', '维护情况']
       AND cardinality(marker_raw) = 2 AND paid_promoted_state = 'yes' AND year_rules = ARRAY['publish_anchor']
       AND event_id = 'CI_V22A_bjs_dup@2026-09-15' AND days_after_publish = 7;
    IF NOT FOUND THEN RAISE EXCEPTION '(b) bjs_dup: 两列同一天该是一次事件, 两条标记都记上'; END IF;
    PERFORM 1 FROM truth_vault.v_paid_boost_events
     WHERE note_id = 'CI_V22A_spx_both' AND ops_date_agrees AND date_sources = ARRAY['🍟前日期'] AND ops_effect_raw IS NULL;
    IF NOT FOUND THEN RAISE EXCEPTION '(b) spx_both: 🍟 事件, 没配上效果的维护时间同一天只作旁证 (ops_date_agrees)'; END IF;
    PERFORM 1 FROM truth_vault.v_paid_boost_events
     WHERE note_id = 'CI_V22A_hath_pair' AND boost_date = '2026-10-16' AND date_sources = ARRAY['维护时间']
       AND ops_effect_value = 3116 AND ops_effect_metric_flag = 'unknown' AND paid_promoted_state = 'no'
       AND ops_effect_vs_current_impressions = 'impressions_missing';
    IF NOT FOUND THEN RAISE EXCEPTION '(b) hath_pair: 来源 B 第 2 对 (10月16日 ↔ 3116), 效果口径 unknown, paid_promoted 不动'; END IF;
    PERFORM 1 FROM truth_vault.v_paid_boost_events WHERE note_id = 'CI_V22A_spx_effect_str' AND ops_effect_value = 2652;
    IF NOT FOUND THEN RAISE EXCEPTION '(b) spx_effect_str: 维护效果是单个字符串也要配上'; END IF;
    PERFORM 1 FROM truth_vault.v_paid_marker_elements
     WHERE note_id = 'CI_V22A_spx_kongping' AND source_col = '维护时间' AND outcome = 'excluded' AND reason = 'ops_date_unpaired';
    IF NOT FOUND THEN RAISE EXCEPTION '(b) spx_kongping: 没配上数字效果的维护时间要在元素视图里写明 ops_date_unpaired'; END IF;
    PERFORM 1 FROM truth_vault.v_paid_boost_quarantine
     WHERE note_id = 'CI_V22A_after_seen' AND first_seen_cn_day = '2026-09-12' AND parsed_date_context = '2026-09-20';
    IF NOT FOUND THEN RAISE EXCEPTION '(b) after_seen: 9/20🍟 在 9-12 就出现了, 隔离时要带两边日期'; END IF;
    RAISE NOTICE '✓ (b)(c)(d)(e) F1: 事件 / 隔离逐条对上; true 的篇都有去处; 陷阱 % 篇三张视图 0 行, 整块扫 🍟 则 % 篇全中', n_trap, n_trap_blob;
END $$;

-- ═══ 夹具: F2 时间线 (CI_V22B_*) ═══════════════════════════════════════
INSERT INTO truth_vault.notes (note_id, project_id, raw_content, publish_time, raw_extra) VALUES
  ('CI_V22B_main',    'CI_V22', 'c', '2026-09-19 16:00', '{"维护时间": ["9月25日"], "维护效果": ["3000"]}'),
  ('CI_V22B_insnull', 'CI_V22', 'c', '2026-09-19 16:00', '{"维护时间": ["9月25日"], "维护效果": ["100"]}'),
  ('CI_V22B_raw',     'CI_V22', 'c', '2026-09-07 16:00', '{"维护情况": ["9/15🍟"]}'),
  ('CI_V22B_prev19',  'CI_V22', 'c', '2026-08-19 16:00', '{"维护情况": ["08/27🍟"]}'),
  ('CI_V22B_late',    'CI_V22', 'c', '2026-09-30 16:00', '{"维护时间": ["10月1日"], "维护效果": ["200"]}'),
  ('CI_V22B_recent',  'CI_V22', 'c', (now() AT TIME ZONE 'UTC') - interval '3 days',
   jsonb_build_object('维护时间', jsonb_build_array(to_char((now() AT TIME ZONE 'Asia/Shanghai')::date - 1, 'YYYY/MM/DD')),
                      '维护效果', jsonb_build_array('300')));
DELETE FROM truth_vault.audit_log WHERE row_id LIKE 'CI\_V22B\_%';
INSERT INTO truth_vault.audit_log (schema_name, table_name, row_id, operation, changed_cols, occurred_at) VALUES
  -- main: 投流日 2026-09-25 (北京)。09-24 两次读 → 基线取 09:00 那次 (12); 09-25 读到 15 (k=0, 不当基线)
  ('truth_vault', 'notes', 'CI_V22B_main', 'INSERT', '{"comments_count": null, "impressions": null, "reads": null, "interactions": null, "tier": "评估中", "tier_source": "状态字段", "last_seen_run_id": "r0", "raw_extra": {"相关截图": [{"file_token": "tokA", "tmp_url": "u1"}]}}', '2026-09-20 08:00'),
  ('truth_vault', 'notes', 'CI_V22B_main', 'UPDATE', '{"last_seen_run_id": ["r0", "r1"], "comments_count": [null, 10], "impressions": [null, 500], "reads": [null, 50], "interactions": [null, 5]}', '2026-09-24 07:00'),
  ('truth_vault', 'notes', 'CI_V22B_main', 'UPDATE', '{"last_seen_run_id": ["r1", "r2"], "comments_count": [10, 12], "tier": ["评估中", "爆"]}', '2026-09-24 09:00'),
  ('truth_vault', 'notes', 'CI_V22B_main', 'UPDATE', '{"last_seen_run_id": ["r2", "r3"], "comments_count": [12, 15]}', '2026-09-25 08:00'),
  --   D+1: 评论 20; 截图只换了 tmp_url (每晚都变) → 曝光仍是投流前那个数 = 没重截
  ('truth_vault', 'notes', 'CI_V22B_main', 'UPDATE', '{"last_seen_run_id": ["r3", "r4"], "comments_count": [15, 20], "raw_extra": [{"相关截图": [{"file_token": "tokA", "tmp_url": "u1"}]}, {"相关截图": [{"file_token": "tokA", "tmp_url": "u2"}]}]}', '2026-09-26 08:00'),
  --   D+3 只有一次 essence 写 (没盖戳) = 那天没读到
  ('truth_vault', 'notes', 'CI_V22B_main', 'UPDATE', '{"essence_annotated_at": [null, "2026-09-28T08:00:00"], "updated_at": ["2026-09-26T08:00:00", "2026-09-28T08:00:00"]}', '2026-09-28 08:00'),
  ('truth_vault', 'notes', 'CI_V22B_main', 'UPDATE', '{"last_seen_run_id": ["r4", "r5"], "comments_count": [20, 5]}', '2026-09-30 08:00'),
  --   D+7: 评论格被清空 [5, null] → value_null; 曝光变了 + 新截图 tokB → 给值
  ('truth_vault', 'notes', 'CI_V22B_main', 'UPDATE', '{"last_seen_run_id": ["r5", "r6"], "comments_count": [5, null], "impressions": [500, 3500], "raw_extra": [{"相关截图": [{"file_token": "tokA", "tmp_url": "u2"}]}, {"相关截图": [{"file_token": "tokA", "tmp_url": "u3"}, {"file_token": "tokB", "tmp_url": "u4"}]}]}', '2026-10-02 08:00'),
  -- insnull: 09-24 那次读是 INSERT, 评论数键在但是 null → 基线 value_null, 不是 ok、不是 0
  ('truth_vault', 'notes', 'CI_V22B_insnull', 'INSERT', '{"comments_count": null, "impressions": null, "last_seen_run_id": "r0"}', '2026-09-24 08:00'),
  ('truth_vault', 'notes', 'CI_V22B_insnull', 'UPDATE', '{"last_seen_run_id": ["r0", "r1"], "comments_count": [null, 3]}', '2026-09-26 08:00'),
  -- raw: 9/15🍟, 9-18 之前评论数只在 raw_extra._undeclared 里 (D+1 那次是数字字符串); 9-18 typed 第一次填 [null, 11]
  ('truth_vault', 'notes', 'CI_V22B_raw', 'INSERT', '{"last_seen_run_id": "r0", "raw_extra": {"_undeclared": {"实时数据.评论数": 3}}}', '2026-09-08 08:00'),
  ('truth_vault', 'notes', 'CI_V22B_raw', 'UPDATE', '{"last_seen_run_id": ["r0", "r1"], "raw_extra": [{"_undeclared": {"实时数据.评论数": 3}}, {"_undeclared": {"实时数据.评论数": 7, "最近检查时间": 1789351200000}}]}', '2026-09-14 07:00'),
  ('truth_vault', 'notes', 'CI_V22B_raw', 'UPDATE', '{"last_seen_run_id": ["r1", "r2"], "raw_extra": [{"_undeclared": {"实时数据.评论数": 7, "最近检查时间": 1789351200000}}, {"_undeclared": {"实时数据.评论数": "9", "最近检查时间": 1789522200000}}]}', '2026-09-16 07:00'),
  ('truth_vault', 'notes', 'CI_V22B_raw', 'UPDATE', '{"last_seen_run_id": ["r2", "r3"], "comments_count": [null, 11], "raw_extra": [{"_undeclared": {"实时数据.评论数": "9", "最近检查时间": 1789522200000}}, {}]}', '2026-09-18 07:00'),
  -- prev19: 08/27🍟; v1_9 之前没有戳 → 08-26 那次写算一次读 (pre_v1_9_any_write); 第一次盖戳 08-30 16:00 UTC
  ('truth_vault', 'notes', 'CI_V22B_prev19', 'INSERT', '{"impressions": 100, "last_seen_run_id": null}', '2026-08-20 08:00'),
  ('truth_vault', 'notes', 'CI_V22B_prev19', 'UPDATE', '{"impressions": [100, 120], "updated_at": ["2026-08-20T08:00:00", "2026-08-26T07:00:00"]}', '2026-08-26 07:00'),
  ('truth_vault', 'notes', 'CI_V22B_prev19', 'UPDATE', '{"last_seen_run_id": [null, "r1"]}', '2026-08-30 16:00'),
  -- late: 投流当天才第一次进库 → 基线 before_history
  ('truth_vault', 'notes', 'CI_V22B_late', 'INSERT', '{"comments_count": 4, "last_seen_run_id": "r0"}', '2026-10-01 08:00');
-- recent: 昨天投的, 前天读过 → D+3 / D+7 not_due
INSERT INTO truth_vault.audit_log (schema_name, table_name, row_id, operation, changed_cols, occurred_at)
VALUES ('truth_vault', 'notes', 'CI_V22B_recent', 'INSERT', '{"comments_count": 2, "last_seen_run_id": "r0"}',
        (now() AT TIME ZONE 'UTC') - interval '2 days');

-- ═══ (f) F2 读数逐格对 ═══════════════════════════════════════════════
DO $$
DECLARE
    r record;
    bad text[] := '{}';
    n int := 0;
BEGIN
    FOR r IN
        SELECT w.*, g.slot_status AS g_slot, g.obs_kind AS g_kind, g.obs_cn_day AS g_day,
               g.comments AS g_c, g.comments_status AS g_cs, g.comments_source AS g_src,
               g.impressions AS g_i, g.impressions_status AS g_is, g.screenshot_tokens_new AS g_tok,
               g.tier AS g_tier, g.comments_measured_at_cn AS g_meas
        FROM (VALUES
            -- note, k, slot_status, obs_kind, obs_cn_day, comments, comments_status, comments_source, impressions, impressions_status, tokens_new, tier
            ('CI_V22B_main', -1, 'ok', 'full_sync', date '2026-09-24', 12::numeric, 'ok', 'comments_count', 500::numeric, 'ok', NULL::jsonb, '爆'),
            ('CI_V22B_main',  0, 'ok', 'full_sync', date '2026-09-25', 15, 'ok', 'comments_count', NULL, 'missing:no_rescreenshot', NULL, '爆'),
            ('CI_V22B_main',  1, 'ok', 'full_sync', date '2026-09-26', 20, 'ok', 'comments_count', NULL, 'missing:no_rescreenshot', NULL, '爆'),
            ('CI_V22B_main',  3, 'missing:no_full_sync_that_day', NULL, NULL, NULL, 'missing:no_full_sync_that_day', NULL, NULL, 'missing:no_full_sync_that_day', NULL, NULL),
            ('CI_V22B_main',  7, 'ok', 'full_sync', date '2026-10-02', NULL, 'missing:value_null', NULL, 3500, 'ok', '["tokB"]', '爆'),
            ('CI_V22B_insnull', -1, 'ok', 'full_sync', date '2026-09-24', NULL, 'missing:value_null', NULL, NULL, 'missing:value_null', NULL, NULL),
            ('CI_V22B_insnull',  1, 'ok', 'full_sync', date '2026-09-26', 3, 'ok', 'comments_count', NULL, 'missing:value_null', NULL, NULL),
            ('CI_V22B_raw', -1, 'ok', 'full_sync', date '2026-09-14', 7, 'ok', 'raw_extra:实时数据.评论数', NULL, 'missing:value_null', NULL, NULL),
            ('CI_V22B_raw',  0, 'missing:no_full_sync_that_day', NULL, NULL, NULL, 'missing:no_full_sync_that_day', NULL, NULL, 'missing:no_full_sync_that_day', NULL, NULL),
            ('CI_V22B_raw',  1, 'ok', 'full_sync', date '2026-09-16', 9, 'ok', 'raw_extra:实时数据.评论数', NULL, 'missing:value_null', NULL, NULL),
            ('CI_V22B_raw',  3, 'ok', 'full_sync', date '2026-09-18', 11, 'ok', 'comments_count', NULL, 'missing:value_null', NULL, NULL),
            ('CI_V22B_raw',  7, 'missing:no_full_sync_that_day', NULL, NULL, NULL, 'missing:no_full_sync_that_day', NULL, NULL, 'missing:no_full_sync_that_day', NULL, NULL),
            ('CI_V22B_prev19', -1, 'ok', 'pre_v1_9_any_write', date '2026-08-26', NULL, 'missing:value_null', NULL, 120, 'ok', NULL, NULL),
            ('CI_V22B_prev19',  0, 'missing:no_full_sync_that_day', NULL, NULL, NULL, 'missing:no_full_sync_that_day', NULL, NULL, 'missing:no_full_sync_that_day', NULL, NULL),
            ('CI_V22B_late', -1, 'missing:before_history', NULL, NULL, NULL, 'missing:before_history', NULL, NULL, 'missing:before_history', NULL, NULL),
            ('CI_V22B_late',  0, 'ok', 'full_sync', date '2026-10-01', 4, 'ok', 'comments_count', NULL, 'missing:value_null', NULL, NULL),
            ('CI_V22B_recent', -1, 'ok', 'full_sync', (now() AT TIME ZONE 'Asia/Shanghai')::date - 2, 2, 'ok', 'comments_count', NULL, 'missing:value_null', NULL, NULL),
            ('CI_V22B_recent',  0, 'missing:no_full_sync_that_day', NULL, NULL, NULL, 'missing:no_full_sync_that_day', NULL, NULL, 'missing:no_full_sync_that_day', NULL, NULL),
            ('CI_V22B_recent',  1, 'missing:not_due', NULL, NULL, NULL, 'missing:not_due', NULL, NULL, 'missing:not_due', NULL, NULL),
            ('CI_V22B_recent',  3, 'missing:not_due', NULL, NULL, NULL, 'missing:not_due', NULL, NULL, 'missing:not_due', NULL, NULL),
            ('CI_V22B_recent',  7, 'missing:not_due', NULL, NULL, NULL, 'missing:not_due', NULL, NULL, 'missing:not_due', NULL, NULL)
        ) AS w(note_id, k, slot, kind, day, c, cs, src, i, istat, tok, tier)
        LEFT JOIN truth_vault.v_paid_boost_readings g ON g.note_id = w.note_id AND g.k = w.k
    LOOP
        n := n + 1;
        IF (r.g_slot, r.g_kind, r.g_day, r.g_c, r.g_cs, r.g_src, r.g_i, r.g_is, r.g_tok, r.g_tier)
           IS DISTINCT FROM (r.slot, r.kind, r.day, r.c, r.cs, r.src, r.i, r.istat, r.tok, r.tier) THEN
            bad := bad || format('%s k=%s 期望 (%s,%s,%s,c=%s %s %s,imp=%s %s,tok=%s,tier=%s) 实得 (%s,%s,%s,c=%s %s %s,imp=%s %s,tok=%s,tier=%s)',
                r.note_id, r.k, r.slot, r.kind, r.day, r.c, r.cs, r.src, r.i, r.istat, r.tok, r.tier,
                r.g_slot, r.g_kind, r.g_day, r.g_c, r.g_cs, r.g_src, r.g_i, r.g_is, r.g_tok, r.g_tier);
        END IF;
    END LOOP;
    -- 巡查时刻: 基线那次读到的「最近检查时间」= 北京 09-14 10:00
    PERFORM 1 FROM truth_vault.v_paid_boost_readings
     WHERE note_id = 'CI_V22B_raw' AND k = -1 AND comments_measured_at_cn = timestamp '2026-09-14 10:00';
    IF NOT FOUND THEN bad := bad || 'CI_V22B_raw k=-1: comments_measured_at_cn 该是 2026-09-14 10:00 (北京)'::text; END IF;
    -- missing 的值一律 NULL, 夹具里没有 0
    PERFORM 1 FROM truth_vault.v_paid_boost_readings
     WHERE note_id LIKE 'CI\_V22B\_%'
       AND ((comments_status <> 'ok' AND comments IS NOT NULL) OR (impressions_status <> 'ok' AND impressions IS NOT NULL)
            OR (reads_status <> 'ok' AND reads IS NOT NULL) OR (interactions_status <> 'ok' AND interactions IS NOT NULL)
            OR comments = 0 OR impressions = 0 OR reads = 0 OR interactions = 0);
    IF FOUND THEN bad := bad || 'missing 的格子有值, 或冒出了 0'::text; END IF;
    -- 宽表: 增量只在两头都 ok 时算
    PERFORM 1 FROM truth_vault.v_paid_boost_evidence
     WHERE note_id = 'CI_V22B_main' AND comments_base = 12 AND comments_d0 = 15
       AND comments_delta_d1 = 8 AND comments_delta_d1_status = 'ok'
       AND comments_delta_d3 IS NULL AND comments_delta_d3_status = 'd3:missing:no_full_sync_that_day'
       AND comments_delta_d7 IS NULL AND comments_delta_d7_status = 'd7:missing:value_null'
       AND impressions_base = 500 AND impressions_base_changed_cn_day = '2026-09-24'
       AND impressions_d7 = 3500 AND screenshot_tokens_new_d7 = '["tokB"]'
       AND tier_on_boost_day = '爆' AND tier_on_boost_day_src = 'k=0' AND base_cn_day = '2026-09-24';
    IF NOT FOUND THEN bad := bad || 'v_paid_boost_evidence 的 CI_V22B_main 行不对'::text; END IF;
    PERFORM 1 FROM truth_vault.v_paid_boost_evidence
     WHERE note_id = 'CI_V22B_insnull' AND comments_base IS NULL AND comments_delta_d1 IS NULL
       AND comments_delta_d1_status = 'base:missing:value_null';
    IF NOT FOUND THEN bad := bad || 'INSERT 带空键被当成了基线'::text; END IF;
    IF cardinality(bad) > 0 THEN
        RAISE EXCEPTION E'(f) F2 读数不对:\n%', array_to_string(bad, E'\n');
    END IF;
    IF n <> 21 THEN RAISE EXCEPTION '(f) 只对了 % 格 (应 21), 期望表没跑全', n; END IF;
    RAISE NOTICE '✓ (f) F2: % 格逐格对上 (基线取投流日前最后一次 · 当天单列 · 缺就写原因不写 0 · 没重截不给曝光 · raw 回退 · v1_9 前 · not_due)', n;
END $$;

-- ═══ 收尾 ═══════════════════════════════════════════════════════════════
DELETE FROM truth_vault.notes WHERE project_id = 'CI_V22';
DELETE FROM truth_vault.projects WHERE project_id = 'CI_V22';
DELETE FROM truth_vault.audit_log WHERE row_id LIKE 'CI\_V22%';
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM truth_vault.notes WHERE note_id LIKE 'CI\_V22%')
       OR EXISTS (SELECT 1 FROM truth_vault.audit_log WHERE row_id LIKE 'CI\_V22%') THEN
        RAISE EXCEPTION '夹具没删干净';
    END IF;
    RAISE NOTICE '✓ check_paid_boost.sql: all checks passed (夹具已清)';
END $$;
