"""
sync_autowriter_decisions_to_prepublish.py
═══════════════════════════════════════════════════════════════════════════

把 autowriter.items 上的审稿决定（approved / needs_revision）反向同步
到 truth_vault.prepublish_evaluations。

⚠️ 2026-09-17 (外部评测 TV-01) 之前这里写的是"作为人类 evaluator 的判断日志",
   而实现把【所有】决策一律标成 evaluator_type='human'、evaluator_id=作者。
   现在按 AW 的 decision_source 分流: human / rule_based / unverified，
   evaluator_id 只填 reviewer 或规则名，绝不填作者。见 _provenance。

每晚自查 (2026-09-17 追加, 见 audit_archived_provenance):
    写入口修好只保证"以后不会再写错", 不保证"以后不会错"。TV-01 的本体是
    **写错了几个月没人发现** —— 598 条评价顶着人工身份躺着, 直到外部评测
    才被翻出来。所以每轮同步跑完会复核【已归档的行】, 判据只有一条:
    每条行都应等于 _provenance() 现在会给出的结果。
    发现"机器判定/来源不明顶着人工身份"或"evaluator_id 是作者"就返回非 0,
    夜跑的聚合失败闸会把整个 workflow 打红并给 owner 发邮件。

为什么需要这个:
    prepublish_evaluations 表 schema 已经存在（D-025），但目前没有任何
    sync 写入它，所以 v_evaluator_calibration view 永远空。把 autowriter
    侧的人工 approved / needs_revision 决定归档进来，至少能算出"运营批准
    了 N 个 items"这一基线统计，为以后接 LLM critic / model evaluator
    时的 "pred vs actual" 校准打地基。

限制 (诚实):
    - 我们只能拿到运营的 "pass / revise" 决定，拿不到他们的 "predict
      tier_class" 因为运营没在 UI 里给预测。所以 pred_tier_class = NULL。
    - actual_tier 也无法立刻填，要等到从 autowriter item 生成的内容**最终
      投放 + 被飞书 sync 回 TV** 才能反推。目前 TV 没有这条 autowriter_item
      → tv_note_id 的 lineage（飞书表里没有这一列），所以 actual_tier
      恒为 NULL，was_correct 一直是 NULL。
    - 总之: v_evaluator_calibration 在这个脚本跑完之后还是空，但 raw 数据
      已经在表里了, 哪天接通 lineage 就能反推过去.

幂等性:
    每个 (autowriter_item_id, evaluator_type) 元组只写一次 —— 2026-09-17 从
    写死的 'human' 改成"本轮会写的那个类型"(TV-01)。按写死的 'human' 去重会
    让已存在的 rule_based / unverified 行被当成"还没同步", 每晚重插一次。

    另有一条【就地收敛】路径: 已归档的行若与 _provenance() 现在的结果不一致
    —— 来源未知归成 unverified 之后 AW 补上了 decision_source、AW 改了口径
    (rule_based ↔ human)、换了 reviewer —— 就地 UPDATE 那一行, 不另插
    (另插会让同一条 item 在校准表里被数两次)。2026-09-17 之前只有
    "unverified → 确定类型"这一种会收敛, 其余漂移每晚被复核 WARN 一次却
    永远修不好、夜跑照样绿(codex review on #130)。

    2026-05-22 audit P1/P2-4 加强: schemas/notes_v1_2.sql 现在带 partial
    UNIQUE INDEX (autowriter_item_id, evaluator_type) WHERE evaluator_type
    ='human' AND autowriter_item_id IS NOT NULL. 应用层去重照旧 (避免读后
    才发现冲突的高耗 round-trip), 但即便两个 worker 同时跑, DB 层会拒第
    二个 INSERT 而不是写两行. 脚本现在会把 23505 转成 info 级 "race"
    日志, 不当 error 计.

迟到决策 (audit P1/P2-4 的已知局限, 2026-08-23 解除):
    旧版只能按 created_at 过滤 —— autowriter.items 当时没有 updated_at
    列, 于是"三个月前创建、今天才被人工改状态"的 item 会被时间窗直接筛
    掉, 而且是静默的. 当时的兜底是把 --since-days 默认从 90 抬到 365.

    aw 的 migrations/001_deskcore.sql 补上了 items.updated_at + 触发器
    (2026-08-23 已应用到生产; 触发器 WHEN 子句盯的正是 status 与
    example_label, 生产实测 status 变更确实会刷 updated_at). 时间窗改成:

        created_at >= since  OR  updated_at >= since

    是【或】, 不是【换成 updated_at】—— 两条分支都要:
      · updated_at 分支 = 真正想要的能力, 捞回迟到的人工决策;
      · created_at 分支 = 保底. updated_at 是 nullable 列 (DEFAULT now(),
        生产当前零 NULL), 万一哪天有人显式插了 NULL, 只写
        .gte("updated_at", ...) 会把那些行【静默丢掉】—— 又是一次"跑得
        好好的、其实一直在漏". 留着 created_at 分支, 新窗口就是旧窗口的
        严格超集, 这次改动不可能比改之前更差.

    默认仍是 365 天, 没跟着缩: 窗口的含义已经变成"最近 N 天被动过的决
    定", cron 若停摆超过 N 天, 停摆期间改的决定就再也捞不回来. 窗口宽
    一点是纯赚. 全扫仍然是 --since-days 0.

    ⚠️ 前置依赖与降级: updated_at 这一列【只有跑过 autowriter 仓的
    migrations/001_deskcore.sql 的库才有】—— 本仓自己那份建库脚本
    autowriter-migrations/007_fresh_install_autowriter_schema.sql 里的
    items 只有 created_at。目标库没有这列时, fetch_pending_decisions 会
    降级回旧口径(只按 created_at)并大声告警, 不会把整条链路打死;
    见那个函数的 docstring。

用法:
    python sync_autowriter_decisions_to_prepublish.py
    python sync_autowriter_decisions_to_prepublish.py --dry-run
    python sync_autowriter_decisions_to_prepublish.py --since-days 0   # 全扫

环境变量:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

from _common import fetch_all_pages, get_supabase_client, setup_logger, _iso_now


logger = setup_logger("sync_aw_decisions")


# autowriter.items.status → prepublish_evaluations.decision mapping.
# 'pending' is unmapped (no decision yet) so those items are skipped.
_STATUS_TO_DECISION = {
    "approved": "pass",
    "needs_revision": "revise",
}


# ── 决策来源 → evaluator 身份 (2026-09-17, 外部评测 TV-01) ──────────────────
# 旧实现把【所有】AW 决策一律写成 evaluator_type='human', evaluator_id=item.user_id
# (稿件作者)。AW 的 autowriter.items 其实早有 decision_source / reviewer_id /
# decided_at 三列, 一个都没读。
#
# 生产实况(2026-09-17 核): 598 条评价全是 human, 而对应 598 条 item 的
# decision_source 【全为 NULL】—— 所以"机器判定被洗成人工"目前还没真发生,
# 真实的坏是: 598 条来源其实未知, 却都署名人工、且署到了作者头上。
# AW 哪天开始写那一列, 旧实现会一声不响地继续洗。
#
# 口径:
#   · 'human' 这个身份【只发给能证明是人审的行】, 且 evaluator_id 必须是 reviewer;
#   · 机器判定 → rule_based, evaluator_id 记具体规则名(auto_dedup 等), 可分开统计;
#   · 来源缺失 / 不认识的新取值 → unverified。【不认识就不猜】, 宁可标"待核验"
#     也不默认成人工 —— 默认成人工正是本次要修的病。
_MACHINE_DECISION_SOURCES = frozenset({"auto_hard_rule", "auto_dedup", "system"})
_EVAL_TYPE_UNVERIFIED = "unverified"

# 本同步【只】拥有这三类 evaluator_type —— 也正是 v1.11 唯一索引覆盖的那三类
# (schemas/notes_v1_11_evaluator_provenance.sql)。两处必须是同一个集合:
#   · 判"这条 item 已归档了吗"只能看这三类;
#   · persona / critic / model 是别的链路写的, 与本同步正交, 看见它们【不能】
#     当成"已归档"而跳过 —— 那会把真正的审稿决策静默吞掉(codex review P1)。
_SYNC_EVALUATOR_TYPES = frozenset({"human", "rule_based", _EVAL_TYPE_UNVERIFIED})


def _provenance(item: dict) -> tuple[str, str | None]:
    """(evaluator_type, evaluator_id) —— 见上方口径。

    故意【不】接受 "看起来像人工" 的模糊输入: 只有 decision_source 恰好等于
    'human' 才给 human 身份, 其余一律不是。
    """
    src = item.get("decision_source")
    src = src.strip() if isinstance(src, str) else None
    if not src:
        return _EVAL_TYPE_UNVERIFIED, None
    if src == "human":
        reviewer = item.get("reviewer_id")
        reviewer = str(reviewer).strip() if reviewer else ""
        # 人工但拿不到 reviewer: 仍算人工(来源明确说了是人审), 但 evaluator_id 留空 ——
        # 填作者等于错认"他自己审了自己", 那是旧实现的错。
        return "human", (reviewer or None)
    if src in _MACHINE_DECISION_SOURCES:
        return "rule_based", src
    # 没见过的新取值: 不猜。标 unverified 并把原串留在 evaluator_id 里, 方便排查。
    return _EVAL_TYPE_UNVERIFIED, src


def _items_query(sb, since_iso: str | None, *, with_updated_at: bool,
                 with_provenance: bool = True):
    """建 autowriter.items 的查询. with_updated_at=False 是【降级形态】.

    时间窗 = created_at OR updated_at, 理由见模块 docstring「迟到决策」.
    【不能】只写 updated_at: 该列 nullable, 单条件会把 NULL 行静默丢掉;
    双条件让新窗口成为旧窗口的严格超集, 所以这次改动不可能造成回归.
    """
    cols = "id, status, user_id, created_at"
    if with_updated_at:
        cols += ", updated_at"
    if with_provenance:
        # TV-01: 这三列决定 evaluator 身份。拿不到就只能写 unverified。
        cols += ", decision_source, reviewer_id, decided_at"
    q = (
        sb.schema("autowriter")
        .table("items")
        .select(cols)
        .in_("status", list(_STATUS_TO_DECISION.keys()))
    )
    if not since_iso:
        return q
    if not with_updated_at:
        return q.gte("created_at", since_iso)
    # 值用双引号包住 —— 时间戳里若出现 , . : 不会被 PostgREST 当成逻辑树的
    # 语法分隔符. 这条语法在【生产 PostgREST 上实测过】: 解析与列解析都过了,
    # 只在权限阶段被 anon 拦下 (42501); 故意写坏括号则是 PGRST100 解析错、
    # 写不存在的列则是 42703 —— 三种错互相区分得开, 所以"过了解析"这个结论
    # 是站得住的. supabase-py 2.30 渲染成
    #   or=(created_at.gte."…",updated_at.gte."…")
    return q.or_(f'created_at.gte."{since_iso}",updated_at.gte."{since_iso}"')


def _looks_like_undefined_column(msg: str) -> bool:
    """这条(已小写的)报错是不是 42703 undefined_column?

    ⚠️ 判据里【不能】有光秃秃的 "column"(codex review P2): 那个词会把任何
    "提到了列名 + 带 column 字样"的错一起吞成"缺列"。本机 PG16 实测复现:
        column reference "decision_source" is ambiguous     ← 42702, 不是缺列
    它会被旧判据认成缺列 → 整条链路静默降级, 而真正的 bug 被吃掉。
    (顺带核过 codex 举的例子: PG16 的列级权限不足实际报的是
     `permission denied for table items`, 不带 column 字样 —— 例子不对,
     但它指出的"判据宽于 docstring 承诺"是真的, 上面那条就是证据。)

    PostgREST 对不存在的列返回 {"code":"42703","message":"column x does not
    exist"}, 两个特征都在, 所以去掉 "column" 不会漏判真正的缺列。
    """
    return "42703" in msg or "does not exist" in msg


def _is_missing_provenance(exc: Exception) -> bool:
    """这个异常是不是"autowriter.items 没有 decision_source/reviewer_id/decided_at"?

    与 _is_missing_updated_at 同款窄判据。降级后【写 unverified 而不是 human】——
    读不到来源时把行标成人工, 正是 TV-01 要修的病, 降级路径不能把它带回来。
    """
    msg = str(exc).lower()
    if not any(c in msg for c in ("decision_source", "reviewer_id", "decided_at")):
        return False
    return _looks_like_undefined_column(msg)


def _is_missing_updated_at(exc: Exception) -> bool:
    """这个异常是不是"autowriter.items 没有 updated_at 列"?

    只认这一种, 别的照旧抛 —— 降级路径必须窄, 否则就变成"出错了也当成功",
    正是本仓一路在治的病。
    """
    msg = str(exc).lower()
    if "updated_at" not in msg:
        return False
    return _looks_like_undefined_column(msg)


def _fetch_items(sb, since_iso: str | None, *, prov: bool) -> list[dict]:
    """取时间窗内的 autowriter.items; 目标库没有 updated_at 列时降级回只按 created_at 并告警。

    同步主流程和归档复核【共用】这一份降级逻辑 —— 复核第一版自己写了一遍"带
    updated_at 取一次、失败就算了", 在 README 那份 fresh-install 建库脚本装出来的库
    (items 没有 updated_at)上每晚报"复核干净", 其实一行没查(codex review on #130)。
    降级判据窄到只认"缺 updated_at 列"这一种错, 其余照旧抛。
    """
    try:
        return fetch_all_pages(
            _items_query(sb, since_iso, with_updated_at=True, with_provenance=prov),
            order_by="id")
    except Exception as exc:
        if not _is_missing_updated_at(exc):
            raise
        logger.warning(
            "autowriter.items 没有 updated_at 列 —— 时间窗降级回【只按 "
            "created_at】, 迟到的人工决策会重新开始漏收。"
            "补法: 在目标库上跑 autowriter 仓的 migrations/001_deskcore.sql。"
            "原始错误: %s", str(exc)[:200],
        )
        return fetch_all_pages(
            _items_query(sb, since_iso, with_updated_at=False, with_provenance=prov),
            order_by="id")


def fetch_pending_decisions(sb, since_iso: str | None) -> list[dict]:
    """Find autowriter items with a status that maps to a decision whose
    prepublish_evaluations row is missing, or no longer equals _provenance()
    (那种带 _upgrade_evaluation_id, 由 insert_evaluation 就地收敛)。

    Returns list of dicts with: id (item_id), status, user_id, created_at,
    以及 updated_at —— **除非**该列不存在(降级路径, 见下), 那时没有这个键。

    ⚠️ **前置依赖**: `updated_at` 是 autowriter 仓
    `migrations/001_deskcore.sql` 加的, 不在 truth-vault 自己那份
    `autowriter-migrations/007_fresh_install_autowriter_schema.sql` 里
    (那份的 items 只有 created_at)。也就是说【只按 TV 这边的建库脚本装起来
    的库没有这一列】。PostgREST 对不存在的列返回 400/42703, 会把整个
    select 打掉。

    所以这里对【且仅对】"没有 updated_at 列"这一种错误降级回旧口径
    (只按 created_at), 并大声告警。理由:
      · 不降级 = 这条归档链路在那种库上直接死掉。它不会静默 ——
        daily-sync 的 `prepublish_sync` 在聚合失败闸里(daily-sync.yml:402),
        整个 workflow 会红并给 owner 发邮件 —— 但"红着不动"不如"降级跑着
        并且喊出来"。
      · 降级到旧口径 = 恰好是本次改动之前的行为, 不会比以前更差。
      · 判据窄到只认这一种异常, 其余照旧抛。
    """
    # 两级降级, 各自判据都窄: 先试"带来源三列", 再试"带 updated_at", 最后旧口径。
    # updated_at 那一级住在 _fetch_items 里, 与归档复核共用同一份。
    try:
        rows = _fetch_items(sb, since_iso, prov=True)
    except Exception as exc:
        if not _is_missing_provenance(exc):
            raise
        # ⚠️ 降级【不是】退回旧行为。旧行为是"读不到来源就当人工", 那正是 TV-01。
        # 这里退回的是"读不到来源就全标 unverified" —— 少了分辨力, 但不会造假身份。
        logger.warning(
            "autowriter.items 缺 decision_source/reviewer_id/decided_at —— "
            "本轮【全部】按 evaluator_type=unverified 归档(不会标成人工)。"
            "补法: 在目标库上跑 autowriter 仓的 deskcore 迁移。原始错误: %s",
            str(exc)[:200],
        )
        rows = _fetch_items(sb, since_iso, prov=False)

    if not rows:
        return []
    # 去重按 (item_id, 我们这次会写的 evaluator_type) —— 不能再按写死的 'human' 筛:
    # 那样一条已存在的 rule_based 行会被当成"还没同步", 每晚重插一次。
    item_ids = [r["id"] for r in rows]
    existing = fetch_all_pages(
        sb.schema("truth_vault")
        .table("prepublish_evaluations")
        # evaluation_id 只为分页排序用(同一 item 可能有多条不同类型的评价)。
        .select("evaluation_id, autowriter_item_id, evaluator_type, evaluator_id")
        # ⚠️ 必须按类型过滤(codex review P1)。改成"取全部类型"那一版有个回归:
        #   一条 item 若已有 persona/critic/model 评价(别的链路写的, 与本同步正交),
        #   下面的 `elif have: continue` 会把它当成"已归档"而永久跳过, 真正的
        #   审稿决策再也进不了校准表。改之前的旧查询 .eq(evaluator_type,'human')
        #   恰好不受影响 —— 是这次放宽类型时引入的, 不是历史问题。
        .in_("evaluator_type", sorted(_SYNC_EVALUATOR_TYPES))
        .in_("autowriter_item_id", item_ids),
        order_by="evaluation_id",
    )
    by_item: dict[str, dict[str, dict]] = {}
    for r in existing:
        by_item.setdefault(r["autowriter_item_id"], {})[r["evaluator_type"]] = r

    out: list[dict] = []
    for r in rows:
        want_type, want_id = _provenance(r)
        have = by_item.get(r["id"], {})
        if not have:
            out.append(r)                 # 还没归档 → 插入
            continue
        # 已有【本同步写的】行 → 挑一条来收敛。have 已在查询处按 _SYNC_EVALUATOR_TYPES
        # 过滤, 所以 persona/critic/model 之类别家的评价不会走到这里把决策吞掉。
        # 挑法: 优先同类型的行(通常已一致, 或只是换了 reviewer / 规则名), 其次此前来源
        # 未知的 unverified(经典的"AW 补上来源"升级), 再其次别的类型(AW 改了口径:
        # rule_based ↔ human)。只挑一条: 唯一索引是 (item, type), 改到目标类型时那个
        # 类型在 have 里必然还没有行, 不会撞。
        # ⚠️ 2026-09-17 之前这里对"同类型已有"和"已有别的确定类型"一律 continue, 于是
        #   只有 unverified → 确定类型 会收敛; AW 把 auto_dedup 改口成 human、换 reviewer、
        #   改规则名的行永远跳过, 复核每晚 WARN 一次却修不好(codex review on #130 P2)。
        cur = (have.get(want_type)
               or have.get(_EVAL_TYPE_UNVERIFIED)
               or next(iter(have.values())))
        if (cur["evaluator_type"], cur["evaluator_id"]) == (want_type, want_id):
            continue                      # 已与 _provenance() 一致 → 幂等跳过
        out.append({**r, "_upgrade_evaluation_id": cur["evaluation_id"],
                    "_upgrade_from": (cur["evaluator_type"], cur["evaluator_id"])})
    return out


def audit_archived_provenance(sb, since_iso: str | None) -> tuple[int, int]:
    """复核【已经归档的行】还对不对得上 AW 现在的来源。返回 (fail_n, warn_n)。

    ⚠️ 为什么需要这个: TV-01 的本体不是"某次写错了", 而是**写错了没人发现** ——
    598 条评价顶着人工身份躺了几个月, 直到外部评测才被翻出来。修好写入口只保证
    以后不再写错, 不保证以后没人手改、没有别的路径绕进来、AW 不会改口径。
    所以要有一条每晚自己会红的守卫。

    不变量只有一条, 也只能有一条:
        每条已归档的行, 都应等于 _provenance() 现在会给出的结果。
    刻意【不】重写一遍判据(比如手写"human 必须带 evaluator_id"那种行内规则):
      · 行内规则抓不到真正的 TV-01 —— `decision_source='auto_dedup'` 却被写成
        human 的行, 带着 evaluator_id='auto_dedup', 行内规则照样放过;
      · 行内规则会误伤合法路径 —— _provenance() 对"AW 说是人审但没记 reviewer"
        【故意】返回 ("human", None), 那不是回归;
      · 而且判据写两份迟早分叉, 这正是 D-061 里回填与 _provenance 打架的老毛病。
    对着函数本身比, 上面三件事一次解决。

    分两级, 因为"对不上"有几种完全不同的成因:

    FAIL(要红):
      ① 行说自己是 human, 但 _provenance() 现在不这么认为
         —— 机器判定/来源不明顶着人工身份, 就是 TV-01 本体。本脚本写不出这种行。
      ② evaluator_id 等于稿件作者 (item.user_id), 而 AW 上游【没有】这么说
         —— 旧实现的原始指纹: 本脚本不会替 AW 把作者填成 reviewer。
         ⚠️ 这条判在"相等即通过"之前: AW 上游若把 reviewer_id 填成了作者本人,
         _provenance() 会原样返回作者, 归档行与它相等, 光靠相等短路会把这一行
         悄悄放过(codex review on #130)。那种情形归 ④, 不是造假。
      ③ 同一条 item 有多条本同步写的行 —— 校准表数两次; 同步只会收敛其中一条,
         另一条永远修不好。这是唯一一种"下一轮不会自愈"的漂移, 所以要红。

    WARN(不红):
      ④ AW 上游自己把作者填成了 reviewer(自己审自己) —— 归档如实照录, 不是同步
         造假, 也不是 TV-01; 但校准时要打折, 所以要看得见。第一次真人自审不能
         变成半夜事故。
      ⑤ 其余不一致 —— 行还是 unverified 而 AW 后来补了来源、AW 改了口径、换了
         reviewer。fetch_pending_decisions 的就地收敛路径下一轮会修好(2026-09-17
         起收敛所有类型, 不只 unverified), 不该半夜把 owner 叫起来。

    ⚠️ 覆盖范围 = 和同步同一个时间窗(默认 365 天)。窗口外的老行不在复核范围里;
    要全量复核就 --since-days 0。这是取舍: 复用同步那两个查询的分页形态, 不另造
    一套全表扫描(那会碰到 in_() 的 URL 长度上限, 得另加分批逻辑)。

    降级与失败: 目标库没有 items.updated_at 时和主流程一样降级到只按 created_at,
    照常复核; 缺 decision_source 三列时没有可比的口径, 跳过并告警(主流程已全按
    unverified 归档); 其余错误照抛 —— 吞成 (0, 0) 就是"没查却报干净"。
    """
    try:
        rows = _fetch_items(sb, since_iso, prov=True)
    except Exception as exc:
        if not _is_missing_provenance(exc):
            raise
        logger.warning(
            "归档复核跳过: AW 缺 decision_source/reviewer_id/decided_at, 没有可比的口径"
            "(同步主流程已就此告警并全按 unverified 归档): %s", str(exc)[:200])
        return 0, 0
    if not rows:
        return 0, 0

    by_id = {r["id"]: r for r in rows}
    existing = fetch_all_pages(
        sb.schema("truth_vault")
        .table("prepublish_evaluations")
        .select("evaluation_id, autowriter_item_id, evaluator_type, evaluator_id")
        .in_("evaluator_type", sorted(_SYNC_EVALUATOR_TYPES))
        .in_("autowriter_item_id", list(by_id)),
        order_by="evaluation_id",
    )

    fails: list[str] = []
    warns: list[str] = []
    per_item: dict[str, list[dict]] = {}
    for ev in existing:
        if ev["autowriter_item_id"] in by_id:
            per_item.setdefault(ev["autowriter_item_id"], []).append(ev)

    for item_id, evs in per_item.items():
        item = by_id[item_id]
        if len(evs) > 1:
            fails.append(
                f"item={item_id} 有 {len(evs)} 条本同步写的评价行"
                f"({', '.join(str(e['evaluator_type']) for e in evs)}) —— 校准表数两次, "
                f"同步收敛不了, 要人工删到一条")
            continue
        ev = evs[0]
        want_type, want_id = _provenance(item)
        got_type, got_id = ev["evaluator_type"], ev["evaluator_id"]
        author = item.get("user_id")
        tag = f"eval={ev['evaluation_id']} item={item_id}"
        if author is not None and got_id is not None and str(got_id) == str(author):
            if (got_type, got_id) == (want_type, want_id):
                warns.append(f"{tag} AW 上游 reviewer_id 就是稿件作者(自己审自己) —— "
                             f"如实照录, 校准时要打折")
            else:
                fails.append(f"{tag} evaluator_id 是稿件作者, 而 AW 没这么说 —— 作者不是审稿人")
            continue
        if (got_type, got_id) == (want_type, want_id):
            continue
        if got_type == "human" and want_type != "human":
            fails.append(
                f"{tag} 归档成 human, 但 decision_source={item.get('decision_source')!r} "
                f"应判 {want_type}")
        else:
            warns.append(f"{tag} {got_type}/{got_id} → 应为 {want_type}/{want_id}, "
                         f"下一轮同步就地收敛")

    for line in warns[:10]:
        logger.warning("归档复核 · WARN: %s", line)
    if warns:
        logger.warning(
            "归档复核: %d 行要看一眼(与 AW 现状不一致的, 下一轮同步会就地收敛; "
            "上游自审的只是提醒)。想立刻纠正不一致就重跑 "
            "schemas/notes_v1_11_evaluator_provenance.sql(幂等且自愈)。", len(warns))
    for line in fails[:10]:
        logger.error("归档复核 · 【FAIL】: %s", line)
    if fails:
        logger.error(
            "归档复核: %d 项站不住(身份造假 TV-01 类 / 同一 item 多条同步行)。本脚本写不出"
            "这种行 —— 查是不是有旧版本在跑、有人手改过表, 或 AW 改了 decision_source 口径。"
            "身份造假的修法: 重跑 schemas/notes_v1_11_evaluator_provenance.sql; "
            "多条同步行要人工删到一条。", len(fails))
    return len(fails), len(warns)


def _is_duplicate_error(exc: Exception) -> bool:
    """Detect SQLSTATE 23505 (unique_violation) from supabase-py errors."""
    code = getattr(exc, "code", None) or getattr(exc, "pgcode", None)
    if code == "23505":
        return True
    msg = str(exc)
    return "23505" in msg or "duplicate key value violates" in msg


def insert_evaluation(sb, item: dict, dry_run: bool = False) -> bool:
    """Insert one prepublish_evaluations row.

    Returns True if the row was inserted, False if it was already present
    (race recovery via 23505). The application-level NOT EXISTS pre-filter
    catches most repeats, but two concurrent runs of this script (e.g., a
    manual run overlapping with cron) can both pass the pre-filter and
    both attempt the INSERT. With the new partial UNIQUE index
    (schemas/notes_v1_2.sql: idx_tv_evals_aw_item_evaluator_uniq), the
    loser gets 23505; we treat that as success-by-other-worker, not error.
    """
    decision = _STATUS_TO_DECISION[item["status"]]
    evaluator_type, evaluator_id = _provenance(item)
    row = {
        "autowriter_item_id": item["id"],
        "evaluator_type": evaluator_type,
        # ⚠️ 绝不再退回 item["user_id"](作者)。作者不是审稿人 —— 见 _provenance。
        "evaluator_id": evaluator_id,
        "decision": decision,
        # score_json / reasoning / pred_tier_class / actual_tier all NULL —
        # see module docstring "限制" for the lineage gap that prevents
        # filling these.
        # 决策时间优先用 AW 的 decided_at(真正做决定的时刻), 缺了才退回"同步时刻"。
        "created_at": item.get("decided_at") or _iso_now(),
    }
    upgrade_id = item.get("_upgrade_evaluation_id")
    if dry_run:
        logger.info("[dry-run] would %s evaluation %s",
                    "converge" if upgrade_id else "insert", row)
        return True
    if upgrade_id:
        # 就地收敛此前的行(unverified 补上来源 / AW 改口径 / 换 reviewer), 不另插。
        # ⚠️ 收敛要把【整行】对齐到 item 现在的状态, 不能只换身份(codex review P2):
        #   · decision —— 两次同步之间 status 可能从 approved 变成 needs_revision,
        #     只改身份会让校准表里留着旧判决, 而且比"没这行"更糟(看着像已核对过);
        #   · created_at —— 旧行是"来源未知"时写的, 那时只能退回同步时刻; 现在
        #     decided_at 到手了, 正该把它纠正成真正的决策时刻。decided_at 仍缺时
        #     row["created_at"] 会是本次的 _iso_now(), 那比旧同步时刻更不准,
        #     所以【只在拿得到 decided_at 时】才改这一列。
        patch = {"evaluator_type": row["evaluator_type"],
                 "evaluator_id": row["evaluator_id"],
                 "decision": row["decision"]}
        if item.get("decided_at"):
            patch["created_at"] = row["created_at"]
        (
            sb.schema("truth_vault")
            .table("prepublish_evaluations")
            .update(patch)
            .eq("evaluation_id", upgrade_id)
            .execute()
        )
        frm = item.get("_upgrade_from") or ("?", "?")
        logger.info("converged evaluation %s: %s/%s → %s/%s (decision=%s)",
                    upgrade_id, frm[0], frm[1], row["evaluator_type"],
                    row["evaluator_id"], row["decision"])
        return True
    try:
        (
            sb.schema("truth_vault")
            .table("prepublish_evaluations")
            .insert(row)
            .execute()
        )
        return True
    except Exception as exc:
        if _is_duplicate_error(exc):
            logger.info(
                "race: prepublish_evaluations row for item %s already exists "
                "(probably another worker wrote it between our SELECT and INSERT). "
                "Treating as success.",
                item["id"],
            )
            return False
        raise


def _touched_after_create(row: dict) -> bool:
    """这条 item 是不是"创建之后又被动过"的.

    ⚠️ **不等于"迟到的审稿决定"**(codex review)。触发器的 WHEN 是
        old.status IS DISTINCT FROM new.status
     OR old.example_label IS DISTINCT FROM new.example_label
    —— 所以【只改了正负例标注、审稿状态一个字没动】也会刷 updated_at。
    库里没有 status 专属的时间戳, 拿不到更细的口径, 所以这个数只能诚实地
    叫"创建后被动过", 不能拿它当"捞回了多少条迟到决策"的证据。

    刻意【不】拿 ISO 字符串比大小: 两列都是 timestamptz, Postgres 只在小数
    秒非零时才渲染小数部分, 于是同一时刻可能一列是 "…:00+00:00"、另一列是
    "…:00.000000+00:00" —— 字典序下 '+'(0x2B) < '.'(0x2E), 会把"其实相等"
    判成"晚于", 这个计数就开始虚报. 解析不了就返回 False (宁可少报也不虚
    报: 这是个用来看修复有没有起作用的数, 虚报比漏报更坏).
    """
    created, updated = row.get("created_at"), row.get("updated_at")
    if not created or not updated:
        return False
    try:
        return datetime.fromisoformat(updated) > datetime.fromisoformat(created)
    except (TypeError, ValueError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--since-days", type=int, default=365,
        help="Only sync items created OR last touched within the last N days "
             "(default 365). autowriter.items 现在有 updated_at 了, 所以"
             "'很久以前创建、最近才改状态'的 item 也在窗口里 —— 窗口的含义"
             "是'最近 N 天被动过的决定'. 默认没跟着缩回 90: cron 停摆超过 N "
             "天, 停摆期间改的决定就捞不回来了. Set 0 to scan everything. "
             "目标库没有 items.updated_at 时会降级回只按 created_at 并告警.",
    )
    args = parser.parse_args()

    since_iso = None
    if args.since_days > 0:
        since_iso = (
            datetime.now(timezone.utc) - timedelta(days=args.since_days)
        ).replace(tzinfo=None).isoformat(timespec="seconds")

    sb = get_supabase_client()
    pending = fetch_pending_decisions(sb, since_iso)
    # 时间窗降级了没? 降级形态的行里根本没有 updated_at 这个键。
    degraded = bool(pending) and "updated_at" not in pending[0]
    # 数一下"创建后被动过"的。旧口径(只按 created_at)在窗口边缘会漏掉的就在
    # 这一批里。把它打出来, 这条修复才是【看得见】的 —— 否则又变成"改了,
    # 但没人知道有没有起作用"(同 check_positive_saturation.py 当年那个盲点)。
    # ⚠️ 它【不是】"迟到决策"的精确计数, 原因见 _touched_after_create。
    touched = sum(1 for r in pending if _touched_after_create(r))
    if degraded:
        logger.info(
            "Found %d autowriter items with new human decisions to archive "
            "(⚠️ 时间窗已降级为只按 created_at —— 目标库没有 items.updated_at, "
            "迟到的人工决策会漏收)", len(pending))
    else:
        logger.info(
            "Found %d autowriter items with new human decisions to archive "
            "(其中 %d 条在创建后被动过 —— 含只改了正负例标注的, 不等于"
            "「捞回了这么多条迟到决策」)", len(pending), touched)

    stats = {"pass": 0, "revise": 0, "race_skipped": 0, "errors": 0}
    for item in pending:
        try:
            inserted = insert_evaluation(sb, item, dry_run=args.dry_run)
            if inserted:
                stats[_STATUS_TO_DECISION[item["status"]]] += 1
            else:
                # 23505 race recovery — another worker wrote it. Not an error,
                # but track separately so ops can spot abnormal contention.
                stats["race_skipped"] += 1
        except Exception as exc:
            logger.exception("item_id=%s failed: %s", item["id"], exc)
            stats["errors"] += 1

    # 写完再复核一遍已归档的行 —— 见 audit_archived_provenance 的 docstring。
    # dry-run 也跑: 它读的是库里【已经存在】的行, 跟本轮写不写无关。
    audit_fail, audit_warn = 0, 0
    try:
        audit_fail, audit_warn = audit_archived_provenance(sb, since_iso)
    except Exception:
        # 复核本身挂了不该把同步判成失败(同步已经成功了), 但必须喊出来。
        logger.exception("归档复核执行失败 —— 本轮同步结果不受影响, 但复核没跑成")
    stats["audit_fail"] = audit_fail    # 身份造假 / 同一 item 多条同步行 → 红
    stats["audit_warn"] = audit_warn    # 下一轮会收敛的漂移 / 上游自审 → 只提醒

    logger.info("Done: %s", json.dumps(stats, ensure_ascii=False))
    return 0 if stats["errors"] == 0 and audit_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
