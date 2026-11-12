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

§8 选卡去重 (审计 11-02 F14a) 和 §9 同一个请求在飞的合并 (AU-F09) 也在这里, 同样真调 librarian_select。反证 (11-11 实跑):
  ⑦ _select_via_llm 去掉 `if nid in taken: continue`           → §8 同一张卡回来两遍, 红
  ⑧ librarian_select 里 _board 恒当领头 (不等在飞的那次)        → §9 第二个请求自己又调了一次模型, 红
  ⑨ _join 不拷贝 (直接回领头那份 list)                          → §9 两个请求拿到同一个对象, 红
  ⑩ librarian_select 的 finally 里不 _land                      → §9 降级之后登记还在, 后到的请求一直等, 红
  ⑪ _unboard 不看是不是自己那条就删                             → §9 领头那次落地时把别人的登记摘了, 红

§10 回流闸 (D-151): 出处帖被闸挡下的卡不进书架。默认关; 这一节两种状态都跑 (改 core.RETURN_GATE_DEFAULT, 不看环境变量)。
反证 (11-12 实跑, 13 个都红):
  ⑫ CARD_BLOCKING_REASONS 加上 not_clean                      → 只有 not_clean 的卡被拿掉, 红
  ⑬ _gate_blocked 去掉 10 分钟那一条 (每次借阅都读库)          → 读库次数, 红
  ⑭ _drop_gated 去掉品牌保底                                  → 一个品牌的卡一张不剩, 红
  ⑮ 读失败时往外抛 / 丢掉上一次读成的结论 / 失败那次不记时刻    → 红
  ⑯ librarian_select 里不在预筛之前筛                          → 书架、版本串没变, 红
  ⑰ _drop_gated 不看开关                                      → 关着也读了库, 红
  ⑱ gate_reasons 把字符串形状的原因也当结论                    → 读不懂的行被拿掉, 红
  ⑲ pass 却带着原因的行也挡 / ⑳ 不认识的类别也当结论           → 红
  ㉑ 没写品牌的卡也算一个品牌保底 / ㉒ 环境变量关不掉代码默认     → 红
  ㉓ _read_gate 按 gate_reasons.hold 的细项放过一部分 hold (11-12 复审后加的 ⑦) → 正文是空的帖的卡被借出去, 红

