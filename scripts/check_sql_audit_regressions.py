"""Existing SQL migration/text invariants, extracted from CI without changing assertions.

Run from the repository root: python scripts/check_sql_audit_regressions.py.
These checks cover declared migration structure; actual SQL behavior is tested
by the PostgreSQL job rather than inferred from these string assertions.
"""
import pathlib

def text(p):
    return pathlib.Path(p).read_text(encoding="utf-8")

# COR-005: fresh install 的 batch_item_counts 清空 search_path 后必须用
# schema 限定表名, 否则运行时 relation does not exist。
f007 = text("autowriter-migrations/007_fresh_install_autowriter_schema.sql")
assert "FROM autowriter.items i" in f007, \
    "COR-005: batch_item_counts 仍用未限定的 items 表名"

# COR-010: versions 必须有 (item_id, version_num) 唯一约束。
assert "versions_item_version_uniq" in f007, \
    "COR-010: versions 缺 (item_id, version_num) 唯一索引"

# COR-019: claim 必须限制 attempts < max_attempts, 否则毒任务无限领取。
for p, name in ((text("autowriter-migrations/008_jobs_table.sql"), "008"),
                (text("sanshengliubu-patches/004_jobs_table.sql"), "004")):
    assert "attempts < max_attempts" in p, \
        f"COR-019: {name} claim_one_job 缺 attempts < max_attempts 闸"

# COR-024: publish_time 清空时 era 也要清空; 未来日期衰减夹到 [0,1]。
assert "NEW.era_tag := NULL" in text("schemas/notes_v1_2.sql"), \
    "COR-024: fill_era_tag 没有清空 era 的分支"
assert "LEAST(1.0::double precision" in text("schemas/notes_v1_4_flywheel_lesson_cards.sql"), \
    "COR-024: recency_weight 没夹到 [0,1]"

# 升级路径: 修复不能只写在历史基线(已部署环境升级时不重跑历史迁移),
# 必须有增量迁移, 且写进 scripts/README.md 的「第一次部署」Step 0 清单。
f009 = text("autowriter-migrations/009_fix_batch_item_counts_and_version_uniq.sql")
assert "FROM autowriter.items i" in f009, "009 迁移缺 batch_item_counts 表名限定"
assert "versions_item_version_uniq" in f009, "009 迁移缺 versions 唯一索引"
v10 = text("schemas/notes_v1_10_era_clear_and_decay_clamp.sql")
assert "NEW.era_tag := NULL" in v10, "v1_10 迁移缺 era 清空"
assert "LEAST(1.0::double precision" in v10, "v1_10 迁移缺衰减夹取"
readme = text("scripts/README.md")
assert "notes_v1_10_era_clear_and_decay_clamp.sql" in readme, "部署清单缺 v1_10"
assert "009_fix_batch_item_counts_and_version_uniq.sql" in readme, "部署清单缺 autowriter 009"

print("  ✓ COR-005/010/019/024 SQL 侧回归通过 (含升级迁移路径)")
