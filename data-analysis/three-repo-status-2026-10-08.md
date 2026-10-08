# 三仓联动状态复核（truth-vault · JevforCoentent · autowriter）· 2026-10-08

> **怎么来的**：三个仓库拉到当天 main（TV `0e54559` · Jev `39fe5a2` · aw `1cb9046`），读完各自的入口文档与最近一轮决策（TV D-075 ~ D-085、Jev docs/00-02、aw runbook），
> 再对着 **生产库**（Supabase `kduysqedr`，`truth_vault` / `autowriter` / `public` 三个 schema）、**GitHub Actions 运行记录**、**三个 Railway 服务的 `/health`** 逐项核。
> 下面每个数都是 10-08 当天查出来的，不是照文档抄的。sanshengliubu（三省六部）仓不在本次范围，只能从 TV 写进 `public.reference_samples` 的那一侧看它。
>
> **一句话**：主干飞轮在转（采集 → 书架 → 写作台借卡 → 发布 → 回程对照，每一段都有生产流量），但 **9 月下旬新接的 Jev 这一圈只合上了一条边**（外部语料今天刚通），
> 入库判定和主抽取两条都还没通电；通道 1 里躺着一批 **8 月 18 日飞书误标后推进去、第二天改回却没撤回来的 284 条处方药"爆款参照"**，这是本次查到最该先处理的事。

---

## 0. 一页读完

**飞轮转没转（按环节）**

| 环节 | 转没转 | 证据（生产库 / 运行记录） |
|---|---|---|
| 采集：飞书 → TV | ✅ 在转 | 6,300 篇；近 30 天入库 665 篇；daily-sync 连续 14+ 晚全绿（#180–#194）；看门狗 18 次全绿 |
| essence 标注 | ✅ 跑满 | 6,300 / 6,300 |
| 策展 → 书架 | ✅ 在转 | 455 张标注 → 306 张可借经验卡 |
| 通道 2：写作台借卡 | ✅ 有真流量，⚠️ 三成冷借超时 | 9 月 31 条 brief，其中 **PR #85（open_project 自动借）合并后那周 25 条**；冷路径 p50 49 s · p95 79 s，**24 次里 7 次超过写作台 60 s 超时** |
| 写作台产出 | ✅ 9 月有量，⚠️ 10 月第一周归零 | 真写的版本：9/7 周 466 · 9/14 周 74 · 9/21 周 176 · 9/28 周 16 · **10/5 周 0**（国庆假期，另见 §1.4） |
| 回程：tv-sync 对照 | ✅ 每天在跑 | 416 篇笔记认回写作台版本；1,593 篇补录副本；最新一次 10-08 04:00 UTC |
| 通道 1：TV → 三省六部 | ✅ 在推，🔴 **有污染** | 591 条样本；其中 **285 条**对应的笔记现在是 趴 / 风控（OKMAN 284 条，处方药，见 §3 P0） |
| 内容特征层（闸二前置） | 🟡 在跑，离闸二还远 | 2,064 / 6,300（33%）；**七个 on_demand 项目一篇都没抽，而它们占了 411 篇爆款里的 217 篇（53%）** |
| Jev · 闸一 | ✅ 完成 | D-081/D-082：Jev 三张表 + owner 95 格裁决已落账本 |
| Jev · 外部语料 ⑧ | ✅ **今天刚通** | 200 篇外部笔记（5 品类 × 40），正文全文（中位 284–567 字），4,800 行答案；之前两次定时跑（9/28、10/5）都红 |
| Jev · 写作台入库判定 ⑤ | ⛔ 没通电 | aw 生产 `/health` 报 `judge.configured: false`；账本里 `aw_version` 0 行；judge HTTP 服务本身在三仓找不到部署地址 |
| Jev · 替换 TV 主抽取 ① | ⛔ 没切 | worker `feature_model` 仍是 `claude-opus-4-6`；primary 行全部 `llm:claude-opus-4-6` |
| 人工审稿 → TV | ✅ 意外地活了 | `review_drafts` 近 30 天被调了 **32 次**（D-072 定 legacy-only 时是 0 次）；`prepublish_evaluations` 598 → 630 |

