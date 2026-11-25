"""check_code_extractor_v2.py —— G-24 代码抽取器 code:v2 的守卫 (PR-1: 只加抽取器和开关, 默认不变)。

    python scripts/check_code_extractor_v2.py          # 全部 (§6 要 fastapi; 没装就跳过并说一声)

守得住什么:
  §1 v1 冻结: extract_hashtags / last_paragraph / first_sentence / _code_features_v1 的源码哈希和改动前一样;
     在固定夹具上 v1 的标签、切片、8 道代码题、原值四列的输出摘要和改动前一样 (摘要是用改动前的 feature_bank 算的)。
  §2 v2 的五类用例: 整行连写 4 个标签无残渣; 末尾连写串 (后面没有句末标点) 全是标签; 「#A#」后面接带句末标点的正文
     = 1 个标签 + 正文; 「#A[话题]#B[话题]#」; 裸「#A #B」。没有连写串的文本 v2 与 v1 逐字节一样。
     8 道代码题里会变的只有三道: body_len_bucket (残渣把 v1 的正文顶过 100 字)、hashtag_bucket、brand_first_position;
     body_question_marks 也数去掉标签的正文 (标签里的问号不算), 但问号数在 v1、v2 下永远一样: v2 只删后面没有句末标点的
     连写串, 串里本身没有问号 (穷举 ≤ 8 字的短串核这条)。所以「v2 的问号用 v1 剥离算」是等价改法, 测不出来也不用测。
     撤回条件的量法 brand_only_in_tags 与抽取器无关。
  §3 反证: 把 v2 换成 v1 (别名) → §2 红; 行上 extractor 写成 code:v1 → §4 红。
  §4 annotate_feature_pass: 不带开关 --code-only 照旧 22 行全是 code:v1、写 note_features、续跑看 code:v1;
     --code-extractor code:v2 → 22 行全是 code:v2、不写 note_features、续跑看 code:v2; 配模型跑 / 副题库 → 退出 2。
     count_unannotated_features --code-only --extractor code:v2 按 code:v2 数。
  §5 backfill-features.yml (bash 真跑): 输入校验 (v2 只配 code_only、只给主题库、闭集); note_ids 探针要 worker 回显
     code_extractor, 请求体只在 v2 时带它; 整项目循环: 先探一次、计数带 --extractor code:v2、请求体带 code_extractor;
     两种模式都是探针回显了、某一批没回显 → 停。
     gate2-run.yml: extractors 含 code:v2 (只限主题库) 时先跑 measure_g24_withdrawal.py; 过 / 没过都往下走, 数不出来停。
  §6 worker: _CODE_EXTRACTORS 与 fb.CODE_EXTRACTORS 逐字相同; 端点 (要 fastapi): 拼 --code-extractor 并回显,
     不带 code_only / 副题库 / 闭集外 → 400 不起子进程; 不带这个键时参数和响应和以前一样。
挡不住什么: 生产上 v2 抽得对不对 (撤回条件要等回填之后按 measure_g24_withdrawal.py 量); 闸二重读本身。
"""
from __future__ import annotations

import contextlib
import hashlib
import inspect
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import feature_bank as fb  # noqa: E402
import annotate_feature_pass as afp  # noqa: E402
import count_unannotated_features as cuf  # noqa: E402

# ── §1 v1 冻结 ────────────────────────────────────────────────────────────────
# 源码哈希 (inspect.getsource 的 sha256 前 16 位), 在改动前的 feature_bank.py (6022f85) 上算的。
FROZEN_SRC = {
    "extract_hashtags": "56fa2c605b7e4ff9",
    "last_paragraph": "f784dc41b8bf00d3",
    "first_sentence": "964300e46cc2bfce",
    "_code_features_v1": "4cf4d845927b5479",
    "code_features": "3ba67dbb4da1c4cd",
    "raw_counts": "161ca6a57d5824fa",
}
BRAND = ["某牌", "尼古丁贴"]
FIXTURES = [
    "【标题】戒烟第几天最难熬？\n【正文】上周三凌晨两点在公司茶水间饿醒。我妈：你身上什么味儿？\n你们戒烟第几天了？#戒烟#",
    "【标题】某牌真好用\n【正文】用了半个月，感觉还行。\n#护肤#好物#推荐#某牌",
    "【标题】分享\n【正文】今天去了公园😀😀，很开心！\n#A#B#C#D",
    "【标题】无\n【正文】#开场#今天说说尼古丁贴。真的有用吗？？\n最后问一句大家呢？",
    "【标题】标题12\n【正文】正文很短 #A[话题]#B[话题]#",
    "【正文】只有正文没有标题，某牌在中间出现了一下，后面还有很多很多字很多很多字。#x #y",
    "【标题】空\n【正文】",
    "【标题】长\n【正文】" + "这是一段很长的正文。" * 60 + "\n#某牌#尼古丁贴#戒烟",
    "【标题】@提到\n【正文】感谢 @朋友A 推荐，某牌～\n\n结尾一段话够十个字了吧？\n#a #b#c",
]
# 在改动前的 feature_bank.py 上算出来的 v1 输出摘要 (_v1_outputs 的 JSON → sha256)。
V1_DIGEST = "e368e8e74a5347faea9b5f33ec7981578a9f78de564a8e1f6502d2bca8e9a964"


