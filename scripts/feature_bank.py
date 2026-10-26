"""scripts/feature_bank.py — 内容特征层的纯逻辑（docs/28 §4-§5, D-065 / D-070）。

只用标准库 + pyyaml, **不 import supabase / anthropic**, 让 CI 守卫和本地自检能在裸环境里跑
（同 deskcore/fingerprint.py 的取舍）。库 I/O 和 LLM 调用在 annotate_feature_pass.py。

这里住着:
  · 问题库的加载 / 校验和 / 结构校验（守卫 1）
  · 标题 / 正文切片: mapping 的 title_extraction (column / markers / none), 09-19 实查 17 张表
  · 四段输入 spans: title / first_sentence / last_para / body(≤1,500 字, 记截断) / full
  · 代码算的 8 个特征 + 3 道占位题（守卫 5）
  · 分组提示词: 一次调用只问一组、同组 ≤ 4 题（守卫 4）; Mode A 防泄漏（守卫 2）
  · 答案校验: 闭集 + 证据是原文子串 + 截断片段的「否」不算数（守卫 3）
  · 下发给写作台的规律列表: aw_instruction=never 的永不出现（守卫 7）
  · 副题库 (D-128): BANKS 闭集 / validate_secondary 跨库校验 / load_bank_pair / check_run_tag / done_marker;
    主题库没写那些键, 走的还是原来的路（scripts/check_secondary_bank.py）
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Optional

import yaml

BANK_PATH = Path(__file__).resolve().parent.parent / "prompts" / "feature_questions_v0_1.yaml"
# 副题库 (D-128): 读者提问方式两道候选题, 和冻结的主题库 fq-v0.1 并排放, 主题库一个字节不动。
# 抽取 / worker / workflow 只认这张表里的【键】(closed set), 不收任意路径 —— 走 HTTP 的永远是 "primary" / "reader"。
READER_BANK_PATH = BANK_PATH.parent / "feature_questions_v0_2_cand_reader.yaml"
BANKS = {"primary": BANK_PATH, "reader": READER_BANK_PATH}

MAX_GROUP_SIZE = 4          # docs/28 §5.3: 同组最多 4 题
BODY_CAP = 1500             # 与 essence 同一截断
EVIDENCE_MAX_CHARS = 30     # 证据片段上限（去空白后）
MIN_BODY_CHARS = 20         # 短于这个的正文不问模型
BOOL_VALUES = ("是", "否")
SPANS = ("title", "first_sentence", "last_para", "body", "full")
TRUNCATABLE_SPANS = ("body", "full")
LAYERS = ("surface", "essence")
HYPOTHESES = ("+", "-", "?")
TITLE_EXTRACTION_MODES = ("column", "markers", "none")
CODE_EXTRACTOR = "code:v1"
# 闸一裁决 (审计 B-17, D-103): 每道模型题一个 gate1_status。pending = 还没裁; pass / fail = docs/28 §6.1 的线;
# kappa_undefined = 样本里答案近乎常数, κ 算不出来 (不算没过, 闸二按 support 自己判)。fail 的题闸二一律打 unreliable。
GATE1_STATUSES = ("pending", "pass", "fail", "kappa_undefined")
GATE1_DEFAULT = "pending"

# ── 副题库 (D-128) ── 下面这些只在 yaml 写了对应键时才生效; 主题库一个都没写, 它的行为不变。
ROLE_SECONDARY = "secondary"
PRIMARY_DONE_MARKER = "has_specific_time"     # 主题库「这篇跑过」的标记题 (= annotate_feature_pass.DONE_MARKER_QUESTION)
GATE2_HALVES = ("holdout", "discovery", "all")
GATE2_PLACEBO = ("from_primary", "in_bank")
# 键白名单: 主题库今天用到的键 + 副题库新增的键。写错一个键 (conditonal_on) 不再被 yaml 静默吞掉 ——
# 它进了 digest, 却没有任何代码读它, 预注册等于没写。
TOP_LEVEL_KEYS = frozenset({
    "bank_version", "status", "frozen_sha256", "essence_vocab", "label_view", "spans", "families",
    "call_groups", "questions", "code_features", "placebo",
    "role", "primary_bank", "run_tag_prefix", "done_marker", "gate2"})
QUESTION_KEYS = frozenset({
    "id", "version", "gate1_status", "family", "group", "layer", "halflife_months", "type", "scope", "ask",
    "yes_if", "yes_examples", "no_if", "no_examples", "options", "evidence", "hypothesis", "why",
    "aw_instruction", "aw_instruction_values", "cross_check", "notes", "retired",
    "conditional_on", "contrast_base_excludes", "null_if_truncated"})
GATE2_KEYS = frozenset({"half", "condition_snapshot", "merged_contrasts", "confirmation_family", "placebo"})
_HEX64 = re.compile(r"[0-9a-f]{64}")
_RUN_TAG_PREFIX = re.compile(r"[a-z][a-z0-9]*-")

# invalid_reason 闭集（docs/28 §5.1 / 问题库答题契约）
INVALID_EVIDENCE_NOT_FOUND = "evidence_not_found"
INVALID_EVIDENCE_TOO_LONG = "evidence_too_long"
INVALID_OUT_OF_VOCAB = "out_of_vocab"
INVALID_MISSING = "missing"
INVALID_NO_TITLE = "no_title"
INVALID_TEXT_TOO_SHORT = "text_too_short"
INVALID_SPAN_TRUNCATED = "span_truncated"
INVALID_NO_BRAND_DICT = "no_brand_dict"
INVALID_JSON = "json_parse_failed"
INVALID_API = "api_error"
INVALID_FILTERED = "gateway_filtered"   # 中转站敏感词拦截 (D-125): 这组题记 NULL, 不算 systemic

# ── Mode A 防泄漏（照搬 annotate_essence_pass.build_mode_a_prompt 的两道, D-028）──
PERFORMANCE_KEYWORDS = (
    "tier", "大爆", "爆贴", "爆款", "爆率", "impressions", "reads", "interactions",
    "互动数", "阅读数", "曝光", "评论数", "performance", "实际表现", "点赞",
)
TEMPLATE_LEAK_PLACEHOLDERS = (
    "{performance", "{tier", "{interactions", "{reads", "{impressions", "{comments",
)

SYSTEM_TEMPLATE = """你在给一条小红书笔记做事实标注。只回答下面几道题，每题只看题目指定的那一段。
不要评价这条笔记好不好，也不要猜它的数据表现。每道题相互独立，不要用一道题的答案去推另一道。

{questions_block}

只输出 JSON，不要 markdown 包装、不要解释：
{{"answers":[{answers_example}]}}
规则：
- bool 题只答「是」或「否」；choice 题只从给出的选项里选一个，原样抄选项名。
- 需要证据时，evidence 必须从题目指定的那一段【原样抄】，不超过 {evidence_max} 字；不需要证据时 evidence 留空字符串。
- 拿不准就按题目里「算否」的标准答「否」，不要为了凑证据而硬答「是」。
- JSON 字符串里的英文双引号写成 \\"，字符串里不要换行（原文换行处直接接着抄）；整个回复只有这一个 JSON 对象。"""

SPAN_LABELS = {
    "title": "标题",
    "first_sentence": "正文第一句",
    "last_para": "正文最后一段",
    "body": "正文",
    "full": "标题+正文",
}


# ═══════════════════════════════════════════════════════════════════════
# 问题库
# ═══════════════════════════════════════════════════════════════════════

# 规范化时剔掉的两行: 二者都是「冻结」这个动作自己写的, 不是题目内容。
# 都是顶格 key（^ 锚在行首、不吃缩进）, 所以选项里的 status:/frozen_sha256: 不会误伤。
_META_LINES = re.compile(rb"(?m)^(?:frozen_sha256|status):.*(?:\r?\n|$)")
# gate1_status 是「对题的裁决」, 不是题目内容 (同 status / frozen_sha256 的道理): 裁一道题不该让 5,900 篇已落库的答案
# 全变成旧 sha。只匹配【缩进的】那一行 (题内字段), 顶格的 status: 走上面那条。
_GATE1_LINES = re.compile(rb"(?m)^[ \t]+gate1_status:.*(?:\r?\n|$)")


