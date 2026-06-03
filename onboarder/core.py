"""onboarder/core.py — 接表起草核心(确定性取数 + 单次 Anthropic 调用)。

改版说明:原先用 claude-agent-sdk 的 agent 循环 + 进程内 MCP 工具,实测那条
"CLI + 流式 + 进程内 MCP"的路太脆(网关连不上、工具不暴露)。本任务本质是
"确定性取数 → 一次推理出草稿",和 librarian 一样,故改成 librarian 同款【单次
非流式 Anthropic 调用】(已验证能透传中转站)。

流程(全确定性,除了第 3 步一次 LLM):
  1. 飞书:list_fields(权威列名 + 单选/多选【完整选项】)+ N 行文案样本 +
     全表 distinct(枚举型列取【全集】,不靠样本 —— 稀有方向不漏)
  2. corpus:历史 mapping + 家族指纹 + 词表(跨表对齐)
  3. 拼一次 prompt → call_anthropic → {mapping_yaml, review_brief}
  4. 词表 + D-021 校验 → 写盘
判断项(方向/阈值/合规)一律标 [待确认];人审 PR 才进库(原则 1)。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

from . import clients, corpus, vocab

DEFAULT_MODEL = os.environ.get("ONBOARDER_MODEL", "claude-sonnet-4-6")
DISTINCT_CAP = 40   # 不同值超过这个数的列视为自由文本,只报数量不铺开(控 prompt 体积)

SYSTEM_PROMPT = f"""你是 Truth Vault 的接表管家。把一张飞书投放表【起草】成一份
mappings/<project_id>.yaml(结构对齐现有 mapping,尤其 mappings/WTG_phase1.yaml),
供策略 lead 审。

宪法(README 原则 1「管家不做判断」):只做【梳理 + 闭集抽取 + 起草】。判断权属于
策略 lead —— 以下【永远只出草稿、标 [待确认]】,绝不替人拍死:
  · direction_decomposition(方向拆解)· tier_thresholds(阈值)· compliance(合规)
  · brand 中文名 / product / category 拿不准也标 [待确认]

分工(对着 docs/04 的 7 步 SOP):
  1 元数据  : 按字段指纹判 schema_family(A:有巡查状态/最近检查时间/主页链接;
             B:有关键词/蓝词记录/项目阶段、缺粉丝数;C:无方向、无数据回收、日期化结算列)
  2 字段映射: 飞书【每一列】都要交代 —— typed 列 / 下划线中间变量 / raw_extra allowlist,
             一条不漏(漏的列会进 D-021 quarantine)
  3 方向拆解: 用【字段选项 / 全表 distinct 的完整取值集】枚举所有「方向」(不是样本!),
             逐个起草 content_format/target_audience/user_pain_point,全标 [待确认]
  4 tier    : A/B 套标准状态规则;C 家族从「备注」起草规则
  5 阈值    : 看互动量分布给推荐,标 [待确认]
  6 合规    : 按 category 提模板 + 扫候选蓝词,标 [待确认]

受控词表(闭集,只能从中取值,编造会被校验拒绝):
{vocab.vocab_reference()}

