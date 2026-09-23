"""
gate1_agreement.py
═══════════════════════════════════════════════════════════════════════════

闸一「测得准」: 逐题算 Jev (三张表) 与 TV 模型 (默认 run_tag=primary, extractor llm:*) 的
一致率与 Cohen's κ, 顺带 Jev–Jev 重叠 (A–B / A–C) —— docs/28 §6.1、D-079 §5、D-081。
D-082 之后多一列 owner: 裁过的格子里 TV / Jev 各对了几个 (extractor human:owner)。
--retest-json 再多一节: 同一个 TV 模型两次跑 (比如 v1 题面的 primary 和 v2 题面的 gate1-v2)
在【没改的题】上自己和自己的一致率 —— 这是模型自身的抖动, 读分歧前先看它。

    python gate1_agreement.py                          # 直接读库 (要 service key; 走表 API, 不要 RPC)
    python gate1_agreement.py --from-json pivot.json   # 读 MCP / SQL 编辑器导出的 pivot
    python gate1_agreement.py ... --out data-analysis/gate1-jev-vs-tv-2026-09-23.md
    python gate1_agreement.py --print-sql --tv-run-tag gate1-v2 --tv-bank-sha 3519081c   # 升版重跑的 TV
    python gate1_agreement.py --from-json v2.json --retest-json v1.json                  # 加 TV 自检一节

**先钉死快照, 再算** (docs/28 §7 附录 B.3 的纪律, codex review on #154):
  · TV 那一边只认【一个】(extractor, bank_sha256) 快照。同一 run_tag 下若混着两个抽取器、
    或题库升版前后两份 (bank_sha256 不同), 本脚本直接退出并列出看到的快照, 让你用
    --tv-extractor / --tv-bank-sha 钉住一个; 不会拿 max() 把两份悄悄并成一份。
  · 同一题在一个快照里只能有一个 question_version; 一个快照里 (篇, 题) 只能有一行。
  · Jev 那一边只看三张表的 extractor (jev:1.13.0-A/B/C), 同一 run_tag 下别的 extractor
    (9/28 的 human:<姓名>) 不进来也不搅局; Jev 重跑落新的 run_tag 就用 --jev-run-tag /
    --jev-bank-sha 钉住。owner 裁决 (human:owner) 单独按 --owner-run-tag 取, 与 Jev 解耦。
  · 同一 run_tag 下【不同题】版本不同是正常的 (D-082 五题升到 2, 其余 1), 报告顶部列出来。
  · run_tag 写进 pivot 每一行 (tv_run_tag / jev_run_tag), 报告表头从 pivot 里读, 不信命令行;
    --from-json 时命令行给的和 pivot 里的不一致 → 退出。

pivot 的形状 (SQL 见 pivot_sql; 读库路径由 pivot_rows 在 Python 里算出**同一形状**):
  每行 {subject_id, question_id, a, b, c, owner, jev_run_tag, jev_versions, jev_shas,
        tv, tv_invalid, tv_version, tv_n, tv_snapshots, tv_run_tag}
  a/b/c = 三张表的答案 (没标这篇就 null), owner = 裁决 (只有当时的分歧格有), tv = TV 模型答案
  (null = 没跑或校验没过), tv_snapshots = 这格 TV 侧看到的 "extractor@sha前8#v版本" 列表,
  tv_n = TV 侧行数 (>1 就是混了)。旧导出没有后面几列也能算, 只是钉不了快照 (报告里会写明)。

口径 (老实写):
  · 一致率 = 两边都有答案的格子里答案相同的比例; κ = Cohen's κ, **任一边取值只有一种时
    κ 没有定义** → 报「不可算」, 不写 1.00 也不写 0 (一边全「否」时数学上 κ 恰好 = 0,
    但那是"另一边有没有偶尔说是"决定的, 不是一致性)。
  · 「Jev 合并」= 一篇有两张表答了取一致的 (不一致记争议、不计), 只有一张表答的直接用。
    这就是 D-079 §5.3 给人的算法, 现在给 Jev。
  · TV 校验没过的格子 (invalid_reason 非空) 不算不一致, 单独数出来 —— 它是"模型没答", 不是"答错"。
  · owner 那一列只数【两边都答了】的裁决格: TV 没答 / Jev 三张表争议的格子不算进 n, 另记「没答 k」;
    否则 n − TV对 − Jev对 会把"没答"当成"都不对" (codex-style review on #155 之前的自查)。
  · 通过线沿用 docs/28 §6.1: 一致率 ≥ 0.85 且 κ ≥ 0.60。**这是模型 vs 模型**, 两个模型在
    题面歧义处一起错的看不出来 (D-081)。owner 那一列只覆盖裁过的格子, 不是整体准确率。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import feature_bank as fb
from gate1_labels import SHORT

RUN_TAG_JEV = "gate1-20260928"
RUN_TAG_OWNER = "gate1-20260928"
RUN_TAG_TV_DEFAULT = "primary"
OWNER_EXTRACTOR = "human:owner"
JEV_EXTRACTORS = {"a": "jev:1.13.0-A", "b": "jev:1.13.0-B", "c": "jev:1.13.0-C"}
PASS_AGREE = 0.85
PASS_KAPPA = 0.60

_RUN_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$")   # 同 worker / annotate_feature_pass
_EXTRACTOR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,79}$")  # 同 worker 的 model 正则加 'llm:' 前缀
_SHA_RE = re.compile(r"^[0-9a-f]{8,64}$")
_MAX_ROWS_PER_REQUEST = 1000   # PostgREST max-rows; 单次请求拿满就是被钳了, 不能当"取全了"


class Pins:
    """五个旋钮, 全部会拼进 SQL 字面量 / PostgREST 过滤器, 只放行闭集正则内的值。"""

    def __init__(self, tv_run_tag: str = RUN_TAG_TV_DEFAULT, tv_extractor: str | None = None,
                 tv_bank_sha: str | None = None, jev_run_tag: str = RUN_TAG_JEV,
                 jev_bank_sha: str | None = None, owner_run_tag: str = RUN_TAG_OWNER):
        for name, tag in (("tv_run_tag", tv_run_tag), ("jev_run_tag", jev_run_tag), ("owner_run_tag", owner_run_tag)):
            if not _RUN_TAG_RE.match(tag or ""):
                raise SystemExit(f"{name} {tag!r} 不合 [A-Za-z0-9][A-Za-z0-9_.-]{{0,39}}")
        if tv_extractor is not None and not (tv_extractor.startswith("llm:") and _EXTRACTOR_RE.match(tv_extractor)):
            raise SystemExit(f"tv_extractor {tv_extractor!r} 要是 llm:<model>, 且合 [A-Za-z0-9][A-Za-z0-9_.:/-]{{0,79}}")
        for name, sha in (("tv_bank_sha", tv_bank_sha), ("jev_bank_sha", jev_bank_sha)):
            if sha is not None and not _SHA_RE.match(sha):
                raise SystemExit(f"{name} {sha!r} 要是 8–64 位小写十六进制 (前缀即可)")
        self.tv_run_tag, self.tv_extractor, self.tv_bank_sha = tv_run_tag, tv_extractor, tv_bank_sha
        self.jev_run_tag, self.jev_bank_sha, self.owner_run_tag = jev_run_tag, jev_bank_sha, owner_run_tag


def pivot_sql(pins: Pins | None = None) -> str:
    """拿去 MCP / SQL 编辑器跑的 pivot。不钉的话 tv_snapshots 会把混进来的快照都列出来, 脚本据此拒算。"""
    p = pins or Pins()
    jev_list = ", ".join(f"'{e}'" for e in JEV_EXTRACTORS.values())
    # 这两段是【替换进去】的, 不走 % 格式化, 所以写单个 % (模板正文里的 like 'llm:%%' 才要双写)
    jev_filters = f"\n        and bank_sha256 like '{p.jev_bank_sha}%'" if p.jev_bank_sha else ""
    tv_filters = ""
    if p.tv_extractor:
        tv_filters += f"\n        and extractor = '{p.tv_extractor}'"
    if p.tv_bank_sha:
        tv_filters += f"\n        and bank_sha256 like '{p.tv_bank_sha}%'"
    return """
