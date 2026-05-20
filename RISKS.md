# Truth Vault · 生产风险登记 (RISKS)

> 进入生产前会咬人的事，按概率 × 后果排序。每条都说明 (1) 是什么 (2) 后果
> (3) 检测方法 (4) 缓解。owner 列表明拍板人 / 处理人。**任何 high-severity
> 项打开前生产部署应该停**。

最后更新: Session #9 完结时盘点。后续每次 sprint 验收应该 review 这个列表
（加新风险 / 关老风险）。

---

## High severity (必须开打开前解决)

### R-001 · sanshengliubu reference_samples 真实 schema 未对账

- **是什么**: TV 通道 1 sync 写入的列名 (`title` / `content` / `target_audience`
  / `hit_keywords` / 等) 来自 Session #7 代码审查时观察的 ssll codebase。
  没有任何人在最新版 ssll 实例上验证过这套列名仍然存在
- **后果**: TV → ssll sync 启动时 preflight_check 报错，飞轮通道 1 完全不通。
  不影响 TV 主表，但飞轮闭环坏了一半
- **检测**: `scripts/sync_truth_vault_baokuan_to_sanshengliubu.py:preflight_check`
  在脚本启动时跑一次列存在性扫描，无脏数据风险
- **缓解**: Sprint 0 第一次 dry-run 时验证。preflight 失败 →
  对账 ssll schema → 同步更新三处 (build_reference_sample + preflight 必填列
  列表 + docs/09 数据映射表)
- **Owner**: 工程师 (拉 ssll dump) + Ziao (确认列名是否能改)

### R-002 · autowriter schema 迁移需要停机窗口

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

### R-003 · service_role key 泄露

- **是什么**: 所有 sync 脚本用 `SUPABASE_SERVICE_ROLE_KEY`，绕过 RLS。如果
  key 进入前端 / 公共 repo / 日志，攻击者能读写所有 schema
- **后果**: 数据被改写 / 删除 / 外泄，包括 ssll 和 autowriter 用户数据
- **检测**:
  - `_common.get_supabase_client()` 启动校验 JWT role
  - GitHub Secret scanning (默认开启)
  - `.gitignore` 含 `.env`
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

### R-008 · autowriter Memory Manager UI 没有负例 review tab

- **是什么**: `extract_negative_examples_from_autowriter.py` 写 `example_label_proposal`
  列，但 autowriter UI 没有页面让用户 review
- **后果**: 负例候选积压在 DB 里，没人确认 → 永远不会变成 example_label='negative'
  → autowriter build_system_prompt 拿不到负例
- **缓解**: 脚本写明候选数 + 类型，让 Ziao 用 Supabase Dashboard SQL 临时
  review (`SELECT id, ... FROM autowriter.items WHERE example_label_proposal IS NOT NULL`)
  + 写一次性 UPDATE 升级。长期还是要前端
- **Owner**: 前端 (待补)

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
