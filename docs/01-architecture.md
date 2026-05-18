# 01 · Truth Vault 三层架构

## 为什么存在

这个文档论证 Truth Vault 数据库的核心架构决策 —— 为什么数据必须分 Surface / Essence / Audience 三层独立存储。这是整个项目最深的设计洞察，所有 schema 设计、标注协议、检索算法都从这里派生。

> 如果你跳过这个文档直接看 schema，会觉得字段过于复杂、有些字段似乎冗余。读完这个文档你会理解每个字段为什么必须存在。

---

## 核心问题：为什么单层数据库会失败

设想一个朴素的设计：把所有笔记的文案 + 互动数据 + 一些标签存进数据库，然后用 embedding 检索做相似召回。这是大多数"AI 营销工具"的做法。这种设计**注定在 6-12 个月后失效**。

原因是文本数据有一个根本性质：**不同层次的信息有不同的时间衰减速度**。

举一个具体例子。看下面两条文案：

> **文案 A（2024 年发布）**：  
> "刷到郁可唯的新综艺，居然能在职场剧里看到中年女演员演不卑微的角色，太爽了"

> **文案 B（2026 年发布）**：  
> "看了《XX 漂亮女孩》大结局，意外的是没把 35+ 女性写成可怜的样子，看完想买个粉饼好好上班"

两条文案在花西子粉饼项目里都是爆款。表面（surface）看，文案 A 提到郁可唯、提到具体综艺名 —— 这些"surface 信息" 6 个月后大概率没人看了，搜索热度归零。文案 B 提到 XX 漂亮女孩 —— 同样会过时。

但这两条文案爆的根本原因是同一个：**戳中了 35+ 女性"我不要被书写成可怜的样子"的自我形象焦虑**。这个"内核（essence）"信息几乎不衰减 —— 三十年前的电视剧观众有这个共鸣，三十年后的短视频观众还会有。

**如果数据库只存 surface（标题、正文、词频、embedding 向量），模型学到的是"提到郁可唯就爆"这种短命相关性**。模型半年后看到不再有人提郁可唯，就以为这种 angle 不管用了，实际上是表层换了。

**如果数据库分层存储，把"郁可唯"放 surface 层、"自我形象焦虑"放 essence 层**，模型可以独立学到 "essence='自我形象焦虑' 的内容历史爆款率 X%"，这个统计跨年度都有效。

这就是分层的意义。

---

## 三层定义

### Layer 1 · Surface（表层）

**定义**：文案的字面表达层 —— 词汇、句式、平台话术、热点 IP 引用、当代用语。

**典型字段**：
- 文本本身（title, body）
- 词法特征（标题字数、是否带数字、是否带 emoji）
- 内容形式（情感叙事 / 横评 / 教程 / 直给）
- 平台话术（小红书特有的"姐妹们"、"绝绝子"、"米色裤子"梗）
- 时效性引用（具体综艺名、明星名、热点事件）

**时间衰减**：
- 半衰期 6-12 个月
- 一年前的爆款 surface 模式，新数据上完全失效

**抓取方法**：
- 文本本身：直接存
- 词法特征：纯代码计算
- 内容形式：LLM 闭集分类
- 时效性引用：LLM 闭集分类（`trend_dependencies` 字段）

### Layer 2 · Essence（内核）

**定义**：文案触发反应的根本机制 —— 情绪杠杆、人性原型、内容内核。

**典型字段**：
- `emotional_lever` —— 主要情绪杠杆（焦虑/羞耻/恐惧/造梦/认同/归属…）
- `emotional_valence` —— positive / negative / neutral
- `emotional_intensity` —— low / medium / high
- `human_truth_archetype` —— 人性原型（同辈比较 / 伴侣关系 / 自我形象维护…）

**时间衰减**：
- 半衰期 5 年以上，接近不衰减
- "35+ 女性自我形象焦虑"在 1995 年成立，2025 年成立，2055 年很可能依然成立

**抓取方法**：
- 必须 LLM 标注，**必须在闭集词表内**
- 不允许自由文本（自由文本跨样本不可比）
- 词表见 [05-controlled-vocab.md](05-controlled-vocab.md)

### Layer 3 · Audience（受众）

**定义**：文案目标共鸣的受众画像 —— 谁会点赞、谁会评论、谁会因为这条产生兴趣。

