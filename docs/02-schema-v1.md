# 02 · Schema v1.2 数据库设计

## 为什么存在

定义 Truth Vault 数据库的字段级 schema。基于 [01-architecture.md](01-architecture.md) 的三层架构 + [09-system-integration.md](09-system-integration.md) 的四层系统架构，落到具体的数据库表和字段。

**Schema 版本**: v1.2
**最后更新**: 2026-05-19（Session #7 后落档）
**v1.1 → v1.2 升级**: 见文末。简言之：Session #7 代码审查发现 sanshengliubu / autowriter 已有完整过程数据表，v1.1 设计的 D-016 4 张表与之严重重叠。v1.2 按 D-024 / D-025 删 3 张冗余表，简化 prepublish_evaluations，改用跨系统 FK 引用。

> 任何字段调整必须更新本文档版本号并记录原因。canonical SQL 是 [`schemas/notes_v1_2.sql`](../schemas/notes_v1_2.sql)，本文档与之冲突时以 SQL 为准。

---

## 表清单 · v1.2 全景

```
┌─ 项目和方向元数据 ────────────────────┐
│  projects (含跨系统映射字段)          │
└──────────────────────────────────────┘
                  │
┌─ 评审校准 (D-025 简化) ───────────────┐
│  prepublish_evaluations               │  ← 仅保留 evaluator 准确率追踪
└──────────────────────────────────────┘  ← 不再存内容/版本/run（在 ssll/aw 已有表）
                                           
┌─ 账号 (D-020) ────────────────────────┐
│  accounts                            │
│  account_snapshots                   │
└──────────────────────────────────────┘
            │
            ▼
┌─ 核心结果表 ──────────────────────────────────────────────────┐
│  notes (含三层架构: Surface + Essence + Audience)             │
│  + 跨系统 FK: source_sanshengliubu_output_id /                │
│             source_autowriter_item_id /                        │
│             source_autowriter_version_id  (D-025)             │
│  + 双通道 sync 追踪: synced_to_ssll_at / synced_to_aw_at      │
│                      synced_ssll_reference_sample_id /        │
│                      synced_autowriter_item_id   (P3 rename)  │
└──────────────────────────────────────────────────────────────┘
            │
            ├──→ comments (D-022 升级 · 楼层结构 + 角色 + 意图)
            ├──→ metric_snapshots (D-018 历史快照)
            ├──→ posthoc_analyses (D-017 复盘解释独立存)
            ├──→ audience_calibrations (LLM vs 蒲公英校准)
            ├──→ quality_review_decisions (D-013 sanity check)
            └──→ note_features (阶段 1 末期启用)

┌─ 治理 ────────────────────────────────┐
│  undeclared_fields_quarantine (D-021)│
│  notes_archive (QSHG_1 等无 tier)    │
└──────────────────────────────────────┘

┌─ 跨 schema views (D-025) ─────────────────────────────────────┐
│  v_prompt_performance       → JOIN public.outputs             │
│  v_model_comparison         → JOIN autowriter.versions        │
│  v_evaluator_calibration    → 仅本 schema                     │
│  v_flywheel_sync_status     → 仅本 schema                     │
└──────────────────────────────────────────────────────────────┘
```

### 行数预估（启动期）

| 表 | 用途 | 启动期行数 |
|---|---|---|
| `projects` | 项目元数据 | ~10 |
| `accounts` | 素人账号 | ~3,000（跨项目复用） |
| `notes` | 已发布笔记 | ~3,400 |
| `metric_snapshots` | 表现历史 | ~10,000-50,000 |
| `comments` | 评论 | ~2,700+ |
| `prepublish_evaluations` | evaluator 准确率追踪 | ~5,000-20,000（sync 时反推存入） |

被 v1.2 移出本 schema 的表（数据在现存系统）:
- `prompt_versions` → `public.outputs` (sanshengliubu)
- `generation_runs` → `public.pipeline_runs` (sanshengliubu) / `autowriter.batches`
- `content_candidates` → `autowriter.items` + `autowriter.versions`

---

## 一、生成过程数据 layer（v1.1 D-016 → v1.2 D-025 简化）

