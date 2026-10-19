"""librarian/external.py — 外部参考书架 (D-117 ②, J-14)。

别家同品类、评论 ≥50 的外部笔记 (truth_vault.external_notes, Jev 每周抓) 做成「外部参考」卡, 借卡时和内部卡一起
给 LLM 挑, 每次最多占 max_per_borrow 张。它们【不进】truth_vault.notes、不当爆文 (D-117 ①: 不是同一种帖子,
混进来会带偏闸二 / 闸三)。

哪些请求有:
  · 只给显式带了 explore 的消费方 (写作台; 规律臂、探索臂都给 —— 两臂只差已验证规律, 对照才干净);
    不带这个键的老消费方 (通道 1 / 旧版写作台) 不给, 缓存键也不变;
  · 只给同品类的项目: brief 的品牌 / 项目名里出现 prompts/external_shelf_v1.json 里某品类登记的品牌名。

卡长什么样: 不带外部的品牌名 —— 只收 Jev 分诊判了没带产品、不像广告的帖 (外部品牌认不全, 只能要本来就没提产品的)。
分诊漏网、正文里仍点了别家品牌的 (配置的 mask_terms), 2026-10-19 起 (D-120) 不再整篇不收, 而是把品牌名换成「某品牌」
再上架 —— 帖子的结构和钩子本来就跟品牌名无关, 整篇丢掉是浪费。点到我们自己登记品牌的照旧不上架: 那多半是我们自己
铺的帖, 不是"别家的自然流量"。卡头写明「外部参考 · 只借结构不抄内容」。

fail-open: 配置读不了 / 查库失败 → 这次没有外部卡, 照常选内部卡。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("flywheel_librarian")

CONFIG_PATH = Path(__file__).resolve().parent.parent / "prompts" / "external_shelf_v1.json"
ID_PREFIX = "ext:"
_FETCH_PER_CATEGORY = 200   # 品牌名那道筛在 Python 里, 多取一些再筛; 一个品类每月最多进 160 篇 (Jev 配置)
SHELF_TTL_S = 600           # 外部表一周才进一次货; 每个请求 (包括命中缓存的) 都去拉 200 篇正文太浪费, 进程里留 10 分钟
_shelf: dict = {}           # 品类 → (卡, 取的时刻)

_cache: dict = {}


def load_config(path: Path = CONFIG_PATH) -> Optional[dict]:
    key = str(path)
    if key in _cache:
        return _cache[key]
    try:
        c = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(c.get("categories"), dict) or int(c["max_per_borrow"]) < 1:
            raise ValueError("缺 categories / max_per_borrow")
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


def qualifies(row: dict, cfg: dict) -> bool:
    """达标: 评论够、没带产品、不像广告 (has_product / ad_like 没判过 = 不收: 认不出品牌就不冒险)、
    标题正文里没点到【我们登记的】品牌 (那多半是我们自己铺的帖)。别家品牌名不再挡, 上架时换成「某品牌」(D-120)。"""
    text = f"{row.get('title') or ''}\n{row.get('body') or ''}".lower()
    return ((row.get("comments") or 0) >= int(cfg["min_comments"])
            and row.get("has_product") is False and row.get("ad_like") is not True
            and not any(t in text for t in _registered_brands(cfg)))


def to_card(row: dict, cfg: Optional[dict] = None) -> dict:
    """``cfg`` 给 mask_terms 用; 不给就读默认配置 (读不了就不换, 但那时整个书架本来就不出卡)。"""
    cfg = cfg if cfg is not None else load_config()
    n = row.get("comments") or 0
    return {
        "source_note_id": f"{ID_PREFIX}{row['note_id']}",
        "external": True,
        "tier": "外部参考",
        "brand": None,
        "category": row.get("category"),
        "comments": n,
        "rank_score": 0.0,
        "is_curated": False,
        "synthetic": False,
        "hook_type": None,
        "structure": None,
        "why_it_worked": f"别家同品类的帖 (不是帆谷投的, 自然流量), 评论 {n}",
        "transferable_tactic": "只借结构 / 钩子, 不抄内容, 不提它的品牌",
        "raw_excerpt": mask_brands(f"{row.get('title') or ''} {row.get('body') or ''}".strip(), cfg),
    }


def fetch_shelf(sb, categories: list[str], cfg: dict) -> list[dict]:
    """这些品类里达标的外部帖, 每个品类按评论数取前 show_per_request 篇, 转成卡。"""
    out: list[dict] = []
    for cat in categories:
        rows = (
            sb.schema("truth_vault").table("external_notes")
            .select("note_id, category, title, body, comments, has_product, ad_like")
            .eq("category", cat).gte("comments", int(cfg["min_comments"]))
            .eq("has_product", False).or_("ad_like.is.null,ad_like.eq.false")
            .order("comments", desc=True).order("note_id")
            .limit(_FETCH_PER_CATEGORY).execute()
        ).data or []
        out += [to_card(r, cfg) for r in rows if qualifies(r, cfg)][:int(cfg["show_per_request"])]
    return out


def shelf_for(sb, brief: dict, *, path: Path = CONFIG_PATH, now: Optional[float] = None) -> list[dict]:
    """这次请求给哪些外部卡。调用方只在显式带 explore 的请求上调。绝不抛。
    按品类在进程里缓存 SHELF_TTL_S 秒; 查库失败不缓存 (下个请求重查)。"""
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
    """进 library_version 的外部卡指纹: 卡的 id **和卡面摘录**。只认 id 的话, mask_terms 补了一个新品牌, 卡面变了
    而版本没变, 旧缓存里没换掉品牌名的摘录会一直被命中(codex review on TV#202)。没有外部卡时与以前一样。"""
    parts = sorted(f"{c.get('source_note_id')}\x00{c.get('raw_excerpt') or ''}" for c in cards)
    if not parts:
        return hashlib.sha256(b"").hexdigest()[:10]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:10]


def is_external(card: dict) -> bool:
    return bool(card.get("external"))


def max_per_borrow(path: Path = CONFIG_PATH) -> int:
    cfg = load_config(path)
    return int(cfg["max_per_borrow"]) if cfg else 0


PROMPT_NOTE = ("标了「外部参考」的卡是别家同品类的帖 (不是帆谷投的, 评论是自然流量): 最多挑 {n} 张, "
               "只借结构 / 钩子, 不抄内容, 不提它的品牌; 同样合适时优先挑帆谷自己的卡。")
