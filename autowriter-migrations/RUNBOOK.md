# autowriter-migrations/ RUNBOOK

Truth Vault 通道 2 集成 patch 包. 把 autowriter 从独立 Supabase 实例迁到
共享 Supabase 实例的 `autowriter` schema, 并加上 TV sync 所需的列.

## 内容

| 文件 | 用途 | 前置条件 |
|---|---|---|
| `001_create_autowriter_schema.sql` | 把 autowriter 5 张表从 public schema **搬迁** 到 autowriter schema (ALTER TABLE SET SCHEMA) | 仅场景 A：autowriter 当前在共享 Supabase 的 public schema |
| `002_add_external_source.sql` | 给 items 加 external_source/external_source_id (P1 Sprint 1.1 幂等键) | 001 完成 (或 autowriter 已在独立 schema) |
| `003_add_example_label_proposal.sql` | 给 items 加 example_label_proposal (P2 negative review queue) | 002 完成 |
| `004_dual_positive_pool_patch.md` | autowriter 代码 patch 设计 | 003 完成 |
| `005_memory_manager_negative_review_tab.md` | autowriter UI patch 设计 | 003 完成 |
| `006_backfill_tv_synced_user_id.sql` | 把历史 TV-synced batches/items 的 user_id 改回 projects.owner_id (audit 2026-05-21 RLS 修复) | 002 完成 + truth-vault sync 脚本已升级到 resolve_aw_project_owner |
| `007_fresh_install_autowriter_schema.sql` | 在共享 Supabase 上**从零创建** autowriter schema + 8 张表 + RLS + grants + RPC (含 TV 集成列, 跑完无需 002/003) | 仅场景 C：共享 Supabase 上从来没装过 autowriter，数据要么是空, 要么后续从老 Supabase 通过 `scripts/migrate_autowriter_across_supabase.py` 迁过来 |
| `008_jobs_table.sql` | R-018: persistent job queue 替代 _queue_worker / _quick_gen_worker daemon thread (Sprint 2+) | 001 + 002 完成 |
| `RUNBOOK.md` | 本文件 | — |

R-017 / R-018 worker process 代码 / R-020 文件拆分方案见 truth-vault
`docs/10-sister-repo-followups.md`.

## 场景判断

**场景 A · autowriter 当前在共享 Supabase 的 public schema (老部署)**:
- 需要把 5 张表 schema-rename + 加 TV 列
- 跑 001 → 002 → 003
- 需要协调 autowriter 维护者 (停机或读写分离窗口)

**场景 B · autowriter 已经在共享 Supabase 的 autowriter schema (或新部署)**:
- 只需加 sync 所需列
- 跳过 001, 直接跑 002 → 003

**场景 C · autowriter 在独立 Supabase project, 现在要合并到共享 Supabase (2026-05-21 起的默认推荐路径)**:
- 跑 007 在共享 Supabase 上从零建好 autowriter schema (包含 TV 集成列, 等价于 002+003 baked-in)
- 用 `truth-vault/scripts/migrate_autowriter_across_supabase.py` 跨 project 迁数据
- 切 autowriter 部署的 `SUPABASE_URL` 指向共享 project
- 完整步骤见 `truth-vault/MIGRATION_PLAN.md` Step 4

确认场景:
```sql
-- 在共享 Supabase 上跑 (truth_vault schema 所在地)
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_name IN ('projects', 'batches', 'items', 'versions', 'memories')
  AND table_schema IN ('public', 'autowriter');
```
- 共享 Supabase 看到 5 张表都在 `public` → 场景 A (跑 001-003)
- 共享 Supabase 看到 5 张表都在 `autowriter` 但缺 TV 列 → 场景 B (跑 002-003)
- 共享 Supabase 没看到这 5 张表 + 你有另一个 Supabase project 跑着 autowriter → 场景 C (跑 007 + 迁数据脚本)

## 部署步骤 (场景 A)

### Step 0 · 备份

```bash
pg_dump <old_autowriter_db> > autowriter_backup_$(date +%Y%m%d).sql
```

### Step 1 · 共享 Supabase 已就绪

- 已建 truth_vault schema (跑 truth-vault/schemas/notes_v1_2.sql)
- 已有 sanshengliubu 在 public schema

### Step 2 · 把 autowriter 数据 dump → restore 到共享实例 public schema

(略, 标准 pg_dump / pg_restore. 注意 RLS policy 跟 GRANTS 一起带过去.)

### Step 3 · 跑迁移

```bash
PGPASSWORD=<service_password> psql -h <shared_supabase_host> -U postgres \
    -d postgres -f 001_create_autowriter_schema.sql
psql ... -f 002_add_external_source.sql
psql ... -f 003_add_example_label_proposal.sql
```

### Step 4 · Supabase Dashboard 暴露 autowriter schema

Settings → API → Exposed schemas → 添加 `autowriter` (默认只有 public).
不加这一步, PostgREST 永远返回 404, sync 脚本会启动失败.

### Step 5 · 改 autowriter codebase

把 `db.get_client()` 改成:
```python
from supabase.client import ClientOptions
client = create_client(URL, KEY, ClientOptions(schema='autowriter'))
```

