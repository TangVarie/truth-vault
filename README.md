# Truth Vault · 帆谷种草决策飞轮

> 这个文档是项目宪法。它定义了 Truth Vault 是什么、不是什么、以及绝对不能违反的设计原则。一旦定稿不轻易修改。

> 🧭 **第一次接手?** 先读 **[docs/00-START-HERE.md](docs/00-START-HERE.md)** —— 从零到最新迭代的完整对齐
> (含"过时描述清单",避免被旧文档带偏)。最新当前状态见 **[docs/21](docs/21-handover-2026-06-05.md)**。
> 本 README 是**稳定的设计宪法**(原则/边界);"现在跑到哪了"以 docs/00 + docs/21 为准。

## 一句话定位

Truth Vault 是帆谷的私有数据基础设施 —— 把每一次小红书种草投放的真实结果沉淀下来，让"什么内容会爆、为什么"成为有数据支撑的事实判断，而不是经验直觉。

## 项目目标

让发的越多 → 数据库越准 → 判断越精 → 后续投放命中率越高 —— 形成数据飞轮。

具体来说，Truth Vault 把真实爆款回流到两个现存系统的飞轮注入点 —— 通道 1 直接 INSERT（push，D-024），通道 2 改为写稿时 pull（D-038）；都不是 HTTP RPC：

1. **sanshengliubu（三省六部）** —— Truth Vault 写入 `public.reference_samples`（v2 "证据包" 列：`post_title` / `post_body` / `top_comments` / `ai_analysis` / `quality_score`），sanshengliubu 的 `vibe_rewriter` 按 `platform + category` 检索并注入到 prompt 高权重位
2. **autowriter（内容工作台）** —— **通道 2 已由 push 改为 pull（D-038）**：TV 不再写 `autowriter.items`，而是把合格爆款策展成"经验卡"放进图书馆视图 `truth_vault.v_flywheel_lesson_cards`；autowriter 写稿时带 brief 调 **LLM 馆员服务**（`librarian/`，Railway）按相关性借阅，注入 system prompt 的 P2 会话层。〔历史 push 路径（写 `autowriter.items`，`example_label='positive'`）已退役，脚本保留备查〕
3. **去中心化写手网络（未来阶段）** —— 写手网络 codebase 尚未启动；规划是写手提交时由 TV 提供"这条相比历史爆款的差异点"诊断（具体集成模式待 Sprint 2+ 设计，可能继续走双通道也可能加只读 RPC）

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
- **服务**: FastAPI（Python）
- **API 网关**: NewAPI / OneAPI（统一 LLM 调用入口）
- **内部 UI**: Streamlit
- **导入器**: 飞书 OpenAPI（lark-oapi）
- **向量索引**: pgvector（阶段 3 启用）

## 进化路径

四阶段，每阶段都有独立 ROI，不强依赖后续阶段：

| 阶段 | 数据门槛 | 方法 | 时长 |
|---|---|---|---|
| 1·描述性 anchor | 几百条 | SQL + LLM 标签 | 2-3 个月 |
| 2·判别式分类 | 1k+ | LightGBM tabular | +3-6 个月 |
| 3·语义融合 | 5k+ | BERT + LightGBM stacking | +9-12 个月 |
| 4·因果评估 | 20k+ | CATE / Causal Forest | +18+ 个月 |

参见: [docs/08-evolution-roadmap.md](docs/08-evolution-roadmap.md)

## 完整目录结构

