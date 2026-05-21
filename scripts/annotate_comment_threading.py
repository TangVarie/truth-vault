"""
annotate_comment_threading.py
═══════════════════════════════════════════════════════════════════════════

D-022 Phase 2: 用 LLM 给已经 flat-extract 进 truth_vault.comments 的评论
补 parent_comment_id, 重建楼层层级.

Sprint 0 现状 (per CURRENT_STATE.md): sync_comments_from_raw_extra.py
做了扁平抽取, comments 行都带 parent_comment_id=NULL. 这个脚本是 Phase 2
独立 LLM pass, 不在 sync 主链路里跑.

设计原则:
    - 输入: 某个 note 的所有 truth_vault.comments 行 + 原始 raw_extra
      的 _comment_text 文本块作为上下文
    - LLM 任务: 给每条评论判定 parent_comment_id (引用了哪条更早的评论)
      或 NULL (顶层评论 / 直接回应贴主)
    - 输出形状: [{comment_id, parent_comment_id_or_null, confidence}, ...]
    - 输出严格校验: comment_id 必须在已有 set 里, parent_comment_id 必须
      在已有 set 里 (或 NULL), 不能成环 (parent 不能是自己或后代)
    - 写回: UPDATE truth_vault.comments SET parent_comment_id = ?
      WHERE comment_id = ?

边界 / 限制 (诚实):
    - 平台原始评论 ID 没保留在 TV 里 (sync 用 ordinal-based id 如 "_c1"),
      所以 LLM 只能基于内容相邻性 + role + 文本引用 推断关系. 这是软推断,
      不可能 100% 准. 失败 case (循环引用 / parent_id 不在 set) 写到
      failed_threading_queue.jsonl, 不阻塞其他 notes 的处理.
    - 只处理那些 raw_extra 里有 _comment_text 的 notes. 没原始文本块的
      跳过 (理论上不应该, 但兜底).
    - 已经有 parent_comment_id 的评论不重新分析 (尊重之前的标注, 避免
      重复跑覆盖手工修正).

用法:
    python annotate_comment_threading.py NUC_phase1
    python annotate_comment_threading.py NUC_phase1 --limit 30
    python annotate_comment_threading.py NUC_phase1 --dry-run
    python annotate_comment_threading.py NUC_phase1 --reannotate    # 覆盖已有

环境变量:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
    ANTHROPIC_API_KEY               (--dry-run 时不需要)
    COMMENT_THREADING_MODEL         (默认 claude-sonnet-4-6)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

from _common import fetch_all_pages, get_supabase_client, setup_logger, _iso_now
# 复用 annotate_essence_pass 里已经成熟的 retry + flock + json parse helpers
from annotate_essence_pass import (
    call_claude,
    parse_claude_json,
    _append_failed_queue,
)


logger = setup_logger("annotate_comment_threading")


THREADING_PROMPT_TEMPLATE = """你是一个小红书评论楼层结构分析专家. 给定一条笔记的所有评论, 判定每条评论
回应的是哪一条更早的评论, 或者是直接回应贴主 (顶层评论).

═══════════════════════════════════════════════
笔记原文 (上下文)
═══════════════════════════════════════════════
{note_content}

═══════════════════════════════════════════════
原始评论文本块 (按平台顺序)
═══════════════════════════════════════════════
{raw_comment_block}

═══════════════════════════════════════════════
已经抽取的扁平评论 (按 comment_order)
═══════════════════════════════════════════════
{flat_comments_list}

═══════════════════════════════════════════════
你的任务
═══════════════════════════════════════════════
对上面 ID 列表里的每一条评论, 输出它回应的是哪条评论的 ID (parent_comment_id)
或 null (如果是顶层 / 直接回应贴主).

判断信号:
  - 文本里 @ 提到某用户名
  - "回复 xxx:" / "→ xxx" 这种显式回复标记
  - 内容上是对前一条的反问 / 补充 / 反驳
  - 角色: 贴主回复必定是某条评论的 child (parent ≠ null)
  - 楼层缩进 (原始文本块里如果有缩进的话)
  - 邻近性 (回应通常贴近被回应那条)

