#!/usr/bin/env python3
"""馆员冷路径预筛 (D-088): 整架取回、按项目级字段挑 ≤24 张给 LLM、rank 前 8 永远在、输出封顶。

断行为不断源码 (D-051): 真的调 librarian.core.shortlist / librarian_select (打桩 fetch_candidates /
get_supabase / call_anthropic / 缓存读写), 核对 LLM 真正看到的候选、缓存版本串、max_tokens。

反证 (改坏之后必须变红, 每条在 D-088 里记了实跑结果):
  ① _affinity 去掉同品牌 +3                        → §2 品牌自己的卡 (rank 最低) 进不了 shortlist, 红
  ①b _affinity 去掉同品类 +2                       → §2b 品类词命中的 C 品牌填不满 16 个位子, 红
  ①c _affinity 去掉人群词 +1                       → §2c 人群词命中的 B 品牌进不来, 红
  ② SHORTLIST_GLOBAL_KEEP 改 0                      → §3 rank 前 8 (别的品牌) 不再无条件保留, 红
  ③ _project_text 把本次 delta 也拼进去             → §4 换 delta 不换项目, shortlist 变了, 红
  ④ library_version 改成看 shortlist 而不是整架     → §6 换掉一张没进 shortlist 的卡, 版本串不变, 红
  ⑤ LIBRARIAN_MAX_TOKENS 改回 1500                  → §7 红
  ⑥ _select_via_llm 喂整架 (cards) 而不是 shown     → §7 LLM 看到了没进 shortlist 的卡, 红

跑法: cd scripts && python check_librarian_shortlist.py
"""
from __future__ import annotations

import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))   # repo 根: 让 librarian 包可导入

from librarian import core  # noqa: E402


def card(nid, brand, category, rank, audience=None):
    return {"source_note_id": nid, "brand": brand, "category": category, "rank_score": rank,
            "target_audience": audience, "tier": "爆", "curated_at": "2026-09-01",
            "is_curated": True, "hook_type": "h", "structure": "s", "why_it_worked": "w",
            "transferable_tactic": "t", "raw_excerpt": f"excerpt of {nid}", "synthetic": False}


# 60 张: A 品牌 30 张 rank 最高 (1.90 → 1.61), C 品牌 20 张居中 (1.50 → 1.31), B 品牌 10 张【最低】(1.20 → 1.11)
A = [card(f"A_{i:02d}", "AlphaBrand", "保健品", 1.90 - i * 0.01, ["上班族"]) for i in range(30)]
C = [card(f"C_{i:02d}", "GammaBrand", "美妆", 1.50 - i * 0.01, ["学生党"]) for i in range(20)]
B = [card(f"B_{i:02d}", "BetaBrand", "酒类", 1.20 - i * 0.01, ["夜猫子", "上班族"]) for i in range(10)]
CARDS = A + C + B
ids = lambda cs: [c["source_note_id"] for c in cs]   # noqa: E731

# ⚠️ 夹具里 B 品牌【只有品牌】这一个信号: system_prompt 不提 B 的品类 (酒类) 和人群 (夜猫子)。
#    第一版把三个信号堆在一句话里, 反证 ① (去掉同品牌 +3) 没红 —— B 靠品类 +2 和人群 +1 照样进。
#    每个信号单独钉 (§2 品牌 / §2b 品类 / §2c 人群), 反证才咬得住。
BRIEF = {
    "consumer": "autowriter", "project_id": "p-beta", "brand": "BetaBrand", "project_name": "Beta 夏季新品",
    "system_prompt": "为 BetaBrand 预调酒写小红书种草, 微醺场景", "tactics": ["场景痛点"],
    # delta
    "tactic": "下班微醺", "key_messages": "低度好入口", "target_audience": "25-35 岁女性", "tone": "口语",
    "extra_instructions": "开头强钩子", "draft_topic": "一个人的夜晚怎么喝",
}

