"""l2_outcome.py —— 学习结果口径的开关 (W-64 下一步 ①)。gate2_run / gate3_score / discover_feature_candidates 共用。

    hit   (默认) truth_vault.v_l2_labels.y —— 今天的口径: 清洗后的 爆 / 大爆 对 趴。本质是一条评论数线, 含我方铺的评论。
    reads (影子) truth_vault.v_l2_outcomes.y_reads_median —— 阅读过本项目中位数 (notes_v1_35)。不含我方评论;
          只有小红书、有阅读、发布满 14 天、本项目这样的帖 ≥ 30 篇的才有值, 没值的行不取。

默认永远是 hit, 而且 hit 那条查询和改之前一模一样 (表名、select 串都不变; check_l2_outcome_switch 钉着)。
reads 只给并排读数: 三个脚本在 reads 下都不写库, 报告里两种口径一起给。把 reads 换成默认是 owner 的决定, 不在这里。
reads 读不到视图 (owner 还没跑 notes_v1_35) → OutcomeUnavailable, 话里直接说要跑哪个文件; 三个脚本都退出 2。
"""
from __future__ import annotations

OUTCOMES = ("hit", "reads")
DEFAULT_OUTCOME = "hit"
HIT_VIEW = "v_l2_labels"
READS_VIEW, READS_COL = "v_l2_outcomes", "y_reads_median"
READS_MIGRATION = "schemas/notes_v1_35_l2_outcomes.sql"
LABEL = {"hit": "爆 (清洗后的 爆 / 大爆 对 趴, v_l2_labels.y; 含我方铺评)",
         "reads": "阅读过本项目中位数 (v_l2_outcomes.y_reads_median, W-64 ①; 不含我方评论; 影子读数, 只报不判)"}


class OutcomeUnavailable(RuntimeError):
    """reads 口径读不到 v_l2_outcomes (多半是 owner 还没跑 READS_MIGRATION)。"""


def fetch_labels(fetch_all_pages, query, outcome: str, order_by: str = "note_id") -> list[dict]:
    """取标签行。hit: 就是 fetch_all_pages(query, order_by=...), 什么都不加 (出错原样抛)。
    reads: 读不到视图 → OutcomeUnavailable, 话里带要跑的迁移文件, 不只甩一串 PostgREST 原错误。"""
    if outcome == DEFAULT_OUTCOME:
        return fetch_all_pages(query, order_by=order_by)
    try:
        return fetch_all_pages(query, order_by=order_by)
    except Exception as exc:  # noqa: BLE001 —— PostgREST / 网络的错误种类很多, 这里只换一句能照着做的话
        raise OutcomeUnavailable(
            f"--outcome {outcome}: 读不到 truth_vault.{READS_VIEW}。多半是 owner 还没跑 {READS_MIGRATION} (只建视图, ¥0), "
            f"跑完再试。原错误: {type(exc).__name__}: {str(exc)[:200]}") from exc


def label_query(sb, cols: str, outcome: str = DEFAULT_OUTCOME):
    """标签行的 PostgREST 查询 (调用方再加 gte 之类的过滤、交给 fetch_all_pages)。cols 里写 y, 两种口径回来的行都叫 y。

    hit   → sb.schema("truth_vault").table("v_l2_labels").select(cols), 和以前逐字一样。
    reads → v_l2_outcomes, y 换成别名 y:y_reads_median, 只取 y_reads_median 不为空的行。"""
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome={outcome!r} 不在 {OUTCOMES}")
    if outcome == "hit":
        return sb.schema("truth_vault").table(HIT_VIEW).select(cols)
    parts = [c.strip() for c in cols.split(",")]
    if "y" not in parts:
        raise ValueError("cols 里要有 y")
    sel = ", ".join(f"y:{READS_COL}" if c == "y" else c for c in parts)
    return sb.schema("truth_vault").table(READS_VIEW).select(sel).not_.is_(READS_COL, None)
