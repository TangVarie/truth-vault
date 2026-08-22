"""deskcore/cli.py — 本地 CLI, 与 HTTP/MCP 共用同一个 core。

跟 librarian/cli.py 同一个用意: core 是纯函数, CLI 是它的第二个 adapter,
不起服务就能验逻辑。

用法:
  python -m deskcore.cli health
  python -m deskcore.cli projects
  python -m deskcore.cli open      --project <uuid> [--tactic ...] [--user <uuid>]
  python -m deskcore.cli draw      --project <uuid> -n 20 [--avoid-days 30]
  python -m deskcore.cli check     --project <uuid> --file drafts.json
  python -m deskcore.cli selftest              ← 不连库, 验查重逻辑
"""

from __future__ import annotations

import argparse
import json
import sys


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


# ══════════════════════════════════════════════════════════════════════
# selftest —— 不连库、不联网, 只验查重与发牌逻辑
# ══════════════════════════════════════════════════════════════════════

class _FakeTable:
    def __init__(self, rows): self._rows = rows
    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def is_(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def not_(self): return self
    def execute(self):
        class R: pass
        r = R(); r.data = self._rows; r.count = len(self._rows); return r


class _FakeSB:
    def __init__(self, fingerprints): self._fp = fingerprints
    def table(self, name):
        return _FakeTable(self._fp if name == "draft_fingerprints" else [])


def selftest() -> int:
    """验三件事: 精确撞开头能拦、换皮改写能拦、正常变体不误伤。"""
    from . import clients, core, vocab

    hist_body = ("上周去闺蜜家看到她桌上放了一盒这个，随手拍了张照。\n"
                 "回来自己也买了一盒，用到现在大概两周。")
    hist = [{
        "id": "h1",
        "title": "闺蜜桌上那盒东西我终于也买了",
        "opening": clients.opening_of(hist_body),
        "title_embedding": None,
        "opening_hash": clients.sha16(clients.normalize_text(clients.opening_of(hist_body))),
        "ngram_hashes": clients.ngram_hashes(hist_body),
        "created_at": "2026-08-01T00:00:00Z",
    }]
    sb = _FakeSB(hist)

    drafts = [
        # 1. 开头一模一样 → 必须 reject
        {"title": "完全不同的标题在这里", "body": hist_body + "\n后面接了别的内容。"},
        # 2. 换皮改写: 同一件事换了说法, 大量四字串重合 → 应该 reject
        {"title": "另一个标题",
         "body": "上周去闺蜜家看到她桌上放了一盒这个，随手拍了张照片。\n"
                 "回来自己也买了一盒，用到现在差不多两周。"},
        # 3. 真正不同的稿子 → 必须 pass
        {"title": "加班到十点，回家路上买了这个",
         "body": "地铁末班车上刷手机，看到有人在讨论换季干燥。\n"
                 "第二天下班顺路去店里拿了一支。"},
    ]

    out = core.check_drafts(sb, "p1", drafts)
    got = [r["status"] for r in out["results"]]
    print("查重自测:")
    for r in out["results"]:
        print(f"  [{r['status']:6s}] {r['title'][:24]:24s} "
              f"title={r['signals']['title_similarity']:.3f} "
              f"opening_exact={r['signals']['opening_exact_match']} "
              f"ngram={r['signals']['body_ngram_jaccard']:.3f}"
              + (f"  ← {r['reason']}" if r["reason"] else ""))

    ok = True
    if got[0] != "reject":
        print(f"  ✗ 用例1 应 reject(开头精确撞车), 实际 {got[0]}"); ok = False
    if got[1] == "pass":
        print(f"  ✗ 用例2 应被拦(换皮改写), 实际 pass"); ok = False
    if got[2] != "pass":
        print(f"  ✗ 用例3 应 pass(真正不同的稿子), 实际 {got[2]} —— 误伤"); ok = False

    # 发牌: 同一组维度必须产生同一个 key, 叠加项不影响
    d = {"emotional_lever": "焦虑撬动", "human_truth_archetype": "健康焦虑",
         "content_format": "情感叙事", "title_structure": "疑问句"}
    if core.angle_key(d) != core.angle_key({**d, "word_tilt": "自嘲"}):
        print("  ✗ angle_key 不该受叠加项影响"); ok = False

    # 词表完整性
    if set(vocab.LEVER_TO_VALENCE) != set(vocab.EMOTIONAL_LEVERS):
        print("  ✗ valence 映射没覆盖全部 lever"); ok = False
    if vocab.normalize_trends(["通用", "当代流行词"]) != ["通用"]:
        print("  ✗ 「通用」排他规则失效"); ok = False

    print(f"\n组合空间: {vocab.combination_space()} 组")
    print("selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


# ══════════════════════════════════════════════════════════════════════

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="deskcore", description="写作台内核 CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("selftest", help="不连库验查重/发牌逻辑")
    sub.add_parser("health", help="回显配置与依赖可用性")
    sub.add_parser("projects", help="列项目")

    p = sub.add_parser("open", help="打开项目, 打印完整写作简报")
    p.add_argument("--project", required=True)
    p.add_argument("--tactic", default="")
    p.add_argument("--topic", default="")
    p.add_argument("--user", default=None)

    p = sub.add_parser("draw", help="发牌")
    p.add_argument("--project", required=True)
    p.add_argument("-n", type=int, default=10)
    p.add_argument("--avoid-days", type=int, default=30)
    p.add_argument("--user", default=None)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--block", action="store_true", help="只打印可贴进 prompt 的坐标块")

    p = sub.add_parser("check", help="查重")
    p.add_argument("--project", required=True)
    p.add_argument("--file", required=True,
                   help='JSON 文件: [{"title": "...", "body": "..."}, ...]')

    args = ap.parse_args(argv)

    if args.cmd == "selftest":
        return selftest()

    # 以下命令要连库, 到这一步才 import(让 selftest 不需要任何依赖)
    from . import clients, core

    if args.cmd == "health":
        lib_ok, lib_note = clients.librarian_reachable()
        _print({
            "embeddings": clients.embeddings_available(),
            "librarian": {"ok": lib_ok, "note": lib_note},
        })
        return 0

    sb = clients.get_supabase()

    if args.cmd == "projects":
        _print(core.list_projects(sb))
    elif args.cmd == "open":
        _print(core.build_brief(sb, args.project, user_id=args.user,
                                brief={"tactic": args.tactic, "draft_topic": args.topic}))
    elif args.cmd == "draw":
        angles = core.draw_angles(sb, args.project, args.n,
                                  avoid_days=args.avoid_days,
                                  user_id=args.user, seed=args.seed)
        if args.block:
            print(core.render_angles_block(angles))
        else:
            _print(angles)
    elif args.cmd == "check":
        with open(args.file, encoding="utf-8") as fh:
            drafts = json.load(fh)
        _print(core.check_drafts(sb, args.project, drafts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
