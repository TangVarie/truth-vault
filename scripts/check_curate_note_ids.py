#!/usr/bin/env python3
"""CI 守卫: 按 note_id 点名重策展 (curate_flywheel_lessons.py --note-ids; D-122 修复计划第 5 条, D-123)。

NUC 15 张卡策展时人群被夜跑冲掉 (提示里写「未标」); 恢复不动 essence_annotated_at, --recurate-stale 永远挑不到它们,
全项目 --recurate 会白白换掉另外 70 张好卡。所以要能「只重策展这几张」, 而且不能比点名的多一张、少一张不吭声。

  §1 read_note_ids: 逗号分隔 / 文件 (一行一个、一行几个、# 注释、空行), 保序去重; 15 个真长度 id 连起来 (>255 字节) 不当路径抛错
  §2 fetch_uncurated_cards(note_ids=…): 只取点名的; 不看 is_curated (已策展的也取); project 筛传下去;
     飞书已删照样跳过; 超过一块的 id 分块 in_ (每块 ≤ NOTE_IDS_CHUNK, .in_ 走 URL); 合起来按 rank_score 降序
  §3 main --note-ids: 少一张 (不在候选 / 项目对不上 / 已删) → rc=2 一次模型都不调、一行不写; 和 --recurate /
     --recurate-stale 同用 → rc=2; dry-run 不调不写; 真跑只写点名的那几张; --limit 小于张数时按 rank 截断并点名推迟的;
     Found 行带 dry_run=true/false (workflow 从这里取); 部分失败 rc=0, 失败的 id 单独一行「note_ids 失败」, 不说「下轮重试」
  §4 默认路 / --recurate-stale 不受影响 (不带 note_ids 时照旧按 is_curated 取, 不发 in_)
  §5 recurate-lessons.yml: note_ids / dry_run 输入走 env 不插进 shell; 点名那步只跑一轮、带 --note-ids 和 --limit;
     循环那步在点名模式下不跑; 入参校验那段 shell 真跑一遍 (好 id 过、坏格式 / 没 mapping / 项目对不上 / 超 limit / 超 50 红);
     点名步和循环步也真跑一遍: PATH 前面垫一个假 python (记下 argv, 再拿假库跑真的 cur.main), 断言 dry_run 勾了就有
     --dry-run、没勾就没有, project 给了就传 --project; dry-run 的 [dry-run] 行打得出来; ✅ / ℹ️ 行的 dry_run 取自脚本日志,
     脚本没照 --dry-run 走就红; 部分失败 ::warning:: 点名失败的卡; 全失败 / 缺卡红; 循环步 dry_run 只跑一轮
反证 (拷到临时目录改, 不改仓里文件, 10-20 实跑): 去掉缺卡拒跑 → §3 红; note_ids 路也加 is_curated=false → §2 红;
     不分块 → §2 红; 长 id 串当路径 stat (ENAMETOOLONG) → §1 红; 点名步不传 --limit → §5 红; 循环步去掉 if → §5 红;
     入参校验不比 limit → §5 红。D-123 复审后补的 11 条: 点名步 DRY_FLAG 判 "True" (dry_run 传丢) → §5 红; 点名步丢掉
     "${PROJ_FLAG[@]}" → §5 红; ✅ 行回显 $DRY_RUN 而不是日志 → §5 红; 点名步的 grep 不带 [dry-run] → §5 红;
     部分失败不 ::warning:: → §5 红; 循环步 DRY_FLAG 判错 → §5 红; 循环步去掉 dry_run 的 MAXB=1 → §5 红;
     循环步丢掉 "${PROJ_FLAG[@]}" → §5 红; 脚本不打失败名单 → §3 红; Found 行不带 dry_run → §3 / §5 红;
     点名模式仍说「下轮重试」→ §3 红。
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import curate_flywheel_lessons as cur  # noqa: E402


class _Q:
    """记录过滤 / 写入的假 query builder (够 fetch_all_pages、in_、upsert 用)。"""

    def __init__(self, sb, name):
        self.sb, self.name, self.filters, self._done, self._upsert = sb, name, [], False, None

    def select(self, *_a, **_k): return self
    def order(self, *_a, **_k): return self
    def range(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self

    def eq(self, col, val):
        self.filters.append(("eq", col, val)); return self

    def in_(self, col, vals):
        self.filters.append(("in", col, list(vals))); return self

    def upsert(self, row, on_conflict=None, **_k):
        self._upsert = (row, on_conflict); return self

    def execute(self):
        if self._upsert is not None:
            self.sb.writes.append((self.name,) + self._upsert)
            return type("R", (), {"data": [self._upsert[0]]})()
        if self._done:                       # fetch_all_pages 翻到第二页 → 空 (同一个请求, 不再记一次)
            return type("R", (), {"data": []})()
        self._done = True
        self.sb.reads.append((self.name, list(self.filters)))
        out = [dict(r) for r in self.sb.tables.get(self.name, [])]
        for kind, col, val in self.filters:
            out = [r for r in out if (r.get(col) == val if kind == "eq" else r.get(col) in val)]
        return type("R", (), {"data": out})()


class _SB:
    def __init__(self, tables):
        self.tables, self.reads, self.writes = tables, [], []

    def schema(self, _s): return self
    def table(self, name): return _Q(self, name)


def _card(nid, rank, curated=True, project="NUC_phase1"):
    # raw_excerpt 带上 id: 假模型按提示里有没有某个 id 决定回不回坏 JSON (部分失败那几条用)
    return {"source_note_id": nid, "project_id": project, "tier": "爆", "brand": "b", "category": "c",
            "emotional_lever": "共鸣释放", "target_audience": ["宝妈"], "raw_excerpt": f"正文 {nid}", "is_curated": curated,
            "rank_score": rank, "curated_at": "2026-06-10T09:00:00" if curated else None, "synthetic": False}


VIEW = [_card("NUC_phase1_recA", 1.2), _card("NUC_phase1_recB", 1.7), _card("NUC_phase1_recC", 1.5),
        _card("NUC_phase1_recNew", 1.9, curated=False), _card("NUC_phase1_recGone", 1.1),
        _card("WTG_phase1_recW", 1.8, project="WTG_phase1")]


class _Log(logging.Handler):
    def __init__(self):
        super().__init__(); self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


GOOD_REPLY = json.dumps({"hook_type": "h", "structure": "s", "why_it_worked": "w", "transferable_tactic": "t"})


def _run_main(argv, sb, *, vanished=frozenset(), reply=None, fail=frozenset()):
    calls: list[str] = []
    cur.get_supabase_client = lambda: sb
    cur.fetch_vanished_note_ids = lambda _sb, project_id=None: set(vanished)
    cur.call_claude = lambda prompt, model: calls.append(prompt) or (
        reply or ("not json" if any(f in prompt for f in fail) else GOOD_REPLY))
    h = _Log()
    cur.logger.addHandler(h)
    try:
        rc = cur.main(argv + ["--qps", "0"])
    finally:
        cur.logger.removeHandler(h)
    return rc, calls, h.lines


def s1_read(fails: list[str]) -> None:
    got = cur.read_note_ids(" NUC_phase1_recB, NUC_phase1_recA,,NUC_phase1_recB ")
    if got != ["NUC_phase1_recB", "NUC_phase1_recA"]:
        fails.append(f"§1 逗号分隔要保序去重、去空白, 实际 {got}")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("# D-122 NUC 15 张\nNUC_phase1_recC\n\nNUC_phase1_recA, NUC_phase1_recC\n  # 注释\nNUC_phase1_recB\n")
        path = f.name
    try:
        got = cur.read_note_ids(path)
        if got != ["NUC_phase1_recC", "NUC_phase1_recA", "NUC_phase1_recB"]:
            fails.append(f"§1 文件 (一行一个 / 一行几个 / # 注释 / 空行) 读错: {got}")
    finally:
        os.unlink(path)
    if cur.read_note_ids(" , ") != []:
        fails.append("§1 只有逗号和空白 → 空名单")
    # 真名单的长度: 15 个 NUC id 连起来 ~400 字节, 超过文件名上限; 当成路径去 stat 会抛 ENAMETOOLONG (10-20 本地实测)
    long_ids = [f"NUC_phase1_recv{i:02d}xd6lzUlFRab" for i in range(15)]
    try:
        got = cur.read_note_ids(",".join(long_ids))
    except OSError as exc:
        got = f"抛了 {exc!r}"
    if got != long_ids:
        fails.append(f"§1 15 个长 id 逗号连起来 (>255 字节) 要照常读, 实际 {got if isinstance(got, str) else len(got)}")


def s2_fetch(fails: list[str]) -> None:
    cur.fetch_vanished_note_ids = lambda _sb, project_id=None: {"NUC_phase1_recGone"}
    sb = _SB({"v_flywheel_lesson_cards": VIEW})
    got = [c["source_note_id"] for c in cur.fetch_uncurated_cards(
        sb, None, False, note_ids=["NUC_phase1_recA", "NUC_phase1_recNew", "NUC_phase1_recB", "NUC_phase1_recGone"])]
    if got != ["NUC_phase1_recNew", "NUC_phase1_recB", "NUC_phase1_recA"]:
        fails.append(f"§2 应只回点名的、不看 is_curated、跳过已删、按 rank 降序, 实际 {got}")
    if any(f[0] == "eq" and f[1] == "is_curated" for _, fs in sb.reads for f in fs):
        fails.append("§2 点名路不许按 is_curated 筛 (已策展的卡正是要重来的)")
    sb = _SB({"v_flywheel_lesson_cards": VIEW})
    got = [c["source_note_id"] for c in cur.fetch_uncurated_cards(
        sb, "NUC_phase1", False, note_ids=["NUC_phase1_recA", "WTG_phase1_recW"])]
    if got != ["NUC_phase1_recA"] or not all(("eq", "project_id", "NUC_phase1") in fs
                                             for name, fs in sb.reads if name == "v_flywheel_lesson_cards"):
        fails.append(f"§2 --project 要传下去, 别的项目的卡不回, 实际 {got}")
    many = [f"NUC_phase1_recX{i:04d}" for i in range(cur.NOTE_IDS_CHUNK * 2 + 7)]
    rows = [_card(x, (i % 13) / 10) for i, x in enumerate(many)]
    sb = _SB({"v_flywheel_lesson_cards": rows})
    cur.fetch_vanished_note_ids = lambda _sb, project_id=None: set()
    got = cur.fetch_uncurated_cards(sb, None, False, note_ids=many)
    ins = [f for name, fs in sb.reads if name == "v_flywheel_lesson_cards" for f in fs if f[0] == "in"]
    if len(got) != len(many) or len(ins) != 3 or max(len(f[2]) for f in ins) > cur.NOTE_IDS_CHUNK:
        fails.append(f"§2 {len(many)} 个 id 要分 3 块 in_ (每块 ≤{cur.NOTE_IDS_CHUNK}) 且一张不丢: "
                     f"块 {[len(f[2]) for f in ins]}, 回 {len(got)}")
    ranks = [c["rank_score"] for c in got]
    if ranks != sorted(ranks, reverse=True):
        fails.append("§2 分块取回后要整体按 rank_score 降序 (--limit 截断时先策展最该上架的)")


def s3_main(fails: list[str]) -> None:
    os.environ["ANTHROPIC_API_KEY"] = "test-not-a-key"
    want = ["NUC_phase1_recA", "NUC_phase1_recB", "NUC_phase1_recC"]

    sb = _SB({"v_flywheel_lesson_cards": VIEW})
    rc, calls, log = _run_main(["--note-ids", ",".join(want + ["NUC_phase1_recTypo"])], sb)
    if rc != 2 or calls or sb.writes or not any("NUC_phase1_recTypo" in ln for ln in log):
        fails.append(f"§3 有一张不在候选里: 要 rc=2、0 次调用、0 写、点名缺的那张; 实际 rc={rc} 调用 {len(calls)} 写 {len(sb.writes)}")

    sb = _SB({"v_flywheel_lesson_cards": VIEW})
    rc, calls, _ = _run_main(["--note-ids", "NUC_phase1_recA,NUC_phase1_recGone"], sb, vanished={"NUC_phase1_recGone"})
    if rc != 2 or calls or sb.writes:
        fails.append(f"§3 点名的卡飞书里已删: 也要 rc=2 一张不跑, 实际 rc={rc} 调用 {len(calls)}")

    sb = _SB({"v_flywheel_lesson_cards": VIEW})
    rc, calls, _ = _run_main(["--note-ids", "WTG_phase1_recW", "--project", "NUC_phase1"], sb)
    if rc != 2 or calls:
        fails.append(f"§3 项目对不上: 要 rc=2, 实际 rc={rc}")

    for extra in (["--recurate"], ["--recurate-stale"]):
        sb = _SB({"v_flywheel_lesson_cards": VIEW})
        rc, calls, _ = _run_main(["--note-ids", ",".join(want)] + extra, sb)
        if rc != 2 or calls or sb.reads:
            fails.append(f"§3 --note-ids 和 {extra[0]} 同用: 要 rc=2 且不查库, 实际 rc={rc}")

    sb = _SB({"v_flywheel_lesson_cards": VIEW})
    rc, calls, _ = _run_main(["--note-ids", " , "], sb)
    if rc != 2 or calls or sb.reads:
        fails.append(f"§3 空名单要 rc=2, 实际 rc={rc}")

    sb = _SB({"v_flywheel_lesson_cards": VIEW})
    rc, calls, log = _run_main(["--note-ids", ",".join(want), "--dry-run"], sb)
    if rc != 0 or calls or sb.writes or not any('"ok": 3' in ln for ln in log):
        fails.append(f"§3 dry-run: 要 rc=0、不调不写、Done ok=3, 实际 rc={rc} 调用 {len(calls)} 写 {len(sb.writes)}")
    if not any(ln.startswith("Found ") and "note_ids=3" in ln and ln.rstrip(")").endswith("dry_run=true") for ln in log):
        fails.append(f"§3 dry-run 的 Found 行要带 note_ids=3 和 dry_run=true (workflow 从这里取, 不回显输入): "
                     f"{[ln for ln in log if ln.startswith('Found ')]}")

    sb = _SB({"v_flywheel_lesson_cards": VIEW})
    rc, calls, log = _run_main(["--note-ids", ",".join(want)], sb)
    written = [w[1]["note_id"] for w in sb.writes]
    if rc != 0 or len(calls) != 3 or sorted(written) != sorted(want) \
            or any(w[0] != "flywheel_lesson_annotations" or w[2] != "note_id" for w in sb.writes):
        fails.append(f"§3 真跑只写点名的 3 张 (按 note_id upsert), 实际 rc={rc} 写 {written}")
    if written != ["NUC_phase1_recB", "NUC_phase1_recC", "NUC_phase1_recA"]:
        fails.append(f"§3 按 rank_score 降序处理, 实际 {written}")
    if any(re.search(r"人群[^\n]*未标|目标人群 \(已标\): 未标", p) for p in calls):
        fails.append("§3 恢复后的卡带着人群, 提示里不该再是「未标」")
    if not any(ln.startswith("Found ") and ln.rstrip(")").endswith("dry_run=false") for ln in log):
        fails.append("§3 真跑的 Found 行要带 dry_run=false")
    if any("note_ids 失败" in ln for ln in log):
        fails.append("§3 全成功时不该有「note_ids 失败」行")

    sb = _SB({"v_flywheel_lesson_cards": VIEW})
    rc, calls, log = _run_main(["--note-ids", ",".join(want), "--limit", "2"], sb)
    written = [w[1]["note_id"] for w in sb.writes]
    if rc != 0 or written != ["NUC_phase1_recB", "NUC_phase1_recC"] \
            or not any("预算截断" in ln and "NUC_phase1_recA" in ln for ln in log):
        fails.append(f"§3 --limit 2 < 3 张: 先策展 rank 高的两张、点名推迟的 recA, 实际 rc={rc} 写 {written}")

    sb = _SB({"v_flywheel_lesson_cards": VIEW})
    rc, calls, log = _run_main(["--note-ids", ",".join(want)], sb, reply="not json")
    if rc != 1 or sb.writes:
        fails.append(f"§3 全军覆没照旧 rc=1 (失败卡不写), 实际 rc={rc}")
    if not any(ln.startswith("note_ids 失败 3 张: ") for ln in log):
        fails.append("§3 全军覆没也要单独一行点名失败的 3 张")

    # 部分失败 (D-123 复审): rc=0 不拖红, 但失败的 id 要单独一行点名; 点名的卡已策展, 夜跑不会重试 —— 不许说「下轮重试」
    sb = _SB({"v_flywheel_lesson_cards": VIEW})
    rc, calls, log = _run_main(["--note-ids", ",".join(want)], sb, fail={"NUC_phase1_recA", "NUC_phase1_recC"})
    written = [w[1]["note_id"] for w in sb.writes]
    line = [ln for ln in log if ln.startswith("note_ids 失败 ")]
    if rc != 0 or written != ["NUC_phase1_recB"] or len(calls) != 5:
        fails.append(f"§3 部分失败: 要 rc=0、只写 recB、失败的各重试一次 (共 5 次调用), 实际 rc={rc} 写 {written} 调用 {len(calls)}")
    if line != ["note_ids 失败 2 张: NUC_phase1_recC,NUC_phase1_recA"]:
        fails.append(f"§3 部分失败要一行点名失败的卡 (按处理顺序, 逗号分隔, 能直接贴回 note_ids), 实际 {line}")
    if any("下轮" in ln for ln in log):
        fails.append(f"§3 点名模式不许承诺「下轮重试」(已策展的卡夜跑和 --recurate-stale 都挑不到): {[ln for ln in log if '下轮' in ln]}")


def s4_default_paths(fails: list[str]) -> None:
    cur.fetch_vanished_note_ids = lambda _sb, project_id=None: set()
    sb = _SB({"v_flywheel_lesson_cards": VIEW})
    got = [c["source_note_id"] for c in cur.fetch_uncurated_cards(sb, "NUC_phase1", False)]
    if got != ["NUC_phase1_recNew"]:
        fails.append(f"§4 默认路仍只取 is_curated=false, 实际 {got}")
    if any(f[0] == "in" for _, fs in sb.reads for f in fs):
        fails.append("§4 不带 note_ids 时不该发 in_")


def s5_workflow(fails: list[str]) -> None:
    import yaml
    wf = yaml.safe_load((ROOT / ".github/workflows/recurate-lessons.yml").read_text(encoding="utf-8"))
    inputs = wf[True]["workflow_dispatch"]["inputs"] if True in wf else wf["on"]["workflow_dispatch"]["inputs"]
    if "note_ids" not in inputs or "dry_run" not in inputs:
        fails.append("§5 recurate-lessons.yml 要有 note_ids / dry_run 两个输入")
    job = wf["jobs"]["recurate"]
    env = job.get("env") or {}
    if "github.event.inputs.note_ids" not in str(env.get("NOTE_IDS")) or "github.event.inputs.dry_run" not in str(env.get("DRY_RUN")):
        fails.append("§5 note_ids / dry_run 要走 job env")
    bad = re.compile(r"\$\{\{\s*(inputs\.|github\.event\.inputs\.|secrets\.)")
    for st in job["steps"]:
        if st.get("run") and bad.search(st["run"]):
            fails.append(f"§5 {st.get('name')} 把输入直接插进了 shell (脚本注入), 改走 env")
    pick = [st for st in job["steps"] if "python curate_flywheel_lessons.py --note-ids" in (st.get("run") or "")]
    loop = [st for st in job["steps"] if "python curate_flywheel_lessons.py --recurate-stale" in (st.get("run") or "")]
    if len(pick) != 1 or len(loop) != 1:
        fails.append(f"§5 点名步 / 循环步应各一个, 实际 {len(pick)} / {len(loop)}")
        return
    p, lp = pick[0], loop[0]
    if "note_ids != ''" not in str(p.get("if")) or "note_ids == ''" not in str(lp.get("if")):
        fails.append("§5 点名步只在 note_ids 非空时跑, 循环步只在 note_ids 为空时跑")
    if 'python curate_flywheel_lessons.py --note-ids "$NOTE_IDS" --limit "$LIMIT"' not in p["run"]:
        fails.append("§5 点名步要原样传 --note-ids \"$NOTE_IDS\" 和 --limit \"$LIMIT\" (预算写明)")
    if "for i in" in p["run"] or '"${DRY_FLAG[@]}"' not in p["run"] or "exit 1" not in p["run"]:
        fails.append("§5 点名步只跑一轮、带 dry_run、非零退出判红")
    if '"${DRY_FLAG[@]}"' not in lp["run"] or 'MAXB=1' not in lp["run"]:
        fails.append("§5 循环步 dry_run 也要传下去, 且只跑一轮 (不写库就不会收敛)")

    guard = [st for st in job["steps"] if "NOTE_IDS" in (st.get("run") or "") and "mappings/" in (st.get("run") or "")]
    if len(guard) != 1:
        fails.append("§5 找不到 note_ids 的入参校验")
        return
    body = guard[0]["run"]

    def run(**kw):
        e = {"PATH": os.environ.get("PATH", ""), "SUPABASE_URL": "x", "SUPABASE_SERVICE_ROLE_KEY": "x",
             "ANTHROPIC_API_KEY": "x", "ANTHROPIC_BASE_URL": "x", "PROJECT": "", "LIMIT": "15", "MAXB": "20",
             "NOTE_IDS": "", "DRY_RUN": "false"}
        e.update(kw)
        r = subprocess.run(["bash", "-e", "-c", body], cwd=ROOT, env=e, capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    ok_ids = ",".join(f"NUC_phase1_rec{c}" for c in "ABCDEFGHIJKLMNO")       # 15 张
    cases = [
        ("15 张 NUC、limit 15", dict(NOTE_IDS=ok_ids), 0),
        ("给了 project 且对得上", dict(NOTE_IDS=ok_ids, PROJECT="NUC_phase1"), 0),
        ("dry_run", dict(NOTE_IDS=ok_ids, DRY_RUN="true"), 0),
        ("超 limit", dict(NOTE_IDS=ok_ids, LIMIT="14"), 1),
        ("项目对不上", dict(NOTE_IDS=ok_ids, PROJECT="WTG_phase1"), 1),
        ("不像 <project>_rec", dict(NOTE_IDS="NUC_phase1_recA,foo"), 1),
        ("非法字符", dict(NOTE_IDS="NUC_phase1_recA;id"), 1),
        ("前缀没有 mapping", dict(NOTE_IDS="NOPE_phase9_recA"), 1),
        ("超 50 个", dict(NOTE_IDS=",".join(f"NUC_phase1_rec{i}" for i in range(51)), LIMIT="50"), 1),
        ("dry_run 乱填", dict(NOTE_IDS=ok_ids, DRY_RUN="yes"), 1),
        ("循环模式不受影响", dict(), 0),
    ]
    for name, kw, want in cases:
        rc, out = run(**kw)
        if rc != want:
            fails.append(f"§5 入参校验「{name}」该 rc={want}, 实际 {rc}: {out.strip()[-200:]}")

    s5_steps(fails, p["run"], lp["run"])


def _stub_curate(argv: list[str]) -> int:
    """§5 的假 python: workflow 两步里的 `python curate_flywheel_lessons.py …` 落到这里 (PATH 前面垫了一个 python 壳)。
    先把 argv 记进 $STUB_ARGV_LOG (一次一行 JSON), 再拿假库跑真的 cur.main —— 日志是脚本自己打的, 步骤从日志里取
    dry_run / ok / 失败名单, 这里不替它编。
      STUB_FAIL     这几张假模型回坏 JSON;      STUB_MISSING  这几张不在视图里;
      STUB_STALE    循环那步的陈旧卡 (假库不落写, 每轮都还在);
      STUB_DROP_DRY 反证: 收到 --dry-run 也当没收到 (参数传丢 / 脚本没照参数走), 步骤要从日志看出来。"""
    if argv and argv[0].endswith("curate_flywheel_lessons.py"):
        argv = argv[1:]
    with open(os.environ["STUB_ARGV_LOG"], "a", encoding="utf-8") as f:
        f.write(json.dumps(argv, ensure_ascii=False) + "\n")
    if os.environ.get("STUB_DROP_DRY"):
        argv = [a for a in argv if a != "--dry-run"]

    def ids(key):
        return [x for x in os.environ.get(key, "").split(",") if x]

    missing, fail = set(ids("STUB_MISSING")), set(ids("STUB_FAIL"))
    cards, notes = [], []
    if "--note-ids" in argv:
        for i, nid in enumerate(cur.read_note_ids(argv[argv.index("--note-ids") + 1])):
            if nid not in missing:
                cards.append(_card(nid, 2.0 - i / 100, project=nid.split("_rec")[0]))
    for nid in ids("STUB_STALE"):
        cards.append(_card(nid, 1.0, project=nid.split("_rec")[0]))
        notes.append({"note_id": nid, "essence_annotated_at": "2026-10-20T16:00:00"})
    sb = _SB({"v_flywheel_lesson_cards": cards, "notes": notes})
    cur.get_supabase_client = lambda: sb
    cur.fetch_vanished_note_ids = lambda _sb, project_id=None: set()
    cur.call_claude = lambda prompt, model: "not json" if any(x in prompt for x in fail) else GOOD_REPLY
    cur.time.sleep = lambda _s: None          # 子进程里, 不影响本进程
    return cur.main(argv)


def s5_steps(fails: list[str], pick_body: str, loop_body: str) -> None:
    """点名步 / 循环步的 shell 原样跑 (D-123 复审: 以前只比子串, DRY_FLAG 判成 "True" 这种回归照样绿,
    免费的 dry-run 就成了 30 次付费调用、15 张卡没人看就被换掉)。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "bin").mkdir()
        stub = tmp / "bin" / "python"
        stub.write_text('#!/usr/bin/env bash\nexec "$STUB_REAL_PYTHON" "$STUB_CHECK" --stub-curate "$@"\n', encoding="utf-8")
        stub.chmod(0o755)
        seq = iter(range(1000))

        def run(body, **kw):
            k = next(seq)
            argv_log = tmp / f"argv{k}.jsonl"
            e = {x: v for x, v in os.environ.items() if not x.startswith("STUB_")}
            e.update({"PATH": f"{tmp / 'bin'}:{os.environ.get('PATH', '')}", "PYTHONIOENCODING": "utf-8",
                      "STUB_REAL_PYTHON": sys.executable, "STUB_CHECK": str(Path(__file__).resolve()),
                      "STUB_ARGV_LOG": str(argv_log), "SUPABASE_URL": "x", "SUPABASE_SERVICE_ROLE_KEY": "x",
                      "ANTHROPIC_API_KEY": "test-not-a-key", "ANTHROPIC_BASE_URL": "x", "FLYWHEEL_CURATOR_MODEL": "",
                      "PROJECT": "", "LIMIT": "15", "MAXB": "3", "NOTE_IDS": "", "DRY_RUN": "false"})
            e.update(kw)
            r = subprocess.run(["bash", "-e", "-c", body.replace("/tmp/r.log", str(tmp / f"r{k}.log"))],
                               cwd=HERE, env=e, capture_output=True, text=True)
            argvs = [json.loads(x) for x in argv_log.read_text(encoding="utf-8").splitlines()] if argv_log.exists() else []
            return r.returncode, r.stdout + r.stderr, argvs

        def pair(argv, flag, val):
            return any(argv[i] == flag and argv[i + 1] == val for i in range(len(argv) - 1))

        abc = "NUC_phase1_recA,NUC_phase1_recB,NUC_phase1_recC"

        rc, out, argvs = run(pick_body, NOTE_IDS=abc, PROJECT="NUC_phase1", DRY_RUN="true")
        a = argvs[0] if len(argvs) == 1 else []
        if rc != 0 or len(argvs) != 1 or "--dry-run" not in a or not pair(a, "--project", "NUC_phase1") \
                or not pair(a, "--note-ids", abc) or not pair(a, "--limit", "15"):
            fails.append(f"§5 点名步 dry_run=true: 要 rc=0、调一次、带 --dry-run / --project NUC_phase1 / --note-ids / --limit 15, "
                         f"实际 rc={rc} argv={argvs}: {out.strip()[-300:]}")
        if out.count("[dry-run] NUC_phase1_rec") != 3 or "dry_run=true" not in out or "ℹ️ dry_run" not in out or "✅" in out:
            fails.append(f"§5 点名步 dry_run=true: 要打出 3 行 [dry-run]、Found 行的 dry_run=true、ℹ️ 行, 实际: {out.strip()[-400:]}")

        rc, out, argvs = run(pick_body, NOTE_IDS=abc, DRY_RUN="false")
        a = argvs[0] if len(argvs) == 1 else []
        if rc != 0 or len(argvs) != 1 or "--dry-run" in a or "--project" in a or "✅ 点名重策展 3/3 张" not in out:
            fails.append(f"§5 点名步 dry_run=false、没给 project: 要不带 --dry-run / --project、✅ 3/3, "
                         f"实际 rc={rc} argv={argvs}: {out.strip()[-300:]}")

        rc, out, _ = run(pick_body, NOTE_IDS=abc, DRY_RUN="false", STUB_FAIL="NUC_phase1_recA,NUC_phase1_recC")
        warn = [ln for ln in out.splitlines() if ln.startswith("::warning::")]
        if rc != 0 or len(warn) != 1 or "NUC_phase1_recA" not in warn[0] or "NUC_phase1_recC" not in warn[0] \
                or "note_ids 失败 2 张" not in out or "✅" in out:
            fails.append(f"§5 点名步部分失败: 要 rc=0、一条 ::warning:: 点名 recA / recC、打出「note_ids 失败」行、没有 ✅, "
                         f"实际 rc={rc}: {out.strip()[-400:]}")

        rc, out, _ = run(pick_body, NOTE_IDS=abc, DRY_RUN="false", STUB_FAIL=abc)
        if rc == 0 or "::error::" not in out:
            fails.append(f"§5 点名步全失败要红, 实际 rc={rc}")

        rc, out, _ = run(pick_body, NOTE_IDS=abc, DRY_RUN="true", STUB_MISSING="NUC_phase1_recB")
        if rc == 0 or "::error::" not in out or "NUC_phase1_recB" not in out:
            fails.append(f"§5 点名步缺卡要红并点名缺的那张, 实际 rc={rc}: {out.strip()[-300:]}")

        rc, out, _ = run(pick_body, NOTE_IDS=abc, DRY_RUN="true", STUB_DROP_DRY="1")
        if rc == 0 or "::error::" not in out or "✅" in out or "ℹ️" in out:
            fails.append(f"§5 点名步: 输入 dry_run=true 而脚本日志是 dry_run=false, 要红 (✅ / ℹ️ 行不许回显输入), "
                         f"实际 rc={rc}: {out.strip()[-300:]}")

        stale = "NUC_phase1_recS1,NUC_phase1_recS2"
        rc, out, argvs = run(loop_body, STUB_STALE=stale, PROJECT="NUC_phase1", DRY_RUN="true", MAXB="3")
        if rc != 0 or len(argvs) != 1 or any("--dry-run" not in a or "--recurate-stale" not in a
                                             or not pair(a, "--project", "NUC_phase1") for a in argvs) \
                or "ℹ️ dry_run" not in out:
            fails.append(f"§5 循环步 dry_run=true: 要只跑一轮、带 --recurate-stale / --dry-run / --project, "
                         f"实际 rc={rc} argv={argvs}: {out.strip()[-300:]}")

        rc, out, argvs = run(loop_body, STUB_STALE=stale, DRY_RUN="false", MAXB="2")
        if rc != 0 or len(argvs) != 2 or any("--dry-run" in a or "--project" in a for a in argvs) \
                or "::warning::到达 max_batches=2" not in out:
            fails.append(f"§5 循环步 dry_run=false: 要跑满 2 轮 (假库不落写, 不收敛)、不带 --dry-run / --project, "
                         f"实际 rc={rc} argv={argvs}: {out.strip()[-300:]}")

        rc, out, _ = run(loop_body, STUB_STALE=stale, DRY_RUN="true", STUB_DROP_DRY="1")
        if rc == 0 or "::error::" not in out:
            fails.append(f"§5 循环步: 输入 dry_run=true 而脚本日志是 dry_run=false, 要红, 实际 rc={rc}")


def main() -> int:
    fails: list[str] = []
    saved = {k: getattr(cur, k) for k in ("get_supabase_client", "fetch_vanished_note_ids", "call_claude")}
    try:
        s1_read(fails)
        s2_fetch(fails)
        s3_main(fails)
        s4_default_paths(fails)
        s5_workflow(fails)
    finally:
        for k, v in saved.items():
            setattr(cur, k, v)
    for f in fails:
        print("  ❌", f)
    if fails:
        print(f"❌ curate --note-ids: {len(fails)} 条不过")
        return 1
    print("✅ curate --note-ids: §1 读名单 · §2 取数 · §3 缺卡拒跑 / dry-run / 只写点名的 / 预算截断 / 失败名单 · §4 默认路不变 · "
          "§5 workflow 入参 + 两步真跑 (argv / dry_run 取自日志 / 部分失败告警) 全过")
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--stub-curate"]:
        sys.exit(_stub_curate(sys.argv[2:]))
    sys.exit(main())
