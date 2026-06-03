# 16 · 接表 Agent（飞书表 → mapping.yaml 自动起草）

> ⚠️ **设计提案 / 草稿状态（2026-06-03）**：本文档定稿"接表 agent"的逻辑、额度、
> 运营界面与验收标准，供 review。代码骨架按本文档落地（`onboarder/` 包 + GitHub
> Actions），分批 push。标 **[待定]** 的是实现期再敲死的细节。
>
> 🔧 **实现期修正（2026-06-03 晚)**:首跑暴露两点 —— ① **GitHub Actions 连不上中转站**
> (curl 超时,网关只放行 Railway/本地 IP);② Agent SDK 的"CLI + 进程内 MCP 工具"路太脆
> (工具没暴露给模型)。故 **onboarder 改为 librarian 同款【确定性取数 + 单次非流式
> Anthropic 调用】**(不再用 agent-sdk / claude CLI / Node),且**在能连到网关的环境跑
> (本地 / Railway,非 GH Actions)**。下文凡提"agent 循环 / in-process MCP 工具 /
> GH Actions 触发",按此修正理解;架构细节以 `onboarder/README.md` 为准。

## 为什么存在

接表（onboarding）是 Truth Vault 入数据的咽喉：每张飞书投放表要先形式化成一份
`mappings/<project_id>.yaml`，sync 脚本才能按它把生贴翻译进标准 schema。

现状是**手搓**：开一个 Claude 会话，对着 7 步 SOP（[docs/04](04-onboarding-sop.md)）
走一遍、起草 yaml。`mappings/WTG_phase1.yaml` 就是这么来的——它的头部注释写着
"结构部分已按真实数据定稿；标 `[待确认]` 的部分需要 WTG 策略 lead 拍板"。
[docs/04](04-onboarding-sop.md) 的参会角色表甚至正式列着 `新会话 Claude（你）|
协助，跑流程、起草 yaml`。

**所以"让 AI 起草 mapping"不是新点子，已经在做了。** 痛点是这件事现在是**一次性、
不可复制、跨表会漂**的聊天会话：

- **冷启动**：每个新会话都要重新喂 [docs/03](03-mapping-protocol.md) 的映射表、
  [docs/05](05-controlled-vocab.md) 的词表、之前几张表的惯例。Claude 不记得上次怎么判的。
- **跨表漂移**：做到第 6、第 N 张表时，没人能把前面所有表同时装在脑子里——于是同一个
  人群一会儿标「年轻女性」一会儿「年轻女」、同一种方向在不同表拆得不一样。**这正是
  表越多越塌的地方。**

接表 agent 把这次手搓过程变成**可复制、跨表一致**的流水线。它践行
[docs/03](03-mapping-protocol.md) 早就定的对齐原则：

> 对齐工作分三段——**人定义 + 代码翻译 + LLM 抽特征**。判断字段含义是人类决策，
> 按定义翻译是代码确定性操作，特征抽取是 LLM 闭集分类。

agent 干"梳理 + 闭集抽取 + 起草"，**判断权留给策略 lead**。

## 定位与边界

**做**：拉飞书表结构 + 样本 → 判 schema 家族 → 全列交代字段映射 → 枚举并起草
方向/intent/tier 规则 → 按互动量分布推荐阈值 → 跑 10 行 dry import → 产出
**draft yaml + review brief**。

**不做**（对齐 README 原则 1「管家不做判断」）：

- ❌ 不替策略 lead 拍板**方向拆解 / tier 阈值 / 合规红线**——这些永远只出
  `[待确认]` 草稿。
- ❌ 不自动 merge 自己产出的 mapping——人审 PR 才进库（见 §运营界面）。
- ❌ 不碰写稿路径（librarian / curator）——那是同步、低延迟、要降级的链路，与本 agent
  无关。

接表 agent 是**离线、人在环、元层**工具：它做考古和起草，人做判断。

## 已定接线（本轮决策）

