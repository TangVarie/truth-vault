"""onboarder/corpus.py — 历史 mappings + 家族指纹 → agent 的 few-shot 上下文。

这是接表 agent 相对"手搓聊天会话"的核心增量:把【全部已完成 mappings/*.yaml】
+ 家族指纹 + 受控词表常驻喂给 agent,让它【对着积累的决策做模式匹配 + 跨表对齐】,
而不是每次从零推(docs/16 §相对手搓的两个增量)。
"""

from __future__ import annotations

import os
from pathlib import Path

from . import vocab

# 家族指纹(docs/04 §Step 1 快速规则 / docs/03 §三个 schema 家族)
FAMILY_FINGERPRINTS = """\
schema 家族判定(看飞书列名指纹):
- 家族 A:有「巡查状态」「最近检查时间」「主页链接」「数据回收情况」;字段用"数"(曝光数/阅读数/互动数)。
- 家族 B:无 A 标志,但有「关键词」「蓝词记录」「项目阶段」「父记录 2/3/4」;字段用"量"(曝光量/阅读量/互动量);通常缺「粉丝数」。
- 家族 C:无「方向」、无数据回收字段、大量日期化结算列;tier 藏在「备注」字段。
⚠️ 真正的新模式(如 WTG 的"状态拆两列:笔记状态+流量状态"、多出「观众分析」列)→ 标成 schema 演化让人定,不要硬糊进已知家族。"""

# docs/03 标准字段映射表(飞书常见列名 → 标准字段)。看到这些列就映成对应 typed 列/中间变量,
# 别一股脑塞 raw_extra —— 否则丢掉结构化处理(典型坑:爆帖置顶评论该是 pinned_comment)。
STANDARD_FIELD_MAP = """\
标准字段映射(docs/03;看到这些列名就映成右边的 typed 列/中间变量,**别塞 raw_extra**):
- 素人编号 → account_id
- 发布时间 → publish_time
- 反馈链接 → publish_url
- 文案 → raw_content(sync 再解析 title/body/hashtags)
- 曝光数/曝光量 → impressions;阅读数/阅读量 → reads;互动数/互动量 → interactions
- 状态/流量状态 → _status_raw(A/B 家族 tier 源,tier_extraction.source 填"状态字段")
- 备注 → _note_for_tier(C 家族 tier 源,source 填"备注字段")
- 方向 → _direction_raw(走 direction_decomposition)
- 发布笔记 → _intent_raw(走 intent_mapping;**没有这列就别写 intent_mapping**)
- 关键词 → target_blue_keywords(投放前定的目标蓝词)
- 蓝词记录/蓝词字段 → hit_blue_keywords(事后回收的命中蓝词)
- 爆帖置顶评论 → pinned_comment
- 随贴评论 → _comment_text(进 comments 表);随贴评论素人 → _comment_text_persona
- 数据回收情况 → data_quality_status
- 观众分析 → _audience_raw(sync 解析进 actual_audience_data,半结构化受众数据;见 NUC/WTG)
- 帐号昵称 → _account_name;粉丝数 → _account_followers;主页链接 → _account_url(暂进 raw_extra)
其余"保留但不处理"的列(图片/附件/巡查/副本/截图/合作码/父记录…)才进 project_specific_fields_to_raw_extra。"""


def _mappings_dir() -> Path:
    # 允许 env 覆盖(测试用);默认 repo 根的 mappings/
    env = os.environ.get("ONBOARDER_MAPPINGS_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "mappings"


def load_existing_mappings(exclude: str | None = None) -> dict[str, str]:
    """读 mappings/*.yaml 原文(不含 _template)。exclude=project_id 时剔除该张
    (eval 重跑某表时,把它本身排除出语料,避免"抄答案")。"""
    out: dict[str, str] = {}
    d = _mappings_dir()
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.yaml")):
        if p.stem.startswith("_"):
            continue
        if exclude and p.stem == exclude:
            continue
        out[p.stem] = p.read_text(encoding="utf-8")
    return out


def build_corpus_context(exclude: str | None = None) -> str:
    """拼成一段喂给 agent 的语料(受控词表 + 家族指纹 + 历史 mapping 全文)。"""
    parts = [
        "═══ 受控词表(闭集,起草时只能从中取值)═══\n" + vocab.vocab_reference(),
        "═══ schema 家族指纹 ═══\n" + FAMILY_FINGERPRINTS,
        "═══ 标准字段映射(优先按此映 typed 列)═══\n" + STANDARD_FIELD_MAP,
    ]
    existing = load_existing_mappings(exclude=exclude)
    if existing:
        block = ["═══ 已完成的历史 mapping(先例;跨表对齐 + 复用拆解的依据)═══"]
        for name, text in existing.items():
            block.append(f"\n──── mappings/{name}.yaml ────\n{text}")
        parts.append("\n".join(block))
    else:
        parts.append("═══ 历史 mapping ═══\n(空 —— 这是第一张表)")
    return "\n\n".join(parts)
