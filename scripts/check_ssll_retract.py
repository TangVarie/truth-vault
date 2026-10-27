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
  ⑥ _retract_one 改回「先删样本、后清标记」       → §2 第一条 delete 就炸 (标记还没清), 红

§7 是 I-06 的大批首推闸 (D-119 第 14 条, D-130): 真的驱动 main(), 假客户端记下每一次 insert / update / delete,
另把 daily-sync.yml 里通道 1 那一步和收尾的失败聚合垫假 python 真跑一遍。反证见 D-130 (每条改坏都红)。

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

    def insert(self, payload):
        self.op, self.payload = "insert", payload
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
        self.inserted: list[str] = []    # §7: 新插进 reference_samples 的 note_id
        self.lookups = 0                 # §7: existing_ssll_sample_id 式的按键查样本次数

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
                    self.lookups += 1
                    key = "_legacy_key" if col.startswith("ai_analysis") else col
                    out = [{"id": x["id"]} for x in self.samples if x.get(key) == val]
                return out
            if q.table_ == "comments":      # §7 推送时取证据评论 (fetch_top_comments); 夹具里没有评论
                return []
            return self.rows_for(q)
        if q.op == "insert":
            assert q.schema_ == "public" and q.table_ == "reference_samples", (q.schema_, q.table_)
            nid = q.payload["source_truth_vault_note_id"]
            self.samples.append({"id": q.payload["id"], "source_truth_vault_note_id": nid})
            self.inserted.append(nid)
            return []
        if q.op == "delete":
            (col, op, sid), = q.filters
            assert q.table_ == "reference_samples" and col == "id" and op == "eq", q.filters
            hit = [x for x in self.samples if x["id"] == sid]
            assert hit, f"删了一个 ssll 里不存在的 id: {sid}"
            # 写序 (D-087, codex review on #165): 删样本之前这篇的 TV 标记必须已经清掉 —— 两步之间断了,
            # 留下「标记空、样本在」下一夜 B 路认得出来; 反过来「标记在、样本没了」两路都够不着。
            owner = hit[0].get("source_truth_vault_note_id") or hit[0].get("_legacy_key")
            assert owner in self.updated, f"先删样本后清标记: 样本 {sid} 的笔记 {owner} 标记还没清"
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


def install(sb: FakeSB, vanished: set[str] = frozenset()):
    s.fetch_all_pages = lambda q, page_size=1000, order_by=None: [dict(r) for r in sb.rows_for(q)]
    # 飞书已删篇 (v_notes_vanished, D-103) 的查询在 _common 里, 这里按名单桩掉; 真视图由 check_vanished_notes.py 守
    s.fetch_vanished_note_ids = lambda _sb, project_id=None: set(vanished)


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
# §1b 飞书已删篇 (v_notes_vanished, 审计 B-21 / D-103): 资格全够的 clean 一旦在名单里就不推; 回收侧不认它 (只认资格, D-087)
install(sb, vanished={"clean"})
got_v = sorted(r["note_id"] for r in s.fetch_pending_baokuan(sb))
assert got_v == sorted(x for x in want if x != "clean"), f"飞书已删的 clean 不该推: {got_v}"
install(sb)
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

# ══ §6 · 写序「先清标记、再删样本」, 断在中间留下的「标记空、样本在」两种走向都能自愈 ═══════════════
#   (a) 笔记仍不合格 → 下一夜 B 路从 ssll 侧取到、撤掉 (就是 §2 n_orphan 的形态, 这里单独钉一次)
#   (b) 笔记又合格了 → push 侧 fetch_pending_baokuan 取到它, existing_ssll_sample_id 认出旧样本 → 只补标记不重插
notes6 = [note("h_bad", "趴", None, synced=None), note("h_good", "爆", None, synced=None)]
sb6 = FakeSB(notes6, [{"id": "s-h_bad", "source_truth_vault_note_id": "h_bad"},
                       {"id": "s-h_good", "source_truth_vault_note_id": "h_good"}])
install(sb6)
assert s.retract_stale_synthetic_from_ssll(sb6, dry_run=False) == 1 and sb6.deleted == ["s-h_bad"], \
    f"标记空、样本在、仍不合格的那篇要被撤 (且只撤它): {sb6.deleted}"
