# OPEN-ITEMS · 三仓未完成清单（truth-vault / autowriter·deskcore / JevforCoentent）

> **10-22移交下一位执行：** 先读 [三仓接手执行书](docs/handoff-2026-10-22-next-owner.md)，再按本表销项。授权、#117最终head、Railway入口、备份/模板/规则顺序与回滚已写全；本轮交接没有继续生产写入。

> **10-21 交接（08:25 UTC 换人）：** 手上做到一半的 PR、接手要按时做的事（原来的定时检查随交接撤了，改成手动），见 [HANDOFF.md](HANDOFF.md) 最上面一节「三库交接 · 2026-10-21」。

> **10-15交接核对：** 本轮检查、改动、生产证据与材料索引见 [HANDOFF.md](HANDOFF.md)。人员40条已返回，C3一次复验172/280暂不推广；C4获此次明确许可完成真实80条，新40与AI参考225/280未达标，本轮不推广；J-05已查到10-12定时成功；J-10不再按“等合同”重复申请既有许可。

> **这份清单为什么存在。** 定了「后做」「等闸二」「等 owner」的事，散落在 DECISIONS、各仓 docs 和审计报告里，没人追就没了。
> Jev 的评论能力就是这么丢的：回路代码写好了，没有接口、没有工具、没跑过一次，写手那边一直用不上，没有任何地方提醒过。
>
> **规矩**（2026-10-12 owner 要求「整个项目里没完成的点要记得」）：
> 1. 任何一条决定里写了「后做 / 下一轮 / 等 X / owner 待定」，**同一个 PR 里**在这里加一行；没加不算定完。
> 2. 关一条要有证据（线上查询、run 号、PR 号），关了挪到文末「已关」并写日期，不直接删。
> 3. 每周一有一个定时检查（routine「OPEN-ITEMS weekly review」）逐条对线上核状态，有变化就开 PR 改这份文件，并给 owner 发一段摘要：本周到期的、状态变了的、过期没动的。
>
> **怎么读**：「谁」= 工程（Claude 做）/ 你拍板 / 你动手 / 运营。「核」= 2026-10-12 这一版对线上或代码核过；「未核」= 只有文档依据。
> 来源写 D 号或 `文件:行`；`aw:` = autowriter 默认分支 `claude/xhs-content-workstation-BSEuH`，`jev:` = JevforCoentent main。
> 首版由 2026-10-12 三仓扫描生成（TV 的 DECISIONS / docs/28 / 审计报告，aw 的 deskcore 文档与 runbook，Jev 的 docs/00 / 01 / 31），并对线上抽查。

---

## 0. 按时间：最近要到期的

| 时间 | 事 | 条目 |
|---|---|---|
| 10-15 已完成 | 修复后首次 Daily 全量定时跑成功（run 38698494948，07:24–08:00 UTC）；watchdog 明天按 26h 判据自然转绿 | 已关 I-14 |
| 10-15 已修 | 通道 2 恢复：owner 改了馆员服务的 Railway 变量，12:50 UTC 写作台借卡成功（RIO，5 张卡） | 已关 L-05 |
| 10-12 已完成 | 闸二报告和 55 行验证结果已写库并核对完整摘要；10 个取值 validated，组合不进 L2；下一轮接评论能力 | 已关 G-01；D-107；J-01 |
| 10-16 已定 | 特征层留在 Railway worker（S-08）；隔离表不做完整版，2,477 条已入库的旧隔离行标 resolved（I-03） | 已关 S-08、I-03 |
| 10-19 已核 | 节后周产出：主写手回到 9 月下半月水平（10-12 周发牌 179、入库稿 104）；另一位写手 9-22 后没再用写作台，途鸽这周 22 篇写作台没接住（原因是 skill 没被调起来，已修，见已关 O-04）；西屋911gt 已接 TV | O-03、O-04、W-25（都已关） |
| 10-26 周一 | 看角度台账灯判据 C：途鸽 / Hatherine / 西屋911gt 还亮不亮（aw#109 上线后第一周）。西屋911gt 是 10-20 新看到的同一形状：XIWU_phase2 近 7 天发出去 60 篇全是补录副本，写作台 10-14 那 20 篇稿子的标题和正文开头在 88 篇里一篇都找不到（只能说明发出去的不是这 20 篇） | O-04（已关，留验证） |
| 10-27 | 读写作台用上率灯第一次输出（10-26 周一夜跑，看 10-05～10-19 发布的笔记）：各项目接住率、未改动率是数还是「待重算」、哪些项目亮黄，数记进 docs/32 §4 | L-06 |
| ≈ 10-22 | 删 D-086 两张备份；librarian 延迟对比 D-090 基线；daily-sync 去掉 C-20 的 `|| true`（条件：`stale_in_ssll` 连续两周 0） | S-01、F-03、L-01 |
| 10-16 已关 | 判定 8 秒截止不动（实测最长 4.3 秒）；入库段变慢到 12 秒，aw#100 让判定只拿整次回包 20 秒里剩下的（已部署，build 73117bd） | J-08（已关）、W-21 |
| 10-16 已上线 | owner 验收 D-112；07:15 UTC 生产开关打开，写作台用真实写手 key 核过两个评论工具；aw#101、aw#102 已部署（协议 `d59368a8f8ad`）；J-02 全量 shadow 9,766 条已写已回读 | J-01（已关）、J-02、W-02 |
| 10-16 红→已修 | daily-sync 两步红：essence 的中转站 key（GitHub secret）被拒，429 锁（S-10，owner 10-16 换 key，gateway-probe 回 200）；SPX 18 条抖音行因表格行序变了被隔离，TV#193 修（I-15，10-17 夜跑后核） | S-10（已关）、I-15 |
| 10-16 已关 | 发牌「漏账」主要是 Hatherine 的稿子直接进了飞书、模型没同时调 `commit_drafts`；每日飞书 → TV 同步已补上指纹，角度重复 2/261，不加闸、不用问人 | W-06（已关）、W-22 |
| 10-16 已上线 | 漏账灯加原因标签：超线项目标「稿子进了飞书但没走 commit」/「飞书里也没有」/「查不到」，灯本身不因此变绿（aw#103，build `4833ad8`；线上 1 个项目超线、属于前一种）；`/health` 按 key 传法计数 | W-22（已关）、W-09 |
| 10-16 已上线 | 写手已重新导入 skill；服务端 skill 版本探针上线（aw#106，build `3c6bb47`，协议不变）：旧版或没核到版本的写手，工具返回值里带升级链接和「更新技能/bywood-writing-desk」，计数看要 key 的 `/skill-versions` | W-02（已关） |
| 10-18 已定 | 拍板类一次判完（D-119）：12 条关、6 条转工程、I-01 里「删除」归宿定了，W-20（写手用的模型）owner 定了维持 gemini。10-17 核：SPX 18 条沿用库里正文、不再隔离；闸三首批 6 篇已打分；D-113 生效 | I-15（已关）、G-03、W-20 |
| 10-19 已上线 | 写作台改版（D-120）：写完自动存档 + Jev 参考分给写手看（不拦），撤掉人审 / 导出，评论按链接写；人改的稿也认（`edited`）、改动差异每周一份摘要（aw#107 已部署，build `4bc41c8`，协议 `af2e95ae314e`；迁移 013 04:45 UTC 已上生产）；夜跑撤掉人审同步、外部卡别家品牌名换「某品牌」、每季度找新特征（TV#202） | J-07、W-23、W-24、G-18、J-14 |
| 10-20 已修 | 轮转复查三处：① 10-19 夜跑闸三红——2 篇 Hatherine 排期稿 9-30 入库当天用旧模型标了 essence、10-18 才发，不是闸三期间换标注器；备份后清掉标注时间、backfill 用冻结标注器重标完（10-19 11:03 UTC）。② 写作台跨项目检查 15~20 篇一批全超时、连品牌词标记一起丢（aw#110 已合并）。③ 改稿差异把稿子末尾的 #话题 行记成"人删了一句"（首晚 440 条里 125 条），摘要会教写手少提品牌；aw#111 + 迁移 014 已上，摘要在重算前不出 | G-03、W-19、W-23 |
| 10-20 夜 | 核 tv-sync 按 `diff_rev = 2` 重算旧口径差异（aw#113 把口径从 1 升到 2）：首晚 440 条里约 228 条发布前那版的对子（加上当晚新对上的）变成 rev 2、"改过"数明显下降；212 条 `lag_days < 0`（发布后才存进写作台的那版）不重算、留在 rev 0，是设计如此（W-27、docs/32 §1），不是重算失败。核 10-20 夜跑闸三 rc=0。**10-20 14:40 核过**：HATHERINE / LNKT / RIO / TUGE 发布前那版的对子全是 rev 2（111 条，改过 73）；`lag_days < 0` 的 214 条留在 rev 0（设计如此）；BJS 65 条、SPX 50 条没重算——当晚差异写库 23502（同一块里新算的带 `computed_at`、同一版重算的不带，PostgREST 补 NULL），aw#116 已修并部署（`f004490`），10-21 14:00 那次补算，14:40 再核。闸三：10-20 daily-sync 成功，Hatherine 两篇 08:15 已用冻结打分器打分；写作台 10-20 六批跨项目检查都是 shadow | W-23、G-03 |
| 10-20 已恢复 · D-123 已合并 | 夜跑批量写把没带的列冲成 NULL（D-122）。恢复已跑完（10-20 约 16:35 UTC）：1,102 格 / 744 篇，回读全部等于计划值。闸三已重冻为 `essence-v1-93035a562b2e`（D-123，TV#210 已合并）。收尾三件事：① 备份并删掉 80 行 v1 分**还没跑**：SQL 在 `docs/d122-repair/d123_gate3_rescore.sql`，Supabase MCP 执行删除要在 app 里点确认、10-20 超时没写进去，在 SQL editor 跑；不删也不影响打分，只是「v1 行为 0」那条核要等删完；② NUC 15 张卡**已重策展**（dry-run run 39467743743，真跑 run 39468049494，成功 15、失败 0）；③ D-122 合并后第一晚核（`docs/d122-repair/05_after_nightly.sql`）：受保护列「非空 → NULL」0 条（`tier` / `tier_source` 置空、且同一条 UPDATE 写了 `tier_cleared` / `tier_unmapped` 旗子的不算），`emotional_lever` 有值而 `content_format` 为空 0 篇 | I-16、G-03 |
| 10-21 daily-sync 跑完后（约 10:15 UTC 之后，手动） | D-122 第一晚核：跑 `docs/d122-repair/05_after_nightly.sql`（受保护列「非空 → NULL」0 条、`emotional_lever` 有值而 `content_format` 为空 0 篇、恢复的格子还等于计划值），结果写进 I-16 ④ | I-16 |
| 10-21 14:40 UTC（手动） | 核 aw#116 修复后第一次 14:00 tv-sync：没有 23502；BJS / SPX 发布前那版的对子变成 `diff_rev = 2`。SQL 在 HANDOFF.md 10-21 那节「接手要按时做的事」，结果写进 W-23 | W-23 |
| aw#115 Codex 过后 | 合并写作台第二批 A–C（aw#115，`python scripts/codex_gate.py TangVarie/autowriter 115` 输出 PASS、CI 绿、没有未解决的 thread），核 `/health` 协议变成 `895ed01874d6`，写手重导 skill。之后按顺序：4 个项目设交付模板 → 看一批真实稿子 → W-28 退路规则 → aw#117 rebase 过 Codex、先跑迁移 015 再上线 | L-07、W-28、J-15 |
| 11-09 之后 | 删 10-09 / 10-10 两批备份表 | S-02 |
| A–C 上线 + 28 天 | 写作台第二批 A–C 上线四周后判接住率走向（上线日以 aw#115 部署那天为准，10-21 还在等 Codex）：不动就回头看内容本身 | L-07 |
| 10-31 | 复查 Supabase 10-30 授权变更：public 的默认授权变了、现有 23 个对象（5 张 ssll 表 + 18 个看板视图）的授权没变、看板照常有数 | S-13 |
| Railway 恢复部署时（等官方通知） | 按 [事件记录](docs/incident-railway-2026-10-22.md) §4.2：重连 GitHub、核变量没被改、各家换新密钥、内部钥匙两端一起换、按 judge → librarian → tv-worker → onboarder → deskcore（含 7ec8c48）→ tv-sync → linkcheck 部署、Vercel 看板重新部署并核对、停用 Supabase 旧版密钥、发写手新钥匙、删已停的 Streamlit；然后 W-23 补跑和交接执行书 A–D | S-12、W-23 |
| 闸二之后 | 评论能力（J-01 起）、写作台工具阻塞（W-01）、P3 / P4、抽取器与 judge 出影子期的决定 | §1、§2、§3 |

