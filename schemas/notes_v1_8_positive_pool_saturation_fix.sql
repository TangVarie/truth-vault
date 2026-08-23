-- ════════════════════════════════════════════════════════════════════
-- schemas/notes_v1_8_positive_pool_saturation_fix.sql
-- ════════════════════════════════════════════════════════════════════
--
-- 2026-08-22 · D-041 附带修复 · 正例饱和度监控的盲点
--
-- 问题:
--   v_autowriter_positive_pool_saturation (notes_v1_2_cross_schema_views.sql:75)
--   的 WHERE 里有一句 `AND i.external_source = 'truth_vault'` —— 它只统计
--   【通道2 push 写进去的】正例。而 push 通道从没真跑过, 生产库里
--   autowriter.items.external_source 全是 NULL (docs/14:77 / CURRENT_STATE.md:77-79)。
--
--   后果: check_positive_saturation.py 在现实中【永远】打印
--   "No active positive examples in any autowriter project." ——
--   它测不到运营自己手标的那些 native 正例, 而那才是真正在注入 prompt 的池子
--   (docs/22:62-68 记录 owner 正例 14 条 / 负例 103 条)。
--
--   也就是说: 这个监控从上线到现在【一次都没有真正生效过】, 而它要监控的
--   趋同回路(模型模仿最近 5 条正例 → 新稿被标 positive → 窗口滚动 → 语感
--   越收越窄)一直在跑, 没有任何人看得见。
--
-- 修法:
--   1. 去掉 external_source 过滤 —— 统计全部正例(native + TV)。
--   2. 【按 user 分区】。deskcore 注入正例时是按 user_id 过滤的(正负例是个人
--      风格资产), 所以一个多人共用的项目有【多个各自独立的注入池】。原来的
--      窗口把全项目的正例混在一起取最近 5 条 —— 那个组合谁都没在用: 既可能
--      掩盖某个人已经饱和的池子, 也可能报出没人经历过的饱和。
--      窗口和输出都加 user_id(codex review P2)。
--   3. 补三列, 让"能测到什么/测不到什么"变成显式信息而不是静默的零:
--        native_positive_count   运营自己标的(external_source IS NULL)
--        tv_positive_count       TV push 写的(已退役, 预期恒为 0)
--        lever_measurable_count  能拿到 emotional_lever 的条数
--      native 正例没有 external_source_id, join 不到 truth_vault.notes,
--      所以【拿不到 lever】。与其让它们静默消失, 不如明确报出来:
--      "池子里 14 条, 其中 0 条能测多样性"。
--
--   CREATE OR REPLACE VIEW 只允许在末尾追加列, 不能改名/改类型/删列 ——
--   所以原有 6 列的名字、顺序、类型全部保持不变, 新列一律追加在最后。
--
-- ⚠️ 前提变更留档:
--   本 view 的"取 created_at DESC 前 5 条"复刻的是 autowriter
--   list_example_items(db.py:2169) 的取法。deskcore 起来之后, 正例改为
--   【按相关性检索 + 开头形态多样性约束】(deskcore/core.py:select_positive_examples,
--   D-041 改动 A), 不再是 recency top-5。所以对走 deskcore 的流量,
--   本 view 量的是"如果还按老办法取会怎样", 属于对照指标, 不是实际注入内容。
--   autowriter 完全退役后本 view 可以下线。
--
-- ⚠️⚠️ 为什么用 DROP + CREATE 而不是 CREATE OR REPLACE(codex review)
--
--   本文件给视图【追加了 4 列】。Postgres 的 CREATE OR REPLACE VIEW 只能在末尾
--   加列, **不能删列** —— 一旦本文件应用过, 任何试图把视图变回 6 列的语句都会
--   报 `ERROR: cannot drop columns from view`(已实测)。
--
--   后果不只是"回滚说明写错了", 更常见的是这个坑:
--     在已应用 v1_8 的库上【重跑基线 notes_v1_2_cross_schema_views.sql 会失败】——
--     而那个文件本身是按"可重复执行"设计并被 CI 反复应用的。
--
--   所以: 本文件自己先 DROP 再 CREATE(不带 CASCADE —— 万一将来有东西依赖它,
--   宁可让 DROP 报错, 也不要静默连带删掉别人); 回滚说明同理。
--   当前无任何对象依赖此视图(pg_depend 查过), DROP 是安全的。
--
-- 部署: Supabase SQL Editor 粘贴执行, 或 MCP apply_migration。
-- 幂等: DROP IF EXISTS + CREATE, 可重复执行。
--
-- 回滚(想变回 v1_2 的 6 列版本):
--   DROP VIEW IF EXISTS truth_vault.v_autowriter_positive_pool_saturation;
--   \i schemas/notes_v1_2_cross_schema_views.sql
--   -- ↑ 必须先 DROP。直接重跑基线会 ERROR: cannot drop columns from view。
-- ════════════════════════════════════════════════════════════════════

