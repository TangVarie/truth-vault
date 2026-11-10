#!/usr/bin/env python3
"""comment_maintained 分来路记录, 与 synthetic 正交 (D-060) + 「维护情况」取值分路 (A2)
   + 投流三态 (A4)。

从 ci.yml 抽出来的 (2026-09-22)。抽的原因是硬的, 不是洁癖:
ci.yml 涨到 516,314 字节时 GitHub 直接 startup_failure —— 0 个 job、瞬间红、
日志里什么都没有, 只在运行名上把 workflow 名换成了文件路径。上一版 511,110 字节
还能跑。所以这个文件的体积是【真闸】, 不是风格问题。新守卫一律写成 scripts/ 里的
脚本, ci.yml 只留一行调用 (D-075 已经定过这个方向, 这次是被撞出来的实证)。
体积棘轮见 scripts/check_system_map.py 的 G6。

跑法: cd scripts && python check_comment_maintained.py
"""

# owner 2026-09-16: "评论数过了50, 但这有可能是我们刷的, 所以其真实的流量一般般"
#
# 第一版只写一个布尔, 被 codex PR#128 P1 指出内部矛盾。查实测(爆款内按来路分):
#     ① 铺评工单   n=28  中位互动 13
#     ② 起量后干预 n=39  中位互动 856~1225
#     ④ 无干预信号 n=306 中位互动 303
# ② 比【完全没有干预信号】的爆款还高 3~4 倍 —— 是真赢家(对已爆的帖做二次运营)。
# 所以 codex 建议的"把 comment_maintained=true 整体剔出训练集"是【错的】,
# 那会删掉 39 条最真的爆款。真正的问题是一个布尔拆不开两种相反语义 → 改记 routes。
#
# 本守卫钉住四件事, 全部断行为不断源码字符串(D-051):
#   (1) 两条来路必须【分开】记, 不许合并;
#   (2) 爆帖控评置顶 / 爆帖置顶评论 两列必须认(codex P2: 此前完全漏网);
#   (3) routes 顺序必须【跨进程】确定, 否则 upsert 每晚写出不同 JSON;
#   (4) 不许并进 synthetic —— 真爆贴也会控评。
import os, sys, json, subprocess
import sync_feishu_notes_to_truth_vault as s
TICKET, POSTHOC = s._CM_ROUTE_TICKET, s._CM_ROUTE_POSTHOC

BASE = {
    "project_id": "TEST_CM", "platform": "xiaohongshu",
    "field_mapping": {"文案": "raw_content", "互动量": "interactions", "状态": "_status_raw"},
    "tier_extraction": {"source": "状态字段", "rules": [
        {"match_contains": ["伪爆贴"], "tier": "爆"},
        {"match_contains": ["爆贴"], "tier": "爆"},
        {"match_contains": ["无水花"], "tier": "趴"}]},
    "project_specific_fields_to_raw_extra": [
        "维护评论50条", "评论铺设情况", "爆帖控评置顶", "爆帖置顶评论", "评论状态"],
}
def f(n): return n.get("data_quality_flags") or {}
def rt(n): return f(n).get("comment_maintained_routes")

# ① tier 源含「控评」→ 起量后干预; synthetic 仍 false; tier 不变
n1, _, _ = s.transform_row(BASE, "r1", {"文案": "c", "状态": "爆贴 控评✅", "互动量": 500})
assert rt(n1) == [POSTHOC], rt(n1)
assert f(n1).get("synthetic") is False, f"控评被误判成假爆款, 真赢家会被删出飞轮: {f(n1)}"
assert n1["tier"] == "爆", f"这个标记不该动 tier: {n1.get('tier')!r}"

# ② 铺评工单列 → 铺评工单(必须与 ① 分开)
for col in s._CM_TICKET_COLS:
    n, _, _ = s.transform_row(BASE, "r2", {"文案": "c", "状态": "爆贴", col: "评论1 评论2"})
    assert rt(n) == [TICKET], f"{col} 该走铺评工单而非起量后干预: {rt(n)}"
    n0, _, _ = s.transform_row(BASE, "r2b", {"文案": "c", "状态": "爆贴", col: ""})
    assert "comment_maintained" not in f(n0), f"{col} 为空不该命中: {f(n0)}"

# ③ 爆帖控评/置顶列 → 起量后干预 (codex P2: HXZ_QD 3 行全漏, HXZ_FB 9 行漏 5)
for col in s._CM_POSTHOC_COLS:
    n, _, _ = s.transform_row(BASE, "r3", {"文案": "c", "状态": "爆贴", col: "x"})
    assert rt(n) == [POSTHOC], f"{col} 该走起量后干预: {rt(n)}"

# ④ 评论状态: 只认后验干预值, 常规值放行
for v in s._COMMENT_MAINTAINED_STATUS:
    n, _, _ = s.transform_row(BASE, "r4", {"文案": "c", "状态": "爆贴", "评论状态": v})
    assert rt(n) == [POSTHOC], f"{v}: {rt(n)}"
for v in ("没有显示", "显示评论", "正常发布", "待评论", "无需控评"):
    n, _, _ = s.transform_row(BASE, "r4b", {"文案": "c", "状态": "爆贴", "评论状态": v})
    assert "comment_maintained" not in f(n), f"{v} 是常规状态, 不该命中: {f(n)}"

# ⑤ 两条来路同时在场 → 都记, 且顺序【跨进程】确定。
#    set 的迭代序随 PYTHONHASHSEED 变, 单进程内测不出来 —— 第一版这条断言写成
#    `rt == sorted(rt)`, 反证(把 sorted 换成 list)时【没有变红】, 因为单次运行里
#    set 序恰好等于排序序。必须起子进程换种子才测得到。
n5, _, _ = s.transform_row(BASE, "r5", {"文案": "c", "状态": "爆贴 控评✅", "维护评论50条": "x"})
assert set(rt(n5)) == {TICKET, POSTHOC}, rt(n5)
probe = (
    "import sys;sys.path.insert(0,%r);import sync_feishu_notes_to_truth_vault as s,json;"
    "n,_,_=s.transform_row(%r,'p',{'文案':'c','状态':'爆贴 控评✅','维护评论50条':'x'});"
    "print(json.dumps(n['data_quality_flags']['comment_maintained_routes'],ensure_ascii=False))"
) % (os.getcwd(), BASE)
outs = set()
for seed in ("0", "1", "42", "12345"):
    env = {**os.environ, "PYTHONHASHSEED": seed}
    outs.add(subprocess.run([sys.executable, "-c", probe], capture_output=True,
                  text=True, env=env, check=True).stdout.strip())