| 维度 | 决策 | 说明 |
|---|---|---|
| **额度来源** | **复用中转站** | 跟 `librarian` 同一个池子（`ANTHROPIC_BASE_URL`），一本账。**不**用 Claude 订阅额度（见 §额度）。 |
| **输入路径** | **飞书 API 自动拉** | 飞书 Bitable REST（镜像 `scripts` 的 `FeishuClient`）拉 fields + 样本行。凭证走 GitHub Secrets。 |
| 模型 | `claude-sonnet-4-6`（中转站已有） | 与 librarian 同款；难分析可临时上 Opus。 |
| 触发 | GitHub Actions `workflow_dispatch` | 填 `project_id` + 飞书 `app_token` + `table_id`（拉新表两者都必需，缺一即配置错误，对齐 `sync_feishu_notes_to_truth_vault.py`）。 |
| 审批 | agent 开 PR，人审 + merge | = 原则 1 的"人拍板"闸门。 |

## 输入 / 输出

**输入**：飞书表标识（`feishu_app_token` + `feishu_table_id`，如 WTG 的
`A2sybSE0pa5kcnsukAMcJ9TDngb` / `tbliiz1N4m9bCRx2`，已写在
`mappings/WTG_phase1.yaml`）。agent 拉两类数据：**① 字段元数据**（权威列名 + 单选/
多选字段的【完整】选项）+ **② N 行文案样本**（默认 N=30，看正文）。

> ⚠️ **枚举型列（方向 / 状态 / 发布笔记 / 备注）的取值必须取自 field 的 select options
> 或【全表 distinct 扫描】，绝不能只从 N 行样本凑** —— 稀有方向（1-4 行）会漏
> （NRT_phase2 有 21 个方向、多个 1-4 行变体）。N 行样本只用于看文案，不用于枚举。

**输出**：

1. `mappings/<project_id>.yaml` —— 结构部分定稿、所有判断项标 `[待确认]`
   （格式完全对齐现有 mapping，见 `mappings/WTG_phase1.yaml`）。
2. **review brief**（PR 描述）—— **只列你要拍板的项**，每项带【agent 草稿 + 理由 +
   在别的表里的先例】。把"对着空表搞考古"变成"审一份填好的、带先例的清单"。

## Agent 逻辑（对着 7 步 SOP 分工）

| SOP 步骤（[docs/04](04-onboarding-sop.md)） | agent 代劳（梳理 / 闭集抽取） | **人拍板**（标 `[待确认]`） |
|---|---|---|
| 1 元数据 | 按字段指纹判 `schema_family`；从数据填 project_id/平台/起止日期 | brand 中文名、product、category |
| 2 字段映射 | 按 [docs/03](03-mapping-protocol.md) 标准表自动配 70-80%、**全列交代**（typed/中间/raw_extra），D-021 一条不丢 | 「陷阱表」里的歧义列 |
| **3 方向拆解 ⭐** | 枚举所有「方向」取值；按方向名+文案样本起草 `content_format`/`target_audience`/`user_pain_point`（锁死受控词表）；提 `sub_directions` + `detection_signal` | **每一条拆解**（SOP 强制策略 lead） |
| 4 tier 抽取 | A/B 套标准规则；C 家族从「备注」枚举值起草规则 | C 家族边角值 |
| 5 阈值 | 算互动量分布（中位/P90/P95/P99/max）→ 推荐爆/大爆 | 最终阈值 |
| 6 合规 | 按 category 提 base_template；扫数据里出现的候选蓝词 | 红线、最终蓝词策略 |
| 7 保存+试导 | 写 draft yaml + 跑 10 行 dry import + 报错 | 批准 |

> 左列就是 `WTG_phase1.yaml` 那次**已经发生**的事。agent 只是让它每张表稳定复现、
> 且跨表不漂。

**schema 家族指纹**（[docs/04](04-onboarding-sop.md) §Step 1 快速规则）：

- 有「巡查状态」「最近检查时间」「主页链接」→ **家族 A**
- 无 A 标志，但有「关键词」「蓝词记录」「项目阶段」→ **家族 B**
- 无「方向」、无数据回收字段、大量日期化结算列 → **家族 C**
- ⚠️ **真正的新模式**（如 WTG 的"状态拆两列：笔记状态 + 流量状态"、多出「观众分析」列）
  → agent **标成 schema 演化让你定**，不默默糊进已知家族。

## 相对手搓的两个增量