# ══ §1 · 上限与直通: 超过 cap 挑 cap 张; 不超过 cap 原样全给 (只排序) ═══════════════════════════
short = core.shortlist(CARDS, BRIEF)
assert len(short) == core.SHORTLIST_CAP == 24, f"应挑 {core.SHORTLIST_CAP} 张, 实得 {len(short)}"
small = core.shortlist(list(reversed(C[:10])), BRIEF)
assert ids(small) == ids(C[:10]), "卡不超过 cap 时必须原样全给、按 rank 降序"
print(f"✓ D-088: 60 张挑 {len(short)} 张; 10 张直通并按 rank 排序")

# ══ §2 · 品牌自己的卡优先 —— B 的 10 张 rank 全库最低, 按 rank 硬切 50 都进不了, 预筛必须全进 ═══════
assert set(ids(B)) <= set(ids(short)), f"品牌自己的卡没进 shortlist: 缺 {sorted(set(ids(B)) - set(ids(short)))}"
print("✓ D-088: 同品牌 10 张 (rank 全库最低) 全部在 shortlist 里")

# ══ §2b/§2c · 品类 +2 与人群 +1 各自单独钉: 没有品牌可对时, 品类词 / 人群词命中的卡要顶上来 ═══════
top8 = ids(sorted(CARDS, key=core._rank_key)[:core.SHORTLIST_GLOBAL_KEEP])
no_brand_cat = {"consumer": "autowriter", "project_id": "p-x", "brand": "", "project_name": "无名项目",
                "system_prompt": "写美妆种草"}                                   # 只命中 C 的品类
rest_c = set(ids(core.shortlist(CARDS, no_brand_cat))) - set(top8)
assert len(rest_c) == 16 and rest_c <= set(ids(C)), f"品类词命中的 C 品牌该填满保留之外的 16 个位子: {sorted(rest_c)}"
no_brand_aud = {"consumer": "autowriter", "project_id": "p-y", "brand": "", "project_name": "无名项目",
                "system_prompt": "写给夜猫子看的内容"}                            # 只命中 B 的人群词
short_aud = core.shortlist(CARDS, no_brand_aud)
assert set(ids(B)) <= set(ids(short_aud)), f"人群词命中的 B 品牌 (rank 最低) 该进 shortlist: {ids(short_aud)}"
print("✓ D-088: 品类词命中 +2、人群词命中 +1 各自单独成立")

# ══ §3 · 跨主题迁移要有料: rank 全局前 8 (全是 A 品牌) 无条件保留 ═══════════════════════════════
assert set(top8) <= set(ids(short)), f"rank 前 {core.SHORTLIST_GLOBAL_KEEP} 没无条件保留: 缺 {sorted(set(top8) - set(ids(short)))}"
assert core.SHORTLIST_GLOBAL_KEEP >= 1, "无条件保留至少要有 1 张"
print(f"✓ D-088: rank 前 {core.SHORTLIST_GLOBAL_KEEP} 张 (别的品牌) 无条件保留")

# ══ §4 · 只看项目级字段: 换 delta 不变、换品牌就变 (block1 的 prompt cache 靠这条) ══════════════════
other_delta = dict(BRIEF, tactic="完全另一个方向", key_messages="别的卖点", target_audience="学生党",
                   tone="正式", extra_instructions="", draft_topic="换个选题")
assert ids(core.shortlist(CARDS, other_delta)) == ids(short), "本次 delta 不该影响 shortlist (同项目内必须稳定)"
gamma = dict(BRIEF, brand="GammaBrand", project_name="Gamma", system_prompt="为 GammaBrand 写美妆种草, 学生党")
short_g = core.shortlist(CARDS, gamma)
rest_g = set(ids(short_g)) - set(top8)        # 无条件保留的 8 张之外的 16 个位子
assert len(rest_g) == 16 and rest_g <= set(ids(C)) and not (set(ids(B)) & set(ids(short_g))), \
    f"换成 Gamma 项目后 8 张保留之外应全是 C 品牌、B 品牌一张不剩: {ids(short_g)}"
print("✓ D-088: 换 delta 结果不变, 换项目结果跟着变")