with j as (select subject_id, question_id,
             max(answer) filter (where extractor = '%(ja)s') as a,
             max(answer) filter (where extractor = '%(jb)s') as b,
             max(answer) filter (where extractor = '%(jc)s') as c,
             count(distinct question_version) as jev_versions,
             count(distinct bank_sha256) as jev_shas
      from truth_vault.note_feature_answers
      where run_tag = '%(jev)s' and subject_type = 'note' and extractor in (%(jev_list)s)%(jev_filters)s
      group by 1, 2),
o as (select subject_id, question_id, max(answer) as owner
      from truth_vault.note_feature_answers
      where run_tag = '%(owner_tag)s' and subject_type = 'note' and extractor = '%(owner)s'
      group by 1, 2),
t as (select subject_id, question_id,
             count(*) as tv_n,
             (array_agg(answer order by question_version desc, extractor, bank_sha256))[1] as tv,
             (array_agg((invalid_reason is not null) order by question_version desc, extractor, bank_sha256))[1] as tv_invalid,
             max(question_version) as tv_version,
             array_agg(distinct extractor || '@' || left(bank_sha256, 8) || '#v' || question_version) as tv_snapshots
      from truth_vault.note_feature_answers
      where run_tag = '%(tv)s' and extractor like 'llm:%%' and subject_type = 'note'%(tv_filters)s
        and subject_id in (select distinct subject_id from j)
      group by 1, 2)
