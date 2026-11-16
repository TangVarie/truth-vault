#!/usr/bin/env python3
"""每晚首图步骤的守卫 (D-158, docs/34-first-image-pass.md)。全是合成数据; 不连库、不联网、不调模型、不碰飞书。
库那一半 (迁移、三个函数、两张视图) 在 ci.yml 的 sql job: scripts/check_first_image_pg.py (真 Postgres)。

  §1  题库 fi-v0.2: 没有 img_colour; 13 题 (11 道模型题 + 2 道代码题); 七个调用组, 先问 A_kind; 四道单独问的题各占一组;
      往外给的题只能是试跑里过线的闭集题; status 不许写 validated; fi-v0.1 那份文件一个字没动
  §2  钱: 每晚 ≤ 约 1 元、一次性 ≤ 约 2 元 (按价格表); 上限只能调低; 涨价上限跟着降、降价抬不过写死的数;
      只许便宜档 —— TIERS["cheap"] 被指到贵的模型上、或有人改了 Pass 里的模型名, 一个请求都不发; 没有换模型的参数;
      一次预留对一个真发出去的请求: default_ask 只试一次、SDK 不重试、只走主中转站 (配了备用站又没定成 primary → 一个请求都不发)
  §3  走一遍 (假库 / 假下载 / 假缩图 / 假模型): 是封面 7 次调用、不是封面 1 次且只写 img_kind 那一行; 视频和太大的文件不下载不问;
      下载失败、解不开、模型没答成、自相矛盾各记各的状态和算不算数; 先不做的项目就算库给了也不碰; 标题不进提示词;
      输出里没有 note_id、标题、封面上的字、文件名、file_token、链接、报错正文
  §4  上限在跑的时候真管用: 图片数到了就停; token 会越线的那一张图不开始; 到了时间上限不再开新图;
      一张图问到一半撞了上限 → 这一篇不写 (不会把缺了题的答案当成答完了)
  §5  不拦夜跑: 迁移没跑 → 零下载零调用、退出码 0; 缺环境变量、没装图片库 → 退出码 0, 只点名字; --strict 才非 0;
      真跑不了的时候 (缺钥匙 / 便宜档配置被拒) 名单照样同步进库; main 自己把 RELAY_FORCE 定成 primary
  §6  一篇帖卡不住整趟: 排第一的那篇飞书不给下载 / 模型答不成 → 记一笔不算数的失败, 后面的照做;
      开头连着两篇都这样 → 停 (两篇都记了); 写不进库 → 停, 不接着花钱
  §7  接线: workflow 有定时也能手动、手动默认干跑、首图那一步不会让 job 变红、没有上传步骤、没用夜跑没有的 secret、
      看门狗名单里有它; 步骤的代码只碰库里那三个函数、不往盘上写图片; 夜跑的 lock 没动; 迁移文件和文档里该有的字都在;
      定时一天只起一趟 (上限是按一趟算的); 不传备用中转站的钥匙; NEW_SINCE 和三个函数的参数钉住; 迁移和这里点名的脚本都真在
  §8  没答成的原因看得见 (11-16 首跑 32 张里 11 张没答成, 当时看不出为什么), 而且【认什么一个字没变】(D-159):
      ① FI.parse_answers 就是 11-16 首跑时 main 上的那个函数 (源码的 sha256 钉住); read_reply 的 parsed、Pass._call 拿到的结果,
        在固定的一批回包上 (对抗评审核实过的每一种 + 更早几轮评审的) 和守卫自己留的那份老读法逐字相同; stop_reason 不改它
      ② 细一层的词 (empty_reply / truncated / no_json / json_not_template / id_numbered / oov_* …) 和「假如放宽某一条读法
        会不会读出来」的词 (would_read) 各有代表性的例子钉住; 带问号 / 叉 / 没勾的框 / 话没说完的不数成「读得出」;
        分类器出了岔子只换一个词, 很长的怪回包不花时间
      ③ 摘要按写死的词分开数: 第一次调用没读出来的、整轮作废的 (哪条自检规则)、逐题无效的次数、回包撞没撞 max_tokens、
        「假如放宽」的那一行; 里面只有写死的词, 没有回包里的字; 没写进库的帖不进原因计数

反证 (改坏之后必须变红):
  ① 题库里把 img_colour 加回来 / 把单独问的题并回组里 / surfaced_questions 里放一道没验证的题        → §1
  ② NIGHTLY_MAX_WEIGHTED 调到 1,000,000 / PassBudget 不取 min                                       → §2
  ③ _call 里去掉 guard_model                                                                        → §2 (假模型数到了不该有的调用)
  ④ 不是封面还接着问后面六次 / 把别的答案也写进去                                                    → §3
  ⑤ summary 里带上 note_id 或标题                                                                   → §3
  ⑥ take_image 改成不查预留                                                                         → §4
  ⑦ main 在迁移没跑时返回非 0 / workflow 的首图步骤去掉 continue-on-error                             → §5 / §7
  ⑧ default_ask 的 max_attempts 改成 3 / 去掉 sdk_max_retries=0 / 去掉「只走主中转站」那一道             → §2
  ⑨ _process 里去掉「撞了上限这一篇不写」那两行                                                       → §4
  ⑩ 排第一的帖被拒时不记就停 (改回老写法)                                                            → §6
  ⑪ cron 改成每小时一趟 / NEW_SINCE 改早 / SupabaseStore 里 p_excluded 写死成 []                      → §7
  ⑫ 去掉 no_answer_why / invalid_q 的计数, 或 summary 不打这几行                                      → §8 ③
  ⑬ parse_answers 里动一个字 (去标点再比 / 认整行 / 换一种切 JSON 的办法 / 同一个键两遍就作废)          → §8 ① (sha256 + 固定回包)
  ⑭ read_reply 把「假如放宽读得出」的答案放进 parsed / 撞了上限就把 parsed 清掉                        → §8 ①
  ⑮ Pass._call 不用 parsed、改用分类器读出来的答案                                                    → §8 ① ③ (抄整行的帖变成答成了)
  ⑯ 换了样子的 JSON 里一个答案都读不出也数一个回包 / would_read 落到有效的题上 / 计数的键带回包里的字     → §8 ② ③
  ⑰ 先数 no_answer 的原因再写库 / 空回包排在撞上限前面 / _json_values 改回拿整个回包去解码 (平方级)      → §8 ② ③

跑法: cd scripts && python check_first_image_pass.py
"""
from __future__ import annotations

import base64
import contextlib
import copy
import hashlib
import inspect
import io
import json
import pathlib
import re
import sys
import time
import types

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

import feishu_media as FM  # noqa: E402
import first_image as FI  # noqa: E402
import first_image_pass as P  # noqa: E402
import model_prices as MP  # noqa: E402

BANK = P.load_bank()
CHEAP = "claude-haiku-5-5"

TITLE_CANARY = "标题探针甲乙丙丁"
TEXT_CANARY = "封面大字探针戊己庚"
NAME_CANARY = "wenjianming_tanzhen"
TOKEN_CANARY = "boxcnTOKENtanzhen"
URL_CANARY = "tanzhen-url.example"
NOTE_CANARY = "notetanzhen"
ERR_CANARY = "baocuo-zhengwen-tanzhen"
CANARIES = (TITLE_CANARY, TEXT_CANARY, NAME_CANARY, TOKEN_CANARY, URL_CANARY, NOTE_CANARY, ERR_CANARY)


def _file(tag: str, typ: str = "image/jpeg", size: int = 300_000, name: str | None = None) -> dict:
    token = f"{TOKEN_CANARY}{tag}"
    return {"file_token": token, "name": name or f"{NAME_CANARY}_{tag}.jpg", "size": size, "type": typ,
            "url": f"https://open.feishu.cn/open-apis/drive/v1/medias/{token}/download",
            "tmp_url": f"https://{URL_CANARY}/tmp/{tag}"}


def _cand(tag: str, project: str = "OKMAN_phase1", n_files: int = 1, col: str = "内容配图", **fkw) -> dict:
    f = _file(tag, **fkw)
    return {"note_id": f"{NOTE_CANARY}-{tag}", "project_id": project, "title": f"{TITLE_CANARY}{tag}",
            "source_column": col, "n_files": n_files, "first_file": f,
            "file_sha": hashlib.sha256(f["file_token"].encode()).hexdigest(), "is_card": False}


class MissingFn(Exception):
    """假的 PostgREST「没有这个函数」。"""
    code = "PGRST202"


class FakeStore:
    def __init__(self, cands=(), missing=False, write_fails=False):
        self.cands, self.missing, self.write_fails = list(cands), missing, write_fails
        self.synced: list[dict] = []
        self.asked: list[tuple] = []
        self.writes: list[tuple[dict, list]] = []

    def sync_bank(self, bank):
        if self.missing:
            raise MissingFn(f"{ERR_CANARY} https://{URL_CANARY}/rest/v1/rpc/sync_first_image_bank")
        self.synced.append({"confirmed": list(bank["cover_confirmed_projects"]), "excluded": list(bank["excluded_projects"]),
                            "surfaced": P.surfaced_questions(bank)})

    def candidates(self, bank, cards_only, limit):
        if self.missing:
            raise MissingFn(f"{ERR_CANARY} PGRST202")
        self.asked.append((cards_only, limit))
        return self.cands[:limit]

    def write(self, state, rows):
        if self.write_fails is True or self.write_fails == state["status"]:   # True = 都写不进; 一个状态词 = 只有它写不进
            raise RuntimeError(f"500 {ERR_CANARY} https://{URL_CANARY}/rest/v1/rpc/write_first_image_result")
        self.writes.append((state, rows))
        return "final" if state["outcome"] == "final" else "retry"


class Fakes:
    """假下载 / 假缩图 / 假模型。假图片的字节就是它的 file_token; 假模型看 token 里的记号决定怎么答。"""

    def __init__(self, usage=True, refuse_feishu=False, refuse_relay=False):
        self.downloads: list[str] = []
        self.asks: list[tuple] = []
        self.usage, self.refuse_feishu, self.refuse_relay = usage, refuse_feishu, refuse_relay

    def download(self, f):
        self.downloads.append(f["file_token"])
        if self.refuse_feishu:
            raise FM.MediaError(FM.NO_PERMISSION, "http403_code99991672_extra0")
        if FI.file_kind(f) == "video":
            raise AssertionError("视频不该被下载")
        for mark, st in (("GONE", FM.NOT_FOUND), ("NET", FM.NETWORK), ("HUGE", FM.TOO_LARGE), ("DENY", FM.NO_PERMISSION)):
            if mark in f["file_token"]:
                raise FM.MediaError(st)
        return f["file_token"].encode()

    def shrink(self, data, sides, decode="auto"):
        if b"BROKEN" in data:
            raise FI.FirstImageError("decode_failed")
        return {"pixels": 3_000_000, "images": {s: (data, 768, 1024) for s in sides}}

    def ask(self, model, prompt, block):
        key = base64.b64decode(block[1]).decode()
        self.asks.append((model, key, prompt))
        if self.refuse_relay or "RELAYERR" in key:
            raise RuntimeError(f"400 {ERR_CANARY} https://{URL_CANARY}/v1/messages")
        qids = re.findall(r"id: (img_[a-z_]+)", prompt)
        idx = FI.question_index(BANK)
        ans = []
        for qid in qids:
            q = idx[qid]
            if qid == "img_kind":
                v = "后台或数据截图" if "NOTCOVER" in key else ("不在闭集里的词" if "NOKIND" in key else "封面")
            elif qid == "img_text_amount":
                v = "没有字" if "CONTRA" in key else "一句大字"
            elif qid == "img_main_text":
                v = f"{TEXT_CANARY}3天见效"
            elif qid == "img_text_kind":
                v = "结果或结论"
            elif qid == "img_layout":
                v = "不在闭集里的词" if "OOV" in key else "一张照片"
            else:
                v = FI.option_values(q)[0]
            ans.append({"id": qid, "answer": v})
        usage = {"input": 1500, "cache_write": 0, "cache_read": 0, "output": 60} if self.usage else None
        return json.dumps({"answers": ans}, ensure_ascii=False), usage


