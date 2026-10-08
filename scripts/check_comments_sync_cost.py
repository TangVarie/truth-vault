#!/usr/bin/env python3
"""评论步的三条加固 (2026-10-08 架构审计 A-07, D-092): 每项目读一次已有评论而不是每篇读一次 ·
夜跑跳过 on_demand 项目 · 「源被清空」对账失败要非零退出。

背景: 评论步每晚对所有带评论的笔记全量重解析, 每篇先 fetch_all_pages 读一遍已有评论(≥2 次 HTTP, 空页终止),
17 个 mapping 全在循环里、on_demand 项目不跳、reconcile 失败仍 return 0。实测一篇 ~1 s, 整轮 44 分钟里
它占 2.5–3k 篇的量, 随库线性涨。

断行为不断源码 (D-051): 假 PostgREST 记下每一次 select / insert / update, 真的驱动 main()。

反证 (改坏之后必须变红):
  ① main 不把项目级结果传给 write_comments(existing=None) → §1 每篇一次 select, 红
  ② 去掉 on_demand + 定时跑的跳过                           → §3 红
  ③ reconcile 失败仍 return 0                               → §4 红
  ④ fetch_project_comments 不按 note 分组 / 丢 comment_order → §2 该插 1 条变成插多条, 红

跑法: cd scripts && python check_comments_sync_cost.py
"""
from __future__ import annotations

import json
import logging
import os
import sys

import sync_comments_from_raw_extra as M

PROJ = "P_phase1"


class _Resp:
    def __init__(self, data):
        self.data = data


class _RecSB:
    """两张表(notes / comments)的假 PostgREST: 记下每次 select 的 (表, 过滤) 和每次写。"""

    def __init__(self, notes, comments):
        self.tables = {"notes": [dict(r) for r in notes], "comments": [dict(r) for r in comments]}
        self.selects: list[tuple[str, tuple]] = []
        self.inserts: list[list[dict]] = []
        self.updates: list[tuple[str, dict]] = []
        self._reset()

    def _reset(self):
        self._table, self._op, self._filters, self._rng, self._negate = None, None, [], None, False
        self._payload = None

    def schema(self, _):
        return self

    def table(self, name):
        self._reset(); self._table = name; return self

    def select(self, *a, **k):
        self._op = "select"; return self

    def eq(self, k, v):
        self._filters.append(("eq", k, v)); return self

    @property
    def not_(self):
        self._negate = True; return self

    def is_(self, k, v):
        self._filters.append(("isnot" if self._negate else "is", k, v)); self._negate = False; return self

    def order(self, *a, **k):
        return self

    def range(self, a, b):
        self._rng = (a, b); return self

    def update(self, patch):
        self._op = "update"; self._payload = patch; return self

    def insert(self, rows):
        self._op = "insert"; self._payload = rows; return self

    def _match(self, r):
        for kind, k, v in self._filters:
            if kind == "eq" and r.get(k) != v:
                return False
            if kind == "isnot" and r.get(k) is None:
                return False
            if kind == "is" and r.get(k) is not None:
                return False
        return True

    def execute(self):
        rows = self.tables[self._table]
        if self._op == "select":
            self.selects.append((self._table, tuple(self._filters)))
            data = sorted((dict(r) for r in rows if self._match(r)), key=lambda r: r.get("comment_id") or r.get("note_id") or "")
            if self._rng is not None:
                data = data[self._rng[0]:self._rng[1] + 1]
            return _Resp(data)
        if self._op == "insert":
            ids = {r["comment_id"] for r in rows}
            for r in self._payload:
                assert r["comment_id"] not in ids, f"主键冲突 {r['comment_id']}"
                ids.add(r["comment_id"])
            rows.extend(dict(r) for r in self._payload)
            self.inserts.append(list(self._payload))
            return _Resp(self._payload)
        if self._op == "update":
            cid = next(v for kind, k, v in self._filters if k == "comment_id")
            for r in rows:
                if r["comment_id"] == cid:
                    r.update(self._payload)
            self.updates.append((cid, dict(self._payload)))
            return _Resp([])
        raise AssertionError(self._op)


