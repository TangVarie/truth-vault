"""deskcore — 写作台内核 (D-041)。

autowriter 的 Streamlit 界面停用后, 把它值钱的四个机制(分层硬约束 / 调校笔记
自动萃取 / 正负例池 / 语义查重)做成 MCP 工具, 挂到 WorkBuddy / Claude Code /
CodeBuddy。数据仍在同一个 Supabase 的 autowriter schema, 一行不迁。

设计见 docs/27-deskcore-mcp.md。
"""