**典型字段**：
- `inferred_audience_profile` (JSONB) —— LLM 从文案 + 评论 + 项目 context 推断
  - demographic：年龄段 / 性别倾向 / 生活阶段
  - psychographic：价值观 / 痛点 / aspiration
- `actual_audience_data` (JSONB) —— 蒲公英后台真实数据（年龄 / 性别 / 城市分布）

**时间衰减**：
- 中等 —— 半衰期 2-3 年
- 一代人的成长会改变 audience 边界
- 但比 surface 慢得多

**抓取方法**：
- LLM 推断（结构化输出）+ 蒲公英真实数据校准
- 推断 prompt 见 [06-essence-annotation.md](06-essence-annotation.md)

---

## 为什么这三层必须独立存储

最直接的反例：**两个 surface 完全不同的项目，essence 可以高度对称，可以策略复用**。

举帆谷做过的两个项目对照：

### 力克雷（戒烟药品） vs 花西子粉饼（35+ 妆容）

| 维度 | 力克雷 · "戒烟" 爆款方向 | 花西子粉饼 · "35+持妆" 爆款方向 |
|---|---|---|
| **Surface** | "相亲被嫌弃一身烟味" "30+ 找不到对象因为抽烟" | "述职答辩妆容不够正式" "55+ 找好用粉饼" |
| 产品 | 处方药戒烟产品 | 美妆 |
| 性别 | 男性向 | 女性向 |
| 平台话术 | 戒烟、戒断反应、NRT | 持妆、妆效、提亮 |
| **Essence** | **自我形象焦虑（中年男性衰退恐惧）** | **自我形象焦虑（35+ 女性衰老恐惧）** |
| Emotional lever | 焦虑撬动 | 焦虑撬动 |
| Valence | 负向 | 负向 |
| Human truth | 自我形象维护 + 被他人评价 | 自我形象维护 + 被他人评价 |
| **Audience** | 30-45 中年男性 / 自我形象焦虑 | 30-45 中年女性 / 自我形象焦虑 |

**两者的 surface 几乎没有重叠** —— embedding 相似度计算结果一定是"不相关"。

**但 essence + audience 是同一个东西** —— 同样是"被他人评价 + 自我维护"的原型，同样是 30-45 中年人群的形象焦虑，只是性别和具体载体不同。

**这意味着什么**：
- 力克雷的"被相亲对象嫌弃显老"这种情绪触发结构，理论上可以迁移到花西子粉饼
- 反过来花西子的"55+ 求好用粉饼"自嘲性张力，可以迁移到力克雷"55+ 戒不掉"
- **Surface 必须重写**（产品不同、性别不同、平台话术不同）
- **Essence 框架可以直接复用**

这就是数据飞轮真正的复利来源。**做的项目越多 → essence pattern 越完整 → 跨产品迁移能力越强 → 新客户冷启动越快**。

简单的 RAG（embedding 检索）抓不到这种迁移。要让数据库支持"跨产品策略迁移"，必须在 essence + audience 层做匹配，而不是 surface 层。

---

## 各层独立的使用方式

不同的下游任务用不同层的数据：

### 阶段 1 · 描述性 anchor 用什么层？

主要用 **Surface 层**（文案字面特征）+ **Essence 层**（情绪 / 原型）做统计对比。

例：给定一条新文案，输出 anchor 报告：
- "标题字数 8（surface），历史方向三爆款均值 11"
- "emotional_lever=焦虑撬动（essence），该项目焦虑撬动爆款率 12%（vs 总体 8%）"

### 阶段 2 · 判别式分类用什么层？

LightGBM 的 features 来自**三层全部**：
- Surface 特征：title_len, opener_type, has_question…
- Essence 特征：emotional_lever, human_truth_archetype, emotional_intensity…
- Audience 特征：age_band, gender_skew, life_stage…

essence 特征的预测力**长期最稳定**，surface 特征**最有近期信号**，audience 特征**给跨项目迁移最大贡献**。

### 阶段 3 · 跨产品迁移评分用什么层？

主要用 **Essence + Audience** 层做相似度计算，**Surface 反向用作"差异化检查"**：

```
迁移性(A → B) = 
    w_a · audience_overlap(A, B)
  + w_e · essence_overlap(A, B)
  - w_s · surface_similarity(A, B) * 时间惩罚
```

注意 surface 那一项是**负权重** —— 跨产品迁移时 surface 太像反而是劣势（要么抄袭被风控，要么没创新很难再爆）。"换皮不换骨" 是正确策略。

