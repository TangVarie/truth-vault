"""
migrate_essence_vocab.py
═══════════════════════════════════════════════════════════════════════════

Generic essence vocab migration runner. 业务上要把 v0.2 词表升 v0.3 时:
1. **operator (你)** 决定 v0.3 含什么内容 — 新增哪些 lever / 拆 / 改名 / 删
2. **operator** 改 schemas/notes_v1_2.sql 里的 CHECK 约束加上新允许值
3. **operator** 在 annotate_essence_pass.py 里更新 EMOTIONAL_LEVERS 等 set
4. **operator** 写 vocab_migrations YAML (见下方格式) 描述老值 → 新值
5. **本脚本** 读 yaml, 跑 UPDATE 把历史数据迁过去, 不需要全表重 LLM 标注

为什么这样设计:
    - 改 CHECK 约束 + 改 set 是元数据决策, 跟具体词表内容强相关, 不能脚本化
    - 把已有 essence 标注从老值映射到新值是机械操作, 可以脚本化
    - 完全重 LLM 标注是最后手段 (贵 + 慢), 大多数情况只是改名/拆分

触发条件 (来自 CURRENT_STATE.md 延后清单 🟡 慢性病): 第一次有人标注时
觉得 "12 个 lever / 19 个 archetype 都不合适" 超过 3 次. **本脚本是个空的
工具, 真正运行时机由 operator 决定 v0.3 内容的那一刻**.

格式:
    在 scripts/ 下放 vocab_migration_<from>_to_<to>.yaml, 形如:

    vocab_version_from: v0.2
    vocab_version_to:   v0.3

    # Field-level migrations. Key = column name in truth_vault.notes;
    # value = mapping from old → new (or null to clear the row's value,
    # for "delete and reannotate" cases).
    emotional_lever:
      # rename
      "焦虑撬动": "焦虑触发"
      # split (须人工 review; 这里只是先清掉, 重新跑 annotate)
      "造梦投射": null

    human_truth_archetype:
      "情感缺位": "情感真空"

    trend_dependencies:
      # delete (重跑 annotate)
      "时事热点": null
      "节日": null

    content_format:
      "情感叙事": "故事叙事"

    # 跑完后 notes.essence_vocab_version 改成下面这个
    target_essence_vocab_version: v0.3

用法:
    python migrate_essence_vocab.py vocab_migration_v0.2_to_v0.3.yaml
    python migrate_essence_vocab.py vocab_migration_v0.2_to_v0.3.yaml --dry-run

注意:
    本脚本只动 truth_vault.notes 的 essence 列. 不动 schema CHECK 约束
    (那个必须手改 schemas/notes_v1_2.sql 然后重跑 schema apply).

环境变量:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from _common import fetch_all_pages, get_supabase_client, setup_logger


logger = setup_logger("migrate_essence_vocab")


# Columns this script knows how to migrate. Each is either a scalar TEXT
# (string mapping) or a TEXT[] (each array element gets mapped).
_SCALAR_COLS = {"emotional_lever", "content_format"}
_ARRAY_COLS = {"human_truth_archetype", "trend_dependencies"}
_ALL_COLS = _SCALAR_COLS | _ARRAY_COLS


def load_migration(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        m = yaml.safe_load(f)
    required = {"vocab_version_from", "vocab_version_to", "target_essence_vocab_version"}
    missing = required - set(m.keys())
    if missing:
        raise ValueError(f"{path}: missing required keys: {missing}")
    unknown_cols = set(m.keys()) - required - _ALL_COLS
    if unknown_cols:
        raise ValueError(
            f"{path}: unknown migration columns {unknown_cols}. "
            f"Supported: {sorted(_ALL_COLS)}"
        )
    return m


def migrate_scalar(sb, column: str, mapping: dict[str, str | None],
                    target_version: str, dry_run: bool) -> int:
    """For a scalar text column, run one UPDATE per (old → new) entry."""
    affected = 0
    for old, new in mapping.items():
        # Find rows
        rows = fetch_all_pages(
            sb.schema("truth_vault").table("notes")
            .select("note_id")
            .eq(column, old)
        )
        if not rows:
            logger.info("  %s: no rows with %s=%r — skipping", column, column, old)
            continue
        logger.info("  %s: %d rows %s=%r → %r",
                    column, len(rows), column, old, new)
        if dry_run:
            affected += len(rows)
            continue
        update = {column: new, "essence_vocab_version": target_version}
        (
            sb.schema("truth_vault").table("notes")
            .update(update).eq(column, old).execute()
        )
        affected += len(rows)
    return affected


def migrate_array(sb, column: str, mapping: dict[str, str | None],
                   target_version: str, dry_run: bool) -> int:
    """For a TEXT[] column, fetch each row, transform the array element by
    element, write back."""
    # Find rows that contain ANY of the old values.
    affected = 0
    # PostgREST 不直接支持 array contains-any over multiple values in one query;
    # do per-key cs/cd query.
    candidate_ids: set[str] = set()
    for old in mapping.keys():
        rows = fetch_all_pages(
            sb.schema("truth_vault").table("notes")
            .select("note_id, " + column)
            .contains(column, [old])
        )
        for r in rows:
            candidate_ids.add(r["note_id"])

    if not candidate_ids:
        logger.info("  %s: no rows contain any old value", column)
        return 0

    logger.info("  %s: %d candidate rows", column, len(candidate_ids))
    # Pull full content for each candidate, transform, write back.
    for note_id in candidate_ids:
        row = (
            sb.schema("truth_vault").table("notes")
            .select(column)
            .eq("note_id", note_id)
            .limit(1).execute()
        )
        if not row.data:
            continue
        old_arr = row.data[0].get(column) or []
        # Element-wise mapping: None → drop; otherwise rename
        new_arr = []
        for v in old_arr:
            if v in mapping:
                replacement = mapping[v]
                if replacement is not None:
                    new_arr.append(replacement)
                # If None, drop entirely (operator will reannotate)
            else:
                new_arr.append(v)
        # De-dup while preserving order
        seen: set[str] = set()
        new_arr = [v for v in new_arr if not (v in seen or seen.add(v))]
        if new_arr == old_arr:
            continue
        logger.info("    %s: %r → %r", note_id, old_arr, new_arr)
        if dry_run:
            affected += 1
            continue
        update = {column: new_arr, "essence_vocab_version": target_version}
        (
            sb.schema("truth_vault").table("notes")
            .update(update).eq("note_id", note_id).execute()
        )
        affected += 1
    return affected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("migration_yaml",
                        help="Path to vocab_migration_<from>_to_<to>.yaml")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    path = Path(args.migration_yaml).resolve()
    if not path.exists():
        logger.error("Migration yaml not found: %s", path)
        return 2

    m = load_migration(path)
    target_version = m["target_essence_vocab_version"]

    logger.info("Migrating essence vocab %s → %s (target_essence_vocab_version=%s)",
                m["vocab_version_from"], m["vocab_version_to"], target_version)

    sb = get_supabase_client()
    stats: dict[str, int] = {}
    for col, mapping in m.items():
        if col in _SCALAR_COLS:
            n = migrate_scalar(sb, col, mapping, target_version, args.dry_run)
            stats[col] = n
        elif col in _ARRAY_COLS:
            n = migrate_array(sb, col, mapping, target_version, args.dry_run)
            stats[col] = n
        # other keys (vocab_version_from etc) are metadata, ignored

    logger.info("Done: %s", json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