def _run(store, fk, *, mode="nightly", bank=None, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        res = P.run_pass(bank=bank or BANK, store=store, mode=mode, download=fk.download, shrinker=fk.shrink,
                         ask=fk.ask, **kw)
        print(P.summary(res))
    return res, buf.getvalue()


def _no_leak(what: str, *texts: str) -> None:
    for t in texts:
        for c in CANARIES:
            assert c not in t, f"{what}: 输出里出现了 {c!r}"


# ── §1 ────────────────────────────────────────────────────────────────────────
def check_bank() -> None:
    assert P.validate_bank(BANK) == [], P.validate_bank(BANK)
    idx = FI.question_index(BANK)
    assert "img_colour" not in idx and len(BANK["questions"]) == 13
    assert len(FI.model_question_ids(BANK)) == 11 and FI.code_question_ids(BANK) == ["img_text_matches_title", "img_text_has_number"]
    assert BANK["bank_version"] == "fi-v0.2" and BANK["status"] == "draft" and BANK["run_tag_prefix"] == "img-"
    assert BANK["cover_confirmed_projects"] == [] and BANK["excluded_projects"] == ["RIO_phase1", "TXQ_phase1", "WTG_phase1"]
    for p in BANK["excluded_projects"]:
        assert (ROOT / "mappings" / f"{p}.yaml").is_file(), f"{p} 不是 mappings/ 里的项目名"
    units = P.call_units(BANK)
    assert [len(u) for u in units] == [2, 2, 3, 1, 1, 1, 1] and units[0] == ["img_kind", "img_text_amount"]
    assert BANK["ask_alone"] == ["img_main_text", "img_text_kind", "img_decoration", "img_brand_readable"]
    assert sorted(q["id"] for q in BANK["questions"] if q["trial"] == "pass_ask_alone") == sorted(
        BANK["ask_alone"] + ["img_text_has_number"]), "试跑里「要单独问」的五道 (第五道是代码从 img_main_text 算的)"
    assert sorted(q["id"] for q in BANK["questions"] if q["trial"] == "pass") == ["img_layout", "img_person", "img_product"]
    assert sorted(P.surfaced_questions(BANK)) == sorted(
        q["id"] for q in BANK["questions"] if q["trial"] in P.SURFACE_TRIALS and q["type"] != "text"), "往外给的就是过线的七道闭集题"
    assert "img_main_text" not in P.surfaced_questions(BANK) and "img_kind" not in P.surfaced_questions(BANK)

    # 和 fi-v0.1 比: 留下的题问法、选项、版本一个字没动
    old = FI.load_bank()
    assert FI.validate_bank(old) == [] and old["bank_version"] == "fi-v0.1" and len(old["questions"]) == 14
    oidx = FI.question_index(old)
    for qid, q in idx.items():
        for key in ("ask", "options", "type", "version", "max_chars"):
            assert q.get(key) == oidx[qid].get(key), f"{qid}.{key} 和 fi-v0.1 不一样"
    raw01 = (ROOT / "prompts" / "first_image_questions_v0_1.yaml").read_bytes()
    assert hashlib.sha256(raw01).hexdigest() == "34959ef29036d59f5e7b20f337f345785efd39c70b7eb6229169ceba88380786", "fi-v0.1 那份文件不许改"

    def bad(mut, needle):
        b = copy.deepcopy(BANK)
        mut(b)
        errs = P.validate_bank(b)
        assert any(needle in e for e in errs), (needle, errs)

    bad(lambda b: b["questions"].append(dict(oidx["img_colour"], trial="pass")), "img_colour")
    bad(lambda b: b.__setitem__("status", "validated"), "validated")
    bad(lambda b: (b["call_groups"]["A_kind"].append("img_text_kind"), b["call_groups"].pop("S_text_kind")), "单独占一个调用组")
    bad(lambda b: b["surfaced_questions"].append("img_text_matches_title"), "surfaced_questions")
    bad(lambda b: b["surfaced_questions"].append("img_main_text"), "surfaced_questions")
    bad(lambda b: b["cover_confirmed_projects"].append("RIO_phase1"), "既在")
    bad(lambda b: b.__setitem__("cover_confirmed_projects", None), "cover_confirmed_projects")
    bad(lambda b: b["call_groups"]["C_content"].extend(["img_layout", "img_finish"]), "最多 4 题")

    def reorder(b):
        g = b["call_groups"]
        b["call_groups"] = {"B_composition": g["B_composition"], **{k: v for k, v in g.items() if k != "B_composition"}}
    bad(reorder, "第一个调用组")
    for u in units:
        prompt = FI.build_prompt(BANK, u)
        for word in ("爆", "趴", "点赞", "tier", TITLE_CANARY):
            assert word not in prompt, f"提示词里出现了 {word!r}"
    print("  §1 题库 fi-v0.2: 13 题 / 七个调用组 / 四道单独问 / 没有 img_colour / 往外给七道; fi-v0.1 没动 ✓")


# ── §2 ────────────────────────────────────────────────────────────────────────
def check_money() -> None:
    assert P.cheap_model() == CHEAP == FI.TIERS["cheap"]
    n, c = P.caps("nightly"), P.caps("cards")
    assert (n["weighted"], n["images"]) == (750_000, 40) and (c["weighted"], c["images"]) == (1_500_000, 60)
    assert 0.9 < MP.yuan_of_weighted(CHEAP, n["weighted"]) <= 1.0, "每晚的 token 上限按价格表不超过 1 元"
    assert 1.8 < MP.yuan_of_weighted(CHEAP, c["weighted"]) <= 2.0, "一次性的 token 上限按价格表不超过 2 元"
    b = P.PassBudget("nightly", 7, max_weighted=10 ** 12, max_images=10 ** 6)
    assert (b.max_weighted, b.max_images, b.max_calls) == (750_000, 40, 280), "上限只能调低"
    b = P.PassBudget("nightly", 7, max_weighted=1000, max_images=3)
    assert (b.max_weighted, b.max_images, b.max_calls) == (1000, 3, 21)
    b = P.PassBudget("cards", 7)
    assert (b.max_weighted, b.max_images, b.max_calls) == (1_500_000, 60, 420)
    # 一张图预留多少 (每次调用: 图片按纸面公式 2 倍 + 提示词 + 输出满打满算): 没花一分钱时也至少放得进 10 张
    est = sum(FI.call_estimate(FI.build_prompt(BANK, u), [(FI.LONG_SIDE, FI.LONG_SIDE)]) for u in P.call_units(BANK))
    assert 60_000 < est < 90_000 and n["weighted"] // est >= 9, est

    old = dict(MP.PRICES)
    try:
        MP.PRICES[CHEAP] = (0.30, 1.50)                      # 涨到 3 倍: 上限跟着降到三分之一
        up = P.caps("nightly")["weighted"]
        assert up < 300_000 and MP.yuan_of_weighted(CHEAP, up) <= 1.0, up
        MP.PRICES[CHEAP] = (0.01, 0.05)                      # 降价: 抬不过写死的数
        assert P.caps("nightly")["weighted"] == 750_000
        MP.PRICES[CHEAP] = (5.00, 25.00)                     # 便宜档不再是最便宜的 → 拒绝
        try:
            P.caps("nightly")
            raise AssertionError("便宜档比别的模型贵了还放行")
        except P.PassConfigError:
            pass
        MP.PRICES.clear()
        MP.PRICES.update(old)
        del MP.PRICES[CHEAP]                                  # 价格表里没有它 → 拒绝
        try:
            P.cheap_model()
            raise AssertionError("价格表里没有便宜档还放行")
        except P.PassConfigError:
            pass
    finally:
        MP.PRICES.clear()
        MP.PRICES.update(old)

    # TIERS["cheap"] 被指到中档上 → 整趟拒绝, 一次下载、一次调用都没有
    fk, store = Fakes(), FakeStore([_cand("a1")])
    old_tier = FI.TIERS["cheap"]
    try:
        FI.TIERS["cheap"] = FI.TIERS["mid"]
        try:
            _run(store, fk)
            raise AssertionError("换成中档还跑了")
        except P.PassConfigError:
            pass
    finally:
        FI.TIERS["cheap"] = old_tier
    assert fk.asks == [] and fk.downloads == [] and store.writes == []
    # 有人直接改了 Pass 里的模型名 → 发请求之前被拦
    fk = Fakes()
    p = P.Pass(bank=BANK, store=FakeStore(), budget=P.PassBudget("nightly", 7), download=fk.download, shrinker=fk.shrink, ask=fk.ask)
    p.model = FI.TIERS["mid"]
    try:
        p._process(_cand("a2"))
        raise AssertionError("改了模型名还发了请求")
    except P.PassConfigError:
        pass
    assert fk.asks == [], "不是便宜档, 一个请求都不许发"
    try:
        P.default_ask(FI.TIERS["mid"], "x", ("image/jpeg", ""))
        raise AssertionError("default_ask 放行了中档")
    except P.PassConfigError:
        pass
    check_one_request_per_reserve()
    src = (HERE / "first_image_pass.py").read_text(encoding="utf-8")
    code = re.sub(r'(?s)""".*?"""', "", src)
    assert "--model" not in code and "--tier" not in code and not re.search(r"environ[^\n]*MODEL", code), "不许有换模型的口子"
    assert code.count("self.ask(") == 1 and code.count("call_claude(") == 1 and 'TIERS["mid"]' not in code and "sonnet" not in code.lower()
    assert code.index("guard_model(self.model)") < code.index("self.ask("), "先核模型再发"
    print(f"  §2 每晚 ≤ {MP.yuan_of_weighted(CHEAP, n['weighted']):.2f} 元 / 一次性 ≤ {MP.yuan_of_weighted(CHEAP, c['weighted']):.2f} 元 (价格表); "
          "上限只能调低; 涨价跟着降; 不是便宜档一个请求都不发 ✓")


def check_one_request_per_reserve() -> None:
    """一次 Budget.reserve 只许对一个真发出去的请求。假的 anthropic SDK 数请求。"""
    import relay_failover
    sent: list[tuple] = []
    built: list[dict] = []

    class APITimeoutError(Exception):
        pass

    class _Messages:
        def __init__(self, kw, behave):
            self.kw, self.behave = kw, behave

        def create(self, **kw):
            sent.append(("backup" if "backup" in str(self.kw.get("base_url")) else "primary", kw["model"], kw["max_tokens"]))
            if self.behave["fail"]:
                raise APITimeoutError("timeout")
            return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="ok")], stop_reason="end_turn",
                                         usage=types.SimpleNamespace(input_tokens=1500, output_tokens=60,
                                                                     cache_creation_input_tokens=0, cache_read_input_tokens=0))
    behave = {"fail": False}
    fake = types.ModuleType("anthropic")
    fake.APITimeoutError = APITimeoutError

    def _mk(**kw):
        built.append(kw)
        return types.SimpleNamespace(messages=_Messages(kw, behave), max_retries=kw.get("max_retries", 2), auth_token=None)
    fake.Anthropic = _mk
    real = sys.modules.get("anthropic")
    names = ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_BASE_URL_BACKUP", "ANTHROPIC_API_KEY_BACKUP",
             "ANTHROPIC_API_KEY_BACKUP_HAIKU", "RELAY_FORCE")
    saved = {k: P.os.environ.pop(k, None) for k in names}
    sys.modules["anthropic"] = fake
    block = FI.as_block(b"ABC")
    try:
        P.os.environ.update({"ANTHROPIC_API_KEY": "k", "ANTHROPIC_BASE_URL": "https://primary.invalid"})
        # 没配备用站: 成功 → 恰好一个请求, 客户端不带 SDK 的重试, 用量带得出来
        text, usage, stop = P.default_ask(CHEAP, "p", block)
        assert stop == "end_turn", "stop_reason 要带出来 (只带写死的词), 不然看不出回包是不是撞了 max_tokens"
        assert text == "ok" and usage["input"] == 1500 and sent == [("primary", CHEAP, FI.MAX_OUTPUT_TOKENS)], sent
        assert built[-1].get("max_retries") == 0, "SDK 自带的重试没关: 一次预留会发出不止一个请求"
        # 失败 (超时这种 call_claude 平时会重试的): 也只发一个请求就抛
        sent.clear()
        behave["fail"] = True
        try:
            P.default_ask(CHEAP, "p", block)
            raise AssertionError("假 SDK 抛了超时, default_ask 却没抛")
        except APITimeoutError:
            pass
        assert len(sent) == 1, f"一次预留发了 {len(sent)} 个请求 (max_attempts 要是 1)"
        # 配了备用站、没把 RELAY_FORCE 定成 primary: 那条路主站一个、备用站一个 → 这一步一个请求都不发
        sent.clear()
        P.os.environ.update({"ANTHROPIC_BASE_URL_BACKUP": "https://backup.invalid", "ANTHROPIC_API_KEY_BACKUP": "kb"})
        assert relay_failover.mode() == relay_failover.MODE_AUTO
        for force in (None, "backup"):
            P.os.environ.pop("RELAY_FORCE", None)
            if force:
                P.os.environ["RELAY_FORCE"] = force
            try:
                P.default_ask(CHEAP, "p", block)
                raise AssertionError("配了备用站还放行: 一次预留可能发出两个请求")
            except P.PassConfigError:
                pass
        assert sent == [], sent
        # 定成 primary (main 开头就这么定): 配着备用站也只打主站一次
        P.os.environ["RELAY_FORCE"] = "primary"
        try:
            P.default_ask(CHEAP, "p", block)
        except APITimeoutError:
            pass
        assert sent == [("primary", CHEAP, FI.MAX_OUTPUT_TOKENS)], sent
    finally:
        for k, v in saved.items():
            P.os.environ.pop(k, None)
            if v is not None:
                P.os.environ[k] = v
        if real is None:
            sys.modules.pop("anthropic", None)
        else:
            sys.modules["anthropic"] = real
    # 配置不对不是「这张图模型没答成」: 整趟停, 不往帖子头上记失败, 也不接着发
    fk, store = Fakes(), FakeStore()

    def refuse(model, prompt, blk):
        fk.asks.append((model, "x", prompt))
        raise P.PassConfigError("配置不对")
    p = P.Pass(bank=BANK, store=store, budget=P.PassBudget("nightly", 7), download=fk.download, shrinker=fk.shrink, ask=refuse)
    try:
        p._process(_cand("cfg1"))
        raise AssertionError("配置错误被当成了模型失败")
    except P.PassConfigError:
        pass
    assert len(fk.asks) == 1 and store.writes == []