select json_agg(json_build_object('subject_id', j.subject_id, 'question_id', j.question_id,
                                  'a', j.a, 'b', j.b, 'c', j.c, 'owner', o.owner,
                                  'jev_run_tag', '%(jev)s', 'jev_versions', j.jev_versions, 'jev_shas', j.jev_shas,
                                  'tv', t.tv, 'tv_invalid', coalesce(t.tv_invalid, false),
                                  'tv_version', t.tv_version, 'tv_n', coalesce(t.tv_n, 0),
                                  'tv_snapshots', coalesce(t.tv_snapshots, '{}'), 'tv_run_tag', '%(tv)s'))::text as pivot
from j left join o using (subject_id, question_id) left join t using (subject_id, question_id);
""".strip() % {"jev": p.jev_run_tag, "tv": p.tv_run_tag, "owner": OWNER_EXTRACTOR, "owner_tag": p.owner_run_tag,
               "tv_filters": tv_filters, "jev_filters": jev_filters, "jev_list": jev_list,
               "ja": JEV_EXTRACTORS["a"], "jb": JEV_EXTRACTORS["b"], "jc": JEV_EXTRACTORS["c"]}


PIVOT_SQL = pivot_sql()


# ─────────────────────────────────────────────────────────────────────────
# 统计
# ─────────────────────────────────────────────────────────────────────────

def kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Cohen's κ; **任一边**只有一种取值 → None (没定义)。

    一边恒定时数学上 κ = 0 (po == pe), 但这个 0 不说明一致性 —— 它只反映另一边偶尔答了别的。
    照顶部口径报「不可算」而不是 0.00, 否则正例稀少的题 (效果承诺 / 故意不说名字) 会被当成
    普通的"不过" (codex review on #154)。"""
    n = len(pairs)
    if n == 0:
        return None
    left = {x for x, _ in pairs}
    right = {y for _, y in pairs}
    if len(left) < 2 or len(right) < 2:
        return None
    cats = sorted(left | right)
    po = sum(1 for x, y in pairs if x == y) / n
    pe = sum((sum(1 for x, _ in pairs if x == c) / n) * (sum(1 for _, y in pairs if y == c) / n) for c in cats)
    if pe >= 1.0 - 1e-12:
        return None
    return (po - pe) / (1 - pe)


def agree(pairs: list[tuple[str, str]]) -> float | None:
    return None if not pairs else sum(1 for x, y in pairs if x == y) / len(pairs)


def jev_merged(a, b, c) -> tuple[str | None, bool]:
    """(合并答案, 是否争议)。两张表都答 → 一致才算; 只一张 → 直接用。"""
    got = [v for v in (a, b, c) if v is not None]
    if not got:
        return None, False
    if len(got) == 1:
        return got[0], False
    if all(v == got[0] for v in got):
        return got[0], False
    return None, True


# ─────────────────────────────────────────────────────────────────────────
# pivot: 三条路 (SQL 导出 / MCP 文件 / 直接读表), 出来的形状必须一样
# ─────────────────────────────────────────────────────────────────────────

def load_pivot(path: Path) -> list[dict]:
    """接受三种形态: 纯 JSON 数组; SQL 返回的 [{"pivot": "<json 文本>"}]; MCP 工具结果的整段文本。"""
    raw = path.read_text(encoding="utf-8")
    # MCP 把大结果存成 {"result": "...<untrusted-data-x>...</untrusted-data-x>..."} 的 JSON 文件
    try:
        env = json.loads(raw)
        if isinstance(env, dict) and isinstance(env.get("result"), str):
            raw = env["result"]
    except json.JSONDecodeError:
        pass
    # 开头那句话里也提到一次 <untrusted-data-x>, 所以要认"标签后紧跟换行、且首尾标签 id 相同"的那一对
    m = re.search(r"<untrusted-data-([0-9a-f-]+)>\n(.*?)\n</untrusted-data-\1>", raw, re.S)
    if m:
        raw = m.group(2)
    data = json.loads(raw)
    if isinstance(data, list) and data and isinstance(data[0], dict) and "pivot" in data[0]:
        data = json.loads(data[0]["pivot"])
    if not isinstance(data, list):
        raise SystemExit("pivot 不是数组")
    return data