def _v1_outputs(m) -> list:
    out = []
    for raw in FIXTURES:
        sp = m.build_spans(raw, mode="markers")
        tags, rest = m.extract_hashtags(sp["_body_untruncated"])
        out.append({"tags": tags, "rest": rest, "first": sp["first_sentence"], "last": sp["last_para"],
                    "lp": m.last_paragraph(sp["_body_untruncated"]), "fs": m.first_sentence(sp["_body_untruncated"]),
                    "code": {k: list(v) for k, v in m.code_features(sp, BRAND).items()},
                    "code_nobrand": {k: list(v) for k, v in m.code_features(sp, []).items()},
                    "raw": m.raw_counts(sp)})
    return out


def _digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def check_v1_frozen() -> None:
    for name, want in FROZEN_SRC.items():
        got = hashlib.sha256(inspect.getsource(getattr(fb, name)).encode("utf-8")).hexdigest()[:16]
        assert got == want, f"{name} 的源码变了 ({got} ≠ {want}) —— v1 是冻结的 (D-134 第 4 条), 改 v2 别碰它"
    got = _digest(_v1_outputs(fb))
    assert got == V1_DIGEST, f"v1 在夹具上的输出变了: {got} ≠ {V1_DIGEST}"
    assert fb.CODE_EXTRACTOR == "code:v1" and fb.CODE_EXTRACTORS == ("code:v1", "code:v2")
    print(f"  ✓ §1 v1 冻结: {len(FROZEN_SRC)} 个函数源码哈希不变; {len(FIXTURES)} 条夹具上 v1 输出摘要不变")


# ── §2 v2 用例 ───────────────────────────────────────────────────────────────

