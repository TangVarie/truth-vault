#!/usr/bin/env python3
"""副题库 fq-v0.2-cand-reader 的守卫 (D-128): 结构 / 跨库 / run_tag / 代码特征 / 预注册钩子。

断行为不断源码 (D-051): 每条都在题库的【副本】上改坏一处, 看 validate_bank / validate_secondary 有没有报出来。
不连库、不联网、不调模型。主题库 fq-v0.1 的计数 (20/8/3、6 组、31/22 行) 照旧由 ci.yml 守卫 1-5 和
check_feature_orchestration 守着, 这里只加一道「主题库没动」的绊线。

反证 (改坏之后必须变红):
  ① conditional_on 写了主题库没有的题 / 本库自己的题 / 闸一没过的题      → §6 红
  ② contrast_base_excludes 不在选项里 / 用在 bool 题 / 剔完不够 2 个取值  → §6 红
  ③ 和主题库同 id 的题 version 没升 (invites_sharing 写回 1)              → §6 红
  ④ done_marker 没写 / 写成主题库的 has_specific_time                      → §6 红
  ⑤ code_features 里写了没实现的 id                                        → §6 红
  ⑥ 确认族里放代码特征 / 取值不成立 / 不是正好 2 行                        → §6 红
  ⑦ 键写错 (题内 / 顶层 / gate2 块)                                         → §6 红
  ⑧ 副题库用 run_tag=primary 或不带 fqr- 前缀                              → §5 红
  ⑨ 默认 code_features 多算了 last_para_has_qmark (冻结题库多一行)          → §4 红
  ⑩ 截断正文的「没问读者」照常落库                                          → §3 红
  ⑪ 副题库 yaml 改了一个字却没改 D-128 (sha 前 12 位对不上)                 → §8 红

跑法: cd scripts && python check_secondary_bank.py
"""
from __future__ import annotations

import copy
import pathlib
import re
import tempfile

import feature_bank as fb

ROOT = pathlib.Path(__file__).resolve().parent.parent
PRIMARY = fb.load_bank()
SEC = fb.load_bank(fb.BANKS["reader"])
SEC_RAW = pathlib.Path(fb.BANKS["reader"]).read_bytes()


def _q(bank: dict, qid: str) -> dict:
    return next(q for q in bank["questions"] if q["id"] == qid)


def _errs(bank: dict) -> list[str]:
    """一份副本的全部错误: 自己的结构 + 对主题库的跨库校验。"""
    return fb.validate_bank(bank) + fb.validate_secondary(bank, PRIMARY)


def _must_fail(bank: dict, needle: str, what: str) -> None:
    errs = _errs(bank)
    assert any(needle in e for e in errs), f"{what} 没被抓住 (要含 {needle!r}): {errs}"


def _ans(**kv):
    return {"answers": [{"id": k, "answer": v[0], "evidence": v[1]} for k, v in kv.items()]}