def pivot_rows(jev_rows: list[dict], owner_rows: list[dict], tv_rows: list[dict], pins: Pins | None = None) -> list[dict]:
    """把三边的原始行 (note_feature_answers 的列: subject_id, question_id, question_version,
    bank_sha256, extractor, answer, invalid_reason) 拼成与 pivot_sql 同一形状的 pivot。
    纯函数, 不碰网络; 调用方负责只传对的 run_tag / extractor 的行 (同 SQL 的 where)。"""
    p = pins or Pins()
    by_key: dict[tuple[str, str], dict] = {}
    for r in jev_rows:
        if r["extractor"] not in JEV_EXTRACTORS.values():
            continue                         # 同 SQL: 只认三张表, human:<姓名> 之类不进来
        k = (r["subject_id"], r["question_id"])
        cell = by_key.setdefault(k, {"a": None, "b": None, "c": None, "_jv": set(), "_js": set(), "_tv": []})
        cell["_jv"].add(r["question_version"])
        cell["_js"].add(r["bank_sha256"])
        for slot, ext in JEV_EXTRACTORS.items():
            if r["extractor"] == ext:
                cell[slot] = _max_answer(cell[slot], r["answer"])
    owner: dict[tuple[str, str], str | None] = {}
    for r in owner_rows:
        if r["extractor"] == OWNER_EXTRACTOR:
            k = (r["subject_id"], r["question_id"])
            owner[k] = _max_answer(owner.get(k), r["answer"])
    for r in tv_rows:
        k = (r["subject_id"], r["question_id"])
        if k in by_key:                      # SQL 是 j left join t: 只有 Jev 标过的格才要 TV
            by_key[k]["_tv"].append(r)
    out = []
    for k in sorted(by_key):
        cell = by_key[k]
        tvs = sorted(cell["_tv"], key=lambda r: (-int(r["question_version"]), r["extractor"], r["bank_sha256"]))
        out.append({
            "subject_id": k[0], "question_id": k[1],
            "a": cell["a"], "b": cell["b"], "c": cell["c"], "owner": owner.get(k),
            "jev_run_tag": p.jev_run_tag, "jev_versions": len(cell["_jv"]), "jev_shas": len(cell["_js"]),
            "tv": tvs[0]["answer"] if tvs else None,
            "tv_invalid": bool(tvs[0].get("invalid_reason")) if tvs else False,
            "tv_version": int(tvs[0]["question_version"]) if tvs else None,
            "tv_n": len(tvs),
            "tv_snapshots": sorted({f"{r['extractor']}@{r['bank_sha256'][:8]}#v{r['question_version']}" for r in tvs}),
            "tv_run_tag": p.tv_run_tag,
        })
    return out


def _max_answer(cur, new):
    """同 SQL 的 max(answer): 同一格同一表若有两行 (混了版本), 取字典序大的 —— 反正 jev_versions > 1
    会让 check_snapshots 拒算, 这里只是保持两条路形状一致。"""
    if new is None:
        return cur
    return new if cur is None or new > cur else cur


