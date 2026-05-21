# 09 · 系统集成架构 v2 · 双通道直接喂数据

## 为什么存在

这个文档是项目最重要的设计文档之一。它定义 **Truth Vault 与帆谷现存系统（三省六部、autowriter、写手网络）如何联动**，让三者形成真正的飞轮（不是孤立工具的拼盘）。

> 任何接手这个项目的人——新工程师、新分析师、半年后的你自己、新窗口的 Claude——必须先读这个文档，否则会把 Truth Vault 当成"另一个数据库"而错过它真正的价值。

**版本说明 · v1 → v2**: v1 设计 HTTP REST API 模式（D-023），v2 改为双通道直接喂数据模式（D-024 + D-025 + D-026 + D-027）。原因详见 [Session #7 代码审查纪录](#附录-为什么从-v1-改到-v2)。

---

## 核心定位声明（30 秒理解）

**Truth Vault 不是独立产品，是帆谷内容飞轮的数据骨架 + 跨系统枢纽。**

它做三件事：
1. **沉淀**已发布笔记的真实表现（tier / 互动 / essence / audience）
2. **回流**这些数据到 sanshengliubu 和 autowriter 的**已有高权重注入路径**（飞轮闭环）
3. **追溯**笔记的来源（哪个 prompt / 哪个 batch / 哪个 candidate）通过跨表 FK

> Truth Vault 不存生成过程数据（prompt 文本 / 候选内容 / 评审记录）——那些数据在 sanshengliubu / autowriter 已有的表里。Truth Vault 通过共享 Supabase + FK 跨表引用即可。

没有 Truth Vault，三个系统就是孤岛：
- sanshengliubu 不知道哪个 prompt 真的让内容爆了 → reference_samples 只能用外部爬的爆文
- autowriter 不知道 Claude 还是 Gemini 在某品类更准 → positive_examples 只能用 AI 自评
- 写手网络不知道自己的内容和历史爆款差在哪
- 你不知道某个 prompt 升级有没有效果

有 Truth Vault 之后，**飞轮闭环**：帆谷真实爆款 → 自动 sync 到两个系统的飞轮注入点 → 下一轮生产用上自己的真实成功案例。

---

## 帆谷现存系统全景（Session #7 代码审查后确认）

```
┌──────────────────────────────────────────────────────────┐
│ sanshengliubu (v0.30.10)                                  │
│ Prompt 生产管线 · Claude/DeepSeek/Gemini 三家             │
│                                                            │
│ 已有表: projects / pipeline_runs / stage_logs /            │
│         outputs / reference_samples                        │
│                                                            │
│ 已有飞轮: reference_samples (爆文证据包)                    │
│           ↓ retrieve_reference_packs                       │
│           ↓ 注入 vibe_rewriter (高权重)                    │
│                                                            │
│ ⭐ Truth Vault 注入点                                      │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│ autowriter (v2.7.9-studio)                                │
│ XHS 内容工作台 · Claude + Gemini 双引擎                    │
│                                                            │
│ 已有表: projects / batches / items / versions / memories  │
│                                                            │
│ 已有飞轮: items.example_label='positive'                    │
│           ↓ build_system_prompt(positive_examples=...)     │
│           ↓ 注入 system prompt (高权重)                    │
│                                                            │
│ ⭐ Truth Vault 注入点                                      │
└──────────────────────────────────────────────────────────┘
```

**两个项目目前是孤岛**：各自独立 Supabase，prompt 从 sanshengliubu → autowriter 是人工复制粘贴。Truth Vault 通过共享 Supabase + 双通道 sync 解决。

---

## 四层系统架构

Truth Vault 与现存系统形成四层架构。**任何对系统行为的描述都应该明确说在哪一层**：

```
┌─────────────────────────────────────────────────────────┐
│ Layer 4 · Optimization (优化层)                          │
│ 角色: 根据真实表现数据反推 prompt 方向应该如何调整         │
│ 实施者: 人类策略 lead (Ziao / 周哥) + Claude 协作          │
│ 输入: Truth Vault 内部 view (跨表 join)                   │
│ 输出: 新的 prompt 版本 (人工写入 sanshengliubu)            │
└─────────────────────────────────────────────────────────┘
                          ↑
┌─────────────────────────────────────────────────────────┐
│ Layer 3 · Persona / Critic / Human (决策层)              │
│ 角色: 对候选内容做最终内容判断 + 改写建议                  │
│ 实施者: sanshengliubu persona_simulator / vibe_critic /   │
│        autowriter _select_best_drafts / 写手 / 人类编辑    │
│ 输入: 候选内容 + Truth Vault 自动喂的 positive/reference   │
│ 输出: pass / revise / reject 决策                          │
└─────────────────────────────────────────────────────────┘
                          ↑
┌─────────────────────────────────────────────────────────┐
│ Layer 2 · Predictor / Evaluator (预测层)                 │
│ 角色: 输出结构化分数 (P(爆), 风险分)                       │
│ 实施者: LightGBM 模型 (D-012 按 intent 分轨, 阶段 2 启用) │
│ 输入: 候选内容 + Truth Vault Core 提供的 features         │
│ 输出: 结构化分数                                           │
└─────────────────────────────────────────────────────────┘
                          ↑
┌─────────────────────────────────────────────────────────┐
│ Layer 1 · Truth Vault Core (数据层 · "管家")              │
│ 角色: 存数据、查数据、算统计、出 anchor、sync 到两个通道   │
│ 实施者: Truth Vault Supabase schema + FastAPI 服务         │
│ 输入: 飞书 sync / 现存系统数据(跨表 read-only)             │
│ 输出: 双通道 sync 到 sanshengliubu / autowriter            │
│ 严格禁止: 不输出内容判断                                   │
└─────────────────────────────────────────────────────────┘
```

参见 [DECISIONS.md](../DECISIONS.md) D-019。

---

## 双通道集成架构 ⭐

这是 v2 的核心。Truth Vault 通过两个通道把爆款数据喂到现存系统**已有的高权重注入路径**：

```
              ┌─────────────────────────────┐
              │ Truth Vault notes (爆款)    │
              │ tier ∈ {爆, 大爆}            │
              └──────────┬──────────────────┘
                         │ 双向 sync
            ┌────────────┴────────────┐
            ▼                         ▼
┌──────────────────────┐  ┌──────────────────────┐
│ 通道 1               │  │ 通道 2               │
│ sanshengliubu.       │  │ autowriter.items     │
│ reference_samples    │  │ (example_label='+')  │
│                      │  │                      │
│ ↓ retrieve_reference_│  │ ↓ build_system_prompt│
│   packs              │  │   (positive_examples)│
│ ↓ 注入 vibe_rewriter │  │ ↓ 注入 system prompt │
│   (高权重)            │  │   (高权重)            │
└──────────────────────┘  └──────────────────────┘
        ▲                         ▲
        │                         │
   修改 1 个方法               P1 改造 (~190 行)
   (~30 行)                   (DDL 修复 + schema 迁移 + 含 lineage 元数据)
```

**核心原则**：
- ✅ Truth Vault 主动喂数据，不要求现存系统调用 Truth Vault
- ✅ 喂到的位置是现存系统**已有的、已被验证的**高权重注入路径
- ✅ 现存系统的修改量最小化（sanshengliubu 加 ~30 行；autowriter 一次性 P1 改造 ~190 行）

> **关于 "autowriter 零代码改动" 的更正**: v1 文档曾声称 autowriter 端零代码改动，仅复用 `example_label` 机制。Sprint 1.1 代码审查发现这个判断不准确——`list_example_items` 通过 `list_batches(limit=50)` 间接查，TV 写入的 special batch 会被滚出 50 个 batch 窗口；同时 autowriter 需要从 `public` schema 迁到 `autowriter` schema 以与 sanshengliubu 共存，迁移涉及 `get_client()` 改动；导出层还需要新增 lineage 元数据列以便 TV 反向归因。这些是一次性 P1 改造，完成后飞轮稳定运行，不会再有持续维护成本。详见 autowriter 仓库的 P1 commits 和 `migrations/RUNBOOK.md`。

---

## 通道 1 · Truth Vault → sanshengliubu.reference_samples

### 数据映射

⚠️ **Source of truth**:
1. sanshengliubu 的 `db/schema.sql` + `db/migrations/005_reference_samples_v2.sql`（"证据包" v2 列） — 定义合法列集
2. `scripts/sync_truth_vault_baokuan_to_sanshengliubu.py:build_reference_sample` — TV 端实际写的字段
3. 本表 — reader-friendly 视图，应该与 (1)(2) 一致

三者不一致时，CI 的 `sanshengliubu sync shape self-check` step 会失败。

⚠️ **v1 → v2 迁移背景**: ssll 早期（v0.10–v0.19）的 reference_samples 用 `title` / `content_text` / `analysis` / `image_url` / `tags` 这套 legacy 列。Migration 005（v0.20+）加入 v2"证据包"列 (`post_title` / `post_body` / `top_comments` / `platform` / `category` / `ai_analysis` / `quality_score`)，作为新的 canonical 来源。`vibe_rewriter` 在 `pipeline/retrieve_samples._shape_for_rewriter` 里**只读 v2 列**，所以 TV 写入必须填 v2 列（legacy `content_text` 仅作为镜像保留给老 reader）。

```
Truth Vault notes                  sanshengliubu.reference_samples (v2)
─────────────────────              ──────────────────────────────────────
raw_content[:80] (首行)            post_title    ★ vibe_rewriter 读
raw_content                        post_body     ★ vibe_rewriter 读
projects.platform → EN→ZH alias    platform      ★ vibe_rewriter 检索键
  ('xiaohongshu' → '小红书')                       (中文 display value; ssll
                                                   UI 与 list_reference_packs
                                                   过滤都用中文)
projects.category                  category      ★ vibe_rewriter 检索键
truth_vault.comments               top_comments  ★ vibe_rewriter 读
  ↓ 转换为 [{text, role, pinned}, ...]            (shape per 005 + reference_pack_analyzer 注释)
                                   ai_analysis   ★ vibe_rewriter 读
                                     见下方"内部聚合"
tier → 100/200                     quality_score (排序权重; 'unranked' 默认 0)
'pack'                             source_type   (ssll 用 `.eq("source_type","pack")`
                                                   过滤; TV 来源标识保留在
                                                   tags + source_truth_vault_note_id)
raw_content[:80] (首行)            title         (canonical 短标题; ssll 列表页用)
raw_content                        content_text  (legacy 镜像; pre-v2 reader 兼容)
['truth_vault_sync', tier]         tags          (TV-origin 标识在这里)
note_id                            source_truth_vault_note_id  ← 幂等键 (must-add: 001 patch)

ai_analysis (JSONB) 内部聚合:
  _truth_vault_note_id             幂等键的 JSON fallback (老 row 无 source_truth_vault_note_id)
  _truth_vault_project_id
  _truth_vault_tier                ('爆' / '大爆')
  _truth_vault_intent
  _truth_vault_quality_score       (与顶级 quality_score 一致，方便不读顶级列的下游)
  _truth_vault_brand               ssll 没有 brand 列, 嵌入这里
  _truth_vault_source_url          ssll 没有 source_url 列, 嵌入这里
  _truth_vault_target_audience     ssll 没有 target_audience 列, 嵌入这里
  _truth_vault_hit_blue_keywords   ssll 没有 hit_keywords 列, 嵌入这里
```

`top_comments` 的元素结构（与 ssll `reference_pack_analyzer.md` 一致）：
```jsonc
{ "text": "评论内容",   // 必填
  "role": "贴主/素人/路人/运营/未知",   // 来自 truth_vault.comments.comment_role
  "pinned": true }                      // 来自 truth_vault.comments.is_pinned
```
注：`likes` 字段在 ssll spec 里是可选 (`{text, likes?}`)，truth_vault.comments 不收集点赞数，所以 TV 注入的行 `likes` 缺省。如果未来 comments 加 likes 字段，同步更新 build_reference_sample。

ssll 重命名任一列时必须同步更新：(1) `sanshengliubu/db/schema.sql` 或 migration、(2) `build_reference_sample` 写列、(3) `preflight_check` 必填列列表、(4) 本表、(5) CI 的 ssll stub 与 shape self-check。任一不一致时 sync 启动会因 preflight 失败 / CI 红。

### sanshengliubu 需要的修改 (~30 行)

> 现实路径：sync 直接由 TV 仓库的 `scripts/sync_truth_vault_baokuan_to_sanshengliubu.py` 跨 schema INSERT 完成（共享 Supabase + service_role）。下方 `import_truth_vault_baokuan` 是给 sanshengliubu 自有 codebase 的可选 helper —— 用于内部 ssll 工具想读 / 重导 TV 数据时复用。**生产飞轮闭环不依赖这个 helper 存在**。

```python
# (可选) 在 sanshengliubu db/supabase_client.py 加 helper，便于 ssll 自身工具
# 读 TV 同步进来的数据时复用 quality_score / ai_analysis 计算逻辑。
# Shape 必须和 truth-vault/scripts/sync_truth_vault_baokuan_to_sanshengliubu.py
# 的 build_reference_sample() 完全一致 —— v2 "证据包" 列 (post_title /
# post_body / top_comments / ...), 不要重新发明列名。
def import_truth_vault_baokuan(self, note: dict) -> dict:
    """从 Truth Vault 导入爆款笔记到 reference_samples（helper, 可选）。
    note 来自 truth_vault.notes JOIN projects，含 top_comments 字段。
    """
    tier = note.get('tier')
    quality_score = {'爆': 100, '大爆': 200}.get(tier, 0)
    raw_content = note.get('raw_content') or ''
    synthetic_title = raw_content.split('\n', 1)[0][:80] or '未命名样本'

    # truth_vault.comments → ssll's [{text, role, pinned}] shape.
    top_comments = [
        {'text': c.get('content'),
         'role': c.get('comment_role'),
         'pinned': bool(c.get('is_pinned'))}
        for c in (note.get('top_comments') or [])
        if c.get('content')
    ]

    ai_analysis = {
        '_truth_vault_note_id': note['note_id'],
        '_truth_vault_project_id': note['project_id'],
        '_truth_vault_tier': tier,
        '_truth_vault_intent': note.get('intent'),
        '_truth_vault_quality_score': quality_score,
        # TV-side metadata that ssll's schema has no top-level home for.
        '_truth_vault_brand': note.get('brand'),
        '_truth_vault_source_url': note.get('publish_url'),
        '_truth_vault_target_audience': note.get('target_audience'),
        '_truth_vault_hit_blue_keywords': note.get('hit_blue_keywords') or [],
    }

    pack = {
        # v2 columns vibe_rewriter actually reads
        'post_title': synthetic_title,
        'post_body':  raw_content,
        'top_comments': top_comments,
        # sanshengliubu list_reference_packs 用中文精确过滤;
        # TV 写 EN canonical key 时必须 alias 为中文 display 值.
        'platform':   _PLATFORM_EN_TO_SSLL.get(
                          note.get('platform') or 'xiaohongshu',
                          '小红书',
                      ),
        'category':   note.get('category'),
        'ai_analysis': ai_analysis,
        # Other v2 canonical columns
        'title':       synthetic_title,
        # ssll 的 list_reference_packs `.eq("source_type","pack")` 过滤;
        # TV 来源 discriminator 落在 tags + source_truth_vault_note_id.
        'source_type': 'pack',
        'content_text': raw_content,  # legacy mirror
        'tags': ['truth_vault_sync'] + ([tier] if tier else []),
        'quality_score': quality_score,
        # Lineage / idempotency key (must-add: 001 patch)
        'source_truth_vault_note_id': note['note_id'],
    }
    return self.save_reference_pack(pack)
```

**必做前置**：reference_samples 表必须加 `source_truth_vault_note_id TEXT` 字段（**注意类型是 TEXT 不是 UUID**，因为 `truth_vault.notes.note_id` 是 TEXT，规则 `{project_id}_{feishu_record_id}`）。这一列是反向追溯键，TV sync 脚本会无条件写入它，sanshengliubu 的 `import_truth_vault_baokuan` 方法也无条件写入。SQL migration 在 `sanshengliubu-patches/001_add_source_tv_note_id.sql`，集成 patch 之前必须先跑。

### Sync 脚本 spec

**文件名**: `scripts/sync_truth_vault_baokuan_to_sanshengliubu.py`
**触发**: 定时任务（每天）或飞书新爆款 sync 后触发

```python
def sync_baokuan_to_sanshengliubu():
    # 1. 查 Truth Vault 中所有 tier ∈ ('爆','大爆') 且未 sync 到 sanshengliubu 的笔记
    # 注：sanshengliubu 留在 public schema（按 D-024），所以 FROM 用 public.reference_samples
    # 去重键优先 source_truth_vault_note_id（专门加的索引列，必做前置 migration 001），
    # 老 row 没填这列时 fallback 到 ai_analysis JSON 路径（OR 兜底）
    new_baokuan = query("""
        SELECT n.*, p.category
        FROM truth_vault.notes n
        JOIN truth_vault.projects p ON n.project_id = p.project_id
        WHERE n.tier IN ('爆', '大爆')
        AND NOT EXISTS (
            SELECT 1 FROM public.reference_samples r
            WHERE r.source_truth_vault_note_id = n.note_id
               OR r.ai_analysis->>'_truth_vault_note_id' = n.note_id  -- legacy fallback
        )
    """)
    
    # 2. 对每条爆款调用 import_truth_vault_baokuan
    for note in new_baokuan:
        # 拉 top comments
        note['top_comments'] = fetch_top_comments(note['note_id'], limit=5)
        ssll_client.import_truth_vault_baokuan(note)
        log_synced(note['note_id'])
    
    # 3. 报告
    print(f"Synced {len(new_baokuan)} 爆款 → public.reference_samples (sanshengliubu 所在)")
```

---

## 通道 2 · Truth Vault → autowriter.items (example_label='positive')

### 关键洞察

autowriter 的 `items.example_label='positive'` 已经有完整的注入机制：
- `db.set_item_example_label(item_id, 'positive')` 标记
- `db.list_example_items(label='positive')` 拉取
- `build_system_prompt(positive_examples=...)` 自动装配进 system prompt（高权重）

**在完成 P1 一次性改造后**（autowriter `list_example_items` 已绕开 50-batch 窗口、`items.external_source` 已加幂等键、schema 已迁到 autowriter），**Truth Vault 直接插入 `autowriter.items` 表，example_label='positive'**，复用 autowriter 既有的 `build_system_prompt(positive_examples=...)` 机制即可生效。下方"autowriter 的修改 · P1 一次性改造（非零代码）"段列出详细改动。

### 实施挑战 · 约定 batch_id / user_id / project_id

autowriter.items 有 NOT NULL 约束：
- `batch_id REFERENCES batches`  → 需要先建一个特殊 batch
- `user_id UUID NOT NULL`  → 需要约定一个 owner
- 通过 batch → project_id 关联到 autowriter.projects

**约定方案**：

```sql
-- 为每个 autowriter project 建一个 "truth_vault_synced" 特殊 batch
INSERT INTO autowriter.batches (id, project_id, tactic, params, ai_engines, user_id)
VALUES (
    '00000000-0000-0000-0000-{autowriter_project_id_suffix}',  -- 约定 ID
    '{autowriter_project_id}',
    'truth_vault_synced_baokuan',
    '{"_source": "truth_vault", "_managed": "automatic"}'::jsonb,
    '[]'::jsonb,  -- 不是 AI 生成的，没有 engine
    '{autowriter_project_owner_id}'
)
ON CONFLICT (id) DO NOTHING;
```

之后 sync 时把爆款笔记作为 items 插入这个 batch。**P1 Sprint 1.1 加了 `external_source` 字段做幂等去重**：

```sql
-- 1. 插 item 行（external_source 是幂等 key）
-- 注: PG 默认没有 uuid() 函数；autowriter schema 启用了 uuid-ossp 扩展，用 uuid_generate_v4()
INSERT INTO autowriter.items (
    id, batch_id, status, example_label,
    external_source, external_source_id,    -- P1 加的去重 key
    user_id, created_at
) VALUES (
    uuid_generate_v4(), {special_batch_id}, 'approved', 'positive',
    'truth_vault', {note.note_id},
    {tv_synced_user_id}, NOW()
)
ON CONFLICT (external_source, external_source_id)
WHERE external_source IS NOT NULL
DO NOTHING;  -- partial UNIQUE INDEX 保证重跑不重复插

-- 2. 插对应的 version 行（ai_engine='truth_vault_sync' 用于 v_model_comparison 排除）
INSERT INTO autowriter.versions (
    id, item_id, version_num, ai_engine, title, body, keywords,
    feedback, images, token_usage
) VALUES (
    uuid_generate_v4(), {item_id}, 1, 'truth_vault_sync',
    {note.title}, {note.body}, {note.hashtags},
    NULL, '[]'::jsonb, '{}'::jsonb
);

-- 3. 关联 best_version_id
UPDATE autowriter.items SET best_version_id = {version_id} WHERE id = {item_id};
```

> 上面是 SQL 思路示例；**实际通过 supabase-py 执行时**，UUID 推荐在 Python 端用 `uuid.uuid4()` 生成传入，避免数据库函数名差异；时间戳用 ISO 字符串（`datetime.utcnow().isoformat()`）或省略让 DB 默认值兜底，不要传字符串 `'now()'`（PostgREST 会把它当字面值字符串而不是 SQL 函数）。

⚠️ **跨 schema 写入注意**: TV sync 脚本是 truth-vault 仓库里的代码，不继承 autowriter 的 `ClientOptions(schema='autowriter')`。在 Python 里写入 autowriter 表必须显式：

```python
client.schema('autowriter').table('items').insert(...).execute()
client.schema('autowriter').table('versions').insert(...).execute()
```

而读 truth_vault 数据则用：

```python
client.schema('truth_vault').table('notes').select(...).execute()
```

不显式指定 schema 会写到 `public.items`（不存在），返回 404。

### ⚠️ TV sync 脚本必须用 SERVICE ROLE KEY

所有跨 schema sync 脚本（飞书→TV / TV→ssll / TV→aw / negative extraction）写入的目标表都启用了 RLS：

- `autowriter.projects/batches/items/versions/memories` 用 `auth.uid() = owner_id/user_id`
- `truth_vault.notes` 后续可能加 RLS（当前未启用，但要为之准备）

普通 `SUPABASE_ANON_KEY` 或经过用户登录的 `authenticated` client **无法**插入不属于自己的项目下的数据 —— RLS 会拦截。Sync 脚本是"系统级"操作，必须用 `SUPABASE_SERVICE_ROLE_KEY`：

```python
import os
from supabase import create_client

# 不要用 ANON_KEY；用 SERVICE_ROLE_KEY 绕过 RLS
client = create_client(
    os.environ['SUPABASE_URL'],
    os.environ['SUPABASE_SERVICE_ROLE_KEY'],  # ⭐ 不是 ANON_KEY
)
# 之后所有 client.schema(...).table(...).insert/update 都享有 RLS bypass
```

> 安全注意：`SERVICE_ROLE_KEY` 是管理员级权限，**绝不能**进前端 / 用户浏览器 / Streamlit 公开页面。只在 sync 脚本（后台 cron / GitHub Actions / 自建 worker）里用，存在服务端 env vars 或 GitHub Secrets 里。Repo 里的 `.env.example` 应该明确两种 key 的差异。

### autowriter 的修改 · P1 一次性改造（非零代码）

P1 Sprint 1.1 + 1.2 涉及的 autowriter 改动：

1. **`list_example_items` 重写**（db.py 约 25 行变更）—— 改用 PostgREST embedded inner join 绕开"最近 50 个 batch"窗口。TV 的 special batch 不再有掉出窗口的风险。
2. **`get_client()` 加默认 schema**（db.py 约 5 行 + 70 行 docstring 注释）—— `ClientOptions(schema='autowriter')`，让 36 个 `client.table(...)` 调用透明指向 `autowriter` schema。
3. **DDL 修复**（db.py 约 80 行）—— `ALTER TABLE items` 顺序修复、`CREATE POLICY IF NOT EXISTS` 改 EXCEPTION 模式、加 `external_source` 字段 + UNIQUE INDEX（用于 TV sync 去重）。
4. **exporter lineage**（exporter.py 约 85 行 + app.py 约 29 行）—— Excel 隐藏列 + Word 6pt 脚注携带 `source_autowriter_{project,batch,item,version}_id`，让 TV 从飞书回收时能反向定位。
5. **数据迁移**（一次性 SQL，5 行 ALTER）—— `public.{5 tables}` → `autowriter.{5 tables}`，自动迁移 policy / index / FK / grant。

完成后：
- `build_system_prompt(positive_examples=...)` 的现有逻辑会自动从 `list_example_items(label='positive')` 拉到 Truth Vault sync 的爆款（**且不会因为窗口滚动而丢失**），作为 positive_examples 注入 system prompt。
- TV 用 `external_source='truth_vault' + external_source_id=note_id` 做幂等去重，重跑 sync 不会重复插入。
- 飞书表里的爆款笔记带 lineage 元数据，TV 反向回收时可填 `truth_vault.notes.source_autowriter_*_id` FK。

### ⚠️ 真实工作流必须用 Excel 整表导入，不能只复制可见文案

exporter.py 把 lineage 写到 Excel 隐藏列 G-L，但**隐藏列只有"整表上传/导入"才会跟着进入飞书多维表格**。如果运营走以下流程，lineage 会丢失：

| 流程 | lineage 能否保留 | TV 反向追溯能力 |
|---|---|---|
| ✅ Excel 整表导入飞书多维表格（DataX / 飞书 OpenAPI / 复制全表） | 保留 | v_model_comparison / v_prompt_performance 有数据 |
| ❌ 选中可见单元格复制粘贴到飞书 | **丢失** | view 长期为空，模型胜率分析破产 |
| ❌ Word 文档手发给客户后客户手工录入 | **丢失** | 同上 |
| ⚠️ Feishu webhook 推送到群（仅通知） | N/A（不是数据 sync 路径） | webhook 不入多维表，本来就不在 lineage 闭环里 |

**强制工作流规则**（NUC_1 pilot 之后由策略 lead 落实到运营 SOP）：
1. 内容产出 → autowriter 导出 Excel → **整文件**上传到飞书多维表格的"数据导入"功能（飞书原生支持 .xlsx 导入，会一次性带所有列含隐藏列）
2. 在飞书多维表里把 G-L 这 6 列设为"隐藏字段"或"管理员可见"，避免运营误删
3. 字段命名保持 `_source_autowriter_project_id` 等下划线前缀，与飞书表里的业务字段区分
4. TV sync 从飞书回收时，按这 6 列填 `truth_vault.notes.source_autowriter_{project,batch,item,version}_id`

不走整表导入路径的客户/项目，TV `v_model_comparison` 和 `v_prompt_performance` 将持续为空——这是**架构层面的"运营纪律 = 数据资产"约束**，不是技术问题。运营 SOP 不变的话，autowriter exporter 加再多 lineage 列也没用。

### Sync 脚本 spec

**文件名**: `scripts/sync_truth_vault_baokuan_to_autowriter_items.py`
**触发**: 同 sanshengliubu sync

```python
def sync_baokuan_to_autowriter():
    # 1. 对每个 autowriter project，确保有 truth_vault_synced 特殊 batch
    autowriter_projects = autowriter_db.list_projects()
    for proj in autowriter_projects:
        ensure_truth_vault_batch_exists(proj['id'], proj['owner_id'])
    
    # 2. 查 Truth Vault 爆款（关联到 autowriter project）
    # 关联规则: Truth Vault projects 表手动维护 mapping_to_autowriter_project_id
    # 去重规则: autowriter.items.external_source_id 已存在 = 已 sync (P1 强幂等键)
    new_baokuan = query("""
        SELECT n.*, p.mapping_to_autowriter_project_id AS aw_project_id
        FROM truth_vault.notes n
        JOIN truth_vault.projects p ON n.project_id = p.project_id
        WHERE n.tier IN ('爆', '大爆')
        AND p.mapping_to_autowriter_project_id IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM autowriter.items i
            WHERE i.external_source = 'truth_vault'
            AND i.external_source_id = n.note_id
        )
    """)
    
    # 3. 对每条爆款插入 autowriter.items + versions
    #    所有 .table() 调用必须显式 .schema('autowriter') —— TV sync 不继承
    #    autowriter 的默认 schema 设置（autowriter 自己的 db.get_client() 才设）。
    for note in new_baokuan:
        item_id, version_id = create_truth_vault_synced_item(
            aw_client=aw_client,  # supabase client，跨 schema 写显式指定
            project_id=note['aw_project_id'],
            title=note['title'],
            body=note['body'],
            keywords=note.get('hashtags', []),
            external_source='truth_vault',
            external_source_id=note['note_id'],  # ⭐ 幂等 key
        )
        # set_item_example_label 也走 .schema('autowriter')
        aw_client.schema('autowriter').table('items').update(
            {'example_label': 'positive'}
        ).eq('id', item_id).execute()
        # 回写 TV.notes.synced_autowriter_item_id 用于反向追溯（P3 命名）
        # 时间戳: 用 Python 端的 ISO 字符串，不要传 'now()'（PostgREST 当字面值）
        tv_client.schema('truth_vault').table('notes').update({
            'synced_to_aw_at': datetime.utcnow().isoformat(),
            'synced_autowriter_item_id': item_id,
        }).eq('note_id', note['note_id']).execute()
        log_synced(note['note_id'], item_id)
    
    print(f"Synced {len(new_baokuan)} 爆款 → autowriter.items (example_label=positive)")
```

---

## 反向通道 · Negative example 信号回流 (D-027)

Truth Vault 不只是单向输出，也从 autowriter 收集 negative 信号。

> **P2 重要更正（Sprint 2）**: v1 的 spec 在三个来源上都有查询逻辑错误，配合 autowriter 的实际行为读会拿不到信号或拿到错误样本。下面是修正后的版本。autowriter 端额外加一列 `items.example_label_proposal`，让脚本只产 candidate 队列，由人工 review 后才落到 `example_label='negative'`，避免误判直接污染 negative pool。

### 前置：autowriter 加一列 `example_label_proposal`

```sql
ALTER TABLE autowriter.items ADD COLUMN IF NOT EXISTS example_label_proposal TEXT
    CHECK (example_label_proposal IN (
        'negative_manual_rewrite',  -- 来源 A: 用户手动重写过 AI 版
        'negative_feedback_iter',   -- 来源 B: 用户给 feedback 后 AI 重生成过
        'negative_batch_rejected'   -- 来源 C: 同 batch 有人通过，本 item 卡 needs_revision
    ));
```

这一列由 extract 脚本写，autowriter Memory Manager UI 读出展示给用户。用户在 UI 里点 "确认为负例" → `example_label='negative' + example_label_proposal=NULL`；点 "忽略" → `example_label_proposal=NULL` 不动 example_label。

### 信号来源 · autowriter 历史 items 的 3 个来源（P2 修正版）

**来源 A · 用户手动重写 AI 版**（原 spec 查 `manual_edit_draft` 是错的——那是临时草稿，保存后会 clear；真实历史信号在 versions 表里 `ai_engine='manual'`，**前一版**才是 negative candidate）:

```sql
-- 当一个 item 有 ai_engine='manual' 的 version，意味着用户重写过 AI 版。
-- 它的"前一版"（version_num < manual version 且 ai_engine 不是 manual）就是被替换的 AI 输出 = negative candidate。
SELECT 
    i.id AS item_id,
    v_ai.id AS rejected_version_id,
    v_ai.title AS rejected_title,
    v_ai.body AS rejected_body,
    v_manual.id AS replacement_version_id,
    v_manual.feedback AS replacement_note  -- 通常是 "手动精修"
FROM autowriter.items i
JOIN autowriter.versions v_manual 
    ON v_manual.item_id = i.id 
    AND v_manual.ai_engine = 'manual'
JOIN autowriter.versions v_ai 
    ON v_ai.item_id = i.id 
    AND v_ai.ai_engine != 'manual'
    AND v_ai.version_num < v_manual.version_num
-- 取该 item 上最接近 manual version 的那个 AI version
WHERE NOT EXISTS (
    SELECT 1 FROM autowriter.versions v_mid
    WHERE v_mid.item_id = i.id
    AND v_mid.ai_engine != 'manual'
    AND v_mid.version_num > v_ai.version_num
    AND v_mid.version_num < v_manual.version_num
);
```

**来源 B · 用户反馈触发的迭代**（原 spec 查 `v_original.feedback` 是错的——`create_version()` 把 feedback 写在**新版本**上，旧版本的 feedback 字段是 NULL；要反过来查）:

```sql
-- feedback 挂在 v_revised 上，v_original 是被这个 feedback 替换掉的旧 AI 版 = negative candidate。
-- 排除 ai_engine='manual' 的 revised，因为那是来源 A 的情况，避免重复计数。
SELECT 
    i.id AS item_id,
    v_original.id AS rejected_version_id,
    v_original.title AS rejected_title,
    v_original.body AS rejected_body,
    v_revised.feedback AS user_feedback,
    v_revised.id AS replacement_version_id
FROM autowriter.versions v_revised
JOIN autowriter.versions v_original 
    ON v_original.item_id = v_revised.item_id 
    AND v_original.version_num < v_revised.version_num
JOIN autowriter.items i ON i.id = v_revised.item_id
WHERE v_revised.feedback IS NOT NULL
  AND v_revised.feedback != '手动精修'  -- 排除来源 A
  AND v_revised.ai_engine != 'manual'
  -- 只取最接近的前一版
  AND NOT EXISTS (
      SELECT 1 FROM autowriter.versions v_mid
      WHERE v_mid.item_id = v_revised.item_id
      AND v_mid.version_num > v_original.version_num
      AND v_mid.version_num < v_revised.version_num
  );
```

**来源 C · 同 batch 部分通过部分卡住**（needs_revision 不等于淘汰——它可能只是还没改完。**这个来源最弱，建议只产 candidate，不直接打 negative**）:

```sql
-- 候选：同 batch 中至少有一个 approved item 的 needs_revision items
-- 注：approved 项是 batch 整体方向已被认可的证据，剩下还卡 needs_revision 的更可能是"被替代品"
-- 但仍可能只是用户暂未处理 → 必须人工 review
SELECT 
    b.id AS batch_id,
    i_rejected.id AS item_id,
    v_latest.id AS rejected_version_id,
    v_latest.title AS rejected_title,
    v_latest.body AS rejected_body
FROM autowriter.batches b
JOIN autowriter.items i_rejected ON b.id = i_rejected.batch_id
JOIN autowriter.versions v_latest 
    ON v_latest.item_id = i_rejected.id 
    AND v_latest.id = i_rejected.best_version_id
WHERE i_rejected.status = 'needs_revision'
  AND EXISTS (
    SELECT 1 FROM autowriter.items i_approved 
    WHERE i_approved.batch_id = b.id 
    AND i_approved.status = 'approved'
  )
  -- 排除已被来源 A/B 标过的 item
  AND NOT EXISTS (
    SELECT 1 FROM autowriter.versions v_check
    WHERE v_check.item_id = i_rejected.id
    AND (v_check.ai_engine = 'manual' OR v_check.feedback IS NOT NULL)
  );
```

### 实施方式 · 一次性脚本（产 candidate 队列，不直接落 negative）

**文件名**: `scripts/extract_negative_examples_from_autowriter.py`
**触发**: 一次性运行（NUC pilot 期间）

```python
def extract_negative_examples():
    """扫 autowriter 历史，把 negative 候选写入 example_label_proposal，
    由用户在 Memory Manager UI 中 review 后才真正落 example_label='negative'。
    """
    aw = aw_client.schema('autowriter')  # 跨 schema 显式

    # 1. 扫 3 个来源，按优先级（A > B > C）打 proposal 标记
    # 来源 A: 强信号——用户实际重写过 AI 版
    items_a = run_query_a(aw)
    for item_id in items_a:
        aw.table('items').update(
            {'example_label_proposal': 'negative_manual_rewrite'}
        ).eq('id', item_id).execute()

    # 来源 B: 中信号——用户反馈触发了改写
    items_b = run_query_b(aw)
    for item_id in items_b:
        # 不覆盖已有 proposal（A > B 优先级）
        aw.table('items').update(
            {'example_label_proposal': 'negative_feedback_iter'}
        ).eq('id', item_id).is_('example_label_proposal', None).execute()

    # 来源 C: 弱信号——同 batch 部分通过，本 item 卡 needs_revision
    items_c = run_query_c(aw)
    for item_id in items_c:
        aw.table('items').update(
            {'example_label_proposal': 'negative_batch_rejected'}
        ).eq('id', item_id).is_('example_label_proposal', None).execute()

    print(f"Source A (manual rewrite): {len(items_a)} candidates (high confidence)")
    print(f"Source B (feedback iter):  {len(items_b)} candidates (medium)")
    print(f"Source C (batch rejected): {len(items_c)} candidates (low — review carefully)")
    print(f"Total: {len(items_a) + len(items_b) + len(items_c)} candidates pending review")
    print("用户在 autowriter Memory Manager UI 中确认后才落 example_label='negative'")
```

### autowriter Memory Manager UI 增强（后续工作）

Memory Manager 页面需要加一个 "负例候选审核" tab，展示所有 `example_label_proposal IS NOT NULL` 的 items，按来源分组（高/中/低置信度），用户批量勾选 → 一键确认/忽略。这是 P1 没做的 UI 工作，不阻塞数据回流脚本本身。Spec：

- 列表筛选：`SELECT * FROM items WHERE example_label_proposal IS NOT NULL AND example_label IS NULL`
- 确认动作：`UPDATE items SET example_label='negative', example_label_proposal=NULL WHERE id IN (...)`
- 忽略动作：`UPDATE items SET example_label_proposal=NULL WHERE id IN (...)`

**autowriter 端 build_system_prompt 行为**: `list_example_items(label='negative')` 只看 `example_label='negative'`，不看 proposal——所以候选不会污染 negative pool，必须人工确认后才生效。这也是为什么 P2 引入 proposal 列：**强制 review 前置**。

---

## 飞书 → Truth Vault 主 sync 通道

这是 Truth Vault 的核心数据来源，10 个项目 6,332 行飞书数据。

### Sync 脚本 spec

**文件名**: `scripts/sync_feishu_notes_to_truth_vault.py`
**触发**: 初次一次性 + 后续周期性（每周）

```python
def sync_feishu_notes(project_id, mapping_yaml_path):
    """按 mapping yaml 把飞书表数据 sync 到 Truth Vault notes 表。"""
    
    # 1. 读 mapping yaml
    mapping = load_mapping(mapping_yaml_path)
    
    # 2. 拉飞书表数据（飞书 OpenAPI）
    rows = feishu_client.list_records(mapping.feishu_app_token, mapping.feishu_table_id)
    
    # 3. 对每行：
    for row in rows:
        # a. 字段映射（按 mapping.field_mapping）
        note = apply_field_mapping(row, mapping)
        
        # b. Step 4.5 数值清洗（D-021）
        note = clean_numeric_fields(note)
        
        # c. 未声明字段检测（D-021 quarantine）
        if has_undeclared_fields(row, mapping):
            quarantine(row, mapping)
            continue
        
        # d. tier 抽取
        note['tier'] = extract_tier(row['status'], mapping)
        
        # e. account_id 关联（D-020）
        ensure_account_exists(note['account_id'])
        
        # f. LLM 标注（D-014 子分类 + D-013 sanity check + D-017 essence 标注）
        # ⚠️ 不在 sync 脚本里调用 LLM —— 延迟到独立 annotation pass（D-028）
        # 原因：sync 脚本在 step d 已抽取 tier，如果同一流程里调 LLM，
        # prompt 有可能泄露 tier（label leakage）。拆成两步：
        #   1. sync 脚本只做数据入库（essence 字段留空）
        #   2. 独立 annotation 脚本查 emotional_lever IS NULL 的行，
        #      用 Mode A prompt（不含 performance）盲标
        # 见 prompts/essence_annotator.md v0.3 + scripts/README.md
        
        # g. UPSERT 到 Truth Vault notes 表
        upsert_note(note)
    
    # 4. 触发下游 sync（双通道）
    sync_baokuan_to_sanshengliubu()
    sync_baokuan_to_autowriter()

    # ℹ️ comments 解析: flat extraction 已实现 (sync_comments_from_raw_extra.py)
    # — 把 raw_extra._comment_text / _comment_text_persona 解析成扁平 comments
    # 表。LLM 楼层结构重建仍待 Sprint 2 (D-022 / R-005)，当前 parent_comment_id
    # 全部 NULL。ssll 通道 1 的 top_comments 因此是扁平 list，不抓楼层互动模式。
```

---

## 共享 Supabase 部署架构

### 设计

```
Supabase Instance (帆谷共享实例)
├── public.projects (sanshengliubu 原表)
├── public.pipeline_runs
├── public.stage_logs
├── public.outputs
├── public.reference_samples       ← Truth Vault 通道 1 注入点
│
├── autowriter.projects (建议迁移到独立 schema)
├── autowriter.batches
├── autowriter.items                ← Truth Vault 通道 2 注入点
├── autowriter.versions
├── autowriter.memories
│
└── truth_vault.notes               ← Truth Vault 主表
    truth_vault.accounts            ← D-020
    truth_vault.account_snapshots
    truth_vault.metric_snapshots    ← D-018
    truth_vault.posthoc_analyses    ← D-017
    truth_vault.audience_calibrations
    truth_vault.quality_review_decisions  ← D-013 配套
    truth_vault.comments
    truth_vault.notes_archive
    truth_vault.undeclared_fields_quarantine  ← D-021
    truth_vault.prepublish_evaluations  ← D-025 简化版（仅 evaluator 校准）
```

**注意**:
- sanshengliubu 历史在 public schema —— 不迁移（破坏现有部署）
- autowriter 建议迁移到 autowriter schema —— 避免 `projects` 表名冲突
- Truth Vault 在 truth_vault schema —— 干净分离

### 跨 schema 查询能力

```sql
-- view: prompt 表现追溯（D-016 简化版）
-- canonical SQL 见 schemas/notes_v1_2_cross_schema_views.sql
CREATE OR REPLACE VIEW truth_vault.v_prompt_performance AS
SELECT 
    o.id AS prompt_id,
    o.run_id,
    o.version,
    pr.project_id AS ssll_project_id,
    pr.completed_at,
    COUNT(DISTINCT n.note_id) AS related_notes_count,
    SUM(CASE WHEN n.tier = '爆' THEN 1 ELSE 0 END) AS bao_count,
    SUM(CASE WHEN n.tier = '大爆' THEN 1 ELSE 0 END) AS dabao_count,
    CASE WHEN COUNT(DISTINCT n.note_id) > 0
        THEN (SUM(CASE WHEN n.tier IN ('爆', '大爆') THEN 1 ELSE 0 END))::FLOAT 
             / COUNT(DISTINCT n.note_id)
        ELSE NULL END AS bao_rate
FROM public.outputs o
LEFT JOIN public.pipeline_runs pr ON o.run_id = pr.id
LEFT JOIN truth_vault.notes n ON n.source_sanshengliubu_output_id = o.id
GROUP BY o.id, o.run_id, o.version, pr.project_id, pr.completed_at;

-- view: 模型胜率（Claude vs Gemini vs DeepSeek）
CREATE OR REPLACE VIEW truth_vault.v_model_comparison AS
SELECT 
    v.ai_engine,
    n.project_id,
    COUNT(*) AS total_versions_used,
    SUM(CASE WHEN n.tier = '爆' THEN 1 ELSE 0 END) AS bao_count,
    SUM(CASE WHEN n.tier = '大爆' THEN 1 ELSE 0 END) AS dabao_count,
    AVG(n.interactions) AS avg_interactions,
    CASE WHEN COUNT(*) > 0
        THEN (SUM(CASE WHEN n.tier IN ('爆', '大爆') THEN 1 ELSE 0 END))::FLOAT / COUNT(*)
        ELSE NULL END AS bao_rate
FROM autowriter.versions v
JOIN autowriter.items i ON v.item_id = i.id
JOIN truth_vault.notes n ON n.source_autowriter_version_id = v.id
WHERE v.ai_engine != 'truth_vault_sync'  -- 排除 Truth Vault 回写的 fake version
GROUP BY v.ai_engine, n.project_id;
```

跨 schema join 在共享 Supabase 是 native PostgreSQL 操作，无需 HTTP API。

---

## 历史数据回流策略（D-026）

| 数据源 | 回流策略 | 工程量 |
|---|---|---|
| 飞书表 notes (6,332 行) | ⭐⭐⭐⭐⭐ **必须回流** | 一次性脚本 `sync_feishu_notes` |
| autowriter.items 用户修改记录 | ⭐⭐ 扫一次作 negative seeds | `extract_negative_examples` 一次性 |
| autowriter.items 正面（已发布的）| 不单独回流，已在飞书表 | 通过 FK 关联（source_autowriter_item_id）|
| sanshengliubu.outputs / stage_logs | ⭐ 跳过（AI 内部对抗，无价值）| 零 |
| sanshengliubu.reference_samples | ⭐⭐⭐ 保留共存（tags 区分 source）| 零 |

---

## 集成时序 · 三阶段实施（v2 更新版）

### 阶段 A · 共享 Supabase + 基础 sync（1-2 周）

**目标**：Truth Vault 服务上线，主 sync 通道跑通

- ✅ 共享 Supabase 实例建立（truth_vault schema）
- ✅ 执行 schemas/notes_v1_2.sql
- ✅ FastAPI 服务脚手架
- ✅ `sync_feishu_notes_to_truth_vault.py` 实现 + 跑 NUC_1 全量
- ⬜ NUC_1 LLM annotation pass（D-014 子分类 + D-017 essence + D-013 sanity check）—— 独立脚本，不在 sync 内（D-028）

**关键交付**：NUC_1 1102 行进入 Truth Vault（surface + tier + 数值字段）。Essence + audience 标注由独立 annotation pass 补充（不在 sync 脚本内，见 D-028）

### 阶段 B · 双通道集成（2-3 周）

**目标**：飞轮闭环

- ✅ sanshengliubu 加 `import_truth_vault_baokuan` 方法（30 行）
- ✅ `sync_truth_vault_baokuan_to_sanshengliubu.py` 跑通
- ✅ `sync_truth_vault_baokuan_to_autowriter_items.py` 跑通（含 special batch 设置）
- ✅ `extract_negative_examples_from_autowriter.py` 一次性跑（NUC 期间）

**关键交付**：
- NUC_1 爆款已注入 sanshengliubu.reference_samples（下次 prompt 生产可见）
- NUC_1 爆款已注入 autowriter.items (example_label='positive')（下次内容生成可见）
- autowriter 历史 negative example 已标记（约几十-几百条）

### 阶段 C · 全项目铺开（2-3 个月）

**目标**：其他 9 个项目逐步 onboard

- HXZ_QD / HXZ_FB → RIO_1 → WTG → NRT_2 / NRT_3 → TXQ_1 → TGV_1 → QSHG_1
- 每个项目 onboard 后立即触发双通道 sync
- 飞轮持续转动

---

## 关键设计原则

### 原则 1 · 数据所有权清晰

| 数据 | 主表所有者 | Truth Vault 角色 |
|---|---|---|
| Prompt 内容 | sanshengliubu.outputs | FK 引用（source_sanshengliubu_output_id）|
| Generation runs | sanshengliubu.pipeline_runs / autowriter.batches | FK 引用 |
| 候选内容 | autowriter.items / versions | FK 引用 |
| 评审决策 | autowriter._select_best_drafts 隐式记录 | 简化 prepublish_evaluations 追踪 evaluator 准确率 |
| 已发布笔记 + tier | Truth Vault notes（主） | 主表 |
| 表现快照 | Truth Vault metric_snapshots | 主表 |
| Essence/Audience 标注 | Truth Vault notes 字段 | 主表 |
| Account 信息 | Truth Vault accounts | 主表 |
| 爆文证据包（混合）| sanshengliubu.reference_samples | 通道 1 sync |
| Positive example（爆款）| autowriter.items (label='+') | 通道 2 sync |
| Negative example | autowriter.items (label='-') | 反向通道（一次性 + 用户手动）|
| 用户偏好规则 | autowriter.memories | 不动 |

### 原则 2 · 现存系统改动最小化

- sanshengliubu: 加 1 个方法 `import_truth_vault_baokuan`（~30 行）
- autowriter: **P1 一次性改造 ~190 行**（DDL 修复 + list_example_items 重写 + schema 迁移 + exporter lineage + external_source 字段）。完成后稳态零维护成本。
- 用户体验: 现存系统的 UI 和工作流不变，只是飞轮注入路径多了一个数据源

### prepublish_evaluations 数据采集（已知 gap, D-034 决策）

`truth_vault.prepublish_evaluations` 表 + `v_evaluator_calibration` view 都
已在 schema 中就绪，但 **目前没有 sync 代码会写入这张表**。原因：

- 设计意图（D-025）是 autowriter `_select_best_drafts` 的隐式评审在 TV sync
  时反推存入 prepublish_evaluations
- 但 autowriter codebase 不存"评审记录"，`_select_best_drafts` 只在每个
  item 上设置 `best_version_id`，没有 evaluator type / score / decision 这些
  字段
- 强行反推 evaluator_id 会变成猜测，evaluator accuracy 数据不可靠

**当前决策（D-034）**: prepublish_evaluations 暂不接通 sync，留作 Phase 2
工作。`v_evaluator_calibration` view 当前永远空（无数据，不报错）。

**接通条件**:
1. autowriter 加一张显式的 `evaluations` 表（item_id, evaluator, decision, score）
2. autowriter 评审动作显式写入这张表（不是从 best_version_id 反推）
3. 然后 TV 加一个 sync 脚本读 autowriter.evaluations → truth_vault.prepublish_evaluations
4. 实际 tier 在 TV 已有 → was_correct 字段自动算

这是工程量较大的 cross-team 工作，等 Sprint 2+ 飞轮主链路验收稳定后再开。

### 原则 3 · Sync 单向 + 幂等

- Truth Vault → sanshengliubu / autowriter 是**单向 sync**（不双向修改）
- 所有 sync 操作必须**幂等**（重跑不重复插入）
- **autowriter 通道**用 `items.external_source='truth_vault' + external_source_id=note_id` 作主去重键（partial UNIQUE INDEX 保证）；不再依赖 `versions.title` 这种弱键
- **sanshengliubu 通道**优先用 `reference_samples.source_truth_vault_note_id` 作主去重键（专门加的索引列，由 `sanshengliubu-patches/001_add_source_tv_note_id.sql` 加）；`ai_analysis->>'_truth_vault_note_id'` 仅作 legacy fallback，兼容老数据

---

## 不集成的话会怎样

- **Truth Vault 沦为孤立数据库** —— 只能回答"已发布表现如何"，回答不了"哪个 prompt 让内容爆了"
- **sanshengliubu reference_samples 没自家数据** —— 只能用外部爬的爆文，prompt 生产时缺乏帆谷自家成功经验
- **autowriter positive_examples 靠 AI 自评** —— 不基于真实 tier，权重低
- **autowriter 用户改写信号丢失** —— 几百条用户手动修改记录浪费

简言之：**v2 双通道是飞轮真正转起来的关键**。

---

## 附录 · 为什么从 v1 改到 v2

Session #7 代码审查发现：

1. **sanshengliubu / autowriter 远比 v1 假设的成熟**（30+ 版本 / 工业级 schema）
2. **两个项目都有自己的"飞轮雏形"**:
   - sanshengliubu.reference_samples + retrieve_reference_packs
   - autowriter.items.example_label + build_system_prompt(positive_examples)
3. **Truth Vault 的 D-016 4 张过程数据表和现存系统严重重叠**（重复造轮子）
4. **现存系统飞轮缺的不是"另一套数据库"，是"自家真实爆款数据"**

v2 的本质：**Truth Vault 从"过程数据库"降级为"结果数据库 + 跨系统飞轮枢纽"**——把帆谷真实爆款数据喂到现存系统已有的飞轮注入点。

参见: [DECISIONS.md](../DECISIONS.md) D-024 / D-025 / D-026 / D-027

---

## 下一步

如果你是新接手的工程师：
1. 部署共享 Supabase 实例（包含三个 schema）
2. 执行 schemas/notes_v1_2.sql
3. 实现 `sync_feishu_notes_to_truth_vault.py`
4. 跑 NUC_1 全量
5. 实现两个通道的 sync 脚本
6. 上线，飞轮开始转

如果你是策略 lead：
1. 维护 Truth Vault projects 表的 `mapping_to_autowriter_project_id`
2. NUC pilot 完成后审查双通道 sync 效果
3. 监控 sanshengliubu vibe_rewriter / autowriter system_prompt 的实际行为变化
