# Truth Vault · 实施手册 (Implementation Guide)

> **这份文档给谁看**
> - 第一次接手 Truth Vault 部署 / 集成 / 运维的工程师
> - 假设你**完全不熟悉**这三个项目, 也不熟悉 Supabase / 飞书 OpenAPI / GitHub Actions
> - 假设你的目标是 "把 TV → sanshengliubu / autowriter 的飞轮跑起来",
>   不是 "理解 TV 是什么"
>
> **如果你想理解项目本身**: 先看 [`README.md`](README.md) → [`CURRENT_STATE.md`](CURRENT_STATE.md)
> **如果你要动手部署**: 从下方 § 0 开始, **按顺序**.
>
> **维护责任**: 任何对部署 / 集成 / 配置流程的改动, 必须同步更新本文件相应章节. 见末尾 § 8.

---

## § 0 · 完整需求清单 (开始前必须凑齐)

下面这些东西**全部**得有, 缺一项就有 step 会卡住. 边读边打钩.

### 0.1 凭证 / 账号 (找谁要)

| 需要的东西 | 用来干什么 | 从哪里拿 |
|---|---|---|
| Supabase 项目 (共享实例) | 装 truth_vault + autowriter + sanshengliubu 三个 schema | Supabase Dashboard → New project. 推荐 Pro plan (RLS 性能 + max_rows ≥ 1000) |
| Supabase URL | sync 脚本连接用 | Supabase Dashboard → Settings → API → Project URL, 形如 `https://xxx.supabase.co` |
| Supabase service_role key | sync 脚本写入用 (绕过 RLS) | 同上 → service_role secret (新格式 `sb_secret_*` 或旧 JWT) |
| 飞书应用 ID + Secret | 拉飞书 Bitable 数据 | 飞书开放平台 → 创建企业自建应用 → 凭证与基础信息. 需要开通 `bitable:app` 权限 |
| Anthropic API key | essence / sub_direction / comments threading LLM pass | console.anthropic.com → API Keys. 第一次跑 NUC_phase1 全量 ≈ ¥200-400 |
| autowriter 服务账号 user_id | autowriter.items.user_id 必填; sync 脚本注入用 | 找 autowriter 维护者建一个 "service account" 用户, 拿它的 UUID |
| GitHub repo 写权限 + Settings/Secrets 权限 | 配 daily-sync.yml secrets, 启用 cron | 找 repo owner (Ziao) 加你为 admin |

### 0.2 协调对象 (找谁谈)

| 角色 | 你要他们做什么 | 详细说明 |
|---|---|---|
| **autowriter 维护者** | 跑 `autowriter-migrations/001/002/003` SQL + 协调停机迁移窗口 | 见 [`autowriter-migrations/RUNBOOK.md`](autowriter-migrations/RUNBOOK.md). 场景 A (autowriter 现在独立 Supabase, 要迁) 需要 0.5-2 小时停机. 场景 B (已经在共享实例) 几分钟. |
| **autowriter 维护者** (后续, 可选) | 实现 [`autowriter-migrations/004_dual_positive_pool_patch.md`](autowriter-migrations/004_dual_positive_pool_patch.md) + [`005_memory_manager_negative_review_tab.md`](autowriter-migrations/005_memory_manager_negative_review_tab.md) | 不阻塞首次部署. 等飞轮跑稳后再做 |
| **sanshengliubu 维护者** | 确认 ssll 已经跑过 `db/migrations/005_reference_samples_v2.sql` (v2 证据包 schema). 然后跑 TV 这边的 patch | 在 ssll 仓库 `db/migrations/` 看 005 是否在. 如果在, 直接跑 [`sanshengliubu-patches/001_add_source_tv_note_id.sql`](sanshengliubu-patches/001_add_source_tv_note_id.sql) |
| **运营 (Ziao 或代理)** | 填飞书表 + 维护 `mappings/*.yaml` + 跨系统手动 mapping | 见 § 4 |

### 0.3 你这边需要熟悉的工具

