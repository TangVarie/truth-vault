-- truth_vault v1.27 · 读者评论分得开来源 + 指标「哪天看到的」视图 (十三件事第 2、4 件, D-154 / D-155, 2026-11-15)
-- ════════════════════════════════════════════════════════════════════
-- 这份迁移做三件事, 都是加法:
--   ① truth_vault.comments 加三列 (都可空, 老行不动):
--        source        这一行是谁写出来的。NULL = 运营在飞书「随贴评论」里自己贴的 (v1.27 之前的全部行, 以及以后运营贴的行);
--                      'linkcheck_digest'  = 从巡查工具 (linkcheck) 写的「评论区快照」那段文字里拆出来的 (第一页, 每条截到 40 字);
--                      'linkcheck_records' = 从巡查工具写的「评论区明细」那一行 JSON 里读出来的 (第一页, 带平台评论 ID, 每条截到 200 字)。
--                      要「读者那一侧」的评论: source LIKE 'linkcheck\_%' 且 is_scripted 不是 true 且 comment_role 不是 '贴主'。
--                      要运营写的: source IS NULL。两种不放进同一个统计里。
--        is_truncated  这条正文是不是被截过 (快照 40 字 / 明细 200 字)。运营贴的行是 NULL (没有这个概念)。
--        observed_at   这条评论是哪一刻在评论区里看到的 (带时区)。明细行 = 那一格 JSON 里的 t; 快照行 = 这一篇的「最近检查时间」,
--                      而且只在同一行的「巡查状态」= 正常 时才填 —— 巡查失败的轮次也会推进「最近检查时间」, 那时的快照还是上一轮的。
--                      拿不准就是 NULL, 不拿同步时刻代填。
--      命中这一行「评论关键词」的评论 (多半是我们自己铺的) 写 is_scripted = true (这一列 v1.2 就有, 以前没人写), 所以数「读者评论」
--      时拿得掉。没命中的不写 false: 没命中不等于不是铺的。
--   ② 视图 truth_vault.v_note_observations: 每篇每个北京日一行, 只出四个指标 (评论数 / 曝光 / 阅读 / 互动) 里至少一个变了的那些天。
--      全部从 audit_log 读 (D-078: audit_log 才是逐次的历史, metric_snapshots 一个窗口只留一个数)。每个指标给「那天结束时的值」
--      和「这个值是哪天变成这样的」。评论数另给 comments_observed_at_cn (北京时间): 有「评论数观测时间」(linkcheck 11-15 加的列,
--      只在真量到评论数时才推进) 就用它; 没有就用「最近检查时间」, 但只在那一刻「巡查状态」= 正常 时才给, 否则 NULL。
--      comments_observed_source 说用的是哪个。
--   ③ metric_snapshots 的表注释和两列注释: collected_at 是同步写这一行的时刻, window_label 是按「发布时间到同步时刻」算出来的档,
--      都不是「这个数是哪一刻量到的」。
--
-- 知道什么、不知道什么:
--   · 评论数: 巡查工具量的, 有时刻 (上面那两列)。运营手填评论数的项目没有时刻, comments_observed_at_cn 是 NULL。
--   · 曝光 / 阅读 / 互动: 运营在作者后台截图, 飞书的 AI 字段读出数字。截图是哪一刻截的没有任何地方记, 这里只知道
--     「TV 哪天第一次看到这个新数」(*_changed_cn_day), 它比真实读数晚: 至少晚到当晚同步, 运营隔了几天才截图就晚几天。
--   · 一天之内变了几次只留最后一次; 夜跑没跑的那天没有行; 2026-09-18 之前评论数只在 raw_extra 里, 这张视图不回头去读。
--   · 「巡查状态」= 正常 但那一轮上游没报评论数 (少见) 时, 用「最近检查时间」会略微报新; 有「评论数观测时间」的表没有这个问题。
--
-- 不做什么: metric_snapshots 的唯一键不动、不回填、不加表; v_paid_boost_readings (v1.22) 的 comments_measured_at_cn 没有
--   「巡查状态 = 正常」这道闸, 这份迁移不改它 (改它要 owner 多跑一份文件), 记在 OPEN-ITEMS I-31。
--
-- 代码是宽容的: 这三列没建之前, scripts/sync_comments_from_raw_extra.py 照今天的行为走 (只解析随贴评论), 每个带快照的项目打一行
--   warning; 视图没建之前没有任何代码读它。TV 这边先合代码还是先跑这份 SQL 都可以。
--   ⚠️ 别的仓有一处还没按 source 分开: 写作台的评论工具读一篇帖的全部评论行。它改完上线之前先不要跑这份 SQL
--   (跑了不报错, 只是读者评论会混进写手看到的「已有评论」; OPEN-ITEMS W-59)。
--
-- 怎么跑: owner 在 Supabase SQL editor 整份跑一次。可以重跑: 三列 IF NOT EXISTS、索引 IF NOT EXISTS、函数和视图 CREATE OR REPLACE、
--   注释覆盖写。加的是可空列, 不重写表、不锁很久。回滚: DROP VIEW truth_vault.v_note_observations; 三列留着不碍事。
-- 夹具与反证: scripts/check_reader_comments_observations.sql (ci.yml sql job)。
-- ════════════════════════════════════════════════════════════════════

