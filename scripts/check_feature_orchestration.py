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
  · 副题库 (D-128, --bank reader): 3 行/篇 (2 道模型题 + last_para_has_qmark)、2 次调用、行上是 fqr-* run_tag 和
    副题库 sha、没有主题库的代码题、不写 note_features; 续跑看 reader_ask_form + 精确 extractor + 副题库 sha,
    假账本上两边的行互相不算「跑过」; run_tag=primary / 不带 fqr- / --code-only / 没 --note-ids / 没 --model /
    --done-by → 退出 2 不调模型不写库; 主题库那条路 (31 行、8 个代码题、写 note_features、续跑查询) 不变。
    backfill-features.yml 两步真用 bash 跑: 输入校验的拒绝、探针要 worker 回显 bank 且日志是该库版本 (假 curl),
    主题库的请求体不带 bank。worker 的 _BANKS 与 fb.BANKS 的键一致; --worker 时 bank 闭集、副题库的 400、回显。
挡不住什么:
  · 真库上 PostgREST 的 like / eq 语义 —— 这里的假库按 SQL LIKE 自己实现了一遍 (% 任意串, _ 单字)。
  · 调用方 (features-sync / backfill-features) 有没有真的给 worker 和计数脚本传同一个 done_by ——
    今天两边都不传 (默认 llm:%), 切 judge 为 primary 时要一起改, 见 D-085。
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import re
import sys
import tempfile
from unittest.mock import patch
from pathlib import Path

import feature_bank as fb
import annotate_feature_pass as afp
import count_unannotated_features as cuf

ROOT = Path(__file__).resolve().parent.parent
# 下面各节会给 afp 的库 I/O 打桩; 真货先留一份
_REAL_DONE = afp.fetch_done_ids
_REAL_PAGES = afp.fetch_all_pages


def check_note_ids() -> None:
    # worker 最多拼 200 个 id; 参数超过文件名上限时也必须按名单读, 不先在 Path.stat 上崩掉。
    for n in (8, 200):
        ids = {f"recSyntheticFeatureNote{i:04d}" for i in range(n)}
        assert afp._read_note_ids(",".join(sorted(ids))) == ids
    assert afp._read_note_ids(" first, second, first, ") == {"first", "second"}
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "ids.txt"
        p.write_text("first\n\n second \nfirst\n", encoding="utf-8")
        assert afp._read_note_ids(str(p)) == {"first", "second"}
    for code in (errno.EACCES, errno.EIO):
        with patch.object(Path, "is_file", side_effect=OSError(code, "synthetic stat failure")):
            try:
                afp._read_note_ids("ids.txt")
            except OSError as exc:
                assert exc.errno == code
            else:
                raise AssertionError("stat failure must not silently become a note ID")
    print("  ✓ --note-ids: 8 / 200 个 id 的长参数不当文件名; 文件、去重和空白口径不变")


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


MODEL_OK = ("claude-sonnet-5-5", "claude-opus-4-6", "claude-sonnet-4-6", "us.anthropic.claude-3-5-sonnet-20241022-v2:0", "anthropic/claude-3.5")
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

# ─────────────────────────────────────────────────────────────────────────
# D-128 · 副题库 (--bank reader): 行、续跑、拒跑、workflow、worker
# ─────────────────────────────────────────────────────────────────────────

READER = fb.load_bank(fb.BANKS["reader"])
PRIMARY_SHA = fb.load_bank()["_sha256"]
R_RAW = "【标题】戒烟第几天最难熬？\n【正文】上周三凌晨两点在公司茶水间饿醒。我妈：你身上什么味儿？嗓子像被砂纸磨过。\n你们戒烟第几天了？#戒烟#"
R_TAG = "fqr-g1-sonnet55-a"
R_MODEL = "claude-sonnet-5-5"


