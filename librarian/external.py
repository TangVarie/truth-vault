"""librarian/external.py — 外部参考书架 (D-117 ②, J-14; D-138 起按「最近涨得快」上架)。

别家同品类的外部笔记 (truth_vault.external_notes, Jev 每周抓) 做成「外部参考」卡, 借卡时和内部卡一起给 LLM 挑,
每次至少 min_external 张、最多 max_per_borrow 张。它们【不进】truth_vault.notes、不当爆文 (D-117 ①: 不是同一种帖子,
混进来会带偏闸二 / 闸三)。

上架看【最近涨得快】, 不看总评论数 (D-138): 按总评论数排出来的多是老帖 (11-02 只读: 旧规则给模型看的 5 个品类 30 张里,
24 张是 90 天以前发的、17 张一年以前)。发帖时间从 note_id 解 (前 8 位十六进制 = unix 秒, 外部表的 publish_time 列是空的):
  · 抓到时发出 3–max_age_days 天 (不到 3 天的评论还没涨完), 且是最近 FRESH_DAYS 天里抓到的;
  · 评论 ≥ min_comments;
  · 日均评论 = 评论 / max(发出天数, 3) 不低于同品类这批帖 (同样 3–max_age_days 天、最近抓到的, 不管有没有产品) 的中位数;
  · 每个品类按日均评论从高到低给模型看前 show_per_request 张。卡的 rank_score 是日均评论在同品类这批帖里的百分位,
    卡上带发出几天、每天多少条评论, 和 Jev 给这篇答的结构题 (开头怎么起、有没有转折、结尾问没问读者……)。

哪些请求有:
  · 只给显式带了 explore 的消费方 (写作台; 规律臂、探索臂都给 —— 两臂只差已验证规律, 对照才干净);
    不带这个键的老消费方 (通道 1 / 旧版写作台) 不给, 缓存键也不变;
  · 只给同品类的项目: brief 的品牌 / 项目名里出现 prompts/external_shelf_v1.json 里某品类登记的品牌名。
    写作台那边发牌也认这张表 (aw deskcore/priors.py 的 EXT_CATEGORY_BY_PROJECT 照抄, 两边各有钉表的用例)。

卡长什么样: 不带外部的品牌名 —— 只收 Jev 分诊判了没带产品、不像广告的帖 (外部品牌认不全, 只能要本来就没提产品的)。
分诊漏网、正文里仍点了别家品牌的 (配置的 mask_terms), 2026-10-19 起 (D-120) 不再整篇不收, 而是把品牌名换成「某品牌」
再上架 —— 帖子的结构和钩子本来就跟品牌名无关, 整篇丢掉是浪费。点到我们自己登记品牌的照旧不上架: 那多半是我们自己
铺的帖, 不是"别家的自然流量"。卡头写明「外部参考 · 只借结构不抄内容」。

fail-open: 配置读不了 / 查库失败 / 这个品类还没有外部帖 → 这次没有外部卡, 照常选内部卡。结构题查不了 → 卡照给, 只是不带结构。
"""

from __future__ import annotations

import bisect
import hashlib
import json
import logging
import re
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("flywheel_librarian")

CONFIG_PATH = Path(__file__).resolve().parent.parent / "prompts" / "external_shelf_v1.json"
ID_PREFIX = "ext:"
SHELF_TTL_S = 600           # 外部表一周才进一次货; 每个请求 (包括命中缓存的) 都去拉一个品类的正文太浪费, 进程里留 10 分钟
_shelf: dict = {}           # 品类 → (卡, 取的时刻)
_PAGE = 1000                # PostgREST 单页上限; 一个品类最近 45 天 ≤ 约 240 篇 (Jev 每月每品类最多进 160 篇), 一页就够
_MAX_PAGES = 5

