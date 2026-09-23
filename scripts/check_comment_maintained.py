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
# ⑫c 途鸽把投流记在 tier 源里(「关注后续流量」9 行, 7 行已进书架)
n12c, _, _ = s.transform_row(BASE, "r12c", {"文案": "c", "状态": "关注后续流量 爆贴"})
assert f(n12c).get("paid_promoted") is True, f"tier 源里的投流标记漏判: {f(n12c)}"
# ⑫d 有这一列但没投流取值 → false(运营 2026-09-22:「维护情况」留空=没做维护)
n12d, _, _ = s.transform_row(M11, "r12d", {"文案": "c", "状态": "爆贴", "维护情况": ["关注"]})
assert f(n12d).get("paid_promoted") is False, f"有列无投流值该判 false: {f(n12d)}"
# ⑫e 【没有】这一列 → 缺键, 不是 false。写 false = 拿"这张表没这列"冒充"没投流"。
n12e, _, _ = s.transform_row(BASE, "r12e", {"文案": "c", "状态": "爆贴"})
assert "paid_promoted" not in f(n12e), f"没有这一列时必须缺键: {f(n12e)}"
# ⑫f 只看 _PAID_COLS 这两列, 不许扫整个 raw_extra —— 生产里别的列也带 🍟:
#    RIO 有个账号昵称叫「🍟的快乐小记」, ANSHEN 有两条评论区快照带 🍟。
#    夹具用一个【已声明进 raw_extra 且不在 _PAID_COLS 里】的列, 才够得着这个场景
#    (账号名走 _account_name 中间量, 判据跑完之后才倒进 raw_extra, 测不到)。
M12f = dict(BASE, project_specific_fields_to_raw_extra=[
    *BASE["project_specific_fields_to_raw_extra"], "评论区快照"])
n12f, _, _ = s.transform_row(M12f, "r12f",
    {"文案": "c", "状态": "爆贴", "评论区快照": "楼主是🍟的快乐小记 求链接"})
assert "paid_promoted" not in f(n12f), \
    f"别的列里的 🍟 不是投流标记, 判据不许扫整个 raw_extra: {f(n12f)}"

print("comment_maintained 分来路 × synthetic 正交 × 维护情况取值 × 投流三态: all checks passed")
