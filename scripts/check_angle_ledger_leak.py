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

判据(三条, 都故意设了下限, 免得天天红 —— D-053):
    A. 某项目窗口内发牌 >= MIN_DRAWN 个角度, 而真稿 == 0     → 抽完没写
    B. 某项目窗口内【发过牌】且真稿 >= MIN_DRAFTS, 而带坐标的 == 0 → 写了不带坐标
    C. 某 TV 项目窗口内补录副本 >= MIN_UNCAUGHT 篇、对上写作台存档的 <= MAX_CAUGHT 篇,
       而它对应的写作台项目近 USED_WITHIN_DAYS 天用过写作台         → 发了帖、写作台没接住
三条都不成立才算通。一次发两三张牌、当场没写完是常态, 所以下限不能是 1。

C 是 2026-10-19 补的(TV OPEN-ITEMS O-04): 途鸽 9-16 之后写作台一次发牌、一篇存档都没收到, 10-12 那周
发出去的 22 篇全是 tv-sync 补录的副本, 写手却一直以为在用写作台。A / B 都从【发牌】那一侧看, 一张牌
都没发的项目在它们眼里是「没活」, 所以这件事一个月都没灯亮。C 从【发帖】那一侧看, 分两种报:
    · 写作台窗口内没收到这个项目的一次发牌、一篇真稿 → 写这个项目的那几场对话没调起写作台(skill 没被
      调起来、没开项目就写了; WorkBuddy 的写作台连接是全局的, owner 10-19 确认)。同一个写手别的项目
      照常发牌也可能是这样 —— 途鸽就是(10-19 写手在另一场对话里列项目是通的);
    · 写作台有动静, 但发出去的不是它存的稿                → 连上了、写完没存档。
「近 USED_WITHIN_DAYS 天用过写作台」那一条是为了不对从来不走写作台的项目天天喊。
数据: autowriter.tv_project_map(TV 项目 → 写作台项目)、truth_vault.notes(publish_time 在窗口内) +
autowriter.tv_note_links(
按 match_kind 分补录 / 对上)、autowriter.angle_ledger(USED_WITHIN_DAYS 天内发过牌的写作台项目)。

数据来源(都在共享 Supabase 的 autowriter schema 里, TV 用 service_role 只读):
    发牌  = autowriter.angle_ledger(drawn_at 在窗口内; consumed_version_id 非 NULL = 销了账)
    成稿  = autowriter.draft_fingerprints(created_at 在窗口内)
    排除  = autowriter.tv_note_links 里 match_kind='ingested' 的 version_id

窗口: 默认 7 天。比馆员那盏灯(48h)长, 因为「发牌 → 写稿」的节奏按天走, 48h 窗口
    多数日子会落进「窗口内没发牌」的无从判定, 灯就白装了。

用法:
    python check_angle_ledger_leak.py                 # 默认 7 天
    python check_angle_ledger_leak.py --window-days 14
    python check_angle_ledger_leak.py --selftest      # CI: 判据 C 的纯函数 + 取数, 不连库

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
# 判据 C 的下限: 一周补录 >= 10 篇且对上 <= 2 篇才喊。10-12 那周 sportsix 补录 12 / 对上 18、
# 百健士 15 / 19, 这种"一部分在外面写"的不喊; 途鸽 22 / 0、Hatherine 23 / 1 喊。
MIN_UNCAUGHT = 10
MAX_CAUGHT = 2
USED_WITHIN_DAYS = 60
# tv-sync 复制进写作台的副本: 不是发牌产出的, 没有坐标, 不能算进未归因。
INGESTED_KIND = "ingested"
# 对上写作台存档的几种(tv-sync 的 match_kind; ambiguous / unmatched 两边都不算)。
CAUGHT_KINDS = frozenset({"body_exact", "title_exact", "fuzzy", "edited", "tv_lineage"})


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


