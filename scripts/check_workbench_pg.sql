-- check_workbench_pg.sql —— schemas/workbench_v1.sql 的 CI 夹具 (W-63, docs/35; ci.yml sql job 调, 迁移已经跑过两遍之后)。
--   psql -v ON_ERROR_STOP=1 -q -f scripts/check_workbench_pg.sql   (在仓库根目录跑; 任何一条对不上 → RAISE → 这一步红)
-- 全是合成数据: 项目 CI_WB_A (小红书, 活跃)、CI_WB_B (小红书, 60 天前停了)、CI_WB_C (抖音, 活跃)、
--   CI_WB_D (小红书, 活跃; 只放块 4 的笔记 ID 来源: 帖都在 6 天内、没账号、没定级, 不动 A / C 的任何计数); 账号都以 ci_wb_ 开头。
-- 固定「今天」= 2026-11-25 (周三), 先给 11-15 拍一份快照, 再给 11-25 拍两遍 (第二遍替换当天)。最后删干净。
--
-- 守的是:
--   A 权限: anon / authenticated / service_role 没有 workbench 的 USAGE; 表、视图、函数对 PUBLIC / anon / authenticated 一个授权都没有;
--     函数只有 service_role 能执行; tv_workbench_ro 能登录、不是超级用户、NOINHERIT、不在任何角色里 (含 authenticator)、
--     没有 truth_vault 的 USAGE、只读视图读不到表; 九个视图的列名里没有原始列; anon 读视图报 42501
--   B 块 1: 一档要 ≥7 天前的爆 (3 天前的爆不算); 二档只认同平台别的项目的爆 (抖音项目的爆不算); 二档 90 天没发帖不列;
--     降档 = 有 ≥7 天前已定级的帖、一篇没爆; 二档同时降档的那一行带降档标; 新号 / 没账号的帖数
--   C 块 2: 每题取最新一次有效的 primary 答案 (老答案、retest、无效答案都不算); 没标两边都不算, 单独数;
--     抽特征那一次正文是空的 (note_features.body_len = 0), 代码题「未出现」和模型题都按没标算
--   D 块 3a: mid_rank 对比本项目更早北京日期的帖 (含 6 天前那篇); 0.952 进; 0.886 不进 (它 ≥ 第 90 百分位 9.9, 按「≥ P90」会进); 24h 没记评论数单列; 别的项目不到 20 篇;
--     铺评只数运营贴的素人评论 (巡查来的、路人不算); 今天的线 line_now = 11 条 (第 90 百分位是 10, 10 条进不了); 不到 20 篇没有线
--   E 块 3b: 不到 96 小时的「72h」快照丢掉; 过了中位数的不进; 按快照曝光排
--   F 块 4: 晚上发只认笔记 ID 还原出的小时、且日期对得上; 日期对不上 → 不知道几点、不算周末; 同号连发只往前看 3 天;
--     笔记 ID 先取顶层、再取 raw_extra -> '_undeclared' (没声明的「作品ID」「笔记ID」); _undeclared 里的 ID 一样要日期对得上;
--     抖音帖不还原 (19 位作品 ID 不解, 抖音行里带的小红书 ID 也不用): 小时 NULL、状态「抖音帖不还原」
--   G 块 5: 一个投流事件; 缺的点是 NULL 不是 0; 视图里没有 event_id、note_id
--   H 影子核对: 满 7 天那一笔按发布前最近一份快照分组 (一档 / 二档 / 降档 / 名单外有历史 / 新号 / 没有账号);
--     第一份快照之前就发了的帖不分组; 同一天重跑不重复记; 90 天前的快照被删; 「已定级为爆」只数爆 / 趴 (评估中是 NULL);
--     满了之后晚 2 天以上才记的 (第 9 天以后) 单独一行「晚记」
--   I 打码: 读视图的人看到的码是 8 位十六进制, 名字提示是首字加 **, 任何视图的任何一行里都没有原始 account_id / note_id
-- 反证 (改坏之后必须变红):
--   函数里把 c_hit_lag_days 改成 0 → B 红 (3 天前爆的号进一档); other 那段去掉 platform 条件 → B 红 (抖音号进二档);
--   fa 去掉 run_tag / invalid_reason 条件或 ORDER BY 去掉 extracted_at DESC → C 红; mid_rank 改成 cc24 ≥ p90_prior → D 红 (W2 也进);
--   c_min_hours72 改成 0 → E 红 (第 60 小时拍的 X3 进候选); weekend 不看 id_day_diff → F 红 (E3 算周末);
--   块 4 去掉 _undeclared 那四列 → F 红 (U1 没有笔记 ID); _undeclared 排到顶层前面 → F 红 (U2 成了 22 点);
--   xid 去掉「平台是小红书」的条件 → F 红 (DY 用了继承来的小红书 ID, 成了 20 点); hour_status 去掉抖音那一支 → F 红;
--   视图里加一列 i.account_id → A、I 红; GRANT SELECT ... TO anon → A 红; 去掉函数的 REVOKE ... FROM PUBLIC → A 红;
--   wb_lab 去掉 nf.body_len = 0 的条件 → C 红 (空正文的「未出现」算成不提品牌); outcomes 的 hit 改回 tier IN (...) → H 红;
--   v_shadow_check 不分晚记 → H 红; line_now 的 >= c_mid_rank 改成 >= c_p90 的百分位 → D 红。

\set QUIET on
SET client_min_messages = warning;

-- ═══ 准备: 清掉上一轮, 造数 ═══════════════════════════════════════════
TRUNCATE workbench.snapshot_runs, workbench.snapshot_items, workbench.snapshot_outcomes;
DELETE FROM truth_vault.comments WHERE project_id LIKE 'CI\_WB\_%';
DELETE FROM truth_vault.note_feature_answers WHERE subject_id LIKE 'CI\_WB\_%';
DELETE FROM truth_vault.metric_snapshots WHERE note_id LIKE 'CI\_WB\_%';
DELETE FROM truth_vault.note_sync_runs WHERE project_id LIKE 'CI\_WB\_%';
DELETE FROM truth_vault.notes WHERE project_id LIKE 'CI\_WB\_%';
DELETE FROM truth_vault.projects WHERE project_id LIKE 'CI\_WB\_%';
DELETE FROM truth_vault.accounts WHERE account_id LIKE 'ci\_wb\_%';

CREATE TEMP TABLE wb_ci AS SELECT DATE '2026-11-25' AS d;

INSERT INTO truth_vault.projects (project_id, brand, product, category, platform) VALUES
    ('CI_WB_A', 'b', 'p', '保健品', 'xiaohongshu'),
    ('CI_WB_B', 'b', 'p', '保健品', 'xiaohongshu'),
    ('CI_WB_C', 'b', 'p', '保健品', 'douyin'),
    ('CI_WB_D', 'b', 'p', '保健品', 'xiaohongshu');
INSERT INTO truth_vault.accounts (account_id, platform)
SELECT 'ci_wb_' || a, 'xiaohongshu'
FROM unnest(ARRAY['t1', 't1r', 't2', 't2old', 'dg', 't2dg', 'dy', 'new', 'fill', 'g5', 's', 'e3', 'e4',
                  'w1', 'w2', 'w3', 'w4', 'x1', 'x2', 'x3', 'x4', 'bst']) AS a;

