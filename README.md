# Truth Vault · 帆谷种草决策飞轮

> 这个文档分两半。**上半是项目宪法**（定位 / 边界 / 三个原则）—— 一旦定稿不轻易修改。
> **下半是当前事实**（跑了多少数据、有哪些闸、目录长什么样）—— 每次大变动后更新。
> 读的时候注意区分：宪法是"不能违反的"，事实是"现在是这样的"。

> 🧭 **第一次接手?** 先读 **[docs/00-START-HERE.md](docs/00-START-HERE.md)** —— 从零到最新迭代的完整对齐
> （含"过时描述清单"，避免被旧文档带偏）。

---

# 上半 · 项目宪法

## 一句话定位

Truth Vault 是帆谷的私有数据基础设施 —— 把每一次小红书种草投放的真实结果沉淀下来，让"什么内容会爆、为什么"成为有数据支撑的事实判断，而不是经验直觉。

## 项目目标

让发的越多 → 数据库越准 → 判断越精 → 后续投放命中率越高 —— 形成数据飞轮。

具体来说，Truth Vault 把真实爆款回流到两个现存系统的飞轮注入点 —— 通道 1 直接 INSERT（push，D-024），通道 2 改为写稿时 pull（D-038）；都不是 HTTP RPC：

1. **sanshengliubu（三省六部）** —— Truth Vault 写入 `public.reference_samples`（v2 "证据包" 列：`post_title` / `post_body` / `top_comments` / `ai_analysis` / `quality_score`），sanshengliubu 的 `vibe_rewriter` 按 `platform + category` 检索并注入到 prompt 高权重位
2. **autowriter（内容工作台）** —— **通道 2 已由 push 改为 pull（D-038）**：TV 不再写 `autowriter.items`，而是把合格爆款策展成"经验卡"放进图书馆视图 `truth_vault.v_flywheel_lesson_cards`；autowriter 写稿时带 brief 调 **LLM 馆员服务**（`librarian/`，Railway）按相关性借阅，注入 system prompt 的 P2 会话层。〔历史 push 路径（写 `autowriter.items`，`example_label='positive'`）已退役，脚本保留备查〕
3. **去中心化写手网络（未来阶段）** —— 写手网络 codebase 尚未启动；规划是写手提交时由 TV 提供"这条相比历史爆款的差异点"诊断（具体集成模式待设计）

> ⚠️ v1 spec（D-023）曾设计为 HTTP REST API，要求三个系统主动调用 TV 的 `/v1/anchor/query` 等端点；Session #7 后改为双通道直插模式（D-024）以最小化对现存系统的改造；其后 D-038 又把**通道 2 从 push 改为 pull + LLM 馆员**（通道 1 仍为 push）。任何"三个系统调用 Truth Vault 的 HTTP API"的描述都属于过时表述。

## 不解决什么（边界）

Truth Vault **不是**：

- ❌ 内容生产工具（生产由 sanshengliubu / autowriter 做）
- ❌ 客户面向的 BI 仪表板（虽然底层数据可以服务这个，但不是首要目标）
- ❌ MMM（媒介组合模型，那是 Robyn / LightweightMMM 的领域）
- ❌ 实时归因系统（不是 Adjust / AppsFlyer）
- ❌ 通用 KOL 数据库（不存储非帆谷投放过的笔记）

Truth Vault **永远不会**：

- ❌ 自动替人类做最终判断（"管家不做判断"是核心原则）
- ❌ 用单一字段编码多维信息（"方向"字段拆解为多维是核心教训）
- ❌ 只学表层模式而不学内核（三层架构是核心架构）

## 三个绝对不能违反的设计原则

### 原则 1：管家做查询，不做判断（Layer 1）

智能管家的"智能"只能用在元层 —— 用什么数据、怎么查、怎么对比。**Truth Vault Core (Layer 1) 不允许做内容质量判断**。

注意"管家不做判断"严格指 Layer 1。整个系统四层架构中（[docs/09-system-integration.md](docs/09-system-integration.md)）：

- **Layer 1 · Truth Vault Core**: 只存数据 / 出 anchor（管家在这里）
- **Layer 2 · Predictor**: 基于模型输出 P(爆) / 风险分（D-012 按 intent 分轨）
- **Layer 3 · Persona / Critic / Human**: 最终内容判断
- **Layer 4 · Optimization**: prompt 方向反推

