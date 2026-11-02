#!/usr/bin/env python3
"""
check_external_shelf.py —— 外部参考书架 (D-117 ②, D-138; prompts/external_shelf_v1.json + librarian/external.py) 的离线守卫。

  §1 配置: D-138 的值 (评论 ≥20、发出 ≤90 天、每次至少 1 张最多 2 张、每品类给模型看 6 张)、一个品牌不许挂两个品类、
     品牌 → 品类整张表钉死 (写作台 aw deskcore/priors.py 的 EXT_CATEGORY_BY_PROJECT 照抄这张, 那边也钉着同一张)
  §2 同品类: 只看 brief 的品牌 / 项目名 (项目定位里顺嘴提到「戒烟」不算), 大小写不敏感; 西屋 / Hatherine / 百健士三个新品类
  §3 达标: 发帖时间从 note_id 解; 抓到时发出 3–90 天、最近 45 天抓到; 评论够; 日均评论 (分母至少 3 天) 不低于同品类中位数;
     Jev 判了没带产品 + 不像广告 + 没点到我们登记的品牌; 没判过的不收
  §4 排序和卡面: 品类内按日均评论从高到低、中位数算全体 (带产品 / 评论少的也算); rank_score 是百分位; 卡上有发出几天、
     日均评论、结构题; id 带 ext: 前缀、没有品牌、别家品牌名换成「某品牌」(D-120); 有外部卡时 prompt 才多那句用法
     (至少 1 张、最多 2 张, 不再「优先挑帆谷自己的卡」); 「已验证爆款」只说帆谷自己的卡; 命中规律的优先只在内部卡之间比
  §5 缓存版本: 外部卡 (连卡面、结构) 进版本串; 发出几天不进; 没有外部卡时与以前一样
  §6 端到端 (打桩): 老消费方不给; 两臂都给; 模型挑多了截到 2 张 (不算契约失败), 截掉的不占 5 张的名额;
     一张没挑就补日均最高的那张 (forced, 进缓存); 满 5 张才顶 rank 最低的内部卡; 摘录截到 600 字;
     查库挂了 / 品类还没有外部帖照样选内部卡; 外部卡不去查 note 的规律答案; 部署前的缓存行补上 external / validated_hits;
     命中缓存时发出几天按 id 重算; 书架按品类在进程里缓存 10 分钟 (查库失败不缓存), 只拉最近 45 天抓到的
  §7 接线: 方向复核那盏灯报书架达标数, 用的是同一个 qualified

跑法: cd scripts && python check_external_shelf.py
"""
from __future__ import annotations

import json
import logging
import pathlib
import sys
import time
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from librarian import core, external as X, patterns as P  # noqa: E402

CFG = X.load_config()
DAY = 86400

# 品牌 → 品类整张表 (D-138)。改这里 = 改 prompts/external_shelf_v1.json 的 categories, 同一个 PR 里 aw 那份跟着改。
BRAND_TABLE = {
    "戒烟": ["力克雷", "nicorette"],
    "鼻炎": ["雷诺考特"],
    "运动补给": ["sportsix"],
    "术后营养": ["大象集团", "nucare"],
    "求职留学": ["途鸽"],
    "家居家电": ["西屋"],
    "个护": ["hatherine"],
    "藻油": ["百健士"],
}


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def ext_row(tag: int, comments: int, age_days: float, *, now: float, fetched_days_ago: float = 1, **kw) -> dict:
    """一篇外部帖: note_id 前 8 位十六进制 = 发帖时刻 (抓到时发出 age_days 天), 后面 16 位用 tag 区分。"""
    fetched = float(int(now - fetched_days_ago * DAY))     # 整秒: note_id 里的发帖时刻也是整秒
    row = {"note_id": f"{int(fetched - age_days * DAY):08x}{tag:016x}", "category": "鼻炎", "title": "换季鼻子又罢工了",
           "body": "求问大家都怎么熬过去的", "comments": comments, "has_product": False, "ad_like": False,
           "fetched_at": _iso(fetched)}
    row.update(kw)
    return row