def v2_failures(m) -> list[str]:
    """v2 该有的行为; 返回不满足的条目 (空 = 全对)。反证时把模块里的 v2 换成 v1 再调一次, 必须有条目。"""
    bad = []

    def want(text, tags, rest_has=None, rest_lacks=()):
        got_tags, rest = m.extract_hashtags_v2(text)
        if sorted(got_tags) != sorted(tags):
            bad.append(f"{text!r}: 标签 {got_tags} ≠ {tags}")
        if rest_has is not None and rest_has not in rest:
            bad.append(f"{text!r}: 正文里该有 {rest_has!r}, 实得 {rest!r}")
        for x in rest_lacks:
            if x in rest:
                bad.append(f"{text!r}: 正文里不该有 {x!r}, 实得 {rest!r}")
    want("#A#B#C#D", ["A", "B", "C", "D"], rest_lacks=("A", "B", "C", "D", "#"))          # 整行连写
    want("用了半个月。\n#护肤#好物#推荐", ["护肤", "好物", "推荐"], "用了半个月。", ("好物",))      # 末尾一行连写
    want("说完了。#甲#乙#丙", ["甲", "乙", "丙"], "说完了。", ("乙",))                        # 同一行末尾、后面没有句末标点
    want("#A#今天很好。", ["A"], "今天很好。")                                              # 「#A#」+ 带句末标点的正文
    want("#A#B，C。", ["A"], "B，C。")                                                    # 后面有句末标点: 交回 v1
    want("#A[话题]#B[话题]#", ["A", "B"], rest_lacks=("B", "话题", "#"))
    want("#A #B", ["A", "B"], rest_lacks=("A", "B"))                                        # 裸标签
    want("#A##B#", ["A", "B"], rest_lacks=("A", "B"))                                       # 两个闭合标签紧挨着
    want("前面#A#B 中间。#C#D", ["A", "C", "D"], "B 中间。", ("D",))                          # 一行两串, 只拆后面那串
    # 没有连写串的文本: v2 与 v1 逐字节一样
    for raw in FIXTURES + ["#单个#", "#裸", "无标签。", "a #x# b #y#"]:
        if not m._V2_RUN.search(raw) and m.extract_hashtags_v2(raw) != m.extract_hashtags(raw):
            bad.append(f"{raw[:20]!r}: 没有连写串却和 v1 不一样")
    # 8 道代码题: 品牌只在连写标签里 → v1 后20%、v2 未出现; 不用「去掉标签的正文」的四道不变
    sp = m.build_spans("【标题】某牌好用\n【正文】这个月用下来感觉还可以，皮肤稳定了不少。\n#护肤#某牌#推荐#好物", mode="markers")
    v1, v2 = m.code_features(sp, BRAND), m.code_features_v2(sp, BRAND)
    if (v1["brand_first_position"][0], v2["brand_first_position"][0]) != ("后20%", "未出现"):
        bad.append(f"品牌只在连写标签里: v1/v2 = {v1['brand_first_position']} / {v2['brand_first_position']}, 期望 后20% / 未出现")
    if (v1["hashtag_bucket"][0], v2["hashtag_bucket"][0]) != ("1-3", ">=4"):
        bad.append(f"4 个连写标签: hashtag_bucket v1/v2 = {v1['hashtag_bucket']} / {v2['hashtag_bucket']}")
    for k in ("title_len_bucket", "title_has_digit", "emoji_bucket", "brand_in_title"):
        if v1[k] != v2[k]:
            bad.append(f"{k} 不该变: {v1[k]} → {v2[k]}")
    # body_len_bucket: 6 个连写标签, v1 留下 3 节残渣, 把正文顶过 100 字; v2 不留
    sp3 = m.build_spans("【标题】x\n【正文】" + "这个月用下来感觉还可以。" * 8
                        + "\n#护肤心得分享#好物推荐清单#敏感肌急救#换季护肤#平价好物#学生党必备", mode="markers")
    a, b = m.code_features(sp3, BRAND)["body_len_bucket"][0], m.code_features_v2(sp3, BRAND)["body_len_bucket"][0]
    if (a, b) != ("100-199", "<100"):
        bad.append(f"连写标签的残渣: body_len_bucket v1/v2 = {a} / {b}, 期望 100-199 / <100")
    # body_question_marks: 数去掉标签的正文, 标签里的问号不算 (不是数原文)
    sp4 = m.build_spans("【标题】x\n【正文】说完了。\n#真的有用吗？#护肤#好物", mode="markers")
    if m.code_features_v2(sp4, BRAND)["body_question_marks"][0] != "0":
        bad.append(f"标签里的问号算进了 body_question_marks: {m.code_features_v2(sp4, BRAND)['body_question_marks']}")
    if list(v2) != list(m.CODE_FEATURE_IDS_V1):
        bad.append(f"v2 的题序 {list(v2)} ≠ {list(m.CODE_FEATURE_IDS_V1)}")
    if m.brand_only_in_tags(sp, BRAND) is not True or m.brand_only_in_tags(sp, []) is not None:
        bad.append("brand_only_in_tags: 品牌只在标签里该是 True, 词典空该是 None")
    sp2 = m.build_spans("【标题】x\n【正文】我在用某牌。\n#某牌#护肤", mode="markers")
    if m.brand_only_in_tags(sp2, BRAND) is not False:
        bad.append("brand_only_in_tags: 正文里也有品牌该是 False")
    return bad


def qmark_invariant_failures(m, max_len: int = 8) -> list[str]:
    """性质: 问号数在 v1、v2 剥离下永远一样 (见文件头)。穷举 {A, #, ？, 空格} 上 ≤ max_len 字的串。"""
    import itertools
    bad = []
    for n in range(2, max_len + 1):
        for tup in itertools.product("A#？ ", repeat=n):
            t = "".join(tup)
            if "#" in t and "？" in t and m.extract_hashtags(t)[1].count("？") != m.extract_hashtags_v2(t)[1].count("？"):
                bad.append(repr(t))
                if len(bad) >= 3:
                    return bad
    return bad


