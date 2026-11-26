"""scripts/first_image.py — 首图试跑的纯逻辑 (D-157, 2026-11-16; docs/33-first-image-trial.md)。

只用标准库 + pyyaml (Pillow / pillow-heif 只在真要解图时才 import), 不连库、不连网、不调模型:
CI 守卫 (check_first_image.py) 和干跑在裸环境里就能跑。库 I/O、飞书下载、模型调用在 first_image_trial.py / feishu_media.py。

这里住着:
  · 题库的加载和结构校验 (一次调用只问一组、一组 ≤ 4 题: 文字题库那条规矩照搬)
  · 哪一列、哪一个附件算首图 (内容配图 > 笔记配图 > 图片, 取第 0 个); 附件是哪一种 (空类型看文件名)
  · 抽样: 分层 + 按 md5(note_id + 种子) 排序, 同一份数据每次抽到同一批
  · 缩图 (只在内存里): 48 MiB 字节上限、像素上限、转 JPEG、去掉元数据
  · 提示词、答案解析、闭集校验、自相矛盾检查、两道代码题
  · 一致率 / κ / kappa_undefined / 过线判定; 只有计数的报告
  · token 硬上限 (Budget): 每次调用【之前】查, 会越线就不调

隐私 (试跑的硬约束): 这个文件产出的报告和任何一行日志里都没有图片字节、标题、封面上的字、文件名、file_token、
链接、note_id。项目名 (project_id) 本来就在仓库的 mappings/ 里, 可以出现。
"""
from __future__ import annotations

import base64
import difflib
import hashlib
import io
import json
import math
import re
import threading
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from feature_bank import MAX_GROUP_SIZE, bank_digest
from gate1_agreement import agree, kappa
import model_prices as MP

BANK_PATH = Path(__file__).resolve().parent.parent / "prompts" / "first_image_questions_v0_1.yaml"
BANK_VERSION = "fi-v0.1"
RUN_TAG_PREFIX = "img-"

# ── 哪一列算帖子自己的图 (设计 §1.1): 三列里第一个非空的, 取第 0 个附件; 没有一篇同时有两列 ──
IMAGE_COLUMNS = ("内容配图", "笔记配图", "图片")
SCREENSHOT_COLUMN = "笔记截图"                       # RIO / TXQ / WTG 两列都有, 试跑自动核一次 (列检查)
COLUMN_CHECK_PROJECTS = ("RIO_phase1", "TXQ_phase1", "WTG_phase1")
TRIAL_PROJECTS = ("TUGE_phase1", "RIO_phase1", "OKMAN_phase1", "HATHERINE_phase1")   # 有带图的爆帖的四个项目
HIT_TIERS = frozenset({"爆", "大爆"})
FLOP_TIER = "趴"
SEED = "first-image-trial-1"

PER_PROJECT_HITS = 6
PER_PROJECT_FLOPS = 6
AWKWARD_PLAN = (("heic", 4), ("big", 4), ("video", 2), ("empty_type", 2))
COVER_CHECK_PER_PROJECT = 3
COLUMN_CHECK_PER_PROJECT = 2
BIG_BYTES = 20 * 1024 * 1024                         # 「20 MiB 以上」那一层
MAX_INPUT_BYTES = 48 * 1024 * 1024                   # 下载的字节上限 (流式读, 超了就断)
PIXEL_CAP = 120_000_000                              # 暂定: 试跑量过最大的文件之后再定 (设计 §5.2)
LONG_SIDE = 1024
LONG_SIDE_BIG = 1568
SUBSET_N = 20                                        # 大图对比、逐题单问各取前 20 张常规图

# ── 设计 §1.4 里量过的全量计数 (2026-11-16 只读), 只用来把试跑的失败率折算成「全量里用不了的占比」──
BACKFILL_TOTAL = 3514
BACKFILL_VIDEO = 12
BACKFILL_DELETED = 11
BACKFILL_HEIC_OR_EMPTY = 187
BACKFILL_BIG = 30
CARD_POSTS = 45
NIGHTLY_IMAGES = 13.4

# ── 过线标准 (设计 §4, 试跑前写死) ──
PASS_SAME_MODEL = 0.90
PASS_KAPPA = 0.60
PASS_TEXT_MATCH = 0.85
PASS_GROUPED_VS_SINGLE = 0.90
PASS_CROSS_TIER = 0.90
PASS_USABLE = 0.90
PASS_UNUSABLE_PROJECTED = 0.10
LOPSIDED = 0.90                                      # 最常见的答案占到这个比例 → kappa_undefined, 不算过
MIN_PAIRS = 30                                       # 少于这么多对不下结论 (小样本冒烟跑不会「过线」)
MIN_PAIRS_SUBSET = 15
TEXT_RATIO = 0.80
TEXT_GREY = 0.60

# ── 花费硬上限 (代码里写死; 命令行只能调低) ──
MAX_WEIGHTED_TOKENS = 3_800_000                      # 输入当量 token; 全按中档价算约 98.5 元 (假设价), 不到 100
MAX_CALLS = 1_400
MAX_OUTPUT_TOKENS = 1500                             # 一次调用的 max_tokens (小模型默认带思考, 思考也占)
ESTIMATE_MARGIN = 2                                  # 调用前预留: 图片 token 按纸面公式的 2 倍留

TIERS = {"mid": "claude-sonnet-5-5", "cheap": "claude-haiku-5-5"}

INVALID_PARSE = "parse_failed"
INVALID_MISSING = "missing"
INVALID_OOV = "out_of_vocab"
INVALID_TEXT_LONG = "text_too_long"
INVALID_NOT_COVER = "not_a_cover"
INVALID_NO_TITLE = "no_title"
INVALID_API = "api_error"
INVALID_BUDGET = "budget_stop"
COVER = "封面"
NO_TEXT = "没有字"


class FirstImageError(Exception):
    """带一个状态词的错误; 状态词可以进日志, 别的不行。"""

    def __init__(self, status: str):
        super().__init__(status)
        self.status = status


# ════════════════════════════════════════════════════════════════════
# 题库
# ════════════════════════════════════════════════════════════════════

def load_bank(path: Path | str = BANK_PATH) -> dict:
    raw = Path(path).read_bytes()
    bank = yaml.safe_load(raw)
    bank["_sha256"] = bank_digest(raw)
    return bank


def question_index(bank: dict) -> dict[str, dict]:
    return {q["id"]: q for q in bank.get("questions") or []}


def model_question_ids(bank: dict) -> list[str]:
    return [q["id"] for q in bank.get("questions") or [] if q.get("type") in ("choice", "text")]


def code_question_ids(bank: dict) -> list[str]:
    return [q["id"] for q in bank.get("questions") or [] if q.get("type") == "code"]


def option_values(q: dict) -> list[str]:
    return [str(o["value"]) for o in q.get("options") or []]


def validate_bank(bank: dict, version: str = BANK_VERSION) -> list[str]:
    """结构校验。返回错误列表, 空 = 合法。version: 这份文件该是哪一版 (试跑是 fi-v0.1; 每晚的首图步骤传它自己的 BANK_VERSION,
    现在是 fi-v0.3; 它自己那几条名单的校验在 first_image_pass.py)。"""
    errs: list[str] = []
    if bank.get("bank_version") != version:
        errs.append(f"bank_version 要是 {version}")
    if bank.get("role") != "image":
        errs.append("role 要是 image")
    if bank.get("status") not in ("draft", "frozen"):
        errs.append("status 只能是 draft / frozen")
    if bank.get("run_tag_prefix") != RUN_TAG_PREFIX:
        errs.append(f"run_tag_prefix 要是 {RUN_TAG_PREFIX} (run_tag=primary 归文字题库)")
    if not isinstance(bank.get("cover_confirmed_projects"), list):
        errs.append("cover_confirmed_projects 要是列表 (可以空)")
    qs = bank.get("questions") or []
    ids = [q.get("id") for q in qs]
    if len(ids) != len(set(ids)):
        errs.append("题号有重复")
    for q in qs:
        qid = str(q.get("id") or "")
        if not re.fullmatch(r"img_[a-z0-9_]{2,40}", qid):
            errs.append(f"题号 {qid!r} 要以 img_ 开头")
        if q.get("type") not in ("choice", "text", "code"):
            errs.append(f"{qid}: type 只能是 choice / text / code")
        if not isinstance(q.get("version"), int):
            errs.append(f"{qid}: 缺 version")
        if q.get("type") in ("choice", "code"):
            vals = option_values(q)
            if len(vals) < 2 or len(vals) != len(set(vals)):
                errs.append(f"{qid}: 闭集至少两个取值且不重复")
        if q.get("type") == "text" and not isinstance(q.get("max_chars"), int):
            errs.append(f"{qid}: text 题要写 max_chars")
    groups = bank.get("call_groups") or {}
    seen: list[str] = []
    for name, members in groups.items():
        members = list(members or [])
        if not 1 <= len(members) <= MAX_GROUP_SIZE:
            errs.append(f"调用组 {name} 有 {len(members)} 题, 一组最多 {MAX_GROUP_SIZE} 题 (docs/28 §5.3)")
        seen.extend(members)
    if len(seen) != len(set(seen)):
        errs.append("同一道题出现在两个调用组里")
    if set(seen) != set(model_question_ids(bank)):
        errs.append("调用组里的题和模型题对不上 (每道模型题恰好在一组里, 代码题不进组)")
    idx = question_index(bank)
    for q in qs:
        if q.get("type") != "code" and q.get("group") and q["id"] not in (groups.get(q["group"]) or []):
            errs.append(f"{q['id']}: group 写的是 {q['group']}, 调用组里没有它")
    for rule in bank.get("consistency") or []:
        refs = list((rule.get("if") or {}).keys()) + list((rule.get("then_not") or {}).keys())
        refs += [rule[k] for k in ("then_empty", "then_not_empty") if rule.get(k)]
        for r in refs:
            if r not in idx:
                errs.append(f"consistency {rule.get('name')}: 不认识的题号 {r}")
    if bank.get("status") == "frozen" and bank.get("frozen_sha256") != bank.get("_sha256"):
        errs.append("status=frozen 但 frozen_sha256 和文件的规范化 sha256 对不上")
    return errs


# ════════════════════════════════════════════════════════════════════
# 哪个附件算首图
# ════════════════════════════════════════════════════════════════════

