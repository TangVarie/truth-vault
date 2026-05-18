# 06 · Essence 层 LLM 标注协议

## 为什么存在

Truth Vault 的三层架构要求每条笔记必须有 essence 层和 audience 层的标注。这些标注必须用 LLM 完成，并且**必须在闭集词表内**。这个文档定义标注的工作流、质量保证、成本控制。

---

## 标注什么

按 [05-controlled-vocab.md](05-controlled-vocab.md) 的词表，每条笔记需要 LLM 输出以下字段：

```yaml
essence_layer:
  emotional_lever: <受控词表>
  emotional_valence: <positive / negative / neutral>
  emotional_intensity: <low / medium / high>
  human_truth_archetype: [<最多2个，主+次>]
  trend_dependencies: [<多选>]
  content_format: <受控词表>

audience_layer:
  inferred_audience_profile:
    demographic:
      age_band: [...]
      gender_skew: ...
      city_tier: [...]
      life_stage: ...
      value_orientation: ...
      income_band: ...
    psychographic:
      primary_pain: <自由文本>
      primary_aspiration: <自由文本>
      likely_objections: <自由文本>
    confidence: <0-1>
```

---

## 标注 prompt 设计

完整 prompt 见 [../prompts/essence_annotator.md](../prompts/essence_annotator.md)。这里说明设计原则。

### 输入 context

每次标注输入给 LLM 的 context：

```
项目元数据:
  - product: Nucare 全营养液体
  - category: 保健品
  - target_blue_keywords: 特医全营养食品, 流质营养餐
  - direction: 任何手术后恢复相关
  - intent: traffic

笔记 surface:
  - title: 剖腹产第5天了为什么还是吃不下😭
  - body: [...]
  - hashtags: [...]

笔记的实际表现（仅作为参考，不影响标注）:
  - tier: 爆
  - interactions: 256
```

把 tier / 数据**作为参考给 LLM** 是有意为之的 —— 不是要 LLM 反推，而是让 LLM 在已知"这条爆了"的情况下分析爆的原因（essence）。这比从零开始猜更准。但要在 prompt 里**明确强调**："tier 是参考信息，但你的标注应该基于内容本身的特征，不要因为爆了就硬贴'高强度'"。

### 输出格式

强制 JSON 输出，schema 校验：

```json
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
      "primary_pain": "刚生产完身体虚弱无力，担心影响哺乳和恢复",
      "primary_aspiration": "希望尽快恢复体力照顾孩子",
      "likely_objections": "贵、是否真的有用"
    },
    "confidence": 0.8
  },
  "reasoning": "<简短解释为什么选这些值>"
}
```

`reasoning` 字段强制 LLM 给出理由 —— 用于质量抽检和后续调试。

### Prompt 关键设计原则

1. **闭集严格**: 在 prompt 里明确列出所有允许的值，强调"只能从以下列表中选"
2. **示例对照**: 给 2-3 个已标注的示例（few-shot）
3. **边界规则**: 明确"焦虑 vs 恐惧"、"身份认同 vs 归属缺失"等模糊边界的判断规则
4. **置信度自评**: confidence < 0.5 时标 `"uncertain"`，后续人工 review
5. **不允许新增值**: LLM 强烈倾向于"创造"新标签，必须明确禁止

---

## 模型选择

| 任务 | 推荐模型 | 理由 |
|---|---|---|
| 标注主任务 | Claude Sonnet 4 | 性价比最优，结构化输出稳定 |
| 抽检对照 | Claude Opus 4.7 | 高难度样本用更强模型校验 |
| 词表设计辅助 | Claude Opus / GPT-5 | 设计阶段一次性投入 |

不推荐：
- GPT-4o（结构化输出对中文 nuance 把握略弱）
- 国产模型（Qwen/DeepSeek）—— 不是不行，是对人性原型这种 Western 心理学概念的训练数据少

---

## 成本估算

每条笔记标注 prompt + 输出大约 3000-4000 tokens：
- 输入 ~2000 tokens（项目 context + 笔记内容）
- 输出 ~1500 tokens（结构化 JSON）

Claude Sonnet 4 价格按当前估算（每 1M token $3 输入 / $15 输出）：
- 单条标注成本: ~$0.03 ≈ ¥0.2
- 3,400 条全量回标: ~¥700-1000
- 含 prompt 调试 + retry: 预算 ¥1500

可控范围内。

---

## 质量保证流程

### 第一道：自动校验

```python
def validate_annotation(raw_response: str) -> Tuple[bool, List[str]]:
    """LLM 输出后立刻校验"""
    errors = []
    
    # 1. JSON 解析
    try:
        data = json.loads(raw_response)
    except:
        return False, ["Invalid JSON"]
    
    # 2. 必填字段
    required = ['essence.emotional_lever', 'essence.content_format', ...]
    for path in required:
        if not get_nested(data, path):
            errors.append(f"Missing: {path}")
    
    # 3. 闭集值检查
    if data['essence']['emotional_lever'] not in VOCAB['emotional_lever']:
        errors.append(f"Invalid emotional_lever: {data['essence']['emotional_lever']}")
    
    # 4. 一致性检查
    if (data['essence']['emotional_lever'] in NEGATIVE_LEVERS 
        and data['essence']['emotional_valence'] != 'negative'):
        errors.append("Negative lever but non-negative valence")
    
    return len(errors) == 0, errors
```

