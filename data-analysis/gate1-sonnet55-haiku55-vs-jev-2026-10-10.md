# 闸一 · Sonnet 5.5 / Haiku 5.5 两趟影子跑 vs Jev 三张表 + owner 裁决（100 篇样本，2026-10-10）

> 口径同 `scripts/gate1_agreement.py` 顶部：Jev 合并 = 一篇有两张表答了取一致的（不一致记争议、不计），只有一张表答的直接用；一致率 = 两边都有答案的格子里答案相同的比例；κ = Cohen's κ，**任一边取值只有一种时记「不可算」**；TV 校验没过的格（invalid_reason 非空）不算不一致、单独数；owner 列只数两边都答了的裁决格。通过线：一致率 ≥ 0.85 且 κ ≥ 0.60（docs/28 §6.1）。**模型 vs 模型**——两个模型在题面歧义处一起错的看不出来（D-081）。
> 这次 1,000 行 pivot 走 Supabase MCP 太大，没有经过脚本的 `--from-json`，而是在 SQL 里按同一口径算（查询见文末；三位小数）。
> TV 快照：run_tag `gate1-sonnet55` = `llm:claude-sonnet-5-5@ba0f570c`（run 37901944400，10-09 07:56–08:38 UTC）、`gate1-haiku55` = `llm:claude-haiku-5-5@ba0f570c`（run 37901990997，07:57–09:16 UTC），各 100 篇全答。question_version：v2 = 第一句类型 / 交代身份 / 产品角色 / 前后转折，v3 = 拿别人对照，其余 v1。Jev：run_tag `gate1-20260928`，`jev:1.13.0-A/B/C@3d299a1e`（v1 题面，50 篇，每表 999–1,000 行）。owner：`human:owner`，同 run_tag，95 格（67 篇，D-082）。「Opus 4.6」一列抄自 `gate1-jev-vs-tv-v2-2026-09-23.md`（`llm:claude-opus-4-6@3519081c`）作对照。

## 逐题（Jev 合并 vs TV）