# ── §1 正例: 两道校验都过、形状对、和主题库不是一个 sha ─────────────────────────────
def check_positive() -> None:
    assert tuple(fb.BANKS) == ("primary", "reader") and fb.BANKS["primary"] == fb.BANK_PATH, fb.BANKS
    assert pathlib.Path(fb.BANKS["reader"]).is_file(), fb.BANKS["reader"]
    assert fb.validate_bank(SEC) == [], fb.validate_bank(SEC)
    assert fb.validate_secondary(SEC, PRIMARY) == [], fb.validate_secondary(SEC, PRIMARY)
    bank, primary = fb.load_bank_pair(fb.BANKS["reader"])
    assert bank["_sha256"] == SEC["_sha256"] and primary["_sha256"] == PRIMARY["_sha256"]
    assert SEC["role"] == fb.ROLE_SECONDARY and SEC["bank_version"] == "fq-v0.2-cand-reader"
    assert [q["id"] for q in fb.llm_questions(SEC)] == ["reader_ask_form", "invites_sharing"]
    assert [c["id"] for c in SEC["code_features"]] == ["last_para_has_qmark"] and SEC["placebo"] == []
    assert set(SEC["call_groups"]) == {"G7_reader_ask", "G8_sharing"}
    assert fb.plan_calls(SEC) == [["reader_ask_form"], ["invites_sharing"]]
    assert not SEC["_sha256"].startswith("ba0f570c") and SEC["_sha256"] != PRIMARY["_sha256"]
    assert SEC["primary_bank"]["sha256"] == PRIMARY["_sha256"] == PRIMARY["frozen_sha256"]
    assert fb.done_marker(SEC) == "reader_ask_form" and fb.done_marker(PRIMARY) == fb.PRIMARY_DONE_MARKER == "has_specific_time"
    assert _q(SEC, "invites_sharing")["version"] == 2 > _q(PRIMARY, "invites_sharing")["version"] == 1
    g2 = SEC["gate2"]
    assert g2["half"] == "holdout" and g2["placebo"] == "from_primary"
    assert g2["condition_snapshot"] == {"bank_sha256": PRIMARY["_sha256"], "extractors": ["llm:claude-sonnet-5-5"],
                                        "run_tag": "primary"}, g2["condition_snapshot"]
    assert g2["confirmation_family"] == [["reader_ask_form", "挑一个+说自己的"], ["invites_sharing", "是"]]
    for qid in ("reader_ask_form", "invites_sharing"):
        assert _q(SEC, qid)["conditional_on"] == ["ending_asks_reader", "asks_for_help"], qid
    assert _q(SEC, "reader_ask_form")["contrast_base_excludes"] == ["没问读者"]
    assert _q(SEC, "reader_ask_form")["null_if_truncated"] == ["没问读者"]
    # 题干原文里不许再有草稿那句「不进仓库」(D-128: 用定稿措辞, 去掉草稿注释)
    assert "不进仓库" not in SEC_RAW.decode("utf-8")
    print(f"  §1 副题库 {SEC['bank_version']} sha {SEC['_sha256'][:12]}: 两道校验都过; 2 模型题 / 1 代码特征 / 0 占位题; "
          "G7+G8; 钉在 ba0f570c ✓")


# ── §2 Mode A 防泄漏: 副题库两组照样过 hygiene, 分层变量不进提示词 ────────────────────
def check_hygiene() -> None:
    spans = fb.build_spans("【标题】早饭吃什么好？\n【正文】这周每天七点起来做早饭，燕麦配鸡蛋。\n\n你们早饭一般吃什么？",
                           mode="markers")
    for single in (False, True):
        for qids in fb.plan_calls(SEC, single=single):
            call = fb.render_call(SEC, qids, spans)       # 内部 hygiene_check
            assert call["question_ids"] == qids, (qids, call["skipped"])
            for kw in fb.PERFORMANCE_KEYWORDS:
                assert kw not in call["system"], (qids, kw)
            # 闸二的分层题 / 新键只在 yaml 里, 模型看不到 (看到了就是拿主题库的答案带偏副题库, 防晕轮)
            for leak in ("ending_asks_reader", "asks_for_help", "conditional_on", "contrast_base_excludes", "gate2"):
                assert leak not in call["system"], (qids, leak)
            for s, label in fb.SPAN_LABELS.items():
                assert (f"【{label}】" in call["user"]) == (s in call["spans_used"]), (qids, s)
    print("  §2 副题库两组 (分组 / 单问) 过 hygiene; 分层题与新键不进提示词 ✓")


