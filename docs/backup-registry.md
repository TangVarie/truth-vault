# 备份表登记册（S-02）

D-136：备份表都留着，不删；新做的备份要登记。

这里是登记册本身。`scripts/verify_supabase_state.sql` #92 数「名字像备份、却不在下表里」的表，应为 0。
大于 0 就是有人做了新备份没登记：在下表加一行（同一个 PR 里，#92 的 VALUES 列表也加同一条），不要删表。

- 「名字像备份」= truth_vault / autowriter / public 下的普通表，名字里有 `backup`，或以 `_bak_` 加四位数字开头，或以 `_` 加 8 位日期结尾。
- 规则是正则，对「schema.表名」整串匹配。CI 守卫 `scripts/check_verify_backup_registry.py` 要求下表和 #92 的列表一条不差。
- 每张表怎么回滚，写在它自己的表注释（COMMENT）里，或写在「来源」那一条记录里。
- 张数是 2026-11-25 生产只读查的，共 82 张，全部登记了。#92b（客户端角色能读写的备份表）同日是 0。
- 最后五行是批 1、批 2 的 owner SQL 会建的备份表（前三行批 1、后两行批 2），先登记；owner 跑了之后张数照括号里的变。

| 规则 | 张数 | 来源 |
|---|---|---|
| `^truth_vault\.backup_d129_ids_20261026$` | 1 | D-129 新旧 id 对照。**永久保留**：闸二和每季度找新特征按它定半区（D-128 补记） |
| `^truth_vault\.backup_(inverted_lineage\|(notes\|nfa\|comments\|metric_snapshots)_vanished)_20261009$` | 5 | 10-09 清理（D-099 / D-102 / D-103）；回滚顺序写在 `truth_vault.backup_notes_vanished_20261009` 的表注释里 |
| `^autowriter\.backup_(tv_note_links_inverted\|items_self_review\|tv_note_links_vanished)_20261009$` | 3 | 10-09 清理 |
| `^autowriter\.backup_(tv_note_links_twins\|orphan_ingest_tuge)_20261010$` | 2 | 10-10 清理 |
| `^autowriter\.backup_memory_xiwu_contam_20261012$` | 1 | 10-12 清理 |
| `^truth_vault\.(reference_samples_backup_tv_stale\|notes_ssll_marker_backup)_20261008$` | 2 | D-086（S-01） |
| `^truth_vault\.backup_quarantine_resolve_20261016$` | 1 | I-03（2,477 行原状态）。回滚：`update truth_vault.undeclared_fields_quarantine q set status=b.status, review_decision=b.review_decision, reviewed_by=b.reviewed_by, reviewed_at=b.reviewed_at from truth_vault.backup_quarantine_resolve_20261016 b where q.quarantine_id=b.quarantine_id` |
| `^truth_vault\.backup_gate3_preannotated_2026(1019\|1030)$` | 2 | G-03 闸三重标前 |
| `^truth_vault\.(backup\|repair)_notes_essence_cols_20261020$` | 2 | D-122 恢复前快照和恢复计划 |
| `^truth_vault\.backup_content_scores_d122_20261020$` | 1 | D-123 |
| `^autowriter\.backup_(global_shorten_rules\|delivery_params)_20261020$` | 2 | docs/32 §2；W-28 |
| `^autowriter\.backup_projects_default_params_20261030$` | 1 | 10-30 标归档前 |
| `^(truth_vault\|autowriter)\.backup_[a-z_]+_d129(_twins)?_20261026$` | 11 | D-129（TV 8 张、aw 3 张）；回滚写在 `truth_vault.backup_notes_d129_20261026` 的表注释里 |
| `^(truth_vault\|autowriter)\.backup_([a-z_]+_)?d129p3(_[a-z]+)?_20261027$` | 16 | D-129 第 3 段 |
| `^(truth_vault\|autowriter)\.backup_([a-z_]+_)?i25(_ids)?_20261027$` | 14 | I-25 |
| `^autowriter\._bak_1102_dup_[a-z_]+$` | 9 | W-41 重复项目并回 |
| `^autowriter\._bak_1102_novelty_rules$` | 1 | 来源没记，表上没有注释 |
| `^autowriter\._bak_1103_(spx_rules\|tuge_comment_rules)$` | 2 | 途鸽那张见 D-145；spx 那张来源没记 |
| `^autowriter\._bak_1110_tuge_(comment_rules\|default_params)$` | 2 | 11-10 途鸽评论配比改写前；回滚写在表注释里 |
| `^autowriter\._bak_1111_tuge_(comment_rules\|rule_compiles)$` | 2 | W-51 |
| `^autowriter\._bak_1113_ending_rule$` | 1 | W-56 |
| `^autowriter\._bak_1123_ending_rule_compile$` | 1 | 11-23 结尾规则重编 |
| `^truth_vault\.backup_external_publish_time_j17_20261125$` | 0（owner 跑 J-17 之后 1） | J-17 回填前的原值，`scripts/backfill_external_publish_time_j17.sql` |
| `^truth_vault\.backup_repoint_stale_(comments\|comment_judge)_20261125$` | 0（owner 跑之后 2） | AU-F02b ④ 删旧帖评论前，`scripts/cleanup_repointed_stale_comments_au_f02b.sql` |
| `^truth_vault\.backup_repoint_stale_ssll_(samples\|marks)_20261125$` | 0（owner 跑之后 2） | AU-F02b ④ 撤三省六部旧样本前，`scripts/withdraw_repointed_stale_ssll_samples_au_f02b.sql` |
| `^truth_vault\.backup_(comments\|nfa)_commenter_20261125$` | 0（owner 跑 v1_31 之后 2） | 列体检 11-25 §3a #1 删 29 行假评论和 270 行判分前的整行备份（D-175），`schemas/notes_v1_31_commenter_codes_cleanup.sql`；回滚写在表注释里 |
| `^truth_vault\.backup_notes_i17_20261125$` | 0（owner 跑 v1_33 之后 1） | I-17 换回 content_format 前，69 篇的 4 列 + 内容层 + 方向原值（D-178），`schemas/notes_v1_33_direction_switch_restore.sql`；回滚写在表注释里 |
