# librarian/ · 飞轮 LLM 馆员服务

pull 模型(D-038 / [docs/14](../docs/14-channel2-pull-librarian.md))的**借阅端**:aw / ssll
写稿时按 brief 向馆员借阅匹配的"经验卡"。

```
librarian/
├── clients.py   自包含 Supabase(service_role) / Anthropic 客户端 (便于独立部署 Railway)
├── core.py      选取核心: 取候选 + 缓存 + LLM 按 brief 推理选 3-5 张 + 降级
├── cli.py       命令行测试器 (--dry-run 看 prompt; 真跑连库 + LLM)
├── sample_brief.json   示例 brief
├── app.py       FastAPI 端点 (POST /librarian, GET /health), aw/ssll 调它
└── requirements.txt  服务依赖 (fastapi/uvicorn/supabase/anthropic)
```
> Railway 部署配置在 **repo 根 `railway.json`**(root 设 repo 根, 让 `librarian` 包可导入)。

## 流程 (core.librarian_select)

1. 取【整架】(`v_flywheel_lesson_cards`, 按 rank_score, 上限 1000; 10-08 实查 306 张)。**空库 → 返回 `[]`**(消费方降级到自有正例)。
2. 算 `library_version` = f(整架候选数, max(curated_at), 月份桶, id 集合摘要[, gate2_run]) → 算 `cache_key`。
3. **同一个 `cache_key` 已经有一次在选 → 等它,拿同一份结果**(AU-F09 在飞合并;进程内,最多等 75 秒,等不到就自己选)。
   **命中缓存 → 直接返回**(跳过 LLM)。
4. 未命中 → **预筛 `shortlist()`(D-088)**: 按 brief 的项目级字段打贴题分(同品牌 +3 · 同品类 +2 · 人群词 +1)挑 ≤24 张,
   rank 全局前 8 张无条件保留(跨主题迁移要有料); 只看项目级字段、不看本次 delta(同项目内候选块稳定, prompt cache 才命中)
   → LLM 按 brief 推理选 3-5 张(两句批注各 ≤30 字, `max_tokens` 封顶 1000)→ 校验 id 在候选内、同一张卡只留一遍(F14a)→ 富集卡内容 → 写缓存。
   **LLM 失败 → 返回 `[]`**(绝不阻塞写稿; 飞轮是增强项)。

> 为什么要预筛(D-088): 之前 fetch 前 50 张按 rank 硬切整批喂 LLM —— 品牌自己的卡常常不在前 50 里;
> 冷路径 24 个样本 p50 49s / p95 79s, 7 次超过写作台 60s 的等待, 耗时大头是模型【写】的那几百 token 走中转站
> (选 0 张的两次只用 3s / 11s)。所以卡给得更贴、字写得更少。守卫: `scripts/check_librarian_shortlist.py`。

**两层省钱(应用 autowriter 同款策略)**:
- **结果缓存**(上面 step 3, `flywheel_librarian_cache`):挡"完全相同的请求"(同 brief + 同 library_version),直接复用上次精选、**整次跳过 LLM**。
- **Anthropic prompt caching**(`cache_control: ephemeral`):候选卡库 + 项目 system_prompt 作为缓存 system 块,挡"同库不同 brief"的请求 —— 只重算 delta 部分,大前缀缓存命中省 ~90%。
- LLM 调用支持**中转站**(`ANTHROPIC_BASE_URL`,同 autowriter `clients.get_anthropic_client` 约定);重试覆盖 429/502/503/529(中转站常见 overloaded)。
- **备用中转站**(可选, D-148):`ANTHROPIC_BASE_URL_BACKUP` + `ANTHROPIC_API_KEY_BACKUP` 都配了才启用。每次尝试先打主站
  (只给一次机会、限时 22 秒, `RELAY_PRIMARY_TIMEOUT_S` 可改, 超过 40 按 40), 超时 / 连不上 / 429 / 5xx / 401-404 → 这次改打备用站; 主站连续
  2 次失败 → 熔断 20 分钟直接走备用站 (「成功但慢 >25 秒」那条在 22 秒限时下用不上)。`RELAY_FORCE=backup` / `primary` 手动切。
  `/health` 的 `relay` 块带模式、熔断状态和本进程计数 (`relay_counts`), 不出地址或 key。运行手册:
  `docs/12-daily-sync-troubleshooting.md`「备用中转站 (D-148)」。
