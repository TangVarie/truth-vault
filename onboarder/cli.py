"""onboarder/cli.py — 命令行入口。

本地:
    # 只拼 prompt 不调 LLM、不连飞书:
    python -m onboarder.cli --project-id X --dry-run
    # 真跑(只需 ANTHROPIC_BASE_URL/ANTHROPIC_API_KEY + FEISHU_APP_ID/SECRET):
    python -m onboarder.cli --project-id WTG_phase1 \
        --app-token bascnXXX --table-id tblXXX --out-dir out
    # 或者直接贴浏览器地址栏里那条链接(/wiki/ 形态也认):
    python -m onboarder.cli --project-id WTG_phase1 \
        --url 'https://x.feishu.cn/base/bascnXXX?table=tblXXX' --out-dir out

多张表一次接:见 `python -m onboarder.batch --help`。

不再需要 Node / claude CLI —— 走 librarian 同款单次 Anthropic 调用。
"""

from __future__ import annotations

import argparse
import sys

from . import core


def main() -> int:
    p = argparse.ArgumentParser(description="接表助手:飞书表 → mapping.yaml 草稿")
    p.add_argument("--project-id", required=True, help="品牌_期数,如 TXQ_phase1")
    p.add_argument("--url", default="", help="飞书表链接(与 --app-token/--table-id 二选一)")
    p.add_argument("--app-token", default="", help="飞书表 app_token")
    p.add_argument("--table-id", default="", help="飞书表 table_id")
    p.add_argument("--sample-n", type=int, default=30, help="拉多少行文案样本(默认 30)")
    p.add_argument("--model", default=core.DEFAULT_MODEL, help="模型(默认 %(default)s)")
    p.add_argument("--out-dir", default="mappings", help="draft yaml + brief 输出目录")
    p.add_argument("--dry-run", action="store_true", help="只拼 prompt 不调 LLM、不连飞书")
    args = p.parse_args()

    if not args.dry_run and not args.url and (not args.app_token or not args.table_id):
        p.error("真跑需要 --url,或 --app-token + --table-id(或加 --dry-run)")

    result = core.run_onboarding(
        project_id=args.project_id,
        app_token=args.app_token,
        table_id=args.table_id,
        url=args.url,
        sample_n=args.sample_n,
        model=args.model,
        out_dir=args.out_dir,
        dry_run=args.dry_run,
    )
    return 1 if result.get("is_error") else 0


if __name__ == "__main__":
    sys.exit(main())
