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

**2026-05-18 补充澄清（Session #3）**:
`tier=删除` 语义明确为**主动删除**（内容质量不达预期、运营决定删了重新发新的），不等同于 `tier=风控`。风控是平台限流行为，有独立标注。

训练时 `tier=删除` 的处理：
- 视为**强负样本**（运营主动判断不好到要删，比"无水花"更明确的失败信号）
- 但样本量小（TGV_1 64 条）不适合独立 label，建议合并到"趴"做二分类训练
- 训练时可加大权重（如 weight=1.5）以反映其更明确的负样本性质

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

## D-010 · target_audience 反映项目+方向的实际策略意图

**日期**: 2026-05-18

**What**: `target_audience` 字段（onboarding 时定义）的含义明确为"**该项目+该方向的实际策略意图人群**"，而不是"理论可能性集合"。

具体规则：
- 如果该方向**这一期实际只打了某个人群**（如 NRT_3 女性自发全部是年轻女性 angle）→ 标具体人群 `["年轻女性"]`
- 如果飞书表本身**标注存在混杂或错误**（如 NRT_3 男性自发既有真男性也有女性视角误标）→ 保留粗集合 `["中年男性", "年轻男性"]`，让 LLM 在 essence 标注阶段通过 inferred_audience_profile.age_band 校准
- 不强制要求"集合越大越保险"——刻意标更大集合会损失策略意图信号

**Why**:
- Ziao 在 Session #3 review NRT 方向拆解时提出"target_audience 需要按年龄段分"
- 实际数据验证：NRT_3 女性自发 211 条全部是年轻女性 angle（健身房 / 医美 / 护肤），如果一律标 `["年轻女性", "中年女性"]` 会丢失"这期实际打的就是年轻"这个策略信号
- target_audience 是策略层信号，inferred_audience_profile.age_band 是文案层信号，两者对照是数据飞轮的校准点

**Rejected**:
- "target_audience 永远标理论可能性集合" —— 拒绝，丢失策略意图
- "target_audience 必须 per-note 由 LLM 自动标" —— 拒绝，onboarding 时由策略 lead 定的"该期实际意图"是必要的人工监督信号
- "target_audience 和 inferred_audience_profile.age_band 二选一" —— 拒绝，两个字段语义不同：前者是策略意图，后者是文案推断

**Implications**:
- direction_decomposition 的 target_audience 字段含义在 [docs/04-onboarding-sop.md](docs/04-onboarding-sop.md) Step 3 需更新说明
- LLM essence 标注 prompt 应该接收 target_audience（候选信号）但不强制限制 inferred_audience_profile 必须在该集合内
- 飞书标注 vs LLM 推断 disagreement 成为数据质量监控指标
- NRT_phase3 / NRT_phase2 mapping yaml 按此原则标注（女性自发=["年轻女性"]，男性自发=粗集合）

---

## D-011 · 借助场景撬动流量是 content_format + intent 的特殊组合

**日期**: 2026-05-18

**What**: NRT 项目"隐形烟渍"方向揭示了一个策略模式：**用具体场景作为内容钩子，但目标不是直接植入产品而是引流**。这种模式的 schema 表达是：
- `content_format: 场景植入`（描述内容的表面形式）
- `intent_override: traffic`（覆盖默认的产品转化意图）

并且建议在分析阶段（不是 schema 层）识别"场景植入 + traffic"的组合作为一种独立策略类型。

**Why**:
- Ziao 在 review 隐形烟渍方向时指出："偏向场景植入，但是本质应该是借助场景来撬动流量，而不是直接植入"
- 单独看 content_format（场景植入）会让人误以为是产品转化（直接植入产品到场景）
- 单独看 intent（traffic）会丢失"用什么形式做流量"的信息
- 两者组合识别才是完整的策略类型

**Rejected**:
- "新增 content_format='场景钩子'" —— 拒绝，会和"场景植入"语义冲突
- "在 intent 里增加 'scene_traffic' 值" —— 拒绝，intent 和 content_format 是独立维度

**Implications**:
- mapping yaml 的 direction_decomposition 允许 `intent_override` 字段
- 分析层面识别 "场景植入 + traffic" 组合作为独立策略，统计其爆款率
- NRT_phase2 隐形烟渍方向按此组合标注
- 未来其他项目如发现类似"用场景做流量"的方向（如美妆"医美场景描述"），按相同模式标注

---

## D-012 · 按 intent 分轨训练和优化（traffic vs conversion 走不同管道）⭐ 核心架构原则

**日期**: 2026-05-18

**What**: 阶段 2 训练分类器和阶段 3 的语义检索时，**按 intent 分别训练 / 评估 / 优化**，不混在一个模型里。具体：

- **intent=traffic（流量向内容）管道**:
  - 模型: `predict_explosion_likelihood`
  - 评估指标: P(爆)、P(大爆)
  - 训练正样本: tier ∈ {爆, 大爆}
  - 训练负样本: tier ∈ {趴, 删除}
  - 特征侧重: essence 层（emotional_lever、human_truth_archetype）+ surface 钩子

- **intent=conversion（产品向内容）管道**:
  - 模型: `predict_conversion_effectiveness`
  - 评估指标: 蓝词命中率、互动率、（将来）转化率
  - 训练正样本: hit_blue_keywords 命中目标蓝词 + interaction_rate 高
  - 训练负样本: 完全无效果的直推
  - 特征侧重: surface 层（产品描述清晰度、卖点呈现）+ content_format 类型

- **intent=educational / mixed / other**: 阶段 1 不单独建模，归入 traffic 管道但降权

**生产时调用方式**:
- sanshengliubu / autowriter 生产内容前先确定 intent
- 按 intent 调用对应预测 API
- 评分对比时**只与同 intent 的历史数据对照**

**Why**:
- Ziao 原话："产品直推本来就是很少爆款，不管是什么产品都是，有爆款才是应该重点关注的稀罕事"
- NRT_3 数据验证：单标产品形式（咀嚼胶/喷雾/戒烟贴）85 条 0 爆款，是 intent=conversion 的天然结果，不是"内容不好"
- 把直推数据和流量帖混在一起训练 → 模型会学到错误信号"产品向 = 一定不爆"，污染对身份导向内容的判断
- Ziao 原话："不同产品不同目的应该需要做不同的匹配或者预测或者优化"
- Ziao 原话："应该是预留接口的"——架构上必须从一开始就支持分轨

**Rejected**:
- "用一个统一模型，把 intent 作为特征传入" —— 拒绝。intent 是核心 confounder，单一模型会学到错误信号
- "只训练流量向模型，产品向不预测" —— 拒绝。产品向也需要优化（比如蓝词命中率提升），只是评估指标不同
- "等数据多了再分轨" —— 拒绝。架构决策必须从一开始就预留接口

**Implications**:
- Schema 层面：intent 字段已存在，不需改 schema
- API 层面：预留两套独立 endpoint
  ```
  POST /v1/predict/explosion   # for intent=traffic
  POST /v1/predict/conversion  # for intent=conversion
  ```
- 阶段 1 anchor 报告必须先确定 intent，再调用对应统计
- 阶段 2 训练管道按 intent 分组
- 评估时不再统一报告 "P(爆)"——按 intent 单独看
- [docs/08-evolution-roadmap.md](docs/08-evolution-roadmap.md) 阶段 2 描述需要更新

**为什么这个决策极重要**: 这是架构层面的"分而治之"原则。如果阶段 2 训练一个统一模型，6 个月后会发现模型在产品向内容上预测全是"不会爆"——但实际上产品向天然爆款少，模型给出的不是错误信号，而是无信息信号。这种情况下整个数据飞轮的下游价值会被稀释。

---

## D-013 · Ingest 阶段 LLM-based sanity check 机制（数据质量监控）

**日期**: 2026-05-18

**What**: 笔记 ingest 入库后，跑 LLM essence 标注产出 inferred_audience_profile。系统**自动对照飞书人工标注的 target_audience**，disagreement 高的笔记 flag for review。

具体机制：

1. **Ingest 阶段**（笔记入库后）→ LLM essence 标注
2. **Disagreement 检测**:
   - 比较 `target_audience`（来自飞书方向，onboarding 定义的策略意图）vs `inferred_audience_profile.demographic`（LLM 推断）
   - 关键维度: age_band 是否 overlap、gender_skew 是否一致
3. **Flag 阈值**:
   - gender 不一致（如方向标男性，LLM 推断 female）→ **high flag**（人工 review）
   - age_band 不 overlap（如方向 ["年轻女性"]，LLM 推断 ["50+"]）→ **medium flag**
   - 部分重叠 → 不 flag
4. **存储**: 新增字段 `data_quality_flags JSONB` 在 notes 表，记录 flag 类型和 disagreement 详情
5. **Review queue**: high flag 笔记进入人工 review queue，运营定期处理

**Why**:
- Ziao 原话："人工总是有可能出错的，不仅仅是这里"
- 真实案例: NRT_3 男性自发 4 条爆款里 2 条实际是女性视角（"为了买包戒烟的姐妹"、"半年戒烟买 Chanel"）
- 如果不监控，错误的 target_audience 会污染下游训练
- LLM 在 audience 推断上是独立信号源，可以作为人工标注的交叉验证

**Rejected**:
- "强制 LLM 推断结果覆盖飞书标注" —— 拒绝。LLM 也会出错，需要人工 review 做最终判断
- "ingest 时阻断（disagreement 高的不入库）" —— 拒绝。会损失数据，应该入库 + flag
- "只看 audience，不监控其他字段" —— 拒绝。intent 也会标错，将来扩展监控范围

**Implications**:
- Schema 微调: notes 表新增 `data_quality_flags JSONB` 字段（schema v1.1，加 migration）
- 工程: ingest 流程加入 LLM 推断 + disagreement 检测步骤
- 文档: [docs/06-essence-annotation.md](docs/06-essence-annotation.md) 末尾追加"数据质量监控"章节
- 监控面板: Streamlit 内部 UI 增加 review queue
- 长期: 累积 disagreement 数据可以训练"自动校正"模型（哪种方向标注容易出错）

---

## D-014 · Mapping YAML 支持方向子分类（LLM ingest 时归类）

**日期**: 2026-05-18

**What**: `direction_decomposition` 支持新机制 `sub_directions` —— 当飞书表"方向"字段粗粒度涵盖多个不同人群/场景时，在 schema 层面通过 LLM 在 ingest 时细分为多个子方向。

具体语法：

```yaml
direction_decomposition:
  "飞书原方向":
    sub_directions:
      - name: 子方向1
        detection_signal: |
          文案中出现 X / Y / Z 信号 → 归此类
        content_format: ...
        target_audience: [...]
        user_pain_point: ...
      
      - name: 子方向2
        detection_signal: ...
        # ...
      
      - name: 其他
        # fallback
        # ...
```

Ingest 流程：飞书原方向 → 找 direction_decomposition 配置 → 如有 sub_directions → LLM 看文案 + detection_signal → 选子方向 → 应用该子方向的所有属性。

**Why**:
- NUC_1 onboarding 时发现：同一飞书方向（"营养保健代餐相关"）的笔记，实际人群完全不同（健身减脂年轻女性 vs 关心父母营养的子女）
- Ziao 原话："需要分两个独立方向"
- 飞书表历史数据无法回头改方向字段 → 必须在 schema 层面细分
- 单一方向粗集合 target_audience（如 `["年轻女性", "病患家属"]`）会损失策略精度
- 子分类信息进入 schema 字段（target_audience / user_pain_point）后，下游训练/检索可以按精细人群分组

**Rejected**:
- "强迫飞书表标注更细粒度" —— 拒绝，历史数据无法改，且未来标注成本高
- "靠 LLM essence 标注阶段自动细化 inferred_audience_profile" —— 拒绝。这只能改 audience 层，content_format 和 user_pain_point 没法精细化。必须在 ingest 层面归类。
- "为每个子方向单独建立飞书表" —— 拒绝，运营负担过重

**Implications**:
- mapping yaml schema 扩展：`direction_decomposition[].sub_directions` 数组结构（可选字段，简单方向不需要）
- Ingest 流程升级：飞书方向 → LLM 子分类（看文案）→ 选 sub_direction → 应用属性
- LLM 子分类 prompt 在 mapping yaml 里定义（`ingest_classification_prompt` 字段）
- **该 LLM 调用与 D-013 sanity check + essence 标注合并到一次调用**（节省 token，逻辑集中）
- 子分类有 confidence，低 confidence 进 review queue（类似 D-013）
- Notes 表不需要新字段——子方向的属性（content_format / target_audience / user_pain_point）已经覆盖所有信息
- 训练时按"精细化后的 target_audience"分组，跨子方向的爆款率统计更有意义

**第一个使用案例**：NUC_phase1
- "营养保健代餐相关" → 健身减脂 / 关心父母营养 / 其他
- "任何手术后恢复相关" → 产后宝妈 / 照顾家人手术 / 其他
- "糖尿病相关"、"抗癌放化疗相关（→重症慢病家属）" 单方向不细分

---

## D-015 · 飞书方向语义重定义（semantic_redefined_as）

**日期**: 2026-05-18

**What**: 当飞书表方向字段的**字面定义和实际投放内容不一致**（标注混杂、命名过窄等），mapping yaml 支持 `semantic_redefined_as` 字段记录重定义后的语义。

```yaml
direction_decomposition:
  "飞书原方向名":
    semantic_redefined_as: 实际语义描述   # 注释性字段
    target_audience: [...]
    user_pain_point: 按实际语义描述
    # ...
```

`semantic_redefined_as` 是注释性元数据，不参与 ingest 逻辑（飞书方向字段值不变），但是 onboarding 时让运营和分析师明白方向的实际含义。

**Why**:
- NUC_1 "抗癌放化疗相关" 飞书方向，实际内容混杂痛风、透析、化疗等多种重症
- 真正的内容定位是"重症慢病家属"，不只抗癌
- 字面命名误导分析（如统计"抗癌"内容爆款率会包含痛风内容）
- 但飞书表历史数据无法改字段值（也不应该改 —— 原始数据应该保留）
- 折衷：保留原方向字段值，但在 schema 层面记录正确语义

**Rejected**:
- "改飞书表字段值" —— 拒绝，原始数据应保留
- "把所有错标笔记移除" —— 拒绝，错标的笔记本身仍是真实数据
- "在 raw_extra 里记录" —— 拒绝，重定义是 schema 层面元数据，应该在 direction_decomposition 显式表达

**Implications**:
- mapping yaml 新增 `semantic_redefined_as` 字段（可选）
- 数据分析师查询时知道"抗癌放化疗相关"实际是"重症慢病家属"
- 报告输出时用重定义后的语义（如"重症慢病家属"方向爆款率 8.3%）
- 未来 NUC_2 期项目可以直接在飞书表用"重症慢病家属"作为方向名，向后兼容

---

## D-016 · 生成过程数据 Layer 加入 v1 schema

**日期**: 2026-05-18（Session #6）

**What**: v1.1 schema 新增 4 张表，覆盖内容生产过程：
- `prompt_versions` (含 parent_prompt_id 演化链)
- `generation_runs`
- `content_candidates` (含被淘汰的候选)
- `prepublish_evaluations`

**Why**:
- v1.0 schema 把"飞轮"窄化为"发布后的数据闭环"，从 notes 表开始
- 没有生成过程数据 → 无法回答"哪个 prompt 方向更好"、"Claude vs Gemini 谁更准"、"哪个 critic 校准"
- 错过生成过程数据 = 错过整个生产链的学习信号
- 被淘汰的候选**特别重要**——"为什么没选这个"是核心学习信号
- 取上得中：在工程启动前补完整，不要等阶段 4

**Rejected**:
- "等阶段 4 因果评估时再加" —— 拒绝。等数据多了再补，前期数据全部丢失，且 schema 改动成本高
- "只存 prompt 不存候选" —— 拒绝。淘汰候选是学习信号
- "只存最终选用的候选" —— 拒绝。淘汰原因丢失

**Implications**:
- Schema v1.1 必须含这 4 张表
- 三省六部 / autowriter 必须集成（通过 POST /v1/prompts、/v1/generation/runs、/v1/evaluations）
- 历史数据回流议程：如有可能，把三省六部 / autowriter 历史几个月的数据导入
- 飞轮反馈接口（GET /v1/prompts/{id}/performance 等）依赖这层
- 详见 [docs/09-system-integration.md](docs/09-system-integration.md)

