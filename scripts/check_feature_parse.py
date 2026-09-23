"""
check_feature_parse.py —— 特征层守卫 8 (D-083): 模型回复的容错解析 + 「没答」的单题兜底。

    cd scripts && python check_feature_parse.py

守得住什么:
  · parse_answers: 围栏 / 闲话 / 字符串里原样换行 / evidence 里没转义的英文双引号 —— 四种真实见过
    (或从 2026-09-23 闸一 59 格整组 missing 反推出来) 的坏回复都能解析出 answers; 纯散文 / 空 → None。
  · 捞出来的 evidence 仍要过 validate_answers 的原文子串校验 (守卫 3 不被绕开)。
  · ask_group: 整组解析失败记 json_parse_failed (不冒充 missing); 重问后仍「没答」的题逐题单问;
    单问只在失败时发生 (正常一篇 0 次); 单问 api 挂 → 那题 api_error、整组 systemic (整篇不落行);
    单问解析出 JSON 但没这题 → missing (如实)。
  · 反证: 把容错层拿掉 (严格 json.loads) 换行那份就解析不出; 把单题兜底关掉 garbage 那组三题就全 NULL。
挡不住什么:
  · 模型把答案本身答错; evidence 捞错但恰好也是原文子串 (守卫 3 只查子串, 不查是不是那一处)。
  · 回复里根本没有 "id"/"answer"/"evidence" 三元组 (比如按题号答) —— 仍是 missing, 靠单问兜底。
"""

from __future__ import annotations

import json
import sys

import feature_bank as fb
import annotate_feature_pass as afp

RAW = "【标题】戒烟第几天最难熬？\n【正文】上周三凌晨两点在公司茶水间饿醒。我妈：\"你身上什么味儿？\"嗓子像被砂纸磨过。\n你们戒烟第几天了？#戒烟#"


def _note():
    return {"note_id": "T_1", "project_id": "T", "title": None, "raw_content": RAW,
            "target_blue_keywords": ["戒烟"], "projects": {"brand": "某牌", "product": "尼古丁贴"}}


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