def verdicts_publish(by_project: dict, pub: dict) -> list[dict]:
    """判据 C: 哪些 TV 项目在发帖、写作台却没接住。纯函数 —— CI 直接喂假数测它。

    ``by_project`` 是 gather() 的那份(写作台项目 → 窗口内发牌 / 真稿); ``pub`` 是 gather_publish() 的:
    ``{"map": {tv: [写作台 project_id…]}, "links": {tv: {"ingested": n, "caught": n}},
    "used": {近 USED_WITHIN_DAYS 天发过牌的写作台 project_id}}``。
    """
    out = []
    used = pub.get("used") or set()
    for tv, pids in sorted((pub.get("map") or {}).items()):
        link = (pub.get("links") or {}).get(tv) or {}
        ing, caught = link.get("ingested", 0), link.get("caught", 0)
        if ing < MIN_UNCAUGHT or caught > MAX_CAUGHT:
            continue
        if not any(p in used for p in pids):
            continue        # 近 USED_WITHIN_DAYS 天没用过写作台: 本来就不在写作台写, 不喊
        drawn = sum((by_project.get(p) or {}).get("drawn", 0) for p in pids)
        drafts = sum((by_project.get(p) or {}).get("drafts", 0) for p in pids)
        if drawn == 0 and drafts == 0:
            kind, why = "desk_silent", ("写作台这几天没收到它一次发牌、一篇存档 —— 写这个项目的对话没走到写作台"
                                        "(skill 没被调起来, 没开项目就写了)")
        else:
            kind, why = "published_unsaved", (f"写作台这几天发牌 {drawn}、真稿 {drafts} —— 连上了, "
                                              "但发出去的不是写作台存的稿(写完没存档)")
        out.append({"project": tv, "kind": kind, "ingested": ing, "caught": caught,
                    "drawn": drawn, "drafts": drafts,
                    "detail": f"{ing} 篇发出去的帖是补录副本、对上写作台存档的 {caught} 篇; {why}"})
    return out


def _print_publish(pub: dict, by_project: dict, window_days: int) -> None:
    links = pub.get("links") or {}
    rows = [(tv, links[tv]) for tv in sorted(pub.get("map") or {})
            if tv in links and (links[tv].get("ingested") or links[tv].get("caught"))]
    if not rows:
        return
    print(f"  发帖对账 · 过去 {window_days} 天 tv-sync 新连上的笔记(判据 C)")
    print(f"  {'TV 项目':<24}{'补录副本':>8}{'对上存档':>8}{'写作台发牌':>10}{'真稿':>6}")
    for tv, l in rows:
        pids = pub["map"][tv]
        drawn = sum((by_project.get(p) or {}).get("drawn", 0) for p in pids)
        drafts = sum((by_project.get(p) or {}).get("drafts", 0) for p in pids)
        print(f"  {tv[:23]:<24}{l.get('ingested', 0):>8}{l.get('caught', 0):>8}{drawn:>10}{drafts:>6}")


def _warn_publish(pub_hits: list[dict], window_days: int) -> None:
    msg = (f"过去 {window_days} 天 {len(pub_hits)} 个 TV 项目在发帖、写作台却没接住: "
           + "; ".join(f"{h['project']}({h['detail']})" for h in pub_hits)
           + " —— 这些帖没有发牌查重, 也进不了改稿差异和参考分, 飞轮只能当外部稿补录。"
             "写作台零动静的: 让写这个项目的人打开上周写它的那场对话, 看有没有 open_project / draw_angles 的调用记录 ——"
             "没有就是那场对话没调起写作台(aw#109 起 skill 触发放宽、写作台会在下一场对话里提醒); 连上了没存档的: 看 aw "
             "deskcore-runbook 的 score_drafts 存档。"
             "修在写手那边和 autowriter 仓, TV 这边改不好。")
    print(f"  ⚠ {msg}")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::warning title=发了帖、写作台没接住::{msg}", flush=True)


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

    pub = stats.get("publish") or {}
    pub_hits = verdicts_publish(by_project, pub)
    _print_publish(pub, by_project, window_days)
    if pub_hits:
        _warn_publish(pub_hits, window_days)

    if drawn == 0:
        print("  · 窗口内没有发牌, 角度台账无从判定(不是健康, 是没活)")
        return 1 if pub_hits else 0

    hits = verdicts(by_project)
    if not hits:
        print("  ✓ 没有项目命中判据 A / B —— 发出去的角度都有稿子接住, 或量小到不值得喊")
        return 1 if pub_hits else 0

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
             "修在 autowriter 仓(score_drafts 每条都要带 draw_angles 给的 angle_key;"
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