### 阶段 4 · 因果评估用什么层？

主要看**同 essence 不同 surface** 的对照实验。例：
- "情绪 lever='焦虑撬动' + intensity='high' 的内容相比 intensity='medium' 的内容，ATE +X%"
- "essence 固定时，prompt v7 vs v6 的 ATE 差异"

---

## 时间衰减的工程实现

检索 / 训练时，每条历史样本的权重按层独立衰减：

```python
def sample_weight(sample, query_date):
    age_months = (query_date - sample.publish_date) / 30
    
    surface_weight = exp(-age_months / 6)        # 半衰期 6 个月
    essence_weight = exp(-age_months / 60)       # 半衰期 5 年
    audience_weight = exp(-age_months / 30)      # 半衰期 2.5 年
    
    return {
        'surface': surface_weight,
        'essence': essence_weight,
        'audience': audience_weight,
    }
```

- 1 年前的样本：surface 权重 ≈ 0.13，essence 权重 ≈ 0.79，audience 权重 ≈ 0.63
- 2 年前的样本：surface 权重 ≈ 0.018，essence 权重 ≈ 0.63，audience 权重 ≈ 0.39

老数据的 surface 信号几乎被归零，但 essence 几乎全部保留。这就是数据库能"穿越周期"的算法机制。

---

## 标注协议要求

为了让三层数据可靠生成，标注协议要满足：

### Surface 层
- 文本本身：原始入库
- 词法特征：确定性代码计算（不用 LLM）
- 内容形式 / 时效性引用：LLM 闭集分类，准确率要求 90%+

### Essence 层
- **必须**用闭集词表（emotional_lever 10 个值、human_truth_archetype 15-20 个值）
- LLM 自由表达就废了 —— 跨样本不可比
- 标注 prompt 严格 JSON schema 输出
- 质量抽检 10% 样本人工 review

### Audience 层
- demographic 部分闭集（age_band, gender_skew, life_stage）
- psychographic 部分自由文本（primary_pain, primary_aspiration）—— 闭集会把信息压死
- 蒲公英真实数据作为校准基线（LLM 推断 vs 真实数据）

详细协议见 [06-essence-annotation.md](06-essence-annotation.md)。

---

## 常见反对意见与回应

### "Essence 是主观的，标注会不稳定"

**回应**：闭集词表 + 严格 prompt + 抽检流程能把标注一致性做到可接受水平（IRR > 0.7）。完全不标 essence 而依赖 embedding —— 假装客观但 embedding 也是某种"机器的主观"，且抓不到真信号。

### "为什么不让模型自己学这些层？"

**回应**：理论上可以（用 BERT + 多任务学习），但需要大量标注数据训练。在 3,400 条数据规模下，闭集人工设计的层级 + LLM 标注的 hybrid 方法效率最高。等数据到 50k+ 可以考虑端到端学习。

### "Surface 和 Essence 难以分清"

**回应**：边界确实模糊，但**不需要完美分清**。原则是"如果一年后这个特征还有效，就放 essence；如果半年后就过时，就放 surface"。具体边界靠词表定义。

### "Audience 推断不准怎么办"

**回应**：D-008 决定就是为了解决这个 —— 蒲公英真实数据校准 LLM 推断。第一版可能不准，但有真实数据反馈后会越来越准。

---

## 这个架构对项目的整体影响

读完这个文档，理解下面这些设计决策的根源：

- 为什么 schema 字段那么多（D-001）—— 三层都要存
- 为什么不能用 RAG（D-002）—— RAG 只匹配 surface
- 为什么"方向"必须拆解（D-003）—— 单字段混合多层信息
- 为什么管家不做判断（D-004）—— 判断需要综合三层，不是单一管家职责
- 为什么必须回标历史数据（D-005）—— essence 层不能空着
- 为什么需要蒲公英数据（D-008）—— audience 层需要真实数据校准

参见 [DECISIONS.md](../DECISIONS.md)。

---

## 下一步

读完这个文档，建议接着读：

1. [02-schema-v1.md](02-schema-v1.md) —— 这套架构如何落到具体字段
2. [05-controlled-vocab.md](05-controlled-vocab.md) —— essence 层的闭集词表
3. [06-essence-annotation.md](06-essence-annotation.md) —— 怎么生产 essence 数据