# ── §3 ────────────────────────────────────────────────────────────────────────
def check_pass() -> None:
    cands = [
        _cand("ok1"),                                            # 单图, 是封面
        _cand("ok2", n_files=3, col="笔记配图"),                   # 多图: 照答, 但 cover_unconfirmed
        _cand("NOTCOVER1"),
        _cand("vid1", typ="video/mp4", name=f"{NAME_CANARY}.mp4"),
        _cand("big1", size=FI.MAX_INPUT_BYTES + 1),
        _cand("GONE1"), _cand("NET1"), _cand("HUGE1"), _cand("BROKEN1"),
        _cand("NOKIND1"), _cand("CONTRA1"), _cand("OOV1"),
        _cand("rio1", project="RIO_phase1"),                     # 先不做的项目: 库不该给, 给了也不碰
        _cand("heic1", typ="", name=f"{NAME_CANARY}.HEIC"),
    ]
    fk, store = Fakes(), FakeStore(cands)
    res, out = _run(store, fk, workers=3)
    assert res["ended"] == "done", res
    by = {s["note_id"].split("-", 1)[1]: (s, rows) for s, rows in store.writes}
    assert set(by) == {c["note_id"].split("-", 1)[1] for c in cands} - {"rio1"}, sorted(by)
    calls = {}
    for _m, key, prompt in fk.asks:
        calls.setdefault(key.replace(TOKEN_CANARY, ""), []).append(re.findall(r"id: (img_[a-z_]+)", prompt))
    assert all(m == CHEAP for m, _k, _p in fk.asks), "只许便宜档"
    assert all(len(q) <= 4 for qs in calls.values() for q in qs)

    s, rows = by["ok1"]
    assert (s["status"], s["outcome"], s["model"], s["width"], s["height"]) == ("answered", "final", CHEAP, 768, 1024)
    assert s["file_sha"] == hashlib.sha256(f"{TOKEN_CANARY}ok1".encode()).hexdigest() and "file_token" not in json.dumps(s)
    assert len(calls["ok1"]) == 7 and calls["ok1"][0] == ["img_kind", "img_text_amount"], "是封面: 七次调用, 先问 A_kind"
    assert sorted(len(q) for q in calls["ok1"]) == [1, 1, 1, 1, 2, 2, 3]
    assert len(rows) == 13 and {r["run_tag"] for r in rows} == {"img-primary"} and {r["bank_version"] for r in rows} == {"fi-v0.2"}
    got = {r["question_id"]: r for r in rows}
    assert got["img_kind"]["answer"] == "封面" and got["img_layout"]["answer"] == "一张照片"
    assert got["img_text_has_number"]["answer"] == "有" and got["img_text_has_number"]["extractor"] == "code:fi"
    assert got["img_text_matches_title"]["answer"] == "不一样" and got["img_layout"]["extractor"] == f"llm:{CHEAP}"
    assert all(set(r) == {"subject_type", "subject_id", "question_id", "question_version", "bank_version", "bank_sha256",
                          "extractor", "run_tag", "answer", "invalid_reason"} for r in rows)
    assert by["ok2"][0]["status"] == "answered" and by["ok2"][0]["n_files"] == 3 and by["ok2"][0]["source_column"] == "笔记配图"
    assert res["flags"] == {"usable": 3, "cover_unconfirmed": 1}, res["flags"]      # ok1 / OOV1 / heic1 可用; ok2 多图没确认

    s, rows = by["NOTCOVER1"]
    assert (s["status"], s["outcome"]) == ("not_a_cover", "final") and len(calls["NOTCOVER1"]) == 1, "不是封面: 只问了第一组"
    assert [(r["question_id"], r["answer"]) for r in rows] == [("img_kind", "后台或数据截图")], "不是封面: 只写 img_kind 那一行"

    tok = lambda t: f"{TOKEN_CANARY}{t}"  # noqa: E731
    assert tok("vid1") not in fk.downloads and "vid1" not in calls and by["vid1"][0]["status"] == "first_is_video"
    assert by["vid1"][0]["model"] is None and by["vid1"][1] == []
    assert tok("big1") not in fk.downloads and by["big1"][0]["status"] == "too_large"
    assert (by["GONE1"][0]["status"], by["GONE1"][0]["outcome"]) == ("download_failed", "counted")
    assert (by["NET1"][0]["status"], by["NET1"][0]["outcome"]) == ("download_failed", "infra"), "网络问题不算数"
    assert (by["HUGE1"][0]["status"], by["HUGE1"][0]["outcome"]) == ("too_large", "final")
    assert (by["BROKEN1"][0]["status"], by["BROKEN1"][0]["outcome"]) == ("decode_failed", "final")
    for t in ("GONE1", "NET1", "HUGE1", "BROKEN1"):
        assert t not in calls and by[t][1] == [], f"{t}: 没拿到图不该问模型、不该写答案"
    assert (by["NOKIND1"][0]["status"], by["NOKIND1"][0]["outcome"]) == ("no_answer", "counted") and len(calls["NOKIND1"]) == 1
    assert (by["CONTRA1"][0]["status"], by["CONTRA1"][0]["outcome"]) == ("no_answer", "counted") and by["CONTRA1"][1] == [], \
        "自相矛盾 (没有字却抄出了字): 整轮作废, 一行都不写"
    s, rows = by["OOV1"]
    oov = {r["question_id"]: r for r in rows}["img_layout"]
    assert s["status"] == "answered" and oov["answer"] is None and oov["invalid_reason"] == "out_of_vocab", "闭集外记无效, 不修补"
    assert tok("rio1") not in fk.downloads and "rio1" not in calls, "先不做的项目不下载、不问"
    assert by["heic1"][0]["file_kind"] == "empty_type" and by["heic1"][0]["status"] == "answered"

    assert res["no_answer_why"] == {"first_call:oov_other": 1, "round:no_text_but_transcribed:transcribed_text": 1}, res["no_answer_why"]
    assert res["invalid_by_question"] == {"img_kind:oov_other": 1, "img_layout:oov_other": 1}, res["invalid_by_question"]
    assert res["reply"] == {}, res["reply"]
    assert res["status"] == {"answered": 4, "not_a_cover": 1, "first_is_video": 1, "too_large": 2, "decode_failed": 1,
                             "download_failed": 2, "no_answer": 2}, res["status"]
    assert res["budget"]["calls"] == len(fk.asks) == 7 * 5 + 1 + 1 == 37 and res["budget"]["images"] == 11
    assert store.synced == [{"confirmed": [], "excluded": ["RIO_phase1", "TXQ_phase1", "WTG_phase1"],
                             "surfaced": P.surfaced_questions(BANK)}] and store.asked == [(False, 80)]
    for _m, _k, prompt in fk.asks:
        assert TITLE_CANARY not in prompt and NOTE_CANARY not in prompt, "标题和 note_id 不进提示词"
    _no_leak("走一遍", out, json.dumps(res, ensure_ascii=False, default=str))
    assert "按假设价估算" in out and "answered=4" in out and "not_a_cover=1" in out

    # mode=cards: 只问库要经验卡的帖, 上限是一次性的那一组
    fk, store = Fakes(), FakeStore([_cand("c1")])
    res, _ = _run(store, fk, mode="cards")
    assert store.asked == [(True, 120)] and res["caps"]["weighted"] == 1_500_000 and res["status"] == {"answered": 1}
    # 确认过的项目: 多图也算可用
    bank2 = copy.deepcopy(BANK)
    bank2["cover_confirmed_projects"] = ["OKMAN_phase1"]
    res, _ = _run(FakeStore([_cand("m1", n_files=4)]), Fakes(), bank=bank2)
    assert res["flags"] == {"usable": 1}
    # 干跑: 同步名单 (不花钱; 停用期间改的名单靠它进库)、问库有几篇; 不下载、不问、不写结果
    fk, store = Fakes(), FakeStore(cands)
    res, out = _run(store, fk, dry_run=True)
    assert res["ended"] == "dry_run" and res["candidates"] == len(cands)
    assert len(store.synced) == 1 and store.synced[0]["excluded"] == BANK["excluded_projects"], "干跑也要同步名单"
    assert store.writes == [] and fk.downloads == [] and fk.asks == []
    _no_leak("干跑", out)
    print("  §3 是封面 7 次调用 / 不是封面 1 次且只写 img_kind; 视频、太大不下载; 各种失败各记各的; 先不做的项目不碰; 输出里没有探针 ✓")


# ── §4 ────────────────────────────────────────────────────────────────────────
def check_caps() -> None:
    many = [_cand(f"n{i:03d}") for i in range(100)]
    fk, store = Fakes(), FakeStore(many)
    res, out = _run(store, fk)
    assert res["ended"] == "cap_max_images" and res["budget"]["images"] == 40 == len(store.writes), res["ended"]
    assert len(fk.asks) == 280 == res["budget"]["calls"] and res["budget"]["spent"] == 280 * 1800
    assert res["budget"]["spent"] <= res["caps"]["weighted"] and store.asked == [(False, 80)]
    assert MP.yuan_of_weighted(CHEAP, res["budget"]["spent"]) < 1.0
    fk, store = Fakes(), FakeStore(many)
    res, _ = _run(store, fk, max_images=3)
    assert res["ended"] == "cap_max_images" and len(store.writes) == 3 and len(fk.asks) == 21
    # token: 这一张图全部调用的预留放不进去 → 这张图不开始 (不下载、不问)
    est = sum(FI.call_estimate(FI.build_prompt(BANK, u), [(FI.LONG_SIDE, FI.LONG_SIDE)]) for u in P.call_units(BANK))
    fk, store = Fakes(), FakeStore(many)
    res, _ = _run(store, fk, max_weighted=est + 7 * 1800 - 1)
    assert res["ended"] == "cap_max_tokens" and len(store.writes) == 1 and len(fk.downloads) == 1 and len(fk.asks) == 7, \
        (res["ended"], len(store.writes), len(fk.asks))
    assert res["budget"]["spent"] == 7 * 1800
    fk, store = Fakes(), FakeStore(many)
    res, _ = _run(store, fk, max_weighted=est - 1)
    assert res["ended"] == "cap_max_tokens" and fk.downloads == [] and fk.asks == [] and store.writes == []
    # 中转站不回报用量: 每次按预留记, 更早停, 但写进去的都是完整的
    fk, store = Fakes(usage=False), FakeStore(many)
    res, _ = _run(store, fk)
    assert res["ended"] == "cap_max_tokens" and 0 < len(store.writes) < 40 and res["budget"]["usage_missing"] == len(fk.asks)
    assert res["budget"]["spent"] <= res["caps"]["weighted"] and all(s["status"] == "answered" for s, _ in store.writes)
    # 一张图问到一半撞了 token 上限 (中转站回报的用量比预留大得多): 这一篇不写 —— 写了就是缺着题的「答完了」, 以后不会再问
    class Greedy(Fakes):
        def ask(self, model, prompt, block):
            text, usage = super().ask(model, prompt, block)
            if "GREEDY" in base64.b64decode(block[1]).decode() and "img_layout" in prompt:
                usage = dict(usage, input=900_000)
            return text, usage
    fk, store = Greedy(), FakeStore([_cand("g1"), _cand("GREEDY1"), _cand("g2")])
    res, _ = _run(store, fk, workers=1)
    done = [s["note_id"].split("-", 1)[1] for s, _rows in store.writes]
    assert res["ended"] == "cap_max_tokens" and done == ["g1"], f"撞了上限的那一篇不该写: {res['ended']} {done}"
    assert sum(1 for _m, k, _p in fk.asks if "GREEDY" in k) == 2, "撞线之后这张图剩下的调用一个都不发"
    # 时间上限: 不再开新图
    ticks = iter(range(1000))
    fk, store = Fakes(), FakeStore(many)
    res, _ = _run(store, fk, deadline=2.5, clock=lambda: next(ticks))
    assert res["ended"] == "time_limit" and 0 < len(store.writes) < 5
    print("  §4 图片数 / token / 时间三道上限在跑的时候都管用; 放不进预留的那张图不开始 ✓")