assert len(outs) == 1, f"routes 顺序随 PYTHONHASHSEED 变, upsert 每晚会写出不同 JSON: {outs}"
assert json.loads(outs.pop()) == sorted([TICKET, POSTHOC]), "routes 必须排序后写"

# ⑥ 飞书多选回的是 list —— 库里「评论状态」实际存成 '["二次评论"]'
n6, _, _ = s.transform_row(BASE, "r6", {"文案": "c", "状态": "爆贴", "评论状态": ["二次评论"]})
assert rt(n6) == [POSTHOC], f"list 形态漏判(库里就是这个形态): {rt(n6)}"

# ⑦ 未声明列路径(D-055 _undeclared) —— BJS/SPX 的「评论状态」就是未声明的
M7 = dict(BASE); M7["project_specific_fields_to_raw_extra"] = []
n7, _, und7 = s.transform_row(M7, "r7", {"文案": "c", "状态": "爆贴", "爆帖置顶评论": "x"})
assert "爆帖置顶评论" in und7, f"前提不成立(该列应落入 undeclared): {und7}"
assert rt(n7) == [POSTHOC], f"_undeclared 路径漏判: {rt(n7)}"

# ⑧ 三路都不在场 → 缺键, 不是 false。
#    写 false = 用"这张表没有控评列"冒充"这条没被控评", 是假阴性。
n8, _, _ = s.transform_row(BASE, "r8", {"文案": "c", "状态": "无水花", "互动量": 2})
assert "comment_maintained" not in f(n8) and "comment_maintained_routes" not in f(n8), \
    f"缺信号时必须缺键, 不许写 false: {f(n8)}"
assert f(n8).get("synthetic") is False, f"synthetic 的显式 false 不受影响: {f(n8)}"

# ⑨ 两个 flag 同时在场时互不干扰
n9, _, _ = s.transform_row(BASE, "r9", {"文案": "c", "状态": "伪爆贴500 控评✅", "互动量": 500})
assert f(n9).get("synthetic") is True and f(n9).get("comment_maintained") is True, f(n9)
assert rt(n9) == [POSTHOC], rt(n9)
assert "伪爆贴" in f(n9).get("synthetic_reason", ""), f(n9)

# ⑩ typed 列 pinned_comment 非空 → 起量后干预 (D-062, owner 拍板并入 route ②)。
#    模板把「爆帖置顶评论」映成 typed 列, raw_extra 里查不到那一列 —— 上面按列名找的
#    循环会漏掉它(生产 127 行, 126 行是爆款)。运营确认这列记的是"第一屏有没有置顶显示",
#    置顶只有作者能做 → 属起量后动作。
#    ⚠️ 夹具要把这列【从 allowlist 里拿掉】: BASE 为了测 HXZ 那种未映射的表把它列在
#    raw_extra allowlist 里, 留着的话值会同时落进 raw_extra, 上面按列名找的循环就把它
#    兜住了 —— 反证时去掉 typed 分支 flag 照样 True, 断言变成空跑(第一版就是这样)。
MP10 = dict(BASE, field_mapping={**BASE["field_mapping"], "爆帖置顶评论": "pinned_comment"},
  project_specific_fields_to_raw_extra=[c for c in BASE.get("project_specific_fields_to_raw_extra", [])
                                        if c != "爆帖置顶评论"])
n10, _, _ = s.transform_row(MP10, "r10", {"文案": "c", "状态": "爆贴", "互动量": 300, "爆帖置顶评论": "第一条置顶"})
assert f(n10).get("comment_maintained") is True and rt(n10) == [POSTHOC], f(n10)
assert "pinned_comment" in f(n10).get("comment_maintained_reason", ""), f(n10)
n10b, _, _ = s.transform_row(MP10, "r10b", {"文案": "c", "状态": "爆贴", "互动量": 300, "爆帖置顶评论": ""})
assert "comment_maintained" not in f(n10b), f"置顶列为空不该算干预: {f(n10b)}"

# ⑪ 「维护情况」按【取值】分路 (A2, 2026-09-22 运营逐值语义)。
#    反证: 若判据退回"列非空即算", 下面 ⑪c 的「✅」会命中 —— 而它是待办不是已铺。
M11 = dict(BASE, project_specific_fields_to_raw_extra=[
    *BASE["project_specific_fields_to_raw_extra"], "维护情况"])
for v, want, n_seed in (("关注", TICKET, 20), ("重点关注⭐️", TICKET, 50),
              ("控评&置顶✅", POSTHOC, 0), ("已评待置顶", POSTHOC, 0)):
    n, _, _ = s.transform_row(M11, "r11", {"文案": "c", "状态": "爆贴", "维护情况": [v]})
    assert rt(n) == [want], f"维护情况「{v}」该走 {want}: {rt(n)}"
    assert f(n).get("comment_maintained_seeded", 0) == n_seed, \
        f"维护情况「{v}」该记 {n_seed} 条已铺: {f(n)}"
# ⑪c 「✅」= 此帖【需要】做50条 = 待办, 一条都不算 —— 列非空即算会在这里红。
n11c, _, _ = s.transform_row(M11, "r11c", {"文案": "c", "状态": "爆贴", "维护情况": ["✅"]})
assert "comment_maintained" not in f(n11c), f"「✅」是待办, 不该命中任何来路: {f(n11c)}"
# ⑪d 同一行两条 route 都在场 —— BJS 6 行「控评&置顶✅」100% 同时带「关注+✅」
n11d, _, _ = s.transform_row(M11, "r11d",
    {"文案": "c", "状态": "爆贴", "维护情况": ["关注", "✅", "控评&置顶✅"]})
