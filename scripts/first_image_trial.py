#!/usr/bin/env python3
"""first_image_trial.py —— 首图试跑 (D-157, 2026-11-16; 设计与读法: docs/33-first-image-trial.md)。

只由人手动跑 (.github/workflows/first-image-trial.yml, workflow_dispatch), 没有任何定时。它做的事:
  1. 只读地从库里取每篇的档位、标题和四个附件列, 按设计分层抽样 (常规 48 张 / 难办的文件 12 个 / 封面检查 39 篇 / 列检查 6 篇)
  2. 用夜跑同步的飞书凭证把首图下载到内存, 缩成长边 1,024 的 JPEG (不写盘、不进 artifact)
  3. 每张图每轮调三次模型 (一次一组、一组四题), 每档跑两轮算一致率, 另在 20 张图上逐题单问、在 20 张上换成长边 1,568
  4. 按试跑前写死的线出一份只有计数的报告

不写库: 这个文件里没有任何一次写操作, 答案只在内存里比完就丢。
花费: 每次调用之前查 token 硬上限 (first_image.Budget, 写死在代码里, 命令行只能调低); --dry-run 不下载、不调模型, 只打印要做什么、
      大约花多少。
日志和报告: 只有计数和状态词。图片、标题、封面上的字、文件名、file_token、链接、note_id、中转站地址、报错正文都不出现。

用法:
    cd scripts && python first_image_trial.py --dry-run                      # 不花钱; 有 SUPABASE_* 就按真实样本数算, 没有就按设计数算
    python first_image_trial.py --tier both --max-images 2 --out ../first-image-trial.md    # 冒烟: 每层最多 2 个
    python first_image_trial.py --tier both --out ../first-image-trial.md                   # 正式试跑

退出码: 0 = 跑完 (或干跑); 2 = 开跑前的检查没过 / 第一张图就被飞书或中转站拒了 (没花钱或只花了一两次调用);
        3 = 中途停了 (到了 token 上限 / 调用上限 / 时间上限), 报告照出, 只覆盖跑到的部分。
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
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

DEFAULT_WORKERS = 4
DEFAULT_MAX_MINUTES = 300
MAX_CONSECUTIVE_API_FAILS = 6     # 连着这么多次调用失败就停: 失败的调用收不收钱不知道, 不往坏通道上接着花
SELECT_COLS = ("note_id, project_id, tier, title, c0:raw_extra->内容配图, c1:raw_extra->笔记配图, "
               "c2:raw_extra->图片, c3:raw_extra->笔记截图")
_COL_ALIAS = {"c0": FI.IMAGE_COLUMNS[0], "c1": FI.IMAGE_COLUMNS[1], "c2": FI.IMAGE_COLUMNS[2], "c3": FI.SCREENSHOT_COLUMN}
REQUIRED_ENV = ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "FEISHU_APP_ID", "FEISHU_APP_SECRET", "ANTHROPIC_API_KEY")


def say(msg: str) -> None:
    print(msg, flush=True)


# ════════════════════════════════════════════════════════════════════
# 取数 (只读)
# ════════════════════════════════════════════════════════════════════

def fetch_rows(sb) -> list[dict]:
    """每篇一行: 档位、标题、四个附件列。只 select; 先只取要的四个键, PostgREST 不认这种写法时退回取整个 raw_extra。"""
    from _common import fetch_all_pages
    try:
        raw = fetch_all_pages(sb.schema("truth_vault").table("notes").select(SELECT_COLS), order_by="note_id")
        return [{"note_id": r["note_id"], "project_id": r["project_id"], "tier": r.get("tier"), "title": r.get("title"),
                 "cols": {name: r.get(alias) for alias, name in _COL_ALIAS.items()}} for r in raw]
    except Exception:  # noqa: BLE001
        say("取数: 只取四个键的写法没成, 改成取整个 raw_extra (慢一些)")
    raw = fetch_all_pages(sb.schema("truth_vault").table("notes").select("note_id, project_id, tier, title, raw_extra"),
                          page_size=200, order_by="note_id")
    return [{"note_id": r["note_id"], "project_id": r["project_id"], "tier": r.get("tier"), "title": r.get("title"),
             "cols": {name: (r.get("raw_extra") or {}).get(name) for name in _COL_ALIAS.values()}} for r in raw]


# ════════════════════════════════════════════════════════════════════
# 默认的三个外部动作 (测试里全换成假的)
# ════════════════════════════════════════════════════════════════════

def default_ask(model: str, prompt: str, block: tuple[str, str]) -> tuple[str, Optional[dict]]:
    """调一次模型 (走仓里现成的 call_claude: 主中转站 + D-148 备用站)。回 (文字, 用量)。只试一次, 重试由试跑自己管。
    SDK 自带的重试也关掉 (sdk_max_retries=0): 一次预留对一个发出去的请求; 配了备用站时主站失败会再打备用站一次, 最多两个。"""
    from annotate_essence_pass import call_claude
    meta: dict = {}
    text = call_claude(prompt, model, max_attempts=1, max_tokens=FI.MAX_OUTPUT_TOKENS, meta=meta, images=[block],
                       sdk_max_retries=0)
    return text, meta.get("usage")


def default_downloader() -> Callable[[dict], bytes]:
    import feishu_media
    from sync_feishu_notes_to_truth_vault import FeishuClient
    client = FeishuClient(os.environ["FEISHU_APP_ID"], os.environ["FEISHU_APP_SECRET"])
    return lambda f: feishu_media.download(client, f, FI.MAX_INPUT_BYTES)


def _status_of(exc: BaseException) -> str:
    """异常 → 状态词: 只有类名和 HTTP 状态码。报错正文里可能有地址和请求体, 一个字都不带。"""
    st = getattr(exc, "status", None)
    if isinstance(st, str) and st.replace("_", "").isalnum():
        return st
    code = getattr(exc, "status_code", None)
    return f"{type(exc).__name__}" + (f":{int(code)}" if isinstance(code, int) else "")


# ════════════════════════════════════════════════════════════════════
# 试跑
# ════════════════════════════════════════════════════════════════════

class Trial:
    def __init__(self, *, bank: dict, tier: str, cap: Optional[int], sample: dict, budget: FI.Budget,
                 download: Callable[[dict], bytes], shrinker: Callable[..., dict],
                 ask: Callable[[str, str, tuple], tuple], workers: int = DEFAULT_WORKERS,
                 deadline: Optional[float] = None, clock: Callable[[], float] = time.monotonic):
        self.bank, self.tier, self.cap, self.sample, self.budget = bank, tier, cap, sample, budget
        self.download, self.shrinker, self.ask = download, shrinker, ask
        self.workers, self.deadline, self.clock = max(1, workers), deadline, clock
        self.plan = FI.run_plan(tier)
        self.groups = [list(v) for v in bank["call_groups"].values()]
        self.model_qids = FI.model_question_ids(bank)
        self.images = sample["regular"] + sample["awkward"]
        self.n_subset = min(FI.SUBSET_N, len(sample["regular"]))
        self.lock = threading.Lock()
        self.results: dict[str, dict] = {r["tag"]: {} for r in self.plan}
        self.status: dict[int, str] = {}
        self.dl = {"ok": 0, "failed": 0, "by_status": Counter(), "seconds": [], "bytes": 0}
        self.pixels: Counter = Counter()
        self.call_seconds: list[float] = []
        self.api_fail: Counter = Counter()
        self.per_tag = {r["tag"]: {"input": 0, "output": 0, "images": 0} for r in self.plan}
        self.ended: Optional[str] = None
        self.done = 0
        self.calls_ok = 0
        self.fail_streak = 0

    # ── 一次模型调用 (预留 → 调 → 结算); 失败重试一次, 每次都先过预算 ──
    def _call(self, run: dict, qids: list[str], jpeg: bytes, size: tuple[int, int]) -> dict[str, tuple]:
        prompt = FI.build_prompt(self.bank, qids)
        est = FI.call_estimate(prompt, [size])
        for _attempt in range(2):
            if self.ended or not self.budget.reserve(est):
                return {q: (None, FI.INVALID_BUDGET) for q in qids}
            t0 = self.clock()
            try:
                text, usage = self.ask(run["model"], prompt, FI.as_block(jpeg))
            except Exception as exc:  # noqa: BLE001
                self.budget.release(est, run["model"])
                with self.lock:
                    self.api_fail[_status_of(exc)] += 1
                    self.fail_streak += 1
                    if self.fail_streak >= MAX_CONSECUTIVE_API_FAILS and not self.ended:
                        self.ended = f"模型调用连着失败 {self.fail_streak} 次（" + "，".join(sorted(self.api_fail)) + "）"
                continue
            self.budget.settle(est, run["model"], usage)
            with self.lock:
                self.calls_ok += 1
                self.fail_streak = 0
                self.call_seconds.append(self.clock() - t0)
                t = self.per_tag.setdefault(run["tag"], {"input": 0, "output": 0, "images": 0})
                tin = sum(int(usage.get(k, 0)) for k in ("input", "cache_write", "cache_read")) if usage else 0
                if tin > 0:
                    t["input"] += tin
                    t["output"] += int(usage.get("output", 0))
                else:
                    # 答成了但中转站没回报用量: 这一档每张图花多少就算不出来了, 报告里写「算不出」, 不写成 0
                    t["no_usage"] = t.get("no_usage", 0) + 1
            return FI.parse_answers(self.bank, qids, text or "")
        if self.calls_ok == 0 and not self.ended:
            # 头一次调用连重试都没成: 中转站多半不收图片 (设计 §4 验收表第二行), 就此停, 不往下花
            self.ended = "第一张图中转站就没答成（" + "，".join(sorted(self.api_fail)) + "）：中转站可能不收图片"
        return {q: (None, FI.INVALID_API) for q in qids}

    def _ask_image(self, run: dict, jpeg: bytes, size: tuple[int, int], title: str) -> dict:
        parsed: dict[str, tuple] = {}
        units = self.groups if run["mode"] == "grouped" else [[q] for q in self.model_qids]
        for qids in units:
            parsed.update(self._call(run, qids, jpeg, size))
        return FI.assemble(self.bank, parsed, title)

    def _fetch(self, f: dict, sides: tuple[int, ...]) -> tuple[Optional[dict], str]:
        """下载 + 解图。回 (shrink 的结果 | None, 状态词)。原始字节在这里就丢。"""
        t0 = self.clock()
        try:
            data = self.download(f)
        except Exception as exc:  # noqa: BLE001
            with self.lock:
                self.dl["failed"] += 1
                self.dl["by_status"][_status_of(exc)] += 1
            return None, "download_failed"
        with self.lock:
            self.dl["ok"] += 1
            self.dl["seconds"].append(self.clock() - t0)
            self.dl["bytes"] += len(data)
        try:
            shr = self.shrinker(data, sides, FI.decode_as(f))
        except Exception as exc:  # noqa: BLE001
            with self.lock:
                self.dl["by_status"][_status_of(exc)] += 1
            return None, "decode_failed"
        finally:
            del data
        with self.lock:
            self.pixels[FI.pixel_bucket(shr["pixels"])] += 1
        return shr, "ok"

    def _process(self, i: int) -> None:
        if self._should_stop():
            return
        item = self.images[i]
        f = item["file"]
        if FI.file_kind(f) == "video":
            self.status[i] = "first_is_video"            # 不下载、不调模型
            return
        in_subset = item["stratum"] == "regular" and i < self.n_subset
        sides = (FI.LONG_SIDE, FI.LONG_SIDE_BIG) if in_subset else (FI.LONG_SIDE,)
        shr, st = self._fetch(f, sides)
        self.status[i] = st
        if shr is None:
            return
        for run in self.plan:
            if run["subset"] and not in_subset:
                continue
            jpeg, w, h = shr["images"][run["long_side"]]
            res = self._ask_image(run, jpeg, (w, h), item["title"])
            with self.lock:
                self.results[run["tag"]][str(i)] = res
                self.per_tag[run["tag"]]["images"] += 1
        with self.lock:
            self.done += 1
            if self.done % 10 == 0:
                say(f"进度: {self.done} 张图问完 · 调用 {self.budget.calls} 次 · {self.budget.spent:,} 输入当量 token")

    def _should_stop(self) -> bool:
        if self.ended:
            return True
        if self.budget.stopped:
            self.ended = f"到了硬上限（{self.budget.stopped}）"
            return True
        if self.deadline is not None and self.clock() > self.deadline:
            self.ended = "到了时间上限"
            return True
        return False

    def run(self) -> None:
        # 第一张能问的图先单独走一遍: 飞书不给下载、或中转站不收图片, 就在这里停, 不往下花钱 (设计 §4 验收表头两行)
        first = next((i for i, it in enumerate(self.images) if FI.file_kind(it["file"]) != "video"), None)
        if first is not None:
            self._process(first)
            if self.status.get(first) == "download_failed" and \
                    (self.dl["by_status"].keys() & {"auth_failed", "no_permission"}):
                self.ended = "第一张图飞书就不给下载（" + "，".join(sorted(self.dl["by_status"])) + "）：查应用的素材下载权限"
                return
            if self.ended:
                return
        rest = [i for i in range(len(self.images)) if i != first]
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            list(pool.map(self._process, rest))
        self._should_stop()
        self.column = self._column_check()
        self.cover = self._cover_check()
        # 最后两步自己也会撞上限 (列核对的最后一次调用把预算用完、封面核对撞时间上限): 再看一遍, 没查完的不记成「跑完」
        self._should_stop()
        if not self.ended:
            self.ended = "跑完"

    def _column_check(self) -> dict:
        ok = posts = 0
        run = dict(self.plan[0], tag="img-g1-column")
        for it in self.sample["column_check"]:
            if self._should_stop():
                break
            posts += 1
            answers = []
            for f in (it["own"], it["shot"]):
                shr, _st = self._fetch(f, (FI.LONG_SIDE,))
                if shr is None:
                    answers.append(None)
                    continue
                jpeg, w, h = shr["images"][FI.LONG_SIDE]
                answers.append(self._call(run, ["img_kind"], jpeg, (w, h))["img_kind"][0])
            if answers[0] == FI.COVER and answers[1] not in (None, FI.COVER):
                ok += 1
        return {"posts": posts, "ok": ok}

    def _cover_check(self) -> dict:
        confirmed = set(self.bank.get("cover_confirmed_projects") or [])
        out: dict[str, dict] = {}
        for it in self.sample["cover_check"]:
            if self._should_stop():
                break
            c = out.setdefault(it["project_id"], {"n": 0, "ok": 0, "cover_unconfirmed": it["project_id"] not in confirmed})
            c["n"] += 1
            shr, _st = self._fetch(it["file"], (FI.LONG_SIDE,))
            c["ok"] += 1 if shr is not None else 0
        return out


def _plan_block(bank: dict, plan: list[dict], sample: dict) -> dict:
    n_images = len([x for x in sample["regular"] + sample["awkward"] if FI.file_kind(x["file"]) != "video"])
    n_subset = min(FI.SUBSET_N, len(sample["regular"]))
    n_col = 2 * len(sample["column_check"])
    return {"runs": plan, "calls": FI.planned_calls(bank, plan, n_images, n_subset, n_col),
            "paper": FI.paper_estimate(bank, plan, n_images, n_subset, n_col)}


def _sample_block(sample: dict) -> dict:
    return {"regular": len(sample["regular"]), "awkward": len(sample["awkward"]),
            "cover_check": len(sample["cover_check"]),
            "cover_check_projects": len({x["project_id"] for x in sample["cover_check"]}),
            "column_check": len(sample["column_check"]), "available": sample["available"]}


def design_sample() -> dict:
    """没连库的干跑: 按设计的篇数摆一个只有数量的样本 (附件是占位, 永远不会被下载)。"""
    ph = {"file_token": "placeholder", "type": "image/jpeg", "size": 0}
    vid = {"file_token": "placeholder", "type": "video/mp4", "size": 0}
    mk = lambda stratum, proj, f: {"note_id": "", "project_id": proj, "stratum": stratum, "label": "", "column": "",  # noqa: E731
                                   "file": f, "n_files": 1, "title": ""}
    regular = [mk("regular", p, ph) for p in FI.TRIAL_PROJECTS for _ in range(FI.PER_PROJECT_HITS + FI.PER_PROJECT_FLOPS)]
    awkward = [mk(k, "", vid if k == "video" else ph) for k, n in FI.AWKWARD_PLAN for _ in range(n)]
    cover = [mk("cover_check", f"表{i + 1}", ph) for i in range(13) for _ in range(FI.COVER_CHECK_PER_PROJECT)]
    column = [{"note_id": "", "project_id": p, "stratum": "column_check", "own": ph, "shot": ph}
              for p in FI.COLUMN_CHECK_PROJECTS for _ in range(FI.COLUMN_CHECK_PER_PROJECT)]
    return {"regular": regular, "awkward": awkward, "cover_check": cover, "column_check": column,
            "available": {"regular": {"按设计（没连库）": len(regular)}, "awkward": dict(FI.AWKWARD_PLAN),
                          "cover_check_projects": 13, "column_check_projects": 3}}


def apply_cap(sample: dict, cap: Optional[int]) -> dict:
    if cap is None:
        return sample
    out = dict(sample)
    for k in ("regular", "awkward", "cover_check", "column_check"):
        out[k] = sample[k][:cap]
    return out


def run_trial(*, bank: dict, tier: str, cap: Optional[int], dry_run: bool, sample: dict,
              budget: Optional[FI.Budget] = None, download=None, shrinker=None, ask=None,
              workers: int = DEFAULT_WORKERS, deadline: Optional[float] = None,
              clock: Callable[[], float] = time.monotonic) -> dict:
    """回一个只有计数和状态词的结果 (FI.build_report 的输入)。dry_run 时三个外部动作一个都不碰。"""
    budget = budget or FI.Budget()
    plan = FI.run_plan(tier)
    res: dict[str, Any] = {
        "bank_version": bank["bank_version"], "bank_sha": bank["_sha256"], "bank_status": bank["status"],
        "tier": tier, "cap": cap, "dry_run": dry_run, "sample": _sample_block(sample),
        "plan": _plan_block(bank, plan, sample),
        "budget": {"max_weighted": budget.max_weighted, "max_calls": budget.max_calls},
        "ended": "干跑" if dry_run else None,
    }
    if dry_run:
        return res
    t = Trial(bank=bank, tier=tier, cap=cap, sample=sample, budget=budget, download=download, shrinker=shrinker,
              ask=ask, workers=workers, deadline=deadline, clock=clock)
    t.column, t.cover = {"posts": 0, "ok": 0}, {}
    t.run()
    res["ended"] = t.ended
    res["budget"].update({"calls": budget.calls, "spent": budget.spent, "usage_missing": budget.usage_missing,
                          "by_model": budget.by_model, "stopped": budget.stopped})
    res["api_failures"] = dict(t.api_fail)
    res["timing"] = {"n": len(t.call_seconds), "median_s": statistics.median(t.call_seconds) if t.call_seconds else None,
                     "max_s": max(t.call_seconds) if t.call_seconds else None}
    res["download"] = {"ok": t.dl["ok"], "failed": t.dl["failed"], "by_status": dict(t.dl["by_status"]),
                       "median_s": statistics.median(t.dl["seconds"]) if t.dl["seconds"] else None, "bytes": t.dl["bytes"]}
    res["pixels"] = dict(t.pixels)
    model_of = {r["tag"]: r["model"] for r in plan}
    res["per_image"] = {}
    for tag, p in t.per_tag.items():
        if p["images"] and tag in model_of:
            y = None if p.get("no_usage") else MP.yuan(model_of[tag], p["input"], p["output"])
            res["per_image"][tag] = {"images": p["images"], "input": p["input"] / p["images"],
                                     "output": p["output"] / p["images"], "yuan": None if y is None else y / p["images"],
                                     "no_usage": p.get("no_usage", 0)}

    # 可用率: 常规图按参照档第一轮的 img_kind 算
    ref = t.results[plan[0]["tag"]]
    u = Counter()
    awk: dict[str, dict] = {}
    for i, item in enumerate(t.images):
        st = t.status.get(i)
        if item["stratum"] == "regular":
            u["regular_n"] += 1
            r = ref.get(str(i))
            if st == "download_failed":
                u["regular_download_failed"] += 1
            elif st == "decode_failed":
                u["regular_decode_failed"] += 1
            elif r is None or "img_kind" not in r["answers"]:
                u["regular_no_answer"] += 1
            elif r["answers"]["img_kind"] != FI.COVER:
                u["regular_not_cover"] += 1
            else:
                u["regular_ok"] += 1
        else:
            a = awk.setdefault(item["stratum"], {"n": 0, "ok": 0})
            a["n"] += 1
            a["ok"] += 1 if st in ("ok", "first_is_video") else 0
    res["usable"] = {k: u.get(k, 0) for k in ("regular_n", "regular_ok", "regular_download_failed",
                                              "regular_decode_failed", "regular_not_cover", "regular_no_answer")}
    res["usable"]["regular_share"] = (u["regular_ok"] / u["regular_n"]) if u["regular_n"] else None
    res["awkward"] = awk
    res["projected_unusable"] = FI.projected_unusable(u["regular_n"], u["regular_n"] - u["regular_ok"], awk)
    res["column_check"], res["cover_check"] = t.column, t.cover

    tiers: dict[str, dict] = {}
    verdicts: dict[str, dict] = {}
    for tname in (["mid", "cheap"] if tier == "both" else [tier]):
        tags = {r["tag"].rsplit("-", 1)[1]: r["tag"] for r in plan if r["tier"] == tname}
        a, b = t.results[tags["a"]], t.results[tags["b"]]
        same = FI.compare(bank, a, b, need_agree=FI.PASS_SAME_MODEL, need_kappa=FI.PASS_KAPPA)
        single = FI.compare(bank, a, t.results[tags["single"]], need_agree=FI.PASS_GROUPED_VS_SINGLE, need_kappa=None,
                            min_pairs=FI.MIN_PAIRS_SUBSET)
        big = FI.compare(bank, a, t.results[tags["1568"]], need_agree=FI.PASS_SAME_MODEL, need_kappa=None,
                         min_pairs=FI.MIN_PAIRS_SUBSET) if "1568" in tags else None
        v = FI.tier_verdicts(same, single)
        verdicts[tname] = v
        tiers[tname] = {"same": same, "single": single, "big": big, "verdicts": v,
                        "invalid_images": sum(1 for r in a.values() if not r["answers"]),
                        "grey": sum(1 for r in a.values() if r.get("grey"))}
    res["tiers"] = tiers
    cross = None
    if tier == "both":
        cross = FI.compare(bank, t.results["img-g1-a"], t.results["img-g1-haiku-a"],
                           need_agree=FI.PASS_CROSS_TIER, need_kappa=FI.PASS_KAPPA)
    res["cross"] = cross
    res["model_choice"] = FI.model_choice(verdicts.get("mid"), verdicts.get("cheap"), cross)
    return res


# ════════════════════════════════════════════════════════════════════
# 命令行
# ════════════════════════════════════════════════════════════════════

def preflight(tier: str, dry_run: bool, env=os.environ) -> list[str]:
    """正式跑之前先查, 缺什么点名 (只点名字, 不打印值)。空列表 = 可以跑。"""
    problems: list[str] = []
    for model in {FI.TIERS[t] for t in (["mid", "cheap"] if tier == "both" else [tier])}:
        if model not in MP.PRICES:
            problems.append(f"scripts/model_prices.py 里没有 {model} 的标价")
    if dry_run:
        return problems
    for name in REQUIRED_ENV:
        if not (env.get(name) or "").strip():
            problems.append(f"没配 {name}")
    lib = FI.image_libs_ready()
    if lib:
        problems.append(f"没装 {lib} (pip install -r scripts/requirements-first-image.txt)")
    return problems


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="首图试跑 (手动; 不写库; 报告只有计数)")
    ap.add_argument("--tier", choices=("mid", "cheap", "both"), default="both")
    ap.add_argument("--max-images", type=int, default=0, help="每一层最多取几个; 0 = 设计全量 (48 / 12 / 39 / 6)")
    ap.add_argument("--max-tokens", type=int, default=FI.MAX_WEIGHTED_TOKENS,
                    help=f"token 硬上限 (输入当量); 只能比 {FI.MAX_WEIGHTED_TOKENS:,} 低")
    ap.add_argument("--max-minutes", type=int, default=DEFAULT_MAX_MINUTES)
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    if args.max_images < 0 or args.max_tokens <= 0 or not 1 <= args.workers <= 8 or args.max_minutes <= 0:
        say("参数不对: max-images ≥ 0, max-tokens > 0, workers 1–8, max-minutes > 0")
        return 2
    cap = args.max_images or None

    bank = FI.load_bank()
    errs = FI.validate_bank(bank)
    if errs:
        say("题库不合法:\n  - " + "\n  - ".join(errs))
        return 2
    problems = preflight(args.tier, args.dry_run)
    if problems:
        say("开跑前的检查没过, 没有花钱:\n  - " + "\n  - ".join(problems))
        return 2

    have_db = all((os.environ.get(k) or "").strip() for k in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"))
    try:
        if have_db:
            from _common import fetch_vanished_note_ids, get_supabase_client
            sb = get_supabase_client()
            rows = fetch_rows(sb)
            sample = FI.select_sample(rows, fetch_vanished_note_ids(sb), cap)
            say(f"取数: {len(rows)} 篇 (只读)")
            del rows
        else:
            say("没配 SUPABASE_*: 干跑按设计的篇数算, 不是真实样本")
            sample = apply_cap(design_sample(), cap)
        kwargs: dict = {}
        if not args.dry_run:
            kwargs = {"download": default_downloader(), "shrinker": FI.shrink, "ask": default_ask}
            import logging
            for noisy in ("httpx", "httpcore", "anthropic", "urllib3"):
                logging.getLogger(noisy).setLevel(logging.WARNING)    # 这几个库在 INFO 级会把请求地址打出来
        res = run_trial(bank=bank, tier=args.tier, cap=cap, dry_run=args.dry_run, sample=sample,
                        budget=FI.Budget(max_weighted=args.max_tokens), workers=args.workers,
                        deadline=time.monotonic() + args.max_minutes * 60, **kwargs)
    except Exception as exc:  # noqa: BLE001 — 报错正文可能带地址 / 钥匙 / 原文, 只留类名
        say(f"试跑中断: {type(exc).__name__} (正文不打印)")
        return 1
    report = FI.build_report(res)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        Path(args.out).with_suffix(".json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str),
                                                       encoding="utf-8")
    say(report)
    if args.dry_run or res["ended"] == "跑完":
        return 0
    return 2 if str(res["ended"]).startswith("第一张图") else 3


if __name__ == "__main__":
    sys.exit(main())
