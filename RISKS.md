# Truth Vault · 生产风险登记 (RISKS)

> 进入生产前会咬人的事，按概率 × 后果排序。每条都说明 (1) 是什么 (2) 后果
> (3) 检测方法 (4) 缓解。owner 列表明拍板人 / 处理人。**任何 high-severity
> 项打开前生产部署应该停**。

最后更新: 2026-05-22 (Session #12 三项目深度审计落地 R-022..R-028, 共 28 条
活跃 + 8 条已关历史). 后续每次 sprint 验收应该 review 这个列表 (加新风险 /
关老风险).

---

## High severity (必须开打开前解决)

### R-001 · sanshengliubu reference_samples schema drift 持续监控

- **是什么**: TV 通道 1 sync 写入的列名集合（v2 "证据包" 列：`post_title` /
  `post_body` / `top_comments` / `platform` / `category` / `ai_analysis` /
  `quality_score` / `source_type` / `content_text` / `title` / `tags` /
  `source_truth_vault_note_id`）。ssll codebase 仍在演化，未来再加列 / 改名
  会让 sync 静默写错位置或被 preflight 拒掉。
- **历史**: 早期（≤ Session #8）误用 v1 legacy 列名 (`title` / `content` /
  `target_audience` / `hit_keywords` / `brand` / `source_url`)，其中 4 列在
  实际 ssll v2 schema 中不存在；如果按那个版本部署，preflight 直接 400。
  当前轮（2026-05）已对账 ssll 仓库 `db/schema.sql` + migrations/005 + 真实
  Postgres 16 实测 INSERT 通过。
- **后果**: 未来 ssll 改 schema 时如未同步更新 TV 端，preflight 失败 → 通道
  1 飞轮坏掉。不影响 TV 主表。
- **检测**: 三层保护:
  1. CI 的 `sanshengliubu sync shape self-check` (Python): 验证
     `build_reference_sample` 输出 keys ⊆ ssll v2 schema 列集
  2. CI 的 `Apply integration migration packs` SQL step: 拿真实 ssll v2
     schema stub 做一次 TV-shape INSERT, 失败即红
  3. `preflight_check` 运行时再核一次 (脚本启动, 无脏数据风险)
- **缓解**: ssll 改列时必须同步五处（同 docs/09 末尾的"重命名 checklist"）。
  生产 dry-run 前先在 staging 上对账一次 ssll 真实 schema。
- **Owner**: 工程师 (CI 守住 drift) + Ziao (协调 ssll 改 schema 时的通知)

### R-002 · autowriter schema 迁移需要停机窗口 ✅ 已关闭 2026-05-22

- **是什么**: 场景 A 部署 (autowriter 当前在独立 Supabase + public schema) 要
  把 5 张表迁到共享 Supabase 的 autowriter schema，期间 autowriter UI 不能写入
- **后果**: 业务侧需要停内容生产 0.5-2 小时。如果不协调强行迁，会丢用户在迁
  移过程中产生的数据
- **检测**: 部署前 `SELECT COUNT(*) FROM public.items WHERE created_at > 'X'`
  在迁移前和迁移后做差值
- **缓解**:
  1. 选择内容生产低谷期（建议周末早上）
  2. 提前 24 小时通知 autowriter 用户
  3. 按 RUNBOOK 跑 pg_dump → restore，再切 config.py 的 SUPABASE_URL
  4. 切完先 read-only 验证 30 分钟再放开写入
- **Owner**: Ziao + autowriter 维护者 (协调窗口)
- **关闭说明 (2026-05-22)**: autowriter 数据已迁到共享 Supabase
  (`kduysqedrclrfevrxiie`) 的 autowriter schema, 验证 40 projects / 3671 items
  / 4425 versions 完整. autowriter 维护者周知迁移完成 (走 007 fresh-install +
  migrate_autowriter_across_supabase.py 路径, 见 MIGRATION_PLAN.md Step 4 ✅).

### R-003 · service_role key 泄露

- **是什么**: 所有 sync 脚本用 `SUPABASE_SERVICE_ROLE_KEY`，绕过 RLS。如果
  key 进入前端 / 公共 repo / 日志，攻击者能读写所有 schema
- **后果**: 数据被改写 / 删除 / 外泄，包括 ssll 和 autowriter 用户数据
- **检测**:
  - `_common.get_supabase_client()` 启动校验 JWT role (含 sb_secret_ / sb_publishable_ 前缀识别)
  - GitHub Secret scanning (默认开启)
  - **Root `.gitignore` 含 `.env` / `*.pem` / `*.key` 兜底**（scripts/.gitignore 只覆盖 scripts/ 一层；根目录有自己的 .gitignore 防止 `.env` 落在 repo 根或其它子目录被 commit）
- **缓解**:
  1. 永远不 commit `.env` (用 `.env.example` 占位)
  2. 生产 cron / Actions 用 GitHub Secrets 注入
  3. 不要在错误日志里 echo 整个 key
  4. 怀疑泄露时立即在 Supabase Dashboard rotate key
