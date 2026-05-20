# 03 · 飞书表 → Truth Vault 映射协议

## 为什么存在

帆谷历史投放数据全部在飞书多维表格里。Truth Vault 需要把这些表的数据导入到标准 schema。但每个项目的飞书表都有细微差别（甲方诉求不同、命名习惯不同、字段演化）。

这个文档定义"如何把任意飞书投放表对齐到 Truth Vault 标准 schema"的协议。

> 核心原则：对齐工作分三段 —— **人定义** + **代码翻译** + **LLM 抽特征**。判断字段含义是人类决策，按定义翻译是代码确定性操作，特征抽取是 LLM 闭集分类。

---

## 三个 schema 家族

10 个历史项目的飞书表实际上属于三个 schema 家族（按时间演化）：

### 家族 A · 最新格式（RIO_1, WTG, TXQ_1）

**特征**:
- 字段命名：「曝光数」「阅读数」「互动数」（用"数"）
- 有完整的运营管理字段：「巡查状态」「最近检查时间」「已确认存活」「数据回收情况」
- 有「主页链接」「粉丝数」字段
- 「内容配图」单独成字段
- 有「客户反馈」「客户状态筛选」（客户视角标注）

**对应项目**: 当前主力 + 新项目应使用此模板

### 家族 B · 中间版本（NRT_2, NRT_3, NUC_1, HXZ_QD, HXZ_FB）

**特征**:
- 字段命名：「曝光量」「阅读量」「互动量」（用"量"）
- 有「数据汇总」「观众分析」（替代了 A 家族的「数据回收情况」）
- 有「关键词」「蓝词记录」「打款金额」「是否留存」「项目阶段」
- 有「父记录 2/3/4」（飞书多维表格的视图内部字段）
- 有「图片」字段（命名简化，对应 A 家族的「内容配图」）
- **没有「主页链接」「粉丝数」** —— 这是 B 家族的关键缺失

### 家族 C · 最老旧（TGV_1, QSHG_1）

**特征**:
- **没有「方向」字段**
- **没有数据回收字段**（曝光/阅读/互动全无）
- 大量 ad-hoc 日期化结算列（0907结算、0906评论结算…）
- tier 标签藏在「备注」字段（"新爆" / "淘汰" / "删0"）
- 有「发布笔记」字段（钓鱼帖/直给笔记/科普贴）

**对应项目**: 历史遗产，仅 TGV_1 有 tier 标注

---

## 标准字段映射表

下面是 10 个历史项目里所有出现过的核心字段，到标准 schema 的映射：

### 标识与基础

| 标准字段 | 家族 A | 家族 B | 家族 C |
|---|---|---|---|
| `note_id` | (生成: `<project_id>_<feishu_record_id>`) | 同 | 同 |
| `account_id` | 「素人编号」 | 「素人编号」 | 「素人编号」 |
| (`_account_name`) † | 「帐号昵称」 | — | — |
| (`_account_followers`) † | 「粉丝数」 | **缺，需补录** | **缺，需补录** |
| `publish_url` | 「反馈链接」 | 「反馈链接」 | 「反馈链接」 |
| `publish_time` | 「发布时间」 | 「发布时间」 | 「发布时间」 |

† 这两个字段映射到下划线前缀的 intermediate（如 `_account_name`），由 sync 脚本落 `raw_extra` JSONB；`truth_vault.notes` 表里没有这两个直接列。未来版本可以把它们写入 `truth_vault.accounts.account_memo`（D-032 重命名前叫 `notes_text`）或 `account_snapshots`，目前不阻塞主链路。

### 内容

| 标准字段 | 家族 A | 家族 B | 家族 C |
|---|---|---|---|
| `raw_content` | 「文案」 | 「文案」 | 「文案」 |
| `title`, `body`, `hashtags` | 从「文案」解析【标题】【正文】【话题标签】 | 从「文案」解析"标题："/"正文：" | 从「文案」解析"标题："/"正文：" |
| `intent` | 推断（项目元数据） | 「发布笔记」: 流量帖→traffic, 直给笔记→conversion | 「发布笔记」: 钓鱼帖→traffic, 直给笔记→conversion, 科普贴→educational |
| `target_blue_keywords` | (项目元数据) | 「关键词」 | (项目元数据) |

### 数据回收

