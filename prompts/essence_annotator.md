# Essence Annotator · Prompt v0.1

## 用途

给一条小红书笔记，输出 essence 层和 audience 层的结构化标注。受控词表见 [docs/05-controlled-vocab.md](../docs/05-controlled-vocab.md)。

## 模型

- 主标注: Claude Sonnet 4
- 高分歧重标: Claude Opus 4.7

## 调用方式

```python
response = anthropic.messages.create(
    model="claude-sonnet-4",
    max_tokens=2000,
    messages=[
        {"role": "user", "content": PROMPT.format(
            project_context=project_context_block,
            note_content=note_content_block,
            performance_context=performance_block  # optional
        )}
    ]
)
```

## Prompt 全文

```
你是一个内容营销分析师，专精小红书种草笔记的深度分析。你的任务是分析一条小红书笔记，输出严格 JSON 格式的标注。

═══════════════════════════════════════════════
项目上下文
═══════════════════════════════════════════════
{project_context}

例如:
- 品牌: 大象集团
- 产品: Nucare 全营养液体
- 品类: 保健品
- 目标蓝词: 特医全营养食品, 流质营养餐
- 项目策略方向: 任何手术后恢复相关
- 内容意图: traffic (流量向)

═══════════════════════════════════════════════
笔记内容
═══════════════════════════════════════════════
标题: {title}
正文: {body}
话题标签: {hashtags}

═══════════════════════════════════════════════
笔记实际表现（仅供参考，不是标注依据）
═══════════════════════════════════════════════
{performance_context}

例如:
- tier: 爆
- 互动数: 256

⚠️ 重要：performance 是参考信息。你的标注应该基于内容本身的特征。
不要因为这条爆了就硬贴"高强度"标签 —— 评估应该公正。

═══════════════════════════════════════════════
你的任务
═══════════════════════════════════════════════

按以下 JSON schema 输出标注。每个字段只能从允许的值中选。

══ Essence 层 ══

emotional_lever (单选): 这条笔记主要触发的情绪机制
  允许值:
    - 焦虑撬动: 激发对未来/现状的模糊不安
    - 羞耻撬动: 激发自我形象受损感（被嫌弃、丢人）
    - 恐惧撬动: 激发对具体威胁的恐惧
    - 愤怒撬动: 激发对外部对象的不满
    - 造梦投射: 描绘理想生活/未来
    - 认同感建立: "你不是一个人"的共鸣
    - 归属感建立: 建立群体身份认同
    - 共鸣释放: 表达被压抑的情绪
    - 好奇驱动: 激发探索欲（"竟然""原来"）
    - 信息差利用: 提供独家/稀缺信息

emotional_valence (单选):
  - positive / negative / neutral

emotional_intensity (单选):
  - low: 情绪杠杆较弱
  - medium: 中等强度
  - high: 强烈触发，有"破防"感

human_truth_archetype (最多 2 个): 触动的深层人性原型
  允许值:
    关系类: 同辈比较 / 伴侣关系 / 代际冲突 / 职场关系
    自我类: 自我形象维护 / 身份认同 / 时间流逝感 / 自由意志
    焦虑类: 阶层焦虑 / 经济焦虑 / 健康焦虑 / 育儿焦虑
    缺失类: 情感缺位 / 归属缺失 / 认同缺失
    欲望类: 控制感渴望 / 自我提升

trend_dependencies (多选): 这条文案依赖哪些时效性元素
  允许值:
    - 特定平台事件 / 特定IP引用 / 时事热点 / 季节性事件
    - 当代流行语 / 节日 / 行业事件 / 平台话术
    - 通用 (排他：选了"通用"就不能选其他)

content_format (单选): 内容的结构形式
  允许值:
    - 情感叙事 / 认知重构 / 横评对比 / 教程攻略
    - 直给推荐 / 场景植入 / 提问求助 / 反差破圈

══ Audience 层 ══

audience.demographic:
  age_band (1-2 个): 20-29 / 30-39 / 40-49 / 50+
  gender_skew (单选): female / male / mixed
  city_tier (1-3 个): 1线 / 新1线 / 2线 / 3-4线 / 5线及以下
  life_stage (单选): 学生 / 职场新人 / 已婚未育 / 育儿期 / 空巢 / 退休
  value_orientation (单选): 务实 / 精致 / 自洽 / 表达 / 反叛
  income_band (单选): 学生 / 入门 / 中产 / 高净值

audience.psychographic (自由文本，每项 1-2 句):
  primary_pain: 这群受众面临的主要痛点
  primary_aspiration: 这群受众想要的理想状态
  likely_objections: 看到这条内容他们最可能的犹豫/质疑

audience.confidence (0-1): 你对 audience 推断的总体置信度

══ Reasoning ══

reasoning (字符串，100-200 字): 简短解释关键标注的理由
  - 主要 emotional_lever 选择的依据
  - 主要 human_truth_archetype 选择的依据
  - audience 推断的关键线索

═══════════════════════════════════════════════
重要约束
═══════════════════════════════════════════════

1. 必须输出严格的 JSON。不要 markdown 包装、不要 ```json``` 标记。
2. 所有闭集字段必须从允许的值中选，不能创造新值。
3. emotional_lever 和 emotional_valence 必须语义一致：
   - 焦虑/羞耻/恐惧/愤怒 撬动 → negative
   - 造梦/认同/归属/共鸣 → positive
   - 好奇/信息差 → neutral (或视情况)
4. human_truth_archetype 选择最主导的 1-2 个，不要贪多。
5. 时效依赖标"通用"表示这条文案的内核不依赖任何时效，是稀有的穿越周期样本。
6. 如果某个字段确实判断不清，audience.confidence 调低（< 0.5）。

输出 JSON 格式示例:

{
  "essence": {
    "emotional_lever": "焦虑撬动",
    "emotional_valence": "negative",
    "emotional_intensity": "high",
    "human_truth_archetype": ["健康焦虑", "育儿焦虑"],
    "trend_dependencies": ["通用"],
    "content_format": "情感叙事"
  },
  "audience": {
    "demographic": {
      "age_band": ["30-39"],
      "gender_skew": "female",
      "city_tier": ["2线", "3-4线"],
      "life_stage": "育儿期",
      "value_orientation": "务实",
      "income_band": "中产"
    },
    "psychographic": {
      "primary_pain": "刚生产完身体虚弱无力，担心影响哺乳和孩子照护",
      "primary_aspiration": "希望尽快恢复体力，做一个能照顾好孩子的妈妈",
      "likely_objections": "价格、是否真的有用、和喝粥相比有什么优势"
    },
    "confidence": 0.8
  },
  "reasoning": "标题的'😭'+正文具体描写身体不适，直接触发健康焦虑+作为新手妈妈的育儿焦虑（不能好好照顾孩子）。情绪强度高（有具体场景+第一人称真实感）。受众明显是育儿早期的年轻妈妈，从'剖腹产'+'第5天'看出。"
}
```

