# sanshengliubu-patches/

Truth Vault 通道 1 集成 patch 包. 部署到 sanshengliubu 仓库 / Supabase 实例.

## 内容

| 文件 | 用途 | 必做? |
|---|---|---|
| `001_add_source_tv_note_id.sql` | 给 `public.reference_samples` 加 `source_truth_vault_note_id` 列 + **partial UNIQUE** 索引 | ⭐ **必做前置** |
| `002_widen_pack_filter_backfill.sql` | 把旧 source_type='truth_vault_sync' 行回填成 'pack' | 老库迁移用 |
| `003_strengthen_tv_note_id_unique.sql` | 把老 (普通 INDEX) 升级成 **partial UNIQUE** | 老库 (装过老版 001) 必做 |
| `004_jobs_table.sql` | R-018: persistent job queue 替代 pipeline orchestrator daemon thread | Sprint 2+ |
| `005_multi_tenant_workspaces.sql` | R-019 Option B: workspaces + workspace_users + RLS policies | 多租户场景才跑 |
| `import_truth_vault_baokuan.py` | sanshengliubu 自有工具用的 helper (列名 + quality_score 计算) | 可选 |
| `README.md` | 本文件 | — |

R-018 (worker process 代码) 和 R-019 决策树详细方案见 truth-vault
`docs/10-sister-repo-followups.md`.

## 部署顺序

1. **跑 001_add_source_tv_note_id.sql** (幂等, 重复执行不报错)
   - psql / Supabase SQL Editor 均可
   - 执行后 `public.reference_samples` 多一列 `source_truth_vault_note_id TEXT`
   - **2026-05-22 audit P1-3** 起, 这个 patch 写入 `idx_reference_samples_tv_note_id_unique`
     (partial UNIQUE). 不跑这一步, truth-vault/scripts/sync_truth_vault_baokuan_to_sanshengliubu.py
     的 `preflight_check()` 会立刻报错; 全量 sync 不会开始
2. **老库特别注意 (升级路径)**: 如果你之前装过 001 的老版本 (只有普通 INDEX 不带 UNIQUE),
   跑 `003_strengthen_tv_note_id_unique.sql` 把约束升级. 如果库里已经因为旧并发跑出
   过重复行, 003 会拒绝执行并列出重复 ID, 让你手工 dedupe 后再跑.
3. **多租户场景** (sanshengliubu fresh schema 关 RLS, 见 audit P2-6): 跑 002 把
   旧 source_type 回填后, 评估是否需要在 ssll 仓库自己开 RLS policy. TV sync 用
   service_role 不受影响.
4. (可选) 把 `import_truth_vault_baokuan.py` 内的 `build_pack` 方法整合进
   sanshengliubu 的 `db/supabase_client.py`. 不做的话生产飞轮闭环也工作,
   sync 是 truth-vault 仓库脚本直接跨 schema 写入.

## 注意事项

- 列名 / 类型 / 索引以本目录为准. 如果 sanshengliubu 后续重命名列, 必须
  同步更新 `truth-vault/scripts/sync_truth_vault_baokuan_to_sanshengliubu.py:
  build_reference_sample` + `preflight_check` + `docs/09-system-integration.md`
  数据映射表.
- `source_truth_vault_note_id` 是 TEXT 不是 UUID, 因为
  `truth_vault.notes.note_id` 规则为 `f"{project_id}_{feishu_record_id}"`.
- sanshengliubu 留在 `public` schema (D-024), 不要把它移到 `sanshengliubu`
  schema; 现有部署的 RLS / pipeline 都假设它在 public.

## 回滚

如果需要回滚 (不推荐):

```sql
DROP INDEX IF EXISTS public.idx_reference_samples_tv_note;
DROP INDEX IF EXISTS public.idx_reference_samples_tv_note_id_unique;
ALTER TABLE public.reference_samples DROP COLUMN IF EXISTS source_truth_vault_note_id;
```

回滚后 Truth Vault 通道 1 sync 会无法启动. 不要在生产数据上回滚.
