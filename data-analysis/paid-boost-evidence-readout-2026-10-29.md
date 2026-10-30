# 投流证据链读数（F1 / F2）· 2026-10-29 骨架 · 10-30 填

> **10-30 填。** owner 10-30 在 SQL editor 跑了 `schemas/notes_v1_22_paid_boost_evidence.sql`；§2–§7、§9 是跑完之后（北京 10-30 上午、当天 daily-sync 之前）读生产视图的数。
> §1 是 10-29 跑之前的只读重测，留着做对照。§8 的「第一晚后」一列等 10-30 的 daily-sync（sync 第一次用元素精确判据）跑完再填。
> 口径和取舍见 DECISIONS D-133；要问运营的口径见 OPEN-ITEMS O-06。
> 全文只放计数、标记取值和日期，不放帖子正文、评论原文、账号昵称；要指到具体某篇，用 `项目 …note_id 末 6 位`（同 D-131 的写法）。

**措辞约定（填的时候照用）**：这是逐例证据，不做因果结论；「维护效果」是运营自报，口径没定（`ops_effect_metric_flag = unknown`）；
缺的格子写 `missing:<原因>`，不是 0；曝光总数里本来就含投流量；评论增量里混着铺评，看 `comment_maintained_seeded`。

---

## 0. 填之前要做完的事

1. ✅ 合并前（只读）记一份基线 → §8「合并前」列（10-29）。
2. ✅ owner 10-30 跑了 v1_22。verify #98 = **0**（5 个视图 + 6 个函数都在），#99 = **0**，#100 = **0 / 0**。
3. ⏳ 等 10-30 daily-sync 跑完填 §8「第一晚后」列。

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

## 2. 投流事件（按项目 × 日期来源）

```sql
SELECT project_id, array_to_string(date_sources, '+') AS src, count(*) AS events,
       count(*) FILTER (WHERE vanished) AS vanished,
       count(*) FILTER (WHERE takeoff_vs_window = 'in_window') AS takeoff_in_window
FROM truth_vault.v_paid_boost_events GROUP BY 1, 2 ORDER BY 1, 2;
```

| 项目 | 日期来源 | 事件 | 其中飞书已删 | 起量时间落在 [D, D+7] | 投流日范围 | 发布后 0–2 天投的 |
|---|---|---|---|---|---|---|
| ANSHEN_phase1 | 🍟前日期 | 2 | 0 | 2 | 09-15 | 0 |
| BJS_phase1 | 🍟前日期 | 7 | 0 | 4 | 08-27 – 09-15 | 0 |
| HATHERINE_phase1 | 维护时间 | 23 | 0 | 7 | 09-23 – 10-23 | 18 |
| SPX_phase1 | 🍟前日期 | 1 | 0 | 1 | 09-16 | 1 |
| SPX_phase1 | 维护时间 | 6 | 0 | 3 | 10-09 – 10-14 | 6 |
| XIWU_phase2 | 维护时间 | 3 | 0 | 1 | 10-26 – 10-27 | 3 |
| **合计** | | **42**（38 篇） | 0 | 18 | | 28 |

- 和本地预演一样：🍟 10 次 + 维护时间配数字效果 32 次。38 篇里 HATHERINE 有 3 篇各投了两三次（同一篇不同日期是不同事件）。
- 42 次里 28 次是发布后 0–2 天投的（来源 B 32 次里 27 次）—— 这些投流之前 TV 最多只读过一晚，基线大多是空的（§4）。

## 3. 隔离（按原因，带原值）

```sql
SELECT project_id, source_col, reason, raw_elem, count(*)
FROM truth_vault.v_paid_boost_quarantine GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3, 4;
```

| 项目 | 列 | 原因 | 原值 | 篇数 |
|---|---|---|---|---|
| HATHERINE_phase1 | 维护时间 | before_publish | 10月22日 | 1 |
| HATHERINE_phase1 | 维护时间 | time_effect_count_mismatch | 10月13日 | 1 |
| SPX_phase1 | 维护情况 | no_date | 已投流，等回收数据 | 1 |
| TUGE_phase1 | _tier_source_raw | no_date | 关注后续流量 | 9 |
| **合计** | | | | **12** |