| 工具 | 用在哪 | 最低要求 |
|---|---|---|
| `git` | clone repo / push 改动 | clone + commit + push 会就行 |
| `python 3.11` + `pip` | 跑 sync 脚本 | 装 venv 就 OK |
| `psql` (Postgres 客户端) | 部署 schema / 验证 / 排错 | apt-get install postgresql-client; SELECT 看得懂就行 |
| Supabase Dashboard | 看表 / 改 mapping 值 / 配 secrets | 网页 UI, 不会就跟着 § 2 一步步点 |
| GitHub Actions | 自动 cron sync | 看得懂 workflow run 状态就行 |

**不需要熟悉**: ML 框架, Streamlit, 飞书 webhook, Docker.

---

## § 1 · 整体架构 (30 秒图解)

```
   飞书 Bitable (运营每天填爆款数据)
        │
        │  sync_feishu_notes_to_truth_vault.py
        ▼
   ┌─────────────────────────────────────────────┐
   │ 共享 Supabase 实例                          │
   │ ├─ truth_vault schema (TV 主数据)           │
   │ ├─ autowriter schema (autowriter 项目数据)  │
   │ └─ public schema (sanshengliubu 数据)       │
   └─────────────────────────────────────────────┘
        │                                  │
        │ 通道 1                            │ 通道 2
        │ sync_truth_vault_baokuan_         │ sync_truth_vault_baokuan_
        │   to_sanshengliubu.py             │   to_autowriter_items.py
        ▼                                  ▼
   public.reference_samples           autowriter.items
   (sanshengliubu 的 vibe_rewriter    (autowriter 的 build_system_prompt
    检索时按 platform+category 拉)     按 created_at DESC 拉 limit=5)
        │                                  │
        │ ssll 自身的内部流程              │ autowriter 自身的内部流程
        ▼                                  ▼
   产出新 prompt (运营手动复制) ──→ autowriter 按新 prompt 生产内容
                                       │
                                       │ 运营审稿 / 发投放
                                       ▼
                              飞书填新一轮结果 → 回到顶部
```

**核心理解**: TV 不调用任何外部 API. 它通过共享 Supabase 跨 schema **直接 INSERT** 到 sanshengliubu / autowriter 的现存表里. 这是 [D-024](DECISIONS.md) 的关键决策. 早期 v1 spec (D-023) 设计的 HTTP REST API **已作废**, 任何要求外部系统调用 TV 的描述都是过时表述.

---

## § 2 · 完整部署 step-by-step

按顺序做. 每一步都有 (a) 命令, (b) 期望输出, (c) 失败时怎么诊断, (d) 怎么验证成功.

### Step 1 · 准备共享 Supabase 实例 (~15 分钟)

**做什么**:
1. 登录 Supabase Dashboard → New project, region 选离用户近的 (帆谷在国内: Northeast Asia · Singapore 或 Tokyo)
2. 等实例 provision 完成
3. Settings → Database → Connection string 记下 host/port (后面 psql 命令用)
4. Settings → API → 记下 Project URL 和 service_role key

**额外配置**:
- Settings → API → **Exposed schemas**: 默认只有 `public`. 加上 `autowriter` 和 `truth_vault` (这两个 schema 还不存在, 但 Supabase 会接受, 后续创建后就生效)
- Settings → API → **Max Rows**: 默认 1000. 至少 5000, 推荐 10000. 否则后续 fetch_all_pages 分页跑得慢

**验证**:
```bash
# 把 SUPABASE_URL 和 service_role key 填到环境变量后:
export SUPABASE_URL='https://你的项目.supabase.co'
export SUPABASE_SERVICE_ROLE_KEY='sb_secret_xxx'  # 或旧 JWT 格式

# 用 curl 或 psql 验证连通
curl "${SUPABASE_URL}/rest/v1/" -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}"
# 期望: 返回 OpenAPI spec JSON, 不是 401
```

**失败诊断**:
- `401`: service_role key 错了 / 拼写错
- `network error`: Supabase 实例没起好, 等 5 分钟
- `403`: 你拿到了 anon key, 不是 service_role

### Step 2 · 部署 TV schema (~5 分钟)

**做什么**: 把 `schemas/notes_v1_2.sql` 应用到 Supabase. 这一步会创建 `truth_vault` schema + 全部表 + 触发器 + 内部 views.

**做之前**: 确认 Step 1 完成. autowriter / sanshengliubu schema 还**没有**也没关系 (cross-schema views 是单独一份文件).

**两种方式 (选一个)**:

