"""
check_gateway_filter.py —— 中转站敏感词拦截 (D-125) 在 essence / 特征层两条 pass 里怎么算。

    cd scripts && python check_gateway_filter.py

背景: 中转站 (new-api) 判一次请求含敏感词就回 HTTP 500, message 里是 "sensitive_words_detected"。
10-23 XIWU_phase2 一篇正文里有个词在中转站词表里, 要引原句做证据的几组次次被拦, 以前按 api_error 记 systemic:
特征层整篇不落行、每批都排第一个重跑 (每批两个名额占一个), 项目只剩它一篇时 features-sync 就判红;
essence 只剩它一篇时 daily-sync 也判红。

守得住什么:
  · is_gateway_filtered: 认异常对象和 "api_error: InternalServerError(...)" 这种错误串; 别的 500 / 429 不认。
  · 特征层: 被拦的组那几题记 NULL + gateway_filtered, 其余组照常, 整篇落库 (标记题那行在) —— 不算 systemic;
    模型题全被拦 → 仍 systemic (整篇不落行), 不悄悄写一篇空答案; 普通 api 挂照旧 systemic。
  · essence: api 失败全是被拦 → gateway_filtered (不计 systemic, 只剩这一篇时不判红); 混着别的 api 错 →
    systemic; 纯校验类 → None。一轮 ≥3 篇被拦且一篇没成 → 判红 (中转站整体开了拦截)。
  · 反证: 拿掉识别 (is_gateway_filtered 恒 False) → 被拦的组回到 api_error + systemic。
挡不住什么:
  · 中转站换了报错文案 (不再带 sensitive_words_detected) —— 那就回到 api_error, 表现和以前一样 (红, 不丢数)。
  · 被拦的题以后能不能答 —— 记 NULL 之后要靠 backfill-features reannotate 重抽。
"""

from __future__ import annotations

import json
import sys

import _common
import annotate_essence_pass as ess
import annotate_feature_pass as afp
import feature_bank as fb

FILTERED_MSG = ("Error code: 500 - {'error': {'type': 'new_api_error', 'message': "
                "'sensitive_words_detected (request id: 2026102319352577)'}, 'type': 'error'}")
RAW = "【标题】周末带娃去哪儿？\n【正文】上周六早上九点去了公园。孩子说：“还想再来。”腿走得发酸。\n大家周末都带娃去哪？#周末#"


class FakeInternalServerError(Exception):
    """形状像 anthropic.InternalServerError: str() 是 'Error code: 500 - {...}'。"""


def _note():
    return {"note_id": "T_1", "project_id": "T", "title": None, "raw_content": RAW,
            "target_blue_keywords": ["遛娃"], "projects": {"brand": "某牌", "product": "推车"}}


def _ids(system: str) -> list[str]:
    return [ln.split(" · ")[0].split(". ", 1)[1] for ln in system.splitlines() if " · 看【" in ln]


def _good(bank, ids):
    idx = fb.question_index(bank); out = []
    for q in ids:
        qq = idx[q]
        if qq["type"] == "bool":
            out.append({"id": q, "answer": "否", "evidence": ""})
        else:
            out.append({"id": q, "answer": "未出现" if q == "product_role" else fb.closed_set(qq)[0], "evidence": ""})
    return out


def check_detect() -> None:
    f = _common.is_gateway_filtered
    assert f(FakeInternalServerError(FILTERED_MSG))
    assert f(f"api_error: {FakeInternalServerError(FILTERED_MSG)!r}")
    assert f(f"retry_api_error: {FakeInternalServerError(FILTERED_MSG)!r}")
    assert not f(FakeInternalServerError("Error code: 500 - {'error': {'message': 'upstream error'}}"))
    assert not f("api_error: RateLimitError('Error code: 429 - Too many failed attempts')")
    assert not f(RuntimeError("503"))
    print("  ✓ is_gateway_filtered: 认异常和错误串里的 sensitive_words_detected; 别的 500 / 429 / 503 不认")


