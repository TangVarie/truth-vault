-- workbench v1 · 工作台：运营每天一页的取数 (W-63, D-169, docs/35-workbench.md, 2026-11-25)
-- ════════════════════════════════════════════════════════════════════
-- 这份 SQL 全是加法, 不改任何已有的表、列、视图、函数:
--   ① schema workbench                        放工作台的一切。不加进 Supabase 的 Exposed schemas (PostgREST 碰不到)。
--   ② 表 workbench.mask_salt                   一行, 打码的盐。值在库里随机生成, 不进文件。谁都不给授权, 只有视图属主读得到。
--   ③ 表 workbench.snapshot_runs               每个北京日一行: 快照时刻、规则版本、每个活跃项目的数据截至和每块的计数、状态词。
--   ④ 表 workbench.snapshot_items              当天五块的每一行 (带内部的 note_id / account_id, 给影子核对接后来的结果)。不出库。
--   ⑤ 表 workbench.snapshot_outcomes           发布满 7 天、满 14 天的帖各记一笔 (docs/35 第 2.0.1 节)。
--   ⑥ 函数 truth_vault.workbench_take_snapshot 按 docs/35 第 2 节的规则算当天五块, 写进 ③④⑤; 同一天重跑就替换当天; 删 90 天前的。
--   ⑦ 九个视图 workbench.v_*                   看板读的那一面: 只出打过码的列 (8 位码、名字提示), 不出 account_id / note_id / 链接 / 正文。
--   ⑧ 角色 tv_workbench_ro                     看板服务端读视图的身份。建成没有密码; 只给 workbench 的 USAGE 和九个视图的 SELECT。
--
-- 谁能用:
--   · 四张表开行级安全、没有策略; PUBLIC / anon / authenticated / tv_workbench_ro 都没有授权。
--   · 函数 EXECUTE 只给 service_role (每天的快照那一步用它)。函数的 PUBLIC EXECUTE 是 Postgres 内置的默认, 单独 REVOKE。
--   · 视图 SELECT 只给 tv_workbench_ro。anon / authenticated 连 schema 的 USAGE 都没有。
--   · tv_workbench_ro 不加进 authenticator (PostgREST 切不到它), 不给 truth_vault 的 USAGE。
--
-- 怎么跑: owner 在 Supabase SQL editor 整份跑一次。可以重跑 (表 IF NOT EXISTS, 函数和视图 CREATE OR REPLACE, 盐只在没有时生成,
--   角色只在没有时建, 权限和注释覆盖写)。要在 v1.12 (comments_count)、v1.13 (答案表)、v1.22 (投流证据)、v1.25 (同步记录)、
--   v1.27 (评论来源) 之后跑; 生产都已经跑过。
-- 跑完之后 owner 还要做三件 (docs/35 第 4 节): 给 tv_workbench_ro 设密码、Vercel 加 WORKBENCH_DATABASE_URL、
--   Vercel 加 WORKBENCH_PASSWORD。
-- 设密码: 密码只用字母和数字, 32 位以上 (别的字符会弄坏连接串)。不要在 SQL editor 里写明文密码: 生产库 log_statement = ddl,
--   ALTER ROLE 那一句会原样进 Postgres 日志。在本机跑 python3 scripts/workbench_role_password.py, 它生成密码和 SCRAM 校验串,
--   把它打出来的那一句 (只有校验串, 没有明文) 贴进 SQL editor; 明文只填进 Vercel。
-- 每天谁调快照: 还没有。v0 先手动在 SQL editor 跑 select truth_vault.workbench_take_snapshot(); 每天的 workflow 是下一个 PR。
-- 参数 p_day 只给 CI 的合成数据用: 它按今天库里的数算「那一天」, 不是回放历史。真跑不传。
--
-- 这份 SQL 就是开关: 没跑之前页面写「还没建」。要撤:
--   DROP FUNCTION truth_vault.workbench_take_snapshot(DATE);
--   DROP SCHEMA workbench CASCADE;
--   DROP ROLE tv_workbench_ro;   (先在 Vercel 删掉 WORKBENCH_DATABASE_URL)
-- 夹具与反证: scripts/check_workbench_pg.sql (ci.yml sql job, 真 Postgres); 规则常量和文档对得上: scripts/check_workbench.py。
-- ════════════════════════════════════════════════════════════════════
BEGIN;

-- ── ① schema ───────────────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS workbench;
COMMENT ON SCHEMA workbench IS
    '工作台 (W-63, D-169, docs/35)。不加进 PostgREST 的 Exposed schemas。只有 tv_workbench_ro 有 USAGE, 只读打过码的视图。';

