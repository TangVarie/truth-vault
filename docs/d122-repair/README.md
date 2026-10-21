# D-122 / D-123 恢复与收尾 SQL（2026-10-20）

生产库 `kduysqedrclrfevrxiie`，都在 Supabase SQL editor 整份粘贴跑。只有 SQL 和计数，没有笔记正文。背景见 DECISIONS D-122、D-123，进度见 OPEN-ITEMS I-16。

| 文件 | 干什么 | 状态 |
|---|---|---|
| `03_verify.sql` | 恢复之后回读：每格等于计划值（`truth_vault.repair_notes_essence_cols_20261020`） | 10-20 跑过：1,102/1,102 |
| `04_rollback.sql` | 恢复回滚：先只读看会回滚几格，再按备份表 `truth_vault.backup_notes_essence_cols_20261020` 回滚；恢复之后被改过、或 essence 又写过的格子不动 | 不用跑，留着备用 |
| `05_after_nightly.sql` | **第一晚核（I-16 ④）**：受保护列「非空 → NULL」的 UPDATE 应为 0（`tier` / `tier_source` 带 `tier_cleared` / `tier_unmapped` 旗子的不算），`emotional_lever` 有值而 `content_format` 为空 0 篇，恢复的格子还等于计划值。时间设成 TV#209 合并时刻 `2026-10-20 16:27 UTC` 之后那一晚 daily-sync 起跑时刻 | **待跑**（10-21 夜跑之后） |
| `d123_gate3_rescore.sql` | **I-16 ② / G-03**：备份到 `truth_vault.backup_content_scores_d122_20261020` 后删掉 80 行旧版本 `essence-v1-322f02c9465f` 的分，下一次夜跑按 `essence-v1-93035a562b2e` 重打。第 0 步只读，第 1 步一个事务、行数不对就整块回滚 | **待跑**。10-20 用 Supabase MCP 跑时卡在 app 里的确认上超时，什么都没写。不删也不影响打分（`gate3_score.py` 只读当前版本的行），但「v1 行为 0」这条核要等删完 |