assert set(rt(n11d)) == {TICKET, POSTHOC}, f"同行两路都要记: {rt(n11d)}"
assert f(n11d).get("comment_maintained_seeded") == 20, f(n11d)
# ⑪e 多档共存取 max 不求和(20 和 50 描述的是同一批评论, 不是 70 条)
n11e, _, _ = s.transform_row(M11, "r11e",
    {"文案": "c", "状态": "爆贴", "维护情况": ["关注", "重点关注⭐️"]})
assert f(n11e).get("comment_maintained_seeded") == 50, f"该取 max 不求和: {f(n11e)}"
# ⑪f 「关注情况」不参与铺评判据 —— 运营没给过它的逐值语义, 不猜
M11f = dict(BASE, project_specific_fields_to_raw_extra=[
    *BASE["project_specific_fields_to_raw_extra"], "关注情况"])
n11f, _, _ = s.transform_row(M11f, "r11f", {"文案": "c", "状态": "爆贴", "关注情况": ["关注"]})
assert "comment_maintained" not in f(n11f), \
    f"「关注情况」里的「关注」运营没定义过语义, 不许当铺评: {f(n11f)}"

# ⑫ 投流三态 (A4)。false 只在【声明了「维护情况」】的表里给, 否则缺键。
for v in ("9/15🍟", "08/27🍟", "已投流，等回收数据"):
    n, _, _ = s.transform_row(M11, "r12", {"文案": "c", "状态": "爆贴", "维护情况": [v]})
    assert f(n).get("paid_promoted") is True, f"投流取值「{v}」漏判: {f(n)}"
# ⑫b 🍟 也可能记在「关注情况」里(ANSHEN 2 行 + SPX 1 行, 占三列合计的 15%)
n12b, _, _ = s.transform_row(M11f, "r12b", {"文案": "c", "状态": "爆贴", "关注情况": ["9/16🍟"]})
assert f(n12b).get("paid_promoted") is True, f"关注情况里的 🍟 漏判: {f(n12b)}"
# ⑫c 途鸽把投流记在 tier 源里(「关注后续流量」9 行, 7 行已进书架)。
#     夹具用生产的形状: 「流量状态」是多选, 原值是 list —— 2026-10-29 生产 9 行的 _tier_source_raw
#     全是 "['关注后续流量', '爆贴' …]" 这种 str(list)。D-133 起按元素精确匹配。
n12c, _, _ = s.transform_row(BASE, "r12c", {"文案": "c", "状态": ["关注后续流量", "爆贴"]})
assert f(n12c).get("paid_promoted") is True, f"tier 源里的投流标记漏判: {f(n12c)}"
assert f(n12c).get("paid_promoted_reason") == "tier 源含「关注后续流量」(运营 2026-09-22: 投流会给的标记)", \
    f"reason 文本要和 A4 一字不差, 否则每晚多一条 audit: {f(n12c)}"
assert "paid_marker_unrecognized" not in f(n12c), f(n12c)
# ⑫g 整串「关注后续流量 爆贴」(一个元素) 认不出日期也认不出是哪个选项 → 不写 paid_promoted (不知道),
#     记 paid_marker_unrecognized; data_quality_flags 一定带上 (受保护列, 不带就留着库里旧的 true)。
#     反证: 退回 A4 的子串判据, 这里会是 True。
n12g, _, _ = s.transform_row(BASE, "r12g", {"文案": "c", "状态": "关注后续流量 爆贴"})
assert "paid_promoted" not in f(n12g), f"认不出的标记不许判投流: {f(n12g)}"
assert f(n12g).get("paid_marker_unrecognized") == ["tier 源取值「关注后续流量 爆贴」"], f(n12g)
# ⑫h 「准备投流」「不投流」含「投流」两个字但不是投流 → 不是 True; 有「维护情况」这一列也不判 false (不知道)
for v in ("准备投流", "不投流"):
    n12h, _, _ = s.transform_row(M11, "r12h", {"文案": "c", "状态": "爆贴", "维护情况": ["关注", v]})
    assert "paid_promoted" not in f(n12h), f"「{v}」不是投流, 也不能说没投: {f(n12h)}"
    assert f(n12h).get("paid_marker_unrecognized") == [f"「维护情况」取值「{v}」"], f(n12h)
# ⑫i 认得出的和认不出的同在一格 → True (认得出的那个算数), 认不出的照记
n12i, _, _ = s.transform_row(M11, "r12i", {"文案": "c", "状态": "爆贴", "维护情况": ["9/15🍟", "准备投流"]})
assert f(n12i).get("paid_promoted") is True and f(n12i).get("paid_promoted_reason") == "「维护情况」取值「9/15🍟」", f(n12i)
assert f(n12i).get("paid_marker_unrecognized") == ["「维护情况」取值「准备投流」"], f(n12i)
# ⑫d 有这一列但没投流取值 → false(运营 2026-09-22:「维护情况」留空=没做维护)
n12d, _, _ = s.transform_row(M11, "r12d", {"文案": "c", "状态": "爆贴", "维护情况": ["关注"]})
assert f(n12d).get("paid_promoted") is False, f"有列无投流值该判 false: {f(n12d)}"
# ⑫e 【没有】这一列 → 缺键, 不是 false。写 false = 拿"这张表没这列"冒充"没投流"。
n12e, _, _ = s.transform_row(BASE, "r12e", {"文案": "c", "状态": "爆贴"})
assert "paid_promoted" not in f(n12e), f"没有这一列时必须缺键: {f(n12e)}"
# ⑫f 只看 _common.PAID_COLS 这两列, 不许扫整个 raw_extra —— 生产里别的列也带 🍟:
#    RIO 有个账号昵称带 🍟, ANSHEN 有两条评论区快照带 🍟。
#    夹具用一个【已声明进 raw_extra 且不在 PAID_COLS 里】的列, 才够得着这个场景
#    (账号名走 _account_name 中间量, 判据跑完之后才倒进 raw_extra, 测不到)。
M12f = dict(BASE, project_specific_fields_to_raw_extra=[
    *BASE["project_specific_fields_to_raw_extra"], "评论区快照"])