def s1_config() -> None:
    assert CFG, "配置读不了"
    assert (CFG["min_comments"], CFG["max_age_days"], CFG["min_external"], CFG["max_per_borrow"],
            CFG["show_per_request"]) == (20, 90, 1, 2, 6), "D-138: 评论 ≥20、发出 ≤90 天、至少 1 张、最多 2 张、给模型看 6 张"
    assert X.min_external() == 1 and X.max_per_borrow() == 2
    assert CFG["categories"] == BRAND_TABLE, f"品牌 → 品类表变了, aw EXT_CATEGORY_BY_PROJECT 要跟着改: {CFG['categories']}"
    seen: dict = {}
    for cat, brands in CFG["categories"].items():
        assert brands, f"{cat}: 没登记品牌"
        for b in brands:
            assert b.lower() not in seen, f"{b} 同时挂在 {seen[b.lower()]} 和 {cat}"
            seen[b.lower()] = cat
    bad = pathlib.Path(__file__).with_name("_bad_shelf.json")
    logging.disable(logging.WARNING)          # 下面两份坏配置各打一条带堆栈的 warning, 是要的, 不刷屏
    try:
        for patch in ({"min_external": 3}, {"max_age_days": 2}):
            bad.write_text(json.dumps({**CFG, **patch}), encoding="utf-8")
            assert X.load_config(bad) is None and X.shelf_for(None, {"brand": "途鸽"}, path=bad) == [], \
                f"配置不合理 ({patch}) 就整份不用, 不给外部卡"
            X._cache.pop(str(bad), None)
    finally:
        logging.disable(logging.NOTSET)
        bad.unlink(missing_ok=True)
    print(f"  §1 配置: {len(CFG['categories'])} 个品类、评论 ≥{CFG['min_comments']}、发出 ≤{CFG['max_age_days']} 天、"
          f"每次 {CFG['min_external']}–{CFG['max_per_borrow']} 张、给模型看 {CFG['show_per_request']} 张、品牌表钉死 ✓")


def s2_match() -> None:
    f = lambda **b: X.categories_for(b, CFG)  # noqa: E731
    assert f(brand="雷诺考特") == ["鼻炎"]
    assert f(brand="sportsix") == f(brand="SPORTSIX") == ["运动补给"]
    assert f(brand="途", project_name="途鸽D-4情绪价值与社会化") == ["求职留学"]
    assert f(brand="唐小轻", project_name="唐小轻-流量-家庭叙事", system_prompt="爸爸戒烟那年…") == [], \
        "只看品牌 / 项目名: 项目定位里提到戒烟不等于做戒烟品类"
    assert f(brand="RIO") == [] and f() == []
    # D-138: 写作台在用的三个项目 (品牌 / 项目名照写作台 projects 表的写法)
    assert f(brand="西屋", project_name="西屋911gt") == f(brand="西屋", project_name="西屋911GT") == ["家居家电"]
    assert f(brand="Hatherine", project_name="Hatherine痘痘贴") == f(brand="hatherine", project_name="hatherine-D3") == ["个护"]
    assert f(brand="百健士", project_name="百健士成人藻油") == f(brand="百健士", project_name="百健士-藻油") == ["藻油"]
    assert f(brand="岸深", project_name="岸深-冲牙器") == [], "TV 里同是个护的别的品牌没登记, 不给 (Jev 个护抓的是另一类帖)"
    print("  §2 同品类: 只看品牌 / 项目名、大小写不敏感、西屋 / Hatherine / 百健士 ✓")