-- ── ② 盐 ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workbench.mask_salt (
    id         BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id),
    salt       BYTEA NOT NULL CHECK (octet_length(salt) = 32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- 两个随机 uuid 拼起来再 sha256, 得到 32 字节。已经有一行就不动: 换盐等于所有码一起变, 影子期前后接不上。
INSERT INTO workbench.mask_salt (salt)
SELECT sha256(convert_to(gen_random_uuid()::text || gen_random_uuid()::text, 'UTF8'))
ON CONFLICT (id) DO NOTHING;
ALTER TABLE workbench.mask_salt ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE workbench.mask_salt IS
    '打码的盐, 一行 32 字节 (workbench v1)。值不进文件、不进仓; 谁都不给授权, 只有视图属主读得到。影子期不换。';

-- ── ③ 每天一行 ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workbench.snapshot_runs (
    day          DATE PRIMARY KEY,
    taken_at     TIMESTAMPTZ NOT NULL,
    took_ms      INT,
    rule_version TEXT NOT NULL,
    projects     JSONB NOT NULL DEFAULT '[]'::jsonb
);
ALTER TABLE workbench.snapshot_runs ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE workbench.snapshot_runs IS
    '工作台快照, 每个北京日一行 (workbench v1)。projects = 每个活跃项目一项: 数据截至 (最近一次跑完的同步)、近 30 天几篇、'
    '最近一篇的日期、曝光中位数, 和 b1..b5 每块的计数与状态词 (为什么空)。同一天重跑就整行替换。';

-- ── ④ 当天五块的每一行 ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workbench.snapshot_items (
    day        DATE NOT NULL REFERENCES workbench.snapshot_runs(day) ON DELETE CASCADE,
    block      TEXT NOT NULL CHECK (block IN ('accounts', 'content_counts', 'content_notes', 'watch_24h', 'watch_72h',
                                              'exposure_hints', 'boost_curves')),
    project_id TEXT NOT NULL,
    item_key   TEXT NOT NULL,
    note_id    TEXT,
    account_id TEXT,
    data       JSONB NOT NULL,
    PRIMARY KEY (day, block, project_id, item_key)
);
CREATE INDEX IF NOT EXISTS idx_wb_items_note ON workbench.snapshot_items (note_id) WHERE note_id IS NOT NULL;
ALTER TABLE workbench.snapshot_items ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE workbench.snapshot_items IS
    '工作台快照的每一行 (workbench v1)。item_key 是内部键 (账号 / 帖 / 写法 / 投流事件), note_id、account_id 是原值: '
    '只给影子核对接后来的结果, 不出库; 看板只读 v_* 视图里打过码的列。';

-- ── ⑤ 满 7 天、满 14 天各记一笔 ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workbench.snapshot_outcomes (
    note_id            TEXT NOT NULL,
    mark               SMALLINT NOT NULL CHECK (mark IN (7, 14)),
    project_id         TEXT NOT NULL,
    publish_day        DATE NOT NULL,
    recorded_day       DATE NOT NULL,
    days_since         INT NOT NULL,
    comments_count     INT,
    over_line          BOOLEAN,
    tier               TEXT,
    hit                BOOLEAN,
    impressions        INT,
    median_impressions NUMERIC,
    expo_hi            BOOLEAN,
    seeded_known       INT NOT NULL DEFAULT 0,
    boosted            BOOLEAN NOT NULL DEFAULT FALSE,
    acct_group         TEXT CHECK (acct_group IN ('一档', '二档', '降档', '名单外有历史', '新号', '没有账号')),
    acct_group_day     DATE,
    PRIMARY KEY (note_id, mark)
);
ALTER TABLE workbench.snapshot_outcomes ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE workbench.snapshot_outcomes IS
    '影子核对用的结果 (workbench v1, docs/35 第 2.0.1 节): 活跃项目里发布满 7 天、满 14 天的帖各记一笔, 满了之后第一次快照记, '
    '漏了就下一次补, days_since 是实际第几天 (比满的那天晚 2 天以上的, 影子核对单独数「晚记」)。over_line = 评论数 ≥45 (含铺评); '
    'hit = 定级为爆或大爆 TRUE、趴 FALSE、没定级 NULL; expo_hi = 曝光高于当天记下的本项目曝光中位数; '
    'boosted = 影子期里 (第一份快照那天起) 有投流记录; acct_group = 发布前最近一份快照里发帖号的档 (只记在满 7 天那一笔)。';


-- ── ⑥ 每天的快照 ───────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION truth_vault.workbench_take_snapshot(p_day DATE DEFAULT NULL)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
SET client_min_messages = warning
AS $fn$
DECLARE
    -- 规则常量 (docs/35 第 2 节)。scripts/check_workbench.py 钉住它们和文档一致; 改了要升 c_rule_version。
    c_rule_version   CONSTANT TEXT    := 'wb-v1';
    c_active_days    CONSTANT INT     := 30;    -- 活跃项目: 近 30 天 (含今天) 有北京发布日期的帖
    c_hit_lag_days   CONSTANT INT     := 7;     -- 块 1: 爆或大爆要 ≥7 天前发; 块 2 过评论线只数 ≥7 天前发、已定级的帖
    c_tier2_days     CONSTANT INT     := 90;    -- 块 1: 二档只列近 90 天在任何项目发过帖的
    c_tier2_max      CONSTANT INT     := 50;    -- 块 1: 二档最多列 50 个
    c_line_comments  CONSTANT INT     := 45;    -- 评论线: 评论数 ≥45 条 (含铺评)
    c_expo_lag_days  CONSTANT INT     := 14;    -- 曝光过中位数: 只数 ≥14 天前发的帖
    c_notes_days     CONSTANT INT     := 14;    -- 块 2 每篇列表、块 4: 近 14 天 (含今天)
    c_watch24_days   CONSTANT INT     := 5;     -- 块 3a: 近 5 天 (含今天) 发、有 24h 快照
    c_min_prior      CONSTANT INT     := 20;    -- 块 3a: 本项目更早的帖 ≥20 篇有 24h 评论数才算
    c_mid_rank       CONSTANT NUMERIC := 0.9;   -- 块 3a: mid_rank ≥ 0.9 (本项目前 10%) 进清单
    c_p90            CONSTANT NUMERIC := 0.9;   -- 块 3a: 另记的第 90 百分位 (W-64 原写的线, 只作参考; 页面上的线是 line_now)
    c_watch72_days   CONSTANT INT     := 8;     -- 块 3b: 近 8 天 (含今天)
    c_min_hours72    CONSTANT INT     := 96;    -- 块 3b: 「72h」快照在日期戳后 ≥96 小时拍的才用
    c_evening_hour   CONSTANT INT     := 18;    -- 块 4: 北京时间 18 点以后发
    c_same_acct_days CONSTANT INT     := 3;     -- 块 4: 同项目同账号, 另一篇在本篇前 3 天到当天之间
    c_boost_days     CONSTANT INT     := 30;    -- 块 5: 近 30 天 (含今天) 投过流的事件
    c_keep_days      CONSTANT INT     := 90;    -- 快照留 90 天
    v_d0       DATE := coalesce(p_day, (now() AT TIME ZONE 'Asia/Shanghai')::date);
    v_t0       TIMESTAMPTZ := clock_timestamp();
    v_first    DATE;
    v_outcomes INT;
    v_projects JSONB;
    v_counts   JSONB;
BEGIN
    -- 同时来两趟只让一趟算
    PERFORM pg_advisory_xact_lock(hashtext('workbench_take_snapshot'));

    -- 同一天重跑: 整天替换 (items 跟着 CASCADE 删)
    DELETE FROM workbench.snapshot_runs WHERE day = v_d0;
    INSERT INTO workbench.snapshot_runs (day, taken_at, rule_version) VALUES (v_d0, v_t0, c_rule_version);
    -- 留 90 天 (先删, 下面「第一份快照」才不会算到删掉的那天)
    DELETE FROM workbench.snapshot_runs WHERE day < v_d0 - c_keep_days;
    DELETE FROM workbench.snapshot_outcomes WHERE recorded_day < v_d0 - c_keep_days;

    DROP TABLE IF EXISTS pg_temp.wb_nb, pg_temp.wb_active, pg_temp.wb_lab, pg_temp.wb_seed, pg_temp.wb_s24, pg_temp.wb_s72;

    -- 帖的底表: 北京日期 = (publish_time + 8h)::date; 爆 = 爆 / 大爆, 趴 = 趴, 其他不算已定级
    CREATE TEMP TABLE wb_nb ON COMMIT DROP AS
    SELECT n.note_id, n.project_id, n.account_id,
           coalesce(n.platform, p.platform) AS platform,
           (n.publish_time + interval '8 hours')::date AS bj_date,
           CASE WHEN n.tier IN ('爆', '大爆') THEN 1 WHEN n.tier = '趴' THEN 0 END AS hit,
           n.tier, n.comments_count, n.impressions, n.reads, n.emotional_valence, n.content_format
    FROM truth_vault.notes n
    JOIN truth_vault.projects p ON p.project_id = n.project_id
    WHERE n.publish_time IS NOT NULL
      AND (n.publish_time + interval '8 hours')::date <= v_d0;

    -- 活跃项目: 近 30 天 (含今天) 有帖。曝光中位数 = 本项目所有有曝光的帖 (和 W-64 一致)
    CREATE TEMP TABLE wb_active ON COMMIT DROP AS
    SELECT p.project_id, p.platform,
           count(*) FILTER (WHERE nb.bj_date > v_d0 - c_active_days) AS posts_30d,
           max(nb.bj_date) AS last_post_day,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY nb.impressions) AS median_impressions,
           (SELECT max(r.completed_at) FROM truth_vault.note_sync_runs r
             WHERE r.project_id = p.project_id AND r.completed_at IS NOT NULL) AS data_as_of
    FROM truth_vault.projects p
    JOIN pg_temp.wb_nb nb ON nb.project_id = p.project_id
    GROUP BY p.project_id, p.platform
    HAVING count(*) FILTER (WHERE nb.bj_date > v_d0 - c_active_days) > 0;

    -- 库里已知的铺评条数: 运营贴的素人评论 (source 为空)。发出时间不明, 只作参考
    CREATE TEMP TABLE wb_seed ON COMMIT DROP AS
    SELECT c.note_id, count(*)::int AS n
    FROM truth_vault.comments c
    WHERE c.comment_role = '素人' AND c.source IS NULL
      AND c.note_id IN (SELECT nb.note_id FROM pg_temp.wb_nb nb JOIN pg_temp.wb_active a ON a.project_id = nb.project_id
                        WHERE nb.bj_date > v_d0 - c_active_days)
    GROUP BY c.note_id;

    -- ══ 块 1 · 账号底子 ══════════════════════════════════════════════════
    -- 一档: 本项目有一篇 ≥7 天前发、已定级为爆或大爆的帖。二档: 不是一档; 同平台的其他项目有一篇 ≥7 天前发的爆或大爆。
    -- 降档: 本项目有 ≥7 天前发且已定级的帖、本项目一篇都没爆。账号历史只算和项目同平台的帖。
    -- 一档、二档、降档的号全记 (影子核对要按档分组); 页面只列 listed 的: 一档全部, 二档近 90 天发过帖的前 50 个。
    INSERT INTO workbench.snapshot_items (day, block, project_id, item_key, account_id, data)
    WITH here AS (
        SELECT nb.project_id, nb.account_id,
               count(*) AS posts_here,
               count(*) FILTER (WHERE nb.hit IS NOT NULL) AS graded_here,
               count(*) FILTER (WHERE nb.hit = 1) AS hits_here,
               count(*) FILTER (WHERE nb.hit IS NOT NULL AND nb.bj_date <= v_d0 - c_hit_lag_days) AS graded_lag,
               count(*) FILTER (WHERE nb.hit = 1 AND nb.bj_date <= v_d0 - c_hit_lag_days) AS hits_lag,
               max(nb.bj_date) AS last_post_here
        FROM pg_temp.wb_nb nb
        JOIN pg_temp.wb_active a ON a.project_id = nb.project_id AND a.platform = nb.platform
        WHERE nb.account_id IS NOT NULL
        GROUP BY nb.project_id, nb.account_id
    ), other AS (
        SELECT DISTINCT a.project_id, nb.account_id
        FROM pg_temp.wb_active a
        JOIN pg_temp.wb_nb nb ON nb.project_id <> a.project_id AND nb.platform = a.platform
        WHERE nb.account_id IS NOT NULL AND nb.hit = 1 AND nb.bj_date <= v_d0 - c_hit_lag_days
    ), last_any AS (
        SELECT nb.account_id, nb.platform, max(nb.bj_date) AS last_any
        FROM pg_temp.wb_nb nb WHERE nb.account_id IS NOT NULL
        GROUP BY nb.account_id, nb.platform
    ), u AS (
        SELECT coalesce(h.project_id, o.project_id) AS project_id,
               coalesce(h.account_id, o.account_id) AS account_id,
               coalesce(h.posts_here, 0) AS posts_here, coalesce(h.graded_here, 0) AS graded_here,
               coalesce(h.hits_here, 0) AS hits_here, coalesce(h.graded_lag, 0) AS graded_lag,
               coalesce(h.hits_lag, 0) AS hits_lag, h.last_post_here,
               (o.account_id IS NOT NULL) AS other_hit
        FROM here h
        FULL JOIN other o ON o.project_id = h.project_id AND o.account_id = h.account_id
    ), t AS (
        SELECT u.*,
               CASE WHEN u.hits_lag > 0 THEN '一档' WHEN u.other_hit THEN '二档' END AS tier,
               (u.graded_lag > 0 AND u.hits_here = 0) AS downgrade,
               la.last_any,
               coalesce(la.last_any > v_d0 - c_tier2_days, FALSE) AS recent
        FROM u
        JOIN pg_temp.wb_active a ON a.project_id = u.project_id
        LEFT JOIN last_any la ON la.account_id = u.account_id AND la.platform = a.platform
    ), t2 AS (
        SELECT t.*,
               row_number() OVER (PARTITION BY t.project_id, (t.tier = '二档' AND t.recent)
                                  ORDER BY t.last_any DESC NULLS LAST, t.account_id) AS rn_recent
        FROM t
        WHERE t.tier IS NOT NULL OR t.downgrade
    ), t3 AS (
        SELECT t2.*,
               (t2.tier = '一档' OR (t2.tier = '二档' AND t2.recent AND t2.rn_recent <= c_tier2_max)) IS TRUE AS listed
        FROM t2
    )
    SELECT v_d0, 'accounts', t3.project_id, t3.account_id, t3.account_id,
           jsonb_build_object(
               'tier', t3.tier, 'downgrade', t3.downgrade, 'recent', t3.recent, 'listed', t3.listed,
               'rank', row_number() OVER (PARTITION BY t3.project_id
                                          ORDER BY t3.listed DESC,
                                                   CASE t3.tier WHEN '一档' THEN 0 WHEN '二档' THEN 1 ELSE 2 END,
                                                   CASE WHEN t3.tier = '一档' THEN t3.hits_here END DESC NULLS LAST,
                                                   t3.last_any DESC NULLS LAST, t3.account_id),
               'posts_here', t3.posts_here, 'graded_here', t3.graded_here, 'hits_here', t3.hits_here,
               'other_hit', t3.other_hit, 'last_post_here', t3.last_post_here)
    FROM t3;

    -- ══ 块 2 · 写法提示 ══════════════════════════════════════════════════
    -- 标签: note_feature_answers 的 primary、答案有效、每道题取最新一次; 情绪基调和内容形式在 notes 上。
    --   抽取器钉住: 代码题只认 code:v1, 模型题认 llm:*。G-24 回填的 code:v2 行更新, 不钉就会盖掉 v1,
    --   「不提品牌」悄悄换口径 (今天夜跑只给新帖写 v1, 两种会混着用)。换不换 v2 是 G-24 PR-2 的事, 到时改这里。
    -- 没标 = NULL, 两边都不算, 另数。绝不当成「没有这种写法」。
    -- 抽特征那一次正文是空的 (note_features.body_len = 0; 一篇一行, 每次主题库抽取都覆盖写, 和答案同一趟落库):
    --   代码题看空正文必然答「未出现」, 模型题 (范围是标题 + 正文) 只看到了标题。这四道答案题都按没标算。
    --   正文后来补了、还没重抽的帖就是这种 (11-25 活跃项目里 16 篇)。重抽之后 body_len 跟着变, 这里自动恢复。
    CREATE TEMP TABLE wb_lab ON COMMIT DROP AS
    WITH fa AS (
        SELECT DISTINCT ON (f.subject_id, f.question_id) f.subject_id AS note_id, f.question_id, f.answer
        FROM truth_vault.note_feature_answers f
        WHERE f.subject_type = 'note' AND f.run_tag = 'primary'
          AND f.invalid_reason IS NULL AND f.answer IS NOT NULL
          AND (f.extractor = 'code:v1' OR f.extractor LIKE 'llm:%')
          AND f.question_id IN ('brand_first_position', 'product_role', 'asks_for_help', 'efficacy_promise')
          AND f.subject_id IN (SELECT nb.note_id FROM pg_temp.wb_nb nb JOIN pg_temp.wb_active a ON a.project_id = nb.project_id)
        ORDER BY f.subject_id, f.question_id, f.extracted_at DESC, f.question_version DESC
    ), piv AS (
        SELECT fa.note_id,
               max(fa.answer) FILTER (WHERE fa.question_id = 'brand_first_position') AS bfp,
               max(fa.answer) FILTER (WHERE fa.question_id = 'product_role') AS prole,
               max(fa.answer) FILTER (WHERE fa.question_id = 'asks_for_help') AS afh,
               max(fa.answer) FILTER (WHERE fa.question_id = 'efficacy_promise') AS eff
        FROM fa GROUP BY fa.note_id
    )
    SELECT nb.note_id, nb.project_id, nb.account_id, nb.bj_date, nb.hit,
           CASE WHEN nb.impressions IS NULL OR a.median_impressions IS NULL THEN NULL
                ELSE nb.impressions > a.median_impressions END AS hi_expo,
           (pv.note_id IS NOT NULL AND nf.body_len = 0) AS body_empty,
           CASE WHEN pv.bfp IS NULL OR nf.body_len = 0 THEN NULL ELSE pv.bfp = '未出现' END AS f_no_brand,
           CASE WHEN pv.prole IS NULL OR nf.body_len = 0 THEN NULL ELSE pv.prole = '未出现' END AS f_no_product,
           CASE WHEN nb.emotional_valence IS NULL THEN NULL ELSE nb.emotional_valence = 'negative' END AS f_negative,
           CASE WHEN pv.afh IS NULL OR nf.body_len = 0 THEN NULL ELSE pv.afh = '是' END AS f_help,
           CASE WHEN pv.prole IS NULL OR nf.body_len = 0 THEN NULL ELSE pv.prole = '主角' END AS f_hero,
           CASE WHEN pv.prole IS NULL OR nf.body_len = 0 THEN NULL ELSE pv.prole = '解决方案' END AS f_solution,
           CASE WHEN pv.eff IS NULL OR nf.body_len = 0 THEN NULL ELSE pv.eff = '是' END AS f_efficacy,
           CASE WHEN nb.content_format IS NULL THEN NULL ELSE nb.content_format = '场景植入' END AS f_scene
    FROM pg_temp.wb_nb nb
    JOIN pg_temp.wb_active a ON a.project_id = nb.project_id
    LEFT JOIN piv pv ON pv.note_id = nb.note_id
    LEFT JOIN truth_vault.note_features nf ON nf.note_id = nb.note_id;

    -- 2a 本项目计数表: 过评论线 (定级为爆或大爆) 只数 ≥7 天前发、已定级的帖; 曝光过中位数只数 ≥14 天前发、有曝光的帖。
    -- w64 一列原样抄 W-64 的倍数 (跨项目、项目内比); 项目内只给计数, 不算倍数。
    INSERT INTO workbench.snapshot_items (day, block, project_id, item_key, data)
    SELECT v_d0, 'content_counts', l.project_id, h.hint,
           jsonb_build_object(
               'seq', h.seq, 'hint', h.hint, 'side', h.side, 'scope', h.scope, 'w64', h.w64,
               'n_flag', count(*) FILTER (WHERE h.flag),
               'n_noflag', count(*) FILTER (WHERE NOT h.flag),
               'n_unlabeled', count(*) FILTER (WHERE h.flag IS NULL),
               'graded_flag', count(*) FILTER (WHERE h.flag AND l.hit IS NOT NULL AND l.bj_date <= v_d0 - c_hit_lag_days),
               'hits_flag', count(*) FILTER (WHERE h.flag AND l.hit = 1 AND l.bj_date <= v_d0 - c_hit_lag_days),
               'graded_noflag', count(*) FILTER (WHERE NOT h.flag AND l.hit IS NOT NULL AND l.bj_date <= v_d0 - c_hit_lag_days),
               'hits_noflag', count(*) FILTER (WHERE NOT h.flag AND l.hit = 1 AND l.bj_date <= v_d0 - c_hit_lag_days),
               'expo_known_flag', count(*) FILTER (WHERE h.flag AND l.hi_expo IS NOT NULL AND l.bj_date <= v_d0 - c_expo_lag_days),
               'expo_hi_flag', count(*) FILTER (WHERE h.flag AND l.hi_expo AND l.bj_date <= v_d0 - c_expo_lag_days),
               'expo_known_noflag', count(*) FILTER (WHERE NOT h.flag AND l.hi_expo IS NOT NULL AND l.bj_date <= v_d0 - c_expo_lag_days),
               'expo_hi_noflag', count(*) FILTER (WHERE NOT h.flag AND l.hi_expo AND l.bj_date <= v_d0 - c_expo_lag_days))
    FROM pg_temp.wb_lab l
    CROSS JOIN LATERAL (VALUES
        (1, '正文不提品牌',   '加分', '过评论线和曝光',
            '同项目里，这类写法过评论线的机会约 2.0–2.6 倍（W-64，15/15 项目同向）。主要是引流稿和产品稿的差别；只在引流稿里比，不显著', l.f_no_brand),
        (2, '产品不出场',     '加分', '过评论线和曝光',
            '同项目里，这类写法过评论线的机会约 1.6–2.1 倍（W-64，14/15 项目同向；和上一条是同一维度）。主要是引流稿和产品稿的差别；只在引流稿里比，不显著', l.f_no_product),
        (3, '负面痛点基调',   '加分', '过评论线和曝光',
            '同项目里，这类写法过评论线的机会约 1.5–1.8 倍（W-64，11/17 项目同向；标注时机有疑问，只算倾向）', l.f_negative),
        (4, '求助式写法',     '加分', '只看曝光',
            '同项目里，这类写法曝光过中位数的机会约 1.3 倍（W-64，14/16 项目同向）', l.f_help),
        (5, '产品当主角',     '减分', '只看曝光',
            '同项目里，这类写法曝光过中位数的机会约 0.76 倍（W-64，12/15 项目同向）', l.f_hero),
        (6, '产品当解决方案', '减分', '只看曝光',
            '同项目里，这类写法曝光过中位数的机会约 0.73 倍（W-64，13/16 项目同向）', l.f_solution),
        (7, '功效承诺',       '减分', '只看曝光',
            '同项目里，这类写法曝光过中位数的机会约 0.6 倍（W-64，12/15 项目同向）', l.f_efficacy),
        (8, '场景植入',       '减分', '只看曝光',
            '同项目里，这类写法曝光过中位数的机会约 0.69 倍（W-64，11/16 项目同向）', l.f_scene)
    ) AS h(seq, hint, side, scope, w64, flag)
    GROUP BY l.project_id, h.seq, h.hint, h.side, h.scope, h.w64;

    -- 2b 近 14 天每篇: 带了哪些加分、减分写法, 哪几维没标
    INSERT INTO workbench.snapshot_items (day, block, project_id, item_key, note_id, account_id, data)
    SELECT v_d0, 'content_notes', l.project_id, l.note_id, l.note_id, l.account_id,
           jsonb_build_object(
               'publish_day', l.bj_date,
               'flags', jsonb_build_object('正文不提品牌', l.f_no_brand, '产品不出场', l.f_no_product,
                                           '负面痛点基调', l.f_negative, '求助式写法', l.f_help,
                                           '产品当主角', l.f_hero, '产品当解决方案', l.f_solution,
                                           '功效承诺', l.f_efficacy, '场景植入', l.f_scene),
               'plus', to_jsonb(array_remove(ARRAY[
                   CASE WHEN l.f_no_brand THEN '正文不提品牌' END,
                   CASE WHEN l.f_no_product THEN '产品不出场' END,
                   CASE WHEN l.f_negative THEN '负面痛点基调' END,
                   CASE WHEN l.f_help THEN '求助式写法（只看曝光）' END]::text[], NULL)),
               'minus', to_jsonb(array_remove(ARRAY[
                   CASE WHEN l.f_hero THEN '产品当主角' END,
                   CASE WHEN l.f_solution THEN '产品当解决方案' END,
                   CASE WHEN l.f_efficacy THEN '功效承诺' END,
                   CASE WHEN l.f_scene THEN '场景植入' END]::text[], NULL)),
               'unlabeled', to_jsonb(array_remove(ARRAY[
                   CASE WHEN l.f_no_brand IS NULL THEN '品牌位置' END,
                   CASE WHEN l.f_no_product IS NULL THEN '产品角色' END,
                   CASE WHEN l.f_negative IS NULL THEN '情绪基调' END,
                   CASE WHEN l.f_help IS NULL THEN '求助式' END,
                   CASE WHEN l.f_efficacy IS NULL THEN '功效承诺' END,
                   CASE WHEN l.f_scene IS NULL THEN '内容形式' END]::text[], NULL)),
               'body_empty', l.body_empty,
               'seeded_known', coalesce(sd.n, 0))
    FROM pg_temp.wb_lab l
    LEFT JOIN pg_temp.wb_seed sd ON sd.note_id = l.note_id
    WHERE l.bj_date > v_d0 - c_notes_days;

    -- ══ 块 3a · 24 小时评论数 ═════════════════════════════════════════════
    -- mid_rank = 比它少的占比 + 一半并列的占比, 对比本项目更早北京日期、有 24h 评论数的帖。≥0.9 进清单。
    -- 不用「≥ 第 90 百分位」: 24h 评论数多数是 0, 第 90 百分位只有 1–5 条 (docs/35 第 2.3 节)。第 90 百分位另记, 只作参考;
    -- 页面上「至少几条才进清单」读 b3a.line_now (按今天本项目更早的帖算)。
    CREATE TEMP TABLE wb_s24 ON COMMIT DROP AS
    SELECT DISTINCT ON (s.note_id) s.note_id, s.comments_count AS cc24, s.hours_since_publish AS h24
    FROM truth_vault.metric_snapshots s
    WHERE s.window_label = '24h'
      AND s.note_id IN (SELECT nb.note_id FROM pg_temp.wb_nb nb JOIN pg_temp.wb_active a ON a.project_id = nb.project_id)
    ORDER BY s.note_id, s.collected_at DESC;

    INSERT INTO workbench.snapshot_items (day, block, project_id, item_key, note_id, account_id, data)
    WITH b24 AS (
        SELECT nb.note_id, nb.project_id, nb.account_id, nb.bj_date, nb.comments_count, s.cc24, s.h24
        FROM pg_temp.wb_nb nb JOIN pg_temp.wb_s24 s ON s.note_id = nb.note_id
    ), ranked AS (
        SELECT c.*, t.n_prior, t.p90_prior, t.mid_rank
        FROM b24 c
        LEFT JOIN LATERAL (
            SELECT count(*) AS n_prior,
                   percentile_cont(c_p90) WITHIN GROUP (ORDER BY e.cc24) AS p90_prior,
                   CASE WHEN c.cc24 IS NULL OR count(*) = 0 THEN NULL
                        ELSE (count(*) FILTER (WHERE e.cc24 < c.cc24)
                              + 0.5 * count(*) FILTER (WHERE e.cc24 = c.cc24))::numeric / count(*) END AS mid_rank
            FROM b24 e
            WHERE e.project_id = c.project_id AND e.bj_date < c.bj_date AND e.cc24 IS NOT NULL
        ) t ON TRUE
        WHERE c.bj_date > v_d0 - c_watch24_days
    )
    SELECT v_d0, 'watch_24h', r.project_id, r.note_id, r.note_id, r.account_id,
           jsonb_build_object(
               'publish_day', r.bj_date, 'hours', r.h24, 'comments_24h', r.cc24,
               'n_prior', r.n_prior, 'p90_prior', r.p90_prior, 'mid_rank', round(r.mid_rank, 3),
               'status', CASE WHEN r.cc24 IS NULL THEN '24h 没记评论数'
                              WHEN r.n_prior < c_min_prior THEN format('本项目更早的帖不到 %s 篇', c_min_prior)
                              WHEN r.mid_rank >= c_mid_rank THEN '进清单'
                              ELSE '没进' END,
               'comments_now', r.comments_count, 'over_line_now', r.comments_count >= c_line_comments,
               'seeded_known', coalesce(sd.n, 0))
    FROM ranked r
    LEFT JOIN pg_temp.wb_seed sd ON sd.note_id = r.note_id;

    -- ══ 块 3b · 「72h」曝光排序 (快照实际在第 4–5 天) ═══════════════════════
    -- 候选: 近 8 天发、「72h」快照在日期戳后 ≥96 小时拍、有曝光、当时曝光还没过本项目曝光中位数。按快照曝光排, 一样的按点击率。
    CREATE TEMP TABLE wb_s72 ON COMMIT DROP AS
    SELECT s.note_id,
           coalesce(bool_or(s.hours_since_publish >= c_min_hours72), FALSE) AS ok96,
           (array_agg(s.impressions ORDER BY s.collected_at DESC) FILTER (WHERE s.hours_since_publish >= c_min_hours72))[1] AS imp72,
           (array_agg(s.reads ORDER BY s.collected_at DESC) FILTER (WHERE s.hours_since_publish >= c_min_hours72))[1] AS rd72,
           (array_agg(s.hours_since_publish ORDER BY s.collected_at DESC) FILTER (WHERE s.hours_since_publish >= c_min_hours72))[1] AS h72
    FROM truth_vault.metric_snapshots s
    WHERE s.window_label = '72h'
      AND s.note_id IN (SELECT nb.note_id FROM pg_temp.wb_nb nb JOIN pg_temp.wb_active a ON a.project_id = nb.project_id)
    GROUP BY s.note_id;

    INSERT INTO workbench.snapshot_items (day, block, project_id, item_key, note_id, account_id, data)
    WITH b72 AS (
        SELECT nb.note_id, nb.project_id, nb.account_id, nb.bj_date, nb.impressions, s.imp72, s.rd72, s.h72,
               a.median_impressions
        FROM pg_temp.wb_nb nb
        JOIN pg_temp.wb_s72 s ON s.note_id = nb.note_id AND s.ok96
        JOIN pg_temp.wb_active a ON a.project_id = nb.project_id
    ), cand AS (
        SELECT b.*, t.n_prior, t.mid_rank
        FROM b72 b
        LEFT JOIN LATERAL (
            SELECT count(*) AS n_prior,
                   CASE WHEN count(*) = 0 THEN NULL
                        ELSE (count(*) FILTER (WHERE e.imp72 < b.imp72)
                              + 0.5 * count(*) FILTER (WHERE e.imp72 = b.imp72))::numeric / count(*) END AS mid_rank
            FROM b72 e
            WHERE e.project_id = b.project_id AND e.bj_date < b.bj_date AND e.imp72 IS NOT NULL
        ) t ON TRUE
        WHERE b.bj_date > v_d0 - c_watch72_days
          AND b.imp72 IS NOT NULL AND b.median_impressions IS NOT NULL
          AND b.imp72 <= b.median_impressions
    )
    SELECT v_d0, 'watch_72h', c.project_id, c.note_id, c.note_id, c.account_id,
           jsonb_build_object(
               'publish_day', c.bj_date, 'hours', c.h72, 'impressions_72h', c.imp72, 'reads_72h', c.rd72,
               'ctr_72h', round(c.rd72::numeric / nullif(c.imp72, 0), 3),
               'median_impressions', round(c.median_impressions::numeric),
               'rank', row_number() OVER (PARTITION BY c.project_id
                                          ORDER BY c.imp72 DESC, c.rd72::numeric / nullif(c.imp72, 0) DESC NULLS LAST, c.note_id),
               'n_prior', c.n_prior,
               'mid_rank', CASE WHEN c.n_prior >= c_min_prior THEN round(c.mid_rank, 3) END,
               'impressions_now', c.impressions,
               'seeded_known', coalesce(sd.n, 0))
    FROM cand c
    LEFT JOIN pg_temp.wb_seed sd ON sd.note_id = c.note_id;

    -- ══ 块 4 · 曝光提示 (只有三条发布前提示) ═══════════════════════════════
    -- 小时只能从笔记 ID 的时间戳还原; 还原的日期和记录的日期对不上 → 不知道几点、不算周末。账号为空 → 同号连发不知道。
    -- 笔记 ID 只在这里算时间用, 不出这一步。
    -- 只认小红书帖的 24 位十六进制笔记 ID: 前 8 位 = unix 秒, 是笔记创建的时刻, 不一定是发出的时刻 (定时发的会早几天),
    --   所以还原出的北京日期要和记录的北京日期是同一天才用 (同一天里先建后定时发的, 分不出来)。
    -- 取的顺序: publish_url → raw_extra 顶层的 笔记ID / 作品ID / 笔记链接 / 链接文本 → raw_extra -> '_undeclared' 下同样四列
    --   (「作品ID」在 HATHERINE、SPX、TUGE、ANSHEN 原来没声明、收在 _undeclared 里; 批 2 (D-175) 起声明了, 夜跑后挪到顶层, 飞书里已经没有的旧帖留在 _undeclared, 所以两处都读; 值是「ID ← 短链」, 取第一段 24 位十六进制)。
    -- 抖音帖 (帖或项目的平台是 douyin) 不还原: 仓里和 W-64 都没有解抖音作品 ID 的口径, 平台也没公开 →
    --   小时是 NULL (不知道, 不当 0 点、不当白天), 状态「抖音帖不还原」; 抖音行里带着的小红书 ID (比如继承来的) 也不用。
    INSERT INTO workbench.snapshot_items (day, block, project_id, item_key, note_id, account_id, data)
    WITH r AS (
        SELECT nb.note_id, nb.project_id, nb.account_id, nb.platform, nb.bj_date, nb.impressions, a.median_impressions,
               CASE WHEN nb.platform = 'xiaohongshu' THEN
                   coalesce(substring(n.publish_url FROM '([0-9a-f]{24})'),
                            substring(n.raw_extra ->> '笔记ID' FROM '([0-9a-f]{24})'),
                            substring(n.raw_extra ->> '作品ID' FROM '([0-9a-f]{24})'),
                            substring(n.raw_extra ->> '笔记链接' FROM '([0-9a-f]{24})'),
                            substring(n.raw_extra ->> '链接文本' FROM '([0-9a-f]{24})'),
                            substring(n.raw_extra -> '_undeclared' ->> '笔记ID' FROM '([0-9a-f]{24})'),
                            substring(n.raw_extra -> '_undeclared' ->> '作品ID' FROM '([0-9a-f]{24})'),
                            substring(n.raw_extra -> '_undeclared' ->> '笔记链接' FROM '([0-9a-f]{24})'),
                            substring(n.raw_extra -> '_undeclared' ->> '链接文本' FROM '([0-9a-f]{24})'))
               END AS xid
        FROM pg_temp.wb_nb nb
        JOIN pg_temp.wb_active a ON a.project_id = nb.project_id
        JOIN truth_vault.notes n ON n.note_id = nb.note_id
        WHERE nb.bj_date > v_d0 - c_notes_days
    ), r2 AS (
        SELECT r.*,
               CASE WHEN r.xid IS NOT NULL
                    THEN to_timestamp(('x' || substr(r.xid, 1, 8))::bit(32)::bigint) AT TIME ZONE 'Asia/Shanghai' END AS id_ts
        FROM r
    ), r3 AS (
        SELECT r2.*,
               (r2.id_ts::date - r2.bj_date) AS id_day_diff,
               CASE WHEN r2.id_ts::date = r2.bj_date THEN extract(hour FROM r2.id_ts)::int END AS hr
        FROM r2
    )
    SELECT v_d0, 'exposure_hints', r3.project_id, r3.note_id, r3.note_id, r3.account_id,
           jsonb_build_object(
               'publish_day', r3.bj_date,
               'hour_bj', r3.hr,
               'hour_status', CASE WHEN r3.platform = 'douyin' THEN '抖音帖不还原'
                                   WHEN r3.xid IS NULL THEN '没有笔记 ID'
                                   WHEN r3.id_day_diff <> 0 THEN '日期对不上'
                                   ELSE '知道' END,
               'evening', CASE WHEN r3.hr IS NULL THEN NULL ELSE r3.hr >= c_evening_hour END,
               'weekend', CASE WHEN r3.id_day_diff <> 0 THEN NULL ELSE extract(isodow FROM r3.bj_date) IN (6, 7) END,
               'same_acct_3d', CASE WHEN r3.account_id IS NULL THEN NULL
                                    ELSE EXISTS (SELECT 1 FROM pg_temp.wb_nb o
                                                 WHERE o.project_id = r3.project_id AND o.account_id = r3.account_id
                                                   AND o.note_id <> r3.note_id
                                                   AND o.bj_date BETWEEN r3.bj_date - c_same_acct_days AND r3.bj_date) END,
               'impressions_now', r3.impressions,
               'median_impressions', round(r3.median_impressions::numeric),
               'seeded_known', coalesce(sd.n, 0))
    FROM r3
    LEFT JOIN pg_temp.wb_seed sd ON sd.note_id = r3.note_id;

    -- ══ 块 5 · 投流前后 ══════════════════════════════════════════════════
    -- 只读 v_paid_boost_evidence 的数值列和状态列。NULL 是缺, 不是 0; 不取运营手填的原文和效果数, 不取增量。
    INSERT INTO workbench.snapshot_items (day, block, project_id, item_key, note_id, data)
    SELECT v_d0, 'boost_curves', e.project_id, e.event_id, e.note_id,
           jsonb_build_object(
               'boost_date', e.boost_date, 'publish_day', e.publish_cn_date, 'days_after_publish', e.days_after_publish,
               'seeded_on_maintain', e.comment_maintained_seeded,
               'comments_base', e.comments_base, 'comments_base_status', e.comments_base_status,
               'comments_d0', e.comments_d0, 'comments_d0_status', e.comments_d0_status,
               'comments_d1', e.comments_d1, 'comments_d1_status', e.comments_d1_status,
               'comments_d3', e.comments_d3, 'comments_d3_status', e.comments_d3_status,
               'comments_d7', e.comments_d7, 'comments_d7_status', e.comments_d7_status,
               'impressions_base', e.impressions_base, 'impressions_base_status', e.impressions_base_status,
               'impressions_d7', e.impressions_d7, 'impressions_d7_status', e.impressions_d7_status,
               'reads_base', e.reads_base, 'reads_base_status', e.reads_base_status,
               'reads_d7', e.reads_d7, 'reads_d7_status', e.reads_d7_status)
    FROM truth_vault.v_paid_boost_evidence e
    JOIN pg_temp.wb_active a ON a.project_id = e.project_id
    WHERE e.boost_date > v_d0 - c_boost_days AND e.boost_date <= v_d0;

    -- ══ 影子核对: 满 7 天、满 14 天各记一笔 ══════════════════════════════
    -- 只记影子期能用上的帖: 发布日不早于第一份快照前 14 天, 也不早于 30 天前。已经记过的不动。
    SELECT min(r.day) INTO v_first FROM workbench.snapshot_runs r;
    INSERT INTO workbench.snapshot_outcomes (note_id, mark, project_id, publish_day, recorded_day, days_since,
                                             comments_count, over_line, tier, hit, impressions, median_impressions, expo_hi,
                                             seeded_known, boosted, acct_group, acct_group_day)
    SELECT nb.note_id, m.mark, nb.project_id, nb.bj_date, v_d0, v_d0 - nb.bj_date,
           nb.comments_count, nb.comments_count >= c_line_comments,
           nb.tier, CASE WHEN nb.tier IN ('爆', '大爆') THEN TRUE WHEN nb.tier = '趴' THEN FALSE END,
           nb.impressions, a.median_impressions,
           CASE WHEN nb.impressions IS NULL OR a.median_impressions IS NULL THEN NULL
                ELSE nb.impressions > a.median_impressions END,
           coalesce(sd.n, 0),
           EXISTS (SELECT 1 FROM workbench.snapshot_items b
                   WHERE b.day = v_d0 AND b.block = 'boost_curves' AND b.note_id = nb.note_id
                     AND (b.data ->> 'boost_date')::date >= v_first),
           CASE WHEN m.mark = 7 THEN g.grp END,
           CASE WHEN m.mark = 7 AND g.grp IS NOT NULL THEN g.gday END
    FROM pg_temp.wb_nb nb
    JOIN pg_temp.wb_active a ON a.project_id = nb.project_id
    CROSS JOIN (VALUES (7), (14)) AS m(mark)
    LEFT JOIN pg_temp.wb_seed sd ON sd.note_id = nb.note_id
    LEFT JOIN LATERAL (
        -- 块 1 分组: 按发布前最近一份快照里发帖号的档。一档 > 二档 > 降档; 名单外的看同平台此前有没有帖。
        SELECT gd.gday,
               CASE WHEN gd.gday IS NULL THEN NULL
                    WHEN nb.account_id IS NULL THEN '没有账号'
                    WHEN ai.data ->> 'tier' = '一档' THEN '一档'
                    WHEN ai.data ->> 'tier' = '二档' THEN '二档'
                    WHEN (ai.data ->> 'downgrade')::boolean THEN '降档'
                    WHEN EXISTS (SELECT 1 FROM pg_temp.wb_nb e
                                 WHERE e.account_id = nb.account_id AND e.platform = a.platform AND e.bj_date < nb.bj_date)
                         THEN '名单外有历史'
                    ELSE '新号' END AS grp
        FROM (SELECT max(rr.day) AS gday FROM workbench.snapshot_runs rr WHERE rr.day < nb.bj_date) gd
        LEFT JOIN workbench.snapshot_items ai
               ON ai.day = gd.gday AND ai.block = 'accounts' AND ai.project_id = nb.project_id AND ai.item_key = nb.account_id
    ) g ON TRUE
    WHERE nb.bj_date <= v_d0 - m.mark
      AND nb.bj_date >= greatest(v_first - c_notes_days, v_d0 - c_active_days)
    ON CONFLICT (note_id, mark) DO NOTHING;
    GET DIAGNOSTICS v_outcomes = ROW_COUNT;

    -- ══ 每个项目的计数和状态词 (页面上「为什么空」就读这里) ════════════════
    SELECT coalesce(jsonb_agg(x.j ORDER BY x.last_post_day DESC, x.project_id), '[]'::jsonb) INTO v_projects
    FROM (
        SELECT a.project_id, a.last_post_day,
               jsonb_build_object(
                   'project_id', a.project_id, 'platform', a.platform, 'posts_30d', a.posts_30d,
                   'last_post_day', a.last_post_day, 'data_as_of', a.data_as_of,
                   'median_impressions', round(a.median_impressions::numeric),
                   'b1', b1.j, 'b2', b2.j, 'b3a', b3a.j, 'b3b', b3b.j, 'b4', b4.j, 'b5', b5.j) AS j
        FROM pg_temp.wb_active a
        CROSS JOIN LATERAL (
            SELECT jsonb_build_object(
                       'tier1', c.tier1, 'tier2', c.tier2, 'tier2_recent', c.tier2_recent, 'tier2_listed', c.tier2_listed,
                       'downgrade', c.downgrade, 'new_acct_posts_30d', c.new_acct, 'no_acct_posts_30d', c.no_acct,
                       'status', CASE WHEN c.tier1 + c.tier2 = 0 THEN '本项目没有一档、二档的号'
                                      WHEN c.tier1 + c.tier2_listed = 0
                                           THEN format('没有一档；二档的号近 %s 天都没发过帖，不列', c_tier2_days)
                                      ELSE '有' END) AS j
            FROM (
                SELECT count(*) FILTER (WHERE i.data ->> 'tier' = '一档') AS tier1,
                       count(*) FILTER (WHERE i.data ->> 'tier' = '二档') AS tier2,
                       count(*) FILTER (WHERE i.data ->> 'tier' = '二档' AND (i.data ->> 'recent')::boolean) AS tier2_recent,
                       count(*) FILTER (WHERE i.data ->> 'tier' = '二档' AND (i.data ->> 'listed')::boolean) AS tier2_listed,
                       count(*) FILTER (WHERE (i.data ->> 'downgrade')::boolean) AS downgrade,
                       (SELECT count(*) FROM pg_temp.wb_nb n
                         WHERE n.project_id = a.project_id AND n.bj_date > v_d0 - c_active_days AND n.account_id IS NOT NULL
                           AND NOT EXISTS (SELECT 1 FROM pg_temp.wb_nb e
                                           WHERE e.account_id = n.account_id AND e.platform = n.platform AND e.bj_date < n.bj_date)) AS new_acct,
                       (SELECT count(*) FROM pg_temp.wb_nb n
                         WHERE n.project_id = a.project_id AND n.bj_date > v_d0 - c_active_days AND n.account_id IS NULL) AS no_acct
                FROM workbench.snapshot_items i
                WHERE i.day = v_d0 AND i.block = 'accounts' AND i.project_id = a.project_id
            ) c
        ) b1
        CROSS JOIN LATERAL (
            SELECT jsonb_build_object(
                       'graded_7d', c.graded, 'hits_7d', c.hits, 'notes_14d', c.n14,
                       'notes_14d_all_unlabeled', c.all_unl, 'notes_14d_some_unlabeled', c.some_unl,
                       'body_empty', c.body_empty, 'body_empty_14d', c.body_empty_14d,
                       'status', CASE WHEN c.n14 = 0 THEN '近 14 天没帖'
                                      WHEN c.all_unl * 2 > c.n14 THEN '多数帖没标'
                                      ELSE '有' END) AS j
            FROM (
                SELECT count(*) FILTER (WHERE l.hit IS NOT NULL AND l.bj_date <= v_d0 - c_hit_lag_days) AS graded,
                       count(*) FILTER (WHERE l.hit = 1 AND l.bj_date <= v_d0 - c_hit_lag_days) AS hits,
                       count(*) FILTER (WHERE l.bj_date > v_d0 - c_notes_days) AS n14,
                       count(*) FILTER (WHERE l.bj_date > v_d0 - c_notes_days
                                          AND l.f_no_brand IS NULL AND l.f_no_product IS NULL AND l.f_negative IS NULL
                                          AND l.f_help IS NULL AND l.f_efficacy IS NULL AND l.f_scene IS NULL) AS all_unl,
                       count(*) FILTER (WHERE l.bj_date > v_d0 - c_notes_days
                                          AND (l.f_no_brand IS NULL OR l.f_no_product IS NULL OR l.f_negative IS NULL
                                               OR l.f_help IS NULL OR l.f_efficacy IS NULL OR l.f_scene IS NULL)) AS some_unl,
                       count(*) FILTER (WHERE l.body_empty) AS body_empty,
                       count(*) FILTER (WHERE l.body_empty AND l.bj_date > v_d0 - c_notes_days) AS body_empty_14d
                FROM pg_temp.wb_lab l WHERE l.project_id = a.project_id
            ) c
        ) b2
        CROSS JOIN LATERAL (
            SELECT jsonb_build_object(
                       'recent_notes', c.recent, 'candidates', c.cand, 'no_24h', c.recent - c.cand,
                       'listed', c.listed, 'short_prior', c.short_prior, 'cc_null', c.cc_null,
                       'prior_now', c.prior_now, 'p90_now', c.p90_now, 'line_now', c.line_now,
                       'status', CASE WHEN c.recent = 0 THEN format('近 %s 天没帖', c_watch24_days)
                                      WHEN c.cand = 0 AND c.prior_now = 0 THEN '本项目没有 24h 快照'
                                      WHEN c.cand = 0 THEN format('近 %s 天的帖都没有 24h 快照', c_watch24_days)
                                      WHEN c.listed > 0 THEN '有'
                                      WHEN c.short_prior > 0 AND c.short_prior = c.cand - c.cc_null
                                           THEN format('本项目更早的帖不到 %s 篇', c_min_prior)
                                      ELSE format('近 %s 天没有帖进清单', c_watch24_days) END) AS j
            FROM (
                SELECT (SELECT count(*) FROM pg_temp.wb_nb n
                         WHERE n.project_id = a.project_id AND n.bj_date > v_d0 - c_watch24_days) AS recent,
                       count(*) AS cand,
                       count(*) FILTER (WHERE i.data ->> 'status' = '进清单') AS listed,
                       count(*) FILTER (WHERE i.data ->> 'status' LIKE '本项目更早的帖不到%') AS short_prior,
                       count(*) FILTER (WHERE i.data ->> 'status' = '24h 没记评论数') AS cc_null,
                       (SELECT count(*) FROM pg_temp.wb_nb n JOIN pg_temp.wb_s24 s ON s.note_id = n.note_id
                         WHERE n.project_id = a.project_id AND n.bj_date < v_d0 AND s.cc24 IS NOT NULL) AS prior_now,
                       (SELECT percentile_cont(c_p90) WITHIN GROUP (ORDER BY s.cc24)
                          FROM pg_temp.wb_nb n JOIN pg_temp.wb_s24 s ON s.note_id = n.note_id
                         WHERE n.project_id = a.project_id AND n.bj_date < v_d0 AND s.cc24 IS NOT NULL) AS p90_now,
                       -- 今天的线: 24h 评论数至少几条, mid_rank 才 ≥ 0.9 (按今天本项目更早的帖算; 更早的帖不到 20 篇就没有线)。
                       -- 每篇候选是和它自己发布日之前的帖比, 所以每篇的线会差一点。
                       (SELECT min(g.c)
                          FROM (SELECT array_agg(s.cc24) AS v, count(*) AS n
                                  FROM pg_temp.wb_nb n JOIN pg_temp.wb_s24 s ON s.note_id = n.note_id
                                 WHERE n.project_id = a.project_id AND n.bj_date < v_d0 AND s.cc24 IS NOT NULL) pr
                          CROSS JOIN LATERAL generate_series(0, coalesce((SELECT max(x) FROM unnest(pr.v) AS x), 0) + 1) AS g(c)
                         WHERE pr.n >= c_min_prior
                           AND ((SELECT count(*) FROM unnest(pr.v) AS x WHERE x < g.c)
                                + 0.5 * (SELECT count(*) FROM unnest(pr.v) AS x WHERE x = g.c))::numeric / pr.n >= c_mid_rank) AS line_now
                FROM workbench.snapshot_items i
                WHERE i.day = v_d0 AND i.block = 'watch_24h' AND i.project_id = a.project_id
            ) c
        ) b3a
        CROSS JOIN LATERAL (
            SELECT jsonb_build_object(
                       'recent_notes', c.recent, 'with_72h', c.with72, 'too_early', c.early, 'no_impressions', c.imp_null,
                       'above_median', c.above, 'candidates', c.cand,
                       'status', CASE WHEN c.recent = 0 THEN format('近 %s 天没帖', c_watch72_days)
                                      WHEN c.cand = 0 THEN format('近 %s 天没有还没过中位数、能比的「72h」快照', c_watch72_days)
                                      ELSE '有' END) AS j
            FROM (
                SELECT count(*) AS recent,
                       count(s.note_id) AS with72,
                       count(*) FILTER (WHERE s.note_id IS NOT NULL AND NOT s.ok96) AS early,
                       count(*) FILTER (WHERE s.ok96 AND s.imp72 IS NULL) AS imp_null,
                       count(*) FILTER (WHERE s.ok96 AND s.imp72 > a.median_impressions) AS above,
                       (SELECT count(*) FROM workbench.snapshot_items i
                         WHERE i.day = v_d0 AND i.block = 'watch_72h' AND i.project_id = a.project_id) AS cand
                FROM pg_temp.wb_nb n
                LEFT JOIN pg_temp.wb_s72 s ON s.note_id = n.note_id
                WHERE n.project_id = a.project_id AND n.bj_date > v_d0 - c_watch72_days
            ) c
        ) b3b
        CROSS JOIN LATERAL (
            SELECT jsonb_build_object(
                       'notes_14d', c.n, 'evening', c.evening, 'weekend', c.weekend, 'same_acct_3d', c.same,
                       'any_hint', c.anyh, 'hour_unknown', c.hour_unknown, 'date_mismatch', c.mismatch,
                       'no_account', c.no_acct,
                       'status', CASE WHEN c.n = 0 THEN format('近 %s 天没帖', c_notes_days)
                                      WHEN c.anyh = 0 THEN format('近 %s 天三条都没触发', c_notes_days)
                                      ELSE '有' END) AS j
            FROM (
                SELECT count(*) AS n,
                       count(*) FILTER (WHERE (i.data ->> 'evening')::boolean) AS evening,
                       count(*) FILTER (WHERE (i.data ->> 'weekend')::boolean) AS weekend,
                       count(*) FILTER (WHERE (i.data ->> 'same_acct_3d')::boolean) AS same,
                       count(*) FILTER (WHERE (i.data ->> 'evening')::boolean OR (i.data ->> 'weekend')::boolean
                                          OR (i.data ->> 'same_acct_3d')::boolean) AS anyh,
                       count(*) FILTER (WHERE i.data ->> 'hour_bj' IS NULL) AS hour_unknown,
                       count(*) FILTER (WHERE i.data ->> 'hour_status' = '日期对不上') AS mismatch,
                       count(*) FILTER (WHERE i.account_id IS NULL) AS no_acct
                FROM workbench.snapshot_items i
                WHERE i.day = v_d0 AND i.block = 'exposure_hints' AND i.project_id = a.project_id
            ) c
        ) b4
        CROSS JOIN LATERAL (
            SELECT jsonb_build_object(
                       'events', count(*),
                       'status', CASE WHEN count(*) = 0 THEN format('近 %s 天没有投流记录', c_boost_days) ELSE '有' END) AS j
            FROM workbench.snapshot_items i
            WHERE i.day = v_d0 AND i.block = 'boost_curves' AND i.project_id = a.project_id
        ) b5
    ) x;

    UPDATE workbench.snapshot_runs
       SET projects = v_projects,
           took_ms = (extract(epoch FROM clock_timestamp() - v_t0) * 1000)::int
     WHERE day = v_d0;

    SELECT jsonb_object_agg(b.block, b.n) INTO v_counts
    FROM (SELECT i.block, count(*) AS n FROM workbench.snapshot_items i WHERE i.day = v_d0 GROUP BY i.block) b;

    -- 返回值只有计数和状态词: 快照那一步会把它打进 Summary
    RETURN jsonb_build_object('day', v_d0, 'rule_version', c_rule_version,
                              'projects', jsonb_array_length(v_projects),
                              'items', coalesce(v_counts, '{}'::jsonb),
                              'outcomes_new', v_outcomes,
                              'took_ms', (extract(epoch FROM clock_timestamp() - v_t0) * 1000)::int);