- **时限**(AU-F09, `clients.py`):SDK 一律 `max_retries=0`, 重试只留 `call_anthropic` 自己那一层 (最多 3 次, 退避 2 / 4 秒);
  单次调用限时 45 秒 (配了备用站时主站 22 秒); 整轮 (各次尝试 + 切备用站 + 退避) 最多 60 秒, 每次调用的限时再按整轮剩下的
  时间收紧。最坏: 主站挂住 22 秒 → 备用站正常约 15 秒 ≈ 37 秒拿到卡; 两边都挂住 → 第 60 秒降级返回 `[]`。60 秒不能再低:
  写作台 `open_project` 起的借阅在后台等满 60 秒, 慢的那次也要写进缓存, 接着来的 `borrow_lessons` 才拿得到。
  `/health` 的 `select` 块回显现在生效的三个时限和在飞合并的计数。三条边界:
  - 限时都按「没有新字节」算 (httpx 按每次读计), 不是墙上时钟。中转站挂着不出字节时上面的数成立 (线上见到的就是这种);
    中转站一直滴保活字节的话不封顶, 一次调用和整轮都可以超过, 等同一个请求的人到 75 秒 (`MERGE_WAIT_S`) 自己去选。
  - 主站本来会在 22-30 秒答完的那种 (线上 10 月中到 11-12 见过 3 次: 11-01 25.5 秒、11-05 28.7 秒、11-11 22.7 秒) 也在
    22 秒被切到备用站, 约 37 秒才拿到卡 (原来 26-29 秒), 写作台那次 `borrow_lessons` 可能等不到 (缓存照样写进去), 被切的
    那次主站可能照样计费。要保这种就把 `RELAY_PRIMARY_TIMEOUT_S` 调到 30, 代价是主站挂住时回到约 45 秒。
  - `RELAY_PRIMARY_TIMEOUT_S` 超过 40 按 40 (整轮 60 秒 - 2 × 10 秒): 再高的话快失败不再重试、缓存块降级不做、备用站
    剩不下一次冷选卡的时间。`/health` 回显的是按 40 封过的值。

## 本地测试

```bash
# 前置: schemas/notes_v1_4 + notes_v1_5 已 apply 到目标库
export SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=...   # service_role
# 只看 prompt + cache_key (不调 LLM):
python -m librarian.cli --brief librarian/sample_brief.json --dry-run
# 真跑 (需 ANTHROPIC_API_KEY):
export ANTHROPIC_API_KEY=...
python -m librarian.cli --brief librarian/sample_brief.json
```

> 当前书架有 **1 张卡**:WTG 那条「参考」(`WTG_phase1_recvk9VPCTNG1b`)。它 synthetic=true
> 但 tier=参考 → 放行(synthetic 只挡爆/大爆;参考是人工内容判断、与指标真假无关,Session #15;
> 卡带 `synthetic` 标记,馆员 `_render_cards` 会提示"指标未验证")。`is_curated=false`,馆员用
> essence + excerpt 兜底,下次策展 pass 补 hook/structure 等 4 字段。真·爆款进库后书架扩充。

## 与"策展员"的区别

- **策展员**(`prompts/flywheel_curator.md` + `scripts/curate_flywheel_lessons.py`):入库时把**单条**爆款提炼成一张经验卡。
- **馆员**(`prompts/flywheel_librarian.md` + 本目录):写稿时从**多张**卡里**按 brief 推理选取**。

## 部署 (Railway)

