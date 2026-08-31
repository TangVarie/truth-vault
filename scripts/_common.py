"""
Shared utilities for Truth Vault sync scripts.

Centralises:
  - Supabase client creation (always service_role; cross-schema explicit)
  - Mapping yaml loading + validation
  - Tier extraction / intent mapping rule engines
  - Quarantine helper for undeclared fields
  - Logging setup
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml
from supabase import create_client, Client


# ─────────────────────────────────────────────────────────────────────────
# Client creation
# ─────────────────────────────────────────────────────────────────────────

def _jwt_role_or_none(token: str) -> Optional[str]:
    """Decode the role claim from a Supabase JWT without verifying signature.

    Supabase issues HS256 JWTs whose payload contains `{"role": "anon"}` or
    `{"role": "service_role"}` (plus iss/iat/exp). We only need to read the
    role to refuse anon keys — signature verification belongs on the server
    side, not in a CLI sync script. base64url decode of payload is enough.
    Returns None if anything about the token doesn't look like a JWT.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload_b64 = parts[1]
    padding = "=" * (-len(payload_b64) % 4)
    try:
        payload_bytes = base64.urlsafe_b64decode(payload_b64 + padding)
        payload = json.loads(payload_bytes)
    except (ValueError, json.JSONDecodeError):
        return None
    role = payload.get("role")
    return role if isinstance(role, str) else None


# Supabase 2024+ "API keys" format. The role is encoded in the prefix:
#   sb_secret_*      → server-only, equivalent to legacy service_role JWT
#   sb_publishable_* → client-safe, equivalent to legacy anon JWT
# These are NOT JWTs (no dots, opaque payload), so _jwt_role_or_none returns
# None for them. We have to recognize the prefix to validate role.
_SB_SECRET_PREFIX = "sb_secret_"
_SB_PUBLISHABLE_PREFIX = "sb_publishable_"


def get_supabase_client() -> Client:
    """Return a Supabase client using SERVICE_ROLE_KEY (RLS bypass).

    Sync scripts MUST use service_role; they perform system-level operations
    that write to multiple users' rows. See docs/09-system-integration.md
    "TV sync 脚本必须用 SERVICE ROLE KEY" for the security rationale.

    Accepts both key formats:
      - Legacy: long HS256 JWT (role=service_role in payload)
      - New (2024+): opaque token prefixed with `sb_secret_`

    Every call explicitly does .schema('truth_vault'/'autowriter'/'public'),
    which sets the schema per-request, so the client default doesn't matter.
    Do NOT pass ClientOptions(schema=None): on supabase-py 2.30.0 a None
    schema becomes a None Accept-Profile header and every .execute() raises
    `AttributeError: 'NoneType' object has no attribute 'encode'` BEFORE any
    request is sent — that bug is why all sync steps failed with truth_vault
    staying empty (debugged 2026-05-27, see docs/12).
    """
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY env vars must be set. "
            "See scripts/.env.example for the full list."
        )

    # 1. New-format API key — the role is in the prefix. Bail early before
    #    trying JWT decode (these are opaque, not JWTs).
    if key.startswith(_SB_PUBLISHABLE_PREFIX):
        raise RuntimeError(
            "SUPABASE_SERVICE_ROLE_KEY starts with 'sb_publishable_' — that's "
            "a publishable (anon-equivalent) key. Sync scripts need a secret "
            "key (starts with 'sb_secret_'). Check Supabase Dashboard → "
            "Settings → API."
        )
    if key.startswith(_SB_SECRET_PREFIX):
        return create_client(url, key)

    # 2. Legacy JWT format — decode payload and check the role claim.
    role = _jwt_role_or_none(key)
    if role is not None:
        if role != "service_role":
            raise RuntimeError(
                f"SUPABASE_SERVICE_ROLE_KEY has role={role!r}, expected 'service_role'. "
                "Sync scripts need service_role to bypass RLS. Check Supabase "
                "Dashboard → Settings → API → service_role secret."
            )
        return create_client(url, key)

    # 3. Neither prefix matched, and not a JWT — last-resort guardrail
    #    against pasting an obviously wrong value (empty / "your-key-here" /
    #    accidentally pasted publishable). We're deliberately permissive
    #    here because Supabase may introduce more formats in the future;
    #    only the most obvious mistakes get rejected.
    if "anon" in key.lower() or len(key) < 20:
        raise RuntimeError(
            "SUPABASE_SERVICE_ROLE_KEY doesn't look like a known Supabase key "
            "format (not a JWT, not sb_secret_*, and is suspiciously short or "
            "contains 'anon'). Check Supabase Dashboard → Settings → API."
        )
    return create_client(url, key)


# ─────────────────────────────────────────────────────────────────────────
# 库结构前置检查 (D-046)
# ─────────────────────────────────────────────────────────────────────────
#
# 治的是「合并 ≠ 部署」: 代码里新写一个列, 而承载它的迁移没在生产库跑过。
#
# 2026-08-27 真出过一次: PR #109 让每条 note upsert 都带 notes.last_seen_at,
# 迁移 notes_v1_9 却从没跑 → **每一条 upsert 都 PGRST204 失败**, 而且是
# 【逐行】失败 —— 几百条一模一样的 traceback 把唯一有用那行信息淹了; 又只在
# "有新行要写"的项目上命中(当天 16 个项目只炸 2 个), 于是整轮看着像个别项目
# 抽风。daily sync 连红 4 天才被发现。
#
# 所以这道闸的价值不在"能发现", 而在【把 4 天 × 逐行 traceback 压成 5 秒 × 一行】。
#
# 探测手法: 拿这些列做一次 `select ... limit 0`。列不存在时 PostgREST 直接回
# 42703 "column X does not exist" —— 这不是推测, 正是那次事故日志里对账查询
# 打出来的那条 warning。比读 information_schema 省事(PostgREST 不暴露它),
# 也不用为此建 RPC; 全程只读, limit 0 不取数据。
# 成功路径每张表一次往返(~9 次, 亚秒级), 只有失败时才逐列再探一遍点名。

