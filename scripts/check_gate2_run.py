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
  ⑩ 主题库那条路的输出变了一个字节 (行或报告)                           → §0 红

§8 副题库 (D-128 / docs/28 §6.2b, run_gate2_secondary)。下面每一条都在一份拷贝上真改坏过、确认变红 (10-27, 50 处改法,
外加 check_gate1_review §1b 4 处、discover 自检 1 处; 复审后又补 18 处, 逐个改坏确认变红再改回):
  ⑪ 副题库收了 --write / --rows-out, 或读的时候调了 write_validation              → §8b 红
  ⑫ 半区按 note_id 不按 D-129 old_id / 映射没读到照跑 / fetch_half_alias 0 对不抛 / 映射表读不了不转成拒跑 /
     名单里新旧两行同在、有点名剔掉的篇不拒 / verify #92 不把映射表除外、OPEN-ITEMS S-02 把它列进可删 → §8a / §8c 红
  ⑬ MH 只按项目分层 (不分 ear × afh)                                           → §8a / §8d 红
  ⑭ 3% 线差一 / 截断 NULL 算成缺 / 截断 NULL 进了比较基数                          → §8a / §8e / §8f 红
  ⑮ 取值行 / 合并行的基数没剔「没问读者」/ 阳性对照的基数剔了 / 合并行的取值集合不对 / 分析不限名单 → §8a / §8f 红
  ⑯ BH 把只报告的行算进家族 / 算不出 p 的那行被挤出家族                              → §8a / §8g 红
  ⑰ 占位题报警四条少一条 / p = 0.10 不算 / 报警了照样算两行 / 作废报告名不带 -void / 占位题按 old_id 算 (夹具里换了 id
     的那篇新旧 id 的占位题答案特意挑成不同)                                     → §8a / §8h 红
  ⑱ 分层快照收了 Opus / 不查版本 (invites_sharing v1 混进来) / 不查重复                → §8a / §8i 红
  ⑲ 副题库 draft 也跑 / 不做跨库校验                                             → §8j 红
  ⑳ --counts-only 的结果或输出碰了 y                                             → §8k 红
  ㉑ 敏感性重跑不剔 / 不加 body_len_bucket / paid_promoted=false 也剔                    → §8a / §8l 红
  ㉒ 只读一次不守 / 作废只看标记或只看文件名 / 名单 sha 按文件算 (拆两份就绕过) / --out 覆盖已有报告 / 正式读不带 --out
     也跑 (只打 stdout、不留记号) / --out 写到 --reports-dir 外也跑 / 连库的正式读 --reports-dir 指到 data-analysis 外
     (连 --out 一起挪走) 就不查 data-analysis / 名单没进 git 也读 / --counts-only 的 --out 不限 …-counts.md、能盖掉带标记的报告
                                                                                  → §8a / §8m 红
  ㉓ 取数不钉 sha / 没有版本探针 / 快照外的行取数时不数 (报告里恒 0) / run_gate2_secondary 不加取数带来的数 → §8n 红
  ㉔ 判据参数能改 / 大项目方向改成按层判 / 不做账号先验 / 只过一行也算发现               → §8a / §8c / §8o 红
  ㉕ workflow 的 reader 分支能 write / 能忽略报警 / 收没进仓库的名单 / 跑组合对比 / counts_only=true 不传 --counts-only /
     读完不传记号 artifact、只数也传 / Guard 见了记号照读 / 记号传上去之前结果就进了 job log / step summary / 别的 artifact
     (记号传失败、读完取消) / Guard 不拒仓库里已有的同名报告                        → §8o 红
  ㉖ 大项目分层内方向按合并 2×2 算 / 有支持的大项目不筛「有这个取值」/ 一篇两种都缺归到分层题 / 缺代码特征那行也算掉 → §8d / §8e / §8q 红
  ㉗ 按名单写死时的 y 算 / 按名单写死时的项目分层 (补记 4 要的是现在的)              → §8p 红

跑法: cd scripts && python check_gate2_run.py
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import random
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feature_bank as fb
import gate1_sample as gs
import gate2_run as G
from discover_feature_candidates import in_discovery_half

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


def _status_matrix_dataset() -> tuple[list, list]:
    """§3 状态表那份合成数据 (§0 金样也用它): 每条状态各造一个特征值, 全按计数造, 确定性。"""
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
    return notes, answers


# ── §0 金样: 主题库那条路的输出钉死 (D-128) ─────────────────────────────────────────
# 351a4bf (D-127 之后、副题库之前) 上 §3 那份合成数据跑出来的 14 行摘要和报告全文 sha256, Python 3.11 / 3.13 两次实测一致。
# 以后给 gate2_run 加副题库的分支 (条件分层 / 剔除基数 / 合并取值 / 两行确认族) 只许走新键, 主题库的输出一个字节都不许变。
# 这里红了先别改数: 是主题库的结论口径变了, 要么改回去, 要么另记 DECISIONS 再换金样。
GOLDEN_ROWS_SHA256 = "81cc83e4644248d28d777db883f7b644ffc6329523657217ab83c68d1b1544ed"
GOLDEN_REPORT_SHA256 = "46d9c73b51b3403e893569b294b9f245500ae3e3df6e3e81a7f33244c09b994b"


def check_golden() -> None:
    notes, answers = _status_matrix_dataset()
    res = _run(notes, answers, unreliable=["own_experience"])
    rows = G.validation_rows(res)
    assert len(rows) == 14, len(rows)
    got_rows = G.rows_digest(rows)
    got_report = hashlib.sha256(G.render_report(res).encode()).hexdigest()
    assert got_rows == GOLDEN_ROWS_SHA256, f"§0 主题库闸二的行变了: {got_rows} ≠ 金样 {GOLDEN_ROWS_SHA256[:12]}"
    assert got_report == GOLDEN_REPORT_SHA256, f"§0 主题库闸二的报告变了: {got_report} ≠ 金样 {GOLDEN_REPORT_SHA256[:12]}"
    print(f"  §0 金样: 状态表数据 14 行摘要 {GOLDEN_ROWS_SHA256[:12]}、报告 {GOLDEN_REPORT_SHA256[:12]} 逐字节不变 ✓")


# ── §3 状态表逐条 ───────────────────────────────────────────────────────────────
def check_status_matrix() -> None:
    notes, answers = _status_matrix_dataset()
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


# ── §5b 行摘要: 写进库的得是看过的那份 (codex review on #173, P1) ─────────────────
def check_rows_digest() -> None:
    import contextlib, io, tempfile
    notes, answers, _ = _dataset()
    _fill_bool(answers, notes, "title_is_question", p_pos=0.6, p_neg=0.3)
    res = _run(notes, answers)
    rows = G.validation_rows(res)
    d = G.rows_digest(rows)
    assert len(d) == 64
    assert G.rows_digest(list(reversed(rows))) == d, "§5b 行序不该影响摘要"
    assert G.rows_digest(G.validation_rows(_run(notes, answers))) == d, "§5b 同数据重算摘要必须相同"
    changed = [dict(r) for r in rows]
    changed[0]["status"] = "reversed" if changed[0]["status"] != "reversed" else "validated"
    assert G.rows_digest(changed) != d, "§5b 状态变了摘要必须变"
    assert G.rows_digest([dict(r, gate2_run="gate2-other") for r in rows]) != d, "§5b 换 run_tag 也是另一份"
    # CLI: --write 不带摘要拒; 摘要对不上拒; 对上了才走到写库那一步 (--fixture 模式到那里才说不写库)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump({"notes": notes, "answers": answers}, f, ensure_ascii=False)
        fx = f.name
    base = ["--sha", SHA, "--extractors", ",".join(EXTRACTORS), "--fixture", fx, "--allow-draft", "--run-tag", "gate2-test"]
    def _main(extra):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = G.main(base + extra)
        return rc, out.getvalue(), err.getvalue()
    rc, out, err = _main([])
    assert rc == 0 and f"rows_sha256 {d}" in out, (rc, out[-200:], err[-200:])
    assert "## 行摘要" in out and d[:12] in out, "§5b 报告末尾要带摘要"
    rc, out, err = _main(["--write"])
    assert rc == 2 and "--expect-rows-sha256" in err, (rc, err)
    rc, out, err = _main(["--write", "--expect-rows-sha256", "0" * 12])
    assert rc == 2 and "对不上" in err, (rc, err)
    rc, out, err = _main(["--write", "--expect-rows-sha256", "abc"])
    assert rc == 2 and "对不上" in err, "§5b 短于 12 位的摘要不算核对"
    rc, out, err = _main(["--write", "--expect-rows-sha256", d[:12]])
    assert rc == 2 and "--fixture 模式不写库" in err, (rc, err)
    print("  §5b 行摘要: 行序无关、重算相同、状态 / run_tag 变了就变; --write 不带摘要 / 对不上 → 退出码 2 ✓")


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


# ── §7b --projects 对不上取数 → 拒跑 (codex review on #173, P2) ─────────────────
def check_projects_present() -> None:
    notes, answers, _ = _dataset()
    ds = {"notes": notes, "answers": answers}
    G.assert_projects_present(ds, None)
    G.assert_projects_present(ds, {"P0", "P1"})
    for bad in ({"P9"}, {"P0", "p1"}):
        try:
            G.assert_projects_present(ds, bad)
        except G.Gate2Refused as exc:
            assert "一篇都没有" in str(exc), exc
        else:
            raise AssertionError(f"§7b --projects {sorted(bad)} 在取数里没有必须拒跑")
    try:
        G.assert_projects_present({"notes": [], "answers": []}, None)
    except G.Gate2Refused as exc:
        assert "0 篇" in str(exc), exc
    else:
        raise AssertionError("§7b 取数 0 篇必须拒跑")
    print("  §7b --projects 拼错 / 没标签 → 拒跑; 取数 0 篇 → 拒跑 ✓")


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# §8 副题库 (D-128 / docs/28 §6.2b): run_gate2_secondary 那条路。夹具全是合成的 (note_id 形如 P0_recS00012, 没有正文,
# 没有一行真答案), 效应按计数造、顺序按 sha256 定, 确定性。真题库 (fq-v0.2-cand-reader, 已冻结) 直接用。
# 每一节在拷贝上改坏对应的代码都会红 (见文件头 ⑪–㉗)。
# ══════════════════════════════════════════════════════════════════════════════════════════════════════
SEC_BANK, SEC_PRIMARY = fb.load_bank_pair(fb.BANKS["reader"])
SEC_SHA = SEC_BANK["_sha256"]
PRI_SHA = SEC_PRIMARY["_sha256"]
SEC_TAG = G.SEC_ANSWERS_RUN_TAG
SONNET = G.SEC_LLM_EXTRACTOR
OPUS = "llm:claude-opus-4-6"
ASKED = ("挑一个", "说自己的", "求推荐", "找同类", "求解答")
# 每个项目 4 层 (ending_asks_reader, asks_for_help), 每层 60 篇, 爆数随层变 (问了读者的层爆率高 —— 辛普森那节要的形状)
SEC_STRATA = ((("是", "是"), 60, 24), (("是", "否"), 60, 18), (("否", "是"), 60, 12), (("否", "否"), 60, 6))
RAF_POS = (("挑一个", .2), ("说自己的", .2), ("求推荐", .1), ("找同类", .1), ("求解答", .1), ("没问读者", .3))
RAF_NEG = (("挑一个", .12), ("说自己的", .13), ("求推荐", .12), ("找同类", .12), ("求解答", .11), ("没问读者", .4))


def _hk(tag: str, nid: str) -> str:
    return hashlib.sha256(f"{tag}:{nid}".encode()).hexdigest()


def _half_ids(prefix: str, n: int, half: str = "holdout", tag: str = "S") -> list[str]:
    out, i = [], 0
    while len(out) < n:
        nid = f"{prefix}_rec{tag}{i:05d}"
        if in_discovery_half(nid) == (half == "discovery"):
            out.append(nid)
        i += 1
    return out


def _assign(rows: list[dict], tag: str, spec) -> dict[str, str]:
    """按 sha256(tag:note_id) 排序后按比例切: 前 round(累计比例·n) 篇取第一个值…… 确定性, 各题互不相关。"""
    rows = sorted(rows, key=lambda r: _hk(tag, r["note_id"]))
    out, cum, start = {}, 0.0, 0
    for value, frac in spec:
        cum += frac
        end = round(cum * len(rows))
        for r in rows[start:end]:
            out[r["note_id"]] = value
        start = end
    for r in rows[start:]:
        out[r["note_id"]] = spec[-1][0]
    return out