def _reader_llm(calls: list):
    """副题库的假模型: reader_ask_form 答「说自己的」、invites_sharing 答「是」, 证据都抄结尾那一问。"""
    def llm(system, user, model):
        calls.append(model)
        ids = [ln.split(" · ")[0].split(". ", 1)[1] for ln in system.splitlines() if " · 看【" in ln]
        ans = {"reader_ask_form": "说自己的", "invites_sharing": "是"}
        return json.dumps({"answers": [{"id": q, "answer": ans[q], "evidence": "你们戒烟第几天了？"} for q in ids]},
                          ensure_ascii=False)
    return llm


def check_reader_rows() -> None:
    note = {"note_id": "R_1", "project_id": "R", "title": None, "raw_content": R_RAW, "target_blue_keywords": ["戒烟"],
            "projects": {"brand": "某牌", "product": "尼古丁贴"}}
    mapping = {"project_id": "R", "field_mapping": {}, "title_extraction": "markers"}
    calls: list = []
    res = afp.annotate_note(READER, note, mapping, model=R_MODEL, extractor="llm:" + R_MODEL, run_tag=R_TAG,
                            single=False, code_only=False, dry_run=False, llm=_reader_llm(calls))
    rows = res["rows"]
    by = {r["question_id"]: r for r in rows}
    assert len(rows) == 3 and len(calls) == 2, (len(rows), len(calls))      # 2 组各一次, 没有重问
    assert set(by) == {"reader_ask_form", "invites_sharing", "last_para_has_qmark"}, sorted(by)
    assert not set(by) & set(fb.CODE_FEATURE_IDS_V1), "副题库写了主题库的代码题 → 同主键盖掉主题库的行"
    assert by["reader_ask_form"]["answer"] == "说自己的" and by["invites_sharing"]["answer"] == "是", by
    assert by["invites_sharing"]["question_version"] == 2 and by["last_para_has_qmark"]["answer"] == "是"
    assert by["last_para_has_qmark"]["extractor"] == fb.CODE_EXTRACTOR and by["reader_ask_form"]["extractor"] == "llm:" + R_MODEL
    assert {r["run_tag"] for r in rows} == {R_TAG}
    assert {(r["bank_version"], r["bank_sha256"]) for r in rows} == {("fq-v0.2-cand-reader", READER["_sha256"])}
    assert READER["_sha256"] != PRIMARY_SHA
    # 代码题那条路: 主题库原样 8 + 3 (only=None), 副题库只出它声明的
    prim = fb.load_bank()
    assert afp.declared_code_ids(prim) is None and afp.declared_code_ids(READER) == ["last_para_has_qmark"]
    sp = fb.build_spans(R_RAW, mode="markers")
    pc = afp.code_rows(prim, note, sp, [], "primary")
    assert [r["question_id"] for r in pc] == list(fb.CODE_FEATURE_IDS_V1) + [p["id"] for p in prim["placebo"]], pc
    assert [r["question_id"] for r in afp.code_rows(READER, note, sp, [], R_TAG)] == ["last_para_has_qmark"]
    print("  ✓ 副题库编排: 3 行/篇 (2 模型题 + last_para_has_qmark), 2 次调用, fqr-* + 副题库 sha, 没有主题库代码题; "
          "主题库 code_rows 仍是 8 + 3")


def _reader_ledger() -> list[dict]:
    """假账本 (项目 R): R_1 只有主题库的标记行; R_2 副题库跑过 (Sonnet / 本 sha); R_3 副题库行但是别的 sha;
    R_4 副题库行但是 Haiku; R_5 没人跑过。"""
    def row(sid, qid, ext, tag, sha):
        return {"subject_type": "note", "subject_id": sid, "question_id": qid, "run_tag": tag, "extractor": ext,
                "bank_sha256": sha}
    rs = READER["_sha256"]
    return [row("R_1", afp.DONE_MARKER_QUESTION, "llm:" + R_MODEL, "primary", PRIMARY_SHA),
            row("R_1", afp.DONE_MARKER_QUESTION, "llm:" + R_MODEL, R_TAG, PRIMARY_SHA),
            row("R_2", "reader_ask_form", "llm:" + R_MODEL, R_TAG, rs),
            row("R_3", "reader_ask_form", "llm:" + R_MODEL, R_TAG, "0" * 64),
            row("R_4", "reader_ask_form", "llm:claude-haiku-5-5", R_TAG, rs)]


