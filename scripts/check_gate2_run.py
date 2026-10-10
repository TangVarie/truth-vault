#!/usr/bin/env python3
"""闸二脚本 gate2_run.py 的守卫 (D-093): 统计量对闭式 · 状态表逐条 · 反证与预注册拒跑 · 行形状。

断行为不断源码 (D-051): §1 / §2 直接算; §3 起用合成数据驱动 run_gate2 (纯函数, 不连库), 每条状态各造一个
特征值, 效应是【按计数造出来的】, 不靠随机数, 所以结果是确定的。

反证 (改坏之后必须变红):
  ① RGB 方差漏一项 (比如去掉 QS/(2S²))            → §1 单层不再等于 Woolf, 红
  ② BH 不做单调修正                               → §2 红
  ③ 大项目方向只数 >1 不数 <1 / 允许两个反向        → §3 「方向不稳」那条红
  ④ 账号先验分层不做 (mh_prior = mh)              → §3 confounded 那条红
  ⑤ 占位题显著不拒跑                               → §4 红
  ⑥ 快照内重复不拒跑                               → §5 红
  ⑦ draft 题库不带 --allow-draft 也跑              → §6 红
  ⑧ run_gate2 不调 validate_bank (冻结后改题照跑)   → §6b 红
  ⑨ 题库 gate1_status: fail 的题没打 unreliable / 冻结带着 pending 照跑 → §6c 红

跑法: cd scripts && python check_gate2_run.py
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

import feature_bank as fb
import gate2_run as G

REAL = fb.load_bank()


def _neutral(bank: dict) -> dict:
    """真题库 D-105 起已冻结、带着真裁决 (fail 的题闸二自动 unreliable)。自检的夹具用它的【中性副本】——
    draft、没记 frozen_sha256、每道模型题 gate1_status=pass——状态表那节的 reversed / no_signal 例子才不会
    被真裁决盖成 unreliable; §6 / §6b / §6c 的反证都在副本上造, 真题库另在 §6c 末尾验一次。"""
    import copy
    b = copy.deepcopy(bank)
    b["status"] = "draft"
    b.pop("frozen_sha256", None)
    for q in b["questions"]:
        if "gate1_status" in q:
            q["gate1_status"] = "pass"
    return b


BANK = _neutral(REAL)
SHA = BANK["_sha256"][:12]
EXTRACTORS = ["code:v1", "llm:test"]
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


# ── §1 单层 MH = 普通 OR, RGB 方差 = Woolf ──────────────────────────────────────
def check_single_stratum_is_woolf() -> None:
    a, b, c, d = 30.0, 70.0, 20.0, 80.0
    mh = G.mh_odds_ratio([(a, b, c, d)])
    or_plain = (a * d) / (b * c)
    se_woolf = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    assert abs(mh["or"] - or_plain) < 1e-12, (mh["or"], or_plain)
    assert abs(mh["se_log"] - se_woolf) < 1e-12, "§1 单层时 RGB 方差必须恰等于 Woolf 的 1/a+1/b+1/c+1/d (statsmodels 同款)"
    assert abs(mh["ci_low"] - math.exp(math.log(or_plain) - 1.959964 * se_woolf)) < 1e-9
    # 两层: 手算 R / S
    t1, t2 = (10.0, 20.0, 5.0, 25.0), (8.0, 12.0, 4.0, 16.0)
    R = 10 * 25 / 60 + 8 * 16 / 40
    S = 20 * 5 / 60 + 12 * 4 / 40
    mh2 = G.mh_odds_ratio([t1, t2])
    assert abs(mh2["or"] - R / S) < 1e-12 and mh2["strata"] == 2
    assert G.mh_odds_ratio([(0, 5, 0, 5)]) is None, "§1 某方向从没出现 → None, 不是除零"
    assert G.mh_odds_ratio([(1, 0, 0, 0)]) is None, "§1 n ≤ 1 的层跳过"
    p = G.wald_p(mh["or"], mh["se_log"])
    z = math.log(or_plain) / se_woolf                      # 1.62 → 双侧 p ≈ 0.104, 和手算一致
    assert abs(p - math.erfc(z / math.sqrt(2))) < 1e-12 and 0.10 < p < 0.11, p
    assert G.wald_p(1.0, 0.3) == 1.0
    assert G.wald_p(3.0, 0.2) < 1e-6
    print("  §1 单层 MH = 普通 OR, RGB 方差 = Woolf; 两层手算对上; 退化情形回 None ✓")


# ── §2 BH ────────────────────────────────────────────────────────────────────
def check_bh() -> None:
    q = G.bh_qvalues({"a": 0.01, "b": 0.02, "c": 0.03, "d": 0.04, "e": 0.05})
    assert all(abs(q[k] - 0.05) < 1e-12 for k in q), q
    q = G.bh_qvalues({"a": 0.001, "b": 0.04, "c": 0.5})
    assert abs(q["a"] - 0.003) < 1e-12 and abs(q["b"] - 0.06) < 1e-12 and abs(q["c"] - 0.5) < 1e-12, q
    q = G.bh_qvalues({"a": 0.03, "b": 0.001})          # 单调修正: a 的 q 不能比它后面更小的 q 小
    assert q["b"] <= q["a"] and abs(q["a"] - 0.03) < 1e-12, q
    # 单调修正真正起作用的形状: p = 0.01 / 0.011 / 0.5 → 不修正时 q = 0.03 / 0.0165 / 0.5 (第一个比第二个大),
    # 修正后 q_1 = min(0.03, 0.0165) = 0.0165。第一版 battery 的反证 ② 就是在这里没红的。
    q = G.bh_qvalues({"a": 0.01, "b": 0.011, "c": 0.5})
    assert abs(q["a"] - 0.0165) < 1e-12 and abs(q["b"] - 0.0165) < 1e-12 and abs(q["c"] - 0.5) < 1e-12, \
        f"§2 BH 的单调修正没起作用: {q}"
    print("  §2 BH: 等差 p 全 0.05, 单调修正 (0.01/0.011/0.5 → 0.0165/0.0165/0.5), 不超过 1 ✓")


# ── 合成数据: 效应按计数造 ──────────────────────────────────────────────────────
def _dataset(projects: int = 5, pos: int = 40, neg: int = 160, accounts_per_project: int = 8) -> tuple[list, list, dict]:
    """projects 个大项目, 每个 pos 正例 / neg 负例, 账号轮流分, 发布时间按序。回 (notes, answers, 每题的填法钩子)。"""
    rng = random.Random(7)
    notes: list[dict] = []
    for p in range(projects):
        pid = f"P{p}"
        for i in range(pos + neg):
            y = 1 if i < pos else 0
            notes.append({"note_id": f"{pid}_n{i:03d}", "project_id": pid,
                          "account_id": f"{pid}_acct{i % accounts_per_project}",
                          "publish_time": (T0 + timedelta(hours=rng.randrange(0, 5000))).isoformat(),
                          "y": y, "has_essence": True, "body_len": 300})
    answers: list[dict] = []
    return notes, answers, {"rng": rng}


def _answer(answers: list, note_id: str, qid: str, value: str, extractor: str = "llm:test", version: int = 1,
            sha: str = SHA) -> None:
    answers.append({"subject_type": "note", "subject_id": note_id, "question_id": qid, "question_version": version,
                    "bank_sha256": sha + "0" * (64 - len(sha)), "extractor": extractor, "answer": value, "run_tag": "primary"})


def _fill_bool(answers, notes, qid, *, p_pos: float, p_neg: float, only_projects=None, version=1, extractor="llm:test"):
    """按【比例精确】给每个项目的正例 / 负例填「是」: 前 round(p·n) 篇是, 其余否 —— 确定性。"""
    by_pj = {}
    for n in notes:
        by_pj.setdefault((n["project_id"], n["y"]), []).append(n)
    for (pid, y), rows in by_pj.items():
        if only_projects is not None and pid not in only_projects:
            continue
        k = round((p_pos if y else p_neg) * len(rows))
        for i, n in enumerate(rows):
            _answer(answers, n["note_id"], qid, "是" if i < k else "否", extractor=extractor, version=version)


def _run(notes, answers, **kw):
    kw.setdefault("allow_draft", True)
    sha = kw.pop("sha", SHA)
    bank = kw.pop("bank", BANK)
    return G.run_gate2({"notes": notes, "answers": answers}, bank, sha=sha, extractors=EXTRACTORS, run_tag="gate2-test", **kw)


def _row(res, qid, value="是"):
    return next(r for r in res["rows"] if r["question_id"] == qid and r["answer"] == value)


# ── §3 状态表逐条 ───────────────────────────────────────────────────────────────
def check_status_matrix() -> None:
    notes, answers, _ = _dataset()
    # validated (+): 正例 60% 是, 负例 30% 是, 五个项目同向
    _fill_bool(answers, notes, "title_is_question", p_pos=0.6, p_neg=0.3)
    # reversed: 预注册 + (has_specific_time), 造成负向
    _fill_bool(answers, notes, "has_specific_time", p_pos=0.2, p_neg=0.5)
    # no_signal: 两边一样
    _fill_bool(answers, notes, "has_specific_place", p_pos=0.4, p_neg=0.4)
    # insufficient: 只在 2 个项目出现 (有支持的大项目 < 3)
    _fill_bool(answers, notes, "has_direct_quote", p_pos=0.6, p_neg=0.3, only_projects={"P0", "P1"})
    # 方向不稳: 三个项目正向、两个项目反向, 合并仍显著
    _fill_bool(answers, notes, "has_body_sensation", p_pos=0.7, p_neg=0.2, only_projects={"P0", "P1", "P2"})
    _fill_bool(answers, notes, "has_body_sensation", p_pos=0.2, p_neg=0.6, only_projects={"P3", "P4"})
    # 新发现 (?): efficacy_promise 预注册 ?, 造正向
    _fill_bool(answers, notes, "efficacy_promise", p_pos=0.6, p_neg=0.3)
    # 闸一不过: own_experience 造正向但传 --unreliable
    _fill_bool(answers, notes, "own_experience", p_pos=0.6, p_neg=0.3)
    # 占位题: 随机, 两边一样
    for k in (1, 2, 3):
        _fill_bool(answers, notes, f"placebo_rand_{k}", p_pos=0.5, p_neg=0.5, extractor="code:v1")
    # 代码特征 choice: body_len_bucket 一个取值正向 (hypothesis 没按取值写 → ? + 备注)
    for n in notes:
        v = ">=400" if (n["y"] and int(n["note_id"][-3:]) % 10 < 6) or (not n["y"] and int(n["note_id"][-3:]) % 10 < 3) else "100-199"
        _answer(answers, n["note_id"], "body_len_bucket", v, extractor="code:v1")

    res = _run(notes, answers, unreliable=["own_experience"])
    s = {(r["question_id"], r["answer"]): r for r in res["rows"]}
    assert set(res["big_projects"]) == {"P0", "P1", "P2", "P3", "P4"} and all(v == 40 for v in res["big_projects"].values())

    r = s[("title_is_question", "是")]
    assert r["status"] == "validated" and r["mh_odds_ratio"] > 2 and r["big_projects_same_dir"] == 5 and r["q_value"] < 0.1, r["summary"]
    r = s[("has_specific_time", "是")]
    assert r["status"] == "reversed" and r["mh_odds_ratio"] < 1 and r["hypothesis"] == "+", r["summary"]
    r = s[("has_specific_place", "是")]
    assert r["status"] == "no_signal" and r["ci_low"] <= 1 <= r["ci_high"], r["summary"]
    r = s[("has_direct_quote", "是")]
    assert r["status"] == "insufficient" and r["big_projects_n"] == 2, r["summary"]
    r = s[("has_body_sensation", "是")]
    assert r["status"] == "no_signal" and "方向不稳" in r["summary"] and r["n_or_below_1"] == 2, r["summary"]
    r = s[("efficacy_promise", "是")]
    assert r["status"] == "validated" and "新发现" in r["summary"], r["summary"]
    r = s[("own_experience", "是")]
    assert r["status"] == "unreliable", r["summary"]
    for k in (1, 2, 3):
        assert s[(f"placebo_rand_{k}", "是")]["status"] in ("no_signal", "insufficient"), s[(f"placebo_rand_{k}", "是")]["summary"]
    assert not res["placebo_alarm"]
    r = s[("body_len_bucket", ">=400")]
    assert r["status"] == "validated" and r["hypothesis"] == "?" and "没按取值写" in r["summary"], r["summary"]
    assert ("body_len_bucket", "100-199") in s and s[("body_len_bucket", "100-199")]["status"] == "reversed" or \
        s[("body_len_bucket", "100-199")]["status"] in ("validated", "reversed"), "choice 题每个取值一行"
    # 快照里没有的题不出现
    assert ("asks_for_help", "是") not in s
    # 行形状
    rows = G.validation_rows(res)
    assert {k for r in rows for k in r} == set(G.VALIDATION_COLUMNS)
    assert len({(r["question_id"], r["question_version"], r["answer"], r["gate2_run"]) for r in rows}) == len(rows), "主键唯一"
    assert all(r["status"] in G.STATUSES and r["hypothesis"] in ("+", "-", "?", "0") for r in rows)
    report = G.render_report(res)
    assert "validated" in report and "title_is_question" in report and "占位题" in report
    print("  §3 状态表: validated / reversed / no_signal(区间) / insufficient / no_signal(方向不稳) / 新发现 / unreliable / "
          "占位题不报警 / choice 按取值; 行形状与主键 ✓")


def check_confounded_by_account_prior() -> None:
    """特征只出现在「先验高」的账号上: 项目内 OR 很高, 按账号先验再分层后 OR 回到 1 附近 → confounded。"""
    notes, answers, _ = _dataset(accounts_per_project=4)
    # 每个项目: acct0 / acct1 是热账号 (爆率 33%), acct2 / acct3 冷账号 (爆率 10%); 发布时间按序号递增,
    # 每个账号都有"更早"的历史。y 按序号 mod 3 / mod 10 定, 特征按 mod 5 定 —— 账号内两者无关 (确定性, 不用随机)。
    for n in notes:
        idx = int(n["note_id"][-3:])
        hot = n["account_id"].endswith(("acct0", "acct1"))
        n["y"] = 1 if (idx % 3 == 0 if hot else idx % 10 == 0) else 0
        n["publish_time"] = (T0 + timedelta(days=idx)).isoformat()
    # 特征 = 热账号上 80% 是、冷账号上 20% 是, 与 y 在账号内无关: 项目内 OR 被账号抬高, 分层后回到 1 附近
    for n in notes:
        idx = int(n["note_id"][-3:])
        hot = n["account_id"].endswith(("acct0", "acct1"))
        _answer(answers, n["note_id"], "judged_by_others", "是" if (idx % 5 != 0) == hot else "否")
    _fill_bool(answers, notes, "title_is_question", p_pos=0.6, p_neg=0.3)
    res = _run(notes, answers)
    r = _row(res, "judged_by_others")
    assert r["mh_odds_ratio"] > 2, r["summary"]
    assert r["status"] == "confounded" and r["mh_prior"] is not None and abs(r["mh_prior"] - r["mh_odds_ratio"]) / r["mh_odds_ratio"] > 0.3, r["summary"]
    assert res["prior_strata"][G.PRIOR_AT_OR_ABOVE] > 0 and res["prior_strata"][G.PRIOR_BELOW] > 0, res["prior_strata"]
    r2 = _row(res, "title_is_question")
    assert r2["status"] == "validated", r2["summary"]
    print("  §3b 账号先验分层: 热账号记号 OR>2 → confounded; 真信号仍 validated; 三档都有人 ✓")


# ── §4 占位题显著 → 拒跑 ────────────────────────────────────────────────────────
def check_placebo_alarm_refuses() -> None:
    notes, answers, _ = _dataset()
    _fill_bool(answers, notes, "placebo_rand_1", p_pos=0.6, p_neg=0.3, extractor="code:v1")
    _fill_bool(answers, notes, "title_is_question", p_pos=0.6, p_neg=0.3)
    try:
        _run(notes, answers)
    except G.Gate2Refused as exc:
        assert "占位题" in str(exc) and "placebo_rand_1" in str(exc), exc
    else:
        raise AssertionError("§4 占位题被判显著且稳定, 整跑必须作废")
    res = _run(notes, answers, ignore_placebo_alarm=True)
    assert res["placebo_alarm"] and _row(res, "placebo_rand_1")["status"] == "reversed"
    print("  §4 占位题显著 → Gate2Refused; --ignore-placebo-alarm 只出报告且标 reversed ✓")


# ── §5 快照唯一性 / 版本 ──────────────────────────────────────────────────────
def check_snapshot_uniqueness() -> None:
    notes, answers, _ = _dataset()
    _fill_bool(answers, notes, "title_is_question", p_pos=0.6, p_neg=0.3)
    _answer(answers, notes[0]["note_id"], "title_is_question", "否", extractor="code:v1")     # 同题两个抽取器
    try:
        _run(notes, answers)
    except G.Gate2Refused as exc:
        assert "不唯一" in str(exc), exc
    else:
        raise AssertionError("§5 快照内 (笔记, 题) 重复必须拒跑")
    # 不在快照里的抽取器 / 别的 sha 不算重复, 也不进分析
    notes, answers, _ = _dataset()
    _fill_bool(answers, notes, "title_is_question", p_pos=0.6, p_neg=0.3)
    _answer(answers, notes[0]["note_id"], "title_is_question", "否", extractor="jev:1.13.0")
    _answer(answers, notes[1]["note_id"], "title_is_question", "否", sha="deadbeefdead")
    res = _run(notes, answers)
    assert res["n_answers"] == len(answers) - 2
    try:
        _run(notes, answers, sha="deadbeef")
    except G.Gate2Refused as exc:
        assert "对不上" in str(exc)
    else:
        raise AssertionError("§5 --sha 与题库文件 digest 对不上必须拒跑")
    print("  §5 快照: (笔记, 题) 重复拒跑; 快照外的行不进; sha 与题库文件对不上拒跑 ✓")


# ── §6 预注册: draft 不跑 ──────────────────────────────────────────────────────
def check_frozen_required() -> None:
    notes, answers, _ = _dataset()
    _fill_bool(answers, notes, "title_is_question", p_pos=0.6, p_neg=0.3)
    assert BANK.get("status") == "draft" and "frozen_sha256" not in BANK, "夹具是真题库的中性副本 (draft), 见 _neutral"
    try:
        _run(notes, answers, allow_draft=False)
    except G.Gate2Refused as exc:
        assert "frozen" in str(exc)
    else:
        raise AssertionError("§6 题库没冻结、没 --allow-draft 必须拒跑 (预注册)")
    print("  §6 题库 draft 且没 --allow-draft → 拒跑 ✓")


def check_frozen_but_edited_refused() -> None:
    """冻结后改过题 (codex review on #169, P1): status=frozen、frozen_sha256 还是改之前的, 操作者拿改后文件的新 digest
    当 --sha 传进来 —— §5 的 sha 比对和 §6 的 frozen 检查都过, 只有 validate_bank 看得出 frozen_sha256 ≠ 规范化 digest。"""
    notes, answers, _ = _dataset()
    _fill_bool(answers, notes, "title_is_question", p_pos=0.6, p_neg=0.3)
    # 冻结的题库每题都得带闸一裁决 (§6c, D-103); 这里只测 digest 那条, 所以统一填 pass
    judged = [dict(q, gate1_status="pass") for q in BANK["questions"]]
    frozen_ok = dict(BANK, status="frozen", frozen_sha256=BANK["_sha256"], questions=judged)
    res = _run(notes, answers, bank=frozen_ok, allow_draft=False)
    assert _row(res, "title_is_question")["status"] == "validated", "§6b 正经冻结 (frozen_sha256 == digest) 的题库必须能跑"
    edited = dict(BANK, status="frozen", frozen_sha256="0" * 64, questions=judged)
    try:
        _run(notes, answers, bank=edited, allow_draft=False)
    except G.Gate2Refused as exc:
        assert "validate_bank" in str(exc) and "frozen_sha256" in str(exc), exc
    else:
        raise AssertionError("§6b frozen 但 frozen_sha256 与规范化 digest 不符 (冻结后改过题) 必须拒跑")
    broken = dict(BANK, status="frozen", frozen_sha256=BANK["_sha256"], call_groups={}, questions=judged)
    try:
        _run(notes, answers, bank=broken, allow_draft=False)
    except G.Gate2Refused as exc:
        assert "validate_bank" in str(exc) and "call_groups" in str(exc), exc
    else:
        raise AssertionError("§6b 结构不合法的题库 (缺 call_groups) 必须拒跑")
    print("  §6b frozen_sha256 == digest 能跑; 冻结后改过题 (digest 不符) 拒跑; 结构不合法拒跑 ✓")


def check_gate1_status_from_bank() -> None:
    """闸一裁决机器可读 (审计 B-17, D-103): 题库里 gate1_status: fail 的题闸二自动 unreliable (不靠 --unreliable 手传);
    冻结时任何一题还是 pending → validate_bank 拦住、run_gate2 拒跑; 取值不在闭集 → 拒跑。"""
    import copy
    notes, answers, _ = _dataset()
    _fill_bool(answers, notes, "title_is_question", p_pos=0.6, p_neg=0.3)
    def _with(status):
        b = copy.deepcopy(BANK)
        next(q for q in b["questions"] if q["id"] == "title_is_question")["gate1_status"] = status
        return b
    assert G.gate1_unreliable(BANK) == set(), "中性副本全 pass, 不该有自动 unreliable 的题"
    res = _run(notes, answers, bank=_with("fail"))
    assert _row(res, "title_is_question")["status"] == "unreliable", "§6c gate1_status: fail 的题必须 unreliable"
    assert "title_is_question" in res["params"]["unreliable"], res["params"]["unreliable"]
    for ok in ("pass", "kappa_undefined"):
        res = _run(notes, answers, bank=_with(ok))
        assert _row(res, "title_is_question")["status"] == "validated", f"§6c gate1_status: {ok} 的题照常进统计"
    frozen_pending = dict(_with("pending"), status="frozen", frozen_sha256=BANK["_sha256"])   # 中性副本全 pass, 要造一道 pending
    try:
        _run(notes, answers, bank=frozen_pending, allow_draft=False)
    except G.Gate2Refused as exc:
        assert "gate1_status" in str(exc) and "pending" in str(exc), exc
    else:
        raise AssertionError("§6c 冻结的题库里还有 gate1_status: pending 的题必须拒跑")
    try:
        _run(notes, answers, bank=_with("maybe"))
    except G.Gate2Refused as exc:
        assert "gate1_status" in str(exc), exc
    else:
        raise AssertionError("§6c gate1_status 不在闭集必须拒跑")
    # 真题库 (D-105 起 frozen、20 题裁决填好): 不带 --allow-draft 能过预注册, fail 的题自动 unreliable、pass 的照常进统计
    assert REAL.get("status") == "frozen", "仓里的题库 D-105 起应当是 frozen"
    real_fail = G.gate1_unreliable(REAL)
    assert real_fail, "真题库应当至少有一道 fail (D-105: 8 道)"
    res = _run(notes, answers, bank=REAL, sha=REAL["_sha256"][:12], allow_draft=False)
    assert set(res["params"]["unreliable"]) >= real_fail, (res["params"]["unreliable"], real_fail)
    assert _row(res, "title_is_question")["status"] == "validated", "真题库里 pass 的题照常进统计"
    print("  §6c gate1_status: fail → unreliable; pass / kappa_undefined 照常; 冻结带 pending 拒跑; 取值闭集; "
          f"真题库 frozen、{len(real_fail)} 道 fail 自动 unreliable ✓")


# ── §7 取数条件 / 大项目动态 ─────────────────────────────────────────────────────
def check_analysis_filter_and_big_projects() -> None:
    notes, answers, _ = _dataset(projects=3, pos=40, neg=100)
    notes[0]["has_essence"] = False
    notes[1]["body_len"] = 20
    notes[2]["body_len"] = None
    kept = G.analysis_notes(notes)
    assert len(kept) == len(notes) - 2 and notes[2] in kept, "§7 没 essence / 正文 < 50 剔掉; body_len 未知的不剔"
    # 第三个项目正例 10 个 → 不是大项目
    small = [n for n in notes if n["project_id"] == "P2" and n["y"]][10:]
    for n in small:
        n["y"] = 0
    _fill_bool(answers, notes, "title_is_question", p_pos=0.6, p_neg=0.3)
    res = _run(notes, answers, min_big=2)
    assert set(res["big_projects"]) == {"P0", "P1"}, res["big_projects"]
    print("  §7 取数条件与大项目 (正例 ≥ 20, 动态算) ✓")


def main() -> int:
    check_single_stratum_is_woolf()
    check_bh()
    check_status_matrix()
    check_confounded_by_account_prior()
    check_placebo_alarm_refuses()
    check_snapshot_uniqueness()
    check_frozen_required()
    check_frozen_but_edited_refused()
    check_gate1_status_from_bank()
    check_analysis_filter_and_big_projects()
    print("\ncheck_gate2_run: 10 节全过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