END
$fn$;

COMMENT ON FUNCTION truth_vault.workbench_take_snapshot(DATE) IS
    '工作台每天的快照 (workbench v1, docs/35 第 2、4 节)。按北京今天算五块, 写进 workbench.snapshot_*; 同一天重跑就替换当天; '
    '顺带给满 7 天、满 14 天的帖各记一笔; 删 90 天前的快照。只有 service_role 能执行。p_day 只给 CI 的合成数据用, 真跑不传。'
    '返回值只有计数。';


-- ── ⑦ 看板读的九个视图 (只出打过码的列) ─────────────────────────────────
-- 码 = sha256(盐 ‖ 'a:' ‖ account_id) / sha256(盐 ‖ 'n:' ‖ note_id) 的前 8 位十六进制; 投流事件用 'e:'。
-- 视图属主读盐和快照表; 读视图的人 (tv_workbench_ro) 碰不到它们。全部只看最近一份快照。

CREATE OR REPLACE VIEW workbench.v_status WITH (security_invoker = false) AS
WITH last AS (
    SELECT r.day, r.taken_at, r.took_ms, r.rule_version, r.projects
    FROM workbench.snapshot_runs r ORDER BY r.day DESC LIMIT 1
), agg AS (
    SELECT count(*) AS n_days, min(r.day) AS first_day FROM workbench.snapshot_runs r
)
SELECT l.day, l.taken_at, l.took_ms, l.rule_version, g.n_days, g.first_day,
       p.ord::int AS seq,
       p.j ->> 'project_id' AS project_id,
       p.j ->> 'platform' AS platform,
       (p.j ->> 'posts_30d')::int AS posts_30d,
       (p.j ->> 'last_post_day')::date AS last_post_day,
       (p.j ->> 'data_as_of')::timestamptz AS data_as_of,
       (p.j ->> 'median_impressions')::numeric AS median_impressions,
       p.j -> 'b1' AS b1, p.j -> 'b2' AS b2, p.j -> 'b3a' AS b3a, p.j -> 'b3b' AS b3b, p.j -> 'b4' AS b4, p.j -> 'b5' AS b5
