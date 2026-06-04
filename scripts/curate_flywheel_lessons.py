"""
curate_flywheel_lessons.py
═══════════════════════════════════════════════════════════════════════════

飞轮策展 pass (pull 建设 ②, D-038 / docs/14). 把已验证的真实爆款(爆/大爆/参考)
提炼成"经验卡"(hook_type / structure / why_it_worked / transferable_tactic),
写入 truth_vault.flywheel_lesson_annotations, 供 LLM 馆员按 brief 借阅。

候选来自 truth_vault.v_flywheel_lesson_cards (schema: notes_v1_4_flywheel_lesson_cards.sql)
里 is_curated=false 的行 —— 即合格、尚未策展的爆款。

⚠️ 与 annotate_essence_pass 的区别: essence 是 performance-BLIND (D-028); 本 pass 恰恰
   performance-AWARE —— 只处理已知爆款, 任务是解释"为什么爆"(posthoc success_pattern)。
   故 prompt 单独在 prompts/flywheel_curator.md, 不能并进 essence_annotator.md(会破坏
   D-028 盲标隔离)。

复用 annotate_essence_pass 的 call_claude / parse_claude_json (带重试的 Anthropic 调用 +
JSON 解析)。未来若再加第三个 LLM pass, 可把这两个 helper 提到 _common。

Usage:
    python curate_flywheel_lessons.py --dry-run --limit 5     # 渲染 prompt, 不调 LLM/不写库
    python curate_flywheel_lessons.py --limit 20              # 真跑
    python curate_flywheel_lessons.py --project WTG_phase1     # 只策展某项目
    python curate_flywheel_lessons.py --recurate              # 重策展(覆盖已有卡)

Environment:
    SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY
    ANTHROPIC_API_KEY          (--dry-run 时不需要)
    FLYWHEEL_CURATOR_MODEL     (default: claude-sonnet-4-6)

前置: schemas/notes_v1_4_flywheel_lesson_cards.sql 必须已应用到目标库, 否则
      v_flywheel_lesson_cards / flywheel_lesson_annotations 不存在。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from _common import fetch_all_pages, get_supabase_client, setup_logger, _iso_now
# 复用 essence pass 的带重试 Anthropic 调用 + JSON 解析, 避免重复实现那套 retry。
# (导入 annotate_essence_pass 仅触发其 def/常量定义, main 有 __name__ guard, 无副作用。)
from annotate_essence_pass import call_claude, parse_claude_json


logger = setup_logger("curate_flywheel_lessons")

CURATOR_VERSION = "flywheel_curator_v1"
REQUIRED_FIELDS = ("hook_type", "structure", "why_it_worked", "transferable_tactic")

# 运行时模板 — 应与 prompts/flywheel_curator.md 保持一致 (改其一时同步另一个)。
CURATOR_PROMPT_TEMPLATE = """你是帆谷内容飞轮的"经验策展员"。下面这条小红书笔记是运营确认【值得借鉴】的真实笔记(等级见下: 爆/大爆 = 验证过的爆款; 参考 = 值得学的好内容)。
你的任务: 提炼出可【迁移】到别的选题/产品的写作经验, 输出严格 JSON。

═══════════════════════════════════════════════
已知上下文 (运营已确认值得借鉴; 你要解释它【为什么有效 / 值得学】)
═══════════════════════════════════════════════
- 等级: {tier}
- 品牌 / 品类: {brand} / {category}
- 情绪杠杆 (已标): {emotional_lever}
- 目标人群 (已标): {target_audience}

═══════════════════════════════════════════════
笔记内容
═══════════════════════════════════════════════
{raw_excerpt}

═══════════════════════════════════════════════
输出 (严格 JSON, 无 markdown 包装, 4 个 key 都必填非空)
═══════════════════════════════════════════════
{{
  "hook_type": "钩子类型(短语,便于按类型检索): 痛点共鸣/反差/福利/悬念/身份认同/场景代入/信息差…",
  "structure": "结构骨架(1-2句): 开场怎么抓→正文怎么铺→转折→CTA→评论区怎么设计",
  "why_it_worked": "为什么有效/值得学(1-2句, 最核心且可迁移的原因, 不是复述内容)",
  "transferable_tactic": "可直接借走的具体手法(1句, 别的产品/选题也能套)"
}}