判断权由 Layer 3 持有，Layer 2 提供结构化预测，Layer 1 提供事实。

参见: [docs/01-architecture.md](docs/01-architecture.md) · [docs/09-system-integration.md](docs/09-system-integration.md) · DECISIONS D-004, D-019

### 原则 2：三层架构（Surface / Essence / Audience）

每条数据必须在三层独立标注：

- **Surface（表层）** —— 字面词汇、当代语言、平台话术（衰减半衰期 6-12 个月）
- **Essence（内核）** —— 情绪杠杆、人性原型（几乎不衰减）
- **Audience（受众）** —— 推断的目标受众画像（变化慢但确实在变）

不允许把这三层混在一个字段里。混了之后跨时间、跨产品的迁移性就被锁死。

参见: [docs/01-architecture.md](docs/01-architecture.md)

### 原则 3：取上得中

Schema 起点决定上限。在 v1 第一版就要包含 essence 层和 audience 层字段，**即使一开始填不满**。后期补不进去 —— 因为历史数据需要回标，标注的人换了一拨，质量一致性出问题。

参见: [docs/02-schema-v1.md](docs/02-schema-v1.md)

## 工程栈

跟现有帆谷工具链对齐，不开新栈：

- **数据库**: Supabase Postgres（跟 sanshengliubu 一致）
- **导入器**: 飞书 OpenAPI（lark-oapi）
- **调度**: GitHub Actions（夜间 cron）
- **常驻服务**: Railway（`librarian/` 馆员 · `worker/` essence+curate · `onboarder/` 接表）
- **看板**: Vercel（`dashboard/`）
- **API 网关**: NewAPI / OneAPI（统一 LLM 调用入口）
- **向量索引**: pgvector（阶段 3 启用，尚未启用）

## 进化路径

四阶段，每阶段都有独立 ROI，不强依赖后续阶段：

| 阶段 | 数据门槛 | 方法 | 状态 |
|---|---|---|---|
| 1·描述性 anchor | 几百条 | SQL + LLM 标签 | ✅ 在跑 |
| 2·判别式分类 | 1k+ | LightGBM tabular | 数据量已过线，未启动 |
| 3·语义融合 | 5k+ | BERT + LightGBM stacking | 数据量刚过线，未启动 |
| 4·因果评估 | 20k+ | CATE / Causal Forest | 远未到 |

参见: [docs/08-evolution-roadmap.md](docs/08-evolution-roadmap.md)

---

# 下半 · 当前事实（2026-09-16）

## 数据现状

| | |
|---|---|
| 笔记总数 | **5,949** |
| 项目数 | **16**（9 个进夜间 cron，7 个 on_demand） |
| 爆款（爆 + 大爆） | 373 |
| 已 essence 标注 | 5,714（96%） |
| 已推三生六部 | 606 |
| 有真实受众数据 | 1,104 |

### 按项目

| 项目 | 品牌 | 品类 | 笔记 | 爆款 | 夜间 cron |
|---|---|---|---|---|---|
| RIO_phase1 | RIO | 酒类 | 802 | 32 | ✅ |
| WTG_phase1 | waytogo | 个护 | 724 | 3 | ✅ |
| NUC_phase1 | 大象集团 | 保健品 | 657 | 85 | on_demand（已停更） |
| NRT_phase3 | 力克雷 | OTC药 | 598 | 44 | on_demand（已停更） |
| NRT_phase2 | 力克雷 | OTC药 | 499 | 42 | on_demand（已停更） |
| SPX_phase1 | SPORTSIX | 保健品 | 488 | 29 | ✅ |
| LNKT_phase1 | 雷诺考特 | OTC药 | 374 | 1 | ✅（唯一抖音表） |
| OKMAN_phase1 | OKMAN | 处方药 | 346 | 37 | ✅ |
| XIWU_phase1 | 西屋 | 家居家电 | 301 | 11 | ✅ |
| HXZ_QD | 花西子 | 美妆 | 202 | 6 | on_demand |
| ANSHEN_phase1 | 岸深 | 个护 | 199 | 2 | ✅ |
| HXZ_FB | 花西子 | 美妆 | 192 | 15 | on_demand |
| BJS_phase1 | 百健士 | 保健品 | 182 | 4 | ✅ |
| TGV_phase1 | TGV | 保健品 | 144 | 14 | on_demand（已停更） |
| TXQ_phase1 | 唐小轻 | 食品饮料 | 127 | 9 | on_demand |
| TUGE_phase1 | 途鸽 | 教育 | 114 | 39 | ✅ |

