-- truth_vault v1.12 · 判爆只看评论数 (D-062, 2026-09-17 运营对齐)
-- ════════════════════════════════════════════════════════════════════
-- 运营口径(data-analysis/ops-answers-2026-09-17.md Q1):
--   爆贴【只看评论数】, 全项目统一: 爆 ≥ 50 / 大爆 ≥ 100 / 评估中 20~50 / 趴 < 20。
--   有评论数的 5 个项目逐行验过, 运营手标与这个门槛几乎全对上。
--
-- 三件事:
--   1. notes 加 comments_count —— 判爆的唯一依据此前只以 raw_extra 键存在
--      (「实时数据.评论数」/「评论数」), 库里没有 typed 列。
--   2. tier CHECK 加 '评估中' —— 它是 20~50 条评论的正式档位, 不是"还没下结论";
--      此前 16 张表的 mapping 都把它映成 '未知'。
--   3. 回填: 把 tier_source='数值推断' 的行退回"没有推断"的状态。
--      旧的数值推断按【互动量】过项目阈值升 tier, 和运营的尺子(评论数)不是一把;
--      43 条里 12 条来自评估中(按口径根本不是爆), 其余 31 条没有状态列可依。
--      退回之后由同步脚本用新尺子(comments_count ≥50/≥100)重新推断 —— 迁移里【不】
--      重写一遍推断规则, 那是 D-061 里回填 SQL 与 _provenance() 分叉的老毛病。
--
-- 幂等: 三步都可重跑。回填第二次跑时已没有 '数值推断' 行, 自然 0 行。
-- 应用顺序: 在 notes_v1_3_reference_tier.sql 之后(它最后一次定义 tier CHECK)。
-- ════════════════════════════════════════════════════════════════════

-- ── 1. 评论数 typed 列 ──
ALTER TABLE truth_vault.notes ADD COLUMN IF NOT EXISTS comments_count INTEGER;
COMMENT ON COLUMN truth_vault.notes.comments_count IS
    '帖子当前总评论数(巡查机器人抓的实时值, 含运营自己铺的评论 —— 运营 2026-09-17 确认)。'
    '判爆的唯一依据: ≥50 爆 / ≥100 大爆。来源列: 实时数据.评论数 / 评论数。'
    '⚠️ 与 interactions 不同步: 互动量是数据回收时的快照, 评论数是实时的。';

-- ── 2. tier CHECK 加 评估中 ──
ALTER TABLE truth_vault.notes DROP CONSTRAINT IF EXISTS notes_tier_check;
ALTER TABLE truth_vault.notes ADD CONSTRAINT notes_tier_check
    CHECK (tier IN ('趴', '预备', '评估中', '爆', '大爆', '参考', '风控', '删除', '未知', '数据异常'));
COMMENT ON COLUMN truth_vault.notes.tier IS
    '爆款分级。运营口径(D-062): 只看评论数, 爆≥50 / 大爆≥100 / 评估中 20~50 / 趴<20, 全项目统一。'
    '评估中 是正式档位(2026-09-17 前被映成 未知)。参考 = 运营人工挑的, 不计爆款统计。';

-- ── 3. 回填: 旧的按互动量数值推断 → 退回"没有推断" ──
--   · 状态列里写着 评估中 的 → tier=评估中, tier_source=状态字段 (等价于 mapping 修好后同步会写的值)
--   · 状态列在场但不是评估中 的 → tier=未知, tier_source=状态字段 (生产上目前 0 行, 为完备保留)
--   · 压根没有状态列的 → tier=NULL, tier_source=NULL (同步对"无状态、无推断"的行就是这么写的)
--   同步脚本下一轮会按 comments_count 重新推断 —— 有评论数的项目(TGV 14 条评论数 ≥203)会回到
--   爆/大爆, 没有评论数的(TXQ/HXZ)按新口径就是不推断。
DO $$
DECLARE
    n_pinggu INT := 0;
    n_other  INT := 0;
    n_none   INT := 0;
BEGIN
    UPDATE truth_vault.notes
       SET tier = '评估中', tier_source = '状态字段'
     WHERE tier_source = '数值推断'
       AND raw_extra->>'_tier_source_raw' ILIKE '%评估中%';
    GET DIAGNOSTICS n_pinggu = ROW_COUNT;

    UPDATE truth_vault.notes
       SET tier = '未知', tier_source = '状态字段'
     WHERE tier_source = '数值推断'
       AND raw_extra ? '_tier_source_raw';
    GET DIAGNOSTICS n_other = ROW_COUNT;

    UPDATE truth_vault.notes
       SET tier = NULL, tier_source = NULL
     WHERE tier_source = '数值推断';
    GET DIAGNOSTICS n_none = ROW_COUNT;

    RAISE NOTICE 'D-062 回填: 数值推断 → 评估中 % 行 / 未知 % 行 / 无状态 % 行 (下一轮同步按评论数重推)',
                 n_pinggu, n_other, n_none;
END $$;
