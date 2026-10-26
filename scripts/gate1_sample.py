#!/usr/bin/env python3
"""gate1_sample.py —— 副题库 fq-v0.2-cand-reader 的闸一样本 / 闸二抽取名单 (D-128)。

只出名单, 不碰正文: 输出 CSV 只有 note_id / project_id / y / 三道分层题的答案 / 层 / 正文 md5, 能进仓库
(docs/28 §6.1 的「名单存档」; 正文留在库里和 scratchpad, D-079 ⑤)。不连库: 先 --print-sql 拿去只读 MCP /
SQL 编辑器跑, 结果存成文件, 再 --from-json。

    cd scripts && python gate1_sample.py --print-sql                       # 发现半的池子 SQL
    python gate1_sample.py --from-json pool.json --out ../data-analysis/gate1-reader-sample-2026-10-26.csv
    python gate1_sample.py --from-json pool.json --verify ../data-analysis/gate1-reader-sample-2026-10-26.csv
    python gate1_sample.py --print-sql --half holdout                      # 闸二: 留出半
    python gate1_sample.py --from-json holdout.json --half holdout --take all --out ../gate2-ids.csv

抽法 (D-128 写死, 改任何一条都要先改 D-128):
  · 池子 = v_l2_labels ∩ 主题库 ba0f570c 的 Sonnet 5.5 答案 (run_tag primary), ending_asks_reader 和
    asks_for_help 两题都要有答案 (闸二按它们分层)。快照的 sha / 抽取器取自副题库 yaml 的
    gate2.condition_snapshot (只有一份来源), title_is_question 拿不到 (没标题记 NULL) 的按「不是」算。
  · 半边: 发现半 = sha256(note_id) 首位十六进制为偶数 —— 直接调 discover_feature_candidates.in_discovery_half,
    不抄一份; SQL 里也按同一规则先筛一遍, 两边对不上 (导出混进了另一半) 就拒。
  · 剔掉 D-128 点名的 8 篇 (三组对照帖 6 篇 + D-127 材料里给 owner 看过的 2 篇)。
  · 层: A = 三题任一为「是」; B = 三题都不是「是」。层内按 sha256(种子 + ':' + note_id) 升序取;
    种子 fqr-g1-2026-10-26, 发现半 A 150 + B 50; 某层不够数就拒, 不悄悄少抽。
  · --half holdout (闸二抽取名单) 再加闸二的取数口径 (docs/28 §6.2, gate2_run): 有 essence、正文 ≥ 50 字
    (body_len 未知的不剔)、飞书里没删 (v_notes_vanished)。发现半不加 —— D-128 的池子没写这三条。
  · 每个 note_id 必须形如 <project_id>_rec…、项目有 mapping (backfill-features 的输入校验同一条)。

挡不住什么: 抽完以后库里的答案 / 标签再变 —— 名单是那一刻的快照, 进仓库之后就是唯一的样本; 拿新导出
--verify 对不上, 说明池子变了, 不说明名单错了。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import re
import sys
from collections import Counter
from pathlib import Path

import feature_bank as fb
from discover_feature_candidates import in_discovery_half
from gate1_agreement import load_pivot

ROOT = Path(__file__).resolve().parent.parent
SEED = "fqr-g1-2026-10-26"
CONDITION_QIDS = ("ending_asks_reader", "asks_for_help", "title_is_question")
REQUIRED_QIDS = ("ending_asks_reader", "asks_for_help")          # 闸二分层用, 两题都要有答案
EXCLUDE = (                                                     # D-128: 三组对照帖 6 篇 + D-127 给 owner 看过的 2 篇
    "SPX_phase1_reczz28NDCkUnZo2", "SPX_phase1_reczz28NDCsT0kYG",
    "HATHERINE_phase1_recvvVqwhU4bwj", "HATHERINE_phase1_reczz28PaNo98D3Z",
    "XIWU_phase2_reczz28PahXPKcbQ", "XIWU_phase2_reczz28Q05VZa80D",
    "HATHERINE_phase1_recvw1LdlTTJMM", "BJS_phase1_recvsWBVowMCHc",
)
TAKE_DISCOVERY = {"A": 150, "B": 50}
MIN_BODY_LEN = 50                                               # 闸二口径 (gate2_run: 正文 ≥ 50 字)
OUT_COLUMNS = ("note_id", "project_id", "y", "ear", "afh", "tiq", "stratum", "raw_md5")
# SQL 导出的列 (数组形式, 省体积); --from-json 也认同名键的对象
POOL_COLUMNS = ("note_id", "project_id", "y", "ear", "afh", "tiq", "n_ear", "n_afh", "n_tiq", "raw_md5",
                "has_essence", "body_len", "vanished")
_NOTE_ID = re.compile(r"^(?P<proj>[A-Za-z0-9_-]+?)_rec[A-Za-z0-9]+$")
_HALVES = ("discovery", "holdout")
_EVEN = ("0", "2", "4", "6", "8", "a", "c", "e")
_ODD = ("1", "3", "5", "7", "9", "b", "d", "f")


class SampleRefused(Exception):
    """池子 / 导出不对, 不出名单。"""


def condition_snapshot() -> tuple[str, str, dict[str, int]]:
    """(主题库 sha, Sonnet 抽取器, {分层题: 版本})。取自副题库 yaml 的 gate2.condition_snapshot, 和主题库对一遍。"""
    reader, primary = fb.load_bank_pair(fb.BANKS["reader"])
    snap = reader["gate2"]["condition_snapshot"]
    if snap["bank_sha256"] != primary["_sha256"] or snap.get("run_tag") != "primary":
        raise SampleRefused(f"condition_snapshot 不是当前主题库的 primary 快照: {snap}")
    if snap["extractors"] != ["llm:claude-sonnet-5-5"]:
        raise SampleRefused(f"D-128 只取 Sonnet 5.5 的分层答案, yaml 写的是 {snap['extractors']}")
    idx = fb.question_index(primary)
    return snap["bank_sha256"], snap["extractors"][0], {q: int(idx[q]["version"]) for q in CONDITION_QIDS}


def pool_sql(half: str = "discovery") -> str:
    if half not in _HALVES:
        raise SampleRefused(f"half 只能是 {_HALVES}")
    sha, ext, ver = condition_snapshot()
    qv = " or ".join(f"(question_id = '{q}' and question_version = {v})" for q, v in ver.items())
    digits = ", ".join(f"'{d}'" for d in (_EVEN if half == "discovery" else _ODD))
    cnt = ",\n         ".join(f"count(*) filter (where question_id = '{q}') as n_{k}"
                              for q, k in zip(CONDITION_QIDS, ("ear", "afh", "tiq")))
    ans = ",\n         ".join(f"max(answer) filter (where question_id = '{q}') as {k}"
                              for q, k in zip(CONDITION_QIDS, ("ear", "afh", "tiq")))
    return f"""-- gate1_sample.py --print-sql --half {half} · 只读 · 列: {', '.join(POOL_COLUMNS)}
