#!/usr/bin/env python3
"""列体检 2026-11-25 (data-analysis/column-audit-2026-11-25.md §3a) 的入库修正: 守卫。

断行为不断源码 (D-051): §1 §2 §3 真的走 load_mapping + transform_row; §4 读真 mapping 的声明;
只有 §5 (注释改正) 是读 yaml 原文。

  §1 「随贴评论素人」是素人编号, 不是评论 (§3a #1): 5 张 B 族表映成 _commenter_codes, transform_row 存成
     raw_extra._commenter_codes 编号列表, 不再出现 _comment_text_persona; 写旧名的 mapping 加载就红。
     (评论同步不读它: check_comment_parser.py 的最后一节。)
  §2 ANSHEN / TUGE 的「蓝词字段 → 命中蓝词」(§3a #2): 映到 hit_blue_keywords, 原样进库, 不剥竞品名 (I-26 已关)。
  §3 「爆帖置顶评论」「爆帖控评置顶」(含 typed 的 pinned_comment) 只认做过的标签 (§3a #3, D-060 / D-062 后续):
     待置顶 / 待做评论 / 待安排贴主自评(回复) / 等解封后控评 / 素人退出无法回收 不算「起量后干预」。
  §4 映射漂移 (§3a #7): SPX 声明「数据整理」不再是「数据汇总」; HATHERINE / TUGE 用新名「下次检查时间」;
     TUGE 不再声明已删的「点赞数」「收藏数」; linkcheck 写的那批列在各表都声明了, 不再落 _undeclared。
  §5 「评论关键词」的注释不再写成「运营定义的蓝词」(§3a #6)。

反证 (改坏之后必须变红):
  ① _KNOWN_INTERMEDIATES 放回 _comment_text_persona            → §1 「旧名加载就红」那条红
  ② transform_row 不消费 _commenter_codes (落回 leftover 原值)  → §1 「是列表」那条红
  ③ 删掉 ANSHEN 的 蓝词字段 映射                               → §2 红 (列进 _undeclared, hit_blue_keywords 空)
  ④ posthoc_done_labels 不滤待办 (_common._CM_POSTHOC_PENDING_RE 永不命中) → §3 待办那几条红 (本文件 §3 末尾实跑这条反证;
     11-25 判据本体挪进 _common, 同步脚本和闸二敏感性重跑共用, G-25)
  ⑤ SPX 改回「数据汇总」                                        → §4 红

跑法: cd scripts && python check_column_audit_fixes.py
"""
from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

import _common as c
import sync_feishu_notes_to_truth_vault as engine

ROOT = Path(__file__).resolve().parent.parent
B_FAMILY = ("HXZ_FB", "HXZ_QD", "NRT_phase2", "NRT_phase3", "NUC_phase1")
POSTHOC = engine._CM_ROUTE_POSTHOC


def _flags(n: dict) -> dict:
    return n.get("data_quality_flags") or {}


