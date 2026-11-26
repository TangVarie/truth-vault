#!/usr/bin/env python3
"""linkcheck 机器词进流量状态格 (I-01 第 1 部分, 2026-11-25): 观察中 / 链接失效 的规则、没命中的标告警、爆贴门槛对不上告警。

断行为不断源码 (D-051): §1 §2 用真 mapping 跑 extract_tier / transform_row; §3 读真 mapping 的规则;
§4 用假飞书跑 preflight_mapping.main; §5 纯函数; 只有 §6 (接线位置) 读源码。

  §1 观察中 → 未知 (XIWU_phase1 37 行、SPX_phase1 11 行以前每晚报「状态值没映上」), 不再打 tier_unmapped。
  §2 链接失效 → 删除 (D-119 #13), 档位低于 爆 / 大爆 / 趴、高于 评估中 / 未知:
     ['大爆','链接失效'] → 大爆 · ['链接失效'] → 删除 · ['链接失效','观察中'] → 删除 · ['链接失效','无水花'] → 趴 ·
     ['爆贴','风控中','链接失效'] → 风控 (否决位照旧) · ['爆贴','疑似限流'] → 爆、HATHERINE ['大爆','疑似限流'] → 大爆 (疑似限流不当风控, 不扩 D-124; HATHERINE 那条 11-25 拿掉)。
  §3 每张每天同步、状态格进 _status_raw 的表 (和 _template) 都有 观察中、链接失效 两条规则。
  §4 preflight: 状态格里没命中任何规则的标列进 warnings, 退出码不变 (0)。
  §5 爆贴门槛对不上: 这一晚新升 爆 / 大爆、档来自 爆贴 / 大爆 标、评论数不到 50 / 100 → 列出来; 诊断信息带「保留高档位」、
     伪爆、库里本来就是 爆 / 大爆、数值推断、没有评论数的 → 不列。
  §6 接线: 门槛检查在翻转闸之后、upsert 之前, 只告警, 不计 errors。
  §7 新档位 × 途鸽那道绊线 (undeclared_ticket_on_positive, 只看没被挡的 爆 / 大爆; 11-26 随 main 合进来): 真 mapping 上
     ['爆贴','链接失效'] / ['大爆','链接失效'] 仍是正例、绊线照看; 删除 / 未知 不看; 否决位挡下的 风控 不看;
     HATHERINE ['爆贴','疑似限流'] 11-25 起不再被否决成 风控 → 成了没挡的 爆, 绊线要看得见; 声明了的途鸽走铺评工单, 不报。

反证 (改坏之后必须变红):
  ① 拿掉 SPX 的 观察中 规则                → §1 红
  ② _TIER_RANK 里不给 删除 档位 (取 0)      → §2 ['链接失效','观察中'] 那条红
  ③ 门槛检查不排除「保留高档位」            → §5 红 (本文件 §5 末尾实跑这条反证)
  ④ preflight 把没命中的标放进 blocking     → §4 退出码那条红
  ⑤ 绊线只认 爆 (漏了 大爆), 或把 删除 / 未知 也当正例 → §7 红

跑法: cd scripts && python check_tier_vocab.py
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
from pathlib import Path

import _common as c
import preflight_mapping as pf
import sync_feishu_notes_to_truth_vault as engine

ROOT = Path(__file__).resolve().parent.parent


def tier_of(pid: str, status) -> str | None:
    return c.extract_tier(status, c.load_mapping(pid)["tier_extraction"]["rules"])


# ── §1 观察中 → 未知 ────────────────────────────────────────────────────────
def check_observing() -> None:
    for pid in ("SPX_phase1", "XIWU_phase1", "ANSHEN_phase1", "BJS_phase1", "LNKT_phase1", "OKMAN_phase1",
                "RIO_phase1", "WTG_phase1"):
        assert tier_of(pid, ["观察中"]) == "未知", f"§1 {pid}: ['观察中'] → {tier_of(pid, ['观察中'])}"
    spx = c.load_mapping("SPX_phase1")
    note, _, _ = engine.transform_row(spx, "r1", {"笔记内容": "正文", "流量状态": ["观察中"]})
    assert note.get("tier") == "未知", note.get("tier")
    assert "tier_unmapped" not in (note.get("data_quality_flags") or {}), "§1 观察中 不该再打 tier_unmapped"
    assert note["tier"] not in engine._FLIP_POSITIVE, "§1 未知 不是正例, 不碰翻转闸"
    print("  §1 观察中 → 未知: 8 张以前缺这条的表都有了, transform_row 不再打 tier_unmapped ✓")


# ── §2 链接失效 → 删除 ─────────────────────────────────────────────────────
def check_dead_link() -> None:
    cases = [
        ("SPX_phase1", ["大爆", "链接失效"], "大爆"),
        ("XIWU_phase1", ["爆贴", "链接失效"], "爆"),
        ("SPX_phase1", ["链接失效"], "删除"),
        ("XIWU_phase1", ["链接失效", "观察中"], "删除"),
        ("SPX_phase1", ["评估中", "链接失效"], "删除"),
        ("SPX_phase1", ["链接失效", "无水花"], "趴"),
        ("SPX_phase1", ["爆贴", "风控中", "链接失效"], "风控"),
        ("XIWU_phase1", ["爆贴", "疑似限流"], "爆"),
        ("SPX_phase1", ["疑似限流", "无水花"], "趴"),
        ("HATHERINE_phase1", ["大爆", "疑似限流"], "大爆"),   # HATHERINE 的 疑似限流 → 风控 11-25 拿掉了 (D-177 第 3 条)
    ]
    for pid, status, want in cases:
        got = tier_of(pid, status)
        assert got == want, f"§2 {pid} {status} → {got}, 应为 {want}"
    assert c._TIER_RANK["趴"] > c._TIER_RANK["删除"] > c._TIER_RANK["评估中"] > c._TIER_RANK["未知"]
    # transform_row: 删除 不被数值推断推回 (只有 None / 未知 才推)
    spx = c.load_mapping("SPX_phase1")
    note, _, _ = engine.transform_row(spx, "r", {"笔记内容": "正文", "流量状态": ["链接失效"], "实时数据.评论数": 80})
    assert note.get("tier") == "删除" and note.get("tier_source") == "状态字段", (note.get("tier"), note.get("tier_source"))
    print(f"  §2 链接失效 → 删除: {len(cases)} 个形状 (爆过的照旧是爆、否决位照旧、疑似限流不当风控), 评论数 80 也不推回 ✓")


# ── §3 lint: 每天同步的表都有这两条 ──────────────────────────────────────────
def check_daily_rules() -> None:
    import yaml
    n = 0
    for f in sorted((ROOT / "mappings").glob("*.yaml")):
        m = yaml.safe_load(f.read_text(encoding="utf-8"))
        if f.stem != "_template":
            if (m.get("sync_config") or {}).get("sync_interval") != "daily":
                continue
            if "_status_raw" not in (m.get("field_mapping") or {}).values():
                continue
        rules = (m.get("tier_extraction") or {}).get("rules") or []
        got = {needle: r.get("tier") for r in rules for needle in (r.get("match_contains") or [])}
        assert got.get("观察中") == "未知", f"§3 {f.name}: 缺「观察中 → 未知」"
        assert got.get("链接失效") == "删除", f"§3 {f.name}: 缺「链接失效 → 删除」"
        n += 1
    assert n >= 13, f"§3 只核到 {n} 份 (12 张每天同步的表 + _template), 路径不对?"
    print(f"  §3 {n} 份 mapping (每天同步 + _template) 都有 观察中 / 链接失效 两条 ✓")


# ── §4 preflight: 没命中的标只告警 ─────────────────────────────────────────
class _FakeFeishu:
    RECORDS: list[dict] = []

    def __init__(self, *_a, **_k):
        pass

    def list_records(self, *_a, **_k):
        yield from self.RECORDS


def _run_preflight(records: list[dict]) -> tuple[int, str]:
    saved_fs, saved_env, saved_argv = pf.FeishuClient, dict(os.environ), sys.argv
    _FakeFeishu.RECORDS = records
    pf.FeishuClient = _FakeFeishu
    os.environ.update({"FEISHU_APP_ID": "x", "FEISHU_APP_SECRET": "y"})
    sys.argv = ["preflight_mapping.py", "SPX_phase1"]
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = pf.main()
    finally:
        pf.FeishuClient, sys.argv = saved_fs, saved_argv
        os.environ.clear()
        os.environ.update(saved_env)
    return rc, buf.getvalue()


def check_preflight_unmatched() -> None:
    base = {"笔记内容": "正文", "反馈链接": {"link": "http://x", "text": "x"}}
    rec = [{"record_id": "r1", "fields": {**base, "流量状态": ["爆贴", "新出现的标"]}},
           {"record_id": "r2", "fields": {**base, "流量状态": ["新出现的标"]}},
           {"record_id": "r3", "fields": {**base, "流量状态": ["无水花"]}}]
    s = pf.project_rows(c.load_mapping("SPX_phase1"), rec, show_cap=8)
    assert dict(s["status_unmatched"]) == {"新出现的标": 2}, dict(s["status_unmatched"])
    rc, out = _run_preflight(rec)
    assert rc == 0, f"§4 没命中的标只告警, 退出码要是 0: rc={rc}\n{out[-800:]}"
    assert "没命中任何规则" in out and "新出现的标" in out, out[-800:]
    rc2, out2 = _run_preflight([rec[2]])
    assert rc2 == 0 and "没命中任何规则" not in out2, "§4 全都命中时不该告警"
    assert pf.status_unmatched_warning(s["status_unmatched"]) and not pf.status_unmatched_warning(type(s["status_unmatched"])())
    print("  §4 preflight: 状态格里没命中的标列进提醒, 退出码仍是 0; 全命中不提醒 ✓")


# ── §5 爆贴门槛对不上 ──────────────────────────────────────────────────────
def _n(nid, tier, cc, src="['爆贴']", diag=None, ts="状态字段", und=False):
    rx = {"_tier_source_raw": src}
    if diag is not None:
        (rx.setdefault("_undeclared", {}) if und else rx)["诊断信息"] = diag
    return {"note_id": nid, "tier": tier, "tier_source": ts, "comments_count": cc, "raw_extra": rx}


def check_threshold() -> None:
    notes = [
        _n("a", "爆", 30),                                       # 新升、30 < 50 → 列
        _n("b", "大爆", 80, src="['大爆']"),                     # 80 < 100 → 列
        _n("c", "爆", 30, diag="保留高档位: 评论被删"),          # linkcheck 故意留的高档 → 不列
        _n("c2", "爆", 30, diag="… 保留高档位 …", und=True),     # 诊断信息在 _undeclared 也认
        _n("d", "爆", 30, src="['伪爆贴500']"),                  # 伪爆 → 不列
        _n("e", "爆", 30),                                       # 库里本来就是 爆 → 不列
        _n("f", "爆", 60),                                       # 过线 → 不列
        _n("g", "大爆", 120, src="['大爆']"),                    # 过线 → 不列
        _n("h", "爆", None),                                     # 没评论数 → 不列
        _n("i", "爆", 30, ts="数值推断"),                        # 不是状态格的档 → 不列
        _n("j", "爆", 30, src="['小爆']"),                       # 不是 爆贴 / 大爆 标 → 不列
        _n("k", "趴", 3, src="['无水花']"),                      # 不是 爆 / 大爆 → 不列
    ]
    current = {"a": "评估中", "b": "爆", "c": "评估中", "c2": None, "e": "爆", "f": "评估中"}
    got = engine.plan_threshold_mismatch(notes, current)
    assert [(m["note_id"], m["tier"], m["need"]) for m in got] == [("a", "爆", 50), ("b", "大爆", 100)], got
    saved = engine._THRESHOLD_KEEP_HIGH
    engine._THRESHOLD_KEEP_HIGH = "\x00不会出现\x00"
    try:
        got2 = {m["note_id"] for m in engine.plan_threshold_mismatch(notes, current)}
        assert {"c", "c2"} <= got2, f"§5 反证没变红: {got2}"
    finally:
        engine._THRESHOLD_KEEP_HIGH = saved
    print("  §5 爆贴门槛: 新升且评论不够的 2 篇列出; 保留高档位 / 伪爆 / 本来就是爆 / 过线 / 没评论数 / 数值推断 不列; "
          "不排除保留高档位就变红 (反证) ✓")


# ── §6 接线 ─────────────────────────────────────────────────────────────────
def check_wiring() -> None:
    src = Path(engine.__file__).read_text(encoding="utf-8")
    body = src[src.index("def main("):]
    i_flip = body.index("flip = plan_tier_flip(")
    i_thr = body.index("mismatch = plan_threshold_mismatch(")
    i_up = body.index("written_ids = upsert_notes_batch(")
    assert i_flip < i_thr < i_up, "§6 门槛检查要在翻转闸之后、upsert 之前"
    block = body[i_thr:body.index("# ── 风控旗子的来源列整轮不见了", i_thr)]
    assert 'stats["errors"]' not in block and "::warning" in block, "§6 只告警 (::warning), 不计 errors"
    print("  §6 接线: 翻转闸之后、upsert 之前, 只 ::warning 不计 errors ✓")


# ── §7 新档位 × 途鸽绊线 ────────────────────────────────────────────────────
def check_tripwire_tiers() -> None:
    cell = "\n".join(f"{i}. 评论{i}" for i in range(1, 21))        # 20 行, 评论数 16 → 16−20 不过线
    cases = [   # (表, 流量状态, 档位, 绊线报几篇)。SPX / HATHERINE 没声明「维护评论」, 途鸽声明了
        ("SPX_phase1", ["爆贴", "链接失效"], "爆", 1),
        ("SPX_phase1", ["大爆", "链接失效"], "大爆", 1),
        ("SPX_phase1", ["链接失效"], "删除", 0),
        ("SPX_phase1", ["观察中", "链接失效"], "删除", 0),
        ("SPX_phase1", ["观察中"], "未知", 0),
        ("SPX_phase1", ["爆贴", "风控中", "链接失效"], "风控", 0),
        ("HATHERINE_phase1", ["爆贴", "疑似限流"], "爆", 1),
        ("HATHERINE_phase1", ["疑似限流"], None, 0),
        ("TUGE_phase1", ["爆贴", "链接失效"], "爆", 0),
    ]
    for pid, status, want, trips in cases:
        m = c.load_mapping(pid)
        note, _, _ = engine.transform_row(m, "r7", {"笔记内容": "正文", "流量状态": status, "实时数据.评论数": 16, "维护评论": cell})
        got = engine.undeclared_ticket_on_positive(m, [note])
        assert note.get("tier") == want and len(got) == trips, f"§7 {pid} {status} → {note.get('tier')} 绊线 {got}, 应为 {want} / {trips}"
    print(f"  §7 新档位 × 途鸽绊线: {len(cases)} 个形状 (链接失效带热度标照报、删除 / 未知 / 风控不报、HATHERINE 疑似限流放出来的爆照报) ✓")


def main() -> int:
    check_observing()
    check_dead_link()
    check_daily_rules()
    check_preflight_unmatched()
    check_threshold()
    check_wiring()
    check_tripwire_tiers()
    print("\ncheck_tier_vocab: 7 节全过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