-- 帖: (note 后缀, 项目, 账号后缀, 几天前发, tier, 评论数, 曝光, 情绪, 内容形式, 平台)
INSERT INTO truth_vault.notes (note_id, project_id, account_id, raw_content, publish_time, tier, comments_count, impressions,
                               emotional_valence, content_format, platform, publish_url, raw_extra)
SELECT 'CI_WB_' || v.p || '_' || v.k, 'CI_WB_' || v.p, CASE WHEN v.acc IS NOT NULL THEN 'ci_wb_' || v.acc END, 'c',
       (w.d - v.ago)::timestamp - interval '8 hours', v.tier, v.cc, v.imp, v.val, v.fmt, v.plat, v.url, v.rx
FROM wb_ci w
CROSS JOIN LATERAL (VALUES
    -- 块 1
    ('A', 't1_hit',    't1',    20, '爆',   80,   3000, 'negative', NULL::text, 'xiaohongshu', NULL::text, NULL::jsonb),
    ('A', 't1_g2',     't1',     9, NULL,   50,   NULL, NULL, NULL, 'xiaohongshu', NULL, NULL),
    ('A', 't1r_hit',   't1r',    3, '爆',   60,   NULL, NULL, NULL, 'xiaohongshu', NULL, NULL),
    ('B', 't2_hit',    't2',    60, '爆',   70,   NULL, NULL, NULL, 'xiaohongshu', NULL, NULL),
    ('A', 't2_g1',     't2',     8, NULL,   50,   NULL, NULL, NULL, 'xiaohongshu', NULL, NULL),
    ('B', 't2old_hit', 't2old', 100, '爆',  70,   NULL, NULL, NULL, 'xiaohongshu', NULL, NULL),
    ('A', 'dg_pa',     'dg',    18, '趴',   10,   NULL, NULL, NULL, 'xiaohongshu', NULL, NULL),
    ('A', 'dg_g3',     'dg',     8, NULL,   10,   NULL, NULL, NULL, 'xiaohongshu', NULL, NULL),
    ('B', 't2dg_hit',  't2dg',  60, '大爆', 120,  NULL, NULL, NULL, 'xiaohongshu', NULL, NULL),
    ('A', 't2dg_pa',   't2dg',  12, '趴',   10,   NULL, NULL, NULL, 'xiaohongshu', NULL, NULL),
    ('C', 'dy_hit',    'dy',    30, '爆',   90,   NULL, NULL, NULL, 'douyin',      NULL, NULL),
    ('A', 'dy',        'dy',     2, NULL,   NULL, NULL, NULL, NULL, 'xiaohongshu', NULL, NULL),
    ('A', 'new',       'new',    1, NULL,   NULL, NULL, NULL, NULL, 'xiaohongshu', NULL, NULL),
    ('A', 'fill_g4',   'fill',   7, '评估中', 5,  NULL, NULL, NULL, 'xiaohongshu', NULL, NULL),
    ('A', 'g5',        'g5',     9, NULL,   46,   NULL, NULL, NULL, 'xiaohongshu', NULL, NULL),
    ('A', 'null_g6',   NULL,     8, NULL,   0,    NULL, NULL, NULL, 'xiaohongshu', NULL, NULL),
    -- 块 3a (W4 在 5 天窗外, 但算 W1 / W2 的「更早的帖」)
    ('A', 'w1',        'w1',     2, NULL,   60,   NULL, 'positive', NULL, 'xiaohongshu', NULL, NULL),
    ('A', 'w2',        'w2',     1, NULL,   20,   NULL, NULL, NULL, 'xiaohongshu', NULL, NULL),
    ('A', 'w3',        'w3',     3, NULL,   NULL, NULL, NULL, NULL, 'xiaohongshu', NULL, NULL),
    ('A', 'w4',        'w4',     6, NULL,   NULL, NULL, NULL, NULL, 'xiaohongshu', NULL, NULL),
    ('C', 'p1',        NULL,     8, NULL,   NULL, NULL, NULL, NULL, 'douyin',      NULL, NULL),
    ('C', 'p2',        NULL,     7, NULL,   NULL, NULL, NULL, NULL, 'douyin',      NULL, NULL),
    ('C', 'c1',        NULL,     1, NULL,   NULL, NULL, NULL, NULL, 'douyin',      NULL, NULL),
    -- 块 3b
    ('A', 'x1',        'x1',     5, NULL,   NULL, 600,  NULL, NULL, 'xiaohongshu', NULL, NULL),
    ('A', 'x2',        'x2',     6, NULL,   NULL, 900,  NULL, NULL, 'xiaohongshu', NULL, NULL),
    ('A', 'x3',        'x3',     4, NULL,   NULL, NULL, NULL, NULL, 'xiaohongshu', NULL, NULL),
    ('A', 'x4',        'x4',     7, NULL,   NULL, 6000, NULL, NULL, 'xiaohongshu', NULL, NULL),
    -- 块 4: E1 周一 20:30 发; E2 周六 10:00 发; E3 记在周日、笔记 ID 是周五 21:00; E4 没有链接
    ('A', 'e1',        's',      2, NULL,   NULL, NULL, NULL, '场景植入', 'xiaohongshu',
        'https://www.xiaohongshu.com/explore/' || lpad(to_hex(extract(epoch FROM (((w.d - 2)::timestamp + interval '20 hours 30 minutes') AT TIME ZONE 'Asia/Shanghai'))::bigint), 8, '0') || '0123456789abcdef', NULL),
    ('A', 'e2',        's',      4, NULL,   NULL, NULL, NULL, NULL, 'xiaohongshu',
        'https://www.xiaohongshu.com/explore/' || lpad(to_hex(extract(epoch FROM (((w.d - 4)::timestamp + interval '10 hours') AT TIME ZONE 'Asia/Shanghai'))::bigint), 8, '0') || '0123456789abcdef', NULL),
    ('A', 'e3',        'e3',     3, NULL,   NULL, NULL, NULL, NULL, 'xiaohongshu', NULL,
        jsonb_build_object('笔记链接', 'https://www.xiaohongshu.com/explore/' || lpad(to_hex(extract(epoch FROM (((w.d - 5)::timestamp + interval '21 hours') AT TIME ZONE 'Asia/Shanghai'))::bigint), 8, '0') || '0123456789abcdef')),
    ('A', 'e4',        'e4',     6, NULL,   NULL, NULL, NULL, NULL, 'xiaohongshu', NULL, NULL),
    -- 块 5: 11-20 投流 (维护时间 + 维护效果), 读数一个都没有
    ('A', 'b1',        'bst',   10, NULL,   NULL, NULL, NULL, NULL, 'xiaohongshu', NULL,
        jsonb_build_object('维护时间', jsonb_build_array(to_char(w.d - 5, 'YYYY/MM/DD')), '维护效果', jsonb_build_array('300')))
) AS v(p, k, acc, ago, tier, cc, imp, val, fmt, plat, url, rx);

