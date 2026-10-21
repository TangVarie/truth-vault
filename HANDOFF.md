# 三库交接 · 2026-10-21（最新，先看这一节）

快照时间 **2026-10-21 08:25 UTC**。上一位接手的 Claude 会话（`session_013CmhA1ySPmo4gLMqyHkhKZ`）到这里停手，owner 换人接手。停手前做了两件事：

- 不再监听 aw#115 / aw#117 的 PR 动态；
- 撤掉了自己排的定时检查，要做的事都列在下面「接手要按时做的事」里。

10-15 那一版在下面，内容没过时的照旧有效。未完成清单以 [OPEN-ITEMS.md](OPEN-ITEMS.md) 为准。这一节只写「做到一半的」和「接手要按时做的」。

### 线上现在是什么版本（08:20 UTC 读的）

| 服务 | 版本 | 怎么核 |
|---|---|---|
| 写作台 deskcore（aw） | build `f0044905bda1`（aw#116 热修），协议 `5ea3b14e1f37`。默认分支已到 `2b96b36`（aw#118 只改文档），Railway 重新部署后 build 会变，协议不变 | `https://autowriter-production.up.railway.app/health` 的 `build` |
| Jev 判定服务 | main `c2183fe`（Jev#25：只改交接文档和一处测试）；`compile.key: true`，模型 `claude-sonnet-5-5`；`comment_tools_enabled: true` | `https://judge-production-601c.up.railway.app/health` |
| truth-vault | main `e177bff`（TV#211：这份交接、D-122 收尾 SQL、`scripts/codex_gate.py`） | — |

### 正在进行的 PR，接手先看这里

**1. aw#115 写作台第二批 A–C**：TangVarie/autowriter#115。
- **状态**：head `c709793`，CI 绿，没有冲突，已是 ready。
- **Codex**：第 12 轮 08:09 UTC 开始审，交接时还没出结果。
- **内容**：交付版式由代码拼、规则的代码检查、限时正则引擎、结构指纹，口径见 aw `docs/deskcore.md` §3.9、§3.10。
- **10-21 这几轮**：
  - 第 9 轮：「必须带的话术」只管标题或正文时，那一处空着不报。
  - 第 10 轮：模板不交付的话题 / 评论，查规则还拿原稿查。
  - 第 11 轮：`^广告$` 这种锚定的话题正则，话题多于一个就漏。
  - 三轮的意见都已修推。前 8 轮每轮推之前都跑了独立复审；第 9–11 轮因为上一会话的子代理额度用完，只跑了全量测试（`c709793` 上 1674 passed）和 smoke，接手的人合并前可以补一次独立复审。
- **下一步**：
  1. 在 truth-vault 跑 `python scripts/codex_gate.py TangVarie/autowriter 115`。
  2. 输出 FINDINGS：修、在 thread 上回、推、再 `@codex review`。
  3. 输出 PASS、CI 绿、没有未解决的 thread：合并。
  4. 合并后核 Railway 部署：`/health` 的 `build.commit` 是合并提交前 12 位，协议变成 `895ed01874d6`。
  5. 写手重导 skill。服务端探针会在工具返回里提醒，计数看 `/skill-versions`。

**2. aw#117 aw E：`check_rules` 写手工具 + Jev 编题**：TangVarie/autowriter#117。
- **状态**：head `52eca1b`，CI 绿，没有冲突。08:16 UTC 被改成 ready（owner 在页面上点的），Codex 自动开始审 `52eca1b`。
- `52eca1b` 是把 aw#115 的 `c709793` 合进来的提交：冲突已解，协议重算为 `be4d668f5ab6`，本地全量 1827 passed。
- ⚠️ **它的 base 还是 aw#115 的分支 `claude/zen-johnson-m2f14s`。aw#115 合并之前不要合它**，否则 aw E 的代码会混进 aw#115。
- **aw#115 合并后按顺序做**：
  1. base 改成默认分支 `claude/xhs-content-workstation-BSEuH`，把默认分支合进来。
  2. 确认 WIP 提交 `49a3684` 里的 12 个回归测试在修复前确实失败。
  3. 修完 PR 描述里剩下的复审意见（只有标题和严重程度，不含客户内容）。
  4. 过 Codex。
  5. 上线前**先在生产跑 `migrations/015_rule_compiles.sql`**。

