"""onboarder/core.py — 接表 agent 编排(claude-agent-sdk)。

构造 ClaudeAgentOptions(in-process MCP 工具 + PreToolUse 护栏 + 预算/turn 上限 +
hermetic CI),跑一次 query() 起草一张表的 mapping。

额度:走中转站 —— CLI 读环境变量 ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN
(或 ANTHROPIC_API_KEY),与 librarian 同一约定、同一个池子。**不**用订阅额度。
"""

from __future__ import annotations

import os
from typing import Any, Optional

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
    query,
)

from . import tools, vocab

DEFAULT_MODEL = os.environ.get("ONBOARDER_MODEL", "claude-sonnet-4-6")

# agent 只能用这 5 个 onboarder 工具(SDK MCP 命名:mcp__<server>__<tool>)
ALLOWED_TOOLS = [f"mcp__onboarder__{t.name}" for t in tools.ALL_TOOLS]

SYSTEM_PROMPT = f"""\
你是 Truth Vault 的【接表管家】。任务:把一张飞书投放表【起草】成一份
mappings/<project_id>.yaml(对齐现有 mapping 的结构),供策略 lead 审。

宪法(README 原则 1「管家不做判断」):你只做【梳理 + 闭集抽取 + 起草】。
判断权属于策略 lead —— 以下三类【永远只出草稿、标 [待确认]】,绝不替人拍死:
  · direction_decomposition(方向拆解)
  · tier_thresholds(数值阈值)
  · compliance(合规红线 / 蓝词策略)
另外 brand 中文名 / product / category 拿不准也标 [待确认]。

分工(对着 docs/04 的 7 步 SOP):
  1 元数据   : 按字段指纹判 schema_family;从数据填 project_id/平台/起止日期
  2 字段映射 : 按家族标准表自动配;**飞书每一列都要交代**(typed 列 / 中间变量 /
              raw_extra allowlist),一条不漏 —— 漏了的列会进 D-021 quarantine
  3 方向拆解⭐: 枚举所有「方向」取值,按方向名+文案样本【起草】content_format/
              target_audience/user_pain_point,全部标 [待确认]
  4 tier 抽取: A/B 套标准规则;C 家族从「备注」起草规则
  5 阈值     : 调 recommend_thresholds,按分布给推荐(标 [待确认])
  6 合规     : 按 category 提模板 + 扫候选蓝词(标 [待确认])
  7 产出     : 自查通过后 emit_draft

受控词表(闭集,只能从中取值;编造会被 emit_draft 拒绝):
{vocab.vocab_reference()}

工作步骤(严格按序):
  1) 先调 read_mapping_corpus(exclude_project_id=<本表>)读词表+家族指纹+历史 mapping,
     做跨表对齐、尽量复用已有方向拆解的写法。
  2) 调 pull_feishu_table 拿列 + 样本行。
  3) 起草整份 yaml(结构对齐 mappings/WTG_phase1.yaml;判断项标 [待确认])。
  4) 用样本里的互动量调 recommend_thresholds。
  5) 调 validate_mapping_yaml(传 columns=飞书全部列名)自查,直到 errors=0 且
     uncovered_columns=[]。
  6) 调 emit_draft 产出 yaml + review brief。

review brief(emit_draft 的 review_brief 参数)只列【要策略 lead 拍板的项】,
每项给:你的草稿 + 理由 + 在别的表里的先例。别复述整份 yaml。
"""

TASK_TEMPLATE = """\
请接入这张飞书表并起草 mapping:
  project_id      = {project_id}
  feishu_app_token = {app_token}
  feishu_table_id  = {table_id}
  sample_n         = {sample_n}
按系统提示的步骤,最后用 emit_draft 产出。完成后用一句话汇报写到哪、还剩几个 [待确认]。
"""


async def _guard_tools(input_data: dict, tool_use_id: Optional[str], context: Any) -> dict:
    """PreToolUse 硬护栏:只放行 onboarder 自己的工具(挡掉任何内建 Bash/Write/Edit 等)。"""
    name = input_data.get("tool_name", "")
    if name in ALLOWED_TOOLS or name.startswith("mcp__onboarder__"):
        return {}
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"接表 agent 只能用 onboarder 工具,拒绝 {name}",
        }
    }


def build_options(model: str, max_turns: int, budget_usd: float, cwd: str) -> ClaudeAgentOptions:
    server = create_sdk_mcp_server("onboarder", "1.0.0", tools=tools.ALL_TOOLS)
    return ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        model=model,
        mcp_servers={"onboarder": server},
        allowed_tools=ALLOWED_TOOLS,
        hooks={"PreToolUse": [HookMatcher(hooks=[_guard_tools])]},
        permission_mode="bypassPermissions",   # headless;放行靠 allowed_tools + 护栏
        max_turns=max_turns,
        max_budget_usd=budget_usd,              # 成本硬上限
        setting_sources=[],                     # hermetic:不读本机 ~/.claude
        cwd=cwd,
    )


async def run_onboarding(
    *,
    project_id: str,
    app_token: str,
    table_id: str,
    sample_n: int = 30,
    model: str = DEFAULT_MODEL,
    max_turns: int = 40,
    budget_usd: float = 2.0,
    out_dir: str = "mappings",
    cwd: Optional[str] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """跑一次接表。dry_run=True 只打印 system prompt + 任务 + 工具,不调 LLM。"""
    os.environ["ONBOARDER_OUT_DIR"] = out_dir
    cwd = cwd or os.getcwd()
    task = TASK_TEMPLATE.format(
        project_id=project_id, app_token=app_token, table_id=table_id, sample_n=sample_n
    )

    if dry_run:
        print("=== SYSTEM PROMPT ===\n" + SYSTEM_PROMPT)
        print("=== ALLOWED TOOLS ===\n" + "\n".join(ALLOWED_TOOLS))
        print("=== TASK ===\n" + task)
        return {"dry_run": True}

    options = build_options(model, max_turns, budget_usd, cwd)
    final: dict[str, Any] = {"result": None, "cost_usd": None, "is_error": None, "tool_calls": []}

    async for message in query(prompt=task, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    print("· claude:", block.text.strip()[:400])
                elif isinstance(block, ToolUseBlock):
                    final["tool_calls"].append(block.name)
                    print(f"  → tool: {block.name}")
        elif isinstance(message, ResultMessage):
            final["result"] = getattr(message, "result", None)
            final["cost_usd"] = getattr(message, "total_cost_usd", None)
            final["is_error"] = getattr(message, "is_error", None)

    print(
        f"\n=== done === cost≈${final['cost_usd']} "
        f"tools={final['tool_calls']} is_error={final['is_error']}"
    )
    if final["result"]:
        print("result:", final["result"])
    return final