**三个仓库的工程健康**：三仓 main 的 CI 全绿；没有任何 open PR；Jev 69 个测试本地全过；aw 生产部署的 commit 与 main 一致、skill 的 `protocol_version` 与服务端一致。

---

## 1. 逐段细看

### 1.1 采集侧（TV）

| 项目 | 笔记 | 爆/大爆 | 末贴 | 近 30 天新增 | 认回写作台 | 已抽特征 | cron |
|---|---|---|---|---|---|---|---|
| RIO_phase1 | 802 | 23 | 07-12 | 0 | 0 | 204 | daily |
| WTG_phase1 | 724 | 0 | 06-01 | 0 | 0 | 204 | daily |
| NUC_phase1 | 657 | 85 | 2025-12 | 0 | 0 | 20 | on_demand |
| NRT_phase3 | 598 | 44 | 2025-12 | 0 | 0 | 20 | on_demand |
| SPX_phase1 | 525 | 32 | 10-11 ⚠️ | 178 | 55 | 224 | daily |
| NRT_phase2 | 499 | 42 | 2025-10 | 0 | 0 | 20 | on_demand |
| LNKT_phase1 | 374 | 1 | 09-04 | 0 | 18 | 202 | daily |
| OKMAN_phase1 | 346 | 37 | 08-16 | 0 | 0 | 224 | daily |
| XIWU_phase1 | 301 | 9 | 08-29 | 0 | 0 | 204 | daily |
| HATHERINE_phase1 | 271 | 5 | 10-09 ⚠️ | 271 | 120 | 204 | daily |
| HXZ_QD | 202 | 4 | 2025-11 | 0 | 0 | 0 | on_demand |
| ANSHEN_phase1 | 201 | 5 | 09-27 | 46 | 2 | 201 | daily |
| BJS_phase1 | 192 | 12 | 10-07 | 79 | 150 | 192 | daily |
| HXZ_FB | 192 | 14 | 2025-11 | 0 | 0 | 0 | on_demand |
| TUGE_phase1 | 145 | 70 | 09-28 | 91 | 71 | 145 | daily |
| TGV_phase1 | 144 | 27 | 2025-08 | 0 | 0 | 0 | on_demand |
| TXQ_phase1 | 127 | 1 | 06-07 | 0 | 0 | 0 | on_demand |

- 10 个项目挂在夜间 cron，但**真正还在产新燃料的只有 5 个**：SPX、HATHERINE、TUGE、BJS、ANSHEN。RIO / WTG / OKMAN / XIWU / LNKT 已经一到四个月没新贴，挂着 daily 只是每晚空转一遍。
- ⚠️ SPX 与 HATHERINE 有 `publish_time` 在**未来**（10-11、10-09）的行：飞书里填的是排期而不是发布时间，或者手误。不多，但 L2 标签窗口和 tv-sync 的 ±30 天匹配窗都按它算。
- 近 7 天只入库 1 篇：国庆假期，不是同步坏了（daily-sync 这几晚都绿、步骤齐全）。

### 1.2 通道 2：书架 → 馆员 → 写作台

D-063 / D-069 查出来的"写作台不来借"在 aw PR #85（open_project 随简报自动借）合并后**确实修好了**：9/21 那周 25 个新 brief，对应同期 176 篇真写的稿子，比例合理。

但 D-074 说"攒够 20 个冷路径样本后按 p95 重定 60 秒"，现在样本够了，结论不好看：

```
冷路径样本 24 · p50 49,457 ms · p95 79,313 ms
> 30 s：14 次（58%） · > 60 s：7 次（29%） · 选出 0 张卡：2 次
```

写作台 `LIBRARIAN_TIMEOUT_SEC = 60`，意思是**接近三成的首次借阅在写手那边是超时、拿不到卡的**（fail-open，写手不会有感觉）。而且 60 s 本身已经压在 MCP 客户端实测容忍（~22 s）之上，再往上加不是办法。
瓶颈在馆员的 `_select_via_llm`：sonnet 读 ≤ 50 张候选卡做选取。要么把 `CANDIDATE_CAP` 用 embedding 预筛压到 10–15 张，要么换成 docs/31 位置 ③ 说的 Jev 一次 50 道是非题（一两秒）。

