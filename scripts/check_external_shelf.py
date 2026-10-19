#!/usr/bin/env python3
"""
check_external_shelf.py —— 外部参考书架 (D-117 ②; prompts/external_shelf_v1.json + librarian/external.py) 的离线守卫。

  §1 配置: 评论门槛和判爆同一把尺子 (50)、每次最多 2 张 (D-117)、一个品牌不许挂两个品类
  §2 同品类: 只看 brief 的品牌 / 项目名 (项目定位里顺嘴提到「戒烟」不算), 大小写不敏感
  §3 达标: 评论够 + Jev 判了没带产品 + 不像广告 + 没点到我们登记的品牌; 没判过的不收 (认不出品牌就不冒险)
  §4 卡面: id 带 ext: 前缀、没有品牌、别家品牌名换成「某品牌」(D-120)、卡头写明只借结构; 有外部卡时 prompt 才多那句用法
  §5 缓存版本: 外部卡进版本串; 没有外部卡时与以前完全一样
  §6 端到端 (打桩): 老消费方不给; 两臂都给; 模型挑多了截到 2 张 (不算契约失败), 截掉的不占 5 张的名额;
     查库挂了照样选内部卡; 外部卡不去查 note 的规律答案; 部署前的缓存行补上 external / validated_hits;
     书架按品类在进程里缓存 10 分钟 (查库失败不缓存), 广告帖在查询里就筛掉
  §7 接线: 方向复核那盏灯报书架达标数, 用的是同一个 qualifies

跑法: cd scripts && python check_external_shelf.py
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from librarian import core, external as X, patterns as P  # noqa: E402

CFG = X.load_config()


def s1_config() -> None:
    import check_external_direction as ced
    assert CFG and CFG["min_comments"] == ced.BAO_COMMENTS == 50, "外部卡的门槛要和判爆同一把尺子 (评论 ≥50)"
    assert CFG["max_per_borrow"] == 2, "D-117: 每次最多占 2 张"
    seen: dict = {}
    for cat, brands in CFG["categories"].items():
        assert brands, f"{cat}: 没登记品牌"
        for b in brands:
            assert b.lower() not in seen, f"{b} 同时挂在 {seen[b.lower()]} 和 {cat}"
            seen[b.lower()] = cat
    print(f"  §1 配置: {len(CFG['categories'])} 个品类、门槛 {CFG['min_comments']}、每次最多 {CFG['max_per_borrow']} 张 ✓")


def s2_match() -> None:
    f = lambda **b: X.categories_for(b, CFG)  # noqa: E731
    assert f(brand="雷诺考特") == ["鼻炎"]
    assert f(brand="sportsix") == f(brand="SPORTSIX") == ["运动补给"]
    assert f(brand="途", project_name="途鸽D-4情绪价值与社会化") == ["求职留学"]
    assert f(brand="唐小轻", project_name="唐小轻-流量-家庭叙事", system_prompt="爸爸戒烟那年…") == [], \
        "只看品牌 / 项目名: 项目定位里提到戒烟不等于做戒烟品类"
    assert f(brand="RIO") == [] and f() == []
    print("  §2 同品类: 只看品牌 / 项目名、大小写不敏感 ✓")


def s3_qualifies() -> None:
    ok = {"comments": 50, "has_product": False, "ad_like": False}
    assert X.qualifies(ok, CFG)
    assert X.qualifies(dict(ok, ad_like=None), CFG)
    assert not X.qualifies(dict(ok, comments=49), CFG)
    assert not X.qualifies(dict(ok, has_product=True), CFG)
    assert not X.qualifies(dict(ok, has_product=None), CFG), "没判过有没有产品的不收"
    assert not X.qualifies(dict(ok, ad_like=True), CFG)
    assert X.qualifies(dict(ok, body="后来换了辅舒良"), CFG), "D-120: 点了别家品牌的照收, 上架时换成「某品牌」"
    assert not X.qualifies(dict(ok, title="雷诺考特用了一周"), CFG), "点了登记品牌 (可能就是我们自己铺的) 不上架"
    assert not X.qualifies(dict(ok, body="试过 SPORTSIX 的胶"), CFG), "登记品牌大小写不敏感"
    print("  §3 达标: 评论 / 没产品 / 不像广告 / 没点我们登记的品牌 ✓")


ROW = {"note_id": "abc", "category": "鼻炎", "title": "换季鼻子又罢工了", "body": "求问大家都怎么熬过去的",
       "comments": 88, "has_product": False, "ad_like": False}
CARD = {"source_note_id": "n1", "tier": "爆", "brand": "雷诺考特", "category": "OTC药", "rank_score": 1.0,
        "curated_at": "2026-10-01", "is_curated": True, "hook_type": "h", "structure": "s",
        "why_it_worked": "w", "transferable_tactic": "t", "raw_excerpt": "e", "synthetic": False}


def s4_card() -> None:
    c = X.to_card(ROW)
    assert c["source_note_id"] == "ext:abc" and c["external"] is True and c["brand"] is None
    txt = core.build_system_blocks({}, [CARD, c])[0]["text"]
    assert "[ext:abc] 外部参考|鼻炎｜别家同品类帖, 只借结构不抄内容" in txt and "评论 88" in txt
    assert "最多挑 2 张" in txt and txt.index("最多挑 2 张") < txt.index("候选经验卡")
    assert "最多挑 2 张" not in core.build_system_blocks({}, [CARD])[0]["text"], "没有外部卡时 prompt 不变"
    # D-120: 别家品牌名换成「某品牌」, 不分大小写, 长的先换
    m = X.to_card(dict(ROW, title="辅舒良和内舒拿我都试过", body="后来朋友推荐 MAURTEN 的胶"), CFG)["raw_excerpt"]
    assert "辅舒良" not in m and "内舒拿" not in m and "maurten" not in m.lower(), m
    assert m.count(X.MASK) == 3, m
    assert X.mask_brands("雅培安素", {"mask_terms": ["雅培", "雅培安素"]}) == X.MASK, "长的先换, 不留半截"
    assert X.mask_brands("没有品牌", None) == "没有品牌" and X.mask_brands("", CFG) == ""
    print("  §4 卡面: ext: 前缀、无品牌、只借结构、别家品牌名换成「某品牌」; 有外部卡才多那句用法 ✓")


def s5_version() -> None:
    cards = [CARD]
    base = core.library_version(cards, gate2_run="g")
    assert core.library_version(cards, gate2_run="g", external=None) == base
    a, b = X.to_card(ROW), X.to_card(dict(ROW, note_id="xyz"))
    assert X.digest([a, b]) == X.digest([b, a])
    v1 = core.library_version(cards, gate2_run="g", external=X.digest([a]))
    v2 = core.library_version(cards, gate2_run="g", external=X.digest([a, b]))
    assert len({base, v1, v2}) == 3
    # mask_terms 补了一个品牌: id 没变, 卡面变了 → 版本必须变, 否则旧缓存里没换掉品牌名的摘录一直被命中
    masked = X.to_card(dict(ROW, body="后来用了新牌子"), {**CFG, "mask_terms": CFG["mask_terms"] + ["新牌子"]})
    plain = X.to_card(dict(ROW, body="后来用了新牌子"), CFG)
    assert masked["source_note_id"] == plain["source_note_id"] and X.digest([masked]) != X.digest([plain])
    print("  §5 缓存版本: 外部卡(连卡面)进版本串、没有时不变 ✓")


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


def s6_end_to_end() -> None:
    rows = [dict(ROW, note_id=f"e{i}", comments=200 - i) for i in range(4)] + \
           [dict(ROW, note_id="prod", comments=999, has_product=True)]
    sb = _SB(rows)
    seen: dict = {}
    core.get_supabase = lambda *a, **k: sb
    core.latest_gate2_run = lambda s: P.load_delivery()["gate2_run"]   # 规律臂有下发, 才会去查命中
    P.verified_against_db = lambda s, d, **kw: True                     # 对库那一步 check_desk_delivery §3 管
    core.fetch_candidates = lambda s, **kw: [dict(CARD), dict(CARD, source_note_id="n2", rank_score=0.5)]
    core.get_cache = lambda s, key: None
    keys: list = []
    core.put_cache = lambda s, key, brief, lib_v, sel, **kw: keys.append(key)
    asked: list = []
    P.fetch_answers = lambda s, ids, d: asked.append(list(ids)) or {}

    def llm(prompt, model, *, system=None, **kw):
        seen["system"] = "\n".join(b["text"] for b in system)
        ids = ["ext:e0", "ext:e1", "n1", "ext:e2"]
        return json.dumps({"selected": [{"source_note_id": i, "why_relevant": "r", "borrow_what": "b"} for i in ids]})
    core.call_anthropic = llm

    brief = {"consumer": "deskcore", "project_id": "p", "brand": "雷诺考特"}
    res = core.librarian_select_full(dict(brief))
    assert "外部参考" not in seen["system"] and not any(s.get("external") for s in res["selected"]), \
        "不带 explore 的老消费方不给外部卡"
    assert not any(t == "table" and a == ("external_notes",) for t, a in sb.log), "老消费方连外部表都不查"

    for arm in (False, True):
        res = core.librarian_select_full(dict(brief, explore=arm))
        ext = [s for s in res["selected"] if s["external"]]
        assert [s["source_note_id"] for s in ext] == ["ext:e0", "ext:e1"], f"explore={arm}: 外部卡截到 2 张"
        assert [s["source_note_id"] for s in res["selected"] if not s["external"]] == ["n1"]
        assert "ext:prod" not in seen["system"] and "[ext:e3]" in seen["system"], "带产品的不上架; 达标的都给模型看"
    assert len(set(keys[-2:])) == 2, "两臂缓存仍分开"
    dry = core.librarian_select(dict(brief, explore=False), dry_run=True)
    want = X.digest([X.to_card(r) for r in rows if X.qualifies(r, CFG)][:CFG["show_per_request"]])
    assert dry["external"] == 4 and dry["library_version"].endswith(f":ext{want}"), "外部书架换一批, 缓存键要跟着换"
    assert asked and all(not str(i).startswith("ext:") for ids in asked for i in ids), "外部卡不查 note 的规律答案"

    assert any(t == "or_" and a == ("ad_like.is.null,ad_like.eq.false",) for t, a in sb.log), "广告帖在查询里就筛掉"

    def llm_many(prompt, model, *, system=None, **kw):
        ids = [f"ext:e{i}" for i in range(4)] + ["ext:e0", "n1", "n2"]
        return json.dumps({"selected": [{"source_note_id": i, "why_relevant": "r", "borrow_what": "b"} for i in ids]})
    core.call_anthropic = llm_many
    res = core.librarian_select_full(dict(brief, project_id="p7", explore=True))
    assert [s["source_note_id"] for s in res["selected"]] == ["ext:e0", "ext:e1", "n1", "n2"], \
        "截掉的外部卡不占名额: 模型多挑了外部卡, 后面合格的内部卡不能被挤掉"
    core.call_anthropic = llm

    calls = sum(1 for t, a in sb.log if t == "table" and a == ("external_notes",))
    X.shelf_for(sb, brief)
    assert sum(1 for t, a in sb.log if t == "table" and a == ("external_notes",)) == calls, "10 分钟内不再拉外部表"
    X._shelf.clear()
    sb.rows = RuntimeError("db down")
    res = core.librarian_select_full(dict(brief, project_id="p2", explore=False))
    assert [s["source_note_id"] for s in res["selected"]] == ["n1"] and res["status"] == "ok", "外部表挂了照样选内部卡"
    assert X._shelf == {}, "查库失败不缓存, 下个请求重查"
    sb.rows = rows
    assert X.shelf_for(sb, brief, now=10 ** 9), "库恢复了就有"

    old = [{"source_note_id": "n1", "why_relevant": "r"}]
    core.get_cache = lambda s, key: [dict(c) for c in old]
    res = core.librarian_select_full(dict(brief, project_id="p8", explore=False))
    assert res["selected"][0]["external"] is False and res["selected"][0]["validated_hits"] == [], \
        "部署前的缓存行没有这两个键, 命中时补上 (文档承诺选中的卡都带)"
    print("  §6 端到端: 老消费方不给; 两臂都给; 截到 2 张且不占名额; 带产品 / 广告不上架; 不查规律答案; "
          "查库挂了照样选; 书架进程内缓存; 旧缓存行补键 ✓")


def s7_wiring() -> None:
    src = (ROOT / "scripts" / "check_external_direction.py").read_text(encoding="utf-8")
    assert "X.qualifies(" in src, "方向复核报的书架达标数要用同一个 qualifies, 不许另抄一份口径"
    wf = (ROOT / ".github" / "workflows" / "daily-sync.yml").read_text(encoding="utf-8")
    assert "python check_external_direction.py" in wf, "每周方向复核没接进夜跑"
    print("  §7 接线: 方向复核报书架达标数 (同一个 qualifies)、接进夜跑 ✓")


def main() -> int:
    s1_config()
    s2_match()
    s3_qualifies()
    s4_card()
    s5_version()
    s6_end_to_end()
    s7_wiring()
    print("\ncheck_external_shelf: 7 节全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