def _sec_answer(answers, nid, qid, value, *, ver, ext, tag=SEC_TAG, sha=SEC_SHA, invalid=None):
    answers.append({"subject_type": "note", "subject_id": nid, "question_id": qid, "question_version": ver,
                    "bank_sha256": sha, "extractor": ext, "run_tag": tag, "answer": value, "invalid_reason": invalid})


def _sec_fixture(*, raf=lambda ear, afh, y: RAF_POS if y else RAF_NEG,
                 inv=lambda ear, afh, y: .35 if y else .2, qm=lambda ear, afh, y: .5 if y else .45,
                 projects=("P0", "P1", "P2", "P3"), y_order=None, extras: bool = True) -> tuple[dict, list[dict]]:
    """→ (dataset, 名单行)。extras=True 时加上「真实世界的毛刺」(都应当不改结论): 小项目、截断 NULL、掉出去的三种各 1 篇、
    敏感性标记、D-129 换了 id 的一篇、名单外的发现半笔记 (带极端答案)、Opus 的分层行、主题库 invites_sharing v1 的行。"""
    notes, answers, man = [], [], []
    for p in projects + (("P4",) if extras else ()):
        small = p == "P4"
        ids = iter(_half_ids(p, 240))
        for (ear, afh), n, k in SEC_STRATA:
            if small:
                n, k = 10, 1
            group = [next(ids) for _ in range(n)]
            if y_order is not None:
                group.sort(key=y_order)
            rows = []
            for j, nid in enumerate(group):
                rows.append({"note_id": nid, "project_id": p, "account_id": f"{p}_acct{int(_hk('acct', nid), 16) % 8}",
                             "publish_time": (T0 + timedelta(hours=int(_hk('t', nid)[:6], 16) % 5000)).isoformat(),
                             "y": 1 if j < k else 0, "has_essence": True,
                             "body_len": 60 + int(_hk('len', nid)[:4], 16) % 700, "data_quality_flags": {},
                             "has_pinned_comment": False})
            pos, neg = [r for r in rows if r["y"]], [r for r in rows if not r["y"]]
            a_raf = {**_assign(pos, "raf", raf(ear, afh, 1)), **_assign(neg, "raf", raf(ear, afh, 0))}
            a_inv = {**_assign(pos, "inv", (("是", inv(ear, afh, 1)), ("否", 1 - inv(ear, afh, 1)))),
                     **_assign(neg, "inv", (("是", inv(ear, afh, 0)), ("否", 1 - inv(ear, afh, 0))))}
            a_qm = {**_assign(pos, "qm", (("是", qm(ear, afh, 1)), ("否", 1 - qm(ear, afh, 1)))),
                    **_assign(neg, "qm", (("是", qm(ear, afh, 0)), ("否", 1 - qm(ear, afh, 0))))}
            for r in rows:
                nid = r["note_id"]
                _sec_answer(answers, nid, "ending_asks_reader", ear, ver=1, ext=SONNET, tag="primary", sha=PRI_SHA)
                _sec_answer(answers, nid, "asks_for_help", afh, ver=1, ext=SONNET, tag="primary", sha=PRI_SHA)
                _sec_answer(answers, nid, "reader_ask_form", a_raf[nid], ver=1, ext=SONNET)
                _sec_answer(answers, nid, "invites_sharing", a_inv[nid], ver=2, ext=SONNET)
                _sec_answer(answers, nid, "last_para_has_qmark", a_qm[nid], ver=1, ext=fb.CODE_EXTRACTOR)
                man.append({"note_id": nid, "project_id": p, "y": r["y"], "ear": ear, "afh": afh, "tiq": None,
                            "stratum": "A" if "是" in (ear, afh) else "B", "raw_md5": _hk("md5", nid)[:32]})
            notes += rows
    alias = {"ZZ_recNewX": "ZZ_recOldX"}
    vanished: list[str] = []
    if extras:
        p1 = [n for n in notes if n["project_id"] == "P1"]
        # 正文截断记 NULL (reader_ask_form 整题 NULL + span_truncated): 不算缺、不进分子分母
        for n in p1[:5]:
            a = next(a for a in answers if a["subject_id"] == n["note_id"] and a["question_id"] == "reader_ask_form")
            a.update(answer=None, invalid_reason=fb.INVALID_SPAN_TRUNCATED)
        # 掉出去的三种各 1 篇: 飞书删了 / invites_sharing 没行 / ending_asks_reader 没答案
        gone = p1[5]["note_id"]
        notes = [n for n in notes if n["note_id"] != gone]
        vanished.append(gone)
        answers[:] = [a for a in answers if not (a["subject_id"] == p1[6]["note_id"] and a["question_id"] == "invites_sharing")]
        next(a for a in answers if a["subject_id"] == p1[7]["note_id"] and a["question_id"] == "ending_asks_reader")["answer"] = None
        # 敏感性: 投流 / 维护 (起量后干预) / 置顶
        p2 = [n for n in notes if n["project_id"] == "P2"]
        for n in p2[:6]:
            n["data_quality_flags"] = {"paid_promoted": True}
        for n in p2[6:10]:
            n["data_quality_flags"] = {"comment_maintained": True, "comment_maintained_routes": ["起量后干预"]}
        for n in p2[10:13]:
            n["has_pinned_comment"] = True
        p2[13]["data_quality_flags"] = {"paid_promoted": False}                   # false 不剔
        # D-129: 一篇新行自己的 id 落在发现半, 旧 id 在留出半 → 按旧 id 算留出半, 进得来
        moved = _half_ids("P3", 1, half="discovery", tag="Moved")[0]
        # 旧 id 挑一个三道占位题答案和新 id 不全相同的: 占位题错按旧 id 算时支持数会变, §8h 才测得出
        plc = lambda nid: [fb.placebo_answer(nid, k) for k in (1, 2, 3)]                 # noqa: E731
        old = next(o for o in _half_ids("BJSX", 50, half="holdout", tag="Old") if plc(o) != plc(moved))
        alias[moved] = old
        src = next(n for n in notes if n["project_id"] == "P3" and not n["y"])
        notes.append(dict(src, note_id=moved))
        for a in [a for a in answers if a["subject_id"] == src["note_id"]]:
            answers.append(dict(a, subject_id=moved))
        man.append(dict(next(m for m in man if m["note_id"] == src["note_id"]), note_id=moved))
        # 名单外: 发现半 80 篇, 副题库答案和 y 完全一致 (极端效应) —— 不许漏进分析
        for i, nid in enumerate(_half_ids("P0", 80, half="discovery", tag="Disc")):
            y = i % 2
            notes.append({"note_id": nid, "project_id": "P0", "account_id": "P0_acct0",
                          "publish_time": (T0 + timedelta(hours=i)).isoformat(), "y": y, "has_essence": True,
                          "body_len": 300, "data_quality_flags": {}, "has_pinned_comment": False})
            _sec_answer(answers, nid, "ending_asks_reader", "是", ver=1, ext=SONNET, tag="primary", sha=PRI_SHA)
            _sec_answer(answers, nid, "asks_for_help", "否", ver=1, ext=SONNET, tag="primary", sha=PRI_SHA)
            _sec_answer(answers, nid, "reader_ask_form", "挑一个" if y else "求解答", ver=1, ext=SONNET)
            _sec_answer(answers, nid, "invites_sharing", "是" if y else "否", ver=2, ext=SONNET)
            _sec_answer(answers, nid, "last_para_has_qmark", "是", ver=1, ext=fb.CODE_EXTRACTOR)
        # 快照外的行: Opus 的分层答案 (相反)、主题库 invites_sharing v1 (相反) —— 都不许进来
        for m in man[::3]:
            _sec_answer(answers, m["note_id"], "ending_asks_reader", "否" if m["ear"] == "是" else "是", ver=1, ext=OPUS,
                        tag="primary", sha=PRI_SHA)
            _sec_answer(answers, m["note_id"], "invites_sharing", "是" if m["y"] else "否", ver=1, ext=SONNET,
                        tag="primary", sha=PRI_SHA)
    return {"notes": notes, "answers": answers, "vanished": vanished, "half_alias": alias}, man