```
truth-vault/
├── README.md                          ← 本文件 · 项目宪法 (30 秒上手)
├── ONBOARDING.md                      ← 新人第一周 checklist ⭐ 第一次接手必读
├── IMPLEMENTATION_GUIDE.md            ← 部署 + 集成实操手册 ⭐ 动手前必读
├── CURRENT_STATE.md                   ← 当前进度快照 · Sprint 0 scope
├── DECISIONS.md                       ← 决策日志 D-001 ~ D-038 (只追加)
├── RISKS.md                           ← 生产风险登记
│
├── .github/workflows/                 ← CI (Python compile + SQL apply + yaml lint)
│   └── ci.yml
│
├── docs/                              ← 设计文档
│   ├── 01-architecture.md             ← Surface/Essence/Audience 三层架构论证
│   ├── 02-schema-v1.md                ← v1.2 schema 详解 (字段级)
│   ├── 03-mapping-protocol.md         ← 飞书 → DB 映射 + 3 家族 schema
│   ├── 04-onboarding-sop.md           ← 新项目 7 步接入 SOP
│   ├── 05-controlled-vocab.md         ← 词表 v0.2 (lever 12/archetype 19/...)
│   ├── 06-essence-annotation.md       ← LLM 双模式标注协议 (D-017/D-028)
│   ├── 07-audience-data.md            ← 蒲公英真实 audience 数据接入
│   ├── 08-evolution-roadmap.md        ← 4 阶段进化 (描述/判别/语义/因果)
│   ├── 09-system-integration.md       ⭐ 双通道集成架构 (必读)
│   └── 99-rejected-ideas.md           ← 走过的弯路存档
│
├── schemas/                           ← 可执行 SQL
│   ├── notes_v1_2.sql                 ← truth_vault schema · 13 张表 + 内部 views
│   └── notes_v1_2_cross_schema_views.sql ← 跨 schema views (D-029 部署拆分)
│
├── mappings/                          ← 每项目映射 yaml
│   ├── _template.yaml                 ← 新项目复制此模板
│   ├── WTG_phase1.yaml                ← waytogo 个护 (已上线 · 724 篇)
│   ├── NRT_phase2.yaml                ← 力克雷 OTC药 (已上线 · 499 篇/27 爆款)
│   ├── NRT_phase3.yaml                ← 力克雷 phase 3 (有 mapping · 待接)
│   └── NUC_phase1.yaml                ← 大象 Nucare (有 mapping · 待接)
│
├── prompts/                           ← LLM prompt 库
│   ├── essence_annotator.md           ← Mode A/B 双模式 (D-028 物理隔离)
│   └── audience_inferrer.md           ← 独立 audience 推断
│
├── scripts/                           ← 真实可跑的 Python 脚本 ⭐
│   ├── README.md                      ← 数据流图 + 部署 + 故障排查
│   ├── _common.py                     ← 共享工具 (client/mapping/分页/JWT)
│   ├── .env.example                   ← 环境变量模板
│   ├── requirements.txt               ← 依赖
│   │
│   ├── sync_feishu_notes_to_truth_vault.py            ← [1] 飞书 → TV (每日)
│   ├── sync_comments_from_raw_extra.py                ← [5] 评论文本 → comments 表
│   ├── annotate_essence_pass.py                       ← [6] LLM 标注独立 pass (D-028)
│   ├── sync_truth_vault_baokuan_to_sanshengliubu.py   ← [2] TV → ssll 通道 1
│   ├── sync_truth_vault_baokuan_to_autowriter_items.py ← [3] TV → autowriter 通道 2 (已退役 D-038·备查)
│   └── extract_negative_examples_from_autowriter.py   ← [4] 负例候选挖掘 (一次性)
│
├── sanshengliubu-patches/             ← 通道 1 集成包 (部署到 ssll 仓库)
│   ├── README.md                      ← 部署顺序 + 回滚
│   ├── 001_add_source_tv_note_id.sql  ← 必做前置 SQL migration
│   └── import_truth_vault_baokuan.py  ← 可选 helper (列名 + quality_score)
│
├── autowriter-migrations/             ← 通道 2 集成包 (部署到 autowriter 仓库)
│   ├── RUNBOOK.md                     ← 场景 A/B 完整步骤 + Auth/RLS
│   ├── 001_create_autowriter_schema.sql       ← 5 表迁移到 autowriter schema
│   ├── 002_add_external_source.sql            ← items 加幂等键
│   └── 003_add_example_label_proposal.sql     ← items 加负例候选列
│
└── data-analysis/
    └── 10-project-audit.md            ← 10 个项目的初始数据审计
```

> ⚠️ **此目录树是早期快照,有遗漏**。已新增但未列全:`docs/00` + `docs/10`~`21`;`schemas/` 的
> `notes_v1_3`(参考 tier)/`v1_4`(书架)/`v1_5`(馆员缓存)/`v1_6`(sync_status);三个 Railway 服务
> **`librarian/`(通道2 馆员)· `worker/`(essence+curate)· `onboarder/`(接表)**;`scripts/curate_flywheel_lessons.py`
> 等。完整结构以仓库实际 + [docs/00 §9](docs/00-START-HERE.md) 为准。

## 文档导航（按角色）

### 新人 · 第一次接手项目

| 顺序 | 文件 | 用途 |
|---|---|---|
| 0 ⭐⭐ | [docs/00-START-HERE.md](docs/00-START-HERE.md) | **从零到最新的完整对齐**(含过时描述清单)· 第一次接手从这读 |
| 0 ⭐ | [ONBOARDING.md](ONBOARDING.md) | 第一周 checklist + 找谁要凭证 + FAQ |
| 1 | 本文件 (README.md) | 项目边界、原则、栈、四层架构 |
| 2 | [CURRENT_STATE.md](CURRENT_STATE.md) | 当前 sprint scope + 已知 gap |
| 3 ⭐ | [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md) | **动手部署/集成时的实操手册** · step-by-step 命令 + 验证 + 排错矩阵 |
| 4 | [docs/09-system-integration.md](docs/09-system-integration.md) ⭐ | 双通道集成 (核心理论) |
| 5 | [docs/01-architecture.md](docs/01-architecture.md) | 三层架构 (Surface/Essence/Audience) |
| 6 | [DECISIONS.md](DECISIONS.md) | D-001 ~ D-038 决策考古 |
| 6 | [RISKS.md](RISKS.md) | 生产前会咬人的事 |