DAY_S = 86400
MIN_AGE_DAYS = 3            # 抓到时发出不到 3 天: 评论还在涨, 日均评论偏高, 不算
VELOCITY_FLOOR_DAYS = 3     # 日均评论的分母至少 3 天 (和 MIN_AGE_DAYS 一样; 分开写是因为意思不同)
FRESH_DAYS = 45             # 只看最近 45 天里抓到的 (Jev 每周抓; 一个多月没再抓到, 「最近涨得快」就无从说起)
EXCERPT_CAP = 600           # 选中卡回给消费方的摘录上限 (内部卡视图本来就截在 600 字, 外部卡是标题 + 整篇正文)

EXTERNAL_RUN_TAG = "external"   # Jev 给外部帖答题写的 run_tag (同 scripts/check_external_direction.py)
STRUCTURE_QIDS = ("title_is_question", "opening_type", "turning_point", "ending_asks_reader",
                  "asks_for_help", "own_experience")
_OPENING = {
    "具体事件": "开头先讲一件具体的事",
    "身份自述": "开头先讲自己的身份",
    "观点断言": "开头先下一个判断",
    "提问": "开头先抛一个问题",
    "数据事实": "开头先摆一个数字或事实",
    "感叹情绪": "开头先是一句感叹",
}
_YES = (
    ("title_is_question", "标题是问句"),
    ("turning_point", "中间有一次前后转折"),
    ("asks_for_help", "在向大家讨主意"),
    ("own_experience", "讲的是自己的经历"),
    ("ending_asks_reader", "结尾问了读者"),
)

_cache: dict = {}


def load_config(path: Path = CONFIG_PATH) -> Optional[dict]:
    key = str(path)
    if key in _cache:
        return _cache[key]
    try:
        c = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(c.get("categories"), dict) or int(c["max_per_borrow"]) < 1:
            raise ValueError("缺 categories / max_per_borrow")
        if int(c["max_age_days"]) < MIN_AGE_DAYS or int(c["min_comments"]) < 0 or int(c["show_per_request"]) < 1:
            raise ValueError("max_age_days / min_comments / show_per_request 不对")
        if not 0 <= int(c.get("min_external") or 0) <= int(c["max_per_borrow"]):
            raise ValueError("min_external 要在 0 和 max_per_borrow 之间")
    except Exception:  # noqa: BLE001
        logger.warning("外部参考书架配置读不了 (%s), 本次不给外部卡", path, exc_info=True)
        c = None
    _cache[key] = c
    return c


def categories_for(brief: dict, cfg: dict) -> list[str]:
    """brief 的品牌 / 项目名里出现了哪个品类登记的品牌 → 那些品类 (按配置顺序)。"""
    text = " ".join(str(brief.get(k) or "") for k in ("brand", "project_name")).lower()
    return [cat for cat, brands in cfg["categories"].items()
            if any(b and b.lower() in text for b in brands)]


MASK = "某品牌"


def _registered_brands(cfg: dict) -> list[str]:
    return [b.lower() for bs in cfg["categories"].values() for b in bs if b]


def mask_brands(text: str, cfg: Optional[dict]) -> str:
    """别家品牌名 (mask_terms) → 「某品牌」, 不分大小写。长的先换: 「雅培安素」不会只换掉半截。"""
    terms = sorted({t for t in ((cfg or {}).get("mask_terms") or []) if t}, key=len, reverse=True)
    if not text or not terms:
        return text or ""
    return re.sub("|".join(re.escape(t) for t in terms), MASK, text, flags=re.I)


# ── 发帖时间 / 日均评论 ──────────────────────────────────────────────────
def posted_at(note_id) -> Optional[float]:
    """发帖时刻 (unix 秒): note_id 前 8 位十六进制就是。解不出 (太短 / 不是十六进制) → None。"""
    head = str(note_id or "")[:8]
    if not re.fullmatch(r"[0-9a-fA-F]{8}", head):
        return None
    ts = int(head, 16)
    return float(ts) if ts > 0 else None


def _epoch(value) -> Optional[float]:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def age_at_scrape(row: dict) -> Optional[float]:
    """抓到时发出了几天 (可以带小数)。发帖时间或抓取时间解不出 → None。"""
    posted, fetched = posted_at(row.get("note_id")), _epoch(row.get("fetched_at"))
    if posted is None or fetched is None:
        return None
    return (fetched - posted) / DAY_S