FROM last l
CROSS JOIN agg g
LEFT JOIN LATERAL jsonb_array_elements(l.projects) WITH ORDINALITY AS p(j, ord) ON TRUE;

CREATE OR REPLACE VIEW workbench.v_accounts WITH (security_invoker = false) AS
WITH x AS (
    SELECT i.project_id, i.data,
           left(encode(sha256(s.salt || convert_to('a:' || i.account_id, 'UTF8')), 'hex'), 8) AS account_code,
           CASE WHEN char_length(i.account_id) <= 1 THEN '*' ELSE left(i.account_id, 1) || '**' END AS name_hint
    FROM workbench.snapshot_items i
    CROSS JOIN workbench.mask_salt s
    WHERE i.day = (SELECT max(r.day) FROM workbench.snapshot_runs r)
      AND i.block = 'accounts'
      AND (i.data ->> 'listed')::boolean
)
SELECT x.project_id, x.account_code, x.name_hint,
       x.data ->> 'tier' AS tier,
       (x.data ->> 'downgrade')::boolean AS downgrade,
       (x.data ->> 'posts_here')::int AS posts_here,
       (x.data ->> 'graded_here')::int AS graded_here,
       (x.data ->> 'hits_here')::int AS hits_here,
       (x.data ->> 'other_hit')::boolean AS other_hit,
       (x.data ->> 'last_post_here')::date AS last_post_here,
       (x.data ->> 'rank')::int AS seq,
       count(*) OVER (PARTITION BY x.project_id, x.account_code) > 1 AS code_clash