def _files(cell: Any) -> list[dict]:
    if not isinstance(cell, list):
        return []
    return [f for f in cell if isinstance(f, dict) and f.get("file_token")]


def pick_first_image(cols: dict) -> Optional[dict]:
    """cols: {列名: 飞书附件数组}。回 {column, n_files, first} 或 None (没有图片列 / 都是空的)。"""
    for col in IMAGE_COLUMNS:
        files = _files(cols.get(col))
        if files:
            return {"column": col, "n_files": len(files), "first": files[0]}
    return None


def file_size(f: dict) -> int:
    try:
        return int(f.get("size") or 0)
    except (TypeError, ValueError):
        return 0


def file_kind(f: dict) -> str:
    """jpeg / png / heic / empty_type / video / other。空类型的看文件名 (设计 §1.4)。"""
    typ = str(f.get("type") or "").strip().lower()
    name = str(f.get("name") or "").strip().lower()
    if typ.startswith("video/") or (not typ and name.endswith((".mp4", ".mov", ".m4v"))):
        return "video"
    if typ in ("image/jpeg", "image/jpg"):
        return "jpeg"
    if typ == "image/png":
        return "png"
    if typ in ("image/heic", "image/heif"):
        return "heic"
    if not typ:
        return "empty_type"
    return "other"


def decode_as(f: dict) -> str:
    """缩图时按哪种解: heic (含空类型且文件名是 .heic/.heif) 要 pillow-heif, 其余交给 Pillow 自己认。"""
    kind = file_kind(f)
    name = str(f.get("name") or "").strip().lower()
    if kind == "heic" or (kind == "empty_type" and name.endswith((".heic", ".heif"))):
        return "heic"
    return "auto"


# ════════════════════════════════════════════════════════════════════
# 抽样
# ════════════════════════════════════════════════════════════════════

def _rank(note_id: str, seed: str = SEED) -> str:
    return hashlib.md5((str(note_id) + seed).encode("utf-8")).hexdigest()


def _item(row: dict, stratum: str, column: str, f: dict, n_files: int, label: str = "") -> dict:
    return {"note_id": row["note_id"], "project_id": row["project_id"], "stratum": stratum, "label": label,
            "column": column, "file": f, "n_files": n_files, "title": row.get("title") or ""}


def select_sample(rows: list[dict], vanished: set, cap: Optional[int] = None) -> dict:
    """rows: [{note_id, project_id, tier, title, cols: {列名: 附件数组}}]。

    回 {regular, awkward, cover_check, column_check} 四个名单 (每项是 _item) 和 available (各层够不够数)。
    cap: 每一层最多取几个 (None = 设计的全量: 48 / 12 / 39 / 6 篇)。常规层按「项目 × 爆趴」轮着取, 所以 cap 小的时候
    也不会全落在一个项目里。档位只用来抽样, 不进提示词。
    """
    live = sorted((r for r in rows if r["note_id"] not in vanished), key=lambda r: _rank(r["note_id"]))
    picked: set = set()

    # 常规: 四个项目各 6 爆 6 趴, JPEG / PNG
    buckets: dict[tuple, list] = {}
    for r in live:
        if r["project_id"] not in TRIAL_PROJECTS:
            continue
        label = "hit" if r.get("tier") in HIT_TIERS else "flop" if r.get("tier") == FLOP_TIER else None
        first = pick_first_image(r.get("cols") or {})
        if not label or not first or file_kind(first["first"]) not in ("jpeg", "png"):
            continue
        b = buckets.setdefault((r["project_id"], label), [])
        if len(b) < (PER_PROJECT_HITS if label == "hit" else PER_PROJECT_FLOPS):
            b.append(_item(r, "regular", first["column"], first["first"], first["n_files"], label))
    regular: list[dict] = []
    order = [(p, lab) for p in TRIAL_PROJECTS for lab in ("hit", "flop")]
    for i in range(max(PER_PROJECT_HITS, PER_PROJECT_FLOPS)):
        for key in order:
            if i < len(buckets.get(key, [])):
                regular.append(buckets[key][i])
    if cap is not None:
        regular = regular[:cap]
    picked |= {x["note_id"] for x in regular}

    # 难办的文件: 所有项目里抽
    awkward: list[dict] = []
    avail_awk: dict[str, int] = {}
    for kind, want in AWKWARD_PLAN:
        got = []
        for r in live:
            if r["note_id"] in picked:
                continue
            first = pick_first_image(r.get("cols") or {})
            if not first:
                continue
            f = first["first"]
            fk = file_kind(f)
            hit = (fk == kind) if kind != "big" else (fk != "video" and file_size(f) >= BIG_BYTES)
            if hit:
                got.append(_item(r, kind, first["column"], f, first["n_files"]))
                if len(got) >= want:
                    break
        avail_awk[kind] = len(got)
        awkward.extend(got)
        picked |= {x["note_id"] for x in got}
    if cap is not None:
        awkward = awkward[:cap]

    # 封面检查: 有多图帖的每张表各 3 篇 (只下载、只解图, 不调模型)
    cover: list[dict] = []
    per_proj: dict[str, int] = Counter()
    for r in live:
        first = pick_first_image(r.get("cols") or {})
        if not first or first["n_files"] < 2 or file_kind(first["first"]) == "video":
            continue
        if per_proj[r["project_id"]] >= COVER_CHECK_PER_PROJECT:
            continue
        per_proj[r["project_id"]] += 1
        cover.append(_item(r, "cover_check", first["column"], first["first"], first["n_files"]))
    cover.sort(key=lambda x: (x["project_id"], _rank(x["note_id"])))
    if cap is not None:
        cover = _round_robin(cover, cap)

    # 列检查: RIO / TXQ / WTG 各 2 篇, 内容配图第 0 个 + 笔记截图第 0 个
    column: list[dict] = []
    per_proj = Counter()
    for r in live:
        if r["project_id"] not in COLUMN_CHECK_PROJECTS or per_proj[r["project_id"]] >= COLUMN_CHECK_PER_PROJECT:
            continue
        cols = r.get("cols") or {}
        own, shot = _files(cols.get(IMAGE_COLUMNS[0])), _files(cols.get(SCREENSHOT_COLUMN))
        if not own or not shot or file_kind(own[0]) not in ("jpeg", "png") or file_kind(shot[0]) not in ("jpeg", "png"):
            continue
        per_proj[r["project_id"]] += 1
        column.append({"note_id": r["note_id"], "project_id": r["project_id"], "stratum": "column_check",
                       "own": own[0], "shot": shot[0]})
    column.sort(key=lambda x: (x["project_id"], _rank(x["note_id"])))
    if cap is not None:
        column = _round_robin(column, cap)

    return {"regular": regular, "awkward": awkward, "cover_check": cover, "column_check": column,
            "available": {"regular": {f"{p}:{lab}": len(buckets.get((p, lab), [])) for p, lab in order},
                          "awkward": avail_awk,
                          "cover_check_projects": len({x["project_id"] for x in cover}),
                          "column_check_projects": len({x["project_id"] for x in column})}}


def _round_robin(items: list[dict], cap: int) -> list[dict]:
    by: dict[str, list] = {}
    for x in items:
        by.setdefault(x["project_id"], []).append(x)
    out: list[dict] = []
    i = 0
    while len(out) < cap and any(i < len(v) for v in by.values()):
        for p in sorted(by):
            if i < len(by[p]) and len(out) < cap:
                out.append(by[p][i])
        i += 1
    return out


# ════════════════════════════════════════════════════════════════════
# 缩图 (只在内存里)
# ════════════════════════════════════════════════════════════════════

_DECODE_LOCK = threading.Lock()      # 一次只解一张大图: 并发解 4 张 1 亿像素的图会把 runner 的内存吃光


def image_libs_ready() -> Optional[str]:
    """Pillow 和 pillow-heif 都装了回 None, 否则回缺的那个名字 (正式跑之前先查, 没装就不花钱)。"""
    try:
        import PIL  # noqa: F401
    except Exception:  # noqa: BLE001
        return "Pillow"
    try:
        import pillow_heif  # noqa: F401
    except Exception:  # noqa: BLE001
        return "pillow-heif"
    return None


def shrink(data: bytes, long_sides: tuple[int, ...] = (LONG_SIDE,), decode: str = "auto") -> dict:
    """把一张图解开、缩到长边 ≤ long_side、重编成 JPEG (元数据随之丢掉)。全程在内存里。

    回 {"pixels": 原图像素数, "images": {long_side: (jpeg 字节, 宽, 高)}}。
    解不开 / 像素超上限 → FirstImageError(decode_failed / too_many_pixels)。
    """
    import warnings

    from PIL import Image, ImageOps

    if decode == "heic":
        import pillow_heif
        pillow_heif.register_heif_opener()
    with _DECODE_LOCK:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                Image.MAX_IMAGE_PIXELS = None            # 上限由下面这行管, 不靠 Pillow 的警告
                im = Image.open(io.BytesIO(data))
                w, h = im.size
                if w * h > PIXEL_CAP:
                    raise FirstImageError("too_many_pixels")
                im.draft("RGB", (max(long_sides) * 2, max(long_sides) * 2))   # JPEG: 解码时就先缩, 省内存
                im = ImageOps.exif_transpose(im)
                if im.mode in ("RGBA", "LA", "P"):
                    im = im.convert("RGBA")
                    bg = Image.new("RGB", im.size, (255, 255, 255))
                    bg.paste(im, mask=im.split()[-1])
                    im = bg
                else:
                    im = im.convert("RGB")
                out: dict[int, tuple] = {}
                for side in sorted(set(long_sides), reverse=True):
                    cp = im.copy()
                    cp.thumbnail((side, side), Image.LANCZOS)
                    cp.info.clear()                      # 注释段 / ICC / DPI 都在 info 里, 存 JPEG 时会被写回去
                    buf = io.BytesIO()
                    cp.save(buf, format="JPEG", quality=85)
                    out[side] = (buf.getvalue(), cp.size[0], cp.size[1])
                return {"pixels": w * h, "images": out}
        except FirstImageError:
            raise
        except Exception:  # noqa: BLE001 — 解图库的报错里可能带文件信息, 只留状态词
            raise FirstImageError("decode_failed") from None


