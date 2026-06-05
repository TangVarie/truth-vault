# 04 · 新项目 Onboarding SOP

## 为什么存在

每个新项目接入 Truth Vault 之前，需要做一次 20-40 分钟的"Onboarding 会议"，把项目策略形式化为 mapping.yaml。这个文档是这个会议的标准操作流程。

> 这个会议不是新增的工作 —— 任何项目开盘都要做策略对齐。Onboarding 是把对齐结果**形式化记录**到 yaml。多花 5-10 分钟，换永久数据资产。

---

## 谁参加

| 角色 | 必要性 |
|---|---|
| **项目经理** | 必须，提供项目原始 context |
| **策略 lead（Ziao 或周哥）** | **必须**，方向拆解、tier 阈值需要策略判断 |
| **客户经理** | 可选，但有客户特殊要求时建议参加 |
| **新会话 Claude（你）** | 协助，跑流程、起草 yaml |

---

## 开会前准备

项目经理准备：
- 飞书表的访问链接（让大家看得到）
- 项目 brief（产品 / 平台 / 投放预算 / 投放时间 / 已知客户特殊要求）
- 如果是有历史数据的项目，导出最新 xlsx

策略 lead 准备：
- 这个项目的**策略意图**（流量向 vs 产品向、什么品类、什么人群）
- 是否复用了之前项目的方法论（如有，参考之前的 mapping）

---

## SOP · 7 个步骤

### Step 1 · 项目元数据（5 分钟）

填这些字段：

```yaml
project_id: <品牌_期数>  # 例: NUC_phase1, NRT_phase3
brand: <品牌中文名>
product: <具体产品>
category: 
  - 处方药 / OTC药 / 保健品 / 医疗器械 / 美妆 / 个护 / 酒类 / 食品饮料 / 母婴 / 3C数码 / 家居家电 / 服饰鞋包 / 教育 / 其他   # 权威见 docs/05 §9
platform: 
  - xiaohongshu / douyin / both
schema_family: A / B / C    # 看飞书表字段命名判断
start_date: YYYY-MM-DD
end_date: YYYY-MM-DD（可填预估）
```

**判断 schema_family 的快速规则**:
- 飞书表有「巡查状态」「最近检查时间」「主页链接」 → 家族 A
- 没有 A 家族标志，但有「关键词」「蓝词记录」「项目阶段」 → 家族 B
- 没有「方向」、没有数据回收字段、有大量日期化结算列 → 家族 C

**合规提示**:
- category 是处方药 → 弹出 "处方药合规模板"，预填禁忌词、警示用语
- category 是保健品 → 弹出 "保健品合规模板"，预填"不能宣称疗效"等
- category 是美妆 → 检查"功效宣称"是否需要备案

### Step 2 · 字段映射（10-15 分钟）

把飞书表的列名映射到标准 schema。

**操作**:
1. 上传飞书表（xlsx）或贴入字段列表（CSV）
2. 系统自动匹配：约 70-80% 字段能自动匹配（按家族 A/B/C 的标准映射表）
3. 剩余字段逐列点击确认：
   - 标准字段（下拉选）
   - 进 raw_extra（项目专属）
   - 忽略（确认无用）

**陷阱与对应**:

| 飞书列名 | 容易误判 | 正确选择 |
|---|---|---|
| 「图片」（B 家族） | 看起来无用 | 标 `_image_url` 进 raw_extra（可能将来做图片特征分析） |
| 「项目阶段」 | 看起来重要 | 现有项目都空着，标 raw_extra |
| 「父记录 2/3/4」 | 看起来神秘 | 飞书内部字段，标 raw_extra 或忽略 |
| 「关键词」 | 容易和 hit_blue_keywords 混淆 | 这是**目标蓝词**（投放前定的），映射到 `target_blue_keywords` |
| 「蓝词记录」 | 同上 | 这是**实际命中蓝词**（事后回收），映射到 `hit_blue_keywords` |
| 「随贴评论」 | 容易当成无用 | **重要**：进 comments 表 |

