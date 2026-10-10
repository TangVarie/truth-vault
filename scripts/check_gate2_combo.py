"""
check_gate2_combo.py —— gate2_combo.py (闸二后半: 组合进不进 L2, docs/28 附录 B.3 / B.4) 的自检。全部合成数据, 不连库。

  §1 中位秩 AUC = 两两比较计数 (含并列记 0.5)
  §2 留一项目: 只在本项目出现的特征没有外部证据, 不进本项目的分
  §3 有真信号 (一道原子题 7:3) → 合并 > 只 essence ≥ 0.02、自助下界 > 0、最低 20% 不更差、置换均值落在 0.47–0.53 → 进
  §4 全是噪声 → 不进 (①或②不过), 置换均值仍在带内
  §5 评估集: 只有代码特征 (LLM 没答) / LLM 只写了一半的篇剔掉 (NULL 答案行算答过); 占位题 / 闸一 fail / --unreliable
     的题不进特征; 快照 (笔记, 题) 重复 → 拒跑
  §6 最低 20% 的算法 (手算, 含加权); 同种子结果逐位相同
  §7 CLI: 真题库 (frozen) + fixture 能跑出报告; sha 对不上退出码 2; --unreliable 传得进去
  §8 逆抽样权重: 权重 = 全量 / 评估集 (按项目、标签); 加权计数 = 把篇按权重复制后的不加权计数; 一篇没抽到的格列出来
  §9 自助 / 置换沿用原始样本定下的项目集合与权重 (正例 5 篇的项目在某次抽样里不足 5 也不掉)
  §10 爆款集锦 (TGV / TUGE) 不进最低 20%

反证 (每条都该让本脚本红): ① AUC 并列不取中位秩; ② 留一项目时把本项目也算进权重 (泄漏 → §2 红, §4 噪声也会"进");
③ 评估集不剔只有部分抽取器答过 / 没答全的篇; ④ 闸一 fail 的题进了特征; ⑤ 置换时打乱的是跨项目的标签;
⑥ 留一项目计数不乘逆抽样权重; ⑦ 自助时项目集合按每次抽样重选; ⑧ 最低 20% 混进爆款集锦。

跑法: cd scripts && python check_gate2_combo.py
"""
from __future__ import annotations

import contextlib
import io
import json
import random
import tempfile

import feature_bank as fb
import gate2_combo as C
import gate2_run as G

REAL = fb.load_bank()
SHA = REAL["_sha256"][:12]
FULL_SHA = REAL["_sha256"]
EXT = ["code:v1", "llm:claude-sonnet-5-5"]
FAIL_Q = sorted(G.gate1_unreliable(REAL))[0]
PASS_Q = "title_is_question"
PLACEBO_Q = (REAL.get("placebo") or [{"id": "placebo_rand_1"}])[0]["id"]
CODE_Q = C.expected_questions(REAL, EXT[0])
LLM_Q = C.expected_questions(REAL, EXT[1])


def _ans(note_id, qid, value, extractor="llm:claude-sonnet-5-5", sha=FULL_SHA):
    return {"subject_type": "note", "subject_id": note_id, "question_id": qid, "question_version": 1,
            "bank_sha256": sha, "extractor": extractor, "answer": value, "run_tag": "primary"}


def _full(nid, given: dict, skip=()) -> list[dict]:
    """一篇的完整快照: given = {题: 答案}, 题按归属记在 code:v1 / LLM 名下; 其余该答的题记 NULL 行 (答过、没答出)。"""
    out = []
    for ext, qs in ((EXT[0], CODE_Q), (EXT[1], LLM_Q)):
        out += [_ans(nid, q, given.get(q), extractor=ext) for q in sorted(qs) if q not in skip]
    return out


def _note(rng, nid, proj, y):
    return {"note_id": nid, "project_id": proj, "y": y, "has_essence": True, "body_len": 300,
            "emotional_lever": rng.choice(["焦虑", "好奇", "共鸣", "爽"]),
            "content_format": rng.choice(["图文", "清单", "故事"]),
            "human_truth_archetype": rng.sample(["a", "b", "c", "d", "e"], rng.choice([1, 2])),
            "target_audience": [rng.choice(["学生", "白领", "宝妈"])]}


