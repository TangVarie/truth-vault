# Truth Vault · 当前状态

**最后更新**: 2026-05-20（Session #8.5 审计修复 + Session #9 review 修复）
**当前阶段**: 阶段 0 · 设计完成 → Session #9 review 修复 → **Sprint 0 主链路就绪（含已知 gap）**
**当前会话编号**: #9（三轮审计 + 用户 review 8 条问题修复：autowriter recovery / label leakage 白盒 / source B prior version / ingested_at 保留 / 集成补丁包 / 含 gap 的 Sprint 0 scope 明确）

---

## Sprint 0 实测能跑什么 / 不能跑什么 ⭐ 明确边界

Sprint 0 的目标是**主链路上线 + 飞轮通道接通**，不是完整三层标注闭环。

**Sprint 0 可以跑（已实现 + 通过烟测）**:
- ✅ 飞书 → TV notes 主表 sync（含 quarantine + tier 抽取含 C 家族 + 数值兜底 + 单方向 direction_decomposition 确定性映射 + excluded_directions 标 数据异常）
- ✅ TV 爆款 → sanshengliubu reference_samples sync（含 preflight + 列名 reconcile + idempotency dual-path）
- ✅ TV 爆款 → autowriter items sync（含 transactional recovery + JWT 校验）
- ✅ autowriter 负例候选挖掘（Source A/B 修正版 + 全分页）
- ✅ 跨 schema views（v_prompt_performance / v_model_comparison / v_top_performing_accounts 直查 notes）
- ✅ Schema 全部 CHECK 约束 + ON DELETE 语义 + ingested_at trigger 保护

**Sprint 0 暂不闭环（已知 P1 gap）**:
- 🚧 **direction_decomposition.sub_directions**：NUC_phase1 6 个子方向（健身减脂 / 关心父母营养 / 产后宝妈 / 照顾家人手术 / ...）需要 LLM 子分类才能落到 schema 字段；当前只保留 `_direction_raw` 到 raw_extra，独立 annotation pass 必须做。`ingest_classification_prompt` 在 NUC_phase1.yaml 已就绪。
- 🚧 **essence + audience LLM 标注**：Mode A 双模式 prompt 已 finalize（v0.3 含白盒 leakage 校验），但没有调用脚本（不在 sync 脚本里跑）。需要独立 annotation pass 脚本读 `notes.emotional_lever IS NULL` 然后批量标注。
- 🚧 **comments 表 sync**：飞书的「随贴评论」「随贴评论素人」是文本块，需要 LLM 重建楼层结构（D-022 / Q21）。当前 sync 脚本只把这两个字段塞进 `raw_extra`，不写 `truth_vault.comments`。ssll 通道 1 的 `top_comments` 因此为空（用兜底空数组）。
- 🚧 **prepublish_evaluations 写入路径**：表 + view 都已就绪，但没有 sync 代码会写入。`v_evaluator_calibration` view 当前永远空。可以等 Sprint 1 第二轮再接通。
- 🚧 **autowriter Memory Manager UI 负例 review tab**：脚本写 `example_label_proposal`，但 autowriter 前端没接。proposal 不污染 negative pool（这是设计），但需要前端工作。

**Sprint 0 验收标准**:
1. NUC_phase1 飞书 1102 行能进 TV，无 quarantine 误判
2. NUC_phase1 爆款（24 大爆 + 20 爆）能进 ssll reference_samples + autowriter items
3. 至少 1 个项目跑通 Source A 负例抽取并人工 review > 0 个候选
4. 跨 schema view 不报错（即使 prepublish_evaluations 为空也算通过）

---

## Session #10 关键产出 ⭐

**主题**: 全系统架构 + 跨仓库对接 review，从"代码能跑"推进到"飞轮能转 + 知道哪里会出问题"。

**5 个并行 Explore agent 全维度审查**（Python / SQL / CI / 安全 / 文档）：
- 共发现 ~36 个问题，按 P0 / P1 / P2 / 延后 / declined 分类处理
- 详细 fix vs 延后 vs declined 的总账分布见下表

**跨仓库对接 review**（基于用户上传的 sanshengliubu / autowriter 最新 zip）：
- 发现 ssll 实际 v2 schema 与 TV 写入 shape 完全不匹配（5 列不存在）
- top_comments 形状错（list[str] vs ssll 期望的 list[{text, likes?}]）
- docs/09 把 v1/v2 列名解释反了
- README "三个调用方"仍是 v1 (D-023 HTTP REST) 框架
- 全部对齐 ssll 真实 v2 schema 后 sync 才真正能跑

**架构层 review**（你的"无脑灌 positive 例子撑爆 prompt" 关切）：
- 通道 2 注入策略原本是"全量灌 + autowriter 按 created_at 取 5"——选择/相关性/多样性全无
- 提出 4 阶段 ML iteration plan（评估框架 / embedding rerank / contrastive adapter / 小模型）
- 小团队约束下收敛到"用现有字段做 weighted ranking + diversity 软约束 + 自动退役"——无新基础设施、无人工依赖