def bank_digest(raw: bytes) -> str:
    """问题库的**规范化**校验和: 把 `frozen_sha256:` 和 `status:` 两行剔掉之后再 hash。

    ⚠️ 为什么不直接 hash 整个文件 (codex review on #141, P1): 冻结那天要把算出来的
    digest 写回同一个文件的 `frozen_sha256:` 字段、并把 `status: draft` 改成
    `status: frozen`, 写回去文件字节就变了 —— 要求「文件 sha256 == 文件里记的那个
    sha256」是自指的, 算不出来。于是冻结这一步会让 validate_bank 永远报错、每次抽取
    直接退出 2。剔掉这两行之后, 冻结前后的 digest 完全一样: 冻结这个动作算得出来,
    落进 note_feature_answers.bank_sha256 的值也不会因为「冻结」把答案劈成两批。
    digest 管的是**题目内容**, 生命周期状态不在里头。
    闸一裁决 (gate1_status) 同理: 裁决是对题的评价, 改它不动题目内容 (D-103)。
    """
    return hashlib.sha256(_GATE1_LINES.sub(b"", _META_LINES.sub(b"", raw))).hexdigest()


def load_bank(path: Path | str = BANK_PATH) -> dict:
    """读问题库, 附上规范化 sha256（跑的时候记进每一行, D-041 的纪律）。"""
    raw = Path(path).read_bytes()
    bank = yaml.safe_load(raw)
    bank["_sha256"] = bank_digest(raw)
    bank["_path"] = str(path)
    return bank


def llm_questions(bank: dict) -> list[dict]:
    return [q for q in (bank.get("questions") or []) if not q.get("retired")]


def question_index(bank: dict) -> dict[str, dict]:
    return {q["id"]: q for q in llm_questions(bank)}


def validate_bank(bank: dict) -> list[str]:
    """结构校验（守卫 1）。返回错误列表, 空 = 合法。

    判据来自 docs/28 §4.1 六条规矩 + §5.3 分组约束 + §4.3 冻结纪律:
      id 唯一; 每题在且只在一个 call_group 里; 组 ≤ 4 题; bool 题有正反例; choice 题的
      hypothesis 键与选项一致; scope / layer / hypothesis / gate1_status 闭集; 冻结后 sha256 不变;
      冻结时每道模型题的 gate1_status 都不能还是 pending (闸一先裁完才能预注册, D-103)。
    """
    errs: list[str] = []
    if not bank.get("bank_version"):
        errs.append("缺 bank_version")
    groups: dict[str, list] = bank.get("call_groups") or {}
    if not groups:
        errs.append("缺 call_groups")
    qs = llm_questions(bank)
    ids = [q.get("id") for q in qs]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        errs.append(f"question id 重复: {dupes}")
    membership: dict[str, list[str]] = {}
    for g, members in groups.items():
        if not isinstance(members, list) or not members:
            errs.append(f"call_group {g} 不是非空列表")
            continue
        if len(members) > MAX_GROUP_SIZE:
            errs.append(f"call_group {g} 有 {len(members)} 题, 超过 {MAX_GROUP_SIZE}")
        for m in members:
            membership.setdefault(m, []).append(g)
    for q in qs:
        qid = q.get("id") or "<无 id>"
        for key in ("id", "version", "family", "group", "layer", "type", "scope", "ask", "hypothesis"):
            if q.get(key) in (None, ""):
                errs.append(f"{qid}: 缺 {key}")
        if not isinstance(q.get("version"), int) or q.get("version", 0) < 1:
            errs.append(f"{qid}: version 必须是 ≥1 的整数")
        if q.get("layer") not in LAYERS:
            errs.append(f"{qid}: layer={q.get('layer')!r} 不在 {LAYERS}")
        if q.get("scope") not in SPANS:
            errs.append(f"{qid}: scope={q.get('scope')!r} 不在 {SPANS}")
        where = membership.get(qid, [])
        if len(where) != 1:
            errs.append(f"{qid}: 应在且只在一个 call_group 里, 实际在 {where}")
        elif where[0] != q.get("group"):
            errs.append(f"{qid}: group={q.get('group')} 与 call_groups 登记的 {where[0]} 不一致")
        if q.get("type") == "bool":
            if not q.get("yes_examples") or not q.get("no_examples"):
                errs.append(f"{qid}: bool 题必须有 yes_examples 和 no_examples")
            if q.get("hypothesis") not in HYPOTHESES:
                errs.append(f"{qid}: bool 题 hypothesis={q.get('hypothesis')!r} 不在 {HYPOTHESES}")
        elif q.get("type") == "choice":
            opts = q.get("options") or []
            values = [o.get("value") if isinstance(o, dict) else o for o in opts]
            if len(values) < 2 or len(set(values)) != len(values):
                errs.append(f"{qid}: choice 题选项要 ≥2 且不重复")
            hyp = q.get("hypothesis")
            if not isinstance(hyp, dict) or set(hyp) != set(values):
                errs.append(f"{qid}: choice 题 hypothesis 的键必须与选项一致")
            elif any(v not in HYPOTHESES for v in hyp.values()):
                errs.append(f"{qid}: choice 题 hypothesis 取值不在 {HYPOTHESES}")
            # 选项级指令 (codex review on #141): choice 题的 aw_instruction 只对某些取值成立
            # (opening_type 的那句只对「具体事件」)。没声明 = 过了闸也不自动下发。
            vals = q.get("aw_instruction_values")
            if vals is not None:
                if not isinstance(vals, list) or not vals:
                    errs.append(f"{qid}: aw_instruction_values 必须是非空列表")
                elif any(v not in values for v in vals):
                    errs.append(f"{qid}: aw_instruction_values {vals} 里有不在选项里的值")
        else:
            errs.append(f"{qid}: type={q.get('type')!r} 不是 bool / choice")
        if q.get("type") == "bool" and q.get("aw_instruction_values") is not None:
            errs.append(f"{qid}: aw_instruction_values 只用于 choice 题 (bool 题的指令对应「是」)")
        if q.get("gate1_status", GATE1_DEFAULT) not in GATE1_STATUSES:
            errs.append(f"{qid}: gate1_status={q.get('gate1_status')!r} 不在 {GATE1_STATUSES}")
    for m in membership:
        if m not in ids:
            errs.append(f"call_groups 里的 {m} 不是问题库里的题")
    code_ids = [c.get("id") for c in (bank.get("code_features") or [])]
    plc_ids = [p.get("id") for p in (bank.get("placebo") or [])]
    all_ids = ids + code_ids + plc_ids
    clash = sorted({i for i in all_ids if all_ids.count(i) > 1})
    if clash:
        errs.append(f"模型题 / 代码特征 / 占位题 id 互相撞了: {clash}")
    for p in bank.get("placebo") or []:
        if str(p.get("hypothesis")) != "0":
            errs.append(f"占位题 {p.get('id')} 的 hypothesis 必须是 '0'")
    if bank.get("status") == "frozen":
        pending = [q.get("id") for q in qs if q.get("gate1_status", GATE1_DEFAULT) == GATE1_DEFAULT]
        if pending:
            errs.append(f"status=frozen 但 {len(pending)} 道题 gate1_status 还是 pending: {pending} —— 闸一裁完 (pass / fail / "
                        "kappa_undefined) 才能冻结, 预注册不能带着没裁的题 (审计 B-17, D-103)")
        want = bank.get("frozen_sha256")
        if not want:
            errs.append("status=frozen 但没记 frozen_sha256")
        elif bank.get("_sha256") and want != bank["_sha256"]:
            errs.append("status=frozen 但问题库规范化 sha256 与 frozen_sha256 不符 —— 冻结后改题要升 version 并记 DECISIONS "
                        f"(现在是 {bank['_sha256']})")
    errs += _validate_extensions(bank)
    return errs