约束: 每个字段 1-2 句、简洁; why_it_worked / transferable_tactic 必须可迁移(写成别人也能借的经验)。
"""


def build_curator_prompt(card: dict) -> str:
    aud = card.get("target_audience")
    aud_str = ", ".join(aud) if isinstance(aud, list) else (aud or "未标")
    return CURATOR_PROMPT_TEMPLATE.format(
        tier=card.get("tier") or "?",
        brand=card.get("brand") or "(未填)",
        category=card.get("category") or "(未填)",
        emotional_lever=card.get("emotional_lever") or "未标",
        target_audience=aud_str,
        raw_excerpt=(card.get("raw_excerpt") or "").strip() or "(无正文)",
    )


def validate_lesson(data) -> list[str]:
    """轻校验: 4 个 key 都在且为非空字符串。策展字段是自由文本, 不查闭集词表。"""
    if not isinstance(data, dict):
        return ["response is not a JSON object"]
    errors = []
    for f in REQUIRED_FIELDS:
        v = data.get(f)
        if not isinstance(v, str) or not v.strip():
            errors.append(f"{f} missing or empty")
    return errors


def fetch_uncurated_cards(sb, project_id, recurate: bool) -> list[dict]:
    """从策展库视图取合格爆款。默认只取 is_curated=false; --recurate 取全部。"""
    q = (
        sb.schema("truth_vault")
        .table("v_flywheel_lesson_cards")
        .select(
            "source_note_id, project_id, tier, brand, category, "
            "emotional_lever, target_audience, raw_excerpt, is_curated"
        )
    )
    if project_id:
        q = q.eq("project_id", project_id)
    if not recurate:
        q = q.eq("is_curated", False)
    return fetch_all_pages(q)


def write_lesson_back(sb, note_id: str, model: str, parsed: dict, dry_run: bool) -> None:
    row = {
        "note_id": note_id,
        "hook_type": parsed["hook_type"].strip(),
        "structure": parsed["structure"].strip(),
        "why_it_worked": parsed["why_it_worked"].strip(),
        "transferable_tactic": parsed["transferable_tactic"].strip(),
        "curated_by": model,
        "curator_version": CURATOR_VERSION,
        "curated_at": _iso_now(),
    }
    if dry_run:
        logger.info("[dry-run] would upsert lesson for %s: hook=%r", note_id, row["hook_type"])
        return
    (
        sb.schema("truth_vault")
        .table("flywheel_lesson_annotations")
        .upsert(row, on_conflict="note_id")
        .execute()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--project", help="只策展某项目 (如 WTG_phase1)")
    parser.add_argument("--dry-run", action="store_true",
                        help="渲染 prompt, 跳过 LLM + 写库")
    parser.add_argument("--limit", type=int, default=0, help="最多处理 N 条")
    parser.add_argument("--recurate", action="store_true",
                        help="重策展已有卡 (默认只处理 is_curated=false)")
    parser.add_argument("--qps", type=float, default=2.0,
                        help="限速 (default 2 req/s)")
    args = parser.parse_args()

    model = os.environ.get("FLYWHEEL_CURATOR_MODEL", "claude-sonnet-4-6")
    if not args.dry_run and not os.environ.get("ANTHROPIC_API_KEY"):
        logger.error("ANTHROPIC_API_KEY must be set (or use --dry-run)")
        return 2

    sb = get_supabase_client()
    cards = fetch_uncurated_cards(sb, args.project, args.recurate)
    if args.limit:
        cards = cards[: args.limit]
    logger.info("Found %d card(s) to curate (model=%s, recurate=%s)",
                len(cards), model, args.recurate)

    stats = {"ok": 0, "ok_after_retry": 0, "failed": 0}
    sleep_s = 1.0 / args.qps if args.qps > 0 else 0
    for i, card in enumerate(cards):
        note_id = card["source_note_id"]   # 视图导出列名是 source_note_id; 写回仍落 note_id PK
        prompt = build_curator_prompt(card)
        if args.dry_run:
            logger.info("[dry-run] %s prompt len=%d", note_id, len(prompt))
            stats["ok"] += 1
            continue
        # 单卡最多试 2 次。call_claude 自身只重试【API 错误】,不重试"HTTP 200 但返回非法 JSON /
        # 不合规"——而 LLM 偶发吐坏 JSON 正是此类(实测 NRT_2 15 张里偶发 1 张 json_parse_failed)。
        # curate 是 best-effort 富集,单卡抽风不该拖红整条 daily-sync,故失败重提一次。
        parsed, errors = None, ["not_attempted"]
        for attempt in (1, 2):
            try:
                raw = call_claude(prompt, model)
            except Exception as exc:
                errors = [f"api_failed: {exc!r}"]
                logger.warning("curate API failed for %s (try %d): %r", note_id, attempt, exc)
                continue
            parsed = parse_claude_json(raw)
            errors = validate_lesson(parsed) if parsed is not None else ["json_parse_failed"]
            if not errors:
                if attempt == 2:
                    stats["ok_after_retry"] += 1
                break
            logger.warning("curate validation failed for %s (try %d): %s", note_id, attempt, errors)
        if errors:
            stats["failed"] += 1
            continue
        write_lesson_back(sb, note_id, model, parsed, dry_run=False)
        stats["ok"] += 1
        if i % 10 == 0:
            logger.info("[%d/%d] %s ok=%d failed=%d", i + 1, len(cards), note_id,
                        stats["ok"], stats["failed"])
        time.sleep(sleep_s)

    logger.info("Done: %s", json.dumps(stats, ensure_ascii=False))
    # 返回码策略:只有【全军覆没】(一张都没成功却有失败)才判失败 —— 那多半是系统性问题
    # (FLYWHEEL_CURATOR_MODEL 配错 / 中转站余额耗尽 / 限流),该红该告警。零星单卡失败(ok>0)
    # 容忍并返回 0:curate 幂等(失败卡 is_curated=false),下轮 daily-sync 自动重试,不该
    # 因 LLM 偶发抽风把整条 sync 拖红(对齐 best-effort 富集定位)。
    if stats["failed"] > 0 and stats["ok"] == 0:
        logger.error("curate 全部失败 (%d 张) —— 多半系统性(模型 env / 余额 / 限流),需排查。",
                     stats["failed"])
        return 1
    if stats["failed"] > 0:
        logger.warning("curate 有 %d 张失败(已各重试一次),ok=%d;失败卡下轮幂等重试,不拖红本次。",
                       stats["failed"], stats["ok"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