# ── §5 ────────────────────────────────────────────────────────────────────────
def check_never_blocks() -> None:
    fk, store = Fakes(), FakeStore([_cand("x1")], missing=True)
    res, out = _run(store, fk)
    assert res["ended"] == "migration_missing" and fk.downloads == [] and fk.asks == [] and store.writes == []
    assert "notes_v1_28_first_image.sql" in out and "没花钱" in out
    _no_leak("迁移没跑", out, json.dumps(res, ensure_ascii=False, default=str))

    class Down(FakeStore):
        def sync_bank(self, bank):
            raise ConnectionError(f"{ERR_CANARY} {URL_CANARY}")
    res, out = _run(Down(), Fakes())
    assert res["ended"] == "db_unavailable"
    _no_leak("库连不上", out, json.dumps(res, ensure_ascii=False, default=str))

    def main_out(argv, env):
        buf = io.StringIO()
        old = dict(P.os.environ)
        try:
            for k in P.REQUIRED_ENV:
                P.os.environ.pop(k, None)
            P.os.environ.update(env)
            with contextlib.redirect_stdout(buf):
                rc = P.main(argv)
        finally:
            P.os.environ.clear()
            P.os.environ.update(old)
        return rc, buf.getvalue()

    rc, out = main_out([], {"SUPABASE_URL": "https://x.example", "ANTHROPIC_API_KEY": "sk-secret-value"})
    assert rc == 0 and "FEISHU_APP_ID" in out and "sk-secret-value" not in out and "没花钱" in out, (rc, out)
    rc, out = main_out(["--strict"], {})
    assert rc == 2 and "SUPABASE_URL" in out
    rc, out = main_out(["--dry-run"], {})
    assert rc == 0 and "750,000" in out and CHEAP in out, out
    rc, out = main_out(["--max-images", "-1"], {})
    assert rc == 0 and "参数不对" in out
    probs = P.preflight(False, env={k: "x" for k in P.REQUIRED_ENV})
    assert probs == [] or all("没装" in p for p in probs), probs
    # 配齐了、库里没有那三个函数: main 也是 0
    old_get, old_dl, old_libs = None, P.default_downloader, FI.image_libs_ready
    import _common
    old_get = _common.get_supabase_client
    try:
        _common.get_supabase_client = lambda: None
        P.default_downloader = lambda: Fakes().download
        FI.image_libs_ready = lambda: None
        old_store = P.SupabaseStore
        P.SupabaseStore = lambda sb: FakeStore(missing=True)
        rc, out = main_out([], {k: "x" for k in P.REQUIRED_ENV})
        assert rc == 0 and "migration_missing" in out, (rc, out)
        rc, out = main_out(["--strict"], {k: "x" for k in P.REQUIRED_ENV})
        assert rc == 3
        _no_leak("main 迁移没跑", out)
        # 真跑不了的时候名单照样同步: 缺模型的钥匙 / 便宜档配置被拒 / 干跑。不同步的话这段时间里新列为「先不做」的项目
        # 在读的那一面还是能用的。main 开头把 RELAY_FORCE 定成 primary (备用站那条路一次调用发两个请求)。
        stores: list = []
        seen_force: list = []

        def mk_store(sb):
            seen_force.append(P.os.environ.get("RELAY_FORCE"))
            stores.append(FakeStore())
            return stores[-1]
        P.SupabaseStore = mk_store
        db = {"SUPABASE_URL": "https://x.example", "SUPABASE_SERVICE_ROLE_KEY": "x"}
        rc, out = main_out([], dict(db, RELAY_FORCE="backup"))
        assert rc == 0 and "ANTHROPIC_API_KEY" in out and "名单已同步进库" in out and len(stores) == 1, (rc, out)
        assert stores[0].synced and stores[0].synced[0]["excluded"] == BANK["excluded_projects"] and stores[0].writes == []
        assert seen_force == ["primary"], seen_force
        old_tier = FI.TIERS["cheap"]
        try:
            FI.TIERS["cheap"] = FI.TIERS["mid"]
            rc, out = main_out([], {k: "x" for k in P.REQUIRED_ENV})
        finally:
            FI.TIERS["cheap"] = old_tier
        assert rc == 0 and "名单已同步进库" in out and len(stores) == 2 and len(stores[1].synced) == 1 and stores[1].asked == [], (rc, out)
        rc, out = main_out(["--dry-run"], db)
        assert rc == 0 and len(stores) == 3 and len(stores[2].synced) == 1 and "dry_run" in out, (rc, out)
        rc, out = main_out([], {"ANTHROPIC_API_KEY": "x"})
        assert rc == 0 and "名单没同步" in out and len(stores) == 3, "没配库就不连库"
    finally:
        _common.get_supabase_client, P.default_downloader, FI.image_libs_ready = old_get, old_dl, old_libs
        P.SupabaseStore = old_store
    print("  §5 迁移没跑 / 库连不上 / 缺环境变量: 零下载零调用, 退出码 0, 只点名字; --strict 才非 0 ✓")


# ── §6 ────────────────────────────────────────────────────────────────────────
def check_stops() -> None:
    many = [_cand(f"s{i:02d}") for i in range(10)]

    def by_tag(store):
        return {s["note_id"].split("-", 1)[1]: (s["status"], s["outcome"], rows) for s, rows in store.writes}

    # 飞书谁都不给下载 (凭证 / 权限): 开头连着两篇被拒才停; 两篇各记一笔不算数的失败, 不调模型
    fk, store = Fakes(refuse_feishu=True), FakeStore(many)
    res, out = _run(store, fk)
    assert res["ended"] == "feishu_refused" and len(fk.downloads) == 2 and fk.asks == [], res
    assert [(s["status"], s["outcome"], rows) for s, rows in store.writes] == [("download_failed", "infra", [])] * 2, store.writes
    assert res["detail"] == {"download:no_permission": 2}
    _no_leak("飞书拒绝", out, json.dumps(res, ensure_ascii=False, default=str))
    # 只有排第一的那一篇飞书不给 (单个文件的 400 / 403): 记它一笔, 后面的照做 —— 不记的话它每晚都排第一, 整趟永远卡住
    fk, store = Fakes(), FakeStore([_cand("DENY1")] + many[:5])
    res, out = _run(store, fk)
    st = by_tag(store)
    assert res["ended"] == "done" and st["DENY1"][:2] == ("download_failed", "infra") and len(store.writes) == 6, (res["ended"], st)
    assert sum(1 for v in st.values() if v[0] == "answered") == 5 and len(fk.asks) == 35
    # 这一趟已经有图下载成了之后再碰到不给下载的: 是那个文件的事, 算数的失败 (满 3 次不再试)
    fk, store = Fakes(), FakeStore([many[0], _cand("DENY2"), _cand("DENY3"), many[1]])
    res, _ = _run(store, fk)
    st = by_tag(store)
    assert res["ended"] == "done" and st["DENY2"][:2] == st["DENY3"][:2] == ("download_failed", "counted") and st["s01"][0] == "answered", st
    # 中转站什么图都答不成: 开头连着两张都这样才停; 两篇各记一笔不算数的失败, 一共四次调用
    fk, store = Fakes(refuse_relay=True), FakeStore(many)
    res, out = _run(store, fk)
    assert res["ended"] == "relay_refused" and len(fk.asks) == 4, (res["ended"], len(fk.asks))
    assert [(s["status"], s["outcome"], rows) for s, rows in store.writes] == [("model_failed", "infra", [])] * 2, store.writes
    assert res["detail"] == {"model:RuntimeError": 4} and res["budget"]["usage_missing"] == 4
    _no_leak("中转站拒绝", out, json.dumps(res, ensure_ascii=False, default=str))
    # 只有排第一的那张图中转站答不成 (比如被网关的过滤拦了): 记它一笔, 后面的照做
    fk, store = Fakes(), FakeStore([_cand("RELAYERR0")] + many[:5])
    res, out = _run(store, fk)
    st = by_tag(store)
    assert res["ended"] == "done" and st["RELAYERR0"] == ("model_failed", "infra", []) and len(store.writes) == 6, (res["ended"], st)
    assert sum(1 for v in st.values() if v[0] == "answered") == 5 and len(fk.asks) == 2 + 35
    # 中途某一张图模型出错: 这一张记 model_failed (不算数), 别的照做; 写进去的答案里没有它
    mid = [_cand("g1"), _cand("RELAYERR1"), _cand("g2")]
    fk, store = Fakes(), FakeStore(mid)
    res, out = _run(store, fk)
    st = {s["note_id"].split("-", 1)[1]: (s["status"], s["outcome"], rows) for s, rows in store.writes}
    assert st["RELAYERR1"][:2] == ("model_failed", "infra") and st["RELAYERR1"][2] == [] and st["g2"][0] == "answered", st
    assert res["ended"] == "done"
    # 连着失败 6 次就停
    bad = [_cand("g0")] + [_cand(f"RELAYERR{i}") for i in range(2, 9)]
    fk, store = Fakes(), FakeStore(bad)
    res, _ = _run(store, fk)
    assert res["ended"] == "relay_failing" and sum(1 for _m, k, _p in fk.asks if "RELAYERR" in k) == 6, res["ended"]
    assert sum(1 for s, _ in store.writes if s["status"] == "model_failed") == 2, "判了「中转站坏了」之后的那一篇不记"
    # 写不进库: 停, 不接着花钱
    fk, store = Fakes(), FakeStore(many, write_fails=True)
    res, out = _run(store, fk)
    assert res["ended"] == "write_failed" and len(fk.asks) == 7 and len(fk.downloads) == 1
    _no_leak("写不进库", out, json.dumps(res, ensure_ascii=False, default=str))
    print("  §6 排第一的帖被拒 → 记一笔、后面照做; 开头连着两篇被拒 → 停; 中途出错只记那一张; 连着失败、写不进库 → 停 ✓")


