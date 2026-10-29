# 投流证据链读数（F1 / F2）· 2026-10-29 · 骨架

> **这是骨架。** `schemas/notes_v1_22_paid_boost_evidence.sql` 还没在生产跑（owner 在 SQL editor 跑；只建函数和视图，可重跑）。
> 跑之前生产里没有这几张视图，所以下面凡是要读视图的格子都空着，只写了「跑完怎么填」。现在就能报的只读数单独列在 §1。
> 口径和取舍见 DECISIONS D-133；要问运营的口径见 OPEN-ITEMS O-06。
> 全文只放计数、标记取值和日期，不放帖子正文、评论原文、账号昵称；要指到具体某篇，用 `项目 …note_id 末 6 位`（同 D-131 的写法）。

**措辞约定（填的时候照用）**：这是逐例证据，不做因果结论；「维护效果」是运营自报，口径没定（`ops_effect_metric_flag = unknown`）；
缺的格子写 `missing:<原因>`，不是 0；曝光总数里本来就含投流量；评论增量里混着铺评，看 `comment_maintained_seeded`。

---

## 0. 填之前要做完的事

1. 合并前（只读）记一份基线，填进 §8 的「合并前」列。
2. owner 跑 v1_22。跑完 `scripts/verify_supabase_state.sql` #98 应为 0（11 = 没跑）。
3. 合并后等一晚（daily-sync），再填 §8 的「第一晚后」列，再填 §2–§7。

## 1. 现在就能报的（10-29 只读重测，不读视图）

**标记列在哪些项目里有值**（篇数；`raw_extra` 顶层空才看 `_undeclared`）：

| 项目 | 篇数 | 维护情况 | 维护时间 | 维护效果 | 关注情况 | tier 源含「关注后续流量」 | paid_promoted 真 / 假 / 缺 |
|---|---|---|---|---|---|---|---|
| ANSHEN_phase1 | 201 | 18 | 0 | 0 | 13 | 0 | 2 / 199 / 0 |
| BJS_phase1 | 182 | 18 | 0 | 0 | 0 | 0 | 7 / 175 / 0 |
| BJS_phase2 | 95 | 1 | 1 | 0 | 0 | 0 | 0 / 95 / 0 |
| HATHERINE_phase1 | 327 | 7 | 20 | 20 | 0 | 0 | 0 / 327 / 0 |
| SPX_phase1 | 643 | 28 | 15 | 6 | 1 | 0 | 2 / 641 / 0 |
| TUGE_phase1 | 187 | 0 | 0 | 0 | 0 | 9 | 9 / 178 / 0 |
| XIWU_phase2 | 186 | 1 | 7 | 4 | 0 | 0 | 0 / 184 / 2 |
| 其余 12 个项目 | — | 0 | 0 | 0 | 0 | 0 | 全缺 |

（BJS_phase2 当天还在入库：上午 73 篇、下午 95 篇；以 apply 那天重数为准。）

