"""onboarder/cli.py — 命令行入口。

本地:
    # 只看 prompt + 工具,不调 LLM:
    python -m onboarder.cli --project-id TXQ_phase1 --app-token x --table-id y --dry-run
    # 真跑(需中转站 + 飞书凭证,见 onboarder/README.md):
    python -m onboarder.cli --project-id TXQ_phase1 \
        --app-token bascnXXX --table-id tblXXX

GitHub Actions 里由 .github/workflows/onboard-table.yml 调,产出再开 PR。
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from . import core


def main() -> int:
    p = argparse.ArgumentParser(description="接表 agent:飞书表 → mapping.yaml 草稿")
    p.add_argument("--project-id", required=True, help="品牌_期数,如 TXQ_phase1")
    p.add_argument("--app-token", default="", help="飞书表 app_token")
    p.add_argument("--table-id", default="", help="飞书表 table_id")
    p.add_argument("--sample-n", type=int, default=30, help="拉多少行样本(默认 30)")
    p.add_argument("--model", default=core.DEFAULT_MODEL, help="模型(默认 %(default)s)")
    p.add_argument("--max-turns", type=int, default=40)
    p.add_argument("--budget-usd", type=float, default=2.0, help="单次成本硬上限")
    p.add_argument("--out-dir", default="mappings", help="draft yaml + brief 输出目录")
    p.add_argument("--dry-run", action="store_true", help="只打印 prompt/工具,不调 LLM")
    args = p.parse_args()

    if not args.dry_run and (not args.app_token or not args.table_id):
        p.error("真跑需要 --app-token 和 --table-id(或加 --dry-run)")

    result = asyncio.run(
        core.run_onboarding(
            project_id=args.project_id,
            app_token=args.app_token,
            table_id=args.table_id,
            sample_n=args.sample_n,
            model=args.model,
            max_turns=args.max_turns,
            budget_usd=args.budget_usd,
            out_dir=args.out_dir,
            dry_run=args.dry_run,
        )
    )
    return 1 if result.get("is_error") else 0


if __name__ == "__main__":
    sys.exit(main())