def gather_publish(sb, since_iso: str, used_since_iso: str, until_iso: str | None = None) -> dict:
    """判据 C 要的数: TV 项目 → 写作台项目、窗口内【发出去】的笔记按 match_kind 分、近期用过写作台的项目。"""
    from _common import fetch_all_pages  # 局部 import, 理由见文件头

    # tv_project_map 是人工维护的几十行, 一页够; 笔记和台账会跨 1000 行的页边界, 按唯一键翻。
    maps = (sb.schema("autowriter").table("tv_project_map")
            .select("tv_project_id, project_id").execute()).data or []
    # 窗口按 truth_vault.notes.publish_time 切, 不按对照写进去的时间(matched_at): 新接一张表、或者 tv-sync 停了几天
    # 再补, 一批旧笔记会同时拿到很新的 matched_at, 被当成"这周发的"(codex review on aw#109, 同一个坑)。
    # until_iso: 排期还没发的(publish_time 在未来)不算。
    q = (sb.schema("truth_vault").table("notes")
         .select("note_id, project_id, publish_time")
         .gte("publish_time", since_iso))
    if until_iso:
        q = q.lte("publish_time", until_iso)
    notes = fetch_all_pages(q, order_by="note_id")
    tv_ids = {m["tv_project_id"] for m in maps}
    note_ids = [n["note_id"] for n in notes if n.get("project_id") in tv_ids]
    links: list[dict] = []
    for i in range(0, len(note_ids), 200):
        links.extend((sb.schema("autowriter").table("tv_note_links")
                      .select("note_id, tv_project_id, match_kind")
                      .in_("note_id", note_ids[i:i + 200]).execute()).data or [])
    used = fetch_all_pages(
        sb.schema("autowriter").table("angle_ledger")
        .select("id, project_id")
        .gte("drawn_at", used_since_iso),
        order_by="id")

    by_tv: dict[str, list] = {}
    for m in maps:
        by_tv.setdefault(m["tv_project_id"], []).append(m["project_id"])
    counts: dict[str, dict] = {}
    for l in links:
        c = counts.setdefault(l.get("tv_project_id") or "?", {"ingested": 0, "caught": 0})
        if l.get("match_kind") == INGESTED_KIND:
            c["ingested"] += 1
        elif l.get("match_kind") in CAUGHT_KINDS:
            c["caught"] += 1
    pids = {p for ps in by_tv.values() for p in ps}
    return {"map": by_tv, "links": counts, "used": {u["project_id"] for u in used} & pids}


def _project_names(sb, pids: set) -> dict:
    pids = [p for p in pids if p]
    out: dict[str, str] = {}
    for i in range(0, len(pids), 200):
        rows = (sb.schema("autowriter").table("projects")
                .select("id, name").in_("id", pids[i:i + 200]).execute()).data or []
        for r in rows:
            out[r["id"]] = r.get("name") or r["id"]
    return out