1. **上下文常驻、零冷启动**：`docs/03` 映射表 + `docs/05` 词表 + **全部已完成
   `mappings/*.yaml`** 每次都在 agent 上下文里。它是**对着你积累的决策做模式匹配**，
   不是从零推。
2. **跨表一致性（"对齐"）**：全量 mapping 在手 →
   - 强制同一受控词表值（杜绝「年轻女性」/「年轻女」漂移）；
   - **复用已有方向拆解**（新表出现"直给型"→ 套 WTG 的拆法让你确认）；
   - 统一家族判定口径与阈值方法论。

   **表越多，它越值钱；手工是表越多越崩。**

## 护栏

- **受控词表 = 硬校验**：`content_format`（8 值：情感叙事/认知重构/横评对比/教程攻略/
  直给推荐/场景植入/提问求助/反差破圈）、`target_audience`（11 值：年轻女性/中年女性/
  银发女性/年轻男性/中年男性/银发男性/学生党/宝妈/伴侣家人/病患家属/通用）是**闭集**。
  一个校验 hook 直接**拒掉任何词表外的值**（含 LLM 编造）。这就是
  [docs/03](03-mapping-protocol.md) 说的"LLM 闭集分类"安全落地。
- **human gate**：`direction_decomposition` / `tier_thresholds` / `compliance`
  永远只出 `[待确认]` 草稿。agent 不 merge 自己的产出。
- **D-021 全列交代**：飞书表每一列要么映射、要么进 raw_extra allowlist、要么显式忽略；
  **未声明列整行进 quarantine**，绝不静默吞。agent 输出必须覆盖 100% 列。
- **dry-run 验证**：定稿前跑 10 行试导入，tier 抽取 / 方向拆解 / 数值清洗都过一遍。

## 额度

走**中转站**（`ANTHROPIC_BASE_URL` + auth token，与 `librarian/clients.py` 同约定），
token 从你充值的网关余额扣，跟 librarian **一本账**。

⚠️ **不用 Claude 订阅（Pro/Max）额度**：

- 订阅是给**交互式**用的（按个人座位、给本人用），接到无人值守、定时跑的服务上不符合用途。
- 2025 年 Anthropic 给订阅（含 Claude Code）加了**每周用量上限**（叠加在 5 小时滚动窗口外），
  明确针对"长时间连续 / 自动化 / 当后台服务"的用法。拿订阅喂部署 agent：① 正是被限制的
  场景；② 每周封顶会让批量接表随时被掐，还可能挤爆你自己交互用的额度。
- 中台组件该有**计量、可隔离**的预算口子，不蹭个人订阅。（退路：若网关对 agent 的 API
  表面透传不全，单配一把官方 key 直连，成本单独记账。）

**量级**：离线批处理，一张表跑一次约几毛~一两块人民币（上下文大但靠 prompt caching
命中，大头是缓存读）。接 6 张是零头——**瓶颈是网关兼容性，不是钱**。

## 运营界面

Agent SDK 无自带 GUI，界面由现有栈拼出三个面：

| 面 | 干什么 | 用现有的哪块 |
|---|---|---|
| **触发** | 发起一次接表 | GitHub Actions `workflow_dispatch`（填 project_id + table_id） |
| **审批 + 产出** ⭐ | 看草稿 + brief、改、批 | **agent 开 PR** → 在 GitHub 审 `mappings/<id>.yaml` + brief、改、merge |
| **监控** | 额度 / 日志 / 轨迹 | 成本看**中转站用量面板**；日志看 Actions run；每次 run 记一行进 `truth_vault.agent_runs` [待定] |

**审批面 = agent 开 PR** 是关键：零新 UI、`[待确认]` 即 PR checklist、yaml 可在
GitHub 里直接改、天然版本化可审计，且**就是原则 1 的人拍板闸门变成实物**。

**第一版不建 UI**——Actions 触发 + PR 审批，零新基建即可跑顺。等接了两三张表、流程稳了，
再考虑用栈里已有的 **Streamlit** 做一页（table_id → 草稿+brief → 填 `[待确认]` →
一键开 PR），给非 git 用户更友好。

## 包结构与落地计划

