#!/usr/bin/env python3
"""
check_content_layer.py —— 内容层 notes.content_layer (D-140; _common.derive_layer) 的离线守卫。

  §1 mapping: 每一份 mapping 都读得出来; 写了 layer 的方向只许 P / T / Q / J (写错一个字母 load_mapping 就红);
     D-140 写明的那几份逐条钉死 (XIWU 流量贴 T / 产品贴 P; BJS 好物分享-产品贴 P / 提问贴 Q, BJS_phase2 精品贴 J;
     SPX 提问贴 Q / 好物分享-产品贴 P; HATHERINE 产品-* P / 流量-* T; OKMAN D10-产品贴 P; LNKT 流量贴 T)
  §2 词规则: 整个值 产品贴 / 流量贴 / 提问贴 / 精品贴, 前缀 产品- / 流量-, 后缀 -产品贴 / -流量贴; 绝不在题目名里找子串
     (方向三 产品直给型 / 方向四 提问与红黑榜 / 付款与签约提问帖 / 极简提问 都是 NULL);
     库里读出来是 JSON 数组字符串 ('["流量贴"]') 也认; 多选要每个值都同一层, 有分歧 / 有的认不出 → NULL;
     一个值都认不出才退回 intent (conversion → P, traffic → T, 别的 NULL)
  §3 真 mapping × 生产里真出现过的方向值 (11-03 只读): 每个值落在哪一层钉死
  §4 sync: transform_row 每行都带 content_layer (值可以是 None); 库里还没有这一列 → 写库前整列拿掉、别的不动;
     探不到也不让入库崩
  §5 别的写入方不碰: essence 的写回 (含子方向) 里没有 content_layer

跑法: cd scripts && python check_content_layer.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common as C  # noqa: E402
import sync_feishu_notes_to_truth_vault as engine  # noqa: E402

MAPPINGS = Path(__file__).resolve().parent.parent / "mappings"

# D-140 写明的层 (改这里 = 改 mappings/*.yaml 的 layer, 同一个 PR 里写 D 号)
DECLARED = {
    "XIWU_phase1": {"流量贴": "T", "产品贴": "P"},
    "XIWU_phase2": {"流量贴": "T", "产品贴": "P"},
    "BJS_phase1": {"好物分享-产品贴": "P", "提问贴": "Q"},
    "BJS_phase2": {"好物分享-产品贴": "P", "提问贴": "Q", "精品贴": "J"},
    "SPX_phase1": {"提问贴": "Q", "好物分享-产品贴": "P"},
    "HATHERINE_phase1": {"产品-全家桶": "P", "产品-76贴囤货": "P", "产品-功能说明": "P", "流量-不破皮痘": "T",
                         "产品-微针": "P", "产品-oly上架": "P", "流量-破皮痘": "T", "产品-对比": "P"},
    "OKMAN_phase1": {"D10-产品贴": "P"},
    "LNKT_phase1": {"流量贴": "T"},
}


def s1_mappings() -> None:
    ids = sorted(p.stem for p in MAPPINGS.glob("*.yaml") if p.stem != "_template")
    assert len(ids) >= 19, ids
    seen = {}
    for pid in ids:
        m = C.load_mapping(pid)
        layers = {k: v["layer"] for k, v in (m.get("direction_decomposition") or {}).items()
                  if isinstance(v, dict) and "layer" in v}
        assert all(v in C.CONTENT_LAYERS for v in layers.values()), (pid, layers)
        seen[pid] = layers
    for pid, want in DECLARED.items():
        assert seen[pid] == want, f"{pid}: mapping 里写的 layer {seen[pid]} ≠ D-140 定的 {want}"
    assert {p for p, v in seen.items() if v} == set(DECLARED), \
        f"只有 D-140 写明的那几份 mapping 有 layer: {sorted(p for p, v in seen.items() if v)}"
    bjs2 = C.load_mapping("BJS_phase2")["direction_decomposition"]["精品贴"]
    assert bjs2 == {"layer": "J"}, "精品贴只写 layer: 不送受保护的 content_format / 人群 / 痛点 (I-17)"
    # 写错一个字母就在 load_mapping 红
    bad = MAPPINGS / "ZZ_layer_bad.yaml"
    src = (MAPPINGS / "XIWU_phase2.yaml").read_text(encoding="utf-8")
    try:
        for wrong in ("p", "产品", "X"):
            bad.write_text(src.replace("project_id: XIWU_phase2", "project_id: ZZ_layer_bad", 1)
                           .replace("    layer: T ", f"    layer: {wrong} ", 1), encoding="utf-8")
            try:
                C.load_mapping("ZZ_layer_bad")
            except ValueError as exc:
                assert "layer" in str(exc), exc
            else:
                raise AssertionError(f"layer={wrong!r} 应该被 load_mapping 挡住")
    finally:
        bad.unlink(missing_ok=True)
    print(f"  §1 mapping: {len(ids)} 份都读得出来; layer 只许 P/T/Q/J、写错就红; D-140 写明的 {len(DECLARED)} 份逐条钉死 ✓")


def s2_rules() -> None:
    d = lambda raw, intent=None, m=None: C.derive_layer(raw, m or {}, intent)  # noqa: E731
    for raw, want in (("产品贴", "P"), ("流量贴", "T"), ("提问贴", "Q"), ("精品贴", "J"),
                      ("产品-全家桶", "P"), ("流量-某某提问", "T"), ("好物分享-产品贴", "P"), ("某饮品-流量贴", "T"),
                      ("D10-产品贴", "P"), ("好物分享－产品贴", "P"), (" 流量贴 ", "T")):
        assert d(raw) == want, (raw, d(raw), want)
    # 题目名里的「产品」「提问」「流量」不是层
    for raw in ("方向三 产品直给型", "方向四 提问与红黑榜", "付款与签约提问帖", "极简提问", "方向九某流量科普", "某某药提问",
                "产品-", "-产品贴", "产品贴子", "真实体验与求问", "某某联名活动宣传"):
        assert d(raw) is None, (raw, d(raw))
    # 库里读出来的形状
    assert d('["流量贴"]') == "T" and d(["产品贴"]) == "P" and d([{"text": "提问贴"}]) == "Q" and d({"text": "精品贴"}) == "J"
    assert d('["方向四 提问与红黑榜", "赠送反差内容"]') is None
    # 多选: 每个值同一层才给; 有分歧 / 有的认不出 → NULL, 不退回 intent
    assert d(["流量贴", "流量-破皮痘"]) == "T"
    assert d(["流量贴", "产品贴"], "traffic") is None, "有分歧 → NULL"
    assert d(["流量贴", "某个选题"], "conversion") is None, "有的认不出 → NULL"
    assert d("流量贴, 产品贴") is None and d('["流量贴", "产品贴"]') is None
    # 一个值都认不出 → intent
    assert d(None, "conversion") == "P" and d(None, "traffic") == "T" and d("", "traffic") == "T"
    assert d(["为爱助戒"], "traffic") == "T" and d(["咀嚼胶"], "conversion") == "P"
    assert d(None, "mixed") is None and d(None, "educational") is None and d(None, None) is None and d("极简提问") is None
    # mapping 写明的 layer 压过词规则; 整格 (多选拼起来的键) 先看
    m = {"direction_decomposition": {"极简提问": {"layer": "Q"}, "流量贴": {"layer": "T"},
                                     "方向四 提问与红黑榜, 赠送反差内容": {"layer": "Q"}, "产品贴": {"content_format": "x"}}}
    assert d("极简提问", m=m) == "Q" and d(["方向四 提问与红黑榜", "赠送反差内容"], m=m) == "Q"
    assert d("产品贴", m=m) == "P", "mapping 里有这个方向但没写 layer → 照词规则"
    assert d(["极简提问", "流量贴"], m=m) is None, "逐个值看: Q 和 T 有分歧 → NULL"
    print("  §2 词规则: 整值 / 前缀 / 后缀; 题目名里的子串不算; JSON 数组字符串; 多选要一致; 认不出才看 intent; mapping 压过规则 ✓")


# 11-03 生产只读里出现过的方向值的形状 (raw_extra._direction_raw), 每个值落在哪一层 —— 规则改了, 这张表跟着改。
# 本仓公开: mapping 里已经有的值照写, 没进 mapping 的值换成同一个形状的占位 (同样的前缀 / 后缀 / 子串), 判定结果不变。
PROD = {
    "XIWU_phase1": [(["流量贴"], None, "T"), (["产品贴"], None, "P")],
    "XIWU_phase2": [(["流量贴"], None, "T"), (["产品贴"], None, "P"), (None, None, None)],
    "BJS_phase1": [("好物分享-产品贴", None, "P"), ("提问贴", None, "Q")],
    "BJS_phase2": [("提问贴", None, "Q"), ("好物分享-产品贴", None, "P"), ("精品贴", None, "J")],
    "SPX_phase1": [("提问贴", None, "Q"), ("好物分享-产品贴", None, "P"), ("方向一某场景向", None, None),
                   ("方向四某流量科普", None, None), ("某联名活动宣传", None, None), ("某某测评", None, None),
                   ("某饮品-产品贴", None, "P"), ("某饮品-流量贴", None, "T"), ("某联名款➕某贴-产品贴", None, "P")],
    "HATHERINE_phase1": [("流量-某某提问", None, "T"), ("产品-全家桶", None, "P"), ("产品-某某对照", None, "P"),
                         ("流量-某某避雷", None, "T"), ("流量-破皮痘", None, "T")],
    "OKMAN_phase1": [(["D10-产品贴"], None, "P"), (["真实体验与求问"], None, None), (["D9-男性被评价"], None, None)],
    "LNKT_phase1": [("流量贴", None, "T"), ("极简提问", None, None), ("某某药提问", None, None), ("互助求助", None, None)],
    "WTG_phase1": [(["方向三 产品直给型"], None, None), (["方向三 产品直给型", "方向六 辐照消杀内裤"], None, None)],
    "RIO_phase1": [(["方向四 提问与红黑榜"], None, None), (["方向四 提问与红黑榜", "赠送反差内容"], None, None)],
    "TUGE_phase1": [(["付款与签约提问帖"], None, None), (["付款与签约提问帖", "严格控评"], None, None)],
    "ANSHEN_phase1": [("口气 · 社交焦虑", "conversion", "P"), ("正畸牙套党", "traffic", "T")],
    "NRT_phase2": [(None, "traffic", "T"), (["咀嚼胶"], "conversion", "P"), (["为爱助戒", "咀嚼胶"], "traffic", "T")],
    "NUC_phase1": [(["营养保健代餐相关"], "traffic", "T"), (["糖尿病相关"], "conversion", "P")],
    "HXZ_QD": [(["妆效问题"], "traffic", "T"), (None, None, None)],
    "TGV_phase1": [(None, None, None)],
    "TXQ_phase1": [(["方向四 配料表反思"], None, None)],
}


def s3_production_values() -> None:
    n = 0
    for pid, cases in PROD.items():
        m = C.load_mapping(pid)
        for raw, intent, want in cases:
            got = C.derive_layer(raw, m, intent)
            assert got == want, f"{pid} {raw!r} intent={intent}: {got} ≠ {want}"
            n += 1
    print(f"  §3 真 mapping × 生产方向值: {n} 个值逐个钉死 (WTG 产品直给型 / RIO 提问与红黑榜 / TUGE 提问帖 / LNKT 极简提问 都是 NULL) ✓")


class _Q:
    def __init__(self, sb):
        self.sb = sb

    def select(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def execute(self):
        if isinstance(self.sb.result, Exception):
            raise self.sb.result
        return type("R", (), {"data": self.sb.result})()


class _SB:
    def __init__(self, result):
        self.result = result

    def schema(self, s):
        return self

    def table(self, t):
        return _Q(self)


def s4_sync() -> None:
    m = C.load_mapping("BJS_phase2")
    fm = {v: k for k, v in m["field_mapping"].items()}
    base = {fm["raw_content"]: "占位正文 " * 5}
    note, _metric, _und = engine.transform_row(m, "recL1", {**base, fm["_direction_raw"]: "精品贴"})
    assert note["content_layer"] == "J" and "content_format" not in note, note
    note2, _, _ = engine.transform_row(m, "recL2", dict(base))
    assert "content_layer" in note2 and note2["content_layer"] is None, "没填方向的行也带这个键 (批量 upsert 每行同一组列)"
    note3, _, _ = engine.transform_row(m, "recL3", {**base, fm["_direction_raw"]: "提问贴"})
    assert note3["content_layer"] == "Q" and note3["content_format"] == "提问求助"
    # 库里有这一列 → 原样写; 没有 / 探不到 → 整列拿掉, 别的键一个不动
    pending = [dict(note), dict(note2)]
    assert engine.prepare_content_layer(_SB([{"note_id": "x", "content_layer": None}]), pending) is True
    assert [p["content_layer"] for p in pending] == ["J", None]
    C._CONTENT_LAYER_WARNED.clear()
    for probe in (RuntimeError("{'code': '42703', 'message': 'column notes.content_layer does not exist'}"),
                  RuntimeError("connection reset"), [{"note_id": "x"}]):
        pending = [dict(note), dict(note2)]
        assert engine.prepare_content_layer(_SB(probe), pending) is False, probe
        assert all("content_layer" not in p for p in pending) and pending[0]["raw_extra"] == note["raw_extra"], \
            "没有这一列: 只拿掉 content_layer, 别的照旧"
    assert C.notes_content_layer_supported(_SB([])) is True, "空库算有"
    print("  §4 sync: transform_row 每行都带 content_layer; 库里没有这一列 / 探不到 → 写库前整列拿掉、别的不动 ✓")


def s5_other_writers() -> None:
    import annotate_essence_pass as E
    captured: list = []

    class Upd:
        def update(self, u):
            captured.append(u)
            return self

        def eq(self, *a):
            return self

        def execute(self):
            return None

    class SB:
        def schema(self, s):
            return self

        def table(self, t):
            return Upd()
    parsed = {"essence": {"emotional_lever": "a", "emotional_valence": "positive", "emotional_intensity": "low",
                          "human_truth_archetype": "b", "trend_dependencies": "c", "content_format": "d"},
              "audience": {}}
    subs = [{"name": "s1", "content_format": "x", "target_audience": ["通用"], "layer": "P"}]
    E.write_essence_back(SB(), "n1", "m", parsed, ("s1", subs), dry_run=False, content_sha="abc")
    assert captured and "content_layer" not in captured[0] and "layer" not in captured[0], captured
    src = (Path(__file__).resolve().parent / "sync_truth_vault_baokuan_to_sanshengliubu.py").read_text(encoding="utf-8")
    assert "content_layer" not in src
    print("  §5 别的写入方不碰: essence 写回 (含子方向配置里多写的 layer) 没有 content_layer ✓")


def main() -> int:
    s1_mappings()
    s2_rules()
    s3_production_values()
    s4_sync()
    s5_other_writers()
    print("\ncheck_content_layer: 5 节全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
