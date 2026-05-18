# Truth Vault · 当前状态

> 这个文件是项目的"实时状态快照"。每次会话结束时由 Claude 输出新版本、Ziao 提交进 repo。新会话开始时第一个读的文件。

**最后更新**: 2026-05-18  
**当前阶段**: 阶段 0 · 设计（Schema 设计、文档奠基期）  
**当前会话编号**: #1（首次完整项目文档奠基）

---

## 项目状态概览

### 已完成 ✅

- [x] **10 个项目数据审计** —— 6,332 行数据完整盘点，发现三个 schema 家族、tier 标签分布、数据完整度图谱（见 [data-analysis/10-project-audit.md](data-analysis/10-project-audit.md)）
- [x] **三层架构论证** —— Surface / Essence / Audience 分层（见 [docs/01-architecture.md](docs/01-architecture.md)）
- [x] **Schema v1 设计** —— 包含三层字段（见 [docs/02-schema-v1.md](docs/02-schema-v1.md)）
- [x] **三个家族的映射协议** —— A/B/C 家族字段差异和对齐方案（见 [docs/03-mapping-protocol.md](docs/03-mapping-protocol.md)）
- [x] **新项目 onboarding SOP** —— 20-40 分钟流程（见 [docs/04-onboarding-sop.md](docs/04-onboarding-sop.md)）
- [x] **受控词表 v0.1 草案** —— 6 个核心词表（见 [docs/05-controlled-vocab.md](docs/05-controlled-vocab.md)）
- [x] **关键决策落档** —— 8 条核心决策（见 [DECISIONS.md](DECISIONS.md)）

### 进行中 🔧

无 —— 当前等待 Ziao review 文档后启动下一步。

### 待启动 📋

- [ ] **受控词表 v0.1 评审**（Ziao + 周哥）
- [ ] **NUC_1 试点 onboarding**（第一个吃螃蟹的项目）
- [ ] **NRT 系列方向拆解会议**（最复杂，需 1 小时专门讨论）
- [ ] **B 家族粉丝数补录**（约 2,300 条历史数据）
- [ ] **历史数据 essence 回标**（约 3,400 条，¥1000-1500 预算）
- [ ] **蒲公英后台数据账号清单**（哪些项目有权限）
- [ ] **NewAPI 网关部署**（独立于 Truth Vault 但相关）
- [ ] **FastAPI 服务搭建**（阶段 1 工程开发起点）

---

## 下一步要做的事（按优先级）

### #1 · 受控词表 v0.1 评审 ⭐ 当前阻塞点

**为什么阻塞**: Essence 层标注必须基于闭集词表。词表错了 → essence 数据废 → 三层架构核心层失效。

**需要谁**: Ziao + 周哥（策略视角）

**评审重点**:
- `emotional_lever` 10 个值是否覆盖了帆谷历史项目里所有触发模式？
- `human_truth_archetype` 15-20 个值是否够用？哪些可能漏掉了？
- `target_audience` 闭集值是否需要细分？（如"宝妈"要不要拆"育儿早期" vs "育儿中期"）
- `trend_dependencies` 时效性标签是否需要增减？

**输入文档**: [docs/05-controlled-vocab.md](docs/05-controlled-vocab.md)

**输出**: 受控词表 v0.2（带 Ziao/周哥 review comments）

**预计耗时**: 1 小时讨论 + 0.5 小时整理

---

### #2 · NUC_1 试点 onboarding

**为什么是 NUC_1**: 数据最干净（tier 标签完整 114 爆 / 553 趴、数据回收率 59%、文案 657 条）、方向相对简单（4 个）。

**需要谁**: Ziao（onboarding 主持） + 项目经理（提供原始 context）

**操作步骤**: 见 [docs/04-onboarding-sop.md](docs/04-onboarding-sop.md)

**输出**: 
- `mappings/NUC_phase1.yaml`（项目的 onboarding 配置）
- 试点报告：onboarding 流程的盲点和优化建议

**预计耗时**: 30 分钟

---

### #3 · NRT 系列方向拆解会议

**为什么单独排**: NRT_2 / NRT_3 的"方向"字段是 10 个项目里维度混杂最严重的（身份 + 产品形式 + 内容方向三维混编 + 组合标签）。自动化方案做不出来，必须策略 lead 亲自拍。

**需要谁**: Ziao 或周哥（必须，无法委托）

**输入**: [data-analysis/10-project-audit.md](data-analysis/10-project-audit.md) 中 NRT 方向取值清单

**输出**: 
- `mappings/NRT_phase2.yaml`
- `mappings/NRT_phase3.yaml`

**预计耗时**: 1 小时

---

### #4 · 蒲公英后台数据账号清单整理

**为什么现在做**: Ziao 提到这件事现在就能做。趁热做掉，为阶段 1 的 audience 校准做准备。

**需要谁**: Ziao + 投放执行同事

