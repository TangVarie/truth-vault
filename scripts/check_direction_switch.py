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
     essence 那一次没改 content_format → 不换、打本轮旗子 (这一轮没写旗子列就不打); 读库 / 读 audit_log 失败 → 一篇不动;
     dry-run 不读库; 上一次也抬不了 / 库里不是旧方向的值 / 新篇 → 不读 audit_log。
  §6 HATHERINE 9 月下旬起的 10 个新方向名都登记了 (只有 layer): 送 None、层照前缀。
  §7 schemas/notes_v1_33 里「哪些方向抬得了」「哪些标要忽略」两张小表和 mapping 逐条一致; 忽略标不能同时是方向。
  §8 接线: 清空 / 恢复在 upsert 之前; content_format_not_restored 是本轮旗子 (以库里旗子为底时剥掉)。

反证 (改坏之后必须变红):
  ① 去掉 BJS_phase2 的 direction_ignore_tokens       → §1 红 (本文件 §1 末尾实跑)
  ② transform_row 不管子方向也清                     → §3 「NUC 三个键都不出现」红
  ③ restore 不看「库里是不是旧方向的值」             → §5 「库里已是 essence 的值」那条红
  ④ v1_33 少写一个抬得了的方向                       → §7 红
  ⑤ essence 查子方向不去掉忽略标 / restore 候选不跳过子方向 → §3 红

跑法: cd scripts && python check_direction_switch.py
"""
from __future__ import annotations

import copy
import re
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
        assert st == {"candidates": 5, "restored": 1, "not_restored": 2}, st
        assert sb.reads == ["notes", "audit_log"], sb.reads
        for fail in ("notes", "audit_log"):
            ns = pending()
            st = engine.restore_content_format(_FakeSB(stored, audit, fail=fail), BJS2, ns, {"方向"}, dry_run=False)
            assert not any("content_format" in n for n in ns) and st["restored"] == st["not_restored"] == 0, \
                f"§5 读 {fail} 失败 → 一篇都不动"
            assert not any((n.get("data_quality_flags") or {}).get(engine._CF_NOT_RESTORED_FLAG) for n in ns)
        sb = _FakeSB(stored, audit)
        st = engine.restore_content_format(sb, BJS2, pending(), {"方向"}, dry_run=True)
        assert sb.reads == [] and st["candidates"] == 5, "§5 dry-run 不读库"
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
          "读库或 audit_log 失败一篇不动; dry-run 不读 ✓")


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


def main() -> int:
    check_ignore_tokens()
    check_unliftable_clears()
    check_untouched()
    check_cleared_cell()
    check_restore()
    check_hatherine()
    check_sql_parity()
    check_wiring()
    print("\ncheck_direction_switch: 8 节全过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
