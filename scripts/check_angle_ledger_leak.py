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
    A. 窗口内某【一轮】发牌(同一人、同项目、同一个 drawn_at)>= MIN_DRAW_CARDS 张、发出已满
       DRAW_GRACE_HOURS 小时, 而这一轮一张都没销账                                  → 抽完没写(没存档)
    B. 某项目窗口内【发过牌】且真稿 >= MIN_DRAFTS, 而带坐标的 == 0 → 写了不带坐标
    C. 某 TV 项目窗口内【发出去】的帖里补录副本 >= MIN_UNCAUGHT 篇、对上写作台存档的 <= MAX_CAUGHT 篇
       (两个下限按窗口长度等比放大, 每 7 天一份), 而它对应的写作台项目用过写作台 → 发了帖、写作台没接住
三条都不成立才算通。一次发两三张牌、当场没写完是常态, 所以下限不能是 1。

A 在 2026-10-23 从「按项目合计」改成「按每一轮发牌」(TV OPEN-ITEMS W-29)。10-20..10-22 主写手在途鸽发了
五轮 73 张(10/15/16/16/16)、百健士成人藻油 10-22 06:57 一轮 24 张, 一轮都没存档, 而旧 A 两处都没喊:
    · 旧 A 要「项目窗口内发牌 >= 10 且真稿 == 0」—— 途鸽窗口里有一条手工入库的稿, 真稿 = 1, 73 张全被它盖住;
      百健士成人藻油同窗口里 10-21 那轮 16 张存了档, 项目合计有稿, 24 / 0 那一轮也被盖住;
    · 反过来, 10-21 08:12 夜跑时百健士成人藻油刚发的一轮还没存(08:29 才存), 项目窗口内真稿 0 → 旧 A 报了假警报。
一轮 = 一次 deskcore_reserve_angles 调用: 它在一个事务里把整轮插进台账, drawn_at 全是那个事务的 now()
(RPC 缺席时的降级路径 aw store.record_draw 也是一条 insert、显式写同一个 drawn_at), 所以按
(drawn_by, project_id, drawn_at) 分组就是一轮; 台账没有批次列, 这是唯一的轮次键。销账 = 存档提交时
写 consumed_version_id / consumed_at(两列同一条 UPDATE 写)。一轮里销了哪怕一张就算接住了 —— 发 16 张写 3 篇是正常节奏。

C 是 2026-10-19 补的(TV OPEN-ITEMS O-04): 途鸽 9-16 之后写作台一次发牌、一篇存档都没收到, 10-12 那周
发出去的 22 篇全是 tv-sync 补录的副本, 写手却一直以为在用写作台。A / B 都从【发牌】那一侧看, 一张牌
都没发的项目在它们眼里是「没活」, 所以这件事一个月都没灯亮。C 从【发帖】那一侧看, 分两种报:
    · 写作台窗口内没收到这个项目的一次发牌、一篇真稿 → 写这个项目的那几场对话没调起写作台(skill 没被
      调起来、没开项目就写了; WorkBuddy 的写作台连接是全局的, owner 10-19 确认)。同一个写手别的项目
      照常发牌也可能是这样 —— 途鸽就是(10-19 写手在另一场对话里列项目是通的);
    · 写作台有动静, 但发出去的不是它存的稿                → 连上了、写完没存档。
