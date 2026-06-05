# 00 · START HERE — Truth Vault 从零到现在的完整对齐

> **第一次接手就从这里读。** 读完这一篇,你能把"项目为什么存在 → 核心设计内核 → 每一轮迭代
> → 当前状态"整条线串起来,并且**不会被仓库里的过时描述带偏**(§6 专门列了哪些说法已作废)。
>
> 这份文档是**地图**;详细内容在它指向的各篇 docs(§9 索引)。`README.md` 是**项目宪法**
> (定义 TV 是什么 / 不是什么 / 不可违反的原则),本文是**阅读路线 + 演进脉络**,二者互补。
>
> **推荐阅读顺序**:本文 §1-§2 → `README.md`(宪法) → `docs/01`(三层架构的 why) →
> 本文 §4(演进时间线)→ `docs/21`(当前状态最新快照)→ 按需深入。

---

## 1. 一分钟理解 Truth Vault

- **帆谷** = 做小红书**种草投放**的公司。一次次投放,有的笔记"爆"(高互动)、有的"趴"。
- **Truth Vault(TV)** = 帆谷的**私有数据基础设施**:把每次投放的**真实结果沉淀**下来,让
  "什么内容会爆、为什么"成为**有数据支撑的事实判断**,而不是个人经验直觉。
- **目标 = 数据飞轮**:发得越多 → 库越准 → 判断越精 → 后续命中率越高。
- **TV 不生产内容**。它把"真实爆款经验"**回流**给两个现存的生产系统(见 §2.4),让它们写得更准。
- **不是什么**(边界,详见 README):不是内容生产工具 / 不是 BI 仪表板 / 不是 MMM / 不是实时归因 /
  不是通用 KOL 库(只存帆谷投过的笔记)。

---

## 2. 核心设计内核(先把这 4 个心智模型建对,后面才不会乱)

### 2.1 三层数据:Surface / Essence / Audience(D-001,最深的设计洞察)

单层数据库(只存文案 + 互动 + embedding)**注定 6-12 个月后失效** —— 因为不同层信息的**时间衰减速度不同**:

| 层 | 是什么 | 例子 | 时间衰减 |
|---|---|---|---|
| **Surface 表层** | 字面表达:词汇、句式、平台话术、热点/明星引用 | "刷到郁可唯新综艺…" | **快**(半衰期 6 个月) |
| **Essence 内核** | 触发反应的根本机制:情绪杠杆、人性原型 | "35+ 女性'不要被写成可怜样子'的自我形象焦虑" | **几乎不衰减**(半衰期 5 年)= **穿越周期** |
| **Audience 受众** | 谁会共鸣:人群画像 | 30-45 中年女性 / 形象焦虑 | 中(半衰期 2.5 年) |

**为什么分层**:两个 surface 完全不同的项目(力克雷戒烟 ↔ 花西子粉饼),essence 可以高度对称
("自我形象焦虑 + 被他人评价"),从而**跨产品策略迁移**。这是飞轮复利的真正来源。详见 `docs/01`。

### 2.2 穿越周期:按层不同半衰期衰减(这条最容易被实现写错,见 §6)

检索/排序时,每条历史样本的权重**按层独立衰减**(`docs/01` + `docs/05:371`):
```
surface_weight  = 0.5 ** (age_months / 6)    # 半衰期 6 个月
essence_weight  = 0.5 ** (age_months / 60)   # 半衰期 5 年 —— 几乎不衰减
audience_weight = 0.5 ** (age_months / 30)   # 半衰期 2.5 年
```
**老数据 surface 几乎归零,但 essence 几乎全部保留 —— 这就是"穿越周期"的算法机制。**
→ 书架(经验卡 = essence)用 essence 慢衰减、**不硬切**;ssll/注入(消费 surface/审美)用快衰减 + 12 个月窗。

### 2.3 四层系统(D-019,把"数据"和"用数据"分清)