def _options(q: dict) -> list:
    return [o.get("value") if isinstance(o, dict) else o for o in q.get("options") or []]


def _str_list(v) -> bool:
    """非空、元素都是非空字符串、不重复的列表。"""
    return isinstance(v, list) and bool(v) and all(isinstance(x, str) and x for x in v) and len(set(v)) == len(v)


def _validate_extensions(bank: dict) -> list[str]:
    """validate_bank 的追加检查 (D-128): 键白名单 + 副题库那几个新键。只拦主题库今天没用到的写法, 所以主题库照样返回 []。

    不查跨库的事 (conditional_on 是不是主题库的题、同 id 版本高不高) —— 那要两份题库一起看, 在 validate_secondary。
    """
    errs: list[str] = []
    qs = llm_questions(bank)
    idx = {q.get("id"): q for q in qs}
    ids = list(idx)
    code_ids = [c.get("id") for c in (bank.get("code_features") or []) if isinstance(c, dict)]
    plc_ids = [p.get("id") for p in (bank.get("placebo") or []) if isinstance(p, dict)]
    own = set(ids) | set(code_ids) | set(plc_ids)

    stray = sorted(str(k) for k in bank if not str(k).startswith("_") and k not in TOP_LEVEL_KEYS)
    if stray:
        errs.append(f"题库顶层有不认识的键 {stray} (白名单 TOP_LEVEL_KEYS; 写错的键进 digest 却没人读)")
    for q in bank.get("questions") or []:
        bad = sorted(str(k) for k in q if k not in QUESTION_KEYS)
        if bad:
            errs.append(f"{q.get('id') or '<无 id>'}: 不认识的键 {bad} (白名单 QUESTION_KEYS)")
    for qid, q in idx.items():
        cond = q.get("conditional_on")
        if cond is not None:
            if not _str_list(cond):
                errs.append(f"{qid}: conditional_on 必须是不重复的非空 id 列表")
            elif own & set(cond):
                errs.append(f"{qid}: conditional_on {sorted(own & set(cond))} 是本题库自己的题 —— 分层用的是主题库已有答案")
        exc = q.get("contrast_base_excludes")
        if exc is not None:
            opts = _options(q)
            if q.get("type") != "choice":
                errs.append(f"{qid}: contrast_base_excludes 只用于 choice 题")
            elif not _str_list(exc):
                errs.append(f"{qid}: contrast_base_excludes 必须是不重复的非空列表")
            elif any(v not in opts for v in exc):
                errs.append(f"{qid}: contrast_base_excludes {exc} 里有不在选项里的值")
            elif len(opts) - len(exc) < 2:
                errs.append(f"{qid}: contrast_base_excludes 剔完只剩 {len(opts) - len(exc)} 个取值, 至少要 2 个才比得起来")
        nit = q.get("null_if_truncated")
        if nit is not None:
            vocab = BOOL_VALUES if q.get("type") == "bool" else tuple(_options(q))
            if not _str_list(nit):
                errs.append(f"{qid}: null_if_truncated 必须是不重复的非空列表")
            elif any(v not in vocab for v in nit):
                errs.append(f"{qid}: null_if_truncated {nit} 里有不在闭集里的值")
            elif q.get("scope") not in TRUNCATABLE_SPANS:
                errs.append(f"{qid}: null_if_truncated 只对 scope 为 {TRUNCATABLE_SPANS} 的题有意义 (别的段不截断)")

    role = bank.get("role")
    if role is not None and role != ROLE_SECONDARY:
        errs.append(f"role={role!r} 只能不写 (主题库) 或 {ROLE_SECONDARY!r}")
    marker = bank.get("done_marker")
    if marker is not None and marker not in ids:
        errs.append(f"done_marker={marker!r} 不是本题库的模型题 (断点续跑靠它判「这篇跑过」)")
    if role == ROLE_SECONDARY:
        pb = bank.get("primary_bank")
        if not isinstance(pb, dict) or not isinstance(pb.get("sha256"), str) or not _HEX64.fullmatch(pb["sha256"]) \
                or not pb.get("bank_version"):
            errs.append("副题库要写 primary_bank: {bank_version, sha256 (64 位小写十六进制)}")
        prefix = bank.get("run_tag_prefix")
        if not isinstance(prefix, str) or not _RUN_TAG_PREFIX.fullmatch(prefix):
            errs.append(f"副题库要写 run_tag_prefix (小写字母开头、以 - 结尾, 如 fqr-), 实得 {prefix!r}")
        if marker is None:
            errs.append("副题库要写 done_marker (本库的一道模型题), 不能借主题库的 has_specific_time")
        if bank.get("gate2") is None:
            errs.append("副题库要写 gate2 块 (闸二的比法跑之前写死, D-128)")
    unimpl = [c for c in code_ids if c not in CODE_FEATURE_IMPL]
    if unimpl:
        errs.append(f"code_features {unimpl} 没有实现 (CODE_FEATURE_IMPL) —— 写进题库却永远不出行")
    g2 = bank.get("gate2")
    if any(q.get("conditional_on") for q in qs) and not (isinstance(g2, dict) and isinstance(g2.get("condition_snapshot"), dict)):
        errs.append("有题写了 conditional_on, gate2.condition_snapshot 必须写明分层答案取自哪份快照")

    if g2 is None:
        return errs
    if not isinstance(g2, dict):
        return errs + ["gate2 必须是映射"]
    bad = sorted(str(k) for k in g2 if k not in GATE2_KEYS)
    if bad:
        errs.append(f"gate2 有不认识的键 {bad} (白名单 GATE2_KEYS)")
    if g2.get("half") not in GATE2_HALVES:
        errs.append(f"gate2.half={g2.get('half')!r} 不在 {GATE2_HALVES}")
    snap = g2.get("condition_snapshot")
    if snap is not None:
        ex = snap.get("extractors") if isinstance(snap, dict) else None
        if not isinstance(snap, dict) or not isinstance(snap.get("bank_sha256"), str) \
                or not _HEX64.fullmatch(snap["bank_sha256"]) or not snap.get("run_tag") \
                or not isinstance(ex, list) or not ex or not all(isinstance(e, str) and e.startswith("llm:") for e in ex):
            errs.append("gate2.condition_snapshot 要写 {bank_sha256 (64 位), extractors (非空, llm:…), run_tag}")
    merged_labels: dict[str, set] = {}
    mcs = g2.get("merged_contrasts") or []
    if not isinstance(mcs, list):
        errs.append("gate2.merged_contrasts 必须是列表")
        mcs = []
    for m in mcs:
        mq = idx.get(m.get("question_id")) if isinstance(m, dict) else None
        if mq is None or mq.get("type") != "choice":
            errs.append(f"gate2.merged_contrasts {m!r}: question_id 必须是本库的 choice 模型题")
            continue
        opts, vals, label = _options(mq), m.get("values"), m.get("label")
        exc = set(mq.get("contrast_base_excludes") or [])
        if not _str_list(vals) or len(vals) < 2 or any(v not in opts for v in vals):
            errs.append(f"gate2.merged_contrasts {mq['id']}: values {vals} 要 ≥2 个、不重复、都在选项里")
        elif exc & set(vals):
            errs.append(f"gate2.merged_contrasts {mq['id']}: values 和 contrast_base_excludes 撞了 {sorted(exc & set(vals))}")
        elif len(opts) - len(exc) - len(vals) < 1:
            errs.append(f"gate2.merged_contrasts {mq['id']}: 合并后对照组一个取值都不剩")
        if not isinstance(label, str) or not label or label in opts:
            errs.append(f"gate2.merged_contrasts {mq['id']}: label 必须是非空、且不和选项重名")
        if m.get("hypothesis") not in HYPOTHESES:
            errs.append(f"gate2.merged_contrasts {mq['id']}: hypothesis={m.get('hypothesis')!r} 不在 {HYPOTHESES}")
        if isinstance(label, str):
            merged_labels.setdefault(mq["id"], set()).add(label)
    fam = g2.get("confirmation_family")
    if not isinstance(fam, list) or len(fam) != 2:
        errs.append("gate2.confirmation_family 必须正好 2 行 (D-128: BH 只在这两行里做)")
        fam = fam if isinstance(fam, list) else []
    seen = set()
    for row in fam:
        if not isinstance(row, list) or len(row) != 2:
            errs.append(f"gate2.confirmation_family 的行 {row!r} 必须是 [question_id, 取值]")
            continue
        qid, val = row
        q = idx.get(qid) if isinstance(qid, str) else None
        if q is None:
            errs.append(f"gate2.confirmation_family {row}: {qid!r} 不是本库的模型题 (代码特征 / 占位题不进确认族)")
            continue
        if q.get("type") == "bool":
            ok = val == "是"
        else:
            ok = (val in _options(q) and val not in (q.get("contrast_base_excludes") or [])) \
                or val in merged_labels.get(qid, set())
        if not ok:
            errs.append(f"gate2.confirmation_family {row}: 取值不成立 (bool 只认「是」; choice 认选项或 merged_contrasts 的 label, "
                        "不能是 contrast_base_excludes)")
        if (qid, str(val)) in seen:
            errs.append(f"gate2.confirmation_family {row} 重复")
        seen.add((qid, str(val)))
    plc = g2.get("placebo")
    if plc not in GATE2_PLACEBO:
        errs.append(f"gate2.placebo={plc!r} 不在 {GATE2_PLACEBO}")
    elif plc == "in_bank" and not plc_ids:
        errs.append("gate2.placebo=in_bank 但本库没有占位题")
    elif plc == "from_primary" and role != ROLE_SECONDARY:
        errs.append("gate2.placebo=from_primary 只用于副题库")
    return errs


