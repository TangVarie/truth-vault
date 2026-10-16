# OPEN-ITEMS · 三仓未完成清单（truth-vault / autowriter·deskcore / JevforCoentent）

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
| ≈ 10-16 | 特征层要不要也搬离 Railway worker；隔离表轻版观察一周后回看 | S-08、I-03 |
| ≈ 10-19 | 节后写作台周产出有没有回到 9 月水平（没回到就查协议 / skill 导入） | O-03 |
| ≈ 10-22 | 删 D-086 两张备份；librarian 延迟对比 D-090 基线；daily-sync 去掉 C-20 的 `|| true`（条件：`stale_in_ssll` 连续两周 0） | S-01、F-03、L-01 |
| 写手回来两周后 | 用真实样本重调 `JUDGE_TIMEOUT_SEC` | J-08 |
| 11-09 之后 | 删 10-09 / 10-10 两批备份表 | S-02 |
| 闸二之后 | 评论能力（J-01 起）、写作台工具阻塞（W-01）、P3 / P4、抽取器与 judge 出影子期的决定 | §1、§2、§3 |

---

## 1. 特征层与闸二 / 闸三（docs/28）

| ID | 事 | 状态与证据 | 谁 | 触发 / 到期 | 来源 |
|---|---|---|---|---|---|
| G-02 | 「新发现，方向未预设」的 validated 特征，下发前 owner 看过 | D-107：brand_first_position=未出现/中间、body_question_marks=>=2、emoji_bucket=0/1-3 共 5 个取值待审；efficacy_promise=是虽 validated 但永不下发 | 你拍板 | 下发新发现之前 | docs/28:316；D-106 #4；D-107 |
| G-03 | 闸三第一轨：冻结现有 essence 打分器，冻结日之后发布的笔记开始写 `content_scores` | 没开始（核：没有任何脚本写 `content_scores`）；P0 里写的是「现在就做、不依赖特征层」；需约 1,060 篇新笔记、1–2 个月 | 工程 | 尽快 | D-065 #8；docs/28:347、:429 |
| G-04 | P3：冻结「essence + 特征」打分器作为闸三第二轨，写作台稿子影子打分（`aw_version`），每周看「落在历史最低 20% 的稿子占比」 | D-107 本轮组合未过（AUC 增益 −0.00105、95% 区间跨零），本轮不启动；G-03 的 essence 第一轨仍可独立推进 | 工程 | 另行预注册的新一轮组合评估过线后 | docs/28:371-373、:432；D-107 |
| G-05 | P4 一组：卡片视图加 `validated_hits`；librarian「已验证规律」缓存块（`gate2_run` 进 `library_version()`）；`prepublish_evaluations` 写模型行 + 按版本回填 `actual_tier`；15% 批级随机探索臂（与 aw 一起）；`v_dash_feature_perf` 和结案报告特征表 | 都没有 | 工程（+ aw） | 闸二 / 闸三 | docs/28:353-392、:433 |
| G-06 | `rank_score` 账号项改成收缩后的账号先验；先修 `personal_bao_rate`（分母含风控 / 删除、分子含数值推断）；改完把书架前 20 前后对比贴进 DECISIONS | 没做 | 工程 | P4 | docs/28:358、:479；D-097 #4 |
| G-07 | 最低 20% 的 `revise` 标记怎么给挑稿的人看 | 没定 | 你拍板（+ aw 维护者） | P3 | D-065 续 #8；docs/28:465 |
| G-08 | 退役 `v_l2_labels_v1` | 没做 | 工程 | 闸二第一轮对完账 | D-067 |
| G-09 | 下一版题库：代码特征 choice 题按取值写方向；新增美妆 / 母婴等项目时复查五道 v2 题面的例子 | 等下一版 | 工程 | 题库升版 | D-106 #4；D-082 |
| G-10 | 救闸一没过的三道（具体时间 / 地点 / 身体感受）：owner 裁约 50 格，`build_gate1_human_sheets.py` 出表 | 这一轮明确不救 | 你拍板 + 你动手（可选） | 想救时 | D-105；D-106 #3 |
| G-11 | 结构类题的层级和半衰期（surface、30 个月）按闸二跨项目稳定性重估 | 工程复评完成：见 `data-analysis/structure-layer-reassessment-2026-10-12.md`；18道中3道含validated值、7道no_signal、7道unreliable、1道reversed；保留surface/30先验，30个月尚无时间估计，跨期验证留季度复跑 | 工程 | 下一次季度闸二（G-12），跨期窗口和支持量预注册后验证 | docs/28:475；D-107 |
| G-12 | 闸二每季度重跑 | 没排期 | 工程 | 每季度 | docs/28:414 |
| G-13 | 抽取器要不要换 Jev（审计 A-10）；换就要：features-sync / backfill 传 `done_by`、`code:v1` 走 `--code-only`、worker `/annotate-features` 改调 `/judge`、修 Jev docs/31 的自相矛盾 | D-105 定的是留 Sonnet 5.5；Jev 还在 v1 题面 | 你拍板 → 工程 | 闸二后 | 审计 A-10；D-085；D-105 |
| G-14 | 抽取器换 Haiku 5.5（省约 20 倍） | 搁置，影子数据在库 | 你拍板 | 成本成问题时 | D-105 #1 |
| G-15 | P5：「投流后增量」做第二标签 | 待定 | 你拍板 | 投流三列攒够数据 | docs/28:434 |
| G-16 | 仓库变量 `FEATURE_LIMIT` 有没有覆盖 yaml 默认 24 | 未核（MCP 看不到仓库变量） | 你动手（GitHub Settings → Variables 看一眼） | 随时 | D-089 #1 |
| G-17 | 最低20%爆率恢复覆盖原全量分析集：为 HXZ_QD/TXQ 的负例补足代表样本，再按新的预注册范围评估 | PR #177 复核发现两项目评估集缺负例整格；本次更正排除它们，只报告有完整标签覆盖项目的最低20%，不声称原全量判据通过 | 工程 | 下一轮需要原全量范围时；不挡本轮「组合不进L2」结论 | D-107 复核；PR #177 |