-- 块 4 的笔记 ID 来源 (项目 CI_WB_D): 「作品ID」的值照线上的样子是「24 位十六进制 ← 短链」
--   U1 周二 19:15 发, ID 只在 _undeclared 的「作品ID」里; U2 周一, 顶层「笔记ID」是 09:00、_undeclared「作品ID」是 22:00 → 先认顶层;
--   U3 记在周日, _undeclared「笔记ID」是周五 21:00 (定时发: ID 是创建时刻) → 日期对不上;
--   DY 周六, 这个小红书项目里的一篇抖音帖: 链接里的 19 位作品 ID 高 32 位当 unix 秒是周六 20:00, _undeclared 里还带着一个
--   周六 20:00 的小红书 ID (像从上一行继承来的) → 都不用, 小时 NULL
INSERT INTO truth_vault.notes (note_id, project_id, account_id, raw_content, publish_time, platform, publish_url, raw_extra)
SELECT 'CI_WB_D_' || v.k, 'CI_WB_D', NULL, 'c', (w.d - v.ago)::timestamp - interval '8 hours', v.plat, v.url, v.rx
FROM wb_ci w
CROSS JOIN LATERAL (VALUES
    ('u1', 1, 'xiaohongshu', NULL::text,
        jsonb_build_object('_undeclared', jsonb_build_object('作品ID',
            lpad(to_hex(extract(epoch FROM (((w.d - 1)::timestamp + interval '19 hours 15 minutes') AT TIME ZONE 'Asia/Shanghai'))::bigint), 8, '0')
            || '0123456789abcdef ← https://xhslink.com/o/Ab12Cd34Ef'))),
    ('u2', 2, 'xiaohongshu', NULL,
        jsonb_build_object(
            '笔记ID', lpad(to_hex(extract(epoch FROM (((w.d - 2)::timestamp + interval '9 hours') AT TIME ZONE 'Asia/Shanghai'))::bigint), 8, '0') || '0123456789abcdef',
            '_undeclared', jsonb_build_object('作品ID',
                lpad(to_hex(extract(epoch FROM (((w.d - 2)::timestamp + interval '22 hours') AT TIME ZONE 'Asia/Shanghai'))::bigint), 8, '0')
                || '0123456789abcdef ← https://xhslink.com/o/Ab12Cd34Ef'))),
    ('u3', 3, 'xiaohongshu', NULL,
        jsonb_build_object('_undeclared', jsonb_build_object('笔记ID',
            lpad(to_hex(extract(epoch FROM (((w.d - 5)::timestamp + interval '21 hours') AT TIME ZONE 'Asia/Shanghai'))::bigint), 8, '0') || '0123456789abcdef'))),
    ('dy', 4, 'douyin',
        'https://www.douyin.com/video/'
            || ((extract(epoch FROM (((w.d - 4)::timestamp + interval '20 hours') AT TIME ZONE 'Asia/Shanghai'))::bigint << 32) + 123456789)::text,
        jsonb_build_object('_undeclared', jsonb_build_object('作品ID',
            lpad(to_hex(extract(epoch FROM (((w.d - 4)::timestamp + interval '20 hours') AT TIME ZONE 'Asia/Shanghai'))::bigint), 8, '0')
            || '0123456789abcdef ← https://xhslink.com/o/Ab12Cd34Ef')))
) AS v(k, ago, plat, url, rx);

-- 20 篇垫底的帖: 11–30 天前, 同一个号, 没定级, 曝光都是 1000; 24h 评论数 0×10、1..10
INSERT INTO truth_vault.notes (note_id, project_id, account_id, raw_content, publish_time, impressions)
SELECT 'CI_WB_A_f' || lpad(k::text, 2, '0'), 'CI_WB_A', 'ci_wb_fill', 'c', (w.d - (10 + k))::timestamp - interval '8 hours', 1000
FROM wb_ci w, generate_series(1, 20) AS k;

INSERT INTO truth_vault.metric_snapshots (note_id, collected_at, window_label, hours_since_publish, comments_count, impressions, reads)
SELECT 'CI_WB_A_f' || lpad(k::text, 2, '0'), now(), '24h', 16, CASE WHEN k <= 10 THEN 0 ELSE k - 10 END, NULL, NULL
FROM generate_series(1, 20) AS k
UNION ALL SELECT * FROM (VALUES
    ('CI_WB_A_w1', now(), '24h', 16, 12,   NULL::int, NULL::int),
    ('CI_WB_A_w2', now(), '24h', 16, 10,   NULL, NULL),
    ('CI_WB_A_w3', now(), '24h', 16, NULL, NULL, NULL),
    ('CI_WB_A_w4', now(), '24h', 16, 50,   NULL, NULL),
    ('CI_WB_C_p1', now(), '24h', 16, 1,    NULL, NULL),
    ('CI_WB_C_p2', now(), '24h', 16, 2,    NULL, NULL),
    ('CI_WB_C_c1', now(), '24h', 16, 3,    NULL, NULL),
    ('CI_WB_A_x1', now(), '72h', 110, NULL, 500,  50),
    ('CI_WB_A_x2', now(), '72h', 100, NULL, 800,  40),
    ('CI_WB_A_x3', now(), '72h', 60,  NULL, 300,  30),
    ('CI_WB_A_x4', now(), '72h', 120, NULL, 5000, 500)
) AS s(note_id, collected_at, window_label, h, cc, imp, rd);

-- 标签: dg_pa 老答案「未出现」、新答案「中间」→ 取中间; e4 只有 retest 的答案; e3 的答案无效 → 都算没标;
--   t2dg_pa 抽特征那一次正文是空的 (body_len = 0): 「未出现」两题都按没标算; t1_hit 正文 300 字, 照常算
INSERT INTO truth_vault.note_feature_answers (subject_type, subject_id, question_id, question_version, bank_version, bank_sha256,
                                               extractor, run_tag, answer, invalid_reason, extracted_at) VALUES
    ('note', 'CI_WB_A_t1_hit',  'brand_first_position', 1, 'fq', 's', 'code:v1',  'primary',    '未出现', NULL, '2026-11-10'),
    ('note', 'CI_WB_A_t1_hit',  'product_role',         1, 'fq', 's', 'llm:m',    'primary',    '未出现', NULL, '2026-11-10'),
    ('note', 'CI_WB_A_dg_pa',   'brand_first_position', 1, 'fq', 's', 'code:old', 'primary',    '未出现', NULL, '2026-11-01'),
    ('note', 'CI_WB_A_dg_pa',   'brand_first_position', 1, 'fq', 's', 'code:v1',  'primary',    '中间',   NULL, '2026-11-10'),
    ('note', 'CI_WB_A_t2dg_pa', 'brand_first_position', 1, 'fq', 's', 'code:v1',  'primary',    '未出现', NULL, '2026-11-14'),
    ('note', 'CI_WB_A_t2dg_pa', 'product_role',         1, 'fq', 's', 'llm:m',    'primary',    '未出现', NULL, '2026-11-14'),
    ('note', 'CI_WB_A_e4',      'brand_first_position', 1, 'fq', 's', 'code:v1',  'retest-1',   '未出现', NULL, '2026-11-20'),
    ('note', 'CI_WB_A_e3',      'brand_first_position', 1, 'fq', 's', 'code:v1',  'primary',    '未出现', 'evidence_not_found', '2026-11-23');