def s3_qualifies() -> None:
    now = time.time()
    assert X.posted_at("6aa34a0b" + "0" * 16) == float(0x6AA34A0B), "前 8 位十六进制就是 unix 秒"
    assert X.posted_at("abc") is None and X.posted_at("zzzzzzzz00") is None and X.posted_at(None) is None
    r = ext_row(1, 60, 10, now=now)
    assert abs(X.age_at_scrape(r) - 10) < 1e-6 and abs(X.velocity(r) - 6.0) < 1e-6
    assert abs(X.velocity(ext_row(1, 60, 1, now=now)) - 20.0) < 1e-6, "日均评论的分母至少 3 天"
    assert X.velocity(ext_row(1, 60, 10, now=now, fetched_at=None)) is None, "抓取时间不知道就算不了"
    assert X.velocity(dict(r, note_id="abc")) is None, "发帖时间解不出就算不了"

    ok = lambda row, med=0.1: X.qualifies(row, CFG, med, now=now)  # noqa: E731
    assert ok(r)
    assert ok(ext_row(1, 60, 3, now=now)) and not ok(ext_row(1, 60, 2.9, now=now)), "发出不到 3 天评论还在涨, 不算"
    assert ok(ext_row(1, 60, 90, now=now)) and not ok(ext_row(1, 60, 90.5, now=now)), "发出超过 90 天不算「最近」"
    assert ok(ext_row(1, 60, 10, now=now, fetched_days_ago=44)) and \
        not ok(ext_row(1, 60, 10, now=now, fetched_days_ago=46)), "只看最近 45 天抓到的"
    assert not ok(dict(r, note_id="abc")), "发帖时间解不出的不收"
    assert ok(dict(r, comments=20)) and not ok(dict(r, comments=19)), "评论 ≥20"
    assert ok(r, 6.0) and not ok(r, 6.01), "日均评论不低于同品类中位数"
    assert not ok(r, None), "品类没有可比的帖 (没有中位数) 不收"
    assert ok(dict(r, ad_like=None))
    assert not ok(dict(r, has_product=True)) and not ok(dict(r, has_product=None)), "没判过有没有产品的不收"
    assert not ok(dict(r, ad_like=True))
    assert ok(dict(r, body=f"后来换了{CFG['mask_terms'][0]}")), "D-120: 点了别家品牌的照收, 上架时换成「某品牌」"
    assert not ok(dict(r, title="雷诺考特用了一周")), "点了登记品牌 (可能就是我们自己铺的) 不上架"
    assert not ok(dict(r, body="试过 SPORTSIX 的胶")), "登记品牌大小写不敏感"
    assert not ok(dict(r, body="西屋的按摩椅坐了一周")), "新登记的品牌一样挡"
    print("  §3 达标: note_id 解发帖时间 / 3–90 天 / 最近 45 天抓到 / 评论 ≥20 / 日均不低于中位数 / 没产品 / 不像广告 / "
          "没点我们登记的品牌 ✓")


CARD = {"source_note_id": "n1", "tier": "爆", "brand": "雷诺考特", "category": "OTC药", "rank_score": 1.0,
        "curated_at": "2026-10-01", "is_curated": True, "hook_type": "h", "structure": "s",
        "why_it_worked": "w", "transferable_tactic": "t", "raw_excerpt": "e", "synthetic": False}