- `paid_promoted = true` 共 20 篇，reason 只有六种写法：「维护情况」取值「9/15🍟」6、「08/27🍟」1、「已投流，等回收数据」1，「关注情况」取值「9/15🍟」2、「9/16🍟」1，tier 源含「关注后续流量」9。按 D-133 的新判据逐篇重算：20 篇照旧 true，认不出的元素 0 个。
- 「维护效果」30 篇、「维护时间」43 篇（OPEN-ITEMS 10-27 记的是 28 / 39）。维护时间 49 个元素的写法：`M月D日` 37、`YYYY/M/D` 11、`M/D` 1。
- 两列配对：HATHERINE 维护时间 1 个 + 维护效果 2 个的 1 篇（进隔离）；XIWU_phase2「一轮 / 二轮维护」那篇效果是「20条评论」（不算投流）；维护时间没有效果的 13 篇（SPX 9、XIWU_phase2 3、BJS_phase2 1）。
- **整块扫 🍟 会扫到的**（反证用，三张视图里都不该有它们）：`raw_extra` 里 🍟 不在维护情况 / 关注情况的 3 篇（RIO、ANSHEN、XIWU_phase2 各 1）；只在 audit_log 历史 raw_extra 里有 🍟 的 1 篇（ANSHEN）；标题正文 1 篇（NUC）；`data_quality_flags` 文本 10 篇（都是 `paid_promoted_reason`）。
- audit_log：355,771 行、285 MB，2026-05-27 起，没有任何作业在删（I-10）。`occurred_at` 是 UTC 无时区：抽查两篇，和同一行 `last_seen_at`（带时区）只差几秒。
- 书架 `v_flywheel_lesson_cards`：313 张（全部已策展）。全库 tier：趴 5,169 · 空 615 · 风控 310 · 爆 304 · 评估中 125 · 大爆 114 · 预备 108 · 未知 61 · 参考 2 · 数据异常 1（共 6,809 篇）。
- 本地预演（把上面这些标记列的子集、67 篇、不含正文，拷进本地 PG16 跑 v1_22，**不是生产视图的读数**）：事件 42（🍟 10 + 维护时间配数字效果 32），隔离 12（TUGE no_date 9、SPX no_date 1、HATHERINE 个数对不上 1、HATHERINE 早于发布 1），认不出 0；来源 B 的 32 次里 27 次是发布后 0–2 天投的。apply 之后以 §2 / §3 为准。

## 2. 投流事件（按项目 × 日期来源）—— 待填

```sql
SELECT project_id, array_to_string(date_sources, '+') AS src, count(*) AS events,
       count(*) FILTER (WHERE vanished) AS vanished,
       count(*) FILTER (WHERE takeoff_vs_window = 'in_window') AS takeoff_in_window
FROM truth_vault.v_paid_boost_events GROUP BY 1, 2 ORDER BY 1, 2;
```

| 项目 | 日期来源 | 事件 | 其中飞书已删 | 起量时间落在 [D, D+7] |
|---|---|---|---|---|
| | | | | |

## 3. 隔离（按原因，带原值）—— 待填

```sql
SELECT project_id, source_col, reason, raw_elem, count(*)
FROM truth_vault.v_paid_boost_quarantine GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3, 4;
```

| 项目 | 列 | 原因 | 原值 | 篇数 |
|---|---|---|---|---|
| | | | | |

## 4. 覆盖：每个事件有没有读数 —— 待填

```sql
SELECT count(*) AS events,
       count(*) FILTER (WHERE comments_base_status = 'ok') AS c_base,
       count(*) FILTER (WHERE comments_d1_status = 'ok') AS c_d1,
       count(*) FILTER (WHERE comments_d3_status = 'ok') AS c_d3,
       count(*) FILTER (WHERE comments_d7_status = 'ok') AS c_d7,
       count(*) FILTER (WHERE comments_delta_d7_status = 'ok') AS c_pair_d7,
       count(*) FILTER (WHERE impressions_base_status = 'ok') AS imp_base,
       count(*) FILTER (WHERE impressions_d7_status = 'ok') AS imp_d7_rescreenshot
FROM truth_vault.v_paid_boost_evidence;
-- 缺的原因分布
SELECT comments_base_status, count(*) FROM truth_vault.v_paid_boost_evidence GROUP BY 1 ORDER BY 2 DESC;
```

| 事件 | 评论基线 ok | D+1 ok | D+3 ok | D+7 ok | 基线 + D+7 成对 | 曝光基线 ok | D+7 重截过 |
|---|---|---|---|---|---|---|---|
| | | | | | | | |

预期（先说给 owner 听）：大多数格子是 missing。来源 B 的投流多数在发布后 0–2 天，那时 TV 还没读过第一晚；🍟 那批（08-27 / 09-15 / 09-16）的评论数 09-17 之前只在 raw_extra 里，有就读出来、标 `comments_source = raw_extra:实时数据.评论数`。这是如实输出，不是 bug。