n12f, _, _ = s.transform_row(M12f, "r12f",
    {"文案": "c", "状态": "爆贴", "评论区快照": "楼主是🍟的合成小号 求链接"})
assert "paid_promoted" not in f(n12f), \
    f"别的列里的 🍟 不是投流标记, 判据不许扫整个 raw_extra: {f(n12f)}"

# ⑬ 减法重判 (D-084 B1, owner 2026-09-23): 评论数 − 已铺 ≥ 50 → 「铺评未跨线」(放行), 否则仍 铺评工单。
#    夹具要把「评论数」映成 typed 列 comments_count, 否则减法没数可减。
SEEDED_OK = s._CM_ROUTE_SEEDED_OK
M13 = dict(M11, field_mapping={**BASE["field_mapping"], "评论数": "comments_count"})
def _cm(rid, row):
    n, _, _ = s.transform_row(M13, rid, {"文案": "c", "状态": "爆贴", **row})
    return n
n13a = _cm("r13a", {"维护情况": ["关注"], "评论数": 49})
assert rt(n13a) == [TICKET] and f(n13a)["comment_maintained_seeded"] == 20, f"49−20=29 < 50 该剔: {f(n13a)}"
n13b = _cm("r13b", {"维护情况": ["关注"], "评论数": 73})
assert rt(n13b) == [SEEDED_OK] and f(n13b)["comment_maintained_seeded"] == 20, f"73−20=53 ≥ 50 是真赢家: {f(n13b)}"
assert "53" in f(n13b)["comment_maintained_reason"], f(n13b)
assert n13b["tier"] == "爆", "减法只决定挡不挡, 不动 tier"
n13c = _cm("r13c", {"维护情况": ["关注"], "评论数": 70});  assert rt(n13c) == [SEEDED_OK], f"边界 70−20=50 含等号: {rt(n13c)}"
n13d = _cm("r13d", {"维护情况": ["关注"], "评论数": 69});  assert rt(n13d) == [TICKET], f"69−20=49 不够: {rt(n13d)}"
n13e = _cm("r13e", {"维护情况": ["关注"]});                 assert rt(n13e) == [TICKET], f"没评论数不减、照旧剔: {rt(n13e)}"
# 工单列: D-150 起减格子里的行数, 封顶 50 (逐条见 ⑮); 这里用 60 行的格子钉住封顶那一头
_CELL60 = "\n".join(f"示例评论{i}" for i in range(60))
n13f = _cm("r13f", {"维护评论50条": _CELL60, "评论数": 100}); assert rt(n13f) == [SEEDED_OK], f"工单列封顶 50 条: 100−50=50 过线: {rt(n13f)}"
n13g = _cm("r13g", {"维护评论50条": _CELL60, "评论数": 99});  assert rt(n13g) == [TICKET], f"99−50=49 不够: {rt(n13g)}"
n13h = _cm("r13h", {"维护情况": ["关注", "控评&置顶✅"], "评论数": 205})
assert set(rt(n13h)) == {SEEDED_OK, POSTHOC}, f"真赢家 + 起量后干预 两路都在: {rt(n13h)}"
# 下游只认「铺评工单」: 通道 1 的共用判据对 铺评未跨线 放行、对 铺评工单 仍挡 (书架 v1.14 / L2 v1.15 的 SQL 同样只 ? '铺评工单')
import sync_truth_vault_baokuan_to_sanshengliubu as ssll
assert ssll.metric_tier_untrustworthy_reason({"tier": "爆", "data_quality_flags": f(n13b)}) is None, "铺评未跨线 该进通道 1"
assert ssll.metric_tier_untrustworthy_reason({"tier": "爆", "data_quality_flags": f(n13a)}) == TICKET, "铺评工单 仍该挡"
# 反证: 把爆线抬到天上 → 73 那条退回 铺评工单 (规则真的在减法上)
_saved = s._COMMENT_TIER_BAO; s._COMMENT_TIER_BAO = 10**9
try:
    assert rt(_cm("r13x", {"维护情况": ["关注"], "评论数": 73})) == [TICKET], "反证失败: 减法规则没生效"
finally:
    s._COMMENT_TIER_BAO = _saved

# ⑭ 风控旗子的来源列整轮不见了 (外部评审 11-04 F01)。驱动真的 main(), 库和飞书打桩。
#    改名 维护情况 → 库里的 铺评工单 routes 沿用 + 红; 改名 笔记状态 → 库里的 synthetic:true 沿用 + 红;
#    列还在、只是这一格清空了 → 照常清掉(运营清标记的路不能被这道闸堵死), 也不读库。
#    反证: 把 main() 里的 carry_risk_flags 换成恒 {} → A / B 两条红(旗子被冲掉、不计错)。
#    rc 另受「要害字段整列空」(D-056, 合成行没填指标)影响, 所以按扣掉那一项之后的 errors 判红绿。
import io, logging
s14 = s
M14 = {
    "project_id": "T_CM14", "platform": "xiaohongshu",
    "field_mapping": {"文案": "raw_content", "标题": "title", "流量状态": "_status_raw",
                      "笔记状态": "_note_status_raw", "评论数": "comments_count"},
    "tier_extraction": {"source": "状态字段", "rules": [
        {"match_contains": ["大爆"], "tier": "大爆"}, {"match_contains": ["爆贴"], "tier": "爆"},
        {"match_contains": ["无水花"], "tier": "趴"}]},
    "project_specific_fields_to_raw_extra": ["维护情况"],
    "sync_config": {"feishu_app_token": "app", "feishu_table_id": "tbl"},
}
def _stored(row):     # 库里这篇的旗子 = 改名之前那一晚 transform_row 写进去的
    n, _, _ = s.transform_row(M14, "r1", {"文案": "c", "标题": "t", **row})
    return n["data_quality_flags"]

