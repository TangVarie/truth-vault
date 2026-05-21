# Supabase 合并迁移计划 (2026-05-21)

> Truth Vault 飞轮上线阻塞项的解封工作。把分散在两个 Supabase project 的
> autowriter / sansheng 数据，合并到一个共享 project 的不同 schema 里，
> 让 D-024 设计能真正生效。

## 背景：架构和现实不一致

**TV 设计假设**（D-024，docs/09-system-integration.md）：

```
共享 Supabase project
├── public schema       → sanshengliubu 表 (projects, pipeline_runs, ...,  reference_samples)
├── autowriter schema   → autowriter 表 (projects, batches, items, versions, ...)
└── truth_vault schema  → TV 自有表 (projects, notes, accounts, ...)
```

**实际状态**（截至 2026-05-21）：

```
xhs-workstation (vnbcytilakkxojhgzeqr, ap-south-1)
└── autowriter schema → 40 projects / 460 batches / 3621 items / 4321 versions / 257 memories / ...

三省六部-workstation (kduysqedrclrfevrxiie, ap-southeast-1)
└── public schema → sansheng 表 (0 rows, fresh deploy)
```

两个 project 跨 cluster 不能 JOIN，结果：

- `truth_vault/schemas/notes_v1_2_cross_schema_views.sql` 里的 `v_prompt_performance`
  / `v_model_comparison` / `v_autowriter_positive_pool_saturation` 没法部署
- `truth-vault/scripts/_common.py::get_supabase_client()` 设计为单连接
  `.schema('autowriter')` / `.schema('public')` 切换，跨 project 直接断
- 两个 sync 脚本（通道 1 写 sansheng / 通道 2 写 autowriter）失效

## 决策：合并到三省六部 project

选项对比（详见 truth-vault/DECISIONS.md 后续追加的 D-037）：

| 选项 | 数据迁移量 | 维护成本 | Region |
|---|---|---|---|
| **A. 合并到三省六部 project ⭐** | autowriter 单向 8750 行 → 三省六部 | 最低（D-024 原设计零改动） | ap-southeast-1（新加坡，更靠近国内） |
| B. 合并到 xhs project | sansheng 5 张空表 + truth_vault schema → xhs | 低 | ap-south-1（孟买，更远） |
| C. 新建第三个共享 project | 双向迁移 | 中（两边都搬） | 重新选 |
| D. 保持两 project，改 TV 仓库支持多连接 | 0 行数据 | 高（TV sync 脚本 + cross-schema views 全改） | — |

**选定 A**。理由：

1. **数据完整性**：sansheng 那边目前 0 行（fresh deploy），所有真实数据都在
   autowriter 侧。单向迁移 + 严格行数对账，回滚路径是"目标库 TRUNCATE 重跑"。
2. **维护优雅**：TV sync 脚本 / cross-schema views 全部按 D-024 原设计落地，
   未来开发人员看 truth-vault/docs 完全自洽，不需要"特殊情况要绕开"。
3. **操作干净**：迁完后 xhs-workstation project 可以 pause 做兜底回滚，
   不删数据；2 周观察期后归档。单一真实数据源。
4. **物理就近**：ap-southeast-1（新加坡）对国内用户延迟比 ap-south-1（孟买）
   小 50-80ms，autowriter 用户体验改善。

## 状态追踪 · 已完成的步骤

### ✅ Step 1. 在三省六部 project 上创建 autowriter schema

- 文件：`autowriter-migrations/007_fresh_install_autowriter_schema.sql`
- 跑法：`apply_migration` via Supabase MCP（已执行 2026-05-21）
- 校验：8 张表（projects/batches/items/versions/memories/calibration_note_audit/
  batch_metrics/user_logins）+ RLS policy + per-user unique index +
  pgvector 扩展 + batch_item_counts RPC，全部就位
- 与 002/003 关系：007 是"场景 C · 共享 Supabase 全新建"路径；001（场景 A，
  从 public 迁移）+ 002（external_source 列）+ 003（example_label_proposal）
  对已存在 autowriter 部署仍然适用，不冲突

### ✅ Step 2. 在三省六部 project 上创建 truth_vault schema

- 文件：`schemas/notes_v1_2.sql`（修复了 search_path 不包含 extensions
  导致 `uuid_generate_v4()` 找不到的问题）
- 校验：14 张表（projects/accounts/account_snapshots/notes/metric_snapshots/
  posthoc_analyses/prepublish_evaluations/quality_review_decisions/comments/
  notes_archive/audience_calibrations/undeclared_fields_quarantine/note_features/
  audit_log）+ 7 个内部 view + 2 个 trigger function

### ✅ Step 3. 跑 cross-schema views

- 文件：`schemas/notes_v1_2_cross_schema_views.sql`
- 校验：v_prompt_performance / v_model_comparison /
  v_autowriter_positive_pool_saturation 全部建好

## 还需要做的 · 由 operator 完成

### 🔜 Step 4. 数据迁移：xhs-workstation → 三省六部.autowriter

需要 operator 手动跑一次，因为脚本要 service_role key（敏感凭据，
不能落到 MCP/CI 里）。

