# 三仓内部架构全链路审计（truth-vault · autowriter · JevforCoentent）· 2026-10-08

> **怎么来的**：接着 `three-repo-status-2026-10-08.md`（当天上午的状态复核）往下挖。这次不看"转没转"，看"每一段的内部是怎么接的、哪里会断、断了谁知道"。
> 三个仓各拉到当天 main（TV `3aca9ab` · aw `1cb9046` · Jev `f0096ec`），按七段流程分头读代码（每段一个只读审计，共 ~360 次文件读取），
> 每一条代码结论再拿 **生产库**（Supabase `kduysqedr`）、**GitHub Actions 运行记录**、**Supabase 安全顾问** 核一遍。
> 下面每个数字都是 10-08 11:00 UTC 前后查出来的；标 **[生产确认]** 的是查到了，标 **[代码确认]** 的是代码能证明但生产还没出现过，标 **[疑似]** 的是推断。
>
> **一句话**：主干飞轮在转，但 **三处"真值"已经被悄悄污染**（写作台"人审"全是模型自审、31 篇笔记血缘倒挂、闸二快照分裂），
> **四处"断了没人知道"**（借卡超时让写手整份简报丢掉、回程 cron 永远比夜跑早、外部语料写库失败静默丢周、缺 secret 永久绿），
> 其余是 20 来条灯不亮 / 文档漂 / 半态 的老问题。本文只审不修；§5 给了处理顺序。

---

## 0. 一页读完

**每段流程最该先修的一件事**

| 段 | 内部状态 | 最该先修 |
|---|---|---|
| 采集（飞书 → notes / comments） | 转，但无防误标闸，评论步每晚全量重解析 | A-06 整批 tier 翻转闸 · A-07 评论步按内容哈希跳过 |
| 通道 2（essence → 策展 → 书架 → 馆员 → 写作台） | 转；馆员降级对写手显示为"没卡"；卡片内容冻结在首次策展 | A-04 借卡与 open_project 解耦 · B-02 再策展路径 |
| 通道 1（TV → 三省六部） | D-086/087 后干净（stale 0 · gated 80） | 无 P1；B-14 未来发布时间夹住 |
| 写作台（open_project → 发牌 → commit → judge → 回程 → 人审） | 32 条"人审"是整批自审；31 篇血缘倒挂；judge 通电但 0 样本 | A-01 自审标记 · A-02 补录副本不参与匹配 · A-05 回程 cron 挪到夜跑之后 |
| 特征层（题库 → 抽取 → 账本 → 闸一 → 闸二） | 2,231 篇有特征；闸二没有脚本；快照分成两半；on_demand 大项目 0 负例 | A-03 写 `gate2_run.py` + 决定快照口径 |
| Jev 八个位置 | ⑧ 通；⑤ 通电 0 样本；①②③④⑥⑦ 休眠 | A-08 外部语料写库失败要红 · A-09 MCP 别带 key |
| 运维（workflow / 服务 / 灯） | 看门狗只看"有没有绿"；缺 secret 也绿；5 个模型环境变量名 | B-10 cron 事件缺 secret 要红 · B-01 退掉饱和灯 |

**P1 清单（10 条，§2.1 有证据）**

| # | 一句话 | 判定 |
|---|---|---|
| A-01 | 近 30 天 32 条 `human` 审稿全部是提交后 9–37 秒内整批自审 → `prepublish_evaluations` 的人审真值被污染 | 生产确认 |
| A-02 | tv-sync 把 31 篇笔记的 `source_autowriter_version_id` 指到了"从 TV 补录进来的副本" → 对照视图把它们算成写作台产出 | 生产确认 |
| A-03 | 闸二没有可执行脚本；361 篇（含闸一全部 100 篇）在旧题库 sha；NUC/NRT_2/NRT_3 在当前 sha 下 0 负例 | 生产确认 |
| A-04 | open_project 同步借卡最长 60 s，MCP 客户端只容忍 ~22 s；09-22 冷借 13 次里 12 次超 22 s；此后周产量 175 → 16 → 0 | 生产确认 |
| A-05 | aw 回程 cron 04:00 UTC；TV 夜跑实际 08:04–09:00 UTC 才起 → 回程每天看的是前一天的笔记 | 生产确认 |
| A-06 | 采集对整批 tier 翻转没有任何闸；08-18 OKMAN 一晚 285 条升爆（82.4%） | 生产确认 |
| A-07 | 评论步每晚对所有有评论的笔记全量重解析，≥2 次 HTTP/篇，无 `skip_on_cron`，永远 exit 0 | 代码确认 |
| A-08 | 外部语料：`apply_rows` 写库失败 `continue-on-error`，但 `seen` 状态已先存 → 那一周静默丢；10-12 首次 main 定时跑缓存为空 | 代码确认 |
| A-09 | 写手侧 MCP 把 `TYPESAFE_API_KEY` 和暗题（可一行算出）带到写手机器；project 自报 | 代码确认 |
| A-10 | Jev 切主抽取会打碎账本：无 `done_by`、无 `code:v1`、一次问 20 题违反 §5.3、对照视图按 extractor 分裂 | 代码确认 · 决策项 |

---

## 1. 全链路地图

每张表四列：**步骤（函数/位置）· 触发与幂等键 · 失败被吞在哪 · 谁能看见**。行号以 10-08 main 为准。

### 1.1 采集：飞书 → `notes` / `comments`（`daily-sync.yml`，cron `17 2 * * *`，实际起跑 08:04–09:00 UTC）

| 步骤 | 触发 / 幂等键 | 失败被吞在哪 | 谁能看见 |
|---|---|---|---|
| `feishu_sync` → `sync_feishu_notes_to_truth_vault.py main()`：`load_mapping` → `skip_on_demand_on_cron`（:1466）→ `assert_db_schema_ready`（:1539）→ 逐行 `transform_row` → `quarantine_record` → `upsert_notes_batch` → `upsert_metrics_batch` → `update_project_date_range` → 只报不改的 reconcile（:1946） | `note_id = f"{project_id}_{record_id}"`（`_common.py:530`），PostgREST `on_conflict=note_id`；**payload 里没有的键保留库值**；`metric_snapshots (note_id,window_label,source)`；隔离表 `(project_id,record_id,reason)` ignore_duplicates | 表级拉取失败只计数（:1596）；`transform_row` 异常只计数（:1729）；`_detect_missing_core_columns` 读库失败 → 守卫静默关闭（:476）；`update_project_date_range` 失败只 warning（:1919）；reconcile 查询失败 = "没有消失的"（:1969） | `errors>0` 才 exit 1；aggregate 步汇总 |
| `comments_sync` → `sync_comments_from_raw_extra.py`：拉所有带 `raw_extra` 的笔记（:488）→ 每篇 `existing_comments` + `write_comments`（按 `(role,content)` 配对，id `{note_id}_h{sha12}_{nth}`）→ 清空 reconcile | **无 `skip_on_cron`**（yml:147-169）；内容键 id | reconcile 失败 → `stats=-1`，exit 0（:552）；`return 0` 永远（:573）；插入失败 raise → 该项目中途断，后面项目当晚全跳 | 看不见 |
| essence / curate / ssll / prepublish | 见 1.2 / 1.3 / 1.4 | | |

**tier 的来源链**：状态字段 → `tier` + `tier_source='状态字段'`（:792-799）；备注字段次之；评论兜底 `数值推断`（书架视图排除）。`人工补录` 没有任何代码路径写，库里手改会被下次 sync 覆盖。

### 1.2 通道 2：essence → 策展 → 书架 → 馆员 → 写作台