def _dataset(signal: float, *, projects=5, pos=40, neg=160, seed=7, extra=None, names=None, keep=None):
    """signal = 强题在正例里答「是」的比例 (负例 1 − signal); 0.5 = 没有信号。essence 四列与标签独立。
    keep(project, y, i) → False 的篇在全量里、但快照里没有 (模拟抽样)。"""
    rng = random.Random(seed)
    notes, given = [], {}
    for p in range(projects):
        proj = names[p] if names else f"P{p}"
        for i in range(pos + neg):
            y = 1 if i < pos else 0
            nid = f"{proj}_n{i:03d}"
            notes.append(_note(rng, nid, proj, y))
            strong = rng.random() < (signal if y else 1 - signal)
            g = {PASS_Q: "是" if strong else "否"}
            for q in ("own_experience", "has_direct_quote", "asks_for_help", "title_has_digit"):
                g[q] = rng.choice(["是", "否"])
            if keep is None or keep(proj, y, i):
                given[nid] = g
    raw: list[dict] = []
    if extra:
        extra(notes, given, raw, rng)
    answers = [a for nid, g in given.items() for a in _full(nid, g)] + raw
    return {"notes": notes, "answers": answers}


def _brute_auc(s, y):
    pos = [a for a, b in zip(s, y) if b]
    neg = [a for a, b in zip(s, y) if not b]
    tot = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return tot / (len(pos) * len(neg))


def check_auc() -> None:
    rng = random.Random(1)
    for _ in range(50):
        n = rng.randrange(5, 40)
        s = [rng.choice([0.1, 0.2, 0.2, 0.3, 0.5, 0.9]) for _ in range(n)]
        y = [rng.choice([0, 1]) for _ in range(n)]
        if 0 < sum(y) < n:
            assert abs(C.auc_midrank(s, y) - _brute_auc(s, y)) < 1e-12, (s, y)
    assert C.auc_midrank([1, 2], [1, 1]) is None
    print("  §1 中位秩 AUC = 两两比较 (并列 0.5), 50 组随机含并列 ✓")


def check_lopo() -> None:
    notes = [{"note_id": "a", "project_id": "P0", "y": 1, "feats": {"tag": {"X"}, "q": {"Only0"}, "both": {"X", "Only0"}}},
             {"note_id": "b", "project_id": "P0", "y": 0, "feats": {"tag": {"X"}, "q": {"Only0"}, "both": {"X", "Only0"}}},
             {"note_id": "c", "project_id": "P1", "y": 1, "feats": {"tag": {"X"}, "q": {"Z"}, "both": {"X", "Z"}}},
             {"note_id": "d", "project_id": "P1", "y": 1, "feats": {"tag": {"X"}, "q": {"Z"}, "both": {"X", "Z"}}}]
    ys = [n["y"] for n in notes]
    q = C.lopo_scores(notes, ys, "q")
    assert q[0] is None and q[1] is None, f"§2 只在 P0 出现的特征不该给 P0 打分 (泄漏): {q}"
    t = C.lopo_scores(notes, ys, "tag")
    import math
    assert abs(t[0] - math.log((2 + 1) / (0 + 1))) < 1e-12, t   # P0 的分只看 P1: X 2 爆 0 趴
    assert abs(t[2] - math.log((1 + 1) / (1 + 1))) < 1e-12, t   # P1 的分只看 P0: X 1 爆 1 趴
    print("  §2 留一项目: 本项目的笔记不进本项目的权重; 只在本项目出现的特征不打分 ✓")


def check_signal_enters() -> None:
    ds = _dataset(0.72)
    notes, meta = C.build_eval(ds, REAL, sha=SHA, extractors=EXT)
    res = C.run_combo(notes, boot=300, perms=10)
    assert res["gain"] >= C.AUC_GAIN, res["auc"]
    assert res["boot"]["ci_low"] > 0, res["boot"]
    assert res["criteria"]["bottom20"], res["bottom"]
    assert C.PERM_BAND[0] <= res["perm_mean"] <= C.PERM_BAND[1] and res["perm_max"] < res["auc"]["both"], (res["perm_mean"], res["perm_max"])
    assert res["enter_l2"], res["criteria"]
    print(f"  §3 有真信号: tag {res['auc']['tag']:.3f} / q {res['auc']['q']:.3f} / both {res['auc']['both']:.3f}, "
          f"自助下界 {res['boot']['ci_low']:.3f}, 置换均值 {res['perm_mean']:.3f} → 进 ✓")


