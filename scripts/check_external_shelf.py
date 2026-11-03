#!/usr/bin/env python3
"""
check_external_shelf.py —— 外部参考书架 (D-117 ②, D-138; prompts/external_shelf_v1.json + librarian/external.py) 的离线守卫。

  §1 配置: D-138 的值 (评论 ≥20、发出 ≤90 天、每次至少 1 张最多 2 张、每品类给模型看 6 张)、一个品牌不许挂两个品类、
     品牌 → 品类整张表钉死 (写作台 aw deskcore/priors.py 的 EXT_CATEGORY_BY_PROJECT 照抄这张, 那边也钉着同一张);
     「至少 1 张」8 个品类都管 (D-140: 遮挡按篇做, 不靠公开名单), 但只塞摘录遮过的卡
  §2 同品类: 只看 brief 的品牌 / 项目名 (项目定位里顺嘴提到「戒烟」不算), 大小写不敏感; 西屋 / Hatherine / 百健士三个新品类
  §3 达标: 发帖时间从 note_id 解; 抓到时发出 3–90 天、最近 45 天抓到; 评论够; 日均评论 (分母至少 3 天) 不低于同品类中位数;
     不像广告 + 没点到我们登记的品牌; D-140 起带产品的也收 (has_product 不再挡); Jev 功效题答「是」的不收、没答的也不收
  §4 排序和卡面: 品类内按日均评论从高到低、中位数算全体 (带产品 / 评论少的也算); rank_score 是百分位; 卡上有抓到时
     发出几天 / 共几条 / 那时每天几条 (乘得回去), 现在发出几天另起半句; why_it_worked 只写抓取那一刻的数 (不带现在的天数、
     不带百分位, 缓存放多久都不过时); 结构题; id 带 ext: 前缀、没有品牌; 遮挡 (D-140): 模型列的词只留原文里逐字出现的,
     换成「某品牌」/「某产品」、长的先换、拉丁不分大小写、短拉丁词按词边界, 再换配置 mask_terms; 没有遮挡行 → 摘录空、只给结构; 有外部卡时
     prompt 才多那句用法 (能补的品类至少 1 张、最多 2 张, 没遮挡的品类只说最多 2 张; 不再「优先挑帆谷自己的卡」);
     「已验证爆款」只说帆谷自己的卡; 命中规律的优先只在内部卡之间比
  §5 缓存版本: 外部卡 (连卡面、结构、遮没遮过) 进版本串; 遮挡词变了版本跟着变; 现在发出几天不进; 没有外部卡时与以前一样
  §6 端到端 (打桩): 老消费方不给; 两臂都给; 模型挑多了截到 2 张 (不算契约失败), 截掉的不占 5 张的名额;
     一张没挑就补日均最高的那张 (forced, 进缓存); 满 5 张才顶 rank 最低的内部卡; 摘录截到 600 字;
     查库挂了 / 品类还没有外部帖照样选内部卡; 外部卡不去查 note 的规律答案; 部署前的缓存行补上 external / validated_hits;
     命中缓存时现在发出几天按 id 重算, why_it_worked 一周后命中也和它不打架; 书架按品类在进程里缓存 10 分钟
     (查库失败不缓存), 只拉最近 45 天抓到的; 功效题答「是」/ 没答的不上架; 遮挡行过期 (原文变了) 的只给结构;
     没遮挡行又没结构的不上架、往下补; 遮挡表还没建 → 全部只给结构、不强塞 (m0)、只 warning 一次、借卡照常;
     答案查不了 → 这个品类没有外部卡、内部卡照常; 答案按 100 篇一批、翻到空页 (不静默截断)
  §6b 保底: 满 5 张顶谁、不到 5 张不顶、有外部卡不动; 只补摘录遮过的卡, 只给结构的卡再快也不补
  §7 接线: 方向复核那盏灯报书架达标数, 用的是同一个 qualified; 遮挡词夜跑、内容层补填接进夜跑

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
    # D-140: 遮挡按篇做 (模型列词 + 代码逐字核对), 不靠这份公开名单 —— 8 个品类都管「至少 1 张」, 强塞只塞遮过的卡 (§6 / §6b)
    assert CFG["min_external_categories"] == list(BRAND_TABLE), CFG["min_external_categories"]
    seen: dict = {}
    for cat, brands in CFG["categories"].items():
        assert brands, f"{cat}: 没登记品牌"
        for b in brands:
            assert b.lower() not in seen, f"{b} 同时挂在 {seen[b.lower()]} 和 {cat}"
            seen[b.lower()] = cat
    bad = pathlib.Path(__file__).with_name("_bad_shelf.json")
    logging.disable(logging.WARNING)          # 下面两份坏配置各打一条带堆栈的 warning, 是要的, 不刷屏
    try:
        for patch in ({"min_external": 3}, {"max_age_days": 2}, {"min_external_categories": ["没登记的品类"]},
                      {"min_external_categories": "戒烟"}):
            bad.write_text(json.dumps({**CFG, **patch}), encoding="utf-8")
            assert X.load_config(bad) is None and X.shelf_for(None, {"brand": "途鸽"}, path=bad) == [], \
                f"配置不合理 ({patch}) 就整份不用, 不给外部卡"
            X._cache.pop(str(bad), None)
        # 没写 min_external_categories = 哪个品类都不强塞 (新配置默认安全)
        bad.write_text(json.dumps({k: v for k, v in CFG.items() if k != "min_external_categories"}), encoding="utf-8")
        card = {"external": True, "category": "鼻炎", "masked": True, "raw_excerpt": "遮过的摘录"}
        assert X.load_config(bad) and X.min_external(bad) == 1 and X.forceable([card], bad) == [] \
            and X.min_external_for([card], bad) == 0, "没写 min_external_categories: 配置照用, 但哪个品类都不强塞"
        X._cache.pop(str(bad), None)
    finally:
        logging.disable(logging.NOTSET)
        bad.unlink(missing_ok=True)
    print(f"  §1 配置: {len(CFG['categories'])} 个品类、评论 ≥{CFG['min_comments']}、发出 ≤{CFG['max_age_days']} 天、"
          f"每次 {CFG['min_external']}–{CFG['max_per_borrow']} 张 (至少那张 {len(CFG['min_external_categories'])} 个品类都管、只塞遮过的卡)、"
          f"给模型看 {CFG['show_per_request']} 张、品牌表钉死 ✓")


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
    assert ok(dict(r, has_product=True)) and ok(dict(r, has_product=None)), \
        "D-140: has_product 不再挡 (分诊只看标题 + 摘要, 代替不了「没有别家品牌名」); 品牌名靠遮挡表遮"
    assert not ok(dict(r, ad_like=True))
    assert ok(dict(r, body=f"后来换了{CFG['mask_terms'][0]}")), "D-120: 点了别家品牌的照收, 上架时换成「某品牌」"
    # D-140 / F-08: 功效题 (Jev 全文答的 efficacy_promise) 只有答了「否」才上架; 答「是」、没答、答空都不上 (fail-closed)
    assert X.efficacy_ok({"efficacy_promise": "否"}) and not X.efficacy_ok({"efficacy_promise": "是"})
    assert not X.efficacy_ok({}) and not X.efficacy_ok(None) and not X.efficacy_ok({"efficacy_promise": ""}) \
        and not X.efficacy_ok({"opening_type": "提问"}), "没有功效答案的不上架"
    rs = [ext_row(1, 60, 10, now=now), ext_row(2, 60, 10, now=now), ext_row(3, 60, 10, now=now, has_product=True)]
    ans = {rs[0]["note_id"]: {"efficacy_promise": "否"}, rs[1]["note_id"]: {"efficacy_promise": "是"},
           rs[2]["note_id"]: {"efficacy_promise": "否"}}
    assert [t[0]["note_id"] for t in X.qualified(rs, CFG, ans, now=now)] == sorted([rs[0]["note_id"], rs[2]["note_id"]]), \
        "答了「是」的不收; 带产品、答了「否」的收"
    assert X.qualified(rs, CFG, {}, now=now) == [], "一个答案都没有 = 一篇都不收"
    assert not ok(dict(r, title="雷诺考特用了一周")), "点了登记品牌 (可能就是我们自己铺的) 不上架"
    assert not ok(dict(r, body="试过 SPORTSIX 的胶")), "登记品牌大小写不敏感"
    assert not ok(dict(r, body="西屋的按摩椅坐了一周")), "新登记的品牌一样挡"
    print("  §3 达标: note_id 解发帖时间 / 3–90 天 / 最近 45 天抓到 / 评论 ≥20 / 日均不低于中位数 / 带产品也收 / 不像广告 / "
          "没点我们登记的品牌 / 功效题答「否」才收、没答不收 ✓")


CARD = {"source_note_id": "n1", "tier": "爆", "brand": "雷诺考特", "category": "OTC药", "rank_score": 1.0,
        "curated_at": "2026-10-01", "is_curated": True, "hook_type": "h", "structure": "s",
        "why_it_worked": "w", "transferable_tactic": "t", "raw_excerpt": "e", "synthetic": False}


def s4_order_and_card() -> None:
    now = time.time()
    rows = [ext_row(0, 30, 3, now=now),                                   # 日均 10
            ext_row(1, 200, 40, now=now),                                 # 日均 5: 低于中位数 8, 不上架
            ext_row(8, 400, 50, now=now),                                 # 日均 8: 总评论最多, 达标但排在日均 10 的后面
            ext_row(2, 60, 6, now=now),                                   # 日均 10  (同速按 note_id)
            ext_row(3, 900, 10, now=now, has_product=True),               # 日均 90: 带产品的也上架 (D-140), 排第一
            ext_row(4, 5, 5, now=now), ext_row(5, 4, 4, now=now),         # 日均 1 / 1: 评论不够, 也算进中位数
            ext_row(6, 3000, 400, now=now),                               # 发出太久: 不进中位数、不上架
            ext_row(7, 40, 20, now=now, category="戒烟")]                  # 另一个品类自己算中位数
    got = X.candidates(rows, CFG, now=now)
    ids = [r["note_id"] for r, _, _ in got]
    by = {r["note_id"]: (v, p) for r, v, p in got}
    nid = lambda tag: next(r["note_id"] for r in rows if r["note_id"].endswith(f"{tag:016x}"))  # noqa: E731
    want = [nid(3)] + sorted([nid(0), nid(2)]) + [nid(8), nid(7)]
    assert ids == want, ("品类内按日均评论从高到低 (同速按 note_id), 不按总评论数; 中位数算全体 (评论少的也算: "
                         f"1,1,5,8,10,10,90 → 8): {ids}")
    ans = {i: {"efficacy_promise": "否"} for i in ids}
    ans[nid(2)] = {"efficacy_promise": "是"}
    del ans[nid(8)]
    assert [r["note_id"] for r, _, _ in X.qualified(rows, CFG, ans, now=now)] == [nid(3), nid(0), nid(7)], \
        "上架 = 便宜那几道 + 功效题答「否」 (答「是」的、没答的去掉), 顺序不变"
    assert nid(1) not in by, "日均 5 低于中位数, 不上架"
    assert abs(by[nid(0)][1] - 5 / 7) < 1e-9, "百分位 = 中位秩 / 同品类篇数 (10 排在 7 篇的第 5、6 位 → 5/7)"
    assert by[nid(7)][1] == 0.5, "只有一篇的品类: 它就是中位数, 达标, 百分位 0.5"

    fq = {"opening_type": "具体事件", "turning_point": "是", "ending_asks_reader": "是", "asks_for_help": "否",
          "own_experience": "是", "title_is_question": "否", "efficacy_promise": "是"}
    c = X.to_card(rows[0], CFG, rate=by[nid(0)][0], pct=by[nid(0)][1], fq=fq, now=now, mask=[])
    assert c["source_note_id"] == f"ext:{nid(0)}" and c["external"] is True and c["brand"] is None
    assert c["masked"] is True and c["raw_excerpt"] == f"{rows[0]['title']} {rows[0]['body']}", "遮挡行查过了、没有要遮的: 原文照给"
    bare = X.to_card(rows[0], CFG, rate=by[nid(0)][0], pct=by[nid(0)][1], fq=fq, now=now)
    assert bare["masked"] is False and bare["raw_excerpt"] == "" and bare["structure"] == X.describe(fq), \
        "D-140: 没有有效遮挡行 → 只给结构, 不给原文摘录"
    assert c["posted_days_ago"] == 4 and c["age_at_scrape_days"] == 3 and c["comments_per_day"] == 10.0 \
        and c["rank_score"] == round(5 / 7, 3), "现在发出 4 天; 抓到时发出 3 天、共 30 条 → 那时每天 10 条"
    assert "efficacy_promise" not in c["fq"] and c["fq"]["opening_type"] == "具体事件", "卡上只带结构题"
    assert c["structure"] == "开头先讲一件具体的事；中间有一次前后转折；讲的是自己的经历；结尾问了读者", c["structure"]
    # why_it_worked 只写抓取那一刻的数: 写作台模型读它, 缓存行一放一周, 现在的天数 / 上架时的百分位都会过时
    assert "抓到时发出约 3 天、共 30 条评论, 那时每天约 10.0 条" in c["why_it_worked"], c["why_it_worked"]
    assert "发出约 4 天" not in c["why_it_worked"] and "快过同品类" not in c["why_it_worked"], \
        "why_it_worked 不写现在发出几天、不写百分位 (命中缓存时它们会和 posted_days_ago / rank_score 对不上)"
    later = X.to_card(rows[0], CFG, rate=by[nid(0)][0], pct=by[nid(0)][1], fq=fq, now=now + 7 * DAY)
    assert later["posted_days_ago"] == 11 and later["why_it_worked"] == c["why_it_worked"], \
        "一周后同一张卡: posted_days_ago 变了, why_it_worked 一字不变"
    assert X.describe({"opening_type": "其他"}) is None and X.describe(None) is None

    txt = core.build_system_blocks({}, [CARD, c])[0]["text"]
    assert f"[ext:{nid(0)}] 外部参考|鼻炎｜别家同品类最近涨得快的帖, 只借结构不抄内容" in txt
    assert "抓到时发出约 3 天、共 30 条评论、那时每天约 10.0 条；现在发出约 4 天" in txt and "结构: 开头先讲一件具体的事" in txt
    assert "至少挑 1 张、最多 2 张" in txt and txt.index("至少挑 1 张") < txt.index("候选经验卡")
    assert "优先挑帆谷自己的卡" not in txt, "D-138: 不再让模型同样合适时先挑内部卡"
    assert "至少挑" not in core.build_system_blocks({}, [CARD])[0]["text"], "没有外部卡时 prompt 不变"
    txt = core.build_system_blocks({}, [CARD, bare])[0]["text"]
    assert "摘要: (这张只给结构, 不给原文)" in txt and "最多挑 2 张" in txt and "至少挑" not in txt, \
        "只给结构的卡: 卡上说明不给原文; 一摞里没有遮过的外部卡 → 不说「至少」(不强塞)"
    # 抓到时发出 3 天、60 条评论, 44 天前抓的: 现在发出 47 天。日均 20 条只能和「抓到时 3 天」挨着 (3 × 20 = 60),
    # 不能写成「发出约 47 天 · 每天约 20 条 · 共 60 条」(47 × 20 ≠ 60, 模型会以为它一直这么涨)
    old = X.to_card(ext_row(30, 60, 3, now=now, fetched_days_ago=44), CFG, now=now, mask=[])
    assert (old["posted_days_ago"], old["age_at_scrape_days"], old["comments_per_day"]) == (47, 3, 20.0), old
    assert old["age_at_scrape_days"] * old["comments_per_day"] == old["comments"], "卡上挨着的三个数乘得回去"
    txt = core.build_system_blocks({}, [CARD, old])[0]["text"]
    assert "抓到时发出约 3 天、共 60 条评论、那时每天约 20.0 条；现在发出约 47 天" in txt, txt
    assert "发出约 47 天 · 每天约" not in txt and "47 天、共" not in txt, "现在的天数不和日均评论挨着写"
    assert "抓到时发出约 3 天、共 60 条评论, 那时每天约 20.0 条" in old["why_it_worked"] and "47" not in old["why_it_worked"]
    # D-140: 能强塞的只有摘录遮过的卡 (8 个品类都算); 只给结构的卡不算 —— 只有它们时 prompt 只说最多几张
    home = dict(c, source_note_id="ext:home", category="家居家电")
    assert X.forceable([CARD, home]) == [home], "家居家电 (D-138 新登记) 遮过了就能补 (F-10 关)"
    assert X.forceable([CARD, bare]) == [] and X.forceable([CARD, c, bare]) == [c], "只给结构的卡不强塞"
    assert X.forceable([dict(c, raw_excerpt="")]) == [], "摘录是空的不算遮过"
    txt = core.build_system_blocks({}, [CARD, bare])[0]["text"]
    assert "最多挑 2 张" in txt and "至少挑" not in txt, "只有结构卡: 用法只说最多 2 张"
    assert "至少挑 1 张、最多 2 张" in core.build_system_blocks({}, [CARD, c, bare])[0]["text"], "有遮过的卡就照旧至少 1 张"
    head = core.ROLE_TASK_INSTR.split("你的任务")[0]
    assert "帆谷自己的卡是\n【已验证爆款/值得参考】" in head and "外部参考" in head, "「已验证爆款」只说帆谷自己的卡"
    rules = P.render_block({"patterns": [{"label": "L", "instruction": "i", "evidence": "e"}]})
    assert "帆谷自己的卡里, 下面标了「命中已验证规律」的, 同样合适时优先借" in rules and "不因此少挑外部卡" in rules
    # D-120: 配置里的别家品牌名换成「某品牌」, 不分大小写, 长的先换 (遮挡行查过、没有要遮的词也照换)
    # 别家品牌名从配置里取, 不在这里另写一份 (本仓公开)
    a, b = [t for t in CFG["mask_terms"] if not t.isascii()][:2]
    latin = next(t for t in CFG["mask_terms"] if t.isascii())
    m = X.to_card(dict(rows[0], title=f"{a}和{b}我都试过", body=f"后来朋友推荐 {latin.upper()} 的胶"), CFG, mask=[])["raw_excerpt"]
    assert all(t.lower() not in m.lower() for t in (a, b, latin)), m
    assert m.count(X.MASK) == 3, m
    assert X.mask_brands("某甲某甲乙", {"mask_terms": ["某甲", "某甲某甲乙"]}) == X.MASK, "长的先换, 不留半截"
    assert X.mask_brands("没有品牌", None) == "没有品牌" and X.mask_brands("", CFG) == ""
    # D-140: 模型列的词 (遮挡表) —— 只留原文里逐字出现的; 品牌 → 某品牌、产品 → 某产品; 别的字一个不动
    title, body = "换季鼻子又罢工了", "用了 BrandX 的 Pro 系列, 后来 brandx 客服说 Pro 系列要连用。某甲店也有卖。haha"
    text = f"{title}\n{body}"
    terms = X.clean_terms([{"t": "BrandX", "k": "品牌"}, {"t": "Pro 系列", "k": "产品"}, {"t": "某甲店", "k": "店铺"},
                           {"t": "Pro系列", "k": "产品"}, {"t": "编出来的牌子", "k": "品牌"}, {"t": "鼻", "k": "品牌"},
                           {"t": "brandx", "k": "品牌"}, {"t": "HA", "k": "品牌"}, "BrandX", 42, None], text)
    assert [t["t"] for t in terms] == ["BrandX", "Pro 系列", "某甲店"], \
        f"只留原文里逐字出现的 (改写过的 / 编的 / 一个字的 / 半截拉丁词都丢), 大小写不敏感去重: {terms}"
    assert terms[2]["k"] == "品牌", "k 认不得的当品牌"
    mc = X.to_card(dict(rows[0], title=title, body=body), CFG, mask=terms)
    assert mc["raw_excerpt"] == "换季鼻子又罢工了 用了 某品牌 的 某产品, 后来 某品牌 客服说 某产品要连用。某品牌也有卖。haha", mc["raw_excerpt"]
    assert all(t["t"].lower() not in mc["raw_excerpt"].lower() for t in terms), "列出来的词一个都不剩"
    assert X.apply_mask("BrandXPro 新款", [{"t": "BrandX", "k": "品牌"}], None) == "某品牌Pro 新款", \
        "长拉丁词贴着别的字母也换 (漏遮比多遮坏)"
    assert X.apply_mask("某牌A和某牌A加强", [{"t": "某牌A", "k": "品牌"}, {"t": "某牌A加强", "k": "产品"}], None) \
        == "某品牌和某产品", "长的先换, 换上去的字不会再被匹配"
    print("  §4 排序和卡面: 按日均评论排、中位数算全体、百分位当 rank_score; 卡上抓到时天数 / 共几条 / 那时日均挨着写、"
          "现在发出几天另起; why_it_worked 只写抓取时的数; 结构; 能补的品类至少 1 张最多 2 张、没遮挡的品类只说最多; "
          "不再优先内部卡; 「已验证爆款」只说内部卡; 遮挡词逐字核对后换成「某品牌」/「某产品」、配置名单照换; "
          "没遮挡行只给结构、不强塞 ✓")


def s5_version() -> None:
    now = time.time()
    cards = [CARD]
    base = core.library_version(cards, gate2_run="g")
    assert core.library_version(cards, gate2_run="g", external=None) == base
    a, b = X.to_card(ext_row(1, 60, 10, now=now), mask=[]), X.to_card(ext_row(2, 60, 10, now=now), mask=[])
    assert X.digest([a, b]) == X.digest([b, a])
    v1 = core.library_version(cards, gate2_run="g", external=X.digest([a]))
    v2 = core.library_version(cards, gate2_run="g", external=X.digest([a, b]))
    assert len({base, v1, v2}) == 3
    # mask_terms 补了一个品牌: id 没变, 卡面变了 → 版本必须变, 否则旧缓存里没换掉品牌名的摘录一直被命中
    r = ext_row(1, 60, 10, now=now, body="后来用了新牌子")
    masked = X.to_card(r, {**CFG, "mask_terms": CFG["mask_terms"] + ["新牌子"]}, mask=[])
    plain = X.to_card(r, CFG, mask=[])
    assert masked["source_note_id"] == plain["source_note_id"] and X.digest([masked]) != X.digest([plain])
    assert X.digest([X.to_card(r, CFG, fq={"turning_point": "是"}, mask=[])]) != X.digest([plain]), "结构题晚到, 版本也要变"
    assert X.digest([X.to_card(r, CFG, now=now + 3 * DAY, mask=[])]) == X.digest([plain]), "现在发出几天每天都变, 不进版本"
    # D-140: 夜跑新列了这一篇的遮挡词 (没有 → 有 / 词变了), 卡面变了, 版本必须变; 只给结构的卡和遮过的卡不同版本
    by_model = X.to_card(r, CFG, mask=[{"t": "新牌子", "k": "品牌"}])
    struct = X.to_card(r, CFG, fq={"turning_point": "是"})
    assert X.digest([by_model]) != X.digest([plain]), "遮挡词变了 → 版本变"
    assert X.digest([by_model]) == X.digest([masked]), "同一张卡面 (模型列的词和配置名单换出来一样) → 同一个版本"
    assert X.digest([struct]) != X.digest([X.to_card(r, CFG, fq={"turning_point": "是"}, mask=[])]), \
        "只给结构 → 遮过、给摘录: 版本变"
    real = X.MASK_RULES
    try:
        X.MASK_RULES = real + "x"
        bumped = X.digest([plain])
    finally:
        X.MASK_RULES = real
    assert bumped != X.digest([plain]), "遮挡规则升版 (MASK_RULES), 旧缓存全部作废"
    print("  §5 缓存版本: 外部卡(连卡面、结构、遮没遮过、遮挡规则版本)进版本串、现在发出几天不进、没有时不变 ✓")


class _Q:
    """一张表的假查询: 认 select / eq / gte / in_ / order / range / limit; 每一步记进 log。表是异常 → execute 抛。"""

    def __init__(self, db, table):
        self.db, self.t, self.f, self.rng, self.lim = db, table, [], None, None

    def _log(self, name, a):
        self.db.log.append((name, a))
        return self

    def select(self, *a, **k):
        return self._log("select", a)

    def eq(self, c, v):
        self.f.append(lambda r: r.get(c) == v)
        return self._log("eq", (c, v))

    def gte(self, c, v):
        self.f.append(lambda r: str(r.get(c) or "") >= str(v))
        return self._log("gte", (c, v))

    def in_(self, c, vs):
        vs = {str(x) for x in vs}
        self.f.append(lambda r: str(r.get(c)) in vs)
        return self._log("in_", (c, sorted(vs)))

    def order(self, *a, **k):
        return self._log("order", a)

    def range(self, a, b):
        self.rng = (a, b)
        return self._log("range", (a, b))

    def limit(self, n):
        self.lim = n
        return self._log("limit", (n,))

    def execute(self):
        tab = self.db.tables.get(self.t, [])
        if isinstance(tab, Exception):
            raise tab
        rows = [r for r in tab if all(f(r) for f in self.f)]
        if self.rng:
            rows = rows[self.rng[0]:self.rng[1] + 1]
        if self.lim is not None:
            rows = rows[:self.lim]
        return type("R", (), {"data": [dict(r) for r in rows]})()


class _SB:
    def __init__(self, tables):
        self.tables, self.log = tables, []

    def schema(self, s):
        return self

    def table(self, t):
        self.log.append(("table", (t,)))
        return _Q(self, t)


def _ans(nid, q, a, at="2026-11-01T00:00:00+00:00"):
    return {"subject_type": "external_note", "run_tag": "external", "subject_id": nid, "question_id": q, "answer": a,
            "extracted_at": at}


def _mask(row, terms, *, stale=False):
    return {"note_id": row["note_id"], "terms": terms,
            "text_sha": "0" * 64 if stale else X.mask_text_sha(row.get("title"), row.get("body"))}


def _sel(ids):
    return json.dumps({"selected": [{"source_note_id": i, "why_relevant": "r", "borrow_what": "b"} for i in ids]})


def s6_end_to_end() -> None:
    now = time.time()
    long_body = "长" * 1500
    # e0..e3 日均 40 / 30 / 20 / 10; 带产品那篇日均 300 (D-140 起带产品也收, 但它的功效题答了「是」→ 不上架);
    # 四篇评论不够的慢帖把中位数拉到 e3 (9 篇的第 5 篇)
    rows = [ext_row(i, (4 - i) * 100, 10, now=now, body=long_body if i == 0 else "求问") for i in range(4)] + \
           [ext_row(9, 3000, 10, now=now, has_product=True)] + \
           [ext_row(20 + i, 5, 10, now=now) for i in range(4)]
    rows[1]["body"] = "求问 BrandX 的 Pro 系列好用吗"
    E = [f"ext:{rows[i]['note_id']}" for i in range(4)]
    PROD, SLOW = f"ext:{rows[4]['note_id']}", f"ext:{rows[5]['note_id']}"
    answers = ([_ans(rows[i]["note_id"], "efficacy_promise", "否") for i in range(4)]
               + [_ans(rows[0]["note_id"], "opening_type", "具体事件"),
                  _ans(rows[2]["note_id"], "turning_point", "是"),
                  _ans(rows[4]["note_id"], "efficacy_promise", "否", at="2026-10-01T00:00:00+00:00"),
                  _ans(rows[4]["note_id"], "efficacy_promise", "是")])            # 同一题答过两次: 取最后抽的 (是)
    # e0 查过、没有要遮的; e1 有两个词; e2 的遮挡行过期 (原文变过) → 只给结构; e3 没有遮挡行、也没有结构 → 不上架
    masks = [_mask(rows[0], []), _mask(rows[1], [{"t": "BrandX", "k": "品牌"}, {"t": "Pro 系列", "k": "产品"}]),
             _mask(rows[2], [], stale=True)]
    sb = _SB({"external_notes": rows, "note_feature_answers": answers, X.MASK_TABLE: masks})
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
        assert PROD not in seen["system"] and SLOW not in seen["system"], \
            "功效题答了「是」(最后抽的那次) / 评论不够的不上架"
        assert f"[{E[3]}]" not in seen["system"], "没有遮挡行、也没有结构的卡不上架"
        e2_block = seen["system"].split(f"[{E[2]}]")[1].split("\n\n")[0]
        assert "结构: 中间有一次前后转折" in e2_block and "摘要: (这张只给结构, 不给原文)" in e2_block, \
            "遮挡行过期 (原文变过) → 只给结构"
        assert "BrandX" not in seen["system"] and "Pro 系列" not in seen["system"] \
            and "求问 某品牌 的 某产品好用吗" in seen["system"], "列出来的品牌 / 产品名在给模型的卡上已经换掉"
        assert not any(s.get("forced") for s in res["selected"]), "模型自己挑了外部卡就不补"
        e0 = next(s for s in res["selected"] if s["source_note_id"] == E[0])
        assert len(e0["excerpt"]) == X.EXCERPT_CAP and e0["comments_per_day"] == 40.0 and e0["posted_days_ago"] == 11 \
            and e0["age_at_scrape_days"] == 10, "选中卡的摘录截到 600 字; 外部卡带现在发出几天、抓到时发出几天、那时日均评论"
        assert e0["fq"] == {"opening_type": "具体事件"} and e0["structure"] == "开头先讲一件具体的事", \
            "结构题和功效题一次查; 卡上只带结构题"
        e1 = next(s for s in res["selected"] if s["source_note_id"] == E[1])
        assert "某品牌" in e1["excerpt"] and "BrandX" not in e1["excerpt"], "回给写作台的摘录也是遮过的"
    assert len(set(keys[-2:])) == 2, "两臂缓存仍分开"
    dry = core.librarian_select(dict(brief, explore=False), dry_run=True)
    want = X.digest(X.fetch_shelf(sb, ["鼻炎"], CFG))
    assert dry["external"] == 3 and dry["library_version"].endswith(f":ext{want}m1"), \
        "外部书架换一批 / 遮挡词变了, 缓存键要跟着换; 这摞要求至少挑几张 (m1) 也在里面"
    assert asked and all(not str(i).startswith("ext:") for ids in asked for i in ids), "外部卡不查 note 的规律答案"
    assert any(t == "gte" and a[0] == "fetched_at" for t, a in sb.log), "只拉最近 45 天抓到的"
    assert any(t == "table" and a == ("note_feature_answers",) for t, a in sb.log) and \
        any(t == "eq" and a == ("subject_type", "external_note") for t, a in sb.log), "上架的卡去查 Jev 给外部帖答的题"
    asked_ids = [a[1] for t, a in sb.log if t == "in_" and a[0] == "subject_id"]
    assert asked_ids and all(rows[5]["note_id"] not in ids for ids in asked_ids), "答案只给过了便宜那几道的帖查"
    mask_ids = [a[1] for t, a in sb.log if t == "in_" and a[0] == "note_id"]
    assert mask_ids and all(rows[4]["note_id"] not in ids for ids in mask_ids), "遮挡表只给功效题过了的帖查"

    pick[:] = E + [E[0], "n1", "n2"]
    res = core.librarian_select_full(dict(brief, project_id="p7", explore=True))
    assert [s["source_note_id"] for s in res["selected"]] == [E[0], E[1], "n1", "n2"], \
        "截掉的外部卡不占名额: 模型多挑了外部卡, 后面合格的内部卡不能被挤掉"

    # D-138 保底: 模型一张外部卡都没挑 → 补日均最高的那张 (D-140: 只补摘录遮过的), 标 forced, 进缓存
    pick[:] = ["n2", "n1"]
    res = core.librarian_select_full(dict(brief, project_id="p3", explore=False))
    assert [s["source_note_id"] for s in res["selected"]] == ["n2", "n1", E[0]] and res["status"] == "ok", res
    forced = res["selected"][-1]
    assert forced["forced"] is True and forced["external"] is True and forced["why_relevant"] == core.FORCED_WHY
    assert not any(s.get("forced") for s in res["selected"][:2]) and stored[-1][-1].get("forced") is True, \
        "补的那张在缓存的 selected[] 里也标着 forced"
    # 这份缓存一周后被命中: posted_days_ago 按 id 重算成 18, why_it_worked 里不能还写着「发出约 11 天」
    row = json.loads(json.dumps(stored[-1]))
    core.get_cache = lambda s, key: json.loads(json.dumps(row))
    real_time, week = core.time, now + 7 * DAY
    core.time = type("T", (), {"time": staticmethod(lambda: week), "monotonic": staticmethod(time.monotonic)})
    try:
        hit = core.librarian_select_full(dict(brief, project_id="p3", explore=False))["selected"][-1]
    finally:
        core.time = real_time
        core.get_cache = lambda s, key: None
    assert hit["source_note_id"] == E[0] and hit["posted_days_ago"] == 18 and hit["age_at_scrape_days"] == 10, hit
    assert hit["why_it_worked"] == row[-1]["why_it_worked"] and "抓到时发出约 10 天" in hit["why_it_worked"] \
        and "11 天" not in hit["why_it_worked"] and "18 天" not in hit["why_it_worked"], \
        "命中缓存: why_it_worked 只有抓取那一刻的数, 不会和重算过的 posted_days_ago 打架"
    pick[:] = []
    res = core.librarian_select_full(dict(brief, project_id="p4", explore=False))
    assert res["selected"] == [] and res["status"] == "no_match", "模型一张都没挑 (没有合适的) 不补"
    pick[:] = [E[0], "n1"]

    calls = sum(1 for t, a in sb.log if t == "table" and a == ("external_notes",))
    X.shelf_for(sb, brief)
    assert sum(1 for t, a in sb.log if t == "table" and a == ("external_notes",)) == calls, "10 分钟内不再拉外部表"
    X._shelf.clear()
    sb.tables["external_notes"] = RuntimeError("db down")
    pick[:] = ["n1"]
    res = core.librarian_select_full(dict(brief, project_id="p2", explore=False))
    assert [s["source_note_id"] for s in res["selected"]] == ["n1"] and res["status"] == "ok", "外部表挂了照样选内部卡, 也不补"
    assert X._shelf == {}, "查库失败不缓存, 下个请求重查"
    sb.tables["external_notes"] = rows
    assert X.shelf_for(sb, brief, now=10 ** 9), "库恢复了就有"

    # 答案查不了 (功效题判不了) → 这个品类这次没有外部卡 (fail-closed), 内部卡照常, 不缓存
    X._shelf.clear()
    sb.tables["note_feature_answers"] = RuntimeError("answers down")
    res = core.librarian_select_full(dict(brief, project_id="p11", explore=False))
    assert [s["source_note_id"] for s in res["selected"]] == ["n1"] and "外部参考|" not in seen["system"], \
        "答案查不了: 不拿没判过功效的帖上架"
    assert X._shelf == {}
    sb.tables["note_feature_answers"] = answers

    # 遮挡表还没建 (owner 没跑 v1_24): 全部只给结构、不强塞 (m0)、只 warning 一次、借卡照常
    X._shelf.clear()
    X._MASK_WARNED.clear()
    sb.tables[X.MASK_TABLE] = RuntimeError(
        "{'code': 'PGRST205', 'message': \"Could not find the table 'truth_vault.external_note_masks' in the schema cache\"}")
    pick[:] = ["n2", "n1"]
    caught: list = []
    handler = logging.Handler()
    handler.emit = lambda rec: caught.append(rec.getMessage())
    X.logger.addHandler(handler)
    try:
        res = core.librarian_select_full(dict(brief, project_id="p12", explore=False))
        X._shelf.clear()
        core.librarian_select_full(dict(brief, project_id="p13", explore=False))
    finally:
        X.logger.removeHandler(handler)
    assert [s["source_note_id"] for s in res["selected"]] == ["n2", "n1"], "没遮过的卡不强塞"
    assert "BrandX" not in seen["system"] and "摘要: (这张只给结构, 不给原文)" in seen["system"] \
        and f"[{E[0]}]" in seen["system"] and f"[{E[1]}]" not in seen["system"], \
        "遮挡表没建: 有结构的卡只给结构 (e0 / e2), 没结构的 (e1 / e3) 不上架"
    assert "最多挑 2 张" in seen["system"] and "至少挑" not in seen["system"]
    assert core.librarian_select(dict(brief, project_id="p12", explore=False), dry_run=True)["library_version"].endswith("m0")
    assert sum("还没建" in m for m in caught) == 1, f"遮挡表没建只 warning 一次: {caught}"
    sb.tables[X.MASK_TABLE] = masks
    X._shelf.clear()

    # 登记了、外部表里还没有这个品类的帖: 书架空, 内部卡照常, 不补
    sb.tables["external_notes"] = []
    pick[:] = ["n1"]
    res = core.librarian_select_full(dict(brief, brand="西屋", project_name="西屋911gt", project_id="p5", explore=False))
    assert [s["source_note_id"] for s in res["selected"]] == ["n1"] and res["status"] == "ok"
    assert "至少挑" not in seen["system"], "没有外部卡时不提外部卡的用法"
    assert X._shelf.get("家居家电", (None,))[0] == [], "空书架也缓存 (查库成功了, 只是没货)"

    # D-140 (F-10 关): 家居家电有货、遮过了 → 和老品类一样至少 1 张, 模型一张没挑就补
    X._shelf.clear()
    sb.tables["external_notes"] = [dict(r, category="家居家电") for r in rows]
    home = dict(brief, brand="西屋", project_name="西屋911gt", explore=False)
    pick[:] = ["n1"]
    res = core.librarian_select_full(dict(home, project_id="p9"))
    assert [s["source_note_id"] for s in res["selected"]] == ["n1", E[0]] and res["selected"][-1]["forced"] is True, \
        "家居家电遮过了: 一张外部卡没挑就补"
    assert f"[{E[0]}] 外部参考|家居家电" in seen["system"] and "至少挑 1 张、最多 2 张" in seen["system"]
    pick[:] = [E[1], "n1"]
    res = core.librarian_select_full(dict(home, project_id="p10"))
    assert [s["source_note_id"] for s in res["selected"]] == [E[1], "n1"], "模型自己挑的照给"
    X._shelf.clear()
    sb.tables["external_notes"] = rows
    pick[:] = [E[0], "n1"]

    old = [{"source_note_id": "n1", "why_relevant": "r"},
           {"source_note_id": E[1], "why_relevant": "r", "external": True, "posted_days_ago": 1}]
    core.get_cache = lambda s, key: [dict(c) for c in old]
    res = core.librarian_select_full(dict(brief, project_id="p8", explore=False))
    assert res["selected"][0]["external"] is False and res["selected"][0]["validated_hits"] == [], \
        "部署前的缓存行没有这两个键, 命中时补上 (文档承诺选中的卡都带)"
    assert res["selected"][1]["posted_days_ago"] == 11, "命中缓存时「发出几天」按 id 重算, 不是写缓存那天的数"
    core.get_cache = lambda s, key: None

    # 答案分批翻页: 250 篇 → 3 批 (100 / 100 / 50), 每批翻到空页才收工, 服务端把页钳短也不漏
    many = [f"{i:024x}" for i in range(250)]
    db = _SB({"note_feature_answers": [_ans(n, q, "否") for n in many for q in ("efficacy_promise", "turning_point",
                                                                               "opening_type", "own_experience",
                                                                               "title_is_question")]})
    real_page = X._PAGE
    try:
        X._PAGE = 120                                     # 一批 100 篇 × 5 题 = 500 行, 一页只回 120 行
        got = X.fetch_answers(db, many)
    finally:
        X._PAGE = real_page
    assert len(got) == 250 and all(len(v) == 5 for v in got.values()), "分批 + 翻页, 一个答案都不丢"
    assert sum(1 for t, a in db.log if t == "in_" and a[0] == "subject_id") > 3 and \
        max(len(a[1]) for t, a in db.log if t == "in_" and a[0] == "subject_id") == X.ANSWERS_CHUNK
    print("  §6 端到端: 老消费方不给; 两臂都给; 截到 2 张且不占名额; 一张没挑就补遮过的 (forced, 进缓存)、没挑任何卡不补; "
          "一周后命中缓存 why_it_worked 不和重算的天数打架; 摘录 600 字、遮过; 功效题「是」(取最后一次) / 评论不够不上架; "
          "遮挡过期只给结构、没遮挡又没结构不上架; 答案 / 遮挡只给过了前一道的帖查; 答案查不了没有外部卡; 遮挡表没建只给结构、"
          "不强塞、warning 一次; 查库挂了 / 品类没货照样选; 家居家电遮过了照样至少 1 张; 书架进程内缓存; 旧缓存行补键; "
          "答案分批翻页不丢 ✓")


def s6b_ensure_external() -> None:
    """_ensure_external 单测: 满 5 张时顶谁、不到 5 张时不顶、已经有外部卡时不动; 只补摘录遮过的卡。"""
    now = time.time()
    shelf = [X.to_card(ext_row(i, 100 * (i + 1), 10, now=now), CFG, mask=[]) for i in range(3)]   # 日均 10 / 20 / 30
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
    # D-140: 只补摘录遮过的卡。只给结构的那张日均更高也不补它; 书架上只有结构卡 → 不补
    fast = dict(shelf[2], source_note_id="ext:fast", comments_per_day=999.0, masked=False, raw_excerpt="")
    assert [s["source_note_id"] for s in core._ensure_external(three, internal + [fast] + shelf)] == ["i0", "i1", "i2", top], \
        "补的是遮过的卡里日均最高的那张, 不是只给结构那张更快的"
    struct_only = [dict(c, masked=False, raw_excerpt="") for c in shelf]
    assert core._ensure_external(three, internal + struct_only) == three, "书架上只有结构卡: 不补"
    home = [dict(c, category="家居家电") for c in shelf]
    assert core._ensure_external(three, internal + home)[-1]["source_note_id"] == top, "家居家电遮过了照样补 (F-10 关)"
    print("  §6b 外部卡保底: 满 5 张顶 rank 最低的内部卡、不到 5 张只加不顶、有外部卡 / 书架空 / 没挑任何卡都不动; "
          "只补摘录遮过的卡 ✓")


def s7_wiring() -> None:
    src = (ROOT / "scripts" / "check_external_direction.py").read_text(encoding="utf-8")
    assert "X.qualified(" in src and "X.fetch_answers(" in src, \
        "方向复核报的书架达标数要用同一个 qualified (连功效题), 不许另抄一份口径"
    wf = (ROOT / ".github" / "workflows" / "daily-sync.yml").read_text(encoding="utf-8")
    assert "python check_external_direction.py" in wf, "每周方向复核没接进夜跑"
    assert "python mask_external_names.py" in wf and "python backfill_content_layer.py" in wf, \
        "遮挡词 / 内容层补填没接进夜跑"
    lib = (ROOT / "librarian" / "external.py").read_text(encoding="utf-8")
    assert 'get("has_product") is False' not in lib, "D-140: has_product 不再当上架条件"
    print("  §7 接线: 方向复核报书架达标数 (同一个 qualified, 连功效题)、遮挡词和内容层补填接进夜跑 ✓")


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