- **Owner**: 工程师 (代码层) + Ziao (密钥保管)

### R-004 · Anthropic API 预算超支 / API key 失效

- **是什么**: `annotate_essence_pass.py` 跑 NUC_1 全量 1102 行 ≈ ¥200-400，
  跑全部 ~3,400 条 ≈ ¥700-1500（见 docs/06-essence-annotation.md 估算）。
  没有预算硬阈值
- **后果**: 月底账单意外 / API 限流 / Sprint 1 卡住
- **检测**:
  - 脚本每 100 条会 log 一次进度，按 QPS 限速 (默认 2/sec)
  - Anthropic 控制台有 spending limit (要先设)
- **缓解**:
  1. `--limit 30` 先 pilot, 看准确率
  2. 在 Anthropic console 设硬 spending cap
  3. 按项目分批跑 (NUC → HXZ → RIO ...), 每批之间 review
  4. ESSENCE_MODEL 默认 sonnet (¥0.2/条), opus 仅用于高分歧重标
- **Owner**: Ziao (预算批准) + 工程师 (--limit 控制)

---

## Medium severity (可接受短期, 但要在 Sprint 1 解决)

### R-005 · comment 楼层结构 LLM 重建未实施

- **是什么**: `sync_comments_from_raw_extra.py` 写扁平表，
  `parent_comment_id` 全 NULL。LLM 楼层重建是 D-022 / Q21
- **后果**: ssll vibe_rewriter 拿到的 `top_comments` 是扁平 list，
  抓不到楼主回复 / 楼层互动模式
- **缓解**: NUC pilot 后估算 LLM 重建成本 (Q21)；先用扁平版本上线
- **Owner**: 工程师

### R-006 · sub_directions LLM 子分类未实施

- **是什么**: NUC_phase1 6 个 schema 子方向 (健身减脂 / 关心父母营养 / etc)
  需要 LLM 在 ingest 时分类。当前 sync 只做单方向决定性 lookup
- **后果**: 跨方向分析时 `target_audience` / `user_pain_point` 字段为 NULL，
  必须等 LLM annotation pass 跑完才能查。统计 view 会显示数据 sparse
- **缓解**: D-035 已落档为 Phase 2。配套 `ingest_classification_prompt`
  在 NUC_phase1.yaml 已就绪，Sprint 1 可接通
- **Owner**: 工程师

### R-007 · prepublish_evaluations 永远空

- **是什么**: schema 表 + view 就绪，但无 sync 代码写入。autowriter 不存
  显式评审记录
- **后果**: `v_evaluator_calibration` 永远 0 行，无法判断哪个 evaluator (persona /
  critic) 准
- **缓解**: D-034 已落档为 Phase 2，等 autowriter 加 `evaluations` 表
- **Owner**: cross-team (autowriter 维护者 + 工程师)

### R-008 · autowriter Memory Manager UI 没有负例 review tab ✅ 已关闭 2026-05-22

- **是什么**: `extract_negative_examples_from_autowriter.py` 写 `example_label_proposal`
  列，但 autowriter UI 没有页面让用户 review
- **后果**: 负例候选积压在 DB 里，没人确认 → 永远不会变成 example_label='negative'
  → autowriter build_system_prompt 拿不到负例
- **缓解**: 脚本写明候选数 + 类型，让 Ziao 用 Supabase Dashboard SQL 临时
  review (`SELECT id, ... FROM autowriter.items WHERE example_label_proposal IS NOT NULL`)
  + 写一次性 UPDATE 升级。长期还是要前端
- **Owner**: 前端 (待补)
- **关闭说明 (2026-05-22)**: autowriter 维护者周知 Memory Manager 负例审核
  tab 已在代码完成 (autowriter 仓前端). 负例候选 (example_label_proposal)
  现在能在 UI review → 确认后落 example_label='negative'.

### R-009 · NRT_2 / NRT_3 category (处方药 vs OTC) 未拍板

- **是什么**: 这两个 mapping yaml 现在写 `category: 处方药`，但力克雷 NRT
  系列在国内按 OTC 销售
- **后果**: TV 通道 1 sync 写到 ssll `category = '处方药'`, ssll 检索时
  这两个项目会和真正的处方药混在一起，污染 vibe_rewriter 的样本池
- **缓解**: docs/05-controlled-vocab.md §9 已经标出待 Ziao + 周哥确认。
  这两个项目在 onboard 进 TV 之前必须先决议
- **Owner**: Ziao + 周哥

### R-010 · 飞书 OpenAPI rate limit (50 QPS)

- **是什么**: 默认 50 QPS per app。NUC_1 全量 1102 行单进程 ~5-10 分钟，
  全 6332 行可能 30-60 分钟
- **后果**: 长时间 sync 时其他飞书集成可能被限流
- **缓解**: 脚本已有 `time.sleep(0.1)` 在分页间。如果其他集成抢资源，
  错开时段跑 (深夜 cron)