| 步骤 | 触发 / 幂等键 | 失败被吞在哪 | 谁能看见 |
|---|---|---|---|
| `essence_sync` → `POST worker/annotate-essence`（每项目，on_demand 跳过，≤8 篇/请求，`WORKER_LIMIT`=15/项目）→ `annotate_essence_pass.py` | `essence_annotated_at IS NULL`，按 `note_id` 升序（:555-568） | 子方向失败 → 笔记照样标完、`direction_subtype` 永远空（:803-809）；逐篇失败 → `failed_essence_queue.jsonl`（Railway 临时盘，没人读，:889-922）；409/502/503/504 → `::warning`（yml:190-198） | `systemic>0 and ok==0` 才红 |
| `curate_sync` → `POST worker/curate` → `curate_flywheel_lessons.py`：`v_flywheel_lesson_cards WHERE NOT is_curated ORDER BY rank_score DESC` → LLM → upsert `flywheel_lesson_annotations`（`curated_at=NOW()`） | `note_id` PK；共享预算 ≤15 卡/晚 | 单卡失败 → 留着明晚；任一卡成功 exit 0（:259-266）；**`/curate` 只转发 `limit/project/dry_run`（`worker/app.py:371-387`），`--recurate` 只有 CLI 有** | 409 = "transient" |
| 书架视图 `v_flywheel_lesson_cards`（v1_4 → v1_10 夹 → v1_14 工单闸）：`rank_score = recency + tier + tier_source + 0.3×account_bao_rate` | 实时视图 | — | — |
| 馆员（Railway `truth-vault-production`）`librarian_select`：整架 ≤1000 → `library_version(count, max curated_at, month, id-digest[, gate2_run])` → `cache_key` → 命中即回 → `shortlist` 24（rank 前 8 永远在，D-088）→ `_select_via_llm`（sonnet，`max_tokens` 1000）→ `put_cache(select_ms)` | `cache_key`（`core.py:255-262`） | LLM 失败 → `[]` + `status=degraded`，**不写缓存行**（:489-500）；`put_cache` 失败只 warning（:507-512）；`last_hit_at` 更新 `except: pass`（:273-277）；`latest_gate2_run` 失败放行（:241-243）；**HTTP 永远 200**（`app.py:100-108`） | Railway 日志 |
| 写作台消费：`_borrow_for_brief`（`deskcore/core.py:3632-3670`）在 `build_writing_brief` 的**同步路径**上，`LIBRARIAN_TIMEOUT_SEC`=60（`config.py:124-129`）；渲染 ≤5 张（`memory.py:304`） | — | `librarian_client.py:118-150` 一切 → `[]`；**不读 `status`**，`[]` → `BORROW_EMPTY`（:159-181） | 写手看到"没有合适的卡" |
| 灯（`always()`）：`check_positive_saturation.py` · `prune_librarian_cache.py --ttl-days 30` · `check_librarian_traffic.py`（48h） | daily-sync 尾部 | 全部 `|| true` | 只在 Actions 日志 |

### 1.3 通道 1：TV 爆款 → `public.reference_samples`（三省六部）

`sync_truth_vault_baokuan_to_sanshengliubu.py`：先 `retract_stale`（D-087，先清 TV 标记再删 ssll 样本）→ 再 push（`fetch_pending_baokuan`，12 个月窗 :152，排除 synthetic 与 铺评工单）。状态视图 `v_flywheel_sync_status`（v1_19）：`pending_ssll_sync` / `gated_ssll_sync` / `stale_in_ssll`。

10-08 生产：306 条样本；17 项目 `stale_in_ssll` 全 0；`gated` 合计 80（TUGE 56 · BJS 10 · RIO 10 · ANSHEN 2 · HATHERINE 1 · SPX 1）。撤回只 `logger.info`（:332），`main()` 只在 push 错时非零（:804）；状态打印步 `|| true`（yml:496）。**无 P1**。

### 1.4 写作台：open_project → 发牌 → commit → judge → 回程 → 人审 → prepublish

| 步骤 | 触发 / 幂等键 | 失败被吞在哪 | 谁能看见 |
|---|---|---|---|
| `get_protocol`（`tools.py:84`）：12 位 hex 摘要 | — | 不吞（有意） | — |
| **`open_project`** → `core.build_writing_brief:236`：P0 硬约束（fail-closed，`store.shared_memories:220`）→ 软层相关度（Gemini 嵌入 ×2，无 http 超时）→ **同步借卡 ≤60 s** → `angle_debt`（:383） | 只读 | 借卡、angle_debt 异常全吞 | `protocol.md:55`："这个工具报错就停下来，不要凭记忆补一份约束" |
| `draw_angles:412` → RPC `deskcore_reserve_angles`（`001:261`，事务级 advisory lock；占位挡 1 天，已消费挡 `avoid_days`） | `(project, angle_key)` 窗内唯一 | `record_draw:684` / `recent_angle_keys:618` 失败 → "drawing WITHOUT cross-batch avoidance" | — |
| 生成：**客户端模型**；deskcore 零 LLM 调用（`core.py:3088`） | — | — | — |
| **`commit_drafts:1393`**：项目写锁（等 90 s / TTL 600 s，:2788）→ `_gate`（fail-closed）→ 指纹 RPC（原子复查）→ `mint_draft_identity` → `consume_angle` | 指纹 `version_id`（行存在前先铸，:1491） | mint 半成功（`store.py:1335`）、替换挂接（:1615）、consume（`store.py:727/745`）、metrics（:1379）、锁释放（:2840）全吞；**`consume_angle` 对 `inserted_idx` 全跑，不看 `minted_ok`**（:1633-1647） | `judge_status` / 返回体 |
| judge（影子）：锁释放后线程池，共享 8 s 死线（`_judge_committed:1246`）；`judge_client.judge_draft:201` 永不 raise；`write=true`，`subject_type='aw_version'` | PK 含 `subject_id=versions.id` | 一切 → `judge_status`；外层 try（:1811）；超时后 judge 仍可能写账本（:1254） | `batch_metrics.meta.judge` |
| `batch_metrics`（`_record_commit_metrics:1340`，`meta.mode='deskcore_commit'`） | 无 | 插入失败吞 → 8 s 再调参样本偏 | — |
| **回程 `tv-sync`**：Railway cron `0 4 * * *` `--all --write-tv`（`railway.cron.json`）→ `core.tv_sync:3908` → `tvlink.match_note:222` → `ingest_published`（100 篇/块，锁）→ `tv_links_upsert` → `deskcore_tv_backfill_lineage`（只填 NULL 列） | `tv_note_links.note_id` PK；ingest 按 `(opening_hash, ngram)` 幂等 | 指纹写（:2970）、item 查（:3824, :4063）吞；**块循环（:4034-4056）和每 TV 项目循环（`cli._tv_sync:326`）无 try** → 一个 `IngestBusy` 当晚后面项目全断 | Railway 日志 |
| 人审 `review_drafts:1850` → `db.update_item_status:1099`（`decision_source='human'`，`reviewer_id=caller`） | 每批每条一次（:1933） | 逐行失败报 `failed` | — |
| → TV `sync_autowriter_decisions_to_prepublish.py`（`daily-sync.yml:411`）：`_provenance:182` → `prepublish_evaluations` | `(autowriter_item_id, evaluator_type)` 唯一 | 审计崩溃吞（:691） | `audit_archived_provenance` 每晚 32 条 WARN ④"自己审自己" |
| `v_angle_outcomes`（aw `011`）：`angle_ledger`（已消费）LEFT JOIN `tv_note_links` LEFT JOIN `notes.tier` | 视图 | — | 只有 `doctor` 读（`deskcore/core.py:2411`） |

### 1.5 特征层：题库 → 抽取 → 账本 → 闸一 → 闸二 → 消费者