**已落地 fix 总账**（7 个 commit, 26 项）:
- `1e09eec` P0 数据正确性 3 项（autowriter best_version_id 重对账 / PostgREST or_clause 拆分 / quarantine partial UNIQUE INDEX）
- `df7f19a` P1 LLM pipeline 强化（API retry / payload size cap / fcntl flock）+ 类型守卫（tier_source 白名单 / isinstance feedback）
- `d1adcbd` P2 文档同步 + metric_snapshots 索引 + 4 项新 CI 测试
- `d7636dc` ssll v2 schema 真对齐
- `2ef5bf8` docs/09 v1/v2 倒置纠正 + README 双通道 framing + ONBOARDING/RUNBOOK 硬前置提醒 + RISKS R-001 更新
- `e5d266a` D-036: v_autowriter_injection_candidates view + diversity + retire + ssll hygiene + preview tool
- `9cc23cd` daily-sync workflow（manual 起步、secrets 配齐后取消注释 schedule）+ 延后清单 19 项含触发条件

**延后但记账了**（CURRENT_STATE.md 延后清单分 4 类共 19 项）:
- 🟡 慢性病 10 项（触发就必须做：tier 阈值自适应 / essence vocab v0.3 / 饱和度监控 / autowriter 双池 / metric_snapshots 时序 / prepublish_evaluations / comments 楼层 / Memory Manager UI / 依赖锁 / 跨 schema 审计）
- 🔵 能力扩展 5 项（规模到了做：pgvector rerank / 静态检查 / Slack webhook / RLS / 评论脱敏）
- ⚪ 可能不做 3 项（仅备忘：微调小模型 / backtest framework / pytest 框架）
- 🟣 远期 1 项（跨项目 essence 知识迁移）

**review 后判定不做**（在对应 commit message 里有理由记录，备忘）:
- Prompt injection via `.format()` 花括号 → `str.format()` 不递归解析替换值，无 Python 层注入面
- `_iso_now()` 时区冗余 → 实际已经是单链调用
- UUID 校验晚于 fetch → 实际代码已经在 fetch 前校验
- ONBOARDING Day 2 cd scripts/ 命令 → 已经在 scripts/ 下，命令本身没问题
- JSONB GIN 全加索引 → Agent 过度建议，无证据这些列被按内容查
- `.env.example` JWT 占位符 → 仍是占位符不是真实 key
- RISKS R-003 启动校验缺失 → Agent 误判，`_common.py` 已经校验

**接手时需要做的事**（不立即跑也行，但要意识到）:
1. 配 GitHub Secrets (SUPABASE_URL / KEY / FEISHU_APP_ID/SECRET / AUTOWRITER_SYNC_USER_ID) → 取消 `daily-sync.yml` 注释里的 schedule → cron 自动跑起来。步骤详见 `.github/workflows/daily-sync.yml` 顶部注释。
2. 第一次切到新 sync 策略之前用 `python scripts/preview_injection_candidates.py --project NUC_phase1` 看一下输出顺不顺眼。说明见 `scripts/README.md` "注入策略预览" 段。
3. 任何"做着做着觉得不对劲"或"想起一个潜在风险" → 加进 延后清单 + 写触发条件 + **不立即开工**。判断属于 🟡/🔵/⚪/🟣 哪一类。

---

## Session #8 关键产出 ⭐

**全部审计修复**（接续 Session #7 设计）:
- **P0 文档扫荡**: v1.1 → v1.2 引用全清；素人编号 → account_id；02-schema-v1.md 重写
- **P1 autowriter 修复**: DDL 顺序 + POLICY 语法 + list_example_items 50-batch 窗口 + external_source 强幂等 + exporter lineage + B1 schema 迁移
- **P2 业务逻辑硬伤**: negative example 3 个来源 SQL 全部修正 + metric_snapshots 加 window_label/UNIQUE + category 受控词表
- **P3 命名整理**: notes 表 aw_item_id → synced_autowriter_item_id

**真实可跑代码**（不是 spec）:
- `truth-vault/scripts/` 4 个 Python sync 脚本 + `_common.py` 共享工具
- `sanshengliubu-patches/` 001_add_source_tv_note_id.sql + import_truth_vault_baokuan.py + README（**Session #9 补回 final ZIP 漏掉的目录**）
- `autowriter-migrations/` 001_create_autowriter_schema.sql + 002_add_external_source.sql + 003_add_example_label_proposal.sql + RUNBOOK（**Session #9 补回**）

**Session #9 review 修复（用户反馈 8 条 + 我自己 review 后续）**:
- ✅ Issue 1 · 补回 sanshengliubu-patches/ 和 autowriter-migrations/ 目录
- ✅ Issue 2 · autowriter sync 失败恢复（dedup 分支补齐 version + best_version_id）
- ✅ Issue 3 · 负例 Source B 加 prior-version 校验（同 Source A 模式）
- ✅ Issue 4 · Sprint 0 scope 含 gap 明确（本节）
- ✅ Issue 5 · Mode A label leakage 改为白盒（只校验 template + project_context，不扫 title/body）
- ✅ Issue 6 · reference_samples 字段映射 reconcile（doc 09 对齐 script，加 preflight）
- ✅ Issue 7 · service_role JWT payload 解码校验（取代弱启发式）
- ✅ Issue 8 · ingested_at 保留（DB trigger + 客户端不传）
- ✅ 附加 · C 家族 tier 抽取（_note_for_tier）/ 全 fetch 分页 / Source A 时序 / TIMESTAMP TZ / 数值 tier 兜底 / direction_decomposition 确定性部分 / parent_comment_id ON DELETE / category CHECK / tier_thresholds 默认值移除 / 模型 ID 更新

