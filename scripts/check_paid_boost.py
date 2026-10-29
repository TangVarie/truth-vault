#!/usr/bin/env python3
"""投流证据链 F1 的 Python 侧守卫 (D-133)。SQL 侧是 scripts/check_paid_boost.sql (CI 的 sql job 跑), 两边读同一份
夹具 scripts/check_paid_boost_cases.json。

跑法: cd scripts && python check_paid_boost.py

钉住五件事, 全部断行为 (D-051), 不断源码字符串 —— 第 ③ 段是故意改坏代码再跑一遍:
  ① 元素判据: 每个夹具格子拆成元素、逐个定类, 和夹具写的一致 (正例: M/D🍟、已投流，等回收数据、tier 源元素
     「关注后续流量」、维护时间 / 维护效果的四种写法; 反例: 准备投流、不投流、整串「关注后续流量 爆贴」、关注 / ✅ /
     控评 / 铺评那些取值、2/30🍟、Sep15🍟、贴进来的评论)。tier 源的 str() 形状也对得上 (SQL 那边拆的是它)。
  ② 整行: 夹具每一行过真的 transform_row —— paid_promoted 三态、paid_marker_unrecognized、reason 文本;
     白名单外的列 (RIO 帐号昵称、ANSHEN / XIWU_phase2 评论区快照、NUC 标题正文) 带 🍟 也不碰;
     并且 transform_row 写出的 raw_extra 和 check_paid_boost.sql 按夹具拼的那份一字不差 (SQL 夹具就是 sync 真写的形状)。
  ③ 反证 (改坏代码): 把 sync 的判据换回 A4 的子串判据 → 「准备投流」「整串关注后续流量」两行必须红;
     换成「整个 raw_extra 里有 🍟 就算」→ RIO / ANSHEN / XIWU_phase2 三个陷阱必须红; 把 _common 的元素判据换成子串 →
     元素段必须红。改不坏 (锚点找不到) 也算红 —— 那说明这段反证已经空跑了。
  ④ SQL ↔ Python 一致: 从 schemas/notes_v1_22_paid_boost_evidence.sql 里把 tv_classify_paid_element 的字面量、
     日期正则、白名单列、去空白字符集抠出来, 和 _common 的常量逐个比, 两个方向都比 (多一个少一个都红)。
  ⑤ 静态禁令: v1_22 和 sync 里不许出现「把 raw_extra / data_quality_flags 转成文本再搜 🍟」的写法,
     sync 里不许回到「'🍟' in _v」的子串判据; 禁令正则自己先对坏样本试一遍 (不然是空规则)。
  另: ci.yml 的 sql job 真的用 -v cases=… 跑了 check_paid_boost.sql (接线断了这一份 Python 守卫照样绿, 要看得见)。

挡不住什么: SQL 视图的行为 (事件去重、隔离原因、F2 读数) 不在这里, 在 check_paid_boost.sql; 运营换一种全新的写法
(比如「9月15日🍟」) 两边会一起判成认不出、进隔离 —— 那是对的, 但要人看隔离视图才知道 (verify #100)。
"""
from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import _common as c                                   # noqa: E402
import sync_feishu_notes_to_truth_vault as s          # noqa: E402

CASES = json.loads((HERE / "check_paid_boost_cases.json").read_text(encoding="utf-8"))
SQL_FILE = ROOT / "schemas" / "notes_v1_22_paid_boost_evidence.sql"
SYNC_FILE = HERE / "sync_feishu_notes_to_truth_vault.py"
CI_FILE = ROOT / ".github" / "workflows" / "ci.yml"

BASE_FM = {"标题": "title", "文案": "raw_content", "互动量": "interactions", "状态": "_status_raw"}
TIER_RULES = [{"match_contains": ["爆贴"], "tier": "爆"}, {"match_contains": ["无水花"], "tier": "趴"}]