输出两段,用下面两行分隔标记隔开;**不要用 ``` 代码块包裹,也不要输出 JSON**:
===MAPPING_YAML===
(完整 mapping.yaml 文本,结构对齐 mappings/WTG_phase1.yaml;所有判断项写成 [待确认])
===REVIEW_BRIEF===
(给策略 lead 的 review brief,markdown:只列要拍板的项,每项带草稿 + 理由 + 在别的表里的先例;别复述整份 yaml)"""


def _render_fields(fields: list[dict]) -> str:
    if not fields:
        return "(list_fields 不可用 —— 只能依据下面样本里出现过的列;注意空列可能漏)"
    out = []
    for f in fields:
        opts = f.get("options") or []
        tail = f"  选项({len(opts)}): {opts}" if opts else ""
        out.append(f"- {f.get('field_name')} (type={f.get('type')}){tail}")
    return "\n".join(out)


def _render_distinct(distinct: dict, cap: int = DISTINCT_CAP) -> str:
    out = []
    for col, items in distinct.get("distinct", {}).items():
        if len(items) > cap:
            out.append(f"[{col}] {len(items)} 个不同值(高基数,疑似自由文本,略)")
        else:
            vals = ", ".join(f"{v}×{c}" for v, c in items)
            out.append(f"[{col}] {len(items)} 个: {vals}")
    return "\n".join(out) or "(无)"


def _render_samples(rows: list[dict], k: int = 8) -> str:
    return json.dumps([r.get("fields", {}) for r in rows[:k]], ensure_ascii=False, indent=2)


def build_user_message(project_id: str, fields: list, sample: dict, distinct: dict) -> str:
    return "\n\n".join([
        corpus.build_corpus_context(exclude=project_id),
        f"═══ 本次要接的表 ═══\nproject_id: {project_id}\n拉到 {sample.get('n')} 行样本。",
        "── 字段清单(权威列名 + 单选/多选的完整选项)──\n" + _render_fields(fields),
        "── 全表 distinct(枚举型列的取值【全集】;高基数列只报数量)──\n" + _render_distinct(distinct),
        "── 文案样本(看风格,不用于枚举)──\n" + _render_samples(sample.get("rows", [])),
        f"据此起草 mappings/{project_id}.yaml + review brief,按系统提示的两段分隔格式输出。",
    ])


def _strip_fence(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else ""
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()


def _split_output(raw: str) -> tuple[str, str]:
    """从模型输出切出 (mapping_yaml, review_brief)。

    首选 ===MAPPING_YAML=== / ===REVIEW_BRIEF=== 分隔;兼容旧 JSON;再不行整段当 yaml。
    """
    M, B = "===MAPPING_YAML===", "===REVIEW_BRIEF==="
    if M in raw and B in raw:
        after = raw.split(M, 1)[1]
        y, b = after.split(B, 1)
        return _strip_fence(y), _strip_fence(b)
    parsed = clients.parse_json(raw)
    if isinstance(parsed, dict) and "mapping_yaml" in parsed:
        return parsed["mapping_yaml"], parsed.get("review_brief", "")
    return _strip_fence(raw), ""


def run_onboarding(
    *,
    project_id: str,
    app_token: str,
    table_id: str,
    sample_n: int = 30,
    model: str = DEFAULT_MODEL,
    out_dir: str = "mappings",
    dry_run: bool = False,
) -> dict[str, Any]:
    """跑一次接表起草。dry_run=True 只拼 prompt 不调 LLM(也不连飞书)。"""
    # ── 1. 确定性取数 ──
    if dry_run:
        fields, sample, distinct = [], {"columns": [], "rows": [], "n": 0}, {"distinct": {}}
    else:
        try:
            fields = clients.list_fields(app_token, table_id)
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ list_fields 失败(飞书 bot 权限?): {exc}")
            fields = []
        sample = clients.pull_columns_and_samples(app_token, table_id, sample_n)
        all_cols = [f["field_name"] for f in fields] or sample["columns"]
        print(f"· 拉到 {len(all_cols)} 列、{sample['n']} 行样本;全表 distinct 扫描中…")
        distinct = clients.distinct_values(app_token, table_id, all_cols)
        print(f"· distinct 扫描了 {distinct['scanned']} 行")

    user = build_user_message(project_id, fields, sample, distinct)

    if dry_run:
        print("=== SYSTEM PROMPT ===\n" + SYSTEM_PROMPT)
        print("\n=== USER (corpus 已省, 仅结构) ===\n" + user[-1500:])
        return {"dry_run": True}

    # ── 3. 一次 LLM 调用 ──
    print(f"· 调 {model}(单次,走中转站)起草中…")
    raw = clients.call_anthropic(user, model, system=SYSTEM_PROMPT, max_tokens=16000)
    mapping_text, brief = _split_output(raw)
    if not mapping_text.strip():
        print("❌ 没解析出 mapping_yaml。原始响应前 1200 字:\n" + (raw or "")[:1200])
        return {"is_error": True}

    # ── 4. 校验 + 写盘 ──
    all_cols = [f["field_name"] for f in fields] or sample.get("columns")
    try:
        mp = yaml.safe_load(mapping_text)
    except yaml.YAMLError as exc:
        print(f"❌ 产出的 yaml 解析失败: {exc}")
        mp = None
    res = (vocab.validate_mapping(mp, columns=all_cols) if isinstance(mp, dict)
           else {"errors": ["yaml 解析失败"], "pending": [], "uncovered_columns": []})

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    yaml_path = out / f"{project_id}.yaml"
    brief_path = out / f"{project_id}.brief.md"
    yaml_path.write_text(mapping_text, encoding="utf-8")
    brief_path.write_text(brief, encoding="utf-8")

    print(f"\n=== 写出 {yaml_path} + {brief_path} ===")
    print("词表 errors:", res["errors"] or "无")
    print("未覆盖列(D-021):", res["uncovered_columns"] or "无")
    print(f"待确认项 {len(res['pending'])} 个(交策略 lead 拍板)")
    return {
        "yaml": str(yaml_path), "brief": str(brief_path),
        "errors": res["errors"], "uncovered": res["uncovered_columns"],
        "pending": res["pending"],
        "is_error": bool(res["errors"] or res["uncovered_columns"]),
    }
