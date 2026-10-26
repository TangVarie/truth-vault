#!/usr/bin/env python3
"""check_gate1_models.py —— gate1_models.py (副题库闸一, D-128) 的自检。只用合成数据, 不连库。

断行为不断源码 (D-051), 反证 (改坏之后必须变红):
  ① 一趟里混了 extractor / 两个 sha / 主题库 sha / 旧版本号 / 一格两行 / 缺格 / 名单外的篇 / 没点名的 run_tag  → §3 红
  ② owner 的行不是 human:owner、裁决不在闭集; owner 的 run_tag 和模型重名; --bank 给主题库; 三趟不是 A/B/H     → §3 红
  ③ 读者怎么回答不按合并 3 档判 (挑一个 vs 说自己的算不一致)                                               → §1 红
  ④ 「至少一方不是没问读者」的子集把两边都没问读者的格算进去                                                → §1 红
  ⑤ invites_sharing 的 κ 不只在 A 层算                                                                     → §1 红
  ⑥ 证据无效率把不问的格 (text_too_short) 算进分母 / 把别的无效原因算进分子                                → §2 红
  ⑦ 复核推翻 3 格还判过; 没 owner 裁决却给出 pass                                                           → §4 红
  ⑧ 证据原文 (哨兵串) 出现在报告 / 格子表 / stdout 里                                                       → §5 红
  ⑨ 抽查格跟着 owner 的裁决变 (应只看模型的答案)                                                           → §6 红
  ⑩ yaml 的合并 / 剔除和 D-128 的 3 档对不上还照算                                                          → §7 红

跑法: cd scripts && python check_gate1_models.py
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import pathlib
import tempfile

import feature_bank as fb
import gate1_models as gm

SENTINEL = "哨兵证据串SENTINEL-7f3a"
BANK = gm.load_secondary("reader")
RUNS = gm.parse_runs(list(gm.DEFAULT_RUNS), BANK)
SHA = BANK["_sha256"]
PSHA = fb.load_bank()["_sha256"]
VER = {q["id"]: q["version"] for q in fb.llm_questions(BANK)}
TAG = {r.label: r.tag for r in RUNS}
EXT = {r.label: r.extractor for r in RUNS}
OWNER = gm.OWNER_RUN_TAG
N_A, N_B = 30, 10
NOTES = [f"SYN_recA{i:03d}" for i in range(N_A)] + [f"SYN_recB{i:03d}" for i in range(N_B)]
STRAT = {n: ("A" if "recA" in n else "B") for n in NOTES}


def _kappa_ref(pairs):
    """独立实现的 Cohen κ (不借 gate1_agreement), 用来对答案。"""
    n = len(pairs)
    cats = sorted({x for p in pairs for x in p})
    po = sum(a == b for a, b in pairs) / n
    pe = sum((sum(a == c for a, _ in pairs) / n) * (sum(b == c for _, b in pairs) / n) for c in cats)
    return (po - pe) / (1 - pe)


def _answers() -> dict:
    """{(note, qid): {A: (ans, reason), B: …, H: …}} 以及 owner 的裁决。设计好的几类格:
    读者怎么回答: 前 4 篇 A=挑一个/B=说自己的/H=挑一个 (合并档一致, 原始不一致); 4–7 A=求解答/B=求解答/H=求推荐;
    8 A 证据无效; 其余 A 层多数「说自己的」一致、B 层「没问读者」一致。
    请读者讲经历: 第 0 篇三趟都 text_too_short (不问); 1–5 A=是/B=否/H=是; 其余 A 层 是/否 交替一致, B 层「否」一致。"""
    cells = {}
    for i, n in enumerate(NOTES):
        a_layer = STRAT[n] == "A"
        if i < 4:
            raf = {"A": ("挑一个", None), "B": ("说自己的", None), "H": ("挑一个", None)}
        elif i < 8:
            raf = {"A": ("求解答", None), "B": ("求解答", None), "H": ("求推荐", None)}
        elif i == 8:
            raf = {"A": (None, fb.INVALID_EVIDENCE_NOT_FOUND), "B": ("说自己的", None), "H": ("说自己的", None)}
        elif a_layer:
            v = "说自己的" if i % 3 else "找同类"
            raf = {L: (v, None) for L in "ABH"}
        else:
            raf = {L: ("没问读者", None) for L in "ABH"}
        cells[(n, "reader_ask_form")] = raf
        if i == 0:
            inv = {L: (None, fb.INVALID_TEXT_TOO_SHORT) for L in "ABH"}
        elif i <= 5:
            inv = {"A": ("是", None), "B": ("否", None), "H": ("是", None)}
        elif a_layer:
            v = "是" if i % 2 else "否"
            inv = {L: (v, None) for L in "ABH"}
        else:
            inv = {L: ("否", None) for L in "ABH"}
        cells[(n, "invites_sharing")] = inv
    return cells


def _owner(cells: list[dict], overturn: int = 1) -> dict:
    """owner: 不一致的格按设计裁 (读者怎么回答前 4 篇 → 挑一个; 4–7 → 求推荐; 8 → 说自己的; 请读者讲经历 1–5 → 否);
    抽查格照一致的答案确认, 每题推翻 overturn 格。"""
    own = {}
    flips = {q: 0 for q in VER}
    for c in cells:
        k = (c["note_id"], c["question_id"])
        if c["kind"] == "disagree":
            i = NOTES.index(c["note_id"])
            if c["question_id"] == "reader_ask_form":
                own[k] = "挑一个" if i < 4 else ("求推荐" if i < 8 else "说自己的")
            else:
                own[k] = "否"
        elif c["kind"] == "spot":
            v = c["A"]
            if flips[c["question_id"]] < overturn:
                v = {"说自己的": "求解答", "找同类": "挑一个", "没问读者": "求解答", "是": "否", "否": "是"}[v]   # 跨合并档
                flips[c["question_id"]] += 1
            own[k] = v
    return own


def _rows(ans: dict, owner: dict | None = None) -> list[dict]:
    rows = []
    for (n, q), by in ans.items():
        for L, (a, why) in by.items():
            rows.append({"subject_id": n, "question_id": q, "question_version": VER[q], "bank_sha256": SHA,
                         "extractor": EXT[L], "run_tag": TAG[L], "answer": a, "invalid_reason": why,
                         "evidence": SENTINEL if a else None, "prob": None, "extra": SENTINEL})
    for (n, q), a in (owner or {}).items():
        rows.append({"subject_id": n, "question_id": q, "question_version": VER[q], "bank_sha256": SHA,
                     "extractor": gm.OWNER_EXTRACTOR, "run_tag": OWNER, "answer": a, "invalid_reason": None,
                     "evidence": SENTINEL})
    return rows


def _manifest(td: pathlib.Path) -> pathlib.Path:
    p = td / "gate1-reader-sample-synthetic.csv"
    lines = ["note_id,project_id,y,ear,afh,tiq,stratum,raw_md5"]
    for n in NOTES:
        e = "是" if STRAT[n] == "A" else "否"
        lines.append(f"{n},SYN,{int('A0' in n)},{e},否,否,{STRAT[n]},{'0' * 32}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _clean(rows):
    """模拟 load_rows: 只留白名单列。"""
    return [{c: r[c] for c in gm.ROW_COLUMNS} for r in rows]


def _run(rows, manifest, owner_tag=OWNER, **kw):
    return gm.run(_clean(rows), BANK, RUNS, manifest, owner_tag=owner_tag, **kw)


def _refused(fn, needle: str, what: str) -> None:
    try:
        fn()
    except gm.Gate1Refused as exc:
        assert needle in str(exc), f"{what}: 拒了但原因不对 (要含 {needle!r}): {exc}"
        return
    raise AssertionError(f"{what}: 该拒算没拒")


def _owner_for(manifest):
    _, cells0, _ = _run(_rows(_answers()), manifest, owner_tag=None)
    return cells0, _owner(cells0)


# §1 判定档与子集 ──────────────────────────────────────────────────────────────────────
def check_levels(td) -> None:
    m = _manifest(td)
    cells0, own = _owner_for(m)
    report, cells, res = _run(_rows(_answers(), own), m)
    raf, inv = res["reader_ask_form"], res["invites_sharing"]
    # 合并 3 档: 前 4 篇 挑一个/说自己的 → 合并档一致, 原始不一致
    assert raf["AB"]["n"] == raf["AB_raw"]["n"] == len(NOTES) - 1, (raf["AB"], raf["AB_raw"])
    assert raf["AB"]["agree"] == 1.0 and abs(raf["AB_raw"]["agree"] - (len(NOTES) - 1 - 4) / (len(NOTES) - 1)) < 1e-9, raf
    # A 对参考 (合并档): 手算对一遍
    ref = {c["cell_id"]: c["reference"] for c in cells}
    pairs = [(gm.level("reader_ask_form", c["A"]), gm.level("reader_ask_form", ref[c["cell_id"]])) for c in cells
             if c["question_id"] == "reader_ask_form" and c["A"] is not None and ref[c["cell_id"]] is not None]
    assert raf["AR"]["n"] == len(pairs) and abs(raf["AR"]["kappa"] - _kappa_ref(pairs)) < 1e-12, (raf["AR"], len(pairs))
    # 至少一方不是没问读者: 两边都没问读者的格不进
    sub = [p for p in pairs if p != ("没问读者", "没问读者")]
    assert raf["AR_asking"]["n"] == len(sub) < len(pairs) and abs(raf["AR_asking"]["kappa"] - _kappa_ref(sub)) < 1e-12
    # 可答 vs 其他问法: 两边都问了读者
    both = [p for p in pairs if "没问读者" not in p]
    assert raf["AR_ask_vs_other"]["n"] == len(both)
    # invites_sharing: κ 只在 A 层; 一致率在全部; 不问的那格不在任何 n 里
    inv_pairs = [(c["A"], ref[c["cell_id"]]) for c in cells if c["question_id"] == "invites_sharing"
                 and c["A"] is not None and ref[c["cell_id"]] is not None]
    a_pairs = [(c["A"], ref[c["cell_id"]]) for c in cells if c["question_id"] == "invites_sharing" and c["stratum"] == "A"
               and c["A"] is not None and ref[c["cell_id"]] is not None]
    assert inv["AR"]["n"] == len(inv_pairs) == len(NOTES) - 1 and inv["AR_stratumA"]["n"] == len(a_pairs) == N_A - 1
    assert abs(inv["AR_stratumA"]["kappa"] - _kappa_ref(a_pairs)) < 1e-12
    assert inv["kinds"]["skip"] == 1 and raf["kinds"]["disagree"] == 9 and inv["kinds"]["disagree"] == 5, (raf["kinds"], inv["kinds"])
    # 判定行里 invites_sharing 引的是 A 层 κ, reader_ask_form 引的是合并档和子集两条
    assert any("A 层" in w for w in inv["why"]) and any("至少一方不是没问读者" in w for w in raf["why"])
    # 三趟全错 = 只有复核推翻的那 1 格 (4–7 篇 owner 选了求推荐, H 对了, 不算全错)
    assert raf["all_wrong"] == 1 and inv["all_wrong"] == 1, (raf["all_wrong"], inv["all_wrong"])
    print("  §1 合并 3 档 (挑一个=说自己的)、A 对参考 κ 与独立实现一致、「至少一方不是没问读者」子集、请读者讲经历 κ 只在 A 层 ✓")


# §2 证据无效率 ─────────────────────────────────────────────────────────────────────
def check_evidence_rate(td) -> None:
    m = _manifest(td)
    ans = _answers()
    ans[(NOTES[9], "reader_ask_form")]["A"] = (None, fb.INVALID_EVIDENCE_TOO_LONG)
    ans[(NOTES[10], "reader_ask_form")]["A"] = (None, fb.INVALID_SPAN_TRUNCATED)      # 截断不是证据无效
    ans[(NOTES[11], "reader_ask_form")]["A"] = (None, fb.INVALID_FILTERED)            # 被拦不算问了
    _, _, res = _run(_rows(ans), m, owner_tag=None)
    iv = res["reader_ask_form"]["invalid"]["A"]
    assert iv["asked"] == len(NOTES) - 1 and iv["evidence_bad"] == 2, iv
    assert abs(iv["rate"] - 2 / (len(NOTES) - 1)) < 1e-12 and res["reader_ask_form"]["line_evidence"] is False   # 2/39 > 3%
    iv2 = res["invites_sharing"]["invalid"]["A"]
    assert iv2["asked"] == len(NOTES) - 1 and iv2["evidence_bad"] == 0 and iv2["reasons"] == {fb.INVALID_TEXT_TOO_SHORT: 1}, iv2
    assert res["invites_sharing"]["line_evidence"] is True
    print("  §2 证据无效率 = (evidence_not_found + evidence_too_long) ÷ 问了的格; 不问 / 被拦不进分母, 截断不进分子 ✓")


# §3 拒算 ─────────────────────────────────────────────────────────────────────────
def check_refusals(td) -> None:
    m = _manifest(td)
    base = _rows(_answers())

    def mut(fn):
        rows = copy.deepcopy(base)
        fn(rows)
        return lambda: _run(rows, m, owner_tag=None)
    a_rows = lambda rows: [r for r in rows if r["run_tag"] == TAG["A"]]  # noqa: E731
    _refused(mut(lambda rs: a_rows(rs)[0].update(extractor="llm:claude-opus-4-6")), "extractor 应只有", "一趟混了两个抽取器")
    _refused(mut(lambda rs: a_rows(rs)[0].update(bank_sha256="1" * 64)), "bank_sha256 应只有", "一趟两个 sha")
    _refused(mut(lambda rs: [r.update(bank_sha256=PSHA) for r in rs if r["run_tag"] == TAG["H"]]), "主题库 sha", "一趟在主题库 sha 下")
    _refused(mut(lambda rs: [r.update(question_version=1) for r in rs if r["question_id"] == "invites_sharing"
                             and r["run_tag"] == TAG["B"]]), "question_version 应是 2", "旧版本号")
    _refused(mut(lambda rs: rs.append(dict(a_rows(rs)[0]))), "格有多行", "一格两行")
    _refused(mut(lambda rs: rs.remove([r for r in rs if r["run_tag"] == TAG["H"]][5])), "覆盖不全", "缺一格")
    _refused(mut(lambda rs: rs.append(dict(a_rows(rs)[0], subject_id="SYN_recZ999"))), "不在名单里", "名单外的篇")
    _refused(mut(lambda rs: rs.append(dict(a_rows(rs)[0], run_tag="fqr-g1-other"))), "没点名的 run_tag", "没点名的 run_tag")
    _refused(mut(lambda rs: a_rows(rs)[0].update(answer="外星选项", invalid_reason=None)), "不在闭集", "答案不在闭集")
    _refused(mut(lambda rs: a_rows(rs)[0].update(question_id="ending_asks_reader")), "不是本库的题", "混进主题库的题")
    cells0, own = _owner_for(m)
    rows = _rows(_answers(), own)
    bad = copy.deepcopy(rows)
    next(r for r in bad if r["run_tag"] == OWNER).update(extractor="human:张三")
    _refused(lambda: _run(bad, m), "extractor 应只有 human:owner", "owner 的行不是 human:owner")
    bad = copy.deepcopy(rows)
    next(r for r in bad if r["run_tag"] == OWNER).update(answer="拿不准")
    _refused(lambda: _run(bad, m), "不在闭集", "owner 的裁决是拿不准")
    _refused(lambda: _run(rows, m, owner_tag=TAG["B"]), "和模型的一趟重了", "owner 的 run_tag 和模型重名")
    _refused(lambda: _run(rows, m, bank_sha="deadbeef"), "不是这份题库的 sha", "--bank-sha 钉错")
    _refused(lambda: gm.load_secondary("primary"), "不合法", "--bank 给主题库")
    _refused(lambda: gm.load_secondary(str(fb.BANK_PATH)), "不合法", "--bank 给主题库路径")
    for specs, needle in ((list(gm.DEFAULT_RUNS[:2]), "正好是"),
                          ([gm.DEFAULT_RUNS[0], gm.DEFAULT_RUNS[0].replace("A=", "B="), gm.DEFAULT_RUNS[2]], "不能重复"),
                          (["A=primary@llm:x", gm.DEFAULT_RUNS[1], gm.DEFAULT_RUNS[2]], "不能用 run_tag"),
                          (["A=gate1-sonnet55@llm:x", gm.DEFAULT_RUNS[1], gm.DEFAULT_RUNS[2]], "fqr-"),
                          (["A=fqr-g1-a@jev:1.13.0", gm.DEFAULT_RUNS[1], gm.DEFAULT_RUNS[2]], "要写成")):
        _refused(lambda: gm.parse_runs(specs, BANK), needle, f"--run {specs}")
    print("  §3 拒算: 混抽取器 / 两个 sha / 主题库 sha / 旧版本 / 一格两行 / 缺格 / 名单外 / 没点名的 tag / 不在闭集 / 主题库的题 / "
          "owner 不是 human:owner 或裁拿不准 / owner tag 撞模型 / sha 钉错 / --bank 主题库 / 三趟不对 ✓")


# §4 判定 ──────────────────────────────────────────────────────────────────────────
def check_verdicts(td) -> None:
    m = _manifest(td)
    _, cells_no, res_no = _run(_rows(_answers()), m, owner_tag=None)
    # 没有 owner: A 对 B 已不过的题直接 fail (请读者讲经历 5/39 不一致), 其余 pending —— 不让 owner 白裁一道挂了的题
    assert res_no["invites_sharing"]["verdict"] == "fail", res_no["invites_sharing"]["why"]
    assert res_no["reader_ask_form"]["verdict"] == "pending" and "AR" not in res_no["reader_ask_form"]
    cells0, own = _owner_for(m)
    _, _, res = _run(_rows(_answers(), own), m)
    assert res["reader_ask_form"]["owner"]["spot_overturned"] == 1 and res["reader_ask_form"]["owner"]["spot_ruled"] == 20
    for q, r in res.items():
        assert r["verdict"] in ("pass", "fail", "kappa_undefined"), (q, r["verdict"], r["why"])
    # A 对 B 一致率: 请读者讲经历 5/39 不一致 → < 0.90 → fail (线是真按 0.90 判的)
    assert res["invites_sharing"]["AB"]["ok_agree"] is False and res["invites_sharing"]["verdict"] == "fail"
    # 推翻 3 格 → 这题不过 (哪怕别的线都过)
    _, _, res3 = _run(_rows(_answers(), _owner(cells0, overturn=3)), m)
    assert res3["reader_ask_form"]["owner"]["spot_overturned"] == 3 and res3["reader_ask_form"]["verdict"] == "fail"
    assert any("复核推翻 ≤ 2: 不过" in w for w in res3["reader_ask_form"]["why"])
    # 推翻按判定档数: 找同类 → 求推荐 (同在「其他问法」) 只算原始推翻, 不算判定档推翻
    own_in = dict(own)
    k_in = next((c["note_id"], c["question_id"]) for c in cells0 if c["kind"] == "spot" and c["A"] == "找同类"
                and own[(c["note_id"], c["question_id"])] == "找同类")
    own_in[k_in] = "求推荐"
    _, _, res_in = _run(_rows(_answers(), own_in), m)
    assert (res_in["reader_ask_form"]["owner"]["spot_overturned"], res_in["reader_ask_form"]["owner"]["spot_overturned_raw"]) == (1, 2)
    # 一致格凑不满 20 个复核 → pending, 不能降成「有几格裁几格」再判 pass (codex review on #238)
    assert res["reader_ask_form"]["verdict"] == "pass", res["reader_ask_form"]["why"]
    r10 = copy.deepcopy(res["reader_ask_form"])
    r10["owner"].update(spot=10, spot_ruled=10)
    v10, why10 = gm._verdict("reader_ask_form", r10, True)
    assert v10 == "pending" and any("凑不满 D-128 预注册的复核 20 格" in w for w in why10), (v10, why10)
    # 复核没裁完 → pending (不是 pass)
    own19 = dict(own)
    spot_keys = [(c["note_id"], c["question_id"]) for c in cells0 if c["kind"] == "spot" and c["question_id"] == "reader_ask_form"]
    own19.pop(spot_keys[0])
    _, _, res19 = _run(_rows(_answers(), own19), m)
    assert res19["reader_ask_form"]["verdict"] in ("pending", "fail"), res19["reader_ask_form"]["verdict"]
    assert any("复核只裁了 19 / 20" in w for w in res19["reader_ask_form"]["why"])
    # κ 没定义: 三趟、参考全是同一个值 → kappa_undefined, 不是 pass
    ans = _answers()
    for k in ans:
        ans[k] = {L: (("没问读者" if k[1] == "reader_ask_form" else "否"), None) for L in "ABH"}
    _, cells_u, _ = _run(_rows(ans), m, owner_tag=None)
    _, _, res_u = _run(_rows(ans, {(c["note_id"], c["question_id"]): c["A"] for c in cells_u if c["kind"] == "spot"}), m)
    assert res_u["reader_ask_form"]["verdict"] == "kappa_undefined", res_u["reader_ask_form"]["why"]
    # 不一致格没裁完 → pending, 不是 pass (rev: 只裁抽查页、不一致页空着 → 没裁的格掉出分母, 剩下全是参考 = A 的一致格)
    ans = _answers()
    for i, n in enumerate(NOTES[:9]):
        ans[(n, "reader_ask_form")] = {"A": ("挑一个", None), "B": ("挑一个", None), "H": ("求解答", None)}
    for n in NOTES[1:6]:
        ans[(n, "invites_sharing")] = {L: ("是", None) for L in "ABH"}
    _, cells_d, _ = _run(_rows(ans), m, owner_tag=None)
    dis_d = [(c["note_id"], c["question_id"]) for c in cells_d if c["kind"] == "disagree"]
    assert len(dis_d) == 9 and {k[1] for k in dis_d} == {"reader_ask_form"}, dis_d
    spot_ok = {(c["note_id"], c["question_id"]): c["A"] for c in cells_d if c["kind"] == "spot"}
    _, _, rs = _run(_rows(ans, spot_ok), m)
    r = rs["reader_ask_form"]
    assert r["owner"]["disagree_ruled"] == 0 and r["AR"]["ok_agree"] is True and r["verdict"] == "pending", (r["verdict"], r["why"])
    assert any("不一致格只裁了 0 / 9" in w for w in r["why"]) and any("A 对参考一致率 ≥ 0.85: 不作数" in w for w in r["why"])
    assert rs["invites_sharing"]["verdict"] in ("pass", "kappa_undefined"), rs["invites_sharing"]["why"]   # 那题没有不一致格
    _, _, rs8 = _run(_rows(ans, {**spot_ok, **{k: "求解答" for k in dis_d[:8]}}), m)            # 裁了 8 / 9, 还是 pending
    assert rs8["reader_ask_form"]["verdict"] == "pending" and any("只裁了 8 / 9" in w for w in rs8["reader_ask_form"]["why"])
    _, _, rs_all = _run(_rows(ans, {**spot_ok, **{k: "求解答" for k in dis_d}}), m)            # 全裁, A 全错 → fail
    assert rs_all["reader_ask_form"]["verdict"] == "fail" and rs_all["reader_ask_form"]["AR"]["agree"] < 0.85
    _, _, rs_ok = _run(_rows(ans, {**spot_ok, **{k: "挑一个" for k in dis_d}}), m)             # 全裁, A 全对 → 不再 pending
    assert rs_ok["reader_ask_form"]["verdict"] in ("pass", "kappa_undefined"), rs_ok["reader_ask_form"]["why"]
    # 没裁完也照样能判 fail 的: A–B 不过 (不看参考) / 复核推翻 3 (只增不减)
    own_no_inv = {k: v for k, v in own.items() if not (k[1] == "invites_sharing" and
                                                         next(c for c in cells0 if (c["note_id"], c["question_id"]) == k)["kind"] == "disagree")}
    _, _, rn = _run(_rows(_answers(), own_no_inv), m)
    assert rn["invites_sharing"]["verdict"] == "fail" and rn["invites_sharing"]["owner"]["disagree_ruled"] == 0, rn["invites_sharing"]["why"]
    own3 = _owner(cells0, overturn=3)
    own3.pop(next(k for k in own3 if k[1] == "reader_ask_form" and
                  next(c for c in cells0 if (c["note_id"], c["question_id"]) == k)["kind"] == "disagree"))
    _, _, r3p = _run(_rows(_answers(), own3), m)
    assert r3p["reader_ask_form"]["verdict"] == "fail" and r3p["reader_ask_form"]["owner"]["disagree_ruled"] == 8, r3p["reader_ask_form"]["why"]
    print("  §4 判定: 没 owner → pending; A–B 一致率 < 0.90 → fail; 复核推翻 3 → fail; 复核没裁完 → 不是 pass; κ 没定义 → kappa_undefined; "
          "不一致格没裁完 (0/9、8/9) → pending、对参考的线不作数, A–B 不过 / 推翻 3 照样 fail ✓")


# §5 哨兵: 证据原文不出现在任何输出里 ─────────────────────────────────────────────────
def check_sentinel(td) -> None:
    m = _manifest(td)
    cells0, own = _owner_for(m)
    rows = _rows(_answers(), own)
    assert all(SENTINEL in json.dumps(r, ensure_ascii=False) for r in rows if r["answer"])
    sql = gm.pivot_sql(BANK, RUNS)
    assert "evidence" not in sql.split("\n", 1)[1], "取数 SQL 选了 evidence 列"
    # MCP 导出的样子: {"result": "...<untrusted-data-x>\n[{\"pivot\": \"…\"}]\n</untrusted-data-x>..."}
    inner = json.dumps([{"pivot": json.dumps(rows, ensure_ascii=False)}], ensure_ascii=False)
    env = {"result": f"Below is …\n<untrusted-data-abc>\n{inner}\n</untrusted-data-abc>\n…"}
    src = td / "runs.json"
    src.write_text(json.dumps(env, ensure_ascii=False), encoding="utf-8")
    loaded = gm.load_rows(src)
    assert loaded and all(tuple(r) == gm.ROW_COLUMNS for r in loaded) and SENTINEL not in json.dumps(loaded, ensure_ascii=False)
    out, cells_out = td / "report.md", td / "cells.csv"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = gm.main(["--from-json", str(src), "--manifest", str(m), "--owner-run-tag", OWNER,
                      "--out", str(out), "--cells-out", str(cells_out)])
    assert rc == 0, buf.getvalue()
    for name, text in (("报告", out.read_text(encoding="utf-8")), ("格子表", cells_out.read_text(encoding="utf-8")),
                       ("stdout", buf.getvalue())):
        assert SENTINEL not in text, f"证据原文漏进了{name}"
    assert "evidence" not in out.read_text(encoding="utf-8").split("```sql", 1)[1].split("\n", 2)[2]
    # 拒算时退出 2 (不是崩)
    bad = td / "bad.json"
    bad.write_text(json.dumps([r for r in rows if r["run_tag"] != TAG["H"]], ensure_ascii=False), encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        assert gm.main(["--from-json", str(bad), "--manifest", str(m)]) == 2
        assert gm.main(["--print-sql"]) == 0
    print("  §5 哨兵证据串不在读进来的行 / 报告 / 格子表 / stdout 里; SQL 不选 evidence; MCP 导出能读; 拒算退出 2 ✓")


# §6 格子表 ───────────────────────────────────────────────────────────────────────
def check_cells(td) -> None:
    m = _manifest(td)
    _, cells_no, _ = _run(_rows(_answers()), m, owner_tag=None)
    cells0, own = _owner_for(m)
    _, cells, _ = _run(_rows(_answers(), own), m)
    spot = lambda cs: sorted(c["cell_id"] for c in cs if c["kind"] == "spot")  # noqa: E731
    assert spot(cells) == spot(cells_no), "抽查格跟着 owner 的裁决变了 —— 应只看模型的答案"
    # owner 在表外的一致格上也裁了一格 (不该有, 但有了也不能把它挪进抽查集): 抽查集不变, 计数单列
    extra = next(c for c in cells0 if c["kind"] == "agree" and c["question_id"] == "reader_ask_form")
    own2 = dict(own)
    own2[(extra["note_id"], extra["question_id"])] = extra["A"]
    own2.pop(next((c["note_id"], c["question_id"]) for c in cells if c["kind"] == "spot" and c["question_id"] == "reader_ask_form"))
    _, cells2, res2 = _run(_rows(_answers(), own2), m)
    assert spot(cells2) == spot(cells_no), "owner 多裁了一格, 抽查集就变了 —— 抽查格只能看模型的答案"
    assert res2["reader_ask_form"]["owner"]["agree_cells_ruled_outside_spot"] == 1
    for q in VER:
        assert sum(1 for c in cells if c["kind"] == "spot" and c["question_id"] == q) == gm.SPOT_N
    p = td / "cells_rt.csv"
    p.write_text(gm.cells_csv(cells), encoding="utf-8")
    back = gm.read_cells(p)
    assert [c["cell_id"] for c in back] == [c["cell_id"] for c in cells] and back[3]["A"] == cells[3]["A"]
    assert all(c["cell_id"] == f"{c['note_id']}:{c['question_id']}" for c in back)
    bad = gm.cells_csv(cells).replace(f"{NOTES[0]}:reader_ask_form,", f"{NOTES[1]}:reader_ask_form,", 1)
    p.write_text(bad, encoding="utf-8")
    _refused(lambda: gm.read_cells(p), "", "格子表 cell_id 和 note_id 对不上")
    print("  §6 格子表: 每题 20 个抽查格、只看模型答案 (有没有 owner 裁决都一样); 往返一致; 坏行拒 ✓")


# §7 合并 3 档和 yaml 对一遍 ─────────────────────────────────────────────────────────
def check_merge_consistency(td) -> None:
    raw = pathlib.Path(fb.BANKS["reader"]).read_text(encoding="utf-8")
    bad = raw.replace("      values: [挑一个, 说自己的]", "      values: [挑一个, 求推荐]", 1)
    assert bad != raw
    p = td / "bank_bad_merge.yaml"
    p.write_text(bad, encoding="utf-8")
    _refused(lambda: gm.load_secondary(str(p)), "3 档对不上", "yaml 的合并和 D-128 不一致")
    assert gm.level("reader_ask_form", "挑一个") == gm.level("reader_ask_form", "说自己的") == "可答"
    assert gm.level("reader_ask_form", "找同类") == "其他问法" and gm.level("invites_sharing", "是") == "是"
    print("  §7 合并 3 档只认 D-128 那一份, yaml 改了合并取值就拒 ✓")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        t = pathlib.Path(td)
        check_levels(t)
        check_evidence_rate(t)
        check_refusals(t)
        check_verdicts(t)
        check_sentinel(t)
        check_cells(t)
        check_merge_consistency(t)
    print("\ncheck_gate1_models: 7 节全过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