## 2. Jev（判定服务）

> 定位：一个判定服务挂八个位置（特征层、TV 评论、借卡、发牌、入库判定、三省六部、素人初稿、外部语料），见 jev:docs/00、docs/31。
> 10-12 核：在跑的只有**入库判定**（今天 30 篇稿、690 行账本）、写手手动判稿（deskcore 转发 `judge_draft` / `repair_plan_for` / `list_banks`）、**外部语料**（10-08 入库 200 篇，正文中位 426 字）。账本里 `comment` 0 行、`ssll_sample` 0 行。

| ID | 事 | 状态与证据 | 谁 | 触发 / 到期 | 来源 |
|---|---|---|---|---|---|
| J-01 | **写手的评论能力**：Jev 给评论开 HTTP 端点（判一条给修改单、判一整组评论区）→ deskcore 转发两个新工具 → 协议加「写评论怎么走」 | Jev#9/aw#96已合并并部署；Jev生产health确认comment_tools_enabled=false，writer key鉴权开启且非mock；24工具已在deskcore；700格参考冻结、真实模型对照已完，待错漏复核与owner上线验收 | 工程 | J-03验收后再开开关并真接口核查 | jev:docs/00 #12、docs/01 §4、§6；D-107、D-110 |
| J-02 | 评论回填 ②：9,649 条评论跑运营侧（意图 / 像不像安排的 / 类型）+ 读者侧 7 题，进账本 `subject_type='comment'`，评论构成做闸二候选特征 | shadow workflow/续跑已备，尚未shadow/primary；候选1开发试跑553/700但24格回退，暂不推广；J-03新40条单人参考已固定，C3获本次许可完整复验172/280、69歧义，暂不推广；仍须边界复核/下一版和owner验收；primary还需当前题库摘要的验收记录 | 工程 | J-03独立新参考冻结/独立复验及owner报告验收后小批shadow核查；绑定题库的owner验收记录后primary全量/回读 | docs/31 §4.1、§7.2；D-111 |
| J-03 | 评论参考扩到100条，大健康品类，两人对定义标；与模型对照后验收 | C1获授权完整试跑553/700，24回退、无歧义误报4→12，暂不推广；用户已确认detail_level看可核对文本细节、不强制个人经历。当前C3采用该范围并修缺回复对象提示，已获本次40条许可完成独立复验；历史C1/C2保留。零背景表已返回并委托处理，280格原判固定为单人参考v1，92格异于AI稿、AI覆盖0；定义解释分歧另记。专用评估入口217项通过；C3一次40/40有效，172/280一致、137无歧义一致、69歧义、0缺答；相对参考背书漏报0/28、误报4/12。暂不推广；默认v0.4/关闭。**10-15 起 D-112 门槛轮**：只用 speech_act/names_brand/echoes_post/detail_level 四题判通过（阈值沿用、不放宽），register/reader_value/arranged 降为参考提示；新抽 40 条（sha256 f7b7ffc5…，40/40 核生产一致）答题表已交复核人员；Jev #17 评估工具参考冻结前拒绝调用、只跑一次 | 复核人员（填表）→ 工程（核表冻结、跑一次、出报告） | 复核表返回后 | jev:docs/comment-reader-candidate-2026-10-13.md；D-111 |
| J-04 | 三省六部：二审 Jev 影子跑、采样正文落库再判、预埋评论过评论题库、persona 第三路 | 没接上（核：账本 `ssll_sample` 0 行）；那个仓本会话看不到代码 | 三省六部维护者 | 你决定什么时候推 | jev:docs/00 #5；docs/31 §6；jev:docs/02:226 |
| J-06 | 借卡接 Jev 影子跑 | 没做，借卡还是走 TV librarian | 工程 | 你决定 | docs/31 §3 ③ |
| J-07 | judge 出影子期：最低 20% / 平台硬伤标 `revise`（不拦），修改单要不要随入库返回写手；需要新的 `decision_source` 值 + TV `_MACHINE_DECISION_SOURCES` | 硬编码 shadow；D-103 C-12 维持影子 | 你拍板 → 工程 | 闸二有 validated 特征 | aw:deskcore.md:540；D-103 |
| J-08 | 用真实样本重调 `JUDGE_TIMEOUT_SEC`（看 `batch_metrics` 里 `mode=deskcore_commit`） | 等样本（写手放假，10-08 起 0 样本） | 工程 | 写手回来两周后 | aw:runbook:950；审计 |
| J-09 | judge-production 上设 `JEV_TIMEOUT_SEC=6 JEV_RETRIES=1`（审计 B-08，代码已支持） | 未核 env 是否已设 | 你动手（Railway） | 随时 | jev:`judge/jev_client.py:88-92` |
| J-10 | 核对生产Rx策略与仓内既有许可是否一致 | 仓内10-08 PR5已把OKMAN/OKMAN_phase1加入rx_cleared，本轮未改；project_layer_cleared仍空。带鉴权现网policy回显本次未重测，其他未清出Rx仍403 | 工程 | 有合法鉴权的下一次实际请求核对，不重复索取已有合同许可 | jev:config/data_policy.yaml；HANDOFF |
| J-11 | 「只判 `commit_drafts`、补录稿靠 TV 事后抽取」这条写进 TV DECISIONS；核 TV 抽取确实覆盖补录的项目 | 没记 | 工程 | 随时 | aw:runbook:951 |
| J-12 | `tv_project_map` 完整性：没映射的项目一篇都不判 | 未核；跑 `tv-map list` 对活跃项目 | 工程 | 随时 | aw:runbook:952 |
| J-13 | 素人初稿入口接同一个 `/judge` | 当时就定了后做 | 你拍板 | — | jev:docs/00 #8 |