**3. aw#119**：TangVarie/autowriter#119，让 CI 真正跑到依赖 fastapi / mcp 的测试。owner 另开会话在做，不属于这份交接。

**已合并的交接文档 PR**：TV#211、aw#118、Jev#25，08:08 UTC 合并。
- owner 破例，没等 Codex 审最新提交，**只限这三个纯文档 PR**。这份 08:25 的更新也按同样的破例直接合。
- 改成 ready 时，Codex 在合并后自动审了 aw#118 和 Jev#25，交接时结果还没看。要是指出了真的文档错误，开一个小的文档 PR 改掉。

### aw#115 部署之后的数据操作（一步一步来，每步先备份）

1. 4 个项目设交付模板：百健士、西屋911gt、Hatherine、途鸽。途鸽用「照规则原样」那版。
2. 看一批真实稿子。
3. W-28：插 3 条硬的退路规则，撤 6 条交付格式规则。
4. 只给规则 `ec0b9bd6` 加代码检查。

另外两点：

- Hatherine 的 `a6f0075c` / `b1f17f57` 要等 D1–D7 重录。
- 计划、SQL 和逐条规则的处理里有客户的规则原文，**不进 GitHub**。10-21 已作为文件包 `ops-packets-2026-10-21.tar.gz` 发给 owner（发了两次），接手向 owner 要，照包里 `README.md` 的顺序做。

### I-16 / D-123 收尾（SQL 在 [docs/d122-repair/](docs/d122-repair/README.md)）

- **② 删 80 行旧版本闸三分**：`d123_gate3_rescore.sql`，还没跑。
  - Supabase MCP 执行删除要在 app 里点确认，10-20 卡在这一步超时，什么都没写。在 SQL editor 跑。
  - 要在没有 Daily TV sync 正在跑的时候跑，文件开头会先锁表。
- **③ NUC 15 张卡已重策展**：
  - dry-run run 39467743743，渲染 15/15，没调模型；
  - 真跑 run 39468049494，成功 15、失败 0；
  - 回读：`curated_at` 晚于恢复的 15 张，NUC 其他卡没动。
- **④ 第一晚核**：`05_after_nightly.sql`，见下面「接手要按时做的事」。

### 接手要按时做的事

原来都排成了触发进上一会话的定时检查，交接时已撤。到点手动做：

| 时间（UTC） | 做什么 | 结果写到 |
|---|---|---|
| 10-21 daily-sync 跑完之后（cron 02:17，实际常拖到 06–09 点起跑，约 10:15 之后） | 跑 `docs/d122-repair/05_after_nightly.sql`，三处都要过：<br>① 受保护列「非空 → NULL」的 unexpected 为 0；<br>② `emotional_lever` 有值而 `content_format` 为空的是 0，或者只是还没标 essence 的新笔记；<br>③ 恢复的格子还等于计划值。<br>有被冲掉的马上查原因 | OPEN-ITEMS I-16 ④ |
| 10-21 14:40 | 核 aw#116 修复后第一次 14:00 tv-sync：<br>① 没有 23502，`tv_edit_diffs` 的 `max(computed_at)` 往前走了；<br>② BJS / SPX 能算差异的对子变成 `diff_rev = 2`。<br>SQL：`select d.tv_project_id, d.diff_rev, count(*) from autowriter.tv_edit_diffs d join autowriter.tv_note_links l using (note_id) where l.lag_days is null or l.lag_days >= 0 group by 1,2;` | OPEN-ITEMS W-23、「0. 按时间」10-20 夜那行 |
| 10-22 | ① S-01：D-086 两张备份到期，核备份表和现表没有要回滚的差异，DROP SQL 给 owner 在 SQL editor 自己跑；<br>② F-03：librarian 借卡延迟对比 D-090 基线（`truth_vault.flywheel_librarian_cache.select_ms`、`/health` 的 `prompt_cache_usage`），连同 W-08 `LIBRARIAN_TIMEOUT_SEC` 要不要按 p95 重调一起下结论；<br>③ L-01：daily-sync 的 `stale_in_ssll` 连续两周是 0 的话，开 PR 去掉 C-20 的 `|| true` | OPEN-ITEMS S-01、F-03、L-01 |
| 10-23 | G-05：10-16 14:00 UTC 起 `params.source='deskcore'` 的 batch，数四样：<br>① `params.flywheel_arm`，探索臂应约 15%；<br>② `params.flywheel_arm_source`，简报传回来的占多少；<br>③ 带 `flywheel_arm_mixed` 的条数，以及 `batch_metrics` 里 `meta.mode='deskcore_commit'` 的 `arm_mixed_unmarked_item_ids` 非空的条数；<br>④ `truth_vault.flywheel_librarian_cache` 里 `library_version` 带 `:dl`、`:explore` / `:ext` 的行。<br>偏离大的告诉 owner | OPEN-ITEMS G-05 |
| 11-09 | S-02：10-09 / 10-10 两批备份表到期（名单以 OPEN-ITEMS S-02 为准），核过没有要回滚的，DROP SQL 给 owner 跑 | OPEN-ITEMS S-02 |
| 11-16 | S-02：`truth_vault.backup_quarantine_resolve_20261016` 到期，同上 | OPEN-ITEMS S-02 |
| 每周一 01:47 | OPEN-ITEMS 周检。这个 routine 每次起新会话，不依赖上一会话，**保留着** | 它自己开 PR |

