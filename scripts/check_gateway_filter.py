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
  · 特征层只有 G1 (标题 + 第一句) 答成、其余全被拦也落库 —— 单篇规则拦不住中转站整体收紧, 靠 features-sync /
    backfill-features 跨批合计: 本轮 ≥3 篇被拦 → 红。这里把 workflow 里那几行 (# D-125 gf、↳ 那行) 原样抠出来跑。
  · essence: api 失败全是被拦 → gateway_filtered (不计 systemic, 只剩这一篇时不判红); 混着别的 api 错 →
    systemic; 纯校验类 → None。一轮 ≥3 篇被拦且一篇没成 → 先拿无害假笔记探一次: 探针也被拦才判红 (被拦的篇
    夜夜回来, 一个项目攒到 3 篇不该天天红); 探针不带原笔记的正文。
  · 反证: 拿掉识别 (is_gateway_filtered 恒 False) → 被拦的组回到 api_error + systemic。
挡不住什么:
  · 中转站换了报错文案 (不再带 sensitive_words_detected) —— 那就回到 api_error, 表现和以前一样 (红, 不丢数)。
  · 被拦的题以后能不能答 —— 记 NULL 之后要靠 backfill-features reannotate 重抽。
"""

from __future__ import annotations

import io
import json
import logging
import os
import pathlib
import subprocess
import sys
import tempfile
from unittest.mock import patch

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

    # C2. 只有 G1 (标题 + 第一句) 答成、其余全被拦: 单篇规则放行 (落库), 中转站整体收紧靠 workflow 跨批合计 (见 check_workflows)
    rest = {q for i, g in enumerate(groups) if i != 0 for q in g}
    res = afp.annotate_note(bank, note, mapping, model="m", extractor="llm:m", run_tag="primary",
                            single=False, code_only=False, dry_run=False, llm=make_llm(rest))
    assert res["stats"]["groups_ok"] == 1 and res["stats"]["filtered"] == len(groups) - 1 and not afp._is_systemic(res["stats"]), res["stats"]

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
    # reannotate 时有一组被拦也算 systemic: 同 PK 覆盖会拿 NULL 盖掉原来答好的题
    assert not afp._is_systemic({"filtered": 1, "groups_ok": 5}) and afp._is_systemic({"filtered": 1, "groups_ok": 5}, reannotate=True)

    # E. 反证: 拿掉识别 → 被拦的组回到 api_error + systemic (以前的行为)
    saved = afp.is_gateway_filtered
    afp.is_gateway_filtered = lambda e: False
    try:
        res = afp.annotate_note(bank, note, mapping, model="m", extractor="llm:m", run_tag="primary",
                                single=False, code_only=False, dry_run=False, llm=make_llm(blocked))
        assert res["stats"]["filtered"] == 0 and afp._is_systemic(res["stats"]), res["stats"]
    finally:
        afp.is_gateway_filtered = saved
    # F. main() 端到端 (假库): 部分被拦 → 落库、Done 行 gateway_filtered=1、退出 0; 同一篇 --reannotate → 一行不落 (不拿 NULL 盖旧答案)
    def run_main(argv):
        written = []
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "x"}), \
                patch.object(afp, "get_supabase_client", return_value=object()), \
                patch.object(afp, "load_mapping", return_value=mapping), \
                patch.object(afp, "fetch_notes", return_value=[note]), \
                patch.object(afp, "fetch_done_ids", return_value=set()), \
                patch.object(afp, "write_answers", side_effect=lambda sb, rows, dry_run: written.extend(rows)), \
                patch.object(afp, "write_raw_counts"), \
                patch.object(afp, "_llm", make_llm(blocked)), \
                tempfile.TemporaryDirectory() as td:
            buf = io.StringIO(); h = logging.StreamHandler(buf); afp.logger.addHandler(h)
            try:
                rc = afp.main(argv + ["--qps", "0", "--failed-queue", f"{td}/fq.jsonl"])
            finally:
                afp.logger.removeHandler(h)
        return rc, written, buf.getvalue()
    rc, written, log = run_main(["T"])
    assert rc == 0 and written and '"gateway_filtered": 1' in log and "gateway_filtered T_1:" in log, (rc, len(written))
    rc, written, log = run_main(["T", "--reannotate"])
    assert not written and "systemic T_1:" in log, (rc, len(written))
    print("  ✓ 特征层: 被拦的组 NULL + gateway_filtered、其余照常、整篇落库 (标记题被拦也落); 全被拦 / 普通 api 挂仍 systemic;"
          " reannotate 时被拦不覆盖旧答案; 反证拿掉识别回到 systemic")


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
    assert f({"ok": 0, "failed_after_retry": 3, "gateway_filtered": 3}) == 1     # ≥3 篇被拦、一篇没成、没探: 红
    assert f({"ok": 0, "failed_after_retry": 3, "gateway_filtered": 3, "gateway_canary_ok": False}) == 1
    assert f({"ok": 0, "failed_after_retry": 3, "gateway_filtered": 3, "gateway_canary_ok": True}) == 0   # 探针过了: 是各篇自己的
    assert f({"ok": 1, "failed_after_retry": 5, "gateway_filtered": 5}) == 0
    assert f({"ok": 0, "systemic_failed": 1}) == 1 and f({"ok": 0, "hygiene_failed": 1}) == 1   # 原有两条不变

    # 探针: 项目上下文照旧, 正文换成无害假笔记 (原笔记的标题 / 正文 / 话题一个字都不带); 被拦 → False
    secret = "原笔记里的词XYZ"
    note = {"note_id": "P_1", "title": secret, "body": secret, "raw_content": secret, "hashtags": [secret],
            "intent": "种草", "target_blue_keywords": ["推车"], "raw_extra": {"_direction_raw": "带娃出行", "x": secret}}
    seen = []
    def ok_call(prompt, model, cached_system=None):
        seen.append((prompt, cached_system or "")); return "{}"
    def blocked_call(prompt, model, cached_system=None):
        raise FakeInternalServerError(FILTERED_MSG)
    saved = ess.call_claude
    try:
        ess.call_claude = ok_call
        assert ess._gateway_canary("m", {"brand": "某牌", "product": "推车"}, note) is True
        assert seen and all(secret not in u and secret not in s for u, s in seen), seen
        assert "推车" in seen[0][0] and "带娃出行" in seen[0][0], seen[0][0][:300]   # 项目上下文还在
        ess.call_claude = blocked_call
        assert ess._gateway_canary("m", {"brand": "某牌"}, note) is False
    finally:
        ess.call_claude = saved
    print("  ✓ essence: 全是被拦 → gateway_filtered、混别的 api 错 → systemic、校验类 → None; 只剩被拦的篇不红;"
          " ≥3 篇全拦先探一次, 探针也被拦才红; 探针不带原笔记正文")


def check_essence_main_canary() -> None:
    """main() 真把探针接上: 3 篇被拦、一篇没成 → 多一次调用; 探针过 → 不红, 探针也被拦 → 红;
    --dry-run 不调; 混着 systemic 不探、照红。"""
    good = json.dumps({"essence": {"emotional_lever": "焦虑撬动", "emotional_valence": "negative",
                                   "emotional_intensity": "high", "human_truth_archetype": ["健康焦虑"],
                                   "trend_dependencies": ["通用"], "content_format": "情感叙事"}, "audience": {}})
    bad = [f"原笔记被拦词BAD{i}" for i in range(3)]

    def run(block, extra=(), other_err=False):
        notes = [{"note_id": f"P_{i}", "project_id": "P", "title": f"t{i}", "body": b,
                  "raw_content": f"【标题】t{i}\n【正文】{b}", "hashtags": [], "intent": "种草",
                  "target_blue_keywords": ["推车"], "raw_extra": {"_direction_raw": "带娃出行"},
                  "projects": {"brand": "某牌", "product": "推车"}} for i, b in enumerate(bad)]
        if other_err:
            notes.append(dict(notes[0], note_id="P_X", body="SYSTEMIC", raw_content="【正文】SYSTEMIC",
                              projects={"brand": "某牌", "product": "推车"}))
        calls = []

        def call(prompt, model, *, cached_system=None):
            calls.append(prompt)
            if "SYSTEMIC" in prompt:
                raise FakeInternalServerError("Error code: 500 - upstream error")
            if block(prompt):
                raise FakeInternalServerError(FILTERED_MSG)
            return good
        buf = io.StringIO(); h = logging.StreamHandler(buf); ess.logger.addHandler(h)
        try:
            with tempfile.TemporaryDirectory() as td, \
                    patch.object(sys, "argv", ["x", "P", "--qps", "0", "--failed-queue", f"{td}/q.jsonl", *extra]), \
                    patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake"}), \
                    patch.object(ess, "load_mapping", return_value={}), \
                    patch.object(ess, "get_supabase_client", return_value=object()), \
                    patch.object(ess, "fetch_unannotated_notes", return_value=notes), \
                    patch.object(ess, "get_sub_directions_for_note", return_value=None), \
                    patch.object(ess, "write_essence_back"), \
                    patch.object(ess, "call_claude", side_effect=call):
                rc = ess.main()
        finally:
            ess.logger.removeHandler(h)
        return rc, len(calls), buf.getvalue()

    rc, n, log = run(lambda p: any(b in p for b in bad))
    assert rc == 0 and n == 4 and '"gateway_filtered": 3' in log, (rc, n)          # 探针过了: 是各篇自己的, 不红
    rc, n, _ = run(lambda p: True)
    assert rc == 1 and n == 4, (rc, n)                                               # 探针也被拦: 红
    rc, n, _ = run(lambda p: True, extra=["--dry-run"])
    assert rc == 0 and n == 0, (rc, n)                                               # dry-run 不调
    rc, n, _ = run(lambda p: any(b in p for b in bad), other_err=True)
    assert rc == 1 and n == 4, (rc, n)                                               # 混着 systemic: 不探, 照红
    print("  ✓ essence main(): 3 篇被拦 → 探一次; 探针过不红、被拦红; dry-run 不调; 混着 systemic 不探照红")


def _gf_line(wf: str) -> str:
    lines = [ln.strip() for ln in wf.splitlines() if ln.rstrip().endswith("# D-125 gf")]
    assert lines, "workflow 里找不到 # D-125 gf 那行"
    return lines[0]


def _bash(script: str) -> str:
    return subprocess.run(["bash", "-eo", "pipefail", "-c", script], capture_output=True, text=True, check=True).stdout


def check_workflows() -> None:
    root = pathlib.Path(__file__).resolve().parent.parent / ".github" / "workflows"
    fs = (root / "features-sync.yml").read_text(encoding="utf-8")
    bf = (root / "backfill-features.yml").read_text(encoding="utf-8")
    done = 'Done: {"ok": 2, "failed": 0, "systemic_failed": 0, "gateway_filtered": 2, "groups_ok": 9}'
    with tempfile.TemporaryDirectory() as td:
        j = pathlib.Path(td) / "r.json"
        for wf, path in ((fs, "/tmp/feat.json"), (bf, "/tmp/b.json")):
            line = _gf_line(wf).replace(path, str(j))
            for tail, want in (("x · " + done + "\n", "2"), ("没有 Done 行\n", "0"), ("Done: {坏 json\n", "0"), (None, "0")):
                j.write_text(json.dumps({"stdout_tail": tail}) if tail is not None else "{}", encoding="utf-8")
                got = _bash(line + '\necho "$gf"').strip()
                assert got == want, (path, tail, got)
        # ↳ 那行: 只认 logger 分隔符后面的 systemic / gateway_filtered, 不吃单问的 single_gateway_filtered q=...
        arrow = next(ln.strip() for ln in fs.splitlines() if "↳" in ln).replace("/tmp/feat.json", str(j))
        tail = ("2026 [WARNING] annotate_features · systemic A_1: api_error: boom\n"
                "2026 [WARNING] annotate_features · single_gateway_filtered q=opening_type: InternalServerError(x)\n"
                "2026 [WARNING] annotate_features · gateway_filtered B_2: 2 组被中转站敏感词拦截\n")
        j.write_text(json.dumps({"stdout_tail": tail}), encoding="utf-8")
        out = _bash(arrow)
        assert "↳ systemic A_1:" in out and "↳ gateway_filtered B_2:" in out and "q=" not in out, out
    # 跨批合计的红线在: features-sync 一处, backfill-features 两种模式各一处
    assert 'if [ "$gf_total" -ge 3 ]; then' in fs and fs.count("gf_total=$((gf_total + gf))") == 1
    assert bf.count('[ "$gf_total" -lt 3 ] ||') == 2 and bf.count("gf_total=$((gf_total + gf))") == 2
    # 到 3 篇就停 (不是跑完才红): features-sync 在批循环里 break、项目循环里再 break; backfill 两种模式都在循环里 exit
    i_gf, i_stop, i_proj, i_red = (fs.index("# D-125 gf"), fs.index('if [ "$gf_total" -ge 3 ]; then gf_stop=1; break; fi'),
                                    fs.index('if [ "$gf_stop" = "1" ]'), fs.index('if [ "$gf_total" -ge 3 ]; then\n'))
    assert i_gf < i_stop < i_proj < i_red, (i_gf, i_stop, i_proj, i_red)
    for anchor in ("gf_total=$((gf_total + gf))\n              # 到 3 篇就停", "gf_total=$((gf_total + gf))\n            [ \"$gf_total\" -lt 3 ] ||"):
        assert anchor in bf, anchor
    print("  ✓ workflow: # D-125 gf 那行从 Done 行取 gateway_filtered (没有 / 坏了按 0, pipefail 下不炸); ↳ 那行不吃单问日志; ≥3 篇的红线在")


def main() -> int:
    check_detect()
    check_features(fb.load_bank())
    check_essence()
    check_essence_main_canary()
    check_workflows()
    print("✓ 中转站敏感词拦截 (D-125): 按单篇内容问题计, 不拖住队列、不误判红; 全拦 / 整体拦截仍红")
    return 0


if __name__ == "__main__":
    sys.exit(main())
