# Truth Vault · 当前状态

> 这个文件是项目的"实时状态快照"。每次会话结束时由 Claude 输出新版本、Ziao 提交进 repo。新会话开始时第一个读的文件。

**最后更新**: 2026-05-18
**当前阶段**: 阶段 0 · 设计 → 即将进入阶段 1 · 描述性 anchor
**当前会话编号**: #4（议程清理 + D-012 核心架构原则确立）

---

## 项目状态概览

### 已完成 ✅

- [x] **10 个项目数据审计** —— 6,332 行
- [x] **三层架构论证** —— Surface / Essence / Audience
- [x] **Schema v1 设计** —— 含三层字段
- [x] **三个家族的映射协议** —— A/B/C
- [x] **新项目 onboarding SOP** —— 7 步流程
- [x] **受控词表 v0.2 finalized**
- [x] **Essence 标注 prompt v0.2**
- [x] **NRT_phase3 mapping yaml** —— 17 方向 + 1 异常
- [x] **NRT_phase2 mapping yaml** —— 21 方向 + 1 异常
- [x] **数据质量监控机制设计** ⭐ Session #4 新增（D-013）
- [x] **核心架构原则: 按 intent 分轨**  ⭐ Session #4 新增（D-012）
- [x] **关键决策落档** —— D-001 ~ D-013

### 进行中 🔧

无 —— 当前等待启动 NUC_1 试点 onboarding。

### 待启动 📋

- [ ] **NUC_1 试点 onboarding** ⭐ 当前阻塞点
- [ ] **NRT_2/3 mapping yaml 实操 review**
- [ ] **B 家族粉丝数补录**（约 2,300 条）
- [ ] **历史数据 essence 回标**（约 3,400 条，¥1000-1500）
- [ ] **蒲公英后台数据账号清单**
- [ ] **NewAPI 网关部署**
- [ ] **FastAPI 服务搭建**
- [ ] **周哥二次 review 词表 v0.2**（可选，不阻塞）
- [ ] **NRT tier 阈值实操校准**
- [ ] **更新 onboarding-sop.md Step 3**（D-010 target_audience 含义微调）
- [ ] **D-013 sanity check 工程实现**（schema v1.1 加 data_quality_flags 字段）

---

## 下一步要做的事（按优先级）

### #1 · NUC_1 试点 onboarding ⭐ 当前阻塞点

**为什么是阻塞点**: 所有架构和词表都已就绪。下一步必须用第一个真实项目（NUC_1，最干净）验证整套流程。

**为什么是 NUC_1**:
- 数据最干净（114 爆 / 553 趴 tier 完整）
- 数据回收率 59%（B 家族最高）
- 方向相对简单（4 个用户场景）
- 保健品合规相对清晰
- mapping yaml 草案已准备好 [mappings/NUC_phase1.yaml](mappings/NUC_phase1.yaml)

**需要谁**:
- Ziao（必须）
- NUC 项目经理（提供原始 context）
- 新会话 Claude

**操作步骤**: 按 [docs/04-onboarding-sop.md](docs/04-onboarding-sop.md) 的 7 步走

**注意 Session #3-4 引入的两个新原则**:
- **D-010** target_audience 标"该项目+该方向的实际策略意图"，不是理论集合
- **D-012** 按 intent 分轨原则——onboarding 时记录 intent，将来训练分类器时分组

**预期输出**:
- `mappings/NUC_phase1.yaml` 定稿版（替换当前草案）
- 试点报告
- 30 条样本 essence 标注，验证 v0.2 词表实操可用性

**预计耗时**: 30-40 分钟 onboarding + 1 小时 pilot 标注

---

### #2 · 蒲公英后台数据账号清单整理

**为什么并行做**: 不阻塞 #1。Ziao 可以在和项目经理对接 NUC_1 之前/之后做掉。**Session #4 已确认**：不需要先和客户做合规对齐（R-012），可以直接做。

**需要谁**: Ziao + 投放执行同事

**输出**: 一张表，列出哪些项目有蒲公英权限 / 能拉什么字段

**预计耗时**: 0.5-1 小时

---

### #3 · NRT_phase3 / NRT_phase2 实操 review

排在 NUC 之后。需要 Ziao + 数据导入后看真实互动量中位数校准 tier 阈值。

---

### #4 · 工程启动

只有 #1 跑通才启动。具体见 [docs/08-evolution-roadmap.md](docs/08-evolution-roadmap.md) 阶段 1。

启动顺序：
1. NewAPI 网关部署
2. Supabase 项目创建 + schema SQL 执行（**注意 schema v1.1 需要加 data_quality_flags 字段，对应 D-013**）
3. FastAPI 项目脚手架 + 飞书 import 脚本
4. 历史数据导入
5. Essence 全量回标 pipeline + sanity check 集成

**关键架构提醒**: 阶段 2 训练分类器时**必须按 intent 分轨**（D-012）：
- `predict_explosion_likelihood` for intent=traffic
- `predict_conversion_effectiveness` for intent=conversion
- 不能用统一模型把 intent 作为特征传入