# ═══════════════════════════════════════════════════════════════════════
# 副题库 (D-128): 跨库校验 / 读两份 / run_tag / 续跑标记
# ═══════════════════════════════════════════════════════════════════════

def _all_ids(bank: dict) -> set:
    return ({q.get("id") for q in llm_questions(bank)}
            | {c.get("id") for c in (bank.get("code_features") or []) if isinstance(c, dict)}
            | {p.get("id") for p in (bank.get("placebo") or []) if isinstance(p, dict)})


def validate_secondary(bank: dict, primary: dict) -> list[str]:
    """副题库对主题库的跨库校验。返回错误列表, 空 = 合法。

    · 主题库必须 frozen, 且 _sha256 == frozen_sha256 == 副题库 primary_bank.sha256 (gate2.condition_snapshot 同);
    · conditional_on 的每道题都是主题库的模型题, 且闸一 pass (拿闸一没过的题分层 = 拿噪声分层);
    · 组名不和主题库撞; 同 id 的题版本必须更高 ((question_id, question_version) 跨库唯一, invites_sharing 2 > 1);
    · done_marker 和代码特征 id 都不是主题库的 id (否则续跑会把主题库的行当成本库跑过);
    · bank_version 和主题库不同。
    """
    errs: list[str] = []
    if bank.get("role") != ROLE_SECONDARY:
        return [f"不是副题库 (role={bank.get('role')!r})"]
    psha = primary.get("_sha256")
    if primary.get("status") != "frozen":
        errs.append("主题库没冻结, 副题库不能钉在它上面")
    if not psha or primary.get("frozen_sha256") != psha:
        errs.append(f"主题库 frozen_sha256 与规范化 digest 不符 ({str(primary.get('frozen_sha256'))[:12]} vs {str(psha)[:12]})")
    pb = bank.get("primary_bank") if isinstance(bank.get("primary_bank"), dict) else {}
    if pb.get("sha256") != psha:
        errs.append(f"primary_bank.sha256 {str(pb.get('sha256'))[:12]} 不是当前主题库 {str(psha)[:12]}")
    if pb.get("bank_version") != primary.get("bank_version"):
        errs.append(f"primary_bank.bank_version {pb.get('bank_version')!r} 不是当前主题库 {primary.get('bank_version')!r}")
    g2 = bank.get("gate2") if isinstance(bank.get("gate2"), dict) else {}
    snap = g2.get("condition_snapshot")
    if isinstance(snap, dict) and snap.get("bank_sha256") != psha:
        errs.append(f"gate2.condition_snapshot.bank_sha256 {str(snap.get('bank_sha256'))[:12]} 不是主题库 {str(psha)[:12]}")
    pidx = question_index(primary)
    for q in llm_questions(bank):
        for c in q.get("conditional_on") or []:
            if c not in pidx:
                errs.append(f"{q.get('id')}: conditional_on 的 {c!r} 不是主题库的模型题")
            elif pidx[c].get("gate1_status") != "pass":
                errs.append(f"{q.get('id')}: conditional_on 的 {c!r} 闸一不是 pass ({pidx[c].get('gate1_status')!r})")
        pq = pidx.get(q.get("id"))
        if pq is not None and not (isinstance(q.get("version"), int) and q["version"] > int(pq.get("version") or 0)):
            errs.append(f"{q.get('id')}: 和主题库同 id, version 必须 > 主题库的 {pq.get('version')} (实得 {q.get('version')})")
    clash = sorted(set(bank.get("call_groups") or {}) & set(primary.get("call_groups") or {}))
    if clash:
        errs.append(f"组名和主题库撞了: {clash}")
    pids = _all_ids(primary)
    if bank.get("done_marker") in pids:
        errs.append(f"done_marker={bank.get('done_marker')!r} 是主题库的 id —— 续跑会把主题库的行当成本库跑过")
    shared_code = sorted({c.get("id") for c in (bank.get("code_features") or []) if isinstance(c, dict)} & pids)
    if shared_code:
        errs.append(f"代码特征 {shared_code} 是主题库的 id —— 副题库只写自己声明的新特征, 不碰主题库的行")
    if bank.get("bank_version") == primary.get("bank_version"):
        errs.append(f"bank_version 和主题库一样 ({bank.get('bank_version')!r})")
    return errs


def load_bank_pair(path: Path | str) -> tuple[dict, dict]:
    """读副题库 + 主题库, 两道校验 (validate_bank 各自 + validate_secondary) 有一条不过就 raise ValueError。"""
    bank = load_bank(path)
    primary = load_bank(BANK_PATH)
    errs = ([f"主题库: {e}" for e in validate_bank(primary)] + validate_bank(bank)
            + validate_secondary(bank, primary))
    if errs:
        raise ValueError(f"副题库 {path} 不合法: " + "; ".join(errs))
    return bank, primary


def check_run_tag(bank: dict, run_tag: Optional[str]) -> Optional[str]:
    """副题库只许写在自己的 run_tag 前缀下 (fqr-*)。返回错误信息, None = 可以。主题库不管 (照旧)。

    为什么要拦: note_feature_answers 的主键不含 bank_sha256, 副题库用 run_tag=primary 跑会按同一主键盖掉主题库的行。"""
    if bank.get("role") != ROLE_SECONDARY:
        return None
    prefix = bank.get("run_tag_prefix") or ""
    if not run_tag or run_tag == "primary":
        return f"副题库 {bank.get('bank_version')} 不能用 run_tag={run_tag!r} (主题库的行会被同主键覆盖)"
    if not prefix or not run_tag.startswith(prefix) or run_tag == prefix:
        return f"副题库 {bank.get('bank_version')} 的 run_tag 必须以 {prefix!r} 开头且后面还有字, 实得 {run_tag!r}"
    return None


def done_marker(bank: dict) -> str:
    """断点续跑判「这篇跑过」用哪道题: 题库写了 done_marker 就用它, 没写 (主题库) 照旧 has_specific_time。"""
    return bank.get("done_marker") or PRIMARY_DONE_MARKER


# ═══════════════════════════════════════════════════════════════════════
# 切片: 标题 / 正文
# ═══════════════════════════════════════════════════════════════════════

