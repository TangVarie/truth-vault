# truth-vault/scripts/

Truth Vault 飞轮的 6 个真实可跑 Python 脚本（+ `_common.py` 共享工具）。

## 概览

```
scripts/
├── _common.py                                          共享工具（client / mapping loader / pagination）
├── sync_feishu_notes_to_truth_vault.py                 飞书 → TV (periodic)
├── sync_comments_from_raw_extra.py                     comment 文本块 → truth_vault.comments (post-sync)
├── annotate_essence_pass.py                            Mode A essence/audience LLM 标注 (independent pass)
├── sync_truth_vault_baokuan_to_sanshengliubu.py        TV 爆款 → ssll (periodic)
├── sync_truth_vault_baokuan_to_autowriter_items.py     TV 爆款 → autowriter (periodic)
├── extract_negative_examples_from_autowriter.py        autowriter 历史挖 negative (one-shot)
├── requirements.txt                                    依赖
├── .env.example                                        环境变量模板
└── README.md                                           本文件
```

## 数据流图

```
飞书多维表格 ──[1]──► truth_vault.notes ──[2]──► public.reference_samples
                            │     ▲              (sanshengliubu / vibe_rewriter)
                            │     │
                            │   [5,6] enrichment
                            │     │
                            │     └─ truth_vault.comments / essence/audience fields
                            │
                            └──[3]──► autowriter.items
                                      (example_label='positive')

[1] sync_feishu_notes_to_truth_vault.py          每日 cron
[2] sync_truth_vault_baokuan_to_sanshengliubu.py  每日 cron 或 [1] 跑完后触发
[3] sync_truth_vault_baokuan_to_autowriter_items.py 同上
[5] sync_comments_from_raw_extra.py               [1] 跑完后跑 (落 comments 表)
[6] annotate_essence_pass.py                      独立 LLM pass, D-028 不在 [1] 内

(单独的反向通道)
autowriter 历史 items ──[4]──► autowriter.items.example_label_proposal
                              (待人工 review → example_label='negative')

[4] extract_negative_examples_from_autowriter.py  一次性, NUC pilot 期间跑
```

注意 [5] 和 [6] 的顺序很重要：
- [6] 必须在 [1] 之后单独跑（D-028 要求 LLM 标注绝不和 tier 抽取共进程）。
- [5] 可以在 [1] 之后随时跑，但晚于 [6] 会让 ssll 拿到带 essence 标注但
  无 comments 的 reference pack（vibe_rewriter 的评论证据缺失但 essence
  分析正确）；如果 [5] 先跑则反过来。两者交错并不冲突。

## 安装

```bash
cd truth-vault/scripts
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 填入真实凭证
```

## 运行（按顺序）

### 第一次部署（Sprint 0 工程实施）

```bash
# Step 1: 共享 Supabase 已就绪（autowriter schema 已迁移，truth_vault schema 已建表）
# Step 2: sanshengliubu 已部署，include import_truth_vault_baokuan 方法

# Step 3: 拉飞书数据进 TV（按项目逐个跑）
python sync_feishu_notes_to_truth_vault.py NUC_phase1 --dry-run    # 先 dry-run 看是否报错
python sync_feishu_notes_to_truth_vault.py NUC_phase1              # 实跑

# Step 4: 把 TV 爆款喂给 sanshengliubu
python sync_truth_vault_baokuan_to_sanshengliubu.py --dry-run
python sync_truth_vault_baokuan_to_sanshengliubu.py

# Step 5: 把 TV 爆款喂给 autowriter
python sync_truth_vault_baokuan_to_autowriter_items.py --dry-run
python sync_truth_vault_baokuan_to_autowriter_items.py

# Step 6: 一次性从 autowriter 历史挖 negative 候选
python extract_negative_examples_from_autowriter.py --dry-run
python extract_negative_examples_from_autowriter.py
```

### 日常运维（每日）

把 step 3-5 放进 cron / GitHub Actions：

```bash
#!/bin/bash
# /etc/cron.daily/truth-vault-sync
set -e
cd /opt/truth-vault/scripts
source venv/bin/activate

# Source .env safely (handles comments and blank lines, unlike
# `export $(cut -d= -f1 .env)` which would try to export comment lines).
set -a              # auto-export every variable that gets defined
source .env
set +a

# Step 1: feishu → TV (主链路)
for project in NUC_phase1 NRT_phase2 NRT_phase3; do
    python sync_feishu_notes_to_truth_vault.py "$project"
done

# Step 2: comments 解析（独立，不阻塞主链路）
for project in NUC_phase1 NRT_phase2 NRT_phase3; do
    python sync_comments_from_raw_extra.py "$project"
done

# Step 3: essence/audience LLM 标注（独立 D-028 pass，按预算调 --limit）
for project in NUC_phase1 NRT_phase2 NRT_phase3; do
    python annotate_essence_pass.py "$project" --limit 50
done

# Step 4: TV → 双通道
python sync_truth_vault_baokuan_to_sanshengliubu.py
python sync_truth_vault_baokuan_to_autowriter_items.py
```