## 3. 写作台（autowriter / deskcore）

| ID | 事 | 状态与证据 | 谁 | 触发 / 到期 | 来源 |
|---|---|---|---|---|---|
| W-02 | 写手重新导入 skill（本轮 `protocol_version 3fdff2c0b985`） | **先别群发**：J-01 会再改协议，等评论工具上线一起导一次；不导也不会写错（开场核版本会下发新正文） | 你动手 | J-01 上线后 | aw:SKILL.md:35 |
| W-04 | 发牌按结果加权（留 15% 纯随机，只滤「写不出来」的角度） | `v_angle_outcomes` 有、只有 doctor 读；`draw_angles` 还是均匀洗牌 | 工程 | 闸二有 validated 特征、每维样本够 | aw:deskcore.md:342；aw:`core.py:441-478` |
| W-05 | `store.recent_angle_keys` 不翻页，台账大了会静默截断、重复发已用角度 | 未修 | 工程 | 台账变大前 | aw:runbook:964；aw:`store.py:618` |
| W-06 | 发牌到成稿漏账：核对会话中断、commit/export链路，是否加硬闸另拍板 | 10-15 health七日drawn149/consumed73，leak_pct51，2项目超线；本轮未改消费记录，需定位流程断点 | 工程定位 + owner流程确认 | 写手实际使用数据复核 | D-071；aw:HANDOFF |
| W-07 | 借卡质量从没测过；D-088 预筛之后 0 次借卡 | 等样本，对 D-090 基线 | 工程 / 你 | 写手回来 | aw:runbook:945 |
| W-08 | `LIBRARIAN_TIMEOUT_SEC=60` 按 p95 重调（实测 p95 79 秒 / 24 样本；客户端只忍约 22 秒） | 未定 | 工程 | 和 F-03 一起 | aw:`config.py:117-127` |
| W-09 | WorkBuddy 到底用哪种方式传 key（自定义头 / OAuth / `?key=`）没人记过；如果是 `?key=`，key 在访问日志里，要轮换 | 未核 | 你动手（问写手或看 WorkBuddy 配置） | 随时 | aw:deskcore.md:713-721 |
| W-10 | `ingest_target=false` 的映射（RIO ×5、hatherine-QNA）要不要入库目标；它们每晚重配、`tv-resolve` 会报错 | 未定 | 你拍板 | — | 审计 C-11 |
| W-11 | 运营把补录副本重新录成飞书正式行时，tv-sync 关联不回去（10-10 手工修过一次，没有代码路径） | 未处理 | 工程 | 再出现时 | D-104 §2 |
| W-12 | 模糊匹配要人用 `tv-resolve` 处理，没指定人 | 无人负责 | 你指定人 | — | aw:runbook:241 |
| W-13 | 指纹 / 向量：一个 owner + 9 个休眠项目（718 篇老稿）没指纹；提交时的原子复查没覆盖标题语义；`semantic_degraded` 只打日志没有灯；项目名唯一约束没进库；一条全局规则没向量（跑 `reembed_my_rules`）；backfill 5000 行上限 | 都未做 | 工程 | 休眠项目激活时先 backfill；其余低优先 | aw:runbook:936、946、959、963、967 |
| W-14 | 停掉 Streamlit 工作台（前提 09-20 已满足）；README「选定之前不要停」过时 | 没停 | 你动手 | 随时 | aw:runbook:944；D-072 |
| W-15 | Railway 健康检查用 `/health` 还是 `/ready` | 产品决定，没定 | 你拍板 | — | aw:`app.py:577` |
| W-16 | 新中转站：1.8 倍价格系数没对过账单；`-thinking` 后缀、`cache_control` 透传没验证；单点 | 未核 | 你动手（对账单）/ 你拍板 | 随时 | D-098；aw:`config.py:56` |
| W-17 | 远期产品决定：团队共享（`project_members`）；个人调校笔记升项目基线；正例补 essence 标签 | 第一期不做 | 你拍板 | — | aw:deskcore.md:115、818、821 |
| W-19 | **跨项目串内容的防护**（10-12 事故：写手在同一个 WorkBuddy 对话里先写 Hatherine痘痘贴、再切西屋911gt，模型 gemini-3.1-pro-preview 把痘痘贴的规则抄进西屋的硬规则、出了 5 篇痘痘贴文案；deskcore 本身没串，`open_project` 只回本项目 + 全局规则）。要做：① 协议加一条「一个对话只写一个项目，换项目新开对话；`open_project` 拿到的项目名要在回复第一行复述」；② `record_rule` 入库前查内容里有没有同一写手其他项目的品牌名 / 专属词，有就拒并提示；③ `commit_drafts` 时用现成向量比稿子离本项目近还是离该写手的另一个项目近，离别的项目更近就标出来（影子期只记不拦） | aw#96已部署；现场5专属词已配置生产并回读，旧值本地备份；按生产回读配置跑本地已合代码，串词拒绝零写入、正常西屋规则可写（仅fake库）。影子提示已上线；带鉴权线上拒写尚未实测、误报/漏报待样本，不升硬闸 | 工程 | 上线后的影子样本与真实带鉴权调用复核 | 10-12 owner 报告；`autowriter.backup_memory_xiwu_contam_20261012` |
| W-20 | WorkBuddy 里写手用的模型是 gemini-3.1-pro-preview（预览版）：协议按 Claude 调过，换模型后长对话里的上下文隔离、规则遵守没验证过 | 未评估 | 你拍板（要不要统一写手的模型） | — | 10-12 截图 |
| W-18 | aw 文档过时：runbook §1.7「011 尚未执行 / judge 未配置」、「012 没跑」「八个迁移」、7c 飞书六列、#8 4000 行上限；deskcore.md Hatherine「不在 TV」 | 本次补HANDOFF及runbook当前入口；旧段落逐段追平未全完成，不能把历史未配置当当前事实 | 工程 | 后续逐段核迁移/环境和文档 | aw:HANDOFF；aw:runbook |

