#!/usr/bin/env python3
"""scripts/count_unannotated_features.py — 一个项目还有多少篇没跑过特征抽取。

由 backfill-features.yml / daily-sync 调（仿 count_unannotated_essence.py）:
remaining==0 就停, 两轮没下降就停。「跑过」的判据**直接复用**
annotate_feature_pass.fetch_done_ids —— 两边一个口径, 不各写一遍。

⚠️ 算的是【集合差】不是两个计数相减 (codex review on #141): 答案表对 notes 没有外键
(D-065 有意为之), 删掉一篇已标注的笔记、又新来一篇, 两个计数正好抵消 → remaining=0,
夜跑和 backfill 都会以为「抽完了」而再也不调 worker。

恢复队列 (v1.26, D-153): 队列里现在不能抽的篇 (还在等待期 / 已隔离) 【不计进】这个数 —— 它回答的是「现在叫 worker
还有几篇可做」。把它们算进来, 只剩存量时夜跑每晚都会白叫一次 worker、还会被当成欠产判红。存量由
feature_recovery_report.py 单独报。队列表还没建 (v1.26 没跑) 就和之前一样数;
那条「迁移还没跑」的提醒走标准错误, 标准输出永远只有一个数。

--done-by (D-085) 与 annotate_feature_pass 的同名参数同一个口径 (同一个解析函数)。judge 做 primary
之后, 这里和 worker 请求体的 done_by 要给同一个值: 一边认 jev:1.13.0 答过、一边不认的话,
计数永远降不到 0, backfill 会一直调 worker 空转。

  python count_unannotated_features.py <project_id> [--extractor llm:<model> | --done-by jev:1.13.0,llm:%]
                                       [--run-tag primary] [--code-only]
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

from _common import fetch_all_pages, get_supabase_client
import feature_bank as fb
from annotate_feature_pass import (blocked_ids, done_patterns, fetch_done_ids, fetch_recovery_rows,
                                   parse_done_by)


def count_remaining(project_id: str, *, run_tag: str = "primary",
                    code_only: bool = False, extractor: str = "",
                    done_by: Optional[tuple[str, ...]] = None) -> int:
    sb = get_supabase_client()
    q = (sb.schema("truth_vault").table("notes").select("note_id")
         .eq("project_id", project_id))
    note_ids = {r["note_id"] for r in fetch_all_pages(q, order_by="note_id")}
    done = fetch_done_ids(sb, project_id, run_tag=run_tag, code_only=code_only,
                          extractor=extractor or None, done_by=done_by or None)
    blocked: set[str] = set()
    if not code_only:
        patterns = done_patterns(extractor=extractor or None, done_by=done_by or None)
        blocked = set(blocked_ids(fetch_recovery_rows(sb, project_id, fb.load_bank()["_sha256"], run_tag, patterns)))
    return len(note_ids - done - blocked)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_id")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--extractor", default="",
                   help="精确匹配某个抽取器; 默认按 llm:%% 前缀 (worker 那边的 FEATURE_MODEL 可能和这里不同)")
    g.add_argument("--done-by", default="",
                   help="同 annotate_feature_pass --done-by (D-085): 逗号分隔的精确值或以 %% 结尾的前缀")
    ap.add_argument("--run-tag", default="primary")
    ap.add_argument("--code-only", action="store_true")
    a = ap.parse_args(argv)
    done_by = None
    if a.done_by:
        if a.code_only:
            ap.error("--done-by 只管模型题; --code-only 的判据固定是 code:v1")
        try:
            done_by = parse_done_by(a.done_by)
        except ValueError as exc:
            ap.error(str(exc))
    # 标准输出只放那个数: 工作流是 rem=$(python count_unannotated_features.py …) 再拿它和 "0" 比。
    # 日志 (比如 v1.26 没跑时那条 warning) 默认也写标准输出, 混进去之后 rem 永远不等于 0 —— 改写到标准错误。
    for name in ("annotate_features", "_common"):
        for h in logging.getLogger(name).handlers:
            if isinstance(h, logging.StreamHandler) and h.stream in (sys.stdout, sys.__stdout__):
                h.setStream(sys.stderr)
    print(count_remaining(a.project_id.strip(), run_tag=a.run_tag,
                          code_only=a.code_only, extractor=a.extractor, done_by=done_by))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
