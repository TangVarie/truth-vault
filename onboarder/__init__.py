"""onboarder/ · 接表 agent —— 飞书表 → mapping.yaml 自动起草。

见 docs/16-onboarding-agent.md。agent 干"梳理 + 闭集抽取 + 起草",判断权
(方向拆解 / tier 阈值 / 合规)留给策略 lead(README 原则 1)。

布局(镜像 librarian/ 的自包含风格):
    vocab.py    受控词表闭集 + 校验器(硬护栏)
    clients.py  飞书(REST,镜像 scripts 的 FeishuClient)+ Supabase 客户端
    corpus.py   历史 mappings + 家族指纹 → agent few-shot 上下文
    tools.py    claude-agent-sdk 的 in-process 工具(拉表/读语料/推荐阈值/校验/产出)
    core.py     agent 编排(ClaudeAgentOptions + PreToolUse 护栏 + 跑 query)
    cli.py      命令行入口
    eval_wtg.py WTG 金标准回归 eval
"""

__all__ = ["vocab", "clients", "corpus", "tools", "core"]