repo 根 `railway.json` 已配好;在 Railway 建一个 service、root 指 repo 根、设环境变量
(`SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` / `ANTHROPIC_API_KEY` / **`ANTHROPIC_BASE_URL`**
(中转站/第三方网关, 可选, 不设走官方) / `FLYWHEEL_LIBRARIAN_MODEL`(见下方⚠️) /
**`LIBRARIAN_API_KEY`** / 可选的备用中转站 `ANTHROPIC_BASE_URL_BACKUP` + `ANTHROPIC_API_KEY_BACKUP` 与 `RELAY_FORCE`
(D-148, 见上))即可。healthcheck 走 `/health`。

> ⚠️ **`LIBRARIAN_API_KEY` 从"建议设"变成"必须设"**(2026-08-26,跨库审计 SUP-001)。
> 不设的话服务照常起、`/health` 照常 200,但**所有业务请求一律 401** ——
> 因为它持 service-role 客户端读 lesson cards、且每次 miss 都打一次 LLM,
> 漏配一个 secret 就等于把这两样交给公网,而漏配**没有任何症状**。
> 本地开发要免鉴权,显式设 `LIBRARIAN_ALLOW_ANONYMOUS=1`(别设进 Railway);
> 当前处于哪一态看 `/health` 的 `auth.mode`。

> ⚠️ **模型 env 名各服务不同(2026-06-04 踩过的坑)**:馆员读 **`FLYWHEEL_LIBRARIAN_MODEL`**(默认
> `claude-sonnet-5-5`),而 worker 读 `ESSENCE_MODEL`、autowriter 读 `CLAUDE_MODEL` —— **三个名字都不一样**。
> 如果你的中转站通道**不 serve 默认的 `claude-sonnet-5-5`**,却只给 worker/aw 设了能跑通的模型、忘了给馆员
> 设 `FLYWHEEL_LIBRARIAN_MODEL`,馆员每次调用都会失败、**降级成 `{"selected":[]}`**(且 `flywheel_librarian_cache`
> 一直 0,从外面 200 看不出错)。**换通道模型时,三个服务的模型 env 都要设成通道认的那个名字。**

调用(消费方):
```
POST /librarian   header: X-Librarian-Key: <key>   body: <brief JSON>
→ {"selected": [ {source_note_id, why_relevant, borrow_what, hook_type, structure, excerpt, ...}, ... ]}
```

## 回流闸（D-151，已做、开关关着）

写作台每晚 tv-sync 的最后一步给映射项目里每篇发出去的帖分一次类，记在 `autowriter.tv_note_links` 的 `gate` / `gate_reasons` 上（aw 迁移 020；分类那一半在 TangVarie/autowriter）。馆员可以在整架取回之后、算版本串和预筛之前，把出处帖「不能学」的卡拿掉（`core._drop_gated`）。