| 步骤 | 触发 / 幂等键 | 失败被吞在哪 |
|---|---|---|
| 题库 `prompts/feature_questions_v0_1.yaml`：`status: draft`（:67），无 `frozen_sha256`；规范 sha **ba0f570c…**（`feature_bank.py:92-103`）；5 题已到 v2/v3 | 改题库 = 新快照，不重抽旧笔记 | `validate_bank` 只在 `frozen` 时校 sha（:205-211） |
| `annotate_feature_pass.py`：每篇 11 行 `code:v1` + 20 行 `llm:<model>`；6 组调用（`fb.plan_calls`），失败组重试一次（:229-241），`missing`/`json_parse_failed` 单题兜底（:245-263） | DONE 标记 `has_specific_time` under `(extractor LIKE 'llm:%', run_tag)`（:70, :107-141）；PK `(subject_type,subject_id,question_id,question_version,extractor,run_tag)` | 任一组 `api_error` → 整篇不写、下轮再来（:463-469）；`failed_feature_queue.jsonl` 在 worker cwd（临时盘，没人读，:382） |
| worker `/annotate-features`（`worker/app.py:297`）：脚本级锁 → 409；子进程 900 s；Railway 边缘 ~300 s 切断 | — | 502 = 边缘切了但 worker 还在跑、锁还在 |
| `features-sync.yml`：cron `47 12 * * *`（实际 16:45–20:48 UTC 起，35–85 min）；`FEATURE_LIMIT` 24（D-089）；`FEAT_REQ_MAX=2`；on_demand 跳过（:171-175） | 同上 | 409 等 60 s×5；502 扣预算继续；只有某项目**第一批**就 systemic 或 >½ 项目饿着才红（:216-241）；注释自认"挡不住慢性欠产" |
| `backfill-features.yml`：手动；`note_ids ≤ 200`；`run_tag` / `bank_sha` 探针；**无 on_demand 闸**；note_ids 路径**不暴露 `reannotate`**（worker 接受，`app.py:315`） | primary 下已答过的跳过 | — |
| 闸一：`gate1-jev-vs-tv-v2-2026-09-23.md`；owner 95 格裁决（`human:owner`，`gate1-20260928`）；D-084 关闭 | 一次性 | 结论没有机器可读形式（无 `retired:` / `gate1_status`） |
| 闸二：`v_feature_contrast`（v1_13:93-115，按 `question_version, bank_version, bank_sha256, extractor` 分组）→ **没有代码**，只有 docs/28 附录 B 的 SQL（:625-770） | `feature_validation` PK `(question_id,question_version,answer,gate2_run)` | — |
| 消费者：馆员 `latest_gate2_run` 只进 `library_version`（`core.py:155`）；`instructions_for_desk`（:791）无生产调用方；`draw_angles` 是 `random.Random`（:441） | — | 闸二结论今天只会换馆员缓存键 |

### 1.6 Jev 八个位置（JevforCoentent，judge = Railway `judge-production-601c`）

| # | 位置 | 状态 | 已有 | 第一次真用会断在哪 |
|---|---|---|---|---|
| ① | TV 主抽取 → Jev | 休眠 | `/judge`、`fq_shadow.py --from-db`；TV `annotate_feature_pass.py --done-by`、`worker/app.py:334` | 没有 workflow 传 `done_by`；Jev 不产 `code:v1`；见 A-10 |
| ② | 评论回填 | 休眠 | `scripts/backfill_comments.py`（ops v0.2 + reader v0.3） | `fetch()` 单次 GET 无分页（:51-54），9,652 行 > PostgREST 默认 1000；reader 在 MCP/HTTP 是 v0.4 |
| ③ | 借卡 → Jev | 缺 | — | owner 已走嵌入预筛（D-088） |
| ④ | 发牌筛组合 | 缺 | — | 等闸二 |
| ⑤ | 写作台入库判定 | **通电，0 样本** | `/judge_draft` + `judge/draft.py` + `judge/policy.py`；aw `judge_client.build_draft_request` | aw 发 `judge_paras="never"`、无 `brief`、`return_rows=false`（`autowriter/judge_client.py:107-125`）→ human_feel 题库装了不判、**暗题永远不判**（`loop.py:236-238`）、项目层全死（B-07） |
| ⑥ | 三省六部二审 | 休眠 | `banks/ssll_critic_v0.1.yaml`（8 题） | 无调用方；`ssll_sample` id 约定只在 v1_17 注释里 |
| ⑦ | 素人初稿 | 缺 | — | docs/00 #8 "后做" |
| ⑧ | 外部语料 | **通；首次 main 定时跑 10-12 03:00 UTC** | `judge/external.py`、`scripts/external_corpus.py`、`apply_rows.py`、`external-corpus.yml` | A-08 |

账本写入（`judge/core.py:258-267`）：200 行/批，每批一个 POST，`Prefer: resolution=merge-duplicates` 无 `on_conflict` → 按 PK 合并，Jev 与 Opus 行可共存；第 k 批失败前 k-1 批已落、`api.py:253/314` 无 try → 500。mock 拒写两道闸都在（`api.py:183-184`、`core.py:252-254`）。

### 1.7 运维：workflow / 服务 / 环境变量 / 灯

| workflow | 触发 | timeout | 写什么 | 失败谁知道 |
|---|---|---|---|---|
| `daily-sync.yml` | `17 2 * * *`（实际 08:04–09:00 UTC，跑 44–53 min） | 240 | notes / accounts / metrics / comments（runner）；essence、curate（worker）；ssll push+retract；prepublish；缓存 prune | aggregate 步 → 邮件；cancelled → 只有看门狗 |
| `features-sync.yml` | `47 12 * * *`（实际 16:45–20:48 UTC） | 240 | `note_feature_answers` | 红 → 邮件；无时长灯 |
| `sync-watchdog.yml` | `41 23 * * *` | 10 | 无 | 只问"26 h 内有没有一次 schedule 成功"（:54-58, :98-102） |
| `backfill-essence/features.yml` | 手动 | **无**（默认 360） | 同上 | 触发人邮件 |
| Jev `external-corpus.yml` | `0 3 * * 1`（整点） | 40 | `external_notes` + 账本，**`continue-on-error: true`**（:59） | 只有抓取红会发邮件；无 concurrency 组 |
| aw `railway.cron.json` | `0 4 * * *` | — | `tv_note_links`、`notes.source_autowriter_version_id` | 无 |

| 服务 | `/health` 报什么 | 未配置时 | 静默点 |
|---|---|---|---|
| TV librarian | `ok` 永远 true + `auth` | 401 | ANTHROPIC key/模型错 → `degraded` + `[]` + 200；`/health` 不报 ANTHROPIC |
| TV worker | auth + `essence_model`/`feature_model` + `running[]` | 401 | **`FLYWHEEL_CURATOR_MODEL` 不在 `/health`**（`worker/app.py:254-257`），但 `/curate` 子进程读它（`curate_flywheel_lessons.py:205`） |
| TV onboarder | auth | 401 | — |
| aw deskcore | `/health` 永远 200；`/ready` 503；`judge.configured` | 401 | 嵌入降级为"纯确定性"只带 note（`app.py:518`） |
| judge | `mode/jev_key/write_enabled/mock` | **503**（不是 401） | 无 Supabase → 静默只读 |
| Vercel 看板 | — | — | 无 key → `EMPTY_DATA` 渲染全零 |

模型环境变量五个名字：`FLYWHEEL_LIBRARIAN_MODEL` / `ESSENCE_MODEL` / `FEATURE_MODEL` / `FLYWHEEL_CURATOR_MODEL` / `ONBOARDER_MODEL`（+ aw `CLAUDE_MODEL`），只有前三个一起写在文档里。

---

