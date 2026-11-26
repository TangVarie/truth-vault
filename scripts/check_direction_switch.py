#!/usr/bin/env python3
"""方向从抬得了变成抬不了 (I-17, 2026-11-25): 款式标忽略、清人群 / 痛点 / 产品焦点、content_format 换回 essence 的值。

断行为不断源码 (D-051): §1–§4、§6 用真 mapping 跑 transform_row / 纯函数; §5 用假库跑 restore_content_format;
§7 比 v1_33 的两张小表和 mapping; 只有 §8 (接线位置) 读源码。

  §1 Step 0: BJS_phase2 的 成人款 / 儿童款 查表和判层前去掉。「提问贴, 成人款」照常按 提问贴 抬、层 Q;
     「精品贴, 成人款」层 J、什么都不抬。没配 direction_ignore_tokens 的 mapping 查表键一字不变。
  §2 抬得了 → 抬不了 (只剩款式标 / mapping 里没有 / 只登记了 layer): 人群 / 痛点 / 产品焦点送 None (键在、值空),
     content_format 不送 (留给 §5)。
  §3 不碰: NUC 的子方向 (essence 管) 三个键都不出现、不进 content_format 恢复的候选; 带忽略标的子方向,
     essence 查子方向和 sync 用同一个去掉忽略标的键; 正文推断出来的方向照常抬; 抬得了的方向照常抬。
  §4 方向格清空: 方向列这一轮还在 → 三列送 None; 方向列整轮没返回 (改名) → 什么都不动。
  §5 content_format: 库里上一次的方向抬得了、库里正好是它抬的值 → 换成 audit_log 里 essence 最后一次写的值;
     essence 那一次没改 content_format → 不换、打本轮旗子 (这一轮没写旗子列就不打); 读库 / 读 audit_log 失败 → 一篇不动,
     回 held (读库失败 = 全部候选, 读 audit_log 失败 = 要换的那几篇); dry-run 不读库; 上一次也抬不了 / 库里不是旧方向的值 /
     新篇 → 不读 audit_log。
  §6 HATHERINE 9 月下旬起的 10 个新方向名都登记了 (只有 layer): 送 None、层照前缀。
  §7 schemas/notes_v1_33 里「哪些方向抬得了」「哪些标要忽略」两张小表和 mapping 逐条一致; 忽略标不能同时是方向。
  §8 接线: 清空 / 恢复在 upsert 之前; content_format_not_restored 是本轮旗子 (以库里旗子为底时剥掉)。
  §9 读失败留着 raw_extra、下一轮照常换回 (Codex #312 P2): 真 postgrest-py 发请求 (check_batch_upsert_columns 的假 HTTP),
     按 PostgREST 的 columns= 落进一个字典库, 连跑两晚。第一晚读 audit_log / 读库失败 → held 的篇这一轮请求里没有 raw_extra
     (columns= 里也没有, 逐行兜底也没有)、库里留着上一次的方向, 三列照样清、别的列照写; 第二晚读得到 → 换回 essence 的值。
     读 audit_log 失败只留要换的篇 (新篇、抬得了的篇照写); 读库失败全部候选都留。留列的篇先整行 INSERT ... ON CONFLICT
     DO NOTHING: 库里还没有的新篇带着 raw_extra 落库、不再发第二遍 (同一晚 essence 的 prompt 里有它的方向), 库里已有的不动;
     这一步也按名单列分组 (D-122)、批被拒逐行插; 全插不成 → 退回去掉 raw_extra 的那一份, 新篇这一晚 raw_extra 是 NULL,
     essence 照 PostgREST 的取数形状 (键在、值 None) 拼 prompt 不许抛。读得到时 hold 是空的、请求和不带 hold 一字不差。
     再驱动真的 main() 两晚: 第一晚 Done 行 content_format_restore_held、errors 1、退出码 1、::error、新篇 raw_extra 在;
     第二晚换回、绿; dry-run 不读库、不发请求、绿。

反证 (改坏之后必须变红):
  ① 去掉 BJS_phase2 的 direction_ignore_tokens       → §1 红 (本文件 §1 末尾实跑)
  ② transform_row 不管子方向也清                     → §3 「NUC 三个键都不出现」红
  ③ restore 不看「库里是不是旧方向的值」             → §5 「库里已是 essence 的值」那条红
  ④ v1_33 少写一个抬得了的方向                       → §7 红
  ⑤ essence 查子方向不去掉忽略标 / restore 候选不跳过子方向 → §3 红
  ⑥ 不留 raw_extra (hold 传 None, 就是 Codex 说的那件事)    → §9 第二晚换不回来, 红 (本文件 §9 实跑)
  读失败不回 held / 读 audit_log 失败留全部候选 / upsert 不认 hold、分组不按 hold 分、补 None 补到 raw_extra、
  逐行兜底发原行 / main 不传 hold、不计 error、不记 Done 键 → §9 红 (改文件跑过, 结果记在 TV#312 的 PR 说明里)
  不先插新篇 / 先插那一步用 merge / 插进去的再发一遍 / 先插不按名单列分组 / 先插没有逐行兜底 / 不看回包按整组算 /
  essence 读 raw_extra 不防 NULL → §9 红 (同上)

跑法: cd scripts && python check_direction_switch.py
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import logging
import os
import re
import sys
from pathlib import Path

import _common as c
import sync_feishu_notes_to_truth_vault as engine

ROOT = Path(__file__).resolve().parent.parent
CLEAR = engine._PROFILE_CLEAR_COLS
BJS2 = c.load_mapping("BJS_phase2")


def _tr(mapping: dict, fields: dict, rid: str = "r1") -> dict:
    note, _, _ = engine.transform_row(mapping, rid, {"笔记内容": "正文", "文案": "正文", **fields})
    return note


# ── §1 Step 0: 款式标忽略 ────────────────────────────────────────────────────
def check_ignore_tokens() -> None:
    n = _tr(BJS2, {"方向": ["提问贴", "成人款"]})
    want = BJS2["direction_decomposition"]["提问贴"]
    assert n.get("content_format") == want["content_format"] and n.get("target_audience") == want["target_audience"] \
        and n.get("user_pain_point") == want["user_pain_point"], f"§1 「提问贴, 成人款」该按 提问贴 抬: {n}"
    assert n.get("content_layer") == "Q", n.get("content_layer")
    assert n["raw_extra"]["_direction_raw"] == ["提问贴", "成人款"], "§1 方向原值照存"
    n = _tr(BJS2, {"方向": ["精品贴", "成人款"]})
    assert n.get("content_layer") == "J" and "content_format" not in n, n
    assert all(k in n and n[k] is None for k in CLEAR), f"§1 精品贴只登记了 layer, 三列送 None: {n}"
    assert c.effective_direction_key(["提问贴", "儿童款"], BJS2) == "提问贴"
    assert c.effective_direction_key(["成人款"], BJS2) == ""
    tuge = c.load_mapping("TUGE_phase1")
    for raw in (["要不要找机构", "客资可能"], "提问贴", ["a"], [{"text": "x"}, "y"]):
        assert c.effective_direction_key(raw, tuge) == c._direction_key(raw), f"§1 没配忽略标的 mapping 键要一字不变: {raw!r}"
    # 反证 ①: 去掉忽略标 → 「提问贴, 成人款」查不到、层 NULL
    m = copy.deepcopy(BJS2)
    m.pop("direction_ignore_tokens")
    n = _tr(m, {"方向": ["提问贴", "成人款"]})
    assert "content_format" not in n and n.get("content_layer") is None, "§1 反证没变红"
    print("  §1 款式标忽略: 「提问贴, 成人款」按提问贴抬、层 Q; 「精品贴, 成人款」层 J 不抬; 别的 mapping 键不变; 去掉就变红 (反证) ✓")


# ── §2 抬不了 → 三列送 None ──────────────────────────────────────────────────
def check_unliftable_clears() -> None:
    for raw in (["成人款"], ["儿童款"], ["成人款", "儿童款"], ["没登记的方向"]):
        n = _tr(BJS2, {"方向": raw})
        assert all(k in n and n[k] is None for k in CLEAR), f"§2 {raw}: 三列要送 None: {n}"
        assert "content_format" not in n, f"§2 {raw}: content_format 不在这里送 (留给 restore_content_format)"
    n = _tr(BJS2, {"方向": ["成人款"]})
    assert n.get("content_layer") is None, n.get("content_layer")
    print("  §2 只剩款式标 / 没登记的方向: 人群 / 痛点 / 产品焦点送 None, content_format 不送, 层 NULL ✓")


# ── §3 不碰的 ──────────────────────────────────────────────────────────────
def check_untouched() -> None:
    nuc = c.load_mapping("NUC_phase1")
    sub = next(k for k, v in nuc["direction_decomposition"].items() if isinstance(v, dict) and "sub_directions" in v)
    n = _tr(nuc, {"方向": sub})
    assert not any(k in n for k in CLEAR), f"§3 子方向归 essence, 三个键都不该出现: {[k for k in CLEAR if k in n]}"
    xiwu = c.load_mapping("XIWU_phase1")
    n = _tr(xiwu, {"方向": "已发布", "笔记内容": "西屋 GT33 用了一个月, 厨房终于清爽了"})
    assert n["raw_extra"].get("_direction_inferred"), "§3 前提: 这一条要走正文推断"
    lifted = xiwu["direction_decomposition"][n["raw_extra"]["_direction_inferred"]["direction"]]
    assert n.get("target_audience") == lifted.get("target_audience") and n.get("target_audience") is not None, \
        f"§3 正文推断的方向照常抬, 不送 None: {n.get('target_audience')!r}"
    spx = c.load_mapping("SPX_phase1")
    n = _tr(spx, {"方向": "提问贴"})
    assert n.get("target_audience") is not None and n.get("content_format") is not None, "§3 抬得了的方向照常抬"
    # 子方向不是 content_format 恢复的候选 (essence 管, restore 不读库)
    n = _tr(nuc, {"方向": sub}, rid="s0")
    n["note_id"] = "s0"
    assert engine.plan_content_format_restore(nuc, [n], {"方向"}) == [], "§3 子方向的篇不该进 content_format 恢复的候选"
    # 子方向 + 忽略标 (今天没有这样的表: BJS_phase2 没有子方向; 以后有了也要对): essence 查子方向用去掉忽略标的键, 和 sync 同一个键
    import annotate_essence_pass as E
    nuc_ign = copy.deepcopy(nuc)
    nuc_ign["direction_ignore_tokens"] = ["成人款"]
    assert "成人款" not in nuc_ign["direction_decomposition"]
    got = E.get_sub_directions_for_note(nuc_ign, {"raw_extra": {"_direction_raw": [sub, "成人款"]}})
    assert got is not None and got[0] == sub, f"§3 essence 查子方向要先去掉忽略标: {got!r}"
    n = _tr(nuc_ign, {"方向": [sub, "成人款"]}, rid="s1")
    n["note_id"] = "s1"
    assert not any(k in n for k in CLEAR), "§3 子方向 + 忽略标: sync 也认成子方向, 三个键都不出现"
    assert engine.plan_content_format_restore(nuc_ign, [n], {"方向"}) == [], "§3 子方向 + 忽略标也不是恢复的候选"
    print("  §3 子方向三个键都不出现、不进 content_format 恢复 (带忽略标也一样, essence 用同一个键); 正文推断 / 抬得了的方向照常抬 ✓")


# ── §4 方向格清空 ───────────────────────────────────────────────────────────
def check_cleared_cell() -> None:
    notes = [{"note_id": "a", "raw_extra": {}}, {"note_id": "b", "raw_extra": {"_direction_raw": ["提问贴"]}},
             {"note_id": "c", "raw_extra": {}, "target_audience": ["x"]}]
    got = engine.apply_cleared_direction(BJS2, copy.deepcopy(notes), seen_cols={"笔记内容"})
    assert got == 0, "§4 方向列整轮没返回 (改名) → 不动"
    ns = copy.deepcopy(notes)
    got = engine.apply_cleared_direction(BJS2, ns, seen_cols={"方向", "笔记内容"})
    assert got == 2 and all(ns[0][k] is None for k in CLEAR), f"§4 方向格清空、方向列还在 → 送 None: {ns[0]}"
    assert not any(k in ns[1] for k in CLEAR), "§4 有方向的篇不在这里管"
    assert ns[2]["target_audience"] == ["x"], "§4 这一轮已经带了的值不覆盖"
    print("  §4 方向格清空: 方向列还在 → 送 None; 整轮没返回 (改名) → 不动 ✓")


# ── §5 content_format 换回 essence 的值 ───────────────────────────────────────
class _FakeSB:
    """只认两种读: notes 的 (note_id, content_format, raw_extra->_direction_raw) 和 audit_log 的 essence 行。"""

    def __init__(self, stored: dict, audit: list[dict], fail: str = ""):
        self.stored, self.audit, self.fail = stored, audit, fail
        self.reads: list[str] = []
        self._t = None

    def schema(self, *_):
        return self

    def table(self, t):
        self._t = t
        return self

    def select(self, *_):
        return self

    def eq(self, *_):
        return self

    def in_(self, _c, ids):
        self._ids = list(ids)
        return self

    @property
    def not_(self):
        return self

    def is_(self, *_):
        return self


def _fake_fetch(q, page_size=1000, order_by=None):
    q.reads.append(q._t)
    if q.fail == q._t:
        raise RuntimeError("库挂了")
    if q._t == "notes":
        return [q.stored[i] for i in q._ids if i in q.stored]
    return [r for r in q.audit if r["row_id"] in q._ids]


def check_restore() -> None:
    lift = BJS2["direction_decomposition"]["好物分享-产品贴"]["content_format"]

    def pending():
        out = []
        for nid in ("a", "b", "c", "d", "e"):
            n = _tr(BJS2, {"方向": ["成人款"]}, rid=nid)
            n["note_id"] = nid
            out.append(n)
        out[3].pop("data_quality_flags", None)          # d: 这一轮没写旗子列
        return out

    stored = {
        "a": {"note_id": "a", "content_format": lift, "_direction_raw": "好物分享-产品贴"},          # 换
        "b": {"note_id": "b", "content_format": lift, "_direction_raw": ["好物分享-产品贴"]},        # essence 没改 → 旗子
        "c": {"note_id": "c", "content_format": "情感叙事", "_direction_raw": "好物分享-产品贴"},   # 库里已是 essence 的
        "d": {"note_id": "d", "content_format": lift, "_direction_raw": "好物分享-产品贴"},          # essence 没改, 没旗子列
        # e: 新篇
    }
    audit = [
        {"audit_id": 1, "row_id": "a", "content_format": [lift, "认知重构"], "essence_annotated_at": [None, "t"]},
        {"audit_id": 5, "row_id": "a", "content_format": [lift, "情感叙事"], "essence_annotated_at": ["t", "t2"]},
        {"audit_id": 2, "row_id": "b", "content_format": None, "essence_annotated_at": [None, "t"]},
        {"audit_id": 3, "row_id": "d", "content_format": None, "essence_annotated_at": [None, "t"]},
    ]
    saved = engine.fetch_all_pages
    engine.fetch_all_pages = _fake_fetch
    try:
        ns = pending()
        sb = _FakeSB(stored, audit)
        st = engine.restore_content_format(sb, BJS2, ns, {"方向"}, dry_run=False)
        by = {n["note_id"]: n for n in ns}
        assert by["a"].get("content_format") == "情感叙事", f"§5 a 要换成 essence 最后一次写的值: {by['a'].get('content_format')!r}"
        assert "content_format" not in by["b"] and by["b"]["data_quality_flags"].get(engine._CF_NOT_RESTORED_FLAG), \
            "§5 b: essence 没改 content_format → 不换、打本轮旗子"
        assert "content_format" not in by["c"], "§5 c: 库里已是 essence 的值, 不该动 (反证 ③)"
        assert "content_format" not in by["d"] and "data_quality_flags" not in by["d"], "§5 d: 这一轮没写旗子列就不打"
        assert "content_format" not in by["e"], "§5 e: 新篇没有上一次"
        assert st == {"candidates": 5, "restored": 1, "not_restored": 2, "held": []}, st
        assert sb.reads == ["notes", "audit_log"], sb.reads
        for fail, held in (("notes", ["a", "b", "c", "d", "e"]), ("audit_log", ["a", "b", "d"])):
            ns = pending()
            st = engine.restore_content_format(_FakeSB(stored, audit, fail=fail), BJS2, ns, {"方向"}, dry_run=False)
            assert not any("content_format" in n for n in ns) and st["restored"] == st["not_restored"] == 0, \
                f"§5 读 {fail} 失败 → 一篇都不动"
            assert not any((n.get("data_quality_flags") or {}).get(engine._CF_NOT_RESTORED_FLAG) for n in ns)
            assert st["held"] == held, f"§5 读 {fail} 失败 → held 是 {held} (读库失败全部候选, 读 audit_log 失败要换的那几篇): {st['held']}"
        sb = _FakeSB(stored, audit)
        st = engine.restore_content_format(sb, BJS2, pending(), {"方向"}, dry_run=True)
        assert sb.reads == [] and st["candidates"] == 5 and st["held"] == [], "§5 dry-run 不读库、不留"
        # 上一次也抬不了 → 不读 audit_log
        sb = _FakeSB({"a": {"note_id": "a", "content_format": lift, "_direction_raw": ["成人款"]}}, audit)
        engine.restore_content_format(sb, BJS2, pending()[:1], {"方向"}, dry_run=False)
        assert sb.reads == ["notes"], sb.reads
        # 抬得了的篇不是候选, 一次库都不读
        sb = _FakeSB(stored, audit)
        n = _tr(BJS2, {"方向": ["提问贴"]})
        assert engine.restore_content_format(sb, BJS2, [n], {"方向"}, dry_run=False)["candidates"] == 0 and sb.reads == []
    finally:
        engine.fetch_all_pages = saved
    print("  §5 content_format: 旧方向的值 + essence 改过 → 换成 essence 最后一次的值; 没改 → 打旗子不换; 已是 essence 的 / 新篇不动; "
          "读库或 audit_log 失败一篇不动、回 held; dry-run 不读 ✓")


# ── §6 HATHERINE 新方向名 ────────────────────────────────────────────────────
NEW_HATH = ("流量-长痘提问", "产品-线下铺货", "流量-隐形体面", "流量-韩国痘痘贴", "流量-避雷帖", "产品-拉踩",
            "流量-痘贴吸脓效果", "流量-对比图", "流量-医院就诊", "流量-拉踩")


def check_hatherine() -> None:
    m = c.load_mapping("HATHERINE_phase1")
    dd = m["direction_decomposition"]
    for name in NEW_HATH:
        e = dd.get(name)
        assert isinstance(e, dict) and set(e) == {"layer"}, f"§6 {name}: 只登记 layer, 不写抬的值 (content_format 归 essence): {e}"
        assert e["layer"] == c.token_layer(name), f"§6 {name}: layer 要和前缀判的一样"
        n = _tr(m, {"方向": name})
        assert all(k in n and n[k] is None for k in CLEAR) and "content_format" not in n, n
        assert n.get("content_layer") == e["layer"]
    print(f"  §6 HATHERINE {len(NEW_HATH)} 个新方向名: 只登记 layer, 送 None, 层照前缀 ✓")


# ── §7 v1_33 的两张小表 = mapping ─────────────────────────────────────────────
def check_sql_parity() -> None:
    sql = (ROOT / "schemas" / "notes_v1_33_direction_switch_restore.sql").read_text(encoding="utf-8")
    lifts_sql = set(re.findall(r"\('([A-Za-z_0-9]+)', '([^']+)', '([^']+)'\)", sql.split("INSERT INTO i17_lifts VALUES", 1)[1].split(";", 1)[0]))
    ign_sql = set(re.findall(r"\('([A-Za-z_0-9]+)', '([^']+)'\)", sql.split("INSERT INTO i17_ign VALUES", 1)[1].split(";", 1)[0]))
    projects = sorted({p for p, _, _ in lifts_sql})
    assert projects == ["BJS_phase2", "HATHERINE_phase1", "SPX_phase1"], projects
    want_lifts, want_ign = set(), set()
    for pid in projects:
        m = c.load_mapping(pid)
        for k, e in (m.get("direction_decomposition") or {}).items():
            if engine.direction_lifts_profile(e):
                want_lifts.add((pid, k, e["content_format"]))
        want_ign |= {(pid, t) for t in (m.get("direction_ignore_tokens") or [])}
    assert lifts_sql == want_lifts, f"§7 v1_33 抬得了的方向和 mapping 不一致: 多 {lifts_sql - want_lifts} 少 {want_lifts - lifts_sql}"
    assert ign_sql == want_ign, f"§7 v1_33 忽略标和 mapping 不一致: {ign_sql} vs {want_ign}"
    bad = copy.deepcopy(BJS2)
    bad["direction_ignore_tokens"] = ["提问贴"]
    import tempfile, shutil, yaml
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "BJS_phase2.yaml").write_text(yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8")
        saved = c._MAPPINGS_DIR
        c._MAPPINGS_DIR = tmp
        try:
            c.load_mapping("BJS_phase2")
        except ValueError as exc:
            assert "direction_ignore_tokens" in str(exc), exc
        else:
            raise AssertionError("§7 忽略标同时是方向, 加载要红")
        finally:
            c._MAPPINGS_DIR = saved
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"  §7 v1_33: 抬得了的方向 {len(want_lifts)} 条、忽略标 {len(want_ign)} 个和 mapping 逐条一致; 忽略标同时是方向就加载红 ✓")


# ── §8 接线 ─────────────────────────────────────────────────────────────────
def check_wiring() -> None:
    src = Path(engine.__file__).read_text(encoding="utf-8")
    body = src[src.index("def main("):]
    i_clr = body.index("apply_cleared_direction(mapping, pending_notes, seen_cols)")
    i_cf = body.index("restore_content_format(sb, mapping, pending_notes, seen_cols, dry_run=args.dry_run)")
    i_up = body.index("written_ids = upsert_notes_batch(")
    i_risk = body.index("# ── 风控旗子的来源列整轮不见了 (外部评审 11-04 F01) ──")
    assert i_risk < i_clr < i_cf < i_up, "§8 清空 / 恢复要在风控旗子之后 (旗子列可能被整列拿掉)、upsert 之前"
    assert engine._CF_NOT_RESTORED_FLAG in engine._PER_RUN_FLAG_KEYS
    assert set(CLEAR) <= set(engine.UPSERT_PROTECTED_COLS), "§8 三列在 UPSERT_PROTECTED_COLS 里, 送 None 才清得掉"
    print("  §8 接线: 风控旗子之后、upsert 之前; content_format_not_restored 是本轮旗子 ✓")


# ── §9 读失败: 这一轮不写 raw_extra, 下一轮照常换回 (Codex #312 P2) ───────────────────────
import httpx                                                               # noqa: E402
import annotate_essence_pass as essence                                    # noqa: E402
from check_batch_upsert_columns import _Client as _PgClient, _Recorder, violations   # noqa: E402  真 postgrest-py + 假 HTTP

LIFT = BJS2["direction_decomposition"]["好物分享-产品贴"]["content_format"]
ESS = "情感叙事"


def _ignore(q: dict) -> bool:
    """这个请求是 INSERT ... ON CONFLICT DO NOTHING (postgrest-py 的 ignore_duplicates)。"""
    return "resolution=ignore-duplicates" in q["prefer"]


class _DbRec(_Recorder):
    """check_batch_upsert_columns 的假 HTTP, 多认得库里有哪些篇: ignore_duplicates 的请求照 PostgREST 只回真插进去的行
    (库里已有的不回)。fail_insert = ignore_duplicates 的请求一律拒 (批和逐行都拒)。每个请求记下成没成 (ok)。"""

    def __init__(self, db: dict, *, fail_insert: bool = False, **kw):
        super().__init__(**kw)
        self.known, self.fail_insert = set(db), fail_insert

    def handler(self, request: httpx.Request) -> httpx.Response:
        res = super().handler(request)
        q = self.requests[-1]
        q["ok"] = res.status_code < 300
        if not q["ok"] or not q["path"].endswith("/notes"):
            return res
        if _ignore(q):
            if self.fail_insert:
                q["ok"] = False
                return httpx.Response(503, json={"message": "insert refused (test)"})
            new = [r for r in q["rows"] if r["note_id"] not in self.known]
            self.known |= {r["note_id"] for r in new}
            return httpx.Response(201, json=new)
        self.known |= {r["note_id"] for r in q["rows"]}
        return res


def _apply(db: dict, rec: _DbRec) -> None:
    """录下的 notes 请求按 PostgREST 落进字典库: 批量请求 columns= 里的每一列都 SET (这一行没带 = NULL);
    单行请求 (逐行兜底, 没有 columns=) 只 SET 带了的键; ignore_duplicates 的请求只插库里还没有的篇。被拒的请求不落。"""
    for q in rec.requests:
        if not q["path"].endswith("/notes") or not q["ok"]:
            continue
        for row in q["rows"]:
            if _ignore(q) and row["note_id"] in db:
                continue
            cur = db.setdefault(row["note_id"], {})
            for col in (q["columns"] if q["columns"] is not None else row):
                cur[col] = row.get(col)


def _stripped(rec: _DbRec) -> list[dict]:
    """正常写的请求 (不是先插新篇的那一步)。"""
    return [q for q in rec.requests if not _ignore(q)]


def _essence_ctx(row: dict) -> str:
    """库里这一行照 essence 取数的样子 (NOTE_SELECT 的每一列都在, 库里是 NULL 的就是 None —— PostgREST 回的就是这样,
    .get 的默认值不起作用) 进真 build_mode_a_prompt, 回 user prompt。"""
    cols = [c.strip() for c in essence.NOTE_SELECT.split("projects(")[0].split(",") if c.strip()]
    return essence.build_mode_a_prompt({}, {c: json.loads(json.dumps(row.get(c))) for c in cols})[1]


def _dir(row: dict):
    """库里这一行 raw_extra._direction_raw (raw_extra 是 NULL 就是 None, 让断言报出来, 别 TypeError)。"""
    return (row.get("raw_extra") or {}).get("_direction_raw")


def _stored_view(db: dict) -> dict:
    return {nid: {"note_id": nid, "content_format": r.get("content_format"),
                  "_direction_raw": _dir(r)} for nid, r in db.items()}


def _night(db: dict, rows: dict, audit: list, *, fail: str = "", hold_on: bool = True, fail_batch: bool = False,
           fail_insert: bool = False):
    """一晚: transform_row → 清空 → 恢复 (读 db) → upsert_notes_batch (真 postgrest-py) → 落进 db。回 (restore 的统计, 录下的请求, pending)。"""
    pending = []
    for rid, f in rows.items():
        n = _tr(BJS2, f, rid=rid)
        n["note_id"] = rid
        pending.append(n)
    seen = {"方向", "笔记内容", "文案"}
    engine.apply_cleared_direction(BJS2, pending, seen)
    st = engine.restore_content_format(_FakeSB(_stored_view(db), audit, fail=fail), BJS2, pending, seen, dry_run=False)
    hold = {nid: engine._CF_HOLD_COLS for nid in st["held"]} if hold_on else None
    rec = _DbRec(db, fail_batch=fail_batch, fail_insert=fail_insert)
    before = json.loads(json.dumps(pending))
    written = engine.upsert_notes_batch(_PgClient(rec), pending, hold=hold)
    assert json.loads(json.dumps(pending)) == before, "§9 upsert_notes_batch 不许改调用方的行"
    assert written == {n["note_id"] for n in pending}, "§9 留 raw_extra 的篇照样写 (盖戳、指标的外键靠它)"
    _apply(db, rec)
    return st, rec, pending


# 第 0 晚: a 的方向抬得了 (库里 content_format = 抬的值, essence 判的是 情感叙事, audit_log 里有), n 早就只剩款式标,
# L 抬得了。第 1 晚: a 换成只剩款式标 (要换回 情感叙事)、n 换成另一个款式标、L 不变、e 是新篇。
_N0 = {"a": {"方向": "好物分享-产品贴"}, "n": {"方向": ["成人款"]}, "L": {"方向": "提问贴"}}
_N1 = {"a": {"方向": ["成人款"]}, "n": {"方向": ["儿童款"]}, "L": {"方向": "提问贴", "笔记内容": "新正文"}, "e": {"方向": ["成人款"]}}
_AUDIT = [{"audit_id": 7, "row_id": "a", "content_format": [LIFT, ESS], "essence_annotated_at": [None, "t"]}]


def _two_nights(fail: str, *, hold_on: bool = True, **kw) -> tuple[dict, list]:
    db: dict = {}
    _night(db, _N0, _AUDIT)
    assert db["a"]["content_format"] == LIFT and _dir(db["a"]) == "好物分享-产品贴", db["a"]
    out = [_night(db, _N1, _AUDIT, fail=fail, hold_on=hold_on, **kw)]
    out.append(json.loads(json.dumps(db)))                 # 第 1 晚之后的库
    out.append(_night(db, _N1, _AUDIT))
    return db, out


def check_read_failure_retry() -> None:
    saved = engine.fetch_all_pages
    engine.fetch_all_pages = _fake_fetch
    lg, level = engine.logger, engine.logger.level
    lg.setLevel(logging.CRITICAL)            # 读失败的 warning / 逐行兜底的 traceback 是故意的, 不刷屏
    try:
        # ── A) 第 1 晚读 audit_log 失败: 只留 a ─────────────────────────────
        db, ((st1, rec1, p1), after1, (st2, _r2, _p2)) = _two_nights("audit_log")
        assert st1["held"] == ["a"], f"§9A 读 audit_log 失败只留要换的那篇: {st1['held']}"
        assert _dir(after1["a"]) == "好物分享-产品贴" and after1["a"]["content_format"] == LIFT, \
            f"§9A 第 1 晚 a 的 raw_extra 要留着上一次的方向: {after1['a']}"
        assert all(after1["a"].get(k) is None for k in CLEAR), "§9A 三列照样清 (别的列照写)"
        assert _dir(after1["e"]) == ["成人款"], "§9A 新篇不在要换的里面, raw_extra 照写"
        assert _dir(after1["L"]) == "提问贴" and after1["L"]["raw_content"] == "新正文", "§9A 抬得了的篇照写"
        assert _dir(after1["n"]) == ["儿童款"], "§9A 上一次也抬不了的篇不留"
        ins = [q for q in rec1.requests if _ignore(q)]
        assert [sorted(r["note_id"] for r in q["rows"]) for q in ins] == [["a"]] and ins[0]["ok"], \
            f"§9A 留列的篇先整行插一遍 (库里已有 → 不动), 只有 a: {[q['rows'] for q in ins]}"
        for q in _stripped(rec1):
            ids = {r["note_id"] for r in q["rows"]}
            if "a" in ids:
                assert "raw_extra" not in (q["columns"] or []) and all("raw_extra" not in r for r in q["rows"]), \
                    f"§9A a 所在的请求不许带 raw_extra (columns= 里有就是写 NULL): {q['columns']}"
                assert ids == {"a"}, f"§9A 留 raw_extra 的篇自成一组: {ids}"
        orig_a = next(n for n in json.loads(json.dumps(p1)) if n["note_id"] == "a")
        sent_a = next(r for q in _stripped(rec1) for r in q["rows"] if r["note_id"] == "a")
        assert {k: v for k, v in orig_a.items() if k != "raw_extra"} == {k: v for k, v in sent_a.items() if k in orig_a}, \
            "§9A a 别的键原样发"
        mirror = set().union(*(n.keys() for n in p1)) - set(engine.UPSERT_PROTECTED_COLS) - {"raw_extra"}
        assert all(c in sent_a for c in mirror), f"§9A a 照样按整轮补 None (镜像飞书不变): 少 {mirror - set(sent_a)}"
        assert st2["restored"] == 1 and st2["held"] == [] and db["a"]["content_format"] == ESS, \
            f"§9A 第 2 晚读得到 → 换回 essence 的值: {st2} {db['a'].get('content_format')!r}"
        assert _dir(db["a"]) == ["成人款"], "§9A 第 2 晚 raw_extra 照常写新方向"

        # ── B) 第 1 晚读库失败: 全部候选 (a、n、e) 都留 ─────────────────────────
        db, ((st1, rec1, p1), after1, (st2, _r2, _p2)) = _two_nights("notes")
        assert sorted(st1["held"]) == ["a", "e", "n"], f"§9B 读库失败全部候选都留: {st1['held']}"
        assert _dir(after1["a"]) == "好物分享-产品贴" and _dir(after1["n"]) == ["成人款"], \
            f"§9B 第 1 晚 a、n 的 raw_extra 留着上一次的方向: {after1['a']} {after1['n']}"
        assert _dir(after1["e"]) == ["成人款"] and after1["e"].get("raw_content"), \
            f"§9B 新篇 (库里还没有) 照常整行插进去、raw_extra 也在 (不许落 NULL, essence 同一晚读它): {after1['e']}"
        assert "成人款" in _essence_ctx(after1["e"]), "§9B 同一晚 essence 给新篇的 prompt 里有它的方向"
        ins = [q for q in rec1.requests if _ignore(q)]
        assert ins and all(q["ok"] for q in ins) and sorted(r["note_id"] for q in ins for r in q["rows"]) == ["a", "e", "n"] \
            and all("raw_extra" in r for q in ins for r in q["rows"]), "§9B 留列的篇先整行 (带 raw_extra) 插一遍"
        assert not any(r["note_id"] == "e" for q in _stripped(rec1) for r in q["rows"]), \
            "§9B 插进去的新篇不再发第二遍 (多一遍 = 多一行只改 updated_at 的 audit_log)"
        assert {r["note_id"] for q in _stripped(rec1) for r in q["rows"]} >= {"a", "n", "L"}, "§9B 库里已有的照常写去掉留列的那一份"
        bad = violations(rec1.requests, {n["note_id"]: json.loads(json.dumps(n)) for n in p1})
        assert not bad, f"§9B 先插新篇那一步也守 D-122 (名单里的列按组带): {bad}"
        assert _dir(after1["L"]) == "提问贴", "§9B 抬得了的篇 (不是候选) 照写"
        assert all(after1["a"].get(k) is None for k in CLEAR)
        assert st2["restored"] == 1 and db["a"]["content_format"] == ESS, f"§9B 第 2 晚换回: {st2}"
        assert _dir(db["n"]) == ["儿童款"] and _dir(db["e"]) == ["成人款"], \
            "§9B 第 2 晚 raw_extra 补上"

        # ── 先插新篇那一步按名单列分组 (D-122): 留列的篇有的带 content_format、有的不带, 不带的不许被补成 NULL ──
        rec = _DbRec({})
        rows = [{"note_id": "x", "raw_content": "1", "content_format": "X", "raw_extra": {"k": 1}},
                {"note_id": "y", "raw_content": "2", "raw_extra": {"k": 2}}]
        engine.upsert_notes_batch(_PgClient(rec), rows, hold={"x": engine._CF_HOLD_COLS, "y": engine._CF_HOLD_COLS})
        dbx: dict = {}
        _apply(dbx, rec)
        assert not violations(rec.requests, {r["note_id"]: r for r in rows}) and "content_format" not in dbx["y"] \
            and dbx["x"]["content_format"] == "X" and [_ignore(q) for q in rec.requests] == [True, True], \
            f"§9 先插新篇按名单列分组, 插进去就不再发: {[(q['columns'], q['rows']) for q in rec.requests]}"

        # ── C) 读库失败 + 批被拒: 先插新篇也逐行兜底, 新篇照样带着 raw_extra 落库 ─────────────────
        db, ((st1, rec1, _p1), after1, (st2, _r2, _p2)) = _two_nights("notes", fail_batch=True)
        assert sorted(st1["held"]) == ["a", "e", "n"] and _dir(after1["e"]) == ["成人款"], \
            f"§9C 批被拒 → 逐行插, 新篇照样带 raw_extra: {after1['e']}"
        assert _dir(after1["a"]) == "好物分享-产品贴" and _dir(after1["n"]) == ["成人款"], "§9C a、n 照样留着"
        assert st2["restored"] == 1 and db["a"]["content_format"] == ESS, f"§9C 第 2 晚换回: {st2}"

        # ── D) 读库失败 + 先插新篇那一步全被拒 (批、逐行都拒): 退回去掉留列的那一份, 新篇这一晚 raw_extra 是 NULL;
        #       essence 读这一行不许抛 (不然整个项目这一晚的 essence 停在这一篇), 第 2 晚补上 ─────────────
        db, ((st1, rec1, _p1), after1, (st2, _r2, _p2)) = _two_nights("notes", fail_insert=True)
        assert [q["ok"] for q in rec1.requests if _ignore(q)] and not any(q["ok"] for q in rec1.requests if _ignore(q))
        assert "e" in after1 and after1["e"].get("raw_extra") is None and after1["e"].get("raw_content"), \
            f"§9D 插新篇失败 → 退回去掉 raw_extra 的那一份, 新篇照样写进去 (盖戳、指标外键靠它): {after1.get('e')}"
        assert _dir(after1["a"]) == "好物分享-产品贴", "§9D a 照样留着"
        assert "(项目未定义方向)" in _essence_ctx(after1["e"]), "§9D essence 的 prompt 读得了 raw_extra 是 NULL 的那一行"
        assert st2["restored"] == 1 and _dir(db["e"]) == ["成人款"], "§9D 第 2 晚换回、新篇 raw_extra 补上"

        # ── 反证 ⑥: 不留 raw_extra (改之前的行为) → 第 2 晚换不回来 ─────────────────
        for fail in ("audit_log", "notes"):
            db, ((st1, _r, _p), _after, (st2, _r2, _p2)) = _two_nights(fail, hold_on=False)
            assert st1["held"] and st2["restored"] == 0 and db["a"]["content_format"] == LIFT, \
                f"§9 反证: 读 {fail} 失败又不留 raw_extra, 第 2 晚该换不回来 (Codex 说的那件事): {st2}"

        # ── 读得到: hold 是空的, 请求和不带 hold 一字不差 ─────────────────────────────
        db0: dict = {}
        _night(db0, _N0, _AUDIT)
        db1 = json.loads(json.dumps(db0))
        st, rec, pending = _night(db0, _N1, _AUDIT)
        assert st["held"] == [] and st["restored"] == 1
        rec_plain = _Recorder()
        engine.upsert_notes_batch(_PgClient(rec_plain), pending)
        assert [(q["columns"], q["rows"]) for q in rec.requests] == [(q["columns"], q["rows"]) for q in rec_plain.requests], \
            "§9 读得到时和不带 hold 发的请求一字不差"

        # ── 逐行兜底: 批被拒 → 单行请求也不带 raw_extra ──────────────────────────────
        st, rec, _p = _night(db1, _N1, _AUDIT, fail="audit_log", fail_batch=True)
        singles = [q["rows"][0] for q in _stripped(rec) if q["columns"] is None]
        assert st["held"] == ["a"] and any(r["note_id"] == "a" for r in singles)
        assert all("raw_extra" not in r for r in singles if r["note_id"] == "a"), "§9 逐行兜底发的也是去掉 raw_extra 的那一份"
        assert _dir(db1["a"]) == "好物分享-产品贴"

        # ── dry-run: 不读、不留、不发 ─────────────────────────────────────────────
        sb = _FakeSB(_stored_view(db0), _AUDIT, fail="audit_log")
        pend = [dict(_tr(BJS2, f, rid=rid), note_id=rid) for rid, f in _N1.items()]
        st = engine.restore_content_format(sb, BJS2, pend, {"方向"}, dry_run=True)
        rec = _DbRec({})
        engine.upsert_notes_batch(_PgClient(rec), pend, dry_run=True, hold={"a": engine._CF_HOLD_COLS})
        assert st["held"] == [] and sb.reads == [] and rec.requests == [], "§9 dry-run 不读库、不留、不发请求"
    finally:
        engine.fetch_all_pages = saved
        lg.setLevel(level)
    print("  §9 读失败: 留着 raw_extra (请求里没有、columns= 里没有、逐行兜底也没有), 三列 / 别的列照写, 第 2 晚换回; "
          "读 audit_log 失败只留要换的、读库失败留全部候选; 新篇先整行插 (带 raw_extra, 批被拒逐行插, 只发一遍, 守 D-122), "
          "插不成退回 NULL、essence 读得了; 读得到时请求不变; dry-run 不读不发; 不留就换不回来 (反证 ⑥) ✓")
    check_main_two_nights()


# ── §9 续: 驱动真的 main() 两晚 (Done 行 / errors / 退出码 / ::error / hold 接到 upsert) ─────────────
class _Read:
    def __init__(self, t: str, sel: str):
        self.t, self.sel, self.ids = t, sel, None

    def in_(self, _c, ids):
        self.ids = list(ids)
        return self

    @property
    def not_(self):
        return self

    def __getattr__(self, _name):
        return lambda *a, **k: self


class _Hybrid:
    """main 用的库: 读 (select) 交给下面的假 fetch_all_pages 照字典库答; upsert 走真 postgrest-py + 假 HTTP 录下来。"""

    def __init__(self, rec: _Recorder):
        self.rec = rec

    def schema(self, name):
        hy = self

        class _S:
            def table(self, t):
                class _T:
                    def select(self, sel, *a, **k):
                        return _Read(t, sel)

                    def upsert(self, rows, **k):
                        return _PgClient(hy.rec).schema(name).table(t).upsert(rows, **k)
                return _T()

            def rpc(self, *a, **k):
                raise AssertionError("§9 main: 这里不该调 rpc (账本已打桩)")
        return _S()


_PID = "T_I17"
_MAIN_MAP = {"project_id": _PID, "platform": "xiaohongshu",
             "field_mapping": {"文案": "raw_content", "标题": "title", "方向": "_direction_raw"},
             "direction_decomposition": copy.deepcopy(BJS2["direction_decomposition"]),
             "direction_ignore_tokens": list(BJS2["direction_ignore_tokens"]),
             "sync_config": {"feishu_app_token": "app", "feishu_table_id": "tbl"}}


def _main_night(db: dict, rows: dict, audit: list, *, fail: str = "", dry: bool = False):
    reads: list[str] = []
    rec = _DbRec(db)

    def pages(q, page_size=1000, order_by=None):
        if not isinstance(q, _Read):
            return []
        if q.t == "notes" and "_direction_raw" in q.sel or q.t == "audit_log":
            reads.append(q.t)
        if q.t == fail:
            raise RuntimeError("库挂了")
        if q.t == "notes" and "_direction_raw" in q.sel:
            return [_stored_view(db)[i] for i in q.ids if i in db]
        if q.t == "audit_log":
            return [r for r in audit if r["row_id"] in q.ids]
        return []

    class F:
        def __init__(self, *a, **k): pass

        def list_records(self, *a, **k):
            return iter([{"record_id": rid, "fields": {"文案": "正文正文", "标题": "t", **f}} for rid, f in rows.items()])

    stubs = dict(
        FeishuClient=F, get_supabase_client=lambda *a, **k: _Hybrid(rec), assert_db_schema_ready=lambda *a, **k: None,
        begin_sync_run=lambda *a, **k: engine.LEDGER_MISSING, complete_sync_run=lambda *a, **k: None,
        ensure_project_exists=lambda *a, **k: None, quarantine_record=lambda *a, **k: None,
        fetch_acknowledged_quarantine=lambda *a, **k: set(), upsert_metrics_batch=lambda *a, **k: (0, []),
        update_project_date_range=lambda *a, **k: None, fetch_all_pages=pages, load_mapping=lambda _p: _MAIN_MAP,
        _detect_missing_capabilities=lambda *a, **k: [], prepare_content_layer=lambda *a, **k: True)
    saved = {k: getattr(engine, k) for k in stubs}
    saved_argv, out, buf = sys.argv, io.StringIO(), io.StringIO()
    handlers, engine.logger.handlers = engine.logger.handlers, [logging.StreamHandler(buf)]
    env = {k: os.environ.get(k) for k in ("FEISHU_APP_ID", "FEISHU_APP_SECRET", "GITHUB_ACTIONS", "TV_SCHEDULED_RUN")}
    try:
        for k, v in stubs.items():
            setattr(engine, k, v)
        os.environ.update(FEISHU_APP_ID="x", FEISHU_APP_SECRET="y", GITHUB_ACTIONS="true")
        os.environ.pop("TV_SCHEDULED_RUN", None)
        sys.argv = ["x", _PID] + (["--dry-run"] if dry else [])
        with contextlib.redirect_stdout(out):
            rc = engine.main()
    finally:
        for k, v in saved.items():
            setattr(engine, k, v)
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        engine.logger.handlers = handlers
        sys.argv = saved_argv
    _apply(db, rec)
    done = json.loads(buf.getvalue().split("Done: ")[1].split("\n")[0])
    return rc, done, out.getvalue(), reads, rec


def check_main_two_nights() -> None:
    nid = lambda r: engine.make_note_id(_PID, r)            # noqa: E731
    n0 = {"a": {"方向": "好物分享-产品贴"}, "L": {"方向": "提问贴"}}
    n1 = {"a": {"方向": ["成人款"]}, "L": {"方向": "提问贴"}, "e": {"方向": ["成人款"]}}
    audit = [{"audit_id": 7, "row_id": nid("a"), "content_format": [LIFT, ESS], "essence_annotated_at": [None, "t"]}]
    for fail, held in (("audit_log", 1), ("notes", 2)):
        db: dict = {}
        rc, done, out, _reads, _rec = _main_night(db, n0, audit)
        assert rc == 0 and done["errors"] == 0 and done["content_format_restore_held"] == 0, f"§9 main 第 0 晚要绿: {done}"
        assert db[nid("a")]["content_format"] == LIFT
        rc, done, out, reads, rec = _main_night(db, n1, audit, fail=fail)
        assert done["content_format_restore_held"] == held and done["content_format_restored"] == 0, \
            f"§9 main 读 {fail} 失败: Done 行 content_format_restore_held = {held}: {done}"
        assert done["errors"] == 1 and rc == 1, f"§9 main 读 {fail} 失败要红 (errors 1、退出码 1): rc={rc} {done}"
        assert "::error title=content_format 恢复没读到库" in out, "§9 main 读失败要有 ::error"
        assert done["upserted"] == 3, f"§9 main 留 raw_extra 的篇照样写: {done}"
        assert _dir(db[nid("a")]) == "好物分享-产品贴" and all(db[nid("a")].get(k) is None for k in CLEAR), \
            f"§9 main 读 {fail} 失败: a 的 raw_extra 留着上一次的方向 (hold 接到了 upsert), 三列照清: {db[nid('a')]}"
        assert _dir(db[nid("e")]) == ["成人款"], f"§9 main 读 {fail} 失败: 新篇照常带 raw_extra 插进去: {db[nid('e')]}"
        rc, done, out, reads, rec = _main_night(db, n1, audit)
        assert rc == 0 and done["errors"] == 0 and done["content_format_restored"] == 1 \
            and done["content_format_restore_held"] == 0 and "::error" not in out, f"§9 main 第 2 晚换回、绿: rc={rc} {done}"
        assert db[nid("a")]["content_format"] == ESS and _dir(db[nid("a")]) == ["成人款"]
    rc, done, out, reads, rec = _main_night({}, n1, audit, fail="audit_log", dry=True)
    assert rc == 0 and done["content_format_restore_held"] == 0 and reads == [] and rec.requests == [], \
        f"§9 main dry-run: 不读库、不发请求、绿: rc={rc} {done} {reads}"
    print("  §9 main 两晚: 读 audit_log / 读库失败 → Done 行 content_format_restore_held 1 / 2、errors 1、退出码 1、::error, "
          "a 的 raw_extra 留着; 第 2 晚换回、绿; dry-run 不读不发 ✓")


def main() -> int:
    check_ignore_tokens()
    check_unliftable_clears()
    check_untouched()
    check_cleared_cell()
    check_restore()
    check_hatherine()
    check_sql_parity()
    check_wiring()
    check_read_failure_retry()
    print("\ncheck_direction_switch: 9 节全过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
