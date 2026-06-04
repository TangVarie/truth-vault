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


def count_remaining(project_id: str) -> int:
    sb = get_supabase_client()
    res = (
        sb.schema("truth_vault").table("notes")
        .select("note_id", count="exact")
        .eq("project_id", project_id)
        .is_("essence_annotated_at", "null")
        .limit(1)
        .execute()
    )
    # postgrest 的 exact count;兜底用 data 长度(理论不会走到)。
    return res.count if res.count is not None else len(res.data or [])


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print("usage: count_unannotated_essence.py <project_id>", file=sys.stderr)
        return 2
    print(count_remaining(sys.argv[1].strip()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
