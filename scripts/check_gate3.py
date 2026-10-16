#!/usr/bin/env python3
"""
check_gate3.py —— 闸三第一轨 (D-118, scripts/gate3_score.py) 的离线守卫, CI 跑, 不连库。

  §1 冻结文件: 读得进、版本号和内容摘要对得上; 改一个权重就拒跑; 冻结 SQL 没被改过
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
    print("  §1 冻结文件: 版本摘要对得上、改权重拒跑、冻结 SQL 未改 ✓")
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


def s8_report(sc: dict) -> None:
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)
    v = G.verdict([], sc)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = G.report(G.plan([_note("a")], set(), sc, now), v, sc)
    assert rc == 0 and "还差最低档 212" in buf.getvalue(), buf.getvalue()
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
    s8_report(sc)
    s9_wiring()
    print("\ncheck_gate3: 9 节全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