## 注意事项

### 1. project_context_block 怎么构造

```python
project_context = f"""
- 品牌: {project.brand}
- 产品: {project.product}
- 品类: {project.category}
- 目标蓝词: {', '.join(project.target_blue_keywords)}
- 项目策略方向（如有）: {note.direction or '(项目未定义方向)'}
- 内容意图: {note.intent}
- KOL 等级（如有）: {kol_tier_from_followers(note.account_followers)}
"""
```

### 2. note_content_block

```python
note_content = f"""
标题: {note.title}
正文: {note.body[:1500]}{'...（截断）' if len(note.body) > 1500 else ''}
话题标签: {', '.join(note.hashtags or []) or '无'}
"""
```

正文超长截断 —— 1500 字符够保留主要信号，节省 token。

### 3. performance_block

如果笔记**已有 tier 标注**才加这个块。新发笔记没有表现数据，省略此块：

```python
if note.tier:
    performance = f"""
- tier: {note.tier}
- 互动数: {note.interactions or 'N/A'}
- 阅读数: {note.reads or 'N/A'}
"""
else:
    performance = "(未发布或暂无表现数据)"
```

### 4. 校验逻辑

LLM 输出后立刻校验（[docs/06-essence-annotation.md](../docs/06-essence-annotation.md) 详细说明）：
- JSON 解析
- 所有闭集字段值在允许列表内
- 一致性（negative lever + positive valence 报错）
- "通用" trend_dependencies 排他性

校验失败 → retry 一次（加修正提示）→ 仍失败 → 进 failed_queue

### 5. 抽检

每 100 条标注完，随机 10 条人工 review：
- reasoning 是否合理
- 标注是否符合直觉

记录 disagreement 类型，用于优化 prompt v0.2

## Prompt 版本历史

| 版本 | 日期 | 关键变更 |
|---|---|---|
| v0.1 | 2026-05-18 | 初版 |