def check_v2_cases() -> None:
    bad = v2_failures(fb)
    assert not bad, "v2 用例不过:\n  " + "\n  ".join(bad)
    bad = qmark_invariant_failures(fb)
    assert not bad, f"问号数在 v1 / v2 下不一样了 (文件头说永远一样, D-179 第 1 条也这么写): {bad}"
    import measure_g24_withdrawal as mw          # 撤回条件: 10% 正好算过, 词典空的不进分母
    rows = [{"project_id": "A", "only_in_tags": i == 0} for i in range(10)] + [{"project_id": "B", "only_in_tags": None}]
    r = mw.withdrawal_share(rows)
    assert (r["num"], r["den"], r["passed"]) == (1, 10, True), r
    assert mw.withdrawal_share(rows + [{"project_id": "B", "only_in_tags": True}])["passed"] is False
    assert mw.withdrawal_share([])["share"] is None and mw.THRESHOLD == 0.10 and mw.POSITION == "后20%"
    print("  ✓ §2 v2: 整行连写 / 末尾连写 / 「#A#」+ 正文 / [话题] / 裸标签 / 一行两串; 无连写串时与 v1 逐字节一样; "
          "只动三道题 (正文长度、标签数、品牌位置), 问号数穷举核过 v1 = v2; 撤回条件量法与抽取器无关")


class _Alias:
    """把 feature_bank 的 v2 换成 v1 的假模块 (反证用)。"""
    def __init__(self, base):
        self._b = base

    def __getattr__(self, k):
        if k == "extract_hashtags_v2":
            return self._b.extract_hashtags
        if k == "code_features_v2":
            return lambda sp, bw: self._b.code_features(sp, bw)
        return getattr(self._b, k)


def check_counterproofs() -> None:
    assert v2_failures(_Alias(fb)), "反证失败: v2 换成 v1 之后 §2 还是绿的 —— 用例测了个寂寞"
    print("  ✓ §3 反证: v2 别名成 v1 → §2 红")


# ── §4 annotate_feature_pass / count ─────────────────────────────────────────

NOTE = {"note_id": "T_1", "project_id": "T", "title": None,
        "raw_content": "【标题】某牌好用\n【正文】这个月用下来感觉还可以，皮肤稳定了不少。\n#护肤#某牌#推荐#好物",
        "target_blue_keywords": [], "projects": {"brand": "某牌", "product": "尼古丁贴"}}
MAPPING = {"project_id": "T", "field_mapping": {}, "title_extraction": "markers"}


def _run_main(argv, done_log, written, raw):
    saved = {k: getattr(afp, k) for k in ("get_supabase_client", "load_mapping", "fetch_notes", "fetch_done_ids",
                                         "write_answers", "write_raw_counts", "fetch_recovery_rows")}
    afp.get_supabase_client = lambda: object()
    afp.load_mapping = lambda pid: MAPPING
    afp.fetch_notes = lambda sb, pid: [NOTE, dict(NOTE, note_id="T_2"), dict(NOTE, note_id="T_3")]
    afp.fetch_done_ids = lambda sb, pid, **kw: (done_log.append(kw), {"T_2"})[1]
    afp.write_answers = lambda sb, rows, dry_run: written.extend(rows)
    afp.write_raw_counts = lambda sb, nid, counts, bv, dry_run: raw.append(nid)
    afp.fetch_recovery_rows = lambda *a: {}
    afp.logger.disabled = True
    try:
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            return afp.main(argv)
    finally:
        afp.logger.disabled = False
        for k, v in saved.items():
            setattr(afp, k, v)