# ── §3 证据与截断: 没问读者免证据、挑一个要证据、截断正文的没问读者 → span_truncated ─────────
def check_evidence_and_truncation() -> None:
    sp = fb.build_spans("【标题】年终奖先还房贷还是先换车？\n【正文】今年拿到年终奖，纠结了一周。\n\n大家要是遇到这种情况会怎么选？", mode="markers")
    r = fb.validate_answers(SEC, ["reader_ask_form"], _ans(reader_ask_form=("没问读者", "")), sp)
    assert r["reader_ask_form"] == {"answer": "没问读者", "evidence": None, "invalid_reason": None}, r
    r = fb.validate_answers(SEC, ["reader_ask_form"], _ans(reader_ask_form=("挑一个", "")), sp)
    assert r["reader_ask_form"]["invalid_reason"] == fb.INVALID_EVIDENCE_NOT_FOUND, r
    r = fb.validate_answers(SEC, ["reader_ask_form"], _ans(reader_ask_form=("挑一个", "先还房贷还是先换车")), sp)
    assert r["reader_ask_form"]["answer"] == "挑一个" and r["reader_ask_form"]["invalid_reason"] is None, r
    r = fb.validate_answers(SEC, ["invites_sharing"], _ans(invites_sharing=("是", "遇到这种情况会怎么选？")), sp)
    assert r["invites_sharing"]["answer"] == "是", r
    r = fb.validate_answers(SEC, ["invites_sharing"], _ans(invites_sharing=("是", "纠结了一周")), sp)
    assert r["invites_sharing"]["invalid_reason"] == fb.INVALID_EVIDENCE_NOT_FOUND, "invites_sharing 只看结尾那段"
    # 截断: full 被截到 1,500 字, 结尾看不到 → 「没问读者」说不准 → NULL + span_truncated; 证据在前缀里的取值照常
    sp_t = fb.build_spans("【标题】这三支口红哪支更日常？\n【正文】" + "今天试色。" * 400 + "\n\n你们呢？", mode="markers")
    assert sp_t["_truncated"]
    r = fb.validate_answers(SEC, ["reader_ask_form"], _ans(reader_ask_form=("没问读者", "")), sp_t)
    assert r["reader_ask_form"] == {"answer": None, "evidence": None, "invalid_reason": fb.INVALID_SPAN_TRUNCATED}, r
    r = fb.validate_answers(SEC, ["reader_ask_form"], _ans(reader_ask_form=("挑一个", "哪支更日常")), sp_t)
    assert r["reader_ask_form"]["answer"] == "挑一个", r
    # invites_sharing 看 last_para (从没截断的正文切), 截断不影响它的「否」
    r = fb.validate_answers(SEC, ["invites_sharing"], _ans(invites_sharing=("否", "")), sp_t)
    assert r["invites_sharing"]["answer"] == "否", r
    # 反证: 拿掉 null_if_truncated → 截断正文的「没问读者」照常落库 (这正是 D-128 要挡的)
    b = copy.deepcopy(SEC); _q(b, "reader_ask_form").pop("null_if_truncated")
    r = fb.validate_answers(b, ["reader_ask_form"], _ans(reader_ask_form=("没问读者", "")), sp_t)
    assert r["reader_ask_form"]["answer"] == "没问读者", "反证前提: 没有 null_if_truncated 时截断不拦 choice 题"
    # 主题库不受影响: 截断时 choice 题照常 (product_role 选 未出现 免证据)
    r = fb.validate_answers(PRIMARY, ["product_role"], _ans(product_role=("未出现", "")), sp_t)
    assert r["product_role"]["answer"] == "未出现", r
    print("  §3 没问读者免证据、挑一个要证据、invites_sharing 只认结尾; 截断正文的没问读者 → span_truncated; 主题库照旧 ✓")


