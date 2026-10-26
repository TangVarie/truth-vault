#!/usr/bin/env python3
"""gate1_models.py —— 副题库 fq-v0.2-cand-reader 的闸一: 模型对模型 + owner 裁决 (D-128, docs/28 §6.1)。

没有人工标注员 (D-084), 闸一换成三趟模型 + owner 裁:
  A = fqr-g1-sonnet55-a (Sonnet 5.5)、B = fqr-g1-sonnet55-b (Sonnet 5.5 再跑一遍)、H = fqr-g1-haiku55 (Haiku 5.5);
  owner 的裁决落 fqr-g1-owner (extractor human:owner, ingest_gate1_review.py)。
gate1_agreement.py 是 Jev 那一轮的 (以 Jev 三张表为基准), 不动它; 只借它的 kappa / agree / load_pivot。

    cd scripts && python gate1_models.py --print-sql                  # 拿去只读 MCP / SQL 编辑器跑, 存成文件
    python gate1_models.py --from-json runs.json --out ../data-analysis/gate1-reader-2026-10-27.md \
        --cells-out ../data-analysis/gate1-reader-cells-2026-10-27.csv
    python gate1_models.py --from-json runs.json --owner-run-tag fqr-g1-owner ...   # 收完 owner 裁决后的终版

判法 (D-128 写死, 这里只照做):
  · 线: Sonnet A 对 B 一致率 ≥ 0.90; A 对参考一致率 ≥ 0.85 且 κ ≥ 0.60; A 的证据无效率 ≤ 3%;
    owner 从每题三趟一致的格里抽 20 个复核, 推翻 > 2 个这题不过。
  · 参考 = 三趟不全一致的格由 owner 裁 + 三趟都一致的格 (owner 复核过的一致格以 owner 为准)。
    「不全一致」按原始取值算 (6 个选项), 任一趟没答 (校验没过) 也算不一致 —— 那一格也给 owner。
  · reader_ask_form 按合并后的 3 档判 (可答 = 挑一个 + 说自己的; 其他问法 = 求推荐 + 找同类 + 求解答; 没问读者),
    κ 还要在「至少一方不是没问读者」的子集上 ≥ 0.60; 6 个选项的表、问了读者之间「可答 vs 其他问法」只报告。
  · invites_sharing v2: κ 只在 A 层 (样本名单的 stratum) 上算; 一致率在全部 200 篇上算; 全部的 κ、B 层的一致率只报告。
  · 一致率 / κ 只数两边都答了的格; κ 没定义 (一边只有一种取值) 报「不可算」→ kappa_undefined。
  · 证据无效率 = (evidence_not_found + evidence_too_long) ÷ 问了的格 (不算 no_title / text_too_short /
    api_error / gateway_filtered)。
  · 「分组 vs 单问」不适用 (每组一题)。

先钉死再算 (拒算 = 退出 2, 列出看到了什么):
  · 一趟 (run_tag) 里只许一个 extractor、一个 bank_sha256 (= --bank-sha, 默认题库自己的 sha; 主题库 ba0f570c 直接拒)、
    每题一个 question_version (= 题库里的版本)、每格一行;
  · 三趟都要覆盖名单 × 两题的每一格 (答了 + 没过校验 + 不问的都算有行), 名单外的篇不许出现;
  · owner 的行只许 human:owner、同一个 sha / 版本、名单内、答案在闭集里。
  · --bank 只收副题库 (键或路径); 拿主题库来算 → 拒。

不出正文、不出证据: SQL 不选 evidence 列, --from-json 读进来的行只留白名单里的列 (subject_id, question_id,
question_version, bank_sha256, extractor, run_tag, answer, invalid_reason)。报告 / 格子表只有 note_id、题号、
取值和计数, 能进仓库。

格子表 (--cells-out, 每行一格): cell_id = <note_id>:<question_id>, kind = disagree (给 owner 裁) / spot (20 个复核,
按 sha256(种子:cell_id) 在一致格里取, 只看模型的答案, 和 owner 裁没裁无关) / agree / skip (三趟都不问)。
build_gate1_review_sheet.py 从它做表, ingest_gate1_review.py 拿它对账。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import feature_bank as fb
from gate1_agreement import agree, kappa, load_pivot
from gate1_labels import SHORT
from gate1_sample import SampleRefused, read_manifest

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = ROOT / "data-analysis" / "gate1-reader-sample-2026-10-26.csv"
DEFAULT_RUNS = ("A=fqr-g1-sonnet55-a@llm:claude-sonnet-5-5",
                "B=fqr-g1-sonnet55-b@llm:claude-sonnet-5-5",
                "H=fqr-g1-haiku55@llm:claude-haiku-5-5")
LABELS = ("A", "B", "H")
OWNER_RUN_TAG = "fqr-g1-owner"
OWNER_EXTRACTOR = "human:owner"
PASS_AB = 0.90
PASS_AGREE = 0.85
PASS_KAPPA = 0.60
PASS_EVIDENCE = 0.03
SPOT_N = 20
SPOT_MAX_OVERTURN = 2
SPOT_SEED = "fqr-g1-2026-10-26:spot"
# D-128 的合并 3 档。只认这一份; 载入题库时和 yaml 的 merged_contrasts / contrast_base_excludes 对一遍。
MERGED = {"挑一个": "可答", "说自己的": "可答", "求推荐": "其他问法", "找同类": "其他问法", "求解答": "其他问法",
          "没问读者": "没问读者"}
MERGED_Q = "reader_ask_form"
STRATUM_KAPPA_Q = "invites_sharing"            # κ 只在 A 层算
NOT_ASKED = frozenset({fb.INVALID_NO_TITLE, fb.INVALID_TEXT_TOO_SHORT, fb.INVALID_API, fb.INVALID_FILTERED, "dry_run"})
STRUCTURAL = frozenset({fb.INVALID_NO_TITLE, fb.INVALID_TEXT_TOO_SHORT})
EVIDENCE_BAD = frozenset({fb.INVALID_EVIDENCE_NOT_FOUND, fb.INVALID_EVIDENCE_TOO_LONG})
ROW_COLUMNS = ("subject_id", "question_id", "question_version", "bank_sha256", "extractor", "run_tag", "answer",
               "invalid_reason")
CELL_COLUMNS = ("cell_id", "note_id", "question_id", "stratum", "kind", "A", "B", "H", "A_reason", "B_reason",
                "H_reason", "owner", "reference")
_RUN_SPEC = re.compile(r"^(?P<label>[A-Z])=(?P<tag>[A-Za-z0-9][A-Za-z0-9_.-]{0,39})@(?P<ext>llm:[A-Za-z0-9][A-Za-z0-9_.:/-]{0,79})$")
_SHA = re.compile(r"^[0-9a-f]{8,64}$")


class Gate1Refused(Exception):
    """快照没钉住 / 覆盖不全 / 混了东西: 不算。"""


@dataclass(frozen=True)
class Run:
    label: str
    tag: str
    extractor: str


# ─────────────────────────────────────────────────────────────────────────
# 参数
# ─────────────────────────────────────────────────────────────────────────

def load_secondary(spec: str) -> dict:
    """--bank: BANKS 的键或 yaml 路径; 只收副题库, 主题库 (ba0f570c) 直接拒。走 load_bank_pair 的两道校验。"""
    path = fb.BANKS.get(spec, spec)
    try:
        bank, primary = fb.load_bank_pair(path)
    except ValueError as exc:
        raise Gate1Refused(str(exc)) from exc
    if bank["_sha256"] == primary["_sha256"] or bank["_sha256"].startswith(primary["_sha256"][:8]):
        raise Gate1Refused("这是主题库, 不是副题库 —— 主题库的闸一用 gate1_agreement.py")
    q = fb.question_index(bank).get(MERGED_Q)
    if q is not None:
        opts = [o["value"] for o in q["options"]]
        merged = {v for m in bank["gate2"]["merged_contrasts"] if m["question_id"] == MERGED_Q for v in m["values"]}
        want = {v for v, lv in MERGED.items() if lv == "可答"}
        if set(opts) != set(MERGED) or merged != want or set(q.get("contrast_base_excludes") or []) != {"没问读者"}:
            raise Gate1Refused(f"{MERGED_Q} 的选项 / 合并 / 剔除和 D-128 的 3 档对不上: 选项 {opts}, 合并 {sorted(merged)}")
    return bank


def parse_runs(specs: list[str], bank: dict) -> list[Run]:
    runs = []
    for s in specs:
        m = _RUN_SPEC.match(s)
        if not m:
            raise Gate1Refused(f"--run {s!r} 要写成 L=<run_tag>@llm:<model>")
        err = fb.check_run_tag(bank, m.group("tag"))
        if err:
            raise Gate1Refused(err)
        runs.append(Run(m.group("label"), m.group("tag"), m.group("ext")))
    if tuple(sorted(r.label for r in runs)) != tuple(sorted(LABELS)):
        raise Gate1Refused(f"三趟要正好是 {LABELS} (D-128: Sonnet A / Sonnet B / Haiku), 实得 {[r.label for r in runs]}")
    if len({r.tag for r in runs}) != len(runs):
        raise Gate1Refused("三趟的 run_tag 不能重复 (同 extractor 同 run_tag 是同一主键, 第二趟会被续跑跳过)")
    return sorted(runs, key=lambda r: LABELS.index(r.label))


def check_owner_tag(bank: dict, tag: str | None, runs: list[Run]) -> None:
    if tag is None:
        return
    err = fb.check_run_tag(bank, tag)
    if err:
        raise Gate1Refused(err)
    if tag in {r.tag for r in runs}:
        raise Gate1Refused(f"owner 的 run_tag {tag!r} 和模型的一趟重了")


def pivot_sql(bank: dict, runs: list[Run], owner_tag: str | None = OWNER_RUN_TAG) -> str:
    """只选白名单的列 (没有 evidence)。按 run_tag 取, 不按 extractor / sha 筛 —— 混进来的东西要看得见才拒得了。"""
    tags = [r.tag for r in runs] + ([owner_tag] if owner_tag else [])
    qids = [q["id"] for q in fb.llm_questions(bank)]
    lit = lambda xs: ", ".join(f"'{x}'" for x in xs)  # noqa: E731 (都过了正则 / 题库校验)
    return f"""-- gate1_models.py --print-sql · 只读 · 列: {', '.join(ROW_COLUMNS)} (不选 evidence)
