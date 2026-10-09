#!/usr/bin/env python3
"""CI 守卫: 飞书里已删的篇不再喂下游 (审计 B-21, D-103)。

  §1 schemas/notes_v1_21_vanished_notes.sql 的判据: 按【本项目】最近一次完整同步 (DISTINCT ON project_id ... ORDER BY
     last_seen_at DESC) 比 last_seen_run_id; 从没盖过戳的 (IS NULL) 不算
  §2 _common.fetch_vanished_note_ids: 读 v_notes_vanished, 按 note_id 翻页, 可按项目筛, 回 set
  §3 curate_flywheel_lessons.fetch_uncurated_cards: 名单里的卡不进策展 (默认路 / --recurate 都是), 项目筛传下去
  §4 sync_truth_vault_baokuan_to_sanshengliubu.fetch_pending_baokuan: 资格全够也不推名单里的篇, 项目筛传下去
  §5 gate2_run.fetch_dataset: 名单里的篇不进闸二 notes, vanished_dropped 数出来
  §6 verify_supabase_state.sql #93 读这张视图 (灯)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))


class _Rec:
    """假 query builder: 记下表名和过滤, 任何链式调用都回自己; execute 回 rows 的翻页切片。"""

    def __init__(self, name, rows, log):
        self.name, self.rows, self.log, self._rng = name, rows, log, (0, None)
        log.append(("table", name))

    def __getattr__(self, meth):
        def _call(*a, **k):
            self.log.append((meth, a, k))
            if meth == "range":
                self._rng = (a[0], a[1])
            return self
        return _call

    def execute(self):
        start, end = self._rng
        page = list(self.rows)[start:(end + 1) if end is not None else None]
        return type("R", (), {"data": page})()


class _SB:
    def __init__(self, tables):
        self.tables, self.log = tables, []

    def schema(self, _s): return self
    def table(self, name): return _Rec(name, self.tables.get(name, []), self.log)


def main() -> int:
    fails: list[str] = []

    # §1
    sql = (HERE.parent / "schemas" / "notes_v1_21_vanished_notes.sql").read_text(encoding="utf-8")
    body = re.sub(r"(?m)^\s*--.*$", "", sql)
    for needle in ("CREATE OR REPLACE VIEW truth_vault.v_notes_vanished", "DISTINCT ON (project_id)",
                   "ORDER BY project_id, last_seen_at DESC", "WHERE last_seen_run_id IS NOT NULL",
                   "n.last_seen_run_id IS NOT NULL", "n.last_seen_run_id <> l.latest_run_id",
                   "JOIN latest l ON l.project_id = n.project_id", "AS has_lesson_card"):
        if needle not in body:
            fails.append(f"§1 视图里缺: {needle}")
    if re.search(r"interval\s+'\d+ days?'", body):
        fails.append("§1 判据不许用固定天数 (on_demand 项目不进夜跑会被整批报成消失)")

    # §2
    import _common as C
    rows = [{"note_id": "v1"}, {"note_id": "v2"}]
    sb = _SB({"v_notes_vanished": rows})
    got = C.fetch_vanished_note_ids(sb)
    tables = [x[1] for x in sb.log if x[0] == "table"]
    if got != {"v1", "v2"} or tables != ["v_notes_vanished"] or any(x[0] == "eq" for x in sb.log):
        fails.append(f"§2 不筛项目时应读 v_notes_vanished 全表回 set: got={got} log={sb.log}")
    if not any(x[0] == "order" and x[1][:1] == ("note_id",) for x in sb.log):
        fails.append(f"§2 要按 note_id 翻页 (fetch_all_pages 的唯一键): {sb.log}")
    sb = _SB({"v_notes_vanished": rows})
    C.fetch_vanished_note_ids(sb, "P1")
    if ("eq", ("project_id", "P1"), {}) not in sb.log:
        fails.append(f"§2 给了项目要 eq project_id: {sb.log}")

    # §3
    import curate_flywheel_lessons as cur
    view = [{"source_note_id": "a", "is_curated": False, "rank_score": 1.0, "curated_at": None},
            {"source_note_id": "gone", "is_curated": False, "rank_score": 0.9, "curated_at": None},
            {"source_note_id": "c", "is_curated": True, "rank_score": 0.8, "curated_at": "2026-09-01T00:00:00"}]
    calls: list = []
    cur.fetch_all_pages = lambda q, page_size=1000, order_by=None: [dict(r) for r in view]
    cur.fetch_vanished_note_ids = lambda _sb, project_id=None: calls.append(project_id) or {"gone"}
    got3 = [c["source_note_id"] for c in cur.fetch_uncurated_cards(_SB({}), "P7", False)]
    if got3 != ["a", "c"] or calls != ["P7"]:
        fails.append(f"§3 默认路: 名单里的 gone 不进策展、项目筛传下去: got={got3} calls={calls}")
    got3b = [c["source_note_id"] for c in cur.fetch_uncurated_cards(_SB({}), None, True)]
    if got3b != ["a", "c"] or calls[-1] is not None:
        fails.append(f"§3 --recurate 路同样排除: got={got3b} calls={calls}")
    cur.fetch_vanished_note_ids = lambda _sb, project_id=None: set()
    if [c["source_note_id"] for c in cur.fetch_uncurated_cards(_SB({}), None, False)] != ["a", "gone", "c"]:
        fails.append("§3 名单为空时卡集不变")

    # §4
    import sync_truth_vault_baokuan_to_sanshengliubu as S
    from datetime import datetime, timezone
    recent = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    def note(nid):
        return dict(note_id=nid, project_id="P", platform="xiaohongshu", tier="爆", tier_source="状态字段",
                    publish_time=recent, synced_to_ssll_at=None, data_quality_flags=None)
    notes = [note("keep"), note("gone")]
    S.fetch_all_pages = lambda q, page_size=1000, order_by=None: [dict(r) for r in notes]
    seen: list = []
    S.fetch_vanished_note_ids = lambda _sb, project_id=None: seen.append(project_id) or {"gone"}
    got4 = sorted(r["note_id"] for r in S.fetch_pending_baokuan(_SB({}), "P"))
    if got4 != ["keep"] or seen != ["P"]:
        fails.append(f"§4 通道 1 不推名单里的篇、项目筛传下去: got={got4} seen={seen}")
    S.fetch_vanished_note_ids = lambda _sb, project_id=None: set()
    if sorted(r["note_id"] for r in S.fetch_pending_baokuan(_SB({}))) != ["gone", "keep"]:
        fails.append("§4 名单为空时推送候选不变")

    # §5
    import gate2_run as G
    import feature_bank as fb
    bank = fb.load_bank()
    tables = {"v_l2_labels": [{"note_id": "n1", "project_id": "P", "account_id": "a", "publish_time": "2026-01-01", "y": 1},
                              {"note_id": "gone", "project_id": "P", "account_id": "a", "publish_time": "2026-01-01", "y": 0},
                              {"note_id": "n3", "project_id": "Q", "account_id": "b", "publish_time": "2026-01-01", "y": 1}],
              "notes": [{"note_id": "n1", "emotional_lever": "x"}, {"note_id": "gone", "emotional_lever": "x"}],
              "note_features": [{"note_id": "n1", "body_len": 100}], "note_feature_answers": []}
    C.fetch_all_pages = lambda q, page_size=1000, order_by=None: [dict(r) for r in tables.get(q.name, [])]
    C.fetch_vanished_note_ids = lambda _sb, project_id=None: {"gone"}
    ds = G.fetch_dataset(_SB(tables), bank=bank, sha="deadbeef", extractors=["llm:test"])
    ids = sorted(n["note_id"] for n in ds["notes"])
    if ids != ["n1", "n3"] or ds.get("vanished_dropped") != 1:
        fails.append(f"§5 闸二取数要排掉名单里的篇并数出来: ids={ids} dropped={ds.get('vanished_dropped')}")
    ds = G.fetch_dataset(_SB(tables), bank=bank, sha="deadbeef", extractors=["llm:test"], projects={"Q"})
    if [n["note_id"] for n in ds["notes"]] != ["n3"] or ds.get("vanished_dropped") != 0:
        fails.append(f"§5 --projects 之外的消失篇不计入 dropped: {ds['notes']} / {ds.get('vanished_dropped')}")

    # §6
    verify = (HERE / "verify_supabase_state.sql").read_text(encoding="utf-8")
    if "SELECT '93'," not in verify or "truth_vault.v_notes_vanished" not in verify:
        fails.append("§6 verify_supabase_state.sql 要有 #93 读 v_notes_vanished")

    for f in fails:
        print("  ❌", f)
    if fails:
        print(f"❌ vanished notes: {len(fails)} 条不过")
        return 1
    print("✅ vanished notes: §1 视图判据 · §2 取 id · §3 新策展 · §4 通道 1 · §5 闸二取数 · §6 verify 灯 全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
