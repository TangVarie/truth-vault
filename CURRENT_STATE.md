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

## 关键文件清单（v1.2）

```
README.md                           ← 项目宪法（v1.2 部分微调）
CURRENT_STATE.md                    ← 本文件
DECISIONS.md                        ← 1100+ 行，含 D-001 ~ D-027

docs/
  01-architecture.md                ← 三层架构论证
  02-schema-v1.md                   ← Schema v1.2 描述（已对齐 notes_v1_2.sql）
  03-mapping-protocol.md            ← 飞书 → DB 映射 + Step 4.5 清洗
  04-onboarding-sop.md              ← 新项目接入 SOP
  05-controlled-vocab.md            ← 词表 v0.2
  06-essence-annotation.md          ← LLM 标注协议（含双模式）
  07-audience-data.md               ← 蒲公英数据接入
  08-evolution-roadmap.md           ← 四阶段进化（阶段 2 按 intent 分轨）
  09-system-integration.md          ⭐ 双通道集成架构 v2（必读）
  99-rejected-ideas.md              ← 走过的弯路

mappings/
  _template.yaml
  NRT_phase2.yaml
  NRT_phase3.yaml
  NUC_phase1.yaml                   ← 第一个完整 onboarded 项目

prompts/
  essence_annotator.md
  audience_inferrer.md

schemas/
  notes_v1_2.sql                    ← 表+内部 views（无外部依赖）
  notes_v1_2_cross_schema_views.sql ← 跨 schema views（D-029 拆分）                    ⭐ v1.2 简化版（删 3 表 + 跨 schema FK）

data-analysis/
  10-project-audit.md
```

---

## 新会话开场协议

新窗口的 Claude 接到项目：

1. 按顺序读取：
   - `README.md`
   - `CURRENT_STATE.md`（本文件）
   - `DECISIONS.md`
   - **`docs/09-system-integration.md` v2** ⭐ Session #7 必读

2. 工程实施时额外读取：
   - `schemas/notes_v1_2.sql` + `schemas/notes_v1_2_cross_schema_views.sql`
   - `docs/02-schema-v1.md`（待 Session #8 更新到 v1.2）
   - `docs/03-mapping-protocol.md`
   - `mappings/NUC_phase1.yaml`

3. 反向陈述当前理解 → 等 Ziao 确认。

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
