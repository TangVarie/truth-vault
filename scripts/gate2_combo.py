"""
gate2_combo.py
═══════════════════════════════════════════════════════════════════════════

闸二后半 · 组合进不进 L2 (docs/28 §6.2「组合进不进 L2」+ 附录 B.3 / B.4) 的可执行版。
单个特征值的四条判据在 gate2_run.py; 这里回答另一个问题: 把原子题整体加进打分器, 比只用 essence 好多少。

打分器 (与 l2-feasibility §8.6 同一个, 最笨的那个): 每个特征 = 一个 token —— essence 四列
(L:情绪杠杆 / F:内容形式 / A:人性原型 / U:目标人群) 与原子题答案 (Q:题号=答案, 含 code:v1 的代码特征)。
留一项目: 给目标项目打分时, 权重只用【其他项目】的笔记算, w = ln((爆 + 1) / (趴 + 1)); 一篇笔记的分 = 它带的
特征权重的平均。三种打分器: tag (只 essence) / q (只原子题) / both (合并)。

判据 (docs/28 §6.2, 预注册, 数字不在这里改):
  ① 加权 AUC (按项目正例数加权, 只算正例 ≥ 5 的项目; 项目内中位秩 AUC): both − tag ≥ 0.02;
  ② 按项目分层有放回自助抽笔记 1,000 次, 「both − tag」的 95% 区间下界 > 0;
  ③ 最低 20% 那一档 (项目内按分排, 各项目最低 20% 合起来) 的爆率: both ≤ tag;
  ④ 反证 B.4: 项目内置换标签 20 次, both 的加权 AUC 平均落在 0.47–0.53, 且没有一次 ≥ 真实那一跑。
  四条全过 → enter_l2 = true。

快照与 gate2_run 同一套 (preregistration_check / snapshot_answers): 题库 frozen、--sha 是 digest 前缀、快照内 (笔记, 题)
唯一。评估集 = gate2_run 的分析集 (有 essence、正文 ≥ 50 字) ∩ 快照里【每个】抽取器都答过的篇 —— 混着"只有代码特征"
的篇, q 打分器在不同笔记上用的是不同的特征集, AUC 没有意义 (D-106)。占位题不进特征; 闸一 fail 的题默认也不进
(它们没过"测得准", --include-unreliable 只给对照用)。

    cd scripts && python gate2_combo.py --sha ba0f570c --extractors code:v1,llm:claude-sonnet-5-5 \
        --out ../data-analysis/feature-gate2-combo-<日期>.md --json-out combo.json
    … --fixture some.json   # 离线 (CI 夹具): {notes:[{note_id, project_id, y, has_essence, body_len, emotional_lever, …}], answers:[…]}

只出报告, 不写库: 进不进 L2 是 DECISIONS 里的一条决定, 不是一行数据。
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Optional

import feature_bank as fb
import gate2_run as G

VARIANTS = ("tag", "q", "both")
MIN_POS = 5
AUC_GAIN = 0.02
PERM_BAND = (0.47, 0.53)


# ── 特征 ─────────────────────────────────────────────────────────────────────

def _as_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v if x not in (None, "")]
    return [str(v)] if str(v) else []


def tag_features(note: dict) -> set[str]:
    out = {"L:" + x for x in _as_list(note.get("emotional_lever"))}
    out |= {"F:" + x for x in _as_list(note.get("content_format"))}
    out |= {"A:" + x for x in _as_list(note.get("human_truth_archetype"))}
    out |= {"U:" + x for x in _as_list(note.get("target_audience"))}
    return out


def build_eval(dataset: dict, bank: dict, *, sha: str, extractors: list[str], include_unreliable: bool = False,
               projects: Optional[set[str]] = None) -> tuple[list[dict], dict]:
    """评估集 + 每篇三套特征。回 (notes, meta)。notes 每篇带 feats = {tag: set, q: set, both: set}。"""
    answers = G.snapshot_answers(dataset, sha, extractors)
    placebo = {q["id"] for q in bank.get("placebo") or []}
    excluded = set() if include_unreliable else G.gate1_unreliable(bank)
    ext_of: dict[str, set[str]] = defaultdict(set)
    qf: dict[str, set[str]] = defaultdict(set)
    for a in answers:
        ext_of[a["subject_id"]].add(a["extractor"])
        if a.get("answer") is None or a["question_id"] in placebo or a["question_id"] in excluded:
            continue
        qf[a["subject_id"]].add(f"Q:{a['question_id']}={a['answer']}")
    want = set(extractors)
    notes = []
    dropped_partial = 0
    for n in G.analysis_notes(dataset["notes"]):
        if projects is not None and n["project_id"] not in projects:
            continue
        if ext_of.get(n["note_id"], set()) != want:
            if ext_of.get(n["note_id"]):
                dropped_partial += 1
            continue
        t, q = tag_features(n), qf.get(n["note_id"], set())
        if not t or not q:
            continue
        notes.append({"note_id": n["note_id"], "project_id": n["project_id"], "y": int(n["y"]),
                      "feats": {"tag": t, "q": q, "both": t | q}})
    meta = {"n_answers": len(answers), "excluded_questions": sorted(excluded),
            "dropped_partial_extractors": dropped_partial}
    return notes, meta


# ── 打分 + AUC ──────────────────────────────────────────────────────────────

def lopo_scores(notes: list[dict], ys: list[int], variant: str) -> list[Optional[float]]:
    """留一项目: 权重用其他项目的笔记算。ys 与 notes 对齐 (置换时传打乱的标签)。"""
    tot = defaultdict(lambda: [0, 0])                                # feat → [爆, 趴]
    per = defaultdict(lambda: defaultdict(lambda: [0, 0]))           # project → feat → [爆, 趴]
    for n, y in zip(notes, ys):
        for f in n["feats"][variant]:
            tot[f][0 if y else 1] += 1
            per[n["project_id"]][f][0 if y else 1] += 1
    out: list[Optional[float]] = []
    for n in notes:
        mine = per[n["project_id"]]
        ws = []
        for f in n["feats"][variant]:
            pos = tot[f][0] - mine[f][0]
            neg = tot[f][1] - mine[f][1]
            if pos + neg == 0:
                continue                                             # 这个特征只在本项目出现: 没有外部证据
            ws.append(math.log((pos + 1.0) / (neg + 1.0)))
        out.append(sum(ws) / len(ws) if ws else None)
    return out


def auc_midrank(scores: list[float], ys: list[int]) -> Optional[float]:
    """Mann–Whitney: 中位秩 (并列取平均秩)。"""
    n1 = sum(ys)
    n0 = len(ys) - n1
    if n1 == 0 or n0 == 0:
        return None
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    rsum = sum(r for r, y in zip(ranks, ys) if y)
    return (rsum - n1 * (n1 + 1) / 2.0) / (n1 * n0)


def weighted_auc(by_proj: dict[str, tuple[list[float], list[int]]]) -> tuple[Optional[float], dict]:
    num = den = 0.0
    per = {}
    for p, (s, y) in by_proj.items():
        pos = sum(y)
        if pos < MIN_POS:
            continue
        a = auc_midrank(s, y)
        if a is None:
            continue
        per[p] = (a, pos)
        num += a * pos
        den += pos
    return (num / den if den else None), per


def _group(notes: list[dict], scores: dict[str, list[Optional[float]]], ys: list[int], idx: Iterable[int]):
    """按项目分组, 只留三套分都有的篇 (配对比较)。回 {variant: {project: (scores, ys)}}。"""
    g = {v: defaultdict(lambda: ([], [])) for v in VARIANTS}
    for i in idx:
        if any(scores[v][i] is None for v in VARIANTS):
            continue
        p = notes[i]["project_id"]
        for v in VARIANTS:
            g[v][p][0].append(scores[v][i])
            g[v][p][1].append(ys[i])
    return g


def bottom_quintile_rate(by_proj: dict[str, tuple[list[float], list[int]]], frac: float = 0.2) -> dict:
    """项目内按分升序, 取最低 frac (至少 1 篇; 并列按出现顺序), 各项目合起来算爆率; 其余合起来算一个。"""
    lo_n = lo_pos = hi_n = hi_pos = 0
    for s, y in by_proj.values():
        k = max(1, round(frac * len(s)))
        order = sorted(range(len(s)), key=lambda i: s[i])
        low = set(order[:k])
        for i in range(len(s)):
            if i in low:
                lo_n += 1
                lo_pos += y[i]
            else:
                hi_n += 1
                hi_pos += y[i]
    return {"bottom_n": lo_n, "bottom_rate": lo_pos / lo_n if lo_n else None,
            "rest_n": hi_n, "rest_rate": hi_pos / hi_n if hi_n else None}


def permute_within_project(notes: list[dict], seed: int) -> list[int]:
    rng = random.Random(seed)
    by_p: dict[str, list[int]] = defaultdict(list)
    for i, n in enumerate(notes):
        by_p[n["project_id"]].append(i)
    ys = [n["y"] for n in notes]
    out = list(ys)
    for p in sorted(by_p):
        idx = by_p[p]
        vals = [ys[i] for i in idx]
        rng.shuffle(vals)
        for i, v in zip(idx, vals):
            out[i] = v
    return out


def run_combo(notes: list[dict], *, boot: int = 1000, perms: int = 20, seed: int = 20261010) -> dict:
    if not notes:
        raise G.Gate2Refused("评估集 0 篇: 快照里没有同时被每个抽取器答过、又有 essence 的篇")
    ys = [n["y"] for n in notes]
    scores = {v: lopo_scores(notes, ys, v) for v in VARIANTS}
    g = _group(notes, scores, ys, range(len(notes)))
    real = {}
    per_proj = {}
    for v in VARIANTS:
        real[v], per_proj[v] = weighted_auc(g[v])
    if real["tag"] is None or real["both"] is None:
        raise G.Gate2Refused(f"没有正例 ≥ {MIN_POS} 的项目, 加权 AUC 算不出")
    gain = real["both"] - real["tag"]

    # ② 配对自助: 项目内有放回抽篇, 三套分一起抽 (同一篇同一次)
    rng = random.Random(seed)
    proj_idx: dict[str, list[int]] = defaultdict(list)
    for i, n in enumerate(notes):
        if all(scores[v][i] is not None for v in VARIANTS):
            proj_idx[n["project_id"]].append(i)
    diffs = []
    for _ in range(boot):
        pick = []
        for p in sorted(proj_idx):
            ids = proj_idx[p]
            pick.extend(ids[rng.randrange(len(ids))] for _ in ids)
        gb = _group(notes, scores, ys, pick)
        a_tag, _ = weighted_auc(gb["tag"])
        a_both, _ = weighted_auc(gb["both"])
        if a_tag is not None and a_both is not None:
            diffs.append(a_both - a_tag)
    diffs.sort()
    ci = (diffs[int(0.025 * (len(diffs) - 1))], diffs[int(math.ceil(0.975 * (len(diffs) - 1)))]) if diffs else (None, None)

    # ③ 最低 20%
    bq = {v: bottom_quintile_rate(g[v]) for v in VARIANTS}

    # ④ 置换反证
    perm = {v: [] for v in VARIANTS}
    for k in range(perms):
        yk = permute_within_project(notes, seed + 1000 + k)
        sk = {v: lopo_scores(notes, yk, v) for v in VARIANTS}
        gk = _group(notes, sk, yk, range(len(notes)))
        for v in VARIANTS:
            a, _ = weighted_auc(gk[v])
            perm[v].append(a)
    pb = [a for a in perm["both"] if a is not None]
    perm_mean = sum(pb) / len(pb) if pb else None
    perm_max = max(pb) if pb else None

    c1 = gain >= AUC_GAIN
    c2 = ci[0] is not None and ci[0] > 0
    c3 = (bq["both"]["bottom_rate"] is not None and bq["tag"]["bottom_rate"] is not None
          and bq["both"]["bottom_rate"] <= bq["tag"]["bottom_rate"])
    c4 = perm_mean is not None and PERM_BAND[0] <= perm_mean <= PERM_BAND[1] and perm_max < real["both"]
    return {"n_notes": len(notes), "n_pos": sum(ys), "auc": real, "per_project": per_proj, "gain": gain,
            "boot": {"n": len(diffs), "ci_low": ci[0], "ci_high": ci[1]}, "bottom": bq,
            "perm": {v: perm[v] for v in VARIANTS}, "perm_mean": perm_mean, "perm_max": perm_max,
            "criteria": {"auc_gain": c1, "boot_ci": c2, "bottom20": c3, "permutation": c4},
            "enter_l2": bool(c1 and c2 and c3 and c4)}


# ── 报告 ─────────────────────────────────────────────────────────────────────

def _f(v, d=3):
    return "—" if v is None else f"{v:.{d}f}"


def render(res: dict, meta: dict, *, sha: str, extractors: list[str]) -> str:
    c = res["criteria"]
    ok = lambda b: "过" if b else "**不过**"  # noqa: E731
    L = [f"# 闸二后半 · 组合进不进 L2 (docs/28 §6.2 + 附录 B.3 / B.4)", "",
         f"> 快照 `bank_sha256` 前缀 `{sha}` · 抽取器 {extractors} · 评估集 {res['n_notes']:,} 篇 (正例 {res['n_pos']:,}) · "
         f"闸一 fail 不进特征: {meta.get('excluded_questions') or '无'} · 只有部分抽取器答过而剔掉的篇 {meta.get('dropped_partial_extractors', 0)}",
         "", "| 打分器 | 加权 AUC | 置换 20 次 (均值 / 最大) |", "|---|---|---|"]
    for v, name in (("tag", "只 essence"), ("q", "只原子题"), ("both", "合并")):
        pv = [a for a in res["perm"][v] if a is not None]
        L.append(f"| {name} | {_f(res['auc'][v])} | {_f(sum(pv) / len(pv) if pv else None)} / {_f(max(pv) if pv else None)} |")
    b = res["boot"]
    bt, bb = res["bottom"]["tag"], res["bottom"]["both"]
    L += ["", "| 判据 | 实测 | 线 | 判 |", "|---|---|---|---|",
          f"| ① 合并 − 只 essence | {_f(res['gain'])} | ≥ {AUC_GAIN} | {ok(c['auc_gain'])} |",
          f"| ② 自助 {b['n']} 次 95% 区间 | [{_f(b['ci_low'])}, {_f(b['ci_high'])}] | 下界 > 0 | {ok(c['boot_ci'])} |",
          f"| ③ 最低 20% 爆率 (合并 / 只 essence) | {_f(bb['bottom_rate'])} / {_f(bt['bottom_rate'])} | 合并 ≤ 只 essence | {ok(c['bottom20'])} |",
          f"| ④ 置换反证 (合并) | 均值 {_f(res['perm_mean'])}, 最大 {_f(res['perm_max'])} vs 真实 {_f(res['auc']['both'])} | 均值 ∈ [{PERM_BAND[0]}, {PERM_BAND[1]}] 且最大 < 真实 | {ok(c['permutation'])} |",
          "", f"**进不进 L2: {'进' if res['enter_l2'] else '不进'}**", "",
          "## 逐项目 (正例 ≥ 5)", "", "| 项目 | 正例 | 只 essence | 只原子题 | 合并 |", "|---|---|---|---|---|"]
    for p in sorted(res["per_project"]["tag"], key=lambda p: -res["per_project"]["tag"][p][1]):
        row = [res["per_project"][v].get(p) for v in VARIANTS]
        L.append(f"| {p} | {row[0][1]} | " + " | ".join(_f(r[0]) if r else "—" for r in row) + " |")
    L += ["", "## 口径", "",
          "- 打分器、留一项目、中位秩 AUC 与附录 B.3 的 SQL 同一套; 评估集只留快照里每个抽取器都答过的篇, 三套分都算得出的才进配对比较。",
          "- 最低 20%: 项目内按分升序取最低 20% (至少 1 篇), 各项目合起来算爆率。",
          f"- 置换: 项目内打乱标签, 特征不动, 种子固定; 判据只看合并打分器, 另两套列着对照。"]
    return "\n".join(L) + "\n"


# ── 取数 (生产) ───────────────────────────────────────────────────────────────

def fetch(sb, *, bank: dict, sha: str, extractors: list[str], projects: Optional[set[str]]) -> dict:
    from _common import fetch_all_pages
    ds = G.fetch_dataset(sb, bank=bank, sha=sha, extractors=extractors, projects=projects)
    tags = {r["note_id"]: r for r in fetch_all_pages(
        sb.schema("truth_vault").table("notes")
          .select("note_id, emotional_lever, content_format, human_truth_archetype, target_audience"), order_by="note_id")}
    for n in ds["notes"]:
        t = tags.get(n["note_id"]) or {}
        for k in ("emotional_lever", "content_format", "human_truth_archetype", "target_audience"):
            n[k] = t.get(k)
    return ds


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[2])
    ap.add_argument("--sha", required=True)
    ap.add_argument("--extractors", required=True, help="逗号分隔, 与 gate2_run 同一个快照, 如 code:v1,llm:claude-sonnet-5-5")
    ap.add_argument("--bank", default=str(fb.BANK_PATH))
    ap.add_argument("--projects", default="")
    ap.add_argument("--include-unreliable", action="store_true", help="闸一 fail 的题也进特征 (只给对照用)")
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--perms", type=int, default=20)
    ap.add_argument("--seed", type=int, default=20261010)
    ap.add_argument("--allow-draft", action="store_true")
    ap.add_argument("--fixture", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args(argv)
    extractors = [e.strip() for e in args.extractors.split(",") if e.strip()]
    projects = {p.strip() for p in args.projects.split(",") if p.strip()} or None
    bank = fb.load_bank(args.bank)
    try:
        sha = G.preregistration_check(bank, args.sha, allow_draft=args.allow_draft)
        if args.fixture:
            dataset = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        else:
            from _common import get_supabase_client
            dataset = fetch(get_supabase_client(), bank=bank, sha=sha, extractors=extractors, projects=projects)
        G.assert_projects_present(dataset, projects)
        notes, meta = build_eval(dataset, bank, sha=sha, extractors=extractors,
                                 include_unreliable=args.include_unreliable, projects=projects)
        res = run_combo(notes, boot=args.boot, perms=args.perms, seed=args.seed)
    except G.Gate2Refused as exc:
        print(f"组合对比没跑: {exc}", file=sys.stderr)
        return 2
    report = render(res, meta, sha=sha, extractors=extractors)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
    else:
        print(report)
    if args.json_out:
        slim = {k: v for k, v in res.items() if k != "per_project"}
        slim["per_project"] = {v: {p: {"auc": a, "pos": n} for p, (a, n) in res["per_project"][v].items()} for v in VARIANTS}
        slim["meta"] = meta
        Path(args.json_out).write_text(json.dumps(slim, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"组合对比: 加权 AUC tag {_f(res['auc']['tag'])} / q {_f(res['auc']['q'])} / both {_f(res['auc']['both'])}; "
          f"进 L2 = {res['enter_l2']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
