# 07 · 蒲公英后台数据接入

> ⚠️ **落地方案见 [docs/23-L3-audience-layer-plan.md](23-L3-audience-layer-plan.md)**(现状 vs 本文设计的差距 + 分阶段)。
> 摸底结论(2026-06-05):LLM 推断已有(essence 副产品,1042 条);**真实蒲公英 age/gender/city 基本没拉进来**
> (观众分析列大多「无」)→ 校准闭环卡在"先拉真实数据"(ops),**先做的是 D-013 受众不符检测**(纯代码、688 条可跑)。

## 为什么存在

Schema v1 包含 `actual_audience_data` 字段（[02-schema-v1.md](02-schema-v1.md)），用来存小红书蒲公英 / 创作中心后台拉到的真实观众数据。这个文档定义如何接入这些数据、怎么和 LLM 推断的 audience profile 对齐。

> Ziao 提到现在就能拉蒲公英数据，这是 Truth Vault 的一个独特价值杠杆 —— 大多数 AI 营销工具拿不到，只有自己投放的 agency 能拉到。

---

## 蒲公英能拉到什么

按 Ziao 的反馈，浅层观众数据可拉的字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| 年龄分布 | 分布百分比 | 18 以下 / 18-24 / 25-30 / 31-40 / 41+ |
| 性别分布 | 百分比 | 女 / 男 |
| 城市分布 | 分布百分比 | 按一线/新一线/二线…分类 |
| 兴趣标签 | 标签列表 | 平台推断的兴趣类别 |
| 设备分布 | 百分比 | iOS / Android（可选） |

深层数据（行为路径、停留时长等）通常需要更高权限，第一阶段不依赖。

---

## 数据结构设计

`notes.actual_audience_data` 字段是 JSONB，结构如下：

```json
{
  "synced_at": "2026-05-18T12:00:00",
  "data_source": "xhs_pugongying",
  "raw_table_url": "<飞书或客户给的原始表 URL>",
  
  "age_distribution": {
    "18_below": 0.05,
    "18_24": 0.22,
    "25_30": 0.31,
    "31_40": 0.28,
    "41_above": 0.14
  },
  
  "gender_distribution": {
    "female": 0.78,
    "male": 0.22
  },
  
  "city_distribution": {
    "1线": 0.15,
    "新1线": 0.20,
    "2线": 0.25,
    "3-4线": 0.30,
    "5线及以下": 0.10
  },
  
  "interest_tags": [
    {"tag": "美妆", "weight": 0.45},
    {"tag": "护肤", "weight": 0.30},
    {"tag": "穿搭", "weight": 0.25}
  ],
  
  "device_distribution": {
    "ios": 0.65,
    "android": 0.35
  },
  
  "total_views_at_sync": 12345,
  "completeness_score": 0.85
}
```

`completeness_score` 反映蒲公英给的数据完整度 —— 不同账号 / 不同时段返回的字段不一样。

---

## 拉取流程

### 方式 A · 手动导出（启动期推荐）

蒲公英后台导出 CSV → 上传到内部 Web UI → 系统解析入库。

**优点**: 零开发成本，立刻能跑  
**缺点**: 依赖人工，时效慢

操作步骤：
1. 投放人在蒲公英后台导出该笔记的"观众分析"CSV
2. 上传到 Truth Vault Web UI（`/upload-pugongying`）
3. 系统按 publish_url 匹配 note_id，解析数据入 `actual_audience_data`
4. 自动校验：LLM 推断 vs 真实数据，diff 大的写入 review queue

### 方式 B · 蒲公英 OpenAPI（自动化，二期）

如果蒲公英 / 小红书提供 API：
- 配置 API key + token
- 定时任务（每周一次）拉新发布的笔记数据
- 自动入库

**当前状态**: 待调研 —— 需要先确认蒲公英是否提供 OpenAPI。

### 方式 C · 飞书表中转（中期方案）

如果团队已经把蒲公英数据回填到飞书表里，那 Truth Vault 直接从飞书同步即可，无需单独流程。

---

## 字段对齐：LLM 推断 vs 真实数据

LLM 推断的 `inferred_audience_profile.demographic` 和真实数据需要对齐：

| 字段 | LLM 闭集 | 蒲公英真实数据 | 对齐方式 |
|---|---|---|---|
| age_band | [20-29, 30-39, 40-49, 50+] | 5 档分布百分比 | 把真实分布做 majority 归类，找最大占比的档位 |
| gender_skew | female / male / mixed | 性别百分比 | >70% 女 → female; >70% 男 → male; 否则 mixed |
| city_tier | [1线, 新1线, 2线, 3-4线, 5线] | 5 档百分比 | 取最大占比 + 第二大（如果 ≥25%）|
| life_stage | 学生/职场新人/...（闭集） | 无对应字段 | 不对齐（只能靠 LLM 推断） |
| value_orientation | 务实/精致/... | 无对应字段 | 不对齐 |
| income_band | 学生/入门/中产/高净值 | 无对应字段 | 不对齐 |

