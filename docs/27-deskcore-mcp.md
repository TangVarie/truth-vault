# 27 · deskcore · 写作台内核外置为 MCP（D-041）

> **给谁看**：想把帆谷的写作能力挂到 WorkBuddy / Claude Code / CodeBuddy 的人；以及以后要维护 deskcore 的人。
>
> **一句话**：autowriter 内容工作台的 Streamlit 界面停用，但它值钱的四个机制做成了 MCP 工具（`deskcore/`，Railway），数据仍在同一个 Supabase 的 `autowriter` schema，**一行不迁**。
>
> 设计背景见 §1（为什么搬）· 接入照 §5 做 · 维护看 §3/§4。

---

## 1. 为什么搬

团队基本弃用了自建工作台转用 WorkBuddy。两边各有各的毛病，而且是互补的：

| | 自建工作台（autowriter） | WorkBuddy |
|---|---|---|
| 规则执行 | ✅ 提示词规则输入后严格执行 | ❌ 经常忘记之前定的规则 |
| 像不像本人 | ✅ 喂自己写的内容会慢慢变成"像我在说话" | ❌ 感觉持续在跟 AI 对话 |
| 操作成本 | ❌ 一个项目 5 个提示词要点 5 次，几十个提示词散在各项目 | ✅ 流畅 |
| 速度 | ❌ 太慢太卡 | ✅ 快 |
| 重复率 | ❌ 高 | ✅ 相对低 |

读过两个仓的真实代码后，结论是：**工作台的优势是四个具体机制（可搬），劣势是四个具体缺陷（可修），两件事在同一个改动里完成。**

### 1.1 值钱的四个机制（搬走）

| 机制 | autowriter 出处 | deskcore 对应 |
|---|---|---|
| 五层 system prompt + hard/soft 分级 | `memory.py:131` `build_layered_system_prompt` | `core.build_brief` → `open_project` |
| 调校笔记自动萃取（信号 A 手动精修 diff 最高权重） | `memory.py:1154` `generate_calibration_notes` | `core.record_edit` / `distill_calibration` |
| 正负例池（人工标注） | `db.py:2169` `list_example_items` + `items.example_label` | `core._fetch_labeled` / `label_example` |
| 语义查重设施 | `dedup.py` + `versions.embedding vector(768)` | `core.check_drafts` + `draft_fingerprints` |

"规则不忘"的真身就是第一条：hard 规则进 P0，顶一句「本节每一条都必须 100% 满足」，**每次生成重新注入**，不依赖上下文记忆。WorkBuddy 缺的正是这一层。

"像我在说话"的真身是第二条：它只吃两种信号——手动精修 diff（最高权重）和迭代反馈链——并且**明确拒绝**从"没改就通过"的稿子里学（`memory.py:1191-1194`，理由是模型会从偶然选择里编造风格规则）。

### 1.2 重复率的四个根因（修掉）

1. **硬闸默认是关的。** `config.py:132` `ENABLE_DEDUP_REGEN` 默认 `"0"`。查重跑了、命中了，只写一条 UI 警告，**不重生也不拦**。
2. **只比标题，阈值过高。** `app.py:520` 只对 `title` 取向量；阈值 0.92（`config.py:140`）对标题 embedding 极高，换个说法的同角度标题普遍落在 0.85–0.90 全部溜过。正文开头、场景、结尾完全不在查重范围。
3. **提示词侧只看最近 20 条。** `db.py:1556` 从库里捞 150 条 / 最近 40 批，`generator.py:1384` 一句 `historical[-20:]` 扔掉 130 条；剩下的还只是软指令（"宁可少出一条"），靠模型自觉。
4. **正例池是 recency top-5，构成趋同回路。** `db.py:2169` 确认仍是 `created_at DESC` limit 5。模型模仿最近 5 条正例 → 新稿被标 positive → 窗口滚动 → 语感越收越窄。

第 4 条最隐蔽：监控它的 `check_positive_saturation.py` 只统计 `external_source='truth_vault'` 的行，而那列生产库里全是 NULL（push 通道从没真跑过），所以它**永远打印"没有正例"**——这个回路从上线到现在没有任何人看见过。已在 `schemas/notes_v1_8_positive_pool_saturation_fix.sql` 一并修掉。

另外，`_assign_slot_coordinates`（`generator.py:1301`，给每篇分配不同的角度×句式×词感）被移除成死代码。注释（`generator.py:1576-1584`）说理由是跟项目自己的 role 设定打架，并留了话："future iteration wants them back behind a per-project opt-in flag"。deskcore 的 `draw_angles` 就是按那条路复活的——**切入角度优先用项目自己的 `custom_roles`，没配才用通用池**。

### 1.3 慢的根因