# ── §4 代码特征: 默认仍是那 8 个; last_para_has_qmark 只在点名时算 ─────────────────────
def check_code_features() -> None:
    sp = fb.build_spans("【标题】早饭\n【正文】这周每天七点起来做早饭。\n\n你们早饭一般吃什么？\n#早餐# #打卡#", mode="markers")
    dflt = fb.code_features(sp, [])
    assert tuple(dflt) == fb.CODE_FEATURE_IDS_V1 and len(dflt) == 8, list(dflt)
    assert "last_para_has_qmark" not in dflt, "默认多算一行 = 改了冻结题库的产出"
    assert fb.code_features(sp, [], only=None) == dflt
    assert set(fb.CODE_FEATURE_IMPL) == set(fb.CODE_FEATURE_IDS_V1) | {"last_para_has_qmark"}
    assert [c["id"] for c in PRIMARY["code_features"]] == list(fb.CODE_FEATURE_IDS_V1)
    # check_external_direction 传的 spans 没有 last_para: 默认路径不许碰它
    bare = {"title": "早饭", "_body_untruncated": "你们吃什么？"}
    assert set(fb.code_features(bare, [])) == set(fb.CODE_FEATURE_IDS_V1)

    def qm(body: str):
        s = fb.build_spans("【标题】t\n【正文】" + body, mode="markers")
        return fb.code_features(s, [], only=["last_para_has_qmark"])["last_para_has_qmark"]
    assert qm("今天就到这。\n\n你们平时几点睡？") == ("是", None), "全角 ？"
    assert qm("今天就到这。\n\nwhat do you think?") == ("是", None), "半角 ?"
    assert qm("开头问一句：你们几点睡？\n\n今天就分享到这里啦大家晚安") == ("否", None), "问号只在前面的段落"
    assert qm("今天就分享到这里啦大家晚安\n#失眠怎么办？# #打卡#") == ("否", None), "末尾话题标签里的 ？ 不算"
    assert qm("") == (None, fb.INVALID_TEXT_TOO_SHORT), "空正文"
    assert qm("#早餐# #打卡#") == (None, fb.INVALID_TEXT_TOO_SHORT), "只有话题标签"
    # 没有 last_para 键时从没截断的正文现切, 与 build_spans 切出来的一致
    assert fb.last_para_has_qmark({"_body_untruncated": "前面。\n\n你们呢？"}) == ("是", None)
    assert fb.code_features(sp, [], only=["body_len_bucket", "last_para_has_qmark"]) == {
        "body_len_bucket": dflt["body_len_bucket"], "last_para_has_qmark": ("是", None)}
    try:
        fb.code_features(sp, [], only=["no_such_feature"])
    except ValueError as exc:
        assert "没有实现" in str(exc)
    else:
        raise AssertionError("点名没实现的代码特征必须 ValueError")
    print("  §4 默认 code_features 仍是 8 个 (不碰 last_para); last_para_has_qmark: 全角/半角/话题标签/空正文/现切 ✓")


# ── §5 run_tag: 副题库只许 fqr-*; 主题库不管 ────────────────────────────────────────
def check_run_tags() -> None:
    assert "覆盖" in fb.check_run_tag(SEC, "primary"), "primary 要单独拒并说清后果 (不只靠前缀)"
    for bad in ("primary", "gate1-x", "gate1-sonnet55", "", None, "fqr-", "xfqr-a", "FQR-a"):
        assert fb.check_run_tag(SEC, bad), f"副题库 run_tag={bad!r} 必须拒"
    for ok in ("fqr-g1-sonnet55-a", "fqr-g1-sonnet55-b", "fqr-g1-haiku55", "fqr-g1-owner", "fqr-g2-sonnet55"):
        assert fb.check_run_tag(SEC, ok) is None, ok
    for any_tag in ("primary", "gate1-sonnet55", None):
        assert fb.check_run_tag(PRIMARY, any_tag) is None, "主题库不受 run_tag 前缀约束 (照旧)"
    print("  §5 副题库拒 primary / gate1-* / 无前缀 / 光前缀; fqr-g1-* / fqr-g2-* 放行; 主题库不管 ✓")