-- ── ① comments 三列 ─────────────────────────────────────────────────
ALTER TABLE truth_vault.comments ADD COLUMN IF NOT EXISTS source       TEXT;
ALTER TABLE truth_vault.comments ADD COLUMN IF NOT EXISTS is_truncated BOOLEAN;
ALTER TABLE truth_vault.comments ADD COLUMN IF NOT EXISTS observed_at  TIMESTAMPTZ;

-- 运营写的行 source 是 NULL, 占绝大多数; 只给巡查来的行建索引。
CREATE INDEX IF NOT EXISTS idx_tv_comments_source
    ON truth_vault.comments(source, note_id) WHERE source IS NOT NULL;

COMMENT ON COLUMN truth_vault.comments.source IS
    '这一行是谁写出来的 (v1.27)。NULL = 运营在飞书「随贴评论」里贴的; linkcheck_digest = 巡查工具「评论区快照」那段文字拆出来的 '
    '(第一页, 每条截到 40 字); linkcheck_records = 巡查工具「评论区明细」那一行 JSON 读出来的 (第一页, 带平台评论 ID)。'
    '读者那一侧 = source LIKE ''linkcheck\_%'' 且 is_scripted 不是 true 且 comment_role 不是 贴主。两种来源不放进同一个统计。';
COMMENT ON COLUMN truth_vault.comments.is_truncated IS
    '正文是不是被截过 (v1.27): 快照行截到 40 字、明细行截到 200 字。运营贴的行是 NULL。';
COMMENT ON COLUMN truth_vault.comments.observed_at IS
    '这条评论是哪一刻在评论区里看到的 (v1.27)。明细行 = 那一格 JSON 的 t; 快照行 = 这一篇的「最近检查时间」, 只在「巡查状态」= 正常 时填。'
    '拿不准是 NULL, 不拿同步时刻代填。comment_time 是评论自己的发布时刻 (只有明细行有), created_at 是 TV 写这一行的时刻。';
COMMENT ON COLUMN truth_vault.comments.is_scripted IS
    '是不是我们自己铺的。巡查来的行: 正文命中这一行「评论关键词」的写 true (多半是铺的), 没命中的留 NULL (没命中不等于不是铺的)。';


-- ── ③ metric_snapshots: 两列不是观测时刻 ─────────────────────────────
COMMENT ON TABLE truth_vault.metric_snapshots IS
    '每篇每个时间档只留一个数 (UNIQUE note_id + window_label + source, 后写的盖掉先写的)。不是逐次观测的历史: 逐次的变化在 audit_log, '
    '按天看用 v_note_observations (v1.27)。今天没有任何分析读这张表。';
COMMENT ON COLUMN truth_vault.metric_snapshots.collected_at IS
    '同步脚本写这一行的时刻 (UTC, 夜跑的钟)。不是这些数被量到的时刻: 评论数是巡查工具更早量的, 曝光 / 阅读 / 互动是运营更早截的图。';
COMMENT ON COLUMN truth_vault.metric_snapshots.window_label IS
    '按「发布时间到同步时刻」隔了多久算出来的档 (2h / 24h / … / ad_hoc)。不是「发布后正好这么久量到的数」: 同步什么时候跑、'
    '运营什么时候截图都不按这个档来。';


-- ── ② v_note_observations ───────────────────────────────────────────
-- 两个小函数: 视图里七处要用, 写成函数免得抄七遍。都只看类型对不对, 不对就是 NULL, 不抛错。
CREATE OR REPLACE FUNCTION truth_vault.tv_jsonb_num(v jsonb) RETURNS numeric
    LANGUAGE sql IMMUTABLE
    SET search_path = ''
