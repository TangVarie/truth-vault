#!/usr/bin/env python3
"""scripts/feature_recovery_report.py — 特征恢复队列里的存量, 报一行, 永远退出 0 (D-153)。

features-sync / backfill-features 收尾时调。队列 (truth_vault.feature_annotation_failures, v1.26) 里
现在不能抽的篇分两种: 等下一轮的 (还在等待期) 和已隔离的 (记满 3 次失败, 不再自动重抽)。它们是存量,
不是这一轮的失败: 只打一条 ::warning:: 带数字, 不让夜跑变红。没有存量 → 什么都不打。
表还没建 (v1.26 没跑) → 打一条「迁移还没跑」的 ::warning::, 夜跑页面上看得见, 照样退出 0。

只读, 只取 project_id / attempts / next_retry_at, 不碰标题正文。读不到库也退出 0 (打一行说没读到)。

  python feature_recovery_report.py [project_id]
"""
from __future__ import annotations

import sys
from collections import Counter
from typing import Optional

import feature_bank as fb
from _common import fetch_all_pages, get_supabase_client, is_missing_db_object
from annotate_feature_pass import DEFAULT_DONE_BY, RECOVERY_MIGRATION, retry_state


def backlog_by_project(sb, project_id: str = "", run_tag: str = "primary") -> dict[str, Counter]:
    """{project_id: Counter(deferred=…, quarantined=…)}; 一篇有几行 (换过模型名) 只算一次, 取最严的状态。"""
    worst: dict[tuple[str, str], str] = {}
    for pat in DEFAULT_DONE_BY:
        q = (sb.schema("truth_vault").table("feature_annotation_failures")
             .select("id,subject_id,project_id,attempts,next_retry_at")
             .eq("run_tag", run_tag).eq("bank_sha256", fb.load_bank()["_sha256"]))
        q = q.like("extractor", pat) if pat.endswith("%") else q.eq("extractor", pat)
        if project_id:
            q = q.eq("project_id", project_id)
        for r in fetch_all_pages(q, order_by="id"):
            state = retry_state(r)
            key = (r["project_id"], r["subject_id"])
            if state == "quarantined" or (state == "deferred" and worst.get(key) != "quarantined"):
                worst[key] = state
    out: dict[str, Counter] = {}
    for (pid, _), state in worst.items():
        out.setdefault(pid, Counter())[state] += 1
    return out


def main(argv: Optional[list[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    project_id = args[0].strip() if args else ""
    try:
        backlog = backlog_by_project(get_supabase_client(), project_id)
    except Exception as exc:  # noqa: BLE001 —— 报告读不到不该让夜跑变红
        if is_missing_db_object(exc):
            # worker 那边的同一条提醒只进 Railway 日志, 计数脚本的又被工作流丢掉 (2>/dev/null): 夜跑页面上要有一行。
            print(f"::warning title=迁移还没跑 (notes_v1_26)::特征恢复队列还没建 (owner 在 SQL editor 跑 {RECOVERY_MIGRATION} "
                  "之前都是这样): 特征照 v1.26 之前的办法抽, 不影响本轮结果。")
        else:
            print(f"::warning::features 恢复队列的存量这一轮没读到 ({type(exc).__name__}), 不影响本轮结果。")
        return 0
    deferred = sum(c["deferred"] for c in backlog.values())
    quarantined = sum(c["quarantined"] for c in backlog.values())
    if not (deferred or quarantined):
        return 0
    detail = "; ".join(f"{pid} 等 {c['deferred']} / 隔离 {c['quarantined']}" for pid, c in sorted(backlog.items()))
    print(f"::warning::features 恢复队列存量 (不算本轮失败): 等下一轮 {deferred} 篇, 已隔离 {quarantined} 篇 —— {detail}。"
          "等着的到点自动重抽; 隔离的不会自动再抽, 要重抽用 backfill-features 点名 note_ids + reannotate。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
