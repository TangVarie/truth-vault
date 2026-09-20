#!/usr/bin/env python3
"""
annotate_feature_pass.py — 内容特征层的抽取 pass（docs/28 §5, D-065 / D-070 P1）
═══════════════════════════════════════════════════════════════════════════

对一个项目的笔记跑问题库 prompts/feature_questions_v0_1.yaml:
  · 代码算的 8 个特征 + 3 道占位题（extractor = code:v1, 不花模型钱）
  · 20 道模型题, 按 call_groups 一次一组、同组 ≤ 4 题（防晕轮, docs/28 §5.3）
答案落 truth_vault.note_feature_answers（一题一行、带 bank 版本与校验和）,
数值原值落 truth_vault.note_features 现有四列（docs/28 §4.4）。

纯逻辑（切片 / 提示词 / 校验）在 feature_bank.py; 本文件只做库 I/O + LLM 调用 + 编排。
LLM 调用复用 annotate_essence_pass.call_claude（中转站 base_url + prompt caching + 退避）。

⚠️ 与 essence 同一条纪律（D-028）: 本 pass 绝不和 tier 抽取共进程, 提示词里只有切好的文本,
   不给 tier / 指标 / 评论 / 干预列。feature_bank.hygiene_check 每次渲染都断言。

Usage:
    python annotate_feature_pass.py NUC_phase1 --limit 30                # 增量（没答过的）
    python annotate_feature_pass.py NUC_phase1 --dry-run --limit 3       # 只渲染, 不调模型不写库
    python annotate_feature_pass.py NUC_phase1 --run-tag gate1-a --single --note-ids ids.txt
                                                                        # 闸一: 每题单问, 指定名单
    python annotate_feature_pass.py NUC_phase1 --code-only               # 只跑代码特征

Environment:
    SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY
    ANTHROPIC_API_KEY（--dry-run / --code-only 不需要）
    FEATURE_MODEL（默认取 ESSENCE_MODEL, 再默认 claude-sonnet-4-6）

Resumability:
    「答过」= 该 (extractor, run_tag) 下已有 has_specific_time 这一题的行（每道题都会落行,
    不问的也记 NULL + 原因, 所以任一题都能当标记）。--reannotate 忽略这个标记全部重跑。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

from _common import fetch_all_pages, get_supabase_client, load_mapping, setup_logger, _iso_now
import feature_bank as fb

logger = setup_logger("annotate_features")

DONE_MARKER_QUESTION = "has_specific_time"   # 每篇必落的一行, 当「这篇跑过了」的标记
_RUN_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$")


# ─────────────────────────────────────────────────────────────────────────
# 库 I/O
# ─────────────────────────────────────────────────────────────────────────

def fetch_notes(sb, project_id: str) -> list[dict]:
    q = (
        sb.schema("truth_vault").table("notes")
        .select("note_id, project_id, title, raw_content, target_blue_keywords, "
                "projects(brand, product)")
        .eq("project_id", project_id)
    )
    return fetch_all_pages(q, order_by="note_id")


def fetch_done_ids(sb, project_id: str, extractor: str, run_tag: str) -> set[str]:
    q = (
        sb.schema("truth_vault").table("note_feature_answers")
        .select("subject_id")
        .eq("subject_type", "note")
        .eq("question_id", DONE_MARKER_QUESTION)
        .eq("extractor", extractor)
        .eq("run_tag", run_tag)
        .like("subject_id", f"{project_id}_%")
    )
    return {r["subject_id"] for r in fetch_all_pages(q, order_by="subject_id")}


def write_answers(sb, rows: list[dict], dry_run: bool) -> None:
    if dry_run or not rows:
        return
    sb.schema("truth_vault").table("note_feature_answers").upsert(rows).execute()


def write_raw_counts(sb, note_id: str, counts: dict, bank_version: str, dry_run: bool) -> None:
    if dry_run:
        return
    row = {"note_id": note_id, **counts,
           "extracted_at": _iso_now(), "extractor_version": f"{bank_version}/{fb.CODE_EXTRACTOR}"}
    sb.schema("truth_vault").table("note_features").upsert(row).execute()


# ─────────────────────────────────────────────────────────────────────────
# 行构造
# ─────────────────────────────────────────────────────────────────────────

def _row(bank: dict, note_id: str, qid: str, version: int, extractor: str, run_tag: str,
         answer: Optional[str], evidence: Optional[str], reason: Optional[str]) -> dict:
    return {
        "subject_type": "note", "subject_id": note_id,
        "question_id": qid, "question_version": version,
        "bank_version": bank["bank_version"], "bank_sha256": bank["_sha256"],
        "extractor": extractor, "run_tag": run_tag,
        "answer": answer, "evidence": evidence, "prob": None,
        "invalid_reason": reason, "extracted_at": _iso_now(),
    }


def code_rows(bank: dict, note: dict, spans: dict, brand_words: list[str], run_tag: str) -> list[dict]:
    """8 个代码特征 + 3 道占位题, extractor 固定 code:v1。"""
    rows = []
    versions = {c["id"]: int(c.get("version") or 1) for c in bank.get("code_features") or []}
    for qid, (ans, reason) in fb.code_features(spans, brand_words).items():
        rows.append(_row(bank, note["note_id"], qid, versions.get(qid, 1), fb.CODE_EXTRACTOR, run_tag,
                         ans, None, reason))
    for qid, ans in fb.placebo_answers(bank, note["note_id"]).items():
        rows.append(_row(bank, note["note_id"], qid, 1, fb.CODE_EXTRACTOR, run_tag, ans, None, None))
    return rows


# ─────────────────────────────────────────────────────────────────────────
# LLM
# ─────────────────────────────────────────────────────────────────────────

def _llm(system: str, user: str, model: str) -> str:
    # 延迟导入: --dry-run / --code-only 不需要 anthropic SDK。
    from annotate_essence_pass import call_claude
    return call_claude(user, model, cached_system=system)


def ask_group(bank: dict, call: dict, spans: dict, model: str, *, llm=_llm
              ) -> tuple[dict[str, dict], bool, list[str]]:
    """问一组题: 一次 + 校验不过的题重问一次。返回 (每题结果, 是否重问过, 系统性错误列表)。

    重问只针对没过的题（其余答案保留）; 仍不过 → NULL + 原因。
    api_error 是基础设施问题, 整组记 api_error, 调用方计 systemic。
    """
    from annotate_essence_pass import parse_claude_json
    qids = call["question_ids"]
    try:
        raw = llm(call["system"], call["user"], model)
    except Exception as exc:  # noqa: BLE001
        return ({q: {"answer": None, "evidence": None, "invalid_reason": fb.INVALID_API} for q in qids},
                False, [f"api_error: {exc!r}"])
    parsed = fb_parse(parse_claude_json, raw)
    results = fb.validate_answers(bank, qids, parsed, spans)
    bad = fb.retryable(results)
    if not bad:
        return results, False, []
    note = fb.correction_note(results) if parsed is not None else "- 上一次回复不是合法 JSON / 含 markdown 包装"
    retry_user = (call["user"] + "\n\n═══ 你上一次的回复 ═══\n" + (raw or "")[:4000]
                  + "\n\n═══ 校验没过, 只重答下面这些题（其余可以照抄）═══\n" + note
                  + "\n\n严格按原格式重新输出全部题目的 JSON。")
    try:
        raw2 = llm(call["system"], retry_user, model)
    except Exception as exc:  # noqa: BLE001
        for q in bad:
            results[q] = {"answer": None, "evidence": None, "invalid_reason": fb.INVALID_API}
        return results, True, [f"retry_api_error: {exc!r}"]
    parsed2 = fb_parse(parse_claude_json, raw2)
    results2 = fb.validate_answers(bank, qids, parsed2, spans)
    for q in bad:
        results[q] = results2[q]
    return results, True, []


def fb_parse(parse_fn, raw: str) -> Optional[dict]:
    try:
        return parse_fn(raw)
    except Exception:  # noqa: BLE001
        return None


# ─────────────────────────────────────────────────────────────────────────
# 一篇笔记
# ─────────────────────────────────────────────────────────────────────────

def annotate_note(bank: dict, note: dict, mapping: dict, *, model: str, extractor: str,
                  run_tag: str, single: bool, code_only: bool, dry_run: bool, llm=None,
                  sleep_s: float = 0.0) -> dict:
    """返回 {rows, raw_counts, stats}。stats: groups_ok / groups_retry / systemic / invalid。

    llm 默认取模块级 _llm（运行时查, 不在 def 时绑定 —— CI 自检 monkeypatch 它走假模型）。"""
    llm = llm or _llm
    project = note.get("projects") or {}
    mode = (mapping.get("title_extraction") or "none")
    spans = fb.build_spans(note.get("raw_content") or "", mode=mode, title_col=note.get("title"))
    brand_words = fb.brand_dictionary(project, note, mapping)
    rows = code_rows(bank, note, spans, brand_words, run_tag)
    stats = {"groups_ok": 0, "groups_retry": 0, "systemic": 0, "invalid": 0, "answered": 0,
             "title_how": spans["_title_how"], "truncated": bool(spans["_truncated"])}
    if code_only:
        return {"rows": rows, "raw_counts": fb.raw_counts(spans), "stats": stats, "spans": spans}

    idx = fb.question_index(bank)
    errors: list[str] = []
    for qids in fb.plan_calls(bank, single=single):
        call = fb.render_call(bank, qids, spans)   # 守卫 2 / 4 在这里断言
        for q, reason in call["skipped"].items():
            rows.append(_row(bank, note["note_id"], q, idx[q]["version"], extractor, run_tag, None, None, reason))
        if not call["question_ids"]:
            continue
        if dry_run:
            for q in call["question_ids"]:
                rows.append(_row(bank, note["note_id"], q, idx[q]["version"], extractor, run_tag, None, None, "dry_run"))
            continue
        results, retried, errs = ask_group(bank, call, spans, model, llm=llm)
        errors += errs
        if errs and all(r.get("invalid_reason") == fb.INVALID_API for r in results.values()):
            stats["systemic"] += 1
        else:
            stats["groups_ok"] += 1
        if retried:
            stats["groups_retry"] += 1
        for q, r in results.items():
            rows.append(_row(bank, note["note_id"], q, idx[q]["version"], extractor, run_tag,
                             r["answer"], r["evidence"], r["invalid_reason"]))
            if r["answer"] is None:
                stats["invalid"] += 1
            else:
                stats["answered"] += 1
        if sleep_s:
            time.sleep(sleep_s)
    stats["errors"] = errors
    return {"rows": rows, "raw_counts": fb.raw_counts(spans), "stats": stats, "spans": spans}


# ─────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────

def _exit_code_for_stats(stats: dict) -> int:
    """同 annotate_essence_pass._exit_code_for_stats 的口径:
    卫生断言失败任意一条 → 1; systemic>0 且一篇都没成功 → 1; 其余 0（单篇抽风幂等下轮续）。"""
    if stats.get("hygiene_failed"):
        return 1
    if stats.get("systemic_failed", 0) > 0 and stats.get("ok", 0) == 0:
        return 1
    return 0


def _read_note_ids(spec: str) -> set[str]:
    p = Path(spec)
    if p.exists():
        return {ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()}
    return {x.strip() for x in spec.split(",") if x.strip()}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("project_id")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true", help="只渲染提示词, 不调模型、不写库")
    ap.add_argument("--code-only", action="store_true", help="只跑代码特征 + 占位题")
    ap.add_argument("--reannotate", action="store_true", help="忽略「已答过」标记, 全部重跑（同 PK 覆盖）")
    ap.add_argument("--run-tag", default="primary", help="primary 进分析; retest-* / gate1-* 只给闸一")
    ap.add_argument("--single", action="store_true", help="每题单问（闸一「分组 vs 单问」对比用）")
    ap.add_argument("--note-ids", default="", help="只跑这些 note_id（逗号分隔或文件路径）")
    ap.add_argument("--model", default="", help="覆盖 FEATURE_MODEL")
    ap.add_argument("--qps", type=float, default=2.0)
    ap.add_argument("--failed-queue", default="failed_feature_queue.jsonl")
    args = ap.parse_args(argv)

    if not _RUN_TAG_RE.match(args.run_tag):
        logger.error("run_tag 只能是字母数字 _ . -, ≤40 字: %r", args.run_tag)
        return 2
    model = args.model or os.environ.get("FEATURE_MODEL") or os.environ.get("ESSENCE_MODEL", "claude-sonnet-4-6")
    need_llm = not (args.dry_run or args.code_only)
    if need_llm and not os.environ.get("ANTHROPIC_API_KEY"):
        logger.error("ANTHROPIC_API_KEY must be set (or use --dry-run / --code-only)")
        return 2

    bank = fb.load_bank()
    errs = fb.validate_bank(bank)
    if errs:
        logger.error("问题库结构不合法, 拒绝开跑: %s", errs)
        return 2
    extractor = f"llm:{model}"
    mapping = load_mapping(args.project_id)
    mode = mapping.get("title_extraction") or "none"
    logger.info("bank=%s sha=%s… model=%s run_tag=%s title_extraction=%s single=%s",
                bank["bank_version"], bank["_sha256"][:12], model, args.run_tag, mode, args.single)

    sb = get_supabase_client()
    notes = fetch_notes(sb, args.project_id)
    if args.note_ids:
        keep = _read_note_ids(args.note_ids)
        notes = [n for n in notes if n["note_id"] in keep]
    if not args.reannotate:
        done = fetch_done_ids(sb, args.project_id, fb.CODE_EXTRACTOR if args.code_only else extractor, args.run_tag)
        notes = [n for n in notes if n["note_id"] not in done]
    if args.limit:
        notes = notes[: args.limit]
    logger.info("Found %d notes to annotate for project %s", len(notes), args.project_id)

    stats = {"ok": 0, "failed": 0, "systemic_failed": 0, "hygiene_failed": 0,
             "groups_ok": 0, "groups_retry": 0, "answered": 0, "invalid": 0,
             "title_how": {}, "truncated": 0}
    sleep_s = 1.0 / args.qps if args.qps > 0 else 0
    fq = Path(args.failed_queue).resolve()
    for i, note in enumerate(notes):
        try:
            res = annotate_note(bank, note, mapping, model=model, extractor=extractor,
                                run_tag=args.run_tag, single=args.single, code_only=args.code_only,
                                dry_run=args.dry_run, sleep_s=sleep_s)
        except AssertionError as exc:
            logger.error("Hygiene assertion failed on %s: %s", note["note_id"], exc)
            stats["hygiene_failed"] += 1
            _append_failed(fq, note, args.project_id, [f"hygiene_failed: {exc}"])
            continue
        st = res["stats"]
        stats["title_how"][st["title_how"]] = stats["title_how"].get(st["title_how"], 0) + 1
        stats["truncated"] += int(st["truncated"])
        if args.dry_run:
            call_n = sum(1 for _ in fb.plan_calls(bank, single=args.single))
            logger.info("[dry-run] %s title=%r calls=%d rows=%d", note["note_id"],
                        (res["spans"]["title"] or "")[:30], call_n, len(res["rows"]))
            stats["ok"] += 1
            continue
        if st.get("systemic") and not st.get("groups_ok"):
            stats["failed"] += 1
            stats["systemic_failed"] += 1
            _append_failed(fq, note, args.project_id, st.get("errors") or ["systemic"])
            continue   # 一组都没成功: 不落行, 下轮幂等续
        try:
            write_answers(sb, res["rows"], dry_run=False)
            write_raw_counts(sb, note["note_id"], res["raw_counts"], bank["bank_version"], dry_run=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("write rejected %s: %s", note["note_id"], exc)
            stats["failed"] += 1
            stats["systemic_failed"] += 1
            _append_failed(fq, note, args.project_id, [f"write_rejected: {exc}"])
            continue
        stats["ok"] += 1
        for k in ("groups_ok", "groups_retry", "answered", "invalid"):
            stats[k] += st[k]
        if i % 10 == 0:
            logger.info("[%d/%d] %s ok=%d failed=%d answered=%d invalid=%d",
                        i + 1, len(notes), note["note_id"], stats["ok"], stats["failed"],
                        stats["answered"], stats["invalid"])

    logger.info("Done: %s", json.dumps(stats, ensure_ascii=False))
    code = _exit_code_for_stats(stats)
    if code:
        logger.error("feature pass 判红: hygiene_failed=%d systemic_failed=%d ok=%d",
                     stats["hygiene_failed"], stats["systemic_failed"], stats["ok"])
    return code


def _append_failed(path: Path, note: dict, project_id: str, errors: list[str]) -> None:
    rec = {"note_id": note.get("note_id"), "project_id": project_id, "errors": errors,
           "attempted_at": _iso_now()}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    sys.exit(main())
