# Audience Inferrer · Prompt v0.1

## 用途

独立于 essence_annotator 的 audience 层推断 prompt。当 essence 已标注但 audience 需要单独重跑时使用（如优化 audience 推断准确率时）。

> 大部分情况下用 essence_annotator 一次性出 essence + audience。这个独立 prompt 主要用于 audience 校准实验或重标。

## 模型

- 主推断: 配置层指定（默认 claude-sonnet-4-20250514，上线前核实最新 model id）
- 高分歧重跑: 配置层指定（默认 claude-opus-4-6-20250610，上线前核实最新 model id）

## 调用方式

```python
response = anthropic.messages.create(
    model=config.ESSENCE_MODEL_PRIMARY,  # 见 .env / config.py
    max_tokens=1200,
    messages=[
        {"role": "user", "content": PROMPT.format(
            project_context=project_context_block,
            note_content=note_content_block,
            essence_context=essence_block,    # essence 已标注则传入
            actual_audience=actual_block       # 如有蒲公英数据传入做校准
        )}
    ]
)
```

## Prompt 全文

```
你是一个内容营销分析师，专精小红书种草受众分析。任务：根据一条小红书笔记，推断会因这条内容产生共鸣的受众画像。

═══════════════════════════════════════════════
项目上下文
═══════════════════════════════════════════════
{project_context}

═══════════════════════════════════════════════
笔记内容
═══════════════════════════════════════════════
标题: {title}
正文: {body}
话题标签: {hashtags}

═══════════════════════════════════════════════
笔记 essence 信息（已标注，参考用）
═══════════════════════════════════════════════
{essence_context}

例如:
- emotional_lever: 焦虑撬动
- human_truth_archetype: 健康焦虑, 育儿焦虑
- content_format: 情感叙事

═══════════════════════════════════════════════
笔记实际受众数据（如有蒲公英后台数据）
═══════════════════════════════════════════════
{actual_audience}

如果有实际数据，你的推断应该考虑这些事实。
如果实际数据和你的直觉判断不一致，以实际数据为准并解释为什么。

例如:
- 真实年龄分布: 18-24: 5%, 25-30: 22%, 31-40: 48%, 41+: 25%
- 真实性别分布: 女 91%, 男 9%
- 真实城市分布: 1线 15%, 新1线 22%, 2线 28%, 3-4线 28%, 5线 7%

═══════════════════════════════════════════════
你的任务
═══════════════════════════════════════════════

输出严格 JSON 格式的 audience profile。

══ Demographic (闭集) ══

age_band (1-2 个): 哪个年龄段会因这条内容产生共鸣
  允许值: 20-29 / 30-39 / 40-49 / 50+

gender_skew (单选):
  - female: 显著偏向女性受众
  - male: 显著偏向男性受众
  - mixed: 性别没有明显偏向

city_tier (1-3 个): 受众的城市层级
  允许值: 1线 / 新1线 / 2线 / 3-4线 / 5线及以下

life_stage (单选):
  - 学生 / 职场新人 / 已婚未育 / 育儿期 / 空巢 / 退休

value_orientation (单选):
  - 务实: 关注实用、性价比
  - 精致: 追求品质和形式
  - 自洽: 自我接纳、不向外比较
  - 表达: 追求独特、表达自我
  - 反叛: 挑战主流、反传统

income_band (单选):
  - 学生 / 入门 (月收入<5k) / 中产 (5-30k) / 高净值 (30k+)

══ Psychographic (自由文本，每项 1-2 句) ══

primary_pain: 这群受众面临的主要痛点，文案触发的就是这个痛点
primary_aspiration: 这群受众想要的理想状态，文案承诺解决的就是通向这个状态
likely_objections: 看到这条内容他们最可能产生的犹豫或质疑

══ Confidence ══

confidence (0-1): 你对这个推断的总体置信度
  - 0.9+: 文案有非常明确的受众信号（性别词、年龄词、生活场景具体）
  - 0.7-0.9: 信号明确但有一些模糊
  - 0.5-0.7: 信号较少，依赖品类+内容形式推断
  - <0.5: 几乎无信号，仅基于品类常识推断 ← 这种情况需要标记

══ Reasoning ══

reasoning (字符串，80-150 字): 简短解释推断依据
  - 关键线索（哪些词/场景暗示了 demographic）
  - 不确定的地方
  - 如果有实际数据校准，说明如何调整了判断

═══════════════════════════════════════════════
重要约束
═══════════════════════════════════════════════

1. 严格 JSON 输出，不要 markdown 包装
2. 闭集字段必须从允许值中选
3. 如果文案信号不足，宁可标低 confidence + 范围更宽的 age_band（如 [30-39, 40-49]），不要硬猜
4. age_band 多选要相邻（不要标 [20-29, 50+]）
5. psychographic 不是描述这条文案，是描述**会被这条文案打动的人**
6. 如果有实际数据，必须基于实际数据校准

输出 JSON 格式示例:

{
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
    "primary_aspiration": "希望尽快恢复体力做好妈妈这个角色",
    "likely_objections": "价格、是否真的有用、和喝粥相比有什么优势"
  },
  "confidence": 0.85,
  "reasoning": "标题'剖腹产第5天'+'吃不下'锁定了产后早期女性。'😭'emoji+第一人称叙述是 30-39 已育女性常见表达。考虑保健品价格定位推断为中产。confidence 较高因为有非常具体的生活阶段信号。"
}
```

## 校准模式说明

当传入 `actual_audience` 真实数据时，prompt 工作模式略有不同：

### Pattern 1: 推断 + 校准（有真实数据）

LLM 首先做独立推断 → 再对照真实数据 → 调整 demographic 字段以符合事实 → reasoning 里说明"原本推断 X，但真实数据显示 Y，调整为 Y 并保留 psychographic 因为它无法从真实数据反推"。

### Pattern 2: 纯推断（无真实数据）

按常规流程跑，confidence 反映推断的可靠程度。

## audience 校准闭环代码

```python
def calibrate_inference(note):
    """对所有有真实 audience 数据的笔记重跑推断 + 比较"""
    
    # 重跑推断（不带 actual data）
    inferred_no_calib = run_audience_prompt(note, actual_audience=None)
    
    # 比较 inferred vs actual
    actual = note.actual_audience_data
    
    age_match = compare_age(
        inferred_no_calib['demographic']['age_band'],
        actual['age_distribution']
    )
    
    # 记录到 audience_calibrations 表
    save_calibration(
        note_id=note.note_id,
        age_inferred=inferred_no_calib['demographic']['age_band'][0],
        age_actual=majority_age(actual['age_distribution']),
        age_match=age_match,
        ...
    )
```

## Prompt 版本历史

| 版本 | 日期 | 关键变更 |
|---|---|---|
| v0.1 | 2026-05-18 | 初版（独立 audience prompt） |
