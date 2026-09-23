"""
ingest_gate1_answers.py
═══════════════════════════════════════════════════════════════════════════

把闸一标注表（build_gate1_human_sheets.py 生成、填完发回的 xlsx）落进
truth_vault.note_feature_answers —— 人填的和别的模型填的都走这一条（A15, D-079 §5.1）。

    python ingest_gate1_answers.py --extractor human:张三 --file 笔记标注_标注员A.xlsx
    python ingest_gate1_answers.py --extractor jev:1.13.0-A --file A_Jev.xlsx   # 一张表一个 extractor, 见下
    python ingest_gate1_answers.py ... --write        # 默认只校验不写

extractor 的写法（与 annotate_feature_pass 的 llm:<model> / code:v1 并列）:
    human:<姓名>     一个人一张表, 姓名进 extractor 才分得清谁和谁不一致（κ 按人算）
    jev:<版本>-<表>  别的模型填的表 —— 它【不是】闸一"人工那一半", 只是又一个模型。
                     一个模型填了 A/B/C 三张, 重叠的 50 篇它答了两遍, 主键里没有"哪张表",
                     不带表的字母就会互相覆盖, 所以 extractor 要写成 jev:1.13.0-A 并一张一跑
run_tag 默认 gate1-20260928, 与 D-079 一致; 主键 (subject, question, version, extractor, run_tag)
决定同一个人同一张表重跑是覆盖, 不是再插一份。

校验（任一条不过就整份不写, 别把半张表落库）:
    · 表里的 note_id 必须全在名单 CSV 里, 且恰好等于名单里分给这位标注员的那 50 篇
      （名单 `annotators` 列）—— 发错表、混了表、少行多行都在这里拦住
    · 表头的中文短题名必须能一一映射回题库 question_id（题库改了题名这里会红）
    · 答案必须在闭集里（bool → 是/否; choice → options）；「—」是预先灰掉的格子, 跳过
      且必须与名单 `skipped_questions` 一致；空格子按【没答】计, 不写行, 但会点名
    · 「拿不准的地方」那一列不进库; 只有 Jev 那种按题写了概率的, 解析出来写进 prob
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

import openpyxl

import feature_bank as fb
from _common import _iso_now, get_supabase_client, setup_logger
from build_gate1_human_sheets import SHORT

logger = setup_logger("ingest_gate1")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = ROOT / "data-analysis" / "gate1-human-sample-2026-09-28.csv"
DEFAULT_RUN_TAG = "gate1-20260928"
SHEET = "标注"
SKIP_MARK = "—"
UPSERT_CHUNK = 200                       # 走 body 不走 URL, 但一次别太大

_EXTRACTOR_RE = re.compile(r"^(human|jev):[^\s:]+$")
# Jev 在「拿不准的地方」里的写法: "4 具体地点或场合：判「是」的概率 0.39，落在 0.35–0.65"
#                                "12 产品角色：第一名只有 0.45；「主角」0.45 与「只暗示」0.33 太接近"
_PROB_RE = re.compile(r"(?m)^(\d+) [^：]+：(?:判「是」的概率|第一名只有) ([0-9.]+)")


def load_manifest(path: Path) -> dict[str, dict]:
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit(f"名单为空: {path}")
    return {r["note_id"]: r for r in rows}


def read_sheet(path: Path, bank: dict) -> tuple[str, list[dict]]:
    """返回 (标注员字母, [{note_id, answers: {qid: 值}, probs: {qid: float}}])。"""
    wb = openpyxl.load_workbook(path, data_only=True)
    if SHEET not in wb.sheetnames:
        raise SystemExit(f"{path.name}: 没有「{SHEET}」页, 页有 {wb.sheetnames}")
    # 标注员字母在「怎么标」页的标题里: 笔记标注 · 标注员 A · 共 50 篇
    who = None
    if "怎么标" in wb.sheetnames:
        for row in wb["怎么标"].iter_rows(values_only=True):
            for v in row:
                m = re.search(r"标注员 ([ABC])", str(v or ""))
                if m:
                    who = m.group(1)
                    break
            if who:
                break
    if not who:
        raise SystemExit(f"{path.name}: 「怎么标」页里找不到「标注员 A/B/C」, 分不清这是谁的表")

    ws = wb[SHEET]
    header = [c.value for c in ws[1]]
    label_to_qid = {v: k for k, v in SHORT.items()}
    qidx = fb.question_index(bank)
    col_q: dict[int, str] = {}
    unc_col = nid_col = None
    for i, h in enumerate(header):
        if h is None:
            continue
        h = str(h)
        if h == "note_id":
            nid_col = i
            continue
        if h.startswith("拿不准"):
            unc_col = i
            continue
        m = re.match(r"^\d+\n(.+)$", h)
        if not m:
            continue
        label = m.group(1).strip()
        if label not in label_to_qid:
            raise SystemExit(f"{path.name}: 表头「{label}」映射不回题库 question_id (SHORT 里没有)")
        qid = label_to_qid[label]
        if qid not in qidx:
            raise SystemExit(f"{path.name}: 题库里没有 {qid}")
        col_q[i] = qid
    if nid_col is None:
        raise SystemExit(f"{path.name}: 没有隐藏的 note_id 列, 回收对不了账")
    if len(col_q) != len(fb.llm_questions(bank)):
        raise SystemExit(f"{path.name}: 映射到 {len(col_q)} 题, 题库有 {len(fb.llm_questions(bank))} 题")

    out = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        nid = row[nid_col]
        if not nid:
            continue
        answers = {qid: (None if row[i] is None else str(row[i]).strip()) for i, qid in col_q.items()}
        probs: dict[str, float] = {}
        if unc_col is not None and row[unc_col]:
            num_to_qid = {int(h.split("\n")[0]): col_q[i] for i, h in enumerate(header) if i in col_q}
            for n, p in _PROB_RE.findall(str(row[unc_col])):
                if int(n) in num_to_qid:
                    probs[num_to_qid[int(n)]] = float(p)
        out.append({"note_id": str(nid), "answers": answers, "probs": probs})
    return who, out


def validate(path: Path, who: str, notes: list[dict], manifest: dict, bank: dict) -> list[str]:
    errs: list[str] = []
    # 名单里 annotators 写成 "AB" / "AC" / "B" / "C" (字母串, 不带分隔符)
    expected = {nid for nid, r in manifest.items() if who in (r["annotators"] or "")}
    got = [n["note_id"] for n in notes]
    if len(got) != len(set(got)):
        errs.append("note_id 有重复行")
    if set(got) != expected:
        errs.append(f"标注员 {who} 的表应有名单里的 {len(expected)} 篇, 实得 {len(got)} 篇; "
                    f"多出 {sorted(set(got) - expected)[:3]}, 缺 {sorted(expected - set(got))[:3]}")
    qidx = fb.question_index(bank)
    for n in notes:
        man = manifest.get(n["note_id"])
        if not man:
            continue
        skipped = set(filter(None, (man.get("skipped_questions") or "").split(",")))
        for qid, v in n["answers"].items():
            if v == SKIP_MARK:
                if qid not in skipped:
                    errs.append(f"{n['note_id']} {qid}: 表里是「—」但名单没说这题不问")
                continue
            if qid in skipped:
                errs.append(f"{n['note_id']} {qid}: 名单说这题不问(灰格), 表里却有答案 {v!r}")
                continue
            if v in (None, ""):
                continue                       # 没答, 汇总时点名
            if v not in fb.closed_set(qidx[qid]):
                errs.append(f"{n['note_id']} {qid}: 答案 {v!r} 不在闭集 {fb.closed_set(qidx[qid])}")
    return errs


def build_rows(notes: list[dict], bank: dict, extractor: str, run_tag: str) -> tuple[list[dict], list[str]]:
    qidx = fb.question_index(bank)
    rows, blanks = [], []
    now = _iso_now()
    for n in notes:
        for qid, v in n["answers"].items():
            if v == SKIP_MARK:
                continue
            if v in (None, ""):
                blanks.append(f"{n['note_id']}:{qid}")
                continue
            rows.append({
                "subject_type": "note", "subject_id": n["note_id"],
                "question_id": qid, "question_version": int(qidx[qid].get("version") or 1),
                "bank_version": bank["bank_version"], "bank_sha256": bank["_sha256"],
                "extractor": extractor, "run_tag": run_tag,
                "answer": v, "evidence": None, "prob": n["probs"].get(qid),
                "invalid_reason": None, "extracted_at": now,
            })
    return rows, blanks


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--file", action="append", required=True, type=Path, help="填完的 xlsx, 可重复")
    ap.add_argument("--extractor", required=True, help="human:<姓名> 或 jev:<版本>")
    ap.add_argument("--run-tag", default=DEFAULT_RUN_TAG)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--write", action="store_true", help="真的写库; 不给就只校验")
    args = ap.parse_args()

    if not _EXTRACTOR_RE.match(args.extractor):
        raise SystemExit(f"extractor 要写成 human:<姓名> 或 jev:<版本>, 实得 {args.extractor!r}")
    if args.extractor.startswith("human:") and len(args.file) > 1:
        raise SystemExit("human:<姓名> 一个人只有一张表; 多张表请分开跑, 各写各的名字")

    bank = fb.load_bank()
    manifest = load_manifest(args.manifest)
    all_rows: list[dict] = []
    for path in args.file:
        who, notes = read_sheet(path, bank)
        errs = validate(path, who, notes, manifest, bank)
        if errs:
            for e in errs[:20]:
                logger.error("%s: %s", path.name, e)
            raise SystemExit(f"{path.name}: {len(errs)} 处校验不过, 整份不写")
        rows, blanks = build_rows(notes, bank, args.extractor, args.run_tag)
        with_prob = sum(1 for r in rows if r["prob"] is not None)
        logger.info("%s: 标注员 %s · %d 篇 · %d 格答案 · %d 格没答 · %d 格带概率",
                    path.name, who, len(notes), len(rows), len(blanks), with_prob)
        if blanks:
            logger.warning("%s: 没答的格子(不写行): %s%s", path.name, ", ".join(blanks[:10]),
                           " …" if len(blanks) > 10 else "")
        all_rows.extend(rows)

    # 主键里没有"哪张表": 同一 extractor 下同一篇答了两次(A/B、A/C 各重叠 25 篇), 后写的会把
    # 先写的盖掉, 双标那一半就丢了。人是一人一名字不会撞; 一个模型填三张表就会 —— 要它保留
    # 重叠, extractor 得带上表的字母(jev:1.13.0-A / -B / -C), 每张单独跑。
    seen: dict[tuple[str, str], int] = {}
    for r in all_rows:
        seen[(r["subject_id"], r["question_id"])] = seen.get((r["subject_id"], r["question_id"]), 0) + 1
    dup = sorted({k[0] for k, c in seen.items() if c > 1})
    if dup:
        raise SystemExit(f"{len(dup)} 篇在多张表里都答了(如 {dup[:3]}), 同一 extractor={args.extractor!r} 下会互相覆盖; "
                         "给每张表不同的 extractor(如 jev:1.13.0-A)并分开跑")

    logger.info("合计 %d 行 → note_feature_answers (extractor=%s, run_tag=%s)%s",
                len(all_rows), args.extractor, args.run_tag, "" if args.write else " [dry-run, 没写]")
    if not args.write:
        return 0
    sb = get_supabase_client()
    for i in range(0, len(all_rows), UPSERT_CHUNK):
        sb.schema("truth_vault").table("note_feature_answers").upsert(all_rows[i:i + UPSERT_CHUNK]).execute()
    logger.info("写完 %d 行", len(all_rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