- **L1 · Core**:标注 + 存储(三层数据进库)。← **当前主力**
- **L2 · Predictor**:发布前预测(会不会爆)。← 未启用(`prepublish_evaluations` 空)
- **L3 · Persona-Critic-Human**:受众推断 + 校准。← **从没运行**(`audience_inferred = 0`)
- **L4 · Optimization**:优化回路。← 未来

### 2.4 双通道回流(通道1 push / 通道2 pull)+ ⚠️ 通道2 push 已退役

TV 把合格爆款回流到两个现存系统:
- **通道 1 · 三生六部(ssll)· push**:TV 直接 INSERT 进 `public.reference_samples`(证据包),
  ssll 的 `vibe_rewriter` 按 `platform+category` 检索注入。**喂的是仿写"审美"= surface。**
- **通道 2 · autowriter · pull(D-038)**:TV **不再** push 写 `autowriter.items`;改为把爆款策展成
  **经验卡**放进图书馆视图 `v_flywheel_lesson_cards`,autowriter 写稿时带 brief 调 **LLM 馆员服务**
  (`librarian/`,Railway)按相关性借阅,注入 prompt。**喂的是可迁移的钩子/结构/手法 = essence。**

> ⚠️ **通道2 的"push 写 autowriter.items"已退役(D-038)**;遗留脚本保留备查、未接进任何 workflow。
> 看到"TV push 进 autowriter.items"的描述 = 过时(见 §6)。

---

## 3. 技术栈(数据怎么流)

```
飞书投放表(数据源)
   │  onboard-table.yml(手动)──▶ Railway·onboarder ──▶ mappings/<proj>.yaml 草稿 PR(人审)
   │  daily-sync.yml(每日 02:00 UTC cron)
   ▼
Truth Vault(Supabase prod `kduysqedrclrfevrxiie` · schema truth_vault)
   notes ──(essence 标注/curate)──▶ flywheel_lesson_annotations(书架)──▶ v_flywheel_lesson_cards
   │                                                                              ▲
   ├─【通道1·push】爆/参考 ──▶ ssll reference_samples                              │【通道2·pull D-038】
   └─                                                       autowriter ◀── LLM 馆员(librarian/, Railway)
```
- **Supabase**(共享 prod,schema `truth_vault`/`autowriter`/`public`,PG17)· **Railway** 3 服务
  (librarian / onboarder / worker)· **GitHub Actions**(cron + 手动)· **中转站/NewAPI**(LLM 网关,
  `ANTHROPIC_BASE_URL`)· **飞书 OpenAPI**(数据源)。
- ⚠️ **LLM 调用必须在 Railway** —— GitHub Actions 海外 runner 连不上中转站(网络层)。GitHub 只触发。

---

## 4. 演进时间线(从最开始到现在 —— 看懂这条才不会拿旧设计当现状)

### 阶段 A · 设计期(D-001 ~ D-022)
三层 schema(D-001)、拒 RAG 当主检索(D-002)、"方向"字段拆解为多维(D-003)、按 intent 分轨训练
(D-012 ⭐)、受控词表(D-009)、audience 层(D-008)、四层系统(D-019)、raw_extra quarantine(D-021)…
确立了"数据资产"的全部结构。

### 阶段 B · 集成方案**三次转向**(最容易踩的历史包袱)
1. **D-023**:原设计 = TV 暴露 HTTP REST API,三系统主动调 `/v1/anchor/query`。→ **已废**。
2. **D-024**:改为**双通道直插**(push),最小化改造现存系统。
3. **D-038**:**通道2 再从 push 改为 pull / 图书馆 + LLM 馆员**(通道1 仍 push)。
→ **任何"三系统调用 TV 的 HTTP API""TV push 进 autowriter.items"的说法都过时。**