认不出的标记元素（`marker_like_unrecognized`）0 个。12 篇都等运营补日期 / 对齐个数（O-06）；补了下一次读就自己挪进 §2。

## 4. 覆盖：每个事件有没有读数

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
| 42 | 21 | 41 | 31 | 35 | 19 | 11 | 25 |

缺的原因：

- 评论基线：`missing:value_null` 15（投流前那一晚评论数还是空的，多是刚入库的帖）、`missing:before_history` 6（投流日前 TV 一次都没读过这篇）。
- 评论 D+7：`not_due` 5（10-23 之后投的，D+7 还没到）、`no_full_sync_that_day` 1、`value_null` 1。
- 曝光 D+7：`no_rescreenshot` 8（投流后运营没重截图，曝光数没变）、`not_due` 5、`value_null` 3、`no_full_sync_that_day` 1。
- D+3 少的 11 次里，9-15 那批（ANSHEN / BJS）的 D+3 落在 09-18，那天只有一次非全量同步，按口径不借邻日。

和事先说的一样：大多数投流发生在发布后 0–2 天，所以「投之前」的格子一半是空的；能成对比较评论（基线 + D+7 都有）的只有 19 次，曝光能成对的更少（基线 11 次）。这是如实输出，不是 bug。

## 5. HATHERINE 试点逐例表

```sql
SELECT right(note_id, 6) AS rec, boost_date, days_after_publish, comments_base, comments_base_status,
       comments_d7, comments_d7_status, comments_delta_d7, impressions_base, impressions_d7, impressions_d7_status,
       ops_effect_value, ops_effect_vs_current_impressions, takeoff_vs_window, tier_on_boost_day, tier_d7
FROM truth_vault.v_paid_boost_evidence WHERE project_id = 'HATHERINE_phase1' ORDER BY boost_date, note_id;
```

「—」= 视图给的是 missing（原因见 §4），不是 0。「运营效果」是运营自报的维护效果数，口径没定（曝光？阅读？），所有 23 次都不超过这篇现在的曝光数（`ops_effect_vs_current_impressions = ok`）。

| 篇 | 投流日 | 发布后天数 | 评论 基线 → D+7（差） | 曝光 基线 / D+7 | 运营效果 | 起量 | tier 投流日 → D+7 |
|---|---|---|---|---|---|---|---|
| …Gh4wi7 | 09-23 | 2 | 12 → 30（+18） | — / 11,753 | 3,636 | after | 风控 → 爆 |
| …vM7NWI | 09-23 | 1 | — → 100 | — / 1,713 | 1,216 | in_window | 未知 → 大爆 |
| …bZ2WF3 | 09-23 | 1 | — → 1 | — / 1,826 | 1,598 | — | 未知 → 趴 |
| …hU4bwj | 09-23 | 1 | — → 106 | — / 5,918 | 4,155 | in_window | 未知 → 大爆 |
| …lTTJMM | 09-24 | 0 | —（before_history）→ 95 | — / 192,067 | 6,357 | in_window | 未知 → 爆 |
| …lTTJMM | 09-28 | 4 | 39 → 100（+61） | — / 192,067 | 5,968 | in_window | 评估中 → 大爆 |
| …US9NmV | 09-29 | 0 | — → 6 | — / — | 3,606 | — | 未知 → 趴 |
| …US5LS3 | 09-30 | 1 | 13 → 118（+105） | — / — | 4,010 | in_window | 评估中 → 大爆 |
| …VAp79v | 09-30 | 0 | — → 6 | — / — | 4,736 | — | 未知 → 趴 |
| …PnNUvk | 10-10 | 1 | 4 → 11（+7） | — / 11,869 | 4,628 | — | 未知 → 趴 |
| …USuKGZ | 10-14 | 0 | — → 11 | — / 3,703 | 2,503 | — | 未知 → 趴 |
| …UScKSp | 10-15 | 1 | 0 → 42（+42） | — / 5,870 | 4,174 | — | 未知 → 评估中 |
| …hU4bwj | 10-19 | 27 | 106 → 106（0） | 10,608 / 14,333 | 1,592 | before | 大爆 → 风控 |
| …lT09d3 | 10-19 | 21 | 24 → 23（−1） | — / 82,173 | 3,674 | — | 评估中 → 趴 |
| …PnNUvk | 10-19 | 10 | 11 → 12（+1） | 11,869 / 16,739 | 4,058 | — | 趴 → 趴 |
| …6s7bsh | 10-20 | 0 | —（before_history）→ 11 | — / 8,010 | 3,585 | — | — → 趴 |
| …DQZ0VP | 10-20 | 0 | —（before_history）→ 11 | — / 2,480 | 1,336 | — | — → 趴 |
| …hYssY5 | 10-22 | 0 | — → 10 | — / 4,467 | 2,356 | — | 未知 → 趴 |
| …hYus0J | 10-22 | 0 | — → 20 | — / 15,054 | 3,370 | — | — → 趴 |
| …o99G76 | 10-22 | 0 | —（before_history）→ 26 | — / 17,306 | 2,587 | in_window | — → 风控 |
| …1aHdKc | 10-22 | 0 | —（before_history）→ 30 | — / 53,996 | 2,754 | — | — → 趴 |
| …PnNUvk | 10-23 | 14 | 11 → —（not_due） | 16,739 / —（not_due） | 3,242 | — | 趴 → — |
| …EdtjL2 | 10-23 | 0 | — → —（not_due） | — / —（not_due） | 2,949 | in_window | — → — |