---

## 当前未决问题（议程）

### Session #4 清理完成 ✅
- ~~[Q3] TGV_1 "删0" 归类~~ → **D-007 补充**: 主动删除（不是风控），训练时作为强负样本合并到"趴"
- ~~[Q5] 蒲公英拉数据合规~~ → **R-012**: 撤销过度担忧，是日常工作流程
- ~~[Q10] NRT 男性自发标注混杂~~ → **D-013**: ingest 阶段 LLM sanity check + flag
- ~~[Q11] 单标产品形式 0 爆款怎么处理~~ → **D-012**: 按 intent 分轨训练，产品向走独立 conversion 模型

### 仍未决
- **[Q4]** 是否对 QSHG_1 这种纯无标注数据，使用半监督学习方式利用？还是只作为 archive？
- **[Q6]** Schema v1 是否保留"项目阶段"字段？目前所有项目都没填值。
- **[Q7]** 是否在 NUC_1 pilot 标注后做一次 v0.2 → v0.3 微调？
- **[Q8]** "时代语言范式" 这个标签的子模式（夸张式自嘲/反向表达等）将来是否升级到闭集？
- **[Q9]** Surface 三级时间衰减权重是否要 A/B 测试不同半衰期数值？

### 新增议程（Session #4 引入）
- **[Q13]** D-013 sanity check 机制要不要扩展到其他字段（不只是 audience，比如 intent / content_format）？
- **[Q14]** intent=conversion 模型的 ground truth 是什么？蓝词命中率 + 互动率？还是只看蓝词？

---

## 重要 context（新窗口必读）

### 这个项目的起源

这个项目从 Ziao 看到 OranAi 的 oransim 开源项目开始 → 探讨"AI persona 评估内容质量"的可行性 → 发现持续提升需要"真实数据回流"作为锚 → 演化为"帆谷私有 Truth Vault" 数据飞轮项目。

完整对话轨迹（关键节点）：
1. 评审 oransim 项目 → 算法不是护城河，回流数据才是
2. RAG 路线被否决 —— "匹配本质粗浅"
3. 10 个项目数据审计
4. Ziao 提出三层架构（Surface / Essence / Audience）—— schema 灵魂
5. **会话 #1**：文档奠基（11 个核心文档 + schema SQL + mapping 模板）
6. **会话 #2**：受控词表 v0.2 finalized，引入三级时间分层
7. **会话 #3**：NRT_phase3 + NRT_phase2 方向拆解，确立 D-010 + D-011
8. **会话 #4（当前）**：议程清理（4 个 Q 落档），确立 D-012 核心架构原则（按 intent 分轨）+ D-013（数据质量监控）

### 几个关键决策的核心理由

读 [DECISIONS.md](DECISIONS.md) 看完整版。摘要：

- **D-001** Schema 必须有 essence 层
- **D-002** 拒绝 RAG 作为主要检索方法
- **D-003** "方向"字段必须 schema 层面拆解为多维
- **D-004** 管家不做内容判断
- **D-005** 历史数据必须回标 essence
- **D-006** A 家族（RIO/WTG/TXQ）是最新格式
- **D-007** TGV_1 备注"新爆"是 tier 金标准（删除≠风控）
- **D-008** Schema v1 必须含 audience 层
- **D-009** 词表 v0.2 finalized —— 三级时间分层
- **D-010** target_audience 反映项目+方向的实际策略意图
- **D-011** "借助场景撬动流量" = 场景植入 + traffic 组合
- **D-012** ⭐ 按 intent 分轨训练和优化（核心架构原则）
- **D-013** ⭐ Ingest 阶段 LLM sanity check 机制

### 这个项目的核心哲学

**取上得中，取中得下，取下而不得**。Schema 起点决定了未来六个月所有可能性的上限。

数据库的价值 = 数据量 × 数据分层质量²。分层质量平方贡献，不能将就。

### Session #4 引入的核心原则

**按 intent 分轨**（D-012）是阶段 2 训练的基本架构原则：
- 流量向内容（intent=traffic）走 explosion 预测模型
- 产品向内容（intent=conversion）走 conversion 预测模型
- 不混在一个统一模型里
- API 层面预留两套 endpoint

**Ziao 的洞察**："不同产品不同目的应该需要做不同的匹配或者预测或者优化"——这不是阶段 2 才决定的事，是从 schema 设计第一天就要预留的接口。

**数据质量监控**（D-013）：
- LLM essence 标注的产出（inferred_audience_profile）作为人工标注的交叉验证
- 真实案例: NRT_3 男性自发 4 条爆款里 2 条是女性视角错标
- 这种机制本身就是数据飞轮的一部分——错误样本变成校准信号

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
   - `mappings/NRT_phase3.yaml` (作为方向拆解参考样本)

3. 用一两句话**反向陈述**你理解的：
   - 当前阶段
   - 下一步要做的事 #1 是什么
   - 是否有未决问题需要先讨论

4. 等 Ziao 确认你理解正确后，再开始工作。

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