FROM x;

CREATE OR REPLACE VIEW workbench.v_content_counts WITH (security_invoker = false) AS
SELECT i.project_id,
       (i.data ->> 'seq')::int AS seq,
       i.data ->> 'hint' AS hint, i.data ->> 'side' AS side, i.data ->> 'scope' AS scope, i.data ->> 'w64' AS w64,
       (i.data ->> 'n_flag')::int AS n_flag, (i.data ->> 'n_noflag')::int AS n_noflag,
       (i.data ->> 'n_unlabeled')::int AS n_unlabeled,
       (i.data ->> 'graded_flag')::int AS graded_flag, (i.data ->> 'hits_flag')::int AS hits_flag,
       (i.data ->> 'graded_noflag')::int AS graded_noflag, (i.data ->> 'hits_noflag')::int AS hits_noflag,
       (i.data ->> 'expo_known_flag')::int AS expo_known_flag, (i.data ->> 'expo_hi_flag')::int AS expo_hi_flag,
       (i.data ->> 'expo_known_noflag')::int AS expo_known_noflag, (i.data ->> 'expo_hi_noflag')::int AS expo_hi_noflag
FROM workbench.snapshot_items i
WHERE i.day = (SELECT max(r.day) FROM workbench.snapshot_runs r)
  AND i.block = 'content_counts';