## 4. 入库与同步（TV）

| ID | 事 | 状态与证据 | 谁 | 触发 / 到期 | 来源 |
|---|---|---|---|---|---|
| I-01 | **统一飞书表准备**：判档版本标记（B4，「第一张新表之前必须有」）、风控否决位（A2）、「观察中」规则（A3）、状态值没匹配的预检告警（A4）、新表族 `capabilities_absent`（A7）、TGV `tier_extraction` 重写（A8，`删除` 归哪你定）、新列 B1–B3 / B5、文档 C1–C6、运营问题 D1–D6、「状态 vs 流量状态」撞名 | 基本没做（grep 都没有） | 工程 + 运营 + 你拍板 | **第一张统一格式表接入之前** | unified-feishu-table-assessment-2026-09-22.md:341-444 |
| I-02 | 全项目每周只读预检（B-16 后半） | 故意没做（怕第一天就红） | 工程 | — | D-095 #2 |
| I-03 | 隔离表完整版（B-15）：`last_seen_at` 列、按原因关；5,013 行待处理，其中 375 行已修好仍挂着 | 轻版 10-09 上线观察一周 | 工程 + 人工复核 | ≈ 10-16 | D-096 #2 |
| I-04 | 评论步骤按内容哈希跳过（A-07a） | 没做，只省 CPU | 工程 | 低 | D-092 |
| I-05 | 两路来源都没有时 `synthetic` 没被显式清掉 | 没做 | 工程 | 低 | D-091 |
| I-06 | 推送侧一晚推多少新爆款要不要封顶 | 没定 | 你拍板 | — | D-087 |
| I-07 | 通道 1 撤回 B 路径（老行按 `ai_analysis->>_truth_vault_note_id`、关读写窗口的 RPC） | 推迟 | 工程 | 出现老行或错撤 | D-087 |
| I-08 | 飞书删了重建的行按 `publish_url` 去重 | 没做，看 verify #93 频率 | 工程 | 视频率 | D-103 B-21 |
| I-09 | 1,051 条 `source_removed` 评论（OKMAN 768 / LNKT 244）怎么处理；源被清空的 27 行 `parser_change` 留着 | 没定 | 你拍板 | — | D-085 |
| I-10 | audit_log 没有保留任务（以后做必须「先抽后删」）；根因 `set_updated_at()` 无条件写 NOW() 没修 | 没做 | 工程 | 低 | D-078 |
| I-11 | LNKT 20 个预声明占位列藏着 2 篇完整抖音笔记（留 / 撤声明、要不要入库）；BJS「蓝词字段」是数字，等运营定格式 | 未核后续 | 你拍板 / 运营 | — | D-053 |
| I-12 | 品牌别名：NRT ×2、TGV 留空待问；力克雷的其他写法 | 待运营 | 运营 | — | ops-answers-2026-09-22.md:482 |
| I-13 | 起量时间的飞书自动化没人知道谁维护，口径改了没处落 | 没人 | 运营 / 你 | — | signal-definitions.md:91；D-062 续 |