def check_reader_main() -> None:
    import logging
    rids = ["R_1", "R_2", "R_3", "R_4", "R_5"]
    mapping = {"project_id": "R", "field_mapping": {}, "title_extraction": "markers"}
    notes = [{"note_id": n, "project_id": "R", "title": None, "raw_content": R_RAW, "target_blue_keywords": ["戒烟"],
              "projects": {"brand": "某牌", "product": "尼古丁贴"}} for n in rids]
    calls: list = []
    written: list = []
    raw_writes: list = []
    fetched: list = []
    box: dict = {}
    saved = {k: getattr(afp, k) for k in ("get_supabase_client", "load_mapping", "fetch_notes", "fetch_done_ids",
                                          "fetch_all_pages", "write_answers", "write_raw_counts", "_llm")}
    env_saved = {k: os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "FEATURE_MODEL", "ESSENCE_MODEL")}
    logs: list = []

    class _H(logging.Handler):
        def emit(self, rec): logs.append(rec.getMessage())
    h = _H()
    afp.logger.addHandler(h)

    def fresh(reader_llm: bool = True):
        box["sb"] = _SB({"note_feature_answers": _reader_ledger()})
        calls.clear(); written.clear(); raw_writes.clear(); fetched.clear(); logs.clear()
        afp._llm = _reader_llm(calls) if reader_llm else _good_llm(calls)

    def ran() -> set:
        return {r["subject_id"] for r in written if r["extractor"].startswith("llm:")}

    afp.get_supabase_client = lambda: box["sb"]
    afp.load_mapping = lambda pid: mapping
    afp.fetch_notes = lambda sb, pid: (fetched.append(pid), [dict(n) for n in notes])[1]
    afp.fetch_done_ids = _REAL_DONE
    afp.fetch_all_pages = _pages
    afp.write_answers = lambda sb, rows, dry_run: written.extend(rows)
    afp.write_raw_counts = lambda *a, **k: raw_writes.append(a[1])
    os.environ["ANTHROPIC_API_KEY"] = "x"
    os.environ.pop("FEATURE_MODEL", None)
    os.environ["ESSENCE_MODEL"] = R_MODEL
    ids = ",".join(rids)
    reader_argv = ["R", "--bank", "reader", "--run-tag", R_TAG, "--model", R_MODEL, "--note-ids", ids, "--qps", "0"]
    try:
        # 副题库: R_2 跑过 (本库标记 + Sonnet + 本 sha); R_1 的主题库标记行、R_3 的旧 sha、R_4 的 Haiku 都不算
        fresh()
        assert afp.main(reader_argv) == 0
        assert ran() == {"R_1", "R_3", "R_4", "R_5"}, ran()
        assert len(written) == 3 * 4 and len(calls) == 2 * 4, (len(written), len(calls))
        assert raw_writes == [], "副题库不许写 note_features (会把 extractor_version 改成副题库的)"
        assert {r["run_tag"] for r in written} == {R_TAG} and {r["bank_sha256"] for r in written} == {READER["_sha256"]}
        assert {r["question_id"] for r in written} == {"reader_ask_form", "invites_sharing", "last_para_has_qmark"}
        assert {r["extractor"] for r in written} == {"llm:" + R_MODEL, fb.CODE_EXTRACTOR}
        (q,) = box["sb"].log
        assert sorted(q.filters) == sorted([("eq", "subject_type", "note"), ("eq", "question_id", "reader_ask_form"),
                                            ("eq", "run_tag", R_TAG), ("like", "subject_id", "R_%"),
                                            ("eq", "extractor", "llm:" + R_MODEL),
                                            ("eq", "bank_sha256", READER["_sha256"])]), q.filters
        line = next(m for m in logs if m.startswith("bank="))
        assert line.startswith(f"bank=fq-v0.2-cand-reader sha={READER['_sha256'][:12]}… model={R_MODEL} run_tag={R_TAG} "), line
        # 主题库 (默认, 夜跑): R_1 的 has_specific_time 算跑过; 副题库的行不算; 查询与 D-128 之前一样 (不带 sha)
        fresh(reader_llm=False)
        assert afp.main(["R", "--qps", "0"]) == 0 and ran() == {"R_2", "R_3", "R_4", "R_5"}, ran()
        assert len(written) == 31 * 4 and sorted(raw_writes) == ["R_2", "R_3", "R_4", "R_5"], (len(written), raw_writes)
        (q,) = box["sb"].log
        assert sorted(q.filters) == sorted([("eq", "subject_type", "note"), ("eq", "question_id", afp.DONE_MARKER_QUESTION),
                                            ("eq", "run_tag", "primary"), ("like", "subject_id", "R_%"),
                                            ("like", "extractor", "llm:%")]), q.filters
        assert {r["bank_sha256"] for r in written} == {PRIMARY_SHA}
        assert next(m for m in logs if m.startswith("bank=")).startswith(f"bank=fq-v0.1 sha={PRIMARY_SHA[:12]}…")
        # 主题库换到副题库的 run_tag 下跑: 副题库 R_2/R_3/R_4 的 reader_ask_form 行不算主题库跑过; R_1 那行算
        fresh(reader_llm=False)
        assert afp.main(["R", "--run-tag", R_TAG, "--model", R_MODEL, "--qps", "0"]) == 0
        assert ran() == {"R_2", "R_3", "R_4", "R_5"}, ran()
        # 拒跑: 退出 2, 不读笔记、不调模型、不写库
        base = ["R", "--bank", "reader", "--qps", "0"]
        bad = [base + ["--run-tag", "primary", "--model", R_MODEL, "--note-ids", ids],
               base + ["--model", R_MODEL, "--note-ids", ids],                        # 默认 run_tag=primary
               base + ["--run-tag", "gate1-sonnet55", "--model", R_MODEL, "--note-ids", ids],
               base + ["--run-tag", "fqr-", "--model", R_MODEL, "--note-ids", ids],
               base + ["--run-tag", R_TAG, "--model", R_MODEL, "--note-ids", ids, "--code-only"],
               base + ["--run-tag", R_TAG, "--model", R_MODEL],                       # 没 --note-ids
               base + ["--run-tag", R_TAG, "--note-ids", ids],                        # 没 --model (FEATURE_MODEL 不算)
               base + ["--run-tag", R_TAG, "--model", R_MODEL, "--note-ids", ids, "--done-by", "llm:%"]]
        for argv in bad:
            fresh()
            os.environ["FEATURE_MODEL"] = R_MODEL
            try:
                assert afp.main(argv) == 2 and not calls and not written and not raw_writes and not fetched, argv
            finally:
                os.environ.pop("FEATURE_MODEL", None)
        for argv in (["R", "--bank", "secondary"], ["R", "--bank", str(fb.BANKS["reader"])]):
            fresh()
            try:
                with patch("sys.stderr"):
                    afp.main(argv)
                raise AssertionError(f"{argv} 该被 argparse 拒 (只收 BANKS 的键, 不收路径)")
            except SystemExit as e:
                assert e.code == 2 and not fetched, (argv, e.code)
        # fetch_done_ids: code-only 不收 marker / bank_sha (标记题固定)
        for kw in ({"code_only": True, "marker": "reader_ask_form"}, {"code_only": True, "bank_sha": "a" * 64}):
            try:
                _REAL_DONE(_SB({}), "R", **kw)
                raise AssertionError(f"{kw} 该被拒")
            except ValueError:
                pass
    finally:
        afp.logger.removeHandler(h)
        for k, v in saved.items():
            setattr(afp, k, v)
        for k, v in env_saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    print("  ✓ 副题库 main: 续跑看 reader_ask_form + 精确 extractor + 副题库 sha (主题库标记 / 旧 sha / Haiku 都不算); "
          "不写 note_features; 主题库续跑不认副题库的行、查询不带 sha; 拒跑 8 种 + 路径当 bank → 退出 2 不读不调不写")


