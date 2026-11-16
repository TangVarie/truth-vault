#!/usr/bin/env python3
"""first_image_pass.py —— 每晚的首图步骤 (I-29, D-158, 2026-11-16; 读法: docs/34-first-image-pass.md)。

owner 11-16 同意的小的那一版:
  1. 只用便宜档模型 (first_image.TIERS["cheap"]); 题库 fi-v0.2 (没有 img_colour; 五道「过, 但要单独问」的题一次只问一道)
  2. RIO / TXQ / WTG 先不做 (题库文件的 excluded_projects)
  3. 模型说首图不是封面的帖: 后面的题不问, 不存能用的特征, 不上经验卡
  4. 多图的帖照样答, 但带 cover_unconfirmed, 读的那一面不给出它的答案, 直到有人按表确认「第一个附件就是封面」
     (题库文件的 cover_confirmed_projects, 今天是空的); 只有一张图的帖现在就用
范围 (D-157): 经验卡背后的帖 + 每晚的新帖 (NEW_SINCE 之后入库、入库时发布还不到 30 天的; 整张表刚接进来或删了重灌时
  带进来的老帖不算, 规则在迁移的 first_image_candidates 里)。老帖不回头补。

它做的事: 问库要这一晚该做的帖 (first_image_candidates) → 按 file_token 从飞书把首图下载到内存 → 缩成长边 1,024 的 JPEG →
先问「是不是封面」那一组, 是封面再问其余六次 → 校验 → 一张图的结果一次写进库 (write_first_image_result)。

钱 (硬的, 写死在代码里, 命令行只能调低):
  · 只许调便宜档: 每次调用之前再核一遍模型名 (不是 TIERS["cheap"]、或它不是价格表里最便宜的那个, 就不发)。
    这个文件没有换模型的参数, 也不读任何环境变量来定模型。
  · 每晚 (mode=nightly): 最多 NIGHTLY_MAX_IMAGES 张图、NIGHTLY_MAX_WEIGHTED 输入当量 token (按价格表约 0.97 元, 不到 1 元)
  · 一次性做经验卡的帖 (mode=cards, 只能手动): 最多 CARDS_MAX_IMAGES 张、CARDS_MAX_WEIGHTED token (约 1.94 元, 不到 2 元)
  · token 上限 = min(写死的数, 按 scripts/model_prices.py 折出来的数): 价格表涨价, 上限自动跟着降; 降价不会把上限抬过写死的数
  · 每次调用【之前】查 (first_image.Budget): 已花的 + 在路上的预留 + 这一次的预留会越线, 这一次就不发, 之后也都不发
  · 一次预留对一个真发出去的请求: 只试一次、SDK 自带的重试关掉、只走主中转站 (这一步自己把 RELAY_FORCE 定成 primary;
    备用站那条路一次调用会发两个请求, 第二个不在账上, 所以这一步不用它 —— 主站不通的那一晚就不做, 下一晚再来)

不拦夜跑: 迁移 (schemas/notes_v1_28_first_image.sql) 没跑、缺环境变量、没装图片库、飞书不给下载、中转站不收图片、到了上限,
  都只打一行说明, 退出码 0 (--strict 才给非 0, 人手动排查时用)。没有新的环境变量和 secret。
一篇帖卡不住整趟: 飞书不给下载、模型没答成的那一篇都先记一笔 (下一晚它排到没做过的帖后面, 试满 6 次不再试) 再往下做;
  这一趟开头连着两篇不同的帖都这样, 才当成凭证 / 中转站的问题停下来。
名单 (先不做的项目 / 确认过封面的项目 / 往外给的题) 只要连得上库就同步, 干跑、缺钥匙、没装图片库时也同步: 它不花钱,
  而读的那一面要靠它才知道哪些帖不能往外给。

没答成的原因 (D-159, docs/34 §10): 摘要里按写死的词分开数 —— 第一次调用没读出来的是哪一种、整轮作废的是哪条自检规则、
  每道题无效了几次、回包撞没撞输出上限。只有计数; 原因不进库。认什么还是 first_image.parse_answers 一个地方说了算, 没有放宽;
  「假如放宽某一条读法会多读出几个」另数一行 (would_read), 那只是给下一步做决定用的数, 不是认下来的答案。

隐私: 图片只在内存里 (不写盘、不进 artifact、不进日志、不进库)。打出来的只有计数和状态词: 没有 note_id、标题、封面上的字、
  文件名、file_token、链接、中转站地址、报错正文。标题只给代码算「大字是不是重复标题」用, 不进提示词。

用法:
    cd scripts && python first_image_pass.py --dry-run                 # 不下载、不调模型、不写结果; 有 SUPABASE_* 就同步名单、报这一晚有几篇要做
    python first_image_pass.py                                         # 每晚那一趟
    python first_image_pass.py --mode cards                            # 一次性: 只做经验卡背后的帖
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import first_image as FI  # noqa: E402
import model_prices as MP  # noqa: E402

BANK_PATH = HERE.parent / "prompts" / "first_image_questions_v0_2.yaml"
BANK_VERSION = "fi-v0.2"
RUN_TAG = "img-primary"
CODE_EXTRACTOR = "code:fi"
FIRST_GROUP = "A_kind"                       # 先问这一组; img_kind 不是「封面」后面就不问
NEW_SINCE = "2026-11-16 00:00:00"            # 「新帖」先要 notes.ingested_at (第一次入库, UTC) 不早于这一刻; 老帖不回头补 (D-157)
SURFACE_TRIALS = ("pass", "pass_ask_alone")  # 往外给的题只能是试跑里两轮对得上的
TRIAL_VERDICTS = ("pass", "pass_ask_alone", "too_few", "kappa_undefined")

# ── 钱: 写死的上限 (命令行只能调低) ──
NIGHTLY_YUAN = 1.0
CARDS_YUAN = 2.0
NIGHTLY_MAX_WEIGHTED = 750_000               # 输入当量 token (输入 + 5 × 输出); 便宜档按价格表约 0.97 元
CARDS_MAX_WEIGHTED = 1_500_000               # 约 1.94 元
NIGHTLY_MAX_IMAGES = 40                      # 设计量过: 每晚新来的带图帖约 13 张
CARDS_MAX_IMAGES = 60                        # 设计时经验卡背后带图的帖 45 篇
MODES = {"nightly": (NIGHTLY_YUAN, NIGHTLY_MAX_WEIGHTED, NIGHTLY_MAX_IMAGES),
         "cards": (CARDS_YUAN, CARDS_MAX_WEIGHTED, CARDS_MAX_IMAGES)}

DEFAULT_WORKERS = 3                          # 一张图里「是封面」之后的那六次调用并着发; 图和图之间不并
DEFAULT_MAX_MINUTES = 40
MAX_CONSECUTIVE_API_FAILS = 6
HEAD_REFUSALS_TO_STOP = 2                    # 这一趟开头连着几篇不同的帖被飞书 / 中转站拒, 才当成不是哪一篇的问题、停
REQUIRED_ENV = ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "FEISHU_APP_ID", "FEISHU_APP_SECRET", "ANTHROPIC_API_KEY")

FINAL, COUNTED, INFRA = "final", "counted", "infra"
INVALID_SOURCE = "source_invalid"            # 代码题: 它要用的那句大字没抄成
_NONE_WORDS = frozenset(FI.normalise(w) for w in ("无", "没有", "没有字", "无字", "空", "空字符串", "none", "null", "n/a"))


class PassConfigError(Exception):
    """配置不对 (题库 / 模型 / 价格)。带一句不含任何客户材料的话。"""


def say(msg: str) -> None:
    print(msg, flush=True)


# ════════════════════════════════════════════════════════════════════
# 模型: 只许便宜档
# ════════════════════════════════════════════════════════════════════

def cheap_model() -> str:
    """这一步唯一许调的模型: 试跑配置里的便宜档, 而且它得是价格表里最便宜的那个 (有人把 TIERS["cheap"] 指到贵的模型上,
    这里就拒绝)。价格表里没有它 → 也拒绝 (算不出上限就不花钱)。"""
    model = FI.TIERS.get("cheap")
    price = MP.PRICES.get(model or "")
    if not model or not price:
        raise PassConfigError("便宜档模型不在价格表里 (scripts/model_prices.py)")
    if any(price[0] > p[0] or price[1] > p[1] for p in MP.PRICES.values()):
        raise PassConfigError("TIERS['cheap'] 指的不是价格表里最便宜的模型, 首图步骤不调它")
    return model


def guard_model(model: str) -> None:
    if model != cheap_model():
        raise PassConfigError("首图步骤只许调便宜档模型")


def caps(mode: str) -> dict:
    """这一趟的三道上限。token 上限 = min(写死的数, 按价格表把元数折成的 token 数)。"""
    if mode not in MODES:
        raise PassConfigError("mode 只能是 nightly / cards")
    yuan, literal, images = MODES[mode]
    per_million = MP.yuan_of_weighted(cheap_model(), 1_000_000)
    if not per_million or per_million <= 0:
        raise PassConfigError("价格表折不出元数")
    weighted = min(literal, int(yuan / per_million * 1_000_000))
    return {"mode": mode, "yuan": yuan, "weighted": weighted, "images": images,
            "weighted_yuan": MP.yuan_of_weighted(cheap_model(), weighted)}


class PassBudget(FI.Budget):
    """first_image.Budget (每次调用之前查 token 和次数) 再加一道图片数的上限。上限只能比写死的数低。"""

    def __init__(self, mode: str, calls_per_image: int, max_weighted: Optional[int] = None,
                 max_images: Optional[int] = None):
        c = caps(mode)
        self.max_images = c["images"] if not max_images or max_images <= 0 else min(int(max_images), c["images"])
        weighted = c["weighted"] if not max_weighted or max_weighted <= 0 else min(int(max_weighted), c["weighted"])
        super().__init__(max_weighted=weighted, max_calls=self.max_images * max(1, int(calls_per_image)))
        self.images = 0

    def take_image(self, estimate_total: int) -> bool:
        """开始做一张图之前: 图片数没到上限、这张图全部调用的预留加起来不越线, 才开始。"""
        with self._lock:
            if self.stopped:
                return False
            if self.images + 1 > self.max_images:
                self.stopped = "max_images"
                return False
            if self.spent + self.reserved + estimate_total > self.max_weighted:
                self.stopped = "max_tokens"
                return False
            self.images += 1
            return True


# ════════════════════════════════════════════════════════════════════
# 题库 fi-v0.2
# ════════════════════════════════════════════════════════════════════

def load_bank(path: Path | str = BANK_PATH) -> dict:
    return FI.load_bank(path)


def call_units(bank: dict) -> list[list[str]]:
    """一张图要发的调用, 按题库里的顺序: 每个调用组一次。"""
    return [list(v) for v in (bank.get("call_groups") or {}).values()]


def surfaced_questions(bank: dict) -> list[str]:
    return [str(q) for q in bank.get("surfaced_questions") or []]


def validate_bank(bank: dict) -> list[str]:
    """fi-v0.1 的结构校验 (一组 ≤ 4 题等) 再加 fi-v0.2 自己的几条。空 = 合法。"""
    errs = list(FI.validate_bank(bank, BANK_VERSION))
    idx = FI.question_index(bank)
    groups = bank.get("call_groups") or {}
    if "img_colour" in idx:
        errs.append("fi-v0.2 里不该有 img_colour (试跑没过线)")
    if bank.get("status") == "validated":
        errs.append("status 不能写 validated: 没有人对着图核过")
    if not groups or next(iter(groups)) != FIRST_GROUP or "img_kind" not in (groups.get(FIRST_GROUP) or []):
        errs.append(f"第一个调用组要是 {FIRST_GROUP}, 里面要有 img_kind")
    for name in ("excluded_projects", "cover_confirmed_projects", "ask_alone", "surfaced_questions"):
        val = bank.get(name)
        if not isinstance(val, list) or any(not isinstance(x, str) or not x.strip() for x in val):
            errs.append(f"{name} 要是字符串列表 (可以空)")
    for qid in bank.get("ask_alone") or []:
        owner = [g for g, members in groups.items() if qid in (members or [])]
        if qid not in idx or len(owner) != 1 or list(groups[owner[0]]) != [qid]:
            errs.append(f"ask_alone 里的 {qid} 要自己单独占一个调用组")
    for q in bank.get("questions") or []:
        verdict = q.get("trial")
        if verdict not in TRIAL_VERDICTS:
            errs.append(f"{q.get('id')}: trial 只能是 {' / '.join(TRIAL_VERDICTS)}")
        if verdict == "pass_ask_alone" and q.get("type") != "code" and q.get("id") not in (bank.get("ask_alone") or []):
            errs.append(f"{q.get('id')}: 试跑结论是「要单独问」, 却不在 ask_alone 里")
    for qid in bank.get("surfaced_questions") or []:
        q = idx.get(qid)
        if not q or q.get("type") == "text" or q.get("trial") not in SURFACE_TRIALS:
            errs.append(f"surfaced_questions 里的 {qid}: 只能是试跑里过线的闭集题 (抄下来的字不往外给)")
    if set(bank.get("excluded_projects") or []) & set(bank.get("cover_confirmed_projects") or []):
        errs.append("同一个项目不能既在 excluded_projects 又在 cover_confirmed_projects 里")
    return errs


# ════════════════════════════════════════════════════════════════════
# 库 (三个函数; 测试里换成假的)
# ════════════════════════════════════════════════════════════════════

class SupabaseStore:
    """生产用: 走 PostgREST 调 v1.28 的三个函数。别的表一概不碰。"""

    def __init__(self, sb):
        self.sb = sb

    def _rpc(self, name: str, args: dict):
        return self.sb.schema("truth_vault").rpc(name, args).execute().data

    def sync_bank(self, bank: dict) -> None:
        self._rpc("sync_first_image_bank", {
            "p_bank_version": bank["bank_version"], "p_bank_sha256": bank["_sha256"],
            "p_confirmed": list(bank.get("cover_confirmed_projects") or []),
            "p_excluded": list(bank.get("excluded_projects") or []),
            "p_surfaced": surfaced_questions(bank)})

    def candidates(self, bank: dict, cards_only: bool, limit: int) -> list[dict]:
        return list(self._rpc("first_image_candidates", {
            "p_bank_version": bank["bank_version"], "p_new_since": NEW_SINCE,
            "p_excluded": list(bank.get("excluded_projects") or []),
            "p_cards_only": bool(cards_only), "p_limit": int(limit)}) or [])

    def write(self, state: dict, rows: list[dict]) -> str:
        out = self._rpc("write_first_image_result", {"p_state": state, "p_rows": rows})
        return out if isinstance(out, str) else "written"


def is_missing_migration(exc: BaseException) -> bool:
    from _common import is_missing_db_object
    return is_missing_db_object(exc)


# ════════════════════════════════════════════════════════════════════
# 默认的两个外部动作 (测试里全换成假的)
# ════════════════════════════════════════════════════════════════════

def default_ask(model: str, prompt: str, block: tuple[str, str]) -> tuple[str, Optional[dict], Optional[str]]:
    """调一次模型 (仓里现成的 call_claude)。一次预留对一个真发出去的请求: 只试一次 (max_attempts=1)、SDK 自带的重试关掉
    (sdk_max_retries=0)、只走主中转站 —— 配了备用站又没把 RELAY_FORCE 定成 primary 时, call_claude 一次会发两个请求
    (主站一个、备用站一个), 第二个不在账上, 所以那种配置下这里一个请求都不发。main() 开头自己把 RELAY_FORCE 定成 primary。"""
    guard_model(model)
    import relay_failover
    if relay_failover.mode() != relay_failover.MODE_PRIMARY_ONLY:
        raise PassConfigError("首图步骤只走主中转站 (RELAY_FORCE 要是 primary)")
    from annotate_essence_pass import call_claude
    meta: dict = {}
    text = call_claude(prompt, model, max_attempts=1, max_tokens=FI.MAX_OUTPUT_TOKENS, meta=meta, images=[block],
                       sdk_max_retries=0)
    return text, meta.get("usage"), FI.stop_word(meta.get("stop_reason"))   # 第三项只会是写死的词 (或 None)


def default_downloader() -> Callable[[dict], bytes]:
    import feishu_media
    from sync_feishu_notes_to_truth_vault import FeishuClient
    client = FeishuClient(os.environ["FEISHU_APP_ID"], os.environ["FEISHU_APP_SECRET"])
    return lambda f: feishu_media.download(client, f, FI.MAX_INPUT_BYTES)


def _status_of(exc: BaseException) -> str:
    """异常 → 状态词: 只有类名和 HTTP 状态码, 报错正文一个字都不带。"""
    st = getattr(exc, "status", None)
    if isinstance(st, str) and st.replace("_", "").isalnum() and len(st) <= 40:
        return st
    code = getattr(exc, "status_code", None)
    return f"{type(exc).__name__}" + (f":{int(code)}" if isinstance(code, int) else "")


# ════════════════════════════════════════════════════════════════════
# 答案 → 要写的行
# ════════════════════════════════════════════════════════════════════

def answer_rows(bank: dict, note_id: str, result: dict, model: str, only: Optional[tuple] = None) -> list[dict]:
    """assemble 的结果 → note_feature_answers 的行。only: 只写这几道题 (不是封面时只写 img_kind)。"""
    rows = []
    for q in bank.get("questions") or []:
        qid = q["id"]
        if only is not None and qid not in only:
            continue
        answer = result["answers"].get(qid)
        why = None if answer is not None else (result["invalid"].get(qid) or (INVALID_SOURCE if q["type"] == "code"
                                                                             else FI.INVALID_MISSING))
        rows.append({"subject_type": "note", "subject_id": note_id, "question_id": qid,
                     "question_version": int(q["version"]), "bank_version": bank["bank_version"],
                     "bank_sha256": bank["_sha256"],
                     "extractor": CODE_EXTRACTOR if q["type"] == "code" else f"llm:{model}",
                     "run_tag": RUN_TAG, "answer": answer, "invalid_reason": why})
    return rows


# ════════════════════════════════════════════════════════════════════
# 这一趟
# ════════════════════════════════════════════════════════════════════

class Pass:
    def __init__(self, *, bank: dict, store: Any, budget: PassBudget, download: Callable[[dict], bytes],
                 shrinker: Callable[..., dict], ask: Callable[[str, str, tuple], tuple],
                 workers: int = DEFAULT_WORKERS, deadline: Optional[float] = None,
                 clock: Callable[[], float] = time.monotonic):
        self.bank, self.store, self.budget = bank, store, budget
        self.download, self.shrinker, self.ask = download, shrinker, ask
        self.workers, self.deadline, self.clock = max(1, min(4, int(workers))), deadline, clock
        self.model = cheap_model()
        self.units = call_units(bank)
        self.confirmed = set(bank.get("cover_confirmed_projects") or [])
        self.excluded = set(bank.get("excluded_projects") or [])
        self.lock = threading.Lock()
        self.status: Counter = Counter()          # 状态词 → 篇数 (写进库的那个 status)
        self.written: Counter = Counter()         # final / retry / quarantined
        self.detail: Counter = Counter()          # 下载 / 解图 / 模型失败的状态词
        self.flags: Counter = Counter()
        # 下面三个只是计数 (11-16 首跑 32 张里 11 张没答成, 当时看不出为什么): 键全是写死的词和题号, 不带回包里的字
        self.no_answer_why: Counter = Counter()   # 没答成的帖 → first_call:<词> / round:<自检规则名>[:细项]
        self.invalid_q: Counter = Counter()       # 题号:<词> → 多少次调用里这道题无效 (含后来答成了的帖)
        self.reply: Counter = Counter()           # 回包: stop:max_tokens / stop:other
        self.would_read: Counter = Counter()      # 假如放宽 (没有放宽): answers:<词> 无效的答案数 / replies:loose_json 回包数
        self._note: dict[str, str] = {}           # 当前这张图各题细一层的词 (图和图之间不并, 一张图内各次调用的题不重)
        self.ended: Optional[str] = None
        self.calls_ok = 0
        self.fail_streak = 0
        self.downloads_ok = 0
        self.head_refused = {"feishu": 0, "relay": 0}   # 这一趟还没有一张图下载成 / 一次调用答成之前, 被拒的帖数

    # ── 一次模型调用: 核模型 → 预留 → 调 → 结算; 失败重试一次, 每次都先过预算 ──
    def _call(self, qids: list[str], jpeg: bytes, size: tuple[int, int]) -> dict[str, tuple]:
        prompt = FI.build_prompt(self.bank, qids)
        est = FI.call_estimate(prompt, [size])
        for _attempt in range(2):
            guard_model(self.model)                               # 不是便宜档 → 抛, 一个请求都不发
            if self.ended or not self.budget.reserve(est):
                return {q: (None, FI.INVALID_BUDGET) for q in qids}
            try:
                text, usage, *more = self.ask(self.model, prompt, FI.as_block(jpeg))
            except PassConfigError:                               # 配置不对 (模型 / 中转站): 不是这张图的事, 整趟停
                self.budget.release(est, self.model)
                raise
            except Exception as exc:  # noqa: BLE001
                self.budget.release(est, self.model)
                with self.lock:
                    self.detail["model:" + _status_of(exc)] += 1
                    self.fail_streak += 1
                    if self.fail_streak >= MAX_CONSECUTIVE_API_FAILS and not self.ended:
                        self.ended = "relay_failing"
                continue
            self.budget.settle(est, self.model, usage)
            with self.lock:
                self.calls_ok += 1
                self.fail_streak = 0
            stop = FI.stop_word(more[0]) if more else None
            read = FI.read_reply(self.bank, qids, text or "", stop)
            with self.lock:
                if stop and stop != "end_turn":
                    self.reply["stop:" + stop] += 1
                for word in read["would_read"].values():
                    self.would_read["answers:" + word] += 1
                if any(w.startswith(FI.WOULD_LOOSE) for w in read["would_read"].values()):
                    self.would_read["replies:" + FI.WOULD_LOOSE] += 1   # 真有一个答案靠它才读得出的回包才数
                for q, word in read["notes"].items():
                    self.invalid_q[f"{q}:{word}"] += 1
                    self._note[q] = word
            return read["parsed"]                                 # = FI.parse_answers(...) 原样; notes / would_read 只进了计数
        return {q: (None, FI.INVALID_API) for q in qids}

    def _void_why(self, res: dict, parsed: dict) -> str:
        """整轮作废的那一篇: 是哪条自检规则 (规则名是题库文件里的, 仓里本来就有), 再加一个写死的细项。"""
        why = next((w for w in res["invalid"].values() if str(w).startswith("inconsistent:")), "")
        name = why.split(":", 1)[-1]
        rule = next((r for r in self.bank.get("consistency") or [] if r.get("name") == name), None)
        if not rule or not re.fullmatch(r"[a-z0-9_]{1,40}", name):
            return "round:other"
        text = (parsed.get(rule.get("then_empty") or rule.get("then_not_empty") or "") or (None, None))[0]
        if rule.get("then_empty") and isinstance(text, str):
            # 说了「没有字」又抄出了字: 抄出来的是一句「没有」的话, 还是真的字 (只比这几个写死的说法, 字本身不往外带)
            said_none = FI.normalise(text) in _NONE_WORDS
            return f"round:{name}:" + ("said_none_in_words" if said_none else "transcribed_text")
        if rule.get("then_not_empty") and isinstance(text, str):
            return f"round:{name}:" + ("symbols_only" if text.strip() else "empty_text")
        return f"round:{name}"

    def _state(self, cand: dict, status: str, outcome: str, *, size: Optional[tuple] = None,
               asked: bool = False) -> dict:
        f = cand["first_file"]
        return {"note_id": cand["note_id"], "project_id": cand["project_id"], "source_column": cand["source_column"],
                "file_sha": cand["file_sha"], "n_files": int(cand["n_files"]), "file_kind": FI.file_kind(f),
                "file_bytes": FI.file_size(f) or None, "width": size[0] if size else None,
                "height": size[1] if size else None, "status": status, "outcome": outcome,
                "bank_version": self.bank["bank_version"], "bank_sha256": self.bank["_sha256"],
                "model": self.model if asked else None}

    def _write(self, cand: dict, status: str, outcome: str, rows: Optional[list] = None, **kw) -> bool:
        """回「写进去了没有」。没写进去的帖不进任何按帖数的计数 (status / no_answer_why)。"""
        try:
            res = self.store.write(self._state(cand, status, outcome, **kw), rows or [])
        except Exception as exc:  # noqa: BLE001 — 写不进去就停: 不接着为存不下来的结果花钱
            self.ended = "migration_missing" if is_missing_migration(exc) else "write_failed"
            self.detail["write:" + type(exc).__name__] += 1
            return False
        self.status[status] += 1
        self.written[res if res in ("final", "retry", "quarantined") else "written"] += 1
        if status == "answered":
            multi = int(cand["n_files"]) > 1 and cand["project_id"] not in self.confirmed
            self.flags["cover_unconfirmed" if multi else "usable"] += 1
        return True

    def _process(self, cand: dict) -> None:
        f = cand.get("first_file") or {}
        if cand.get("project_id") in self.excluded:               # 库里那道筛之外再守一道
            self.detail["skipped_excluded_project"] += 1
            return
        if FI.file_kind(f) == "video":
            self._write(cand, "first_is_video", FINAL)            # 不下载、不调模型
            return
        if FI.file_size(f) > FI.MAX_INPUT_BYTES:
            self._write(cand, "too_large", FINAL)
            return
        # 这张图全部调用的预留: 图片大小还不知道, 按长边 1,024 的方图算 (只会多留)
        est_total = sum(FI.call_estimate(FI.build_prompt(self.bank, u), [(FI.LONG_SIDE, FI.LONG_SIDE)]) for u in self.units)
        if not self.budget.take_image(est_total):
            return
        try:
            data = self.download(f)
        except Exception as exc:  # noqa: BLE001
            st = _status_of(exc)
            self.detail["download:" + st] += 1
            if st == "too_large":
                self._write(cand, "too_large", FINAL)
            elif st in ("auth_failed", "no_permission") and self.downloads_ok == 0:
                # 这一趟还没有一张图下载成: 分不清是这一个文件的事 (飞书对单个文件也回 400 / 403) 还是凭证的事。
                # 先给这一篇记一笔不算数的失败 —— 不记的话它明晚还排第一, 整趟永远卡在它身上 —— 再试下一篇;
                # 连着两篇不同的帖都被拒, 才当成凭证 / 权限的问题停。
                self._write(cand, "download_failed", INFRA)
                self.head_refused["feishu"] += 1
                if self.head_refused["feishu"] >= HEAD_REFUSALS_TO_STOP and not self.ended:
                    self.ended = "feishu_refused"
            else:
                self._write(cand, "download_failed", INFRA if st == "network" else COUNTED)
            return
        self.downloads_ok += 1
        try:
            shr = self.shrinker(data, (FI.LONG_SIDE,), FI.decode_as(f))
        except Exception as exc:  # noqa: BLE001
            self.detail["decode:" + _status_of(exc)] += 1
            self._write(cand, "decode_failed", FINAL)
            return
        finally:
            del data
        jpeg, w, h = shr["images"][FI.LONG_SIDE]
        del shr
        size = (w, h)
        self._note = {}

        parsed = self._call(self.units[0], jpeg, size)
        kind, why = parsed.get("img_kind", (None, FI.INVALID_MISSING))
        if why in (FI.INVALID_BUDGET, FI.INVALID_API):
            if why == FI.INVALID_API and not self.ended:          # 这一趟已经判了「中转站坏了」的, 不往这一篇头上记
                # 记一笔不算数的失败 (不记的话这一篇明晚还排第一, 每晚白花两次调用)。这一趟还没有一次调用答成、
                # 又连着两篇不同的帖都这样, 才当成中转站不收图片, 停。
                self._write(cand, "model_failed", INFRA, size=size, asked=True)
                if self.calls_ok == 0:
                    self.head_refused["relay"] += 1
                    if self.head_refused["relay"] >= HEAD_REFUSALS_TO_STOP and not self.ended:
                        self.ended = "relay_refused"
            return
        if kind is None:
            word = "first_call:" + self._note.get("img_kind", why or FI.INVALID_MISSING)
            if self._write(cand, "no_answer", COUNTED, size=size, asked=True):
                self.no_answer_why[word] += 1                     # 写进去了才数: 这一行的数加起来等于 no_answer 的篇数
            return
        if kind != FI.COVER:
            res = FI.assemble(self.bank, {"img_kind": parsed["img_kind"]}, None)
            self._write(cand, "not_a_cover", FINAL, answer_rows(self.bank, cand["note_id"], res, self.model, ("img_kind",)),
                        size=size, asked=True)
            return
        rest = self.units[1:]
        if rest:
            with ThreadPoolExecutor(max_workers=min(self.workers, len(rest))) as pool:
                for part in pool.map(lambda u: self._call(u, jpeg, size), rest):
                    parsed.update(part)
        reasons = {why for _v, why in parsed.values()}
        if FI.INVALID_BUDGET in reasons:
            return                                                # 到了上限: 这一篇不写, 下一晚重做
        if FI.INVALID_API in reasons:
            if not self.ended:
                self._write(cand, "model_failed", INFRA, size=size, asked=True)
            return
        res = FI.assemble(self.bank, parsed, cand.get("title") or "")
        if res["answers"].get("img_kind") != FI.COVER:            # 自相矛盾, 整轮作废
            if self._write(cand, "no_answer", COUNTED, size=size, asked=True):
                self.no_answer_why[self._void_why(res, parsed)] += 1
            return
        for qid in FI.code_question_ids(self.bank):               # 代码题没算成的 (没有标题 / 那句大字没抄成)
            if qid not in res["answers"]:
                self.invalid_q[f"{qid}:{res['invalid'].get(qid) or INVALID_SOURCE}"] += 1
        self._write(cand, "answered", FINAL, answer_rows(self.bank, cand["note_id"], res, self.model), size=size, asked=True)

    def _should_stop(self) -> bool:
        if self.ended:
            return True
        if self.budget.stopped:
            self.ended = "cap_" + self.budget.stopped
            return True
        if self.deadline is not None and self.clock() > self.deadline:
            self.ended = "time_limit"
            return True
        return False

    def run(self, candidates: list[dict]) -> None:
        for cand in candidates:
            if self._should_stop():
                break
            self._process(cand)
        self._should_stop()
        if not self.ended:
            self.ended = "done"


def run_pass(*, bank: dict, store: Any, mode: str = "nightly", dry_run: bool = False,
             max_weighted: Optional[int] = None, max_images: Optional[int] = None,
             download=None, shrinker=None, ask=None, workers: int = DEFAULT_WORKERS,
             deadline: Optional[float] = None, clock: Callable[[], float] = time.monotonic) -> dict:
    """回一个只有计数和状态词的结果。迁移没跑 → ended = migration_missing, 一个外部动作都没有。"""
    errs = validate_bank(bank)
    if errs:
        raise PassConfigError("题库不合法: " + "; ".join(errs))
    budget = PassBudget(mode, len(call_units(bank)), max_weighted=max_weighted, max_images=max_images)
    res: dict[str, Any] = {
        "mode": mode, "dry_run": dry_run, "bank_version": bank["bank_version"], "bank_sha": bank["_sha256"],
        "model": cheap_model(), "calls_per_image": len(call_units(bank)),
        "caps": {"images": budget.max_images, "weighted": budget.max_weighted, "calls": budget.max_calls,
                 "yuan": MP.yuan_of_weighted(cheap_model(), budget.max_weighted)},
        "candidates": None, "ended": None, "status": {}, "written": {}, "detail": {}, "flags": {},
        "no_answer_why": {}, "invalid_by_question": {}, "reply": {}, "would_read": {},
        "budget": {"images": 0, "calls": 0, "spent": 0, "usage_missing": 0, "yuan": 0.0}}
    try:
        store.sync_bank(bank)                                      # 名单的镜像 (干跑也同步: 不花钱); 也是「迁移跑没跑」的探针
        cands = store.candidates(bank, mode == "cards", budget.max_images * 2)
    except Exception as exc:  # noqa: BLE001
        res["ended"] = "migration_missing" if is_missing_migration(exc) else "db_unavailable"
        res["detail"] = {"db:" + type(exc).__name__: 1}
        return res
    res["candidates"] = len(cands)
    if dry_run:
        res["ended"] = "dry_run"
        return res
    p = Pass(bank=bank, store=store, budget=budget, download=download, shrinker=shrinker, ask=ask,
             workers=workers, deadline=deadline, clock=clock)
    p.run(cands)
    res.update({"ended": p.ended, "status": dict(p.status), "written": dict(p.written), "detail": dict(p.detail),
                "flags": dict(p.flags), "no_answer_why": dict(p.no_answer_why),
                "invalid_by_question": dict(p.invalid_q), "reply": dict(p.reply), "would_read": dict(p.would_read)})
    spent_yuan = MP.yuan_of_weighted(cheap_model(), budget.spent)
    res["budget"] = {"images": budget.images, "calls": budget.calls, "spent": budget.spent,
                     "usage_missing": budget.usage_missing, "yuan": spent_yuan}
    return res


_ENDED_ZH = {
    "done": "做完了这一晚该做的",
    "dry_run": "干跑：没下载、没调模型、没写结果（名单同步了）",
    "migration_missing": "迁移 schemas/notes_v1_28_first_image.sql 还没跑：这一步什么都没做，没花钱",
    "db_unavailable": "读不到库：这一步什么都没做，没花钱",
    "cap_max_images": "到了图片数上限，剩下的下一晚接着做",
    "cap_max_tokens": "到了 token 上限，剩下的下一晚接着做",
    "cap_max_calls": "到了调用次数上限，剩下的下一晚接着做",
    "time_limit": "到了时间上限，剩下的下一晚接着做",
    "feishu_refused": "开头连着两篇帖的图飞书都不给下载（凭证或素材下载权限）：停了，没调模型；这两篇各记了一次不算数的失败",
    "relay_refused": "开头连着两张图中转站都没答成：停了；这两篇各记了一次不算数的失败",
    "relay_failing": "模型调用连着失败：停了",
    "write_failed": "结果写不进库：停了",
}


def summary(res: dict) -> str:
    """给日志和 run 摘要的几行字: 只有计数和状态词。"""
    c = res["caps"]
    lines = [f"首图步骤 · mode={res['mode']} · 题库 {res['bank_version']} · 模型 {res['model']}（只许这一个）",
             f"上限：{c['images']} 张图 / {c['weighted']:,} 输入当量 token（约 {c['yuan']:.2f} 元）/ {c['calls']} 次调用；"
             f"{MP.ASSUMED_NOTE}",
             f"结束方式：{res['ended']}（{_ENDED_ZH.get(res['ended'], '见状态词')}）"]
    if res["candidates"] is not None:
        lines.append(f"这一晚要做的帖：{res['candidates']} 篇（取到上限的两倍为止）")
    if res["dry_run"] or res["ended"] in ("migration_missing", "db_unavailable"):
        return "\n".join(lines) + "\n"
    b = res["budget"]
    lines.append(f"实际：问了 {b['images']} 张图，调用 {b['calls']} 次，{b['spent']:,} 输入当量 token，约 {b['yuan']:.3f} 元；"
                 f"没拿到用量、按预留记的 {b['usage_missing']} 次")
    for title, key in (("写进库的结果", "status"), ("其中", "flags"), ("之后", "written"), ("失败的状态词", "detail"),
                       ("没答成（no_answer）的原因", "no_answer_why"), ("逐题无效（题号:原因=调用次数）", "invalid_by_question"),
                       ("回包", "reply"), ("假如放宽读法会多读出（没有放宽，这些答案照旧无效）", "would_read")):
        if res.get(key):
            lines.append(f"{title}：" + "，".join(f"{k}={v}" for k, v in sorted(res[key].items())))
    return "\n".join(lines) + "\n"


# ════════════════════════════════════════════════════════════════════
# 命令行
# ════════════════════════════════════════════════════════════════════

def preflight(dry_run: bool, env=os.environ) -> list[str]:
    """缺什么点名 (只点名字)。空 = 可以跑。"""
    problems: list[str] = []
    names = REQUIRED_ENV[:2] if dry_run else REQUIRED_ENV
    for name in names:
        if not (env.get(name) or "").strip():
            problems.append(f"没配 {name}")
    if not dry_run:
        lib = FI.image_libs_ready()
        if lib:
            problems.append(f"没装 {lib}")
    return problems


def sync_lists_only(bank: dict, env=os.environ) -> str:
    """真跑不了的时候 (便宜档配置被拒 / 缺钥匙 / 没装图片库) 也把题库里的三张名单同步进库: 不下载、不调模型、不花钱。
    不同步的话, 这段时间里改的「先不做的项目」「确认过封面的项目」到不了读的那一面。回一个状态词。"""
    if any(not (env.get(name) or "").strip() for name in REQUIRED_ENV[:2]):
        return "no_db_env"
    try:
        from _common import get_supabase_client
        SupabaseStore(get_supabase_client()).sync_bank(bank)
        return "synced"
    except Exception as exc:  # noqa: BLE001
        return "migration_missing" if is_missing_migration(exc) else "failed"


_LISTS_ZH = {"synced": "名单已同步进库", "no_db_env": "没配库的环境变量, 名单没同步", "failed": "名单没同步成",
             "migration_missing": "迁移还没跑, 没有名单可同步"}


def _quiet_logs() -> None:
    import logging
    for noisy in ("httpx", "httpcore", "anthropic", "urllib3", "postgrest"):
        logging.getLogger(noisy).setLevel(logging.WARNING)         # 这几个库在 INFO 级会把请求地址打出来


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="每晚的首图步骤 (只用便宜档; 有图片数和 token 两道硬上限; 打出来的只有计数)")
    ap.add_argument("--mode", choices=sorted(MODES), default="nightly")
    ap.add_argument("--max-images", type=int, default=0, help="只能比写死的上限低; 0 = 用写死的")
    ap.add_argument("--max-tokens", type=int, default=0, help="输入当量 token, 只能比写死的上限低; 0 = 用写死的")
    ap.add_argument("--max-minutes", type=int, default=DEFAULT_MAX_MINUTES)
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--strict", action="store_true", help="没做成时给非 0 的退出码 (默认永远 0: 不拦夜跑)")
    args = ap.parse_args(argv)
    bad = 2 if args.strict else 0
    os.environ["RELAY_FORCE"] = "primary"      # 只走主中转站: 一次预留对一个请求 (见 default_ask)
    _quiet_logs()
    if args.max_images < 0 or args.max_tokens < 0 or not 1 <= args.workers <= 4 or args.max_minutes <= 0:
        say("首图步骤: 参数不对 (max-images ≥ 0, max-tokens ≥ 0, workers 1–4, max-minutes > 0), 什么都没做")
        return bad
    try:
        bank = load_bank()
        errs = validate_bank(bank)
        if errs:
            say("首图步骤: 题库不合法, 什么都没做:\n  - " + "\n  - ".join(errs))
            return bad
    except PassConfigError as exc:
        say(f"首图步骤: {exc}, 什么都没做")
        return bad
    except Exception as exc:  # noqa: BLE001
        say(f"首图步骤: 读题库出错 ({type(exc).__name__}), 什么都没做")
        return bad
    try:
        c = caps(args.mode)
    except PassConfigError as exc:
        say(f"首图步骤: {exc}, 没下载、没调模型、没花钱; {_LISTS_ZH[sync_lists_only(bank)]}")
        return bad
    problems = preflight(args.dry_run)
    if problems:
        if args.dry_run:
            say(f"首图步骤（干跑, 没连库）: 上限 {c['images']} 张图 / {c['weighted']:,} 输入当量 token（约 {c['weighted_yuan']:.2f} 元, "
                f"{MP.ASSUMED_NOTE}）; 每张图最多 {len(call_units(bank))} 次调用; 模型 {cheap_model()}")
            return 0
        say("首图步骤: 开跑前的检查没过, 没下载、没调模型、没花钱:\n  - " + "\n  - ".join(problems)
            + f"\n  {_LISTS_ZH[sync_lists_only(bank)]}")
        return bad
    try:
        from _common import get_supabase_client
        store = SupabaseStore(get_supabase_client())
        kwargs: dict = {}
        if not args.dry_run:
            kwargs = {"download": default_downloader(), "shrinker": FI.shrink, "ask": default_ask}
        res = run_pass(bank=bank, store=store, mode=args.mode, dry_run=args.dry_run,
                       max_weighted=args.max_tokens or None, max_images=args.max_images or None,
                       workers=args.workers, deadline=time.monotonic() + args.max_minutes * 60, **kwargs)
    except Exception as exc:  # noqa: BLE001 — 报错正文可能带地址 / 钥匙 / 原文, 只留类名
        say(f"首图步骤中断: {type(exc).__name__} (正文不打印)")
        return bad
    say(summary(res))
    if res["ended"] in ("done", "dry_run") or res["ended"].startswith("cap_") or res["ended"] == "time_limit":
        return 0
    return 3 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
