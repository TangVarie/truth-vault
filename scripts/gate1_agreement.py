"""
gate1_agreement.py
═══════════════════════════════════════════════════════════════════════════

闸一「测得准」: 逐题算 Jev (三张表) 与 TV 模型 (run_tag=primary, extractor llm:*) 的
一致率与 Cohen's κ, 顺带 Jev–Jev 重叠 (A–B / A–C) —— docs/28 §6.1、D-079 §5、D-081。

    python gate1_agreement.py                          # 直接读库 (要 service key)
    python gate1_agreement.py --from-json pivot.json   # 读 MCP / SQL 编辑器导出的 pivot
    python gate1_agreement.py ... --out data-analysis/gate1-jev-vs-tv-2026-09-23.md

pivot 的形状 (见 PIVOT_SQL): 每行 {subject_id, question_id, a, b, c, tv, tv_invalid},
a/b/c = jev:1.13.0-A/B/C 的答案 (没标这篇就 null), tv = TV 模型答案 (null = 没跑或校验没过)。

口径 (老实写):
  · 一致率 = 两边都有答案的格子里答案相同的比例; κ = Cohen's κ, 任一边取值只有一种时
    κ 没有定义 → 报「不可算」, 不写 1.00 也不写 0。
  · 「Jev 合并」= 一篇有两张表答了取一致的 (不一致记争议、不计), 只有一张表答的直接用。
    这就是 D-079 §5.3 给人的算法, 现在给 Jev。
  · TV 校验没过的格子 (invalid_reason 非空) 不算不一致, 单独数出来 —— 它是"模型没答", 不是"答错"。
  · 通过线沿用 docs/28 §6.1: 一致率 ≥ 0.85 且 κ ≥ 0.60。**这是模型 vs 模型**, 两个模型在
    题面歧义处一起错的看不出来 (D-081)。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import feature_bank as fb
from build_gate1_human_sheets import SHORT

RUN_TAG_JEV = "gate1-20260928"
PASS_AGREE = 0.85
PASS_KAPPA = 0.60

PIVOT_SQL = """
with s as (select distinct subject_id from truth_vault.note_feature_answers where run_tag = '%(jev)s'),
j as (select subject_id, question_id,
             max(answer) filter (where extractor = 'jev:1.13.0-A') as a,
             max(answer) filter (where extractor = 'jev:1.13.0-B') as b,
             max(answer) filter (where extractor = 'jev:1.13.0-C') as c
      from truth_vault.note_feature_answers where run_tag = '%(jev)s' group by 1, 2),
t as (select subject_id, question_id, answer as tv, (invalid_reason is not null) as tv_invalid
      from truth_vault.note_feature_answers
      where run_tag = 'primary' and extractor like 'llm:%%' and subject_type = 'note'
        and subject_id in (select subject_id from s))
select json_agg(json_build_object('subject_id', j.subject_id, 'question_id', j.question_id,
                                  'a', j.a, 'b', j.b, 'c', j.c, 'tv', t.tv,
                                  'tv_invalid', coalesce(t.tv_invalid, false)))::text as pivot
from j left join t using (subject_id, question_id);
""".strip() % {"jev": RUN_TAG_JEV}


def kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Cohen's κ; 任一边只有一种取值 → None (没定义)。"""
    n = len(pairs)
    if n == 0:
        return None
    cats = sorted({x for p in pairs for x in p})
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


def fetch_pivot_live() -> list[dict]:
    from _common import get_supabase_client  # noqa: WPS433 (只在读库时才需要)
    sb = get_supabase_client()
    res = sb.rpc("exec_sql", {"q": PIVOT_SQL}).execute()  # 没有这个 rpc 就走 --from-json
    return json.loads(res.data[0]["pivot"])


def fmt(v: float | None) -> str:
    return "不可算" if v is None else f"{v:.2f}"


def build_report(rows: list[dict], bank: dict) -> tuple[str, dict]:
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
    lines.append("")
    lines.append("| # | 题 | Jev合并 vs TV<br>n · 一致 · κ | 争议 | A vs TV | B vs TV | C vs TV | A–B | A–C | TV 没答 | 判 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    summary = {"pass": [], "fail": [], "undefined": []}
    for i, qid in enumerate(qorder, 1):
        rs = by_q.get(qid, [])
        merged_pairs, disputes = [], 0
        per_sheet = {k: [] for k in "abc"}
        ab, ac = [], []
        tv_missing = 0
        for r in rs:
            tv = r.get("tv")
            m, disp = jev_merged(r.get("a"), r.get("b"), r.get("c"))
            disputes += disp
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
        cell = lambda p: f"{len(p)} · {fmt(agree(p))} · {fmt(kappa(p))}"  # noqa: E731
        lines.append(f"| {i} | {SHORT.get(qid, qid)} | {cell(merged_pairs)} | {disputes} | "
                     f"{cell(per_sheet['a'])} | {cell(per_sheet['b'])} | {cell(per_sheet['c'])} | "
                     f"{cell(ab)} | {cell(ac)} | {tv_missing} | {verdict} |")
    lines.append("")
    lines.append(f"过 {len(summary['pass'])} 题 · 不过 {len(summary['fail'])} 题 · κ 不可算 {len(summary['undefined'])} 题")
    if summary["fail"]:
        lines.append("")
        lines.append("不过的题：" + "、".join(f"{SHORT.get(q, q)}（{q}）" for q in summary["fail"]))
    if summary["undefined"]:
        lines.append("")
        lines.append("κ 不可算（一边全是同一个答案，一致率再高也说明不了什么）：" +
                     "、".join(f"{SHORT.get(q, q)}（{q}）" for q in summary["undefined"]))
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
    return "\n".join(lines) + "\n", summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--from-json", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--print-sql", action="store_true", help="打印 pivot SQL (拿去 MCP / SQL 编辑器跑)")
    args = ap.parse_args()
    if args.print_sql:
        print(PIVOT_SQL)
        return 0
    bank = fb.load_bank()
    rows = load_pivot(args.from_json) if args.from_json else fetch_pivot_live()
    report, summary = build_report(rows, bank)
    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"写到 {args.out}")
    print(report if not args.out else report.splitlines()[0])
    print(f"pass={len(summary['pass'])} fail={len(summary['fail'])} undefined={len(summary['undefined'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
