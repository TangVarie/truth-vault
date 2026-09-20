#!/usr/bin/env python3
"""scripts/count_unannotated_features.py — 一个项目还有多少篇没跑过特征抽取。

由 backfill-features.yml / daily-sync 调（仿 count_unannotated_essence.py）:
remaining==0 就停, 两轮没下降就停。「跑过」的判据**直接复用**
annotate_feature_pass.fetch_done_ids —— 两边一个口径, 不各写一遍。

⚠️ 算的是【集合差】不是两个计数相减 (codex review on #141): 答案表对 notes 没有外键
(D-065 有意为之), 删掉一篇已标注的笔记、又新来一篇, 两个计数正好抵消 → remaining=0,
夜跑和 backfill 都会以为「抽完了」而再也不调 worker。

  python count_unannotated_features.py <project_id> [--extractor llm:<model>] [--run-tag primary] [--code-only]
"""
from __future__ import annotations

import argparse

from _common import fetch_all_pages, get_supabase_client
from annotate_feature_pass import fetch_done_ids


def count_remaining(project_id: str, *, run_tag: str = "primary",
                    code_only: bool = False, extractor: str = "") -> int:
    sb = get_supabase_client()
    q = (sb.schema("truth_vault").table("notes").select("note_id")
         .eq("project_id", project_id))
    note_ids = {r["note_id"] for r in fetch_all_pages(q, order_by="note_id")}
    done = fetch_done_ids(sb, project_id, run_tag=run_tag, code_only=code_only,
                          extractor=extractor or None)
    return len(note_ids - done)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_id")
    ap.add_argument("--extractor", default="",
                    help="精确匹配某个抽取器; 默认按 llm:%% 前缀 (worker 那边的 FEATURE_MODEL 可能和这里不同)")
    ap.add_argument("--run-tag", default="primary")
    ap.add_argument("--code-only", action="store_true")
    a = ap.parse_args()
    print(count_remaining(a.project_id.strip(), run_tag=a.run_tag,
                          code_only=a.code_only, extractor=a.extractor))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
