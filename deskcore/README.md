# deskcore · 写作台内核

autowriter 内容工作台的能力内核，做成 MCP 工具服务。**Streamlit 界面停用，积累不迁。**

完整设计与接入说明见 [`docs/27-deskcore-mcp.md`](../docs/27-deskcore-mcp.md)，决策见 DECISIONS `D-041`。

## 它解决什么

| 症状 | 机制 |
|---|---|
| WorkBuddy 老忘记之前定的规则 | `open_project` 每次生成前重新注入 P0 硬约束层，不依赖对话记忆 |
| 写出来像 AI 不像本人 | `record_edit` 收手动精修 diff（最高权重信号），蒸馏成个人调校笔记 |
| 跨批次越写越像 | `draw_angles` 发牌台账 + `check_drafts` 全量成稿指纹硬闸 |
| 一个项目 5 个提示词要点 5 次 | `open_project` 一次拿全 |

## 文件

```
deskcore/
├── app.py       FastAPI + MCP(streamable HTTP) + REST 兜底 + /health 配置回显
├── core.py      纯函数层(不依赖 FastAPI/MCP) —— 简报/发牌/查重/学习
├── tools.py     10 个 MCP 工具, docstring 是给模型看的
├── vocab.py     受控词表闭集(权威源 docs/05), 发牌用
├── clients.py   Supabase / Gemini embedding / librarian 转调 / Anthropic
├── identity.py  API key → user_id, 「个人风格私有」的前提
└── cli.py       本地 adapter, 含不连库的 selftest
```

与 `librarian/` / `onboarder/` / `worker/` 同一套模板：core 纯函数 + 多个 adapter
（CLI / HTTP / MCP）+ `X-*-Key` 鉴权 + `railway.json`。

## 快速自测

```bash
python -m deskcore.cli selftest        # 不连库不联网, 验查重与发牌逻辑
python -m deskcore.cli projects        # 需要 SUPABASE_URL / SERVICE_ROLE_KEY
python -m deskcore.cli draw --project <uuid> -n 20 --block
```

服务起来后 `GET /health` 会回显每个依赖的可用性（模型名 / embedding / librarian /
鉴权），**配错当场可见** —— 这是刻意的，docs/19:180-200 记过一次配错 env 导致
静默降级、查了很久的事故。

## 两条必须知道的纪律

**`check_drafts` 不 fail-open。** 其它读类工具出错返回带 `error` 的可用结构不阻塞
写稿；查重出错必须抛。静默放行就是重演 autowriter 那个 `ENABLE_DEDUP_REGEN` 默认
关着、查重跑了但不拦的老问题。

**`user_id` 用库里已有的 UUID，不要新造。** `autowriter-migrations/RUNBOOK.md:150-153`
记过：写 service account UUID 导致 RLS 屏蔽、`list_example_items` 永远 0 行、
飞轮静默断开。