def _run14(rows, stored, read_ok=True, schema=None, argv_extra=()):
    """schema = 飞书表结构里的列名(None = 读表结构失败)。"""
    cap = {"read": 0, "schema": 0}
    saved = {k: getattr(s14, k) for k in (
        "FeishuClient", "get_supabase_client", "assert_db_schema_ready", "ensure_project_exists",
        "quarantine_record", "fetch_acknowledged_quarantine", "ensure_accounts_batch", "upsert_metrics_batch",
        "update_project_date_range", "fetch_all_pages", "upsert_notes_batch", "load_mapping",
        "_detect_missing_core_columns", "_current_tiers", "prepare_content_layer", "stored_flags_batch")}
    saved_argv = sys.argv
    class F:
        def __init__(self, *a, **k): pass
        def list_records(self, *a, **k):
            return iter([{"record_id": rid, "fields": {"文案": "正文正文", "标题": "t", **fl}} for rid, fl in rows])
        def list_field_names(self, *a, **k):
            cap["schema"] += 1
            if schema is None:
                raise RuntimeError("读表结构失败")
            return set(schema)
    def read(sb, pid, ids):
        cap["read"] += 1
        return {f"T_CM14_{k}": v for k, v in stored.items()} if read_ok else None
    def up(sb, notes, dry_run=False):
        cap["notes"] = {n["note_id"]: n for n in notes}
        return {n["note_id"] for n in notes}
    try:
        s14.FeishuClient = F
        s14.get_supabase_client = lambda *a, **k: object()
        s14.assert_db_schema_ready = lambda *a, **k: None
        s14.ensure_project_exists = lambda *a, **k: None
        s14.quarantine_record = lambda *a, **k: None
        s14.fetch_acknowledged_quarantine = lambda *a, **k: set()
        s14.ensure_accounts_batch = lambda *a, **k: []
        s14.upsert_metrics_batch = lambda *a, **k: (0, [])
        s14.update_project_date_range = lambda *a, **k: None
        s14.fetch_all_pages = lambda *a, **k: []
        s14.load_mapping = lambda _p: M14
        s14._detect_missing_core_columns = lambda *a, **k: []
        s14._current_tiers = lambda *a, **k: {}
        s14.prepare_content_layer = lambda *a, **k: False
        s14.stored_flags_batch = read
        s14.upsert_notes_batch = up
        os.environ.setdefault("FEISHU_APP_ID", "x"); os.environ.setdefault("FEISHU_APP_SECRET", "y")
        buf = io.StringIO(); h = logging.StreamHandler(buf)
        handlers, s14.logger.handlers = s14.logger.handlers, [h]     # 日志只进 buf, 不刷 CI
        sys.argv = ["x", "T_CM14", *argv_extra]
        try:
            rc = s14.main()
        finally:
            s14.logger.handlers = handlers
    finally:
        for k, v in saved.items():
            setattr(s14, k, v)
        sys.argv = saved_argv
    st = json.loads(buf.getvalue().split("Done: ")[1].split("\n")[0])
    # 合成行没填曝光 / 互动等, 「要害字段整列空」那道闸每列各计一次错(D-056), 与本节无关, 扣掉再看
    return rc, st["errors"] - len(st["missing_capabilities"]), st, cap

# A) 维护情况 改名(新名落进 _undeclared): 库里 铺评工单 routes 沿用, 红, 点名这一列
st_a = _stored({"流量状态": "爆贴", "评论数": 55, "维护情况": ["关注"]})
assert st_a["comment_maintained_routes"] == [TICKET], f"前提: 改名前库里是 铺评工单: {st_a}"
SCHEMA14 = {"文案", "标题", "流量状态", "笔记状态", "评论数", "维护情况"}
rc, err, st, cap = _run14([("r1", {"流量状态": "爆贴", "评论数": 55, "维护情况（新）": ["关注"]}),
                           ("r2", {"流量状态": "无水花"})], {"r1": st_a},
                          schema=SCHEMA14 - {"维护情况"} | {"维护情况（新）"})
fa = cap["notes"]["T_CM14_r1"]["data_quality_flags"]
assert fa.get("comment_maintained") is True and fa.get("comment_maintained_routes") == [TICKET] \
    and fa.get("comment_maintained_seeded") == 20, f"⑭A 维护情况改名后库里的 铺评工单 被冲掉了: {fa}"
assert fa.get("risk_flags_carried_from_db") == ["维护情况"], fa
assert rc == 1 and err == 1 and st["risk_source_columns_missing"] == ["维护情况"] and st["risk_flags_carried"] == 1, \
    f"⑭A 要红并点名列: rc={rc} {st}"
assert "comment_maintained" not in cap["notes"]["T_CM14_r2"]["data_quality_flags"], "⑭A 库里没旗子的篇照常"
import sync_truth_vault_baokuan_to_sanshengliubu as ssll14
assert ssll14.metric_tier_untrustworthy_reason({"tier": "爆", "data_quality_flags": fa}) == TICKET, "⑭A 下游仍挡"

# B) 笔记状态 改名: 库里 synthetic:true 沿用(不是被显式写 false), 红
st_b = _stored({"流量状态": "大爆", "笔记状态": "关注"})
assert st_b["synthetic"] is True, f"前提: 改名前库里是伪爆: {st_b}"
rc, err, st, cap = _run14([("r1", {"流量状态": "大爆", "笔记状态（新）": "关注"}),
                           ("r2", {"流量状态": "爆贴"})], {"r1": st_b},
                          schema=SCHEMA14 - {"笔记状态"} | {"笔记状态（新）"})
fb = cap["notes"]["T_CM14_r1"]["data_quality_flags"]
assert fb.get("synthetic") is True and s._SYN_NOTE_STATUS_REASON in fb.get("synthetic_reason", ""), \
    f"⑭B 笔记状态改名后 synthetic 被写成 false: {fb}"
assert rc == 1 and err == 1 and st["risk_source_columns_missing"] == ["笔记状态"], f"⑭B 要红: rc={rc} {st}"
assert cap["notes"]["T_CM14_r2"]["data_quality_flags"].get("synthetic") is False, "⑭B 库里没伪爆的篇照常写 false"