def s4_order_and_card() -> None:
    now = time.time()
    rows = [ext_row(0, 30, 3, now=now),                                   # 日均 10
            ext_row(1, 200, 40, now=now),                                 # 日均 5: 低于中位数 8, 不上架
            ext_row(8, 400, 50, now=now),                                 # 日均 8: 总评论最多, 达标但排在日均 10 的后面
            ext_row(2, 60, 6, now=now),                                   # 日均 10  (同速按 note_id)
            ext_row(3, 900, 10, now=now, has_product=True),               # 日均 90: 带产品不上架, 但算进中位数
            ext_row(4, 5, 5, now=now), ext_row(5, 4, 4, now=now),         # 日均 1 / 1: 评论不够, 也算进中位数
            ext_row(6, 3000, 400, now=now),                               # 发出太久: 不进中位数、不上架
            ext_row(7, 40, 20, now=now, category="戒烟")]                  # 另一个品类自己算中位数
    got = X.qualified(rows, CFG, now=now)
    ids = [r["note_id"] for r, _, _ in got]
    by = {r["note_id"]: (v, p) for r, v, p in got}
    nid = lambda tag: next(r["note_id"] for r in rows if r["note_id"].endswith(f"{tag:016x}"))  # noqa: E731
    want = sorted([nid(0), nid(2)]) + [nid(8), nid(7)]
    assert ids == want, ("品类内按日均评论从高到低 (同速按 note_id), 不按总评论数; 中位数算全体 (带产品 / 评论少的也算: "
                         f"1,1,5,8,10,10,90 → 8): {ids}")
    assert nid(1) not in by, "日均 5 低于中位数, 不上架"
    assert abs(by[nid(0)][1] - 5 / 7) < 1e-9, "百分位 = 中位秩 / 同品类篇数 (10 排在 7 篇的第 5、6 位 → 5/7)"
    assert by[nid(7)][1] == 0.5, "只有一篇的品类: 它就是中位数, 达标, 百分位 0.5"

    fq = {"opening_type": "具体事件", "turning_point": "是", "ending_asks_reader": "是", "asks_for_help": "否",
          "own_experience": "是", "title_is_question": "否", "efficacy_promise": "是"}
    c = X.to_card(rows[0], CFG, rate=by[nid(0)][0], pct=by[nid(0)][1], fq=fq, now=now)
    assert c["source_note_id"] == f"ext:{nid(0)}" and c["external"] is True and c["brand"] is None
    assert c["posted_days_ago"] == 4 and c["comments_per_day"] == 10.0 and c["rank_score"] == round(5 / 7, 3)
    assert "efficacy_promise" not in c["fq"] and c["fq"]["opening_type"] == "具体事件", "卡上只带结构题"
    assert c["structure"] == "开头先讲一件具体的事；中间有一次前后转折；讲的是自己的经历；结尾问了读者", c["structure"]
    assert "每天约 10.0 条评论" in c["why_it_worked"] and "快过同品类近期 71% 的帖" in c["why_it_worked"]
    assert X.describe({"opening_type": "其他"}) is None and X.describe(None) is None

    txt = core.build_system_blocks({}, [CARD, c])[0]["text"]
    assert f"[ext:{nid(0)}] 外部参考|鼻炎｜别家同品类最近涨得快的帖, 只借结构不抄内容" in txt
    assert "发出约 4 天 · 每天约 10.0 条评论 · 共 30 条" in txt and "结构: 开头先讲一件具体的事" in txt
    assert "至少挑 1 张、最多 2 张" in txt and txt.index("至少挑 1 张") < txt.index("候选经验卡")
    assert "优先挑帆谷自己的卡" not in txt, "D-138: 不再让模型同样合适时先挑内部卡"
    assert "至少挑" not in core.build_system_blocks({}, [CARD])[0]["text"], "没有外部卡时 prompt 不变"
    head = core.ROLE_TASK_INSTR.split("你的任务")[0]
    assert "帆谷自己的卡是\n【已验证爆款/值得参考】" in head and "外部参考" in head, "「已验证爆款」只说帆谷自己的卡"
    rules = P.render_block({"patterns": [{"label": "L", "instruction": "i", "evidence": "e"}]})
    assert "帆谷自己的卡里, 下面标了「命中已验证规律」的, 同样合适时优先借" in rules and "不因此少挑外部卡" in rules
    # D-120: 别家品牌名换成「某品牌」, 不分大小写, 长的先换
    # 别家品牌名从配置里取, 不在这里另写一份 (本仓公开)
    a, b = [t for t in CFG["mask_terms"] if not t.isascii()][:2]
    latin = next(t for t in CFG["mask_terms"] if t.isascii())
    m = X.to_card(dict(rows[0], title=f"{a}和{b}我都试过", body=f"后来朋友推荐 {latin.upper()} 的胶"), CFG)["raw_excerpt"]
    assert all(t.lower() not in m.lower() for t in (a, b, latin)), m
    assert m.count(X.MASK) == 3, m
    assert X.mask_brands("雅培安素", {"mask_terms": ["雅培", "雅培安素"]}) == X.MASK, "长的先换, 不留半截"
    assert X.mask_brands("没有品牌", None) == "没有品牌" and X.mask_brands("", CFG) == ""
    print("  §4 排序和卡面: 按日均评论排、中位数算全体、百分位当 rank_score; 卡上有发出几天 / 日均评论 / 结构; "
          "至少 1 张最多 2 张、不再优先内部卡; 「已验证爆款」只说内部卡; 别家品牌名换成「某品牌」 ✓")