| # | 题 | 版本 | Sonnet 5.5<br>n · 一致 · κ | Haiku 5.5<br>n · 一致 · κ | Opus 4.6 (09-23)<br>一致 · κ · 判 | owner 裁过的格<br>TV 对 · Jev 对 · n（Sonnet / Haiku） | TV 没答<br>S / H（Jev 争议） | `gate1_status` |
|---|---|---|---|---|---|---|---|---|
| 1 | 标题是问句 | v1 | 99 · 1.000 · 1.000 | 99 · 0.980 · 0.953 | 0.98 · 0.95 过 | — | 0 / 0 | pass |
| 2 | 第一句类型 | v2 | 98 · 0.684 · 0.522 | 98 · 0.745 · 0.593 | 0.83 · 0.72 不过 | 16 · 5 · 19 / 18 · 5 · 19 | 1 / 1（1） | **fail** |
| 3 | 具体时间 | v1 | 99 · 0.838 · 0.644 | 99 · 0.808 · 0.588 | 0.94 · 0.86 过 | — | 1 / 1 | **fail** |
| 4 | 具体地点或场合 | v1 | 97 · 0.814 · 0.641 | 97 · 0.784 · 0.583 | 0.92 · 0.83 过 | — | 1 / 1（2） | **fail** |
| 5 | 别人说的原话 | v1 | 99 · 0.970 · 0.936 | 99 · 0.949 · 0.890 | 0.97 · 0.93 过 | — | 1 / 1 | pass |
| 6 | 具体身体感受 | v1 | 99 · 0.828 · 0.590 | 99 · 0.899 · 0.761 | 0.91 · 0.79 过 | — | 1 / 1 | **fail** |
| 7 | 结尾问读者 | v1 | 98 · 0.969 · 0.939 | 98 · 0.969 · 0.939 | 0.97 · 0.94 过 | — | 2 / 2 | pass |
| 8 | 请读者讲经历 | v1 | 100 · 0.930 · 0.496 | 100 · 0.940 · 0.592 | 0.93 · 0.50 不过 | — | 0 / 0 | **fail** |
| 9 | 整篇在求助 | v1 | 99 · 0.889 · 0.780 | 97 · 0.887 · 0.776 | 0.89 · 0.78 过 | — | 1 / 3 | pass |
| 10 | 故意不说名字 | v1 | 99 · 0.980 · −0.010 ¹ | 98 · 0.990 · 不可算 | 0.99 · 不可算 | — | 1 / 2 | kappa_undefined |
| 11 | 会有人反对的判断 | v1 | 100 · 0.840 · 0.403 | 100 · 0.830 · 0.385 | 0.96 · 0.58 不过 | — | 0 / 0 | **fail** |
| 12 | 产品角色 | v2 | 98 · 0.663 · 0.416 | 98 · 0.673 · 0.435 | 0.75 · 0.57 不过 | 15 · 3 · 20 / 15 · 3 · 20 | 0 / 0（2） | **fail** |
| 13 | 效果承诺 | v1 | 100 · 0.960 · 不可算 | 100 · 0.970 · 不可算 | 0.99 · 不可算 | — | 0 / 0 | kappa_undefined |
| 14 | 交代身份 | v2 | 100 · 0.680 · 0.342 | 100 · 0.700 · 0.384 | 0.81 · 0.62 不过 | 16 · 12 · 16 / 16 · 12 · 16 | 0 / 0 | pass（owner 锚）² |
| 15 | 亲身经历 | v1 | 97 · 0.969 · 0.885 | 99 · 0.960 · 0.858 | 0.87 · 0.61 过 | — | 3 / 1 | pass |
| 16 | 拿别人对照 | v3 | 99 · 0.899 · 0.502 | 99 · 0.899 · 0.502 | 0.91 · 0.56 不过 | 10 · 1 · 10 / 9 · 1 · 10 | 1 / 1 | pass（owner 锚）² |
| 17 | 点名某类读者 | v1 | 100 · 0.920 · 0.669 | 100 · 0.930 · 0.733 | 0.90 · 0.64 过 | — | 0 / 0 | pass |
| 18 | 前后转折 | v2 | 97 · 0.557 · 0.219 | 98 · 0.541 · 0.198 | 0.60 · 0.27 不过 | 27 · 3 · 29 / 26 · 3 · 29 | 2 / 1（1） | pass（owner 锚）² |
| 19 | 被人评价 | v1 | 95 · 0.947 · 0.875 | 98 · 0.939 · 0.859 | 0.86 · 0.60 过 | — | 5 / 2 | pass |
| 20 | 已发生的坏结果 | v1 | 98 · 0.765 · 0.537 | 98 · 0.765 · 0.537 | 0.84 · 0.68 不过 | — | 1 / 1（1） | **fail** |

¹ Jev 99 格里只有 1 个「是」：κ 数值上算得出来（−0.010），但由一格决定，不是测量，按「近乎常数」记 `kappa_undefined`（Haiku 那趟同一格 TV 校验没过，Jev 侧恰好全「否」，直接不可算）。
² 对 Jev 不过线，但 docs/28 §6.1 的线写的是「与**人工**一致率」，Jev 只是 D-081 的替身。owner 09-23 裁过的格子（都是当时 Opus 与 Jev 的分歧格，是最难的那批）里 Sonnet 对 10/10、16/16、27/29，Jev 对 1/10、12/16、3/29——分歧来自 Jev 还在答 v1 题面（D-082 正因这些格把题面升到 v2 / v3）。在有人裁过的格子上 TV ≥ 0.90，判过。第一句类型（16/19 = 0.84）和产品角色（15/20 = 0.75）没到 0.85，仍是 fail。

直接过线：Sonnet 7 题（1 / 5 / 7 / 9 / 15 / 17 / 19），Haiku 8 题（多一道具体身体感受）。按 Sonnet 填 `gate1_status`：**pass 10 / fail 8 / kappa_undefined 2**（Opus 4.6 09-23 是过 10 / 不过 8 / 不可算 2，但组成不同：Opus 过了具体时间 / 地点 / 身体感受，没过交代身份 / 拿别人对照 / 前后转折——后三道这次靠 owner 锚）。

## owner 裁过的格子（两边都答了的）

| | 格数 | TV 对 | Jev 对 |
|---|---|---|---|
| Sonnet 5.5（10-09） | 94 | 84（89%） | 24（26%） |
| Haiku 5.5（10-09） | 94 | 84（89%） | 24（26%） |
| Opus 4.6（09-23，D-082 原始裁决） | 95 | 66（69%） | 24（25%）；都不对 5 |