方式 A · Supabase Dashboard 网页执行 (推荐第一次部署):
1. Dashboard → SQL Editor → New query
2. 把 `schemas/notes_v1_2.sql` 整个内容复制粘贴进去
3. Run. 等 10-30 秒.

方式 B · 命令行 psql (推荐脚本化部署):
```bash
# Connection string 从 Supabase Dashboard → Database → Connection string (URI 格式)
PGURI="postgresql://postgres.xxx:密码@aws-region.pooler.supabase.com:6543/postgres"
psql "$PGURI" -v ON_ERROR_STOP=1 -f schemas/notes_v1_2.sql
```

**期望输出**: 一长串 `CREATE TABLE` / `CREATE INDEX` / `CREATE TRIGGER` / `CREATE VIEW`, 没有 `ERROR`. 大概几十行输出.

**幂等性**: 这个 SQL 全部用 `CREATE ... IF NOT EXISTS` / `CREATE OR REPLACE`. 重复跑没事.

**验证**:
```sql
-- 在 Supabase SQL Editor 跑:
SELECT COUNT(*) FROM information_schema.tables
WHERE table_schema = 'truth_vault';
-- 期望: ≥ 12 (主表 + 衍生表 + audit_log + 等)

SELECT COUNT(*) FROM information_schema.views
WHERE table_schema = 'truth_vault';
-- 期望: ≥ 5 (v_project_tier_summary, v_data_health,
-- v_top_performing_accounts, v_evaluator_calibration,
-- v_flywheel_sync_status, v_autowriter_injection_candidates)
```

**失败诊断**:
- `permission denied for schema public`: 你用的是 anon key, 不是 service_role
- `pgcrypto extension does not exist`: Supabase 默认装了, 但如果是自托管 PG 要 `CREATE EXTENSION pgcrypto;`
- 中间有报错: 把报错行号贴出来, 大概率是 SQL 语法兼容性 (Supabase 偶尔 PG 版本不一样); 不要继续, 修了再来

### Step 3 · 部署 sanshengliubu 集成 patch (~5 分钟)

**前置条件**:
- sanshengliubu 已经跑过自己的 `db/migrations/005_reference_samples_v2.sql` (v2 证据包 schema)
- **怎么确认**: 找 ssll 维护者. 或者 SQL 查:
  ```sql
  SELECT column_name FROM information_schema.columns
  WHERE table_schema='public' AND table_name='reference_samples'
    AND column_name IN ('post_title','post_body','top_comments','ai_analysis','quality_score');
  -- 期望: 返回 5 行. 少一行说明 ssll 自己的 005 没跑.
  ```

**确认前置后**, 跑 TV 这边的 patch:
```bash
psql "$PGURI" -v ON_ERROR_STOP=1 -f sanshengliubu-patches/001_add_source_tv_note_id.sql
```

**期望输出**: `ALTER TABLE` + `CREATE INDEX` + `COMMENT` + `DO` (4-5 行).

**验证**:
```sql
SELECT column_name, data_type FROM information_schema.columns
WHERE table_schema='public' AND table_name='reference_samples'
  AND column_name='source_truth_vault_note_id';
-- 期望: source_truth_vault_note_id | text
```

**失败诊断**:
- `relation "public.reference_samples" does not exist`: ssll 自己的 schema 都没部署. 找 ssll 维护者先跑 `db/schema.sql` + `db/migrations/005`. **必须**.

### Step 4 · 部署 autowriter 迁移 (要协调; ~30 分钟 - 2 小时)

**这一步必须找 autowriter 维护者**, 因为可能涉及把 autowriter 数据从独立 Supabase 迁到共享实例 (场景 A, 需要停机).

**全部细节在 [`autowriter-migrations/RUNBOOK.md`](autowriter-migrations/RUNBOOK.md)**, 这里只列你需要做什么:

1. **判断场景** (A vs B): 看 autowriter 当前 SUPABASE_URL 是不是已经等于共享实例的 URL.
   - 等于 → 场景 B, 几分钟搞定 (只需要 `001/002/003` SQL)
   - 不等于 → 场景 A, 要协调停机窗口 (建议运营低谷期, 提前 24h 通知 autowriter 用户)