def s5_version() -> None:
    now = time.time()
    cards = [CARD]
    base = core.library_version(cards, gate2_run="g")
    assert core.library_version(cards, gate2_run="g", external=None) == base
    a, b = X.to_card(ext_row(1, 60, 10, now=now)), X.to_card(ext_row(2, 60, 10, now=now))
    assert X.digest([a, b]) == X.digest([b, a])
    v1 = core.library_version(cards, gate2_run="g", external=X.digest([a]))
    v2 = core.library_version(cards, gate2_run="g", external=X.digest([a, b]))
    assert len({base, v1, v2}) == 3
    # mask_terms 补了一个品牌: id 没变, 卡面变了 → 版本必须变, 否则旧缓存里没换掉品牌名的摘录一直被命中
    r = ext_row(1, 60, 10, now=now, body="后来用了新牌子")
    masked = X.to_card(r, {**CFG, "mask_terms": CFG["mask_terms"] + ["新牌子"]})
    plain = X.to_card(r, CFG)
    assert masked["source_note_id"] == plain["source_note_id"] and X.digest([masked]) != X.digest([plain])
    assert X.digest([X.to_card(r, CFG, fq={"turning_point": "是"})]) != X.digest([plain]), "结构题晚到, 版本也要变"
    assert X.digest([X.to_card(r, CFG, now=now + 3 * DAY)]) == X.digest([plain]), "发出几天每天都变, 不进版本"
    print("  §5 缓存版本: 外部卡(连卡面、结构)进版本串、发出几天不进、没有时不变 ✓")


class _Q:
    def __init__(self, rows, log):
        self.rows, self.log = rows, log

    def __getattr__(self, name):
        def f(*a, **k):
            self.log.append((name, a))
            return self
        return f

    def execute(self):
        if isinstance(self.rows, Exception):
            raise self.rows
        return type("R", (), {"data": self.rows})()


class _SB:
    def __init__(self, rows):
        self.rows, self.log = rows, []

    def schema(self, s):
        return self

    def table(self, t):
        self.log.append(("table", (t,)))
        return _Q(self.rows, self.log)


def _sel(ids):
    return json.dumps({"selected": [{"source_note_id": i, "why_relevant": "r", "borrow_what": "b"} for i in ids]})


