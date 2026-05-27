# 11 · 飞书多维表格建表指南

> 给运营 / 项目经理：每个新项目接入 Truth Vault 前，要先建一张飞书多维表格
> （Bitable）当数据入口。这份文档教你建哪些列、列名怎么定、怎么拿 API 凭证、
> 怎么避坑。
>
> 配套文档：`docs/04-onboarding-sop.md`（接入会议 7 步）、
> `docs/03-mapping-protocol.md`（A/B/C 家族字段映射）、
> `mappings/_template.yaml`（mapping 模板）。

---

## ⭐ 第一原则：列结构真相 = 你项目的 mapping yaml

**飞书表该建哪些列、列名叫什么 —— 唯一权威是你那个项目的
`mappings/<项目>.yaml` 里 `field_mapping` 左边那一列。**

sync 脚本 (`scripts/sync_feishu_notes_to_truth_vault.py`) 是按
"飞书列名 → schema 字段" **精确字符串匹配** 的。飞书列名和 yaml 左边对不上
→ 那列数据要么进 `raw_extra`（如果在 `project_specific_fields_to_raw_extra`
白名单里），要么整行进 `undeclared_fields_quarantine`（D-021），**不会静默入库**。

所以：

- **每个项目一张表 + 一个 mapping yaml**，不要一张表跑多项目。
- **列名定下来就不改**。改名必须同步改 mapping yaml，否则 sync 断。
- 不同项目列名可以不一样（事实上 NUC 和 NRT 就略有不同）—— 因为各有各的
  yaml。**不要照搬别的项目的列名，照你自己项目的 yaml。**

> ⚠️ 历史教训：曾有一份建表文档用 A 家族命名（`曝光数`/`命中关键词`），但当前
> 所有在用项目都是 B 家族（`曝光量`/`蓝词记录`）。照过时文档建表 → 数据进
> quarantine。**永远以 yaml 为准。**

---

## 核心字段（所有项目都要）

下面列名是**当前 3 个项目 (NUC_phase1 / NRT_phase2 / NRT_phase3) 的实际约定**
（B 家族）。新项目沿用这套即可；真要改名，记得同步改 yaml。

| 飞书列名 | 字段类型 | mapping yaml 映射 | schema 字段 | 必填 |
|---|---|---|---|---|
| 文案 | 多行文本 | `文案: raw_content` | `notes.raw_content` | ✅ NOT NULL（空行会进 quarantine） |
| 反馈链接 | URL 或文本 | `反馈链接: publish_url` | `notes.publish_url` | 强烈建议 |
| 发布时间 | 日期 | `发布时间: publish_time` | `notes.publish_time` | 建议（缺则 era_tag / 时序分析无法算） |
| 素人编号 | 文本 | `素人编号: account_id` | `notes.account_id` | 建议（缺则 accounts FK 不填） |
| 状态 | **单选** | `状态: _status_raw` → tier_extraction | `notes.tier` | ✅ 不填则全部 tier=null |
| 曝光量 | **数字** | `曝光量: impressions` | `notes.impressions` | 建议 |
| 阅读量 | **数字** | `阅读量: reads` | `notes.reads` | 建议 |
| 互动量 | **数字** | `互动量: interactions` | `notes.interactions` | 建议 |

> **note_id 不用建列** —— sync 脚本按 `f"{project_id}_{feishu_record_id}"`
> 自动生成（feishu_record_id 是飞书每行的内部 ID）。

---

## 「状态」单选的选项值（必须和 yaml 一字不差）

`状态` 是单选，选项文本必须和 `mappings/*.yaml` 的 `tier_extraction.rules`
的 `match_contains` 完全一致。当前 3 个项目识别这 6 个：

| 飞书「状态」选项 | → tier |
|---|---|
| 大爆 | 大爆 |
| 爆贴预备 | 预备 |
| 爆贴 | 爆 |
| 风控 | 风控 |
| 无水花 | 趴 |
| 评估中 | 未知 |

> 匹配是 `contains`（包含即可），所以"爆贴-已复盘"也能命中"爆贴"。但顺序重要：
> yaml 里"大爆"在"爆贴"前匹配，所以"大爆"不会被误判成"爆"。你可以加更多选项，
> 但这 6 个是 mapping 已识别的；加新选项要同步加 `tier_extraction.rules`。

---

## 按家族追加

### B / C 家族（有意图分类，如 NUC / NRT）

| 飞书列名 | 字段类型 | mapping 映射 | 去向 |
|---|---|---|---|
| 发布笔记 | **单选** | `发布笔记: _intent_raw` + intent_mapping 段 | `notes.intent` |
| 方向 | 单选或文本 | `方向: _direction_raw` + direction_decomposition 段 | 多维度拆解（见下） |
| 关键词 | 多选（推荐）或文本 | `关键词: target_blue_keywords` | `notes.target_blue_keywords` (TEXT[]) |
| 蓝词记录 | 多选或文本 | `蓝词记录: hit_blue_keywords` | `notes.hit_blue_keywords` (TEXT[]) |
| 爆帖置顶评论 | 多行文本 | `爆帖置顶评论: pinned_comment` | `notes.pinned_comment` |
| 随贴评论 | 多行文本 | `随贴评论: _comment_text` | comments 表（Phase 2 LLM 解析） |
| 随贴评论素人 | 多行文本 | `随贴评论素人: _comment_text_persona` | comments 表 |