| 标准字段 | 家族 A | 家族 B | 家族 C |
|---|---|---|---|
| `impressions` | 「曝光数」 | 「曝光量」 | **null** |
| `reads` | 「阅读数」 | 「阅读量」 | **null** |
| `interactions` | 「互动数」 | 「互动量」 | **null** |
| `hit_blue_keywords` | 「蓝词字段」 | 「蓝词记录」 | — |
| `data_quality_status` | 「数据回收情况」 | (推断) | "无数据" |

### Tier 标签（金标准）

| 标准字段 | 家族 A | 家族 B | 家族 C |
|---|---|---|---|
| `tier` | 「状态」解析 | 「状态」解析 | **「备注」解析** |
| `tier_source` | "状态字段" | "状态字段" | "备注字段" |

**家族 A/B 的「状态」字段解析规则**:
- 含"大爆" → `tier='大爆'`
- 含"爆贴"（不含"预备"）→ `tier='爆'`
- 含"爆贴预备" → `tier='预备'`
- 含"风控中" → `tier='风控'`
- 含"无水花" → `tier='趴'`
- 含"评估中" → `tier='未知'`（还在观察）

**家族 C 的「备注」字段解析规则**:
- 等于"新爆"或" 新爆"（含空格变体）→ `tier='爆'`
- 等于"淘汰" → `tier='趴'`
- 等于"删0"或含"删0"或含"他自己删了" → `tier='删除'`
- 其他 → `tier=null`

### 评论

| 标准字段 | 家族 A | 家族 B | 家族 C |
|---|---|---|---|
| `pinned_comment` | 「爆帖置顶评论」 | 「爆帖置顶评论」 | — |
| comments 表内容 | 「随贴评论」 | 「随贴评论」+「随贴评论素人」 | — |

### 项目专属（全部进 raw_extra）

家族 A 专属：「口碑通是否发起授权」「客户反馈」「客户状态筛选」「巡查状态」「最近检查时间」「已确认存活」「（梨响确认）文案预审状态」「发布截图」

家族 B 专属：「父记录 2」「父记录 3」「父记录 4」「临时-评论修改对比」「临时用—爆帖tag添加」「项目阶段」「打款金额」「是否留存」「理论金额结算」「数据汇总」「观众分析」

家族 C 专属：所有「0907结算」「0906评论结算」等日期化列、「产品贴数量」「提问帖数量」「私信/评论数量」、「是否打钱」、「二维码」、「整改备注」

---

## 三个家族的 mapping 模板差异

### 家族 A 模板（RIO_1 示例）

```yaml
project_id: RIO_phase1
schema_family: A
field_mapping:
  素人编号: account_id              # → truth_vault.accounts(account_id)
  发布时间: publish_time
  发布状态: _publish_status         # 进 raw_extra
  方向: _direction_raw              # 进 raw_extra，由 direction_decomposition 处理
  反馈链接: publish_url
  文案: raw_content
  曝光数: impressions
  阅读数: reads
  互动数: interactions
  状态: _status_raw                 # 走 tier_extraction 二次处理
  数据回收情况: data_quality_status
  # truth_vault.notes 表无 account_name / account_followers 列，用下划线前缀
  # 走 intermediates → 由 sync 脚本写入 truth_vault.accounts 的扩展字段，
  # 或落 raw_extra；不要直接映射到 notes（会因为不存在的列而 INSERT 失败）。
  帐号昵称: _account_name
  粉丝数: _account_followers
  主页链接: _account_url
  
tier_extraction:
  source: 状态字段
  rules: <见上方家族 A/B 规则>

direction_decomposition:
  # 见 04-onboarding-sop.md
  ...

project_specific_fields_to_raw_extra:
  - 口碑通是否发起授权
  - 客户反馈
  - 客户状态筛选
  - 巡查状态
  - 最近检查时间
  - 已确认存活
  - （梨响确认）文案预审状态
```

### 家族 B 模板（NUC_1 示例）

```yaml
project_id: NUC_phase1
schema_family: B
field_mapping:
  素人编号: account_id              # → truth_vault.accounts(account_id)
  发布时间: publish_time
  发布笔记: _intent_raw             # 中间变量，走 intent_mapping (不要直接映射到 intent，
                                    # 否则会把"流量帖"字符串塞进 enum)
  方向: _direction_raw
  关键词: target_blue_keywords
  反馈链接: publish_url
  文案: raw_content
  曝光量: impressions
  阅读量: reads
  互动量: interactions
  状态: _status_raw                  # 中间变量，走 tier_extraction
  蓝词记录: hit_blue_keywords
  
intent_mapping:
  流量帖: traffic
  直给笔记: conversion
  科普贴: educational

tier_extraction:
  source: 状态字段
  rules: <见上方家族 A/B 规则>

direction_decomposition:
  ...

# B 家族关键缺失：粉丝数
data_supplement_needed:
  - field: account_followers
    method: 通过 publish_url 查小红书 API 或手工补录
    
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
```

