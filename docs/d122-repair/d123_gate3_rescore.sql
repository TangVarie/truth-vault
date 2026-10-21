-- ═══════════════════════════════════════════════════════════════════════════════════════════════
-- D-123 · 闸三打分器重冻之后: 备份并删掉旧版本 essence-v1-322f02c9465f 的 content_scores 行,
--         由下一次 daily-sync 的 gate3_score 用新版本 essence-v1-93035a562b2e 重打。
-- 生产 kduysqedrclrfevrxiie, Supabase SQL editor 整份粘贴执行 (第 0 步只读, 第 1 步一个事务)。
-- ═══════════════════════════════════════════════════════════════════════════════════════════════
--
-- ⚠️ 什么时候跑: TV 仓重冻那个 PR(TV#210)合并进 main 之后, 而且**没有 Daily TV sync 正在跑**的时候(Actions 页看一眼)。
--    合并之前就起跑的那一轮还是旧代码, 可能还在写 v1 行。第 1 步开头先锁表: 等正在写的事务提交、再挡住新写入直到 COMMIT,
--    快照之后才落地的 v1 行不会漏备份(codex review on TV#211); 锁放开之后还有旧代码在跑的话, 第 4 步「v1_rows = 0」会露出来。
--    合并之前跑的话, 当晚夜跑还是旧代码 (读 scorer-essence-v1.json): 新版本号下一行都没有 → 旧版本把这 80 篇按 v1 再打一遍,
--    v1 行又回来了, 只能再删一次。合并之后跑: 旧版本不再有人写, 删掉就是删掉。
--
-- 为什么不用删也能重打 (gate3_score.py, 10-20 读过代码):
--    fetch() 取「已打过」只取 subject_type='note' AND scorer_version = 当前冻结文件的版本号; plan() 只跳过这个集合里的 note_id。
--    新版本号下没有任何行 → 冻结日 (publish_time ≥ 2026-10-17) 之后、有 essence、标注器对得上的笔记全部重打, 一篇不漏;
--    fetch_labeled() / 附录 C 进度也只读新版本号的行。所以 v1 行留着不影响打分和判定, 删它是 D-122 修复计划第 4 条 A 定的
--    「备份后删掉、按新版重打」: 库里不留两套分, 以后谁按 subject_id 联表都不会撞到作废的那一套。
--
-- 10-20 16:30 UTC 只读核过 (只数数):
--    content_scores 共 80 行, 全是 essence-v1-322f02c9465f, 新版本号 0 行;
--    按项目 BJS_phase1 7 / HATHERINE_phase1 7 / SPX_phase1 15 / TUGE_phase1 9 / XIWU_phase2 42;
--    按打分日 (UTC) 10-18 6 行 / 10-19 23 行 / 10-20 51 行; cutpoints project 38 / pooled 42;
--    冻结日之后发布的笔记 80 篇, 全部有 essence、标注器全部对得上 (v0.2 / prediction_feature), 0 篇没打分;
--    其中 3 篇 (HATHERINE) 在 D-122 恢复名单里, 2 篇是 content_format 被冲掉之后才打的分;
--    冻结日之后发布的笔记落标签 (v_l2_labels) 0 篇 —— 重冻时没有看到任何一篇被测笔记的结果。
--    content_scores: 主键 (subject_type, subject_id, scorer_version); 没有触发器、没有视图依赖它; RLS 开着 (SQL editor 不受影响)。
--
-- 合并后到跑这份 SQL 之间要是又跑过一次旧代码的夜跑 (v1 行变多), 第 1 步的行数守卫会 RAISE、整块回滚:
-- 先跑第 0 步看实际行数, 确认多出来的都是旧代码打的 v1 行, 再把第 1 步里的 expected 改成那个数。

-- ── 0. 只读: 现在有几行、各是哪个版本 ───────────────────────────────────────────────────────────
SELECT scorer_version, subject_type, count(*) AS n, min(scored_at) AS first_scored, max(scored_at) AS last_scored
FROM truth_vault.content_scores
GROUP BY 1, 2
ORDER BY 1, 2;
-- 期望 (10-20): essence-v1-322f02c9465f | note | 80; 没有 essence-v1-93035a562b2e 的行。

-- ── 1. 备份 + 删除 (一个事务; 行数对不上就 RAISE, 建表和删除一起回滚) ────────────────────────────
BEGIN;

LOCK TABLE truth_vault.content_scores IN SHARE ROW EXCLUSIVE MODE;

CREATE TABLE truth_vault.backup_content_scores_d122_20261020 AS
SELECT c.*, now() AS backed_up_at
FROM truth_vault.content_scores c
WHERE c.scorer_version = 'essence-v1-322f02c9465f';

COMMENT ON TABLE truth_vault.backup_content_scores_d122_20261020 IS
'D-123 / D-122 修复计划第 4 条 A: 闸三打分器 essence-v1-322f02c9465f 是 10-16 在被夜跑冲掉 F / U token 的数据上冻结的, 10-20 恢复后按同一 SQL 重冻为 essence-v1-93035a562b2e (冻结日 2026-10-17 不动)。本表是删掉的旧版本 content_scores 行原样 (10-20: 80 行), 下一次 daily-sync 用新版本重打。回滚 (只在要退回旧版本时; 先把 TV 仓 SCORER_PATH 改回 scorer-essence-v1.json): insert into truth_vault.content_scores (subject_type, subject_id, project_id, scorer_version, score, pct_in_project, cutpoints, shadow, scored_at) select subject_type, subject_id, project_id, scorer_version, score, pct_in_project, cutpoints, shadow, scored_at from truth_vault.backup_content_scores_d122_20261020 on conflict (subject_type, subject_id, scorer_version) do nothing; 11-20 之后可删 (S-02)。';

DO $$
DECLARE
  expected CONSTANT int := 80;     -- 10-20 16:30 UTC 的数; 见文件头: 合并后又跑过旧代码夜跑就先跑第 0 步再改这里
  n_bak int;
  n_del int;
  n_left int;
  n_new int;
BEGIN
  SELECT count(*) INTO n_bak FROM truth_vault.backup_content_scores_d122_20261020;
  IF n_bak <> expected THEN
    RAISE EXCEPTION 'D-123: 备份到 % 行 essence-v1-322f02c9465f, 预期 % 行 —— 整块回滚 (先跑第 0 步看多出 / 少了的是什么)', n_bak, expected;
  END IF;

  DELETE FROM truth_vault.content_scores c
  USING truth_vault.backup_content_scores_d122_20261020 b
  WHERE c.subject_type = b.subject_type
    AND c.subject_id = b.subject_id
    AND c.scorer_version = b.scorer_version;
  GET DIAGNOSTICS n_del = ROW_COUNT;
  IF n_del <> n_bak THEN
    RAISE EXCEPTION 'D-123: 删了 % 行, 备份 % 行 —— 整块回滚', n_del, n_bak;
  END IF;

  SELECT count(*) INTO n_left FROM truth_vault.content_scores WHERE scorer_version = 'essence-v1-322f02c9465f';
  IF n_left <> 0 THEN
    RAISE EXCEPTION 'D-123: 删完还剩 % 行 essence-v1-322f02c9465f (删除期间有人在写?) —— 整块回滚', n_left;
  END IF;

  SELECT count(*) INTO n_new FROM truth_vault.content_scores WHERE scorer_version = 'essence-v1-93035a562b2e';
  RAISE NOTICE 'D-123: 备份并删除 % 行 essence-v1-322f02c9465f; 新版本 essence-v1-93035a562b2e 现有 % 行 (合并后第一次夜跑之前应为 0)', n_del, n_new;
END $$;

COMMIT;

-- ── 2. 回读 (只读, 跑完第 1 步马上看) ──────────────────────────────────────────────────────────────
SELECT
  (SELECT count(*) FROM truth_vault.backup_content_scores_d122_20261020)                                  AS backup_rows,      -- 80
  (SELECT count(*) FROM truth_vault.content_scores WHERE scorer_version = 'essence-v1-322f02c9465f')       AS v1_rows_left,     -- 0
  (SELECT count(*) FROM truth_vault.content_scores WHERE scorer_version = 'essence-v1-93035a562b2e')       AS new_rows;         -- 合并后第一次夜跑前 0; 之后跑就是新版本已打的篇数

-- ── 3. 重打 ─────────────────────────────────────────────────────────────────────────────────────────
-- 默认: 等下一次 daily-sync 定时跑 (cron 02:17 UTC, 实际 08:00 前后起跑), gate3_score 步把冻结日之后有 essence 的笔记全部按新版打一遍,
--       日志「闸三第一轨 · essence-v1-93035a562b2e · 冻结日 2026-10-17T00:00:00 (D-118 / D-123)」「本轮新打 N、以前打过 0」, 灯 rc=0。
-- 想早点打: Actions → Daily TV sync → Run workflow, skip_essence = true (essence / 策展两步跳过, 不花模型钱), dry_run = false, project 留空:
--       gh workflow run daily-sync.yml --ref main -f skip_essence=true -f dry_run=false
--       整轮飞书 / 评论同步照跑 (40–60 分钟, 和夜跑同一个 concurrency 组, 会排队不会并发)。gate3_score.py 没有单独的 workflow 入口。

-- ── 4. 重打之后回读 (只读, 夜跑之后) ───────────────────────────────────────────────────────────────
SELECT
  (SELECT count(*) FROM truth_vault.notes n
    WHERE n.publish_time >= '2026-10-17' AND coalesce(n.emotional_lever, '') <> ''
      AND n.essence_vocab_version = 'v0.2' AND n.essence_annotation_mode = 'prediction_feature')         AS should_be_scored,
  (SELECT count(*) FROM truth_vault.content_scores WHERE scorer_version = 'essence-v1-93035a562b2e')       AS new_rows,          -- = should_be_scored 减去灯里报的「没有可用 token」「标注器对不上」(10-20 都是 0)
  (SELECT count(*) FROM truth_vault.content_scores WHERE scorer_version = 'essence-v1-322f02c9465f')       AS v1_rows,           -- 0
  (SELECT count(*) FROM truth_vault.backup_content_scores_d122_20261020 b
    WHERE NOT EXISTS (SELECT 1 FROM truth_vault.content_scores c
                      WHERE c.subject_type = b.subject_type AND c.subject_id = b.subject_id
                        AND c.scorer_version = 'essence-v1-93035a562b2e'))                                  AS old_notes_not_rescored, -- 0
  (SELECT count(*) FROM truth_vault.content_scores
    WHERE scorer_version = 'essence-v1-93035a562b2e' AND project_id = 'XIWU_phase2' AND cutpoints = 'pooled') AS xiwu2_pooled;     -- 0 (新版本 XIWU_phase2 有项目切点)
-- 10-20 用新冻结文件对这 80 篇离线重算 (同一份 gate3_score.plan, 输入是当下的 essence), 下面的数都是【和库里现存的 80 行比】
-- (就是备份表里的、被删掉换成新分的那 80 行; 下面第 5 步拿备份表对):
--   80 篇全打, XIWU_phase2 42 篇从全库切点换成项目切点;
--   项目内分位平均 +0.10: XIWU_phase2 +0.18; HATHERINE −0.05 —— content_format 被冲掉之后才打分的 2 篇
--   reczz28Hc1QD80Li 0.580 → 0.391 (−0.19)、reczz28Hc1QD6olx 0.923 → 0.819 (−0.10); 其余项目 ±0.03 以内; 单篇最大变化 0.28 (XIWU_phase2);
--   落最低 20% 的 5 → 6 篇 (TUGE 多 1 篇)。
--   (拿「v1 按当下 essence 重放」当基线会是 HATHERINE −0.02、单篇最大 0.29: 那只量了换打分器这一部分, 那 2 篇的下降大半是恢复
--    content_format 带来的 (−0.155 / −0.091), 换打分器只占 −0.034 / −0.013。回读别拿那组数对。)
-- 有出入的话: 先看那篇的 essence 是不是打分之后又变过 (重打用的是当下的 essence; 10-20 已知 1 篇 XIWU_phase2 的 content_format
-- 在 10-20 夜跑被方向抬的值改了, 不是 NULL, 不属于 D-122)。

-- ── 5. 新分 vs 删掉的旧分, 按项目 (只读, 夜跑之后; 和上面那组数对) ─────────────────────────────────────
SELECT b.project_id,
       count(*)                                                        AS n,
       round(avg(c.pct_in_project - b.pct_in_project)::numeric, 3)     AS mean_dpct,      -- XIWU_phase2 +0.18 / HATHERINE −0.05 / 其余 ±0.03
       round(min(c.pct_in_project - b.pct_in_project)::numeric, 3)     AS min_dpct,
       round(max(c.pct_in_project - b.pct_in_project)::numeric, 3)     AS max_dpct,
       count(*) FILTER (WHERE b.cutpoints <> c.cutpoints)              AS cutpoints_changed, -- XIWU_phase2 42 (pooled → project), 其余 0
       count(*) FILTER (WHERE b.pct_in_project < 0.2)                  AS bottom20_old,
       count(*) FILTER (WHERE c.pct_in_project < 0.2)                  AS bottom20_new     -- 合计 5 → 6, TUGE 多 1
FROM truth_vault.backup_content_scores_d122_20261020 b
JOIN truth_vault.content_scores c
  ON c.subject_type = b.subject_type AND c.subject_id = b.subject_id AND c.scorer_version = 'essence-v1-93035a562b2e'
GROUP BY ROLLUP (b.project_id)
ORDER BY b.project_id NULLS LAST;
-- 合计行 (project_id 为 NULL): n 80, mean_dpct ≈ +0.10。HATHERINE 的 min_dpct ≈ −0.19 (reczz28Hc1QD80Li)。
