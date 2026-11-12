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

1. 取【整架】(`v_flywheel_lesson_cards`, 按 rank_score, 上限 1000; 10-08 实查 306 张)。**空库 → 返回 `[]`**(消费方降级到自有正例)。
2. 算 `library_version` = f(整架候选数, max(curated_at), 月份桶, id 集合摘要[, gate2_run]) → 算 `cache_key`。
3. **同一个 `cache_key` 已经有一次在选 → 等它,拿同一份结果**(AU-F09 在飞合并;进程内,最多等 75 秒,等不到就自己选)。
   **命中缓存 → 直接返回**(跳过 LLM)。
4. 未命中 → **预筛 `shortlist()`(D-088)**: 按 brief 的项目级字段打贴题分(同品牌 +3 · 同品类 +2 · 人群词 +1)挑 ≤24 张,
   rank 全局前 8 张无条件保留(跨主题迁移要有料); 只看项目级字段、不看本次 delta(同项目内候选块稳定, prompt cache 才命中)
   → LLM 按 brief 推理选 3-5 张(两句批注各 ≤30 字, `max_tokens` 封顶 1000)→ 校验 id 在候选内、同一张卡只留一遍(F14a)→ 富集卡内容 → 写缓存。
   **LLM 失败 → 返回 `[]`**(绝不阻塞写稿; 飞轮是增强项)。

> 为什么要预筛(D-088): 之前 fetch 前 50 张按 rank 硬切整批喂 LLM —— 品牌自己的卡常常不在前 50 里;
> 冷路径 24 个样本 p50 49s / p95 79s, 7 次超过写作台 60s 的等待, 耗时大头是模型【写】的那几百 token 走中转站
> (选 0 张的两次只用 3s / 11s)。所以卡给得更贴、字写得更少。守卫: `scripts/check_librarian_shortlist.py`。

**两层省钱(应用 autowriter 同款策略)**:
- **结果缓存**(上面 step 3, `flywheel_librarian_cache`):挡"完全相同的请求"(同 brief + 同 library_version),直接复用上次精选、**整次跳过 LLM**。
- **Anthropic prompt caching**(`cache_control: ephemeral`):候选卡库 + 项目 system_prompt 作为缓存 system 块,挡"同库不同 brief"的请求 —— 只重算 delta 部分,大前缀缓存命中省 ~90%。
- LLM 调用支持**中转站**(`ANTHROPIC_BASE_URL`,同 autowriter `clients.get_anthropic_client` 约定);重试覆盖 429/502/503/529(中转站常见 overloaded)。
- **备用中转站**(可选, D-148):`ANTHROPIC_BASE_URL_BACKUP` + `ANTHROPIC_API_KEY_BACKUP` 都配了才启用。每次尝试先打主站
  (只给一次机会、限时 22 秒, `RELAY_PRIMARY_TIMEOUT_S` 可改, 超过 40 按 40), 超时 / 连不上 / 429 / 5xx / 401-404 → 这次改打备用站; 主站连续
  2 次失败 → 熔断 20 分钟直接走备用站 (「成功但慢 >25 秒」那条在 22 秒限时下用不上)。`RELAY_FORCE=backup` / `primary` 手动切。
  `/health` 的 `relay` 块带模式、熔断状态和本进程计数 (`relay_counts`), 不出地址或 key。运行手册:
  `docs/12-daily-sync-troubleshooting.md`「备用中转站 (D-148)」。
- **时限**(AU-F09, `clients.py`):SDK 一律 `max_retries=0`, 重试只留 `call_anthropic` 自己那一层 (最多 3 次, 退避 2 / 4 秒);
  单次调用限时 45 秒 (配了备用站时主站 22 秒); 整轮 (各次尝试 + 切备用站 + 退避) 最多 60 秒, 每次调用的限时再按整轮剩下的
  时间收紧。最坏: 主站挂住 22 秒 → 备用站正常约 15 秒 ≈ 37 秒拿到卡; 两边都挂住 → 第 60 秒降级返回 `[]`。60 秒不能再低:
  写作台 `open_project` 起的借阅在后台等满 60 秒, 慢的那次也要写进缓存, 接着来的 `borrow_lessons` 才拿得到。
  `/health` 的 `select` 块回显现在生效的三个时限和在飞合并的计数。三条边界:
  - 限时都按「没有新字节」算 (httpx 按每次读计), 不是墙上时钟。中转站挂着不出字节时上面的数成立 (线上见到的就是这种);
    中转站一直滴保活字节的话不封顶, 一次调用和整轮都可以超过, 等同一个请求的人到 75 秒 (`MERGE_WAIT_S`) 自己去选。
  - 主站本来会在 22-30 秒答完的那种 (线上 10 月中到 11-12 见过 3 次: 11-01 25.5 秒、11-05 28.7 秒、11-11 22.7 秒) 也在
    22 秒被切到备用站, 约 37 秒才拿到卡 (原来 26-29 秒), 写作台那次 `borrow_lessons` 可能等不到 (缓存照样写进去), 被切的
    那次主站可能照样计费。要保这种就把 `RELAY_PRIMARY_TIMEOUT_S` 调到 30, 代价是主站挂住时回到约 45 秒。
  - `RELAY_PRIMARY_TIMEOUT_S` 超过 40 按 40 (整轮 60 秒 - 2 × 10 秒): 再高的话快失败不再重试、缓存块降级不做、备用站
    剩不下一次冷选卡的时间。`/health` 回显的是按 40 封过的值。

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
(中转站/第三方网关, 可选, 不设走官方) / `FLYWHEEL_LIBRARIAN_MODEL`(见下方⚠️) /
**`LIBRARIAN_API_KEY`** / 可选的备用中转站 `ANTHROPIC_BASE_URL_BACKUP` + `ANTHROPIC_API_KEY_BACKUP` 与 `RELAY_FORCE`
(D-148, 见上))即可。healthcheck 走 `/health`。

> ⚠️ **`LIBRARIAN_API_KEY` 从"建议设"变成"必须设"**(2026-08-26,跨库审计 SUP-001)。
> 不设的话服务照常起、`/health` 照常 200,但**所有业务请求一律 401** ——
> 因为它持 service-role 客户端读 lesson cards、且每次 miss 都打一次 LLM,
> 漏配一个 secret 就等于把这两样交给公网,而漏配**没有任何症状**。
> 本地开发要免鉴权,显式设 `LIBRARIAN_ALLOW_ANONYMOUS=1`(别设进 Railway);
> 当前处于哪一态看 `/health` 的 `auth.mode`。

> ⚠️ **模型 env 名各服务不同(2026-06-04 踩过的坑)**:馆员读 **`FLYWHEEL_LIBRARIAN_MODEL`**(默认
> `claude-sonnet-5-5`),而 worker 读 `ESSENCE_MODEL`、autowriter 读 `CLAUDE_MODEL` —— **三个名字都不一样**。
> 如果你的中转站通道**不 serve 默认的 `claude-sonnet-5-5`**,却只给 worker/aw 设了能跑通的模型、忘了给馆员
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
