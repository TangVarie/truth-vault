"""
check_desk_use_rate.py
═══════════════════════════════════════════════════════════════════════════

写作台用上率: 每个项目发出去的帖里, 有多少是写作台出的稿、其中多少原样发了? —— 只读, 不写库。每周一跑。

2026-10-20 生产诊断(docs/32 §1): 写作台的稿子短、彼此像, 大多在飞书里被人整篇重写 —— 写作台存的稿最后
发出去的只有 23–45%, 有一个项目是 0。写作台自己量不出这件事: 参考分 79 篇全是 100, 而「被重写」发生在
飞书里、写作台之外。第一批 / 第二批(docs/32)改的是写作台出稿; 这盏灯从【发出去的帖】那一侧看它们有没有用。

口径(按 TV 项目算; 写作台项目经 autowriter.tv_project_map 归到 TV 项目下):
  发布   = truth_vault.notes 里 publish_time 落在窗口内的笔记(只取 id 和时间, 不读正文)
  对过账 = 其中在 autowriter.tv_note_links 里有一行的(tv-sync 每晚给映射项目的每篇都写一行, 正常等于发布)
  接住   = match_kind ∈ {body_exact, title_exact, fuzzy, edited, tv_lineage} 且 lag_days 为空或 >= 0。
           写作台那版晚于发布的, 是发出去之后抄回写作台的, 不算接住(首晚 440 条对上里 212 条是这种;
           同角度台账灯判据 C、aw desk_gap)。ambiguous / unmatched / ingested 都不算。
  未改动 = 接住的里面, autowriter.tv_edit_diffs 有一行 diff_rev >= 2 且 changed = false。
           分母是「接住且算过当前口径差异」的 —— 没算过的(每晚补算有上限、那一版没存正文)不知道改没改,
           不能当成改过。diff_rev 2 的行要等 10-20 写作台部署 + 当晚 tv-sync 重算之后才有: 全库一行都没有时
           打「未改动率: 待重算」, 不打数。changed 很严(标题改了、正文差一个字都算), 所以另报改了标题的篇数。

窗口: 发布于 [现在 −21 天, 现在 −7 天]。晚 7 天看: 稿子发出去要等正文进 TV、tv-sync 夜里对上(edited / fuzzy
     更晚), 看最近几天会把「还没对上」读成「没接住」。窗口 14 天: 一周一个项目常常不到 15 篇, 判不了。
     两个数都能调(--window-days / --delay-days)。

判据(rc=1, 🟡): 窗口内在写作台发过牌(autowriter.angle_ledger)、对过账的发布 >= 15 篇、接住率 < 20% 的 TV 项目。
  · 只看发过牌的: 一张牌都没发的项目本来就没在用写作台, 它的没接住归角度台账灯判据 C(写作台零动静),
    这里不重复喊(D-053)。发过牌的项目两盏灯会同时亮: 判据 C 的「连上了、写完没存档」也算发过牌的项目。两边
    读的是同一批 tv_note_links, 光凭链接分不清「没存档」和「被重写」(两种都是补录副本), 分开它们要看写作台
    这段时间存没存这个项目的稿 —— 判据 C 那张表的「真稿」列。亮黄的报文里点明这一句;
  · 15 篇是比例能不能读的样本下限, 不随窗口放大(它管的是一个比例有几个分母, 不是一周该发多少);
  · 分母用对过账的, 不用发布数: 没对过账的不知道是不是写作台的稿, 当成没接住会在 tv-sync 某晚失败时冒假黄。
rc=2: 判不了 —— 映射的 TV 项目窗口内一篇都没发, 或发了但一条链接都没有(tv-sync 没对过账); 或者【某一个】项目
     发布 >= 15 篇、对过账的不到八成(tv-sync 漏了这个项目: aw 的 tv-sync 一个项目出错只记一行、接着跑别的,
     别的项目照常对账, 全局合计看不出来)。这种项目点名报; 别的项目照常判, 有项目亮黄时 rc 仍是 1。

红了修在 autowriter 仓(写作台出稿质量: TV docs/32 第一批 / 第二批), TV 这边改不好。advisory, 不拖红。

用法:
    python check_desk_use_rate.py                         # 默认: 发布于 21 天前 ~ 7 天前
    python check_desk_use_rate.py --window-days 28 --delay-days 7
    python check_desk_use_rate.py --selftest              # CI: 判据 / 口径 / 取数 / 接线, 不连库

退出码:
    0 = 没有项目命中判据(或有数但没有项目够格判)
    1 = 至少一个项目命中 —— 修在 autowriter 仓
    2 = 判不了(没发布 / 没对过账 / 某个项目大多没对过账), 且没有项目命中
⚠️ 同 check_angle_ledger_leak.py 的约定: 正常跑完末尾必打一行 `DESK_USE_RATE_CHECK_DONE rc=<码>`;
daily-sync.yml 靠有没有这一行判定崩溃, 不靠退出码。
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

# ⚠️ 故意【不】在模块顶层 import _common(会拖进 supabase / yaml): tally / report 是纯函数,
# --selftest 在 CI 的裸环境里直接测它们 —— 同 check_angle_ledger_leak.py 的理由。

DEFAULT_WINDOW_DAYS = 14
DEFAULT_DELAY_DAYS = 7
# 判据下限(10-20 定): 10-12 那周全部映射项目发布 156 篇、接住 29 篇(19%), 之前三周 1–3%。
# 20% 是「写作台在用、发出去的帖五篇里不到一篇是它的稿」—— 比这还低, 写作台就只是个摆设。
MIN_PUBLISHED = 15
MIN_CAUGHT_SHARE = 0.20
# 对过账 / 发布 低于这个数 = tv-sync 漏了这个项目。tv-sync 给映射项目的每篇都写一行(没正文的记 unmatched、对不上的
# 补录成 ingested), 正常两者相等; 留两成余量给当晚刚进 TV、还没轮到对账的。只看发布 >= MIN_PUBLISHED 的项目。
MIN_LINKED_SHARE = 0.8
# 改动差异的当前口径(aw deskcore/tvlink.py DIFF_REV): 2 = 话题行两边都剥、写作台那版晚于发布的不算(10-20)。
# 旧口径的行(0 / 1)把话题行算成"人删了一句"、把抄回去的副本算成"人改过", 不能拿来算未改动。
CURRENT_DIFF_REV = 2
# 对上写作台存档的几种(tv-sync 的 match_kind)。同 check_angle_ledger_leak.CAUGHT_KINDS、aw _TV_BACKFILL_KINDS。
CAUGHT_KINDS = frozenset({"body_exact", "title_exact", "fuzzy", "edited", "tv_lineage"})
CHUNK = 200     # .in_() 走 URL, 约 26 KB 撞线(D-080), 一批 ≤200 个 id


def is_caught(link: dict) -> bool:
    """这篇是不是从写作台出来的: 对上了, 且写作台那版不晚于发布。"""
    lag = link.get("lag_days")
    return link.get("match_kind") in CAUGHT_KINDS and (lag is None or lag >= 0)


def tally(g: dict) -> dict:
    """gather() 的原始行 → 每个 TV 项目一格。纯函数 —— CI 直接喂假数测它。

    ``g``: ``{"map": {tv: [写作台 project_id…]}, "names": {project_id: 名字}, "notes": [{note_id, project_id}],
    "links": {note_id: tv_note_links 行}, "diffs": {note_id: tv_edit_diffs 行}, "drawn": {project_id: 窗口内发牌数}}``。
    窗口内一篇都没发的 TV 项目不出现在结果里。
    """
    rows: dict[str, dict] = {}
    for tv, pids in (g.get("map") or {}).items():
        rows[tv] = {"published": 0, "linked": 0, "caught": 0, "diffed": 0, "unchanged": 0, "title_changed": 0,
                    "drawn": sum((g.get("drawn") or {}).get(p, 0) for p in pids),
                    "desk": sorted({(g.get("names") or {}).get(p) or p for p in pids})}
    links, diffs = g.get("links") or {}, g.get("diffs") or {}
    for n in g.get("notes") or []:
        r = rows.get(n.get("project_id"))
        if r is None:
            continue                    # 没映射写作台的 TV 项目: 本来就不在写作台写, 不算
        r["published"] += 1
        link = links.get(n["note_id"])
        if link is None:
            continue
        r["linked"] += 1
        if not is_caught(link):
            continue
        r["caught"] += 1
        d = diffs.get(n["note_id"])
        if d is None or (d.get("diff_rev") or 0) < CURRENT_DIFF_REV:
            continue                    # 没算过当前口径的差异: 不知道改没改, 不进未改动的分母
        r["diffed"] += 1
        r["unchanged"] += int(d.get("changed") is False)
        r["title_changed"] += int(bool(d.get("title_changed")))
    return {tv: r for tv, r in rows.items() if r["published"]}


def verdicts(rows: dict) -> list[dict]:
    """哪些 TV 项目在用写作台、发出去的帖却大多不是写作台的稿。纯函数。"""
    out = []
    for tv, r in sorted(rows.items()):
        if r["drawn"] <= 0 or r["linked"] < MIN_PUBLISHED:
            continue
        if r["linked"] < r["published"] * MIN_LINKED_SHARE:
            # 对过账不到八成的归 unlinked()「判不了」: 只对上一小部分时, 接住率是偏的子集, 不能再同时喊「没被用上」
            # 把人往出稿质量上引(codex review on TV#208)
            continue
        share = r["caught"] / r["linked"]
        if share < MIN_CAUGHT_SHARE:
            out.append({"project": tv, "share": share, "linked": r["linked"], "caught": r["caught"],
                        "drawn": r["drawn"],
                        "detail": f"对过账 {r['linked']} 篇、接住 {r['caught']} 篇({share:.0%}), "
                                  f"窗口内写作台发牌 {r['drawn']}"})
    return out


def unlinked(rows: dict) -> list[dict]:
    """哪些 TV 项目发了不少帖、tv-sync 却大多没对过账(判不了)。纯函数。

    全局「一条链接都没有」那道 rc=2 管不到这种: aw 的 tv-sync 逐个项目跑, 一个项目出错只记一行、接着跑别的,
    别的项目照常对账, 合计的对过账 > 0; 这个项目在 verdicts() 里因为对过账不到下限被安静地跳过。
    """
    out = []
    for tv, r in sorted(rows.items()):
        if r["published"] >= MIN_PUBLISHED and r["linked"] < r["published"] * MIN_LINKED_SHARE:
            out.append({"project": tv, "published": r["published"], "linked": r["linked"],
                        "detail": f"发布 {r['published']} 篇、对过账 {r['linked']} 篇"})
    return out


def _pct(a: int, b: int) -> str:
    return f"{a / b:.0%}" if b else "—"


def _unchanged_cell(r: dict, any_rev: bool) -> str:
    if not r["caught"]:
        return "—"
    if not any_rev or not r["diffed"]:
        return "待重算"
    return f"{r['unchanged']}/{r['diffed']}"


def _warn(title: str, msg: str) -> None:
    print(f"  ⚠ {msg}")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::warning title={title}::{msg}", flush=True)


def report(g: dict, window_days: int, delay_days: int) -> int:
    """把 gather() 的行渲染成报告并返回退出码。纯函数, 不碰网络。"""
    rows = tally(g)
    any_rev = bool(g.get("any_rev2"))
    pub = sum(r["published"] for r in rows.values())
    linked = sum(r["linked"] for r in rows.values())
    caught = sum(r["caught"] for r in rows.values())
    diffed = sum(r["diffed"] for r in rows.values())
    unchanged = sum(r["unchanged"] for r in rows.values())
    span = f"{(g.get('since') or '')[5:10]} ~ {(g.get('until') or '')[5:10]}"
    rate = (f"未改动率 {unchanged}/{diffed}({_pct(unchanged, diffed)})" if any_rev and diffed
            else "未改动率: 待重算")

    print()
    print("=" * 96)
    print(f"  写作台用上率 · 发布于 {span}(晚 {delay_days} 天看, 窗口 {window_days} 天) · 发布 {pub} · "
          f"对过账 {linked} · 接住 {caught}({_pct(caught, linked)}) · {rate}")
    print("=" * 96)
    if not any_rev:
        print(f"  · tv_edit_diffs 里还没有 diff_rev >= {CURRENT_DIFF_REV} 的行(10-20 写作台部署后当晚 tv-sync 才重算)"
              " —— 旧口径把话题行和抄回去的副本都算成改过, 不拿它算未改动")
    if rows:
        print(f"  {'TV 项目':<20}{'发布':>6}{'对过账':>7}{'接住':>6}{'接住率':>7}{'未改动':>9}{'改标题':>7}"
              f"{'发牌':>6}  写作台项目")
        for tv, r in sorted(rows.items(), key=lambda kv: (-kv[1]["published"], kv[0])):
            title = str(r["title_changed"]) if any_rev and r["diffed"] else "—"
            print(f"  {tv[:19]:<20}{r['published']:>6}{r['linked']:>7}{r['caught']:>6}"
                  f"{_pct(r['caught'], r['linked']):>7}{_unchanged_cell(r, any_rev):>9}{title:>7}"
                  f"{r['drawn']:>6}  {'、'.join(r['desk'])[:40]}")
        print(f"  接住 = 对上写作台发布前存的那版; 未改动 = 接住且算过差异的里面原样发的(标题、正文一个字没动); "
              f"改标题 = 其中标题动过的。判据: 发过牌、对过账 >= {MIN_PUBLISHED} 篇、接住率 < {MIN_CAUGHT_SHARE:.0%}")

    if not pub:
        _warn("写作台用上率判不了", f"映射了写作台的 TV 项目在 {span} 一篇都没发 —— 先看 daily-sync 的飞书入库"
              "和 tv_project_map(这盏灯本身没坏, 是没有可看的帖)。")
        return 2
    if not linked:
        _warn("写作台用上率判不了", f"{span} 发布 {pub} 篇, tv_note_links 里一行都没有 —— tv-sync 没对过账"
              "(aw 的 tv-sync 定时, 见 aw deskcore-runbook), 修好之前这盏灯是瞎的。")
        return 2

    blind = unlinked(rows)
    if blind:
        _warn("写作台用上率有项目判不了",
              f"{span} 有 {len(blind)} 个项目发出去的帖大多没对过账: "
              + "; ".join(f"{b['project']}({b['detail']})" for b in blind)
              + " —— tv-sync 漏了这几个项目(对过账正常等于发布; aw 的 tv-sync 一个项目出错只记一行、接着跑别的,"
                " 看 aw tv-sync 定时的日志里这几个项目的 ❌, 见 aw deskcore-runbook)。修好之前这几个项目的接住率"
                "没法读, 角度台账灯判据 C 对它们也是瞎的。当天才接进 TV 的项目等当晚 tv-sync 之后再看。")
    blind_rc = 2 if blind else 0
    blind_note = "(上面判不了的项目不在内)" if blind else ""

    if not any(r["drawn"] > 0 and r["linked"] >= MIN_PUBLISHED for r in rows.values()):
        print(f"  · 没有项目够格判: 窗口内在写作台发过牌、对过账又够 {MIN_PUBLISHED} 篇的项目一个都没有"
              f"(不是健康, 是没活或量太小; 发了帖、写作台零动静的看角度台账灯判据 C){blind_note}")
        return blind_rc
    hits = verdicts(rows)
    if not hits:
        print(f"  ✓ 没有项目命中: 在写作台发过牌、对过账够 {MIN_PUBLISHED} 篇的项目, 发出去的帖至少 "
              f"{MIN_CAUGHT_SHARE:.0%} 是写作台的稿{blind_note}")
        return blind_rc
    _warn("写作台的稿没被用上",
          f"{span} 发布的帖里, {len(hits)} 个项目在写作台发了牌、发出去的却大多不是写作台的稿: "
          + "; ".join(f"{h['project']}({h['detail']})" for h in hits)
          + " —— 写作台在用、稿子没被用上: 要么写完没存档, 要么存了、在飞书里被整篇重写了(稿短、彼此像、版式不对)。"
            "光看链接分不清这两种, 看写作台这段时间存没存这几个项目的稿: 角度台账灯判据 C 那张表的「真稿」列"
            "(它默认看最近 7 天, 要盖住这里的窗口就手动跑 check_angle_ledger_leak.py --window-days 21)。"
            "真稿接近 0 = 没存档, 判据 C 多半也亮着「连上了、写完没存档」, 先按那边查 score_drafts 存档; "
            "存了不少稿、发出去的仍对不上 = 被重写, 修在 autowriter 仓(写作台出稿质量, TV docs/32 第一批 / 第二批), "
            "先看这几个项目的改稿差异摘要和最近几批稿子长什么样。TV 这边两种都改不好。")
    return 1


def gather(sb, since_iso: str, until_iso: str) -> dict:
    """读 tally() 要的行。只取 id、时间、对照类别和差异的三个标记, 不读任何正文。"""
    from _common import fetch_all_pages  # 局部 import, 理由见文件头

    # tv_project_map 是人工维护的几十行, 一页够(同角度台账灯判据 C)。
    maps = (sb.schema("autowriter").table("tv_project_map")
            .select("tv_project_id, project_id").execute()).data or []
    by_tv: dict[str, list] = {}
    for m in maps:
        by_tv.setdefault(m["tv_project_id"], []).append(m["project_id"])
    # 窗口按 publish_time 切, 不按对照写进去的时间(matched_at): 新接一张表、或 tv-sync 停几天再补, 一批旧笔记会
    # 同时拿到很新的 matched_at(codex review on aw#109, 角度台账灯判据 C 同一个坑)。
    # ⚠️ order_by 必须唯一且在 select 里(fetch_all_pages 按它去重), 所以是 note_id / id, 不是时间列。
    notes = fetch_all_pages(
        sb.schema("truth_vault").table("notes")
        .select("note_id, project_id, publish_time")
        .gte("publish_time", since_iso).lte("publish_time", until_iso),
        order_by="note_id")
    notes = [n for n in notes if n.get("project_id") in by_tv]
    ids = [n["note_id"] for n in notes]
    links: dict[str, dict] = {}
    for i in range(0, len(ids), CHUNK):
        for r in (sb.schema("autowriter").table("tv_note_links")
                  .select("note_id, tv_project_id, project_id, version_id, match_kind, lag_days")
                  .in_("note_id", ids[i:i + CHUNK]).execute()).data or []:
            links[r["note_id"]] = r
    caught_ids = [nid for nid in ids if nid in links and is_caught(links[nid])]
    diffs: dict[str, dict] = {}
    for i in range(0, len(caught_ids), CHUNK):
        for r in (sb.schema("autowriter").table("tv_edit_diffs")
                  .select("note_id, changed, title_changed, diff_rev")
                  .gte("diff_rev", CURRENT_DIFF_REV)
                  .in_("note_id", caught_ids[i:i + CHUNK]).execute()).data or []:
            diffs[r["note_id"]] = r
    # 全库有没有当前口径的行: 没有 = tv-sync 还没按新口径重算过, 未改动率打「待重算」而不是 0。
    any_rev2 = bool((sb.schema("autowriter").table("tv_edit_diffs").select("note_id")
                     .gte("diff_rev", CURRENT_DIFF_REV).limit(1).execute()).data)
    pids = {p for ps in by_tv.values() for p in ps}
    drawn: dict[str, int] = {}
    for a in fetch_all_pages(
            sb.schema("autowriter").table("angle_ledger")
            .select("id, project_id, drawn_at")
            .gte("drawn_at", since_iso).lte("drawn_at", until_iso),
            order_by="id"):
        if a.get("project_id") in pids:
            drawn[a["project_id"]] = drawn.get(a["project_id"], 0) + 1
    return {"map": by_tv, "names": _project_names(sb, pids), "notes": notes, "links": links,
            "diffs": diffs, "drawn": drawn, "any_rev2": any_rev2, "since": since_iso, "until": until_iso}


def _project_names(sb, pids: set) -> dict:
    pids = sorted(p for p in pids if p)
    out: dict[str, str] = {}
    for i in range(0, len(pids), CHUNK):
        for r in (sb.schema("autowriter").table("projects")
                  .select("id, name").in_("id", pids[i:i + CHUNK]).execute()).data or []:
            out[r["id"]] = r.get("name") or r["id"]
    return out


def window(now: datetime, window_days: int, delay_days: int) -> tuple[str, str]:
    """[now − delay − window, now − delay], 无时区 ISO 秒(同角度台账灯的写法)。"""
    until = now - timedelta(days=delay_days)
    since = until - timedelta(days=window_days)
    fmt = (lambda t: t.replace(tzinfo=None).isoformat(timespec="seconds"))  # noqa: E731
    return fmt(since), fmt(until)


def selftest() -> int:
    """判据 / 口径 / 取数 / main 与夜跑接线。不连库; 反证靠改坏输入。"""
    import contextlib
    import io
    import types
    from pathlib import Path

    L = lambda kind, lag=0: {"match_kind": kind, "lag_days": lag}  # noqa: E731
    # ── 接住: 只认对上的五种, 且写作台那版不晚于发布 ───────────────────────────
    assert is_caught(L("body_exact")) and is_caught(L("edited", 3)) and is_caught(L("tv_lineage", None))
    assert not is_caught(L("body_exact", -3)), "发了之后才存进写作台的那版是抄回去的, 不算接住"
    assert not any(is_caught(L(k)) for k in ("ingested", "ambiguous", "unmatched"))

    # ── tally: 一个 TV 项目映射两个写作台项目, 发牌合起来算; 没映射的 TV 项目不进表 ──
    def G(notes, links=None, diffs=None, drawn=None, any_rev2=True):
        return {"map": {"AAA": ["d1", "d2"], "BBB": ["d3"]}, "names": {"d1": "甲台", "d2": "乙台"},
                "notes": notes, "links": links or {}, "diffs": diffs or {}, "drawn": drawn or {},
                "any_rev2": any_rev2, "since": "2026-10-05T08:00:00", "until": "2026-10-19T08:00:00"}

    N = lambda nid, tv="AAA": {"note_id": nid, "project_id": tv}  # noqa: E731
    D = lambda changed, title=False, rev=2: {"changed": changed, "title_changed": title, "diff_rev": rev}  # noqa: E731
    g = G([N("a1"), N("a2"), N("a3"), N("a4"), N("a5"), N("a6"), N("a7"), N("x1", "ZZZ")],
          {"a1": L("body_exact"), "a2": L("fuzzy", 2), "a3": L("edited", None), "a4": L("title_exact", -6),
           "a5": L("ingested", None), "a7": L("edited", 1), "x1": L("body_exact")},
          {"a1": D(False), "a2": D(True, True), "a3": D(False, rev=1), "a4": D(False), "a7": D(True, False)},
          {"d1": 3, "d2": 4, "d3": 9})
    t = tally(g)
    assert set(t) == {"AAA"}, "没映射的 ZZZ 不算; BBB 窗口内一篇没发不出现"
    assert t["AAA"] == {"published": 7, "linked": 6, "caught": 4, "diffed": 3, "unchanged": 1, "title_changed": 1,
                        "drawn": 7, "desk": ["乙台", "甲台"]}, t["AAA"]
    # a4 (lag −6) 不算接住, 它那行 changed=false 也不进未改动; a3 只有旧口径(rev 1)的行 → 不进分母。
    # a7 只改了正文(changed=T、title_changed=F, 最常见的一种): 未改动和改标题各数各的, 不能从同一个标记推出来

    # ── 判据: 下限真的在起作用 ─────────────────────────────────────────────────
    def R(linked, caught, drawn=5):
        return {"P": {"published": linked + 2, "linked": linked, "caught": caught, "diffed": 0, "unchanged": 0,
                      "title_changed": 0, "drawn": drawn, "desk": []}}
    assert [h["project"] for h in verdicts(R(15, 2))] == ["P"], "15 篇接住 2 篇(13%)该喊"
    assert verdicts(R(15, 3)) == [], "正好 20% 不喊"
    assert verdicts(R(14, 0)) == [], "对过账不到 15 篇不判"
    assert verdicts(R(40, 0, drawn=0)) == [], "窗口内一张牌没发的归角度台账灯判据 C, 这里不重复喊"
    # 分母是对过账的、不是发布数: 发了 40 篇、tv-sync 只对过 10 篇, 不能因为没对账就判没接住
    half = {"P": dict(R(10, 0)["P"], published=40)}
    assert verdicts(half) == [], "没对过账的不当成没接住"
    partial = {"P": dict(R(15, 0)["P"], published=100)}
    assert verdicts(partial) == [] and [u["project"] for u in unlinked(partial)] == ["P"], \
        "对过账 15/100: 只报判不了, 不拿偏的子集再喊没接住"

    def run(gg, w=14, d=7):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = report(gg, w, d)
        return rc, buf.getvalue()

    # ── report: 判不了 / 待重算 / 黄 / 通 ─────────────────────────────────────
    rc, out = run(G([]))
    assert rc == 2 and "一篇都没发" in out, out
    rc, out = run(G([N(f"n{i}") for i in range(20)], drawn={"d1": 5}))
    assert rc == 2 and "tv-sync 没对过账" in out, out
    many = [N(f"n{i:02d}") for i in range(20)]
    low = {f"n{i:02d}": L("body_exact" if i < 2 else "unmatched") for i in range(20)}
    rc, out = run(G(many, low, {"n00": D(False)}, {"d2": 3}, any_rev2=False))
    assert rc == 1 and "AAA" in out and "修在 autowriter 仓" in out and "docs/32" in out, out
    assert "未改动率: 待重算" in out and "1/1" not in out, "没有 rev 2 的行时不打未改动的数"
    rc, out = run(G(many, low, {"n00": D(False), "n01": D(True, True)}, {"d2": 3}))
    assert rc == 1 and "未改动率 1/2(50%)" in out, out
    assert "没存档" in out and "真稿" in out and "判据 C" in out, "亮黄要说清怎么和判据 C 的「写完没存档」分开"

    def row_of(out, tv):
        return next(ln.split() for ln in out.splitlines() if ln.startswith(f"  {tv} "))
    for diffs, title in (({"n00": D(False), "n01": D(True, False)}, "0"),      # 只改正文
                         ({"n00": D(False), "n01": D(True, True)}, "1")):      # 标题也改了
        rc, out = run(G(many, low, diffs, {"d2": 3}))
        cols = row_of(out, "AAA")       # TV 项目 发布 对过账 接住 接住率 未改动 改标题 发牌 写作台项目
        assert cols[5] == "1/2" and cols[6] == title, (title, cols)
    ok = {f"n{i:02d}": L("fuzzy", 1) for i in range(20)}
    rc, out = run(G(many, ok, {}, {"d1": 1}))
    assert rc == 0 and "✓" in out and "没被用上" not in out and "待重算" in out, out   # 接住了、差异还没算
    rc, out = run(G(many, low, {}, {}))
    assert rc == 0 and "没有项目够格判" in out and "没被用上" not in out, "没发过牌的项目接住再低也不喊"

    # ── 一个项目的 tv-sync 坏了、别的照常: 合计对过账 > 0, 那个项目要点名报判不了(rc=2), 不能安静跳过 ──
    bbb = [N(f"b{i:02d}", "BBB") for i in range(20)]
    rc, out = run(G(many + bbb, ok, {}, {"d1": 1, "d3": 5}))
    assert rc == 2 and "BBB(发布 20 篇、对过账 0 篇)" in out and "tv-sync 漏了" in out and "AAA(" not in out, out
    assert "✓" in out and "判不了的项目不在内" in out, "AAA 照常判"
    rc, out = run(G(many + bbb, ok, {}, {"d3": 5}))
    assert rc == 2 and "没有项目够格判" in out and "BBB(" in out, "BBB 发过牌但没对过账: 不能落进「没有项目够格判」rc=0"
    part = dict(ok, **{f"b{i:02d}": L("ingested", None) for i in range(10)})     # 对过一半
    rc, out = run(G(many + bbb, part, {}, {"d1": 1, "d3": 5}))
    assert rc == 2 and "BBB(发布 20 篇、对过账 10 篇)" in out, out
    rc, out = run(G(many + bbb, low, {}, {"d1": 1, "d3": 5}))
    assert rc == 1 and "BBB(" in out and "没被用上" in out, "有项目亮黄时 rc 仍是 1, 判不了的照样点名"
    rc, out = run(G(many + bbb[:14], ok, {}, {"d1": 1, "d3": 5}))
    assert rc == 0 and "BBB(" not in out, "发布不到 15 篇的项目不点名(量太小)"
    rc, out = run(G(many + bbb, dict(ok, **{f"b{i:02d}": L("fuzzy", 1) for i in range(16)}),
                    {}, {"d1": 1, "d3": 5}))
    assert rc == 0 and "判不了" not in out, "对过账八成(16/20)算正常"

    # ── gather: 窗口按 publish_time、只取映射项目、in_ 分批、差异只认当前口径、翻页键唯一 ──
    calls: list[tuple] = []

    class _Q:
        def __init__(self, t, rows): self.t, self.rows, self.f, self.lim = t, rows, [], None
        def select(self, *a, **k): return self
        def gte(self, k, v): self.f.append(lambda r: r[k] >= v); return self
        def lte(self, k, v): self.f.append(lambda r: r[k] <= v); return self
        def limit(self, n): self.lim = n; return self
        def in_(self, k, vs):
            calls.append((self.t, len(vs)))
            self.f.append(lambda r, s=set(vs): r[k] in s)
            return self
        def execute(self):
            rows = [r for r in self.rows if all(f(r) for f in self.f)]
            return types.SimpleNamespace(data=rows[:self.lim] if self.lim is not None else rows)

    INWIN, OLD, LATER = "2026-10-12T08:00:00", "2026-09-20T08:00:00", "2026-10-20T08:00:00"
    NOTES = ([{"note_id": f"a{i:03d}", "project_id": "AAA", "publish_time": INWIN} for i in range(230)]
             + [{"note_id": "old1", "project_id": "AAA", "publish_time": OLD},
                {"note_id": "late1", "project_id": "AAA", "publish_time": LATER},
                {"note_id": "z1", "project_id": "ZZZ", "publish_time": INWIN}])
    LINKS = ([{"note_id": f"a{i:03d}", "tv_project_id": "AAA", "project_id": "d1", "version_id": f"v{i}",
               "match_kind": "body_exact" if i < 210 else "unmatched", "lag_days": 1 if i else -2}
              for i in range(230)]
             + [{"note_id": n, "tv_project_id": t, "project_id": "d1", "version_id": "vx",
                 "match_kind": "body_exact", "lag_days": 0} for n, t in (("old1", "AAA"), ("late1", "AAA"),
                                                                          ("z1", "ZZZ"))])
    DIFFS = [{"note_id": "a001", "changed": False, "title_changed": False, "diff_rev": 2},
             {"note_id": "a002", "changed": False, "title_changed": False, "diff_rev": 1},
             {"note_id": "a205", "changed": True, "title_changed": True, "diff_rev": 2},
             {"note_id": "old1", "changed": False, "title_changed": False, "diff_rev": 2}]
    LEDGER = [{"id": f"g{i}", "project_id": p, "drawn_at": at}
              for i, (p, at) in enumerate([("d1", INWIN), ("d1", INWIN), ("d1", OLD), ("d1", LATER),
                                            ("dx", INWIN)])]
    # d1 那张 LATER(窗口之后才发)的牌不能算: 最近 7 天才开始发牌的项目, 不能拿 7~21 天前它不可能写的帖判它
    TABLES = {"tv_project_map": [{"tv_project_id": "AAA", "project_id": "d1"}],
              "notes": NOTES, "tv_note_links": LINKS, "tv_edit_diffs": DIFFS, "angle_ledger": LEDGER,
              "projects": [{"id": "d1", "name": "甲台"}]}

    class SB:
        def schema(self, s): return self
        def table(self, t): return _Q(t, TABLES[t])

    def _pages(q, order_by=None):
        rows, seen = [], set()                        # 照抄真 fetch_all_pages 的去重语义
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
        gg = gather(SB(), "2026-10-05T08:00:00", "2026-10-19T08:00:00")
        assert [n["note_id"] for n in gg["notes"]] == [f"a{i:03d}" for i in range(230)], \
            "窗口外的(9 月的、排期还没发的)和没映射的 ZZZ 都不该进来"
        assert all(n <= CHUNK for _, n in calls) and ("tv_note_links", 30) in calls, calls
        assert set(gg["diffs"]) == {"a001", "a205"}, "差异只取接住的、当前口径的(a002 是 rev 1, old1 在窗口外)"
        assert gg["drawn"] == {"d1": 2} and gg["any_rev2"] is True and gg["names"] == {"d1": "甲台"}, gg["drawn"]
        tt = tally(gg)["AAA"]
        assert (tt["published"], tt["linked"], tt["caught"], tt["diffed"], tt["unchanged"]) == (230, 230, 209, 2, 1), tt
        # a000 的写作台那版晚于发布(lag −2): 不算接住 —— 209 而不是 210
        TABLES["tv_edit_diffs"] = [d for d in DIFFS if d["diff_rev"] < 2]
        assert gather(SB(), "2026-10-05T08:00:00", "2026-10-19T08:00:00")["any_rev2"] is False

        # ── main: 窗口 = [now−delay−window, now−delay]; 哨兵行; 取数崩了不打哨兵 ──
        since, until = window(datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc), 14, 7)
        assert (since, until) == ("2026-10-05T08:00:00", "2026-10-19T08:00:00"), (since, until)
        fake.get_supabase_client = lambda: object()
        real = globals()["gather"]
        seen_args: list = []
        globals()["gather"] = lambda sb, s, u: (seen_args.append((s, u)),
                                                G(many, low, {}, {"d1": 9}))[1]
        argv = sys.argv
        try:
            sys.argv = ["check_desk_use_rate.py"]
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main()
            assert rc == 1 and "DESK_USE_RATE_CHECK_DONE rc=1" in buf.getvalue(), buf.getvalue()
            s, u = seen_args[-1]
            gap = datetime.fromisoformat(u) - datetime.fromisoformat(s)
            assert gap == timedelta(days=DEFAULT_WINDOW_DAYS), (s, u)
            assert datetime.now(timezone.utc).replace(tzinfo=None) - datetime.fromisoformat(u) >= \
                timedelta(days=DEFAULT_DELAY_DAYS) - timedelta(minutes=1), "窗口没往前推 delay 天"

            def boom(sb, s, u):
                raise RuntimeError("PostgREST down")
            globals()["gather"] = boom
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    main()
            except RuntimeError:
                pass
            else:
                raise AssertionError("取数崩了不该被吞")
            assert "DESK_USE_RATE_CHECK_DONE" not in buf.getvalue(), "崩了还打哨兵 → daily-sync 会以为跑完了"
        finally:
            sys.argv = argv
            globals()["gather"] = real
    finally:
        if saved is None:
            sys.modules.pop("_common", None)
        else:
            sys.modules["_common"] = saved

    # ── 夜跑接线: 真的在调它、哨兵前缀一致、只在周一(北京)和手动时跑、不自己传窗口 ──
    wf = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "daily-sync.yml").read_text(encoding="utf-8")
    i = wf.find("python check_desk_use_rate.py")
    assert i > 0, "夜跑没接这道检查"
    step = wf[wf.rfind("- name:", 0, i):wf.find("- name:", i)]
    assert "DESK_USE_RATE_CHECK_DONE rc=" in step, "daily-sync 的哨兵 grep 和脚本不一致"
    assert "TZ=Asia/Shanghai date +%u" in step and "workflow_dispatch" in step, "要每周一跑、手动触发照跑"
    assert "--window-days" not in step and "--delay-days" not in step, "夜跑不该自己传窗口 —— 默认值由脚本钉着"
    assert "set +e" in step, "advisory: 脚本 rc=1/2 不能把这一步判红"
    print("  ✓ 写作台用上率灯: 接住只认发布前那版 / 未改动只认 diff_rev ≥2 且没有时打待重算 / 下限与分母 / "
          "判不了 rc=2 / 取数窗口按 publish_time、分批、翻页键唯一 / 哨兵行 / 每周一接线")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[4])
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS,
                        help=f"看多少天里发布的笔记(默认 {DEFAULT_WINDOW_DAYS})")
    parser.add_argument("--delay-days", type=int, default=DEFAULT_DELAY_DAYS,
                        help=f"窗口往前推几天, 给 tv-sync 留对上的时间(默认 {DEFAULT_DELAY_DAYS})")
    parser.add_argument("--selftest", action="store_true", help="CI: 自检, 不连库")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if args.window_days < 1 or args.delay_days < 0:
        print("--window-days 必须 >= 1, --delay-days 必须 >= 0")
        return 2
    since, until = window(datetime.now(timezone.utc), args.window_days, args.delay_days)

    from _common import get_supabase_client  # 局部 import, 理由见文件头
    rc = report(gather(get_supabase_client(), since, until), args.window_days, args.delay_days)
    # ⚠️ 哨兵行: daily-sync.yml 靠它区分"跑完了"和"崩了"(那边是 set +e 调的)。
    print(f"DESK_USE_RATE_CHECK_DONE rc={rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