## 2. 未解决问题（按严重度）

### 2.1 P1

**A-01 · 写作台 · 32 条"人审"全部是整批自审，9–37 秒内完成** — [生产确认]
`assert_project_access:131-136` 只放项目 owner；`store.py:1354` `items.user_id = user_id`；`core.py:1944-1946` `reviewer_id=user_id` → `reviewer_id == items.user_id` 恒成立。生产：近 30 天 `decision_source='human'` 32 条，分 6 批（09-20 ~ 09-22），**每批 5–7 条在同一秒内 approved，距该批 commit 9–37 秒**，全部 `self_review=true`；`prepublish_evaluations` 近 30 天 `human` 32 条全是它们。协议 `protocol.md:107` 禁止自动通过。TV `audit_archived_provenance:488-491` 每晚打 32 条 WARN ④ 但没人看。
后果：写作台 → TV 的"人审真值"（闸三 / 校准要用的）目前 100% 是模型给自己盖的章。
修法：(1) 这 32 条改 `decision_source`（新值 `self_auto` 或并入 machine 集），TV `_MACHINE_DECISION_SOURCES` 同步；(2) `review_drafts` 拒绝 commit 后 N 分钟内 / reviewer == author 的整批 approve，或者引入团队成员模型；(3) 至少让 `sync_autowriter_decisions_to_prepublish.py` 对 `batches.params.source='deskcore'` 的 item 不写 `human`。

**A-02 · 回程 · 31 篇笔记血缘指向"从 TV 补录进来的副本"（因果倒挂）** — [生产确认]
`versions_for_linking`（`store.py:1956`）索引**所有** item，含 ingest 批次。隔天另一篇正文相同的 TV 笔记（交叉发、重发、上次崩了没链上）`body_exact` 命中补录副本 → `_backfillable`（`core.py:3901-3905`）→ `--write-tv` 把 `notes.source_autowriter_version_id` 写成一个"来自 TV"的版本。同轮重复处理正确（`dup_of` → `ingested`，:4015-4025），跨轮没有。
生产：`notes` 血缘 416 篇 = deskcore 380 + ui 5 + **ingest 31**（SPX 23 篇 08-09~08-13 发布 · HATHERINE 7 · LNKT 1；30 `body_exact` + 1 `fuzzy`）。`truth_vault.v_model_comparison` 存在，会把这 31 篇算成写作台产出。
修法：匹配索引排除 `batches.params->>'source'='ingest'`（只留给 `already_linked`/去重）；每项目、每块包 try，链接按块 upsert；这 31 篇的 `source_autowriter_version_id` 置空（备份先）。

**A-03 · 特征层 · 闸二今天跑不起来，三件事叠在一起** — [生产确认]
(a) **没有脚本**：`grep -il mantel|statsmodels|benjamini scripts/` 为空；`statsmodels` 不在 requirements；`feature_validation` 只有 CI 夹具写过（`ci.yml:7198,7205`）；D-070 自认"闸二 SQL 仍在 docs/28 附录 B"；`gate2-baokuan-missing-features-2026-10-08.md:45` 说"再跑 `scripts/` 里闸二那套"——那套不存在。附录 B 只有 B.1（MH OR）和 B.2（方向）；BH q 值、账号先验分层、status 赋值、B.3 bootstrap、报告输出都没有。
(b) **快照分裂**：`v_feature_contrast` 按 `bank_sha256` 分组；生产 primary 下 **361 篇在旧 sha `3d299a1e`**（含闸一全部 100 篇，其中 50 篇是爆款），1,870 篇在 `ba0f570c`。钉在新 sha 就丢 361 篇全部 31 题；DONE 标记挡住 primary 重抽；`backfill-features.yml` note_ids 路径不暴露 `reannotate`。
(c) **on_demand 大项目 0 负例**：当前 sha 下 2×2 支持度 NUC 75/0 · NRT_3 33/0 · NRT_2 32/0 · HXZ_FB 14/0 · HXZ_QD 4/0（正/负）。B.1 这些层 `a·d/n = b·c/n = 0`；B.2 退化成"正例里有特征的比没特征的多"，不是对比。D-089 只回填正例（今天 237 篇）是对的，但没补负例。
修法：写 `scripts/gate2_run.py`（B.3 唯一性为 0 才跑；B.1/B.2 读 `v_feature_contrast`；statsmodels BH；账号先验再分层；写 `feature_validation` 带 `gate2_run`；出 `feature-gate2-<date>.md`；CI 夹具复现 docs/28 的 OR 2.477 / CI 1.738–3.530）；预注册时二选一：全库在新 sha 重抽 361 篇（≈361×6 次 Opus，batch 2 约 6 h；note_ids 路径加 `reannotate` 输入）或闸二只用新 sha；on_demand 三个大项目各补 60–100 篇趴（同一机制，各 1–2 h），或预注册"闸二只看 daily 项目"。

**A-04 · 写作台 · open_project 的同步借卡让整份简报（含 P0 硬约束）一起丢** — [生产确认]
`config.py:124-127` 自己写着："借阅在 open_project 必经调用的同步路径上…若 MCP 客户端自身超时低于 60s，整份简报(含 P0 硬约束)会一起丢…我们只测到过客户端容忍 ~22s"；`tests/test_librarian_timeout.py:35,52` 把默认钉在 ≥45 s。服务端 `run_in_threadpool` 无预算，客户端报错，`protocol.md:55` 让模型停笔。
生产（`flywheel_librarian_cache.select_ms`）：09-21 8 次 p50 23.2 s（5 次 >22 s）；**09-22 13 次 p50 58.8 s，12 次 >22 s，6 次 >60 s**；09-28 1 次 23.7 s；09-30 2 次 46.9 s。写作台真写版本按周：09-07 465 → 09-14 44 → 09-21 175 → 09-28 16 → 10-05 **0**。`deskcore_commit` 指标只有 09-28 周 5 次。D-088 预筛（10-08 合并）之后**还没有一次借卡**，效果未验。
修法：借卡从 `build_writing_brief` 的同步路径拆出，单独短预算（8–10 s，超时返回 `lessons_status=timeout` 并提示稍后 `borrow_lessons`），或像 judge 一样 `cf.wait(timeout=…)`；改测试。

**A-05 · 回程 · aw tv-sync cron 04:00 UTC 在 TV 夜跑之前** — [生产确认]
`deskcore/railway.cron.json:3` 理由是"TV 夜跑是 UTC 02:00"。Actions 记录：daily-sync `schedule` 近 8 次 `run_started_at` **08:04–09:00 UTC**（GitHub cron 漂移 6–7 h，TV README:185 自己记过"06:30~08:00"），features-sync 16:45–20:48 UTC。所以 04:00 的回程每天匹配的是**前一天**夜跑进来的笔记；D-064"验收看接下来几天"没有书面关闭。
修法：Railway cron 挪到 ~14:00 UTC，或由 daily-sync 末尾触发；在 DECISIONS 记一句。

**A-06 · 采集 · 整批 tier 翻转没有闸** — [生产确认]
`transform_row:792-799` 逐行从状态格写 `tier`，`main()` 从不与库值比。事后网：`audit_log` 触发器、D-087 隔晚撤回、`v_tier_discrepancy`（v1_12 要 `comments_count`，只 7 个 mapping 映射了，OKMAN 没有，且没人跑）。D-087 自认"要挡'推出去'本身，得在 push 侧对单晚新增爆款数设上限"。
生产：08-18 OKMAN 一晚 285 条升爆（82.4%）。
修法（成比例）：`upsert_notes_batch` 前拉 `(note_id, tier)`，数从非正例/NULL 升到 {爆,大爆,参考} 的条数，`> max(15, 10% 项目笔记)` → 本轮 payload 剥掉 `tier/tier_source`（内容/指标照写），`::error` + exit 1，`workflow_dispatch` 加 `allow_mass_tier_flip`。

