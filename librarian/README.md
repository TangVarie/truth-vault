# librarian/ · 飞轮 LLM 馆员服务

pull 模型(D-038 / [docs/14](../docs/14-channel2-pull-librarian.md))的**借阅端**:aw / ssll
写稿时按 brief 向馆员借阅匹配的"经验卡"。

```
librarian/
├── clients.py   自包含 Supabase(service_role) / Anthropic 客户端 (便于独立部署 Railway)
├── core.py      选取核心: 取候选 + 缓存 + LLM 按 brief 推理选 3-5 张 + 降级
├── cli.py       命令行测试器 (--dry-run 看 prompt; 真跑连库 + LLM)
├── sample_brief.json   示例 brief
└── app.py       (后续) FastAPI 端点, aw/ssll 调它; + Railway 部署配置
```

## 流程 (core.librarian_select)

1. 取候选(`v_flywheel_lesson_cards`, 按 rank_score, 上限 50)。**空库 → 返回 `[]`**(消费方降级到自有正例)。
2. 算 `library_version` = f(候选数, max(curated_at)) → 算 `cache_key`。
3. **命中缓存 → 直接返回**(跳过 LLM)。
4. 未命中 → LLM 按 brief 推理选 3-5 张 → 校验 id 在候选内 → 富集卡内容 → 写缓存。
   **LLM 失败 → 返回 `[]`**(绝不阻塞写稿; 飞轮是增强项)。

## 本地测试

```bash
# 前置: schemas/notes_v1_4 + notes_v1_5 已 apply 到目标库
export SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=...   # service_role
# 只看 prompt + cache_key (不调 LLM):
python -m librarian.cli --brief librarian/sample_brief.json --dry-run
# 真跑 (需 ANTHROPIC_API_KEY):
export ANTHROPIC_API_KEY=...
python -m librarian.cli --brief librarian/sample_brief.json
```

> 当前书架为空(0 真·非 synthetic 爆款), 所以真跑会返回 `[]`、dry-run 会显示
> `candidate_count: 0`。等飞书出现真爆款/参考(非 synthetic)、经策展 pass 入库后才有料。

## 与"策展员"的区别

- **策展员**(`prompts/flywheel_curator.md` + `scripts/curate_flywheel_lessons.py`):入库时把**单条**爆款提炼成一张经验卡。
- **馆员**(`prompts/flywheel_librarian.md` + 本目录):写稿时从**多张**卡里**按 brief 推理选取**。

## 待办

- `app.py`:FastAPI 端点(`POST /librarian` 收 brief、回 selected)+ Railway 部署配置(`requirements.txt` / Procfile)。
- 接入消费方:autowriter([R-032](../docs/10-sister-repo-followups.md#r-032))、sanshengliubu([R-033](../docs/10-sister-repo-followups.md#r-033))。