### 1.3 通道 1：TV → 三省六部（🔴 见 §3 P0）

591 条 `reference_samples` 来自 TV。按笔记**现在**的 tier 看：爆 217 · 大爆 87 · 参考 2 · **趴 230 · 风控 54 · 预备 1**。

`audit_log` 把来龙去脉记得很清楚（OKMAN，`synced_to_ssll_at` 非空的 321 篇）：

```
08-18  趴→爆 188 · 风控→爆 50 · 趴→大爆 36 · 数据异常→爆 7 …   ← 飞书状态列一天之内整批变成 爆/大爆
08-18  当晚 daily-sync 按「状态字段」把它们全推进 ssll（quality_score 100 / 200，category 处方药）
08-19  爆→趴 197 · 爆→风控 48 · 大爆→趴 32 …                   ← 第二天改回去了
```

TV 这边改回去了，但通道 1 的自愈回收（`retract_stale_synthetic_from_ssll`）**只撤 synthetic / 铺评工单，不撤"tier 降档"**，于是 284 条处方药"爆款参照"在三省六部的 `reference_samples` 里躺了 7 周。
`v_flywheel_sync_status` 只数**现在**是 爆/大爆 且已同步的（OKMAN 显示 37/0），所以看板上永远看不见这件事。

另外 `pending_ssll_sync` 这一列把被闸挡掉的也算成"待推"：TUGE 显示 14/56，那 56 篇全是 `铺评工单`，是**正确地没推**，不是积压。看板上这个数会让人以为通道 1 卡住了。

### 1.4 写作台（autowriter / deskcore）

| | 数 |
|---|---|
| 项目 / items / versions | 80 / 7,006 / 7,967 |
| 近 30 天 versions | 2,060，其中 **1,593 是 tv-sync 补录副本**，真写的约 470 |
| 指纹库 | 6,150 行（近 30 天 +2,097） |
| 发牌台账 | 发 1,078 · 销 499（46%）；最后一次发牌 09-30 |
| `tv_project_map` | 23 行，覆盖 7 个 TV 项目（ANSHEN / BJS / HATHERINE / LNKT / SPX / TUGE / XIWU） |
| 规则库 | 478 条，hard 61（9/20 时 53） |
| 个人层 | 调校笔记 5 · 精修 diff 30 |
| 人审 | `decision_source='human'` **32 条**，全在近 30 天 |

真写的版本按周：8/17 周 67 · 8/31 周 142 · **9/7 周 466** · 9/14 周 74 · 9/21 周 176 · 9/28 周 16 · 10/5 周 0。10 月第一周为零对得上国庆假期；9/14 那周低是因为那周在做 1,468 篇补录（tv-sync 上线）。**不能据此说写作台停了，但也要等假期后一周看它回不回到 9 月的量。**

`/health` 的 7 天窗口 `drawn 0 / consumed 0`，夜跑两盏 advisory 灯（借阅流量、台账漏账）都报"窗口内没活，无从判定"，与假期一致。

值得单独记一笔：D-072（9/20）把人审链路标成 legacy-only 的依据是"`review_drafts` 一次都没被调过"。**现在被调了 32 次**，`prepublish_evaluations` 从 598 涨到 630。管子没拆，所以数据自己流进来了。那 32 条的 `evaluator_type` 分流是否正确、`pred_tier_class` 仍为空等，等 L2 真要用时再看，但"没人用"这个前提已经不成立。

### 1.5 内容特征层（闸二的前置）

```
primary（llm:claude-opus-4-6）  2,064 篇 · 其中五道升版题（D-082）已有 v2/v3 答案 1,703 篇
code:v1                        2,064 篇
闸一：jev:1.13.0-A/B/C 各 50 篇 · human:owner 95 格 · gate1-v2 / v2fix 重跑 100 / 14 篇
```

features-sync 每晚每项目 ≤ 12 篇（`FEATURE_LIMIT`），9/23 D-083 之后每晚 120 篇、`missing` 0，稳定。但两个结构性问题挡在闸二前面：