**A-07 · 采集 · 评论步每晚全量重解析、无界、永远 exit 0** — [代码确认]
yml:147-169 无 `skip_on_cron`；`main():488` 拉所有带 `raw_extra` 的笔记（payload 含整段评论）；每篇 `existing_comments` → `fetch_all_pages` 以**空页**终止（`_common.py:1285`）→ ≥2 请求/篇 + 重排 + 插入；再 reconcile 翻全部评论 note_id。docstring `:52`"Skip if comments already has rows"自 COR-013 起是假的。17 个 mapping 都映射了随贴评论；最重的 NUC/NRT/HXZ 是 on_demand，内容不变。
修法：(a) `notes` 上存 `sha256(_comment_text+_persona)`，没变就跳（别用 `updated_at`，`set_updated_at` 无条件 bump，D-078）；(b) 这步加 `skip_on_cron`；(c) 失败计数并非零退出。

**A-08 · Jev ⑧ · 写库失败那一周静默丢；10-12 首次 main 定时跑缓存为空** — [代码确认]
`scripts/external_corpus.py:87-88` 在 workflow 的写库步之前 `save_state()`（全部标 `seen`）；`external-corpus.yml:57-60` `apply_rows.py` 带 `continue-on-error: true`；`apply_rows.py:36-38` 失败返回 1。结果：job 绿、`actions/cache` 存了 `seen`、`known_ids` 没这些笔记、永远不再抓；唯一痕迹是 artifact。另：唯一一次好跑（#11）来自分支 `claude/focused-franklin-blz1ig`，Actions 缓存只能从同分支或默认分支恢复 → 10-12 在 main 上 `seen={}`、`monthly={}`，钱由 `known_ids` 护着，但 ~1,400 个 triage 拒绝项要重判；`run_once` 单线程（`external.py:371-434`），估 16–27 min，`timeout-minutes: 40`。`systemic_failure` 只在**全部**失败才红（:450-453）。
生产：`ext-20261008-0513` 200 篇、每篇恰 24 行、无半写——目前干净。
修法：只在 `apply_rows` rc==0 才存状态，或写库失败在 artifact 上传后让 job 红（cache post-step 就不会存）；错误率 >30% `::error`；cron 改 `7 3 * * 1` + concurrency 组。

**A-09 · Jev ⑤ · 写手侧 MCP 把 Jev key 和暗题带到写手机器** — [代码确认 · 上线前必改]
`judge/mcp_server.py:8-9` 让写手把 `TYPESAFE_API_KEY` 放进 `.mcp.json`；`_client()` 直连 Jev，不经 judge 服务，与 README:24、docs/31 §2.1"密钥只在这个服务的环境变量里"矛盾。暗题在工具输出里有遮，但写手的仓库检出里有 `banks/human_feel_para_v0.2.yaml` + `config/hidden_rotation.yaml` + `judge/hidden.py`（`sha256(qid|quarter)` 确定性），一行能算出 2026Q4 = `{para_friction, para_summary_close}`。`project`/`category` 是工具参数、可覆盖 `JUDGE_PROJECT`（:60-61）→ 出境政策自报。MCP 从不写账本。
修法：MCP 改成 `/judge_draft` 的薄客户端（key 留服务端，project 由 per-writer judge key 钉死），或在 docs/00 #4 接受"暗题只对模型暗、不对人暗"。

**A-10 · Jev ① · 切主抽取会打碎账本** — [代码确认 · 决策项，闸二前不要切]
(1) 没有 workflow 传 `done_by`（features-sync 只发 `{project,limit,dry_run}`，:186-189；D-085 自认"一边忘了就会重抽或空转"）；(2) Jev 不产 `code:v1` / 占位题 / `note_features`，B.3 占位反证对 Jev 笔记为空；(3) `v_feature_contrast` 按 extractor 分裂，半 Opus 半 Jev 的库闸不了；(4) Jev 一次问全部 20 题 + 一次证据（`judge/core.py:134-146`），正是 docs/28 §5.3 禁止的光环模式，证据是整句（`core.py:20`），TV 30 字守卫会判 `evidence_too_long`；(5) vendored 题库 sha 今天一致但无跨仓校验；(6) docs/31 自相矛盾（:122 要闸一过线且有人工锚 vs :289 影子 300 篇就切）。
生产：primary 下 Jev 与 Opus 共存 0 行——还没切，还没碎。

### 2.2 P2

