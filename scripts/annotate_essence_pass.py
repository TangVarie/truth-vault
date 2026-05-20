"""
annotate_essence_pass.py
═══════════════════════════════════════════════════════════════════════════

LLM annotation pass. Reads truth_vault.notes rows where essence is unset,
runs Mode A prompt (prediction_feature, performance-blind), writes back to
the notes table.

⚠️ Runs SEPARATELY from sync_feishu_notes_to_truth_vault.py — D-028 mandates
that essence annotation never share a process with tier extraction, because
sharing risks performance signals leaking into the Mode A prompt context.

Usage:
    python annotate_essence_pass.py NUC_phase1 --limit 30           # pilot
    python annotate_essence_pass.py NUC_phase1                       # full
    python annotate_essence_pass.py NUC_phase1 --dry-run --limit 5   # render only

Environment:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
    ANTHROPIC_API_KEY               (skipped with --dry-run)
    ESSENCE_MODEL                   (default: claude-sonnet-4-6)

The script also handles direction_decomposition.sub_directions when the
mapping yaml defines them (NUC_phase1's 6 子方向). In that case the LLM
output is parsed for both sub_direction (writes notes.direction_subtype +
content_format / target_audience / etc) AND essence fields.

Resumability:
    notes.essence_annotated_at + essence_vocab_version are written on
    success. Reruns skip rows that already have essence_annotated_at NOT
    NULL. Use --reannotate to overwrite (e.g. after a vocab version bump).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Optional

from _common import (
    fetch_all_pages,
    get_supabase_client,
    load_mapping,
    setup_logger,
    _iso_now,
)


logger = setup_logger("annotate_essence")


# ─────────────────────────────────────────────────────────────────────────
# Vocab v0.2 — must match docs/05-controlled-vocab.md exactly.
# Used for response validation; LLM outputs outside this set are rejected
# and retried once before being dropped to a failed queue.
# ─────────────────────────────────────────────────────────────────────────

VOCAB_VERSION = "v0.2"

EMOTIONAL_LEVERS = {
    "焦虑撬动", "羞耻撬动", "恐惧撬动", "愤怒撬动", "罪恶感撬动",
    "造梦投射", "认同感建立", "归属感建立", "共鸣释放", "虚荣撬动",
    "好奇驱动", "信息差利用",
}
EMOTIONAL_VALENCE = {"positive", "negative", "neutral"}
EMOTIONAL_INTENSITY = {"low", "medium", "high"}
HUMAN_TRUTH_ARCHETYPES = {
    "同辈比较", "伴侣关系", "代际冲突", "职场关系", "宠物相关",
    "自我形象维护", "身份认同", "时间流逝感", "自由意志",
    "阶层焦虑", "经济焦虑", "健康焦虑", "育儿焦虑",
    "情感缺位", "归属缺失", "认同缺失",
    "控制感渴望", "自我提升", "消费愉悦",
}
TREND_DEPENDENCIES = {
    "特定平台事件", "特定IP引用", "时事热点", "季节性事件", "节日",
    "行业事件", "当代流行词", "时代语言范式", "平台话术", "通用",
}
CONTENT_FORMATS = {
    "情感叙事", "认知重构", "横评对比", "教程攻略",
    "直给推荐", "场景植入", "提问求助", "反差破圈",
}

# ─────────────────────────────────────────────────────────────────────────
# Mode A prompt template — performance-blind, no {tier}/{interactions}/etc
# placeholders. Project context built separately so it can be sanity-checked.
# Full prompt body is in prompts/essence_annotator.md; this is the runtime
# template used for the actual API call.
# ─────────────────────────────────────────────────────────────────────────

MODE_A_PROMPT_TEMPLATE = """你是一个内容营销分析师，专精小红书种草笔记的深度分析。基于内容本身（不基于结果数据）输出严格 JSON 标注。

═══════════════════════════════════════════════
项目上下文
═══════════════════════════════════════════════
{project_context}

═══════════════════════════════════════════════
笔记内容
═══════════════════════════════════════════════
标题: {title}
正文: {body}
话题标签: {hashtags}