def check_noise_stays_out() -> None:
    ds = _dataset(0.5, seed=11)
    notes, _ = C.build_eval(ds, REAL, sha=SHA, extractors=EXT)
    res = C.run_combo(notes, boot=300, perms=10)
    assert not res["enter_l2"], res["criteria"]
    assert not (res["criteria"]["auc_gain"] and res["criteria"]["boot_ci"]), (res["gain"], res["boot"])
    assert C.PERM_BAND[0] - 0.03 <= res["perm_mean"] <= C.PERM_BAND[1] + 0.03, res["perm_mean"]
    print(f"  §4 全噪声: both − tag = {res['gain']:+.3f}, 区间 [{res['boot']['ci_low']:.3f}, {res['boot']['ci_high']:.3f}] → 不进 ✓")


def check_eval_set() -> None:
    def extra(notes, given, raw, rng):
        # 1) 一篇只有代码特征 (LLM 没答): 评估集要剔掉
        notes.append(dict(_note(rng, "CODEONLY", "P0", 1)))
        raw.extend(a for a in _full("CODEONLY", {"title_has_digit": "是"}) if a["extractor"] == "code:v1")
        # 2) 一篇 LLM 只写了一半 (少一道题的行): 也剔掉 —— 只看"每个抽取器都有行"不够 (codex review on #174)
        notes.append(dict(_note(rng, "HALF", "P0", 1)))
        raw.extend(_full("HALF", {PASS_Q: "是", "own_experience": "是"}, skip={"asks_for_help"}))
        # 3) 占位题 + 闸一 fail 的题: 不进特征
        for n in notes[:50]:
            given[n["note_id"]][PLACEBO_Q] = "是"
            given[n["note_id"]][FAIL_Q] = "是" if n["y"] else "否"
    ds = _dataset(0.6, extra=extra)
    notes, meta = C.build_eval(ds, REAL, sha=SHA, extractors=EXT)
    ids = {n["note_id"] for n in notes}
    assert "CODEONLY" not in ids and "HALF" not in ids and meta["dropped_partial_extractors"] == 2, meta
    assert len(notes) == 1000, f"§5 NULL 答案行也算答过, 1000 篇完整的都该在: {len(notes)}"
    feats = set().union(*(n["feats"]["q"] for n in notes))
    assert not any(f.startswith(f"Q:{PLACEBO_Q}=") for f in feats), "§5 占位题进了特征"
    assert not any(f.startswith(f"Q:{FAIL_Q}=") for f in feats), "§5 闸一 fail 的题进了特征"
    assert not any("=None" in f for f in feats), "§5 NULL 答案进了特征"
    notes2, _ = C.build_eval(ds, REAL, sha=SHA, extractors=EXT, include_unreliable=True)
    assert any(f.startswith(f"Q:{FAIL_Q}=") for n in notes2 for f in n["feats"]["q"]), "§5 --include-unreliable 应当放进来"
    notes3, meta3 = C.build_eval(ds, REAL, sha=SHA, extractors=EXT, unreliable={PASS_Q})
    assert PASS_Q in meta3["excluded_questions"] and not any(
        f.startswith(f"Q:{PASS_Q}=") for n in notes3 for f in n["feats"]["q"]), "§5 --unreliable 传入的题进了特征"
    dup = _dataset(0.6)
    dup["answers"].append(_ans("P0_n000", PASS_Q, "否", extractor="code:v1"))
    try:
        C.build_eval(dup, REAL, sha=SHA, extractors=EXT)
    except G.Gate2Refused as exc:
        assert "不唯一" in str(exc)
    else:
        raise AssertionError("§5 快照 (笔记, 题) 重复必须拒跑")
    print(f"  §5 评估集: 只有部分抽取器答过的剔掉 ({meta['dropped_partial_extractors']}); 占位题 / 闸一 fail ({FAIL_Q}) 不进特征; 快照重复拒跑 ✓")