## 5. 飞轮、策展、librarian

| ID | 事 | 状态与证据 | 谁 | 触发 / 到期 | 来源 |
|---|---|---|---|---|---|
| F-01 | NUC `direction_subtype` 回填 | 做了一部分（核：10-09 跑过两次；NUC 有 essence 的 657 篇里还缺 126，D-097 时是 206） | 工程（触发 `backfill-essence.yml` mode=missing_subtype） | 随时 | D-097 |
| F-02 | 新中转站上的 prompt caching。10-12 owner 在中转站后台看到缓存几乎没命中。我们这边的请求写法没问题：题目说明放在 system 块、带 `cache_control`、同一组每次一样、1,160–2,004 字（Sonnet 5.5 门槛 512 token）。以前只数「缓存块被拒、降级」，网关静默丢标记时这个数恒为 0。10-12 起特征层 / essence 的 Done 行带 `prompt_cache`（calls / input / cache_write / cache_read / read_share），librarian `/health` 带 `prompt_cache_usage`。判读：write 和 read 都是 0 = 标记没到上游（通道不支持缓存或被剥掉）；write > 0 而 read ≈ 0 = 多上游账号轮转。计数只在进程内，重启就丢 | **核（10-15）：中转站按请求轮转上游账号，缓存基本白写。** 10-13 / 10-14 两次 features-sync 共 85 批、1,082 次调用：cache_write 1,657,401、cache_read 60,682，read_share 3.2%。每批 2 篇 12 次调用，几乎每次都在写缓存；第二篇的 system 和第一篇逐字相同（`feature_bank.render_call` 只由题组决定），本该全读。读到的只有两种：几秒内的校验重问（读 1,741–1,913，约一组），和 85 批里唯一一批第二篇把六组全读到（9,103 / 9,103）——说明标记到了上游、缓存也能用，就是连续请求落在不同账号。按官方计价（写 1.25 倍、读 0.1 倍）算输入侧：现在比完全不带 `cache_control` 贵 18.9%；中转站要是能让同一来源粘在一个账号上，输入侧降到现在的 59%。10-15 Daily 的 essence 同样：4 个项目 49 次调用，每个项目内连续调用 read_share 0–11%。librarian 本进程 0 次成功调用（见 L-05），取不到数。**决定**：代码不动，先问中转站；中转站给不了粘性分组、且 W-16 对账单显示缓存写确实按 1.25 倍收，再给特征层加开关去掉 `cache_control` | 你（问中转站要「同一来源固定上游账号 / 支持 prompt caching」的分组）+ 工程（后备开关） | ≈ 10-22 看中转站答复 | D-097；D-098 |
| F-03 | D-088 预筛有没有用：跑 librarian-cold-baseline 里的对比 SQL，看 p50 / p95 / 超 60 秒条数对基线（49.5 秒 / 79 秒 / 24 条里 7 条）；p95 还 > 60 秒就决定换通道或 `FLYWHEEL_LIBRARIAN_MODEL`；确认 #167 后 Railway 重部署过 | 等样本 | 工程 + 你拍板 | ≈ 10-22 | D-088；D-090 #5 |
| F-04 | aw 借卡：把借卡移出 `open_project` 同步路径（A-04，客户端只忍约 22 秒）；librarian `degraded` 变 `BORROW_ERROR`（B-04） | 未核（aw 侧没查到修复） | 工程（aw） | 写手恢复借卡首批前独立核查/修复并验约22秒截止；W-01已关，不等J-03 | 审计 A-04、B-04 |
| F-05 | `recurate=all` 不收敛，全量重策展前必须按 `curated_at` 升序 | 没做 | 工程 | 全量重策展前 | D-096 |
| F-06 | 32 条孤儿卡片标注（书架闸挡了但已标注）对账（A9） | 未核 | 工程 | 低 | ops-answers-2026-09-22.md:442 |
| F-07 | 清理：推送时代残留（`preview_injection_candidates.py`、`v_autowriter_injection_candidates`、`v_flywheel_sync_status` 里的 aw 列、docs/09）；孤儿脚本 `annotate_comment_threading.py` 和两个 `migrate_*.py` | 没做 | 工程 | 低 | D-063；D-075 |