═══════════════════════════════════════════════
你的任务
═══════════════════════════════════════════════

按 JSON schema 输出标注。所有闭集字段只能从允许的值中选。

essence.emotional_lever (单选 1 个):
{emotional_levers_block}

essence.emotional_valence (单选):
  positive (对应造梦/认同/归属/共鸣/虚荣)
  negative (对应焦虑/羞耻/恐惧/愤怒/罪恶感)
  neutral (对应好奇/信息差)

essence.emotional_intensity (单选): low / medium / high

essence.human_truth_archetype (1-2 个):
{archetypes_block}

essence.trend_dependencies (多选, 但"通用"排他):
{trend_deps_block}

essence.content_format (单选):
{content_formats_block}

audience.demographic (闭集):
  age_band (1-2 个相邻): 20-29 / 30-39 / 40-49 / 50+
  gender_skew (单选): female / male / mixed
  city_tier (1-3 个): 1线 / 新1线 / 2线 / 3-4线 / 5线及以下
  life_stage (单选): 学生 / 职场新人 / 已婚未育 / 育儿期 / 空巢 / 退休
  value_orientation (单选): 务实 / 精致 / 自洽 / 表达 / 反叛
  income_band (单选): 学生 / 入门 / 中产 / 高净值

audience.psychographic (自由文本, 每项 1-2 句):
  primary_pain, primary_aspiration, likely_objections

audience.confidence (0-1)

reasoning (字符串, 100-200 字): 关键标注的依据 (边界 case 必须说明)

═══════════════════════════════════════════════
重要约束
═══════════════════════════════════════════════
1. 严格 JSON, 无 markdown 包装
2. 闭集字段必须从允许值中选, 不能造新值
3. emotional_lever 和 emotional_valence 必须语义一致
4. trend_dependencies "通用" 是排他标签
5. 信号不足时降 audience.confidence (<0.5)
"""


def build_project_context(project: dict, note: dict) -> str:
    """Render the project_context block. Performance fields are EXCLUDED."""
    return f"""- 品牌: {project.get('brand', '(未填)')}