select json_agg(json_build_array({', '.join(ROW_COLUMNS)})
                order by run_tag, subject_id, question_id, extractor)::text as pivot
from truth_vault.note_feature_answers
where subject_type = 'note'
  and run_tag in ({lit(tags)})
  and question_id in ({lit(qids)});"""


def load_rows(path: Path) -> list[dict]:
    """导出 → 行; 只留 ROW_COLUMNS (evidence 之类一律丢掉, 不进任何输出)。"""
    out = []
    for r in load_pivot(path):
        if isinstance(r, list):
            if len(r) != len(ROW_COLUMNS):
                raise Gate1Refused(f"导出的行有 {len(r)} 列, 应是 {len(ROW_COLUMNS)} ({ROW_COLUMNS})")
            out.append(dict(zip(ROW_COLUMNS, r)))
        elif isinstance(r, dict):
            missing = [c for c in ROW_COLUMNS if c not in r]
            if missing:
                raise Gate1Refused(f"导出的行缺列 {missing}")
            out.append({c: r[c] for c in ROW_COLUMNS})
        else:
            raise Gate1Refused("导出的行既不是数组也不是对象")
    return out


# ─────────────────────────────────────────────────────────────────────────
# 钉快照
# ─────────────────────────────────────────────────────────────────────────

def pin(rows: list[dict], bank: dict, runs: list[Run], manifest: list[dict], *, bank_sha: str | None = None,
        owner_tag: str | None = None) -> dict:
    """→ {label: {(note, qid): (answer, reason)}, "owner": {(note, qid): answer}, "sha": 全 sha}。不对就 Gate1Refused。"""
    sha = bank_sha or bank["_sha256"]
    if not _SHA.match(sha):
        raise Gate1Refused(f"--bank-sha {sha!r} 要是 8–64 位小写十六进制")
    if not bank["_sha256"].startswith(sha):
        raise Gate1Refused(f"--bank-sha {sha} 不是这份题库的 sha ({bank['_sha256'][:12]}): 题库改过就是另一次闸一")
    primary_sha = bank["primary_bank"]["sha256"]
    idx = fb.question_index(bank)
    qids = [q["id"] for q in fb.llm_questions(bank)]
    notes = [m["note_id"] for m in manifest]
    note_set = set(notes)
    by_tag: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_tag[r["run_tag"]].append(r)
    known = {r.tag for r in runs} | ({owner_tag} if owner_tag else set())
    stray = sorted(set(by_tag) - known)
    if stray:
        raise Gate1Refused(f"导出里有没点名的 run_tag {stray}")
    problems: list[str] = []
    out: dict = {"sha": None}

    def common(label: str, rs: list[dict], want_ext: str) -> None:
        exts = sorted({r["extractor"] for r in rs})
        if exts != [want_ext]:
            problems.append(f"{label}: extractor 应只有 {want_ext}, 实得 {exts}")
        shas = sorted({r["bank_sha256"] for r in rs})
        if any(s.startswith(primary_sha[:8]) for s in shas):
            problems.append(f"{label}: 有行在主题库 sha {primary_sha[:8]} 下 —— 那是主题库的答案, 不是副题库的")
        if len(shas) != 1 or not shas[0].startswith(sha):
            problems.append(f"{label}: bank_sha256 应只有 {sha[:12]}…, 实得 {[s[:12] for s in shas]}")
        else:
            out["sha"] = out["sha"] or shas[0]
            if out["sha"] != shas[0]:
                problems.append(f"{label}: sha {shas[0][:12]} 和别的趟 {out['sha'][:12]} 不同")
        for qid in qids:
            vs = sorted({int(r["question_version"]) for r in rs if r["question_id"] == qid})
            if vs and vs != [int(idx[qid]["version"])]:
                problems.append(f"{label}: {qid} 的 question_version 应是 {idx[qid]['version']}, 实得 {vs}")
        unknown_q = sorted({r["question_id"] for r in rs} - set(qids))
        if unknown_q:
            problems.append(f"{label}: 不是本库的题 {unknown_q}")
        cnt = Counter((r["subject_id"], r["question_id"]) for r in rs)
        dup = [k for k, c in cnt.items() if c > 1]
        if dup:
            problems.append(f"{label}: {len(dup)} 格有多行, 如 {dup[0]}")
        outside = sorted({r["subject_id"] for r in rs} - note_set)
        if outside:
            problems.append(f"{label}: {len(outside)} 篇不在名单里, 如 {outside[:3]} —— 跑错了名单")

    for run in runs:
        rs = by_tag.get(run.tag, [])
        common(f"{run.label} ({run.tag})", rs, run.extractor)
        cells = {(r["subject_id"], r["question_id"]): (r["answer"], r["invalid_reason"]) for r in rs}
        missing = [(n, q) for n in notes for q in qids if (n, q) not in cells]
        if missing:
            problems.append(f"{run.label} ({run.tag}): 覆盖不全, 缺 {len(missing)} / {len(notes) * len(qids)} 格, 如 {missing[0]}"
                            " —— 没跑完就再触发一次 (续跑只补缺的)")
        for (n, q), (ans, why) in cells.items():
            if ans is not None and q in idx and ans not in fb.closed_set(idx[q]):
                problems.append(f"{run.label}: {n}/{q} 的答案 {ans!r} 不在闭集")
                break
        out[run.label] = cells
    owner: dict = {}
    if owner_tag:
        rs = by_tag.get(owner_tag, [])
        if rs:
            common(f"owner ({owner_tag})", rs, OWNER_EXTRACTOR)
        for r in rs:
            if r["answer"] not in fb.closed_set(idx.get(r["question_id"], {"type": "bool"})):
                problems.append(f"owner: {r['subject_id']}/{r['question_id']} 的裁决 {r['answer']!r} 不在闭集")
                break
            owner[(r["subject_id"], r["question_id"])] = r["answer"]
    out["owner"] = owner
    if problems:
        raise Gate1Refused("拒算 —— 先钉死快照:\n  - " + "\n  - ".join(problems))
    return out


# ─────────────────────────────────────────────────────────────────────────
# 格子 + 指标
# ─────────────────────────────────────────────────────────────────────────

def level(qid: str, v: str | None) -> str | None:
    """判定用的档: reader_ask_form → 合并 3 档; 别的题原样。"""
    if v is None:
        return None
    return MERGED[v] if qid == MERGED_Q else v


def spot_rank(cell_id: str) -> str:
    return hashlib.sha256(f"{SPOT_SEED}:{cell_id}".encode("utf-8")).hexdigest()


def build_cells(pinned: dict, bank: dict, manifest: list[dict]) -> list[dict]:
    qids = [q["id"] for q in fb.llm_questions(bank)]
    owner = pinned["owner"]
    cells = []
    for m in manifest:
        for q in qids:
            k = (m["note_id"], q)
            got = {L: pinned[L][k] for L in LABELS}
            ans = {L: got[L][0] for L in LABELS}
            why = {L: got[L][1] for L in LABELS}
            if all(why[L] in STRUCTURAL for L in LABELS):
                kind = "skip"
            elif all(ans[L] is not None for L in LABELS) and len({ans[L] for L in LABELS}) == 1:
                kind = "agree"
            else:
                kind = "disagree"
            cells.append({"cell_id": f"{m['note_id']}:{q}", "note_id": m["note_id"], "question_id": q,
                          "stratum": m["stratum"], "kind": kind, **ans,
                          **{f"{L}_reason": why[L] for L in LABELS}, "owner": owner.get(k)})
    for q in qids:
        agreed = sorted((c for c in cells if c["question_id"] == q and c["kind"] == "agree"),
                        key=lambda c: spot_rank(c["cell_id"]))
        for c in agreed[:SPOT_N]:
            c["kind"] = "spot"
    for c in cells:
        if c["owner"] is not None:
            c["reference"] = c["owner"]
        elif c["kind"] in ("agree", "spot"):
            c["reference"] = c["A"]
        else:
            c["reference"] = None
    return cells


def _pairs(cells, qid, left, right, lv=True, where=lambda c: True):
    f = (lambda v: level(qid, v)) if lv else (lambda v: v)
    return [(f(c[left]), f(c[right])) for c in cells
            if c["question_id"] == qid and where(c) and c.get(left) is not None and c.get(right) is not None]


def _line(pairs, need_agree=None, need_kappa=None) -> dict:
    a, k = agree(pairs), kappa(pairs)
    ok_a = None if a is None else (a >= need_agree if need_agree is not None else None)
    ok_k = None if k is None else (k >= need_kappa if need_kappa is not None else None)
    return {"n": len(pairs), "agree": a, "kappa": k, "ok_agree": ok_a, "ok_kappa": ok_k}


def evaluate(cells: list[dict], bank: dict, has_owner: bool) -> dict:
    qids = [q["id"] for q in fb.llm_questions(bank)]
    res: dict = {}
    for q in qids:
        cs = [c for c in cells if c["question_id"] == q]
        r: dict = {"kinds": dict(Counter(c["kind"] for c in cs))}
        # 证据无效率 / 无效原因 (每趟)
        r["invalid"] = {}
        for L in LABELS:
            asked = [c for c in cs if c[f"{L}_reason"] not in NOT_ASKED]
            bad = sum(1 for c in asked if c[f"{L}_reason"] in EVIDENCE_BAD)
            r["invalid"][L] = {"asked": len(asked), "evidence_bad": bad,
                               "rate": (bad / len(asked)) if asked else None,
                               "reasons": dict(Counter(c[f"{L}_reason"] for c in cs if c[f"{L}_reason"]))}
        ev = r["invalid"]["A"]["rate"]
        r["line_evidence"] = None if ev is None else ev <= PASS_EVIDENCE
        # 模型之间
        r["AB"] = _line(_pairs(cs, q, "A", "B"), PASS_AB)
        r["AB_raw"] = _line(_pairs(cs, q, "A", "B", lv=False))
        r["AH"] = _line(_pairs(cs, q, "A", "H"))
        r["BH"] = _line(_pairs(cs, q, "B", "H"))
        r["confusion_AB"] = dict(Counter(_pairs(cs, q, "A", "B", lv=False)))
        # owner
        dis = [c for c in cs if c["kind"] == "disagree"]
        spot = [c for c in cs if c["kind"] == "spot"]
        r["owner"] = {"disagree": len(dis), "disagree_ruled": sum(1 for c in dis if c["owner"] is not None),
                      "spot": len(spot), "spot_ruled": sum(1 for c in spot if c["owner"] is not None),
                      "spot_overturned": sum(1 for c in spot if c["owner"] is not None
                                             and level(q, c["owner"]) != level(q, c["A"])),
                      "spot_overturned_raw": sum(1 for c in spot if c["owner"] is not None and c["owner"] != c["A"]),
                      "agree_cells_ruled_outside_spot": sum(1 for c in cs if c["kind"] == "agree" and c["owner"] is not None)}
        r["all_wrong"] = sum(1 for c in cs if c["owner"] is not None
                             and all(c[L] is not None and c[L] != c["owner"] for L in LABELS))
        if has_owner:
            r["AR"] = _line(_pairs(cs, q, "A", "reference"), PASS_AGREE, PASS_KAPPA)
            r["AR_raw"] = _line(_pairs(cs, q, "A", "reference", lv=False))
            r["confusion_AR"] = dict(Counter(_pairs(cs, q, "A", "reference", lv=False)))
            r["no_reference"] = sum(1 for c in cs if c["kind"] == "disagree" and c["reference"] is None)
            if q == MERGED_Q:
                r["AR_asking"] = _line(_pairs(cs, q, "A", "reference",
                                              where=lambda c: not (c["A"] == "没问读者" and c["reference"] == "没问读者")),
                                       None, PASS_KAPPA)
                r["AR_ask_vs_other"] = _line(_pairs(cs, q, "A", "reference",
                                                    where=lambda c: c["A"] != "没问读者" and c["reference"] not in (None, "没问读者")))
            if q == STRATUM_KAPPA_Q:
                r["AR_stratumA"] = _line(_pairs(cs, q, "A", "reference", where=lambda c: c["stratum"] == "A"),
                                         None, PASS_KAPPA)
                r["AR_stratumB"] = _line(_pairs(cs, q, "A", "reference", where=lambda c: c["stratum"] == "B"))
        r["verdict"], r["why"] = _verdict(q, r, has_owner)
        res[q] = r
    return res


def _verdict(q: str, r: dict, has_owner: bool) -> tuple[str, list[str]]:
    """→ (pass / fail / kappa_undefined / pending, 理由)。线一条不过就 fail; 线都没不过但有 κ 没定义 → kappa_undefined。"""
    why, oks = [], []
    oks.append(("A 对 B 一致率 ≥ 0.90", r["AB"]["ok_agree"]))
    oks.append(("A 证据无效率 ≤ 3%", r["line_evidence"]))
    if not has_owner:
        return "pending", ["还没有 owner 裁决 (参考标签没有), 只看了 A 对 B 和证据无效率"] + \
            [f"{n}: {'过' if ok else ('不过' if ok is False else '不可算')}" for n, ok in oks]
    o = r["owner"]
    pending = []
    if o["spot_ruled"] < min(SPOT_N, o["spot"]):
        pending.append(f"复核只裁了 {o['spot_ruled']} / {min(SPOT_N, o['spot'])} 个一致格")
    oks.append(("A 对参考一致率 ≥ 0.85", r["AR"]["ok_agree"]))
    if q == STRATUM_KAPPA_Q:
        oks.append(("A 对参考 κ ≥ 0.60 (A 层)", r["AR_stratumA"]["ok_kappa"]))
    else:
        oks.append(("A 对参考 κ ≥ 0.60", r["AR"]["ok_kappa"]))
    if q == MERGED_Q:
        oks.append(("A 对参考 κ ≥ 0.60 (至少一方不是没问读者)", r["AR_asking"]["ok_kappa"]))
    oks.append((f"复核推翻 ≤ {SPOT_MAX_OVERTURN}", o["spot_overturned"] <= SPOT_MAX_OVERTURN if o["spot_ruled"] else None))
    for n, ok in oks:
        why.append(f"{n}: {'过' if ok else ('不过' if ok is False else '不可算')}")
    if any(ok is False for _, ok in oks):
        return "fail", why + pending
    if pending:
        return "pending", why + pending
    if any(ok is None for _, ok in oks):
        return "kappa_undefined", why
    return "pass", why


# ─────────────────────────────────────────────────────────────────────────
# 输出: 报告 / 格子表
# ─────────────────────────────────────────────────────────────────────────

def fmt(v) -> str:
    return "不可算" if v is None else f"{v:.2f}"


def _cell(line: dict) -> str:
    return f"{line['n']} · {fmt(line['agree'])} · {fmt(line['kappa'])}"


def cells_csv(cells: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CELL_COLUMNS)
    for c in cells:
        w.writerow(["" if c.get(k) is None else c[k] for k in CELL_COLUMNS])
    return buf.getvalue()


def read_cells(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        if tuple(rd.fieldnames or ()) != CELL_COLUMNS:
            raise Gate1Refused(f"{path}: 列应是 {CELL_COLUMNS}")
        cells = [{k: (v if v != "" else None) for k, v in r.items()} for r in rd]
    ids = [c["cell_id"] for c in cells]
    if len(ids) != len(set(ids)):
        raise Gate1Refused(f"{path}: cell_id 重复")
    for c in cells:
        if c["cell_id"] != f"{c['note_id']}:{c['question_id']}" or c["kind"] not in ("disagree", "spot", "agree", "skip"):
            raise Gate1Refused(f"{path}: 坏行 {c['cell_id']}")
    return cells


def build_report(res: dict, cells: list[dict], bank: dict, runs: list[Run], pinned: dict, manifest_path: Path,
                 manifest: list[dict], owner_tag: str | None, sql: str) -> str:
    mtext = manifest_path.read_bytes()
    L = []
    has_owner = bool(pinned["owner"])
    L.append(f"# 闸一 · 副题库 {bank['bank_version']}（{len(manifest)} 篇 × {len(res)} 题，三趟模型"
             + (" + owner 裁决）" if has_owner else "，owner 还没裁）"))
    L.append("")
    L.append(f"> 口径见 `scripts/gate1_models.py` 顶部与 D-128。题库 sha `{pinned['sha'][:12]}`；名单 "
             f"`{manifest_path.name}`（sha256 `{hashlib.sha256(mtext).hexdigest()[:12]}`，A 层 "
             f"{sum(1 for m in manifest if m['stratum'] == 'A')} / B 层 {sum(1 for m in manifest if m['stratum'] == 'B')}）。")
    L.append("> 三趟：" + "；".join(f"{r.label} = `{r.tag}` · `{r.extractor}`" for r in runs)
             + (f"；owner = `{owner_tag}` · `{OWNER_EXTRACTOR}`（{len(pinned['owner'])} 格）" if owner_tag else "") + "。")
    L.append(f"> 线：A 对 B 一致率 ≥ {PASS_AB:.2f}；A 对参考一致率 ≥ {PASS_AGREE:.2f} 且 κ ≥ {PASS_KAPPA:.2f}；"
             f"A 证据无效率 ≤ {PASS_EVIDENCE:.0%}；复核 {SPOT_N} 格推翻 ≤ {SPOT_MAX_OVERTURN}。读者怎么回答按合并 3 档判。"
             "格子写成 n · 一致率 · κ。")
    L.append("")
    L.append("## 判定")
    L.append("")
    L.append("| 题 | 判 | 理由 |")
    L.append("|---|---|---|")
    for q, r in res.items():
        L.append(f"| {SHORT.get(q, q)}（{q}） | **{r['verdict']}** | {'；'.join(r['why'])} |")
    L.append("")
    L.append("## 模型之间（判定档；读者怎么回答 = 合并 3 档）")
    L.append("")
    L.append("| 题 | A–B | A–B（原始取值） | A–H | B–H |")
    L.append("|---|---|---|---|---|")
    for q, r in res.items():
        L.append(f"| {SHORT.get(q, q)} | {_cell(r['AB'])} | {_cell(r['AB_raw'])} | {_cell(r['AH'])} | {_cell(r['BH'])} |")
    L.append("")
    L.append("## 没答的格（每趟）")
    L.append("")
    L.append("| 题 | 趟 | 问了的格 | 证据无效 | 证据无效率 | 原因分布 |")
    L.append("|---|---|---|---|---|---|")
    for q, r in res.items():
        for lab in LABELS:
            iv = r["invalid"][lab]
            reasons = "，".join(f"{k} {v}" for k, v in sorted(iv["reasons"].items())) or "—"
            rate = "—" if iv["rate"] is None else f"{iv['rate']:.1%}"
            L.append(f"| {SHORT.get(q, q)} | {lab} | {iv['asked']} | {iv['evidence_bad']} | {rate} | {reasons} |")
    L.append("")
    L.append("## owner 与参考")
    L.append("")
    L.append("| 题 | 不全一致的格（已裁） | 复核格（已裁 · 推翻 · 推翻原始） | 三趟全错 | 没有参考的格 | 表外的裁决 |")
    L.append("|---|---|---|---|---|---|")
    for q, r in res.items():
        o = r["owner"]
        L.append(f"| {SHORT.get(q, q)} | {o['disagree']}（{o['disagree_ruled']}） | {o['spot']}（{o['spot_ruled']} · "
                 f"{o['spot_overturned']} · {o['spot_overturned_raw']}） | {r['all_wrong']} | {r.get('no_reference', '—')} | "
                 f"{o['agree_cells_ruled_outside_spot']} |")
    if has_owner:
        L.append("")
        L.append("| 题 | A 对参考（判定档） | A 对参考（原始取值） | 子集 |")
        L.append("|---|---|---|---|")
        for q, r in res.items():
            extra = []
            if "AR_asking" in r:
                extra.append(f"至少一方不是没问读者 {_cell(r['AR_asking'])}")
                extra.append(f"问了读者之间 可答 vs 其他问法（只报告）{_cell(r['AR_ask_vs_other'])}")
            if "AR_stratumA" in r:
                extra.append(f"A 层 {_cell(r['AR_stratumA'])}")
                extra.append(f"B 层（只报告）{_cell(r['AR_stratumB'])}")
            L.append(f"| {SHORT.get(q, q)} | {_cell(r['AR'])} | {_cell(r['AR_raw'])} | {'；'.join(extra) or '—'} |")
    for q, r in res.items():
        for name, key in (("A × B", "confusion_AB"), ("A × 参考", "confusion_AR")):
            conf = r.get(key)
            if not conf:
                continue
            vals = list(fb.closed_set(fb.question_index(bank)[q]))
            L.append("")
            L.append(f"**{SHORT.get(q, q)} · {name}（行 = A，列 = {name.split(' × ')[1]}，原始取值）**")
            L.append("")
            L.append("| | " + " | ".join(vals) + " |")
            L.append("|---|" + "---|" * len(vals))
            for a in vals:
                L.append(f"| {a} | " + " | ".join(str(conf.get((a, b), 0) or "") for b in vals) + " |")
    L.append("")
    L.append("## 和主题库的交叉（只报告；A 的答案 × 名单里主题库 Sonnet ba0f570c 的答案）")
    L.append("")
    a_ans = {(c["note_id"], c["question_id"]): c["A"] for c in cells}
    mf = {m["note_id"]: m for m in manifest}
    t1 = Counter()
    t2 = Counter()
    for n, m in mf.items():
        raf = a_ans.get((n, MERGED_Q))
        if raf is not None:
            t1[(raf != "没问读者", "是" in (m.get("ear"), m.get("tiq")))] += 1
        inv = a_ans.get((n, STRATUM_KAPPA_Q))
        if inv is not None and raf is not None:
            t2[(inv == "是", raf == "说自己的")] += 1
    L.append("| 读者怎么回答 ≠ 没问读者 | 结尾问读者 或 标题是问句 = 是 | 否 |")
    L.append("|---|---|---|")
    for x in (True, False):
        L.append(f"| {'是' if x else '否'} | {t1[(x, True)]} | {t1[(x, False)]} |")
    L.append("")
    L.append("| 请读者讲经历 = 是 | 读者怎么回答 = 说自己的 | 其他 |")
    L.append("|---|---|---|")
    for x in (True, False):
        L.append(f"| {'是' if x else '否'} | {t2[(x, True)]} | {t2[(x, False)]} |")
    L.append("")
    L.append("（yaml 的 cross_check 说「说自己的」要证据在结尾时才该和请读者讲经历一致；这里不读证据，所以只是粗表。）")
    L.append("")
    L.append("## 取数 SQL")
    L.append("")
    L.append("```sql")
    L.append(sql)
    L.append("```")
    return "\n".join(L) + "\n"


def run(rows: list[dict], bank: dict, runs: list[Run], manifest_path: Path, *, bank_sha: str | None = None,
        owner_tag: str | None = None) -> tuple[str, list[dict], dict]:
    """纯函数入口 (CI 走这里): → (报告, 格子, 每题结果)。"""
    try:
        manifest = read_manifest(manifest_path)
    except SampleRefused as exc:
        raise Gate1Refused(str(exc)) from exc
    check_owner_tag(bank, owner_tag, runs)
    pinned = pin(rows, bank, runs, manifest, bank_sha=bank_sha, owner_tag=owner_tag)
    cells = build_cells(pinned, bank, manifest)
    res = evaluate(cells, bank, has_owner=bool(pinned["owner"]))
    report = build_report(res, cells, bank, runs, pinned, manifest_path, manifest, owner_tag,
                          pivot_sql(bank, runs, owner_tag))
    return report, cells, res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bank", default="reader", help="副题库: BANKS 的键或 yaml 路径 (主题库拒)")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--run", action="append", default=None, help="L=<run_tag>@llm:<model>, 三趟 A / B / H (默认见 DEFAULT_RUNS)")
    ap.add_argument("--bank-sha", default=None, help="钉住副题库 sha 前缀 (默认题库自己的)")
    ap.add_argument("--owner-run-tag", default=None, help=f"owner 裁决的 run_tag (收完裁决后给 {OWNER_RUN_TAG})")
    ap.add_argument("--print-sql", action="store_true")
    ap.add_argument("--from-json", type=Path)
    ap.add_argument("--out", type=Path, help="报告 markdown")
    ap.add_argument("--cells-out", type=Path, help="格子表 CSV (cell_id / 各趟答案 / 裁决, 没有正文)")
    a = ap.parse_args(argv)
    try:
        bank = load_secondary(a.bank)
        runs = parse_runs(a.run or list(DEFAULT_RUNS), bank)
        if a.print_sql:
            check_owner_tag(bank, a.owner_run_tag or OWNER_RUN_TAG, runs)
            print(pivot_sql(bank, runs, a.owner_run_tag or OWNER_RUN_TAG))
            return 0
        if not a.from_json:
            ap.error("要 --print-sql 或 --from-json (本脚本不连库)")
        report, cells, res = run(load_rows(a.from_json), bank, runs, a.manifest, bank_sha=a.bank_sha,
                                 owner_tag=a.owner_run_tag)
    except Gate1Refused as exc:
        print(f"拒算: {exc}", file=sys.stderr)
        return 2
    if a.out:
        a.out.write_text(report, encoding="utf-8")
        print(f"报告写到 {a.out}")
    if a.cells_out:
        text = cells_csv(cells)
        a.cells_out.write_text(text, encoding="utf-8")
        print(f"格子表写到 {a.cells_out} ({len(cells)} 格, sha256 {hashlib.sha256(text.encode('utf-8')).hexdigest()})")
    for q, r in res.items():
        print(f"{q}: {r['verdict']} · " + "；".join(r["why"]))
    if not a.out:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
