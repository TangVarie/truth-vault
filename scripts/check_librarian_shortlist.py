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

§11 出处帖投过流的卡照借、回包的卡上写明 (D-151 第 13 条, owner 11-12): 不开关, 合并就生效。11-12 复审后重写:
选卡模型看不到这件事 (prompt 不变); 两种写法 (起量在投流窗口里 / 只知道投过流); 读数在后台线程里、失败 60 秒重读、
旧名单 1 小时; 夜跑那盏灯 (check_librarian_traffic.py) 的投流那一段也在这里测 (ci.yml 不许动)。
反证 (11-12 实跑, 36 个都红):
  ㉔ 任务说明里又写了投流 / ㉕ 候选卡上带记号                                                         → 红
  ㉖ 读失败也占 10 分钟 / ㉗ 读成了 60 秒就重读 / ㉘ 旧名单没有期限 (一直回 false) / ㊽ 去掉 10 分钟那一条 → 红
  ㉙ 借阅等读完才回 / ㉚ 读数放回锁里 / ㉛ 没等到的那次读每次借阅都记一笔 / ㉜ 一笔都不记                  → 红
  ㉝ 那一句带「靠」/ ㉞ 都写「投流起量的」/ ㉟ 都写「投过流」/ ㊱ 事件里有行就算起量在窗口里              → 红
  ㊲ 那一句写进缓存行 / ㊳ 回包时原地改 / ㊴ 接在「为何有效」后面 / ㊵ 放进 excerpt                      → 红
  ㊶ 读失败往外抛 / ㊷ 不知道也写 false / ㊸ 外部卡也标 / ㊾ 并到在飞那次上的请求拿没标过的               → 红
  ㊹ 不看 paid_promoted 标记 / ㊺ 不看投流事件 / ㊻ 读标记不带筛选 / ㊼ 只读第一页 / (53) 事件按 note_id 翻页 → 红
  ㊿ dry-run 也去读那两路 / (51) 外部卡算进 lent / (52) labelled 只记最近一次                           → 红
  (54) 夜跑读的不是馆员读的那两路 / (55) 读不到不打 ::warning / (56) 外部卡算进借出去的卡 /
  (57) 缓存读不到当成馆员瞎了 / (58) 读失败往外抛 / (59) 有一路读不到还报占比                           → 红

