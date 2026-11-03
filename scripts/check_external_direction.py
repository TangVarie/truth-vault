#!/usr/bin/env python3
"""
check_external_direction.py
═══════════════════════════════════════════════════════════════════════════

外部方向复核 (D-117 #3, J-14 ①): 下发给写作台的已验证规律 (prompts/desk_delivery_v1.json), 在外部笔记
(truth_vault.external_notes, 不是我们投的帖) 上方向还对不对? —— 只读, 不写库。

为什么要看: 闸二只在我们自己的帖子上验过。自己投、自己铺评、自己判爆, 飞轮只学自己, 一条规律可能只是我们这套
打法的特征 (近亲繁殖, jev docs/00 #11)。外部帖是另一群人写的, 方向在那边也对, 才更像「这么写本身管用」。

口径 (D-127, 10-26 改: 原来 ≥50 对 <50、不分层、谁大算谁, 真实无效应时一半的周一会报「相反」):
  · 和闸二同一个比法 (docs/28 §6.2): 爆 = 评论 ≥ 50 对 趴 = 评论 < 20, 中间 20–49 (运营口径的「评估中」) 不进表;
  · 按品类分层 (外部一个品类就是一两个搜索词的结果页, 爆率差很多), Mantel–Haenszel 合并优势比 + RGB 区间,
    用 gate2_run.mh_odds_ratio 同一个函数;
  · 区间整段在 1 的上面才算「外部也同向」, 整段在下面才亮「外部方向相反」, 跨 1 = 外部看不出, 不判;
  · 只看「有就算」(any_of) 的规律; 「别这么写」那条 (品牌位置) 外部帖不是我们的品牌, 不适用;
  · 模型题用 Jev 已经给外部帖打好的答案 (note_feature_answers, subject_type=external_note, 同一份冻结题库);
    代码题 (问号数) 用 feature_bank.code_features 同一套代码在外部正文上现算;
  · 去掉中间段之后有 / 没有 两侧各至少 30 篇才判 (MIN_N); 不够就写「样本不够」, 不判。

顺带报外部参考书架 (D-117 ②, librarian/external.py) 每个品类达标几张 —— 和馆员上架用同一个 qualified (D-138: 发出 3–90 天、
最近抓到、评论 ≥20、日均评论不低于同品类中位数; D-140: 带产品也收, Jev 功效题答「否」才收), 口径只有一份; 功效题的答案
也用馆员同一个 X.fetch_answers 取。另报这些帖里有几篇已经有有效的遮挡行 (没有的上架时只给结构)。书架的评论门槛不再是这里判爆的 50: 书架看起量速度, 这里看闸二的结果标签。
D-141 起书架分产品贴 (P: Jev 全文答 product_role 主角 / 解决方案) 和其他 (O) 两族, 每篇和自己那族的中位数比; 这里也用馆员
同一个 X.fetch_roles 分族, 每个品类后面括号里报两族各几篇; product_role 读不了就照 D-140 不分族报, 并写明。

灯 (docs/29 登记, advisory): 有一条规律在够样本、品类内区间整段 < 1 时 → rc=1, 提醒这条可能只在我们自己帖子上成立,
该拿出来议 (改下发的是批准层, 修在 TV 仓 prompts/desk_delivery_v1.json + 新 D 号)。外部表空 / 某道题的外部答案不止一个
抽取器 (Jev 换版没清旧答案) → rc=2, 判不了。
末行哨兵 EXTERNAL_DIRECTION_CHECK_DONE rc=<码>。

用法:
    python check_external_direction.py
    python check_external_direction.py --selftest     # CI: 不连库
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from librarian import external as X  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from gate2_run import mh_odds_ratio  # noqa: E402  (闸二的同一个 MH + RGB, 口径只有一份)

DELIVERY = ROOT / "prompts" / "desk_delivery_v1.json"
BAO_COMMENTS = 50
FLOP_COMMENTS = 20      # 闸二口径: 趴 = 评论 < 20; 20–49 是「评估中」, 不进表 (docs/28 §6.2)
MIN_N = 30


def _outcome(comments) -> Optional[int]:
    """1 = 爆 (≥50), 0 = 趴 (<20), None = 中间段, 不进表。"""
    c = comments or 0
    return 1 if c >= BAO_COMMENTS else (0 if c < FLOP_COMMENTS else None)


def judge(patterns: list[dict], notes: list[dict], answers: dict[str, dict[str, str]],
          mixed: frozenset = frozenset()) -> tuple[int, list[str]]:
    """纯函数。notes: [{note_id, comments, category}]; answers: {note_id: {question_id: answer}};
    mixed: 外部答案不止一个抽取器的题 (不判)。返回 (rc, 报告行)。rc: 1 有规律方向相反 > 2 有判不了的 > 0。"""
    outs = [_outcome(n.get("comments")) for n in notes]
    lines = [f"外部方向复核 · {len(notes)} 篇 · 同闸二口径: 爆 (评论 ≥{BAO_COMMENTS}) {outs.count(1)} 篇 对 "
             f"趴 (<{FLOP_COMMENTS}) {outs.count(0)} 篇, 中间 {outs.count(None)} 篇不算 · 按品类分层 · "
             f"两侧各 ≥{MIN_N} 篇才判, 区间整段在 1 的一侧才算有方向"]
    if not notes:
        lines.append("  ⚠️  external_notes 是空的, 判不了")
        return 2, lines
    rc = 0
    for p in patterns:
        f = p.get("follow") or {}
        if not f.get("any_of"):
            lines.append(f"  —  {p['label']}: 「别这么写」类规律, 外部帖不是我们的品牌, 不适用")
            continue
        mixed_q = sorted({q for q, _ in f["any_of"]} & set(mixed))
        if mixed_q:
            lines.append(f"  ⚠️  {p['label']}: 外部答案里 {mixed_q} 不止一个抽取器, 混着算会张冠李戴, 不判 —— "
                         "先定用哪一版 Jev 的答案")
            rc = rc or 2
            continue
        qs = {q for q, _ in f["any_of"]}
        tables: dict[str, list[int]] = {}                 # 品类 → [有·爆, 有·趴, 没有·爆, 没有·趴]
        unknown = 0
        for n, y in zip(notes, outs):
            ans = answers.get(n["note_id"]) or {}
            if not (qs & set(ans)):
                unknown += 1
                continue
            if y is None:
                continue
            has = any(ans.get(q) == a for q, a in f["any_of"])
            t = tables.setdefault(n.get("category") or "—", [0, 0, 0, 0])
            t[(0 if has else 2) + (0 if y else 1)] += 1
        a, b, c, d = (sum(t[i] for t in tables.values()) for i in range(4))
        fmt = (lambda k, m: "—" if not m else f"{100 * k / m:.1f}%")
        body = (f"{p['label']}: 有 {a + b} 篇爆 {fmt(a, a + b)} / 没有 {c + d} 篇爆 {fmt(c, c + d)}"
                + (f" (没答 {unknown})" if unknown else ""))
        if a + b < MIN_N or c + d < MIN_N:
            lines.append(f"  …  {body} → 样本不够, 不判")
            continue
        m = mh_odds_ratio(tuple(t) for t in tables.values())
        if m is None:
            lines.append(f"  …  {body} → 品类内比不出来 (每个品类都缺一格), 不判")
            continue
        est = f"品类内 OR {m['or']:.2f} ({m['ci_low']:.2f}–{m['ci_high']:.2f})"
        if m["ci_low"] > 1:
            lines.append(f"  ✅ {body}, {est} → 外部也同向")
        elif m["ci_high"] < 1:
            lines.append(f"  🟡 {body}, {est} → 外部方向相反: 这条可能只在我们自己的帖子上成立。拿出来议, 要撤就改批准层 "
                         "prompts/desk_delivery_v1.json 并写新 D 号 (修在 TV 仓)")
            rc = 1
        else:
            lines.append(f"  …  {body}, {est} → 区间跨 1, 外部看不出方向, 不算相反")
    return rc, lines


def shelf_counts(notes: list[dict], cfg: Optional[dict], answers: Optional[dict] = None, *,
                 masks: Optional[dict] = None, now: Optional[float] = None, roles: Optional[dict] = None) -> list[str]:
    """外部参考书架每个登记品类达标几张 (纯函数; ``now`` 给 selftest 钉时间)。登记了、外部表里还没有的品类报 0。
    ``answers``: {note_id: {题: 答}} (X.fetch_answers); None = 读不了 → 报「判不了」, 不报 0。
    ``masks``: {note_id: 遮挡行} (X.fetch_masks); 给了就另报每个品类达标帖里有几篇有有效遮挡行。
    ``roles``: {note_id: product_role} (X.fetch_roles, D-141); 给了就按族比中位数、每个品类括号里报 产品贴 / 其他 各几篇;
    None = 读不了 → 照 D-140 不分族, 行里写明。"""
    if not cfg:
        return ["  ⚠️  外部参考书架配置读不了, 馆员这次不给外部卡"]
    if answers is None:
        return ["  ⚠️  外部帖的功效题答案读不了, 书架达标数这次判不了 (馆员那边这时也不给外部卡)"]
    cands = X.candidates(notes, cfg, now=now, roles=roles)
    got = X.qualified(notes, cfg, answers, now=now, roles=roles)

    def per_cat(c: str) -> str:
        rs = [r for r, _, _ in got if r.get("category") == c]
        if roles is None:
            return f"{c} {len(rs)}"
        p = sum(1 for r in rs if X.family(roles, r.get("note_id")) == X.FAMILY_P)
        return f"{c} {len(rs)} (产品贴 {p} · 其他 {len(rs) - p})"
    med = "同品类同一族 (产品贴 / 其他) 的中位数" if roles is not None else "同品类中位数 (product_role 读不了, 这次不分族)"
    out = ["外部参考书架达标 (发出 {}–{} 天 · 最近 {} 天抓到 · 评论 ≥{} · 日均评论不低于{} · 不像广告 · "
           "功效题答「否」): ".format(X.MIN_AGE_DAYS, cfg["max_age_days"], X.FRESH_DAYS, cfg["min_comments"], med)
           + " · ".join(per_cat(c) for c in cfg["categories"])
           + f"  (功效题挡掉 {len(cands) - len(got)} 篇)"]
    if masks is not None:
        ok = {c: sum(1 for r, _, _ in got if r.get("category") == c
                     and X.valid_mask(r, masks.get(str(r.get("note_id")))) is not None) for c in cfg["categories"]}
        out.append("  其中有有效遮挡行 (上架给遮过的摘录; 没有的只给结构): " + " · ".join(f"{c} {k}" for c, k in ok.items()))
    return out


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


EXTERNAL_RUN_TAG = "external"   # Jev 给外部帖答题写的 run_tag (10-16 实查: 全部是 external × jev:1.13.0)


def gather(sb, d: dict) -> tuple[list[dict], dict[str, dict[str, str]], frozenset]:
    from _common import fetch_all_pages
    notes = fetch_all_pages(sb.schema("truth_vault").table("external_notes")
                            .select("note_id, category, title, body, comments, has_product, ad_like, fetched_at"),
                            order_by="note_id")
    qids = {q for p in d["patterns"] for q, _ in (p.get("follow") or {}).get("any_of") or []}
    sys.path.insert(0, str(ROOT / "scripts"))
    import feature_bank as fb
    code_q = {q["id"] for q in fb.load_bank().get("code_features") or []} & qids
    answers = _code_answers(notes, code_q)
    # ⚠️ fetch_all_pages 要求 order_by 那一列唯一 (重复的会被丢掉)。一篇有好几道题、Jev 换版后同一题还可能有
    # 两个抽取器的答案, 所以按 (题, 抽取器) 一份一份取, subject_id 才唯一。一道题出现第二个抽取器就不判,
    # 混着算会张冠李戴 (闸一吃过同样的亏, DECISIONS 闸一一致率那段)。
    mixed: set = set()
    for q in sorted(qids - code_q):
        def base():
            return (sb.schema("truth_vault").table("note_feature_answers")
                    .select("subject_id, extractor, answer")
                    .eq("subject_type", "external_note").eq("run_tag", EXTERNAL_RUN_TAG)
                    .eq("bank_sha256", d["bank_sha256"]).eq("question_id", q))
        top = (base().order("extractor", desc=True).limit(1).execute()).data or []
        if not top:
            continue
        extractor = top[0]["extractor"]
        if (base().neq("extractor", extractor).limit(1).execute()).data:
            mixed.add(q)
            continue
        for r in fetch_all_pages(base().eq("extractor", extractor), order_by="subject_id"):
            if r.get("answer") is not None:
                answers.setdefault(r["subject_id"], {})[q] = str(r["answer"])
    return notes, answers, frozenset(mixed)


class _FakeDB:
    """note_feature_answers / external_notes 的假库: 认 eq / neq / gte / order / limit / range。"""
    def __init__(self, tables):
        self.tables = tables

    def schema(self, s):
        return self

    def table(self, t):
        db = self

        class Q:
            def __init__(self):
                self.f, self.o, self.lim, self.rng = [], [], None, None

            def select(self, *a):
                return self

            def eq(self, c, v):
                self.f.append(lambda r: r.get(c) == v)
                return self

            def neq(self, c, v):
                self.f.append(lambda r: r.get(c) != v)
                return self

            def order(self, c, desc=False):
                self.o.append((c, desc))
                return self

            def limit(self, n):
                self.lim = n
                return self

            def range(self, a, b):
                self.rng = (a, b)
                return self

            def execute(self):
                rows = [r for r in db.tables.get(t, []) if all(f(r) for f in self.f)]
                for c, desc in reversed(self.o):
                    rows.sort(key=lambda r: str(r.get(c)), reverse=desc)
                if self.rng:
                    rows = rows[self.rng[0]:self.rng[1] + 1]
                if self.lim is not None:
                    rows = rows[:self.lim]
                return type("R", (), {"data": rows})()
        return Q()


def _selftest_gather(d: dict) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    sha = d["bank_sha256"]
    ans = lambda nid, q, a, ex="jev:1.13.0", tag="external": {  # noqa: E731
        "subject_type": "external_note", "subject_id": nid, "question_id": q, "answer": a,
        "extractor": ex, "run_tag": tag, "bank_sha256": sha}
    notes = [{"note_id": f"x{i}", "title": "t", "body": "b", "comments": 60, "category": "鼻炎",
              "has_product": False, "ad_like": False} for i in range(3)]
    rows = [ans("x0", "ending_asks_reader", "是"), ans("x1", "ending_asks_reader", "否"),
            ans("x2", "ending_asks_reader", "是", tag="gate1-v2"),           # 别的 run_tag 不算
            ans("x0", "asks_for_help", "是"), ans("x1", "asks_for_help", "否", ex="jev:1.14.0")]
    _, answers, mixed = gather(_FakeDB({"external_notes": notes, "note_feature_answers": rows}), d)
    assert answers.get("x0", {}).get("ending_asks_reader") == "是" and "ending_asks_reader" not in answers.get("x2", {}), \
        "只认 run_tag=external"
    assert mixed == frozenset({"asks_for_help"}) and "asks_for_help" not in answers.get("x0", {}), \
        "同一道题两个抽取器: 不混着用, 整题标出来不判"


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
    n, a = notes([(1, 1)] * 10 + [(1, 0)] * 20 + [(0, 1)] * 20 + [(0, 0)] * 40)     # 33.3% 对 33.3%
    rc, lines = judge(pats, n, a)
    assert rc == 0 and any("跨 1" in l for l in lines), "一样的爆率不是方向相反"

    def notes2(spec):                                  # (有没有, 评论数, 品类, 篇数)
        out, ans = [], {}
        for has, comments, cat, k in spec:
            for _ in range(k):
                nid = f"m{len(out)}"
                out.append({"note_id": nid, "comments": comments, "category": cat})
                ans[nid] = {"ending_asks_reader": "是" if has else "否"}
        return out, ans
    # D-127: 中间段 (20–49) 不进表 —— 原来 ≥50 对 <50 时, 有的那侧多落在中间段就被算成「相反」(10-26 正文抛问题那次)
    n, a = notes2([(1, 60, "x", 15), (1, 3, "x", 15), (1, 30, "x", 30), (0, 60, "x", 30), (0, 3, "x", 30)])
    rc, lines = judge(pats, n, a)
    assert rc == 0 and "中间 30 篇不算" in lines[0] and any("跨 1" in l and "结尾问读者" in l for l in lines), lines
    # 按品类分层: 合起来看是反的 (40% 对 54%), 每个品类里都是同向 —— 不亮「相反」
    n, a = notes2([(1, 60, "高", 8), (1, 3, "高", 2), (0, 60, "高", 60), (0, 3, "高", 30),
                   (1, 60, "低", 12), (1, 3, "低", 28), (0, 60, "低", 5), (0, 3, "低", 25)])
    rc, lines = judge(pats, n, a)
    assert rc == 0 and not any("🟡" in l for l in lines), lines
    # 不显著的反向 (43% 对 50%, 区间跨 1) 不亮
    n, a = notes2([(1, 60, "x", 13), (1, 3, "x", 17), (0, 60, "x", 15), (0, 3, "x", 15)])
    rc, lines = judge(pats, n, a)
    assert rc == 0 and any("跨 1" in l for l in lines), lines
    rc, lines = judge(pats, n, a, frozenset({"ending_asks_reader"}))
    assert rc == 2 and any("不止一个抽取器" in l and "结尾问读者" in l for l in lines), "抽取器混了不判"
    cfg = X.load_config()
    now = 1_790_000_000.0                               # 钉时间: 都是前一天抓的

    seq = iter(range(1, 100))

    def ext(cat, comments, age_days, **kw):             # note_id 前 8 位十六进制 = 发帖时刻, 后 16 位区分篇
        fetched = now - 86400
        return {"note_id": f"{int(fetched - age_days * 86400):08x}{next(seq):016x}", "category": cat, "comments": comments,
                "has_product": False, "fetched_at": datetime.fromtimestamp(fetched, timezone.utc).isoformat(), **kw}
    rows = [ext("鼻炎", 80, 10), ext("鼻炎", 80, 10, has_product=True), ext("鼻炎", 20, 60),   # 日均 8 / 8 / 0.33, 中位数 8
            ext("鼻炎", 300, 200),                                                            # 发出超过 90 天: 不算
            ext("戒烟", 10, 10)]                                                              # 评论不到 20
    ans = {r["note_id"]: {"efficacy_promise": "否"} for r in rows}
    line = shelf_counts(rows, cfg, ans, now=now)[0]
    assert "鼻炎 2" in line and "戒烟 0" in line and "家居家电 0" in line and "功效题挡掉 0 篇" in line, \
        f"D-140: 带产品的也算达标: {line}"
    ans[rows[1]["note_id"]] = {"efficacy_promise": "是"}
    line = shelf_counts(rows, cfg, ans, now=now)[0]
    assert "鼻炎 1" in line and "功效题挡掉 1 篇" in line, line
    assert "判不了" in shelf_counts(rows, cfg, None, now=now)[0], "答案读不了: 不报 0"
    masks = {rows[0]["note_id"]: {"note_id": rows[0]["note_id"], "terms": [],
                                  "text_sha": X.mask_text_sha(rows[0].get("title"), rows[0].get("body"))}}
    two = shelf_counts(rows, cfg, ans, masks=masks, now=now)
    assert "有效遮挡行" in two[1] and "鼻炎 1" in two[1], two
    assert "不分族" in line, "没给 product_role: 照 D-140 不分族, 行里写明"
    # D-141 分族: 戒烟 P 6 篇日均 2 / 4 / … / 12 (P 族中位数 7), O 6 篇日均 20 / 40 / … / 120 (O 族中位数 70);
    # 品类 12 篇中位数 16 —— 不分族达标的 6 篇全是 O; 分族后两族各 3 篇
    p = [ext("戒烟", 20 * k, 10) for k in range(1, 7)]
    o = [ext("戒烟", 200 * k, 10) for k in range(1, 7)]
    fam = p + o
    fans = {r["note_id"]: {"efficacy_promise": "否"} for r in fam}
    assert "戒烟 6 · " in shelf_counts(fam, cfg, fans, now=now)[0], shelf_counts(fam, cfg, fans, now=now)
    roles = {r["note_id"]: "解决方案" for r in p}
    line = shelf_counts(fam, cfg, fans, now=now, roles=roles)[0]
    assert "戒烟 6 (产品贴 3 · 其他 3)" in line and "同一族" in line and "鼻炎 0 (产品贴 0 · 其他 0)" in line, line
    _selftest_gather(d)
    print("  ✓ selftest: 同向 / 反向亮黄 / 持平不算反 / 中间段不进表 / 品类内比 / 不显著的反向不亮 / 抽取器混了不判 / "
          "样本不够不判 / 品牌类不适用 / 表空 / 书架达标数 (带产品也算、功效题挡、遮挡行数、分族报两族各几篇) / 取答案只认 external、"
          "抽取器混了标出来")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[4])
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    d = json.loads(DELIVERY.read_text(encoding="utf-8"))
    from _common import get_supabase_client
    sb = get_supabase_client()
    notes, answers, mixed = gather(sb, d)
    rc, lines = judge(d["patterns"], notes, answers, mixed)
    cfg = X.load_config()
    shelf_ans = masks = roles = None
    if cfg:
        roles = X.fetch_roles(sb, X.window_ids(notes, cfg))   # 和馆员同一个函数 (D-141); 读不了 = None, 不分族报
        ids = [r["note_id"] for r, _, _ in X.candidates(notes, cfg, roles=roles)]
        try:
            shelf_ans = X.fetch_answers(sb, ids)      # 和馆员同一个函数: 分批翻页、取最后抽的
            masks = X.fetch_masks(sb, ids)
        except Exception as exc:  # noqa: BLE001 —— 书架那行判不了不影响上面的方向判断
            print(f"  ⚠️  书架达标数要的答案读不了: {type(exc).__name__}: {str(exc)[:160]}")
    print("\n".join(lines + shelf_counts(notes, cfg, shelf_ans, masks=masks, roles=roles)))
    print(f"EXTERNAL_DIRECTION_CHECK_DONE rc={rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