def pixel_bucket(pixels: int) -> str:
    mp = pixels / 1e6
    for edge, name in ((2, "<2MP"), (8, "2-8MP"), (20, "8-20MP"), (40, "20-40MP")):
        if mp < edge:
            return name
    return ">=40MP"


def image_tokens_estimate(w: int, h: int) -> int:
    """纸面公式 (宽 × 高 ÷ 750)。只用来在调用前预留额度, 实际以中转站回报的为准。"""
    return math.ceil(w * h / 750)


def as_block(jpeg: bytes) -> tuple[str, str]:
    return ("image/jpeg", base64.b64encode(jpeg).decode("ascii"))


# ════════════════════════════════════════════════════════════════════
# 提示词与答案
# ════════════════════════════════════════════════════════════════════

_PROMPT_HEAD = ("下面是一张图片。只根据这张图片本身回答问题, 不要猜图片以外的事 (这张图来自哪里、效果好不好都不用管)。\n"
                "选择题只能从给出的选项里选一个, 答案照抄选项的原文; 抄字题按要求抄。\n"
                "只输出 JSON, 不要解释、不要加别的字: {\"answers\":[{\"id\":\"题号\",\"answer\":\"答案\"}]}\n")


def option_line(o: dict) -> str:
    """一个选项在提示词里印出来的那一行 (不带打头的「- 」): 有解释的是「选项: 解释」, 没有解释的就是选项本身。
    build_prompt 印的、accept_option_lines 比的是同一个函数的结果, 所以「和提示词里那一行一字不差」不会各说各的。"""
    return f"{o['value']}" + (f": {o['means']}" if o.get("means") else "")


def build_prompt(bank: dict, qids: list[str]) -> str:
    """一次调用的提示词: 只有这一组的题。里面没有档位、数据、标题、正文 —— 这个函数根本拿不到它们。"""
    if not 1 <= len(qids) <= MAX_GROUP_SIZE:
        raise ValueError(f"一次调用最多问 {MAX_GROUP_SIZE} 题")
    idx = question_index(bank)
    parts = [_PROMPT_HEAD]
    for n, qid in enumerate(qids, 1):
        q = idx[qid]
        if q.get("type") not in ("choice", "text"):
            raise ValueError(f"{qid} 不是模型题")
        parts.append(f"\n第 {n} 题 · id: {qid}\n问: {q['ask']}")
        if q["type"] == "choice":
            parts.append("选项:")
            for o in q["options"]:
                parts.append("- " + option_line(o))
        else:
            parts.append(f"答案是照抄的字 (最多 {q['max_chars']} 个字), 没有就给空字符串。")
    return "\n".join(parts) + "\n"


def parse_answers(bank: dict, qids: list[str], text: str) -> dict[str, tuple[Optional[str], Optional[str]]]:
    """模型回的字 → {题号: (答案, 无效原因)}。不在闭集里、缺题、抄的字超长都记无效, 不修补。"""
    idx = question_index(bank)
    got: dict[str, Any] = {}
    try:
        s, e = text.index("{"), text.rindex("}")
        data = json.loads(text[s:e + 1])
        for a in data.get("answers") or []:
            if isinstance(a, dict) and isinstance(a.get("id"), str):
                got.setdefault(a["id"], a.get("answer"))
    except Exception:  # noqa: BLE001
        return {qid: (None, INVALID_PARSE) for qid in qids}
    out: dict[str, tuple] = {}
    for qid in qids:
        q = idx[qid]
        if qid not in got or not isinstance(got[qid], str):
            out[qid] = (None, INVALID_MISSING)
            continue
        val = got[qid].strip()
        if q["type"] == "choice":
            out[qid] = (val, None) if val in option_values(q) else (None, INVALID_OOV)
        else:
            out[qid] = (val, None) if len(val) <= int(q["max_chars"]) else (None, INVALID_TEXT_LONG)
    return out


# ── 回包的诊断 (D-159, docs/34 §10): 只数, 不认 ──────────────────────────────────────────────────
# 认什么、存什么只有上面 parse_answers 一个地方说了算 (和 11-16 首跑时一字不差), 下面的代码一个答案都不改、一个无效原因都不改。
# 它只做两件事, 都只进计数 (first_image_pass 的 run 摘要), 都是写死的词, 不带回包里的任何字:
#   · notes: parse_answers 判了无效的每一道题, 给一个细一层的词 (NOTES)
#   · would_read: 这道无效的题, 【假如】放宽某一条读法, 会不会读出一个答案 (WOULD_READ)。只是「假如」: 没有放宽, 答案照旧无效。
#     这个分类器自己可以有看走眼的地方 (评审列过二十来种), 所以它的数只用来决定下一步值不值得放宽哪一条, 不能拿来认答案。
NOTE_EMPTY = "empty_reply"                # 回包里没有字
NOTE_TRUNCATED = "truncated"              # 没读出来, 而且中转站说是撞了 max_tokens (一个字都没回的也算这个)
NOTE_STOP_OTHER = "stop_other"            # 没读出来, 中转站给的停止原因既不是 end_turn 也不是 max_tokens
NOTE_NO_JSON = "no_json"                  # 没有一段读得出来的 JSON
NOTE_DUP_KEY = "json_duplicate_key"       # 有 JSON, 但一个对象里同一个键写了两遍
NOTE_NO_ANSWERS = "no_answers_in_json"    # 有 JSON, 里面没有认得出的答案
NOTE_NOT_TEMPLATE = "json_not_template"   # 题号和答案都在, 但 JSON 不是模板那个样子
NOTE_ID_NUMBERED = "id_numbered"          # 题号写成了 1 / 2 / 「第 1 题」
NOTE_ID_ABSENT = "id_absent"              # 回包里有别的题, 没有这一道
NOTE_NOT_TEXT = "answer_not_text"         # 答案不是字符串 (列表 / null / 数字)
NOTE_CONFLICT = "conflicting_answers"     # 同一道题两个不一样的答案
NOTE_OOV_WRAPPED = "oov_option_wrapped"   # 字就是某个选项, 两头多了标点 / 引号 / 括号 / 空格
NOTE_OOV_LINE = "oov_option_line"         # 抄的是选项的整行 (选项: 解释)
NOTE_OOV_MARKED = "oov_option_with_mark"  # 字就是某个选项, 但带着问号 / 叉 / 删除线之类的记号, 或字中间断开了
NOTE_OOV_PLUS = "oov_option_plus_more"    # 以某个选项开头, 后面多了字
NOTE_OOV_CONTAINS = "oov_contains_option"  # 里面含着恰好一个选项
NOTE_OOV_PART = "oov_part_of_option"      # 是某一个选项的一截
NOTE_OOV_OTHER = "oov_other"
NOTE_TEXT_LONG = INVALID_TEXT_LONG
NOTE_TOO_LONG = "reply_too_long"          # 回包长过 NOTE_MAX_CHARS, 不细看
NOTE_UNCLASSIFIED = "unclassified"        # 分类器自己出了岔子 (不让它拖垮夜跑)
NOTES = (NOTE_EMPTY, NOTE_TRUNCATED, NOTE_STOP_OTHER, NOTE_NO_JSON, NOTE_DUP_KEY, NOTE_NO_ANSWERS, NOTE_NOT_TEMPLATE,
         NOTE_ID_NUMBERED, NOTE_ID_ABSENT, NOTE_NOT_TEXT, NOTE_CONFLICT, NOTE_OOV_WRAPPED, NOTE_OOV_LINE, NOTE_OOV_MARKED,
         NOTE_OOV_PLUS, NOTE_OOV_CONTAINS, NOTE_OOV_PART, NOTE_OOV_OTHER, NOTE_TEXT_LONG, NOTE_TOO_LONG, NOTE_UNCLASSIFIED)
WOULD_PUNCT = "option_with_punctuation"   # 假如去掉选项两头的标点 / 引号 / 括号 / 空格
WOULD_LINE = "option_line_copied"         # 假如认选项的整行
WOULD_LOOSE = "loose_json"                # 假如认换了样子的 JSON (题号还是那个题号)
WOULD_LOOSE_PUNCT = "loose_json_option_with_punctuation"   # 两条都放宽才读得出
WOULD_LOOSE_LINE = "loose_json_option_line_copied"
WOULD_OTHER = "other"                     # 分类器读得出、又说不出靠的是哪一条 (不该有; 有了就是分类器的毛病)
WOULD_READ = (WOULD_PUNCT, WOULD_LINE, WOULD_LOOSE, WOULD_LOOSE_PUNCT, WOULD_LOOSE_LINE, WOULD_OTHER)
STOP_WORDS = ("end_turn", "max_tokens")   # 中转站回的 stop_reason 只认这两个词, 别的一律记 other
NOTE_MAX_CHARS = 20_000                   # 一次回包最多 MAX_OUTPUT_TOKENS 个 token; 长过这个数的不是正常回包, 不花时间细看

_JSON_OPEN = re.compile(r"[{\[]")
# 选项两头可以去掉的字 (NFKC 之后): 句读、引号、括号、列表记号、加粗的星号。问号、叉、波浪线、省略号都不在里面。
_WRAP = frozenset(" \t\r\n.,;:!。、\"'`“”‘’「」『』《》〈〉【】()[]{}-–—*•·")
_NUMBERED_ID = re.compile(r"(?:第\s*)?\d{1,2}(?:\s*题)?")
_TRAIL_OFF = re.compile(r"[.。、·•,][ \t]*[.。、·•,]|[-–—~]{2}")     # 「封面。。。」「封面. .」「封面——」是话没说完, 不是句号
# 「[ ] 封面」「( ) 封面」是没勾的框, 不是括号。空白只许有一种分法 (两段挨着的 [ \t]* 遇上一长串空格是平方级的回溯)。
_EMPTY_BOX = re.compile(r"[\[(【][ \t]*(?:[-–—][ \t]*)?[\])】]")


def stop_word(stop_reason: Any) -> Optional[str]:
    """stop_reason → 写死的词 (end_turn / max_tokens / other); 没给回 None。原样的字不往外带。"""
    if stop_reason is None:
        return None
    return stop_reason if isinstance(stop_reason, str) and stop_reason in STOP_WORDS else "other"