def velocity(row: dict) -> Optional[float]:
    """日均评论 = 评论 / max(抓到时发出的天数, 3)。评论或天数不知道 → None。"""
    age, n = age_at_scrape(row), row.get("comments")
    if age is None or n is None:
        return None
    return int(n) / max(age, VELOCITY_FLOOR_DAYS)


def in_window(row: dict, cfg: dict, now: Optional[float] = None) -> bool:
    """抓到时发出 3–max_age_days 天, 且是最近 FRESH_DAYS 天里抓到的 —— 中位数和上架看的是同一批帖。"""
    now = time.time() if now is None else now
    age, fetched = age_at_scrape(row), _epoch(row.get("fetched_at"))
    return (age is not None and MIN_AGE_DAYS <= age <= int(cfg["max_age_days"])
            and fetched is not None and now - fetched <= FRESH_DAYS * DAY_S)


def qualifies(row: dict, cfg: dict, median: Optional[float], *, now: Optional[float] = None) -> bool:
    """达标: 在窗口里 (in_window)、评论够、日均评论不低于同品类中位数 (``median``; None = 这个品类没有可比的帖, 不收)、
    没带产品、不像广告 (has_product / ad_like 没判过 = 不收: 认不出品牌就不冒险)、标题正文里没点到【我们登记的】品牌
    (那多半是我们自己铺的帖)。别家品牌名不挡, 上架时换成「某品牌」(D-120)。"""
    v = velocity(row)
    text = f"{row.get('title') or ''}\n{row.get('body') or ''}".lower()
    return (in_window(row, cfg, now) and v is not None and median is not None and v >= median
            and (row.get("comments") or 0) >= int(cfg["min_comments"])
            and row.get("has_product") is False and row.get("ad_like") is not True
            and not any(t in text for t in _registered_brands(cfg)))


def _percentile(v: float, pool: list[float]) -> float:
    """``v`` 在 ``pool`` (已排序) 里的中位秩百分位: 比它小的 + 一半和它一样的, 除以总数。"""
    lo, hi = bisect.bisect_left(pool, v), bisect.bisect_right(pool, v)
    return (lo + hi) / 2 / len(pool)


def qualified(rows: list[dict], cfg: dict, *, now: Optional[float] = None) -> list[tuple[dict, float, float]]:
    """按品类算日均评论的中位数 (同品类、在窗口里的帖, 不管有没有产品), 留下达标的, 品类内按日均评论从高到低
    (同速按 note_id)。返回 [(行, 日均评论, 百分位)]; 品类按第一次出现的顺序。纯函数, 馆员上架和方向复核报数都用它。"""
    now = time.time() if now is None else now
    by_cat: dict = {}
    for r in rows:
        by_cat.setdefault(r.get("category"), []).append(r)
    out: list[tuple[dict, float, float]] = []
    for rs in by_cat.values():
        pool = sorted(v for r in rs if in_window(r, cfg, now) and (v := velocity(r)) is not None)
        if not pool:
            continue
        med = statistics.median(pool)
        got = [(r, velocity(r)) for r in rs if qualifies(r, cfg, med, now=now)]
        got.sort(key=lambda t: (-t[1], str(t[0].get("note_id"))))
        out += [(r, v, _percentile(v, pool)) for r, v in got]
    return out


def describe(fq: Optional[dict]) -> Optional[str]:
    """Jev 结构题答案 → 一句人话 (「开头先讲一件具体的事；中间有一次前后转折；结尾问了读者」)。什么都没答 → None。"""
    fq = fq or {}
    parts = [_OPENING[fq["opening_type"]]] if fq.get("opening_type") in _OPENING else []
    parts += [text for qid, text in _YES if fq.get(qid) == "是"]
    return "；".join(parts) or None


