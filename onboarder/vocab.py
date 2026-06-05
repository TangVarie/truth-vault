"""onboarder/vocab.py — 受控词表闭集 + mapping 校验器(硬护栏)。

docs/05-controlled-vocab.md / docs/04 §Step 3 的闭集在这里写死。校验器是
docs/16 说的"词表硬校验":agent 起草的 mapping 里任何【非占位】的 content_format /
target_audience / tier / intent / schema_family 取值,只要不在闭集里就是 error,
emit_draft 据此 is_error 让 agent 自己改(也可由 PreToolUse hook 拦)。

占位值([待确认] / 空 / None)不算 error —— 草稿合法地留着判断项给策略 lead。
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

# ── 闭集(改这里 = 改护栏;须与 docs/05 / docs/04 同步)──────────────────────
CONTENT_FORMATS = (
    "情感叙事", "认知重构", "横评对比", "教程攻略",
    "直给推荐", "场景植入", "提问求助", "反差破圈",
)  # docs/04 §Step 3 / WTG_phase1.yaml 注释(8 值)

TARGET_AUDIENCES = (
    "年轻女性", "中年女性", "银发女性", "年轻男性", "中年男性", "银发男性",
    "学生党", "宝妈", "伴侣家人", "病患家属", "通用",
)  # docs/04 line 123(11 值)

TIERS = ("大爆", "爆", "预备", "参考", "风控", "趴", "未知", "删除", "数据异常")  # docs/05 §10(9 值)= notes_v1_3 tier CHECK

TIER_SOURCES = ("状态字段", "备注字段")  # tier_extraction.source 闭集(sync 只认这两个)

INTENTS = ("traffic", "conversion", "educational", "mixed", "other")  # docs/05 §1(5 值)= notes_v1_2 intent CHECK

SCHEMA_FAMILIES = ("A", "B", "C")

CATEGORIES = (
    "处方药", "OTC药", "保健品", "医疗器械", "美妆", "个护", "酒类",
    "食品饮料", "母婴", "3C数码", "家居家电", "服饰鞋包", "教育", "其他",
)  # 权威清单 = docs/05-controlled-vocab.md §9「统一词表 v1」(14 值);改这里要同步改 docs/05 §9

# 占位/待确认 → 草稿里合法,不算 error
_PENDING = {"", "[待确认]", "待确认", "[待定]", "待定", "null", "None", "?"}


def is_pending(value: Any) -> bool:
    if value is None:
        return True
    s = str(value).strip()
    return s in _PENDING or s.startswith("[待")


def _check(value: Any, closed: Iterable[str], label: str, errors: list, pending: list):
    """非占位值必须在闭集内,否则记 error;占位值记 pending。"""
    if is_pending(value):
        pending.append(label)
        return
    if str(value).strip() not in closed:
        errors.append(f"{label}: 取值 {value!r} 不在受控词表 {tuple(closed)} 内")


def _iter_audiences(val: Any) -> list:
    if isinstance(val, (list, tuple)):
        return list(val)
    return [val] if val is not None else []


def validate_mapping(
    mapping: dict, columns: Optional[Iterable[str]] = None
) -> dict[str, list]:
    """校验一份(已 yaml.safe_load 的)mapping。

    返回 {"errors": [...], "pending": [...], "uncovered_columns": [...]}:
      - errors            : 非占位的词表外取值 / 结构性硬错(必须 0 才能定稿)
      - pending           : 仍是 [待确认] 的判断项(草稿合法,供人拍板清单)
      - uncovered_columns : 既没 map 也没进 raw_extra allowlist 的飞书列
                            (D-021:会整行进 quarantine;传了 columns 才检)
    """
    errors: list[str] = []
    pending: list[str] = []

    if not isinstance(mapping, dict):
        return {"errors": ["mapping 不是 dict(yaml 解析失败?)"], "pending": [], "uncovered_columns": []}

    # 元数据闭集
    if "schema_family" in mapping:
        _check(mapping.get("schema_family"), SCHEMA_FAMILIES, "schema_family", errors, pending)
    if "category" in mapping:
        _check(mapping.get("category"), CATEGORIES, "category", errors, pending)

    # intent_mapping 的右值(enum)
    for k, v in (mapping.get("intent_mapping") or {}).items():
        _check(v, INTENTS, f"intent_mapping[{k}]", errors, pending)

    # tier_extraction.source(闭集)+ rules[*].tier
    te = mapping.get("tier_extraction") or {}
    if "source" in te:
        _check(te.get("source"), TIER_SOURCES, "tier_extraction.source", errors, pending)
    for i, rule in enumerate(te.get("rules", []) or []):
        if isinstance(rule, dict) and "tier" in rule and rule["tier"] is not None:
            _check(rule["tier"], TIERS, f"tier_extraction.rules[{i}].tier", errors, pending)

    # direction_decomposition(含 sub_directions)
    def _check_direction(name: str, d: dict):
        if "content_format" in d:
            _check(d.get("content_format"), CONTENT_FORMATS, f"direction[{name}].content_format", errors, pending)
        for aud in _iter_audiences(d.get("target_audience")):
            _check(aud, TARGET_AUDIENCES, f"direction[{name}].target_audience", errors, pending)
        if d.get("intent_override") is not None and not is_pending(d.get("intent_override")):
            _check(d["intent_override"], INTENTS, f"direction[{name}].intent_override", errors, pending)

    for name, d in (mapping.get("direction_decomposition") or {}).items():
        if not isinstance(d, dict):
            continue
        subs = d.get("sub_directions")
        if isinstance(subs, list) and subs:
            for sub in subs:
                if isinstance(sub, dict):
                    _check_direction(f"{name}/{sub.get('name', '?')}", sub)
        else:
            _check_direction(name, d)

    # D-021:列覆盖(传了真实列名才检)
    uncovered: list[str] = []
    if columns is not None:
        declared = set((mapping.get("field_mapping") or {}).keys())
        declared |= set(mapping.get("project_specific_fields_to_raw_extra", []) or [])
        ignored = {"_record_id", "_created_time", "_last_modified_time"}
        uncovered = [c for c in columns if c not in declared and c not in ignored]

    return {"errors": errors, "pending": pending, "uncovered_columns": uncovered}


def vocab_reference() -> str:
    """给 agent system prompt / 工具用的人类可读闭集清单。"""
    return (
        "content_format(8): " + " / ".join(CONTENT_FORMATS) + "\n"
        "target_audience(11): " + " / ".join(TARGET_AUDIENCES) + "\n"
        "tier(9): " + " / ".join(TIERS) + "\n"
        "tier_extraction.source(只能二选一): " + " / ".join(TIER_SOURCES) + "\n"
        "intent(5): " + " / ".join(INTENTS) + "\n"
        "schema_family: " + " / ".join(SCHEMA_FAMILIES) + "\n"
        "category: " + " / ".join(CATEGORIES)
    )