读法（逐例，不下因果）：曝光基线 23 次里只有 3 次有（都是发布 10 天以后再投的那几次）；发布当天 / 次日投的，曝光基线一律空，D+7 的曝光里本来就含投流量。评论差能算的 8 次里，铺评占多少要看 `comment_maintained_seeded`，这里没拆。

## 6. 五篇手对（视图的每一格对回 audit_log 原行）

挑法照骨架：BJS 一篇 9/15🍟、ANSHEN 一篇 9/15🍟、SPX 那篇 9/16🍟、HATHERINE 一篇 10-13 入库 / 10-14 投、XIWU_phase2 一篇配数字效果的。
每篇把 `v_paid_boost_readings` 的五行（k = −1 / 0 / 1 / 3 / 7）对到 audit_log（`changed_cols ? 'last_seen_run_id'` = 全量同步；`->1` = 改后的值；北京日 = `occurred_at + 8h`）。

| 篇 | 槽 | 视图取的 audit 行 | 视图的值 | audit 里对上的 | 结论 |
|---|---|---|---|---|---|
| BJS …SIYw6w（09-15） | −1 | 174324（09-14 07:30 UTC，全量） | 评论 0、曝光 252、阅读 11、互动 1 | 评论 = 同行 raw `实时数据.评论数` 0；曝光 / 阅读 = 167083（09-12）；互动 09-10 | ✓ |
| | 0 | 177907（09-15 全量） | 评论 0；曝光 / 阅读 / 互动 `no_rescreenshot` | 09-12 之后三列没改过、截图没换 | ✓ |
| | 1 | 181424（09-16 07:08 全量；同日 184722 非全量不取） | 评论 50 | 181424 raw 评论数 50 | ✓ |
| | 3 | —（09-18 只有 188871，非全量） | `no_full_sync_that_day` | 不向 09-17 / 09-19 借 | ✓ |
| | 7 | 201120（09-22 全量） | 评论 49（comments_count） | 193426（09-20）改成 49 | ✓ |
| ANSHEN …XJ1ThE（09-15） | −1 | 174122（09-14 全量） | 评论 21、曝光 1,799、阅读 592、互动 value_null | raw 评论数 21；曝光 / 阅读 = 166881（09-12） | ✓ |
| | 0 / 1 | 177705 / 181222 | 评论 21 / 22 | raw 评论数 21 / 22 | ✓ |
| | 3 | —（09-18 这篇没有 audit 行） | `no_full_sync_that_day` | 09-17、09-19 各一行 | ✓ |
| | 7 | 200918（09-22） | 评论 46 | 197113（09-21）comments_count → 46 | ✓ |
| SPX …UbfbVY（09-16） | −1 | 179934（09-15 INSERT，全量） | 全部 `value_null` | 入库那行几列都是空 | ✓ |
| | 0 | 183453（09-16 07:10 UTC = 北京 15:10） | 阅读 778、互动 73、评论 68 | 同行 ->1 = 778 / 73，raw 评论数 68 | ✓ **在 k=0（投流当天、前后不明），不是基线**（D-133 第 4 条更正 D-078 的例子） |
| | 1 | 187091（09-17） | 评论 163 | raw 评论数 163 | ✓ |
| | 3 | 191726（09-19） | 评论 165、曝光 12,081、阅读 3,796、互动 216 | 同行 ->1 全对 | ✓ |
| | 7 | 207167（09-23） | 评论 164 | 203364（09-22）→ 164 | ✓ |
| HATHERINE …USuKGZ（10-14） | −1 | 283014（10-13 INSERT，全量；同日 286253 非全量不取） | 全部 `value_null` | 入库那行几列都是空 | ✓ |
| | 0 / 1 | 286950 / 291452 | 评论 4 / 8，互动 0 | 同行 ->1 = 4、0 / 8 | ✓ |
| | 3 | 299751（10-17） | 评论 11、曝光 3,665、阅读 1,047、互动 12 | 299029（10-16 第二次全量）评论 11；295496（10-16）曝光 / 阅读 / 互动 | ✓ |
| | 7 | 317321（10-21 07:38 全量） | 曝光 3,703、阅读 1,053、评论 11 | 307851（10-19）；10-20 16:28 UTC 那行是北京 10-21 但非全量，不取 | ✓ |
| XIWU_phase2 …i1kVkh（10-27） | −1 / 0 / 1 | 342326 / 346823 / 351281 | 评论 0 / 11 / 35；D+1 曝光 161、阅读 27、互动 2 | 同行 ->1 全对 | ✓ |
| | 3 / 7 | — | `not_due` | 读的时候北京 10-30 上午，当天夜跑还没跑 | ✓ |

