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
副题库 (D-128, docs/28 §6.2b; 题库 role: secondary 自动走 run_gate2_secondary 那条路, 永远不写 feature_validation):
    python gate2_run.py --bank reader --sha 9f2cf1c9e7de --manifest ../data-analysis/gate2-reader-holdout-2026-10-27.csv \
        --counts-only                                                                           # 读之前: 只数行数和覆盖
    … --run-tag gate2-reader-2026-11-03 --out ../data-analysis/feature-gate2-gate2-reader-2026-11-03.md   # 只读一次
B.3 组合对比 (留一项目 AUC + 配对自助) 与 B.4 置换反证在 gate2_combo.py (D-106) —— 那是「组合进不进 L2」的决定, 不是单个特征值的闸。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
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


def gate1_unreliable(bank: dict) -> set[str]:
    """题库里闸一裁成 fail 的题 (gate1_status, 审计 B-17 / D-103) → 闸二一律 unreliable。
    pending (还没裁) 和 kappa_undefined (κ 算不出) 不在内: 前者冻结时 validate_bank 会拦, 后者闸二按 support 自己判。"""
    return {q["id"] for q in fb.llm_questions(bank) if q.get("gate1_status") == "fail"}


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

def preregistration_check(bank: dict, sha: str, *, allow_draft: bool = False) -> str:
    """预注册三道 (闸二单特征与组合对比共用): --sha 是题库文件 digest 的前缀; 题库 frozen; validate_bank 为空。回规范化的 sha。"""
    sha = sha.lower()
    if len(sha) < 8:
        raise Gate2Refused("--sha 至少 8 位十六进制前缀")
    if not bank["_sha256"].startswith(sha):
        raise Gate2Refused(f"问题库文件 digest {bank['_sha256'][:12]} 与 --sha {sha} 对不上: 预注册的方向来自题库文件, "
                           "文件和快照必须是同一份")
    if bank.get("status") != "frozen" and not allow_draft:
        raise Gate2Refused("问题库 status 不是 frozen —— 闸二跑之前先冻结 (status: frozen + frozen_sha256), 判据数字记进 "
                           "DECISIONS (docs/28 §6.2 预注册)。试算用 --allow-draft。")
    # 冻结后改过题的题库 (codex review on #169, P1): status 还是 frozen、frozen_sha256 记的是改之前的快照, 操作者拿改后文件
    # 的新 digest 当 --sha 传进来, 上面两条都过 —— 预注册就被绕开了。validate_bank 本来就查"frozen_sha256 == 规范化 digest",
    # 这里把它整个调一遍: 结构不合法或 digest 不符都拒跑。
    errs = fb.validate_bank(bank)
    if errs:
        raise Gate2Refused("问题库没过 validate_bank: " + "; ".join(errs) +
                           " —— 冻结后改题要升 version、重新冻结并记 DECISIONS, 不能拿改后的 digest 当预注册快照。")
    return sha


def snapshot_answers(dataset: dict, sha: str, extractors: Iterable[str]) -> list[dict]:
    """快照内的答案 (run_tag=primary, bank_sha256 前缀, 抽取器集合) + (笔记, 题) 唯一性 (docs/28 B.3)。"""
    ext = set(extractors)
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
    return answers


def run_gate2(dataset: dict, bank: dict, *, sha: str, extractors: list[str], run_tag: str,
              q_max: float = 0.10, min_support: int = 30, min_big: int = 3, big_pos: int = 20,
              confound_delta: float = 0.30, unreliable: Iterable[str] = (), allow_draft: bool = False,
              ignore_placebo_alarm: bool = False) -> dict:
    sha = preregistration_check(bank, sha, allow_draft=allow_draft)
    # 闸一裁决两处来源取并集: 题库里的 gate1_status: fail (机器可读, D-103) ∪ --unreliable 手传的题号 (试算 / 追加)
    unreliable = set(unreliable) | gate1_unreliable(bank)
    ext = set(extractors)

    answers = snapshot_answers(dataset, sha, ext)

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