> **v1.2 重大变更**：v1.1 在本节定义了 4 张过程数据表（prompt_versions / generation_runs / content_candidates / prepublish_evaluations）。Session #7 代码审查发现这些数据在 sanshengliubu / autowriter 已有，重复造轮子。v1.2 按 [D-025](../DECISIONS.md#d-025) 删 3 张，简化第 4 张为校准用途。详见 [09-system-integration.md](09-system-integration.md)。

### 数据所有权（D-025 后）

| 数据 | 主表所有者 | Truth Vault 引用方式 |
|---|---|---|
| Prompt 内容 | `public.outputs` (sanshengliubu) | notes.source_sanshengliubu_output_id FK |
| Generation runs | `public.pipeline_runs` (ssll) / `autowriter.batches` | 通过 item / version 间接 FK |
| 候选内容（含淘汰） | `autowriter.items` + `autowriter.versions` | notes.source_autowriter_item_id / source_autowriter_version_id FK |
| 用户修改/反馈记录 | `autowriter.items.manual_edit_draft` / `autowriter.versions.feedback` | 通过 negative example 反向通道扫一次（D-027）|
| 评审决策 | `autowriter` 内的 `_select_best_drafts` 隐式记录 | 简化的 `prepublish_evaluations`（仅评 evaluator 准确率） |

跨 schema FK 通过共享 Supabase 实例实现（D-024），不设置 REFERENCES 约束（部署灵活性），由应用层 + view 保证一致性。

### prepublish_evaluations（D-025 简化版）

仅用于追踪 evaluator（persona / critic / human / model）准确率，不复制候选内容/版本/run。autowriter `_select_best_drafts` 的隐式评审在 sync 时反推存入此表。

```sql
CREATE TABLE truth_vault.prepublish_evaluations (
    evaluation_id TEXT PRIMARY KEY,
    autowriter_item_id UUID NOT NULL,  -- → autowriter.items.id (跨 schema，不设 REFERENCES)
    
    evaluator_type TEXT NOT NULL 
        CHECK (evaluator_type IN ('persona', 'critic', 'human', 'model', 'rule_based', 'autowriter_select_best')),
    evaluator_id TEXT,                  -- 'claude_judge_v3' / 'persona_v2' / 'gemini_critic' 等
    
    score_json JSONB,
    decision TEXT NOT NULL 
        CHECK (decision IN ('pass', 'revise', 'reject', 'publish')),
    reasoning TEXT,
    
    -- 后续从 truth_vault.notes.tier 反推 evaluator 准确率
    pred_tier_class TEXT,               -- 评审时预测的 tier 等级
    actual_tier TEXT,                   -- 实际 tier（事后填）
    was_correct BOOLEAN GENERATED ALWAYS AS (
        CASE 
            WHEN pred_tier_class IS NULL OR actual_tier IS NULL THEN NULL
            ELSE pred_tier_class = actual_tier 
        END
    ) STORED,
    
    created_at TIMESTAMP
);
```

**Calibration 查询**: 哪个 evaluator 的判断后来被数据证实
```sql
SELECT * FROM truth_vault.v_evaluator_calibration;
-- 返回: 各 evaluator 的 pass_pred_bao_rate vs reject_pred_bao_rate
```

---

## 二、accounts（D-020 新增）

帆谷素人编号跨表跨项目唯一，是金矿数据。

```sql
CREATE TABLE accounts (
    account_id TEXT PRIMARY KEY,      -- 帆谷素人编号
    platform TEXT DEFAULT 'xiaohongshu',
    owner_type TEXT DEFAULT '素人'    -- 默认素人，留 KOC/KOL 扩展位
        CHECK (owner_type IN ('素人', 'KOC', 'KOL', 'brand')),
    
    -- 衍生字段（从 notes 聚合）
    total_notes_count INT DEFAULT 0,
    bao_count INT DEFAULT 0,
    dabao_count INT DEFAULT 0,
    fengkong_count INT DEFAULT 0,
    deleted_count INT DEFAULT 0,
    personal_bao_rate FLOAT,
    
    first_seen_at TIMESTAMP,
    last_publish_at TIMESTAMP,
    account_memo TEXT,                -- 运营备注 (D-032: 原 notes_text，改名避免与 notes 表混淆)
    
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE TABLE account_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(account_id),
    snapshot_at TIMESTAMP NOT NULL,
    
    followers INT,                    -- 多数素人为 null（没粉丝数据）
    avg_reads_30d INT,
    avg_interactions_30d INT,
    median_interactions_recent_10 INT,
    
    account_health_status TEXT,
    source TEXT
);
```

