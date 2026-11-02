#!/usr/bin/env python3
"""scripts/count_unannotated_essence.py — print how many notes in a project still
lack essence annotation (or carry essence from an older version of the text, D-137).

由 .github/workflows/backfill-essence.yml 调:循环灌 essence 时,用它判断"该项目还剩多少
未标注",remaining==0 就停、或两轮没下降就停(防全失败时死循环)。

  python count_unannotated_essence.py <project_id>   # → stdout 打印一个整数
"""
from __future__ import annotations

import sys

from _common import get_supabase_client, load_mapping


def count_remaining(project_id: str, only_missing_subtype: bool = False) -> int:
    """only_missing_subtype (审计 C-03): 直接调 annotate_essence_pass.subtype_backfill_candidates 数 —— 和抽取
    **同一个函数**, 判据只有一处 (含"方向要定义了 sub_directions"那道筛, codex review on #169)。
    这条路不是 count=exact 而是把候选拉回来数: 候选量是百级 (NUC 206), 可接受。"""
    sb = get_supabase_client()
    if only_missing_subtype:
        from annotate_essence_pass import subtype_backfill_candidates
        return len(subtype_backfill_candidates(sb, project_id, load_mapping(project_id)))
    res = (
        sb.schema("truth_vault").table("notes")
        .select("note_id", count="exact")
        .eq("project_id", project_id)
        .is_("essence_annotated_at", "null")
        .limit(1)
        .execute()
    )
    # postgrest 的 exact count;兜底用 data 长度(理论不会走到)。
    never = res.count if res.count is not None else len(res.data or [])
    # 外部审计 11-02 F02 / D-137: 标过、但正文后来改过的也算「待标」—— daily-sync 见到 0 就跳过这个项目, 不数它们的话
    # 没有新笔记的项目上过期的 essence 永远轮不到重标。和抽取同一个函数 (annotate_essence_pass.fetch_stale_essence_ids);
    # v1_23 没跑的库上它回空列表, 这里就和以前一样只数没标过的。
    from annotate_essence_pass import fetch_stale_essence_ids
    return never + len(fetch_stale_essence_ids(sb, project_id))


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--only-missing-subtype"]
    if not args or not args[0].strip():
        print("usage: count_unannotated_essence.py <project_id> [--only-missing-subtype]", file=sys.stderr)
        return 2
    print(count_remaining(args[0].strip(), only_missing_subtype="--only-missing-subtype" in sys.argv[1:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
