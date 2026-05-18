# Truth Vault · 当前状态

> 这个文件是项目的"实时状态快照"。每次会话结束时由 Claude 输出新版本、Ziao 提交进 repo。新会话开始时第一个读的文件。

**最后更新**: 2026-05-18
**当前阶段**: 阶段 0 · 设计 → 即将进入阶段 1 · 描述性 anchor
**当前会话编号**: #2（受控词表 v0.2 finalized）

---

## 项目状态概览

### 已完成 ✅

- [x] **10 个项目数据审计** —— 6,332 行数据完整盘点（见 [data-analysis/10-project-audit.md](data-analysis/10-project-audit.md)）
- [x] **三层架构论证** —— Surface / Essence / Audience 分层（见 [docs/01-architecture.md](docs/01-architecture.md)）
- [x] **Schema v1 设计** —— 包含三层字段（见 [docs/02-schema-v1.md](docs/02-schema-v1.md)）
- [x] **三个家族的映射协议** —— A/B/C 家族字段差异和对齐方案（见 [docs/03-mapping-protocol.md](docs/03-mapping-protocol.md)）
- [x] **新项目 onboarding SOP** —— 20-40 分钟流程（见 [docs/04-onboarding-sop.md](docs/04-onboarding-sop.md)）
- [x] **受控词表 v0.2 finalized** ⭐ 本次会话完成（见 [docs/05-controlled-vocab.md](docs/05-controlled-vocab.md)）
- [x] **Essence 标注 prompt v0.2 同步** —— prompts/essence_annotator.md 与词表对齐
- [x] **关键决策落档** —— D-001 ~ D-009（见 [DECISIONS.md](DECISIONS.md)）

### 进行中 🔧

无 —— 当前等待启动 NUC_1 试点 onboarding。

### 待启动 📋

- [ ] **NUC_1 试点 onboarding** ⭐ 新阻塞点
- [ ] **NRT 系列方向拆解会议**（1 小时专门讨论）
- [ ] **B 家族粉丝数补录**（约 2,300 条历史数据）
- [ ] **历史数据 essence 回标**（约 3,400 条，¥1000-1500 预算）
- [ ] **蒲公英后台数据账号清单**（哪些项目有权限）
- [ ] **NewAPI 网关部署**（precursor to Truth Vault FastAPI 服务）
- [ ] **FastAPI 服务搭建**（阶段 1 工程开发起点）
- [ ] **周哥二次 review 词表 v0.2**（可选，不阻塞）

---

## 下一步要做的事（按优先级）

### #1 · NUC_1 试点 onboarding ⭐ 当前阻塞点

**为什么是阻塞点**: 词表 v0.2 已定稿，下一步必须用真实项目验证整套流程（onboarding SOP + 字段映射 + tier 抽取 + essence 标注 + audience 推断）。NUC_1 是数据最干净的项目，最适合做试点。

**为什么是 NUC_1**:
- 数据最干净（tier 标签完整 114 爆 / 553 趴）
- 数据回收率 59%（B 家族中最高）
- 方向相对简单（4 个用户场景：营养代餐/术后恢复/糖尿病/抗癌放化疗）
- 保健品合规相对清晰
- mapping yaml 草案已准备好（见 [mappings/NUC_phase1.yaml](mappings/NUC_phase1.yaml)）

**需要谁**:
- Ziao（必须，方向拆解和 tier 阈值最终拍板）
- NUC 项目经理（提供原始 context）
- 新会话 Claude（执行 onboarding SOP）

**操作步骤**: 按 [docs/04-onboarding-sop.md](docs/04-onboarding-sop.md) 的 7 步走

**预期输出**:
- `mappings/NUC_phase1.yaml` 定稿版（替换当前草案）
- 试点报告：onboarding 流程的盲点和优化建议
- 跑 30 条样本 essence 标注，验证 v0.2 词表实操可用性

**预计耗时**: 30-40 分钟 onboarding + 1 小时 pilot 标注

---

### #2 · 蒲公英后台数据账号清单整理

**为什么并行做**: Ziao 提到这件事可以立刻做，不需要等 #1。趁热做掉，为阶段 1 后期 audience 校准做准备。

**需要谁**: Ziao + 投放执行同事

**输出**: 一张表，列出：
- 哪些项目的投放笔记我们有蒲公英后台权限
- 每个项目可以拉哪些字段（年龄 / 性别 / 城市 是基础，其他视权限）
- 数据格式（csv 导出还是 API 拉取）

**预计耗时**: 0.5-1 小时

参见 [docs/07-audience-data.md](docs/07-audience-data.md)。

---

### #3 · NRT 系列方向拆解会议

**为什么单独排**: NRT_2 / NRT_3 的"方向"字段是 10 个项目里维度混杂最严重的（身份 + 产品形式 + 内容方向三维混编 + 组合标签如"为爱助戒, 咀嚼胶"）。自动化方案做不出来，必须策略 lead 亲自拍。

