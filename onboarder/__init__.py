"""onboarder/ · 接表助手 —— 飞书表 → mapping.yaml 草稿。

见 docs/16-onboarding-agent.md。做"梳理 + 闭集抽取 + 起草",判断权
(方向拆解 / tier 阈值 / 合规)留给策略 lead(README 原则 1)。

架构:确定性取数 + 单次 Anthropic 调用(librarian 同款,走中转站非流式),
不再用 agent-sdk / claude CLI。布局:
    vocab.py    受控词表闭集 + 校验器(硬护栏)
    clients.py  飞书(REST) + Supabase + Anthropic(中转站单次调用)客户端
    corpus.py   历史 mappings + 家族指纹 → 起草用 few-shot 上下文
    core.py     编排:拉字段/选项/全表 distinct/样本 + 一次调用 → 草稿 + 校验 + 写盘
    cli.py      命令行入口
    eval_wtg.py WTG 结构回归 eval
"""

__all__ = ["vocab", "clients", "corpus", "core"]