# ── §1 随贴评论素人 → 素人编号列表 ───────────────────────────────────────────
def check_commenter_codes() -> None:
    for pid in B_FAMILY:
        fm = c.load_mapping(pid)["field_mapping"]
        assert fm.get("随贴评论素人") == "_commenter_codes", f"§1 {pid}: 随贴评论素人 → {fm.get('随贴评论素人')!r}"
        assert "_comment_text_persona" not in fm.values(), f"§1 {pid} 还在写旧名"
    nuc = c.load_mapping("NUC_phase1")
    base = {"文案": "正文", "随贴评论": "1. 用户A: 好用"}
    for cell, want in (("12a", ["12a"]), (12, ["12"]), ("7", ["7"]), ([{"text": "3"}, {"text": "5b"}], ["3", "5b"]),
                       ("12、15 12", ["12", "15"])):
        note, _, und = engine.transform_row(nuc, "r1", {**base, "随贴评论素人": cell})
        rx = note.get("raw_extra") or {}
        assert rx.get("_commenter_codes") == want, f"§1 {cell!r} → {rx.get('_commenter_codes')!r}, 应为 {want}"
        assert "_comment_text_persona" not in rx, f"§1 旧键不该再写进 raw_extra: {sorted(rx)}"
        assert rx.get("_comment_text") == "1. 用户A: 好用", "§1 随贴评论照旧进 raw_extra._comment_text"
        assert "随贴评论素人" not in und
    for empty in ("", [], None):
        note, _, _ = engine.transform_row(nuc, "r2", {**base, "随贴评论素人": empty})
        assert "_commenter_codes" not in (note.get("raw_extra") or {}), f"§1 空格子不写键: {empty!r}"
    # 写旧名的 mapping 加载就红 (旧名不在 _KNOWN_INTERMEDIATES)
    tmp = Path(tempfile.mkdtemp())
    try:
        src = (ROOT / "mappings" / "NUC_phase1.yaml").read_text(encoding="utf-8")
        old = re.sub(r"随贴评论素人: _commenter_codes.*", "随贴评论素人: _comment_text_persona", src)
        assert old != src
        (tmp / "NUC_phase1.yaml").write_text(old, encoding="utf-8")
        saved = c._MAPPINGS_DIR
        c._MAPPINGS_DIR = tmp
        try:
            c.load_mapping("NUC_phase1")
        except ValueError as exc:
            assert "_comment_text_persona" in str(exc), exc
        else:
            raise AssertionError("§1 写旧名 _comment_text_persona 的 mapping 应该加载就红")
        finally:
            c._MAPPINGS_DIR = saved
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("  §1 随贴评论素人: 5 张 B 族表映成 _commenter_codes, 存编号列表 (字符串 / 数字 / 富文本 / 多个), "
          "空格子不写键, 不再有 _comment_text_persona; 写旧名的 mapping 加载就红 ✓")


# ── §2 蓝词字段 → 命中蓝词 ─────────────────────────────────────────────────
def check_blue_keywords() -> None:
    for pid in ("ANSHEN_phase1", "TUGE_phase1"):
        m = c.load_mapping(pid)
        assert m["field_mapping"].get("蓝词字段") == "hit_blue_keywords", f"§2 {pid}"
        assert "蓝词字段" not in (m.get("project_specific_fields_to_raw_extra") or []), f"§2 {pid} 不该再进 raw_extra"
        note, _, und = engine.transform_row(m, "r1", {"笔记内容": "正文", "蓝词字段": ["品牌词", "竞品词"]})
        assert "蓝词字段" not in und, f"§2 {pid}: 蓝词字段 还在 _undeclared"
        assert note.get("hit_blue_keywords") == ["品牌词", "竞品词"], \
            f"§2 {pid}: 原样进库、不剥竞品名 (I-26 已关): {note.get('hit_blue_keywords')!r}"
    print("  §2 ANSHEN / TUGE: 蓝词字段 → hit_blue_keywords, 不落 _undeclared, 竞品名原样保留 ✓")


# ── §3 起量后干预: 只认做过的标签 ──────────────────────────────────────────
DONE = (["成功"], ["补控成功"], ["交付前补控成功"], ["控住后掉了"], ["成功", "待做评论"],
        ["待安排贴主自评回复", "控住后掉了"], "成功, 待做评论", [{"text": "成功"}])
PENDING = (["待置顶"], ["待做评论"], ["待安排贴主自评"], ["待安排贴主自评回复"], ["等解封后控评"],
           ["待解封后控评"], ["素人退出无法回收"], "待置顶", [{"text": "待做评论"}], ["待置顶", "待做评论"])


def _routes(mapping: dict, fields: dict):
    note, _, _ = engine.transform_row(mapping, "r", fields)
    return _flags(note).get("comment_maintained_routes")


