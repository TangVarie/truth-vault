# Truth Vault · 决策日志

> 这个文档是项目的决策考古层。只追加，不修改。如果某个决策被推翻，新增一条说明推翻理由，而不是删除原决策。

每条决策包含：
- **What** —— 决定了什么
- **Why** —— 为什么这么决定（关键 context）
- **Rejected** —— 拒绝了什么替代方案
- **Implications** —— 这个决策影响哪些下游设计

---

## D-001 · Schema 必须包含 essence 层

**日期**: 2026-05-18

**What**: Schema v1 第一版就必须包含 essence（内核）层字段（emotional_lever / human_truth_archetype / trend_dependencies 等），而不是后期补加。

**Why**: 
- 只有 surface 层的数据，模型只能学到字面模式
- Surface 模式时间衰减快（半衰期 6-12 个月）
- 一年后历史数据的 surface 学到的"什么管用"会跟新数据脱节
- Essence 层（人性、情绪原型）几乎不衰减，是穿越周期的能力来源
- Ziao 原话："这个东西在一开始就需要有个口子，不是说后来怎么怎么着"

**Rejected**:
- "先做 v1 只含 surface，等数据多了再加 essence" —— 拒绝。历史数据回标质量一致性会出问题，标注的人换了一拨之后老数据用不了。
- "essence 自由文本描述" —— 拒绝。LLM 自由描述跨样本不可比。

**Implications**:
- 历史 3,400 条数据需要回标 essence（一次性投入，预算 ¥1000-1500）
- 受控词表 v0.1 必须先于工程实施完成
- 标注 prompt 设计成为关键产出（[docs/06-essence-annotation.md](docs/06-essence-annotation.md)）

---

## D-002 · 拒绝 RAG 作为主要检索方法

**日期**: 2026-05-18

**What**: Truth Vault 不以 embedding-based RAG 作为主要数据检索方式。Embedding 只用于去重检测和阶段 3 之后的辅助语义召回。

**Why**:
- 用 RIO 一期 170 条数据验证：爆款（互动 500+）和趴帖（互动 3）的文案字面高度相似
- Embedding similarity 抓字面模式，抓不到"为什么爆"
- 长尾分布污染：170 条里 160 条趴，top-20 检索 95% 是趴
- 爆的根因往往不在文案里（时段、账号当时流量包、评论区引爆等）
- Ziao 原话："RAG 本质是匹配，你怎么能确保匹配到的是精髓呢？"

**Rejected**:
- "纯 embedding RAG + persona 评分" —— 拒绝，理由如上
- "Hybrid RAG（embedding + tier filter）" —— 拒绝，先有 tier 才能 filter，这是先有鸡先有蛋问题；统计 anchor 更直接

**Implications**:
- 主要检索方式变为"统计 anchor"（结构化查询 + 特征对比）
- 三层架构（Surface / Essence / Audience）成为可能的根因 —— 在三层独立匹配，比单一 embedding 信息量大得多
- pgvector 启用推迟到阶段 3

---

## D-003 · "方向"字段必须在 schema 层面拆解为多维

**日期**: 2026-05-18

**What**: 10 个项目的"方向"字段实际上编码了 3-4 个不同维度的信息（内容形式、目标受众、用户痛点、产品形式）。Schema 必须拆成多个独立字段：
- `content_format`（内容形式）
- `target_audience`（目标受众）
- `user_pain_point`（用户痛点）
- `product_focus`（产品形式）
- `intent`（内容意图：流量向 / 产品向 / 教育向）

每个项目的"方向"字段在 onboarding 时**显式拆解**到这几个字段。

**Why**:
- RIO_1 的方向是"内容形式"（喝酒感受 / 反差与破圈）
- NUC_1 的方向是"用户场景"（术后恢复 / 糖尿病）
- HXZ 的方向是"用户痛点"（持妆问题 / 年龄问题）
- NRT_2/3 的方向是**身份 + 产品形式 + 内容方向 三维混编**（女性自发 / 咀嚼胶 / NRT疗法引导 / 为爱助戒，甚至有"为爱助戒, 咀嚼胶"这种组合标签）
- 单字段编码多维信息直接破坏跨项目可比性
- 即使强行规范化为单字段，跨项目映射也会丢失维度