- 产品: {project.get('product', '(未填)')}
- 品类: {project.get('category', '(未填)')}
- 目标蓝词: {', '.join(note.get('target_blue_keywords') or []) or '无'}
- 内容意图: {note.get('intent') or '未知'}
- 项目级方向 (如有): {note.get('raw_extra', {}).get('_direction_raw') or '(项目未定义方向)'}"""


def build_mode_a_prompt(project: dict, note: dict) -> str:
    project_context = build_project_context(project, note)

    # D-028 hygiene checks — see prompts/essence_annotator.md.
    PERFORMANCE_KEYWORDS = (
        "tier", "大爆", "爆贴", "impressions", "reads", "interactions",
        "互动数", "阅读数", "曝光", "performance", "实际表现",
    )
    TEMPLATE_LEAK_PLACEHOLDERS = (
        "{performance", "{tier", "{interactions", "{reads", "{impressions",
    )
    for placeholder in TEMPLATE_LEAK_PLACEHOLDERS:
        assert placeholder not in MODE_A_PROMPT_TEMPLATE, (
            f"MODE_A_PROMPT_TEMPLATE has a performance placeholder: {placeholder!r}. "
            "This breaks D-028 — Mode A must be performance-blind."
        )
    for kw in PERFORMANCE_KEYWORDS:
        assert kw not in project_context, (
            f"project_context leaked performance signal: {kw!r}. "
            "Check build_project_context() — Mode A must not pass "
            "tier/impressions/reads/interactions through context."
        )

    body = note.get("body") or note.get("raw_content") or ""
    return MODE_A_PROMPT_TEMPLATE.format(
        project_context=project_context,
        title=note.get("title") or note.get("raw_content", "")[:60],
        body=body[:1500] + ("...（截断）" if len(body) > 1500 else ""),
        hashtags=", ".join(note.get("hashtags") or []) or "无",
        emotional_levers_block="  " + " / ".join(sorted(EMOTIONAL_LEVERS)),
        archetypes_block="  " + " / ".join(sorted(HUMAN_TRUTH_ARCHETYPES)),
        trend_deps_block="  " + " / ".join(sorted(TREND_DEPENDENCIES)),
        content_formats_block="  " + " / ".join(sorted(CONTENT_FORMATS)),
    )


# ─────────────────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────────────────

def validate_essence(data: dict) -> list[str]:
    errors: list[str] = []
    e = data.get("essence") or {}
    if e.get("emotional_lever") not in EMOTIONAL_LEVERS:
        errors.append(f"emotional_lever {e.get('emotional_lever')!r} not in vocab")
    if e.get("emotional_valence") not in EMOTIONAL_VALENCE:
        errors.append(f"emotional_valence {e.get('emotional_valence')!r} invalid")
    if e.get("emotional_intensity") not in EMOTIONAL_INTENSITY:
        errors.append(f"emotional_intensity {e.get('emotional_intensity')!r} invalid")
    archetypes = e.get("human_truth_archetype") or []
    if not isinstance(archetypes, list) or not (1 <= len(archetypes) <= 2):
        errors.append("human_truth_archetype must be a list of 1-2 values")
    else:
        bad = [a for a in archetypes if a not in HUMAN_TRUTH_ARCHETYPES]
        if bad:
            errors.append(f"human_truth_archetype values not in vocab: {bad}")
    deps = e.get("trend_dependencies") or []
    if not isinstance(deps, list) or not deps:
        errors.append("trend_dependencies missing or not a list")
    else:
        bad = [d for d in deps if d not in TREND_DEPENDENCIES]
        if bad:
            errors.append(f"trend_dependencies values not in vocab: {bad}")
        if "通用" in deps and len(deps) > 1:
            errors.append("trend_dependencies '通用' must be exclusive")
    if e.get("content_format") not in CONTENT_FORMATS:
        errors.append(f"content_format {e.get('content_format')!r} not in vocab")

    # essence_lever ↔ valence consistency
    negative = {"焦虑撬动", "羞耻撬动", "恐惧撬动", "愤怒撬动", "罪恶感撬动"}
    positive = {"造梦投射", "认同感建立", "归属感建立", "共鸣释放", "虚荣撬动"}
    neutral = {"好奇驱动", "信息差利用"}
    lever = e.get("emotional_lever")
    valence = e.get("emotional_valence")
    if lever in negative and valence != "negative":
        errors.append(f"lever {lever} is negative but valence={valence}")
    if lever in positive and valence != "positive":
        errors.append(f"lever {lever} is positive but valence={valence}")
    if lever in neutral and valence != "neutral":
        errors.append(f"lever {lever} is neutral but valence={valence}")
    return errors


# ─────────────────────────────────────────────────────────────────────────
# Anthropic call (deferred import so --dry-run works without the SDK)
# ─────────────────────────────────────────────────────────────────────────

def call_claude(prompt: str, model: str) -> str:
    """Single Mode A call. Lazy-imports anthropic so --dry-run can work
    even if the package or env var aren't set."""
    import anthropic  # noqa: WPS433 (intentional lazy import)

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=model,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    # Concatenate text blocks. Mode A responses are JSON, never tool calls.
    parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
    return "".join(parts)


def parse_claude_json(text: str) -> Optional[dict]:
    """Strip stray markdown fences and parse JSON. Returns None on failure."""
    t = text.strip()
    if t.startswith("```"):
        # Strip leading fence (```json or ```)
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.endswith("```"):
            t = t.rsplit("```", 1)[0]
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        return None


# ─────────────────────────────────────────────────────────────────────────
# Database I/O
# ─────────────────────────────────────────────────────────────────────────

def fetch_unannotated_notes(sb, project_id: str, reannotate: bool) -> list[dict]:
    q = (
        sb.schema("truth_vault")
        .table("notes")
        .select(
            "note_id, project_id, title, body, raw_content, hashtags, "
            "intent, target_blue_keywords, raw_extra, "
            "projects(brand, product, category)"
        )
        .eq("project_id", project_id)
    )
    if not reannotate:
        q = q.is_("essence_annotated_at", None)
    return fetch_all_pages(q)