def check_bottom_and_determinism() -> None:
    by = {"P0": ([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0], [1, 0, 0, 0, 0, 1, 1, 0, 1, 1]),
          "P1": ([0.5, 0.4, 0.3, 0.2, 0.1], [0, 0, 0, 0, 1])}
    r = C.bottom_quintile_rate(by)
    # P0 最低 2 篇 (0.1, 0.2): 爆 1; P1 最低 1 篇 (0.1): 爆 1 → 3 篇爆 2
    assert r["bottom_n"] == 3 and abs(r["bottom_rate"] - 2 / 3) < 1e-12, r
    assert r["rest_n"] == 12 and abs(r["rest_rate"] - 4 / 12) < 1e-12, r
    # 加权: 总权重 8, 20% = 1.6; 第一篇 (权重 1) 进, 第二篇 (权重 3) 中点 2.5 > 1.6 不进 → 低档爆率 1/1, 其余 1/7
    rw = C.bottom_quintile_rate({"P0": ([0.1, 0.2, 0.3, 0.4], [1, 0, 0, 1], [1.0, 3.0, 3.0, 1.0])})
    assert rw["bottom_n"] == 1 and abs(rw["bottom_rate"] - 1.0) < 1e-12 and abs(rw["rest_rate"] - 1 / 7) < 1e-12, rw
    ds = _dataset(0.65, seed=3)
    notes, _ = C.build_eval(ds, REAL, sha=SHA, extractors=EXT)
    a = C.run_combo(notes, boot=100, perms=4, seed=5)
    b = C.run_combo(notes, boot=100, perms=4, seed=5)
    assert a["auc"] == b["auc"] and a["boot"] == b["boot"] and a["perm"] == b["perm"], "§6 同种子结果必须逐位相同"
    # 置换只在项目内换: 每个项目的正例数不变, 但确实换了 (项目爆率差很大的数据上, 跨项目打乱会改每个项目的正例数)
    skew = [{"note_id": f"S{i}", "project_id": "HI" if i < 50 else "LO", "y": int(i < 40 or 50 <= i < 52)} for i in range(150)]
    for k in range(5):
        yk = C.permute_within_project(skew, 100 + k)
        for proj in ("HI", "LO"):
            idx = [i for i, n in enumerate(skew) if n["project_id"] == proj]
            assert sum(yk[i] for i in idx) == sum(skew[i]["y"] for i in idx), f"§6 置换改了 {proj} 的正例数 (跨项目打乱)"
        assert yk != [n["y"] for n in skew], "§6 置换没换"
    print("  §6 最低 20% 手算对上; 同种子逐位相同; 置换只在项目内 (每项目正例数不变) ✓")


def check_cli() -> None:
    ds = _dataset(0.7, seed=9)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(ds, f, ensure_ascii=False)
        fx = f.name
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = C.main(["--sha", SHA, "--extractors", ",".join(EXT), "--fixture", fx, "--boot", "100", "--perms", "4"])
    assert rc == 0, (rc, err.getvalue()[-300:])
    assert "进不进 L2" in out.getvalue() and "置换反证" in out.getvalue(), out.getvalue()[:300]
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err2 := io.StringIO()):
        rc = C.main(["--sha", "deadbeefdead", "--extractors", ",".join(EXT), "--fixture", fx])
    assert rc == 2 and "对不上" in err2.getvalue(), (rc, err2.getvalue())
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as jf:
        jpath = jf.name
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        rc = C.main(["--sha", SHA, "--extractors", ",".join(EXT), "--fixture", fx, "--boot", "20", "--perms", "2",
                     "--unreliable", f" {PASS_Q} ,", "--json-out", jpath])
    got = json.load(open(jpath, encoding="utf-8"))
    assert rc == 0 and PASS_Q in got["meta"]["excluded_questions"], (rc, got["meta"]["excluded_questions"])
    print("  §7 CLI: 真题库 (frozen) + fixture 出报告; sha 对不上退出码 2; --unreliable 进了排除集 ✓")