# ── §6 反证: 每处改坏都要被报出来 ─────────────────────────────────────────────────
def check_negatives() -> None:
    b = copy.deepcopy(SEC); _q(b, "reader_ask_form")["conditional_on"] = ["ending_asks_readerr", "asks_for_help"]
    _must_fail(b, "不是主题库的模型题", "conditional_on 写了主题库没有的题")
    b = copy.deepcopy(SEC); _q(b, "reader_ask_form")["conditional_on"] = ["invites_sharing"]
    _must_fail(b, "本题库自己的题", "conditional_on 写本库自己的题")
    b = copy.deepcopy(SEC); _q(b, "invites_sharing")["conditional_on"] = ["has_specific_time"]
    _must_fail(b, "闸一不是 pass", "conditional_on 用闸一没过的题")
    b = copy.deepcopy(SEC); _q(b, "invites_sharing")["conditional_on"] = []
    _must_fail(b, "conditional_on 必须是", "conditional_on 空列表")

    b = copy.deepcopy(SEC); _q(b, "reader_ask_form")["contrast_base_excludes"] = ["不存在"]
    _must_fail(b, "不在选项里", "contrast_base_excludes 不在选项里")
    b = copy.deepcopy(SEC); _q(b, "invites_sharing")["contrast_base_excludes"] = ["否"]
    _must_fail(b, "只用于 choice 题", "contrast_base_excludes 用在 bool 题")
    b = copy.deepcopy(SEC); _q(b, "reader_ask_form")["contrast_base_excludes"] = ["没问读者", "求解答", "找同类", "求推荐", "说自己的"]
    _must_fail(b, "至少要 2 个", "contrast_base_excludes 剔完只剩 1 个")

    b = copy.deepcopy(SEC); _q(b, "invites_sharing")["version"] = 1
    _must_fail(b, "version 必须 >", "同 id 版本没升")

    b = copy.deepcopy(SEC); b.pop("done_marker")
    _must_fail(b, "要写 done_marker", "done_marker 没写")
    b = copy.deepcopy(SEC); b["done_marker"] = "has_specific_time"
    _must_fail(b, "主题库的 id", "done_marker 写成主题库的题")
    b = copy.deepcopy(SEC); b["done_marker"] = "last_para_has_qmark"
    _must_fail(b, "不是本题库的模型题", "done_marker 写成代码特征")

    b = copy.deepcopy(SEC); b["code_features"][0]["id"] = "last_para_has_emoji"
    _must_fail(b, "没有实现", "没实现的代码特征")
    b = copy.deepcopy(SEC); b["code_features"][0]["id"] = "body_question_marks"
    _must_fail(b, "是主题库的 id", "副题库重写主题库的代码特征")

    b = copy.deepcopy(SEC); b["gate2"]["confirmation_family"][1] = ["last_para_has_qmark", "是"]
    _must_fail(b, "代码特征 / 占位题不进确认族", "确认族里放代码特征")
    b = copy.deepcopy(SEC); b["gate2"]["confirmation_family"][0] = ["reader_ask_form", "没问读者"]
    _must_fail(b, "取值不成立", "确认族取值是被剔出基数的值")
    b = copy.deepcopy(SEC); b["gate2"]["confirmation_family"][1] = ["invites_sharing", "否"]
    _must_fail(b, "取值不成立", "确认族 bool 题取「否」")
    b = copy.deepcopy(SEC); b["gate2"]["confirmation_family"][0] = ["reader_ask_form", "挑一个+说自己"]
    _must_fail(b, "取值不成立", "确认族 label 打错")
    b = copy.deepcopy(SEC); b["gate2"]["confirmation_family"].append(["reader_ask_form", "说自己的"])
    _must_fail(b, "正好 2 行", "确认族 3 行")
    b = copy.deepcopy(SEC); b["gate2"]["confirmation_family"].pop()
    _must_fail(b, "正好 2 行", "确认族 1 行")

    b = copy.deepcopy(SEC); _q(b, "reader_ask_form")["conditonal_on"] = _q(b, "reader_ask_form").pop("conditional_on")
    _must_fail(b, "不认识的键 ['conditonal_on']", "题内键写错")
    b = copy.deepcopy(SEC); b["done_maker"] = b.pop("done_marker")
    _must_fail(b, "顶层有不认识的键", "顶层键写错")
    b = copy.deepcopy(SEC); b["gate2"]["confirmation_famly"] = b["gate2"].pop("confirmation_family")
    _must_fail(b, "gate2 有不认识的键", "gate2 块键写错")

    b = copy.deepcopy(SEC); b["gate2"]["merged_contrasts"][0]["values"] = ["挑一个", "没问读者"]
    _must_fail(b, "contrast_base_excludes 撞了", "合并取值和剔除取值撞了")
    b = copy.deepcopy(SEC); b["gate2"]["merged_contrasts"][0]["values"] = ["挑一个", "说自已的"]
    _must_fail(b, "都在选项里", "合并取值不在选项里")
    b = copy.deepcopy(SEC); b["gate2"]["merged_contrasts"][0]["label"] = "挑一个"
    _must_fail(b, "不和选项重名", "合并 label 和选项重名")
    b = copy.deepcopy(SEC); b["gate2"]["merged_contrasts"][0]["values"] = ["挑一个", "说自己的", "求推荐", "找同类", "求解答"]
    _must_fail(b, "一个取值都不剩", "合并后对照组空了")

    b = copy.deepcopy(SEC); b["primary_bank"]["sha256"] = "0" * 64
    _must_fail(b, "primary_bank.sha256", "钉错主题库 sha")
    b = copy.deepcopy(SEC); b["gate2"]["condition_snapshot"]["bank_sha256"] = "1" * 64
    _must_fail(b, "condition_snapshot.bank_sha256", "条件快照 sha 不是主题库")
    b = copy.deepcopy(SEC); b["gate2"]["condition_snapshot"]["extractors"] = []
    _must_fail(b, "condition_snapshot 要写", "条件快照没写抽取器")
    p2 = copy.deepcopy(PRIMARY); p2["status"] = "draft"
    errs = fb.validate_secondary(SEC, p2)
    assert any("主题库没冻结" in e for e in errs), errs
    b = copy.deepcopy(SEC); b["call_groups"]["G3_engagement"] = b["call_groups"].pop("G8_sharing")
    _q(b, "invites_sharing")["group"] = "G3_engagement"
    _must_fail(b, "组名和主题库撞了", "组名撞主题库")
    b = copy.deepcopy(SEC); b["bank_version"] = "fq-v0.1"
    _must_fail(b, "bank_version 和主题库一样", "bank_version 撞主题库")
    b = copy.deepcopy(SEC); b.pop("role")
    assert fb.validate_secondary(b, PRIMARY) and fb.check_run_tag(b, "primary") is None, "没写 role 就是主题库"
    b = copy.deepcopy(SEC); b["role"] = "tertiary"
    assert any("role=" in e for e in fb.validate_bank(b))
    b = copy.deepcopy(SEC); b["run_tag_prefix"] = "primary"
    _must_fail(b, "run_tag_prefix", "run_tag_prefix 不以 - 结尾")
    b = copy.deepcopy(SEC); b.pop("gate2")
    _must_fail(b, "要写 gate2 块", "副题库没写 gate2")
    b = copy.deepcopy(SEC); b["gate2"]["half"] = "discovery_and_holdout"
    _must_fail(b, "gate2.half", "gate2.half 不在闭集")
    b = copy.deepcopy(SEC); b["gate2"]["placebo"] = "none"
    _must_fail(b, "gate2.placebo", "gate2.placebo 不在闭集")
    b = copy.deepcopy(SEC); _q(b, "reader_ask_form")["null_if_truncated"] = ["否"]
    _must_fail(b, "不在闭集里", "null_if_truncated 取值不在选项里")
    b = copy.deepcopy(SEC); _q(b, "invites_sharing")["null_if_truncated"] = ["否"]
    _must_fail(b, "只对 scope", "null_if_truncated 用在不截断的段")

    # 读文件那条路: 改坏的 yaml → load_bank_pair 必须 raise; 拿主题库当副题库读也 raise
    bad = SEC_RAW.replace(b"    version: 2\n", b"    version: 1\n", 1)
    assert bad != SEC_RAW
    with tempfile.NamedTemporaryFile("wb", suffix=".yaml", delete=False) as f:
        f.write(bad)
        tmp = f.name
    for path in (tmp, fb.BANK_PATH):
        try:
            fb.load_bank_pair(path)
        except ValueError as exc:
            assert "不合法" in str(exc), exc
        else:
            raise AssertionError(f"load_bank_pair({path}) 必须 raise")
    pathlib.Path(tmp).unlink()
    print("  §6 反证 (conditional_on / excludes / 版本 / done_marker / 代码特征 / 确认族 / 键写错 / 合并 / 钉 sha / 组名 / "
          "gate2 闭集 / null_if_truncated / 读文件) 全部变红 ✓")