> `on_demand` = 夜间 cron 跳过（D-047），要手动 `workflow_dispatch` 才跑。
> "已停更" = 源表最后一条笔记超过 3 个月，不再指望有新数据。

## 入库闸 —— 读代码前先读这一段

从 6 月到 9 月，**这个仓库新增最多的不是功能，是闸**。原因：飞书表是运营在手改的，
列会被加、被改名、被清空，而每一种都能静默污染库。这些闸决定了「什么数据进得来、
什么时候算这一轮跑完整了」，改同步脚本之前必须先理解它们。

| 闸 | 管什么 | 出事时的表现 |
|---|---|---|
| **未声明列吸收**（D-055） | 运营新加的列 → 值收进 `raw_extra._undeclared`，**行照常入库** | 收尾一条 `::warning` 列出新列名 |
| **核心列消失**（D-055 反向闸） | `field_mapping` 的键整轮没返回，**且它以前填过** | 红，并点名"像不像改名" |
| **要害字段自检**（D-056） | 整轮产不出某个必备字段（三个指标 / tier / 发布时间 / 内容形态 / 账号） | 红，**不给认领**，红到运营改表为止 |
| **行级隔离**（D-021 / D-052） | 缺正文、抖音行找不到可继承的文案 | 进隔离表；人认领过的转黄（D-053） |
| **对账闸**（D-058） | 没处理成的行里**有没有库里已存在的 note** | 有 → 不盖戳不对账；没有 → 照常对账 |

三条口径值得单独记住：

- **非核心列加了就收着**（owner 定）—— 一个没声明的列不该把整行挡在外面。翻这道闸之前，OKMAN 一列丢过 346 行、ANSHEN 一族列丢过 268 行。
- **要害字段整列空 = 直接红，不给认领** —— 同步跑绿但项目在看板上等于不存在，这种绿比红更坏。
- **「反馈链接」是全库标准列名**（owner 2026-09-16）—— 落后的表把新名**并列声明**成别名，运营改名时同步无感。

⚠️ **改这些闸之前先读 [DECISIONS.md](DECISIONS.md) 的 D-046 ~ D-059**。每一条都是某天夜跑连红换来的，
并且每一条都有 CI 守卫钉着 —— 守卫断的是**行为**不是源码字符串，改错了会立刻红。

## CI 与守卫

`.github/workflows/ci.yml` 里有 **52 个纯 Python 守卫块**，多数直接驱动真的 `main()` 循环。

本仓的守卫纪律（来自 D-051 的教训）：

1. **断行为，不断源码字符串**。断 `assert "xxx" in src` 那种，判据一重构就变空跑。
2. **每条守卫都要反证**：把修复回退掉，确认它**真的会红**，而且红在对应那条断言上。
3. **写了分支就得有用例真的走进去**，否则那段代码是没人验过的。

> 这三条不是形式主义。9 月里有两次是反证才发现守卫是空跑的：一次是 truthy 断言在值退化时照样过，
> 一次是 fixture 根本没走到新写的分支。

## 六个 workflow

| 文件 | 触发 | 干什么 |
|---|---|---|
| `daily-sync.yml` | 每日 cron（**实际 06:56~07:30 UTC 触发**，非 cron 里写的 02:00） | 飞书→TV / 评论 / essence / 策展 / 通道1 / 回流 |
| `ci.yml` | push + PR | 52 守卫 + SQL apply + yaml lint |
| `preflight.yml` | 手动 | 接新表前的只读体检 |
| `onboard-table.yml` | 手动 | 批量接表 |
| `backfill-essence.yml` | 手动 | essence 补标 |
| `gateway-probe.yml` | 定时 | LLM 网关连通性 |

## 目录结构