- **默认关**：`core.RETURN_GATE_DEFAULT = False`。要开就是改这一行的一个 PR（写作台那头的类别数连着三晚对得上之后，OPEN-ITEMS F-17）。环境变量 `LIBRARIAN_RETURN_GATE` 可以盖过代码默认，但不需要设。关着的时候 `autowriter.tv_note_links` 一次都不读，候选、版本串、缓存键、给模型的 prompt 和以前一字不差。回包不在这句话里：下一节的投流标注不看这个开关，回包的卡多一个 `paid_boost`，投过流的卡 `why_it_worked` 前面多一句，为这个每 10 分钟读两次 TV。
- **挡卡的原因只有五个**（`core.CARD_BLOCKING_REASONS`）：`withdrawn`（飞书里删了）、`hold`（没发布时间 / 排期在后面 / 正文还是空的 / 伪爆，都是「还没到齐」；细项在 `gate_reasons.hold` 里，馆员不看细项，哪种都挡。发出去的短帖有字就不是 `hold`：11-12 复审后写作台那头改的，最初按「正文不到 50 字」搁置，书架上 13 张爆 / 大爆的卡会一直借不出去）、`risk`（风控）、`efficacy`（功效承诺）、`unsure`（功效题还没答）。**只有 `not_clean`（投流标记 / 铺评工单 / 投流事件）的卡照借**：D-133 第 1 条定的是投流证据链不动书架；owner 11-12 定了这种卡照借、卡上写明（D-151 第 13 条，F-16 关），那一句由下一节加，和这个闸的开关无关。
- **没有结论一律留**：四列不在（020 没跑）、这篇没有对账行（没映射写作台的项目）、这一行还没分过类、`gate_reasons` 读不懂（只认 `{"reasons": [名字, …]}`）。
- **10 分钟读一次**（进程内），不是每次借阅都读；读失败沿用上一次读成的结论，一次都没读成过就不筛。绝不往借阅里抛。
- **品牌保底**：筛完某个品牌的卡一张不剩 → 这个品牌的卡全留，`/health` 里记一笔。
- **`/health` 的 `select.return_gate`**（只有布尔、整数和 `null`）：`on` 开没开、`read_ok` / `read_errors` 上次读库成没成、`columns` 那两列在不在、`verdicts` / `unreadable` 书架里有结论 / 读不懂的行数、`would_drop` 最近一次筛书架拿掉几张、`brands_kept` 保底留了几个品牌、`read_age_s` 上次读库是多少秒前。
- 版本串（`library_version`）不用改：它本来就摘要了候选 id 集合，一张卡被挡或放回来，缓存键自己换。
- 守卫：`scripts/check_librarian_shortlist.py` §10（开和关两种状态都跑）。

## 出处帖投过流的卡照借，回包的卡上写明（D-151 第 13 条，不设开关，合并就生效）

owner 11-12 定的：投流起量的帖就直说是投流起量的，让运营自己判断。馆员不藏、不拿掉这种卡，回给消费方的卡上多一句，两种写法，按记录撑得住的写：

> 注意: 这篇是投流起量的, 数据不全是内容带来的, 借不借由你判断　（`core.PAID_BOOST_LINE`：投流事件里起量时间落在投流日到之后 7 天里的）
>
> 注意: 这篇投过流, 数据不全是内容带来的, 借不借由你判断　（`core.PAID_BOOSTED_LINE`：其余的，只知道投过流）