**「发布笔记」单选选项** 要在 yaml 的 `intent_mapping` 段全列出。当前用值：

| 飞书「发布笔记」选项 | → intent |
|---|---|
| 流量帖 | traffic |
| 钓鱼帖 | traffic（NRT_2 用语） |
| 直给笔记 | conversion |

**「方向」字段是 onboarding 价值最高的一步** —— 它的每个取值要在
`direction_decomposition` 段拆成 content_format / target_audience /
user_pain_point 等多维度，可能还要配 LLM 子分类（见 NUC_phase1.yaml 的
`sub_directions` 实例）。这步需要策略 lead 拍板，见 `docs/04 Step 3`。

### A 家族（有完整账号数据）

| 飞书列名 | 字段类型 | mapping 映射 | 去向 |
|---|---|---|---|
| 帐号昵称 | 文本 | `帐号昵称: _account_name` | raw_extra（未来扩到 accounts 表） |
| 粉丝数 | 数字 | `粉丝数: _account_followers` | raw_extra（未来扩到 account_snapshots） |
| 数据回收情况 | 单选 | `数据回收情况: data_quality_status` | `notes.data_quality_status` |

> A 家族的 `曝光数/阅读数/互动数` 命名是历史叫法。**新项目统一用 B 家族的
> `曝光量/阅读量/互动量`**，除非你有历史表必须沿用。无论用哪套，yaml 左边
> 跟着填一样的即可。

### 通用可选

| 飞书列名 | 字段类型 | 用途 |
|---|---|---|
| 话题标签 | 多选 | `notes.hashtags` (TEXT[]) |
| 涉及合规 | 复选框 | `notes.has_compliance_issue` |
| 合规备注 | 多行文本 | `notes.compliance_notes` |
| 评论数 | 数字 | NRT_phase3 用 `评论数: _comment_count` |

---

## lineage 元数据列（autowriter "AI 写 → 人工审 → 发布"流程才需要）

如果这张表会接收 autowriter 导出的内容，加这 6 列（下划线前缀，建议设隐藏字段
防误删）。否则 `v_model_comparison` / `v_prompt_performance` 长期为空：

| 飞书列名 | 字段类型 | 用途 |
|---|---|---|
| `_source_autowriter_project_id` | 文本 | 来源 autowriter 项目 UUID |
| `_source_autowriter_batch_id` | 文本 | 来源 batch UUID |
| `_source_autowriter_item_id` | 文本 | 来源 item UUID |
| `_source_autowriter_version_id` | 文本 | 采用的版本 UUID |
| `_ai_engine` | 文本 | 用了哪个 LLM |
| `_exported_at` | 日期 | 导出时间 |

> ⚠️ **关键**：autowriter 导出的 Excel 的 lineage 在隐藏列 G-L，**只有"整表
> 导入"才会跟着进飞书**（飞书原生「数据导入」功能）。复制可见列粘贴 → 隐藏列
> 丢失 → lineage 断。详见 `docs/09-system-integration.md` 的 lineage 段。

---

## 字段类型怎么选（别图省事全用文本）

sync 脚本按字段类型走不同解析路径，选错类型会让数据切错：

- **单选 / 多选**：飞书 API 返回 `list[dict{text: ...}]`，脚本能精确解析。
  `状态`、`发布笔记`、`数据回收情况` **必须单选**。
- **数字**：飞书返回 int/float，干净。`曝光量/阅读量/互动量/粉丝数` 用数字。
  （脚本的 `parse_numeric` 能兜底 `"1,234"` / 全角数字，但能用数字类型就别用文本。）
- **日期**：飞书返回毫秒时间戳，脚本 `parse_feishu_date` 转 ISO。`发布时间` 用日期。
- **文本 / 多行文本**：返回 str。`关键词` 这类多值字段如果用文本，脚本
  `parse_array` 按 `, 、 / ， 换行` 切分 —— 所以 `"营养液, 全营养"` 切得对，
  但 **`"营养液 全营养"`（空格分隔）会被当成一个词**。多值字段优先用多选，
  或用明确分隔符。

---

## 视图设置

至少建 2 个视图：

| 视图名 | 用途 | 过滤 |
|---|---|---|
| 默认全表 | sync 脚本读取 | **无过滤** |
| 待审核 | 运营日常 | 状态 ∈ {评估中, 风控} |

> `sync_config.feishu_view_id` 填**默认全表**视图的 ID，**不要填带过滤的**，
> 否则会漏数据。留空也行（不传 view_id = 读全表）。

---

## 实操 7 步