def mapping_for(case: dict) -> dict:
    return {"project_id": "CI_V22_A", "platform": "xiaohongshu", "field_mapping": dict(BASE_FM),
            "tier_extraction": {"source": "状态字段", "rules": TIER_RULES},
            "project_specific_fields_to_raw_extra": list(case["declared"])}


def sql_fixture_raw_extra(case: dict) -> dict:
    """check_paid_boost.sql 按夹具拼 raw_extra 的规则 (改一边就要改另一边; ② 段证明它等于 transform_row 的输出)。"""
    f, declared = case["fields"], case["declared"]
    out = {k: v for k, v in f.items() if k in declared}
    und = {k: v for k, v in f.items() if k not in declared and k not in BASE_FM}
    if und:
        out["_undeclared"] = und
    if case.get("tier_repr") is not None:
        out["_tier_source_raw"] = case["tier_repr"]
    return out


# ── ① 元素判据 ─────────────────────────────────────────────────────────────
def element_failures(split=None, classify=None) -> list[str]:
    split = split or c.paid_cell_elements
    classify = classify or c.classify_paid_element
    bad = []
    for e in CASES["elements"]:
        got = [[t, classify(e["col"], t)] for t in split(e["cell"])]
        want = [x[:2] for x in e["expect"]]
        if got != want:
            bad.append(f'{e["id"]}: 期望 {want} 实得 {got}')
        if e["col"] == c.PAID_TIER_KEY and str(e["cell"]) != e["tier_repr"]:
            bad.append(f'{e["id"]}: tier_repr 不是 sync 写进 raw_extra 的 str() 形状: {str(e["cell"])!r} ≠ {e["tier_repr"]!r}')
    return bad


# ── ② 整行 ────────────────────────────────────────────────────────────────
def row_failures(mod) -> list[str]:
    bad = []
    for n in CASES["notes"]:
        note, _, _ = mod.transform_row(mapping_for(n), "rec_" + n["id"], dict(n["fields"]))
        fl = note.get("data_quality_flags") or {}
        want = n["expect_paid"]
        got = fl.get("paid_promoted", "<缺键>")
        if (want is None and "paid_promoted" in fl) or (want is not None and got is not want):
            bad.append(f'{n["id"]}: paid_promoted 期望 {want if want is not None else "<缺键>"} 实得 {got}')
        if fl.get("paid_marker_unrecognized") != n["expect_unrecognized"]:
            bad.append(f'{n["id"]}: paid_marker_unrecognized 期望 {n["expect_unrecognized"]} 实得 {fl.get("paid_marker_unrecognized")}')
        if n.get("trap") and ("paid_promoted_reason" in fl or "paid_marker_unrecognized" in fl):
            bad.append(f'{n["id"]}: 陷阱行 (🍟 在白名单外) 不该有任何投流痕迹: {fl}')
        if want is True and not fl.get("paid_promoted_reason"):
            bad.append(f'{n["id"]}: true 没带 reason')
        want_re = sql_fixture_raw_extra(n)
        got_re = note.get("raw_extra") or {}
        if got_re != want_re:
            bad.append(f'{n["id"]}: transform_row 的 raw_extra 和 SQL 夹具拼法不一致: {got_re} ≠ {want_re}')
    return bad


def check_reason_texts() -> None:
    """A4 的 reason 文本一字不差 (同一行每晚写同一份 JSON, 不制造 audit 噪音; 生产 20 行今天就是这些字)。"""
    m = mapping_for({"declared": ["维护情况", "关注情况"]})
    n, _, _ = s.transform_row(m, "r", {"维护情况": ["关注", "✅", "9/15🍟"], "关注情况": ["9/15🍟"]})
    assert n["data_quality_flags"]["paid_promoted_reason"] == "「维护情况」取值「9/15🍟」; 「关注情况」取值「9/15🍟」", n
    n, _, _ = s.transform_row(m, "r", {"维护情况": ["已投流，等回收数据"]})
    assert n["data_quality_flags"]["paid_promoted_reason"] == "「维护情况」取值「已投流，等回收数据」", n
    n, _, _ = s.transform_row(mapping_for({"declared": []}), "r", {"状态": ["关注后续流量", "爆贴"]})
    assert n["data_quality_flags"]["paid_promoted_reason"] == "tier 源含「关注后续流量」(运营 2026-09-22: 投流会给的标记)", n