# 本仓 sync 链路会写的列。来源: 2026-08-30 用 workflow 把 7 个写库脚本逐个盘了一遍,
# 再拿结果对生产库 information_schema 做确定性核对(当时 128 列全部存在)。
# 新增写入列时【必须】同步加到这里 —— 否则这道闸就漏掉了它, 事故会原样重演。
_REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "notes": (
        "note_id", "project_id", "feishu_record_id", "platform",
        "raw_content", "publish_url", "publish_time", "account_id",
        "tier", "tier_source", "intent", "title",
        "impressions", "reads", "interactions",
        "content_format", "target_audience", "user_pain_point", "product_focus",
        "direction_subtype", "hit_blue_keywords", "target_blue_keywords",
        "pinned_comment", "raw_extra",
        "data_quality_status", "data_quality_flags",
        "actual_audience_data", "audience_actual_synced_at",
        "last_seen_at", "last_seen_run_id",
        "essence_annotated_at", "essence_annotated_by",
        "essence_annotation_mode", "essence_vocab_version",
        "emotional_valence", "emotional_lever", "emotional_intensity",
        "human_truth_archetype", "inferred_audience_profile", "trend_dependencies",
        "source_autowriter_item_id", "source_autowriter_version_id",
        "synced_autowriter_item_id", "synced_to_aw_at",
        # ssll 那对孪生列 —— sync_truth_vault_baokuan_to_sanshengliubu.mark_synced()
        # 每条推成功的爆款都写, retract 分支再置 NULL。手工列清单时漏过一次
        # (只记了 autowriter 那对), 靠 2026-08-30 那轮对抗盘点抓回来。
        "synced_to_ssll_at", "synced_ssll_reference_sample_id",
    ),
    "accounts": ("account_id", "platform", "owner_type", "first_seen_at"),
    "comments": (
        "comment_id", "note_id", "project_id", "content", "comment_role",
        "comment_order", "parent_comment_id", "is_pinned", "is_displayed", "created_at",
    ),
    "metric_snapshots": (
        "note_id", "source", "window_label", "collected_at", "hours_since_publish",
        "impressions", "reads", "interactions", "likes", "saves", "shares",
        "comments_count", "hit_blue_keywords", "keyword_rank", "search_rank",
    ),
    "projects": (
        "project_id", "brand", "product", "category", "platform", "mapping_config",
        "schema_family", "start_date", "end_date", "tier_thresholds",
    ),
    "prepublish_evaluations": (
        "autowriter_item_id", "evaluator_type", "evaluator_id", "decision", "created_at",
    ),
    "flywheel_lesson_annotations": (
        "note_id", "why_it_worked", "transferable_tactic", "hook_type", "structure",
        "curated_at", "curated_by", "curator_version",
    ),
    "undeclared_fields_quarantine": (
        "project_id", "feishu_record_id", "undeclared_field_names",
        "raw_row", "reason", "status", "quarantined_at",
    ),
    # librarian/core.py put_cache() 写的 —— 不在 scripts/ 下, 所以按脚本盘点时会漏。
    # 收进来是因为 daily-sync 确实碰这张表(prune_librarian_cache 那一步)。
    "flywheel_librarian_cache": (
        "cache_key", "consumer", "project_id", "brief_digest",
        "library_version", "selected", "created_at", "last_hit_at",
    ),
}

# ── 以下三类【故意不收】, 免得下一个人"顺手补全"反而把闸弄坏 ──────────────
#
# ① 触发器写的列: notes.era_tag / notes.updated_at / notes.ingested_at /
#    projects.updated_at / accounts.updated_at / flywheel_lesson_annotations.updated_at
#    / audit_log.* —— 这些【我们的代码从来不发】, 是 schemas/notes_v1_2.sql 里的
#    BEFORE/AFTER 触发器写的。而列和触发器出自【同一个迁移文件】, 不可能只缺一半:
#    列没了触发器也没了, 于是"触发器要写一个不存在的列"这种态压根构造不出来。
#    收进来只会白花往返, 不会多挡住任何东西。
#
# ② 另一个库的表: public.reference_samples 在【三生六部那个 Supabase 实例】上,
#    不是本库。本函数拿的是 TV 的 client, 探不到, 也不该由 TV 的 sync 替它把关。
#
# ③ autowriter schema: 本函数只探 truth_vault。autowriter 的漂移该由写它的那个
#    脚本自己把关(它跑在另一条链路上, 挂了不该拖红夜间 TV 同步)。

# 哪个迁移文件加的 —— 报错时直接把"该跑哪个"说出来, 别让人再去翻 README 对清单。
# 只列【后加的、容易漏跑】的; 其余落回通用提示(建表迁移漏了的话报错会非常明显)。
_COLUMN_MIGRATION: dict[str, str] = {
    "last_seen_at":     "schemas/notes_v1_9_last_seen_reconcile.sql",
    "last_seen_run_id": "schemas/notes_v1_9_last_seen_reconcile.sql",
}


def assert_db_schema_ready(client: Client, tables: Optional[Iterable[str]] = None) -> None:
    """开跑前核一次: 本仓会写的列在库里是否都存在; 缺了就【立刻】停, 别逐行撞墙。

    tables 不给就核 _REQUIRED_COLUMNS 全部。放在任何写入之前调用。
    列都在 → 静默返回。缺列 → RuntimeError, 消息里点名缺哪些、该跑哪个迁移。
    """
    names = tuple(tables) if tables is not None else tuple(_REQUIRED_COLUMNS)
    missing: list[str] = []
    for table in names:
        cols = _REQUIRED_COLUMNS.get(table)
        if not cols:
            continue
        try:
            client.schema("truth_vault").table(table).select(",".join(cols)).limit(0).execute()
        except Exception:
            # 整批探失败 → 逐列再探一遍, 把【所有】缺的列一次点全。
            # (PostgREST 一次只报第一个缺的, 一次修一个要来回好几轮。)
            for col in cols:
                try:
                    client.schema("truth_vault").table(table).select(col).limit(0).execute()
                except Exception:
                    missing.append(f"truth_vault.{table}.{col}")
    if not missing:
        return
    migrations = sorted({
        _COLUMN_MIGRATION[m.rsplit(".", 1)[-1]]
        for m in missing if m.rsplit(".", 1)[-1] in _COLUMN_MIGRATION
    })
    todo = ("请先应用: " + " · ".join(migrations)) if migrations else (
        "请对照 scripts/README.md 的「Step 0 · 必做前置 migrations」逐条确认 schemas/ 下的迁移都跑过了"
    )
    raise RuntimeError(
        f"库结构没跟上代码 —— 本仓会写的 {len(missing)} 个列在生产库里不存在:\n"
        + "\n".join(f"    · {m}" for m in missing)
        + f"\n  {todo}\n"
        "  (这道闸是 D-046: 2026-08-27 同类问题让 daily sync 连红 4 天 —— "
        "当时是每条 upsert 各撞一次墙, 几百条 traceback 淹掉了唯一有用的那行。"
        "现在改成开跑前一次性报出来。)"
    )


# ─────────────────────────────────────────────────────────────────────────
# Mapping yaml
# ─────────────────────────────────────────────────────────────────────────

_MAPPINGS_DIR = Path(__file__).resolve().parent.parent / "mappings"


_ALLOWED_TIER_SOURCES = {"状态字段", "备注字段"}