这样 36 个 `client.table('items')` 调用透明指向 `autowriter.items`, 不用
逐个加 `.schema('autowriter')`.

### Step 6 · 校验

```sql
-- 表都在 autowriter schema
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'autowriter'
ORDER BY table_name;
-- 应返回: batches, items, memories, projects, versions

-- items 多了两列
SELECT column_name FROM information_schema.columns
WHERE table_schema = 'autowriter' AND table_name = 'items'
  AND column_name IN ('external_source', 'external_source_id',
                      'example_label_proposal');
-- 应返回 3 行

-- partial UNIQUE index (2026-05-21 后改为 per-user)
SELECT indexname FROM pg_indexes
WHERE schemaname = 'autowriter'
  AND indexname IN ('items_external_source_per_user_uniq', 'items_proposal_idx');
-- 应返回 2 行. 如果还看到 'items_external_source_uniq' (旧的全局名)
-- 需要重跑 002_add_external_source.sql 让自愈 DROP 生效.
```

### Step 7 · 跑 TV sync dry-run

```bash
cd truth-vault/scripts
python sync_truth_vault_baokuan_to_autowriter_items.py --dry-run --limit 5
```

应该看到 `Found N baokuan pending sync` + `would insert item X for note Y` 日志,
不报 404 / FK 错误.

## 部署步骤 (场景 B)

跳过 Step 2, 跑 002 + 003. 其余同上.

## Auth / RLS 注意

autowriter 的 RLS policy 形如:
```sql
CREATE POLICY items_owner ON autowriter.items
    FOR ALL USING (auth.uid() = user_id);
CREATE POLICY batches_owner ON autowriter.batches
    FOR ALL USING (auth.uid() = user_id);
```

TV sync 脚本用 service_role key 绕过 RLS **写入**, 但 autowriter app
读取时用普通用户 JWT, 还是会经过 RLS. 这意味着:

- ✅ **正确**: TV sync 把 batches/items.user_id 写成
  `autowriter.projects.owner_id` (即项目负责人的 auth.users.id)
  → 项目负责人登录后看到自己项目里的 TV-synced positive examples
  → list_example_items() 拿得到 → build_system_prompt() 注入 → 飞轮转

- ❌ **错误 (2026-05-21 audit 前的写法)**: TV sync 写
  `AUTOWRITER_SYNC_USER_ID` (一个独立 service account UUID)
  → 项目负责人 auth.uid() 不匹配 → RLS 屏蔽 → list_example_items
  永远返回 0 行 → autowriter prompt 拿不到 TV 样本 → **飞轮静默断开**

新部署不需要再配 `AUTOWRITER_SYNC_USER_ID`. sync 脚本会自动查
`autowriter.projects.owner_id` 做 user_id. 仅当 owner_id 异常缺失
(违反 NOT NULL) 时, 配了 `AUTOWRITER_SYNC_USER_ID` 会作为兜底降级
(并发出 warning, items 仍对 owner 不可见, 必须手动修复 owner_id 后
重跑 sync).

历史 TV-synced rows 的 user_id 错配需要跑 `006_backfill_tv_synced_user_id.sql`.

跨 schema **写入** (truth-vault sync 写 autowriter 表) 仍必须用
`SUPABASE_SERVICE_ROLE_KEY`, 不能用 anon (anon 没有跨 schema 写权限).

## 回滚

回滚仅适用于失败 dry-run 后的清理, 不要在已有生产数据时回滚.

```sql
-- 003 回滚
DROP INDEX IF EXISTS autowriter.items_proposal_idx;
ALTER TABLE autowriter.items DROP COLUMN IF EXISTS example_label_proposal;

-- 002 回滚
DROP INDEX IF EXISTS autowriter.items_external_source_per_user_uniq;
DROP INDEX IF EXISTS autowriter.items_external_source_uniq;  -- 老版本可能还在
ALTER TABLE autowriter.items DROP COLUMN IF EXISTS external_source_id;
ALTER TABLE autowriter.items DROP COLUMN IF EXISTS external_source;

-- 001 回滚 (危险, 会把所有 autowriter 表移回 public)
-- 不推荐. 如果真要回滚, 用备份 restore.
```

## 故障排查

| 现象 | 原因 | 修复 |
|---|---|---|
| sync 报 `relation "items" does not exist` | autowriter schema 没在 Exposed schemas | Dashboard → Settings → API 加 autowriter |
| sync 报 `permission denied for table items` | 用了 anon key | .env 改 SERVICE_ROLE_KEY |
| `duplicate key value violates ... items_external_source_per_user_uniq` | sync 在跑, 这是预期的幂等机制 (autowriter 2026-05-21 改成 per-user index) | 日志应是 INFO 'Already synced (external_source_id=X)' |
| 还看到 `items_external_source_uniq` (旧全局名) | 旧 PR 版 002 跑过, 但 autowriter 升级 / 重跑 002 之前 | 重跑 `002_add_external_source.sql` (自愈 DROP 旧 + 重建 per-user); 或启动新版 autowriter app, db.py bootstrap 会代劳 |
| `column external_source does not exist` | 002 没跑 | 跑 002 |
| autowriter UI 不显示 negative review tab | 003 跑了但 UI 还没接 | UI 工作另起 (本包不含) |