def check_sampling_weights() -> None:
    # P0: 正例全抽、负例只抽每 4 篇里的 1 篇 → 权重 爆 1 / 趴 4; P1: 全量; P2: 正例一篇没抽到 → 列出来
    keep = lambda proj, y, i: (proj != "P0" or y == 1 or i % 4 == 0) and (proj != "P2" or y == 0)  # noqa: E731
    ds = _dataset(0.65, projects=3, pos=20, neg=80, seed=21, keep=keep)
    notes, meta = C.build_eval(ds, REAL, sha=SHA, extractors=EXT)
    s0 = meta["sampling"]["P0"]
    assert (s0["census_pos"], s0["census_neg"], s0["eval_pos"], s0["eval_neg"]) == (20, 80, 20, 20), s0
    w0 = {n["wt"] for n in notes if n["project_id"] == "P0"}
    assert w0 == {(4.0, 1.0)}, f"§8 P0 的权重应当是 (趴 4, 爆 1): {w0}"
    assert {n["wt"] for n in notes if n["project_id"] == "P1"} == {(1.0, 1.0)}
    assert meta["unrepresented"] == [{"project_id": "P2", "label": "爆", "census": 20}], meta["unrepresented"]
    # 加权计数 = 复制: 把 P0 的每篇负例复制 4 份、权重记 1, 其余篇的分必须一模一样
    rep_notes = []
    for n in notes:
        k = 4 if (n["project_id"] == "P0" and n["y"] == 0) else 1
        rep_notes += [dict(n, wt=(1.0, 1.0)) for _ in range(k)]
    first = {}
    for i, n in enumerate(rep_notes):
        first.setdefault(n["note_id"], i)
    for v in C.VARIANTS:
        a = C.lopo_scores(notes, [n["y"] for n in notes], v)
        b = C.lopo_scores(rep_notes, [n["y"] for n in rep_notes], v)
        for i, n in enumerate(notes):
            x, z = a[i], b[first[n["note_id"]]]
            assert (x is None and z is None) or abs(x - z) < 1e-9, f"§8 {v} {n['note_id']}: 加权 {x} ≠ 复制 {z}"
    print("  §8 逆抽样权重: P0 (趴 4, 爆 1); 加权计数 = 按权重复制; 一篇没抽到的格 (P2 爆) 列出 ✓")


def check_fixed_eligibility() -> None:
    by = {"P0": ([0.1, 0.9, 0.8, 0.2, 0.3], [0, 1, 1, 1, 0], [1.0] * 5)}
    assert C.weighted_auc(by)[0] is None, "§9 不给 eligible 时正例 3 < 5 应当不算"
    a, per = C.weighted_auc(by, {"P0": 5.0})
    assert per == {"P0": (C.auc_midrank(by["P0"][0], by["P0"][1]), 5.0)}, per
    # run_combo 里每一次 weighted_auc 都用同一组 eligible (真实 / 自助 / 置换)
    ds = _dataset(0.7, projects=4, pos=5, neg=60, seed=4)
    notes, meta = C.build_eval(ds, REAL, sha=SHA, extractors=EXT)
    calls, orig = [], C.weighted_auc

    def spy(by_proj, eligible=None):
        calls.append(eligible)
        return orig(by_proj, eligible)
    C.weighted_auc = spy
    try:
        res = C.run_combo(notes, boot=50, perms=3, census_pos=meta["census_pos"])
    finally:
        C.weighted_auc = orig
    assert calls and all(c is not None and c == calls[0] for c in calls), "§9 自助 / 置换里项目集合跟着抽样变了"
    assert set(res["eligible"]) == {"P0", "P1", "P2", "P3"} and res["boot"]["n"] == 50, (res["eligible"], res["boot"])
    print(f"  §9 正例 5 篇的 4 个项目: {len(calls)} 次加权 AUC 全用同一组项目与权重; 自助 50 次一次不少 ✓")


def check_curated_out_of_bottom() -> None:
    names = ["P0", "P1", "P2", "TUGE_phase1"]
    ds = _dataset(0.65, projects=4, pos=20, neg=80, seed=13, names=names)
    notes, meta = C.build_eval(ds, REAL, sha=SHA, extractors=EXT)
    res = C.run_combo(notes, boot=20, perms=2, census_pos=meta["census_pos"])
    non_cur = sum(1 for n in notes if n["project_id"] not in C.CURATED_PROJECTS)
    for v in C.VARIANTS:
        b = res["bottom"][v]
        assert b["bottom_n"] + b["rest_n"] == non_cur, f"§10 {v}: 最低 20% 混进了爆款集锦 ({b['bottom_n'] + b['rest_n']} ≠ {non_cur})"
    assert "TUGE_phase1" in res["per_project"]["tag"], "§10 集锦只出最低 20%, 加权 AUC 照常 (附录 B.3)"
    print("  §10 TUGE_phase1 不进最低 20%, 加权 AUC 照算 ✓")


def main() -> int:
    check_auc()
    check_lopo()
    check_signal_enters()
    check_noise_stays_out()
    check_eval_set()
    check_bottom_and_determinism()
    check_cli()
    check_sampling_weights()
    check_fixed_eligibility()
    check_curated_out_of_bottom()
    print("\ncheck_gate2_combo: 10 节全过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