**Session #8 三轮审计**:
- 第一轮: P0/P1/P2/P3 共 11 条 issue 全部修复
- 第二轮: end-to-end 完备性、文档矛盾、SQL 复制可执行性、service_role 强制、Excel 工作流闭环等 11 条
- 第三轮: quarantine schema 不匹配 / accounts FK 没建 / comments schema 错 / dedup UUID 错误 / sanshengliubu 必需列等 6 条硬 bug + 3 条次级

### Session #7 历史产出（保留供参考）

**代码审查**（Ziao 上传两个仓库的最新分支）:
- sanshengliubu (v0.30.10) - Prompt 生产管线，30+ 版本迭代
- autowriter (v2.7.9-studio) - XHS 内容工作台
- 发现两个项目都比 v1.1 假设的成熟得多
- 发现 v1.1 设计的部分功能（prompt_versions / generation_runs / content_candidates）与现存系统重叠

**架构调整 · v1.1 → v1.2**:
- **D-024**: 双通道集成模式取代 HTTP REST API（D-023 作废）
- **D-025**: 简化 D-016 生成过程数据 layer（删除 3 张冗余表）
- **D-026**: 历史数据回流策略（飞书 notes 必须 + autowriter 扫一次取 negative + sanshengliubu 跳过）
- **D-027**: Negative example 来自用户修改/淘汰行为

**新文档**:
- **docs/09-system-integration.md v2** - 重写为双通道直接喂数据模式
- **schemas/notes_v1_2.sql** - 简化 schema（删除 3 张冗余表 + 新增跨系统 FK）

### Session #8.5 审计修复产出 ⭐

**Prompt 层 label leakage 修复 (D-028)**:
- `prompts/essence_annotator.md` v0.2 → v0.3：物理拆分 Mode A / Mode B
- Mode A prompt 不含 `{performance_context}` 占位符——从代码层面杜绝泄露
- 调用代码含硬校验 assert（prompt 中不允许出现 tier 等关键词）
- 模型 ID 从 prompt 移到配置层（不再硬编码 `claude-sonnet-4`）

**SQL 部署拆分 (D-029)**:
- `notes_v1_2.sql` → 纯 truth_vault 表+内部 views（无外部依赖，可独立执行）
- `notes_v1_2_cross_schema_views.sql` → v_prompt_performance + v_model_comparison（需三个 schema 就绪）

**文档一致性修复**:
- doc 09 的 view 定义对齐到 SQL canonical 版本（修复列名/JOIN/过滤条件不一致）
- 受控词表 tier 7→8（补入 `数据异常`，对齐 SQL CHECK）
- `comment_intent` 加 CHECK 约束（D-031）
- `accounts.notes_text` → `account_memo`（D-032）
- `notes_archive` 加 `account_id` + `publish_time` 索引（D-030）
- `audience_inferrer.md` 模型引用改为配置层
- `_common.py` 补齐缺失的 sentinel token（em dash `—` / `/无`）
- doc 08 roadmap API 端点改为 sync/view/UI 口径（对齐 D-024）
- DECISIONS.md 补录 D-028~D-033

### 双通道集成核心

```
                  ┌─────────────────────────┐
                  │ Truth Vault notes (爆款) │
                  └────────────┬────────────┘
                               │
              ┌────────────────┴────────────────┐
              ▼                                 ▼
┌──────────────────────────┐  ┌──────────────────────────┐
│ 通道 1                    │  │ 通道 2                    │
│ sanshengliubu.            │  │ autowriter.items          │
│ reference_samples         │  │ (example_label='positive')│
│                           │  │                           │
│ → retrieve_reference_packs│  │ → build_system_prompt     │
│ → 注入 vibe_rewriter      │  │   (positive_examples=...) │
│   (高权重)                 │  │ → 注入 system prompt      │
│                           │  │   (高权重)                 │
└──────────────────────────┘  └──────────────────────────┘
   sanshengliubu 加 ~30 行           autowriter 已完成 P1 一次性改造
   (import_truth_vault_baokuan)       (DDL 修复 + schema 迁移 +
                                       list_example_items + lineage 元数据)
```

### 已完成（v1.2 含）✅