_BRACKET_TITLE = re.compile(r"【\s*标\s*题\s*】")
_BRACKET_BODY = re.compile(r"【\s*正\s*文\s*】")
_COLON_TITLE = re.compile(r"标题\s*[：:]")
_COLON_BODY = re.compile(r"(?:^|\n)\s*正文\s*[：:]")
_LEADING_TAG = re.compile(r"^\s*【[^】\n]{1,12}】\s*")   # 「【粉饼贴】标题：…」这种前缀


def split_title_body(raw: str, mode: str, title_col: Optional[str] = None
                     ) -> tuple[Optional[str], str, str]:
    """按 mapping 的 title_extraction 切出 (title, body, how)。

    mode:
      column  — 标题在独立列 (TGV)。正文若以标题开头就把它去掉。
      markers — 文案里带标记。同一个解析器认两种写法（一张表里可能混用, 09-19 实查:
                HXZ_QD / NUC / WTG 两种都有）:
                  「【标题】…【正文】…」   「标题：…\\n正文：…」（冒号全角半角都有, 前面可带【xx】）
                切不出来 → title None（标题类题目记 NULL, 不猜）。
      none    — 没有标题。
    how 记录实际用了哪条路（column / bracket / colon / none）, 闸一登记切法用。
    """
    raw = raw or ""
    if mode not in TITLE_EXTRACTION_MODES:
        raise ValueError(f"title_extraction={mode!r} 不在 {TITLE_EXTRACTION_MODES}")
    if mode == "column":
        title = (title_col or "").strip() or None
        body = raw
        if title and body.lstrip().startswith(title):
            body = body.lstrip()[len(title):]
        return title, _strip_markers(body), "column"
    if mode == "none":
        return None, _strip_markers(raw), "none"

    m_t = _BRACKET_TITLE.search(raw)
    if m_t:
        rest = raw[m_t.end():]
        m_b = _BRACKET_BODY.search(rest)
        if m_b:
            title, body = rest[:m_b.start()], rest[m_b.end():]
        else:
            title, body = _first_line_split(rest)
        title = title.strip() or None
        return title, _strip_markers(body), "bracket"

    head = _LEADING_TAG.sub("", raw, count=1)
    m_t = _COLON_TITLE.match(head.lstrip())
    if m_t:
        rest = head.lstrip()[m_t.end():]
        m_b = _COLON_BODY.search(rest)
        if m_b:
            title, body = rest[:m_b.start()], rest[m_b.end():]
        else:
            title, body = _first_line_split(rest)
        title = title.strip() or None
        return title, _strip_markers(body), "colon"
    return None, _strip_markers(raw), "none"


def _first_line_split(text: str) -> tuple[str, str]:
    """没有正文标记时: 第一行非空文本当标题, 其余当正文。"""
    lines = text.lstrip("\n").split("\n", 1)
    if len(lines) == 1:
        return lines[0], ""
    return lines[0], lines[1]


def _strip_markers(text: str) -> str:
    text = _BRACKET_TITLE.sub("", text)
    text = _BRACKET_BODY.sub("", text)
    text = re.sub(r"(?:^|\n)\s*正文\s*[：:]\s*", "\n", text)
    return text.strip()


# ═══════════════════════════════════════════════════════════════════════
# 话题标签 / 表情 / 句子
# ═══════════════════════════════════════════════════════════════════════

_HASHTAG_CLOSED = re.compile(r"#([^#\s\[\]]{1,40}?)(?:\[话题\])?#")
_HASHTAG_BARE = re.compile(r"#([^\s#\[\]]{1,40})")
_MENTION = re.compile(r"@[^\s@]{1,30}")
# 表情: 剥掉变体选择符后, 把「基字 + 肤色修饰 + ZWJ 连接的后续基字」整串算【一个】。
# ⚠️ 原来的写法把 U+FE0F 当成独立字符匹配, 于是「❤️」「☀️」各记 2 个、一家三口的 ZWJ
# 串记 3 个 —— 分档直接从 1-3 跳到 >=4, 污染闸二 (codex review on #141)。
_EMOJI_BASE = "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2190-\u21FF\u2300-\u23FF]"
_SKIN = "[\U0001F3FB-\U0001F3FF]"
_VARIATION = re.compile("[\uFE0E\uFE0F]")
_EMOJI_SEQ = re.compile(f"{_EMOJI_BASE}(?:{_SKIN})?(?:\u200d{_EMOJI_BASE}(?:{_SKIN})?)*")
_BRACKET_EMOJI = re.compile(r"\[[^\[\]\n]{1,10}R\]")   # 小红书方括号表情 [哭惹R]
_EMOJI = re.compile(f"{_EMOJI_SEQ.pattern}|{_BRACKET_EMOJI.pattern}")   # 只用于剥除, 不用于计数
_SENTENCE_END = re.compile(r"[。！？!?…\n]")
_WS = re.compile(r"\s+")


def extract_hashtags(text: str) -> tuple[list[str], str]:
    """返回 (标签列表, 去掉标签后的文本)。同时认「#…#」「#…[话题]#」和裸「#词」三种。"""
    tags: list[str] = []

    def _grab(m):
        tags.append(m.group(1).strip())
        return " "
    cleaned = _HASHTAG_CLOSED.sub(_grab, text)
    cleaned = _HASHTAG_BARE.sub(_grab, cleaned)
    return tags, cleaned


def count_mentions(text: str) -> int:
    return len(_MENTION.findall(text or ""))


def count_emoji(text: str) -> int:
    """可见表情个数: 变体选择符不单独算, ZWJ 串 / 肤色修饰算一个, 方括号表情算一个。"""
    t = _VARIATION.sub("", text or "")
    return len(_EMOJI_SEQ.findall(t)) + len(_BRACKET_EMOJI.findall(t))


def visible_len(text: str) -> int:
    return len(_WS.sub("", text or ""))


def first_sentence(body: str) -> str:
    """去掉开头的标签、表情后, 到第一个 。！？!?… 或换行为止; 不足 6 字就并入下一句。"""
    _, text = extract_hashtags(body or "")
    text = _EMOJI.sub("", text).strip()
    parts = [p.strip() for p in _SENTENCE_END.split(text)]
    parts = [p for p in parts if p]
    if not parts:
        return ""
    out = parts[0]
    i = 1
    while visible_len(out) < 6 and i < len(parts):
        out = out + parts[i]
        i += 1
    return out


def last_paragraph(body: str) -> str:
    """去掉末尾的标签和 @ 之后, 最后一个非空段落; 不足 10 字就往上再并一段。"""
    _, text = extract_hashtags(body or "")
    text = _MENTION.sub("", text)
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    if not paras:
        return ""
    out = paras[-1]
    i = len(paras) - 2
    while visible_len(out) < 10 and i >= 0:
        out = paras[i] + "\n" + out
        i -= 1
    return out


# ═══════════════════════════════════════════════════════════════════════
# spans
# ═══════════════════════════════════════════════════════════════════════

def build_spans(raw_content: str, *, mode: str, title_col: Optional[str] = None) -> dict:
    """代码先切好四段 + 元信息。模型只看题目 scope 指定的那段（docs/28 §5.1）。"""
    title, body, how = split_title_body(raw_content, mode, title_col)
    truncated = len(body) > BODY_CAP
    body_capped = body[:BODY_CAP]
    full = (f"{title}\n{body_capped}" if title else body_capped)
    return {
        "title": title,                     # None = 拿不到
        "first_sentence": first_sentence(body_capped),
        # ⚠️ 结尾那段必须从【没截断】的正文取 (codex review on #141): 从 body_capped 取
        # 等于把中间某一段当成结尾, 而 last_para 不在 TRUNCATABLE_SPANS 里 —— 模型对着
        # 中段答 ending_asks_reader 还会被判成有效答案。这一段本来就短, 不受 1,500 字约束。
        "last_para": last_paragraph(body),
        "body": body_capped,
        "full": full,
        "_body_untruncated": body,
        "_truncated": truncated,
        "_title_how": how,
    }


# ═══════════════════════════════════════════════════════════════════════
# 代码算的特征 + 占位题
# ═══════════════════════════════════════════════════════════════════════