def write_essence_back(sb, note_id: str, model: str, parsed: dict, dry_run: bool) -> None:
    e = parsed["essence"]
    a = parsed.get("audience") or {}
    update = {
        "emotional_lever": e["emotional_lever"],
        "emotional_valence": e["emotional_valence"],
        "emotional_intensity": e["emotional_intensity"],
        "human_truth_archetype": e["human_truth_archetype"],
        "trend_dependencies": e["trend_dependencies"],
        "content_format": e["content_format"],
        "inferred_audience_profile": a,
        "essence_annotated_by": model,
        "essence_annotated_at": _iso_now(),
        "essence_vocab_version": VOCAB_VERSION,
        "essence_annotation_mode": "prediction_feature",
    }
    if dry_run:
        logger.info("[dry-run] would update note %s with %s", note_id,
                    {k: v for k, v in update.items() if k in ("emotional_lever", "content_format")})
        return
    (
        sb.schema("truth_vault")
        .table("notes")
        .update(update)
        .eq("note_id", note_id)
        .execute()
    )


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project_id", help="e.g. NUC_phase1")
    parser.add_argument("--dry-run", action="store_true",
                        help="Render prompts and skip LLM + DB writes")
    parser.add_argument("--limit", type=int, default=0,
                        help="Process at most N rows")
    parser.add_argument("--reannotate", action="store_true",
                        help="Re-annotate rows that already have essence_annotated_at")
    parser.add_argument("--qps", type=float, default=2.0,
                        help="Rate limit (default 2 req/sec, Anthropic free tier safe)")
    args = parser.parse_args()

    model = os.environ.get("ESSENCE_MODEL", "claude-sonnet-4-6")
    if not args.dry_run and not os.environ.get("ANTHROPIC_API_KEY"):
        logger.error("ANTHROPIC_API_KEY must be set (or use --dry-run)")
        return 2

    mapping = load_mapping(args.project_id)  # loaded for direction_decomposition future use
    sb = get_supabase_client()
    notes = fetch_unannotated_notes(sb, args.project_id, args.reannotate)
    if args.limit:
        notes = notes[: args.limit]
    logger.info("Found %d notes to annotate for project %s (model=%s)",
                len(notes), args.project_id, model)

    stats = {"ok": 0, "validation_failed": 0, "json_parse_failed": 0, "api_failed": 0}
    sleep_s = 1.0 / args.qps if args.qps > 0 else 0
    for i, note in enumerate(notes):
        # Inject project info one level up so prompt builder can read it
        project_info = note.pop("projects", {}) or {}
        try:
            prompt = build_mode_a_prompt(project_info, note)
        except AssertionError as exc:
            logger.error("Hygiene assertion failed on %s: %s", note["note_id"], exc)
            stats["api_failed"] += 1
            continue

        if args.dry_run:
            logger.info("[dry-run] note %s prompt length: %d chars",
                        note["note_id"], len(prompt))
            stats["ok"] += 1
            continue

        try:
            raw = call_claude(prompt, model)
        except Exception as exc:
            logger.exception("LLM call failed for %s: %s", note["note_id"], exc)
            stats["api_failed"] += 1
            continue

        parsed = parse_claude_json(raw)
        if parsed is None:
            logger.warning("JSON parse failed for %s; raw[:200]=%s",
                           note["note_id"], raw[:200])
            stats["json_parse_failed"] += 1
            continue

        errors = validate_essence(parsed)
        if errors:
            logger.warning("Validation failed for %s: %s", note["note_id"], errors)
            stats["validation_failed"] += 1
            continue

        write_essence_back(sb, note["note_id"], model, parsed, dry_run=False)
        stats["ok"] += 1
        if i % 10 == 0:
            logger.info("[%d/%d] %s ok=%d", i + 1, len(notes),
                        note["note_id"], stats["ok"])
        time.sleep(sleep_s)

    logger.info("Done: %s", json.dumps(stats, ensure_ascii=False))
    return 0 if stats["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