| # | 环节 | 一句话 | 证据 | 生产（10-08） | 修法 |
|---|---|---|---|---|---|
| B-01 | 通道 2 | 饱和灯永远 rc=2，前提已退役 | 视图唯一的杠杆路径是 `notes.note_id = items.external_source_id`（`notes_v1_8:89`），没人写这列（push 没跑过，`deskcore/store.py:1327`"不碰 items.external_source"）；视图头自己说"对照指标…可以下线"（v1_8:40-46） | 8 个池 `lever_measurable_count` 全 0；`external_source_id` 非空 0；血缘替代路径只 1 条 | 退灯：删步、删 docs/29 行、记 DECISIONS；多样性已由 `fingerprint.cap_by_shape` 保 |
| B-02 | 通道 2 | 无再策展路径；卡内容冻结在首次策展 | `/curate` 只转 `limit/project/dry_run`；无 workflow 传 `--recurate/--reannotate`；`library_version` 不含 essence/content 时间；v1_4 的 `updated_at` 触发器/索引"供馆员缓存失效"是死的 | **232 / 306 张卡**的 essence 或正文晚于 `curated_at` | worker 加 `recurate`/`curator_version`；`library_version` 折入 `max(essence_annotated_at)`；改 docs/14:125、v1_5:8 |
| B-03 | 通道 2 | 30 天 prune 会在对比日之前删掉 D-088 的"改前"基线 | `prune_librarian_cache.py:64` 删 `last_hit_at < now-30d`；D-088 让旧键全失效，不会再命中 | 24 行 `select_ms` 基线，`last_hit_at` 09-21 ~ 09-30 → **10-21 起消失**，与"两周后对比"撞上 | prune 排除 `select_ms IS NOT NULL`，并把 24 个数现在抄进 `data-analysis/` |
| B-04 | 通道 2 | 馆员降级对写手 = "没卡"，交通灯怪 autowriter | `app.py` 200 + `status=degraded`，`librarian_client.py:159-181` 只看 `selected`；降级不写缓存行 → `check_librarian_traffic.py:84-88` 打印"通道 2 暗着…修在 autowriter 仓" | `selected='[]'` 缓存 2 行（可被服务一个月） | aw 客户端 `status in (degraded,error)` → `BORROW_ERROR`；TV 把降级计进可查的地方 |
| B-05 | 通道 2 | curate 单请求 15 卡 × 2 次 LLM vs 边缘 300 s → 502 + 锁仍持 → 后面项目全 409 | `worker/app.py:66` 900 s，`daily-sync.yml:87` 边缘 ~300 s；essence 有 `ESS_REQ_MAX=8`，curate 没有；预算只在 200 时扣（:361） | D-088 测到坏日 47–86 s/调用 | `CUR_REQ_MAX≈5` 同 essence 循环，或 worker 异步 |
| B-06 | Jev | 账本写入非事务 | `judge/core.py:258-267` 200 行/批；`api.py:253/314` 无 try → 已付 Jev 钱后 500；`/judge` 200 篇 = 4,000 行 20 批可半写；`verify_supabase_state.sql` #86 只查"有答案无笔记"，不查反向 | 目前 0 半写 | 批失败回滚或记 run 级标记；#86 加反向 |
| B-07 | Jev ⑤ | `project_layer_cleared: []` → 写前题库（brief 现编 / 项目题库）对所有项目全死 | `policy.py:78-79`；aw 不发 `brief` | — | owner 决定：是保密立场还是没设默认 |
| B-08 | Jev ⑤ | deskcore 8 s 死线 vs judge 30 s 超时 × 3 重试 × ≤8 s 退避 | `jev_client.py:77,94-110`；`JUDGE_WORKERS` 只管 `/judge`（`api.py:243`） | 16 次 commit 全在配置前（`not_configured`），配置后 0 次 | judge 暴露 `retries/timeout` 环境变量（1 次 / 6 s）；`/judge_draft` 返回 `calls` 延迟 |
| B-09 | Jev ② | 评论回填 `fetch()` 无分页 | `backfill_comments.py:51-54` 单次 GET `limit=N` | `comments` 9,652 行；`comment_intent/is_scripted/comment_type` **0 行有值**（② 没跑过） | 分页；跑前先 `GET limit=10000` 看 max-rows |
| B-10 | 运维 | 缺 GitHub secret → 永久静默绿 | `daily-sync.yml:114-121` `skip=true` 六个阻塞步全跳；aggregate 认 `skipped` 合法（`ci.yml:5703`）；看门狗只看 `conclusion=success`；`WORKER_URL` 同理（`features-sync.yml:99-102`） | — | `schedule` 事件缺 SUPABASE/WORKER secret 直接红；dispatch 保留优雅跳 |
| B-11 | 运维 | `mask_secrets` 是死代码；R-023"三仓已闭"对 TV/Jev 不成立 | `scripts/_common.py:1182` 定义、0 调用；`:1336` 普通 Formatter；Jev `apply_rows.py:37` 直接打印 `{exc}`；只有 aw 有值掩码（`logger_utils.py:80`） | — | `_common.setup_logging` 装掩码 formatter；CI 断言 ≥1 调用点；改 RISKS |
| B-12 | 运维 | `SUPABASE_SERVICE_ROLE_KEY` 散在 ~10 处、无轮换清单 | TV Actions、Jev Actions、Railway ×6、Vercel；看板 README 说 service_role、代码优先 anon（`lib/supabase.ts:17`） | — | RISKS 加"secret → 每个消费者"矩阵；Vercel 真用 anon |
| B-13 | 采集 | 状态格清空 = 旧爆永久；未映射状态值静默 NULL | 飞书省略空字段（:1759），`transform_row:792` 只在有值时设 `tier` → 保留库值；`状态="已发布"` → `tier=None, tier_source='状态字段'` 无 flag（只有方向有 `direction_unmapped`，:846） | **106 行** `tier IS NULL AND tier_source='状态字段'` | 状态列在 `field_mapping` 且本轮 `seen_cols` 里出现过 → 缺格视为显式 NULL；`data_quality_flags.tier_unmapped` + 计数 + `::warning` |
| B-14 | 采集 | 未来 `publish_time` 不夹，漏到 6 个消费者 | `parse_feishu_date` 放行（`_common.py:750`）；`hours_since_publish` 负数（:1156）；`projects.end_date` 未来；`fetch_pending_baokuan` 12 月窗放行（`ssll:152`）、v1_19 同；`era_tag` 未来季度；aw `tvlink.in_window` 用 `lag_days` | **10 行**，最晚 2026-10-11；0 条在 ssll | `transform_row` 里 `> now()+24h` → 存 `raw_extra._publish_time_raw`、置 NULL、flag；`fetch_pending_baokuan`/v1_19 加 `publish_time <= now()` |
| B-15 | 采集 | 隔离表只写不读、只增不减 | `quarantine_record` ignore_duplicates，首见冻结；唯一读者是 sync 自己的 acked 查询（:987）；无视图/看板/脚本消费 | `undeclared_fields_quarantine`：**5,013 pending / 28 reviewed；2,414 条 pending 的记录在 `notes` 里已经存在**（已修复仍 pending） | upsert 更新 `last_seen_at`；`notes` 里有了自动 `resolved`；每晚 `::notice` |
| B-16 | 采集 | onboarder 校形不校合；合并后无人重读飞书 schema | 校闭集词表、D-021 覆盖；不校 `field_mapping` 右侧是不是真列、不校 `direction_decomposition` 键 ⊆ 实际值、不跑 `_reject_shadowed_tier_rules`；重命名只靠"曾经填过"探针（D-055），`_note_status_raw/_comment_text/_note_for_tier` 不在内（:404-412）；`preflight.yml` 手动 | — | 每周只读 `preflight_mapping.py`；`load_mapping` 断言目标 ⊆ 已知列 |
| B-17 | 特征层 | 闸一裁决无机器可读形式；题库未冻结 | 过 10 / 不过 8 / κ 不可算 2，无 `retired:`、无 `gate1_status`；三道抖动题只有"加样本"没有裁决；`status: draft`、无 `frozen_sha256`；假设里多处 "?" | — | 一条 DECISIONS 逐题 gate-1 status，闸二脚本读它；闸二日 `status: frozen` |
| B-18 | 特征层 | 慢性欠产不可见 | 项目级 transient 只 warning；红要 >½ 饿着；看门狗只看成功；docs/29 无产量灯 | 近 14 天夜增 120/晚 → 10-03 115 → 10-07 **84**，`bad=0`（是 daily 项目在排空，不是故障；D-089 的 24 只对还有存量的项目有意义） | `ok batches < ⌈attempted × LIMIT / (2·REQ_MAX)⌉` → `::error`；docs/29 加日增量灯 |
| B-19 | 写作台 | 补录副本（1,593/30 d）三处漏 | (i) A-02 路径；(ii) `list_projects`"历史成稿指纹数"和 `backfill_gap.eligible` 计入（`legacy_version_pages` 上限 5000）；(iii) Streamlit 审稿页列为 pending（`store.py:1279`） | — | "真写" = `batches.params->>'source' IS DISTINCT FROM 'ingest'` 统一 |
| B-20 | 写作台 | commit 半态目录 + `identity_error` 仍 consume | 指纹无版本（:1685；替换挂接失败旧指纹已删新指纹孤儿 :1596-1617）；版本无指纹（ingest :2970）；`consume_angle` 不看 `minted_ok`（:1633-1647）；`tv_note_links.item_id NULL` 从不修；锁释放失败 → 600 s TTL；`batch_metrics` 插入失败偏 8 s 样本 | 悬空 `consumed_version_id` 0；`item_id NULL` 0 | `if minted_ids.get(i) not in minted_ok and not d.get("version_id"): continue`；其余记入 runbook |
| B-21 | 采集 | 飞书已删的笔记仍喂下游 | `notes_v1_9` 只报不改（:2042）；删后重建得新 `record_id` → 新 `note_id`，无按 `publish_url` 去重 | **TGV 144 · HATHERINE 6 · TUGE 4** 篇 `last_seen_at` 超 3 天且已进 ssll 或已标 essence | 决定 orphan 的下游地位（书架/ssll/L2 是否排除） |
| B-22 | 运维 | `public` 5 张表无 RLS；18 个 `v_dash_*` 是 SECURITY DEFINER | Supabase 安全顾问 ERROR 级 | `public.projects / pipeline_runs / reference_samples / outputs / stage_logs`（anon 可读写？需按 grant 再核）；18 视图 | 开 RLS（ssll 用 service_role 不受影响）；视图改 `security_invoker` 或限 anon 的 grant |
| B-23 | Jev ⑧ | 外部语料周跑的可见性 = 0 | 无 TV 灯看 `v_external_reference` 新鲜度；"绿但空"（A-08 或全 triage 拒）哪里都看不见；邮件只发给最后改 cron 那行的人 | `max(fetched_at)` 10-08 05:13 | docs/29 灯：周二查 `max(fetched_at) > now()-8d` |