def _json_values(text: str, hook: Callable[[list], dict]) -> list:
    """回包里一段一段读得出来的 JSON (只取最外层的)。括号不成对 (多半是回到一半断了) → 一段都不取。
    某一段读不出来 (多了个逗号、里面夹着字) → 整段跳过, 不进去找它里面的对象。
    每一段先按括号切出来再解码: 解码器报错时要数行号, 拿整个回包去解码的话每错一次都从头数一遍 (几十万段就是平方级的时间)。"""
    if not _balanced(text):
        return []
    out, i = [], 0
    while True:
        m = _JSON_OPEN.search(text, i)
        if not m:
            return out
        i = _skip_value(text, m.start())
        try:
            out.append(json.loads(text[m.start():i], object_pairs_hook=hook))
        except (ValueError, RecursionError):               # 嵌得太深的回包也只是「读不出来」
            pass


def _balanced(text: str) -> bool:
    """花括号、方括号各自成不成对。JSON 引号里的括号是内容 (抄下来的字里可以有「[限时」), 不算。"""
    curly = square = 0
    in_str = esc = False
    for ch in text:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            curly += 1
        elif ch == "}":
            curly -= 1
        elif ch == "[":
            square += 1
        elif ch == "]":
            square -= 1
    return curly == 0 and square == 0