def load_mapping(project_id: str) -> dict:
    """Load `mappings/<project_id>.yaml`. Validates required keys exist
    and that any closed-set fields (e.g. tier_extraction.source) have
    legal values.
    """
    path = _MAPPINGS_DIR / f"{project_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Mapping yaml not found: {path}")
    with open(path, encoding="utf-8") as f:
        m = yaml.safe_load(f)
    required = {"project_id", "field_mapping"}
    missing = required - set(m.keys())
    if missing:
        raise ValueError(f"{path}: missing required keys: {missing}")
    if m["project_id"] != project_id:
        raise ValueError(
            f"{path}: project_id in yaml ({m['project_id']!r}) "
            f"does not match filename ({project_id!r})"
        )
    # tier_extraction.source picks which intermediate (_status_raw vs
    # _note_for_tier) the rule engine reads. A typo in the yaml ("souce",
    # "状态") used to silently fall back to "状态字段" via .get(default),
    # which means C-family projects (TGV/QSHG that map 备注→_note_for_tier)
    # would silently drop their tier. Reject unknown values here instead.
    tier_extraction = m.get("tier_extraction") or {}
    if "source" in tier_extraction:
        src = tier_extraction["source"]
        if src not in _ALLOWED_TIER_SOURCES:
            raise ValueError(
                f"{path}: tier_extraction.source={src!r} not in "
                f"{sorted(_ALLOWED_TIER_SOURCES)}. Check for typos."
            )
    _reject_shadowed_tier_rules(path, tier_extraction.get("rules") or [])
    return m


def skip_on_demand_on_cron(sync_interval: Optional[str], scheduled: bool) -> bool:
    """夜间 cron(scheduled=True)是否应跳过该项目。

    sync_interval=on_demand 的项目【只】在显式 dispatch / 改成 daily 后才进夜间 cron ——
    防新接的表(填了飞书坐标但还没 preflight 验证)被 02:00 cron 自动灌(codex PR#67 review)。
    on_demand 是 onboarder 起草的安全默认: 接表填坐标 → preflight → 显式跑验证 → 改 daily。
    保守: 只有【确实 cron】且【确实 on_demand】才跳; 显式 dispatch / 本地手跑照跑, 不挡人工。

    ⚠️ 这个判据 daily-sync 里【每一个自动处理步骤】都要用同一份 —— 2026-08-30 之前它只
    挡住了「入库」那一步, essence 标注那步是裸 `for f in mappings/*.yaml` 全遍历, 于是
    on_demand 项目的笔记一落库, 当晚就会被 LLM 按【还没拍板】的方向拆解标注, 而标注按
    essence_annotated_at IS NULL 取, 标完即固化、顺着经验卡→三生六部→autowriter 传下去。
    那道闸的本意("没验证过的表不许自动处理")被只实现了一半。见 D-047。
    """
    return scheduled and sync_interval == "on_demand"


def _reject_shadowed_tier_rules(path, rules: list[dict]) -> None:
    """规则列序里靠前的短针,不许把靠后的长针整条遮死。

    `_first_matching_tier` 取【首个】命中,所以短针在前 = 长针永远不可达。
    实测(2026-08-28,BJS_phase1 起草稿):
        - match_contains: ["爆贴", "爆帖"]   → 爆        # 「伪爆帖500」在这里就命中了
        - match_contains: ["伪爆帖", "伪20评"] → 数据异常   # ← 永远走不到
    后果最严重的一类:运营手工标的假数据被判成【爆】,再叠加 synthetic 那道网当时也漏
    (只认「伪爆贴」不认「伪爆帖」),假爆款就以真爆款身份进了飞轮和看板爆款率。
    这是纯静态可查的 —— 全部既有 mapping 扫过零误报,唯一命中就是上面那条。
    修法是【调列序】:长针(伪爆帖)排到短针(爆帖)前面,与「爆贴预备 先于 爆贴」同理。
    """
    seen: list[tuple[str, Any, int]] = []
    for i, rule in enumerate(rules):
        needles = rule.get("match_contains")
        # 写成裸字符串(而不是列表)时别按字符逐个拆 —— 那会拿单字去比子串, 报一堆假遮死。
        # 这种 mapping 本身就坏(引擎也会逐字符匹配), 但那不是这道 lint 该报的错。
        if not isinstance(needles, list):
            continue
        for needle in map(str, needles):
            for prev_needle, prev_tier, prev_i in seen:
                if prev_needle != needle and prev_needle in needle:
                    raise ValueError(
                        f"{path}: tier 规则列序把长针遮死了 —— 规则#{prev_i} 的"
                        f"「{prev_needle}」(→{prev_tier})是规则#{i} 的「{needle}」"
                        f"(→{rule.get('tier')})的子串, 首个命中原则下后者永远不可达。"
                        f"把「{needle}」那条【上移】到「{prev_needle}」之前。"
                    )
            seen.append((needle, rule.get("tier"), i))


# ─────────────────────────────────────────────────────────────────────────
# Tier / intent / direction rule engines
# ─────────────────────────────────────────────────────────────────────────

# 状态【等级】优先级 —— 多选状态栏同时挂多个状态时, 取等级最高的那个为准。
# 数值只表相对大小; 顺序对齐既有规则表(大爆>爆>预备>参考>风控>趴>未知), 唯一修正是把
# 【爆】提到【预备】之上: 爆贴预备升成爆贴/大爆后, 不能再被列序里靠前的「预备」规则截胡
# (那会把已验证的爆款错判成预备、漏出爆款口径 —— 见本次修复)。所有 mapping 共用此表。
_TIER_RANK = {"大爆": 7, "爆": 6, "预备": 5, "参考": 4, "风控": 3, "趴": 2, "未知": 1}


def _status_tokens(raw_status: Any) -> list[str]:
    """飞书「状态/流量状态」cell → 各【独立状态标】列表。

    - 多选字段(list)→ 每个选项一个 token(再按 ，,、/| 兜底拆一次, 防一格塞多状态)。
      这是本次修复的关键: 多选时必须逐标判级再取最高, 不能把 "爆贴预备, 爆贴" 拼成一
      整串靠规则列序命中(那样「预备」永远先于「爆」命中)。
    - 单值(str/dict)→ 整串当一个 token, 保持旧的整串子串匹配语义不变。C 家族「备注字段」
      判级是长文本, 不能乱拆, 故只对多选 list 做拆分。
    """
    if isinstance(raw_status, list):
        toks: list[str] = []
        for x in raw_status:
            s = str(x.get("text", "")) if isinstance(x, dict) else str(x)
            for sep in ("，", "、", "/", "|"):
                s = s.replace(sep, ",")
            for part in s.split(","):
                p = part.strip()
                if p:
                    toks.append(p)
        return toks
    s = _direction_key(raw_status)
    return [s] if s else []


