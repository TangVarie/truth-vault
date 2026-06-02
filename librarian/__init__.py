"""飞轮 LLM 馆员服务 (pull / 图书馆模型的借阅端, D-038 / docs/14)。

aw / ssll 写稿时按 brief 向馆员借阅匹配的"经验卡"。本包:
    clients.py  — 自包含的 Supabase / Anthropic 客户端 (便于独立部署 Railway)
    core.py     — 选取核心: 取候选 + 缓存 + LLM 按 brief 推理选取 + 降级
    cli.py      — 命令行测试器 (--dry-run 看 prompt; 真跑连库 + LLM)
    app.py      — (后续) FastAPI 端点, aw/ssll 调它

前置库对象 (schemas/): v_flywheel_lesson_cards (v1.4) + flywheel_librarian_cache (v1.5)。
"""