### 家族 C 模板（TGV_1 示例）

```yaml
project_id: TGV_phase1
schema_family: C
field_mapping:
  素人编号: account_id              # → truth_vault.accounts(account_id)
  发布时间: publish_time
  发布笔记: _intent_raw             # 钓鱼帖→traffic, 直给笔记→conversion (走 intent_mapping)
  反馈链接: publish_url
  文案: raw_content
  备注: _note_for_tier              # 中间变量，由 tier_extraction 处理
  
intent_mapping:
  钓鱼帖: traffic
  直给笔记: conversion
  科普贴: educational
  截图: other
  大字报: other
  小红书下单: conversion
  淘宝下单: conversion

# C 家族特殊：tier 从「备注」字段抽取
tier_extraction:
  source: 备注字段
  rules:
    - match_exact: ["新爆", " 新爆"]
      tier: 爆
    - match_exact: ["淘汰"]
      tier: 趴
    - match_contains: ["删0", "他自己删了"]
      tier: 删除
    - default: null

# C 家族关键缺失：数据回收 + 方向
missing_data:
  - impressions, reads, interactions: 全部 null
  - 方向: 项目没有方向字段
  - target_audience: 项目级单一定义（不分方向）

# C 家族特殊：QSHG_1 没有 tier 标签，进 archive 表
archive_only: false   # TGV_1 有 47 条「新爆」，进 notes 主表
                       # QSHG_1 这个值应为 true，进 archive 表

project_specific_fields_to_raw_extra:
  - 0907结算
  - 0906评论结算
  - <所有 0XXX 日期化列>
  - 产品贴数量
  - 提问帖数量
  - 私信/评论数量
  - 是否打钱
  - 二维码
  - 整改备注
```

---

## 飞书表 → 数据库的 sync 流程

### Step 1: 加载 mapping

```python
config = load_project_config(project_id)
# config 来自 projects.mapping_config JSONB 字段
```

### Step 2: 拉飞书表

两种方式二选一：

**方式 A · 飞书 OpenAPI（自动）**:
```python
from lark_oapi.client import Client
# 拉表，返回 list of dicts
records = lark_client.list_records(table_token=config.table_token)
```

**方式 B · 手动 xlsx 上传**（启动期推荐）:
```python
df = pd.read_excel(uploaded_file)
records = df.to_dict('records')
```

### Step 3: 按 mapping 翻译

```python
def translate_record(record: dict, config: ProjectConfig) -> NotesRow:
    row = NotesRow(project_id=config.project_id)
    
    # 字段重命名
    for source_col, target_field in config.field_mapping.items():
        if source_col in record:
            value = record[source_col]
            if target_field.startswith('_'):
                # 中间变量，不直接入主表
                row._temp[target_field] = value
            else:
                setattr(row, target_field, value)
    
    # intent 映射
    if '_intent_raw' in row._temp:
        row.intent = config.intent_mapping.get(
            row._temp['_intent_raw'], 'other'
        )
    
    # 方向拆解
    if '_direction_raw' in row._temp:
        decomposed = config.direction_decomposition.get(
            row._temp['_direction_raw'], {}
        )
        row.content_format = decomposed.get('content_format')
        row.target_audience = decomposed.get('target_audience')
        row.user_pain_point = decomposed.get('user_pain_point')
        row.product_focus = decomposed.get('product_focus')
    
    # tier 抽取
    if config.tier_extraction.source == '状态字段':
        row.tier = parse_status_tier(row._temp.get('_status_raw'))
        row.tier_source = '状态字段'
    elif config.tier_extraction.source == '备注字段':
        row.tier = parse_note_tier(
            row._temp.get('_note_for_tier'), 
            config.tier_extraction.rules
        )
        row.tier_source = '备注字段'
    
    # 文案解析
    row.title, row.body, row.hashtags = parse_content(row.raw_content)
    
    # raw_extra
    row.raw_extra = {
        col: record[col] 
        for col in config.project_specific_fields_to_raw_extra 
        if col in record
    }
    
    return row
```

### Step 4: 验证