跑法: cd scripts && python check_librarian_shortlist.py
"""
from __future__ import annotations

import logging
import os
import pathlib
import random
import sys
import threading
import types

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


def pick(*nids):
    return '{"selected": [' + ", ".join(
        '{"source_note_id": "%s", "why_relevant": "第 %d 条", "borrow_what": "借结构"}' % (n, i)
        for i, n in enumerate(nids)) + "]}"


# ══ §8 · 选卡去重 (F14a): 同一张卡模型挑了两遍只留第一遍, 重复的不占 5 张的名额 ═══════════════════════
core.call_anthropic = lambda *a, **k: pick("B_00", "A_00", "B_00", "B_00", "A_01", "A_00", "A_02", "A_03", "A_04")
writes.clear()
st = {}
sel = core.librarian_select(BRIEF, _status_out=st)
assert [s["source_note_id"] for s in sel] == ["B_00", "A_00", "A_01", "A_02", "A_03"] and st["status"] == "ok", \
    f"同一张卡只该留一遍, 重复的不占名额: {[s['source_note_id'] for s in sel]}"
assert [s["why_relevant"] for s in sel[:2]] == ["第 0 条", "第 1 条"], "留的是第一遍的批注"
assert [s["source_note_id"] for s in writes[-1][1]] == ["B_00", "A_00", "A_01", "A_02", "A_03"], "进缓存的那份也没有重复"
core.call_anthropic = lambda *a, **k: pick("B_00", "B_00")
assert [s["source_note_id"] for s in core.librarian_select(BRIEF)] == ["B_00"], "只挑了一张、挑了两遍 → 一张"
print("✓ F14a: 同一张卡回来几遍只留第一遍, 不占名额, 缓存里也没有重复")

# ══ §9 · 同一个请求在飞的合并 (AU-F09): 第二个等第一个、拿同一份结果; 失败不传下去; 等有上限 ═══════════
logging.getLogger("flywheel_librarian").disabled = True   # ②–④ 故意让模型 / 查库失败、让等待超时, 那几段日志不用进 CI 输出
KEY = core.librarian_select(BRIEF, dry_run=True)["cache_key"]
OTHER = dict(BRIEF, draft_topic="换个选题")          # 换了 delta → 另一个 cache_key, 不该并
real_board = core._board
joined = threading.Event()


def spy_board(key):                                   # 第二个请求拿到在飞的那条登记时点一下, 主线程才放行领头那次
    flight, lead = real_board(key)
    if not lead:
        joined.set()
    return flight, lead


core._board = spy_board


def race(first_llm, *, wait_join=True):
    """两个线程借同一个 brief: 第一个卡在 first_llm 里, 等第二个并上来再放行。返回 (两边结果, 模型被调了几次)。"""
    gate, entered, calls, out = threading.Event(), threading.Event(), [], {}
    joined.clear()

    def llm(prompt, model, *, system=None, **kw):
        calls.append(1)
        if len(calls) > 1:                            # 只有领头那次卡住; 再有人调模型就是没并上
            return pick("A_05")
        entered.set()
        assert gate.wait(20), "领头那次没被放行"
        return first_llm()

    def borrow(name):
        st = {}
        try:
            out[name] = (core.librarian_select(dict(BRIEF), _status_out=st), st.get("status"))
        except Exception as exc:  # noqa: BLE001
            out[name] = (exc, "raised")

    core.call_anthropic = llm
    t1 = threading.Thread(target=borrow, args=("first",), daemon=True)   # daemon: 断言红了进程照样退得出去
    t1.start()
    assert entered.wait(20), "领头那次没走到模型"
    t2 = threading.Thread(target=borrow, args=("second",), daemon=True)
    t2.start()
    if wait_join:
        assert joined.wait(20), "第二个请求没并到在飞的那次上"
    return gate, calls, out, (t1, t2)


def finish(gate, threads):
    gate.set()
    for t in threads:
        t.join(20)
        assert not t.is_alive(), "线程没结束 (等在飞的那次没被叫醒?)"


# ① 正常: 模型只调一次, 两边拿到一样的卡、各自一份; 换 delta / use_cache=False 的请求不等
writes.clear()
merged0 = core.MERGE_STATS["merged"]
gate, calls, out, threads = race(lambda: pick("B_00", "A_00"))
assert [s["source_note_id"] for s in core.librarian_select(OTHER)] == ["A_05"] and len(calls) == 2, \
    "brief 不一样 (另一个 cache_key) 不该等在飞的那次"
assert [s["source_note_id"] for s in core.librarian_select(BRIEF, use_cache=False)] == ["A_05"] and len(calls) == 3, \
    "use_cache=False 是强制重跑, 不并"
finish(gate, threads)
(first, st1), (second, st2) = out["first"], out["second"]
assert len(calls) == 3, f"同一个请求在飞时第二个不该再调模型: 模型被调了 {len(calls)} 次 (该是领头 1 次 + 上面两次)"
assert [s["source_note_id"] for s in first] == ["B_00", "A_00"] and second == first and (st1, st2) == ("ok", "ok"), out
assert second is not first and second[0] is not first[0], "后到的拿的是拷贝, 不是领头那次的同一个对象"
assert len([w for w in writes if w[0] == KEY]) == 1, "这个 cache_key 只写一次缓存"
assert core.MERGE_STATS["merged"] == merged0 + 1 and KEY not in core._FLIGHTS and not core._FLIGHTS, \
    f"并了一次要记数, 结束后登记清空: {core.MERGE_STATS} {len(core._FLIGHTS)}"

# ② 领头那次降级 (模型挂了): 后到的一起拿降级结果、不自己再试; 登记摘掉、不进缓存, 再来的请求照常重新选
writes.clear()


def boom():
    raise RuntimeError("relay down")


gate, calls, out, threads = race(boom)
finish(gate, threads)
assert out["first"] == ([], "degraded") and out["second"] == ([], "degraded") and len(calls) == 1, \
    f"领头那次降级, 后到的拿同一个降级结果, 不再付一次: {out} 模型 {len(calls)} 次"
assert not core._FLIGHTS and not writes, "降级不进缓存, 登记要在 finally 里摘掉"
core.call_anthropic = lambda *a, **k: pick("B_00")
st = {}
assert [s["source_note_id"] for s in core.librarian_select(BRIEF, _status_out=st)] == ["B_00"] and st["status"] == "ok", \
    "一次失败不能传下去: 之后同一个请求照常选得到卡"

# ③ 领头那次崩了 (异常抛出去, 没有结果可拿): 后到的自己选, 和没有合并时一样
real_get = core.get_cache
state = {"n": 0}
gate3, entered3 = threading.Event(), threading.Event()


def flaky_get(sb, key):
    state["n"] += 1
    if state["n"] == 1:
        entered3.set()
        assert gate3.wait(20)
        raise RuntimeError("db down")
    return None


core.get_cache = flaky_get
out = {}


def borrow3(name):
    st = {}
    try:
        out[name] = (core.librarian_select(dict(BRIEF), _status_out=st), st.get("status"))
    except Exception as exc:  # noqa: BLE001
        out[name] = (type(exc).__name__, "raised")


joined.clear()
t1 = threading.Thread(target=borrow3, args=("first",), daemon=True)
t1.start()
assert entered3.wait(20)
t2 = threading.Thread(target=borrow3, args=("second",), daemon=True)
t2.start()
assert joined.wait(20)
finish(gate3, (t1, t2))
core.get_cache = real_get
assert out["first"] == ("RuntimeError", "raised"), out
assert [s["source_note_id"] for s in out["second"][0]] == ["B_00"] and out["second"][1] == "ok" and not core._FLIGHTS, \
    f"领头那次崩了, 后到的该自己选出卡来: {out}"

# ④ 等有上限: 等满了就摘掉卡住的那条登记、自己选; 卡住的那次后来落地, 不许把别人新登记的那条摘了
core.MERGE_WAIT_S, keep = 0.3, core.MERGE_WAIT_S
timeouts0 = core.MERGE_STATS["wait_timeouts"]
gate, calls, out, threads = race(lambda: pick("B_00"))
threads[1].join(20)
assert not threads[1].is_alive() and [s["source_note_id"] for s in out["second"][0]] == ["A_05"] and len(calls) == 2, \
    f"等满 {core.MERGE_WAIT_S} 秒后第二个请求该自己选: {out.get('second')}"
assert KEY not in core._FLIGHTS and core.MERGE_STATS["wait_timeouts"] == timeouts0 + 1, "卡住的那条登记要摘掉、记一次数"
newer, lead = real_board(KEY)                         # 这时又来一个同样的请求, 它当领头
assert lead
finish(gate, threads[:1])
assert core._FLIGHTS.get(KEY) is newer, "卡住的那次落地时只能摘自己那条登记"
core._land(KEY, newer, None)
assert not core._FLIGHTS and out["first"][1] == "ok"
core.MERGE_WAIT_S = keep
assert core.MERGE_WAIT_S >= 60, "等的上限不能比领头那次模型整轮 (60 秒) 短, 否则正常慢的那次也会被重选一遍"
core._board = real_board
logging.getLogger("flywheel_librarian").disabled = False
print("✓ AU-F09: 同一个请求在飞时第二个等它、拿同一份拷贝 (模型只调一次); 降级一起拿、不传下去; 崩了 / 等满了自己选")

# ══ §10 · 回流闸 (D-151): 出处帖被闸挡下的卡不进书架; 默认关, 关着和以前一字不差; 读不到 / 读不懂就不筛 ═══════════
logging.getLogger("flywheel_librarian").disabled = True   # 下面故意让读库失败、让品牌保底触发, 那几行日志不用进 CI 输出
saved_env = os.environ.pop(core.RETURN_GATE_ENV, None)    # 这一节自己定开关, 不看跑它的机器上设了什么
saved_default, saved_clock, saved_chunk = core.RETURN_GATE_DEFAULT, core._gate_clock, core.RETURN_GATE_CHUNK
clock = [1000.0]
core._gate_clock = lambda: clock[0]


class GateSB:
    """假库: 只会 autowriter.tv_note_links 的 select(...).in_(note_id, [...]).execute(), 记下每次请求问了几个 id。"""

    def __init__(self, rows=(), fail=None):
        self.rows, self.fail, self.calls = {r["note_id"]: r for r in rows}, fail, []

    def schema(self, name):
        self._schema = name
        return self

    def table(self, name):
        self._table = name
        return self

    def select(self, cols):
        self._cols = cols
        return self

    def in_(self, col, vals):
        assert col == "note_id"
        self._vals = list(vals)
        return self

    def execute(self):
        self.calls.append((self._schema, self._table, self._cols, len(self._vals)))
        if self.fail is not None:
            raise self.fail
        return types.SimpleNamespace(data=[dict(self.rows[v]) for v in self._vals if v in self.rows])


def gate_row(nid, gate, *reasons, raw=None):
    return {"note_id": nid, "gate": gate, "gate_reasons": {"reasons": list(reasons)} if raw is None else raw[0]}


def use(sb, *, fresh=True):
    """换一个库; fresh = 像刚起的进程 (没有上一次读到的结论, 计数清零)。"""
    core.get_supabase = lambda *a, **k: sb
    if fresh:
        core._GATE.update(at=None, blocked=None)
        core.GATE_STATS.update(read_ok=None, columns=None, read_errors=0, verdicts=0, unreadable=0,
                               would_drop=0, brands_kept=0)
    return sb


def shelf():
    d = core.librarian_select(BRIEF, dry_run=True)
    return d["shelf_count"], d["library_version"], d["cache_key"], d["prompt"]


GATED = [gate_row("A_00", "withdrawn", "withdrawn"),            # rank 全库第一 (无条件保留的那 8 张里): 也要拿掉
         gate_row("A_01", "unsure", "unsure"), gate_row("A_02", "hold", "hold"),
         gate_row("B_00", "fail", "efficacy"), gate_row("B_02", "fail", "not_clean", "risk"),
         gate_row("B_01", "fail", "not_clean"),                 # 只有 not_clean: 照借 (D-133 第 1 条, owner 没定)
         gate_row("A_03", "pass"),
         gate_row("A_04", None, raw=[None]),                    # 这一行还没分过类
         gate_row("A_05", "fail", raw=["efficacy"]),            # gate_reasons 是字符串: 读不懂 → 留
         gate_row("A_06", "fail", raw=[{"reasons": "efficacy"}]),
         gate_row("A_07", "fail", raw=[{"reasons": [{"name": "efficacy"}]}]),
         gate_row("A_08", "pass", "efficacy"),                  # 类别和原因对不上: 按 pass 留
         gate_row("C_00", "later", "efficacy")]                 # 不认识的类别 → 留
DROPPED = {"A_00", "A_01", "A_02", "B_00", "B_02"}
OFF = (60, dry["library_version"], dry["cache_key"], dry["prompt"])      # §6 算的: 没有闸时的书架、版本串、缓存键、prompt

# ① 开关关着 (代码默认关; 环境变量写 0 / off 也是关): 一次库都不读, 书架、版本串、缓存键、prompt 和 §6 一字不差
shipped = core.return_gate_enabled()                    # 环境变量没设 → 就是代码默认
core.RETURN_GATE_DEFAULT = False
sb = use(GateSB(GATED))
assert shelf() == OFF and not sb.calls, f"开关关着不该读库、不该动书架: 读了 {len(sb.calls)} 次"
assert OFF[2] == core.cache_key(BRIEF, core.library_version(CARDS)), "关着时缓存键就是以前那条算法"
whole = list(CARDS)
assert core._drop_gated(sb, whole) is whole and not sb.calls, "关着时原样返回同一个 list"
core.call_anthropic = lambda *a, **k: pick("B_00", "A_00")
assert [s["source_note_id"] for s in core.librarian_select(BRIEF)] == ["B_00", "A_00"] and not sb.calls, \
    "关着时被闸挡下的帖的卡照旧借得出去 (和以前一样)"
assert core.gate_health()["on"] is False and core.gate_health()["read_age_s"] is None
for raw, want in (("1", True), ("true", True), ("ON", True), ("0", False), ("off", False), ("", False)):
    os.environ[core.RETURN_GATE_ENV] = raw
    assert core.return_gate_enabled() is want, f"LIBRARIAN_RETURN_GATE={raw!r} 该是 {want}"
core.RETURN_GATE_DEFAULT = True
os.environ[core.RETURN_GATE_ENV] = "0"
assert core.return_gate_enabled() is False and shelf() == OFF and not sb.calls, "代码默认开了, 环境变量写 0 仍然关得掉"
del os.environ[core.RETURN_GATE_ENV]
assert core.return_gate_enabled() is True, "环境变量没设 → 听代码默认 (开的那个 PR 只改 core.RETURN_GATE_DEFAULT 一行)"

# ② 开着: 挡卡的五种原因拿掉, 只有 not_clean / pass / 没结论 / 读不懂的都留; 在预筛之前拿, 给模型的还是满 24 张
gate_seen: dict = {}


def gate_llm(prompt, model, *, system=None, **kw):
    gate_seen["system"] = system
    return pick("B_00", "B_01", "A_00", "A_03")


core.call_anthropic = gate_llm
n, v_on, k_on, _ = shelf()
kept = [c for c in CARDS if c["source_note_id"] not in DROPPED]
assert n == 55 and v_on == core.library_version(kept) != OFF[1] and k_on != OFF[2], \
    f"书架该剩 55 张、版本串按筛过的书架算 (卡一被挡缓存键就换): {n}"
st = {}
sel = core.librarian_select(BRIEF, _status_out=st)
assert [s["source_note_id"] for s in sel] == ["B_01", "A_03"] and st["status"] == "ok", \
    f"模型硬挑被挡的卡也拿不到 (不在候选里): {[s['source_note_id'] for s in sel]}"
block1 = gate_seen["system"][0]["text"]
assert block1.count("\n[") == 24, f"在预筛之前拿掉: 给模型的还是满 24 张, 实际 {block1.count(chr(10) + '[')}"
assert not [x for x in DROPPED if f"[{x}]" in block1], "被挡的卡不该出现在给模型的候选里"
assert all(f"[{x}]" in block1 for x in ("B_01", "B_03", "A_03", "A_04", "A_05", "A_06", "A_07")), \
    "只有 not_clean、pass、没分过类、读不懂的卡都要留在候选里"
h = core.gate_health()
assert h == {"on": True, "read_age_s": 0, "read_ok": True, "columns": True, "read_errors": 0, "verdicts": 8,
             "unreadable": 4, "would_drop": 5, "brands_kept": 0}, h
assert all(x is None or isinstance(x, (bool, int)) for x in h.values()), "/health 里只有布尔、整数和 None"
assert sb.calls == [("autowriter", "tv_note_links", "note_id, gate, gate_reasons", 60)], \
    f"两次借阅 + 一次 dry-run 只读一次库 (10 分钟内不重读): {sb.calls}"

# ③ 10 分钟读一次: 期间库里的结论变了也不重读; 过了 10 分钟才读到
sb.rows["B_01"] = gate_row("B_01", "fail", "not_clean", "efficacy")
clock[0] += core.RETURN_GATE_TTL_S - 1
assert shelf()[0] == 55 and len(sb.calls) == 1, "10 分钟内不重读"
clock[0] += 2
assert shelf()[0] == 54 and len(sb.calls) == 2 and core.gate_health()["would_drop"] == 6, "过了 10 分钟重读一次"
assert core.RETURN_GATE_TTL_S == 600, "decisions: 每个进程最多 10 分钟读一次"

# ④ 读失败: 沿用上一次读成的结论 (书架不抖), 失败那次也占着 10 分钟; 一次都没读成过 → 不筛。都不往借阅里抛
sb.fail = RuntimeError("PostgREST down")
clock[0] += core.RETURN_GATE_TTL_S + 1
assert shelf()[0] == 54 and len(sb.calls) == 3, "读失败时沿用上一次读到的结论"
assert shelf()[0] == 54 and len(sb.calls) == 3, "失败之后 10 分钟内也不再去撞库"
h = core.gate_health()
assert (h["read_ok"], h["read_errors"]) == (False, 1), h
sb = use(GateSB(GATED, fail=RuntimeError("PostgREST down")))
assert shelf() == OFF and len(sb.calls) == 1, "一次都没读成过: 不筛, 和关着一样"
st = {}
assert [s["source_note_id"] for s in core.librarian_select(BRIEF, _status_out=st)] == ["B_00", "B_01", "A_00", "A_03"] \
    and st["status"] == "ok", "读闸失败不影响借阅"
use(object())                                           # 连 .schema 都没有的库
assert shelf() == OFF, "库对象不对也不许抛进借阅"
sb = use(GateSB(GATED, fail=RuntimeError("{'code': '42703', 'message': 'column tv_note_links.gate does not exist'}")))
assert shelf() == OFF, "aw 迁移 020 没跑 (没有这两列): 不筛"
h = core.gate_health()
assert (h["columns"], h["read_ok"], h["read_errors"], h["would_drop"]) == (False, True, 0, 0), \
    f"没有这两列不是读库故障, 不记 read_errors: {h}"

# ⑤ 品牌保底: 一个品牌的卡全被挡 → 这个品牌的卡全留、记一笔; 没全挡的照筛; 没写品牌的卡不算一个品牌
sb = use(GateSB([gate_row(f"B_{i:02d}", "withdrawn", "withdrawn") for i in range(10)] + [GATED[0]]))
n, _, _, prompt_b = shelf()
assert n == 59 and all(f"[B_{i:02d}]" in prompt_b for i in range(10)) and "[A_00]" not in prompt_b, \
    f"B 品牌 10 张全被挡 → 全留; A_00 照样拿掉: 书架 {n}"
h = core.gate_health()
assert (h["would_drop"], h["brands_kept"]) == (1, 1), h
sb = use(GateSB([gate_row(f"B_{i:02d}", "withdrawn", "withdrawn") for i in range(9)]))
assert shelf()[0] == 51 and core.gate_health()["brands_kept"] == 0, "挡了 9 张、还剩 1 张: 不触发保底"
nameless = [dict(card("N_00", None, "保健品", 0.5)), dict(card("N_01", "", "保健品", 0.4))] + CARDS
sb = use(GateSB([gate_row("N_00", "hold", "hold"), gate_row("N_01", "hold", "hold")]))
assert ids(core._drop_gated(sb, nameless)) == ids(CARDS), "没写品牌的卡全被挡也照筛 (它们不是一个品牌)"

# ⑥ 分批: 一批不超过 RETURN_GATE_CHUNK 个 id (.in_ 走 URL)
core.RETURN_GATE_CHUNK = 25
sb = use(GateSB(GATED))
assert shelf()[0] == 55 and [c[3] for c in sb.calls] == [25, 25, 10], sb.calls
assert saved_chunk <= 200

# ⑦ hold 不看细项: 写作台把搁置的细项记在 gate_reasons.hold 里 (只给人看), 馆员只认 reasons 里的 hold —— 哪种细项都挡。
#    11-12 复审: 最初 short_body 是「正文不到 50 字」, 书架上 13 张爆 / 大爆的卡会因此一直借不出去。那是闸判错了类
#    (短帖不会变长, 不是「还没到齐」), 改在写作台那头: short_body 现在只指正文是空的, 有字的短帖照走后面几步。所以馆员
#    这里不为它开口子 —— 正文是空的帖的卡不该借
core.RETURN_GATE_CHUNK = saved_chunk
HOLDS = [dict(gate_row(nid, "hold", "hold"), gate_reasons={"reasons": ["hold"], "hold": list(details)})
         for nid, details in (("C_10", ["short_body"]), ("C_11", ["scheduled"]), ("C_12", ["no_publish_time", "short_body"]),
                              ("C_13", ["synthetic"]), ("C_14", []))]
sb = use(GateSB(HOLDS))
left = ids(core._drop_gated(sb, list(CARDS)))
assert sorted(set(ids(CARDS)) - set(left)) == [f"C_{i}" for i in range(10, 15)], \
    f"hold 不管细项是什么都挡 (正文是空的也是还没到齐): 拿掉了 {sorted(set(ids(CARDS)) - set(left))}"
h = core.gate_health()
assert (h["verdicts"], h["unreadable"], h["would_drop"]) == (5, 0, 5), f"带着细项的 hold 是读得懂的结论: {h}"

core.RETURN_GATE_DEFAULT, core._gate_clock, core.RETURN_GATE_CHUNK = saved_default, saved_clock, saved_chunk
if saved_env is not None:
    os.environ[core.RETURN_GATE_ENV] = saved_env
use(object())
assert core.CARD_BLOCKING_REASONS == {"withdrawn", "hold", "risk", "efficacy", "unsure"}, \
    "挡卡的原因是这五个; not_clean 不在里面 (D-133 第 1 条, 要加先有 owner 的决定和新 D 号)"
logging.getLogger("flywheel_librarian").disabled = False
print(f"✓ D-151: 回流闸关着和以前一字不差 (不读库); 开着拿掉五种原因的卡、只有 not_clean 的照借; 没结论 / 读不懂 / 读失败不筛; "
      f"10 分钟读一次; 品牌保底; 代码默认现在是{'开' if shipped else '关'}")
print("\ncheck_librarian_shortlist: all checks passed")
