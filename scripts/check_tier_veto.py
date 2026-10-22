#!/usr/bin/env python3
"""风控否决位 (统一表评估 A2, D-124): 多选「流量状态」里任一标判成 风控 → 整格 风控, 不进 _TIER_RANK 择优。

为什么要: 「风控中」人会填进「流量状态」(运营 2026-10-22 第 9 条), 巡查机器人 linkcheck 在链接失效 /
上游标违规时也会写、而且从来不摘 (ops-answers-2026-10-22 §8.2), 和热度档共写一格。
按 rank 取最高时 ['爆贴','风控中'] 判 爆, 风控帖照样进书架 / L2 正例。10-22 生产有 4 行是这个形状
(OKMAN 2 / SPX 1 判 爆、WTG 1 判 预备), 3 行已推 ssll。

断行为不断源码 (D-051): §1 纯函数用真 mapping 的规则; §2 走 transform_row, 带上评论数, 确认数值推断不把 风控 推回爆;
§3 每份带风控规则的 mapping 都过一遍; §4 单值 / 长文本不归它管, 行为不变。

反证 (改坏之后必须变红):
  ① 去掉 extract_tier 里的否决位                 → §1 / §2 / §3 红
  ② 否决位写成"单值也按子串否决"                  → §4 红
  ③ 否决位挡掉了 爆贴预备 + 爆贴 → 爆 的旧修复     → §1 末两条红

跑法: cd scripts && python check_tier_veto.py
"""
from __future__ import annotations

import glob
import pathlib

import _common as c
import sync_feishu_notes_to_truth_vault as engine


def tier_of(pid: str, status) -> str | None:
    return c.extract_tier(status, c.load_mapping(pid)["tier_extraction"]["rules"])


# ── §1 生产里真出现过的形状 ────────────────────────────────────────────────
cases = [
    ("OKMAN_phase1", ["爆贴", "风控中"], "风控"),
    ("SPX_phase1", ["爆帖预备", "爆贴", "风控中"], "风控"),
    ("WTG_phase1", ["爆贴预备", "风控中"], "风控"),
    ("HATHERINE_phase1", ["大爆", "疑似限流"], "风控"),   # HATHERINE 把疑似限流也映成 风控
    ("OKMAN_phase1", ["风控中"], "风控"),
    # 没有风控标的格子照旧按 rank: 旧修复不能被否决位带坏
    ("OKMAN_phase1", ["爆帖预备", "爆贴"], "爆"),
    ("OKMAN_phase1", ["评估中", "无水花"], "趴"),
]
for pid, status, want in cases:
    got = tier_of(pid, status)
    assert got == want, f"{pid} {status} → {got}, 应为 {want}"
print(f"  ✓ §1 {len(cases)} 个形状: 带风控标的判 风控, 其余照旧按 rank")

# ── §2 整行走 transform_row: 评论数过线也不能把 风控 推回 爆 ───────────────────
spx = c.load_mapping("SPX_phase1")
row = {"素人编号": "1", "笔记内容": "正文", "发布时间": 1788710400000, "方向": "提问贴",
       "流量状态": ["大爆", "风控中"], "实时数据.评论数": 180,
       "反馈链接": {"link": "http://xhslink.cn/o/x", "text": "x"}}
note, _, und = engine.transform_row(spx, "rSPX", row)
assert und == [], und
assert note.get("comments_count") == 180, note.get("comments_count")
assert note.get("tier") == "风控", f"大爆 + 风控中 → {note.get('tier')}, 应为 风控"
assert note.get("tier_source") != "数值推断", "数值推断不该改写 风控"
print("  ✓ §2 transform_row: 大爆 + 风控中 → 风控, 评论数 180 也不推回")

# ── §3 每份带 风控 规则的 mapping: 风控标 + 该表最高档标 → 风控 ─────────────────
n = 0
for f in sorted(glob.glob(str(pathlib.Path(__file__).resolve().parent.parent / "mappings" / "*.yaml"))):
    pid = pathlib.Path(f).stem
    if pid.startswith("_"):
        continue
    rules = (c.load_mapping(pid).get("tier_extraction") or {}).get("rules") or []
    veto = [r["match_contains"][0] for r in rules if r.get("tier") == "风控" and r.get("match_contains")]
    top = [r["match_contains"][0] for r in rules
           if r.get("tier") in ("大爆", "爆") and r.get("match_contains")]
    if not veto or not top:
        continue
    for v in veto:
        got = c.extract_tier([top[0], v], rules)
        assert got == "风控", f"{pid}: [{top[0]!r}, {v!r}] → {got}, 应为 风控"
    n += 1
assert n >= 10, f"只核到 {n} 份带风控规则的 mapping, 路径不对?"
print(f"  ✓ §3 {n} 份 mapping: 风控标 + 最高档标 → 风控")

# ── §4 单值 / 长文本不归否决位管 ─────────────────────────────────────────────
rules = [{"match_contains": ["爆贴"], "tier": "爆"}, {"match_contains": ["风控"], "tier": "风控"}]
assert c.extract_tier("之前风控过, 现在已恢复爆贴", rules) == "爆", "单值长文本按列序取首个命中, 不该被否决"
assert c.extract_tier("风控中", rules) == "风控"
print("  ✓ §4 单值 / 长文本仍按规则列序, 否决位只管多选标")

print("\n风控否决位: all checks passed")