def _first_matching_tier(text: str, rules: list[dict]) -> Optional[str]:
    """单个状态值按 yaml 规则【顺序】取首个命中的 tier。

    规则列序在这里只负责【单值内消歧】: "爆贴预备" ⊃ "爆贴", 预备规则列在爆规则之前 →
    纯预备标正确判预备(不会被爆规则的子串命中误升)。跨多个状态值的择优交给
    _TIER_RANK(取最高级), 不再依赖规则列序 —— 这正是修复点。
    """
    for rule in rules:
        if "match_contains" in rule:
            for needle in rule["match_contains"]:
                if needle in text:
                    return rule.get("tier")
    return None


def extract_tier(raw_status: Any, rules: list[dict]) -> Optional[str]:
    """把飞书「状态」cell 判成 notes.tier。

    多选状态栏(list)同时挂多个状态时, 取【等级最高】的那个(_TIER_RANK):
      爆贴预备 + 爆贴  → 爆     (旧逻辑误判成 预备 —— 列序里 预备 在 爆 之前先命中)
      爆贴预备 + 大爆  → 大爆
    单选 / 单值 cell 行为与旧版完全一致。None / 空 → default。
    """
    if raw_status is None:
        return _default_tier(rules)
    tokens = _status_tokens(raw_status)
    if not tokens:
        return _default_tier(rules)
    hits = [t for t in (_first_matching_tier(tok, rules) for tok in tokens) if t is not None]
    if not hits:
        return _default_tier(rules)
    return max(hits, key=lambda t: _TIER_RANK.get(t, 0))


def _default_tier(rules: list[dict]) -> Optional[str]:
    for r in rules:
        if "default" in r:
            return r["default"]
    return None


# notes.intent 的 CHECK 约束取值(schemas/notes_v1_2.sql:200)。map_intent 必须只产出
# 这几个值或 None,否则 upsert 撞 check constraint(codex PR#53)。
_INTENT_ENUM = frozenset({"traffic", "conversion", "educational", "mixed", "other"})


def map_intent(raw_intent: Any, mapping: dict) -> Optional[str]:
    """把飞书「发布笔记」cell 映射成 notes.intent 合法 enum(或 None)。

    两个坑一起处理:
      1. Feishu 可能返回 list(多选 / list[str])或 {'text':...} dict —— 直接拿它做
         intent_mapping 的 dict-key 查找会 `TypeError: unhashable type: 'list'`
         (PR#51 NRT_2 全表 sync 失败根因)。先用 _direction_key 把每个元素展平成字符串。
      2. notes.intent 有 CHECK(只准 traffic/conversion/educational/mixed/other)。
         多选映射到【多个不同 intent】→ 收敛为 'mixed';有值但都没映射到合法 enum
         → 'other'。绝不把原始中文 / 逗号拼接串写进 intent,否则撞 check constraint(PR#53)。
    空 cell → None(intent 列 nullable)。
    """
    if raw_intent is None:
        return None
    raws = raw_intent if isinstance(raw_intent, list) else [raw_intent]
    values = [k for k in (_direction_key(v) for v in raws) if k]
    if not values:
        return None
    mapped = set()
    for v in values:
        m = mapping.get(v, v)        # 按 yaml 映射;无映射退回原值(原值恰好是合法 enum 也接受)
        if m in _INTENT_ENUM:
            mapped.add(m)
    if len(mapped) == 1:
        return next(iter(mapped))
    if len(mapped) >= 2:
        return "mixed"               # 多选落到多个 intent → mixed
    return "other"                   # 有值但都没落到合法 enum → other(不写非法字符串)


# ─────────────────────────────────────────────────────────────────────────
# Note ID generator
# ─────────────────────────────────────────────────────────────────────────

def make_note_id(project_id: str, feishu_record_id: str) -> str:
    """truth_vault.notes.note_id rule (see docs/02-schema-v1.md):
        f"{project_id}_{feishu_record_id}"
    """
    return f"{project_id}_{feishu_record_id}"


def resolve_feishu_tables(sync_config: Optional[dict]) -> list[dict]:
    """把 sync_config 归一成"飞书表定位符列表",支持两种形态:

      · 多表(new): sync_config['tables'] = [
            {feishu_app_token, feishu_table_id, feishu_view_id?}, ... ]
        → 同一 project 合并多张飞书表(如 RIO 同期两表),全部写进 mapping['project_id'];
          note_id = {project_id}_{record} 仍唯一(record_id 跨表碰撞概率可忽略)。
      · 单表(legacy): sync_config 顶层 feishu_app_token / feishu_table_id / feishu_view_id
        (app_token/table_id 可被环境变量 FEISHU_APP_TOKEN / FEISHU_TABLE_ID 兜底)。

    返回 [{'app_token','table_id','view_id'}, ...]。**只做形状归一、不判合法性** ——
    空 / 半配置(只填一半)由调用方按各自退出码语义处理(sync: 占位→0 / 半配→2)。
    """
    sc = sync_config or {}
    raw = sc.get("tables")
    if raw:
        return [
            {
                "app_token": (t or {}).get("feishu_app_token"),
                "table_id": (t or {}).get("feishu_table_id"),
                "view_id": (t or {}).get("feishu_view_id"),
            }
            for t in raw
        ]
    return [
        {
            "app_token": sc.get("feishu_app_token") or os.environ.get("FEISHU_APP_TOKEN"),
            "table_id": sc.get("feishu_table_id") or os.environ.get("FEISHU_TABLE_ID"),
            "view_id": sc.get("feishu_view_id"),
        }
    ]


# ─────────────────────────────────────────────────────────────────────────
# Value coercion · numeric + date
# ─────────────────────────────────────────────────────────────────────────
#
# 飞书 Bitable 单元格的实际值五花八门：
#   - 数值字段（曝光量 / 阅读量 / 互动量等）可能出现:
#       "/" "-" "" "无" "N/A" "暂无"  → 应转 None
#       "1,234"  "1，234"  "１２３"   → 千位分隔/全角，应转 1234/123
#       1234 1234.0                  → 直接接受
#   - 日期字段（publish_time）飞书 API 返回毫秒时间戳（int），需转 ISO
#
# 这两个清洗逻辑由 docs/03-mapping-protocol.md Step 4.5 规定。

_NUMERIC_NULL_TOKENS = {"", "/", "-", "—", "无", "暂无", "/无", "N/A", "n/a", "null", "NULL", "None"}


