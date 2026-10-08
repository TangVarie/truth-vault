#!/usr/bin/env python3
"""通道 1 (TV → 三生六部) 的 push 与回收必须用同一份判据, 回收要认 tier 降档 (D-068 / D-087)。

从 ci.yml 抽出来的 (2026-10-08, D-075 的规矩: 守卫逻辑写进 scripts/, ci.yml 只留一行调用)。
原 D-068 那块 (八条边界行) 逐字保留在 §1; §2 起是 D-087 加的。

断行为不断源码 (D-051): 假 PostgREST 链 + 打桩 fetch_all_pages, 真的走
fetch_pending_baokuan / retract_stale_synthetic_from_ssll / existing_ssll_sample_id,
dry_run 与真写两种模式都跑, 真写模式核对假客户端收到的 delete / update。

反证 (改坏之后必须变红, 每条在 D-087 里记了实跑结果):
  ① ssll_eligibility_reason 去掉 tier 那一行     → §2 的 趴 / 风控 样本留在 ssll, 红
  ② B 路把「TV 里找不到」也当不合格撤           → §2 n_missing 被删, 红
  ③ 去掉 done 去重                               → §2 两路都命中的那篇被数两次, 红
  ④ B 路 .in_() 不分批                            → §4 单次 in_ 超 200, 红
  ⑤ 回收按 publish_time 撤                        → §2 的 n_old (老但仍是爆) 被撤, 红

跑法: cd scripts && python check_ssll_retract.py
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import sync_feishu_notes_to_truth_vault as engine
import sync_truth_vault_baokuan_to_sanshengliubu as s

assert s._CM_ROUTE_TICKET == engine._CM_ROUTE_TICKET, "通道 1 与引擎的 route 字面量分叉了"

NOW = datetime.now(timezone.utc).replace(tzinfo=None)
RECENT = NOW.isoformat(timespec="seconds")
OLD = (NOW - timedelta(days=800)).isoformat(timespec="seconds")


# ── 假 PostgREST: 记下 table / filters / 写操作, 行为由 FakeSB 决定 ────────────────────────
class FakeQ:
    def __init__(self, sb, schema):
        self.sb, self.schema_, self.table_, self.filters = sb, schema, None, []
        self.op, self.payload = "select", None

    def table(self, name):
        self.table_ = name
        return self

    def select(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def range(self, *a, **k):
        return self

    def filter(self, col, op, val):
        self.filters.append((col, op, val))
        return self

    def in_(self, col, vals):
        self.filters.append((col, "in", list(vals)))
        return self

    def eq(self, col, val):
        self.filters.append((col, "eq", val))
        return self

    def neq(self, col, val):
        self.filters.append((col, "neq", val))
        return self

    def gte(self, col, val):
        self.filters.append((col, "gte", val))
        return self

    def is_(self, col, val):
        self.filters.append((col, "is", val))
        return self

    def delete(self):
        self.op = "delete"
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def execute(self):
        return SimpleNamespace(data=self.sb.execute(self))


class FakeSB:
    """notes: dict note_id → row; samples: list of {id, source_truth_vault_note_id, _legacy_key?}。"""

    def __init__(self, notes, samples):
        self.notes = {r["note_id"]: dict(r) for r in notes}
        self.samples = [dict(x) for x in samples]
        self.deleted: list[str] = []
        self.updated: dict[str, dict] = {}
        self.in_sizes: list[int] = []

    def schema(self, name):
        return FakeQ(self, name)

    # 行过滤 —— 只实现本脚本涉及的几种算子, 多了就是守卫自己没覆盖到的路径, 直接炸出来
    def rows_for(self, q: FakeQ) -> list[dict]:
        if q.table_ == "notes":
            rows = list(self.notes.values())
        elif q.table_ == "reference_samples":
            rows = list(self.samples)
        else:
            raise AssertionError(f"没想到会查 {q.schema_}.{q.table_}")
        for col, op, val in q.filters:
            if op == "in":
                self.in_sizes.append(len(val))
                rows = [r for r in rows if r.get(col) in val]
            elif op == "eq":
                rows = [r for r in rows if r.get(col) == val]
            elif op == "neq":           # SQL <>: NULL 也不通过 (fetch_pending_baokuan 的 .neq)
                rows = [r for r in rows if r.get(col) is not None and r.get(col) != val]
            elif op == "gte":
                rows = [r for r in rows if r.get(col) is not None and r.get(col) >= val]
            elif op == "is" and val is None:
                rows = [r for r in rows if r.get(col) is None]
            elif op == "not.is" and val == "null":
                rows = [r for r in rows if r.get(col) is not None]
            else:
                raise AssertionError(f"没实现的算子 {col} {op} {val!r}")
        return rows

    def execute(self, q: FakeQ):
        if q.op == "select":
            if q.table_ == "reference_samples":
                # existing_ssll_sample_id 的双键: 顶层列, 或 ai_analysis->>_truth_vault_note_id (legacy)
                out = []
                for col, op, val in q.filters:
                    if op != "eq":
                        continue
                    key = "_legacy_key" if col.startswith("ai_analysis") else col
                    out = [{"id": x["id"]} for x in self.samples if x.get(key) == val]
                return out
            return self.rows_for(q)
        if q.op == "delete":
            (col, op, sid), = q.filters
            assert q.table_ == "reference_samples" and col == "id" and op == "eq", q.filters
            assert any(x["id"] == sid for x in self.samples), f"删了一个 ssll 里不存在的 id: {sid}"
            self.samples = [x for x in self.samples if x["id"] != sid]
            self.deleted.append(sid)
            return []
        if q.op == "update":
            (col, op, nid), = q.filters
            assert q.table_ == "notes" and col == "note_id" and op == "eq", q.filters
            self.updated[nid] = dict(q.payload)
            self.notes[nid].update(q.payload)
            return []
        raise AssertionError(q.op)


def install(sb: FakeSB):
    s.fetch_all_pages = lambda q, page_size=1000, order_by=None: [dict(r) for r in sb.rows_for(q)]


def note(note_id, tier, flags=None, *, project_id="P", tier_source="状态字段", publish_time=RECENT, synced=None):
    return dict(note_id=note_id, project_id=project_id, platform="xiaohongshu", tier=tier, tier_source=tier_source,
                publish_time=publish_time, synced_to_ssll_at=synced,
                synced_ssll_reference_sample_id=(f"sid-{note_id}" if synced else None),
                data_quality_flags=flags)


# ══ §1 · D-068 原八条边界行, 逐字保留 ═══════════════════════════════════════════════════════
rows = [
    note("clean",      "爆",   None),
    note("emptyflags", "爆",   {"comment_maintained": False}),
    note("boost_bao",  "爆",   {"comment_maintained_routes": ["起量后干预"]}),
    note("ticket_bao", "爆",   {"comment_maintained": True, "comment_maintained_routes": ["铺评工单"]}, synced=RECENT),
    note("both_dabao", "大爆", {"comment_maintained_routes": ["起量后干预", "铺评工单"]}, synced=RECENT),
    note("synth_bao",  "爆",   {"synthetic": True}, synced=RECENT),
    note("ticket_ref", "参考", {"comment_maintained_routes": ["铺评工单"]}),
    note("synth_ref",  "参考", {"synthetic": True}),
]
sb = FakeSB(rows, samples=[])
install(sb)
got = sorted(r["note_id"] for r in s.fetch_pending_baokuan(sb))
want = sorted(["clean", "emptyflags", "boost_bao", "ticket_ref", "synth_ref"])
assert got == want, f"push 侧判据不对: 期望 {want} 实得 {got}"
# 回收候选 = push 侧挡的那三条 (标了 synced, ssll 里没行 → A 路靠标记认出来)
n = s.retract_stale_synthetic_from_ssll(sb, dry_run=True)
assert n == 3, f"回收候选应为 ticket_bao / both_dabao / synth_bao 三条, 实得 {n}"
print("✓ D-068: 通道 1 push 挡 铺评工单/synthetic 的 爆/大爆, 参考与起量后干预放行; 回收对称 (3 条)")

# ══ §2 · D-087: ssll 里的样本, 笔记降档 / 退回未确认就撤; 合格的、找不到的、变老的不动 ══════════
notes2 = [
    note("n_demoted_pa", "趴",   None,                       synced=RECENT),   # 08-18 式: 推过, 改回 趴
    note("n_demoted_fk", "风控", None,                       synced=RECENT),
    note("n_ok",         "爆",   None,                       synced=RECENT),   # 合格, 留
    note("n_numeric",    "爆",   None, tier_source="数值推断", synced=RECENT),  # 状态列被清, 退回推断 → 撤
    note("n_nullsrc",    "爆",   None, tier_source=None,     synced=RECENT),   # push 侧 .neq 也排 NULL → 对称撤
    note("n_ticket",     "爆",   {"comment_maintained_routes": ["铺评工单"]}, synced=RECENT),  # 两路都命中, 只撤一次
    note("n_ref_synth",  "参考", {"synthetic": True},        synced=RECENT),   # 参考放行 synthetic, 留
    note("n_old",        "爆",   None, publish_time=OLD,     synced=RECENT),   # 推进去之后变老 ≠ 推错, 留
    note("n_orphan",     "趴",   None,                       synced=None),     # ssll 有行、TV 标记 NULL → 也撤
]
samples2 = [{"id": f"s-{nid}", "source_truth_vault_note_id": nid}
            for nid in ("n_demoted_pa", "n_demoted_fk", "n_ok", "n_numeric", "n_nullsrc",
                        "n_ticket", "n_ref_synth", "n_old", "n_orphan", "n_missing")]
samples2.append({"id": "s-native", "source_truth_vault_note_id": None})   # ssll 原生样本, 永远不碰

sb2 = FakeSB(notes2, samples2)
install(sb2)
n_dry = s.retract_stale_synthetic_from_ssll(sb2, dry_run=True)
assert n_dry == 6, f"dry-run 应撤 6 篇 (趴 / 风控 / 数值推断 / NULL 来源 / 铺评工单 / orphan), 实得 {n_dry}"
assert sb2.deleted == [] and sb2.updated == {}, "dry-run 不许写"

n_real = s.retract_stale_synthetic_from_ssll(sb2, dry_run=False)
assert n_real == 6, f"真跑应撤 6 篇, 实得 {n_real}"
want_del = sorted(f"s-{x}" for x in ("n_demoted_pa", "n_demoted_fk", "n_numeric", "n_nullsrc", "n_ticket", "n_orphan"))
assert sorted(sb2.deleted) == want_del, f"删错了行: 期望 {want_del} 实得 {sorted(sb2.deleted)}"
assert sorted(sb2.updated) == sorted(x[2:] for x in want_del), f"清标记的笔记不对: {sorted(sb2.updated)}"
assert all(v == {"synced_to_ssll_at": None, "synced_ssll_reference_sample_id": None} for v in sb2.updated.values()), \
    "两列标记要一起清"
left = sorted(x["id"] for x in sb2.samples)
assert left == ["s-n_missing", "s-n_ok", "s-n_old", "s-n_ref_synth", "s-native"], f"留下的不对: {left}"
assert "n_missing" not in sb2.updated, "TV 里找不到的笔记不该被动 (找不到 ≠ 不合格)"
assert s.retract_stale_synthetic_from_ssll(sb2, dry_run=False) == 0, "撤完再跑一遍必须是 0 (幂等)"
print("✓ D-087: 降档 / 退回未确认 / 铺评工单 / orphan 撤 6 篇, 合格·参考·变老·找不到·原生样本不动, 幂等")

# ══ §3 · --project 只动这个项目的, 别的项目既不撤也不算「找不到」 ════════════════════════════
notes3 = [note("a_pa", "趴", None, project_id="A", synced=RECENT),
          note("b_pa", "趴", None, project_id="B", synced=RECENT)]
sb3 = FakeSB(notes3, [{"id": "s-a", "source_truth_vault_note_id": "a_pa"},
                       {"id": "s-b", "source_truth_vault_note_id": "b_pa"}])
install(sb3)
assert s.retract_stale_synthetic_from_ssll(sb3, project_filter="A", dry_run=False) == 1
assert sb3.deleted == ["s-a"] and list(sb3.updated) == ["a_pa"], (sb3.deleted, sb3.updated)
print("✓ D-087: --project 只撤该项目, 别的项目的样本原地不动")

# ══ §4 · B 路回 TV 查笔记必须分批 (D-080: .in_() 走 URL, ≤200 一批), 且一篇不漏 ════════════════
big = [note(f"big_{i:04d}", "趴", None, synced=RECENT) for i in range(250)]
sb4 = FakeSB(big, [{"id": f"s-big_{i:04d}", "source_truth_vault_note_id": f"big_{i:04d}"} for i in range(250)])
install(sb4)
assert s.retract_stale_synthetic_from_ssll(sb4, dry_run=True) == 250
note_batches = [n for n in sb4.in_sizes if n > 2]   # 排掉 A 路 .in_("tier", [爆, 大爆]) 那两个值
assert note_batches and max(note_batches) <= 200, f"一次 in_() 超过 200 个 note_id: {max(note_batches)} (D-080)"
assert sum(note_batches) == 250, f"分批漏了行: {sum(note_batches)}"
print(f"✓ D-087: 250 篇分 {len(note_batches)} 批回查, 单批 ≤ {max(note_batches)}, 一篇不漏")

# ══ §5 · 判据对称: 对任意一行, 「push 会推」⇔「回收不撤」(两边同一个函数, 这里钉住它们没分叉) ════
mixed = rows + [note("x_pa", "趴", None), note("x_num", "爆", None, tier_source="数值推断"),
                note("x_null", "爆", None, tier_source=None), note("x_eval", "评估中", None)]
sb5 = FakeSB(mixed, [])
install(sb5)
pushed = {r["note_id"] for r in s.fetch_pending_baokuan(sb5)}
for r in mixed:
    eligible = s.ssll_eligibility_reason(r) is None
    assert (r["note_id"] in pushed) == eligible, f"push 与资格判据分叉: {r['note_id']} pushed={r['note_id'] in pushed} eligible={eligible}"
print("✓ D-087: push 侧与回收侧是同一份判据 (12 行逐行对称)")
print("\ncheck_ssll_retract: all checks passed")