def selftest() -> int:
    """判据 C 的自检(判据 A / B 的在 ci.yml 那一步的 heredoc 里)。不连库; 反证靠改坏输入。"""
    import contextlib
    import io
    import types

    P = lambda drawn, drafts: {"name": "x", "drawn": drawn, "consumed": drafts,  # noqa: E731
                               "drafts": drafts, "with_key": drafts}   # A / B 都不该响, 只看 C

    def pub(links, used=("d1", "h1", "s1"), mp=None):
        return {"map": mp or {"TUGE": ["d1", "d2"], "HATH": ["h1"], "SPX": ["s1"]},
                "links": links, "used": set(used)}

    # 10-12 那周的真实形状: 途鸽 22 / 0 写作台零动静、Hatherine 23 / 1 发牌 21 存 1、sportsix 12 / 18
    week = pub({"TUGE": {"ingested": 22, "caught": 0}, "HATH": {"ingested": 23, "caught": 1},
                "SPX": {"ingested": 12, "caught": 18}})
    desk = {"h1": P(21, 1), "s1": P(33, 33)}
    got = {h["project"]: h["kind"] for h in verdicts_publish(desk, week)}
    assert got == {"TUGE": "desk_silent", "HATH": "published_unsaved"}, got
    # 下限真的在起作用: 补录差一篇、或对上多一篇, 都不喊
    edge = lambda ing, caught: verdicts_publish({}, pub({"TUGE": {"ingested": ing, "caught": caught}}))  # noqa: E731
    assert [h["kind"] for h in edge(MIN_UNCAUGHT, MAX_CAUGHT)] == ["desk_silent"]
    assert edge(MIN_UNCAUGHT - 1, 0) == [], "补录低于 MIN_UNCAUGHT 不该喊"
    assert edge(MIN_UNCAUGHT, MAX_CAUGHT + 1) == [], "对上多于 MAX_CAUGHT 不该喊"
    # 近 USED_WITHIN_DAYS 天没用过写作台的项目本来就不在写作台写: 不喊(否则天天红, D-053)
    assert verdicts_publish({}, pub({"TUGE": {"ingested": 50, "caught": 0}}, used=())) == []
    # 映射到多个写作台项目时, 用过 / 有动静按整组算: d2 发了牌就不是「没收到调用」
    assert [h["kind"] for h in verdicts_publish({"d2": P(3, 0)}, week)
            if h["project"] == "TUGE"] == ["published_unsaved"]

    def run(stats):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = report(stats, 7)
        return rc, buf.getvalue()

    # 一张牌都没发的那一周: A / B 无从判定, C 照样要喊 —— 途鸽就是这么藏了一个月的
    rc, out = run({"by_project": {}, "ingested_skipped": 0, "publish": week})
    assert rc == 1 and "无从判定" in out and "TUGE" in out and "没接住" in out, out
    assert "HATH" in out and "SPX" in out, "发帖对账表要列出所有有新笔记的 TV 项目"
    rc, out = run({"by_project": {}, "ingested_skipped": 0})
    assert rc == 0, "没有 publish 的老调用方式不变"
    rc, out = run({"by_project": desk, "ingested_skipped": 0,
                   "publish": pub({"SPX": {"ingested": 12, "caught": 18}})})
    assert rc == 0 and "没接住" not in out, out

    # ── gather_publish: 按 match_kind 分、翻页键唯一、只认映射里的项目 ──────────────
    class _Q:
        def __init__(self, rows): self.rows, self.f = rows, []
        def select(self, *a, **k): return self
        def gte(self, k, v): self.f.append(lambda r: r[k] >= v); return self
        def lte(self, k, v): self.f.append(lambda r: r[k] <= v); return self
        def in_(self, k, vs): self.f.append(lambda r: r[k] in set(vs)); return self
        def execute(self): return types.SimpleNamespace(data=[r for r in self.rows if all(f(r) for f in self.f)])

    INWIN, OLD, LATER = "2026-10-14T08:00:00", "2026-09-20T08:00:00", "2026-10-21T08:00:00"
    note = lambda nid, tv, kind, pt: ({"note_id": nid, "project_id": tv, "publish_time": pt},  # noqa: E731
                                      {"note_id": nid, "tv_project_id": tv, "match_kind": kind,
                                       "matched_at": "2026-10-19T04:00:00"})   # 全都是刚连上的 —— 窗口不该按它切
    ROWS = ([note(f"t{i:02d}", "TUGE", "ingested", INWIN) for i in range(22)]
            + [note("t-amb", "TUGE", "ambiguous", INWIN), note("t-un", "TUGE", "unmatched", INWIN),
               note("h1", "HATH", "fuzzy", INWIN), note("h2", "HATH", "tv_lineage", INWIN)]
            + [note(f"old{i:02d}", "TUGE", "ingested", OLD) for i in range(30)]       # 新接表 / 补跑
            + [note(f"sch{i}", "TUGE", "ingested", LATER) for i in range(5)]          # 排期还没发
            + [note("zz1", "NOT_MAPPED", "ingested", INWIN)])
    NOTES, LINKS = [n for n, _ in ROWS], [l for _, l in ROWS]
    LEDGER = [{"id": "a1", "project_id": "d1", "drawn_at": "x"}, {"id": "a2", "project_id": "d1", "drawn_at": "x"},
              {"id": "a3", "project_id": "zz-unmapped", "drawn_at": "x"}]

    class SB:
        def __init__(self): self.s = None
        def schema(self, s): self.s = s; return self
        def table(self, t):
            return _Q({"tv_project_map": [{"tv_project_id": "TUGE", "project_id": "d1"},
                                          {"tv_project_id": "TUGE", "project_id": "d2"},
                                          {"tv_project_id": "HATH", "project_id": "h1"}],
                       "notes": NOTES, "tv_note_links": LINKS, "angle_ledger": LEDGER}[t])

    def _pages(q, order_by=None):
        rows, seen = [], set()                       # 照抄真 fetch_all_pages 的去重语义
        for r in q.execute().data:
            assert order_by in r, f"order_by={order_by!r} 不在 select 里"
            if r[order_by] not in seen:
                seen.add(r[order_by])
                rows.append(r)
        return rows

    saved = sys.modules.get("_common")
    fake = types.ModuleType("_common")
    fake.fetch_all_pages = _pages
    sys.modules["_common"] = fake
    try:
        g = gather_publish(SB(), "2026-10-12T00:00:00", "2026-08-20T00:00:00", until_iso="2026-10-19T08:00:00")
        assert g["map"] == {"TUGE": ["d1", "d2"], "HATH": ["h1"]}, g["map"]
        assert g["links"] == {"TUGE": {"ingested": 22, "caught": 0},
                              "HATH": {"ingested": 0, "caught": 2}}, g["links"]
        assert g["used"] == {"d1"}, "没映射的写作台项目不进 used"
        # 反证: 不传 until → 排期的 5 篇算进来; 窗口拉到 9 月 → 旧的 30 篇算进来 —— 窗口确实是 publish_time
        assert gather_publish(SB(), "2026-10-12T00:00:00", "2026-08-20T00:00:00")["links"]["TUGE"]["ingested"] == 27
        assert gather_publish(SB(), "2026-09-01T00:00:00", "2026-08-20T00:00:00",
                              until_iso="2026-10-19T08:00:00")["links"]["TUGE"]["ingested"] == 52
        assert [h["project"] for h in verdicts_publish({}, g)] == ["TUGE"]

        # main 接线: 两份数都取、哨兵行在
        fake.get_supabase_client = lambda: object()
        real = globals()["gather"], globals()["gather_publish"]
        globals()["gather"] = lambda sb, since: {"by_project": {}, "ingested_skipped": 0}
        globals()["gather_publish"] = lambda sb, since, used, **kw: week
        argv, sys.argv = sys.argv, ["check_angle_ledger_leak.py"]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rc = main()
        finally:
            sys.argv = argv
            globals()["gather"], globals()["gather_publish"] = real
        assert rc == 1 and "ANGLE_LEDGER_CHECK_DONE rc=1" in buf.getvalue(), buf.getvalue()
    finally:
        if saved is None:
            sys.modules.pop("_common", None)
        else:
            sys.modules["_common"] = saved
    print("  ✓ 判据 C: 途鸽 / Hatherine 两种形状分开报、下限在、没用过写作台的不喊、一张牌没发也照喊、取数翻页键唯一")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS,
                        help=f"看过去多少天的发牌与成稿(默认 {DEFAULT_WINDOW_DAYS})")
    parser.add_argument("--selftest", action="store_true", help="CI: 判据 C 的自检, 不连库")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if args.window_days < 1:
        print("--window-days 必须 >= 1")
        return 2
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=args.window_days)).replace(tzinfo=None).isoformat(timespec="seconds")
    used_since = ((now - timedelta(days=max(USED_WITHIN_DAYS, args.window_days)))
                  .replace(tzinfo=None).isoformat(timespec="seconds"))

    from _common import get_supabase_client  # 局部 import, 理由见文件头
    sb = get_supabase_client()
    stats = gather(sb, since)
    stats["publish"] = gather_publish(sb, since, used_since,
                                      until_iso=now.replace(tzinfo=None).isoformat(timespec="seconds"))
    rc = report(stats, args.window_days)
    # ⚠️ 哨兵行: daily-sync.yml 靠它区分"跑完了"和"崩了"(那边是 `|| true` 调的)。
    print(f"ANGLE_LEDGER_CHECK_DONE rc={rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
