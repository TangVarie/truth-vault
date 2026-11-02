#!/usr/bin/env python3
"""CI 守卫: 正文改了 → essence 重标 (外部审计 11-02 F02 第一期, D-137; schemas/notes_v1_23_content_sha.sql)。

  §1 指纹: _common.content_sha 对 check_content_sha_cases.json 每一条都等于记下的 sha (CI sql job 拿同一份文件对
     truth_vault.tv_content_sha, 两边逐条相等); 同组 (只改空白 / 标点 / #话题 / 全角空格 / 零宽字符) 指纹相同,
     不同组 (改一个字、换表情、整段重写、加标题) 指纹不同; 两边的字符类里没有字面的非 ASCII 字符 (都写成 \\uXXXX,
     粘贴进 SQL editor 不会丢)
  §2 选取 (两列在): fetch_unannotated_notes 默认路 = 没标过的 + 正文改过的 (essence_content_sha ≠ content_sha), 没标过的
     排前面; 只改空白 / 话题的不选; 正文改过又改回来的不选; --reannotate / --only-missing-subtype 不叠加过期那一路;
     count_remaining = 没标过的 + 过期的 (daily-sync 见 0 就跳过项目, 不数过期的就永远轮不到)
  §3 main() 真走一遍 (假 LLM): 写回带 essence_content_sha = 取数时那一行的 content_sha; --limit 1 只标没标过的那篇;
     标完 (essence_content_sha 追上 content_sha) 下一轮不再选中 —— 收敛
  §4 两列不在 (v1_23 没跑): 取数 / 计数 / 写回都和以前一样 (只取没标过的、不写 essence_content_sha), warning 只打一次;
     别的错 (连不上) 照抛, 不当成「没迁移」悄悄降级
  §5 daily-sync 接线: essence 步仍是 count_unannotated_essence 判 0 跳过 + annotate_essence_pass --limit "$WORKER_LIMIT"
     (同一份日预算), 日志 grep 带上「content_sha 还没建」那一行
夜跑策展重策展「essence 比卡新」的卡在 check_curate_stale.py §6。

反证 (改坏输入): content_sha 里去掉去话题那一步 → §1 同组不等红; fetch_unannotated_notes 去掉过期那一路 → §2 / §3 红;
count_remaining 不加过期的 → §2 红; write_essence_back 不写 essence_content_sha → §3 红; notes_content_sha_supported 吞掉所有
异常 → §4「连不上照抛」红。
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import _common as C  # noqa: E402
import annotate_essence_pass as E  # noqa: E402
import count_unannotated_essence as K  # noqa: E402


# ── 假 Supabase: 够 fetch_all_pages / in_ / count / update 用; 选了不存在的列时按 PostgREST 的样子抛 42703 ──
class _Missing(Exception):
    pass


class _Q:
    def __init__(self, db, table):
        self.db, self.table, self.cols, self.filters = db, table, "*", []
        self._neg, self._rng, self._lim, self._count, self._update = False, None, None, None, None

    def select(self, cols="*", count=None):
        self.cols, self._count = cols, count
        if not self.db.has_sha and any(c in cols for c in ("content_sha", "essence_content_sha")):
            bad = "content_sha" if "content_sha" in cols.replace("essence_content_sha", "") else "essence_content_sha"
            raise _Missing(f"{{'code': '42703', 'message': 'column notes.{bad} does not exist'}}")
        if self.db.boom:
            raise ConnectionError("PostgREST down")
        return self

    def eq(self, c, v): self.filters.append(lambda r: r.get(c) == v); return self

    def in_(self, c, vs):
        s = set(vs)
        self.filters.append(lambda r: r.get(c) in s)
        return self

    @property
    def not_(self):
        self._neg = True
        return self

    def is_(self, c, v):
        neg, self._neg = self._neg, False
        self.filters.append((lambda r: r.get(c) is not None) if neg else (lambda r: r.get(c) is None))
        return self

    def order(self, *a, **k): return self
    def limit(self, n): self._lim = n; return self
    def range(self, a, b): self._rng = (a, b); return self

    def update(self, payload):
        self._update = payload
        return self

    def execute(self):
        rows = sorted((r for r in self.db.tables[self.table] if all(f(r) for f in self.filters)),
                      key=lambda r: r["note_id"])       # 取数都按 note_id 排 (fetch_all_pages 的 order_by)
        if self._update is not None:
            if not self.db.has_sha and "essence_content_sha" in self._update:
                raise _Missing("{'code': 'PGRST204', 'message': \"Could not find the 'essence_content_sha' column\"}")
            for r in rows:
                r.update(self._update)
            self.db.writes.append(dict(self._update))
            return type("R", (), {"data": rows, "count": None})()
        total = len(rows)
        if self._rng is not None:
            rows = rows[self._rng[0]:self._rng[1] + 1]
        if self._lim is not None:
            rows = rows[:self._lim]
        out = []
        for r in rows:
            d = dict(r)
            if not self.db.has_sha:
                d.pop("content_sha", None)
                d.pop("essence_content_sha", None)
            out.append(d)
        return type("R", (), {"data": out, "count": total if self._count == "exact" else None})()


class _SB:
    def __init__(self, notes, has_sha=True):
        self.tables = {"notes": notes}
        self.has_sha, self.boom, self.writes = has_sha, False, []

    def schema(self, _s): return self
    def table(self, t): return _Q(self, t)


def _note(nid, raw, essence_raw=None, annotated=True, title=None, essence_title="same"):
    """content_sha 模拟生成列 (用 Python 同一份); essence_content_sha = 标的时候那份标题 + 正文的指纹。"""
    r = {"note_id": nid, "project_id": "P", "title": title, "raw_content": raw, "body": None, "hashtags": None,
         "intent": None, "target_blue_keywords": None, "raw_extra": {}, "projects": {"brand": "b"},
         "content_sha": C.content_sha(title, raw), "essence_annotated_at": None, "essence_content_sha": None}
    if annotated:
        r["essence_annotated_at"] = "2026-10-20T00:00:00"
        r["essence_content_sha"] = C.content_sha(title if essence_title == "same" else essence_title,
                                                 raw if essence_raw is None else essence_raw)
    return r


def _fixture():
    return [
        _note("P_a_fresh", "正文没动过"),
        _note("P_b_rewrite", "飞书里整段改写过的新正文", essence_raw="排期时写的旧正文"),
        _note("P_c_ws_only", "维生素D 每天吃多少?\n#维生素", essence_raw="维生素D每天吃多少？ #维生素[话题]# #补钙"),
        _note("P_d_never", "还没标过的一篇", annotated=False),
        _note("P_e_title", "正文没动", title="后来加的标题", essence_title=None),   # 标的时候还没有标题
        _note("P_f_reverted", "改了又改回来的正文"),   # 审计里有过中间版本, 但现在和标的时候一样
        _note("P_0_never2", "另一篇没标过的", annotated=False),
    ]


GOOD = {"essence": {"emotional_lever": "好奇驱动", "emotional_valence": "neutral", "emotional_intensity": "low",
                    "human_truth_archetype": None, "trend_dependencies": [], "content_format": None},
        "audience": {}}


def main() -> int:
    fails: list[str] = []

    # §1 指纹
    cases = json.loads((HERE / "check_content_sha_cases.json").read_text(encoding="utf-8"))
    by_group: dict[str, set] = {}
    for c in cases:
        got = C.content_sha(c["title"], c["raw_content"])
        if got != c["sha"]:
            fails.append(f"§1 {c['label']}: Python 指纹 {got} ≠ 记下的 {c['sha']} (改规则 = 新迁移, 见 v1_23 文件头)")
        by_group.setdefault(c["group"], set()).add(got)
    for g, shas in by_group.items():
        if len(shas) != 1:
            fails.append(f"§1 组 {g} 只改了空白 / 标点 / 话题, 指纹应相同, 实际 {len(shas)} 个")
    firsts = [next(iter(s)) for s in by_group.values()]
    if len(set(firsts)) != len(firsts):
        fails.append("§1 不同组 (改字 / 换表情 / 重写 / 加标题) 的指纹撞了")
    if C.content_sha_text("T", "a #tag b") != "Tab":
        fails.append(f"§1 归一化顺序不对: {C.content_sha_text('T', 'a #tag b')!r}")
    # 两个字符类里不许出现 ASCII 以外的字面字符 (都写成 \uXXXX): owner 是粘贴进 SQL editor 跑的, 不换行空格 / 零宽 / 行分隔这类
    # 一被编辑器吞掉或换掉, 范围就悄悄变了, 两边仍各自自洽, 上面的夹具也看不出来 (复审 on 52f690e)。
    sql_fn = (HERE.parent / C.CONTENT_SHA_MIGRATION).read_text(encoding="utf-8")
    sql_fn = sql_fn[sql_fn.index("AS $fn$"):sql_fn.index("$fn$;")]
    for name, pat in (("CONTENT_SHA_HASHTAG", C.CONTENT_SHA_HASHTAG), ("CONTENT_SHA_STRIP", C.CONTENT_SHA_STRIP),
                      ("v1_23 tv_content_sha 的两个字符类", sql_fn.replace("话题", ""))):
        raw = [f"U+{ord(ch):04X}" for ch in pat if ord(ch) > 127]
        if raw:
            fails.append(f"§1 {name} 里有字面的非 ASCII 字符 {raw[:5]}: 写成 \\uXXXX")

    # §2 选取 (两列在)
    sb = _SB(_fixture())
    got = [n["note_id"] for n in E.fetch_unannotated_notes(sb, "P", False)]
    want = ["P_0_never2", "P_d_never", "P_b_rewrite", "P_e_title"]
    if got != want:
        fails.append(f"§2 默认路应 = 没标过的 (在前) + 正文改过的 {want}, 实际 {got} "
                     "(只改空白 / 话题的 P_c、改回来的 P_f、没动的 P_a 都不该选)")
    rows = E.fetch_unannotated_notes(_SB(_fixture()), "P", False)
    if any("content_sha" not in n for n in rows):
        fails.append("§2 两列在的时候, 取回来的每一行都要带 content_sha (写回要用)")
    if [n["note_id"] for n in E.fetch_unannotated_notes(_SB(_fixture()), "P", False, include_stale=False)] \
            != ["P_0_never2", "P_d_never"]:
        fails.append("§2 include_stale=False 只要没标过的")
    if len(E.fetch_unannotated_notes(_SB(_fixture()), "P", True)) != len(_fixture()):
        fails.append("§2 --reannotate 全部重来, 不该再叠一遍过期的 (会重复)")
    if E.fetch_stale_essence_ids(_SB(_fixture()), "P") != ["P_b_rewrite", "P_e_title"]:
        fails.append(f"§2 fetch_stale_essence_ids 应 = P_b / P_e, 实际 {E.fetch_stale_essence_ids(_SB(_fixture()), 'P')}")
    sb = _SB(_fixture())
    with patch.object(K, "get_supabase_client", return_value=sb):
        n = K.count_remaining("P")
    if n != 4:
        fails.append(f"§2 count_remaining 应 = 没标过的 2 + 过期的 2 = 4 (daily-sync 见 0 就跳过项目), 实际 {n}")

    # §3 main() 真走一遍
    import logging

    def run_main(sb, limit):
        argv = ["annotate_essence_pass.py", "P", "--qps", "0", "--limit", str(limit),
                "--failed-queue", os.devnull]
        buf = io.StringIO()
        h = logging.StreamHandler(buf)      # logger 的 handler 在 import 时就绑了 stdout, redirect 抓不到, 另挂一个
        E.logger.addHandler(h)
        with (patch.object(sys, "argv", argv),
              patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-not-used"}),
              patch.object(E, "load_mapping", return_value={}),
              patch.object(E, "get_supabase_client", return_value=sb),
              patch.object(E, "_annotate_with_retry", return_value=(GOOD, [], "", False)),
              contextlib.redirect_stdout(buf)):
            try:
                rc = E.main()
            finally:
                E.logger.removeHandler(h)
        return rc, buf.getvalue()

    db = _fixture()
    sb = _SB(db)
    rc, out = run_main(sb, 1)
    if rc != 0 or len(sb.writes) != 1 or sb.writes[0].get("essence_content_sha") != C.content_sha(None, "另一篇没标过的"):
        fails.append(f"§3 --limit 1: 只标没标过的第一篇、写回带它的 content_sha; rc={rc} writes={sb.writes}")
    rc, out = run_main(sb, 10)
    rew = next(r for r in db if r["note_id"] == "P_b_rewrite")
    if rc != 0 or len(sb.writes) != 4 or rew["essence_content_sha"] != rew["content_sha"]:
        fails.append(f"§3 --limit 10: 剩下 1 篇没标过的 + 2 篇过期的都标, 过期的写回之后指纹追上 content_sha; "
                     f"rc={rc} writes={len(sb.writes)}")
    if "content_changed=2" not in out:
        fails.append(f"§3 Found 行要报这一轮里正文改过的篇数 (content_changed=2): {out[-300:]}")
    if any("_essence_stale" in w for w in sb.writes):
        fails.append("§3 内部标记 _essence_stale 不能写进库")
    if [n["note_id"] for n in E.fetch_unannotated_notes(sb, "P", False)]:
        fails.append("§3 标完之后下一轮应该一篇都不选 (收敛)")
    # 只改空白 / 话题: 生成列不变 → 不选
    ws = next(r for r in db if r["note_id"] == "P_a_fresh")
    ws["raw_content"] = "正文 没动过 #新加的话题"
    ws["content_sha"] = C.content_sha(None, ws["raw_content"])
    if E.fetch_unannotated_notes(sb, "P", False):
        fails.append("§3 只加了空格和话题标签: 不该重标")
    ws["raw_content"] = "正文改动过"
    ws["content_sha"] = C.content_sha(None, ws["raw_content"])
    if [n["note_id"] for n in E.fetch_unannotated_notes(sb, "P", False)] != ["P_a_fresh"]:
        fails.append("§3 正文真改了一个词: 要重标")

    # §4 两列不在
    C._CONTENT_SHA_WARNED.clear()
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        sb = _SB(_fixture(), has_sha=False)
        got = E.fetch_unannotated_notes(sb, "P", False)
        with patch.object(K, "get_supabase_client", return_value=sb):
            n = K.count_remaining("P")
        rc, out = run_main(sb, 10)
    if [r["note_id"] for r in got] != ["P_0_never2", "P_d_never"] or any("content_sha" in r for r in got):
        fails.append(f"§4 没迁移: 只取没标过的、不带 content_sha, 实际 {[r['note_id'] for r in got]}")
    if n != 2:
        fails.append(f"§4 没迁移: count_remaining 只数没标过的 (2), 实际 {n}")
    if rc != 0 or len(sb.writes) != 2 or any("essence_content_sha" in w for w in sb.writes):
        fails.append(f"§4 没迁移: 照常标没标过的 2 篇、不写 essence_content_sha; rc={rc} writes={sb.writes}")
    if err.getvalue().count("content_sha 还没建") != 1:
        fails.append(f"§4 没迁移的 warning 一个进程只打一次, 实际 {err.getvalue().count('content_sha 还没建')} 次")
    sb = _SB(_fixture())
    sb.boom = True
    try:
        C.notes_content_sha_supported(sb)
        fails.append("§4 连不上 (不是「没有这一列」) 要照抛, 不能当成没迁移悄悄降级")
    except ConnectionError:
        pass
    sb_w = _SB(_fixture(), has_sha=False)
    E.write_essence_back(sb_w, "P_d_never", "m", GOOD, None, dry_run=False)
    if sb_w.writes and "essence_content_sha" in sb_w.writes[0]:
        fails.append("§4 不给 content_sha 时写回不该带 essence_content_sha")
    sb_w = _SB(_fixture())
    E.write_essence_back(sb_w, "P_d_never", "m", GOOD, None, dry_run=False, content_sha="abc")
    if sb_w.writes[-1].get("essence_content_sha") != "abc":
        fails.append("§4 给了 content_sha 写回要带上 essence_content_sha")
    if "content_sha" in C._REQUIRED_COLUMNS["notes"] or "essence_content_sha" in C._REQUIRED_COLUMNS["notes"]:
        fails.append("§4 两列不能进 _REQUIRED_COLUMNS: 迁移没跑之前 sync 会先红 (D-137 要求代码先能在没迁移的库上跑)")

    # §5 daily-sync 接线
    wf = (HERE.parent / ".github" / "workflows" / "daily-sync.yml").read_text(encoding="utf-8")
    i = wf.find("python annotate_essence_pass.py")
    step = wf[wf.rfind("- name:", 0, i):wf.find("- name:", i)]
    for needle in ('python count_unannotated_essence.py "$p"', '[ "$rem" = "0" ]',
                   'python annotate_essence_pass.py "$p" --limit "$WORKER_LIMIT"', "content_sha 还没建"):
        if needle not in step:
            fails.append(f"§5 daily-sync 的 essence 步里找不到 {needle!r} (同一份日预算 / 计数判 0 跳过 / 没迁移的提示要露出来)")
    if not (HERE.parent / C.CONTENT_SHA_MIGRATION).is_file():
        fails.append(f"§5 {C.CONTENT_SHA_MIGRATION} 不在仓里, 提示里让 owner 跑的文件对不上")

    for f in fails:
        print("  ❌", f)
    if fails:
        print(f"❌ content_sha: {len(fails)} 条不过")
        return 1
    print("✅ content_sha (D-137): §1 指纹 · §2 选取 + 计数 · §3 main 写回 + 收敛 · §4 没迁移照旧 · §5 daily-sync 接线 全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
