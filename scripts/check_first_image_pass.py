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
  §8  没答成的原因看得见 (11-16 首跑 32 张里 11 张没答成, 当时看不出为什么): 摘要按写死的词分开数 —— 第一次调用没读出来的
      (empty_reply / truncated / no_json / id_numbered / oov_* …)、整轮作废的 (哪条自检规则)、逐题无效的次数、回包撞没撞 max_tokens;
      回包的读法只认格式不猜意思: 选项外面多了标点、抄了选项的整行、JSON 换了个样子 (题号还是那个题号) 读得出来;
      多一个字少一个字、数字题号、断掉的回包、同一题两个答案照旧无效; 「不是封面」变不成「答成了」;
      带问号 / 叉 / 删除线 / 省略号 / 表情的、字中间断开的选项不认 (「封面？」不是「封面」); 读不出来的那一段 JSON 整段跳过,
      撞了输出上限又不是完整模板的一个答案都不取; 嵌得再深的回包也只是读不出来; 没写进库的帖不进原因计数

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
  ⑫ 去掉 no_answer_why / invalid_q 的计数, 或 summary 不打这几行                                      → §8
  ⑬ match_option 改回只认一字不差 / read_reply 改回只读「第一个 { 到最后一个 }」                       → §8
  ⑭ match_option 放宽成「以选项开头就算」(封面图 / 只抄了半句解释 也算封面)                            → §8
  ⑮ match_option 改回「去掉所有标点符号再比」(封面？ / ❌封面 / ~~封面~~ 也算封面)                     → §8
  ⑯ _json_values 读不出来时往里挪一个字接着找 / read_reply 撞了上限照样捡 / 只接 ValueError             → §8
  ⑰ 先数 no_answer 的原因再写库 / 空回包排在撞上限前面 / 去掉最外层是列表那一支 / 去掉抄字题的两答案检查  → §8