def _skip_value(text: str, start: int) -> int:
    """start 处是一个 { 或 [: 回它配对的那个括号后面的位置 (引号里的括号不算); 配不上就回文末。"""
    depth, in_str, esc = 0, False, False
    for j in range(start, len(text)):
        ch = text[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth <= 0:
                return j + 1
    return len(text)


def _collect(val: Any, qids: list[str], got: dict[str, list], odd_ids: list) -> bool:
    """从一段 JSON 里把 (题号, 答案) 收进 got。回「这一段是不是模板那个样子」。看的样子:
    {"answers":[{id, answer}…]} (模板) / {"answers":{题号: 答案}} / [{id, answer}…] / {id, answer} / {题号: 答案}。"""
    def items(seq: list) -> None:
        for a in seq:
            if isinstance(a, dict) and "id" in a:
                if isinstance(a["id"], str) and a["id"] in qids:
                    got.setdefault(a["id"], []).append(a.get("answer"))
                else:
                    odd_ids.append(a["id"])

    def flat(d: dict) -> None:
        for q in qids:
            if q in d:
                got.setdefault(q, []).append(d[q])

    if isinstance(val, list):
        items(val)
        return False
    if not isinstance(val, dict):
        return False
    ans = val.get("answers")
    if isinstance(ans, list):
        items(ans)
        return True
    if isinstance(ans, dict):
        flat(ans)
    elif "id" in val and "answer" in val:
        items([val])
    else:
        flat(val)
    return False


def match_option(q: dict, raw: str) -> tuple[Optional[str], Optional[str]]:
    """【只给诊断用, 不决定认不认】选择题的一个答案 → (假如放宽会读成哪个选项, 靠的是哪一条)。读不成回 (None, None)。
    一字不差 → (选项, None); 去掉【两头】包着的标点引号括号空格 (_WRAP) 之后和【恰好一个】选项一字不差 → WOULD_PUNCT;
    是【恰好一个】选项在提示词里的整行 → WOULD_LINE。带问号、叉、删除线、省略号、没勾的框、打头的感叹号的读不成。"""
    val = raw.strip()
    vals = option_values(q)
    if val in vals:
        return val, None
    if _boxed_or_negated(raw):
        return None, None
    core = _unwrap(raw)
    hits = [(str(o["value"]), WOULD_PUNCT) for o in q.get("options") or [] if core and core == _unwrap(str(o["value"]))]
    key = normalise(raw)
    for o in q.get("options") or []:
        line = f"{o['value']}: {o.get('means') or ''}"
        if key and o.get("means") and key == normalise(line) and _only_plain_marks(raw, line):
            hits.append((str(o["value"]), WOULD_LINE))
    return hits[0] if len(hits) == 1 else (None, None)


def _plain(text: str) -> str:
    """NFKC、小写、去掉零宽这类看不见的格式字符 (Cf)。别的一个字都不动。"""
    t = unicodedata.normalize("NFKC", text or "").lower()
    return "".join(ch for ch in t if unicodedata.category(ch) != "Cf")


def _unwrap(text: str) -> str:
    """去掉两头 _WRAP 里的字。连着的点、顿号、破折号 (话没说完) 不当句号去: 「封面…」「封面。。。」不是「封面。」。"""
    t = _plain(text)
    if _TRAIL_OFF.search(t):
        return ""
    i, j = 0, len(t)
    while i < j and t[i] in _WRAP:
        i += 1
    while j > i and t[j - 1] in _WRAP:
        j -= 1
    return t[i:j]


def _boxed_or_negated(raw: str) -> bool:
    """两头包着的那一串字里有没有感叹号打头 (可能是「不是」) 或者一个没勾的框 ([ ] / ( ) / [-])。"""
    t = _plain(raw)
    i, j = 0, len(t)
    while i < j and t[i] in _WRAP and t[i] != "!":
        i += 1
    if t[i:i + 1] == "!":
        return True
    while j > i and t[j - 1] in _WRAP:
        j -= 1
    return bool(_EMPTY_BOX.search(t[:i]) or _EMPTY_BOX.search(t[j:]))


def _only_plain_marks(raw: str, line: str) -> bool:
    """raw 里字母数字之外的字, 是不是都在 _WRAP 或者那一行自己的标点里 (而且没有省略号)。"""
    t, own = _plain(raw), set(_plain(line))
    if _TRAIL_OFF.search(t) and not _TRAIL_OFF.search(_plain(line)):
        return False
    return all(ch in _WRAP or ch in own for ch in t if unicodedata.category(ch)[0] not in ("L", "N"))


def _oov_note(q: dict, raw: str) -> str:
    key = normalise(raw)
    opts = [normalise(v) for v in option_values(q)]
    if key and key in opts:
        return NOTE_OOV_MARKED
    if key and sum(1 for o in opts if key.startswith(o)) == 1:
        return NOTE_OOV_PLUS
    if key and sum(1 for o in opts if o in key) == 1:
        return NOTE_OOV_CONTAINS
    if key and sum(1 for o in opts if key in o) == 1:
        return NOTE_OOV_PART
    return NOTE_OOV_OTHER


def _shape_read(bank: dict, qids: list[str], text: str, stop: Optional[str]) -> dict[str, tuple]:
    """【只给诊断用】按格式把回包再看一遍 → {题号: (假如放宽会读出的答案 或 None, 读不出时的词, 读得出时靠的哪一条)}。
    题号必须是问的题号本身; 同一道题两个不一样的答案、同一个键写两遍、不是字符串的答案都读不出;
    停止原因不是 end_turn、又不是一整个模板 JSON 的, 一个都不读 (多半是断了)。"""
    idx = question_index(bank)
    got: dict[str, list] = {}
    odd_ids: list = []
    dup = [False]

    def hook(pairs: list) -> dict:
        out: dict = {}
        for k, v in pairs:
            if k in out:
                dup[0] = True
                raise ValueError("duplicate key")
            out[k] = v
        return out

    strict = True
    try:                                                   # parse_answers 的切法: 第一个 { 到最后一个 }
        vals = [json.loads(text[text.index("{"):text.rindex("}") + 1], object_pairs_hook=hook)]
    except (ValueError, RecursionError):
        strict = False
        vals = _json_values(text, hook)
    else:
        if not (isinstance(vals[0], dict) and isinstance(vals[0].get("answers"), list)):
            vals = _json_values(text, hook)                # 切出来的不是模板: 整个回包按「一段一段完整的 JSON」重看
    template = [_collect(v, qids, got, odd_ids) for v in vals]
    loose = not (strict and all(template))
    if stop not in (None, "end_turn") and loose:
        got = {}
    if not got:
        if stop == "max_tokens":                           # 先看这一条: 思考把上限用完、一个字都没回的也是撞上限
            whole = NOTE_TRUNCATED
        elif not text.strip():
            whole = NOTE_EMPTY
        elif stop not in (None, "end_turn"):
            whole = NOTE_STOP_OTHER
        elif not vals:
            whole = NOTE_DUP_KEY if dup[0] else NOTE_NO_JSON
        elif odd_ids and all((isinstance(i, int) and not isinstance(i, bool))
                             or (isinstance(i, str) and _NUMBERED_ID.fullmatch(i.strip())) for i in odd_ids):
            whole = NOTE_ID_NUMBERED
        else:
            whole = NOTE_NO_ANSWERS
        return {q: (None, whole, None) for q in qids}
    out: dict[str, tuple] = {}
    for qid in qids:
        q = idx[qid]
        if qid not in got:
            out[qid] = (None, NOTE_ID_ABSENT, None)
            continue
        answers = got[qid]
        if any(not isinstance(a, str) for a in answers):
            out[qid] = (None, NOTE_NOT_TEXT, None)
            continue
        if q["type"] == "choice":
            matched = [match_option(q, a) for a in answers]
            if len({v for v, _t in matched}) > 1 or (matched[0][0] is None and len({a.strip() for a in answers}) > 1):
                out[qid] = (None, NOTE_CONFLICT, None)
            elif matched[0][0] is None:
                out[qid] = (None, _oov_note(q, answers[0]), None)
            else:
                tol = next((t for _v, t in matched if t), None)
                out[qid] = (matched[0][0], None, {
                    (False, None): None, (False, WOULD_PUNCT): WOULD_PUNCT, (False, WOULD_LINE): WOULD_LINE,
                    (True, None): WOULD_LOOSE, (True, WOULD_PUNCT): WOULD_LOOSE_PUNCT, (True, WOULD_LINE): WOULD_LOOSE_LINE,
                }[(loose, tol)])
        elif q["type"] != "text":                          # 代码题不问模型; 真出现在这里只给一个词
            out[qid] = (None, NOTE_UNCLASSIFIED, None)
        elif len({normalise(a) for a in answers}) > 1:
            out[qid] = (None, NOTE_CONFLICT, None)
        elif len(answers[0].strip()) > int(q["max_chars"]):
            out[qid] = (None, NOTE_TEXT_LONG, None)
        else:
            out[qid] = (answers[0].strip(), None, WOULD_LOOSE if loose else None)
    return out


_WOULD_NOTE = {WOULD_PUNCT: NOTE_OOV_WRAPPED, WOULD_LINE: NOTE_OOV_LINE, WOULD_LOOSE: NOTE_NOT_TEMPLATE,
               WOULD_LOOSE_PUNCT: NOTE_NOT_TEMPLATE, WOULD_LOOSE_LINE: NOTE_NOT_TEMPLATE, WOULD_OTHER: NOTE_UNCLASSIFIED}


def read_reply(bank: dict, qids: list[str], text: str, stop_reason: Any = None) -> dict:
    """模型回的字 → {"parsed": {题号: (答案, 无效原因)}, "notes": {题号: 词}, "would_read": {题号: 词}}。

    parsed 就是 parse_answers(bank, qids, text) 的结果, 一个字不改 —— 认什么只有它说了算, stop_reason 也不影响它。
    notes 给 parsed 里每道无效的题一个细一层的写死的词 (NOTES); would_read 记其中哪几道【假如】放宽某一条读法就读得出来
    (WOULD_READ)。这两样都只进计数, 没有任何答案因为它们被认下来。分类器出了岔子、回包长得离谱, 都只是换一个词, 不抛。
    """
    text = text or ""
    parsed = parse_answers(bank, qids, text)
    invalid = [q for q in qids if parsed[q][1] is not None]
    notes: dict[str, str] = {}
    would: dict[str, str] = {}
    if not invalid:
        return {"parsed": parsed, "notes": notes, "would_read": would}
    stop = stop_word(stop_reason)
    try:
        seen = None if len(text) > NOTE_MAX_CHARS else _shape_read(bank, qids, text, stop)
    except Exception:  # noqa: BLE001 — 诊断不许拖垮夜跑
        seen = {}
    for q in invalid:
        if seen is None:
            notes[q] = NOTE_TRUNCATED if stop == "max_tokens" else NOTE_TOO_LONG
            continue
        val, note, word = seen.get(q) or (None, NOTE_UNCLASSIFIED, None)
        if val is None:
            notes[q] = note if note in NOTES else NOTE_UNCLASSIFIED
        else:
            would[q] = word if word in WOULD_READ else WOULD_OTHER
            notes[q] = _WOULD_NOTE[would[q]]
    return {"parsed": parsed, "notes": notes, "would_read": would}


# ── 整行照抄 (D-160, docs/34 §11): 认, 但只认和提示词里那一行【一字不差】的 ────────────────────────────
# 第二趟真跑 (每晚那一趟) 104 次调用里, 分类器数出 34 个答案抄的是选项的整行 (「选项: 解释」), 不是选项的名字。parse_answers 一个字不动
# (源码的 sha256 还钉着); 这里只在它判了 out_of_vocab 的选择题上再看一眼, 而且只有下面五条全中才认成那个选项:
#   1. parse_answers 给这道题的是 (None, out_of_vocab)
#   2. 它取的那个答案, 去掉两头的空白、再去掉至多一个打头的「- 」(提示词自己印的那个) 之后, 和【恰好一个】有解释的选项的
#      option_line 用 == 比一字不差 —— 不折全半角、不去标点、不认全角冒号、不认少一个字多一个字的
#   3. 停止原因没给, 或者是 end_turn
#   4. 整个回包除了那一段 JSON 之外没有别的字 (只许整段包在一个 ``` / ```json 围栏里)
#   5. 那一段 JSON 就是模板: 只有 answers 一个键、是列表、每一项只有 id 和 answer 两个键、id 是这次问的题而且不重复、
#      answer 是字符串、整段没有写了两遍的键
# 3–5 看的是整个回包: 有一条不中, 这个回包里一个整行都不认 (照旧 out_of_vocab), 只数一个写死的词 (LINE_REFUSED)。
# 没有解释的选项 (「有」「能」这种) 没有「整行」可抄, 这里什么都不多认: 「- 有」照旧无效。
LINE_REFUSED = ("stop", "text_around_json", "not_template")


def accept_option_lines(bank: dict, qids: list[str], text: str, parsed: dict[str, tuple],
                        stop: Any = None) -> tuple[dict[str, str], dict[str, str]]:
    """回 (认下来的 {题号: 选项}, 一字不差但没认的 {题号: LINE_REFUSED 里的词})。parsed 是 parse_answers 的结果, 这里不改它。
    出了任何岔子都回 ({}, {}): 宁可不认。"""
    try:
        idx = question_index(bank)
        cand = [q for q in qids if idx[q].get("type") == "choice" and parsed.get(q) == (None, INVALID_OOV)]
        if not cand:
            return {}, {}
        s, e = text.index("{"), text.rindex("}")                 # parse_answers 的切法和取法: 同一题取第一个
        got: dict[str, Any] = {}
        for a in json.loads(text[s:e + 1]).get("answers") or []:
            if isinstance(a, dict) and isinstance(a.get("id"), str):
                got.setdefault(a["id"], a.get("answer"))
        hits: dict[str, str] = {}
        for q in cand:
            raw = got.get(q)
            if not isinstance(raw, str):
                continue
            body = raw.strip()
            if body.startswith("- "):
                body = body[2:]
            vals = [str(o["value"]) for o in idx[q].get("options") or [] if o.get("means") and body == option_line(o)]
            if len(vals) == 1:
                hits[q] = vals[0]
        if not hits:
            return {}, {}
        word = _line_refusal(qids, text, s, e, stop_word(stop))
        if word:
            return {}, {q: word for q in hits}
        return hits, {}
    except Exception:  # noqa: BLE001
        return {}, {}


def _line_refusal(qids: list[str], text: str, s: int, e: int, stop: Optional[str]) -> Optional[str]:
    """整个回包够不够格 (上面的 3–5)。够格回 None, 不够格回 LINE_REFUSED 里的一个词。"""
    if stop not in (None, "end_turn"):
        return "stop"
    pre, post = text[:s].strip(), text[e + 1:].strip()
    if not ((pre == "" and post == "") or (pre in ("```", "```json") and post == "```")):
        return "text_around_json"

    def hook(pairs: list) -> dict:
        out: dict = {}
        for k, v in pairs:
            if k in out:
                raise ValueError("duplicate key")
            out[k] = v
        return out

    try:
        data = json.loads(text[s:e + 1], object_pairs_hook=hook)
    except ValueError:
        return "not_template"
    if not isinstance(data, dict) or set(data) != {"answers"} or not isinstance(data["answers"], list):
        return "not_template"
    seen: set = set()
    for a in data["answers"]:
        if not isinstance(a, dict) or set(a) != {"id", "answer"} or not isinstance(a["id"], str) \
                or a["id"] not in qids or a["id"] in seen or not isinstance(a["answer"], str):
            return "not_template"
        seen.add(a["id"])
    return None


def normalise(text: str) -> str:
    """去掉空格、标点、表情, 全角转半角, 转小写 (设计 §3)。"""
    t = unicodedata.normalize("NFKC", text or "").lower()
    return "".join(ch for ch in t if unicodedata.category(ch)[0] in ("L", "N"))


def text_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def transcriptions_match(a: str, b: str) -> bool:
    na, nb = normalise(a), normalise(b)
    return na == nb or text_ratio(na, nb) >= TEXT_RATIO


def text_matches_title(text: str, title: str) -> tuple[Optional[str], Optional[str], bool]:
    """回 (答案, 无效原因, 是否落在 0.60–0.80 的灰带里)。"""
    nt = normalise(text)
    if not nt:
        return NO_TEXT, None, False
    ntitle = normalise(title)
    if not ntitle:
        return None, INVALID_NO_TITLE, False
    short, long_ = sorted((nt, ntitle), key=len)
    if len(short) >= 4 and short in long_:
        return "一样或差不多", None, False
    ratio = text_ratio(nt, ntitle)
    if ratio >= TEXT_RATIO:
        return "一样或差不多", None, False
    return "不一样", None, ratio >= TEXT_GREY


_CN_NUM = re.compile(r"[一二两三四五六七八九十百千万半][天日周月年元块个款种招步次倍折斤岁件条点分秒]")


def text_has_number(text: str) -> str:
    nt = normalise(text)
    if not nt:
        return NO_TEXT
    return "有" if (re.search(r"\d", nt) or _CN_NUM.search(nt)) else "没有"


def assemble(bank: dict, parsed: dict[str, tuple], title: Optional[str]) -> dict:
    """一张图一轮的全部模型答案 → {answers: {题号: 答案}, invalid: {题号: 原因}, grey: bool, voided: [规则名]}。

    顺序: 闭集校验 (parse_answers 已做) → 自相矛盾 → 不是封面 (其余记无效) → 两道代码题。
    自相矛盾 (D-160, docs/34 §11): 每条规则都对着同一份答案看 (前一条规则作废的题不影响后一条怎么判)。
      · 规则写了 void (fi-v0.2): 只把 void 里列的题记无效 (inconsistent:<规则名>; 本来就无效的题留着本来的原因), 别的照留。
        几条规则都中: 作废的题取并集, 一道题的原因是题库里排在前面的那条规则。voided 里是这样处理掉的规则名。
      · 规则没写 void (fi-v0.1): 整轮记无效, 和原来一样; 只要有一条这样的规则中了, 就是整轮 (voided 是空的)。
    没有「信哪一边」的规则: 两头的答案都作废。
    title=None 表示这一轮不算代码题 (列检查那种只问一题的)。
    """
    answers = {q: v for q, (v, why) in parsed.items() if why is None}
    invalid = {q: why for q, (v, why) in parsed.items() if why is not None}
    grey = False
    seen = dict(answers)                                   # 规则只看这一份, 不看作废之后的
    partial: list[tuple[str, list]] = []
    whole: Optional[str] = None
    for rule in bank.get("consistency") or []:
        cond = rule.get("if") or {}
        if not all(seen.get(q) in vals for q, vals in cond.items()):
            continue
        bad = False
        if rule.get("then_empty") and rule["then_empty"] in seen and normalise(seen[rule["then_empty"]]):
            bad = True
        if rule.get("then_not_empty") and rule["then_not_empty"] in seen \
                and not normalise(seen[rule["then_not_empty"]]):
            bad = True
        for q, vals in (rule.get("then_not") or {}).items():
            if seen.get(q) in vals:
                bad = True
        if not bad:
            continue
        if rule.get("void") is None:
            whole = whole or f"inconsistent:{rule.get('name')}"
        else:
            partial.append((str(rule.get("name")), list(rule["void"])))
    if whole:
        return {"answers": {}, "invalid": {q: invalid.get(q, whole) for q in parsed}, "grey": False, "voided": []}
    for name, ids in partial:
        for q in ids:
            if q in parsed:
                answers.pop(q, None)
                invalid.setdefault(q, f"inconsistent:{name}")
    voided = [name for name, _ids in partial]
    if answers.get("img_kind") not in (None, COVER):
        keep = {"img_kind": answers["img_kind"]}
        return {"answers": keep, "invalid": {q: invalid.get(q, INVALID_NOT_COVER) for q in parsed if q != "img_kind"},
                "grey": False, "voided": voided}
    if title is not None and "img_main_text" in answers:
        val, why, grey = text_matches_title(answers["img_main_text"], title)
        if why:
            invalid["img_text_matches_title"] = why
        else:
            answers["img_text_matches_title"] = val
        answers["img_text_has_number"] = text_has_number(answers["img_main_text"])
    return {"answers": answers, "invalid": invalid, "grey": grey, "voided": voided}


# ════════════════════════════════════════════════════════════════════
# 花费硬上限
# ════════════════════════════════════════════════════════════════════

# 11-25 (I-38): 中转站回报的四项用量, 键 → 回包里的字段名。字段名是 API 的, 写死; 摘要里原样打这几个名字
USAGE_FIELDS = (("input", "input_tokens"), ("cache_write", "cache_creation_input_tokens"),
                ("cache_read", "cache_read_input_tokens"), ("output", "output_tokens"))
BIG_INPUT = 3_000          # 一次调用的总输入 (input + 写缓存 + 读缓存) 超过它就数一次; 写死的门槛 (11-24 晚平均每次约 1,300, 11-23 晚约 5,100)
# 回包从哪来 (11-25, I-38): 模型名原样、消息 id 只留开头的前缀。认不出的一律换成下面几个写死的词, 回包里别的字一个都不往外带
REPLY_NOT_GIVEN = "【没回】"
REPLY_ODD_MODEL = "【不像模型名】"
REPLY_NO_UNDERSCORE = "【没有下划线】"
REPLY_ODD_ID = "【开头认不出】"
REPLY_OTHERS = "【另外几种】"
_REPLY_MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,63}")
# 消息 id 的前缀只认两样: 第一段 1–8 个小写字母 (msg); 第二段只认这张写死的厂商标记单子 (Bedrock / Vertex), 单子之外的一概不留
ID_VENDOR_TAGS = ("bdrk", "vrtx")
_ID_FIRST_RE = re.compile(r"[a-z]{1,8}")
_ID_PREFIX_RE = re.compile(r"[a-z]{1,8}(?:_(?:" + "|".join(ID_VENDOR_TAGS) + r"))?")   # 打印之前再核: 和 reply_id_prefix 同一个规矩
_REPLY_WORDS = frozenset({REPLY_NOT_GIVEN, REPLY_ODD_MODEL, REPLY_NO_UNDERSCORE, REPLY_ODD_ID, REPLY_OTHERS})