1. **七个 on_demand 项目（NUC / NRT_2 / NRT_3 / HXZ_QD / HXZ_FB / TGV / TXQ，共 2,359 篇）不在 features-sync 里**，只有闸一那 60 篇。它们持有 **217 / 411 篇爆款**。闸二是"特征在爆与趴之间有没有区分度"，一半的正例没有特征，这一步算不动。要么对这七个项目跑一次 `backfill-features.yml`（约 2,359 篇 ÷ 120/晚 ≈ 20 晚，或开大 batch），要么闸二先只用 daily 项目并写明。
2. **每项目 12 篇的封顶让预算空转**：ANSHEN / BJS / TUGE 已抽完，HATHERINE 还差 67 篇；剩下的 RIO 598 · WTG 520 · SPX 301 · LNKT 172 · OKMAN 122 · XIWU 97 按 12/晚各自算，RIO 要 50 晚，而整趟 2 小时 16 分离 240 分钟上限还有一倍余量。把 `FEATURE_LIMIT`（repo variable）提到 20–24，大项目的收尾时间能减半。

### 1.6 Jev（JevforCoentent）

仓库本身：3 个 PR 全合、CI 绿、69 个测试全过（本地复跑）。docs/02 列的 13 项硬伤 + §2 的 10 项设计缺口都在 PR #1/#2 里修掉了，仓内文档与代码对得上。

八个位置的实际状态：

| 位置 | 代码 | 生产 |
|---|---|---|
| ① TV 主抽取换 Jev | `fq_shadow.py --from-db` 就绪；TV 侧 `--done-by` 续跑判据已落（D-085） | **没切**，也没跑 300 篇影子跑 |
| ② 评论回填 | `backfill_comments.py` 就绪；TV 侧评论切法已修、1,210 条旧行已删（D-085 续） | **没跑**；账本 `comment` 0 行 |
| ③ 借卡换 Jev | 未写 | — |
| ④ 发牌筛组合 | 未写 | — |
| ⑤ 写作台入库判定 | aw `judge_client.py` + `_judge_committed` 已合（#92）；请求体与 Jev `DraftRequest` 字段逐一对得上 | **`JUDGE_URL` 没配**；judge 服务本身没有部署证据（三仓无 railway 地址）；账本 `aw_version` 0 行；`batch_metrics` 里 5 次 commit 都是 `not_configured` |
| ⑥ 三省六部二审 | 题库 `ssll_critic_v0.1` 就绪 | 不在本次范围 |
| ⑦ 素人初稿 | 后做 | — |
| ⑧ 外部语料 | `external_corpus.py` + 周一定时 | ✅ **10-08 第一次真跑成功**：9/28、10/5 两次定时跑红（密钥/UA 问题），今天手动四连跑修掉 Cloudflare UA 封锁和详情解析，第二次写入把 60 字摘要换成了全文。**下周一 10-12 是第一次定时真跑** |

Jev 的账本写入走 PostgREST，TV 的 v1_17 / v1_18 迁移 9/26 已 apply，`v_external_reference` 今天起有数据可查。

---

## 2. 结合的进度（每条缝的五个状态）

| 缝 | 代码合并 | 迁移落库 | 部署 | 配置 | 生产流量 | 验收 |
|---|---|---|---|---|---|---|
| TV → ssll（通道 1 push） | ✅ | ✅ | ✅ | ✅ | ✅ 591 | ⚠️ 污染 284，见 P0 |
| TV 书架 → 馆员 → deskcore（通道 2 pull） | ✅ | ✅ v1.16 | ✅ | ✅ | ✅ 31/月 | ⚠️ 29% 冷借超时 |
| deskcore → TV 回程（tv-sync） | ✅ | ✅ 009/010 | ✅ cron 04:00 | ✅ 7 项目映射 | ✅ 每天 | ✅ |
| aw 人审 → TV prepublish | ✅ | ✅ 006 / v1.11 | ✅ | ✅ | ✅ 32 条 | 未复核分流口径 |
| aw 台账 ↔ TV tier（v_angle_outcomes） | ✅ | ✅ 011 已 apply | — | — | 可查 | 发牌加权未做（等闸二） |
| Jev → TV 账本（外部语料） | ✅ | ✅ v1_17/18 | GitHub Actions | ✅ | ✅ 今天 200 篇 | 下周一看定时跑 |
| Jev → TV 账本（闸一） | ✅ | ✅ | — | — | ✅ 3,000 行 | ✅ D-082 裁决完 |
| aw → Jev → TV 账本（入库判定） | ✅ #92 | ✅ | ⛔ judge 未部署 | ⛔ `JUDGE_URL` 空 | ⛔ 0 | — |
| TV worker → Jev（主抽取） | 半（TV 侧判据） | ✅ | ⛔ | ⛔ | ⛔ | 影子跑未做 |
| Jev → TV comments（评论回填） | ✅ | ✅ | — | — | ⛔ 0 | — |

