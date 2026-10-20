#!/usr/bin/env python3
"""
gate3_score.py
═══════════════════════════════════════════════════════════════════════════

闸三第一轨 (docs/28 §6.3, D-118): 用【冻结的】essence 打分器, 给冻结日之后发布的每条笔记打分, 写
truth_vault.content_scores; 再按附录 C 报一次进度 (两档爆率、单侧两比例检验、离样本量还差多少)。

冻结的东西全在 data-analysis/gate3/scorer-essence-v1-93035a562b2e.json (D-123), 由 freeze-essence-v1.sql 在生产只读算出
(D-118 定的口径; 10-20 D-122 恢复了被夜跑冲掉的 F / U token 之后按同一 SQL 重冻, 冻结日不动, 10-17 起的分按新版重打。
10-16 那份 scorer-essence-v1.json = essence-v1-322f02c9465f 留在目录里作历史, 不再读):
  · 权重: token (L/F/A/U, 与 gate2_combo.tag_features 同一套) → w = ln((爆+1)/(趴+1)), 冻结日前的全部训练集;
  · 切点: 每个项目冻结日前笔记分数的 101 个分位 (不足 50 篇的项目用全库);
  · essence 标注器: 词表 v0.2 + claude-sonnet-5-5 + prediction_feature。闸三期间换 essence 模型 / 词表,
    新笔记的标签和冻结权重就不是一回事了 —— 这种笔记不打分, 计 annotator_mismatch, 灯红。
文件里的 scorer_version 带核心内容的 sha256 前 12 位; 读的时候重算, 对不上就拒跑 (有人手改了冻结文件)。

打分只做一次: content_scores 的主键是 (subject_type, subject_id, scorer_version), 写用 ignore_duplicates ——
已经打过的笔记以后 essence 被重标也不改分 (「入库即打分」, 闸三测的是前瞻)。

这是一盏拖红的灯 (docs/29 登记): 闸三要攒一到几个月的数, 漏打 / 标注器被换掉都会让整轮作废, 不能等到出结论那天
才发现。退出码 1 = 写失败 / 有该打没打上的 / 有标注器对不上的; 末行哨兵 GATE3_SCORE_CHECK_DONE rc=<码>。

用法:
    python gate3_score.py                     # 打分 + 进度
    python gate3_score.py --dry-run           # 只算不写
    python gate3_score.py --selftest          # CI 用, 不连库 (同 check_gate3.py)
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

ROOT = Path(__file__).resolve().parent.parent
SCORER_PATH = ROOT / "data-analysis" / "gate3" / "scorer-essence-v1-93035a562b2e.json"   # 文件名 = scorer-<scorer_version>.json (D-123)
CORE_KEYS = ("scorer", "freeze_publish_time", "token_scheme", "weights", "cutpoints", "frozen_annotator", "criteria")
STALE_ESSENCE_HOURS = 72          # 入库超过这么久还没 essence 的, 单独报 (essence 每日有上限, 正常会排队一两天)
NOTE_COLS = ("note_id, project_id, publish_time, created_at, emotional_lever, content_format, human_truth_archetype, "
             "target_audience, essence_vocab_version, essence_annotated_by, essence_annotation_mode")


class ScorerTampered(RuntimeError):
    pass


# ── 冻结文件 ─────────────────────────────────────────────────────────────────

def scorer_digest(sc: dict) -> str:
    core = {k: sc[k] for k in CORE_KEYS}
    return hashlib.sha256(json.dumps(core, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def load_scorer(path: Path = SCORER_PATH) -> dict:
    sc = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = [k for k in CORE_KEYS + ("scorer_version",) if k not in sc]
    if missing:
        raise ScorerTampered(f"冻结文件缺字段 {missing}")
    want = f"{sc['scorer']}-{scorer_digest(sc)[:12]}"
    if sc["scorer_version"] != want:
        raise ScorerTampered(f"冻结文件被改过: scorer_version={sc['scorer_version']}, 按内容重算是 {want}。"
                             " 冻结的打分器不许改; 要换就另起版本、写新 D 号、闸三重新计时。")
    return sc


# ── 打分 ─────────────────────────────────────────────────────────────────────

def _as_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v if x not in (None, "")]
    return [str(v)] if str(v) else []


def note_tokens(note: dict) -> set[str]:
    """与 gate2_combo.tag_features 逐字同一套 (check_gate3 §2 钉着两边一致)。"""
    out = {"L:" + x for x in _as_list(note.get("emotional_lever"))}
    out |= {"F:" + x for x in _as_list(note.get("content_format"))}
    out |= {"A:" + x for x in _as_list(note.get("human_truth_archetype"))}
    out |= {"U:" + x for x in _as_list(note.get("target_audience"))}
    return out


def score_tokens(tokens: Iterable[str], weights: dict) -> Optional[float]:
    ws = [float(weights[t]) for t in tokens if t in weights]
    return round(sum(ws) / len(ws), 6) if ws else None


def pct_from_quantiles(s: float, q: list) -> float:
    """101 个分位 (0, 0.01 … 1) 上的位置, 0 = 最差。落在一段相等分位上取那段的中点 (分数离散, 并列很多)。"""
    if s < q[0]:
        return 0.0
    if s > q[-1]:
        return 1.0
    lo, hi = bisect.bisect_left(q, s), bisect.bisect_right(q, s)
    if lo < hi:
        return round((lo + hi - 1) / 2 / 100, 6)
    k = lo - 1
    span = q[k + 1] - q[k]
    frac = (s - q[k]) / span if span > 0 else 0.0
    return round(min(1.0, max(0.0, (k + frac) / 100)), 6)


def cutpoints_for(project_id: str, sc: dict) -> tuple[list, str]:
    proj = (sc["cutpoints"].get("project") or {}).get(project_id)
    if proj:
        return proj["q"], "project"
    return sc["cutpoints"]["pooled"]["q"], "pooled"


def annotator_ok(note: dict, sc: dict) -> bool:
    fa = sc["frozen_annotator"]
    return (note.get("essence_vocab_version") == fa["essence_vocab_version"]
            and note.get("essence_annotated_by") == fa["essence_annotated_by"]
            and note.get("essence_annotation_mode") == fa["essence_annotation_mode"])


def _ts(v) -> Optional[datetime]:
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def plan(notes: list[dict], already: set[str], sc: dict, now: datetime) -> dict:
    """纯函数: 冻结日之后的笔记 → 这一轮要写的行 + 各类计数。不碰库。"""
    freeze = sc["freeze_publish_time"]
    rows: list[dict] = []
    c = Counter()
    mismatch: list[str] = []
    for n in sorted(notes, key=lambda r: r["note_id"]):
        if str(n.get("publish_time") or "") < freeze:
            continue                                   # 取数已经按 publish_time 过滤; 这里再挡一次 (fixture / 时区)
        c["after_freeze"] += 1
        if not (n.get("emotional_lever") or ""):
            c["no_essence"] += 1
            created = _ts(n.get("created_at"))
            if created and now - created > timedelta(hours=STALE_ESSENCE_HOURS):
                c["stale_essence"] += 1
            continue
        if n["note_id"] in already:
            c["already"] += 1
            continue
        if not annotator_ok(n, sc):
            c["annotator_mismatch"] += 1
            mismatch.append(n["note_id"])
            continue
        s = score_tokens(note_tokens(n), sc["weights"])
        if s is None:
            c["unscorable"] += 1
            continue
        q, kind = cutpoints_for(n["project_id"], sc)
        rows.append({"subject_type": "note", "subject_id": n["note_id"], "project_id": n["project_id"],
                     "scorer_version": sc["scorer_version"], "score": s, "pct_in_project": pct_from_quantiles(s, q),
                     "cutpoints": kind, "shadow": True})
        c["pooled" if kind == "pooled" else "project_cut"] += 1
    return {"rows": rows, "counts": c, "mismatch": mismatch}


# ── 判定 (附录 C) ────────────────────────────────────────────────────────────

def one_sided_p(b_pos: int, b_n: int, r_pos: int, r_n: int) -> Optional[float]:
    """H1: 最低档爆率 < 其余爆率。合并方差的两比例 z, 单侧。"""
    if not b_n or not r_n:
        return None
    p = (b_pos + r_pos) / (b_n + r_n)
    if p in (0.0, 1.0):
        return None
    z = (r_pos / r_n - b_pos / b_n) / math.sqrt(p * (1 - p) * (1 / b_n + 1 / r_n))
    return 0.5 * math.erfc(z / math.sqrt(2))


def verdict(labeled: list[dict], sc: dict) -> dict:
    """labeled: [{pct_in_project, y}] —— 已打分、已落标签 (v_l2_labels)、在分析口径内的冻结后笔记。"""
    cr = sc["criteria"]
    b = [r for r in labeled if float(r["pct_in_project"]) < cr["bottom_pct"]]
    rest = [r for r in labeled if float(r["pct_in_project"]) >= cr["bottom_pct"]]
    b_pos, r_pos = sum(int(r["y"]) for r in b), sum(int(r["y"]) for r in rest)
    out = {"bottom_n": len(b), "bottom_pos": b_pos, "rest_n": len(rest), "rest_pos": r_pos,
           "bottom_rate": b_pos / len(b) if b else None, "rest_rate": r_pos / len(rest) if rest else None,
           "p": one_sided_p(b_pos, len(b), r_pos, len(rest))}
    out["ratio"] = (out["bottom_rate"] / out["rest_rate"]) if out["rest_rate"] else None
    if len(b) < cr["min_bottom"] or len(rest) < cr["min_rest"]:
        out["status"] = "accumulating"
    elif out["ratio"] is not None and out["p"] is not None and out["ratio"] <= cr["ratio_max"] and out["p"] < cr["alpha"]:
        out["status"] = "pass"
    else:
        out["status"] = "fail"
    return out


def report(res: dict, v: dict, sc: dict) -> int:
    c, cr = res["counts"], sc["criteria"]
    print(f"闸三第一轨 · {sc['scorer_version']} · 冻结日 {sc['freeze_publish_time']} (D-118 / D-123)")
    print(f"  冻结后发布 {c['after_freeze']} 篇: 本轮新打 {len(res['rows'])}、以前打过 {c['already']}、"
          f"还没 essence {c['no_essence']} (其中入库超过 {STALE_ESSENCE_HOURS}h 的 {c['stale_essence']})、"
          f"标注器对不上 {c['annotator_mismatch']}、没有可用 token {c['unscorable']}")
    if res["rows"]:
        print(f"  新打的切点: 项目内 {c['project_cut']} / 全库 {c['pooled']}")
    def _r(x):
        return "—" if x is None else f"{100 * x:.2f}%"
    ratio = "—" if v["ratio"] is None else f"{v['ratio']:.2f}"
    pval = "—" if v["p"] is None else f"{v['p']:.4f}"
    print(f"  已落标签: 最低20% {v['bottom_n']} 篇 (爆 {v['bottom_pos']}, {_r(v['bottom_rate'])}) · "
          f"其余 {v['rest_n']} 篇 (爆 {v['rest_pos']}, {_r(v['rest_rate'])}) · 比值 {ratio} · 单侧 p {pval}")
    need_b, need_r = max(0, cr["min_bottom"] - v["bottom_n"]), max(0, cr["min_rest"] - v["rest_n"])
    if v["status"] == "accumulating":
        print(f"  进度: 还差最低档 {need_b} 篇、其余 {need_r} 篇 (目标 {cr['min_bottom']} / {cr['min_rest']}), 不出结论")
    else:
        print(f"  ⚖️  样本够了, 判定 = {v['status']} (线: 比值 ≤ {cr['ratio_max']} 且 p < {cr['alpha']})。写 DECISIONS, 不自动做任何事")
    rc = 0
    if c["annotator_mismatch"]:
        fa = sc["frozen_annotator"]
        print(f"  🔴 {c['annotator_mismatch']} 篇冻结后笔记的 essence 不是冻结的标注器 "
              f"({fa['essence_vocab_version']} / {fa['essence_annotated_by']} / {fa['essence_annotation_mode']}) 标的,"
              f" 例 {res['mismatch'][:3]}。闸三期间换了 essence 模型或词表, 这些笔记不能用冻结权重打 —— "
              "要么换回去, 要么另冻一个版本、写新 D 号、闸三重新计时。修在 TV 仓 (ESSENCE_MODEL / 词表)。")
        rc = 1
    return rc


# ── 生产 ─────────────────────────────────────────────────────────────────────

def fetch(sb, sc: dict) -> tuple[list[dict], set[str]]:
    from _common import fetch_all_pages
    notes = fetch_all_pages(sb.schema("truth_vault").table("notes").select(NOTE_COLS)
                            .gte("publish_time", sc["freeze_publish_time"]), order_by="note_id")
    done = {r["subject_id"] for r in fetch_all_pages(
        sb.schema("truth_vault").table("content_scores").select("subject_id")
        .eq("subject_type", "note").eq("scorer_version", sc["scorer_version"]), order_by="subject_id")}
    return notes, done


def write(sb, rows: list[dict]) -> int:
    for i in range(0, len(rows), 200):
        sb.schema("truth_vault").table("content_scores").upsert(
            rows[i:i + 200], on_conflict="subject_type,subject_id,scorer_version", ignore_duplicates=True).execute()
    return len(rows)


def fetch_labeled(sb, sc: dict) -> list[dict]:
    """附录 C: 已打分 ∩ v_l2_labels, 口径同训练集 (正文 ≥ 50 字或未知、飞书里没删)。"""
    from _common import fetch_all_pages, fetch_vanished_note_ids
    scores = {r["subject_id"]: r for r in fetch_all_pages(
        sb.schema("truth_vault").table("content_scores").select("subject_id, pct_in_project")
        .eq("subject_type", "note").eq("scorer_version", sc["scorer_version"]), order_by="subject_id")}
    if not scores:
        return []
    labels = fetch_all_pages(sb.schema("truth_vault").table("v_l2_labels").select("note_id, y")
                             .gte("publish_time", sc["freeze_publish_time"]), order_by="note_id")
    ids = [r["note_id"] for r in labels if r["note_id"] in scores]
    short: set[str] = set()
    for i in range(0, len(ids), 100):
        for r in fetch_all_pages(sb.schema("truth_vault").table("note_features").select("note_id, body_len")
                                 .in_("note_id", ids[i:i + 100]), order_by="note_id"):
            if r.get("body_len") is not None and int(r["body_len"]) < 50:
                short.add(r["note_id"])
    vanished = fetch_vanished_note_ids(sb)
    return [{"note_id": r["note_id"], "y": r["y"], "pct_in_project": scores[r["note_id"]]["pct_in_project"]}
            for r in labels if r["note_id"] in scores and r["note_id"] not in short and r["note_id"] not in vanished]


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[3])
    ap.add_argument("--scorer", default=str(SCORER_PATH))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        import check_gate3
        return check_gate3.main()
    sc = load_scorer(Path(args.scorer))
    from _common import get_supabase_client
    sb = get_supabase_client()
    notes, done = fetch(sb, sc)
    res = plan(notes, done, sc, datetime.now(timezone.utc))
    rc = 0
    if not args.dry_run and res["rows"]:
        write(sb, res["rows"])
        _, done_after = fetch(sb, sc)
        lost = [r["subject_id"] for r in res["rows"] if r["subject_id"] not in done_after]
        if lost:
            print(f"  🔴 写完回读少了 {len(lost)} 篇 (例 {lost[:3]}): content_scores 没写进去, 闸三在漏数。")
            rc = 1
    v = verdict(fetch_labeled(sb, sc), sc)
    rc = max(rc, report(res, v, sc))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"### 闸三第一轨 ({sc['scorer_version']})\n\n本轮新打 {len(res['rows'])} 篇; 已落标签 "
                    f"最低20% {v['bottom_n']} / 其余 {v['rest_n']} (目标 {sc['criteria']['min_bottom']} / "
                    f"{sc['criteria']['min_rest']}); 状态 {v['status']}\n\n")
    print(f"GATE3_SCORE_CHECK_DONE rc={rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