def check_parse(bank, spans) -> None:
    ok = json.dumps({"answers": _good(bank, ["turning_point"])}, ensure_ascii=False)
    assert fb.parse_answers(ok)["answers"][0]["id"] == "turning_point"
    # 1. 围栏 + 闲话
    assert fb.parse_answers("好的，结果如下：\n```json\n" + ok + "\n```\n以上。")["answers"][0]["id"] == "turning_point"
    # 2. 字符串里原样换行 (严格 JSON 解析失败) —— 反证: json.loads 本身就解析不出
    nl = '{"answers":[{"id":"judged_by_others","answer":"是","evidence":"砂纸磨过。\n你们戒烟"}]}'
    try:
        json.loads(nl); raise AssertionError("反证失败: 严格 JSON 居然接受了原样换行")
    except json.JSONDecodeError:
        pass
    got = fb.parse_answers(nl)
    assert got and got["answers"][0]["evidence"] == "砂纸磨过。\n你们戒烟", got
    v = fb.validate_answers(bank, ["judged_by_others"], got, spans)
    assert v["judged_by_others"]["answer"] == "是", v      # 换行处的证据仍是原文子串 (去空白比)
    # 3. evidence 里没转义的英文双引号 —— 反证: 两层 json.loads 都解析不出, 靠正则捞
    dq = '{"answers":[{"id":"has_direct_quote","answer":"是","evidence":"我妈："你身上什么味儿？""},{"id":"has_specific_time","answer":"是","evidence":"凌晨两点"}]}'
    for strict in (True, False):
        try:
            json.loads(dq, strict=strict); raise AssertionError("反证失败: json.loads 接受了没转义的引号")
        except json.JSONDecodeError:
            pass
    got = fb.parse_answers(dq)
    assert got and [a["id"] for a in got["answers"]] == ["has_direct_quote", "has_specific_time"], got
    v = fb.validate_answers(bank, ["has_direct_quote", "has_specific_time"], got, spans)
    assert v["has_direct_quote"]["answer"] == "是" and v["has_specific_time"]["answer"] == "是", v
    # 4. 捞出来的证据不是原文 → 守卫 3 照样拦 (容错不绕开硬闸)
    fake = '{"answers":[{"id":"has_direct_quote","answer":"是","evidence":"这句"不在"原文里"}]}'
    v = fb.validate_answers(bank, ["has_direct_quote"], fb.parse_answers(fake), spans)
    assert v["has_direct_quote"]["invalid_reason"] == fb.INVALID_EVIDENCE_NOT_FOUND, v
    # 5. 散文 / 空 / 只有别的键 → None
    for bad in ("抱歉，我无法完成这个标注。", "", "```json\n```", '{"result": "ok"}', '[1,2,3]'):
        assert fb.parse_answers(bad) is None, bad
    # 6. (自审 on #156) 正则路里的 JSON 转义要还原: 一题未转义引号把 JSON 弄断, 另一题证据里是合法的 \n
    mixed = ('{"answers":[{"id":"turning_point","answer":"否","evidence":""},'
             '{"id":"judged_by_others","answer":"是","evidence":"我妈："你身上什么味儿？""},'
             '{"id":"negative_outcome_happened","answer":"是","evidence":"砂纸磨过。\\n你们戒烟"}]}')
    v = fb.validate_answers(bank, ["turning_point", "judged_by_others", "negative_outcome_happened"], fb.parse_answers(mixed), spans)
    assert v["judged_by_others"]["answer"] == "是" and v["negative_outcome_happened"]["answer"] == "是", v
    # 7. 内嵌 `",`: 证据锚在 } 上, 捞到完整 45 字 → 超 30 字 / 不是子串 → NULL, 不是截断前缀被当成好证据
    long_dq = ('{"answers":[{"id":"has_direct_quote","answer":"是","evidence":"上周三凌晨两点在公司茶水间饿醒,我妈说:"你身上什么味儿?",我说没事就是嗓子像被砂纸磨过"}]}')
    got = fb.parse_answers(long_dq)
    assert len(got["answers"][0]["evidence"]) == 45, got
    assert fb.validate_answers(bank, ["has_direct_quote"], got, spans)["has_direct_quote"]["answer"] is None
    # 8. 合法 JSON 后面跟闲话 (闲话里还有大括号) → 第一个完整对象照常解析
    chatter = json.dumps({"answers": [{"id": "judged_by_others", "answer": "是", "evidence": "砂纸磨过。\n你们戒烟"}]}, ensure_ascii=False) + "\n注：格式为 {id, answer, evidence}。"
    assert fb.validate_answers(bank, ["judged_by_others"], fb.parse_answers(chatter), spans)["judged_by_others"]["answer"] == "是"
    # 9. 形状不对但三元组在: 裸对象 (单问时常见) / 键名打错 / answers 是对象 / 裸列表 → 扶正
    for shape in ('{"id":"turning_point","answer":"否","evidence":""}',
                  '{"answer":[{"id":"turning_point","answer":"否","evidence":""}]}',
                  '{"answers":{"id":"turning_point","answer":"否","evidence":""}}',
                  '[{"id":"turning_point","answer":"否","evidence":""}]'):
        got = fb.parse_answers(shape)
        assert got and got["answers"][0]["id"] == "turning_point", shape
    # 10. \uXXXX / \\ 也还原
    got = fb.parse_answers('{"answers":[{"id":"x","answer":"\\u662f","evidence":"a\\\\b"}]}')
    assert got["answers"][0]["answer"] == "是" and got["answers"][0]["evidence"] == "a\\b", got
    print("  ✓ parse_answers: 围栏 / 换行 / 未转义引号 / 转义还原 / 内嵌 \", / 闲话 / 形状扶正; 散文 None; 捞出来的证据仍过守卫 3")