**结论**：9 月 23–26 日那一轮"三仓各开一个 PR"把**代码和迁移**全部落地了，但 Jev 这一圈只有不需要常驻服务的那条（GitHub Actions 跑外部语料）通了电。
需要 judge 服务常驻的两条（写作台入库判定、TV 主抽取）停在"部署 + 配两个 env"这一步，和 D-063 那次"管子通、龙头没人拧"是同一个形状。

---

## 3. 问题清单（按该先处理的顺序）

### P0 · 通道 1 里有 284 条处方药"伪爆款参照"（三省六部正在用）

- **事实**：OKMAN_phase1 有 321 篇标了 `synced_to_ssll_at`，现在只有 37 篇是 爆/大爆；229 篇 趴、54 篇 风控、1 篇 预备 的 `reference_samples` 行仍在 `public` 里，`quality_score` 100/200、`category` 处方药。
- **来龙去脉**：08-18 飞书状态列整批翻成 爆/大爆（188 + 50 + 36 + …），当晚推进 ssll；08-19 改回。TV 的 tier 是对的，ssll 的没人撤。
- **为什么没人发现**：`retract_stale_synthetic_from_ssll` 只认 synthetic / 铺评工单；`v_flywheel_sync_status` 只数现在是爆的。两道灯都照不到"推出去之后降档"。
- **建议**：① 一次性清理：按 `source_truth_vault_note_id` 对应笔记 `tier NOT IN (爆, 大爆, 参考)` 删 285 行，同时把这些笔记的 `synced_to_ssll_at` 清空（删前先备份行）；② 把回收判据扩成"已同步但现在不满足 push 判据的一律撤"，与 push 共用同一份判据（D-068 的对称原则）；③ `v_flywheel_sync_status` 加一列 `stale_in_ssll`。**删生产行要 owner 点头，本次没动。**
- 顺带：`pending_ssll_sync` 把被闸挡掉的也算进去（TUGE 56 全是铺评工单），看板会误导，建议拆成 `gated` / `pending` 两列。

### P1 · 写作台入库判定没通电，judge 服务没部署

- aw `/health`：`judge.configured: false`；`batch_metrics` 五次 commit 全 `not_configured`；账本 `aw_version` 0 行。
- 三个仓库里找不到 judge 的 Railway 地址（aw runbook §1.7 第 1 步"judge 服务先在 Railway 起来"没有执行记录）。
- 上线只差 runbook §1.7 的 6 步：起服务 → 配 `JUDGE_URL` / `JUDGE_API_KEY` → `/health` 看 `judge.configured` → 确认 `tv_project_map` → 随手 commit 一篇看 `judge.summary` → 两周后按 `batch_metrics` 重定 8 秒。处方药项目（OKMAN）按 `data_policy.yaml` 会 403，这是设计如此。
- 代码契约我对过一遍：aw `build_draft_request` 发的 10 个字段 Jev `DraftRequest` 全认；`write=true` + `subject_id=versions.id` 的 422 防线、403 `policy:` 前缀都对得上。

### P1 · 馆员冷路径三成超时（通道 2 实际打折）

见 §1.2。D-074 等的 20 个样本已经有 24 个：p95 79 s，7/24 超过 60 s。建议先把 `librarian/core.py` 的 `CANDIDATE_CAP=50` 前面加 embedding 预筛（书架 306 张卡，pgvector 已装未用），或直接走 docs/31 位置 ③ 用 Jev 判 50 张卡。两个都不需要改写作台。

### P1 · 闸二算不动：一半的正例没有特征