---

## 1. 特征层与闸二 / 闸三（docs/28）

| ID | 事 | 状态与证据 | 谁 | 触发 / 到期 | 来源 |
|---|---|---|---|---|---|
| G-03 | 闸三第一轨：冻结现有 essence 打分器，冻结日之后发布的笔记开始写 `content_scores` | **现行打分器 `essence-v1-93035a562b2e`**（10-20 重冻，D-123），冻结日仍是 10-17。**10-16 已冻结开工**（D-118）：打分器 `essence-v1-322f02c9465f`，冻结日 10-17，daily-sync 每晚给新笔记打分，灯 `GATE3_SCORE_CHECK_DONE` 拖红；要最低档 ≥212 / 其余 ≥847 篇落标签。近几周每周只落 30–50 篇，回到每周 200 篇约 11 月底出结论，否则要半年以上。**10-18 首批**：6 篇（BJS 3、TUGE 3，项目内分位 0.05–0.98），标注器对不上 0，灯 rc=0。**10-19 红**：冻结后发布 31 篇，17 新打、12 已打、标注器对不上 2——是 Hatherine 两篇 9-30 入库就用 opus-4-6 标过的排期稿（10-18 才发），不是换了标注器；全库冻结后发布 / 排期的笔记里只有这 2 篇是旧标注器。备份 `truth_vault.backup_gate3_preannotated_20261019` 后清标注时间，backfill-essence 用 sonnet-5-5 重标（10-19 11:03 UTC），10-20 夜跑会给它们打分。**10-20 发现**：冻结打分器的训练集和切点里有被夜跑批量写冲掉的 F / U token（10-16 前 703 篇形态为空、NUC 160 篇训练样本没有人群），恢复后权重和 NUC / NRT_phase2 / SPX 的切点会移；10-20 定 A（owner 授权代定）：恢复回读后重冻、10-17 起约 80 行备份后按新版重打，见 I-16、D-122 修复计划第 4 条。**10-20 已重冻**（D-123）：恢复回读之后，同一份 `freeze-essence-v1.sql` 原样重跑，四段 md5 和库里一致。新文件 `scorer-essence-v1-93035a562b2e.json`，旧文件留档不读；冻结日、判据、标注器都不变。变化：训练集 4,947 篇、正例 280、17 个项目；权重变化超过 0.05 的有 13 个（U:宝妈 +0.38 最大）；NUC 的 20% 线 +0.114，NRT_phase2 +0.059；XIWU_phase2 有了自己的项目切点。已打的分正好 80 行，全是 v1。D-123 的 PR 合并后跑 SQL 备份并删掉，下一次夜跑按新版重打。离线重算：XIWU_phase2 42 篇换成项目切点，最低 20% 的从 5 篇变成 6 篇。重打后核：新版本行数 = 冻结日之后有 essence 的篇数，v1 行为 0，灯 rc=0 **10-21 只读复核**：新版分数 106/106、该打而未打 0，原 80 篇全部重打；旧版仍 80 行、备份表未建，D-123 清理仍未完成。 | 工程 | 每周一报进度；12-15 复核速度；删除 SQL 还没跑（`docs/d122-repair/d123_gate3_rescore.sql`，在 SQL editor 跑），删完下一次夜跑后核 | D-118；D-123；docs/28 §6.3 |
| G-04 | P3：冻结「essence + 特征」打分器作为闸三第二轨，写作台稿子影子打分（`aw_version`），每周看「落在历史最低 20% 的稿子占比」 | D-107 本轮组合未过（AUC 增益 −0.00105、95% 区间跨零），本轮不启动；G-03 的 essence 第一轨仍可独立推进。挑稿的人怎么看「最低 20%」已定（D-119，原 G-07）：一列「建议改」+ 一句理由，不排序、不挡交付。D-120 撤了 `review_drafts` / `export_drafts`，这一列改放在 `score_drafts` 的返回里（和参考分并排） | 工程 | 另行预注册的新一轮组合评估过线后 | docs/28:371-373、:432；D-107 |
| G-05 | P4 一组：卡片视图加 `validated_hits`；librarian「已验证规律」缓存块（`gate2_run` 进 `library_version()`）；`prepublish_evaluations` 写模型行 + 按版本回填 `actual_tier`；15% 批级随机探索臂（与 aw 一起）；`v_dash_feature_perf` 和结案报告特征表 | 下发清单已定（D-116：问号 / 结尾问读者 / 求助 / 品牌位置一句，emoji 和「不提品牌」不发）；指令放题库外的批准层 `prompts/desk_delivery_v1.json`。**10-16 已上线**：卡片 `validated_hits`、馆员「已验证规律」块（TV#195，下发前对库核闸二结果）、写作台 15% 对照臂（aw#104，一场写作只分一次组，臂记进 `batches.params` 和 `batch_metrics.meta`，跨臂改稿标 mixed）；deskcore 生产 `2c2cf51`。剩：`prepublish_evaluations` 等闸三；第一批分了臂的稿子发出去之后核一次库里臂的分布（约 15% explore）、`flywheel_arm_source` 里 `brief` 占多少 | 工程（+ aw） | 闸三后（评估行）；10-23 核臂分布 | docs/28:353-392、:433；D-116 |
| G-06 | `rank_score` 账号项改成收缩后的账号先验；先修 `personal_bao_rate`（分母含风控 / 删除、分子含数值推断）；改完把书架前 20 前后对比贴进 DECISIONS | 没做 | 工程 | P4 | docs/28:358、:479；D-097 #4 |
| G-08 | 退役 `v_l2_labels_v1` | 没做 | 工程 | 闸二第一轮对完账 | D-067 |
| G-09 | 下一版题库：代码特征 choice 题按取值写方向；新增美妆 / 母婴等项目时复查五道 v2 题面的例子；闸一没过的三道（具体时间 / 地点 / 身体感受）改题面后重过闸一（D-119，原 G-10） | 等下一版 | 工程 | 题库升版 | D-106 #4；D-082 |
| G-11 | 结构类题的层级和半衰期（surface、30 个月）按闸二跨项目稳定性重估 | 工程复评完成：见 `data-analysis/structure-layer-reassessment-2026-10-12.md`；18道中3道含validated值、7道no_signal、7道unreliable、1道reversed；保留surface/30先验，30个月尚无时间估计，跨期验证留季度复跑 | 工程 | 下一次季度闸二（G-12），跨期窗口和支持量预注册后验证 | docs/28:475；D-107 |
| G-12 | 闸二每季度重跑 | 没排期 | 工程 | 每季度 | docs/28:414 |
| G-15 | P5：「投流后增量」做第二标签 | D-119：现在不做。10-18 生产只读：「维护效果」有值 13 篇、「维护时间」27 篇、标了投流 8 篇 | 工程 | 「维护效果」有值 ≥200 篇且跨 ≥3 个项目（周一例行检查数一次） | docs/28:434 |
| G-18 | 每季度找一次新特征候选（D-120）：`feature-discovery.yml`（1/4/7/10 月 2 号）按项目对照上一季爆 / 趴，出候选题报告，只用哈希切出的一半笔记；候选进题库照旧走 G-09 那条路（草案 → 闸一 → 闸二只用另一半或下一季新笔记） | 10-19 上线（脚本 `scripts/discover_feature_candidates.py`，CI 跑离线自检）；首次定时跑 2027-01-02。要提前看可以手动触发（dry_run 先数样本） | 工程 | 每季度；首跑后挑候选并进 G-09 | D-120 |
| G-17 | 最低20%爆率恢复覆盖原全量分析集：为 HXZ_QD/TXQ 的负例补足代表样本，再按新的预注册范围评估 | PR #177 复核发现两项目评估集缺负例整格；本次更正排除它们，只报告有完整标签覆盖项目的最低20%，不声称原全量判据通过 | 工程 | 下一轮需要原全量范围时；不挡本轮「组合不进L2」结论 | D-107 复核；PR #177 |

## 2. Jev（判定服务）