with a as (
  select subject_id,
         {cnt},
         {ans}
  from truth_vault.note_feature_answers
  where subject_type = 'note' and run_tag = 'primary' and extractor = '{ext}'
    and bank_sha256 = '{sha}'
    and ({qv})
  group by 1)
select json_agg(json_build_array(l.note_id, l.project_id, l.y, a.ear, a.afh, a.tiq, a.n_ear, a.n_afh, a.n_tiq,
                                 md5(coalesce(n.raw_content, '')), n.emotional_lever is not null, f.body_len,
                                 v.note_id is not null) order by l.note_id)::text as pivot
from truth_vault.v_l2_labels l
join a on a.subject_id = l.note_id
join truth_vault.notes n on n.note_id = l.note_id
left join truth_vault.note_features f on f.note_id = l.note_id
left join truth_vault.v_notes_vanished v on v.note_id = l.note_id
where substr(encode(sha256(convert_to(l.note_id, 'UTF8')), 'hex'), 1, 1) in ({digits});"""


def load_pool(path: Path) -> list[dict]:
    """MCP / SQL 编辑器的导出 → [{POOL_COLUMNS…}]。行可以是数组 (pool_sql 的形状) 或同名键的对象。"""
    data = load_pivot(path)
    out = []
    for r in data:
        if isinstance(r, list):
            if len(r) != len(POOL_COLUMNS):
                raise SampleRefused(f"导出的行有 {len(r)} 列, 应是 {len(POOL_COLUMNS)} 列 ({POOL_COLUMNS})")
            out.append(dict(zip(POOL_COLUMNS, r)))
        elif isinstance(r, dict):
            missing = [c for c in POOL_COLUMNS if c not in r]
            if missing:
                raise SampleRefused(f"导出的行缺列 {missing}")
            out.append({c: r[c] for c in POOL_COLUMNS})
        else:
            raise SampleRefused("导出的行既不是数组也不是对象")
    return out


def rank_key(note_id: str, seed: str = SEED) -> str:
    return hashlib.sha256(f"{seed}:{note_id}".encode("utf-8")).hexdigest()


def stratum(r: dict) -> str:
    """A = ending_asks_reader / asks_for_help / title_is_question 任一为「是」; 否则 B (NULL 按「不是」)。"""
    return "A" if "是" in (r.get("ear"), r.get("afh"), r.get("tiq")) else "B"


def parse_take(spec: str, half: str) -> dict | None:
    """'150,50' → {A: 150, B: 50}; 'all' → None (全取)。不给: 发现半 = D-128 的 150/50, 留出半 = all。"""
    if not spec:
        return dict(TAKE_DISCOVERY) if half == "discovery" else None
    if spec == "all":
        return None
    m = re.fullmatch(r"(\d+),(\d+)", spec)
    if not m:
        raise SampleRefused(f"--take 要写成 A,B (如 150,50) 或 all, 实得 {spec!r}")
    return {"A": int(m.group(1)), "B": int(m.group(2))}


def build_sample(pool: list[dict], *, half: str = "discovery", take: dict | None = None,
                 seed: str = SEED, mappings_dir: Path | None = None) -> tuple[list[dict], dict]:
    """→ (名单行, 统计)。所有拒绝都在这里 (SampleRefused), 不写任何文件。"""
    if half not in _HALVES:
        raise SampleRefused(f"half 只能是 {_HALVES}")
    mdir = mappings_dir or (ROOT / "mappings")
    ids = [r["note_id"] for r in pool]
    dup = sorted(k for k, c in Counter(ids).items() if c > 1)
    if dup:
        raise SampleRefused(f"导出里 note_id 重复 {len(dup)} 个, 如 {dup[:3]} —— SQL 的 join 放大了行")
    wrong_half = [n for n in ids if in_discovery_half(n) != (half == "discovery")]
    if wrong_half:
        raise SampleRefused(f"{len(wrong_half)} 篇不在{'发现' if half == 'discovery' else '留出'}半 (如 {wrong_half[:3]}) —— "
                            "导出混进了另一半, 闸二会被污染 (D-120)")
    multi = [r["note_id"] for r in pool if any(int(r.get(k) or 0) > 1 for k in ("n_ear", "n_afh", "n_tiq"))]
    if multi:
        raise SampleRefused(f"{len(multi)} 篇的分层题在快照里有多行 (如 {multi[:3]}) —— 快照没钉住")
    bad_id, no_map = [], set()
    for r in pool:
        m = _NOTE_ID.match(r["note_id"])
        if not m or m.group("proj") != r["project_id"]:
            bad_id.append(r["note_id"])
        elif not (mdir / f"{r['project_id']}.yaml").is_file():
            no_map.add(r["project_id"])
    if bad_id:
        raise SampleRefused(f"{len(bad_id)} 个 note_id 不是 <project_id>_rec… (如 {bad_id[:3]}), backfill-features 收不了")
    if no_map:
        raise SampleRefused(f"这些项目没有 mapping, backfill-features 收不了: {sorted(no_map)}")
    for r in pool:
        if r.get("y") not in (0, 1):
            raise SampleRefused(f"{r['note_id']}: y={r.get('y')!r} 不是 0/1")
        if not re.fullmatch(r"[0-9a-f]{32}", str(r.get("raw_md5") or "")):
            raise SampleRefused(f"{r['note_id']}: raw_md5 不是 32 位十六进制")

    st = {"half": half, "seed": seed, "rows_with_any_answer": len(pool)}
    both = [r for r in pool if all(r.get(k) is not None for k in ("ear", "afh"))]
    st["pool_both_answered"] = len(both)
    excluded = sorted(r["note_id"] for r in both if r["note_id"] in EXCLUDE)
    st["excluded_present"] = excluded
    kept = [r for r in both if r["note_id"] not in EXCLUDE]
    if half == "holdout":
        drops = Counter()
        keep2 = []
        for r in kept:
            if r.get("vanished"):
                drops["vanished"] += 1
            elif not r.get("has_essence"):
                drops["no_essence"] += 1
            elif r.get("body_len") is not None and int(r["body_len"]) < MIN_BODY_LEN:
                drops["body_lt_50"] += 1
            else:
                keep2.append(r)
        st["gate2_filter_drops"] = dict(drops)
        kept = keep2
    st["pool"] = len(kept)
    by: dict[str, list[dict]] = {"A": [], "B": []}
    for r in kept:
        by[stratum(r)].append(r)
    for k in by:
        by[k].sort(key=lambda r: rank_key(r["note_id"], seed))
    st["pool_by_stratum"] = {k: len(v) for k, v in by.items()}
    if take is not None:
        short = {k: (len(by[k]), n) for k, n in take.items() if len(by[k]) < n}
        if short:
            raise SampleRefused("层里不够数 (有 / 要): " + ", ".join(f"{k} {h}/{n}" for k, (h, n) in short.items())
                                + " —— 不悄悄少抽; 改数要先改 D-128")
        chosen = {k: by[k][:take.get(k, 0)] for k in by}
    else:
        chosen = by
    rows = []
    for k in ("A", "B"):
        for r in chosen[k]:
            rows.append({"note_id": r["note_id"], "project_id": r["project_id"], "y": int(r["y"]),
                         "ear": r.get("ear"), "afh": r.get("afh"), "tiq": r.get("tiq"), "stratum": k,
                         "raw_md5": r["raw_md5"]})
    st["taken"] = {k: len(chosen[k]) for k in ("A", "B")}
    st["by_project"] = dict(sorted(Counter(r["project_id"] for r in rows).items()))
    st["y"] = {f"{s}{y}": sum(1 for r in rows if r["stratum"] == s and r["y"] == y) for s in ("A", "B") for y in (1, 0)}
    return rows, st


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(OUT_COLUMNS)
    for r in rows:
        w.writerow(["" if r[c] is None else r[c] for c in OUT_COLUMNS])
    return buf.getvalue()


def read_manifest(path: Path) -> list[dict]:
    """名单 CSV → 行 (空格子 → None, y → int)。列不对 / 重复 / 层不认识 → SampleRefused。下游 (gate1_models、
    做表、收表) 都走这一个函数读名单。"""
    with open(path, encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        if tuple(rd.fieldnames or ()) != OUT_COLUMNS:
            raise SampleRefused(f"{path}: 列应是 {OUT_COLUMNS}, 实得 {rd.fieldnames}")
        rows = [{k: (v if v != "" else None) for k, v in r.items()} for r in rd]
    ids = [r["note_id"] for r in rows]
    if len(ids) != len(set(ids)) or not ids:
        raise SampleRefused(f"{path}: 名单为空或 note_id 重复")
    for r in rows:
        r["y"] = int(r["y"])
        if r["stratum"] not in ("A", "B"):
            raise SampleRefused(f"{path}: {r['note_id']} 的 stratum={r['stratum']!r}")
    return rows


def summary_text(st: dict) -> str:
    lines = [f"half={st['half']} seed={st['seed']}",
             f"导出行 (三题任一有行) {st['rows_with_any_answer']} · 两道分层题都有答案 {st['pool_both_answered']}"
             f" · 剔掉 D-128 点名的 {len(st['excluded_present'])} 篇"
             + (f" · 闸二口径再剔 {st['gate2_filter_drops']}" if "gate2_filter_drops" in st else "")
             + f" → 池子 {st['pool']}",
             f"池子分层: A {st['pool_by_stratum']['A']} · B {st['pool_by_stratum']['B']}",
             f"取: A {st['taken']['A']} · B {st['taken']['B']} · y (A1/A0/B1/B0) {st['y']}",
             f"项目: {st['by_project']}"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--print-sql", action="store_true")
    ap.add_argument("--half", choices=_HALVES, default="discovery")
    ap.add_argument("--from-json", type=Path)
    ap.add_argument("--take", default="", help="A,B (发现半默认 150,50) 或 all (留出半默认)")
    ap.add_argument("--seed", default=SEED)
    ap.add_argument("--out", type=Path, help="写名单 CSV")
    ap.add_argument("--verify", type=Path, help="重算一遍, 和这份名单逐字节比 (不写)")
    a = ap.parse_args(argv)
    try:
        if a.print_sql:
            print(pool_sql(a.half))
            return 0
        if not a.from_json:
            ap.error("要 --print-sql 或 --from-json")
        rows, st = build_sample(load_pool(a.from_json), half=a.half, take=parse_take(a.take, a.half), seed=a.seed)
    except SampleRefused as exc:
        print(f"拒绝: {exc}", file=sys.stderr)
        return 2
    print(summary_text(st))
    text = to_csv(rows)
    if a.verify:
        same = a.verify.read_text(encoding="utf-8") == text
        print(f"verify {a.verify}: {'一致' if same else '不一致'}")
        if not same:
            return 1
    if a.out:
        a.out.write_text(text, encoding="utf-8")
        print(f"写到 {a.out} ({len(rows)} 篇, sha256 {hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