def pass_failures() -> list[str]:
    """§4 的断言 (空 = 全对)。反证时把 code_rows 改成「v2 的行写成 code:v1」再调一次, 必须有条目。"""
    bad = []
    log, rows, raw = [], [], []
    rc = _run_main(["T", "--code-only"], log, rows, raw)
    if not (rc == 0 and len(rows) == 22 and {r["extractor"] for r in rows} == {"code:v1"} and raw == ["T_1", "T_3"]):
        bad.append(f"默认 --code-only: rc={rc} 行={len(rows)} 抽取器={ {r['extractor'] for r in rows} } note_features={raw}")
    if log != [{"run_tag": "primary", "code_only": True, "extractor": None}]:
        bad.append(f"默认 --code-only 的续跑查询变了: {log}")
    log, rows, raw = [], [], []
    rc = _run_main(["T", "--code-only", "--code-extractor", "code:v2"], log, rows, raw)
    exts = {r["extractor"] for r in rows}
    if not (rc == 0 and len(rows) == 22 and exts == {"code:v2"} and raw == []):
        bad.append(f"--code-extractor code:v2: rc={rc} 行={len(rows)} 抽取器={exts} note_features={raw}")
    if log != [{"run_tag": "primary", "code_only": True, "extractor": "code:v2"}]:
        bad.append(f"v2 的续跑要看 code:v2: {log}")
    by = {(r["subject_id"], r["question_id"]): r["answer"] for r in rows}
    if by.get(("T_1", "brand_first_position")) != "未出现" or not by.get(("T_1", "placebo_rand_1")):
        bad.append("v2 行: 品牌只在连写标签里该是 未出现, 占位题要照抄")
    for argv in (["T", "--code-extractor", "code:v2"], ["T", "--code-only", "--code-extractor", "code:v3"],
                 ["T", "--code-only", "--code-extractor", "code:v2", "--bank", "reader", "--note-ids", "T_1",
                  "--model", "m", "--run-tag", "fqr-x"]):
        log, rows, raw = [], [], []
        os.environ["ANTHROPIC_API_KEY"] = "x"
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                rc = _run_main(argv, log, rows, raw)
        except SystemExit as e:          # argparse 闭集外 → 2
            rc = e.code
        if rc != 2 or rows or raw:
            bad.append(f"{argv} 该退出 2、不写: rc={rc} 行={len(rows)}")
    return bad


def check_pass() -> None:
    bad = pass_failures()
    assert not bad, "annotate_feature_pass:\n  " + "\n  ".join(bad)
    real_rows = afp.code_rows
    afp.code_rows = lambda *a, **k: [dict(r, extractor=fb.CODE_EXTRACTOR) for r in real_rows(*a, **k)]
    try:
        assert pass_failures(), "反证失败: v2 的行写成 code:v1 (会盖掉 v1 的行) 也是绿的"
    finally:
        afp.code_rows = real_rows
    # code_rows 直接调: v2 只给主题库; 闭集外 → ValueError
    bank = fb.load_bank()
    sp = fb.build_spans(NOTE["raw_content"], mode="markers")
    for ext in ("code:v3", "llm:x"):
        try:
            afp.code_rows(bank, NOTE, sp, ["某牌"], "primary", ext)
            raise AssertionError(f"code_rows 收了 {ext}")
        except ValueError:
            pass
    # count_unannotated_features: --code-only --extractor code:v2 按 code:v2 数
    tables = {"notes": [{"note_id": n, "project_id": "T"} for n in ("T_1", "T_2", "T_3")],
              "note_feature_answers": [
                  {"subject_type": "note", "subject_id": "T_1", "question_id": "body_len_bucket", "run_tag": "primary", "extractor": "code:v1"},
                  {"subject_type": "note", "subject_id": "T_2", "question_id": "body_len_bucket", "run_tag": "primary", "extractor": "code:v1"},
                  {"subject_type": "note", "subject_id": "T_2", "question_id": "body_len_bucket", "run_tag": "primary", "extractor": "code:v2"}]}
    import check_feature_orchestration as cfo
    saved = (cuf.get_supabase_client, cuf.fetch_all_pages, afp.fetch_all_pages)
    cuf.get_supabase_client = lambda: cfo._SB(tables)
    cuf.fetch_all_pages = afp.fetch_all_pages = cfo._pages
    try:
        def count(argv):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                assert cuf.main(argv) == 0
            return buf.getvalue().strip()
        assert count(["T", "--code-only"]) == "1", "code:v1 口径: T_3 没跑"
        assert count(["T", "--code-only", "--extractor", "code:v2"]) == "2", "code:v2 口径: T_1 T_3 没跑"
    finally:
        cuf.get_supabase_client, cuf.fetch_all_pages, afp.fetch_all_pages = saved
    print("  ✓ §4 pass: 默认 --code-only 22 行全 code:v1 + 写 note_features + 续跑看 code:v1; code:v2 22 行全 code:v2、"
          "不写 note_features、续跑看 code:v2; 配模型跑 / 闭集外 / 副题库 → 退出 2; 计数按 code:v2 数; 反证 (写成 code:v1) 红")


# ── §5 backfill-features.yml ─────────────────────────────────────────────────

def _wf_steps() -> dict:
    import yaml
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "backfill-features.yml").read_text(encoding="utf-8"))
    assert wf[True]["workflow_dispatch"]["inputs"]["code_extractor"]["default"] == "code:v1"
    return {str(st.get("name", "")): st.get("run", "") for st in wf["jobs"]["backfill"]["steps"]}


