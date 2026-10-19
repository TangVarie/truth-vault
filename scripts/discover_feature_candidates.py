#!/usr/bin/env python3
"""discover_feature_candidates.py —— 每季度找一次新特征的候选题 (D-120, 2026-10-19)。

特征题库 (prompts/feature_questions_v0_1.yaml) 冻结在 ba0f570c, 题是 9 月按当时的认识出的。题库不该永远是那一版:
这个脚本每季度拿上一季的笔记, 按项目对照「爆 / 大爆」和「趴」两组, 让模型提出**现有题库没覆盖**、只看标题正文就能
指着原文回答的是 / 否题。它只出候选, 不改题库、不写库 —— 候选题要进题库, 照旧走出题六条规矩 → 新版本草案 → 闸一 (κ)
→ 闸二 (区分度), 由人拍板。

为什么要留一半笔记不看 (holdout): 在同一批笔记上「先找出差异、再检验差异」必然显著。所以按 note_id 的哈希把笔记分成
两半, 只用发现半 (哈希首位是偶数) 来提题; 报告里写明, 候选题跑闸二时只用另一半 (或下一季的新笔记)。

不把原文带进 GitHub: 报告只有题目、判据、编的例子和计数。模型被要求例子自己编; 代码再查一遍, 例子里有一段 ≥ 8 字和
输入的标题正文一样的, 那个例子直接删掉。

标签与闸二同源: truth_vault.v_l2_labels (y=1 是清洗后的 爆 / 大爆, y=0 是 趴)。

用法:
    cd scripts && python discover_feature_candidates.py --dry-run               # 只数样本, 不调模型
    python discover_feature_candidates.py --out ../feature-candidates.md        # 正式跑 (需 ANTHROPIC_* 与 SUPABASE_*)
    python discover_feature_candidates.py --selftest                            # 离线自检 (CI 跑这个)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

import feature_bank as fb

DEFAULT_DAYS = 92
PER_GROUP = 15                 # 每个项目每组最多几篇
MIN_PER_GROUP = 5              # 爆 或 趴 少于这个数的项目不提题 (对照太薄)
PER_PROJECT_CANDIDATES = 4
MAX_CANDIDATES = 10
EXCERPT_CHARS = 280            # 每篇给模型看的正文长度
COPY_RUN = 8                   # 例子和输入有连续 8 字一样 → 当作抄了原文, 删
ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,47}$")
MODEL_ENV = "FEATURE_DISCOVERY_MODEL"
DEFAULT_MODEL = "claude-sonnet-5-5"

SYSTEM = """你在帮一个小红书内容团队给「内容特征题库」提新题。题库里的每一题都是一个闭集小问题, 只看笔记的标题和正文,
能指着原文回答。下面会给你一个项目的两组笔记: A 组是评论多的 (爆), B 组是评论少的 (趴)。

请比较两组, 提出最多 {k} 道**现有题库没有覆盖**的是 / 否题。出题规矩:
1. 一题只问一件事。
2. 答「是」必须能从原文里抄出一小段做证据。
3. 只用发布前就有的东西: 只看标题和正文, 不提评论、互动、点赞、阅读、爆不爆。
4. 边界写清楚: yes_if / no_if 各一句。
5. 写下方向: hypothesis 是 "+"(A 组更常见) 或 "-"(B 组更常见)。
6. 例子 (yes_example / no_example) 必须是你自己编的句子, 不许抄下面任何一篇的原文。
7. 不要和现有题重复或换个说法再问一遍; 不要只对这一个品牌成立 (要能问别的项目)。

现有题库 (id: 题目):
{existing}