_DIGIT = re.compile(r"[0-9０-９]")


def _bucket(n: int, edges: list[tuple[int, str]], last: str) -> str:
    for upper, label in edges:
        if n <= upper:
            return label
    return last


def brand_dictionary(project: dict, note: dict, mapping: Optional[dict] = None) -> list[str]:
    """品牌词 / 产品词词典: projects.brand + product + 笔记 target_blue_keywords + mapping.brand_aliases。
    占位（(未填) / 待确认 这种）交给运营补 aliases(Q3 / I-12), 这里只做形状过滤。"""
    cands: list[str] = []
    for v in (project.get("brand"), project.get("product")):
        if isinstance(v, str):
            cands.append(v)
    for v in (note.get("target_blue_keywords") or []):
        if isinstance(v, str):
            cands.append(v)
    for v in ((mapping or {}).get("brand_aliases") or []):
        if isinstance(v, str):
            cands.append(v)
    out = []
    for c in cands:
        c = c.strip()
        if len(c) < 2 or c.startswith("(") or "待" in c and len(c) <= 4:
            continue
        if c not in out:
            out.append(c)
    return out


def _find_brand(text: str, words: list[str]) -> int:
    """第一个品牌词出现的位置（字符下标）, 不区分大小写; 没有 → -1。"""
    low = (text or "").lower()
    best = -1
    for w in words:
        i = low.find(w.lower())
        if i >= 0 and (best < 0 or i < best):
            best = i
    return best


# 主题库 fq-v0.1 的 8 个代码特征 (默认就算这 8 个, 一个不多: 多一行就改了冻结题库的产出, 31/22 行的计数会红)。
CODE_FEATURE_IDS_V1 = ("body_len_bucket", "title_len_bucket", "title_has_digit", "body_question_marks",
                       "emoji_bucket", "hashtag_bucket", "brand_in_title", "brand_first_position")
# 实现了的全部代码特征: 题库 code_features 里写的 id 必须在这里 (validate_bank)。新的只在 only= 点名时才算。
CODE_FEATURE_IMPL = CODE_FEATURE_IDS_V1 + ("last_para_has_qmark",)


def code_features(spans: dict, brand_words: list[str], only: Optional[list[str]] = None
                  ) -> dict[str, tuple[Optional[str], Optional[str]]]:
    """代码特征 → {id: (answer, invalid_reason)}。分档固定, 不按项目分位（docs/28 §4.4）。

    only=None (主题库, 所有现有调用方): 原样回那 8 个, 与 D-128 之前逐字节一致。
    only=[ids] (副题库): 只回点名的那几个, 顺序照 only; 点了没实现的 id → ValueError。
    """
    if only is None:
        return _code_features_v1(spans, brand_words)
    unknown = [i for i in only if i not in CODE_FEATURE_IMPL]
    if unknown:
        raise ValueError(f"代码特征 {unknown} 没有实现 (CODE_FEATURE_IMPL)")
    v1 = _code_features_v1(spans, brand_words) if any(i in CODE_FEATURE_IDS_V1 for i in only) else {}
    out: dict[str, tuple[Optional[str], Optional[str]]] = {}
    for i in only:
        out[i] = last_para_has_qmark(spans) if i == "last_para_has_qmark" else v1[i]
    return out


def last_para_has_qmark(spans: dict) -> tuple[Optional[str], Optional[str]]:
    """正文最后一段 (同 last_para 切法: 去掉末尾话题标签和 @) 里有没有 ？ 或 ?。副题库 D-128 的探索特征, 不进确认族。

    spans 里没有 last_para (check_external_direction 传的那种只有正文的 spans) 就从没截断的正文现切; 段落为空 → text_too_short。"""
    lp = spans.get("last_para")
    if lp is None:
        lp = last_paragraph(spans.get("_body_untruncated") or "")
    if visible_len(lp) == 0:
        return None, INVALID_TEXT_TOO_SHORT
    return ("是" if ("？" in lp or "?" in lp) else "否"), None


def _code_features_v1(spans: dict, brand_words: list[str]) -> dict[str, tuple[Optional[str], Optional[str]]]:
    """主题库的 8 个代码特征 (D-128 之前的 code_features 原文, 只改了名字)。"""
    body = spans["_body_untruncated"]
    title = spans["title"]
    tags, body_wo_tags = extract_hashtags(body)
    blen = visible_len(body_wo_tags)
    out: dict[str, tuple[Optional[str], Optional[str]]] = {}
    out["body_len_bucket"] = (_bucket(blen, [(99, "<100"), (199, "100-199"), (399, "200-399")], ">=400"), None)
    if title is None:
        out["title_len_bucket"] = (None, INVALID_NO_TITLE)
        out["title_has_digit"] = (None, INVALID_NO_TITLE)
    else:
        out["title_len_bucket"] = (_bucket(visible_len(title), [(10, "<=10"), (15, "11-15")], ">=16"), None)
        out["title_has_digit"] = ("是" if _DIGIT.search(title) else "否", None)
    qm = body_wo_tags.count("？") + body_wo_tags.count("?")
    out["body_question_marks"] = (_bucket(qm, [(0, "0"), (1, "1")], ">=2"), None)
    em = count_emoji(body)
    out["emoji_bucket"] = (_bucket(em, [(0, "0"), (3, "1-3")], ">=4"), None)
    out["hashtag_bucket"] = (_bucket(len(tags), [(0, "0"), (3, "1-3")], ">=4"), None)
    if not brand_words:
        out["brand_in_title"] = (None, INVALID_NO_BRAND_DICT)
        out["brand_first_position"] = (None, INVALID_NO_BRAND_DICT)
    else:
        if title is None:
            out["brand_in_title"] = (None, INVALID_NO_TITLE)
        else:
            out["brand_in_title"] = ("是" if _find_brand(title, brand_words) >= 0 else "否", None)
        pos = _find_brand(body_wo_tags, brand_words)
        n = max(len(body_wo_tags), 1)
        if pos < 0:
            out["brand_first_position"] = ("未出现", None)
        elif pos / n < 0.2:
            out["brand_first_position"] = ("前20%", None)
        elif pos / n >= 0.8:
            out["brand_first_position"] = ("后20%", None)
        else:
            out["brand_first_position"] = ("中间", None)
    return out


def raw_counts(spans: dict) -> dict[str, int]:
    """数值原值, 写 note_features 现有列。"""
    body = spans["_body_untruncated"]
    tags, _ = extract_hashtags(body)
    return {
        "title_len": visible_len(spans["title"]) if spans["title"] is not None else None,
        "body_len": visible_len(extract_hashtags(body)[1]),
        "hashtag_count": len(tags),
        "mention_count": count_mentions(body),
    }


def placebo_answer(note_id: str, k: int) -> str:
    """sha256(note_id + ':fq-placebo-k') 最后一位十六进制 < 8 记「是」。确定性, 与内容无关。"""
    h = hashlib.sha256(f"{note_id}:fq-placebo-{k}".encode("utf-8")).hexdigest()
    return "是" if int(h[-1], 16) < 8 else "否"


def placebo_answers(bank: dict, note_id: str) -> dict[str, str]:
    out = {}
    for i, p in enumerate(bank.get("placebo") or [], start=1):
        out[p["id"]] = placebo_answer(note_id, i)
    return out


# ═══════════════════════════════════════════════════════════════════════
# 提示词（分组）
# ═══════════════════════════════════════════════════════════════════════

def _render_question(n: int, q: dict) -> str:
    label = SPAN_LABELS[q["scope"]]
    lines = [f"{n}. {q['id']} · 看【{label}】· {q['ask']}"]
    if q["type"] == "bool":
        ye = " / ".join(q.get("yes_examples") or [])
        ne = " / ".join(q.get("no_examples") or [])
        lines.append(f"   算「是」：{q.get('yes_if', '')} 例：{ye}")
        lines.append(f"   算「否」：{q.get('no_if', '')} 例：{ne}")
    else:
        lines.append("   选项：")
        for o in q.get("options") or []:
            if isinstance(o, dict):
                lines.append(f"   - {o['value']}：{o.get('means', '')} 例：{o.get('example', '')}")
            else:
                lines.append(f"   - {o}")
    ev = q.get("evidence")
    if ev:
        lines.append(f"   证据：{ev}")
    return "\n".join(lines)