### 部署 / 实施 · 按需读

| 文件 | 用途 |
|---|---|
| [docs/02-schema-v1.md](docs/02-schema-v1.md) | 数据库 schema 字段级详解 |
| [schemas/notes_v1_2.sql](schemas/notes_v1_2.sql) | truth_vault schema 可执行 SQL |
| [schemas/notes_v1_2_cross_schema_views.sql](schemas/notes_v1_2_cross_schema_views.sql) | 跨 schema views (autowriter 就绪后执行) |
| [sanshengliubu-patches/README.md](sanshengliubu-patches/README.md) | ssll 通道 1 集成 patch |
| [autowriter-migrations/RUNBOOK.md](autowriter-migrations/RUNBOOK.md) | autowriter 通道 2 + schema 迁移 |
| [scripts/README.md](scripts/README.md) | 6 个 sync 脚本的部署 + cron + 故障排查 |

### 数据 / 标注 / 内容 · 按主题

| 文件 | 用途 |
|---|---|
| [docs/11-feishu-table-setup.md](docs/11-feishu-table-setup.md) ⭐ | **建飞书表入口（运营/新项目接入第一步）** · 建哪些列 + 拿 API 凭证 + 避坑 |
| [docs/03-mapping-protocol.md](docs/03-mapping-protocol.md) | 飞书 → DB 映射协议 |
| [docs/04-onboarding-sop.md](docs/04-onboarding-sop.md) | 新项目接入 7 步 SOP |
| [docs/05-controlled-vocab.md](docs/05-controlled-vocab.md) | 受控词表 v0.2 (essence/audience/category) |
| [docs/06-essence-annotation.md](docs/06-essence-annotation.md) | LLM 标注双模式协议 |
| [docs/07-audience-data.md](docs/07-audience-data.md) | 蒲公英真实 audience 数据接入 |
| [prompts/essence_annotator.md](prompts/essence_annotator.md) | Mode A/B prompt 文本 (v0.3) |
| [prompts/audience_inferrer.md](prompts/audience_inferrer.md) | Audience 单独推断 prompt |
| [mappings/_template.yaml](mappings/_template.yaml) | 新项目 mapping 模板 |
| [mappings/NUC_phase1.yaml](mappings/NUC_phase1.yaml) | NUC_1 完整 onboard 示例 |

### 历史 / 演化 · 参考

| 文件 | 用途 |
|---|---|
| [docs/08-evolution-roadmap.md](docs/08-evolution-roadmap.md) | 4 阶段路径 (描述/判别/语义/因果) |
| [docs/99-rejected-ideas.md](docs/99-rejected-ideas.md) | 走过的弯路 (RAG / 单层 schema / 等) |
| [data-analysis/10-project-audit.md](data-analysis/10-project-audit.md) | 10 个项目的初始数据审计 |

## 项目维护者

- **策略 / 决策**: Ziao
- **开发**: 待定
- **AI 协作**: Claude (Anthropic) 通过多个会话窗口持续协作

## 接入指南：新会话 Claude / 工程师怎么用这个 repo

按以下顺序读：

1. **本文件 (README.md)** · 30 秒 · 项目边界、原则、目录结构
2. **[CURRENT_STATE.md](CURRENT_STATE.md)** · 2 分钟 · 当前 Sprint 0 能跑什么 / 不能跑什么
3. **[docs/09-system-integration.md](docs/09-system-integration.md)** ⭐ · 5 分钟 · 双通道集成 (核心架构)
4. **[DECISIONS.md](DECISIONS.md)** · 决策考古 D-001 ~ D-038 · 做任何调整前必读

> 工程实施时再按需读 schema / mappings / scripts 文档（见上方"部署/实施"分组）。

## 当前阶段 (2026-06-05)

✅ **飞轮已转起来**: 2 个项目入库 (WTG + NRT_2 = 1223 篇)、通道1(ssll)+ 通道2(pull/馆员)都 live、
   NRT_2 27 篇真爆款全同步 + 全策展上架 (书架 28 卡)。
🚧 **进行中**: NRT_2 essence 标注 drain (daily-sync 50/天)。
📋 **下一步**: 接 NRT_3/NUC 灌更多真燃料 → L3 受众层 (从没运行) → L2 预测。

> 完整当前状态见 **[docs/21-handover-2026-06-05.md](docs/21-handover-2026-06-05.md)**;从零到现在的完整对齐见
> **[docs/00-START-HERE.md](docs/00-START-HERE.md)**。(本节早期"Sprint 0 / NUC pilot"表述已过时。)