- **Owner**: 工程师

---

## Low severity (Sprint 2+ 再说)

### R-011 · 蒲公英真实 audience 数据接入路径未实施

- 见 docs/07-audience-data.md。`audience_calibrations` 表就绪但无 sync 脚本

### R-012 · 跨 schema FK 没有 PG 约束

- D-025 决定 source_sanshengliubu_output_id / source_autowriter_item_id 不设
  REFERENCES (部署灵活性)。一致性靠应用层 + view。dangling FK 可能存在

### R-013 · `excluded_directions` 处理粗糙

- 当前对 NRT_3 「女性自发, 男性自发」直接打 tier=数据异常。如果将来出现别
  的飞书错标 pattern, 需要扩展规则

### R-014 · 飞书 record_id 含 `_` 字符的边界

- `note_id = f"{project_id}_{feishu_record_id}"`，飞书 record_id 理论
  上含 `_`。当前用单独的 `feishu_record_id` 列规避反向解析，但仍是脆弱约定

### R-015 · 没有备份策略

- Supabase 有自动备份，但没人定义 RPO/RTO。如果 truth_vault schema 被误删，
  恢复多久？多少数据丢失？

### R-016 · projects / accounts 统计缓存列未自动维护

- **是什么**：`projects.{total_notes, notes_with_data, notes_with_tier,
  notes_with_essence, notes_with_actual_audience, last_sync_at}` 和
  `accounts.{total_notes_count, bao_count, dabao_count, fengkong_count,
  deleted_count, personal_bao_rate}` 都是声明在 schema 里的缓存列，但当前
  没有触发器、后台 job 或 sync 路径去维护它们。
- **后果**：人或 dashboard 直接 SELECT 这些列会拿到 0 / NULL / 旧值，被
  误判为「没有数据」或「项目空载」。
- **检测**：schema 里所有受影响的列已加 COMMENT 'CACHE-ONLY · 未自动维护'，
  Supabase Studio / pgAdmin 会展示该注释；`v_top_performing_accounts` /
  `v_project_tier_summary` / `v_data_health` / `v_flywheel_sync_status`
  是 live-compute 的正确源。
- **缓解**：短期：所有看板/查询切换到上述 view，不要读裸列；中期（Sprint 1+）
  二选一 —— (a) 加 AFTER INSERT/UPDATE trigger 同步缓存，或 (b) 跑一个
  cron 的 refresh job（适合按小时刷新即可的看板）。
- **Owner**：DB / 数据负责人

### R-017 · AutoWriter requirements.txt 无上限, 长期会漂移 [audit 2026-05-22 P2-7] ✅ 已关闭 2026-05-22 (aw: 9 依赖锁上限 + requirements.lock + CI 烟雾)

- **是什么**: AutoWriter 仓 `requirements.txt` 只用 `>=` 没有上限 (`streamlit>=1.30.0`,
  `anthropic>=0.40.0`, `google-genai>=0.5.0`, `supabase>=2.0.0`). 也没有
  `requirements.lock`. TV 自己的 scripts/requirements.lock 已经锁定; 这个风险
  只挂在 AutoWriter 仓.
- **后果**: 任意一次 fresh deploy 或 `pip install -U` 就可能引入 Streamlit /
  Supabase-py / Anthropic SDK 的 breaking change. PostgREST 查询参数, Streamlit
  session_state 行为, Anthropic / Google client 的入参都换过. TV 通道 2 写入
  靠 supabase-py 的 schema-aware client (autowriter/db.py), supabase-py 一升
  小版本就可能让 list_example_items() 的 embedded join 解析失败 —— 飞轮静默断.
- **检测**: 跑 `pip install -r autowriter/requirements.txt && python -c "from autowriter import db; db.get_client()"`
  烟雾测试; 如果 PostgREST schema 选择或 RLS 走不通就报错.
- **缓解**: 在 **AutoWriter 仓** 加上限 + 生成 lock:
  ```bash
  cd autowriter/
  echo 'streamlit>=1.30.0,<2.0' > requirements.txt
  echo 'anthropic>=0.40.0,<1.0' >> requirements.txt
  echo 'google-genai>=0.5.0,<1.0' >> requirements.txt
  echo 'supabase>=2.0.0,<3.0' >> requirements.txt
  pip-compile requirements.txt -o requirements.lock --resolver=backtracking
  ```
  CI 至少跑 `pip install -r requirements.txt && python -c 'import autowriter'`.
  **详细操作步骤 + CI workflow 模板**: `docs/10-sister-repo-followups.md § R-017`
- **Owner**: AutoWriter 维护者

### R-018 · 业务项目用 daemon thread 处理后台任务, 重启即丢 [audit 2026-05-22 P2-8] 🟡 aw Phase 1 已合 (休眠) / Phase 2 + ssll 延后