CREATE OR REPLACE VIEW workbench.v_content_notes WITH (security_invoker = false) AS
SELECT i.project_id,
       left(encode(sha256(s.salt || convert_to('n:' || i.note_id, 'UTF8')), 'hex'), 8) AS note_code,
       CASE WHEN i.account_id IS NOT NULL
            THEN left(encode(sha256(s.salt || convert_to('a:' || i.account_id, 'UTF8')), 'hex'), 8) END AS account_code,
       (i.data ->> 'publish_day')::date AS publish_day,
       ARRAY(SELECT jsonb_array_elements_text(i.data -> 'plus')) AS plus_hints,
       ARRAY(SELECT jsonb_array_elements_text(i.data -> 'minus')) AS minus_hints,
       ARRAY(SELECT jsonb_array_elements_text(i.data -> 'unlabeled')) AS unlabeled,
       coalesce((i.data ->> 'body_empty')::boolean, FALSE) AS body_empty
FROM workbench.snapshot_items i
CROSS JOIN workbench.mask_salt s
WHERE i.day = (SELECT max(r.day) FROM workbench.snapshot_runs r)
  AND i.block = 'content_notes';

CREATE OR REPLACE VIEW workbench.v_watch_24h WITH (security_invoker = false) AS
SELECT i.project_id,
       left(encode(sha256(s.salt || convert_to('n:' || i.note_id, 'UTF8')), 'hex'), 8) AS note_code,
       CASE WHEN i.account_id IS NOT NULL
            THEN left(encode(sha256(s.salt || convert_to('a:' || i.account_id, 'UTF8')), 'hex'), 8) END AS account_code,
       (i.data ->> 'publish_day')::date AS publish_day,
       (i.data ->> 'hours')::int AS hours_24h,
       (i.data ->> 'comments_24h')::int AS comments_24h,
       (i.data ->> 'n_prior')::int AS n_prior,
       (i.data ->> 'p90_prior')::numeric AS p90_prior,
       (i.data ->> 'mid_rank')::numeric AS mid_rank,
       i.data ->> 'status' AS status,
       (i.data ->> 'comments_now')::int AS comments_now,
       (i.data ->> 'over_line_now')::boolean AS over_line_now,
       (i.data ->> 'seeded_known')::int AS seeded_known