def s6_end_to_end() -> None:
    now = time.time()
    long_body = "长" * 1500
    # e0..e3 日均 40 / 30 / 20 / 10; 带产品那篇日均 300 (不上架); 四篇评论不够的慢帖把中位数拉到 e3 (9 篇的第 5 篇)
    rows = [ext_row(i, (4 - i) * 100, 10, now=now, body=long_body if i == 0 else "求问") for i in range(4)] + \
           [ext_row(9, 3000, 10, now=now, has_product=True)] + \
           [ext_row(20 + i, 5, 10, now=now) for i in range(4)]
    E = [f"ext:{rows[i]['note_id']}" for i in range(4)]
    PROD, SLOW = f"ext:{rows[4]['note_id']}", f"ext:{rows[5]['note_id']}"
    sb = _SB(rows)
    seen: dict = {}
    core.get_supabase = lambda *a, **k: sb
    core.latest_gate2_run = lambda s: P.load_delivery()["gate2_run"]   # 规律臂有下发, 才会去查命中
    P.verified_against_db = lambda s, d, **kw: True                     # 对库那一步 check_desk_delivery §3 管
    core.fetch_candidates = lambda s, **kw: [dict(CARD), dict(CARD, source_note_id="n2", rank_score=0.5)]
    core.get_cache = lambda s, key: None
    keys: list = []
    stored: list = []
    core.put_cache = lambda s, key, brief, lib_v, sel, **kw: keys.append(key) or stored.append(sel)
    asked: list = []
    P.fetch_answers = lambda s, ids, d: asked.append(list(ids)) or {}
    pick: list = [E[0], E[1], "n1", E[2]]

    def llm(prompt, model, *, system=None, **kw):
        seen["system"] = "\n".join(b["text"] for b in system)
        return _sel(pick)
    core.call_anthropic = llm

    brief = {"consumer": "deskcore", "project_id": "p", "brand": "雷诺考特"}
    res = core.librarian_select_full(dict(brief))
    assert "外部参考" not in seen["system"].split("你的任务")[1] and not any(s.get("external") for s in res["selected"]), \
        "不带 explore 的老消费方不给外部卡"
    assert not any(t == "table" and a == ("external_notes",) for t, a in sb.log), "老消费方连外部表都不查"
    assert [s["source_note_id"] for s in res["selected"]] == ["n1"] and not any(s.get("forced") for s in res["selected"]), \
        "老消费方没有书架, 也不补外部卡"

    for arm in (False, True):
        res = core.librarian_select_full(dict(brief, explore=arm))
        ext = [s for s in res["selected"] if s["external"]]
        assert [s["source_note_id"] for s in ext] == E[:2], f"explore={arm}: 外部卡截到 2 张"
        assert [s["source_note_id"] for s in res["selected"] if not s["external"]] == ["n1"]
        assert PROD not in seen["system"] and SLOW not in seen["system"] and f"[{E[3]}]" in seen["system"], \
            "带产品 / 评论不够的不上架; 达标的 (日均不低于中位数) 都给模型看"
        assert not any(s.get("forced") for s in res["selected"]), "模型自己挑了外部卡就不补"
        e0 = next(s for s in res["selected"] if s["source_note_id"] == E[0])
        assert len(e0["excerpt"]) == X.EXCERPT_CAP and e0["comments_per_day"] == 40.0 and e0["posted_days_ago"] == 11, \
            "选中卡的摘录截到 600 字; 外部卡带发出几天、日均评论"
        assert e0["fq"] == {} and e0["structure"] is None, "结构题查不到 (假库里没有) 就不带, 卡照给"
    assert len(set(keys[-2:])) == 2, "两臂缓存仍分开"
    dry = core.librarian_select(dict(brief, explore=False), dry_run=True)
    want = X.digest([X.to_card(r, CFG, rate=v, pct=p) for r, v, p in X.qualified(rows, CFG)][:CFG["show_per_request"]])
    assert dry["external"] == 4 and dry["library_version"].endswith(f":ext{want}"), "外部书架换一批, 缓存键要跟着换"
    assert asked and all(not str(i).startswith("ext:") for ids in asked for i in ids), "外部卡不查 note 的规律答案"
    assert any(t == "gte" and a[0] == "fetched_at" for t, a in sb.log), "只拉最近 45 天抓到的"
    assert any(t == "table" and a == ("note_feature_answers",) for t, a in sb.log) and \
        any(t == "eq" and a == ("subject_type", "external_note") for t, a in sb.log), "上架的卡去查 Jev 给外部帖答的结构题"

    pick[:] = E + [E[0], "n1", "n2"]
    res = core.librarian_select_full(dict(brief, project_id="p7", explore=True))
    assert [s["source_note_id"] for s in res["selected"]] == [E[0], E[1], "n1", "n2"], \
        "截掉的外部卡不占名额: 模型多挑了外部卡, 后面合格的内部卡不能被挤掉"

    # D-138 保底: 模型一张外部卡都没挑 → 补日均最高的那张, 标 forced, 进缓存
    pick[:] = ["n2", "n1"]
    res = core.librarian_select_full(dict(brief, project_id="p3", explore=False))
    assert [s["source_note_id"] for s in res["selected"]] == ["n2", "n1", E[0]] and res["status"] == "ok", res
    forced = res["selected"][-1]
    assert forced["forced"] is True and forced["external"] is True and forced["why_relevant"] == core.FORCED_WHY
    assert not any(s.get("forced") for s in res["selected"][:2]) and stored[-1][-1].get("forced") is True, \
        "补的那张在缓存的 selected[] 里也标着 forced"
    pick[:] = []
    res = core.librarian_select_full(dict(brief, project_id="p4", explore=False))
    assert res["selected"] == [] and res["status"] == "no_match", "模型一张都没挑 (没有合适的) 不补"
    pick[:] = [E[0], "n1"]

    calls = sum(1 for t, a in sb.log if t == "table" and a == ("external_notes",))
    X.shelf_for(sb, brief)
    assert sum(1 for t, a in sb.log if t == "table" and a == ("external_notes",)) == calls, "10 分钟内不再拉外部表"
    X._shelf.clear()
    sb.rows = RuntimeError("db down")
    pick[:] = ["n1"]
    res = core.librarian_select_full(dict(brief, project_id="p2", explore=False))
    assert [s["source_note_id"] for s in res["selected"]] == ["n1"] and res["status"] == "ok", "外部表挂了照样选内部卡, 也不补"
    assert X._shelf == {}, "查库失败不缓存, 下个请求重查"
    sb.rows = rows
    assert X.shelf_for(sb, brief, now=10 ** 9), "库恢复了就有"

    # 登记了、外部表里还没有这个品类的帖 (家居家电 / 个护 / 藻油 在 Jev 进货之前): 书架空, 内部卡照常, 不补
    X._shelf.clear()
    sb.rows = []
    res = core.librarian_select_full(dict(brief, brand="西屋", project_name="西屋911gt", project_id="p5", explore=False))
    assert [s["source_note_id"] for s in res["selected"]] == ["n1"] and res["status"] == "ok"
    assert "至少挑" not in seen["system"], "没有外部卡时不提外部卡的用法"
    assert X._shelf.get("家居家电", (None,))[0] == [], "空书架也缓存 (查库成功了, 只是没货)"
    sb.rows = rows

    old = [{"source_note_id": "n1", "why_relevant": "r"},
           {"source_note_id": E[1], "why_relevant": "r", "external": True, "posted_days_ago": 1}]
    core.get_cache = lambda s, key: [dict(c) for c in old]
    res = core.librarian_select_full(dict(brief, project_id="p8", explore=False))
    assert res["selected"][0]["external"] is False and res["selected"][0]["validated_hits"] == [], \
        "部署前的缓存行没有这两个键, 命中时补上 (文档承诺选中的卡都带)"
    assert res["selected"][1]["posted_days_ago"] == 11, "命中缓存时「发出几天」按 id 重算, 不是写缓存那天的数"
    core.get_cache = lambda s, key: None
    print("  §6 端到端: 老消费方不给; 两臂都给; 截到 2 张且不占名额; 一张没挑就补 (forced, 进缓存)、没挑任何卡不补; "
          "摘录 600 字; 带产品 / 评论不够不上架; 不查规律答案; 查库挂了 / 品类没货照样选; 书架进程内缓存; 旧缓存行补键 ✓")