Streamlit。`app.py` 5560 行，每次交互全量重跑。能力外置后这个问题自动消失：推理归 WorkBuddy，deskcore 只做轻量数据操作。

---

## 2. 架构

```
WorkBuddy 项目 (mcp.json 项目级)        Claude Code / CodeBuddy
        │                                      │
        └────────── MCP over HTTP ─────────────┘
                        │
            deskcore/ (Railway · FastAPI + MCP SDK)
                        │
      ┌─────────────────┼──────────────────┐
      │                 │                  │
autowriter schema   009 新增 4 张表    librarian /librarian
(8 张表原样复用)    (台账/指纹/个人      (转调, 借真实爆款经验卡)
                     笔记/精修 diff)
```

deskcore 是 truth-vault 仓的**第四个 Railway 服务**，与 `librarian/` / `onboarder/` / `worker/` 同一套模板：FastAPI + `GET /health` + `X-*-Key` 鉴权（未设则放行）+ core 纯函数 + `railway.json`。

### 2.1 隔离口径

用户 2026-08-22 拍板：**项目规则团队共享 + 个人风格私有**。

| 层 | 内容 | 存放 |
|---|---|---|
| **共享**（按 project_id） | 硬/软规则、项目 prompt 包、发牌台账、成稿指纹库 | `memories` / `projects` / `angle_ledger` / `draft_fingerprints` |
| **私有**（按 user_id） | 个人调校笔记、手动精修 diff、个人正负例 | `user_calibration_notes` / `style_edits` / `items.example_label` |

autowriter 原来靠 RLS 按 `user_id` 隔离一切。deskcore 持 service_role（绕 RLS），**由服务端自己执行这个口径**——规则按 project_id 读全量不过滤 user_id，个人层才按 user_id 过滤。

身份从 API key 解析（`deskcore/identity.py`）：一人一把 key，`DESKCORE_KEYS` 是 key → user_id 的映射。

> ⚠️ `user_id` 必须用 `autowriter.projects.owner_id` / `items.user_id` 里**已有的**那个 UUID，不要新造。`RUNBOOK.md:150-153` 记过一次：写了 service account UUID 导致 RLS 屏蔽，`list_example_items` 永远 0 行，飞轮静默断开。

### 2.2 三处刻意的改动（不是照搬）

**A. 正例不再 recency top-5** → `core.select_positive_examples`：有 brief 且 embedding 可用时按相关性排序，然后跑一遍开头形态多样性约束（每种开头只收第一条，再补满）。多样性那一步是从 `sync_truth_vault_baokuan_to_autowriter_items.py:211-269` 的两趟贪心搬的，但那边 `min_levers` 只是 advisory 不拒绝，这里是真约束。embedding 不可用时退化成 recency，与原行为一致、不会更差。

**B. 查重比全量、比三个信号** → 标题语义 + 开头精确指纹 + 正文四字串 Jaccard。四字串那条对齐 `human-writing/scripts/check_prose.py` 的跨篇指纹思路，专抓"换了词但还是同一篇"。

**C. 查重是硬闸** → `check_drafts` 是 deskcore **唯一不 fail-open** 的工具。其它读类工具出错返回带 `error` 的可用结构不阻塞写稿；查重出错必须抛。静默放行就是重演根因 1。

---

## 3. 工具面（10 个）

| 阶段 | 工具 | 说明 |
|---|---|---|
| 写稿前 | `list_projects` | 项目清单 + 各自的规则数/指纹数 |
| | `open_project` | **一次拿全**写作简报：stable / p0 / p1 / tactics。治"5 个提示词点 5 次" |
| | `draw_angles` | 发牌：n 组互不重复、避开台账的创作坐标，带 `prompt_block` 可直接贴 |
| | `borrow_lessons` | 转调 librarian，借真实爆款经验卡 |
| 写稿后 | `check_drafts` | **硬闸**：全量历史 + 本批内互比，返回 pass/warn/reject |
| | `commit_drafts` | 定稿入库：写指纹 + 给坐标销账 |
| 反馈 | `record_rule` | 沉淀规则（团队共享），hard 进 P0 |
| | `record_edit` | 喂手动精修 diff（信号 A），自动更新个人调校笔记 |
| | `label_example` | 标正/负例 |
| | `my_style` | 查看个人风格资产 |

工具的 docstring 就是模型看到的说明，写给模型看。维护者要看的原因在 `deskcore/core.py` 的注释里。

### 3.1 发牌的组合空间

主维度笛卡尔积 = `emotional_lever(12) × human_truth_archetype(19) × content_format(8) × title_structure(8)` = **14,592 组**。一次出 20–50 条离撞车很远。