def check_posthoc_pending() -> None:
    for v in DONE:
        assert engine.posthoc_done_labels(v), f"§3 做过的标签被滤掉了: {v!r}"
    for v in PENDING:
        assert engine.posthoc_done_labels(v) == [], f"§3 待办 / 做不成的标签不该算做过: {v!r}"
    nuc = c.load_mapping("NUC_phase1")      # 爆帖置顶评论 → typed pinned_comment
    qd = c.load_mapping("HXZ_QD")           # 爆帖控评置顶 → raw_extra
    fb = c.load_mapping("HXZ_FB")           # 爆帖置顶评论 → raw_extra
    base = {"文案": "正文", "状态": "爆贴"}
    for v in DONE:
        assert _routes(nuc, {**base, "爆帖置顶评论": v}) == [POSTHOC], f"§3 NUC typed {v!r}"
        assert _routes(qd, {**base, "爆帖控评置顶": v}) == [POSTHOC], f"§3 HXZ_QD {v!r}"
        assert _routes(fb, {**base, "爆帖置顶评论": v}) == [POSTHOC], f"§3 HXZ_FB {v!r}"
    for v in PENDING:
        assert _routes(nuc, {**base, "爆帖置顶评论": v}) is None, f"§3 NUC typed 待办 {v!r} 被当成做过"
        assert _routes(qd, {**base, "爆帖控评置顶": v}) is None, f"§3 HXZ_QD 待办 {v!r} 被当成做过"
        assert _routes(fb, {**base, "爆帖置顶评论": v}) is None, f"§3 HXZ_FB 待办 {v!r} 被当成做过"
    # typed 列的值本身不动 (只决定算不算干预)
    note, _, _ = engine.transform_row(nuc, "r", {**base, "爆帖置顶评论": ["待置顶"]})
    assert note.get("pinned_comment") == ["待置顶"], note.get("pinned_comment")
    # reason 文字不变 (已经标过的行每晚写出同一份 JSON)
    note, _, _ = engine.transform_row(nuc, "r", {**base, "爆帖置顶评论": ["成功"]})
    assert "typed 列 pinned_comment 非空 = 做了置顶" in _flags(note).get("comment_maintained_reason", "")
    # 同步脚本用的就是 _common 那一个 (闸二敏感性重跑也用它, G-25; check_gate2_run §8r 另钉闸二那头)
    assert engine.posthoc_done_labels is c.posthoc_done_labels, "§3 同步脚本又有了自己的一份 posthoc_done_labels"
    # 反证 ④: 不滤待办 → 待办被当成做过 (这节真的在测过滤)
    saved = c._CM_POSTHOC_PENDING_RE
    c._CM_POSTHOC_PENDING_RE = re.compile(r"(?!)")
    try:
        assert _routes(nuc, {**base, "爆帖置顶评论": ["待置顶"]}) == [POSTHOC], "§3 反证没变红"
    finally:
        c._CM_POSTHOC_PENDING_RE = saved
    print(f"  §3 起量后干预: {len(DONE)} 种做过的写法算, {len(PENDING)} 种待办 / 做不成的不算 "
          "(typed pinned_comment / raw_extra 两路); 值不动、reason 不变; 不滤就变红 (反证) ✓")


# ── §4 映射漂移 ─────────────────────────────────────────────────────────────
# (项目, 列): linkcheck 写的、11-25 生产里落在 _undeclared 的列 (列体检 §3a #7)。只声明进 raw_extra, 不映 typed 列。
DECLARE = {
    "ANSHEN_phase1": ("作品ID", "整理状态", "整理时评论数", "整理时互动数", "互动数", "观众分析"),
    "BJS_phase1": ("互动数", "观众分析"),
    "BJS_phase2": ("评估基线时间", "评估基线评论数"),
    "HATHERINE_phase1": ("下次检查时间", "作品ID", "整理状态", "整理时评论数", "整理时互动数", "蓝词来源",
                         "评估基线时间", "评估基线评论数"),
    "SPX_phase1": ("数据整理", "作品ID", "整理状态", "整理时评论数", "整理时互动数", "蓝词来源",
                   "评估基线时间", "评估基线评论数", "限流前评论数"),
    "TUGE_phase1": ("下次检查时间", "作品ID", "整理状态", "整理时评论数", "整理时互动数", "蓝词来源",
                    "评估基线时间", "评估基线评论数", "搜索关键词", "互动数"),
}
GONE = {"SPX_phase1": ("数据汇总",), "HATHERINE_phase1": ("下次巡查时间",),
        "TUGE_phase1": ("下次巡查时间", "点赞数", "收藏数")}