FROM workbench.snapshot_items i
CROSS JOIN workbench.mask_salt s
WHERE i.day = (SELECT max(r.day) FROM workbench.snapshot_runs r)
  AND i.block = 'watch_24h';

CREATE OR REPLACE VIEW workbench.v_watch_72h WITH (security_invoker = false) AS
SELECT i.project_id,
       left(encode(sha256(s.salt || convert_to('n:' || i.note_id, 'UTF8')), 'hex'), 8) AS note_code,
       CASE WHEN i.account_id IS NOT NULL
            THEN left(encode(sha256(s.salt || convert_to('a:' || i.account_id, 'UTF8')), 'hex'), 8) END AS account_code,
       (i.data ->> 'publish_day')::date AS publish_day,
       (i.data ->> 'hours')::int AS hours_72h,
       (i.data ->> 'impressions_72h')::int AS impressions_72h,
       (i.data ->> 'reads_72h')::int AS reads_72h,
       (i.data ->> 'ctr_72h')::numeric AS ctr_72h,
       (i.data ->> 'median_impressions')::numeric AS median_impressions,
       (i.data ->> 'rank')::int AS rank_in_project,
       (i.data ->> 'n_prior')::int AS n_prior,
       (i.data ->> 'mid_rank')::numeric AS mid_rank,
       (i.data ->> 'impressions_now')::int AS impressions_now
FROM workbench.snapshot_items i
CROSS JOIN workbench.mask_salt s
WHERE i.day = (SELECT max(r.day) FROM workbench.snapshot_runs r)
  AND i.block = 'watch_72h';

CREATE OR REPLACE VIEW workbench.v_exposure_hints WITH (security_invoker = false) AS
SELECT i.project_id,
       left(encode(sha256(s.salt || convert_to('n:' || i.note_id, 'UTF8')), 'hex'), 8) AS note_code,
       CASE WHEN i.account_id IS NOT NULL
            THEN left(encode(sha256(s.salt || convert_to('a:' || i.account_id, 'UTF8')), 'hex'), 8) END AS account_code,
       (i.data ->> 'publish_day')::date AS publish_day,
       (i.data ->> 'hour_bj')::int AS hour_bj,
       i.data ->> 'hour_status' AS hour_status,
       (i.data ->> 'evening')::boolean AS evening,
       (i.data ->> 'weekend')::boolean AS weekend,
       (i.data ->> 'same_acct_3d')::boolean AS same_acct_3d,
       (i.data ->> 'impressions_now')::int AS impressions_now,
       (i.data ->> 'median_impressions')::numeric AS median_impressions
FROM workbench.snapshot_items i
CROSS JOIN workbench.mask_salt s
WHERE i.day = (SELECT max(r.day) FROM workbench.snapshot_runs r)
  AND i.block = 'exposure_hints';

CREATE OR REPLACE VIEW workbench.v_boost_curves WITH (security_invoker = false) AS
SELECT i.project_id,
       left(encode(sha256(s.salt || convert_to('e:' || i.item_key, 'UTF8')), 'hex'), 8) AS event_code,
       left(encode(sha256(s.salt || convert_to('n:' || i.note_id, 'UTF8')), 'hex'), 8) AS note_code,
       (i.data ->> 'boost_date')::date AS boost_date,
       (i.data ->> 'publish_day')::date AS publish_day,
       (i.data ->> 'days_after_publish')::int AS days_after_publish,
       (i.data ->> 'seeded_on_maintain')::numeric AS seeded_on_maintain,
       (i.data ->> 'comments_base')::numeric AS comments_base, i.data ->> 'comments_base_status' AS comments_base_status,
       (i.data ->> 'comments_d0')::numeric AS comments_d0, i.data ->> 'comments_d0_status' AS comments_d0_status,
       (i.data ->> 'comments_d1')::numeric AS comments_d1, i.data ->> 'comments_d1_status' AS comments_d1_status,
       (i.data ->> 'comments_d3')::numeric AS comments_d3, i.data ->> 'comments_d3_status' AS comments_d3_status,
       (i.data ->> 'comments_d7')::numeric AS comments_d7, i.data ->> 'comments_d7_status' AS comments_d7_status,
       (i.data ->> 'impressions_base')::numeric AS impressions_base, i.data ->> 'impressions_base_status' AS impressions_base_status,
       (i.data ->> 'impressions_d7')::numeric AS impressions_d7, i.data ->> 'impressions_d7_status' AS impressions_d7_status,
       (i.data ->> 'reads_base')::numeric AS reads_base, i.data ->> 'reads_base_status' AS reads_base_status,
       (i.data ->> 'reads_d7')::numeric AS reads_d7, i.data ->> 'reads_d7_status' AS reads_d7_status
FROM workbench.snapshot_items i
CROSS JOIN workbench.mask_salt s
WHERE i.day = (SELECT max(r.day) FROM workbench.snapshot_runs r)
  AND i.block = 'boost_curves';