# ── backfill-features.yml: 两步真用 bash 跑 (输入校验 / 探针 + 分批请求体) ────────────────────────────

def _wf_step(name_prefix: str) -> str:
    import yaml
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "backfill-features.yml").read_text(encoding="utf-8"))
    steps = wf["jobs"]["backfill"]["steps"]
    (step,) = [st for st in steps if str(st.get("name", "")).startswith(name_prefix)]
    return step["run"]


def _bash_step(script: str, env: dict, cwd: Path) -> "subprocess.CompletedProcess":
    import subprocess
    full = dict(os.environ)
    full["PATH"] = os.path.dirname(sys.executable) + os.pathsep + full.get("PATH", "")
    full.update(env)
    return subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script], cwd=str(cwd),
                          env=full, capture_output=True, text=True, timeout=120)


def check_workflow_inputs() -> None:
    script = _wf_step("Validate inputs")
    ids = "NUC_phase1_recSynthA,NRT_phase2_recSynthB"
    sha8 = READER["_sha256"][:8]
    ok_reader = {"PROJECT": "gate1r", "BATCH": "6", "MAXB": "120", "NOTE_IDS": ids, "RUN_TAG": R_TAG,
                 "BANK_SHA": sha8, "REANNOTATE": "false", "MODEL": R_MODEL, "CODE_ONLY": "false", "BANK": "reader"}
    prim = {"PROJECT": "gate1", "BATCH": "6", "MAXB": "120", "NOTE_IDS": ids, "RUN_TAG": "primary",
            "BANK_SHA": "", "REANNOTATE": "false", "MODEL": "", "CODE_ONLY": "false", "BANK": ""}
    cwd = ROOT / "scripts"
    r = _bash_step(script, ok_reader, cwd)
    assert r.returncode == 0 and "bank=reader" in r.stdout, (r.returncode, r.stdout, r.stderr)
    for env in (prim, dict(prim, BANK="primary"),
                {**prim, "NOTE_IDS": "", "PROJECT": "NUC_phase1", "RUN_TAG": ""}):
        r = _bash_step(script, env, cwd)
        assert r.returncode == 0, (env, r.stdout, r.stderr)
    cases = [({"BANK": "Reader"}, "bank 只能是"),
             ({"BANK": "../prompts/x.yaml"}, "bank 只能是"),
             ({"RUN_TAG": "primary"}, "run_tag"),
             ({"RUN_TAG": "gate1-sonnet55"}, "必须以 fqr- 开头"),
             ({"RUN_TAG": "fqr-"}, "必须以 fqr- 开头"),
             ({"CODE_ONLY": "true", "MODEL": ""}, "不收 code_only"),
             ({"REANNOTATE": "true"}, "不收 reannotate"),
             ({"BANK_SHA": ""}, "必须给 bank_sha"),
             ({"MODEL": ""}, "必须给 model"),
             ({"NOTE_IDS": "", "PROJECT": "NUC_phase1", "RUN_TAG": "", "BANK_SHA": "", "MODEL": ""},
              "整项目回填永远是主题库")]
    for patch_env, needle in cases:
        r = _bash_step(script, {**ok_reader, **patch_env}, cwd)
        assert r.returncode != 0 and needle in r.stdout, (patch_env, r.returncode, r.stdout[-400:])
    print("  ✓ backfill-features 输入校验 (bash 真跑): reader 要 fqr- / bank_sha / model, 不收 code_only / reannotate / "
          "整项目模式 / 路径; 主题库三种老用法照旧放行")