**结论**: 真实数据能校准的只有 age / gender / city 三项。其他 demographic 字段和所有 psychographic 字段只能靠 LLM。

但即使只有这三项校准，价值已经很大：
- age / gender 是 audience 的最基础维度
- LLM 在这三项上推断错了，整个 audience profile 就废了

---

## 校准闭环算法

```python
def calibrate_audience_inference(note):
    """每条笔记拉到真实数据后，对照 LLM 推断，更新校准信号"""
    
    actual = note.actual_audience_data
    inferred = note.inferred_audience_profile['demographic']
    
    diffs = {}
    
    # Age
    actual_age_majority = max(
        actual['age_distribution'].items(), 
        key=lambda x: x[1]
    )[0]
    inferred_age = inferred['age_band'][0]  # 主 age_band
    
    diffs['age_match'] = (actual_age_majority == inferred_age)
    diffs['age_actual'] = actual_age_majority
    diffs['age_inferred'] = inferred_age
    
    # Gender
    actual_gender = (
        'female' if actual['gender_distribution']['female'] > 0.7
        else 'male' if actual['gender_distribution']['male'] > 0.7
        else 'mixed'
    )
    diffs['gender_match'] = (actual_gender == inferred['gender_skew'])
    
    # City tier
    actual_city_majority = max(
        actual['city_distribution'].items(),
        key=lambda x: x[1]
    )[0]
    diffs['city_match'] = actual_city_majority in inferred['city_tier']
    
    # Write to calibration log
    save_calibration_record(note.note_id, diffs)
    
    # Trigger retraining if disagreement systematic
    if rolling_disagreement_rate() > 0.3:
        trigger_audience_prompt_revision()
```

### Disagreement 监控

汇总所有有真实数据的笔记，计算 LLM 推断准确率：

```sql
-- 按品类看 age 推断准确率
SELECT 
    p.category,
    COUNT(*) as total,
    SUM(CASE WHEN c.age_match THEN 1 ELSE 0 END) as matches,
    SUM(CASE WHEN c.age_match THEN 1 ELSE 0 END)::FLOAT / COUNT(*) as accuracy
FROM truth_vault.audience_calibrations c
JOIN truth_vault.notes n ON c.note_id = n.note_id
JOIN truth_vault.projects p ON n.project_id = p.project_id
GROUP BY p.category;
```

**目标准确率**: age ≥ 70%, gender ≥ 85%, city ≥ 60% 

低于阈值的品类需要：
- 优化 audience 推断 prompt（针对该品类加更多上下文）
- 用 Opus 重标该品类历史数据

---

## 蒲公英数据账号清单（下一步要做的事 #4）

这是 [CURRENT_STATE.md](../CURRENT_STATE.md) 列出的 #4 任务。Ziao + 投放执行同事整理一张表：

| 项目 | 平台账号 | 蒲公英权限 | 可拉字段 | 数据格式 |
|---|---|---|---|---|
| NUC_1 | ? | ✅ / ❌ | age/gender/city/... | CSV / API |
| HXZ_QD | ? | | | |
| ... | | | | |

目的：知道哪些项目可以做 audience 校准，先做最完整的项目。

---

## 合规考虑

涉及客户数据 —— 需要遵守的几个原则：

1. **数据隔离**: 每个项目的 actual_audience_data 严格按 project_id 隔离，Supabase Row Level Security 配好
2. **跨客户聚合**: 现阶段不做。将来如果做（如"保健品品类 35+ 女性平均特征"分析），需要先确认客户合同是否允许第三方数据聚合使用。这是阶段 3+ 才考虑的问题，现在不阻塞。

**之前担忧"拉蒲公英数据前要和处方药客户合规对齐"已被推翻**（见 [99-rejected-ideas.md](99-rejected-ideas.md) R-012）—— 自己投放的笔记拉自己后台数据是日常工作流程，不需要额外对齐。

---

## 蒲公英数据的下游应用

### 阶段 1（启动期）

- 作为 audience 推断的校准信号
- 在 anchor 报告里多一行："该项目实际观众 50% 在 30-39 岁，目标受众设定吻合"

### 阶段 2（训练分类器）

- 真实 audience 数据作为 feature 进入模型
- 模型能学到 "30-39 女性 + 焦虑撬动 + 情感叙事 = 高爆款概率"
- 但只有部分数据有真实 audience —— 半监督学习

### 阶段 3+（语义融合）

- "找历史上目标受众相似的爆款" —— 跨项目策略迁移的真正实现
- 例：HXZ_QD 想做新 angle，查"30-39 女性 + 焦虑撬动 + 情感叙事"在其他品类的爆款，看能不能借鉴

---

## 下一步

1. **完成账号清单**（任务 #4）—— Ziao + 投放执行
2. **试拉一个项目数据** —— 推荐 NUC_1（先做最干净的）
3. **校准闭环验证** —— 看 LLM 推断 vs 真实数据的 disagreement