INSERT INTO truth_vault.note_features (note_id, body_len, extracted_at, extractor_version) VALUES
    ('CI_WB_A_t1_hit', 300, '2026-11-10', 'fq-v0.1/code:v1'),
    ('CI_WB_A_t2dg_pa', 0,  '2026-11-14', 'fq-v0.1/code:v1');

-- 评论: W1 两条运营贴的素人评论 (算), 一条巡查来的素人评论、一条路人 (都不算)
INSERT INTO truth_vault.comments (comment_id, note_id, project_id, content, comment_role, source) VALUES
    ('ci_wb_c1', 'CI_WB_A_w1', 'CI_WB_A', 'x', '素人', NULL),
    ('ci_wb_c2', 'CI_WB_A_w1', 'CI_WB_A', 'x', '素人', NULL),
    ('ci_wb_c3', 'CI_WB_A_w1', 'CI_WB_A', 'x', '素人', 'linkcheck_records'),
    ('ci_wb_c4', 'CI_WB_A_w1', 'CI_WB_A', 'x', '路人', NULL);

INSERT INTO truth_vault.note_sync_runs (run_id, project_id, started_at, completed_at, seen_count)
VALUES ('ci_wb_run1', 'CI_WB_A', '2026-11-24 12:00+00', '2026-11-24 12:30+00', 45);

-- 一份 120 天前的快照: 拍 11-25 那一趟要把它删掉
INSERT INTO workbench.snapshot_runs (day, taken_at, rule_version) VALUES (DATE '2026-11-25' - 120, now(), 'wb-v1');

-- ═══ 拍快照: 11-15 一份, 11-25 两遍 ════════════════════════════════════
SELECT truth_vault.workbench_take_snapshot(DATE '2026-11-15') IS NOT NULL AS ok \gset
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM workbench.snapshot_runs WHERE day = DATE '2026-11-25' - 120) THEN
        -- 11-15 那一趟只删 11-15 往前 90 天以前的: 120 天前那份 (7-28) 应该已经没了
        RAISE EXCEPTION 'H: 90 天前的快照没删';
    END IF;
END $$;
SELECT truth_vault.workbench_take_snapshot(DATE '2026-11-25') IS NOT NULL AS ok \gset
CREATE TEMP TABLE wb_first_pass AS
    SELECT block, count(*) AS n FROM workbench.snapshot_items WHERE day = DATE '2026-11-25' GROUP BY block;
CREATE TEMP TABLE wb_outcomes_first AS SELECT count(*) AS n FROM workbench.snapshot_outcomes;
SELECT truth_vault.workbench_take_snapshot(DATE '2026-11-25') IS NOT NULL AS ok \gset

-- ═══ A 权限 ═══════════════════════════════════════════════════════════
DO $$
DECLARE
    bad TEXT;
    r   RECORD;
BEGIN
    FOR r IN SELECT unnest(ARRAY['anon', 'authenticated', 'service_role']) AS role LOOP
        IF has_schema_privilege(r.role, 'workbench', 'USAGE') THEN
            RAISE EXCEPTION 'A: % 有 workbench 的 USAGE', r.role;
        END IF;
    END LOOP;
    -- 表、视图: 除了属主, 只许 tv_workbench_ro 对 v_* 有 SELECT
    SELECT string_agg(c.relname || ':' || CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END
                      || ':' || a.privilege_type, ', ')
      INTO bad
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
      CROSS JOIN LATERAL aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) a
     WHERE n.nspname = 'workbench' AND c.relkind IN ('r', 'v', 'm', 'S')
       AND a.grantee <> c.relowner
       AND NOT (c.relkind = 'v' AND c.relname LIKE 'v\_%' AND a.grantee = 'tv_workbench_ro'::regrole AND a.privilege_type = 'SELECT');
    IF bad IS NOT NULL THEN RAISE EXCEPTION 'A: workbench 里多出来的授权: %', bad; END IF;
    IF (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'workbench' AND c.relkind = 'v' AND c.relname LIKE 'v\_%'
           AND has_table_privilege('tv_workbench_ro', c.oid, 'SELECT')) <> 9 THEN
        RAISE EXCEPTION 'A: tv_workbench_ro 不是正好能读九个视图';
    END IF;
    -- 函数: 只有属主和 service_role
    SELECT string_agg(CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END, ', ')
      INTO bad
      FROM pg_proc p
      CROSS JOIN LATERAL aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a
     WHERE p.oid = 'truth_vault.workbench_take_snapshot(date)'::regprocedure
       AND a.grantee <> p.proowner AND a.grantee <> 'service_role'::regrole;
    IF bad IS NOT NULL THEN RAISE EXCEPTION 'A: 快照函数还能被这些角色执行: %', bad; END IF;
    IF NOT has_function_privilege('service_role', 'truth_vault.workbench_take_snapshot(date)', 'EXECUTE') THEN
        RAISE EXCEPTION 'A: service_role 不能执行快照函数';
    END IF;
    IF NOT (SELECT prosecdef AND 'search_path=""' = ANY(proconfig) FROM pg_proc
             WHERE oid = 'truth_vault.workbench_take_snapshot(date)'::regprocedure) THEN
        RAISE EXCEPTION 'A: 快照函数不是 SECURITY DEFINER 或 search_path 不是空';
    END IF;
    -- 读视图的角色
    IF NOT (SELECT rolcanlogin AND NOT rolsuper AND NOT rolinherit AND NOT rolbypassrls AND NOT rolcreaterole AND NOT rolcreatedb
                   AND rolconnlimit = 5 AND rolpassword IS NULL
              FROM pg_authid WHERE rolname = 'tv_workbench_ro') THEN
        RAISE EXCEPTION 'A: tv_workbench_ro 的属性不对 (要 LOGIN NOINHERIT、没有特权、连接上限 5、SQL 里不设密码)';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_auth_members WHERE member = 'tv_workbench_ro'::regrole) THEN
        RAISE EXCEPTION 'A: tv_workbench_ro 是别的角色的成员 (不许进 authenticator)';
    END IF;
    IF has_schema_privilege('tv_workbench_ro', 'truth_vault', 'USAGE') THEN
        RAISE EXCEPTION 'A: tv_workbench_ro 有 truth_vault 的 USAGE';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_db_role_setting s
                    WHERE s.setrole = 'tv_workbench_ro'::regrole AND s.setdatabase = 0
                      AND 'default_transaction_read_only=on' = ANY(s.setconfig) AND 'statement_timeout=8s' = ANY(s.setconfig)) THEN
        RAISE EXCEPTION 'A: tv_workbench_ro 没设只读事务和 8 秒超时';
    END IF;
    -- 视图的列名里没有原始列
    SELECT string_agg(c.table_name || '.' || c.column_name, ', ')
      INTO bad
      FROM information_schema.columns c
     WHERE c.table_schema = 'workbench' AND c.table_name LIKE 'v\_%'
       AND c.column_name IN ('account_id', 'note_id', 'event_id', 'item_key', 'publish_url', 'feishu_record_id', 'title', 'body',
                             'raw_content', 'hashtags', 'pinned_comment', 'compliance_notes', 'raw_extra', 'account_memo',
                             'marker_raw', 'ops_effect_raw', 'ops_effect_value', 'screenshot_tokens_new_d7', 'salt', 'content', 'data');
    IF bad IS NOT NULL THEN RAISE EXCEPTION 'A: 视图出了原始列: %', bad; END IF;