- [x] 10 个项目数据审计
- [x] 三层架构（Surface / Essence / Audience）
- [x] 四层系统架构
- [x] Schema v1.2 设计（13 张表 + 跨 schema views）
- [x] 三个家族的映射协议
- [x] 新项目 onboarding SOP
- [x] 受控词表 v0.2
- [x] Essence 标注双模式 prompt
- [x] NRT_phase3 / NRT_phase2 / NUC_phase1 mapping yaml
- [x] **代码审查 sanshengliubu + autowriter** ⭐ Session #7
- [x] **双通道集成架构** ⭐ Session #7
- [x] **三个 sync 脚本完整 spec**（在 09-system-integration.md）
- [x] 关键决策落档 D-001 ~ D-027
- [x] **P0 文档扫荡**（v1.1 → v1.2 全清，note_id / account_id 命名干净）⭐ Session #8
- [x] **P1 Sprint 1.1**：autowriter DDL 修复 + list_example_items 重写 + external_source 去重列 + exporter lineage 元数据 ⭐ Session #8
- [x] **P1 Sprint 1.2**：autowriter `get_client()` 改 ClientOptions(schema='autowriter') + 数据迁移 SQL + RUNBOOK ⭐ Session #8
- [x] **P1 Sprint 1.3**：09-system-integration.md "零代码改动" 措辞更正 + sync spec 用 external_source 强幂等键 ⭐ Session #8
- [x] **P2 四**：negative example 3 个来源的查询逻辑修正（manual rewrite 走 ai_engine='manual'；feedback 挂 v_revised；需要 review queue 不直接落 negative） + autowriter 加 `example_label_proposal` 列 ⭐ Session #8
- [x] **P2 八**：`metric_snapshots` 加 `window_label` / `hours_since_publish` / `UNIQUE(note_id, window_label, source)` ⭐ Session #8
- [x] **P2 十一**：`category` 受控词表 v1（14 个值），TV/sanshengliubu 共用，写入 05-controlled-vocab.md §9 ⭐ Session #8
- [x] **P3 十**：notes 表 `aw_item_id` → `synced_autowriter_item_id` / `ssll_reference_sample_id` → `synced_ssll_reference_sample_id`（schemas + docs 全部同步）⭐ Session #8
- [x] **二审 11 条**：end-to-end 完备性 + service_role 强制 + Excel 工作流闭环 + Auth/RLS 段 + 4 处 SQL 复制可执行性 + 文档矛盾清扫 ⭐ Session #8
- [x] **三审 6 条硬 bug**：quarantine 列名对齐 + ensure_account_exists 实装 + comments schema 修 + autowriter dedup UUID 修 + sanshengliubu 列变必需 + sub-issue 修 ⭐ Session #8
- [x] **真实可跑 Python sync 脚本**：4 个脚本（feishu→TV / TV→ssll / TV→aw / extract negative）+ `_common.py` 共享工具 + .env.example + scripts/README ⭐ Session #8
- [x] **sanshengliubu patch**：`import_truth_vault_baokuan` 方法 + 必需的 schema migration SQL ⭐ Session #8

### 待启动 📋

- [ ] **跑 staging 环境 dry-run 验收**（sync 脚本 + sanshengliubu patch）⭐ 当前阻塞点
- [ ] 共享 Supabase 实例上线（public + autowriter + truth_vault 三 schema 就绪）
- [ ] **执行 autowriter migration RUNBOOK**（场景 A 或 B；含 Auth/RLS 检查）
- [ ] **执行 sanshengliubu patches/001_add_source_tv_note_id.sql**（在 sanshengliubu 集成 patch 之前）
- [ ] Supabase Dashboard → Exposed schemas 加 `autowriter` 和 `truth_vault`
- [ ] 给每个 mapping yaml 补 `sync_config` 段（feishu_app_token / feishu_table_id）
- [ ] sanshengliubu 集成 `import_truth_vault_baokuan` 方法（已提供 patch 代码）
- [ ] autowriter Memory Manager UI 加"负例候选审核" tab（不阻塞 sync，UX 优化）
- [ ] NRT_phase2/3 category 决议（OTC药 / 处方药 由策略 lead 拍板）
- [ ] NUC_1 全量导入 1102 行 + 验收 v_model_comparison view 有数据
- [ ] 其他项目 onboarding

---

## 下一步要做的事（按优先级）

### #1 · 共享 Supabase 部署 + Truth Vault 服务上线 (Sprint 0)

**预计耗时**: 1-2 周

1. 新建/选用一个共享 Supabase 实例
2. 在该实例创建三个 schema：public（已有 sanshengliubu）/ autowriter（迁移）/ truth_vault（新建）
3. 执行 schemas/notes_v1_2.sql 创建 truth_vault schema 所有表
4. autowriter 数据迁移到 autowriter schema（避免 projects 表名冲突）
   - 这需要协调 autowriter 维护者（你/工程师）
5. FastAPI 项目脚手架

**注意**: 共享实例后，autowriter 的 config.py 需要更新 SUPABASE_URL 指向共享实例，并在 SQL queries 里加 `autowriter.` schema prefix。

### #2 · 主 sync 通道 + NUC_1 全量导入 (Sprint 1)

**Session #8 已交付**: `sync_feishu_notes_to_truth_vault.py` 真实可跑脚本，含 D-021 quarantine 机制 + Step 4.5 数值清洗（千位分隔/全角数字/`/`-`无` token）+ publish_time 毫秒转 ISO + ensure_project_exists + ensure_account_exists FK 防护。