AS $$
    SELECT CASE WHEN jsonb_typeof(v) = 'number' THEN (v #>> '{}')::numeric END;
$$;

-- 毫秒时间戳 (飞书日期列) → 北京时间 (无时区)。2000-01-01 到 2100-01-01 之外的数不认。
CREATE OR REPLACE FUNCTION truth_vault.tv_ms_to_cn(v jsonb) RETURNS timestamp
    LANGUAGE sql STABLE
    SET search_path = ''
AS $$
    SELECT CASE WHEN jsonb_typeof(v) = 'number' AND (v #>> '{}')::numeric BETWEEN 946684800000 AND 4102444800000
                THEN (to_timestamp(((v #>> '{}')::numeric / 1000.0)::double precision) AT TIME ZONE 'Asia/Shanghai') END;
$$;

--   occurred_at 是 UTC 的无时区时间戳 → 北京日 = (occurred_at + 8h)::date (同 v1.22)。
--   某个指标「那天结束时的值」= 那天或之前最后一次改它的那一行的新值; audit 里那之前没改过 → 之后第一次改它那一行的旧值
--   (这时 *_changed_cn_day 是 NULL: 知道值, 不知道是哪天变成这样的)。
--   raw_extra 里的格子: 顶层有值用顶层, 顶层空才看 _undeclared (同 v1.22 的 tv_raw_cell; 这里内联, 不依赖 v1.22 跑没跑)。
--   用的时候带上 note_id (或先从 notes 取一个项目的 note_id 再连): 不带条件就是把整张 audit_log 过一遍。
CREATE OR REPLACE VIEW truth_vault.v_note_observations AS
WITH au AS (
    SELECT a.row_id AS note_id, a.audit_id, a.occurred_at, a.operation, a.changed_cols,
           (a.occurred_at + interval '8 hours')::date AS cn_day
    FROM truth_vault.audit_log a
    WHERE a.schema_name = 'truth_vault' AND a.table_name = 'notes'
      AND a.operation IN ('INSERT', 'UPDATE') AND a.row_id IS NOT NULL
),
vals AS (
    SELECT au.note_id, au.audit_id, au.occurred_at, au.cn_day, v.item, v.new_v,
           first_value(v.old_v) OVER (PARTITION BY au.note_id, v.item ORDER BY au.occurred_at, au.audit_id) AS first_old
    FROM au
    CROSS JOIN LATERAL (
        SELECT t.item,
               CASE WHEN au.operation = 'UPDATE' THEN au.changed_cols -> t.item -> 0 END AS old_v,
               CASE WHEN au.operation = 'UPDATE' THEN au.changed_cols -> t.item -> 1
                    ELSE au.changed_cols -> t.item END AS new_v
        FROM (VALUES ('comments_count'), ('impressions'), ('reads'), ('interactions')) AS t(item)
        WHERE au.changed_cols ? t.item
        UNION ALL
        SELECT r.item, r.old_v, r.new_v
        FROM (SELECT CASE WHEN au.operation = 'UPDATE' THEN au.changed_cols -> 'raw_extra' -> 0 END AS ob,
                     CASE WHEN au.operation = 'UPDATE' THEN au.changed_cols -> 'raw_extra' -> 1
                          ELSE au.changed_cols -> 'raw_extra' END AS nb) b
        CROSS JOIN LATERAL (
            SELECT 'raw:' || c.col AS item,
                   coalesce(nullif(nullif(nullif(b.ob -> c.col, 'null'::jsonb), '""'::jsonb), '[]'::jsonb),
                            b.ob -> '_undeclared' -> c.col) AS old_v,
                   coalesce(nullif(nullif(nullif(b.nb -> c.col, 'null'::jsonb), '""'::jsonb), '[]'::jsonb),
                            b.nb -> '_undeclared' -> c.col) AS new_v
            FROM (VALUES ('最近检查时间'), ('巡查状态'), ('评论数观测时间')) AS c(col)
        ) r
        WHERE au.changed_cols ? 'raw_extra'
          AND (au.operation = 'INSERT' OR r.old_v IS DISTINCT FROM r.new_v)
    ) v
),
dl AS (   -- 每篇每项每个北京日: 那天最后一次
    SELECT DISTINCT ON (note_id, item, cn_day) note_id, item, cn_day, new_v, first_old
    FROM vals
    ORDER BY note_id, item, cn_day, occurred_at DESC, audit_id DESC
),
d AS (    -- 每篇每个北京日一行, 七项摊平: *_chg 那天改没改, *_v 那天最后的新值, *_fo 这一项第一次被改之前的值
    SELECT note_id, cn_day,
           coalesce(bool_or(item = 'comments_count'), false)       AS cc_chg,
           coalesce(bool_or(item = 'impressions'), false)          AS imp_chg,
           coalesce(bool_or(item = 'reads'), false)                AS rd_chg,
           coalesce(bool_or(item = 'interactions'), false)         AS it_chg,
           coalesce(bool_or(item = 'raw:最近检查时间'), false)     AS chk_chg,
           coalesce(bool_or(item = 'raw:巡查状态'), false)         AS st_chg,
           coalesce(bool_or(item = 'raw:评论数观测时间'), false)   AS ob_chg,
           max(new_v::text) FILTER (WHERE item = 'comments_count')         AS cc_v,
           max(new_v::text) FILTER (WHERE item = 'impressions')            AS imp_v,
           max(new_v::text) FILTER (WHERE item = 'reads')                  AS rd_v,
           max(new_v::text) FILTER (WHERE item = 'interactions')           AS it_v,
           max(new_v::text) FILTER (WHERE item = 'raw:最近检查时间')       AS chk_v,
           max(new_v::text) FILTER (WHERE item = 'raw:巡查状态')           AS st_v,
           max(new_v::text) FILTER (WHERE item = 'raw:评论数观测时间')     AS ob_v,
           max(first_old::text) FILTER (WHERE item = 'comments_count')     AS cc_fo,
           max(first_old::text) FILTER (WHERE item = 'impressions')        AS imp_fo,
           max(first_old::text) FILTER (WHERE item = 'reads')              AS rd_fo,
           max(first_old::text) FILTER (WHERE item = 'interactions')       AS it_fo,
           max(first_old::text) FILTER (WHERE item = 'raw:最近检查时间')   AS chk_fo,
           max(first_old::text) FILTER (WHERE item = 'raw:巡查状态')       AS st_fo,
           max(first_old::text) FILTER (WHERE item = 'raw:评论数观测时间') AS ob_fo
    FROM dl
    GROUP BY note_id, cn_day
),
w1 AS (   -- 每项: 到这一天为止最后一次改它是哪天 (没改过 = NULL)
    SELECT d.note_id, d.cn_day, d.cc_chg, d.imp_chg, d.rd_chg, d.it_chg,
           d.cc_v, d.imp_v, d.rd_v, d.it_v, d.chk_v, d.st_v, d.ob_v,
           max(CASE WHEN d.cc_chg  THEN d.cn_day END) OVER w AS cc_day,
           max(CASE WHEN d.imp_chg THEN d.cn_day END) OVER w AS imp_day,
           max(CASE WHEN d.rd_chg  THEN d.cn_day END) OVER w AS rd_day,
           max(CASE WHEN d.it_chg  THEN d.cn_day END) OVER w AS it_day,
           max(CASE WHEN d.chk_chg THEN d.cn_day END) OVER w AS chk_day,
           max(CASE WHEN d.st_chg  THEN d.cn_day END) OVER w AS st_day,
           max(CASE WHEN d.ob_chg  THEN d.cn_day END) OVER w AS ob_day,
           max(d.cc_fo)  OVER (PARTITION BY d.note_id) AS cc_fo,
           max(d.imp_fo) OVER (PARTITION BY d.note_id) AS imp_fo,
           max(d.rd_fo)  OVER (PARTITION BY d.note_id) AS rd_fo,
           max(d.it_fo)  OVER (PARTITION BY d.note_id) AS it_fo,
           max(d.chk_fo) OVER (PARTITION BY d.note_id) AS chk_fo,
           max(d.st_fo)  OVER (PARTITION BY d.note_id) AS st_fo,
           max(d.ob_fo)  OVER (PARTITION BY d.note_id) AS ob_fo
    FROM d
    WINDOW w AS (PARTITION BY d.note_id ORDER BY d.cn_day)
),
w2 AS (   -- 每项那天结束时的值: 最后改它那天的新值; 那之前没改过 → 第一次被改之前的值
    SELECT w1.note_id, w1.cn_day, w1.cc_chg, w1.imp_chg, w1.rd_chg, w1.it_chg,
           w1.cc_day, w1.imp_day, w1.rd_day, w1.it_day,
           (CASE WHEN w1.cc_day  IS NOT NULL THEN max(w1.cc_v)  OVER (PARTITION BY w1.note_id, w1.cc_day)  ELSE w1.cc_fo  END)::jsonb AS cc,
           (CASE WHEN w1.imp_day IS NOT NULL THEN max(w1.imp_v) OVER (PARTITION BY w1.note_id, w1.imp_day) ELSE w1.imp_fo END)::jsonb AS imp,
           (CASE WHEN w1.rd_day  IS NOT NULL THEN max(w1.rd_v)  OVER (PARTITION BY w1.note_id, w1.rd_day)  ELSE w1.rd_fo  END)::jsonb AS rd,
           (CASE WHEN w1.it_day  IS NOT NULL THEN max(w1.it_v)  OVER (PARTITION BY w1.note_id, w1.it_day)  ELSE w1.it_fo  END)::jsonb AS it,
           (CASE WHEN w1.chk_day IS NOT NULL THEN max(w1.chk_v) OVER (PARTITION BY w1.note_id, w1.chk_day) ELSE w1.chk_fo END)::jsonb AS chk,
           (CASE WHEN w1.st_day  IS NOT NULL THEN max(w1.st_v)  OVER (PARTITION BY w1.note_id, w1.st_day)  ELSE w1.st_fo  END)::jsonb AS st,
           (CASE WHEN w1.ob_day  IS NOT NULL THEN max(w1.ob_v)  OVER (PARTITION BY w1.note_id, w1.ob_day)  ELSE w1.ob_fo  END)::jsonb AS ob
    FROM w1
)
SELECT w2.note_id,
       w2.cn_day,
       array_remove(ARRAY[CASE WHEN w2.cc_chg  THEN 'comments_count' END,
                          CASE WHEN w2.imp_chg THEN 'impressions' END,
                          CASE WHEN w2.rd_chg  THEN 'reads' END,
                          CASE WHEN w2.it_chg  THEN 'interactions' END], NULL) AS changed_today,
       -- 评论数
       truth_vault.tv_jsonb_num(w2.cc)  AS comments_count,
       w2.cc_day                        AS comments_changed_cn_day,
       CASE WHEN truth_vault.tv_ms_to_cn(w2.ob) IS NOT NULL THEN truth_vault.tv_ms_to_cn(w2.ob)
            WHEN w2.st #>> '{}' = '正常' THEN truth_vault.tv_ms_to_cn(w2.chk) END AS comments_observed_at_cn,
       CASE WHEN truth_vault.tv_ms_to_cn(w2.ob) IS NOT NULL THEN '评论数观测时间'
            WHEN w2.st #>> '{}' = '正常' AND truth_vault.tv_ms_to_cn(w2.chk) IS NOT NULL THEN '最近检查时间(巡查状态=正常)'
       END                              AS comments_observed_source,
       CASE WHEN jsonb_typeof(w2.st) = 'string' THEN w2.st #>> '{}' END AS patrol_status,
       -- 曝光 / 阅读 / 互动: 运营截图读出来的数, 只知道 TV 哪天第一次看到
       truth_vault.tv_jsonb_num(w2.imp) AS impressions,
       w2.imp_day                       AS impressions_changed_cn_day,
       truth_vault.tv_jsonb_num(w2.rd)  AS reads,
       w2.rd_day                        AS reads_changed_cn_day,
       truth_vault.tv_jsonb_num(w2.it)  AS interactions,
       w2.it_day                        AS interactions_changed_cn_day
FROM w2
WHERE w2.cc_chg OR w2.imp_chg OR w2.rd_chg OR w2.it_chg;

COMMENT ON VIEW truth_vault.v_note_observations IS
    '每篇每个北京日一行, 只出 评论数 / 曝光 / 阅读 / 互动 至少一个变了的那些天 (v1.27, D-155), 全部从 audit_log 读。'
    '每个指标给那天结束时的值和「哪天变成这样的」(*_changed_cn_day = TV 第一次看到这个数的北京日, 不是量到的那一刻)。'
    'comments_observed_at_cn 是评论数量到的北京时间: 有「评论数观测时间」用它, 否则用「最近检查时间」且只在「巡查状态」= 正常 时给。'
    '曝光 / 阅读 / 互动 是运营截图读出来的, 截图时刻没有记录。查的时候带 note_id。';