跑法: cd scripts && python check_first_image_pass.py
"""
from __future__ import annotations

import base64
import contextlib
import copy
import hashlib
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


def _reply(items) -> str:
    return json.dumps({"answers": [{"id": i, "answer": a} for i, a in items]}, ensure_ascii=False)


def check_reply_reading() -> None:
    g = P.call_units(BANK)[0]

    def kind(text, stop=None):
        r = FI.read_reply(BANK, g, text, stop)
        assert set(r["notes"].values()) <= set(FI.NOTES) and set(r["tolerated"]) <= set(FI.TOLERATED), r
        assert r["parsed"] == FI.parse_answers(BANK, g, text), "parse_answers 和 read_reply 是同一套读法"
        return r["parsed"]["img_kind"], r["notes"].get("img_kind"), r["tolerated"]

    # 读得出来的: 提示词自己招来的几种写法 (选项是带着解释打出来的, 又说「照抄选项的原文」; 只说了「只输出 JSON」)
    assert kind(_reply([("img_kind", "封面"), ("img_text_amount", "一句大字")])) == (("封面", None), None, [])
    assert KIND_LINE.split(": ", 1)[0] == "封面" and f"- {KIND_LINE}" in FI.build_prompt(BANK, g), "KIND_LINE 就是提示词里那一行"
    assert kind(_reply([("img_kind", KIND_LINE)])) == (("封面", None), None, [FI.TOL_LINE])
    assert kind(_reply([("img_kind", SHOT_LINE)]))[0] == ("后台或数据截图", None), "抄整行的「不是封面」还是不是封面"
    for v in ("封面。", "「封面」", "- 封面", " 封面\u200b", '"封面"', "**封面**", "（封面）", "【封面】", "封面！", "封面，"):
        assert kind(_reply([("img_kind", v)])) == (("封面", None), None, [FI.TOL_PUNCT]), v
    for v in ("!封面", "！封面", "! 封面"):                 # 打头的感叹号不当标点去 (可能是「不是」)
        assert kind(_reply([("img_kind", v)]))[0][0] is None, v
    assert kind(_reply([("img_kind", KIND_LINE.replace(": ", "："))])) == (("封面", None), None, [FI.TOL_LINE]), "整行里冒号换了全角"
    two = json.dumps([{"id": "img_kind", "answer": "封面"}, {"id": "img_text_amount", "answer": "没有字"}], ensure_ascii=False)
    r2 = FI.read_reply(BANK, g, two)                          # 最外层是列表、两个对象 (老的读法读不出来)
    assert r2["parsed"]["img_kind"] == ("封面", None) and r2["parsed"]["img_text_amount"] == ("没有字", None) \
        and r2["tolerated"] == [FI.TOL_LOOSE_JSON], r2
    ok = _reply([("img_kind", "封面")])
    for text in (ok + " 说明: {备注}", '格式: {"answers":[{"id":"题号","answer":"答案"}]}\n' + ok,
                 '{"id":"img_kind","answer":"封面"}\n{"id":"img_text_amount","answer":"没有字"}',
                 json.dumps([{"id": "img_kind", "answer": "封面"}], ensure_ascii=False),
                 json.dumps({"answers": {"img_kind": "封面"}}, ensure_ascii=False),
                 json.dumps({"img_kind": "封面", "img_text_amount": "没有字"}, ensure_ascii=False)):
        assert kind(text) == (("封面", None), None, [FI.TOL_LOOSE_JSON]), text
    assert kind("```json\n" + ok + "\n```") == (("封面", None), None, []), "围栏里的 JSON 本来就读得出来"

    # 照旧无效的: 只认格式, 不猜意思。每一种都有自己的词
    for v, note in (("封面图", FI.NOTE_OOV_PLUS), ("封面: 给读者看的图", FI.NOTE_OOV_PLUS), ("是封面", FI.NOTE_OOV_CONTAINS),
                    ("看不清", FI.NOTE_OOV_PART), ("数据截图", FI.NOTE_OOV_PART), ("cover", FI.NOTE_OOV_OTHER),
                    ("别的东西", FI.NOTE_OOV_OTHER), ("", FI.NOTE_OOV_OTHER)):
        assert kind(_reply([("img_kind", v)])) == ((None, FI.INVALID_OOV), note, []), v
    # 带着会改意思的记号的, 或者字中间断开的: 字是那个选项, 也不认 (不把打了问号、打了叉、划掉的「封面」读成封面)
    for v in ("封面？", "封面?", "封面 (?)", "❌封面", "封面❌", "封面 ✗", "封面×", "封面(×)", "≠封面", "~封面", "~~封面~~",
              "封面…", "封面...", "封面……", "封\n面", "封 面", "封\u0336面\u0336", "封面🙂", "✓封面", "封面/", "<封面>"):
        assert kind(_reply([("img_kind", v)])) == ((None, FI.INVALID_OOV), FI.NOTE_OOV_MARKED, []), v
    for v in (KIND_LINE + "？", "❌" + KIND_LINE, "~~" + KIND_LINE + "~~", KIND_LINE + "…", KIND_LINE.replace("封面", "封\u0336面")):
        got = kind(_reply([("img_kind", v)]))
        assert got[0] == (None, FI.INVALID_OOV) and got[2] == [], v
    q_amount = FI.question_index(BANK)["img_text_amount"]
    assert FI.match_option(q_amount, "没有字？") == (None, None) and FI.match_option(q_amount, "没有字。") == ("没有字", FI.TOL_PUNCT)
    # 读不出来的那一段 JSON 整段跳过, 不进去捡里面的对象; 撞了输出上限又不是完整的模板, 一个答案都不取
    for text, stop, note in (
            ('{"answers":[{"id":"img_kind","answer":"封面"},]}', None, FI.NOTE_NO_JSON),
            ('{"answers":[{"id":"img_kind","answer":"封面"},{"id":"img_text_amount","answer":"没有字"}], 备注}', None, FI.NOTE_NO_JSON),
            ('{"id":"img_kind","answer":"封面"}\n', "max_tokens", FI.NOTE_TRUNCATED),
            (two, "max_tokens", FI.NOTE_TRUNCATED),
            ("", "max_tokens", FI.NOTE_TRUNCATED),             # 思考把上限用完、一个字都没回: 是撞上限, 不是 empty_reply
            ("  \n", "max_tokens", FI.NOTE_TRUNCATED),
            ("[" * 12000 + "]" * 12000, None, FI.NOTE_NO_JSON),  # 嵌得太深: 只是读不出来, 不抛
            ('{"a":' + "[" * 12000 + "]" * 12000 + "}", "end_turn", FI.NOTE_NO_JSON),
            ('说明 {"x": 1} 和 {备注}', None, FI.NOTE_NO_ANSWERS)):
        r = FI.read_reply(BANK, g, text, stop)
        assert r["parsed"]["img_kind"] == (None, FI.INVALID_PARSE) and r["notes"]["img_kind"] == note and r["tolerated"] == [], \
            (text[:60], r["parsed"]["img_kind"], r["notes"]["img_kind"], r["tolerated"])
    assert kind(ok, "max_tokens") == (("封面", None), None, []), "完整的模板 JSON 读得出来, 撞没撞上限都一样"
    assert kind("{备注} " + '{"id":"img_kind","answer":"封面"}') == (("封面", None), None, [FI.TOL_LOOSE_JSON]), "跳过读不出来的一段, 后面的照读"
    # null 的重复项不算一个答案; 只有 null 还是没答
    assert kind(json.dumps({"answers": [{"id": "img_kind", "answer": "封面"}, {"id": "img_kind", "answer": None}]}))[0] == ("封面", None)
    assert kind(json.dumps({"answers": [{"id": "img_kind", "answer": None}]}))[:2] == ((None, FI.INVALID_MISSING), FI.NOTE_NOT_TEXT)
    assert kind(json.dumps({"answers": [{"id": "img_kind", "answer": "封面"}, {"id": "img_kind", "answer": ["封面"]}]}))[:2] == \
        ((None, FI.INVALID_MISSING), FI.NOTE_NOT_TEXT), "不是字符串的重复项 (null 以外) 还是无效"
    assert kind(_reply([("img_kind", "别的"), ("img_kind", "其他")]))[:2] == ((None, FI.INVALID_PARSE), FI.NOTE_CONFLICT), "两个都认不出、又不一样"
    assert kind(_reply([("img_kind", "别的"), ("img_kind", " 别的 ")]))[:2] == ((None, FI.INVALID_OOV), FI.NOTE_OOV_OTHER), "认不出的同一个答案说两遍"
    # 抄字题: 两遍不一样 → 无效; 只差标点空格 → 算同一个, 取第一遍
    gt = ["img_main_text"]
    rt = FI.read_reply(BANK, gt, _reply([("img_main_text", "三天见效"), ("img_main_text", "七天见效")]))
    assert rt["parsed"]["img_main_text"] == (None, FI.INVALID_PARSE) and rt["notes"]["img_main_text"] == FI.NOTE_CONFLICT, rt
    rt = FI.read_reply(BANK, gt, _reply([("img_main_text", "三天见效"), ("img_main_text", "三天 见效！")]))
    assert rt["parsed"]["img_main_text"] == ("三天见效", None) and not rt["notes"], rt

    for text, stop, why, note in (
            ("", None, FI.INVALID_PARSE, FI.NOTE_EMPTY),
            ("", "end_turn", FI.INVALID_PARSE, FI.NOTE_EMPTY),
            ("我看不了图片", "end_turn", FI.INVALID_PARSE, FI.NOTE_NO_JSON),
            ('{"answers":[{"id":"img_kind","answer":"封面"},{"id":"img_text_amount","answer":"一句', "max_tokens",
             FI.INVALID_PARSE, FI.NOTE_TRUNCATED),
            ('{"answers":[{"id":"img_kind","answer":"封面"},{"id":"img_text_amount","answer":"一句', None,
             FI.INVALID_PARSE, FI.NOTE_NO_JSON),                      # 断掉的回包: 不从里面捡半截答案
            (_reply([("1", "封面"), ("2", "没有字")]), None, FI.INVALID_MISSING, FI.NOTE_ID_NUMBERED),
            (json.dumps({"answers": [{"id": 1, "answer": "封面"}]}), None, FI.INVALID_MISSING, FI.NOTE_ID_NUMBERED),
            (_reply([("题号", "封面")]), None, FI.INVALID_MISSING, FI.NOTE_NO_ANSWERS),
            (_reply([("img_text_amount", "没有字")]), None, FI.INVALID_MISSING, FI.NOTE_ID_ABSENT),
            (json.dumps({"answers": [{"id": "img_kind", "answer": ["封面"]}]}), None, FI.INVALID_MISSING, FI.NOTE_NOT_TEXT),
            (_reply([("img_kind", "封面"), ("img_kind", "后台或数据截图")]), None, FI.INVALID_PARSE, FI.NOTE_CONFLICT),
            (_reply([("img_kind", "别的"), ("img_kind", "封面")]), None, FI.INVALID_PARSE, FI.NOTE_CONFLICT),
            ('{"img_kind":"后台或数据截图"} ' + ok, None, FI.INVALID_PARSE, FI.NOTE_CONFLICT)):
        assert kind(text, stop)[:2] == ((None, why), note), (text, kind(text, stop))
    assert kind(_reply([("img_kind", "封面"), ("img_kind", "封面。")]))[0] == ("封面", None), "同一个答案说两遍不算矛盾"
    assert FI.stop_word("end_turn") == "end_turn" and FI.stop_word("max_tokens") == "max_tokens" and FI.stop_word(None) is None
    assert FI.stop_word(f"x {ERR_CANARY}") == "other", "stop_reason 只带写死的词"

    # 两份题库里, 去掉标点之后没有两个选项撞在一起, 也没有哪个选项的整行和别的选项撞 (撞了 match_option 就只能都不认)
    for bank in (BANK, FI.load_bank()):
        for q in bank["questions"]:
            if q["type"] != "choice":
                continue
            keys = [FI.normalise(str(o["value"])) for o in q["options"]]
            keys += [FI.normalise(f"{o['value']}{o['means']}") for o in q["options"] if o.get("means")]
            assert all(keys) and len(keys) == len(set(keys)), q["id"]
            for o in q["options"]:
                assert FI.match_option(q, str(o["value"])) == (str(o["value"]), None)
                if o.get("means"):
                    assert FI.match_option(q, f"{o['value']}: {o['means']}") == (str(o["value"]), FI.TOL_LINE), q["id"]

    # 走一遍: 假模型按记号换一种回法
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
            elif "FLAT" in key:
                return json.dumps({a["id"]: a["answer"] for a in ans}, ensure_ascii=False), usage, "end_turn"
            elif "TRUNC" in key and first:
                return json.dumps({"answers": ans}, ensure_ascii=False)[:40], usage, "max_tokens"
            elif "SILENT" in key and first:
                return "", usage, f"refusal {ERR_CANARY}"
            elif "SAIDNONE" in key:
                ans = [dict(a, answer={"img_text_amount": "没有字", "img_main_text": "无。"}.get(a["id"], a["answer"])) for a in ans]
            elif "NOTEXT" in key:
                ans = [dict(a, answer="" if a["id"] == "img_main_text" else a["answer"]) for a in ans]
            elif "MANY" in key and "img_person" in prompt:
                ans = [dict(a, answer={"img_person": "有人", "img_scene": "生活场景。"}.get(a["id"], a["answer"])) for a in ans]
            return json.dumps({"answers": ans}, ensure_ascii=False), usage, "end_turn"

    tags = ["ok1", "LINE1", "FLAT1", "SHOTFULL1", "PLUS1", "HALF1", "NUMID1", "TRUNC1", "SILENT1", "SAIDNONE1", "NOTEXT1", "MANY1",
            "DOUBT1", "CROSS1", "THINK1", "SYMBOLS1"]
    fk, store = Odd(), FakeStore([_cand(t) for t in tags])
    res, out = _run(store, fk)
    by = {s["note_id"].split("-", 1)[1]: (s["status"], s["outcome"], rows) for s, rows in store.writes}
    assert res["ended"] == "done" and [by[t][0] for t in tags] == [
        "answered", "answered", "answered", "not_a_cover", "no_answer", "no_answer", "no_answer", "no_answer", "no_answer",
        "no_answer", "no_answer", "answered", "no_answer", "no_answer", "no_answer", "no_answer"], [by[t][0] for t in tags]
    for t in ("LINE1", "FLAT1"):
        got = {r["question_id"]: r["answer"] for r in by[t][2]}
        assert got["img_kind"] == "封面" and len(by[t][2]) == 13 and all(r["invalid_reason"] is None for r in by[t][2]), \
            f"{t}: 存的是选项的原值, 不是回包里的写法"
    assert [(r["question_id"], r["answer"]) for r in by["SHOTFULL1"][2]] == [("img_kind", "后台或数据截图")]
    for t in ("PLUS1", "HALF1", "NUMID1", "TRUNC1", "SILENT1", "DOUBT1", "CROSS1", "THINK1"):
        assert by[t][1:] == ("counted", []) and sum(1 for _m, k, _p in fk.asks if t in k) == 1, f"{t}: 第一次调用没读出来, 后面不问"
    for t in ("SAIDNONE1", "NOTEXT1", "SYMBOLS1"):
        assert by[t][1:] == ("counted", []) and sum(1 for _m, k, _p in fk.asks if t in k) == 7, f"{t}: 整轮作废还是整轮作废"
    many = {r["question_id"]: r for r in by["MANY1"][2]}
    assert many["img_person"]["invalid_reason"] == "out_of_vocab" and many["img_scene"]["answer"] == "生活场景"
    assert res["status"] == {"answered": 4, "not_a_cover": 1, "no_answer": 11}, res["status"]
    assert sum(res["no_answer_why"].values()) == res["status"]["no_answer"], "每一篇没答成的都有一个原因"
    assert res["no_answer_why"] == {
        "first_call:oov_option_plus_more": 1, "first_call:oov_part_of_option": 1, "first_call:id_numbered": 1,
        "first_call:truncated": 2, "first_call:empty_reply": 1, "first_call:oov_option_with_mark": 2,
        "round:no_text_but_transcribed:said_none_in_words": 1, "round:text_but_not_transcribed:empty_text": 1,
        "round:text_but_not_transcribed:symbols_only": 1}, res["no_answer_why"]
    assert res["invalid_by_question"] == {
        "img_kind:oov_option_plus_more": 1, "img_kind:oov_part_of_option": 1, "img_kind:id_numbered": 1,
        "img_kind:oov_option_with_mark": 2,
        "img_text_amount:id_numbered": 1, "img_kind:truncated": 2, "img_text_amount:truncated": 2,
        "img_kind:empty_reply": 1, "img_text_amount:empty_reply": 1, "img_person:oov_other": 1}, res["invalid_by_question"]
    assert res["reply"] == {"stop:max_tokens": 2, "stop:other": 1, "tolerated:option_line_copied": 2,
                            "tolerated:loose_json": 7, "tolerated:option_with_punctuation": 1}, res["reply"]
    for line in ("没答成（no_answer）的原因：", "逐题无效（题号:原因=调用次数）：", "回包：", "first_call:truncated=2", "first_call:oov_option_with_mark=2",
                 "round:no_text_but_transcribed:said_none_in_words=1", "img_person:oov_other=1", "stop:max_tokens=2"):
        assert line in out, f"摘要里没有 {line}"
    _no_leak("没答成的原因", out, json.dumps(res, ensure_ascii=False, default=str))
    for text in (out, json.dumps(res, ensure_ascii=False)):
        assert "给读者看的图" not in text and "refusal" not in text, "回包里的字 / stop_reason 的原样不进输出"
    keys = list(res["no_answer_why"]) + list(res["invalid_by_question"]) + list(res["reply"])
    assert all(re.fullmatch(r"[a-z0-9_:]+", k) for k in keys), keys
    # 没写进库的帖不进原因计数: 原因那一行的数加起来永远等于 no_answer 的篇数
    for tag in ("PLUS9", "SAIDNONE9"):                         # 第一次调用没读出来 / 整轮作废, 两条路
        res, _ = _run(FakeStore([_cand(tag)], write_fails="no_answer"), Odd())
        assert res["ended"] == "write_failed" and res["status"] == {} and res["no_answer_why"] == {}, (tag, res["no_answer_why"])
    # 嵌得太深的回包: 这一篇记没答成, 整趟照走 (不是「首图步骤中断」)
    class Deep(Fakes):
        def ask(self, model, prompt, block):
            text, usage = super().ask(model, prompt, block)
            return ("[" * 12000 + "]" * 12000 if "DEEP" in base64.b64decode(block[1]).decode() else text), usage, "end_turn"
    res, _ = _run(FakeStore([_cand("DEEP1"), _cand("ok2")]), Deep())
    assert res["ended"] == "done" and res["status"] == {"no_answer": 1, "answered": 1} \
        and res["no_answer_why"] == {"first_call:no_json": 1}, res
    # 标题是空的帖: 代码题算不成也数得到
    res, _ = _run(FakeStore([dict(_cand("t1"), title="")]), Fakes())
    assert res["status"] == {"answered": 1} and res["invalid_by_question"] == {"img_text_matches_title:no_title": 1}, res
    for doc, needles in (("docs/34-first-image-pass.md", ("D-159", "first_call:", "oov_option_plus_more", "oov_option_with_mark", "stop:other", "237,558", "推断")),
                         ("DECISIONS.md", ("D-159", "237,558")), ("OPEN-ITEMS.md", ("D-159", "I-38")), ("CURRENT_STATE.md", ("D-159",))):
        text = (ROOT / doc).read_text(encoding="utf-8")
        for nd in needles:
            assert nd in text, f"{doc} 里没写 {nd}"
    print("  §8 没答成的原因按写死的词分开数; 回包只认格式: 两头的标点 / 整行 / 换了样子的 JSON 读得出, "
          "多字少字 / 带问号或叉 / 数字题号 / 断包 / 读不出来的一段 / 两个答案照旧无效 ✓")


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