**Sprint 1 工作不再是"实现脚本"，而是**:
1. 给每个 mapping yaml 补 `sync_config.feishu_app_token` + `feishu_table_id`
2. 在 staging Supabase + 真实飞书表跑 `--dry-run --limit 5` 抽样测试
3. 根据 stats 判断是否需要扩 `_NUMERIC_COLS` / `_NUMERIC_NULL_TOKENS` / `_coerce_value` 边界
4. NUC_1 全量 1102 行实跑导入
5. 30 条 pilot 跑 essence_annotator + audience_inferrer prompt（这部分**还未自动化**，目前 spec 形态）
6. 跑 quality_review_decisions 抽查准确率，调词表/prompt
7. （D-014 LLM 子分类目前还在 raw_extra，独立 essence annotation pass 处理）

**预计耗时**: 1-2 周（脚本已有，主要是配置 + pilot 验证）

### #3 · 双通道集成 + 飞轮闭环 (Sprint 2)

**Session #8 已交付**: 三个 sync 脚本 + sanshengliubu patch 实代码。

**Sprint 2 工作**:
1. 跑 `sanshengliubu-patches/001_add_source_tv_note_id.sql` 加列（**必做前置**）
2. sanshengliubu 集成 `import_truth_vault_baokuan` 方法（patch 已就绪，~50 行复制粘贴）
3. dry-run 测试 `sync_truth_vault_baokuan_to_sanshengliubu.py`，验证幂等（pre-insert + post-fail orphan recovery 双层保护）
4. dry-run 测试 `sync_truth_vault_baokuan_to_autowriter_items.py`，验证 special batch + external_source dedup
5. 一次性跑 `extract_negative_examples_from_autowriter.py` 写 `example_label_proposal`
6. autowriter Memory Manager UI 加"负例候选审核" tab（**这一项仍需要前端开发**，本包不含）

**已知 P1 不闭环点**:
- **comments 表 sync 没有自动脚本**：TV → ssll 的 top_comments 字段会为空（除非手工导入 truth_vault.comments）。这不阻塞 notes 主链路，但 vibe_rewriter 的 reference packs 评论证据会缺失。等 NUC pilot 后判断是否需要补一个 sync 脚本。
- **autowriter Memory Manager 没有负例 review UI**：脚本写入 `example_label_proposal`，但没有前端展示页面。

**关键验收**:
- NUC_1 爆款已注入 `public.reference_samples`（下次 prompt 生产可见）
- NUC_1 爆款已注入 `autowriter.items` (example_label='positive')
- autowriter 历史 negative example 已写入 `example_label_proposal`（待 UI review）

**预计耗时**: 1-2 周（脚本已有，主要是部署 + 测试 + Memory Manager UI）

### #4 · 全项目铺开 (后续 2-3 个月)

按优先级：HXZ_QD / HXZ_FB → RIO_1 → WTG → NRT_2 / NRT_3 → TXQ_1 → TGV_1 → QSHG_1

---

## 延后清单 + 触发条件 ⭐ 避免遗忘

经 Session #10 全系统架构 review 后**明确暂不做但不忘记**的事项。**注意分类——不是所有都是"不需要"**：

- 🟡 **慢性病** —— 真潜在风险/缺失能力。触发信号一出，不做就积累代价。**几乎肯定都要做**，只是不急。
- 🔵 **能力扩展** —— 数据/团队/合规上规模之前做没意义，到了某个阈值就要做。
- ⚪ **可能永远不做** —— 真的属于"小团队不划算" 或 "等更大投入再说"，仅备忘。
- 🟣 **远期路标** —— Stage 2+/3+ 才进场，现在做也无处可用。

**没有触发就别动**，这是小团队的取舍纪律。

### 🟡 慢性病（触发就必须做）

