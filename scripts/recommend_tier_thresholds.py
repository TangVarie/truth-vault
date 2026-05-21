"""
recommend_tier_thresholds.py
═══════════════════════════════════════════════════════════════════════════

只读分析工具。每月 / 季度跑一次，按近 N 天 interactions 分布算出 P75/P90，
对比 mappings/<project>.yaml 里硬编码的 tier_thresholds，**输出建议供人决策，
不自动改 yaml**。

用法:
    python recommend_tier_thresholds.py                       # 全部项目
    python recommend_tier_thresholds.py --project NUC_phase1  # 单项目
    python recommend_tier_thresholds.py --window-days 30      # 近 30 天分布

为什么不自动改 yaml: 阈值调整是产品/运营决策，不是算法决策。脚本只 surface
"现在 yaml 里的阈值和最近实际分布偏离多少"，由 Ziao 决定是否真要 bump。

触发条件（来自 CURRENT_STATE.md 延后清单 🟡 慢性病）: 第一次有项目出现
"按现在阈值没爆款 / 爆款太多" 明显跑偏。这个脚本的目的是让你**早 1-2 个月**
看见跑偏的迹象，而不是等到完全错了才修。

环境变量:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from _common import fetch_all_pages, get_supabase_client, load_mapping, setup_logger


logger = setup_logger("recommend_tier_thresholds")


_MAPPINGS_DIR = Path(__file__).resolve().parent.parent / "mappings"


def _pct(values: list[float], percentile: float) -> float | None:
    """简单 percentile (无 numpy 依赖). values must be pre-sorted."""
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    k = (len(values) - 1) * percentile / 100.0
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[f]
    return values[f] + (values[c] - values[f]) * (k - f)


def analyze_project(sb, project_id: str, window_days: int) -> dict | None:
    """Per-project distribution analysis. Returns None if yaml missing or
    if there's no data in the window."""
    try:
        mapping = load_mapping(project_id)
    except FileNotFoundError:
        return None

    current = mapping.get("tier_thresholds") or {}
    if not current:
        return None  # No declared thresholds — can't recommend deltas

    # Pull interactions for the recency window.
    from datetime import datetime, timedelta, timezone
    cutoff_iso = (
        datetime.now(timezone.utc) - timedelta(days=window_days)
    ).replace(tzinfo=None).isoformat(timespec="seconds")

    rows = fetch_all_pages(
        sb.schema("truth_vault").table("notes")
        .select("note_id, interactions, tier, tier_source, publish_time")
        .eq("project_id", project_id)
        .not_.is_("interactions", None)
        .gte("publish_time", cutoff_iso)
    )

    interactions = sorted(
        float(r["interactions"]) for r in rows
        if isinstance(r.get("interactions"), (int, float))
    )
    if not interactions:
        return None

    p50 = _pct(interactions, 50)
    p75 = _pct(interactions, 75)
    p90 = _pct(interactions, 90)
    p95 = _pct(interactions, 95)

    suggested = {
        # 爆 ≈ P75 (上四分位 / 中上水平)
        "爆":   int(round(p75)) if p75 else None,
        # 大爆 ≈ P90 (top decile)
        "大爆": int(round(p90)) if p90 else None,
    }

    # Drift: 当前阈值距离建议阈值的相对偏离 (用于人眼判断要不要改)
    drift: dict[str, float | None] = {}
    for k in ("爆", "大爆"):
        cur = current.get(k)
        sug = suggested.get(k)
        if cur and sug:
            drift[k] = (sug - cur) / cur
        else:
            drift[k] = None

    # tier 分布也算一下 (实际命中数 vs 总数)
    tier_counts: dict[str, int] = {}
    for r in rows:
        t = r.get("tier")
        if t:
            tier_counts[t] = tier_counts.get(t, 0) + 1

    return {
        "project_id": project_id,
        "n_rows": len(interactions),
        "window_days": window_days,
        "p50": p50, "p75": p75, "p90": p90, "p95": p95,
        "current": current,
        "suggested": suggested,
        "drift": drift,
        "tier_counts": tier_counts,
    }


def format_markdown(reports: list[dict]) -> str:
    """Render reports as a markdown doc the operator can paste / commit."""
    out = ["# Tier 阈值建议 (read-only)\n"]
    out.append(
        f"按近 {reports[0]['window_days']} 天 interactions 分布算出 P75/P90, "
        "对比 mapping yaml 里硬编码的 tier_thresholds. 不自动改 yaml.\n\n"
        "**判断要不要 bump 的经验法则**:\n"
        "- drift 绝对值 < 20%: 阈值仍合理, 不动\n"
        "- drift 20-50%: 留意, 看下一次 review 是否仍然偏离\n"
        "- drift > 50%: 大概率要调; 看 tier_counts 是否也明显异常 "
        "(例: 当前 yaml 阈值下'爆'占比 < 5% 或 > 30%, 都是分布偏移信号)\n\n"
    )
    out.append("| 项目 | N | P75 (建议爆) | P90 (建议大爆) | 当前 yaml 爆 / 大爆 | drift | 实际 tier 分布 |\n")
    out.append("|---|---|---|---|---|---|---|\n")
    for r in reports:
        drift_pct = ", ".join(
            f"{k}: {d*100:+.0f}%" if d is not None else f"{k}: —"
            for k, d in r["drift"].items()
        )
        tier_dist = " / ".join(
            f"{k}={v}" for k, v in sorted(r["tier_counts"].items())
        ) or "—"
        out.append(
            f"| {r['project_id']} | {r['n_rows']} | "
            f"{r['p75']:.0f} | {r['p90']:.0f} | "
            f"{r['current'].get('爆','—')} / {r['current'].get('大爆','—')} | "
            f"{drift_pct} | {tier_dist} |\n"
        )
    return "".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--project", help="Limit to one project")
    parser.add_argument("--window-days", type=int, default=90,
                        help="Distribution computed over this many days back (default 90)")
    parser.add_argument("--output", help="Write markdown to this path "
                        "(default: stdout)")
    args = parser.parse_args()

    sb = get_supabase_client()

    if args.project:
        project_ids = [args.project]
    else:
        project_ids = sorted(
            p.stem for p in _MAPPINGS_DIR.glob("*.yaml") if p.stem != "_template"
        )

    reports: list[dict] = []
    for pid in project_ids:
        r = analyze_project(sb, pid, args.window_days)
        if r is None:
            logger.info("  %s: skipped (no yaml / no thresholds / no data)", pid)
            continue
        reports.append(r)

    if not reports:
        logger.warning("No projects to analyze. Are there any notes with "
                       "interactions in the last %d days?", args.window_days)
        return 1

    md = format_markdown(reports)
    if args.output:
        Path(args.output).write_text(md, encoding="utf-8")
        logger.info("Wrote report to %s", args.output)
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