def _bash(script: str, env: dict) -> subprocess.CompletedProcess:
    full = dict(os.environ)
    full["PATH"] = os.path.dirname(sys.executable) + os.pathsep + full.get("PATH", "")
    full.update(env)
    return subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script], cwd=str(ROOT / "scripts"),
                          env=full, capture_output=True, text=True, timeout=120)


_FAKE = r"""
curl() {
  local out="" body=""
  while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift 2;; -d) body="$2"; shift 2;; *) shift;; esac; done
  printf '%s\n' "$body" >> "$FAKE_DIR/bodies.jsonl"
  case "$body" in *'"dry_run":true'*) cp "$FAKE_DIR/probe.json" "$out";; *) cp "$FAKE_DIR/chunk.json" "$out";; esac
  printf 200
}
sleep() { :; }
python() {
  if [ "$1" = "count_unannotated_features.py" ]; then
    echo "$*" >> "$FAKE_DIR/count_args.txt"; n=$(wc -l < "$FAKE_DIR/count_args.txt")
    [ "$n" -le 1 ] && echo 3 || echo 0; return 0
  fi
  command python "$@"
}
"""


def _wf_run(script: str, env: dict, probe: dict, chunk: dict) -> tuple[int, str, list, list]:
    with tempfile.TemporaryDirectory() as td:
        Path(td, "probe.json").write_text(json.dumps(probe), encoding="utf-8")
        Path(td, "chunk.json").write_text(json.dumps(chunk), encoding="utf-8")
        r = _bash(_FAKE + script.replace("/tmp/", td + "/"), {"FAKE_DIR": td, "WORKER_URL": "http://w.invalid",
                                                             "WORKER_API_KEY": "k", **env})
        p, c = Path(td, "bodies.jsonl"), Path(td, "count_args.txt")
        bodies = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []
        counts = c.read_text(encoding="utf-8").splitlines() if c.exists() else []
        return r.returncode, r.stdout + r.stderr, bodies, counts