失败的标注自动 retry 一次（修正 prompt），再失败则进 failed_queue 等人工 review。

### 第二道：抽样人工 review

每 100 条标注完，随机抽 10 条人工 review：
- 看 reasoning 是否合理
- 看 essence 标注是否符合直觉
- 记录 disagreement 类型

**目标 IRR（标注一致性）≥ 0.7**

抽检结果用于：
- 优化 prompt
- 识别词表盲点
- 训练标注质量监控指标

### 第三道：高 disagreement 样本用 Opus 重标

抽检中标注质量低的批次，用 Claude Opus 重跑（多花 5 倍成本，但更准）。Opus 标注作为该批次的最终值。

---

## 标注 SOP（实操步骤）

### 1. 准备

- 词表 v0.2 已定稿（[05-controlled-vocab.md](05-controlled-vocab.md)）
- prompt 已 finalized 并跑过 30 条样本测试
- API key + 预算批准

### 2. 分批

把 3,400 条数据按项目分批：
- NUC_1（657 条）—— 第一批（最干净）
- HXZ_QD + HXZ_FB（394 条）—— 第二批
- RIO_1（296 条）—— 第三批
- WTG / TXQ_1 / NRT_3 / NRT_2 —— 第四批

每批跑完抽检，再决定下一批是否调整 prompt。

### 3. 并行调度

```python
async def annotate_batch(notes, concurrency=5):
    semaphore = asyncio.Semaphore(concurrency)
    
    async def annotate_one(note):
        async with semaphore:
            try:
                response = await claude_client.messages.create(...)
                valid, errors = validate_annotation(response.content)
                if valid:
                    save_annotation(note.note_id, response.content)
                else:
                    # retry once
                    response = await retry_with_corrections(...)
                    if valid:
                        save_annotation(...)
                    else:
                        add_to_failed_queue(note.note_id, errors)
            except Exception as e:
                log_error(note.note_id, e)
    
    await asyncio.gather(*[annotate_one(n) for n in notes])
```

### 4. 监控面板（Streamlit）

跑标注时实时显示：
- 完成进度（已标注 / 总数）
- 验证失败率
- API 调用速率和总成本
- 抽检队列里的样本

### 5. 结果回填

```sql
UPDATE notes 
SET emotional_lever = ?, 
    emotional_valence = ?,
    -- ...
    essence_annotated_by = 'claude-sonnet-4',
    essence_annotated_at = NOW(),
    essence_vocab_version = 'v0.2'
WHERE note_id = ?;
```

---

## 词表更新时的迁移策略

当词表从 v0.2 升级到 v0.3 时：

### 情况 1：新增值

老数据不重标。新数据用新词表。SQL 查询时记得带 `essence_vocab_version` 过滤。

### 情况 2：合并值

例：v0.2 有"焦虑撬动"和"恐惧撬动"，v0.3 合并为"焦虑/恐惧撬动"。

- 写 migration: `UPDATE notes SET emotional_lever = '焦虑/恐惧撬动' WHERE emotional_lever IN ('焦虑撬动', '恐惧撬动')`
- 老数据可直接用

### 情况 3：拆分值

例：v0.2 "焦虑撬动"，v0.3 拆为"经济焦虑撬动"、"健康焦虑撬动"等。

- 老数据**不能自动迁移** —— 必须重标
- 用 Opus 重标所有标了"焦虑撬动"的样本，按新词表分类

### 情况 4：删除值

罕见。如果决定删除，先把所有使用该值的样本重标，再删词表。

每次词表变更必须在 [DECISIONS.md](../DECISIONS.md) 记录。

---

## 蒲公英真实数据校准（audience 层）

LLM 推断的 audience demographic 和蒲公英真实数据的对照：

```python
# 拉蒲公英数据后
actual = pd.read_csv('xhs_dashboard_export.csv')

# 对每条笔记
for note in notes_with_dashboard_data:
    inferred = note.inferred_audience_profile['demographic']
    actual_dist = actual[actual.note_id == note.note_id]
    
    # 计算 disagreement
    age_disagreement = compare_distributions(
        inferred['age_band'], 
        actual_dist['age_distribution']
    )
    
    if age_disagreement > 0.3:
        # 重标这条 + 记录该模式
        flag_for_relearning(note)
```

随后定期：
- 分析高 disagreement 的 pattern
- 更新 audience 推断 prompt 加入校正
- 重新跑 audience 标注

这就是数据飞轮在 audience 层的具体闭环。

---

## 下一步

1. Ziao + 周哥完成 [05-controlled-vocab.md](05-controlled-vocab.md) review
2. Finalize [../prompts/essence_annotator.md](../prompts/essence_annotator.md)
3. 跑 30 条样本 pilot，看输出质量
4. 跑全量 3,400 条
5. 抽检 + 优化