见 §1.5。先决定 on_demand 七个项目要不要抽（2,359 篇、约 217 篇爆款）；再把 `FEATURE_LIMIT` 从 12 提上去。这两件不做，闸二至少还要等两个月。

### P2 · 外部语料：定时跑连红两次没人看，今天的真跑在分支上

- 9/28、10/5 的 `external-corpus.yml` 定时跑都是 failure（密钥未配 / UA 被 Cloudflare 封）。它没有登记在 TV `docs/29` 的灯登记册里，也没人收它的红。
- 今天真正写入全文的那次（run #11）是从分支 `claude/focused-franklin-blz1ig` 手动触发的，PR #4 已合并，**10-12 周一是 main 上第一次定时真跑**，要有人看。
- 第一次（60 字摘要）写进去的 200 篇被第二次按 `note_id` upsert 覆盖了，账本 4,800 行也随之覆盖，库里现在是干净的。

### P2 · 评论回填 ② 还没跑

TV 侧前置（切法修复 + 1,210 条旧行清理）9/27 已做完，Jev 侧 `backfill_comments.py` 就绪，9,652 条评论的 `comment_intent` / `is_scripted` 仍是空。这是 docs/31 里"现在就能做"的四件里唯一没动的。

### P2 · 文档的"当前事实"全部过期

| 文件 | 写着 | 实际 |
|---|---|---|
| TV `README.md` 下半 | 2026-09-16，5,949 篇 / 16 项目 | 6,300 篇 / 17 项目（HATHERINE 9/17 接入） |
| TV `CURRENT_STATE.md` | 最后更新 2026-06-09 | 顶部补丁堆到 9/20，正文仍是 6 月 |
| TV `RISKS.md` | 最后更新 2026-05-22（R-028） | README 索引说到 R-031 |
| aw `deskcore-runbook.md` | 快照 2026-08-26 | 之后的 009/010/011、judge 都以补丁段形式挂在上面 |
| Jev `docs/31` | 只在 Jev 仓，TV 的 docs/30 从未入库 | TV 文档里引用 docs/30/31 的地方指向不存在的文件 |
| TV `docs/00` §3 数据流向图 | 没有 `external_notes` / judge 两条路 | D-085 自己写明"没加" |

这个仓的纪律是"去问系统，别抄文档"（D-075），所以它不致命，但新接手的人会被 README 的数字带偏。

### P3 · 小项

- SPX / HATHERINE 有 `publish_time` 在未来的行（运营填的是排期）。
- daily-sync 10-07 跑了 52 分钟，其中 **comments 那一步 44 分钟**（D-085 后对所有项目跑、不走 on_demand 闸）。离 240 分钟上限还远，但它随语料线性涨。
- 饱和度灯每晚 `rc=2`（"没测全，无法判定"）：这盏灯从 v1_8 起就一直是这个读数，按 docs/29 的规矩该么补 essence 标注让它能测，要么退灯。
- `flywheel_librarian_cache` 的 TTL 30 天 prune 让"馆员历史流量"只能看最近一个月；D-074 要的 p95 样本以后要从别处留。

---

## 4. 建议顺序

1. **先清通道 1 的 285 条**（P0）：这是唯一一条"现在就在污染下游生成"的事，处方药品类。owner 点头后执行，顺手把回收判据改成与 push 对称。
2. **把 judge 服务起起来、给 deskcore 配两个 env**（P1）：代码 9/26 就合了，影子期只记不拦，没有风险，不配就永远攒不到样本。
3. **馆员冷路径预筛**（P1）：通道 2 是飞轮里唯一真正"把经验喂回生产"的那条，三成超时等于打七折。
4. **决定 on_demand 七个项目要不要进特征层，提 `FEATURE_LIMIT`**（P1）：不决定，闸二没有开跑日期。
5. 10-12 周一盯一次 `external-corpus` 定时跑；把它登进 `docs/29` 的灯登记册。
6. 跑评论回填 ②。
7. 假期后一周看写作台周产量回不回到 9 月的水平；回不去再查协议 / skill 导入。
8. 文档"当前事实"段统一刷一遍（README 下半、RISKS 表头、docs/00 §3 补两条路）。