### Step 3 · 方向拆解（最关键，5-15 分钟）

这一步是 onboarding 价值密度最高的部分，**也是 NRT 系列要花 1 小时的原因**。

**操作**:
1. 系统列出飞书表里「方向」字段的所有不同取值
2. 对每个取值，策略 lead 给出 4 个映射：

```yaml
direction_decomposition:
  "方向一 喝酒感受":
    content_format: 情感叙事        # 必填，受控词表
    intent_override: traffic        # 可选，覆盖项目级 intent
    target_audience: ["年轻女性"]   # 必填，受控词表
    user_pain_point: 独居松弛       # 可选，自由文本
    product_focus: null             # 可选，项目专属
    tier_threshold_override: null   # 可选，方向级别覆盖项目级阈值
```

**预定义参考**（基于已有项目）:

| 飞书方向（典型例子） | content_format | target_audience | user_pain_point |
|---|---|---|---|
| 喝酒感受 (RIO) | 情感叙事 | 年轻女性 | 独居松弛 |
| 反差与破圈 (RIO) | 反差破圈 | 通用 | 意外感 |
| 提问与红黑榜 (RIO) | 提问求助 | 通用 | 选品困惑 |
| 产品直给型 (WTG) | 直给推荐 | 通用 | 选品困惑 |
| 直播切片 (WTG) | 场景植入 | 通用 | (依产品) |
| NRT疗法引导 (NRT) | 认知重构 | 通用 | NRT 科普 |
| 女性自发 (NRT) | 情感叙事 | 年轻女性 | 戒烟动机 |
| 为爱助戒 (NRT) | 情感叙事 | 伴侣家人 | 为伴侣戒烟 |
| 持妆问题 (HXZ) | 场景植入 | 中年女性 | 持妆需求 |
| 年龄问题 (HXZ) | 场景植入 | 中年女性 | 衰老焦虑 |
| 任何手术后恢复相关 (NUC) | 场景植入 | 病患家属, 宝妈 | 术后营养 |
| 糖尿病相关 (NUC) | 认知重构 | 病患家属 | 血糖管理 |

⚠️ **target_audience 必须从 [docs/05-controlled-vocab.md](05-controlled-vocab.md) 的 11 个闭集值中选**：年轻女性 / 中年女性 / 银发女性 / 年轻男性 / 中年男性 / 银发男性 / 学生党 / 宝妈 / 伴侣家人 / 病患家属 / 通用

**NRT 特殊：组合标签**

```yaml
direction_decomposition:
  "为爱助戒, 咀嚼胶":
    target_audience: ["伴侣家人"]
    content_format: 情感叙事
    user_pain_point: 为伴侣戒烟
    product_focus: 咀嚼胶    # 多维标签拆到这个字段
```

### Step 4 · Tier 抽取规则（5 分钟）

**家族 A/B**: 默认从「状态」字段抽取，使用 [03-mapping-protocol.md](03-mapping-protocol.md) 里的标准规则。无需配置。

**家族 C**: 必须配置「备注」字段的解析规则：

```yaml
tier_extraction:
  source: 备注字段
  rules:
    - match_exact: ["新爆"]
      tier: 爆
    - match_exact: ["淘汰"]
      tier: 趴
    # 该项目特殊词需补充
    - default: null
```

### Step 5 · Tier 阈值（数值层面，3 分钟）

定义这个项目"爆"是多少互动数。**项目级别**（不同项目阈值差异极大）。

参考已有数据：

| 项目 | 爆 阈值（互动数） | 大爆 阈值 |
|---|---|---|
| RIO_1 | 100 | 500 |
| NRT_3 | 200 | 1500 |
| NUC_1 | 100 | 800 |
| HXZ_QD | 30 | 1000 |
| HXZ_FB | 50 | 1500 |