def _plain_str(x: Any) -> Optional[str]:
    """先认类型, 再做别的: 是 str (含子类) → 拷成一个普通的 str; 别的 → None。
    按 type(x) 认 (和 isinstance 一样认子类, 但不读 x 的任何属性: __class__ 冒充不了, 读属性抛错也碰不到);
    拷成普通的 str 之后, 子类改写的 __eq__ / __bool__ / __len__ / __hash__ / split 一个都碰不到。
    回包里的怪对象要是在这几个函数里抛错, 会从 Pass._call 冲出 run_pass, 连花了多少钱那一行都打不出来。"""
    return str.__str__(x) if issubclass(type(x), str) else None


def reply_model_word(model: Any) -> str:
    """回包里的模型名 → 原样 (只许像模型名的: 字母数字开头, 只有字母数字和 . _ : @ / -, 最长 64); 别的换成写死的词。
    先认类型 (_plain_str) 再做任何比较: 不是字符串的对象一次比较都不做 (它的 __eq__ / __bool__ 抛错也碰不到)。"""
    s = _plain_str(model)
    if s is None:
        return REPLY_NOT_GIVEN if model is None else REPLY_ODD_MODEL
    if not s:
        return REPLY_NOT_GIVEN
    return s if _REPLY_MODEL_RE.fullmatch(s) else REPLY_ODD_MODEL


def reply_id_prefix(msg_id: Any) -> str:
    """消息 id → 开头的前缀 (msg / msg_bdrk / msg_vrtx), id 剩下的部分一个字都不带。按下划线切开:
    第一段是 1–8 个小写字母的才要 (不是 → 【开头认不出】; 没有下划线 → 【没有下划线】);
    第二段只有在写死的单子 ID_VENDOR_TAGS (bdrk / vrtx) 里才留, 不在单子里的 (小写字母加数字的、像单词的, 什么样子都一样) 不留;
    再往后的一概不要。打出来的只可能是第一段, 或者第一段 + 单子里的一个词。"""
    s = _plain_str(msg_id)
    if not s:
        return REPLY_NOT_GIVEN
    parts = s.split("_")
    if len(parts) < 2:
        return REPLY_NO_UNDERSCORE
    if not _ID_FIRST_RE.fullmatch(parts[0]):
        return REPLY_ODD_ID
    return f"{parts[0]}_{parts[1]}" if parts[1] in ID_VENDOR_TAGS else parts[0]


def printable_model_word(word: Any) -> str:
    """打印之前再核一遍 (计数的键不管从哪来): 写死的词或像模型名的原样, 别的一律 【不像模型名】。同样先认类型。"""
    s = _plain_str(word)
    return s if s is not None and (s in _REPLY_WORDS or _REPLY_MODEL_RE.fullmatch(s)) else REPLY_ODD_MODEL


def printable_id_prefix(word: Any) -> str:
    """打印之前再核一遍: 写死的词, 或和 reply_id_prefix 同一个规矩的前缀 (第一段 1–8 个小写字母, 后面最多跟 _bdrk / _vrtx),
    别的一律 【开头认不出】。同样先认类型。"""
    s = _plain_str(word)
    return s if s is not None and (s in _REPLY_WORDS or _ID_PREFIX_RE.fullmatch(s)) else REPLY_ODD_ID


class Budget:
    """调用【之前】reserve: 已花的 + 在路上的预留 + 这一次的预留 会越线 → 回 False, 这次不调, 之后也都不调。

    settle 把预留换成中转站回报的实数; 回报里没有用量 (None / 全 0) 时按预留记, 宁可多算。线程安全。
    """

    def __init__(self, max_weighted: int = MAX_WEIGHTED_TOKENS, max_calls: int = MAX_CALLS):
        self.max_weighted = min(int(max_weighted), MAX_WEIGHTED_TOKENS)
        self.max_calls = min(int(max_calls), MAX_CALLS)
        self.spent = 0
        self.reserved = 0
        self.calls = 0
        self.usage_missing = 0
        self.stopped: Optional[str] = None
        self.by_model: dict[str, dict] = {}
        # 11-25 (I-38): 只是记下来给摘要看, 不进 spent、不改预留。和 by_model 的 input / output 是同一批调用 (拿到了用量的)
        self.usage_split = {k: 0 for k, _f in USAGE_FIELDS}      # 四项各自加起来 (只加回报了的)
        self.usage_reported = {k: 0 for k, _f in USAGE_FIELDS}   # 四项各在几次调用里回报了 (没回报的不当 0)
        self.input_per_call: list[int] = []                      # 每次调用的总输入 (input + 写缓存 + 读缓存)
        self._lock = threading.Lock()

    def reserve(self, estimate: int) -> bool:
        with self._lock:
            if self.stopped:
                return False
            if self.calls + 1 > self.max_calls:
                self.stopped = "max_calls"
                return False
            if self.spent + self.reserved + estimate > self.max_weighted:
                self.stopped = "max_tokens"
                return False
            self.calls += 1
            self.reserved += estimate
            return True

    def settle(self, estimate: int, model: str, usage: Optional[dict]) -> None:
        with self._lock:
            self.reserved -= estimate
            m = self.by_model.setdefault(model, {"calls": 0, "input": 0, "output": 0, "weighted": 0,
                                                 "est_calls": 0, "est_weighted": 0})
            m["calls"] += 1
            tin = tout = 0
            if usage:
                tin = int(usage.get("input", 0)) + int(usage.get("cache_write", 0)) + int(usage.get("cache_read", 0))
                tout = int(usage.get("output", 0))
            if tin <= 0:
                self.usage_missing += 1
                self.spent += estimate
                m["weighted"] += estimate
                m["est_calls"] += 1          # 没拿到用量 (含失败的调用): 按预留记, 报告里的钱也要把这一块算进去
                m["est_weighted"] += estimate
                return
            w = MP.weighted_tokens(tin, tout)
            self.spent += w
            m["input"] += tin
            m["output"] += tout
            m["weighted"] += w
            for k, _f in USAGE_FIELDS:                # 中转站没回报的那一项: 不加、不当 0, 只是这一项少数一次
                if usage.get(k) is not None:
                    self.usage_split[k] += int(usage[k])
                    self.usage_reported[k] += 1
            self.input_per_call.append(tin)

    def release(self, estimate: int, model: str) -> None:
        """这一次调用失败了 (没拿到回报)。按预留记账: 失败的调用中转站收不收钱不知道, 当它收了。"""
        self.settle(estimate, model, None)


def call_estimate(prompt: str, sizes: list[tuple[int, int]]) -> int:
    """一次调用预留多少输入当量 token: 图片按纸面公式 ×2, 提示词一个字算一个 token, 输出按 max_tokens 满打满算。"""
    img = sum(image_tokens_estimate(w, h) for w, h in sizes) * ESTIMATE_MARGIN
    return img + len(prompt) + MP.OUTPUT_WEIGHT * MAX_OUTPUT_TOKENS


# ════════════════════════════════════════════════════════════════════
# 试跑的计划 (干跑和正式跑共用一份)
# ════════════════════════════════════════════════════════════════════

