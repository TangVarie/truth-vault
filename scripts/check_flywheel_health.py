"""
check_flywheel_health.py
═══════════════════════════════════════════════════════════════════════════

固化 R-022 / 通道1 下游验证清单 (见 docs/12 "飞轮健康自查"): 确认飞轮在 ssll
侧真闭环 —— ① TV 把爆款上架到 reference_samples ② ssll 写稿时真检索并用了它们.

四个检查 (只读, 不写库):
  Check 1 · TV→ssll 上架    : reference_samples 里有多少 TV 来源样本
  Check 2 · ssll 真用了吗    : public.stage_logs 的 r022_flywheel_audit 命中率
                              (ssll vibe_loop 每轮写一行; db_hit_rate = DB锚点 / 总vibe单元)
  Check 3 · 有没有飞轮告警   : r022_flywheel_audit status='completed_warn'
  Check 4 · TV 样本检索得到吗: TV 来源样本的 platform/category 没填空
                              (填错 ssll 会退化成 platform-only 检索, 见 docs/13)

退出码: 0 = 健康 / 仅提示; 1 = 发现可处理问题 (命中率低 / 有告警 / 样本缺 category).
"无审计行" 不算失败 —— 那是 "ssll 还没产出过内容", 提示去触发一次 vibe_loop 再来.

用法:
    python check_flywheel_health.py
    python check_flywheel_health.py --days 14 --hit-rate-threshold 0.3
    python check_flywheel_health.py --json     # 机器可读 (给 cron / 监控)

放进 cron: daily-sync.yml 跑完 sync 后加一步 `python check_flywheel_health.py`.
字段名 (db_sourced / static_sourced / total_vibe_cells) 以 ssll docs/architecture.md §2
为准; 跨仓查 stage_logs 的原始 SQL 模板见 docs/10 "TV 日报跨仓查 R-022 audit".
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

from _common import fetch_all_pages, get_supabase_client, setup_logger


logger = setup_logger("check_flywheel_health")

R022_STAGE = "r022_flywheel_audit"


def _utc_cutoff_iso(days: float) -> str:
    """Naive-UTC ISO cutoff (匹配本仓时间约定; ssll stage_logs 比较时 Postgres 自行 cast)."""
    return (
        (datetime.now(timezone.utc) - timedelta(days=days))
        .replace(tzinfo=None)
        .isoformat(timespec="seconds")
    )


def _as_int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


# ── Check 1 · TV→ssll 上架 ──────────────────────────────────────────────
def check_1_reference_samples(sb) -> dict:
    """reference_samples 总数 + TV 来源条数 + TV 明细(供 Check 4 复用)."""
    total = (
        sb.schema("public").table("reference_samples")
        .select("*", count="exact").limit(1).execute()
    ).count or 0
    # 分页拉全 (review #27 r3332926868): TV 样本超 PostgREST 1000 行上限时,
    # 单次 .execute() 只回第一页 → tv_origin 少算, 且 Check 4 只检视第一页,
    # 后面缺 platform/category 的样本会被误报健康. 用 fetch_all_pages 跟
    # check_2 / check_3 的 stage_logs 拉取保持一致.
    tv_rows = fetch_all_pages(
        sb.schema("public").table("reference_samples")
        .select("source_truth_vault_note_id, platform, category, quality_score")
        .not_.is_("source_truth_vault_note_id", None)
    )
    return {"total": total, "tv_origin": len(tv_rows), "tv_rows": tv_rows}


# ── Check 2 · ssll 写稿时真在用 DB 样本吗 ────────────────────────────────
def check_2_retrieval_audit(sb, days: float) -> dict:
    """聚合 r022_flywheel_audit 的 DB 命中率 (ssll 每轮 vibe_loop 写一行)."""
    rows = fetch_all_pages(
        sb.schema("public").table("stage_logs")
        .select("*")
        .eq("stage_name", R022_STAGE)
        .gte("created_at", _utc_cutoff_iso(days))
    )
    db_sourced = static_sourced = total_cells = 0
    for r in rows:
        od = r.get("output_data") or {}
        if not isinstance(od, dict):
            continue
        db_sourced += _as_int(od.get("db_sourced"))
        static_sourced += _as_int(od.get("static_sourced"))
        total_cells += _as_int(od.get("total_vibe_cells"))
    hit_rate = (db_sourced / total_cells) if total_cells else None
    return {
        "audit_rows": len(rows),
        "db_sourced": db_sourced,
        "static_sourced": static_sourced,
        "total_cells": total_cells,
        "hit_rate": hit_rate,
    }


# ── Check 3 · 飞轮告警 ──────────────────────────────────────────────────
def check_3_warnings(sb) -> dict:
    rows = fetch_all_pages(
        sb.schema("public").table("stage_logs")
        .select("run_id, created_at, status, output_data")
        .eq("stage_name", R022_STAGE)
        .eq("status", "completed_warn")
        .gte("created_at", _utc_cutoff_iso(1))
    )
    return {"warn_rows": rows}


# ── Check 4 · TV 样本检索得到吗 (platform/category 没填空) ───────────────
def check_4_retrievability(tv_rows: list) -> dict:
    bad = [
        r for r in tv_rows
        if not (r.get("platform") or "").strip() or not (r.get("category") or "").strip()
    ]
    return {"bad": bad}


# ── 上下文 · TV 侧同步状态 ───────────────────────────────────────────────
def context_sync_status(sb) -> list:
    return (
        sb.schema("truth_vault").table("v_flywheel_sync_status")
        .select(
            "project_id, total_baokuan, synced_to_ssll, pending_ssll_sync, "
            "synced_to_aw, pending_aw_sync, total_reference"
        )
        .execute()
    ).data or []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--days", type=float, default=7,
                        help="Check 2 审计窗口天数 (default 7)")
    parser.add_argument("--hit-rate-threshold", type=float, default=0.3,
                        help="db_hit_rate 低于此值告警 (default 0.3, 来自 docs/10)")
    parser.add_argument("--json", action="store_true",
                        help="输出机器可读 JSON (给 cron / 监控), 不打印人读报告")
    args = parser.parse_args()

    sb = get_supabase_client()

    ctx = context_sync_status(sb)
    c1 = check_1_reference_samples(sb)
    c2 = check_2_retrieval_audit(sb, args.days)
    c3 = check_3_warnings(sb)
    c4 = check_4_retrievability(c1["tv_rows"])

    problems: list[str] = []
    advisories: list[str] = []

    if c1["tv_origin"] == 0:
        advisories.append(
            "Check1: reference_samples 里还没有 TV 来源样本 (爆/大爆/参考 还没同步到 ssll)."
        )
    if c2["audit_rows"] == 0:
        advisories.append(
            f"Check2: 近 {args.days:g} 天没有 r022_flywheel_audit 行 —— ssll 还没跑过 vibe_loop, "
            "无法验证它是否真用了 DB 样本. 去触发一次 ssll 生成, 再回来跑本脚本."
        )
    elif c2["hit_rate"] is not None and c2["hit_rate"] < args.hit_rate_threshold:
        problems.append(
            f"Check2: db_hit_rate={c2['hit_rate']:.2f} < {args.hit_rate_threshold} "
            f"(db_sourced={c2['db_sourced']} / total_cells={c2['total_cells']}). "
            "ssll 写稿大多没锚 DB 样本 —— 查 category 是否对得上 / TV 是否漏同步."
        )
    if c3["warn_rows"]:
        problems.append(
            f"Check3: 过去 24h 有 {len(c3['warn_rows'])} 条 r022 告警 (completed_warn)."
        )
    if c4["bad"]:
        problems.append(
            f"Check4: {len(c4['bad'])} 条 TV 来源样本缺 platform/category —— "
            "ssll 会退化成 platform-only 检索 (见 docs/13)."
        )

    if args.json:
        out = {
            "context_sync_status": ctx,
            "check1_reference_samples": {"total": c1["total"], "tv_origin": c1["tv_origin"]},
            "check2_retrieval_audit": {
                k: c2[k] for k in
                ("audit_rows", "db_sourced", "static_sourced", "total_cells", "hit_rate")
            },
            "check3_warnings": len(c3["warn_rows"]),
            "check4_bad_samples": len(c4["bad"]),
            "problems": problems,
            "advisories": advisories,
            "healthy": not problems,
        }
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 1 if problems else 0

    print()
    print("=" * 92)
    print("  飞轮健康自查 · R-022 / 通道1 下游验证")
    print("=" * 92)
    print("  [TV 侧同步状态 · v_flywheel_sync_status]")
    if not ctx:
        print("    (无项目)")
    for r in ctx:
        print(
            f"    {r['project_id']:<16} 爆/大爆={_as_int(r.get('total_baokuan')):>3} "
            f"→ssll {_as_int(r.get('synced_to_ssll'))}/{_as_int(r.get('pending_ssll_sync'))} "
            f"→aw {_as_int(r.get('synced_to_aw'))}/{_as_int(r.get('pending_aw_sync'))} "
            f"参考={_as_int(r.get('total_reference'))}"
        )

    print()
    print(f"  Check 1 · TV→ssll 上架        : reference_samples 共 {c1['total']}, TV 来源 {c1['tv_origin']}")
    if c2["hit_rate"] is not None:
        c2_line = f"db_hit_rate={c2['hit_rate']:.2f} (db={c2['db_sourced']}/total={c2['total_cells']})"
    else:
        c2_line = "无 vibe 单元数据"
    print(f"  Check 2 · ssll 检索命中(近{args.days:g}天): audit 行={c2['audit_rows']}, {c2_line}")
    print(f"  Check 3 · 24h 飞轮告警        : {len(c3['warn_rows'])} 条")
    print(f"  Check 4 · TV 样本缺 platform/category: {len(c4['bad'])} 条")
    for r in c4["bad"]:
        print(f"      ⚠ {r.get('source_truth_vault_note_id')}: "
              f"platform={r.get('platform')!r} category={r.get('category')!r}")

    print()
    for a in advisories:
        print(f"  ℹ {a}")
    if problems:
        print()
        for p in problems:
            print(f"  ⚠ {p}")
        print(f"\n  ✗ 发现 {len(problems)} 个可处理问题.")
        return 1
    print("\n  ✓ 未发现可处理问题" + ("（含若干提示，见上）" if advisories else "") + ".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
