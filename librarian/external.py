"""librarian/external.py — 外部参考书架 (D-117 ②, J-14; D-138 起按「最近涨得快」上架)。

别家同品类的外部笔记 (truth_vault.external_notes, Jev 每周抓) 做成「外部参考」卡, 借卡时和内部卡一起给 LLM 挑,
每次至少 min_external 张、最多 max_per_borrow 张。它们【不进】truth_vault.notes、不当爆文 (D-117 ①: 不是同一种帖子,
混进来会带偏闸二 / 闸三)。

上架看【最近涨得快】, 不看总评论数 (D-138): 按总评论数排出来的多是老帖 (11-02 只读: 旧规则给模型看的 5 个品类 30 张里,
24 张是 90 天以前发的、17 张一年以前)。发帖时间从 note_id 解 (前 8 位十六进制 = unix 秒, 外部表的 publish_time 列是空的):
  · 抓到时发出 3–max_age_days 天 (不到 3 天的评论还没涨完), 且是最近 FRESH_DAYS 天里抓到的;
  · 评论 ≥ min_comments;
  · 日均评论 = 评论 / max(发出天数, 3) 不低于同品类这批帖 (同样 3–max_age_days 天、最近抓到的, 不管有没有产品) 的中位数;
  · 每个品类按日均评论从高到低给模型看前 show_per_request 张 (D-141 起两族各一半, 见下)。卡的 rank_score 是日均评论在同品类
    (D-141 起: 同品类同一族) 这批帖里的百分位,
    卡上带抓到时发出几天、共几条评论、那时每天几条 (三个数是同一次抓取量的, 乘得回去), 另带现在发出几天
    (posted_days_ago, 命中缓存时按 id 重算; 不和日均评论挨着写, 免得读的人拿现在的天数去乘), 和 Jev 给这篇答的结构题
    (开头怎么起、有没有转折、结尾问没问读者……)。why_it_worked 只写抓取那一刻定下的数, 缓存放多久都不过时。

哪些请求有:
  · 只给显式带了 explore 的消费方 (写作台; 规律臂、探索臂都给 —— 两臂只差已验证规律, 对照才干净);
    不带这个键的老消费方 (通道 1 / 旧版写作台) 不给, 缓存键也不变;
  · 只给同品类的项目: brief 的品牌 / 项目名里出现 prompts/external_shelf_v1.json 里某品类登记的品牌名。
    写作台那边发牌也认这张表 (aw deskcore/priors.py 的 EXT_CATEGORY_BY_PROJECT 照抄, 两边各有钉表的用例)。
  · 「至少 min_external 张」只管 min_external_categories 里的品类 (D-140 起 8 个品类全在), 且只塞摘录遮过的卡。

卡长什么样 (D-140, 11-03 起): 不再只收 Jev 分诊判了「没带产品」的帖 —— 那只看标题和约 60 字摘要, 11-03 核查 994 篇
「没带产品」里 482 篇正文点了产品, 上架的卡把别家品牌名原样带了出去。现在带不带产品都收, 品牌 / 产品名靠遮:
  · 模型只【列出】每篇里指向具体品牌 / 产品系列型号 / 店铺 / 售卖机构的专有名称 (scripts/mask_external_names.py 夜跑,
    存在 truth_vault.external_note_masks), 代码核过这些词逐字出现在原文里才收; 上架时按 text_sha 核对原文没变,
    把这些词换成「某品牌」/「某产品」(长的先换, 拉丁字母不分大小写), 再换配置里的 mask_terms。正文别的字一个不动 ——
    要学的是写法 (节奏、结构), 模型从不改写正文。
  · 没有有效遮挡行 (还没列过 / 原文变了 / 表还没建) 的帖: 卡上只给结构、不给原文摘录; 连结构都没有的不上架。
  · 强塞 (每次至少 1 张) 只塞有遮过的摘录的卡, 从不强塞只有结构的卡。8 个品类都在 min_external_categories 里。
  · Jev 全文答的 efficacy_promise (健康功效说法) 是「是」的不上架, 没答的也不上架 (fail-closed, 和写作台发牌一致, F-08)。
点到我们自己登记品牌的照旧不上架: 那多半是我们自己铺的帖, 不是"别家的自然流量"。卡头写明「外部参考 · 只借结构不抄内容」。

产品贴 / 其他分两族排 (D-141, 11-03 起): 正文里把产品当主角 / 解决方案写的帖起量天然慢 —— 11-03 只读, 近 45 天抓到、
抓到时发出 3–90 天、不像广告: 产品贴 220 篇日均评论中位数 0.71, 提问 / 求助 54 篇 4.65, 其他 212 篇 2.84。混在一起排,
戒烟、求职留学给模型看的 6 张里一张产品贴都没有, 写产品贴时没有外部的样子可看。外部参考不许因为写了产品就被压下去:
  · 族看 Jev 全文答的 product_role (最新的有效答案): 主角 / 解决方案 = P; 别的 (顺带一提、只暗示、未出现、没答) = O,
    提问 / 求助的帖也在 O 里。窗口里每一篇都要查 (中位数要全体), 同 fetch_answers 100 篇一批、翻到空页;
  · 中位数按 (品类, 族) 算, 每篇只和自己那族比; 百分位 (rank_score) 也在自己那族里排。一族在窗口里不到 MIN_FAMILY_N 篇,
    这一族的中位数和百分位用整个品类的;
  · 给模型看的 show_per_request 张两族各一半: P 先, 两族轮流, 族内按日均评论从高到低; 一族不够, 另一族接着补满;
  · 卡上 product_in_body: P 是 true、O 是 false, 馆员 prompt 的卡头写「正文写了产品」; 进外部卡指纹 (digest)。
    强塞那张 (D-140 规则) 不看族, 照旧是遮过的卡里日均最高的;
  · product_role 读不了 → 这次当一族排 (D-140 的老样子), 卡上 product_in_body 是 None, warning 只打一次 (恢复了再坏再打)。

fail-open (对内部卡): 配置读不了 / 查库失败 / 这个品类还没有外部帖 → 这次没有外部卡, 照常选内部卡。
fail-closed (对外部卡): Jev 的答案 (功效题 + 结构题) 查不了 → 这个品类这次没有外部卡; 遮挡表读不了 → 全部只给结构。
fail-soft (D-141): product_role 查不了 → 不分族, 照 D-140 排。
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
SHELF_TTL_S = 600           # 外部表一周才进两次货 (Jev 周一、周四, D-139); 每个请求 (包括命中缓存的) 都去拉一个品类的正文太浪费, 进程里留 10 分钟
_shelf: dict = {}           # 品类 → (卡, 取的时刻)
_PAGE = 1000                # PostgREST 单页上限; 一个品类最近 45 天 ≤ 约 540 篇 (Jev 每月每品类最多进 360 篇, D-139), 一页就够
_MAX_PAGES = 5

DAY_S = 86400
MIN_AGE_DAYS = 3            # 抓到时发出不到 3 天: 评论还在涨, 日均评论偏高, 不算
VELOCITY_FLOOR_DAYS = 3     # 日均评论的分母至少 3 天 (和 MIN_AGE_DAYS 一样; 分开写是因为意思不同)
FRESH_DAYS = 45             # 只看最近 45 天里抓到的 (Jev 一周抓两次; 一个多月没再抓到, 「最近涨得快」就无从说起)
EXCERPT_CAP = 600           # 选中卡回给消费方的摘录上限 (内部卡视图本来就截在 600 字, 外部卡是标题 + 整篇正文)

EXTERNAL_RUN_TAG = "external"   # Jev 给外部帖答题写的 run_tag (同 scripts/check_external_direction.py)
STRUCTURE_QIDS = ("title_is_question", "opening_type", "turning_point", "ending_asks_reader",
                  "asks_for_help", "own_experience")
EFFICACY_QID = "efficacy_promise"   # Jev 全文答的健康功效说法 (D-140 / F-08): 只有答了「否」的才上架
ANSWER_QIDS = STRUCTURE_QIDS + (EFFICACY_QID,)
ANSWERS_CHUNK = 100         # 一次 .in_() 带这么多个 id, URL 不会过长 (同 aw deskcore/store.py NOTE_ANSWERS_CHUNK)
_ANSWER_MAX_PAGES = 20      # 每批 100 篇 × 7 题 × 抽取器版本, 一页 1000 行; 翻到这么多页还没到空页 = 不对劲, 当读不了 (不静默截断)
PRODUCT_QID = "product_role"        # Jev 全文答的「正文里产品是什么角色」(D-141 分族用)
PRODUCT_ROLES = ("主角", "解决方案")  # 这两个算产品贴 (P); 顺带一提 / 只暗示 / 未出现 / 没答 都算 O
FAMILY_P, FAMILY_O = "P", "O"
FAMILY_ORDER = (FAMILY_P, FAMILY_O, None)   # 轮流放的顺序; None = product_role 读不了, 不分族 (只有这一族)
MIN_FAMILY_N = 5            # 一族在窗口里不到 5 篇: 中位数就是一两篇的数 (4 篇是中间两篇的平均), 下一次抓取进一两篇就换个样,
                            # 达标的最多也就两篇; 这时用整个品类的中位数和百分位。11-03 只读只有个护的 O 族 (4 篇) 落在这里
_FAMILY_WARNED: list[bool] = []
MASK_TABLE = "external_note_masks"
MASK_RULES = "m1"           # 遮挡规则 (clean_terms / apply_mask) 的版本, 进外部卡指纹: 规则一改, 旧缓存里的摘录全部作废
_MASK_WARNED: list[bool] = []
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
        forced = c.get("min_external_categories") or []
        if not isinstance(forced, list) or any(f not in c["categories"] for f in forced):
            raise ValueError("min_external_categories 要是 categories 里登记过的品类名")
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
MASK_BY_KIND = {"品牌": "某品牌", "产品": "某产品"}
_ASCII_ALNUM = re.compile(r"[A-Za-z0-9]")
_SHORT_LATIN = 3            # 只有拉丁字母 / 数字、不超过 3 个字符的词 (如 HA / GT) 两边不许紧挨着字母数字, 免得把 haha 里的 ha 也换掉


def _registered_brands(cfg: dict) -> list[str]:
    return [b.lower() for bs in cfg["categories"].values() for b in bs if b]


def mask_text_sha(title, body) -> str:
    """遮挡行的 text_sha: sha256(标题 + 换行 + 正文)。列词那一刻的原文; 和现在对不上 = 过期 (D-140)。"""
    return hashlib.sha256(f"{title or ''}\n{body or ''}".encode("utf-8")).hexdigest()


def _short_latin(t: str) -> bool:
    return len(t) <= _SHORT_LATIN and all(_ASCII_ALNUM.fullmatch(ch) for ch in t)


def _term_regex(t: str) -> str:
    """一个词的匹配式: 按【原样】逐字 (re.escape); 短的纯拉丁词两边不许紧挨着字母数字。大小写由调用方用 re.I。"""
    pat = re.escape(t)
    if _short_latin(t):
        pat = rf"(?<![A-Za-z0-9]){pat}(?![A-Za-z0-9])"
    return pat


def _same_term(a: str, b: str) -> bool:
    """替换时算不算同一个词: 按各自原样编的匹配式 (re.I) 互相整串匹配得上, 词边界规则也一样 —— 和替换同一个口径。
    不能拿 casefold 去重 / 编正则: ß、İ、ﬁ 这类字 casefold 之后变了样 (Straße → strasse), re.I 并不认,
    词核过了却换不掉, 名字就漏出去了 (D-140 review)。"""
    return (_short_latin(a) == _short_latin(b)
            and re.fullmatch(_term_regex(a), b, flags=re.I) is not None
            and re.fullmatch(_term_regex(b), a, flags=re.I) is not None)


def clean_terms(terms, text: str) -> list[dict]:
    """模型列出来的词 → 能用的词: 只留在 ``text`` (标题 + 换行 + 正文) 里逐字出现的 (拉丁字母不分大小写, 同替换时的口径),
    去掉空的 / 一个字的 / 带换行的, 按大小写不敏感去重 (先出现的留下; 口径见 _same_term)。k 只认 品牌 / 产品, 别的都当
    品牌 (多遮不漏)。纯函数; mask 脚本存之前用它, 馆员上架前再用一遍 (表里的行不全信)。"""
    out: list[dict] = []
    for item in terms if isinstance(terms, list) else []:
        if isinstance(item, str):
            t, k = item, "品牌"
        elif isinstance(item, dict):
            t, k = item.get("t"), item.get("k")
        else:
            continue
        if not isinstance(t, str):
            continue
        t = t.strip()
        if len(t) < 2 or "\n" in t or any(_same_term(t, o["t"]) for o in out):
            continue
        if not re.search(_term_regex(t), text or "", flags=re.I):
            continue
        out.append({"t": t, "k": k if k in MASK_BY_KIND else "品牌"})
    return out


def apply_mask(text: str, terms: list[dict], cfg: Optional[dict]) -> str:
    """把 ``terms`` (clean_terms 过的) 和配置里的 mask_terms 一起, 一遍换掉: 长的先换 (「某牌甲某系列」不会只换掉半截),
    拉丁字母不分大小写, 换上去的「某品牌」/「某产品」不会再被别的词匹配到。别的字一个不动。
    匹配式按每个词的【原样】编 (和 clean_terms 核对时同一个口径); 去重用 _same_term, 不用 casefold。"""
    if not text:
        return ""
    entries: list[list[str]] = []        # [原样的词, 品牌 / 产品]

    def put(t: str, k: str, override: bool) -> None:
        for e in entries:
            if _same_term(e[0], t):
                if override:
                    e[1] = k
                return
        entries.append([t, k])
    for t in ((cfg or {}).get("mask_terms") or []):
        if isinstance(t, str) and t.strip():
            put(t.strip(), "品牌", False)
    for it in terms or []:
        put(it["t"], it["k"], True)
    if not entries:
        return text
    entries.sort(key=lambda e: len(e[0]), reverse=True)
    rx = re.compile("|".join(f"({_term_regex(t)})" for t, _ in entries), flags=re.I)
    return rx.sub(lambda m: MASK_BY_KIND[entries[m.lastindex - 1][1]], text)


def mask_brands(text: str, cfg: Optional[dict]) -> str:
    """只换配置里的 mask_terms (D-120 那一层): 别家品牌名 → 「某品牌」, 不分大小写, 长的先换。"""
    return apply_mask(text or "", [], cfg)


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


def window_ids(rows: list[dict], cfg: dict, *, now: Optional[float] = None) -> list[str]:
    """在窗口里的帖的 id (算中位数的那一批) —— 分族要给它们每一篇查 product_role (D-141)。"""
    now = time.time() if now is None else now
    return [str(r["note_id"]) for r in rows if r.get("note_id") and in_window(r, cfg, now)]


def family(roles: Optional[dict], note_id) -> Optional[str]:
    """``roles`` ({note_id: product_role}, fetch_roles 给的) 里这篇算哪一族: 主角 / 解决方案 → P, 别的 / 没答 → O。
    ``roles`` 是 None (读不了) → None: 不分族, 整个品类一族 (D-140 的老样子)。"""
    if roles is None:
        return None
    return FAMILY_P if roles.get(str(note_id)) in PRODUCT_ROLES else FAMILY_O


def qualifies(row: dict, cfg: dict, median: Optional[float], *, now: Optional[float] = None) -> bool:
    """便宜的那几道 (不查库): 在窗口里 (in_window)、评论够、日均评论不低于同品类 (D-141 起: 同品类同一族) 的中位数
    (``median``; None = 没有可比的帖, 不收)、不像广告 (ad_like 不是 true)、标题正文里没点到【我们登记的】品牌 (那多半是我们自己铺的帖)。
    D-140 起不看 has_product: 带不带产品都收, 别家品牌 / 产品名上架时按遮挡表换掉 (apply_mask)。
    功效说法那道要查 Jev 的答案, 在 efficacy_ok / qualified 里。"""
    v = velocity(row)
    text = f"{row.get('title') or ''}\n{row.get('body') or ''}".lower()
    return (in_window(row, cfg, now) and v is not None and median is not None and v >= median
            and (row.get("comments") or 0) >= int(cfg["min_comments"])
            and row.get("ad_like") is not True
            and not any(t in text for t in _registered_brands(cfg)))


def efficacy_ok(answers: Optional[dict]) -> bool:
    """Jev 全文答的 efficacy_promise 是「否」才上架 (D-140 / F-08, 同写作台发牌的外部池子)。答了「是」不上;
    没答 / 答空 / 答了别的也不上 (fail-closed: 戒烟、鼻炎、术后营养、藻油都是管得严的品类)。"""
    return (answers or {}).get(EFFICACY_QID) == "否"


def _percentile(v: float, pool: list[float]) -> float:
    """``v`` 在 ``pool`` (已排序) 里的中位秩百分位: 比它小的 + 一半和它一样的, 除以总数。"""
    lo, hi = bisect.bisect_left(pool, v), bisect.bisect_right(pool, v)
    return (lo + hi) / 2 / len(pool)


def candidates(rows: list[dict], cfg: dict, *, now: Optional[float] = None,
               roles: Optional[dict] = None) -> list[tuple[dict, float, float]]:
    """按 (品类, 族) 算日均评论的中位数 (在窗口里的帖, 不管有没有产品), 留下过了便宜那几道 (qualifies) 的, 品类内按日均评论
    从高到低 (同速按 note_id; 两族混着排, 给模型看哪几张由 split_shown 定)。返回 [(行, 日均评论, 百分位)]; 品类按第一次
    出现的顺序。纯函数。功效说法那道要查库, 只给这一步留下来的帖查 (qualified / fetch_shelf)。
    ``roles``: {note_id: product_role} (fetch_roles 给的, D-141); 每篇只和自己那族比, 百分位也在自己那族里排; 一族在窗口里
    不到 MIN_FAMILY_N 篇就用整个品类的中位数和百分位。``roles`` 是 None (读不了 / 不给) → 不分族, 和 D-140 一模一样。"""
    now = time.time() if now is None else now
    by_cat: dict = {}
    for r in rows:
        by_cat.setdefault(r.get("category"), []).append(r)
    out: list[tuple[dict, float, float]] = []
    for rs in by_cat.values():
        win = [(r, v) for r in rs if in_window(r, cfg, now) and (v := velocity(r)) is not None]
        if not win:
            continue
        whole = sorted(v for _, v in win)
        by_fam: dict = {}
        for r, v in win:
            by_fam.setdefault(family(roles, r.get("note_id")), []).append(v)
        # 族 → (中位数, 排百分位的那一池); 小族用整个品类的
        pools = {f: sorted(vs) if f is None or len(vs) >= MIN_FAMILY_N else whole for f, vs in by_fam.items()}
        meds = {f: statistics.median(p) for f, p in pools.items()}
        got = []
        for r in rs:
            f = family(roles, r.get("note_id"))
            if f in pools and qualifies(r, cfg, meds[f], now=now):
                got.append((r, velocity(r), pools[f]))
        got.sort(key=lambda t: (-t[1], str(t[0].get("note_id"))))
        out += [(r, v, _percentile(v, pool)) for r, v, pool in got]
    return out


def qualified(rows: list[dict], cfg: dict, answers: dict, *, now: Optional[float] = None,
              roles: Optional[dict] = None) -> list[tuple[dict, float, float]]:
    """真正上架的口径: candidates 里 Jev 功效题答了「否」的 (``answers``: {note_id: {题: 答}}, fetch_answers 取的;
    ``roles`` 同 candidates)。纯函数, 馆员上架和方向复核报数都用它 —— 口径只有一份。``answers`` 给空 = 一篇都不收 (fail-closed)。"""
    return [t for t in candidates(rows, cfg, now=now, roles=roles)
            if efficacy_ok(answers.get(str(t[0].get("note_id"))))]


def split_shown(by_family: dict, n: int) -> list:
    """给模型看的那 ``n`` 张 (D-141): 两族轮流放, P 先 (FAMILY_ORDER), 族内照原来的顺序 (日均评论从高到低); 一族放完了,
    另一族接着补, 放满 ``n`` 张或两族都放完为止。``by_family`` 的键是 P / O / None (None = product_role 读不了, 只有这一族,
    结果就是前 ``n`` 张, 和 D-140 一样)。``n`` 是奇数时 P 多一张。纯函数。"""
    queues = [list(by_family.get(f) or []) for f in FAMILY_ORDER]
    out: list = []
    while len(out) < n and any(queues):
        for q in queues:
            if q and len(out) < n:
                out.append(q.pop(0))
    return out


def describe(fq: Optional[dict]) -> Optional[str]:
    """Jev 结构题答案 → 一句人话 (「开头先讲一件具体的事；中间有一次前后转折；结尾问了读者」)。什么都没答 → None。"""
    fq = fq or {}
    parts = [_OPENING[fq["opening_type"]]] if fq.get("opening_type") in _OPENING else []
    parts += [text for qid, text in _YES if fq.get(qid) == "是"]
    return "；".join(parts) or None


def to_card(row: dict, cfg: Optional[dict] = None, *, rate: Optional[float] = None, pct: Optional[float] = None,
            fq: Optional[dict] = None, now: Optional[float] = None, mask: Optional[list] = None,
            fam: Optional[str] = None) -> dict:
    """``cfg`` 给 mask_terms 用; 不给就读默认配置 (读不了就不换, 但那时整个书架本来就不出卡)。
    ``rate`` / ``pct`` 是 qualified() 算好的日均评论和百分位 (不给就按这一行自己算日均、百分位记 0);
    ``fq`` 是 Jev 给这篇答的结构题; ``now`` 用来算现在发出几天 (posted_days_ago)。
    ``mask`` 是这篇有效的遮挡词 (valid_mask 给的, 可以是空列表 = 查过了没有要遮的); None = 没有有效遮挡行 →
    raw_excerpt 给空串, 卡上只有结构 (D-140: 没遮过的原文不出书架)。``masked`` 标这张卡的摘录是不是遮过的 ——
    只有遮过的卡能被强塞 (forceable)。``fam`` 是这篇的族 (family 给的, D-141): P → product_in_body true (卡头写
    「正文写了产品」), O → false, None (product_role 读不了) → None。

    why_it_worked 只写抓取那一刻定下的数 (抓到时发出几天、共几条评论、那时每天几条): 写作台模型读它, 缓存行一放一周,
    写「现在发出几天」会和命中时重算的 posted_days_ago 对不上; 百分位是上架那天同品类那批帖排出来的, 也会过时,
    只放在 rank_score 里。日均评论旁边只写抓到时的天数 —— 写现在的天数, 读的人一乘就和总评论数对不上。"""
    cfg = cfg if cfg is not None else load_config()
    now = time.time() if now is None else now
    n = row.get("comments") or 0
    rate = velocity(row) if rate is None else rate
    posted = posted_at(row.get("note_id"))
    days_ago = int((now - posted) // DAY_S) if posted is not None else None
    age = age_at_scrape(row)
    scraped_age = int(age + 0.5) if age is not None else None    # 四舍五入: 乘回去离总评论数最近
    per_day = round(rate, 1) if rate is not None else None
    fq = {q: fq[q] for q in STRUCTURE_QIDS if (fq or {}).get(q) is not None}
    why = "别家同品类最近涨得快的帖 (不是帆谷投的, 自然流量)"
    if scraped_age is not None and per_day is not None:
        why += f": 抓到时发出约 {scraped_age} 天、共 {n} 条评论, 那时每天约 {per_day} 条"
    return {
        "source_note_id": f"{ID_PREFIX}{row['note_id']}",
        "external": True,
        "tier": "外部参考",
        "brand": None,
        "category": row.get("category"),
        "comments": n,
        "posted_days_ago": days_ago,           # 现在发出几天 (命中缓存时按 id 重算)
        "age_at_scrape_days": scraped_age,     # 抓到时发出几天: comments / comments_per_day 是这个时候量的
        "comments_per_day": per_day,
        "fq": fq,
        "rank_score": round(pct, 3) if pct is not None else 0.0,
        "is_curated": False,
        "synthetic": False,
        "hook_type": None,
        "structure": describe(fq),
        "why_it_worked": why,
        "transferable_tactic": "只借结构 / 钩子, 不抄内容, 不提它的品牌",
        "product_in_body": None if fam is None else fam == FAMILY_P,   # D-141: 正文里产品是主角 / 解决方案
        "masked": mask is not None,
        "raw_excerpt": (apply_mask(f"{row.get('title') or ''} {row.get('body') or ''}".strip(), mask, cfg)
                        if mask is not None else ""),
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


def _latest(best: dict, key: tuple, row: dict) -> None:
    """``best[key] = (抽取时间, 答案)``, 只留最后抽的那一行; 空答案不算 (同 aw deskcore/store.py _latest_answer)。"""
    ans = str(row.get("answer") if row.get("answer") is not None else "").strip()
    if not ans:
        return
    at = _epoch(row.get("extracted_at")) or 0.0
    if key not in best or at >= best[key][0]:
        best[key] = (at, ans)


def fetch_answers(sb, ids: list, qids=ANSWER_QIDS) -> dict[str, dict[str, str]]:
    """Jev 给这几篇外部帖答的题 {note_id: {题: 答}} (subject_type=external_note, run_tag=external); 同一题答过几次
    取最后抽的那个有效答案。id 按 ANSWERS_CHUNK 个一批 .in_(), 每批按主键排序翻页, 拿到空页才收工 (服务端钳短了也不漏);
    翻到 _ANSWER_MAX_PAGES 页还没完 → 抛 (宁可这次没有外部卡, 也不拿半截答案判功效)。查库失败照抛, 调用方决定怎么退。"""
    want = sorted({str(i) for i in ids if i})
    qids = list(qids)
    best: dict = {}
    for i in range(0, len(want), ANSWERS_CHUNK):
        chunk = want[i:i + ANSWERS_CHUNK]
        off = 0
        for _ in range(_ANSWER_MAX_PAGES):
            rows = (
                sb.schema("truth_vault").table("note_feature_answers")
                .select("subject_id, question_id, answer, extracted_at")
                .eq("subject_type", "external_note").eq("run_tag", EXTERNAL_RUN_TAG)
                .in_("question_id", qids).in_("subject_id", chunk)
                # subject_type / run_tag 钉死了, 剩下这四列就是主键: 排序唯一, 翻页不漏不重
                .order("subject_id").order("question_id").order("question_version").order("extractor")
                .range(off, off + _PAGE - 1).execute()
            ).data or []
            if not rows:
                break
            for r in rows:
                sid, qid = str(r.get("subject_id") or ""), str(r.get("question_id") or "")
                if sid and qid in qids:
                    _latest(best, (sid, qid), r)
            off += len(rows)
        else:
            raise RuntimeError(f"外部帖答案翻了 {_ANSWER_MAX_PAGES} 页还没完 (这一批 {len(chunk)} 篇), 不拿半截答案判功效")
    out: dict[str, dict[str, str]] = {}
    for (sid, qid), (_at, ans) in best.items():
        out.setdefault(sid, {})[qid] = ans
    return out


def fetch_roles(sb, ids: list) -> Optional[dict[str, str]]:
    """这几篇 Jev 全文答的 product_role {note_id: 答} (D-141 分族用): 走 fetch_answers 同一条路 (100 篇一批、每批翻到空页、
    同一题取最后抽的有效答案), 没答的不在里面 (算 O)。读不了 → None: 调用方这次不分族 (D-140 的老样子), 不抛;
    warning 只打一次, 读成功一次之后再坏再打。"""
    try:
        got = fetch_answers(sb, ids, qids=(PRODUCT_QID,))
    except Exception:  # noqa: BLE001
        if not _FAMILY_WARNED:
            _FAMILY_WARNED.append(True)
            logger.warning("外部帖 product_role 读不了: 这次不分产品贴 / 其他两族, 整个品类一起排 (D-141 之前的样子)",
                           exc_info=True)
        return None
    _FAMILY_WARNED.clear()
    return {nid: a[PRODUCT_QID] for nid, a in got.items() if a.get(PRODUCT_QID)}


def _missing_table(exc: BaseException) -> bool:
    s = f"{exc!r} {exc}"
    return MASK_TABLE in s and any(m in s for m in ("PGRST205", "42P01", "does not exist", "Could not find the table"))


def fetch_masks(sb, ids: list) -> dict[str, dict]:
    """这几篇的遮挡行 {note_id: {terms, text_sha}}。表还没建 (v1_24 没跑) → {} 并打一次 warning; 别的读错 → {} 并 warning。
    读不到 = 这几篇当没遮过: 卡上只给结构 (fail-closed, 借卡照常)。"""
    want = sorted({str(i) for i in ids if i})
    out: dict[str, dict] = {}
    try:
        for i in range(0, len(want), ANSWERS_CHUNK):
            rows = (
                sb.schema("truth_vault").table(MASK_TABLE).select("note_id, terms, text_sha")
                .in_("note_id", want[i:i + ANSWERS_CHUNK]).execute()
            ).data or []
            out.update({str(r["note_id"]): r for r in rows if r.get("note_id") is not None})
    except Exception as exc:  # noqa: BLE001
        if _missing_table(exc):
            if not _MASK_WARNED:
                _MASK_WARNED.append(True)
                logger.warning("truth_vault.%s 还没建 (owner 跑 schemas/notes_v1_24 之前都是这样): 外部卡全部只给结构、"
                               "不给原文摘录, 也不强塞 (D-140)", MASK_TABLE)
        else:
            logger.warning("外部帖遮挡表读不了, 这次外部卡全部只给结构", exc_info=True)
        return {}
    return out


def valid_mask(row: dict, mask_row: Optional[dict]) -> Optional[list]:
    """遮挡行有效 (列词时的原文 = 现在的标题 + 正文) → 再过一遍 clean_terms 的词 (可以是空列表); 没有 / 过期 / 形状不对 → None。"""
    if not isinstance(mask_row, dict) or not isinstance(mask_row.get("terms"), list):
        return None
    if mask_row.get("text_sha") != mask_text_sha(row.get("title"), row.get("body")):
        return None
    return clean_terms(mask_row["terms"], f"{row.get('title') or ''}\n{row.get('body') or ''}")


def fetch_shelf(sb, categories: list[str], cfg: dict, *, now: Optional[float] = None) -> list[dict]:
    """这些品类里上架的外部帖: 窗口里每一篇查 product_role 分族 (fetch_roles; 读不了就不分族) → 便宜那几道 (candidates,
    每篇和自己那族的中位数比) → 给留下的帖查 Jev 的答案 (功效题 + 结构题, 分批翻页) → 功效题答了「否」的 → 查这些帖的
    遮挡行 → 转成卡, 每个品类给模型看 show_per_request 张, 两族各一半、轮流放 (split_shown, D-141)。没有有效遮挡行的卡
    只给结构; 连结构都没有的跳过、由同一族的下一张补 (族内还是按日均评论)。答案查不了照抛 (shelf_for 接住: 这个品类
    这次没有外部卡); product_role 查不了不抛 (不分族, 照 D-140 排, 照样进缓存)。"""
    now = time.time() if now is None else now
    out: list[dict] = []
    for cat in categories:
        rows = _category_rows(sb, cat, now)
        roles = fetch_roles(sb, window_ids(rows, cfg, now=now))
        cands = candidates(rows, cfg, now=now, roles=roles)
        if not cands:
            continue
        answers = fetch_answers(sb, [r["note_id"] for r, _, _ in cands])
        ok = [(r, v, p) for r, v, p in cands if efficacy_ok(answers.get(str(r["note_id"])))]
        masks = fetch_masks(sb, [r["note_id"] for r, _, _ in ok]) if ok else {}
        by_fam: dict = {}
        for r, v, p in ok:
            nid = str(r["note_id"])
            fam = family(roles, nid)
            card = to_card(r, cfg, rate=v, pct=p, fq=answers.get(nid), now=now, mask=valid_mask(r, masks.get(nid)),
                           fam=fam)
            if not card["raw_excerpt"] and not card["structure"]:
                continue
            by_fam.setdefault(fam, []).append(card)
        out += split_shown(by_fam, int(cfg["show_per_request"]))
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


_PIB = {True: "P", False: "O"}      # product_in_body 进指纹的写法; None (没分族) → "-"


def digest(cards: list[dict]) -> str:
    """进 library_version 的外部卡指纹: 卡的 id、**卡面摘录、结构、摘录遮没遮过、正文写没写产品 (D-141)**, 再加遮挡规则的
    版本 (MASK_RULES)。
    只认 id 的话, mask_terms 补了一个新品牌 / 夜跑新列了一篇的遮挡词, 卡面变了而版本没变, 旧缓存里没遮的摘录会一直被
    命中 (codex review on TV#202); 结构题晚到也一样。遮挡规则 (clean_terms / apply_mask) 改了就升 MASK_RULES。
    现在发出几天每天都在变, 不进指纹 (命中缓存时按 id 重算, core._refresh_external); 卡上别的数 (why_it_worked 也是)
    都是抓取那一刻定下的, 不随时间变。没有外部卡时与以前一样 (空串的哈希)。"""
    parts = sorted(f"{c.get('source_note_id')}\x00{c.get('raw_excerpt') or ''}\x00{c.get('structure') or ''}"
                   f"\x00{int(bool(c.get('masked')))}\x00{_PIB.get(c.get('product_in_body'), '-')}" for c in cards)
    if not parts:
        return hashlib.sha256(b"").hexdigest()[:10]
    return hashlib.sha256((MASK_RULES + "\n" + "\n".join(parts)).encode("utf-8")).hexdigest()[:10]


def is_external(card: dict) -> bool:
    return bool(card.get("external"))


def max_per_borrow(path: Path = CONFIG_PATH) -> int:
    cfg = load_config(path)
    return int(cfg["max_per_borrow"]) if cfg else 0


def min_external(path: Path = CONFIG_PATH) -> int:
    """配置的每次至少几张外部卡 (只管 min_external_categories 里的品类, 见 min_external_for)。配置读不了 → 0。"""
    cfg = load_config(path)
    return min(int(cfg.get("min_external") or 0), int(cfg["max_per_borrow"])) if cfg else 0


def forceable(cards: list[dict], path: Path = CONFIG_PATH) -> list[dict]:
    """``cards`` 里能拿来凑「至少 min_external 张」的外部卡: 品类在 min_external_categories 里, 而且摘录是遮过的
    (masked 且摘录不空, D-140)。只有结构的卡模型可以挑, 但从不强塞、不补。配置读不了 → []。"""
    cfg = load_config(path)
    cats = set((cfg or {}).get("min_external_categories") or [])
    return [c for c in cards if is_external(c) and c.get("category") in cats
            and c.get("masked") and (c.get("raw_excerpt") or "").strip()]


def min_external_for(cards: list[dict], path: Path = CONFIG_PATH) -> int:
    """这一摞候选卡要求至少挑几张外部卡: 有 forceable 的外部卡 → min_external, 否则 0。
    prompt 那句用法 (prompt_note) 和保底 (core._ensure_external) 都看它, 缓存版本也带着它 (core.librarian_select)。"""
    return min_external(path) if forceable(cards, path) else 0


PROMPT_NOTE = ("标了「外部参考」的卡是别家同品类最近涨得快的帖 (不是帆谷投的, 评论是自然流量; 卡上有抓到时发出几天、"
               "共几条评论、那时每天几条, 和现在发出几天): {pick}, 只借结构 / 钩子, 不抄内容, 不提它的品牌。")


def prompt_note(cards: list[dict], path: Path = CONFIG_PATH) -> str:
    """候选卡前面那句外部卡用法; 配置读不了 → 空串。``cards`` 里有 forceable 的外部卡时是「至少挑 1 张、最多 2 张」,
    只有只给结构的外部卡 (没遮过) 时是「最多挑 2 张」。"""
    n, m = max_per_borrow(path), min_external_for(cards, path)
    if not n:
        return ""
    return PROMPT_NOTE.format(pick=f"至少挑 {m} 张、最多 {n} 张" if m else f"最多挑 {n} 张")