### 2.3 P3（短）

- **C-01** `rank_score` 的 `tier_source` 项是常数（书架上只会是 状态字段/备注字段，都 +0.2）；账号项 60/306 用默认 0.3；`personal_bao_rate` 分母含风控/删除、分子含 `数值推断`。实际排序 = tier → recency。
- **C-02** 提示缓存回退不可见：`clients.py:116-130` 任何异常都去掉 `cache_control` 重试并打"疑似不支持 prompt caching"，只进 Railway stdout；`select_ms` 包含最多 6 次重试 + 6 s 退避，D-074 的 p95 掺了重试。`annotate_essence_pass.py:521-532` 同样。
- **C-03** 子方向缺口：NUC 206 篇 `essence_annotated_at` 非空但 `direction_subtype` 空且 `raw_extra ? '_direction_raw'`；只有 `--reannotate` 能补，从没跑过。
- **C-04** 卡住行无死信：essence 按 `note_id` 升序、curate 按 `rank_score` 降序，持续失败的那一篇每晚排头烧预算；JSONL 队列在临时盘。今天实查 stuck essence/curate 都是 0。
- **C-05** 50→24 消费端不破；陈旧文本：`autowriter/docs/deskcore-runbook.md:910`（`CANDIDATE_CAP=50`）、`prompts/flywheel_librarian.md:7`（block1"跨项目共享"）。
- **C-06** 模型环境变量五个名字、响度不一：essence/curate 配错响（404 不重试 → 全败 → 红），馆员配错哑（B-04）；`curator_model` 不在 worker `/health`。
- **C-07** `:pN` 段落行违反 TV `aw_version` 契约（`api.py:312-313`；`verify_supabase_state.sql` #84 会算孤儿）——aw 发 `never` 所以休眠。
- **C-08** 暗题行不可区分、季度按服务器本地时间（`hidden.py:26-28` `date.today()`：Railway UTC vs 写手本地，每季交界 8 h 不一致）；`override: {}`；docs/00 #4"暗题已实现"在生产从未触发。
- **C-09** 题库孤儿：`ssll_critic_v0.1` 无代码引用；`comment_ops_v0.1`、`comment_thread_v0.2/0.3`、`human_feel_para_v0.1` 只有测试用；全部被 `/banks` 列出。
- **C-10** `fq_shadow.py --from-db` 取 `order=note_id&limit=N`，产不出 docs/28 §6.1 的 5 项目 × 30 爆 + 30 趴。
- **C-11** `ingest_target=false` 的映射（RIO ×5、hatherine-QNA，今天加的）：未匹配笔记每晚重匹配写 `unmatched`；`tv_resolve` 抛错（:3857）。judge 用没问题。
- **C-12** judge "shadow" 硬编码（`_judge_block:1236`、`app.py:534`）；要变 enforcing 得加 `decision_source` 值 + TV `_MACHINE_DECISION_SOURCES`。
- **C-13** 看板只读 18 个 `public.v_dash_*`（`lib/dashboard-data.ts:74-91`），v1_19 两列不会出现在 Vercel 上；硬编码 `AI_DIMS=14`、`ARCHETYPES=19`、三个 `SHOWCASE_EXT_*` 合成项目、静态 `TICKER_EVENTS`。
- **C-14** Jev 未配置返回 503，TV 返回 401（`judge/api.py:100`）；deskcore 两个都容忍。
- **C-15** 三个 `ci.yml` 和两个 backfill 无 `timeout-minutes`（默认 360）。
- **C-16** 迁移命名三种口径（`20260920054230`、`notes_v1_17_…`、`aw_008_…`）；README Step 0 守卫只盖 `notes_v1_*`，`dashboard_views_v*` / `security_revoke_*` 无部署清单。生产迁移表今天 66 条，v1_2 ~ v1_19 齐（无 v1_3，文件也不存在）。
- **C-17** 一次性表无过期：`autowriter.versions_num_backup_20260826`（448 kB，08-26 起"可以 drop"）、`truth_vault.reference_samples_backup_tv_stale_20261008`（704 kB）、`notes_ssll_marker_backup_20261008`（72 kB）——D-086 定 ≈10-22 drop；`v_l2_labels_v1` 等闸二；`prepublish_evaluations` legacy-only 仍每晚同步。
- **C-18** `_detect_missing_core_columns` 读库失败 → 守卫静默关（`:476-478`）。
- **C-19** worker 互斥是进程内的；Railway `restartPolicyMaxRetries: 3` 后服务停着，sync 侧会判 systemic 红——可接受，记文档。
- **C-20** `stale_in_ssll` / `gated` / 撤回摘要只打印不断言（`daily-sync.yml:496` `|| true`）；owner 已在 D-087 延后灯。
- **C-21** 文档漂移（挑影响判断的）：`README.md:115,297`"16 项目（9 cron / 7 on_demand）" → 17 / 10 / 7；`:188` 脚本数 72/43/5 → 80/50/7；`:211`"6 个 workflow" → 9；`:213`"20 个 SQL ~v1_10" → 29 个 ~v1_19；`CURRENT_STATE.md` 停在 06-09（cron、每晚篇数都旧）；`RISKS.md` 停在 05-22（R-007 被 D-072 取代，R-023 错）；`docs/00` §3 无 external/judge 路径、"PG17" vs CI PG16、"Railway 3 服务" → 6；aw runbook `:50`"02:00 UTC / 129 runs / 八个迁移" → 02:17 / >180 / 11；Jev README "56 测试" → 69；代码注释 `sync-watchdog.yml:21,121`"180min" → 240、`backfill-*.yml:130,230`"3 次" → 6、`worker/app.py:22`"没设则放行(dev)"、`dashboard-data.ts:6`"只读 v_dash_overview 这一个"。

---

## 3. 生产数据推翻或已关闭的猜测（别再追）

| 猜测 | 实查 | 结论 |
|---|---|---|
| 闸一 C 表灰格修复 `fix_gate1_grey_cells.sql` 没执行过（D-085） | `jev:1.13.0-C` / `gate1-20260928`：1,000 行里 989 非空 | 与"修过"一致，不用追 |
| 外部语料账本可能半写（B-06 反向） | `ext-20261008-0513` 200 篇，每篇恰 24 行（20 fq + 4 triage），0 异常 | 目前干净 |
| mock 行泄漏 | `extractor LIKE 'mock:%'` 0 | 干净 |
| judge ⑤ 已经在写账本 | `aw_version` 0 行；16 次 commit 全是 `not_configured`（配置前）；配置后 0 次 commit | 通电了，**一个生产样本都没有**，§3.8 的影子数据要等写手回来 |
| essence / curate 有卡住的行 | 7 天以上未标 0；未策展 0 | 干净 |
| 账本悬空 `consumed_version_id`（B-20） | 0 | 代码路径存在，生产没踩到 |
| 补录版本无链接 / `tv_note_links.item_id NULL` | 0 / 0 | 干净 |
| B.3 唯一性在新 sha 下有违例 | 0 | 可以钉 `ba0f570c` |
| on_demand 爆款缺 essence（B.3 L2 入口会排除） | NUC 85 · NRT_3 44 · NRT_2 42 · TGV 27 · HXZ_FB 14 · HXZ_QD 4 · TXQ 1 全有 essence | 不是阻碍 |
| v1_19 上线后 stale/gated | stale 全 0；gated 80（= 69 铺评工单 + 11 synthetic） | D-087 postscript 已记 |
| Jev 与 Opus 在 primary 共存 | 0 | A-10 是"将来会"，不是"已经" |
| 今天 237 篇定向回填 | 11:00 UTC 仍有 70 篇爆款无特征（SPX 20 · TGV 19 · RIO 15 · OKMAN 10 · HATHERINE 3 · XIWU 2 · TXQ 1）；run #4 09:50 起仍 in_progress | A 单（on_demand 187）只剩 TGV 19 + TXQ 1；B 单（daily 50）等 11:26 自动触发 |

