-- ════════════════════════════════════════════════════════════════════
-- truth_vault v1.34 · 书架排序的账号项换成「收缩后的账号先验」(G-06; docs/28 §7.1 第 3 条, D-065 续 #7)
-- ════════════════════════════════════════════════════════════════════
--
-- 改什么: 只重建一个视图 truth_vault.v_flywheel_lesson_cards。不动表, 不删列。
--   rank_score 里的账号项:
--     旧  COALESCE(personal_bao_rate, 0.3) × 0.3            (分母含风控 / 删除, 分子含数值推断; 60/306 张卡用默认 0.3)
--     新  0.3 × (1 − account_prior)
--   account_prior = (这个账号【更早发布】的清洗后正例数 + 10 × 项目基线) / (这个账号更早发布的清洗后标签篇数 + 10)
--     · 标签只读 v_l2_labels (已剔数值推断 / synthetic / 伪爆 / 铺评工单 / 互动不高于本项目趴中位的爆)。
--     · 「更早」= publish_time 严格小于这张卡: 卡自己、同一时刻发的都不算 (同 gate2_run.account_prior_strata)。
--       账号跨项目算; 没有账号、没有更早的标签 → 先验 = 项目基线。
--     · 项目基线 = 本项目 v_l2_labels 的平均 y; 本项目一个正例都没有 (或不在 v_l2_labels 里) → 用全库平均 y。
--   意思: 弱账号爆出来的那张卡, 更能说明内容本身的功劳, 往前排。账号项永远在 [0, 0.3]。
--   列: v1_14 的列一个不少、顺序不变 (account_bao_rate 留着当旧列, 代码里没人读它);
--       末尾加两列 account_prior (收缩后的先验) 和 account_prior_n (用了几篇更早的标签)。
--   v_top_performing_accounts 不动 (它还喂注入候选视图和 CI 的爆率测试)。
--
-- 影响: 写手借到的卡会变 (11-25 按本文件的定义在生产只读现算: 书架约 330 张, 前 20 张约留 11 张, 馆员常驻的前 8 张留 3 张;
--   数字每天随新数据小动, 见 D 条目的前后对照)。
--   library_version 不含 rank_score: 已缓存的选卡要等月份桶或候选集合变了才换; 新请求马上用新顺序。
--   不花钱, 不调模型。PostgREST 读的列都还在。生产实测整视图约 64 ms。
--
-- 怎么跑: owner 在 Supabase SQL editor 整段粘贴运行一次。必须在 v1_14、v1_15 之后 (生产早已跑过)。
--   什么时候跑 (D-180 第 6 条): 写手收工后; 避开北京 20:47–00:47 (夜跑同步的时段);
--   和 G-24 的批准层 v4 (PR-2 合并) 至少错开 3 天 —— 两次写手看得见的变化分开归因。v4 要合之前工程会先说。
-- 可以重跑: CREATE OR REPLACE VIEW, 跑几遍结果都一样; 最后那个 SELECT 重跑也给同一份前后对照。
-- 备份: 旧定义就是仓库里的 schemas/notes_v1_14_shelf_ticket_gate.sql (11-25 只读核过: 生产上的定义和它一致, 24 列)。
--   第 0 段先核一遍: 生产上的视图列不是 v1_14 的 24 列、也不是本文件的 26 列, 就报错停下, 什么都不改
--   (那说明有人改过, 仓库里的旧定义不能当备份; 把报错发给工程)。旧排序不另存: 能从视图自己的两列反推 (见最后的 SELECT)。
-- 回滚: 把下面第 1 段 rank_score 的最后一项换回 `+ COALESCE(a.personal_bao_rate, 0.3::double precision) * 0.3::double precision`
--   再跑一遍。不要 DROP VIEW 再跑 v1_14: 看板 public.v_dash_overview 依赖这个视图, DROP 会连带删掉它;
--   新加的两列留着不碍事 (CREATE OR REPLACE 不许删列)。
-- 跑完只看最后一个 SELECT (编辑器只显示最后一个结果):
--   cards 和 cards_v1_14_rule 一样 (按 v1_14 的准入数, 一张没丢); rank_score_null 0; prior_out_of_range 0;
--   top20_kept 约 11、top8_kept 约 3 (第一次跑和重跑都是这个数)。
-- ════════════════════════════════════════════════════════════════════

-- 0. 先核生产上的视图还是仓库里的样子 (v1_14 的 24 列, 或者本文件跑过之后的 26 列); 不是就停, 不改任何东西
DO $$
DECLARE
  cols text[];
  v14 text[] := ARRAY['source_note_id','project_id','brand','category','platform','tier','tier_source','publish_time',
                      'emotional_lever','target_audience','user_pain_point','content_format','hit_blue_keywords',
                      'hook_type','structure','why_it_worked','transferable_tactic','curated_at','is_curated',
                      'raw_excerpt','recency_weight','account_bao_rate','rank_score','synthetic'];
BEGIN
  SELECT array_agg(column_name::text ORDER BY ordinal_position) INTO cols
  FROM information_schema.columns WHERE table_schema = 'truth_vault' AND table_name = 'v_flywheel_lesson_cards';
  IF cols IS DISTINCT FROM v14 AND cols IS DISTINCT FROM v14 || ARRAY['account_prior', 'account_prior_n'] THEN
    RAISE EXCEPTION 'v1.34 没跑: 生产上 v_flywheel_lesson_cards 的列不是 v1_14 的样子, 仓库里的旧定义不能当备份。把这条报错发给工程。实际列: %', cols;
  END IF;
END $$;

-- 1. 视图
CREATE OR REPLACE VIEW truth_vault.v_flywheel_lesson_cards AS
WITH eligible AS (
    SELECT
        n.note_id, n.project_id, n.raw_content, n.account_id,
        n.tier, n.tier_source, n.publish_time, n.platform,
        n.emotional_lever, n.target_audience, n.user_pain_point, n.content_format,
        n.hit_blue_keywords, n.data_quality_flags,
        p.brand, p.category,
        -- essence 半衰期 5 年 + COR-024 未来日期夹到 [0,1] (同 v1_10 / v1_14, 原样保留)
        LEAST(1.0::double precision,
              power(0.5::double precision,
                    (EXTRACT(epoch FROM now()::timestamp without time zone - n.publish_time)
                     / (86400.0 * 30.0 * 60.0))::double precision)) AS recency_weight
    FROM truth_vault.notes n
    JOIN truth_vault.projects p ON p.project_id = n.project_id
    WHERE n.tier = ANY (ARRAY['爆', '大爆', '参考'])
      AND n.tier_source IS DISTINCT FROM '数值推断'
      AND n.publish_time IS NOT NULL
      AND NOT (COALESCE(n.data_quality_flags ->> 'synthetic', 'false') = 'true'
               AND n.tier = ANY (ARRAY['爆', '大爆']))
      -- v1.14: 铺评工单 (D-060 route) 的 爆/大爆 不上书架。读引擎写的 routes, 不重写判据。
      AND NOT (COALESCE(n.data_quality_flags -> 'comment_maintained_routes', '[]'::jsonb) ? '铺评工单'
               AND n.tier = ANY (ARRAY['爆', '大爆']))
),
-- v1.34 (G-06): 账号先验只读清洗后的标签 (v_l2_labels 是口径的唯一住处, D-067)
l2 AS (
    SELECT account_id, project_id, publish_time, y FROM truth_vault.v_l2_labels
),
proj_base AS (
    SELECT project_id, avg(y)::double precision AS base, sum(y) AS n_pos FROM l2 GROUP BY project_id
),
global_base AS (
    SELECT COALESCE(avg(y)::double precision, 0.0) AS base FROM l2
),
history AS (
    SELECT e.note_id, count(h.y) AS n_prev, COALESCE(sum(h.y), 0) AS pos_prev
    FROM eligible e
    LEFT JOIN l2 h ON h.account_id = e.account_id AND h.publish_time < e.publish_time
    GROUP BY e.note_id
),
prior AS (
    SELECT e.note_id, h.n_prev,
           (h.pos_prev + 10.0 * CASE WHEN pb.n_pos > 0 THEN pb.base ELSE g.base END)::double precision
             / (h.n_prev + 10)::double precision AS account_prior
    FROM eligible e
    JOIN history h ON h.note_id = e.note_id
    CROSS JOIN global_base g
    LEFT JOIN proj_base pb ON pb.project_id = e.project_id
)
SELECT
    e.note_id AS source_note_id,
    e.project_id, e.brand, e.category, e.platform,
    e.tier, e.tier_source, e.publish_time,
    e.emotional_lever, e.target_audience, e.user_pain_point, e.content_format,
    e.hit_blue_keywords,
    la.hook_type, la.structure, la.why_it_worked, la.transferable_tactic,
    la.curated_at,
    (la.note_id IS NOT NULL) AS is_curated,
    left(e.raw_content, 600) AS raw_excerpt,
    e.recency_weight,
    COALESCE(a.personal_bao_rate, 0.3::double precision) AS account_bao_rate,   -- 旧列, 只为列集不变; 不进 rank_score
    e.recency_weight
        + CASE e.tier
            WHEN '大爆' THEN 0.5
            WHEN '爆'   THEN 0.3
            WHEN '参考' THEN 0.15
            ELSE 0
          END::double precision
        + CASE e.tier_source
            WHEN '状态字段' THEN 0.2
            WHEN '备注字段' THEN 0.2
            WHEN '人工补录' THEN 0.2
            ELSE 0
          END::double precision
        + 0.3::double precision * (1.0::double precision - pr.account_prior) AS rank_score,
    (COALESCE(e.data_quality_flags ->> 'synthetic', 'false') = 'true') AS synthetic,
    pr.account_prior,
    pr.n_prev::integer AS account_prior_n
FROM eligible e
JOIN prior pr ON pr.note_id = e.note_id
LEFT JOIN truth_vault.flywheel_lesson_annotations la ON la.note_id = e.note_id
LEFT JOIN truth_vault.v_top_performing_accounts a   ON a.account_id = e.account_id;

-- 2. 回读: 只有这一个 SELECT, 只有计数。旧排序从视图自己的两列反推:
--    旧 rank_score = 新 rank_score − 0.3 × (1 − account_prior) + 0.3 × account_bao_rate (account_bao_rate 就是旧口径 COALESCE 过的值)。
--    cards_v1_14_rule 按 v1_14 的准入条件直接数 notes, 应和 cards 一样。
WITH v AS (
    SELECT source_note_id, rank_score, account_prior, account_prior_n,
           rank_score - 0.3 * (1 - account_prior) + 0.3 * account_bao_rate AS rank_score_old
    FROM truth_vault.v_flywheel_lesson_cards
), r AS (
    SELECT *, row_number() OVER (ORDER BY rank_score_old DESC, source_note_id) AS rk_old,
              row_number() OVER (ORDER BY rank_score DESC, source_note_id)     AS rk_new
    FROM v
)
SELECT count(*)                                                    AS cards,
       (SELECT count(*) FROM truth_vault.notes n JOIN truth_vault.projects p ON p.project_id = n.project_id
         WHERE n.tier = ANY (ARRAY['爆', '大爆', '参考'])
           AND n.tier_source IS DISTINCT FROM '数值推断'
           AND n.publish_time IS NOT NULL
           AND NOT (COALESCE(n.data_quality_flags ->> 'synthetic', 'false') = 'true' AND n.tier = ANY (ARRAY['爆', '大爆']))
           AND NOT (COALESCE(n.data_quality_flags -> 'comment_maintained_routes', '[]'::jsonb) ? '铺评工单'
                    AND n.tier = ANY (ARRAY['爆', '大爆'])))   AS cards_v1_14_rule,
       count(*) FILTER (WHERE rank_score IS NULL)                  AS rank_score_null,
       count(*) FILTER (WHERE account_prior IS NULL OR account_prior < 0 OR account_prior > 1) AS prior_out_of_range,
       count(*) FILTER (WHERE account_prior_n = 0)                 AS no_earlier_labels,
       count(*) FILTER (WHERE rk_old <= 20 AND rk_new <= 20)       AS top20_kept,
       count(*) FILTER (WHERE rk_old <= 8 AND rk_new <= 8)         AS top8_kept,
       round(avg(abs(rk_old - rk_new)), 1)                         AS mean_rank_move,
       count(*) FILTER (WHERE abs(rk_old - rk_new) > 50)           AS moved_over_50
FROM r;