# C) 两列都还在(别的行返回了), 只是这一篇的格子清空了 → 照常清掉、绿、不读库
rc, err, st, cap = _run14([("r1", {"流量状态": "大爆"}),
                           ("r2", {"流量状态": "爆贴", "笔记状态": "正常", "维护情况": ["✅"]})],
                          {"r1": {**st_a, **st_b}})
fc = cap["notes"]["T_CM14_r1"]["data_quality_flags"]
assert "comment_maintained" not in fc and fc.get("synthetic") is False and fc.get("paid_promoted") is False, \
    f"⑭C 列还在时运营清空格子要清得掉: {fc}"
assert err == 0 and cap["read"] == 0 and cap["schema"] == 0 and st["risk_source_columns_missing"] == [], \
    f"⑭C 正常路径: 不红、不读库、不读表结构: rc={rc} read={cap['read']} schema={cap['schema']} {st}"

# D) 列不见了又读不到库 → 这一轮 data_quality_flags 整列不写(留库里旧 JSON), 红
rc, err, st, cap = _run14([("r1", {"流量状态": "大爆"})], {}, read_ok=False)
assert "data_quality_flags" not in cap["notes"]["T_CM14_r1"] and rc == 1 and err == 1, \
    f"⑭D 读不到库: 不写这一列 + 红: rc={rc} {cap['notes']}"

# E) 声明了但从来没值、库里也没有它判出来的旗子 → 不红(不会每晚误报)
rc, err, st, cap = _run14([("r1", {"流量状态": "爆贴"})], {"r1": {"synthetic": False, "paid_promoted": False}})
assert err == 0 and cap["read"] == 1, f"⑭E 没有证据就不红: rc={rc} {st}"

# G) 列还在表结构里, 只是这一轮整列格子都空了(飞书不返回空格子, 一行都没返回这一列): 运营清掉了最后一个标记
#    → 照常清掉、不红、不读库(复核 11-04: SPX 关注情况 整列只有 1 格有值, 清掉它不能每晚红、清不掉)
rc, err, st, cap = _run14([("r1", {"流量状态": "大爆"}), ("r2", {"流量状态": "爆贴"})],
                          {"r1": {**st_a, **st_b}}, schema=SCHEMA14)
fg = cap["notes"]["T_CM14_r1"]["data_quality_flags"]
assert "comment_maintained" not in fg and fg.get("synthetic") is False and "risk_flags_carried_from_db" not in fg, \
    f"⑭G 整列格子清空(列还在)要清得掉: {fg}"
assert err == 0 and cap["schema"] == 1 and cap["read"] == 0 and st["risk_source_columns_missing"] == [], \
    f"⑭G 列还在: 不红、不读库: rc={rc} {st} {cap['schema']} {cap['read']}"
# G2) 表结构读不到 → 按不见了处理(核之前的行为): 沿用 + 红
rc, err, st, cap = _run14([("r1", {"流量状态": "大爆"}), ("r2", {"流量状态": "爆贴"})],
                          {"r1": {**st_a, **st_b}}, schema=None)
assert cap["notes"]["T_CM14_r1"]["data_quality_flags"].get("synthetic") is True and err == 2, \
    f"⑭G2 表结构读不到: 沿用 + 红: {err} {st}"

# H) --limit 跑(不完整)又读不到库: 整列不写照旧, 但不红(同沿用那一支: 不完整的一轮少返回一列不算证据)
rc, err, st, cap = _run14([("r1", {"流量状态": "大爆"}), ("r2", {"流量状态": "爆贴"})], {}, read_ok=False,
                          argv_extra=("--limit", "1"))
assert "data_quality_flags" not in cap["notes"]["T_CM14_r1"] and err == 0, \
    f"⑭H --limit + 读不到库: 不写这一列、不红: {err} {st} {cap['notes']}"

# J) 沿用是「合」不是「换」(codex #269): 维护情况 不见了(库里只判出 起量后干预), 维护评论50条 这一轮新填了 20 行
#    → 这一轮判出的 铺评工单 + 已铺 20 (D-150: 按行数, 55−20=35 不够线) 要留着, 库里的 起量后干预 也要留着; 下游照挡。
#    反证: carry_risk_flags 退回整族替换 → 铺评工单 和 seeded 被换掉, metric_tier_untrustworthy_reason 回 None。
st_j = _stored({"流量状态": "爆贴", "评论数": 55, "维护情况": ["控评&置顶✅"]})
assert st_j["comment_maintained_routes"] == [POSTHOC], f"前提: 库里只有 起量后干预: {st_j}"
_saved_extra = list(M14["project_specific_fields_to_raw_extra"])
M14["project_specific_fields_to_raw_extra"] = _saved_extra + ["维护评论50条"]
try:
    rc, err, st, cap = _run14([("r1", {"流量状态": "爆贴", "评论数": 55,
                                       "维护评论50条": "\n".join(f"示例评论{i}" for i in range(20))})], {"r1": st_j},
                              schema=SCHEMA14 - {"维护情况"} | {"维护评论50条"})
finally:
    M14["project_specific_fields_to_raw_extra"] = _saved_extra
fj = cap["notes"]["T_CM14_r1"]["data_quality_flags"]
assert set(fj.get("comment_maintained_routes") or []) == {TICKET, POSTHOC} and fj.get("comment_maintained_seeded") == 20, \
    f"⑭J 这一轮新判出的 铺评工单 / 已铺 20 (按行数) 没留住 (被库里旧的整族换掉, 或没按行数减): {fj}"
assert "维护评论50条" in fj.get("comment_maintained_reason", "") and "控评&置顶✅" in fj.get("comment_maintained_reason", ""), fj
assert fj.get("risk_flags_carried_from_db") == ["维护情况"] and rc == 1 and err == 1, f"⑭J 照旧红: rc={rc} {st}"
assert ssll14.metric_tier_untrustworthy_reason({"tier": "爆", "data_quality_flags": fj}) == TICKET, "⑭J 下游要挡"
# J2) 纯函数: 布尔任一为 true; 库里有、这一轮没有的键补上; 这一轮有的键不被库里的覆盖
_m = s._merge_risk_family({"synthetic": False, "paid_promoted": False}, {"synthetic": True, "synthetic_reason": "x"},
                          "synthetic")
