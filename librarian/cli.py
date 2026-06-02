"""librarian/cli.py — 馆员选取命令行测试器。

给一个 brief, 跑馆员选取; --dry-run 只渲染 prompt(不调 LLM、不写缓存)。
FastAPI 端点(后续 app.py)与本 CLI 共用 core.librarian_select, 这里先用来连库验证。

用法:
    python -m librarian.cli --brief librarian/sample_brief.json --dry-run
    python -m librarian.cli --brief librarian/sample_brief.json
    echo '{"consumer":"autowriter","project_id":"x","brand":"WTG","tactic":"经期场景"}' \\
        | python -m librarian.cli --stdin --dry-run

前置:
    v1.4 + v1.5 已 apply 到目标库 (v_flywheel_lesson_cards + flywheel_librarian_cache);
    SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY; ANTHROPIC_API_KEY (非 --dry-run 时)。
"""

from __future__ import annotations

import argparse
import json
import sys

from .core import librarian_select


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--brief", help="brief JSON 文件路径")
    src.add_argument("--stdin", action="store_true", help="从 stdin 读 brief JSON")
    p.add_argument("--dry-run", action="store_true",
                   help="只渲染 prompt + 算 cache_key, 不调 LLM / 不写缓存")
    p.add_argument("--no-cache", action="store_true", help="跳过缓存读写, 强制跑馆员")
    p.add_argument("--model", default=None, help="覆盖 FLYWHEEL_LIBRARIAN_MODEL")
    args = p.parse_args()

    if args.stdin:
        brief = json.load(sys.stdin)
    else:
        with open(args.brief, encoding="utf-8") as f:
            brief = json.load(f)

    out = librarian_select(
        brief, model=args.model, use_cache=not args.no_cache, dry_run=args.dry_run,
    )
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
