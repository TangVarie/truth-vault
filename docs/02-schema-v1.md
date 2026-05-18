# 02 · Schema v1 数据库设计

## 为什么存在

这个文档定义 Truth Vault 数据库的字段级 schema。基于 [01-architecture.md](01-architecture.md) 的三层架构，将抽象设计落到具体的数据库表和字段。

> 任何字段调整必须更新本文档版本号并记录原因。

**Schema 版本**: v1.0  
**最后更新**: 2026-05-18

---

## 表清单

Truth Vault v1 包含 4 张表：

| 表名 | 用途 | 行数预估（启动期） |
|---|---|---|
| `projects` | 项目元数据（每个投放项目一行） | ~10 |
| `notes` | 笔记主表（每条已发布笔记一行） | ~3,400 |
| `comments` | 评论表（控评 + 素人评论） | ~2,700 |
| `notes_archive` | 文案语料库（无 tier 标签的笔记） | ~400（QSHG_1） |

辅助表（阶段 2 启用）：

| 表名 | 启用阶段 |
|---|---|
| `note_features` | 阶段 1 末期（结构化特征抽取） |
| `ml_models` | 阶段 2 |
| `predictions` | 阶段 2 |
| `experiments` | 阶段 4 |

---

## projects 表

```sql
CREATE TABLE projects (
    project_id TEXT PRIMARY KEY,           -- 'NUC_phase1', 'RIO_phase2' 形式
    brand TEXT NOT NULL,                   -- '大象集团', '锐澳', '力克雷'
    product TEXT NOT NULL,                 -- 'Nucare 全营养液体'
    category TEXT NOT NULL,                -- '保健品', '处方药', '美妆', '酒类'…
    platform TEXT NOT NULL,                -- 'xiaohongshu', 'douyin'…
    
    start_date DATE,
    end_date DATE,
    
    -- onboarding 配置（从 mappings/<project>.yaml 加载）
    mapping_config JSONB,                  -- 完整的 mapping.yaml 内容
    
    -- 项目级别的 tier 阈值（每个项目独立设定）
    tier_thresholds JSONB,                 -- {"爆": 100, "大爆": 1000}
    
    -- 数据健康度元数据
    total_notes INT DEFAULT 0,
    notes_with_data INT DEFAULT 0,
    notes_with_tier INT DEFAULT 0,
    last_sync_at TIMESTAMP,
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

**字段说明**:

- `mapping_config` 是这个项目的飞书表 → 数据库字段映射配置，全文存为 JSONB。每次 sync 时读取这个字段做翻译。详见 [03-mapping-protocol.md](03-mapping-protocol.md)。
- `tier_thresholds` 项目级别的爆/大爆阈值，不同项目不同（取决于该项目历史数据分布）。

---

## notes 表（核心表）

这是整个系统的核心表。三层架构（Surface / Essence / Audience）的字段全部在这张表里。

```sql
CREATE TABLE notes (
    -- ── 标识 ──
    note_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    
    -- ═══════════════════════════════════════
    -- Layer 1 · SURFACE 层
    -- ═══════════════════════════════════════
    
    -- 原始文案
    title TEXT,                            -- 解析后的标题
    body TEXT,                             -- 解析后的正文
    hashtags TEXT[],                       -- 话题标签数组
    raw_content TEXT,                      -- 原始「文案」字段，未解析
    
    -- 内容形式（受控词表）
    intent TEXT CHECK (intent IN ('traffic', 'conversion', 'educational', 'mixed', 'other')),
    content_format TEXT,                   -- 见 05-controlled-vocab.md
    
    -- ═══════════════════════════════════════
    -- Layer 2 · ESSENCE 层（必填，但允许 onboarding 时延迟标注）
    -- ═══════════════════════════════════════
    
    emotional_lever TEXT,                  -- 主情绪杠杆，受控词表
    emotional_valence TEXT CHECK (emotional_valence IN ('positive', 'negative', 'neutral')),
    emotional_intensity TEXT CHECK (emotional_intensity IN ('low', 'medium', 'high')),
    human_truth_archetype TEXT[],          -- 人性原型，允许 1-2 个
    trend_dependencies TEXT[],             -- 时效依赖标签
    
    -- ═══════════════════════════════════════
    -- Layer 3 · AUDIENCE 层
    -- ═══════════════════════════════════════
    
    target_audience TEXT[],                -- 目标受众（onboarding 时定义）
    inferred_audience_profile JSONB,       -- LLM 推断的完整画像
    actual_audience_data JSONB,            -- 蒲公英后台真实数据
    
    -- 项目专属维度（从「方向」字段拆解）
    user_pain_point TEXT,                  -- 项目专属，自由文本
    product_focus TEXT,                    -- 产品形式（如 NRT 的"咀嚼胶/喷雾"）
    
    -- ═══════════════════════════════════════
    -- 投放元数据
    -- ═══════════════════════════════════════
    
    account_name TEXT,
    account_followers INT,                 -- B 家族历史数据需要补录
    publish_time TIMESTAMP,
    publish_url TEXT,
    target_blue_keywords TEXT[],           -- 投放时的目标蓝词
    
    -- ═══════════════════════════════════════
    -- 数据回收（可为 null，TGV_1 / QSHG_1 没有这些）
    -- ═══════════════════════════════════════
    
    impressions INT,                       -- 曝光
    reads INT,                             -- 阅读
    interactions INT,                      -- 互动
    hit_blue_keywords TEXT[],              -- 实际命中蓝词
    
    -- 衍生数值（自动计算）
    read_rate FLOAT GENERATED ALWAYS AS (
        CASE WHEN impressions > 0 THEN reads::FLOAT / impressions ELSE NULL END
    ) STORED,
    interaction_rate FLOAT GENERATED ALWAYS AS (
        CASE WHEN reads > 0 THEN interactions::FLOAT / reads ELSE NULL END
    ) STORED,
    
    -- ═══════════════════════════════════════
    -- 人工标签（金标准）
    -- ═══════════════════════════════════════
    
    tier TEXT CHECK (tier IN ('趴', '预备', '爆', '大爆', '风控', '删除', '未知')),
    tier_source TEXT CHECK (tier_source IN ('状态字段', '备注字段', '数值推断', '人工补录', '未标注')),
    data_quality_status TEXT,              -- 「数据回收情况」: 最终回收/回收失败/无回收
    
    -- ═══════════════════════════════════════
    -- 控评/合规
    -- ═══════════════════════════════════════
    
    pinned_comment TEXT,                   -- 「爆帖置顶评论」
    has_compliance_issue BOOLEAN DEFAULT FALSE,
    compliance_notes TEXT,
    
    -- ═══════════════════════════════════════
    -- 标注元数据（重要：将来调整词表时不污染老数据）
    -- ═══════════════════════════════════════
    
    essence_annotated_by TEXT,             -- 'claude-sonnet-4' / 'human' / 'pending'
    essence_annotated_at TIMESTAMP,
    essence_vocab_version TEXT,            -- 'v0.1' / 'v0.2'… 词表版本快照
    
    audience_inferred_at TIMESTAMP,
    audience_actual_synced_at TIMESTAMP,
    
    -- ═══════════════════════════════════════
    -- 元数据
    -- ═══════════════════════════════════════
    
    raw_extra JSONB,                       -- 项目专属字段全进这里（不丢数据）
    
    -- 时间分桶（方便查询）
    era_tag TEXT,                          -- '2025Q4', '2026Q1' 形式
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 索引
CREATE INDEX idx_notes_project ON notes(project_id);
CREATE INDEX idx_notes_publish_time ON notes(publish_time);
CREATE INDEX idx_notes_tier ON notes(tier);
CREATE INDEX idx_notes_intent ON notes(intent);
CREATE INDEX idx_notes_content_format ON notes(content_format);
CREATE INDEX idx_notes_essence_lever ON notes(emotional_lever);
CREATE INDEX idx_notes_era ON notes(era_tag);

-- GIN 索引用于数组字段
CREATE INDEX idx_notes_audience ON notes USING GIN(target_audience);
CREATE INDEX idx_notes_archetype ON notes USING GIN(human_truth_archetype);
CREATE INDEX idx_notes_hashtags ON notes USING GIN(hashtags);
CREATE INDEX idx_notes_blue_kw ON notes USING GIN(target_blue_keywords);
```

---

## comments 表

控评 / 素人评论独立成表 —— 这是一个被低估的资产，约 2,700 条样本。

```sql
CREATE TABLE comments (
    comment_id TEXT PRIMARY KEY,
    note_id TEXT NOT NULL REFERENCES notes(note_id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    
    content TEXT NOT NULL,
    comment_type TEXT CHECK (comment_type IN ('贴主评论', '素人评论', '控评植入', '其他')),
    
    is_displayed BOOLEAN,                  -- 是否真实显示出来（「评论状态」推断）
    is_pinned BOOLEAN DEFAULT FALSE,       -- 是否置顶（pinned_comment 的来源）
    
    contains_blue_keyword BOOLEAN,
    blue_keywords_matched TEXT[],
    
    -- 关联到主笔记的 essence/audience 层（继承）
    -- 不冗余存储，需要时 JOIN notes 即可
    
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_comments_note ON comments(note_id);
CREATE INDEX idx_comments_project ON comments(project_id);
```

---

## notes_archive 表

QSHG_1 这种**只有文案、没有 tier 标签、没有数值数据**的项目，进 archive 表。这些数据：
- 不参与训练（缺 label）
- 可作为 embedding 语料库（阶段 3 用于扩大召回）
- 可作为半监督学习的未标注负样本（阶段 3+）

```sql
CREATE TABLE notes_archive (
    archive_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    
    raw_content TEXT NOT NULL,
    title TEXT,
    body TEXT,
    
    intent TEXT,                           -- 如果有「发布笔记」字段可推断
    publish_time TIMESTAMP,
    
    raw_extra JSONB,
    
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## note_features 表（阶段 1 末期启用）

结构化特征抽取的产出 —— 由 LLM worker 异步填充。和 notes 表分离的目的是允许特征独立 retrain（更新特征定义时不影响主表）。

```sql
CREATE TABLE note_features (
    note_id TEXT PRIMARY KEY REFERENCES notes(note_id) ON DELETE CASCADE,
    
    -- ── 词法特征（代码计算）──
    title_len INT,
    body_len INT,
    hashtag_count INT,
    mention_count INT,                     -- 品牌词在文案中出现次数
    mention_position_first INT,            -- 品牌词首次出现位置（字符数）
    has_number_in_title BOOLEAN,
    has_emoji_in_title BOOLEAN,
    has_question_in_title BOOLEAN,
    
    -- ── LLM 抽取（闭集分类）──
    opener_type TEXT,                      -- 场景描写/物件描写/疑问/感叹/直接陈述/对话
    title_hook_type TEXT,                  -- 反差/数字/疑问/痛点/反问/陈述
    has_specific_scene BOOLEAN,
    has_dialogue BOOLEAN,
    has_self_deprecation BOOLEAN,
    
    -- ── 风险信号 ──
    compliance_red_flags TEXT[],           -- 触犯哪些品类红线
    ai_smell_score INT,                    -- 0-100，越高越像 AI 写
    
    -- ── 元数据 ──
    extracted_at TIMESTAMP,
    extractor_version TEXT
);
```

---

## tier 字段的多源协议

`tier_source` 字段记录这个 tier 是怎么来的，置信度不同：

| tier_source | 来源 | 置信度 | 备注 |
|---|---|---|---|
| `状态字段` | A/B 家族「状态」列含"爆贴"/"大爆" | **高** | 人工标注，运营审慎 |
| `备注字段` | C 家族「备注」列含"新爆" | **高** | 人工标注，运营审慎 |
| `数值推断` | 按项目 tier_thresholds 互动数自动归类 | **中** | 启动期临时使用 |
| `人工补录` | onboarding 后人工 review 补录 | **高** | |
| `未标注` | 完全没标，进 archive | **N/A** | |

**训练时按 tier_source 加权** —— 数值推断的置信度低，应该降权。

---

## raw_extra 字段的用法

`raw_extra` JSONB 字段是"逃生舱" —— 飞书表里没被映射到标准字段的所有列原样存进去。这意味着：

- 数据永远不会丢
- 即使当时没识别出某字段的价值，将来发现有用可以回头分析
- 项目专属字段（NRT 的"父记录 2/3/4"、"临时-评论修改对比"等）全部在这里

示例：

```json
{
  "口碑通是否发起授权": "是-0317",
  "客户反馈": "罐装",
  "客户状态筛选": null,
  "巡查状态": "正常",
  "最近检查时间": "2026-04-30 14:10:45",
  "项目阶段": null,
  "理论金额结算": "0"
}
```

---

## era_tag 字段（时间分桶）

`era_tag` 字段是时间衰减计算的基础。格式："`YYYY Q[1-4]`"。

```sql
-- 自动填充 era_tag（触发器）
CREATE OR REPLACE FUNCTION fill_era_tag() RETURNS TRIGGER AS $$
BEGIN
    NEW.era_tag := EXTRACT(YEAR FROM NEW.publish_time)::TEXT 
                   || ' Q' 
                   || EXTRACT(QUARTER FROM NEW.publish_time)::TEXT;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER notes_set_era 
BEFORE INSERT OR UPDATE OF publish_time ON notes
FOR EACH ROW EXECUTE FUNCTION fill_era_tag();
```

季度颗粒度的选择是平衡：
- 太粗（年）：surface 层时间衰减计算不准
- 太细（月）：样本量不足，统计噪声大

---

## Schema 演化协议

Schema 升级时遵守：

1. **永远不删字段** —— 改为 deprecated，新字段并存
2. **永远不改字段类型** —— 加新字段做转换，老字段保留
3. **每次升级写 migration**：`schemas/migrations/v1_to_v1.1.sql`
4. **版本号字段记录**：所有标注层（`essence_vocab_version`）都记录当时的词表版本

这样 6 个月后回头看，能完整重现当时的标注上下文。

---

## 字段是否必填的总览

| 字段 | 必填 | 说明 |
|---|---|---|
| note_id, project_id | ✅ | |
| title, body | ✅ | 至少有一个非空 |
| raw_content | ✅ | 永远存原始数据 |
| intent | ✅ | 默认 'other'，onboarding 后补准 |
| publish_time | ✅ | |
| publish_url | ✅ | 唯一定位笔记 |
| impressions / reads / interactions | ⬜ | C 家族允许 null |
| tier | ⬜ | 但有就必须有 tier_source |
| target_audience | ✅ | onboarding 时定义，至少 1 个值 |
| emotional_lever | ⬜ | 标注后填充 |
| account_followers | ⬜ | A 家族有，B 家族要补录 |
| raw_extra | ⬜ | 但强烈建议填，永远别丢数据 |

---

## 可执行 SQL

完整的可执行 DDL 见 [../schemas/notes_v1.sql](../schemas/notes_v1.sql) —— 包含建表 + 索引 + 触发器，可以直接在 Supabase SQL Editor 里跑。

---

## 下一步

读完这个文档，建议接着读：

1. [03-mapping-protocol.md](03-mapping-protocol.md) —— 飞书表怎么映射到这个 schema
2. [05-controlled-vocab.md](05-controlled-vocab.md) —— enum 字段的受控词表
3. [04-onboarding-sop.md](04-onboarding-sop.md) —— 新项目接入这个 schema 的流程
