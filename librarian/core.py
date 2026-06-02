"""librarian/core.py — 飞轮馆员选取核心 (D-038 / docs/14)。

librarian_select(brief) 的流程:
    1. 取候选经验卡 (v_flywheel_lesson_cards, 按 rank_score 排序, 上限 CANDIDATE_CAP)。
       空库 → 返回 []  (消费方降级到自有正例)。
    2. 算 library_version = f(候选数, max(curated_at))。
    3. 算 cache_key = hash(consumer + project_id + brief_digest + library_version);
       命中缓存 → 直接返回 (跳过 LLM)。
    4. 未命中 → 渲染 brief + 候选 → LLM 推理选 3-5 张 → 校验 id → 富集摘要 → 写缓存。
       LLM 出错 → 返回 []  (绝不阻塞写稿; 飞轮是增强项)。

library_version 说明: 用 (候选数, max(curated_at)) 而非每行 updated_at ——
    * 新爆款进/出候选集 → 候选数变 → 失效；
    * 重策展 → 策展 pass 每次 upsert 都把 curated_at 置 NOW() → max(curated_at) 变 → 失效。
    覆盖了"新增"和"重策展"两大触发。极少见的边角 (已在候选内的笔记原地改内容、
    既不增减也不重策展) 由缓存 TTL (created_at prune) 兜底。
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Optional

from .clients import call_anthropic, get_supabase, iso_now, parse_json


LIBRARIAN_VERSION = "flywheel_librarian_v1"
CANDIDATE_CAP = 50          # 喂给 LLM 的候选上限 (库小, 50 足够; 大了再加 embedding 预筛)
DEFAULT_SELECT_MIN = 3
DEFAULT_SELECT_MAX = 5

# ── prompt 分段(Anthropic prompt caching 友好, 同 autowriter generator 的策略) ──
# 把【稳定且大】的部分作为带 cache_control: ephemeral 的 system 块, 重复请求共享缓存
# 前缀、省 ~90% 成本/延迟。顺序按"前缀稳定性"排(越稳越靠前, 因为缓存匹配的是前缀):
#   block1 = ROLE_TASK(永不变) + 候选卡(同 library_version 内不变, 且【跨项目共享】)
#   block2 = 项目 prompt 包(同项目内不变)
#   user   = 本次 delta(每次变, 不缓存)
# Anthropic 单请求最多 4 个 cache breakpoint, 这里用 2 个。这层 prompt-cache 与上面的
# 结果缓存(flywheel_librarian_cache)互补: 结果缓存挡"完全相同的请求", prompt-cache 省
# "同库不同 brief"的请求(只重算 delta 部分)。prompts/flywheel_librarian.md 同步说明。
ROLE_TASK_INSTR = """你是帆谷内容飞轮的"经验馆员"。下面给你一批【已验证爆款/值得参考】的"经验卡",
和一个写作 brief。你的任务: 为这次写作【推理挑选 3-5 张最有借鉴价值的卡】, 并说清每张
【为什么相关】+【借它哪个部位】。

推理(不是按相似度硬凑): 优先同品牌/同品类/同人群, 但也可跨主题借走可迁移的钩子/结构/手法。
挑 3-5 张(候选不足就少挑; 一张都不合适就返回空数组)。