2. **应用三个 migration** (无论场景 A 或 B, 都要跑):
   ```bash
   psql "$PGURI" -v ON_ERROR_STOP=1 -f autowriter-migrations/001_create_autowriter_schema.sql
   psql "$PGURI" -v ON_ERROR_STOP=1 -f autowriter-migrations/002_add_external_source.sql
   psql "$PGURI" -v ON_ERROR_STOP=1 -f autowriter-migrations/003_add_example_label_proposal.sql
   ```
3. **场景 A 额外步骤**: pg_dump 旧数据 + restore 到共享实例; 改 autowriter 仓库的 `config.py` 的 SUPABASE_URL; 改 autowriter 代码里所有 SQL 加 `autowriter.` schema 前缀. 这些**全部由 autowriter 维护者做**, 你只协调时间.

**验证**:
```sql
-- 5 张 autowriter 表都搬到 autowriter schema 了
SELECT table_name FROM information_schema.tables
WHERE table_schema='autowriter'
  AND table_name IN ('projects','batches','items','versions','memories');
-- 期望: 5 行

-- 002 加的 external_source 列
SELECT column_name FROM information_schema.columns
WHERE table_schema='autowriter' AND table_name='items'
  AND column_name IN ('external_source','external_source_id');
-- 期望: 2 行

-- 003 加的 example_label_proposal 列
SELECT column_name FROM information_schema.columns
WHERE table_schema='autowriter' AND table_name='items'
  AND column_name='example_label_proposal';
-- 期望: 1 行
```

**失败诊断**:
- `relation "autowriter.items" does not exist`: 001 没跑 / autowriter 表还在 public schema; 跑 001
- `column "external_source" already exists`: 之前跑过了, 这条 ALTER 是 IF NOT EXISTS 的, 应该自动跳过. 如果不是, 检查 SQL 文件版本
- autowriter UI 报 `relation does not exist`: autowriter 自己代码还没改成读 autowriter schema. 找 autowriter 维护者. **场景 A 不能省略代码改造**

### Step 5 · 部署跨 schema views (~2 分钟)

**前置**: Step 2 + Step 4 都成功 (truth_vault + autowriter 两个 schema 都已就绪).

```bash
psql "$PGURI" -v ON_ERROR_STOP=1 -f schemas/notes_v1_2_cross_schema_views.sql
```

**期望输出**: 3 行 `CREATE VIEW` (`v_prompt_performance`, `v_model_comparison`, `v_autowriter_positive_pool_saturation`).

**验证**:
```sql
SELECT COUNT(*) FROM truth_vault.v_prompt_performance;
SELECT COUNT(*) FROM truth_vault.v_model_comparison;
SELECT COUNT(*) FROM truth_vault.v_autowriter_positive_pool_saturation;
-- 期望: 每个都返回 0 (空 view, 但能查就行)
```

### Step 6 · 配置环境变量 + GitHub Secrets (~10 分钟)

**两套配置, 用途不一样**:
- 本地 `.env`: 给你手动跑脚本调试用
- GitHub Secrets: 给 daily-sync.yml workflow 用 (cron 自动跑)

#### 本地 .env (拷贝 .env.example 改)

```bash
cd scripts/
cp .env.example .env
# 编辑 .env, 把每个变量按下表填好
```