### 1. 建表
飞书 → 工作台 → 多维表格 → 新建。命名建议 `<品牌>_<phase>_seeding`
（例 `Nucare_phase1_seeding`）。

### 2. 加列
照上面的表逐列加，**注意字段类型**（单选/多选/数字/日期/文本，建后别随便改 ——
飞书允许改但已有数据会出意外行为）。

### 3. 配单选选项
`状态`、`发布笔记`、`数据回收情况` 加选项，**文本和 mapping yaml 一字不差**。

### 4. 拿 app_token + table_id
浏览器打开这张表，URL 长这样：
```
https://xxx.feishu.cn/base/bascnXXXXXXXX?table=tblYYYYYYYY&view=vewZZZZZZZZ
```
- `app_token` = `bascnXXXXXXXX`（`base/` 后面那串）
- `table_id` = `tblYYYYYYYY`（`table=` 后面）
- `view_id` = `vewZZZZZZZZ`（`view=` 后面，可选）

### 5. 建飞书应用 + 授权访问这张表
1. 飞书开放平台 (open.feishu.cn) → 创建企业自建应用 → 拿 `App ID` + `App Secret`
   （填进 GitHub Secrets 的 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`）
2. 应用 → 权限管理 → 加**多维表格读权限**（`bitable:app:readonly` 或 `bitable:app`）
3. **把应用加为这张表的协作者**：多维表格 → 右上角共享 → 添加协作者 → 搜应用名
   → 加进去（这步漏了会 401，光有权限不够，还要被表"邀请"）
4. 应用要**发布版本**（开放平台 → 版本管理 → 创建版本 → 申请上线），权限才生效

### 6. 填回 mapping yaml
```yaml
sync_config:
  source_type: feishu_api
  feishu_app_token: bascnXXXXXXXX
  feishu_table_id: tblYYYYYYYY
  feishu_view_id: vewZZZZZZZZ      # 可选，留空读全表
  sync_interval: on_demand
```

### 7. dry-run 测
```bash
cd scripts
python sync_feishu_notes_to_truth_vault.py <项目名> --dry-run --limit 5
```
看 stats（`upserted` / `quarantined` / `errors`）合理就实跑（去掉 `--dry-run`）。
`quarantined` 高 → 多半是列名和 yaml 对不上，回 Step 2 核对。

---

## 容易踩的坑（已和当前代码核对）

1. **「文案」空行**：D-021 quarantine 会拦空 `raw_content` 行。飞书表里大量空白行
   会刷屏告警 → 建表后加一个隐藏视图过滤掉空白行，或 sync 前清空行。
2. **单选误建成文本**：`状态` 一旦从单选改文本，飞书 API 返回从
   `[{text:"爆贴"}]` 变 `"爆贴"`。`extract_tier` 是 contains 还能匹配，但别的
   单选字段未必。建表初期最容易踩，**一开始就选对类型**。
3. **「关键词」空格分隔**：用文本字段时 `parse_array` 不按空格切。
   `"营养液 全营养"` → 一个词。用多选字段，或逗号/顿号分隔。
4. **复制别的飞书表**：飞书"复制多维表格"生成**新的** app_token + table_id +
   view_id，老 mapping 的这些值全失效。复制后必须重填 sync_config。
5. **应用没发布版本 / 没加协作者**：拿了 App ID/Secret 但 sync 报 401 →
   99% 是 Step 5 的"加协作者"或"发布版本"漏了。
6. **列名和 yaml 对不上**：最常见。数据进 quarantine 不报错但不入 notes 表。
   永远以 `mappings/<项目>.yaml` 的 `field_mapping` 左边为准。

---

## 附：当前 3 个项目的真实列清单（照抄即可）

NUC_phase1 / NRT_phase2 / NRT_phase3 共用这套 B 家族列（NRT_phase3 多一列 `评论数`）：

```
素人编号        (文本)      → account_id
发布时间        (日期)      → publish_time
发布笔记        (单选)      → _intent_raw    [选项: 流量帖/钓鱼帖/直给笔记]
方向            (单选/文本)  → _direction_raw [取值在 yaml direction_decomposition 拆解]
关键词          (多选)      → target_blue_keywords
反馈链接        (URL)       → publish_url
文案            (多行文本)   → raw_content    [必填]
状态            (单选)      → _status_raw     [选项: 大爆/爆贴预备/爆贴/风控/无水花/评估中]
曝光量          (数字)      → impressions
阅读量          (数字)      → reads
互动量          (数字)      → interactions
蓝词记录        (多选)      → hit_blue_keywords
爆帖置顶评论    (多行文本)   → pinned_comment
随贴评论        (多行文本)   → _comment_text
随贴评论素人    (多行文本)   → _comment_text_persona
评论数          (数字)      → _comment_count  [仅 NRT_phase3]
```

> 新项目如果业务字段一样，直接照这套建 + 复制一份 NUC_phase1.yaml 改
> `project_id` / `brand` / `direction_decomposition`。业务字段不同就按
> 「第一原则」自定义，记得 field_mapping 跟着改。