def check_workflow() -> None:
    steps = _wf_steps()
    val = next(v for k, v in steps.items() if k.startswith("Validate inputs"))
    ids = "NUC_phase1_recSynthA,NUC_phase1_recSynthB"
    base = {"PROJECT": "NUC_phase1", "BATCH": "6", "MAXB": "3", "NOTE_IDS": "", "RUN_TAG": "", "BANK_SHA": "",
            "REANNOTATE": "false", "MODEL": "", "CODE_ONLY": "true", "BANK": "", "CODE_EXTRACTOR": "code:v2"}
    for env in (base, {**base, "CODE_EXTRACTOR": ""}, {**base, "CODE_EXTRACTOR": "code:v1", "CODE_ONLY": "false"},
                {**base, "NOTE_IDS": ids, "PROJECT": "g24", "RUN_TAG": "primary"}):
        r = _bash(val, env)
        assert r.returncode == 0, (env, r.stdout[-300:], r.stderr[-300:])
    for patch, needle in (({"CODE_ONLY": "false"}, "只配 code_only=true"), ({"CODE_EXTRACTOR": "code:v3"}, "只能是 code:v1 / code:v2"),
                          ({"CODE_EXTRACTOR": "llm:x"}, "只能是 code:v1 / code:v2")):
        r = _bash(val, {**base, **patch})
        assert r.returncode != 0 and needle in r.stdout, (patch, r.stdout[-300:])
    # note_ids 模式: v2 要 worker 回显; 请求体只在 v2 时带 code_extractor
    nid = next(v for k, v in steps.items() if k.startswith("Run only the given note_ids"))
    line = "x · bank=fq-v0.1 sha=ba0f570c47d5… model=m run_tag=primary title_extraction=x"
    env = {"NOTE_IDS": ids, "BATCH": "6", "RUN_TAG": "primary", "MODEL": "", "BANK_SHA": "", "BANK": "",
           "REANNOTATE": "false", "CODE_ONLY": "true", "CODE_EXTRACTOR": "code:v2"}
    good = {"ok": True, "note_ids_count": 1, "code_extractor": "code:v2", "stderr_tail": line}
    chunk = {"ok": True, "note_ids_count": 2, "returncode": 0, "code_extractor": "code:v2", "stdout_tail": "Done: {}"}
    rc, out, bodies, _ = _wf_run(nid, env, good, chunk)
    assert rc == 0 and len(bodies) == 2 and all(b.get("code_extractor") == "code:v2" and b.get("code_only") for b in bodies), (rc, out[-500:], bodies)
    rc, out, bodies, _ = _wf_run(nid, env, {k: v for k, v in good.items() if k != "code_extractor"}, chunk)
    assert rc == 1 and "没回显 code_extractor=code:v2" in out and len(bodies) == 1, (rc, out[-400:])
    rc, out, bodies, _ = _wf_run(nid, env, good, {k: v for k, v in chunk.items() if k != "code_extractor"})
    assert rc == 1 and "换成了旧 worker" in out and len(bodies) == 2, (rc, out[-400:])
    rc, out, bodies, _ = _wf_run(nid, {**env, "CODE_EXTRACTOR": "code:v1"}, {k: v for k, v in good.items() if k != "code_extractor"},
                                 {k: v for k, v in chunk.items() if k != "code_extractor"})
    assert rc == 0 and len(bodies) == 2 and not any("code_extractor" in b for b in bodies), (rc, out[-400:], bodies)
    # 整项目循环: v2 先探一次、计数带 --extractor code:v2、请求体带 code_extractor; v1 时三样都和以前一样
    loop = next(v for k, v in steps.items() if k.startswith("Loop worker"))
    env = {"PROJECT": "NUC_phase1", "BATCH": "50", "MAXB": "3", "CODE_ONLY": "true", "CODE_EXTRACTOR": "code:v2"}
    rc, out, bodies, counts = _wf_run(loop, env, {"ok": True, "code_extractor": "code:v2"},
                                      {"ok": True, "returncode": 0, "code_extractor": "code:v2", "stdout_tail": "Done: {}"})
    assert rc == 0 and bodies[0].get("dry_run") and all(b.get("code_extractor") == "code:v2" for b in bodies), (rc, out[-500:], bodies)
    assert counts and all("--code-only --extractor code:v2" in c for c in counts), counts
    rc, out, bodies, counts = _wf_run(loop, env, {"ok": True}, {"ok": True, "returncode": 0, "stdout_tail": "Done: {}"})
    assert rc == 1 and "没回显 code_extractor=code:v2" in out and len(bodies) == 1, (rc, out[-400:])
    rc, out, bodies, counts = _wf_run(loop, env, {"ok": True, "code_extractor": "code:v2"},
                                      {"ok": True, "returncode": 0, "stdout_tail": "Done: {}"})
    assert rc == 1 and "换成了旧 worker" in out and len(bodies) == 2, ("整项目循环: 探针回显了、这一批没回显 → 该停", rc, out[-400:])
    rc, out, bodies, counts = _wf_run(loop, {**env, "CODE_EXTRACTOR": ""}, {"ok": True},
                                      {"ok": True, "returncode": 0, "stdout_tail": "Done: {}"})
    assert rc == 0 and bodies and not any("code_extractor" in b or b.get("dry_run") for b in bodies), (rc, out[-400:], bodies)
    assert counts and all(c.strip() == "count_unannotated_features.py NUC_phase1 --code-only" for c in counts), counts
    check_gate2_measure_step()
    print("  ✓ §5 backfill-features: v2 只配 code_only / 闭集; 探针和每一批都要回显 code_extractor (两种模式), 旧 worker 停; "
          "计数带 --extractor code:v2; 不给或给 code:v1 时请求体和计数参数和以前一样。"
          "gate2-run: 抽取器含 code:v2 才量撤回条件, 过 / 没过往下走, 数不出来停")