### owner 定的规矩，接手照办

- **合并**：合并前 Codex 必须审过当前 head、没有未解决的意见（`scripts/codex_gate.py`），CI 要绿。10-21 的破例只限三个纯文档交接 PR 和这次文档更新，代码 PR 照旧。
- **Codex 额度**：10-21 03:15–08:05 UTC 左右，Codex 回「代码审查额度用完」，四个库都审不了，之后 owner 说已恢复。再碰到就先别合，告诉 owner。
- **不进 GitHub 的内容**：原始评论、答卷、规则原文、稿子、笔记正文都不进 GitHub（代码、测试、文档、PR、评论都不行），只放合成例子和计数。
- **写生产库**：先建备份表、再写。隔离表只有人能改（D-053）。不伪造独立标注或 `accepted_by`，不改审核员的标签。
- **密钥**：只在对话里给，不进仓库。
- **提交和 PR**：不写模型标识。

---

# 三库交接总览 · 2026-10-15

> **评论线云端交接**：[数据/回填接手说明及完整材料入口](docs/comment-handoff-online-2026-10-15.md)，可直接在GitHub阅读。

本轮接管覆盖 **2026-10-12～15**。同步/数据库/写作台生产快照截至 **2026-10-15 12:04（北京时间）**；本次评论返回与C3复验记录核对于 **2026-10-15 19:34（北京时间）**，不表示其他生产数字也在该时刻重新检查。本文汇总已做检查、实际改动、证据与下一步；日常待办仍维护在 [OPEN-ITEMS.md](OPEN-ITEMS.md)，决策原因见 [DECISIONS.md](DECISIONS.md) D-107～D-111。更早的设计与部署属于继承状态，不表示本轮重新验证或实施过。

## 接手先看这五件事

1. 闸二本轮已完成：最后重标批次和55行验证均已核验。**组合不进入L2**，未据此调整检索权重。
2. 评论工程已合并、已部署，**生产评论开关仍关闭**。旧100条参考已定，模型对照已做，但尚无上线验收。
3. 人员40条原判已固定，AI覆盖0格；C3及后续C4固定验证均完成但不推广。C4新40与AI参考225/280未达标准，详见[云端交接](docs/comment-handoff-online-2026-10-15.md)；上线未验收。
4. 10-13/14每日同步两处故障已修复并补跑成功；**修复后的首次全量定时成功仍待观察**。10-15 watchdog指向的是10-14修复前的失败，不是新的Daily失败。
5. 写作台跨项目防护已部署，5个现场专属词已配生产；带鉴权的线上拒写和借卡客户端截止仍待真实验收。