---

## 4. 跨仓的系统性模式

1. **放行式失败让"空"和"坏"长得一样**：馆员降级 = 没卡；借卡超时 = 没卡；judge 任何错 = `judge_status`；看板缺 key = 全零；缺 secret = 绿；评论步 = 永远 exit 0；外部语料写库失败 = 绿。每一处单独看都是"不阻塞写手"的好意，合起来是：没有一个地方能回答"这段昨晚到底跑了没"。
2. **灯只打印不断言**：饱和灯永远 rc=2、撤回摘要 `logger.info`、`stale_in_ssll` `|| true`、交通灯怪错仓、看门狗只看"有绿"。docs/29 的"没人看的灯就该退掉"原则对这些灯都适用。
3. **时钟没对齐**：cron `02:17` 实际 `08:04–09:00`；`12:47` 实际 `16:45–20:48`；aw 回程 `04:00` 比夜跑早；features-sync 慢一点就越过 `23:41` 看门狗；Jev 周跑整点。
4. **真值被自己人写**：reviewer == author（A-01）；MCP 的 project 自报（A-09）；人工补录 `tier_source` 没有写入路径；`人工` 审稿源头全是模型。
5. **多个快照并存、没有选择器**：题库 sha 两半（A-03）；Jev vs Opus（A-10）；comment reader v0.3 vs v0.4（B-09）；补录副本 vs 真写（B-19）；旧 `_c{n}` 评论 id vs 新哈希 id。
6. **半态只在代码注释里**：commit 的六种半态、ingest 的无 try 循环、worker 的临时盘死信队列、隔离表的 2,414 条"已修复仍 pending"。
7. **文档记的是出发时的样子**：CURRENT_STATE 06-09、RISKS 05-22、README 的计数、runbook 的 02:00——每次决策都进了 DECISIONS，但上游入口文档没人回写。

---

## 5. 建议处理顺序（本文不做，供排期）

1. **先止血（一天内）**：A-01 把 32 条自审改标 + `review_drafts` 加同人/秒级拒绝；A-02 这 31 篇血缘置空 + 匹配索引排除 ingest；B-03 把 24 个基线数抄进 `data-analysis/`（10-21 前）。
2. **再对时钟（一天内）**：A-05 回程 cron 挪到 14:00 UTC；Jev cron 改 `7 3 * * 1` + concurrency；A-08 写库失败要红（10-12 之前）。
3. **闸二能跑之前（一周）**：A-03 的脚本 + 快照口径决定 + on_demand 负例回填；B-17 闸一裁决落 DECISIONS；题库冻结。
4. **写手回来之前（一周）**：A-04 借卡解耦；B-04 降级→`BORROW_ERROR`；A-09 MCP 薄客户端化；B-07 决定项目层。
5. **采集加闸（两周）**：A-06 翻转闸；A-07 评论哈希跳过；B-13/B-14 状态清空与未来时间；B-15 隔离表自动 resolved。
6. **可见性（随手）**：B-10 缺 secret 红；B-01 退饱和灯；B-23 外部语料灯；C-06 `curator_model` 进 `/health`；B-22 public 表 RLS。
7. **文档回写**：C-21 一次性清；DECISIONS 加索引（D-075 已提）。

A-10 不排期：闸二第一次跑完之前不切 Jev 主抽取。

---

## 6. 附录：复核用 SQL（10-08 跑过的，可直接重跑）

```sql
-- A-01 自审
select b.project_id, left(b.id::text,8) batch, count(*) n, min(v.created_at) first_commit,
       min(i.decided_at) first_decided, bool_and(i.reviewer_id=i.user_id) all_self
from autowriter.items i join autowriter.versions v on v.item_id=i.id join autowriter.batches b on b.id=i.batch_id
where i.decision_source='human' group by 1,2 order by 4;

-- A-02 血缘倒挂
select n.project_id, l.match_kind, count(*) from truth_vault.notes n
join autowriter.versions v on v.id=n.source_autowriter_version_id
join autowriter.items i on i.id=v.item_id join autowriter.batches b on b.id=i.batch_id
left join autowriter.tv_note_links l on l.note_id=n.note_id
where b.params->>'source'='ingest' group by 1,2;

-- A-03 快照分裂 / 每项目 2×2 支持度
select left(bank_sha256,8) sha, extractor, run_tag, count(distinct subject_id)
from truth_vault.note_feature_answers where subject_type='note' group by 1,2,3 order by 1,2,3;
select l.project_id, sum(l.y) pos, count(*)-sum(l.y) neg
from truth_vault.v_l2_labels l join truth_vault.note_feature_answers a on a.subject_id=l.note_id
where a.subject_type='note' and a.run_tag='primary' and a.question_id='has_specific_time'
  and a.extractor like 'llm:%' and a.bank_sha256 like 'ba0f570c%' group by 1 order by 2 desc;

-- A-04 借卡延迟 vs 产量
select date(created_at) d, count(*) borrows, count(*) filter (where select_ms>22000) over22s,
       percentile_cont(.5) within group (order by select_ms) p50
from truth_vault.flywheel_librarian_cache where select_ms is not null group by 1 order by 1;
select date_trunc('week',v.created_at)::date w, coalesce(b.params->>'source','ui') src, count(*)
from autowriter.versions v join autowriter.items i on i.id=v.item_id join autowriter.batches b on b.id=i.batch_id
where v.created_at > now()-interval '60 days' group by 1,2 order by 1,2;

-- B-02 陈旧卡
select count(*) from truth_vault.v_flywheel_lesson_cards c join truth_vault.notes n on n.note_id=c.source_note_id
where c.is_curated and (n.essence_annotated_at > c.curated_at or n.updated_at > c.curated_at + interval '1 day');

-- B-03 基线存活
select count(*), min(last_hit_at), max(last_hit_at) from truth_vault.flywheel_librarian_cache where select_ms is not null;

-- B-13 / B-14 / B-15 / B-21 采集
select count(*) from truth_vault.notes where tier is null and tier_source='状态字段';
select count(*), max(publish_time) from truth_vault.notes where publish_time > now();
select status, count(*) from truth_vault.undeclared_fields_quarantine group by 1;
select count(*) from truth_vault.undeclared_fields_quarantine q
join truth_vault.notes n on n.note_id = q.project_id||'_'||q.feishu_record_id where q.status='pending';
select project_id, count(*) filter (where last_seen_at < now()-interval '3 days'
  and (synced_to_ssll_at is not null or essence_annotated_at is not null)) vanished_downstream
from truth_vault.notes group by 1 having count(*) filter (where last_seen_at < now()-interval '3 days') > 0;

-- ⑤ / ⑧ / mock
select count(*) from truth_vault.note_feature_answers where subject_type='aw_version';
select e.run_id, count(*) notes, count(a.subject_id) with_rows from truth_vault.external_notes e
left join (select distinct subject_id from truth_vault.note_feature_answers where subject_type='external_note') a
  on a.subject_id=e.note_id group by 1;
select count(*) from truth_vault.note_feature_answers where extractor like 'mock:%';
```

Actions 侧：`GET /actions/workflows/daily-sync.yml/runs?event=schedule` 看 `run_started_at`（本次 8 条全在 08:04–09:00 UTC）；`features-sync.yml` 同（16:45–20:48 UTC）。