**核心查询**: 跨项目高爆率素人识别
```sql
SELECT * FROM v_top_performing_accounts LIMIT 20;
```

这让模型训练时可以**分离账号能力和内容能力**——避免把"某素人天然能爆"误判成"某种内容能爆"。

---

## 三、notes（核心表 · v1.2 升级）

```sql
CREATE TABLE truth_vault.notes (
    -- ── 标识 ──
    note_id TEXT PRIMARY KEY,         -- 生成规则: {project_id}_{feishu_record_id}
    project_id TEXT NOT NULL REFERENCES truth_vault.projects(project_id),
    
    -- ── 账号关联 (D-020) ──
    account_id TEXT REFERENCES truth_vault.accounts(account_id),
    
    -- ── 跨系统来源 FK (D-025 替代 v1.1 的 source_candidate_id) ──
    -- 跨 schema FK，不设置 REFERENCES 约束，应用层 + view 保证一致性
    source_sanshengliubu_output_id UUID,  -- → public.outputs.id
    source_autowriter_item_id UUID,       -- → autowriter.items.id
    source_autowriter_version_id UUID,    -- → autowriter.versions.id
    
    -- ════════════════════════════════════
    -- Layer 1 · SURFACE
    -- ════════════════════════════════════
    title, body, hashtags, raw_content,
    intent, content_format,
    
    -- ════════════════════════════════════
    -- Layer 2 · ESSENCE
    -- ════════════════════════════════════
    emotional_lever, emotional_valence, emotional_intensity,
    human_truth_archetype TEXT[],
    trend_dependencies TEXT[],
    
    -- ════════════════════════════════════
    -- Layer 3 · AUDIENCE
    -- ════════════════════════════════════
    target_audience TEXT[],
    inferred_audience_profile JSONB,
    actual_audience_data JSONB,
    
    -- 项目专属
    user_pain_point TEXT,
    product_focus TEXT,
    direction_subtype TEXT,           -- D-014 LLM 子分类结果
    
    -- ── 投放元数据 ──
    publish_time TIMESTAMP,
    publish_url TEXT,
    target_blue_keywords TEXT[],
    
    -- ── 数据回收（最新值，历史进 metric_snapshots）──
    impressions INT, reads INT, interactions INT,
    hit_blue_keywords TEXT[],
    read_rate FLOAT (生成列),
    interaction_rate FLOAT (生成列),
    
    -- ── 人工标签 ──
    tier TEXT (含 '数据异常' 新值),
    tier_source TEXT,
    data_quality_status TEXT,
    data_quality_flags JSONB,         -- D-013 sanity check
    
    -- ── 控评/合规 ──
    pinned_comment TEXT,
    has_compliance_issue BOOLEAN,
    compliance_notes TEXT,
    
    -- ── 标注元数据 ──
    essence_annotated_by TEXT,
    essence_annotated_at TIMESTAMP,
    essence_vocab_version TEXT,
    essence_annotation_mode TEXT,     -- D-017: prediction_feature vs posthoc_explanation
    
    audience_inferred_at TIMESTAMP,
    audience_actual_synced_at TIMESTAMP,
    
    -- ── 双通道 sync 状态追踪 (D-024) ──
    synced_to_ssll_at TIMESTAMP,               -- 同步到 sanshengliubu.reference_samples 的时间
    synced_to_aw_at TIMESTAMP,                 -- 同步到 autowriter.items 的时间
    synced_ssll_reference_sample_id UUID,      -- sanshengliubu.reference_samples.id (synced)
    synced_autowriter_item_id UUID,            -- autowriter.items.id (synced; example_label='positive')
    -- 命名约定: source_* 表示"来源于"（追溯笔记原本来自哪个 item/version）
    --           synced_* 表示"反向回灌后生成的目标行 ID"（P3 重命名完成）
    
    -- ── 元数据 ──
    raw_extra JSONB,
    era_tag TEXT (自动填充),

    -- ── Ingest 追溯（sync 脚本写入）──
    feishu_record_id TEXT,                     -- 飞书 record_id; 同 project 下唯一, 用于反查
    platform TEXT NOT NULL DEFAULT 'xiaohongshu',  -- 平台标识, 未来支持非小红书时无需改 schema
    ingested_at TIMESTAMP DEFAULT NOW(),       -- 第一次 ingest 时间（区别于 created_at 可能在 UPSERT 后变更）
    
    created_at, updated_at
);
```