**Rejected**:
- "强制所有项目使用相同方向命名规范" —— 拒绝，业务现实不允许（甲方诉求不同）
- "用 LLM 自动把方向字段拆解为多维" —— 拒绝，方向背后的策略意图必须人类拍板，LLM 无法可靠推断

**Implications**:
- Onboarding 流程必须包含"方向拆解"环节
- NRT 系列方向最复杂，需要 Ziao/周哥 1 小时专门讨论
- `intent` 字段直接复用「发布笔记」字段（流量帖/钓鱼帖 → traffic; 直给笔记 → conversion）

---

## D-004 · 管家不允许做内容判断

**日期**: 2026-05-18

**What**: Truth Vault 的"智能管家"层只允许做三件事：查询、统计、特征对比。**不允许做内容质量判断**（不允许说"这条好/不好"、"会不会爆"、"建议怎么改"）。

**Why**:
- 数据库的智能性必须有边界，否则引入 LLM 幻觉
- 决策权应该留给 persona / critic / 人类写手
- "管家"和"判断者"角色分离，让 LLM 风险被锁在数据维度（最多查错表、算错统计，不会编内容）
- Ziao 原话："如果智能可能会引入变量而模型幻觉，或者应该加入一个管家类型的角色，也就是不对结果做判断"

**Rejected**:
- "管家直接给出 P(爆) 概率" —— 拒绝，这是判断
- "管家输出推荐改写方向" —— 拒绝，这是判断
- "完全规则化、不用 LLM" —— 拒绝，特征抽取需要 LLM，但锁在闭集标签上

**Implications**:
- 管家工具集只有 `query_db` + `compute_stats` + `extract_features`，没有 `score` 或 `recommend`
- 管家的输出格式是结构化 JSON（事实层），不是自然语言判断
- Persona/critic 接管最终判断，管家提供事实 anchor

---

## D-005 · 历史数据必须回标 essence

**日期**: 2026-05-18

**What**: 已有的 3,400 条带 tier 标签的数据，必须在阶段 1 启动前回标 essence 层（emotional_lever / human_truth_archetype / trend_dependencies / inferred_audience_profile）。

**Why**:
- D-001 决定 schema 必须含 essence 层
- 历史数据如果没有 essence，无法用于训练阶段 2 的分类器（特征缺失）
- 未来标注质量一致性问题 —— 等数据攒到一万条再回标，预算会高 10 倍且质量降低

**Rejected**:
- "只标新数据，老数据放着" —— 拒绝。老数据是爆款样本最集中的资产（约 280+ 爆款样本），不标等于浪费。

**Implications**:
- 预算 ¥1000-1500（Claude Sonnet API 成本）
- 时间 2-3 天跑完
- 需要 [docs/06-essence-annotation.md](docs/06-essence-annotation.md) 的标注协议先稳定
- 需要质量抽检流程（10% 样本人工 review）

---

## D-006 · 修正：A 家族（RIO/WTG/TXQ）是最新格式

**日期**: 2026-05-18

**What**: 修正之前的判断 —— 三个 schema 家族中，A 家族（RIO_1 / WTG / TXQ_1）反而是最新格式，不是最老的。B 家族（NRT/NUC/HXZ）是中间版本，C 家族（TGV/QSHG）才是最老的。

**Why**:
- A 家族独有的字段：「主页链接」+「粉丝数」+「数据回收情况」+「巡查状态」+「最近检查时间」+「已确认存活」 —— 都是"现代化"特征
- B 家族缺粉丝数和数据生命周期管理字段 —— 是早期飞书表演化阶段
- Ziao 在 review 时纠正了我之前的判断

**Rejected**:
- "对齐到 B 家族字段" —— 之前的设计，已推翻

**Implications**:
- 标准 schema 必须包含 A 家族独有的字段，特别是 `account_followers` 和 `data_quality_status`
- B 家族（NRT/NUC/HXZ）需要补录粉丝数 —— 约 2,300 条历史数据
- 新项目按 A 家族字段标准接入

