# docs/14 · 通道2 v2 · Pull / 图书馆 + LLM 馆员（取代 D-024 通道2 push）

**新增**: 2026-06-01（Session #15）
**状态**: 设计已定稿（§6 决议已拍），**待建**。消费方改造跟踪：autowriter [docs/10 R-032](10-sister-repo-followups.md#r-032)、sanshengliubu [docs/10 R-033](10-sister-repo-followups.md#r-033)。
**取代**: [D-024](../DECISIONS.md#d-024) 的**通道2（autowriter）部分**。通道1（ssll）的现状不变（但 ssll 是馆员的第二个消费方，见 R-033）。决策记录见 [DECISIONS.md D-038](../DECISIONS.md#d-038)。

> **一句话**: 通道2 从"TV 预先把爆款 **push** 进 `autowriter.items`（example_label='positive'）"改为"TV 当**图书馆 + LLM 馆员**（独立共享服务），aw / ssll 写稿时按需借阅匹配的爆款经验"。

---

## 0. 为什么改（push 的根本困局）

push 模型（D-024 通道2）跑下来暴露一个结构性问题，根因不在配置而在机制：

- autowriter 现成的正例机制是 `build_system_prompt` → `list_example_items('positive')` → **按 `created_at` 取最近 5 条**（见 `sync_truth_vault_baokuan_to_autowriter_items.py` docstring）。**没有相关性检索、没有 LLM 匹配。**
- 所以"哪条爆款对哪次写稿有用"这件事，push 模型**没法在写稿时判断**，只能在**推送时**就钦定"这条爆款进哪个项目"——`truth_vault.projects.mapping_to_autowriter_project_id` 这个单 FK 就是干这个的。
- 于是一切复杂度都从这个单 FK 长出来：WTG 一个 TV 项目 ↔ autowriter **18 个项目 / 3 个 owner**（命名两套、编号对不齐）的一对多路由、产品/流量分类、扇出到每个 owner、每 owner 的桶……**这些全是"autowriter 不会检索"的替代品。**

而**通道1（ssll）从来没有这个问题**：TV 只把爆款堆进 `public.reference_samples`，ssll 的 `vibe_rewriter` 写稿时自己调 `retrieve_reference_packs()` **按 platform/category 现借**（见 [docs/10 R-022 ✅](10-sister-repo-followups.md#r-022)）。**没有任何"先决定推给哪个项目"的预路由。** 通道1 天生是图书馆模型，因为 ssll 现成的注入点本来就是个检索。

**结论**: 把通道2 也对齐成 pull / 图书馆，且把这个"图书馆 + 馆员"做成 **aw / ssll 共享的服务**。一刀下去，路由表、扇出、产品/流量分类、每-owner-桶 **全部消失**——它们的存在只是为了补 autowriter 不做检索这个洞。

---

## 1. 核心模型：图书馆 + 管家 + 馆员

```
飞书爆款 ──①管家(LLM)入库策展──→ [TV 策展库：经验卡(只摆爆/大爆，去长尾)]
                                            ↑ 借阅(带 brief)        ↑
aw / ssll 写稿请求 ──────────→ [②馆员(LLM)推理挑选+点评] ──→ 选中 3-5 条经验 ──→ 注入 prompt
                                  (带结果缓存，命中跳过 LLM)            (与消费方自有正例并列、分区)
```

- **书架** = TV 策展库：只摆**已验证的真实爆款**（tier ∈ 爆/大爆），不是生贴，是提炼过的"经验卡"。
- **管家** = 入库时的 LLM：把每条爆款消化成结构化经验卡（钩子/情绪杠杆/结构/**为什么爆**/可借手法）。TV 现有 essence annotation pass 已起头。
- **馆员** = 写稿时的 LLM（**aw / ssll 共享**）：拿写作 brief，**推理**该借哪几条、借哪个部位、为什么，返回挑选+点评过的少数几条。带结果缓存。

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

- **① 入库策展（管家整理书架）**: 把每条爆款提炼成经验卡——`hook_type` / `structure` / `why_it_worked` / `transferable_tactic` + 原文片段。书架上摆的是带索引、可迁移的经验，不是生贴。
- **② 借阅推理（馆员服务借书人）**: 输入写作 brief（项目 prompt 包 + 本次请求 delta），LLM **不按相似度捞**，而是推理：该借哪几条、借**哪个部位**（钩子？评论区设计？结构？）、为什么；可跨主题迁移（"这条虽是别的产品，但开场正适合你这篇"）。输出 3-5 条 + 点评。

**为什么这不是 D-002 否掉的 RAG**（三条，缺一不可）：
1. 书架**预策展只摆爆/大爆**——D-002 的"长尾 160/170 趴、检索捞到趴"前提在此不成立（趴根本不进库）。
2. 馆员是**推理选取**，不是相似度 top-k。
3. **不建手维护规则表**：爆款稀少 → 库长期很小 → 直接把整库喂 LLM 让它每次看 brief 判断，最省最准；"tier 只摆爆/大爆"是零维护的结构性过滤，不算规则表。

---

## 3. 什么退役 / 什么保留

| | 项 | 说明 |
|---|---|---|
| **退役**（pull 上线后） | `scripts/sync_truth_vault_baokuan_to_autowriter_items.py` 整条 push 管子 | special batch / 写 `example_label='positive'` / `external_source` 幂等 / 6 个月退役 pass —— 全是 push 侧机制 |
| **退役** | `projects.mapping_to_autowriter_project_id` 作为**路由**用途 | 列可留作溯源，但不再决定"推给谁" |
| **重生**（不是删，是搬进策展库/馆员） | `v_autowriter_injection_candidates` 的 `injection_score` + 多样性 + 新鲜度（[D-036](../DECISIONS.md) 那套） | 排序/去重/退役逻辑搬进**管家策展 + 馆员选取**，让借到的是"好书且新" |
| **保留 · 完全不动** | autowriter 原生 `example_label`（owner 对自己稿子点正/负）+ `build_system_prompt` 消费链 | owner 判断侧，与飞轮无关 |
| **保留 · 完全不动** | negative 反向通道（[D-027](../DECISIONS.md#d-027)：`extract_negative_examples` → `example_label_proposal` → Memory Manager review） | 同上，owner 判断侧 |
| **保留 · 现状不动** | 通道1（ssll）现有 `retrieve_reference_packs` category-filter 注入 | 已验证（R-022 ✅）；ssll 升级到馆员是**可选**项（R-033），不阻塞 |
| **保留 + 扩展** | TV essence annotation pass | 管家策展的种子，扩成"经验卡"生成 |

> **重要**: autowriter 现存账号数据（项目 / items / versions / owner 手标的正负例 / batches / memories）**一根毫毛都不碰**。而且通道2 push **从没真跑过**（`autowriter.items.external_source` 全 NULL、`truth_vault_synced` batch 一个都没建），所以 push 退役时连一条 TV 的行都不用清——白纸切换。

---

## 4. 组件设计

### 4.1 TV 策展库 · 经验卡（✅ 已建 · schemas/notes_v1_4_flywheel_lesson_cards.sql）

物化成 view 或表（refresh by 策展 pass），一条爆款一张卡：

```
truth_vault.v_flywheel_lesson_cards
─────────────────────────────────────────────
source_note_id      ← truth_vault.notes.note_id（溯源键）
tier                ← 爆 / 大爆（硬过滤，趴/风控/未知不进库）
brand, category, platform
target_audience     ← essence
emotional_lever     ← essence（已有）
hook_type           ← 管家 LLM 新提炼（钩子类型）
structure           ← 管家 LLM 新提炼（骨架：开场/铺陈/转折/CTA/评论区设计）
why_it_worked       ← 管家 LLM 新提炼（为什么爆，可迁移的那条经验）
transferable_tactic ← 管家 LLM 新提炼（可直接借走的具体手法，如"用'差旅3天不用换'当场景钩子"）
raw_excerpt         ← raw_content 片段（供仿写，截断防 prompt 爆）
rank_score          ← 吸收 D-036：tier 权重 + recency + account_bao_rate
```

`hook_type / structure / why_it_worked / transferable_tactic` 是 essence pass 的**扩展产出**（新增 prompt 段，扩 `prompts/essence_annotator.md`）。

**实现说明（v1.4 已落地）**：经验卡字段落在独立表 `truth_vault.flywheel_lesson_annotations`（按 note_id 一行，仿 `note_features` 范式，不污染 notes 主表），由策展 pass 写入；视图 `truth_vault.v_flywheel_lesson_cards` 把合格爆款 + essence + 经验卡（LEFT JOIN，未策展也出卡，馆员用 raw_excerpt + essence 兜底）+ rank_score 组装好。eligibility 同注入候选但**去掉 aw 映射要求**（pull 不预路由）；**synthetic 伪贴：爆/大爆排除、参考放行**（纯人工判断、与指标真假无关，同 docs/13 通道1——push 的注入 view 是无差别排除，那条在退役不动它）。已用现有 1 条参考笔记实跑验证（eligibility + rank_score 正确）。下一步 ② 策展 pass 填这张表。

### 4.2 LLM 馆员服务（独立共享服务）

**消费方**: autowriter（[R-032](10-sister-repo-followups.md#r-032)）**和** sanshengliubu（[R-033](10-sister-repo-followups.md#r-033)）——所以它必须是**独立共享服务**，不能塞进任一仓。

- **形态（D-038 已定）**: **FastAPI on Railway**。理由：共享服务值得正经常驻服务；**Python 一种语言**贯穿管家(入库 cron)+馆员(查询)，复用 Anthropic/essence 代码；**无执行时长上限**（不受 Edge ~2 分钟限制，后期可做多步推理/大库）。**Edge Function 已排除**（Deno 重写 + 执行上限 + 共享服务不该用受限函数）。
- **输入（brief）**: 大头是**项目的 prompt 包**（实质内容在这）+ 本次请求 delta：
  ```
  # 实质（项目级，稳定 → 缓存友好）
  brand, project_name, system_prompt, system_prompt_tone,
  system_prompt_exec, tactics, calibration_notes
  # delta（本次请求）
  tactic, target_audience, tone, extra_instructions, draft_topic?(可选选题)
  ```
  全是 aw / ssll 生成时**现成就有的**，不用新收集。
- **输出**: `[{source_note_id, why_relevant(点评), borrow_what(借哪个部位), excerpt}]` × 3-5
- **缓存（必须，省 LLM 成本）**: 内容寻址缓存，一张 Supabase 表 `truth_vault.flywheel_librarian_cache`：
  - `cache_key = hash(consumer + project_id + brief_digest + library_version)`
  - 命中 → 直接返回上次精选，**跳过 LLM**；未命中 → 跑馆员 → 写回。
  - **自动失效**：`library_version` = 经验卡 `max(updated_at)` / 计数器；新爆款入库 → 版本变 → 旧 key 不命中 → 重算。brief 改 → `brief_digest` 变 → 重算。
  - 爆款稀少（库几乎不变）+ brief 稳定 → 命中率极高，绝大多数请求 **0 LLM**。底层调用再叠 Anthropic prompt caching 兜底。
- **运行时机**: 消费方每次起 batch / 写稿请求时同步调一次（per-batch，不必 per-item）。
- **鉴权**: 服务用 service_role 读 TV 策展库 + 缓存；对外（aw/ssll 调用）用一个内部 API key / JWT，别裸暴露公网。

### 4.3 消费方改造（aw = R-032，ssll = R-033）

最小改动：写稿前调馆员 → 把返回的经验作为**独立 section** 注入 prompt，与消费方自有正例**并列、分区标注**：

```
build_system_prompt 装配（autowriter，新增一段）:
  【真实爆款参照 · 系统按本次选题匹配（飞轮）】
    {馆员返回的 3-5 条经验卡 + 点评}
  【我的优质案例（owner 自标 positive，原生不动）】
    {list_example_items('positive') 现有逻辑}
```

ssll 侧类似：在 `vibe_rewriter` 现有 DB 样本注入位（R-022）改为/补为调馆员。详见 docs/10 R-032 / R-033。

---

## 5. 失败 / 降级 / 无状态

- **馆员超时/不可用/空库** → 消费方**回退到自有正例**（aw: owner positive；ssll: 现有 `retrieve_reference_packs`），照常写稿，**绝不阻塞**。飞轮是增强项，不是写稿前置依赖。
- 馆员**无状态**：每次按 brief 现算（或命中缓存），不在消费方留 TV 数据（这正是 pull 比 push 干净的地方——没有要同步/退役/RLS 对齐的注入行）。
- **溯源**: 馆员返回带 `source_note_id`，消费方生成内容时可记录"参考了哪几条"，供后续飞轮效果分析（替代 push 模式下 `synced_autowriter_item_id` 的 lineage 作用）。

---

## 6. 决议（§6.1–6.4 已拍 · Session #15）

1. **馆员 = 纯 LLM，不建手维护规则表** ✅。"tier 只摆爆/大爆"是结构性过滤（零维护）保留；"category/方向 → 借哪些"这种手工映射表不建，交 LLM 每次看 brief 判断。爆款稀少 → 库长期很小 → 直接把整库喂 LLM 最省最准。
2. **brief = 项目 prompt 包（system_prompt + tone + exec + tactics + calibration_notes）+ 本次 delta** ✅。实质内容在项目 prompt 里；全是消费方现成的。详见 §4.2。
3. **接口 = FastAPI on Railway，作为 aw + ssll 共享馆员服务** ✅（[D-038](../DECISIONS.md#d-038)）。Edge Function 排除（Deno 重写 + ~2 分钟执行上限顶不住 + 共享服务不该用受限函数）。详见 §4.2。
4. **经验卡字段 + 策展 prompt 由设计方定** ✅。字段见 §4.1；策展 prompt 扩 `prompts/essence_annotator.md`，新增 hook_type / structure / why_it_worked / transferable_tactic 四段，其余复用现有 essence。
5. **新增 · 馆员结果缓存** ✅（你提的）：内容寻址 + 库版本自动失效，见 §4.2，省 LLM 成本。

**仍待定（不阻塞开建）**:
- 库大了**是否加 embedding 粗筛**（现在库小不必；要加也是免维护那种，**永不碰手工规则表**）。
- ssll 采纳馆员的细节（从现有 category-filter 切到馆员）：见 [R-033](10-sister-repo-followups.md#r-033)。

---

## 7. 与既有决策的关系

- **取代** D-024 通道2：D-024 当年选 push 的理由是"复用 autowriter 现成注入点、零改动、飞轮启动快"。但 autowriter 现成注入点是 recency-push（不是检索），导致路由困局。现在 **0 条合格爆款**（见 docs/13），是重做选型的**最佳窗口**——没有数据要迁。代价是 aw/ssll 侧要改生成流程（R-032/R-033），等于重开一个已拍板决策，已在 D-038 记录权衡。
- **不触碰** D-027（negative 反向通道）、通道1 现状、owner 原生 example_label。
- **不违背** D-002：见 §2，这不是被否的 naive RAG。