def check_snapshots(rows: list[dict], expect_tv_run_tag: str | None = None) -> dict:
    """钉快照 (顶部口径)。返回 {"tv_snapshot", "versions", "pinned", "tv_run_tag", "jev_run_tag"};
    混了就 SystemExit, 把看到的快照列出来。旧导出没有快照列 → pinned=False, 不拒。
    expect_tv_run_tag: 命令行给的; 和 pivot 里记的不一致 → 退出 (报告表头不能标错来源)。"""
    tags = {r.get("tv_run_tag") for r in rows if r.get("tv_run_tag")}
    jtags = {r.get("jev_run_tag") for r in rows if r.get("jev_run_tag")}
    if len(tags) > 1 or len(jtags) > 1:
        raise SystemExit(f"pivot 里混了多个 run_tag: tv={sorted(tags)} jev={sorted(jtags)} —— 一份 pivot 只能是一组快照")
    tv_tag = next(iter(tags)) if tags else None
    if expect_tv_run_tag and tv_tag and tv_tag != expect_tv_run_tag:
        raise SystemExit(f"--tv-run-tag {expect_tv_run_tag!r} 与 pivot 里记的 tv_run_tag {tv_tag!r} 不一致 —— "
                         "这份 pivot 不是那次跑的导出, 或者参数给错了")
    has_meta = any("tv_snapshots" in r for r in rows)
    if not has_meta:
        return {"tv_snapshot": None, "versions": {}, "pinned": False, "tv_run_tag": tv_tag,
                "jev_run_tag": next(iter(jtags)) if jtags else None}
    snaps: set[str] = set()
    per_q_versions: dict[str, set[int]] = defaultdict(set)
    multi = [r for r in rows if (r.get("tv_n") or 0) > 1]
    jev_mixed = [r for r in rows if (r.get("jev_versions") or 0) > 1 or (r.get("jev_shas") or 0) > 1]
    for r in rows:
        for s in r.get("tv_snapshots") or []:
            snaps.add(s.rsplit("#v", 1)[0])
        if r.get("tv_version") is not None:
            per_q_versions[r["question_id"]].add(int(r["tv_version"]))
    problems = []
    if len(snaps) > 1:
        problems.append("TV 侧混了 %d 个 (extractor, bank_sha256) 快照: %s —— 用 --tv-extractor / --tv-bank-sha 钉住一个"
                        % (len(snaps), ", ".join(sorted(snaps))))
    if multi:
        ex = multi[0]
        problems.append("TV 侧 %d 个格子有多行 (同 run_tag 下混了版本或抽取器), 例如 %s/%s: %s"
                        % (len(multi), ex["subject_id"], ex["question_id"], ex.get("tv_snapshots")))
    bad_q = {q: sorted(v) for q, v in per_q_versions.items() if len(v) > 1}
    if bad_q:
        problems.append("同一题在 TV 侧出现多个 question_version: %s" % bad_q)
    if jev_mixed:
        ex = jev_mixed[0]
        problems.append("Jev 三张表 %d 个格子混了版本或题库校验和, 例如 %s/%s —— Jev 重跑请落新 run_tag, 用 --jev-run-tag / --jev-bank-sha 钉住"
                        % (len(jev_mixed), ex["subject_id"], ex["question_id"]))
    if problems:
        raise SystemExit("拒算 —— 先钉死快照 (docs/28 附录 B.3):\n  - " + "\n  - ".join(problems))
    return {"tv_snapshot": next(iter(snaps)) if snaps else None,
            "versions": {q: next(iter(v)) for q, v in per_q_versions.items()}, "pinned": True,
            "tv_run_tag": tv_tag, "jev_run_tag": next(iter(jtags)) if jtags else None}


# ─────────────────────────────────────────────────────────────────────────
# 读库 (表 API, 不用 RPC —— 库里没有 exec_sql 这种函数, codex review on #154)
# ─────────────────────────────────────────────────────────────────────────

_COLS = "subject_id, question_id, question_version, bank_sha256, extractor, answer, invalid_reason"


def _one_request(q, what: str) -> list[dict]:
    """单次请求取满 _MAX_ROWS_PER_REQUEST 行就是被 PostgREST max-rows 钳了 → 报错, 不静默截断。
    每个请求都按 (run_tag, extractor 或 llm:%, question_id) 切过, 正常 ≤ 样本篇数 × 版本数 ≪ 1000。"""
    rows = q.range(0, _MAX_ROWS_PER_REQUEST - 1).execute().data or []
    if len(rows) >= _MAX_ROWS_PER_REQUEST:
        raise SystemExit(f"{what}: 单次请求拿到 {len(rows)} 行, 撞到 PostgREST max-rows, 会被截断 —— "
                         "样本远超闸一规模; 用 --print-sql 导出后 --from-json")
    return rows