---

## D-007 · TGV_1 备注「新爆」是 tier 金标准

**日期**: 2026-05-18

**What**: TGV_1 项目的 tier 标签从「备注」字段抽取，规则：
- 备注含「新爆」→ tier=爆（47 条）
- 备注含「淘汰」→ tier=趴（305 条）
- 备注含「删0」→ tier=删除（独立状态，64 条）
- 其他 → tier=null

TGV_1 从 archive only 升级到 notes 主表（数值字段允许为 null）。

**Why**:
- Ziao 提醒后重新审视 TGV_1 的「备注」字段，发现 47 条人工"新爆"标注
- 人工"爆"标注是金标准（运营标爆很谨慎）
- 47 爆 + 305 趴是干净的二分类训练数据
- 即使没有数值数据，二分类训练依然有效

**Rejected**:
- "TGV_1 只进 archive" —— 拒绝（之前的判断，已修正）
- "TGV_1 用 LLM 自动从备注推断 tier" —— 拒绝。"新爆"/"淘汰"/"删0"是确定性 keyword match，不需要 LLM。

**Implications**:
- C 家族特殊 mapping 规则：tier 抽取来源是「备注」字段而非「状态」字段
- Schema 必须支持 tier 独立于数值数据存在（impressions/reads/interactions 允许 null）
- 训练数据池从 ~3,000 增加到 ~3,400 条（增量 13%）
- 增加 47 个爆款样本（总爆款样本池 ~328 → ~328 个，14% 增量）

---

## D-008 · Schema v1 必须包含 audience 层

**日期**: 2026-05-18

**What**: Schema v1 必须包含两个 audience 相关字段：
- `inferred_audience_profile` (JSONB) —— LLM 推断
- `actual_audience_data` (JSONB) —— 蒲公英后台数据（如有）

字段定义见 [docs/02-schema-v1.md](docs/02-schema-v1.md)。

**Why**:
- 三层架构（Surface / Essence / Audience）必须三层都有
- Ziao 提出"两个产品的用户画像相似时，策略可以复用" —— 这要求 audience 层数据
- Ziao 可以立即拉蒲公英数据 —— 现成的真实数据源
- LLM 推断 vs 蒲公英真实数据可形成 audience 推断器的校准闭环

**Rejected**:
- "audience 只用 LLM 推断" —— 拒绝。错过了蒲公英真实数据的校准价值。
- "等真实数据齐了再加 audience 字段" —— 拒绝。新项目数据每天都在产生，schema 落后于数据是灾难。

**Implications**:
- 蒲公英数据接入流程必须设计（见 [docs/07-audience-data.md](docs/07-audience-data.md)）
- LLM audience 推断 prompt 设计成为关键产出
- audience profile 一部分闭集（demographic）+ 一部分自由文本（pain/aspiration）

---

## D-009 · 受控词表 v0.2 finalized

**日期**: 2026-05-18

**What**: 受控词表从 v0.1 升级到 v0.2，经 Ziao review 后定稿。具体变更：

- **emotional_lever (10 → 12)**:
  - 新增 `罪恶感撬动`（负向）—— "做得不够好"的愧疚
  - 新增 `虚荣撬动`（正向）—— "我比 XX 强"的优越感
  - 焦虑 vs 恐惧 边界明确为"担心 vs 怕"，"模糊未来 vs 具体威胁"

- **human_truth_archetype (17 → 19)**:
  - 新增 `宠物相关`（关系类）
  - 新增 `消费愉悦`（欲望类）

- **trend_dependencies (9 → 10) ⭐ 关键重构**:
  - 把 "当代流行语" 拆为 `当代流行词`（半衰期 6-12 月）+ `时代语言范式`（半衰期 2-3 年）
  - 引入三级时间分层：通用 / 时代语言范式 / 当代流行词
  - "通用" 定义严格化（不含任何当代/平台/IP 元素）

- **target_audience (10 → 11)**:
  - 新增 `病患家属`（NUC 抗癌方向、糖尿病家属方向用到）

**Why**:

