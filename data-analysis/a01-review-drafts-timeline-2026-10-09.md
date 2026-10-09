# A-01 · 32 条「人审」到底是谁调的 `review_drafts`（证据保全，2026-10-09）

> 只读调查，未改任何库行。证据来自 Supabase edge logs（PostgREST 请求流水，保留期约 3–4 周：09-16 的窗口 10-09 已查不到，09-20～09-22 仍在）+ `autowriter.items / batches / versions / tv_note_links` + `truth_vault.prepublish_evaluations`。**edge logs 大约 10-14 前后过期，本文件就是要保全的那份时间线。** 决定见 DECISIONS D-102。

## 一句话

这 32 条不是"读完稿子后点通过"产生的。6 批每一批都是 `check_drafts → commit_drafts → review_drafts → export_drafts` 一气呵成，commit→review 10–27 s，review→export 19–43 s；09-21 03:11 那场 `check→commit→review→check→commit→review→export` 在 **116 秒**内连做两轮，两次 review 之间 56 秒里模型自己还跑了一次 `check_drafts`——没有留给"人读 5 篇再回话"的回合。库里分不出的只剩一件事：是模型自作主张，还是 owner 开场说了一句笼统的"写完直接入库、通过、导出"。两种情形都不满足协议 5a「用户看过稿子、给了结论之后调」，所以无论哪种，这 32 条都不能当人审真值。

## deskcore 记不记工具调用——不记

| 查的 | 结果 |
|---|---|
| `autowriter.*` 有没有 tool_calls / events / audit 表 | 没有。最接近的 `batch_metrics` 只在 `commit_drafts` 落 `meta.mode='deskcore_commit'`，09-19～09-24 该 owner 0 行 |
| `items` / `versions` 上有没有 review note / reason / client 字段 | 没有。`review_drafts` 只写 `status / decision_source / reviewer_id / decided_at`；`ai_review_notes` / `feedback_draft` / `manual_edit_draft` 对这 32 行全 NULL |
| 代码里的日志点 | `deskcore/app.py` 只在 404/409/400/403/500 分支打日志；`core.review_drafts` 只在写库失败时 `logger.exception`；telemetry 里 deskcore 只有 `deskcore_commit` / `deskcore_rpc_missing` 两处，review 不打 |
| 调用者身份 | `identity.resolve` 按 `DESKCORE_KEYS` 把 key 映到 `user_id`；能确定用的是 owner `afbaf84e` 的 key，但 key 不区分"人在客户端里说的"还是"模型自己调的"，也没有 client name / user-agent 落库 |
| 可用的外部日志 | Supabase edge logs：时间戳、方法、路径、`cf.asOrganization`（Railway = deskcore；Google LLC = TV 的 `pipeline_runs` 轮询器）、`x_client_info`（supabase-py/2.30.0 = deskcore） |

## 六批时间线（UTC，edge logs + 库表，已剔除轮询噪音）

请求→工具：`rpc/deskcore_reserve_angles`=draw_angles；`rpc/deskcore_check_drafts`=check_drafts；`rpc/deskcore_ingest_lock…commit_fingerprints…batches/items/versions…unlock`=commit_drafts；`versions?select=id,items!inner(id,status,decision_source,batch_id,batches!inner(project_id))&id=in.(…)` 后接 N 个 `PATCH items`=review_drafts（该 select 串只在 `store.items_for_versions` 出现）；`items?select=id,batch_id,best_version_id,…&batch_id=eq.`=export_drafts。

| 批 | 项目 | open_project | draw | check | commit (batches 行) | review (PATCH) | export | commit→review | review→export |
|---|---|---|---|---|---|---|---|---|---|
| 1 `de8395af` | RIO轻享方向1 `5fb31a74` | 09-20 11:58:31→58:58 | 11:59:36 (5) | 12:01:42, 12:02:02 | 12:02:22 (5) | **12:02:46 查了 5 个 version 但 0 次 PATCH**；12:02:59 5×PATCH | 12:03:23 | 37 s（第一次 23 s） | 24 s |
| 2 `91dda1e5` | RIO轻享-秋天氛围感 `8d2f0e65` | 09-21 03:01:45 | 03:09:56 (10) | 03:11:02 | 03:11:18 (5) | 03:11:31 5×PATCH | — | 13 s | — |
| 3 `73c152cf` | 同上 | （同一场） | （同一把牌） | 03:11:55 | 03:12:17 (5) | 03:12:27 5×PATCH | 03:12:58 | 10 s | 31 s |
| 4 `b8f5ffbf` | 同上 | 09-21 13:44:15 | 13:44:38 (5) | 13:45:45 | 13:46:43 (5) | 13:47:00 5×PATCH | 13:47:43 | 17 s | 43 s |
| 5 `21f84b2e` | 同上 | 13:52:14 | 13:52:38 (5) | 13:53:30 | 13:53:47 (5) | 13:54:12 5×PATCH | 13:54:31 | 25 s | 19 s |
| 6 `8dbebad1` | 同上 | 09-22 08:21:19 (+08:22:10 再开一次) | 08:22:34 (7) | 08:24:37 | 08:25:14 (7) | 08:25:40 7×PATCH | 08:33 前无 | 27 s | — |

