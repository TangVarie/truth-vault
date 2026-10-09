#!/usr/bin/env python3
"""scripts/count_unannotated_essence.py — print how many notes in a project still
lack essence annotation.

由 .github/workflows/backfill-essence.yml 调:循环灌 essence 时,用它判断"该项目还剩多少
未标注",remaining==0 就停、或两轮没下降就停(防全失败时死循环)。

  python count_unannotated_essence.py <project_id>   # → stdout 打印一个整数
"""
from __future__ import annotations

import sys

from _common import get_supabase_client


def count_remaining(project_id: str, only_missing_subtype: bool = False) -> int:
    """only_missing_subtype (审计 C-03): 与 annotate_essence_pass.fetch_unannotated_notes 的
    --only-missing-subtype 同一判据 —— 已标 essence、direction_subtype 空、raw_extra._direction_raw 非空。"""
    sb = get_supabase_client()
    q = (
        sb.schema("truth_vault").table("notes")
        .select("note_id", count="exact")
        .eq("project_id", project_id)
    )
    if only_missing_subtype:
        q = (q.not_.is_("essence_annotated_at", "null")
              .is_("direction_subtype", "null")
              .not_.is_("raw_extra->_direction_raw", "null"))
    else:
        q = q.is_("essence_annotated_at", "null")
    res = q.limit(1).execute()
    # postgrest 的 exact count;兜底用 data 长度(理论不会走到)。
    return res.count if res.count is not None else len(res.data or [])


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--only-missing-subtype"]
    if not args or not args[0].strip():
        print("usage: count_unannotated_essence.py <project_id> [--only-missing-subtype]", file=sys.stderr)
        return 2
    print(count_remaining(args[0].strip(), only_missing_subtype="--only-missing-subtype" in sys.argv[1:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