- **是什么**: AutoWriter `app.py` 的 `_queue_worker` / `_quick_gen_worker` 和
  sanshengliubu `pipeline/orchestrator.py` 的 `_thread_target` 都用
  `threading.Thread(daemon=True)` 在 Streamlit 进程内跑生成 / 流水线任务.
- **后果**: Streamlit 进程被 reload / 容器滚动发布 / OOM 被 kill 时, 正在跑
  的 batch / pipeline run 直接丢. UI 上显示 "running" 但实际死掉; 用户看到
  "偶发卡死".
- **检测**: 在 staging 上启动 batch → 立刻 `pkill streamlit` → 重启后看
  autowriter.batches.status 是否还是 running 但没新 version 进来.
- **缓解**: 在两个业务项目仓库中, 把任务移到 DB-backed job queue. 完整 SQL +
  Python worker 代码 + systemd / supervisor / Render 部署模板 + 4-phase 灰度
  迁移计划 全部在:
  - DDL: `autowriter-migrations/008_jobs_table.sql` (autowriter schema) /
    `sanshengliubu-patches/004_jobs_table.sql` (public schema)
  - 设计: `docs/10-sister-repo-followups.md § R-018`
  - 关键: 用 PG `SELECT ... FOR UPDATE SKIP LOCKED` (封装为 `claim_one_job()`
    RPC) 保证多 worker 副本并发不抢同一行; heartbeat thread 独立于 handler
    线程, 长 LLM call 不阻塞心跳.