def rows_digest(rows: list[dict]) -> str:
    """feature_validation 行的规范化摘要 (codex review on #173, P1): 只出报告那次和 --write 那次是两个进程, 中间夜跑 /
    回填可能改了账本或 v_l2_labels, 写进库的必须是看过的那一份。行按 (题, 版本, 取值) 排序、键排序、JSON 紧凑序列化
    再 sha256; 列就是 VALIDATION_COLUMNS (含 gate2_run —— 换 run_tag 也算另一份)。"""
    canon = sorted(({k: r.get(k) for k in VALIDATION_COLUMNS} for r in rows),
                   key=lambda r: (str(r["question_id"]), int(r["question_version"] or 0), str(r["answer"])))
    blob = json.dumps(canon, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def assert_projects_present(dataset: dict, projects: Optional[set[str]]) -> None:
    """--projects 里每个项目在取数里都得有篇 (codex review on #173, P2): 拼错 / 该项目没有 v_l2_labels 时, 以前是
    0 篇分析集照跑、全部 insufficient, 带 --write 还会顶掉同 tag 的正经结果。取数 0 篇同理。"""
    seen = {n.get("project_id") for n in dataset.get("notes", [])}
    if projects:
        missing = sorted(p for p in projects if p not in seen)
        if missing:
            raise Gate2Refused(f"--projects 里 {missing} 在 v_l2_labels 里一篇都没有 (拼错了? 没有标签?); "
                               f"取到的项目: {sorted(x for x in seen if x)}")
    if not dataset.get("notes"):
        raise Gate2Refused("取数 0 篇: 没有分析集就没有闸二")


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
    lines += ["", "## 没做", "", "- B.3 组合对比 (留一项目 AUC + 配对自助) 与 B.4 置换反证在 `gate2_combo.py` (同一个 workflow 的下一步): 那是「组合进不进 L2」的决定。",
              "- `unreliable` = 题库里 `gate1_status: fail` 的题 ∪ `--unreliable` 传入的题号 (D-103); `kappa_undefined` 的题照常进统计, 按 support 判。"]
    return "\n".join(lines) + "\n"


# ── 取数 (生产) ───────────────────────────────────────────────────────────────

def fetch_dataset(sb, *, bank: dict, sha: str, extractors: list[str], projects: Optional[set[str]] = None) -> dict:
    """``bank`` 必须是 main() 里 --bank 读进来的那一份: 取哪些题按它算 (codex review on #169, P1 —— 以前这里重新
    load 默认题库, --bank 指向别的冻结题库时, 只在那份里的题永远取不到答案、报告里静默少题)。"""
    from _common import fetch_all_pages, fetch_vanished_note_ids
    labels = fetch_all_pages(sb.schema("truth_vault").table("v_l2_labels")
                             .select("note_id, project_id, account_id, publish_time, y"), order_by="note_id")
    ess = {r["note_id"]: r.get("emotional_lever") is not None
           for r in fetch_all_pages(sb.schema("truth_vault").table("notes").select("note_id, emotional_lever"), order_by="note_id")}
    blen = {r["note_id"]: r.get("body_len")
            for r in fetch_all_pages(sb.schema("truth_vault").table("note_features").select("note_id, body_len"), order_by="note_id")}
    # 飞书里已删 (本项目最近一次完整同步没见到) 的篇不进闸二 (审计 B-21, D-103): 它们的标签是删前的快照, 之后没人维护。
    vanished = fetch_vanished_note_ids(sb)
    notes = [{"note_id": r["note_id"], "project_id": r["project_id"], "account_id": r.get("account_id"),
              "publish_time": r.get("publish_time"), "y": int(r["y"]), "has_essence": ess.get(r["note_id"], False),
              "body_len": blen.get(r["note_id"])}
             for r in labels if (projects is None or r["project_id"] in projects) and r["note_id"] not in vanished]
    n_vanished = sum(1 for r in labels if r["note_id"] in vanished and (projects is None or r["project_id"] in projects))
    # ⚠️ fetch_all_pages 按 order_by 那一列去重 (它要求唯一列)。账本一篇 31 行, 整表按 subject_id 翻页会把同一篇
    #    合并成一行、重复也看不见。所以按 (题, 抽取器) 一条一条查: 这个切片里 subject_id 唯一 (sha 钉住了版本),
    #    跨抽取器的重复在 run_gate2 里按 (笔记, 题) 数出来。
    answers: list[dict] = []
    qids = sorted({t["question_id"] for t in bank_targets(bank)})
    for qid in qids:
        for ext in extractors:
            q = (sb.schema("truth_vault").table("note_feature_answers")
                 .select("subject_id, question_id, question_version, bank_sha256, extractor, answer")
                 .eq("subject_type", "note").eq("run_tag", "primary").like("bank_sha256", f"{sha}%")
                 .eq("question_id", qid).eq("extractor", ext))
            answers.extend(fetch_all_pages(q, order_by="subject_id"))
    return {"notes": notes, "answers": answers, "vanished_dropped": n_vanished}


def write_validation(sb, rows: list[dict]) -> int:
    for i in range(0, len(rows), 200):
        sb.schema("truth_vault").table("feature_validation").upsert(rows[i:i + 200]).execute()
    return len(rows)


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# 副题库的闸二 (D-128 + 三条补记, docs/28 §6.2b): fq-v0.2-cand-reader 读者提问方式两道题。
# 独立一条路: 上面主题库的函数 (run_gate2 / render_report / validation_rows / bank_targets / contrast_tables /
# fetch_dataset / _assign_status) 一个字节不动 (check_gate2_run §0 金样), 这里只【调用】其中几个纯函数。和主题库不同的地方:
#   · 只读 --manifest (进了仓库的名单 CSV, 可给多份) 里的篇; 每份名单的 sha256 和合并名单 sha 进报告; 同一份名单只读一次 (补记 7)
#   · 留出半, D-129 换了 id 的按 old_id 定 (映射表读不到就不跑); 名单里有一篇不在留出半就拒
#   · 两份快照分开取: 副题库答案 (fqr-g2-sonnet55 + 副题库全 64 位 sha + Sonnet 5.5 / code:v1) 与分层答案
#     (gate2.condition_snapshot: 主题库 ba0f570c、run_tag primary、只认 Sonnet —— Opus 的行不算); (笔记, 题) 唯一, 版本钉死
#   · 名单里掉出去的分三种数, 加起来 > 名单 3% 拒读; 正文截断记 NULL 的单独计数、不算缺, 也不进分子分母 (补记 5)
#   · MH 的层 = 项目 × ending_asks_reader × asks_for_help (题上的 conditional_on); 账号先验在这上面再加一层
#   · contrast_base_excludes (没问读者) 不进取值行和合并行的比较基数; 阳性对照 (没问读者 对其余) 用全部
#   · 确认族两行 (C1 合并行、C2 invites_sharing 是), BH 只在这两行里做 (q ≤ 0.10); 其余只报告、不判状态
#   · 占位题从主题库定义按 note_id 现算, 同样分层, 不进家族; 报警 = 这次读作废: 两行连算都不算, 报告带 -void (补记 2)
#   · 结果永远不写 feature_validation —— 这条路里没有 write_validation 的调用, CLI 也不收 --write
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════

SEC_ANSWERS_RUN_TAG = "fqr-g2-sonnet55"          # D-128 补记: 第一波 / 第二波都抽在这个 run_tag 下
SEC_LLM_EXTRACTOR = "llm:claude-sonnet-5-5"     # 副题库的模型题只认这一个抽取器; 代码特征是 fb.CODE_EXTRACTOR
SEC_MISSING_MAX_FRAC = 0.03                     # 补记 5: 三种掉出去的加起来超过名单篇数的 3% 就拒读
SEC_PLACEBO_P_MAX = 0.10                        # 补记 2: 占位题判「显著」用原始 p ≤ 0.10 (偏严)
SEC_DROP_KINDS = ("out_of_scope", "no_answer", "no_condition")
SEC_DROP_LABELS = {"out_of_scope": "不在闸二口径里了 (删了 / 标签变了 / 没 essence / 正文 < 50 字)",
                   "no_answer": "两道题有一道没有可用答案 (没行, 或 answer 为空但不是正文截断)",
                   "no_condition": "两道分层题有一道没有答案"}
# body_len_bucket 的切点 = feature_bank 主题库代码特征的同名特征 (按 note_features.body_len 现算, check_gate2_run §8 对过)
BODY_LEN_EDGES = ((99, "<100"), (199, "100-199"), (399, "200-399"))
BODY_LEN_TOP = ">=400"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "data-analysis"
# 读过的报告第一行之后带这一行 (HTML 注释, markdown 里看不见); 「只读一次」靠它找 (补记 7)
SEC_MARK = "<!-- gate2-secondary bank_sha256={sha} combined_manifest_sha256={man} void={void} -->"
SEC_MARK_RE = re.compile(r"<!-- gate2-secondary bank_sha256=([0-9a-f]{64}) combined_manifest_sha256=([0-9a-f]{64}) "
                         r"void=([01]) -->")


def body_len_bucket(body_len) -> str:
    """note_features.body_len → 主题库 body_len_bucket 的档; 没有 body_len 的单独一档 (闸二口径里缺值不剔)。"""
    if body_len is None:
        return "unknown"
    for upper, label in BODY_LEN_EDGES:
        if int(body_len) <= upper:
            return label
    return BODY_LEN_TOP


def sensitivity_flags(dq: Optional[dict], has_pinned_comment: bool = False) -> list[str]:
    """敏感性重跑要剔的篇 (D-128: 记过置顶 / 控评 / 铺评 / 投流)。读的是同步引擎写好的标记, 不重判:
      · data_quality_flags.comment_maintained_routes 非空: 铺评工单 / 起量后干预 (控评、置顶、改评) / 铺评未跨线;
        只写了 comment_maintained=true 没写 routes 的老行也算;
      · data_quality_flags.paid_promoted = true (投流三态里只认 true; 缺键 = 不知道, 不剔);
      · notes.pinned_comment 非空 (同步时已并进「起量后干预」, 这里再直接看一遍列)。"""
    dq = dq if isinstance(dq, dict) else {}
    out = set()
    routes = dq.get("comment_maintained_routes") or []
    for r in (routes if isinstance(routes, list) else [routes]):
        out.add(f"维护:{r}")
    if dq.get("comment_maintained") is True and not routes:
        out.add("维护")
    if dq.get("paid_promoted") is True:
        out.add("投流")
    if has_pinned_comment:
        out.add("置顶")
    return sorted(out)


def contrast_tables_by(notes: list[dict], side, stratum_of) -> dict[Any, list[float]]:
    """集合版的 contrast_tables (副题库): side(note) → True (有) / False (没有) / None (不进比较基数: 没答、正文截断
    记 NULL、contrast_base_excludes 的取值)。每层一张 2×2, 下标同 contrast_tables: a 有且爆 / b 有且趴 / c 没有且爆 / d 没有且趴。"""
    tabs: dict[Any, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    for n in notes:
        s = side(n)
        if s is None:
            continue
        y = int(n["y"])
        idx = (0 if y else 1) if s else (2 if y else 3)
        tabs[stratum_of(n)][idx] += 1
    return tabs


def _options(q: dict) -> list[str]:
    return [str(o.get("value")) if isinstance(o, dict) else str(o) for o in q.get("options") or []]


def secondary_targets(bank: dict) -> list[dict]:
    """副题库要算的行。has = 算「有」的取值; base = 进比较基数的取值 (None = 所有有答案的)。
      · merged (合并行, gate2.merged_contrasts): 集合对集合, 基数剔掉 contrast_base_excludes;
      · value (choice 题每个不在 excludes 里的取值): 对其余提问类型, 基数同上 —— 只报告;
      · control (excludes 的取值, 阳性对照): 对其余全部 —— 只报告;
      · bool 模型题的「是」; 代码特征 —— 只报告。
    family = 在 gate2.confirmation_family 里 (只有这两行判状态、做 BH)。占位题从主题库现算, 不在这里。"""
    g2 = bank["gate2"]
    family = {(str(q), str(v)) for q, v in g2["confirmation_family"]}
    out: list[dict] = []

    def add(qid, label, has, base, hyp, kind):
        out.append({"question_id": qid, "answer": str(label), "has": frozenset(has),
                    "base": None if base is None else frozenset(base), "hypothesis": str(hyp), "kind": kind,
                    "family": (qid, str(label)) in family})

    for q in fb.llm_questions(bank):
        hyp = q.get("hypothesis")
        if q.get("type") == "bool":
            add(q["id"], "是", {"是"}, None, hyp if isinstance(hyp, str) else "?", "bool")
            continue
        opts = _options(q)
        exc = [v for v in opts if v in (q.get("contrast_base_excludes") or [])]
        asked = [v for v in opts if v not in exc]
        hyp = hyp if isinstance(hyp, dict) else {}
        for m in g2.get("merged_contrasts") or []:
            if m["question_id"] == q["id"]:
                add(q["id"], m["label"], m["values"], asked, m["hypothesis"], "merged")
        for v in asked:
            add(q["id"], v, {v}, asked, hyp.get(v, "?"), "value")
        for v in exc:
            add(q["id"], v, {v}, None, hyp.get(v, "?"), "control")
    for c in bank.get("code_features") or []:
        if c.get("type", "bool") == "bool":
            add(c["id"], "是", {"是"}, None, c.get("hypothesis", "?"), "code")
        else:
            for v in _options(c):
                add(c["id"], v, {v}, None, "?", "code")
    missing = family - {(t["question_id"], t["answer"]) for t in out}
    if missing:
        raise Gate2Refused(f"gate2.confirmation_family 里的 {sorted(missing)} 算不出行 —— 题库和比法对不上")
    return out


def load_manifests(paths: Iterable[str]) -> list[dict]:
    """--manifest 的每份 CSV → {path, sha256 (文件字节), rows}。列 / 重复 / 层的检查用 gate1_sample.read_manifest (同一个读法)。"""
    from gate1_sample import SampleRefused, read_manifest
    out = []
    for p in paths:
        path = Path(p)
        try:
            raw = path.read_bytes()
            rows = read_manifest(path)
        except (OSError, SampleRefused) as exc:
            raise Gate2Refused(f"名单 {p} 读不了: {exc}") from exc
        out.append({"path": str(p), "sha256": hashlib.sha256(raw).hexdigest(), "rows": rows})
    return out


def combined_manifest_sha(note_ids: Iterable[str]) -> str:
    """合并名单 sha (补记 7 的「名单 sha」): 几份名单的 note_id 按码点排序、每个一行再 sha256 —— 同一批篇换个拆法 sha 不变,
    多一篇少一篇就变。"""
    return hashlib.sha256("".join(f"{n}\n" for n in sorted(set(note_ids))).encode("utf-8")).hexdigest()


def untracked_manifests(paths: Iterable[str]) -> list[str]:
    """没进 git 的名单 (git ls-files --error-unmatch 不认的; 没装 git / 不在仓库里也算没进)。正式读只读进了仓库的名单 ——
    临时拼一份没提交的名单读, 名单 sha 就不在仓库的记录里 (D-128 补记)。"""
    import subprocess
    bad = []
    for p in paths:
        p = Path(p).resolve()
        try:
            ok = subprocess.run(["git", "-C", str(p.parent), "ls-files", "--error-unmatch", "--", p.name],
                                capture_output=True, text=True).returncode == 0
        except OSError:
            ok = False
        if not ok:
            bad.append(str(p))
    return bad


def void_path(out: Path) -> Path:
    """作废那次的报告名带 -void (补记 2 / 7): 不算读过。"""
    return out if out.stem.endswith("-void") else out.with_name(f"{out.stem}-void{out.suffix}")


def prior_secondary_reads(dirs: Iterable[Path], combined_sha: str) -> list[str]:
    """dirs 下已有的、同一份合并名单的副题库闸二报告 (补记 7)。作废的那次 (标记 void=1 且文件名带 -void) 不算读过;
    只改文件名、标记还是 void=0 的照算 —— 不能靠改名把读过的那次变成作废。"""
    hits: list[str] = []
    seen: set[Path] = set()
    for d in dirs:
        d = Path(d)
        if not d.is_dir() or d.resolve() in seen:
            continue
        seen.add(d.resolve())
        for f in sorted(d.glob("*.md")):
            try:
                text = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for m in SEC_MARK_RE.finditer(text):
                if m.group(2) == combined_sha and not (m.group(3) == "1" and "-void" in f.name):
                    hits.append(str(f))
                    break
    return hits


def _secondary_prereg(bank: dict, primary: dict, sha: str) -> str:
    """副题库的预注册: 冻结 + digest (preregistration_check, 不许 allow_draft) + 主题库自己合法 + 跨库校验 (load_bank_pair 那两道)。"""
    if bank.get("role") != fb.ROLE_SECONDARY:
        raise Gate2Refused("run_gate2_secondary 只收副题库 (role: secondary); 主题库走 run_gate2")
    sha = preregistration_check(bank, sha, allow_draft=False)
    errs = [f"主题库: {e}" for e in fb.validate_bank(primary)] + fb.validate_secondary(bank, primary)
    if errs:
        raise Gate2Refused("副题库跨库校验没过: " + "; ".join(errs))
    g2 = bank.get("gate2") or {}
    if g2.get("placebo") != "from_primary":
        raise Gate2Refused(f"gate2.placebo={g2.get('placebo')!r}: 这条路只实现了 from_primary (D-128)")
    snap = g2.get("condition_snapshot") or {}
    if snap.get("extractors") != [SEC_LLM_EXTRACTOR] or snap.get("run_tag") != "primary":
        raise Gate2Refused(f"D-128 的分层答案只取主题库 primary 快照里的 Sonnet 5.5, yaml 写的是 {snap}")
    return sha


def _snapshot(rows: list[dict], *, expect: dict[str, tuple[int, set]], vocab: dict[str, tuple], what: str
              ) -> dict[str, dict[str, dict]]:
    """一份快照的行 (调用方已按 run_tag / sha / 抽取器筛过) → {题: {笔记: 行}}。版本必须是 expect 里钉的那个、(笔记, 题)
    唯一、答案在闭集 —— 有一条不满足整跑拒 (同 snapshot_answers 的纪律)。"""
    bad_ver = sorted({(a["question_id"], int(a["question_version"])) for a in rows
                      if int(a["question_version"]) != expect[a["question_id"]][0]})
    if bad_ver:
        raise Gate2Refused(f"{what}里有不是题库版本的行: {bad_ver} (应是 "
                           f"{ {q: v for q, (v, _) in expect.items()} }) —— 比如主题库的 invites_sharing v1 混进来了")
    seen: dict[tuple[str, str], int] = defaultdict(int)
    for a in rows:
        seen[(a["subject_id"], a["question_id"])] += 1
    dups = sorted(k for k, v in seen.items() if v > 1)
    if dups:
        raise Gate2Refused(f"{what}内 (笔记, 题) 不唯一: {len(dups)} 对, 如 {dups[:3]} —— 先清快照再跑")
    oov = sorted({(a["question_id"], a["answer"]) for a in rows
                  if a.get("answer") is not None and str(a["answer"]) not in vocab[a["question_id"]]})
    if oov:
        raise Gate2Refused(f"{what}里有闭集外的答案: {oov[:5]}")
    out: dict[str, dict[str, dict]] = {q: {} for q in expect}
    for a in rows:
        out[a["question_id"]][a["subject_id"]] = a
    return out


def _sec_stats(notes: list[dict], side, *, strata_of, big: set, prior: Optional[dict] = None) -> dict:
    """一行的数: 分层 MH (+ RGB 区间 + Wald p)、支持、比较基数、大项目方向 (合并 2×2 +0.5, 照主题库) 与每个大项目分层内
    的 MH 方向 (只报告)、账号先验再分层的 OR、只按项目分层的 OR、完全不分层的 OR。"""
    by_stratum = contrast_tables_by(notes, side, strata_of)
    by_proj = contrast_tables_by(notes, side, lambda n: n["project_id"])
    support = int(sum(t[0] + t[1] for t in by_stratum.values()))
    base_n = int(sum(sum(t) for t in by_stratum.values()))
    big_tabs = {p: t for p, t in by_proj.items() if p in big and (t[0] + t[1]) > 0}
    above = sum(1 for t in big_tabs.values() if (t[0] + .5) * (t[3] + .5) > (t[1] + .5) * (t[2] + .5))
    below = sum(1 for t in big_tabs.values() if (t[0] + .5) * (t[3] + .5) < (t[1] + .5) * (t[2] + .5))
    within = {}
    for p in sorted(big_tabs):
        m = mh_odds_ratio([t for k, t in by_stratum.items() if k[0] == p])
        within[p] = "?" if m is None else ("+" if m["or"] > 1 else "-" if m["or"] < 1 else "=")
    row = {"support": support, "base_n": base_n, "big_projects_n": len(big_tabs), "n_or_above_1": above,
           "n_or_below_1": below, "big_within": within, "mh_odds_ratio": None, "ci_low": None, "ci_high": None,
           "p_value": None, "mh_prior": None, "or_project_only": None, "or_crude": None, "strata": 0}
    mh = mh_odds_ratio(by_stratum.values())
    if mh is not None:
        row.update({"mh_odds_ratio": mh["or"], "ci_low": mh["ci_low"], "ci_high": mh["ci_high"],
                    "p_value": wald_p(mh["or"], mh["se_log"]), "strata": mh["strata"]})
        if prior is not None:
            m2 = mh_odds_ratio(contrast_tables_by(notes, side, lambda n: strata_of(n) + (prior[n["note_id"]],)).values())
            row["mh_prior"] = m2["or"] if m2 else None
    mp = mh_odds_ratio(by_proj.values())
    row["or_project_only"] = mp["or"] if mp else None
    tot = [sum(t[i] for t in by_stratum.values()) for i in range(4)]
    mc = mh_odds_ratio([tuple(tot)])
    row["or_crude"] = mc["or"] if mc else None
    return row


def _side(answers: dict[str, str], has: frozenset, base: Optional[frozenset]):
    def side(n):
        a = answers.get(n["note_id"])
        if a is None or (base is not None and a not in base):
            return None
        return a in has
    return side


def run_gate2_secondary(dataset: dict, bank: dict, primary: dict, *, sha: str, manifests: list[dict], run_tag: str,
                        answers_run_tag: str = SEC_ANSWERS_RUN_TAG, counts_only: bool = False,
                        reports_dirs: Iterable[Path] = (), q_max: float = 0.10, min_support: int = 30,
                        min_big: int = 3, big_pos: int = 20, confound_delta: float = 0.30) -> dict:
    """副题库闸二 (纯函数: dataset + 两份题库 + 名单 → 结果)。dataset = {notes (v_l2_labels 去掉飞书已删的, 带 has_essence /
    body_len / data_quality_flags / has_pinned_comment), vanished, answers (两份快照的行混在一起, 这里按 run_tag / sha /
    抽取器分开), half_alias ({new_id: old_id}, D-129 映射表), ignored_rows (可无: 生产取数只取快照那一片, 快照外的行数在
    库里数好带过来)}。counts_only = 只数行数和覆盖, 一个 y 都不碰。"""
    from discover_feature_candidates import half_id, in_discovery_half
    from gate1_sample import EXCLUDE

    sha = _secondary_prereg(bank, primary, sha)
    full_sha = bank["_sha256"]
    err = fb.check_run_tag(bank, answers_run_tag)
    if err:
        raise Gate2Refused(err)
    g2 = bank["gate2"]
    alias = dataset.get("half_alias")
    if not isinstance(alias, dict) or not alias:
        raise Gate2Refused("D-129 的 id 映射 (half_alias) 没读到 —— 换了 id 的行半区定不了, 不跑 (fail closed, D-128 补记)")

    # ── 名单 ──
    if not manifests:
        raise Gate2Refused("没给名单 (--manifest): 副题库闸二只读进了仓库的名单 (D-128 补记)")
    man: dict[str, dict] = {}
    for m in manifests:
        for r in m["rows"]:
            if r["note_id"] in man:
                raise Gate2Refused(f"{r['note_id']} 在两份名单里都有 (第二份 {m['path']}) —— 名单之间不许重叠")
            man[r["note_id"]] = r
    excl = sorted(set(man) & set(EXCLUDE))
    if excl:
        raise Gate2Refused(f"名单里有 D-128 点名剔掉的篇: {excl}")
    twins = sorted(n for n in man if alias.get(n) in man)
    if twins:
        raise Gate2Refused(f"名单里同时有新行和它的旧行 (D-129): {twins[:3]} —— 同一篇算了两次")
    half = g2.get("half")
    if half in ("holdout", "discovery"):
        wrong = sorted(n for n in man if in_discovery_half(half_id(n, alias)) != (half == "discovery"))
        if wrong:
            raise Gate2Refused(f"名单里 {len(wrong)} 篇不在{'留出' if half == 'holdout' else '发现'}半 (半区按 D-129 old_id 定), "
                               f"如 {wrong[:3]} —— 发现半看过的篇不能拿来确认 (D-120 / D-128)")
    combined = combined_manifest_sha(man)
    ids_md5 = hashlib.md5(",".join(sorted(man)).encode("utf-8")).hexdigest()
    if not counts_only:
        hits = prior_secondary_reads(reports_dirs, combined)
        if hits:
            raise Gate2Refused(f"这份名单 (sha {combined[:12]}) 已经读过: {hits} —— 留出半只读一次 (D-128 补记 7); "
                               "作废那次的报告名带 -void、标记 void=1 才不算")

    # ── 两份快照 ──
    sec_expect: dict[str, tuple[int, set]] = {}
    sec_vocab: dict[str, tuple] = {}
    for q in fb.llm_questions(bank):
        sec_expect[q["id"]] = (int(q["version"]), {SEC_LLM_EXTRACTOR})
        sec_vocab[q["id"]] = fb.closed_set(q)
    for c in bank.get("code_features") or []:
        sec_expect[c["id"]] = (int(c["version"]), {fb.CODE_EXTRACTOR})
        sec_vocab[c["id"]] = fb.BOOL_VALUES if c.get("type", "bool") == "bool" else tuple(_options(c))
    snap = g2["condition_snapshot"]
    cond_qids: list[str] = []
    for q in fb.llm_questions(bank):
        for c in q.get("conditional_on") or []:
            if c not in cond_qids:
                cond_qids.append(c)
    pidx = fb.question_index(primary)
    cond_expect = {c: (int(pidx[c]["version"]), set(snap["extractors"])) for c in cond_qids}
    cond_vocab = {c: fb.closed_set(pidx[c]) for c in cond_qids}

    sec_rows, cond_rows = [], []
    ignored = {"secondary": 0, "condition": 0}
    for a in dataset["answers"]:
        if a.get("subject_type", "note") != "note":
            continue
        tag, asha, ext, qid = a.get("run_tag", "primary"), str(a.get("bank_sha256", "")).lower(), a.get("extractor"), a["question_id"]
        if tag == answers_run_tag and qid in sec_expect:
            if asha == full_sha and ext in sec_expect[qid][1]:
                sec_rows.append(a)
            else:
                ignored["secondary"] += 1                     # 同 run_tag 下别的 sha / 抽取器: 不在快照里
        elif tag == snap["run_tag"] and qid in cond_expect:
            if asha == snap["bank_sha256"] and ext in cond_expect[qid][1]:
                cond_rows.append(a)
            else:
                ignored["condition"] += 1                     # Opus 4.6 那些行、别的 sha
    for k, v in (dataset.get("ignored_rows") or {}).items():  # 生产取数只取快照那一片, 快照外的行在库里数好了带过来
        ignored[k] += int(v)
    sec = _snapshot(sec_rows, expect=sec_expect, vocab=sec_vocab, what="副题库快照")
    cond = _snapshot(cond_rows, expect=cond_expect, vocab=cond_vocab, what="分层快照")
    model_qids = [q["id"] for q in fb.llm_questions(bank)]
    code_qids = [c["id"] for c in bank.get("code_features") or []]

    # ── 掉出去的 (补记 5): 按 口径 → 两道题 → 分层题 的先后归到第一种, 三种加起来就是掉出去的篇数 ──
    labels = {n["note_id"]: n for n in dataset["notes"]}
    vanished = set(dataset.get("vanished") or [])
    drops: dict[str, dict[str, int]] = {k: defaultdict(int) for k in SEC_DROP_KINDS}
    truncated: dict[str, int] = defaultdict(int)
    in_scope: list[dict] = []
    analysis: list[dict] = []
    for nid in sorted(man):
        n = labels.get(nid)
        if n is None:
            drops["out_of_scope"]["vanished" if nid in vanished else "not_in_v_l2_labels"] += 1
            continue
        if not n.get("has_essence"):
            drops["out_of_scope"]["no_essence"] += 1
            continue
        if n.get("body_len") is not None and n["body_len"] < 50:
            drops["out_of_scope"]["body_lt_50"] += 1
            continue
        in_scope.append(n)
        why = None
        for q in model_qids:
            a = sec[q].get(nid)
            if a is None:
                why = f"{q}: 没有行"
            elif a.get("answer") is None and a.get("invalid_reason") != fb.INVALID_SPAN_TRUNCATED:
                why = f"{q}: NULL ({a.get('invalid_reason') or '没写原因'})"
            if why:
                break
        if why:
            drops["no_answer"][why] += 1
            continue
        miss = [c for c in cond_qids if cond[c].get(nid) is None or cond[c][nid].get("answer") is None]
        if miss:
            drops["no_condition"][f"{miss[0]}: 没有答案"] += 1
            continue
        for q in model_qids:
            if sec[q][nid].get("answer") is None:
                truncated[q] += 1
        analysis.append(dict(n, cond=tuple(str(cond[c][nid]["answer"]) for c in cond_qids)))
    n_man = len(man)
    n_drop = sum(sum(v.values()) for v in drops.values())
    would_refuse = n_drop > SEC_MISSING_MAX_FRAC * n_man

    # ── 覆盖 (counts-only 也出; 只数行, 不碰 y) ──
    coverage = {}
    for q in model_qids + code_qids:
        rows_q = sec[q]
        on = [rows_q[n] for n in man if n in rows_q]
        nulls: dict[str, int] = defaultdict(int)
        for a in on:
            if a.get("answer") is None:
                nulls[a.get("invalid_reason") or "没写原因"] += 1
        coverage[q] = {"version": sec_expect[q][0], "extractor": sorted(sec_expect[q][1])[0], "rows": len(rows_q),
                       "rows_in_manifest": len(on), "answered": sum(1 for a in on if a.get("answer") is not None),
                       "null_by_reason": dict(sorted(nulls.items())), "manifest_without_row": n_man - len(on),
                       "rows_outside_manifest": len(rows_q) - len(on)}
    for c in cond_qids:
        on = [cond[c][n] for n in man if n in cond[c]]
        coverage[c] = {"version": cond_expect[c][0], "extractor": ",".join(sorted(cond_expect[c][1])),
                       "rows_in_manifest": len(on), "answered": sum(1 for a in on if a.get("answer") is not None),
                       "manifest_without_row": n_man - len(on)}
    by_alias = sum(1 for n in man if n in alias)
    result = {
        "run_tag": run_tag, "answers_run_tag": answers_run_tag, "bank_version": bank["bank_version"], "sha": full_sha,
        "sha_arg": sha, "primary_version": primary["bank_version"], "primary_sha": primary["_sha256"],
        "condition_snapshot": {"run_tag": snap["run_tag"], "bank_sha256": snap["bank_sha256"],
                               "extractors": list(snap["extractors"]), "questions": {c: cond_expect[c][0] for c in cond_qids}},
        "model_questions": {q: sec_expect[q][0] for q in model_qids}, "code_features": {c: sec_expect[c][0] for c in code_qids},
        "manifests": [{"path": m["path"], "sha256": m["sha256"], "n": len(m["rows"])} for m in manifests],
        "combined_sha": combined, "ids_md5": ids_md5, "n_manifest": n_man, "half": half, "half_by_old_id": by_alias,
        "drops": {k: dict(sorted(v.items())) for k, v in drops.items()}, "n_drop": n_drop,
        "tolerance": int(math.floor(SEC_MISSING_MAX_FRAC * n_man)), "would_refuse": would_refuse,
        "truncated": dict(truncated), "n_analysis": len(analysis), "coverage": coverage, "ignored_rows": ignored,
        "counts_only": counts_only, "void": False,
        "params": {"q_max": q_max, "min_support": min_support, "min_big": min_big, "big_pos": big_pos,
                   "confound_delta": confound_delta, "missing_max_frac": SEC_MISSING_MAX_FRAC,
                   "placebo_p_max": SEC_PLACEBO_P_MAX}}
    if counts_only:
        return result
    if would_refuse:
        raise Gate2Refused(f"名单 {n_man} 篇里掉出去 {n_drop} 篇, 超过 3% (最多 {result['tolerance']} 篇) —— 先查原因再读 "
                           f"(D-128 补记 5): " + "; ".join(f"{SEC_DROP_LABELS[k]} {sum(v.values())}" for k, v in drops.items()))
    if not analysis:
        raise Gate2Refused("名单里没有一篇进得了分析集")

    # ── 从这里起才碰 y ──
    strata_of = lambda n: (n["project_id"],) + n["cond"]                        # noqa: E731  项目 × ear × afh
    pos_by_proj: dict[str, int] = defaultdict(int)
    for n in in_scope:                                                          # 补记 1: 名单里、闸二口径内的爆
        pos_by_proj[n["project_id"]] += int(n["y"])
    big = {p for p, c in pos_by_proj.items() if c >= big_pos}
    prior = account_prior_strata(analysis_notes(dataset["notes"]))              # 账号先验照主题库: 口径内全部已标签笔记
    result.update({"big_projects": {p: pos_by_proj[p] for p in sorted(big)}, "n_pos": sum(int(n["y"]) for n in analysis),
                   "y_changed": sum(1 for n in in_scope if int(n["y"]) != int(man[n["note_id"]]["y"])),
                   "project_changed": sum(1 for n in in_scope if n["project_id"] != man[n["note_id"]]["project_id"]),
                   "prior_strata": {k: sum(1 for n in analysis if prior[n["note_id"]] == k)
                                    for k in (PRIOR_NONE, PRIOR_BELOW, PRIOR_AT_OR_ABOVE)}})

    # ── 反证先跑 (补记 2): 占位题从主题库定义按 note_id 现算, 同样分层, 不进家族 ──
    plc_ans = {n["note_id"]: fb.placebo_answers(primary, n["note_id"]) for n in analysis}
    placebo_rows, alarm = [], []
    for p in primary.get("placebo") or []:
        ans = {nid: v[p["id"]] for nid, v in plc_ans.items()}
        r = {"question_id": p["id"], "answer": "是", "hypothesis": "0", "kind": "placebo",
             **_sec_stats(analysis, _side(ans, frozenset({"是"}), None), strata_of=strata_of, big=big)}
        r["alarm"] = placebo_alarm(r, min_support=min_support, min_big=min_big)
        placebo_rows.append(r)
        if r["alarm"]:
            alarm.append(p["id"])
    result.update({"placebo_rows": placebo_rows, "placebo_alarm": alarm})
    if alarm:
        result["void"] = True                         # 两行连算都不算: 作废那次没露出两行的结果, 才不算用掉「只读一次」
        return result

    # ── 两行确认族 + 只报告的行 ──
    answered = {q: {nid: str(a["answer"]) for nid, a in sec[q].items() if a.get("answer") is not None} for q in sec}
    unreliable = gate1_unreliable(bank)
    family_rows, report_rows = [], []
    targets = {(t["question_id"], t["answer"]): t for t in secondary_targets(bank)}
    for t in targets.values():
        st = _sec_stats(analysis, _side(answered[t["question_id"]], t["has"], t["base"]), strata_of=strata_of, big=big,
                        prior=prior if t["family"] else None)
        row = {"question_id": t["question_id"], "question_version": sec_expect[t["question_id"]][0], "answer": t["answer"],
               "hypothesis": t["hypothesis"], "kind": t["kind"], "family": t["family"],
               "has": sorted(t["has"]), "base": None if t["base"] is None else sorted(t["base"]),
               "q_value": None, "status": None, "hyp_note": "", **st}
        (family_rows if t["family"] else report_rows).append(row)
    # BH 只在确认族两行里做 (D-128); 算不出 p 的那行按 p = 1 留在家族里 —— 家族大小钉死是 2, 不因为一行算不出就变成 1
    qv = bh_qvalues({(r["question_id"], r["answer"]): (r["p_value"] if r["p_value"] is not None else 1.0)
                     for r in family_rows})
    for r in family_rows:
        r["q_value"] = qv[(r["question_id"], r["answer"])]
        _assign_status(r, q_max=q_max, min_support=min_support, min_big=min_big, confound_delta=confound_delta,
                       unreliable=unreliable)
    # 敏感性重跑 (只报告): 剔掉记过置顶 / 控评 / 铺评 / 投流的篇, 再加一层 body_len_bucket
    flagged = {n["note_id"]: sensitivity_flags(n.get("data_quality_flags"), bool(n.get("has_pinned_comment")))
               for n in analysis}
    kept = [n for n in analysis if not flagged[n["note_id"]]]
    flag_counts: dict[str, int] = defaultdict(int)
    for fl in flagged.values():
        for f in fl:
            flag_counts[f] += 1
    sens = []
    for r in family_rows:
        t = targets[(r["question_id"], r["answer"])]
        st = _sec_stats(kept, _side(answered[t["question_id"]], t["has"], t["base"]),
                        strata_of=lambda n: strata_of(n) + (body_len_bucket(n.get("body_len")),), big=big)
        sens.append({"question_id": r["question_id"], "answer": r["answer"], **st})
    result.update({"family_rows": family_rows, "report_rows": report_rows, "sensitivity": sens,
                   "sensitivity_dropped": sum(1 for v in flagged.values() if v),
                   "sensitivity_flags": dict(sorted(flag_counts.items())),
                   "verdict": secondary_verdict(family_rows)})
    return result


def placebo_alarm(r: dict, *, min_support: int = 30, min_big: int = 3) -> bool:
    """补记 2 的报警规则, 四条同时满足才报: 支持 ≥ 30 且有支持的大项目 ≥ 3; MH 95% 区间不跨 1; 原始 p ≤ 0.10;
    大项目最多一个反向 (反向 = 和合并 OR 的方向相反, 合并 2×2 +0.5 判)。"""
    or_ = r["mh_odds_ratio"]
    if or_ is None or r["support"] < min_support or r["big_projects_n"] < min_big:
        return False
    if r["ci_low"] <= 1.0 <= r["ci_high"] or r["p_value"] > SEC_PLACEBO_P_MAX:
        return False
    opposite = r["n_or_below_1"] if or_ > 1 else r["n_or_above_1"] if or_ < 1 else 0
    return opposite <= 1


def secondary_verdict(family_rows: list[dict]) -> str:
    """补记 3: 两行都 validated 才算一个发现; 只过一行 = 单行过, 不算发现。"""
    ok = [f"{r['question_id']}={r['answer']}" for r in family_rows if r["status"] == "validated"]
    st = ", ".join(f"{r['question_id']}={r['answer']} {r['status']}" for r in family_rows)
    if len(ok) == len(family_rows):
        v = "两行都 validated —— 算一个发现 (不算两次确认, D-128)。下发要另记 DECISIONS, 副题库不写 feature_validation。"
    elif len(ok) == 1:
        v = (f"单行过，不算发现 (D-128 补记 3): 只有 {ok[0]} validated ({st})。不下发, 不升主题库, 等 2027-04-02 那次再读。")
    else:
        v = f"没有发现: 两行都没过 ({st})。"
        if any(r["status"] == "insufficient" for r in family_rows):
            v += " insufficient = 样本不够, 不等于被否定 (D-128 功效那条)。"
    c2 = next((r for r in family_rows if r["question_id"] == "invites_sharing"), None)
    if c2 is not None and c2["status"] in ("insufficient", "no_signal"):
        v += (" C2 读出「样本不够」或不显著: invites_sharing 模型偏宽 (闸一 A 判「是」23 篇里 9 篇参考是「否」), 「是」组里"
              "混着约四成参考的「否」, 效应往 1 拉 (D-128 闸一结论第 2 点)。")
    return v


# ── 副题库: 报告 ─────────────────────────────────────────────────────────────────

def _f(v, d=2) -> str:
    return "—" if v is None else f"{v:.{d}f}"


def _fp(p) -> str:
    return "—" if p is None else (f"{p:.1e}" if p < 0.001 else f"{p:.3f}")


def _secondary_head(res: dict) -> list[str]:
    cs = res["condition_snapshot"]
    lines = [f"> 题库 `{res['bank_version']}` sha `{res['sha']}` (frozen) · 答案 run_tag `{res['answers_run_tag']}` · "
             f"模型题 {', '.join(f'{q} v{v}' for q, v in res['model_questions'].items())} 只认 `{SEC_LLM_EXTRACTOR}` · "
             f"代码特征 {', '.join(f'{q} v{v}' for q, v in res['code_features'].items())} 只认 `{fb.CODE_EXTRACTOR}`",
             f"> 分层快照 (gate2.condition_snapshot): 主题库 `{res['primary_version']}` sha `{cs['bank_sha256'][:12]}…` · "
             f"run_tag `{cs['run_tag']}` · {', '.join(cs['extractors'])} · "
             f"{', '.join(f'{q} v{v}' for q, v in cs['questions'].items())} (别的抽取器的行不算, 本次快照外 "
             f"{res['ignored_rows']['condition']} 行)",
             "> 名单: " + " · ".join(f"`{m['path']}` {m['n']} 篇 sha256 `{m['sha256']}`" for m in res["manifests"]),
             f"> 合并名单 {res['n_manifest']:,} 篇 · 名单 sha `{res['combined_sha']}` · note_id 逗号拼接 md5 `{res['ids_md5']}` · "
             f"半区 {res['half']} (D-129 换了 id、按 old_id 定半区的 {res['half_by_old_id']} 篇)"]
    return lines


def _drops_table(res: dict) -> list[str]:
    lines = ["| 掉出去的原因 (补记 5; 一篇只归第一种) | 篇 | 明细 |", "|---|---|---|"]
    for k in SEC_DROP_KINDS:
        v = res["drops"][k]
        lines.append(f"| {SEC_DROP_LABELS[k]} | {sum(v.values())} | "
                     + ("; ".join(f"{a} {b}" for a, b in v.items()) or "—") + " |")
    lines.append(f"| **合计** | **{res['n_drop']}** | 容忍上限 {res['tolerance']} 篇 (名单 {res['n_manifest']:,} 篇的 3%)"
                 + (" —— **超过了, 读的时候会拒**" if res["would_refuse"] else "") + " |")
    lines += ["", "正文截断记 NULL 的 (不算缺, 也不进分子分母): "
              + (", ".join(f"{q} {n}" for q, n in sorted(res["truncated"].items())) or "0") + f" · 进分析集 {res['n_analysis']:,} 篇"]
    return lines


def _coverage_table(res: dict) -> list[str]:
    lines = ["| 题 | 版本 | 抽取器 | 快照行 | 名单内的行 | 有答案 | NULL (原因) | 名单里没行 | 名单外的行 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for q, c in res["coverage"].items():
        nulls = "; ".join(f"{k} {v}" for k, v in c.get("null_by_reason", {}).items()) or "0"
        lines.append(f"| `{q}` | v{c['version']} | {c['extractor']} | {c.get('rows', '—')} | {c['rows_in_manifest']} | "
                     f"{c['answered']} | {nulls if 'null_by_reason' in c else '—'} | {c['manifest_without_row']} | "
                     f"{c.get('rows_outside_manifest', '—')} |")
    lines.append(f"\n副题库 run_tag 下快照外的行 (别的 sha / 抽取器): {res['ignored_rows']['secondary']}")
    return lines


def render_counts_secondary(res: dict) -> str:
    """--counts-only: 只有行数、覆盖、名单核对 —— 没有 y、没有 OR、没有 p (读之前只许跑这个, D-128 补记 6)。"""
    lines = [f"# 闸二 · 副题库 · 只数行数 · {res['run_tag']}", ""] + _secondary_head(res) + [
        "", "## 名单与掉出去的", ""] + _drops_table(res) + ["", "## 覆盖", ""] + _coverage_table(res) + [
        "", "这一份只数行数和覆盖, 不是闸二的读: 没把答案和标签放在一起算过。"]
    return "\n".join(lines) + "\n"


def render_report_secondary(res: dict) -> str:
    if res["void"]:
        return _render_void_secondary(res)
    p = res["params"]
    lines = [f"# 闸二 · 副题库 {res['bank_version']} · {res['run_tag']}", "",
             SEC_MARK.format(sha=res["sha"], man=res["combined_sha"], void=0), ""] + _secondary_head(res) + [
        f"> 分析集 {res['n_analysis']:,} 篇 (正例 {res['n_pos']:,}) · 大项目 (名单里、口径内爆 ≥ {p['big_pos']}): "
        + (", ".join(f"{k} {v}" for k, v in res["big_projects"].items()) or "无"),
        f"> 判据: 确认族两行 BH q ≤ {p['q_max']} · 支持 ≥ {p['min_support']} · 有支持的大项目 ≥ {p['min_big']}、最多 1 个反向 "
        f"(合并 2×2 +0.5) · 账号先验再分层后 OR 变化 ≤ {int(p['confound_delta'] * 100)}% · MH 的层 = 项目 × "
        + " × ".join(res["condition_snapshot"]["questions"]),
        f"> 账号先验档 (分析集): 无记录 {res['prior_strata'][PRIOR_NONE]} · 低于基线 {res['prior_strata'][PRIOR_BELOW]} · "
        f"不低于 {res['prior_strata'][PRIOR_AT_OR_ABOVE]} · 标签和名单写死时不同的 {res['y_changed']} 篇 (按现在的算) · "
        f"项目变了的 {res['project_changed']} 篇 (按现在的项目分层, 补记 4)", "",
        "## 结论", "", f"**{res['verdict']}**", "",
        "## 确认族 (BH 只在这两行里做)", "",
        "| 行 | 预注册 | 状态 | OR | 95% CI | p | q | 大项目同向/有支持 | 大项目分层内方向 (只报告) | 支持 / 基数 | "
        "先验分层 OR | 只按项目 OR | 不分层 OR | 说明 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in res["family_rows"]:
        lines.append(f"| `{r['question_id']}` {r['answer']} | {r['hypothesis']} | **{r['status']}** | {_f(r['mh_odds_ratio'])} | "
                     f"{_f(r['ci_low'])}–{_f(r['ci_high'])} | {_fp(r['p_value'])} | {_f(r['q_value'], 3)} | "
                     f"{r['big_projects_same_dir']}/{r['big_projects_n']} | "
                     f"{', '.join(f'{k} {v}' for k, v in r['big_within'].items()) or '—'} | {r['support']} / {r['base_n']} | "
                     f"{_f(r['mh_prior'])} | {_f(r['or_project_only'])} | {_f(r['or_crude'])} | {r['summary'].split(': ', 1)[-1]} |")
    lines += ["", "## 只报告 (不判状态、不进 BH、不下发)", "",
              "| 题 | 取值 | 比较基数 | 预注册 | OR | 95% CI | p | 支持 / 基数 | 大项目 >1/<1 (合并 2×2) | 大项目分层内方向 | "
              "只按项目 OR | 不分层 OR |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    kind_note = {"value": "其余提问类型 (剔掉 contrast_base_excludes)", "control": "全部 (阳性对照)", "merged": "其余提问类型",
                 "bool": "全部", "code": "全部"}
    for r in res["report_rows"]:
        lines.append(f"| `{r['question_id']}` | {r['answer']} | {kind_note[r['kind']]} | {r['hypothesis']} | "
                     f"{_f(r['mh_odds_ratio'])} | {_f(r['ci_low'])}–{_f(r['ci_high'])} | {_fp(r['p_value'])} | "
                     f"{r['support']} / {r['base_n']} | {r['n_or_above_1']}/{r['n_or_below_1']} of {r['big_projects_n']} | "
                     f"{', '.join(f'{k} {v}' for k, v in r['big_within'].items()) or '—'} | {_f(r['or_project_only'])} | "
                     f"{_f(r['or_crude'])} |")
    lines += ["", "「只按项目」= 不分 ending_asks_reader / asks_for_help 的层 (主题库的分法); 「不分层」= 全部并成一张 2×2。"
              "两者和上面分层的 OR 差得多时, 是分层题在混杂 (辛普森那种), 以分层的为准。", "",
              f"## 敏感性重跑 (只报告): 剔掉记过置顶 / 控评 / 铺评 / 投流的 {res['sensitivity_dropped']} 篇, 再加一层 body_len_bucket", "",
              "剔的依据: `notes.data_quality_flags.comment_maintained_routes` 非空 (铺评工单 / 起量后干预 / 铺评未跨线)、"
              "`data_quality_flags.paid_promoted = true`、`notes.pinned_comment` 非空。命中: "
              + (", ".join(f"{k} {v}" for k, v in res["sensitivity_flags"].items()) or "无"), "",
              "| 行 | OR | 95% CI | p | 支持 / 基数 |", "|---|---|---|---|---|"]
    for s in res["sensitivity"]:
        lines.append(f"| `{s['question_id']}` {s['answer']} | {_f(s['mh_odds_ratio'])} | {_f(s['ci_low'])}–{_f(s['ci_high'])} | "
                     f"{_fp(s['p_value'])} | {s['support']} / {s['base_n']} |")
    lines += ["", "## 反证 (占位题, 不在 BH 家族里)", "",
              f"3 道占位题按主题库定义从 note_id 现算, 同一份名单、同样分层。报警 = 支持 ≥ {p['min_support']} 且有支持的大项目 ≥ "
              f"{p['min_big']}、区间不跨 1、原始 p ≤ {p['placebo_p_max']}、大项目最多一个反向, 四条同时满足 (补记 2)。", ""]
    lines += _placebo_table(res)
    lines += ["", "过: 没有一道占位题报警。", "", "## 掉出去的与覆盖", ""] + _drops_table(res) + [""] + _coverage_table(res)
    lines += ["", "## 读的时候要记着的两点 (D-128 闸一结论, 不改判定)", "",
              "1. reader_ask_form 按 C1 两组看, A 和参考跨组的错判两个方向差不多 (3 对 4); 错判和爆不相关时效应只会往 1 拉, 偏保守。",
              "2. invites_sharing 模型偏宽: 参考「是」16 篇, A 判「是」23 篇, 其中 9 篇参考是「否」 —— C2 的「是」组里混着约四成参考的「否」。",
              "", "## 不写", "", "- 副题库的结果永远不写 `feature_validation` (D-128): 馆员取全表最新的一次闸二、不分题库, 写进去写作台的规律下发会整体断掉。"
              "结论只进这份报告和 DECISIONS。"]
    return "\n".join(lines) + "\n"


def _placebo_table(res: dict) -> list[str]:
    lines = ["| 占位题 | OR | 95% CI | 原始 p | 支持 | 大项目 >1/<1 (合并 2×2) | 报警 |", "|---|---|---|---|---|---|---|"]
    for r in res["placebo_rows"]:
        lines.append(f"| `{r['question_id']}` | {_f(r['mh_odds_ratio'])} | {_f(r['ci_low'])}–{_f(r['ci_high'])} | "
                     f"{_fp(r['p_value'])} | {r['support']} | {r['n_or_above_1']}/{r['n_or_below_1']} of {r['big_projects_n']} | "
                     f"{'**报警**' if r['alarm'] else '—'} |")
    return lines


def _render_void_secondary(res: dict) -> str:
    """占位题报警 (补记 2): 这次读作废。报告只写报警内容和计数, 确认族两行不出 OR、p 和状态 (它们根本没算)。"""
    lines = [f"# 闸二 · 副题库 {res['bank_version']} · {res['run_tag']} · 作废 (占位题报警)", "",
             SEC_MARK.format(sha=res["sha"], man=res["combined_sha"], void=1), ""] + _secondary_head(res) + [
        f"> 分析集 {res['n_analysis']:,} 篇", "",
        f"## 占位题报警: {', '.join(res['placebo_alarm'])}", "",
        "这次读作废 (D-128 补记 2): 确认族两行没有算, 这份报告里没有它们的 OR、p 和状态。查清原因 (快照混了、标签没清洗之类)、"
        "记进 DECISIONS 之后可以重读; 作废这次没露出两行的结果, 不算用掉「只读一次」(报告名带 -void)。", ""]
    lines += _placebo_table(res)
    lines += ["", "## 掉出去的与覆盖", ""] + _drops_table(res) + [""] + _coverage_table(res)
    return "\n".join(lines) + "\n"


# ── 副题库: 取数 (生产) ─────────────────────────────────────────────────────────

def fetch_dataset_secondary(sb, *, bank: dict, primary: dict, answers_run_tag: str = SEC_ANSWERS_RUN_TAG) -> dict:
    """run_gate2_secondary 要的 dataset。两份快照分开查, 每次查一个 (题, 抽取器, 版本) 的切片 —— 这个切片里 subject_id 唯一
    (主键 subject_type, subject_id, question_id, question_version, extractor, run_tag), fetch_all_pages 按 subject_id 去重
    不会吞掉行。版本不对的行另用一个有上限的查询捞出来放进 answers, 让 run_gate2_secondary 拒 (不在这里静默丢)。
    D-129 映射表读不到 / 0 对 → Gate2Refused (fail closed)。正文、置顶评论的文字都不取, 只取「有没有」。快照外的行
    (同 run_tag、同题, 别的 sha / 抽取器) 只数不取, 放进 ignored_rows。"""
    from _common import fetch_all_pages, fetch_half_alias, fetch_vanished_note_ids, mask_secrets
    try:
        alias = fetch_half_alias(sb)
    except Exception as exc:  # noqa: BLE001 — 什么原因都一样: 半区定不了就不跑
        raise Gate2Refused(f"D-129 映射表读不到, 半区定不了, 不跑 (fail closed): {type(exc).__name__}: "
                           f"{mask_secrets(str(exc))[:300]}") from exc
    tv = lambda t: sb.schema("truth_vault").table(t)                            # noqa: E731
    labels = fetch_all_pages(tv("v_l2_labels").select("note_id, project_id, account_id, publish_time, y"), order_by="note_id")
    meta = {r["note_id"]: r for r in fetch_all_pages(
        tv("notes").select("note_id, emotional_lever, data_quality_flags, pinned_comment"), order_by="note_id")}
    blen = {r["note_id"]: r.get("body_len")
            for r in fetch_all_pages(tv("note_features").select("note_id, body_len"), order_by="note_id")}
    vanished = fetch_vanished_note_ids(sb)
    notes = []
    for r in labels:
        if r["note_id"] in vanished:
            continue
        m = meta.get(r["note_id"]) or {}
        notes.append({"note_id": r["note_id"], "project_id": r["project_id"], "account_id": r.get("account_id"),
                      "publish_time": r.get("publish_time"), "y": int(r["y"]),
                      "has_essence": m.get("emotional_lever") is not None, "body_len": blen.get(r["note_id"]),
                      "data_quality_flags": m.get("data_quality_flags") or {},
                      "has_pinned_comment": m.get("pinned_comment") not in (None, "")})
    cols = "subject_type, subject_id, question_id, question_version, bank_sha256, extractor, run_tag, answer, invalid_reason"
    slices = [(answers_run_tag, bank["_sha256"], q["id"], int(q["version"]), SEC_LLM_EXTRACTOR) for q in fb.llm_questions(bank)]
    slices += [(answers_run_tag, bank["_sha256"], c["id"], int(c["version"]), fb.CODE_EXTRACTOR)
               for c in bank.get("code_features") or []]
    snap = bank["gate2"]["condition_snapshot"]
    pidx = fb.question_index(primary)
    conds = []
    for q in fb.llm_questions(bank):
        conds += [c for c in q.get("conditional_on") or [] if c not in conds]
    slices += [(snap["run_tag"], snap["bank_sha256"], c, int(pidx[c]["version"]), e) for c in conds for e in snap["extractors"]]
    answers: list[dict] = []
    for tag, sha, qid, ver, ext in slices:
        base = lambda: (tv("note_feature_answers").select(cols).eq("subject_type", "note").eq("run_tag", tag)  # noqa: E731
                        .eq("bank_sha256", sha).eq("question_id", qid).eq("extractor", ext))
        answers.extend(fetch_all_pages(base().eq("question_version", ver), order_by="subject_id"))
        # 同一切片里版本不对的行 (比如 invites_sharing v1 混进副题库 sha 下): 有一行就够拒, 捞前 50 行
        answers.extend((base().neq("question_version", ver).limit(50).execute()).data or [])
    # 快照外的行 (同 run_tag、同题, 别的 sha / 抽取器, 比如 primary 下 Opus 4.6 的分层行): 上面只取了快照那一片, 这些行
    # 到不了 run_gate2_secondary, 这里只数不取 —— 报告里「快照外 N 行」要的是库里的真数, 不是 0
    def _n(tag, qid, sha=None, ext=None) -> int:
        q = (tv("note_feature_answers").select("subject_id", count="exact").eq("subject_type", "note")
             .eq("run_tag", tag).eq("question_id", qid))
        if sha is not None:
            q = q.eq("bank_sha256", sha).eq("extractor", ext)
        return int(q.limit(1).execute().count or 0)
    groups: dict[tuple[str, str, str], tuple[str, set]] = {}
    for tag, sha, qid, _ver, ext in slices:
        kind = "secondary" if tag == answers_run_tag else "condition"
        groups.setdefault((kind, tag, qid), (sha, set()))[1].add(ext)
    ignored = {"secondary": 0, "condition": 0}
    for (kind, tag, qid), (sha, exts) in groups.items():
        ignored[kind] += _n(tag, qid) - sum(_n(tag, qid, sha, e) for e in sorted(exts))
    return {"notes": notes, "vanished": sorted(vanished), "answers": answers, "half_alias": alias, "ignored_rows": ignored}


def main_secondary(args, bank_path) -> int:
    """副题库那条路的 CLI (main 按题库 role 分过来)。退出码: 0 读完 / 只数完; 2 拒跑; 3 占位题报警、作废报告已写。"""
    def refuse(msg) -> int:
        print(f"闸二 (副题库) 没跑: {msg}", file=sys.stderr)
        return 2

    if args.write or args.expect_rows_sha256 or args.rows_out:
        return refuse("副题库的结果永远不写 feature_validation (D-128): 不收 --write / --expect-rows-sha256 / --rows-out")
    if args.allow_draft:
        return refuse("副题库不收 --allow-draft: 只读冻结的题库 (D-128 闸一结论, status: frozen)")
    if args.ignore_placebo_alarm:
        return refuse("占位题报警 = 这次读作废 (D-128 补记 2), 不许忽略")
    if args.projects or args.unreliable:
        return refuse("范围由名单定、闸一裁决在题库里: 不收 --projects / --unreliable")
    if (args.q_max, args.min_support, args.min_big, args.big_pos, args.confound_delta) != (0.10, 30, 3, 20, 0.30):
        return refuse("判据跑之前写死在 D-128 (q ≤ 0.10、支持 ≥ 30、大项目 ≥ 3 / 爆 ≥ 20、先验变化 ≤ 30%), 不收改动")
    if args.extractors and {e.strip() for e in args.extractors.split(",") if e.strip()} != {fb.CODE_EXTRACTOR, SEC_LLM_EXTRACTOR}:
        return refuse(f"副题库的抽取器钉死是 {SEC_LLM_EXTRACTOR} (模型题) + {fb.CODE_EXTRACTOR} (代码特征), 不收 {args.extractors!r}")
    if not args.sha:
        return refuse("--sha 必填: 副题库 digest 的前缀 (≥ 8 位, D-128 写的是 9f2cf1c9e7de)")
    if not args.manifest:
        return refuse("--manifest 必填: 进了仓库的名单 CSV (第一波 data-analysis/gate2-reader-holdout-2026-10-27.csv, 第二波另给一次)")
    try:
        bank, primary = fb.load_bank_pair(bank_path)
    except ValueError as exc:
        return refuse(str(exc))
    out = Path(args.out) if args.out else None
    if args.counts_only:
        # 只数行数的文件只许叫 …-counts.md, 也不许盖掉带「读过」标记的报告 (盖掉 = 抹掉只读一次的记号)
        if out is not None:
            if not out.name.endswith("-counts.md"):
                return refuse(f"--counts-only 的 --out 要叫 …-counts.md (收到 {out.name}): 不和读的报告混名")
            try:
                marked = out.exists() and SEC_MARK_RE.search(out.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError) as exc:
                return refuse(f"{out} 读不了, 不覆盖: {exc}")
            if marked:
                return refuse(f"{out} 是读过的报告 (带标记), 只数行数不许盖掉它 (补记 7)")
    else:
        # 正式读必须留下记号: 报告写进 --reports-dir (默认 data-analysis/), 那里才是 prior_secondary_reads 找的地方 (补记 7)
        if out is None:
            return refuse("正式读必须带 --out, 把报告写进 data-analysis/: 只打到 stdout 的读不留记号, 「只读一次」守不住 (补记 7)")
        # 连库的正式读只认 data-analysis/: --reports-dir 指到别处, 那里没有读过的报告, 第二次读就放过去了 (补记 7 实现口径)
        if not args.fixture and Path(args.reports_dir).resolve() != REPORTS_DIR.resolve():
            return refuse(f"连库的正式读只在 {REPORTS_DIR} 找读过的报告、只往那里写 (收到 --reports-dir {args.reports_dir}): "
                          "--reports-dir 只给 --fixture 的离线跑用 (补记 7)")
        if out.resolve().parent != Path(args.reports_dir).resolve():
            return refuse(f"正式读的报告必须写进 {args.reports_dir} (收到 --out {out}): 写到别处, 下次读找不到它 (补记 7)")
        if out.suffix != ".md":
            return refuse(f"正式读的报告名必须以 .md 结尾 (收到 {out.name}): 「读过没有」只扫 *.md, 别的扩展名下次读找不到它 "
                          "(补记 7; codex review on #246)")
        if "-void" in out.name:
            return refuse(f"报告名 {out.name} 带 -void: 那是作废报告的名字 (补记 7), 正式读不许这么叫")
        if out.name.endswith("-counts.md"):
            return refuse(f"报告名 {out.name} 以 -counts.md 结尾: 那是只数行数的名字, 正式读不许这么叫")
        if out.exists() or void_path(out).exists():
            return refuse(f"{out} (或 -void 那份) 已经在了, 不覆盖")
        if not args.fixture:
            loose = untracked_manifests(args.manifest)
            if loose:
                return refuse(f"名单没进仓库: {loose} —— 正式读只读进了仓库的名单 (先 git add -f, D-128 补记)")
    dirs = [Path(args.reports_dir)] + ([out.parent] if out is not None else [])
    try:
        manifests = load_manifests(args.manifest)
        if args.fixture:
            dataset = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        else:
            from _common import get_supabase_client
            dataset = fetch_dataset_secondary(get_supabase_client(), bank=bank, primary=primary,
                                              answers_run_tag=args.answers_run_tag)
        res = run_gate2_secondary(dataset, bank, primary, sha=args.sha, manifests=manifests, run_tag=args.run_tag,
                                  answers_run_tag=args.answers_run_tag, counts_only=args.counts_only, reports_dirs=dirs)
    except Gate2Refused as exc:
        return refuse(exc)
    if args.counts_only:
        text = render_counts_secondary(res)
        if out is not None:
            out.write_text(text, encoding="utf-8")
        else:
            print(text)
        print(f"闸二 (副题库) 只数行数: 名单 {res['n_manifest']} 篇、掉出去 {res['n_drop']} 篇 (上限 {res['tolerance']})"
              + (" —— 超过 3%, 读的时候会拒" if res["would_refuse"] else ""), file=sys.stderr)
        return 0
    text = render_report_secondary(res)
    target = void_path(out) if res["void"] else out
    target.write_text(text, encoding="utf-8")
    if res["void"]:
        print(f"闸二 (副题库) 作废: 占位题报警 {res['placebo_alarm']} —— 确认族两行没算; 报告 {target} "
              "(补记 2: 查清原因、记 DECISIONS 后可重读)", file=sys.stderr)
        return 3
    print("闸二 (副题库): " + ", ".join(f"{r['question_id']}={r['answer']} {r['status']}" for r in res["family_rows"])
          + f" · 名单 sha {res['combined_sha'][:12]} —— 报告进 data-analysis/ 并提交, 「只读一次」靠它守 (补记 7)", file=sys.stderr)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sha", default="", help="bank_sha256 前缀 (≥ 8 位), 快照的一半 (必填; 副题库给副题库的 sha)")
    ap.add_argument("--extractors", default="", help="逗号分隔, 快照的另一半, 如 code:v1,llm:claude-opus-4-6 (主题库必填; "
                                                     "副题库钉死, 不用给)")
    ap.add_argument("--run-tag", default="gate2-" + datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    ap.add_argument("--bank", default=str(fb.BANK_PATH),
                    help="题库: primary / reader (feature_bank.BANKS 的键) 或 yaml 路径; role: secondary 的走副题库那条路 (D-128)")
    ap.add_argument("--projects", default="", help="逗号分隔只看这些项目; 空 = 全部")
    ap.add_argument("--unreliable", default="", help="逗号分隔, 额外打 unreliable 的题号 (题库 gate1_status: fail 的题自动算, D-103)")
    ap.add_argument("--q-max", type=float, default=0.10)
    ap.add_argument("--min-support", type=int, default=30)
    ap.add_argument("--min-big", type=int, default=3)
    ap.add_argument("--big-pos", type=int, default=20)
    ap.add_argument("--confound-delta", type=float, default=0.30)
    ap.add_argument("--allow-draft", action="store_true", help="题库没冻结也跑 (试算 / CI 夹具); 正式跑不许")
    ap.add_argument("--ignore-placebo-alarm", action="store_true", help="反证没过也出报告 (只为排查, 不写库)")
    ap.add_argument("--fixture", default="", help="离线: 从 json 读 {notes, answers} (副题库另带 vanished / half_alias), 不连库")
    ap.add_argument("--out", default="", help="报告 markdown 路径")
    ap.add_argument("--rows-out", default="", help="feature_validation 行 json 路径")
    ap.add_argument("--write", action="store_true", help="写 feature_validation (upsert, 主键含 gate2_run); 必须带 --expect-rows-sha256")
    ap.add_argument("--expect-rows-sha256", default="",
                    help="--write 必带: 这次算出的 feature_validation 行摘要必须以它开头 (≥12 位十六进制), 从看过报告的那次 "
                         "(报告末尾 / stdout 的 rows_sha256) 抄 —— 写进库的就是看过的那份, 中间数据变了就拒 (codex review on #173)")
    # 副题库 (D-128 / docs/28 §6.2b) 才用的四个
    ap.add_argument("--manifest", action="append", default=[],
                    help="副题库: 进了仓库的名单 CSV, 可给多次 (第一波 + 第二波); 只读名单里的篇, 名单 sha 进报告")
    ap.add_argument("--counts-only", action="store_true",
                    help="副题库: 只数行数 / 覆盖 / 名单, 不出 y 的交叉表、OR、p (读之前只许跑这个, D-128 补记 6)")
    ap.add_argument("--answers-run-tag", default=SEC_ANSWERS_RUN_TAG, help="副题库答案的 run_tag (fqr-*)")
    ap.add_argument("--reports-dir", default=str(REPORTS_DIR),
                    help="副题库: 到这里找读过的报告 (同一份名单只读一次, 补记 7); 只给 --fixture 的离线跑改, "
                         "连库的正式读只认 data-analysis/ (改了就拒)")
    args = ap.parse_args(argv)
    bank_path = fb.BANKS.get(args.bank, args.bank)
    if fb.load_bank(bank_path).get("role") == fb.ROLE_SECONDARY:
        return main_secondary(args, bank_path)
    if args.manifest or args.counts_only or args.answers_run_tag != SEC_ANSWERS_RUN_TAG:
        ap.error("--manifest / --counts-only / --answers-run-tag 只给副题库 (--bank reader)")
    if not args.sha or not args.extractors:
        ap.error("the following arguments are required: --sha, --extractors")
    extractors = [e.strip() for e in args.extractors.split(",") if e.strip()]
    unreliable = [u.strip() for u in args.unreliable.split(",") if u.strip()]
    projects = {p.strip() for p in args.projects.split(",") if p.strip()} or None
    bank = fb.load_bank(bank_path)
    sb = None
    try:
        if args.fixture:
            dataset = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        else:
            from _common import get_supabase_client
            sb = get_supabase_client()
            dataset = fetch_dataset(sb, bank=bank, sha=args.sha, extractors=extractors, projects=projects)
        assert_projects_present(dataset, projects)
        result = run_gate2(dataset, bank, sha=args.sha, extractors=extractors, run_tag=args.run_tag, q_max=args.q_max,
                           min_support=args.min_support, min_big=args.min_big, big_pos=args.big_pos,
                           confound_delta=args.confound_delta, unreliable=unreliable, allow_draft=args.allow_draft,
                           ignore_placebo_alarm=args.ignore_placebo_alarm)
    except Gate2Refused as exc:
        print(f"闸二没跑: {exc}", file=sys.stderr)
        return 2
    report = render_report(result)
    rows = validation_rows(result)
    digest = rows_digest(rows)
    report += (f"\n## 行摘要\n\n`rows_sha256` = `{digest}` —— 写库那次带 `--expect-rows-sha256 {digest[:12]}` 核对, "
               "摘要对不上就不写 (codex review on #173)。\n")
    print(f"rows_sha256 {digest}")
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
    else:
        print(report)
    if args.rows_out:
        Path(args.rows_out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.write:
        want = args.expect_rows_sha256.strip().lower()
        if not want:
            print("--write 要带 --expect-rows-sha256 <看过的那次的 rows_sha256 前 ≥12 位>: 先不带 --write 跑一次、看报告、抄摘要, "
                  "再写 (codex review on #173)", file=sys.stderr)
            return 2
        if len(want) < 12 or any(c not in "0123456789abcdef" for c in want) or not digest.startswith(want):
            print(f"不写库: 这次算出的行摘要 {digest[:12]}… 与 --expect-rows-sha256 {want[:12]}… 对不上 —— 中间账本 / 标签变了, "
                  "或抄错了; 重新出报告、重新看", file=sys.stderr)
            return 2
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