# ── ③ 反证: 改坏代码再跑 ───────────────────────────────────────────────────
def mutant(replacements: list[tuple[str, str]], name: str):
    src = SYNC_FILE.read_text(encoding="utf-8")
    for old, new in replacements:
        k = src.count(old)
        assert k == 1, f"反证 {name} 的锚点在 sync 里出现 {k} 次 (应为 1): {old!r} —— 判据代码改了, 反证要跟着改, 不然是空跑"
        src = src.replace(old, new)
    mod = types.ModuleType(f"sync_mutant_{name}")
    mod.__file__ = str(SYNC_FILE)
    exec(compile(src, f"<{name}>", "exec"), mod.__dict__)
    return mod


def check_mutations() -> None:
    # (a) 退回 A4 的子串判据
    a = mutant([
        ("_cls = classify_paid_element(_col, _v)",
         '_cls = "paid_dated" if ("🍟" in _v or "投流" in _v or _v in ("已投流，等回收数据",)) else "non_paid"'),
        ("_cls = classify_paid_element(PAID_TIER_KEY, _v)",
         '_cls = "paid_undated" if "关注后续流量" in _v else "non_paid"'),
    ], "substring")
    fa = row_failures(a)
    for case_id in ("prepare", "tuge_plain"):
        assert any(x.startswith(case_id + ":") for x in fa), f"反证 (a) 子串判据没让「{case_id}」红 —— 守卫空跑: {fa}"
    # (b) 整个 raw_extra 里有 🍟 就算 (不看列)
    b = mutant([
        ("for _v in paid_cell_elements(_cm_cell(_col)):",
         'for _v in (["整块扫到🍟"] if _col == PAID_COLS[0] and "🍟" in json.dumps(_re_all, ensure_ascii=False) else []):'),
        ("_cls = classify_paid_element(_col, _v)", '_cls = "paid_dated"'),
    ], "blobscan")
    fb = row_failures(b)
    for case_id in ("trap_rio", "trap_anshen_live", "trap_xiwu"):
        assert any(x.startswith(case_id + ":") for x in fb), f"反证 (b) 整块扫 🍟 没让「{case_id}」红 —— 守卫空跑: {fb}"
    # (c) _common 的元素判据换成子串 → 元素段红
    def substring_classify(col, txt):
        if col in c.PAID_COLS:
            return "paid_dated" if ("🍟" in txt or "投流" in txt) else "non_paid"
        return c.classify_paid_element(col, txt)
    fc = element_failures(classify=substring_classify)
    for case_id in ("neg_prepare", "neg_not", "neg_sep15", "neg_pasted_comment"):
        assert any(x.startswith(case_id + ":") for x in fc), f"反证 (c) 子串元素判据没让「{case_id}」红: {fc}"
    print(f"  ③ 反证: 子串判据红 {len(fa)} 条 · 整块扫 🍟 红 {len(fb)} 条 · 元素子串红 {len(fc)} 条 (点名的都在)")


# ── ④ SQL ↔ Python 一致 ────────────────────────────────────────────────────
def _sql_function_body(sql: str, name: str) -> str:
    m = re.search(r"CREATE OR REPLACE FUNCTION truth_vault\." + name + r"\b.*?\$\$(.*?)\$\$", sql, re.S)
    assert m, f"v1_22 里找不到函数 {name}"
    return m.group(1)


def _sql_literals(body: str) -> set[str]:
    return {x.replace("''", "'") for x in re.findall(r"(?<![A-Za-z])'((?:[^']|'')*)'", body)}