「用过写作台」(台账里有过它的牌, 不限时间)那一条是为了不对从来不走写作台的项目天天喊; 不设 60 天之类的期限 ——
断得越久越该喊, 设了期限, 一个断了两个月的项目反而会自己转绿(codex review on TV#205)。
「对上」只认写作台那版早于发布的(lag_days >= 0 或没记): 发出去之后才进写作台的那版是抄回去的, 不算接住
(全库 440 条对上里 212 条是这种; DECISIONS 里对上本来就只是「对应版本」, 不是生成来源)。
数据: autowriter.tv_project_map(TV 项目 → 写作台项目)、truth_vault.notes(publish_time 在窗口内) +
autowriter.tv_note_links(
按 match_kind 分补录 / 对上, 对上只认 lag_days >= 0)、autowriter.angle_ledger(发过牌的写作台项目, 不限时间)。

数据来源(都在共享 Supabase 的 autowriter schema 里, TV 用 service_role 只读):
    发牌  = autowriter.angle_ledger(drawn_at 在窗口内; drawn_by = 谁发的; consumed_version_id 非 NULL = 销了账)
    成稿  = autowriter.draft_fingerprints(created_at 在窗口内)
    排除  = autowriter.tv_note_links 里 match_kind='ingested' 的 version_id

窗口: 默认 7 天。比馆员那盏灯(48h)长, 因为「发牌 → 写稿」的节奏按天走, 48h 窗口
    多数日子会落进「窗口内没发牌」的无从判定, 灯就白装了。

用法:
    python check_angle_ledger_leak.py                 # 默认 7 天
    python check_angle_ledger_leak.py --window-days 14
    python check_angle_ledger_leak.py --selftest      # CI: 判据 A / C 的纯函数 + 取数, 不连库

退出码:
    0 = 窗口内没发牌(无从判定), 或三条判据都不成立
    1 = 至少一轮发牌命中 A、或一个项目命中 B / C —— 修在 autowriter 仓(协议/使用习惯), TV 这边红了也改不好
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
# 判据 A 的两道门(W-29, 按每一轮发牌判):
#   MIN_DRAW_CARDS —— 一轮至少几张才单独点名。主写手一轮常见 5–24 张(10-12 / 10-14 有不少 5 张一轮的真交付;
#     10-20..10-22: 途鸽 10/15/16/16/16、百健士成人藻油 16 / 24)。不到 5 张的一轮单独没存档, 代价只是占了一天避重
#     (占位 1 天自然过期), 不值得一轮一行地点名(D-053); 过去 30 天里不到 5 张的 3 轮其实都存了档。但零碎轮次
#     不能整个放过: 同一人在同一项目上不到 5 张的轮次合起来 >= SMALL_DRAWS_TOTAL 张、而他在这个项目上一轮都没
#     存档, 照样点名(见 _small_unsettled) —— 改成按轮判之前, 按项目的旧判据抓得到这种形状, 不能改丢。
#   DRAW_GRACE_HOURS —— 发出多久之后才判。存档顺利的轮次在最后一次 check_drafts 之后 25–80 秒就存了, 10-21 那次
#     假警报的一轮晚了 17 分钟; 夜跑实际 08–09 时(UTC)起跑, 12 小时让临近夜跑才发的牌留到下一晚判, 不会因为
#     "还在写"被点名, 而前一晚之前发的每一轮都判得到(最晚隔一晚, 远在 7 天窗口之内)。
MIN_DRAW_CARDS = 5
DRAW_GRACE_HOURS = 12
# 零碎轮次(每轮 < MIN_DRAW_CARDS 张)合起来到这个数才判 —— 沿用旧判据「一周发牌 >= 10 张、一篇没写」的门。
SMALL_DRAWS_TOTAL = 10
# 「也可能是存了档但没带 angle_key」那句提示的窗口: 这一轮发牌后多久之内, 同项目有不带坐标的真稿才算数。
NOKEY_AFTER_HOURS = 24
# 判据 B 的下限: 低于它不喊。一次发牌 2-5 张、当场只写一两篇是正常节奏。
MIN_DRAFTS = 5
# 判据 C 的下限: 一周补录 >= 10 篇且对上 <= 2 篇才喊。10-12 那周 sportsix 补录 12 / 对上 18、
# 百健士 15 / 19, 这种"一部分在外面写"的不喊; 途鸽 22 / 0、Hatherine 23 / 1 喊。
MIN_UNCAUGHT = 10
MAX_CAUGHT = 2
CHECK_C_BASE_DAYS = 7          # 上面两个下限是按 7 天定的; --window-days 14 就各乘 2(codex review on TV#205)
# tv-sync 复制进写作台的副本: 不是发牌产出的, 没有坐标, 不能算进未归因。
INGESTED_KIND = "ingested"
# 对上写作台存档的几种(tv-sync 的 match_kind; ambiguous / unmatched 两边都不算)。
CAUGHT_KINDS = frozenset({"body_exact", "title_exact", "fuzzy", "edited", "tv_lineage"})


def _utc(ts: str) -> datetime:
    """PostgREST 的 timestamptz 文本 → aware UTC。没带时区的按 UTC(本脚本的窗口起点就是这么写的)。"""
    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _utc_or_none(ts) -> datetime | None:
    """同 _utc, 解析不了(空、或不是时刻文本)就回 None。只给提示 / 兜底那几处用: 夜跑不能因为一个怪值整个崩掉。"""
    try:
        return _utc(ts) if ts else None
    except (TypeError, ValueError):
        return None


def _unsettled_draws(draws: list[dict], now: datetime) -> tuple[list[dict], list[dict]]:
    """够张数、一张没销账的轮次, 分成 (满宽限期的, 还在宽限期里的)。"""
    cutoff = now - timedelta(hours=DRAW_GRACE_HOURS)
    due, pending = [], []
    for d in draws:
        if d["cards"] < MIN_DRAW_CARDS or d["consumed"] > 0:
            continue
        (due if _utc(d["drawn_at"]) <= cutoff else pending).append(d)
    return due, pending


def _small_unsettled(draws: list[dict], now: datetime) -> list[dict]:
    """零碎轮次的兜底: 同一人、同一项目, 每轮 < MIN_DRAW_CARDS 张、发出满宽限期、一张没销账的轮次合起来
    >= SMALL_DRAWS_TOTAL 张, 而且这个人在这个项目上窗口内一轮都没销过账。返回每组一格。"""
    cutoff = now - timedelta(hours=DRAW_GRACE_HOURS)
    settled, groups = set(), {}
    for d in draws:
        key = (d.get("drawn_by"), d["project_id"])
        if d["consumed"] > 0:
            settled.add(key)
            continue
        at = _utc_or_none(d.get("drawn_at"))
        if d["cards"] >= MIN_DRAW_CARDS or at is None or at > cutoff:
            continue
        g = groups.setdefault(key, {"project_id": d["project_id"], "name": d.get("name"),
                                    "drawn_by": d.get("drawn_by"), "rounds": 0, "cards": 0,
                                    "first": at, "last": at})
        g["rounds"] += 1
        g["cards"] += d["cards"]
        g["first"], g["last"] = min(g["first"], at), max(g["last"], at)
    return [g for k, g in groups.items() if k not in settled and g["cards"] >= SMALL_DRAWS_TOTAL]


def verdicts_draws(draws: list[dict], now: datetime) -> list[dict]:
    """判据 A: 哪几轮发牌一张都没存档。纯函数 —— selftest 直接喂假轮次测它。

    ``draws`` 是 gather() 的那份, 每轮一格 ``{project_id, name, drawn_by, drawn_at, cards, consumed}``;
    一轮 = 同一人、同项目、同一个 drawn_at(理由见文件头)。窗口由 gather() 的 drawn_at >= since 管,
    这里只管下限和宽限期。返回按项目、发牌时刻排好。
    """
    out = []
    for d in _unsettled_draws(draws, now)[0]:
        at = _utc(d["drawn_at"])
        out.append({"project": d.get("name") or d["project_id"], "project_id": d["project_id"],
                    "kind": "drawn_unwritten", "drawn": d["cards"], "drawn_by": d.get("drawn_by"),
                    "rounds": 1, "nokey_drafts": d.get("nokey_drafts", 0),
                    "at": at, "detail": f"{at:%m-%d %H:%M} UTC 发牌 {d['cards']}、销账 0"})
    for g in _small_unsettled(draws, now):
        out.append({"project": g.get("name") or g["project_id"], "project_id": g["project_id"],
                    "kind": "drawn_unwritten_small", "drawn": g["cards"], "drawn_by": g.get("drawn_by"),
                    "rounds": g["rounds"], "nokey_drafts": 0, "at": g["first"],
                    "detail": (f"{g['first']:%m-%d %H:%M}–{g['last']:%m-%d %H:%M} UTC 零碎发牌 {g['rounds']} 轮"
                               f"(每轮不到 {MIN_DRAW_CARDS} 张)共 {g['cards']} 张、销账 0")})
    return sorted(out, key=lambda h: (h["project"], h["at"]))


def verdicts(by_project: dict) -> list[dict]:
    """判据 B: 哪些项目写了稿不带坐标。纯函数 —— CI 直接喂假 stats 测它。

    ``by_project`` 按 project_id 索引, 每格带一个 ``name`` 作显示。判据 A 不在这里:
    10-23 起按每一轮发牌判(W-29), 见 verdicts_draws()。
    """
    out = []
    for pid, s in sorted(by_project.items()):
        name = s.get("name") or pid
        drawn, drafts, with_key = s["drawn"], s["drafts"], s["with_key"]
        if drawn > 0 and drafts >= MIN_DRAFTS and with_key == 0:
            # ⚠️ `drawn > 0` 这一条不能省(codex review on #143): 压根没走 draw_angles
            # 的项目, 它的稿子本来就没有坐标, 台账里也没有行可销 —— 报它"漏账"是
            # 判错病因, 而且只要别的项目发过一次牌, 全局那道 drawn == 0 的闸就拦不住。
            out.append({"project": name, "project_id": pid, "kind": "unattributed",
                        "drafts": drafts,
                        "detail": f"发了 {drawn} 个角度、{drafts} 篇真稿入库, "
                                  "没有一篇带 angle_key, 台账无法销账"})
    return out


def verdicts_publish(by_project: dict, pub: dict, window_days: int = CHECK_C_BASE_DAYS) -> list[dict]:
    """判据 C: 哪些 TV 项目在发帖、写作台却没接住。纯函数 —— CI 直接喂假数测它。

    ``by_project`` 是 gather() 的那份(写作台项目 → 窗口内发牌 / 真稿); ``pub`` 是 gather_publish() 的:
    ``{"map": {tv: [写作台 project_id…]}, "links": {tv: {"ingested": n, "caught": n}},
    "used": {发过牌的写作台 project_id(不限时间)}}``。``window_days`` 把两个下限按 7 天一份等比放大。
    """
    out = []
    used = pub.get("used") or set()
    scale = max(window_days, 1) / CHECK_C_BASE_DAYS
    min_uncaught, max_caught = MIN_UNCAUGHT * scale, MAX_CAUGHT * scale
    for tv, pids in sorted((pub.get("map") or {}).items()):
        link = (pub.get("links") or {}).get(tv) or {}
        ing, caught = link.get("ingested", 0), link.get("caught", 0)
        if ing < min_uncaught or caught > max_caught:
            continue
        if not any(p in used for p in pids):
            continue        # 从没在写作台里写过的项目: 本来就不在写作台写, 不喊
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


def report(stats: dict, window_days: int, now: datetime | None = None) -> int:
    """把 gather() 的统计渲染成报告并返回退出码。纯函数, 不碰网络。``now`` 只给判据 A 的宽限期用。"""
    now = now or datetime.now(timezone.utc)
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
    pub_hits = verdicts_publish(by_project, pub, window_days)
    _print_publish(pub, by_project, window_days)
    if pub_hits:
        _warn_publish(pub_hits, window_days)

    if drawn == 0:
        print("  · 窗口内没有发牌, 角度台账无从判定(不是健康, 是没活)")
        return 1 if pub_hits else 0

    draws = stats.get("draws") or []
    unwritten = verdicts_draws(draws, now)
    pending = _unsettled_draws(draws, now)[1]
    if pending:
        print(f"  · {len(pending)} 轮发牌(>= {MIN_DRAW_CARDS} 张)发出不满 {DRAW_GRACE_HOURS} 小时、还没销账 —— "
              "存档可能还在路上, 下一晚再判")
    unattr = verdicts(by_project)
    if not unwritten and not unattr:
        print("  ✓ 没有一轮发牌命中判据 A、没有项目命中判据 B —— 发出去的角度都有稿子接住, 或量小到不值得喊")
        return 1 if pub_hits else 0

    parts = []
    if unwritten:
        # 一轮一行, 夜跑日志里直接读得出「哪个项目、哪一刻发的、几张、销了几张」。
        print(f"  抽完没写 · 判据 A(每一轮: >= {MIN_DRAW_CARDS} 张、发出满 {DRAW_GRACE_HOURS} 小时、一张没销账):")
        for h in unwritten:
            # 按这一轮判, 不按整个项目是否命中 B(review on W-29): 项目别处有带坐标的稿子时 B 不响, 但这一轮
            # 之后确实有不带坐标的真稿(D-071 Hatherine-D2 那种: 存了档、没带 angle_key) —— 不提一句就会让人去
            # 找一个其实发生过的 score_drafts。反过来项目命中 B、这一轮之后却没有无坐标的稿, 也不该带这句。
            also = (f" —— 发牌后 {NOKEY_AFTER_HOURS} 小时内这个项目有 {h['nokey_drafts']} 篇真稿没带 angle_key, "
                    "也可能是存了档但没带坐标" if h.get("nokey_drafts") else "")
            print(f"    · {h['project']} {h['detail']}{also}")
        parts.append(f"抽完没写 {sum(h.get('rounds', 1) for h in unwritten)} 轮: "
                     + "; ".join(f"{h['project']} {h['detail']}" for h in unwritten))
    if unattr:
        parts.append("写了不带坐标: " + "; ".join(f"{h['project']}({h['detail']})" for h in unattr))
    n_proj = len({h["project_id"] for h in unwritten + unattr})
    msg = (f"过去 {window_days} 天 {n_proj} 个项目的角度没走到成稿。" + " | ".join(parts)
           + " —— 后果不是少写了几篇: 没销账的坐标一天后就不在避重集里, 同一个故事"
             "下一批会被再抽一次, 而「同题重写」指纹闸抓不到。"
             "修在 autowriter 仓(score_drafts 每条都要带 draw_angles 给的 angle_key;"
             "会话别停在发牌之后; 抽完没写的那几轮, 去写手那场对话看最后一次 check_drafts 之后"
             "有没有 score_drafts 调用、有没有报错 —— W-29), 见 TV docs/27 与 aw deskcore-runbook。")
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
        .select("id, project_id, drawn_by, consumed_version_id, drawn_at")
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

    # 判据 A 的轮次: (drawn_by, project_id, drawn_at) 一组 = 一次 reserve 调用(理由见文件头)。
    # drawn_at 按 PostgREST 给的原文本分组, 不先解析 —— 同一事务写的同一个值, 文本也一字不差。
    draws: dict[tuple, dict] = {}
    for a in angles:
        s = slot(a["project_id"])
        s["drawn"] += 1
        d = draws.setdefault(
            (a.get("drawn_by"), a["project_id"], a.get("drawn_at")),
            {"project_id": a["project_id"], "name": s["name"], "drawn_by": a.get("drawn_by"),
             "drawn_at": a.get("drawn_at"), "cards": 0, "consumed": 0})
        d["cards"] += 1
        if a.get("consumed_version_id"):
            s["consumed"] += 1
            d["consumed"] += 1
    nokey: dict[str, list[datetime]] = {}            # 项目 → 不带坐标的真稿的入库时刻(给每轮那句提示用)
    for f in fps:
        if f.get("version_id") in ingested:
            continue
        s = slot(f["project_id"])
        s["drafts"] += 1
        if f.get("angle_key"):
            s["with_key"] += 1
        elif (t := _utc_or_none(f.get("created_at"))) is not None:
            nokey.setdefault(f["project_id"], []).append(t)
    for d in draws.values():
        start = _utc_or_none(d.get("drawn_at"))
        d["nokey_drafts"] = 0 if start is None else sum(
            1 for t in nokey.get(d["project_id"], ())
            if start <= t <= start + timedelta(hours=NOKEY_AFTER_HOURS))
    return {"by_project": by_project, "ingested_skipped": len(ingested), "draws": list(draws.values())}


def gather_publish(sb, since_iso: str, until_iso: str | None = None) -> dict:
    """判据 C 要的数: TV 项目 → 写作台项目、窗口内【发出去】的笔记按 match_kind 分、用过写作台的项目。"""
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
                      .select("note_id, tv_project_id, match_kind, lag_days")
                      .in_("note_id", note_ids[i:i + 200]).execute()).data or [])
    # 不限时间: 断得越久越该喊(见文件头)。台账全表千把行, id + project_id 两列, 夜跑拉一遍不贵。
    used = fetch_all_pages(
        sb.schema("autowriter").table("angle_ledger")
        .select("id, project_id"),
        order_by="id")

    by_tv: dict[str, list] = {}
    for m in maps:
        by_tv.setdefault(m["tv_project_id"], []).append(m["project_id"])
    counts: dict[str, dict] = {}
    for l in links:
        c = counts.setdefault(l.get("tv_project_id") or "?", {"ingested": 0, "caught": 0})
        if l.get("match_kind") == INGESTED_KIND:
            c["ingested"] += 1
        elif l.get("match_kind") in CAUGHT_KINDS and (l.get("lag_days") is None or l["lag_days"] >= 0):
            c["caught"] += 1            # 写作台那版晚于发布 = 发出去之后抄回去的, 不算接住
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
    """判据 A(按每一轮发牌, W-29)与判据 C 的自检(判据 B 的在 ci.yml 那一步的 heredoc 里)。不连库; 反证靠改坏输入。"""
    import contextlib
    import io
    import types

    def run(stats, now=None, gha=False):
        buf = io.StringIO()
        saved_env = os.environ.get("GITHUB_ACTIONS")
        os.environ["GITHUB_ACTIONS"] = "true" if gha else "false"      # gha=True 时连 ::warning 那行一起断
        try:
            with contextlib.redirect_stdout(buf):
                rc = report(stats, 7, now)
        finally:
            if saved_env is None:
                os.environ.pop("GITHUB_ACTIONS", None)
            else:
                os.environ["GITHUB_ACTIONS"] = saved_env
        return rc, buf.getvalue()

    # ── 判据 A(W-29): 按每一轮发牌判 —— 纯函数的几道门 ─────────────────────────────
    NOW = datetime(2026, 10, 23, 8, 12, tzinfo=timezone.utc)           # 夜跑大约这个点起跑
    ago = lambda h: (NOW - timedelta(hours=h)).isoformat()             # noqa: E731
    D = lambda at, cards, consumed=0, pid="b1", name="百健士成人藻油": {   # noqa: E731
        "project_id": pid, "name": name, "drawn_by": "w1", "drawn_at": at, "cards": cards, "consumed": consumed}
    A = lambda *ds, now=NOW: [(h["project"], h["drawn"]) for h in verdicts_draws(list(ds), now)]  # noqa: E731
    # 张数下限: 差一张不喊, 够了就喊
    assert A(D(ago(30), MIN_DRAW_CARDS - 1)) == [], "低于 MIN_DRAW_CARDS 的零碎发牌不该喊"
    assert A(D(ago(30), MIN_DRAW_CARDS)) == [("百健士成人藻油", MIN_DRAW_CARDS)]
    # 一轮里销了哪怕一张就算接住: 发 16 写 1 是正常节奏, 不喊
    assert A(D(ago(30), 16, consumed=1)) == [], "部分销账的一轮不该喊"
    # 宽限期: 差一分钟不喊, 过一分钟就喊(宽限期不是无限宽)
    assert A(D(ago(DRAW_GRACE_HOURS - 1 / 60), 16)) == [], "宽限期里的不该喊"
    assert A(D(ago(DRAW_GRACE_HOURS + 1 / 60), 16)) == [("百健士成人藻油", 16)]
    # PostgREST 的几种时刻写法都认(带毫秒 / Z / 不带时区)
    assert len(verdicts_draws([D("2026-10-22T06:57:12.88Z", 24), D("2026-10-22T06:57:12", 24)], NOW)) == 2

    # 10-21 那次假警报: 08:12:03 发的 16 张, 08:12:40 夜跑时还没存(08:29 才存)。旧 A 按项目合计
    # (发牌 16 >= 10、真稿 0)喊了; 现在它在宽限期里 → 不喊, 只记一行「下一晚再判」; 下一晚它销了账 → 也不喊。
    fp_at, fp_run = "2026-10-21T08:12:03.204+00:00", datetime(2026, 10, 21, 8, 12, 40, tzinfo=timezone.utc)
    fp_proj = {"b1": {"name": "百健士成人藻油", "drawn": 16, "consumed": 0, "drafts": 0, "with_key": 0}}
    rc, out = run({"by_project": fp_proj, "ingested_skipped": 0, "draws": [D(fp_at, 16)]}, now=fp_run)
    assert rc == 0 and "1 轮发牌" in out and "下一晚再判" in out and "抽完没写" not in out, out
    assert A(D(fp_at, 16, consumed=16), now=fp_run + timedelta(days=1)) == []
    # 「也可能是存了档但没带 angle_key」按这一轮判, 不按项目是否命中 B(review on W-29):
    #   项目别处有带坐标的稿(B 不响), 但这一轮之后有不带坐标的真稿 → 带这句(Hatherine-D2 那种, D-071)
    keyed = {"x": {"name": "X", "drawn": 16, "consumed": 0, "drafts": 12, "with_key": 9}}
    rc, out = run({"by_project": keyed, "ingested_skipped": 0,
                   "draws": [dict(D(ago(30), 16, pid="x", name="X"), nokey_drafts=3)]}, now=NOW)
    assert rc == 1 and "· X " in out and "有 3 篇真稿没带 angle_key" in out and "写了不带坐标" not in out, out
    #   项目命中 B, 但这一轮之后没有无坐标的稿 → 不带这句, 别把病因说成"没带坐标"
    nokeyp = {"x": {"name": "X", "drawn": 16, "consumed": 0, "drafts": MIN_DRAFTS, "with_key": 0}}
    rc, out = run({"by_project": nokeyp, "ingested_skipped": 0,
                   "draws": [dict(D(ago(30), 16, pid="x", name="X"), nokey_drafts=0)]}, now=NOW)
    assert rc == 1 and "· X " in out and "写了不带坐标" in out and "真稿没带 angle_key" not in out, out

    # 零碎轮次的兜底: 同一人同一项目 4 轮 × 3 张 = 12 张、一轮都没存 → 点名; 合起来 9 张 / 这个人在这个项目上
    # 存过一轮 / 还在宽限期里的, 都不点名(改成按轮判之前, 按项目的旧判据抓得到这种, 不能改丢)
    S3 = lambda h, by="w1", consumed=0: dict(D(ago(h), 3, consumed=consumed, pid="h1", name="Hatherine"),  # noqa: E731
                                             drawn_by=by)
    small = [S3(30), S3(40), S3(50), S3(60)]
    got = verdicts_draws(small, NOW)
    assert [(h["project"], h["drawn"], h["rounds"]) for h in got] == [("Hatherine", 12, 4)], got
    assert "零碎发牌 4 轮" in got[0]["detail"] and "共 12 张" in got[0]["detail"], got
    assert verdicts_draws(small[:3], NOW) == [], "合起来 9 张不到 SMALL_DRAWS_TOTAL, 不该喊"
    assert verdicts_draws(small + [S3(20, consumed=3)], NOW) == [], "同一人在这个项目上存过一轮, 零碎的不喊"
    assert verdicts_draws(small[:3] + [S3(1)], NOW) == [], "宽限期里的零碎轮次不算进去"
    assert verdicts_draws([S3(30), S3(40), S3(50, by="w2"), S3(60, by="w2")], NOW) == [], "两个人各 6 张, 不并"
    rc, out = run({"by_project": {"h1": {"name": "Hatherine", "drawn": 12, "consumed": 0, "drafts": 0,
                                         "with_key": 0}}, "ingested_skipped": 0, "draws": small}, now=NOW, gha=True)
    warn = [ln for ln in out.splitlines() if ln.startswith("::warning")]
    assert rc == 1 and "零碎发牌 4 轮" in out and len(warn) == 1 and "抽完没写 4 轮" in warn[0], out

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
    # 从没在写作台里写过的项目本来就不在写作台写: 不喊(否则天天红, D-053)
    assert verdicts_publish({}, pub({"TUGE": {"ingested": 50, "caught": 0}}, used=())) == []
    # 映射到多个写作台项目时, 用过 / 有动静按整组算: d2 发了牌就不是「没收到调用」
    assert [h["kind"] for h in verdicts_publish({"d2": P(3, 0)}, week)
            if h["project"] == "TUGE"] == ["published_unsaved"]
    # --window-days 14: 两周各 10 / 2 合起来 20 / 4, 不能因为窗口拉长就把问题藏掉; 14 天里只有 10 篇补录也不该喊
    two_weeks = lambda ing, caught: verdicts_publish({}, pub({"TUGE": {"ingested": ing, "caught": caught}}), 14)  # noqa: E731
    assert [h["kind"] for h in two_weeks(20, 4)] == ["desk_silent"], "下限要按窗口放大"
    assert two_weeks(19, 0) == [] and two_weeks(20, 5) == []

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
        def eq(self, k, v): self.f.append(lambda r: r.get(k) == v); return self
        def gte(self, k, v): self.f.append(lambda r: r[k] >= v); return self
        def lte(self, k, v): self.f.append(lambda r: r[k] <= v); return self
        def in_(self, k, vs): self.f.append(lambda r: r[k] in set(vs)); return self
        def execute(self): return types.SimpleNamespace(data=[r for r in self.rows if all(f(r) for f in self.f)])

    INWIN, OLD, LATER = "2026-10-14T08:00:00", "2026-09-20T08:00:00", "2026-10-21T08:00:00"
    note = lambda nid, tv, kind, pt, lag=None: ({"note_id": nid, "project_id": tv, "publish_time": pt},  # noqa: E731
                                               {"note_id": nid, "tv_project_id": tv, "match_kind": kind, "lag_days": lag,
                                                "matched_at": "2026-10-19T04:00:00"})   # 全都是刚连上的 —— 窗口不该按它切
    ROWS = ([note(f"t{i:02d}", "TUGE", "ingested", INWIN) for i in range(22)]
            + [note("t-amb", "TUGE", "ambiguous", INWIN), note("t-un", "TUGE", "unmatched", INWIN),
               note("h1", "HATH", "fuzzy", INWIN, 1), note("h2", "HATH", "tv_lineage", INWIN),
               note("h3", "HATH", "body_exact", INWIN, -3)]                             # 发了之后才进写作台: 不算接住
            + [note(f"old{i:02d}", "TUGE", "ingested", OLD) for i in range(30)]       # 新接表 / 补跑
            + [note(f"sch{i}", "TUGE", "ingested", LATER) for i in range(5)]          # 排期还没发
            + [note("zz1", "NOT_MAPPED", "ingested", INWIN)])
    NOTES, LINKS = [n for n, _ in ROWS], [l for _, l in ROWS]
    LEDGER = [{"id": "a1", "project_id": "d1", "drawn_at": "2026-05-01T00:00:00"},   # 半年前发过也算用过
              {"id": "a2", "project_id": "d1", "drawn_at": "2026-09-16T06:59:00"},
              {"id": "a3", "project_id": "zz-unmapped", "drawn_at": "2026-10-18T00:00:00"}]

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
        g = gather_publish(SB(), "2026-10-12T00:00:00", until_iso="2026-10-19T08:00:00")
        assert g["map"] == {"TUGE": ["d1", "d2"], "HATH": ["h1"]}, g["map"]
        assert g["links"] == {"TUGE": {"ingested": 22, "caught": 0},
                              "HATH": {"ingested": 0, "caught": 2}}, g["links"]   # h3 (lag -3) 不算
        assert g["used"] == {"d1"}, "没映射的写作台项目不进 used"
        # 反证: 不传 until → 排期的 5 篇算进来; 窗口拉到 9 月 → 旧的 30 篇算进来 —— 窗口确实是 publish_time
        assert gather_publish(SB(), "2026-10-12T00:00:00")["links"]["TUGE"]["ingested"] == 27
        assert gather_publish(SB(), "2026-09-01T00:00:00",
                              until_iso="2026-10-19T08:00:00")["links"]["TUGE"]["ingested"] == 52
        assert [h["project"] for h in verdicts_publish({}, g)] == ["TUGE"]

        # ── 判据 A 取数 + 报告: 10-20..10-22 的真形状(张数是真的; 时刻除 10-21 02:54 / 10-22 06:57 外只取形状) ──
        def cards(pid, at, n, consumed=0, by="w1"):
            return [{"id": f"{pid}|{by}|{at}|{i}", "project_id": pid, "drawn_by": by, "drawn_at": at,
                     "consumed_version_id": f"v|{pid}|{at}|{i}" if i < consumed else None} for i in range(n)]
        TUGE = [("2026-10-20T07:05:41.120+00:00", 10), ("2026-10-21T02:54:08.517+00:00", 15),
                ("2026-10-21T07:38:20.004+00:00", 16), ("2026-10-22T05:21:55.390+00:00", 16),
                ("2026-10-22T06:32:32.685+00:00", 16)]
        LEDGER_A = ([r for at, n in TUGE for r in cards("d1", at, n)]                     # 途鸽五轮 73 张, 0 销账
                    + cards("d1", "2026-10-10T03:00:00+00:00", 16)                       # 窗口(7 天)外: 不判
                    + cards("b1", "2026-10-21T08:12:03.204+00:00", 16, consumed=16)      # 17 分钟后存了档
                    + cards("b1", "2026-10-22T06:57:12.880+00:00", 24)                   # 24 / 0
                    + cards("b1", "2026-10-23T07:40:00.000+00:00", 16)                   # 32 分钟前发的: 宽限期里
                    + cards("s1", "2026-10-21T03:00:00.000+00:00", 16, consumed=3)       # 部分销账
                    + cards("h1", "2026-10-20T09:00:00.000+00:00", 3)                    # 零碎试抽, 两个人
                    + cards("h1", "2026-10-20T09:00:00.000+00:00", 3, by="w2"))          # 同一刻: 是两轮, 不是一轮 6 张
        FPS_A = ([{"id": "fp-manual", "project_id": "d1", "angle_key": None, "version_id": "v-manual",
                   "created_at": "2026-10-20T05:49:50+00:00"}]                            # 途鸽那条手工入库的稿(真实时刻: 第一轮之前)
                 + [{"id": f"fp-ing{i}", "project_id": "d1", "angle_key": None, "version_id": f"v-ing{i}",
                     "created_at": "2026-10-22T04:00:00+00:00"} for i in range(18)]       # tv-sync 补录的 18 条
                 + [{"id": f"fp-b{i}", "project_id": "b1", "angle_key": f"k{i}", "version_id": f"v-b{i}",
                     "created_at": "2026-10-21T08:29:10+00:00"} for i in range(16)]
                 + [{"id": f"fp-s{i}", "project_id": "s1", "angle_key": f"k{i}", "version_id": f"v-s{i}",
                     "created_at": "2026-10-21T03:30:00+00:00"} for i in range(3)])
        TABLES_A = {"angle_ledger": LEDGER_A, "draft_fingerprints": FPS_A,
                    "tv_note_links": [{"version_id": f"v-ing{i}", "match_kind": INGESTED_KIND} for i in range(18)],
                    "projects": [{"id": "d1", "name": "途鸽"}, {"id": "b1", "name": "百健士成人藻油"},
                                 {"id": "s1", "name": "sportsix"}, {"id": "h1", "name": "Hatherine"}]}

        class SBA(SB):
            def table(self, t): return _Q(TABLES_A[t])

        st = gather(SBA(), (NOW - timedelta(days=DEFAULT_WINDOW_DAYS)).isoformat())
        tg = st["by_project"]["d1"]
        # 旧 A 为什么没喊: 按项目合计, 途鸽 73 张、真稿被那条手工入库的撑成 1(补录的 18 条照旧排除) —— 「真稿 == 0」不成立
        assert (tg["drawn"], tg["consumed"], tg["drafts"], tg["with_key"]) == (73, 0, 1, 0), tg
        assert st["ingested_skipped"] == 18, st["ingested_skipped"]
        assert len(st["draws"]) == 5 + 3 + 1 + 2, sorted((d["name"], d["drawn_at"]) for d in st["draws"])
        got = [(h["project"], f"{h['at']:%m-%d %H:%M}", h["drawn"]) for h in verdicts_draws(st["draws"], NOW)]
        assert got == [("百健士成人藻油", "10-22 06:57", 24),
                       ("途鸽", "10-20 07:05", 10), ("途鸽", "10-21 02:54", 15), ("途鸽", "10-21 07:38", 16),
                       ("途鸽", "10-22 05:21", 16), ("途鸽", "10-22 06:32", 16)], got
        # 每轮那句提示的取数: 只数这一轮发牌后 NOKEY_AFTER_HOURS 小时内、同项目、不是 tv-sync 副本、不带坐标的真稿。
        # 途鸽那条手工入库在第一轮之前 → 五轮都是 0; 18 条补录副本不算 → 也是 0。
        assert {d["drawn_at"][:16]: d["nokey_drafts"] for d in st["draws"] if d["project_id"] == "d1"
                and d["drawn_at"] >= "2026-10-20"} == {at[:16]: 0 for at, _ in TUGE}, st["draws"]
        FPS_A.append({"id": "fp-nokey", "project_id": "d1", "angle_key": None, "version_id": "v-nokey",
                      "created_at": "2026-10-21T07:20:00+00:00"})                        # 10-21 02:54 那轮之后 4.5 小时
        try:
            st2 = gather(SBA(), (NOW - timedelta(days=DEFAULT_WINDOW_DAYS)).isoformat())
        finally:
            FPS_A.pop()
        nk = {d["drawn_at"][:16]: d["nokey_drafts"] for d in st2["draws"] if d["project_id"] == "d1"
              and d["drawn_at"] >= "2026-10-20"}
        assert nk["2026-10-21T02:54"] == 1, nk
        assert nk["2026-10-20T07:05"] == 0, f"发牌满 {NOKEY_AFTER_HOURS} 小时之后才入库的不算: {nk}"
        assert nk["2026-10-21T07:38"] == 0 and nk["2026-10-22T05:21"] == 0, f"发牌之前入库的不算: {nk}"

        # 反证: 分组键漏了 drawn_by → Hatherine 两个人同一刻的 3 + 3 并成一轮 6 张, 越过下限冒出假警报
        merged = [dict(d, cards=6) for d in st["draws"] if d["project_id"] == "h1"][:1]
        assert [h["project"] for h in verdicts_draws(merged, NOW)] == ["Hatherine"], "反证前提不成立"

        rc, out = run(st, now=NOW, gha=True)
        lines = [ln.strip() for ln in out.splitlines() if ln.startswith("    · ")]
        assert rc == 1 and len(lines) == 6, out
        assert "· 途鸽 10-21 02:54 UTC 发牌 15、销账 0" in lines, lines
        assert "· 百健士成人藻油 10-22 06:57 UTC 发牌 24、销账 0" in lines, lines
        assert not any(k in ln for ln in lines for k in ("10-21 08:12", "sportsix", "Hatherine")), lines
        assert "1 轮发牌" in out and "下一晚再判" in out, out                              # 07:40 那轮还在宽限期
        warn = [ln for ln in out.splitlines() if ln.startswith("::warning title=角度台账漏账")]
        assert len(warn) == 1 and "抽完没写 6 轮" in warn[0] and "途鸽 10-21 02:54 UTC 发牌 15、销账 0" in warn[0], warn

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
    finally:
        if saved is None:
            sys.modules.pop("_common", None)
        else:
            sys.modules["_common"] = saved
    print("  ✓ 判据 A: 按每一轮发牌判 —— 途鸽五轮不被一条手工入库盖住、24 / 0 那轮不被同项目存了档的一轮盖住、"
          "17 分钟后存档的不喊、部分销账不喊、零碎试抽单独不喊但合起来够数照喊、同一刻两个人是两轮、"
          "「没带坐标」的提示按这一轮判")
    print("  ✓ 判据 C: 途鸽 / Hatherine 两种形状分开报、下限在、没用过写作台的不喊、一张牌没发也照喊、取数翻页键唯一")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS,
                        help=f"看过去多少天的发牌与成稿(默认 {DEFAULT_WINDOW_DAYS})")
    parser.add_argument("--selftest", action="store_true", help="CI: 判据 A / C 的自检, 不连库")
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