def to_card(row: dict, cfg: Optional[dict] = None, *, rate: Optional[float] = None, pct: Optional[float] = None,
            fq: Optional[dict] = None, now: Optional[float] = None) -> dict:
    """``cfg`` 给 mask_terms 用; 不给就读默认配置 (读不了就不换, 但那时整个书架本来就不出卡)。
    ``rate`` / ``pct`` 是 qualified() 算好的日均评论和百分位 (不给就按这一行自己算日均、百分位记 0);
    ``fq`` 是 Jev 给这篇答的结构题; ``now`` 用来算发出几天。"""
    cfg = cfg if cfg is not None else load_config()
    now = time.time() if now is None else now
    n = row.get("comments") or 0
    rate = velocity(row) if rate is None else rate
    posted = posted_at(row.get("note_id"))
    days_ago = int((now - posted) // DAY_S) if posted is not None else None
    per_day = round(rate, 1) if rate is not None else None
    fq = {q: fq[q] for q in STRUCTURE_QIDS if (fq or {}).get(q) is not None}
    why = "别家同品类最近涨得快的帖 (不是帆谷投的, 自然流量)"
    if days_ago is not None and per_day is not None:
        why += f": 发出约 {days_ago} 天, 每天约 {per_day} 条评论 (共 {n} 条)"
        if pct is not None:
            why += f", 快过同品类近期 {round(pct * 100)}% 的帖"
    return {
        "source_note_id": f"{ID_PREFIX}{row['note_id']}",
        "external": True,
        "tier": "外部参考",
        "brand": None,
        "category": row.get("category"),
        "comments": n,
        "posted_days_ago": days_ago,
        "comments_per_day": per_day,
        "fq": fq,
        "rank_score": round(pct, 3) if pct is not None else 0.0,
        "is_curated": False,
        "synthetic": False,
        "hook_type": None,
        "structure": describe(fq),
        "why_it_worked": why,
        "transferable_tactic": "只借结构 / 钩子, 不抄内容, 不提它的品牌",
        "raw_excerpt": mask_brands(f"{row.get('title') or ''} {row.get('body') or ''}".strip(), cfg),
    }


def _category_rows(sb, cat: str, now: float) -> list[dict]:
    """一个品类最近 FRESH_DAYS 天抓到的全部外部帖 (中位数要全体, 不能先按评论 / 产品筛)。"""
    since = datetime.fromtimestamp(now - FRESH_DAYS * DAY_S, timezone.utc).isoformat(timespec="seconds")
    out: list[dict] = []
    for page in range(_MAX_PAGES):
        rows = (
            sb.schema("truth_vault").table("external_notes")
            .select("note_id, category, title, body, comments, has_product, ad_like, fetched_at")
            .eq("category", cat).gte("fetched_at", since)
            .order("note_id").range(page * _PAGE, (page + 1) * _PAGE - 1).execute()
        ).data or []
        out += rows
        if len(rows) < _PAGE:
            return out
    logger.warning("外部参考书架: 品类 %s 最近 %d 天超过 %d 篇, 只看了前 %d 篇", cat, FRESH_DAYS, len(out), len(out))
    return out


def structure_answers(sb, ids: list[str]) -> dict[str, dict[str, str]]:
    """Jev 给这几篇外部帖答的结构题 {note_id: {题: 答}}; 同一题答过几次取最新的。查不了 → {} (卡照给, 不带结构)。"""
    ids = sorted({str(i) for i in ids if i})
    if not ids:
        return {}
    try:
        rows = (
            sb.schema("truth_vault").table("note_feature_answers")
            .select("subject_id, question_id, answer, extracted_at")
            .eq("subject_type", "external_note").eq("run_tag", EXTERNAL_RUN_TAG)
            .in_("question_id", list(STRUCTURE_QIDS)).in_("subject_id", ids)
            .order("extracted_at").limit(_PAGE).execute()
        ).data or []
    except Exception:  # noqa: BLE001
        logger.warning("外部参考卡的结构题查不了, 这次卡上不带结构", exc_info=True)
        return {}
    out: dict[str, dict[str, str]] = {}
    for r in rows:
        if r.get("subject_id") is None or r.get("question_id") not in STRUCTURE_QIDS or r.get("answer") is None:
            continue
        out.setdefault(str(r["subject_id"]), {})[r["question_id"]] = str(r["answer"])
    return out


def fetch_shelf(sb, categories: list[str], cfg: dict, *, now: Optional[float] = None) -> list[dict]:
    """这些品类里达标的外部帖, 每个品类按日均评论取前 show_per_request 篇, 转成卡 (带结构题)。"""
    now = time.time() if now is None else now
    out: list[dict] = []
    for cat in categories:
        top = qualified(_category_rows(sb, cat, now), cfg, now=now)[:int(cfg["show_per_request"])]
        fq = structure_answers(sb, [r["note_id"] for r, _, _ in top])
        out += [to_card(r, cfg, rate=v, pct=p, fq=fq.get(str(r["note_id"])), now=now) for r, v, p in top]
    return out


def shelf_for(sb, brief: dict, *, path: Path = CONFIG_PATH, now: Optional[float] = None) -> list[dict]:
    """这次请求给哪些外部卡。调用方只在显式带 explore 的请求上调。绝不抛。
    按品类在进程里缓存 SHELF_TTL_S 秒; 查库失败不缓存 (下个请求重查)。品类登记了但外部表里还没有 → []。"""
    cfg = load_config(path)
    if not cfg:
        return []
    cats = categories_for(brief, cfg)
    if not cats:
        return []
    now = time.monotonic() if now is None else now
    out: list[dict] = []
    for cat in cats:
        hit = _shelf.get(cat)
        if hit and now - hit[1] < SHELF_TTL_S:
            out += hit[0]
            continue
        try:
            cards = fetch_shelf(sb, [cat], cfg)
        except Exception:  # noqa: BLE001
            logger.warning("外部参考书架查询失败, 这次不给外部卡 (品类 %s)", cat, exc_info=True)
            continue
        _shelf[cat] = (cards, now)
        out += cards
    return out


def digest(cards: list[dict]) -> str:
    """进 library_version 的外部卡指纹: 卡的 id、**卡面摘录和结构**。只认 id 的话, mask_terms 补了一个新品牌, 卡面变了
    而版本没变, 旧缓存里没换掉品牌名的摘录会一直被命中(codex review on TV#202); 结构题晚到也一样。
    发出几天每天都在变, 不进指纹 (命中缓存时按 id 重算, core._refresh_external)。没有外部卡时与以前一样。"""
    parts = sorted(f"{c.get('source_note_id')}\x00{c.get('raw_excerpt') or ''}\x00{c.get('structure') or ''}"
                   for c in cards)
    if not parts:
        return hashlib.sha256(b"").hexdigest()[:10]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:10]