| 变量 | 必填 | 从哪里拿 | 示例 |
|---|---|---|---|
| `SUPABASE_URL` | ✅ | Step 1 拿到的 Project URL | `https://abc.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅ | Step 1 拿到的 service_role secret | `sb_secret_xxx...` 或 `eyJxxx...` (旧 JWT) |
| `FEISHU_APP_ID` | ✅ | 飞书开放平台 → 应用凭证 | `cli_axxx` |
| `FEISHU_APP_SECRET` | ✅ | 同上 | `xxx` |
| `AUTOWRITER_SYNC_USER_ID` | 可选 (兜底) | 2026-05-21 audit 后默认改用 `autowriter.projects.owner_id`; 这个 env 仅在 owner_id 异常缺失时作为兜底, 新部署可以不配 | `00000000-0000-0000-0000-000000000001` |
| `ANTHROPIC_API_KEY` | annotation 才用 | console.anthropic.com → API Keys | `sk-ant-xxx` |
| `ESSENCE_MODEL` | 可选 | 默认 `claude-sonnet-4-6` | `claude-sonnet-4-6` |
| `COMMENT_THREADING_MODEL` | 可选 | 默认同上 | `claude-sonnet-4-6` |
| `AUTOWRITER_INJECTION_MAX_PER_RUN` | 可选 | 默认 5 | `5` |
| `AUTOWRITER_INJECTION_MIN_SCORE` | 可选 | 默认 0.5 | `0.5` |
| `AUTOWRITER_INJECTION_MIN_LEVERS` | 可选 | 默认 3 | `3` |
| `AUTOWRITER_EXAMPLE_MAX_AGE_DAYS` | 可选 | 默认 180 | `180` |

`.env` **绝不能 commit**, `.gitignore` 已经排除了它. 不要 paste 到任何聊天工具 / share / Slack.

#### GitHub Secrets

repo → Settings → Secrets and variables → Actions → New repository secret. 每个变量加一次. 名字和上表完全一致.

**至少**配齐 `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` / `FEISHU_APP_ID` / `FEISHU_APP_SECRET`. `AUTOWRITER_SYNC_USER_ID` 2026-05-21 audit 后改为可选 (默认从 `autowriter.projects.owner_id` 解析); 没有 `ANTHROPIC_API_KEY` 的话 annotation step 自动跳过, 主 sync 不受影响.

### Step 7 · 第一次 dry-run 验证 (~10 分钟)

**做什么**: 跑一次 sync 但 `--dry-run`, 看 stdout 是否报错.

**前置**: 至少一个 `mappings/*.yaml` 已经填好 `sync_config.feishu_app_token` / `feishu_table_id`. 见 § 3.3.

```bash
cd scripts/
source venv/bin/activate
source .env  # 把环境变量加载进当前 shell

# 第一步: feishu → TV 主数据
python sync_feishu_notes_to_truth_vault.py NUC_phase1 --dry-run --limit 5

# 第二步: TV → ssll (没爆款的话会直接 "Found 0 pending", 那也算对)
python sync_truth_vault_baokuan_to_sanshengliubu.py --dry-run

# 第三步: TV → autowriter
python sync_truth_vault_baokuan_to_autowriter_items.py --dry-run

# 第四步: preview (核对 injection 候选)
python preview_injection_candidates.py --project NUC_phase1
```

**期望输出 (每个脚本)**:
- 启动时不报错 (没有 `RuntimeError: SUPABASE_URL...`)
- `Found N records / candidates ...` 这种统计行
- `[dry-run] would upsert ...` 这种伪写入行
- 结束 `Done: {...}` stats JSON

**失败诊断**:
- `RuntimeError: SUPABASE_SERVICE_ROLE_KEY has role='anon'`: 你拿到的是 anon key, 重新去 Step 1 拿 service_role
- `preflight failed ...post_body...`: ssll 自己的 005 migration 没跑. 回 Step 3.
- `relation "autowriter.items" does not exist`: 回 Step 4.
- `mapping_to_autowriter_project_id IS NULL`: 该 TV 项目还没建跟 autowriter 项目的映射. 见 § 4.

### Step 8 · 启用 daily-sync cron (~5 分钟)

**前置**: Step 7 全部 dry-run 通过.

1. 编辑 `.github/workflows/daily-sync.yml`, **取消** 头部的 `# schedule:` 注释段:
   ```yaml
   schedule:
     - cron: '0 2 * * *'   # 02:00 UTC = 10:00 北京时间
   ```
2. Commit + push 到 main. GitHub Actions 第二天 02:00 UTC 自动跑.
3. 第一次想立刻试: repo → Actions → Daily TV sync → Run workflow → dry_run=true → Run. 看 logs.
4. dry_run=true 跑过后再 dry_run=false 实跑一次, 验证写入真到 Supabase.

**期望行为**: 每天 02:00 自动跑全 pipeline. 失败的话 GitHub 给 repo owner 发邮件.

---

## § 3 · 配置参考

### 3.1 完整 .env 字段表

见 [§ 2 Step 6](#step-6--配置环境变量--github-secrets) 表格. 同样的字段也在 `scripts/.env.example` 里有备注.

### 3.2 完整 GitHub Secrets 字段表

同上.

### 3.3 mapping yaml 怎么写

**位置**: `mappings/<project_id>.yaml`. 每个 TV 项目 (NUC_phase1 / NRT_phase3 / TGV_1 / 等) 一份.

**最小可跑骨架**:
```yaml
project_id: NUC_phase1
brand: NUC
product: 营养代餐
category: 保健品              # 必须从 docs/05-controlled-vocab.md §9 闭集里选
platform: xiaohongshu
schema_family: A             # A/B/C, 见 docs/02-schema-v1.md
tier_thresholds:
  爆:   150                  # 爆款门槛 (互动量)
  大爆: 700

sync_config:
  source_type: feishu_api
  feishu_app_token: bascnXXXXXXXXXXXXX   # 找 Ziao 要
  feishu_table_id:  tblYYYYYYYYYY        # 同上
  feishu_view_id:   vewZZZZZZZZ          # 可选, 默认用 default view

field_mapping:
  # 飞书列名 → TV 字段名 (或 _中间态_前缀)
  "文案":      raw_content
  "互动量":    interactions
  "曝光":      impressions
  "阅读":      reads
  "状态":      _status_raw              # 给 tier_extraction 用
  "蓝词命中":  hit_blue_keywords
  # 等等

tier_extraction:
  source: 状态字段                       # 状态字段 | 备注字段, 必须从闭集选
  rules:
    - match_contains: ["大爆"]
      tier: 大爆
    - match_contains: ["爆"]
      tier: 爆
    - match_contains: ["趴"]
      tier: 趴
    - match_contains: ["风控"]
      tier: 风控
    - default: 未知

# 可选: 拉到 TV 但不进主表的字段, 进 raw_extra
project_specific_fields_to_raw_extra:
  - "随贴评论"
  - "随贴评论素人"
```

**详细字段定义**: 见 [`docs/03-mapping-protocol.md`](docs/03-mapping-protocol.md). **不要绕过协议**: 一切字段必须先在协议里有 spec 才能加进 yaml.

**完整示例**: `mappings/NUC_phase1.yaml` (已就绪), 直接拷贝改名再调整字段.

### 3.4 跨系统手动 mapping 怎么建

TV → autowriter 通道需要 `truth_vault.projects.mapping_to_autowriter_project_id` 这一列指向具体的 autowriter 项目. 这是**手工维护**, 没有自动:

```sql
-- 在 Supabase SQL Editor:
UPDATE truth_vault.projects
SET mapping_to_autowriter_project_id = 'autowriter_的_projects.id_UUID'
WHERE project_id = 'NUC_phase1';
```

**怎么找 autowriter 那个 UUID**:
```sql
SELECT id, name FROM autowriter.projects WHERE name LIKE '%NUC%';
```

同理 ssll 那边的 `mapping_to_sanshengliubu_project_id` (如果之后 ssll 也按项目隔离).

**没建这一列, TV → autowriter sync 会**: skip 全部该 TV 项目的 baokuan (脚本 log 会写 "Skipping N baokuan without mapping_to_autowriter_project_id set"). 这是设计行为, 不是 bug.

---

## § 4 · 跨项目对接 checklist

### 4.1 给 sanshengliubu 维护者的指令

| 时机 | 要他们做什么 | 怎么验证完成 |
|---|---|---|
| 部署前 | 确认 ssll 自身的 `db/migrations/005_reference_samples_v2.sql` 跑过 | Step 3 的 SQL 查询应该返回 5 行 |
| 部署前 | 在共享 Supabase 实例上跑 `sanshengliubu-patches/001_add_source_tv_note_id.sql` | Step 3 验证 |
| 长期 | 如果将来 ssll 改 reference_samples schema (重命名列 / 加新列 / 删列), **必须**通知 TV 这边. 三个地方要同步更新: `scripts/sync_truth_vault_baokuan_to_sanshengliubu.py:build_reference_sample`, `:preflight_check`, `docs/09-system-integration.md` | CI 的 `sanshengliubu sync shape self-check` step 红 |

### 4.2 给 autowriter 维护者的指令

| 时机 | 要他们做什么 | 怎么验证完成 |
|---|---|---|
| 部署前 | 走完 `autowriter-migrations/RUNBOOK.md` 场景 A 或 B (含 001/002/003 + 数据迁移) | Step 4 验证 |
| 部署前 | 建一个 service account 用户, 给你它的 user_id (UUID) | 你能用这个 UUID 跑通 `sync_truth_vault_baokuan_to_autowriter_items.py --dry-run` |
| 长期 (可选) | 实施 [`autowriter-migrations/004_dual_positive_pool_patch.md`](autowriter-migrations/004_dual_positive_pool_patch.md): list_example_items 加 source_filter, app.py 拆 native + TV 双池 | autowriter 端 build_system_prompt 注入的 5 个 positive 例子能看到既有 TV 同步进来的也有 autowriter 内置的 |
| 长期 (可选) | 实施 [`autowriter-migrations/005_memory_manager_negative_review_tab.md`](autowriter-migrations/005_memory_manager_negative_review_tab.md): Memory Manager 加负例 review tab | 运营能在 autowriter UI 上确认 negative example_label_proposal → example_label='negative' |
| 长期 | 如果 autowriter 改 items/batches/versions 表的列, **必须**通知 TV 这边. 影响: `sync_truth_vault_baokuan_to_autowriter_items.py`, `extract_negative_examples_from_autowriter.py`, `sync_autowriter_decisions_to_prepublish.py`, `notes_v1_2_cross_schema_views.sql` | CI 的 SQL apply step 红 / 运行时 PostgREST 报 column does not exist |

### 4.3 给运营 (Ziao 或代理) 的指令

| 任务 | 频率 | 干什么 |
|---|---|---|
| 填飞书表的真实数据 | 每天 | 互动量 / 阅读量 / tier / 控评内容; 不能填错 0 (会触发 tier 错位) |
| 维护 `mappings/<project>.yaml` | 项目 onboarding 时 | 新项目按 § 3.3 模板填 |
| 设置 mapping_to_autowriter_project_id | 项目 onboarding 时 | 按 § 3.4 手工建跨系统映射 |
| 审 `example_label_proposal` 负例候选 | 每月一次 (或等触发) | 在 autowriter Memory Manager UI 里确认 (#8 实施完成后) |
| 审 essence 标注质量 | 每月一次 | 抽 30 条人工核对, 调词表/prompt; 见 [`docs/07-quality-review.md`](docs/07-quality-review.md) |
| 看 `recommend_tier_thresholds.py` 报告 | 每季度一次 | drift > 50% 考虑改 yaml 的 tier_thresholds |
| 看 `check_positive_saturation.py` 输出 | 每周一次 / cron 自动 | 哪个项目 dominant_lever_ratio ≥ 0.6 就要警惕 |

---

## § 5 · 验证 / 监控 / 排错

### 5.1 每天看什么

GitHub Actions → Daily TV sync 的最新 run 状态:
- 绿色 ✅: 通过, 看 `Show flywheel status` step 的 stdout, 关键指标:
  - `pending_ssll_sync` / `pending_aw_sync` 不该长期 > 50; 长期堆积说明 sync 没跑
  - `last_baokuan_sync_to_*_at` 是不是昨天的 — 不是说明 sync 出问题
- 红色 ❌: 失败, 看哪一步红, 按 § 5.4 排错

### 5.2 每周看什么

```bash
# 飞轮状态
psql "$PGURI" -c "SELECT * FROM truth_vault.v_flywheel_sync_status;"

# 数据健康度
psql "$PGURI" -c "SELECT * FROM truth_vault.v_data_health;"

# Positive pool 饱和度 (前提: 通道 2 已经在跑一段时间)
python scripts/check_positive_saturation.py
```

### 5.3 每月看什么

```bash
# Tier 阈值是否仍合理
python scripts/recommend_tier_thresholds.py --window-days 90

# 跑一次负例挖掘 (一次性 / 定期, 频率自定)
python scripts/extract_negative_examples_from_autowriter.py

# 审计日志看看有没有奇怪改动
psql "$PGURI" -c "
  SELECT operation, table_name, COUNT(*), MAX(occurred_at)
  FROM truth_vault.audit_log
  WHERE occurred_at > NOW() - INTERVAL '30 days'
  GROUP BY operation, table_name;
"
```

### 5.4 常见错误诊断矩阵

| 报错 / 现象 | 哪一步出问题 | 怎么修 |
|---|---|---|
| `RuntimeError: SUPABASE_SERVICE_ROLE_KEY has role='anon'` | Step 6 用错 key | 拿 service_role key, 不是 anon |
| `preflight failed ...post_body / post_title / top_comments...` | Step 3 没跑 ssll 的 005 | 找 ssll 维护者 |
| `relation "autowriter.items" does not exist` | Step 4 没跑 001 | 跑 autowriter-migrations/001 |
| `column "external_source" of relation "items" does not exist` | Step 4 没跑 002 | 跑 autowriter-migrations/002 |
| `column "example_label_proposal" ... does not exist` | Step 4 没跑 003 | 跑 autowriter-migrations/003 |
| `Skipping N baokuan without mapping_to_autowriter_project_id` | § 3.4 没建跨系统映射 | UPDATE truth_vault.projects 设那一列 |
| `permission denied for schema autowriter` | Step 1 没把 autowriter 加进 Exposed schemas | Settings → API → Exposed schemas |
| `Feishu auth failed code: 99991663` | FEISHU_APP_SECRET 错 / 应用没启用 | 飞书开放平台检查应用状态 |
| `Feishu list_records error code: 91402` | 飞书应用没拿到 Bitable 读权限 | 飞书开放平台 → 权限管理 → 添加 `bitable:app` |
| `mapping yaml ... missing required keys: project_id, field_mapping` | yaml 错 | 按 § 3.3 模板补 |
| `tier_extraction.source='错的值' not in ['状态字段', '备注字段']` | yaml typo | 改正 |
| sync 跑通了但 ssll vibe_rewriter 没拿到数据 | preflight 假通过但 schema 实际不对 | 在 ssll 端跑 `SELECT * FROM public.reference_samples WHERE source_truth_vault_note_id IS NOT NULL LIMIT 5` 看数据是否真到了 |
| `dominant_lever_ratio = 1.0` 告警 | autowriter 拉的 5 条都是同 lever | 等 essence 标注覆盖率上来 + diversity filter 才会生效; 或人工标更多元的 baokuan 进 TV |
| daily-sync workflow 跑了但每天都失败 | 大概率 secrets 没配齐 / 配错 | repo → Settings → Secrets, 重新核对每个值 |

### 5.5 紧急情况怎么办

| 情况 | 怎么处置 |
|---|---|
| 发现 sync 写了大量错的数据 | (1) 立刻 disable daily-sync.yml 的 schedule; (2) 用 `truth_vault.audit_log` 查最近 24h 改了什么; (3) 决定 rollback 还是手工修 |
| Supabase 实例宕机 | sync 自动 retry 已经能扛短暂 (call_claude 3 次指数退避). 持续宕看 Supabase status; 加客户 ticket |
| 飞书表数据被运营误删 | sync 不会主动删 TV 行, 但下次 sync 重跑会丢 quarantine 行. 跟运营核对源数据, 必要时手动 INSERT |
| service_role key 泄漏 | (1) Supabase Dashboard → API → Reset service_role key; (2) 把所有用到的地方 (.env / GitHub Secrets / autowriter config) 同步换新 |

---

## § 6 · 本文档的维护

**什么时候改这份文档**:

| 触发 | 改哪里 |
|---|---|
| 新加一个外部依赖 (例: 新接入抖音 API) | § 0.1, § 0.2 |
| 部署流程加了新 step | § 2 加 step |
| 加了新的 .env 变量 | § 3.1 + Step 6 表格 |
| 加了新 sync 脚本 | § 2 Step 7 + § 5.2 / 5.3 监控查询 |
| 出现新的常见错误 | § 5.4 矩阵加一行 |
| sanshengliubu 或 autowriter 改了 schema | § 4 加 "时机 = 这次改动" 一行, 描述 TV 这边要同步改的地方 |
| 加了新延后 backlog 项 | 这份文档不动; 改 `CURRENT_STATE.md` 的延后清单 |

**这份文档不该包含什么**:
- 设计原因 / 决策依据 (那是 `DECISIONS.md` / `docs/01-09`)
- 项目宪法 / 概念解释 (那是 `README.md` / `docs/01`)
- 状态快照 / 当前 Sprint 进度 (那是 `CURRENT_STATE.md`)
- 风险 backlog + 触发条件 (那是 `RISKS.md` + `CURRENT_STATE.md` 延后清单)

**这份文档的目标**: 任何一个不熟悉项目的工程师, 拿到 0.1 列的全部凭证 + 这份文档, **不读其他任何文档**, 也能把飞轮跑起来. 如果做不到, 就是这份文档不够完整, 应该补.