#### 4.1 准备凭据

Supabase Dashboard → 两个 project 都取一次：
- `Settings → API → Project URL`
- `Settings → API → service_role secret`（**不是 anon**！）

#### 4.2 设置环境变量

```bash
# 源（autowriter 数据所在地）
export AW_MIGRATE_SRC_URL='https://vnbcytilakkxojhgzeqr.supabase.co'
export AW_MIGRATE_SRC_KEY='sb_secret_... 或老 JWT'   # service_role key

# 目标（D-024 共享 Supabase）
export AW_MIGRATE_DST_URL='https://kduysqedrclrfevrxiie.supabase.co'
export AW_MIGRATE_DST_KEY='sb_secret_... 或老 JWT'   # service_role key
```

#### 4.3 干跑校验

```bash
cd truth-vault
pip install -r scripts/requirements.lock  # supabase-py 等
python scripts/migrate_autowriter_across_supabase.py --dry-run
```

预期输出（行数对账，写入 0 行）：

```
[projects]              src=40    dst(before)=0    dst(after)=0    delta=0    ✅
[batches]               src=460   dst(before)=0    dst(after)=0    delta=0    ✅
[items]                 src=3621  dst(before)=0    dst(after)=0    delta=0    ✅
[versions]              src=4321  dst(before)=0    dst(after)=0    delta=0    ✅
[memories]              src=257   dst(before)=0    dst(after)=0    delta=0    ✅
[calibration_note_audit] src=37    dst(before)=0    dst(after)=0    delta=0    ✅
[batch_metrics]         src=12    dst(before)=0    dst(after)=0    delta=0    ✅
[user_logins]           src=2     dst(before)=0    dst(after)=0    delta=0    ✅
```

#### 4.4 真跑

```bash
python scripts/migrate_autowriter_across_supabase.py
```

预期 5-10 分钟（取决于跨 region 延迟）。脚本会按 FK 依赖顺序分批迁移
（projects → batches → items → versions → memories → calibration_note_audit
 → batch_metrics → user_logins），每张表迁完立即校验 src vs dst 行数。

任何 delta ≠ 0 的表都会被标 `⚠️`，integration 不算完成。

#### 4.5 切换 autowriter 应用配置

autowriter 的部署位置（Streamlit Cloud / Railway / 自托管）的 secrets：

```toml
# 旧
SUPABASE_URL = "https://vnbcytilakkxojhgzeqr.supabase.co"
SUPABASE_ANON_KEY = "..."  # xhs-workstation anon key

# 新
SUPABASE_URL = "https://kduysqedrclrfevrxiie.supabase.co"
SUPABASE_ANON_KEY = "..."  # 三省六部 anon key
```

同时确认 `Settings → API → Exposed schemas` 已包含 `autowriter`
（PostgREST 才会暴露这些表，否则 autowriter app 启动 404）。

#### 4.6 (可选) 第三方部署 .env 更新

如果有 CI / cron job 用同一套 SUPABASE_URL，记得一并改。

#### 4.7 兜底回滚窗口

`xhs-workstation` project pause 但不删，留 2 周观察期。任何 autowriter
异常都可以 `Settings → Pause project 切回` 临时恢复。2 周后归档（保留
project 不动，仅 DELETE 数据）或彻底删 project。

### 🔜 Step 5. 启动飞轮（取决于 TV notes 有数据）

数据迁移完成后，开飞轮：

```bash
# 1. 同步飞书原始 notes 到 truth_vault
python scripts/sync_feishu_notes_to_truth_vault.py --project NUC_phase1

# 2. 同步爆款到 sansheng（通道 1）
python scripts/sync_truth_vault_baokuan_to_sanshengliubu.py

# 3. 同步爆款到 autowriter（通道 2）
python scripts/sync_truth_vault_baokuan_to_autowriter_items.py
```

3 个脚本都用同一个 `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` env var
（指向三省六部 project）。详见 `docs/09-system-integration.md`。

## 监控

完成后，跑 `scripts/verify_supabase_state.sql` 在三省六部 project 上应该
全 ✅（A/B/C/D/E 五段都通过）。这个 SQL 是单文件自检，operator 重跑无成本，
未来 onboarding 新人也用它做"我接手时 Supabase 配齐了吗"的体检。

## 风险记录（追加到 RISKS.md）

| ID | 风险 | 现状 | 缓解 |
|---|---|---|---|
| R-xx | 数据迁移漏行 | 行数对账 ✅ 兜底；服务窗口期人工抽样核查 5-10 条 | 脚本内置 src/dst count 对账 |
| R-xx | autowriter app 切配置失败 | 旧 project pause，可回滚 | 2 周观察期 + DNS-free 切换 |
| R-xx | RLS user_id ≠ owner_id（D-024 audit 已修） | 跨 schema 迁移不涉及 RLS 重建 | 006_backfill_tv_synced_user_id.sql 已修历史数据；新 sync 用 owner_id |

## 决策记录

完成后追加到 DECISIONS.md 作为 D-037（"合并 autowriter 到三省六部 project
以恢复 D-024 共享 Supabase 设计"）。