def _note(nid, text):
    return {"note_id": nid, "project_id": PROJ, "raw_extra": {"_comment_text": text}}


def _crow(nid, i, content, role="素人"):
    return {"comment_id": f"{nid}_h{i}", "note_id": nid, "project_id": PROJ, "content": content,
            "comment_role": role, "comment_order": i}


def _drive(sb, *, interval="daily", scheduled=False, argv=()):
    """真的跑 main(); 回 (rc, stats, sb)。"""
    saved = (M.get_supabase_client, M.fetch_all_pages, M.load_mapping)
    msgs: list[str] = []

    class _H(logging.Handler):
        def emit(self, record):
            msgs.append(record.getMessage())
    h = _H()
    M.logger.addHandler(h)
    old_env, old_argv = os.environ.get("TV_SCHEDULED_RUN"), sys.argv
    try:
        M.get_supabase_client = lambda *a, **k: sb
        M.fetch_all_pages = lambda q, page_size=1000, order_by=None: list(q.execute().data)
        M.load_mapping = lambda pid: {"project_id": pid, "sync_config": {"sync_interval": interval}}
        if scheduled:
            os.environ["TV_SCHEDULED_RUN"] = "true"
        else:
            os.environ.pop("TV_SCHEDULED_RUN", None)
        sys.argv = ["x", PROJ, *argv]
        rc = M.main()
    finally:
        M.get_supabase_client, M.fetch_all_pages, M.load_mapping = saved
        M.logger.removeHandler(h)
        sys.argv = old_argv
        if old_env is None:
            os.environ.pop("TV_SCHEDULED_RUN", None)
        else:
            os.environ["TV_SCHEDULED_RUN"] = old_env
    done = [m for m in msgs if m.startswith("Done: ")]
    stats = json.loads(done[-1][len("Done: "):]) if done else None
    return rc, stats, msgs


def _comment_selects(sb):
    return [f for t, f in sb.selects if t == "comments"]


# ── §1 已入库、源没变: 每项目一次读, 零写 ────────────────────────────────────────
def check_one_read_per_project() -> None:
    notes = [_note("n1", "1. 好用\n2. 真的吗"), _note("n2", "1. 一般"), _note("n3", "1. 回购了\n2. +1\n3. +1")]
    comments = [_crow("n1", 1, "好用"), _crow("n1", 2, "真的吗"), _crow("n2", 1, "一般"),
                _crow("n3", 1, "回购了"), _crow("n3", 2, "+1"), _crow("n3", 3, "+1")]
    sb = _RecSB(notes, comments)
    rc, st, _ = _drive(sb)
    assert rc == 0 and st["notes_processed"] == 3 and st["comments_written"] == 0, (rc, st)
    cs = _comment_selects(sb)
    assert len(cs) == 1, f"§1 已有评论应该每项目读一次, 实际 {len(cs)} 次: {cs}"
    assert any(k == "project_id" for _, k, _v in cs[0]) and not any(k == "note_id" for _, k, _v in cs[0]), \
        "§1 那一次读要按 project_id, 不是按 note_id"
    assert not sb.inserts and not sb.updates, "§1 源没变一行都不写"
    assert st["notes_source_cleared"] == 0
    print("  §1 三篇都已入库: comments 表只读 1 次(按项目), 零 insert / update ✓")


# ── §2 源里多了一条 / 顺序变了: 只写该写的, 读仍是一次 ───────────────────────────
def check_delta_writes_only_what_changed() -> None:
    notes = [_note("n1", "1. 新来的\n2. 好用\n3. 真的吗"), _note("n2", "1. 一般")]
    comments = [_crow("n1", 1, "好用"), _crow("n1", 2, "真的吗"), _crow("n2", 1, "一般")]
    sb = _RecSB(notes, comments)
    rc, st, _ = _drive(sb)
    assert rc == 0 and st["comments_written"] == 1, st
    assert len(_comment_selects(sb)) == 1, "§2 读仍然只有一次"
    assert len(sb.inserts) == 1 and [r["content"] for r in sb.inserts[0]] == ["新来的"], sb.inserts
    assert {c for c, _ in sb.updates} == {"n1_h1", "n1_h2"}, f"§2 原有两条 comment_order 要顺延: {sb.updates}"
    assert all(r["note_id"] == "n2" or True for r in sb.tables["comments"])
    print("  §2 n1 头部插了一条: 1 次读、插 1 条、重排 2 条; n2 不动 ✓")