def check_parity() -> None:
    sql = SQL_FILE.read_text(encoding="utf-8")
    body = _sql_function_body(sql, "tv_classify_paid_element")
    classes = {"paid_dated", "paid_undated", "marker_like_unrecognized", "non_paid",
               "ops_date", "ops_effect_numeric", "ops_effect_other"}
    want = ({*c.PAID_COLS, c.PAID_TIER_KEY, c.OPS_DATE_COL, c.OPS_EFFECT_COL,
             c.PAID_DATED_RE.pattern, c.PAID_MARKER_LIKE_RE.pattern, c.OPS_EFFECT_NUMERIC_RE.pattern,
             *c.PAID_UNDATED_EXACT, *c.PAID_TIER_EXACT} | classes)
    got = _sql_literals(body)
    assert got == want, (f"tv_classify_paid_element 的字面量和 _common 不一致: SQL 多 {sorted(got - want)} "
                         f"· SQL 少 {sorted(want - got)}")
    assert set(c.PAID_HIT_CLASSES) <= classes
    # 精确值在 SQL 里是 IN (...) 的成员, 不是正则
    for v in (*c.PAID_UNDATED_EXACT, *c.PAID_TIER_EXACT):
        assert re.search(r"txt IN \([^)]*'" + re.escape(v) + "'", body), f"「{v}」在 SQL 里不是精确匹配"
    # 日期正则在解析函数里也是同一个字面量
    assert "'" + c.PAID_DATED_RE.pattern + "'" in _sql_function_body(sql, "tv_parse_ops_date"), \
        "tv_parse_ops_date 里的 M/D🍟 正则和 _common.PAID_DATED_RE 不一致"
    # 白名单列: 元素视图读的就是这四列 (+ tier 源), 顺序也一样
    m = re.search(r"CROSS JOIN \(VALUES ((?:\('[^']+'\),?\s*)+)\) AS c\(col\)", sql)
    assert m, "元素视图里找不到白名单列的 VALUES 表"
    cols = tuple(re.findall(r"\('([^']+)'\)", m.group(1)))
    assert cols == (*c.PAID_COLS, c.OPS_DATE_COL, c.OPS_EFFECT_COL), f"元素视图白名单 {cols} 与 _common 不一致"
    # 预筛的键表也是这四列 (少一列 = 那一列的元素永远进不了视图, 且没有任何报错)
    prefilters = [tuple(re.findall(r"'([^']+)'", a)) for a in re.findall(r"\?\|\s*ARRAY\[([^\]]*)\]", sql)]
    assert len(prefilters) == 2 and all(p == cols for p in prefilters), f"元素视图预筛的键表和白名单不一致: {prefilters}"
    # 去空白: SQL 每个 btrim 都用同一个字符集, 而且等于 PAID_ELEM_WS
    trims = re.findall(r"btrim\([^;]*?,\s*(E'[^']*')\)", sql)
    assert trims and set(trims) == {r"E' \t\r\n'"}, f"SQL 的 btrim 字符集不统一: {set(trims)}"
    assert c.PAID_ELEM_WS == " \t\r\n"
    print(f"  ④ parity: 判据字面量 {len(want)} 个两边一致 · 白名单 {len(cols)} 列 · btrim {len(trims)} 处同一字符集")


# ── ⑤ 静态禁令 ─────────────────────────────────────────────────────────────
BANNED_SQL = [
    re.compile(r"(raw_extra|data_quality_flags|changed_cols|raw_cell|blob)\s*(?:\)\s*)?::\s*(text|varchar)", re.I),
    re.compile(r"\blike\s+'%[^']*(🍟|投流|薯条)", re.I),
]
BANNED_PY = [
    re.compile(r"""["'](?:🍟|投流|薯条|关注后续流量)["']\s+in\s+(?:str|repr|json\.dumps)\("""),
    re.compile(r"""["'](?:🍟|投流)["']\s+in\s+_v\b"""),
    re.compile(r"""_PAID_TIER_SRC_RE\.search\(tier_src_str\)"""),
]