| 事项 | 现在不做的理由 | 触发条件 |
|---|---|---|
| **Tier 阈值自适应**（按近 90 天 percentile 重算 yaml 里的 tier_thresholds） | yaml 当前硬编码值仍合理 | 第一次有项目出现"按现在阈值没爆款 / 爆款太多" 明显跑偏（直觉判断或 v_data_health.tier_coverage_rate 异常） |
| **Essence vocab v0.2 → v0.3 升级 + 老数据回标工具** | v0.2 词表覆盖率足够 Sprint 0-1 标注；升级工具是大工程 | 第一次有人标注时觉得"12 个 lever / 19 个 archetype 都不合适"超过 3 次 |
| **自反馈循环饱和度监控**（同一 lever 占 positive pool > 阈值时告警） | 现有 diversity 软约束已经在 sync 时主动避开同 lever 满 5 slot 的情况 | 第一次手动 review 时观察到"近 1 个月 positive items 80%+ 都是同一种调性" |
| **autowriter 端拆 "TV positive" vs "native positive" 双池** | TV-synced item 现在和 autowriter native positive 混在同一 list_example_items 池里，按 created_at 共同排序 | autowriter 运营反馈"内置的 positive 永远轮不上"，或想做 A/B 对比 TV-injected vs native 的下游表现 |
| **metric_snapshots 时序回收**（2h/24h/72h/7d window 自动 sync） | 当前飞书 import 只写 window_label='ad_hoc'；schema 留好但没人读 | 决定做 Layer 4 因果归因 / 时序 tier 早期预警时 |
| **prepublish_evaluations 写入路径**（schema 有但 view 永远空） | autowriter 端没有 `_select_best_drafts` 反推 hook；要 ssll critic 输出归档需要跨仓库改造 | 决定做 evaluator 校准 dashboard / 反推 prompt 改进时 |
| **comments 楼层重建**（D-022 Phase 2 LLM 重建 parent_comment_id） | 当前扁平评论已经能给 ssll vibe_rewriter 提供共振信号 | ssll 端反馈"评论楼层关系对生成质量有帮助" |
| **autowriter Memory Manager UI 负例审核 tab** | 候选写入了 `example_label_proposal` 但 autowriter 没前端审核界面 → negative_examples pipeline 实际上没贯通 | 决定要让 negative_examples 真注入到 build_system_prompt 时（不做这个，负例反向通道整条链都是白搭） |
| **依赖锁文件**（pip-compile / requirements.lock） | requirements.txt 用 `>=` 范围足够 Sprint 0-1；CI 用 ubuntu-latest 装当前最新版每次都能跑通 | 第一次因为某个上游库版本变化导致生产 sync 静默挂掉 |
| **跨 schema 写入审计日志**（service_role 谁/何时改了哪一行） | service_role 只在 GitHub Actions 跑，且写入路径已有 dry-run + preflight 保护 | 真出现过一次误操作污染生产；或合规要求审计 |

### 🔵 能力扩展（业务/数据上规模时做）

| 事项 | 触发条件 |
|---|---|
| **pgvector embedding rerank** 注入候选（用 BGE-M3 / Qwen-Embedding 等现成模型做相关性排序） | TV 累计 baokuan 数 ≥ 5000，且 v_autowriter_injection_candidates 现有 score 在多个项目同时跑偏 |
| **mypy / ruff / sqlfluff 静态检查** | 团队规模扩到 3+ 工程师，或第一次因为类型错误线上崩 |
| **Sync 失败 Slack/飞书 webhook 告警** | 团队规模扩到 5+ 工程师或 GitHub failure email 被忽略 |
| **完整 RLS 策略 + 多用户隔离** | 第一次有 Streamlit / 网页 UI 暴露 TV 数据给非工程师 |
| **评论作为 prompt 素材的隐私脱敏** | 真有合规 / 法务审查；或评论数据要面向客户/外部分享 |

### ⚪ 可能永远不做（仅备忘）

| 事项 | 不做的判断依据 |
|---|---|
| **微调小模型**（embedding adapter / LoRA / 任何端到端学习） | 小团队工作量过大，且没有评估基线就训练等于乱猜。唯一翻案条件：招了懂 ML 的人 |
| **完整 LLM-judge backtest framework** | 太重；`preview_injection_candidates.py` 已能让人眼判断"新策略是否更合理"。配套 ML 投入时才有意义 |
| **pytest 框架替代 ci.yml 内联测试** | 当前内联测试可读、可维护、CI 上跑得快；切换成本远高于价值。唯一翻案条件：测试数量翻倍（当前 ~10 个），或本地复现 CI 故障变得困难 |

### 🟣 远期路标

| 事项 | 何时进场 |
|---|---|
| **跨项目 essence 知识迁移**（NRT 的爆款经验喂给 NUC 的 autowriter） | 至少跑稳 6 个月单项目映射 + essence 标注全覆盖 + 新品类启动时缺历史 baokuan 严重影响生成质量。三个条件全满足前不要碰 |

---

**判断这清单要不要扩**: 任何新发现的"做着做着会出事"风险 → 加进 🟡 慢性病 + 写触发。任何"现在好像可以优化但不紧急"的想法 → 想清楚是 🟡/🔵/⚪ 哪类再存进来。**避免被未来可能用得上的事拖住**，但**也避免把真正会成为债务的事忘掉**。

---

## 当前未决问题（议程）

### Session #7 清理完成 ✅
- ~~D-023 HTTP REST API 设计~~ → **D-024 双通道直接 INSERT 取代**
- ~~D-016 prompt_versions / generation_runs / content_candidates 4 张表~~ → **D-025 简化为 FK 引用**
- ~~历史数据是否回流~~ → **D-026 分级处理**
- ~~autowriter 历史 items 怎么处理~~ → **D-027 抽 negative example 种子**
- ~~共享 Supabase 还是独立实例~~ → **D-024 确认共享**
- ~~sanshengliubu reference_samples 怎么处理~~ → **D-026 共存（tags 区分 source）**