> ⚠️ **idempotency**：`feishu_record_id` 和 `note_id` 不冗余——`note_id` 是 `f"{project_id}_{feishu_record_id}"`，理论上能解析出 record_id，但飞书 record_id 长度不固定且可能含 `_`，单独存一列更稳妥。`sync_feishu_notes_to_truth_vault.py` 写入时填这 3 列；老库通过 `ALTER TABLE ADD COLUMN IF NOT EXISTS` 补齐。索引 `idx_tv_notes_feishu_record(project_id, feishu_record_id)` 支持 sync 脚本"是否已 ingest"的反查。

### note_id 生成规则（v1.1 修正，v1.2 沿用）

```python
note_id = f"{project_id}_{feishu_record_id}"
# 例: "NUC_phase1_rec123abc"
```

飞书 record_id 是飞书多维表格自动生成的全局唯一 ID。**不再用素人编号作为 note_id 一部分**——素人编号是 account_id，一个素人在同一项目可发多条笔记。

### essence_annotation_mode（D-017 关键字段）

```sql
essence_annotation_mode TEXT 
    CHECK (essence_annotation_mode IN ('prediction_feature', 'posthoc_explanation'))
```

- `prediction_feature`: LLM 标注时**严禁输入** tier / impressions / reads / interactions。用于模型训练特征。
- `posthoc_explanation`: 已知 tier 后分析。**禁止用于训练特征**。

主 essence 字段（emotional_lever / human_truth_archetype 等）应用 `prediction_feature` 模式标注。复盘解释独立进 `posthoc_analyses` 表。

---

## 四、metric_snapshots（D-018, P2 hardened · 审计 八）

```sql
CREATE TABLE truth_vault.metric_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    note_id TEXT REFERENCES truth_vault.notes(note_id) ON DELETE CASCADE,
    collected_at TIMESTAMP NOT NULL,
    
    -- ── 时间窗口标签（P2 新增）──
    window_label TEXT NOT NULL DEFAULT 'ad_hoc'
        CHECK (window_label IN ('2h','24h','72h','7d','14d','30d','final','ad_hoc')),
    hours_since_publish INT,            -- 冗余于 publish_time，但 publish_time 历史数据不可靠
    
    impressions, reads, interactions,
    likes, saves, shares, comments_count,
    
    hit_blue_keywords TEXT[],
    search_rank, keyword_rank,
    
    notes TEXT,                         -- 运营备注（"评估期满"等）
    source TEXT NOT NULL DEFAULT 'ad_hoc',
    -- 'manual' / 'feishu_import' / 'puyuan' / 'xhs_scraper' / 'ad_hoc'
    
    -- 防重复采集（P2 新增）
    UNIQUE (note_id, window_label, source)
);
```

**机会主义抓取**（不强制定时）：每次运营更新飞书数据时自动 snapshot 一份。`notes.impressions` 始终是最新值，snapshots 是历史归档。

**P2 八的两个新增**：
- `window_label`: 标记快照的时间窗（2h / 24h / 72h / 7d / 14d / 30d / final / ad_hoc）。`ad_hoc` 是不确定窗口的兜底值，历史数据没有窗口标记的全部归这里。如果定时采集开发了，新数据用具体窗口。
- `UNIQUE(note_id, window_label, source)`: 防止同一笔记同一窗口被同一来源重复采集——重采时要么 UPDATE 现有行（建议），要么先 DELETE 再 INSERT。三个 UNIQUE 字段都 NOT NULL DEFAULT，避开了 PG 把 NULL 视为不同值的陷阱。

