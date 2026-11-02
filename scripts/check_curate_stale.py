#!/usr/bin/env python3
"""CI 守卫: 重策展"essence 比卡新"的那条路 (D-096, 2026-10-08 审计 B-02)。

  §1 stale_cards: 只挑 essence_annotated_at > curated_at 的; 相等 / 更早 / 缺 / 认不出 → 不挑 (不乱花钱)
  §2 时区: 带偏移的 essence 时间与 naive UTC 的 curated_at 比得对 (+08:00 的 10:00 = UTC 02:00)
  §3 fetch_uncurated_cards(stale_only=True): 只取 is_curated=true, 再按 notes.essence_annotated_at 过滤;
     默认路径仍是 is_curated=false (daily-sync 的行为一字不变)
  §4 worker /curate: recurate="stale" → --recurate-stale; "all"/true → --recurate; 省略 → 都不带; 别的 → 400
  §5 收敛前提: 重策展写回的 curated_at 是现在 (写回路径没改也要钉住: 否则 stale 永远 stale, 工作流空转烧钱)
  §6 夜跑模式 (外部审计 11-02 F02 第一期, D-137): 不带 --recurate / --recurate-stale / --note-ids 时, 先没策展过的,
     预算有剩再接上 essence 比卡新的已策展卡 (同 §3 的 stale_only 那一路); 没策展过的占满预算就不去查 essence 时间;
     main() 真走这条路 (dry-run, 日志 daily_stale=N, 两类都策展到); --daily-pass new / stale 各只取一类;
     v1_23 没跑 (notes 没有 content_sha 两列) 时 stale 那一路一张不取, 和以前一模一样; --daily-pass 不和 --recurate* 一起用
  §7 daily-sync 策展步分两遍 (复审 on 52f690e): 假 python 真跑这一步的 bash —— 先每个项目 new、再拿剩下的预算每个项目
     stale, 排在前面的项目的重策展抢不到后面项目的新卡; 预算用完点名; on_demand 两遍都跳; 没迁移时 stale 那遍见到
     「content_sha 还没建」就停
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import curate_flywheel_lessons as cur  # noqa: E402


class _Q:
    """记录 .eq / .in_ 过滤的假 query builder, 够 fetch_all_pages / in_ 查询用。"""

    def __init__(self, rows, log):
        self.rows, self.log, self.filters = rows, log, []

    def select(self, *_a, **_k): return self
    def order(self, *_a, **_k): return self
    def range(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self

    def eq(self, col, val):
        self.filters.append(("eq", col, val)); return self

    def in_(self, col, vals):
        self.filters.append(("in", col, list(vals))); return self

    def execute(self):
        out = self.rows
        for kind, col, val in self.filters:
            out = [r for r in out if (r.get(col) == val if kind == "eq" else r.get(col) in val)]
        self.log.append(list(self.filters))
        self._done = getattr(self, "_done", False)
        if self._done:        # fetch_all_pages 翻到第二页 → 空
            return type("R", (), {"data": []})()
        self._done = True
        return type("R", (), {"data": out})()


class _SB:
    def __init__(self, tables):
        self.tables, self.log = tables, []

    def schema(self, _s): return self
    def table(self, name): return _Q(self.tables[name], self.log)


def main() -> int:
    fails: list[str] = []

    # §1
    cards = [{"source_note_id": "a", "curated_at": "2026-09-01T00:00:00"},
             {"source_note_id": "b", "curated_at": "2026-09-01T00:00:00"},
             {"source_note_id": "c", "curated_at": "2026-09-01T00:00:00"},
             {"source_note_id": "d", "curated_at": None},
             {"source_note_id": "e", "curated_at": "2026-09-01T00:00:00"}]
    ess = {"a": "2026-09-02T00:00:00", "b": "2026-09-01T00:00:00", "c": "2026-08-01T00:00:00",
           "d": "2026-10-01T00:00:00", "e": "not a date"}
    got = {c["source_note_id"] for c in cur.stale_cards(cards, ess)}
    if got != {"a"}:
        fails.append(f"§1 只有 a 的 essence 比卡新, 实际挑了 {sorted(got)}")

    # §2
    tz_cards = [{"source_note_id": "x", "curated_at": "2026-09-01T03:00:00"}]
    if cur.stale_cards(tz_cards, {"x": "2026-09-01T10:00:00+08:00"}):
        fails.append("§2 +08:00 的 10:00 = UTC 02:00 < 03:00, 不该算新")
    if not cur.stale_cards(tz_cards, {"x": "2026-09-01T12:00:00+08:00"}):
        fails.append("§2 +08:00 的 12:00 = UTC 04:00 > 03:00, 该算新")

    # §3
    view = [{"source_note_id": "n1", "is_curated": True, "curated_at": "2026-09-01T00:00:00", "rank_score": 1},
            {"source_note_id": "n2", "is_curated": True, "curated_at": "2026-09-05T00:00:00", "rank_score": 0.9},
            {"source_note_id": "n3", "is_curated": False, "curated_at": None, "rank_score": 0.8}]
    notes = [{"note_id": "n1", "essence_annotated_at": "2026-09-03T00:00:00"},
             {"note_id": "n2", "essence_annotated_at": "2026-09-03T00:00:00"},
             {"note_id": "n3", "essence_annotated_at": "2026-09-03T00:00:00"}]
    sb = _SB({"v_flywheel_lesson_cards": view, "notes": notes, "v_notes_vanished": []})
    got3 = [c["source_note_id"] for c in cur.fetch_uncurated_cards(sb, None, True, stale_only=True)]
    if got3 != ["n1"]:
        fails.append(f"§3 stale_only 应只回 n1 (已策展且 essence 更新), 实际 {got3}")
    if not any(("eq", "is_curated", True) in f for f in sb.log):
        fails.append("§3 stale_only 必须先按 is_curated=true 取 (别把未策展的也拉下来)")
    sb2 = _SB({"v_flywheel_lesson_cards": view, "notes": notes, "v_notes_vanished": []})
    got_default = [c["source_note_id"] for c in cur.fetch_uncurated_cards(sb2, None, False)]
    if got_default != ["n3"] or not any(("eq", "is_curated", False) in f for f in sb2.log):
        fails.append(f"§3 默认路径仍该只取 is_curated=false → n3, 实际 {got_default}")
    if any(("in", "note_id", ["n3"]) in f for f in sb2.log):
        fails.append("§3 默认路径不该去查 notes.essence_annotated_at")

    # §4
    try:
        import worker.app as w
        from fastapi.testclient import TestClient
    except ImportError as exc:                       # 本地 venv 没装 fastapi: CI 装了, 这里说清而不是假装过
        print(f"  ⚠️ §4 跳过 (import 失败: {exc}); CI 的 python job 装了 worker 依赖, 那里会跑")
        w = None
    if w is not None:
        seen: list[list[str]] = []
        w._run = lambda script, args: seen.append(list(args)) or {"ok": True, "returncode": 0, "stdout_tail": "", "stderr_tail": ""}
        w._check_auth = lambda *_a, **_k: None
        c = TestClient(w.app)
        for body, want in [({"limit": 3, "recurate": "stale"}, ["--recurate-stale"]),
                           ({"limit": 3, "recurate": "all"}, ["--recurate"]),
                           ({"limit": 3, "recurate": True}, ["--recurate"]),
                           ({"limit": 3}, [])]:
            r = c.post("/curate", json=body)
            if r.status_code != 200:
                fails.append(f"§4 {body} → HTTP {r.status_code}: {r.text[:120]}"); continue
            flags = [a for a in seen[-1] if a.startswith("--recurate")]
            if flags != want:
                fails.append(f"§4 {body} → 期望 {want}, 实际 {flags}")
        r = c.post("/curate", json={"limit": 3, "recurate": "yes"})
        if r.status_code != 400:
            fails.append(f"§4 recurate='yes' 该 400, 实际 {r.status_code}")

    # §5
    import inspect
    src = inspect.getsource(cur.write_lesson_back)
    if '"curated_at": _iso_now()' not in src:
        fails.append("§5 写回必须把 curated_at 置为现在, 否则 stale 永远 stale、重策展工作流空转烧钱")

    # §6 夜跑模式: 正文改了 → essence 按新正文重标 (essence_annotated_at 变新) → 这张卡按旧正文策展的, 夜跑要重策展它。
    #    反证: fetch_daily_cards 只回没策展过的 (以前的行为) → 下面第一条红; 把 stale 排到没策展的前面 → 顺序那条红。
    # v1_23 跑过: notes 上有 content_sha 两列 (notes_content_sha_supported 探的就是这个)
    notes_old = notes
    notes = [dict(n, content_sha="s", essence_content_sha="s") for n in notes_old]
    sb6 = _SB({"v_flywheel_lesson_cards": view, "notes": notes, "v_notes_vanished": []})
    got6 = [c["source_note_id"] for c in cur.fetch_daily_cards(sb6, None)]
    if got6 != ["n3", "n1"]:
        fails.append(f"§6 夜跑应先 n3 (没策展过) 再 n1 (essence 比卡新), n2 (卡比 essence 新) 不取; 实际 {got6}")
    sb6 = _SB({"v_flywheel_lesson_cards": view, "notes": notes, "v_notes_vanished": []})
    got6 = [c["source_note_id"] for c in cur.fetch_daily_cards(sb6, None, limit=1)]
    if got6 != ["n3"] or any(f and f[0][:2] == ("in", "note_id") for f in sb6.log):
        fails.append(f"§6 没策展过的占满预算 (limit=1) 就不该再查 essence 时间: {got6} / {sb6.log}")
    only_curated = [r for r in view if r["is_curated"]]
    sb6 = _SB({"v_flywheel_lesson_cards": only_curated, "notes": notes, "v_notes_vanished": []})
    got6 = [c["source_note_id"] for c in cur.fetch_daily_cards(sb6, None, limit=5)]
    if got6 != ["n1"]:
        fails.append(f"§6 没有没策展过的卡时, 夜跑照样重策展 essence 比卡新的那张: 期望 ['n1'], 实际 {got6}")
    import io
    import logging
    sb6 = _SB({"v_flywheel_lesson_cards": view, "notes": notes, "v_notes_vanished": []})
    saved_client = cur.get_supabase_client
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    cur.logger.addHandler(h)
    try:
        cur.get_supabase_client = lambda: sb6
        rc = cur.main(["--limit", "5", "--dry-run", "--qps", "0"])
    finally:
        cur.get_supabase_client = saved_client
        cur.logger.removeHandler(h)
    out = buf.getvalue()
    if rc != 0 or "Found 2 card(s)" not in out or "daily_stale=1" not in out or '"ok": 2' not in out:
        fails.append(f"§6 main() 夜跑模式该策展 2 张 (1 张没策展过 + 1 张 essence 比卡新): rc={rc} {out[-400:]}")
    if "'_stale'" in out or any("_stale" in c for c in view):
        fails.append("§6 内部标记 _stale 漏进了日志 / 候选行 (它只给日志数数用)")
    for which, want in (("new", ["n3"]), ("stale", ["n1"])):
        sb6 = _SB({"v_flywheel_lesson_cards": view, "notes": notes, "v_notes_vanished": []})
        got6 = [c["source_note_id"] for c in cur.fetch_daily_cards(sb6, None, limit=5, which=which)]
        if got6 != want:
            fails.append(f"§6 --daily-pass {which} 应只取 {want}, 实际 {got6}")
    # v1_23 没跑 (notes 上没有那两列): 夜跑策展和以前一模一样 —— 只取没策展过的, essence 比卡新的不碰 (复审 on 52f690e:
    # 以前这一路没看迁移, 迁移之前就会多重策展一张 essence 被清过时间的卡)。反证: 去掉 notes_content_sha_supported 那一条 → 红
    for which, want in (("both", ["n3"]), ("stale", [])):
        sb6 = _SB({"v_flywheel_lesson_cards": view, "notes": notes_old, "v_notes_vanished": []})
        got6 = [c["source_note_id"] for c in cur.fetch_daily_cards(sb6, None, limit=5, which=which)]
        if got6 != want:
            fails.append(f"§6 两列不在时 (v1_23 没跑) --daily-pass {which} 应 = {want} (和以前一样), 实际 {got6}")
    for bad in (["--recurate"], ["--recurate-stale"], ["--note-ids", "n1"]):
        if cur.main(["--limit", "5", "--dry-run", "--daily-pass", "stale"] + bad) != 2:
            fails.append(f"§6 --daily-pass 和 {bad[0]} 一起用应退 2")

    # §7 daily-sync 策展步: 假 python 真跑这一步的 bash
    fails += _check_two_pass_loop()

    for f in fails:
        print("  ❌", f)
    if fails:
        print(f"❌ curate stale: {len(fails)} 条不过")
        return 1
    print("✅ curate stale: §1 挑选 · §2 时区 · §3 取数 · §4 worker 映射 · §5 收敛前提 · §6 夜跑先新卡再重策展过期卡"
          "(没迁移照旧) · §7 daily-sync 两遍 (全局先新卡) 全过")
    return 0


# 假 python: skip_on_cron.py 对 Z_ondemand 回 0 (= on_demand, 跳过), 别的回 1 (照跑); curate_flywheel_lessons.py 记下
# (遍, 项目, 预算), 从 $STOCK 里取这个项目这一遍有几张卡, 策展 min(有的, 预算) 张, 打 Done 行。$NO_SHA 非空 = v1_23 没跑:
# stale 那遍打「content_sha 还没建」、0 张。
_FAKE_PY = r'''
python() {
  case "$1" in
    skip_on_cron.py) [ "$2" = "Z_ondemand" ] && return 0; return 1 ;;
    curate_flywheel_lessons.py)
      shift
      local p="" lim="" pass="" have n
      while [ $# -gt 0 ]; do
        case "$1" in --project) p=$2; shift 2 ;; --limit) lim=$2; shift 2 ;; --daily-pass) pass=$2; shift 2 ;; *) shift ;; esac
      done
      echo "$pass $p $lim" >> "$CALLS"
      have=$(awk -v k="$pass:$p" '$1 == k {print $2}' "$STOCK"); have=${have:-0}
      n=$(( have < lim ? have : lim ))
      if [ "$pass" = "stale" ] && [ -n "$NO_SHA" ]; then echo "⚠️ notes.content_sha 还没建 (假)" >&2; n=0; fi
      echo "Done: {\"ok\": $n, \"ok_after_retry\": 0, \"failed\": 0}"
      return 0 ;;
  esac
  return 2
}
'''


def _check_two_pass_loop() -> list[str]:
    import subprocess
    import tempfile

    import yaml
    out: list[str] = []
    wf = yaml.safe_load((HERE.parent / ".github" / "workflows" / "daily-sync.yml").read_text(encoding="utf-8"))
    runs = [st.get("run") or "" for job in wf["jobs"].values() for st in job.get("steps", [])]
    body = next((r for r in runs if "python curate_flywheel_lessons.py" in r), "")
    if '--daily-pass "$pass"' not in body or "for pass in new stale" not in body:
        return ["§7 daily-sync 策展步要分两遍跑 (for pass in new stale + --daily-pass \"$pass\")"]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "scripts").mkdir()
        (root / "mappings").mkdir()
        for p in ("A_p", "B_p", "C_p", "Z_ondemand", "_template"):
            (root / "mappings" / f"{p}.yaml").write_text("x: 1\n", encoding="utf-8")
        script = body.replace("${{ github.event.inputs.dry_run }}", "").replace("/tmp/cur.log", str(root / "cur.log"))

        def run(stock: str, limit: int, no_sha: bool = False):
            (root / "stock").write_text(stock, encoding="utf-8")
            calls = root / "calls"
            calls.write_text("", encoding="utf-8")
            env = dict(os.environ, CALLS=str(calls), STOCK=str(root / "stock"), WORKER_LIMIT=str(limit),
                       PROJECT_FILTER="", FLYWHEEL_CURATOR_MODEL="", NO_SHA="1" if no_sha else "")
            p = subprocess.run(["bash", "-e", "-c", _FAKE_PY + "\n" + script], cwd=root / "scripts", env=env,
                               capture_output=True, text=True, timeout=60)
            return p.returncode, p.stdout + p.stderr, calls.read_text(encoding="utf-8").split("\n")[:-1]

        # A 排在前面、有 3 张 essence 比卡新的; C 排在后面、有 2 张新卡; 预算 4。一遍跑: A 先重策展 3 张, C 只剩 1 张预算。
        # 两遍: C 的 2 张新卡先上, A 再拿剩下的 2 张重策展; B / C 的重策展点名留到下轮
        rc, log, calls = run("stale:A_p 3\nnew:C_p 2\nstale:C_p 1\n", 4)
        if rc != 0 or calls != ["new A_p 4", "new B_p 4", "new C_p 4", "stale A_p 2"]:
            out.append(f"§7 两遍的顺序 / 预算不对: rc={rc} calls={calls} {log[-300:]}")
        if "重策展 (essence 比卡新的卡) 留到下轮 cron: B_p C_p" not in log:
            out.append(f"§7 重策展那遍预算用完要点名留到下轮的项目: {log[-300:]}")
        if log.count("⏭  Z_ondemand") != 1 or any("Z_ondemand" in c for c in calls):
            out.append(f"§7 on_demand 项目两遍都不跑、跳过的提示只打一次: calls={calls}")
        # 没迁移: stale 那遍第一个项目就见到「content_sha 还没建」, 整遍停, 不点名留到下轮
        rc, log, calls = run("stale:A_p 3\nnew:C_p 2\n", 15, no_sha=True)
        if rc != 0 or calls != ["new A_p 15", "new B_p 15", "new C_p 15", "stale A_p 13"] \
                or "content_sha 还没建 (v1_23 没跑)" not in log or "留到下轮" in log:
            out.append(f"§7 没迁移时 stale 那遍见到 warning 就停: rc={rc} calls={calls} {log[-300:]}")
    return out


if __name__ == "__main__":
    os.environ.setdefault("AW_DISABLE_ST_CACHE", "1")
    sys.exit(main())