只输出 JSON: {{"candidates": [{{"id": "英文小写下划线", "ask": "…？", "scope": "title|first_sentence|last_para|body|full",
"yes_if": "…", "no_if": "…", "yes_example": "…", "no_example": "…", "hypothesis": "+|-", "why": "一句话"}}]}}"""


def in_discovery_half(note_id: str) -> bool:
    """note_id 的 sha256 首位十六进制是偶数 → 发现半。另一半留给候选题的闸二。"""
    return int(hashlib.sha256(str(note_id).encode("utf-8")).hexdigest()[0], 16) % 2 == 0


def existing_questions(bank: dict) -> list[tuple[str, str]]:
    out = [(q["id"], q.get("ask") or "") for q in bank.get("questions") or [] if q.get("id")]
    out += [(c["id"], c.get("ask") or c.get("what") or "") for c in bank.get("code_features") or []
            if isinstance(c, dict) and c.get("id")]
    return out


def build_user_prompt(project: str, category: Optional[str], a: list[dict], b: list[dict]) -> str:
    def one(r: dict) -> str:
        title = (r.get("title") or "").strip()[:60]
        body = re.sub(r"\s+", " ", r.get("body") or "").strip()[:EXCERPT_CHARS]
        return f"- 标题: {title} | 正文: {body}"

    def block(rows: list[dict]) -> str:
        return "\n".join(one(r) for r in rows)
    return (f"项目: {project}" + (f" (品类: {category})" if category else "") +
            f"\n\nA 组 (评论多, {len(a)} 篇):\n{block(a)}\n\nB 组 (评论少, {len(b)} 篇):\n{block(b)}")


def _copied(example: str, corpus: str) -> bool:
    s = re.sub(r"\s+", "", example or "")
    return any(s[i:i + COPY_RUN] in corpus for i in range(0, max(0, len(s) - COPY_RUN + 1)))


def validate(raw: dict, *, existing_ids: set[str], corpus: str, project: str) -> tuple[list[dict], list[str]]:
    """模型回的 JSON → (留下的候选, 丢掉的原因)。corpus 是去空白后的输入原文, 用来查例子有没有抄。"""
    kept, dropped = [], []
    items = raw.get("candidates") if isinstance(raw, dict) else None
    for c in (items if isinstance(items, list) else [])[:PER_PROJECT_CANDIDATES]:
        if not isinstance(c, dict):
            dropped.append("不是对象")
            continue
        cid, ask = str(c.get("id") or "").strip(), str(c.get("ask") or "").strip()
        if not ID_RE.match(cid):
            dropped.append(f"{cid or '(空 id)'}: id 不是小写下划线")
            continue
        if cid in existing_ids:
            dropped.append(f"{cid}: 和现有题同名")
            continue
        if not ask or c.get("scope") not in fb.SPANS or c.get("hypothesis") not in ("+", "-"):
            dropped.append(f"{cid}: 缺题目 / scope 不在 {fb.SPANS} / hypothesis 不是 + -")
            continue
        text = " ".join(str(c.get(k) or "") for k in ("ask", "yes_if", "no_if", "why"))
        leak = [w for w in fb.PERFORMANCE_KEYWORDS if w.lower() in text.lower()]
        if leak:
            dropped.append(f"{cid}: 用到了发布后的信息 ({'、'.join(leak)}) —— 出题规矩 4")
            continue
        out = {k: str(c.get(k) or "").strip() for k in ("id", "ask", "scope", "yes_if", "no_if", "hypothesis", "why")}
        for k in ("yes_example", "no_example"):
            ex = str(c.get(k) or "").strip()
            if ex and not _copied(ex, corpus):
                out[k] = ex
            elif ex:
                dropped.append(f"{cid}: {k} 和原文有连续 {COPY_RUN} 字一样, 例子删了 (题留着)")
        out["projects"] = [project]
        kept.append(out)
    return kept, dropped


def _norm_ask(ask: str) -> str:
    return re.sub(r"[\s？?。,，、]", "", ask)


def merge(per_project: list[list[dict]]) -> list[dict]:
    """同 id 或同题目 (去标点) 的合成一条, 记下哪些项目都提了; 多个项目都提的排前面。"""
    by_key: dict[str, dict] = {}
    for cands in per_project:
        for c in cands:
            key = next((k for k, v in by_key.items() if k == c["id"] or _norm_ask(v["ask"]) == _norm_ask(c["ask"])), None)
            if key is None:
                by_key[c["id"]] = dict(c)
            else:
                by_key[key]["projects"] = sorted(set(by_key[key]["projects"]) | set(c["projects"]))
    return sorted(by_key.values(), key=lambda c: (-len(c["projects"]), c["id"]))


def sample(labels: list[dict], *, since: datetime, per_group: int) -> dict[str, dict[int, list[str]]]:
    """项目 → {1: [爆的 note_id], 0: [趴的 note_id]}, 只取发现半、since 之后发布的, 每组按 note_id 稳定取前 per_group 篇
    (按哈希排, 不按时间: 避免全挤在季末)。"""
    groups: dict[str, dict[int, list[str]]] = defaultdict(lambda: {0: [], 1: []})
    for r in labels:
        ts = r.get("publish_time")
        try:
            t = datetime.fromisoformat(str(ts).replace("Z", "+00:00")) if ts else None
        except ValueError:
            t = None
        if t is not None and t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if t is None or t < since or not in_discovery_half(r["note_id"]):
            continue
        groups[r["project_id"]][int(r["y"])].append(r["note_id"])
    rank = lambda nid: hashlib.sha256(f"order:{nid}".encode()).hexdigest()  # noqa: E731
    return {p: {y: sorted(ids, key=rank)[:per_group] for y, ids in g.items()} for p, g in groups.items()}


def run(*, labels: list[dict], fetch_notes: Callable[[list[str]], dict[str, dict]], categories: dict[str, str],
        bank: dict, call: Optional[Callable[[str, str], str]], since: datetime, per_group: int = PER_GROUP,
        projects: Optional[set[str]] = None) -> dict:
    """``call(system, user) -> text``; None = dry-run (只数样本)。"""
    existing = existing_questions(bank)
    existing_ids = {i for i, _ in existing}
    system = SYSTEM.format(k=PER_PROJECT_CANDIDATES, existing="\n".join(f"{i}: {a}" for i, a in existing))
    groups = sample(labels, since=since, per_group=per_group)
    report = {"since": since.date().isoformat(), "projects": [], "skipped": [], "dropped": [], "candidates": [],
              "holdout_rule": "sha256(note_id) 首位十六进制为奇数的笔记没给模型看 —— 候选题的闸二只用这一半或下一季的新笔记",
              "bank_version": bank.get("bank_version"), "bank_sha256": bank.get("frozen_sha256")}
    per_project = []
    for p in sorted(groups):
        if projects and p not in projects:
            continue
        a_ids, b_ids = groups[p][1], groups[p][0]
        if len(a_ids) < MIN_PER_GROUP or len(b_ids) < MIN_PER_GROUP:
            report["skipped"].append({"project": p, "baokuan": len(a_ids), "pa": len(b_ids)})
            continue
        report["projects"].append({"project": p, "baokuan": len(a_ids), "pa": len(b_ids)})
        if call is None:
            continue
        notes = fetch_notes(a_ids + b_ids)
        a = [notes[i] for i in a_ids if i in notes]
        b = [notes[i] for i in b_ids if i in notes]
        corpus = re.sub(r"\s+", "", "".join((n.get("title") or "") + (n.get("body") or "") for n in a + b))
        try:
            raw = json.loads(_strip_fence(call(system, build_user_prompt(p, categories.get(p), a, b))))
        except Exception as exc:  # noqa: BLE001 — 一个项目失败不拖垮整季
            report["dropped"].append(f"{p}: 这次没拿到候选 ({type(exc).__name__}: {str(exc)[:120]})")
            continue
        kept, dropped = validate(raw, existing_ids=existing_ids, corpus=corpus, project=p)
        report["dropped"] += [f"{p}: {d}" for d in dropped]
        per_project.append(kept)
    report["candidates"] = merge(per_project)[:MAX_CANDIDATES]
    return report


def _strip_fence(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0] if t.rstrip().endswith("```") else t
    return t


def render(report: dict, *, dry_run: bool) -> str:
    lines = [f"# 特征候选题 · {datetime.now(timezone.utc).date().isoformat()}", "",
             f"- 看的是 {report['since']} 以来发布的笔记, 只用发现半; {report['holdout_rule']}",
             f"- 现有题库: {report.get('bank_version')} (frozen {str(report.get('bank_sha256') or '')[:8]})",
             f"- 提了题的项目: {len(report['projects'])} 个; 对照太薄跳过: {len(report['skipped'])} 个"
             + (" —— **dry-run, 没调模型**" if dry_run else ""), ""]
    if report["projects"]:
        lines += ["| 项目 | 爆 | 趴 |", "|---|---|---|"]
        lines += [f"| {r['project']} | {r['baokuan']} | {r['pa']} |" for r in report["projects"]]
        lines.append("")
    if report["skipped"]:
        lines.append("跳过: " + "、".join(f"{r['project']}(爆 {r['baokuan']} / 趴 {r['pa']})" for r in report["skipped"]))
        lines.append("")
    if not dry_run:
        lines.append(f"## 候选 ({len(report['candidates'])} 道)")
        lines.append("")
        if not report["candidates"]:
            lines.append("这一季没有留下来的候选。")
        for c in report["candidates"]:
            lines += [f"### `{c['id']}` · {c['ask']}",
                      f"- scope: {c['scope']} · 方向: {c['hypothesis']} · 提出的项目: {'、'.join(c['projects'])}",
                      f"- 判是: {c['yes_if']}" + (f" (例: {c['yes_example']})" if c.get("yes_example") else ""),
                      f"- 判否: {c['no_if']}" + (f" (例: {c['no_example']})" if c.get("no_example") else ""),
                      f"- 为什么: {c['why']}", ""]
        if report["dropped"]:
            lines += ["## 丢掉的", ""] + [f"- {d}" for d in report["dropped"]] + [""]
        lines += ["## 下一步", "",
                  "候选题不会自己进题库。要收哪几道: 照 prompts/feature_questions_v0_1.yaml 开头的出题六条规矩改写成正式题 →",
                  "开一个新版本的草案 → 闸一 (κ) → 闸二 (只用 holdout 半或下一季的新笔记) → 过了才冻结进新版本。"]
    return "\n".join(lines) + "\n"


def _selftest() -> None:
    bank = {"bank_version": "fq-test", "frozen_sha256": "abcd" * 16,
            "questions": [{"id": "title_is_question", "ask": "标题是不是一个问句？"}]}
    now = datetime(2026, 10, 19, tzinfo=timezone.utc)
    ids = [f"P_rec{i:03d}" for i in range(200)]
    disc = [i for i in ids if in_discovery_half(i)]
    assert 60 < len(disc) < 140, "哈希切半应该大致对半"
    labels = [{"note_id": n, "project_id": "P", "publish_time": "2026-09-01T00:00:00", "y": k % 2}
              for k, n in enumerate(ids)]
    labels.append({"note_id": "OLD_1", "project_id": "P", "publish_time": "2025-01-01T00:00:00", "y": 1})
    notes = {n: {"title": f"标题{n}", "body": "第一段写了一个很具体的价格数字九十九元。" + n} for n in ids}
    seen = {}

    def call(system, user):
        seen["system"], seen["user"] = system, user
        return json.dumps({"candidates": [
            {"id": "mentions_price", "ask": "正文有没有写具体价格？", "scope": "body", "yes_if": "写了数字价格",
             "no_if": "没写", "yes_example": "这瓶我买的时候六十八", "no_example": "第一段写了一个很具体的价格",
             "hypothesis": "+", "why": "价格让读者能比较"},
            {"id": "title_is_question", "ask": "x？", "scope": "title", "yes_if": "", "no_if": "", "hypothesis": "+"},
            {"id": "BadId", "ask": "x？", "scope": "title", "hypothesis": "+"},
            {"id": "mentions_likes", "ask": "有没有提点赞？", "scope": "body", "yes_if": "提了点赞", "no_if": "",
             "hypothesis": "+"},
        ]}, ensure_ascii=False)

    rep = run(labels=labels, fetch_notes=lambda nids: {i: notes[i] for i in nids}, categories={"P": "测试"},
              bank=bank, call=call, since=now - timedelta(days=DEFAULT_DAYS), per_group=10)
    assert [r["project"] for r in rep["projects"]] == ["P"] and rep["projects"][0]["baokuan"] == 10
    assert "title_is_question" in seen["system"], "现有题要给模型看, 免得重复"
    assert all(i in disc for i in re.findall(r"P_rec\d{3}", seen["user"])), "只给模型看发现半"
    assert "OLD_1" not in seen["user"], "季度窗口之外的不给"
    (c,) = rep["candidates"]
    assert c["id"] == "mentions_price" and c["yes_example"] == "这瓶我买的时候六十八"
    assert "no_example" not in c, "抄了原文的例子要删掉"
    reasons = " ".join(rep["dropped"])
    assert "同名" in reasons and "小写下划线" in reasons and "点赞" in reasons and "例子删了" in reasons
    dry = run(labels=labels, fetch_notes=lambda nids: {}, categories={}, bank=bank, call=None,
              since=now - timedelta(days=DEFAULT_DAYS), per_group=10)
    assert dry["candidates"] == [] and dry["projects"]
    thin = run(labels=labels[:8], fetch_notes=lambda nids: {}, categories={}, bank=bank, call=call,
               since=now - timedelta(days=DEFAULT_DAYS))
    assert thin["skipped"] and not thin["projects"], "对照太薄的项目跳过, 不提题"
    m = merge([[dict(c, projects=["A"])], [dict(c, id="price_given", projects=["B"])]])
    assert len(m) == 1 and m[0]["projects"] == ["A", "B"], "同一个题目不同 id 合成一条"
    md = render(rep, dry_run=False)
    assert "mentions_price" in md and "第一段写了一个很具体的价格" not in md, "报告里不许有原文"
    bad = run(labels=labels, fetch_notes=lambda nids: {i: notes[i] for i in nids}, categories={}, bank=bank,
              call=lambda s, u: "不是 JSON", since=now - timedelta(days=DEFAULT_DAYS), per_group=10)
    assert bad["candidates"] == [] and "没拿到候选" in bad["dropped"][0], "一个项目失败不拖垮整季"
    print("discover_feature_candidates selftest: OK")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    ap.add_argument("--per-group", type=int, default=PER_GROUP)
    ap.add_argument("--projects", default="", help="逗号分隔只看这些项目; 留空 = 全部")
    ap.add_argument("--out", default="", help="报告写到这个 markdown 文件 (同名 .json 一并写)")
    ap.add_argument("--dry-run", action="store_true", help="只数样本, 不调模型")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        _selftest()
        return 0
    from _common import fetch_all_pages, get_supabase_client
    sb = get_supabase_client()
    bank = fb.load_bank()
    labels = fetch_all_pages(sb.schema("truth_vault").table("v_l2_labels")
                             .select("note_id, project_id, publish_time, y"), order_by="note_id")
    cats = {r["project_id"]: r.get("category") for r in fetch_all_pages(
        sb.schema("truth_vault").table("projects").select("project_id, category"), order_by="project_id")}

    def fetch_notes(nids: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for i in range(0, len(nids), 100):
            rows = (sb.schema("truth_vault").table("notes").select("note_id, title, body")
                    .in_("note_id", nids[i:i + 100]).execute()).data or []
            out.update({r["note_id"]: r for r in rows})
        return out

    call = None
    if not args.dry_run:
        from annotate_essence_pass import call_claude
        model = os.environ.get(MODEL_ENV, DEFAULT_MODEL)
        call = lambda system, user: call_claude(user, model, cached_system=system)  # noqa: E731
    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    projects = {p.strip() for p in args.projects.split(",") if p.strip()} or None
    # 定时跑时跳过 on_demand 的项目 (mapping 没经 preflight 拍板的表, 同 essence / curate 的闸, D-047); 判据只有一份:
    # _common.skip_on_demand_on_cron。mapping 读不出来的照跑 (同 skip_on_cron.py 的取向: 宁可吵不可静)。
    if os.environ.get("TV_SCHEDULED_RUN") == "true" or os.environ.get("GITHUB_EVENT_NAME") == "schedule":
        from _common import load_mapping, skip_on_demand_on_cron
        gated = set()
        for p in sorted({r["project_id"] for r in labels}):
            try:
                interval = (load_mapping(p).get("sync_config") or {}).get("sync_interval")
            except Exception:  # noqa: BLE001
                continue
            if skip_on_demand_on_cron(interval, True):
                gated.add(p)
        labels = [r for r in labels if r["project_id"] not in gated]
        if gated:
            print(f"定时跑, 跳过 on_demand 项目: {'、'.join(sorted(gated))}")
    report = run(labels=labels, fetch_notes=fetch_notes, categories=cats, bank=bank, call=call, since=since,
                 per_group=args.per_group, projects=projects)
    md = render(report, dry_run=args.dry_run)
    print(md)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        Path(args.out).with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.dry_run and not report["projects"]:
        print("::error::这一季没有一个项目的爆 / 趴够做对照 —— 标签视图可能空了, 去看 v_l2_labels")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