## 5. HATHERINE 试点逐例表 —— 待填

```sql
SELECT right(note_id, 6) AS rec, boost_date, days_after_publish, comments_base, comments_base_status,
       comments_d7, comments_d7_status, comments_delta_d7, impressions_base, impressions_d7, impressions_d7_status,
       ops_effect_value, ops_effect_vs_current_impressions, takeoff_vs_window, tier_on_boost_day, tier_d7
FROM truth_vault.v_paid_boost_evidence WHERE project_id = 'HATHERINE_phase1' ORDER BY boost_date, note_id;
```

## 6. 五篇手对（视图的每一格对回 audit_log 原行）—— 待填

挑法：BJS 一篇 9/15🍟、ANSHEN 一篇 9/15🍟、SPX 那篇 9/16🍟（关注情况和维护时间同一天）、HATHERINE 一篇 10-13 入库 / 10-14 投 / 10-21 补效果的、XIWU_phase2 一篇配数字效果的。
每篇列：`v_paid_boost_readings` 五行（k = −1 / 0 / 1 / 3 / 7）× 对得上的 audit 行（audit_id、occurred_at、北京日、`->0 / ->1`）。

```sql
SELECT * FROM truth_vault.v_paid_boost_readings WHERE note_id = :'note_id' ORDER BY k;
SELECT audit_id, occurred_at, (occurred_at + interval '8 hours')::date AS cn_day, operation,
       changed_cols ? 'last_seen_run_id' AS full_sync,
       changed_cols -> 'comments_count' AS comments, changed_cols -> 'impressions' AS impressions
FROM truth_vault.audit_log
WHERE schema_name = 'truth_vault' AND table_name = 'notes' AND row_id = :'note_id' ORDER BY occurred_at;
```

已知要核的一点：SPX 那篇 9/16 15:10（北京）读到的「阅读 778 · 互动 73」，在视图里应是 k=0（投流当天、前后不明），不是基线（D-133 第 4 条更正了 D-078 的例子）。

## 7. 反证：整块扫 🍟 扫到的篇，三张视图里一篇都没有 —— 待填

```sql
WITH trap AS (
  SELECT note_id FROM truth_vault.notes
  WHERE raw_extra::text LIKE '%🍟%' OR data_quality_flags::text LIKE '%🍟%'
     OR coalesce(title, '') || coalesce(raw_content, '') LIKE '%🍟%')
SELECT count(*) AS blob_hits,
       count(*) FILTER (WHERE note_id IN (SELECT note_id FROM truth_vault.v_paid_boost_events)
                           OR note_id IN (SELECT note_id FROM truth_vault.v_paid_boost_quarantine)) AS in_views
FROM trap;
```

应是：整块扫中的里面，只有真打了标记的那些（今天 10 篇 🍟）在视图里；§1 列的 RIO / ANSHEN（现版 + 历史版）/ XIWU_phase2 / NUC 一篇都不在。

## 8. 基线对比（不该变的四个数）—— 待填

| | 合并前（10-__） | 第一晚后（10-__） |
|---|---|---|
| 书架已策展卡数 | | |
| 全库 tier 分布 | | |
| `paid_promoted` 真 / 假 / 缺（分项目） | | |
| 闸二敏感性剔除篇数（投流一项） | | |

另记：verify #99（true 却没有去处）= __，#100（认不出 / 标记被删）= __ / __。

## 9. 性能 —— 待填

```sql
EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM truth_vault.v_paid_boost_evidence;
```

超过 5 秒就按 D-133 第 7 条改物化视图（daily-sync 里刷新）。本地 PG16 上五个视图各 10–20 毫秒（CI 夹具大小；两个拆元素函数标了 `ROWS 3`，没标之前本地 JIT 让一次读要 2–4 秒；生产 10-29 查过 `jit = off`）。