assert _m == {"synthetic": True, "synthetic_reason": "x"}, _m
_m = s._merge_risk_family({"paid_promoted": True, "paid_promoted_reason": "new"},
                          {"paid_promoted": True, "paid_promoted_reason": "old; new"}, "paid_promoted")
assert _m == {"paid_promoted": True, "paid_promoted_reason": "new; old"}, _m

# I) 沿用标记是每一轮现判的键: 以库里旗子为底补正文时剥掉, 不会在列修好之后还挂着
_n14 = {"note_id": "T_CM14_r9", "raw_extra": {}}
s.mark_recovered_body(_n14, {"route": "kept", "filled": ["raw_content"]},
                      stored_flags={**st_b, "risk_flags_carried_from_db": ["笔记状态"]})
assert "risk_flags_carried_from_db" not in _n14["data_quality_flags"] and _n14["data_quality_flags"]["synthetic"] is True, \
    f"⑭I 补正文以库里旗子为底时, 旧的沿用标记要剥掉: {_n14['data_quality_flags']}"

# F) 读库分批(in_ 走 URL, 每批 ≤ 100), 读不到回 None
class _Q14:
    def __init__(self): self.batches = []
    def __getattr__(self, name):
        def step(*a, **k):
            if name == "in_": self.batches.append(list(a[1]))
            return self
        return step
_q14 = _Q14(); _saved_fap = s.fetch_all_pages
s.fetch_all_pages = lambda q, order_by=None: [{"note_id": i, "data_quality_flags": {"synthetic": True}} for i in q.batches[-1]]
try:
    got = s.stored_flags_batch(_q14, "T", [f"n{i}" for i in range(230)])
    assert len(got) == 230 and [len(b) for b in _q14.batches] == [100, 100, 30], _q14.batches
    s.fetch_all_pages = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("库挂了"))
    assert s.stored_flags_batch(_Q14(), "T", ["n1"]) is None, "⑭F 读不到 → None"
finally:
    s.fetch_all_pages = _saved_fap

print("  ⑭ 风控来源列整轮不见: 维护情况改名留 routes + 红 · 笔记状态改名留 synthetic + 红 · 格子清空照常清 · "
      "整列清空但表结构还在照常清 · 读不到不写 · 无证据不红 · 不完整的一轮不红 ✓")

# ⑮ 工单列减的是格子里的行数 (D-150, owner 2026-11-10「贴几条就是发了几条」): 已铺 = 行数, 封顶 50; 数不出行数
#    (不是文本 / 有一行是好几条用空格接成的一长串 / 一条都不剩) 照旧按 50。「维护情况」那几档不变。夹具里的评论都是编的。
#    ⚠️ 先走 transform_row 断行为, 纯函数放后面: 拿 D-150 之前的引擎跑, 第一条 (⑮a) 就红在断言上, 不是红在缺函数上。
#    反证: 退回一律 50 → ⑮a 红 (80−50=30 不够线, 照旧剔); 拿掉封顶 → ⑮c 红; 不切同一行的编号 → ⑮d 红;
#    拿掉「一长串」那条 → ⑮e 红 (12 段算 1 条, 80−1 过线放出去); 空行 / 编号行 / 【…】行也算 → ⑮f 红。
def _lines(k, fmt="示例评论{}"):
    return "\n".join(fmt.format(i) for i in range(1, k + 1))
def _cm15(cell, cc, rid="r15"):
    n = _cm(rid, {"维护评论50条": cell, "评论数": cc})
    return rt(n), f(n).get("comment_maintained_seeded"), f(n).get("comment_maintained_reason", "")
# a) 20 行 + 评论数 80 → 80−20=60 过线 → 铺评未跨线, 记已铺 20; reason 写数到几行
r15, sd15, why15 = _cm15(_lines(20), 80)
assert r15 == [SEEDED_OK] and sd15 == 20, f"⑮a 20 行该减 20, 80−20=60 ≥ 50 放行: {r15} {sd15} {why15}"
assert "数到 20 行" in why15 and "80 − 已铺 20 = 60" in why15, f"⑮a reason 要写数到几行、减完多少: {why15}"
assert ssll.metric_tier_untrustworthy_reason({"tier": "爆", "data_quality_flags": {"comment_maintained_routes": r15}}) is None
# b) 20 行 + 评论数 60 → 60−20=40 不够 → 铺评工单; 边界 70 含等号
r15, sd15, _w = _cm15(_lines(20), 60)
assert r15 == [TICKET] and sd15 == 20, f"⑮b 60−20=40 < 50 照剔: {r15} {sd15}"
assert ssll.metric_tier_untrustworthy_reason({"tier": "爆", "data_quality_flags": {"comment_maintained_routes": r15}}) == TICKET
assert _cm15(_lines(20), 70)[0] == [SEEDED_OK] and _cm15(_lines(20), 69)[0] == [TICKET], "⑮b 边界 70−20=50 放 / 69 剔"
# c) 50 行以上封顶 50
for k15 in (50, 51, 87):
    r15, sd15, why15 = _cm15(_lines(k15), 99)
    assert r15 == [TICKET] and sd15 == 50, f"⑮c {k15} 行封顶 50, 99−50=49 不够: {r15} {sd15}"
    assert ("封顶 50 条" in why15) == (k15 > 50) and f"数到 {k15} 行" in why15, why15
assert _cm15(_lines(87), 100)[0] == [SEEDED_OK], "⑮c 封顶之后 100−50=50 过线"
# d) 一行写了好几条带编号的要切开数: 「1. … 2. …」(编号前有空白, D-085 那套) 和「1、…。2、…」(紧贴前文)
sp15 = " ".join(f"{i}. 示例评论{i}" for i in range(1, 21))
gl15 = "".join(f"{i}、示例评论{i}。" for i in range(1, 21))
for cell15, want15 in ((sp15, 20), (gl15, 20), (sp15 + "\n" + _lines(5, "示例补充{}"), 25)):
    r15, sd15, _w = _cm15(cell15, 60)
    assert sd15 == want15 and r15 == [TICKET], f"⑮d 编号写在同一行要切开数: {cell15[:24]}… → {sd15} {r15}"