不强制统一观察窗口——帆谷实际工作流是"项目结案后定 tier"，时间窗口不是核心 ([DECISIONS D-018](../DECISIONS.md))。但有了 window_label，未来想跑"24h 互动率 vs final tier"这种建模分析也不会被脏数据干扰。

---

## 五、posthoc_analyses（D-017 · 复盘独立存）

```sql
CREATE TABLE posthoc_analyses (
    analysis_id TEXT PRIMARY KEY,
    note_id TEXT REFERENCES notes(note_id),
    
    analysis_mode TEXT                -- 'success_pattern' / 'failure_pattern' / 'attribution' / 'counter_factual'
        CHECK (analysis_mode IN ('success_pattern', 'failure_pattern', 'attribution', 'counter_factual')),
    
    attribution_explanation TEXT,
    contributing_factors JSONB,
    counter_factual TEXT,
    
    analyzed_by TEXT,                 -- 'llm-with-tier-context' / 'human'
    analyzed_at TIMESTAMP
);
```

复盘字段（已知"这条爆了"后分析为什么）和训练特征分离。

---

## 六、comments（v1.1 升级 · D-022）

```sql
CREATE TABLE comments (
    comment_id TEXT PRIMARY KEY,
    note_id TEXT REFERENCES notes(note_id),
    project_id TEXT REFERENCES projects(project_id),
    
    content TEXT NOT NULL,
    
    -- D-022 新增: 楼层结构
    parent_comment_id TEXT REFERENCES comments(comment_id),
    comment_order INT,
    comment_time TIMESTAMP,
    
    -- D-022 新增: 角色和意图
    comment_role TEXT                 -- '贴主' / '素人' / '路人' / '运营' / '未知'
        CHECK (comment_role IN ('贴主', '素人', '路人', '运营', '未知')),
    is_scripted BOOLEAN,
    comment_intent TEXT,              -- 闭集: 补充信息 / 反驳质疑 / 蓝词植入 / 共鸣扩散 / 引导私信 / 其他
    
    comment_type TEXT,
    is_displayed BOOLEAN,
    is_pinned BOOLEAN,
    
    contains_blue_keyword BOOLEAN,
    blue_keywords_matched TEXT[],
    raw_extra JSONB,
    
    created_at TIMESTAMP
);
```

历史评论数据需要 LLM 重建楼层结构（飞书表"随贴评论"是文本块）。

---

## 七、治理表

### undeclared_fields_quarantine（D-021）

飞书 sync 遇到未声明字段时整行进 quarantine（不静默入库）：

```sql
CREATE TABLE undeclared_fields_quarantine (
    quarantine_id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(project_id),
    
    raw_row JSONB NOT NULL,
    undeclared_field_names TEXT[],
    
    status TEXT DEFAULT 'pending',    -- pending / reviewed / resolved / rejected
    review_decision TEXT,
    reviewed_by TEXT,
    reviewed_at TIMESTAMP,
    
    quarantined_at TIMESTAMP
);
```

### quality_review_decisions（D-013 配套）

```sql
CREATE TABLE quality_review_decisions (
    review_id TEXT PRIMARY KEY,
    note_id TEXT REFERENCES notes(note_id),
    
    flag_type TEXT,
    reviewer TEXT,
    decision TEXT,                    -- '真错标' / 'LLM错判' / '边界case' / '需复查'
    action_taken TEXT,
    notes TEXT,
    
    reviewed_at TIMESTAMP
);
```

### audience_calibrations（**注意表名统一**）

之前 docs/07-audience-data.md 用过 `calibration_records`，**统一为 `audience_calibrations`**。