def parse_array(value: Any) -> Optional[list]:
    """Convert a Feishu cell value to a list[str] suitable for PG TEXT[].

    The complication: 飞书表的 "关键词 / 蓝词记录" 这类字段可能是
        - 多选 cell  → list[dict{text: ...}]   (preferred)
        - 单行文本  → str "营养液, 全营养, 控糖"
        - 多行文本  → str "营养液\\n全营养\\n控糖"
        - 数组       → list[str]   (some Bitable variants)
        - 空 / "无" / "/"  → None

    We accept all of the above and emit list[str]. Returning None lets the
    caller leave the column unset; returning [] is a valid empty array if
    that's what makes sense for the column.

    Splitters: , 、 / ， \\n  (Chinese & English comma, ideographic comma,
    slash, newline).  All trimmed; empties dropped.
    """
    if value is None:
        return None
    if isinstance(value, list):
        if not value:
            return []
        if all(isinstance(x, dict) and "text" in x for x in value):
            return [str(x["text"]).strip() for x in value if x.get("text")]
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str):
        s = value.strip()
        if not s or s in _NUMERIC_NULL_TOKENS:
            return None
        parts = re.split(r"[,，、/\n]+", s)
        return [p.strip() for p in parts if p.strip()]
    # int/float/bool/dict: stringify
    return [str(value)]


def _direction_key(value: Any) -> str:
    """Flatten a Feishu 方向 cell to a hashable string key for the
    direction_decomposition / excluded_directions lookups.

    Feishu returns this column as a str, or a list whose elements are plain
    strings (multi-select) or {'text': ...} dicts (rich-text / option cells).
    Using the raw list as a dict key raises `TypeError: unhashable type:
    'list'`. We join multi-value lists with ", " to match the mapping yaml's
    multi-direction keys (e.g. excluded_directions "女性自发, 男性自发"), the
    same per-element convention parse_array() uses. A single-value cell yields
    just that value, so single-direction configs still match.

    Used at BOTH sync time (transform_row) and annotation time
    (annotate_essence_pass.get_sub_directions_for_note) — keep them consistent
    by sharing this one helper, or a list-valued direction just moves the
    crash from one pass to the next. Also reused by extract_tier() to flatten a
    list/dict 状态 cell before substring matching (same generic Feishu-cell →
    string logic; the name says 方向 for historical reasons).
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("text", "")).strip()
    if isinstance(value, list):
        parts = [
            str(x.get("text", "")).strip() if isinstance(x, dict) else str(x).strip()
            for x in value
        ]
        return ", ".join(p for p in parts if p)
    return "" if value is None else str(value)


def parse_numeric(value: Any) -> Optional[float]:
    """Robustly convert a Feishu cell value to a number, or None if it's
    one of the conventional 'no data' tokens.

    Accepts:
        - int / float                  → unchanged
        - str "1,234"  "1，234"          → 1234.0 (Chinese/English thousands)
        - str "１２３"                    → 123.0 (full-width digits)
        - str "1.4万" "3.2w" "1.2亿"      → 14000.0 / 32000.0 / 120000000.0 (中文万位)
        - str "/" "-" "" "无" "N/A" ... → None
        - None                          → None
        - list/dict (non-numeric)       → None

    Returns float because numeric Feishu cells can be decimal.  Cast to int
    at write time if the target column is INT.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s in _NUMERIC_NULL_TOKENS:
        return None
    # Normalize: drop thousands separators (both CN ， and EN ,) + convert
    # full-width digits to ASCII via str.translate.
    fullwidth = str.maketrans("０１２３４５６７８９．", "0123456789.")
    s2 = s.translate(fullwidth).replace(",", "").replace("，", "")
    # 中文数量级后缀(2026-08-31 补)。小红书/抖音的后台在数大了之后会显示「1.4万」而不是
    # 14000 —— 在这之前这类值走到下面的 float() 会 ValueError → 返回 None, 也就是
    # 【静默丢掉】。丢的还偏偏是表现最好的那批行(只有数大了才会显示成万), 等于把高分行
    # 系统性地从指标里择出去。LNKT_phase1 的「数据汇总」文本里实测 2 行如此, 全库其余 1 行。
    # 只在原本会返回 None 的路径上补, 所以不会改变任何已经解析成功的值。
    _SUFFIX = {"万": 1e4, "w": 1e4, "W": 1e4, "亿": 1e8}
    if s2 and s2[-1] in _SUFFIX:
        try:
            return float(s2[:-1]) * _SUFFIX[s2[-1]]
        except ValueError:
            return None
    try:
        return float(s2)
    except ValueError:
        return None


def parse_feishu_date(value: Any) -> Optional[str]:
    """Convert a Feishu Bitable date cell to a Postgres-friendly ISO string.

    Feishu returns dates as int milliseconds since epoch.  This function
    accepts that, plus strings that already look like ISO timestamps
    (passes them through unchanged after stripping).  Returns None for
    empty/invalid values rather than letting them crash the INSERT.
    """
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        if not s or s in _NUMERIC_NULL_TOKENS:
            return None
        return s  # caller's problem if format is bad; Postgres will reject
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Heuristic: > 10**12 means milliseconds (since 2001-09-09 in ms);
        # smaller means seconds (since 2286-11-20 in s, which is far future,
        # so treating it as seconds is reasonable as a backup).
        ts = float(value)
        if ts > 10**12:
            ts = ts / 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")
        except (OSError, OverflowError, ValueError):
            return None
    return None


