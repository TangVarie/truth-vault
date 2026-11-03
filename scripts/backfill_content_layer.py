#!/usr/bin/env python3
"""
backfill_content_layer.py
═══════════════════════════════════════════════════════════════════════════

内容层 notes.content_layer (D-140; schemas/notes_v1_24_external_masks_content_layer.sql) 的补填: 只往【空】里填, 只填算得出的。

为什么要有它: feishu → TV 那一步每晚把 daily 项目的每一行整行重写一遍 (transform_row 每行都带 content_layer), 所以
owner 跑完 v1_24 的下一晚, daily 项目自己就填满了。但夜跑跳过 sync_interval=on_demand 的项目 (HXZ / NRT / NUC / TGV / TXQ,
D-047), 这些老项目的行不会再被重写 —— 内容层只能从库里已有的东西算: raw_extra._direction_raw (sync 原样留着的方向格)
和 notes.intent。判定规则和 sync 是同一个函数 (_common.derive_layer), 口径只有一份。

  · 默认 (夜跑): 只看夜跑 feishu 同步跳过的项目 (同 _common.skip_on_demand_on_cron, scheduled=True)。daily 项目不碰 ——
    它们由 sync 写, 两边都写会在「飞书里清空了发布笔记格、库里 intent 还是旧值」这种边角上来回翻;
  · --all: 全部项目 (手动一次性, 比如 sync 那晚某个 daily 项目没跑成);
  · --project P: 只看一个项目;
  · 写的时候再带一次 content_layer IS NULL: 和 sync 同时跑也不会盖掉 sync 刚写的值。可以重跑, 第二遍 0 行。

库里还没有这一列 (v1_24 没跑) → 什么都不写, rc=2 (每晚一行 notice, 不拖红)。
末行哨兵 CONTENT_LAYER_BACKFILL_CHECK_DONE rc=<0 填完 / 1 有写失败的 / 2 判不了>; daily-sync 靠有没有这一行判崩溃 (docs/29)。

用法:
    python backfill_content_layer.py [--all | --project P] [--dry-run]
    python backfill_content_layer.py --selftest        # CI: 不连库
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    CONTENT_LAYERS,
    derive_layer,
    fetch_all_pages,
    load_mapping,
    notes_content_layer_supported,
    skip_on_demand_on_cron,
)

MAPPINGS = Path(__file__).resolve().parent.parent / "mappings"
UPDATE_CHUNK = 150          # .in_ 走 URL (同 annotate_essence_pass.STALE_IDS_CHUNK)
SENTINEL = "CONTENT_LAYER_BACKFILL_CHECK_DONE"


def all_projects() -> list[str]:
    return sorted(p.stem for p in MAPPINGS.glob("*.yaml") if p.stem != "_template")


def nightly_projects(projects: list[str]) -> list[str]:
    """夜跑 feishu 同步跳过的项目 (同一个判据)。mapping 读不出来的不碰 (那一步也会红)。"""
    out = []
    for p in projects:
        try:
            m = load_mapping(p)
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠️  {p}: mapping 读不出来 ({exc}), 跳过")
            continue
        if skip_on_demand_on_cron((m.get("sync_config") or {}).get("sync_interval"), True):
            out.append(p)
    return out


def plan(rows: list[dict], mapping: dict) -> dict[str, list[str]]:
    """纯函数: 空着内容层的行 → {层: [note_id]}。算不出的不在里面。"""
    out: dict[str, list[str]] = {}
    for r in rows:
        if r.get("content_layer") is not None:
            continue
        lay = derive_layer(r.get("dir"), mapping, r.get("intent"))
        if lay in CONTENT_LAYERS:
            out.setdefault(lay, []).append(str(r["note_id"]))
    return out


def fetch_rows(sb, project_id: str) -> list[dict]:
    return fetch_all_pages(
        sb.schema("truth_vault").table("notes")
        .select("note_id, intent, content_layer, dir:raw_extra->_direction_raw")
        .eq("project_id", project_id).is_("content_layer", "null"),
        order_by="note_id")


def write(sb, todo: dict[str, list[str]], *, dry_run: bool) -> tuple[int, int]:
    """按层分批写, 每批再带一次 content_layer IS NULL。返回 (写了几篇, 失败几篇)。"""
    done = failed = 0
    for lay, ids in todo.items():
        for i in range(0, len(ids), UPDATE_CHUNK):
            chunk = ids[i:i + UPDATE_CHUNK]
            if dry_run:
                done += len(chunk)
                continue
            try:
                (sb.schema("truth_vault").table("notes").update({"content_layer": lay})
                 .in_("note_id", chunk).is_("content_layer", "null").execute())
                done += len(chunk)
            except Exception as exc:  # noqa: BLE001 —— 一批写不进不拖垮别的批
                print(f"  ⚠️  写 {lay} 层 {len(chunk)} 篇失败: {type(exc).__name__}: {str(exc)[:160]}")
                failed += len(chunk)
    return done, failed


def run(sb, projects: list[str], *, dry_run: bool) -> int:
    try:
        if not notes_content_layer_supported(sb):
            print("  notes.content_layer 还没建 (owner 在 SQL editor 跑 v1_24 之前都是这样), 这一轮不填")
            return 2
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠️  探 notes.content_layer 失败 ({type(exc).__name__}: {str(exc)[:160]}), 这一轮不填")
        return 2
    rc = 0
    total: Counter = Counter()
    for p in projects:
        try:
            mapping = load_mapping(p)
            rows = fetch_rows(sb, p)
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠️  {p}: 读不出来 ({type(exc).__name__}: {str(exc)[:160]})")
            rc = 1
            continue
        todo = plan(rows, mapping)
        done, failed = write(sb, todo, dry_run=dry_run)
        total.update({k: len(v) for k, v in todo.items()})
        left = len(rows) - sum(len(v) for v in todo.values())
        print(f"  {p}: 空着 {len(rows)} 篇 → " + (" · ".join(f"{k} {len(v)}" for k, v in sorted(todo.items())) or "一篇都算不出")
              + f"{'(dry-run 不写)' if dry_run else ''}; 算不出、留空 {left} 篇" + (f"; 写失败 {failed} 篇" if failed else ""))
        if failed:
            rc = 1
    print("合计: " + (" · ".join(f"{k} {total[k]}" for k in CONTENT_LAYERS if total[k]) or "没有要填的"))
    return rc


# ── selftest ─────────────────────────────────────────────────────────────
class _Q:
    def __init__(self, db, table):
        self.db, self.table, self.f, self.upd, self.rng = db, table, [], None, None

    def select(self, *a, **k):
        return self

    def eq(self, c, v):
        self.f.append(lambda r: r.get(c) == v)
        return self

    def is_(self, c, v):
        self.f.append(lambda r: r.get(c) is None)
        return self

    def in_(self, c, vs):
        vs = set(vs)
        self.f.append(lambda r: r.get(c) in vs)
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        self.rng = (0, n - 1)
        return self

    def range(self, a, b):
        self.rng = (a, b)
        return self

    def update(self, d):
        self.upd = d
        return self

    def execute(self):
        if self.db.missing_column:
            raise RuntimeError("{'code': '42703', 'message': 'column notes.content_layer does not exist'}")
        rows = [r for r in self.db.rows if all(f(r) for f in self.f)]
        if self.upd is not None:
            for r in rows:
                r.update(self.upd)
            self.db.updates.append((dict(self.upd), len(rows)))
            return type("R", (), {"data": rows})()
        if self.rng:
            rows = rows[self.rng[0]:self.rng[1] + 1]
        return type("R", (), {"data": [dict(r) for r in rows]})()


class _DB:
    def __init__(self, rows, missing_column=False):
        self.rows, self.updates, self.missing_column = rows, [], missing_column

    def schema(self, s):
        return self

    def table(self, t):
        return _Q(self, t)


def selftest() -> int:
    nrt = load_mapping("NRT_phase2")
    rows = [
        {"note_id": "a", "project_id": "NRT_phase2", "intent": "traffic", "dir": None, "content_layer": None},
        {"note_id": "b", "project_id": "NRT_phase2", "intent": "conversion", "dir": ["咀嚼胶"], "content_layer": None},
        {"note_id": "c", "project_id": "NRT_phase2", "intent": None, "dir": ["为爱助戒"], "content_layer": None},
        {"note_id": "d", "project_id": "NRT_phase2", "intent": "traffic", "dir": None, "content_layer": "Q"},  # 有值不动
        {"note_id": "e", "project_id": "NRT_phase2", "intent": None, "dir": '["流量贴", "产品贴"]', "content_layer": None},
        {"note_id": "f", "project_id": "OTHER", "intent": "traffic", "dir": None, "content_layer": None},
    ]
    assert plan(rows[:5], nrt) == {"T": ["a"], "P": ["b"]}, plan(rows[:5], nrt)
    db = _DB([dict(r) for r in rows])
    assert run(db, ["NRT_phase2"], dry_run=False) == 0
    got = {r["note_id"]: r["content_layer"] for r in db.rows}
    assert got == {"a": "T", "b": "P", "c": None, "d": "Q", "e": None, "f": None}, got
    assert all(n <= UPDATE_CHUNK for _, n in db.updates)
    n_upd = len(db.updates)
    assert run(db, ["NRT_phase2"], dry_run=False) == 0 and len(db.updates) == n_upd, "第二遍 0 行要写"
    dry = _DB([dict(r) for r in rows])
    assert run(dry, ["NRT_phase2"], dry_run=True) == 0 and not dry.updates, "dry-run 不写"
    assert run(_DB([dict(r) for r in rows], missing_column=True), ["NRT_phase2"], dry_run=False) == 2, \
        "v1_24 没跑: 什么都不写, rc=2"
    night = nightly_projects(all_projects())
    assert "NRT_phase2" in night and "XIWU_phase2" not in night and "SPX_phase1" not in night, night
    print(f"  ✓ selftest: 只填空的、算得出的; 第二遍 0 行; dry-run 不写; 没迁移 rc=2; 夜跑只看 on_demand 项目 ({len(night)} 个)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="内容层补填 (D-140): 只往空里填, 只填算得出的")
    ap.add_argument("--project")
    ap.add_argument("--all", action="store_true", help="全部项目 (默认只看夜跑 feishu 同步跳过的 on_demand 项目)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    rc: Optional[int] = None
    try:
        projects = [args.project] if args.project else (all_projects() if args.all else nightly_projects(all_projects()))
        print(f"内容层补填 (D-140) · {len(projects)} 个项目: {', '.join(projects) or '(无)'}")
        from _common import get_supabase_client
        rc = run(get_supabase_client(), projects, dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001 —— advisory: 不让夜跑崩, 但哨兵照打, rc=1
        print(f"  ⚠️  补填出错: {type(exc).__name__}: {str(exc)[:200]}")
        rc = 1
    print(f"{SENTINEL} rc={rc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