镜像 `librarian/` 的自包含布局（便于独立跑 / Actions 里跑）：

```
onboarder/
├── clients.py    飞书 Bitable REST（镜像 scripts FeishuClient）+ Supabase + Anthropic(中转站单次调用)
├── vocab.py      受控词表闭集（8 content_format / 11 target_audience）+ 校验器（硬护栏）
├── corpus.py     加载 mappings/*.yaml + docs/03 家族指纹 → 起草用 few-shot 上下文
├── core.py       编排:确定性取数(字段/选项/全表 distinct/样本) + 单次 Anthropic 调用 → 草稿 + 校验 + 写盘
├── eval_wtg.py   WTG 结构回归 eval（见 §验收）
├── cli.py        命令行入口（--dry-run 拼 prompt；真跑连飞书 + LLM,只需 Python)
└── README.md
.github/workflows/
└── onboard-table.yml   workflow_dispatch → 跑 core → 开 PR(⚠️ 需在能连网关的环境跑,非 GH Actions)
```

不再有"agent 可调的 MCP 工具" —— 全是 `core` 里的**确定性步骤**:飞书拉字段/选项/全表
distinct(`clients`)· 读 `mappings/` + 词表/家族指纹(`corpus`)· 词表 + D-021 校验
(`vocab`)· 单次 `call_anthropic`(`clients`,走中转站非流式)。

## 验收 · WTG 金标准 eval

⚠️ **WTG 不是"已确认的金标准"—— 只有【结构部分】定稿。** `mappings/WTG_phase1.yaml`
的头注明说：field_mapping / raw_extra / tier 规则 / 阈值【结构】已按真实数据定稿，但
direction 拆解 / tier 阈值 / 合规 / 元数据仍是 `[待确认]` 草稿、**未经 WTG 策略 lead
确认**。所以 eval **只拿【结构字段】当 oracle，绝不把草稿的判断【值】当真值**（否则等于
拿 agent 没人审的猜测当答案训练自己 —— codex PR#37 review）。

`eval_wtg.py` 让 agent **重跑 WTG**，然后对：

- **结构字段必须对上**（oracle）：`schema_family`、`field_mapping` 列集（35 列全交代）、
  `project_specific_fields_to_raw_extra` 列集、`tier_extraction` 规则、方向**名集合**、
  `tier_thresholds` **存在性**。
- **`[待确认]` 覆盖必须一致**：agent 要把同样的判断项标成待确认，不擅自拍死。
- **不比判断值**：content_format / audience / 阈值数字 / 合规 这些草稿值**不进 diff**
  —— 等 WTG 策略 lead 确认后再扩展 eval 断言它们。

通过判据：结构字段 diff = 0，且 `[待确认]` 项集合 ⊇ WTG 当时标的。

## 待验证 / 风险

- **网关透传**：agent 比单次调用用到更多 API 表面（工具调用循环、system prompt、
  prompt caching、可能 token 计数）；中转站需全透传。librarian 已走通 caching 是好兆头，
  实现期实测一遍。
- **飞书 bot 权限**：`FEISHU_APP_ID/SECRET` 进 GitHub Secrets（密钥绝不进 git，
  对齐 `mappings/WTG_phase1.yaml` 的 sync_config 注释）；bot 需对目标表有读权限。
- **枚举完整性**：方向/状态等枚举型列的取值改走 field 选项 / 全表 distinct（不靠 30 行
  样本）；N 行只用于看文案。极大表全扫一次 distinct 的成本可接受（一次 sync 也要全拉）。

## 下一步

1. review 本文档定稿逻辑。
2. push `onboarder/` 骨架 + `eval_wtg.py`（先把 WTG 金标准 eval 跑绿）。
3. 接 `.github/workflows/onboard-table.yml`，配齐 Secrets，拿一张**真·新表**首跑。

> 相关：[docs/03](03-mapping-protocol.md)（映射协议）· [docs/04](04-onboarding-sop.md)
> （7 步 SOP）· [docs/05](05-controlled-vocab.md)（受控词表）· `librarian/`（同款
> 中转站 + 自包含客户端范式）· README 原则 1（管家不做判断）· D-021（未声明列 quarantine）。
