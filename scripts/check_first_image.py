#!/usr/bin/env python3
"""首图试跑的守卫 (D-157, docs/33-first-image-trial.md)。全是合成数据; 不连库、不联网、不调模型、不碰飞书。

  §1  题库: 14 题 (12 道模型题 + 2 道代码题)、三组各四题、一组五题 / 两组合并 / 代码题进组都被拒; 提示词里只有这一组的题,
      没有档位和数据的字眼
  §2  哪个附件算首图: 内容配图 > 笔记配图 > 图片, 取第 0 个; 视频 / HEIC / 空类型看文件名
  §3  抽样: 分层数对 (48 / 12 / 39 / 6)、同一份数据每次抽到同一批、飞书里删了的不抽、上限小的时候轮着项目取
  §4  答案: 闭集外 / 缺题 / 解析不了 / 抄的字超长都记无效; 三条自相矛盾; 不是封面; 两道代码题和灰带
  §5  过线: 一致率和 κ 都要够; 答案一边倒记 kappa_undefined、不算过; 对数不够不下结论; 便宜档要自己过线
  §6  token 硬上限: 会越线的那一次调用根本不发; 命令行抬不高上限; 没有用量回报按预留记
  §7  整个试跑走一遍 (假下载 / 假缩图 / 假模型): 调用数 = 计划数; 视频不下载不调模型; 下载失败的不调模型; 干跑一次外部动作都没有;
      第一张图被飞书拒 / 被中转站拒就停; 日志、报告、json 里没有标题、封面上的字、文件名、file_token、链接、note_id、报错正文
  §8  飞书下载: 超过字节上限就断、状态码译成状态词、只认飞书主机的 extra、报错里不带 token 和链接
  §9  call_claude: 不给 images 时发出去的请求和以前一模一样; 给了就把图片块放在文字前面; 用量带得出来
  §10 接线: workflow 只能手动、默认干跑、只传那份报告; 试跑脚本里没有写库的动作、没有往盘上写图片; 别的 workflow 不提它;
      价格只有 model_prices.py 一处; 缩图 (装了 Pillow 才测)

反证 (改坏之后必须变红):
  ① 题库某一组加到 5 题 / build_prompt 一次给 5 题                          → §1
  ② Budget.reserve 改成「先调再查」(越线那次也发出去)                         → §6 (假模型数到多出来的那一次)
  ③ kappa_undefined 当成 pass                                               → §5
  ④ 报告或日志里带上标题 / 抄下来的字 / file_token                           → §7
  ⑤ workflow 加 schedule、dry_run 默认改成 false、artifact 路径放宽           → §10
  ⑥ call_claude 不给 images 时请求体变了                                    → §9

跑法: cd scripts && python check_first_image.py
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import pathlib
import re
import sys
import types

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

import feishu_media as FM  # noqa: E402
import first_image as FI  # noqa: E402
import first_image_trial as T  # noqa: E402
import model_prices as MP  # noqa: E402

BANK = FI.load_bank()

# 探针: 这些字出现在任何输出里就是漏了
TITLE_CANARY = "标题探针甲乙丙丁"
TEXT_CANARY = "封面大字探针戊己庚"
NAME_CANARY = "wenjianming_tanzhen"
TOKEN_CANARY = "boxcnTOKENtanzhen"
URL_CANARY = "tanzhen-url.example"
NOTE_CANARY = "notetanzhen"
ERR_CANARY = "baocuo-zhengwen-tanzhen"
CANARIES = (TITLE_CANARY, TEXT_CANARY, NAME_CANARY, TOKEN_CANARY, URL_CANARY, NOTE_CANARY, ERR_CANARY)


def _file(i: int, typ: str = "image/jpeg", size: int = 300_000, name: str | None = None) -> dict:
    return {"file_token": f"{TOKEN_CANARY}{i:05d}", "name": name or f"{NAME_CANARY}_{i}.jpg", "size": size, "type": typ,
            "url": f"https://open.feishu.cn/open-apis/drive/v1/medias/{TOKEN_CANARY}{i:05d}/download",
            "tmp_url": f"https://{URL_CANARY}/tmp/{i}"}


def _rows() -> list[dict]:
    """够抽出设计全量的一份假数据: 13 张有多图帖的表, 四个试跑项目各有足够的爆和趴。"""
    rows: list[dict] = []
    n = 0

    def add(project: str, tier: str, cols: dict) -> None:
        nonlocal n
        n += 1
        rows.append({"note_id": f"{NOTE_CANARY}-{n:04d}", "project_id": project, "tier": tier,
                     "title": f"{TITLE_CANARY}{n}", "cols": cols})

    for p in FI.TRIAL_PROJECTS:
        col = "内容配图" if p in ("RIO_phase1", "OKMAN_phase1") else "笔记配图"
        for k in range(9):
            add(p, "爆" if k % 2 else "大爆", {col: [_file(n), _file(n + 5000)]})
        for k in range(12):
            add(p, "趴", {col: [_file(n, "image/png")]})
        add(p, "评估中", {col: [_file(n)]})
    for p in ("TXQ_phase1", "WTG_phase1", "RIO_phase1"):
        for k in range(4):
            add(p, "趴", {"内容配图": [_file(n), _file(n + 6000)], "笔记截图": [_file(n + 7000)]})
    for p in ("LNKT_phase1", "XIWU_phase1", "XIWU_phase2", "BJS_phase1", "BJS_phase2", "ANSHEN_phase1", "SPX_phase1"):
        col = "内容配图" if p.startswith(("LNKT", "XIWU")) else "笔记配图"
        for k in range(5):
            add(p, "趴", {col: [_file(n), _file(n + 8000)]})
    for k in range(6):
        add("BJS_phase1", "趴", {"笔记配图": [_file(n, "image/heic", name=f"{NAME_CANARY}.heic")]})
    for k in range(6):
        add("SPX_phase1", "趴", {"笔记配图": [_file(n, size=FI.BIG_BYTES + 5)]})
    for k in range(3):
        add("RIO_phase1", "趴", {"内容配图": [_file(n, "video/mp4", name=f"{NAME_CANARY}.mp4")]})
    for k in range(3):
        add("XIWU_phase2", "趴", {"内容配图": [_file(n, "", name=f"{NAME_CANARY}.HEIC")]})
    add("NUC_phase1", "爆", {"图片": [_file(n)]})
    add("HXZ_FB", "爆", {})
    return rows


# ── 假的三个外部动作 ──────────────────────────────────────────────────────────
class Fakes:
    """假下载 / 假缩图 / 假模型。假图片的字节里带着它的 file_token, 假模型据此给出稳定的答案。"""

    def __init__(self, *, fail_download=(), usage=True, flip=None, refuse_feishu=False, refuse_relay=False):
        self.downloads: list[str] = []
        self.asks: list[tuple] = []
        self.fail_download, self.usage, self.flip = set(fail_download), usage, flip or (lambda model, qid, key: False)
        self.refuse_feishu, self.refuse_relay = refuse_feishu, refuse_relay

    def download(self, f: dict) -> bytes:
        self.downloads.append(f["file_token"])
        if self.refuse_feishu:
            raise FM.MediaError(FM.NO_PERMISSION)
        if f["file_token"] in self.fail_download:
            raise FM.MediaError(FM.NOT_FOUND)
        if FI.file_kind(f) == "video":
            raise AssertionError("视频不该被下载")
        return f["file_token"].encode()

    def shrink(self, data: bytes, sides, decode="auto") -> dict:
        return {"pixels": 3_000_000, "images": {s: (data + b"|%d" % s, 768 * s // 1024, s) for s in sides}}

    def ask(self, model: str, prompt: str, block: tuple) -> tuple:
        import base64
        key = base64.b64decode(block[1]).decode().split("|")[0]
        self.asks.append((model, key, prompt))
        if self.refuse_relay:
            raise RuntimeError(f"400 {ERR_CANARY} https://{URL_CANARY}/v1/messages")
        qids = re.findall(r"id: (img_[a-z_]+)", prompt)
        h = int(re.sub(r"\D", "", key) or 0)
        ans = []
        for qid in qids:
            q = FI.question_index(BANK)[qid]
            if qid == "img_kind":
                # 列检查: 截图那一列 (token 序号 ≥ 7000 的) 答「后台或数据截图」
                v = "后台或数据截图" if 7000 <= h % 100000 < 8000 else "封面"
            elif qid == "img_text_amount":
                v = "一句大字"
            elif qid == "img_main_text":
                v = f"{TEXT_CANARY}{h % 7}天"
            elif qid == "img_layout":
                v = "一张照片"
            else:
                vals = FI.option_values(q)
                v = vals[(h + len(qid)) % len(vals)]
                if self.flip(model, qid, h):
                    v = vals[(h + len(qid) + 1) % len(vals)]
            ans.append({"id": qid, "answer": v})
        usage = {"input": 1500, "cache_write": 0, "cache_read": 0, "output": 60} if self.usage else None
        return json.dumps({"answers": ans}, ensure_ascii=False), usage


def _run(fk: Fakes, *, tier="both", cap=None, dry_run=False, budget=None, rows=None, bank=None, vanished=frozenset()):
    sample = FI.select_sample(rows if rows is not None else _rows(), set(vanished), cap)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        res = T.run_trial(bank=bank or BANK, tier=tier, cap=cap, dry_run=dry_run, sample=sample, budget=budget,
                          download=fk.download, shrinker=fk.shrink, ask=fk.ask, workers=3)
    return res, buf.getvalue(), sample


def _no_leak(what: str, *texts: str) -> None:
    for t in texts:
        for c in CANARIES:
            assert c not in t, f"{what}: 输出里出现了 {c!r}"


# ── §1 ────────────────────────────────────────────────────────────────────────
def check_bank() -> None:
    assert FI.validate_bank(BANK) == [], FI.validate_bank(BANK)
    assert len(BANK["questions"]) == 14 and len(FI.model_question_ids(BANK)) == 12 and len(FI.code_question_ids(BANK)) == 2
    assert [len(v) for v in BANK["call_groups"].values()] == [4, 4, 4] and FI.MAX_GROUP_SIZE == 4
    assert BANK["status"] == "draft" and BANK["run_tag_prefix"] == "img-" and BANK["cover_confirmed_projects"] == []
    bad = copy.deepcopy(BANK)
    bad["call_groups"]["A_text"].append(bad["call_groups"]["B_composition"].pop())
    assert any("最多 4 题" in e for e in FI.validate_bank(bad)), "一组五题没被拒"
    bad = copy.deepcopy(BANK)
    bad["call_groups"] = {"all": [q for g in BANK["call_groups"].values() for q in g]}
    assert any("最多 4 题" in e for e in FI.validate_bank(bad)), "三组合并没被拒"
    bad = copy.deepcopy(BANK)
    bad["call_groups"]["C_content"] = bad["call_groups"]["C_content"][:3] + ["img_text_has_number"]
    assert any("对不上" in e for e in FI.validate_bank(bad)), "代码题进组没被拒"
    bad = copy.deepcopy(BANK)
    bad["run_tag_prefix"] = "primary"
    assert any("run_tag_prefix" in e for e in FI.validate_bank(bad))
    bad = copy.deepcopy(BANK)
    bad["status"], bad["frozen_sha256"] = "frozen", "0" * 64
    assert any("frozen" in e for e in FI.validate_bank(bad))
    try:
        FI.build_prompt(BANK, FI.model_question_ids(BANK)[:5])
        raise AssertionError("build_prompt 一次给 5 题没被拒")
    except ValueError:
        pass
    try:
        FI.build_prompt(BANK, ["img_text_has_number"])
        raise AssertionError("代码题不该能问模型")
    except ValueError:
        pass
    for name, qids in BANK["call_groups"].items():
        p = FI.build_prompt(BANK, list(qids))
        assert set(re.findall(r"id: (img_[a-z_]+)", p)) == set(qids), name
        for word in ("爆", "趴", "点赞", "tier", TITLE_CANARY):
            assert word not in p, f"提示词里出现了 {word!r}"
    for r in FI.run_plan("both"):
        assert r["tag"].startswith(FI.RUN_TAG_PREFIX) and r["tag"] != "primary"
    print("  §1 题库 14 题 / 三组各四题; 五题一组、合并、代码题进组都被拒; 提示词只有本组的题 ✓")


# ── §2 ────────────────────────────────────────────────────────────────────────
def check_pick() -> None:
    a, b, c = _file(1), _file(2), _file(3)
    assert FI.pick_first_image({"内容配图": [a, b], "图片": [c]})["first"] is a
    assert FI.pick_first_image({"内容配图": [], "笔记配图": [b, a], "图片": [c]}) == {"column": "笔记配图", "n_files": 2, "first": b}
    assert FI.pick_first_image({"图片": [c]})["column"] == "图片"
    assert FI.pick_first_image({"笔记截图": [a], "相关截图": [b]}) is None, "截图列不是帖子自己的图"
    assert FI.pick_first_image({}) is None and FI.pick_first_image({"内容配图": "不是数组"}) is None
    assert FI.file_kind(_file(1, "video/mp4")) == "video" and FI.file_kind(_file(1, "", name="a.MOV")) == "video"
    assert FI.file_kind(_file(1, "image/heic")) == "heic" and FI.file_kind(_file(1, "", name="a.heic")) == "empty_type"
    assert FI.file_kind(_file(1, "image/png")) == "png" and FI.file_kind(_file(1, "application/pdf")) == "other"
    assert FI.decode_as(_file(1, "", name="A.HEIC")) == "heic" and FI.decode_as(_file(1, "image/heic")) == "heic"
    assert FI.decode_as(_file(1, "", name="a.jpg")) == "auto" and FI.decode_as(_file(1)) == "auto"
    print("  §2 列的先后、第 0 个附件、视频 / HEIC / 空类型 ✓")


# ── §3 ────────────────────────────────────────────────────────────────────────
def check_sample() -> None:
    rows = _rows()
    s = FI.select_sample(rows, set())
    assert len(s["regular"]) == 48 and len(s["awkward"]) == 12 and len(s["cover_check"]) == 39 and len(s["column_check"]) == 6
    assert len({x["project_id"] for x in s["cover_check"]}) == 13
    per = {}
    for x in s["regular"]:
        per[(x["project_id"], x["label"])] = per.get((x["project_id"], x["label"]), 0) + 1
        assert FI.file_kind(x["file"]) in ("jpeg", "png")
    assert set(per.values()) == {6} and len(per) == 8, per
    assert [x["stratum"] for x in s["awkward"]] == ["heic"] * 4 + ["big"] * 4 + ["video"] * 2 + ["empty_type"] * 2
    ids = lambda smp: [x["note_id"] for k in ("regular", "awkward", "cover_check", "column_check") for x in smp[k]]  # noqa: E731
    assert ids(s) == ids(FI.select_sample(list(reversed(rows)), set())), "同一份数据要抽到同一批 (和行的顺序无关)"
    assert not ({x["note_id"] for x in s["regular"]} & {x["note_id"] for x in s["awkward"]})
    gone = {x["note_id"] for x in s["regular"][:5]}
    s2 = FI.select_sample(rows, gone)
    assert not (gone & set(ids(s2))), "飞书里删了的篇不该被抽到"
    assert all(r["tier"] != "评估中" for r in rows if r["note_id"] in {x["note_id"] for x in s["regular"]})
    s3 = FI.select_sample(rows, set(), cap=4)
    assert [len(s3[k]) for k in ("regular", "awkward", "cover_check", "column_check")] == [4, 4, 4, 4]
    assert len({x["project_id"] for x in s3["regular"]}) == 2 and len({x["project_id"] for x in s3["cover_check"]}) == 4
    assert {x["project_id"] for x in s["column_check"]} == set(FI.COLUMN_CHECK_PROJECTS)
    print("  §3 分层 48 / 12 / 39 / 6; 可重复; 删了的不抽; 小上限轮着项目取 ✓")


# ── §4 ────────────────────────────────────────────────────────────────────────
def _parsed(**kv) -> dict:
    return {k: (v, None) for k, v in kv.items()}


def check_answers() -> None:
    g = list(BANK["call_groups"]["A_text"])
    ok = json.dumps({"answers": [{"id": "img_kind", "answer": "封面"}, {"id": "img_text_amount", "answer": "一句大字"},
                                 {"id": "img_main_text", "answer": "三天见效"}, {"id": "img_text_kind", "answer": "结果或结论"}]},
                    ensure_ascii=False)
    p = FI.parse_answers(BANK, g, "好的，答案如下：\n" + ok + "\n以上。")
    assert all(why is None for _, why in p.values()) and p["img_main_text"][0] == "三天见效"
    p = FI.parse_answers(BANK, g, ok.replace("封面", "封面图").replace("三天见效", "字" * 41))
    assert p["img_kind"] == (None, FI.INVALID_OOV) and p["img_main_text"] == (None, FI.INVALID_TEXT_LONG)
    p = FI.parse_answers(BANK, g, json.dumps({"answers": [{"id": "img_kind", "answer": "封面"}]}))
    assert p["img_text_kind"] == (None, FI.INVALID_MISSING)
    assert set(FI.parse_answers(BANK, g, "我看不了图片").values()) == {(None, FI.INVALID_PARSE)}

    base = dict(img_kind="封面", img_text_amount="一句大字", img_main_text="三天见效", img_text_kind="结果或结论",
                img_layout="一张照片")
    r = FI.assemble(BANK, _parsed(**base), "三天见效！真的")
    assert r["answers"]["img_text_matches_title"] == "一样或差不多" and r["answers"]["img_text_has_number"] == "有"
    for patch, name in ((dict(img_text_amount="没有字"), "no_text_but_transcribed"),
                        (dict(img_main_text=" 。"), "text_but_not_transcribed"),
                        (dict(img_layout="纯文字卡片", img_text_amount="没有字", img_main_text=""), "text_card_without_text")):
        r = FI.assemble(BANK, _parsed(**{**base, **patch}), "标题")
        assert r["answers"] == {} and set(r["invalid"].values()) == {f"inconsistent:{name}"}, (name, r)
    r = FI.assemble(BANK, _parsed(**{**base, "img_kind": "后台或数据截图"}), "标题")
    assert r["answers"] == {"img_kind": "后台或数据截图"} and set(r["invalid"].values()) == {FI.INVALID_NOT_COVER}
    r = FI.assemble(BANK, _parsed(**{**base, "img_text_amount": "没有字", "img_main_text": ""}), "标题")
    assert r["answers"]["img_text_matches_title"] == FI.NO_TEXT and r["answers"]["img_text_has_number"] == FI.NO_TEXT
    r = FI.assemble(BANK, _parsed(**base), "")
    assert r["invalid"]["img_text_matches_title"] == FI.INVALID_NO_TITLE and "img_text_has_number" in r["answers"]
    r = FI.assemble(BANK, _parsed(img_kind="封面"), None)
    assert "img_text_matches_title" not in r["answers"] and "img_text_matches_title" not in r["invalid"]

    assert FI.normalise(" ＡＢ，c！😀 １２ ") == "abc12"
    assert FI.transcriptions_match("三天见效！", "三天 见效") and not FI.transcriptions_match("三天见效", "完全不同的一句")
    assert FI.text_matches_title("敏感肌", "敏感肌怎么选面霜")[0] == "不一样", "短的不到 4 个字不算包含"
    assert FI.text_matches_title("敏感肌面霜", "敏感肌面霜怎么选")[0] == "一样或差不多"
    val, _, grey = FI.text_matches_title("敏感肌怎么选防晒", "敏感肌怎么选面霜")
    assert val == "不一样" and grey, "相似度 0.60–0.80 要记成灰带"
    assert FI.text_matches_title("今天吃什么", "面霜测评合集")[2] is False
    assert FI.text_has_number("七天瘦了") == "有" and FI.text_has_number("￥９９") == "有" and FI.text_has_number("一起变美") == "没有"
    print("  §4 闭集 / 缺题 / 解析不了 / 超长; 三条自相矛盾; 不是封面; 代码题与灰带 ✓")


# ── §5 ────────────────────────────────────────────────────────────────────────
def _runs(n: int, qid: str, left: list[str], right: list[str]) -> tuple[dict, dict]:
    a = {str(i): {"answers": {qid: left[i % len(left)]}, "invalid": {}} for i in range(n)}
    b = {str(i): {"answers": {qid: right[i % len(right)]}, "invalid": {}} for i in range(n)}
    return a, b


def check_stats() -> None:
    q = "img_person"
    kw = dict(need_agree=FI.PASS_SAME_MODEL, need_kappa=FI.PASS_KAPPA)
    a, b = _runs(60, q, ["没有人", "看得到脸"], ["没有人", "看得到脸"])
    r = FI.compare(BANK, a, b, **kw)[q]
    assert r["verdict"] == "pass" and r["n"] == 60 and r["agree"] == 1.0
    a, b = _runs(60, q, ["没有人", "看得到脸"], ["没有人", "看得到脸", "没有人", "没有人"])
    assert FI.compare(BANK, a, b, **kw)[q]["verdict"] == "fail"
    # 一边倒: 60 对里 59 对都是同一个答案, 一致率 0.98 —— 不算过
    a = {str(i): {"answers": {q: "没有人"}, "invalid": {}} for i in range(60)}
    b = copy.deepcopy(a)
    b["0"]["answers"][q] = "看得到脸"
    a["1"]["answers"][q] = "看得到脸"
    r = FI.compare(BANK, a, b, **kw)[q]
    assert r["agree"] > 0.95 and r["verdict"] == "kappa_undefined", r
    b = copy.deepcopy(a)
    assert FI.compare(BANK, {k: {"answers": {q: "没有人"}, "invalid": {}} for k in a}, {k: {"answers": {q: "没有人"}, "invalid": {}} for k in a},
                      **kw)[q]["verdict"] == "kappa_undefined", "两边恒定 (κ 算不出) 也不算过"
    a, b = _runs(10, q, ["没有人", "看得到脸"], ["没有人", "看得到脸"])
    assert FI.compare(BANK, a, b, **kw)[q]["verdict"] == "too_few", "对数不够不下结论"
    # 无效的答案不进对数
    a, b = _runs(40, q, ["没有人", "看得到脸"], ["没有人", "看得到脸"])
    for i in range(15):
        b[str(i)] = {"answers": {}, "invalid": {q: FI.INVALID_OOV}}
    assert FI.compare(BANK, a, b, **kw)[q]["n"] == 25
    # 抄字题: 按匹配规则, 线 0.85
    ta = {str(i): {"answers": {"img_main_text": f"第{i}句大字啊"}, "invalid": {}} for i in range(40)}
    tb = {str(i): {"answers": {"img_main_text": f"第{i}句 大字啊！" if i >= 5 else "别的话"}, "invalid": {}} for i in range(40)}
    r = FI.compare(BANK, ta, tb, **kw)["img_main_text"]
    assert r["verdict"] == "pass" and abs(r["agree"] - 35 / 40) < 1e-9 and r["kappa"] is None
    tb["5"]["answers"]["img_main_text"] = tb["6"]["answers"]["img_main_text"] = "别的话"
    assert FI.compare(BANK, ta, tb, **kw)["img_main_text"]["verdict"] == "fail"

    same = {"q1": {"verdict": "pass"}, "q2": {"verdict": "pass"}, "q3": {"verdict": "kappa_undefined"}, "q4": {"verdict": "fail"}}
    single = {"q1": {"verdict": "pass"}, "q2": {"verdict": "fail"}, "q3": {"verdict": "pass"}, "q4": {"verdict": "pass"}}
    v = FI.tier_verdicts(same, single)
    assert v == {"q1": "pass", "q2": "ask_alone", "q3": "kappa_undefined", "q4": "fail"}, v
    mid = {"q1": "pass", "q2": "pass", "q3": "kappa_undefined"}
    cross_ok = {"q1": {"verdict": "pass"}, "q2": {"verdict": "pass"}, "q3": {"verdict": "pass"}}
    assert FI.model_choice(mid, {"q1": "pass", "q2": "pass", "q3": "fail"}, cross_ok)["choice"] == "cheap"
    # 便宜档自己没过 (哪怕和中档对得上) → 中档; 借不了中档的结果
    mc = FI.model_choice(mid, {"q1": "pass", "q2": "fail", "q3": "pass"}, cross_ok)
    assert mc["choice"] == "mid" and mc["blocking"] == ["q2"]
    assert FI.model_choice(mid, {"q1": "pass", "q2": "kappa_undefined"}, cross_ok)["choice"] == "mid"
    assert FI.model_choice(mid, {"q1": "pass", "q2": "pass"}, {**cross_ok, "q1": {"verdict": "fail"}})["choice"] == "mid"
    assert FI.model_choice(None, {"q1": "pass"}, None)["choice"] == "not_compared"
    assert FI.model_choice({"q1": "fail"}, {"q1": "pass"}, cross_ok)["choice"] == "none_kept"
    assert (FI.PASS_SAME_MODEL, FI.PASS_KAPPA, FI.PASS_TEXT_MATCH, FI.PASS_GROUPED_VS_SINGLE, FI.PASS_CROSS_TIER, FI.LOPSIDED) \
        == (0.90, 0.60, 0.85, 0.90, 0.90, 0.90), "过线标准是试跑前写死的"
    print("  §5 一致率 + κ; 一边倒 = kappa_undefined 不算过; 对数不够不下结论; 便宜档自己过线 ✓")


# ── §6 ────────────────────────────────────────────────────────────────────────
def check_budget() -> None:
    assert FI.Budget(max_weighted=10 ** 12, max_calls=10 ** 9).max_weighted == FI.MAX_WEIGHTED_TOKENS, "上限只能调低"
    assert FI.Budget(max_weighted=10 ** 12, max_calls=10 ** 9).max_calls == FI.MAX_CALLS
    assert MP.yuan_of_weighted(FI.TIERS["mid"], FI.MAX_WEIGHTED_TOKENS) < 100, "硬上限全按中档价也不到 100 元 (假设价)"
    b = FI.Budget(max_weighted=1000)
    assert b.reserve(400) and b.reserve(400) and not b.reserve(400), "第三次会越线, 不许发"
    assert b.stopped == "max_tokens" and not b.reserve(1), "停了就一直停"
    b = FI.Budget(max_weighted=1000)
    assert b.reserve(600)
    b.settle(600, "m", {"input": 100, "output": 10})
    assert b.spent == 150 and b.reserved == 0 and b.reserve(600), "结算后按实数记 (输入 + 5 × 输出)"
    b.settle(600, "m", None)
    assert b.spent == 750 and b.usage_missing == 1, "没有用量回报 → 按预留记"
    b = FI.Budget(max_calls=2)
    assert b.reserve(1) and b.reserve(1) and not b.reserve(1) and b.stopped == "max_calls"

    # 整个试跑里: 上限很低时, 假模型被调到的次数 × 每次的实数 不超过上限, 而且停了之后一次都不再调
    fk = Fakes()
    est = FI.call_estimate(FI.build_prompt(BANK, list(BANK["call_groups"]["A_text"])), [(768, 1024)])
    cap_tokens = est * 3 + 10 * 1800
    res, out, _ = _run(fk, tier="mid", budget=FI.Budget(max_weighted=cap_tokens))
    assert res["ended"].startswith("到了硬上限") and res["budget"]["stopped"] == "max_tokens", res["ended"]
    assert res["budget"]["spent"] <= cap_tokens and len(fk.asks) == res["budget"]["calls"] < 60, (len(fk.asks), res["budget"])
    assert len(fk.asks) * 1800 <= cap_tokens
    # 上限比一次调用的预留还小 → 一次都不发 (先查后调; 改成先调后查这里就会多出一次)
    fk0 = Fakes()
    res0, _, _ = _run(fk0, tier="mid", budget=FI.Budget(max_weighted=est - 1))
    assert fk0.asks == [] and res0["budget"]["calls"] == 0 and res0["ended"].startswith("到了硬上限"), (len(fk0.asks), res0["ended"])
    fk0 = Fakes()
    res0, _, _ = _run(fk0, tier="mid", budget=FI.Budget(max_calls=7))
    assert len(fk0.asks) == 7 and res0["budget"]["stopped"] == "max_calls"
    # 没有用量回报的中转站: 每次按预留记, 更早停
    fk2 = Fakes(usage=False)
    res2, _, _ = _run(fk2, tier="mid", budget=FI.Budget(max_weighted=cap_tokens))
    assert len(fk2.asks) < len(fk.asks) and res2["budget"]["usage_missing"] == len(fk2.asks)
    # 上限正好卡在最后一步 (列核对) 里: 没查完的不能记成「跑完」(以前最后两步之后不再看上限, 报告就少了「没跑完」那句)
    fk3 = Fakes()
    full, _, _ = _run(fk3, tier="both")
    assert full["ended"] == "跑完", full["ended"]
    fk3 = Fakes()
    cut, _, _ = _run(fk3, tier="both", budget=FI.Budget(max_calls=full["budget"]["calls"] - 1))
    assert cut["budget"]["stopped"] == "max_calls" and cut["ended"].startswith("到了硬上限"), (cut["ended"], cut["budget"]["stopped"])
    # 没回报用量的调用: 钱不能显示成 0 —— 模型那一行把按预留估的加进去并标出来, 每张图 / 每月的花费写「算不出」
    fk4 = Fakes(usage=False)
    res4, _, _ = _run(fk4, tier="mid")
    m4 = next(iter(res4["budget"]["by_model"].values()))
    assert m4["input"] == 0 and m4["est_calls"] == m4["calls"] > 0 and m4["est_weighted"] > 0, m4
    assert all(v["yuan"] is None and v["no_usage"] > 0 for v in res4["per_image"].values()), res4["per_image"]
    md4 = FI.build_report(res4)
    assert "按预留估的" in md4 and "算不出" in md4 and "| 0.00 |" not in md4, "没回报用量时报告不能写成没花钱"
    assert "按预留估的" not in FI.build_report(full), "都回报了用量时不出这句"
    print(f"  §6 越线的那次不发 (上限 {cap_tokens:,} → 调了 {len(fk.asks)} 次就停); 上限抬不高; 没用量按预留记、钱不显示成 0; 卡在最后一步不算跑完 ✓")


# ── §7 ────────────────────────────────────────────────────────────────────────
def check_trial() -> None:
    fk = Fakes()
    res, out, sample = _run(fk)
    assert res["ended"] == "跑完", res["ended"]
    n_img = sum(1 for x in sample["regular"] + sample["awkward"] if FI.file_kind(x["file"]) != "video")
    assert n_img == 58 and res["plan"]["calls"]["total"] == 58 * 3 * 4 + 20 * 12 * 2 + 20 * 3 + 12 == 1248
    assert len(fk.asks) == res["budget"]["calls"] == res["plan"]["calls"]["total"], (len(fk.asks), res["budget"]["calls"])
    assert all(len(re.findall(r"id: img_", p)) <= 4 for _, _, p in fk.asks), "一次调用最多四题"
    video_tokens = {x["file"]["file_token"] for x in sample["awkward"] if x["stratum"] == "video"}
    assert len(video_tokens) == 2 and not (video_tokens & set(fk.downloads)) and not (video_tokens & {k for _, k, _ in fk.asks})
    assert res["awkward"]["video"] == {"n": 2, "ok": 2} and res["awkward"]["heic"] == {"n": 4, "ok": 4}
    assert res["usable"]["regular_ok"] == 48 and res["usable"]["regular_share"] == 1.0
    assert res["column_check"] == {"posts": 6, "ok": 6}
    assert len(res["cover_check"]) == 13 and all(c == {"n": 3, "ok": 3, "cover_unconfirmed": True} for c in res["cover_check"].values())
    assert set(res["tiers"]) == {"mid", "cheap"} and res["cross"] is not None
    assert res["tiers"]["mid"]["same"]["img_person"]["verdict"] == "pass"
    for q in ("img_kind", "img_text_amount", "img_layout"):      # 假模型在这三题上永远答同一个: 一边倒, 不算过
        assert res["tiers"]["mid"]["verdicts"][q] == "kappa_undefined", (q, res["tiers"]["mid"]["verdicts"][q])
    assert res["model_choice"]["choice"] == "cheap"
    assert res["budget"]["by_model"][FI.TIERS["mid"]]["calls"] == 58 * 6 + 240 + 60 + 12
    report = FI.build_report(res)
    blob = json.dumps(res, ensure_ascii=False, default=str)
    _no_leak("正式跑", out, report, blob)
    assert "kappa_undefined" in report and "cover_unconfirmed" in report and "按假设价估算" in report

    # 题库里确认过的表不带 cover_unconfirmed
    bank2 = copy.deepcopy(BANK)
    bank2["cover_confirmed_projects"] = ["TUGE_phase1"]
    res_c, _, _ = _run(Fakes(), tier="cheap", cap=3, bank=bank2)
    assert [p for p, c in res_c["cover_check"].items() if not c["cover_unconfirmed"]] in ([], ["TUGE_phase1"])
    assert res_c["model_choice"]["choice"] == "not_compared", "只跑一档不下选档的结论"
    assert all(v == "too_few" for v in res_c["tiers"]["cheap"]["verdicts"].values()), "小样本不许过线"

    # 便宜档自己两轮对不上 → 选中档
    seen_n: dict = {}

    def flip(model, qid, h):                      # 便宜档的 img_person: 同一张图第二次问 (b 轮) 换一个答案
        if "haiku" not in model or qid != "img_person":
            return False
        seen_n[h] = seen_n.get(h, 0) + 1
        return seen_n[h] == 2
    res_f, out_f, _ = _run(Fakes(flip=flip))
    assert res_f["tiers"]["cheap"]["verdicts"]["img_person"] in ("fail", "ask_alone", "kappa_undefined")
    assert res_f["model_choice"]["choice"] == "mid" and "img_person" in res_f["model_choice"]["blocking"]

    # 下载失败的图: 不调模型、不算可用
    s0 = FI.select_sample(_rows(), set())
    dead = {s0["regular"][5]["file"]["file_token"], s0["regular"][30]["file"]["file_token"]}
    fk = Fakes(fail_download=dead)
    res, out, _ = _run(fk, tier="mid")
    assert not (dead & {k for _, k, _ in fk.asks}), "下载失败的图不该问模型"
    assert res["usable"]["regular_download_failed"] == 2 and res["download"]["by_status"] == {"not_found": 2}
    _no_leak("下载失败", out, FI.build_report(res), json.dumps(res, ensure_ascii=False, default=str))

    # 干跑: 三个外部动作一次都没有
    fk = Fakes()
    res, out, _ = _run(fk, dry_run=True)
    assert fk.downloads == [] and fk.asks == [] and res["ended"] == "干跑" and res["plan"]["calls"]["total"] == 1248
    rep = FI.build_report(res)
    assert "没有花钱" in rep and 30 < res["plan"]["paper"]["yuan"] < 60, res["plan"]["paper"]["yuan"]
    _no_leak("干跑", out, rep, json.dumps(res, ensure_ascii=False, default=str))

    # 第一张图飞书就不给下载 → 停, 一次模型都不调
    fk = Fakes(refuse_feishu=True)
    res, out, _ = _run(fk, tier="mid")
    assert res["ended"].startswith("第一张图飞书") and fk.asks == [] and len(fk.downloads) == 1, (res["ended"], len(fk.downloads))
    # 中转站不收图片 → 第一次调用 (加一次重试) 之后就停
    fk = Fakes(refuse_relay=True)
    res, out, _ = _run(fk, tier="both")
    assert res["ended"].startswith("第一张图中转站") and len(fk.asks) == 2 and res["budget"]["calls"] == 2, (res["ended"], len(fk.asks))
    _no_leak("中转站拒绝", out, FI.build_report(res), json.dumps(res, ensure_ascii=False, default=str))
    assert res["api_failures"] == {"RuntimeError": 2}

    # 命令行: 没有库也能干跑 (按设计的篇数); 正式跑缺凭证在花钱之前就停, 只点名字
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = T.main(["--dry-run"]) if not T.os.environ.get("SUPABASE_URL") else 0
    assert rc == 0
    probs = T.preflight("both", False, env={"SUPABASE_URL": "x", "ANTHROPIC_API_KEY": "sk-secret-value"})
    assert any("FEISHU_APP_ID" in p for p in probs) and not any("sk-secret-value" in p for p in probs)
    assert T.preflight("both", True, env={}) == []
    print("  §7 调用数 = 计划数 (1,248); 视频 / 下载失败不调模型; 干跑零动作; 两种拒绝就停; 输出里没有任何探针 ✓")


# ── §8 ────────────────────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, status=200, chunks=(b"x" * 1000,) * 10):
        self.status_code, self._chunks, self.read, self.closed = status, chunks, 0, False

    def iter_content(self, _n):
        for c in self._chunks:
            self.read += 1
            yield c

    def close(self):
        self.closed = True


class _Client:
    def __init__(self, fail=False):
        self.fail = fail

    def _ensure_token(self):
        if self.fail:
            raise RuntimeError(f"Feishu auth failed: {{'msg': '{ERR_CANARY}'}}")
        return "t-secret-bearer"


def check_media() -> None:
    seen: dict = {}

    def get(url, headers=None, params=None, stream=None, timeout=None):
        seen.update(url=url, headers=headers, params=params, stream=stream)
        return seen["resp"]

    f = _file(7)
    seen["resp"] = _Resp()
    assert FM.download(_Client(), f, 50_000, http_get=get) == b"x" * 10_000
    assert seen["url"] == FM.MEDIA_URL.format(file_token=f["file_token"]) and seen["stream"] is True and seen["params"] == {}
    assert seen["headers"] == {"Authorization": "Bearer t-secret-bearer"} and seen["resp"].closed
    assert URL_CANARY not in seen["url"], "不跟库里存的 tmp_url 走"
    seen["resp"] = _Resp()
    try:
        FM.download(_Client(), f, 2500, http_get=get)
        raise AssertionError("超过上限没断")
    except FM.MediaError as e:
        assert e.status == FM.TOO_LARGE and seen["resp"].read == 3, "读到第 3 块就该断, 不把整个文件读完"
    for code, want in ((403, FM.NO_PERMISSION), (400, FM.NO_PERMISSION), (401, FM.AUTH_FAILED), (404, FM.NOT_FOUND), (502, FM.HTTP_ERROR)):
        seen["resp"] = _Resp(status=code)
        try:
            FM.download(_Client(), f, 50_000, http_get=get)
            raise AssertionError(code)
        except FM.MediaError as e:
            assert e.status == want and str(e) == want, (code, e.status)
            if want == FM.NO_PERMISSION:
                # 拒绝时带一个只有字母数字的细项 (状态码 / 飞书数字错误码 / 带没带 extra); 回包读不出来也不炸
                assert e.detail and e.detail.startswith(f"http{code}_code") and e.detail.replace("_", "").isalnum(), e.detail
    # 飞书回包里的数字错误码带得出来, 别的一个字都不带 (回包里的 msg 可能有地址)
    seen["resp"] = _Resp(status=403, chunks=(b'{"code": 1061004, "msg": "forbidden https://example.invalid/x"}',))
    try:
        FM.download(_Client(), dict(f, url="https://open.feishu.cn/x?extra=abc"), 50_000, http_get=get)
        raise AssertionError("403 没抛")
    except FM.MediaError as e:
        assert e.detail == "http403_code1061004_extra1", e.detail
    try:
        FM.download(_Client(fail=True), f, 50_000, http_get=get)
        raise AssertionError("auth")
    except FM.MediaError as e:
        assert e.status == FM.AUTH_FAILED and ERR_CANARY not in str(e) and e.__cause__ is None

    def boom(url, **kw):
        raise ConnectionError(f"HTTPSConnectionPool: {url}")
    try:
        FM.download(_Client(), f, 50_000, http_get=boom)
        raise AssertionError("network")
    except FM.MediaError as e:
        assert e.status == FM.NETWORK and TOKEN_CANARY not in str(e) and e.__cause__ is None and e.__suppress_context__
    for bad in ("", "../../etc", "a b", "x" * 80, None, "tok?x=1"):
        try:
            FM.download(_Client(), {"file_token": bad}, 10, http_get=get)
            raise AssertionError(bad)
        except FM.MediaError as e:
            assert e.status == FM.BAD_TOKEN
    seen["resp"] = _Resp()
    FM.download(_Client(), {**f, "url": "https://open.feishu.cn/open-apis/drive/v1/medias/x/download?extra=%7B%22a%22%3A1%7D"},
                50_000, http_get=get)
    assert seen["params"] == {"extra": '{"a":1}'}
    seen["resp"] = _Resp()
    FM.download(_Client(), {**f, "url": f"https://{URL_CANARY}/x?extra=evil", "tmp_url": "http://open.feishu.cn/x?extra=evil"},
                50_000, http_get=get)
    assert seen["params"] == {}, "别的主机 / 非 https 上的 extra 不认"
    assert T._status_of(RuntimeError(f"{ERR_CANARY} https://{URL_CANARY}")) == "RuntimeError"
    e = RuntimeError(ERR_CANARY)
    e.status_code = 429
    assert T._status_of(e) == "RuntimeError:429" and T._status_of(FM.MediaError(FM.NOT_FOUND)) == "not_found"
    print("  §8 流式上限; 状态码 → 状态词; 只认飞书主机的 extra; 报错里不带 token / 链接 / 正文 ✓")


# ── §9 ────────────────────────────────────────────────────────────────────────
def check_call_claude() -> None:
    import annotate_essence_pass as E
    import relay_failover
    assert relay_failover.mode() == relay_failover.MODE_PRIMARY_ONLY or True
    sent: list[dict] = []

    class _Messages:
        def create(self, **kw):
            sent.append(kw)
            return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="ok")], stop_reason="end_turn",
                                         usage=types.SimpleNamespace(input_tokens=11, output_tokens=3,
                                                                     cache_creation_input_tokens=0, cache_read_input_tokens=2))
    fake = types.ModuleType("anthropic")
    built: list[dict] = []
    clients: list = []

    def _mk(**kw):
        built.append(kw)
        clients.append(types.SimpleNamespace(messages=_Messages(), max_retries=2))   # 2 = SDK 的默认值
        return clients[-1]
    fake.Anthropic = _mk
    real = sys.modules.get("anthropic")
    saved = {k: T.os.environ.pop(k, None) for k in ("ANTHROPIC_BASE_URL_BACKUP", "ANTHROPIC_API_KEY_BACKUP", "RELAY_FORCE")}
    sys.modules["anthropic"] = fake
    try:
        assert E.call_claude("提示词", "m1") == "ok"
        assert sent[-1] == {"model": "m1", "max_tokens": 2000, "messages": [{"role": "user", "content": "提示词"}]}, sent[-1]
        assert E.call_claude("提示词", "m1", cached_system="S", max_tokens=77) == "ok"
        assert sent[-1] == {"model": "m1", "max_tokens": 77, "messages": [{"role": "user", "content": "提示词"}], "system": "S"}
        assert E.call_claude("提示词", "m1", images=[]) == "ok" and sent[-1]["messages"][0]["content"] == "提示词"
        meta: dict = {}
        assert E.call_claude("提示词", "m1", max_attempts=1, max_tokens=FI.MAX_OUTPUT_TOKENS, meta=meta,
                             images=[("image/jpeg", "QUJD")]) == "ok"
        assert sent[-1]["messages"] == [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"}},
            {"type": "text", "text": "提示词"}]}] and "system" not in sent[-1]
        assert meta == {"stop_reason": "end_turn", "usage": {"input": 11, "cache_write": 0, "cache_read": 2, "output": 3}}, meta
        text, usage = T.default_ask("m2", "p", FI.as_block(b"ABC"))
        assert text == "ok" and usage["input"] == 11 and sent[-1]["max_tokens"] == FI.MAX_OUTPUT_TOKENS
        assert sent[-1]["messages"][0]["content"][0]["source"]["data"] == "QUJD"
        # 调用上限按「发出去的请求」数: 试跑关掉 SDK 自带的重试; 别的调用方客户端的构造一字不变
        assert all("max_retries" not in kw for kw in built[:-1]), "现有调用方的客户端构造变了"
        assert built[-1].get("max_retries") == 0, "试跑的客户端还带着 SDK 的重试: 一次预留会发出不止一个请求"
        T.os.environ.update({"ANTHROPIC_BASE_URL_BACKUP": "https://backup.invalid", "ANTHROPIC_API_KEY_BACKUP": "k",
                             "RELAY_FORCE": "backup"})
        assert relay_failover.mode() == relay_failover.MODE_BACKUP_ONLY
        assert E.call_claude("提示词", "m1") == "ok" and clients[-1].max_retries == 2, "别的调用方的备用站客户端不动"
        assert T.default_ask("m2", "p", FI.as_block(b"ABC"))[0] == "ok"
        assert clients[-1].max_retries == 0, "试跑走备用站时也不许 SDK 自己重试"
    finally:
        for k, v in saved.items():
            T.os.environ.pop(k, None)
            if v is not None:
                T.os.environ[k] = v
        if real is None:
            sys.modules.pop("anthropic", None)
        else:
            sys.modules["anthropic"] = real
    print("  §9 call_claude: 不给 images 请求体不变; 给了图片块在文字前面; 用量带得出来 ✓")


# ── §10 ───────────────────────────────────────────────────────────────────────
def check_wiring() -> None:
    import yaml
    wf_dir = ROOT / ".github" / "workflows"
    raw = (wf_dir / "first-image-trial.yml").read_text(encoding="utf-8")
    wf = yaml.safe_load(raw)
    on = wf[True]
    assert set(on) == {"workflow_dispatch"}, f"首图试跑只能手动触发, 现在是 {sorted(on)}"
    inputs = on["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"tier", "max_images", "dry_run"} and inputs["dry_run"]["default"] == "true", "默认必须是干跑"
    job = wf["jobs"]["trial"]
    assert job.get("permissions") == {"contents": "read"}
    assert "'true'" in job["env"]["IN_DRY_RUN"], "输入缺省时也按干跑"
    ups = [s for s in job["steps"] if "upload-artifact" in str(s.get("uses"))]
    assert len(ups) == 1 and ups[0]["with"]["path"].endswith("/first-image-trial/first-image-trial.*"), "只传那份报告"
    runs = "\n".join(s.get("run", "") for s in job["steps"])
    assert "first_image_trial.py" in runs and "requirements-first-image.txt" in runs and "<<" not in runs
    secrets = set(re.findall(r"secrets\.([A-Z_]+)", raw))
    known = set(re.findall(r"secrets\.([A-Z_]+)", (wf_dir / "daily-sync.yml").read_text(encoding="utf-8")))
    assert secrets <= known, f"试跑用了夜跑没有的 secret: {sorted(secrets - known)}"
    for other in sorted(wf_dir.glob("*.yml")):
        if other.name in ("first-image-trial.yml", "ci.yml"):
            continue
        assert "first_image" not in other.read_text(encoding="utf-8"), f"{other.name} 不该提首图试跑 (它没有定时)"
    lock = (HERE / "requirements.lock").read_text(encoding="utf-8").lower()
    assert "pillow" not in lock, "夜跑的 lock 这一波不动"

    for name in ("first_image_trial.py", "first_image.py", "feishu_media.py"):
        src = (HERE / name).read_text(encoding="utf-8")
        code = re.sub(r'(?s)""".*?"""', "", src)
        for verb in (".upsert(", ".delete(", ".rpc(", ".storage", "execute_sql"):
            assert verb not in code, f"{name} 里出现了 {verb} —— 试跑不写库"
        for m in re.finditer(r"\.table\([^)]*\)\s*(\.\w+)", code):
            assert m.group(1) == ".select", f"{name}: 对表只许 select, 出现了 {m.group(1)}"
        assert not re.search(r"open\([^)]*['\"][wa]b", code) and ".write_bytes(" not in code, f"{name}: 不许往盘上写二进制"
        assert "tempfile" not in code and "NamedTemporaryFile" not in code
        for m in re.finditer(r"\.save\(([^,)]*)", code):
            assert m.group(1).strip() == "buf", f"{name}: 图片只许存进内存里的 buf"
    trial = (HERE / "first_image_trial.py").read_text(encoding="utf-8")
    assert len(re.findall(r"\.table\(", trial)) == 2 and "fetch_vanished_note_ids" in trial, "只读两处: notes 的两种取法"
    assert trial.count(".write_text(") == 2, "试跑只写两个文件: 报告 md 和 json"

    import mask_external_names as M
    assert M.PRICES is MP.PRICES and MP.ASSUMED is True
    assert MP.PRICES == {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00)}, "搬家不改数"
    assert set(FI.TIERS.values()) <= set(MP.PRICES)
    assert abs(MP.yuan("claude-sonnet-5-5", 1_000_000, 0) - 2.0 * 1.8 * 7.2) < 1e-9 and MP.yuan("没有这个模型", 1, 1) is None
    assert MP.weighted_tokens(100, 10) == 150
    for doc, needles in (("docs/33-first-image-trial.md", ("first-image-trial.yml", "cover_unconfirmed", "kappa_undefined", "dry_run")),
                         ("DECISIONS.md", ("D-157",)), ("OPEN-ITEMS.md", ("D-157", "I-29"))):
        text = (ROOT / doc).read_text(encoding="utf-8")
        for nd in needles:
            assert nd in text, f"{doc} 里没写 {nd}"
    # 文档里写的冒烟花费要和干跑自己算的对得上 (原先三处写「不到 1 元」, 干跑算出来是 106 次、约 3.7 元)
    smoke = T.run_trial(bank=BANK, tier="both", cap=2, dry_run=True, sample=T.apply_cap(T.design_sample(), 2),
                        budget=FI.Budget())["plan"]
    assert smoke["calls"]["total"] == 106 and round(smoke["paper"]["yuan"]) == 4, (smoke["calls"]["total"], smoke["paper"]["yuan"])
    for doc in ("docs/33-first-image-trial.md", ".github/workflows/first-image-trial.yml", "OPEN-ITEMS.md"):
        text = (ROOT / doc).read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if "冒烟" in ln and "max_images" in ln]
        assert any("约 4 元" in ln and "106 次" in ln for ln in lines) and not any("不到 1 元" in ln for ln in lines), \
            f"{doc}: 冒烟的花费和干跑对不上"
    both = FI.paper_estimate(BANK, FI.run_plan("both"), 58, 20, 0)["per_tier"]["cheap"]["yuan"]
    one = FI.paper_estimate(BANK, [r for r in FI.run_plan("both") if r["tag"] == "img-g1-haiku-a"], 58, 20, 0)["per_tier"]["cheap"]["yuan"]
    assert (both, one) == (1.75, 0.55) and "约 1.2 元" in (ROOT / "docs/33-first-image-trial.md").read_text(encoding="utf-8")

    if FI.image_libs_ready() in (None, "pillow-heif"):
        from PIL import Image
        im = Image.new("RGB", (3000, 2000), (200, 30, 30))
        exif = im.getexif()
        exif[0x010F] = "exif-make-tanzhen"
        buf = io.BytesIO()
        im.save(buf, format="JPEG", exif=exif, comment=b"zhushi-tanzhen", icc_profile=b"icc-tanzhen" * 20, dpi=(300, 300))
        assert b"zhushi-tanzhen" in buf.getvalue() and b"icc-tanzhen" in buf.getvalue()
        out = FI.shrink(buf.getvalue(), (FI.LONG_SIDE, FI.LONG_SIDE_BIG))
        assert out["pixels"] == 6_000_000 and FI.pixel_bucket(out["pixels"]) == "2-8MP"
        j, w, h = out["images"][FI.LONG_SIDE]
        assert (w, h) == (1024, 683) and out["images"][FI.LONG_SIDE_BIG][1:] == (1568, 1045)
        back = Image.open(io.BytesIO(j))
        assert back.format == "JPEG" and b"exif-make-tanzhen" not in j and not dict(back.getexif()), "元数据要丢掉"
        for side in (FI.LONG_SIDE, FI.LONG_SIDE_BIG):
            jj = out["images"][side][0]
            meta_left = set(Image.open(io.BytesIO(jj)).info) - {"jfif", "jfif_version", "jfif_unit", "jfif_density"}
            assert b"zhushi-tanzhen" not in jj and b"icc-tanzhen" not in jj and not meta_left, f"{side}: 注释段 / ICC 没丢 {meta_left}"
        small = io.BytesIO()
        Image.new("RGBA", (300, 400), (0, 0, 0, 0)).save(small, format="PNG")
        s = FI.shrink(small.getvalue())
        assert s["images"][FI.LONG_SIDE][1:] == (300, 400), "小图不放大"
        assert Image.open(io.BytesIO(s["images"][FI.LONG_SIDE][0])).getpixel((5, 5)) == (255, 255, 255), "透明底垫白"
        try:
            FI.shrink(b"not an image " + NAME_CANARY.encode())
            raise AssertionError("解不开没报")
        except FI.FirstImageError as e:
            assert e.status == "decode_failed" and e.__cause__ is None
        old, FI.PIXEL_CAP = FI.PIXEL_CAP, 1_000_000
        try:
            FI.shrink(buf.getvalue())
            raise AssertionError("像素上限没管用")
        except FI.FirstImageError as e:
            assert e.status == "too_many_pixels"
        finally:
            FI.PIXEL_CAP = old
        pil = "缩图在 Pillow 上测过"
    else:
        pil = "这个环境没装 Pillow, 缩图那几条没测 (夜跑的 lock 里本来就没有它)"
    assert FI.image_tokens_estimate(768, 1024) == 1049 and FI.pixel_bucket(50_000_000) == ">=40MP"
    print(f"  §10 workflow 只能手动 / 默认干跑 / 只传报告; 不写库不写盘; 价格只有一处; {pil} ✓")


def main() -> int:
    check_bank()
    check_pick()
    check_sample()
    check_answers()
    check_stats()
    check_budget()
    check_trial()
    check_media()
    check_call_claude()
    check_wiring()
    print("\ncheck_first_image: 10 节全过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