# ── §7 绊线: 主题库没动; features-sync 的请求体不带 bank ─────────────────────────────
def check_tripwires() -> None:
    assert fb.BANK_PATH.name == "feature_questions_v0_1.yaml", fb.BANK_PATH
    assert PRIMARY["_sha256"].startswith("ba0f570c"), PRIMARY["_sha256"]
    assert fb.validate_bank(PRIMARY) == [], fb.validate_bank(PRIMARY)
    assert len(fb.llm_questions(PRIMARY)) == 20 and len(PRIMARY["code_features"]) == 8 and len(PRIMARY["placebo"]) == 3
    new_top = {"role", "primary_bank", "run_tag_prefix", "done_marker", "gate2"}
    assert not new_top & set(PRIMARY), "主题库不该写副题库的键"
    assert not any(k in q for q in PRIMARY["questions"]
                   for k in ("conditional_on", "contrast_base_excludes", "null_if_truncated"))
    wf = (ROOT / ".github" / "workflows" / "features-sync.yml").read_text(encoding="utf-8")
    bodies = re.findall(r'^\s*-d "(.*)"', wf, re.M)
    assert bodies and all('\\"project\\"' in b for b in bodies), bodies   # 抓的是请求体那一行 (带 project), 不是 URL
    assert all("bank" not in b for b in bodies), f"features-sync 的请求体带了 bank: {bodies}"
    print("  §7 主题库路径 / ba0f570c / validate_bank 空 / 20-8-3 / 没写新键; features-sync 请求体不带 bank ✓")


