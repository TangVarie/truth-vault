# 特征抽取失败恢复（v1.26，D-153）

特征脚本（`scripts/annotate_feature_pass.py`）用 `schemas/notes_v1_26_feature_failure_recovery.sql` 建的一张队列表和三个函数。迁移由 owner 在 SQL editor 跑，什么时候跑都行；没跑之前 worker 喊一次 warning，照 v1.26 之前的办法抽，features-sync 收尾在 run 页面上打一条「迁移还没跑 (notes_v1_26)」。迁移本身不调模型、不删已有答案。

## 什么算失败，什么算完成

- 一组题里至少有一道有效答案，记 `groups_ok`；一道都没有，记 `groups_invalid`。`Done:` 行里有 `answered`、`invalid`、`model_valid_rate`。
- **问了模型、整篇一条有效的模型答案都没有**：不写答案、不写完成标记，进队列记一次失败，这一趟退出非零（`model_no_valid`）。没有正文或标题、本来就没有题可问的篇不算；个别题是空的照旧（D-083）。
- 接口报错、写库被拒：和以前一样算这一篇没成，下一趟整篇重跑。它们**不记失败次数**。
- 队列里现在不能抽的篇分两种：还在等待期的（`retry_deferred`）和已隔离的（`retry_quarantined`）。它们是存量，只在 `Done:` 行里报数，**不让这一趟变红**。`count_unannotated_features.py` 不把它们算进「还能抽几篇」，所以只剩存量时夜跑不会去叫 worker；存量由 `feature_recovery_report.py` 在夜跑收尾报一条 warning。

## 重试的次数和间隔

调模型之前，worker 先在库里给这一篇占位。占位是一个约 20 小时的租约，**不记次数**：进程中途被杀，租约到期后下一趟自己会再认领。

只有「问了模型、整篇零有效」记次数：

| 第几次失败 | 之后 |
|---|---|
| 第 1 次 | 等约 20 小时（夜跑每 24 小时一趟，下一晚轮得到） |
| 第 2 次 | 等约 44 小时（隔一晚的那一趟轮得到） |
| 第 3 次 | 隔离，不再自动抽 |

接口报错、写库被拒、卫生断言没过：当场放开占位，次数不变，下一趟照常重试。中转站连挂几晚不会把好好的篇隔离掉。占位那一下本身没成（库抖了一下、超时）也一样：只跳过那一篇，不调模型、不记次数，这一批剩下的照常抽；整批都占不上才判红。

同一篇同一时间只有一个 worker 能占位；每次占位有自己的令牌，晚到的旧请求改不了新一次的状态。

## 换过模型名

夜跑判断「跑过没有」时认所有 `llm:` 开头的标签（GitHub 这边和 worker 那边配的模型名可能不一样，生产也换过模型）。队列跟着同一个口径：

- 一篇抽成功时，这一篇同一题库、同一 run_tag 下**所有 `llm:` 标签**的队列行一起清掉。迁移导入的历史行挂在当时的模型名下，不这样清，这些篇会每晚被重抽。
- 一篇在队列里有几行时取最严的状态：任何一行隔离了，这一篇就算隔离，换模型名不会让它自动再抽。

## 隔离之后怎么重抽

修好模型或中转站之后，对**点名的篇**显式重放一次：backfill-features 工作流填 `note_ids`、勾 `reannotate`；或者本地：

```bash
python scripts/annotate_feature_pass.py PROJECT --note-ids NOTE_ID --model MODEL --reannotate --limit 1
```

这是操作说明，不是部署时自动执行的命令。重放要花模型钱；成了清队列，没成还是隔离。查队列只需要 note_id、标签、题库 sha、次数和错误类型，里面没有正文。

## 保护旧答案

`write_feature_answers_preserving_valid` 在数据库的 `ON CONFLICT` 里判断：新答案是空的，就不盖库里已有的有效答案；新答案有效，照常替换。判断和写入是同一条语句。留下来的旧行带的还是旧的 `bank_sha256` / `extracted_at`，不会被说成这一趟测的。三个函数只给 `service_role`。

## 历史数据

迁移会把历史上「整篇模型题全是空、却留着完成标记」的篇排进队列（次数从 0 算）。不排的：本来就没题可问的；同一题库下已经有别的 `llm:` 标签答出来过的（所以重跑迁移不会把抽成的篇再排一次）。排进去的篇之后几晚各重抽一次，受每晚每项目的上限管。

## 本地验证

- `python scripts/check_feature_failure_recovery.py`：真的 `main()`，假的库和模型。
- `python scripts/check_feature_batch_loop.py`：features-sync 那段 shell，加 backfill-features 两个循环的接线。
- `scripts/check_feature_failure_recovery.sql`、`scripts/seed_feature_recovery_legacy.sql` + `scripts/check_feature_failure_recovery_legacy.sql`：只给本地一次性的测试库用，不要指向生产。
- 原有的 `check_feature_orchestration.py`、`check_feature_parse.py`、`check_gateway_filter.py` 照常要过。
