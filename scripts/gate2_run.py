#!/usr/bin/env python3
"""闸二 · 有区分度 (docs/28 §6.2) 的可执行版 —— 单个特征值的四条判据 + 状态 + feature_validation 行 + 报告 (D-093)。

docs/28 附录 B 只有 SQL 散句 (B.1 合并优势比、B.2 大项目方向), BH 校正、账号先验分层、状态赋值、报告都没有代码;
D-070 记着「闸二 SQL 仍在 docs/28 附录 B」。这个脚本把 §6.2 的判据原样落成代码, 纯 Python (requirements.lock 里没有
numpy / statsmodels), 与 statsmodels 的核对靠闭式: 单层时 Robins–Breslow–Greenland 方差恰等于 Woolf 的
1/a+1/b+1/c+1/d, 守卫 check_gate2_run.py 钉着这一点。

四条判据 (§6.2, 一字不改):
  1. 按项目分层的 Mantel–Haenszel 合并优势比, RGB 方差给 95% 区间 (B.1);
  2. Benjamini–Hochberg, q ≤ 0.10, 占位题同一个校正家族, bool 题只算「是」;
  3. 正例 ≥ 20 的大项目 (动态算) 逐个看方向, 最多一个反向; 只数该取值真出现过的项目 (B.2 两条纪律);
  4. 再按「项目 × 账号先验爆率」分层重算: 方向变了或点估计变化 > 30% → confounded。账号先验只用该账号更早发布的、
     已清洗标签的笔记, ≥ 3 篇才算, 三档: 无记录 / 低于项目基线 / 不低于。
状态: validated / reversed / no_signal / confounded / unreliable / insufficient (§6.2 表)。
反证 (跑之前): 占位题在任一方向都不许同时满足 1–3 条 —— 满足了整跑作废、一行不写。

数据: v_l2_labels (正例 = 清洗后的 爆/大爆, 负例 = 趴), 有 essence、正文 ≥ 50 字 (note_features.body_len; 没有 body_len 的
不剔)。快照: bank_sha256 前缀 + 抽取器集合 (B.3 的 :sha / :extractors), 快照内 (笔记, 题) 必须唯一, 否则不跑。
预注册: 问题库必须 status: frozen 且 digest 与 --sha 一致 (--allow-draft 只给 CI 夹具和试算用)。

用法:
    cd scripts && python gate2_run.py --sha ba0f570c --extractors code:v1,llm:claude-opus-4-6 \
        --run-tag gate2-2026-10-15 --out ../data-analysis/feature-gate2-2026-10-15.md            # 试算, 不写库
    … --write                                                                                   # 写 feature_validation
    … --fixture some.json                                                                       # 离线 (CI 夹具)
没做 (留第二步): B.3 组合对比 (留一项目 AUC + 配对自助) 与 B.4 置换反证 —— 那是「组合进不进 L2」的决定, 不是单个特征值的闸。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import feature_bank as fb

Z95 = 1.959964
STATUSES = ("validated", "no_signal", "reversed", "confounded", "unreliable", "insufficient")
PRIOR_NONE, PRIOR_BELOW, PRIOR_AT_OR_ABOVE = "none", "below", "at_or_above"


class Gate2Refused(RuntimeError):
    """预注册 / 快照 / 反证哪一条不满足, 整跑不许进行 (退出码 2)。"""


# ── 统计: 纯函数 ───────────────────────────────────────────────────────────────

def mh_odds_ratio(tables: Iterable[tuple[float, float, float, float]]) -> Optional[dict]:
    """Mantel–Haenszel 合并优势比 + Robins–Breslow–Greenland 方差 (docs/28 B.1 的公式原样)。
    n ≤ 1 的层跳过; 没有可用层、或 R / S 为 0 (某一方向在所有层都没出现) → None。"""
    R = S = PR = PSQR = QS = 0.0
    k = 0
    for a, b, c, d in tables:
        n = a + b + c + d
        if n <= 1:
            continue
        k += 1
        r, s = a * d / n, b * c / n
        P, Q = (a + d) / n, (b + c) / n
        R += r
        S += s
        PR += P * r
        PSQR += P * s + Q * r
        QS += Q * s
    if k == 0 or R <= 0 or S <= 0:
        return None
    or_ = R / S
    var = PR / (2 * R * R) + PSQR / (2 * R * S) + QS / (2 * S * S)
    se = math.sqrt(var)
    return {"or": or_, "ci_low": math.exp(math.log(or_) - Z95 * se),
            "ci_high": math.exp(math.log(or_) + Z95 * se), "se_log": se, "strata": k}


def wald_p(or_: float, se_log: float) -> float:
    """ln(OR) / se 的双侧 Wald p (与 statsmodels StratifiedTable 的 oddsratio_pooled 检验同口径)。"""
    if se_log <= 0:
        return 0.0 if or_ != 1 else 1.0
    z = abs(math.log(or_)) / se_log
    return math.erfc(z / math.sqrt(2))


def bh_qvalues(pvals: dict[Any, float]) -> dict[Any, float]:
    """Benjamini–Hochberg: q_i = min_{j ≥ i} (m · p_(j) / j), 按 p 升序, 单调不降。"""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    q: dict[Any, float] = {}
    running = 1.0
    for rank in range(m, 0, -1):
        key, p = items[rank - 1]
        running = min(running, m * p / rank)
        q[key] = min(1.0, running)
    return q


# ── 数据 ───────────────────────────────────────────────────────────────────────

def _parse_ts(v) -> Optional[datetime]:
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def analysis_notes(notes: list[dict], *, min_body: int = 50) -> list[dict]:
    """§6.2 的取数条件: 有 essence、正文 ≥ 50 字 (body_len 未知的不剔)。"""
    out = []
    for n in notes:
        if not n.get("has_essence"):
            continue
        bl = n.get("body_len")
        if bl is not None and bl < min_body:
            continue
        out.append(n)
    return out


def account_prior_strata(notes: list[dict], *, min_history: int = 3) -> dict[str, str]:
    """每篇的账号先验档: 该账号【更早发布】的已标签笔记 ≥ min_history 篇 → 爆率 vs 项目基线 (项目内平均 y)。"""
    baseline: dict[str, float] = {}
    by_proj: dict[str, list[int]] = defaultdict(list)
    for n in notes:
        by_proj[n["project_id"]].append(int(n["y"]))
    for p, ys in by_proj.items():
        baseline[p] = sum(ys) / len(ys)
    by_acct: dict[str, list[dict]] = defaultdict(list)
    for n in notes:
        if n.get("account_id") and _parse_ts(n.get("publish_time")):
            by_acct[n["account_id"]].append(n)
    strata: dict[str, str] = {n["note_id"]: PRIOR_NONE for n in notes}
    for acct, rows in by_acct.items():
        rows.sort(key=lambda r: _parse_ts(r["publish_time"]))
        seen_y: list[int] = []
        i = 0
        while i < len(rows):
            t = _parse_ts(rows[i]["publish_time"])
            j = i
            group = []
            while j < len(rows) and _parse_ts(rows[j]["publish_time"]) == t:   # 同一时刻发的互不算"更早"
                group.append(rows[j])
                j += 1
            if len(seen_y) >= min_history:
                rate = sum(seen_y) / len(seen_y)
                for n in group:
                    strata[n["note_id"]] = PRIOR_BELOW if rate < baseline[n["project_id"]] else PRIOR_AT_OR_ABOVE
            seen_y.extend(int(n["y"]) for n in group)
            i = j
    return strata


def contrast_tables(notes: list[dict], answered: dict[str, str], value: str,
                    stratum_of) -> dict[Any, list[float]]:
    """每层一张 2×2: a = 有该值且爆, b = 有且趴, c = 答了别的值且爆, d = 答了别的值且趴。没答 / 无效的不进。"""
    tabs: dict[Any, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    for n in notes:
        ans = answered.get(n["note_id"])
        if ans is None:
            continue
        has = ans == value
        y = int(n["y"])
        idx = (0 if y else 1) if has else (2 if y else 3)
        tabs[stratum_of(n)][idx] += 1
    return tabs


# ── 题库 → 要判的 (题, 版本, 取值, 预注册方向) ─────────────────────────────────

def bank_targets(bank: dict) -> list[dict]:
    """20 道模型题 + 8 道代码特征 + 3 道占位题。bool 只算「是」; choice 每个取值一行, 方向按取值 (没按取值写的记 ?)。"""
    out = []

    def _opt_value(o) -> str:
        """模型题的 options 是 [{value, means, example}], 代码特征的是纯字符串列表 —— 两种都认。"""
        if isinstance(o, dict):
            return str(o.get("value") or o.get("id") or o.get("name") or next(iter(o.values())))
        return str(o)

    def add(q: dict, kind: str):
        qid = q["id"]
        hyp = q.get("hypothesis")
        if q.get("type") == "choice":
            opts = q.get("options") or []
            vals = [_opt_value(o) for o in (opts if isinstance(opts, list) else list(opts))]
            for v in vals:
                h = hyp.get(v, "?") if isinstance(hyp, dict) else "?"
                out.append({"question_id": qid, "value": v, "hypothesis": h, "kind": kind,
                            "hyp_note": "" if isinstance(hyp, dict) else "choice 题 hypothesis 没按取值写, 按 ? 处理"})
        else:
            out.append({"question_id": qid, "value": "是", "hypothesis": (hyp if isinstance(hyp, str) else "?"),
                        "kind": kind, "hyp_note": ""})

    for q in fb.llm_questions(bank):
        add(q, "llm")
    for q in bank.get("code_features") or []:
        add(q, "code")
    for q in bank.get("placebo") or []:
        out.append({"question_id": q["id"], "value": "是", "hypothesis": "0", "kind": "placebo", "hyp_note": ""})
    return out


# ── 主流程 (纯函数: dataset + bank + 参数 → 结果) ─────────────────────────────

def run_gate2(dataset: dict, bank: dict, *, sha: str, extractors: list[str], run_tag: str,
              q_max: float = 0.10, min_support: int = 30, min_big: int = 3, big_pos: int = 20,
              confound_delta: float = 0.30, unreliable: Iterable[str] = (), allow_draft: bool = False,
              ignore_placebo_alarm: bool = False) -> dict:
    sha = sha.lower()
    if len(sha) < 8:
        raise Gate2Refused("--sha 至少 8 位十六进制前缀")
    if not bank["_sha256"].startswith(sha):
        raise Gate2Refused(f"问题库文件 digest {bank['_sha256'][:12]} 与 --sha {sha} 对不上: 预注册的方向来自题库文件, "
                           "文件和快照必须是同一份")
    if bank.get("status") != "frozen" and not allow_draft:
        raise Gate2Refused("问题库 status 不是 frozen —— 闸二跑之前先冻结 (status: frozen + frozen_sha256), 判据数字记进 "
                           "DECISIONS (docs/28 §6.2 预注册)。试算用 --allow-draft。")
    unreliable = set(unreliable)
    ext = set(extractors)

    # 快照内的答案 + 唯一性 (B.3)
    answers = [a for a in dataset["answers"]
               if a.get("subject_type", "note") == "note" and a.get("run_tag", "primary") == "primary"
               and str(a.get("bank_sha256", "")).lower().startswith(sha) and a.get("extractor") in ext]
    seen: dict[tuple[str, str], int] = defaultdict(int)
    for a in answers:
        seen[(a["subject_id"], a["question_id"])] += 1
    dups = sorted(k for k, v in seen.items() if v > 1)
    if dups:
        raise Gate2Refused(f"快照内 (笔记, 题) 不唯一: {len(dups)} 对, 如 {dups[:3]} —— 同一题被两个抽取器 / 两个版本答过, "
                           "先清快照再跑 (docs/28 B.3)")
    versions: dict[str, set[int]] = defaultdict(set)
    answered: dict[str, dict[str, str]] = defaultdict(dict)       # qid → note_id → answer (answer 非空)
    for a in answers:
        versions[a["question_id"]].add(int(a["question_version"]))
        if a.get("answer") is not None:
            answered[a["question_id"]][a["subject_id"]] = str(a["answer"])
    multi = {q: v for q, v in versions.items() if len(v) > 1}
    if multi:
        raise Gate2Refused(f"同一快照里一道题有多个版本: {multi} —— sha 应该钉住版本, 这不该发生")

    notes = analysis_notes(dataset["notes"])
    labeled_ids = {n["note_id"] for n in notes}
    pos_by_proj: dict[str, int] = defaultdict(int)
    for n in notes:
        pos_by_proj[n["project_id"]] += int(n["y"])
    big = {p for p, c in pos_by_proj.items() if c >= big_pos}
    prior = account_prior_strata(notes)

    rows: list[dict] = []
    pvals: dict[tuple[str, str], float] = {}
    for t in bank_targets(bank):
        qid, value = t["question_id"], t["value"]
        if qid not in versions:
            continue                                            # 这一跑的快照里没有这道题 (比如还没抽)
        qver = next(iter(versions[qid]))
        ans = {k: v for k, v in answered.get(qid, {}).items() if k in labeled_ids}
        by_proj = contrast_tables(notes, ans, value, lambda n: n["project_id"])
        support = sum(tab[0] + tab[1] for tab in by_proj.values())
        big_tabs = {p: tab for p, tab in by_proj.items() if p in big and (tab[0] + tab[1]) > 0}
        n_above = sum(1 for tab in big_tabs.values() if (tab[0] + .5) * (tab[3] + .5) > (tab[1] + .5) * (tab[2] + .5))
        n_below = sum(1 for tab in big_tabs.values() if (tab[0] + .5) * (tab[3] + .5) < (tab[1] + .5) * (tab[2] + .5))
        mh = mh_odds_ratio(by_proj.values())
        row = {"question_id": qid, "question_version": qver, "answer": value, "bank_version": bank["bank_version"],
               "gate2_run": run_tag, "hypothesis": t["hypothesis"], "kind": t["kind"],
               "support": int(support), "big_projects_n": len(big_tabs), "n_or_above_1": n_above, "n_or_below_1": n_below,
               "mh_odds_ratio": None, "ci_low": None, "ci_high": None, "q_value": None, "p_value": None,
               "mh_prior": None, "hyp_note": t["hyp_note"]}
        if mh is not None:
            row.update({"mh_odds_ratio": mh["or"], "ci_low": mh["ci_low"], "ci_high": mh["ci_high"]})
            row["p_value"] = wald_p(mh["or"], mh["se_log"])
            pvals[(qid, value)] = row["p_value"]
            by_prior = contrast_tables(notes, ans, value, lambda n: (n["project_id"], prior[n["note_id"]]))
            mh2 = mh_odds_ratio(by_prior.values())
            row["mh_prior"] = mh2["or"] if mh2 else None
        rows.append(row)

    qv = bh_qvalues(pvals) if pvals else {}
    placebo_alarm: list[str] = []
    for row in rows:
        key = (row["question_id"], row["answer"])
        row["q_value"] = qv.get(key)
        _assign_status(row, q_max=q_max, min_support=min_support, min_big=min_big,
                       confound_delta=confound_delta, unreliable=unreliable)
        if row["kind"] == "placebo" and row["_crit123"]:
            placebo_alarm.append(f"{row['question_id']}: OR {row['mh_odds_ratio']:.2f} "
                                 f"[{row['ci_low']:.2f}, {row['ci_high']:.2f}] q={row['q_value']:.3f} "
                                 f"大项目 {row['n_or_above_1']}↑/{row['n_or_below_1']}↓")
    if placebo_alarm and not ignore_placebo_alarm:
        raise Gate2Refused("反证没过: 占位题被判成「显著且稳定」—— 这一跑作废, 一行不写。" + " ; ".join(placebo_alarm)
                           + " (docs/28 §6.2 反证 ①; 多半是快照混了两份答案或标签漏了清洗)")

    big_desc = {p: pos_by_proj[p] for p in sorted(big)}
    return {"rows": rows, "placebo_alarm": placebo_alarm, "big_projects": big_desc,
            "n_notes": len(notes), "n_pos": sum(int(n["y"]) for n in notes),
            "n_answers": len(answers), "sha": sha, "extractors": sorted(ext), "run_tag": run_tag,
            "params": {"q_max": q_max, "min_support": min_support, "min_big": min_big, "big_pos": big_pos,
                       "confound_delta": confound_delta, "unreliable": sorted(unreliable)},
            "prior_strata": {k: sum(1 for v in prior.values() if v == k) for k in (PRIOR_NONE, PRIOR_BELOW, PRIOR_AT_OR_ABOVE)}}


def _assign_status(row: dict, *, q_max: float, min_support: int, min_big: int, confound_delta: float,
                   unreliable: set) -> None:
    """§6.2 状态表, 按表里的先后: unreliable → insufficient → no_signal (区间 / q / 方向不稳) → confounded → reversed / validated。"""
    or_, lo, hi, q = row["mh_odds_ratio"], row["ci_low"], row["ci_high"], row["q_value"]
    row["_crit123"] = False
    direction = None if or_ is None else ("+" if or_ > 1 else "-" if or_ < 1 else None)
    row["big_projects_same_dir"] = (row["n_or_above_1"] if direction == "+" else row["n_or_below_1"] if direction == "-" else 0)
    opposite = (row["n_or_below_1"] if direction == "+" else row["n_or_above_1"] if direction == "-" else 0)

    def done(status: str, why: str) -> None:
        row["status"] = status
        row["summary"] = _summary(row, why)

    if row["question_id"] in unreliable:
        return done("unreliable", "闸一没过")
    if row["support"] < min_support or row["big_projects_n"] < min_big:
        return done("insufficient", f"有该取值的笔记 {row['support']} 篇 / 有支持的大项目 {row['big_projects_n']} 个")
    if or_ is None or direction is None:
        return done("no_signal", "合并优势比算不出 (某一方向在所有项目都没出现)")
    if lo <= 1.0 <= hi:
        return done("no_signal", "95% 区间跨 1")
    if q is None or q > q_max:
        return done("no_signal", f"BH 校正后 q={q:.3f} > {q_max}")
    if opposite > 1:
        return done("no_signal", f"大项目方向不稳: {row['n_or_above_1']} 个 >1, {row['n_or_below_1']} 个 <1")
    row["_crit123"] = True
    mp = row["mh_prior"]
    if mp is None or (mp > 1) != (or_ > 1) or abs(mp - or_) / or_ > confound_delta:
        return done("confounded", f"按账号先验再分层后 OR {or_:.2f} → {('算不出' if mp is None else f'{mp:.2f}')}")
    hyp = row["hypothesis"]
    if hyp in ("+", "-") and hyp != direction:
        return done("reversed", f"显著但与预注册方向 {hyp} 相反")
    if hyp == "0":
        return done("reversed", "占位题却显著 —— 反证失败 (见 placebo_alarm)")
    return done("validated", "四条全过" + ("; 新发现, 方向未预设, owner 看过再下发" if hyp == "?" else ""))


def _summary(row: dict, why: str) -> str:
    bits = [f"{row['status']}: {why}"]
    if row["mh_odds_ratio"] is not None:
        bits.append(f"OR {row['mh_odds_ratio']:.2f} [{row['ci_low']:.2f}, {row['ci_high']:.2f}]")
    if row["q_value"] is not None:
        bits.append(f"q={row['q_value']:.3f}")
    bits.append(f"大项目 {row['big_projects_same_dir']}/{row['big_projects_n']} 同向, 支持 {row['support']} 篇")
    if row.get("hyp_note"):
        bits.append(row["hyp_note"])
    return " · ".join(bits)[:400]


# ── 输出 ───────────────────────────────────────────────────────────────────────

VALIDATION_COLUMNS = ("question_id", "question_version", "answer", "bank_version", "gate2_run", "status", "hypothesis",
                      "mh_odds_ratio", "ci_low", "ci_high", "q_value", "big_projects_same_dir", "big_projects_n", "summary")


def validation_rows(result: dict) -> list[dict]:
    """feature_validation 的行 (只留表里有的列; 占位题也写, hypothesis '0')。"""
    out = []
    for r in result["rows"]:
        row = {k: r.get(k) for k in VALIDATION_COLUMNS}
        for k in ("mh_odds_ratio", "ci_low", "ci_high", "q_value"):
            if row[k] is not None:
                row[k] = float(f"{row[k]:.6g}")
        out.append(row)
    return out


def render_report(result: dict) -> str:
    p = result["params"]
    lines = [f"# 闸二 · 单个特征值 · {result['run_tag']}", "",
             f"> 快照 `bank_sha256` 前缀 `{result['sha']}` · 抽取器 {result['extractors']} · 账本行 {result['n_answers']:,}",
             f"> 分析集 {result['n_notes']:,} 篇 (正例 {result['n_pos']:,}; 有 essence、正文 ≥ 50 字) · 大项目 (正例 ≥ {p['big_pos']}): "
             + (", ".join(f"{k} {v}" for k, v in result["big_projects"].items()) or "无"),
             f"> 判据: q ≤ {p['q_max']} · 支持 ≥ {p['min_support']} 篇 · 有支持的大项目 ≥ {p['min_big']} · 最多 1 个大项目反向 · "
             f"账号先验分层后 OR 变化 ≤ {int(p['confound_delta'] * 100)}% · 闸一不过: {p['unreliable'] or '（没传）'}",
             f"> 账号先验档: 无记录 {result['prior_strata'][PRIOR_NONE]} · 低于基线 {result['prior_strata'][PRIOR_BELOW]} · "
             f"不低于 {result['prior_strata'][PRIOR_AT_OR_ABOVE]}", ""]
    counts = defaultdict(int)
    for r in result["rows"]:
        counts[r["status"]] += 1
    lines.append("| 状态 | 个 |\n|---|---|")
    lines += [f"| {s} | {counts.get(s, 0)} |" for s in STATUSES]
    lines += ["", "| 题 | 取值 | 预注册 | 状态 | OR | 95% CI | q | 大项目同向/有支持 | 支持 | 先验分层 OR | 说明 |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    order = {s: i for i, s in enumerate(("validated", "reversed", "confounded", "no_signal", "insufficient", "unreliable"))}
    for r in sorted(result["rows"], key=lambda r: (order[r["status"]], r["q_value"] if r["q_value"] is not None else 9, r["question_id"])):
        f = lambda v, d=2: "—" if v is None else f"{v:.{d}f}"
        lines.append(f"| `{r['question_id']}` | {r['answer']} | {r['hypothesis']} | **{r['status']}** | {f(r['mh_odds_ratio'])} | "
                     f"{f(r['ci_low'])}–{f(r['ci_high'])} | {f(r['q_value'], 3)} | {r['big_projects_same_dir']}/{r['big_projects_n']} | "
                     f"{r['support']} | {f(r['mh_prior'])} | {r['summary'].split(': ', 1)[-1]} |")
    lines += ["", "## 反证 (占位题)", ""]
    if result["placebo_alarm"]:
        lines += ["**没过** —— " + "; ".join(result["placebo_alarm"])]
    else:
        plc = [r for r in result["rows"] if r["kind"] == "placebo"]
        lines += ["过: " + ("; ".join(f"`{r['question_id']}` {r['status']} (q={r['q_value']:.2f})" if r["q_value"] is not None
                                       else f"`{r['question_id']}` {r['status']}" for r in plc) or "快照里没有占位题")]
    lines += ["", "## 没做", "", "- B.3 组合对比 (留一项目 AUC + 配对自助) 与 B.4 置换反证不在本脚本里: 那是「组合进不进 L2」的决定。",
              "- `unreliable` 只按 `--unreliable` 传入的题号打 (闸一结论还没有机器可读形式, 审计 B-17)。"]
    return "\n".join(lines) + "\n"


# ── 取数 (生产) ───────────────────────────────────────────────────────────────

def fetch_dataset(sb, *, sha: str, extractors: list[str], projects: Optional[set[str]] = None) -> dict:
    from _common import fetch_all_pages
    labels = fetch_all_pages(sb.schema("truth_vault").table("v_l2_labels")
                             .select("note_id, project_id, account_id, publish_time, y"), order_by="note_id")
    ess = {r["note_id"]: r.get("emotional_lever") is not None
           for r in fetch_all_pages(sb.schema("truth_vault").table("notes").select("note_id, emotional_lever"), order_by="note_id")}
    blen = {r["note_id"]: r.get("body_len")
            for r in fetch_all_pages(sb.schema("truth_vault").table("note_features").select("note_id, body_len"), order_by="note_id")}
    notes = [{"note_id": r["note_id"], "project_id": r["project_id"], "account_id": r.get("account_id"),
              "publish_time": r.get("publish_time"), "y": int(r["y"]), "has_essence": ess.get(r["note_id"], False),
              "body_len": blen.get(r["note_id"])}
             for r in labels if (projects is None or r["project_id"] in projects)]
    # ⚠️ fetch_all_pages 按 order_by 那一列去重 (它要求唯一列)。账本一篇 31 行, 整表按 subject_id 翻页会把同一篇
    #    合并成一行、重复也看不见。所以按 (题, 抽取器) 一条一条查: 这个切片里 subject_id 唯一 (sha 钉住了版本),
    #    跨抽取器的重复在 run_gate2 里按 (笔记, 题) 数出来。
    answers: list[dict] = []
    qids = sorted({t["question_id"] for t in bank_targets(fb.load_bank())})
    for qid in qids:
        for ext in extractors:
            q = (sb.schema("truth_vault").table("note_feature_answers")
                 .select("subject_id, question_id, question_version, bank_sha256, extractor, answer")
                 .eq("subject_type", "note").eq("run_tag", "primary").like("bank_sha256", f"{sha}%")
                 .eq("question_id", qid).eq("extractor", ext))
            answers.extend(fetch_all_pages(q, order_by="subject_id"))
    return {"notes": notes, "answers": answers}


def write_validation(sb, rows: list[dict]) -> int:
    for i in range(0, len(rows), 200):
        sb.schema("truth_vault").table("feature_validation").upsert(rows[i:i + 200]).execute()
    return len(rows)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sha", required=True, help="bank_sha256 前缀 (≥ 8 位), 快照的一半")
    ap.add_argument("--extractors", required=True, help="逗号分隔, 快照的另一半, 如 code:v1,llm:claude-opus-4-6")
    ap.add_argument("--run-tag", default="gate2-" + datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    ap.add_argument("--bank", default=str(fb.BANK_PATH))
    ap.add_argument("--projects", default="", help="逗号分隔只看这些项目; 空 = 全部")
    ap.add_argument("--unreliable", default="", help="逗号分隔, 闸一没过的题号 → unreliable")
    ap.add_argument("--q-max", type=float, default=0.10)
    ap.add_argument("--min-support", type=int, default=30)
    ap.add_argument("--min-big", type=int, default=3)
    ap.add_argument("--big-pos", type=int, default=20)
    ap.add_argument("--confound-delta", type=float, default=0.30)
    ap.add_argument("--allow-draft", action="store_true", help="题库没冻结也跑 (试算 / CI 夹具); 正式跑不许")
    ap.add_argument("--ignore-placebo-alarm", action="store_true", help="反证没过也出报告 (只为排查, 不写库)")
    ap.add_argument("--fixture", default="", help="离线: 从 json 读 {notes, answers}, 不连库")
    ap.add_argument("--out", default="", help="报告 markdown 路径")
    ap.add_argument("--rows-out", default="", help="feature_validation 行 json 路径")
    ap.add_argument("--write", action="store_true", help="写 feature_validation (upsert, 主键含 gate2_run)")
    args = ap.parse_args(argv)
    extractors = [e.strip() for e in args.extractors.split(",") if e.strip()]
    unreliable = [u.strip() for u in args.unreliable.split(",") if u.strip()]
    projects = {p.strip() for p in args.projects.split(",") if p.strip()} or None
    bank = fb.load_bank(args.bank)
    sb = None
    try:
        if args.fixture:
            dataset = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        else:
            from _common import get_supabase_client
            sb = get_supabase_client()
            dataset = fetch_dataset(sb, sha=args.sha, extractors=extractors, projects=projects)
        result = run_gate2(dataset, bank, sha=args.sha, extractors=extractors, run_tag=args.run_tag, q_max=args.q_max,
                           min_support=args.min_support, min_big=args.min_big, big_pos=args.big_pos,
                           confound_delta=args.confound_delta, unreliable=unreliable, allow_draft=args.allow_draft,
                           ignore_placebo_alarm=args.ignore_placebo_alarm)
    except Gate2Refused as exc:
        print(f"闸二没跑: {exc}", file=sys.stderr)
        return 2
    report = render_report(result)
    rows = validation_rows(result)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
    else:
        print(report)
    if args.rows_out:
        Path(args.rows_out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.write:
        if args.ignore_placebo_alarm and result["placebo_alarm"]:
            print("反证没过, 不写库", file=sys.stderr)
            return 2
        if sb is None:
            print("--fixture 模式不写库", file=sys.stderr)
            return 2
        n = write_validation(sb, rows)
        print(f"feature_validation 写入 {n} 行 (gate2_run={args.run_tag})")
    counts = defaultdict(int)
    for r in result["rows"]:
        counts[r["status"]] += 1
    print("闸二: " + ", ".join(f"{s} {counts.get(s, 0)}" for s in STATUSES), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