# ── §8 预注册钩子: D-128 写了副题库 sha 前 12 位、docs/28 有 §6.2b ───────────────────────
def check_preregistration_hook() -> None:
    dec = (ROOT / "DECISIONS.md").read_text(encoding="utf-8")
    m = re.search(r"^## D-128 .*?(?=^## D-\d+ |\Z)", dec, re.S | re.M)
    assert m, "DECISIONS.md 里没有 D-128 (副题库的预注册)"
    d128 = m.group(0)
    sha12 = SEC["_sha256"][:12]
    assert sha12 in d128, (f"D-128 没写副题库现在的 sha 前 12 位 {sha12}: 改了 yaml 就得同时改 D-128 "
                           "(闸一 / 闸二都钉在这个 sha 上)")
    doc = (ROOT / "docs" / "28-content-feature-layer.md").read_text(encoding="utf-8")
    assert re.search(r"^### 6\.2b ", doc, re.M), "docs/28 缺 §6.2b (副题库的闸二比法)"
    # 反证: yaml 多一个字 → digest 变 → D-128 里找不到 → 红 (status / gate1_status 两行不进 digest, 改它们不触发)
    assert fb.bank_digest(SEC_RAW + b"# x\n")[:12] not in d128
    assert fb.bank_digest(SEC_RAW.replace(b"gate1_status: pending", b"gate1_status: pass")) == SEC["_sha256"]
    print(f"  §8 D-128 写了副题库 sha {sha12}; docs/28 §6.2b 在; 改一个字就对不上 ✓")


def main() -> int:
    check_positive()
    check_hygiene()
    check_evidence_and_truncation()
    check_code_features()
    check_run_tags()
    check_negatives()
    check_tripwires()
    check_preregistration_hook()
    print("\ncheck_secondary_bank: 8 节全过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