`angle_key` 只取这四个主维度做指纹；情绪强度 / 时效依赖 / 词感是叠加项**不进 key**——否则同一个核心组合换个词感就被当成"没用过"，台账白记。

台账避重的两档时效：
- 真出了稿的（`consumed_version_id` 非 NULL）按 `avoid_days`（默认 30 天）算
- 只抽了没用的（占位）按 1 天算——抽了不写不该长期占坑，否则连点几次发牌就把空间锁死

### 3.2 词表

`deskcore/vocab.py`。权威源是 `docs/05-controlled-vocab.md`，改这里必须同步改那边并建 DECISIONS 记录。

补齐了 TV 原本**没有代码化闭集**的 5 个 essence 维度（`emotional_lever` / `human_truth_archetype` / `trend_dependencies` / `emotional_valence` / `emotional_intensity`）——它们此前只以自然语言存在于 `prompts/essence_annotator.md` 正文和 docs/05 表格里，`onboarder/vocab.py` 只硬编码了另外 7 组。

两条约束直接写进代码：
- `emotional_valence` 由 `emotional_lever` **唯一决定**（docs/05 §4），不独立抽、只派生
- `trend_dependencies` 的「通用」**排他**（docs/05 §7）

还带了 `LEVER_BOUNDARY_RULES`——抽到"焦虑撬动"时会把"焦虑 vs 恐惧"的判据一起给模型。docs/05 花 40 行讲这三组怎么分是有原因的，光给标签名模型会混。

---

## 4. 数据层

`autowriter-migrations/009_deskcore.sql`。**现有 8 张表一行不动**，只加 4 张 + 1 列。

| 新增 | 对应的根因 |
|---|---|
| `angle_ledger` | 跨批次没有"哪些角度用过"的持久记录 |
| `draft_fingerprints` | 查重池是进程内内存字典（`app.py:1024`），重启即空；且只比标题 |
| `user_calibration_notes` | `projects.calibration_notes` 是项目级单份，承载不了"共享 + 私有"分层 |
| `style_edits` | 手动精修 diff 的原始存放处。笔记是导出物、diff 才是事实，换蒸馏 prompt 时要能重算 |
| `items.updated_at`（列） | `sync_autowriter_decisions_to_prepublish.py:36-40` 记的缺陷：没这列只能按 created_at 过滤，漏收迟到的人工决策 |

RLS 全部 enable 不建 policy = service_role only，与 `truth_vault` 现有 15 张后台表同模式。

---

## 5. 接入

### 5.1 部署 deskcore

Railway 新建 service，config file 指 `deskcore/railway.json`，root = repo 根。

env：

| 变量 | 必需 | 说明 |
|---|---|---|
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` | ✅ | 共享 prod 库 `kduysqedrclrfevrxiie` |
| `DESKCORE_KEYS` | 生产必需 | `{"k-xxx": {"user_id": "<uuid>", "name": "Ziao"}}`，一人一把 |
| `GOOGLE_API_KEY` | 强烈建议 | embedding。不设则查重降级为纯确定性（同角度换说法的标题会漏） |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL` | ✅ | 调校笔记蒸馏。base_url = 中转站 |
| `DESKCORE_MODEL` | 可选 | 默认 `claude-sonnet-4-6` |
| `LIBRARIAN_URL` / `LIBRARIAN_API_KEY` | 可选 | 借爆款经验卡。不设则 `borrow_lessons` 返回空 |

> ⚠️ **模型 env 变量名的坑**：三个现有服务各不相同（worker `ESSENCE_MODEL` / librarian `FLYWHEEL_LIBRARIAN_MODEL` / autowriter `CLAUDE_MODEL`），已经害过一次——librarian 忘了配，每次 LLM 调用失败降级成 `[]`，外面看永远 200，查了很久（docs/19:180-200）。deskcore 用 `DESKCORE_MODEL`，且 **`/health` 会回显实际解析到的模型名和每个依赖的可用性**，让配错当场可见。

### 5.2 自测（不写一行配置）

```bash
# 逻辑自测, 不连库不联网
python -m deskcore.cli selftest

# 连库
export SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=...
python -m deskcore.cli projects
python -m deskcore.cli open --project <uuid> --tactic "经期场景痛点切入"
python -m deskcore.cli draw --project <uuid> -n 20 --block
```

服务起来之后：

```bash
curl -sS "$DESKCORE_URL/health" | jq        # 看每个依赖的 ok
curl -sS "$DESKCORE_URL/tools" | jq         # 工具清单
curl -sS -X POST "$DESKCORE_URL/tool/list_projects" \
  -H "X-Deskcore-Key: $KEY" -H 'content-type: application/json' -d '{}'
```

### 5.3 挂到 WorkBuddy

项目级 `mcp.json`：