> 定位：一个判定服务挂八个位置（特征层、TV 评论、借卡、发牌、入库判定、三省六部、素人初稿、外部语料），见 jev:docs/00、docs/31。
> 10-12 核：在跑的只有**入库判定**（今天 30 篇稿、690 行账本）、写手手动判稿（deskcore 转发 `judge_draft` / `repair_plan_for` / `list_banks`）、**外部语料**（10-08 入库 200 篇，正文中位 426 字）。账本里 `comment` 0 行、`ssll_sample` 0 行。

| ID | 事 | 状态与证据 | 谁 | 触发 / 到期 | 来源 |
|---|---|---|---|---|---|
| J-02 | 评论回填 ②：9,649 条评论跑运营侧（意图 / 像不像安排的 / 类型）+ 读者侧 7 题，进账本 `subject_type='comment'`，评论构成做闸二候选特征 | **10-16 全量 shadow 已完成**：run 38868417905（07:37–07:55 UTC），run_tag `shadow-comments-38868417905`。9,766 条 = comments 表全部；读者侧 68,362 行、运营侧 19,532 行，无效 0、错误 0、没用续跑；产物逐文件扫过没有原文。构成：OTC药素人 5,227（背书 54%、点名 34%、像脚本 47%）；保健品素人 1,227（背书 84%、像脚本 83%）；处方药素人 1,172（接住帖子只有 33%）；美妆素人 307（背书 98%、像脚本 97%）。表里素人评论大多是铺评的样子，评论构成要按来路分开才能当特征。D-119：进闸二时要报一次「去掉运营从飞书删掉的那批评论」（OKMAN 768、LNKT 244 等）的敏感性结果 | 工程 | 先定来路区分口径，再做评论构成进闸二；primary 等绑定当前题库摘要的验收记录 | docs/31 §4.1、§7.2；D-111 |
| J-14 | 外部语料用起来（378 篇，5 个品类，按评论 ≥50 只有 124 篇算爆） | D-117：不进主库、不当爆文。① 每周方向复核（`check_external_direction.py`，daily-sync 每周一，advisory）；10-16 三条规律外部都不到 30 篇，判「样本不够」。② 外部参考书架（`librarian/external.py`）：88 张上架，只给写作台、同品类、每次最多 2 张。10-16 TV#196 已合（Codex 额度用完，换独立评审两轮，5 处修完）。aw 工具说明补了 `external` 的意思（aw#105，只改工具说明、不用重导）。D-120：别家品牌名换成「某品牌」再上架，不再整篇不收（10-19 多上架 5 篇）；点了我们登记品牌的照旧不收。剩：方向复核攒够 30 篇后第一次出判定时看一眼 | 工程 | 每周一看灯 | D-117；jev:docs/00 #11 |
| J-07 | 参考分的口径复核（原「judge 出影子期」） | **D-120（10-19）出影子期**：`score_drafts` 每篇回参考分 + 最多 3 条修改建议给写手看，仍不拦（aw#107）。10-19 生产只读：影子期 7 条硬伤 p 全在 0.54–0.69，所以分「有把握（p≥0.7）−25 / 拿不准 −8」两档。剩：有把握的硬伤攒够 30 篇时冻结样本、抽核准确率 ≥80%，不够就调 `SCORE_SURE_P` 或扣分；最低 20% 仍跟 G-04 走 | 工程 | 有把握的硬伤攒够 30 篇（`batch_metrics.meta.judge[].score`） | D-119 #7；D-120 |
| J-10 | 核对生产Rx策略与仓内既有许可是否一致 | 仓内10-08 PR5已把OKMAN/OKMAN_phase1加入rx_cleared，本轮未改；project_layer_cleared 10-20 改成 `["*"]`（D-121，Rx 闸不变、`rx_cleared` 不认 `*`）。Jev 部署后用 `/health` 或带鉴权请求的 `policy` 回显核一次；其他未清出Rx仍403 | 工程 | 有合法鉴权的下一次实际请求核对，不重复索取已有合同许可 | jev:config/data_policy.yaml；HANDOFF |
| J-11 | 「只判 `score_drafts`（原 `commit_drafts`）存档的稿、补录稿靠 TV 事后抽取」这条写进 TV DECISIONS；核 TV 抽取确实覆盖补录的项目 | 没记 | 工程 | 随时 | aw:runbook:951 |
| J-12 | `tv_project_map` 完整性：没映射的项目一篇都不判 | **10-16 核**：近 7 天活跃的 5 个写作台项目里只有西屋911gt 没映射，其余 4 个都有。**写稿和借卡不受影响**（借卡不走这张表）；没映射期间只少两样：入库时的影子判定记录（10-14 那批 20 篇 `not_configured`），写手侧 `judge_draft` 判不了这个项目。映射本来就在项目建好飞书表、TV 里有了项目之后做；现有 `XIWU_phase1` 是西屋按摩椅 GT33（08-29 结束），不是同一产品 | 工程 | TV 里有了西屋 911GT 项目之后 `tv-map add` | aw:runbook:952 |
| J-15 | 写作台第二批 E：自由文本规则编成 Jev 是非题，结果给写手看（只提示不拦），拿人改标定 | **owner 10-20 全部放行（D-121）**：Jev `project_layer_cleared` 改 `["*"]`（Rx 闸不变），规则原文可以发给 Jev 编题。Jev 侧（Jev#23，10-20 合并部署 `dde0e4f`，`/compile_rules` 线上已在）：通配放行、`POST /compile_rules`（规则 → 是非题 + 能用代码查的规则给出代码检查；题号带规则原文 sha 和题目指纹）、Jev 格式题可带 `scope`（标题 / 正文 / 全文）。写作台侧：编好的题存 `autowriter.rule_compiles`（规则 id + 内容哈希），人手检查保留在 `memories.rule_payload`，新工具在打分之后查规则、硬规则记必须改、软规则记建议改；内联 `project_bank` 发、单独 run_tag。软规则从简报开头挪走仍等标定（`tv_edit_diffs` 发布前人改，`lag_days ≥ 0`、`diff_rev ≥ 2`） | 工程（aw） | aw 侧查规则工具已写好：TangVarie/autowriter#117（ready，叠在 aw#115 上：`check_rules` 工具 + 迁移 015）。10-21 接续修复及本地全量 1872 passed 已完成；aw#115 合并后改 base 至默认分支并同步，再按最终 head 过 Codex，上线前先在生产跑 `migrations/015_rule_compiles.sql`；标定等 D 灯和改稿差异攒够（≥ 4 周） | docs/32 §3 E；D-121；jev:docs/00 #7；jev:config/data_policy.yaml |

## 3. 写作台（autowriter / deskcore）