## 幂等性保证

所有脚本都设计为可重复运行，重跑不会重复插入：

| 脚本 | 幂等机制 |
|---|---|
| sync_feishu_notes_to_truth_vault.py | `notes.note_id` PRIMARY KEY = `{project_id}_{feishu_record_id}`，UPSERT |
| sync_truth_vault_baokuan_to_sanshengliubu.py | 优先查 `reference_samples.source_truth_vault_note_id` (干净的索引列, 由 001_add_source_tv_note_id.sql 加)；老 row 没填这列时 fallback 查 `ai_analysis->>'_truth_vault_note_id'` JSON 路径 |
| sync_truth_vault_baokuan_to_autowriter_items.py | `items.external_source_id` partial UNIQUE INDEX，INSERT 重复返回 23505 → skip |
| extract_negative_examples_from_autowriter.py | 只覆盖 `example_label_proposal IS NULL AND example_label IS NULL` 的 item |

## 安全

- 所有脚本必须用 `SUPABASE_SERVICE_ROLE_KEY`（RLS bypass）。`_common.py` 的 `get_supabase_client()` 启动时会做一个非严格的 anon key 检测，发现可疑值会立即抛错。
- `.env` 不要 commit；CI/CD 用 secrets manager 注入。
- service_role 不能进任何前端 / 用户浏览器 / Streamlit 公开页。只在后台 worker / cron / GitHub Actions 用。
- 飞书 app_id/app_secret 同上。

## 调试 / 故障排查

| 报错 | 原因 | 修复 |
|---|---|---|
| `relation "items" does not exist` | TV sync 写 autowriter 时没用 `.schema('autowriter')` | 检查代码是否漏了 `.schema()` 调用 |
| `permission denied for table xxx` | 用了 ANON_KEY 而不是 SERVICE_ROLE_KEY | 检查 .env |
| `duplicate key value violates unique constraint` | 不是 bug，是幂等机制在工作 | log 应该是 INFO 级"Already synced，skipping" |
| Feishu `code: 99991663` | tenant_access_token 失效 | 脚本会自动重试一次；如果连续失败，检查 app_id/app_secret 是否正确 |
| `mapping_to_autowriter_project_id IS NULL` | TV 项目没建立 autowriter 映射 | 手动在 truth_vault.projects 表里 UPDATE 该列 |
| Excel lineage 没出现在飞书 → TV recovery 拿不到 | 运营走的是复制粘贴而不是整表导入 | 见 docs/09-system-integration.md 的 Excel 工作流规则 |

## 测试

每个脚本都支持 `--dry-run` 模式，不会写任何数据。配合 `--limit N` 在小数据集上验证。

部署到生产前的标准流程：
1. 在 staging Supabase 上跑 `--dry-run --limit 5`
2. 看 stdout 的 stats 是否合理
3. 实跑 `--limit 5`，去数据库验证写入正确
4. 全量跑

## 已知限制

- **`sync_feishu_notes_to_truth_vault.py` 不调用 LLM**：sync 脚本只做映射 + 落 `notes` / `metric_snapshots`。对于带 `sub_directions` 的多分支方向（NUC_phase1 的 营养保健代餐 / 术后恢复），sync 仅把 `_direction_raw` 放进 `raw_extra`，由 `annotate_essence_pass.py` 同 pass 内用 LLM 选 sub_direction 并写回 `direction_subtype` + `content_format` / `target_audience` / `user_pain_point` / `product_focus`。单方向配置（糖尿病 / 抗癌放化疗）的 `content_format` 等字段在 sync 时已确定性写入，不依赖 LLM。
- **comments 评论楼层重建不在这里**：`sync_comments_from_raw_extra.py` 只解析为扁平评论；`parent_comment_id` 层级重建（D-022）是 Sprint 2 LLM 任务。
- **飞书 API 限速**：本脚本是单进程顺序读取，rate limit 友好但全量首次拉 6000+ 行可能花 5-10 分钟。