---

## D-017 · Essence 标注双模式（label leakage 防范）

**日期**: 2026-05-18（Session #6）

**What**: Essence 标注分两种模式：

- **prediction_feature_mode**: LLM 标注时**严禁输入** tier / impressions / reads / interactions / 任何 performance 信号。结果可安全用于训练。
- **posthoc_explanation_mode**: 已知 tier 后做复盘分析。结果**禁止用于训练**，独立存入 `posthoc_analyses` 表。

`notes` 表新增字段 `essence_annotation_mode` 标记每条记录的标注模式。**主 essence 字段必须用 prediction_feature_mode 标注**。

**Why**:
- 之前 [docs/06-essence-annotation.md](docs/06-essence-annotation.md) 提到"给 LLM 看 tier 让它分析爆的原因更准"——这是 ML 经典 label leakage 错误
- LLM 知道"这条爆了"后会**事后合理化**，标更高的 emotional_intensity / 更精确的 audience
- 后续训练"预测爆不爆"的模型会学到这些后验偏见 → 部署后预测全是"高质量"
- 复盘分析（已知结果分析原因）本身有价值，但必须和训练特征隔离

**Rejected**:
- "继续给 LLM 看 tier 提升标注质量" —— 拒绝。质量提升的是事后描述，不是事前预测能力
- "通过保留 tier 但要求 LLM 不参考来防 leakage" —— 拒绝。模型无法可靠"忽略"输入
- "完全不做复盘分析" —— 拒绝。复盘有价值（人类学习），独立存即可

**Implications**:
- `notes.essence_annotation_mode` 字段新增（必填，枚举: prediction_feature / posthoc_explanation）
- 新增 `posthoc_analyses` 表（复盘结果）
- [docs/06-essence-annotation.md](docs/06-essence-annotation.md) 标注协议重写：prediction_feature mode 的 prompt 严禁输入 performance 字段
- [prompts/essence_annotator.md](prompts/essence_annotator.md) 拆为两个 prompt 模板
- 训练时 SQL 过滤: `WHERE essence_annotation_mode = 'prediction_feature'`

---

## D-018 · Metric snapshots（机会主义抓取版）

**日期**: 2026-05-18（Session #6）

**What**: 新增 `metric_snapshots` 表存历史表现数据。**不强制定时抓取**——每次运营更新飞书数据时自动 snapshot 一份。`notes.impressions/reads/interactions` 保留最新值。

**为什么是简化版**:
- 原始建议: 强制 24h / 72h / 7d / 14d 统一观察窗口
- Ziao 反馈："实际数据回收节奏不固定，最后爆了就行，时间窗口没那么重要"
- 帆谷实际工作流: 项目结案后定 final tier
- 因此不强制时间窗口，但保留 snapshot 历史能力（未来如想做"前期 vs 后期"分析可回溯）

**Why**:
- v1.0 schema 只有 impressions/reads/interactions 当前值，没有时间序列
- 即使不强制窗口，保留 snapshot 历史是**几乎零成本**的（每次飞书 sync 都顺便 snapshot 一份）
- 未来有需求时可回溯（"是不是前 24h 爆后续停了"）
- tier 字段不需要 tier_observed_at_window 元数据——帆谷的 tier 是项目结案后的最终判定

**Rejected**:
- "强制 24h / 72h / 7d / 14d 观察窗口" —— 拒绝，运营负担过重且非帆谷工作流
- "完全不存历史，只存当前值" —— 拒绝，损失未来分析能力

**Implications**:
- `metric_snapshots` 表加入 schema v1.1
- 每次飞书 sync / pugongying sync 自动追加 snapshot
- tier 字段保持最终判定语义（不分窗口）
- 未来分析时间曲线靠 snapshot 表（不阻塞当前）

---

## D-019 · 系统四层分层（澄清 D-004）

**日期**: 2026-05-18（Session #6）

**What**: 明确 Truth Vault 在帆谷系统中的位置——四层架构：

- **Layer 1 · Truth Vault Core** ("管家"): 存数据、查数据、算统计、出 anchor。**严禁内容判断**。
- **Layer 2 · Predictor / Evaluator**: 基于模型输出 P(爆) / 风险分。**允许结构化预测**。
- **Layer 3 · Persona / Critic / Human**: 最终内容判断 + 改写建议。
- **Layer 4 · Optimization**: 根据真实数据反推 prompt 方向。

D-004 "管家不做判断"指 Layer 1，**不指整个系统**。Layer 2 可以做预测（统计模型不是 LLM 幻觉），Layer 3 做最终判断。

**Why**:
- D-004 "管家不做判断" 和 D-012 "按 intent 分轨预测" 文字上冲突
- 工程师可能不知道到底允许做 score 还是不允许
- 实际是不同层的不同职责
- 需要明确分层定义边界

**Rejected**:
- "Truth Vault 包含所有四层" —— 拒绝，会让"管家"边界失守
- "Layer 2 也禁止预测" —— 拒绝，预测是 D-012 核心，不能禁
- "不分层，靠工程师自觉" —— 拒绝，新工程师会困惑

**Implications**:
- [docs/09-system-integration.md](docs/09-system-integration.md) 详细描述四层
- README.md "原则 1: 管家做查询不做判断" 改为指 Layer 1
- D-004 文字补充说明 Layer 1 严格意义
- Truth Vault 服务对外 API 分类：Layer 1 接口（统计 / anchor）vs Layer 2 接口（predict_explosion / predict_conversion）

---

## D-020 · 账号变量结构化（按帆谷实际简化）

**日期**: 2026-05-18（Session #6）

**What**: 新增 `accounts` 和 `account_snapshots` 表。`notes` 加 `account_id` FK。

**简化点**（基于 Ziao 反馈"都是素人长期合作，不记录粉丝"）:
- account_snapshots 的 followers / avg_reads 等字段允许多数为 null
- 不强制定时抓 account snapshot
- 但 accounts 表本身必须有（素人编号跨表跨项目唯一是金矿）

**Why**:
- 爆款数据不分离账号效应 → 把账号能力误判成内容能力（混淆变量陷阱）
- Ziao 反馈："我们每个素人有编号，跨表一致，编号是人的 ID，一次打上之后不变"
- 同一素人在一个项目可能发多条笔记
- "判断是不是某个素人质量好造成爆款多"是 Ziao 明确想要的分析能力
- 模型训练时 account_id 作为 categorical feature 进入

**Rejected**:
- "只在 notes 表加 account_id，不建 accounts 表" —— 拒绝，无法做素人维度聚合
- "强制采集粉丝数 / avg_reads" —— 拒绝，帆谷实际拿不到这些数据
- "用 account_name 而不是 account_id" —— 拒绝，昵称可能重复

**Implications**:
- `accounts` 表 + `account_snapshots` 表加入 schema v1.1
- `notes.account_id` FK 新增（必填，从飞书"素人编号"映射）
- account 衍生字段（total_notes / bao_rate）自动维护
- 跨项目高爆率素人识别 view: `v_top_performing_accounts`
- 阶段 2 模型训练时 account_id 必须作为 feature（避免账号能力混淆）

---

## D-021 · raw_extra 治理（quarantine 机制）

**日期**: 2026-05-18（Session #6）

**What**: 飞书 sync 字段处理规则统一：

| 字段类型 | 处理 |
|---|---|
| 已声明标准字段 (in `field_mapping`) | 正常映射 |
| 已声明项目专属字段 (in `project_specific_fields_to_raw_extra`) | 进 raw_extra |
| **未声明字段** | **整行 quarantine（不静默入库）** |

未声明字段触发：
1. 该行进 `undeclared_fields_quarantine` 表
2. 运营 review 后决定：加入 mapping / 加入 raw_extra / 忽略
3. Review 后该行重试 sync

**Why**:
- v1.0 文档冲突：模板说"未列出字段自动进 raw_extra"，protocol 又说"未声明列 hard fail"
- 静默入库到 raw_extra → 飞书表结构悄悄变化导致下游数据污染
- Hard fail → 数据丢失风险
- 折衷：保留数据 + 阻断污染 = quarantine

**Rejected**:
- "未声明字段静默入库到 raw_extra" —— 拒绝，飞书表结构变化无监控
- "未声明字段直接丢弃" —— 拒绝，可能丢失重要数据
- "全部走 raw_extra 不做 field_mapping" —— 拒绝，损失结构化能力

**Implications**:
- `undeclared_fields_quarantine` 表加入 schema v1.1
- ingest 脚本必须实现 quarantine 逻辑
- 内部 Web UI 必须有 quarantine review 界面
- [docs/03-mapping-protocol.md](docs/03-mapping-protocol.md) 治理纪律章节更新

---

## D-022 · Comments 表升级

**日期**: 2026-05-18（Session #6）

**What**: `comments` 表新增字段：
- 楼层结构: `parent_comment_id` / `comment_order` / `comment_time`
- 角色和意图: `comment_role` (5 值闭集) / `is_scripted` / `comment_intent` (6 值闭集)

**Why**:
- 评论数据是种草飞轮的关键资产，但 v1.0 comments 表过于扁平
- 评论楼层结构反映"二次引爆"机制（一个评论引发讨论 → 形成楼）
- 评论意图分类（蓝词植入 / 引导私信 / 共鸣扩散）是策略层信号
- 帆谷有"素人—楼层—回复"产品结构经验，应该被数据库支持

**Rejected**:
- "comments 字段保持简单" —— 拒绝，评论是被低估的资产
- "评论意图完全自由文本" —— 拒绝，跨样本不可比
- "暂不做升级，等需要时再加" —— 拒绝，schema 早做不影响生产

**Implications**:
- `comments` 表升级（schema v1.1）
- 历史评论数据（约 2,700 条）需要 LLM 重建楼层结构（飞书表"随贴评论"是文本块）
- comment_intent 闭集词表写入 [docs/05-controlled-vocab.md](docs/05-controlled-vocab.md)
- 评论标注是 essence 标注之外的另一个 batch 任务

---

## D-023 · Truth Vault 与现存系统集成架构 **(SUPERSEDED by D-024)**

> ⚠️ **已作废**: 这份 HTTP REST API 设计在 Session #7 被 D-024 完整取代为
> 双通道直接 INSERT 模式。保留本节作为决策档案; 实施请看 D-024。

**日期**: 2026-05-18（Session #6）

**What**: Truth Vault 与三省六部 / autowriter / 写手网络 通过 **HTTP REST API** 集成，形成内容飞轮。

集成接口分两类：
- **写入接口**: 生产系统 → Truth Vault (POST /v1/prompts, /v1/generation/runs, /v1/evaluations, /v1/notes, /v1/snapshots)
- **反馈接口**: Truth Vault → 生产系统 (GET /v1/prompts/{id}/performance, /v1/models/comparison, /v1/evaluators/calibration, /v1/anchor, /v1/accounts/{id}/history, POST /v1/predict/explosion, /v1/predict/conversion)

集成分三阶段实施：
- **阶段 A** (1-2 月): 数据回流（生产系统 → Truth Vault），不强制使用反馈
- **阶段 B** (3-4 月): 反馈接口上线，可选调用
- **阶段 C** (6+ 月): 决策必须基于 Truth Vault 反馈，飞轮闭环

**Why**:
- 项目核心目标是"飞轮"，不是"另一个数据库"
- 没有集成 → 数据沉淀和生产决策脱节 → 数据飞轮空转
- HTTP REST 解耦：各系统独立部署、独立扩展、故障隔离
- 渐进集成降低风险：阶段 A 对生产流程影响小，阶段 C 才真正闭环

**Rejected**:
- "Truth Vault 直接共享 Supabase 给三省六部" —— 拒绝，系统耦合、故障扩散
- "Truth Vault 替代三省六部 / autowriter" —— 拒绝，是补充不是替代
- "一次性全部集成" —— 拒绝，风险过高
- "只做写入不做反馈" —— 拒绝，反馈是飞轮闭环关键

**Implications**:
- [docs/09-system-integration.md](docs/09-system-integration.md) 详细描述集成架构（必读）
- 工程实施 Sprint 0: 部署 Truth Vault + 实现写入接口（阶段 A）
- 工程实施 Sprint 3-4: 反馈接口（阶段 B）
- 写入接口设计原则: 生产系统**自愿调用**，不阻塞生产流程
- 反馈接口设计原则: Truth Vault 提供**信息**，不替代生产系统的判断权
- 历史数据回流议程: 三省六部 / autowriter 历史几个月 prompt + 生成数据是否回流（一次性大工程）

---

## D-024 · Truth Vault 双通道集成模式（取代 D-023 HTTP REST）

