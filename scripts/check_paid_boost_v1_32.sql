-- check_paid_boost_v1_32.sql · v1_32 (「维护效果」口径 = increment, 列体检 2026-11-25 §3a #4) 的 SQL 侧守卫。
-- CI 的 sql job 一行 (在仓库根目录; 第一个 -f 是 v1_32 的第一遍, 批 1 的部署清单守卫 §3 认这一行):
--   psql -v ON_ERROR_STOP=1 -q -f schemas/notes_v1_32_paid_boost_effect_increment.sql -f scripts/check_paid_boost_v1_32.sql
-- 本文件先 \i 再跑一遍 v1_32 (幂等), 再带 want_flag=increment 把 check_paid_boost.sql 整个跑一遍 (\i), 然后
-- 钉三件事, 夹具行全带 CI_V32 前缀, 最后删干净:
--   ① 维护时间配上纯数字效果 → 事件, ops_effect_metric_flag = increment;
--   ② 🍟 事件没有效果 → flag 是 NULL (不是 increment);
--   ③ XIWU_phase2 那种「一轮 / 二轮维护」+「20条评论」(铺评条数) → 一个事件都没有, 元素视图里是 ops_effect_not_numeric。
-- 反证: 把 v1_32 的 'increment' 改回 'unknown', 或者去掉下面的 \set want_flag increment → 先在 \i 的 check_paid_boost.sql (b) 红
--       (11-25 实跑); 把效果判成数字的正则放宽到带「条」→ ③ 红。

\set QUIET on
\set ON_ERROR_STOP 1

\i schemas/notes_v1_32_paid_boost_effect_increment.sql
\set want_flag increment
\set cases `cat scripts/check_paid_boost_cases.json`
\i scripts/check_paid_boost.sql

INSERT INTO truth_vault.projects (project_id, brand, product, category) VALUES ('CI_V32', 'b', 'p', '保健品');
INSERT INTO truth_vault.notes (note_id, project_id, raw_content, publish_time, raw_extra) VALUES
  ('CI_V32_pair',  'CI_V32', 'c', '2026-10-09 16:00', '{"维护时间": ["10月14日"], "维护效果": ["2652"]}'),
  ('CI_V32_chips', 'CI_V32', 'c', '2026-09-07 16:00', '{"维护情况": ["9/15🍟"]}'),
  ('CI_V32_xiwu',  'CI_V32', 'c', '2026-10-14 16:00',
   '{"维护情况": ["一轮维护", "二轮维护"], "维护时间": ["10月19日", "10月26日"], "维护效果": ["20条评论", "+20条评论"]}');

DO $$
BEGIN
    PERFORM 1 FROM truth_vault.v_paid_boost_events
     WHERE note_id = 'CI_V32_pair' AND boost_date = '2026-10-14' AND ops_effect_value = 2652
       AND ops_effect_metric_flag = 'increment';
    IF NOT FOUND THEN RAISE EXCEPTION '① 维护时间配纯数字效果: 该是一次事件, flag = increment'; END IF;
    PERFORM 1 FROM truth_vault.v_paid_boost_events
     WHERE note_id = 'CI_V32_chips' AND ops_effect_raw IS NULL AND ops_effect_metric_flag IS NULL;
    IF NOT FOUND THEN RAISE EXCEPTION '② 🍟 事件没有效果: flag 该是 NULL'; END IF;
    IF EXISTS (SELECT 1 FROM truth_vault.v_paid_boost_events WHERE note_id = 'CI_V32_xiwu') THEN
        RAISE EXCEPTION '③ 铺评条数 (一轮 / 二轮维护 + 20条评论) 不是投流, 不该有事件';
    END IF;
    IF (SELECT count(*) FROM truth_vault.v_paid_marker_elements
         WHERE note_id = 'CI_V32_xiwu' AND source_col = '维护效果' AND reason = 'ops_effect_not_numeric') <> 2 THEN
        RAISE EXCEPTION '③ 铺评条数的两个效果元素该是 ops_effect_not_numeric';
    END IF;
    IF EXISTS (SELECT 1 FROM truth_vault.v_paid_boost_events
                WHERE ops_effect_raw IS NOT NULL AND ops_effect_metric_flag IS DISTINCT FROM 'increment') THEN
        RAISE EXCEPTION '有效果的事件都该是 increment';
    END IF;
    RAISE NOTICE '✓ check_paid_boost_v1_32.sql: 配上数字效果 = increment · 🍟 无效果 = NULL · 铺评条数不进事件';
END $$;

DELETE FROM truth_vault.notes WHERE project_id = 'CI_V32';
DELETE FROM truth_vault.projects WHERE project_id = 'CI_V32';
DELETE FROM truth_vault.audit_log WHERE row_id LIKE 'CI\_V32%';
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM truth_vault.notes WHERE note_id LIKE 'CI\_V32%') THEN
        RAISE EXCEPTION '夹具没删干净';
    END IF;
END $$;