**需要谁**: Ziao 或周哥（必须，无法委托）

**输入**: [data-analysis/10-project-audit.md](data-analysis/10-project-audit.md) 中 NRT 方向取值清单

**输出**:
- `mappings/NRT_phase2.yaml`
- `mappings/NRT_phase3.yaml`

**预计耗时**: 1 小时

建议在 #1（NUC_1 onboarding）跑通之后做 —— 利用 NUC 的经验，NRT 拆解会更顺。

---

### #4 · 工程启动

只有 #1-#3 都过了才启动。具体见 [docs/08-evolution-roadmap.md](docs/08-evolution-roadmap.md) 阶段 1 部分。

启动顺序：
1. NewAPI 网关部署（独立任务，可早做）
2. Supabase 项目创建 + schema SQL 执行（[schemas/notes_v1.sql](schemas/notes_v1.sql)）
3. FastAPI 项目脚手架 + 飞书 import 脚本
4. 历史数据导入（已 onboarded 项目）
5. Essence 全量回标 pipeline

---

## 当前未决问题（议程）

逐项需要在后续会话中拍板。**词表评审完成后，议程区清空了几项，新增几项**：

### 已完成清理
- ~~[Q1] target_audience 的"宝妈"是否要细分？~~ → **D-009 决定不细分**（life_stage 字段处理）
- ~~[Q2] human_truth_archetype 是否需要包含"宠物相关"？~~ → **D-009 决定新增**

### 仍未决
- **[Q3]** TGV_1 的"删0"备注，归类为 `tier=删除` 还是 `tier=风控`？影响训练数据筛选。
- **[Q4]** 是否对 QSHG_1 这种纯无标注数据，使用半监督学习方式利用？还是只作为 archive？
- **[Q5]** 蒲公英拉数据时，是否需要先和客户对齐合规条款？（特别是处方药客户）
- **[Q6]** Schema v1 是否保留"项目阶段"字段？目前所有项目都没填值，但飞书表有这一列。

### 新增议程（v0.2 词表使用后可能出现的）
- **[Q7]** 是否在 NUC_1 pilot 标注后做一次 v0.2 → v0.3 微调？（看 30 条样本的标注难点）
- **[Q8]** "时代语言范式" 这个标签的子模式（夸张式自嘲/反向表达等）将来是否升级到闭集？
- **[Q9]** Surface 三级时间衰减权重是否要 A/B 测试不同半衰期数值？

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
7. Ziao 提出三层架构（Surface / Essence / Audience）—— schema 真正的灵魂
8. **会话 #1**：文档奠基（11 个核心文档 + schema SQL + mapping 模板）
9. **会话 #2（当前）**：受控词表 v0.2 finalized，引入三级时间分层

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
- **D-009** ⭐ 词表 v0.2 finalized —— 引入三级时间分层（通用/时代语言范式/当代流行词）

### 这个项目的核心哲学

**取上得中，取中得下，取下而不得**。Schema 起点决定了未来六个月所有可能性的上限。

数据库的价值 = 数据量 × 数据分层质量²。分层质量平方贡献，不能将就。

### 会话 #2 引入的新概念："时代语言范式"

Ziao 在词表 review 时提出深刻洞察：在"具体流行词"和"穿越周期的通用"之间，存在一层**结构性话术模式**（夸张式自嘲、反向表达、缩写文化、emoji 配文化、数字+夸张、拟人化）。

这一层的半衰期约 2-3 年（比流行词长，比纯通用短），反映时代特征但有迁移性。识别这一层是数据库支持"引领新话术而不是模仿"的算法基础。

trend_dependencies 词表因此重构为三级时间分层：
- 通用（5 年+ 半衰期）
- 时代语言范式（2-3 年）
- 当代流行词（6-12 月）

Surface 层时间衰减权重按此三级独立计算。详见 [docs/05-controlled-vocab.md](docs/05-controlled-vocab.md) 第 7 节。

---

## 新会话开场协议

新窗口的 Claude 接到这个项目时，**严格按以下顺序操作**：

1. 用 web_fetch 或读取上传文件，按顺序读取：
   - `README.md`
   - `CURRENT_STATE.md`（本文件）
   - `DECISIONS.md`

2. 如果接下来要做 NUC_1 onboarding，额外读取：
   - `docs/04-onboarding-sop.md`
   - `docs/05-controlled-vocab.md`
   - `mappings/NUC_phase1.yaml` (草案)

3. 用一两句话**反向陈述**你理解的：
   - 当前阶段
   - 下一步要做的事 #1 是什么
   - 是否有未决问题需要先讨论

4. 等 Ziao 确认你理解正确后，再开始工作。

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