### 仍未决
- **[Q4]** QSHG_1 无标注数据是否半监督？
- **[Q6]** Schema 是否保留"项目阶段"字段？
- **[Q7]** NUC_1 pilot 标注后是否做 v0.2 → v0.3 词表微调？
- **[Q8]** "时代语言范式" 子模式是否升级到闭集？
- **[Q9]** Surface 三级时间衰减 A/B 测试？
- **[Q13]** D-013 sanity check 扩展到其他字段？
- **[Q14]** intent=conversion 模型的 ground truth？
- **[Q15]** D-014 LLM 子分类"其他"fallback 占比监控？
- **[Q16]** 一次 LLM 调用做 4 件事 vs 拆开（需 NUC pilot 实测）
- **[Q17]** D-015 semantic_redefined_as 字段在查询时怎么暴露？
- **[Q21]** comment 楼层 LLM 重建成本估算（~2,700 条 × 单条成本）

### 新增议程（Session #7 引入）
- **[Q22]** autowriter 从独立 Supabase 迁移到共享 Supabase 的具体步骤？数据迁移过程中能否保证零停机？
- **[Q23]** Truth Vault 双通道 sync 频率？爆款每天 sync 一次还是更高频？
- **[Q24]** 工程师人选？

---

## 重要 context（新窗口必读）

### 项目起源

从 Ziao 看 oransim 开始 → 探讨 AI persona 评估 → 发现需要真实数据回流 → 演化为帆谷私有 Truth Vault 数据飞轮项目。

完整对话轨迹：
1. 评审 oransim → 算法不是护城河
2. RAG 路线被否决
3. 10 个项目数据审计
4. 三层架构（Surface / Essence / Audience）—— schema 灵魂
5. **会话 #1**: 文档奠基
6. **会话 #2**: 词表 v0.2 + 三级时间分层
7. **会话 #3**: NRT_phase3/2 方向拆解
8. **会话 #4**: 议程清理 + D-012 按 intent 分轨 + D-013 sanity check
9. **会话 #5**: NUC_1 试点 onboarding + D-014/D-015
10. **会话 #6**: v1.1 大升级（生成过程数据 + label leakage + 集成架构）
11. **会话 #7（当前）**: ⭐ 代码审查发现 v1.1 设计部分重复造轮子 → v1.2 双通道集成模式

### 关键决策摘要

读 [DECISIONS.md](DECISIONS.md) 看完整版。**Session #7 关键调整**：

- **D-001~D-022** v1.1 决策（部分被 v1.2 调整）
- **D-023** HTTP REST API 集成 → **作废，被 D-024 取代**
- **D-024** ⭐ Truth Vault 双通道集成（sanshengliubu.reference_samples + autowriter.items）
- **D-025** ⭐ 简化生成过程数据 layer（删除 3 张冗余表，改为 FK 引用）
- **D-026** ⭐ 历史数据回流策略（飞书必回 + autowriter 扫一次 + sanshengliubu 跳过）
- **D-027** ⭐ Negative example 来源（autowriter 用户修改 + 反馈 + 淘汰行为）

### Session #7 核心理解

**Truth Vault 角色重新定位**:
- v1.1 误以为 Truth Vault 是"过程数据库"（含生成过程数据）
- 代码审查发现 sanshengliubu / autowriter 已有完整过程数据表
- **v1.2 正确定位：Truth Vault 是"结果数据库 + 跨系统飞轮枢纽"**

**飞轮闭环的真正含义**:
- 不是"Truth Vault 提供 API 让别人调"
- 是"Truth Vault 主动喂数据到现存系统已有的高权重注入路径"
- sanshengliubu.reference_samples 注入 vibe_rewriter（已有机制）
- autowriter.items.example_label='positive' 注入 build_system_prompt（已有机制）
- autowriter 已完成 P1 一次性改造（DDL 修复 + schema 迁移 + list_example_items + lineage，约 190 行）；sanshengliubu 加 ~30 行 `import_truth_vault_baokuan` = 飞轮转起来

**Negative example 信号源**:
- 正面信号来自 Truth Vault notes（tier=爆/大爆，已发布真实数据）
- 负面信号来自 autowriter.items 的用户修改/淘汰行为（来自人，不是 AI 自评）
- 两者来源独立 → 高质量训练对比

### 关键集成假设

1. **共享 Supabase 实例**（不是独立实例）
2. **autowriter 迁移到 autowriter schema**（避免 public.projects 冲突）
3. **sanshengliubu 保持在 public schema**（不动现有部署）
4. **truth_vault schema 新建**

---

## 关键文件清单（v1.2 / Session #9）