def run_plan(tier: str) -> list[dict]:
    """这一档要跑哪几轮。每轮: tag / model / long_side / mode(grouped|single) / subset(只跑前 20 张常规图)。

    每一档自己跑两轮 (a / b) 加逐题单问: 便宜档要靠自己过线, 不借中档的结果。大图对比只在参照档做一次。
    """
    tiers = ["mid", "cheap"] if tier == "both" else [tier]
    plan: list[dict] = []
    for i, t in enumerate(tiers):
        model = TIERS[t]
        sfx = "" if t == "mid" else "-haiku"
        plan.append({"tag": f"img-g1{sfx}-a", "tier": t, "model": model, "long_side": LONG_SIDE, "mode": "grouped",
                     "subset": False})
        plan.append({"tag": f"img-g1{sfx}-b", "tier": t, "model": model, "long_side": LONG_SIDE, "mode": "grouped",
                     "subset": False})
        plan.append({"tag": f"img-g1{sfx}-single", "tier": t, "model": model, "long_side": LONG_SIDE, "mode": "single",
                     "subset": True})
        if i == 0:
            plan.append({"tag": f"img-g1{sfx}-1568", "tier": t, "model": model, "long_side": LONG_SIDE_BIG,
                         "mode": "grouped", "subset": True})
    return plan


def planned_calls(bank: dict, plan: list[dict], n_images: int, n_subset: int, n_column_files: int) -> dict:
    n_groups = len(bank["call_groups"])
    n_model_q = len(model_question_ids(bank))
    per_run = {}
    for r in plan:
        n = n_subset if r["subset"] else n_images
        per_run[r["tag"]] = n * (n_groups if r["mode"] == "grouped" else n_model_q)
    return {"per_run": per_run, "column_check": n_column_files,
            "total": sum(per_run.values()) + n_column_files}


def paper_estimate(bank: dict, plan: list[dict], n_images: int, n_subset: int, n_column_files: int) -> dict:
    """纸面估算 (设计 §4 的假设: 3:4 的封面、图片 token = 宽 × 高 ÷ 750、每次调用 900 token 提示词、每张图 300 token 输出)。
    不是实测; 试跑量出来的 token 数才是实数。"""
    n_groups = len(bank["call_groups"])
    n_model_q = len(model_question_ids(bank))
    per_tier: dict[str, dict] = {}
    for r in plan:
        n = n_subset if r["subset"] else n_images
        calls = n * (n_groups if r["mode"] == "grouped" else n_model_q)
        img = image_tokens_estimate(round(r["long_side"] * 3 / 4), r["long_side"])
        t = per_tier.setdefault(r["tier"], {"model": r["model"], "calls": 0, "input": 0, "output": 0})
        t["calls"] += calls
        t["input"] += calls * (img + 900)
        t["output"] += n * 300
    ref = plan[0]
    col_img = image_tokens_estimate(round(LONG_SIDE * 3 / 4), LONG_SIDE)
    t = per_tier.setdefault(ref["tier"], {"model": ref["model"], "calls": 0, "input": 0, "output": 0})
    t["calls"] += n_column_files
    t["input"] += n_column_files * (col_img + 300)
    t["output"] += n_column_files * 50
    total_yuan = 0.0
    for t in per_tier.values():
        t["weighted"] = MP.weighted_tokens(t["input"], t["output"])
        t["yuan"] = round(MP.yuan(t["model"], t["input"], t["output"]) or 0.0, 2)
        total_yuan += t["yuan"]
    return {"per_tier": per_tier, "yuan": round(total_yuan, 2),
            "weighted": sum(t["weighted"] for t in per_tier.values())}


# ════════════════════════════════════════════════════════════════════
# 一致率与过线
# ════════════════════════════════════════════════════════════════════

def _pairs(left: dict, right: dict, qid: str) -> list[tuple[str, str]]:
    """两轮里同一张图、这道题都有有效答案的那些对。left / right: {图的序号: assemble 的结果}。"""
    out = []
    for key, a in left.items():
        b = right.get(key)
        if b is None or qid not in a["answers"] or qid not in b["answers"]:
            continue
        out.append((a["answers"][qid], b["answers"][qid]))
    return out


def compare(bank: dict, left: dict, right: dict, *, need_agree: float, need_kappa: Optional[float],
            min_pairs: int = MIN_PAIRS) -> dict[str, dict]:
    """逐题比两轮。回 {题号: {n, agree, kappa, top_share, verdict}}。

    verdict: pass / fail / kappa_undefined (答案一边倒或 κ 算不出: 不算过, 记「还没验证」) / too_few (对数不够, 不下结论)。
    抄字题 (text) 按 transcriptions_match 比, 线是 0.85, 没有 κ。
    """
    idx = question_index(bank)
    out: dict[str, dict] = {}
    for qid in [q["id"] for q in bank["questions"]]:
        pairs = _pairs(left, right, qid)
        n = len(pairs)
        if idx[qid]["type"] == "text":
            ag = (sum(1 for a, b in pairs if transcriptions_match(a, b)) / n) if n else None
            verdict = "too_few" if n < min_pairs else ("pass" if ag >= PASS_TEXT_MATCH else "fail")
            out[qid] = {"n": n, "agree": ag, "kappa": None, "top_share": None, "verdict": verdict}
            continue
        ag = agree(pairs)
        kp = kappa(pairs)
        flat = [x for p in pairs for x in p]
        top = (Counter(flat).most_common(1)[0][1] / len(flat)) if flat else None
        if n < min_pairs:
            verdict = "too_few"
        elif need_kappa is not None and (kp is None or (top is not None and top >= LOPSIDED)):
            verdict = "kappa_undefined"
        elif ag >= need_agree and (need_kappa is None or kp >= need_kappa):
            verdict = "pass"
        else:
            verdict = "fail"
        out[qid] = {"n": n, "agree": ag, "kappa": kp, "top_share": top, "verdict": verdict}
    return out


def tier_verdicts(same: dict[str, dict], single: Optional[dict[str, dict]]) -> dict[str, str]:
    """一档模型自己的逐题结论: 同模型两轮过线, 且分组问和单题问对得上。

    pass / fail / kappa_undefined / too_few / ask_alone (两轮过了, 但分组问和单题问对不上 → 这题以后单独问)。
    """
    out = {}
    for qid, s in same.items():
        v = s["verdict"]
        if v == "pass" and single is not None:
            sv = single.get(qid, {}).get("verdict")
            if sv == "fail":
                v = "ask_alone"
            elif sv == "too_few":
                v = "too_few"
        out[qid] = v
    return out


def model_choice(mid: Optional[dict[str, str]], cheap: Optional[dict[str, str]],
                 cross: Optional[dict[str, dict]]) -> dict:
    """用哪一档。便宜档只有在【中档留下的每一道题】上自己过线、并且和中档对得上, 才用; 否则中档。
    只跑了一档时不下「选哪档」的结论。"""
    if mid is None or cheap is None or cross is None:
        return {"choice": "not_compared", "blocking": []}
    kept = [q for q, v in mid.items() if v in ("pass", "ask_alone")]
    if not kept:
        return {"choice": "none_kept", "blocking": []}
    blocking = [q for q in kept
                if cheap.get(q) not in ("pass", "ask_alone") or cross.get(q, {}).get("verdict") != "pass"]
    return {"choice": "mid" if blocking else "cheap", "blocking": blocking, "kept": kept}


# ════════════════════════════════════════════════════════════════════
# 报告 (只有计数)
# ════════════════════════════════════════════════════════════════════

def fmt(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.2f}"


_VERDICT_ZH = {"pass": "过", "fail": "不过", "kappa_undefined": "kappa_undefined（没验证，不算过）",
               "too_few": "对数不够，不下结论", "ask_alone": "过，但要单独问", None: "—"}


def projected_unusable(regular_n: int, regular_bad: int, awkward: dict[str, dict]) -> Optional[float]:
    """把试跑的失败率折成「全量 3,514 篇里用不了的占比」: 每一类按设计 §1.4 的篇数加权。样本是 0 的那一类不估。"""
    def rate(kinds: tuple[str, ...]) -> Optional[float]:
        n = sum(awkward.get(k, {}).get("n", 0) for k in kinds)
        bad = sum(awkward.get(k, {}).get("n", 0) - awkward.get(k, {}).get("ok", 0) for k in kinds)
        return None if n == 0 else bad / n
    r_reg = None if regular_n == 0 else regular_bad / regular_n
    r_heic, r_big = rate(("heic", "empty_type")), rate(("big",))
    if r_reg is None or r_heic is None or r_big is None:
        return None
    rest = BACKFILL_TOTAL - BACKFILL_VIDEO - BACKFILL_DELETED - BACKFILL_HEIC_OR_EMPTY - BACKFILL_BIG
    bad = BACKFILL_VIDEO + BACKFILL_DELETED + BACKFILL_HEIC_OR_EMPTY * r_heic + BACKFILL_BIG * r_big + rest * r_reg
    return bad / BACKFILL_TOTAL