def is_external(card: dict) -> bool:
    return bool(card.get("external"))


def max_per_borrow(path: Path = CONFIG_PATH) -> int:
    cfg = load_config(path)
    return int(cfg["max_per_borrow"]) if cfg else 0


def min_external(path: Path = CONFIG_PATH) -> int:
    """每次借卡至少带几张外部卡 (书架有卡时; 模型一张没挑就补, core._ensure_external)。配置读不了 → 0。"""
    cfg = load_config(path)
    return min(int(cfg.get("min_external") or 0), int(cfg["max_per_borrow"])) if cfg else 0


PROMPT_NOTE = ("标了「外部参考」的卡是别家同品类最近涨得快的帖 (不是帆谷投的, 评论是自然流量; 卡上有发出几天、每天多少条评论): "
               "{pick}, 只借结构 / 钩子, 不抄内容, 不提它的品牌。")


def prompt_note(path: Path = CONFIG_PATH) -> str:
    """候选卡前面那句外部卡用法; 配置读不了 → 空串。min_external = 1 时是「至少挑 1 张、最多 2 张」。"""
    n, m = max_per_borrow(path), min_external(path)
    if not n:
        return ""
    return PROMPT_NOTE.format(pick=f"至少挑 {m} 张、最多 {n} 张" if m else f"最多挑 {n} 张")
