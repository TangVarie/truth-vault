#!/usr/bin/env python3
"""
check_gate3.py —— 闸三第一轨 (D-118, scripts/gate3_score.py) 的离线守卫, CI 跑, 不连库。

  §1 冻结文件: 读得进、版本号和内容摘要对得上; 改一个权重就拒跑; 冻结 SQL 没被改过;
     文件名带版本号; 被替换的上一版留在目录里也读得进 (D-123 重冻: 同一 SQL、同一冻结日 / 判据 / 标注器, 只有数据变了)
  §2 token 与闸二 gate2_combo.tag_features 逐字同一套
  §3 打分 = 有权重的 token 的平均; 没见过的 token 跳过; 一个都没有 → 不打
  §4 分位: 低于最低 / 高于最高、并列段取中点、段内插值、单调
  §5 切点: 有项目切点用项目的, 没有用全库
  §6 计划: 冻结日前不打、没 essence 不打 (久了单独计)、打过的不重打 (幂等)、标注器对不上不打并计数
  §7 判定: 样本不够 = accumulating; 够了按「比值 ≤ 0.5 且单侧 p < 0.05」判 pass / fail
  §8 报告: 标注器对不上 → rc=1 并点名修在哪; 其余 rc=0
  §9 接线: daily-sync 有这一步、在 essence 之后策展之前、进失败聚合、靠哨兵判崩溃; CI 编译并跑本文件
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gate3_score as G  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def s1_frozen_file() -> dict:
    sc = G.load_scorer()
    assert sc["scorer_version"].startswith("essence-v1-") and len(sc["weights"]) == 47
    assert sc["freeze_publish_time"] == "2026-10-17T00:00:00"
    assert sc["frozen_annotator"] == {"essence_vocab_version": "v0.2", "essence_annotated_by": "claude-sonnet-5-5",
                                      "essence_annotation_mode": "prediction_feature"}
    assert all(len(v["q"]) == 101 and v["q"] == sorted(v["q"]) for v in sc["cutpoints"]["project"].values())
    assert len(sc["cutpoints"]["pooled"]["q"]) == 101
    bad = copy.deepcopy(sc)
    bad["weights"]["F:提问求助"] += 0.5
    tmp = ROOT / "data-analysis" / "gate3" / ".tampered.json"
    try:
        tmp.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        try:
            G.load_scorer(tmp)
            raise AssertionError("§1 改了权重还能读进来")
        except G.ScorerTampered:
            pass
    finally:
        tmp.unlink(missing_ok=True)
    sql = (ROOT / sc["meta"]["freeze_sql"]).read_bytes()
    assert hashlib.sha256(sql).hexdigest() == sc["meta"]["freeze_sql_sha256"], "§1 冻结 SQL 被改过, 和冻结文件对不上"
    # D-123: 打分器重冻过一次 (D-122 恢复了被冲掉的 F / U token)。当前文件名带版本号; 上一版留在目录里作历史, 也不许手改。
    assert G.SCORER_PATH.name == f"scorer-{sc['scorer_version']}.json", "§1 文件名要等于 scorer-<scorer_version>.json"
    hist = {}
    for f in sorted((ROOT / "data-analysis" / "gate3").glob("scorer-*.json")):
        h = G.load_scorer(f)                                           # 历史文件被手改也拒
        assert h["scorer_version"] not in hist, f"§1 两份冻结文件版本号相同: {h['scorer_version']}"
        hist[h["scorer_version"]] = h
    prev = hist.get(sc["meta"].get("supersedes"))
    assert prev is not None and prev["scorer_version"] != sc["scorer_version"], "§1 被替换的上一版要留在目录里"
    for k in ("scorer", "freeze_publish_time", "token_scheme", "frozen_annotator", "criteria"):
        assert prev[k] == sc[k], f"§1 重冻只换数据, {k} 不许跟着变 (要变就是另一回事: 新 D 号、闸三重新计时)"
    assert prev["meta"]["freeze_sql"] == sc["meta"]["freeze_sql"] and \
        prev["meta"]["freeze_sql_sha256"] == sc["meta"]["freeze_sql_sha256"], "§1 重冻要用同一份冻结 SQL"
    print("  §1 冻结文件: 版本摘要对得上、改权重拒跑、冻结 SQL 未改、上一版留档且只换了数据 ✓")
    return sc


def s2_tokens() -> None:
    import gate2_combo
    samples = [
        {"emotional_lever": "恐惧撬动", "content_format": "提问求助", "human_truth_archetype": ["健康焦虑", "健康焦虑", ""],
         "target_audience": ["通用", None]},
        {"emotional_lever": "", "content_format": None, "human_truth_archetype": None, "target_audience": []},
        {"emotional_lever": ["共鸣释放"], "content_format": "情感叙事", "human_truth_archetype": ("代际冲突",),
         "target_audience": "宝妈"},
    ]
    for n in samples:
        assert G.note_tokens(n) == gate2_combo.tag_features(n), (n, G.note_tokens(n), gate2_combo.tag_features(n))
    print("  §2 token 与闸二 tag_features 一致 ✓")


def s3_score(sc: dict) -> None:
    w = sc["weights"]
    t = {"L:恐惧撬动", "F:提问求助", "A:没见过的原型"}
    want = round((w["L:恐惧撬动"] + w["F:提问求助"]) / 2, 6)
    assert G.score_tokens(t, w) == want
    assert G.score_tokens({"A:没见过"}, w) is None and G.score_tokens(set(), w) is None
    print("  §3 打分 = 已知 token 权重平均, 未知跳过 ✓")


def s4_pct() -> None:
    q = [i / 100 for i in range(101)]
    assert G.pct_from_quantiles(-1, q) == 0.0 and G.pct_from_quantiles(2, q) == 1.0
    assert G.pct_from_quantiles(0.2, q) == 0.2 and G.pct_from_quantiles(0.205, q) == 0.205
    flat = [0.0] * 30 + [i / 100 for i in range(30, 101)]
    assert G.pct_from_quantiles(0.0, flat) == round(29 / 2 / 100, 6), "并列段取中点"
    xs = [x / 1000 for x in range(-50, 1050)]
    ps = [G.pct_from_quantiles(x, flat) for x in xs]
    assert all(a <= b + 1e-12 for a, b in zip(ps, ps[1:])), "分位要单调"
    print("  §4 分位: 边界 / 并列中点 / 插值 / 单调 ✓")


def s5_cut(sc: dict) -> None:
    q, kind = G.cutpoints_for("NUC_phase1", sc)
    assert kind == "project" and q == sc["cutpoints"]["project"]["NUC_phase1"]["q"]
    q, kind = G.cutpoints_for("NEW_phase9", sc)
    assert kind == "pooled" and q == sc["cutpoints"]["pooled"]["q"]
    print("  §5 切点: 有项目用项目、新项目用全库 ✓")


def _note(nid, pub="2026-10-20T10:00:00", **kw):
    n = {"note_id": nid, "project_id": "NUC_phase1", "publish_time": pub, "created_at": "2026-10-20T12:00:00",
         "emotional_lever": "恐惧撬动", "content_format": "提问求助", "human_truth_archetype": ["健康焦虑"],
         "target_audience": ["通用"], "essence_vocab_version": "v0.2", "essence_annotated_by": "claude-sonnet-5-5",
         "essence_annotation_mode": "prediction_feature"}
    n.update(kw)
    return n


def s6_plan(sc: dict) -> None:
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)
    notes = [
        _note("a"), _note("b", project_id="NEW_phase9"),
        _note("old", pub="2026-10-16T23:59:59"),
        _note("noess", emotional_lever=None, created_at="2026-10-20T00:00:00"),
        _note("fresh", emotional_lever="", created_at=(now - timedelta(hours=5)).isoformat()),
        _note("opus", essence_annotated_by="claude-opus-4-6"),
        _note("unk", emotional_lever="没见过", content_format="没见过", human_truth_archetype=[], target_audience=[]),
    ]
    res = G.plan(notes, set(), sc, now)
    got = {r["subject_id"]: r for r in res["rows"]}
    c = res["counts"]
    assert set(got) == {"a", "b"}, got.keys()
    assert got["a"]["cutpoints"] == "project" and got["b"]["cutpoints"] == "pooled"
    assert all(r["shadow"] is True and r["scorer_version"] == sc["scorer_version"] for r in res["rows"])
    assert c["after_freeze"] == 6 and c["no_essence"] == 2 and c["stale_essence"] == 1
    assert c["annotator_mismatch"] == 1 and res["mismatch"] == ["opus"] and c["unscorable"] == 1
    again = G.plan(notes, set(got), sc, now)
    assert not again["rows"] and again["counts"]["already"] == 2, "§6 打过的不重打"
    print("  §6 计划: 冻结前 / 没 essence / 打过 / 标注器不对 / 没 token 都不打, 幂等 ✓")


def s7_verdict(sc: dict) -> None:
    def rows(n, pos, pct):
        return [{"pct_in_project": pct, "y": 1 if i < pos else 0} for i in range(n)]
    v = G.verdict(rows(100, 1, 0.1) + rows(400, 30, 0.6), sc)
    assert v["status"] == "accumulating"
    v = G.verdict(rows(212, 2, 0.1) + rows(847, 60, 0.6), sc)
    assert v["status"] == "pass" and v["ratio"] < 0.5 and v["p"] < 0.05, v
    v = G.verdict(rows(212, 12, 0.1) + rows(847, 60, 0.6), sc)
    assert v["status"] == "fail" and v["ratio"] > 0.5, v
    v = G.verdict(rows(212, 1, 0.1) + rows(847, 9, 0.6), sc)
    assert v["status"] == "fail" and v["ratio"] <= 0.5 and v["p"] > 0.05, ("比值过线但 p 不显著也是 fail", v)
    assert G.verdict(rows(212, 0, 0.1) + rows(847, 0, 0.6), sc)["status"] == "fail", "全 0 判不出, 不算过"
    assert abs(G.one_sided_p(10, 100, 10, 100) - 0.5) < 1e-9
    print("  §7 判定: accumulating / pass / fail(比值) / fail(p) / 全 0 ✓")


def s7b_side_reads(sc: dict) -> None:
    """D-146 (外部评审 11-04 F08): 主判定一个字不改, 旁边并排报分层 MH / 分层精确 p / Fisher + mid-p / 各项目 2×2。
    反证: 把 side_reads 的分层换成一层 → 辛普森那条的 pass_read 变 clean, 红。"""
    def rows(n, pos, pct, proj):
        return [{"pct_in_project": pct, "y": 1 if i < pos else 0, "project_id": proj} for i in range(n)]
    # 精确检验对上手算: 品茶 2×2 [[3,1],[1,3]] 单侧 Fisher = 17/70; 一层时分层 p = Fisher
    p, midp = G.exact_lower_p([(1, 4, 3, 4)])
    assert abs(p - 17 / 70) < 1e-12 and abs(midp - (1 / 70 + 0.5 * 16 / 70)) < 1e-12, (p, midp)
    # 辛普森: 两个项目内最低档与其余爆率都相同, 只是最低档偏集中在少爆的项目 → 合并 pass, 分层不过
    v = G.verdict(rows(200, 2, 0.1, "A") + rows(100, 1, 0.6, "A") + rows(20, 2, 0.1, "B") + rows(800, 80, 0.6, "B"), sc)
    sd = v["side"]
    assert v["status"] == "pass" and v["ratio"] < 0.25 and v["p"] < 0.001, ("主判定照 D-118 不变", v)
    assert abs(sd["mh_ratio"] - 1.0) < 1e-9 and sd["p_strat"] > 0.4 and not sd["strat_ok"], sd
    assert v["pass_read"] == "depends_on_project_mix", v["pass_read"]
    a_, b_ = sd["per_project"]
    assert (a_["project_id"], a_["bottom_pos"], a_["bottom_n"], a_["rest_pos"], a_["rest_n"]) == ("A", 2, 200, 1, 100)
    assert abs(a_["bottom_share"] - 2 / 3) < 1e-9 and abs(b_["bottom_share"] - 20 / 820) < 1e-9, sd["per_project"]
    # 事件少: 0/212 vs 11/847 —— z 过 (p≈0.048), Fisher 不过 (≈0.0846), mid-p 过 (≈0.042, 只报不判)
    v = G.verdict(rows(212, 0, 0.1, "A") + rows(847, 11, 0.6, "A"), sc)
    sd = v["side"]
    assert v["status"] == "pass" and 0.04 < v["p"] < 0.05, v
    assert abs(sd["p_fisher"] - 0.0846) < 5e-4 and sd["midp_fisher"] < 0.05 and not sd["fisher_ok"], sd
    assert sd["strat_ok"] is False and v["pass_read"] == "depends_on_project_mix", (sd, v["pass_read"])
    # 干净的通过: 一个项目、事件够多 → 三样都过
    v = G.verdict(rows(212, 2, 0.1, "A") + rows(847, 60, 0.6, "A"), sc)
    assert v["status"] == "pass" and v["pass_read"] == "clean", (v["side"], v["pass_read"])
    # 没过主判定时不给 pass_read (并排读数不能把 fail 读成 pass)
    v = G.verdict(rows(212, 12, 0.1, "A") + rows(847, 60, 0.6, "B"), sc)
    assert v["status"] == "fail" and v["pass_read"] is None
    # 旧形状 (行里没有 project_id) 照跑: 归一层, 分层 = 合并
    v = G.verdict([{"pct_in_project": 0.1, "y": 0}] * 212 + [{"pct_in_project": 0.6, "y": 1}] * 60
                  + [{"pct_in_project": 0.6, "y": 0}] * 787, sc)
    assert v["side"]["per_project"][0]["project_id"] == "?" and v["side"]["p_strat"] == v["side"]["p_fisher"]
    # 报告里看得见; 取数带上 project_id
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        G.report(G.plan([], set(), sc, datetime(2026, 10, 25, tzinfo=timezone.utc)),
                 G.verdict(rows(200, 2, 0.1, "A") + rows(100, 1, 0.6, "A") + rows(20, 2, 0.1, "B") + rows(800, 80, 0.6, "B"), sc), sc)
    out = buf.getvalue()
    assert "并排 (D-146" in out and "分层 MH 比值 1.00" in out and "A: 最低档 2/200" in out and "取决于项目构成" in out, out
    src = (ROOT / "scripts/gate3_score.py").read_text(encoding="utf-8")
    assert '.select("subject_id, pct_in_project, project_id")' in src, "fetch_labeled 要带 project_id, 不然分不了层"
    print("  §7b 并排读数 (D-146): 品茶 Fisher 对上 · 辛普森 → 主判定 pass 但取决于项目构成 · 0/212 vs 11/847 Fisher 不过"
          " · 干净通过 · fail 不给 pass_read · 旧形状一层 · 报告与取数 ✓")


def s8_report(sc: dict) -> None:
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)
    v = G.verdict([], sc)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = G.report(G.plan([_note("a")], set(), sc, now), v, sc)
    assert rc == 0 and "还差最低档 212" in buf.getvalue(), buf.getvalue()
    assert "落档率" not in buf.getvalue(), "一篇标签都没有时不报落档率 (分母 0)"
    # 落档率 (D-137 第 7 条): 35 / 352 落在最低档 → 照这个率到 212 要约 2,133 篇有标签的笔记
    labeled = [{"pct_in_project": 0.1, "y": 0}] * 35 + [{"pct_in_project": 0.5, "y": 1 if i < 9 else 0} for i in range(317)]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        G.report(G.plan([_note("a")], set(), sc, now), G.verdict(labeled, sc), sc)
    assert "落档率: 最低档 35/352 = 9.9%" in buf.getvalue() and "约 2,133 篇" in buf.getvalue(), buf.getvalue()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = G.report(G.plan([_note("x", essence_annotated_by="claude-opus-4-6")], set(), sc, now), v, sc)
    assert rc == 1 and "修在 TV 仓" in buf.getvalue() and "重新计时" in buf.getvalue()
    print("  §8 报告: 标注器被换 → rc=1 且说清修在哪 ✓")


def s9_wiring() -> None:
    import yaml
    wf_text = (ROOT / ".github/workflows/daily-sync.yml").read_text(encoding="utf-8")
    steps = yaml.safe_load(wf_text)["jobs"]["sync"]["steps"]
    ids = [s.get("id") for s in steps]
    assert "gate3_score" in ids, "daily-sync 没有闸三打分这一步"
    st = steps[ids.index("gate3_score")]
    assert st.get("continue-on-error") is True and "gate3_score.py" in st["run"]
    assert ids.index("essence_sync") < ids.index("gate3_score") < ids.index("curate_sync"), "要在 essence 之后打分"
    sentinel = "GATE3_SCORE_CHECK_DONE" + " rc="          # 拼出来: 原文写在这里会被 check_system_map 当成又一盏灯
    assert sentinel in st["run"], "靠哨兵行判崩溃"
    assert G.SCORER_PATH.name in st["run"], "daily-sync 那一步的说明要写当前冻结文件 (重冻之后别还指着旧的)"
    agg = [s for s in steps if s.get("name", "").startswith("Fail job on any sync failure")][0]["run"]
    assert "gate3_score:" in agg, "没进失败聚合"
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "scripts/gate3_score.py" in ci and "python check_gate3.py" in ci
    src = (ROOT / "scripts/gate3_score.py").read_text(encoding="utf-8")
    assert 'print(f"' + sentinel + '{rc}")' in src
    print("  §9 接线: daily-sync 步骤位置 / 失败聚合 / 哨兵 / CI ✓")


def main() -> int:
    sc = s1_frozen_file()
    s2_tokens()
    s3_score(sc)
    s4_pct()
    s5_cut(sc)
    s6_plan(sc)
    s7_verdict(sc)
    s7b_side_reads(sc)
    s8_report(sc)
    s9_wiring()
    print("\ncheck_gate3: 9 节 + §7b 全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