## 6. 灯与看板

| ID | 事 | 状态与证据 | 谁 | 触发 / 到期 | 来源 |
|---|---|---|---|---|---|
| L-01 | 去掉 daily-sync.yml:438 stale / gated / retract 摘要上的 `|| true`（C-20） | 还在 | 工程 | `stale_in_ssll` 连续两周 0（≥ 10-22） | D-087；D-103 |
| L-02 | deskcore `/health` 的 `config.pipeline` 没人定期看 | 已知缺口 | 你拍板 | — | docs/29:42 |
| L-03 | 每周看灯：`LIBRARIAN_TRAFFIC`、`ANGLE_LEDGER`、`EXTERNAL_CORPUS`、Jev `external-corpus.yml` | 例行 | 你动手（周一定时检查会代看一遍） | 每周 | docs/29:32-44 |
| L-04 | 看板：docs/24 Phase 3–4（内部页 Supabase Auth、自定义域名）；docs/24:136 还让人配 service_role（文档漂移）；v1_19 两列没上 Vercel（已接受，C-13） | 未核 / 已接受 | 工程 / 你拍板 | — | docs/24 |

## 7. 运维、密钥、备份

| ID | 事 | 状态与证据 | 谁 | 触发 / 到期 | 来源 |
|---|---|---|---|---|---|
| S-01 | 删 D-086 两张备份：`truth_vault.reference_samples_backup_tv_stale_20261008`、`truth_vault.notes_ssll_marker_backup_20261008`（先确认三省六部没反映参考池变薄） | 到期前 | 你动手（SQL editor） | ≈ 10-22 | D-086；D-103 |
| S-02 | 删 10-09 / 10-10 备份：`truth_vault.backup_inverted_lineage_20261009`、`truth_vault.backup_{notes,nfa,comments,metric_snapshots}_vanished_20261009`、`autowriter.backup_tv_note_links_inverted_20261009`、`autowriter.backup_items_self_review_20261009`、`autowriter.backup_tv_note_links_vanished_20261009`、`autowriter.backup_tv_note_links_twins_20261010`、`autowriter.backup_orphan_ingest_tuge_20261010`、`autowriter.backup_memory_xiwu_contam_20261012`；`truth_vault.backup_notes_vanished_20261009` 的 COMMENT 里有回滚顺序 | 到期前（verify #92 也会提示） | 你动手 | 11-09 之后 | D-099；D-102；D-103；D-104 |
| S-03 | 删 Vercel 项目 truth-vault 上的 `SUPABASE_SERVICE_ROLE_KEY` | 未核（10-12 用 Vercel 连接查环境变量被拒 403，只能你看） | 你动手 | 随时 | D-101 #5 |
| S-04 | service_role key（2026-05 起一直在用）按 R-032 SOP 轮换 | 没做 | 你拍板 / 你动手 | — | RISKS.md:556-578 |
| S-05 | docs/04 新服务清单加一条「更新 R-032 key → 持有者矩阵」 | 没写 | 工程 | 低 | RISKS.md:581 |
| S-06 | 开 RLS 后三省六部还能不能读、它实际用哪把 key（读到 0 行就回滚或换 key）；三省六部下次在 `public` 建表时收回 anon 默认权限 | 未核 | 工程 / 你 | 三省六部下次跑 | D-101 |
| S-07 | 改动后跑一遍 `verify_supabase_state.sql`，重点 #88 #89 #91 #92 #93 #94 | 部分核过（10-12：HATHERINE 6 条 twin 链接在 10-11 同步后仍是 `ingested`；TUGE 孤儿副本已删、回读 0） | 工程 | 每次大改后 | D-099；D-102；D-104 |
| S-08 | 特征层要不要也搬离 Railway worker 改 GitHub 直跑；搬完删 worker 的 `/annotate-essence` 和 `/curate`（worker/app.py:267、:377 还在）并记新 D；D-077 的根修并进来 | 没定。新证据（10-12 重标第三批 run 38209316795）：5 批先吃 Railway 网关 502（慢批超过网关时限），worker 在后台照样跑完、一直占着锁，后面的重试全是 409，CI 判「5 批失败」，核库 99 篇里 98 篇其实已写齐——worker 这条路会把「慢」报成「失败」 | 工程 | 直跑稳定一周后（≈ 10-16） | D-100 |
| S-09 | 小工程：迁移命名与 `dashboard_views_*` / `security_*` 部署清单（C-16）；密钥打码没盖住隔离路径的 `print()`；备份 RPO / RTO 没定义（R-015） | 没做 | 工程 / 你拍板 | 低 | 审计 C-16；D-095；RISKS.md:182 |