```sql
CREATE TABLE audience_calibrations (
    calibration_id TEXT PRIMARY KEY,
    note_id TEXT REFERENCES notes(note_id),
    
    age_inferred, age_actual, age_match BOOLEAN,
    gender_inferred, gender_actual, gender_match BOOLEAN,
    city_inferred TEXT[], city_actual, city_match BOOLEAN,
    
    calibrated_at TIMESTAMP
);
```

---

## 关键 Views（飞轮反馈数据源）

> v1.2 重点变化：`v_prompt_performance` / `v_model_comparison` 从"查 truth_vault 自己的表"改成"跨 schema JOIN sanshengliubu / autowriter 的表"。前提是共享 Supabase 实例（D-024）。

### v_prompt_performance（跨 schema · D-025）

```sql
-- 把 sanshengliubu.outputs 和 truth_vault.notes 关联，反推 prompt 表现
JOIN public.outputs o ON ...
LEFT JOIN truth_vault.notes n ON n.source_sanshengliubu_output_id = o.id
```

返回每条 prompt 关联到的爆款数、bao_rate。完整定义见 `schemas/notes_v1_2.sql`。

### v_model_comparison（跨 schema · D-025）

```sql
-- 通过 autowriter.versions.ai_engine + truth_vault.notes.tier 反推 Claude vs Gemini 胜率
FROM autowriter.versions v
JOIN autowriter.items i ON v.item_id = i.id
JOIN truth_vault.notes n ON n.source_autowriter_version_id = v.id
WHERE v.ai_engine != 'truth_vault_sync'   -- 排除反向回灌的哨兵
```

### v_evaluator_calibration（D-013 + D-025）

各 evaluator 的 pass_pred_bao_rate vs reject_pred_bao_rate。仅本 schema。

### v_flywheel_sync_status（D-024 监控）

每个项目的爆款数、已 sync 到 sanshengliubu / autowriter 的数、待 sync 的数。

### v_top_performing_accounts（D-020）

跨项目高爆率素人识别。

### v_project_tier_summary / v_data_health

项目 tier 分布概览 + 每项目的数据完整度评分。

---

## v1.1 → v1.2 升级 Migration

> v1.0 → v1.1 历史 migration 见 [DECISIONS.md](../DECISIONS.md) 中的 D-016 / D-018 / D-020 / D-022 落档。

如果已经按 v1.1 部署，按以下顺序 migrate 到 v1.2（**注意：这会删除 3 张已存的过程数据表，先确认数据已迁移到 sanshengliubu / autowriter 或已废弃**）：

```sql
-- 1. notes 表替换 source_candidate_id 为 3 个跨系统 FK
ALTER TABLE truth_vault.notes
    ADD COLUMN IF NOT EXISTS source_sanshengliubu_output_id UUID,
    ADD COLUMN IF NOT EXISTS source_autowriter_item_id UUID,
    ADD COLUMN IF NOT EXISTS source_autowriter_version_id UUID;

-- (可选: 把旧 source_candidate_id 数据 backfill 到新字段后)
ALTER TABLE truth_vault.notes
    DROP CONSTRAINT IF EXISTS fk_notes_candidate,
    DROP COLUMN IF EXISTS source_candidate_id;

-- 2. notes 表新增双通道 sync 追踪字段（D-024 + P3 命名）
ALTER TABLE truth_vault.notes
    ADD COLUMN IF NOT EXISTS synced_to_ssll_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS synced_to_aw_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS synced_ssll_reference_sample_id UUID,
    ADD COLUMN IF NOT EXISTS synced_autowriter_item_id UUID;
-- 如果是从已 v1.1 部署升级，并且已经有旧的 ssll_reference_sample_id / aw_item_id 列，
-- 用 ALTER ... RENAME COLUMN 改名而不是 ADD 新列：
--   ALTER TABLE truth_vault.notes RENAME COLUMN ssll_reference_sample_id TO synced_ssll_reference_sample_id;
--   ALTER TABLE truth_vault.notes RENAME COLUMN aw_item_id TO synced_autowriter_item_id;

-- 3. projects 表新增跨系统映射字段（D-024）
ALTER TABLE truth_vault.projects
    ADD COLUMN IF NOT EXISTS mapping_to_autowriter_project_id UUID,
    ADD COLUMN IF NOT EXISTS mapping_to_sanshengliubu_project_id UUID;

-- 3.5. (Session #10) 删除从未被写入的项目级 sync 时间戳缓存列。
-- v_flywheel_sync_status view 改用 MAX(n.synced_to_*_at) 动态计算，
-- 不再依赖这两列。
ALTER TABLE truth_vault.projects
    DROP COLUMN IF EXISTS last_baokuan_sync_to_ssll_at,
    DROP COLUMN IF EXISTS last_baokuan_sync_to_aw_at;

-- 4. prepublish_evaluations 重建（简化版）
DROP TABLE IF EXISTS truth_vault.prepublish_evaluations CASCADE;
-- 然后按 schemas/notes_v1_2.sql 重新 CREATE，autowriter_item_id 替代 candidate_id

-- 5. 删除 3 张 D-016 冗余表（数据迁移到 ssll/aw 已完成的前提下）
DROP TABLE IF EXISTS truth_vault.content_candidates CASCADE;
DROP TABLE IF EXISTS truth_vault.generation_runs CASCADE;
DROP TABLE IF EXISTS truth_vault.prompt_versions CASCADE;

-- 6. 重建 view（替换为跨 schema 版本）
DROP VIEW IF EXISTS truth_vault.v_prompt_performance;
DROP VIEW IF EXISTS truth_vault.v_model_comparison;
-- 然后按 schemas/notes_v1_2.sql 末尾的 view 定义重建
```