输出严格 JSON(无 markdown 包装):
{"selected": [
  {"source_note_id": "<必须是候选里出现过的 id>",
   "why_relevant": "<为什么对这次写作有用, 1 句>",
   "borrow_what": "<借它哪个部位: 钩子/结构/评论区设计/某手法, 1 句>"}
]}"""

# 项目级、稳定字段(进【缓存】的 system 块; 同项目跨请求复用)。
_PROJECT_FIELDS = (
    ("brand", "品牌"),
    ("project_name", "项目"),
    ("system_prompt", "项目定位(system_prompt)"),
    ("system_prompt_tone", "语气基调"),
    ("system_prompt_exec", "执行要求"),
    ("tactics", "项目战术"),
    ("calibration_notes", "校准笔记"),
)
# 本次请求 delta(进 user message; 每次变, 不缓存)。
_DELTA_FIELDS = (
    ("tactic", "本次策略/方向"),
    ("target_audience", "目标人群"),
    ("tone", "本次语气"),
    ("extra_instructions", "本次特别要求"),
    ("draft_topic", "本次选题"),
)
# brief_digest 只 hash 这些字段(项目+delta+consumer+project_id), 保证结果缓存 key 稳定。
_BRIEF_DIGEST_KEYS = (
    tuple(k for k, _ in _PROJECT_FIELDS)
    + tuple(k for k, _ in _DELTA_FIELDS)
    + ("consumer", "project_id")
)


# ── 候选 + 版本 ──────────────────────────────────────────────────────────
def fetch_candidates(sb, limit: int = CANDIDATE_CAP) -> list[dict]:
    return (
        sb.schema("truth_vault").table("v_flywheel_lesson_cards")
        .select(
            "source_note_id, tier, brand, category, emotional_lever, target_audience, "
            "hook_type, structure, why_it_worked, transferable_tactic, raw_excerpt, "
            "curated_at, is_curated, rank_score"
        )
        .order("rank_score", desc=True)
        .limit(limit)
        .execute()
    ).data or []


def library_version(cards: list[dict]) -> str:
    """f(候选数, max(curated_at)) —— 见模块 docstring。"""
    max_curated = max((c.get("curated_at") or "" for c in cards), default="")
    return f"{len(cards)}:{max_curated or 'none'}"


# ── 缓存键 ───────────────────────────────────────────────────────────────
def brief_digest(brief: dict) -> str:
    blob = json.dumps(
        {k: brief.get(k) for k in _BRIEF_DIGEST_KEYS},
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def cache_key(brief: dict, lib_version: str) -> str:
    raw = "|".join((
        str(brief.get("consumer")),
        str(brief.get("project_id")),
        brief_digest(brief),
        lib_version,
    ))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_cache(sb, key: str) -> Optional[list]:
    res = (
        sb.schema("truth_vault").table("flywheel_librarian_cache")
        .select("selected").eq("cache_key", key).limit(1).execute()
    ).data or []
    if not res:
        return None
    # best-effort 命中时间 (LRU 观测; 失败不影响返回)
    try:
        sb.schema("truth_vault").table("flywheel_librarian_cache") \
          .update({"last_hit_at": iso_now()}).eq("cache_key", key).execute()
    except Exception:
        pass
    return res[0].get("selected")


def put_cache(sb, key: str, brief: dict, lib_version: str, selected: list) -> None:
    sb.schema("truth_vault").table("flywheel_librarian_cache").upsert({
        "cache_key": key,
        "consumer": brief.get("consumer"),
        "project_id": brief.get("project_id"),
        "brief_digest": brief_digest(brief),
        "library_version": lib_version,
        "selected": selected,
        "created_at": iso_now(),
        "last_hit_at": iso_now(),
    }, on_conflict="cache_key").execute()


# ── prompt 渲染 + 选取 ──────────────────────────────────────────────────
def _render_fields(brief: dict, fields) -> str:
    lines = []
    for key, label in fields:
        val = brief.get(key)
        if val:
            if isinstance(val, (list, dict)):
                val = json.dumps(val, ensure_ascii=False)
            lines.append(f"- {label}: {val}")
    return "\n".join(lines)


def _render_cards(cards: list[dict]) -> str:
    blocks = []
    for c in cards:
        head = f"[{c.get('source_note_id')}] {c.get('tier')}|{c.get('brand')}|{c.get('category')}"
        if c.get("is_curated"):
            body = (
                f"  钩子: {c.get('hook_type')}\n"
                f"  结构: {c.get('structure')}\n"
                f"  为何有效: {c.get('why_it_worked')}\n"
                f"  可借手法: {c.get('transferable_tactic')}"
            )
        else:  # 未策展: essence + 摘要兜底
            aud = c.get("target_audience")
            aud = ", ".join(aud) if isinstance(aud, list) else (aud or "?")
            body = f"  (未策展) 情绪杠杆: {c.get('emotional_lever') or '?'} · 人群: {aud}"
        excerpt = (c.get("raw_excerpt") or "").strip().replace("\n", " ")[:200]
        blocks.append(f"{head}\n{body}\n  摘要: {excerpt}")
    return "\n\n".join(blocks)


def build_system_blocks(brief: dict, cards: list[dict]) -> list[dict]:
    """两个带 cache_control 的 system 块(prompt caching):
      block1 = ROLE_TASK + 候选卡 (同 library_version 内稳定, 跨项目共享 → 命中率最高)
      block2 = 项目 prompt 包      (同项目内稳定)
    本次 delta 不在这里(进 user message)。"""
    cards_text = (
        f"{ROLE_TASK_INSTR}\n\n"
        f"═══ 候选经验卡 (按 rank_score 排序, 共 {len(cards)} 张) ═══\n"
        f"{_render_cards(cards)}"
    )
    project_text = "═══ 项目背景 ═══\n" + (_render_fields(brief, _PROJECT_FIELDS) or "(无)")
    return [
        {"type": "text", "text": cards_text, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": project_text, "cache_control": {"type": "ephemeral"}},
    ]


def build_user_message(brief: dict) -> str:
    delta = _render_fields(brief, _DELTA_FIELDS) or "(无特别要求)"
    return (
        "═══ 本次写作 ═══\n" + delta
        + "\n\n据此从上面候选经验卡里挑 3-5 张, 按要求输出严格 JSON {\"selected\": [...]}。"
    )


def build_prompt(brief: dict, cards: list[dict]) -> str:
    """dry-run 展示用: 把缓存块 + user message 拼成可读串(实际调用走分块 system)。"""
    sys_text = "\n\n".join(b["text"] for b in build_system_blocks(brief, cards))
    return f"{sys_text}\n\n──────── [user message] ────────\n{build_user_message(brief)}"


def _select_via_llm(brief: dict, cards: list[dict], model: str) -> list[dict]:
    """调 LLM 选取 → 解析 → 校验 id 在候选内 → 富集卡内容。失败抛异常给上层降级。
    用带 cache_control 的 system 块(候选卡 + 项目包)+ delta user message → prompt caching。"""
    raw = call_anthropic(
        build_user_message(brief), model,
        system=build_system_blocks(brief, cards),
    )
    parsed = parse_json(raw)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("selected"), list):
        raise ValueError("librarian response missing 'selected' list")

    by_id = {c.get("source_note_id"): c for c in cards}
    out = []
    for item in parsed["selected"][:DEFAULT_SELECT_MAX]:
        if not isinstance(item, dict):
            continue
        nid = item.get("source_note_id")
        card = by_id.get(nid)
        if card is None:        # 丢弃编造的 / 不在候选里的 id
            continue
        out.append({
            "source_note_id": nid,
            "why_relevant": (item.get("why_relevant") or "").strip(),
            "borrow_what": (item.get("borrow_what") or "").strip(),
            # 富集: 把卡内容附上, 消费方拼 prompt 直接可用
            "tier": card.get("tier"),
            "hook_type": card.get("hook_type"),
            "structure": card.get("structure"),
            "why_it_worked": card.get("why_it_worked"),
            "transferable_tactic": card.get("transferable_tactic"),
            "excerpt": card.get("raw_excerpt"),
        })
    return out


# ── 编排 ─────────────────────────────────────────────────────────────────
def librarian_select(brief: dict, *, model: Optional[str] = None,
                     use_cache: bool = True, dry_run: bool = False) -> Any:
    """馆员选取主入口。见模块 docstring。

    返回: dry_run → {_dry_run, prompt, ...} 诊断 dict; 否则 → list[选中卡]。
    空库 / LLM 失败 → []  (消费方据此降级到自有正例, 绝不阻塞写稿)。
    """
    model = model or os.environ.get("FLYWHEEL_LIBRARIAN_MODEL", "claude-sonnet-4-6")
    sb = get_supabase()

    cards = fetch_candidates(sb)
    if not cards:
        return {"_dry_run": True, "candidate_count": 0, "note": "空库 → 返回 []"} if dry_run else []

    lib_v = library_version(cards)
    key = cache_key(brief, lib_v)

    if dry_run:
        return {
            "_dry_run": True,
            "candidate_count": len(cards),
            "library_version": lib_v,
            "cache_key": key,
            "prompt": build_prompt(brief, cards),
        }

    if use_cache:
        cached = get_cache(sb, key)
        if cached is not None:
            return cached

    try:
        selected = _select_via_llm(brief, cards, model)
    except Exception:
        return []   # 降级: 绝不阻塞写稿

    if use_cache:
        try:
            put_cache(sb, key, brief, lib_v, selected)
        except Exception:
            pass    # 缓存写失败不影响本次返回
    return selected
