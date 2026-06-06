# Truth Vault · 全局交接 (2026-06-05 · Session #18 收口)

> 写给**下一个接手 / 新会话 / 三个月后的自己**。
>
> **本篇取代 [docs/21](21-handover-2026-06-05.md) 作为"当前状态"权威**(21 是 NRT_2 上线那轮的快照,保留作历史)。
> 21 之后又发生了一整轮:**NUC + NRT_3 两个项目上线、接表 SOP 升级(preflight 体检 + cron 安全闸)、
> 一串健壮性 bug 根治、通道2(autowriter 飞轮)production 真正拉通、负面机制澄清**。本篇把这些对齐到一处。
>
> 配套:总入口 [00](00-START-HERE.md) · 架构 [01](01-architecture.md) · 决策 [DECISIONS.md](../DECISIONS.md) ·
> 风险 [RISKS.md](../RISKS.md) · 拉取/馆员 [14](14-channel2-pull-librarian.md) · 接表 SOP [04](04-onboarding-sop.md) · 跨仓 [10](10-sister-repo-followups.md)。

---

## 0. TL;DR(90 秒)

- **飞轮 4 个项目、第一次端到端真转起来了**:WTG / NRT_2 / NUC / NRT_3 共 **2478 篇笔记 · 96 篇真爆款燃料(全部 →ssll) · 87 张经验卡上架**。
- **通道2(autowriter)production 拉通** ⭐:autowriter 写稿时**真的在调 TV 的 LLM 馆员、借爆款经验卡注入 prompt**(实测一单借回 5 张)。不再是"自测可用",是**真有流量**。
- **接表从"prod 试错"升级成"接表前一键体检 + cron 安全闸"**:`preflight_mapping.py`(+ Preflight workflow)接表前几秒投影出"会丢多少/哪些列没声明/品类/方向";`sync_interval` 现在**真生效**(新表 `on_demand` 时夜间 cron 不碰,验证后改 `daily` 才入)。NRT_3 上线全程**没碰 prod 试错**(preflight 拦下 596 行真内容丢失)。
- **一串健壮性 bug 根治**(都因 NUC 是首个大规模跑 sub_direction 的表逼出来):essence 单条抽风/Railway 超时/bash 崩、curate 超时、空行日志刷屏——全部容忍/兜底化,且是**通用修复**(不分表)。
- **负面机制澄清(本轮重点纠错)**:TV **只送正面**爆款经验;负例是 **autowriter 自己的人工标注**(`example_label='negative'`),**TV 不推负面、`趴` 不能当负面源**(正负信号不对称,见 [D-040](../DECISIONS.md#d-040))。
- **下一步**:L3 受众层(设计齐全、代码空,是 L2 预测的输入前提)→ L2 预测。

---

## 1. 当前真实数据状态(2026-06-05 实查 · 4 项目)

| 项目 | 笔记 | 爆款(爆+大爆) | 真爆款(状态字段) | →ssll | essence 已标 | sync_interval |
|---|---|---|---|---|---|---|
| WTG_phase1(个护) | 724 | 3 | 0(synthetic, 不进下游) | 0 | 724(全) | daily |
| NRT_phase2(OTC药) | 499 | 27 | 27 | 27 | 101 | daily |
| NUC_phase1(保健品) | 657 | 44 | 44 | 44 | 167 | daily |
| NRT_phase3(OTC药) | 598 | 25 | 25 | 25 | 50 | daily |
| **合计** | **2478** | **99** | **96 真**(WTG 3 synthetic 除外) | **96** | **1042 / 2478** | — |

- **真燃料 96 篇全部 `synced_to_ssll`**(通道1);**书架经验卡 87 张策展完**(`v_flywheel_lesson_cards` 共 97 张可借,87 已策展 + 10 待 curate)。
- essence 各项目按 daily-sync 每天 50/项目 drain(均 `daily`、进夜间 cron)。
- **L3 受众** `audience_inferred = 0`(从没跑过);L2/L4 未启用。

---

## 2. 通道2(autowriter 飞轮)production 拉通 ⭐(D-038 / R-032)

通道2 = TV 把合格爆款策展成**经验卡**放进图书馆视图 `v_flywheel_lesson_cards`,autowriter **写稿时向 LLM 馆员按 brief 借阅、注入 prompt**(喂可迁移的钩子/结构/手法 = essence)。**两侧都已就绪并真有流量**:

**TV 侧(就绪)**:97 卡在架(87 策展) · 馆员服务 `librarian/`(FastAPI on Railway) · 缓存表 `flywheel_librarian_cache`。

**aw 侧(已接,本轮确认真在用)**:
- `librarian_client.py`:`build_brief()` + `fetch_flywheel_lessons()` → `POST {LIBRARIAN_URL}/librarian`、`X-Librarian-Key`、解析 `selected`、**任何失败返 `[]` 降级**。
- `app.py` `_queue_worker_impl`(生成主路径):`fetch_flywheel_lessons(build_brief(...))` → 传 `flywheel_lessons or None` 进 prompt(真 fetch + 优雅降级)。
- `memory.py` `build_layered_system_prompt()`:`flywheel_lessons` 注入 **P2 层独立 section**(`[真实爆款参照 · 系统按本次选题从帆谷飞轮库匹配]`),与 owner 自有正例并列、每批随 brief 变、不缓存。
- **实测**:一单真生成(真实 project UUID)调到馆员、**借回 5 张经验卡**注入,馆员缓存出现真实流量行。

**autowriter 部署 env(在 aw 的 Streamlit secrets / 部署平台,不是 GitHub Secrets)**:
- `LIBRARIAN_URL` = TV 馆员 Railway 地址 · `LIBRARIAN_API_KEY` = **必须 = TV 侧 key**(校验 `X-Librarian-Key`)· `LIBRARIAN_TIMEOUT_SEC`(默认 8、建议 **20**:覆盖缓存未命中的 LLM 选卡 + 冷启动余量;为空时 `fetch` 静默返 `[]`=不注入,这是"没设 env"的典型表现)。

> ⚠️ R-018 Phase-2 若把生成搬进 `worker.py`,要把 app.py 这段 R-032 接线**一并搬过去**,否则切到 worker 路径飞轮注入会丢。

---

## 3. 负面例子机制(本轮重点澄清 · 防再次踩错)

**TV 只贡献正面;负例完全是 autowriter 自己的,TV 不推负面。** autowriter 写稿 system prompt 有**三条轨**:

| 轨 | 来源 | 正/负 | 谁产生 |
|---|---|---|---|
| Owner 正例(P1) | autowriter 自己 approved/打标 positive 的 items（现 14） | ✅ | autowriter 内部 |
| Owner 负例(P1) | autowriter 自己的**人类行为**:手动精修/反馈改写/同批淘汰（现 103 已确认） | ❌ | autowriter 内部 |
| **TV 飞轮(P2)** | TV 馆员按 brief 借的**爆款经验卡** | ✅ | **TV → AW(就是 §2)** |

**负例链路(全程在 AW 自己库里转)**:`extract_negative_examples_from_autowriter.py`(TV 仓脚本,扫 AW 历史的 A/B/C 信号)→ 写 `autowriter.items.example_label_proposal`**候选** → **人工在 Memory Manager"负例候选 review" tab 审**(Confirm/Reject)→ 确认的落 `example_label='negative'` → `build_system_prompt` 注入 `[反面案例·主动规避]`。脚本只产候选;人工标是日常主路径(D-027)。

> UI 里"外部源(Truth Vault 等)写入候选负例"——那个"TV"**只是因为挖掘脚本放在 TV 仓**,**不是 TV 在做内容判断**;候选内容是 **AW 自己的烂稿**,不是 TV 数据。

**⚠️ 为什么负例只能人工标、不能从 `趴` 推(正负信号不对称,[D-040](../DECISIONS.md#d-040))**:
- **「爆」干净**(赢=内容够好+拿到分发);**「趴」脏**(输有一堆与内容无关的无辜解释:**撞流量墙**没进流量池就死、**账号**权重/限流、时机)。
- 把 `趴` 当差笔记 → 把被埋没的好内容也标成垃圾、**污染负面特征**。**故负例以人工标注为准;`趴` 不作负面源。**
- 跨产品"避坑特征"(对称的负面飞轮)= **roadmap 空白**,真做的话源**必须用人工标的干净负例**(不是 `趴`),优先级低。

---

## 4. 接表 SOP 升级:preflight 体检 + cron 安全闸(本轮新增)

把过去"在 prod 真跑→看炸什么→修"收敛成**"接表前一键体检 + 未验证的表 cron 不碰"**:

**preflight 体检**(`scripts/preflight_mapping.py` / `Preflight mapping` workflow):复用真 `transform_row` + FeishuClient **只读飞书、不写库、不调 LLM**,一屏报出:未声明列(标出"其中多少行有正文=真笔记会丢")· 品类是否在受控闭集 · 入库投影(upsert/空占位/丢) · tier/intent 分布 · 方向是否全部命中拆解。退出码 1=有阻断问题。

**cron 安全闸**(`sync_interval` 现在**真生效**):
- 新表填坐标后**留 `on_demand`** → 夜间 02:00 cron **不碰它**(防 preflight 验证前被自动灌)。
- 显式 `Daily TV sync`(填 project)/ 本地手跑 → 照常跑(不挡人工)。
- 验证 OK 后把 `sync_interval` 改 **`daily`** → 才入夜间 cron。活跃项目(WTG/NRT_2/NUC/NRT_3)均已 `daily`。

**接新表完整流程**:填 `sync_config` 坐标(留 `on_demand`)→ **preflight** → 按报告补 `raw_extra` 白名单 → PR 合 → **显式** `Daily TV sync`(全名,先 dry_run)→ 实跑验证 → **改 `daily`** 入 cron → essence 自动 drain。

---

## 5. 本轮(Session #18)做了什么 + 决策

### 上线
- **NUC_phase1(保健品)+ NRT_phase3(OTC药)上线**:飞轮 2→4 项目,+69 篇真爆款燃料。NRT_3 走新 preflight SOP、零 prod 试错。
- **通道2 production 拉通**:确认 autowriter 真在调馆员、注入飞轮经验卡(§2)。

### 根治的 bug(NUC 首个大规模 sub_direction 表逼出来,均通用修复)
| 坑 | 修 |
|---|---|
| essence 单条抽风(`failed_after_retry`)拖红整 sync | `_exit_code_for_stats` 仅全军覆没/hygiene 才红(对齐 curate #56) |
| sub_direction 翻倍 LLM → Railway 5min 超时 502 | `ESS_REQ_MAX` 15→8 |
| 502 非 JSON body 让 `ok=$(jq)` 在 bash -e 下 exit 5 崩 | `jq … \|\| echo false` 守卫 |
| 超时/抽风把整 sync 拖红 | essence 批级容忍 + curate transient 容忍;`worker_fail_kind` 据 curl 退出码区分**瞬时(超时/网关)vs 系统性(DNS/拒连/URL错/4xx)** |
| 空关联/评论碎片行逐条刷 445 行 WARNING | 正向 `_NOTE_DATA_SIGNALS` 判据,空占位静默收成一行汇总 |

### 设计-代码缺口补齐
- **D-009** surface 三级时间衰减:注入视图 recency 线性→三级指数(`notes_v1_7`,**已 apply prod**)。
- **R-031** 飞书 autowriter 回灌 lineage 列 → notes FK(`transform_row`,**已解决**)。
- **preflight + cron 闸**(本轮 SOP 核心)。

### 决策(DECISIONS)
- **D-039**:`essence_annotation_mode` 放宽为 nullable(合理偏离 D-017)。
- **D-040** ⭐:负面信号只取人工标注、`趴` 不可作负面源(正负不对称)+ 跨产品避坑特征方向(roadmap)。**D-027 Implications 追加同款推理。**

### 本轮 PR
#62 NUC 接入 · #63 D-009/R-031/D-039+essence worker 容忍 · #64 essence Railway 稳健 · #65 curate transient · #66 preflight 工具+碎片静默 · #67 NRT_3+Preflight workflow+cron 闸 · #68 NRT_3 补声明 观众分析 · #69 NRT_3 入 cron + 文档刷新。

---

## 6. 待办 / 路线图(按优先级)

- **P1 · 灌更多真燃料**:接表已被 preflight + cron 闸去险,后续表照 §4 SOP 走即可。
- **P2 · L3 受众层**(最大的"设计齐全、代码空"):**落地方案见 [docs/23](23-L3-audience-layer-plan.md)**。摸底结论:推断**已有**(essence 副产品,1042 条满 profile),**真实蒲公英数据基本没拉进来**(观众分析列大多「无」)。→ **先做 Phase 1 D-013 不符检测**(纯代码、688 条现成、立刻抓人工标错的受众、把 `audience_inferred` 从 0 拉起来);校准闭环卡在"先把真实 age/gender/city 拉进来"(ops 瓶颈,非代码)。**这是 L2 预测的输入前提。**
- **P3 · 设计-代码缺口**:D-009 surface 三级衰减虽 apply 但注入视图当前 0 行(push 退役、aw 走 pull),是 spec 摆正+预置;R-005 评论楼层重建;D-017 prompt 双模板(posthoc 未启用)。
- **P3 · 跨产品负面飞轮(D-040 roadmap)**:从人工标的干净负例萃取避坑特征,**不碰 `趴`**。优先级低于 L3。
- **P4 · 未来**:L2 Predictor(`prepublish_evaluations` 现空)· L4 Optimization。

### 并行新方向(Session #18 起头,独立于灌料/补层主线)
- **飞轮总看板(在线网站)** —— 见 **[docs/24](24-dashboard-plan.md)**。对外装逼 + 对内自监测,Vercel + Next.js + 共享 Supabase 照见 aw/tv/ssll(+未来去中心化)全生态。**Phase 0 骨架 + 扩展接口已落**(`dashboard/`,在 PR #69);Phase 1 上线需接入 Vercel + Supabase key。开新窗口接力从 docs/24 §9。
- **L3 受众层** —— 见 **[docs/23](23-L3-audience-layer-plan.md)**(同 P2)。

---

## 7. 不可违反的不变量 / 雷区(务必记住)

1. **LLM 调用必须在 Railway**(GitHub 连不上中转站,只触发);改 worker/librarian 代码要从 main 重新部署。
2. **essence(书架)慢衰减不硬切 / surface(ssll·注入)快衰减切老的**——别混;半衰期是 `0.5^(age/H)` 不是 `exp`。
3. **飞书 cell 可能是 list/dict**:任何拿 cell 做 dict-key/解析先展平(`_direction_key` / `_audience_text`)。
4. **接新表先 preflight**(看未声明列/品类/方向)→ 新表 `sync_interval` 留 `on_demand`(cron 不碰)→ 验证后改 `daily`。
5. **`数值推断`/synthetic 不进下游**;真爆款要有权威「状态字段」tier。
6. **负例只人工标、TV 不推负面、`趴` 不作负面源**(正负不对称,D-040)。**别再想"用趴做负面飞轮"。**
7. **TV 只送正面飞轮经验卡**;负面/避坑全在 AW 本地。
8. **调 Railway worker 的步骤(essence/curate)区分瞬时 vs 系统性失败**:瞬时(超时/网关/连接抖动)告警不拖红、系统性(配置/鉴权)才红。
9. **不往已合并分支推**;先合 PR 再从 main 跑。

---

## 8. 关键文件地图 + 运行手册速查

| 路径 | 作用 |
|---|---|
| `scripts/preflight_mapping.py` | ⭐ 接表前只读体检(投影 upsert/quarantine/分布) |
| `scripts/sync_feishu_notes_to_truth_vault.py` | 飞书→TV 入库(`transform_row` + cron 闸 `_skip_on_demand_on_cron` + lineage FK + 空占位判据) |
| `scripts/annotate_essence_pass.py` | essence 标注(`_exit_code_for_stats` 容忍)+ sub_direction(D-014) |
| `scripts/curate_flywheel_lessons.py` | 爆款→经验卡 |
| `scripts/extract_negative_examples_from_autowriter.py` | 挖 AW 历史负例**候选**(写 proposal,人工 UI 确认才算) |
| `librarian/core.py` | 通道2 拉取馆员(`fetch_candidates` / `library_version` 缓存键) |
| `schemas/notes_v1_4_flywheel_lesson_cards.sql` | 书架视图(essence 半衰期) · `notes_v1_7_*` 注入视图三级 surface 衰减 |
| `.github/workflows/{daily-sync,preflight,backfill-essence}.yml` | 心跳(含 cron 闸+worker 容忍) / 接表体检 / 灌 essence |
| `autowriter-migrations/005_*.md` | aw 负例审核 tab spec(已在 aw 端实现) |
| `DECISIONS.md` / `RISKS.md` | 决策考古层 / 风险登记 |

- **接新表**:见 §4(填坐标留 on_demand → preflight → 补白名单 → 合 → 显式 sync 验证 → 改 daily)。
- **查飞轮**:`SELECT * FROM truth_vault.v_flywheel_sync_status;` · 书架 `count(*) FROM flywheel_lesson_annotations` · 馆员流量 `SELECT * FROM flywheel_librarian_cache`。
- **接馆员自测**:docs/19 §自测 curl。

---

## 9. 文档阅读路线(新人无弯路)

`README`(宪法)→ `docs/00-START-HERE`(总入口 + §6 过时描述清单)→ `docs/01`(三层架构 why)→ **本篇 `docs/22`(当前状态最新权威)** → 按需深入(`14` 馆员 / `04` 接表 SOP / `DECISIONS` D-040 负面 / `07` 受众层)。

> docs/20/21 是更早的历史快照(NRT_2 上线前/那轮);**当前状态以本篇为准**。

---

_本交接覆盖到 2026-06-05 Session #18:4 项目入库(2478 篇 / 96 真爆款 / 87 经验卡)、接表 SOP 升级(preflight + cron 闸)、
通道2 production 拉通、负面机制澄清(D-040)。下一步重心:L3 受众层 → L2 预测。管道扎实,往前是"补层"。_
