"""check_l2_outcome_switch.py —— W-64 ① 的 --outcome 影子开关 (gate2_run / gate3_score / discover_feature_candidates)。

    cd scripts && python check_l2_outcome_switch.py

守得住什么:
  §1 l2_outcome.label_query: hit 查 v_l2_labels、select 串原样、不加过滤; reads 查 v_l2_outcomes、y 是 y_reads_median 的别名、
     只取非空; 闭集外 → ValueError。fetch_labels: reads 读不到视图 → OutcomeUnavailable, 话里带 notes_v1_35; hit 的错原样抛。
  §2 gate2_run: 默认 fetch_dataset 只查 v_l2_labels (和以前同一条查询), 结果和以前一样; reads 时 notes 换成阅读口径、
     notes_hit 是默认那批、答案只取一次; CLI: 默认和显式 --outcome hit 的报告逐字节一样、不带新段落; reads 出两种口径对照;
     reads 带 --write / 副题库 / 取数里没有 notes_hit / 视图读不到 → 退出 2 (最后一种提示跑 notes_v1_35)。反证: 把默认口径改成 reads → 本节红。
  §3 gate3_score: fetch_labeled_all 默认查 v_l2_labels, reads 查 v_l2_outcomes; main 带 --outcome reads 不打分不写库、
     照常的读数后面多一行并排, step summary 写「本轮没打分」不写「本轮新打」; 视图读不到 → 退出 2、提示跑 notes_v1_35;
     不带时照旧写、summary 照旧。
  §4 discover_feature_candidates: 默认提示词逐字节和以前一样、报告没有新键; reads 只换两组的说法、报告写口径和默认口径的组数;
     视图读不到 → 退出 2、提示跑 notes_v1_35。
挡不住什么: 生产上 v_l2_outcomes 的数对不对 (那是 check_l2_outcomes.sql 的事); reads 口径要不要当默认 (owner 定)。
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import feature_bank as fb  # noqa: E402
import l2_outcome  # noqa: E402
import gate2_run as G2  # noqa: E402
import gate3_score as G3  # noqa: E402
import discover_feature_candidates as DFC  # noqa: E402
import _common  # noqa: E402


# ── 假 PostgREST: 记下每条查询 (表 / select / 过滤), 在内存表上真过滤、真投影 (含 a:b 别名) ─────────────
class _Q:
    def __init__(self, sb, name):
        self.sb, self.name, self.cols, self.filters, self.neg = sb, name, None, [], False
        self.rng = None
        self.log = {"table": name, "select": None, "filters": []}
        sb.log.append(self.log)

    def select(self, cols, **_k):
        self.cols, self.log["select"] = cols, cols
        return self

    def _add(self, kind, col, val, fn):
        if self.neg:
            kind, fn, self.neg = "not." + kind, (lambda f: (lambda r: not f(r)))(fn), False
        self.log["filters"].append((kind, col, val))
        self.filters.append(fn)
        return self

    @property
    def not_(self):
        self.neg = True
        return self

    def eq(self, c, v): return self._add("eq", c, v, lambda r: r.get(c) == v)
    def like(self, c, v): return self._add("like", c, v, lambda r: str(r.get(c, "")).startswith(v.rstrip("%")))
    def gte(self, c, v): return self._add("gte", c, v, lambda r: r.get(c) is not None and str(r[c]) >= str(v))
    def in_(self, c, vs): return self._add("in", c, tuple(vs), lambda r, s=set(vs): r.get(c) in s)
    def is_(self, c, v): return self._add("is", c, v, lambda r: r.get(c) is None)
    def order(self, *_a, **_k): return self

    def range(self, a, b):
        self.rng = (a, b)
        return self

    def execute(self):
        if self.name in self.sb.missing:     # 像 PostgREST 对不存在的视图那样报错
            raise RuntimeError(f"relation truth_vault.{self.name} does not exist (42P01)")
        rows = [r for r in self.sb.tables.get(self.name, []) if all(f(r) for f in self.filters)]
        rows.sort(key=lambda r: str(r.get("note_id") or r.get("subject_id") or ""))
        if self.rng:
            rows = rows[self.rng[0]:self.rng[1] + 1]
        if self.cols:
            out = []
            for r in rows:
                d = {}
                for c in (x.strip() for x in self.cols.split(",")):
                    alias, _, src = c.partition(":")
                    d[alias] = r.get(src or alias)
                out.append(d)
            rows = out
        return type("R", (), {"data": rows})()


class _SB:
    def __init__(self, tables, missing=()):
        self.tables, self.log, self.missing = tables, [], set(missing)

    def schema(self, _s): return self
    def table(self, name): return _Q(self, name)
    def tables_read(self): return [q["table"] for q in self.log]


# ── §1 ──────────────────────────────────────────────────────────────────────

def check_label_query() -> None:
    sb = _SB({})
    l2_outcome.label_query(sb, "note_id, y")
    assert sb.log == [{"table": "v_l2_labels", "select": "note_id, y", "filters": []}], sb.log
    sb = _SB({})
    l2_outcome.label_query(sb, "note_id, project_id, y", "reads")
    assert sb.log == [{"table": "v_l2_outcomes", "select": "note_id, project_id, y:y_reads_median",
                       "filters": [("not.is", "y_reads_median", None)]}], sb.log
    for bad in ("Reads", "hit;drop", ""):
        try:
            l2_outcome.label_query(_SB({}), "note_id, y", bad)
            raise AssertionError(f"收了 {bad!r}")
        except ValueError:
            pass
    assert l2_outcome.DEFAULT_OUTCOME == "hit" and l2_outcome.OUTCOMES == ("hit", "reads")
    sb = _SB({}, missing={"v_l2_outcomes", "v_l2_labels"})
    try:
        l2_outcome.fetch_labels(_common.fetch_all_pages, l2_outcome.label_query(sb, "note_id, y", "reads"), "reads")
        raise AssertionError("reads 读不到视图也没报")
    except l2_outcome.OutcomeUnavailable as exc:
        assert l2_outcome.READS_MIGRATION in str(exc) and "42P01" in str(exc), exc
    try:
        l2_outcome.fetch_labels(_common.fetch_all_pages, l2_outcome.label_query(sb, "note_id, y"), "hit")
        raise AssertionError("hit 读不到也没报")
    except l2_outcome.OutcomeUnavailable:
        raise AssertionError("hit 的错不该换成 reads 的提示")
    except RuntimeError as exc:
        assert "42P01" in str(exc)
    # 原错误先打码再截 200 字: 钥匙跨着第 200 个字时, 先截会剩不到 20 个字, 打码认不出来, 漏半截
    fake_key = "sb_secret_" + "Q" * 40

    def _leaky(_q, order_by="note_id"):
        raise RuntimeError("x" * 180 + " apikey=" + fake_key)
    try:
        l2_outcome.fetch_labels(_leaky, None, "reads")
        raise AssertionError("reads 出错也没报")
    except l2_outcome.OutcomeUnavailable as exc:
        shown = G2.mask_secrets(str(exc))             # 调用方照旧再打一遍码
        assert "sb_secret_" not in shown and "QQ" not in shown, shown
    print("  ✓ §1 label_query: hit = v_l2_labels 原样; reads = v_l2_outcomes + y 别名 + 只取非空; 闭集外拒; "
          "reads 读不到视图 → 提示跑 notes_v1_35, hit 的错原样抛; 原错误先打码再截")


# ── §2 gate2_run ─────────────────────────────────────────────────────────────

BANK = fb.load_bank()
SHA = BANK["_sha256"]


def _ds_tables() -> dict:
    labels, outcomes, notes, feats, answers = [], [], [], [], []
    for p in ("PA", "PB", "PC"):
        for i in range(60):
            nid = f"{p}_rec{i:03d}"
            h = int(hashlib.sha256(nid.encode()).hexdigest()[:4], 16)
            y = int(h % 5 == 0)
            yr = int(h % 2 == 0)
            labels.append({"note_id": nid, "project_id": p, "account_id": f"a{h % 7}", "publish_time": f"2026-0{1 + i % 8}-01", "y": y})
            outcomes.append({"note_id": nid, "project_id": p, "account_id": f"a{h % 7}", "publish_time": f"2026-0{1 + i % 8}-01",
                             "y_reads_median": None if i % 10 == 9 else yr})
            notes.append({"note_id": nid, "emotional_lever": "x"})
            feats.append({"note_id": nid, "body_len": 300})
            answers.append({"subject_type": "note", "subject_id": nid, "question_id": "has_specific_time", "question_version": 1,
                            "bank_sha256": SHA, "extractor": "llm:test", "run_tag": "primary",
                            "answer": "是" if (h >> 3) % 3 == 0 else "否"})
    return {"v_l2_labels": labels, "v_l2_outcomes": outcomes, "notes": notes, "note_features": feats,
            "v_notes_vanished": [], "note_feature_answers": answers}


def gate2_default_failures() -> list[str]:
    """默认 fetch_dataset 的行为; 反证时把 l2_outcome.DEFAULT_OUTCOME 改成 reads 再调, 必须有条目。"""
    bad = []
    sb = _SB(_ds_tables())
    ds = G2.fetch_dataset(sb, bank=BANK, sha=SHA[:8], extractors=["llm:test"])
    lab = [q for q in sb.log if q["table"] in ("v_l2_labels", "v_l2_outcomes")]
    if [(q["table"], q["select"], q["filters"]) for q in lab] != [("v_l2_labels", "note_id, project_id, account_id, publish_time, y", [])]:
        bad.append(f"默认取标签的查询变了: {lab}")
    if set(ds) != {"notes", "answers", "vanished_dropped"}:
        bad.append(f"默认返回的键变了: {sorted(ds)}")
    want = sorted((r["note_id"], r["y"]) for r in _ds_tables()["v_l2_labels"])
    if sorted((n["note_id"], n["y"]) for n in ds.get("notes", [])) != want:
        bad.append("默认 notes 不是 v_l2_labels 的 y")
    return bad


def _fixture(td: Path, with_hit: bool = True) -> Path:
    sb = _SB(_ds_tables())
    ds = G2.fetch_dataset(sb, bank=BANK, sha=SHA[:8], extractors=["llm:test"], outcome="reads")
    if not with_hit:
        ds.pop("notes_hit")
    p = td / ("fx.json" if with_hit else "fx_nohit.json")
    p.write_text(json.dumps(ds, ensure_ascii=False), encoding="utf-8")
    return p


def _g2_main(argv) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = G2.main(argv)
    return rc, out.getvalue(), err.getvalue()


def check_gate2() -> None:
    bad = gate2_default_failures()
    assert not bad, "gate2 默认路:\n  " + "\n  ".join(bad)
    saved = l2_outcome.DEFAULT_OUTCOME
    l2_outcome.DEFAULT_OUTCOME = "reads"
    try:
        assert gate2_default_failures(), "反证失败: 默认口径指到 v_l2_outcomes 也是绿的"
    finally:
        l2_outcome.DEFAULT_OUTCOME = saved
    # reads 取数: notes 换成阅读口径 (空值不取), notes_hit = 默认那批, 答案每个 (题, 抽取器) 只取一次
    sb = _SB(_ds_tables())
    ds = G2.fetch_dataset(sb, bank=BANK, sha=SHA[:8], extractors=["llm:test"], outcome="reads")
    t = _ds_tables()
    assert sorted((n["note_id"], n["y"]) for n in ds["notes"]) == sorted(
        (r["note_id"], r["y_reads_median"]) for r in t["v_l2_outcomes"] if r["y_reads_median"] is not None)
    assert sorted((n["note_id"], n["y"]) for n in ds["notes_hit"]) == sorted((r["note_id"], r["y"]) for r in t["v_l2_labels"])
    n_ans_q = sum(1 for q in sb.log if q["table"] == "note_feature_answers")
    assert n_ans_q == len({t_["question_id"] for t_ in G2.bank_targets(BANK)}), n_ans_q
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        fx = _fixture(tdp)
        base = ["--sha", SHA[:8], "--extractors", "llm:test", "--fixture", str(fx), "--run-tag", "gate2-test"]
        rc0, o0, _ = _g2_main(base + ["--out", str(tdp / "d.md")])
        rc1, o1, _ = _g2_main(base + ["--outcome", "hit", "--out", str(tdp / "h.md")])
        d, h = (tdp / "d.md").read_text(encoding="utf-8"), (tdp / "h.md").read_text(encoding="utf-8")
        assert rc0 == rc1 == 0 and d == h and o0 == o1 and "结果口径" not in d and "两种结果口径" not in d, (rc0, rc1)
        rc, _, err = _g2_main(base + ["--outcome", "reads", "--out", str(tdp / "r.md")])
        r = (tdp / "r.md").read_text(encoding="utf-8")
        assert rc == 0 and "> 结果口径: 阅读过本项目中位数" in r and "## 两种结果口径对照" in r and "状态变了的行" in r, (rc, err)
        assert r.splitlines()[0] == d.splitlines()[0], "标题行不该变"
        for extra, needle in ((["--outcome", "reads", "--write", "--expect-rows-sha256", "a" * 12], "影子读数"),
                              (["--outcome", "reads", "--bank", "reader"], "不收 --outcome")):
            rc, _, err = _g2_main(base + extra)
            assert rc == 2 and needle in err, (extra, rc, err)
        rc, _, err = _g2_main(["--sha", SHA[:8], "--extractors", "llm:test", "--fixture", str(_fixture(tdp, False)),
                               "--outcome", "reads"])
        assert rc == 2 and "notes_hit" in err, (rc, err)
    saved_client = _common.get_supabase_client
    _common.get_supabase_client = lambda: _SB(_ds_tables(), missing={"v_l2_outcomes"})
    try:
        rc, _, err = _g2_main(["--sha", SHA[:8], "--extractors", "llm:test", "--outcome", "reads", "--run-tag", "gate2-test"])
    finally:
        _common.get_supabase_client = saved_client
    assert rc == 2 and l2_outcome.READS_MIGRATION in err, (rc, err[-300:])
    print("  ✓ §2 gate2_run: 默认取数只查 v_l2_labels、报告和显式 hit 逐字节一样; reads 换 notes、答案只取一次、出两种口径对照; "
          "reads + --write / 副题库 / 缺 notes_hit / 视图读不到 → 2; 反证 (默认指到新视图) 红")


# ── §3 gate3_score ───────────────────────────────────────────────────────────

def _g3_tables(sc) -> dict:
    fr = sc["freeze_publish_time"]
    later = (datetime.fromisoformat(str(fr)[:10]) + timedelta(days=3)).date().isoformat()
    ids = [f"Q_rec{i:02d}" for i in range(12)]
    return {"content_scores": [{"subject_type": "note", "subject_id": n, "scorer_version": sc["scorer_version"],
                                "pct_in_project": 0.1 if i < 4 else 0.7, "project_id": "Q"} for i, n in enumerate(ids)],
            "v_l2_labels": [{"note_id": n, "y": int(i % 3 == 0), "publish_time": later} for i, n in enumerate(ids)],
            "v_l2_outcomes": [{"note_id": n, "y_reads_median": (None if i == 11 else int(i % 2 == 0)), "publish_time": later}
                              for i, n in enumerate(ids)],
            "note_features": [{"note_id": n, "body_len": 300} for n in ids],
            "v_notes_vanished": [], "notes": []}


def check_gate3() -> None:
    sc = G3.load_scorer(G3.SCORER_PATH)
    t = _g3_tables(sc)
    sb = _SB(t)
    rows, _ = G3.fetch_labeled_all(sb, sc)
    lab = [q for q in sb.log if q["table"] in ("v_l2_labels", "v_l2_outcomes")]
    assert [(q["table"], q["select"]) for q in lab] == [("v_l2_labels", "note_id, y")], lab
    assert sorted((r["note_id"], r["y"]) for r in rows) == sorted((r["note_id"], r["y"]) for r in t["v_l2_labels"])
    sb = _SB(t)
    rows, _ = G3.fetch_labeled_all(sb, sc, outcome="reads")
    lab = [q for q in sb.log if q["table"] in ("v_l2_labels", "v_l2_outcomes")]
    assert [(q["table"], q["select"]) for q in lab] == [("v_l2_outcomes", "note_id, y:y_reads_median")], lab
    assert len(rows) == 11 and all(r["y"] in (0, 1) for r in rows)
    # main: reads 不打分不写库, 多一行并排; 默认照旧写
    saved = {k: getattr(G3, k) for k in ("fetch", "write", "load_scorer")}
    saved_client = _common.get_supabase_client
    writes: list = []
    note = {"note_id": "Q_new", "project_id": "Q", "publish_time": "2099-01-01", "created_at": "2099-01-01"}
    G3.fetch = lambda sb_, sc_: ([], set())
    G3.write = lambda sb_, rows_: writes.append(len(rows_)) or len(rows_)
    _common.get_supabase_client = lambda: _SB(t)
    try:
        G3.plan_real = G3.plan
        G3.plan = lambda notes, done, sc_, now: {"rows": [{"subject_id": "Q_new"}], "counts": {
            "after_freeze": 1, "already": 0, "no_essence": 0, "stale_essence": 0, "annotator_mismatch": 0,
            "unscorable": 0, "project_cut": 1, "pooled": 0}, "mismatch": []}
        with tempfile.TemporaryDirectory() as td:
            summ = Path(td, "summary.md")

            def g3(argv):
                summ.write_text("", encoding="utf-8")
                out = io.StringIO()
                old = os.environ.get("GITHUB_STEP_SUMMARY")
                os.environ["GITHUB_STEP_SUMMARY"] = str(summ)
                try:
                    with contextlib.redirect_stdout(out):
                        rc_ = G3.main(argv)
                finally:
                    if old is None:
                        os.environ.pop("GITHUB_STEP_SUMMARY", None)
                    else:
                        os.environ["GITHUB_STEP_SUMMARY"] = old
                return rc_, out.getvalue(), summ.read_text(encoding="utf-8")
            rc, out, sm = g3(["--outcome", "reads"])
            assert rc == 0 and writes == [] and "并排 (W-64 ①" in out and "不打分" in out, (rc, writes, out[-400:])
            assert "本轮没打分" in sm and "本轮新打" not in sm and "并排 (W-64 ①" in sm, sm
            _common.get_supabase_client = lambda: _SB(t, missing={"v_l2_outcomes"})
            rc, out, sm = g3(["--outcome", "reads"])
            assert rc == 2 and writes == [] and l2_outcome.READS_MIGRATION in out, (rc, out[-400:])
            _common.get_supabase_client = lambda: _SB(t)
            G3.fetch = lambda sb_, sc_: ([], {"Q_new"})
            rc, out, sm = g3([])
            assert writes == [1] and "W-64" not in out and "本轮新打 1 篇" in sm and "W-64" not in sm, (writes, out[-300:], sm)
    finally:
        G3.plan = G3.plan_real
        del G3.plan_real
        for k, v in saved.items():
            setattr(G3, k, v)
        _common.get_supabase_client = saved_client
    print("  ✓ §3 gate3_score: 取标签默认 v_l2_labels / reads v_l2_outcomes; --outcome reads 不写 content_scores、多一行并排、"
          "summary 写「本轮没打分」; 视图读不到 → 2; 默认照旧写")


# ── §4 discover ──────────────────────────────────────────────────────────────

def check_discover() -> None:
    existing = DFC.existing_questions(BANK)
    legacy = DFC.SYSTEM.format(k=DFC.PER_PROJECT_CANDIDATES, existing="\n".join(f"{i}: {a}" for i, a in existing))
    assert DFC.system_prompt(existing) == legacy, "默认提示词变了"
    reads = DFC.system_prompt(existing, "reads")
    assert DFC.GROUPS_HIT in legacy and DFC.GROUPS_READS in reads and DFC.GROUPS_HIT not in reads
    assert reads.replace(DFC.GROUPS_READS, DFC.GROUPS_HIT) == legacy, "reads 只该换两组的说法"
    now = datetime(2026, 10, 19, tzinfo=timezone.utc)
    labels = [{"note_id": f"P_rec{i:03d}", "project_id": "P", "publish_time": "2026-09-01T00:00:00", "y": i % 2} for i in range(80)]
    kw = dict(labels=labels, fetch_notes=lambda ids: {}, categories={}, bank=BANK, call=None, since=now - timedelta(days=92))
    r0 = DFC.run(**kw)
    assert "outcome" not in r0 and "结果口径" not in DFC.render(r0, dry_run=True)
    r1 = DFC.run(**kw, outcome="reads")
    r1["hit_groups"] = {"P": {1: 3, 0: 9}}
    md = DFC.render(r1, dry_run=True)
    assert r1["outcome"] == "reads" and "结果口径: 阅读过本项目中位数" in md and "P 3/9" in md, md
    saved_client = _common.get_supabase_client
    _common.get_supabase_client = lambda: _SB({}, missing={"v_l2_outcomes"})
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = DFC.main(["--outcome", "reads", "--dry-run"])
    finally:
        _common.get_supabase_client = saved_client
    assert rc == 2 and l2_outcome.READS_MIGRATION in err.getvalue(), (rc, err.getvalue()[-300:])
    print("  ✓ §4 discover: 默认提示词逐字节不变、报告没有新键; reads 只换两组的说法、报告写口径和默认口径的组数; 视图读不到 → 2")


def main() -> int:
    check_label_query()
    check_gate2()
    check_gate3()
    check_discover()
    print("✓ W-64 ① --outcome 影子开关: 全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