def _manifests(man: list[dict], split: int = 0) -> list[dict]:
    """名单行 → run_gate2_secondary 的 manifests (split > 0 时拆成两份, 模拟第一波 + 第二波)。"""
    parts = [man[:split], man[split:]] if split else [man]
    out = []
    for i, rows in enumerate(parts):
        text = gs.to_csv(rows)
        out.append({"path": f"wave{i + 1}.csv", "sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "rows": [dict(r) for r in rows]})
    return out


def _sec_run(ds, man, **kw):
    kw.setdefault("sha", SEC_SHA[:12])
    kw.setdefault("run_tag", "gate2-reader-test")
    bank = kw.pop("bank", SEC_BANK)
    manifests = kw.pop("manifests", None) or _manifests(man)
    return G.run_gate2_secondary(ds, bank, SEC_PRIMARY, manifests=manifests, **kw)


def _refused(fn, needle: str, what: str) -> None:
    try:
        fn()
    except G.Gate2Refused as exc:
        assert needle in str(exc), f"{what}: 拒了但原因不对 (要含 {needle!r}): {exc}"
        return
    raise AssertionError(f"{what}: 该拒没拒")


def _cmp(res: dict) -> list:
    """结果里比较用的部分: 两行 + 只报告的行 + 占位题 (行的数, 不含报告措辞)。"""
    keys = ("question_id", "answer", "status", "mh_odds_ratio", "ci_low", "ci_high", "p_value", "q_value", "support",
            "base_n", "mh_prior", "or_project_only", "or_crude")
    rnd = lambda v: round(v, 9) if isinstance(v, float) else v                       # noqa: E731  加法顺序不同的末位误差
    return [tuple(rnd(r.get(k)) for k in keys) for r in res.get("family_rows", []) + res.get("report_rows", [])
            + res.get("placebo_rows", []) + res.get("sensitivity", [])]


def _row2(res: dict, qid: str, value: str) -> dict:
    return next(r for r in res["family_rows"] + res["report_rows"] if r["question_id"] == qid and r["answer"] == value)


# 合成夹具 + 那份报告全文的 sha256 (本地 Python 3.11 / 3.13 两次实测一致)。改了副题库那条路的口径这里就红:
# 先看是不是本意, 是的话另记 DECISIONS 再换金样。
SEC_GOLDEN_REPORT_SHA256 = "3a53851041ceffb8ce05bcedc6b4a138ff5f5385f6bf23cd145fa461d60fcf81"


# ── §8a 金样 + 两行都过 = 一个发现 ───────────────────────────────────────────────────
def check_secondary_golden() -> None:
    ds, man = _sec_fixture()
    res = _sec_run(ds, man)
    rep = G.render_report_secondary(res)
    got = hashlib.sha256(rep.encode()).hexdigest()
    assert got == SEC_GOLDEN_REPORT_SHA256, f"§8a 副题库报告变了: {got} ≠ 金样 {SEC_GOLDEN_REPORT_SHA256[:12]}"
    assert G.render_report_secondary(_sec_run(*_sec_fixture())) == rep, "§8a 同数据重算必须逐字节相同"
    assert [r["status"] for r in res["family_rows"]] == ["validated", "validated"], res["verdict"]
    assert "两行都 validated —— 算一个发现" in rep and "不算两次确认" in rep
    assert rep.count("**validated**") == 2, "§8a 只有确认族两行有状态"
    print(f"  §8a 副题库金样: 合成夹具报告 {got[:12]} 逐字节不变; 两行都 validated → 「算一个发现」 ✓")


# ── §8b 永远不写 feature_validation ───────────────────────────────────────────────
def check_secondary_never_writes(td: Path) -> None:
    import contextlib
    ds, man = _sec_fixture()
    (td / "nw").mkdir()
    fx, csvp = td / "sec.json", td / "wave1.csv"
    fx.write_text(json.dumps(ds, ensure_ascii=False), encoding="utf-8")
    csvp.write_text(gs.to_csv(man), encoding="utf-8")
    base = ["--bank", "reader", "--sha", SEC_SHA[:12], "--manifest", str(csvp), "--fixture", str(fx),
            "--reports-dir", str(td / "nw"), "--run-tag", "gate2-reader-test"]

    def _main(extra):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = G.main(base + extra)
        return rc, out.getvalue(), err.getvalue()
    for extra in (["--write"], ["--write", "--expect-rows-sha256", "0" * 12], ["--rows-out", str(td / "r.json")]):
        rc, _, err = _main(extra)
        assert rc == 2 and "永远不写 feature_validation" in err, (extra, rc, err)
    real = G.write_validation
    G.write_validation = lambda *a, **k: (_ for _ in ()).throw(AssertionError("副题库调用了 write_validation"))
    try:
        rc, out, err = _main(["--out", str(td / "nw" / "feature-gate2-reader-b.md")])
    finally:
        G.write_validation = real
    assert rc == 0 and (td / "nw" / "feature-gate2-reader-b.md").is_file() and "feature_validation 写入" not in out + err, (rc, err)
    print("  §8b --write / --expect-rows-sha256 / --rows-out → 退出码 2; 整条读完没碰 write_validation ✓")


# ── §8c 半区按 D-129 old_id 定; 映射表读不到不跑 ──────────────────────────────────────
def check_secondary_half_alias() -> None:
    ds, man = _sec_fixture()
    moved = next(n for n in ds["half_alias"] if n.startswith("P3_recMoved"))
    assert in_discovery_half(moved) and not in_discovery_half(ds["half_alias"][moved])
    res = _sec_run(ds, man)
    assert res["half_by_old_id"] == 1 and res["n_analysis"] == 998, (res["half_by_old_id"], res["n_analysis"])
    # 去掉映射: 这篇按自己的 id 落在发现半 → 拒
    ds2 = dict(ds, half_alias={k: v for k, v in ds["half_alias"].items() if k != moved})
    _refused(lambda: _sec_run(ds2, man), "不在留出半", "去掉 old_id 映射后发现半的篇混进名单")
    # 反方向: 自己落在留出半、旧 id 在发现半 → 拒
    p0 = next(m["note_id"] for m in man if m["project_id"] == "P0")
    old_disc = _half_ids("BJSX", 1, half="discovery", tag="Old")[0]
    ds3 = dict(ds, half_alias={**ds["half_alias"], p0: old_disc})
    _refused(lambda: _sec_run(ds3, man), "不在留出半", "旧 id 在发现半的新行")
    # 映射表没读到 / 0 对 → fail closed
    _refused(lambda: _sec_run({k: v for k, v in ds.items() if k != "half_alias"}, man), "fail closed", "没有 half_alias")
    _refused(lambda: _sec_run(dict(ds, half_alias={}), man), "fail closed", "half_alias 是空的")
    # 新行和它的旧行都在名单里 → 拒
    twin = dict(next(m for m in man if m["note_id"] == moved), note_id=ds["half_alias"][moved])
    _refused(lambda: _sec_run(ds, man + [twin]), "旧行", "新旧两行都在名单里")
    # D-128 点名剔掉的篇 → 拒
    ex = next(n for n in gs.EXCLUDE if not in_discovery_half(n))
    _refused(lambda: _sec_run(ds, man + [dict(man[0], note_id=ex)]), "点名剔掉", "名单里有点名剔掉的篇")
    # _common.fetch_half_alias: {new: old}; 0 对 / new_id 重复 / 表读不了 → 抛; fetch_dataset_secondary 转成拒跑
    import _common as C
    rows = [{"old_id": "A_recOld1", "new_id": "B_recNew1"}, {"old_id": "A_recOld2", "new_id": None}]
    assert C.fetch_half_alias(_FakeSB({C.D129_ID_MAP_TABLE: rows})) == {"B_recNew1": "A_recOld1"}
    for bad, needle in (([{"old_id": "A_recOld2", "new_id": None}], "0 对"),
                        (rows + [{"old_id": "A_recOld3", "new_id": "B_recNew1"}], "重复")):
        try:
            C.fetch_half_alias(_FakeSB({C.D129_ID_MAP_TABLE: bad}))
        except RuntimeError as exc:
            assert needle in str(exc), exc
        else:
            raise AssertionError(f"§8c fetch_half_alias 该抛没抛 ({needle})")
    _refused(lambda: G.fetch_dataset_secondary(_FakeSB({}, missing={C.D129_ID_MAP_TABLE}), bank=SEC_BANK,
                                               primary=SEC_PRIMARY), "fail closed", "映射表读不了")
    # 映射表永久保留: 名字像备份, 运维清单不能把它当过期备份删 (删了闸二和每季度 G-18 fail closed, 41 篇的半区也算不回来)。
    # verify #92 (过期备份计数, 「> 0 = 该 drop 了」) 要把它除外; OPEN-ITEMS S-02 「…之后才可删」那一句里不能有它
    import re as _re
    root = Path(__file__).resolve().parent.parent
    verify = (Path(__file__).resolve().parent / "verify_supabase_state.sql").read_text(encoding="utf-8")
    v92 = verify[verify.index("SELECT '92'"):verify.index("SELECT '93'")]
    assert f"(n.nspname, c.relname) <> ('truth_vault', '{C.D129_ID_MAP_TABLE}')" in v92, "verify #92 没把 D-129 映射表除外"
    s02 = next(ln for ln in (root / "OPEN-ITEMS.md").read_text(encoding="utf-8").splitlines() if ln.startswith("| S-02 |"))
    droppable = [seg for seg in _re.split(r"[；。]", s02) if "可删" in seg]
    assert droppable and not any(C.D129_ID_MAP_TABLE in seg for seg in droppable), "S-02 把 D-129 映射表列进了可删"
    assert f"`truth_vault.{C.D129_ID_MAP_TABLE}`（old_id → new_id 映射）**永久保留、不删**" in s02
    assert f"COMMENT ON TABLE truth_vault.{C.D129_ID_MAP_TABLE} IS '" in s02 and "永久保留" in s02
    print("  §8c 半区: 换了 id 的按 old_id (两个方向); 去掉映射 / 映射为空 / 读不了 → 拒; 新旧两行同在、点名的篇 → 拒; "
          "映射表 verify #92 除外、S-02 不删 ✓")


# ── §8d 辛普森: 不分层 OR > 1, 分层题内 OR = 1 ────────────────────────────────────────
def check_secondary_simpson() -> None:
    # invites_sharing「是」的比例只随 ending_asks_reader 变 (2/3 vs 1/3), 层内和 y 无关; 问了读者的层爆率又高
    ds, man = _sec_fixture(inv=lambda ear, afh, y: 2 / 3 if ear == "是" else 1 / 3, extras=False)
    res = _sec_run(ds, man)
    c2 = _row2(res, "invites_sharing", "是")
    assert abs(c2["mh_odds_ratio"] - 1.0) < 1e-9, c2["mh_odds_ratio"]
    assert c2["or_project_only"] > 1.3 and c2["or_crude"] > 1.3, (c2["or_project_only"], c2["or_crude"])
    assert c2["status"] == "no_signal", c2["summary"]
    # 补记 1 另报的那列: 每个大项目在 ear × afh 层内的 MH 方向是「=」, 合并 2×2 判的却是 4 个都 >1 —— 这列就是为了露出这种翻转
    assert set(c2["big_within"]) == {"P0", "P1", "P2", "P3"} and set(c2["big_within"].values()) == {"="}, c2["big_within"]
    assert c2["n_or_above_1"] == 4, c2["n_or_above_1"]
    assert res["verdict"].startswith("单行过，不算发现") and "等 2027-04-02" in res["verdict"], res["verdict"]
    assert "invites_sharing 模型偏宽" in res["verdict"], "C2 不显著时要带上闸一那条提醒"
    print(f"  §8d 辛普森: 只按项目 OR {c2['or_project_only']:.2f} / 不分层 {c2['or_crude']:.2f}, 分层题内 1.00 → no_signal; "
          "大项目合并 2×2 4 个 >1、分层内方向全「=」; 只过 C1 → 「单行过，不算发现」 ✓")


# ── §8e 掉出去的三种 + 3% 线; 截断 NULL 不算缺 ─────────────────────────────────────────
def check_secondary_drops() -> None:
    ds, man = _sec_fixture()
    res = _sec_run(ds, man)
    assert res["n_manifest"] == 1001 and res["tolerance"] == 30
    assert {k: sum(v.values()) for k, v in res["drops"].items()} == {"out_of_scope": 1, "no_answer": 1, "no_condition": 1}
    assert res["drops"]["no_condition"] == {"ending_asks_reader: 没有答案": 1}, res["drops"]
    assert res["truncated"] == {"reader_ask_form": 5} and res["n_analysis"] == 1001 - 3, res["truncated"]
    p0 = [m["note_id"] for m in man if m["project_id"] == "P0"]

    def _more(n_scope, n_ans, n_cond):
        d = json.loads(json.dumps(ds, ensure_ascii=False))
        ids = iter(p0)
        notes = {n["note_id"]: n for n in d["notes"]}
        for i in range(n_scope):                                   # 没 essence / 正文 < 50 / 不在 v_l2_labels 轮着来
            nid = next(ids)
            if i % 3 == 0:
                notes[nid]["has_essence"] = False
            elif i % 3 == 1:
                notes[nid]["body_len"] = 20
            else:
                d["notes"] = [n for n in d["notes"] if n["note_id"] != nid]
        for i in range(n_ans):                                     # 没行 / NULL 但不是截断
            nid = next(ids)
            if i % 2:
                d["answers"] = [a for a in d["answers"] if not (a["subject_id"] == nid and a["question_id"] == "reader_ask_form"
                                                                 and a["run_tag"] == SEC_TAG)]
            else:
                a = next(a for a in d["answers"] if a["subject_id"] == nid and a["question_id"] == "invites_sharing"
                         and a["run_tag"] == SEC_TAG)
                a.update(answer=None, invalid_reason=fb.INVALID_EVIDENCE_NOT_FOUND)
        for _ in range(n_cond):
            nid = next(ids)
            d["answers"] = [a for a in d["answers"] if not (a["subject_id"] == nid and a["question_id"] == "asks_for_help")]
        return d
    ok = _sec_run(_more(9, 9, 9), man)                             # 3 + 27 = 30 篇 = 上限, 照读
    assert ok["n_drop"] == 30 and {k: sum(v.values()) for k, v in ok["drops"].items()} == \
        {"out_of_scope": 10, "no_answer": 10, "no_condition": 10}, ok["drops"]
    assert ok["drops"]["out_of_scope"] == {"body_lt_50": 3, "no_essence": 3, "not_in_v_l2_labels": 3, "vanished": 1}
    assert ok["drops"]["no_answer"]["invites_sharing: NULL (evidence_not_found)"] == 5
    _refused(lambda: _sec_run(_more(9, 9, 10), man), "超过 3%", "31 篇 > 1,001 的 3%")
    over = _sec_run(_more(9, 9, 10), man, counts_only=True)
    assert over["would_refuse"] and "读的时候会拒" in G.render_counts_secondary(over), "counts-only 不拒, 但要写明"
    # 一篇两道题没行、分层题也没答案 → 只归「两道题」(先后: 口径 → 两道题 → 分层题); 只缺 last_para_has_qmark 那行的不算掉
    # (补记 5 只数两道模型题), 留在分析集里, 覆盖里记「名单里没行」
    d = json.loads(json.dumps(ds, ensure_ascii=False))
    both, qm_only = p0[0], p0[1]
    d["answers"] = [a for a in d["answers"] if not ((a["subject_id"] == both and a["question_id"] == "invites_sharing"
                                                     and a["run_tag"] == SEC_TAG)
                                                    or (a["subject_id"] == qm_only and a["question_id"] == "last_para_has_qmark"))]
    next(a for a in d["answers"] if a["subject_id"] == both and a["question_id"] == "ending_asks_reader"
         and a["extractor"] == SONNET)["answer"] = None
    r3 = _sec_run(d, man)
    assert {k: sum(v.values()) for k, v in r3["drops"].items()} == {"out_of_scope": 1, "no_answer": 2, "no_condition": 1}, r3["drops"]
    assert r3["drops"]["no_answer"]["invites_sharing: 没有行"] == 2 and r3["n_drop"] == 4 and r3["n_analysis"] == 1001 - 4
    assert r3["coverage"]["last_para_has_qmark"]["manifest_without_row"] == res["coverage"]["last_para_has_qmark"]["manifest_without_row"] + 1
    print("  §8e 掉出去的: 三种分开数 (口径 / 两道题 / 分层题, 各自明细); 30 = 上限照读、31 拒; 截断 NULL 5 篇不算缺; "
          "两种都缺的只归第一种; 只缺代码特征那行的不算掉 ✓")


# ── §8f 比较基数 / 阳性对照 / 合并行手算 / 截断 NULL 不进分子分母 ─────────────────────────
def check_secondary_base_and_merged() -> None:
    ds, man = _sec_fixture()
    res = _sec_run(ds, man)
    lab = {n["note_id"]: n for n in ds["notes"]}
    by = defaultdict(dict)
    for a in ds["answers"]:
        if a["run_tag"] == SEC_TAG and a["bank_sha256"] == SEC_SHA:
            by[a["question_id"]][a["subject_id"]] = a
        elif a["run_tag"] == "primary" and a["extractor"] == SONNET and a["question_id"] in ("ending_asks_reader", "asks_for_help"):
            by["c:" + a["question_id"]][a["subject_id"]] = a["answer"]
    ana = [m["note_id"] for m in man if m["note_id"] in lab and m["note_id"] in by["invites_sharing"]
           and by["invites_sharing"][m["note_id"]]["answer"] is not None
           and by["c:ending_asks_reader"].get(m["note_id"]) and by["c:asks_for_help"].get(m["note_id"])]
    assert len(ana) == res["n_analysis"]
    raf = {n: by["reader_ask_form"][n]["answer"] for n in ana}
    # 手算 C1: 可答 {挑一个, 说自己的} 对其余提问类型, 没问读者和截断 NULL 不进; 层 = 项目 × ear × afh
    tabs = defaultdict(lambda: [0, 0, 0, 0])
    for n in ana:
        v = raf[n]
        if v is None or v == "没问读者":
            continue
        k = (lab[n]["project_id"], by["c:ending_asks_reader"][n], by["c:asks_for_help"][n])
        y = lab[n]["y"]
        tabs[k][(0 if y else 1) if v in ("挑一个", "说自己的") else (2 if y else 3)] += 1
    R = sum(a * d / (a + b + c + d) for a, b, c, d in tabs.values())
    S = sum(b * c / (a + b + c + d) for a, b, c, d in tabs.values())
    c1 = _row2(res, "reader_ask_form", "挑一个+说自己的")
    assert abs(c1["mh_odds_ratio"] - R / S) < 1e-12, (c1["mh_odds_ratio"], R / S)
    asked = sum(1 for n in ana if raf[n] not in (None, "没问读者"))
    answered = sum(1 for n in ana if raf[n] is not None)
    assert c1["base_n"] == asked == 618 and c1["support"] == sum(1 for n in ana if raf[n] in ("挑一个", "说自己的"))
    for v in ASKED:
        r = _row2(res, "reader_ask_form", v)
        assert r["base_n"] == asked and r["support"] == sum(1 for n in ana if raf[n] == v), v
    ctl = _row2(res, "reader_ask_form", "没问读者")
    assert ctl["base_n"] == answered == res["n_analysis"] - 5 and ctl["kind"] == "control", "阳性对照用全部 (截断 NULL 除外)"
    assert ctl["mh_odds_ratio"] < 1, "阳性对照应出 −"
    assert _row2(res, "invites_sharing", "是")["base_n"] == res["n_analysis"], "截断的是 reader_ask_form, invites_sharing 照算"
    print(f"  §8f 合并行 = 手算 MH {R / S:.4f}; 取值行 / 合并行基数 {asked} (剔掉没问读者和截断 NULL); "
          f"阳性对照基数 {answered}、出 −; 截断只影响那一道题 ✓")


# ── §8g BH 只在两行里做 ─────────────────────────────────────────────────────────
def check_secondary_bh_family() -> None:
    # 阳性对照 (没问读者) 造得很强: 它的 p 比两行都小得多 —— 它要是混进家族, 两行的 q 就会变
    strong = lambda ear, afh, y: ((("挑一个", .25), ("说自己的", .25), ("求推荐", .15), ("找同类", .15), ("求解答", .1),  # noqa: E731
                                   ("没问读者", .1)) if y else (("挑一个", .12), ("说自己的", .13), ("求推荐", .1),
                                                                 ("找同类", .1), ("求解答", .05), ("没问读者", .5)))
    ds, man = _sec_fixture(raf=strong)
    res = _sec_run(ds, man)
    fam = {(r["question_id"], r["answer"]): r["p_value"] for r in res["family_rows"]}
    assert len(fam) == 2
    want = G.bh_qvalues(fam)
    for r in res["family_rows"]:
        assert abs(r["q_value"] - want[(r["question_id"], r["answer"])]) < 1e-15, (r["question_id"], r["q_value"])
    every = {**fam, **{(r["question_id"], r["answer"]): r["p_value"] for r in res["report_rows"] + res["placebo_rows"]}}
    wide = G.bh_qvalues(every)
    assert any(abs(wide[k] - want[k]) > 1e-6 for k in fam), "夹具要让「全部行一起校正」和「只两行」的 q 不同, 否则这节测不出"
    tiny = _row2(res, "reader_ask_form", "没问读者")["p_value"]
    assert tiny < min(fam.values()) / 100, "只报告的行里要有一个 p 比两行都小得多的 (阳性对照)"
    assert all(r["q_value"] is None and r["status"] is None for r in res["report_rows"]), "只报告的行不判状态、不进 BH"
    assert all("q_value" not in r and "status" not in r for r in res["placebo_rows"]), "占位题不进家族"
    # 算不出 p 的那行按 p = 1 留在家族里 (家族大小钉死 2)
    ds2, man2 = _sec_fixture(raf=lambda ear, afh, y: (("挑一个", .5), ("没问读者", .5)) if y else (("挑一个", .5), ("没问读者", .5)),
                             extras=False)
    r2 = _sec_run(ds2, man2)
    c1 = _row2(r2, "reader_ask_form", "挑一个+说自己的")
    c2 = _row2(r2, "invites_sharing", "是")
    assert c1["mh_odds_ratio"] is None and abs(c2["q_value"] - min(1.0, 2 * c2["p_value"])) < 1e-15, (c1, c2["q_value"])
    print("  §8g BH 只在确认族两行 (q 与手算的两行 BH 相同, 和「全部一起校正」不同); 只报告的行 / 占位题没有 q 和状态; "
          "算不出 p 的那行按 p=1 占家族的位 ✓")


# ── §8h 占位题: 从主题库现算、不进家族、报警 = 作废 ───────────────────────────────────────
def check_secondary_placebo(td: Path) -> None:
    ds, man = _sec_fixture()
    res = _sec_run(ds, man)
    ana = _analysis_ids(res, ds, man)
    assert [r["question_id"] for r in res["placebo_rows"]] == [p["id"] for p in SEC_PRIMARY["placebo"]] == \
        ["placebo_rand_1", "placebo_rand_2", "placebo_rand_3"] and not res["placebo_alarm"]
    for k, r in enumerate(res["placebo_rows"], start=1):                 # 主题库的定义, 按 note_id 现算 (不是旧 id)
        assert r["support"] == sum(1 for n in ana if fb.placebo_answer(n, k) == "是"), r["question_id"]
        assert r["base_n"] == len(ana)
    moved = [n for n in ana if n in ds["half_alias"]]
    assert moved and any(fb.placebo_answer(n, k) != fb.placebo_answer(ds["half_alias"][n], k) for n in moved for k in (1, 2, 3)), \
        "夹具里换了 id 的篇, 新旧 id 的占位题答案要有不同, 否则「按 note_id 不按 old_id」这条测不出"
    # 报警规则逐条 (补记 2)
    base = {"mh_odds_ratio": 1.8, "ci_low": 1.2, "ci_high": 2.7, "p_value": 0.004, "support": 60, "big_projects_n": 3,
            "n_or_above_1": 2, "n_or_below_1": 1}
    assert G.placebo_alarm(base)
    for k, v in (("support", 29), ("big_projects_n", 2), ("ci_low", 0.9), ("p_value", 0.11), ("n_or_below_1", 2),
                 ("mh_odds_ratio", None)):
        assert not G.placebo_alarm(dict(base, **{k: v})), f"占位题报警: {k}={v} 时不该报"
    assert G.placebo_alarm(dict(base, mh_odds_ratio=0.5, ci_low=0.3, ci_high=0.8, n_or_above_1=1, n_or_below_1=2))
    assert G.placebo_alarm(dict(base, p_value=G.SEC_PLACEBO_P_MAX)), "原始 p ≤ 0.05/3 含等号"
    # 10-27 改 (补记 2): 三道合起来 5%; 单道 p 在 0.0167 和 0.05 之间、区间也不跨 1 的不再报警
    assert abs(G.SEC_PLACEBO_P_MAX - 0.05 / 3) < 1e-12
    assert not G.placebo_alarm(dict(base, p_value=0.02)), "p = 0.02 > 0.05/3 不该报"
    # 报警 → 作废: 两行没算、报告不出它们的数、文件名带 -void、不算读过
    ads, aman = _sec_fixture(y_order=lambda nid: fb.placebo_answer(nid, 1) != "是")
    vres = _sec_run(ads, aman)
    assert vres["void"] and vres["placebo_alarm"] == ["placebo_rand_1"]
    assert "family_rows" not in vres and "report_rows" not in vres and "verdict" not in vres, "报警时两行连算都不算"
    vrep = G.render_report_secondary(vres)
    assert "void=1" in vrep and "作废" in vrep and "placebo_rand_1" in vrep
    for leak in ("挑一个+说自己的", "validated", "no_signal", "insufficient", "确认族 (BH", "只报告 (不判状态"):
        assert leak not in vrep, f"作废报告里不许出现 {leak!r}"
    import contextlib
    fx, csvp = td / "alarm.json", td / "alarm.csv"
    fx.write_text(json.dumps(ads, ensure_ascii=False), encoding="utf-8")
    csvp.write_text(gs.to_csv(aman), encoding="utf-8")
    rdir = td / "alarm-reports"
    rdir.mkdir()
    out = rdir / "feature-gate2-reader-a.md"
    args = ["--bank", "reader", "--sha", SEC_SHA[:12], "--manifest", str(csvp), "--fixture", str(fx),
            "--reports-dir", str(rdir), "--run-tag", "gate2-reader-a", "--out", str(out)]
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        rc = G.main(args)
    assert rc == 3 and not out.exists() and (rdir / "feature-gate2-reader-a-void.md").is_file(), (rc, err.getvalue())
    assert "挑一个+说自己的" not in err.getvalue() and "validated" not in err.getvalue()
    # 作废那份不算读过: 同一份名单 (数据修好之后) 照样能读
    assert not G.prior_secondary_reads([rdir], vres["combined_sha"])
    good = _sec_run(ds, man, reports_dirs=[rdir])
    assert good["combined_sha"] == vres["combined_sha"] and not good["void"] and good["family_rows"]
    print("  §8h 占位题: 主题库 3 道按 note_id 现算、不进家族; 报警四条逐条 (含 p = 0.10); 报警 → 两行不算、报告不露、"
          "-void、退出码 3、不算读过 ✓")


def _analysis_ids(res: dict, ds: dict, man: list[dict]) -> set:
    lab = {n["note_id"] for n in ds["notes"]}
    inv = {a["subject_id"] for a in ds["answers"] if a["run_tag"] == SEC_TAG and a["question_id"] == "invites_sharing"
           and a["answer"] is not None}
    ear = {a["subject_id"] for a in ds["answers"] if a["run_tag"] == "primary" and a["extractor"] == SONNET
           and a["question_id"] == "ending_asks_reader" and a["answer"] is not None}
    out = {m["note_id"] for m in man if m["note_id"] in lab and m["note_id"] in inv and m["note_id"] in ear}
    assert len(out) == res["n_analysis"], (len(out), res["n_analysis"])
    return out


# ── §8i 快照钉死: Opus 不算、重复拒、invites_sharing v1 进不来 ──────────────────────────────
def check_secondary_snapshot_pinning() -> None:
    ds, man = _sec_fixture()
    res = _sec_run(ds, man)
    assert res["ignored_rows"]["condition"] > 0, "夹具里要有 Opus 的分层行"
    clean = dict(ds, answers=[a for a in ds["answers"] if a["extractor"] != OPUS
                              and not (a["question_id"] == "invites_sharing" and a["question_version"] == 1)])
    assert _cmp(_sec_run(clean, man)) == _cmp(res), "Opus 的分层行 / 主题库的 invites_sharing v1 混进来了"
    nid = man[0]["note_id"]
    dup_cond = next(a for a in ds["answers"] if a["subject_id"] == nid and a["question_id"] == "asks_for_help")
    _refused(lambda: _sec_run(dict(ds, answers=ds["answers"] + [dict(dup_cond)]), man), "不唯一", "分层快照重复")
    dup_sec = next(a for a in ds["answers"] if a["subject_id"] == nid and a["question_id"] == "reader_ask_form")
    _refused(lambda: _sec_run(dict(ds, answers=ds["answers"] + [dict(dup_sec, answer="求解答")]), man), "不唯一", "副题库快照重复")
    v1 = dict(next(a for a in ds["answers"] if a["subject_id"] == nid and a["question_id"] == "invites_sharing"
                   and a["run_tag"] == SEC_TAG), question_version=1, subject_id=man[1]["note_id"])
    _refused(lambda: _sec_run(dict(ds, answers=[a for a in ds["answers"] if not (a["subject_id"] == man[1]["note_id"]
                                                                                    and a["question_id"] == "invites_sharing")]
                                    + [v1]), man), "不是题库版本", "副题库 sha 下的 invites_sharing v1")
    oov = dict(dup_sec, answer="随便")
    _refused(lambda: _sec_run(dict(ds, answers=[a for a in ds["answers"] if a is not dup_sec] + [oov]), man), "闭集外",
             "闭集外的答案")
    # 别的 sha / 别的抽取器 / 别的 run_tag 下的副题库行不进快照
    noise = [dict(dup_sec, bank_sha256="0" * 64, answer="挑一个"), dict(dup_sec, extractor="llm:claude-haiku-5-5"),
             dict(dup_sec, run_tag="fqr-g1-sonnet55-a")]
    r2 = _sec_run(dict(ds, answers=ds["answers"] + noise), man)
    assert _cmp(r2) == _cmp(res) and r2["ignored_rows"]["secondary"] == 2, r2["ignored_rows"]
    print("  §8i 快照: Opus 分层行和主题库 invites_sharing v1 不进 (结果逐行相同); 两份快照重复 → 拒; 副题库 sha 下的 v1 → 拒; "
          "闭集外 → 拒; 别的 sha / 抽取器 / run_tag 不进 ✓")


# ── §8j 预注册: 冻结、sha、跨库、run_tag ──────────────────────────────────────────────
def check_secondary_prereg() -> None:
    import copy
    ds, man = _sec_fixture(extras=False)
    assert SEC_BANK["status"] == "frozen" and SEC_BANK["frozen_sha256"] == SEC_SHA
    draft = dict(copy.deepcopy(SEC_BANK), status="draft")
    _refused(lambda: _sec_run(ds, man, bank=draft), "frozen", "draft 的副题库")
    pend = copy.deepcopy(SEC_BANK)
    pend["questions"][1]["gate1_status"] = "pending"
    _refused(lambda: _sec_run(ds, man, bank=pend), "pending", "冻结但还有 pending 的题")
    _refused(lambda: _sec_run(ds, man, sha="ba0f570c"), "对不上", "sha 不是副题库的")
    _refused(lambda: _sec_run(ds, man, bank=SEC_PRIMARY, sha=PRI_SHA[:12]), "只收副题库", "主题库走副题库那条路")
    for tag in ("primary", "gate2-x", "fqr-"):
        _refused(lambda: _sec_run(ds, man, answers_run_tag=tag), "run_tag", f"answers_run_tag={tag}")
    other = dict(copy.deepcopy(SEC_BANK), primary_bank={"bank_version": "fq-v0.1", "sha256": "0" * 64})
    _refused(lambda: _sec_run(ds, man, bank=other), "跨库校验", "primary_bank 钉的不是当前主题库")
    both = copy.deepcopy(SEC_BANK)
    both["gate2"]["condition_snapshot"]["extractors"] = [SONNET, OPUS]
    _refused(lambda: _sec_run(ds, man, bank=both), "Sonnet", "分层快照写了 Opus")
    print("  §8j 预注册: draft / pending / sha 对不上 / 主题库 / run_tag 不是 fqr-… / 跨库钉错 / 分层快照不只 Sonnet → 拒 ✓")


# ── §8k --counts-only: 没有 y、没有 OR、没有 p ───────────────────────────────────────
def check_secondary_counts_only(td: Path) -> None:
    ds, man = _sec_fixture()
    res = _sec_run(ds, man, counts_only=True)
    for k in ("family_rows", "report_rows", "placebo_rows", "big_projects", "n_pos", "y_changed", "prior_strata",
              "sensitivity", "verdict"):
        assert k not in res, f"counts-only 的结果里不许有 {k}"
    text = G.render_counts_secondary(res)
    for bad in ("OR", " p ", "p=", "q=", "爆", "正例", "validated", "置信"):
        assert bad not in text, f"counts-only 输出里出现了 {bad!r}"
    # 和 y、和答案取值都无关: 把 y 全翻 → 整个结果 (不只是输出) 一样; 再把取值全换 (NULL 不动) → 输出逐字节相同
    d1 = json.loads(json.dumps(ds, ensure_ascii=False))
    for n in d1["notes"]:
        n["y"] = 1 - n["y"]
    assert _sec_run(d1, man, counts_only=True) == res, "counts-only 的结果随 y 变了 —— 它碰了 y"
    swap = {"挑一个": "求解答", "求解答": "挑一个", "说自己的": "没问读者", "没问读者": "说自己的", "是": "否", "否": "是"}
    d2 = json.loads(json.dumps(d1, ensure_ascii=False))
    for a in d2["answers"]:
        if a["answer"] is not None:
            a["answer"] = swap.get(a["answer"], a["answer"])
    assert G.render_counts_secondary(_sec_run(d2, man, counts_only=True)) == text, "counts-only 的输出随 y / 答案取值变了"
    # 读过了也能数; 不写读过的标记
    rdir = td / "counts-reports"
    rdir.mkdir()
    (rdir / "feature-gate2-reader-x.md").write_text(G.SEC_MARK.format(sha=SEC_SHA, man=res["combined_sha"], void=0), encoding="utf-8")
    assert _sec_run(ds, man, counts_only=True, reports_dirs=[rdir])["n_manifest"] == 1001
    assert not G.SEC_MARK_RE.search(text), "counts-only 的输出不许带「读过」的标记"
    print("  §8k --counts-only: 结果里没有 y 派生的键; 输出没有 OR / p / 爆; 翻 y、换取值输出逐字节不变; 读过之后照样能数 ✓")


# ── §8l 敏感性重跑 ───────────────────────────────────────────────────────────────
def check_secondary_sensitivity() -> None:
    sf = G.sensitivity_flags
    assert sf(None) == [] and sf({}) == [] and sf({"paid_promoted": False}) == []
    assert sf({"paid_promoted": True}) == ["投流"]
    assert sf({"comment_maintained": True, "comment_maintained_routes": ["铺评工单", "起量后干预"]}) == \
        ["维护:起量后干预", "维护:铺评工单"]
    assert sf({"comment_maintained_routes": ["铺评未跨线"]}) == ["维护:铺评未跨线"]
    assert sf({"comment_maintained": True}) == ["维护"], "只有 comment_maintained 没有 routes 的老行也剔"
    assert sf({}, True) == ["置顶"]
    # body_len_bucket 的切点 = 主题库代码特征 (按同一个 body_len)
    for n in (0, 1, 50, 99, 100, 199, 200, 399, 400, 1013):
        spans = fb.build_spans("字" * n, mode="none")
        assert G.body_len_bucket(fb.raw_counts(spans)["body_len"]) == fb.code_features(spans, [])["body_len_bucket"][0], n
    assert G.body_len_bucket(None) == "unknown"
    ds, man = _sec_fixture()
    res = _sec_run(ds, man)
    lab = {n["note_id"]: n for n in ds["notes"]}
    ana = _analysis_ids(res, ds, man)
    flagged = {n for n in ana if sf(lab[n]["data_quality_flags"], lab[n]["has_pinned_comment"])}
    assert res["sensitivity_dropped"] == len(flagged) == 13
    assert res["sensitivity_flags"] == {"投流": 6, "维护:起量后干预": 4, "置顶": 3}, res["sensitivity_flags"]
    raf = {a["subject_id"]: a["answer"] for a in ds["answers"] if a["run_tag"] == SEC_TAG and a["question_id"] == "reader_ask_form"}
    ear = {a["subject_id"]: a["answer"] for a in ds["answers"] if a["run_tag"] == "primary" and a["extractor"] == SONNET
           and a["question_id"] == "ending_asks_reader"}
    afh = {a["subject_id"]: a["answer"] for a in ds["answers"] if a["run_tag"] == "primary" and a["extractor"] == SONNET
           and a["question_id"] == "asks_for_help"}
    base = [n for n in ana - flagged if raf[n] not in (None, "没问读者")]
    cells = defaultdict(int)
    for n in base:
        cells[(lab[n]["project_id"], ear[n], afh[n], G.body_len_bucket(lab[n]["body_len"]))] += 1
    s1 = next(s for s in res["sensitivity"] if s["question_id"] == "reader_ask_form")
    assert s1["base_n"] == len(base) and s1["strata"] == sum(1 for v in cells.values() if v > 1), (s1["base_n"], s1["strata"])
    assert len({k[:3] for k in cells}) < s1["strata"], "body_len_bucket 那一层要真的加上"
    print(f"  §8l 敏感性: 维护 (三条 route) / 投流 true / 置顶 → 剔 {len(flagged)} 篇, false 和缺键不剔; body_len_bucket 切点同主题库; "
          f"重跑基数 {len(base)}、层 {s1['strata']} 与手算一致 ✓")


# ── §8m 只读一次 (补记 7) ─────────────────────────────────────────────────────────
def check_secondary_single_read(td: Path) -> None:
    ds, man = _sec_fixture()
    rdir = td / "single"
    rdir.mkdir()
    res = _sec_run(ds, man, reports_dirs=[rdir])
    (rdir / "feature-gate2-reader-1.md").write_text(G.render_report_secondary(res), encoding="utf-8")
    _refused(lambda: _sec_run(ds, man, reports_dirs=[rdir]), "已经读过", "同一份名单读第二次")
    _refused(lambda: _sec_run(ds, man, manifests=_manifests(man, split=700), reports_dirs=[rdir]), "已经读过",
             "同一批篇拆成两份名单再读")
    assert _sec_run(ds, man[:-1], reports_dirs=[rdir])["combined_sha"] != res["combined_sha"], "少一篇就是另一份名单"
    # 改名成 -void 但标记还是 void=0 → 照算读过; 标记 void=1 但名字不带 -void → 照算; 两样都对才不算
    (rdir / "feature-gate2-reader-1.md").rename(rdir / "feature-gate2-reader-1-void.md")
    _refused(lambda: _sec_run(ds, man, reports_dirs=[rdir]), "已经读过", "只改名不改标记")
    text = (rdir / "feature-gate2-reader-1-void.md").read_text(encoding="utf-8").replace("void=0", "void=1")
    (rdir / "feature-gate2-reader-1-void.md").write_text(text, encoding="utf-8")
    assert _sec_run(ds, man, reports_dirs=[rdir])["family_rows"], "作废的那份不算读过"
    (rdir / "feature-gate2-reader-1-void.md").rename(rdir / "feature-gate2-reader-1.md")
    _refused(lambda: _sec_run(ds, man, reports_dirs=[rdir]), "已经读过", "标记 void=1 但名字不带 -void")
    # CLI: 正式读必须把报告写进 --reports-dir (那里才找得到); 不带 --out / 写到别处 / 带 -void / -counts.md / 已存在 → 拒
    import contextlib
    fx, csvp = td / "sr.json", td / "sr.csv"
    fx.write_text(json.dumps(ds, ensure_ascii=False), encoding="utf-8")
    csvp.write_text(gs.to_csv(man), encoding="utf-8")
    nodata = ["--bank", "reader", "--sha", SEC_SHA[:12], "--manifest", str(csvp), "--reports-dir", str(rdir)]
    base = nodata + ["--fixture", str(fx)]

    def _main(args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = G.main(args)
        return rc, out.getvalue(), err.getvalue()
    fresh = td / "single-fresh"
    for d in (fresh, td / "elsewhere", td / "elsewhere2"):
        d.mkdir()
    fbase = nodata[:-1] + [str(fresh), "--fixture", str(fx)]
    for extra, needle in (([], "必须带 --out"), (["--out", str(td / "elsewhere" / "r.md")], "必须写进"),
                          (["--out", str(fresh / "x-void.md")], "-void"), (["--out", str(fresh / "x-counts.md")], "-counts.md"),
                          (["--out", str(fresh / "first.txt")], ".md 结尾"), (["--out", str(fresh / "first")], ".md 结尾")):
        rc, out, err = _main(fbase + extra)                   # fresh 里没有读过的报告: 拒只能是因为 --out
        assert rc == 2 and needle in err and "validated" not in out + err, (extra, rc, err)
    assert not list(fresh.iterdir()), "拒跑不留文件"
    rc, _, err = _main(base + ["--out", str(rdir / "feature-gate2-reader-1.md")])
    assert rc == 2 and "已经在了" in err, (rc, err)
    rc, _, err = _main(base + ["--out", str(rdir / "feature-gate2-reader-2.md")])
    assert rc == 2 and "已经读过" in err, (rc, err)
    # 名单没进 git → 正式读拒 (在连库之前就拒; --fixture 的离线跑不查)。连库换成抛错的桩: 这条测试本身永远不连库
    import _common as C
    real_client, real_reports, real_untracked = C.get_supabase_client, G.REPORTS_DIR, G.untracked_manifests
    C.get_supabase_client = lambda: (_ for _ in ()).throw(AssertionError("名单没进仓库却去连库了"))
    G.REPORTS_DIR = fresh                                     # 连库的正式读只认 REPORTS_DIR: 这里把它指到 fresh
    try:
        rc, _, err = _main(nodata[:-1] + [str(fresh), "--out", str(fresh / "r.md")])
    finally:
        C.get_supabase_client, G.REPORTS_DIR = real_client, real_reports
    assert rc == 2 and "没进仓库" in err, (rc, err)
    # --counts-only 不许盖掉读过的报告: 只收 …-counts.md, 同名文件里有标记也拒 (盖掉 = 抹掉记号, 再读就放行了)
    marked = rdir / "feature-gate2-reader-1.md"
    before = marked.read_text(encoding="utf-8")
    rc, _, err = _main(base + ["--counts-only", "--out", str(marked)])
    assert rc == 2 and "-counts.md" in err and marked.read_text(encoding="utf-8") == before, (rc, err)
    sneaky = rdir / "feature-gate2-reader-3-counts.md"
    sneaky.write_text(before, encoding="utf-8")
    rc, _, err = _main(base + ["--counts-only", "--out", str(sneaky)])
    assert rc == 2 and "读过的报告" in err and sneaky.read_text(encoding="utf-8") == before, (rc, err)
    sneaky.unlink()
    rc, _, err = _main(base + ["--counts-only", "--out", str(rdir / "feature-gate2-reader-4-counts.md")])
    assert rc == 0 and _main(base + ["--out", str(rdir / "feature-gate2-reader-5.md")])[0] == 2, "数完行数照样拦着再读"
    # 读一次 (fresh 里) 留下记号; 第二次不管写到哪都拒
    rc, out, err = _main(fbase + ["--out", str(fresh / "feature-gate2-reader-a.md")])
    assert rc == 0 and (fresh / "feature-gate2-reader-a.md").is_file() and not out.strip(), (rc, err)
    for extra in ([], ["--out", str(fresh / "feature-gate2-reader-b.md")], ["--out", str(td / "elsewhere2" / "b.md")]):
        rc, out, err = _main(fbase + extra)
        assert rc == 2 and "validated" not in out + err, (extra, rc, err)
    # 连库的正式读 (不带 --fixture) 只认 data-analysis/ (这里 = 打桩的 REPORTS_DIR): --reports-dir 指到别处、--out 跟过去,
    # 也绕不过那里读过的报告 (补记 7 实现口径)。连库换成假库、名单当作进了 git —— 不守的话这一跑真能读完、再写一份 void=0 的报告;
    # 先在空的 REPORTS_DIR 里真读一次, 证明这条路走得通, 拒是因为 --reports-dir
    G.untracked_manifests = lambda paths: []
    C.get_supabase_client = lambda: _FakeSB(_fake_tables(ds))
    live = nodata[:-1]                                        # 没有 --fixture
    try:
        G.REPORTS_DIR = td / "single-live"
        G.REPORTS_DIR.mkdir()
        rc, out, err = _main(live + [str(G.REPORTS_DIR), "--out", str(G.REPORTS_DIR / "feature-gate2-reader-live.md")])
        assert rc == 0 and (G.REPORTS_DIR / "feature-gate2-reader-live.md").is_file(), (rc, err)
        G.REPORTS_DIR = fresh                                 # fresh 里有读过的报告 (上面那次)
        other = td / "elsewhere3"
        other.mkdir()
        rc, out, err = _main(live + [str(other), "--out", str(other / "again.md")])
        assert rc == 2 and "连库的正式读只在" in err and "validated" not in out + err and not list(other.iterdir()), (rc, err)
        rc, out, err = _main(live + [str(fresh), "--out", str(fresh / "feature-gate2-reader-c.md")])
        assert rc == 2 and "已经读过" in err and not (fresh / "feature-gate2-reader-c.md").exists(), (rc, err)
    finally:
        C.get_supabase_client, G.REPORTS_DIR, G.untracked_manifests = real_client, real_reports, real_untracked
    print("  §8m 只读一次: 同一份名单 (含拆成两份) 第二次 → 拒; 少一篇 = 另一份; 作废要「名字带 -void + 标记 void=1」才不算; "
          "正式读不带 --out / 写到 data-analysis 外 / -void / -counts.md / 已存在 / 名单没进 git / 连库时 --reports-dir 指到别处 → 拒; "
          "--counts-only 盖不掉读过的报告 ✓")


# ── §8n 取数: 假库上跑 fetch_dataset_secondary, 和直接给 dataset 结果相同 ────────────────────
class _FakeQ:
    """假 PostgREST builder: eq / neq 真过滤, select 真投影, order + range / limit 真切片 (fetch_all_pages 要的那几样)。"""

    def __init__(self, rows, log, name):
        self.rows, self.log, self.name = rows, log, name
        self.filters, self.cols, self._order, self._rng, self._limit, self._count = [], None, None, None, None, None

    def select(self, cols, count=None):
        self.cols = [c.strip() for c in cols.split(",")]
        self._count = count
        return self

    def eq(self, c, v):
        self.filters.append((c, v, True))
        self.log.append((self.name, "eq", c, v))
        return self

    def neq(self, c, v):
        self.filters.append((c, v, False))
        self.log.append((self.name, "neq", c, v))
        return self

    def order(self, c):
        self._order = c
        return self

    def range(self, a, b):
        self._rng = (a, b)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        rows = [r for r in self.rows if all((r.get(c) == v) == want for c, v, want in self.filters)]
        n = len(rows) if self._count == "exact" else None
        if self._order:
            rows.sort(key=lambda r: str(r.get(self._order)))
        if self._rng:
            rows = rows[self._rng[0]:self._rng[1] + 1]
        if self._limit is not None:
            rows = rows[:self._limit]
        if self.cols:
            rows = [{c: r.get(c) for c in self.cols} for r in rows]
        return type("R", (), {"data": rows, "count": n})()


class _FakeSB:
    def __init__(self, tables, missing=()):
        self.tables, self.missing, self.log = tables, set(missing), []

    def schema(self, _s):
        return self

    def table(self, name):
        if name in self.missing:
            raise RuntimeError(f'relation "truth_vault.{name}" does not exist')
        return _FakeQ(self.tables.get(name, []), self.log, name)


def _fake_tables(ds: dict) -> dict:
    gone = [{"note_id": n, "project_id": n.split("_rec")[0], "account_id": None, "publish_time": None, "y": 0,
             "has_essence": True, "body_len": 300, "data_quality_flags": {}, "has_pinned_comment": False} for n in ds["vanished"]]
    allnotes = ds["notes"] + gone
    return {
        "v_l2_labels": [{k: n[k] for k in ("note_id", "project_id", "account_id", "publish_time", "y")} for n in allnotes],
        "notes": [{"note_id": n["note_id"], "emotional_lever": "x" if n["has_essence"] else None,
                   "data_quality_flags": n["data_quality_flags"], "pinned_comment": "置顶评论" if n["has_pinned_comment"] else None,
                   "raw_content": "不该取"} for n in allnotes],
        "note_features": [{"note_id": n["note_id"], "body_len": n["body_len"]} for n in allnotes],
        "v_notes_vanished": [{"note_id": n} for n in ds["vanished"]],
        "backup_d129_ids_20261026": [{"old_id": o, "new_id": n, "how": "raw_exact", "keep_gate1": False}
                                     for n, o in ds["half_alias"].items()] + [{"old_id": "W_recWaste", "new_id": None}],
        "note_feature_answers": [dict(a) for a in ds["answers"]],
    }


def check_secondary_fetch() -> None:
    ds, man = _sec_fixture()
    # 副题库 run_tag 下快照外的两行 (Haiku、别的 sha); 夹具本来就有 Opus 的分层行
    a0 = next(a for a in ds["answers"] if a["run_tag"] == SEC_TAG and a["question_id"] == "reader_ask_form")
    ds["answers"] += [dict(a0, extractor="llm:claude-haiku-5-5"), dict(a0, bank_sha256="0" * 64)]
    sb = _FakeSB(_fake_tables(ds))
    got = G.fetch_dataset_secondary(sb, bank=SEC_BANK, primary=SEC_PRIMARY)
    assert got["half_alias"] == ds["half_alias"] and got["vanished"] == ds["vanished"]
    assert all("raw_content" not in n and "pinned_comment" not in n for n in got["notes"]), "正文 / 置顶评论文字不取"
    assert not any(a["extractor"] == OPUS for a in got["answers"]), "Opus 的分层行不该查出来"
    res = _sec_run(ds, man)
    r2 = _sec_run(got, man)
    assert _cmp(r2) == _cmp(res) and r2["drops"] == res["drops"] and r2["sensitivity_flags"] == res["sensitivity_flags"]
    # 快照外的行取数时不取、在库里数: 报告里「快照外 N 行」和直接给全部行时一样, 不是恒 0
    n_opus = sum(1 for a in ds["answers"] if a["extractor"] == OPUS and a["question_id"] in ("ending_asks_reader", "asks_for_help"))
    assert r2["ignored_rows"] == res["ignored_rows"] == {"secondary": 2, "condition": n_opus} and n_opus > 0, \
        (r2["ignored_rows"], res["ignored_rows"], n_opus)
    assert f"本次快照外 {n_opus} 行" in G.render_counts_secondary(_sec_run(got, man, counts_only=True))
    eqs = {(c, v) for name, op, c, v in sb.log if name == "note_feature_answers" and op == "eq"}
    assert ("run_tag", SEC_TAG) in eqs and ("bank_sha256", SEC_SHA) in eqs and ("bank_sha256", PRI_SHA) in eqs, eqs
    assert ("extractor", SONNET) in eqs and ("extractor", fb.CODE_EXTRACTOR) in eqs and ("question_version", 2) in eqs
    # 版本不对的行 (副题库 sha 下的 invites_sharing v1) 由探针捞出来交给 run_gate2_secondary 拒, 不在取数里静默丢
    t = _fake_tables(ds)
    a0 = next(a for a in t["note_feature_answers"] if a["run_tag"] == SEC_TAG and a["question_id"] == "invites_sharing")
    t["note_feature_answers"].append(dict(a0, question_version=1))
    bad = G.fetch_dataset_secondary(_FakeSB(t), bank=SEC_BANK, primary=SEC_PRIMARY)
    _refused(lambda: _sec_run(bad, man), "不是题库版本", "取数时混进的 invites_sharing v1")
    print("  §8n 取数 (假库, 过滤 / 投影 / 翻页都真做): 结果和直接给 dataset 相同; 只查 Sonnet / code:v1、全 sha、钉版本; "
          "快照外的行 (Opus / Haiku / 别的 sha) 只数不取、数对; 不取正文; 版本不对的行被探针捞出来 → 拒 ✓")


# ── §8o CLI / workflow / 进了仓库的第一波名单 ──────────────────────────────────────────
def check_secondary_cli_and_workflow(td: Path) -> None:
    import contextlib
    import yaml
    ds, man = _sec_fixture(extras=False)
    fx, csvp = td / "cli.json", td / "cli.csv"
    fx.write_text(json.dumps(ds, ensure_ascii=False), encoding="utf-8")
    csvp.write_text(gs.to_csv(man), encoding="utf-8")
    base = ["--bank", "reader", "--fixture", str(fx), "--reports-dir", str(td / "cli-reports")]

    def _main(args):
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            try:
                rc = G.main(args)
            except SystemExit as exc:
                rc = exc.code
        return rc, err.getvalue()
    ok = base + ["--sha", SEC_SHA[:12], "--manifest", str(csvp), "--out", str(td / "cli-reports" / "feature-gate2-reader-cli.md")]
    for extra, needle in ((["--projects", "P0"], "--projects"), (["--q-max", "0.2"], "D-128"),
                          (["--min-support", "20"], "D-128"), (["--extractors", "code:v1,llm:claude-opus-4-6"], "钉死"),
                          (["--allow-draft"], "--allow-draft"), (["--ignore-placebo-alarm"], "不许忽略"),
                          (["--answers-run-tag", "primary"], "run_tag")):
        rc, err = _main(ok + extra)
        assert rc == 2 and needle in err, (extra, rc, err)
    rc, err = _main(base + ["--manifest", str(csvp)])
    assert rc == 2 and "--sha 必填" in err, err
    rc, err = _main(base + ["--sha", SEC_SHA[:12]])
    assert rc == 2 and "--manifest 必填" in err, err
    rc, err = _main(ok + ["--extractors", "llm:claude-sonnet-5-5,code:v1", "--counts-only", "--out", str(td / "c-counts.md")])
    assert rc == 0 and (td / "c-counts.md").is_file() and "只数行数" in err, (rc, err)
    rc, err = _main(ok + ["--counts-only", "--out", str(td / "c.md")])
    assert rc == 2 and "-counts.md" in err and not (td / "c.md").exists(), (rc, err)
    rc, err = _main(ok + ["--manifest", str(csvp)])
    assert rc == 2 and "两份名单里都有" in err, "同一份名单给两次 = 重叠"
    # 主题库那条路: --manifest / --counts-only 不收; --sha / --extractors 照旧必填; --bank primary 这个键能用
    rc, _ = _main(["--sha", SHA, "--extractors", ",".join(EXTRACTORS), "--manifest", str(csvp)])
    assert rc == 2
    rc, _ = _main(["--sha", SHA])
    assert rc == 2
    notes, answers, _ = _dataset()
    _fill_bool(answers, notes, "title_is_question", p_pos=0.6, p_neg=0.3)
    pfx = td / "primary.json"
    pfx.write_text(json.dumps({"notes": notes, "answers": answers}, ensure_ascii=False), encoding="utf-8")
    rc, err = _main(["--bank", "primary", "--sha", REAL["_sha256"][:12], "--extractors", ",".join(EXTRACTORS),
                     "--fixture", str(pfx), "--run-tag", "gate2-test"])
    assert rc == 0, err
    # workflow: bank 输入 (primary / reader)、名单、counts_only; reader 不许 write、不跑组合对比
    wf_text = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "gate2-run.yml").read_text(encoding="utf-8")
    wf = yaml.safe_load(wf_text)
    inputs = (wf.get("on") or wf.get(True))["workflow_dispatch"]["inputs"]
    assert inputs["bank"]["default"] == "primary" and {"manifests", "counts_only"} <= set(inputs), sorted(inputs)
    assert inputs["counts_only"]["default"] == "true", "counts_only 默认 true: 手滑点一下不会用掉「只读一次」"
    steps = wf["jobs"]["gate2"]["steps"]
    guard = next(s["run"] for s in steps if s.get("name", "").startswith("Guard"))
    # 真跑一遍 Guard 那段 bash (假 secret, 不连库): reader 带 write / 忽略报警 / 范围 / 没进仓库的名单 → 红; bank 只收两个值
    import os
    import subprocess
    import sys
    gfile = td / "guard.sh"
    gfile.write_text(guard, encoding="utf-8")

    def _guard(**env):
        e = dict(os.environ, PATH=os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", ""),
                 GITHUB_ENV=str(td / "genv"), SUPABASE_URL="x", SUPABASE_SERVICE_ROLE_KEY="y", IN_WRITE="false",
                 IN_IGNORE_PLACEBO="false", IN_PROJECTS="", IN_UNRELIABLE="", IN_EXTRACTORS="code:v1,llm:claude-sonnet-5-5",
                 IN_RUN_TAG="", IN_BANK="reader", IN_SHA=SEC_SHA[:12], IN_COUNTS_ONLY="true",
                 IN_MANIFESTS="data-analysis/gate2-reader-holdout-2026-10-27.csv", IN_REVIEWED="")
        e.update(env)
        p = subprocess.run(["bash", "-e", str(gfile)], cwd=Path(__file__).resolve().parent, env=e, capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr
    for env, needle in (({"IN_WRITE": "true"}, "write 必须是 false"), ({"IN_IGNORE_PLACEBO": "true"}, "不许忽略占位题报警"),
                        ({"IN_PROJECTS": "P0"}, "projects / unreliable"), ({"IN_MANIFESTS": ""}, "要给 manifests"),
                        ({"IN_MANIFESTS": "data-analysis/nope.csv"}, "没进仓库"), ({"IN_MANIFESTS": "/etc/passwd"}, "data-analysis/"),
                        ({"IN_COUNTS_ONLY": "maybe"}, "counts_only"), ({"IN_BANK": "other"}, "bank 只能是"),
                        # 带换行的输入: grep 按行匹配会放过去, 再经 GITHUB_ENV 盖掉 IN_COUNTS_ONLY (复核 on #246)
                        ({"IN_RUN_TAG": "ok\nIN_COUNTS_ONLY=false"}, "不许有换行"), ({"IN_SHA": SEC_SHA[:12] + "\r"}, "不许有换行")):
        rc, out = _guard(**env)
        assert rc != 0 and needle in out, (env, rc, out[-300:])
    in_git = subprocess.run(["git", "ls-files", "--error-unmatch", "../data-analysis/gate2-reader-holdout-2026-10-27.csv"],
                            cwd=Path(__file__).resolve().parent, capture_output=True, text=True).returncode == 0
    # 假 gh: 记下参数, 回 GH_COUNT (Guard 用 --jq .total_count 取数); GH_FAIL 非空就失败 (查不了 artifact)
    ghbin = td / "ghbin"
    ghbin.mkdir()
    (ghbin / "gh").write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$GH_LOG"\n[ -n "$GH_FAIL" ] && exit 1\necho "$GH_COUNT"\n',
                              encoding="utf-8")
    (ghbin / "gh").chmod(0o755)
    ghlog = td / "gh.log"

    def _guard_gh(count="0", fail="", **env):
        for f in (ghlog, td / "genv"):
            f.unlink(missing_ok=True)
        rc, out = _guard(PATH=str(ghbin) + os.pathsep + os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", ""),
                         GH_LOG=str(ghlog), GH_COUNT=count, GH_FAIL=fail, GITHUB_REPOSITORY="o/r", **env)
        return rc, out, (ghlog.read_text(encoding="utf-8") if ghlog.exists() else "")
    if in_git:                                              # 过了「名单进没进仓库」才走得到的: 要 git (CI 的 checkout 是 git 仓库)
        rc, out = _guard(IN_SHA="ba0f570c")
        assert rc != 0 and "不是副题库" in out, out[-300:]
        rc, out, gh = _guard_gh(count="1")                  # counts_only=true: 不查读过没有 (数行数随时能跑)
        assert rc == 0 and "bank=reader" in out and "write=false" in out and not gh, (out[-300:], gh)
        genv = (td / "genv").read_text(encoding="utf-8")
        assert "TAG=gate2-reader-" in genv and "MANIFESTS= data-analysis/gate2-reader-holdout-2026-10-27.csv" in genv, genv
        assert "READ_KEY" not in genv
        # counts_only=false: 按合并名单 sha 查 artifact gate2-reader-read-<前 12 位>; 有 → 拒; 查不了 → 拒; 没有 → 记 READ_KEY
        key = "35549d5ca27b"                                # 第一波单独的合并名单 sha 前 12 位 (下面另核)
        rc, out, gh = _guard_gh(count="1", IN_COUNTS_ONLY="false")
        assert rc != 0 and "已经读过" in out and f"actions/artifacts?name=gate2-reader-read-{key}" in gh, (out[-300:], gh)
        rc, out, gh = _guard_gh(fail="1", IN_COUNTS_ONLY="false")
        assert rc != 0 and "fail closed" in out, out[-300:]
        rc, out, gh = _guard_gh(count="0", IN_COUNTS_ONLY="false")
        assert rc == 0 and f"READ_KEY={key}" in (td / "genv").read_text(encoding="utf-8"), out[-300:]
        assert G.untracked_manifests([str(Path(__file__).resolve().parent.parent / "data-analysis"
                                          / "gate2-reader-holdout-2026-10-27.csv")]) == []
    assert G.untracked_manifests([str(csvp)]) == [str(csvp.resolve())], "临时名单不在 git 里"
    assert wf["jobs"]["gate2"]["permissions"] == {"contents": "read", "actions": "read"}, "Guard 查 artifact 要 actions: read"
    run_reader = next(s for s in steps if s.get("name", "").startswith("副题库闸二"))
    assert "--bank reader" in run_reader["run"] and "--write" not in run_reader["run"] and run_reader["if"].count("reader")
    # 真跑一遍 reader 那步的 bash (python 换成桩: 记参数, 成功时往 --out 写「读的结果」、往 stderr 写两行状态, 退出码按 STUB_RC):
    # counts_only=true 才带 --counts-only、写 …-counts.md; false 不带、写 feature-gate2-<TAG>.md —— 少了 --counts-only,
    # 「只数」的那一下就成了那唯一一次读, 还打进公开的 job log
    wfdir = td / "wf"
    (wfdir / "scripts").mkdir(parents=True)
    (wfdir / "data-analysis").mkdir()
    pybin = td / "pybin"
    pybin.mkdir()
    (pybin / "python").write_text(
        '#!/bin/sh\nprintf "%s\\n" "$@" > "$ARGV_LOG"\nout=""; prev=""\n'
        'for a in "$@"; do [ "$prev" = "--out" ] && out="$a"; prev="$a"; done\nrc="${STUB_RC:-0}"\n'
        'if [ "$rc" = "0" ]; then echo "READ-STDERR validated" >&2; [ -n "$out" ] && echo "READ-RESULT" > "$out"; '
        'else echo "REFUSE-REASON" >&2; fi\n'
        '[ "$rc" = "3" ] && [ -n "$out" ] && echo "VOID-COUNTS" > "${out%.md}-void.md"\nexit "$rc"\n', encoding="utf-8")
    (pybin / "python").chmod(0o755)
    rfile = td / "reader.sh"
    rfile.write_text(run_reader["run"], encoding="utf-8")
    summary = td / "summary.md"
    for co, stub_rc in (("true", "0"), ("false", "0"), ("false", "2")):
        summary.unlink(missing_ok=True)
        e = dict(os.environ, PATH=str(pybin) + os.pathsep + os.environ.get("PATH", ""), ARGV_LOG=str(td / "argv.txt"),
                 IN_COUNTS_ONLY=co, MANIFESTS=" data-analysis/w1.csv data-analysis/w2.csv", TAG="gate2-reader-t",
                 IN_SHA=SEC_SHA[:12], READ_KEY="0" * 12, GITHUB_STEP_SUMMARY=str(summary), RUNNER_TEMP=str(td), STUB_RC=stub_rc)
        p = subprocess.run(["bash", "-e", str(rfile)], cwd=wfdir / "scripts", env=e, capture_output=True, text=True)
        argv = (td / "argv.txt").read_text(encoding="utf-8").splitlines()
        assert p.returncode == int(stub_rc) and argv[:3] == ["gate2_run.py", "--bank", "reader"], (co, p.returncode, p.stderr[-300:], argv)
        assert ("--counts-only" in argv) == (co == "true") and "--write" not in argv, (co, argv)
        want = "../data-analysis/feature-gate2-gate2-reader-t" + ("-counts.md" if co == "true" else ".md")
        assert argv[argv.index("--out") + 1] == want, (co, argv)
        assert [argv[i + 1] for i, a in enumerate(argv) if a == "--manifest"] == ["../data-analysis/w1.csv", "../data-analysis/w2.csv"]
        shown = p.stdout + p.stderr + (summary.read_text(encoding="utf-8") if summary.exists() else "")
        if co == "true":                                    # 只数行数: 照旧当场打出来
            assert "READ-RESULT" in shown and "READ-STDERR" in shown, shown[-300:]
        elif stub_rc == "0":                                # 正式读: 记号传上去之前结果哪儿都不露 (stderr 存着, 报告不打)
            assert "READ-RESULT" not in shown and "READ-STDERR" not in shown, shown[-300:]
            assert "READ-STDERR" in (td / "gate2-reader-stderr.txt").read_text(encoding="utf-8")
        else:                                               # 拒跑: 原因照打
            assert "REFUSE-REASON" in shown, shown[-300:]
    # 读过的记号: 紧跟在 reader 那步后面, 名字按 Guard 查的那个, 文件就是正式读写的那份; 报告文件在就传 (always(), 不看前面成没成)
    mark = steps[steps.index(run_reader) + 1]
    assert mark.get("uses", "").startswith("actions/upload-artifact") and mark["with"]["name"] == "gate2-reader-read-${{ env.READ_KEY }}", mark
    assert mark["with"]["path"] == "data-analysis/feature-gate2-${{ env.TAG }}.md" and mark["with"]["if-no-files-found"] == "error"
    assert mark.get("id") and "env.IN_BANK == 'reader'" in mark["if"] and "env.IN_COUNTS_ONLY == 'false'" in mark["if"]
    assert "gate2-reader-read-$KEY" in guard and "READ_KEY=$KEY" in guard
    # 整个 job 按 if 走一遍 (只认这个 workflow 用到的写法; reader 相关的 run 步真跑 bash, python 是上面的桩):
    # 不管记号传成没成、中途取消没有, 读的结果 (报告 / 两行状态) 只能在记号传上去之后露出来 (job log、step summary、别的 artifact)
    import re as _re

    def _if_ok(step, st) -> bool:
        expr = (step.get("if") or "").strip()
        atoms = [a.strip() for a in expr.split("&&")] if expr else []
        ok = st["status"] == "success" or any(a in ("always()", "!cancelled()", "failure()", "cancelled()") for a in atoms)
        for a in atoms:
            if a == "always()":
                continue
            if a == "success()":
                ok = ok and st["status"] == "success"
                continue
            m = _re.fullmatch(r"(env|steps)\.(\w+)(?:\.outcome)? (==|!=) '([^']*)'", a)
            h = _re.fullmatch(r"hashFiles\(format\('([^']*)', env\.(\w+)\)\) != ''", a)
            if m:
                v = (st["env"] if m[1] == "env" else st["outcome"]).get(m[2], "")
                ok = ok and ((v == m[4]) == (m[3] == "=="))
            elif h:
                ok = ok and (st["ws"] / h[1].replace("{0}", st["env"].get(h[2], ""))).is_file()
            else:
                raise AssertionError(f"workflow 模拟不认识的 if: {a!r} ({step.get('name')})")
        return ok

    def _job(name, stub_rc="0", mark_fails=False, cancel_after_reader=False):
        ws = td / f"job-{name}"
        for d in ("scripts", "data-analysis", "tmp"):
            (ws / d).mkdir(parents=True)
        tag = "gate2-reader-t"
        st = {"status": "success", "outcome": {}, "ws": ws,
              "env": {"IN_BANK": "reader", "IN_COUNTS_ONLY": "false", "IN_IGNORE_PLACEBO": "false", "IN_WRITE": "false",
                      "TAG": tag, "READ_KEY": "0" * 12, "MANIFESTS": " data-analysis/w1.csv", "IN_SHA": SEC_SHA[:12]}}
        report = ws / "data-analysis" / f"feature-gate2-{tag}.md"
        summ = ws / "summary.md"
        marked, leaks, ran = False, [], []
        for s in steps:
            sname = s.get("name") or s.get("uses", "")
            if not _if_ok(s, st):
                if s.get("id"):
                    st["outcome"][s["id"]] = "skipped"
                continue
            ran.append(sname)
            outcome, shown = "success", ""
            if s.get("uses", "").startswith("actions/upload-artifact"):
                paths = [ln.strip().replace("${{ env.TAG }}", tag) for ln in str(s["with"]["path"]).splitlines() if ln.strip()]
                if s is mark:
                    outcome = "failure" if mark_fails or not report.is_file() else "success"
                    marked = marked or outcome == "success"
                elif f"data-analysis/feature-gate2-{tag}.md" in paths and report.is_file():
                    shown = report.read_text(encoding="utf-8")
            elif "run" in s and (s is run_reader or "reader" in (s.get("if") or "") or "read_mark" in (s.get("if") or "")):
                before = summ.read_text(encoding="utf-8") if summ.exists() else ""
                e = dict(os.environ, PATH=str(pybin) + os.pathsep + os.environ.get("PATH", ""), ARGV_LOG=str(ws / "argv.txt"),
                         GITHUB_STEP_SUMMARY=str(summ), RUNNER_TEMP=str(ws / "tmp"), STUB_RC=stub_rc, **st["env"])
                p = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", s["run"]],
                                   cwd=ws / s.get("working-directory", "."), env=e, capture_output=True, text=True)
                outcome = "success" if p.returncode == 0 else "failure"
                shown = p.stdout + p.stderr + (summ.read_text(encoding="utf-8") if summ.exists() else "")[len(before):]
            if ("READ-RESULT" in shown or "READ-STDERR" in shown) and not marked:
                leaks.append(sname)
            if s.get("id"):
                st["outcome"][s["id"]] = outcome
            if outcome == "failure" and st["status"] == "success":
                st["status"] = "failure"
            if s is run_reader and cancel_after_reader:
                st["status"] = "cancelled"
        return {"marked": marked, "leaks": leaks, "ran": ran, "report_left": report.is_file(),
                "summary": summ.read_text(encoding="utf-8") if summ.exists() else ""}
    ok = _job("ok")
    assert ok["marked"] and not ok["leaks"] and "READ-RESULT" in ok["summary"], ok
    for name, kw in (("mark-fails", {"mark_fails": True}), ("cancelled", {"cancel_after_reader": True}),
                     ("void", {"stub_rc": "3"}), ("refused", {"stub_rc": "2"})):
        r = _job(name, **kw)
        assert not r["leaks"], (name, r)                    # 记号没传上去的时候, 结果一处都没露
        assert "READ-RESULT" not in r["summary"], (name, r)
        assert r["marked"] == (name == "cancelled"), (name, r)   # 读完再取消: 报告在就传记号; 作废 / 拒跑不传
        if name == "mark-fails":                           # 记号传失败: 报告在离开 runner 之前删掉, 重跑再读不算第二次
            assert not r["report_left"], r
    # Guard: 仓库里已有同名报告 (这里借已提交的主题库报告 feature-gate2-gate2-20261010.md) → 拒, 不让旧文件冒充这次读去传记号
    if in_git:
        rc, out, gh = _guard_gh(count="0", IN_COUNTS_ONLY="false", IN_RUN_TAG="gate2-20261010")
        assert rc != 0 and "已经在仓库里" in out and not gh, (out[-300:], gh)
    combo = next(s for s in steps if s.get("name", "").startswith("组合进不进 L2"))
    assert "primary" in combo["if"], "组合对比只给主题库"
    # 进了仓库的第一波名单: sha 和 D-128 补记一致、全在留出半 (10-27 映射表里没有一篇是它的 new_id / old_id)、没有点名的篇
    wave1 = Path(__file__).resolve().parent.parent / "data-analysis" / "gate2-reader-holdout-2026-10-27.csv"
    (m1,) = G.load_manifests([str(wave1)])
    assert m1["sha256"] == "c761364a9d9d4af4d0920fb36bb20df836150fa3b005236b360d27ba3584fd36" and len(m1["rows"]) == 1227
    ids = [r["note_id"] for r in m1["rows"]]
    assert not any(in_discovery_half(n) for n in ids) and not set(ids) & set(gs.EXCLUDE)
    assert hashlib.md5(",".join(sorted(ids)).encode()).hexdigest() == "18a22fa1c54bcc9829d4dd6747351a67"
    assert G.combined_manifest_sha(ids) == "35549d5ca27be3e1b6790603ac980172aece006115e34e8adcdf7f154301e27a", \
        "名单 sha 的定义变了 (D-128 补记: 第一波单独 = 35549d5ca27b…)"
    dec = (Path(__file__).resolve().parent.parent / "DECISIONS.md").read_text(encoding="utf-8")
    assert m1["sha256"] in dec, "D-128 补记里记的第一波名单 sha 对不上"
    print("  §8o CLI: 范围 / 判据 / 抽取器 / draft / 忽略报警 / run_tag / 缺 sha / 缺名单 / 名单重叠 → 2; counts-only 写 …-counts.md; "
          "主题库不收副题库参数、--bank primary 能用; workflow reader 分支不写库、counts_only 才带 --counts-only、"
          "读完传记号 artifact、记号传上去之前结果不露 (传失败 / 取消 / 作废 / 拒跑整 job 走一遍)、Guard 见记号 / 查不了 / 同名报告已在就拒、"
          "组合对比只给主题库; "
          "第一波名单 sha c761364a… / 1,227 篇 / 全在留出半 / md5 18a22fa1… ✓")


# ── §8p 按现在的标签和项目算, 不按名单写死时的 (补记 4) ─────────────────────────────────────
def check_secondary_current_labels() -> None:
    ds, man = _sec_fixture()
    res = _sec_run(ds, man)
    assert res["y_changed"] == 0 and res["project_changed"] == 0
    ana = _analysis_ids(res, ds, man)
    flip = [m["note_id"] for m in man if m["note_id"] in ana and m["project_id"] == "P1"][:5]
    moved = [m["note_id"] for m in man if m["note_id"] in ana and m["project_id"] == "P0"][:40]
    man2 = []
    for m in man:
        m = dict(m)
        if m["note_id"] in flip:
            m["y"] = 1 - int(m["y"])                       # 名单写死之后标签变了
        if m["note_id"] in moved:
            m["project_id"] = "PX"                         # 名单写死时的旧项目 (挪表前那种): 分层用现在的项目
        man2.append(m)
    r2 = _sec_run(ds, man2)
    assert r2["y_changed"] == 5 and r2["project_changed"] == 40, (r2["y_changed"], r2["project_changed"])
    assert _cmp(r2) == _cmp(res) and r2["big_projects"] == res["big_projects"], "名单里写死的 y / 项目不该进计算"
    for r, r0 in zip(r2["family_rows"], res["family_rows"]):
        assert r["big_within"] == r0["big_within"] and r["strata"] == r0["strata"], r["question_id"]
    print("  §8p 名单写死时的 y (5 篇) / 项目 (40 篇) 和现在不同: 只记数, 计算全按现在的标签和项目 (补记 4) ✓")


# ── §8q 有支持的大项目: 大项目里没有这个取值的不算 ───────────────────────────────────────────
def check_secondary_big_support() -> None:
    ds, man = _sec_fixture(extras=False)
    for a in ds["answers"]:                                # P3 里「挑一个 / 说自己的」一篇都没有 (都改成求推荐)
        if a["question_id"] == "reader_ask_form" and a["subject_id"].startswith("P3_") and a["answer"] in ("挑一个", "说自己的"):
            a["answer"] = "求推荐"
    res = _sec_run(ds, man)
    assert set(res["big_projects"]) == {"P0", "P1", "P2", "P3"}, res["big_projects"]
    c1 = _row2(res, "reader_ask_form", "挑一个+说自己的")
    assert c1["big_projects_n"] == 3 and set(c1["big_within"]) == {"P0", "P1", "P2"}, (c1["big_projects_n"], c1["big_within"])
    assert c1["n_or_above_1"] + c1["n_or_below_1"] <= 3
    assert _row2(res, "invites_sharing", "是")["big_projects_n"] == 4
    # 占位题报警的「有支持的大项目 ≥ 3」也是这个数: 四个大项目里只有两个有「是」→ 不报; 其余三条都满足 (换成 4 就报)
    notes = [{"note_id": f"{p}_{i:03d}", "project_id": p, "cond": ("是", "否"), "y": int(i < 30)}
             for p in ("P0", "P1", "P2", "P3") for i in range(100)]
    has = {n["note_id"] for n in notes if n["project_id"] in ("P0", "P1") and (int(n["note_id"][3:]) < 12 or 30 <= int(n["note_id"][3:]) < 38)}
    row = G._sec_stats(notes, lambda n: n["note_id"] in has, strata_of=lambda n: (n["project_id"],) + n["cond"],
                       big={"P0", "P1", "P2", "P3"})
    assert row["support"] == 40 and row["big_projects_n"] == 2 and not G.placebo_alarm(row), row
    assert G.placebo_alarm(dict(row, big_projects_n=4)), "夹具其余三条要满足, 不然测不出这一条"
    print("  §8q 有支持的大项目: C1 在 P3 没支持 → 4 个大项目只算 3 个; 占位题只有 2 个大项目有支持 → 不报警 ✓")


def main() -> int:
    check_golden()
    check_single_stratum_is_woolf()
    check_bh()
    check_status_matrix()
    check_confounded_by_account_prior()
    check_placebo_alarm_refuses()
    check_snapshot_uniqueness()
    check_rows_digest()
    check_frozen_required()
    check_frozen_but_edited_refused()
    check_gate1_status_from_bank()
    check_analysis_filter_and_big_projects()
    check_projects_present()
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        check_secondary_golden()
        check_secondary_never_writes(t)
        check_secondary_half_alias()
        check_secondary_simpson()
        check_secondary_drops()
        check_secondary_base_and_merged()
        check_secondary_bh_family()
        check_secondary_placebo(t)
        check_secondary_snapshot_pinning()
        check_secondary_prereg()
        check_secondary_counts_only(t)
        check_secondary_sensitivity()
        check_secondary_single_read(t)
        check_secondary_fetch()
        check_secondary_cli_and_workflow(t)
        check_secondary_current_labels()
        check_secondary_big_support()
    print("\ncheck_gate2_run: 13 节 + §8 副题库 17 节全过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