| ID | 事 | 状态与证据 | 谁 | 触发 / 到期 | 来源 |
|---|---|---|---|---|---|
| W-23 | 匹配加固 + 人的改动回到飞轮（D-120 商榷 1）：包含度 0.30–0.60 且领先第二名 ≥0.15 认成 `edited`，领先不够进周检；每对记一条改动差异（`tv_edit_diffs`）；`open_project` 每周最多一次摘要，写手的模型归纳成规则建议、用户同意才 `record_rule` | aw#107 已合并部署（build `4bc41c8`），迁移 013 10-19 04:45 UTC 已上生产、表 / CHECK / 视图核过。差异里还记「还在但改了字」的句子对，摘要从上次看到的地方往后给。"标题相同还要正文重合"不做：低重合的 59 条是版本没存正文，不是错配。上线后看：第一晚补算的差异条数、`edited` / `ambiguous` 各几条、第一份摘要有没有被 ack。**10-20 核首晚**：440 条差异、362 条"改过"，其中 125 条只差写作台稿子末尾的 #话题 行（TV 正文读进来就剥了话题、稿子没剥；百健士正文完全相同的 165 条里 148 条被记成改过、品牌次数少一次）。aw#111 两边都剥话题，迁移 014 加 `diff_rev`，tv-sync 重算旧口径的行（不推水位），摘要只读当前口径——生产还没有任何 ack / 据此记的规则（aw#111 10-20 02:52 UTC 部署，build `31f6c63`）。10-20 aw#113 口径升到 `diff_rev` 2：写作台那版晚于发布的（`lag_days < 0`，首晚 212 条）不再算差异、也不重算（W-27）。10-19 22:03 按新定时跑了、中午那次不再写；当晚新对上 0（10-19 写的稿还没发）、补录 90（XIWU_phase2 88），`edited` / `ambiguous` 都是 0  **10-22 03:31 UTC 复核未过**：BJS原有65、SPX原有50条仍rev0；含尚无差异行的真实可比较对子，分别待补82/65，最新link更新停在10-20。需查Railway cron日志并补跑，详见10-22接续记录。**10-22 补记**：Supabase 日志里 10-21 13:50–15:30 UTC 没有任何 tv-sync 请求——那一轮根本没跑；Railway 全平台暂停部署（S-12），恢复后先确认 cron 真跑起来再核。 | 工程（aw） | 10-20 夜 tv-sync 后核：发布前那版的对子 `diff_rev` 全为 2（212 条 `lag_days < 0` 的留在 0，W-27）、改过数下降；再看第一份摘要 | D-120 |
| W-24 | 写手升级 skill（D-120 协议变了） | 服务端探针会在工具返回里自动带升级提醒（aw#106 的机制），不用人去群发；部署后看 `/skill-versions` 里旧版的人数降下来 | 工程（看计数） | aw#107 部署后一周 | D-120；aw#106 |
| W-04 | 发牌按结果加权（留 15% 纯随机，只滤「写不出来」的角度） | `v_angle_outcomes` 有、只有 doctor 读；`draw_angles` 还是均匀洗牌 | 工程 | 闸二有 validated 特征、每维样本够 | aw:deskcore.md:342；aw:`core.py:441-478` |
| W-05 | `store.recent_angle_keys` 不翻页，台账大了会静默截断、重复发已用角度 | 未修 | 工程 | 台账变大前 | aw:runbook:964；aw:`store.py:618` |
| W-07 | 借卡质量从没测过；D-088 预筛之后 0 次借卡 | 等样本，对 D-090 基线 | 工程 / 你 | 写手回来 | aw:runbook:945 |
| W-08 | `LIBRARIAN_TIMEOUT_SEC=60` 按 p95 重调（实测 p95 79 秒 / 24 样本；客户端只忍约 22 秒） | 10-22冷借p95已降至21.8秒，暂不延长超时；仍观察真实简报成功率，与F-03部署核验一起收口 | 工程 | 和 F-03 一起 | aw:`config.py:117-127` |
| W-09 | WorkBuddy 到底用哪种方式传 key（自定义头 / OAuth / `?key=`）没人记过；如果是 `?key=`，key 在访问日志里，要轮换 | 计数已上线：aw#103（build `4833ad8`），`/health.key_transport` 按 header / bearer / query / none 计，只记传法不记 key。计数是进程级的，每次部署清零。10-18：header 2,291、query 0、none 1 | 工程 | 10-23：看一周计数，`query` 一直是 0 就停收 `?key=`；不是 0 再定轮换 | aw:deskcore.md:713-721；aw#103 |
| W-10 | `ingest_target=false` 的映射（RIO ×5、hatherine-QNA）要不要入库目标；它们每晚重配、`tv-resolve` 会报错 | D-119：保留只判不入库。工程改两处：夜间重匹配跳过这类映射（不再每晚写 `unmatched`）；`tv-resolve` 遇到时说明白话、不抛错 | 工程（aw） | 随下一个 aw PR | 审计 C-11 |
| W-11 | 运营把补录副本重新录成飞书正式行时，tv-sync 关联不回去（10-10 手工修过一次，没有代码路径） | 未处理 | 工程 | 再出现时 | D-104 §2 |
| W-12 | 模糊匹配要人用 `tv-resolve` 处理，没指定人 | D-119：不另指定人。对不上的留 `unmatched`，不伤下游；`tv-sync` 报表里的 ambiguous 由 Claude 周一例行检查看一次，正文确实是同一篇才 `tv-resolve`。10-18：unmatched 813、fuzzy 25 | 工程（Claude 周检） | 每周一 | aw:runbook:241 |
| W-13 | 指纹 / 向量：一个 owner + 9 个休眠项目（718 篇老稿）没指纹；提交时的原子复查没覆盖标题语义；`semantic_degraded` 只打日志没有灯；项目名唯一约束没进库；一条全局规则没向量（跑 `reembed_my_rules`）；backfill 5000 行上限 | 都未做 | 工程 | 休眠项目激活时先 backfill；其余低优先 | aw:runbook:936、946、959、963、967 |
| W-16 | 新中转站：1.8 倍价格系数没对过账单；`-thinking` 后缀没验证；单点 | 未核。`cache_control` 已按 D-113 默认关掉，不再依赖这次对账 | 你动手（对账单） | 随时 | D-098；D-113；aw:`config.py:56` |
| W-19 | **跨项目串内容的防护**（10-12 事故：写手在同一个 WorkBuddy 对话里先写 Hatherine痘痘贴、再切西屋911gt，模型 gemini-3.1-pro-preview 把痘痘贴的规则抄进西屋的硬规则、出了 5 篇痘痘贴文案；deskcore 本身没串，`open_project` 只回本项目 + 全局规则）。要做：① 协议加一条「一个对话只写一个项目，换项目新开对话；`open_project` 拿到的项目名要在回复第一行复述」；② `record_rule` 入库前查内容里有没有同一写手其他项目的品牌名 / 专属词，有就拒并提示；③ `commit_drafts` 时用现成向量比稿子离本项目近还是离该写手的另一个项目近，离别的项目更近就标出来（影子期只记不拦） | aw#96已部署；现场5专属词已配置生产并回读，旧值本地备份；按生产回读配置跑本地已合代码，串词拒绝零写入、正常西屋规则可写（仅fake库）。影子提示已上线；带鉴权线上拒写尚未实测、误报/漏报待样本，不升硬闸。**10-20**：10-14 / 10-19 五批 15~20 篇的影子检查全部 1.5 秒超时，超时那条路连品牌词标记一起丢了；根因是标题向量逐对纯 Python 比（20 篇每项目约 115 毫秒），aw#110 改矩阵比（约 5 毫秒）、向量部分自守截止，品牌词标记外层超时也照报 | 工程 | 上线后的影子样本与真实带鉴权调用复核 | 10-12 owner 报告；`autowriter.backup_memory_xiwu_contam_20261012` |
| W-21 | 写作台入库段变慢：10 篇一批的 `phase_ms.commit` 从 4～9 秒（10-12～10-14）涨到 11～12 秒（10-15 三批），原假设 1～3 秒；库侧两条 RPC（闸的历史比对、原子写指纹）平均都不到 0.5 秒，大头不在库；commit 里没有分段计时，拆不开 | 未定位；aw#100 已让判定让路，回包还在 22 秒内。10-19 核：10-12 周 11 批 commit 段 p50 6.5 秒、p95 12.3 秒，判定 0 次超时 | 工程 | commit 段 p95 超过 14 秒，或下一次改 aw 时顺手加分段计时 | J-08；`autowriter.batch_metrics` |
| W-18 | aw 文档过时：runbook §1.7「011 尚未执行 / judge 未配置」、「012 没跑」「八个迁移」、7c 飞书六列、#8 4000 行上限；deskcore.md Hatherine「不在 TV」 | 本次补HANDOFF及runbook当前入口；旧段落逐段追平未全完成，不能把历史未配置当当前事实 | 工程 | 后续逐段核迁移/环境和文档 | aw:HANDOFF；aw:runbook |
| W-26 | 写作台第二批 F：按段判稿、按段给修改建议 | 不做（10-20）：近 14 天稿子中位 163 字、中位 1 段，SPX 中位 95 字、98 篇里 10 篇有换行；Jev 按换行切段、逐段串行判，项目层题的证据只从正文挑 | 工程 | 多数在用项目的稿子变长、变成多段时再议（周一例行检查看一眼稿长中位） | docs/32 §3 F |
| W-27 | `tv_note_links` 里 212 条对上的写作台版本是发布后 6～7 天才存进写作台的（全是 body_exact / title_exact，不是补录批次）：谁、为什么把发出去的帖存回了写作台 | 没查。影响已挡住：改稿差异 `diff_rev` 2 不再算它们，用上率灯和角度台账灯判据 C 不算接住；根因不在第二批里 | 工程（aw） | 低；再看到发布后才存的版本成批出现时 | docs/32 §1、§5 第 9 条 |
| W-28 | 交付模板接管后撤各项目的交付格式规则（docs/32 §3 A；aw docs/deskcore.md §3.9「上线后要做的」） | 没做（A 在 aw#115，等 Codex 过后合并）。**10-21 已备好计划**：百健士、西屋911gt、Hatherine、途鸽 4 个项目的模板，插 3 条硬的退路规则、撤 6 条交付格式规则，Hatherine 有两条要等 D1–D7 重录；计划和 SQL 里有客户的规则原文，不进 GitHub，文件包已发给 owner。每给一个项目设模板：互相打架的交付格式规则（HATHERINE 6 条以上、WTG 的话题顺序那条）先整行备份再 `retire`；**留一条和模板一致的短规则当退路**（只写【标题】/【正文】标记和话题行放哪）——`score_drafts` 出错、一篇没存进去、模板写坏时回包没有 `delivery`，协议让写手照规则自己排，`open_project` 的简报里也不带模板，全撤了版式就回到模型即兴排。aw 让简报带上模板（或一句话版式）之后，这条退路规则也可以撤 | 工程（aw + 数据操作） | 每个项目设模板时；A 上线后一周内核一遍哪些项目有模板、各还剩几条交付格式规则 | docs/32 §3 A、§4、§5 第 5 条 |

## 4. 入库与同步（TV）

