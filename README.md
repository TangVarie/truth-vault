# Truth Vault · 帆谷种草决策飞轮

> 这个文档是项目宪法。它定义了 Truth Vault 是什么、不是什么、以及绝对不能违反的设计原则。一旦定稿不轻易修改。

## 一句话定位

Truth Vault 是帆谷的私有数据基础设施 —— 把每一次小红书种草投放的真实结果沉淀下来，让"什么内容会爆、为什么"成为有数据支撑的事实判断，而不是经验直觉。

## 项目目标

让发的越多 → 数据库越准 → 判断越精 → 后续投放命中率越高 —— 形成数据飞轮。

具体来说，Truth Vault 服务三个调用方：

1. **sanshengliubu（三省六部）** —— 提示词生产管线，在 persona simulation 之前注入历史 anchor
2. **autowriter（内容工作台）** —— 内容批量生产工具，在 Claude vs Gemini 二选一时提供历史依据
3. **去中心化写手网络** —— 写手提交内容时获得"这条相比历史爆款的差异点"诊断

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

## 文档导航

| 文件 | 用途 |
|---|---|
| [CURRENT_STATE.md](CURRENT_STATE.md) | 当前进度快照（每次会话更新） |
| [DECISIONS.md](DECISIONS.md) | 决策日志（只追加） |
| [docs/01-architecture.md](docs/01-architecture.md) | 三层架构完整论证 |
| [docs/02-schema-v1.md](docs/02-schema-v1.md) | 数据库 schema (v1.2) |
| [docs/03-mapping-protocol.md](docs/03-mapping-protocol.md) | 飞书表 → 数据库的映射协议 |
| [docs/04-onboarding-sop.md](docs/04-onboarding-sop.md) | 新项目接入 SOP |
| [docs/05-controlled-vocab.md](docs/05-controlled-vocab.md) | 受控词表 |
| [docs/06-essence-annotation.md](docs/06-essence-annotation.md) | LLM 标注协议（含双模式） |
| [docs/07-audience-data.md](docs/07-audience-data.md) | 蒲公英后台数据接入 |
| [docs/08-evolution-roadmap.md](docs/08-evolution-roadmap.md) | 四阶段进化路径 |
| **[docs/09-system-integration.md](docs/09-system-integration.md)** | **⭐ 系统集成架构（必读）** |
| [docs/99-rejected-ideas.md](docs/99-rejected-ideas.md) | 走过的弯路（重要） |
| [data-analysis/10-project-audit.md](data-analysis/10-project-audit.md) | 10 个项目的初始数据审计 |
| [schemas/notes_v1_2.sql](schemas/notes_v1_2.sql) | 可执行 SQL · 表+内部 views (v1.2) |
| [schemas/notes_v1_2_cross_schema_views.sql](schemas/notes_v1_2_cross_schema_views.sql) | 跨 schema views（三个 schema 就绪后执行）|

## 项目维护者

- **策略 / 决策**: Ziao
- **开发**: 待定
- **AI 协作**: Claude (Anthropic) 通过多个会话窗口持续协作

## 接入指南：新会话 Claude 应该怎么用这个 repo

新窗口的 Claude 接到这个项目时，按以下顺序读：

1. 本文件（README.md）—— 30 秒，理解项目边界和原则
2. [CURRENT_STATE.md](CURRENT_STATE.md) —— 1 分钟，理解当前进度和下一步
3. CURRENT_STATE 里引用的具体 docs 文档 —— 按需读取
4. **在做任何决策前，先读 [DECISIONS.md](DECISIONS.md)**，确认没有违反已有决策

新会话开场协议见 [CURRENT_STATE.md](CURRENT_STATE.md) 文末。