assert [r["note_id"] for r in s.fetch_pending_baokuan(sb6)] == ["h_good"], "标记空、又合格的那篇要回到 push 候选"
assert s.existing_ssll_sample_id(sb6, "h_good") == "s-h_good", "push 侧要认出旧样本 (只补标记, 不重插)"
print("✓ D-087: 先清标记再删样本; 断在中间的残留, 不合格的下一夜撤、合格的 push 侧认出旧样本只补标记")
# ══ §7 · 大批首推闸 (I-06, D-119 第 14 条, D-130): 一轮新插 > 30 篇 → 一篇不推、列名单、rc=1; 放行开关只放这一道 ═══
#   真的驱动 main(): 假客户端记下每一次 insert (新插的样本) / update (TV 标记) / delete (回收)。
import io
import logging
import os
import pathlib
import subprocess
import sys
import tempfile

import yaml

CAP = s.BULK_FIRST_PUSH_MAX
assert CAP == 30, f"上限是 D-119 第 14 条定的 30 (近 45 天最多一晚 13 篇的两倍多), 改了要先改决定: {CAP}"
ON_DEMAND = {"Q"}                 # 夹具里的 on_demand 项目; 其余项目按 daily
_summary = pathlib.Path(tempfile.mkdtemp()) / "step_summary.md"


def run_main(sb: FakeSB, *argv: str):
    """跑一次 main(), 返回 (rc, WARNING 以上的日志, step summary)。"""
    install(sb)
    s.get_supabase_client = lambda: sb
    s.load_mapping = lambda pid: {"sync_config": {"sync_interval": "on_demand" if pid in ON_DEMAND else "daily"}}
    _summary.write_text("", encoding="utf-8")
    os.environ["GITHUB_STEP_SUMMARY"] = str(_summary)
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setLevel(logging.WARNING)
    old_level, old_argv = s.logger.level, sys.argv
    s.logger.setLevel(logging.WARNING)          # 31 条 "Synced …" 不刷屏; 要核的都在 WARNING 以上
    s.logger.addHandler(h)
    try:
        sys.argv = ["sync_truth_vault_baokuan_to_sanshengliubu.py", *argv]
        rc = s.main()
    finally:
        s.logger.removeHandler(h)
        s.logger.setLevel(old_level)
        sys.argv = old_argv
        os.environ.pop("GITHUB_STEP_SUMMARY", None)
    return rc, buf.getvalue(), _summary.read_text(encoding="utf-8")


BODY = "夹具正文-不该出现在名单里"


def fresh(n, project_id="P"):
    """n 篇资格齐全、还没推过的爆款 (= 换号事故里那批新 note_id 的样子)。"""
    return [dict(note(f"{project_id}_rec{i:04d}", "爆", None, project_id=project_id), raw_content=BODY)
            for i in range(n)]


def wrote_nothing(sb):
    return sb.inserted == [] and sb.updated == {} and sb.deleted == []


# §7a 正常夜 (13 篇 = 近 45 天最多的一晚): 照推, 闸不逐篇查 —— 按键查样本的次数和没有这道闸时一样 (每篇 2 次: 主键 + legacy 键)
sb = FakeSB(fresh(13), [])
rc, log, summ = run_main(sb)
assert rc == 0 and len(sb.inserted) == 13 and len(sb.updated) == 13, (rc, len(sb.inserted), len(sb.updated))
assert sb.lookups == 13 * 2, f"正常夜多查了库: {sb.lookups} 次按键查样本 (没有这道闸时是 26)"
assert "大批首推" not in log and summ == "", "正常夜不该出闸的日志 / 摘要"
print("✓ §7a 正常夜 13 篇照推, 闸不多查一次库")

# §7b 恰好 30 篇: 不挡 (> 30 才挡)。再加 2 篇 orphan 让待推 32 > 30, 逼闸逐篇分 —— 边界落在「新插 30」本身上
sb = FakeSB(fresh(CAP), [])
rc, log, summ = run_main(sb)
assert rc == 0 and len(sb.inserted) == CAP, f"30 篇是上限本身, 不该挡: rc={rc} 新插 {len(sb.inserted)}"
assert sb.lookups == CAP * 2, f"待推恰好 30 篇闸也不该逐篇查 (≤ 上限就不查): {sb.lookups} 次, 应为主循环的 60"
orph2 = [note(f"P_orph{i:02d}", "爆", None) for i in range(2)]
sb = FakeSB(fresh(CAP) + orph2, [{"id": f"s-{r['note_id']}", "source_truth_vault_note_id": r["note_id"]} for r in orph2])
rc, log, summ = run_main(sb)
assert rc == 0 and len(sb.inserted) == CAP and len(sb.updated) == CAP + 2, \
    f"待推 32 = 新插 30 + orphan 2, 新插没过线, 不该挡: rc={rc} 新插 {len(sb.inserted)}"
print("✓ §7b 恰好 30 篇照推 (待推 30 / 待推 32 里新插 30 都照推)")

