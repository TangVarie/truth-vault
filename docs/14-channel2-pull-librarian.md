# docs/14 · 通道2 v2 · Pull / 图书馆 + LLM 馆员（取代 D-024 通道2 push）

**新增**: 2026-06-01（Session #15）
**状态**: 设计已定稿，**待建**。autowriter 侧改造跟踪见 [docs/10 R-032](10-sister-repo-followups.md#r-032)。
**取代**: [D-024](../DECISIONS.md#d-024) 的**通道2（autowriter）部分**。通道1（ssll）完全不变。决策记录见 [DECISIONS.md D-038](../DECISIONS.md#d-038)。

> **一句话**: 通道2 从"TV 预先把爆款 **push** 进 `autowriter.items`（example_label='positive'）"改为"TV 当**图书馆**，autowriter 写稿时按需向 **LLM 馆员**借阅匹配的爆款经验"。

---

## 0. 为什么改（push 的根本困局）

push 模型（D-024 通道2）跑下来暴露一个结构性问题，根因不在配置而在机制：

- autowriter 现成的正例机制是 `build_system_prompt` → `list_example_items('positive')` → **按 `created_at` 取最近 5 条**（见 `sync_truth_vault_baokuan_to_autowriter_items.py` docstring）。**没有相关性检索、没有 LLM 匹配。**
- 所以"哪条爆款对哪次写稿有用"这件事，push 模型**没法在写稿时判断**，只能在**推送时**就钦定"这条爆款进哪个项目"——`truth_vault.projects.mapping_to_autowriter_project_id` 这个单 FK 就是干这个的。
- 于是一切复杂度都从这个单 FK 长出来：WTG 一个 TV 项目 ↔ autowriter **18 个项目 / 3 个 owner**（命名两套、编号对不齐）的一对多路由、产品/流量分类、扇出到每个 owner、每 owner 的桶……**这些全是"autowriter 不会检索"的替代品。**

而**通道1（ssll）从来没有这个问题**：TV 只把爆款堆进 `public.reference_samples`，ssll 的 `vibe_rewriter` 写稿时自己调 `retrieve_reference_packs()` **按 platform/category 现借**（见 [docs/10 R-022 ✅](10-sister-repo-followups.md#r-022)）。**没有任何"先决定推给哪个项目"的预路由。** 通道1 天生是图书馆模型，因为 ssll 现成的注入点本来就是个检索。

**结论**: 把通道2 也对齐成 pull / 图书馆。一刀下去，路由表、扇出、产品/流量分类、每-owner-桶 **全部消失**——它们的存在只是为了补 autowriter 不做检索这个洞。

---

## 1. 核心模型：图书馆 + 管家 + 馆员

```
飞书爆款 ──①管家(LLM)入库策展──→ [TV 策展库：经验卡(只摆爆/大爆，去长尾)]
                                            ↑ 借阅(带 brief)
autowriter 写稿请求 ──────────→ [②馆员(LLM)推理挑选+点评] ──→ 选中 3-5 条经验 ──→ 注入 prompt
                                                                      (与 owner 自有正例并列、分区)
```

- **书架** = TV 策展库：只摆**已验证的真实爆款**（tier ∈ 爆/大爆），不是生贴，是提炼过的"经验卡"。
- **管家** = 入库时的 LLM：把每条爆款消化成结构化经验卡（钩子/情绪杠杆/结构/**为什么爆**）。TV 现有的 essence annotation pass 已经起了头。
- **馆员** = 写稿时的 LLM：拿 autowriter 的写作 brief，**推理**该借哪几条、借它们的**哪个部位**、为什么，返回挑选+点评过的少数几条。

### ⚠️ 两套独立逻辑，绝不能合并

| | **owner 自有正例** | **飞轮经验（本设计）** |
|---|---|---|
| 来源 | owner 在 Memory Manager 里对**自己的稿子**点正/负 | 现实世界真爆过的帆谷爆款 |
| 逻辑 | 主观："我喜欢这一版" | 客观："它真的爆了" |
| 机制 | autowriter 原生 `example_label` + `list_example_items` | TV 馆员按需供给 |
| 本设计影响 | **完全不动** | 新增，与上者**并列、分区**注入 prompt |

写稿时 prompt 里的正例 = **owner 自己的正例（原生，不动）** ⊕ **馆员给的飞轮精选（新增）**。两个 section、两套来源，内容可能重合，但权重和逻辑分开。

---

## 2. LLM 的两个位置（出力点是"判断"，不是相似度检索）

如果 LLM 只算 embedding 相似度，那是向量检索、不配叫馆员，也正是 [D-002](../DECISIONS.md#d-002) 否掉的 naive RAG。本设计里 LLM 在两处做**判断**：

- **① 入库策展（管家整理书架）**: 把每条爆款提炼成经验卡——`hook_type` / `emotional_lever` / `structure` / `why_it_worked` / `target_audience` + 原文片段。书架上摆的是带索引、可迁移的经验，不是生贴。
- **② 借阅推理（馆员服务借书人）**: 输入写作 brief（项目/品类/品牌/方向/人群/可选当前选题），LLM **不按相似度捞**，而是推理：这个任务该借哪几条、借**哪个部位**（钩子？评论区设计？结构？）、为什么；可跨主题迁移（"这条虽是别的产品，但开场正适合你这篇"）。输出 3-5 条 + 点评。

**为什么这不是 D-002 否掉的 RAG**（三条，缺一不可）：
1. 书架**预策展只摆爆/大爆**——D-002 的"长尾 160/170 趴、检索捞到趴"前提在此不成立（趴根本不进库）。
2. 馆员是**推理选取**，不是相似度 top-k。
3. 最简版甚至**先按 category/brand 结构化过滤**、再交 LLM 选，连 embedding 都可不必（与通道1 同思路）。

---

## 3. 什么退役 / 什么保留

| | 项 | 说明 |
|---|---|---|
| **退役**（pull 上线后） | `scripts/sync_truth_vault_baokuan_to_autowriter_items.py` 整条 push 管子 | special batch / 写 `example_label='positive'` / `external_source` 幂等 / 6 个月退役 pass —— 全是 push 侧机制 |
| **退役** | `projects.mapping_to_autowriter_project_id` 作为**路由**用途 | 列可留作溯源，但不再决定"推给谁" |
| **重生**（不是删，是搬进策展库/馆员） | `v_autowriter_injection_candidates` 的 `injection_score` + 多样性 + 新鲜度（[D-036](../DECISIONS.md) 那套） | 排序/去重/退役逻辑搬进**管家策展 + 馆员选取**，让借到的是"好书且新" |
| **保留 · 完全不动** | autowriter 原生 `example_label`（owner 对自己稿子点正/负）+ `build_system_prompt` 消费链 | owner 判断侧，与飞轮无关 |
| **保留 · 完全不动** | negative 反向通道（[D-027](../DECISIONS.md#d-027)：`extract_negative_examples` → `example_label_proposal` → Memory Manager review） | 同上，owner 判断侧 |
| **保留 · 完全不动** | 通道1（ssll）整条 | 它本来就是 pull/图书馆，已验证（R-022 ✅） |
| **保留 + 扩展** | TV essence annotation pass | 管家策展的种子，扩成"经验卡"生成 |

> **重要**: autowriter 现存账号数据（项目 / items / versions / owner 手标的正负例 / batches / memories）**一根毫毛都不碰**。而且通道2 push **从没真跑过**（`autowriter.items.external_source` 全 NULL、`truth_vault_synced` batch 一个都没建），所以 push 退役时连一条 TV 的行都不用清——白纸切换。

---

## 4. 组件设计（草案，细节见 §6 待定）

### 4.1 TV 策展库 · 经验卡

物化成 view 或表（refresh by 策展 pass），一条爆款一张卡：

```
truth_vault.v_flywheel_lesson_cards   (sketch)
─────────────────────────────────────────────
source_note_id      ← truth_vault.notes.note_id（溯源键）
tier                ← 爆 / 大爆（硬过滤，趴/风控/未知不进库）
category, platform, brand
target_audience     ← essence
emotional_lever     ← essence（已有）
hook_type           ← 管家 LLM 新提炼
structure           ← 管家 LLM 新提炼（骨架：开场/铺陈/转折/CTA/评论区设计）
why_it_worked       ← 管家 LLM 新提炼（为什么爆，可迁移的那条经验）
raw_excerpt         ← raw_content 片段（供仿写，截断防 prompt 爆）
rank_score          ← 吸收 D-036：tier 权重 + recency + account_bao_rate
```

`hook_type / structure / why_it_worked` 是 essence pass 的**扩展产出**（新增 prompt 段）。

### 4.2 LLM 馆员服务（跑在 TV 侧）

- **输入（brief）**: `{project_id, category, platform, brand, 方向/angle, target_audience, draft_context?(可选当前选题/草稿)}`
- **输出**: `[{source_note_id, why_relevant(点评), borrow_what(借哪个部位), excerpt}]` × 3-5
- **形态**: TV 已有 FastAPI 服务层（docs/09 Layer 1），馆员作为一个 endpoint；或 Supabase Edge Function（LLM 调用在 2 分钟上限内，可行）。**待定见 §6。**
- **运行时机**: autowriter 每次起 batch / 写稿请求时**同步**调一次（per-batch，不必 per-item）。

### 4.3 autowriter 侧改造（R-032，sister-repo 工作）

最小改动：写稿前调馆员 → 把返回的经验作为**独立 section** 注入 prompt，与 owner 自有正例**并列、分区标注**：

```
build_system_prompt 装配（新增一段）:
  【真实爆款参照 · 系统按本次选题匹配（飞轮）】
    {馆员返回的 3-5 条经验卡 + 点评}
  【我的优质案例（owner 自标 positive，原生不动）】
    {list_example_items('positive') 现有逻辑}
```

详细 prompt 模板 + 调用点改造由 autowriter 维护者落地，见 docs/10 R-032。

---

## 5. 失败 / 降级 / 无状态

- **馆员超时/不可用/空库** → autowriter **回退到 owner 自有正例**，照常写稿，**绝不阻塞**。飞轮是增强项，不是写稿前置依赖。
- 馆员**无状态**：每次按 brief 现算，不在 autowriter 留 TV 数据（这正是 pull 比 push 干净的地方——没有要同步/退役/RLS 对齐的注入行）。
- **溯源**: 馆员返回带 `source_note_id`，autowriter 生成内容时可记录"参考了哪几条"，供后续飞轮效果分析（替代 push 模式下 `synced_autowriter_item_id` 的 lineage 作用）。

---

## 6. 待定（开建前要拍的）

1. **馆员 = 规则+LLM 混合，还是纯 LLM？** 建议混合：先 category/brand/方向 结构化收窄，再 LLM 推理选取（省 token、稳）。
2. **brief 里放哪些字段**：最少 category/platform/brand/方向；要不要把"当前选题/草稿摘要"也喂给馆员做更准的迁移判断？
3. **馆员接口形态**：TV FastAPI endpoint vs Supabase Edge Function（牵涉 autowriter 怎么调、鉴权、网络）。
4. **经验卡字段最终集** + 策展 pass 的 prompt（管家提炼 hook/structure/why 的 prompt 规格）。
5. **是否需要 embedding 预筛**：库小（爆款本就稀少）时可不必；库大了再加 essence 向量做粗筛。
6. **R-032 的 autowriter 侧工时/owner**：见 docs/10。

---

## 7. 与既有决策的关系

- **取代** D-024 通道2：D-024 当年选 push 的理由是"复用 autowriter 现成注入点、零改动、飞轮启动快"。但 autowriter 现成注入点是 recency-push（不是检索），导致路由困局。现在 **0 条合格爆款**（见 docs/13），是重做选型的**最佳窗口**——没有数据要迁。代价是 autowriter 侧要改生成流程（R-032），等于重开一个已拍板决策，已在 D-038 记录权衡。
- **不触碰** D-027（negative 反向通道）、通道1、owner 原生 example_label。
- **不违背** D-002：见 §2，这不是被否的 naive RAG。
