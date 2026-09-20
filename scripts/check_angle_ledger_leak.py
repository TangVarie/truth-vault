"""
check_angle_ledger_leak.py
═══════════════════════════════════════════════════════════════════════════

写作台发出去的「角度」有没有走到成稿? —— 只读, 不写库。

2026-09-20 查 deskcore 的 `/health` 发现 `config.pipeline.ok = false`: 近 7 天发牌
214 个角度、只有 20 个在台账上销了账。顺着挖下去(D-071), 194 个没销账的角度分成
两种完全不同的形状, 而 `/health` 那一个百分比把它们糊在一起:

  · 138 个 —— **抽完一篇稿都没写**。draw_angles 之后同项目窗口内没有任何真稿入库。
    会话在发牌之后就停了。sportsix 三次共 60 个角度、hatherine 系列四个项目, 都是这样。
  · 56 个 —— **写了稿, 但提交时没带 angle_key**。稿子进了指纹库, 台账却销不了账。
    后果写在 deskcore/core.py 的注释里: 这些坐标一天后就不在避重集里, 同一个故事
    下一批还会被抽到, 而「同题重写」指纹闸抓不到。

⚠️ **必须排除 TV 导入的副本, 否则这个指标读出来是假的。** 同窗口 1,507 条指纹里
1,468 条是 `tv-sync` 把 TV 笔记复制进写作台留下的(`tv_note_links.match_kind='ingested'`,
D-064), 它们本来就没有 angle_key —— 不是发牌产出的, 没有坐标。把它们算进「没带
坐标的稿子」, 未归因率永远是 97%+, 这盏灯就等于没有。真稿只有 39 条, 其中 22 条带坐标。

判据(两条, 都故意设了下限, 免得天天红 —— D-053):
    A. 某项目窗口内发牌 >= MIN_DRAWN 个角度, 而真稿 == 0     → 抽完没写
    B. 某项目窗口内【发过牌】且真稿 >= MIN_DRAFTS, 而带坐标的 == 0 → 写了不带坐标
两条都不成立才算通。一次发两三张牌、当场没写完是常态, 所以下限不能是 1。

数据来源(都在共享 Supabase 的 autowriter schema 里, TV 用 service_role 只读):
    发牌  = autowriter.angle_ledger(drawn_at 在窗口内; consumed_version_id 非 NULL = 销了账)
    成稿  = autowriter.draft_fingerprints(created_at 在窗口内)
    排除  = autowriter.tv_note_links 里 match_kind='ingested' 的 version_id

窗口: 默认 7 天。比馆员那盏灯(48h)长, 因为「发牌 → 写稿」的节奏按天走, 48h 窗口
    多数日子会落进「窗口内没发牌」的无从判定, 灯就白装了。

用法:
    python check_angle_ledger_leak.py                 # 默认 7 天
    python check_angle_ledger_leak.py --window-days 14

退出码:
    0 = 窗口内没发牌(无从判定), 或两条判据都不成立
    1 = 至少一个项目命中判据 —— 修在 autowriter 仓(协议/使用习惯), TV 这边红了也改不好
⚠️ 同 check_librarian_traffic.py 的约定: 正常跑完末尾必打一行
`ANGLE_LEDGER_CHECK_DONE rc=<码>`; daily-sync.yml 靠有没有这一行判定崩溃, 不靠退出码。
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

# ⚠️ 故意【不】在模块顶层 import _common(会拖进 supabase / yaml)。report() 是纯函数,
# CI 在裸环境里直接 import 本模块测它 —— 同 check_librarian_traffic.py 的理由。

DEFAULT_WINDOW_DAYS = 7
# 判据下限: 低于这两个数不喊。一次发牌 2-5 张、当场只写一两篇是正常节奏。
MIN_DRAWN = 10
MIN_DRAFTS = 5
# tv-sync 复制进写作台的副本: 不是发牌产出的, 没有坐标, 不能算进未归因。
INGESTED_KIND = "ingested"


def verdicts(by_project: dict) -> list[dict]:
    """哪些项目命中了判据。纯函数 —— CI 直接喂假 stats 测它。

    ``by_project`` 按 project_id 索引, 每格带一个 ``name`` 作显示。
    """
    out = []
    for pid, s in sorted(by_project.items()):
        name = s.get("name") or pid
        drawn, drafts, with_key = s["drawn"], s["drafts"], s["with_key"]
        if drawn >= MIN_DRAWN and drafts == 0:
            out.append({"project": name, "project_id": pid, "kind": "drawn_unwritten",
                        "drawn": drawn,
                        "detail": f"发了 {drawn} 个角度, 窗口内一篇真稿都没入库"})
        elif drawn > 0 and drafts >= MIN_DRAFTS and with_key == 0:
            # ⚠️ `drawn > 0` 这一条不能省(codex review on #143): 压根没走 draw_angles
            # 的项目, 它的稿子本来就没有坐标, 台账里也没有行可销 —— 报它"漏账"是
            # 判错病因, 而且只要别的项目发过一次牌, 全局那道 drawn == 0 的闸就拦不住。
            out.append({"project": name, "project_id": pid, "kind": "unattributed",
                        "drafts": drafts,
                        "detail": f"发了 {drawn} 个角度、{drafts} 篇真稿入库, "
                                  "没有一篇带 angle_key, 台账无法销账"})
    return out


def report(stats: dict, window_days: int) -> int:
    """把 gather() 的统计渲染成报告并返回退出码。纯函数, 不碰网络。"""
    by_project = stats.get("by_project") or {}
    drawn = sum(s["drawn"] for s in by_project.values())
    consumed = sum(s["consumed"] for s in by_project.values())
    drafts = sum(s["drafts"] for s in by_project.values())
    with_key = sum(s["with_key"] for s in by_project.values())
    ingested = stats.get("ingested_skipped", 0)

    print()
    print("=" * 84)
    print(f"  角度台账 · 过去 {window_days} 天 · 发牌 {drawn} · 销账 {consumed} · "
          f"真稿 {drafts}(带坐标 {with_key})")
    print("=" * 84)
    print(f"  已排除 {ingested} 条 tv-sync 导入的副本(match_kind={INGESTED_KIND}) —— "
          "它们不是发牌产出的, 本来就没有坐标")
    if by_project:
        print(f"  {'项目':<24}{'发牌':>6}{'销账':>6}{'真稿':>6}{'带坐标':>8}")
        for pid, s in sorted(by_project.items(), key=lambda kv: -kv[1]["drawn"]):
            print(f"  {(s.get('name') or pid)[:23]:<24}{s['drawn']:>6}{s['consumed']:>6}"
                  f"{s['drafts']:>6}{s['with_key']:>8}")

    if drawn == 0:
        print("  · 窗口内没有发牌, 无从判定(不是健康, 是没活) —— ok")
        return 0

    hits = verdicts(by_project)
    if not hits:
        print("  ✓ 没有项目命中判据 —— 发出去的角度都有稿子接住, 或量小到不值得喊")
        return 0

    unwritten = [h for h in hits if h["kind"] == "drawn_unwritten"]
    unattr = [h for h in hits if h["kind"] == "unattributed"]
    parts = []
    if unwritten:
        parts.append("抽完没写: " + "; ".join(f"{h['project']}({h['detail']})" for h in unwritten))
    if unattr:
        parts.append("写了不带坐标: " + "; ".join(f"{h['project']}({h['detail']})" for h in unattr))
    msg = (f"过去 {window_days} 天 {len(hits)} 个项目的角度没走到成稿。" + " | ".join(parts)
           + " —— 后果不是少写了几篇: 没销账的坐标一天后就不在避重集里, 同一个故事"
             "下一批会被再抽一次, 而「同题重写」指纹闸抓不到。"
             "修在 autowriter 仓(commit_drafts 每条都要带 draw_angles 给的 angle_key;"
             "会话别停在发牌之后), 见 TV docs/27 与 aw deskcore-runbook。")
    print(f"  ⚠ {msg}")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::warning title=角度台账漏账(发了牌没走到成稿)::{msg}", flush=True)
    return 1


def gather(sb, since_iso: str) -> dict:
    """读两边的行。只取判据要的几列。"""
    from _common import fetch_all_pages  # 局部 import, 理由见文件头

    # ⚠️ order_by 必须是【唯一 + 稳定】的列, 且出现在 select 里 —— 这是
    # fetch_all_pages 自己 docstring 里的正确性前提, 不是洁癖: 它按 order_by 的值
    # 去重(fresh = 没见过的那些), 用 created_at / drawn_at 这种**不唯一**的列做键,
    # 同一毫秒的几行跨页时会被当成重复**静默丢掉**, 计数就少了、判据可能翻面。
    # 本窗口 7 天就有 1,507 条指纹, 早就跨过 1000 行的页边界(codex review on #143)。
    angles = fetch_all_pages(
        sb.schema("autowriter").table("angle_ledger")
        .select("id, project_id, consumed_version_id, drawn_at")
        .gte("drawn_at", since_iso),
        order_by="id")
    fps = fetch_all_pages(
        sb.schema("autowriter").table("draft_fingerprints")
        .select("id, project_id, angle_key, version_id, created_at")
        .gte("created_at", since_iso),
        order_by="id")

    # 排除 tv-sync 导入的副本。按实际见到的 version_id 精确查 —— 不按时间窗猜,
    # 猜错的方向是把导入副本当成"真稿没带坐标", 那正是要避免的假警报。
    ids = [f["version_id"] for f in fps if f.get("version_id")]
    ingested: set[str] = set()
    for i in range(0, len(ids), 200):
        rows = (sb.schema("autowriter").table("tv_note_links")
                .select("version_id")
                .eq("match_kind", INGESTED_KIND)
                .in_("version_id", ids[i:i + 200])
                .execute()).data or []
        ingested.update(r["version_id"] for r in rows)

    names = _project_names(sb, {a["project_id"] for a in angles}
                           | {f["project_id"] for f in fps})
    by_project: dict[str, dict] = {}

    def slot(pid):
        # ⚠️ 按 **project_id** 聚合, 名字只作显示(codex review on #143): service_role
        # 读的是全租户的行, 而项目名不唯一(生产里就有「百健士-藻油」与「百健士藻油」
        # 这种)。拿名字当键会把两个不相干的 UUID 并成一格 —— 合起来的计数可能越过
        # 判据门槛(假警报), 也可能让一个项目的漏账被另一个的正常量盖住(漏报)。
        key = pid or "?"
        return by_project.setdefault(
            key, {"name": names.get(pid) or key, "drawn": 0, "consumed": 0,
                  "drafts": 0, "with_key": 0})

    for a in angles:
        s = slot(a["project_id"])
        s["drawn"] += 1
        if a.get("consumed_version_id"):
            s["consumed"] += 1
    for f in fps:
        if f.get("version_id") in ingested:
            continue
        s = slot(f["project_id"])
        s["drafts"] += 1
        if f.get("angle_key"):
            s["with_key"] += 1
    return {"by_project": by_project, "ingested_skipped": len(ingested)}


def _project_names(sb, pids: set) -> dict:
    pids = [p for p in pids if p]
    out: dict[str, str] = {}
    for i in range(0, len(pids), 200):
        rows = (sb.schema("autowriter").table("projects")
                .select("id, name").in_("id", pids[i:i + 200]).execute()).data or []
        for r in rows:
            out[r["id"]] = r.get("name") or r["id"]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS,
                        help=f"看过去多少天的发牌与成稿(默认 {DEFAULT_WINDOW_DAYS})")
    args = parser.parse_args()
    if args.window_days < 1:
        print("--window-days 必须 >= 1")
        return 2
    since = ((datetime.now(timezone.utc) - timedelta(days=args.window_days))
             .replace(tzinfo=None).isoformat(timespec="seconds"))

    from _common import get_supabase_client  # 局部 import, 理由见文件头
    sb = get_supabase_client()
    stats = gather(sb, since)
    rc = report(stats, args.window_days)
    # ⚠️ 哨兵行: daily-sync.yml 靠它区分"跑完了"和"崩了"(那边是 `|| true` 调的)。
    print(f"ANGLE_LEDGER_CHECK_DONE rc={rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
