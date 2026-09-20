#!/usr/bin/env python3
"""scripts/count_unannotated_features.py — 一个项目还有多少篇没跑过特征抽取。

由 backfill-features.yml / daily-sync 调（仿 count_unannotated_essence.py）:
remaining==0 就停, 两轮没下降就停。「跑过」的判据与 annotate_feature_pass 一致:
该 (extractor, run_tag) 下已有 DONE_MARKER_QUESTION 那一行。

  python count_unannotated_features.py <project_id> [--extractor llm:<model>] [--run-tag primary]
"""
from __future__ import annotations

import argparse
import os

from _common import fetch_all_pages, get_supabase_client
from annotate_feature_pass import DONE_MARKER_QUESTION


def count_remaining(project_id: str, extractor: str, run_tag: str) -> int:
    sb = get_supabase_client()
    total = (sb.schema("truth_vault").table("notes").select("note_id", count="exact")
             .eq("project_id", project_id).limit(1).execute())
    n_total = total.count if total.count is not None else len(total.data or [])
    q = (sb.schema("truth_vault").table("note_feature_answers").select("subject_id")
         .eq("subject_type", "note").eq("question_id", DONE_MARKER_QUESTION)
         .eq("extractor", extractor).eq("run_tag", run_tag)
         .like("subject_id", f"{project_id}_%"))
    done = {r["subject_id"] for r in fetch_all_pages(q, order_by="subject_id")}
    return max(n_total - len(done), 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_id")
    ap.add_argument("--extractor", default="")
    ap.add_argument("--run-tag", default="primary")
    a = ap.parse_args()
    model = os.environ.get("FEATURE_MODEL") or os.environ.get("ESSENCE_MODEL", "claude-sonnet-4-6")
    print(count_remaining(a.project_id.strip(), a.extractor or f"llm:{model}", a.run_tag))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