_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*\r?\n(.*?)\r?\n```\s*$", re.S)
# 三元组: id / answer / evidence 三个键按这个顺序相邻 (SYSTEM_TEMPLATE 给的样例就是这个顺序)。
# evidence 是对象里最后一个键, 所以它的结尾锚在『" 后面紧跟 }』—— 不锚在逗号上:
# 原文里 `",` 太常见 (引完一句话接逗号), 锚逗号会把证据截成前缀, 而前缀仍是原文子串, 守卫 3 拦不住,
# 30 字上限也只对截断后的字符串生效 (自审 on #156)。
_ANSWER_RE = re.compile(
    r'"id"\s*:\s*"(?P<id>[A-Za-z0-9_]+)"\s*,\s*'
    r'"answer"\s*:\s*"(?P<answer>[^"]*)"\s*,\s*'
    r'"evidence"\s*:\s*"(?P<evidence>.*?)"\s*}', re.S)
_TRIPLE_KEYS = ("id", "answer", "evidence")


def _json_string(s: str) -> str:
    """把正则捞出来的字符串体按 JSON 字符串解码 (\\n \\" \\\\ \\uXXXX …); 解不开就原样。
    只替换 \\" 的话, evidence 里一个合法的 \\n 会变成字面的反斜杠 n, 子串校验必失败 → 好答案被判
    evidence_not_found、还进不了单问兜底 (自审 on #156)。"""
    try:
        return json.loads('"' + s + '"', strict=False)
    except (json.JSONDecodeError, ValueError):
        return s


def _first_object(t: str):
    """从第一个 { 起解析【第一个】完整 JSON 值, 后面跟着闲话也不管 (rfind 最后一个 } 会被闲话里的
    大括号带偏)。严格 / 宽松各试一次。解不出返回 None。"""
    lo = t.find("{")
    if lo == -1:
        return None
    for strict in (True, False):
        try:
            obj, _ = json.JSONDecoder(strict=strict).raw_decode(t, lo)
            return obj
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _coerce_answers(obj) -> Optional[dict]:
    """JSON 解析出来了但形状不对时尽量扶正: 裸的 {id, answer, evidence} → 包一层; 键名打错
    ({"answer": [...]}) 或 answers 是单个对象 → 找到那个『带 id 的对象 / 对象列表』。扶不正 → None。"""
    if isinstance(obj, dict) and isinstance(obj.get("answers"), list):
        return obj
    if isinstance(obj, dict) and all(k in obj for k in _TRIPLE_KEYS):
        return {"answers": [obj]}
    if isinstance(obj, dict):
        for v in obj.values():
            if isinstance(v, list) and v and all(isinstance(x, dict) and "id" in x for x in v):
                return {"answers": v}
            if isinstance(v, dict) and all(k in v for k in _TRIPLE_KEYS):
                return {"answers": [v]}
    if isinstance(obj, list) and obj and all(isinstance(x, dict) and "id" in x for x in obj):
        return {"answers": obj}
    return None


def parse_answers(raw: str) -> Optional[dict]:
    """把模型回复解析成 {"answers": [...]}; 解析不出来返回 None。

    比 annotate_essence_pass.parse_claude_json 多几层容错, 只针对本 pass 这个【固定、扁平】的
    形状 (answers 是 {id, answer, evidence} 的列表), 不通用:
      1. 去掉 markdown 围栏, 从第一个 { 起解析第一个完整 JSON 值 (后面的闲话不算数)。
      2. 先严格再 strict=False: 允许字符串里出现原样换行 / 控制符。evidence 是从正文原样抄的,
         抄到换行处模型常常直接把换行写进字符串 —— 严格 JSON 会整段解析失败, 于是整组题
         全记 missing (2026-09-23 闸一 100 篇里 59 格 missing 都是整组一起没的, D-083)。
      3. 解析出来但形状不对 (裸三元组 / 键名打错 / answers 是对象) → _coerce_answers 扶正。
      4. 还不行就按正则逐条捞 "id" / "answer" / "evidence" 三元组: evidence 里没转义的英文双引号
         (原文含 " 时模型照抄) 会让 JSON 断在中间, 但三元组本身还在。evidence 的结尾锚在
         『" 后面紧跟 }』(它是最后一个键), 内嵌的 `"` `",` 都不会截错; 捞出的字符串体按 JSON
         字符串解码 (\\n / \\" / \\uXXXX 还原)。
    捞出来的东西照旧过 validate_answers: 证据必须是原文子串、≤ 30 字, 所以捞错了只会变 NULL,
    不会变成错答案 (守卫 3 仍在)。挡不住: 捞到的证据恰好也是原文别处的子串。
    这个函数不碰网络, check_feature_parse.py 有正反例。
    """
    if not raw:
        return None
    t = raw.strip()
    m = _FENCE_RE.match(t)
    if m:
        t = m.group(1).strip()
    obj = _first_object(t)
    if obj is not None:
        fixed = _coerce_answers(obj)
        if fixed is not None:
            return fixed
    found = [{"id": g["id"], "answer": _json_string(g["answer"]), "evidence": _json_string(g["evidence"])}
             for g in (mm.groupdict() for mm in _ANSWER_RE.finditer(t))]
    return {"answers": found} if found else None


def hygiene_check(system_prompt: str, user_template_parts: list[str]) -> None:
    """Mode A 两道检查（守卫 2）: 指令 / 题目文本里不许有表现类关键词, 模板里不许有表现类占位符。
    笔记正文本身不查 —— 那是内容, 不是上下文。"""
    for ph in TEMPLATE_LEAK_PLACEHOLDERS:
        assert ph not in SYSTEM_TEMPLATE and all(ph not in p for p in user_template_parts), (
            f"feature 模板含表现类占位符 {ph!r} —— 违反 D-028 Mode A")
    for kw in PERFORMANCE_KEYWORDS:
        assert kw not in system_prompt, (
            f"feature 提示词（指令/题目）泄漏表现类关键词 {kw!r} —— 违反 D-028 Mode A")


def render_call(bank: dict, question_ids: list[str], spans: dict) -> dict:
    """把【一组】题渲染成一次调用。question_ids 必须同属一个 call_group 且 ≤ 4（守卫 4）。

    返回 {system, user, question_ids, spans_used, skipped: {qid: reason}}。
    skipped 是这次不问的题（拿不到标题 / 正文太短）, 调用方直接记 NULL。
    """
    idx = question_index(bank)
    qs = [idx[q] for q in question_ids]
    groups = {q["group"] for q in qs}
    if len(groups) != 1:
        raise ValueError(f"一次调用只能问一个组, 收到 {sorted(groups)} (docs/28 §5.3 防晕轮)")
    if len(qs) > MAX_GROUP_SIZE:
        raise ValueError(f"一次调用最多 {MAX_GROUP_SIZE} 题, 收到 {len(qs)}")
    (group,) = groups
    declared = set(bank["call_groups"][group])
    stray = [q["id"] for q in qs if q["id"] not in declared]
    if stray:
        raise ValueError(f"{stray} 不在 call_group {group} 里")

    skipped: dict[str, str] = {}
    asked: list[dict] = []
    for q in qs:
        sc = q["scope"]
        if sc == "title" and spans["title"] is None:
            skipped[q["id"]] = INVALID_NO_TITLE
        elif visible_len(spans[sc] or "") < (MIN_BODY_CHARS if sc in ("body", "full") else 2):
            skipped[q["id"]] = INVALID_TEXT_TOO_SHORT
        else:
            asked.append(q)
    if not asked:
        return {"system": "", "user": "", "question_ids": [], "spans_used": [], "skipped": skipped}

    qblock = "\n".join(_render_question(i + 1, q) for i, q in enumerate(asked))
    example = ", ".join(
        '{"id":"%s","answer":"%s","evidence":""}' % (q["id"], "是" if q["type"] == "bool" else "<选项>")
        for q in asked
    )
    system = SYSTEM_TEMPLATE.format(questions_block=qblock, answers_example=example,
                                    evidence_max=EVIDENCE_MAX_CHARS)
    spans_used = []
    for q in asked:
        if q["scope"] not in spans_used:
            spans_used.append(q["scope"])
    user_parts = [f"【{SPAN_LABELS[s]}】\n{spans[s]}" for s in spans_used]
    hygiene_check(system, [f"【{SPAN_LABELS[s]}】\n" for s in spans_used])
    return {
        "system": system,
        "user": "\n\n".join(user_parts) + "\n\n按上面的题目输出 JSON。",
        "question_ids": [q["id"] for q in asked],
        "spans_used": spans_used,
        "skipped": skipped,
    }