**输出**: 一张表，列出：
- 哪些项目的投放笔记我们有蒲公英后台权限
- 每个项目可以拉哪些字段（年龄 / 性别 / 城市 是基础，其他视权限）
- 数据格式（csv 导出还是 API 拉取）

**预计耗时**: 0.5-1 小时

参见: [docs/07-audience-data.md](docs/07-audience-data.md)

---

### #5 · 工程启动

只有 #1-#4 都过了才启动。具体见 [docs/08-evolution-roadmap.md](docs/08-evolution-roadmap.md) 阶段 1 部分。

---

## 当前未决问题（议程）

逐项需要在后续会话中拍板：

- **[Q1]** `target_audience` 的"宝妈"是否要细分为"育儿早期" vs "育儿中期" vs "二胎宝妈"？
- **[Q2]** `human_truth_archetype` 是否需要包含"宠物相关"原型？（NUC 数据里有一些宠物角度）
- **[Q3]** TGV_1 的"删0"备注，归类为 `tier=删除` 还是 `tier=风控`？影响训练数据筛选。
- **[Q4]** 是否对 QSHG_1 这种纯无标注数据，使用半监督学习方式利用？还是只作为 archive？
- **[Q5]** 蒲公英拉数据时，是否需要先和客户对齐合规条款？（特别是处方药客户）
- **[Q6]** Schema v1 是否保留"项目阶段"字段？目前所有项目都没填值，但飞书表有这一列。

---

## 重要 context（新窗口必读）

### 这个项目的起源

这个项目从 Ziao 看到 OranAi 的 oransim 开源项目开始 → 探讨"AI persona 评估内容质量"的可行性 → 发现持续提升需要"真实数据回流"作为锚 → 演化为"帆谷私有 Truth Vault" 数据飞轮项目。

完整对话轨迹（关键节点）：
1. 评审 oransim 项目 → 结论：算法不是护城河，回流数据才是
2. 讨论 persona 接入 sanshengliubu / autowriter / seeding-prompt-refiner
3. Ziao 提出"真实数据支撑"是真正的数据飞轮 → 提出"管家"概念
4. RAG 路线被否决 —— Ziao 直觉判断"匹配本质粗浅"，用 RIO 数据验证
5. 三段式映射架构（人 + 工程 + LLM）解决"对齐不可自动化"问题
6. 10 个项目数据审计 → 发现三个 schema 家族 + 方向字段多维问题
7. Ziao 提出三层架构（Surface / Essence / Audience）—— 这是 schema 真正的灵魂
8. 文档奠基（当前会话）

### 几个关键决策的核心理由

读 [DECISIONS.md](DECISIONS.md) 看完整版。摘要：

- **D-001** Schema 不能只有 surface 层 —— 表层信息时间衰减快，无法穿越周期
- **D-002** 拒绝 RAG 作为主要检索方法 —— embedding 无法区分爆款 vs 趴款
- **D-003** "方向"字段必须在 schema 层面拆解为多维 —— 单字段多维语义破坏跨项目可比性
- **D-004** 管家不允许做内容判断 —— 锁住 LLM 幻觉风险
- **D-005** 历史数据必须回标 essence —— 取上得中，第一天就要高
- **D-006** A 家族（RIO/WTG/TXQ）是最新格式 —— 之前判断反了，需修正
- **D-007** TGV_1 备注"新爆"是 tier 金标准 —— C 家族数据可用性升级
- **D-008** Schema v1 必须包含 audience 层字段 —— 蒲公英数据校准的预留位

### 这个项目的核心哲学

**取上得中，取中得下，取下而不得**。Schema 起点决定了未来六个月所有可能性的上限。

数据库的价值 = 数据量 × 数据分层质量²。分层质量平方贡献，不能将就。

---

## 新会话开场协议

新窗口的 Claude 接到这个项目时，**严格按以下顺序操作**：

1. 用 web_fetch 或读取上传文件，按顺序读取：
   - `README.md` 
   - `CURRENT_STATE.md`（本文件）
   - `DECISIONS.md`

2. 用一两句话**反向陈述**你理解的：
   - 当前阶段
   - 下一步要做的事 #1 是什么
   - 是否有未决问题需要先讨论

3. 等 Ziao 确认你理解正确后，再开始工作。

如果 Ziao 的请求和你刚读到的 CURRENT_STATE 不一致（比如他想跳过 #1 直接做 #3），先问一下原因，**不要默默放弃当前阻塞点**。

---

## 会话交接模板

每次会话结束时，Claude 主动输出以下内容，Ziao commit 到 repo：

```markdown
## Session #N 交接 · YYYY-MM-DD

### 本次会话做了什么
- ...

### CURRENT_STATE.md 应该更新成什么
[贴上完整的更新后 markdown]

### 文档应该新增/修改什么
- 新增: docs/XX-...
- 修改: docs/YY-...

### 下次会话应该从哪里开始
建议开场词:
[...]
```