```python
def validate(row: NotesRow, config: ProjectConfig) -> List[str]:
    errors = []
    
    # 必填字段
    if not row.raw_content:
        errors.append("文案为空")
    if not row.publish_url:
        errors.append("反馈链接为空")
    if not row.target_audience:
        errors.append("target_audience 必填（onboarding 时定义）")
    
    # 飞书新增列检测（防止悄悄漏字段）
    flagged_cols = set(record.keys()) - set(config.field_mapping.keys()) - set(config.project_specific_fields_to_raw_extra)
    if flagged_cols:
        errors.append(f"飞书表出现未声明列: {flagged_cols}，请更新 mapping")
    
    return errors
```

### Step 4.5: 数值字段清洗（重要）

⚠️ **在 NUC_1 试导入时发现的坑**：飞书表的数值字段（impressions / reads / interactions / account_followers）有时会用**占位符字符**而非 null 或空：

| 占位符 | 含义 | 出现频率 |
|---|---|---|
| `"/"` | 未填 / 无数据 | NUC_1 中很常见（曝光量/阅读量字段） |
| `"-"` | 同上 | 偶见 |
| `""` 空字符串 | 未填 | 常见 |
| `"无"` | 中文表达 | 偶见 |
| 全角数字（"１２３"） | 输入法误用 | 极少 |
| `NaN` (pandas) | 真正的 null | 标准 |

**必须做的清洗**（所有项目通用，不需要每个项目单独配置）：

```python
def clean_numeric(value):
    """清洗数值字段，把占位符统一为 None"""
    if value is None:
        return None
    if pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value == int(value) else value
    
    # 字符串处理
    s = str(value).strip()
    
    # 占位符黑名单
    PLACEHOLDERS = {"/", "-", "—", "", "无", "/无", "N/A", "n/a", "null", "NULL"}
    if s in PLACEHOLDERS:
        return None
    
    # 全角转半角
    s = s.translate(str.maketrans('０１２３４５６７８９', '0123456789'))
    
    # 尝试转 int
    try:
        return int(s.replace(',', ''))  # 处理千位逗号
    except ValueError:
        # 既不是占位符也不是数字 → 记录但返回 None
        logger.warning(f"无法解析的数值字段: {value!r}")
        return None
```

应用于所有数值字段：impressions / reads / interactions / account_followers / 其他将来添加的数值字段。

**结果**：数据库里看到的 `impressions = NULL` 含义是"无数据"，统一可比。SQL 查询 `WHERE impressions IS NOT NULL` 能可靠过滤。

### Step 5: 入库

```python
if errors:
    log_error(row, errors)
    skip_row()
else:
    insert_into_notes(row)
    if has_comments:
        insert_into_comments(row.note_id, comments)
```

### Step 6: Sync 报告

每次 sync 输出报告：

```
=== Project NUC_phase1 · Sync Report ===
拉取记录数: 1103
成功入库: 657
跳过（无文案/无链接）: 446
跳过（重复 note_id）: 0
错误（schema 失配）: 0
新发现字段: 无
入库覆盖率: 60%
```

---

## 治理纪律（不可妥协）

### 1. 硬阻断比报警有效

- mapping.yaml 必填字段没填 → sync 失败
- 飞书表多了未声明列 → sync 失败，直到人工确认
- 必填字段缺失（如 raw_content）→ 那一行入库失败但其他行继续

### 2. Schema 版本化

- mapping.yaml 含 `version` 字段
- 标准 schema 升级时，老项目 mapping 自动标"需要升级"
- 老数据按老 schema 留着，新数据按新 schema 进

### 3. 定期对账

每周一次：
- 飞书表行数 vs 数据库行数
- 字段缺失率
- 上次 sync 时间
- 差距大于阈值（如 10%）报警

### 4. 永远不丢数据

未识别字段进 raw_extra。即使当时没识别出价值，将来发现有用可以回头分析。

---

## 启动期推荐方案（前 3 个月）

不做飞书自动拉取。流程是：

1. 项目结案后 7 天内，项目经理 export 飞书表为 xlsx
2. 上传到内部 Web UI（Streamlit 做的）
3. 触发 sync，看报告
4. 报告无错误 → 入库
5. 报告有错误 → 项目经理 + 策略 lead 排查（可能要更新 mapping）

3 个月后流程稳定，再上飞书自动拉取（lark-oapi）。

---

## 下一步

读完这个文档，接着读：

1. [04-onboarding-sop.md](04-onboarding-sop.md) —— 新项目第一次接入的 step-by-step
2. [../mappings/_template.yaml](../mappings/_template.yaml) —— mapping.yaml 模板