| ID | 事 | 状态与证据 | 谁 | 触发 / 到期 | 来源 |
|---|---|---|---|---|---|
| I-01 | **统一飞书表准备**：判档版本标记（B4，「第一张新表之前必须有」）、风控否决位（A2）、「观察中」规则（A3）、状态值没匹配的预检告警（A4）、新表族 `capabilities_absent`（A7）、TGV `tier_extraction` 重写（A8；`删除` 单独保留成一档，D-119）、新列 B1–B3 / B5、文档 C1–C6、运营问题 D1–D6、「状态 vs 流量状态」撞名 | 工程项基本没做。**运营 D1–D6 10-22 已答**（[ops-answers-2026-10-22](data-analysis/ops-answers-2026-10-22.md)）：D2 不能纯机器写（「风控中」人填；linkcheck 在链接失效 / 上游标违规时也写、从不摘，ops-answers §8.2）→ **A2 已做（D-124，TV#216）。**10-22 夜跑已核**（run 39741176137，全绿）：正好 4 行变风控（OKMAN 2、SPX 1 爆→风控，WTG 1 预备→风控），整批翻转闸没拦；推过 ssll 的 3 行已撤回，各项目 stale_in_ssll 都是 0**，C5 文档仍待写；D3 评估中新判据已记 signal-definitions，但 linkcheck 还没实现（I-20）；D4 伪爆标记不会再有 → 老表换格式前先 dry-run 列出 synthetic true→false 的行；D5 评论关键词≠蓝词，另开列；D6 蓝词累计、竞品名 TV 入库时排除（等运营名单，O-05）；「状态」与「流量状态」不会同表，撞名不用抢先改。B5 口径已定（只写首次起量、清空重判、首轮不算），可以做 | 工程 + 运营 | **第一张统一格式表接入之前** | unified-feishu-table-assessment-2026-09-22.md:341-444 |
| I-02 | 全项目每周只读预检（B-16 后半） | 故意没做（怕第一天就红） | 工程 | — | D-095 #2 |
| I-04 | 评论步骤按内容哈希跳过（A-07a） | 没做，只省 CPU | 工程 | 低 | D-092 |
| I-05 | 两路来源都没有时 `synthetic` 没被显式清掉 | 没做 | 工程 | 低 | D-091 |
| I-06 | 通道 1「大批首推」闸：单晚待推 > 30 篇时整步不推、列名单、拖红，人看过用 workflow_dispatch 显式放行 | D-119：不设常规上限（近 45 天每晚 1–5 篇、最多 13 篇）。D-091 只数已在库的笔记，新 note_id 不经过它；新项目有 on_demand 闸，已在跑的项目出映射事故（记录换号）没有闸（Codex 复审 #200） | 工程 | 随下一个 TV 代码 PR | D-087；D-091；D-119 |
| I-07 | 通道 1 撤回 B 路径（老行按 `ai_analysis->>_truth_vault_note_id`、关读写窗口的 RPC） | 推迟 | 工程 | 出现老行或错撤 | D-087 |
| I-08 | 飞书删了重建的行按 `publish_url` 去重 | 没做，看 verify #93 频率 | 工程 | 视频率 | D-103 B-21 |
| I-10 | audit_log 没有保留任务（以后做必须「先抽后删」）；根因 `set_updated_at()` 无条件写 NOW() 没修 | 没做 | 工程 | 低 | D-078 |
| I-16 | **夜跑批量写冲掉 essence 列：恢复 + 验证**（D-122 / D-123）。**10-22 进度**：①（恢复）已完成；②（闸三重冻）已完成：80 行旧分 10-22 05:54 UTC 备份后删掉，当晚夜跑按新版重打，第 4 步回读全过（新版 177 行 = 应打 177 篇，旧版 0 行，备份 80 篇全部重打，XIWU_phase2 没有落到 pooled 切点）；③（NUC 15 张）已重策展；④（第一晚核）10-21 已只读核过，详见右栏。SQL 都在 `docs/d122-repair/`。① 合并后建备份表 `truth_vault.backup_notes_essence_cols_<日期>`（COMMENT 写回滚；回滚跳过恢复之后 essence 又写过的篇），按 `audit_log` 现算名单恢复：content_format 取冲掉之前最近一次 essence 写入之后的值，10-20 dry-run 是 `essence_wrote` 689 篇（其中 HATHERINE 11 篇和被冲掉的值不同）+ `essence_kept` 55 篇（WTG 51 篇重标同标签、HATHERINE 4 篇）；NUC 人群 / 痛点取 essence 按子方向写的值；HATHERINE 17 篇人群 / 痛点是旧方向抬上来的值，不恢复（和 D-122「定了什么」第 5 条同一规则，见 I-17）。② 闸三：冻结打分器是在冲掉的数据上建的（D-122 修复计划第 4 条），**定 A**（10-20，owner 授权代定）：恢复回读后重冻一版、10-17 起约 80 行 `content_scores` 备份后按新版重打，新版本号记新 D 号。③ 副本：NUC 15 张策展卡是人群被冲掉之后策展的，恢复后只重策展这 15 张（给策展脚本加按 note_id 选卡，另开小 PR）；NUC 8 篇三省六部样本的 `_truth_vault_target_audience` 是 null，定了不补（D-122 修复计划第 5 条）。④ 合并后第一晚核三件事：`audit_log` 里受保护列「非空 → NULL」0 条（`tier` / `tier_source` 置空、且同一条 UPDATE 写进去的 `data_quality_flags` 带 `tier_cleared` 或 `tier_unmapped` 的不算——10-20 生产 270 篇 / 62 篇带这两个旗子，是代码故意写的 NULL）；`emotional_lever` 有值而 `content_format` 为空 0 篇；各项目 Done 行的 `upserted` 和修复前同量级 | **① 已完成**（10-20 约 16:35 UTC，TV#209 合并后）：1,102 格 / 744 篇，content_format 744、NUC 人群 179、痛点 179。备份 `truth_vault.backup_notes_essence_cols_20261020` 744 行，计划 `truth_vault.repair_notes_essence_cols_20261020` 1,102 行（`essence_wrote` 689 + `essence_kept` 55 + `essence_subdir` 179×2）。回读 1,102/1,102 格等于计划值，`emotional_lever` 有值而 `content_format` 为空 0 篇。**② 已重冻**（D-123）：新版本 `essence-v1-93035a562b2e`，冻结日仍是 10-17。10-17 起已打的分正好 80 行，全是 v1。删除 SQL（`docs/d122-repair/d123_gate3_rescore.sql`）：备份到 `truth_vault.backup_content_scores_d122_20261020`，再删掉，DO 块带行数守卫。**还没跑**：10-20 用 Supabase MCP 跑卡在 app 里的确认上超时，什么都没写；在 SQL editor 跑。下一次夜跑按新版重打后核：新版本行数 = 冻结日之后有 essence 的篇数，v1 行为 0。**③ 已加**（D-123）：`curate_flywheel_lessons.py --note-ids`，`recurate-lessons.yml` 加了 `note_ids` / `dry_run` 输入，`check_curate_note_ids.py` 进 CI。15 张名单逐篇重算核过（id 在 D-123）。**10-20 已跑**（17:40–17:43 UTC）：dry-run run 39467743743 渲染 15/15、没调模型；真跑 run 39468049494 成功 15、失败 0；回读 15 张 `curated_at` 晚于恢复、还是旧的 0 张，NUC 其他卡没动。**④ 数据核查已过**：10-21 16:34 北京时间（08:34 UTC），run 39563186123 已成功完成；按 `05_after_nightly.sql` 同口径只读核：受保护列非空转 NULL 0 次、lever 有值而 format 为空 0 篇、1,102 格恢复值漂移 0。新版分数 106/106，原 80 篇均已按新版重打。**② 10-22 已完成**：owner 05:54 UTC 在 SQL editor 跑了 `d123_gate3_rescore.sql` 第 1 步，回读备份表 `truth_vault.backup_content_scores_d122_20261020` 80 行（RLS 开、anon / authenticated 读不到、注释带回滚语句），旧版 0 行，新版 106 行不变；当晚夜跑后按第 4 步再核一次。夜跑各项目 upsert 规模另见本轮接续记录。代码修复和守卫在 TV#209（`upsert_notes_batch` 按 `UPSERT_PROTECTED_COLS` 分组、名单外列整轮补 NULL；`scripts/check_batch_upsert_columns.py` 接进 CI）。10-20 只读：content_format 744 篇（WTG 195 / NUC 179 / RIO 90 / NRT_phase2 86 / HATHERINE 83 / LNKT 74 / SPX 29 / TUGE 6 / BJS 2），全部有 `audit_log` 记录，其中 729 篇冲掉的是 essence 的值；NUC 人群 / 痛点各 179 篇；HATHERINE 到 10-20 还在每晚发生 | 工程（owner 10-20 授权代定、含写库） | ①②③ 已完成；④ 数据核查已过；10-22 夜跑后按 d123 第 4 步核新版重打 | D-122；D-123 |
| I-17 | 方向从抬得了改成表里没有的值时，清掉旧方向抬上来的人群 / 痛点 / 产品焦点，形态回到 essence 的判断（D-122「定了什么」第 5 条）。修复后同步对这种篇不再写这几列、库里留着旧方向的值，和恢复时「旧方向抬的值不恢复」相反 | 没做。生产一个月约 17 篇，都在 HATHERINE（9 月下旬起运营用了一套新方向名，mapping 没跟上）。同步自己不知道上一次的方向，要么读库比 `raw_extra._direction_raw`，要么夜跑后单独一步按 audit_log 找。owner 若改成「旧方向的值留着」，这条关掉、I-16 的恢复改用 744 / 196 / 196 变体 | 工程 | 恢复之后、HATHERINE mapping 补新方向之前 | D-122 |
| I-18 | 特征层 --note-ids 长名单被当文件名 | **TV#213 已合并，worker 部署待核**：只捕获 ENAMETOOLONG，其它权限/I/O错误继续上抛；长名单、文件、EACCES/EIO及worker端点守卫通过 | 工程 | 核 Railway worker 部署最终合并提交后关 | [10-22记录](docs/continuation-2026-10-22.md) |
| I-19 | NRT_phase2/3、TGV 的新品牌词典还没用上（I-12 后续） | 三个项目都是 `on_demand`，定时 features-sync 跳过；`brand_in_title` / `brand_first_position` 要手动跑一轮才按新词典算。代码题，worker `/annotate-features` 带 `code_only` 不花模型钱（`backfill-features.yml` 没暴露这个输入）；不带 `reannotate` 只补未标注的 347 / 444 / 136 篇，已标注的旧行保持旧词典 | 工程。**owner 10-22：跑；10-22 已跑完**：TV#217 给 `backfill-features.yml` 加了 `code_only`，三个项目各派一次（TGV 136、NRT_phase2 347、NRT_phase3 444 篇，0 失败，不花模型钱）。`brand_first_position` 覆盖 499/499、598/598、144/144，正文出现品牌 89 / 51 / 12 篇。已标注的 152 / 154 / 8 篇仍是旧词典，要统一重算另说（同样 code_only，带 reannotate，走 note_ids） | 剩旧行要不要重算 | [ops-answers-2026-10-22](data-analysis/ops-answers-2026-10-22.md) §6 |
| I-20 | **linkcheck 补两件事**（写「流量状态」「起量时间」「蓝词字段」的就是它）：① 运营第 7 条「评估中」新判据（48h→72h 涨 <10 → 无水花，之后每个 24h 窗口同理），要让「评估中 → 无水花」绕过它现在的只升不降；② 竞品名排除：linkcheck#50（10-22 合并）写明竞品词原样保留，在 linkcheck 排除要先和改它的人对齐，否则只在 TV 入库时排除 | 10-22 只读核对 linkcheck 2eb9cc7：新判据**没实现**。89 行眼下不会翻，linkcheck 改了也大多碰不到：它帖龄满 30 天就归档不再巡查（68 行已过线，其余 21 行最晚 11-14 过线），只存两个评论数、补不出已过 72h 的 48h→72h。SPX / XIWU_phase2 的 `hit_blue_keywords` 里已有 康比特 / 迈胜 / 奥佳华 / 荣康 等竞品名，会跟着书架卡进写作台。详见 ops-answers 第 3 节更正注、§8 | **owner 10-22：linkcheck 的改动转给别人，TV 这边不碰**；运营（竞品名单、正好涨 10 条落哪边）；TV 侧等对方上线后做入库排除和 B5 | 上线要等 Railway 恢复部署（S-12） | [ops-answers-2026-10-22](data-analysis/ops-answers-2026-10-22.md) §8 |


## 5. 飞轮、策展、librarian

| ID | 事 | 状态与证据 | 谁 | 触发 / 到期 | 来源 |
|---|---|---|---|---|---|
| F-01 | NUC `direction_subtype` 回填 | 做了一部分（核：10-09 跑过两次；NUC 有 essence 的 657 篇里还缺 126，D-097 时是 206） | 工程（触发 `backfill-essence.yml` mode=missing_subtype） | 随时 | D-097 |
| F-03 | D-088 预筛有没有用：跑 librarian-cold-baseline 里的对比 SQL，看 p50 / p95 / 超 60 秒条数对基线（49.5 秒 / 79 秒 / 24 条里 7 条）；p95 还 > 60 秒就决定换通道或 `FLYWHEEL_LIBRARIAN_MODEL`；确认 #167 后 Railway 重部署过 | **10-22 已出数**：24次冷借 p50 15,446ms / p95 21,759ms，超60秒0、超22秒2、空结果0。已低于60秒门槛，暂不换模型；#167之后Railway部署证明仍待核 | 工程（10-22 出数后按 D-119 授权直接判） | ≈ 10-22 | D-088；D-090 #5 |
| F-04 | aw 借卡：把借卡移出 `open_project` 同步路径（A-04，客户端只忍约 22 秒）；librarian `degraded` 变 `BORROW_ERROR`（B-04） | 未核（aw 侧没查到修复） | 工程（aw） | 写手恢复借卡首批前独立核查/修复并验约22秒截止；W-01已关，不等J-03 | 审计 A-04、B-04 |
| F-05 | `recurate=all` 不收敛，全量重策展前必须按 `curated_at` 升序 | 没做 | 工程 | 全量重策展前 | D-096 |
| F-06 | 32 条孤儿卡片标注（书架闸挡了但已标注）对账（A9） | 未核 | 工程 | 低 | ops-answers-2026-09-22.md:442 |
| F-07 | 清理：推送时代残留（`preview_injection_candidates.py`、`v_autowriter_injection_candidates`、`v_flywheel_sync_status` 里的 aw 列、docs/09）；孤儿脚本 `annotate_comment_threading.py` 和两个 `migrate_*.py` | 没做 | 工程 | 低 | D-063；D-075 |