跑法: cd scripts && python check_librarian_shortlist.py
"""
from __future__ import annotations

import logging
import os
import pathlib
import random
import sys
import threading
import time
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))   # repo 根: 让 librarian 包可导入

from librarian import core  # noqa: E402

# 投流标注 (D-151 第 13 条) 回包前会去读出处帖投过流的那两路 (10 分钟一次)。§1–§10 的假库不认这两路读数, 这里先换成
# 「读到了, 一篇都没有」: 那几节的卡都是 paid_boost=false、一个字不加。§11 换回真的读法, 对着假库逐条测。
REAL_READ_PAID = core._read_paid_source
core._read_paid_source = lambda sb, table, where, cols, order: []


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
assert writes and writes[0][2] is not None, "冷路径结果要进缓存并带 select_ms"
assert [dict(s, paid_boost=False) for s in writes[0][1]] == sel and not any("paid_boost" in s for s in writes[0][1]), \
    "回包 = 进缓存的那份 + paid_boost (没有投流帖时都是 false, 别的一个字不差); 缓存行里不带这个键"
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
         gate_row("B_01", "fail", "not_clean"),                 # 只有 not_clean: 照借 (D-133 第 1 条; owner 11-12 定了照借、卡上写明, §11)
         gate_row("A_03", "pass"),
         gate_row("A_04", None, raw=[None]),                    # 这一行还没分过类
         gate_row("A_05", "fail", raw=["efficacy"]),            # gate_reasons 是字符串: 读不懂 → 留
         gate_row("A_06", "fail", raw=[{"reasons": "efficacy"}]),
         gate_row("A_07", "fail", raw=[{"reasons": [{"name": "efficacy"}]}]),
         gate_row("A_08", "pass", "efficacy"),                  # 类别和原因对不上: 按 pass 留
         gate_row("C_00", "later", "efficacy")]                 # 不认识的类别 → 留
DROPPED = {"A_00", "A_01", "A_02", "B_00", "B_02"}
OFF = (60, dry["library_version"], dry["cache_key"], dry["prompt"])      # §6 算的: 没有闸时的书架、版本串、缓存键、prompt

# ① 开关关着 (代码默认关; 环境变量写 0 / off 也是关): tv_note_links 一次都不读, 书架、版本串、缓存键、prompt 和 §6 一字不差
#    (回包不在这句话里: 第 13 条的投流标注不看开关, 见 §11)
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
    "挡卡的原因是这五个; not_clean 不在里面 (owner 11-12: 投流起量的卡照借、卡上写明, D-151 第 13 条; 要改先有 owner 的决定和新 D 号)"
logging.getLogger("flywheel_librarian").disabled = False
print(f"✓ D-151: 回流闸关着候选 / 版本串 / 缓存键 / prompt 和以前一字不差 (不读 tv_note_links); 开着拿掉五种原因的卡、只有 not_clean 的照借; 没结论 / 读不懂 / 读失败不筛; "
      f"10 分钟读一次; 品牌保底; 代码默认现在是{'开' if shipped else '关'}")

# ══ §11 · 出处帖投过流的卡照借, 回包的卡上写明 (D-151 第 13 条): 只给人看, 选卡模型看不到; 不进缓存, 回包时现加 ═════════
logging.getLogger("flywheel_librarian").disabled = True   # 下面故意让读库失败
core._read_paid_source = REAL_READ_PAID
saved_clock, saved_page, saved_pages = core._gate_clock, core.PAID_BOOST_PAGE, core.PAID_BOOST_MAX_PAGES
saved_wait = core.PAID_BOOST_WAIT_S
saved_shelf_for = core.X.shelf_for
clock = [5000.0]
core._gate_clock = lambda: clock[0]
LINE, PLAIN = core.PAID_BOOST_LINE, core.PAID_BOOSTED_LINE   # 「投流起量的」(起量在投流窗口里) / 「投过流」(只知道投过流)
FLAG_FILTER = ("data_quality_flags->>paid_promoted", "true")
IN_WINDOW = core.PAID_TAKEOFF_IN_WINDOW


class _PaidQ:
    def __init__(self, sb, schema):
        self.sb, self.q = sb, {"schema": schema, "eq": None, "in": None, "range": None, "gte": None, "order": None}

    def table(self, name):
        self.q["table"] = name
        return self

    def select(self, cols):
        self.q["cols"] = cols
        return self

    def eq(self, col, val):
        self.q["eq"] = (col, val)
        return self

    def in_(self, col, vals):
        self.q["in"] = (col, list(vals))
        return self

    def gte(self, col, val):
        self.q["gte"] = (col, val)
        return self

    def order(self, col, **kw):
        self.q["order"] = col
        return self

    def range(self, lo, hi):
        self.q["range"] = (lo, hi)
        return self

    def execute(self):
        return self.sb._run(self.q)


class PaidSB:
    """假库: truth_vault.notes (只回 note_id; 带着 paid_promoted 那个筛选才只回标了的, 不带就整表都回)、
    truth_vault.v_paid_boost_events (一篇可以有几行; 每行带 takeoff_vs_window, 没写的当 missing)、
    truth_vault.flywheel_librarian_cache (夜跑那盏灯数借出去的卡)、autowriter.tv_note_links (回流闸那一读)。记下每个请求。
    stall: {表名: Event} —— 读这张表时卡住, 等 Event 被 set (最多 20 秒)。"""

    def __init__(self, flagged=(), events=(), clean=("A_01", "A_02", "C_00"), gate=(), fail=(), cache=(), stall=None):
        self.notes = {n: True for n in flagged} | {n: False for n in clean}
        self.events = [e if isinstance(e, tuple) else (e, "missing") for e in events]
        self.gate, self.fail, self.calls = {r["note_id"]: r for r in gate}, set(fail), []
        self.cache, self.stall = list(cache), dict(stall or {})

    def schema(self, name):
        return _PaidQ(self, name)

    def _run(self, q):
        self.calls.append((q["schema"], q["table"], q["eq"], q["range"]))
        if q["table"] in self.stall:
            assert self.stall[q["table"]].wait(20), "卡住的那次读没被放行"
        if q["table"] in self.fail:
            raise RuntimeError(f"PostgREST down ({q['table']})")
        if q["table"] == "tv_note_links":
            return types.SimpleNamespace(data=[dict(self.gate[v]) for v in q["in"][1] if v in self.gate])
        assert q["schema"] == "truth_vault", q
        if q["table"] == "flywheel_librarian_cache":
            assert q["cols"] == "selected" and q["gte"][0] == "created_at" and q["in"][0] == "consumer", q
            return types.SimpleNamespace(data=[{"selected": r["selected"]} for r in self.cache
                                               if r["created_at"] >= q["gte"][1] and r["consumer"] in q["in"][1]])
        if q["table"] == "notes":
            assert q["order"] == "note_id", q
            rows = [{"note_id": n} for n in sorted(self.notes) if self.notes[n] or q["eq"] != FLAG_FILTER]
        else:
            assert q["table"] == "v_paid_boost_events" and q["eq"] is None and q["order"] == "event_id", q
            rows = [{"note_id": n, "takeoff_vs_window": tw} for n, tw in self.events]   # 假库里 event_id 的顺序 = 写进来的顺序
        keep = [c.strip() for c in q["cols"].split(",")]
        lo, hi = q["range"]
        return types.SimpleNamespace(data=[{k: r[k] for k in keep} for r in rows[lo:hi + 1]])


def settle():
    """等后台那次读写回 (断言之前叫一下, 读数才是定的)。"""
    t = core._PAID["thread"]
    if t is not None:
        t.join(20)
        assert not t.is_alive(), "后台那次读没结束"


def paid_use(sb):
    """换一个库, 像刚起的进程: 没有上一次读到的投流帖, 计数清零。"""
    settle()
    core.get_supabase = lambda *a, **k: sb
    core._PAID.update(at=None, next=None, flagged=None, events=None, window=None, thread=None, started=0.0, late=None)
    core._PAID["ok_at"] = {"flagged": None, "events": None}
    core.PAID_STATS.update(read_ok=None, read_errors=0, flagged=None, events=None, window=None, lent=0, labelled=0)
    return sb


def paid_reads(sb):
    return [c[1] for c in sb.calls if c[1] != "tv_note_links"]


paid_seen: dict = {}


def paid_llm(*nids):
    def llm(prompt, model, *, system=None, **kw):
        paid_seen["text"] = repr((prompt, system))            # 模型这一次看到的全部文字
        paid_seen["n"] = paid_seen.get("n", 0) + 1
        return pick(*nids)
    return llm


LONG = "长" * 2000                                         # 比摘录上限 (600) 和消费方的 200 字都长
SHELF = [dict(c, raw_excerpt=LONG) if c["source_note_id"] == "B_00" else c for c in CARDS]
core.fetch_candidates = lambda sb, **kw: list(SHELF)
core.get_cache = lambda sb, key: None
writes.clear()

# ⓪ 那两句话本身 (11-12 复审): 一句话只说一遍, 不带「靠」(不做归因); 「投流起量的」是 owner 的原话, 只给记录撑得住的卡,
#    别的卡只说查得到的那一半「投过流」
for line in (LINE, PLAIN):
    assert line.startswith("注意: 这篇") and line.endswith(", 数据不全是内容带来的, 借不借由你判断") and len(line) <= 35 \
        and "靠" not in line and "(" not in line, f"那一句要短、只说一遍、不带「靠」: {line!r}"
assert "是投流起量的" in LINE and "投过流" in PLAIN and "起量" not in PLAIN and LINE != PLAIN, (LINE, PLAIN)

# ① 冷路径。和写作台 priors.is_clean 投流那一半同一批帖: 标了 paid_promoted 的 (A_00)、只在投流事件里的 (B_00, 两行)、
#    两样都有的 (B_01); A_01 两样都没有。起量时间落在投流窗口里的 (B_00: 有一行是 in_window) 写「投流起量的」; 只有标记的
#    (A_00)、事件里没填起量时间的 (B_01) 写「投过流」。回包里 paid_boost=true, 那一句在 why_it_worked 最前面
sb = paid_use(PaidSB(flagged=["A_00", "B_01"], events=[("B_00", "after"), ("B_00", IN_WINDOW), "B_01"]))
core.call_anthropic = paid_llm("B_00", "A_00", "A_01", "B_01")
st = {}
sel = core.librarian_select(BRIEF, _status_out=st)
by = {s["source_note_id"]: s for s in sel}
assert list(by) == ["B_00", "A_00", "A_01", "B_01"] and st["status"] == "ok", "出处帖投过流的卡照借, 一张不少"
assert by["B_00"]["paid_boost"] is True and by["B_00"]["why_it_worked"] == f"{LINE}。w", \
    f"起量时间在投流窗口里: 写「投流起量的」, 原来的「为何有效」接在后面: {by['B_00']['why_it_worked']!r}"
for nid in ("A_00", "B_01"):
    assert by[nid]["paid_boost"] is True and by[nid]["why_it_worked"] == f"{PLAIN}。w", \
        f"{nid}: 只有标记 / 没填起量时间, 只写「投过流」: {by[nid]['why_it_worked']!r}"
assert by["A_01"]["paid_boost"] is False and by["A_01"]["why_it_worked"] == "w", "没有标记、不在事件里的卡: paid_boost=false, 一个字不加"
assert paid_reads(sb) == ["notes", "v_paid_boost_events"] and sb.calls[0][2] == FLAG_FILTER, \
    f"一次读 = 两个请求: 标了 paid_promoted 的帖 (带筛选)、投流事件: {sb.calls}"
# 只给人看: 选卡模型这一次看到的文字里没有这件事, 和书架上一篇投流帖都没有时一字不差, 缓存键也一样 (11-12 复审:
# owner 把判断留给运营; 模型看得到就可能自己绕开这些卡, 那就是藏)
with_paid, key_paid = paid_seen["text"], writes[-1][0]
assert "投流" not in with_paid and "投过流" not in with_paid and "投流" not in core.ROLE_TASK_INSTR, \
    "给选卡模型的候选和任务说明里不该有投流这件事"
assert with_paid.count("\\n[") == 24, "候选还是 24 张"
paid_use(PaidSB())
core.librarian_select(BRIEF)
assert paid_seen["text"] == with_paid and writes[-1][0] == key_paid, "书架上有没有投过流的帖, 给模型的文字和缓存键都一样"
sb = paid_use(sb)
sb.calls.clear()
sel = core.librarian_select(BRIEF)
by = {s["source_note_id"]: s for s in sel}
# 不进缓存: 缓存行里没有 paid_boost, why_it_worked 是原来的
cached_row = writes[-1][1]
assert [c["source_note_id"] for c in cached_row] == list(by) and not any("paid_boost" in c for c in cached_row) \
    and all(c["why_it_worked"] == "w" for c in cached_row), "进缓存的卡不带那一句 (回包时现加)"
# 那一句不在摘录里: 摘录回包截到 600 字、消费方再截 200 字, 那一句整句都在别的字段上
assert len(by["B_00"]["excerpt"]) == core.X.EXCERPT_CAP == 600 and LINE not in by["B_00"]["excerpt"], "摘录照旧截到 600 字"
DESK_FIELDS = ("hook_type", "structure", "why_it_worked", "transferable_tactic", "borrow_what", "why_relevant")
desk_text = "\n".join(str(by["B_00"][k]) for k in DESK_FIELDS) + "\n" + by["B_00"]["excerpt"][:200]
assert LINE in desk_text, "消费方只渲染认得的那六个字段 + 200 字摘录 (aw memory.render_flywheel_block) 时, 那一句也整句在"
h = core.paid_health()
assert h == {"read_age_s": 0, "read_ok": True, "read_errors": 0, "flagged": 2, "events": 2, "window": 1,
             "lent": 4, "labelled": 3}, h
assert all(x is None or isinstance(x, (bool, int)) for x in h.values()), "/health 里只有布尔、整数和 None"
core.librarian_select(BRIEF)
h = core.paid_health()
assert (h["lent"], h["labelled"]) == (8, 6) and len(sb.calls) == 2, "lent / labelled 是累计的 (不是只记最近一次); 10 分钟内不重读"
assert paid_seen["text"] == with_paid and "投流" not in core.librarian_select(BRIEF, dry_run=True)["prompt"], \
    "那批帖已经读在手上的时候再选一次 (冷路径、dry-run): 给模型的文字还是一字不差, 没有投流这件事"
# dry-run (诊断) 的 prompt 和生产冷路径一样不带; 诊断不回卡, 也就不去读那两路
fresh_sb = paid_use(PaidSB(flagged=["A_00"], events=[("B_00", IN_WINDOW)]))
dry = core.librarian_select(BRIEF, dry_run=True)
assert "投流" not in dry["prompt"] and dry["cache_key"] == key_paid and not fresh_sb.calls, "dry-run: prompt 不带, 不读那两路"
assert (core.PAID_BOOST_TTL_S, core.PAID_BOOST_RETRY_S, core.PAID_BOOST_STALE_S) == (600, 60, 3600) \
    and 0 < core.PAID_BOOST_WAIT_S <= 5, "读成了 10 分钟不重读; 读失败 60 秒后重读; 1 小时没读成新的不再说「不是」; 回包最多等几秒"
assert [(n, t, w) for n, t, w, _, _ in core._PAID_SOURCES] == \
    [("flagged", "notes", FLAG_FILTER), ("events", "v_paid_boost_events", None)], \
    "只看 TV 自己的两样: paid_promoted 标记、投流事件 (铺评工单是另一回事, 不在这条里)"

# ② 命中缓存: 这次改动之前写的缓存行 (没有 paid_boost、没有 external 键) 回包时现加那一句, 不调模型、不改缓存键;
#    新认出来的投流帖过了 10 分钟就标上, 还是同一行缓存
sb = paid_use(PaidSB(flagged=["A_00", "B_01"], events=[("B_00", IN_WINDOW), "B_01"]))
OLD_ROW = [{"source_note_id": "B_00", "why_relevant": "同品牌", "borrow_what": "借钩子", "tier": "爆", "synthetic": False,
            "hook_type": "h", "structure": "s", "why_it_worked": "w", "transferable_tactic": "t", "excerpt": "e"},
           {"source_note_id": "A_01", "why_relevant": "跨主题", "borrow_what": "借结构", "tier": "爆", "synthetic": False,
            "hook_type": "h", "structure": "s", "why_it_worked": "w", "transferable_tactic": "t", "excerpt": "e"},
           {"source_note_id": "A_02", "why_relevant": "没策展的卡", "borrow_what": "借结构", "why_it_worked": None}]
key_before = core.librarian_select(BRIEF, dry_run=True)["cache_key"]
core.get_cache = lambda sb, key: [dict(c) for c in OLD_ROW] if key == key_before else None
paid_seen["n"] = 0
writes.clear()
hit = core.librarian_select(BRIEF)
assert [(c["source_note_id"], c["paid_boost"]) for c in hit] == [("B_00", True), ("A_01", False), ("A_02", False)] \
    and hit[0]["why_it_worked"] == f"{LINE}。w" and hit[1]["why_it_worked"] == "w", \
    f"以前写的缓存行回包时也要带那一句: {[(c['source_note_id'], c.get('paid_boost')) for c in hit]}"
assert paid_seen["n"] == 0 and not writes and len(sb.calls) == 2, "命中缓存: 不调模型、不重写缓存; 那两路读一次"
sb.events.append(("A_01", "missing"))                     # 今晚的同步新认出一篇投流帖 (没填起量时间)
sb.notes["A_02"] = True                                   # 另一篇新标了 paid_promoted (这张卡没策展, why_it_worked 是空的)
assert [c["paid_boost"] for c in core.librarian_select(BRIEF)] == [True, False, False] and len(sb.calls) == 2, \
    "10 分钟内用的还是上一次读到的, 不重读"
clock[0] += core.PAID_BOOST_TTL_S + 1
hit = core.librarian_select(BRIEF)
assert [c["paid_boost"] for c in hit] == [True, True, True] and hit[1]["why_it_worked"] == f"{PLAIN}。w" \
    and hit[2]["why_it_worked"] == PLAIN, "新认出来的投流帖过了 10 分钟就标上; 原来没有「为何有效」的卡就只有那一句"
assert core.librarian_select(BRIEF, dry_run=True)["cache_key"] == key_before and paid_seen["n"] == 0 and len(sb.calls) == 4, \
    "投流帖多了一篇: 缓存键不变 (书架没动), 还是命中那一行、不调模型"
assert OLD_ROW[0]["why_it_worked"] == "w" and "paid_boost" not in OLD_ROW[0]

# ③ 读失败: 一次都没读成过 → 卡照常借出去、不带那一句, paid_boost 是 null, 计数加; 不往借阅里抛。
#    失败之后 60 秒重读 (11-12 复审: 原来失败也占 10 分钟, 刚部署的进程第一次读失败, 投过流的卡要不带那一句地借 10 分钟)
core.get_cache = lambda sb, key: None
sb = paid_use(PaidSB(flagged=["A_00"], events=[("B_00", IN_WINDOW)], fail=["notes", "v_paid_boost_events"]))
core.call_anthropic = paid_llm("B_00", "A_00", "A_01")
st = {}
sel = core.librarian_select(BRIEF, _status_out=st)
assert [s["source_note_id"] for s in sel] == ["B_00", "A_00", "A_01"] and st["status"] == "ok", "读投流帖失败不影响借阅"
assert all(s["paid_boost"] is None and s["why_it_worked"] == "w" for s in sel), \
    "一次都没读成过: 卡上不写那一句, paid_boost 是 null (不知道), 不是 false"
h = core.paid_health()
assert (h["read_ok"], h["read_errors"], h["flagged"], h["events"], h["lent"], h["labelled"]) == (False, 2, None, None, 3, 0), h
clock[0] += core.PAID_BOOST_RETRY_S - 1
core.librarian_select(BRIEF)
assert len(sb.calls) == 2 and core.paid_health()["read_errors"] == 2, "失败之后 60 秒内不再去撞库"
sb.fail.clear()                                           # 库好了: 失败之后过 60 秒 (不是 10 分钟) 就读到, 那一句回来
clock[0] += 2
sel = core.librarian_select(BRIEF)
assert [s["paid_boost"] for s in sel] == [True, True, False] and core.paid_health()["read_ok"] is True \
    and sel[0]["why_it_worked"] == f"{LINE}。w" and sel[1]["why_it_worked"] == f"{PLAIN}。w", \
    f"读失败 60 秒后重读, 读到就标上: {[s['paid_boost'] for s in sel]}"
clock[0] += core.PAID_BOOST_RETRY_S + 1
core.librarian_select(BRIEF)
assert len(sb.calls) == 4, "读成之后是 10 分钟不重读, 不是 60 秒"
# 两路各记各的: 之后事件那一路挂了 → 沿用它上一次读成的那份 (B_00 还标着、还是「投流起量的」), 标记那一路照常读到新的;
# 事件那一路上次读成还在 1 小时内, 不在两份里的卡还算「不是」(false)
core.call_anthropic = paid_llm("B_00", "A_01", "A_02")
sb.fail.add("v_paid_boost_events")
sb.notes["A_01"] = True
clock[0] += core.PAID_BOOST_TTL_S
sel = core.librarian_select(BRIEF)
assert [s["paid_boost"] for s in sel] == [True, True, False] and sel[0]["why_it_worked"] == f"{LINE}。w", \
    f"一路读失败: 沿用它上一次读成的, 另一路照常: {[s['paid_boost'] for s in sel]}"
h = core.paid_health()
assert (h["read_ok"], h["read_errors"], h["flagged"], h["events"], h["window"]) == (False, 3, 2, 1, 1), h
n_calls = len(sb.calls)
clock[0] += core.PAID_BOOST_RETRY_S + 1
core.librarian_select(BRIEF)
assert len(sb.calls) == n_calls + 2, "有一路失败: 60 秒后两路都重读"
# 那一路一直读不到, 上次读成已经是 1 小时以前: 在旧名单里的帖照标, 不在的不再说「不是」, 是不知道 (null) ——
# 这期间新投的帖不在旧名单里 (11-12 复审: 原来旧名单没有期限, 一直回 false)
clock[0] += core.PAID_BOOST_STALE_S
sel = core.librarian_select(BRIEF)
assert [s["paid_boost"] for s in sel] == [True, True, None] and sel[0]["why_it_worked"] == f"{LINE}。w", \
    f"旧名单过了 1 小时: 在里面的照标, 不在的是 null: {[s['paid_boost'] for s in sel]}"
sb.fail.clear()
clock[0] += core.PAID_BOOST_RETRY_S + 1
assert [s["paid_boost"] for s in core.librarian_select(BRIEF)] == [True, True, False], "读成了: 又能说「不是」"
# 事件那一路从来没读成过 (视图不在): 标了 paid_promoted 的照样写明; 别的卡是不知道 (null), 不是 false
core.call_anthropic = paid_llm("B_00", "A_00", "A_01")
sb = paid_use(PaidSB(flagged=["A_00"], events=[("B_00", IN_WINDOW)], fail=["v_paid_boost_events"]))
sel = core.librarian_select(BRIEF)
assert [s["paid_boost"] for s in sel] == [None, True, None] and sel[1]["why_it_worked"] == f"{PLAIN}。w", \
    f"一路从来没读成过: 读成的那一路照标, 别的卡不知道: {[s['paid_boost'] for s in sel]}"
paid_use(object())                                        # 连 .schema 都没有的库
assert [s["paid_boost"] for s in core.librarian_select(BRIEF)] == [None, None, None], "库对象不对也不许抛进借阅"

# ③b 读卡住 (视图慢 / 超时; supabase 客户端默认 120 秒): 借阅最多等 PAID_BOOST_WAIT_S, 不等它读完; 读在后台线程里,
#     不占着锁, 同时到的借阅不排队、不另起一次读; 读完自己写回 (11-12 复审: 原来两路读数在锁里做, 每次借阅都排在后面)
core.PAID_BOOST_WAIT_S = 0.05
go = threading.Event()
sb = paid_use(PaidSB(flagged=["A_00"], events=[("B_00", IN_WINDOW)], stall={"v_paid_boost_events": go}))
t0 = time.monotonic()
sel = core.librarian_select(BRIEF)
took = time.monotonic() - t0
assert took < 5 and [s["paid_boost"] for s in sel] == [None, None, None], f"读卡住: 借阅只等 {core.PAID_BOOST_WAIT_S} 秒就回 ({took:.1f}s)"
h = core.paid_health()
assert (h["read_ok"], h["read_errors"]) == (False, 1), f"没等到要记一笔: {h}"
assert core._PAID_LOCK.acquire(timeout=1), "读还卡着的时候锁不该被占着"
core._PAID_LOCK.release()
t0 = time.monotonic()
core.librarian_select(BRIEF)
assert time.monotonic() - t0 < 5 and paid_reads(sb) == ["notes", "v_paid_boost_events"] \
    and core.paid_health()["read_errors"] == 1, "读还卡着: 后到的借阅不等、不另起一次读, 同一次读只记一笔"
go.set()
settle()
sel = core.librarian_select(BRIEF)
assert [s["paid_boost"] for s in sel] == [True, True, False] and core.paid_health()["read_ok"] is True \
    and len(sb.calls) == 2, "卡住的那次读完自己写回, 下一次借阅就标上, 不用重读"
go.clear()                                                # 手上有上一次读成的: 再卡住, 借阅照样很快回, 用手上那份
clock[0] += core.PAID_BOOST_TTL_S + 1
t0 = time.monotonic()
sel = core.librarian_select(BRIEF)
assert time.monotonic() - t0 < 5 and [s["paid_boost"] for s in sel] == [True, True, False], "手上有上一次读成的: 不等, 照标"
go.set()
settle()
core.PAID_BOOST_WAIT_S = saved_wait

# ④ 外部卡从不标 (别家的帖, 不归这条管): 就算它的 id 出现在投流帖里, 回包也不带那一句
EXT = {"source_note_id": "ext:E1", "external": True, "category": "不在保底品类里", "comments": 90, "masked": True,
       "raw_excerpt": "别家的帖", "structure": "先问后答", "why_it_worked": "抓到时每天 30 条评论", "rank_score": 0.5}
core.X.shelf_for = lambda sb, brief, **kw: [dict(EXT)]
sb = paid_use(PaidSB(flagged=["ext:E1", "E1"], events=["ext:E1", "B_00"]))
core.call_anthropic = paid_llm("ext:E1", "B_00")
sel = core.librarian_select(dict(BRIEF, explore=False))
assert [(s["source_note_id"], s["external"], s["paid_boost"]) for s in sel] == [("ext:E1", True, False), ("B_00", False, True)], sel
assert sel[0]["why_it_worked"] == EXT["why_it_worked"] and sel[1]["why_it_worked"] == f"{PLAIN}。w" \
    and (core.paid_health()["lent"], core.paid_health()["labelled"]) == (1, 1), "外部卡: 回包不带那一句, 也不算进 lent"
core.get_cache = lambda sb, key: [dict(core._enrich(EXT, "r", "b")), dict(OLD_ROW[0])]    # 命中缓存的外部卡也一样
hit = core.librarian_select(dict(BRIEF, explore=False))
assert [(c["external"], c["paid_boost"]) for c in hit] == [(True, False), (False, True)] \
    and hit[0]["why_it_worked"] == EXT["why_it_worked"], hit
core.X.shelf_for = saved_shelf_for
core.get_cache = lambda sb, key: None

# ⑤ 和回流闸没关系: 闸关着不读那四列; 闸开着, 只有 not_clean 的卡照借、照标; 被闸拿掉的卡不会因为投流回来; 020 没跑一样标
saved_env = os.environ.pop(core.RETURN_GATE_ENV, None)
saved_default = core.RETURN_GATE_DEFAULT
core.RETURN_GATE_DEFAULT = False
rows = [gate_row("B_01", "fail", "not_clean"), gate_row("A_00", "withdrawn", "withdrawn")]
sb = paid_use(use(PaidSB(flagged=["A_00", "B_01"], events=["B_00"], gate=rows)))
core.call_anthropic = paid_llm("B_00", "B_01", "A_00")
assert [(s["source_note_id"], s["paid_boost"]) for s in core.librarian_select(BRIEF)] == \
    [("B_00", True), ("B_01", True), ("A_00", True)] and "tv_note_links" not in [c[1] for c in sb.calls], \
    "闸关着: 一次都不读 tv_note_links, 那一句照样有 (只看 TV 自己的数)"
core.RETURN_GATE_DEFAULT = True
sb = paid_use(use(PaidSB(flagged=["A_00", "B_01"], events=["B_00"], gate=rows)))
assert [(s["source_note_id"], s["paid_boost"]) for s in core.librarian_select(BRIEF)] == [("B_00", True), ("B_01", True)], \
    "闸开着: 只有 not_clean 的卡照借、照标 (没有对账行的 B_00 也标); 已删的帖的卡照旧拿掉"
sb = paid_use(use(PaidSB(flagged=["B_01"], events=["B_00"], fail=["tv_note_links"])))
assert [s["paid_boost"] for s in core.librarian_select(BRIEF)] == [True, True, False], "闸读不到 (020 没跑 / 库挂了) 一样标"
core.RETURN_GATE_DEFAULT = saved_default
if saved_env is not None:
    os.environ[core.RETURN_GATE_ENV] = saved_env
use(object())

# ⑥ 并到在飞的那次上的请求拿到的也是标过的 (AU-F09)
sb = paid_use(PaidSB(flagged=["B_00"]))
core._board = spy_board
gate, calls, out, threads = race(lambda: pick("B_00", "A_01"))
finish(gate, threads)
core._board = real_board
assert len(calls) == 1 and out["second"][0] == out["first"][0] and \
    [(s["paid_boost"], s["why_it_worked"]) for s in out["second"][0]] == [(True, f"{PLAIN}。w"), (False, "w")], out

# ⑦ 翻页: 一页读满就接着读 (事件按 event_id 排; 后面那一页上的 in_window 也算); 页数到顶就用读到的, 不抛
core.PAID_BOOST_PAGE = 2
sb = paid_use(PaidSB(events=["A_00", "A_01", "A_02", "B_00", ("A_00", IN_WINDOW)]))
assert core._paid_boosted(sb) == (frozenset({"A_00", "A_01", "A_02", "B_00"}), frozenset({"A_00"}), True) and \
    [c[3] for c in sb.calls if c[1] == "v_paid_boost_events"] == [(0, 1), (2, 3), (4, 5)], sb.calls
core.PAID_BOOST_MAX_PAGES = 2
sb = paid_use(PaidSB(events=["A_00", "A_01", "A_02", "B_00", "B_01"]))
assert core._paid_boosted(sb).ids == {"A_00", "A_01", "A_02", "B_00"} and core.paid_health()["read_ok"] is True, \
    "页数到顶: 用读到的这些"
core.PAID_BOOST_PAGE, core.PAID_BOOST_MAX_PAGES = saved_page, saved_pages

# ⑧ 夜跑那盏灯 (check_librarian_traffic.py) 的投流那一段: 馆员读的那两路夜里照样读一遍, 读不到 → ::warning (馆员那头读不到时
#    卡照常借出去、借卡返回 ok, 别处都不红); 近 7 天借给写作台的内部卡里投过流的占几成, 和 11-12 的基线并排印 (只印不判)
import contextlib  # noqa: E402
import io  # noqa: E402

import check_librarian_traffic as T  # noqa: E402

assert [(n, t, w) for n, t, w, _ in T.PAID_SOURCES] == [(n, t, w) for n, t, w, _, _ in core._PAID_SOURCES] \
    and [o for *_, o in T.PAID_SOURCES] == [o for *_, o in core._PAID_SOURCES], "夜跑读的那两路要和馆员读的是同一个表 / 视图、同一个筛选"
assert T.PAID_BASELINE == (52, 165), "11-12 的基线: 165 张内部卡里 52 张 (D-151 第 13 条)"
CACHE_ROWS = [
    {"consumer": "deskcore", "created_at": "2026-11-10T00:00:00",
     "selected": [{"source_note_id": "B_00"}, {"source_note_id": "A_01"}, {"source_note_id": "ext:E1", "external": True}]},
    {"consumer": "autowriter", "created_at": "2026-11-11T00:00:00",
     "selected": [{"source_note_id": "A_00"}, {"source_note_id": "ext:E2"}, "不是卡", {"source_note_id": "C_00"}]},
    {"consumer": "deskcore", "created_at": "2026-11-11T00:00:00", "selected": []},          # 作废过的行 (D-126)
    {"consumer": "deskcore", "created_at": "2026-11-01T00:00:00", "selected": [{"source_note_id": "B_00"}]},   # 7 天以前
    {"consumer": "sanshengliubu", "created_at": "2026-11-11T00:00:00", "selected": [{"source_note_id": "B_00"}]},  # 不是写作台
]


def paid_report(sb, gha=False):
    buf, old = io.StringIO(), os.environ.pop("GITHUB_ACTIONS", None)
    if gha:
        os.environ["GITHUB_ACTIONS"] = "true"
    try:
        with contextlib.redirect_stdout(buf):
            p = T.gather_paid(sb, "2026-11-05T00:00:00")
            blind = T.report_paid(p)
    finally:
        os.environ.pop("GITHUB_ACTIONS", None)
        if old is not None:
            os.environ["GITHUB_ACTIONS"] = old
    return p, blind, buf.getvalue()


p, blind, text = paid_report(PaidSB(flagged=["A_00"], events=["B_00", "B_00"], cache=CACHE_ROWS), gha=True)
assert (p["flagged"], p["events"], p["rows"], p["lent"], p["lent_paid"], p["errors"]) == (1, 1, 3, 4, 2, []), p
assert blind is False and "::warning" not in text and "内部卡 4 张" in text and "投过流的 2 张 (50%)" in text \
    and "52 / 165 = 32%" in text, text
p, blind, text = paid_report(PaidSB(flagged=["A_00"], events=["B_00"], cache=CACHE_ROWS, fail=["v_paid_boost_events"]), gha=True)
assert blind is True and p["events"] is None and p["errors"] == [("events", "RuntimeError")] and "::warning" in text \
    and "v_paid_boost_events" in text and "数不出" in text and "%" not in text.split("近 7 天")[1].split("\n")[0], \
    f"有一路读不到: 打 ::warning, 不报一个算不准的占比: {text}"
assert "::warning" not in paid_report(PaidSB(fail=["notes"]))[2], "不在 GHA 里不打 ::warning (只印 ⚠)"
p, blind, text = paid_report(PaidSB(flagged=["A_00"], fail=["flywheel_librarian_cache"]), gha=True)
assert blind is False and p["lent"] is None and "::warning" not in text and "没有数" in text, "缓存读不到: 说没有数, 不当成馆员瞎了"
p, blind, text = paid_report(PaidSB(flagged=["A_00"]), gha=True)
assert blind is False and p["lent"] == 0 and "无从比" in text, "7 天里没有借卡: 不除零, 不报占比"
p, blind, text = paid_report(object(), gha=True)
assert blind is True and len(p["errors"]) == 3 and text.count("::warning") == 1, "库对象不对: 不抛, 当两路都读不到"

core._gate_clock = saved_clock
paid_use(object())
logging.getLogger("flywheel_librarian").disabled = False
print("✓ D-151 第 13 条: 出处帖投过流的卡照借, 回包的卡上写明 (起量在投流窗口里写「投流起量的」, 其余写「投过流」; 标记 ∪ 投流事件, "
      "和写作台同一批帖); 选卡模型看不到, prompt 和缓存键不变; 不进缓存, 以前的缓存行回包时现加; 读失败不标、不挡借阅、记数、"
      "60 秒后重读; 读卡住不堵借阅; 旧名单过 1 小时不再说「不是」; 外部卡不标; 和回流闸的开关无关; 夜跑那盏灯照读那两路")
print("\ncheck_librarian_shortlist: all checks passed")
