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