**新项目设阈值的方法**:
- 没有历史数据：从行业常识起步，跑 50 条后再调
- 有相似品类历史：参照那个项目的阈值
- 客户预算极大或极小：相应放大/缩小

```yaml
tier_thresholds:
  爆: 100
  大爆: 1000
```

注意：tier 阈值只用于**数值推断兜底**（没有人工标 tier 时按数值算）。**有人工 tier 标注时优先用人工**。

### Step 6 · 合规和雷区（5-10 分钟）

按 category 预填，但项目级别可以追加：

```yaml
compliance:
  base_template: 处方药         # 预填的基础模板
  
  custom_red_flags:
    - "禁止任何'治疗'字样"
    - "禁止剂量数字（mg/g）"
    - "禁止与症状直接关联"
    - "禁止使用'根治''治愈'等绝对化表达"
  
  blue_keyword_strategy:
    primary: ["力克雷", "NRT 疗法"]
    secondary: ["尼古丁替代", "戒烟科学方法"]
    avoid: ["处方药", "治疗"]
```

### Step 7 · 保存 + 数据预导入（5 分钟）

生成完整 mapping.yaml，保存到 `mappings/<project_id>.yaml`（含 `sync_config` 飞书坐标）。

**先跑只读体检**（不写库、不调 LLM，几秒出报告）：

```bash
FEISHU_APP_ID=… FEISHU_APP_SECRET=… python scripts/preflight_mapping.py <project_id>
```

preflight 复用真 `transform_row` 投影全表，一屏看清：
- **未声明列** → 会被 D-021 整行 quarantine（NRT_2 曾因此丢 482 行真内容）；报告会标出"哪些列没声明、其中多少行有正文＝真笔记会丢"。
- **品类是否在受控闭集**（否则 sync 撞 `notes.category` CHECK）。
- **入库投影**：会 upsert 多少 / 空占位静默多少 / 因未声明列丢多少。
- **分布**：tier（爆+大爆＝燃料)、intent（`other` 多＝intent_mapping 没覆盖)、**方向是否全部命中 `direction_decomposition`**。

退出码 1 = 有该先修的阻断问题（未声明列丢真内容 / 品类非法）→ 按报告改 mapping，重跑到干净。
**这一步把"在 prod 真跑→看炸什么→修"收敛成"接表前一键体检"。**

体检干净 → PR → 合 → `Daily TV sync`（全名，先 dry_run）→ 实跑 → backfill essence。

---

## NUC_1 试点 Onboarding 演示

下面是 NUC_1 项目（保健品 Nucare）真实跑一遍 onboarding 的预期输出：