## 8. 你要做的（从上面挑出来，方便一次看完）

| 条目 | 一句话 |
|---|---|
| J-03 | 这一次C1已试跑完，文本细节口径已按你的A/D判定确认；新40条已返回，依委托固定280格单人原判参考；C3获本次许可独立复验完成172/280一致，暂不推广，下一步边界复核；旧A/B不重填 |
| W-02 | skill 重新导入：**等 J-01 上线后**一起导，现在先不群发 |
| W-09 | 问写手 WorkBuddy 里 deskcore 的 key 是怎么填的（头 / OAuth / 网址里 `?key=`） |
| W-14 | 停 Streamlit 工作台 |
| W-16 | 对一次中转站账单，看 1.8 倍系数对不对；顺便看缓存写是不是按 1.25 倍收 |
| F-02 | 问中转站有没有「同一来源固定上游账号、支持 prompt caching」的分组（现在按请求轮转，缓存读到 3.2%） |
| J-09 | 核对Railway上Jev超时环境变量；J-10的OKMAN既有放行不再重复申请 |
| S-01、S-02 | 到期删备份（10-22 / 11-09 之后） |
| S-03、S-04 | Vercel 上删 service_role key；找时间轮换 service_role key |
| G-16 | GitHub 仓库变量里看一眼有没有 `FEATURE_LIMIT` |
| 拍板类 | G-02、G-07、G-13、I-06、I-09、I-11、W-10、W-15、W-17、J-04 何时推三省六部 |
| O-01 | 运营：I-12 品牌别名、I-13 起量时间自动化归属、I-01 统一表 D1–D6 |
| O-03 | ≈ 10-19 看节后写作台周产出有没有恢复 |

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