# §7c 31 篇: 一行不写、rc=1、名单 (只有 note_id) 进日志和 step summary
rows31 = fresh(CAP + 1)
sb = FakeSB(rows31, [])
rc, log, summ = run_main(sb)
assert rc == 1, f"超线要退出码 1 (daily-sync 那一步 outcome=failure、失败聚合点名 ssll_sync), 实得 {rc}"
assert wrote_nothing(sb), f"超线要一篇不推: 新插 {sb.inserted} / 标记 {list(sb.updated)} / 删 {sb.deleted}"
ids31 = [r["note_id"] for r in rows31]
assert "大批首推被挡" in log and all(i in log for i in ids31), "日志里要有被挡的字样和完整名单"
assert all(i in summ for i in ids31) and "allow_bulk_ssll_push" in summ, "step summary 里要有名单和放行开关的名字"
assert BODY not in log + summ, "名单只给 note_id, 不带正文"
# §7c' 31 篇新插 + 2 篇 orphan: 挡住时 orphan 的补标记也不做 (D-130 第 3 条), truth_vault.notes 一行不动
sb = FakeSB(rows31 + orph2, [{"id": f"s-{r['note_id']}", "source_truth_vault_note_id": r["note_id"]} for r in orph2])
rc, log, summ = run_main(sb)
assert rc == 1 and wrote_nothing(sb), \
    f"挡住的那一轮 orphan 也不许补标记: rc={rc} 新插 {sb.inserted} 标记 {list(sb.updated)} 删 {sb.deleted}"
print("✓ §7c 31 篇: 一行不写、rc=1、日志和 step summary 都有完整名单; 带 orphan 时 orphan 也不补标记")

# §7d 放行: --allow-bulk-push 让同一批 31 篇全推, rc=0
sb = FakeSB(rows31, [])
rc, log, summ = run_main(sb, "--allow-bulk-push")
assert rc == 0 and sorted(sb.inserted) == sorted(ids31), f"放行之后要全推: rc={rc} 新插 {len(sb.inserted)}"
assert "已放行" in log, "放行也要留一行痕 (谁在哪晚放了多少)"
print("✓ §7d --allow-bulk-push 放行同一批 31 篇")

# §7e dry-run 不受影响: 不写、rc=0, 照样逐篇走一遍; 只多一行「真跑会被挡」
sb = FakeSB(rows31, [])
rc, log, summ = run_main(sb, "--dry-run")
assert rc == 0 and wrote_nothing(sb), f"dry-run 不许写、不许因为这道闸红: rc={rc}"
assert "[dry-run]" in log and "真跑会" in log and all(i in log for i in ids31), "dry-run 要把真跑会挡的名单打出来"
# 「照样逐篇走一遍」: 闸逐篇查 31×2 次 + 主循环逐篇查 31×2 次; 只有前一半 = dry-run 被闸截在循环前面了
assert sb.lookups == (CAP + 1) * 2 * 2, f"dry-run 要照样逐篇走主循环 (预演 31 篇新插): 按键查样本 {sb.lookups} 次, 应为 124"
print("✓ §7e dry-run 31 篇: 不写、rc=0、名单照打、主循环照样逐篇走")

# §7f 数的是【新插】: 25 篇新 + 10 篇 orphan (ssll 已有样本、TV 标记空 → 只补标记) = 待推 35, 新插 25 ≤ 30 → 照推
orph = [note(f"P_orph{i:02d}", "爆", None) for i in range(10)]
sb = FakeSB(fresh(25) + orph, [{"id": f"s-{r['note_id']}", "source_truth_vault_note_id": r["note_id"]} for r in orph])
rc, log, summ = run_main(sb)
assert rc == 0 and len(sb.inserted) == 25, f"orphan 只补标记、不算新插: rc={rc} 新插 {len(sb.inserted)}"
assert all(sb.updated[r["note_id"]]["synced_ssll_reference_sample_id"] == f"s-{r['note_id']}" for r in orph), "orphan 要补上旧样本 id"
print("✓ §7f 待推 35 = 新插 25 + orphan 10: 只数新插, 照推")

# §7g 资格不齐的 (铺评工单 / synthetic 的爆) 和 on_demand 项目的不算, 放行开关也不放 on_demand
junk = [note(f"P_tk{i:02d}", "爆", {"comment_maintained_routes": ["铺评工单"]}) for i in range(20)]
sb = FakeSB(fresh(28) + junk + fresh(40, project_id="Q"), [])
rc, log, summ = run_main(sb)
assert rc == 0 and len(sb.inserted) == 28 and all(i.startswith("P_rec") for i in sb.inserted), \
    f"只该推 P 的 28 篇 (铺评工单不合格、Q 是 on_demand): rc={rc} {len(sb.inserted)}"
