# docs/27 · 写作台没在调馆员：通道 2 重新接线说明（给 autowriter 维护者）

**面向**：autowriter（写作台 / deskcore）维护者。
**一句话**：TV → 写作台的「爆款经验卡」通道（D-038 pull / LLM 馆员，R-032）**在生产没有在跑**。
TV 侧书架和馆员服务是好的；写作台生成时基本没有来借。请按 §2 查三件事、按 §4 验收。
**背景**：契约与接法没变，仍是 [docs/15](15-autowriter-librarian-integration.md)（详细）/ [docs/19](19-autowriter-librarian-quickstart.md)（快速接入 + 自测 curl）。本文只讲「为什么说没在跑」和「怎么确认修好了」。

---

## 1. 证据（2026-09-17 复核，TV 生产库）

写作台的生成量 vs 馆员收到的 brief（`truth_vault.flywheel_librarian_cache`，按 brief 去重）：

| 日期 | 写作台 batches / versions | 馆员被调（新 brief） |
|---|---|---|
| 08-19 | 11 / 67 | 5 |
| 09-02 | 12 / 83 | **0** |
| 09-03 | 15 / 39 | 2 |
| 09-07 | 15 / 233 | **0** |
| 09-08 | 1 / 10 | 1 |
| 09-10 | 12 / 196 | **0** |
| 09-11 ~ 09-16 | 15 / 56 | **0** |

30 天 82 个 batch、713 个版本，馆员总共 8 个 brief、集中在 3 天，最重的三天一次都没调。
8 条里 5 条 `consumer=autowriter`（8/19 同一天，像一次测试），3 条 `consumer=deskcore`（9 月初）。
R-032 在 2026-06-05 的「production 拉通」是真的，但那是一单实测；之后的生成主路径显然不带馆员。

TV 侧现状：书架 328 张策展卡（326 张爆/大爆），馆员服务 `https://truth-vault-production.up.railway.app` 活着（`GET /health`）。

## 2. 请查三件事（都在 autowriter 仓 / 部署平台）

1. **生成主路径还调不调馆员。** docs/22 §2 记的接线是 `app.py:_queue_worker_impl` 里
   `fetch_flywheel_lessons(build_brief(...))` → 传进 `memory.build_layered_system_prompt(flywheel_lessons=...)`（P2 层独立 section）。
   当时就写了风险：**R-018 Phase-2 把生成搬进 `worker.py` 时要把这段一并搬过去，否则飞轮注入会丢**。
   请看现在真正跑生成的那条路径（worker.py / deskcore MCP / 批量与单条两处）里有没有这个调用，以及 deskcore 的路径是不是只在部分流程里调（缓存里 `deskcore` 的 3 条说明它至少有时会调）。
2. **部署 env 在不在。** `LIBRARIAN_URL` / `LIBRARIAN_API_KEY`（必须等于 TV 侧 librarian 服务的 key）/ `LIBRARIAN_TIMEOUT_SEC`（建议 20）。
   `librarian_client` 是 fail-open：任何失败（含 env 为空、401、超时）都**静默返 `[]`**，写稿照常，只是没有飞轮那一节。
   所以「env 没配」和「接线丢了」在写作台上看起来一模一样：都没症状。
3. **fail-open 要留痕。** 馆员返回 `[]` 或抛异常时打一条 WARN（带 project_id、HTTP 状态或异常类型）并计数；
   env 为空时启动就 WARN 一次。不然这条通道下次暗了还是没人知道。

## 3. 自测（不改代码，先证明馆员端能用）

```bash
export LIBRARIAN_URL='https://truth-vault-production.up.railway.app'
export LIBRARIAN_API_KEY='<librarian 口令, 找 TV/运维拿>'
curl -sS "$LIBRARIAN_URL/health"
curl -sS -X POST "$LIBRARIAN_URL/librarian" \
  -H "X-Librarian-Key: $LIBRARIAN_API_KEY" -H 'content-type: application/json' \
  -d '{"consumer":"autowriter","project_id":"relink-test","brand":"test",
       "system_prompt":"为一次性内裤写小红书种草, 强调便携卫生、差旅/经期场景。",
       "tactic":"经期场景痛点切入","target_audience":"年轻女性","tone":"闺蜜口吻"}'
```
预期：`selected` 里 3–5 张卡（`source_note_id` / `why_relevant` / `borrow_what` / `structure` …）。
返回 `{"selected": []}` 说明是馆员端问题（模型 env / 空库），不是你们的接线，找 TV。401 = key 不对。