> ⚠️ **通道 2（autowriter）部分已被 [D-038](#d-038) 取代**（push → pull / 图书馆 + LLM 馆员，2026-06-01 Session #15）。**通道 1（ssll）不变，仍然有效。** 下方"通道 2"小节按 push 模型描述，保留作决策档案；实施请看 D-038 + [docs/14](docs/14-channel2-pull-librarian.md)。

**日期**: 2026-05-19（Session #7）

**What**: 通过共享 Supabase + 直接 INSERT 到现存系统的高权重注入点，实现飞轮闭环。**不做 HTTP REST API**。

具体两个通道：

**通道 1 · sanshengliubu.reference_samples**:
- Truth Vault 把 tier ∈ {爆, 大爆} 的笔记 sync 进 sanshengliubu.reference_samples 表
- 字段映射: title/body/comments/platform/category/ai_analysis/quality_score/tags
- 自动被 sanshengliubu.retrieve_reference_packs() 拉出注入 vibe_rewriter（已存在的高权重路径）
- 修改量: sanshengliubu 加 1 个方法 import_truth_vault_baokuan（~30 行）

**通道 2 · autowriter.items (example_label='positive')** ⚠️ 已被 [D-038](#d-038) 取代（见本节顶部横幅）:
- Truth Vault 把爆款笔记直接插入 autowriter.items 表，example_label='positive'
- 使用约定的 batch_id / user_id / project_id（特殊"truth_vault_synced"batch）
- 自动被 autowriter.build_system_prompt() 通过 positive_examples 参数注入（已存在的高权重路径）
- **修改量: autowriter 零代码改动**（复用现有 example_items 机制）

**Why**:
- D-023 设计的 HTTP REST 接口要求 sanshengliubu / autowriter **主动调用** Truth Vault，强制改造负担大
- 看代码发现 sanshengliubu.reference_samples 字段完美对应 Truth Vault 爆款笔记
- 看代码发现 autowriter.items 已有 example_label='positive' 机制 + positive_examples 注入逻辑
- 直接喂数据到现有飞轮位置，**零改动 + 高权重**（和自家 positive_example 同等优先级）
- HTTP REST 的"信息 vs 决策分离"价值在帆谷规模下不值得耦合开销

**Rejected**:
- "HTTP REST API（D-023 原设计）" —— 拒绝。要求改造现存系统，飞轮启动慢
- "把爆款数据塞进 autowriter.memories" —— 拒绝。memory 系统是为"用户偏好规则"设计，不是"具体爆款样例"。注入权重低、需要用户在 UI confirm
- "在 autowriter.build_system_prompt 新加注入层" —— 拒绝。需要改 autowriter 代码，且和现有 positive_examples 重复

**Implications**:
- D-023 的 HTTP REST API 设计**作废**（写入接口 + 反馈接口都不做）
- sanshengliubu 只需要加 1 个 `import_truth_vault_baokuan(note)` 方法
- autowriter 零代码改动
- 反馈接口（GET /v1/prompts/.../performance 等）改为内部 view + 内部 Web UI（不对外暴露 API）
- 共享 Supabase 是前提（[D-027](#d-027) 确认）

参见 [docs/09-system-integration.md](docs/09-system-integration.md) v2 重写版。

---

## D-025 · 简化 D-016 生成过程数据 layer

**日期**: 2026-05-19（Session #7）

**What**: D-016 设计的 4 张生成过程数据表大幅简化：

| D-016 原设计 | v1.2 调整 |
|---|---|
| `prompt_versions` 表 | **删除**。Prompt 内容存在 sanshengliubu.outputs，Truth Vault 通过 sanshengliubu_output_id FK 引用 |
| `generation_runs` 表 | **删除**。Run 数据存在 sanshengliubu.pipeline_runs + autowriter.batches，Truth Vault 通过 FK 引用 |
| `content_candidates` 表 | **删除**。候选内容存在 autowriter.items + versions，Truth Vault 通过 FK 引用 |
| `prepublish_evaluations` 表 | **保留但简化**。autowriter._select_best_drafts 是隐式评审，Truth Vault sync 时反推存为 evaluator 准确率追踪 |

`notes` 表新增 FK 字段：
- `source_sanshengliubu_output_id UUID` → sanshengliubu.outputs.id
- `source_autowriter_item_id UUID` → autowriter.items.id  
- `source_autowriter_version_id UUID` → autowriter.versions.id

跨 Supabase schema 的查询通过 PostgreSQL view 实现（共享实例使跨表 join native 支持）。

**Why**:
- 看代码发现 sanshengliubu / autowriter 已有完整的过程数据表结构
- Truth Vault 复制存储 = 重复造轮子 + 同步成本 + 数据不一致风险
- 共享 Supabase 下 FK 引用更优雅
- Truth Vault 真正的核心是"结果数据 + 跨系统飞轮枢纽"，不是"过程数据库"

**Rejected**:
- "Truth Vault 完整复制 prompt / run / candidate 数据" —— 拒绝。重复存储 + 同步开销
- "完全删除 prepublish_evaluations" —— 拒绝。evaluator 准确率追踪有价值（autowriter._select_best_drafts 选择的实际命中率）

**Implications**:
- schemas/notes_v1_2.sql 删除 3 张表
- v_prompt_performance / v_model_comparison 等 view 改为跨 schema join
- D-016 文字保留（记录历史），但实施按 D-025 简化版
- autowriter 历史 batches/items 不需要回流（直接 join 即可）

---

## D-026 · 历史数据回流策略（分级处理）

**日期**: 2026-05-19（Session #7）

**What**: 按数据价值分级回流：

| 数据源 | 价值 | 处理 |
|---|---|---|
| **飞书表 notes**（10 项目 6,332 行，含 tier）| ⭐⭐⭐⭐⭐ | **必须回流**。这是 Truth Vault 的核心数据资产 |
| **autowriter.items 用户修改记录** | ⭐⭐ | **扫一次作为 negative_examples 种子**（见 D-027）|
| **autowriter.items 用户淘汰候选** | ⭐⭐ | 同上，作为 negative_examples |
| **autowriter.items 已发布且 tier 已知** | ⭐⭐⭐⭐⭐ | 不单独回流——这些笔记本身在飞书表 notes 里，已经在第一项回流中。通过 source_autowriter_item_id FK 关联 |
| **sanshengliubu.outputs / stage_logs** | ⭐ | **跳过**。AI 内部对抗中间产物，没有真实 tier 校准，回流没意义 |
| **sanshengliubu.reference_samples** | ⭐⭐⭐ | **保留共存**。人工 curate 的外部爆文 + Truth Vault sync 的帆谷自家爆款共存，用 tags 区分 source |

**Why**:
- Ziao 反馈："autowriter 几百条不干净，正面的内容我们都已经摘出来做了发布了，反而没有必要"
- Ziao 反馈："sanshengliubu 跑的 prompt 只有 AI 内部对抗，没有人工最后意见，是前置数据孤岛"
- 正面信号源于"已发布 + tier=爆"（飞书表 → Truth Vault notes）—— 一手数据
- 负面信号源于"用户修改/淘汰行为"（autowriter.items）—— 信号弱但来源不同
- 两者来源独立 = 高质量训练对比

**Rejected**:
- "全部回流（含 sanshengliubu outputs）" —— 拒绝。AI 中间产物无校准价值，污染数据
- "autowriter items 整体回流（含 positive）" —— 拒绝。Ziao 指出 positive 已在飞书表里
- "跳过 autowriter 历史回流" —— 拒绝。negative example 是难得信号，扫一次成本不高

**Implications**:
- 写 3 个 sync script（详细 spec 见 docs/09 v2）:
  - `sync_feishu_notes_to_truth_vault.py`（一次性 + 周期性）
  - `sync_truth_vault_baokuan_to_sanshengliubu.py`（持续 sync）
  - `sync_truth_vault_baokuan_to_autowriter_items.py`（持续 sync）
- 写 1 个一次性脚本 `extract_negative_examples_from_autowriter.py`（详见 D-027）
- sanshengliubu.reference_samples 加 tags 区分 source

---

## D-027 · Negative example 信号来源（autowriter 用户修改/淘汰行为）

**日期**: 2026-05-19（Session #7）

**What**: autowriter 历史 items 中的 negative example 信号有 3 个来源：

**来源 A · 用户手动修改记录**:
```sql
-- 用户进入"✏️ 手动精修"修改的 items
SELECT i.id, v.title, v.body, i.manual_edit_draft
FROM items i 
JOIN versions v ON i.id = v.item_id
WHERE i.manual_edit_draft IS NOT NULL
AND i.manual_edit_draft != ''
```
信号：用户觉得这版需要手动改 → AI 这条写得不够好

**来源 B · 用户反馈触发的迭代**:
```sql
-- 同一 item 有多个 version 且 feedback 不为空
SELECT i.id, v1.body AS original, v2.body AS revised, v1.feedback
FROM versions v1
JOIN versions v2 ON v1.item_id = v2.item_id AND v2.version_num > v1.version_num
WHERE v1.feedback IS NOT NULL
```
信号：原版被用户要求改写 → original 是 negative，revised 是 positive 候选（但可能没发布）

**来源 C · 用户淘汰候选**:
```sql
-- 同一 batch 多个 items，只有部分进入 approved
SELECT b.id, i1.id AS rejected_item, i2.id AS approved_item
FROM batches b
JOIN items i1 ON b.id = i1.batch_id AND i1.status = 'needs_revision'
JOIN items i2 ON b.id = i2.batch_id AND i2.status = 'approved'
WHERE NOT EXISTS (
    SELECT 1 FROM items i3 
    WHERE i3.batch_id = b.id AND i3.example_label = 'positive'
    AND i3.id = i1.id
)
```
信号：同一 batch 里淘汰的候选 = AI 生成的"不被选中的版本"

**回流到 autowriter.items 的方式**:
不需要回流到 autowriter（数据本来就在那）。而是：
- 一次性脚本 `extract_negative_examples_from_autowriter.py` 扫这 3 个来源
- 把识别出的 negative example 在 autowriter.items 表里**打 `example_label='negative'`**
- autowriter 现有的 build_system_prompt 自动注入 negative_examples 参数（零改动）

**Why**:
- Ziao 反馈："正面的内容我们都已经摘出来做了发布了，反而没有必要"
- 用户修改 / 反馈 / 淘汰行为是**真实负面信号**（来自人，不是 AI 自评）
- autowriter.items.example_label='negative' 是 autowriter 已有的注入路径
- 一次性扫不是高频任务，可以在 NUC pilot 期间手动跑一次

**Rejected**:
- "把负面信号也存进 Truth Vault notes 表" —— 拒绝。Truth Vault notes 是"已发布笔记"专用，未发布的 negative 不该混
- "把负面信号塞进 autowriter.memories" —— 拒绝。memory 系统不接受具体 example，权重也低

**Implications**:
- 写一次性脚本 `extract_negative_examples_from_autowriter.py`（约 100 行 SQL + Python）
- autowriter.items.example_label 现有逻辑零改动
- 用户在 autowriter Memory Manager UI 里可以 review / unflag 这些自动标记
- 未来 autowriter 持续运行时**手动**打标 negative 仍然是主要来源（自动扫只做历史种子）
- **2026-06-05 追加（Session #18 · 正负信号不对称的关键澄清，完整见 [D-040](#d-040)）**：负例**只能靠人工显式标注**，
  **绝不能从数据反推**——尤其**不**能拿 TV 的 `趴`（无水花）笔记当负面源。原因 = **正负信号天生不对称**：能「爆」通常
  意味着内容够好【且】拿到了分发（高互动难偶然刷出）；但「趴」有大量**与内容无关**的无辜解释——**撞流量墙**（根本没进
  流量池就死、压根没被看到）、**账号权重/限流**、选题时机/运气，三者在数据里很难干净拆分。把 `趴` 一概当差笔记萃取
  负面特征，会**把"被埋没的好内容"也标成垃圾、污染负面特征库**。而**人工显式标 = "我看了内容、判定它就是差"**，是针对
  内容本身的主动判断、没有流量墙/账号混淆——这才是可信负面信号。**所以负例以人工标注（`example_label='negative'`，
  经 UI 确认）为准；`趴` 至多弱参考、不作负面源。** 这反过来印证了本条"负例靠人标、不从数据推"的原始判断是对的。

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

---

## D-028 · Essence 标注 prompt 强制双模式隔离（label leakage 修复）

**日期**: 2026-05-20（Session #8.5 审计修复）

**What**: `prompts/essence_annotator.md` 从 v0.2 升级到 v0.3，物理拆分为 Mode A / Mode B 两个独立 prompt 模板：

- **Mode A (prediction_feature)**: prompt 中**不包含** `{performance_context}` 占位符。无论调用方传什么参数，LLM 看不到 tier / impressions / reads / interactions。调用代码加硬校验（assert prompt 中不含 performance 关键词）。
- **Mode B (posthoc_explanation)**: 独立 prompt，含 performance 数据，结果只进 `posthoc_analyses` 表。

**Why**:
- v0.2 prompt 把 `{performance_context}` 作为"可选"参数，加了"不要被 tier 拉偏"的指令文本。但 LLM 行为研究表明，即使指令说"忽略"，exposure 本身就会影响输出分布——LLM 会事后合理化，给爆款标更高 intensity、更精确 audience。
- `docs/06-essence-annotation.md` 正确描述了 D-017 双模式设计，但 `prompts/essence_annotator.md` 没有对应实现——只有一个模板。
- sync 脚本 (`sync_feishu_notes_to_truth_vault.py`) 的执行流中 tier 在 LLM 标注前就已抽取，如果 prompt 模板包含 performance 占位符，标注函数可能传入 tier。
- 物理隔离（两个不同的 prompt 字符串）比指令隔离（"请忽略这个字段"）可靠得多。

**Rejected**:
- "Mode A prompt 包含 performance 块但加更强的'忽略'指令" —— 拒绝。exposure bias 不是指令能消除的。
- "sync 脚本保证不传 performance，prompt 层面不改" —— 拒绝。防御深度不够，未来换人写 annotation pass 可能忘记。

**Implications**:
- `prompts/essence_annotator.md` v0.3：两个独立 prompt 模板 + 调用代码示例含 assert 校验
- `docs/06-essence-annotation.md` 更新引用
- sync 脚本中 LLM 标注延迟到独立 pass（已在 Session #8 实现），与本决策互为补充

---

## D-029 · SQL 文件拆分为两阶段部署

**日期**: 2026-05-20（Session #8.5 审计修复）

**What**: `schemas/notes_v1_2.sql` 拆为两个文件：

1. **`notes_v1_2.sql`** —— truth_vault schema 所有表 + 触发器 + 仅引用 truth_vault 表的内部 views（v_project_tier_summary / v_data_health / v_top_performing_accounts / v_evaluator_calibration / v_flywheel_sync_status）。无外部 schema 依赖，可独立执行。
2. **`notes_v1_2_cross_schema_views.sql`** —— `v_prompt_performance`（引用 public.outputs / public.pipeline_runs）和 `v_model_comparison`（引用 autowriter.versions / autowriter.items）。需要三个 schema 都就绪后才能执行。

**Why**:
- `CURRENT_STATE.md` 部署步骤写"先执行 notes_v1_2.sql 再迁移 autowriter"——但 SQL 末尾的跨 schema view 会因为 `autowriter.versions` 不存在而 `CREATE VIEW` 报错。
- 拆文件后部署顺序清晰：tables → 迁移 autowriter → cross-schema views。

**Implications**:
- README 和 CURRENT_STATE 部署步骤更新
- `docs/09-system-integration.md` 的 view 代码块统一到 SQL 文件的 canonical 版本

---

## D-030 · notes_archive 加 account_id 和 publish_time 索引

**日期**: 2026-05-20（Session #8.5 审计修复）

**What**: `notes_archive` 表新增 `account_id` 字段（FK 到 accounts）+ `publish_time` 索引。

**Why**:
- 如果一个素人同时有进 notes 和 archive 的笔记，无 account_id 就无法跨表做素人维度分析。
- QSHG_1 无标注数据可能进 archive（Q4），未来做半监督学习需要按 publish_time 过滤。

---

## D-031 · comment_intent 加 CHECK 约束

**日期**: 2026-05-20（Session #8.5 审计修复）

**What**: `comments.comment_intent` 从无约束 TEXT 改为 CHECK 闭集约束（补充信息 / 反驳质疑 / 蓝词植入 / 共鸣扩散 / 引导私信 / 其他）。

**Why**: `comment_type` 已有 CHECK，`comment_intent` 只有注释说"闭集"但 SQL 层面没约束。与项目"硬阻断比报警有效"的治理哲学矛盾。

---

## D-032 · accounts.notes_text 改名为 account_memo

**日期**: 2026-05-20（Session #8.5 审计修复）

**What**: `accounts` 表的 `notes_text` 字段改名为 `account_memo`。

**Why**: 在笔记（notes）数据库里有个字段叫 `notes_text` 极易混淆 —— 看起来像是"笔记文本"而实际是"账号备注"。改名消除歧义。

---

## D-033 · 受控词表 tier 增加第 8 个值 "数据异常"

**日期**: 2026-05-20（Session #8.5 审计修复）

**What**: `docs/05-controlled-vocab.md` tier 定义从 7 值增加到 8 值，补入 `数据异常`。

**Why**: SQL CHECK 约束里已有 8 个值（含 `数据异常`），词表文档只列了 7 个（漏了）。D-013 sanity check 机制需要这个值来标记数据自相矛盾的行。

---

## D-034 · prepublish_evaluations 暂不接通 sync（Phase 2 工作）

**日期**: 2026-05-20（Session #9 review 修复）

**What**: `truth_vault.prepublish_evaluations` 表 + `v_evaluator_calibration` view 保留在 schema，但暂不写入。autowriter 现有 codebase 不存"评审记录"，只通过 `best_version_id` 隐式记录，反推 evaluator 会变成猜测。

**Why**:
- D-025 原意是 autowriter `_select_best_drafts` 的隐式评审在 sync 时反推存入
- 但 autowriter `_select_best_drafts` 没有 evaluator type / score / decision 字段
- 强行从 `best_version_id` 推 evaluator 不可靠，会给 v_evaluator_calibration 灌脏数据
- 当前空表 + 空 view 不报错，等 autowriter 加 evaluations 表再接通

**Rejected**:
- 在 sync 时随机给 evaluator='autowriter_select_best' 凑数 — 拒绝。脏数据更难清理。
- 直接删 prepublish_evaluations 表 — 拒绝。设计 + view 已稳定，删了下游 query 会断。

**Implications**:
- v_evaluator_calibration 当前永远空（不影响主链路）
- Phase 2+ 工作：autowriter 加 evaluations 表 → TV 加 sync 脚本 → was_correct 自动算
- 需要 cross-team 协调，等飞轮主链路验收稳定后开

---

## D-035 · Sprint 0 scope 含已知 gap（comments LLM 重建 / essence 标注 / sub_directions）

**日期**: 2026-05-20（Session #9 review 修复）

**What**: Sprint 0 实测的范围明确为"主链路 + 飞轮通道接通"，不是"完整三层标注闭环"。三个 P1 gap 写明：

1. **sub_directions LLM 子分类（D-014）**: NUC_phase1 的 6 个 schema 子方向需要 LLM 在 ingest 时分类才能落到 `target_audience` / `content_format` 等字段。当前 `sync_feishu_notes` 只做单方向 decomposition 的确定性 lookup，sub_directions 保留 `_direction_raw` 到 raw_extra 让独立 LLM pass 处理。
2. **Essence + audience 标注（D-017 / D-028 Mode A）**: `annotate_essence_pass.py` 已交付，但需要独立运行（D-028 不能和 sync 同进程）。Sprint 0 验收 NUC pilot 30 条标注准确率后才大规模铺开。
3. **Comments 楼层重建（D-022 / Q21）**: `sync_comments_from_raw_extra.py` 当前只做扁平 line-by-line 解析，不做 parent_comment_id 推断。LLM 重建楼层成本估算（Q21）后再做。

**Why**:
- 这三件事的实施成本和质量风险都很高（特别是 sub_directions 准确率会影响 NUC 全部 1102 行的下游分析）
- 主链路 + 飞轮通道不依赖它们就能跑起来（爆款 sync + 双通道注入都能闭环）
- 先用 Sprint 0 验证主链路稳定性，三件事在 Sprint 1+ 按 ROI 排序补

**Implications**:
- `CURRENT_STATE.md` "Sprint 0 实测能跑什么 / 不能跑什么" 节明确列出
- `docs/09-system-integration.md` "comments 暂不闭环" 段保留
- 不应在 Sprint 0 验收时把这三件事当阻塞点

---

## D-036 · autowriter 注入候选 + 飞轮打分（injection_score / rank_score）

**日期**: 补记（原始决策讨论未入档；2026-06 审计从代码 + 多处 "D-036" 引用反向补，故 Why 仅记已知部分）

**What**: 爆款进 autowriter 注入池 / 馆员书架前，按一个【打分公式】排序，让"借到的是好书且新"：
`score = recency_weight + tier 加成(大爆 +0.5 / 爆 +0.3 / 参考 +0.15) + tier_source 加成(状态字段/备注字段/人工补录 +0.2) + account_bao_rate × 0.3`。

**Why（已知部分）**: 单纯按 tier 取会让"老但高 tier"压过"新且相关"；打分把新鲜度 + 账号质量一起纳入。

**Implements / Refs**: `v_autowriter_injection_candidates`（schemas/notes_v1_2 → v1_3）、`v_flywheel_lesson_cards`（notes_v1_4）、`sync_truth_vault_baokuan_to_autowriter_items.py`、`librarian/core.py`。注入(push)用 surface 线性衰减 + 12 个月窗；书架(pull, D-038)用 essence 半衰期 5 年(D-001)。

**注**: D-037 在代码 / 文档中无任何引用，疑为跳号，未补。

---

## D-038 · 通道2 改为 Pull / 图书馆 + LLM 馆员（取代 D-024 通道2 push）

**日期**: 2026-06-01（Session #15）

**What**: autowriter 通道（通道2）从"TV 把爆款 **push** 进 `autowriter.items`（example_label='positive'，单 FK `mapping_to_autowriter_project_id` 路由）"改为"TV 当**策展图书馆**，autowriter 写稿时向 **LLM 馆员**按 brief 借阅匹配的爆款经验"。通道1（ssll）不变。完整设计见 [docs/14](docs/14-channel2-pull-librarian.md)。

**Why**:
- push 模型要求**推送时就钦定**"哪条爆款进哪个项目"，根因是 autowriter 现成正例机制（`list_example_items`）**按 `created_at` 取最近 5 条 —— recency，不做相关性检索**。于是路由表 / 产品流量分类 / 扇出每 owner / 每 owner 桶 这一坨复杂度，全是"autowriter 不会检索"的替代品（WTG 一个 TV 项目 ↔ 18 个 aw 项目 / 3 owner 的一对多即症状）。
- 通道1 从无此苦：ssll `retrieve_reference_packs()` 写稿时按 category/platform 现借（[R-022 ✅](docs/10-sister-repo-followups.md#r-022)），天生 pull。通道2 对齐成 pull，路由那一坨**整体消失**。
- 引入 LLM 的价值在**判断**（入库提炼经验卡 + 借阅推理选取），不是 embedding 相似度，故不落入 [D-002](#d-002) 否掉的 naive RAG（书架预策展只摆爆/大爆，长尾趴根本不进库）。
- **0 条合格爆款**（docs/13）是重做此选型的最佳窗口：没有数据要迁，push 从没真跑过（`items.external_source` 全 NULL）。

**Rejected**:
- "保持 D-024 push + 按产品/流量路由 + 扇出每 owner" —— 拒绝。路由复杂度是 autowriter 不检索的替代品；aw 18 项目命名两套 / 编号对不齐，长期维护成本高。
- "纯 embedding RAG 检索" —— 拒绝（D-002 长尾污染）。本设计是预策展 + LLM 推理选取，不是相似度 top-k。
- "新建空的'飞轮正例池'项目" —— 拒绝。正例是项目级消费（`list_example_items` 走 `batches!inner(project_id)`），没人在空池里写稿，注进去永不被取用。

**Implications**:
- D-024 的**通道2 部分作废**（push 管子待 pull 上线后退役）；通道1 不受影响。D-024 已加 superseded-in-part 标记。
- `scripts/sync_truth_vault_baokuan_to_autowriter_items.py` 进入退役倒计时（pull 上线前保留，因为 0 注入、留着无害）；`v_autowriter_injection_candidates` 的排序 / 多样性逻辑搬进策展库 + 馆员。
- autowriter 侧需改生成流程（调馆员 + 注入），跟踪见 [docs/10 R-032](docs/10-sister-repo-followups.md#r-032)。
- **馆员 = 独立共享服务（FastAPI on Railway），aw + ssll 共用**（Edge Function 排除：Deno 重写 + ~2min 执行上限顶不住）。brief 以项目 `system_prompt` 为主体 + 请求 delta；结果走内容寻址缓存（库版本自动失效）省 LLM。详见 docs/14 §4.2 / §6。
- ssll 从现有 category-filter `retrieve_reference_packs` 切到馆员（可选升级）：跟踪 [R-033](docs/10-sister-repo-followups.md#r-033)。
- 不触碰：owner 原生 `example_label`、negative 反向通道（[D-027](#d-027)）、通道1。
- `docs/13` 通道2 步骤（配 aw 映射 + 跑 push sync）加 deprecation 横幅。

参见 [docs/14-channel2-pull-librarian.md](docs/14-channel2-pull-librarian.md)。

---

## D-039 · essence_annotation_mode 放宽为 nullable（合理偏离 D-017 的"必填"）

**日期**: 2026-06-05（Session #17）

**What**: [D-017](#d-017) 的 Implications 写 `notes.essence_annotation_mode` 字段**新增（必填，枚举: prediction_feature / posthoc_explanation）**。实际落地的 schema（`schemas/notes_v1_2.sql:255-256`）把它建成 **nullable**（只有 CHECK 约束枚举值，无 NOT NULL）。本条**正式记录这个偏离并确认它是对的**——不是 bug。（DECISIONS 只追加，不改 D-017 原文；读 D-017 看到"必填"时以本条为准。）

**Why**:
- sync 的写入时序是**先插入 note 行、后由独立 essence pass 异步标注**（[D-028](#d-028)：Mode A 标注与 tier/performance 严格隔离，`sync_feishu_notes` 不调 LLM）。若 `essence_annotation_mode` NOT NULL，每条新 note 在【还没标注】时就会卡住 INSERT —— 与"先入库、按 `essence_annotated_at IS NULL` 续标"的幂等管道直接冲突。
- 字段语义本就是"**这条已被标注时，用的是哪种模式**"，未标注时为 NULL 是**正确的缺省**，不是缺数据。
- D-017 防 label-leakage 的**核心保护仍然成立**：主 essence 走 Mode A（performance-blind），由 `annotate_essence_pass.py` 落地、写 `essence_annotation_mode='prediction_feature'`；训练查询按 `WHERE essence_annotation_mode = 'prediction_feature'` 过滤（NULL=未标注，自然被排除）。放宽 NOT NULL **不削弱**该隔离，只去掉一个与异步标注时序冲突的写入约束。

**Rejected**:
- "保持 NOT NULL，sync 插入时先写一个占位 mode" —— 拒绝。会污染语义（未标注的行被标成像已标注），且占位值要么撞 CHECK、要么需要再加一个"未标注"枚举值，得不偿失。
- "改 D-017 原文把'必填'划掉" —— 拒绝。DECISIONS 是只追加的决策考古层；偏离用新条目记录，保留 D-017 当时的判断轨迹。

**Implications**:
- `notes.essence_annotation_mode` 维持 nullable + CHECK 枚举（现状，无需改 schema）。
- 训练 / 下游过滤继续用 `essence_annotation_mode = 'prediction_feature'`（隐含排除 NULL 未标注行），见 D-017 Implications。
- **连带欠账（本条不解决，登记备查）**：D-017 还要求 `prompts/essence_annotator.md` 拆成两个 prompt 模板（prediction_feature / posthoc_explanation），现仍只有 Mode A 一个模板；posthoc 复盘模式（`posthoc_analyses` 表）整体尚未启用，故拆模板无紧迫性。待真正要做 essence 复盘分析时一并补。

---

## D-040 · 负面信号只取人工标注；`趴` 不可作负面源（正负不对称）+ 跨产品避坑特征方向

**日期**: 2026-06-05（Session #18）

**What**: 明确两件事（澄清并补强 [D-027](#d-027)）：

1. **负面特征（negative example）只来自【人工显式标注】的干净负例**（autowriter `example_label='negative'`，经
   Memory Manager UI 确认），**绝不从数据反推**——尤其**不**把 TV 的 `趴`（无水花）笔记当负面源。
2. **方向（roadmap，尚未建）**：若要做"跨产品可迁移的**避坑特征**"（与正面飞轮对称的负面飞轮），源头**必须是
   AW 的人工标注干净负例**，由 TV 管家萃取成可迁移的反面本质、borrow 时一并注入"避开这类写法"；**绝不是** `趴`。
   当前 AW 本地注入已覆盖眼前需求，此跨产品萃取**优先级低**。

**Why（正负信号天生不对称——这是本条的核心，别再踩）**:

- **「爆」是干净信号**：能爆通常得内容够好【且】拿到分发；高互动很难靠偶然/账号刷出。→ TV 正面飞轮（爆款→经验卡→
  管家注入）建立在这个干净信号上，成立。
- **「趴」是脏信号**：不爆有一堆**与内容无关**的无辜解释——**撞流量墙**（没进流量池就死、根本没被看到 → 低互动跟
  内容好坏零关系）、**账号问题**（权重低/限流）、选题时机/运气。三者在数据里**很难干净拆分**。
- 一句话：**「赢」需要真的好；「输」有太多无辜的理由。** 把 `趴` 一概当差笔记 → 把被埋没的好内容也标成垃圾 →
  **污染负面特征库**。
- 反过来：**人工显式标 negative = "我看了内容、判定它就是差"**，是针对内容本身的主动判断、没有流量墙/账号混淆 →
  这才是可信的负面信号。

**Rejected**:

- **"用 TV 的 `趴` 笔记做负面飞轮 / 负面本质源"** —— 拒绝。混淆项（流量墙/账号/时机）无法干净剥离，会污染特征库。
  （唯一勉强可控的一小片：**曝光高但互动率极低** = 被分发了仍不被买账；但仍有受众错配/账号混淆，最多弱参考、不作主源。）
- "把 AW 负例回流进 TV `notes` 表" —— 拒绝（同 D-027：notes 是【已发布爆款事实】层，未发布废稿不混）。

**Implications**:

- 负例现状**维持不动**：AW 本地、人工标注为主（`extract_negative_examples_from_autowriter.py` 只产**候选**写
  `example_label_proposal`，人工 UI 确认才落 `example_label='negative'`）；**TV 不掺和、不推负面、不从 `趴` 推**。
- **跨产品避坑特征 = roadmap 空白项（非 bug）**：要做的话——源用 AW 人工标负例、TV 管家萃取反面本质、管家 borrow
  时注入避坑段；优先级低于"灌料 + L3"。**登记备查，别再有人（含 AI）想着"用趴做负面飞轮"重踩。**
- ⚠️ 内部逻辑纠错留痕：Session #18 讨论中一度提出"负面飞轮 from `趴`"，被策略 lead 当场否掉（理由即上方 Why），
  本条把"为什么不能这么做"固化进决策层，避免反复。

---

## D-041 · 写作台能力外置为 MCP（落在 autowriter，不在 TV）；TV 侧只出词表与盲点修复

**日期**: 2026-08-22

**What**: 三件事：

1. **autowriter 内容工作台的 Streamlit 界面停用**，它值钱的四个机制（分层硬约束 /
   调校笔记自动萃取 / 正负例池 / 语义查重）重做成 MCP 工具服务 `deskcore`，挂到
   WorkBuddy / Claude Code / CodeBuddy。Supabase 里的 `autowriter` schema 一行不迁。
2. **`deskcore` 落在 autowriter 仓，不在 Truth Vault。**（见下方 Rejected 第一条 ——
   这一条是本决策最要紧的边界。）
3. **TV 侧的交付物只有两样**：受控词表的机器可读导出（`schemas/controlled_vocab_v0_2.json`）
   + 正例饱和度监控的盲点修复（`schemas/notes_v1_8_...sql`）。

**Why（为什么 deskcore 不能放 TV）**:

- `README.md` 的边界写死了：Truth Vault **不是**内容生产工具（生产由 sanshengliubu /
  autowriter 做）。deskcore 的 `check_drafts` 会 reject 稿子、`draw_angles` 替人决定
  每篇写什么角度 —— 这是内容判断，属 Layer 3，**直接违反原则 1「管家做查询，不做判断」**。
- 数据流向也是一边倒：deskcore 十个工具里九个只读写 `autowriter` schema，新增的四张表
  全在 `autowriter` 下。唯一碰 TV 的 `borrow_lessons` 是**走 HTTP 调 librarian** ——
  跟 autowriter 现有的 `librarian_client.py` 是同一个消费者姿势。消费者住自己仓里，
  ssll 和 autowriter 都如此，deskcore 没有例外的理由。
- 放进 autowriter 还能**真正瘦身**：`memory.build_layered_system_prompt` /
  `memory.generate_calibration_notes` / `db.list_example_items` / `dedup.py` /
  `librarian_client.py` 全都已经在那边了。放 TV 等于把这些重写一遍（实测约 400-500 行
  重复），两份「怎么拼分层 prompt」的代码分居两仓是最容易烂掉的那种结构。

**Why（重复率的四个根因 —— 这部分的诊断在 TV 侧留档，因为它解释了 §3 的盲点修复）**:

- **硬闸默认关着**：`config.py:132` `ENABLE_DEDUP_REGEN` 默认 `"0"`，查重命中只写警告不拦。
- **只比标题且阈值 0.92 过高**：换说法的同角度标题普遍落在 0.85-0.90 全部溜过。
- **提示词侧只看最近 20 条**：`db.py:1556` 捞 150 条，`generator.py:1384` 一句 `[-20:]` 扔掉 130 条。
- **正例池 recency top-5 构成趋同回路**：模型模仿最近 5 条 → 新稿被标 positive →
  窗口滚动 → 语感越收越窄。

第四条此前**完全不可见**：监控它的 `check_positive_saturation.py` 只统计
`external_source='truth_vault'` 的行，而 push 通道从没真跑过（那列生产库里全 NULL），
所以它**从上线起永远打印「没有正例」**。它测不到运营手标的 native 正例 —— 而那才是真正在
注入 prompt 的池子。这个回路跑了多久没人知道。**这是 TV 侧必须修的，因为 view 在
`truth_vault` schema 下。**

**Rejected**:

- **「deskcore 放 truth-vault，跟 librarian/onboarder/worker 并列」** —— 拒绝，理由见上方
  Why 第一节。⚠️ 本条曾被实际写成代码并开了 PR#103，是**违反 README 边界的实现**，
  经用户当场指出后撤回。留档防止再犯：`autowriter-migrations/` 目录存在于 TV，是因为
  TV 当年为**集成**改 autowriter 的 schema（001-006 全是集成产物，007 只是
  `db.py::CREATE_TABLES_SQL` 的快照）；那不构成「TV 拥有 autowriter schema」的通则，
  更不构成「autowriter 的新能力可以住进 TV」。
- **「完全退役工作台、记忆从头积累」** —— 拒绝。40 项目 / 269 条记忆 / 103 条已确认负例 /
  调校笔记是几年积累，重新驯化的成本远高于换个头。
- **「全部团队共享记忆」** —— 拒绝。会抹平个人风格，而「像我在说话」正是这次要保住的东西。
  口径定为**项目规则团队共享 + 个人风格私有**。
- **「用 DeepSeek Harness 做底座」** —— 拒绝。它是 2026-08-13 发的开源 agent 运行时框架，
  解决「agent 怎么跑」；缺的不是运行时，是记忆的内容和结构，那部分自己已经有了。
- **「autowriter 手抄一份词表」** —— 拒绝。`onboarder/vocab.py` 已经是 docs/05 的手抄副本，
  再加一份跨仓手抄必然漂移。改为 TV 导出 `schemas/controlled_vocab_v0_2.json`，
  消费方原样 vendor 并记校验和。

**Implications（TV 侧）**:

- **`schemas/controlled_vocab_v0_2.json`** = 词表的机器可读权威导出。**只导出 TV 拥有的层**
  （essence 维度 + 跨仓共享分类）；表层的标题句式/词感/切入角度不在此列 —— 那是各生产系统
  自己的东西，半衰期 6-12 个月，本来就该独立演进（README 原则 2 的 Surface/Essence 分层）。
- **改词表现在要三处同步**：docs/05（人类可读权威）→ `schemas/controlled_vocab_v0_2.json`
  （机器可读导出，CI 保证一致）→ `onboarder/vocab.py`。下游 vendor 方按校验和跟进。
- `schemas/notes_v1_8_...sql`：去掉 `external_source` 过滤，补 native/tv/可测条数三列，
  且 **`dominant_lever_ratio` 的分母改为「可测条数」** —— 一条都测不到时报 NULL 而不是 0
  （0 会被读成「多样性很好」，是要避免的假阴性）。CI 有两段断言钉死这个行为。
- **监控本身也要被监控**：`check_positive_saturation.py` 在 `daily-sync.yml` 里是
  `|| true` 调的（饱和不该拖红整轮同步），但裸 `|| true` 连**崩溃**一起吞。修 v1_8 的
  同一个 PR 里，渲染循环就因此带过一个 `pool_n` 未赋值的 `NameError` —— 只要 view 回
  任何一行就必崩，而崩了之后脚本天天「跑过」、天天什么都没测，**v1_8 要修的盲点换个
  形式原样回来**。两道补丁钉死：① `report()` 抽成不碰网络的纯函数，CI 拿假行跑完整
  渲染路径（8 个用例，含"部分可测但 ratio 好看"这条 round-2 判据）；② 正常跑完打
  `SATURATION_CHECK_DONE rc=` 哨兵行，daily-sync 靠它区分崩溃与饱和 —— 因为 Python
  崩溃的退出码也是 1，跟本脚本「确实饱和」的 1 撞车，光看退出码分不出来。
- TV **不持有** deskcore 的任何代码、迁移或部署配置。相关 followup 记在
  [docs/10-sister-repo-followups.md](docs/10-sister-repo-followups.md)。

**Implications（autowriter 侧，本仓不实施、仅登记）**:

- `deskcore/` 作为 MCP 服务落 autowriter，复用其 `db.py` / `memory.py` / `dedup.py` /
  `librarian_client.py`，只新增：发牌台账、成稿指纹库、个人调校笔记分层、身份解析。
- 四张新表进 `db.py::CREATE_TABLES_SQL`（fresh install）+ autowriter 自己的 `migrations/`（增量）。
- **user_id 必须用库里已有的 UUID**，不要新造 —— `autowriter-migrations/RUNBOOK.md:150-153`
  记过：写 service account UUID 导致 RLS 屏蔽、`list_example_items` 永远 0 行、飞轮静默断开。

---

## D-042 · 分页必须带唯一稳定排序键；worker 侧加每脚本互斥锁

**日期**: 2026-08-23

**What**: 三件事，都是「跑得好好的、其实一直有洞」那一类：

1. **`fetch_all_pages()` 的 `order_by` 改为必填关键字参数**，24 个调用点全部显式传入
   唯一且稳定的排序键（`_common.py:813`）。
2. **Railway worker 加每脚本互斥锁**（`worker/app.py`），抢不到 → `409`；
   `daily-sync.yml` 加 `concurrency` group + `timeout-minutes`，并把 `409` 归入
   **瞬时失败**（幂等下轮续，不拖红）。
3. **`/health` 自曝配置**（worker），把「没配 `WORKER_API_KEY` = 谁都能调」这件事
   显式暴露成 `auth.ok=false`，而不是只在代码里静默放行。

**Why 1（无序 OFFSET 分页会丢行，而且不报错）**:

OFFSET 分页的每一页是一次**独立的 HTTP 请求**，各自的事务快照、相隔数秒。SQL 对没有
`ORDER BY` 的查询**不保证任何行序** —— 两次请求的顺序完全可以不同，于是跨页时有的行被
跳过、有的行被取两遍。**不抛异常、不打警告**，脚本照常打印成功。

这不是理论洁癖，本库两个条件都占齐：

- `synchronize_seqscans = on`（PG 默认）：seq scan 允许从表中间开始、绕回开头。
- `truth_vault.notes` 插入 4,223 行却被 UPDATE 过 120,853 次（每行约 28.6 次），
  `metric_snapshots` 5,712 行 / 109,876 次。每次 UPDATE 都把新元组写到可能不同的页 ——
  物理顺序被反复重排。

审计时已有 4 个调用点实际跨过 1000 行页边界。

**两条实现约束**（都验证过，别改回去）:

- `.order()` 是**追加**语义（postgrest-py 把新列拼到已有 order 串后面），只能在循环
  **外**调一次；放循环里会拼成 `id.asc,id.asc,id.asc,…`。
- `.range()` 用 `params.add()` 而非 `set()`，循环里重复调会累积成
  `offset=0&offset=1000&offset=2000&…`。实测 PostgREST 取**最后一个**，所以现在能正常
  翻页 —— 但这是**未文档化行为**，万一哪天改成取第一个，每页都返回同一批行、
  `len(page)==page_size` 永真 → **死循环**。函数里的 `seen` 去重兼进度检查就是这条的
  保险：一页里一条新行都没有就报错，不静默转圈也不返回重复行。

**排序键的选法**：`rank_score` / `injection_score` 这类含 recency 项、随墙钟连续变化的
计算列**不能**当唯一键（页与页之间它就重排了）。它们保留作**主排序**（先 `.order(...)`），
本函数再追加唯一键作次级键把顺序钉死 —— `curate_flywheel_lessons.py` /
`preview_injection_candidates.py` 都是这个形状。

**Why 2（两个 workflow 打同一个 worker，谁都不知道对方在跑）**:

`daily-sync.yml` 和 `backfill-essence.yml` POST 的是**同一个** `/annotate-essence`。
`annotate_essence_pass.py` 开工时 `SELECT essence_annotated_at IS NULL` 拿一批 ——
两个 run 同时跑就各自快照**同一批**笔记，重复烧 LLM、且非确定性互相覆盖 essence。

`backfill-essence.yml:30` 已有 concurrency group，但它只挡 backfill 自己、而且是
per-project，**挡不住跨 workflow 相撞**。那道闸在 GitHub 侧，而真正被共享的资源是
worker 这一个进程 —— 所以锁必须落在 worker 里。GitHub 侧的 group 只解决
daily-sync 自己（cron 与手动 dispatch）相撞。

`409` 必须归**瞬时失败**：worker 忙 = 够到了、没干活、完全幂等，跟网关超时同类。
若判成 systemic，第一批就 409 会让整个夜间同步报红 —— 加锁反而制造告警噪音。

`timeout-minutes: 120`：近 30 次 run 实测 15-38min，GitHub 默认 360min。某次
curl/worker 挂死会白烧 6h runner，并把下一天的 cron 顶到排队。

**Why 3（`/health` 说 ok 不等于配置是对的）**:

`_check_auth()` 在没配 `WORKER_API_KEY` 时**静默放行**（dev 模式）。这在本地是便利，
在 Railway 上就是「公网裸奔但看着一切正常」，而且**没有任何地方看得出来**。
docs/19:180-200 记过同型事故（配置错被 except 吞掉，外面永远 200，查了很久）。

`ok` 保持 `True` 不变（Railway healthcheck 靠它起容器，未配 key 仍是有意的 dev 模式），
要看的是 `auth.ok`。只回显**有没有配**的布尔，绝不回显 key 本身 —— CI 有断言钉死。

**Rejected**:

- ❌ **把 `library_version` 从 `max(curated_at)` 改成 `max(updated_at)`。**
  审计初稿据 `notes_v1_4_flywheel_lesson_cards.sql:39` 的注释（写着
  `library_version = max(updated_at)`）判它是 P0，因为视图第 111 行只导出 `curated_at`。
  **实测推翻了这个判断**：`curate_flywheel_lessons.py:143` 每次 upsert 都显式写
  `curated_at = NOW()`，重策展照样让缓存失效 —— 生产库 347 行里 29 行 `updated_at >
  curated_at`，但**全部是 ~1 秒**的时钟/往返噪音（`curated_at` 截到整秒、`updated_at`
  带微秒），没有任何真实漂移。改成 `updated_at` 反而更差：微秒精度 + 任何非策展 UPDATE
  都会把整个缓存打穿。**真正的缺陷只是那条注释写错了**，已改注释，不动视图与代码。
  记在这里是因为「按注释判 bug」这个错法值得留档。
- ❌ **`ALTER DEFAULT PRIVILEGES` 收紧 `public` schema 的默认写权限。**
  能一劳永逸覆盖未来所有视图，但 `public` 是与三生六部共享的 schema
  （`dashboard/lib/supabase.ts:11` 记了它 RLS-off 且 anon 可读），改默认值会波及对方
  的写入，不该由本仓单方面决定。改为只撤**已存在**的 `v_dash_*`，并在文件头写明
  「新增看板视图后请重跑本文件」。

**Implications**:

- 新写 `fetch_all_pages` 调用点漏传 `order_by` 会被 `TypeError` 挡住（运行时），
  CI 另有一道 **AST 扫描**在合并前就拦（用 AST 而非 grep：grep 会被注释和字符串里的
  `order_by=` 骗过去，也读不出跨行调用）。已反证过 —— 还原任一调用点，CI 立刻红。
- `schemas/security_revoke_anon_write_dash_views.sql` **是纵深防御，不是补漏**：
  现有 18 个 `v_dash_*` 全是聚合视图，`is_insertable_into = 'NO'`，PG 在重写阶段就拒写
  （`cannot insert into view … aggregate functions are not automatically updatable`），
  跟权限无关 —— 今天拿公开 anon key 也写不进去。撤的是**将来有人加了单表直通视图会自动
  继承的**那份权限：那种视图 PG 判定为 auto-updatable，而这些视图是
  `security_invoker=false`（以 owner 身份跑、绕开底层 `truth_vault` 的 RLS），
  于是「anon key 可写 → 经视图穿透 RLS 写进 truth_vault」，且不会有任何报错。
  PG 16 上实测过整条路径：建单表直通视图 → `is_insertable_into='YES'` →
  `SET ROLE anon; INSERT` → `INSERT 0 1`，行进了底表；跑完本文件同一句 →
  `permission denied`，读仍正常。CI 每次复跑这个探针。
- **2026-08-23 已 apply 到生产**（`kduysqedr`，走 Supabase 迁移历史落成
  `security_revoke_anon_write_dash_views`，而不是裸跑 —— 迁移表里留得下痕迹，
  免得又出现「合了代码不等于上了 schema」）。应用前后都在**生产库**上量过：

  | | 应用前 | 应用后 |
  |---|---|---|
  | `public` 下 anon 有 INSERT 的关系数 | **18**（全是 `v_dash_*`） | **0** |
  | 同上，`authenticated` 写权限（INS/UPD/DEL/TRUNC） | 18 | **0** |
  | 18 个 `v_dash_*` 仍可被 anon / authenticated SELECT | 18 / 18 | **18 / 18** |
  | 以 `anon` 身份实读 `v_dash_overview` | 1 行 | **1 行** |
  | 非 `v_dash_*` 的 public 关系被误伤 | — | **0**（撤之前该数就是 0，撤之后仍是 0） |

  幂等性也在生产上复跑验过（再跑一遍，anon 写权限仍 0、读仍 18）。
  `get_advisors` 无新增 —— 剩下的 `security_definer_view` / `rls_disabled_in_public`
  ERROR 全是本次之前就有的。
- 约定不变：**只对运行时已存在的 `v_dash_*` 生效，新增看板视图后要重跑本文件**
  （`schemas/` 里其余 REVOKE 文件同此约定）。

---

## D-043 · 迟到的人工决策：时间窗改成 `created_at` **OR** `updated_at`（不是替换）

**日期**: 2026-08-23

**What**: `scripts/sync_autowriter_decisions_to_prepublish.py` 的时间窗从
`created_at >= since` 改成 `created_at >= since OR updated_at >= since`。

**Why**: 这个脚本把 autowriter 侧的人工审稿决定（approved / needs_revision）归档进
`truth_vault.prepublish_evaluations`。`autowriter.items` 从前没有 `updated_at`，
于是「三个月前创建、今天才被人工改状态」的 item 会被时间窗**静默**筛掉 ——
脚本照常打印成功，少收的那些没有任何地方看得出来。当时的兜底是把 `--since-days`
默认从 90 抬到 365，属于拿窗口宽度换命中率。

aw 的 `migrations/001_deskcore.sql` 补上了 `items.updated_at` + 触发器，
2026-08-23 已应用到生产，这条局限才真正可解。

**为什么是「或」而不是「换成 `updated_at`」**（这是本条真正的决策）:

- `updated_at` 分支是想要的能力：捞回迟到的决定。
- `created_at` 分支是保底。`updated_at` 是 **nullable** 列（`DEFAULT now()`，
  生产当前零 NULL），哪天有人显式插了 NULL，只写 `.gte("updated_at", …)`
  会把那些行**静默丢掉** —— 正好又是这次审计一路在治的那个病。
- 留着 `created_at` 分支之后，**新窗口是旧窗口的严格超集**，这次改动在数学上
  不可能比改之前更差。这个性质比「哪个列更准确」重要。

**生产实测**（都在 `kduysqedr` 上量的，不是照文档推的）:

- 触发器 `WHEN (old.status IS DISTINCT FROM new.status OR old.example_label IS
  DISTINCT FROM new.example_label)` —— 事务内改一条 `approved → needs_revision`，
  `updated_at` 从 backfill 值（= `created_at`）跳到 `now()`，然后 rollback。
- PostgREST 的 `or=` 语法在**生产实例上**验过能过：解析与列解析都过了、只在权限阶段
  被 anon 拦（42501）；故意写坏括号是 `PGRST100`、写不存在的列是 `42703` ——
  三种错互相区分得开，所以「过了解析」这个结论站得住。
- supabase-py 2.30 渲染成 `or=(created_at.gte."…",updated_at.gte."…")`，
  与 `status=in.(…)` 是两个独立 query param，PostgREST 之间取 AND。值用双引号包住，
  时间戳里若出现 `,` `.` `:` 不会被当成逻辑树的分隔符。

**Rejected**:

- ❌ **只按 `updated_at` 过滤。** 干净，但 nullable 那个洞会静默吃行。
- ❌ **把 `autowriter.items.updated_at` 改成 NOT NULL。** 能一劳永逸，但那是 aw 仓
  owned 的表，从 TV 仓单方面 `ALTER` 会让 aw 的迁移文件与生产库对不上 ——
  正是「代码与 schema 分家」那个病。要改应该走 aw 的迁移。
- ❌ **把 `--since-days` 默认缩回 90。** 抬到 365 的原因（没有 `updated_at`）确实没了，
  但窗口的含义也变了：现在是「最近 N 天**被动过**的决定」。cron 停摆超过 N 天，
  停摆期间改的决定就再也捞不回来。窗口宽一点是纯赚，保持 365。

**Implications**:

- CI 加了一道用例，对**两种**错误实现都会红：退回只按 `created_at` → 迟到决策捞不回；
  改成只按 `updated_at` → `updated_at IS NULL` 的行被静默丢掉。假件不是只记调用串，
  而是把谓词真的求值一遍，所以测的是「筛出来的是不是想要的行」。三种改坏方式都反证过。
- 脚本现在单独数并打印「其中 N 条是创建后才改过状态的迟到决策」。不打这个数的话，
  这条修复就又变成「改了，但没人知道有没有起作用」—— 与 `check_positive_saturation.py`
  当年那个盲点同型。

---

## D-044 · 批量接表：编排放调用方（不做服务端批量端点）+ 已有 mapping 默认不覆盖

**日期**: 2026-08-28

**What**: 接表从"一次一张"扩到"一次一批"，四件事：

1. **编排在调用方**（`onboarder/batch.py`），逐表打现有的 `POST /onboard`。**不**新增
   `/onboard-batch` 服务端端点。
2. **`/onboard` 接受 `url`**（整条飞书链接，含 `/wiki/` 形态），不再强制先抠出
   `app_token` + `table_id`。解析在 `onboarder/links.py`（纯标准库、不联网）。
3. **已存在的 `mappings/<id>.yaml` 默认跳过，且在起草之前就跳**；要重出草稿须显式
   `--overwrite`。
4. `onboard-table.yml` 的 dispatch 输入改走 `env:`，不再插值进 `run:` 的 bash。

**Why（为什么批量不做成服务端端点）**:

- **超时**：单表 = 全表 distinct 扫描 + 一次 16k 输出的 LLM 调用，现有 workflow 给的是
  `--max-time 220`，大表已经偏紧。服务端把 N 张串进一个请求必然超时，而 HTTP 请求是
  原子的 —— **超时那一刻，已经跑完的那几张也一起没了**。逐表独立请求则是"第 6 张挂了，
  前 5 张的草稿还在盘上"。
- **无状态**：Railway 重启 / 重部署会丢内存里的批次状态。要么加一套作业存储，要么接受
  "批量跑一半没了"。为一年几次的接表建作业存储不划算。
- **不新增鉴权面**：SUP-001 那条跨服务守卫的用例表（三个服务 × 三种鉴权态）不用动。
  新端点意味着新的 fail-closed 判定要重新证一遍。

**Why（为什么已有 mapping 默认不覆盖 —— 这条是本决策最要紧的护栏）**:

`mappings/*.yaml` 里的判断项（方向拆解 / tier 阈值 / 合规）是**策略 lead 审过**的，
是 README 原则 1「管家不做判断」那道人工闸门的**唯一实物**。重跑一版新草稿盖上去，
等于把人拍过的板悄悄换成模型的新猜测 —— 而在 diff 里它长得就像一次正常更新。
一张表时人还看得见；一批 6 张，没有人会逐个核对。

跳过还必须发生在**起草之前**：放在后面的话，每张被跳过的表仍要白烧一次全表扫描
加一次 LLM 调用。

**Why（为什么链接解析要单独一层，而不是让人自己抠 id）**:

运营手里只有浏览器地址栏那条链接。抠 `app_token` / `table_id` 是人肉的、每次都要做、
而且**抠错了要跑完一整轮飞书全表扫描才发现**。三种"看着能跑、其实是另一回事"的形态
在 `links.py` 里显式区分，不猜：

- `/base/` 与 `/wiki/` —— **一视同仁**，token 直接当 `app_token` 用，解析阶段零联网
  （2026-08-28 Ziao 口径：飞书两种 token 都收；挂在知识库下的多维表是常态，地址栏给的
  就是 `/wiki/` 形态）。只在**第一次取字段失败之后**才花一次调用去换 `obj_token` 重试，
  换成功后**后续取数全用换过的那个**——一半用新一半用旧会表现成"字段拉到了但一行数据
  都没有"。两次都失败时抛**第一个**异常：权限不足 / 表不存在才是要看的，"它不是知识库
  节点"只是兜底路径的副产物，拿它报错会把人带偏。
- `larksuite.com` —— 国际版 Lark，API 主机是 `open.larksuite.com`，而本仓客户端固定
  `open.feishu.cn`。不拦的话表现为"这张表不存在"。
- 缺 `?table=` —— 多表 base 的链接省略 `table` 时是**歧义不是缺省**：只有一张表就用它，
  多张则报出候选让人选。猜错的代价是一份接错表的 mapping。

**Rejected**:

- ❌ **服务端 `/onboard-batch`**。理由见上方三条（超时 / 无状态 / 鉴权面）。
- ❌ **并发跑多张表**。省下的是几分钟，换来的是飞书限流和网关并发上限这两类
  "只在批量大的时候才出现"的故障 —— 而批量大正是它最不该挂的时候。串行。
- ❌ **失败自动重试**。批量失败几乎都是权限 / 链接 / 表本身的问题，重试一万次还是同一个
  错，而每次重试都是一次全表扫描。改成：汇总里直接吐出一份**可粘贴重跑**的失败清单。
- ❌ **另起一个 `onboard-tables.yml`，与单表 workflow 并存**。两份 git 逻辑必然漂。
  改成单表内部当 1 条清单跑，`onboarder/draft-<id>` 这个分支名对老用法保持不变。
- ❌ **`project_id` 只做格式校验**。它会拼成 `mappings/<id>.yaml` 落盘、`git add`
  再 push，中间没有人看一眼，所以按**白名单**收（黑名单永远漏）。

**Implications**:

- 退出码语义：`0` 全干净 / `1` 有表失败或校验不干净（草稿照样已写盘，红是为了"别直接
  merge"，不是为了丢产出）/ `2` 清单本身有错（**一张都不跑** —— 跑一半会留下"部分接进来
  了"的中间态，要靠人去分辨哪几张成了）。
- `draft()` 现在把草稿的顶层 `project_id` 钉成请求值。文件名由请求定、yaml 里那一行由
  模型写，漂了就会撞上 CI 的 mapping lint —— 而它是**已知输入**，不是判断项，与
  `sync_config` 里的 `app_token` 同一性质。
- CI 新增两道守卫：批量自检（路径穿越 / 链接三态 / 逐表隔离 / 覆盖闸 / 汇总表格不被异常
  消息撑烂）+ 接表 workflow 的脚本注入闸。后者对坏样本反证过会红。

---

## D-045 · 假爆款那道网按【语义】收，不按某一种写法收；短针遮长针的列序做成 lint

**日期**: 2026-08-28

**What**: 两处修 + 两道守卫，都指向同一个失效模式 —— **运营手工标的假数据以真爆款身份进飞轮**。

1. `sync_feishu_notes_to_truth_vault.py` 判 `data_quality_flags.synthetic` 的那道网，
   从写死的 `"伪爆贴" in tier_src_str` 改成 `_SYNTHETIC_TIER_SRC_RE`
   （`伪爆[贴帖]|伪\d+评`），并把命中的原串写进 `synthetic_reason`。
2. `_common.load_mapping()` 新增 `_reject_shadowed_tier_rules()`：`tier_extraction.rules`
   里靠前规则的短针，不许是靠后规则某根针的**子串** —— 那会让后面那条整条不可达。

**Why（这不是一次拼写订正，是那道网的收法本身错了）**:

`transform_row` 里那段注释是这么承诺的：synthetic **独立**于 tier 取值判定，
"确保假爆款【不论 tier 怎么定】都被剔出爆款/飞轮"。它独立于 tier 判，但它**没有独立于
运营的写法** —— 只认「伪爆**贴**」。

2026-08-28 批量接的 BJS_phase1 / SPX_phase1 两张表，运营写的是「伪爆**帖**500」。
帖/贴 在这个语料里从来是混用的：库里既有 mapping 的 tier 规则**早就两个都收**
（XIWU、BJS 都写 `["爆贴", "爆帖"]`）—— 也就是说，"运营两种都写"是**已知事实**，
只有这道网还按单一写法收。

BJS 这张表上两个缺陷刚好叠在一起，后果是最坏的那种：

| | |
|---|---|
| tier 规则 `["爆贴","爆帖"]→爆` 排在 `["伪爆帖","伪20评"]→数据异常` **前面** | 「伪爆帖500」首个命中 → `tier=爆` |
| synthetic 那道网只认「伪爆贴」 | `'伪爆贴' in '伪爆帖500'` = False → `synthetic=false` |

`tier=爆` + `synthetic=false` = **运营亲手标的假爆款，进种草飞轮、进看板爆款率、
进书架经验卡**，全程零告警。两道防线各自看都"正常工作"，是它们同时对同一种写法失明。

**Why（为什么列序做成 lint 而不是只改 BJS 那一张）**:

`_first_matching_tier` 取首个命中，所以"短针在前"= 后面那条整条死掉。这是**纯静态可查**的：
不需要数据、不需要跑 sync。写完拿全部既有 mapping 扫了一遍 —— **10 张零误报，唯一命中
就是 BJS 这条**。既然一次就能证明它精确，就没有理由只修个例、把同一个坑留给下一张表。

报错直接给修法（"把「伪爆帖」那条**上移**"），因为修法与既有的
「爆贴预备 先于 爆贴」是同一条规律，不是新知识。

**Rejected**:

- ❌ **只把 `"伪爆贴"` 改成 `("伪爆贴", "伪爆帖")` 两个字面量**。下一种写法（伪爆款 /
  伪数据 / 假爆贴）还是漏。按语义收：`伪爆[贴帖]` 覆盖帖贴混写，`伪\d+评` 覆盖
  「伪20评」这类人工补的假互动数 —— 后者同属"指标不可信"，两张表的状态列就是这么写的。
- ❌ **把 `伪` 开头一律判 synthetic**。过宽，会把正常状态词误伤成假数据，
  而误伤的方向是"真爆款被剔出飞轮"，同样有代价。
- ❌ **靠 tier 规则自己写对来兜底**。tier 是 mapping 里的**判断项**、每张表由模型起草，
  而 synthetic 是引擎侧的**护栏** —— 护栏依赖被护对象写对，就不是护栏了。
  这正是 `transform_row` 当初把两者分开判的原因，本次只是让它真的做到。
- ❌ **只在 preflight 里查列序**。preflight 是接表流程里的一步，而 `load_mapping` 是
  **每次 sync 必经**；护栏放在必经路径上。

**Implications**:

- `数据异常` 不在 `_TIER_RANK` 里（rank 0），所以多选 cell 同时挂「伪爆帖500 / 爆贴」时，
  取最高级仍会得到 `爆`。**这条没改** —— 它是 D-033 的既有语义（多选取最高级），
  而 synthetic 那道网现在会独立标住这一行，飞轮/看板口径是干净的。
  真要改 tier 本身的取值，是策略口径问题，留给策略 lead。
- BJS_phase1 的草稿仍需在 PR 上把那两条规则**调序**后再 merge：lint 会挡住它进 sync，
  但草稿分支上的 yaml 尚未被 lint 覆盖（草稿还没进 `mappings/`）。

---

## D-046 · 写库的列必须先落库：迁移没跑 = 每一条 upsert 都失败，且要 4 天才有人看见

**日期**: 2026-08-30

**What**: 把 `schemas/notes_v1_9_last_seen_reconcile.sql` 应用到生产 Supabase
（`truth_vault.notes` 加 `last_seen_at` / `last_seen_run_id` + 索引）。

**故障**: Daily TV sync **连红 4 天**（run #133 08-27 → #136 08-30），每次
`feishu_sync` 步骤挂在 RIO_phase1 / WTG_phase1 上：

```
PGRST204: Could not find the 'last_seen_at' column of 'notes' in the schema cache
```

**根因不是代码，是「合并 ≠ 部署」**：PR #109（COR-011 对账，08-27 合并）让
`transform_row` 在**每一条** note upsert 里带上 `last_seen_at` / `last_seen_run_id`，
但那两列所在的迁移 `notes_v1_9` **从来没在生产库上跑过**。第一个变红的 run
（#133）就是 #109 合并后的第一次 cron —— 时间线与报错列名双向吻合。

`scripts/README.md` 早就把这条写成硬前置，原文：

> ⚠️ **这一条是硬前置, 不是可选**: 没跑它的库上，**每一条 note 的 upsert 都会失败**
> （column does not exist），而不是降级。

**所以文档没缺，缺的是【强制】。** 这是本仓第二次栽在同一类问题上 ——
2026-08-28 接表时六张表全报 `missing required field: app_token`，
根因是 Railway 上还跑着旧版 `app.py`（D-044 的部署提醒段）。两次都是
「代码进了 main，承载它的运行时没跟上」，而两次都**没有任何症状**能提前暴露：
`/health` 照常 200，CI 照常绿，只有真跑起来才炸。

**为什么这次的表现形式特别坏**：

- 不是整步一次性失败，是**逐行**失败 → 日志里几百条一模一样的 traceback，
  真正的一行信息（缺哪个列）被淹在里面；
- **当天 16 个项目里只有 RIO / WTG 报错**，于是整轮看起来像"个别项目有问题"，
  而不是"库结构不对"。但那 14 个**不是"没事"，是压根没走到 upsert** —— 这一点
  一开始写错了（codex review 指出，2026-08-30 按 run #136 日志核实订正）：

  | 情况 | 项目数 | 实际发生了什么 |
  |---|---|---|
  | `sync_interval: on_demand` | **13** | 夜间 cron 直接跳过，**一行都没读** |
  | `daily` 且全部 quarantine | 1（OKMAN） | `total 350 / quarantined 350 / upserted 0` → `pending_notes` 空，没有可写的行 |
  | `daily` 且真写库 | 2（RIO / WTG） | `errors 391` / `errors 710` —— 全部是这个缺列错 |

  **没有"新行 vs 老行"这回事**：`upsert_notes_batch` 每轮把该项目**所有**有效行
  重写一遍，不查存在性也不比对是否变化。所以判据是「这轮有没有行走到 upsert」，
  跟"有没有新数据"无关。把它记成"只有有新行的项目才命中"会把下一个人往
  "查哪个项目有新数据"的方向带偏 —— 而正确的方向是"查哪个项目今晚真的写了库"。

- 另外 `last_seen_*` 只在 **full_scan** 时才盖（无 `--limit` 截断、无飞书抓取失败、
  `errors == 0`、非 dry-run，见 `sync_feishu_notes_to_truth_vault.py:1068-1079`）。
  这构成一个**自锁**：第一条 upsert 失败 → `errors > 0` → 后续轮次连戳都不盖了，
  但**失败照旧**，因为 payload 是在盖戳之前就带上这两列的。
- `feishu_sync` 之后的步骤（comments / essence / curate / ssll）**全绿**，
  汇总行只有一句 `failed steps: feishu_sync`，很容易被读成偶发。

**Rejected**:

- ❌ **在 sync 里 try/except 掉这个列**（缺列就不写）。那正是 COR-011 要避免的：
  对账证据一旦可以静默缺失，`last_seen_at IS NULL` 就同时意味着"还没同步过"和
  "库没升级"，而这两者的处置完全相反。宁可炸。
- ❌ **只把 README 写得更醒目**。它已经写得够醒目了（三行 ⚠️ + 空库实测记录），
  仍然漏了 —— 靠人读文档记得跑迁移，不是护栏。

**Implications** —— 已做（2026-08-30，策略 lead 拍板"待办做"）:

`_common.assert_db_schema_ready()`，接在 `sync_feishu_notes_to_truth_vault.main()` 里
`get_supabase_client()` 之后、第一次写库之前。缺列 → 立刻 `exit 2`，消息点名缺哪些列、
该跑哪个迁移文件。**把「4 天 × 逐行 traceback」压成「5 秒 × 一行」。**

**探测手法**：拿要写的列做一次 `select ... limit 0`。列不存在时 PostgREST 直接回
42703 —— 这不是推测，正是那次事故日志里对账查询打出来的那条 warning。比读
`information_schema` 省事（PostgREST 不暴露它），也不用为此建 RPC；全程只读。
成功路径每张表一次往返（9 张，亚秒级），只有失败时才逐列复探一遍把缺的**全部**点名
（PostgREST 一次只报第一个，不复探就得一次修一个、来回好几轮）。

**为什么装在 sync 而不是各脚本各管各的**：sync 是 daily-sync 的第一步，在这里核
**整条链路**会写的列，后面 comments / essence / curate / ssll 的漂移也在开跑前就报出来，
而不是夜里跑到一半才炸。

**列清单怎么来的**：2026-08-30 用一个 workflow 把 7 个写库脚本并行盘了一遍，
再拿结果对生产库 `information_schema` 做**确定性核对**（当时 128 列全部存在，
即补上 v1_9 之后没有残留漂移）。随后一轮**对抗盘点**抓到手工清单的真洞：
`notes.synced_to_ssll_at` / `synced_ssll_reference_sample_id`（只记了 autowriter
那对孪生列，漏了 ssll 这对）+ 整张 `flywheel_librarian_cache`（它在 `librarian/`
不在 `scripts/`，按脚本盘点必然漏）。**手工列清单会漏，这就是证据。**

**三类故意不收**（写进代码注释，免得下一个人"顺手补全"反而弄坏闸）:

- **触发器写的列**（`era_tag` / `updated_at` / `ingested_at` / `audit_log.*`）——
  我们的代码从不发它们，且列与触发器出自同一个迁移文件，不可能只缺一半，
  收进来只白花往返。
- **另一个库的表**（`public.reference_samples` 在三生六部那个实例）—— 本函数拿的是
  TV 的 client，探不到，也不该由 TV 的 sync 替它把关。
- **autowriter schema** —— 跑在另一条链路上，挂了不该拖红夜间 TV 同步。

**守卫**：CI 新增一道，对旧行为反证过会红 —— 精确复现 2026-08-27 那次（notes 缺
`last_seen_at` + `last_seen_run_id`），断言两列**都**被点名、且报错说清该跑哪个迁移；
另断言清单没被删残（表 ≥ 6、notes 列 ≥ 30、必核列在场），以及**闸真的接在
`main()` 上且排在第一次写库之前** —— 只写函数不接线是这类护栏最常见的死法。

---

## D-047 · `on_demand` 闸要覆盖【每一个】自动处理步骤，不只是入库

**日期**: 2026-08-30

**What**: 判据本体移到 `_common.skip_on_demand_on_cron`（单一来源），新增
`scripts/skip_on_cron.py` 作 CLI shim，接进 `daily-sync.yml` 的 **essence 标注**那一步。

**Why**: `sync_interval: on_demand` 那道闸的注释白纸黑字写着它防的是
「新接的表（填了飞书坐标但还没 preflight 验证）被 02:00 cron 自动灌」。
但它**只实现了一半** —— 入库那步调 `_skip_on_demand_on_cron`，
而 essence 那步是裸 `for f in ../mappings/*.yaml` 全遍历，
**`sync_interval` 在整个 essence 路径里一次都没出现**。

后果不是"多跑一点"：

- 笔记一落库，**当晚**就被 LLM 按**还没拍板**的 `direction_decomposition` 标注；
- 标注按 `essence_annotated_at IS NULL` 取 → **标完即固化**，不会自动重标；
- 再顺着 经验卡 → 三生六部 → autowriter 传下去。

也就是说 README 原则 1 那道人工闸门（判断权归策略 lead）被绕过了，
而且是**静默**绕过 —— 日志里只会看到一行 `✅ essence 已全部标完`。

这次接六张表时撞上：六张全是 `on_demand`、共 120 处 `[待确认]`，
只要跑一次实跑 sync，第二天早上那 120 处 provisional 判断就进飞轮了。

**判据必须只有一份**：essence 那步没有在 bash 里重写一遍 `grep on_demand`，
而是调 `skip_on_cron.py`，它内部就是入库那步用的同一个函数。两份判据漂开的表现是
"某一步悄悄多跑了一批没验证过的表" —— 没有任何症状，正是本仓反复栽的那类。

**exit 2 取"照跑"而不是"跳过"**：`skip_on_cron.py` 判不了时（mapping 读不出来）
返回 2，调用方**照跑**。跳过是静默少干活、查起来毫无线索；照跑最多多标一次（幂等，
且下游本来就要人审）。宁可吵不可静。

**Rejected**:

- ❌ **在 essence 的 bash 循环里直接写 yaml 判断**。判据会漂，且漂开无症状。
- ❌ **让 `count_unannotated_essence.py` 对 on_demand 项目返回 0**。那会让日志打出
  `✅ essence 已全部标完` —— 一句**假话**。跳过就要说跳过。

**`curate` 是同一个泄漏口的另一张嘴 —— 已一并补（2026-08-30，策略 lead 选 A）**:

`curate_flywheel_lessons.py` 是**全局单次调用**，`fetch_uncurated_cards()` 只按
`is_curated=false`（+ 可选 `project`）取，不看 `sync_interval`。而它的候选视图
`v_flywheel_lesson_cards` 的 WHERE 只有
`tier ∈ (爆,大爆,参考)` + `tier_source ≠ 数值推断` + `publish_time IS NOT NULL`
—— **完全不要求先有 essence**。所以本次补的 essence 闸**挡不住 curate**。

**为什么只能在调用方修**：curate 的 LLM 调用跑在 **Railway worker** 上，而
`TV_SCHEDULED_RUN` 只存在于 GitHub Actions 的 job 环境里 —— 把判断塞进
`curate_flywheel_lessons.py`，它在 worker 上会**永远判成"非 cron"**，等于没加。
改 worker 协议（给 `/curate` 加个 `scheduled` 字段）则是又一次「合并 ≠ 部署」的风险，
而这一轮已经被它咬过两次（Railway 旧版 `app.py`、迁移没落库）。
`/curate` 只收单个 `project`、没有"排除某些"，所以调用方只剩**按项目循环**一条路。

**预算仍然全局共享，不是每个项目各给一份**（这一条是本次实现里最要紧的取舍）：

`CUR_LIMIT`（15）原本兼着两个作用 —— 「每日够用」+「单请求 >~15 张会撞 worker
5min 超时」。天真的循环写法会变成 `N × 15`，把每晚的 LLM 账单乘以项目数；
而共享一个 `remaining`、按每个项目**实际策展数**递减，两个作用都保住，
**总量与改动前一致**。待办没做完是幂等的（`is_curated=false`），下轮 cron 续 ——
与改动前同一条路。

**截断不许静默**：预算用完时把**剩下哪些项目**点名进 `::notice::`。
否则日志看着就像"全都策展过了" —— 而这正是本仓反复栽的那类静默。
实测 16 个项目 / 预算 15 / 每个吃 2 → 跑 8 + 推迟 8 = 16，一个都没丢。

**逐项目隔离**：一个项目系统性失败不再带走其余项目（与 essence 段同构），
但仍 `fail_count++`，收尾判红。

**守卫**：CI 那道 D-047 守卫扩到 curate —— 断言已接闸、闸在**真正发请求那一行**之前
（判据钉在 `-X POST "${WORKER_URL%/}/curate"` 上，不是任何出现 `/curate` 的地方：
注释里也会提到它，拿它比位置会把守卫变成在考注释怎么写 —— 这条是写守卫时它自己
先把我拦下来的）、按项目循环、预算共享递减、截断不静默、逐项目隔离。
已反证：把 curate 的闸拆掉，守卫变红。

---

### 第三张嘴：通道1（TV 爆款 → 三生六部）—— 唯一跨库的那张（2026-08-30，同日补）

补完 essence 和 curate、正要跑六张表实跑时发现的：`daily-sync.yml` 的
**通道1** 那一步（`sync_truth_vault_baokuan_to_sanshengliubu.py`）
**连项目循环都没有** —— 一句全局调用，而 `fetch_pending_baokuan()` 只按
`tier ∈ (爆,大爆,参考)` + `tier_source ≠ 数值推断` + 12 个月内 + `synced_to_ssll_at IS NULL`
取，**`sync_interval` 全程不出现**。

**为什么这张最要紧**：前两张的后果都还留在 `truth_vault` 自己家里（essence 标注、
经验卡都在本库，改 mapping 后还能重跑）。这一张把内容写进**另一个 Supabase** 的
`public.reference_samples` —— 三生六部的高权重检索池，直接喂写作引擎。
而 `build_reference_sample()` 带过去的字段里就有 `target_audience` 和方向拆解，
**正是那 120 处 `[待确认]` 本身**。推过去就追不回来：本仓唯一的自愈回收路径
`retract_stale_synthetic_from_ssll` 只认 synthetic，不认"方向拆错了"。

实测代价：六张表 preflight 合计 **1025 行会入库、27 条燃料（爆+大爆）**。
不补这道闸，实跑当晚这 27 条就带着 provisional 判断进了写作引擎。

**闸装在脚本里，不是 bash 循环里** —— 与 curate 的结论**相反**，因为前提不同：
这个脚本跑在 **GitHub runner** 上（不像 curate 在 Railway worker 上），
mapping 的 `sync_interval` 读得到，不必把调用拆成按项目循环。
**判据在哪儿跑，决定闸装在哪儿** —— 这是三张嘴形态各不相同的唯一原因，不是风格差异。

### 这一道【不看是不是 cron】—— 与前两道故意不同

前两道传的是真实的 `scheduled`，「只挡 cron、不挡人工」。这一道恒传 `True`，
**任何一次跑都挡**，直到该项目翻 `daily`。因为风险类别不同：

| | 写到哪 | 可逆吗 |
|---|---|---|
| essence / curate | `truth_vault` 自己家里 | 幂等，改完 mapping 能重跑 |
| **通道1（本步）** | **另一个团队的生产检索池** | **没有回头路** |

**"手动触发"并不会让那 120 处 `[待确认]` 变成已拍板。** 接表 SOP 的顺序是
preflight → 显式跑一次验证 → 拍板 → 翻 `daily`；中间那次**验证性质的实跑**
如果顺手把结果推进另一个团队的生产检索池，那不叫验证。

这一条不是事后补的原则 —— 是被自己的实跑逼出来的：补完只挡 cron 那版之后，
准备跑六张表时才意识到 `workflow_dispatch` 下 `TV_SCHEDULED_RUN=false`，
**我自己那次实跑照样会把 27 条推过去**。闸挡住了 cron，没挡住我。

**代价实测为零**：查了生产库，除 `RIO_phase1`（10 条待推，而它是 `daily`）外，
**所有 `on_demand` 项目的 ssll 待推量都是 0** —— 存量早推完了（它们的入库本来就被
cron 闸挡着，没有新行进来）。所以这道闸对现有项目是 no-op，只对新表生效。

**豁免是一个专门的开关，不是 `--project`**：`--include-on-demand`。
`--project X` **不**自带豁免 —— 一个开关一个意思，免得"我只是想定向跑一下"
顺手变成"我同意把它推进写作引擎"。永久的那条路是翻 `daily`，
与 LNKT yaml 里"翻 daily 时要同步提醒 ssll 那边对齐平台名写法"说的是同一个时刻。

**顺带修的**：这一步以前**根本不认 `PROJECT_FILTER`** —— workflow 的 `project` 输入
自己写着"只跑某个项目"，而定向跑一个项目时它照样全局推。脚本本来就有 `--project`，
接上就是。

**回收不受闸管**：`retract_stale_synthetic_from_ssll` 排在闸之前、不带过滤。
闸挡的是"往外推"，不是"把推错的拉回来" —— 后者任何时候都该跑。
CI 守卫把这个顺序钉死了。

**跳过要点名**：拦下多少条、分别属于哪些项目，`logger.info` 打出来。
静默过滤会让日志看着像"这些项目本来就没爆款"。

**判不了照推**：项目没有 mapping 文件 / yaml 读不出来 → 照推，与 `skip_on_cron.py`
的 exit 2 同取向。

**守卫**：CI 的 D-047 守卫加第 ⑥ 段。已反证这些回归各被不同断言抓住 ——
① 闸函数留着但 `main()` 不调（"只写工具不接线"，这类护栏最常见的死法）；
② 闸装到回收之前，把回收也一起挡了；③ 判不了时取向反了（跳过而非照推）；
④ 闸退回"只挡 cron"；⑤ `--project` 顺手带出豁免；⑥ 步骤不认 `PROJECT_FILTER`。
行为断言用的是 `mappings/` 里真实的 on_demand / daily 项目各一个，不是构造的假数据。

---

## D-048 · 指标藏在「键值文本」里的表：解析可以做，但解析成功那一刻会激活占位阈值

**日期**: 2026-08-31

**What**: 新增 mapping 能力 `metrics_from_kv_text`，把「键：值；键：值」文本 cell 里的指标
解析进 `notes.impressions` / `notes.interactions`；`parse_numeric` 补中文数量级后缀；
LNKT_phase1 接上该能力，**同时摘掉它的 `tier_thresholds`**。

**Why 做**: LNKT_phase1（抖音）没有独立的曝光/互动列，一次数据回收的全部指标被塞进
「数据汇总-第N次」一个文本 cell。299 行里 214 行有值，格式与本仓已有的
`parse_audience_analysis`（；分段 ：分键值）**完全同形**，可确定性解析、不需要 LLM。
不解析，这张表就永久半瞎：无指标、无数值兜底、看板无数。

**取【最后一个有值的快照】，不取各键最大值** —— 两条理由：

1. 一行的各项指标必须来自**同一次回收**。逐键取最大会出现播放量取第2次、点赞量取第3次，
   拼出来的互动率是假的。
2. 实测三次都有的 154 行里，**12 行「晚的快照反而更小」**（累计值不该降）。成因至少三种：
   第1次之后塌掉（1202→96，像换了条帖）、第3次原样等于第1次（把旧值又粘了一遍）、
   小幅回落（评论被删）。没有一条规则对三种都对，而取最大值会把第一种的 104 放大成 1202
   —— 凭空造爆款正是 D-045/D-047 一路在防的事。取最后一次永远不会大于运营最近一次读数。

**但不静默**：命中「更早的快照 anchor 更大」时写
`data_quality_flags.metrics_snapshot_regressed = {picked, picked_value, max_seen}`，可查。

### 真正的风险不在解析，在【解析成功那一刻，占位阈值会变成生效的】

这是本条决策的核心，也是差点踩进去的坑。

LNKT 的 `tier_thresholds: {爆: 50, 大爆: 500}` 在 8-30 定稿时被标成
「不生效的占位」——因为 `interactions` 全 null，数值推断永远不触发。**指标一解析出来，
这句话立刻失效**：爆=50 会把一大批行自动升成爆。

拿 214 行解析出的互动量按运营标注分组：

| 运营标注 | n | 中位 | p90 | 最高 |
|---|---:|---:|---:|---:|
| 趴 | 194 | 6 | 38 | **555** |
| 风控 | 8 | 5 | 189 | 189 |
| 参考 | 1 | — | — | 316 |
| 爆 | 1 | — | — | **412** |

**运营标「无水花」的最高一条（555）比唯一那条「爆贴」（412）还高。** 那条 9437 播放、
440 点赞的帖，运营看完仍然判无水花 —— 这张表的爆款判断不是按互动量做的。

在这种分布上设任何阈值都是错的：设 50 → 大批趴被升成爆（SPX 那个坑的放大版）；
设 556 → 唯一那条真爆反而够不着，且这个数没有任何依据。**所以整块摘掉**，
让数值推断在本项目上不触发，tier 全部以运营的「流量状态」为准。

缺 `tier_thresholds` 是安全的（引擎 `mapping.get("tier_thresholds") or {}` → 不提升；
`recommend_tier_thresholds.py` 也会跳过），**这是结论不是漏配**。

### `parse_numeric` 补中文数量级后缀

`"1.4万"` 之前会 `ValueError` → 返回 `None`，也就是**静默丢掉**。丢的还偏偏是
数大到显示成万的那批行 —— 等于把高分行系统性地从指标里择出去。
只在原本会返回 `None` 的路径上补，所以不改变任何已经解析成功的值；
全库实测受影响 3 行（LNKT 2 + 其它 1）。裸「万」/「abc万」/bool 仍返回 None。

### 比率键跳过是【防御层】，不是当前唯一屏障

`parse_kv_metrics` 显式跳过带 `%` 的键。今天的 `parse_numeric` 对 `"49.18%"` 本来就返回
None，所以删掉这两行行为暂时不变 —— 写守卫时实测确认过，**第一版守卫因此是空跑的**。
留着是因为 `parse_numeric` 全仓共用：哪天有人给它加上「识别百分号」这种健壮性改造，
比率就会静默流进计数指标。守卫改成 monkeypatch 一个会吃 `%` 的 `parse_numeric`，
专门测这一层还在。

**守卫**: CI 新增 D-048 一步。已反证四种回归各被不同断言抓住 ——
① 把占位阈值加回配了指标解析的项目（这条是本守卫的重点）；② 取值改成跨快照逐键取最大；
③ 拆掉比率键跳过（用 monkeypatch 才测得到）；④ 撤掉万位后缀。

**Rejected**:

- ❌ **逐键取跨快照最大值**。见上：会把「第1次之后塌掉」那种放大成假爆款。
- ❌ **把阈值调高到 556 以上**。数字没有依据，且唯一那条真爆够不着 —— 用一个假精确
  掩盖「这张表的互动量分不开趴和爆」这个事实。
- ❌ **只在 `parse_kv_metrics` 里处理万位、不动 `parse_numeric`**。判据分两份，
  下一张有万位的表还会再丢一次；而扩展共享函数只把 None 变成正确值，不改已有行为。

---

## D-049 · 方向列被写坏的那批行：不等飞书改，用正文兜底，但兜底必须自带出处

**日期**: 2026-08-31 · **触发**: 西屋 78 行没有 content_format / target_audience

### 事实先摆清楚

XIWU_phase1 全表 300 行，其中 78 行的「方向」列里躺着 **`已发布`** —— 那是「发布状态」
的取值，不是方向。分布不是零星填错，是一刀切：

| 发布日 | 方向=已发布 | 方向正常 |
|---|---|---|
| 08/20 | 0 | 16 |
| 08/23 | 0 | 14 |
| 08/24 | 11 | 0 |
| 08/25 ~ 08/29 | 67 | 0 |

**2026-08-24 是分界线，之后 78/78 全中。** 同一批行的其余列全对（正文/发布时间/链接/
流量状态/曝光数/互动数都在），所以**不是整表错位**，只有方向这一列脏。看着像新建一批行时
按列批量填、点错了列头；飞书多选列会把粘进来的值自动收成新选项，所以这一列吃得下「已发布」。

⚠️ **自查方式**：飞书里按 `发布时间 ≥ 2026-08-24` 筛一下看方向列。表默认从 08/03 排起，
从顶上翻看到的是好的那批。

后果：这 78 行 `content_format` / `target_audience` / `user_pain_point` 全空 —— 入了库
但拿不到任何可用于飞轮的结构化标签。

### 定的口径

策略 lead 2026-08-31 的决定：**方向列只会有「流量贴」「产品贴」两个值，不新增选项；
要更细的区分，本仓自己拿正文做。** 所以不等飞书改，引擎侧兜底。

新增 mapping 顶层块 `direction_from_content`（opt-in，没配的项目行为一字不变）：

```yaml
direction_from_content:
  default: 流量贴
  rules:
    - direction: 产品贴
      require: [西屋, GT33, ...]   # 任一命中 → 正向条件成立
      unless:  [求推荐, 纠结, ...]  # 任一命中 → 这条作废, 继续往下
```

### 判据是量出来的，不是拍的

拿 08/24 之前 **222 行运营手填的方向**当标注集试的：

| 规则 | 判成产品贴且对 | 判成产品贴但错 | 整体准确率 |
|---|---|---|---|
| 只看「正文点名西屋/GT33」 | 33 / 38 | 12 | 92.3% |
| **+「有选购提问词就不算」** | **27 / 38** | **1** | **94.6%** |
| 再加「安装/送装/开箱」等已购信号 | 29 / 38 | 6 | 93.2% |

单看点名信号已经很强（产品贴 86.8% vs 流量贴 6.5%），但那 12 条误判全是**还没买、
正在纠结**的选购贴 —— 正文里把西屋 GT33 当候选款报价（「西屋GT33大概七千」），照样点名。
叠一层提问词否决就压到 1 条。第三行那版多捞对 2 条、多判错 5 条，**弃用**。

这条轴本质是【买没买】：产品贴是产品已经在生活里（→ 场景植入），流量贴是还在问该不该买
（→ 提问求助），和 `direction_decomposition` 里两个方向的 content_format 是同一根轴。

**⚠️ 94.6% 是在同一张表的标注集上量的，是自评不是外部验证，真实错误率只会更高。**

### 所以兜底只兜底，不越权

1. **只在方向查不到时跑**。运营填对了的行一律不碰 —— 推断永远压不过人填的。
2. **必须留痕**：`raw_extra._direction_inferred` 记 {方向, 命中的词, 来源=正文推断}，
   同时 `data_quality_flags.direction_unmapped` 记源头问题（方向列里有 mapping 不认识的值）。
   下游任何时候都分得清哪些是运营填的、哪些是猜的。同 D-048 里 `tier_source='数值推断'` 的口径。
3. **推断出来的方向不参与 tier 判定**。`tier_threshold_override` 和 `excluded_directions`
   都按【原始】方向判。理由同 D-048：tier 是钱字段，不让任何推断去动它。
4. 不进 `data_quality_flags.synthetic` —— 那把闸是挡伪爆贴的，别混。

落到这 78 行：产品贴 19 / 流量贴 59。和我逐条手读这 78 行的结论 **76/78 一致**；
两条分歧都是「能不能」这个词出现在跟选购无关的句子里（「很多人问能不能送父母」的测评贴、
「问我能不能负责所有家务」的相亲贴）。试过把「能不能/会不会」从否决词里摘掉：
**在运营标注集上反而更差**（多对 1、多错 2），所以留着 —— 不拿自己的手判去调参数。

**守卫**: CI 新增 D-049 一步（5 组）。反证过：把「只在方向查不到时跑」这个条件拿掉，
守卫 ② 立刻变红。

**Rejected**:

- ❌ **出清单让运营在飞书改**。已出过一版 CSV，被否：方向列的取值集合是固定的，
  更细的区分归本仓做。（顺带一个自己的 bug：那份 CSV 存的是无 BOM 的 UTF-8，
  Excel 打开是乱码。重出的一版加了 BOM。）
- ❌ **在库里手动改这 78 行的方向**。`notes` 每次 sync 都按飞书重写，改了下次就没。
- ❌ **交给 essence LLM 那条道**。它读的是已经有 content_format 的行；而且这是个
  二分、有强词面信号的问题，确定性规则能查、能反证、能进 CI，LLM 不行。
- ❌ **不确定就留空（三分类）**。实测要留空 93/222 = 42%，其中大头是既不点名也不提问的
  纯情感贴 —— 而它们按 base rate（83%）本来就是流量贴。留空等于把大多数对的也扔了。
- ❌ **顺手把流量贴再拆细**（送礼父母/产后/打工人/学生党）。现在拆等于先验地分好类，
  沿用 mapping 里写死的那句：真要拆是后面看飞轮回收效果再说。要拆的话，位置就是这个块 ——
  策略 lead 这次说的「要进一步区分就用正文自己做」正是指这里。

---

## D-050 · 六张表从 `on_demand` 翻成 `daily`

**日期**: 2026-08-31 · **决定人**: 策略 lead · **范围**: TUGE / ANSHEN / LNKT / XIWU / BJS / SPX

### 翻掉意味着什么

`on_demand` 挡的是【夜间 cron 的四步】(D-047)，翻成 `daily` 是四步一起开：

| 步骤 | 翻掉之后 |
|---|---|
| ① feishu → truth_vault 入库 | 每晚自动灌新行 |
| ② essence 标注(LLM) | 每晚每项目 ≤ `WORKER_LIMIT`(默认 **15**) 条 |
| ③ curate 飞轮经验卡 | 爆款数量级，随之开 |
| ④ **通道1 → sanshengliubu.reference_samples** | **跨库写另一个团队的生产检索池** |

第 ④ 步是唯一不可逆的一步，所以翻之前把首跑会推多少条数出来了：

| 项目 | 会推去 ssll |
|---|---|
| XIWU | 9 (爆) |
| TUGE | 8 (爆7 + 大爆1) |
| SPX | 5 (爆) |
| LNKT | 2 (爆1 + 参考1) |
| BJS | 1 (爆) |
| ANSHEN | 0 |
| **合计** | **25** |

口径同 `fetch_pending_baokuan`：tier ∈ (爆/大爆/参考)、`tier_source ≠ 数值推断`、12 个月内、
未同步过、指标型 tier 排除 synthetic。**数值推断的行推不出去** —— XIWU 那 2 条阈值升上来的
爆就卡在这道闸上，这正是 D-048 定的口径在起作用。

essence 有每项目每晚 15 条的封顶，1025 条积压会分十几个晚上标完，不会一夜烧穿预算。

### 翻之前核过、结论是【不挡】的两件事

- **LNKT 是 `douyin`，其余五张是 `xiaohongshu`。** 本仓这侧 `_platform_for_ssll` 早就有
  `douyin → 抖音` 的显式映射，不会 silent fallback 写英文。剩下的不确定在 ssll 那侧
  —— 它的 `list_reference_packs` 有没有真的按「抖音」检索没人确认过。**最坏情况是那 2 条
  躺在 reference_samples 里没人取**，不是写坏数据，所以不挡这次翻。要用起来得 ssll 那边确认。
- **BJS 飞书「蓝词字段」的选项还是 SPORTSIX 的。** 翻之前查了库：
  **BJS 的 `hit_blue_keywords` 一条都没有值**(SPX 那边 35 条有值、全是 SPORTSIX 的词，那是对的)。
  所以现在【没有错数据入库】，问题是运营一旦开始打标就会从错的选项里挑。
  这是要在运营开始填之前修掉的事，不是这次翻的阻断项。
  ⚠️ 之前把这条说成「翻 daily 的前置条件」是说重了 —— 实际数据里它还没发生。

### 还留在 `on_demand` 的

HXZ_FB / HXZ_QD / NRT_phase2 / NRT_phase3 / NUC_phase1(前五个 `TableIdNotFound`，接不上飞书)
/ TGV_phase1 / TXQ_phase1。D-047 的 CI 守卫要求库里至少各有一个 `on_demand` 和一个 `daily`
项目来跑真值表，这批留着顺带满足了这个前提。

---

## D-051 · 夜跑连红三晚：一半是我 D-047 的闸在 `bash -e` 下把「照跑」当崩溃，一半是运营加列被 D-021 隔离、#121 把它从静默变成了红

**日期**: 2026-09-02 · **触发**: 8/31、9/1、9/2 三次定时跑全红

### 症状

| 夜跑 | 红的步骤 |
|---|---|
| 8/31 #152 | essence_sync · curate_sync |
| 9/1 #154 | feishu_sync · essence_sync · curate_sync |
| 9/2 #155 | feishu_sync · essence_sync · curate_sync |

两类，根因完全不同，分开说。

### A. essence / curate：我的 bug（D-047，8/30）

两步各跑 **1 秒**就退出码 1，一行输出都没有。原因是我在 D-047 里把闸接成：

```bash
python skip_on_cron.py "$p"; rc=$?
```

`skip_on_cron.py` 的契约是 0=跳过 / **1=照跑** / 2=判不了。GitHub 的 `run:` 默认 `bash -e`，
一条裸命令返回 1 就直接掐死整步 —— 根本走不到 `rc=$?`。所以循环到**第一个 `daily` 项目**
就死：8/31 死在 OKMAN（7 秒，前面 8 个 on_demand 返回 0 都过了），9/1 起 ANSHEN 翻成 daily
后第一个就死（1 秒）。**D-047 合并后 essence / curate 在 cron 里一次都没真正跑过。**

本地复现：`TV_SCHEDULED_RUN=true bash -e -c 'python3 skip_on_cron.py ANSHEN_phase1; rc=$?; echo 到了'`
不打印「到了」、退出 1；换 HXZ_FB（on_demand）正常。

**为什么 D-047 的守卫没抓到**：它只断言 `"skip_on_cron.py" in body` —— 查字符串在不在，
不查退出码怎么被消费。和 D-048 第一版守卫一样是**空跑的守卫**。这已经是第二次了。

修：`rc=0; python skip_on_cron.py "$p" || rc=$?`（`||` 使其成为被测试的命令，`-e` 不触发）。
新守卫 D-051 把 workflow 里那一行**原样**丢进 `bash -e` 跑，后面跟哨兵：daily+cron 必须走到
哨兵且 rc=1，on_demand → 0，读不出 → 2。反证过：把修复撤回，守卫立刻红。

### B. feishu_sync：运营在飞书加列 → D-021 整行隔离；#121（9/1）让它不再静默

| 表 | 飞书总行 | 进库 | 隔离 | 新列 | 从哪天起 |
|---|---|---|---|---|---|
| OKMAN | 350 | **0** | 350 | 链接文本 | **8/21** |
| TUGE | 231 | **0** | 231 | 下次巡查时间 (+起量时间) | 9/2 |
| RIO | 800 | 391 | 409 | 父记录 | **6/19** |
| LNKT | 364 | 101 | 263 | 数据回收 · 数据汇总 | 8/26 起的新行 |
| BJS | 64 | 20 | 44 | 数据整理 | 9/1 |
| XIWU | 301 | 299 | 2 | 图有问题 | 9/2 |
| SPX | 374 | 324 | 50 | （缺正文，见下） | 8/30 |

**这不是 #121 弄坏的，是 #121 让人看见的。** COR-002 之前，隔离行不计 errors，步骤是绿的
—— 于是 OKMAN 从 8/21 起、RIO 从 6/19 起一直在丢行，没有任何症状。COR-002 把「隔离 = 这次
没处理成」计进 errors，红是对的。正确的反应是把列声明掉，不是把红压回去。

每个新列按隔离表里的真实值判，全部走 D-021 的 `project_specific_fields_to_raw_extra`，
先例都在：

- **下次巡查时间**(TUGE)：公式列（Excel 序列日 `46270.59`），**每行都有值**，所以一出现就把
  原来 40 行好的也一起隔离了。→ raw_extra。**起量时间** → 同 BJS/LNKT/XIWU 先例。
- **链接文本**(OKMAN)：`反馈链接` 的纯文本副本。→ raw_extra。
- **父记录**(RIO)：飞书父子记录指针，409 行子记录只有 `方向+父记录`。→ raw_extra（BJS/LNKT 先例）。
  声明后这些子记录会落到「只缺正文、且无账号/链接/指标信号」→ `empty_placeholder`，不计错。
- **图有问题**(XIWU)：QA 勾选框 true/false。→ raw_extra。
- **数据回收**(LNKT)：截图附件 → raw_extra。**数据汇总**(LNKT)：8/26 起新行不再分「第N次」，
  改填单列，形状和 D-048 解析的一模一样 → raw_extra **并**加进 `metrics_from_kv_text.sources`
  末尾（= 最新；D-048 写 mapping 时就预留了这句）。回放：新旧并存取新，只有老列的老行不变。
- **数据整理**(BJS)：`曝光量：53；阅读量：5；互动量：0`，本表原本**没有任何指标列**。
  → 按 D-048 机制接 `metrics_from_kv_text`。**同时摘掉那组「占位, 不生效」的 `tier_thresholds`
  (爆 100/大爆 500)** —— 解析成功那一刻它就会生效，而这两个数没有依据（D-048 原话，CI ④ 也不许并存）。

用隔离表里的真实行本地回放：六张表 `undeclared=[]`，BJS 解析出 53/5/0，LNKT 388/5。

### 修完还会红的（不是 mapping 问题，是数据本身）

- **SPX 50 行**：有链接、有曝光/阅读/互动、有观众分析、有截图，**就是没有 文案**。是真笔记，
  运营没贴正文。COR-002 计错是对的（没正文的笔记进不了飞轮），要运营补。
- **TUGE 64 行**：只填了 `素人编号`，别的全空 —— 预建的排期行。有账号信号就不算空占位，
  照 COR-002 计错。这是 `_NOTE_DATA_SIGNALS` 的边界：单独一个 `account_id` 该不该算「有实质」，
  留给 COR-002 的作者定，我不动。
- 这两条会让 feishu_sync 继续红，直到运营补正文 / 口径定下来。

### 顺带看到的

- **cron 又晚了**：配 02:00 UTC，8/31 08:01、9/1 07:09、9/2 06:44 才起跑。
- **`WORKER_LIMIT` 被改成了 50**（repo variable，原 15）。步骤内部按 ≤8 拆子批，不会 502，只是记一笔。
- **comments 那步 30~40 分钟**，三晚都是。它是绿的，但 40 分钟对 400 条评论不正常，另开 issue 看。

**Rejected**

- ❌ **把 COR-002 的 `errors += 1` 撤掉让步骤回绿**：那就回到 OKMAN 静默丢一个月的状态。
- ❌ **只修我的 bug、mapping 留给运营**：列是运营加的没错，但声明列是 D-021 的机械动作、
  先例齐全，不是业务判断；而且不声明 OKMAN/TUGE 一行都进不来。
- ❌ **给 BJS 保留占位阈值**：D-048 已经吃过一次亏，CI 守卫也不允许。