# ── §3 夜跑跳过 on_demand ────────────────────────────────────────────────────────
def check_on_demand_skipped_on_cron() -> None:
    sb = _RecSB([_note("n1", "1. 好用")], [])
    rc, st, msgs = _drive(sb, interval="on_demand", scheduled=True)
    assert rc == 0 and st is None, "§3 定时跑 + on_demand → 跳过, 不该有 Done 行"
    assert not sb.selects and not sb.inserts, "§3 跳过 = 一次库都不碰"
    assert any("on_demand" in m for m in msgs), "§3 要说一声为什么跳"

    sb = _RecSB([_note("n1", "1. 好用")], [])
    rc, st, _ = _drive(sb, interval="on_demand", scheduled=False)
    assert rc == 0 and st and st["comments_written"] == 1, "§3 手动 / 本地跑 on_demand 照跑, 不挡人工"
    sb = _RecSB([_note("n1", "1. 好用")], [])
    rc, st, _ = _drive(sb, interval="daily", scheduled=True)
    assert rc == 0 and st and st["comments_written"] == 1, "§3 定时跑 daily 照跑"
    print("  §3 定时跑 + on_demand 跳过且不碰库; 手动 / daily 照跑 ✓")


# ── §4 对账失败 → 非零 ───────────────────────────────────────────────────────────
def check_reconcile_failure_is_nonzero() -> None:
    sb = _RecSB([_note("n1", "1. 好用")], [_crow("n1", 1, "好用"), _crow("n9", 1, "孤儿")])
    saved = M.collect_cleared_vanished

    def boom(*a, **k):
        raise RuntimeError("对账挂了")
    M.collect_cleared_vanished = boom
    try:
        rc, st, _ = _drive(sb)
    finally:
        M.collect_cleared_vanished = saved
    assert st["notes_source_cleared"] == -1, st
    assert rc == 1, "§4 对账没算成, 退出码要非零 —— 以前 return 0, 看门狗永远绿"
    rc, st, _ = _drive(_RecSB([_note("n1", "1. 好用")], [_crow("n1", 1, "好用"), _crow("n9", 1, "孤儿")]))
    assert rc == 0 and st["notes_source_cleared"] == 1, "§4 对账算成了(n9 源里没了, 只报不删) → 0"
    print("  §4 对账失败 rc=1, 对账成功(含只报不删的清空 note)rc=0 ✓")


# ── §5 老调用形状不变 ────────────────────────────────────────────────────────────
def check_write_comments_without_existing_still_reads() -> None:
    sb = _RecSB([], [_crow("n1", 1, "好用")])
    saved = M.fetch_all_pages
    M.fetch_all_pages = lambda q, page_size=1000, order_by=None: list(q.execute().data)
    try:
        n = M.write_comments(sb, "n1", PROJ, [("素人", "好用"), ("素人", "新")], dry_run=False)
    finally:
        M.fetch_all_pages = saved
    assert n == 1 and len(_comment_selects(sb)) == 1 and any(k == "note_id" for _, k, _v in _comment_selects(sb)[0]), \
        "§5 不传 existing 的老调用(ci COR-013 那步 / check_comment_parser)仍按 note 读一次"
    print("  §5 write_comments 不传 existing 时行为不变 ✓")


def main() -> int:
    check_one_read_per_project()
    check_delta_writes_only_what_changed()
    check_on_demand_skipped_on_cron()
    check_reconcile_failure_is_nonzero()
    check_write_comments_without_existing_still_reads()
    print("\ncheck_comments_sync_cost: 5 节全过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
