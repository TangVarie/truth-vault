"""
check_angle_ledger_leak.py
═══════════════════════════════════════════════════════════════════════════

飞书上已经发出去的帖, 有几篇对不回写作台? —— 只读, 不写库。

2026-10-29 起这盏灯只报这一件事(TV OPEN-ITEMS W-38, D-132)。写手没有「存档」这一步(D-120): 稿子写完贴进飞书,
写作台每天按内容把飞书的帖对回写作台的稿(aw tv-sync)。W-38 之前写作台的稿只在模型调了 score_drafts 时才进库,
这盏灯就拿「发了牌、牌没销」去猜「写了没存档」(判据 A, W-29), 把系统的缺口说成了写手漏了一步。W-38 起 aw 在查重
(check_drafts, 每篇必过)时就记下底稿, tv-sync 对不上写作台版本的帖再拿底稿对一次、对上了转成版本 —— 牌销不销只看稿子
有没有发出去被对回来, 「发了牌没销」本来就不是问题(没写出来、写了没发的牌本来就不销), 判据 A 撤了。

现在的判据(只有一条, C; 2026-10-19 O-04 补的那条):
    某 TV 项目窗口内【发出去】的帖(publish_time 在窗口内、飞书里没删的)里, 补录成副本的(tv-sync 记成 ingested ——
    对不回写作台、又不会再重对的终态)>= MIN_UNCAUGHT 篇、对上写作台的 <= MAX_CAUGHT 篇(两个下限按窗口长度等比放大, 每
    7 天一份), 而它对应的写作台项目用过写作台(台账里有过它的牌、或者在写作台查过重, 不限时间) → 发出去的帖对不回写作台。
    红只数补录副本, 和 aw 给写手的 desk_gap 提醒同一个口径; 没对上(unmatched: 没有补录目标的项目、没正文、W-38 这晚没转成
    明晚再试)、分不出(ambiguous: 对上了不止一版, 本来就是写作台的稿)、tv-sync 还没对到的, 只在表里分列。分两种报:
      · 写作台窗口内没查过这个项目一篇稿(draft_snapshots, W-38) → 写它的那几场对话没走到写作台(skill 没被调起来、没开项目
        就写了; WorkBuddy 的写作台连接是全局的, owner 10-19 确认)。018 没跑(没有底稿表)时退回看发牌和稿子;
      · 写作台查过稿, 发出去的帖却对不回 → 改写得太多 / 底稿过期了, 或 aw tv-sync 的底稿那一步出了错(看 tv-sync 日志
        「查重底稿」那一行)。写作台开始记底稿之前发的帖已经补录成副本、改不回来, 单独数出来, 免得第一周白查。
    「对上」只认写作台那版早于发布的(lag_days >= 0 或没记): 发出去之后才进写作台的那版是抄回去的, 不算(全库 440 条对上里
    212 条是这种; DECISIONS 里对上本来就只是「对应版本」, 不是生成来源)。
    这盏灯随夜跑在早上 08~10 时(UTC)跑, 那时飞书当天的帖刚同步进 TV, tv-sync(14:00 UTC)还没对到它们 —— 单列「还没对」。
「用过写作台」那一条是为了不对从来不走写作台的项目天天喊; 不设 60 天之类的期限 —— 断得越久越该喊, 设了期限, 一个断了
两个月的项目反而会自己转绿(codex review on TV#205)。

只报、不喊的(给人看, 不进退出码):
    · 角度台账表: 每个写作台项目窗口内发牌 / 销账 / 稿子 / 带坐标(先排除 tv-sync 的补录副本 —— 它们不是发牌产出的,
      没有坐标; 不排除的话未归因率永远 97%+, D-071);
    · 发了牌、稿子(>= MIN_DRAFTS 篇)一篇都没带 angle_key 的项目(以前的判据 B): 牌就销不了、同一个故事会被再抽一次 ——
      那是模型没把 draw_angles 给的 angle_key 带到查重 / 存档(aw 的事), 不是写手的事。

数据: autowriter.tv_project_map(TV 项目 → 写作台项目)、truth_vault.notes(publish_time 在窗口内) 减
truth_vault.v_notes_vanished(飞书里删了的)、autowriter.tv_note_links(按 match_kind 分)、autowriter.angle_ledger
(发过牌的写作台项目不限时间; 窗口内的发牌)、autowriter.draft_fingerprints(窗口内的稿子)、autowriter.draft_snapshots
(查重底稿: 只取 project_id / checked_at 数篇数, 不取标题正文)。

窗口: 默认 7 天。

用法:
    python check_angle_ledger_leak.py                 # 默认 7 天
    python check_angle_ledger_leak.py --window-days 14
    python check_angle_ledger_leak.py --selftest      # CI: 判据 C 的纯函数 + 取数, 不连库

退出码:
    0 = 没有 TV 项目命中判据 C
    1 = 至少一个 TV 项目命中 —— 修在 autowriter 仓(skill 触发 / tv-sync 的对照), TV 这边红了也改不好
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
# 「稿子不带坐标」那一行提示的下限: 低于它不提。一次发牌 2-5 张、当场只写一两篇是正常节奏。
MIN_DRAFTS = 5
# 判据 C 的下限: 一周对不回 >= 10 篇且对上 <= 2 篇才喊。10-12 那周 sportsix 补录 12 / 对上 18、
# 百健士 15 / 19, 这种"一部分在外面写"的不喊; 途鸽 22 / 0、Hatherine 23 / 1 喊。
MIN_UNCAUGHT = 10
MAX_CAUGHT = 2
CHECK_C_BASE_DAYS = 7          # 上面两个下限是按 7 天定的; --window-days 14 就各乘 2(codex review on TV#205)
# tv-sync 复制进写作台的副本: 不是发牌产出的, 没有坐标, 不能算进台账表的稿子。
INGESTED_KIND = "ingested"
# 对上写作台的几种(tv-sync 的 match_kind)。同 aw core._TV_BACKFILL_KINDS、check_desk_use_rate.CAUGHT_KINDS。
CAUGHT_KINDS = frozenset({"body_exact", "title_exact", "fuzzy", "edited", "tv_lineage"})
# 表里分列、不进红的几种: 对不上的(没有补录目标 / 没正文 / W-38 明晚再试)、分不出是哪一版的(本来就是写作台的稿)。
INFO_KINDS = ("unmatched", "ambiguous")


def _utc_or_none(ts) -> datetime | None:
    """PostgREST 的时刻文本 → aware UTC; 没带时区的按 UTC; 解析不了回 None(夜跑不能因为一个怪值整个崩掉)。"""
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def unattributed(by_project: dict) -> list[dict]:
    """发了牌、稿子够数、一篇都没带 angle_key 的写作台项目(以前的判据 B; 10-29 起只报不喊)。纯函数。

    ``by_project`` 按 project_id 索引, 每格带一个 ``name`` 作显示。
    """
    out = []
    for pid, s in sorted(by_project.items()):
        drawn, drafts, with_key = s["drawn"], s["drafts"], s["with_key"]
        # ⚠️ `drawn > 0` 这一条不能省(codex review on #143): 压根没走 draw_angles 的项目, 它的稿子本来就没有坐标,
        # 台账里也没有行可销 —— 报它是判错病因。
        if drawn > 0 and drafts >= MIN_DRAFTS and with_key == 0:
            out.append({"project": s.get("name") or pid, "project_id": pid, "kind": "unattributed",
                        "drafts": drafts,
                        "detail": f"发牌 {drawn}、稿子 {drafts} 篇, 没有一篇带 angle_key, 台账销不了账"})
    return out


def verdicts_publish(by_project: dict, pub: dict, window_days: int = CHECK_C_BASE_DAYS) -> list[dict]:
    """判据 C: 哪些 TV 项目发出去的帖补录成了副本(对不回写作台)。纯函数 —— CI 直接喂假数测它。

    ``by_project`` 是 gather() 的那份(写作台项目 → 窗口内发牌 / 稿子); ``pub`` 是 gather_publish() 的:
    ``{"map": {tv: [写作台 project_id…]}, "links": {tv: {"published", "caught", "ingested", "pre_snapshot",
    "unmatched", "ambiguous", "unlinked", "late"}}, "used": {用过写作台的 project_id}, "snapshots": {写作台 project_id:
    窗口内查重底稿篇数} 或 None(018 没跑)}``。``window_days`` 把两个下限按 7 天一份等比放大。
    """
    out = []
    used = pub.get("used") or set()
    snaps = pub.get("snapshots")
    scale = max(window_days, 1) / CHECK_C_BASE_DAYS
    min_uncaught, max_caught = MIN_UNCAUGHT * scale, MAX_CAUGHT * scale
    for tv, pids in sorted((pub.get("map") or {}).items()):
        link = (pub.get("links") or {}).get(tv) or {}
        ing, caught, pre = link.get(INGESTED_KIND, 0), link.get("caught", 0), link.get("pre_snapshot", 0)
        if ing < min_uncaught or caught > max_caught:
            continue
        if not any(p in used for p in pids):
            continue        # 从没在写作台里写过的项目: 本来就不在写作台写, 不喊
        drawn = sum((by_project.get(p) or {}).get("drawn", 0) for p in pids)
        drafts = sum((by_project.get(p) or {}).get("drafts", 0) for p in pids)
        checked = None if snaps is None else sum(snaps.get(p, 0) for p in pids)
        # 一点动静都没有(没发牌、没存稿、也没查过重)才算对话没走到写作台; 底稿表刚建、还没记上的那几天, 发了牌的不算没动静
        if drawn == 0 and drafts == 0 and not checked:
            kind, why = "desk_silent", ("写作台这几天没收到这个项目的发牌、稿子" + ("、查重" if checked is not None else "")
                                        + " —— 写它的对话没走到写作台(skill 没被调起来, 没开项目就写了)")
        elif checked:
            kind, why = "published_unmatched", (f"写作台这几天查过 {checked} 篇稿, 发出去的帖却对不回: 改写得太多 / 底稿过期了,"
                                                " 或 aw tv-sync 的底稿那一步出了错(看 tv-sync 日志「查重底稿」那一行)")
        else:
            kind, why = "published_unmatched", (f"写作台这几天发牌 {drawn}、稿子 {drafts}"
                                                + ("" if checked is None else ", 一篇都没记下查重底稿")
                                                + " —— 发出去的帖对不回: 多半是写作台开始记查重底稿之前写的(看「之前」那几篇), "
                                                "不是的话看 aw tv-sync 日志")
        pre_note = (f"(其中约 {pre} 篇发布于写作台开始记查重底稿之前, 已补录成副本、改不回来)" if pre else "")
        out.append({"project": tv, "kind": kind, "ingested": ing, "caught": caught, "pre_snapshot": pre,
                    "drawn": drawn, "drafts": drafts, "checked": checked,
                    "detail": f"发出去的帖里 {ing} 篇补录成了副本{pre_note}、对上 {caught} 篇; {why}"})
    return out


def _print_publish(pub: dict, by_project: dict, window_days: int) -> None:
    links = pub.get("links") or {}
    snaps = pub.get("snapshots")
    rows = [(tv, links[tv]) for tv in sorted(pub.get("map") or {}) if (links.get(tv) or {}).get("published")]
    if not rows:
        print(f"  · 过去 {window_days} 天映射里的 TV 项目没有发出去的帖")
        return
    print(f"  发帖对账 · 过去 {window_days} 天发出去的帖(按发布时间, 飞书里删了的不算)"
          + ("; 018 没跑, 查重底稿那列空着" if snaps is None else ""))
    print(f"  {'TV 项目':<22}{'发出去':>6}{'对上':>6}{'补录副本':>8}{'没对上':>7}{'分不出':>7}{'还没对':>7}"
          f"{'写作台发牌':>10}{'查重底稿':>8}")
    for tv, l in rows:
        pids = pub["map"][tv]
        drawn = sum((by_project.get(p) or {}).get("drawn", 0) for p in pids)
        checked = "—" if snaps is None else str(sum(snaps.get(p, 0) for p in pids))
        print(f"  {tv[:21]:<22}{l.get('published', 0):>6}{l.get('caught', 0):>6}{l.get(INGESTED_KIND, 0):>8}"
              f"{l.get('unmatched', 0):>7}{l.get('ambiguous', 0):>7}{l.get('unlinked', 0):>7}{drawn:>10}{checked:>8}")


def _warn_publish(pub_hits: list[dict], window_days: int) -> None:
    msg = (f"过去 {window_days} 天 {len(pub_hits)} 个 TV 项目发出去的帖对不回写作台: "
           + "; ".join(f"{h['project']}({h['detail']})" for h in pub_hits)
           + " —— 这些帖在写作台里没有出处: 没有发牌查重的记录, 也进不了改稿差异和参考分, 飞轮只能当外部稿补录。"
             "写作台没查过稿的: 看写这个项目的那几场对话有没有 open_project / check_drafts 的调用记录 —— 没有就是那场对话"
             "没调起写作台(aw#109 起 skill 触发放宽、写作台会在下一场对话里提醒); 查过稿的: 看 aw tv-sync 的日志"
             "(W-38 起查重时记下的底稿会在补录之前再对一次)。写手没有存档这一步, 修在 autowriter 仓, TV 这边改不好。")
    print(f"  ⚠ {msg}")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::warning title=发出去的帖对不回写作台::{msg}", flush=True)


def report(stats: dict, window_days: int, now: datetime | None = None) -> int:
    """把 gather() + gather_publish() 的统计渲染成报告并返回退出码。纯函数, 不碰网络。``now`` 留着给调用方对齐签名。"""
    by_project = stats.get("by_project") or {}
    drawn = sum(s["drawn"] for s in by_project.values())
    consumed = sum(s["consumed"] for s in by_project.values())
    drafts = sum(s["drafts"] for s in by_project.values())
    with_key = sum(s["with_key"] for s in by_project.values())
    ingested = stats.get("ingested_skipped", 0)

    print()
    print("=" * 84)
    print(f"  发帖对账 + 角度台账 · 过去 {window_days} 天 · 发牌 {drawn} · 销账 {consumed} · "
          f"稿子 {drafts}(带坐标 {with_key})")
    print("=" * 84)
    pub = stats.get("publish") or {}
    pub_hits = verdicts_publish(by_project, pub, window_days)
    _print_publish(pub, by_project, window_days)

    # 台账表只报: 牌只在稿子存了档、或者发出去以后被对回来时才销, 没写的、写了没发的本来就不销(D-132)
    print(f"  角度台账(只报, 不判): 牌在稿子存档、或发出去后被 tv-sync 对回来时销账, 没销的不算问题; "
          f"稿子已排除 {ingested} 条 tv-sync 补录副本(match_kind={INGESTED_KIND}, 不是发牌产出的)")
    if by_project:
        print(f"  {'写作台项目':<22}{'发牌':>6}{'销账':>6}{'稿子':>6}{'带坐标':>8}")
        for pid, s in sorted(by_project.items(), key=lambda kv: -kv[1]["drawn"]):
            print(f"  {(s.get('name') or pid)[:21]:<22}{s['drawn']:>6}{s['consumed']:>6}"
                  f"{s['drafts']:>6}{s['with_key']:>8}")
    for h in unattributed(by_project):
        print(f"  · {h['project']}: {h['detail']} —— 模型没把 draw_angles 给的 angle_key 带到查重 / 存档, "
              "同一个故事会被再抽一次; 修在 aw(只报, 不进退出码)")

    if pub_hits:
        _warn_publish(pub_hits, window_days)
        return 1
    print("  ✓ 没有 TV 项目命中判据 C —— 发出去的帖对得回写作台, 或量小到不值得喊")
    return 0


def gather(sb, since_iso: str) -> dict:
    """台账表要的数: 窗口内每个写作台项目发了几张牌、销了几张、几篇稿子(排除补录副本)、几篇带坐标。"""
    from _common import fetch_all_pages  # 局部 import, 理由见文件头

    # ⚠️ order_by 必须是【唯一 + 稳定】的列, 且出现在 select 里 —— fetch_all_pages 按 order_by 的值去重, 用
    # created_at / drawn_at 这种不唯一的列做键, 同一毫秒的几行跨页时会被静默丢掉(codex review on #143)。
    angles = fetch_all_pages(
        sb.schema("autowriter").table("angle_ledger")
        .select("id, project_id, consumed_version_id")
        .gte("drawn_at", since_iso),
        order_by="id")
    fps = fetch_all_pages(
        sb.schema("autowriter").table("draft_fingerprints")
        .select("id, project_id, angle_key, version_id")
        .gte("created_at", since_iso),
        order_by="id")

    # 排除 tv-sync 补录的副本: 按实际见到的 version_id 精确查, 不按时间窗猜。
    ids = [f["version_id"] for f in fps if f.get("version_id")]
    ingested: set[str] = set()
    for i in range(0, len(ids), 200):
        rows = (sb.schema("autowriter").table("tv_note_links")
                .select("version_id")
                .eq("match_kind", INGESTED_KIND)
                .in_("version_id", ids[i:i + 200])
                .execute()).data or []
        ingested.update(r["version_id"] for r in rows)

    names = _project_names(sb, {a["project_id"] for a in angles} | {f["project_id"] for f in fps})
    by_project: dict[str, dict] = {}

    def slot(pid):
        # ⚠️ 按 **project_id** 聚合, 名字只作显示(codex review on #143): 项目名不唯一(「百健士-藻油」与「百健士藻油」),
        # 拿名字当键会把两个不相干的 UUID 并成一格。
        key = pid or "?"
        return by_project.setdefault(
            key, {"name": names.get(pid) or key, "drawn": 0, "consumed": 0, "drafts": 0, "with_key": 0})

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


def _snapshot_counts(sb, pids: set, since_iso: str) -> tuple[dict, set, str | None] | None:
    """查重底稿(W-38): 窗口内每个写作台项目查过几篇、表里有过底稿的项目(不限窗口, 表本身只留 60 天)、全表最早一篇是哪会儿
    查的。只取 project_id / checked_at, 不碰标题正文。表不在(018 没跑, PGRST205)回 None; 别的错直接抛(灯崩了比错判好,
    有哨兵行兜着)。"""
    from _common import fetch_all_pages  # 局部 import, 理由见文件头

    try:
        rows = fetch_all_pages(sb.schema("autowriter").table("draft_snapshots")
                               .select("id, project_id, checked_at"), order_by="id")
    except Exception as exc:                            # noqa: BLE001
        if "pgrst205" in str(exc).lower() and "draft_snapshots" in str(exc):
            return None
        raise
    counts: dict[str, int] = {}
    ever: set = set()
    for r in rows:
        if r.get("project_id") in pids:
            ever.add(r["project_id"])
            if str(r.get("checked_at") or "") >= since_iso:
                counts[r["project_id"]] = counts.get(r["project_id"], 0) + 1
    first = min((str(r["checked_at"]) for r in rows if r.get("checked_at")), default=None)
    return counts, ever, first


def _cn_day(ts: str):
    """时刻文本 → 北京日历日。TV 的 publish_time 不带时区、是北京那天的 0 点存成 UTC(前一天 16:00), 也按 UTC 读。"""
    t = _utc_or_none(ts)
    return None if t is None else (t + timedelta(hours=8)).date()


def gather_publish(sb, since_iso: str, until_iso: str | None = None) -> dict:
    """判据 C 要的数: TV 项目 → 写作台项目、窗口内【发出去】的帖按对照分、用过写作台的项目、窗口内的查重底稿篇数。"""
    from _common import fetch_all_pages, fetch_vanished_note_ids  # 局部 import, 理由见文件头

    maps = (sb.schema("autowriter").table("tv_project_map")
            .select("tv_project_id, project_id").execute()).data or []
    # 窗口按 truth_vault.notes.publish_time 切, 不按对照写进去的时间(matched_at): 新接一张表、或者 tv-sync 停了几天
    # 再补, 一批旧笔记会同时拿到很新的 matched_at, 被当成"这周发的"(codex review on aw#109)。
    # until_iso: 排期还没发的(publish_time 在未来)不算。
    q = (sb.schema("truth_vault").table("notes")
         .select("note_id, project_id, publish_time")
         .gte("publish_time", since_iso))
    if until_iso:
        q = q.lte("publish_time", until_iso)
    notes = fetch_all_pages(q, order_by="note_id")
    # 飞书里删了的不算(同 check_desk_use_rate): 那些帖已经不在了, 对不对得回无所谓。视图不在就直接抛(B-10 的道理)。
    vanished = fetch_vanished_note_ids(sb)
    tv_ids = {m["tv_project_id"] for m in maps}
    mine = [n for n in notes if n.get("project_id") in tv_ids and n["note_id"] not in vanished]
    links: dict[str, dict] = {}
    ids = [n["note_id"] for n in mine]
    for i in range(0, len(ids), 200):
        for l in (sb.schema("autowriter").table("tv_note_links")
                  .select("note_id, tv_project_id, match_kind, lag_days")
                  .in_("note_id", ids[i:i + 200]).execute()).data or []:
            links[l["note_id"]] = l
    # 不限时间: 断得越久越该喊(见文件头)。台账全表千把行, id + project_id 两列, 夜跑拉一遍不贵。
    used = fetch_all_pages(sb.schema("autowriter").table("angle_ledger").select("id, project_id"), order_by="id")

    by_tv: dict[str, list] = {}
    for m in maps:
        by_tv.setdefault(m["tv_project_id"], []).append(m["project_id"])
    pids = {p for ps in by_tv.values() for p in ps}
    snap = _snapshot_counts(sb, pids, since_iso)
    snap_counts, snap_ever, first_snapshot = snap if snap is not None else (None, set(), None)
    first_day = _cn_day(first_snapshot) if first_snapshot else None
    counts: dict[str, dict] = {}
    for n in mine:
        c = counts.setdefault(n["project_id"], {"published": 0, "caught": 0, INGESTED_KIND: 0, "pre_snapshot": 0,
                                                "unmatched": 0, "ambiguous": 0, "unlinked": 0, "late": 0})
        c["published"] += 1
        l = links.get(n["note_id"])
        kind = (l or {}).get("match_kind")
        if l is None:
            c["unlinked"] += 1                  # tv-sync 还没对到(它 14:00 UTC 跑, 这盏灯早上跑)
        elif kind in CAUGHT_KINDS:
            if l.get("lag_days") is None or l["lag_days"] >= 0:
                c["caught"] += 1
            else:
                c["late"] += 1                  # 写作台那版晚于发布 = 发出去之后抄回去的, 不算对上
        elif kind == INGESTED_KIND:
            c[INGESTED_KIND] += 1
            # 写作台开始记查重底稿(018)之前发的: 那时还认不回没存档的稿, 已经补录成副本、改不回来。按北京日历日比(发布时间
            # 只有日期): 第一份底稿那天发的不算之前
            pub_day = _cn_day(str(n.get("publish_time") or ""))
            if first_day is None or (pub_day is not None and pub_day < first_day):
                c["pre_snapshot"] += 1
        elif kind in INFO_KINDS:
            c[kind] += 1
    return {"map": by_tv, "links": counts, "snapshots": snap_counts,
            "used": ({u["project_id"] for u in used} | snap_ever) & pids}


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
    """判据 C + 台账表的自检。不连库; 反证靠改坏输入。"""
    import contextlib
    import io
    import types

    def run(stats, days=7, gha=False):
        buf = io.StringIO()
        saved_env = os.environ.get("GITHUB_ACTIONS")
        os.environ["GITHUB_ACTIONS"] = "true" if gha else "false"      # gha=True 时连 ::warning 那行一起断
        try:
            with contextlib.redirect_stdout(buf):
                rc = report(stats, days)
        finally:
            if saved_env is None:
                os.environ.pop("GITHUB_ACTIONS", None)
            else:
                os.environ["GITHUB_ACTIONS"] = saved_env
        return rc, buf.getvalue()

    P = lambda drawn, consumed, drafts, with_key, name="x": {  # noqa: E731
        "name": name, "drawn": drawn, "consumed": consumed, "drafts": drafts, "with_key": with_key}
    L = lambda caught=0, ing=0, un=0, amb=0, unlinked=0, pre=0: {  # noqa: E731
        "published": caught + ing + un + amb + unlinked, "caught": caught, INGESTED_KIND: ing, "pre_snapshot": pre,
        "unmatched": un, "ambiguous": amb, "unlinked": unlinked, "late": 0}

    def pub(links, used=("d1", "h1", "s1"), mp=None, snaps=None):
        return {"map": mp or {"TUGE": ["d1", "d2"], "HATH": ["h1"], "SPX": ["s1"]},
                "links": links, "used": set(used), "snapshots": snaps}

    # ── 判据 A 撤了(D-132): 发了牌、一张没销、一篇稿都没有 —— 不喊, 退出码 0 ─────────────────
    rc, out = run({"by_project": {"b1": P(24, 0, 0, 0, name="百健士成人藻油")}, "ingested_skipped": 0})
    assert rc == 0 and "抽完没写" not in out and "::warning" not in out, out
    assert "百健士成人藻油" in out and "没销的不算问题" in out, "台账表照样列出来"
    # 以前的判据 B: 稿子够数、一篇不带坐标 → 只报一行, 不进退出码
    rc, out = run({"by_project": {"p7": P(20, 0, 10, 0, name="D2")}, "ingested_skipped": 0}, gha=True)
    assert rc == 0 and "D2: 发牌 20、稿子 10 篇, 没有一篇带 angle_key" in out, out
    assert "::warning" not in out, "只报不喊的不打 annotation"
    assert unattributed({"丙": P(0, 0, 50, 0)}) == [], "没发过牌的项目, 稿子本来就没坐标"
    assert unattributed({"乙": P(6, 0, 5, 1)}) == [] and unattributed({"乙": P(6, 0, 4, 0)}) == []
    same_name = {"idA": P(12, 0, 3, 0, name="重名"), "idB": P(12, 0, 3, 0, name="重名")}
    assert unattributed(same_name) == [], "两个同名项目各 3 篇, 谁都不该被提(按 id 不按名字)"

    # ── 判据 C: 10-12 那周的真实形状(途鸽 22 / 0 写作台零动静、Hatherine 23 / 1、sportsix 12 / 18), 018 没跑 ──────
    week = pub({"TUGE": L(ing=22), "HATH": L(caught=1, ing=23), "SPX": L(caught=18, ing=12)})
    desk = {"h1": P(21, 1, 1, 1), "s1": P(33, 33, 33, 33)}
    got = {h["project"]: h["kind"] for h in verdicts_publish(desk, week)}
    assert got == {"TUGE": "desk_silent", "HATH": "published_unmatched"}, got
    # 红只数补录副本(终态, 同 aw desk_gap 的口径): 没对上(W-38 明晚再试 / 没正文 / 只判不入库)、分不出、还没对的都不算
    only = lambda **k: verdicts_publish({}, pub({"TUGE": L(**k)}))  # noqa: E731
    assert only(un=12) == [] and only(amb=12) == [] and only(unlinked=30) == [], "不是补录副本的不进红"
    assert [h["kind"] for h in only(ing=MIN_UNCAUGHT, caught=MAX_CAUGHT)] == ["desk_silent"]
    assert only(ing=MIN_UNCAUGHT - 1, un=20) == [] and only(ing=MIN_UNCAUGHT, caught=MAX_CAUGHT + 1) == []
    # 从没在写作台里写过的项目本来就不在写作台写: 不喊(否则天天红, D-053)
    assert verdicts_publish({}, pub({"TUGE": L(ing=50)}, used=())) == []
    # 映射到多个写作台项目时, 用过 / 有动静按整组算: d2 发了牌就不是「没收到调用」
    assert [h["kind"] for h in verdicts_publish({"d2": P(3, 0, 0, 0)}, week) if h["project"] == "TUGE"] \
        == ["published_unmatched"]
    # --window-days 14: 两个下限按窗口放大
    two = lambda ing, caught: verdicts_publish({}, pub({"TUGE": L(ing=ing, caught=caught)}), 14)  # noqa: E731
    assert [h["kind"] for h in two(20, 4)] == ["desk_silent"] and two(19, 0) == [] and two(20, 5) == []
    # 018 跑了: 有没有在写作台查过重来分两种(发了牌、一篇没查 = 对话没走到写作台; 查过 = 查过的稿对不回)
    snap_week = lambda snaps: {h["project"]: h["kind"] for h in verdicts_publish(  # noqa: E731
        {"d1": P(26, 0, 0, 0)}, pub({"TUGE": L(ing=13, pre=13)}, snaps=snaps))}
    assert snap_week({"d2": 7}) == {"TUGE": "published_unmatched"}
    # 底稿表刚建、还没记上: 发了牌的不算「没动静」(不能把它说成对话没走到写作台)
    h0 = verdicts_publish({"d1": P(26, 0, 0, 0)}, pub({"TUGE": L(ing=13, pre=13)}, snaps={}))[0]
    assert h0["kind"] == "published_unmatched" and "一篇都没记下查重底稿" in h0["detail"], h0
    assert [x["kind"] for x in verdicts_publish({}, pub({"TUGE": L(ing=13)}, snaps={}))] == ["desk_silent"]
    h = verdicts_publish({}, pub({"TUGE": L(ing=13, pre=13)}, snaps={"d2": 7}))[0]
    assert "写作台这几天查过 7 篇稿" in h["detail"] and "其中约 13 篇发布于写作台开始记查重底稿之前" in h["detail"], h

    rc, out = run({"by_project": {}, "ingested_skipped": 0, "publish": week}, gha=True)
    warn = [ln for ln in out.splitlines() if ln.startswith("::warning")]
    assert rc == 1 and len(warn) == 1 and "发出去的帖对不回写作台" in warn[0], out
    assert "TUGE" in warn[0] and "HATH" in warn[0] and "SPX" not in warn[0], warn
    assert "写完没存档" not in out and "存档提交" not in out, "写手没有存档这一步, 灯里不许这么说(D-132)"
    assert "SPX" in out and "018 没跑" in out, "发帖对账表要列出所有有帖的 TV 项目; 没有底稿表要说"
    rc, out = run({"by_project": {}, "ingested_skipped": 0})
    assert rc == 0, "没有 publish 的老调用方式不变"

    # ── gather_publish: 按对照分、飞书删了的不算、窗口按发布时间、翻页键唯一、只认映射里的项目、底稿只数不读 ──────────
    class _Q:
        def __init__(self, rows, sink=None, cols=None): self.rows, self.f, self.sink, self.cols = rows, [], sink, cols
        def select(self, cols="*", *a, **k):
            if self.cols is not None:
                self.cols.append(cols)
            return self
        def eq(self, k, v):
            if self.sink is not None:
                self.sink.append((k, v))
            self.f.append(lambda r: r.get(k) == v)
            return self
        def gte(self, k, v): self.f.append(lambda r: r.get(k) is not None and r[k] >= v); return self
        def lte(self, k, v): self.f.append(lambda r: r.get(k) is not None and r[k] <= v); return self
        def in_(self, k, vs): self.f.append(lambda r: r.get(k) in set(vs)); return self
        def order(self, k, **kw): self.f.append(lambda r: True); self.okey = k; return self
        def limit(self, n): self.n = n; return self
        def execute(self):
            rows = [r for r in self.rows if all(f(r) for f in self.f)]
            if getattr(self, "okey", None):
                rows = sorted(rows, key=lambda r: r[self.okey])[: getattr(self, "n", None)]
            return types.SimpleNamespace(data=rows)

    INWIN, OLD, LATER = "2026-10-14T08:00:00", "2026-09-20T08:00:00", "2026-10-21T08:00:00"
    note = lambda nid, tv, kind, pt, lag=None: ({"note_id": nid, "project_id": tv, "publish_time": pt},  # noqa: E731
                                               None if kind is None else
                                               {"note_id": nid, "tv_project_id": tv, "match_kind": kind, "lag_days": lag})
    ROWS = ([note(f"t{i:02d}", "TUGE", "ingested", INWIN) for i in range(20)]
            + [note("t-late", "TUGE", "ingested", "2026-10-16T16:00:00")]             # 底稿开始记之后发的
            + [note("t-amb", "TUGE", "ambiguous", INWIN), note("t-un", "TUGE", "unmatched", INWIN),
               note("t-new", "TUGE", None, INWIN),                                   # tv-sync 还没对到
               note("t-gone", "TUGE", "ingested", INWIN),                            # 飞书里删了
               note("h1", "HATH", "fuzzy", INWIN, 1), note("h2", "HATH", "tv_lineage", INWIN),
               note("h3", "HATH", "body_exact", INWIN, -3)]                          # 发了之后才进写作台: 不算对上
            + [note(f"old{i:02d}", "TUGE", "ingested", OLD) for i in range(30)]     # 新接表 / 补跑
            + [note(f"sch{i}", "TUGE", "ingested", LATER) for i in range(5)]        # 排期还没发
            + [note("zz1", "NOT_MAPPED", "ingested", INWIN)])
    NOTES = [n for n, _ in ROWS]
    LINKS = [l for _, l in ROWS if l is not None]
    LEDGER = [{"id": "a1", "project_id": "d1", "consumed_version_id": None, "drawn_at": "2026-05-01T00:00:00"},
              {"id": "a2", "project_id": "d1", "consumed_version_id": "v9", "drawn_at": "2026-10-13T06:59:00"},
              {"id": "a3", "project_id": "zz-unmapped", "consumed_version_id": None, "drawn_at": "2026-10-18T00:00:00"}]
    FPS = ([{"id": f"f{i}", "project_id": "d1", "angle_key": None, "version_id": f"vi{i}",
             "created_at": "2026-10-14T00:00:00"} for i in range(8)]                 # 补录副本: 不算稿子
           + [{"id": "g1", "project_id": "d1", "angle_key": "k1", "version_id": "v9",
               "created_at": "2026-10-13T07:00:00"}])
    SNAPS = [{"id": "s1", "project_id": "h1", "checked_at": "2026-10-15T03:00:00+00:00", "title": "不该被读到"},
             {"id": "s2", "project_id": "h1", "checked_at": "2026-10-16T03:00:00+00:00", "title": "不该被读到"},
             {"id": "s3", "project_id": "zz-unmapped", "checked_at": "2026-10-16T03:00:00+00:00"},
             {"id": "s4", "project_id": "d2", "checked_at": "2026-10-20T03:00:00+00:00"}]          # d2 没发过牌, 只查过重: 也算用过
    eq_seen: list = []
    snap_cols: list = []
    missing_snapshots = [False]
    TABLES = {"tv_project_map": [{"tv_project_id": "TUGE", "project_id": "d1"},
                                 {"tv_project_id": "TUGE", "project_id": "d2"},
                                 {"tv_project_id": "HATH", "project_id": "h1"}],
              "notes": NOTES, "tv_note_links": LINKS + [{"version_id": f"vi{i}", "match_kind": INGESTED_KIND,
                                                          "note_id": f"x{i}"} for i in range(8)],
              "angle_ledger": LEDGER, "draft_fingerprints": FPS,
              "projects": [{"id": "d1", "name": "途鸽"}]}

    class SB:
        def schema(self, s): return self
        def table(self, t):
            if t == "draft_snapshots":
                if missing_snapshots[0]:
                    raise RuntimeError("{'code': 'PGRST205', 'message': \"Could not find the table "
                                       "'autowriter.draft_snapshots' in the schema cache\"}")
                return _Q(SNAPS, cols=snap_cols)
            return _Q(TABLES[t], eq_seen if t == "tv_note_links" else None)

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
    fake.fetch_vanished_note_ids = lambda sb, project_id=None: {"t-gone"}
    sys.modules["_common"] = fake
    try:
        g = gather_publish(SB(), "2026-10-12T00:00:00", until_iso="2026-10-19T08:00:00")
        assert g["map"] == {"TUGE": ["d1", "d2"], "HATH": ["h1"]}, g["map"]
        assert g["links"]["TUGE"] == {"published": 24, "caught": 0, INGESTED_KIND: 21, "pre_snapshot": 20,
                                      "unmatched": 1, "ambiguous": 1, "unlinked": 1, "late": 0}, g["links"]["TUGE"]
        assert g["links"]["HATH"] == {"published": 3, "caught": 2, INGESTED_KIND: 0, "pre_snapshot": 0,
                                      "unmatched": 0, "ambiguous": 0, "unlinked": 0, "late": 1}, g["links"]["HATH"]
        assert g["snapshots"] == {"h1": 2, "d2": 1}, "只数映射里的写作台项目"
        assert all("title" not in c and "body" not in c and c != "*" for c in snap_cols), f"底稿只数不读: {snap_cols}"
        assert g["used"] == {"d1", "h1", "d2"}, "没映射的写作台项目不进 used; 只查过重的也算用过"
        # 反证: 不传 until → 排期的 5 篇算进来; 窗口拉到 9 月 → 旧的 30 篇算进来 —— 窗口确实是 publish_time
        assert gather_publish(SB(), "2026-10-12T00:00:00")["links"]["TUGE"][INGESTED_KIND] == 26
        assert gather_publish(SB(), "2026-09-01T00:00:00",
                              until_iso="2026-10-19T08:00:00")["links"]["TUGE"][INGESTED_KIND] == 51
        # 反证: 视图里那篇不排除就多一篇
        fake.fetch_vanished_note_ids = lambda sb, project_id=None: set()
        assert gather_publish(SB(), "2026-10-12T00:00:00",
                              until_iso="2026-10-19T08:00:00")["links"]["TUGE"][INGESTED_KIND] == 22
        fake.fetch_vanished_note_ids = lambda sb, project_id=None: {"t-gone"}
        assert [h["project"] for h in verdicts_publish({}, g)] == ["TUGE"]
        # 018 没跑: 底稿那一列空着、全部副本都算「记底稿之前」、按发牌和稿子分两种(老办法)
        missing_snapshots[0] = True
        g0 = gather_publish(SB(), "2026-10-12T00:00:00", until_iso="2026-10-19T08:00:00")
        assert g0["snapshots"] is None and g0["links"]["TUGE"]["pre_snapshot"] == 21 and g0["used"] == {"d1"}, g0
        missing_snapshots[0] = False

        # ── gather: 台账表排除补录副本(反证: 不排除, 8 条副本会被当成 8 篇不带坐标的稿) ────────────
        st = gather(SB(), "2026-10-12T00:00:00")
        assert ("match_kind", INGESTED_KIND) in eq_seen, "没有按 match_kind=ingested 过滤"
        assert st["ingested_skipped"] == 8 and st["by_project"]["d1"] == P(1, 1, 1, 1, name="途鸽"), st

        # main 接线: 两份数都取、哨兵行在
        fake.get_supabase_client = lambda: object()
        real = globals()["gather"], globals()["gather_publish"]
        globals()["gather"] = lambda sb, since: {"by_project": {}, "ingested_skipped": 0}
        globals()["gather_publish"] = lambda sb, since, **kw: week
        argv, sys.argv = sys.argv, ["check_angle_ledger_leak.py"]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rc = main()
        finally:
            sys.argv = argv
            globals()["gather"], globals()["gather_publish"] = real
        assert rc == 1 and "ANGLE_LEDGER_CHECK_DONE rc=1" in buf.getvalue(), buf.getvalue()
        # 夜跑真的在调它, 且哨兵前缀两边一致(同馆员流量那盏灯的做法); 夜跑不自己传窗口 —— 默认值由脚本钉着
        wf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".github", "workflows",
                               "daily-sync.yml")
        if os.path.exists(wf_path):
            wf = open(wf_path, encoding="utf-8").read()
            assert "python check_angle_ledger_leak.py" in wf, "夜跑没接这道检查"
            assert "ANGLE_LEDGER_CHECK_DONE rc=" in wf, "daily-sync 的哨兵 grep 和脚本不一致"
            assert "--window-days" not in wf.split("check_angle_ledger_leak.py", 1)[1][:200], "夜跑不该自己传窗口"
    finally:
        if saved is None:
            sys.modules.pop("_common", None)
        else:
            sys.modules["_common"] = saved
    print("  ✓ 判据 A 撤了: 发了牌一张没销不喊; 以前的 B 只报一行、不进退出码")
    print("  ✓ 判据 C: 红只数补录副本(没对上 / 分不出 / 还没对的分列)、飞书删了的不算、下限在、没用过写作台的不喊、"
          "按查没查过重分两种报、记底稿之前的副本单独数、底稿只数不读、取数翻页键唯一、台账表排除补录副本")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS,
                        help=f"看过去多少天发出去的帖与发牌(默认 {DEFAULT_WINDOW_DAYS})")
    parser.add_argument("--selftest", action="store_true", help="CI: 判据 C 的自检, 不连库")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if args.window_days < 1:
        print("--window-days 必须 >= 1")
        return 2
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=args.window_days)).replace(tzinfo=None).isoformat(timespec="seconds")

    from _common import get_supabase_client  # 局部 import, 理由见文件头
    sb = get_supabase_client()
    stats = gather(sb, since)
    stats["publish"] = gather_publish(sb, since,
                                      until_iso=now.replace(tzinfo=None).isoformat(timespec="seconds"))
    rc = report(stats, args.window_days, now)
    # ⚠️ 哨兵行: daily-sync.yml 靠它区分"跑完了"和"崩了"(那边是 `|| true` 调的)。
    print(f"ANGLE_LEDGER_CHECK_DONE rc={rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