def check_gate2_measure_step() -> None:
    """gate2-run.yml 里量撤回条件那一步: 条件写对、排在闸二前面; bash 真跑 (假 python 给 0 / 1 / 2)。"""
    import yaml
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "gate2-run.yml").read_text(encoding="utf-8"))
    steps = wf["jobs"]["gate2"]["steps"]
    idx = [i for i, st in enumerate(steps) if "measure_g24_withdrawal.py" in (st.get("run") or "")]
    run_idx = next(i for i, st in enumerate(steps) if "python gate2_run.py --sha" in (st.get("run") or "")
                   and "--bank reader" not in (st.get("run") or ""))
    assert len(idx) == 1 and idx[0] < run_idx, f"gate2-run.yml 要有一步量撤回条件, 排在闸二之前: {idx} / {run_idx}"
    st = steps[idx[0]]
    assert st.get("if", "").strip() == "env.IN_BANK == 'primary'", st.get("if")   # 副题库不量; check_gate2_run 的模拟认这种写法
    assert st.get("working-directory") == "scripts", st

    def run(extractors: str, rc_py: int):
        with tempfile.TemporaryDirectory() as td:
            fake = f'python() {{ echo "fake $*" >> "{td}/argv"; echo "fake $*"; return {rc_py}; }}\n'
            r = _bash(fake + st["run"], {"IN_SHA": "ba0f570c", "IN_EXTRACTORS": extractors, "RUNNER_TEMP": td,
                                        "GITHUB_STEP_SUMMARY": str(Path(td, "sum.md"))})
            summ = Path(td, "sum.md").read_text(encoding="utf-8") if Path(td, "sum.md").exists() else ""
            called = Path(td, "argv").exists()
        return r, summ, called
    for rc_py, want_rc, needle in ((0, 0, "过了"), (1, 0, "没过"), (2, 2, "数不出来")):
        r, summ, called = run("code:v2, llm:claude-sonnet-5-5", rc_py)
        assert called and r.returncode == want_rc and needle in r.stdout and "measure_g24_withdrawal.py --sha ba0f570c" in summ, \
            (rc_py, r.returncode, r.stdout[-300:], summ[-300:])
    for ext in ("code:v1,llm:claude-sonnet-5-5", "code:v22,llm:x", ""):
        r, summ, called = run(ext, 1)
        assert r.returncode == 0 and not called and not summ and "不量" in r.stdout, (ext, r.returncode, r.stdout[-200:])


# ── §6 worker ────────────────────────────────────────────────────────────────

def check_worker() -> None:
    import re
    src = (ROOT / "worker" / "app.py").read_text(encoding="utf-8")
    m = re.search(r'^_CODE_EXTRACTORS = \(([^)]*)\)$', src, re.M)
    assert m and tuple(re.findall(r'"([^"]+)"', m.group(1))) == fb.CODE_EXTRACTORS, "worker _CODE_EXTRACTORS 与 fb 不一致"
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  ✓ §6 worker: _CODE_EXTRACTORS 与 fb.CODE_EXTRACTORS 一致 (没装 fastapi, 端点那半跳过)")
        return
    sys.path.insert(0, str(ROOT))
    os.environ.pop("WORKER_API_KEY", None)
    os.environ["WORKER_ALLOW_ANONYMOUS"] = "1"
    import worker.app as w
    seen: list = []
    real = w._run
    w._run = lambda script, args: (seen.append(list(args)), {"ok": True, "returncode": 0, "stdout_tail": "", "stderr_tail": ""})[1]
    try:
        c = TestClient(w.app)

        def post(**body):
            seen.clear()
            return c.post("/annotate-features", json={"project": "T", **body})
        r = post(code_only=True, code_extractor="code:v2")
        assert r.status_code == 200 and seen == [["T", "--limit", "50", "--code-only", "--code-extractor", "code:v2"]], seen
        assert r.json()["code_extractor"] == "code:v2"
        r = post(code_only=True)
        assert seen == [["T", "--limit", "50", "--code-only"]] and "code_extractor" not in r.json(), (seen, r.json())
        for body in ({"code_extractor": "code:v2"}, {"code_only": True, "code_extractor": "code:v3"},
                     {"code_only": True, "code_extractor": ["code:v2"]},
                     {"code_only": True, "code_extractor": "code:v2", "bank": "reader", "run_tag": "fqr-x",
                      "model": "m", "note_ids": ["T_recA"]}):
            r = post(**body)
            assert r.status_code == 400 and not seen, (body, r.status_code, seen)
    finally:
        w._run = real
        os.environ.pop("WORKER_ALLOW_ANONYMOUS", None)
    print("  ✓ §6 worker: _CODE_EXTRACTORS 一致; 拼 --code-extractor 并回显; 不带 code_only / 闭集外 / 副题库 → 400 不起子进程; "
          "不带这个键参数照旧")


def main() -> int:
    if "--print-v1-digest" in sys.argv:
        print(_digest(_v1_outputs(fb)))
        return 0
    check_v1_frozen()
    check_v2_cases()
    check_counterproofs()
    check_pass()
    check_workflow()
    check_worker()
    print("✓ G-24 code:v2 守卫全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