## 6. 灯与看板

| ID | 事 | 状态与证据 | 谁 | 触发 / 到期 | 来源 |
|---|---|---|---|---|---|
| L-01 | 去掉 daily-sync.yml:438 stale / gated / retract 摘要上的 `|| true`（C-20） | 还在 | 工程 | `stale_in_ssll` 连续两周 0（≥ 10-22） | D-087；D-103 |
| L-03 | 每周看灯：`LIBRARIAN_TRAFFIC`、`ANGLE_LEDGER`、`EXTERNAL_CORPUS`、`DESK_USE_RATE`（10-20 加，周一才跑）、Jev `external-corpus.yml` | 例行 | 你动手（周一定时检查会代看一遍） | 每周 | docs/29:32-45 |
| L-06 | 写作台用上率灯（`DESK_USE_RATE_CHECK_DONE`，docs/32 D）第一次读数 | 10-20 加（TV，`scripts/check_desk_use_rate.py`，daily-sync 每周一北京时间跑，advisory）。10-26 第一次跑，看 10-05～10-19 发布的笔记。读的时候核三件事：① 未改动率是数还是「待重算」——10-20 写作台部署、当晚 tv-sync 重算之后应该有 `diff_rev` 2 的行，还是待重算就去看 tv-sync；② 哪些项目亮黄、是不是在用写作台的那几个；③ 有没有项目被点名「判不了 · tv-sync 漏了」（整窗或在用期里发布 ≥15 篇、对过账不到八成；表里对过账一列正常等于发布）；④ 和角度台账灯判据 C 同一周一起亮的项目，看判据 C 表里的「真稿」列分开「没存档」和「被重写」。数记进 docs/32 §4 那张表，之后每周一跟 L-03 一起看 | 工程（Claude 周检） | 10-27 | docs/32 §3 D、§4；docs/29 |
| L-07 | 写作台第二批 A–C 上线四周后判接住率走向 | A–C 在 aw#115，10-21 08:09 UTC Codex 第 12 轮开始审（进度看 PR），还没上线。上线日 + 28 天，拿 D 灯连续四周的接住率、未改动率（docs/32 §4 那张表）判：不动 = 问题不在版式和规则，回头看内容本身（选题、角度、示例），另开条目；在动 = 继续按周看。单周起落不下结论 | 工程（Claude 周检）→ 你拍板下一步 | A–C 上线日 + 28 天（上线日待定） | docs/32 §4 |

## 7. 运维、密钥、备份

| ID | 事 | 状态与证据 | 谁 | 触发 / 到期 | 来源 |
|---|---|---|---|---|---|
| S-01 | 删 D-086 两张备份：`truth_vault.reference_samples_backup_tv_stale_20261008`、`truth_vault.notes_ssll_marker_backup_20261008`（先确认三省六部没反映参考池变薄） | 到期前 | 你动手（SQL editor） | ≈ 10-22 | D-086；D-103 |
| S-02 | 删 10-09 / 10-10 备份：`truth_vault.backup_inverted_lineage_20261009`、`truth_vault.backup_{notes,nfa,comments,metric_snapshots}_vanished_20261009`、`autowriter.backup_tv_note_links_inverted_20261009`、`autowriter.backup_items_self_review_20261009`、`autowriter.backup_tv_note_links_vanished_20261009`、`autowriter.backup_tv_note_links_twins_20261010`、`autowriter.backup_orphan_ingest_tuge_20261010`、`autowriter.backup_memory_xiwu_contam_20261012`；`truth_vault.backup_notes_vanished_20261009` 的 COMMENT 里有回滚顺序；10-16 新增 `truth_vault.backup_quarantine_resolve_20261016`（I-03 的 2,477 行原状态；回滚 `update truth_vault.undeclared_fields_quarantine q set status=b.status, review_decision=b.review_decision, reviewed_by=b.reviewed_by, reviewed_at=b.reviewed_at from truth_vault.backup_quarantine_resolve_20261016 b where q.quarantine_id=b.quarantine_id`），11-16 之后可删；10-19 新增 `truth_vault.backup_gate3_preannotated_20261019`（2 行，闸三重标前的整行原样），11-19 之后可删；10-20 新增 `autowriter.backup_global_shorten_rules_20261020`（写作台第一批撤掉的 5 条全局写短规则，撤前整行原样，docs/32 §2），11-20 之后可删；10-20 新增 `truth_vault.backup_notes_essence_cols_20261020`（744 行）+ `truth_vault.repair_notes_essence_cols_20261020`（1,102 行），这是 D-122 恢复前的快照和恢复计划，回滚写在备份表的 COMMENT 里，12-01 之后可删；D-123 合并后新增 `truth_vault.backup_content_scores_d122_20261020`（80 行，闸三旧版本 `essence-v1-322f02c9465f` 的分，回滚写在 COMMENT 里），11-20 之后可删 | 到期前（verify #92 也会提示） | 你动手 | 11-09 之后 | D-099；D-102；D-103；D-104 |
| S-05 | docs/04 新服务清单加一条「更新 R-032 key → 持有者矩阵」 | 没写 | 工程 | 低 | RISKS.md:581 |
| S-06 | 开 RLS 后三省六部还能不能读、它实际用哪把 key（读到 0 行就回滚或换 key）；三省六部下次在 `public` 建表时收回 anon 默认权限 | 10-22 边缘日志：三省六部轮询（`public.pipeline_runs`，约 2 万次 / 天）带的是 service_role，不靠 `ssll_authenticated_read` 那条 policy；它的去留并到 S-13。10-30 起 public 新建对象不再自动授权（Supabase 邮件），三省六部建新表要自己 GRANT | 工程 / 你 | 三省六部下次跑 | D-101 |
| S-07 | 改动后跑一遍 `verify_supabase_state.sql`，重点 #88 #89 #91 #92 #93 #94 | 部分核过（10-12：HATHERINE 6 条 twin 链接在 10-11 同步后仍是 `ingested`；TUGE 孤儿副本已删、回读 0） | 工程 | 每次大改后 | D-099；D-102；D-104 |
| S-09 | 小工程：迁移命名与 `dashboard_views_*` / `security_*` 部署清单（C-16）；密钥打码没盖住隔离路径的 `print()` | 备份 RPO / RTO 已定（D-119）：人写的、不能从飞书重建的表靠每日备份，RPO 24 小时、RTO 一个工作日，不买 PITR。剩两件小工程没做 | 工程 | 低 | 审计 C-16；D-095；RISKS.md:182 |
| S-12 | **Railway 环境变量泄露**（10-21 公告；部分变量被解密）。我们在 Railway 上的服务：aw deskcore / tv-sync / 已停的 Streamlit、TV tv-worker / librarian / onboarder、Jev judge、linkcheck cron / 面板，外加三省六部。要换的密钥和顺序见 [事件记录](docs/incident-railway-2026-10-22.md) | **owner 10-22：等 Railway 官方通知，暂停期间不改 Railway**。Supabase 用方案乙：旧版 service_role 先不停，每 3 小时巡检日志（基线 10-13 起全部来源对得上），有异常立刻停用旧版密钥；恢复时每组一把 `sb_secret_` 再停旧版。新密钥不在恢复前填进 Railway | 你（各家后台、GitHub Secrets、写手钥匙）+ 工程（Railway 侧，若给 project token） | Railway 恢复部署时；或 Railway 通知我们在受影响名单内时立刻 | Railway 公告 / status QH8L8B3E |
| S-13 | **Supabase 警告分诊（10-22）**：① 关掉 Auth 注册、② 去掉 `ssll_authenticated_read`：**owner 10-22 定：都不做，目前没有必要**；③ 10-31 复查 10-30 授权变更；④ autowriter 两个没用的向量索引 | 详见 [Supabase 警告分诊](docs/supabase-advisors-2026-10-22.md)。18 条 ERROR（`v_dash_*` 定义者视图）维持 D-101 的已接受例外，理由已补正（D-101 补记）。任何登录用户都能读 public 下 5 张 ssll 表（含 `reference_samples` 330 行爆款正文）；旧 anon key 可能随已停的 Streamlit 在 Railway 泄露，注册开着就能拿它注册登录。auth.users 6 个、最新 05-21、最后登录 08-19，没人在用登录。日志巡检已加看注册 / 登录 | ③ ④ 工程（① ② 不做；日志巡检照常盯注册 / 登录，有异常再报） | ③ 10-31 | docs/supabase-advisors-2026-10-22.md |

## 8. 你要做的（从上面挑出来，方便一次看完）

> 只放要你本人账号或对外联系才能做的事。生产记录能核的、按流程后做的、能按授权判的，Claude 自己做，不放这里（owner 10-16）。