sb = FakeSB(fresh(3) + fresh(40, project_id="Q"), [])
rc, log, summ = run_main(sb, "--allow-bulk-push")
assert rc == 0 and len(sb.inserted) == 3 and not any(i.startswith("Q_") for i in sb.inserted), \
    "--allow-bulk-push 不许顺手放行 on_demand 项目 (那是 --include-on-demand)"
print("✓ §7g 不合格的、on_demand 的不算数; 放行开关不放 on_demand")

# §7h 项目筛 / --limit 认: --project R 时只数 R 的; --limit 10 时这一轮只处理 10 篇, 不挡
sb = FakeSB(fresh(CAP + 1) + fresh(5, project_id="R"), [])
rc, log, summ = run_main(sb, "--project", "R")
assert rc == 0 and len(sb.inserted) == 5 and all(i.startswith("R_") for i in sb.inserted), (rc, sb.inserted)
sb = FakeSB(fresh(CAP + 1), [])
rc, log, summ = run_main(sb, "--limit", "10")
assert rc == 0 and len(sb.inserted) == 10, f"--limit 10 这一轮只会推 10 篇: rc={rc} {len(sb.inserted)}"
print("✓ §7h --project / --limit 之内数")

# §7i 回收不受这道闸管: 被挡的那一晚, 降档的旧样本照样撤 (闸挡往外推, 不挡往回收)
sb = FakeSB(rows31 + [note("P_old_pa", "趴", None, synced=RECENT)],
            [{"id": "s-P_old_pa", "source_truth_vault_note_id": "P_old_pa"}])
rc, log, summ = run_main(sb)
assert rc == 1 and sb.inserted == [] and sb.deleted == ["s-P_old_pa"] and list(sb.updated) == ["P_old_pa"], \
    f"挡推送的那一晚回收照跑、推送一篇不做: 删 {sb.deleted} 标记 {list(sb.updated)} 新插 {sb.inserted}"
print("✓ §7i 挡住的那一晚回收照跑")

# §7j daily-sync 接线: 通道 1 那一步垫假 python 真跑 —— 定时跑 / 手动不勾 不放行, 手动勾了才带 --allow-bulk-push;
#     脚本退出码 1 → 这一步失败 → 收尾的失败聚合点名 ssll_sync 并 exit 1 (D-073)
wf = yaml.safe_load((pathlib.Path(__file__).resolve().parent.parent / ".github/workflows/daily-sync.yml").read_text(encoding="utf-8"))
inputs = wf[True]["workflow_dispatch"]["inputs"] if True in wf else wf["on"]["workflow_dispatch"]["inputs"]
assert inputs["allow_bulk_ssll_push"]["type"] == "boolean" and inputs["allow_bulk_ssll_push"]["default"] is False, \
    "放行开关要是默认关的 boolean 输入"
steps = wf["jobs"]["sync"]["steps"]
st = [x for x in steps if x.get("id") == "ssll_sync"]
assert len(st) == 1 and "sync_truth_vault_baokuan_to_sanshengliubu.py" in st[0]["run"], "找不到通道 1 那一步 (id: ssll_sync)"
assert st[0].get("continue-on-error") is True, "通道 1 要 continue-on-error, 由收尾聚合判红 (否则后面的灯一步都不跑)"
agg = [x for x in steps if x.get("name", "").startswith("Fail job on any sync failure")]
assert len(agg) == 1, "找不到收尾的失败聚合"


def sh(script: str, subst: dict[str, str], env: dict[str, str] | None = None):
    for k, v in subst.items():
        script = script.replace("${{ " + k + " }}", v)
    assert "${{" not in script, f"还有没替换的表达式: {script[script.index('${{'):][:60]}"
    with tempfile.TemporaryDirectory() as td:
        fake = pathlib.Path(td) / "python"
        fake.write_text('#!/bin/sh\necho "$@" > "$ARGV_OUT"\nexit "${STUB_RC:-0}"\n', encoding="utf-8")
        fake.chmod(0o755)
        out = pathlib.Path(td) / "argv"
        e = dict(os.environ, PATH=f"{td}:{os.environ['PATH']}", ARGV_OUT=str(out), **(env or {}))
        # GitHub 的默认 shell 是 bash --noprofile --norc -eo pipefail
        p = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
                           capture_output=True, text=True, env=e)
        return p.returncode, (out.read_text().split() if out.exists() else None), p.stdout + p.stderr