def plan_calls(bank: dict, single: bool = False) -> list[list[str]]:
    """本轮要发的调用清单: 默认按 call_groups 一组一次; single=True 每题单问（闸一对比用）。"""
    if single:
        return [[q["id"]] for q in llm_questions(bank)]
    return [list(members) for members in bank["call_groups"].values()]


# ═══════════════════════════════════════════════════════════════════════
# 答案校验
# ═══════════════════════════════════════════════════════════════════════

def _norm(s: str) -> str:
    return _WS.sub("", s or "")


_EXEMPT_RE = re.compile(r"选「(.+?)」以外")


def evidence_required(q: dict, answer: str) -> bool:
    """什么时候必须给证据: bool 答「是」; choice 除非题目说「不需要」或选了豁免值（如 product_role 的 未出现）。"""
    ev = (q.get("evidence") or "").strip()
    if q["type"] == "bool":
        return answer == "是"
    if ev.startswith("不需要"):
        return False
    m = _EXEMPT_RE.search(ev)
    if m and answer == m.group(1):
        return False
    return True


def closed_set(q: dict) -> tuple[str, ...]:
    if q["type"] == "bool":
        return BOOL_VALUES
    return tuple(o["value"] if isinstance(o, dict) else o for o in q.get("options") or [])


def validate_answers(bank: dict, question_ids: list[str], parsed: Any, spans: dict
                     ) -> dict[str, dict]:
    """逐题校验模型输出（守卫 3）。返回 {qid: {answer, evidence, invalid_reason}}。

    · 答案不在闭集 → out_of_vocab
    · 需要证据而证据不是 scope 那段的原样子串（去空白比）→ evidence_not_found; 超 30 字 → evidence_too_long
    · 片段被截断且 scope 为 body/full 且答「否」→ span_truncated（「否」不能来自没看全的片段）;
      题目写了 null_if_truncated 的, 那几个取值同样处理（副题库 reader_ask_form 的「没问读者」: 结尾被截掉了就说不准, D-128）
    · 缺题 → missing
    """
    idx = question_index(bank)
    got: dict[str, dict] = {}
    if isinstance(parsed, dict) and isinstance(parsed.get("answers"), list):
        for a in parsed["answers"]:
            if isinstance(a, dict) and a.get("id") in question_ids:
                got[a["id"]] = a
    out: dict[str, dict] = {}
    for qid in question_ids:
        q = idx[qid]
        a = got.get(qid)
        if a is None:
            out[qid] = {"answer": None, "evidence": None, "invalid_reason": INVALID_MISSING}
            continue
        ans = str(a.get("answer") if a.get("answer") is not None else "").strip()
        ev = str(a.get("evidence") or "").strip()
        if ans not in closed_set(q):
            out[qid] = {"answer": None, "evidence": ev or None, "invalid_reason": INVALID_OUT_OF_VOCAB}
            continue
        if evidence_required(q, ans):
            nev = _norm(ev)
            if not nev or nev not in _norm(spans[q["scope"]] or ""):
                out[qid] = {"answer": None, "evidence": ev or None, "invalid_reason": INVALID_EVIDENCE_NOT_FOUND}
                continue
            if len(nev) > EVIDENCE_MAX_CHARS:
                out[qid] = {"answer": None, "evidence": ev, "invalid_reason": INVALID_EVIDENCE_TOO_LONG}
                continue
        if spans.get("_truncated") and q["scope"] in TRUNCATABLE_SPANS and (
                ans == "否" or ans in (q.get("null_if_truncated") or ())):
            out[qid] = {"answer": None, "evidence": None, "invalid_reason": INVALID_SPAN_TRUNCATED}
            continue
        out[qid] = {"answer": ans, "evidence": ev or None, "invalid_reason": None}
    return out


def correction_note(results: dict[str, dict]) -> str:
    """重问一次时附的修正说明（只列没过的题）。"""
    lines = []
    for qid, r in results.items():
        reason = r.get("invalid_reason")
        if reason in (None, INVALID_SPAN_TRUNCATED):
            continue
        if reason == INVALID_OUT_OF_VOCAB:
            lines.append(f"- {qid}: 答案不在允许的取值里, 只能从题目给的选项/是否里选")
        elif reason == INVALID_EVIDENCE_NOT_FOUND:
            lines.append(f"- {qid}: evidence 不是指定那一段的原样片段。要么从原文一字不改地抄, 要么改答「否」")
        elif reason == INVALID_EVIDENCE_TOO_LONG:
            lines.append(f"- {qid}: evidence 超过 {EVIDENCE_MAX_CHARS} 字, 只抄最关键的一小段")
        elif reason == INVALID_MISSING:
            lines.append(f"- {qid}: 漏答了")
    return "\n".join(lines)


def retryable(results: dict[str, dict]) -> list[str]:
    return [qid for qid, r in results.items()
            if r.get("invalid_reason") not in (None, INVALID_SPAN_TRUNCATED)]


# ═══════════════════════════════════════════════════════════════════════
# 写作台下发（守卫 7）
# ═══════════════════════════════════════════════════════════════════════

def instructions_for_desk(bank: dict, validation_rows: list[dict]) -> list[dict]:
    """把 feature_validation 里 validated 的行翻成写作台能照做的话。

    ⚠️ aw_instruction=never 的题（efficacy_promise, 合规观察项）**永不出现**在返回里,
    不管闸二把它判成什么（docs/28 §4.2, D-065 续 第 1 条）。方向为「?」的新发现也要 owner 看过
    才下发, 这里只标 needs_owner_review, 不擅自过滤。

    另外两道闸（codex review on #141）:
      · **版本要对得上**: 结论行的 question_version / bank_version 必须等于当前问题库里的值。
        改过题的旧结论不许套到新题干上 —— 旧答案是按旧边界答的, 新指令是按新题干写的。
        缺字段一律不下发（fail-closed）。
      · **choice 题按取值下发**: 一道 choice 题只有一句 aw_instruction, 但闸二是【按取值】
        下结论的。`aw_instruction_values` 声明这句话对哪些取值成立（opening_type 只对
        「具体事件」）; 没声明就不自动下发。bool 题只认「是」。
    """
    idx = question_index(bank)
    bank_version = bank.get("bank_version")
    out: list[dict] = []
    for row in validation_rows:
        if row.get("status") != "validated":
            continue
        q = idx.get(row.get("question_id"))
        if q is None:
            continue
        if row.get("question_version") is None or int(row["question_version"]) != int(q["version"]):
            continue
        if row.get("bank_version") != bank_version:
            continue
        instr = q.get("aw_instruction")
        if not instr or str(instr).strip().lower() == "never":
            continue
        answer = row.get("answer")
        if q["type"] == "bool":
            if answer != "是":
                continue
        elif answer not in (q.get("aw_instruction_values") or []):
            continue
        out.append({
            "question_id": q["id"],
            "answer": row.get("answer"),
            "instruction": instr,
            "summary": row.get("summary"),
            "needs_owner_review": row.get("hypothesis") == "?",
        })
    return out
