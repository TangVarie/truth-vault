#!/usr/bin/env python3
"""CI 守卫: 「已标 essence 但 direction_subtype 空」那条补标路 (2026-10-08 审计 C-03)。

NUC 10-08 实查 206 篇 essence_annotated_at 非空、direction_subtype 空、raw_extra 有 _direction_raw: 以前只有
--reannotate 全重做能补 (不收敛: 每轮 --limit 都从 note_id 最小的开始), 从没跑过。

  §1 annotate_essence_pass.fetch_unannotated_notes(only_missing_subtype=True) 的过滤 = 三条库判据 + (给了 mapping 时)
     "方向在 direction_decomposition 里定义了 sub_directions"这道内存筛 (codex review on #169, P1: 单方向配置的篇
     永远判不出 direction_subtype, 不筛就每轮重标、remaining 不收敛); 默认路径不变; --reannotate 不加 essence 过滤
  §2 count_unannotated_essence.count_remaining(only_missing_subtype=True) 走 subtype_backfill_candidates —— 和抽取
     同一个函数 (两边不一致就不收敛); 默认 count 路径不变
  §3 worker /annotate-essence: only_missing_subtype → --only-missing-subtype
  §4 backfill-essence.yml: mode 输入存在、missing_subtype 时 remaining 与请求体都切判据
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))


class _Q:
    def __init__(self, log, rows):
        self.log, self.rows, self._neg, self._rng = log, rows, False, (0, None)

    def select(self, *a, **k): return self
    def eq(self, c, v): self.log.append(("eq", c, v)); return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self

    def range(self, start, end):
        self._rng = (start, end)          # fetch_all_pages 翻页: 按 offset 切片, 翻到空页为止
        return self

    @property
    def not_(self):
        self._neg = True
        return self

    def is_(self, c, v):
        self.log.append(("not.is" if self._neg else "is", c))
        self._neg = False
        return self

    def execute(self):
        start, end = self._rng
        page = list(self.rows)[start:(end + 1) if end is not None else None]
        return type("R", (), {"data": page, "count": 7})()


class _SB:
    def __init__(self, rows=()):
        self.log, self.rows = [], list(rows)

    def schema(self, _s): return self
    def table(self, _n): return _Q(self.log, self.rows)


MISSING = [("not.is", "essence_annotated_at"), ("is", "direction_subtype"), ("not.is", "raw_extra->_direction_raw")]

# 映射里两种方向: 「多方向」定义了 sub_directions (有子方向可判), 「单方向」没有 (sync 时就确定性抬到 direction, 永远没有
# direction_subtype)。库判据三条都过的四篇里, 只有方向 = 多方向 的两篇 (含飞书多选给的 list 形态) 是真候选。
MAPPING = {"direction_decomposition": {
    "多方向": {"sub_directions": [{"name": "子一", "detection_signal": "x"}]},
    "单方向": {"canonical": "单方向"},
}}
ROWS = [
    {"note_id": "n1", "raw_extra": {"_direction_raw": "多方向"}},
    {"note_id": "n2", "raw_extra": {"_direction_raw": "单方向"}},         # 单方向配置 → 没子方向可判
    {"note_id": "n3", "raw_extra": {"_direction_raw": "没登记的方向"}},   # mapping 里没有 → 同样判不出
    {"note_id": "n4", "raw_extra": {"_direction_raw": ["多方向"]}},       # 飞书多选 list 形态, _direction_key 归一化
]
CANDIDATES = ["n1", "n4"]


def main() -> int:
    fails: list[str] = []
    import annotate_essence_pass as E
    import count_unannotated_essence as K

    # §1
    sb = _SB(ROWS); got_rows = E.fetch_unannotated_notes(sb, "P", True, only_missing_subtype=True)
    got = [x for x in sb.log if x[0] != "eq"]
    if got != MISSING:
        fails.append(f"§1 only_missing_subtype 的过滤应为 {MISSING}, 实际 {got}")
    if [n["note_id"] for n in got_rows] != [r["note_id"] for r in ROWS]:
        fails.append(f"§1 不给 mapping 时只做库判据、不筛方向 (老行为), 实际 {[n['note_id'] for n in got_rows]}")
    sb = _SB(ROWS); got_rows = E.fetch_unannotated_notes(sb, "P", True, only_missing_subtype=True, mapping=MAPPING)
    if [n["note_id"] for n in got_rows] != CANDIDATES or [x for x in sb.log if x[0] != "eq"] != MISSING:
        fails.append(f"§1 给了 mapping 要再筛掉没定义 sub_directions 的方向: 应 {CANDIDATES}, 实际 "
                     f"{[n['note_id'] for n in got_rows]} (库判据 {[x for x in sb.log if x[0] != 'eq']})")
    sb = _SB(ROWS); got_rows = E.fetch_unannotated_notes(sb, "P", False, mapping=MAPPING)
    if [x for x in sb.log if x[0] != "eq"] != [("is", "essence_annotated_at")] or len(got_rows) != len(ROWS):
        fails.append(f"§1 默认路径应只过滤 essence_annotated_at is null、且不按方向筛, 实际 {sb.log} / {len(got_rows)} 篇")
    sb = _SB(ROWS); got_rows = E.fetch_unannotated_notes(sb, "P", True, mapping=MAPPING)
    if [x for x in sb.log if x[0] != "eq"] or len(got_rows) != len(ROWS):
        fails.append(f"§1 --reannotate 不该加 essence 过滤、也不按方向筛, 实际 {sb.log} / {len(got_rows)} 篇")
    sb = _SB(ROWS)
    if [n["note_id"] for n in E.subtype_backfill_candidates(sb, "P", MAPPING)] != CANDIDATES:
        fails.append("§1 subtype_backfill_candidates 必须 = only_missing_subtype + mapping 那条路")

    # §2
    sb = _SB(ROWS); K.get_supabase_client = lambda: sb; K.load_mapping = lambda _p: MAPPING
    n = K.count_remaining("P", only_missing_subtype=True)
    if n != len(CANDIDATES) or [x for x in sb.log if x[0] != "eq"] != MISSING:
        fails.append(f"§2 count 要和抽取数出同一批 (含方向筛): 应 {len(CANDIDATES)}, 实际 n={n} log={sb.log}")
    sb = _SB(ROWS); K.get_supabase_client = lambda: sb
    n = K.count_remaining("P")
    if n != 7 or [x for x in sb.log if x[0] != "eq"] != [("is", "essence_annotated_at")]:
        fails.append(f"§2 默认 count 判据变了 (应走 count=exact 的 7): n={n} {sb.log}")

    # §3
    try:
        import worker.app as w
        from fastapi.testclient import TestClient
    except ImportError as exc:
        print(f"  ⚠️ §3 跳过 (import 失败: {exc}); CI 的 python job 装了 worker 依赖, 那里会跑")
        w = None
    if w is not None:
        seen: list[list[str]] = []
        w._run = lambda script, args: seen.append(list(args)) or {"ok": True, "returncode": 0, "stdout_tail": "", "stderr_tail": ""}
        w._check_auth = lambda *_a, **_k: None
        c = TestClient(w.app)
        c.post("/annotate-essence", json={"project": "P", "limit": 3, "only_missing_subtype": True})
        if "--only-missing-subtype" not in seen[-1]:
            fails.append(f"§3 worker 没把 only_missing_subtype 映成 --only-missing-subtype: {seen[-1]}")
        c.post("/annotate-essence", json={"project": "P", "limit": 3})
        if "--only-missing-subtype" in seen[-1]:
            fails.append("§3 不传 only_missing_subtype 不该带 flag")

    # §4
    import yaml
    wf = yaml.safe_load((HERE.parent / ".github" / "workflows" / "backfill-essence.yml").read_text(encoding="utf-8"))
    inputs = (wf.get("on") or wf.get(True) or {}).get("workflow_dispatch", {}).get("inputs", {})
    mode = inputs.get("mode") or {}
    if sorted(mode.get("options") or []) != ["missing_subtype", "pending"] or mode.get("default") != "pending":
        fails.append(f"§4 backfill-essence.yml 的 mode 输入形状不对: {mode}")
    runs = "\n".join(st.get("run") or "" for st in wf["jobs"]["backfill"]["steps"])
    for needle in ('"only_missing_subtype":true', "count_unannotated_essence.py \"$PROJECT\" $COUNT_FLAG", '"missing_subtype" ]; then COUNT_FLAG="--only-missing-subtype"'):
        if needle not in runs:
            fails.append(f"§4 workflow 里缺: {needle}")

    for f in fails:
        print("  ❌", f)
    if fails:
        print(f"❌ essence subtype backfill: {len(fails)} 条不过")
        return 1
    print("✅ essence subtype backfill: §1 fetch 判据 · §2 count 同判据 · §3 worker 映射 · §4 workflow 接线 全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