END $$;

SET ROLE anon;
DO $$
BEGIN
    PERFORM 1 FROM workbench.v_status;
    RAISE EXCEPTION 'A: anon 读到了 workbench.v_status';
EXCEPTION WHEN insufficient_privilege THEN NULL;
END $$;
RESET ROLE;

SET ROLE tv_workbench_ro;
DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['workbench.snapshot_items', 'workbench.snapshot_runs', 'workbench.snapshot_outcomes',
                             'workbench.mask_salt', 'truth_vault.notes'] LOOP
        BEGIN
            EXECUTE 'SELECT 1 FROM ' || t || ' LIMIT 1';
            RAISE EXCEPTION 'A: tv_workbench_ro 读到了 %', t;
        EXCEPTION WHEN insufficient_privilege THEN NULL;
        END;
    END LOOP;
    BEGIN
        PERFORM truth_vault.workbench_take_snapshot(DATE '2026-11-25');
        RAISE EXCEPTION 'A: tv_workbench_ro 能执行快照函数';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
END $$;
-- I 打码: 以读视图的人的身份看, 每一行里都没有原始 id
CREATE TEMP TABLE wb_seen AS
          SELECT 'v_status' AS v, to_jsonb(x)::text AS t FROM workbench.v_status x
UNION ALL SELECT 'v_accounts', to_jsonb(x)::text FROM workbench.v_accounts x
UNION ALL SELECT 'v_content_counts', to_jsonb(x)::text FROM workbench.v_content_counts x
UNION ALL SELECT 'v_content_notes', to_jsonb(x)::text FROM workbench.v_content_notes x
UNION ALL SELECT 'v_watch_24h', to_jsonb(x)::text FROM workbench.v_watch_24h x
UNION ALL SELECT 'v_watch_72h', to_jsonb(x)::text FROM workbench.v_watch_72h x
UNION ALL SELECT 'v_exposure_hints', to_jsonb(x)::text FROM workbench.v_exposure_hints x
UNION ALL SELECT 'v_boost_curves', to_jsonb(x)::text FROM workbench.v_boost_curves x
UNION ALL SELECT 'v_shadow_check', to_jsonb(x)::text FROM workbench.v_shadow_check x;
CREATE TEMP TABLE wb_seen_acc AS SELECT * FROM workbench.v_accounts WHERE project_id = 'CI_WB_A';
CREATE TEMP TABLE wb_seen_boost AS SELECT * FROM workbench.v_boost_curves WHERE project_id = 'CI_WB_A';
CREATE TEMP TABLE wb_seen_shadow AS SELECT * FROM workbench.v_shadow_check;
CREATE TEMP TABLE wb_seen_status AS SELECT * FROM workbench.v_status;
CREATE TEMP TABLE wb_seen_hints AS SELECT * FROM workbench.v_exposure_hints;
RESET ROLE;

DO $$
DECLARE
    bad TEXT;
BEGIN
    SELECT string_agg(DISTINCT v, ', ') INTO bad FROM wb_seen
     WHERE t LIKE '%ci\_wb\_%' OR t LIKE '%CI\_WB\_A\_%' OR t LIKE '%CI\_WB\_C\_%' OR t LIKE '%CI\_WB\_D\_%'
        OR t LIKE '%xiaohongshu.com%' OR t LIKE '%douyin.com%' OR t LIKE '%xhslink%' OR t ~ '[0-9a-f]{8}0123456789abcdef';
    IF bad IS NOT NULL THEN RAISE EXCEPTION 'I: 这些视图里出现了原始 account_id / note_id / 链接: %', bad; END IF;
    IF (SELECT count(DISTINCT v) FROM wb_seen) <> 9 THEN
        RAISE EXCEPTION 'I: 九个视图里有的读出来是空的 (夹具该让每个视图都有行)';
    END IF;
    IF EXISTS (SELECT 1 FROM wb_seen_acc WHERE account_code !~ '^[0-9a-f]{8}$' OR name_hint <> 'c**') THEN
        RAISE EXCEPTION 'I: 账号码不是 8 位十六进制, 或名字提示不是首字加 **';
    END IF;
    IF EXISTS (SELECT 1 FROM wb_seen_acc a JOIN workbench.mask_salt s ON TRUE
                WHERE a.account_code = left(md5('ci_wb_t1'), 8) OR a.account_code = left(encode(sha256(convert_to('a:ci_wb_t1', 'UTF8')), 'hex'), 8)) THEN
        RAISE EXCEPTION 'I: 账号码没加盐';
    END IF;
END $$;

-- ═══ B 块 1 ═══════════════════════════════════════════════════════════
DO $$
DECLARE
    got TEXT;
    j   JSONB;
BEGIN
    SELECT string_agg(account_id || ':' || coalesce(data ->> 'tier', '-') || ':' || (data ->> 'downgrade') || ':' || (data ->> 'listed'),
                      ',' ORDER BY account_id COLLATE "C")
      INTO got FROM workbench.snapshot_items
     WHERE day = DATE '2026-11-25' AND block = 'accounts' AND project_id = 'CI_WB_A';
    IF got IS DISTINCT FROM 'ci_wb_dg:-:true:false,ci_wb_t1:一档:false:true,ci_wb_t2:二档:false:true,ci_wb_t2dg:二档:true:true,ci_wb_t2old:二档:false:false' THEN
        RAISE EXCEPTION 'B: CI_WB_A 的账号档不对, 实得 %', got;
    END IF;
    SELECT string_agg(account_id || ':' || coalesce(data ->> 'tier', '-'), ',' ORDER BY account_id COLLATE "C")
      INTO got FROM workbench.snapshot_items
     WHERE day = DATE '2026-11-25' AND block = 'accounts' AND project_id = 'CI_WB_C';
    IF got IS DISTINCT FROM 'ci_wb_dy:一档' THEN RAISE EXCEPTION 'B: CI_WB_C 的账号档不对, 实得 %', got; END IF;
    SELECT string_agg(tier || ':' || downgrade || ':' || other_hit || ':' || posts_here, ',' ORDER BY seq) INTO got FROM wb_seen_acc;
    IF got IS DISTINCT FROM '一档:false:false:2,二档:false:true:1,二档:true:true:1' THEN
        RAISE EXCEPTION 'B: v_accounts 列出来的不对 (一档在前、二档按最近发帖日), 实得 %', got;
    END IF;
    SELECT b1 INTO j FROM wb_seen_status WHERE project_id = 'CI_WB_A';
    IF j IS DISTINCT FROM '{"tier1": 1, "tier2": 3, "tier2_recent": 2, "tier2_listed": 2, "downgrade": 2,
                           "new_acct_posts_30d": 18, "no_acct_posts_30d": 1, "status": "有"}'::jsonb THEN
        RAISE EXCEPTION 'B: CI_WB_A 的 b1 计数不对, 实得 %', j;
    END IF;
    IF EXISTS (SELECT 1 FROM wb_seen_status WHERE project_id = 'CI_WB_B') THEN
        RAISE EXCEPTION 'B: 60 天没发帖的 CI_WB_B 不该算活跃项目';
    END IF;
    IF (SELECT posts_30d FROM wb_seen_status WHERE project_id = 'CI_WB_A') <> 44
       OR (SELECT data_as_of FROM wb_seen_status WHERE project_id = 'CI_WB_A') <> TIMESTAMPTZ '2026-11-24 12:30+00'
       OR (SELECT median_impressions FROM wb_seen_status WHERE project_id = 'CI_WB_A') <> 1000 THEN
        RAISE EXCEPTION 'B: CI_WB_A 的近 30 天帖数 / 数据截至 / 曝光中位数不对';
    END IF;