emotional_lever 两个新增：
- 罪恶感和虚荣是真实存在且与现有 10 个值有边界差异的情绪机制
- NUC 抗癌方向、TGV 教育类有罪恶感 angle；横评类、阶层暗示类有虚荣 angle
- Ziao 原话："单独成项吧，确实有这个意义"

焦虑 vs 恐惧保留两个值：
- Ziao 原话："焦虑更加偏担心，而恐惧有怕的成分更多"
- 两者情绪机制本质不同（未发生 vs 已发生、模糊 vs 具体）
- 合并会丢失重要区分信息

human_truth 两个新增：
- Ziao 原话："单独成项吧，单独去判断更可靠，我们要尽可能去精准覆盖，大不了就是闲置"
- 宠物相关在 NUC 数据里有真实 angle，不放进现有原型会被错标
- 消费愉悦是美妆类的核心 angle，组合标注（自我提升+控制感）不够准

target_audience 新增病患家属：
- 现有 10 个值里"伴侣家人"和"宝妈"都不准确覆盖"为病患购买"的人群
- NUC 项目有大量这类内容（抗癌、糖尿病家属、术后恢复购买者）

trend_dependencies 关键重构（三级时间分层）：
- Ziao 提出深刻洞察："话术也可能是一种通用...每年都会有新的流行词被造出来，但是这些造出来的词可能也会有一些通用的倾向甚至趋势方法，这是一种比纯表层更深入更持久的东西，这可能反映了这一个时代阶段的特性"
- Ziao 原话："这代表了我们有可能可以去引领新的话术。而不是纯粹的模仿和等待新数据"
- 在"具体流行词"（半衰期 6-12 月）和"完全通用"（半衰期 5 年+）之间，存在**结构性话术模式**（半衰期 2-3 年）—— 如夸张式自嘲、反向表达、缩写文化、emoji 配文化
- 识别这层模式 = 数据库支持"引领新话术"而非"等待新数据"的算法基础
- 工程实现：surface 层的时间衰减按 trend_dependencies 三级分层独立计算（v0.2 词表文档已给出完整代码）

**Rejected**:

- "合并焦虑和恐惧为单值用 intensity 区分" —— Ziao 拒绝，两者本质不同
- "细分宝妈为孕期/育儿早期/育儿中期/二胎" —— 拒绝，life_stage 字段已能区分，避免双重维度
- "保持 '当代流行语' 单个标签" —— 拒绝，会损失时代范式的信号价值，无法识别可迁移的话术结构
- "保持 '通用' 宽松定义（核心通用即可，附带话术不算）" —— 拒绝，宽松定义稀释通用样本的核心价值

**Implications**:

- [docs/05-controlled-vocab.md](docs/05-controlled-vocab.md) 升级为 v0.2 定稿版
- [prompts/essence_annotator.md](prompts/essence_annotator.md) 同步升级为 v0.2（内嵌词表）
- 历史数据回标使用 v0.2 词表（essence_vocab_version = 'v0.2'）
- Surface 层时间衰减算法引入三级分层（见词表文档代码）
- CURRENT_STATE 任务 #1 阻塞解除，可启动 NUC_1 pilot

**未变更字段**: intent / content_format / emotional_valence / emotional_intensity / tier

---

## 待定决策（议程）

以下是已识别但未拍板的决策候选，列在这里防止丢失：

- **DD-A** `target_audience` 闭集词表是否细分宝妈类型？（影响词表 v0.1 → v0.2）
- **DD-B** `tier=删除` 是否参与模型训练？（影响训练数据筛选）
- **DD-C** QSHG_1 这种无标注数据是否使用半监督学习？
- **DD-D** Schema 是否保留"项目阶段"字段？（飞书表有但都没填）
- **DD-E** 跨客户数据是否允许在 aggregate 层共用？（涉及客户合同）

---

## 决策模板

新增决策请用此模板：

```markdown
## D-XXX · 一句话标题

**日期**: YYYY-MM-DD

**What**: ...

**Why**: ...

**Rejected**: 
- "替代方案 A" —— 拒绝理由
- "替代方案 B" —— 拒绝理由

**Implications**: 
- ...
- ...
```