def check_features(bank) -> None:
    note = _note()
    mapping = {"project_id": "T", "field_mapping": {}, "title_extraction": "markers"}
    marker = afp.DONE_MARKER_QUESTION
    groups = list(fb.plan_calls(bank))
    marker_group = next(i for i, g in enumerate(groups) if marker in g)

    def make_llm(blocked):
        def llm(system, user, model):
            ids = _ids(system)
            if any(q in blocked for q in ids):
                raise FakeInternalServerError(FILTERED_MSG)
            return json.dumps({"answers": _good(bank, ids)}, ensure_ascii=False)
        return llm

    # A. 部分组被拦 (标记题那组没被拦): 被拦的几题 NULL + gateway_filtered, 其余照常, 不算 systemic, 落库
    blocked_groups = [i for i in range(len(groups)) if i not in (0, marker_group)][:2]
    blocked = {q for i in blocked_groups for q in groups[i]}
    res = afp.annotate_note(bank, note, mapping, model="m", extractor="llm:m", run_tag="primary",
                            single=False, code_only=False, dry_run=False, llm=make_llm(blocked))
    st = res["stats"]
    by = {r["question_id"]: r for r in res["rows"] if r["extractor"] == "llm:m"}
    assert st["systemic"] == 0 and st["filtered"] == len(blocked_groups) and st["groups_ok"] == len(groups) - len(blocked_groups), st
    for q in blocked:
        assert by[q]["answer"] is None and by[q]["invalid_reason"] == fb.INVALID_FILTERED, by[q]
    assert by[marker]["invalid_reason"] is None, by[marker]          # 标记题那行在 → 下轮不再重跑
    assert all(e.startswith("gateway_filtered: ") for e in st["errors"]), st["errors"]
    assert not afp._is_systemic(st)

    # B. 标记题那组也被拦 (但别的组答成): 仍落库, 标记题那行是 NULL + gateway_filtered —— 行在就算跑过
    res = afp.annotate_note(bank, note, mapping, model="m", extractor="llm:m", run_tag="primary",
                            single=False, code_only=False, dry_run=False, llm=make_llm(set(groups[marker_group])))
    by = {r["question_id"]: r for r in res["rows"] if r["extractor"] == "llm:m"}
    assert by[marker]["invalid_reason"] == fb.INVALID_FILTERED and not afp._is_systemic(res["stats"]), res["stats"]

    # C. 全被拦: 仍 systemic (整篇不落行), 不悄悄写一篇空答案
    every = {q for g in groups for q in g}
    res = afp.annotate_note(bank, note, mapping, model="m", extractor="llm:m", run_tag="primary",
                            single=False, code_only=False, dry_run=False, llm=make_llm(every))
    assert res["stats"]["groups_ok"] == 0 and res["stats"]["filtered"] == len(groups) and afp._is_systemic(res["stats"]), res["stats"]

    # D. 普通 api 挂 (不是被拦) 照旧 systemic; 被拦 + api 挂混在一篇里 → systemic
    def boom(system, user, model):
        if any(q in blocked for q in _ids(system)):
            raise FakeInternalServerError("Error code: 500 - {'error': {'message': 'upstream error'}}")
        return json.dumps({"answers": _good(bank, _ids(system))}, ensure_ascii=False)
    res = afp.annotate_note(bank, note, mapping, model="m", extractor="llm:m", run_tag="primary",
                            single=False, code_only=False, dry_run=False, llm=boom)
    by = {r["question_id"]: r for r in res["rows"] if r["extractor"] == "llm:m"}
    assert res["stats"]["systemic"] == len(blocked_groups) and afp._is_systemic(res["stats"]), res["stats"]
    assert all(by[q]["invalid_reason"] == fb.INVALID_API for q in blocked)
    assert afp._is_systemic({"systemic": 1, "filtered": 1, "groups_ok": 4})

    # E. 反证: 拿掉识别 → 被拦的组回到 api_error + systemic (以前的行为)
    saved = afp.is_gateway_filtered
    afp.is_gateway_filtered = lambda e: False
    try:
        res = afp.annotate_note(bank, note, mapping, model="m", extractor="llm:m", run_tag="primary",
                                single=False, code_only=False, dry_run=False, llm=make_llm(blocked))
        assert res["stats"]["filtered"] == 0 and afp._is_systemic(res["stats"]), res["stats"]
    finally:
        afp.is_gateway_filtered = saved
    print("  ✓ 特征层: 被拦的组 NULL + gateway_filtered、其余照常、整篇落库 (标记题被拦也落); 全被拦 / 普通 api 挂仍 systemic; 反证拿掉识别回到 systemic")


def check_essence() -> None:
    filtered = f"api_error: {FakeInternalServerError(FILTERED_MSG)!r}"
    other = "api_error: FakeInternalServerError(\"Error code: 500 - {'error': {'message': 'upstream error'}}\")"
    c = ess._classify_api_failure
    assert c([filtered]) == "gateway_filtered"
    assert c([f"retry_{filtered}"]) == "gateway_filtered"
    assert c([filtered, other]) == "systemic" and c([other]) == "systemic"
    assert c(["json_parse_failed_after_retry"]) is None and c([]) is None

    # _annotate_with_retry 真把被拦的异常记成带标记的 api_error (分类器吃到的就是这个形状)
    saved = ess.call_claude
    ess.call_claude = lambda p, m: (_ for _ in ()).throw(FakeInternalServerError(FILTERED_MSG))
    try:
        parsed, errors, _raw, _retry = ess._annotate_with_retry("prompt", "m")
    finally:
        ess.call_claude = saved
    assert parsed is None and c(errors) == "gateway_filtered", errors

    f = ess._exit_code_for_stats
    assert f({"ok": 0, "failed_after_retry": 1, "gateway_filtered": 1}) == 0     # 只剩被拦的那一篇: 不红
    assert f({"ok": 0, "failed_after_retry": 2, "gateway_filtered": 2}) == 0
    assert f({"ok": 0, "failed_after_retry": 3, "gateway_filtered": 3}) == 1     # 一轮 ≥3 篇被拦、一篇没成: 红
    assert f({"ok": 1, "failed_after_retry": 5, "gateway_filtered": 5}) == 0
    assert f({"ok": 0, "systemic_failed": 1}) == 1 and f({"ok": 0, "hygiene_failed": 1}) == 1   # 原有两条不变
    print("  ✓ essence: 全是被拦 → gateway_filtered、混别的 api 错 → systemic、校验类 → None; 只剩被拦的篇不红, ≥3 篇全拦才红")


def main() -> int:
    check_detect()
    check_features(fb.load_bank())
    check_essence()
    print("✓ 中转站敏感词拦截 (D-125): 按单篇内容问题计, 不拖住队列、不误判红; 全拦 / 整体拦截仍红")
    return 0


if __name__ == "__main__":
    sys.exit(main())
