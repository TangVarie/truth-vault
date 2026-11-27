#!/usr/bin/env python3
"""measure_g24_withdrawal.py —— G-24 / D-134 撤回条件的量法 (只读, 不写库, 不调模型)。

条件 (D-134「代价与后续」, 预注册见 G-24 的 D 条目): code:v2 下 brand_first_position = 后20% 的篇里,
「品牌只在标签里」(feature_bank.brand_only_in_tags) 的比例 ≤ 10% → 「品牌别硬插」的例子可以打开 (PR-2: 批准层升 v4)。
分母只数词典不空的篇; 同时打出 code:v1 的同一个数作对照 (10-30 是 162/199)。
G-24 (D-179 11-27 补): code:v2 那一份只数 code:v1 在同一 sha 前缀、run_tag primary 下也答过 brand_first_position 的篇
(v1 那一行答案是什么都行): code:v2 回填给整个项目写, code:v1 只在 features-sync / 早先回填跑过的篇有, 不筛的话 v2 的分母
里有对照那边根本没有的篇。丢了几篇在判定行之前打一行 (只有计数); code:v1 那一份不筛。和 gate2_run 同一条规则。

    cd scripts && python measure_g24_withdrawal.py --sha ba0f570c            # 回填 code:v2 之后跑
输出只有计数和项目代号。退出码: 0 = 条件过; 1 = 没过; 2 = 数不出来 (code:v2 一行都没有、连库 / 取数出错等)。
判定那一行 (「撤回条件 (≤ 10%): 过 / 没过」) 总是 stdout 的最后一行; gate2-run 要退出码和这一行对得上才认。
出错时只往 stderr 打打过码的一句 (gate2-run 不把 stderr 写进 step summary)。
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from typing import Iterable, Optional

import feature_bank as fb
from secret_mask import mask_secrets

THRESHOLD = 0.10
POSITION = "后20%"


def withdrawal_share(rows: Iterable[dict]) -> dict:
    """rows: {project_id, only_in_tags: True/False/None}。None (词典空) 不进分母。"""
    tot = defaultdict(lambda: [0, 0])
    for r in rows:
        if r["only_in_tags"] is None:
            continue
        t = tot[r["project_id"]]
        t[1] += 1
        t[0] += int(bool(r["only_in_tags"]))
    num = sum(v[0] for v in tot.values())
    den = sum(v[1] for v in tot.values())
    share = (num / den) if den else None
    return {"num": num, "den": den, "share": share, "passed": (share is not None and share <= THRESHOLD),
            "by_project": {p: tuple(v) for p, v in sorted(tot.items())}}


def late_ids(answers: Iterable[dict], v1_subjects: Optional[set] = None) -> tuple[list[str], int]:
    """brand_first_position = 后20% 的篇 (排好序)。v1_subjects 给了 (code:v2 那一份, D-179 11-27 补): 只留 code:v1 也答过
    这道题的篇, 回 (留下的篇, 丢掉的篇数); 不给 (code:v1 那一份) 就不筛, 丢 0。"""
    ids = sorted(a["subject_id"] for a in answers if a.get("answer") == POSITION)
    if v1_subjects is None:
        return ids, 0
    kept = [i for i in ids if i in v1_subjects]
    return kept, len(ids) - len(kept)


def _answers(sb, sha: str, extractor: str) -> list[dict]:
    from _common import fetch_all_pages
    return fetch_all_pages(sb.schema("truth_vault").table("note_feature_answers")
                           .select("subject_id, answer").eq("subject_type", "note").eq("run_tag", "primary")
                           .eq("question_id", "brand_first_position").eq("extractor", extractor)
                           .like("bank_sha256", f"{sha}%"), order_by="subject_id")


def _rows_for(sb, ids: list[str]) -> list[dict]:
    from _common import load_mapping
    out: list[dict] = []
    maps: dict[str, dict] = {}
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        notes = (sb.schema("truth_vault").table("notes")
                 .select("note_id, project_id, title, raw_content, target_blue_keywords, projects(brand, product)")
                 .in_("note_id", chunk).execute().data) or []
        for n in notes:
            pid = n["project_id"]
            if pid not in maps:
                try:
                    maps[pid] = load_mapping(pid)
                except Exception:  # noqa: BLE001 —— 没有 mapping 的项目按 none 切, 别名为空
                    maps[pid] = {}
            m = maps[pid]
            spans = fb.build_spans(n.get("raw_content") or "", mode=m.get("title_extraction") or "none",
                                   title_col=n.get("title"))
            words = fb.brand_dictionary(n.get("projects") or {}, n, m)
            out.append({"project_id": pid, "only_in_tags": fb.brand_only_in_tags(spans, words)})
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sha", required=True, help="bank_sha256 前缀 (≥ 8 位)")
    a = ap.parse_args(argv)
    if len(a.sha) < 8:
        ap.error("--sha 至少 8 位")
    try:
        from _common import get_supabase_client
        sb = get_supabase_client()
        ans = {ext: _answers(sb, a.sha.lower(), ext) for ext in fb.CODE_EXTRACTORS}
        v1_subjects = {r["subject_id"] for r in ans[fb.CODE_EXTRACTOR]}       # v1 答过这道题的篇, 答案不论
        res, v2_dropped = {}, 0
        for ext in fb.CODE_EXTRACTORS:
            ids, dropped = late_ids(ans[ext], v1_subjects if ext == fb.CODE_EXTRACTOR_V2 else None)
            if ext == fb.CODE_EXTRACTOR_V2:
                v2_dropped = dropped
            res[ext] = withdrawal_share(_rows_for(sb, ids))
    except Exception as exc:  # noqa: BLE001 —— 连库 / 取数出错 = 数不出来 (2); 别让 Python 崩溃的退出码 1 冒充「没过」
        print(f"数不出来: {type(exc).__name__}: {mask_secrets(str(exc))[:300]}", file=sys.stderr)
        return 2
    for ext, r in res.items():
        share = "—" if r["share"] is None else f"{r['share']:.1%}"
        print(f"{ext}: {POSITION} {r['den']} 篇, 品牌只在标签里 {r['num']} 篇 ({share})")
        for p, (k, n) in r["by_project"].items():
            print(f"    {p}: {k}/{n}")
    print(f"{fb.CODE_EXTRACTOR_V2} 的{POSITION}只数 {fb.CODE_EXTRACTOR} 也答过 brand_first_position 的篇 (同一 sha、run_tag primary; "
          f"D-179 11-27 补): 丢掉 {v2_dropped} 篇")
    v2 = res[fb.CODE_EXTRACTOR_V2]
    if not v2["den"]:
        print("code:v2 下没有「后20%」的篇 (回填还没跑?) —— 数不出来")
        return 2
    print(f"撤回条件 (≤ {THRESHOLD:.0%}): {'过' if v2['passed'] else '没过'}")
    return 0 if v2["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