END $$;

-- ═══ C 块 2 ═══════════════════════════════════════════════════════════
DO $$
DECLARE
    got TEXT;
    j   JSONB;
BEGIN
    SELECT data - 'seq' - 'hint' - 'side' - 'scope' - 'w64' INTO j FROM workbench.snapshot_items
     WHERE day = DATE '2026-11-25' AND block = 'content_counts' AND project_id = 'CI_WB_A' AND item_key = '正文不提品牌';
    IF j IS DISTINCT FROM '{"n_flag": 1, "n_noflag": 1, "n_unlabeled": 43, "graded_flag": 1, "hits_flag": 1, "graded_noflag": 1,
                           "hits_noflag": 0, "expo_known_flag": 1, "expo_hi_flag": 1, "expo_known_noflag": 0, "expo_hi_noflag": 0}'::jsonb THEN
        RAISE EXCEPTION 'C: 「正文不提品牌」的计数不对 (老答案 / retest / 无效答案 / 空正文的答案算进去了?), 实得 %', j;
    END IF;
    SELECT string_agg(item_key || ':' || (data ->> 'n_flag') || '/' || (data ->> 'n_noflag') || '/' || (data ->> 'n_unlabeled'), ',' ORDER BY (data ->> 'seq')::int)
      INTO got FROM workbench.snapshot_items
     WHERE day = DATE '2026-11-25' AND block = 'content_counts' AND project_id = 'CI_WB_A';
    IF got IS DISTINCT FROM '正文不提品牌:1/1/43,产品不出场:1/0/44,负面痛点基调:1/1/43,求助式写法:0/0/45,产品当主角:0/1/44,产品当解决方案:0/1/44,功效承诺:0/0/45,场景植入:1/0/44' THEN
        RAISE EXCEPTION 'C: 八种写法的 有/没有/没标 不对, 实得 %', got;
    END IF;
    SELECT (data -> 'minus') || (data -> 'unlabeled') INTO j FROM workbench.snapshot_items
     WHERE day = DATE '2026-11-25' AND block = 'content_notes' AND item_key = 'CI_WB_A_e1';
    IF j IS DISTINCT FROM '["场景植入", "品牌位置", "产品角色", "情绪基调", "求助式", "功效承诺"]'::jsonb THEN
        RAISE EXCEPTION 'C: E1 的减分 / 没标不对, 实得 %', j;
    END IF;
    SELECT b2 INTO j FROM wb_seen_status WHERE project_id = 'CI_WB_A';
    IF j IS DISTINCT FROM '{"graded_7d": 3, "hits_7d": 1, "notes_14d": 26, "notes_14d_all_unlabeled": 24,
                           "notes_14d_some_unlabeled": 26, "body_empty": 1, "body_empty_14d": 1, "status": "多数帖没标"}'::jsonb THEN
        RAISE EXCEPTION 'C: CI_WB_A 的 b2 计数不对, 实得 %', j;
    END IF;
    SELECT jsonb_build_object('plus', data -> 'plus', 'unlabeled', data -> 'unlabeled', 'body_empty', data -> 'body_empty') INTO j
      FROM workbench.snapshot_items
     WHERE day = DATE '2026-11-25' AND block = 'content_notes' AND item_key = 'CI_WB_A_t2dg_pa';
    IF j IS DISTINCT FROM '{"plus": [], "unlabeled": ["品牌位置", "产品角色", "情绪基调", "求助式", "功效承诺", "内容形式"],
                           "body_empty": true}'::jsonb THEN
        RAISE EXCEPTION 'C: 空正文那篇该六维全没标、不带加分写法, 实得 %', j;
    END IF;
END $$;

-- ═══ D 块 3a ══════════════════════════════════════════════════════════
DO $$
DECLARE
    got TEXT;
    j   JSONB;
BEGIN
    SELECT string_agg(item_key || ':' || (data ->> 'status') || ':' || coalesce(data ->> 'mid_rank', '-') || ':' || (data ->> 'n_prior')
                      || ':' || (data ->> 'seeded_known'), ',' ORDER BY item_key COLLATE "C")
      INTO got FROM workbench.snapshot_items
     WHERE day = DATE '2026-11-25' AND block = 'watch_24h' AND project_id IN ('CI_WB_A', 'CI_WB_C');
    IF got IS DISTINCT FROM 'CI_WB_A_w1:进清单:0.952:21:2,CI_WB_A_w2:没进:0.886:22:0,CI_WB_A_w3:24h 没记评论数:-:21:0,CI_WB_C_c1:本项目更早的帖不到 20 篇:1.000:2:0' THEN
        RAISE EXCEPTION 'D: 24h 清单不对, 实得 %', got;
    END IF;
    IF (SELECT (data ->> 'p90_prior')::numeric FROM workbench.snapshot_items
         WHERE day = DATE '2026-11-25' AND block = 'watch_24h' AND item_key = 'CI_WB_A_w1') <> 9 THEN
        RAISE EXCEPTION 'D: W1 的第 90 百分位不是 9';
    END IF;
    SELECT b3a - 'p90_now' INTO j FROM wb_seen_status WHERE project_id = 'CI_WB_A';
    IF j IS DISTINCT FROM '{"recent_notes": 10, "candidates": 3, "no_24h": 7, "listed": 1, "short_prior": 0, "cc_null": 1,
                           "prior_now": 23, "line_now": 11, "status": "有"}'::jsonb
       OR (SELECT round((b3a ->> 'p90_now')::numeric, 2) FROM wb_seen_status WHERE project_id = 'CI_WB_A') <> 10 THEN
        RAISE EXCEPTION 'D: CI_WB_A 的 b3a 计数不对, 实得 %', j;
    END IF;
    IF (SELECT b3a ->> 'status' FROM wb_seen_status WHERE project_id = 'CI_WB_C') IS DISTINCT FROM '本项目更早的帖不到 20 篇' THEN
        RAISE EXCEPTION 'D: CI_WB_C 该写「本项目更早的帖不到 20 篇」';
    END IF;
    IF (SELECT b3a -> 'line_now' FROM wb_seen_status WHERE project_id = 'CI_WB_C') IS DISTINCT FROM 'null'::jsonb THEN
        RAISE EXCEPTION 'D: CI_WB_C 更早的帖不到 20 篇, 不该有线';
    END IF;