ssll_run = st[0]["run"]
for allow, want in (("", False), ("false", False), ("true", True)):   # "" = 定时跑 (没有 inputs)
    rc_, argv_, _ = sh(ssll_run, {"github.event.inputs.dry_run": "", "github.event.inputs.allow_bulk_ssll_push": allow},
                       {"PROJECT_FILTER": ""})
    assert rc_ == 0 and argv_ is not None, f"通道 1 那一步没跑起来 (allow={allow!r}): rc={rc_}"
    assert ("--allow-bulk-push" in argv_) == want, f"allow_bulk_ssll_push={allow!r} 时参数不对: {argv_}"
    assert "--include-on-demand" not in argv_, "放行大批首推不许顺手放行 on_demand"
rc_, _, _ = sh(ssll_run, {"github.event.inputs.dry_run": "", "github.event.inputs.allow_bulk_ssll_push": ""},
               {"PROJECT_FILTER": "", "STUB_RC": "1"})
assert rc_ == 1, f"脚本退出码 1 时这一步要失败 (continue-on-error 之后 outcome=failure), 实得 {rc_}"
outcomes = {k: "success" for k in ("feishu_sync", "comments_sync", "essence_sync", "gate3_score", "curate_sync", "ssll_sync")}
agg_run = agg[0]["run"].replace("${{ github.repository }}", "o/r").replace("${{ github.run_id }}", "1")
rc_, _, out_ = sh(agg_run, {f"steps.{k}.outcome": v for k, v in dict(outcomes, ssll_sync="failure").items()})
assert rc_ == 1 and "ssll_sync" in out_, f"通道 1 被挡 (failure) 时失败聚合要红并点名 ssll_sync: rc={rc_}"
rc_, _, _ = sh(agg_run, {f"steps.{k}.outcome": v for k, v in outcomes.items()})
assert rc_ == 0, "全绿时失败聚合不该红"
print("✓ §7j daily-sync: 定时跑 / 不勾不放行、勾了才放行且不带 --include-on-demand; 退出码 1 → 这一步红 → 聚合点名 ssll_sync")


# §7k 闸查旧样本出错 → 按新插算 (D-130 第 1 条: 宁可多数一篇也不让闸漏)。
#     PostgREST 一时 5xx: 闸里那一次查炸了, 到主循环再查就好了 —— 闸要是把出错当 orphan (或干脆跳过),
#     新插就被少数, 一批换号来的新篇照样整批推出去。
class FlakySB(FakeSB):
    """flaky 里的 note_id 第一次按键查样本就抛 (只抛一次), 之后照常。"""

    def __init__(self, notes, samples, flaky):
        super().__init__(notes, samples)
        self.flaky = set(flaky)

    def execute(self, q: FakeQ):
        if q.op == "select" and q.table_ == "reference_samples":
            hit = [v for _c, op, v in q.filters if op == "eq" and v in self.flaky]
            if hit:
                self.flaky.discard(hit[0])
                raise RuntimeError(f"假 PostgREST 503 ({hit[0]})")
        return super().execute(q)


#   直接调: 31 篇在闸里全查炸 → 31 篇全算新插、挡
sb = FlakySB(rows31, [], flaky=ids31)
s.logger.disabled = True            # 31 条「查失败 → 按新插算」不刷屏; 日志行本身下面 main() 那段核
try:
    plan = s.plan_bulk_first_push(sb, rows31)
finally:
    s.logger.disabled = False
assert sorted(plan["new"]) == sorted(ids31) and plan["orphans"] == [] and plan["blocked"], \
    f"查样本出错要按新插算: 新插 {len(plan['new'] or [])} / orphan {len(plan['orphans'])} / blocked={plan['blocked']}"
#   驱动 main(): 31 篇里 3 篇在闸里查炸 —— 按新插算才 31 > 30 挡住; 当 orphan 算就只剩 28, 闸漏、主循环再查又好了, 31 篇全推
flaky3 = ids31[:3]
sb = FlakySB(rows31, [], flaky=flaky3)
rc, log, summ = run_main(sb)
err = [ln for ln in log.splitlines() if "【大批首推被挡】" in ln]
assert rc == 1 and wrote_nothing(sb), f"闸里查炸的篇要算新插、照挡: rc={rc} 新插 {len(sb.inserted)} 标记 {len(sb.updated)}"
assert len(err) == 1 and all(i in err[0] for i in flaky3), "查炸的那 3 篇要在 ERROR 行的新插名单里"
assert "按新插算" in log, "查炸要留一行 WARNING"
print("✓ §7k 闸里查旧样本出错 → 按新插算 (31 篇全炸全算; 3 篇炸把 28 顶过线照挡、名单里有它们)")

print("\ncheck_ssll_retract: all checks passed")