# ══ §5 · 确定性: 输入乱序结果不变; 输出按 rank 降序 ═══════════════════════════════════════════
shuffled = list(CARDS)
random.Random(7).shuffle(shuffled)
assert ids(core.shortlist(shuffled, BRIEF)) == ids(short), "输入顺序不该影响结果"
assert ids(short) == ids(sorted(short, key=core._rank_key)), "输出必须按 rank_score 降序 (prompt 里的说法不变)"
print("✓ D-088: 乱序输入结果一样, 输出按 rank 降序")

# ══ §6 · 缓存版本看【整架】: 换掉一张没进 shortlist 的卡, 版本串必须变 (TV-03 那课, 边界是整架) ═════
core.get_supabase = lambda *a, **k: object()
core.latest_gate2_run = lambda sb: None
core.fetch_candidates = lambda sb, **kw: list(CARDS)
dry = core.librarian_select(BRIEF, dry_run=True)
assert dry["shelf_count"] == 60 and dry["candidate_count"] == 24, (dry["shelf_count"], dry["candidate_count"])
assert dry["library_version"] == core.library_version(CARDS), "版本串必须按整架算, 不是按 shortlist 算"
out_of_short = next(c for c in CARDS if c["source_note_id"] not in set(ids(short)))
swapped = [dict(c, source_note_id="NEW_X") if c is out_of_short else c for c in CARDS]
core.fetch_candidates = lambda sb, **kw: list(swapped)
dry2 = core.librarian_select(BRIEF, dry_run=True)
assert ids(core.shortlist(swapped, BRIEF)) == ids(short), "换掉的那张本来就不在 shortlist 里, shortlist 不该变"
assert dry2["library_version"] != dry["library_version"], "整架换了一张 (哪怕没进 shortlist) 缓存版本也得变"
assert "NEW_X" not in dry2["prompt"] and out_of_short["source_note_id"] not in dry["prompt"], "没进 shortlist 的卡不该出现在 prompt 里"
print("✓ D-088: 版本串按整架算; 换掉一张没进 shortlist 的卡, 缓存键照样失效")

# ══ §7 · LLM 真正看到的是 shortlist, 且输出封顶 ≤1000 token ════════════════════════════════════
core.fetch_candidates = lambda sb, **kw: list(CARDS)
core.get_cache = lambda sb, key: None
writes: list = []
core.put_cache = lambda sb, key, brief, lib_v, sel, **kw: writes.append((key, sel, kw.get("select_ms")))
seen: dict = {}


def fake_llm(prompt, model, *, system=None, **kw):
    seen["system"] = system
    seen["kw"] = kw
    return '{"selected": [{"source_note_id": "B_00", "why_relevant": "同品牌微醺场景", "borrow_what": "借开场钩子"},' \
           ' {"source_note_id": "A_00", "why_relevant": "跨主题借结构", "borrow_what": "借三段式骨架"}]}'


core.call_anthropic = fake_llm
st: dict = {}
sel = core.librarian_select(BRIEF, _status_out=st)
assert [s["source_note_id"] for s in sel] == ["B_00", "A_00"] and st["status"] == "ok", (sel, st)
assert sel[0]["hook_type"] == "h" and sel[0]["excerpt"] == "excerpt of B_00", "选中卡要富集卡内容"
assert seen["kw"].get("max_tokens") == core.LIBRARIAN_MAX_TOKENS and core.LIBRARIAN_MAX_TOKENS <= 1000, \
    f"输出必须封顶 ≤1000 token: 传了 {seen['kw'].get('max_tokens')}"
block1 = seen["system"][0]["text"]
assert block1.count("\n[") == 24, f"LLM 应看到 24 张卡, 实看到 {block1.count(chr(10) + '[')}"
assert all(f"[{nid}]" in block1 for nid in ids(short)) and "[C_19]" not in block1, "LLM 看到的必须恰好是 shortlist"
assert "30 字" in block1, "指令里要写明两句批注各 ≤30 字 (输出封顶靠它, max_tokens 只是兜底)"
assert writes and writes[0][1] == sel and writes[0][2] is not None, "冷路径结果要进缓存并带 select_ms"
print("✓ D-088: LLM 看到的恰是 shortlist 24 张, max_tokens 封顶 ≤1000, 批注 ≤30 字写进指令, 结果进缓存")
print("\ncheck_librarian_shortlist: all checks passed")
