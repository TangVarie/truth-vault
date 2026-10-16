#!/usr/bin/env python3
"""
check_desk_delivery.py —— P4 已验证规律下发 (D-116; prompts/desk_delivery_v1.json + librarian/patterns.py) 的离线守卫。

  §1 批准层与闸二产物 / 冻结题库一致: 每个取值 validated、版本对得上、方向对 (any_of 是 OR>1、none_of 是 OR<1)、
     新发现 (hypothesis ?) 必须 owner 批准、题库原话来源逐字一致、aw_instruction=never 的永不下发、
     validated 的取值要么下发要么在 suppressed (不许静默漏掉)
  §2 命中: any_of 有就算; none_of 要 requires 都答过且一个都没有; 没答过不算「做到了」
  §3 下发开关: 探索臂 / 没闸二结论 / 批准层是旧一轮 → 不下发
  §4 缓存版本: 规律版本、探索臂各自进版本串; 两样都没有时与以前完全一样
  §5 prompt: 规律段只在下发时出现、在卡前面; 卡面标命中
  §6 端到端 (打桩): 不带 explore 的老消费方不下发; 规律臂: 规律进 system、选中的卡带 validated_hits、响应带 patterns;
     探索臂什么都不带且缓存键不同;
     命中查询挂了照样选卡 (fail-open)
  §7 HTTP 响应带 patterns 键

跑法: cd scripts && python check_desk_delivery.py
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from librarian import core, patterns as P  # noqa: E402
import feature_bank as fb  # noqa: E402

D = json.loads((ROOT / "prompts" / "desk_delivery_v1.json").read_text(encoding="utf-8"))


def s1_consistency() -> None:
    bank = fb.load_bank()
    assert D["bank_version"] == bank["bank_version"] and D["bank_sha256"] == bank["frozen_sha256"] == bank["_sha256"], \
        "批准层的题库版本 / 摘要对不上冻结题库"
    rows = json.loads((ROOT / "data-analysis" / f"feature-gate2-{D['gate2_run']}.rows.json").read_text(encoding="utf-8"))
    by = {(r["question_id"], r["answer"]): r for r in rows if r["gate2_run"] == D["gate2_run"]}
    qs = {**{q["id"]: q for q in bank.get("code_features") or []}, **fb.question_index(bank)}   # 代码特征题不在 question_index 里
    used: set = set()
    for p in D["patterns"]:
        f = p["follow"]
        assert bool(f.get("any_of")) != bool(f.get("none_of")), f"{p['id']}: any_of / none_of 二选一"
        assert set(f.get("requires") or []) <= {q for q, _ in f.get("none_of") or []}, f"{p['id']}: requires 只给 none_of 用"
        vals = [(tuple(v), +1) for v in f.get("any_of") or []] + [(tuple(v), -1) for v in f.get("none_of") or []]
        for (q, a), sign in vals:
            r = by.get((q, a))
            assert r and r["status"] == "validated", f"{p['id']}: {q}={a} 在 {D['gate2_run']} 里不是 validated"
            assert r["bank_version"] == D["bank_version"] and int(r["question_version"]) == int(qs[q]["version"]), f"{q} 版本对不上"
            assert (r["mh_odds_ratio"] > 1) == (sign > 0), f"{p['id']}: {q}={a} 方向反了 (OR {r['mh_odds_ratio']})"
            if r["hypothesis"] == "?":
                assert "owner" in p["source"], f"{p['id']}: {q}={a} 是新发现, 下发要 owner 批准 (G-02)"
            assert str(qs[q].get("aw_instruction") or "").strip().lower() != "never", f"{q} 是 aw_instruction=never, 永不下发"
            used.add((q, a))
        if p["source"] == "bank":
            (q, a), = [tuple(v) for v in f["any_of"]]
            assert p["instruction"] == qs[q]["aw_instruction"], f"{p['id']}: 说是题库原话, 但和题库不一致"
            assert (qs[q]["type"] == "bool" and a == "是") or a in (qs[q].get("aw_instruction_values") or []), p["id"]
    sup = {tuple(s["value"]) for s in D["suppressed"]}
    assert not (sup & used), f"既下发又压着: {sup & used}"
    validated = {k for k, r in by.items() if r["status"] == "validated"}
    assert validated == used | sup, f"闸二 validated 但批准层没表态: {validated - used - sup}; 多出来的: {(used | sup) - validated}"
    assert ("efficacy_promise", "是") in sup
    print(f"  §1 批准层 ↔ 闸二 {D['gate2_run']} ↔ 冻结题库: {len(D['patterns'])} 条下发、{len(sup)} 条压着, 全部表态 ✓")


def s2_hits() -> None:
    ans = {
        "a": {"ending_asks_reader": "是", "brand_first_position": "后20%", "brand_in_title": "否"},
        "b": {"body_question_marks": ">=2", "brand_first_position": "中间"},
        "c": {"brand_in_title": "否"},                                   # 位置没答过 → 品牌那条不算做到
        "d": {"asks_for_help": "否", "brand_first_position": "未出现"},
    }
    h = P.card_hits(ans, D)
    assert h == {"a": ["ending_asks_reader", "brand_placement"], "b": ["question_marks"], "d": ["brand_placement"]}, h
    print("  §2 命中: any_of / none_of / 没答过不算 ✓")


def s3_switch() -> None:
    assert P.active_delivery(D["gate2_run"], explore=True) is None
    assert P.active_delivery(None, explore=False) is None
    assert P.active_delivery("gate2-20990101", explore=False) is None
    assert P.active_delivery(D["gate2_run"], explore=False)["patterns"]
    print("  §3 下发开关: 探索臂 / 无结论 / 旧一轮都不下发 ✓")


def s4_version() -> None:
    cards = [{"source_note_id": "x", "curated_at": "2026-10-01"}]
    base = core.library_version(cards, gate2_run="g")
    assert core.library_version(cards, gate2_run="g", delivery=None, explore=False) == base
    dl = core.library_version(cards, gate2_run="g", delivery=P.delivery_digest(D))
    ex = core.library_version(cards, gate2_run="g", explore=True)
    assert len({base, dl, ex}) == 3
    D2 = json.loads(json.dumps(D))
    D2["patterns"][0]["instruction"] += "。"
    assert P.delivery_digest(D2) != P.delivery_digest(D), "改了一条规律, 规律版本得变"
    print("  §4 缓存版本: 规律 / 探索臂各自分开, 都没有时不变 ✓")


CARD = {"source_note_id": "n1", "tier": "爆", "brand": "B", "category": "c", "rank_score": 1.0,
        "curated_at": "2026-10-01", "is_curated": True, "hook_type": "h", "structure": "s",
        "why_it_worked": "w", "transferable_tactic": "t", "raw_excerpt": "e", "synthetic": False}


def s5_prompt() -> None:
    plain = core.build_system_blocks({}, [CARD])[0]["text"]
    assert "已验证规律" not in plain
    blk = core.build_system_blocks({}, [dict(CARD, validated_hits=["结尾问读者"])], D)[0]["text"]
    assert blk.startswith(core.ROLE_TASK_INSTR)
    assert blk.index("已验证规律") < blk.index("候选经验卡"), "规律段要在卡前面 (稳定前缀)"
    assert "命中已验证规律: 结尾问读者" in blk and D["patterns"][3]["instruction"] in blk
    print("  §5 prompt: 规律段只在下发时出现、在卡前、卡面标命中 ✓")


def s6_end_to_end() -> None:
    seen: dict = {}
    writes: list = []
    core.get_supabase = lambda *a, **k: object()
    core.latest_gate2_run = lambda sb: D["gate2_run"]
    core.fetch_candidates = lambda sb, **kw: [dict(CARD), dict(CARD, source_note_id="n2", rank_score=0.5)]
    core.get_cache = lambda sb, key: None
    core.put_cache = lambda sb, key, brief, lib_v, sel, **kw: writes.append((key, sel))
    P.fetch_answers = lambda sb, ids, d: {"n1": {"ending_asks_reader": "是"}}

    def llm(prompt, model, *, system=None, **kw):
        seen["system"] = "\n".join(b["text"] for b in system)
        return json.dumps({"selected": [{"source_note_id": "n1", "why_relevant": "r", "borrow_what": "结尾问读者"}]})
    core.call_anthropic = llm
    res = core.librarian_select_full({"consumer": "t", "project_id": "p"})
    assert res["patterns"] == [] and "已验证规律" not in seen["system"] and res["selected"][0]["validated_hits"] == [], \
        "不带 explore 的老消费方 (通道 1 / 旧版写作台) 不参与分臂、不下发规律"
    k_legacy = writes[-1][0]

    res = core.librarian_select_full({"consumer": "t", "project_id": "p", "explore": False})
    assert res["status"] == "ok" and [p["id"] for p in res["patterns"]] == [p["id"] for p in D["patterns"]]
    assert res["selected"][0]["validated_hits"] == ["结尾问读者"]
    assert "已验证规律" in seen["system"] and "命中已验证规律: 结尾问读者" in seen["system"]
    k_rules = writes[-1][0]

    res = core.librarian_select_full({"consumer": "t", "project_id": "p", "explore": True})
    assert res["patterns"] == [] and "已验证规律" not in seen["system"]
    assert res["selected"][0]["validated_hits"] == [] and writes[-1][0] not in (k_rules, k_legacy), "探索臂要另一份缓存"

    def boom(sb, ids, d):
        raise RuntimeError("db down")
    P.fetch_answers = boom
    res = core.librarian_select_full({"consumer": "t", "project_id": "p2", "explore": False})
    assert res["status"] == "ok" and res["selected"][0]["validated_hits"] == [] and res["patterns"]
    print("  §6 端到端: 老消费方不下发; 规律臂: 规律进 system、卡带命中、响应带 patterns; 探索臂全不带且另缓存; 命中查询挂了照样选 ✓")


def s7_http() -> None:
    src = (ROOT / "librarian" / "app.py").read_text(encoding="utf-8")
    assert 'return {"selected": selected, "status": status, "patterns": patterns}' in src
    assert "librarian_select_full" in src
    print("  §7 HTTP 响应带 patterns ✓")


def main() -> int:
    s1_consistency()
    s2_hits()
    s3_switch()
    s4_version()
    s5_prompt()
    s6_end_to_end()
    s7_http()
    print("\ncheck_desk_delivery: 7 节全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