```
truth-vault/
├── README.md                ← 本文件 · 宪法 + 当前事实
├── ONBOARDING.md            ← 新人第一周 checklist ⭐ 第一次接手必读
├── IMPLEMENTATION_GUIDE.md  ← 部署 + 集成实操手册
├── CURRENT_STATE.md         ← 当前进度快照 + 延后清单
├── DECISIONS.md             ← 决策日志 D-001 ~ D-059（只追加）⭐ 改任何闸之前必读
├── RISKS.md                 ← 生产风险登记
├── MIGRATION_PLAN.md        ← 跨库迁移计划
│
├── .github/workflows/       ← 6 个 workflow（见上表）
├── docs/                    ← 29 篇设计文档（00 是入口，99 是弯路存档）
├── schemas/                 ← 20 个 SQL：notes_v1_2 ~ v1_10 + dashboard_views_v1~v6 + 安全补丁
├── mappings/                ← 每项目一份 yaml（16 个项目 + _template）
├── prompts/                 ← LLM prompt 库（essence / audience）
├── scripts/                 ← 20+ 个 Python 脚本，见 scripts/README.md
│   ├── sync_feishu_notes_to_truth_vault.py   ← ⭐ 主入口：飞书 → TV，所有入库闸都在这
│   ├── _common.py                            ← 共享工具（client / mapping / 分页 / 隔离表）
│   ├── preflight_mapping.py                  ← 接表前只读体检（投影真 sync 行为）
│   ├── annotate_essence_pass.py              ← LLM 标注独立 pass（D-028）
│   ├── curate_flywheel_lessons.py            ← 策展经验卡上架（通道 2）
│   └── sync_truth_vault_baokuan_to_sanshengliubu.py  ← 通道 1
│
├── librarian/               ← Railway · LLM 馆员服务（通道 2 pull）
├── worker/                  ← Railway · essence 标注 + 策展
├── onboarder/               ← Railway · 接表 agent
├── dashboard/               ← Vercel · 三界面看板
│
├── sanshengliubu-patches/   ← 通道 1 集成包（部署到 ssll 仓库）
├── autowriter-migrations/   ← 通道 2 集成包（部署到 autowriter 仓库）
└── data-analysis/           ← 项目数据审计
```

## 文档导航

### 第一次接手

| 顺序 | 文件 | 用途 |
|---|---|---|
| 0 ⭐⭐ | [docs/00-START-HERE.md](docs/00-START-HERE.md) | **从零到最新的完整对齐**（含过时描述清单） |
| 0 ⭐ | [ONBOARDING.md](ONBOARDING.md) | 第一周 checklist + 找谁要凭证 + FAQ |
| 1 | 本文件 | 边界、原则、当前事实、入库闸 |
| 2 | [CURRENT_STATE.md](CURRENT_STATE.md) | 当前 scope + 已知 gap + 延后清单 |
| 3 ⭐ | [DECISIONS.md](DECISIONS.md) | D-001 ~ D-059 · **改任何东西之前必读** |
| 4 ⭐ | [docs/09-system-integration.md](docs/09-system-integration.md) | 双通道集成（核心理论） |
| 5 | [docs/01-architecture.md](docs/01-architecture.md) | 三层架构 |
| 6 | [RISKS.md](RISKS.md) | 生产前会咬人的事 |

### 运营 / 接新表

| 文件 | 用途 |
|---|---|
| [docs/11-feishu-table-setup.md](docs/11-feishu-table-setup.md) ⭐ | **建飞书表入口** · 建哪些列 + 拿凭证 + 避坑 |
| [docs/04-onboarding-sop.md](docs/04-onboarding-sop.md) | 新项目接入 SOP |
| [docs/03-mapping-protocol.md](docs/03-mapping-protocol.md) | 飞书 → DB 映射协议 + schema 家族 |
| [mappings/_template.yaml](mappings/_template.yaml) | 新项目 mapping 模板（已是「反馈链接」口径） |
| [docs/12-daily-sync-troubleshooting.md](docs/12-daily-sync-troubleshooting.md) | 夜跑红了怎么查 |

### 部署 / 实施

