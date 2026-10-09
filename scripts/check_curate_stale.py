#!/usr/bin/env python3
"""CI 守卫: 重策展"essence 比卡新"的那条路 (D-096, 2026-10-08 审计 B-02)。

  §1 stale_cards: 只挑 essence_annotated_at > curated_at 的; 相等 / 更早 / 缺 / 认不出 → 不挑 (不乱花钱)
  §2 时区: 带偏移的 essence 时间与 naive UTC 的 curated_at 比得对 (+08:00 的 10:00 = UTC 02:00)
  §3 fetch_uncurated_cards(stale_only=True): 只取 is_curated=true, 再按 notes.essence_annotated_at 过滤;
     默认路径仍是 is_curated=false (daily-sync 的行为一字不变)
  §4 worker /curate: recurate="stale" → --recurate-stale; "all"/true → --recurate; 省略 → 都不带; 别的 → 400
  §5 收敛前提: 重策展写回的 curated_at 是现在 (写回路径没改也要钉住: 否则 stale 永远 stale, 工作流空转烧钱)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import curate_flywheel_lessons as cur  # noqa: E402


class _Q:
    """记录 .eq / .in_ 过滤的假 query builder, 够 fetch_all_pages / in_ 查询用。"""

    def __init__(self, rows, log):
        self.rows, self.log, self.filters = rows, log, []

    def select(self, *_a, **_k): return self
    def order(self, *_a, **_k): return self
    def range(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self

    def eq(self, col, val):
        self.filters.append(("eq", col, val)); return self

    def in_(self, col, vals):
        self.filters.append(("in", col, list(vals))); return self

    def execute(self):
        out = self.rows
        for kind, col, val in self.filters:
            out = [r for r in out if (r.get(col) == val if kind == "eq" else r.get(col) in val)]
        self.log.append(list(self.filters))
        self._done = getattr(self, "_done", False)
        if self._done:        # fetch_all_pages 翻到第二页 → 空
            return type("R", (), {"data": []})()
        self._done = True
        return type("R", (), {"data": out})()


class _SB:
    def __init__(self, tables):
        self.tables, self.log = tables, []

    def schema(self, _s): return self
    def table(self, name): return _Q(self.tables[name], self.log)


def main() -> int:
    fails: list[str] = []

    # §1
    cards = [{"source_note_id": "a", "curated_at": "2026-09-01T00:00:00"},
             {"source_note_id": "b", "curated_at": "2026-09-01T00:00:00"},
             {"source_note_id": "c", "curated_at": "2026-09-01T00:00:00"},
             {"source_note_id": "d", "curated_at": None},
             {"source_note_id": "e", "curated_at": "2026-09-01T00:00:00"}]
    ess = {"a": "2026-09-02T00:00:00", "b": "2026-09-01T00:00:00", "c": "2026-08-01T00:00:00",
           "d": "2026-10-01T00:00:00", "e": "not a date"}
    got = {c["source_note_id"] for c in cur.stale_cards(cards, ess)}
    if got != {"a"}:
        fails.append(f"§1 只有 a 的 essence 比卡新, 实际挑了 {sorted(got)}")

    # §2
    tz_cards = [{"source_note_id": "x", "curated_at": "2026-09-01T03:00:00"}]
    if cur.stale_cards(tz_cards, {"x": "2026-09-01T10:00:00+08:00"}):
        fails.append("§2 +08:00 的 10:00 = UTC 02:00 < 03:00, 不该算新")
    if not cur.stale_cards(tz_cards, {"x": "2026-09-01T12:00:00+08:00"}):
        fails.append("§2 +08:00 的 12:00 = UTC 04:00 > 03:00, 该算新")

    # §3
    view = [{"source_note_id": "n1", "is_curated": True, "curated_at": "2026-09-01T00:00:00", "rank_score": 1},
            {"source_note_id": "n2", "is_curated": True, "curated_at": "2026-09-05T00:00:00", "rank_score": 0.9},
            {"source_note_id": "n3", "is_curated": False, "curated_at": None, "rank_score": 0.8}]
    notes = [{"note_id": "n1", "essence_annotated_at": "2026-09-03T00:00:00"},
             {"note_id": "n2", "essence_annotated_at": "2026-09-03T00:00:00"},
             {"note_id": "n3", "essence_annotated_at": "2026-09-03T00:00:00"}]
    sb = _SB({"v_flywheel_lesson_cards": view, "notes": notes, "v_notes_vanished": []})
    got3 = [c["source_note_id"] for c in cur.fetch_uncurated_cards(sb, None, True, stale_only=True)]
    if got3 != ["n1"]:
        fails.append(f"§3 stale_only 应只回 n1 (已策展且 essence 更新), 实际 {got3}")
    if not any(("eq", "is_curated", True) in f for f in sb.log):
        fails.append("§3 stale_only 必须先按 is_curated=true 取 (别把未策展的也拉下来)")
    sb2 = _SB({"v_flywheel_lesson_cards": view, "notes": notes, "v_notes_vanished": []})
    got_default = [c["source_note_id"] for c in cur.fetch_uncurated_cards(sb2, None, False)]
    if got_default != ["n3"] or not any(("eq", "is_curated", False) in f for f in sb2.log):
        fails.append(f"§3 默认路径仍该只取 is_curated=false → n3, 实际 {got_default}")
    if any(("in", "note_id", ["n3"]) in f for f in sb2.log):
        fails.append("§3 默认路径不该去查 notes.essence_annotated_at")

    # §4
    try:
        import worker.app as w
        from fastapi.testclient import TestClient
    except ImportError as exc:                       # 本地 venv 没装 fastapi: CI 装了, 这里说清而不是假装过
        print(f"  ⚠️ §4 跳过 (import 失败: {exc}); CI 的 python job 装了 worker 依赖, 那里会跑")
        w = None
    if w is not None:
        seen: list[list[str]] = []
        w._run = lambda script, args: seen.append(list(args)) or {"ok": True, "returncode": 0, "stdout_tail": "", "stderr_tail": ""}
        w._check_auth = lambda *_a, **_k: None
        c = TestClient(w.app)
        for body, want in [({"limit": 3, "recurate": "stale"}, ["--recurate-stale"]),
                           ({"limit": 3, "recurate": "all"}, ["--recurate"]),
                           ({"limit": 3, "recurate": True}, ["--recurate"]),
                           ({"limit": 3}, [])]:
            r = c.post("/curate", json=body)
            if r.status_code != 200:
                fails.append(f"§4 {body} → HTTP {r.status_code}: {r.text[:120]}"); continue
            flags = [a for a in seen[-1] if a.startswith("--recurate")]
            if flags != want:
                fails.append(f"§4 {body} → 期望 {want}, 实际 {flags}")
        r = c.post("/curate", json={"limit": 3, "recurate": "yes"})
        if r.status_code != 400:
            fails.append(f"§4 recurate='yes' 该 400, 实际 {r.status_code}")

    # §5
    import inspect
    src = inspect.getsource(cur.write_lesson_back)
    if '"curated_at": _iso_now()' not in src:
        fails.append("§5 写回必须把 curated_at 置为现在, 否则 stale 永远 stale、重策展工作流空转烧钱")

    for f in fails:
        print("  ❌", f)
    if fails:
        print(f"❌ curate stale: {len(fails)} 条不过")
        return 1
    print("✅ curate stale: §1 挑选 · §2 时区 · §3 取数 · §4 worker 映射 · §5 收敛前提 全过")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("AW_DISABLE_ST_CACHE", "1")
    sys.exit(main())
