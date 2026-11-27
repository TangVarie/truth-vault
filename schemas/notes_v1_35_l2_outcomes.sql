-- ════════════════════════════════════════════════════════════════════
-- truth_vault v1.35 · 不含我方铺评的学习结果: 视图 v_l2_outcomes (W-64 下一步 ①; D-169 11-25 补记)
-- ════════════════════════════════════════════════════════════════════
--
-- 改什么: 只新建一个视图 truth_vault.v_l2_outcomes, 再收紧它的读权限。不动表, 不动 v_l2_labels, 不改任何默认。
--
-- 为什么: 今天学的「爆」(v_l2_labels.y; 写作台 priors 的命中 / 评论 ≥ 20) 本质是一条评论数线, 我们自己铺的评论也算在里面
--   (data-analysis/hit-attribution-2026-11-25.md §1、§5)。「阅读过本项目中位数」不含我方评论, 今天就能算。
--   「真实读者评论数」还算不出来 (爬过评论区的帖约 1,460 篇, 其中约 950 篇有读者评论行, 都只有第一页; 运营贴的行记不全铺了多少), 这里只当诊断列给。
--
-- 一行 = 一篇有档位 (爆 / 大爆 / 趴) 的帖, synthetic 和投流 (data_quality_flags.paid_promoted = true) 的不要 (投流把阅读抬高)。
--   y_hit                今天的口径 = v_l2_labels.y; 被 v_l2_labels 洗掉的爆 (数值推断 / 铺评工单 / 互动不高于趴中位…) 是 NULL
--   reads                阅读 (运营后台截图读出来的, 截图时刻不固定: W-64 查到「72h」其实约在第 4.6 天)
--   reads_pct_in_project 阅读在本项目「可比的帖」里的分位 (percent_rank, 0–1)
--   y_reads_median       阅读 > 本项目中位数 → 1, 否则 0 (正好等于中位数算 0)
--   y_reads_top_quartile 阅读 > 本项目 75 分位 → 1, 否则 0
--   「可比的帖」= 小红书、有阅读、发布满 14 天 (阅读还在涨的不算)。本项目可比的帖不到 30 篇、抖音 (没有阅读)、
--   没满 14 天、没有阅读 → 这三列都是 NULL。中位数这条线很松 (11-25 现有的 L2 正例全部过线), 用的时候把分位或 top-quartile 一起报。
--   seeded_comment_rows  运营在飞书贴的评论行数 (comments.source IS NULL) —— 只是诊断, 不是结果
--   reader_comment_rows  巡查工具看到的读者那一侧评论行数 (第一页; 有明细用明细, 没有用快照; 不含命中关键词的、不含贴主的);
--                        没爬过评论区是 NULL —— 只是诊断, 不是结果, 第一页数不出总量
--
-- 读权限: 视图带 account_id (D-169 的含义), 只给 service_role, 不给 anon / authenticated。
-- 怎么跑: owner 在 Supabase SQL editor 整段粘贴运行一次。要在 v1_15 (v_l2_labels)、v1_22 (paid_promoted)、
--   v1_27 (comments.source) 之后, 生产早都跑过。
-- 可以重跑: CREATE OR REPLACE VIEW + REVOKE / GRANT, 跑几遍结果都一样。不写任何表, 没有要备份的数据;
--   回滚 = DROP VIEW truth_vault.v_l2_outcomes; (还没有别的视图依赖它)。
-- 跑完看最后一个 SELECT: 行数、可比的帖、过中位数的篇数、前端角色能不能读 (应是 false / false)。
-- 夹具: scripts/check_l2_outcomes.sql (CI sql job)。
-- ════════════════════════════════════════════════════════════════════