END $$;

-- ═══ E 块 3b ══════════════════════════════════════════════════════════
DO $$
DECLARE
    got TEXT;
    j   JSONB;
BEGIN
    SELECT string_agg(item_key || ':' || (data ->> 'rank') || ':' || (data ->> 'impressions_72h') || ':' || (data ->> 'ctr_72h'), ',' ORDER BY item_key COLLATE "C")
      INTO got FROM workbench.snapshot_items
     WHERE day = DATE '2026-11-25' AND block = 'watch_72h' AND project_id = 'CI_WB_A';
    IF got IS DISTINCT FROM 'CI_WB_A_x1:2:500:0.100,CI_WB_A_x2:1:800:0.050' THEN
        RAISE EXCEPTION 'E: 72h 排序不对 (不到 96 小时的、过了中位数的不该进), 实得 %', got;
    END IF;
    SELECT b3b INTO j FROM wb_seen_status WHERE project_id = 'CI_WB_A';
    IF j IS DISTINCT FROM '{"recent_notes": 16, "with_72h": 4, "too_early": 1, "no_impressions": 0, "above_median": 1,
                           "candidates": 2, "status": "有"}'::jsonb THEN
        RAISE EXCEPTION 'E: CI_WB_A 的 b3b 计数不对, 实得 %', j;
    END IF;
END $$;

-- ═══ F 块 4 ═══════════════════════════════════════════════════════════
DO $$
DECLARE
    got TEXT;
    j   JSONB;
BEGIN
    SELECT string_agg(item_key || ':' || coalesce(data ->> 'hour_bj', '-') || ':' || (data ->> 'hour_status') || ':'
                      || coalesce(data ->> 'evening', '-') || ':' || coalesce(data ->> 'weekend', '-') || ':' || coalesce(data ->> 'same_acct_3d', '-'),
                      ',' ORDER BY item_key COLLATE "C")
      INTO got FROM workbench.snapshot_items
     WHERE day = DATE '2026-11-25' AND block = 'exposure_hints' AND item_key IN ('CI_WB_A_e1', 'CI_WB_A_e2', 'CI_WB_A_e3', 'CI_WB_A_e4', 'CI_WB_A_null_g6');
    IF got IS DISTINCT FROM 'CI_WB_A_e1:20:知道:true:false:true,CI_WB_A_e2:10:知道:false:true:false,CI_WB_A_e3:-:日期对不上:-:-:false,CI_WB_A_e4:-:没有笔记 ID:-:false:false,CI_WB_A_null_g6:-:没有笔记 ID:-:false:-' THEN
        RAISE EXCEPTION 'F: 三条提示不对, 实得 %', got;
    END IF;
    SELECT b4 INTO j FROM wb_seen_status WHERE project_id = 'CI_WB_A';
    IF j IS DISTINCT FROM '{"notes_14d": 26, "evening": 1, "weekend": 6, "same_acct_3d": 4, "any_hint": 9, "hour_unknown": 24,
                           "date_mismatch": 1, "no_account": 1, "status": "有"}'::jsonb THEN
        RAISE EXCEPTION 'F: CI_WB_A 的 b4 计数不对, 实得 %', j;
    END IF;
    -- 笔记 ID 的来源: 顶层先于 _undeclared; _undeclared 的也要日期对得上; 抖音帖不还原 (NULL, 不是 0)
    SELECT string_agg(item_key || ':' || coalesce(data ->> 'hour_bj', '-') || ':' || (data ->> 'hour_status') || ':'
                      || coalesce(data ->> 'evening', '-') || ':' || coalesce(data ->> 'weekend', '-') || ':' || coalesce(data ->> 'same_acct_3d', '-'),
                      ',' ORDER BY item_key COLLATE "C")
      INTO got FROM workbench.snapshot_items
     WHERE day = DATE '2026-11-25' AND block = 'exposure_hints' AND project_id = 'CI_WB_D';
    IF got IS DISTINCT FROM 'CI_WB_D_dy:-:抖音帖不还原:-:true:-,CI_WB_D_u1:19:知道:true:false:-,CI_WB_D_u2:9:知道:false:false:-,CI_WB_D_u3:-:日期对不上:-:-:-' THEN
        RAISE EXCEPTION 'F: 笔记 ID 的来源 (顶层 → _undeclared、只认小红书) 不对, 实得 %', got;
    END IF;
    IF EXISTS (SELECT 1 FROM workbench.snapshot_items
                WHERE day = DATE '2026-11-25' AND block = 'exposure_hints' AND item_key = 'CI_WB_D_dy' AND data -> 'hour_bj' IS DISTINCT FROM 'null'::jsonb) THEN
        RAISE EXCEPTION 'F: 抖音帖的小时该是 JSON null (不知道), 不是 0';
    END IF;
    SELECT b4 INTO j FROM wb_seen_status WHERE project_id = 'CI_WB_D';
    IF j IS DISTINCT FROM '{"notes_14d": 4, "evening": 1, "weekend": 1, "same_acct_3d": 0, "any_hint": 2, "hour_unknown": 2,
                           "date_mismatch": 1, "no_account": 4, "status": "有"}'::jsonb THEN
        RAISE EXCEPTION 'F: CI_WB_D 的 b4 计数不对, 实得 %', j;
    END IF;
    IF (SELECT string_agg(hour_status || ':' || coalesce(hour_bj::text, '-'), ',' ORDER BY hour_status COLLATE "C", hour_bj)
          FROM wb_seen_hints WHERE project_id = 'CI_WB_D') IS DISTINCT FROM '抖音帖不还原:-,日期对不上:-,知道:9,知道:19' THEN
        RAISE EXCEPTION 'F: v_exposure_hints 里 CI_WB_D 的小时 / 状态不对';
    END IF;
END $$;

-- ═══ G 块 5 ═══════════════════════════════════════════════════════════
DO $$
BEGIN
    IF (SELECT count(*) FROM wb_seen_boost) <> 1
       OR (SELECT boost_date FROM wb_seen_boost) <> DATE '2026-11-20'
       OR (SELECT days_after_publish FROM wb_seen_boost) <> 5
       OR (SELECT event_code !~ '^[0-9a-f]{8}$' OR note_code !~ '^[0-9a-f]{8}$' FROM wb_seen_boost) THEN
        RAISE EXCEPTION 'G: 投流事件不对';
    END IF;
    IF EXISTS (SELECT 1 FROM wb_seen_boost
                WHERE comments_base IS NOT NULL OR comments_d1 IS NOT NULL OR comments_d7 IS NOT NULL
                   OR impressions_base IS NOT NULL OR impressions_d7 IS NOT NULL OR comments_base_status = 'ok') THEN
        RAISE EXCEPTION 'G: 没有读数的点该是 NULL (不补 0)';
    END IF;
    IF (SELECT b5 ->> 'status' FROM wb_seen_status WHERE project_id = 'CI_WB_C') IS DISTINCT FROM '近 30 天没有投流记录' THEN
        RAISE EXCEPTION 'G: CI_WB_C 该写「近 30 天没有投流记录」';
    END IF;
END $$;