def _audience_text(value: Any) -> str:
    """把飞书「观众分析」cell 归一成 parse_audience_analysis 期望的【；分段】文本。

    富文本/多段会返回 list[dict{text}] 或 list[str] —— 那是【一段连续文本的富文本 run】,
    原文的 ；分段在文本内容里, 所以各段【直接拼接(空串连)】即还原, 解析器照常按 ； 切段。
    绝不能用 _direction_key 的 ', ' 连 —— 逗号会破坏 ；分段 + 段内 ，pairs, 让后面的
    年龄/城市/阅读时长段被丢(codex PR#59 review)。str 原样; dict 取 text; None → ''。
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("text", ""))
    if isinstance(value, list):
        return "".join(
            (x.get("text", "") if isinstance(x, dict) else str(x if x is not None else ""))
            for x in value
        )
    return str(value)


def parse_kv_metrics(value: Any) -> dict[str, float]:
    """把「键：值；键：值」半结构化文本解析成 {键: 数值}。

    与 parse_audience_analysis 是【同一形状】的文本(；分段, ：分键值), 所以共用
    _audience_text 做富文本归一 —— 那个函数本身与"受众"无关, 只是把
    str / dict{text} / list[富文本run] 拍平成一段连续文本。

    用途: 有些飞书表不给独立的指标列, 而是把一次数据回收的所有指标塞进一个文本 cell。
    LNKT_phase1(抖音)的「数据汇总-第N次」就是这样:
        "播放量：2187；点赞量：77；评论量：11；分享量：0；收藏量：2；划走率：49.18%；…"

    解析口径:
      - 只取【纯数值】键。带 % 的比率键(划走率/完读率/…)一律【跳过】——
        它们与计数键混在同一段文本里, 若按裸数字收会把 "49.18%" 当成 49.18 个单位,
        而调用方要的是计数。要比率请另写解析, 不要放宽这里。
      - 千分位逗号(1,234)会被 parse_numeric 处理; 空段 / 无值 / "无" 跳过。
      - 同名键重复出现取【最后一个】(与 dict 赋值语义一致, 实测未出现重复)。
      - 解析不出任何键 → 返回空 dict(不是 None), 调用方按"这个快照没数据"处理。
    """
    text = _audience_text(value).strip()
    if not text:
        return {}
    out: dict[str, float] = {}
    for seg in re.split(r"[；;]", text):
        parts = re.split(r"[：:]", seg.strip(), maxsplit=1)
        if len(parts) != 2:
            continue
        key, raw = parts[0].strip(), parts[1].strip()
        if not key or not raw or raw in ("无", "-"):
            continue
        # 比率键显式跳过。注意这是【防御层】而不是当前唯一屏障 —— 今天的 parse_numeric
        # 对 "49.18%" 本来就返回 None, 所以去掉这两行行为暂时不变。留着是因为
        # parse_numeric 是全仓共用的, 哪天有人给它加上"识别百分号"这种健壮性改造,
        # 比率就会静默流进计数指标(下游拿一个百分数去比互动量阈值)。CI 守卫用
        # monkeypatch 把 parse_numeric 换成会吃 % 的版本, 专门测这一层还在。
        if "%" in raw:
            continue
        num = parse_numeric(raw)
        if num is not None:
            out[key] = num
    return out


def parse_audience_analysis(value: Any) -> Optional[dict]:
    """Parse 半结构化「观众分析」文本 → notes.actual_audience_data (文档约定形状).

    WTG ROC素人分发表 的「观众分析」列格式 (；分段, ：分键值):
      "性别分布：男性4%，女性96%；年龄分布：<18占2%，18-24占5%，25-34占45%；
       城市分布：上海11%，北京5%；阅读时长：14.7秒"

    输出对齐 docs/07-audience-data.md 约定 (消费方 prompts/audience_inferrer.md
    直接 actual['gender_distribution']['female'] / actual['age_distribution']):
      - top-level 键: gender_distribution / age_distribution / city_distribution
      - 百分比【归一化成分数】(96% → 0.96), 不是原始 96.0 (否则下游 ×100 错)
      - 性别键映射英文 female / male (消费方按英文键直接索引)
      - 年龄/城市保留源 bucket 标签 (WTG 分桶 != 蒲公英标准桶, 消费方只 iterate
        items() 取 majority, 标签不影响)
      - read_duration_sec 是秒数, 不归一化
    空段 ("性别分布：" / "性别分布：无") 跳过. 全空 / None / 非字符串 → None.
    """
    text = _audience_text(value).strip()   # 归一 str/list/dict(富文本段空串拼接)→ ；分段文本
    if not text:
        return None

    _GENDER_KEY = {"男性": "male", "男": "male", "女性": "female", "女": "female"}

    def _pairs(s: str) -> dict:
        # "男性4%，女性96%" / "<18占2%，18-24占5%" → {name: pct_float}
        out: dict[str, float] = {}
        for part in re.split(r"[，,]", s):
            part = part.strip()
            if not part or part in ("无", "-"):
                continue
            m = re.match(r"^(.+?)占?(\d+(?:\.\d+)?)\s*%?$", part)
            if m:
                try:
                    out[m.group(1).strip()] = float(m.group(2))
                except ValueError:
                    pass
        return out

    def _as_fraction(d: dict, key_map: Optional[dict] = None) -> dict:
        # 百分比 → 分数 (96 → 0.96); 可选键名映射 (性别 → 英文 female/male)
        return {
            (key_map.get(k, k) if key_map else k): round(v / 100.0, 4)
            for k, v in d.items()
        }

    result: dict[str, Any] = {}
    for sec in re.split(r"[；;]", text):
        parts = re.split(r"[：:]", sec.strip(), maxsplit=1)
        if len(parts) != 2:
            continue
        key, val = parts[0].strip(), parts[1].strip()
        if not val or val == "无":
            continue
        if key.startswith("性别"):
            raw = _pairs(val)
            if raw:
                result["gender_distribution"] = _as_fraction(raw, _GENDER_KEY)
        elif key.startswith("年龄"):
            raw = _pairs(val)
            if raw:
                result["age_distribution"] = _as_fraction(raw)
        elif key.startswith("城市"):
            raw = _pairs(val)
            if raw:
                result["city_distribution"] = _as_fraction(raw)
        elif key.startswith("阅读时长"):
            mnum = re.search(r"(\d+(?:\.\d+)?)", val)
            if mnum:
                result["read_duration_sec"] = float(mnum.group(1))
    if not result:
        return None
    result["data_source"] = "feishu_观众分析"
    result["_raw"] = text[:500]
    return result


def quarantine_record(
    client: Client,
    project_id: str,
    feishu_record_id: str,
    raw_row: dict[str, Any],
    undeclared_fields: list[str],
    reason: str = "undeclared_fields",
) -> None:
    """Write the entire raw row to truth_vault.undeclared_fields_quarantine
    instead of silently dropping new/unknown fields. See D-021.

    Idempotent on (project_id, feishu_record_id, reason) — repeated runs of
    sync_feishu on a row that still has undeclared fields don't pile up rows
    in the quarantine table. Backed by the NON-partial unique index
    uq_quarantine_project_record_reason (notes_v1_2.sql): PostgREST emits a
    predicateless `ON CONFLICT (cols)` which Postgres CANNOT match to a partial
    index (raises 42P10), so the index must be non-partial. It uses the default
    NULLS DISTINCT — non-null feishu_record_id rows dedup, while anonymous
    (NULL feishu_record_id) rows are allowed to coexist. ignore_duplicates=True
    preserves any reviewer state (status/review_decision/reviewed_by) an operator
    has already set on the first-seen quarantine row.
    """
    (
        client.schema("truth_vault")
        .table("undeclared_fields_quarantine")
        .upsert(
            {
                "project_id": project_id,
                "feishu_record_id": feishu_record_id,
                "raw_row": raw_row,
                "undeclared_field_names": undeclared_fields,
                "reason": reason,
                "status": "pending",
                "quarantined_at": _iso_now(),
            },
            on_conflict="project_id,feishu_record_id,reason",
            ignore_duplicates=True,
        )
        .execute()
    )


def ensure_account_exists(
    client: Client,
    account_id: Optional[str],
    platform: str = "xiaohongshu",
    owner_type: str = "素人",
) -> None:
    """UPSERT a row into truth_vault.accounts so subsequent notes inserts
    don't get rejected by the FK constraint
    `notes.account_id REFERENCES accounts(account_id)`.

    Called by sync_feishu_notes_to_truth_vault.py before each note upsert.
    Idempotent (on_conflict=account_id). Skips silently if account_id is
    None or empty (the note will be inserted without account_id, which is
    allowed because the FK is nullable).

    Owner_type default '素人' matches the Truth Vault docs convention for
    飞书素人编号 — KOC/KOL/brand accounts come from different ingest paths.
    """
    if not account_id:
        return
    (
        client.schema("truth_vault")
        .table("accounts")
        .upsert(
            {
                "account_id": account_id,
                "platform": platform,
                "owner_type": owner_type,
                "first_seen_at": _iso_now(),
            },
            on_conflict="account_id",
            # Don't overwrite existing first_seen_at on conflict — Supabase
            # upsert with default behavior would; instead use ignore_duplicates
            # so we keep the original first_seen_at the first time we saw it.
            ignore_duplicates=True,
        )
        .execute()
    )


def ensure_project_exists(client: Client, mapping: dict) -> None:
    """UPSERT a row into truth_vault.projects from the mapping yaml.

    Called by sync_feishu_notes_to_truth_vault.py before any notes are
    inserted.  Without this, the very first sync on a fresh deployment
    would fail with FK violation
    (`notes.project_id REFERENCES projects(project_id)`).

    Update semantics (split mapping-owned vs manually-curated):
      • mapping-owned fields (brand / product / category / platform /
        schema_family / tier_thresholds / mapping_config) ARE updated on
        re-sync. The yaml is the source of truth — if NRT_phase2's category
        flips from 处方药 to OTC药 (vocab v1 §9), the DB row should reflect
        that on the next sync.
      • cross-system mapping columns (mapping_to_autowriter_project_id /
        mapping_to_sanshengliubu_project_id) are manually maintained post-
        onboarding and MUST NOT be overwritten. We achieve this by simply
        not including them in `row` — Supabase upsert only touches columns
        sent in the payload, so absent keys preserve whatever's in the DB.
      • derived stats (total_notes / notes_with_data / etc) are likewise
        never sent here.
      • start_date / end_date are computed from notes.publish_time via
        update_project_date_range() called at the end of sync, not from
        the yaml (the yaml has placeholder strings like
        'auto_from_publish_time_min' that aren't DATE-castable).
    """
    project_id = mapping.get("project_id")
    if not project_id:
        raise ValueError("mapping yaml is missing required field: project_id")

    # Subset of the yaml that's safe to snapshot into projects.mapping_config JSONB
    # for traceability.  We strip out big or sensitive sections.
    mapping_snapshot = {
        k: v for k, v in mapping.items()
        if k in {
            "version", "schema_family", "intent_mapping",
            "tier_extraction", "tier_thresholds", "data_supplement_needed",
            "project_specific_fields_to_raw_extra",
        }
    }

    row = {
        "project_id":     project_id,
        "brand":          mapping.get("brand") or "(未填)",
        "product":        mapping.get("product") or "(未填)",
        "category":       mapping.get("category") or "其他",
        "platform":       mapping.get("platform", "xiaohongshu"),
        "schema_family":  mapping.get("schema_family"),
        "tier_thresholds": mapping.get("tier_thresholds") or None,
        "mapping_config": mapping_snapshot,
    }
    # Trim None values that would violate NOT NULL CHECKs (brand/product/category
    # are NOT NULL).  Defaults above cover that, so this is belt-and-suspenders.
    row = {k: v for k, v in row.items() if v is not None}

    # ignore_duplicates omitted → default UPDATE-on-conflict. Updates every
    # column present in `row`; columns absent from `row` (the cross-system
    # mapping cols, derived stats, start/end dates, created_at) are preserved.
    (
        client.schema("truth_vault")
        .table("projects")
        .upsert(row, on_conflict="project_id")
        .execute()
    )


def update_project_date_range(client: Client, project_id: str) -> None:
    """Compute and write projects.start_date / end_date from notes.publish_time.

    The mapping yaml carries `start_date: auto_from_publish_time_min` placeholders
    that aren't database-castable, so ensure_project_exists() can't fill them.
    Run this at the END of sync (after all notes are upserted) to keep the
    project-level date range honest.

    No-op if the project has no notes with publish_time set yet.

    2026-05-22 audit P1: 老版本是两次独立 SELECT + 一次 UPDATE 三步, 中间没
    事务保护. 同一时刻另一个 sync_feishu 写入新 note, 可能让 start_date >
    end_date (查 earliest 时数据是 A, 查 latest 时数据更新成 B). 改成单条
    AGGREGATE: client 端 fetch 完所有 publish_time 再算 min/max, 一次 UPDATE.
    PostgREST 不支持 SELECT MIN/MAX 子查询 + UPDATE 的原子写, 但 client 端
    one-shot 算完已经把 race window 关掉了 (要 race, 得在 fetch 那一瞬间
    insert; 而 insert 走 upsert + 不动 start/end_date 列, 不会产生 start>end).
    """
    # 一次 fetch 拿到所有 publish_time. 行数大时 fetch_all_pages 自动分页.
    # note_id 只为分页做稳定键(publish_time 不唯一), 不参与下面的 min/max。
    rows = fetch_all_pages(
        client.schema("truth_vault").table("notes")
        .select("note_id, publish_time")
        .eq("project_id", project_id)
        .not_.is_("publish_time", None),
        order_by="note_id",
    )
    if not rows:
        return
    times = [str(r["publish_time"])[:10] for r in rows if r.get("publish_time")]
    if not times:
        return
    update = {
        "start_date": min(times),
        "end_date":   max(times),
    }
    (
        client.schema("truth_vault")
        .table("projects")
        .update(update)
        .eq("project_id", project_id)
        .execute()
    )


# ─────────────────────────────────────────────────────────────────────────
# Secret masking (2026-05-22 audit P3)
# ─────────────────────────────────────────────────────────────────────────

import re as _re

# 已知 secret 前缀正则. 加新格式时往这里加, 让 mask_secrets 覆盖所有 logger.
_SECRET_PATTERNS = [
    _re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),       # Anthropic
    _re.compile(r"sb_secret_[A-Za-z0-9]{20,}"),       # Supabase 2024+
    _re.compile(r"sbp_[A-Za-z0-9]{20,}"),             # Supabase service token
    _re.compile(r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}"),  # JWT
    _re.compile(r"AIza[A-Za-z0-9_\-]{20,}"),          # Google API key
    _re.compile(r"sk-proj-[A-Za-z0-9_\-]{20,}"),      # OpenAI
    _re.compile(r"sk-[A-Za-z0-9]{40,}"),              # OpenAI 老格式
]


def mask_secrets(s: str) -> str:
    """Mask known secret patterns in a string before logging it.

    Logger formatters / exception handlers / telemetry events should pipe
    user-visible strings through this before writing. Conservative — won't
    catch every secret shape, but catches Anthropic / Supabase / Google /
    OpenAI / JWT default formats.

    For exception messages from supabase-py / requests that may include
    bearer tokens in URLs or stacktrace, pass `mask_secrets(str(exc))`.
    """
    if not isinstance(s, str) or not s:
        return s
    for pat in _SECRET_PATTERNS:
        s = pat.sub("***REDACTED***", s)
    return s


# ─────────────────────────────────────────────────────────────────────────
# Pagination helper
# ─────────────────────────────────────────────────────────────────────────

# Supabase PostgREST default response cap. Configurable in Settings → API →
# Max Rows; production default is 1000 unless changed. If we want to avoid
# silently truncating large result sets, every "fetch all" path needs to
# loop until the page is short.
_DEFAULT_PAGE_SIZE = 1000


def fetch_all_pages(query_builder, page_size: int = _DEFAULT_PAGE_SIZE,
                    *, order_by: str) -> list:
    """Drain a Supabase PostgREST query across all pages.

    Usage:
        rows = fetch_all_pages(
            sb.schema("truth_vault").table("notes")
              .select("note_id, ...")
              .in_("tier", ["爆", "大爆"]),
            order_by="note_id",
        )

    ⚠️ ``order_by`` 是**必填**的, 且必须是【唯一 + 稳定】的列, 还必须出现在
    ``.select()`` 里。这不是洁癖, 是这个函数的正确性前提:

    OFFSET 分页的每一页是一次**独立的 HTTP 请求**(各自的事务快照, 相隔数秒)。
    SQL 对没有 ORDER BY 的查询【不保证任何行序】, 两次请求的顺序完全可以不同,
    于是跨页时**有的行被跳过、有的行被取两遍** —— 而且不报错, 脚本照常打印
    成功。这不是理论: 本库 synchronize_seqscans=on(PG 默认, seq scan 允许从
    表中间开始并绕回), 且 truth_vault.notes 插入 4.2k 行却被 UPDATE 过 12 万次
    (每行约 28.6 次), 每次 UPDATE 都把新元组写到可能不同的页 —— 物理顺序被
    反复重排。2026-08-23 审计时已有 4 个调用点跨过 1000 行页边界。

    "稳定"= 值不随时间变。**不能**用 rank_score / injection_score 这类含
    recency 项、随墙钟连续变化的计算列做唯一排序键: 页与页之间它就重排了。
    那些列可以作为**主排序**保留在 builder 里(``.order(...)`` 先调), 本函数
    再追加 ``order_by`` 作次级键把顺序钉死。

    另外两点实现约束(都验证过, 别改回去):

    1. ``.order()`` 是**追加**语义(postgrest-py 把新列拼到已有 order 串后面),
       所以只能在循环**外**调一次; 放循环里会拼成 ``id.asc,id.asc,id.asc,...``。
    2. ``.range()`` 用的是 ``params.add()`` 而非 ``set()``, 循环里重复调会累积成
       ``offset=0&offset=1000&offset=2000&...``。实测 PostgREST 取**最后一个**,
       所以现在能正常翻页 —— 但这是**未文档化行为**, 万一哪天改成取第一个,
       每页都会返回同一批行、``len(page)==page_size`` 永真 → **死循环**。
       下面的 ``seen`` 去重兼进度检查就是这条的保险: 一页里一条新行都没有就
       判定没有进展并报错, 不会静默转圈也不会返回重复行。
    """
    q = query_builder.order(order_by)      # 一次, 循环外 —— 见上方约束 1
    rows: list = []
    seen: set = set()
    start = 0
    while True:
        page = (q.range(start, start + page_size - 1).execute()).data or []
        if page and order_by not in page[0]:
            raise RuntimeError(
                f"fetch_all_pages: order_by={order_by!r} 不在返回列里 —— "
                f"请把它加进 .select()。拿到的列: {sorted(page[0])}"
            )
        fresh = [r for r in page if r.get(order_by) not in seen]
        if page and not fresh:
            raise RuntimeError(
                f"fetch_all_pages: offset={start} 这一页 {len(page)} 行全是重复的, "
                "分页没有前进。多半是 PostgREST 对重复 offset 参数的取值行为变了"
                "(见本函数 docstring 约束 2), 或 order_by 不唯一。"
            )
        seen.update(r.get(order_by) for r in fresh)
        rows.extend(fresh)
        # ⚠️ 终止判据是【空页】而不是【短页】, offset 按【实拿到的行数】前进。
        # PostgREST 的 max-rows 会把请求钳短。本库实测 max-rows=1000, 而
        # _DEFAULT_PAGE_SIZE 也是 1000 —— 正好相等才没出事, 零余量:
        #   curl 'stage_logs?select=id' -H 'Range: 0-1071'
        #     → 只回 1000 行, content-range: 0-999/*
        # 上限一旦被调低(或哪天 PostgREST 换了默认值), 每一页都成"短页",
        # 按 len(page) < page_size 收工 = 第一页就返回 = 24 个调用点集体静默截断,
        # 恰好是本函数存在的理由。按空页收工则与服务端上限无关, 代价是末尾多发
        # 一次空请求。(codex aw#57 review 指出同类问题, 本仓同一缺陷)
        if not page:
            return rows
        start += len(page)


# ─────────────────────────────────────────────────────────────────────────
# Time helpers
# ─────────────────────────────────────────────────────────────────────────

def _iso_now() -> str:
    """UTC ISO timestamp, suitable for PostgREST TIMESTAMP columns.

    The schema uses `TIMESTAMP WITHOUT TIME ZONE` (not TIMESTAMPTZ), so we
    emit a naive UTC string. If we included the `+00:00` suffix, Postgres
    would silently strip the timezone on insert and downstream readers
    would have no way to know the value is UTC. Naive UTC + a project
    convention ("all timestamps are UTC") is more predictable until/unless
    the schema migrates to TIMESTAMPTZ.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _iso_now_tz() -> str:
    """UTC ISO timestamp **带偏移量**, 给 ``TIMESTAMPTZ`` 列用。

    ⚠️ 和上面那个 ``_iso_now()`` 是两件事, 别混:

      · ``_iso_now()`` 故意去掉时区, 因为本仓绝大多数列是
        ``TIMESTAMP WITHOUT TIME ZONE``, 带上 ``+00:00`` 会被 Postgres 悄悄
        丢掉、读的人再也判不出它是不是 UTC;
      · ``TIMESTAMPTZ`` 列**正相反** —— 给它一个 naive 串, Postgres 会按
        **会话时区**解释再转成 UTC 存。会话时区不是 UTC 时(连接默认不保证是),
        存进去的时刻整体偏几个小时, 基于它算的"消失了多久"跟着错, 而且不报错。
        (codex review)

    ``notes.last_seen_at`` 是 ``TIMESTAMPTZ``(见 schemas/notes_v1_9), 走这个。
    以后新增 TIMESTAMPTZ 列也走这个。
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ─────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────

def setup_logger(name: str, level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s · %(message)s")
    )
    logger.addHandler(h)
    return logger