### 阶段 C · 建设期(Session #9 ~ #16,2026-05 ~ 06-02)
管道建成 + 三仓集成审计 + 共享 Supabase 迁移;**WTG_phase1 第一个项目 onboard**(Session #13);
**通道1 首次端到端打通**(Session #15,第一条「参考」进 ssll;落地 synthetic 分级);
**通道2 改 pull + LLM 馆员服务建成并上线 Railway**(Session #16,v1.4 书架 + v1.5 缓存 + `librarian/` +
策展 pass + cron 已开)。详见 `CURRENT_STATE.md`。

### 阶段 D · 上线 + 加固期(本轮,2026-06-04/05)⭐ 最新
- **NRT_phase2(力克雷,第 2 个项目)上线** —— 飞轮**第一次有真实燃料**:27 篇真爆款进库 + 全同步 ssll +
  全策展上架(书架 1→28 卡)。
- NRT_2 上线**一口气炸出 9 个潜伏 bug,全部根治**(品类未决议 / sync 假绿 / intent list 崩 / quarantine 索引 /
  漏声明列 / curate 抽风 / 观众分析静默丢 / vocab 闭集 / tier_threshold_override)。详见 `docs/21` §4。
- **最重要的设计回归**:书架 recency 之前误用 surface 的线性快衰减 + 1 年硬切,**违背 D-001 穿越周期**;
  已改回 **essence 半衰期 5 年、不硬切**(§2.2)。
- **全库审计**(4 路并行 agent):确认没有别处"代码做了和设计相反的事";高风险区全 honored;收尾文档/日志卫生。
- 产出本系列交接(`docs/20` → `docs/21` → 本文)。

---

## 5. 当前状态(快照;最新数字以 `docs/21` 为准)

- **2 个项目**:WTG_phase1(个护)· NRT_phase2(OTC药)。**1223 篇笔记**。
- **30 篇爆款**(WTG 3 = synthetic/数值推断,不进下游;**NRT_2 27 = 真实**)。
- **书架 28 张经验卡**;馆员(D-038 拉取)通道验证可用。
- essence 标了 825/1223(NRT_2 在 daily-sync 按 50/天 drain)。
- **L3 受众层从没运行**(`audience_inferred=0`);L2/L4 未启用。

---

## 6. ⚠️ 过时描述 / 易踩的错误心智(读到旧文档、旧注释、旧 PR 时别被带偏)

| 你可能看到的旧说法 | 真相 |
|---|---|
| "三系统调用 TV 的 HTTP REST API"(D-023) | **废**。改为双通道直插(D-024)+ 通道2 pull(D-038)。 |
| "通道2 push 写 `autowriter.items`"(D-024) | **退役**(D-038)。只剩通道1(ssll)是 push;通道2 是 pull/馆员。 |
| "书架按 `publish_time > now()-1年` 硬切 / 线性衰减" | **已改**。书架 = essence 半衰期 5 年指数衰减、**无硬切**(本轮回归 D-001)。 |
| "sub_directions LLM 子分类未实施"(R-006 旧文) | **已实施**(`annotate_essence_pass`)。 |
| "essence_annotation_mode 必填"(D-017) | 实际 schema **nullable**(sync 先插入、后标注;合理放宽)。 |
| daily-sync 的 `project` 填简称(如 `NRT_2`) | **必须填全名**(`NRT_phase2`)—— 填错会**静默空跑还报绿**。 |
| "essence 也按时间快衰减" | **不**。essence 穿越周期、几乎不衰减;只有 surface/审美快衰减。 |

---

## 7. 不可违反的不变量(违反 = 中途出错)

1. **LLM 调用必须在 Railway**(GitHub 连不上中转站);GitHub 只触发。
2. **essence(书架)慢衰减不硬切 / surface(ssll·注入)快衰减切老的** —— 别混。半衰期是 `0.5^(age/H)` 不是 `exp`。
3. **飞书 cell 可能是 list/dict**(多选/富文本):任何拿 cell 做 dict-key / 解析的地方都要先展平
   (`_direction_key`;观众分析用 `_audience_text` 空串拼接)。**写新字段解析时务必记住。**
4. **Railway 边缘单请求 ~5min 超时**:走边缘的长 LLM 调用每请求 ≤15 条;大表靠循环多轮。
5. **`数值推断` / synthetic 不进下游**:有意设计;真爆款入库要有权威「状态字段」tier。
6. **新表第一次 sync 后查 quarantine 的 `undeclared_field_names`**,把漏声明的列补进 raw_extra 白名单。
7. **不往已合并分支推**;先合 PR 再从 main 跑;改 worker/librarian 上跑的代码要从 main 重新部署才生效。

---

## 8. 运行手册 / 文件地图

详见 `docs/21` §8(文件地图)+ §9(运行手册速查)。最常用:
- **接新表(已有 mapping)**:填 `sync_config` 坐标 → **`python scripts/preflight_mapping.py <项目全名>`(只读体检)** → 按报告改 mapping → PR → 合 → `Daily TV sync`(填**全名**,先 dry_run)→ 实跑 → `Backfill essence`(batch=12)。
- **查飞轮状态**:`SELECT * FROM truth_vault.v_flywheel_sync_status;` · 书架厚度 `count(*) FROM flywheel_lesson_annotations`。

---

## 9. 全部文档索引(各篇一句话)

| 文档 | 一句话 |
|---|---|
| `README.md` | **项目宪法**:TV 是什么/不是什么/不可违反原则 |
| `DECISIONS.md` | **决策考古层**(D-001~D-038,只追加):每个决定的 What/Why/Rejected/Implications |
| `RISKS.md` | 风险登记(R-001~R-031;开着的 = 已知缺口) |
| `CURRENT_STATE.md` | 会话/迭代时间线(Session #9~#16) |
| **本文 `00`** | **总入口**:从零到现在的完整对齐 + 过时描述清单 |
| `01-architecture` | 三层架构的 **why**(最该先读的设计文档) |
| `02-schema-v1` | schema 字段落地 |
| `03-mapping-protocol` | A/B/C 家族字段映射协议 |
| `04-onboarding-sop` | 接新项目的 7 步 SOP(方向拆解 = 策略 lead 拍板) |
| `05-controlled-vocab` | 受控词表(情绪杠杆/人性原型/tier/category/**衰减谱**) |
| `06-essence-annotation` | essence 标注协议(Mode A/B label-leakage 隔离) |
| `07-audience-data` | 受众层设计(**注:L3 尚未运行**) |
| `08-evolution-roadmap` | 演进路线图 |
| `09-system-integration` | 与 ssll/autowriter 的集成 |
| `10-sister-repo-followups` | 跨仓待办(R-031 等) |
| `11-feishu-table-setup` | 飞书建表指南 + 怎么拿 app_token/table_id + 授权机器人 |
| `12-daily-sync-troubleshooting` | daily-sync 排错(连库失败 5 步全挂的根因) |
| `13-flywheel-activation-runbook` / `13-integration-status` | 飞轮激活手册 / 集成状态 |
| `14-channel2-pull-librarian` | 通道2 pull + 馆员设计(D-038) |
| `15-autowriter-librarian-integration` | autowriter 接馆员的详细说明 |
| `16-onboarding-agent` / `17-onboarder-status-handoff` | 接表 agent 设计 / 状态交接 |
| `18-codebase-audit-2026-06-04` | 一次全库审计报告 |
| `19-autowriter-librarian-quickstart` | autowriter 接馆员快速接入 + 自测 |
| `20-handover-2026-06-04` | 上线**前**的交接快照(历史) |
| **`21-handover-2026-06-05`** | **当前状态权威交接**(NRT_2 上线 + 审计后) |
| `99-rejected-ideas` | 否决过的想法(别重复提) |

---

_本入口写于 2026-06-05。当前里程碑:2 项目入库、飞轮首批真燃料(NRT_2 27 爆款)、穿越周期衰减回归 D-001、
全库审计完成。下一步重心(见 `docs/21` §5):接 NRT_3/NUC 灌料 → L3 受众层 → L2 预测。_