def check_fallback(bank, note, mapping) -> None:
    calls: list[tuple[str, str]] = []

    def good_llm(system, user, model):
        calls.append((system, user))
        return json.dumps({"answers": _good(bank, _ids(system))}, ensure_ascii=False)

    # A. 正常回复: 6 组、0 重问、0 单问
    res = afp.annotate_note(bank, note, mapping, model="m", extractor="llm:m", run_tag="primary",
                            single=False, code_only=False, dry_run=False, llm=good_llm)
    assert len(calls) == 6 and res["stats"]["singles"] == 0 and res["stats"]["groups_retry"] == 0, (len(calls), res["stats"])
    assert not any(r["invalid_reason"] in (fb.INVALID_MISSING, fb.INVALID_JSON) for r in res["rows"])

    # B. G6 那组两次都答散文 → 整组 json_parse_failed → 三题各单问一次, 单问答得出来
    calls.clear()
    def garbage_llm(system, user, model):
        calls.append((system, user))
        ids = _ids(system)
        if "turning_point" in ids and len(ids) > 1:
            return "抱歉，我无法按这个格式作答。"
        return json.dumps({"answers": _good(bank, ids)}, ensure_ascii=False)
    res = afp.annotate_note(bank, note, mapping, model="m", extractor="llm:m", run_tag="primary",
                            single=False, code_only=False, dry_run=False, llm=garbage_llm)
    by = {r["question_id"]: r for r in res["rows"]}
    assert len(calls) == 6 + 1 + 3, len(calls)                         # 6 组 + 1 重问 + 3 单问
    assert res["stats"]["singles"] == 3 and res["stats"]["groups_retry"] == 1 and res["stats"]["systemic"] == 0, res["stats"]
    for q in ("turning_point", "judged_by_others", "negative_outcome_happened"):
        assert by[q]["answer"] == "否" and by[q]["invalid_reason"] is None, by[q]
    retry_user = calls[6][1]
    assert "解析不出 JSON" in retry_user and "英文双引号写成" in retry_user, retry_user[-300:]
    single_sys = calls[7][0]
    assert len(_ids(single_sys)) == 1, _ids(single_sys)                   # 兜底确实是单题

    # C. 单问也挂 (api) → 那几题记 api_error, 整组 systemic (整篇不落行, 下轮重跑), 不抛
    calls.clear()
    def garbage_then_boom(system, user, model):
        calls.append((system, user))
        ids = _ids(system)
        if "turning_point" in ids and len(ids) > 1:
            return "抱歉。"
        if len(ids) == 1 and ids[0] in ("turning_point", "judged_by_others", "negative_outcome_happened"):
            raise RuntimeError("503")
        return json.dumps({"answers": _good(bank, ids)}, ensure_ascii=False)
    res = afp.annotate_note(bank, note, mapping, model="m", extractor="llm:m", run_tag="primary",
                            single=False, code_only=False, dry_run=False, llm=garbage_then_boom)
    by = {r["question_id"]: r for r in res["rows"]}
    assert by["turning_point"]["invalid_reason"] == fb.INVALID_API and res["stats"]["systemic"] == 1, (by["turning_point"], res["stats"])
    assert len(res["stats"]["errors"]) == 3 and all("single_api_error" in e for e in res["stats"]["errors"])
    # C2. 单问解析出 JSON 但没这题 → 如实记 missing (不再是 json_parse_failed), 不算 systemic
    calls.clear()
    def garbage_then_wrong_id(system, user, model):
        calls.append((system, user))
        ids = _ids(system)
        if "turning_point" in ids and len(ids) > 1:
            return "抱歉。"
        if len(ids) == 1 and ids[0] in ("turning_point", "judged_by_others", "negative_outcome_happened"):
            return json.dumps({"answers": [{"id": "has_specific_time", "answer": "否", "evidence": ""}]}, ensure_ascii=False)
        return json.dumps({"answers": _good(bank, ids)}, ensure_ascii=False)
    res = afp.annotate_note(bank, note, mapping, model="m", extractor="llm:m", run_tag="primary",
                            single=False, code_only=False, dry_run=False, llm=garbage_then_wrong_id)
    by = {r["question_id"]: r for r in res["rows"]}
    assert by["turning_point"]["invalid_reason"] == fb.INVALID_MISSING and res["stats"]["systemic"] == 0 and res["stats"]["singles"] == 3, (by["turning_point"], res["stats"])

    # D. 模型漏一题 (其余正常) → 只那一题 missing → 重问 → 仍漏 → 单问答出
    calls.clear()
    def drop_one(system, user, model):
        calls.append((system, user))
        ids = _ids(system)
        ans = _good(bank, [q for q in ids if q != "judged_by_others" or len(ids) == 1])
        return json.dumps({"answers": ans}, ensure_ascii=False)
    res = afp.annotate_note(bank, note, mapping, model="m", extractor="llm:m", run_tag="primary",
                            single=False, code_only=False, dry_run=False, llm=drop_one)
    by = {r["question_id"]: r for r in res["rows"]}
    assert len(calls) == 6 + 1 + 1 and res["stats"]["singles"] == 1, (len(calls), res["stats"])
    assert by["judged_by_others"]["answer"] == "否" and by["turning_point"]["answer"] == "否"

    # E. 反证: 把单题兜底关掉 (让 _UNANSWERED 为空) → garbage 那组三题全 NULL
    saved = afp._UNANSWERED
    afp._UNANSWERED = ()
    try:
        calls.clear()
        res = afp.annotate_note(bank, note, mapping, model="m", extractor="llm:m", run_tag="primary",
                                single=False, code_only=False, dry_run=False, llm=garbage_llm)
        by = {r["question_id"]: r for r in res["rows"]}
        assert len(calls) == 7 and all(by[q]["answer"] is None for q in ("turning_point", "judged_by_others", "negative_outcome_happened"))
    finally:
        afp._UNANSWERED = saved
    print("  ✓ ask_group: 解析失败记 json_parse_failed; 重问后仍没答 → 单题兜底 (正常 0 次, 坏组 3 次, 漏一题 1 次); 单问 api 挂 → api_error + systemic; 单问没这题 → missing; 反证关掉兜底三题全 NULL")


def main() -> int:
    bank = fb.load_bank()
    note = _note()
    mapping = {"project_id": "T", "field_mapping": {}, "title_extraction": "markers"}
    spans = fb.build_spans(RAW, mode="markers")
    check_parse(bank, spans)
    check_fallback(bank, note, mapping)
    print("✓ 守卫 8 (D-083): 容错解析 + 单题兜底, 反证都红")
    return 0


if __name__ == "__main__":
    sys.exit(main())
