#!/usr/bin/env python3
"""
check_external_direction.py
═══════════════════════════════════════════════════════════════════════════

外部方向复核 (D-117 #3, J-14 ①): 下发给写作台的已验证规律 (prompts/desk_delivery_v1.json), 在外部笔记
(truth_vault.external_notes, 不是我们投的帖) 上方向还对不对? —— 只读, 不写库。

为什么要看: 闸二只在我们自己的帖子上验过。自己投、自己铺评、自己判爆, 飞轮只学自己, 一条规律可能只是我们这套
打法的特征 (近亲繁殖, jev docs/00 #11)。外部帖是另一群人写的, 方向在那边也对, 才更像「这么写本身管用」。

口径:
  · 爆 = 评论 ≥ 50 (和我们判爆同一把尺子);
  · 只看「有就算」(any_of) 的规律; 「别这么写」那条 (品牌位置) 外部帖不是我们的品牌, 不适用;
  · 模型题用 Jev 已经给外部帖打好的答案 (note_feature_answers, subject_type=external_note, 同一份冻结题库);
    代码题 (问号数) 用 feature_bank.code_features 同一套代码在外部正文上现算;
  · 有 / 没有 两侧各至少 30 篇才判 (MIN_N); 不够就写「样本不够」, 不判。

顺带报外部参考书架 (D-117 ②, librarian/external.py) 每个品类达标几张 —— 和馆员上架用同一个 qualifies, 口径只有一份。

灯 (docs/29 登记, advisory): 有一条规律在够样本的情况下外部方向相反 → rc=1, 提醒这条可能只在我们自己帖子上成立,
该拿出来议 (改下发的是批准层, 修在 TV 仓 prompts/desk_delivery_v1.json + 新 D 号)。外部表空 → rc=2。
末行哨兵 EXTERNAL_DIRECTION_CHECK_DONE rc=<码>。

用法:
    python check_external_direction.py
    python check_external_direction.py --selftest     # CI: 不连库
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from librarian import external as X  # noqa: E402

DELIVERY = ROOT / "prompts" / "desk_delivery_v1.json"
BAO_COMMENTS = 50
MIN_N = 30


def judge(patterns: list[dict], notes: list[dict], answers: dict[str, dict[str, str]]) -> tuple[int, list[str]]:
    """纯函数。notes: [{note_id, comments}]; answers: {note_id: {question_id: answer}}。返回 (rc, 报告行)。"""
    lines = [f"外部方向复核 · {len(notes)} 篇 (评论 ≥{BAO_COMMENTS} 的 "
             f"{sum(1 for n in notes if (n.get('comments') or 0) >= BAO_COMMENTS)} 篇) · 两侧各 ≥{MIN_N} 篇才判"]
    if not notes:
        lines.append("  ⚠️  external_notes 是空的, 判不了")
        return 2, lines
    rc = 0
    for p in patterns:
        f = p.get("follow") or {}
        if not f.get("any_of"):
            lines.append(f"  —  {p['label']}: 「别这么写」类规律, 外部帖不是我们的品牌, 不适用")
            continue
        has, no = [0, 0], [0, 0]                        # [篇数, 爆]
        unknown = 0
        for n in notes:
            ans = answers.get(n["note_id"]) or {}
            qs = {q for q, _ in f["any_of"]}
            if not (qs & set(ans)):
                unknown += 1
                continue
            side = has if any(ans.get(q) == a for q, a in f["any_of"]) else no
            side[0] += 1
            side[1] += int((n.get("comments") or 0) >= BAO_COMMENTS)
        rh = has[1] / has[0] if has[0] else None
        rn = no[1] / no[0] if no[0] else None
        fmt = (lambda r: "—" if r is None else f"{100 * r:.1f}%")
        body = (f"{p['label']}: 有 {has[0]} 篇 {fmt(rh)} / 没有 {no[0]} 篇 {fmt(rn)}"
                + (f" (没答 {unknown})" if unknown else ""))
        if has[0] < MIN_N or no[0] < MIN_N:
            same = "同向" if (rh is not None and rn is not None and rh > rn) else "方向不明"
            lines.append(f"  …  {body} → 样本不够, 不判 (目前{same})")
        elif rh > rn:
            lines.append(f"  ✅ {body} → 外部也同向")
        else:
            lines.append(f"  🟡 {body} → 外部方向相反: 这条可能只在我们自己的帖子上成立。拿出来议, 要撤就改批准层 "
                         "prompts/desk_delivery_v1.json 并写新 D 号 (修在 TV 仓)")
            rc = 1
    return rc, lines


def shelf_counts(notes: list[dict], cfg: Optional[dict]) -> list[str]:
    """外部参考书架每个登记品类达标几张 (纯函数)。"""
    if not cfg:
        return ["  ⚠️  外部参考书架配置读不了, 馆员这次不给外部卡"]
    n = {c: sum(1 for r in notes if r.get("category") == c and X.qualifies(r, cfg)) for c in cfg["categories"]}
    return ["外部参考书架达标 (评论 ≥{} · 没带产品 · 不像广告): ".format(cfg["min_comments"])
            + " · ".join(f"{c} {k}" for c, k in n.items())]


def _code_answers(notes: list[dict], qids: set[str]) -> dict[str, dict[str, str]]:
    sys.path.insert(0, str(ROOT / "scripts"))
    import feature_bank as fb
    out: dict[str, dict[str, str]] = {}
    for n in notes:
        body = n.get("body") or ""
        spans = {"title": n.get("title"), "_body_untruncated": body, "body": body}
        feats = fb.code_features(spans, [])
        out[n["note_id"]] = {q: v[0] for q, v in feats.items() if q in qids and v[0] is not None}
    return out


def gather(sb, d: dict) -> tuple[list[dict], dict[str, dict[str, str]]]:
    from _common import fetch_all_pages
    notes = fetch_all_pages(sb.schema("truth_vault").table("external_notes")
                            .select("note_id, category, title, body, comments, has_product, ad_like"),
                            order_by="note_id")
    qids = {q for p in d["patterns"] for q, _ in (p.get("follow") or {}).get("any_of") or []}
    sys.path.insert(0, str(ROOT / "scripts"))
    import feature_bank as fb
    code_q = {q["id"] for q in fb.load_bank().get("code_features") or []} & qids
    answers = _code_answers(notes, code_q)
    # ⚠️ fetch_all_pages 要求 order_by 那一列唯一: 一篇有好几道题的答案, 所以按题一道一道取 (题内 subject_id 唯一)
    for q in sorted(qids - code_q):
        rows = fetch_all_pages(
            sb.schema("truth_vault").table("note_feature_answers").select("subject_id, answer")
            .eq("subject_type", "external_note").eq("bank_sha256", d["bank_sha256"]).eq("question_id", q),
            order_by="subject_id")
        for r in rows:
            if r.get("answer") is not None:
                answers.setdefault(r["subject_id"], {})[q] = str(r["answer"])
    return notes, answers


def selftest() -> int:
    d = json.loads(DELIVERY.read_text(encoding="utf-8"))
    pats = d["patterns"]
    def notes(spec):
        out, ans = [], {}
        for i, (has, bao) in enumerate(spec):
            nid = f"n{i}"
            out.append({"note_id": nid, "comments": 60 if bao else 3})
            ans[nid] = {"ending_asks_reader": "是" if has else "否"}
        return out, ans
    n, a = notes([(1, 1)] * 20 + [(1, 0)] * 20 + [(0, 1)] * 10 + [(0, 0)] * 30)
    rc, lines = judge(pats, n, a)
    assert rc == 0 and any("结尾问读者" in l and "✅" in l for l in lines), lines
    n, a = notes([(1, 1)] * 5 + [(1, 0)] * 35 + [(0, 1)] * 20 + [(0, 0)] * 20)
    rc, lines = judge(pats, n, a)
    assert rc == 1 and any("🟡" in l and "结尾问读者" in l for l in lines), lines
    n, a = notes([(1, 0)] * 10 + [(0, 1)] * 40)
    rc, lines = judge(pats, n, a)
    assert rc == 0 and any("样本不够" in l for l in lines), "一侧不到 30 篇不判"
    assert any("品牌别硬插" in l and "不适用" in l for l in lines)
    assert judge(pats, [], {})[0] == 2
    cfg = X.load_config()
    rows = [{"category": "鼻炎", "comments": 80, "has_product": False}, {"category": "鼻炎", "comments": 80, "has_product": True},
            {"category": "戒烟", "comments": 10, "has_product": False}]
    assert "鼻炎 1" in shelf_counts(rows, cfg)[0] and "戒烟 0" in shelf_counts(rows, cfg)[0]
    print("  ✓ selftest: 同向 / 反向亮黄 / 样本不够不判 / 品牌类不适用 / 表空 / 书架达标数")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[4])
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    d = json.loads(DELIVERY.read_text(encoding="utf-8"))
    from _common import get_supabase_client
    notes, answers = gather(get_supabase_client(), d)
    rc, lines = judge(d["patterns"], notes, answers)
    print("\n".join(lines + shelf_counts(notes, X.load_config())))
    print(f"EXTERNAL_DIRECTION_CHECK_DONE rc={rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
