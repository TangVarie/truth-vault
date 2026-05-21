"""
preview_injection_candidates.py
═══════════════════════════════════════════════════════════════════════════

Side-by-side preview: 当前 sync 策略 vs 新的 score+diversity 策略，下次
跑 sync_truth_vault_baokuan_to_autowriter_items.py 时会选哪几条注入到
autowriter.items（example_label='positive'）。

No writes, no side effects. 这不是 backtest，只是个"看一眼放心不放心"的工具。
觉得新策略选的更合理，cron 切到新 sync 就行；觉得不对，回退也是一行。

用法:
    python preview_injection_candidates.py                       # 全部项目
    python preview_injection_candidates.py --project NUC_phase1  # 单项目
    python preview_injection_candidates.py --limit 10            # 多取几条

环境变量:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""

from __future__ import annotations

import argparse
import sys

from _common import fetch_all_pages, get_supabase_client, setup_logger


logger = setup_logger("preview_injection")


def _fmt_row(r: dict, with_score: bool = False) -> str:
    snippet = (r.get("raw_content") or "").replace("\n", " ").strip()[:40]
    parts = [
        f"{r['note_id']:<32s}",
        f"{str(r.get('publish_time') or '')[:10]:<10s}",
        f"tier={r.get('tier') or '?':<3s}",
        f"src={(r.get('tier_source') or '?'):<8s}",
    ]
    if with_score:
        parts.append(f"score={r.get('injection_score') or 0:.2f}")
        parts.append(f"lever={(r.get('emotional_lever') or '?'):<10s}")
    parts.append(snippet)
    return "  " + " | ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--project", help="Limit to one project (e.g. NUC_phase1)")
    parser.add_argument("--limit", type=int, default=5,
                        help="Show top N from each strategy (default 5; matches "
                             "autowriter's build_system_prompt[:5] slice)")
    args = parser.parse_args()

    sb = get_supabase_client()

    # ── Current strategy: 全部 pending baokuan，按 publish_time DESC 取 N ──
    # This is the closest proxy to "what autowriter sees in list_example_items
    # ordered by created_at DESC" since older sync logic synced everything.
    cur_q = (
        sb.schema("truth_vault").table("notes")
        .select("note_id, project_id, tier, tier_source, publish_time, "
                "emotional_lever, raw_content")
        .in_("tier", ["爆", "大爆"])
        .is_("synced_to_aw_at", None)
    )
    if args.project:
        cur_q = cur_q.eq("project_id", args.project)
    cur_rows = fetch_all_pages(cur_q.order("publish_time", desc=True))[:args.limit]

    # ── New strategy: score view + diversity ──
    new_q = (
        sb.schema("truth_vault").table("v_autowriter_injection_candidates")
        .select("note_id, project_id, raw_content, tier, tier_source, "
                "publish_time, emotional_lever, injection_score, "
                "recency_weight, account_bao_rate")
        .is_("synced_to_aw_at", None)
    )
    if args.project:
        new_q = new_q.eq("project_id", args.project)
    new_rows = fetch_all_pages(new_q.order("injection_score", desc=True))

    # Apply the same diversity filter the sync script would.
    from sync_truth_vault_baokuan_to_autowriter_items import (
        apply_diversity_filter,
        DEFAULT_INJECTION_MIN_SCORE,
        DEFAULT_INJECTION_MIN_LEVERS,
    )
    above = [c for c in new_rows if (c.get("injection_score") or 0) >= DEFAULT_INJECTION_MIN_SCORE]
    new_top = apply_diversity_filter(
        above, max_n=args.limit, min_levers=DEFAULT_INJECTION_MIN_LEVERS,
    )

    # ── Display ──
    title = f"project={args.project}" if args.project else "all projects"
    print("\n" + "=" * 96)
    print(f"  Injection preview · {title} · limit={args.limit}")
    print("=" * 96)

    print(f"\n  [当前策略] 全部 pending, publish_time DESC")
    print("  " + "-" * 92)
    if not cur_rows:
        print("    (无 pending baokuan)")
    for r in cur_rows:
        print(_fmt_row(r, with_score=False))

    print(f"\n  [新策略] v_autowriter_injection_candidates · score DESC + diversity")
    print(f"  min_score={DEFAULT_INJECTION_MIN_SCORE} · min_levers={DEFAULT_INJECTION_MIN_LEVERS}")
    print("  " + "-" * 92)
    if not new_top:
        print("    (无符合条件的候选 — 可能全部不达 score 门槛，或全部在 12 月以外，或全部数值推断未 confirm)")
    for r in new_top:
        print(_fmt_row(r, with_score=True))

    # ── Diff ──
    cur_ids = {r["note_id"] for r in cur_rows}
    new_ids = {r["note_id"] for r in new_top}
    common = cur_ids & new_ids

    print("\n  [差异]")
    print("  " + "-" * 92)
    print(f"    共同: {len(common):2d} / {args.limit}")
    only_cur = sorted(cur_ids - new_ids)
    only_new = sorted(new_ids - cur_ids)
    if only_cur:
        print(f"    仅当前会选 (新策略已过滤掉): {only_cur}")
    if only_new:
        print(f"    仅新策略会选 (按 score+diversity 上升): {only_new}")
    if not only_cur and not only_new:
        print("    两策略结果一致")
    print()

    # ── Stats on the broader pool ──
    print("  [候选池统计 · 不限 limit]")
    print("  " + "-" * 92)
    print(f"    符合 view eligibility 的 pending 候选: {len(new_rows)}")
    print(f"    其中达 min_score≥{DEFAULT_INJECTION_MIN_SCORE} 的: {len(above)}")
    if new_rows:
        scores = sorted((r["injection_score"] or 0) for r in new_rows)
        n = len(scores)
        print(f"    score 分布 · min={scores[0]:.2f} · "
              f"p50={scores[n//2]:.2f} · max={scores[-1]:.2f}")
        levers = {r.get("emotional_lever") for r in new_rows if r.get("emotional_lever")}
        print(f"    emotional_lever 覆盖: {len(levers)} 种 · {sorted(levers)}")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