-- 影子核对: 全部项目合在一起, 只有计数。每篇帖在同一块只算第一次出现那天; n 只数结果知道的 (缺的不当「没过」)。
-- 晚记: 满 7 / 14 天之后 1 天内记上的算准时; 再晚的 (多是第一份快照那天补记的) 数是晚几天的, 看什么那一列带「（晚记…）」单独数。
CREATE OR REPLACE VIEW workbench.v_shadow_check WITH (security_invoker = false) AS
WITH runs AS (
    SELECT r.day, r.rule_version FROM workbench.snapshot_runs r
), oc AS (
    SELECT o.*,
           CASE WHEN o.days_since > o.mark + 1 THEN format('（晚记：第 %s 天以后才记）', o.mark + 2) ELSE '' END AS lt
    FROM workbench.snapshot_outcomes o
), o7 AS (
    SELECT * FROM oc WHERE mark = 7
), o14 AS (
    SELECT * FROM oc WHERE mark = 14
), first_seen AS (
    SELECT DISTINCT ON (i.block, i.note_id) i.block, i.note_id, i.project_id, i.day, i.data
    FROM workbench.snapshot_items i
    WHERE i.note_id IS NOT NULL AND i.block IN ('content_notes', 'watch_24h', 'watch_72h', 'exposure_hints')
    ORDER BY i.block, i.note_id, i.day
), listed24 AS (
    SELECT i.note_id,
           bool_or(i.data ->> 'status' = '进清单') AS listed,
           bool_or(i.data ->> 'status' IN ('进清单', '没进')) AS ranked
    FROM workbench.snapshot_items i WHERE i.block = 'watch_24h' GROUP BY i.note_id
), rows_ AS (
    -- 块 1: 发布前最近一份快照里发帖号的档
    SELECT '1' AS block, r.rule_version, o.acct_group AS grp, m.measure || o.lt AS measure, m.yes
    FROM o7 o
    JOIN runs r ON r.day = o.acct_group_day
    CROSS JOIN LATERAL (VALUES ('满 7 天过评论线', o.over_line), ('已定级为爆', o.hit),
                               ('其中有投流记录', o.boosted)) AS m(measure, yes)
    WHERE o.acct_group IS NOT NULL
    UNION ALL
    -- 块 2: 每种写法 有 / 没有 / 没标
    SELECT '2', r.rule_version,
           fl.key || '：' || CASE fl.value WHEN 'true'::jsonb THEN '有' WHEN 'false'::jsonb THEN '没有' ELSE '没标' END,
           m.measure || coalesce(m.lt, ''), m.yes
    FROM first_seen f
    JOIN runs r ON r.day = f.day
    CROSS JOIN LATERAL jsonb_each(f.data -> 'flags') AS fl(key, value)
    LEFT JOIN o7 ON o7.note_id = f.note_id
    LEFT JOIN o14 ON o14.note_id = f.note_id
    CROSS JOIN LATERAL (VALUES ('满 7 天过评论线', o7.over_line, o7.lt), ('满 14 天曝光过中位数', o14.expo_hi, o14.lt))
                        AS m(measure, yes, lt)
    WHERE f.block = 'content_notes'
      AND (m.measure = '满 14 天曝光过中位数' OR fl.key IN ('正文不提品牌', '产品不出场', '负面痛点基调'))
    UNION ALL
    -- 块 3a: 进过清单 / 排过名没进
    SELECT '3a', r.rule_version, CASE WHEN l.listed THEN '进清单' ELSE '没进' END, m.measure || coalesce(o7.lt, ''), m.yes
    FROM first_seen f
    JOIN runs r ON r.day = f.day
    JOIN listed24 l ON l.note_id = f.note_id AND l.ranked
    LEFT JOIN o7 ON o7.note_id = f.note_id
    CROSS JOIN LATERAL (VALUES ('满 7 天过评论线', o7.over_line), ('已定级为爆', o7.hit),
                               ('其中有投流或新铺评', o7.boosted OR o7.seeded_known > coalesce((f.data ->> 'seeded_known')::int, 0)))
                        AS m(measure, yes)
    WHERE f.block = 'watch_24h'
    UNION ALL
    -- 块 4: 三条提示 中 / 没中 / 不知道
    SELECT '4', r.rule_version,
           h.hint || '：' || CASE WHEN h.v IS NULL THEN '不知道' WHEN h.v THEN '中' ELSE '没中' END,
           '满 14 天曝光过中位数' || coalesce(o14.lt, ''), o14.expo_hi
    FROM first_seen f
    JOIN runs r ON r.day = f.day
    LEFT JOIN o14 ON o14.note_id = f.note_id
    CROSS JOIN LATERAL (VALUES ('晚上发', (f.data ->> 'evening')::boolean), ('周末发', (f.data ->> 'weekend')::boolean),
                               ('同号 3 天内连发', (f.data ->> 'same_acct_3d')::boolean)) AS h(hint, v)
    WHERE f.block = 'exposure_hints'
    UNION ALL
    -- 块 5: 事件满 8 天后, 每个点有没有数 (最近一份快照里的值)
    SELECT '5', r.rule_version, pt.point, '满 8 天这个点有数', (pt.v IS NOT NULL AND pt.v <> 'null'::jsonb)
    FROM (SELECT DISTINCT ON (i.item_key) i.item_key, i.day, i.data
          FROM workbench.snapshot_items i WHERE i.block = 'boost_curves'
          ORDER BY i.item_key, i.day DESC) e
    JOIN runs r ON r.day = e.day
    CROSS JOIN LATERAL (VALUES ('评论 基线', e.data -> 'comments_base'), ('评论 第 1 天', e.data -> 'comments_d1'),
                               ('评论 第 3 天', e.data -> 'comments_d3'), ('评论 第 7 天', e.data -> 'comments_d7'),
                               ('曝光 基线', e.data -> 'impressions_base'), ('曝光 第 7 天', e.data -> 'impressions_d7'))
                        AS pt(point, v)
    WHERE (e.data ->> 'boost_date')::date <= (SELECT max(rr.day) FROM runs rr) - 8
), auc_in AS (
    -- 块 3b: 每个候选第一次出现时的快照曝光, 对满 14 天曝光过没过中位数; 项目内排序能力 (AUC), 晚记的单独算
    SELECT f.project_id, r.rule_version, o14.lt, (f.data ->> 'impressions_72h')::numeric AS x, o14.expo_hi AS y
    FROM first_seen f
    JOIN runs r ON r.day = f.day
    JOIN o14 ON o14.note_id = f.note_id
    WHERE f.block = 'watch_72h' AND o14.expo_hi IS NOT NULL
), auc AS (
    SELECT a.project_id, a.rule_version, a.lt,
           sum(CASE WHEN a.x > b.x THEN 1.0 WHEN a.x = b.x THEN 0.5 ELSE 0 END) / count(*) AS auc
    FROM auc_in a
    JOIN auc_in b ON b.project_id = a.project_id AND b.rule_version = a.rule_version AND b.lt = a.lt AND a.y AND NOT b.y
    GROUP BY a.project_id, a.rule_version, a.lt
)
SELECT q.block, q.rule_version, q.grp, q.measure,
       count(*) FILTER (WHERE q.yes IS NOT NULL) AS n,
       count(*) FILTER (WHERE q.yes) AS n_yes,
       NULL::numeric AS value
FROM rows_ q
GROUP BY q.block, q.rule_version, q.grp, q.measure
UNION ALL
SELECT '3b', ai.rule_version, ai.project_id, '满 14 天曝光过中位数' || ai.lt,
       count(*), count(*) FILTER (WHERE ai.y), round(max(au.auc), 3)
FROM auc_in ai
LEFT JOIN auc au ON au.project_id = ai.project_id AND au.rule_version = ai.rule_version AND au.lt = ai.lt
GROUP BY ai.project_id, ai.rule_version, ai.lt;


-- ── ⑧ 读视图的角色, 和全部权限 ──────────────────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tv_workbench_ro') THEN
        -- 没有密码: owner 用 scripts/workbench_role_password.py 生成 SCRAM 校验串, 在 SQL editor 里设 (不写明文, 见文件头)
        CREATE ROLE tv_workbench_ro LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
            CONNECTION LIMIT 5;
    END IF;
END $$;
ALTER ROLE tv_workbench_ro SET default_transaction_read_only = on;
ALTER ROLE tv_workbench_ro SET statement_timeout = '8s';
ALTER ROLE tv_workbench_ro SET search_path = workbench;
COMMENT ON ROLE tv_workbench_ro IS
    '工作台看板服务端读视图的身份 (workbench v1, docs/35 第 3 节)。只有 workbench 的 USAGE 和九个 v_* 视图的 SELECT; '
    '不在 authenticator 里, 没有 truth_vault 的 USAGE。密码只在 Vercel 的 WORKBENCH_DATABASE_URL 里。';

-- 先全收, 再只给该给的
REVOKE ALL ON SCHEMA workbench FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA workbench FROM PUBLIC;
REVOKE ALL ON FUNCTION truth_vault.workbench_take_snapshot(DATE) FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated', 'service_role', 'tv_workbench_ro'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON SCHEMA workbench FROM %I', r);
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA workbench FROM %I', r);
            EXECUTE format('REVOKE ALL ON FUNCTION truth_vault.workbench_take_snapshot(DATE) FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION truth_vault.workbench_take_snapshot(DATE) TO service_role;
    END IF;
END $$;
GRANT USAGE ON SCHEMA workbench TO tv_workbench_ro;
GRANT SELECT ON workbench.v_status, workbench.v_accounts, workbench.v_content_counts, workbench.v_content_notes,
                workbench.v_watch_24h, workbench.v_watch_72h, workbench.v_exposure_hints, workbench.v_boost_curves,
                workbench.v_shadow_check
    TO tv_workbench_ro;

COMMENT ON VIEW workbench.v_status IS '最近一份快照: 每个活跃项目一行, 带 b1..b5 每块的计数和状态词 (为什么空)。没有快照时 0 行。';
COMMENT ON VIEW workbench.v_accounts IS '块 1 账号底子: 只列 listed 的号 (一档全部、二档近 90 天发过帖的前 50 个)。账号码 8 位, 名字提示是首字加 **。';
COMMENT ON VIEW workbench.v_content_counts IS '块 2 写法提示的本项目计数表: 每种写法一行, 有 / 没有 / 没标; w64 是 W-64 的倍数原文。';
COMMENT ON VIEW workbench.v_content_notes IS '块 2 近 14 天每篇: 加分、减分写法和没标的维度; body_empty = 抽特征那一次正文是空的 (四道答案题都按没标算)。';
COMMENT ON VIEW workbench.v_watch_24h IS '块 3a 24 小时评论数: 近 5 天有 24h 快照的候选, status = 进清单 / 没进 / 不到 20 篇 / 没记评论数。';
COMMENT ON VIEW workbench.v_watch_72h IS '块 3b 「72h」曝光排序: 快照实际在第 4–5 天; 只看当时曝光还没过中位数的。';
COMMENT ON VIEW workbench.v_exposure_hints IS '块 4 曝光提示: 近 14 天每篇三条发布前提示; NULL = 不知道 (不当成「没有」)。';
COMMENT ON VIEW workbench.v_boost_curves IS '块 5 投流前后: 近 30 天每个事件一行; NULL 是缺, 画线时断开。没有效果结论。';
COMMENT ON VIEW workbench.v_shadow_check IS '影子核对, 只有计数: 每块每组 n (结果知道的) 和 n_yes; 3b 的 value 是项目内排序能力 (AUC)。满了之后晚 2 天以上才记的, measure 带「晚记」单独数。';

COMMIT;
