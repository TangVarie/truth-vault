# autowriter-migrations/ RUNBOOK

Truth Vault 通道 2 集成 patch 包. 把 autowriter 从独立 Supabase 实例迁到
共享 Supabase 实例的 `autowriter` schema, 并加上 TV sync 所需的列.

## 内容

| 文件 | 用途 | 前置条件 |
|---|---|---|
| `001_create_autowriter_schema.sql` | 创建 autowriter schema + 迁移 5 张表 from public | 仅场景 A 需要 |
| `002_add_external_source.sql` | 给 items 加 external_source/external_source_id (P1 Sprint 1.1 幂等键) | 001 完成 (或 autowriter 已在独立 schema) |
| `003_add_example_label_proposal.sql` | 给 items 加 example_label_proposal (P2 negative review queue) | 002 完成 |
| `RUNBOOK.md` | 本文件 | — |

## 场景判断

**场景 A · autowriter 当前在独立 Supabase 实例 + public schema**:
- 需要把数据迁过来 + 改 schema
- 跑 001 → 002 → 003 全套
- 需要协调 autowriter 维护者 (停机或读写分离窗口)

**场景 B · autowriter 已经在共享 Supabase 的 autowriter schema (或新部署)**:
- 只需加 sync 所需列
- 跳过 001, 直接跑 002 → 003

确认场景:
```sql
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_name IN ('projects', 'batches', 'items', 'versions', 'memories')
  AND table_schema IN ('public', 'autowriter');
```

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

-- partial UNIQUE index
SELECT indexname FROM pg_indexes
WHERE schemaname = 'autowriter'
  AND indexname IN ('items_external_source_uniq', 'items_proposal_idx');
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
```

TV sync 脚本用 service_role key 绕过 RLS, 不需要改 policy. 但要确认:
1. 跨 schema 写入 (truth-vault sync 写 autowriter 表) **必须** 用
   `SUPABASE_SERVICE_ROLE_KEY`, 不能用 anon
2. AUTOWRITER_SYNC_USER_ID 指向一个真实存在的 auth.users 行
   (TV-synced items 的 owner)

## 回滚

回滚仅适用于失败 dry-run 后的清理, 不要在已有生产数据时回滚.

```sql
-- 003 回滚
DROP INDEX IF EXISTS autowriter.items_proposal_idx;
ALTER TABLE autowriter.items DROP COLUMN IF EXISTS example_label_proposal;

-- 002 回滚
DROP INDEX IF EXISTS autowriter.items_external_source_uniq;
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
| `duplicate key value violates ... items_external_source_uniq` | sync 在跑, 这是预期的幂等机制 | 日志应是 INFO 'Already synced (external_source_id=X)' |
| `column external_source does not exist` | 002 没跑 | 跑 002 |
| autowriter UI 不显示 negative review tab | 003 跑了但 UI 还没接 | UI 工作另起 (本包不含) |
