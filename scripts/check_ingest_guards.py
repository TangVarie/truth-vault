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


def main() -> int:
    check_future_publish_time()
    check_cleared_status()
    check_unmapped_status_flag()
    check_flip_plan()
    check_flip_block()
    check_current_tiers_batched()
    check_wiring()
    print("\ncheck_ingest_guards: 7 节全过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