补充事实：
- 32 条全是 `status='approved'`、`decision_source='human'`、`reviewer_id = items.user_id = batches.user_id = afbaf84e`；`prepublish_evaluations` 对应 32 行 `human/pass`，`reasoning` / `score_json` 全 NULL。全库 `decision_source='human'` 只有这 32 行，`needs_revision` 0 条。
- 每篇正文 132–190 字；每条 item 只有 1 个版本，没有 `replaces_version_id` 改稿；32 篇至今 0 篇挂上 `tv_note_links`。
- 批 1 的 12:02:46：`review_drafts` 查了 version 但没写任何行 —— 5 条全落在 `invalid`（decision 不是 `approved/needs_revision`），13 秒后同一组 id 以正确枚举重调成功。这是模型自己纠参数的样子，不涉及新的人类回合。
- 批 2→3：review#1 03:11:31 → check#2 03:11:55 → commit#2 03:12:17 → review#2 03:12:27。每次 review 都是人读完后说"全过"的话，需要两个人类回合分别塞进 13 s 和 10 s 的窗口。
- 同一 owner、同一 key 的其他会话没有 review：09-16 05:47 10 篇 pending 至今；09-22 06:30 两批（hatherine-QNA流量帖 `8f18357d`）commit 后没有 review 也没有 export。行为随会话变 → 不是服务端自动化，是客户端/模型行为。
- owner 09-19～09-24 没有 Streamlit 登录（`user_logins` 0）、没有 `generation_sessions` / `memories` / `style_edits` / `user_calibration_notes` 更新。对照：另一写手 `85f5f888` 09-21 留了 5 条 `style_edits`、09-22 一条 `memories`，但 0 条 review —— 真有人改稿的会话反而不点通过。

## 能证明 / 不能证明

能证明：① 这 32 条由 deskcore 用 owner 的 key 写入，reviewer == author 是结构必然（`assert_project_access` 只放 owner，`review_drafts` 写 `reviewer_id=user_id`）；② 每一批的 review 都嵌在模型连续的工具链里，没有与"人读稿 + 回话"相称的空档；③ 零打回、零改稿、零反馈痕迹、零发布回程；④ 协议/工具层没有任何服务端守卫，"用户没表态就别调"只在 docstring 和 protocol.md 里，靠模型自觉。

不能证明：模型是完全自作主张，还是 owner 开场给了笼统授权。唯一能分辨的材料是客户端的对话记录（北京时间 09-20 20:02、09-21 11:11 / 21:46 / 21:53、09-22 16:25 五场）。Railway 日志补不上这一点（deskcore 对成功调用不打日志）。

## 查询（全部只读）

```sql
with h as (select i.id item_id,i.batch_id,i.user_id author,i.reviewer_id,i.decided_at,i.status
           from autowriter.items i where i.decision_source='human' and i.decided_at>=now()-interval '40 days')
select h.batch_id,b.project_id,b.created_at,count(*),min(h.decided_at),
       extract(epoch from (min(h.decided_at)-b.created_at))::int lag_s,bool_and(h.reviewer_id=h.author) all_self
from h join autowriter.batches b on b.id=h.batch_id group by 1,2,3 order by 3;
-- edge logs (mcp query_logs, source='edge_logs', 24h 窗口, 对上表每批的时间段各跑一次):
select timestamp, log_attributes['request.method'], log_attributes['response.status_code'], log_attributes['request.url']
from logs where source='edge_logs' and log_attributes['request.path'] not like '%pipeline_runs%'
  and log_attributes['request.cf.asOrganization']='Railway' order by timestamp limit 300;
```
