"""
check_feature_orchestration.py —— 特征层编排自检 (D-070 起) + 续跑判据认得出 judge (D-085)。

    cd scripts && python check_feature_orchestration.py     # 编排 + 续跑判据 + worker 两条正则 (不需要 fastapi)
    python scripts/check_feature_orchestration.py --worker  # worker 端点真走一遍 (要 fastapi; CI 排在装它之后)

D-085 之前这些断言内联在 ci.yml 的 heredoc 里 (97 行)。改续跑判据必改这块守卫, 而 ci.yml 离 505,000
字节的棘轮 (check_system_map.py G6) 只剩约 1 KB —— 按 D-075 的规矩挪进 scripts/, ci.yml 只留一行调用。
check_orchestration() 是原块逐字搬过来的 (只把顶层 import 提到文件头), 断言一条没改。

守得住什么:
  · 编排 (原块): 31 行/篇、6 组 + 2 次重问 = 8 次调用、任一组 api 挂整篇不落行、写序 raw→answers、
    code-only 不调模型; 续跑判据的默认路径: 模型跑按 llm:% 前缀 (不带 extractor), code-only 看 code:v1
    的 body_len_bucket, 显式 extractor 精确匹配。
  · 续跑判据 (D-085): --done-by 的精确值 / 前缀各查一次取并集; 默认仍是 llm:%; 假账本上 judge 答过的
    (jev:1.13.0) 默认会被再抽一遍 (反证: 问题真实存在), 带 --done-by 就跳过; 计数脚本同口径;
    extractor 与 done_by 同给 / code-only 带 done_by / 非法 done_by → 拒。
  · model 不许是 extractor 标签: --model 或 FEATURE_MODEL 写成 jev:1.13.0 / llm:x → 退出 2、不调模型不写库
    (否则拼出 llm:jev:1.13.0, 与 judge 的 jev:1.13.0 永远对不上)。带 :0 尾巴的真模型名照常放行。
  · worker 与 pass 的 _DONE_BY_RE 逐字相同; worker 的 _MODEL_RE 拒 extractor 标签; --worker 时真打端点:
    非法 model / done_by → 400 且不起子进程, 合法 done_by 原样拼进 --done-by 并在响应里回显。
挡不住什么:
  · 真库上 PostgREST 的 like / eq 语义 —— 这里的假库按 SQL LIKE 自己实现了一遍 (% 任意串, _ 单字)。
  · 调用方 (features-sync / backfill-features) 有没有真的给 worker 和计数脚本传同一个 done_by ——
    今天两边都不传 (默认 llm:%), 切 judge 为 primary 时要一起改, 见 D-085。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import feature_bank as fb
import annotate_feature_pass as afp
import count_unannotated_features as cuf

ROOT = Path(__file__).resolve().parent.parent
# 下面各节会给 afp 的库 I/O 打桩; 真货先留一份
_REAL_DONE = afp.fetch_done_ids
_REAL_PAGES = afp.fetch_all_pages


def check_orchestration() -> None:
    # 编排自检: annotate_feature_pass 端到端走假 LLM + 假库 (不连网), 断行为不断源码。
    bank = fb.load_bank()
    raw = "【标题】戒烟第几天最难熬？\n【正文】上周三凌晨两点在公司茶水间饿醒。我妈：你身上什么味儿？嗓子像被砂纸磨过。\n你们戒烟第几天了？#戒烟#"
    note = {"note_id": "T_1", "project_id": "T", "title": None, "raw_content": raw, "target_blue_keywords": ["戒烟"], "projects": {"brand": "某牌", "product": "尼古丁贴"}}
    mapping = {"project_id": "T", "field_mapping": {}, "title_extraction": "markers"}
    calls = []
    def fake_llm(system, user, model):
        calls.append(system)
        ids = [ln.split(" · ")[0].split(". ", 1)[1] for ln in system.splitlines() if " · 看【" in ln]
        idx = fb.question_index(bank); out = []
        for q in ids:
            qq = idx[q]
            if q == "has_specific_time": out.append({"id": q, "answer": "是", "evidence": "凌晨两点"})
            elif q == "has_direct_quote": out.append({"id": q, "answer": "是", "evidence": "这句不在原文里"})
            elif q == "opening_type": out.append({"id": q, "answer": "外星选项", "evidence": ""})
            elif qq["type"] == "bool": out.append({"id": q, "answer": "否", "evidence": ""})
            else: out.append({"id": q, "answer": "未出现" if q == "product_role" else fb.closed_set(qq)[0], "evidence": ""})
        return json.dumps({"answers": out}, ensure_ascii=False)
    res = afp.annotate_note(bank, note, mapping, model="m", extractor="llm:m", run_tag="primary", single=False, code_only=False, dry_run=False, llm=fake_llm)
    rows = res["rows"]; by = {r["question_id"]: r for r in rows}
    assert len(rows) == 31 and len(calls) == 8, (len(rows), len(calls))        # 6 组 + 2 次重问
    assert by["has_specific_time"]["answer"] == "是" and by["has_direct_quote"]["invalid_reason"] == "evidence_not_found"
    assert by["opening_type"]["invalid_reason"] == "out_of_vocab" and by["product_role"]["answer"] == "未出现"
    assert by["body_len_bucket"]["extractor"] == "code:v1" and by["placebo_rand_2"]["extractor"] == "code:v1"
    assert all(r["bank_sha256"] == bank["_sha256"] and r["bank_version"] == "fq-v0.1" for r in rows)
    assert {r["subject_type"] for r in rows} == {"note"} and {r["run_tag"] for r in rows} == {"primary"}
    assert res["raw_counts"] == {"title_len": 9, "body_len": 45, "hashtag_count": 1, "mention_count": 0}, res["raw_counts"]
    # api 全挂 → 整篇 systemic, 编排层不落行
    def boom(*a, **k): raise RuntimeError("503 gateway")
    res2 = afp.annotate_note(bank, note, mapping, model="m", extractor="llm:m", run_tag="primary", single=False, code_only=False, dry_run=False, llm=boom)
    assert res2["stats"]["systemic"] == 6 and res2["stats"]["groups_ok"] == 0
    # 退出码口径同 essence: 全军覆没才红, 单篇抽风不红
    assert afp._exit_code_for_stats({"ok": 0, "systemic_failed": 3}) == 1
    assert afp._exit_code_for_stats({"ok": 5, "systemic_failed": 3}) == 0
    assert afp._exit_code_for_stats({"ok": 5, "hygiene_failed": 1}) == 1
    # ── codex review on #141 · 只要有一组 api 挂, 整篇不落行 (哪怕别的组都成功) ──
    def half_boom(system, user, model):
        if "turning_point" in system:
            raise RuntimeError("503 gateway")
        return fake_llm(system, user, model)
    res3 = afp.annotate_note(bank, note, mapping, model="m", extractor="llm:m", run_tag="primary", single=False, code_only=False, dry_run=False, llm=half_boom)
    assert res3["stats"]["systemic"] == 1 and res3["stats"]["groups_ok"] >= 4, res3["stats"]   # 半挂: 有组成功也有组挂

    # main 走假库: fetch / done / write 全打桩, 断言写进去的行数、写序与 resume 过滤
    import os
    os.environ["ANTHROPIC_API_KEY"] = "x"
    written, order = [], []
    _real_done = afp.fetch_done_ids          # 下面要打桩, 先把真货留一份
    afp.get_supabase_client = lambda: object()
    afp.load_mapping = lambda pid: mapping
    afp.fetch_notes = lambda sb, pid: [note, dict(note, note_id="T_2"), dict(note, note_id="T_3")]
    afp.fetch_done_ids = lambda sb, pid, **kw: {"T_2"}
    afp.write_answers = lambda sb, rows, dry_run: (order.append("answers"), written.extend(rows))
    afp.write_raw_counts = lambda *a, **k: order.append("raw")
    afp._llm = fake_llm
    calls.clear()
    rc = afp.main(["T", "--limit", "5"])
    assert rc == 0 and len(written) == 62 and {r["subject_id"] for r in written} == {"T_1", "T_3"}, (rc, len(written))
    # 写序: 数值原值在前、带标记题的答案在后 (反过来 → 写答案成功而原值失败时, 下轮 resume 跳过这篇, 原值永远缺)
    assert order == ["raw", "answers", "raw", "answers"], order
    # 反证: 半挂那篇一行都不许落 (旧口径 systemic and not groups_ok 会在这里写 31 行)
    afp.fetch_notes = lambda sb, pid: [note]
    afp.fetch_done_ids = lambda sb, pid, **kw: set()
    afp._llm = half_boom
    written.clear(); order.clear()
    rc = afp.main(["T"])
    assert rc == 1 and written == [] and order == [], (rc, len(written), order)
    afp._llm = fake_llm
    afp.fetch_notes = lambda sb, pid: [note, dict(note, note_id="T_2"), dict(note, note_id="T_3")]
    afp.fetch_done_ids = lambda sb, pid, **kw: {"T_2"}
    # run_tag 非法 → 2; --code-only 不需要 key、不调模型
    assert afp.main(["T", "--run-tag", "bad tag"]) == 2
    calls.clear(); written.clear(); order.clear()
    assert afp.main(["T", "--code-only"]) == 0 and not calls and len(written) == 22 and {r["extractor"] for r in written} == {"code:v1"}

    # ── codex review on #141 · resume 的判据: code-only 用代码那边的标记题, 模型跑按 llm:% 前缀 ──
    class _Q:
        """记下 fetch_done_ids 真的往查询里塞了什么 (不连库)。"""
        def __init__(self, log): self.log = log
        def schema(self, s): return self
        def table(self, t): self.log["table"] = t; return self
        def select(self, *a, **k): return self
        def eq(self, k, v): self.log[k] = v; return self
        def like(self, k, v): self.log["like_" + k] = v; return self
    _real_pages = afp.fetch_all_pages
    afp.fetch_all_pages = lambda q, order_by=None: []
    log = {}; _real_done(_Q(log), "T", run_tag="primary", code_only=True)
    # 反证: 这里若仍是模型那边的标记题 has_specific_time, --code-only 永远 resume 不上 (代码题从不写那一行)
    assert log["table"] == "note_feature_answers" and log["question_id"] == "body_len_bucket" and log["extractor"] == "code:v1", log
    log = {}; _real_done(_Q(log), "T", run_tag="primary", code_only=False)
    # 反证: 两边 FEATURE_MODEL 配得不一样时, 精确匹配 extractor 会把所有笔记当没跑过 → 必须是 llm:% 前缀
    assert log["question_id"] == "has_specific_time" and log["like_extractor"] == "llm:%" and "extractor" not in log, log
    log = {}; _real_done(_Q(log), "T", run_tag="gate1_b", code_only=False, extractor="llm:x")
    assert log["extractor"] == "llm:x" and log["run_tag"] == "gate1_b" and log["like_subject_id"] == "T_%" and "like_extractor" not in log, log
    afp.fetch_all_pages = _real_pages
    print("  ✓ 编排: 31 行/篇, 8 次调用 (6 组 + 2 次重问), 任一组挂整篇不落行, 写序 raw→answers, resume 判据分 code/llm 两套, code-only 不调模型")


# ─────────────────────────────────────────────────────────────────────────
# D-085 · 续跑判据认得出 judge
# ─────────────────────────────────────────────────────────────────────────

def _like(value: str, pat: str) -> bool:
    """SQL LIKE: % 任意串, _ 单字 (fetch_done_ids 的 subject_id 过滤就是 'T_%')。"""
    rx = "".join(".*" if c == "%" else "." if c == "_" else re.escape(c) for c in pat)
    return re.fullmatch(rx, value, re.S) is not None


class _Q:
    """假 PostgREST 查询构造器: 只记过滤条件, 由 _pages 在假表上求值。每次 sb.schema() 一条新查询。"""

    def __init__(self, tables: dict, log: list):
        self.tables, self.table_name, self.filters = tables, None, []
        log.append(self)

    def schema(self, s): return self
    def table(self, t): self.table_name = t; return self
    def select(self, *a, **k): return self
    def eq(self, k, v): self.filters.append(("eq", k, v)); return self
    def like(self, k, v): self.filters.append(("like", k, v)); return self

    def extractor_filters(self) -> list[tuple[str, str]]:
        return [(op, v) for op, k, v in self.filters if k == "extractor"]


class _SB:
    def __init__(self, tables: dict):
        self.tables, self.log = tables, []

    def schema(self, s):
        return _Q(self.tables, self.log).schema(s)


def _pages(q, order_by=None):
    out = []
    for r in q.tables.get(q.table_name, []):
        if all((r.get(k) == v) if op == "eq" else _like(str(r.get(k)), v) for op, k, v in q.filters):
            out.append(r)
    return out


def _ans(subject_id: str, extractor: str, run_tag: str = "primary", qid: str = afp.DONE_MARKER_QUESTION) -> dict:
    return {"subject_type": "note", "subject_id": subject_id, "question_id": qid,
            "run_tag": run_tag, "extractor": extractor}


# 假账本: T_1 judge 答过 (jev:1.13.0 / primary); T_2 TV 自己答过; T_3 只在别的 run_tag 下有 judge 行; T_4 没人答过
LEDGER = [
    _ans("T_1", "jev:1.13.0"),
    _ans("T_2", "llm:claude-opus-4-6"),
    _ans("T_3", "jev:1.13.0", run_tag="gate1-x"),
    _ans("T_2", fb.CODE_EXTRACTOR, qid=afp.CODE_DONE_MARKER_QUESTION),
]
NOTE_IDS = ["T_1", "T_2", "T_3", "T_4"]


def _tables() -> dict:
    return {"note_feature_answers": [dict(r) for r in LEDGER],
            "notes": [{"note_id": n, "project_id": "T"} for n in NOTE_IDS]}


def check_parse_done_by() -> None:
    assert afp.DEFAULT_DONE_BY == ("llm:%",), \
        f"默认续跑判据变了: {afp.DEFAULT_DONE_BY} —— 改它就是改夜跑口径, 要在 DECISIONS 里说清"
    for ok, want in (("jev:1.13.0", ("jev:1.13.0",)),
                     ("llm:%,jev:%", ("llm:%", "jev:%")),
                     (" llm:% , llm:% ,jev:1.13.0-C", ("llm:%", "jev:1.13.0-C")),
                     ("llm:us.anthropic.claude-3-5-sonnet-20241022-v2:0", ("llm:us.anthropic.claude-3-5-sonnet-20241022-v2:0",))):
        assert afp.parse_done_by(ok) == want, (ok, afp.parse_done_by(ok))
    for bad in ("", " , ", "%", "jev:", "jev:%x", "llm:claude_x%", "JEV:1", "jev 1", "llm:a;b", "llm:%%"):
        try:
            afp.parse_done_by(bad)
            raise AssertionError(f"--done-by {bad!r} 该被拒")
        except ValueError:
            pass
    print("  ✓ parse_done_by: 精确值 / 以 % 结尾的前缀 / 去重保序; 空、无命名空间、% 在中间、前缀里带 _ 都拒")


def check_fetch_done_ids() -> None:
    afp.fetch_all_pages = _pages
    try:
        # 默认: 只认 llm:% —— judge 答过的 T_1 不算答过 (这就是要修的那件事, 默认行为本身不改)
        sb = _SB(_tables())
        assert _REAL_DONE(sb, "T") == {"T_2"}
        assert len(sb.log) == 1 and sb.log[0].extractor_filters() == [("like", "llm:%")], sb.log[0].filters
        # done_by 精确值: eq, 不走 like
        sb = _SB(_tables())
        assert _REAL_DONE(sb, "T", done_by=("jev:1.13.0",)) == {"T_1"}
        assert [q.extractor_filters() for q in sb.log] == [[("eq", "jev:1.13.0")]], [q.filters for q in sb.log]
        # done_by 多项: 各查一次取并集; run_tag 照样过滤 (T_3 的 judge 行在 gate1-x 下, 不算)
        sb = _SB(_tables())
        assert _REAL_DONE(sb, "T", done_by=("jev:1.13.0", "llm:%")) == {"T_1", "T_2"}
        assert [q.extractor_filters() for q in sb.log] == [[("eq", "jev:1.13.0")], [("like", "llm:%")]]
        for q in sb.log:
            assert ("eq", "question_id", afp.DONE_MARKER_QUESTION) in q.filters and ("eq", "run_tag", "primary") in q.filters, q.filters
            assert ("like", "subject_id", "T_%") in q.filters and ("eq", "subject_type", "note") in q.filters, q.filters
        sb = _SB(_tables())
        assert _REAL_DONE(sb, "T", run_tag="gate1-x", done_by=("jev:%",)) == {"T_3"}
        # 旧的两条路不变: code-only 看 code:v1 的 body_len_bucket; 显式 extractor 精确匹配
        sb = _SB(_tables())
        assert _REAL_DONE(sb, "T", code_only=True) == {"T_2"}
        assert sb.log[0].extractor_filters() == [("eq", fb.CODE_EXTRACTOR)]
        sb = _SB(_tables())
        assert _REAL_DONE(sb, "T", extractor="llm:claude-opus-4-6") == {"T_2"}
        # 两个判据同时给 / code-only 带 done_by → 拒, 不猜
        for kw in ({"extractor": "llm:x", "done_by": ("jev:%",)}, {"code_only": True, "done_by": ("jev:%",)}):
            try:
                _REAL_DONE(_SB(_tables()), "T", **kw)
                raise AssertionError(f"{kw} 该被拒")
            except ValueError:
                pass
    finally:
        afp.fetch_all_pages = _REAL_PAGES
    print("  ✓ fetch_done_ids: 默认 llm:% 不变; done_by 精确值走 eq、前缀走 like、多项取并集; run_tag 照样过滤; 冲突参数拒")


def _good_llm(calls: list):
    bank = fb.load_bank()
    idx = fb.question_index(bank)

    def llm(system, user, model):
        calls.append(model)
        ids = [ln.split(" · ")[0].split(". ", 1)[1] for ln in system.splitlines() if " · 看【" in ln]
        out = []
        for q in ids:
            qq = idx[q]
            if qq["type"] == "bool":
                out.append({"id": q, "answer": "否", "evidence": ""})
            else:
                out.append({"id": q, "answer": "未出现" if q == "product_role" else fb.closed_set(qq)[0], "evidence": ""})
        return json.dumps({"answers": out}, ensure_ascii=False)
    return llm


def check_main_resume() -> None:
    raw = "【标题】戒烟第几天最难熬？\n【正文】上周三凌晨两点在公司茶水间饿醒。我妈：你身上什么味儿？嗓子像被砂纸磨过。\n你们戒烟第几天了？#戒烟#"
    mapping = {"project_id": "T", "field_mapping": {}, "title_extraction": "markers"}
    notes = [{"note_id": n, "project_id": "T", "title": None, "raw_content": raw,
              "target_blue_keywords": ["戒烟"], "projects": {"brand": "某牌", "product": "尼古丁贴"}} for n in NOTE_IDS]
    calls: list = []
    written: list = []
    box = {}
    saved = {k: getattr(afp, k) for k in ("get_supabase_client", "load_mapping", "fetch_notes", "fetch_done_ids",
                                          "fetch_all_pages", "write_answers", "write_raw_counts", "_llm")}
    env_saved = {k: os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "FEATURE_MODEL", "ESSENCE_MODEL")}

    def fresh():
        box["sb"] = _SB(_tables())
        calls.clear(); written.clear()
        return box["sb"]

    afp.get_supabase_client = lambda: box["sb"]
    afp.load_mapping = lambda pid: mapping
    afp.fetch_notes = lambda sb, pid: [dict(n) for n in notes]
    afp.fetch_done_ids = _REAL_DONE
    afp.fetch_all_pages = _pages
    afp.write_answers = lambda sb, rows, dry_run: written.extend(rows)
    afp.write_raw_counts = lambda *a, **k: None
    afp._llm = _good_llm(calls)
    os.environ["ANTHROPIC_API_KEY"] = "x"
    os.environ.pop("FEATURE_MODEL", None)
    os.environ["ESSENCE_MODEL"] = "claude-opus-4-6"
    def run_main(argv: list[str]) -> int:
        return afp.main(argv + ["--qps", "0"])      # 假模型不限速

    try:
        def ran() -> set[str]:
            return {r["subject_id"] for r in written if r["extractor"].startswith("llm:")}

        # 反证先行: 不带 --done-by (今天的夜跑) → judge 答过的 T_1 被 Opus 再抽一遍
        fresh()
        assert run_main(["T"]) == 0 and ran() == {"T_1", "T_3", "T_4"}, ran()
        # 带 --done-by: judge 与 TV 自己答过的都跳过; 只剩没人答过的
        fresh()
        assert run_main(["T", "--done-by", "jev:1.13.0,llm:%"]) == 0 and ran() == {"T_3", "T_4"}, ran()
        assert {r["extractor"] for r in written if r["question_id"] == afp.DONE_MARKER_QUESTION} == {"llm:claude-opus-4-6"}
        # --done-by 取代 --model 的精确匹配 (不是再叠一层)
        fresh()
        assert run_main(["T", "--model", "claude-opus-4-6", "--done-by", "jev:%"]) == 0 and ran() == {"T_2", "T_3", "T_4"}, ran()
        assert [q.extractor_filters() for q in box["sb"].log] == [[("like", "jev:%")]]

        # model 写成 extractor 标签 → 退出 2, 一次调用都没有、一行都不写
        for argv, env in ((["T", "--model", "jev:1.13.0"], None), (["T", "--model", "llm:claude-opus-4-6"], None),
                          (["T", "--code-only", "--model", "code:v1"], None), (["T"], "jev:1.13.0")):
            fresh()
            if env:
                os.environ["FEATURE_MODEL"] = env
            try:
                assert run_main(argv) == 2 and not calls and not written, (argv, env, len(calls), len(written))
            finally:
                os.environ.pop("FEATURE_MODEL", None)
        # 带 :0 尾巴的真模型名照常放行, extractor 就是 llm:<它>, 续跑按它精确匹配
        m = "us.anthropic.claude-3-5-sonnet-20241022-v2:0"
        fresh()
        assert run_main(["T", "--model", m, "--limit", "1"]) == 0 and {r["extractor"] for r in written} >= {"llm:" + m}
        assert box["sb"].log[0].extractor_filters() == [("eq", "llm:" + m)]
        # 非法 --done-by / code-only 带 --done-by → 退出 2
        for argv in (["T", "--done-by", "llm:claude_x%"], ["T", "--done-by", "%"], ["T", "--done-by", " , "],
                     ["T", "--code-only", "--done-by", "jev:%"]):
            fresh()
            assert run_main(argv) == 2 and not calls and not written, argv
    finally:
        for k, v in saved.items():
            setattr(afp, k, v)
        for k, v in env_saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    print("  ✓ main: 不带 --done-by 时 judge 答过的会被再抽 (反证); 带上就跳过; --done-by 取代 --model 精确匹配;"
          " model 是 extractor 标签 (参数或 FEATURE_MODEL) → 退出 2 不调模型; v2:0 这种真模型名放行")


def check_count_script() -> None:
    import contextlib
    import io
    saved = (cuf.get_supabase_client, cuf.fetch_all_pages, afp.fetch_all_pages)
    sb = _SB(_tables())
    cuf.get_supabase_client = lambda: sb
    cuf.fetch_all_pages = _pages
    afp.fetch_all_pages = _pages          # fetch_done_ids 在 afp 的命名空间里找它
    try:
        def count(argv) -> str:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                assert cuf.main(argv) == 0
            return buf.getvalue().strip()
        assert count(["T"]) == "3", "默认口径: T_1 (judge 答过) / T_3 / T_4 都算没抽"
        assert count(["T", "--done-by", "jev:1.13.0,llm:%"]) == "2"
        assert count(["T", "--extractor", "jev:1.13.0"]) == "3"          # 精确匹配 T_1, 剩 T_2 T_3 T_4
        for argv in (["T", "--extractor", "llm:x", "--done-by", "jev:%"], ["T", "--code-only", "--done-by", "jev:%"],
                     ["T", "--done-by", "llm:a_b%"]):
            with contextlib.redirect_stderr(io.StringIO()):
                try:
                    cuf.main(argv)
                    raise AssertionError(f"{argv} 该被拒")
                except SystemExit as e:
                    assert e.code == 2, (argv, e.code)
    finally:
        cuf.get_supabase_client, cuf.fetch_all_pages, afp.fetch_all_pages = saved
    print("  ✓ count_unannotated_features: --done-by 与 pass 同口径 (3 → 2); 与 --extractor 互斥; code-only 不收")


def _worker_patterns() -> dict[str, str]:
    src = (ROOT / "worker" / "app.py").read_text(encoding="utf-8")
    got = dict(re.findall(r'^(_DONE_BY_RE|_MODEL_RE) = re\.compile\(r"(.+)"\)$', src, re.M))
    assert set(got) == {"_DONE_BY_RE", "_MODEL_RE"}, f"worker/app.py 里找不到两条正则 (写法变了就同步改这里): {sorted(got)}"
    return got


MODEL_OK = ("claude-opus-4-6", "claude-sonnet-4-6", "us.anthropic.claude-3-5-sonnet-20241022-v2:0", "anthropic/claude-3.5")
MODEL_TAGS = ("jev:1.13.0", "llm:claude-opus-4-6", "code:v1", "human:x", "JEV:1")


def check_worker_source() -> None:
    pats = _worker_patterns()
    assert pats["_DONE_BY_RE"] == afp._DONE_BY_RE.pattern, \
        "worker 与 pass 的 _DONE_BY_RE 不一样 —— worker 放行的 done_by pass 会退出 2 (或反过来)"
    model_re = re.compile(pats["_MODEL_RE"])
    for m in MODEL_OK:
        assert model_re.match(m), f"worker 把真模型名 {m!r} 拒了"
        assert not afp._EXTRACTOR_TAG_RE.match(m), f"pass 把真模型名 {m!r} 当成了 extractor 标签"
    for m in MODEL_TAGS:
        assert not model_re.match(m), f"worker 放行了 extractor 标签 {m!r} 当 model (会拼出 llm:{m})"
        assert afp._EXTRACTOR_TAG_RE.match(m), m
    print("  ✓ worker: _DONE_BY_RE 与 pass 逐字相同; _MODEL_RE 拒 jev:/llm:/code:/human: 标签、放行 v2:0 这类真模型名")


def check_worker_endpoint() -> None:
    """--worker: 真起 FastAPI app 打 /annotate-features (要 fastapi; CI 里排在装它的那一步之后)。"""
    sys.path.insert(0, str(ROOT))
    os.environ.pop("WORKER_API_KEY", None)
    os.environ["WORKER_ALLOW_ANONYMOUS"] = "1"
    from fastapi.testclient import TestClient
    import worker.app as w
    seen: list[list[str]] = []
    real_run = w._run

    def fake_run(script, args):
        seen.append(list(args))
        return {"ok": True, "returncode": 0, "stdout_tail": "", "stderr_tail": ""}
    w._run = fake_run
    try:
        c = TestClient(w.app)

        def post(**body):
            seen.clear()
            return c.post("/annotate-features", json={"project": "T", **body})
        for m in MODEL_TAGS:
            r = post(model=m)
            assert r.status_code == 400 and not seen, (m, r.status_code, seen)
        for m in MODEL_OK:
            r = post(model=m)
            assert r.status_code == 200 and seen and seen[0][seen[0].index("--model") + 1] == m, (m, r.status_code, seen)
        r = post()
        assert r.status_code == 200 and "--done-by" not in seen[0] and "done_by" not in r.json(), (seen, r.json())
        r = post(done_by=["jev:1.13.0", "llm:%"])
        assert r.status_code == 200 and seen[0][seen[0].index("--done-by") + 1] == "jev:1.13.0,llm:%", seen
        assert r.json()["done_by"] == ["jev:1.13.0", "llm:%"], r.json()
        for bad in ("jev:1.13.0", [], ["llm:a_b%"], ["%"], [1], ["jev:%"] * 9, ["jev:1.13.0; rm -rf /"]):
            r = post(done_by=bad)
            assert r.status_code == 400 and not seen, (bad, r.status_code, seen)
        r = post(done_by=["jev:%"], code_only=True)
        assert r.status_code == 400 and not seen, (r.status_code, seen)
    finally:
        w._run = real_run
        os.environ.pop("WORKER_ALLOW_ANONYMOUS", None)
    print("  ✓ worker /annotate-features: extractor 标签当 model → 400 不起子进程; done_by 原样拼进 --done-by 并回显;"
          " 非法 done_by / code_only 带 done_by → 400; 不带 done_by 时参数与响应都和以前一样")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker", action="store_true", help="只跑 worker 端点那一节 (要 fastapi)")
    a = ap.parse_args(argv)
    if a.worker:
        check_worker_endpoint()
        return 0
    check_orchestration()
    check_parse_done_by()
    check_fetch_done_ids()
    check_main_resume()
    check_count_script()
    check_worker_source()
    print("✓ 特征层编排自检 + 续跑判据 (D-085): 全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