def build_report(res: dict) -> str:
    """res 是 first_image_trial.run_trial 的结果 (全是计数和状态词)。回 Markdown。"""
    L: list[str] = []
    add = L.append
    add("# 首图试跑报告（只有计数）")
    add("")
    add(f"- 题库 {res['bank_version']} · sha256 前 12 位 `{res['bank_sha'][:12]}` · 状态 {res['bank_status']}")
    add(f"- 档位 {res['tier']} · 每层上限 {res['cap'] if res['cap'] is not None else '设计全量'} · "
        f"{'干跑（没下载、没调模型）' if res['dry_run'] else '正式跑'}")
    add(f"- 结束方式：{res['ended']}")
    add("- 这份报告里没有图片、标题、封面上的字、文件名、链接、note_id；项目名是仓库 mappings/ 里本来就有的。")
    add("")
    add("## 1. 抽到的样本")
    add("")
    s = res["sample"]
    add(f"- 常规图 {s['regular']} 张（四个项目各 6 爆 6 趴，设计 48）；难办的文件 {s['awkward']} 个（设计 12）；"
        f"封面检查 {s['cover_check']} 篇 / {s['cover_check_projects']} 张表（设计 39 / 13）；"
        f"列检查 {s['column_check']} 篇（设计 6）")
    add("- 常规图各格够不够数（项目:爆趴 = 抽到几张）：" + "，".join(f"{k}={v}" for k, v in s["available"]["regular"].items()))
    add("- 难办的文件各类抽到：" + "，".join(f"{k}={v}" for k, v in s["available"]["awkward"].items()))
    add("")
    add("## 2. 计划与花费")
    add("")
    p = res["plan"]
    add("| 轮次 | 模型 | 长边 | 问法 | 计划调用 |")
    add("|---|---|---|---|---|")
    for r in p["runs"]:
        add(f"| {r['tag']} | {r['model']} | {r['long_side']} | {'分组（一次一组，最多 4 题）' if r['mode'] == 'grouped' else '逐题单问'} "
            f"| {p['calls']['per_run'][r['tag']]} |")
    add(f"| 列检查（只问 img_kind） | {p['runs'][0]['model']} | {LONG_SIDE} | 单题 | {p['calls']['column_check']} |")
    add("")
    add(f"- 计划调用合计 {p['calls']['total']} 次；纸面估算 {p['paper']['weighted']:,} 输入当量 token，约 {p['paper']['yuan']} 元"
        f"（{MP.ASSUMED_NOTE}；纸面公式不是实测）")
    add(f"- 硬上限：{res['budget']['max_weighted']:,} 输入当量 token（输入 + 5 × 输出；全按中档价约 "
        f"{MP.yuan_of_weighted(TIERS['mid'], res['budget']['max_weighted']):.0f} 元）和 {res['budget']['max_calls']} 次调用，"
        "每次调用之前查，会越线就不调")
    if res["dry_run"]:
        add("")
        add("干跑到此为止：没有下载任何附件，没有调用模型，没有花钱。")
        return "\n".join(L) + "\n"
    b = res["budget"]
    add(f"- 实际：调用 {b['calls']} 次；{b['spent']:,} 输入当量 token；没拿到用量（含失败的调用）、按预留记的 {b['usage_missing']} 次")
    add("")
    add("| 模型 | 调用 | 输入 token | 输出 token | 约合（元） |")
    add("|---|---|---|---|---|")
    any_est = False
    for model, m in sorted(b["by_model"].items()):
        y = MP.yuan(model, m["input"], m["output"])
        if m.get("est_calls"):
            # 有调用没回报用量: 这些按预留的 token 折成钱加进去, 标出来 —— 不能让「没回报」看起来像「没花钱」
            any_est = True
            ye = MP.yuan_of_weighted(model, m["est_weighted"])
            y = None if (y is None or ye is None) else y + ye
            add(f"| {model} | {m['calls']} | {m['input']:,} | {m['output']:,} | {fmt(y)}（含 {m['est_calls']} 次按预留估的） |")
        else:
            add(f"| {model} | {m['calls']} | {m['input']:,} | {m['output']:,} | {fmt(y)} |")
    add("")
    if any_est:
        add("输入 / 输出两列只有中转站回报了用量的调用；没回报的（含失败的）按预留的 token 折成钱算进「约合」，是往高估。")
        add("")
    add(f"元是{MP.ASSUMED_NOTE}；token 数是中转站回报的。")
    add("")
    t = res["timing"]
    add(f"- 每次调用用时：中位 {fmt(t['median_s'])} 秒，最慢 {fmt(t['max_s'])} 秒（{t['n']} 次）")
    for tag, per in sorted(res["per_image"].items()):
        if not tag.endswith(("-a", "-1568")):          # 第二轮和逐题单问是核对用的, 不是以后每张图的花法
            continue
        if per.get("no_usage"):
            add(f"- {tag}：有 {per['no_usage']} 次调用中转站没回报用量，每张图花多少算不出，经验卡和每晚的花费也不估（{per['images']} 张）")
            continue
        add(f"- {tag}：每张图平均输入 {per['input']:,.0f} / 输出 {per['output']:,.0f} token（{per['images']} 张），"
            f"约 {fmt(per['yuan'])} 元一张 → 经验卡那 {CARD_POSTS} 篇约 {fmt(per['yuan'] * CARD_POSTS if per['yuan'] is not None else None)} 元，"
            f"每晚新帖（{NIGHTLY_IMAGES} 张）一个月约 {fmt(per['yuan'] * NIGHTLY_IMAGES * 30 if per['yuan'] is not None else None)} 元")
    add("")
    add("## 3. 下载与解图")
    add("")
    d = res["download"]
    add(f"- 飞书下载：成功 {d['ok']}，失败 {d['failed']}（按原因：" + ("，".join(f"{k}={v}" for k, v in sorted(d['by_status'].items())) or "无")
        + f"）；每个文件中位 {fmt(d['median_s'])} 秒；合计 {d['bytes'] / 1e6:.1f} MB")
    if d.get("detail"):
        add("- 飞书拒绝下载的细项（HTTP 状态码 / 飞书错误码 / 这次带没带 extra）：" + "，".join(f"{k}={v}" for k, v in sorted(d["detail"].items())))
    add("- 原图像素分布：" + ("，".join(f"{k}={v}" for k, v in sorted(res['pixels'].items())) or "无"))
    u = res["usable"]
    add(f"- 常规图可用：{u['regular_ok']} / {u['regular_n']}"
        f"（下载失败 {u['regular_download_failed']}，解不开 {u['regular_decode_failed']}，答「不是封面」{u['regular_not_cover']}，"
        f"模型没答成 {u['regular_no_answer']}）→ {_bar(u['regular_share'], PASS_USABLE, u['regular_n'] >= MIN_PAIRS)}")
    for kind, want in AWKWARD_PLAN:
        a = res["awkward"].get(kind, {"n": 0, "ok": 0})
        what = "记成 first_is_video、没有调模型" if kind == "video" else "下载并解开"
        add(f"- {kind}：{a['ok']} / {a['n']} {what}（设计要 {want} 个）")
    pu = res["projected_unusable"]
    add(f"- 折算到全量 {BACKFILL_TOTAL:,} 篇，用不了的占比：{fmt(pu)}（线 ≤ {PASS_UNUSABLE_PROJECTED:.2f}；"
        f"其中视频 {BACKFILL_VIDEO}、已删 {BACKFILL_DELETED} 是定数）" if pu is not None
        else "- 折算到全量用不了的占比：样本不够，没算")
    add("")
    add("## 4. 列检查（RIO / TXQ / WTG：内容配图是不是帖子自己的图）")
    add("")
    c = res["column_check"]
    add(f"- {c['posts']} 篇里，「内容配图」答封面且「笔记截图」答不是封面的 {c['ok']} 篇；设计要 6 篇全对 → "
        + ("过" if c["posts"] >= 6 and c["ok"] == c["posts"] else "没过或没做全，这三个项目的取列规则先别用"))
    add("")
    add("## 5. 封面检查（多图的帖，第一个附件是不是封面）")
    add("")
    add("试跑不让任何人看到图片，所以这一步只核「第一个附件下得到、解得开」。「第一个附件就是封面」要人确认；"
        "没确认的表，多图的帖一律带 cover_unconfirmed，不上经验卡、不进封面建议。")
    add("")
    add("| 项目 | 抽到 | 下得到解得开 | cover_unconfirmed |")
    add("|---|---|---|---|")
    for proj, cc in sorted(res["cover_check"].items()):
        add(f"| {proj} | {cc['n']} | {cc['ok']} | {'是' if cc['cover_unconfirmed'] else '否（题库里已确认）'} |")
    add("")
    add("## 6. 逐题一致率")
    add("")
    for tier, tv in res["tiers"].items():
        add(f"### {tier}（{TIERS[tier]}）")
        add("")
        add("| 题 | 两轮对数 | 一致率 | κ | 最常见答案占比 | 分组对单题（对数 / 一致率） | 这一档自己的结论 |")
        add("|---|---|---|---|---|---|---|")
        for qid, sm in tv["same"].items():
            sg = (tv.get("single") or {}).get(qid)
            add(f"| {qid} | {sm['n']} | {fmt(sm['agree'])} | {fmt(sm['kappa'])} | {fmt(sm['top_share'])} | "
                f"{(str(sg['n']) + ' / ' + fmt(sg['agree'])) if sg else '—'} | {_VERDICT_ZH[tv['verdicts'][qid]]} |")
        add("")
        cnt = Counter(tv["verdicts"].values())
        add("小结：" + "，".join(f"{_VERDICT_ZH[k]} {v} 题" for k, v in cnt.most_common())
            + f"；整轮答案无效（自相矛盾 / 解析不了）的图 {tv['invalid_images']} 张；标题对比落在灰带（0.60–0.80）的 {tv['grey']} 张")
        if tv.get("big"):
            worst = min((x["agree"] for x in tv["big"].values() if x["agree"] is not None), default=None)
            add(f"长边 {LONG_SIDE} 对 {LONG_SIDE_BIG}（{SUBSET_N} 张）：逐题一致率最低 {fmt(worst)}（只报告，不设线）")
        add("")
    if res.get("cross"):
        add("### 中档对便宜档")
        add("")
        add("| 题 | 对数 | 一致率 | κ | 结论 |")
        add("|---|---|---|---|---|")
        for qid, x in res["cross"].items():
            add(f"| {qid} | {x['n']} | {fmt(x['agree'])} | {fmt(x['kappa'])} | {_VERDICT_ZH[x['verdict']]} |")
        add("")
    add("## 7. 验收")
    add("")
    mc = res["model_choice"]
    zh = {"cheap": "便宜档：中档留下的每一道题，便宜档都自己过线、并且和中档对得上",
          "mid": "中档：便宜档在这些题上没过或和中档对不上 → " + "、".join(mc.get("blocking") or []),
          "not_compared": "这次只跑了一档，没有两档对比，不下「选哪档」的结论",
          "none_kept": "中档没有一道题过线，先改题再说"}[mc["choice"]]
    add(f"- 用哪一档：{zh}")
    add("- 没做的两项（要人看图，试跑不让图片离开内存）：模型答得对不对的人工核对（20 张 × 11 道客观题）、"
        "每张表「第一个附件是不是封面」。所以这次的验收只凭模型之间的一致；设计里这是选项 (b)。")
    add(f"- 结束方式：{res['ended']}。不是「跑完」的话，上面的数只覆盖跑到的那一部分，不能当验收结论。")
    return "\n".join(L) + "\n"


def _bar(v: Optional[float], need: float, enough: bool) -> str:
    if v is None or not enough:
        return f"{fmt(v)}（样本不够，不下结论；线 ≥ {need:.2f}）"
    return f"{fmt(v)}（线 ≥ {need:.2f}，{'过' if v >= need else '不过'}）"