## 三库分工和交接入口

| 库 | 本轮负责内容 | 交接 |
| --- | --- | --- |
| truth-vault | 数据同步、特征与闸二、跨库决策及统一待办 | 本文；[待办](OPEN-ITEMS.md) |
| JevforCoentent | 评论HTTP、标注对账、参考评估、隔离候选 | [Jev交接](https://github.com/TangVarie/JevforCoentent/blob/main/HANDOFF.md) |
| autowriter | deskcore工具、MCP并发、跨项目防护、协议 | [写作台交接](https://github.com/TangVarie/autowriter/blob/claude/xhs-content-workstation-BSEuH/HANDOFF.md) |

默认分支：TV/Jev为`main`；autowriter为`claude/xhs-content-workstation-BSEuH`，不要向不存在的aw main交接。

## 已做检查与改动

### 1. 特征重标、闸二和结构层级

- 重标三批实际完成499/499（200+200+99），单篇补跑 [38233093886](https://github.com/TangVarie/truth-vault/actions/runs/38233093886)成功；核查按完整答案与当前题库摘要进行，不只看run颜色。
- 闸二只读 [38234131740](https://github.com/TangVarie/truth-vault/actions/runs/38234131740)、写库 [38234730010](https://github.com/TangVarie/truth-vault/actions/runs/38234730010)均成功；生产55行摘要为`c3dfab5dc85e9c31fdec9e44e43853fe158dc30b0d5e88400c2db535070c11c3`。10个取值validated，不等于每道题或后续阶段全过。
- 组合增益ΔAUC=-0.00105，95%区间跨零，**不进入L2**。最低20%结论只覆盖有完整标签支持的项目；HXZ_QD/TXQ缺负例覆盖，不声称原全量范围通过。见 [PR177](https://github.com/TangVarie/truth-vault/pull/177)、[组合修正报告](data-analysis/feature-gate2-combo-gate2-20261010-support-corrected.md)。
- G-11复评18道结构题：3道含validated取值、7道no_signal、7道unreliable、1道reversed。保留surface和30个月先验；没有跨期估计，运行时未接半衰期权重。见 [复评报告](data-analysis/structure-layer-reassessment-2026-10-12.md)。
- 继续使用已选Sonnet 5.5抽取器；没有因这轮检查切换Jev/Haiku或重开闸一。`efficacy_promise`即使validated也永不下发；新发现取值仍需owner审阅。

### 2. 评论参考、评估与候选

| 阶段 | 已完成事实 | 不能据此推导 |
| --- | --- | --- |
| 原A/B | 校验原文、逐条题面、闭集与来源；替换2条占位并让A/B补标 | 文件填满不等于来源是真人 |
| 冻结旧参考 | 100条/700格：522格A/B共识、178格AI来源仲裁；owner知情后指示采用最终裁决 | 不称独立真人金标准准确率；不按模型回改700格 |
| cb-v0.4 eval-v2 | 503/700一致，414无歧义一致，172歧义，0缺答/无效 | 未做上线验收；2条背书漏报也不等于真实HTTP绕过 |
| 一次获准C1试跑 | 553/700一致，470无歧义一致，142歧义；74修复/24回退；无歧义背书误报4→12 | 不推广C1；旧100条只能作开发回归 |
| 当前C3 | owner确认detail_level看可核对文本细节，不强制个人经历；缺回复对象不作“没有问题”的证据 | C3未试跑，不能套C1分数 |
| 独立40条 | 与dev99帖及同项目同文零重叠；OTC14/保健14/Rx12，素人36/贴主4；AI草稿280格及理由已拟 | 样本独立不表示AI参考是独立真人准确率 |
| 人员复核 | 已返回并委托完成处理；40条/280格闭集有效，原文/ID/题面映射未变；原判另存固定参考，与AI稿92格不同、覆盖0格 | 单人参考，保留定义解释分歧，不称双人金标准；本次40条C3另获一次许可并已完成；无上线授权 |

本地评估曾因全选项概率验证修复完整重跑，正式基线取eval-v2的503/414/172；初次503/411/173产物保留，不平均或择优。C1只跑了owner明确许可的一批；此前自动审批拒绝另一次语料发送的范围限制仍须尊重。

代码与详细报告在Jev库；本库见 [最终参考](data-analysis/comment-final-reference-2026-10-13.md)、[候选诊断](data-analysis/comment-candidate-diagnosis-2026-10-13.md)。对应 [TV178](https://github.com/TangVarie/truth-vault/pull/178)、[179](https://github.com/TangVarie/truth-vault/pull/179)、[180](https://github.com/TangVarie/truth-vault/pull/180)、[181](https://github.com/TangVarie/truth-vault/pull/181)，Jev9～12和aw96均已合并。

### 3. 部署、身份、协议与现场配置

- 10-15只读健康核验：Jev真实服务为`https://judge-production-601c.up.railway.app`，`ok=true/mock=false/auth.required=true/writer_keys=2/comment_tools_enabled=false`。旧`judge-production.up.railway.app`不是该服务。
- deskcore为`https://autowriter-production.up.railway.app`；核对到代码`487403b75fb0`、协议`3fdff2c0b985`、24工具、3把鉴权key、匿名关闭、judge configured且shadow。health能证明配置，不能代替带鉴权端到端验收。
- W-19生产根项目的`isolation_terms`已CAS更新并回读：痘痘贴、祛痘、去痘、抑痘、76片；保留其余default_params并兼容jsonb字符串形式，其他项目未改。旧值本地备份。
- 用生产回读配置跑本地已合代码：5词均拒且0写入、正常西屋规则允许。此项用fake库，**没有完成真实带鉴权线上拒写探针**。入稿语义归属仍是影子提示，不升硬闸。
- 10-15健康另有真实待办：7日角度149发出/73消费，漏账51%，2项目超线；这是W-06，不能因顶层`ok=true`称业务全健康。

### 4. 每日同步故障与恢复

[PR182](https://github.com/TangVarie/truth-vault/pull/182)已合并`bc81c7bf0dba7226fd5fb92a3e9bae6cd607340b`，PR和main的Python/SQL/mapping CI通过。

| 问题 | 修复与生产验证 |
| --- | --- |
| SPX「互动量」改为「互动数」 | mapping兼容新旧名，共存时新名优先（含0/空值）；同目标列断源检查保留。恢复 [38542412990](https://github.com/TangVarie/truth-vault/actions/runs/38542412990)成功：540篇同步、535快照、errors=0；7条标准指标与最新快照全部回读匹配 |
| HATHERINE合法JSON数组导致`.get()`崩溃 | 校验对象、标量和列表成员类型，错误进入既有重试/failed_queue并继续批次。续标 [38542417239](https://github.com/TangVarie/truth-vault/actions/runs/38542417239)成功：7次调用/7篇完成/0失败，282/282已标；原275篇完整行摘要不变 |

离线回归：`scripts/check_daily_sync_compat.py`；新旧列、双列0/空值、快照、断源、错误JSON重试及单条失败不掐批次均覆盖；原词表/重试/写入大小检查也通过。未改模型、标注词表或判爆口径。

SPX的27条已认领隔离仍存在。无写入预检 [38542036132](https://github.com/TangVarie/truth-vault/actions/runs/38542036132)按原dry-run规则不读取认领名单，故仍红27条；其核心列/指标检查已通过，实际同步读名单后成功。不要修改认领状态或压掉数据质量闸来清红。

**10-15状态**：watchdog [38667591742](https://github.com/TangVarie/truth-vault/actions/runs/38667591742)在09:48检查过去26小时，仍指向10-14修复前 [38529381244](https://github.com/TangVarie/truth-vault/actions/runs/38529381244)。它只计schedule，昨天的定向手动成功不算全量定时验收。截至12:04，今日Daily未出现新run，workflow active，声明10:17，历史有数小时漂移。最新特征层schedule [38608278755](https://github.com/TangVarie/truth-vault/actions/runs/38608278755)成功。不要把排队延迟或旧告警写成新的模型/同步失败；也不要提前宣称新定时已通过。

## 下一位接手的执行顺序

| 优先级 | 具体动作 | 完成判据 / 依赖 |
| --- | --- | --- |
| P0 | 观察修复后首次Daily schedule；失败就看聚合步骤点名，再查子步骤日志 | 必须是全量schedule成功；核查写入/缺失能力/剩余待标，不能只用手动SPX成功替代 |
| 已完成 | 接收核验40条/280格返回，按原判固定单人参考v1 | 原文/ID/隐藏映射未变，缺答/越界/公式0；92格异于AI稿，AI覆盖0格；定义分歧另记，不称金标准 |
| 已完成 | Jev独立40条专用评估入口 | 绑定样本/C3/题面/参考/原工作簿/模型；开发帖及同项目文本零重叠；旧100条loader不放宽；全量217项通过，真实输入预检0调用 |
| 已完成 | 本次40条C3独立复验 | 用户明确许可后完整40/40有效，172/280一致、137无歧义一致、69歧义、0缺答；相对参考背书漏报0/28、误报4/12；一次许可已用完 |
| P1 | 统一题意边界，准备下一版固定规则与新样本计划 | 不推广C3；先处理价值类别优先级、具体承接、数值细节/品牌边界及7条编辑标记；若据本40条改题，转开发用途，不继续当未见测试集 |
| P1 | owner验收报告后再推进J-01/J-02/W-02 | 再开评论、真接口小批核查、统一导入skill；J-02小批shadow亦须独立复验。primary还需绑定实际题库摘要的真实验收记录，不能伪造旧human-gold字段 |
| P1 | F-04真实客户端借卡截止、W-19鉴权拒写、W-06角度漏账 | 分别采真实延时、核对拒写零写入及正常请求、定位超线项目流程；不随意把影子升级硬阻断 |
| P2 | G-02/G-17/G-12及G-05 | owner审新发现；补完整项目标签覆盖再复评最低20%；预注册季度/跨期窗口；运行时权重另立工程，当前未实现 |

其他历史待办继续按OPEN-ITEMS逐条核，不把未查过的条目自动划掉。Jev现有配置早在10-08把OKMAN/OKMAN_phase1加入`rx_cleared`，本轮未改变；此前清单“等合同”过时。仍未清出的Rx项目保持403；项目层权限是另一道独立门槛。

## 本地材料交接与来源边界

此前仅公开代码、汇总和摘要；2026-10-15 owner获知三仓公开后明确许可本批完整Excel/交接包公开归档，现统一在[Jev云端目录](https://github.com/TangVarie/JevforCoentent/blob/main/docs/handoff/2026-10-15/README.md)，含逐条阅读页和原始快照附件。以下原工作区路径仅作历史索引，不再要求接手人依赖该工作区。不要重抽一批凑相同ID；凭据不公开，未来素材不自动继承本次发布许可。

| 材料 | 当前工作区位置 |
| --- | --- |
| 旧冻结100条/700格及正式评估 | `/workspace/annotation-packets/J03-health-20261013-final-reference/`（正式live子目录`evaluation-live-4wj31n53`） |
| 替换后样本与原题面 | `/workspace/annotation-packets/J03-health-20261013-round2/` |
| C1授权、试跑、24回退/74修复 | `/workspace/annotation-packets/J03-health-20261013-candidate-experiment/`（`candidate1-live-gnjpf90t`） |
| 新40条样本、C3题面、AI草稿 | `/workspace/annotation-packets/J03-health-20261013-independent-holdout/` |
| 返回单人参考及核验 | `/workspace/annotation-packets/J03-health-20261015-holdout-reference/`；reference/manifest、92格对账、返回备注、validate-only状态 |
| 给复核人员的文件 | 上述目录`40条评论_复核人员直接填写包.zip`；Excel与说明在`给复核人员_40条中文答题包/` |
| W-19配置前后与本地探针 | `/workspace/rollout-audits/20261013/w19-project-config-before.json`、`w19-project-config-after.json`、`w19-guard-validation.json` |
| 10-14故障与恢复前后核查 | `/workspace/rollout-audits/20261014/run-failure-diagnosis/`（`before-recovery.json`、`after-recovery.json`、`recovery-runs.json`） |

关键SHA-256：旧参考`18ac3677862d62f72a4d48287ce26e39a1cc623fdb10dfd067e47435d04cdcf6`；新40样本`acd6b5de112eb15000f2b9aa91226a8374fd363bc879af5bdd2c15a774544d38`；C3题库`ac8260ddbe5a5614fa9da31154f9eb2f5438e444b2141bf55ef1c74d89fea48e`；新40题面`c48ffab04fb79dea43f630cc361d512b88ce1528fb89aa412894d2b2a339e941`；AI草稿`42de2e005027378739d2a53977a57dea1984cffcf6a07e2beda8eca9c360ede6`。更多绑定见本地manifest及Jev交接。

凭据按既有环境绑定使用，不从聊天复制到文档、仓库或产物。当前managed环境未绑定密钥不表示GitHub生产secrets缺失；也不表示可以重发历史语料。

## 只读排查入口

```bash
gh run list --repo TangVarie/truth-vault --limit 20
gh run view RUN_ID --repo TangVarie/truth-vault --json jobs
curl -fsS https://judge-production-601c.up.railway.app/health
curl -fsS https://autowriter-production.up.railway.app/health
```

本次环境的`gh run view --log/--log-failed`曾返回空内容；不能把空日志当没有错误。可用GitHub job日志API或连接器`github_fetch_workflow_job_logs`，并读取最终聚合步骤的真实outcome。`continue-on-error`会让中间步骤看似success，最终聚合才是整批结论。

**10-15 19:34（北京时间）复核返回与C3复验补记：** [Jev详细返回说明](https://github.com/TangVarie/JevforCoentent/blob/main/docs/comment-holdout-return-2026-10-15.md)。单人参考SHA-256 `953dc0975d58574045324d55b7f01b97a352b724c12e2c08ee8ff616045341d3`。冻结仅固定比较版本，`definition_conformance_accepted/human_gold_ready/release_accepted`均false；C3、旧700格、生产配置未改。


## 评论线本轮收尾 · 2026-10-15 20:28（北京时间）

用户委托整线完成后再交接。此前Jev #14与TV #185已合并；[Jev #15](https://github.com/TangVarie/JevforCoentent/pull/15)固定C4七题判法并保留模型/闭集顺序/阈值/路由，初次231项工程测试通过，审阅后242项通过。20条虚构合成131/140，另有本地HTTP联真实Jev的纯虚构单条/整组7次请求核查，均不冒充生产效果或鉴权端到端验收。

自动审批最初拒绝C4真实出境；用户随后明确“允许本次C4共80条真实验证”，已完整执行旧40开发回归/新40 AI参考，各40/40有效、0缺答。旧40原判完全不改，一致187/280，较C3修复26/回退11；新40 AI参考一致225/280、无歧义一致193、歧义57。新40逐题36/39/32/32/29/30/27，相对AI参考背书漏报1/32、误报1/8；该漏报另有三题歧义，非已证HTTP漏放。

**本轮不推广C4**：总80.4%低于85%，语气/安排低于每题75%，无歧义背书漏报1高于0。没有临时放宽标准、回改参考或追加候选追分。新参考明确AI来源，不称独立真人准确率；本40条既已分析，下一轮据此改题后须转开发用途。生产评论继续关闭，评论账本批次0，未shadow/primary、未群发重导skill；正式验收记录要求保留。

本轮工程、固定验证和不发布结论已收尾，下一轮应先决定主观读感是否适合作原子题、主行为边界如何独立复核，再制定新参考/新样本与预算；不得重跑旧A/B或把已完成事项退回未开始。完整证据和后续边界见Jev #15的 `docs/comment-line-closeout-2026-10-15.md`，私有材料在 `/workspace/annotation-packets/J03-health-20261015-line-closeout/`；其他12:04生产快照本次未重查。

**C4审阅补丁说明：** 当前评估器v2已补原判独立摘要、20/40/40范围、调用前阈值类型/范围和全选项概率检查。初次v1批次未保存完整概率向量，仅作为历史诊断，不能追认严格v2验收；无追加模型调用。三组v2零调用预检与242项工程回归通过，见Jev收尾报告。