## 4. 验收（怎么算修好）

1. 接完后在写作台**真跑一单生成**（不是 dry-run）。
2. TV 侧看馆员流量：
   ```sql
   select consumer, project_id, created_at, last_hit_at
   from truth_vault.flywheel_librarian_cache order by last_hit_at desc limit 20;
   ```
   应出现一条 `consumer=autowriter`（或 `deskcore`）、时间是刚才那一单的行。同一个 brief 反复生成只刷 `last_hit_at`，不新增行，这是缓存命中，也算通。
3. 从此每晚 02:00Z TV 夜跑多了一步「通道 2 借阅流量检查」：过去 48h（与每日夜跑重叠）写作台有 batch 而馆员没被写作台调过就打 `::warning`（advisory，不拖红 —— 修在你们仓，TV 红了也改不好）。只数 `consumer` 为 `autowriter` / `deskcore` 的流量，ssll 或诊断 curl 的不算 —— 所以**别改 brief 里的 `consumer` 值**，改了要告诉 TV。接好后它应该安静。
4. 生成出来的稿子 system prompt 里应有 `[真实爆款参照 · 系统按本次选题从帆谷飞轮库匹配]` 那一节（docs/22 §2）。

## 5. TV 侧已做 / 不用你们做

- 夜跑守卫 `scripts/check_librarian_traffic.py`（D-063）。
- 夜跑守卫 `scripts/check_angle_ledger_leak.py`（D-071）：发了角度没走到成稿就 `::warning`，两种形状分开报（「抽完没写」vs「写了不带 `angle_key`」），**先排除 `tv_note_links.match_kind='ingested'` 的导入副本**再算——不排除的话未归因率永远 97%+，而且病因会判反。同样是 advisory，不拖红。
- 书架、馆员、缓存、prompt caching 都不用动；契约不变。
- 如果你们决定改用别的注入位置或改 brief 字段，先看 docs/15 §0 的契约，改了告诉 TV 一声。

## 6. 查完了（2026-09-19，D-069）：管子通、龙头没人拧

§2 三件事的答案，都在 autowriter 仓查的（HEAD 74ad881）+ TV 生产库复核：

1. **生成主路径还调不调馆员。** 三条路径都接着：Streamlit 的 `generation_service._queue_worker_impl` / `_quick_gen_worker` 都调 `fetch_flywheel_lessons(build_brief(...))` 并把 `flywheel_status` 记进 `batch_metrics.injection`；deskcore 有 `borrow_lessons` 工具。但**真正在跑的只有 deskcore**：30 天里写作台 90 个 batch 全是 `ai_engines=["deskcore"]`（71 批 `params.source=deskcore` 的成稿 + 19 批 `source=ingest` 的 tv-sync 补录），Streamlit 路径最后一次跑是 08-19（那天 `flywheel_lessons: 5`，管子是通的），`autowriter.jobs` 表是空的（worker 队列没人用）。
   而 deskcore 那条路的问题是**协议**：`open_project` / `draw_angles` 必做，`borrow_lessons` 是「想要真实爆款参照时调」。09-01 ~ 09-16 写作台 commit 了 71 批稿子，馆员缓存里 consumer=deskcore 只有 3 行（09-03 ×2、09-08 ×1，各借到 4-5 张卡）。通道 2 在每场对话里取决于模型愿不愿意多调一个可选工具，它 95% 的时候不愿意。
2. **部署 env 在不在。** 在。deskcore `/health` 报 `librarian.configured: true`，那 3 次借阅都成功。Streamlit / worker 服务的 env 从这里看不到，但那两条路径本来也没在跑，不是当前的问题。
3. **fail-open 有没有留痕。** `librarian_client` 五种结局各发一条 telemetry 事件（stdout JSON），deskcore 端没有 WARN。

**修法**（autowriter [PR #85](https://github.com/TangVarie/autowriter/pull/85)）：把借阅并进必做的 `open_project`——简报多出 `lessons` / `lessons_status`，`borrow_lessons` 改成换题时「再借」；`not_configured` / `timeout` / `error` 各记一条 WARN；协议正文和 skill 同步改口（运营要重新导入一次 skill）。brief 的 `consumer` 仍是 `deskcore`，D-063 的夜跑检查口径不变。

**验收**照 §4：合并部署后运营开一场写作台对话，`flywheel_librarian_cache` 里应多一行 consumer=deskcore；D-063 的 `::warning` 应从此安静。