五篇 25 个槽、每个有值的格子都对得上 audit_log 原行，0 处不一致。

## 7. 反证：整块扫 🍟 扫到的篇，三张视图里一篇都没有

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

整块扫中 14 篇，在视图里的 10 篇 = 真打了 🍟 标记的 10 篇；不在视图里的 4 篇正是 §1 列的 ANSHEN、NUC、RIO、XIWU_phase2 各 1 篇。✓（只在 audit_log 历史 raw_extra 里有 🍟 的那篇 ANSHEN 不在现版 raw_extra 里，本来就扫不到。）

## 8. 基线对比（不该变的四个数）

| | 合并前（10-29） | apply 后、夜跑前（10-30 03:00 UTC） | 第一晚后（10-30 daily-sync） |
|---|---|---|---|
| 书架已策展卡数 | 313 | 313 | ⏳ |
| 全库 tier 分布 | 趴 5,169 · 空 615 · 风控 310 · 爆 304 · 评估中 125 · 大爆 114 · 预备 108 · 未知 61 · 参考 2 · 数据异常 1 | 同左（共 6,809） | ⏳ |
| `paid_promoted` 真 / 假 / 缺（分项目） | ANSHEN 2/199/0 · BJS_phase1 7/175/0 · BJS_phase2 0/95/0 · HATHERINE 0/327/0 · SPX 2/641/0 · TUGE 9/178/0 · XIWU_phase2 0/184/2 | 真的分项目全同；假的 SPX 642、TUGE 179、XIWU_phase2 204（10-29 入库的新帖） | ⏳ |
| 闸二敏感性剔除篇数（投流一项） | `paid_promoted = true` 的 20 篇 | 同（20 篇） | ⏳ |

verify #99（true 却没有去处）= **0**，#100（认不出 / 标记被删）= **0 / 0**。

## 9. 性能

```sql
EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM truth_vault.v_paid_boost_evidence;
```

生产 10-30：执行 **456 毫秒**、规划 9 毫秒，全在缓存里（shared hit 73,669 页）。大头是拆元素那一步（约 375 毫秒，其中 `_tier_source_raw` 逐篇过 6,809 篇约 226 毫秒）。远低于 5 秒，按 D-133 第 7 条继续用视图，不改物化视图。
