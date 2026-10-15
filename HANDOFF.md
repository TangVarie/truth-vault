# 三库交接总览 · 2026-10-15

本轮接管覆盖 **2026-10-12～15**。同步/数据库/写作台生产快照截至 **2026-10-15 12:04（北京时间）**；本次评论返回与C3复验记录核对于 **2026-10-15 19:34（北京时间）**，不表示其他生产数字也在该时刻重新检查。本文汇总已做检查、实际改动、证据与下一步；日常待办仍维护在 [OPEN-ITEMS.md](OPEN-ITEMS.md)，决策原因见 [DECISIONS.md](DECISIONS.md) D-107～D-111。更早的设计与部署属于继承状态，不表示本轮重新验证或实施过。

## 接手先看这五件事

1. 闸二本轮已完成：最后重标批次和55行验证均已核验。**组合不进入L2**，未据此调整检索权重。
2. 评论工程已合并、已部署，**生产评论开关仍关闭**。旧100条参考已定，模型对照已做，但尚无上线验收。
3. 新40条人员复核已返回并核验，280格原判固定为单人参考v1，与AI草稿92格不同、AI覆盖0格。专用评估及零调用预检已过；另获此次许可完成C3一次真实复验172/280一致、69歧义、0缺答，不推广；题意差异另记，上线未验收。
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

GitHub只放代码、合成测试、匿名汇总和摘要。真实评论/帖子、原表、仲裁、固定题面、完整SQL抽样及评估包仍只本地；这些路径是**当前工作区**路径，换机器要由owner安全转交，不保证GitHub Actions或新checkout里存在。不要重抽一批来凑相同ID，也不要上传原文作为文档附件。

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