- **哪些帖算**：`data_quality_flags.paid_promoted` 为真，或者在 `truth_vault.v_paid_boost_events` 里（D-133；投了流、没标 `paid_promoted` 的也在里面）。和写作台 `priors.is_clean` 投流那一半是同一批帖。只看 TV 自己的数，不读回流闸那四列：迁移 020 跑没跑、回流闸开没开都一样。铺评工单不在这一条里（那是评论是铺的；这种爆 / 大爆本来就不上书架）。
- **哪种写法**：「投流起量的」是 owner 的原话，只给记录撑得住的卡：事件视图的 `takeoff_vs_window = 'in_window'`（起量日在投流日到之后 7 天里）。这说的是时间，不是归因（D-133 第 1 条「不做因果归因」没动）。只有 `paid_promoted` 标记、没有投流日期的，起量在投流窗口之外的，没填起量时间的，只写「投过流」。11-12 只读书架上 20 张：前一种 10 张，后一种 10 张（只有标记 7、事件里没填起量时间 2、起量在投流 16 天之后 1）。
- **只给人看，选卡的模型看不到**（11-12 复审后改的；最初候选卡上也有这一句、任务说明里也有一句）：候选卡上没有任何记号，任务说明里没有这件事，所以这一步的 prompt、候选、缓存键、选哪几张都不因为投流变（对着 `9a2c708` 的 prompt 逐字比过）。原因：owner 把判断留给运营；这 20 张卡占书架 6%、占借出去的内部卡 32%，选卡模型要是看得到、自己绕开，运营就再也见不到它们，等于藏了，也等于让投流证据链动了借出去的卡（D-133 第 1 条）。
- **回给消费方的卡**：都带 `paid_boost`（`true` = 出处帖投过流；`false` = 没有 `paid_promoted` 标记、也不在投流事件里，而且这两路 1 小时内都读成过，外部参考卡一律 `false`；`null` = 不知道：有一路没读成过，或者上次读成已经是 1 小时以前）。`true` 的卡那一句写在 `why_it_worked` 的最前面，原来的内容接在后面（原来是空的就只有这一句）。放这个字段是因为两条消费路径都原样带它（写作台把整张卡交给模型；常规生成那条只渲染认得的几个字段）；不放 `excerpt`，那一段会被截。**`false` 不等于「查过、没投过流」**：进了隔离视图（标记认不出、日期和效果配不上）而既没标记也没事件的帖也是 `false`，和写作台的干净尺子一样不把它当投流（11-12 书架上 1 张）。
- **到没到写手眼前**：这一句到的是写作台的模型。写作台的协议和工具说明还没教模型把它转告写手（OPEN-ITEMS W-54），在那之前写手看不看得到没有保证。
- **不进缓存**：缓存行里的卡不带这一句，每次回包时按当下读到的那批帖现加（`core._label_paid`；命中缓存的、新选的、并到在飞那次上的都一样）。以前写的缓存行照样带，今晚新认出来的投流帖今晚就标上；`library_version` 和缓存键没改。
- **读数**：一次两个请求（标了 `paid_promoted` 的帖、投流事件），在后台线程里读，不占锁。读成了 10 分钟内不重读；有一路失败，60 秒后重读。借阅一进来就让它读起来，回包前最多等到这次读开始后的 4 秒（冷路径上它和选卡的模型调用同时跑），等不到就用手上那份、记一笔，线程读完自己写回（supabase 客户端默认 120 秒超时，不能在借阅的路上干等）。哪一路读失败就沿用它上一次读成的那份（在里面的帖照标）；上次读成已经是 1 小时以前，不在里面的卡是 `null`，不再说 `false`。两路都从来没读成过，卡照常借出去、都不带这一句。绝不往借阅里抛。
- **`/health` 的 `select.paid_boost`**（只有布尔、整数和 `null`，重启清零）：`read_ok` 上次两路都读成没有、`read_errors` 累计读失败的路数加上回包前没等到的次数（涨了 = 有卡在不带这一句地借出去，或者用的是旧的那批帖）、`flagged` / `events` 两路各读到几篇、`window` 事件里起量在投流窗口内的几篇、`lent` / `labelled` 累计回了几张内部卡、其中标了几张、`read_age_s` 上次去读是多少秒前。
- **谁在看**：`/health` 没有脚本去拉（TV 的夜跑不知道馆员的地址）。夜跑的借阅流量灯（`scripts/check_librarian_traffic.py`）每晚用夜跑的钥匙把这两路照样读一遍，读不到就打 `::warning`（视图被迁移改了名、权限这一类，馆员多半也读不到）；同一段印近 7 天新借给写作台的内部卡里出处帖投过流的占几成，和 11-12 的基线（165 张里 52 张，32%）并排，只印不判。馆员进程自己读不到而夜跑读得到的情况这盏灯看不出，周检时手看 `/health`。
- 11-12 只读：书架 321 张里 20 张会带这一句（爆 8、大爆 12，6 个品牌）；馆员缓存 38 次借卡的 165 张内部卡里 52 张（26 次）。
- 守卫：`scripts/check_librarian_shortlist.py` §11（夜跑那一段也在这里测）；`/health` 那一块在 `scripts/check_relay_failover.py`。

## 待办

- 前置:`schemas/notes_v1_4` + `notes_v1_5` apply 到 prod(否则视图/表不存在)。
- 接入消费方:autowriter([R-032](../docs/10-sister-repo-followups.md#r-032))、sanshengliubu([R-033](../docs/10-sister-repo-followups.md#r-033))——写稿前调本服务、把 selected 注入 prompt。
