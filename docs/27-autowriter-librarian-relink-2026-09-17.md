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
3. 从此每晚 02:00Z TV 夜跑多了一步「通道 2 借阅流量检查」：过去 24h 写作台有 batch 而馆员零流量就打 `::warning`（advisory，不拖红 —— 修在你们仓，TV 红了也改不好）。接好后它应该安静。
4. 生成出来的稿子 system prompt 里应有 `[真实爆款参照 · 系统按本次选题从帆谷飞轮库匹配]` 那一节（docs/22 §2）。

## 5. TV 侧已做 / 不用你们做

- 夜跑守卫 `scripts/check_librarian_traffic.py`（D-063）。
- 书架、馆员、缓存、prompt caching 都不用动；契约不变。
- 如果你们决定改用别的注入位置或改 brief 字段，先看 docs/15 §0 的契约，改了告诉 TV 一声。