| 文件 | 用途 |
|---|---|
| [docs/02-schema-v1.md](docs/02-schema-v1.md) | schema 字段级详解 |
| [scripts/README.md](scripts/README.md) | 脚本的部署 + cron + 故障排查 |
| [sanshengliubu-patches/README.md](sanshengliubu-patches/README.md) | 通道 1 集成 patch |
| [autowriter-migrations/RUNBOOK.md](autowriter-migrations/RUNBOOK.md) | 通道 2 + schema 迁移 |
| [docs/14-channel2-pull-librarian.md](docs/14-channel2-pull-librarian.md) | 馆员服务设计 |

### 数据 / 标注

| 文件 | 用途 |
|---|---|
| [docs/05-controlled-vocab.md](docs/05-controlled-vocab.md) | 受控词表 v0.2 |
| [docs/06-essence-annotation.md](docs/06-essence-annotation.md) | LLM 标注双模式协议 |
| [docs/07-audience-data.md](docs/07-audience-data.md) | 蒲公英真实 audience 接入 |
| [docs/23-L3-audience-layer-plan.md](docs/23-L3-audience-layer-plan.md) | L3 受众层计划 |
| [prompts/](prompts/) | prompt 文本 |

### 历史 / 演化

| 文件 | 用途 |
|---|---|
| [docs/08-evolution-roadmap.md](docs/08-evolution-roadmap.md) | 4 阶段路径 |
| [docs/99-rejected-ideas.md](docs/99-rejected-ideas.md) | 走过的弯路 |
| [docs/26-handover-2026-06-09.md](docs/26-handover-2026-06-09.md) | 最近一次完整交接（6 月） |
| [data-analysis/10-project-audit.md](data-analysis/10-project-audit.md) | 10 项目数据审计（schema 的由来） |
| [data-analysis/l2-feasibility.md](data-analysis/l2-feasibility.md) | L2 可行性实测（9/16，含复现 SQL） |
| [data-analysis/signal-definitions.md](data-analysis/signal-definitions.md) | **信号定义与标签污染实测**（9/16，读 L2 之前先读这个） |

## 现在在哪 / 下一步

✅ **飞轮在转**：16 个项目 5,949 篇入库，9 个每晚自动同步；通道 1（ssll）+ 通道 2（pull/馆员）都 live；essence 标注覆盖 96%。

✅ **入库这一层基本稳了**：9 月密集补了 D-046 ~ D-059 一整套闸。现在运营改表的三种形态（加列 / 改名 / 清空）都能被正确分流 —— 加列不拖行、改名点名、要害字段空了直接红。

🚧 **还欠着的**：

- **L2 预测层从没启动** —— 数据量早就过了 1k 门槛，9/16 做过一次实测（[l2-feasibility.md](data-analysis/l2-feasibility.md)）：
  留一项目验证 AUC ≈ 0.61，能稳定挑出最差的 20%（爆率 3.4% vs 基线 6.8%），但挑不准最好的 20%。
  **别急着搭服务** —— 实测里「负面情绪撬动 vs 正面共鸣」项目内差 3–6 倍，这条规律本身不用模型就能交付。
- **标签有 21% 是污染的** —— 373 个爆款里 79 个来自刷评 / 数值推断 / 运营手标的伪爆贴，
  见 [signal-definitions.md](data-analysis/signal-definitions.md)。清洗后 AUC 0.612 → 0.624。
- **投流数据全库不存在** —— 区分不了「内容差」和「没获得曝光机会」，这是运营侧要加的列。
- **L3 受众层只有 1,104 条有真实数据**（19%），其余靠推断。
- **SPX 27 条「抖音接抖音」笔记进不来** —— owner 定了不修，那批笔记的文案归属说不清。
- **pgvector 未启用**，阶段 3 语义融合没开始。

📋 **下一步优先级**：数据量已经够喂 L2 了，闸也稳了 —— 瓶颈从"数据进不来"转移到"没人用这些数据做预测"。

## 项目维护者

- **策略 / 决策**: Ziao
- **开发**: 待定
- **AI 协作**: Claude (Anthropic) 通过多个会话窗口持续协作

---

> 📌 **给下一个接手的人**：这个仓库最贵的东西不是代码，是 [DECISIONS.md](DECISIONS.md) 里 59 条
> "为什么当初那么做"。每一条 Rejected 段都是真的试过或者真的算过。改任何闸之前先翻它，
> 大概率你想到的方案已经被试过并且记了为什么不行。
