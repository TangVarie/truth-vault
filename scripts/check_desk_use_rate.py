"""
check_desk_use_rate.py
═══════════════════════════════════════════════════════════════════════════

写作台用上率: 每个项目发出去的帖里, 有多少是写作台出的稿、其中多少原样发了? —— 只读, 不写库。每周一跑。

2026-10-20 生产诊断(docs/32 §1): 写作台的稿子短、彼此像, 大多在飞书里被人整篇重写 —— 写作台存的稿最后
发出去的只有 23–45%, 有一个项目是 0。写作台自己量不出这件事: 参考分 79 篇全是 100, 而「被重写」发生在
飞书里、写作台之外。第一批 / 第二批(docs/32)改的是写作台出稿; 这盏灯从【发出去的帖】那一侧看它们有没有用。

口径(按 TV 项目算; 写作台项目经 autowriter.tv_project_map 归到 TV 项目下):
  发布   = truth_vault.notes 里 publish_time 落在窗口内的笔记(只取 id 和时间, 不读正文); 飞书里已删的
           (v_notes_vanished, 审计 B-21 / D-103)不算, 同闸二 / 策展 / 通道 1
  发牌   = autowriter.angle_ledger 里 drawn_at 落在 [窗口起点 − 7 天, 窗口终点] 的牌: 牌先发、稿后存、帖再发,
           只看窗口内会把起点前几天发的那批读成零动静(见 DRAW_LOOKBACK_DAYS)。
  在用期 = 这个 TV 项目每张牌那天起 7 天, 加上每篇接住的帖存稿那天(发布日 − lag_days)起 7 天, 按日、可以断成
           几段(见 USE_TAIL_DAYS)。首牌之前、末牌 7 天之后、中间停了一阵的那几天发的帖基本不可能是写作台的稿, 判据只看
           在用期里发布的; 接住的帖本身证明那几天写作台在出稿(翻旧牌写、没抽新牌也算)(codex review on TV#208)。
           回看期内一张牌都没发的项目没有在用期(D-053, 见下)
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

判据(rc=1, 🟡): 写作台在用(回看期内发过牌, 或窗口里有接住的帖)、在用期里发布的帖对过账 >= 15 篇(且占在用期里发布的八成以上)、其中接住率 < 20% 的
  TV 项目。表里的发布 / 对过账两列照旧数整个窗口(tv-sync 对没对账和写作台用没用无关)。
  · 够不够格判只有一条规则(_judgeable): verdicts() 和「没有项目够格判」那句都调它, ✓ 那句照它写, 不各写一遍;
  · 只看在用的: 回看期内一张牌都没发、窗口里也没有一篇接住的项目本来就没在用写作台, 它的没接住归角度台账灯
    判据 C(写作台零动静), 这里不重复喊(D-053)。没抽新牌、翻更早的牌写出接住的帖的也算在用(接住本身就是证据,
    codex review on TV#208)。在用的项目两盏灯会同时亮: 判据 C 的「查过稿、发出去对不回」也算在用的项目。两边
    读的是同一批 tv_note_links, 光凭链接分不清「没在写作台写」和「被重写」(两种都是补录副本), 分开它们要看写作台
    这段时间查没查过这个项目的稿 —— 判据 C 那张表的「查重底稿」列(W-38 / D-132; 写手没有存档这一步, 不看存档)。
    亮黄的报文里点明这一句;
  · 15 篇是比例能不能读的样本下限, 不随窗口放大(它管的是一个比例有几个分母, 不是一周该发多少);
  · 分母用对过账的, 不用发布数: 没对过账的不知道是不是写作台的稿, 当成没接住会在 tv-sync 某晚失败时冒假黄。
rc=2: 判不了 —— 映射的 TV 项目窗口内一篇都没发, 或发了但一条链接都没有(tv-sync 没对过账); 或者【某一个】项目
     整窗(或在用的项目在用期里)发布 >= 15 篇、对过账的不到八成(tv-sync 漏了这个项目: aw 的 tv-sync 一个项目出错
     只记一行、接着跑别的, 别的项目照常对账, 全局合计看不出来; tv-sync 坏的那几天正好是在用的那几天时, 整窗合计还
     过八成)。这种项目点名报; 别的项目照常判, 有项目亮黄时 rc 仍是 1。

红了修在 autowriter 仓(写作台出稿质量: TV docs/32 第一批 / 第二批), TV 这边改不好。advisory, 不拖红。

用法:
    python check_desk_use_rate.py                         # 默认: 发布于 21 天前 ~ 7 天前
    python check_desk_use_rate.py --window-days 28 --delay-days 7
    python check_desk_use_rate.py --selftest              # CI: 判据 / 口径 / 取数 / 接线, 不连库

退出码:
    0 = 没有项目命中判据(或有数但没有项目够格判, 且没有项目被点名判不了)
    1 = 至少一个项目命中 —— 修在 autowriter 仓
    2 = 判不了(没发布 / 没对过账 / 某个项目整窗或在用期里大多没对过账), 且没有项目命中
⚠️ 同 check_angle_ledger_leak.py 的约定: 正常跑完末尾必打一行 `DESK_USE_RATE_CHECK_DONE rc=<码>`;
daily-sync.yml 靠有没有这一行判定崩溃, 不靠退出码。
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone

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
# 发牌往窗口起点前多看几天(10-20 定, codex review on TV#208): 牌先发、稿后存、帖再发。10-20 生产只读: 写作台接住的帖,
# 存稿 → 发布的 lag_days p10 0 / 中位 1 / p90 4 / 最长 38(213 条链接), 牌又是存稿前不久发的 —— 7 天盖住九成还有余量。
# 不为最长那条尾巴放长: 回看越长, 一个月前用过一阵、后来不用了的项目越会被当成在用, 拿它没写的帖判它。终点不往后放:
# 窗口终点之后的牌不可能是窗口里那些帖的。
DRAW_LOOKBACK_DAYS = 7
# 在用期: 一张牌(或一篇接住的帖的存稿日)之后多少天发的帖还算这段写作台在用(10-20 定, codex review on TV#208)。同一组
# lag 数、同一个理由: 存稿 → 发布 p90 4 天, 7 天盖住九成。回看放长之后光在首牌处切不够: 起点前 6 天发过一张牌、
# 之后再没动的项目, 会拿整窗它没写的帖判它(回看把「一张牌判它之后的所有帖」从 14 天拉到 21 天); 中间停了一阵的也一样。
USE_TAIL_DAYS = DRAW_LOOKBACK_DAYS
# 改动差异的当前口径(aw deskcore/tvlink.py DIFF_REV): 2 = 话题行两边都剥、写作台那版晚于发布的不算(10-20)。
# 旧口径的行(0 / 1)把话题行算成"人删了一句"、把抄回去的副本算成"人改过", 不能拿来算未改动。
CURRENT_DIFF_REV = 2
# 对上写作台版本的几种(tv-sync 的 match_kind)。同 check_angle_ledger_leak.CAUGHT_KINDS、aw _TV_BACKFILL_KINDS。
CAUGHT_KINDS = frozenset({"body_exact", "title_exact", "fuzzy", "edited", "tv_lineage"})
CHUNK = 200     # .in_() 走 URL, 约 26 KB 撞线(D-080), 一批 ≤200 个 id


def is_caught(link: dict) -> bool:
    """这篇是不是从写作台出来的: 对上了, 且写作台那版不晚于发布。"""
    lag = link.get("lag_days")
    return link.get("match_kind") in CAUGHT_KINDS and (lag is None or lag >= 0)


def _day(ts) -> str:
    """时间戳 → YYYY-MM-DD。按日比, 同 aw tvlink.lag_days(两边各取日期相减)。"""
    return str(ts or "")[:10]


def _save_day(n: dict, link: dict) -> str:
    """接住的帖那版存进写作台的日子: 发布日 − lag_days; lag 不知道的(tv_lineage 等)按发布日。"""
    day, lag = _day(n.get("publish_time")), link.get("lag_days")
    return (date.fromisoformat(day) - timedelta(days=lag)).isoformat() if day and lag else day


def _spans(days: set, lo: str, hi: str) -> list[tuple[str, str]]:
    """一堆日子 → 连续的几段 [(起, 止)], 只留 [lo, hi] 里的(报文用)。"""
    out: list[list[str]] = []
    for d in sorted(x for x in days if lo <= x <= hi):
        if out and date.fromisoformat(d) - date.fromisoformat(out[-1][1]) == timedelta(days=1):
            out[-1][1] = d
        else:
            out.append([d, d])
    return [(a, b) for a, b in out]


def tally(g: dict) -> dict:
    """gather() 的原始行 → 每个 TV 项目一格。纯函数 —— CI 直接喂假数测它。

    ``g``: ``{"map": {tv: [写作台 project_id…]}, "names": {project_id: 名字},
    "notes": [{note_id, project_id, publish_time}], "links": {note_id: tv_note_links 行},
    "diffs": {note_id: tv_edit_diffs 行}, "drawn": {project_id: 回看期内发牌数},
    "drawn_days": {project_id: 回看期内发过牌的日子 [YYYY-MM-DD…]}, "since" / "until": 窗口}``。
    发布 / 对过账 / 接住 数整个窗口(unlinked() 的整窗那条和表里的发布、对过账两列用它); ``j_*`` 只数在用期里发布的
    —— 判据用它(codex review on TV#208)。在用期 = 这个 TV 项目(映射的几个写作台项目合起来)每个发牌日、每篇接住的帖的
    存稿日起 USE_TAIL_DAYS 天, 按日、可以断成几段: 首牌之前、末牌 7 天之后、中间停了一阵的帖不判; 首牌之前就有接住的帖
    (翻旧牌写、没抽新牌; 早的牌在回看之外)那几天照判 —— 接住本身证明写作台在出稿, 回看期内一张牌都没发也一样。
    回看期内没发牌、窗口里也没有一篇接住的项目没有在用期(D-053, 归角度台账灯判据 C)。``use_spans`` = 在用期落在窗口里的几段, 给报文用。窗口内一篇都没发的 TV 项目不出现。
    """
    links, diffs = g.get("links") or {}, g.get("diffs") or {}
    drawn, drawn_days = g.get("drawn") or {}, g.get("drawn_days") or {}
    rows: dict[str, dict] = {}
    marks: dict[str, set] = {}
    for tv, pids in (g.get("map") or {}).items():
        marks[tv] = {_day(d) for p in pids for d in drawn_days.get(p) or ()}
        rows[tv] = {"published": 0, "linked": 0, "caught": 0, "diffed": 0, "unchanged": 0, "title_changed": 0,
                    "drawn": sum(drawn.get(p, 0) for p in pids), "use_spans": [],
                    "j_published": 0, "j_linked": 0, "j_caught": 0,
                    "desk": sorted({(g.get("names") or {}).get(p) or p for p in pids})}
    for n in g.get("notes") or []:
        link = links.get(n.get("note_id"))
        if n.get("project_id") in marks and link is not None and is_caught(link):
            marks[n["project_id"]].add(_save_day(n, link))
    lo, hi = _day(g.get("since")) or "0000", _day(g.get("until")) or "9999"
    use: dict[str, set] = {}
    for tv, r in rows.items():
        # 在用的证据有两种: 回看期内的发牌日, 和接住的帖的存稿日。回看期内没发牌、却有接住的帖(翻更早的牌写)照样在用
        # —— 接住本身就证明写作台在出稿(codex review on TV#208); 两样都没有的才不算在用(D-053, 归判据 C)。
        use[tv] = {(date.fromisoformat(m) + timedelta(days=k)).isoformat()
                   for m in marks[tv] if m for k in range(USE_TAIL_DAYS + 1)}
        r["use_spans"] = _spans(use[tv], lo, hi)
    for n in g.get("notes") or []:
        r = rows.get(n.get("project_id"))
        if r is None:
            continue                    # 没映射写作台的 TV 项目: 本来就不在写作台写, 不算
        # 按日比: 当天发牌、当天发出去的算(接住的 lag_days p10 就是 0)
        judged = int(_day(n.get("publish_time")) in use[n["project_id"]])
        r["published"] += 1
        r["j_published"] += judged
        link = links.get(n["note_id"])
        if link is None:
            continue
        r["linked"] += 1
        r["j_linked"] += judged
        if not is_caught(link):
            continue
        r["caught"] += 1
        r["j_caught"] += judged
        d = diffs.get(n["note_id"])
        if d is None or (d.get("diff_rev") or 0) < CURRENT_DIFF_REV:
            continue                    # 没算过当前口径的差异: 不知道改没改, 不进未改动的分母
        r["diffed"] += 1
        r["unchanged"] += int(d.get("changed") is False)
        r["title_changed"] += int(bool(d.get("title_changed")))
    return {tv: r for tv, r in rows.items() if r["published"]}


def _active(r: dict) -> bool:
    """写作台在这个项目上在用: 回看期内发过牌, 或者窗口里有接住的帖(翻更早的牌写也算, codex review on TV#208)。"""
    return r["drawn"] > 0 or r["caught"] > 0


def _judgeable(r: dict) -> bool:
    """这个项目够不够格判。verdicts() 和 report() 的「没有项目够格判」都只调这里 —— 以前两处各写一遍, report 漏了
    八成那条: 唯一在用的项目对过账 15/100 时 verdicts() 跳过它, report 却打绿 ✓(codex review on TV#208)。
    两条八成和 unlinked() 的两条一一对应: 对过账够样本、却因为对账不全不够格判的, unlinked() 一定点名。"""
    return (_active(r)
            and r["j_linked"] >= MIN_PUBLISHED                          # 在用期里对过账够样本下限
            and r["j_linked"] >= r["j_published"] * MIN_LINKED_SHARE    # 在用期里的也大多对过账, 不然接住率是偏的子集
            # 整窗对过账不到八成的归 unlinked()「判不了」: 不能再同时喊「没被用上」把人往出稿质量上引
            and r["linked"] >= r["published"] * MIN_LINKED_SHARE)


def _span_text(r: dict) -> str:
    return "、".join(a[5:] if a == b else f"{a[5:]}~{b[5:]}" for a, b in r["use_spans"]) or "—"


def verdicts(rows: dict) -> list[dict]:
    """哪些 TV 项目在用写作台、在用期里发出去的帖却大多不是写作台的稿。纯函数。"""
    out = []
    for tv, r in sorted(rows.items()):
        if not _judgeable(r):
            continue
        share = r["j_caught"] / r["j_linked"]
        if share < MIN_CAUGHT_SHARE:
            out.append({"project": tv, "share": share, "linked": r["j_linked"], "caught": r["j_caught"],
                        "drawn": r["drawn"], "use_spans": r["use_spans"],
                        "detail": f"在用期 {_span_text(r)} 发布 {r['j_published']} 篇、对过账 {r['j_linked']} 篇、"
                                  f"接住 {r['j_caught']} 篇({share:.0%}); 整窗发布 {r['published']} 篇, 发牌 {r['drawn']}"})
    return out


def unlinked(rows: dict) -> list[dict]:
    """哪些 TV 项目发了不少帖、tv-sync 却大多没对过账(判不了)。纯函数。

    全局「一条链接都没有」那道 rc=2 管不到这种: aw 的 tv-sync 逐个项目跑, 一个项目出错只记一行、接着跑别的,
    别的项目照常对账, 合计的对过账 > 0; 这个项目在 verdicts() 里因为对过账不到下限被安静地跳过。
    两条任一条就点名: 整窗发布 >= 15 篇、对过账不到八成; 或者在用的项目在用期里发布 >= 15 篇、对过账不到八成 ——
    tv-sync 从某天起坏、这个项目又正好从某天起才用写作台, 没对上的扎堆在在用期里, 整窗合计还过八成; 只看整窗, 它会在
    _judgeable() 里被安静跳过、旁边别的项目照打 ✓(codex review on TV#208)。
    """
    out = []
    for tv, r in sorted(rows.items()):
        if r["published"] >= MIN_PUBLISHED and r["linked"] < r["published"] * MIN_LINKED_SHARE:
            detail = f"发布 {r['published']} 篇、对过账 {r['linked']} 篇"
        elif (_active(r) and r["j_published"] >= MIN_PUBLISHED
              and r["j_linked"] < r["j_published"] * MIN_LINKED_SHARE):
            detail = (f"在用期 {_span_text(r)} 发布 {r['j_published']} 篇、对过账 {r['j_linked']} 篇; "
                      f"整窗 {r['linked']}/{r['published']}")
        else:
            continue
        out.append({"project": tv, "published": r["published"], "linked": r["linked"], "detail": detail})
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
    draw_from = (g.get("draw_since") or "")[5:10]
    rate = (f"未改动率 {unchanged}/{diffed}({_pct(unchanged, diffed)})" if any_rev and diffed
            else "未改动率: 待重算")

    print()
    print("=" * 96)
    print(f"  写作台用上率 · 发布于 {span}(晚 {delay_days} 天看, 窗口 {window_days} 天"
          + (f"; 发牌看 {draw_from} 起" if draw_from else "") + f") · 发布 {pub} · "
          f"对过账 {linked} · 接住 {caught}({_pct(caught, linked)}) · {rate}")
    print("=" * 96)
    if not any_rev:
        print(f"  · tv_edit_diffs 里还没有 diff_rev >= {CURRENT_DIFF_REV} 的行(10-20 写作台部署后当晚 tv-sync 才重算)"
              " —— 旧口径把话题行和抄回去的副本都算成改过, 不拿它算未改动")
    if rows:
        print(f"  {'TV 项目':<20}{'发布':>6}{'对过账':>7}{'接住':>6}{'接住率':>7}{'未改动':>9}{'改标题':>7}"
              f"{'发牌':>6}{'在用天':>7}{'在用期内':>12}  写作台项目")
        for tv, r in sorted(rows.items(), key=lambda kv: (-kv[1]["published"], kv[0])):
            title = str(r["title_changed"]) if any_rev and r["diffed"] else "—"
            used = (str(sum((date.fromisoformat(b) - date.fromisoformat(a)).days + 1 for a, b in r["use_spans"]))
                    if r["use_spans"] else "—")
            judged = f"{r['j_caught']}/{r['j_linked']}/{r['j_published']}" if r["use_spans"] else "—"
            print(f"  {tv[:19]:<20}{r['published']:>6}{r['linked']:>7}{r['caught']:>6}"
                  f"{_pct(r['caught'], r['linked']):>7}{_unchanged_cell(r, any_rev):>9}{title:>7}"
                  f"{r['drawn']:>6}{used:>7}{judged:>12}  {'、'.join(r['desk'])[:40]}")
        print(f"  接住 = 对上写作台发布前存的那版; 未改动 = 接住且算过差异的里面原样发的(标题、正文一个字没动); "
              f"改标题 = 其中标题动过的。发牌数窗口起点前 {DRAW_LOOKBACK_DAYS} 天到终点(牌先发、帖后发); "
              f"在用天 = 窗口里算写作台在用的天数(每个发牌日、每篇接住的帖的存稿日起 {USE_TAIL_DAYS} 天); "
              f"在用期内 = 这些天发布的 接住/对过账/发布。判据只看在用期内: 写作台在用(发过牌或有接住)、在用期内对过账 >= {MIN_PUBLISHED} 篇"
              f"且占这些天发布八成以上、接住率 < {MIN_CAUGHT_SHARE:.0%}")

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

    if not any(_judgeable(r) for r in rows.values()):     # 和 verdicts() 同一条规则, 不另写(codex review on TV#208)
        print(f"  · 没有项目够格判: 写作台在用(发过牌或有接住)、在用期内发布的帖对过账够 {MIN_PUBLISHED} 篇且八成以上对过账的项目"
              f"一个都没有(不是健康, 是没活、量太小或对账不全; 发了帖、写作台零动静的看角度台账灯判据 C){blind_note}")
        return blind_rc
    hits = verdicts(rows)
    if not hits:
        print(f"  ✓ 没有项目命中: 写作台在用(发过牌或有接住)、在用期内对过账够 {MIN_PUBLISHED} 篇且八成以上对过账的项目, "
              f"在用期内发出去的帖至少 {MIN_CAUGHT_SHARE:.0%} 是写作台的稿{blind_note}")
        return blind_rc
    _warn("写作台的稿没被用上",
          f"{span} 发布的帖里, {len(hits)} 个项目写作台在用(发过牌或有接住的帖)、在用期里发出去的却大多不是写作台的稿: "
          + "; ".join(f"{h['project']}({h['detail']})" for h in hits)
          + " —— 写作台在用、稿子没被用上: 要么稿子没在写作台写(没查过重), 要么查过、在飞书里被整篇重写了(稿短、彼此像、"
            "版式不对)。光看链接分不清这两种, 看写作台这段时间查没查过这几个项目的稿: 发帖对账灯判据 C 那张表的「查重底稿」列"
            "(它默认看最近 7 天, 要盖住这里的窗口就手动跑 check_angle_ledger_leak.py --window-days 21)。"
            "查重底稿接近 0 = 没在写作台写, 判据 C 多半也亮着「写作台没查过这个项目一篇稿」, 先按那边查; "
            "查过不少稿、发出去的仍对不上 = 被重写, 修在 autowriter 仓(写作台出稿质量, TV docs/32 第一批 / 第二批), "
            "先看这几个项目的改稿差异摘要和最近几批稿子长什么样。写手没有存档这一步; TV 这边两种都改不好。")
    return 1


def gather(sb, since_iso: str, until_iso: str) -> dict:
    """读 tally() 要的行。只取 id、时间、对照类别和差异的三个标记, 不读任何正文。"""
    from _common import fetch_all_pages, fetch_vanished_note_ids  # 局部 import, 理由见文件头

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
    # 飞书里已删的篇(本项目最近一次完整同步没见到, 审计 B-21 / D-103)不算发出去的帖, 同闸二 / 策展 / 通道 1: 删前的
    # 快照之后没人维护, 删了又重贴的一篇会数成两篇(codex review on TV#208)。视图不在就直接抛(fetch_vanished_note_ids
    # 的约定): 不打哨兵、daily-sync 报崩, 好过静默把删了的篇算进分母。
    vanished = fetch_vanished_note_ids(sb)
    notes = [n for n in notes if n.get("project_id") in by_tv and n["note_id"] not in vanished]
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
    # 发牌不按发布窗口原样切(codex review on TV#208): 牌先发、稿后存、帖再发。原样切, 起点前两天发的一批、帖正好落在
    # 窗口里的项目读成零动静; 终点前一天为之后的帖发的一张牌, 又让这个项目拿窗口里更早的帖挨判。所以起点往前放
    # DRAW_LOOKBACK_DAYS 天, 并记下每个写作台项目这段里哪几天发过牌 —— tally() 拿它们(加接住的存稿日)划在用期, 只判
    # 在用期里发布的帖: 只记首牌的话, 起点前 6 天一张牌、之后再没动的项目会拿整窗的帖挨判。
    draw_since = (datetime.fromisoformat(since_iso)
                  - timedelta(days=DRAW_LOOKBACK_DAYS)).isoformat(timespec="seconds")
    drawn: dict[str, int] = {}
    drawn_days: dict[str, set] = {}
    for a in fetch_all_pages(
            sb.schema("autowriter").table("angle_ledger")
            .select("id, project_id, drawn_at")
            .gte("drawn_at", draw_since).lte("drawn_at", until_iso),
            order_by="id"):
        p = a.get("project_id")
        if p in pids:
            drawn[p] = drawn.get(p, 0) + 1
            if a.get("drawn_at"):
                drawn_days.setdefault(p, set()).add(_day(a["drawn_at"]))      # 按日, 同 tally() 的比法
    return {"map": by_tv, "names": _project_names(sb, pids), "notes": notes, "links": links,
            "diffs": diffs, "drawn": drawn, "drawn_days": {p: sorted(ds) for p, ds in drawn_days.items()},
            "any_rev2": any_rev2, "since": since_iso, "until": until_iso, "draw_since": draw_since}


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
    import itertools
    import types
    from pathlib import Path

    L = lambda kind, lag=0: {"match_kind": kind, "lag_days": lag}  # noqa: E731
    # ── 接住: 只认对上的五种, 且写作台那版不晚于发布 ───────────────────────────
    assert is_caught(L("body_exact")) and is_caught(L("edited", 3)) and is_caught(L("tv_lineage", None))
    assert not is_caught(L("body_exact", -3)), "发了之后才存进写作台的那版是抄回去的, 不算接住"
    assert not any(is_caught(L(k)) for k in ("ingested", "ambiguous", "unmatched"))

    # ── tally: 一个 TV 项目映射两个写作台项目, 发牌合起来算; 没映射的 TV 项目不进表 ──
    def G(notes, links=None, diffs=None, drawn=None, any_rev2=True, days=None):
        # days 不给 = 发过牌的项目一直在用(09-30 起每 7 天一张, 在用期盖住整个窗口、窗口里的帖全判); 给了就是在测在用期
        return {"map": {"AAA": ["d1", "d2"], "BBB": ["d3"]}, "names": {"d1": "甲台", "d2": "乙台"},
                "notes": notes, "links": links or {}, "diffs": diffs or {}, "drawn": drawn or {},
                "drawn_days": days if days is not None else {p: ["2026-09-30", "2026-10-07", "2026-10-14"]
                                                             for p in drawn or {}},
                "any_rev2": any_rev2, "since": "2026-10-05T08:00:00", "until": "2026-10-19T08:00:00"}

    N = lambda nid, tv="AAA", at="2026-10-12T08:00:00": {"note_id": nid, "project_id": tv, "publish_time": at}  # noqa: E731
    D = lambda changed, title=False, rev=2: {"changed": changed, "title_changed": title, "diff_rev": rev}  # noqa: E731
    g = G([N("a1"), N("a2"), N("a3"), N("a4"), N("a5", at="2026-10-07T23:00:00"), N("a6", at="2026-10-08T00:30:00"),
           N("a7"), N("x1", "ZZZ")],
          {"a1": L("body_exact"), "a2": L("fuzzy", 2), "a3": L("edited", None), "a4": L("title_exact", -6),
           "a5": L("ingested", None), "a7": L("edited", 1), "x1": L("body_exact")},
          {"a1": D(False), "a2": D(True, True), "a3": D(False, rev=1), "a4": D(False), "a7": D(True, False)},
          {"d1": 3, "d2": 4, "d3": 9}, days={"d1": ["2026-10-10"], "d2": ["2026-10-08"], "d3": ["2026-10-01"]})
    t = tally(g)
    assert set(t) == {"AAA"}, "没映射的 ZZZ 不算; BBB 窗口内一篇没发不出现"
    assert t["AAA"] == {"published": 7, "linked": 6, "caught": 4, "diffed": 3, "unchanged": 1, "title_changed": 1,
                        "drawn": 7, "use_spans": [("2026-10-08", "2026-10-19")],
                        "j_published": 6, "j_linked": 5, "j_caught": 4, "desk": ["乙台", "甲台"]}, t["AAA"]
    # a4 (lag −6) 不算接住, 它那行 changed=false 也不进未改动; a3 只有旧口径(rev 1)的行 → 不进分母。
    # a7 只改了正文(changed=T、title_changed=F, 最常见的一种): 未改动和改标题各数各的, 不能从同一个标记推出来。
    # 在用期: d1 / d2 合起来的发牌日 10-08、10-10, 加接住的存稿日(a2 10-12 − 2 = 10-10、a7 10-11、a1 / a3 10-12),
    # 各起 7 天 → 10-08 ~ 10-19(截到窗口终点); a5 10-07 发的在在用期之前 → 进发布 / 对过账两列、不进 j_*;
    # a6 和第一个发牌日同一天(按日比)→ 进 j_published

    # ── 判据: 下限真的在起作用 ─────────────────────────────────────────────────
    def R(linked, caught, drawn=5):
        return {"P": {"published": linked + 2, "linked": linked, "caught": caught, "diffed": 0, "unchanged": 0,
                      "title_changed": 0, "drawn": drawn, "use_spans": [("2026-10-05", "2026-10-19")] if drawn else [],
                      "j_published": linked + 2 if drawn else 0, "j_linked": linked if drawn else 0,
                      "j_caught": caught if drawn else 0, "desk": []}}
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
    late = {"P": dict(R(40, 0)["P"], j_published=20, j_linked=14, j_caught=0)}
    assert verdicts(late) == [], "整窗对过账 40 篇, 在用期里只有 14 篇: 判据数在用期的, 不够 15 篇不判"
    skew = {"P": dict(R(40, 0)["P"], j_published=30, j_linked=20, j_caught=0)}
    assert verdicts(skew) == [] and [u["project"] for u in unlinked(skew)] == ["P"], \
        "在用期 30 篇只对过 20 篇(不到八成): 偏的子集不判, 点名判不了(整窗 40/42 过八成也要点)"
    # 对过账够样本、却因为对账不全(整窗或在用期)不够格判的, unlinked() 一定点名 —— 不会两边都不出声
    for pub, lk, jp, jl in itertools.product((15, 20, 40, 100), (15, 20, 30, 40, 100), (15, 20, 30, 40),
                                             (15, 20, 30, 40)):
        if jl <= lk <= pub and jl <= jp <= pub and jp - jl <= pub - lk:
            r = dict(R(15, 0)["P"], published=pub, linked=lk, j_published=jp, j_linked=jl, j_caught=0)
            assert _judgeable(r) or unlinked({"P": r}), (pub, lk, jp, jl)

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
    assert "查重底稿" in out and "判据 C" in out and "被重写" in out, "亮黄要说清怎么和判据 C 的「没在写作台写」分开"
    assert "写完没存档" not in out and "查 score_drafts 存档" not in out, "写手没有存档这一步(D-132)"

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
    assert "且八成以上对过账的项目, 在用期内发出去的帖至少 20%" in out, "✓ 那句要说全 _judgeable 的规则, 不能比它宽"
    none = {f"n{i:02d}": L("unmatched") for i in range(20)}
    rc, out = run(G(many, none, {}, {}))
    assert rc == 0 and "没有项目够格判" in out and "没被用上" not in out, "没发牌、也一篇没接住: 没在用, 归判据 C"
    # 回看期内没发牌、却有接住的帖(翻更早的牌写): 接住证明在用, 照判(codex review on TV#208)
    rc, out = run(G(many, low, {}, {}))
    assert rc == 1 and "AAA(在用期" in out and "接住 2 篇(10%)" in out, out
    assert "发了牌" not in out and "写作台在用(发过牌或有接住的帖)" in out, "只靠接住证明在用的不能说成发过牌(发牌 0)"

    # ── 一个项目的 tv-sync 坏了、别的照常: 合计对过账 > 0, 那个项目要点名报判不了(rc=2), 不能安静跳过 ──
    bbb = [N(f"b{i:02d}", "BBB") for i in range(20)]
    rc, out = run(G(many + bbb, ok, {}, {"d1": 1, "d3": 5}))
    assert rc == 2 and "BBB(发布 20 篇、对过账 0 篇)" in out and "tv-sync 漏了" in out and "AAA(" not in out, out
    assert "✓" in out and "判不了的项目不在内" in out, "AAA 照常判"
    rc, out = run(G(many + bbb, none, {}, {"d3": 5}))      # AAA 没发牌也没接住(不在用), 只有 BBB 在用
    assert rc == 2 and "没有项目够格判" in out and "BBB(" in out, "BBB 发过牌但没对过账: 不能落进「没有项目够格判」rc=0"
    rc, out = run(G(many + bbb, ok, {}, {"d3": 5}))        # AAA 没发牌、20 篇全接住: 接住证明在用, 照判
    assert rc == 2 and "BBB(" in out and "✓" in out and "没有项目够格判" not in out, out
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

    # ── 够不够格判和 verdicts() 是同一条 _judgeable: 唯一在用的项目对过账 15/100, 只能报判不了, 不能接着打绿 ✓ ──
    hund = [N(f"p{i:03d}") for i in range(100)]
    rc, out = run(G(hund, {f"p{i:03d}": L("fuzzy", 1) for i in range(15)}, {}, {"d1": 2}))
    assert rc == 2 and "没有项目够格判" in out and "✓" not in out and "AAA(发布 100 篇、对过账 15 篇)" in out, out

    # ── 在用期: 每个发牌日 / 接住的存稿日起 7 天; 首牌之前、末牌 7 天之后、中间停的那几天发的帖不判(codex review on TV#208) ──
    ing = lambda ns: {n["note_id"]: L("ingested", None) for n in ns}  # noqa: E731
    spread = [N(f"s{i:02d}", at=f"2026-10-{5 + i % 14:02d}T08:00:00") for i in range(20)]    # 10-05 ~ 10-18
    rc, out = run(G(spread, ing(spread), {}, {"d1": 1}, days={"d1": ["2026-10-18"]}))
    assert rc == 0 and "没有项目够格判" in out and "没被用上" not in out, \
        "窗口末尾才发第一张牌(为之后的帖发的): 不拿窗口前段那些帖判它"
    rc, out = run(G(spread, ing(spread), {}, {"d1": 1}, days={"d1": ["2026-09-29"]}))
    assert rc == 0 and "没有项目够格判" in out and "没被用上" not in out, \
        "只在回看里(起点前 6 天)发过一张牌、之后再没动: 那批稿 10-03 前后就发完了, 不拿整窗手写的帖判它"
    after = [N(f"t{i:02d}", at=f"2026-10-{13 + i % 6:02d}T08:00:00") for i in range(20)]  # 起点 7 天之后
    rc, out = run(G(after, ing(after), {}, {"d1": 10}, days={"d1": ["2026-09-29"]}))
    assert rc == 0 and "没有项目够格判" in out and "没被用上" not in out, "起点前 6 天发了 10 张、之后停用"
    # 一直在用(每三天一张): 在用期盖住整窗, 判的就是整窗 —— 和不切一样
    every = {"d1": ["2026-09-30", "2026-10-03", "2026-10-06", "2026-10-09", "2026-10-12", "2026-10-15", "2026-10-18"]}
    lows = {**ing(spread), "s00": L("fuzzy", 0), "s01": L("fuzzy", 0)}
    t = tally(G(spread, lows, {}, {"d1": 7}, days=every))["AAA"]
    assert (t["j_published"], t["j_linked"], t["j_caught"]) == (t["published"], t["linked"], t["caught"]) == (20, 20, 2)
    rc, out = run(G(spread, lows, {}, {"d1": 7}, days=every))
    assert rc == 1 and "AAA(在用期 10-05~10-19 发布 20 篇、对过账 20 篇、接住 2 篇(10%); 整窗发布 20 篇, 发牌 7)" in out, out
    # 中间停了一阵(09-29 一张, 10-15 再用): 10-08 ~ 10-13 手写的 20 篇不判
    gap = [N(f"h{i:02d}", at=f"2026-10-{8 + i % 6:02d}T08:00:00") for i in range(20)]
    back = [N(f"k{i:02d}", at="2026-10-16T08:00:00") for i in range(16)]
    rc, out = run(G(gap + back, {**ing(gap + back), **{f"k{i:02d}": L("fuzzy", 1) for i in range(4)}}, {}, {"d1": 2},
                    days={"d1": ["2026-09-29", "2026-10-15"]}))
    assert rc == 0 and "✓" in out, "在用期内 4/16(25%) 不喊; 停用那几天的 20 篇不往下拉(整窗 4/36 = 11%)"
    assert row_of(out, "AAA")[8:10] == ["7", "4/16/16"], row_of(out, "AAA")     # 10-05~10-06、10-15~10-19
    pre = [N(f"q{i:02d}", at="2026-10-08T08:00:00") for i in range(20)]
    post = [N(f"r{i:02d}", at="2026-10-14T20:00:00") for i in range(16)]
    lk = {**ing(pre), **{f"r{i:02d}": L("unmatched", None) for i in range(16)}}
    rc, out = run(G(pre + post, {**lk, **{f"r{i:02d}": L("fuzzy", 0) for i in range(4)}}, {}, {"d1": 2},
                    days={"d1": ["2026-10-14"]}))
    assert rc == 0 and "✓" in out, "在用期内 4/16(25%) 不喊; 首牌前 20 篇补录的不往下拉(整窗 4/36 = 11%)"
    rc, out = run(G(pre + post, {**lk, "r00": L("fuzzy", 0)}, {}, {"d1": 2}, days={"d1": ["2026-10-14"]}))
    assert rc == 1 and "AAA(在用期 10-14~10-19 发布 16 篇、对过账 16 篇、接住 1 篇(6%); 整窗发布 36 篇" in out, out
    cols = row_of(out, "AAA")       # … 发牌 在用天 在用期内(接住/对过账/发布) 写作台项目; 发布 / 对过账 / 接住仍数整窗
    assert cols[1:4] == ["36", "36", "1"] and cols[7:10] == ["2", "6", "1/16/16"], cols
    # 接住的帖证明那几天在用(翻旧牌写、没抽新牌, 或那批牌在回看之外): 首牌(10-10)前 20 篇接住(存稿 10-03)
    early = [N(f"c{i:02d}", at="2026-10-06T08:00:00") for i in range(20)]
    later = [N(f"m{i:02d}", at="2026-10-12T08:00:00") for i in range(16)]
    rc, out = run(G(early + later, {**{f"c{i:02d}": L("body_exact", 3) for i in range(20)}, **ing(later),
                                    "m00": L("fuzzy", 0), "m01": L("fuzzy", 0)}, {}, {"d1": 2},
                    days={"d1": ["2026-10-10"]}))
    assert rc == 0 and "✓" in out and "没被用上" not in out, "在用期内 22/36(61%), 不能只拿首牌后 2/16 判"
    # 末牌之后照存稿: 10-01 一张牌, 10-16 又有接住的帖(存稿 10-15) —— 10-15 起也在用, 一起判
    first16 = [N(f"e{i:02d}", at="2026-10-06T08:00:00") for i in range(16)]
    tail = [N(f"f{i:02d}", at="2026-10-16T08:00:00") for i in range(10)] + \
        [N(f"u{i:02d}", at="2026-10-17T08:00:00") for i in range(6)]
    rc, out = run(G(first16 + tail, {**ing(first16 + tail), **{f"f{i:02d}": L("body_exact", 1) for i in range(10)}},
                    {}, {"d1": 1}, days={"d1": ["2026-10-01"]}))
    assert rc == 0 and "✓" in out, "在用期 10-05~10-08、10-15~10-19 里 10/32(31%); 只按牌划只剩 10-06 那 16 篇, 冒假黄"
    assert row_of(out, "AAA")[8:10] == ["9", "10/32/32"], row_of(out, "AAA")

    # ── 在用期里大多没对过账、整窗还过八成: 点名判不了, 不能落进 ✓ 或「没有项目够格判」rc=0(codex review on TV#208) ──
    old100 = [N(f"o{i:03d}", at="2026-10-06T08:00:00") for i in range(100)]
    fresh = [N(f"w{i:02d}", at="2026-10-14T08:00:00") for i in range(30)]
    lk = {**ing(old100), **ing(fresh[:15])}         # 整窗 115/130 = 88%; 在用期(10-14 起)15/30
    rc, out = run(G(old100 + fresh, lk, {}, {"d1": 3}, days={"d1": ["2026-10-14"]}))
    assert rc == 2 and "没有项目够格判" in out and "✓" not in out \
        and "AAA(在用期 10-14~10-19 发布 30 篇、对过账 15 篇; 整窗 115/130)" in out, out
    bbb_ok = {f"b{i:02d}": L("fuzzy", 1) for i in range(20)}
    rc, out = run(G(old100 + fresh[:20] + bbb, {**ing(old100), **bbb_ok}, {}, {"d1": 3, "d3": 5},
                    days={"d1": ["2026-10-14"], "d3": ["2026-10-07"]}))
    assert rc == 2 and "AAA(在用期 10-14~10-19 发布 20 篇、对过账 0 篇; 整窗 100/120)" in out \
        and "✓" in out and "判不了的项目不在内" in out, "tv-sync 从 10-14 起漏了 AAA: 点名, BBB 照常 ✓"
    assert row_of(out, "AAA")[9] == "0/0/20", "在用期内一格要露出没对上的 20 篇, 不能是 0/0"

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

    INWIN, OLD, LATER = "2026-10-08T08:00:00", "2026-09-20T08:00:00", "2026-10-20T08:00:00"
    PRE = "2026-10-01T08:00:00"         # 窗口起点(10-05)前 4 天发的牌: 回看 7 天之内, 帖(10-08)正好落在窗口里、牌后第 7 天
    NOTES = ([{"note_id": f"a{i:03d}", "project_id": "AAA", "publish_time": INWIN} for i in range(230)]
             + [{"note_id": "old1", "project_id": "AAA", "publish_time": OLD},
                {"note_id": "late1", "project_id": "AAA", "publish_time": LATER},
                {"note_id": "z1", "project_id": "ZZZ", "publish_time": INWIN},
                {"note_id": "gone1", "project_id": "AAA", "publish_time": INWIN}])    # 飞书里已删
    LINKS = ([{"note_id": f"a{i:03d}", "tv_project_id": "AAA", "project_id": "d1", "version_id": f"v{i}",
               "match_kind": "body_exact" if i < 210 else "unmatched", "lag_days": 1 if i else -2}
              for i in range(230)]
             + [{"note_id": n, "tv_project_id": t, "project_id": "d1", "version_id": "vx",
                 "match_kind": "body_exact", "lag_days": 0} for n, t in (("old1", "AAA"), ("late1", "AAA"),
                                                                          ("z1", "ZZZ"), ("gone1", "AAA"))])
    DIFFS = [{"note_id": "a001", "changed": False, "title_changed": False, "diff_rev": 2},
             {"note_id": "a002", "changed": False, "title_changed": False, "diff_rev": 1},
             {"note_id": "a205", "changed": True, "title_changed": True, "diff_rev": 2},
             {"note_id": "old1", "changed": False, "title_changed": False, "diff_rev": 2}]
    LEDGER = [{"id": f"g{i}", "project_id": p, "drawn_at": at}
              for i, (p, at) in enumerate([("d1", INWIN), ("d1", INWIN), ("d1", OLD), ("d1", LATER),
                                            ("dx", INWIN), ("d1", PRE)])]
    # d1 那张 LATER(窗口之后才发)的牌不能算: 最近 7 天才开始发牌的项目, 不能拿 7~21 天前它不可能写的帖判它。
    # OLD(9-20)在回看 7 天(9-28 起)之外也不算; PRE(10-01)要算, 首牌就是它
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
    vanished_calls: list = []
    fake.fetch_vanished_note_ids = lambda _sb, project_id=None: (vanished_calls.append(project_id), {"gone1"})[1]
    sys.modules["_common"] = fake
    try:
        gg = gather(SB(), "2026-10-05T08:00:00", "2026-10-19T08:00:00")
        assert [n["note_id"] for n in gg["notes"]] == [f"a{i:03d}" for i in range(230)], \
            "窗口外的(9 月的、排期还没发的)、没映射的 ZZZ、飞书里已删的 gone1 都不该进来"
        assert vanished_calls == [None], "已删名单读一次、全库(按项目筛会漏映射的别的项目)"
        assert all(n <= CHUNK for _, n in calls) and ("tv_note_links", 30) in calls, calls
        assert set(gg["diffs"]) == {"a001", "a205"}, "差异只取接住的、当前口径的(a002 是 rev 1, old1 在窗口外)"
        assert gg["drawn"] == {"d1": 3} and gg["any_rev2"] is True and gg["names"] == {"d1": "甲台"}, gg["drawn"]
        assert gg["drawn_days"] == {"d1": ["2026-10-01", "2026-10-08"]} and gg["draw_since"] == "2026-09-28T08:00:00", \
            (gg["drawn_days"], gg.get("draw_since"))
        tt = tally(gg)["AAA"]
        assert (tt["published"], tt["linked"], tt["caught"], tt["diffed"], tt["unchanged"]) == (230, 230, 209, 2, 1), tt
        # a000 的写作台那版晚于发布(lag −2): 不算接住 —— 209 而不是 210
        # 只在窗口起点前几天发过一批牌的项目, 帖落在窗口里: 是在用写作台, 要判(以前按发布窗口切发牌, 读成零动静)
        TABLES["angle_ledger"] = [r for r in LEDGER if r["drawn_at"] == PRE]
        rc, out = run(gather(SB(), "2026-10-05T08:00:00", "2026-10-19T08:00:00"))
        assert rc == 0 and "✓" in out and "没有项目够格判" not in out and "发牌看 09-28 起" in out, out
        TABLES["tv_note_links"] = [dict(r, match_kind="ingested", lag_days=None) for r in LINKS]
        rc, out = run(gather(SB(), "2026-10-05T08:00:00", "2026-10-19T08:00:00"))
        assert rc == 1 and "AAA(在用期 10-05~10-08 发布 230 篇、对过账 230 篇、接住 0 篇(0%)" in out, \
            "没有接住的帖垫着, 光凭 10-01 那张牌也要判(在用期到牌后第 7 天 10-08 为止, 含当天)"
        TABLES["tv_note_links"] = LINKS
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
          "够格判与判据同一条 / 判不了 rc=2(整窗或在用期对账不全) / 发牌回看 7 天 + 在用期 / 已删的篇不算 / "
          "取数窗口按 publish_time、分批、翻页键唯一 / 哨兵行 / 每周一接线")
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