这 95 格是按 Opus 与 Jev 的分歧选出来的，对 Opus 偏不利、对 Sonnet / Haiku 中性；两个新模型在同一批难格上比 Opus 多对 18 格，主要来自五道升版题——题面改了，模型按新题面答，owner 当时裁的就是新题面的意思。

## Sonnet 5.5 vs Haiku 5.5 互看（同 100 篇，两边都答了的格）

| # | 题 | n | 一致 | κ | Sonnet 答案分布 |
|---|---|---|---|---|---|
| 1 | 标题是问句 | 99 | 0.980 | 0.953 | 否 0.68 · 是 0.32 |
| 2 | 第一句类型 | 99 | 0.848 | 0.783 | 具体事件 0.45 · 身份自述 0.24 · 观点断言 0.14 · 感叹情绪 0.08 · 提问 0.04 · 数据事实 0.03 · 其他 0.01 |
| 3 | 具体时间 | 99 | 0.869 | 0.726 | 是 0.62 · 否 0.38 |
| 4 | 具体地点或场合 | 99 | 0.929 | 0.854 | 否 0.59 · 是 0.41 |
| 5 | 别人说的原话 | 99 | 0.960 | 0.913 | 否 0.62 · 是 0.38 |
| 6 | 具体身体感受 | 99 | 0.889 | 0.729 | 否 0.72 · 是 0.28 |
| 7 | 结尾问读者 | 98 | 1.000 | 1.000 | 是 0.52 · 否 0.48 |
| 8 | 请读者讲经历 | 100 | 0.930 | 0.496 | 否 0.93 · 是 0.07 |
| 9 | 整篇在求助 | 97 | 0.918 | 0.834 | 否 0.54 · 是 0.46 |
| 10 | 故意不说名字 | 98 | 1.000 | 1.000 | 否 0.99 · 是 0.01 |
| 11 | 会有人反对的判断 | 100 | 0.830 | 0.527 | 否 0.77 · 是 0.23 |
| 12 | 产品角色 | 100 | 0.920 | 0.821 | 未出现 0.73 · 顺带一提 0.10 · 主角 0.08 · 解决方案 0.08 · 只暗示 0.01 |
| 13 | 效果承诺 | 100 | 0.970 | 0.556 | 否 0.96 · 是 0.04 |
| 14 | 交代身份 | 100 | 0.900 | 0.646 | 是 0.84 · 否 0.16 |
| 15 | 亲身经历 | 97 | 0.969 | 0.878 | 是 0.86 · 否 0.14 |
| 16 | 拿别人对照 | 99 | 0.980 | 0.823 | 否 0.94 · 是 0.06 |
| 17 | 点名某类读者 | 100 | 0.970 | 0.872 | 否 0.88 · 是 0.12 |
| 18 | 前后转折 | 98 | 0.949 | 0.798 | 否 0.85 · 是 0.15 |
| 19 | 被人评价 | 95 | 0.968 | 0.922 | 否 0.72 · 是 0.28 |
| 20 | 已发生的坏结果 | 99 | 0.859 | 0.716 | 否 0.53 · 是 0.47 |

中位数：一致 0.93、κ 0.80。两个模型彼此的一致远高于各自与 Jev 的一致——对 Jev 不过的那几道里，分歧多半在 Jev 这一侧（v1 题面）或题面本身，不在 Sonnet / Haiku 之间。

## 结论（记在 D-105）

- 抽取器留 Sonnet 5.5：Haiku 没有比它更过线，只是不更差；两边 owner 格都对 84/94。
- `gate1_status` 按上表最后一列填；题库 `status: frozen`，`frozen_sha256 = ba0f570c47d594ca4dad571c5a9f5d06da51861b041ba364c3a915220b985ddd`（digest 不变）。
- 没救回来的三道（具体时间 / 地点 / 身体感受）：Opus 对 Jev 过、Sonnet / Haiku 不过，谁对没人看过。最便宜的路是 owner 再裁这三题上 Sonnet 与 Jev 的分歧格（每题 16–19 格），`build_gate1_human_sheets.py` 能出表。

## 口径一致性