-- 先 DROP: 见文件头的说明。不带 CASCADE, 有依赖时宁可报错。
DROP VIEW IF EXISTS truth_vault.v_autowriter_positive_pool_saturation;

CREATE VIEW truth_vault.v_autowriter_positive_pool_saturation AS
WITH top_5 AS (
    SELECT
        b.project_id AS aw_project_id,
        i.external_source_id AS tv_note_id,
        i.external_source,
        n.emotional_lever,
        i.user_id,
        ROW_NUMBER() OVER (
            -- v1_8: 加 user_id 进分区。deskcore 的注入池是 per-user 的, 混在
            -- 一起算出来的"最近 5 条"任何人都不曾用过。
            PARTITION BY b.project_id, i.user_id ORDER BY i.created_at DESC
        ) AS rn
    FROM autowriter.items i
    JOIN autowriter.batches b ON b.id = i.batch_id
    LEFT JOIN truth_vault.notes n ON n.note_id = i.external_source_id
    WHERE i.example_label = 'positive'
    -- v1_8: 去掉 `AND i.external_source = 'truth_vault'`。
    -- 那一句让本 view 只看 push 通道写的行, 而那列全 NULL, 于是永远空。
),
in_pool AS (
    SELECT * FROM top_5 WHERE rn <= 5
),
lever_counts AS (
    SELECT aw_project_id, user_id, emotional_lever, COUNT(*) AS cnt
    FROM in_pool
    WHERE emotional_lever IS NOT NULL
    GROUP BY aw_project_id, user_id, emotional_lever
),
per_pool_top_lever AS (
    SELECT aw_project_id, user_id, MAX(cnt) AS top_lever_count
    FROM lever_counts
    GROUP BY aw_project_id, user_id
)
SELECT
    -- ── 原有 6 列: 名字/顺序/类型不变 (CREATE OR REPLACE 的硬要求) ──
    p.aw_project_id,
    COUNT(*)::INT AS active_positive_count,
    array_agg(DISTINCT p.emotional_lever)
        FILTER (WHERE p.emotional_lever IS NOT NULL) AS lever_distribution,
    COUNT(DISTINCT p.emotional_lever)
        FILTER (WHERE p.emotional_lever IS NOT NULL)::INT AS distinct_lever_count,
    COALESCE(MAX(t.top_lever_count), 0)::INT AS top_lever_count,
    -- ⚠️ 分母改成【可测条数】而不是池子总条数。用总条数当分母会让
    -- "5 条里只有 1 条能测 lever" 算出 ratio=0.2 显示成健康, 实际是没测到。
    CASE WHEN COUNT(*) FILTER (WHERE p.emotional_lever IS NOT NULL) > 0
         THEN ROUND(
                COALESCE(MAX(t.top_lever_count), 0)::numeric
                / COUNT(*) FILTER (WHERE p.emotional_lever IS NOT NULL)::numeric, 2)
         ELSE NULL          -- NULL = 测不了, 不是"健康"
    END AS dominant_lever_ratio,

    -- ── v1_8 新增 3 列 (追加在末尾) ──
    COUNT(*) FILTER (WHERE p.external_source IS NULL)::INT
        AS native_positive_count,
    COUNT(*) FILTER (WHERE p.external_source = 'truth_vault')::INT
        AS tv_positive_count,
    COUNT(*) FILTER (WHERE p.emotional_lever IS NOT NULL)::INT
        AS lever_measurable_count,
    -- v1_8: 池子归谁。NULL = 历史行没记 user_id(或 TV push 写的)。
    -- 一个 aw_project_id 现在可能有多行, 每个用户一行 —— 这是刻意的, 因为
    -- 每个人的注入池是独立的。
    p.user_id AS pool_user_id
FROM in_pool p
LEFT JOIN per_pool_top_lever t
       ON t.aw_project_id = p.aw_project_id
      AND t.user_id IS NOT DISTINCT FROM p.user_id
GROUP BY p.aw_project_id, p.user_id;

COMMENT ON VIEW truth_vault.v_autowriter_positive_pool_saturation IS
    '正例池饱和度(按 project × user 分区 —— deskcore 的注入池是 per-user 的). '
    'v1_8 修掉只看 external_source=truth_vault 的盲点(那列全 NULL, '
    '导致本 view 从上线起一直为空). dominant_lever_ratio 的分母是【可测条数】, '
    'NULL 表示测不了而非健康. native 正例 join 不到 truth_vault.notes 故无 lever. D-041.';