约束:
  - parent_comment_id 必须是已有 ID 列表里的某个值, 或 null
  - parent_comment_id 不能等于 comment_id 自己
  - 不能形成环 (A→B→A)
  - 信号不足时大胆给 null (顶层评论是常态)
  - confidence 标低分时, 我们后续可以人工 review

输出严格 JSON, 无 markdown 包装:
{{
  "threading": [
    {{"comment_id": "...", "parent_comment_id": null | "...", "confidence": 0-1, "reason": "<一句>"}},
    ...
  ]
}}
"""


def fetch_notes_with_pending_threading(
    sb, project_id: str, reannotate: bool, limit: int
) -> list[dict]:
    """Notes whose raw_extra has _comment_text AND have at least one row in
    truth_vault.comments. By default skips notes whose comments already have
    parent_comment_id assigned (assume already threaded)."""
    # 1. Pull candidate notes
    q = (
        sb.schema("truth_vault")
        .table("notes")
        .select("note_id, raw_content, raw_extra")
        .eq("project_id", project_id)
        .not_.is_("raw_extra", None)
    )
    rows = fetch_all_pages(q)
    candidates = []
    for r in rows:
        re = r.get("raw_extra") or {}
        # Either of these keys can carry the original feishu comment block
        for k in ("_comment_text", "_comment_text_persona"):
            if isinstance(re.get(k), str) and re[k].strip():
                r["_raw_comment_block"] = re[k]
                candidates.append(r)
                break

    if not candidates:
        return []

    # 2. For each candidate, fetch its comments + check threading state
    out: list[dict] = []
    for r in candidates:
        if limit and len(out) >= limit:
            break
        comments = fetch_all_pages(
            sb.schema("truth_vault").table("comments")
            .select("comment_id, content, comment_role, comment_order, parent_comment_id, is_pinned")
            .eq("note_id", r["note_id"])
            .order("comment_order", desc=False)
        )
        if not comments:
            continue
        already_threaded = any(c.get("parent_comment_id") for c in comments)
        if already_threaded and not reannotate:
            continue
        r["_comments"] = comments
        out.append(r)
    return out


def build_threading_prompt(note: dict, comments: list[dict]) -> str:
    flat_lines = []
    for c in comments:
        role = c.get("comment_role") or "未知"
        order = c.get("comment_order")
        pinned = " ⭐顶置" if c.get("is_pinned") else ""
        content = (c.get("content") or "").replace("\n", " ")[:200]
        flat_lines.append(f"  - comment_id={c['comment_id']!r} order={order} role={role}{pinned}: {content}")
    note_body = (note.get("raw_content") or "")[:500]
    raw_block = (note.get("_raw_comment_block") or "")[:3000]
    return THREADING_PROMPT_TEMPLATE.format(
        note_content=note_body or "(空)",
        raw_comment_block=raw_block or "(空)",
        flat_comments_list="\n".join(flat_lines),
    )


def validate_threading(parsed: dict, allowed_ids: set[str]) -> list[str]:
    """Verify the LLM output is well-formed: each entry references known
    comment_ids, parent_comment_id is in set or null, no self-loop, no
    cycles."""
    errs: list[str] = []
    threading = parsed.get("threading")
    if not isinstance(threading, list):
        return ["threading is not a list"]
    seen_ids: set[str] = set()
    edges: dict[str, str | None] = {}
    for entry in threading:
        cid = entry.get("comment_id")
        pid = entry.get("parent_comment_id")
        if cid not in allowed_ids:
            errs.append(f"unknown comment_id {cid!r}")
            continue
        if cid in seen_ids:
            errs.append(f"duplicate entry for {cid!r}")
            continue
        seen_ids.add(cid)
        if pid is not None and pid not in allowed_ids:
            errs.append(f"unknown parent_comment_id {pid!r} for {cid!r}")
            continue
        if pid == cid:
            errs.append(f"self-loop on {cid!r}")
            continue
        edges[cid] = pid

    # Cycle detection (only meaningful for entries that survived the
    # per-row checks above).
    for cid in edges:
        seen = {cid}
        cur = edges.get(cid)
        steps = 0
        while cur is not None:
            if cur in seen:
                errs.append(f"cycle through {cid!r}")
                break
            seen.add(cur)
            cur = edges.get(cur)
            steps += 1
            if steps > len(edges) + 1:
                errs.append(f"cycle (depth exceeded) through {cid!r}")
                break
    return errs


def apply_threading(sb, threading: list[dict], dry_run: bool = False) -> int:
    """Write parent_comment_id back to truth_vault.comments. Returns count
    of rows actually changed (entries with parent_comment_id=null on
    already-null comments are a no-op and not counted)."""
    changed = 0
    for entry in threading:
        cid = entry["comment_id"]
        pid = entry.get("parent_comment_id")  # may be None
        if dry_run:
            logger.info("[dry-run] would set comment %s parent=%s", cid, pid)
            changed += 1
            continue
        (
            sb.schema("truth_vault")
            .table("comments")
            .update({"parent_comment_id": pid})
            .eq("comment_id", cid)
            .execute()
        )
        changed += 1
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("project_id")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0,
                        help="Process at most N notes")
    parser.add_argument("--reannotate", action="store_true",
                        help="Re-thread notes whose comments already have parent_comment_id set")
    parser.add_argument("--qps", type=float, default=2.0)
    parser.add_argument("--failed-queue", default="failed_threading_queue.jsonl")
    args = parser.parse_args()

    model = os.environ.get("COMMENT_THREADING_MODEL", "claude-sonnet-4-6")
    if not args.dry_run and not os.environ.get("ANTHROPIC_API_KEY"):
        logger.error("ANTHROPIC_API_KEY must be set (or use --dry-run)")
        return 2

    sb = get_supabase_client()
    notes = fetch_notes_with_pending_threading(
        sb, args.project_id, args.reannotate, args.limit,
    )
    logger.info("Found %d notes with threadable comments for project %s",
                len(notes), args.project_id)

    failed_queue_path = Path(args.failed_queue).resolve()
    stats = {"ok": 0, "failed": 0, "skipped": 0}
    sleep_s = 1.0 / args.qps if args.qps > 0 else 0

    for i, note in enumerate(notes):
        comments = note["_comments"]
        allowed_ids = {c["comment_id"] for c in comments}
        prompt = build_threading_prompt(note, comments)

        if args.dry_run:
            logger.info("[dry-run] %s prompt length %d, %d comments",
                        note["note_id"], len(prompt), len(comments))
            stats["ok"] += 1
            continue

        try:
            raw = call_claude(prompt, model)
        except Exception as exc:
            logger.warning("API failure on %s: %s", note["note_id"], exc)
            stats["failed"] += 1
            _append_failed_queue(failed_queue_path, note, args.project_id,
                                  [f"api_error: {exc!r}"], "")
            continue
        parsed = parse_claude_json(raw)
        if parsed is None:
            stats["failed"] += 1
            _append_failed_queue(failed_queue_path, note, args.project_id,
                                  ["json_parse_failed"], raw)
            continue
        errs = validate_threading(parsed, allowed_ids)
        if errs:
            logger.warning("Validation failed for %s: %s", note["note_id"], errs)
            stats["failed"] += 1
            _append_failed_queue(failed_queue_path, note, args.project_id,
                                  errs, raw)
            continue

        try:
            apply_threading(sb, parsed["threading"])
            stats["ok"] += 1
            logger.info("Threaded %s (%d comments)", note["note_id"], len(comments))
        except Exception as exc:
            logger.exception("write failed for %s: %s", note["note_id"], exc)
            stats["failed"] += 1
            _append_failed_queue(failed_queue_path, note, args.project_id,
                                  [f"write_error: {exc!r}"], raw)
        time.sleep(sleep_s)

    logger.info("Done: %s", json.dumps(stats, ensure_ascii=False))
    if stats["failed"]:
        logger.info("Failed rows appended to %s — review then either fix the "
                    "underlying note + rerun, or feed the file back through "
                    "this script after correcting the prompt.", failed_queue_path)
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