def s6b_ensure_external() -> None:
    """_ensure_external 单测: 满 5 张时顶谁、不到 5 张时不顶、已经有外部卡时不动。"""
    now = time.time()
    shelf = [X.to_card(ext_row(i, 100 * (i + 1), 10, now=now), CFG) for i in range(3)]   # 日均 10 / 20 / 30
    top = shelf[2]["source_note_id"]
    internal = [dict(CARD, source_note_id=f"i{k}", rank_score=s) for k, s in enumerate([0.9, 0.2, 0.7, 0.2, 0.5])]
    full = [core._enrich(c, "r", "b") for c in internal]
    out = core._ensure_external(full, internal + shelf)
    assert [s["source_note_id"] for s in out] == ["i0", "i1", "i2", "i4", top], \
        "满 5 张: 顶掉 rank_score 最低的内部卡 (两张同分顶靠后的), 补日均最高的外部卡在末尾"
    assert out[-1]["forced"] is True and len(out) == core.DEFAULT_SELECT_MAX and full[3]["source_note_id"] == "i3", \
        "不改调用方的列表"
    three = full[:3]
    assert [s["source_note_id"] for s in core._ensure_external(three, internal + shelf)] == ["i0", "i1", "i2", top], \
        "不到 5 张: 加在末尾, 一张内部卡都不顶"
    with_ext = three[:2] + [core._enrich(shelf[0], "r", "b")]
    assert core._ensure_external(with_ext, internal + shelf) == with_ext, "已经有外部卡就不动"
    assert core._ensure_external(three, internal) == three, "书架空不动"
    assert core._ensure_external([], internal + shelf) == [], "模型一张没挑不补"
    print("  §6b 外部卡保底: 满 5 张顶 rank 最低的内部卡、不到 5 张只加不顶、有外部卡 / 书架空 / 没挑任何卡都不动 ✓")


def s7_wiring() -> None:
    src = (ROOT / "scripts" / "check_external_direction.py").read_text(encoding="utf-8")
    assert "X.qualified(" in src, "方向复核报的书架达标数要用同一个 qualified, 不许另抄一份口径"
    wf = (ROOT / ".github" / "workflows" / "daily-sync.yml").read_text(encoding="utf-8")
    assert "python check_external_direction.py" in wf, "每周方向复核没接进夜跑"
    print("  §7 接线: 方向复核报书架达标数 (同一个 qualified)、接进夜跑 ✓")


def main() -> int:
    s1_config()
    s2_match()
    s3_qualifies()
    s4_order_and_card()
    s5_version()
    s6_end_to_end()
    s6b_ensure_external()
    s7_wiring()
    print("\ncheck_external_shelf: 8 节全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
