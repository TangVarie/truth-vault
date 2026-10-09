#!/usr/bin/env python3
"""CI 守卫: 「已标 essence 但 direction_subtype 空」那条补标路 (2026-10-08 审计 C-03)。

NUC 10-08 实查 206 篇 essence_annotated_at 非空、direction_subtype 空、raw_extra 有 _direction_raw: 以前只有
--reannotate 全重做能补 (不收敛: 每轮 --limit 都从 note_id 最小的开始), 从没跑过。

  §1 annotate_essence_pass.fetch_unannotated_notes(only_missing_subtype=True) 的过滤 = 三条判据; 默认路径不变; --reannotate 不加 essence 过滤
  §2 count_unannotated_essence.count_remaining(only_missing_subtype=True) 用同一判据 (两边不一致就不收敛)
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
    def __init__(self, log):
        self.log, self._neg = log, False

    def select(self, *a, **k): return self
    def eq(self, c, v): self.log.append(("eq", c, v)); return self
    def order(self, *a, **k): return self
    def range(self, *a, **k): return self
    def limit(self, *a, **k): return self

    @property
    def not_(self):
        self._neg = True
        return self

    def is_(self, c, v):
        self.log.append(("not.is" if self._neg else "is", c))
        self._neg = False
        return self

    def execute(self):
        return type("R", (), {"data": [], "count": 7})()


class _SB:
    def __init__(self):
        self.log = []

    def schema(self, _s): return self
    def table(self, _n): return _Q(self.log)


MISSING = [("not.is", "essence_annotated_at"), ("is", "direction_subtype"), ("not.is", "raw_extra->_direction_raw")]


def main() -> int:
    fails: list[str] = []
    import annotate_essence_pass as E
    import count_unannotated_essence as K

    # §1
    sb = _SB(); E.fetch_unannotated_notes(sb, "P", True, only_missing_subtype=True)
    got = [x for x in sb.log if x[0] != "eq"]
    if got != MISSING:
        fails.append(f"§1 only_missing_subtype 的过滤应为 {MISSING}, 实际 {got}")
    sb = _SB(); E.fetch_unannotated_notes(sb, "P", False)
    if [x for x in sb.log if x[0] != "eq"] != [("is", "essence_annotated_at")]:
        fails.append(f"§1 默认路径应只过滤 essence_annotated_at is null, 实际 {sb.log}")
    sb = _SB(); E.fetch_unannotated_notes(sb, "P", True)
    if [x for x in sb.log if x[0] != "eq"]:
        fails.append(f"§1 --reannotate 不该加 essence 过滤, 实际 {sb.log}")

    # §2
    sb = _SB(); K.get_supabase_client = lambda: sb
    n = K.count_remaining("P", only_missing_subtype=True)
    if n != 7 or [x for x in sb.log if x[0] != "eq"] != MISSING:
        fails.append(f"§2 count 的判据要与 fetch 一致: n={n} log={sb.log}")
    sb = _SB(); K.get_supabase_client = lambda: sb
    K.count_remaining("P")
    if [x for x in sb.log if x[0] != "eq"] != [("is", "essence_annotated_at")]:
        fails.append(f"§2 默认 count 判据变了: {sb.log}")

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