CREATE OR REPLACE VIEW truth_vault.v_l2_outcomes AS
WITH base AS (
    SELECT n.note_id, n.project_id, n.account_id, n.publish_time, n.platform, n.tier, n.reads,
           (n.platform = 'xiaohongshu' AND n.reads IS NOT NULL
            AND n.publish_time <= now()::timestamp without time zone - interval '14 days') AS comparable
    FROM truth_vault.notes n
    WHERE n.tier IN ('爆', '大爆', '趴')
      AND COALESCE(n.data_quality_flags ->> 'synthetic', 'false') <> 'true'
      AND COALESCE(n.data_quality_flags ->> 'paid_promoted', 'false') <> 'true'
),
proj AS (
    SELECT project_id, count(*) AS n_comparable,
           percentile_cont(0.5)  WITHIN GROUP (ORDER BY reads) AS reads_median,
           percentile_cont(0.75) WITHIN GROUP (ORDER BY reads) AS reads_p75
    FROM base WHERE comparable GROUP BY project_id
),
pct AS (
    SELECT note_id, percent_rank() OVER (PARTITION BY project_id ORDER BY reads) AS reads_pct_in_project
    FROM base WHERE comparable
),
cm AS (
    SELECT c.note_id,
           count(*) FILTER (WHERE c.source IS NULL) AS seeded_rows,
           count(*) FILTER (WHERE c.source = 'linkcheck_records' AND c.is_scripted IS NOT TRUE
                              AND c.comment_role IS DISTINCT FROM '贴主') AS reader_records,
           count(*) FILTER (WHERE c.source = 'linkcheck_digest' AND c.is_scripted IS NOT TRUE
                              AND c.comment_role IS DISTINCT FROM '贴主') AS reader_digest,
           bool_or(c.source = 'linkcheck_records') AS has_records,
           bool_or(c.source = 'linkcheck_digest')  AS has_digest
    FROM truth_vault.comments c
    GROUP BY c.note_id
)
SELECT
    b.note_id, b.project_id, b.account_id, b.publish_time, b.platform, b.tier,
    l.y AS y_hit,
    b.reads,
    CASE WHEN b.comparable AND p.n_comparable >= 30 THEN pc.reads_pct_in_project END AS reads_pct_in_project,
    CASE WHEN b.comparable AND p.n_comparable >= 30 THEN (b.reads > p.reads_median)::int END AS y_reads_median,
    CASE WHEN b.comparable AND p.n_comparable >= 30 THEN (b.reads > p.reads_p75)::int END AS y_reads_top_quartile,
    COALESCE(cm.seeded_rows, 0)::int AS seeded_comment_rows,
    CASE WHEN cm.has_records THEN cm.reader_records
         WHEN cm.has_digest  THEN cm.reader_digest END::int AS reader_comment_rows
FROM base b
LEFT JOIN truth_vault.v_l2_labels l ON l.note_id = b.note_id
LEFT JOIN proj p ON p.project_id = b.project_id
LEFT JOIN pct pc ON pc.note_id = b.note_id
LEFT JOIN cm ON cm.note_id = b.note_id;

COMMENT ON VIEW truth_vault.v_l2_outcomes IS
    'W-64 ①: 不含我方铺评的学习结果 (阅读过本项目中位数) 与 y_hit 并排。一行一篇有档位的帖, 不含 synthetic / 投流。'
    'y_reads_* 只在小红书、有阅读、发布满 14 天、本项目这样的帖 ≥ 30 篇时有值, 否则 NULL; 正好等于中位数算 0。'
    '阅读来自运营截图, 时刻不固定; 中位数线很松, 配 reads_pct_in_project / y_reads_top_quartile 一起报。'
    'seeded_comment_rows / reader_comment_rows 只是诊断 (读者那一侧只有第一页), 不是结果。不给 anon / authenticated。';

REVOKE ALL ON truth_vault.v_l2_outcomes FROM PUBLIC;
REVOKE ALL ON truth_vault.v_l2_outcomes FROM anon, authenticated;
GRANT SELECT ON truth_vault.v_l2_outcomes TO service_role;

-- 回读 (只有计数)
SELECT count(*)                                           AS rows_total,
       count(*) FILTER (WHERE y_reads_median IS NOT NULL) AS rows_with_reads_outcome,
       count(DISTINCT project_id) FILTER (WHERE y_reads_median IS NOT NULL) AS projects_with_reads_outcome,
       count(*) FILTER (WHERE y_reads_median = 1)         AS above_median,
       count(*) FILTER (WHERE y_hit = 1 AND y_reads_median = 1) AS hits_above_median,
       count(*) FILTER (WHERE y_hit IS NULL AND tier IN ('爆', '大爆') AND y_reads_median = 1) AS cleaned_hits_above_median,
       count(*) FILTER (WHERE reader_comment_rows IS NOT NULL) AS notes_with_reader_rows,
       has_table_privilege('anon', 'truth_vault.v_l2_outcomes', 'SELECT')          AS anon_can_read,
       has_table_privilege('authenticated', 'truth_vault.v_l2_outcomes', 'SELECT') AS authenticated_can_read
FROM truth_vault.v_l2_outcomes;
