# librarian/ · 飞轮 LLM 馆员服务

pull 模型(D-038 / [docs/14](../docs/14-channel2-pull-librarian.md))的**借阅端**:aw / ssll
写稿时按 brief 向馆员借阅匹配的"经验卡"。

```
librarian/
├── clients.py   自包含 Supabase(service_role) / Anthropic 客户端 (便于独立部署 Railway)
├── core.py      选取核心: 取候选 + 缓存 + LLM 按 brief 推理选 3-5 张 + 降级
├── cli.py       命令行测试器 (--dry-run 看 prompt; 真跑连库 + LLM)
├── sample_brief.json   示例 brief
├── app.py       FastAPI 端点 (POST /librarian, GET /health), aw/ssll 调它
└── requirements.txt  服务依赖 (fastapi/uvicorn/supabase/anthropic)
```
> Railway 部署配置在 **repo 根 `railway.json`**(root 设 repo 根, 让 `librarian` 包可导入)。

## 流程 (core.librarian_select)

1. 取候选(`v_flywheel_lesson_cards`, 按 rank_score, 上限 50)。**空库 → 返回 `[]`**(消费方降级到自有正例)。
2. 算 `library_version` = f(候选数, max(curated_at)) → 算 `cache_key`。
3. **命中缓存 → 直接返回**(跳过 LLM)。
4. 未命中 → LLM 按 brief 推理选 3-5 张 → 校验 id 在候选内 → 富集卡内容 → 写缓存。
   **LLM 失败 → 返回 `[]`**(绝不阻塞写稿; 飞轮是增强项)。

**两层省钱(应用 autowriter 同款策略)**:
- **结果缓存**(上面 step 3, `flywheel_librarian_cache`):挡"完全相同的请求"(同 brief + 同 library_version),直接复用上次精选、**整次跳过 LLM**。
- **Anthropic prompt caching**(`cache_control: ephemeral`):候选卡库 + 项目 system_prompt 作为缓存 system 块,挡"同库不同 brief"的请求 —— 只重算 delta 部分,大前缀缓存命中省 ~90%。
- LLM 调用支持**中转站**(`ANTHROPIC_BASE_URL`,同 autowriter `clients.get_anthropic_client` 约定);重试覆盖 429/502/503/529(中转站常见 overloaded)。

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

> 当前书架有 **1 张卡**:WTG 那条「参考」(`WTG_phase1_recvk9VPCTNG1b`)。它 synthetic=true
> 但 tier=参考 → 放行(synthetic 只挡爆/大爆;参考是人工内容判断、与指标真假无关,Session #15;
> 卡带 `synthetic` 标记,馆员 `_render_cards` 会提示"指标未验证")。`is_curated=false`,馆员用
> essence + excerpt 兜底,下次策展 pass 补 hook/structure 等 4 字段。真·爆款进库后书架扩充。

## 与"策展员"的区别

- **策展员**(`prompts/flywheel_curator.md` + `scripts/curate_flywheel_lessons.py`):入库时把**单条**爆款提炼成一张经验卡。
- **馆员**(`prompts/flywheel_librarian.md` + 本目录):写稿时从**多张**卡里**按 brief 推理选取**。

## 部署 (Railway)

repo 根 `railway.json` 已配好;在 Railway 建一个 service、root 指 repo 根、设环境变量
(`SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` / `ANTHROPIC_API_KEY` / **`ANTHROPIC_BASE_URL`**
(中转站/第三方网关, 可选, 不设走官方) / `FLYWHEEL_LIBRARIAN_MODEL`(见下方⚠️) / 建议设
`LIBRARIAN_API_KEY` 鉴权)即可。healthcheck 走 `/health`。

> ⚠️ **模型 env 名各服务不同(2026-06-04 踩过的坑)**:馆员读 **`FLYWHEEL_LIBRARIAN_MODEL`**(默认
> `claude-sonnet-4-6`),而 worker 读 `ESSENCE_MODEL`、autowriter 读 `CLAUDE_MODEL` —— **三个名字都不一样**。
> 如果你的中转站通道**不 serve 默认的 `claude-sonnet-4-6`**,却只给 worker/aw 设了能跑通的模型、忘了给馆员
> 设 `FLYWHEEL_LIBRARIAN_MODEL`,馆员每次调用都会失败、**降级成 `{"selected":[]}`**(且 `flywheel_librarian_cache`
> 一直 0,从外面 200 看不出错)。**换通道模型时,三个服务的模型 env 都要设成通道认的那个名字。**

调用(消费方):
```
POST /librarian   header: X-Librarian-Key: <key>   body: <brief JSON>
→ {"selected": [ {source_note_id, why_relevant, borrow_what, hook_type, structure, excerpt, ...}, ... ]}
```

## 待办

- 前置:`schemas/notes_v1_4` + `notes_v1_5` apply 到 prod(否则视图/表不存在)。
- 接入消费方:autowriter([R-032](../docs/10-sister-repo-followups.md#r-032))、sanshengliubu([R-033](../docs/10-sister-repo-followups.md#r-033))——写稿前调本服务、把 selected 注入 prompt。