def check_static_ban() -> None:
    # 规则先对坏样本试一遍: 抓不到就是空规则
    for pat, sample in ((BANNED_SQL[0], "WHERE raw_extra::text LIKE '%x%'"),
                        (BANNED_SQL[0], "WHERE (a.changed_cols)::text ~ 'x'"),
                        (BANNED_SQL[1], "WHERE x LIKE '%🍟%'"),
                        (BANNED_PY[0], 'if "🍟" in json.dumps(raw_extra):'),
                        (BANNED_PY[0], "if '🍟' in str(note):"),
                        (BANNED_PY[1], 'if "🍟" in _v or "投流" in _v:'),
                        (BANNED_PY[2], "if tier_src_seen and _PAID_TIER_SRC_RE.search(tier_src_str):")):
        assert pat.search(sample), f"禁令正则 {pat.pattern} 抓不到坏样本 {sample!r}"
    hits = []
    for f in sorted((ROOT / "schemas").glob("notes_v1_22*.sql")):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("--", 1)[0]
            hits += [f"{f.name}:{i}: {line.strip()}" for p in BANNED_SQL if p.search(code)]
    for i, line in enumerate(SYNC_FILE.read_text(encoding="utf-8").splitlines(), 1):
        code = line.split("#", 1)[0]
        hits += [f"{SYNC_FILE.name}:{i}: {line.strip()}" for p in BANNED_PY if p.search(code)]
    assert not hits, "整块扫 🍟 / 子串判据回来了 (D-133):\n  " + "\n  ".join(hits)
    print("  ⑤ 静态禁令: v1_22 / sync 里没有把 raw_extra 转文本搜 🍟、没有子串判据 (规则自测 7 条)")


def check_ci_wiring() -> None:
    ci = CI_FILE.read_text(encoding="utf-8")
    assert re.search(r'psql -v ON_ERROR_STOP=1 -v cases="\$\(cat scripts/check_paid_boost_cases\.json\)" '
                     r"-f scripts/check_paid_boost\.sql", ci), "ci.yml 的 sql job 没有用夹具跑 check_paid_boost.sql"
    assert ci.count("psql -v ON_ERROR_STOP=1 -f schemas/notes_v1_22_paid_boost_evidence.sql") == 2, \
        "ci.yml 要把 v1_22 apply 两遍 (幂等)"
    assert "python check_paid_boost.py" in ci and "scripts/check_paid_boost.py" in ci
    verify = (HERE / "verify_supabase_state.sql").read_text(encoding="utf-8")
    for ord_, needle in (("98", "v_paid_boost_evidence"), ("99", "v_paid_boost_quarantine"), ("100", "marker_like_unrecognized")):
        m = re.search(r"SELECT '" + ord_ + r"',.*?(?=\nUNION ALL|\n\))", verify, re.S)
        assert m and needle in m.group(0), f"verify_supabase_state.sql 要有 #{ord_} ({needle}) —— 生产 apply 之后靠它看证据链在不在、有没有漏网"


def main() -> int:
    fe = element_failures()
    assert not fe, "① 元素判据:\n  " + "\n  ".join(fe)
    print(f"  ① 元素判据: {len(CASES['elements'])} 个格子逐元素对上 (含 tier 源 str() 形状)")
    fr = row_failures(s)
    assert not fr, "② 整行:\n  " + "\n  ".join(fr)
    check_reason_texts()
    n_trap = sum(1 for n in CASES["notes"] if n.get("trap"))
    print(f"  ② 整行: {len(CASES['notes'])} 行过 transform_row (陷阱 {n_trap} 行不碰), raw_extra 与 SQL 夹具拼法一致, reason 与 A4 一字不差")
    check_mutations()
    check_parity()
    check_static_ban()
    check_ci_wiring()
    print("投流证据链 F1 (Python 侧): all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
