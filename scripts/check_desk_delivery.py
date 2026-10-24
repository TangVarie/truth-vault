#!/usr/bin/env python3
"""
check_desk_delivery.py —— P4 已验证规律下发 (D-116; prompts/desk_delivery_v1.json + librarian/patterns.py) 的离线守卫。

  §1 批准层与闸二产物 / 冻结题库一致: 每个取值 validated、版本对得上、方向对 (any_of 是 OR>1、none_of 是 OR<1)、
     新发现 (hypothesis ?) 必须 owner 批准、题库原话来源逐字一致、aw_instruction=never 的永不下发、
     validated 的取值要么下发要么在 suppressed (不许静默漏掉)
  §2 命中: any_of 有就算; none_of 要 requires 都答过且一个都没有; 没答过不算「做到了」; skip_if 的卡不算
     (没露品牌的卡不是「品牌别硬插」的例子 —— requires 题里被压着的取值必须进 skip_if, §1 核)
  §3 下发开关: 探索臂 / 没闸二结论 / 批准层是旧一轮 → 不下发; 库里那一轮的行变了 (同标签重跑: 不再 validated /
     方向反了 / 题库版本变了 / 行没了) 或查不了 → 不下发; 对库结果进程内缓存 10 分钟, 查不了只记 30 秒
  §4 缓存版本: 规律版本、探索臂各自进版本串; 两样都没有时与以前完全一样
  §5 prompt: 规律段只在下发时出现、在卡前面; 卡面标命中
  §6 端到端 (打桩): 不带 explore 的老消费方不下发; 规律臂: 规律进 system、选中的卡带 validated_hits、响应带 patterns;
     探索臂什么都不带且缓存键不同;
     命中查询挂了照样选卡 (fail-open), 但这次结果不写缓存; 新策展还没抽特征的卡在 shortlist 里也不写缓存
     (老卡没答案照写)
  §7 HTTP 响应带 patterns 键; primary 答案重抽 (backfill-features reannotate) 之后清掉带规律的馆员缓存

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
        assert not f.get("skip_if") or f.get("none_of"), f"{p['id']}: skip_if 只给 none_of 用"
        # 「别这么写」的规律, requires 题剩下的取值都会被当成「做到了」: 其中被压着的取值不排掉, 就等于从后门下发
        # (品牌别硬插 × 未出现; codex review on #195)
        backdoor = {tuple(s["value"]) for s in D["suppressed"] if s["value"][0] in (f.get("requires") or [])}
        assert backdoor <= {tuple(v) for v in f.get("skip_if") or []}, f"{p['id']}: 压着的 {backdoor} 没进 skip_if"
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
        "d": {"asks_for_help": "否", "brand_first_position": "未出现"},   # 没露品牌 → 不是品牌位置的例子
        "e": {"brand_first_position": "后20%", "brand_in_title": "是"},
        "f": {"brand_first_position": "后20%"},
    }
    h = P.card_hits(ans, D)
    assert h == {"a": ["ending_asks_reader", "brand_placement"], "b": ["question_marks"], "f": ["brand_placement"]}, h
    print("  §2 命中: any_of / none_of / 没答过不算 / 没露品牌不算 ✓")


class _FV:
    """feature_validation 的假库: 只认 .schema().table().select().eq().limit().execute()。"""
    def __init__(self, rows):
        self.rows, self.calls = rows, 0

    def schema(self, s):
        return self

    def table(self, t):
        return self

    def select(self, *a):
        return self

    def eq(self, *a):
        return self

    def limit(self, *a):
        return self

    def execute(self):
        self.calls += 1
        if isinstance(self.rows, Exception):
            raise self.rows
        return type("R", (), {"data": self.rows})()


def s3_switch() -> None:
    assert P.active_delivery(D["gate2_run"], explore=True) is None
    assert P.active_delivery(None, explore=False) is None
    assert P.active_delivery("gate2-20990101", explore=False) is None
    assert P.active_delivery(D["gate2_run"], explore=False)["patterns"]

    rows = [r for r in json.loads((ROOT / "data-analysis" / f"feature-gate2-{D['gate2_run']}.rows.json")
                                  .read_text(encoding="utf-8")) if r["gate2_run"] == D["gate2_run"]]
    assert P.matches_db(rows, D), "批准时的那份结果本身要过"
    flip = lambda q, a, **kw: [dict(r, **kw) if (r["question_id"], r["answer"]) == (q, a) else r for r in rows]  # noqa: E731
    assert not P.matches_db(flip("ending_asks_reader", "是", status="no_signal"), D), "同标签重跑后不再 validated"
    assert not P.matches_db(flip("brand_in_title", "是", mh_odds_ratio=1.4), D), "「别这么写」那条方向反了"
    assert not P.matches_db(flip("asks_for_help", "是", bank_version="fq-v0.2"), D)
    assert not P.matches_db([r for r in rows if r["question_id"] != "body_question_marks"], D), "行没了"
    assert P.matches_db(flip("emoji_bucket", "0", status="no_signal"), D), "没下发的取值变了不影响"

    P._verified.clear()
    sb = _FV(rows)
    assert P.active_delivery(D["gate2_run"], explore=False, sb=sb)["patterns"]
    sb.rows = flip("ending_asks_reader", "是", status="reversed")
    assert P.active_delivery(D["gate2_run"], explore=False, sb=sb), "10 分钟内复用上一次的核对结果"
    assert sb.calls == 1
    assert not P.verified_against_db(sb, D, now=__import__("time").monotonic() + P.VERIFY_TTL_S + 1), "过期后重查"
    P._verified.clear()
    sb = _FV(RuntimeError("db down"))
    t0 = __import__("time").monotonic()
    assert P.verified_against_db(sb, D, now=t0) is False, "查不了 → 不下发"
    sb.rows = rows
    assert P.verified_against_db(sb, D, now=t0 + 10) is False and sb.calls == 1, "30 秒内不重查"
    assert P.verified_against_db(sb, D, now=t0 + P.VERIFY_RETRY_S + 1) is True, \
        "查不了只记 30 秒, 库一恢复就重新下发 —— 别让一次抖动把规律关掉 10 分钟 (codex review on #195)"
    P._verified.clear()
    print("  §3 下发开关: 探索臂 / 无结论 / 旧一轮 / 库里结果变了 / 查不了 都不下发 ✓")


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
    P.verified_against_db = lambda sb, d, **kw: True        # 对库那一步 §3 单测过; 这里只看它有没有被接上 (见下)
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

    dry = core.librarian_select({"consumer": "t", "project_id": "p3", "explore": False}, dry_run=True)
    assert dry["patterns"] == len(D["patterns"]) and "命中已验证规律: 结尾问读者" in dry["prompt"], \
        "dry-run 要给出生产冷路径真发的 prompt, 包括命中标记 (codex review on #195)"

    shelf = core.fetch_candidates
    core.fetch_candidates = lambda sb, **kw: []
    res = core.librarian_select_full({"consumer": "t", "project_id": "p4", "explore": False})
    assert res["selected"] == [] and [p["id"] for p in res["patterns"]] == [p["id"] for p in D["patterns"]], \
        "书架空了规律照样给 (codex review on #195)"
    core.fetch_candidates = shelf

    P.verified_against_db = lambda sb, d, **kw: False
    res = core.librarian_select_full({"consumer": "t", "project_id": "p5", "explore": False})
    assert res["patterns"] == [] and "已验证规律" not in seen["system"], "馆员下发前要对库 (active_delivery 带 sb)"
    P.verified_against_db = lambda sb, d, **kw: True

    from datetime import datetime, timezone
    fresh = datetime.now(timezone.utc).isoformat()
    core.fetch_candidates = lambda sb, **kw: [dict(CARD), dict(CARD, source_note_id="n9", curated_at=fresh)]
    n_writes = len(writes)
    core.librarian_select_full({"consumer": "t", "project_id": "p6", "explore": False})
    assert len(writes) == n_writes, "新策展、还没抽特征的卡在里面: 这份命中不完整, 不写缓存 (codex review on #195)"
    core.fetch_candidates = lambda sb, **kw: [dict(CARD), dict(CARD, source_note_id="n9")]
    core.librarian_select_full({"consumer": "t", "project_id": "p6", "explore": False})
    assert len(writes) == n_writes + 1, "老卡没答案是永远没有, 照写缓存"
    core.fetch_candidates = shelf

    def boom(sb, ids, d):
        raise RuntimeError("db down")
    P.fetch_answers = boom
    n_writes = len(writes)
    res = core.librarian_select_full({"consumer": "t", "project_id": "p2", "explore": False})
    assert res["status"] == "ok" and res["selected"][0]["validated_hits"] == [] and res["patterns"]
    assert len(writes) == n_writes, "命中没查成的选择不许写缓存, 否则库恢复了也一直命中它 (codex review on #195)"
    print("  §6 端到端: 老消费方不下发; 规律臂: 规律进 system、卡带命中、响应带 patterns; 探索臂全不带且另缓存; dry-run 带命中; 空书架照给规律; 下发前对库; 新卡没答完 / 命中查询挂了照样选、不写缓存 ✓")


class _Cache:
    def __init__(self, rows):
        self.rows, self.deleted = rows, []
        self._like = None
        self._del = False
        self._upd = None
        self._not_null = None

    def schema(self, s):
        return self

    def table(self, t):
        self._like, self._del, self._upd, self._not_null = None, False, None, None
        return self

    @property
    def not_(self):
        return _Not(self)

    def update(self, vals):
        self._upd = vals
        return self

    def select(self, *a, **k):
        return self

    def delete(self):
        self._del = True
        return self

    def limit(self, *a):
        return self

    def like(self, col, pat):
        import fnmatch
        self._like = fnmatch.translate(pat.replace("%", "*"))
        return self

    def execute(self):
        import re
        hit = [r for r in self.rows if re.match(self._like, r["library_version"])
               and (self._not_null is None or r.get(self._not_null) is not None)]
        if self._del:
            self.deleted += hit
            self.rows = [r for r in self.rows if r not in hit]
        if self._upd is not None:
            for r in hit:
                r.update(self._upd)
        return type("R", (), {"data": hit, "count": len(hit)})()


class _Not:
    def __init__(self, q):
        self.q = q

    def is_(self, col, val):
        assert val == "null"
        self.q._not_null = col
        return self.q


def s7_http() -> None:
    src = (ROOT / "librarian" / "app.py").read_text(encoding="utf-8")
    assert 'return {"selected": selected, "status": status, "patterns": patterns}' in src
    assert "librarian_select_full" in src

    import prune_librarian_cache as prune
    cards = [{"source_note_id": "x", "curated_at": "2026-10-01"}]
    with_dl = core.library_version(cards, gate2_run="g", delivery=P.delivery_digest(D))
    plain = core.library_version(cards, gate2_run="g")
    explore = core.library_version(cards, gate2_run="g", explore=True)
    sb = _Cache([{"library_version": v, "selected": [{"source_note_id": "x"}],
                  "last_hit_at": "2026-10-22T08:05:21"} for v in (with_dl, plain, explore)])
    prune.prune_delivery(sb)
    by = {r["library_version"]: r for r in sb.rows}
    assert not sb.deleted and len(sb.rows) == 3, "D-126: 只作废不删行 —— 借阅流量灯靠这张表的 last_hit_at 数借阅"
    assert by[with_dl]["selected"] is None and by[with_dl]["last_hit_at"], "带规律下发的那行: selected 清空, 借阅时间留着"
    assert by[plain]["selected"] and by[explore]["selected"], "只作废带规律下发的那几行, 老消费方 / 探索臂的不动"
    lib_src = (ROOT / "librarian" / "core.py").read_text(encoding="utf-8")
    assert 'return res[0].get("selected")' in lib_src and "if cached is not None:" in lib_src, \
        "馆员要把 selected 为 NULL 的行当没命中 (重挑后按 cache_key 覆盖), 作废才等于删"
    wf = (ROOT / ".github" / "workflows" / "backfill-features.yml").read_text(encoding="utf-8")
    step = wf[wf.index("清掉带规律命中的馆员缓存"):]
    step = step[:step.index("      - name:")]
    assert "python prune_librarian_cache.py --delivery-only" in step and "always()" in step
    assert "reannotate == 'true'" in step and "run_tag == 'primary'" in step
    print("  §7 HTTP 响应带 patterns; primary 答案重抽后作废带规律的馆员缓存 (selected 清空、行留着) ✓")


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