- 直接过线那 7 道两趟影子都 ≥ 0.85 / ≥ 0.60；Opus 09-23 同样过。
- D-082 五道升版题对 Jev（v1 题面）的一致率天然偏低，和 09-23 v2 报告的方向一致（那次 TV 自己两次跑在这五题上 0.74–0.99）。
- 占位题（placebo）不在模型题里，不进本表。

## SQL（Supabase MCP 跑，10-10 03:3x UTC）

逐题 Jev 合并 vs TV + owner 列：

```sql
with jev as (
  select subject_id, question_id,
    max(answer) filter (where extractor='jev:1.13.0-A') a,
    max(answer) filter (where extractor='jev:1.13.0-B') b,
    max(answer) filter (where extractor='jev:1.13.0-C') c
  from truth_vault.note_feature_answers
  where run_tag='gate1-20260928' and subject_type='note' and extractor in ('jev:1.13.0-A','jev:1.13.0-B','jev:1.13.0-C') and bank_sha256 like '3d299a1e%'
  group by 1,2),
jm as (
  select subject_id, question_id, a, b, c,
    case when (select count(distinct x) from unnest(array[a,b,c]) x where x is not null) = 1 then coalesce(a,b,c) end as merged,
    ((select count(distinct x) from unnest(array[a,b,c]) x where x is not null) > 1) as disputed
  from jev),
own as (select subject_id, question_id, max(answer) owner from truth_vault.note_feature_answers
        where run_tag='gate1-20260928' and subject_type='note' and extractor='human:owner' group by 1,2),
tv as (
  select run_tag, subject_id, question_id, question_version, (invalid_reason is not null) as invalid,
         case when invalid_reason is null then answer end as tv
  from truth_vault.note_feature_answers
  where run_tag in ('gate1-sonnet55','gate1-haiku55') and subject_type='note' and extractor like 'llm:%' and bank_sha256 like 'ba0f570c%'),
cells as (
  select t.run_tag, t.question_id, t.subject_id, t.question_version, t.tv, t.invalid, j.merged, j.disputed, o.owner
  from tv t join jm j using (subject_id, question_id) left join own o using (subject_id, question_id)),
pairs as (select * from cells where tv is not null and merged is not null),
ptv as (select run_tag, question_id, tv as cat, count(*)::float / sum(count(*)) over (partition by run_tag, question_id) p from pairs group by 1,2,3),
pjv as (select run_tag, question_id, merged as cat, count(*)::float / sum(count(*)) over (partition by run_tag, question_id) p from pairs group by 1,2,3),
pe as (select run_tag, question_id, sum(ptv.p * pjv.p) pe from ptv join pjv using (run_tag, question_id, cat) group by 1,2),
st as (
  select run_tag, question_id, max(question_version) qv, count(*) n, avg((tv = merged)::int) po,
         count(distinct tv) tv_k, count(distinct merged) jev_k
  from pairs group by 1,2),
ow as (
  select run_tag, question_id,
    count(*) filter (where owner is not null and tv is not null and merged is not null) n_own,
    count(*) filter (where owner is not null and tv is not null and merged is not null and tv = owner) tv_ok,
    count(*) filter (where owner is not null and tv is not null and merged is not null and merged = owner) jev_ok,
    count(*) filter (where owner is not null and (tv is null or merged is null)) own_unanswered,
    count(*) filter (where invalid) invalid_n, count(*) filter (where disputed) disputed_n, count(*) cells_n
  from cells group by 1,2)
select s.run_tag, s.question_id, s.qv, s.n, round(s.po::numeric, 3) agree,
       case when s.tv_k < 2 or s.jev_k < 2 then null else round(((s.po - pe.pe) / nullif(1 - pe.pe, 0))::numeric, 3) end kappa,
       s.tv_k, s.jev_k, ow.n_own, ow.tv_ok, ow.jev_ok, ow.own_unanswered, ow.invalid_n, ow.disputed_n, ow.cells_n
from st s join pe using (run_tag, question_id) join ow using (run_tag, question_id)
order by s.question_id, s.run_tag;
```

Sonnet vs Haiku 互看：同上的 `tv` 子查询，按 (subject_id, question_id) 自连接两个 run_tag，一致率 / κ 同样算法。
