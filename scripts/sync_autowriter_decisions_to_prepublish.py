"""
sync_autowriter_decisions_to_prepublish.py
═══════════════════════════════════════════════════════════════════════════

把 autowriter.items 上的运营审稿决定（approved / needs_revision）反向同步
到 truth_vault.prepublish_evaluations，作为人类 evaluator 的判断日志。

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
    每个 (autowriter_item_id, evaluator_type='human') 元组只写一次。重跑
    会跳过已经有 prepublish_evaluations 行的 items。

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


def _items_query(sb, since_iso: str | None, *, with_updated_at: bool):
    """建 autowriter.items 的查询. with_updated_at=False 是【降级形态】.

    时间窗 = created_at OR updated_at, 理由见模块 docstring「迟到决策」.
    【不能】只写 updated_at: 该列 nullable, 单条件会把 NULL 行静默丢掉;
    双条件让新窗口成为旧窗口的严格超集, 所以这次改动不可能造成回归.
    """
    cols = "id, status, user_id, created_at"
    if with_updated_at:
        cols += ", updated_at"
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


def _is_missing_updated_at(exc: Exception) -> bool:
    """这个异常是不是"autowriter.items 没有 updated_at 列"?

    只认这一种, 别的照旧抛 —— 降级路径必须窄, 否则就变成"出错了也当成功",
    正是本仓一路在治的病。
    """
    msg = str(exc).lower()
    if "updated_at" not in msg:
        return False
    return any(k in msg for k in ("42703", "does not exist", "column"))


def fetch_pending_decisions(sb, since_iso: str | None) -> list[dict]:
    """Find autowriter items with a status that maps to a decision, that
    don't yet have a 'human' prepublish_evaluations row.

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
    try:
        rows = fetch_all_pages(
            _items_query(sb, since_iso, with_updated_at=True), order_by="id")
    except Exception as exc:
        if not _is_missing_updated_at(exc):
            raise
        logger.warning(
            "autowriter.items 没有 updated_at 列 —— 时间窗降级回【只按 "
            "created_at】, 迟到的人工决策会重新开始漏收。"
            "补法: 在目标库上跑 autowriter 仓的 migrations/001_deskcore.sql。"
            "原始错误: %s", str(exc)[:200],
        )
        rows = fetch_all_pages(
            _items_query(sb, since_iso, with_updated_at=False), order_by="id")

    # Exclude items that already have a 'human' eval row.
    if not rows:
        return []
    item_ids = [r["id"] for r in rows]
    existing = fetch_all_pages(
        sb.schema("truth_vault")
        .table("prepublish_evaluations")
        # evaluation_id 只为分页排序用(同一 item 可能有多条 human 评价)。
        .select("evaluation_id, autowriter_item_id")
        .eq("evaluator_type", "human")
        .in_("autowriter_item_id", item_ids),
        order_by="evaluation_id",
    )
    existing_ids = {r["autowriter_item_id"] for r in existing}
    return [r for r in rows if r["id"] not in existing_ids]


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
    row = {
        "autowriter_item_id": item["id"],
        "evaluator_type": "human",
        "evaluator_id": str(item.get("user_id") or ""),
        "decision": decision,
        # score_json / reasoning / pred_tier_class / actual_tier all NULL —
        # see module docstring "限制" for the lineage gap that prevents
        # filling these.
        "created_at": _iso_now(),
    }
    if dry_run:
        logger.info("[dry-run] would insert evaluation %s", row)
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

    logger.info("Done: %s", json.dumps(stats, ensure_ascii=False))
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