# ── §7 ────────────────────────────────────────────────────────────────────────
def check_wiring() -> None:
    import yaml
    wf_dir = ROOT / ".github" / "workflows"
    raw = (wf_dir / "first-image-sync.yml").read_text(encoding="utf-8")
    wf = yaml.safe_load(raw)
    on = wf[True]
    assert set(on) == {"workflow_dispatch", "schedule"} and len(on["schedule"]) == 1
    assert re.fullmatch(r"[0-5]?\d (?:[01]?\d|2[0-3]) \* \* \*", on["schedule"][0]["cron"]), \
        "定时只许一天一趟 (固定的分和时): 钱的上限是按一趟算的, 一天多起几趟就是几份上限"
    inputs = on["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"mode", "dry_run", "max_images"} and inputs["dry_run"]["default"] == "true", "手动触发默认干跑"
    assert len(wf["jobs"]) == 1
    job = wf["jobs"]["first-image"]
    assert job.get("permissions") == {"contents": "read"} and job["timeout-minutes"] <= 90
    assert "'schedule'" in job["env"]["IN_DRY_RUN"] and "'true'" in job["env"]["IN_DRY_RUN"]
    assert not any("upload-artifact" in str(s.get("uses")) for s in job["steps"]), "图片和报告都不进 artifact"
    run_steps = [s for s in job["steps"] if s.get("run")]
    assert run_steps and all(s.get("continue-on-error") is True for s in run_steps), "每个 run 步骤都不许让 job 变红"
    assert all(isinstance(s.get("timeout-minutes"), int) and s["timeout-minutes"] < job["timeout-minutes"] for s in run_steps), \
        "每个 run 步骤自己的时限要比 job 的短 (撞 job 的时限是 cancelled, continue-on-error 管不了)"
    assert sum(s["timeout-minutes"] for s in run_steps) + 5 <= job["timeout-minutes"] and P.DEFAULT_MAX_MINUTES < 55
    runs = "\n".join(s["run"] for s in run_steps)
    assert "first_image_pass.py" in runs and "requirements-first-image.txt" in runs and "<<" not in runs
    assert "--strict" not in runs and "exit 1" not in runs and "2>&1" not in runs
    secrets = set(re.findall(r"secrets\.([A-Z_]+)", raw))
    known = set(re.findall(r"secrets\.([A-Z_]+)", (wf_dir / "daily-sync.yml").read_text(encoding="utf-8")))
    assert secrets <= known, f"首图步骤用了夜跑没有的 secret: {sorted(secrets - known)}"
    assert set(re.findall(r"vars\.([A-Z_]+)", raw)) == set() and not any("BACKUP" in x for x in secrets), \
        "首图步骤不传备用中转站的钥匙 (那条路一次调用发两个请求)"
    assert job["env"]["RELAY_FORCE"] == "primary" and not any("BACKUP" in k for k in job["env"])
    for other in ("daily-sync.yml", "features-sync.yml"):
        assert "first_image" not in (wf_dir / other).read_text(encoding="utf-8"), f"{other} 里不该有首图步骤"
    wd = (wf_dir / "sync-watchdog.yml").read_text(encoding="utf-8")
    assert '("first-image-sync.yml",' in wd, "看门狗名单里要有它"
    assert 'MAY_BE_OFF = {"first-image-sync.yml"}' in wd, "文档写的停法是停用 workflow: 看门狗要认得, 而且只对首图这一趟认 (check_sync_watchdog.py ⑬)"
    assert "pillow" not in (HERE / "requirements.lock").read_text(encoding="utf-8").lower(), "夜跑的 lock 不动"

    src = (HERE / "first_image_pass.py").read_text(encoding="utf-8")
    code = re.sub(r'(?s)""".*?"""', "", src)
    assert set(re.findall(r'_rpc\("(\w+)"', code)) == {"sync_first_image_bank", "first_image_candidates", "write_first_image_result"}
    for verb in (".table(", ".upsert(", ".delete(", ".storage", "execute_sql", "tempfile", ".write_bytes(",
                 ".write_text(", "NamedTemporaryFile"):
        assert verb not in code, f"first_image_pass.py 里出现了 {verb}"
    assert not re.search(r"open\(", code), "这一步不开任何文件"
    assert code.count(".rpc(") == 1

    # 「新帖从哪天算」和三个函数的参数: 生产走的是 SupabaseStore (PG 夹具用的是它自己的 psql 版), 在这里钉
    assert P.NEW_SINCE == "2026-11-16 00:00:00", "NEW_SINCE 改早 = 回头补老帖 (D-157 不许)"

    class _Sb:
        def __init__(self):
            self.calls: list[tuple] = []

        def schema(self, name):
            self._schema = name
            return self

        def rpc(self, fn, args):
            self.calls.append((self._schema, fn, args))
            return self

        def execute(self):
            return types.SimpleNamespace(data="final" if self.calls[-1][1] == "write_first_image_result" else [])
    sb = _Sb()
    st = P.SupabaseStore(sb)
    bank2 = dict(BANK, cover_confirmed_projects=["OKMAN_phase1"])
    st.sync_bank(bank2)
    assert st.candidates(bank2, True, 7) == [] and st.candidates(bank2, False, 80) == []
    assert st.write({"note_id": "n"}, [{"q": 1}]) == "final"
    assert sb.calls == [
        ("truth_vault", "sync_first_image_bank", {"p_bank_version": "fi-v0.2", "p_bank_sha256": BANK["_sha256"],
                                                  "p_confirmed": ["OKMAN_phase1"], "p_excluded": BANK["excluded_projects"],
                                                  "p_surfaced": P.surfaced_questions(BANK)}),
        ("truth_vault", "first_image_candidates", {"p_bank_version": "fi-v0.2", "p_new_since": "2026-11-16 00:00:00",
                                                   "p_excluded": BANK["excluded_projects"], "p_cards_only": True, "p_limit": 7}),
        ("truth_vault", "first_image_candidates", {"p_bank_version": "fi-v0.2", "p_new_since": "2026-11-16 00:00:00",
                                                   "p_excluded": BANK["excluded_projects"], "p_cards_only": False, "p_limit": 80}),
        ("truth_vault", "write_first_image_result", {"p_state": {"note_id": "n"}, "p_rows": [{"q": 1}]})], sb.calls

    sql = (ROOT / "schemas" / "notes_v1_28_first_image.sql").read_text(encoding="utf-8")
    for needle in ("CREATE TABLE IF NOT EXISTS truth_vault.note_first_image", "CREATE TABLE IF NOT EXISTS truth_vault.first_image_bank_state",
                   "CREATE OR REPLACE VIEW truth_vault.v_first_image_features", "CREATE OR REPLACE VIEW truth_vault.v_note_first_image_source",
                   "ENABLE ROW LEVEL SECURITY", "FROM PUBLIC, anon, authenticated", "'内容配图'), (2, '笔记配图'), (3, '图片')",
                   "run_tag = 'img-primary'"):
        assert needle in sql, f"迁移里没有 {needle}"
    assert sql.count("DROP ") == sql.count("--        DROP ") + sql.count("-- 回滚: DROP "), "迁移只做加法 (DROP 只出现在回滚说明里)"
    assert "ALTER TABLE truth_vault.note_feature_answers" not in sql and "file_token TEXT" not in sql
    # 迁移和这份守卫点名的脚本、文件都得真在 (照着头注去找夹具的人不能扑空)
    for text in (sql, (HERE / "check_first_image_pass.py").read_text(encoding="utf-8").split('"""')[1],
                 (HERE / "check_first_image_pg.py").read_text(encoding="utf-8").split('"""')[1]):
        for rel in set(re.findall(r"(?:scripts|schemas|prompts|docs)/[\w./-]+\.(?:py|sql|yaml|md)", text)):
            assert (ROOT / rel).is_file(), f"点名的 {rel} 不存在"
    # 自检 #87 (同一跑里行数不齐 = 半写) 不数首图的行: 不是封面的帖按规矩只存一行
    v87 = re.search(r"SELECT '87'.*?\$q\$(.*?)\$q\$", (HERE / "verify_supabase_state.sql").read_text(encoding="utf-8"), re.S)
    assert v87 and "run_tag NOT LIKE 'img-%'" in v87.group(1), "verify_supabase_state.sql #87 要把首图的行除外"
    assert list(FI.IMAGE_COLUMNS) == ["内容配图", "笔记配图", "图片"], "取列的顺序和迁移里那张视图是同一条"
    assert f"'{P.RUN_TAG}'" in sql and P.RUN_TAG.startswith(BANK["run_tag_prefix"]) and P.RUN_TAG != "primary"

    for doc, needles in (("docs/34-first-image-pass.md", ("notes_v1_28_first_image.sql", "v_first_image_features", "cover_unconfirmed",
                                                          "没有人对着图核过", "750,000", "1,500,000", "first-image-sync.yml",
                                                          "cover_confirmed_projects", "RIO")),
                         ("DECISIONS.md", ("D-158", "40/48", "0.87")), ("OPEN-ITEMS.md", ("D-158", "I-36", "I-37")),
                         ("CURRENT_STATE.md", ("D-158",)), ("scripts/README.md", ("notes_v1_28_first_image.sql",)),
                         ("docs/00-START-HERE.md", ("34-first-image-pass",))):
        text = (ROOT / doc).read_text(encoding="utf-8")
        for nd in needles:
            assert nd in text, f"{doc} 里没写 {nd}"
    print("  §7 workflow 定时 + 手动 (默认干跑)、不会变红、不传 artifact; 代码只碰三个函数、不开文件; 迁移只做加法; 文档齐 ✓")


# ── §8 ────────────────────────────────────────────────────────────────────────
KIND_LINE = "封面: 给读者看的图：照片、拼图、带字的图、文字卡片、聊天或备忘录样式的图都算"
SHOT_LINE = "后台或数据截图：创作者后台、数据统计页、已发布笔记页面的截图（带互动数字、导航栏、数据曲线这类界面）"
OLD_PARSER_SHA256 = "957a83bfbc5d4f2571d3bbd683c356760c2ddcbded39407a0cbf0ad34c7cf657"   # FI.parse_answers 的源码 (和 11-16 首跑时 main 上的一字不差)
G_KIND = ["img_kind", "img_text_amount"]


def _reply(items) -> str:
    return json.dumps({"answers": [{"id": i, "answer": a} for i, a in items]}, ensure_ascii=False)


def _old_parse(bank: dict, qids: list, text: str) -> dict:
    """守卫自己留的一份老读法 (11-16 首跑时 main 上的 parse_answers, 逻辑一字不差): 认什么只许和它一样。"""
    idx = {q["id"]: q for q in bank["questions"]}
    got: dict = {}
    try:
        s, e = text.index("{"), text.rindex("}")
        data = json.loads(text[s:e + 1])
        for a in data.get("answers") or []:
            if isinstance(a, dict) and isinstance(a.get("id"), str):
                got.setdefault(a["id"], a.get("answer"))
    except Exception:  # noqa: BLE001
        return {qid: (None, "parse_failed") for qid in qids}
    out: dict = {}
    for qid in qids:
        q = idx[qid]
        if qid not in got or not isinstance(got[qid], str):
            out[qid] = (None, "missing")
            continue
        val = got[qid].strip()
        if q["type"] == "choice":
            out[qid] = (val, None) if val in [str(o["value"]) for o in q["options"]] else (None, "out_of_vocab")
        else:
            out[qid] = (val, None) if len(val) <= int(q["max_chars"]) else (None, "text_too_long")
    return out


def review_corpus() -> list:
    """固定的一批回包 [(题号们, 回包, stop_reason)]: 11-16 对抗评审里核实过的每一种 (scratch 的 real.json 逐条抄进来的),
    加上更早几轮评审的 (否定、没勾的框、话没说完、同一个键两遍、断掉的数组、引号里的括号、断包)。全是合成的字。"""
    K, A, one = ["img_kind"], G_KIND, json.dumps({"id": "img_kind", "answer": "封面"}, ensure_ascii=False)
    ok = _reply([("img_kind", "封面")])
    two = json.dumps([{"id": "img_kind", "answer": "封面"}, {"id": "img_text_amount", "answer": "没有字"}], ensure_ascii=False)
    out: list = []

    def add(qids, text, *stops):
        for st in stops or (None, "end_turn"):
            out.append((qids, text, st))

    # 一个答案的各种写法 (模板 JSON 里)
    kind_answers = [
        "封面", " 封面 ", "封面。", "「封面」", "- 封面", " 封面​", '"封面"', "**封面**", "（封面）", "【封面】", "封面！", "封面，",
        KIND_LINE, SHOT_LINE, KIND_LINE.replace(": ", "："), "后台或数据截图", "看不清或空白",
        "!封面", "！封面", "! 封面", "!" + KIND_LINE, "！" + KIND_LINE, "「! " + KIND_LINE + "」",
        "封面。。。", "封面. . .", "封面 . .", "封面. .", "封面···", "封面、、、", "封面——", "封面｡｡｡", "封面。。", "封面,,,",
        "[ ] 封面", "- [ ] 封面", "( ) 封面", "（ ）封面", "[] 封面", "[ ]封面", "[-] 封面", "[x] 封面", "[X] 封面", "[✓] 封面",
        "☐ 封面", "☑ 封面", "封面 [ ]", "[ ] " + KIND_LINE,
        "封面: !给读者看的图：照片、拼图、带字的图、文字卡片、聊天或备忘录样式的图都算",
        "封面 . . . 给读者看的图：照片、拼图、带字的图、文字卡片、聊天或备忘录样式的图都算",
        "封面:(给读者看的图：照片、拼图、带字的图、文字卡片、聊天或备忘录样式的图都算。。。",
        "封面图", "封面: 给读者看的图", "是封面", "不是封面", "看不清", "数据截图", "cover", "别的东西", "",
        "封面？", "封面?", "封面 (?)", "❌封面", "封面❌", "封面 ✗", "封面×", "封面(×)", "≠封面", "~封面", "~~封面~~",
        "封面…", "封面...", "封面……", "封\n面", "封 面", "封̶面̶", "封面🙂", "✓封面", "封面/", "<封面>",
        KIND_LINE + "？", "❌" + KIND_LINE, "~~" + KIND_LINE + "~~", KIND_LINE + "…", KIND_LINE.replace("封面", "封̶面")]
    for v in kind_answers:
        add(A, _reply([("img_kind", v), ("img_text_amount", "没有字")]))
        add(K, json.dumps({"img_kind": v}, ensure_ascii=False))
    for v in (None, ["封面"], 1, True, {"v": "封面"}):
        add(A, json.dumps({"answers": [{"id": "img_kind", "answer": v}]}, ensure_ascii=False))
    for qid, vals in (("img_brand_readable", ("能", "能。", "能。。", "( ) 能", "不能", "能?")),
                      ("img_decoration", ("有", "有。。。", "🈶", "㊒", "没有", "有。")),
                      ("img_text_amount", ("没有字", "没有字。。。", "没有字？", "没有字。", "很多字")),
                      ("img_main_text", ("三天见效", " 三天见效 ", "字" * 40, "字" * 41, "", "[限时优惠", "满减}到手"))):
        for v in vals:
            add([qid], _reply([(qid, v)]))
            add([qid], json.dumps({qid: v}, ensure_ascii=False))
    # 换了样子的 JSON
    for text in (two, one, "[" + one + "]", "[" + one + ",]", "[" + one, "[" + one + ", {]",
                 '{"id":"img_kind","answer":"封面"}\n{"id":"img_text_amount","answer":"没有字"}',
                 json.dumps({"answers": {"img_kind": "封面"}}, ensure_ascii=False),
                 json.dumps({"img_kind": "封面", "img_text_amount": "没有字"}, ensure_ascii=False),
                 json.dumps({"img_kind": ["封面"]}, ensure_ascii=False),
                 json.dumps([{"id": "img_kind", "answer": "封面图"}, {"id": "img_text_amount", "answer": "很多字"}], ensure_ascii=False),
                 ok + " 说明: {备注}", '格式: {"answers":[{"id":"题号","answer":"答案"}]}\n' + ok, "{备注} " + one,
                 "```json\n" + ok + "\n```", "好的，答案如下：\n" + ok + "\n以上。", '说明 {"x": 1} 和 {备注}', "我看不了图片", "", "  \n",
                 '{"answers": 5, "img_kind": "封面"}', '{"answers": "img_kind"}', '{"answers": null}', "{}", "[]", "null",
                 '{"answers":[{"id":"img_kind","answer":"封面"},]}',
                 '{"answers":[{"id":"img_kind","answer":"封面"},{"id":"img_text_amount","answer":"没有字"}], 备注}',
                 _reply([("1", "封面"), ("2", "没有字")]), json.dumps({"answers": [{"id": 1, "answer": "封面"}]}),
                 _reply([("题号", "封面")]), _reply([("img_text_amount", "没有字")]),
                 "[" * 12000 + "]" * 12000, '{"a":' + "[" * 12000 + "]" * 12000 + "}", "{,}" * 2000, "[1,]\n" * 2000):
        add(A, text, None, "end_turn", "max_tokens", "length")
    # 同一道题两个答案 / 同一个键两遍 / 一段读不出来的 JSON 带着另一个答案 (real.json 2、3、7、8、9、15、18)
    for text in (
            _reply([("img_kind", "封面"), ("img_kind", "后台或数据截图")]), _reply([("img_kind", "别的"), ("img_kind", "封面")]),
            _reply([("img_kind", "别的"), ("img_kind", "其他")]), _reply([("img_kind", "别的"), ("img_kind", " 别的 ")]),
            _reply([("img_kind", "封面"), ("img_kind", "封面。")]), _reply([("img_kind", "封面"), ("img_kind", None)]),
            _reply([("img_kind", None), ("img_kind", "封面")]), _reply([("img_kind", "封面"), ("img_kind", ["封面"])]),
            '{"img_kind":"后台或数据截图"} ' + ok,
            "{'img_kind': '后台或数据截图'}\n" + '{"img_kind":"封面","img_text_amount":"没有字"}',
            '{"img_kind":"后台或数据截图",} {"img_kind":"封面"}', '{"img_kind":"后台或数据截图", } {"img_kind":"封面"}',
            '{"img_kind":"封面","img_kind":"后台或数据截图"} {"img_kind":"封面"}',
            '{"answers":{"img_kind":"封面"},"img_kind":"后台或数据截图"}', '{"id":"img_kind","answer":"封面","img_kind":"后台或数据截图"}',
            '{"img_kind":"封面","更正":{"img_kind":"后台或数据截图"}}', '{"img_kind":"封面","correction":{"img_kind":"后台或数据截图"}}',
            '[{"id":"img_kind","answer":"封面"},[{"id":"img_kind","answer":"后台或数据截图"}]]',
            '{"answers":[{"id":"img_kind","answer":"封面"}],"img_kind":"后台或数据截图"}',
            '{"answers": {"img_kind": "封面", "img_kind": "后台或数据截图"}}', '{"img_kind": "后台或数据截图", "img_kind": "封面"}',
            '{"id": "img_kind", "answer": "封面", "answer": "后台或数据截图"}',
            '{"answers":[{"id":"img_kind","answer":"封面"},{"id":"img_text_amount","answer":"没有字"}],"note":"a","note":"b"}',
            '{"answers":[{"id":"img_kind","answer":"封面","answer":"封面"}]}', '{"answers":[{"id":"img_kind","id":"img_kind","answer":"封面"}]}',
            '{"answers":[{"id":"img_kind","answer":"封面","why":"a"},{"id":"img_text_amount","answer":"没有字"}],"note":"x","note":"x"}',
            '{"answers":[{"id":"img_kind","answer":"封面"},{"id":"img_text_amount","answer":"没有字","why":"a","why":"b"}]}',
            '{"answers":[{"id":"img_kind","answer":"封面","answer":"封面"},{"id":"img_text_amount","answer":"一句大字"}]}',
            '{"answers":[{"id":"img_kind","answer":"封面"},{"id":"img_text_amount","answer":"没有字","answer":"一句大字"}]}',
            '{"answers":[{"id":"img_kind","answer":"封面"},{"id":"img_text_amount","answer":"一句大字"}],"meta":{"n":1,"n":1}}',
            '{"answers":[{"id":"img_kind","id":"img_kind","answer":"后台或数据截图"},{"id":"img_text_amount","answer":"一句大字"}]}',
            '答案不是 {"img_kind":"封面"}', "答案不是 " + ok, '{"img_kind":"封面"}'):
        add(A, text, None, "end_turn", "max_tokens", "model_context_window_exceeded", "length")
    add(["img_decoration"], '{"answers":[{"id":"img_decoration","answer":"有","answer":"有"}]}')
    # 断包 (real.json 4、10、11、16、19)
    for text in (
            '看起来像 6" 手机的截图 {"img_kind":"封面"} {"img_text_amount":"没有', '注: 5" 的图 {"img_kind":"封面"} {"img_text_amount":"一句',
            ok + '\n更正: {"answers":[{"id":"img_kind","answer":"后台', "[" + ok + ',{"answers":[{"id":"img_kind","answer":"后台或',
            '图上写着 5" 的屏幕。\n{"id":"img_kind","answer":"封面"}\n{"id":"img_text_amount","answer":"一句',
            '先看"标题\n{"id":"img_kind","answer":"封面"}\n{"id":"img_text_amount","answer":"没有字"}\n更正: {"id":"img_kind","answer":"后台或数据截',
            one + "\n", ok, ok[:40], two[:30],
            '{"answers":[{"id":"img_kind","answer":"封面"},{"id":"img_text_amount","answer":"一句'):
        add(A, text, None, "end_turn", "max_tokens")
    add(["img_layout", "img_finish"], '照片"}, {"id": "img_finish", "answer": "随手拍"}]}')
    add(K, _reply([("img_kind", "封面。。。")]))
    add(K, _reply([("img_kind", "[ ] 封面")]))
    # 题库里每道选择题的每个选项: 包了标点的、抄了整行的、换了样子的 JSON 里的 —— 单问这一题、和它那一次调用的别的题一起问, 两种都过
    # (后面几次调用的题也在里面: 只在某几道题、某一次调用上放宽的改法也过不了)
    idx = {q["id"]: q for q in BANK["questions"]}
    for unit in P.call_units(BANK):
        for qid in unit:
            q = idx[qid]
            if q["type"] != "choice":
                continue
            rest = [(o, str(idx[o]["options"][0]["value"]) if idx[o]["type"] == "choice" else "三天见效") for o in unit if o != qid]
            for o in q["options"]:
                v = str(o["value"])
                forms = [v, v + "。", "「" + v + "」", "**" + v + "**", "- " + v, "（" + v + "）。", v + "？", "[ ] " + v]
                if o.get("means"):
                    forms += [f"{v}: {o['means']}", f"{v}：{o['means']}", f"「{v}: {o['means']}」"]
                for f in forms:
                    add([qid], _reply([(qid, f)]))
                    add([qid], json.dumps({qid: f}, ensure_ascii=False))
                    add([qid], json.dumps([{"id": qid, "answer": f}], ensure_ascii=False))
                    if rest:
                        add(unit, _reply([(qid, f)] + rest))
                        add(unit, json.dumps(dict([(qid, f)] + rest), ensure_ascii=False))
    for text in ('{"id": "img_main_text", "answer": "[限时优惠"}', '[{"id": "img_main_text", "answer": "满减}到手"}]',
                 '{"img_main_text": "写着 \\"[\\" 的图"}', _reply([("img_main_text", "三天见效"), ("img_main_text", "七天见效")]),
                 _reply([("img_main_text", "三天见效"), ("img_main_text", "三天 见效！")])):
        add(["img_main_text"], text)
    return out


def check_reply_reading() -> None:
    g = G_KIND
    assert g == P.call_units(BANK)[0]

    # ① 认什么只许和老读法一样: parse_answers 的源码钉住; read_reply 的 parsed、Pass 拿到的 parsed, 在固定的一批回包上逐字相同
    src = inspect.getsource(FI.parse_answers)
    assert hashlib.sha256(src.encode("utf-8")).hexdigest() == OLD_PARSER_SHA256, "FI.parse_answers 被改了: 认什么不许动 (D-159)"
    assert "read_reply" not in src and "_shape_read" not in src and "match_option" not in src
    corpus = review_corpus()
    assert len(corpus) > 3000 and {st for _q, _t, st in corpus} >= {None, "end_turn", "max_tokens", "length"}, len(corpus)
    n_invalid = n_would = 0
    for qids, text, stop in corpus:
        want = _old_parse(BANK, qids, text)
        r = FI.read_reply(BANK, qids, text, stop)
        assert repr(r["parsed"]) == repr(want) == repr(FI.parse_answers(BANK, qids, text)), \
            f"认下来的和老读法不一样 (第 {corpus.index((qids, text, stop))} 条)"
        assert set(r) == {"parsed", "notes", "would_read"}
        bad = {q for q in qids if want[q][1] is not None}
        assert set(r["notes"]) == bad and set(r["notes"].values()) <= set(FI.NOTES), "每道无效的题有一个写死的词, 有效的题没有"
        assert set(r["would_read"]) <= bad and set(r["would_read"].values()) <= set(FI.WOULD_READ), "would_read 只落在无效的题上"
        n_invalid += len(bad)
        n_would += len(r["would_read"])

        class One(Fakes):                                  # Pass._call 拿到的也是老读法的结果 (stop_reason 不改它)
            def ask(self, model, prompt, block, _t=text, _s=stop):
                return _t, {"input": 10, "output": 5}, _s
        p = P.Pass(bank=BANK, store=None, budget=P.PassBudget("nightly", 7), download=None, shrinker=None, ask=One().ask)
        assert repr(p._call(qids, b"x", (1, 1))) == repr(want), "Pass._call 认下来的和老读法不一样"
    assert n_invalid > 3000 and 1000 < n_would < n_invalid, (n_invalid, n_would)
    # 每道选择题 (哪一次调用的都算) 在固定回包里都有「假如放宽就读得出」的答案 —— 上面已经逐条钉住它们照旧无效
    seen_would: dict = {}
    for qids, text, stop in corpus:
        for q, w in FI.read_reply(BANK, qids, text, stop)["would_read"].items():
            seen_would.setdefault(q, set()).add(w)
    for q in BANK["questions"]:
        if q["type"] != "choice":
            continue
        need = {FI.WOULD_PUNCT, FI.WOULD_LOOSE, FI.WOULD_LOOSE_PUNCT}
        if any(o.get("means") for o in q["options"]):
            need |= {FI.WOULD_LINE, FI.WOULD_LOOSE_LINE}
        assert seen_would.get(q["id"], set()) >= need, f"{q['id']}: 固定回包里缺一种「假如放宽」的样子"

    def kind(text, stop=None, qid="img_kind", qids=None):
        r = FI.read_reply(BANK, qids or g, text, stop)
        return r["parsed"][qid], r["notes"].get(qid), r["would_read"].get(qid)

    # 老读法认的还是认 (一字不差的选项、围栏、前后有闲话); 它不认的一个都没多认: 这几条是评审里漏进去过的
    ok = _reply([("img_kind", "封面")])
    for text in (_reply([("img_kind", "封面"), ("img_text_amount", "一句大字")]), "```json\n" + ok + "\n```", "好的：\n" + ok + "\n以上。",
                 _reply([("img_kind", " 封面 ")])):
        for stop in (None, "end_turn", "max_tokens", "length"):
            assert kind(text, stop) == (("封面", None), None, None), (text, stop)
    for v in ("封面。", "「封面」", "**封面**", KIND_LINE, "封面。。。", "[ ] 封面", "( ) 封面", "!封面", "封面？", "❌封面", "封面图", "🈶"):
        assert kind(_reply([("img_kind", v)]))[0] == (None, FI.INVALID_OOV), f"没有放宽: {v!r} 不是一字不差的选项"
    assert kind(_reply([("img_decoration", "🈶")]), qid="img_decoration", qids=["img_decoration"])[0] == (None, FI.INVALID_OOV)
    for text in ('{"img_kind":"封面"}', '[{"id":"img_kind","answer":"封面"}]', '{"answers":{"img_kind":"封面"}}', '答案不是 {"img_kind":"封面"}',
                 '{"answers":{"img_kind":"封面"},"img_kind":"后台或数据截图"}',
                 '看起来像 6" 手机的截图 {"img_kind":"封面"} {"img_text_amount":"没有'):
        assert kind(text)[0] == (None, FI.INVALID_MISSING), f"没有放宽: 不是模板的 JSON 里的答案不认: {text}"
    for text in ('{"img_kind":"后台或数据截图",} {"img_kind":"封面"}', "{'img_kind': '后台或数据截图'}\n" + '{"img_kind":"封面"}',
                 '[{"id":"img_kind","answer":"封面"},{"id":"img_text_amount","answer":"没有字"}]', "我看不了图片", ""):
        assert kind(text)[0] == (None, FI.INVALID_PARSE), text
    # 老读法本来就认的, 照旧认 (评审说的两处「倒退」): 同一个键两遍、同一题两个答案取第一个、撞了上限但 JSON 完整
    for text, want in (('{"answers":[{"id":"img_kind","answer":"封面","answer":"封面"}]}', "封面"),
                       ('{"answers":[{"id":"img_kind","answer":"封面"}],"note":"a","note":"b"}', "封面"),
                       ('{"answers":[{"id":"img_kind","answer":"封面"}],"meta":{"n":1,"n":1}}', "封面"),
                       (_reply([("img_kind", "封面"), ("img_kind", "后台或数据截图")]), "封面"),
                       (_reply([("img_kind", "后台或数据截图"), ("img_kind", "封面")]), "后台或数据截图"),
                       (ok + " 说明: {备注}", None), ('{"id":"img_kind","answer":"封面"}\n', None)):
        for stop in (None, "max_tokens"):
            got = kind(text, stop)[0]
            assert got[0] == want and got == _old_parse(BANK, g, text)["img_kind"], (text, stop, got)

    # ② 细一层的词和「假如放宽」的词 (只是计数用的词; 上面已经钉住了答案照旧无效)
    oov, miss, fail = FI.INVALID_OOV, FI.INVALID_MISSING, FI.INVALID_PARSE
    two = json.dumps([{"id": "img_kind", "answer": "封面"}, {"id": "img_text_amount", "answer": "没有字"}], ensure_ascii=False)
    for v, note, would in (
            ("封面。", FI.NOTE_OOV_WRAPPED, FI.WOULD_PUNCT), ("「封面」", FI.NOTE_OOV_WRAPPED, FI.WOULD_PUNCT),
            ("**封面**", FI.NOTE_OOV_WRAPPED, FI.WOULD_PUNCT), ("- 封面", FI.NOTE_OOV_WRAPPED, FI.WOULD_PUNCT),
            (KIND_LINE, FI.NOTE_OOV_LINE, FI.WOULD_LINE), (SHOT_LINE, FI.NOTE_OOV_LINE, FI.WOULD_LINE),
            (KIND_LINE.replace(": ", "："), FI.NOTE_OOV_LINE, FI.WOULD_LINE),
            ("封面图", FI.NOTE_OOV_PLUS, None), ("封面: 给读者看的图", FI.NOTE_OOV_PLUS, None), ("是封面", FI.NOTE_OOV_CONTAINS, None),
            ("看不清", FI.NOTE_OOV_PART, None), ("数据截图", FI.NOTE_OOV_PART, None), ("cover", FI.NOTE_OOV_OTHER, None),
            ("", FI.NOTE_OOV_OTHER, None),
            # 带着会改意思的记号的: 「假如放宽」也读不出 (不把打了问号、打了叉、没勾的框、话没说完的「封面」数成读得出)
            ("封面？", FI.NOTE_OOV_MARKED, None), ("❌封面", FI.NOTE_OOV_MARKED, None), ("~~封面~~", FI.NOTE_OOV_MARKED, None),
            ("封面…", FI.NOTE_OOV_MARKED, None), ("封 面", FI.NOTE_OOV_MARKED, None), ("!封面", FI.NOTE_OOV_MARKED, None),
            ("封面。。。", FI.NOTE_OOV_MARKED, None), ("封面. . .", FI.NOTE_OOV_MARKED, None), ("封面——", FI.NOTE_OOV_MARKED, None),
            ("[ ] 封面", FI.NOTE_OOV_MARKED, None), ("( ) 封面", FI.NOTE_OOV_MARKED, None), ("- [ ] 封面", FI.NOTE_OOV_MARKED, None),
            ("!" + KIND_LINE, FI.NOTE_OOV_PLUS, None), ("[ ] " + KIND_LINE, FI.NOTE_OOV_PLUS, None), (KIND_LINE + "？", FI.NOTE_OOV_PLUS, None)):
        assert kind(_reply([("img_kind", v)])) == ((None, oov), note, would), (v, kind(_reply([("img_kind", v)])))
    for text, stop, why, note, would in (
            ("", None, fail, FI.NOTE_EMPTY, None), ("  \n", "end_turn", fail, FI.NOTE_EMPTY, None),
            ("", "max_tokens", fail, FI.NOTE_TRUNCATED, None),          # 思考把上限用完、一个字都没回: 是撞上限, 不是 empty_reply
            ("", "refusal", fail, FI.NOTE_EMPTY, None), ("我看不了图片", "refusal", fail, FI.NOTE_STOP_OTHER, None),
            ("我看不了图片", "end_turn", fail, FI.NOTE_NO_JSON, None),
            (ok[:40], "max_tokens", fail, FI.NOTE_TRUNCATED, None), (ok[:40], None, fail, FI.NOTE_NO_JSON, None),
            (two, None, fail, FI.NOTE_NOT_TEMPLATE, FI.WOULD_LOOSE), (two, "max_tokens", fail, FI.NOTE_TRUNCATED, None),
            (two, "length", fail, FI.NOTE_STOP_OTHER, None),            # 不认识的停止原因: 也不数成读得出
            ('{"img_kind":"封面"}', None, miss, FI.NOTE_NOT_TEMPLATE, FI.WOULD_LOOSE),
            ('{"img_kind":"封面。"}', None, miss, FI.NOTE_NOT_TEMPLATE, FI.WOULD_LOOSE_PUNCT),
            (json.dumps({"img_kind": KIND_LINE}, ensure_ascii=False), None, miss, FI.NOTE_NOT_TEMPLATE, FI.WOULD_LOOSE_LINE),
            ('{"answers":{"img_kind":"封面"}}', "end_turn", miss, FI.NOTE_NOT_TEMPLATE, FI.WOULD_LOOSE),
            ('{"img_kind":"封面"}', "max_tokens", miss, FI.NOTE_TRUNCATED, None),
            ('{"img_kind": ["封面"]}', None, miss, FI.NOTE_NOT_TEXT, None),          # 不是字符串: 换了样子也读不出, 不数
            ('[{"id":"img_kind","answer":"封面图"},{"id":"img_text_amount","answer":"很多字"}]', None, fail, FI.NOTE_OOV_PLUS, None),
            ('{"img_kind":"后台或数据截图"} ' + ok, None, fail, FI.NOTE_CONFLICT, None),
            ('{"answers":[{"id":"img_kind","answer":"封面"},]}', None, fail, FI.NOTE_NO_JSON, None),
            ('{"answers":[{"id":"img_kind","answer":"封面"},{"id":"img_text_amount","answer":"没有字"}], 备注}', None, fail, FI.NOTE_NO_JSON, None),
            ('说明 {"x": 1} 和 {备注}', None, fail, FI.NOTE_NO_ANSWERS, None),
            (_reply([("1", "封面"), ("2", "没有字")]), None, miss, FI.NOTE_ID_NUMBERED, None),
            (json.dumps({"answers": [{"id": 1, "answer": "封面"}]}), None, miss, FI.NOTE_ID_NUMBERED, None),
            (_reply([("题号", "封面")]), None, miss, FI.NOTE_NO_ANSWERS, None),
            (_reply([("img_text_amount", "没有字")]), None, miss, FI.NOTE_ID_ABSENT, None),
            (json.dumps({"answers": [{"id": "img_kind", "answer": None}]}), None, miss, FI.NOTE_NOT_TEXT, None),
            (_reply([("img_kind", None), ("img_kind", "封面")]), None, miss, FI.NOTE_NOT_TEXT, None),
            (_reply([("img_kind", "别的"), ("img_kind", "封面")]), None, oov, FI.NOTE_CONFLICT, None),
            (_reply([("img_kind", "封面。"), ("img_kind", "后台或数据截图")]), None, oov, FI.NOTE_CONFLICT, None),
            ('{"answers":[{"id":"img_kind","answer":"封面。"}],"note":"a","note":"b"}', None, oov, FI.NOTE_DUP_KEY, None),
            ("x" * 20_001, None, fail, FI.NOTE_TOO_LONG, None),             # 长度上限写死在这里: 调大了这两条就红
            ("x" * 20_001, "max_tokens", fail, FI.NOTE_TRUNCATED, None),
            ("x" * 20_000, None, fail, FI.NOTE_NO_JSON, None)):
        assert kind(text, stop) == ((None, why), note, would), (text[:60], stop, kind(text, stop))
    assert FI.NOTE_MAX_CHARS == 20_000, "细看的回包长度上限不许悄悄调大"
    deep = kind("[" * 9000 + "]" * 9000)                       # 嵌得很深: 解码器受不受得了看 Python 版本, 哪种都只是一个词, 不抛
    assert deep[0] == (None, fail) and deep[1] in (FI.NOTE_NO_JSON, FI.NOTE_NO_ANSWERS) and deep[2] is None, deep
    gt = ["img_main_text"]
    rt = FI.read_reply(BANK, gt, _reply([("img_main_text", "字" * 41)]))
    assert rt["parsed"]["img_main_text"] == (None, FI.INVALID_TEXT_LONG) and rt["notes"] == {"img_main_text": FI.NOTE_TEXT_LONG}, rt
    rt = FI.read_reply(BANK, gt, '{"img_main_text": "三天见效"}')
    assert rt["parsed"]["img_main_text"] == (None, miss) and rt["would_read"] == {"img_main_text": FI.WOULD_LOOSE}, rt
    assert FI.stop_word("end_turn") == "end_turn" and FI.stop_word("max_tokens") == "max_tokens" and FI.stop_word(None) is None
    assert FI.stop_word(f"x {ERR_CANARY}") == "other" and FI.stop_word(["max_tokens"]) == "other", "stop_reason 只带写死的词"
    assert len(set(FI.NOTES)) == len(FI.NOTES) and all(re.fullmatch(r"[a-z_]+", w) for w in FI.NOTES + FI.WOULD_READ)
    # 「假如放宽」的分类器: 两份题库里每个选项的整行都数得成 (不然那一行的计数永远是 0, 看不出值不值得放宽)
    for bank in (BANK, FI.load_bank()):
        for q in bank["questions"]:
            for o in q.get("options") or [] if q["type"] == "choice" else []:
                assert FI.match_option(q, str(o["value"])) == (str(o["value"]), None)
                assert FI.match_option(q, f"「{o['value']}」。") == (str(o["value"]), FI.WOULD_PUNCT), q["id"]
                if o.get("means"):
                    assert FI.match_option(q, f"{o['value']}: {o['means']}") == (str(o["value"]), FI.WOULD_LINE), q["id"]
    # 分类器不许拖垮夜跑: 自己出了岔子只是换一个词; 很长的怪回包不花时间 (平方级的那种写法 0.9 MB 要三十几秒)
    real_shape = FI._shape_read
    try:
        FI._shape_read = lambda *a, **k: (_ for _ in ()).throw(RuntimeError(ERR_CANARY))
        r = FI.read_reply(BANK, g, "{'img_kind': '封面'}", "end_turn")
        assert r["parsed"]["img_kind"] == (None, fail) and r["notes"]["img_kind"] == FI.NOTE_UNCLASSIFIED and not r["would_read"], r
    finally:
        FI._shape_read = real_shape
    for hostile in ("{,}" * 300_000, "[1,]\n" * 100_000, '{"a":' * 200_000, '"' * 500_000 + "{}", "[" * 500_000 + "]" * 500_000):
        t0 = time.perf_counter()
        r = FI.read_reply(BANK, g, hostile, "end_turn")
        real_shape(BANK, g, hostile, "end_turn")           # 不靠长度上限: 分类器本身也得是线性的
        assert time.perf_counter() - t0 < 20, "很长的怪回包读了太久"
        assert repr(r["parsed"]) == repr(_old_parse(BANK, g, hostile)) and set(r["notes"].values()) <= set(FI.NOTES)
    # 一个答案里「开括号 + 一长串空格」: 没勾的框那条正则写成两段挨着的空白时是平方级的 (上限以内一条回包 1.6 秒, 6 万字十几秒)
    kq = FI.question_index(BANK)["img_kind"]
    for n in (19_900, 60_000):
        for v in ("[" + " " * n + "封面图", "封面图" + " " * (n // 2) + "(" * 200 + " " * (n // 2), "【" + " \t" * (n // 2) + "-" + " " * n + "封面图"):
            text = _reply([("img_kind", v)])
            t0 = time.perf_counter()
            r = FI.read_reply(BANK, g, text, "end_turn")
            assert FI.match_option(kq, v) == (None, None) and real_shape(BANK, g, text, "end_turn")["img_kind"][0] is None
            assert time.perf_counter() - t0 < 2, "答案里一长串空格读了太久 (正则回溯)"
            assert repr(r["parsed"]) == repr(_old_parse(BANK, g, text)) and not r["would_read"]
            assert r["notes"]["img_kind"] == (FI.NOTE_TOO_LONG if len(text) > 20_000 else FI.NOTE_OOV_PLUS), (n, r["notes"])

    # ③ 走一遍: 假模型按记号换一种回法。认下来的和老读法一样 (抄整行 / 换了样子的 JSON 还是没答成), 摘要里只有写死的词
    class Odd(Fakes):
        def ask(self, model, prompt, block):
            text, usage = super().ask(model, prompt, block)
            key = base64.b64decode(block[1]).decode()
            first = "img_kind" in prompt
            ans = json.loads(text)["answers"]
            if "LINE" in key and first:
                ans[0]["answer"] = KIND_LINE
            elif "SHOTFULL" in key and first:
                ans[0]["answer"] = SHOT_LINE
            elif "WRAP" in key and first:
                ans[0]["answer"] = "「封面」。"
            elif "DOUBT" in key and first:
                ans[0]["answer"] = "封面？"
            elif "CROSS" in key and first:
                ans[0]["answer"] = "❌封面"
            elif "THINK" in key and first:
                return "", usage, "max_tokens"
            elif "SYMBOLS" in key:
                ans = [dict(a, answer="！！" if a["id"] == "img_main_text" else a["answer"]) for a in ans]
            elif "PLUS" in key and first:
                ans[0]["answer"] = "封面图"
            elif "HALF" in key and first:
                ans[0]["answer"] = "看不清"
            elif "NUMID" in key and first:
                ans = [{"id": str(n), "answer": a["answer"]} for n, a in enumerate(ans, 1)]
            elif "FLAT" in key and first:
                return json.dumps({a["id"]: a["answer"] for a in ans}, ensure_ascii=False), usage, "end_turn"
            elif "CUTOBJ" in key and first:
                return json.dumps({a["id"]: a["answer"] for a in ans}, ensure_ascii=False), usage, "max_tokens"
            elif "LIST" in key and first:
                return json.dumps([{"id": "img_kind", "answer": ["封面"]}], ensure_ascii=False), usage, "end_turn"
            elif "TRUNC" in key and first:
                return json.dumps({"answers": ans}, ensure_ascii=False)[:40], usage, "max_tokens"
            elif "SILENT" in key and first:
                return "", usage, f"refusal {ERR_CANARY}"
            elif "SAIDNONE" in key:
                ans = [dict(a, answer={"img_text_amount": "没有字", "img_main_text": "无。"}.get(a["id"], a["answer"])) for a in ans]
            elif "NOTEXT" in key:
                ans = [dict(a, answer="" if a["id"] == "img_main_text" else a["answer"]) for a in ans]
            elif "NOANS" in key and first:                 # 换了样子的 JSON, 但里面一个答案都读不出: 不数进 replies:loose_json
                return '{"foo": 1}', usage, "end_turn"
            elif "CONFL" in key and first:
                return '{"img_kind":"后台或数据截图","img_text_amount":"没有字"} ' + text, usage, "end_turn"
            elif "DUPK" in key and first:
                return '{"img_kind":"封面","img_kind":"封面","img_text_amount":"一句大字"}', usage, "end_turn"
            elif "LATERPUNCT" in key and not first:           # 后面几次调用的每道选择题: 选项包了标点
                ans = [dict(a, answer=f"「{a['answer']}」。" if a["id"] in later_choice else a["answer"]) for a in ans]
            elif "LATERFULL" in key and not first:           # 后面几次调用的每道选择题: 抄了选项的整行 (有解释的才抄得成)
                ans = [dict(a, answer=line_of(a["id"], a["answer"])) for a in ans]
            elif "MANY" in key and "img_person" in prompt:
                ans = [dict(a, answer={"img_person": "有人", "img_scene": "生活场景。"}.get(a["id"], a["answer"])) for a in ans]
            return json.dumps({"answers": ans}, ensure_ascii=False), usage, "end_turn"

    bidx = FI.question_index(BANK)
    later_choice = [q for u in P.call_units(BANK)[1:] for q in u if bidx[q]["type"] == "choice"]

    def line_of(qid, v):
        means = next((o.get("means") for o in bidx[qid].get("options") or [] if str(o["value"]) == v), None)
        return f"{v}: {means}" if qid in later_choice and means else v

    tags = ["ok1", "LINE1", "FLAT1", "SHOTFULL1", "PLUS1", "HALF1", "NUMID1", "TRUNC1", "SILENT1", "SAIDNONE1", "NOTEXT1", "MANY1",
            "DOUBT1", "CROSS1", "THINK1", "SYMBOLS1", "WRAP1", "CUTOBJ1", "LIST1", "NOANS1", "CONFL1", "DUPK1", "LATERPUNCT1", "LATERFULL1"]
    fk, store = Odd(), FakeStore([_cand(t) for t in tags])
    res, out = _run(store, fk)
    by = {s["note_id"].split("-", 1)[1]: (s["status"], s["outcome"], rows) for s, rows in store.writes}
    assert res["ended"] == "done" and [by[t][0] for t in tags] == [
        "answered" if t in ("ok1", "MANY1", "LATERPUNCT1", "LATERFULL1") else "no_answer" for t in tags], [by[t][0] for t in tags]
    for t in ("LINE1", "FLAT1", "SHOTFULL1", "WRAP1", "CUTOBJ1", "LIST1", "PLUS1", "HALF1", "NUMID1", "TRUNC1", "SILENT1", "DOUBT1",
              "CROSS1", "THINK1", "NOANS1", "CONFL1", "DUPK1"):
        assert by[t][1:] == ("counted", []) and sum(1 for _m, k, _p in fk.asks if t in k) == 1, \
            f"{t}: 第一次调用没读出来 (没有放宽), 一行答案都不写, 后面不问"
    for t in ("SAIDNONE1", "NOTEXT1", "SYMBOLS1"):
        assert by[t][1:] == ("counted", []) and sum(1 for _m, k, _p in fk.asks if t in k) == 7, f"{t}: 整轮作废还是整轮作废"
    many = {r["question_id"]: r for r in by["MANY1"][2]}
    assert many["img_person"]["invalid_reason"] == "out_of_vocab" and many["img_scene"]["invalid_reason"] == "out_of_vocab" \
        and many["img_scene"]["answer"] is None, "「生活场景。」不是一字不差的选项: 存的还是 out_of_vocab"
    # 后面几次调用的每道选择题: 包了标点的、抄了整行的都照旧存 out_of_vocab、答案是空的 (不只是第一次调用不放宽)
    punct = {r["question_id"]: r for r in by["LATERPUNCT1"][2]}
    full = {r["question_id"]: r for r in by["LATERFULL1"][2]}
    asked = {r["question_id"]: r["answer"] for r in by["ok1"][2]}
    lined = [q for q in later_choice if line_of(q, asked[q]) != asked[q]]
    assert len(later_choice) == 8 and len(lined) >= 4 and {u[0] for u in P.call_units(BANK)[1:]} - {"img_main_text"} <= set(later_choice)
    for q in later_choice:
        assert (punct[q]["answer"], punct[q]["invalid_reason"]) == (None, "out_of_vocab"), f"{q}: 包了标点的选项不认"
        want_full = (None, "out_of_vocab") if q in lined else (asked[q], None)
        assert (full[q]["answer"], full[q]["invalid_reason"]) == want_full, f"{q}: 抄了整行的选项不认"
    for rows in (punct, full):
        assert all(rows[q]["invalid_reason"] is None for q in rows if q not in later_choice)
    stored = {r["invalid_reason"] for _s, rows in store.writes for r in rows}
    assert stored <= {None, FI.INVALID_PARSE, FI.INVALID_MISSING, FI.INVALID_OOV, FI.INVALID_TEXT_LONG, P.INVALID_SOURCE,
                      FI.INVALID_NO_TITLE, FI.INVALID_NOT_COVER}, f"落库的无效原因还是老的那几个词: {stored}"
    assert res["status"] == {"answered": 4, "no_answer": 20}, res["status"]
    assert sum(res["no_answer_why"].values()) == res["status"]["no_answer"], "每一篇没答成的都有一个原因"
    assert res["no_answer_why"] == {
        "first_call:oov_option_line": 2, "first_call:oov_option_wrapped": 1, "first_call:json_not_template": 1,
        "first_call:oov_option_plus_more": 1, "first_call:oov_part_of_option": 1, "first_call:id_numbered": 1,
        "first_call:truncated": 3, "first_call:empty_reply": 1, "first_call:oov_option_with_mark": 2,
        "first_call:answer_not_text": 1, "first_call:no_answers_in_json": 1, "first_call:conflicting_answers": 1,
        "first_call:json_duplicate_key": 1,
        "round:no_text_but_transcribed:said_none_in_words": 1, "round:text_but_not_transcribed:empty_text": 1,
        "round:text_but_not_transcribed:symbols_only": 1}, res["no_answer_why"]
    want_q = {f"{q}:oov_option_wrapped": 1 for q in later_choice}
    want_q.update({f"{q}:oov_option_line": 1 for q in lined})
    want_q["img_scene:oov_option_wrapped"] = 2             # MANY1 的那一个
    want_q.update({
        "img_kind:no_answers_in_json": 1, "img_text_amount:no_answers_in_json": 1, "img_kind:conflicting_answers": 1,
        "img_text_amount:conflicting_answers": 1, "img_kind:json_duplicate_key": 1, "img_text_amount:json_duplicate_key": 1,
        "img_kind:oov_option_line": 2, "img_kind:oov_option_wrapped": 1, "img_kind:json_not_template": 1,
        "img_text_amount:json_not_template": 1, "img_kind:oov_option_plus_more": 1, "img_kind:oov_part_of_option": 1,
        "img_kind:id_numbered": 1, "img_kind:oov_option_with_mark": 2, "img_text_amount:id_numbered": 1,
        "img_kind:truncated": 3, "img_text_amount:truncated": 3, "img_kind:empty_reply": 1, "img_text_amount:empty_reply": 1,
        "img_kind:answer_not_text": 1, "img_text_amount:id_absent": 1,
        "img_person:oov_other": 1})
    assert res["invalid_by_question"] == want_q, res["invalid_by_question"]
    assert res["reply"] == {"stop:max_tokens": 3, "stop:other": 1}, res["reply"]
    # 「假如放宽」: 按无效的答案数; 换了样子的 JSON 那一行按回包数, 而且只数真有答案读得出的回包
    # (FLAT1 两个答案 1 个回包; CUTOBJ1 撞了上限、LIST1 答案不是字符串、NOANS1 里面没有答案、CONFL1 两段答案打架、
    #  DUPK1 同一个键两遍 → 都是换了样子的 JSON, 但一个答案都读不出, 不数)
    assert res["would_read"] == {"answers:option_line_copied": 2 + len(lined), "answers:option_with_punctuation": 2 + len(later_choice),
                                 "answers:loose_json": 2, "replies:loose_json": 1}, res["would_read"]
    assert "tolerated" not in json.dumps(res) and "rescued" not in json.dumps(res), "没有「放宽读出来了」这种计数"
    for line in ("没答成（no_answer）的原因：", "逐题无效（题号:原因=调用次数）：", "回包：", "first_call:truncated=3", "first_call:oov_option_with_mark=2",
                 "round:no_text_but_transcribed:said_none_in_words=1", "img_person:oov_other=1", "stop:max_tokens=3",
                 "假如放宽读法会多读出（没有放宽，这些答案照旧无效）：", f"answers:option_line_copied={2 + len(lined)}", "replies:loose_json=1"):
        assert line in out, f"摘要里没有 {line}"
    _no_leak("没答成的原因", out, json.dumps(res, ensure_ascii=False, default=str))
    for text in (out, json.dumps(res, ensure_ascii=False)):
        assert "给读者看的图" not in text and "refusal" not in text and "tolerated" not in text, "回包里的字 / stop_reason 的原样不进输出"
    keys = list(res["no_answer_why"]) + list(res["invalid_by_question"]) + list(res["reply"]) + list(res["would_read"])
    assert all(re.fullmatch(r"[a-z0-9_:]+", k) for k in keys), keys
    fixed = set(FI.NOTES) | {FI.INVALID_PARSE, FI.INVALID_MISSING, FI.INVALID_OOV, FI.INVALID_TEXT_LONG}
    assert all(k.split(":", 1)[1] in fixed for k in res["invalid_by_question"]), "逐题无效的词全在写死的那张单子里"
    assert all(k.split(":", 1)[1] in fixed for k in res["no_answer_why"] if k.startswith("first_call:"))
    assert all(k.split(":", 1)[1] in FI.WOULD_READ for k in res["would_read"]) and set(res["reply"]) <= {"stop:max_tokens", "stop:other"}
    # 没写进库的帖不进原因计数: 原因那一行的数加起来永远等于 no_answer 的篇数
    for tag in ("PLUS9", "SAIDNONE9"):                         # 第一次调用没读出来 / 整轮作废, 两条路
        res, _ = _run(FakeStore([_cand(tag)], write_fails="no_answer"), Odd())
        assert res["ended"] == "write_failed" and res["status"] == {} and res["no_answer_why"] == {}, (tag, res["no_answer_why"])
    # 嵌得太深的回包: 这一篇记没答成, 整趟照走 (不是「首图步骤中断」)
    class Deep(Fakes):
        def ask(self, model, prompt, block):
            text, usage = super().ask(model, prompt, block)
            return ("[" * 9000 + "]" * 9000 if "DEEP" in base64.b64decode(block[1]).decode() else text), usage, "end_turn"
    res, _ = _run(FakeStore([_cand("DEEP1"), _cand("ok2")]), Deep())
    assert res["ended"] == "done" and res["status"] == {"no_answer": 1, "answered": 1} \
        and res["no_answer_why"] in ({"first_call:no_json": 1}, {"first_call:no_answers_in_json": 1}), res
    # 标题是空的帖: 代码题算不成也数得到
    res, _ = _run(FakeStore([dict(_cand("t1"), title="")]), Fakes())
    assert res["status"] == {"answered": 1} and res["invalid_by_question"] == {"img_text_matches_title:no_title": 1}, res
    for doc, needles in (("docs/34-first-image-pass.md", ("D-159", "first_call:", "oov_option_plus_more", "oov_option_with_mark", "stop:other",
                                                          "would_read", "没有放宽", "原因还不知道", "别的记 `reply_too_long`")),
                         ("DECISIONS.md", ("D-159", "would_read", "没有放宽")), ("OPEN-ITEMS.md", ("D-159", "I-38", "would_read")),
                         ("CURRENT_STATE.md", ("D-159", "没有放宽"))):
        text = (ROOT / doc).read_text(encoding="utf-8")
        for nd in needles:
            assert nd in text, f"{doc} 里没写 {nd}"
    print(f"  §8 没答成的原因按写死的词分开数; 认什么和老读法逐字相同 ({len(corpus)} 条固定回包, 含评审核实过的每一种), "
          "没有放宽; 「假如放宽」只是另数一行 ✓")


def main() -> int:
    check_bank()
    check_money()
    check_pass()
    check_caps()
    check_never_blocks()
    check_stops()
    check_wiring()
    check_reply_reading()
    print("\ncheck_first_image_pass: 8 节全过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