-- ═══ H 影子核对 ═══════════════════════════════════════════════════════
DO $$
DECLARE
    got TEXT;
BEGIN
    SELECT string_agg(block || ':' || n, ',' ORDER BY block COLLATE "C") INTO got
      FROM (SELECT block, count(*) AS n FROM workbench.snapshot_items WHERE day = DATE '2026-11-25' GROUP BY block) x;
    IF got IS DISTINCT FROM (SELECT string_agg(block || ':' || n, ',' ORDER BY block COLLATE "C") FROM wb_first_pass) THEN
        RAISE EXCEPTION 'H: 同一天重跑之后行数变了: % (第一遍 %)', got, (SELECT string_agg(block || ':' || n, ',' ORDER BY block COLLATE "C") FROM wb_first_pass);
    END IF;
    IF (SELECT count(*) FROM workbench.snapshot_outcomes) <> (SELECT n FROM wb_outcomes_first) THEN
        RAISE EXCEPTION 'H: 同一天重跑又记了一遍结果';
    END IF;
    IF (SELECT count(*) FROM workbench.snapshot_runs) <> 2 THEN RAISE EXCEPTION 'H: 应该正好两份快照 (11-15、11-25)'; END IF;
    SELECT string_agg(note_id || ':' || coalesce(acct_group, '-'), ',' ORDER BY note_id COLLATE "C") INTO got
      FROM workbench.snapshot_outcomes
     WHERE mark = 7 AND recorded_day = DATE '2026-11-25' AND project_id LIKE 'CI\_WB\_%';
    IF got IS DISTINCT FROM 'CI_WB_A_b1:-,CI_WB_A_dg_g3:降档,CI_WB_A_f01:-,CI_WB_A_f02:-,CI_WB_A_f03:-,CI_WB_A_f04:-,CI_WB_A_f05:-,CI_WB_A_f06:-,'
                            'CI_WB_A_fill_g4:名单外有历史,CI_WB_A_g5:新号,CI_WB_A_null_g6:没有账号,CI_WB_A_t1_g2:一档,CI_WB_A_t2_g1:二档,'
                            'CI_WB_A_t2dg_pa:-,CI_WB_A_x4:新号,CI_WB_C_p1:没有账号,CI_WB_C_p2:没有账号' THEN
        RAISE EXCEPTION 'H: 满 7 天那一笔的账号分组不对, 实得 %', got;
    END IF;
    SELECT string_agg(note_id || ':' || recorded_day || ':' || days_since, ',' ORDER BY note_id COLLATE "C") INTO got
      FROM workbench.snapshot_outcomes
     WHERE mark = 7 AND recorded_day = DATE '2026-11-15' AND project_id LIKE 'CI\_WB\_%'
       AND note_id IN ('CI_WB_A_t1_hit', 'CI_WB_A_dg_pa', 'CI_WB_A_f07', 'CI_WB_A_f14');
    IF got IS DISTINCT FROM 'CI_WB_A_dg_pa:2026-11-15:8,CI_WB_A_f07:2026-11-15:7,CI_WB_A_f14:2026-11-15:14,CI_WB_A_t1_hit:2026-11-15:10' THEN
        RAISE EXCEPTION 'H: 11-15 那一份记的满 7 天不对 (漏了要补、记实际第几天), 实得 %', got;
    END IF;
    IF EXISTS (SELECT 1 FROM workbench.snapshot_outcomes WHERE note_id = 'CI_WB_A_f15') THEN
        RAISE EXCEPTION 'H: 第一份快照前 14 天以前发的帖不该记';
    END IF;
    SELECT string_agg(grp || ':' || n || '/' || n_yes, ',' ORDER BY grp COLLATE "C") INTO got
      FROM wb_seen_shadow WHERE block = '1' AND measure = '满 7 天过评论线';
    IF got IS DISTINCT FROM '二档:1/1,名单外有历史:1/0,新号:0/0,没有账号:1/0,降档:1/0' THEN
        RAISE EXCEPTION 'H: 块 1 的影子核对 (准时记的) 不对, 实得 %', got;
    END IF;
    -- t1_g2、g5 是 9 天前发的, 11-25 才记 (第 9 天): 晚记, 单独一行
    SELECT string_agg(grp || ':' || n || '/' || n_yes, ',' ORDER BY grp COLLATE "C") INTO got
      FROM wb_seen_shadow WHERE block = '1' AND measure = '满 7 天过评论线（晚记：第 9 天以后才记）';
    IF got IS DISTINCT FROM '一档:1/1,新号:1/1' THEN
        RAISE EXCEPTION 'H: 块 1 晚记的那一行不对, 实得 %', got;
    END IF;
    -- 「已定级为爆」只数定级为爆 / 趴的: 名单外有历史那一组只有 fill_g4 (评估中), n 该是 0
    --   (没有账号那一组混着别的 CI 步骤留下的帖, 不在这里核)
    IF (SELECT n FROM wb_seen_shadow WHERE block = '1' AND grp = '名单外有历史' AND measure = '已定级为爆') IS DISTINCT FROM 0 THEN
        RAISE EXCEPTION 'H: 「已定级为爆」把没定级的帖 (评估中) 算成了没爆';
    END IF;
    SELECT string_agg(note_id || ':' || coalesce(tier, '-') || ':' || coalesce(hit::text, '-'), ',' ORDER BY note_id COLLATE "C") INTO got
      FROM workbench.snapshot_outcomes
     WHERE mark = 7 AND note_id IN ('CI_WB_A_fill_g4', 'CI_WB_A_t2dg_pa', 'CI_WB_A_t1_hit', 'CI_WB_A_dg_g3');
    IF got IS DISTINCT FROM 'CI_WB_A_dg_g3:-:-,CI_WB_A_fill_g4:评估中:-,CI_WB_A_t1_hit:爆:true,CI_WB_A_t2dg_pa:趴:false' THEN
        RAISE EXCEPTION 'H: snapshot_outcomes.hit 不对 (爆 TRUE、趴 FALSE、没定级 NULL), 实得 %', got;
    END IF;
END $$;

-- ═══ 清理 ═════════════════════════════════════════════════════════════
TRUNCATE workbench.snapshot_runs, workbench.snapshot_items, workbench.snapshot_outcomes;
DELETE FROM truth_vault.comments WHERE project_id LIKE 'CI\_WB\_%';
DELETE FROM truth_vault.note_feature_answers WHERE subject_id LIKE 'CI\_WB\_%';
DELETE FROM truth_vault.metric_snapshots WHERE note_id LIKE 'CI\_WB\_%';
DELETE FROM truth_vault.note_sync_runs WHERE project_id LIKE 'CI\_WB\_%';
DELETE FROM truth_vault.notes WHERE project_id LIKE 'CI\_WB\_%';
DELETE FROM truth_vault.projects WHERE project_id LIKE 'CI\_WB\_%';
DELETE FROM truth_vault.accounts WHERE account_id LIKE 'ci\_wb\_%';
DELETE FROM truth_vault.audit_log WHERE row_id LIKE 'CI\_WB\_%' OR row_id LIKE 'ci\_wb\_%';
\echo 'check_workbench_pg: 权限 / 五块 / 影子核对 / 打码 全过'
