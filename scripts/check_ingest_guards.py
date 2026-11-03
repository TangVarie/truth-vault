#!/usr/bin/env python3
"""采集三道新闸 (2026-10-08 架构审计 A-06 / B-13 / B-14, D-091): 未来 publish_time 夹掉 ·
状态格清空写回默认 + 状态值没映上打旗 · 整批 tier 翻转在 upsert 之前挡住。

断行为不断源码 (D-051): §1 / §2b 真的走 transform_row; §2 / §3 / §4 走纯函数; §5 打桩 fetch_all_pages
核分批; §6 / §7 只核接线 (旗标与 workflow 输入存在、调用顺序在 upsert 之前) —— 这两条是形态守卫,
挡的是"闸写了没接上"。

反证 (改坏之后必须变红, 每条在 D-091 里记了实跑结果):
  ① _is_future_publish_time 恒 False                 → §1 未来日期照样入库, 红
  ② apply_cleared_status 不看 seen_cols              → §2 「列改名不动」那条红
  ③ plan_tier_flip 只数升不数降                      → §3 降档用例红
  ④ 阈值去掉 max(MIN, …) 只按比例                    → §3 小项目用例红
  ⑤ apply_tier_flip_block 把没翻的篇也剥掉 tier      → §4 红
  ⑥ _current_tiers 不分批                            → §5 单次 in_ 超 100, 红
  ⑦ --allow-mass-tier-flip 不读 ALLOW_MASS_TIER_FLIP → §6 红

跑法: cd scripts && python check_ingest_guards.py
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sync_feishu_notes_to_truth_vault as engine

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime.now(timezone.utc)

RULES = [{"match_contains": ["大爆"], "tier": "大爆"},
         {"match_contains": ["爆贴"], "tier": "爆"},
         {"match_contains": ["无水花"], "tier": "趴"}]
MAPPING = {
    "project_id": "T_phase1", "platform": "xiaohongshu",
    "field_mapping": {"标题": "title", "正文": "raw_content", "发布时间": "publish_time",
                      "流量状态": "_status_raw"},
    "tier_extraction": {"source": "状态字段", "rules": RULES},
}


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _row(**fields) -> dict:
    base = {"标题": "t", "正文": "正文正文正文正文正文正文正文正文正文正文"}
    base.update(fields)
    return base


def _note(fields: dict) -> dict:
    note, _metric, _und = engine.transform_row(MAPPING, "rec1", fields)
    return note


# ── §1 未来 publish_time ───────────────────────────────────────────────────────
def check_future_publish_time() -> None:
    fut = _note(_row(**{"发布时间": _ms(NOW + timedelta(days=3)), "流量状态": "爆贴"}))
    assert fut["publish_time"] is None, "§1 未来 3 天的 publish_time 该置空"
    assert fut["raw_extra"]["_publish_time_raw"][:4] == str((NOW + timedelta(days=3)).year), "§1 原值要留在 raw_extra"
    assert fut["data_quality_flags"]["publish_time_future"], "§1 要打旗子"
    assert fut["tier"] == "爆", "§1 夹 publish_time 不该动 tier"

    past = _note(_row(**{"发布时间": _ms(NOW - timedelta(days=1)), "流量状态": "爆贴"}))
    assert isinstance(past["publish_time"], str) and "publish_time_future" not in (past.get("data_quality_flags") or {}), \
        "§1 昨天的日期不能被夹"
    soon = _note(_row(**{"发布时间": _ms(NOW + timedelta(hours=23)), "流量状态": "爆贴"}))
    assert isinstance(soon["publish_time"], str), "§1 24 小时内的「未来」(时区 / 当天) 不夹"
    assert engine._is_future_publish_time("not a date") is False, "§1 认不出的格式不算未来"
    assert engine._is_future_publish_time((NOW + timedelta(days=2)).isoformat(timespec="seconds")) is True
    print("  §1 未来 publish_time: 置空 + 原值留 raw_extra + 旗子; 昨天 / 23h 内不动 ✓")


# ── §2 状态格清空 → 默认档 ─────────────────────────────────────────────────────
def check_cleared_status() -> None:
    def notes():
        return [{"note_id": "a"},
                {"note_id": "b", "tier": "爆", "tier_source": "状态字段"},
                {"note_id": "c", "tier": "大爆", "tier_source": "数值推断"}]

    ns = notes()
    assert engine.apply_cleared_status(MAPPING, ns, {"流量状态", "标题"}) == 1
    assert ns[0]["tier"] is None and ns[0]["tier_source"] is None and ns[0]["data_quality_flags"]["tier_cleared"] is True, \
        "§2 状态列还在、这篇没格 → tier 显式 NULL(规则无 default)"
    assert ns[1]["tier"] == "爆" and ns[2]["tier"] == "大爆" and ns[2]["tier_source"] == "数值推断", "§2 有 tier 的不动"

    ns = notes()
    assert engine.apply_cleared_status(MAPPING, ns, {"标题", "正文"}) == 0 and "tier" not in ns[0], \
        "§2 状态列本轮一行都没出现(改名 / 整列空) → 不动, 交给核心列消失闸"

    with_default = dict(MAPPING, tier_extraction={"source": "状态字段", "rules": RULES + [{"default": "趴"}]})
    ns = notes()
    assert engine.apply_cleared_status(with_default, ns, {"流量状态"}) == 1 and ns[0]["tier"] == "趴", "§2 规则有 default 就写 default"

    note_family = dict(MAPPING, field_mapping={"标题": "title", "备注": "_note_for_tier"},
                       tier_extraction={"source": "备注字段", "rules": RULES})
    ns = notes()
    assert engine.apply_cleared_status(note_family, ns, {"备注"}) == 1, "§2 备注字段那一族按 _note_for_tier 的源列判"
    assert engine.apply_cleared_status(note_family, notes(), {"流量状态"}) == 0, "§2 备注族看的不是状态列"
    print("  §2 状态格清空: 列还在才写默认; 列改名不动; 有 tier 的不动; 两族源列各判各的 ✓")


def check_unmapped_status_flag() -> None:
    n = _note(_row(**{"流量状态": "已发布"}))
    assert n["tier"] is None and n["tier_source"] == "状态字段", "§2b 没映上的状态值 tier 仍是 NULL(不改取值)"
    assert n["data_quality_flags"]["tier_unmapped"] == "已发布", "§2b 但要把原值打成旗子"
    ok = _note(_row(**{"流量状态": "爆贴"}))
    assert "tier_unmapped" not in (ok.get("data_quality_flags") or {}), "§2b 映上的不打旗"
    absent = _note(_row())
    assert "tier" not in absent, "§2b 格根本不在 → transform_row 不写 tier(由 apply_cleared_status 接手)"
    print("  §2b 状态值没映上: tier NULL + tier_unmapped 旗子; 映上 / 缺格不打 ✓")


# ── §3 翻转计划 ────────────────────────────────────────────────────────────────
def _pending(ids, tier):
    return [{"note_id": i, "tier": tier, "tier_source": "状态字段"} for i in ids]


def check_flip_plan() -> None:
    cur100 = {f"n{i}": "趴" for i in range(100)}
    p = engine.plan_tier_flip(_pending([f"n{i}" for i in range(20)], "爆"), cur100)
    assert p["existing"] == 20 and p["threshold"] == 15 and len(p["upgrades"]) == 20 and p["blocked"], \
        "§3 100 篇存量里 20 篇升爆 > max(15, 10%) → 挡"
    p = engine.plan_tier_flip(_pending([f"n{i}" for i in range(12)], "爆"), cur100)
    assert not p["blocked"] and len(p["upgrades"]) == 12, "§3 12 篇 ≤ 15 → 放"

    # 存量按 payload 里库里已有的篇数算: 整表同步时 = 项目存量
    full = _pending([f"n{i}" for i in range(100)], "趴")
    for n in full[:16]:
        n["tier"] = "爆"
    p = engine.plan_tier_flip(full, cur100)
    assert p["existing"] == 100 and p["threshold"] == 15 and p["blocked"], "§3 整表 100 篇、16 篇升 → 挡"
    big = {f"n{i}": "趴" for i in range(300)}
    fullbig = _pending([f"n{i}" for i in range(300)], "趴")
    for n in fullbig[:20]:
        n["tier"] = "爆"
    p = engine.plan_tier_flip(fullbig, big)
    assert p["threshold"] == 30 and not p["blocked"], "§3 300 篇存量阈值 30, 20 篇升 → 放"

    down = engine.plan_tier_flip(_pending([f"n{i}" for i in range(20)], "趴"), {f"n{i}": "爆" for i in range(100)})
    assert len(down["downgrades"]) == 20 and down["blocked"], "§3 降档同样算翻转(整批撤回同样要人确认)"

    same = engine.plan_tier_flip(_pending([f"n{i}" for i in range(50)], "大爆"), {f"n{i}": "爆" for i in range(100)})
    assert not same["flips"], "§3 正例内部换档(爆 → 大爆)不算翻转"
    same2 = engine.plan_tier_flip(_pending([f"n{i}" for i in range(50)], "评估中"), cur100)
    assert not same2["flips"], "§3 非正例内部换档(趴 → 评估中)不算"

    new = engine.plan_tier_flip(_pending([f"x{i}" for i in range(50)], "爆"), cur100)
    assert new["existing"] == 0 and not new["flips"] and not new["blocked"], "§3 库里没有的新篇不算(首次同步不会被挡)"
    notier = engine.plan_tier_flip([{"note_id": f"n{i}"} for i in range(50)], cur100)
    assert not notier["flips"], "§3 payload 不带 tier 的篇不算"

    nulls = engine.plan_tier_flip(_pending([f"n{i}" for i in range(20)], "参考"), {f"n{i}": None for i in range(100)})
    assert len(nulls["upgrades"]) == 20, "§3 库里 NULL → 参考 也是升(参考进通道 1)"

    small = {f"n{i}": "趴" for i in range(20)}
    assert engine.plan_tier_flip(_pending([f"n{i}" for i in range(16)], "爆"), small)["blocked"], "§3 小项目 16 > max(15, 2) → 挡"
    assert not engine.plan_tier_flip(_pending([f"n{i}" for i in range(15)], "爆"), small)["blocked"], "§3 15 = 阈值, 不超过 → 放"

    allowed = engine.plan_tier_flip(_pending([f"n{i}" for i in range(20)], "爆"), cur100, allow=True)
    assert not allowed["blocked"] and len(allowed["flips"]) == 20, "§3 放行开关: 不挡, 但翻转照数(日志里看得见)"
    assert allowed["current"]["n0"] == "趴", "§3 计划里带库里原值, 旗子要用"
    print("  §3 翻转计划: 升/降都算, 内部换档 / 新篇 / 无 tier 不算, 阈值 max(15, 10% 存量), 放行只关挡不关数 ✓")


# ── §4 挡 = 只剥翻转篇的 tier ─────────────────────────────────────────────────
def check_flip_block() -> None:
    cur = {f"n{i}": "趴" for i in range(100)}
    pend = _pending([f"n{i}" for i in range(20)], "爆") + _pending([f"n{i}" for i in range(20, 25)], "趴")
    pend[0]["raw_content"] = "正文"
    plan = engine.plan_tier_flip(pend, cur)
    assert plan["blocked"]
    assert engine.apply_tier_flip_block(pend, plan) == 20
    for n in pend[:20]:
        assert "tier" not in n and "tier_source" not in n, "§4 被挡的篇 payload 里不能有 tier(upsert 保留库值)"
        assert n["data_quality_flags"]["tier_flip_blocked"] == {"from": "趴", "to": "爆"}, "§4 旗子记本想写成什么"
    assert pend[0]["raw_content"] == "正文", "§4 内容照写"
    for n in pend[20:]:
        assert n["tier"] == "趴" and "data_quality_flags" not in n, "§4 没翻的篇一个字都不动"
    print("  §4 挡: 只剥翻转篇的 tier/tier_source, 内容 / 其它篇不动 ✓")


# ── §5 读库分批 ────────────────────────────────────────────────────────────────
class _Q:
    def __init__(self, rec):
        self.rec, self.ids = rec, None

    def schema(self, *_):
        return self

    def table(self, *_):
        return self

    def select(self, *_):
        return self

    def eq(self, *_):
        return self

    def in_(self, _col, ids):
        self.ids = list(ids)
        self.rec.append(self.ids)
        return self


def check_current_tiers_batched() -> None:
    calls: list[list[str]] = []
    client = _Q(calls)
    tiers = {f"n{i:03d}": ("爆" if i % 7 == 0 else "趴") for i in range(250)}
    saved = engine.fetch_all_pages
    engine.fetch_all_pages = lambda q, page_size=1000, order_by=None: [{"note_id": i, "tier": tiers[i]} for i in q.ids if i in tiers]
    try:
        got = engine._current_tiers(client, "T_phase1", list(tiers) + ["ghost"])
    finally:
        engine.fetch_all_pages = saved
    assert got == tiers, "§5 读回的 tier 要和库里一样, 不在库里的不出现"
    assert len(calls) == 3 and all(len(c) <= 100 for c in calls), f"§5 251 个 id 要分 3 批、每批 ≤ 100: {[len(c) for c in calls]}"

    def boom(*a, **k):
        raise RuntimeError("库挂了")
    engine.fetch_all_pages = boom
    try:
        assert engine._current_tiers(_Q([]), "T_phase1", ["n1"]) is None, "§5 读不到 → None(调用方记错、不挡)"
    finally:
        engine.fetch_all_pages = saved
    print("  §5 读库: 按 100 分批, 读不到回 None ✓")


# ── §6 / §7 接线 ─────────────────────────────────────────────────────────────
def check_wiring() -> None:
    src = Path(engine.__file__).read_text(encoding="utf-8")
    assert re.search(r'add_argument\("--allow-mass-tier-flip"', src), "§6 CLI 开关要在"
    assert 'os.environ.get("ALLOW_MASS_TIER_FLIP"' in src, "§6 开关要读 ALLOW_MASS_TIER_FLIP 环境变量(workflow 两条路都能放行)"
    yml = (ROOT / ".github" / "workflows" / "daily-sync.yml").read_text(encoding="utf-8")
    assert "allow_mass_tier_flip:" in yml and "--allow-mass-tier-flip" in yml, "§6 workflow_dispatch 要有放行输入并传给脚本"
    assert "schedule" in yml and "定时跑永远不放行" in yml, "§6 定时跑不能放行"

    body = src[src.index("def main("):]
    i_clear = body.index("apply_cleared_status(mapping, pending_notes, seen_cols)")
    i_plan = body.index("plan_tier_flip(pending_notes, current_tiers")
    i_block = body.index("apply_tier_flip_block(pending_notes, flip)")
    i_upsert = body.index("upsert_notes_batch(sb, pending_notes")
    i_stamp = body.index('n["last_seen_run_id"] = run_id')
    assert i_stamp < i_clear < i_plan < i_block < i_upsert, "§7 三道闸都要在盖戳之后、upsert 之前, 顺序 清空 → 计划 → 挡"
    assert 'stats["errors"] += 1' in body[i_block:i_upsert], "§7 挡住要红(errors+1), 不能只告警"
    print("  §6 开关三条路(CLI / env / workflow 输入)都在, 定时跑不放行; §7 调用顺序在 upsert 之前且挡住要红 ✓")


# ── §8 抖音行沿用以前已继承成功的正文 (2026-10-16, D-052 续) ─────────────────────────
class _Chain:
    """supabase 查询链的桩: 每一步都返回自己, 记下 not_.is_ 的列。"""
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def step(*args, **kwargs):
            self.calls.append((name, args))
            return self
        return step

    @property
    def not_(self):
        self.calls.append(("not_", ()))
        return self


def check_reuse_previous_inheritance() -> None:
    restore = {"方向": "_direction_raw"}
    stored = {"raw_content": "库里那份正文", "from": "recPREV",
              "raw_extra": {"_direction_raw": "提问贴", "_content_inherited_from": "recPREV"}}
    out, meta = engine.reuse_previous_inheritance({"方向": "抖音", "笔记内容": ""}, stored, "笔记内容", restore)
    assert out["笔记内容"] == "库里那份正文" and meta["reused"] is True and meta["from"] == "recPREV", "§8 有库里那份就沿用"
    assert out["方向"] == "提问贴" and meta["overrides"] == {"方向": "抖音"}, \
        "§8 also_inherit 的列复原成当初继承到的, 这行自己的「抖音」记进 overrides"
    half = {"raw_content": "x", "from": "r", "raw_extra": {"_content_inherited_from": "r"}}
    assert engine.reuse_previous_inheritance({"方向": "抖音"}, half, "笔记内容", restore)[1] is None, \
        "§8 方向复原不了 → 不沿用(半套继承会把形态/人群/痛点冲成 null, codex review on #193)"
    assert engine.reuse_previous_inheritance({}, stored, "笔记内容", {"方向": None})[1] is None, \
        "§8 also_inherit 落普通列(复原不了)→ 不沿用"
    same, none = engine.reuse_previous_inheritance({"笔记内容": ""}, None, "笔记内容", restore)
    assert none is None and same == {"笔记内容": ""}, "§8 库里没有就不沿用(照常隔离)"
    assert engine.reuse_previous_inheritance({}, {"raw_content": ""}, "笔记内容")[1] is None, "§8 库里正文为空不算"
    assert set(engine._REUSABLE_INHERIT_REASONS) == {"inherit_prev_row_is_same_kind", "inherit_parent_not_found"}, \
        "§8 只对「上一行判不了」放行, 其它理由照旧隔离"

    # 端到端: 真 SPX mapping, 沿用后 transform 拆出来的跟一次成功继承的一样
    spx = engine.load_mapping("SPX_phase1")
    keys = engine.inherit_restore_keys(spx["content_inherit_from_previous_row"], spx["field_mapping"])
    assert keys == {"方向": "_direction_raw"}, f"§8 SPX 的 also_inherit 应能复原: {keys}"
    row = {"方向": "抖音", "笔记内容": "", "素人编号": "S1"}
    parent = {"方向": "提问贴", "笔记内容": "【标题】跑完反胃？【正文】第三十公里那口胶", "素人编号": "S0"}
    inherited, _m, why = engine.inherit_content_from_previous_row(
        dict(row), parent, "recP", spx["content_inherit_from_previous_row"], "笔记内容")
    assert why is None
    first, _, _ = engine.transform_row(spx, "recD", inherited)
    db = {"raw_content": first["raw_content"], "from": "recP", "raw_extra": first["raw_extra"]}
    reused, _ = engine.reuse_previous_inheritance(dict(row), db, "笔记内容", keys)
    again, _, _ = engine.transform_row(spx, "recD", reused)
    for col in ("raw_content", "content_format", "target_audience", "user_pain_point"):
        assert again.get(col) is not None and again.get(col) == first.get(col), f"§8 沿用后 {col} 要跟当初一样"

    saved = engine.fetch_all_pages
    try:
        rows = [{"note_id": "P_recA", "raw_content": "a", "content_format": "x",
                 "raw_extra": {"_content_inherited_from": "recP", "_inherited_overrides": {"方向": "抖音"}}},
                {"note_id": "P_recB", "raw_content": "", "raw_extra": {"_content_inherited_from": "recQ"}},
                {"note_id": "OTHER_recC", "raw_content": "c", "raw_extra": {"_content_inherited_from": "recR"}}]
        chain = _Chain()
        engine.fetch_all_pages = lambda qb, order_by: rows
        got = engine.fetch_previous_inheritance(type("C", (), {"schema": lambda self, _s: chain})(), "P")
        assert set(got) == {"recA"} and got["recA"]["from"] == "recP", "§8 只收本项目、正文非空、真继承过的"
        assert ("not_", ()) in chain.calls, "§8 只查带 _content_inherited_from 的 note"

        def boom(qb, order_by):
            raise RuntimeError("db down")
        engine.fetch_all_pages = boom
        assert engine.fetch_previous_inheritance(type("C", (), {"schema": lambda self, _s: _Chain()})(), "P") == {}, \
            "§8 读不到库 → 不放宽"
    finally:
        engine.fetch_all_pages = saved

    src = Path(engine.__file__).read_text(encoding="utf-8")
    body = src[src.index("def main("):]
    i_reuse = body.index("reuse_previous_inheritance(")
    i_quar = body.index("reason=inh_reason)")
    assert i_reuse < i_quar, "§8 先试沿用, 沿用不了才隔离"
    assert "if (inherit_spec and content_col and not args.dry_run) else {}" in body, "§8 dry-run 不读库"
    assert "content_col, inherit_restore)" in body, "§8 主循环沿用时要带上 also_inherit 的复原表"
    print("  §8 抖音行: 以前继承成功的沿用库里那份(方向一并复原, 形态/人群/痛点不丢), 其它照旧隔离, 读不到库不放宽 ✓")



# ── §9 有链接、缺正文的行: 父记录子行接父行正文 / 正文被清空的老笔记留库里那份 (2026-11-03, D-144) ─────────
_BODY = "【标题】藻油到底怎么挑【正文】颗粒小、没腥味, 早饭后一粒"


def _bjs_row(rid: str, *, body: str | None = None, url: str | None = None, parent: str | None = None,
             kol: str = "LX02", table: str = "tblBJS") -> dict:
    f: dict = {"素人编号": kol, "发布时间": 1793635200000, "流量状态": ["观察中"], "实时数据.评论数": 3}
    if body is not None:
        f["笔记内容"] = body
    if url is not None:
        f["反馈链接"] = {"link": url, "text": url}
    if parent is not None:
        f["父记录"] = [{"type": "text", "table_id": table, "text_arr": ["1091"], "record_ids": [parent], "text": "1091"}]
    return {"record_id": rid, "fields": f}


class _StoredQ:
    """supabase 查询链的桩: schema/table/select/eq/limit/execute 读 note_id → 库里那篇; 其余查询走 fetch_all_pages 桩。"""
    def __init__(self, notes: dict, raise_on: set = frozenset()):
        self.notes, self.raise_on, self.asked_ids, self._id = notes, raise_on, [], None

    def schema(self, *a): return self
    def table(self, *a): return self
    def select(self, *a, **k): return self
    def or_(self, *a, **k): return self
    def limit(self, *a, **k): return self

    def eq(self, col, val):
        if col == "note_id":
            self._id = val
        return self

    def in_(self, col, vals):
        self.asked = list(vals)
        return self

    def execute(self):
        nid, self._id = self._id, None
        self.asked_ids.append(nid)
        if nid in self.raise_on:
            raise RuntimeError("db down")
        row = self.notes.get(nid)
        return type("R", (), {"data": [row] if row else []})()


def check_missing_body_recovery() -> None:
    pid = engine.parent_record_id
    assert pid(_bjs_row("c", url="u", parent="recP")["fields"]) == "recP", "§9 父记录格 → 父行 record_id"
    assert pid(_bjs_row("c", url="u", parent="recP")["fields"], {"tblBJS"}) == "recP"
    assert pid(_bjs_row("c", url="u", parent="recP", table="tblOTHER")["fields"], {"tblBJS"}) is None, \
        "§9 父记录指到这个项目以外的表 → 不接"
    assert pid({"父记录": [{"type": "text", "table_id": "tblBJS", "text_arr": []}]}) is None, "§9 空占位行的父记录格 → None"
    assert pid({"父记录": [{"record_ids": ["a", "b"]}]}) is None and pid({}) is None, "§9 指了两条 / 没这一列 → None"

    m = engine.load_mapping("BJS_phase2")
    common = dict(project_id="BJS_phase2", content_col="笔记内容", title_col=None, url_col="反馈链接",
                  allowed_tables={"tblBJS"})

    def never(_nid):
        raise AssertionError("§9 这种行不该读库")

    parent = _bjs_row("recP", body=_BODY, url="https://xhslink.cn/o/P", kol="1091")
    child = _bjs_row("recC", url="https://xhslink.cn/o/C", parent="recP")
    out, meta = engine.recover_missing_body(child["fields"], record_id="recC", pulled={"recP": parent["fields"]},
                                            stored=never, **common)
    assert out["笔记内容"] == _BODY and meta == {"route": "parent", "from": "recP", "source": "feishu",
                                                "filled": ["笔记内容"]}, f"§9 子行接这一轮飞书里的父行: {meta}"
    assert "笔记内容" not in child["fields"], "§9 不能改调用方手里的原始行"

    db = {"BJS_phase2_recP": {"raw_content": "库里父行正文", "title": None, "publish_url": "https://xhslink.cn/o/P"}}
    out, meta = engine.recover_missing_body(child["fields"], record_id="recC",
                                            pulled={"recP": _bjs_row("recP", url="https://xhslink.cn/o/P")["fields"]},
                                            stored=db.get, **common)
    assert out["笔记内容"] == "库里父行正文" and meta["source"] == "db", "§9 父行这一轮没正文 → 接库里父行那篇"
    out, meta = engine.recover_missing_body(child["fields"], record_id="recC", pulled={}, stored=db.get, **common)
    assert meta and meta["source"] == "db", "§9 父行这一轮没拉到 → 接库里父行那篇"

    same = _bjs_row("recS", url="https://xhslink.cn/o/P", parent="recP")
    out, meta = engine.recover_missing_body(same["fields"], record_id="recS", pulled={"recP": parent["fields"]},
                                            stored=lambda _n: None, **common)
    assert meta is None and "笔记内容" not in out, "§9 子行和父行同一个链接(同一篇登记两次)→ 不接, 照旧隔离"

    kept_db = {"BJS_phase2_recK": {"raw_content": "库里这篇正文", "title": None, "publish_url": "https://xhslink.cn/o/K"}}
    cleared = _bjs_row("recK", url="https://xhslink.cn/o/K")
    out, meta = engine.recover_missing_body(cleared["fields"], record_id="recK", pulled={}, stored=kept_db.get, **common)
    assert out["笔记内容"] == "库里这篇正文" and meta == {"route": "kept", "filled": ["笔记内容"]}, \
        "§9 已入库的笔记飞书正文空了 → 正文留库里那份"
    assert engine.recover_missing_body(cleared["fields"], record_id="recK", pulled={}, stored=lambda _n: None,
                                       **common)[1] is None, "§9 库里也没有 → 补不上(照旧隔离)"
    orphan = _bjs_row("recO", url="https://xhslink.cn/o/O", parent="recGONE")
    assert engine.recover_missing_body(orphan["fields"], record_id="recO", pulled={}, stored=lambda _n: None,
                                       **common)[1] is None, "§9 父行哪儿都找不到、自己也不在库里 → 补不上"

    placeholder = {"父记录": [{"type": "text", "table_id": "tblBJS", "text_arr": []}]}
    assert engine.recover_missing_body(placeholder, record_id="recE", pulled={}, stored=never, **common)[1] is None, \
        "§9 空占位行(没链接)不碰、不读库"
    linked_no_url = _bjs_row("recN", parent="recP")["fields"]
    assert engine.recover_missing_body(linked_no_url, record_id="recN", pulled={"recP": parent["fields"]},
                                       stored=never, **common)[1] is None, \
        "§9 有父记录但没反馈链接(评论碎片之类)→ 不接: 判「本该是笔记」只看反馈链接(D-052)"
    assert engine.recover_missing_body(parent["fields"], record_id="recP", pulled={}, stored=never, **common)[1] is None, \
        "§9 自己有正文 → 不碰"

    titled = {"标题": "title", "正文": "raw_content", "链接": "publish_url"}
    t_out, t_meta = engine.recover_missing_body(
        {"链接": "https://x/k"}, record_id="r", project_id="T", content_col="正文", title_col="标题", url_col="链接",
        pulled={}, stored={"T_r": {"raw_content": "库里正文", "title": "库里标题"}}.get)
    assert t_out == {"链接": "https://x/k", "正文": "库里正文", "标题": "库里标题"} and t_meta["filled"] == ["正文", "标题"], \
        f"§9 有标题列的表: 标题也空就一并补 {titled}"
    t_out, _ = engine.recover_missing_body(
        {"链接": "https://x/k", "标题": "飞书里的新标题"}, record_id="r", project_id="T", content_col="正文",
        title_col="标题", url_col="链接", pulled={}, stored={"T_r": {"raw_content": "库里正文", "title": "旧"}}.get)
    assert t_out["标题"] == "飞书里的新标题", "§9 飞书里标题还在 → 不拿库里的旧标题盖"

    # transform 之后: 子行自己的链接 / 素人 / 指标, 父行的正文, 双留痕
    out, meta = engine.recover_missing_body(child["fields"], record_id="recC", pulled={"recP": parent["fields"]},
                                            stored=never, **common)
    note, metric, _ = engine.transform_row(m, "recC", out)
    engine.mark_recovered_body(note, meta)
    assert note["raw_content"] == _BODY and note["publish_url"] == "https://xhslink.cn/o/C" and note["account_id"] == "LX02"
    assert note["data_quality_flags"]["content_inherited"] is True
    assert note["raw_extra"]["_content_from_parent"] == {"record_id": "recP", "source": "feishu", "filled": ["笔记内容"]}
    assert "_content_inherited_from" not in note["raw_extra"], "§9 不占 D-052 的键(它的「沿用」要读)"
    kn = {"note_id": "x"}
    engine.mark_recovered_body(kn, {"route": "kept", "filled": ["笔记内容"]})
    assert kn["data_quality_flags"] == {"content_cleared_in_feishu": True} and kn["raw_extra"]["_content_kept_from_db"]

    q = _StoredQ({"N_a": {"raw_content": "a", "title": None, "publish_url": "u"}, "N_e": {"raw_content": ""}}, {"N_x"})
    assert engine.fetch_stored_body(q, "N_a")["raw_content"] == "a"
    assert engine.fetch_stored_body(q, "N_e") is None and engine.fetch_stored_body(q, "N_missing") is None
    assert engine.fetch_stored_body(q, "N_x") is None, "§9 读不到库 → None(不放宽)"

    # 端到端: 驱动真的 main()。子行排在父行前面也接得上; 正文清空的老笔记照常入库盖戳; 只有找不到父行的那条红
    import io, json, logging, os, sys
    os.environ.setdefault("FEISHU_APP_ID", "x")
    os.environ.setdefault("FEISHU_APP_SECRET", "y")
    rows = [_bjs_row("recC2", url="https://xhslink.cn/o/C2", parent="recP", kol="YQ04"),   # 父行之前
            parent,
            child,
            {"record_id": "recE", "fields": {"父记录": [{"type": "text", "table_id": "tblBJS", "text_arr": []}]}},
            cleared,
            orphan]
    saved = {k: getattr(engine, k) for k in (
        "FeishuClient", "get_supabase_client", "assert_db_schema_ready", "ensure_project_exists", "quarantine_record",
        "fetch_acknowledged_quarantine", "ensure_accounts_batch", "upsert_metrics_batch", "update_project_date_range",
        "fetch_all_pages", "upsert_notes_batch", "load_mapping")}
    saved_argv = sys.argv
    try:
        m2 = dict(m)
        m2["sync_config"] = dict(m["sync_config"], feishu_table_id="tblBJS")
        cap: dict = {"quarantined": []}

        def run(dry: bool):
            qb = _StoredQ(dict(kept_db))
            class F:
                def __init__(self, *a, **k): pass
                def list_records(self, *a, **k): return iter(rows)
            engine.FeishuClient = F
            engine.get_supabase_client = lambda *a, **k: qb
            engine.assert_db_schema_ready = lambda *a, **k: None
            engine.ensure_project_exists = lambda *a, **k: None
            engine.quarantine_record = lambda sb, p, rid, *a, **k: cap["quarantined"].append(rid)
            engine.fetch_acknowledged_quarantine = lambda sb, p: set()
            engine.ensure_accounts_batch = lambda *a, **k: []
            engine.upsert_metrics_batch = lambda *a, **k: (0, [])
            engine.update_project_date_range = lambda *a, **k: None
            engine.load_mapping = lambda _p: m2

            def pages(b, order_by=None):
                asked = getattr(b, "asked", None)
                if asked is not None:
                    b.asked = None
                    return []
                return []
            engine.fetch_all_pages = pages

            def up(sb, notes, dry_run=False):
                cap["notes"] = notes
                return [n["note_id"] for n in notes]
            engine.upsert_notes_batch = up
            buf = io.StringIO()
            h = logging.StreamHandler(buf)
            engine.logger.addHandler(h)
            sys.argv = ["x", "BJS_phase2"] + (["--dry-run"] if dry else [])
            cap["notes"] = []
            rc = engine.main()
            engine.logger.removeHandler(h)
            log = buf.getvalue()
            return rc, json.loads(log.split("Done: ")[1].split("\n")[0]), cap["notes"], log, qb

        rc, st, notes, log, qb = run(dry=False)
        by = {n["note_id"]: n for n in notes}
        assert st["body_from_parent"] == 2 and st["body_kept_from_db"] == 1, st
        # 合成行没填曝光 / 阅读 / 互动 / 档位, 「要害字段整列空」那道闸每列各计一次错(D-056), 和本节无关, 扣掉再看
        assert st["errors"] - len(st["missing_capabilities"]) == 1 and st["quarantined"] == 2 and rc == 1, \
            f"§9 只剩找不到父行的那条计错(空占位不计): {st}"
        assert st["empty_placeholder"] == 1 and st["undeclared_absorbed"] == 0, f"§9 父记录已在 mapping 里声明: {st}"
        assert set(by) == {"BJS_phase2_recC2", "BJS_phase2_recP", "BJS_phase2_recC", "BJS_phase2_recK"}, sorted(by)
        assert by["BJS_phase2_recC2"]["raw_content"] == _BODY, "§9 子行排在父行前面也接得上(先拉全再处理)"
        assert by["BJS_phase2_recC2"]["account_id"] == "YQ04" and by["BJS_phase2_recC2"]["publish_url"].endswith("/C2")
        assert by["BJS_phase2_recK"]["raw_content"] == "库里这篇正文"
        assert by["BJS_phase2_recK"]["data_quality_flags"]["content_cleared_in_feishu"] is True
        assert all(n.get("last_seen_at") for n in notes), "§9 接上的 / 留库里那份的都照常盖戳(找不到父行的那条库里没有, 不挡对账)"
        assert sorted(cap["quarantined"]) == ["recE", "recO"], cap["quarantined"]
        assert "BJS_phase2_recK" in qb.asked_ids and "BJS_phase2_recP" not in qb.asked_ids, \
            f"§9 父行这一轮飞书里有正文就不读库: {qb.asked_ids}"
        assert "飞书里正文空了" in log

        cap["quarantined"] = []
        rc, st, notes, log, qb = run(dry=True)
        assert st["body_from_parent"] == 2 and st["body_kept_from_db"] == 0 and not [i for i in qb.asked_ids if i], \
            f"§9 dry-run 不读库: 只接得上这一轮飞书里的父行 {st} {qb.asked_ids}"
    finally:
        for k, v in saved.items():
            setattr(engine, k, v)
        sys.argv = saved_argv

    src = Path(engine.__file__).read_text(encoding="utf-8")
    body = src[src.index("def main("):]
    i_rec = body.index("recover_missing_body(")
    i_tr = body.index("note, metric, undeclared = transform_row(")
    i_req = body.index("REQUIRED_NOTE_FIELDS =")
    assert i_rec < i_tr < i_req, "§9 先补正文、再 transform、再过缺必填闸"
    print("  §9 有链接缺正文: 父记录子行接父行正文(飞书优先、库里兜底, 同链接不接), 老笔记正文空了留库里那份、"
          "不计错照常盖戳; 空占位 / 没链接的不碰; dry-run 不读库 ✓")


def main() -> int:
    check_future_publish_time()
    check_cleared_status()
    check_unmapped_status_flag()
    check_flip_plan()
    check_flip_block()
    check_current_tiers_batched()
    check_wiring()
    check_reuse_previous_inheritance()
    check_missing_body_recovery()
    print("\ncheck_ingest_guards: 9 节全过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