def fetch_pivot_live(bank: dict, pins: Pins | None = None) -> list[dict]:
    """按 (run_tag, extractor, question_id) 一次一请求; subject 列表走 in_() 要分批 (URL ~26 KB, D-080)。
    过滤条件与 pivot_sql 逐条对应 (Jev 三张表 / owner / TV llm:%), 两条路出同一形状。"""
    from _common import get_supabase_client  # noqa: WPS433 (只在读库时才需要)
    p = pins or Pins()
    sb = get_supabase_client()
    tbl = lambda: sb.schema("truth_vault").table("note_feature_answers").select(_COLS).eq("subject_type", "note")  # noqa: E731
    qids = [q["id"] for q in fb.llm_questions(bank)]
    jev_rows: list[dict] = []
    for ext in JEV_EXTRACTORS.values():
        for qid in qids:
            q = tbl().eq("run_tag", p.jev_run_tag).eq("extractor", ext).eq("question_id", qid)
            if p.jev_bank_sha:
                q = q.like("bank_sha256", f"{p.jev_bank_sha}%")
            jev_rows += _one_request(q, f"{ext}/{qid}")
    owner_rows: list[dict] = []
    for qid in qids:
        owner_rows += _one_request(tbl().eq("run_tag", p.owner_run_tag).eq("extractor", OWNER_EXTRACTOR).eq("question_id", qid),
                                   f"{OWNER_EXTRACTOR}/{qid}")
    subjects = sorted({r["subject_id"] for r in jev_rows})
    tv_rows: list[dict] = []
    for qid in qids:
        for i in range(0, len(subjects), 100):          # ≤100 个 id 一批: note_id ~25 字节, 远离 26 KB
            q = tbl().eq("run_tag", p.tv_run_tag).eq("question_id", qid).in_("subject_id", subjects[i:i + 100])
            q = q.eq("extractor", p.tv_extractor) if p.tv_extractor else q.like("extractor", "llm:%")
            if p.tv_bank_sha:
                q = q.like("bank_sha256", f"{p.tv_bank_sha}%")
            tv_rows += _one_request(q, f"tv/{qid}")
    return pivot_rows(jev_rows, owner_rows, tv_rows, p)


# ─────────────────────────────────────────────────────────────────────────
# 报告
# ─────────────────────────────────────────────────────────────────────────

def fmt(v: float | None) -> str:
    return "不可算" if v is None else f"{v:.2f}"