完整 SQL 见 [../schemas/notes_v1_2.sql](../schemas/notes_v1_2.sql)。

---

## v1.1 → v1.2 变更总结

**删除的表（数据由现存系统承载）**:
- `prompt_versions` → 改由 `public.outputs` (sanshengliubu) 承载
- `generation_runs` → 改由 `public.pipeline_runs` (sanshengliubu) + `autowriter.batches` 承载
- `content_candidates` → 改由 `autowriter.items` + `autowriter.versions` 承载

**简化的表**:
- `prepublish_evaluations`: 删除内容字段，仅保留 evaluator_type / decision / pred vs actual tier 用于校准

**notes 表 FK 变化**:
- 删除: `source_candidate_id` (因 content_candidates 表已删)
- 新增: `source_sanshengliubu_output_id` / `source_autowriter_item_id` / `source_autowriter_version_id`（跨 schema FK，不设 REFERENCES 约束）

**notes 表新增 sync 字段**:
- `synced_to_ssll_at` / `synced_to_aw_at`: D-024 双通道 sync 时间戳
- `synced_ssll_reference_sample_id` / `synced_autowriter_item_id`: 反向回灌后生成的目标行 ID（P3 命名规范：synced_* 是回灌产物，区别于 source_* 是来源追溯）

**projects 表新增跨系统映射字段**:
- `mapping_to_autowriter_project_id` / `mapping_to_sanshengliubu_project_id`: 手动维护

> 注 (Session #10): 早期版本声明过 `projects.last_baokuan_sync_to_ssll_at` /
> `_to_aw_at` 缓存列，但没有任何 sync 脚本写入它们。已删除；
> `v_flywheel_sync_status` view 改用 `MAX(n.synced_to_*_at)` 从 notes 行级
> 时间戳动态聚合。

**Views 变化**:
- `v_prompt_performance` / `v_model_comparison`: 改为跨 schema JOIN
- 新增 `v_flywheel_sync_status`: 监控双通道 sync 完成度
- 新增 `v_evaluator_calibration`: 校准 evaluator 准确率

**集成模式变化（详见 09-system-integration.md v2）**:
- v1.1: HTTP REST API（D-023，已作废）
- v1.2: 共享 Supabase + 双通道直接 INSERT（D-024）

---

## 下一步

读完这个文档，建议接着读：

1. [09-system-integration.md](09-system-integration.md) —— 这些表怎么被三省六部 / autowriter 使用
2. [05-controlled-vocab.md](05-controlled-vocab.md) —— enum 字段的受控词表
3. [../schemas/notes_v1_2.sql](../schemas/notes_v1_2.sql) —— 完整可执行 SQL