- **进度 (2026-05-22)**:
  - ✅ **aw Phase 1 已合** (PR #37 地基 + #38 并发 CAS 修复). 生产
    (`kduysqedrclrfevrxiie`) 已建 `autowriter.jobs` 表 + `claim_one_job` RPC,
    领取机制 (含并发 CAS) 端到端实测过, 测试数据已清. **代码休眠**: 没 worker
    在跑, UI 仍走原线程, 对线上零影响.
    - TV 核查: `autowriter.claim_one_job` EXECUTE 仅 postgres + service_role
      (PUBLIC/anon/authenticated 已 revoke, 沿用 008 的 P1 加固) ✅
    - 注: 生产 RPC 是 SECURITY INVOKER (TV 008 源是 DEFINER) — 因只 service_role
      可调 + service_role bypassrls, 功能等价且更最小权限, 非安全洞.
  - ⏳ **aw Phase 2 延后**: worker 部署 + UI 灰度切换 + 常驻 worker. 触发条件:
    频繁重部署 / 多用户 / 高频高量 / 关浏览器挂着生成. 地基已就绪随时可接.
  - ⏳ **ssll 侧未启**: 见 sanshengliubu `docs/architecture.md` backlog (触发
    条件: 浏览器关闭丢任务变成日常痛点).
- **Owner**: AutoWriter 维护者 + sanshengliubu 维护者

### R-019 · sanshengliubu fresh schema 关 RLS — 单租户假设没写明 [audit 2026-05-22 P2-6] ✅ 已关闭 2026-05-22

- **是什么**: `sanshengliubu-main/db/schema.sql:117-121` 显式 `ALTER TABLE ...
  DISABLE ROW LEVEL SECURITY` 对 5 张主表 (projects / pipeline_runs / stage_logs
  / outputs / reference_samples). 适合 single-tenant MVP, 但部署文档没强调.
- **后果**: 如果 ssll 后续接入第二个客户 / 第二个品牌, 共用同一个 Supabase
  时所有数据互相可见 (anon / authenticated JWT 都能 SELECT * 跨项目).
- **检测**: `SELECT relname, relrowsecurity FROM pg_class JOIN pg_namespace
  ON relnamespace=pg_namespace.oid WHERE nspname='public' AND relrowsecurity=false;`
- **缓解**: 在 **sanshengliubu 仓** 二选一. 决策树 + 完整文案模板 + SQL +
  代码改造步骤都在 `docs/10-sister-repo-followups.md § R-019`. 摘要:
  - (a) **Option A 单租户声明**: README.md 顶部加醒目段, db/schema.sql 在
    DISABLE 语句旁加注释指向 R-019 docs, app.py 启动 banner 显示
    "🔓 单租户模式". 10 分钟工作量.
  - (b) **Option B 多租户 RLS**: 跑
    `sanshengliubu-patches/005_multi_tenant_workspaces.sql` 加 workspace_id +
    ENABLE RLS + workspace-scoped policy. 手工 INSERT workspace_users 行映射
    现有用户. supabase_client.py 注入 workspace_id 到所有 INSERT. TV sync
    在 reference_samples 写入时填默认 workspace_id. 1-2 天 + staging 验证.
- **Owner**: sanshengliubu 维护者 (产品方向决定 a 或 b)
- **关闭说明 (2026-05-22)**: sanshengliubu PR #27 落地 Option A. README.md
  顶部 ⚠️ 警告条 + `db/schema.sql` DISABLE RLS 块上方 13 行 audit 注释
  + `app.py` sidebar `🔓 单租户模式` caption. 三处显式提醒 + 指向 005 多租户
  migration. Option B 未来切换零迷路.

### R-020 · 业务项目超大单文件, 改动成本高 [audit 2026-05-22 P2-9]

- **是什么**:
  - autowriter/app.py: 4,669 行
  - autowriter/db.py: 2,216 行
  - autowriter/memory.py: 2,153 行
  - autowriter/generator.py: 1,724 行
  - sanshengliubu/pipeline/orchestrator.py: 4,146 行
  - sanshengliubu/pages/3_pipeline_detail.py: 1,958 行
  - sanshengliubu/pipeline/agents/__init__.py: 1,602 行
- **后果**: 不是 bug, 但每次改 sync / RLS / sample selection 都容易碰到远处
  副作用. 长期会让 audit / review / 改造成本不断上升.
- **缓解**: 先拆 DB / repository 层和 sync / job 层 (这两块改动频率最高),
  不要先做 UI 大重构. 给拆出的模块补最小单元测试. 保持原入口函数不变,
  逐步迁移. 仍是 Sprint 2+ 工作.
  **完整拆分方案 (autowriter/db.py → autowriter/db/{client,projects,batches,items,
  versions,memories,rls,jobs}.py, memory.py 同理) + 反模式清单 + 暂不拆原因**
  在 `docs/10-sister-repo-followups.md § R-020`.
- **Owner**: AutoWriter 维护者 + sanshengliubu 维护者

### R-021 · 缺 staging E2E 验证 (auth/RLS + 真实 PostgREST join) [audit 2026-05-22 P2/P3-10]

- **是什么**: TV CI 主要是 shape / SQL / fake client 测试, 但 service_role
  写 → owner JWT 读 (真 RLS) 的端到端在 staging 上没跑过.
- **后果**: TV sync 用 service_role 写 batches/items 后, 项目 owner 用真实
  JWT 通过 PostgREST 走 `batches!inner(project_id)` embedded join 是否真能拿
  到 positive examples — 这是飞轮 sync 链路的最后一公里, 静态分析覆盖不到.
- **缓解**: 部署前在 staging Supabase 至少跑一次:
  1. service_role 跑 `sync_truth_vault_baokuan_to_autowriter_items.py --dry-run`
     然后实跑 1 条
  2. 用真实 project owner 的 JWT 走 PostgREST 查 `autowriter.items?select=*,batches!inner(project_id)&batches.project_id=eq.<aw_project>&example_label=eq.positive`,
     验证能查到 step 1 写入的行
  3. 重跑 step 1, 验证 `synced=0, deduped=1` (幂等)
  4. 在 AutoWriter UI 把那个 item 设 `needs_revision`,
     跑 `sync_autowriter_decisions_to_prepublish.py`, 验证 `prepublish_evaluations`
     里出现对应 row, 重跑 → race_skipped=1
- **Owner**: 工程师 (脚本) + Ziao (准 staging Supabase 实例 + 真实用户 JWT)

### R-022 · sanshengliubu vibe_rewriter 没用 DB 样本, 飞轮闭环漏 [audit 2026-05-22 deep-dive P0] ✅ 已关闭 2026-05-22 (ssll PR #27 + #28 都已合)

- **是什么 (audit 原始诊断)**: sanshengliubu `pipeline/prompts/vibe_rewriter.md`
  用 6 条硬编码人物例子做"真人参照", `pipeline/retrieve_samples.py` 虽然能查
  DB 样本但**结果没拼进 prompt**. TV → reference_samples 通路通了, 但 LLM 看不到.
- **复核澄清**: sanshengliubu 维护者复核发现链路其实早就在 (orchestrator
  注入了 reference_packs_by_platform, prompt 里也有"如有必用"指令), 但**有 3
  个隐患让飞轮事实失效**: 静态样本位置喧宾夺主、没 source_type 追溯、0 命中
  无告警. 修复方向正确, 范围有调整.
- **后果**: TV 飞轮存满爆款, sanshengliubu 生成质量不提升. **飞轮架构最大隐患**.
- **进度说明 (2026-05-22)**: sanshengliubu 维护者实施 4 道关卡:
  1. **Prompt 层** (PR #27 ✅): vibe_rewriter.md PRIMARY/FALLBACK 分层 +
     **三态决策表** 强制 LLM 在 rewrite_summary 写 `源:数据库样本 #<id>`
     或 `源:静态兜底 #<编号>`
  2. **检索层** (PR #27 ✅): retrieve_samples 加 source_type (truth_vault/manual) +
     summarize_packs_by_platform; 0 packs 升 WARNING
  3. **注入层** (PR #27 ✅): orchestrator vibe_loop 把 reference_packs_summary
     推到 critic / structural_rewriter / vibe_rewriter 三处
  4. **运行时审计 + 持久化** (PR #28 ✅ 已合):
     `_audit_rewrite_source_tags` 每 iteration 跑, findings 落 `stage_logs`
     (stage_name='r022_flywheel_audit'), per-platform 配额规则防包用尽误报,
     unicode 冒号也支持. TV 跨仓监控基础设施就位.
- **代码层面已关闭**: 4 道关卡全部在 ssll main, 飞轮 prompt + 运行时 audit +
  持久化都跑得起来.
- **生产验证 gate (待 ssll vibe_loop 首次真跑)**: 2026-05-22 用 Supabase MCP
  查 `SELECT COUNT(*) FROM public.stage_logs WHERE stage_name='r022_flywheel_audit'`
  得 0 行 — 预期, ssll 还没在生产跑过 vibe_loop. 下次真跑后这条 SQL 应该出现
  行, 且 `output_data->>'db_sourced'` > 0 表明飞轮真的命中. **0 行不代表 bug,
  代表还没跑数据**.
- **TV 侧 follow-up**: 飞轮真启用后, 加 `scripts/check_flywheel_health.py` 或
  在 `verify_supabase_state.sql` 加新 J 节查 `r022_flywheel_audit.completed_warn`.
  SQL 模板见 `docs/10-sister-repo-followups.md § "TV 日报跨仓查 R-022 audit"`.

### R-023 · 3 项目 logger 没 mask secret [audit 2026-05-22 deep-dive P1] ✅ 已关闭 2026-05-22 (3 仓全)

- **是什么**: API key (sk-ant-* / sb_secret_* / AIza* / JWT) 可能出现在
  logger.exception / Streamlit 错误 expander / telemetry 事件参数里.
- **后果**: 日志被运维查看 / 上传到第三方平台 / 截图发群时, secret 外泄.
- **关闭说明 (2026-05-22, 3 仓全)**:
  - TV: `scripts/_common.py::mask_secrets()` (7 模式)
  - ssll: PR #27 `pipeline/logger_utils.py` (7 模式 shadow-aligned) +
    `install_secret_masking_on_root_logger()` 启动挂 root logger formatter
  - aw: `logger_utils.mask_secrets` (7 类) 接入日志 + UI 错误展示 (autowriter
    维护者周知完成)
- **Owner**: 已完成.

### R-024 · autowriter worker 多次启动重叠 + stacktrace 泄漏 [audit 2026-05-22 deep-dive P1] ✅ 已关闭 2026-05-22 (重复启动已被 phase 状态机阻止 + 错误脱敏并入 R-023)

- **是什么**: autowriter `app.py:3004` 的 daemon worker 没有"单例校验",
  用户快速点击多次启动按钮会启动重叠 worker 抢同一 batch; `app.py:2332`
  把 traceback.format_exc() 直接展示到 UI expander.
- **后果**: 重叠 worker 浪费 token / 状态机错乱; stacktrace 泄漏内部路径 + API key.
- **缓解**: R-018 (jobs+worker) 是终极方案, R-024 是短期止血. 完整代码见
  `docs/10-sister-repo-followups.md § R-024`.
- **Owner**: autowriter 维护者. 工时 2 小时.

### R-025 · autowriter prompt 用户输入直拼, 无 token 上限 [audit 2026-05-22 deep-dive P2] ✅ 已关闭 2026-05-22 (aw: 输入截断 + [USER_INPUT] 围栏 + 注入防御)

- **是什么**: `generator.py:61-118` 把用户表单输入 (tactic / target_audience /
  extra_instructions) 直接拼进 system prompt, 无 escape 无字符上限.
- **后果**: 自家用风险低. 未来开放给客户/团队成员填表单时, 可被 `<!-- system:
  ignore previous -->` 注入越权; 长 calibration_notes 把总 token 推过模型上限
  导致生成截断.
- **缓解**: 用 `[USER-FIELD-*]` 标记边界 + 硬上限 8000 字 + system prompt 头部
  防注入声明. 见 `docs/10-sister-repo-followups.md § R-025`.
- **Owner**: autowriter 维护者. 工时 3 小时.

### R-026 · 3 项目 LLM 调用 retry framework 不统一 [audit 2026-05-22 deep-dive P2] ✅ 已关闭 2026-05-22 (ssll Claude 统一留 R-026.2)

- **是什么**: TV `annotate_essence_pass` 有 max_attempts + backoff, sanshengliubu
  `pipeline/orchestrator.py` + autowriter `generator.py` 调 LLM **没看到 retry**.
- **复核澄清**: sanshengliubu 复核发现 Claude 调用其实在 `BaseAgent.run()`
  已有 MAX_RETRIES + 指数退避 (3 次 / 3s 基底). 但 **Gemini 调用裸跑**, 429/503
  直接挂条 vibe_loop.
- **后果**: LLM 服务 429/5xx 瞬时抖动时, sister-repo 直接挂掉整个 batch /
  pipeline run, 用户看到 "Anthropic overloaded" 失败但其实只是临时.
- **关闭进度**:
  - ✅ TV: `annotate_essence_pass.call_claude` 已有 max_attempts + backoff
  - ✅ ssll Gemini: PR #27 加 `pipeline/llm_retry.py` (max_attempts=3,
    max_wait=30s, `_is_transient` 覆盖 429/503/504/timeout/overloaded 等) +
    `gemini_client.call_gemini_json` 包重试
  - ✅ autowriter: 8 处此前裸调的辅助 LLM 调用已补重试 (autowriter 维护者周知)
  - ⏳ ssll Claude 路径: 保留 BaseAgent.run() 独立 retry (4 项耦合状态机:
    retry + budget + rate limiter + cache-fallback). 统一迁移留给 **R-026.2**
    (触发式延后, 非 R-026 主体范围). 这是 R-026 唯一剩余尾巴, 不阻塞关闭.
- **跨 backend 设计选择**: 详见 sanshengliubu `docs/architecture.md §1`
  对照表 + 不统一理由. 未来触发条件: 第三个非 Anthropic backend / 全局重试
  可观测 / BaseAgent.run() 改动频繁.

### R-026.2 · sanshengliubu BaseAgent.run() 重试迁到 llm_retry [Sprint 2+]

- **是什么**: PR #27 落地 R-026 时只把 Gemini 加了独立 retry. Claude /
  DeepSeek / OpenAI 走 `BaseAgent.run()` 内嵌的 4 项耦合状态机 (retry + budget
  + rate limiter + cache-fallback). 跨 backend 重试参数和日志格式不统一.
- **后果**: 跨 backend 调试时"为什么 Claude 等了 3s, Gemini 等了 30s" 类型
  问题查起来要看两套代码; 未来加全局重试可观测困难.
- **缓解**: 把 BaseAgent.run() 重试逻辑迁到 `pipeline/llm_retry.py`. 需要先
  把 budget / rate limiter / cache-fallback 拆出来或保留, 再统一 retry 入口.
- **触发条件** (sanshengliubu `docs/architecture.md §1` 末尾):
  - 出现第三个非 Anthropic LLM backend (e.g. 直连 Mistral)
  - 运维要"全局重试可观测", 需要统一日志格式
  - `BaseAgent.run()` 自身改动频繁, 维护重试逻辑成本超过迁移成本
- **Owner**: sanshengliubu 维护者. 工时 1-2 天 + e2e 测试.

### R-027 · autowriter update_project 列漂移静默 strip [audit 2026-05-22 deep-dive P3] ✅ 已关闭 2026-05-22 (aw: 改为 UI 显式告警)

- **是什么**: autowriter `db.py:477-505` 撞到"列不存在"会剥掉那列再 retry, 只埋
  telemetry, **用户在 UI 设了值但 DB 没生效, 无明显错误提示**.
- **后果**: schema 滞后时 UI 行为不符预期, 运维只能从日志反查.
- **缓解**: 加 `st.warning` + 显式 logger.error. 见 `docs/10-sister-repo-followups.md § R-027`.
- **Owner**: autowriter 维护者. 工时 1 小时.

### R-028 · sanshengliubu 单 stage 失败必须整 pipeline 重跑 [audit 2026-05-22 deep-dive P3]

- **是什么**: 复合 stage (strategy_loop / vibe_loop) 内部 cell 失败时, resume
  会重跑前面已成功的 cell, 浪费 LLM token + 时间.
- **后果**: 单 stage 偶发抖动 → 整 pipeline 重跑 → 时间和成本翻倍.
- **缓解**: stage_logs 加 cell_status JSONB + resume 时 skip 已 success 的 cell.
  见 `docs/10-sister-repo-followups.md § R-028`.
- **Owner**: sanshengliubu 维护者. 工时 1-2 天.

### R-029 · autowriter RLS policy auth.uid() 每行重算 [Supabase advisor 2026-05-22 auth_rls_initplan] ✅ 已关闭 2026-05-22 (TV 即时修 + aw 源码同步)

- **是什么**: Supabase perf advisor 报 `autowriter.generation_sessions`
  (`generation_sessions_owner`) 和 `autowriter.session_messages`
  (`session_messages_owner`) 的 RLS policy 每行重新求值 `auth.uid()`.
  包成 `(select auth.uid())` 后 PG 当 initplan 只算一次.
- **后果**: 大规模时 RLS 检查慢. 当前 60 / 1244 行影响还小, session_messages
  会随使用持续涨.
- **已做 (TV 侧即时修复)**: 2026-05-22 用 Supabase MCP apply_migration 把两个
  policy 就地改成 `(select auth.uid())`, advisor 2 个 auth_rls_initplan WARN
  已消失. 零行为改变.
- **✅ aw 源码已同步 (2026-05-22)**: autowriter 维护者把全 10 表 11 处 RLS
  policy 的 `auth.uid()` 都包成 `(select auth.uid())` 写进源码, 重跑 bootstrap
  不会再 regress. TV 复查生产: `generation_sessions` / `session_messages` 两个
  policy 确认是 `(select auth.uid())`, advisor auth_rls_initplan 清零.
- **✅ 顺带 unindexed_fk 也修了**: autowriter 维护者建了 8 个 FK 覆盖索引,
  advisor unindexed_foreign_keys 对 autowriter 表清零 (TV 复查: autowriter
  schema FK 覆盖索引 11 个).
- **Owner**: autowriter 维护者 (已完成).

### R-030 · TV 一堆 unused_index advisor (INFO) — 预期, 不处理 [Supabase advisor 2026-05-22]

- **是什么**: Supabase perf advisor 报 truth_vault 几十个 index "unused".
- **后果**: 无. **这是预期**: TV 14 张表现在全 0 行 (飞轮还没跑数据), 没有
  query 命中过这些 index, 所以全标 "unused". 它们是按 sync 脚本 + view 的
  查询模式设计的 (note_id / project_id / tier / publish_time / GIN 等), 数据
  一进来就会被用上.
- **缓解**: **不要删这些 index**. 飞轮启用 + sync 跑过几轮后重新看 advisor,
  真正一直 unused 的 (比如某个从没被查的列) 再单独评估. 现在删等于自废武功.
- **Owner**: 无需 action. 记录在案防止有人看到 advisor 就手贱删索引.

### R-031 · 飞书 lineage 列未接通 notes FK (docs/11 文档化时发现) [2026-05-22]

- **是什么**: docs/11 描述 autowriter 回灌要在飞书表加 6 个 `_source_autowriter_*`
  lineage 列, 但当前 sync 脚本未声明这些列 → 加了会 quarantine 整行; 即使列进
  `project_specific_fields_to_raw_extra` 也只落 raw_extra, 不填
  `notes.source_autowriter_item_id` / `source_autowriter_version_id` FK 列.
- **后果**: 现状下 lineage 列要么搞坏 ingestion, 要么数据存了但 `v_model_comparison`
  仍空. docs/11 已加 🚫 警告 "先别加这 6 列" + 临时办法 (列进 raw_extra allowlist).
- **缓解**: sync 脚本 `transform_row` 加 lineage 列 → FK 列的特殊处理. 完整代码
  + 验证见 `docs/10-sister-repo-followups.md § R-031`.
- **Owner**: TV 维护者. 工时 2-3 小时. P3. 触发条件: 真跑 autowriter "AI 写→
  人工审→发布→飞书回收" 完整闭环时.

---

## 已关闭风险 (历史档案)

### R-X01 · sanshengliubu reference_samples 字段映射文档/脚本冲突 [已关 Session #9]

doc 09 写 `post_title / post_body / quality_score`, 脚本写 `title / content`. Session #9 用 `preflight_check` 锁定为脚本权威, 文档已对齐. 见 commit `e331551`.

### R-X02 · autowriter sync 失败留下脏数据 [已关 Session #9]

`insert_synced_item` 先插 items 再插 version, 中间失败 dedup 分支直接 mark synced. Session #9 `_ensure_version_and_link` + 显式 dedup 恢复逻辑修复. 见 commit `77c4506`.

### R-X03 · Mode A label leakage 校验误伤正常文案 [已关 Session #9]

旧校验扫整个 prompt 含 title/body. Session #9 拆白盒: 只校验 template + project_context. 见 commit `77c4506`.

### R-X04 · ingested_at 被 UPSERT 覆盖 [已关 Session #9]

schema DEFAULT NOW() 只在 INSERT 触发, UPSERT 重置. Session #9 加 `preserve_ingested_at` trigger + 客户端不再传字段. 见 commit `77c4506`.

### R-X05 · Supabase 1000 行回包上限静默截断 [已关 Session #9]

所有 fetch 路径加 `fetch_all_pages()` 分页. 见 commit `d592498`.

### R-X06 · service_role key 检测启发式不可靠 [已关 Session #9]

Session #9 改 base64 解码 JWT payload 校验 role claim. 见 commit `d95137f`.

### R-X07 · sanshengliubu-patches / autowriter-migrations 目录缺失 [已关 Session #9]

final ZIP 漏了, Session #9 补回完整目录 + RUNBOOK. 见 commit `7d338c4`.

### R-X08 · 负例 Source A/B 查询过宽 [已关 Session #9]

Source A 旧逻辑只看 "有 manual 且 有非 manual" 不管时序; Source B 旧逻辑只看
feedback 非空不管是否有前一版. Session #9 都加了 version_num 严格小于的校验.
见 commit `77c4506`.

### R-X09 · C 家族 (TGV/QSHG) tier 抽取断链 [已关 Session #9]

sync 脚本只查 `_status_raw`, 不查 `_note_for_tier` (备注字段). TGV_1 的 47 条
「新爆」全部 tier=NULL. Session #9 根据 mapping 的 `tier_extraction.source` 动态选择.
见 commit `b4218f6`.