```yaml
# mappings/NUC_phase1.yaml

version: 1.0
project_id: NUC_phase1
brand: 大象集团
product: Nucare 全营养液体
category: 保健品
platform: xiaohongshu
schema_family: B
start_date: 2025-11-03
end_date: 2026-XX-XX

# 字段映射
field_mapping:
  素人编号: account_id              # → truth_vault.accounts(account_id)
  发布时间: publish_time
  发布笔记: _intent_raw
  是否发布: _published_status
  方向: _direction_raw
  关键词: target_blue_keywords
  反馈链接: publish_url
  文案: raw_content
  状态: _status_raw
  曝光量: impressions
  阅读量: reads
  互动量: interactions
  蓝词记录: hit_blue_keywords
  爆帖置顶评论: pinned_comment
  随贴评论: _comment_text          # 进 comments 表
  随贴评论素人: _comment_text_persona

intent_mapping:
  流量帖: traffic
  直给笔记: conversion

# 注意: NUC_1 使用 D-014 LLM 子分类机制，飞书方向粗粒度 → 子方向细化
# 完整定稿版见 [../mappings/NUC_phase1.yaml](../mappings/NUC_phase1.yaml)
# 简化版示例（不展示 sub_directions 细节）：
direction_decomposition:
  "营养保健代餐相关":
    # 实际有 sub_directions: 健身减脂 / 关心父母营养 / 其他
    # 此处简化为粗集合 target_audience
    content_format: 情感叙事
    target_audience: ["年轻女性", "病患家属"]
    user_pain_point: 营养摄入需求（健身减脂 + 父母饮食）
  "任何手术后恢复相关":
    # 实际有 sub_directions: 产后宝妈 / 照顾家人手术 / 其他
    content_format: 情感叙事
    target_audience: ["宝妈", "病患家属"]
    user_pain_point: 术后/产后营养
  "糖尿病相关":
    content_format: 情感叙事
    target_audience: ["病患家属"]
    user_pain_point: 糖尿病饮食与营养平衡
  "抗癌放化疗相关":
    # 注: semantic_redefined_as: 重症慢病家属（D-015）
    content_format: 情感叙事
    target_audience: ["病患家属"]
    user_pain_point: 重症/慢病照顾营养支持

tier_extraction:
  source: 状态字段
  # 使用标准 A/B 家族规则

tier_thresholds:
  爆: 100
  大爆: 800

compliance:
  base_template: 保健品
  custom_red_flags:
    - "禁止宣称疗效"
    - "禁止'治疗''治愈''康复'等绝对化表达"
    - "禁止替代医疗"

# B 家族关键缺失
data_supplement_needed:
  - field: account_followers
    method: 通过 publish_url 调小红书 API 补录
    
project_specific_fields_to_raw_extra:
  - 父记录 2
  - 父记录 3
  - 父记录 4
  - 临时-评论修改对比
  - 临时用—爆帖tag添加
  - 项目阶段
  - 打款金额
  - 是否留存
  - 理论金额结算
  - 数据汇总
  - 观众分析
  - 关键词       # 注意：已 mapping，原始值也保留备查
```

---

## 常见问题

### Q: 项目方向比较模糊，不知道选哪个 content_format

**A**: 看正文主导结构。
- 文案大量场景描写、有情节有对话 → 情感叙事
- 文案对比多个产品 → 横评对比
- 文案讲原理 / 教方法 → 认知重构 / 教程攻略
- 文案直接推产品好处 → 直给推荐
- 文案以提问开头希望评论区回答 → 提问求助

### Q: 多个方向都符合怎么办？

**A**: 选**最主导**的。`content_format` 是单选。如果项目方向本身就跨多种内容形式（如 NRT 的"NRT疗法引导, 戒烟贴"），用 product_focus 字段补充。

### Q: target_audience 是否要细分？

**A**: 第一版词表用粗分（年轻女性 / 中年女性 / 银发族 / 学生党 / 宝妈 / 中年男性 / 伴侣家人 / 通用）。等数据多了再考虑细分。

### Q: 项目经理对方向定义没把握怎么办？

**A**: 必须策略 lead 在场。Onboarding 不允许只项目经理一人填 —— 方向定义错了后面所有分析都受影响。

### Q: NRT 系列已经有方向组合标签（"为爱助戒, 咀嚼胶"），怎么处理？

**A**: 对每种组合显式列出映射，**不要让系统自动推断组合**。NRT_3 有 ~15 种独立标签 + 组合，需要 1 小时专门讨论。

---

## Onboarding 验收清单

完成 onboarding 后检查：

- [ ] project_id 格式正确（品牌_期数）
- [ ] schema_family 正确判断
- [ ] 所有「方向」取值都有映射
- [ ] tier_thresholds 设了爆/大爆两档
- [ ] 合规模板按 category 加载
- [ ] 字段映射无 "未识别" 状态
- [ ] 试导入 10 条样本无错误
- [ ] mapping.yaml 文件已 commit 到 `mappings/` 目录

---

## 下一步

完成 onboarding 后，可以：

1. 触发完整 sync —— 把项目所有历史数据入库
2. 跑 essence 标注 —— 看 [06-essence-annotation.md](06-essence-annotation.md)
3. 跑数据健康检查 —— 看 sync 报告

或者，如果想看更多 onboarding 例子，参考 `mappings/` 目录下已完成的项目 yaml。