| 条目 | 一句话 |
|---|---|
| W-16 | 有空对一次中转站账单，核 1.8 倍系数（缓存已按 D-113 关掉，这条不再挡任何事） |
| S-01、S-02 | 备份到期时 Claude 发删表 SQL，你在 SQL editor 跑（10-22 / 11-09 / 11-16 / 11-19 / 11-20） |
| S-12 | Railway 泄露：等官方通知。恢复时按[事件记录](docs/incident-railway-2026-10-22.md) §4.2 换密钥（各家后台、GitHub Secrets、Vercel 由你，写手新钥匙由你发）；三省六部自己的 AI 密钥找它的维护者换；看一下 GitHub 组织里 Railway App 的权限和审计日志 |
| O-05 | 转给运营两件事（[ops-answers-2026-10-22](data-analysis/ops-answers-2026-10-22.md)）：①「笔记状态」三条要求（§2：选项里不要有「关注」；要标假数据就固定一个选项、放笔记状态并先告诉我们；其余无要求）；② 要各项目竞品名清单，TV 入库时从蓝词里排除（§5）；③ ~~问清「起量时间」谁写~~ 已答（owner 10-22）：由 TangVarie/linkcheck 巡查机器人写，代码已核（ops-answers §8）；④ 再问运营一句：「评估中」新判据里正好涨 10 条算哪边（I-20）。O-01 那批问题 10-22 已答完 |
| I-16 | 不用动手（10-20 已授权代定：闸三 A、NUC 只重策展 15 张、HATHERINE 旧方向的值不恢复）；恢复已跑完，闸三已重冻（D-123），15 张已重策展。删 80 行旧分 10-22 你已在 SQL editor 跑完（回读通过）；备份表按 S-02 11-20 之后可删。要反过来再说（I-17 跟着关） |
| W-28、J-15 | 4 个项目的交付模板和退路规则操作包（含客户规则原文，不进 GitHub）10-21 已发给你；接手的人向你要这份文件包 |

其余标「你拍板」的条目 10-18 已按授权判完（D-119）；W-20 owner 10-18 定了维持现状。

## 9. 文档与远期

| ID | 事 | 状态 | 来源 |
|---|---|---|---|
| D-01 | 文档刷新（C-21）+ DECISIONS 加索引：CURRENT_STATE.md 头还是 06-09；RISKS.md 头 05-22，R-007 / R-023 过时；docs/00:179「LLM 调用必须在 Railway」D-100 后过时，「Railway 3 服务」应为 6，PG17（CI 用 PG16），§3 缺外部语料和 judge；README:310「投流数据全库不存在」过时；docs/30 / docs/31 悬空引用；`docs/08`、`docs/10`、`docs/13` 停在 9 月中 | 核过 | 审计 C-21；D-075 |
| X-01 | L3 受众层（docs/23；R-011 受众数据同步）；pgvector 第三阶段；R-005 评论楼层重建 | 远期 | docs/23；README:314；RISKS.md:94 |
| X-02 | 研究遗留：「排除 SPX 类项目」规则要只用训练集的判据 + 外层 holdout；`synthetic_known` 三态视图 | 低 | DECISIONS.md:3276、:3442 |
| X-03 | 老议程 DD-A ~ DD-E 没正式关；R-018 二期、R-020、R-021、R-026.2、R-028 | 未核（RISKS 05-22 后没更新） | DECISIONS.md:995-1001 |
| X-04 | 老归档库 `vnbcytilakkxojhgzeqr` 清理；Vercel Preview 的 `SUPABASE_URL` | 未核 | docs/archive/26-handover-2026-06-09.md:92 |

---

## 已关

