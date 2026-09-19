-- ════════════════════════════════════════════════════════════════════
-- truth_vault v1.15 · L2 正负例口径的唯一住处: v_l2_labels (+ v_l2_labels_v1 对照)
-- ════════════════════════════════════════════════════════════════════
--
-- 升级迁移 (不是 fresh install 基线)。只建两个视图, 不动表。
--
-- 为什么:
--   L2 的正例/负例口径一直只活在文档里 (signal-definitions §八 的判据、l2-feasibility §8.6 的
--   复现 SQL 里的 d 子查询), 每个分析各抄一遍。docs/28 (D-065 草案) 要让特征对比、闸二、闸三都
--   读同一个口径, 所以先把它落成视图 —— 以后 l2 的 SQL 只读 v_l2_labels, 不再各写各的。
--
-- 两个视图:
--   v_l2_labels_v1  逐字照搬 l2-feasibility §8.6 的 d (只去掉「有 essence、正文 ≥ 50 字」两条,
--                   那是实验取数条件, 不是口径)。目的是能复现 9/16 的数字、确认管道对得上。
--                   它带着四处已知问题, 【故意不修】, 留作对照; 下一轮实验对完账就可以退役。
--   v_l2_labels     修了四处 (D-067):
--     (a) raw_extra 为 NULL 时 NOT (raw_extra ? … OR raw_extra ? …) 整体为 NULL → 干净爆款被静默排除
--     (b) tier_source <> '数值推断' 对 NULL 同理 → IS DISTINCT FROM
--     (c) 比 signal-definitions §八 少了 synthetic 闸: 「伪500评」这类 synthetic 行不含「伪爆」二字,
--         会被当成正例 → 加 COALESCE(data_quality_flags->>'synthetic','false') <> 'true'
--     (d) 铺评工单改读引擎写的 data_quality_flags.comment_maintained_routes (D-060, 同时认顶层列
--         和 raw_extra._undeclared), 不再在视图里重写列名判据 (判据只有一份, 住引擎里; D-062 续)
--   生产实查 (2026-09-19): 389 条 爆/大爆 里 (a) 0 (b) 0 (c) 1 (d) 0; 顶层键与引擎 routes 完全重合
--   (41 = 41)。所以今天两版只差 1 条 (SPX 一条 synthetic 大爆); 修的是口径对齐和 NULL 健壮性,
--   不是今天的数字。差异报告见 data-analysis/l2-labels-v1-vs-v2-2026-09-19.md。
--
-- 列: note_id / project_id / account_id / publish_time / platform / y (1 = 正例, 0 = 趴)。
--   不在这里过滤 essence 或正文长度 —— 那是各实验自己的取数条件。
--   评估中 / 参考 / 风控 / 删除 / 未知 / 预备 都不在视图里 (既不是正例也不是负例)。
--
-- 部署: psql -d <shared_supabase> -f notes_v1_15_l2_labels.sql   (顺序无要求, 只依赖 notes 表)
-- 幂等: CREATE OR REPLACE VIEW, 可安全重跑。
-- ════════════════════════════════════════════════════════════════════

-- 1. 对照版: 逐字沿用 l2-feasibility §8.6 的 d。⚠️ 带着 (a)(b)(c)(d) 四处问题, 故意不修。
CREATE OR REPLACE VIEW truth_vault.v_l2_labels_v1 AS
WITH pa AS (
    SELECT project_id, percentile_disc(0.5) WITHIN GROUP (ORDER BY interactions) AS pm
    FROM truth_vault.notes
    WHERE tier = '趴' AND interactions IS NOT NULL
    GROUP BY 1
)
SELECT n.note_id, n.project_id, n.account_id, n.publish_time, n.platform,
       CASE WHEN n.tier IN ('爆', '大爆') THEN 1 ELSE 0 END AS y
FROM truth_vault.notes n
LEFT JOIN pa USING (project_id)
WHERE n.tier = '趴'
   OR ( n.tier IN ('爆', '大爆')
        AND COALESCE(n.raw_extra->>'_tier_source_raw', '') NOT LIKE '%伪爆%'
        AND NOT (n.raw_extra ? '维护评论50条' OR n.raw_extra ? '评论铺设情况')
        AND n.tier_source <> '数值推断'
        AND NOT (n.interactions IS NOT NULL AND pa.pm IS NOT NULL
                 AND n.interactions <= pa.pm) );

-- 2. 正式版: signal-definitions §八 的五条, NULL 安全, 铺评工单读引擎 routes。
CREATE OR REPLACE VIEW truth_vault.v_l2_labels AS
WITH pa AS (
    SELECT project_id, percentile_disc(0.5) WITHIN GROUP (ORDER BY interactions) AS pm
    FROM truth_vault.notes
    WHERE tier = '趴' AND interactions IS NOT NULL
    GROUP BY 1
)
SELECT n.note_id, n.project_id, n.account_id, n.publish_time, n.platform,
       CASE WHEN n.tier IN ('爆', '大爆') THEN 1 ELSE 0 END AS y
FROM truth_vault.notes n
LEFT JOIN pa USING (project_id)
WHERE n.tier = '趴'
   OR ( n.tier IN ('爆', '大爆')
        -- ① 运营没判的不算 (b: NULL 安全)
        AND n.tier_source IS DISTINCT FROM '数值推断'
        -- ② 假爆款闸 (c: 之前漏了这条)
        AND COALESCE(n.data_quality_flags ->> 'synthetic', 'false') <> 'true'
        -- ③ ② 的冗余兜底
        AND COALESCE(n.raw_extra ->> '_tier_source_raw', '') NOT LIKE '%伪爆%'
        -- ④ 铺评工单 = D-060 的 route (d: 读引擎, 不重写列名判据; a: 不再碰 raw_extra ? …)
        AND NOT (COALESCE(n.data_quality_flags -> 'comment_maintained_routes', '[]'::jsonb) ? '铺评工单')
        -- ⑤ 内部自洽: 互动不能低于本项目「趴」的中位
        AND NOT (n.interactions IS NOT NULL AND pa.pm IS NOT NULL
                 AND n.interactions <= pa.pm) );