def build_report(rows: list[dict], bank: dict, *, tv_run_tag: str | None = None,
                 retest_rows: list[dict] | None = None) -> tuple[str, dict]:
    """tv_run_tag: 命令行给的期望值, 只用来和 pivot 里记的核对; 表头印的是 pivot 里的。"""
    snap = check_snapshots(rows, expect_tv_run_tag=tv_run_tag)
    label_tag = snap["tv_run_tag"] or (f"{tv_run_tag}（pivot 未带 run_tag, 按命令行参数）" if tv_run_tag else "未知（旧导出）")
    qorder = [q["id"] for q in fb.llm_questions(bank)]
    by_q: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_q[r["question_id"]].append(r)
    notes = {r["subject_id"] for r in rows}
    tv_notes = {r["subject_id"] for r in rows if r.get("tv") is not None}
    tv_invalid_total = sum(1 for r in rows if r.get("tv_invalid"))

    lines = []
    lines.append(f"# 闸一 · Jev vs TV 模型 逐题一致率（{len(notes)} 篇样本，TV 已答 {len(tv_notes)} 篇）")
    lines.append("")
    lines.append(f"> 口径见 `scripts/gate1_agreement.py` 顶部。通过线：一致率 ≥ {PASS_AGREE:.2f} 且 κ ≥ {PASS_KAPPA:.2f}"
                 f"（docs/28 §6.1）。**模型 vs 模型**——两个模型在题面歧义处一起错的看不出来（D-081）。")
    lines.append(f"> TV 校验没过的格子 {tv_invalid_total} 个，不算不一致，单独列。")
    if snap["pinned"]:
        vers = Counter(snap["versions"].values())
        by_ver = {v: sorted(q for q, qv in snap["versions"].items() if qv == v) for v in vers}
        ver_txt = "；".join(f"v{v}: " + "、".join(SHORT.get(q, q) for q in qs) for v, qs in sorted(by_ver.items()))
        lines.append(f"> TV 快照：run_tag `{label_tag}`，`{snap['tv_snapshot']}`（extractor@bank_sha256 前 8 位）；"
                     f"question_version {ver_txt}。Jev：run_tag `{snap['jev_run_tag']}`。")
    else:
        lines.append(f"> TV 快照：run_tag `{label_tag}`；这份 pivot 没带快照列（旧导出），**没法核对**是否混了抽取器 / 题库版本。")
    lines.append("")
    lines.append("| # | 题 | Jev合并 vs TV<br>n · 一致 · κ | 争议 | A vs TV | B vs TV | C vs TV | A–B | A–C | TV 没答 | owner 裁过的格<br>TV 对 · Jev 对 · n | 判 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    summary = {"pass": [], "fail": [], "undefined": [], "owner": {}}
    for i, qid in enumerate(qorder, 1):
        rs = by_q.get(qid, [])
        merged_pairs, disputes = [], 0
        per_sheet = {k: [] for k in "abc"}
        ab, ac = [], []
        tv_missing = 0
        own_n = own_tv = own_jev = own_skip = 0
        for r in rs:
            tv = r.get("tv")
            m, disp = jev_merged(r.get("a"), r.get("b"), r.get("c"))
            disputes += disp
            if r.get("owner") is not None:
                if tv is None or m is None:      # 没答 / 争议: 不是"都不对", 单独记
                    own_skip += 1
                else:
                    own_n += 1
                    own_tv += int(tv == r["owner"])
                    own_jev += int(m == r["owner"])
            if r.get("a") is not None and r.get("b") is not None:
                ab.append((r["a"], r["b"]))
            if r.get("a") is not None and r.get("c") is not None:
                ac.append((r["a"], r["c"]))
            if tv is None:
                tv_missing += 1
                continue
            if m is not None:
                merged_pairs.append((m, tv))
            for k in "abc":
                if r.get(k) is not None:
                    per_sheet[k].append((r[k], tv))
        ag, kp = agree(merged_pairs), kappa(merged_pairs)
        if ag is None:
            verdict = "—"
        elif kp is None:
            verdict = "κ 不可算"
            summary["undefined"].append(qid)
        elif ag >= PASS_AGREE and kp >= PASS_KAPPA:
            verdict = "过"
            summary["pass"].append(qid)
        else:
            verdict = "**不过**"
            summary["fail"].append(qid)
        if own_n or own_skip:
            summary["owner"][qid] = {"tv": own_tv, "jev": own_jev, "n": own_n, "skipped": own_skip}
        own_txt = "—" if not (own_n or own_skip) else f"{own_tv} · {own_jev} · {own_n}" + (f"（没答 {own_skip}）" if own_skip else "")
        cell = lambda p: f"{len(p)} · {fmt(agree(p))} · {fmt(kappa(p))}"  # noqa: E731
        lines.append(f"| {i} | {SHORT.get(qid, qid)} | {cell(merged_pairs)} | {disputes} | "
                     f"{cell(per_sheet['a'])} | {cell(per_sheet['b'])} | {cell(per_sheet['c'])} | "
                     f"{cell(ab)} | {cell(ac)} | {tv_missing} | {own_txt} | {verdict} |")
    lines.append("")
    lines.append(f"过 {len(summary['pass'])} 题 · 不过 {len(summary['fail'])} 题 · κ 不可算 {len(summary['undefined'])} 题")
    if summary["fail"]:
        lines.append("")
        lines.append("不过的题：" + "、".join(f"{SHORT.get(q, q)}（{q}）" for q in summary["fail"]))
    if summary["undefined"]:
        lines.append("")
        lines.append("κ 不可算（一边全是同一个答案，一致率再高也说明不了什么；不算过也不算不过）：" +
                     "、".join(f"{SHORT.get(q, q)}（{q}）" for q in summary["undefined"]))
    if summary["owner"]:
        tot = {k: sum(v[k] for v in summary["owner"].values()) for k in ("tv", "jev", "n", "skipped")}
        lines.append("")
        lines.append(f"owner 裁过的格子（两边都答了的）：TV 对 {tot['tv']} · Jev 对 {tot['jev']} · n {tot['n']}"
                     + (f"；另有 {tot['skipped']} 格 TV 没答或 Jev 争议，不计" if tot["skipped"] else "") + "。")
    # 分歧最多的 (Jev合并 vs TV) 格子按题列出答案分布, 方便看是"谁在偏"
    lines.append("")
    lines.append("## 不一致格子的方向（Jev合并 → TV）")
    lines.append("")
    for qid in qorder:
        rs = by_q.get(qid, [])
        c = Counter()
        for r in rs:
            m, _ = jev_merged(r.get("a"), r.get("b"), r.get("c"))
            if m is not None and r.get("tv") is not None and m != r["tv"]:
                c[(m, r["tv"])] += 1
        if c:
            lines.append(f"- {SHORT.get(qid, qid)}：" + "，".join(f"{a}→{b} ×{n}" for (a, b), n in c.most_common()))
    if retest_rows is not None:
        lines += retest_section(rows, retest_rows, bank, snap)
    return "\n".join(lines) + "\n", summary


def retest_section(rows: list[dict], other: list[dict], bank: dict, snap: dict) -> list[str]:
    """同一个 TV 模型两次跑 (本 pivot 的 tv vs 另一份 pivot 的 tv), 逐题一致率 / κ。
    题面没改的题 (两边 question_version 相同) 量的是模型自身抖动; 改了的题量的是题面改动 + 抖动, 分开标。"""
    osnap = check_snapshots(other)
    other_tv = {(r["subject_id"], r["question_id"]): r for r in other}
    lines = ["", f"## TV 自己两次跑的一致率（本表 run_tag `{snap.get('tv_run_tag') or '?'}` vs `{osnap.get('tv_run_tag') or '?'}`）", "",
             "> 同一模型、同一批原文，两次跑的答案对不对得上。题面没改的题量的是**模型自身抖动**，读上面的分歧前先看它；"
             "改了题面的题量的是题面改动 + 抖动。两边都答了才计。", "",
             "| # | 题 | 版本（本 / 另） | n · 一致 · κ | 方向（另 → 本） |", "|---|---|---|---|---|"]
    qorder = [q["id"] for q in fb.llm_questions(bank)]
    by_q: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_q[r["question_id"]].append(r)
    for i, qid in enumerate(qorder, 1):
        pairs, c = [], Counter()
        for r in by_q.get(qid, []):
            o = other_tv.get((r["subject_id"], qid))
            if r.get("tv") is None or not o or o.get("tv") is None:
                continue
            pairs.append((o["tv"], r["tv"]))
            if o["tv"] != r["tv"]:
                c[(o["tv"], r["tv"])] += 1
        v_here, v_other = snap["versions"].get(qid), osnap["versions"].get(qid)
        ver = f"v{v_here} / v{v_other}" + ("" if v_here == v_other else " **改了题面**") if v_here and v_other else "?"
        lines.append(f"| {i} | {SHORT.get(qid, qid)} | {ver} | {len(pairs)} · {fmt(agree(pairs))} · {fmt(kappa(pairs))} | "
                     + ("，".join(f"{a}→{b} ×{n}" for (a, b), n in c.most_common()) or "—") + " |")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--from-json", type=Path, default=None)
    ap.add_argument("--retest-json", type=Path, default=None, help="另一份 pivot (同一 TV 模型的另一次跑), 加「TV 自己两次跑」一节")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--print-sql", action="store_true", help="打印 pivot SQL (拿去 MCP / SQL 编辑器跑)")
    ap.add_argument("--tv-run-tag", default=None,
                    help=f"TV 那一边读哪个 run_tag (读库默认 {RUN_TAG_TV_DEFAULT}; --from-json 时只用来和 pivot 核对)")
    ap.add_argument("--tv-extractor", default=None, help="钉住 TV 抽取器, 如 llm:claude-opus-4-6 (混了就必须给)")
    ap.add_argument("--tv-bank-sha", default=None, help="钉住 TV 题库 sha256 前缀 (≥8 位; 混了就必须给)")
    ap.add_argument("--jev-run-tag", default=RUN_TAG_JEV, help=f"Jev 三张表的 run_tag (默认 {RUN_TAG_JEV}; Jev 重跑落新 tag 就改这里)")
    ap.add_argument("--jev-bank-sha", default=None, help="钉住 Jev 题库 sha256 前缀")
    ap.add_argument("--owner-run-tag", default=RUN_TAG_OWNER, help=f"owner 裁决的 run_tag (默认 {RUN_TAG_OWNER})")
    args = ap.parse_args()
    pins = Pins(args.tv_run_tag or RUN_TAG_TV_DEFAULT, args.tv_extractor, args.tv_bank_sha,
                args.jev_run_tag, args.jev_bank_sha, args.owner_run_tag)
    if args.print_sql:
        print(pivot_sql(pins))
        return 0
    bank = fb.load_bank()
    rows = load_pivot(args.from_json) if args.from_json else fetch_pivot_live(bank, pins)
    retest = load_pivot(args.retest_json) if args.retest_json else None
    report, summary = build_report(rows, bank, tv_run_tag=args.tv_run_tag, retest_rows=retest)
    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"写到 {args.out}")
    print(report if not args.out else report.splitlines()[0])
    print(f"pass={len(summary['pass'])} fail={len(summary['fail'])} undefined={len(summary['undefined'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