# 这些列只当留痕, 永远不映 typed 列 (评估基线评论数 / 整理时评论数 不是评论数; 下次检查时间 是 Excel 序列日)
NEVER_TYPED = ("评估基线评论数", "整理时评论数", "下次检查时间", "下次巡查时间", "限流前评论数")


def check_mapping_drift() -> None:
    n = 0
    for pid, cols in DECLARE.items():
        m = c.load_mapping(pid)
        allow = set(m.get("project_specific_fields_to_raw_extra") or [])
        for col in cols:
            assert col in allow, f"§4 {pid}: 「{col}」没声明进 raw_extra, 还会落 _undeclared"
            n += 1
        row = {"笔记内容": "正文", "文案": "正文", **{col: "x" for col in cols}}
        note, _, und = engine.transform_row(m, "r", row)
        assert not set(cols) & set(und), f"§4 {pid}: 这些列还在 _undeclared: {sorted(set(cols) & set(und))}"
        rx = note.get("raw_extra") or {}
        assert all(rx.get(col) == "x" for col in cols), f"§4 {pid}: 没落到 raw_extra 顶层"
    for pid, cols in GONE.items():
        m = c.load_mapping(pid)
        declared = set(m["field_mapping"]) | set(m.get("project_specific_fields_to_raw_extra") or [])
        for col in cols:
            assert col not in declared, f"§4 {pid}: 还声明着已经不在表里的「{col}」"
    for f in sorted((ROOT / "mappings").glob("*.yaml")):
        if f.stem.startswith("_"):
            continue
        fm = c.load_mapping(f.stem)["field_mapping"]
        bad = [col for col in NEVER_TYPED if col in fm]
        assert not bad, f"§4 {f.stem}: {bad} 只能留痕, 不能映 typed 列 / 中间量"
    print(f"  §4 映射漂移: {n} 个 (项目, 列) 声明进 raw_extra、不再落 _undeclared; 旧名 / 已删的列不再声明; "
          "基线评论数 / 下次检查时间 这类列哪张表都没映 typed 列 ✓")


# ── §5 「评论关键词」注释 ─────────────────────────────────────────────────────
# 11-25 之前三份 mapping 的写法: 「运营定义的评论区蓝词」「= 运营定义的蓝词」。同一行同时列了好几列名的说明不算。
_WRONG_KEYWORD_NOTE = re.compile(r"评论关键词.*(?:定义的评论区蓝词|=\s*运营定义的蓝词)")


def check_keyword_comments() -> None:
    assert _WRONG_KEYWORD_NOTE.search("  - 评论关键词            # 运营定义的评论区蓝词 —— 同 TUGE 先例")
    assert _WRONG_KEYWORD_NOTE.search("      9) 评论关键词列(多选: 途鸽/途鸽求职)= 运营定义的蓝词;")
    bad = []
    for f in sorted((ROOT / "mappings").glob("*.yaml")):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if _WRONG_KEYWORD_NOTE.search(line):
                bad.append(f"{f.name}:{i}")
    assert not bad, f"§5 「评论关键词」是我们自己铺评的关键词, 不是蓝词; 这些注释还写着蓝词: {bad}"
    print("  §5 「评论关键词」注释: 没有一处再写成蓝词 ✓")


def main() -> int:
    check_commenter_codes()
    check_blue_keywords()
    check_posthoc_pending()
    check_mapping_drift()
    check_keyword_comments()
    print("\ncheck_column_audit_fixes: 5 节全过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
