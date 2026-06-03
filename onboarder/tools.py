"""onboarder/tools.py — claude-agent-sdk 的 in-process 工具(@tool)。

agent 只允许用这 5 个工具(core.ALLOWED_TOOLS + PreToolUse 护栏),全部只读 /
受控写:
    pull_feishu_table     拉飞书表的列 + 样本行(只读)
    read_mapping_corpus   读历史 mapping + 家族指纹 + 词表(只读)
    recommend_thresholds  按互动量分布推荐 tier 阈值(纯计算)
    validate_mapping_yaml 校验草稿(词表 + D-021 覆盖)—— 让 agent 自查
    emit_draft            产出 draft yaml + review brief(唯一的写;再校验一次兜底)

工具返回约定(claude-agent-sdk):{"content": [{"type":"text","text": ...}],
可选 "is_error": True}。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml
from claude_agent_sdk import tool

from . import clients, corpus, vocab


def _text(s: str, is_error: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"content": [{"type": "text", "text": s}]}
    if is_error:
        out["is_error"] = True
    return out


# ── 1. 拉飞书表 ──────────────────────────────────────────────────────────
@tool(
    "pull_feishu_table",
    "拉飞书表前 N 行【文案样本】+ 样本里出现的列(只读)。看正文用;**枚举方向/状态请用 "
    "list_field_options 或 distinct_values,别靠这 N 行(稀有方向会漏)**。",
    {"app_token": str, "table_id": str, "sample_n": int},
)
async def pull_feishu_table(args: dict[str, Any]) -> dict[str, Any]:
    try:
        data = clients.pull_columns_and_samples(
            args["app_token"], args["table_id"], int(args.get("sample_n", 30) or 30)
        )
    except Exception as exc:  # noqa: BLE001 —— 把错误回给 agent,别炸进程
        return _text(f"拉表失败: {type(exc).__name__}: {exc}", is_error=True)
    return _text(
        f"列({len(data['columns'])}): {data['columns']}\n\n"
        f"样本 {data['n']} 行:\n" + json.dumps(data["rows"], ensure_ascii=False, indent=2)
    )


# ── 1b. 字段元数据(枚举型列的权威/完整取值)──────────────────────────────
@tool(
    "list_field_options",
    "列出飞书表所有字段:名称 + 类型 + 单选/多选字段的【完整】选项。枚举方向/状态优先用它;"
    "字段名也是 D-021 列覆盖的权威清单(含空列)。",
    {"app_token": str, "table_id": str},
)
async def list_field_options(args: dict[str, Any]) -> dict[str, Any]:
    try:
        fields = clients.list_fields(args["app_token"], args["table_id"])
    except Exception as exc:  # noqa: BLE001
        return _text(f"列字段失败: {type(exc).__name__}: {exc}", is_error=True)
    lines = [f"字段 {len(fields)} 个(权威列清单;带「选项」的是枚举型列的完整取值):"]
    for f in fields:
        tail = f"  选项({len(f['options'])}): {f['options']}" if f["options"] else ""
        lines.append(f"- {f['field_name']} (type={f['type']}){tail}")
    return _text("\n".join(lines))


# ── 1c. 全表 distinct(文本型枚举列取全集)──────────────────────────────────
@tool(
    "distinct_values",
    "对指定列做【全表】扫描,返回每列完整 distinct 取值 + 计数。枚举型【文本】列"
    "(方向/状态/发布笔记/备注 若不是单选字段)用它拿全集,别从样本凑。",
    {"app_token": str, "table_id": str, "columns": list},
)
async def distinct_values(args: dict[str, Any]) -> dict[str, Any]:
    cols = args.get("columns") or []
    if not cols:
        return _text("columns 不能为空", is_error=True)
    try:
        res = clients.distinct_values(args["app_token"], args["table_id"], cols)
    except Exception as exc:  # noqa: BLE001
        return _text(f"distinct 扫描失败: {type(exc).__name__}: {exc}", is_error=True)
    out = [f"全表扫描 {res['scanned']} 行:"]
    for c, items in res["distinct"].items():
        out.append(f"\n[{c}] {len(items)} 个不同值:")
        out.extend(f"  {val!r} × {cnt}" for val, cnt in items)
    return _text("\n".join(out))


# ── 2. 读历史语料 ────────────────────────────────────────────────────────
@tool(
    "read_mapping_corpus",
    "读受控词表 + schema 家族指纹 + 全部历史 mapping 原文。起草前先读它,做跨表对齐 + 复用已有拆解。",
    {"exclude_project_id": str},
)
async def read_mapping_corpus(args: dict[str, Any]) -> dict[str, Any]:
    return _text(corpus.build_corpus_context(exclude=args.get("exclude_project_id") or None))


# ── 3. 推荐 tier 阈值 ────────────────────────────────────────────────────
def _pctile(vals: list[float], q: float):
    if not vals:
        return None
    s = sorted(vals)
    i = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[i]


@tool(
    "recommend_thresholds",
    "传入互动量数组,返回分布(中位/P90/P95/P99/max)+ 推荐的 爆/大爆 数值阈值兜底。",
    {"interactions": list},
)
async def recommend_thresholds(args: dict[str, Any]) -> dict[str, Any]:
    raw = args.get("interactions") or []
    nums: list[float] = []
    for v in raw:
        try:
            nums.append(float(str(v).replace(",", "").strip()))
        except (TypeError, ValueError):
            continue
    if not nums:
        return _text("无可用互动量数值(样本里该列可能全为占位符)。阈值留 [待确认]。")
    p99 = _pctile(nums, 0.99)
    mx = max(nums)
    rec_bao = int(round(p99)) if p99 else None
    rec_dabao = int(round(mx)) if mx else None
    return _text(
        f"n={len(nums)} 中位={_pctile(nums,0.5)} P90={_pctile(nums,0.9)} "
        f"P95={_pctile(nums,0.95)} P99={p99} max={mx}\n"
        f"推荐起点(策略可调): 爆≈{rec_bao}(P99) 大爆≈{rec_dabao}(max)。"
        f"注意阈值只是【兜底】(人工 tier 缺失时用),tier_source='数值推断' 的行不进飞轮。"
    )


# ── 4. 自查草稿 ──────────────────────────────────────────────────────────
@tool(
    "validate_mapping_yaml",
    "校验 mapping 草稿:受控词表合规 + D-021 列覆盖(传 columns 才检)。定稿前自查,errors 必须为 0。",
    {"mapping_yaml": str, "columns": list},
)
async def validate_mapping_yaml(args: dict[str, Any]) -> dict[str, Any]:
    try:
        mp = yaml.safe_load(args.get("mapping_yaml") or "")
    except yaml.YAMLError as exc:
        return _text(f"yaml 解析失败: {exc}", is_error=True)
    res = vocab.validate_mapping(mp, columns=args.get("columns"))
    return _text(
        "errors: " + json.dumps(res["errors"], ensure_ascii=False)
        + "\npending([待确认], 草稿合法): " + json.dumps(res["pending"], ensure_ascii=False)
        + "\nuncovered_columns(D-021): " + json.dumps(res["uncovered_columns"], ensure_ascii=False)
    )


# ── 5. 产出(唯一的写)────────────────────────────────────────────────────
@tool(
    "emit_draft",
    "产出最终 draft mapping.yaml + review brief。写盘前再校验一次:词表 error 或 D-021 未覆盖列 → 拒绝,让你改。",
    {"project_id": str, "mapping_yaml": str, "review_brief": str, "columns": list},
)
async def emit_draft(args: dict[str, Any]) -> dict[str, Any]:
    pid = args.get("project_id")
    if not pid:
        return _text("project_id 必填", is_error=True)
    try:
        mp = yaml.safe_load(args.get("mapping_yaml") or "")
    except yaml.YAMLError as exc:
        return _text(f"yaml 解析失败: {exc}", is_error=True)

    res = vocab.validate_mapping(mp, columns=args.get("columns"))
    if res["errors"] or res["uncovered_columns"]:
        return _text(
            "拒绝写盘 —— 先修复:\n"
            "词表 errors: " + json.dumps(res["errors"], ensure_ascii=False)
            + "\n未覆盖列(D-021): " + json.dumps(res["uncovered_columns"], ensure_ascii=False),
            is_error=True,
        )

    out_dir = Path(os.environ.get("ONBOARDER_OUT_DIR", "mappings"))
    out_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = out_dir / f"{pid}.yaml"
    brief_path = out_dir / f"{pid}.brief.md"
    yaml_path.write_text(args["mapping_yaml"], encoding="utf-8")
    brief_path.write_text(args.get("review_brief") or "", encoding="utf-8")
    return _text(
        f"已写: {yaml_path} + {brief_path}。"
        f"待确认项 {len(res['pending'])} 个(交策略 lead 拍板): "
        + json.dumps(res["pending"], ensure_ascii=False)
    )


ALL_TOOLS = [
    pull_feishu_table,
    list_field_options,
    distinct_values,
    read_mapping_corpus,
    recommend_thresholds,
    validate_mapping_yaml,
    emit_draft,
]