```json
{
  "mcpServers": {
    "deskcore": {
      "url": "https://<your-deskcore>.up.railway.app/mcp",
      "headers": { "X-Deskcore-Key": "k-xxx" }
    }
  }
}
```

skill 放 `~/.workbuddy/skills/bywood-writing-desk/SKILL.md`（本仓 `skills/bywood-writing-desk/SKILL.md` 直接复制）。

> ⚠️ **鉴权头的退路**：WorkBuddy 的 HTTP MCP 能不能配自定义 header，官方更新日志只说了支持 HTTP MCP 和 OAuth（v4.7.3），没有权威文档。所以 deskcore 的 key **三种传法都收**：
> 1. `X-Deskcore-Key: <key>`
> 2. `Authorization: Bearer <key>`
> 3. `?key=<key>` 查询参数
>
> 前两种不通就用第三种把 key 拼进 URL。**这一步必须最先验**——协议层不通的话整个形态要换。

### 5.4 挂到 Claude Code

```bash
claude mcp add --transport http deskcore https://<your-deskcore>.up.railway.app/mcp \
  --header "X-Deskcore-Key: k-xxx"
```

skill 放 `~/.claude/skills/`（或项目 `.claude/skills/`）。CodeBuddy 同理，路径是 `.codebuddy/skills/`。

---

## 6. 与三个语言类 skill 的分工

仓里已经有三套并列的语言规则（`human-writing` 全禁口径 / `bywood-proposal` 散段口径 / `seeding-prompt-refiner`），**不要再立第四套**。`bywood-writing-desk` 只管流程纪律，语言层引用 `human-writing`。

| skill | 管什么 |
|---|---|
| `human-writing` | 这一篇读起来像不像人写的（去 AI 味、禁用句式、跨篇指纹） |
| `bywood-writing-desk` | 这一批守不守项目规则、跟历史重不重 |
| `seeding-prompt-refiner` | 提示词本身怎么迭代（分型、N=20 量化、单变量 mutation） |

顺带：`seeding-prompt-refiner/SKILL.md:496` 自己写过「LLM 是无状态函数……提示词再好也解决不了跨批次去重这个根本问题」，并把这条归给工作台。它诊断对了，缺的就是一个能持久记账的外部工具。它 `references/cross-batch-diversity.md` 里那四套**用户手动维护**的补偿机制（角度编号库 / 历史回避清单 / 跨批次分布档案 / 账号差异化种子），deskcore 落地后可以全部退役——这也是它自己标注的"过渡方案，不是长期方案"。

---

## 7. autowriter 的处置

- Streamlit **停服但不删仓**：代码是这些机制唯一的文档
- Supabase `autowriter` schema **一行不动**
- 现有 `librarian_client.py` 接线保留（要回滚时用）
- 停服前跑一次 `extract_negative_examples_from_autowriter.py`，把最后一批负例候选捞出来人工确认掉

---

## 8. 已知风险与未决点

1. **WorkBuddy 的 HTTP MCP 自定义鉴权头无权威文档。** 见 §5.3，已留两条退路，但**必须最先验**。
2. **馆员选卡质量从未在真实规模验证过。** `librarian/README` 写的"书架 1 张卡"是 Session #16 旧文；`docs/26` 实测已 118 张卡 / 可借 201，OKMAN 七月又进了 17 条爆款。但 118 张规模下的选卡准确率没人测过。`librarian/core.py:33` 的 `CANDIDATE_CAP=50` 注释预留了加 embedding 预筛的口子。
3. **embedding 依赖 `GOOGLE_API_KEY`。** 存量 768 维向量都是 Gemini `text-embedding-004` 产的，换模型会让历史向量全部作废需重算。第一期沿用。没有它时查重降级为纯确定性——仍能抓开头撞车和四字串重合（`selftest` 证明了这点），但同角度换说法的标题会漏。
4. **查重目前在 Python 里逐对比。** `_fetch_fingerprints` 有 4000 行上限。单项目到十万行量级时该改成 pgvector 服务端检索（`draft_fingerprints` 已经建了 ivfflat 索引，改起来不难）。
5. **"个人风格私有"与团队协作的张力。** 同一项目两个人各自驯化，风格会分叉。指纹库是共享的（互相避重），但调校笔记不共享。跑一段时间如果分叉太严重，可能需要"把我的调校笔记提升为项目基线"的操作。第一期不做，先观察。
6. **`draw_angles` 的组合空间会被慢慢吃掉。** 14,592 组、avoid_days=30，按每天 50 条算一个月 1500 组，占 10%，安全。但如果某个项目长期高频产出，要么调小 avoid_days，要么把 `trend_dependencies` / `emotional_intensity` 也纳入 `angle_key` 把空间乘上去。