_FAKE_CURL = r"""
curl() {
  local out="" body=""
  while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift 2;; -d) body="$2"; shift 2;; *) shift;; esac; done
  printf '%s\n' "$body" >> "$FAKE_DIR/bodies.jsonl"
  case "$body" in *'"dry_run":true'*) cp "$FAKE_DIR/probe.json" "$out";; *) cp "$FAKE_DIR/chunk.json" "$out";; esac
  printf 200
}
sleep() { :; }
"""


def check_workflow_probe() -> None:
    script = _wf_step("Run only the given note_ids")
    assert script.count("/tmp/") >= 3
    ids = "NUC_phase1_recSynthA,NUC_phase1_recSynthB,NRT_phase2_recSynthC"
    rsha, psha = READER["_sha256"], PRIMARY_SHA

    def run(env: dict, probe: dict) -> tuple[int, str, list[dict]]:
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "probe.json").write_text(json.dumps(probe, ensure_ascii=False), encoding="utf-8")
            (Path(td) / "chunk.json").write_text(json.dumps({"ok": True, "note_ids_count": 2, "returncode": 0,
                                                             "stdout_tail": "Done: {\"ok\": 2}"}), encoding="utf-8")
            body = _FAKE_CURL + script.replace("/tmp/", td + "/")
            full = {"FAKE_DIR": td, "WORKER_URL": "http://worker.invalid", "WORKER_API_KEY": "k", "NOTE_IDS": ids,
                    "BATCH": "6", "REANNOTATE": "false", "CODE_ONLY": "false", **env}
            r = _bash_step(body, full, ROOT / "scripts")
            p = Path(td) / "bodies.jsonl"
            sent = [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []
            return r.returncode, r.stdout, sent

    def line(bv, sha, model, tag):
        return f"2026 [INFO] annotate_features · bank={bv} sha={sha[:12]}… model={model} run_tag={tag} title_extraction=x single=False"
    reader_env = {"RUN_TAG": R_TAG, "MODEL": R_MODEL, "BANK_SHA": rsha[:8], "BANK": "reader"}
    good = {"ok": True, "note_ids_count": 1, "bank": "reader", "stderr_tail": line("fq-v0.2-cand-reader", rsha, R_MODEL, R_TAG)}
    rc, out, sent = run(reader_env, good)
    assert rc == 0 and "✅ worker 按 bank=fq-v0.2-cand-reader 跑" in out, (rc, out[-600:])
    assert len(sent) == 1 + 2 and all(b.get("bank") == "reader" for b in sent), sent        # 探针 + NUC 一批 + NRT 一批
    assert sent[0]["dry_run"] is True and sent[0]["run_tag"] == R_TAG and sent[0]["model"] == R_MODEL
    # 旧版 worker: 响应没有 bank (吞掉了) → 停在探针, 一个真请求都不发
    old = {k: v for k, v in good.items() if k != "bank"}
    rc, out, sent = run(reader_env, old)
    assert rc == 1 and "没回显 bank=reader" in out and len(sent) == 1, (rc, out[-400:], sent)
    # 回显了 bank, 但日志那行是主题库 (sha 前缀碰巧对上也不行) → 停
    rc, out, sent = run(reader_env, dict(good, stderr_tail=line("fq-v0.1", rsha, R_MODEL, R_TAG)))
    assert rc == 1 and "日志不是 bank=fq-v0.2-cand-reader" in out and len(sent) == 1, (rc, out[-400:])
    # sha 对不上 → 原有那道照样停
    rc, out, sent = run(reader_env, dict(good, stderr_tail=line("fq-v0.2-cand-reader", psha, R_MODEL, R_TAG)))
    assert rc == 1 and "问题库不是期望的" in out and len(sent) == 1, (rc, out[-400:])
    # 主题库 (bank 没给): 旧 worker 的响应照样放行, 请求体一个 bank 键都没有 —— 与 D-128 之前一样
    old_primary = {"ok": True, "note_ids_count": 1, "stderr_tail": line("fq-v0.1", psha, "claude-opus-4-6", "primary")}
    for b in ("", "primary"):
        rc, out, sent = run({"RUN_TAG": "primary", "MODEL": "", "BANK_SHA": "", "BANK": b}, old_primary)
        assert rc == 0 and len(sent) == 3 and not any("bank" in x for x in sent), (b, rc, out[-400:], sent)
    print("  ✓ backfill-features 探针 (bash + 假 curl): reader 要 worker 回显 bank 且日志是 bank=fq-v0.2-cand-reader, 否则停在探针"
          "、不发真请求; 请求体带 bank; 主题库请求体不带 bank、旧 worker 照旧放行")


def check_worker_banks_source() -> None:
    src = (ROOT / "worker" / "app.py").read_text(encoding="utf-8")
    m = re.search(r'^_BANKS = \(([^)]*)\)$', src, re.M)
    assert m, "worker/app.py 里找不到 _BANKS = (...) (写法变了就同步改这里)"
    got = tuple(re.findall(r'"([^"]+)"', m.group(1)))
    assert got == tuple(fb.BANKS), f"worker 的 _BANKS {got} 与 feature_bank.BANKS 的键 {tuple(fb.BANKS)} 不一致"
    print(f"  ✓ worker: _BANKS {got} 与 feature_bank.BANKS 的键逐字相同")


def check_worker_endpoint_bank() -> None:
    """--worker: bank 闭集、副题库在起子进程之前 400、响应永远回显 bank; 不带 bank 时参数与以前一样。"""
    sys.path.insert(0, str(ROOT))
    os.environ.pop("WORKER_API_KEY", None)
    os.environ["WORKER_ALLOW_ANONYMOUS"] = "1"
    from fastapi.testclient import TestClient
    import worker.app as w
    assert w._BANKS == tuple(fb.BANKS), (w._BANKS, tuple(fb.BANKS))
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
            return c.post("/annotate-features", json={"project": "R", **body})
        good = {"bank": "reader", "run_tag": R_TAG, "model": R_MODEL, "note_ids": ["R_recA", "R_recB"]}
        r = post(**good)
        assert r.status_code == 200 and r.json()["bank"] == "reader", (r.status_code, r.json())
        assert seen == [["R", "--limit", "50", "--run-tag", R_TAG, "--model", R_MODEL, "--note-ids", "R_recA,R_recB",
                         "--bank", "reader"]], seen
        # 不带 bank: 参数与 D-128 之前一模一样 (没有 --bank), 响应回显 primary
        r = post(model=R_MODEL)
        assert r.status_code == 200 and seen == [["R", "--limit", "50", "--model", R_MODEL]] and r.json()["bank"] == "primary", seen
        r = post()
        assert seen == [["R", "--limit", "50"]] and r.json()["bank"] == "primary", seen
        r = post(bank="primary", run_tag="primary")
        assert r.status_code == 200 and seen[0][-2:] == ["--bank", "primary"] and r.json()["bank"] == "primary", seen
        for bad in ("Reader", "secondary", "../prompts/feature_questions_v0_2_cand_reader.yaml", "", 1, ["reader"]):
            r = post(**dict(good, bank=bad))
            assert r.status_code == 400 and not seen, (bad, r.status_code, seen)
        for patch_body in ({"run_tag": "primary"}, {"run_tag": None}, {"code_only": True}, {"note_ids": None},
                           {"model": None}, {"done_by": ["llm:%"]}):
            body = {k: v for k, v in {**good, **patch_body}.items() if v is not None}
            r = post(**body)
            assert r.status_code == 400 and not seen and "bank=reader" in r.json()["detail"], (patch_body, r.status_code, r.json())
    finally:
        w._run = real_run
        os.environ.pop("WORKER_ALLOW_ANONYMOUS", None)
    print("  ✓ worker /annotate-features bank (D-128): _BANKS == fb.BANKS 的键; reader 拼 --bank reader 并回显; 不带 bank "
          "参数照旧、回显 primary; 非法 bank / 路径 → 400; reader 配 primary 或缺 run_tag / code_only / 缺 note_ids / "
          "缺 model / done_by → 400 不起子进程")



def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker", action="store_true", help="只跑 worker 端点那一节 (要 fastapi)")
    a = ap.parse_args(argv)
    if a.worker:
        check_worker_endpoint()
        check_worker_endpoint_bank()
        return 0
    check_note_ids()
    check_orchestration()
    check_parse_done_by()
    check_fetch_done_ids()
    check_main_resume()
    check_count_script()
    check_worker_source()
    check_reader_rows()
    check_reader_main()
    check_workflow_inputs()
    check_workflow_probe()
    check_worker_banks_source()
    print("✓ 特征层编排自检 + 续跑判据 (D-085) + 副题库 (D-128): 全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
