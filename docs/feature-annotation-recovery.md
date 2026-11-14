# 特征抽取失败恢复（F03）

特征脚本使用 `schemas/notes_v1_26_feature_failure_recovery.sql` 的失败队列及三个 RPC。先审核并应用迁移，再部署 worker / 使用新版脚本；缺表或 RPC 时明确报迁移名称并失败，不能静默退回旧的完成判据。迁移不调模型、不会删除已有答案；把历史上模型答案全为 NULL、仍留有完成标记的快照导入队列，排除“正文太短”等真实不适用情况。

## 完成和失败

- 每组至少有一道有效答案才计 `groups_ok`；全部无效计 `groups_invalid`。`Done` 同时给出 `answered`、`invalid`、`model_valid_rate`。
- 实际问过模型、但整篇没有一条有效模型答案：不写答案/完成标记，脚本退出非零。没有可问的问题不算模型坏回复；零星 NULL 仍保留 D-083 的语义。
- API/写库失败仍非成功。失败预留状态在库里，不能靠重启 worker 清掉重试上限。原 JSONL 只作为本地诊断副本，恢复不依赖它。
- 队列中仍在退避或已经隔离的项目会明确报 `retry_deferred` / `retry_quarantined`，退出非零。这是“没有完成”，不是成功的空跑。`count_unannotated_features` 仍把这些篇计为未解决；工作流自身的两轮无进展保护可停止重复探测，重复探测不再调用模型。

## 自动重试与显式重放

开模型调用之前，数据库原子预留一次尝试。首次失败等至少24小时；第二次失败再等48小时；第三次失败隔离，后续定时任务不再付费重试。进程在调用期间被杀也消耗这次预留，避免崩溃导致无限付费。

排查并修好模型/网关后，用现有 backfill / 本地脚本对**指定篇**显式重放一次，例如：

```bash
python scripts/annotate_feature_pass.py PROJECT --note-ids NOTE_ID --model MODEL --reannotate --limit 1
```

这是操作说明，不是部署时应自动执行的命令。重放会花模型费，应在既有操作授权范围内进行；失败仍保留隔离，成功后才清掉队列。变更模型/题库产生独立快照，不修改旧快照答案。查询失败队列只需 ID、抽取器、题库 SHA、尝试次数和错误类型，不包含客户原文或回复。

同一快照并发预留只允许一个自动尝试；每次预留有独立令牌。旧请求的迟到结果不能清掉新尝试的恢复状态，即使旧队列行曾删除再重建。显式重放可绕过退避，因此仍应逐篇提交，不并发重放同一快照。

## 保护旧答案

`write_feature_answers_preserving_valid` 在数据库 `ON CONFLICT` 内决定：新答案为 NULL 时不能盖掉旧非 NULL 答案；新有效答案可正常替换。判断与写入在同一语句中，不能被“先读后写”的并发窗口绕过。RPC 仅给 `service_role`，固定 `search_path`，不开放给 anon/authenticated。

若某题本次无效、但库里保留了上一轮有效答案，保留的整行仍带旧的 `bank_sha256` / `extracted_at`，不会把旧答案伪装成本轮重新测得。整篇全无效时连部分覆盖都不做。

## 本地验证

- `python scripts/check_feature_failure_recovery.py`：真实 `main` / 解析器连跑，坏回复不盖标记、第二轮不付费、三轮封顶、显式恢复、历史 NULL 标记、缺迁移拒跑。
- `psql -v ON_ERROR_STOP=1 < scripts/check_feature_failure_recovery.sql`：仅供本地测试库，验证原子预留/旧令牌无效/封顶/恢复/NULL 保护/权限，夹具事务回滚。
- 原有 `check_feature_orchestration.py`、`check_feature_parse.py`、`check_gateway_filter.py` 应继续通过。不得把本地测试库命令指向生产。