| 日期 | 条目 | 证据 |
|---|---|---|
| 2026-10-22 | **I-12：品牌别名** | 运营 10-22 答：力克雷另有 15 种写法（NRT疗法 / Nicorette / 替烟口香糖等），TGV = the good vitamin、一般写 TGV不哭糖。写进 NRT_phase2/3、TGV_phase1 的 `brand_aliases`（「力克雷」已是 brand、重复的一条去掉）；按正文粗算命中篇数 NRT2 104→105、NRT3 54→57、TGV 26→26。三个项目都是 on_demand，定时特征层跳过它们，新词典要手动跑一轮才生效，见 I-19。见 [ops-answers-2026-10-22](data-analysis/ops-answers-2026-10-22.md) 第 1–2 条 |
| 2026-10-22 | **I-13：起量时间口径；O-01：交运营的问题清单** | 运营 10-22 答：机器填，首次「评论比上次涨 ≥50% 且多 ≥20」的时刻，只写一次、人工清空重判、首轮巡查不算；人一般不改值、可能清空；SPX 10-16 那列同一方法。运营说「由你写」，谁维护这条自动化转 O-05 ③。推翻 10-16「人工维护」的说法，signal-definitions 已改；SPX / ANSHEN 落在 `_undeclared` 的这一列补了声明。O-01 其余 D1–D6 的答复记进 I-01，后续要转运营的两件事见 O-05 |
| 2026-10-22 | **S-11：未知审查结论误判 PASS** | TV#213 head b0c4326 复审 completed / false、无未解决线程、CI 39716368184 success，合并为24c6bc1。19个离线场景接入CI；未知、缺失、非布尔均WAIT，合并仍另核当前head、CI和未解决线程 |
| 2026-10-19 | **O-04：途鸽 22 篇写作台没接住** | 后台：9-16 06:59 UTC 之后写作台没收到途鸽任何一次调用，10-12 周 22 篇在全库 6,478 篇存档里一句都找不到（同一查法对已对上的 38 篇是 38/38）。写手自测「列一下我的项目」是通的；owner 确认 WorkBuddy 的写作台连接是全局的——原因是那一波 **skill 没被调起来**（写手点的是 human-writing），后面整套流程就没走。已修：aw#108（调不通 `open_project` 就不写）、TV#205（角度台账灯判据 C：发了帖写作台没接住，当天只亮途鸽和 Hatherine）、aw#109（skill 描述放宽到只报品牌名 / 只贴 brief / 只点 human-writing 都触发；出现 human-writing 就核对要不要走写作台；服务端说明同口径；`open_project` / `list_projects` 带 `desk_gap` 原话提醒运营哪个项目没接住）。skill 自动更新，不用写手操作。**10-26 周一**看判据 C：途鸽 / Hatherine 还亮就再查 |
| 2026-10-19 | **W-25：西屋911gt 接进 TV** | owner 10-19 给了发布表（和 XIWU_phase1 同一个 base）。接成 `XIWU_phase2`（TV#203）：照 phase1 的列结构起草、Preflight 对真表核两轮到干净；显式实跑入库 71 篇（10-07 ~ 10-18 发布，空占位 42，错误 0），目前评论最多 4、还没有爆款。`autowriter.tv_project_map` 已加 `XIWU_phase2 → 西屋911gt`（补录目标），写作台这个项目的稿子从下一批起能拿到参考分（品类 家居家电），今晚 tv-sync 开始对回。看了文案定方向口径（产品是 911GT 按摩椅，人群比 phase1 散，记「通用」），翻 daily |
| 2026-10-19 | **O-03：节后写作台周产出** | 只读核生产（`angle_ledger` / `versions` / `batch_metrics`，按周）。主写手 10-12 周发牌 179、销 103、写作台入库稿 104，回到 9-14 / 9-21 两周（144 / 123 张，入库 44 / 175 篇）的水平，低于 9 月头两周（335 / 292 张）。总量没回到 9 月：另一位写手 9-22 之后没再在写作台里发牌（之前做 hatherine D1–D6、RIO、百健士）；途鸽这周 22 篇发出去的笔记在写作台里没有来源，途鸽 9-16 之后就没人在写作台发过牌（之前 100 张、入库 104 篇），说明途鸽的稿子从 9 月中起在写作台外面写（10-19 更正：这句判过头了，后台只能说明写作台没收到途鸽的调用，见 O-04）。10-16 写手已重导 skill、服务端探针在，skill 版本不是原因；是谁、为什么不用写作台，数据看不出来，记成 O-04 问 owner。漏账：10-12 周 42% 没销，在 9 月 28%–68% 区间内，没变坏。入库段 p95 12.3 秒（W-21 门槛 14 秒），判定 104 次 0 超时，20 次 `not_configured` 全是西屋911gt（新开 W-25，10-19 已关）。同周补录副本 72 篇（途鸽 22、Hatherine 23、百健士 15、sportsix 12）= 稿子进了飞书没走写作台，D-120 改版后不再需要提交，这个口径以后看 tv-sync 的对上率 |
| 2026-10-18 | **W-20：写手用的模型** | owner 10-18：维持现状，写手都用 gemini 系列，效果不错（D-119 补记）。跨项目串内容靠 W-19 的服务端防护；以后改协议和工具说明按 gemini 考虑 |
| 2026-10-18 | **I-15：SPX 抖音行沿用库里正文** | 10-17 daily-sync（run 39011678570）`inherit_reused=18`、`quarantine_new=0`；库里 18 篇 content_format / target_audience / user_pain_point 都在（提问求助 12、场景植入 6）；隔离表 18 条 pending 停在 10-16（D-053 不由程序改） |
| 2026-10-18 | **G-07、G-10、G-13、G-14：闸与特征层的拍板项** | D-119：G-07 并进 G-04（「建议改」一列 + 理由）；G-10 不救、并进 G-09；G-13 不换 Jev（换了闸二快照作废）；G-14 不换 Haiku（一晚 105 篇、输入约 114 万 token，等 owner 对账再看） |
| 2026-10-18 | **J-06、J-13：Jev 两个后做项** | D-119：借卡不挂 Jev 影子（下发和外部书架都建在 TV 馆员上）；素人初稿入口不在三仓，那边要接时给 key 调同一个 `/judge` |
| 2026-10-18 | **W-15、W-17：写作台产品项** | D-119：Railway 健康检查保持 `/health`（用 `/ready` 会让外部依赖挂着时发不了版）；团队共享等远期项等真有需要再开 |
| 2026-10-18 | **I-09、I-11：采集的拍板项** | D-119：运营删掉的评论留着、敏感性检查记进 J-02；LNKT 2 篇占位列抖音笔记留声明不入库，BJS 蓝词字段并进运营问题清单 |
| 2026-10-18 | **L-02、L-04：灯与看板** | D-119：`config.pipeline` 由 daily-sync 漏账灯每晚读；看板 Phase 3–4 不做，docs/24 的 service_role 改成 anon |
| 2026-10-16 | **W-02：写手重新导入 skill（协议 `d59368a8f8ad`）** | owner 10-16 告知已通知写手重导。之后靠服务端探针兜底（aw#106，build `3c6bb47`）：`open_project` 报 skill 版本，旧版 / 没核到的在返回值里带升级入口，其它工具同一人 30 分钟最多再提醒一次；24 小时计数看 `/skill-versions`（要 key）。只改工具说明，协议仍是 `d59368a8f8ad`，写手不用为探针再导 |
| 2026-10-16 | **G-02：闸二新发现下不下发** | owner 10-16「① 发，②③ 按 B，④⑤ 不发」，见 D-116。下发通道留在 G-05 |
| 2026-10-16 | **S-10：TV 仓 GitHub secret 里的中转站 key** | owner 10-16 换了 secret；gateway-probe run 38887264544（1 token ping，`claude-sonnet-5-5`）回 http=200。今天漏掉的 essence 由今晚 daily-sync 补上，不单独重跑 |
| 2026-10-16 | **W-22：漏账灯分清「没交」和「交了没走 commit」** | aw#103（build `4833ad8`，Codex 复审无问题）。没做成单独一档黄：两种情况坐标都没销账、都会被重抽，灯照旧红；改成给每个超线项目贴原因标签——同一窗口里飞书同步回来过补录副本 → `delivered_without_commit`，没有 → `not_delivered`，副本数读不到 → `unknown`（总数给 null，不给 0）。`/health` 只露总数 `projects_delivered_without_commit`，哪个项目是哪种在鉴权过的 `doctor` 里看。上线后 `/health`：7 天发 179 / 销 103，1 个项目超线，属于「交了没走 commit」 |
| 2026-10-16 | **J-01：写手的评论能力** | 07:15 UTC 开关打开；写作台用真实写手 key 核过两个端点（单条通过、整组里的背书送复核）；aw#101 / aw#102 已部署（build 1abf3b5，协议 `d59368a8f8ad`）；Jev#22（0ce92ae）让整组题也只提示；回滚 = 开关改回 0 |
| 2026-10-16 | **J-04：三省六部不接** | 它自己的运行记录 `public.pipeline_runs` 最后一次 2026-08-28（总共 23 次），之后没在用；owner 10-16「不管吧，我觉得没必要」。三省六部恢复使用时再议 |
| 2026-10-16 | **J-03：评论参考与门槛轮验收** | D-112 门槛轮按预注册判据通过（门槛题 150/160，背书漏报 0；run 38862116728），owner 10-16 回「验收」。之后的上线跟 J-01，回填跟 J-02 |
| 2026-10-16 | **J-08：判定截止按真实样本定** | 8 秒不动（9 批 / 84 篇，最长 4.3 秒）；aw#100 让判定只拿整次回包 20 秒里剩下的时间，不到 1 秒整批记 timeout 不发，已部署（deskcore build 73117bd）。入库段变慢另跟 W-21 |
| 2026-10-16 | **W-14：Streamlit 工作台停服** | owner 10-16 在 Railway 停掉；之后 deskcore（build 73117bd）、Jev、TV、tv-worker 四个 `/health` 都 200，没停错服务。仓库与 Supabase 不动（D-072）。aw README 状态随下一次 aw PR 改 |
| 2026-10-16 | **J-09：Jev 超时环境变量** | owner 10-16 在 judge-production 设了 `JEV_TIMEOUT_SEC=6`、`JEV_RETRIES=1`（Jev `/health` 不回显这两个值，以 owner 确认为准） |
| 2026-10-16 | **G-16：仓库变量 `FEATURE_LIMIT`** | 不用去 Settings 看：10-15 features-sync 定时 run 38776935038 的日志里 `FEATURE_LIMIT: 24`，就是 D-089 定的值 |
| 2026-10-16 | **S-03 / S-04：Vercel 上的 service_role key、key 轮换** | owner 10-16：密钥自己管，不再在这里跟踪 |
| 2026-10-16 | **F-02：中转站 prompt caching → 关掉（D-113）** | owner 10-16 问过中转站：没有固定上游账号的分组。按 F-02 实测（read_share 3.2%），带缓存标记按官方计价输入侧贵约 19%、不收溢价时关掉也只少省约 3%，所以不等对账单，特征层 / essence / 馆员默认改发纯字符串 system，`PROMPT_CACHE_ENABLED=1` 可恢复。CI `check_prompt_cache_fallback.py` §7 钉住默认关。部署后核：馆员 `/health` `prompt_cache_enabled=false`、下一次特征层 Done 行 `cache_write=0`。10-16 定 |
| 2026-10-16 | **W-06：发牌到成稿「漏账」，不加硬闸** | 只读核生产（没改消费记录）：7 天发 179 / 销 103，缺口主要在 Hatherine痘痘贴（26/0）。同期飞书 → TV 同步回来 20 篇 Hatherine 已发笔记，写作台只入库 1 篇——稿子照常进了飞书，只是那几场对话里模型没在交付同时调 `commit_drafts`（同一个账号在 sportsix / 百健士 / 西屋 都照常入库）。实际影响很小：每日同步已给这 20 篇补上指纹，查重最多晚一天看到；Hatherine 自 09-02 起 261 个角度只重复过 2 个。其余缺口：百健士 10-12 11:45–12:19 三次发牌 20 张没入库、次日补录副本 12 篇，和 Hatherine 同一模式（交稿没走 `commit_drafts`）；西屋 10-12 那 20 张是 W-19 串内容那场作废的；sportsix 10-15 16:40 十张当时还在写。76 张缺口 = 26 + 20 + 20 + 10，全部有归属（codex review on #189）。不加闸、不需要问写手；漏账灯口径另改（W-22）。10-16 核 |
| 2026-10-16 | **S-08：特征层留在 Railway worker，不搬** | features-sync 自 10-09 起 7 晚连续 success；搬到 GitHub 直跑要重写 ci.yml 里一整组围绕 worker 的守卫（D-047 闸位置、409/502 分类、欠产判据），换来的只是大批回填时少一种「慢被报成失败」——那种情况以核库为准（L-05/S-08 证据已记）。worker 上闲置的 `/annotate-essence`、`/curate` 也先不删：要 key 才能调，CI 的鉴权测试拿它们当探针，删了要连带改测试，没有运行收益；等哪天 worker 整体退役一起删。复议条件：中转站挡 Railway 出口，或又要做千篇级回填。10-16 定 |
| 2026-10-16 | **I-03：隔离表完整版不做，清掉已入库的旧隔离行** | 轻版（D-096 #2）观察一周：每晚新增隔离≈0，「老的又冒」只有 SPX 27 条已认领行；问题不是缺 `last_seen_at`，而是 5,195 条 pending 里大半早已入库。把 notes 里已有对应笔记的 2,477 条（10 个项目）标 `resolved`（`reviewed_by='claude (owner-delegated, I-03)'`，先备份到 `backup_quarantine_resolve_20261016`）；按 D-053 语义，它们若再被隔离会算新情况、照常红。剩 2,718 条 pending 是飞书里一直没正文的行，不动。10-16 核 |
| 2026-10-15 | **L-05：通道 2（馆员 → 写作台经验卡）10-01 起暗了两周** | 根因：馆员服务的 Railway 变量没跟上 10-09 换中转站（D-098 #3），模型调用全报 `InternalServerError`，馆员回 `[]`、写作台 fail-open，两边都不红。owner 10-15 改变量重启后：12:50:45 UTC `flywheel_librarian_cache` 新增 consumer=deskcore 一行（RIO 项目，选中 5 张，select_ms 16,182），馆员 `/health` 的 `prompt_cache_usage.calls=2`、fallback 0。冷借 16 秒超过 open_project 里 10 秒的借阅预算（D-074），所以冷借时简报先回 timeout，随后 `borrow_lessons` 命中缓存即回——这是既有设计，客户端截止仍归 F-04。次日 daily-sync 的「通道 2」灯应转绿。10-15 核 |
| 2026-10-15 | **I-14：#182 修复后首次 Daily 全量定时验收** | schedule run 38698494948（main 04ecb99）success，最终聚合步骤无失败步；飞书 10 个项目 errors 全 0，SPX 588 行 / 555 入库 / 27 条已认领隔离（与修复前一致）；essence 4 个项目 46/46 成功、0 失败；策展成功；用时 35/240 分钟。10-15 核 |
| 2026-10-15核对 | **J-05：外部语料首次定时成功** | Jev run38237686717在10-12 schedule成功；日志apply_rows报告external_notes178行、note_feature_answers4272行。后续仍按周跑/账本新鲜度监控，不再列为“尚未成功一次” |
| 2026-10-13 | **W-01/W-03：MCP线程池与本轮协议** | aw#96已合并，生产build.commit=487403b75fb0、协议3fdff2c0b985、24工具；CI通过。MCP真实并发/身份与REST适配器回归已测；借卡客户端截止仍跟F-04，skill重新导入仍待W-02/J-03 |
| 2026-10-12 | **G-01：闸二正式跑、D-107、审核摘要写库** | 重标三批实际 499/499 篇完整（200 + 200 + 99）；单篇补跑 38233093886 成功；只读 run 38234131740、写库 run 38234730010 都成功；生产回读 55 行完整摘要 `c3dfab5dc85e9c31fdec9e44e43853fe158dc30b0d5e88400c2db535070c11c3` 与报告一致。10 个取值 validated；组合不进 L2（AUC 增益 −0.00105、95% 区间跨零），不是所有后续阶段都已过闸。G-02 新发现审阅、G-03 第一轨、G-04 下一轮组合、J-01 评论能力继续跟踪 |
| 2026-10-10 | TUGE 孤儿补录副本删除（D-104） | owner 在 SQL editor 跑完，回读 version / item / 指纹 / 链接都是 0 |
| 2026-10-12 | D-104 的 6 条 HATHERINE twin 链接不被 tv-sync 改回 | 10-11 那次同步更新了 806 条 unmatched，这 6 条仍是 `ingested`、`updated_at` 停在 10-10 03:07 |
| 2026-10-12 | 过期卡片重新策展（D-096：10-08 时 164/306 张过期） | `recurate-lessons.yml` 10-09 跑了三次；10-12 查 308 张已策展卡里过期 0 张 |
| 2026-10-09 | 写手机器不再持 Jev 密钥、不起 `judge.mcp_server`（审计 A-09） | JevforCoentent#7 / #8，autowriter#95 |
| 2026-10-12 | 西屋911gt 被痘痘贴污染的两条规则清理（硬规则 0c2a7f93 里抄自 Hatherine 的「祛痘、去痘、除螨、抑痘、抗生素、激素、调节激素、连根拔起」；交付格式规则里「弃用旧的“图片梳理”格式」） | 改前原样备份在 `autowriter.backup_memory_xiwu_contam_20261012`（2 行，COMMENT 里有回滚语句）；改后该项目 confirmed 规则里痘 / 图片梳理 / hatherine / 深蓝 / 粉色 / 76片 0 条；全库同类跨项目串词扫描 0 条 |
| 2026-10-10 | 外部语料两个阻塞 bug（Cloudflare 拦 UA、详情解析不出正文） | JevforCoentent#4 合进 main；10-08 第二次手动跑写进 200 篇完整正文 |