```
truth-vault/
├── README.md                          ← 项目宪法 + 完整目录结构索引
├── CURRENT_STATE.md                   ← 本文件 (Sprint 0 scope)
├── DECISIONS.md                       ← D-001 ~ D-035 (Session #9 加了 D-034/D-035)
│
├── docs/                              ← 10 篇设计文档
│   ├── 01-architecture.md             三层架构论证
│   ├── 02-schema-v1.md                Schema v1.2 字段级 (已对齐 SQL)
│   ├── 03-mapping-protocol.md         飞书 → DB 映射 + Step 4.5 清洗
│   ├── 04-onboarding-sop.md           新项目 7 步接入 SOP
│   ├── 05-controlled-vocab.md         词表 v0.2 (含 category v1)
│   ├── 06-essence-annotation.md       LLM 标注协议双模式
│   ├── 07-audience-data.md            蒲公英 audience 数据
│   ├── 08-evolution-roadmap.md        四阶段进化
│   ├── 09-system-integration.md       ⭐ 双通道集成架构 v2 (必读)
│   └── 99-rejected-ideas.md           走过的弯路
│
├── schemas/                           ← 可执行 SQL
│   ├── notes_v1_2.sql                 truth_vault schema · 13 张表 + 内部 views
│   │                                    + ingested_at 保留 trigger (Session #9)
│   │                                    + category CHECK (Session #9)
│   │                                    + parent_comment_id ON DELETE SET NULL
│   └── notes_v1_2_cross_schema_views.sql 跨 schema views (D-029 部署拆分)
│
├── mappings/                          ← 项目 mapping yaml
│   ├── _template.yaml                 新项目模板
│   ├── NUC_phase1.yaml                NUC_1 完整 (含 ingest_classification_prompt)
│   ├── NRT_phase2.yaml                NRT_2 草稿
│   └── NRT_phase3.yaml                NRT_3 草稿
│
├── prompts/                           ← LLM prompt 库
│   ├── essence_annotator.md           Mode A/B 双模式 v0.3 (白盒 leakage 校验)
│   └── audience_inferrer.md           Audience 独立推断 v0.1
│
├── scripts/                           ← 6 个真实可跑 Python 脚本 ⭐
│   ├── README.md                      数据流图 + 部署 + 故障排查
│   ├── _common.py                     共享工具 (含 JWT 校验 + 分页 helper)
│   ├── .env.example                   含 ANTHROPIC_API_KEY + ESSENCE_MODEL
│   ├── requirements.txt               supabase + pyyaml + requests + anthropic
│   │
│   ├── sync_feishu_notes_to_truth_vault.py            主 sync (含 C 家族 tier
│   │                                                    + direction_decomposition
│   │                                                    + 数值 tier 兜底)
│   ├── sync_comments_from_raw_extra.py                ⭐ Session #9 新增
│   ├── annotate_essence_pass.py                       ⭐ Session #9 新增 LLM pass
│   ├── sync_truth_vault_baokuan_to_sanshengliubu.py   通道 1 (含 preflight)
│   ├── sync_truth_vault_baokuan_to_autowriter_items.py 通道 2 (含 transactional
│   │                                                    recovery, Session #9)
│   └── extract_negative_examples_from_autowriter.py   3 来源 (含 Source A/B
│                                                       prior-version 校验)
│
├── sanshengliubu-patches/             ⭐ Session #9 补回 (final ZIP 漏)
│   ├── README.md                      部署顺序 + 回滚
│   ├── 001_add_source_tv_note_id.sql  必做前置
│   └── import_truth_vault_baokuan.py  可选 helper
│
├── autowriter-migrations/             ⭐ Session #9 补回 (final ZIP 漏)
│   ├── RUNBOOK.md                     场景 A/B 完整步骤 + Auth/RLS
│   ├── 001_create_autowriter_schema.sql      5 表迁移
│   ├── 002_add_external_source.sql           幂等键
│   └── 003_add_example_label_proposal.sql    负例候选列
│
└── data-analysis/
    └── 10-project-audit.md            10 个项目初始审计
```

**统计**: 40 个文件 · ~12,700 行 (docs/sql/yaml/python) · 全部本地烟测通过 (Postgres 16 部署 + Python syntax + comment parser 6/6 单测)

---

## 新会话开场协议

新窗口的 Claude 接到项目，按以下顺序读：

1. **主线 (30 分钟)**:
   - `README.md` · 完整目录结构 + 导航分组
   - `CURRENT_STATE.md`（本文件）· Sprint 0 scope + 已知 gap
   - `docs/09-system-integration.md` ⭐ · 双通道集成核心架构
   - `docs/01-architecture.md` · 三层架构论证
   - `DECISIONS.md` D-001 ~ D-035 · 决策考古

2. **工程实施按需读**:
   - Schema: `schemas/notes_v1_2.sql` + `docs/02-schema-v1.md`
   - 部署: `sanshengliubu-patches/README.md` + `autowriter-migrations/RUNBOOK.md`
   - Sync 脚本: `scripts/README.md` (含数据流图 + cron + 故障排查)
   - Mapping: `mappings/_template.yaml` + `docs/03-mapping-protocol.md`
   - LLM 标注: `prompts/essence_annotator.md` + `docs/06-essence-annotation.md`

3. **反向陈述当前理解 → 等 Ziao 确认。特别确认**:
   - Sprint 0 scope (主链路) vs Sprint 1+ gap (sub_directions / Memory UI / prepublish_evaluations)
   - 没有违反 D-001~D-035 任何决策

---

## 会话交接模板

```markdown
## Session #N 交接 · YYYY-MM-DD

### 本次会话做了什么
- ...

### CURRENT_STATE.md 应该更新成什么
[贴完整 markdown]

### 文档应该新增/修改什么
- 新增/修改: ...

### 下次会话应该从哪里开始
建议开场词:
[...]
```