assert _cm15(gl15, 70)[0] == [SEEDED_OK], "⑮d 切开数成 20 条, 70−20=50 放"
assert s.count_ticket_lines("1. 示例评论花了2.5万\n2. 示例评论面了3、4家")[0] == 2, "小数、「3、4 家」不是编号, 不切"
# 两种写法混在同一行 (Codex TV#276): 先紧贴后空白、先空白后紧贴, 都要一遍数全; 少数一条就会把 52 条的帖放出去
mx15 = "1、示例评论一。2、示例评论二。 3、示例评论三"
assert s.count_ticket_lines(mx15)[0] == 3 and s.count_ticket_lines("1. 示例评论一 2. 示例评论二。3、示例评论三")[0] == 3, "⑮d 混写也切开"
assert _cm15(mx15, 52)[:2] == ([TICKET], 3), "⑮d 混写数成 3 条: 52−3=49 不够线, 照剔"
assert s.count_ticket_lines("12、示例评论十二 13、示例评论十三")[0] == 2 and s.count_ticket_lines("1、示例评论面了12、13家")[0] == 1, "⑮d 「12、」里的「2、」不是编号"
# 紧贴的编号要接着行首往下数 (1 → 2 → 3…): 行首 1、正文里一个「3、」不是第 2 条, 不切 (反证: 拿掉连号那条 → 切成 2 条)
assert s.count_ticket_lines("1、示例评论面了3、四家")[0] == 1, s.count_ticket_lines("1、示例评论面了3、四家")
assert s.count_ticket_lines("1、示例评论一。2、示例评论二。4、示例评论四")[0] == 2, "连号断在 4: 只切到 2"
# e) 数不出 → 照旧按 50: 不是文本 / 一行是 ≥ 10 段空白接成的一长串 (哪怕前面有正常的行) / 只有【…】标签 / 只有空白
blob15 = " ".join(f"示例评论{i}" for i in range(1, 13))          # 12 条用空格接成一行
for cell15 in (["示例评论1", "示例评论2"], blob15, _lines(19) + "\n" + blob15, "【示例配图说明】", "   \n  "):
    r15, sd15, why15 = _cm15(cell15, 80)
    assert r15 == [TICKET] and sd15 == 50, f"⑮e 数不出该按 50 (80−50=30 照剔): {cell15!r:.40} → {r15} {sd15} {why15}"
    assert "数不出条数, 按 50 条算" in why15, why15
assert s.count_ticket_lines("示例 评论 夹了 几个 空格 one two three four")[0] == 1, "9 段以内照常算 1 条"
# f) 空行、只有编号的行、只有【…】的行不算; 「666」这种光数字是一条评论, 算
cell15 = "\n\n" + "\n\n  \n".join(f"示例评论{i}" for i in range(1, 21)) + "\n\n"
assert _cm15(cell15, 70)[1] == 20, "⑮f 空行不算"
cell15 = "\n".join(f"{i}.\n示例评论{i}" for i in range(1, 21)) + "\n【示例配图】\n(21)\n666"
assert s.count_ticket_lines(cell15)[0] == 21, f"⑮f 编号行 / 标签行不算, 666 算: {s.count_ticket_lines(cell15)}"
# g) 列没声明 (落进 _undeclared) 同样按行数
M15 = dict(M13, project_specific_fields_to_raw_extra=[
    c for c in M13["project_specific_fields_to_raw_extra"] if c != "维护评论50条"])
n15g, _, und15 = s.transform_row(M15, "r15g", {"文案": "c", "状态": "爆贴", "维护评论50条": _lines(20), "评论数": 80})
assert "维护评论50条" in und15 and rt(n15g) == [SEEDED_OK] and f(n15g)["comment_maintained_seeded"] == 20, f(n15g)
# h) 和「维护情况」的档同在 → 取大 (同一批评论, 不求和)
n15h = _cm("r15h", {"维护评论50条": _lines(20), "维护情况": ["重点关注⭐️"], "评论数": 80})
assert rt(n15h) == [TICKET] and f(n15h)["comment_maintained_seeded"] == 50, f(n15h)
n15h = _cm("r15h2", {"维护评论50条": _lines(30), "维护情况": ["关注"], "评论数": 79})
assert rt(n15h) == [TICKET] and f(n15h)["comment_maintained_seeded"] == 30, f(n15h)
# i) 来源列不见了那一轮 (F01) 沿用库里旗子: seeded 现在能 < 50, 合并仍只往更挡的方向 ——
#    库里 D-150 之前的 铺评工单 / 50, 这一轮按行数判成 铺评未跨线 / 20 → routes 两个都在 (照挡), seeded 记 50
_m = s._merge_risk_family(
    {"comment_maintained": True, "comment_maintained_routes": [SEEDED_OK], "comment_maintained_seeded": 20},
    {"comment_maintained": True, "comment_maintained_routes": [TICKET], "comment_maintained_seeded": 50},
    "comment_maintained")
assert _m["comment_maintained_routes"] == sorted([SEEDED_OK, TICKET]) and _m["comment_maintained_seeded"] == 50, _m
assert ssll.metric_tier_untrustworthy_reason({"tier": "爆", "data_quality_flags": _m}) == TICKET, "⑮i 合并后照挡"
_m = s._merge_risk_family({"comment_maintained": True, "comment_maintained_seeded": 30},
                          {"comment_maintained": True, "comment_maintained_seeded": 20}, "comment_maintained")
assert _m["comment_maintained_seeded"] == 30, f"⑮i 这一轮多也记大的: {_m}"
print("  ⑮ 工单列按行数减 (D-150): 20 行 80 放 / 60 剔 · 封顶 50 · 同一行的编号切开 · 数不出按 50 · "
      "空行 / 编号行 / 标签行不算 · 和维护情况取大 · 沿用时只往更挡合 ✓")

print("comment_maintained 分来路 × synthetic 正交 × 维护情况取值 × 投流三态 × 减法重判 × 来源列消失 × 按行数减: all checks passed")
