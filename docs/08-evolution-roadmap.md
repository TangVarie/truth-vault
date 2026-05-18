# 08 · Truth Vault 四阶段进化路径

## 为什么存在

数据飞轮不是一次性建好的，是分阶段进化的。每个阶段独立有 ROI、独立可交付。这个文档定义四阶段进化路径，让你随时知道当前在哪、下一步通向哪。

---

## 整体路线图

```
   阶段 1            阶段 2            阶段 3            阶段 4
─────────────►   ─────────────►   ─────────────►   ─────────────►
描述性 anchor    判别式分类        语义融合          因果评估

几百条           1k+              5k+              20k+
SQL+LLM 标签     LightGBM          BERT+stacking    CATE 估计
0-3 月           +3-6 月           +9-12 月          +18+ 月

▼               ▼                ▼                ▼
"历史上方向     "这条新内容       "找语义相似       "v7 prompt
三爆款率        预测属于趴帖      的爆款"           ATE +12%"
8%"             置信 0.72"
```

---

## 阶段 1 · 描述性 Anchor

### 目标

让 sanshengliubu / autowriter / 写手平台**第一次能查询历史数据**。给每条新内容提供"历史同方向的统计基线 + 特征对比"作为决策 anchor。

### 数据门槛

- 几百条带 tier 标签的笔记
- 当前已有: ~3,400 条 ✅ **超额完成**

### 关键产出

| 产出 | 文档 |
|---|---|
| 数据库 schema | [02-schema-v1.md](02-schema-v1.md) |
| Mapping 协议 | [03-mapping-protocol.md](03-mapping-protocol.md) |
| Onboarding SOP | [04-onboarding-sop.md](04-onboarding-sop.md) |
| 受控词表 v0.1 | [05-controlled-vocab.md](05-controlled-vocab.md) |
| Essence 标注 | [06-essence-annotation.md](06-essence-annotation.md) |
| Audience 接入 | [07-audience-data.md](07-audience-data.md) |

### 工程组件

| 组件 | 技术栈 | 备注 |
|---|---|---|
| 数据库 | Supabase Postgres | 跟 sanshengliubu 同一个实例 |
| Truth Vault Service | FastAPI | 独立进程 |
| NewAPI 网关 | OneAPI Docker | 统一 LLM 调用 |
| 内部 Web UI | Streamlit | 数据健康面板、anchor 报告浏览 |
| 飞书导入器 | 手动 xlsx 上传 → 自动 lark-oapi | 启动期手动 |
| LLM 标注 worker | Python asyncio + Claude API | 离线批量 |

### 核心 API

```
POST /v1/projects                  # 新项目接入 (onboarding 完成后)
POST /v1/notes/import              # 批量导入飞书表
POST /v1/anchor/query              # 核心：给内容返回 anchor 报告
GET  /v1/health/{project_id}       # 数据健康度
POST /v1/audience/sync             # 同步蒲公英数据
```

### 时间表（2-3 个月）

| Week | 任务 |
|---|---|
| 1 | NewAPI 部署 + Schema SQL 执行 + Standard Schema 落定 |
| 2-3 | FastAPI 服务搭建 + 飞书 import 脚本 + 试点 NUC_1 onboarding |
| 4-5 | 历史 3,400 条数据导入 + raw_extra 入库 |
| 6 | 受控词表 v1.0 finalized |
| 7-8 | Essence 全量回标（3,400 条）+ 抽检 |
| 9 | sanshengliubu / autowriter 接入 anchor API |
| 10 | 蒲公英数据接入 pilot（NUC_1）|
| 11-12 | 内部 Web UI 上线 + 数据健康面板 |

### 验收标准

- [ ] 至少 5 个项目完成 onboarding
- [ ] 3,000+ 条笔记入库且带 essence 标注
- [ ] anchor API 在 sanshengliubu 中接入并跑通
- [ ] anchor API 在 autowriter 中接入并跑通
- [ ] 内部 Web UI 上线，数据健康面板可用

### ROI

- **sanshengliubu** 的 persona simulator 有了历史 anchor，判决质量提升（具体提升幅度待 A/B 测量）
- **autowriter** 的 Claude vs Gemini 二选一有了客观依据
- 客户提案有了"数据支撑的策略说明"
- 后续阶段的基建到位

---

## 阶段 2 · 判别式分类

### 目标

训练一个能预测"这条内容会爆吗"的分类器。从"描述历史" 升级到 "预测未来"。

### 数据门槛

- 1k+ 单项目 / 3k+ 跨项目
- 当前已超过 —— 跨项目 3,400 条
- 但有些品类样本太少（如清森河谷只有 QSHG_1 一期），单项目精度受限

### 算法

**LightGBM 三分类**（趴 / 爆 / 大爆）
- Features 来自 [02-schema-v1.md](02-schema-v1.md) 三层全部
- Focal loss 处理类别不平衡（趴 90% / 爆 10%）
- 项目维度 cross-validation（同项目数据不能同时在 train 和 test）

### 训练管道

- 每周一次 retrain
- 模型版本管理（ml_models 表）
- 新模型 AUC 没超过旧模型不上线

### 新增 API

```
POST /v1/predict/tier       # 给一段内容 → P(爆 / 中 / 趴)
POST /v1/predict/compare    # 给两段内容 → P(A 比 B 好)
                            #   ← autowriter 二选一直接调
```

### 下游接入升级

- **autowriter**: 从 "anchor 报告 + Claude 评委" → "分类器置信度 + Claude 评委"
  - P(A better) > 0.65 → 直接选 A，跳过 Claude（省 token、提速）
  - 模糊地带 → 走 Claude 评委
- **sanshengliubu vibe_critic**: 加入"分类器预测"作为判断 anchor
- **写手平台**: 提交内容时直接给 P(爆 / 中 / 趴) 分布

### 时间（+3-6 月）

阶段 1 完成后再启动。

### 验收

- LightGBM 模型 AUC > 0.75
- 在 5 个不同品类上 cross-validation 一致
- API 接入 autowriter 后 2 周观测：A/B 测试显示推荐准确率提升 > 15%

### 风险

- 类别不平衡（爆款 10%）—— 已用 focal loss 缓解
- 跨品类泛化弱 —— essence 特征是关键
- 时间漂移 —— surface 特征权重设低、定期 retrain

---

## 阶段 3 · 语义融合

### 目标

把 BERT 文本编码和 LightGBM tabular features 融合，让模型同时利用**文本字面信号**和**结构化特征**。

### 数据门槛

- 5k+ 跨项目跨品类

### 算法

**Stacking 架构**:
- 底层 BERT（或 BGE-M3 中文 embedding）编码原始文本 → 768 维向量
- 底层 LightGBM 基于 tabular features → 三分类概率
- 顶层 logistic regression 融合两者 → 最终预测

**新启用 pgvector**:
- notes.content_embedding (vector(1536)) 字段填充
- 支持向量检索 "找语义相似 + 已经爆的笔记"

### 新增 API

```
POST /v1/search/similar_explosions
# 找历史上语义相似且爆了的笔记
# 注意 "且爆了" 的过滤条件 —— 这就是为什么阶段 1 的 RAG 不行
```

### 下游应用 —— 跨产品迁移推荐

终于可以做这件事：

> "我正在做 HXZ 粉饼的新方向，找帆谷历史上 essence + audience 相似但产品不同的爆款，看能不能借鉴策略"

具体实现：
- 用 essence + audience 字段做 cosine similarity
- top-K 跨产品候选
- 用 surface_similarity * 时间惩罚 反向降权（避免抄袭）
- 输出"可借鉴 angle 列表"给写手

### 时间（+9-12 月）

阶段 2 跑稳 3 个月后启动。

### 验收

- Stacking 模型 AUC > 0.80（提升约 5 pp）
- 跨品类预测准确率提升明显（最弱品类 AUC 从 0.65 → 0.72）
- 跨产品迁移 API 上线，写手开始使用

---

## 阶段 4 · 因果评估

### 目标

回答"什么策略真正有用" —— 不是"什么内容相关于爆款"，而是"做了 X 是否导致了爆款率提升"。

### 数据门槛

- 20k+ 数据 + 带 prompt 元数据（每条笔记标注是哪个 prompt 版本生成的）

### 算法

**CATE 估计**（条件平均处理效应）:
- Dragonnet / TARNet / Causal Forest
- 控制混淆变量（方向、产品、KOL 等级、时段）
- 输出某次 prompt 升级的 ATE 数字

### 新增表

```sql
CREATE TABLE prompts (
    prompt_id TEXT PRIMARY KEY,
    project_id TEXT,
    version TEXT,
    content TEXT,           -- prompt 全文
    created_at TIMESTAMP
);

CREATE TABLE experiments (
    experiment_id TEXT PRIMARY KEY,
    prompt_a TEXT,
    prompt_b TEXT,
    ate FLOAT,
    p_value FLOAT,
    sample_size INT,
    ...
);
```

### 下游应用

主要服务**客户提案和内部 QBR**：

- 客户问 "为什么你们方法论比 XX 公司贵" → 给 ATE 数字
- 客户问 "换素材有用吗" → 给某次 prompt 升级的 ATE
- 内部 QBR 用因果证据看哪条策略真 work、哪条只是相关
- pricing 谈判: "我们的 v7 prompt 相比行业基准 ATE +12%"

### 时间（+18+ 月）

阶段 3 跑稳后启动。这是研究型工作，需要 ML 工程师。

### 验收

- 因果模型在已知 A/B 实验上验证（事先知道 ATE 的实验）
- 客户提案中开始使用 ATE 数字
- 至少 5 次 prompt 升级有量化因果评估

---

## 阶段 5（远期愿景）· 生成式校准

### 目标

把累积的判别式模型反过来训练生成式模型 —— 让 autowriter 生成时**直接对齐高爆款概率特征分布**，而不是事后筛选。

### 算法

- RLHF 风格（用判别式模型作为 reward model）
- 微调 autowriter 用的基础模型

### 时间（24+ 月）

不在当前路线图。先走完前 4 阶段，看竞争压力和客户需求再决定。

---

## 跨阶段的几个关键原则

### 1. 阶段独立 ROI

每个阶段不依赖后续阶段就有交付价值。阶段 1 自己就是 anchor 系统，不需要阶段 2 上线就有用。

### 2. 基础设施投资 > 功能堆叠

- Schema 阶段 1 就要按阶段 4 的需求设计（D-001, D-008）
- 数据治理纪律不放松
- 取上得中

### 3. 不要为了模型而模型

阶段 2-4 的存在前提是：阶段 1 数据飞轮**已经转起来了**。如果阶段 1 数据回收 SLA 没立住、字段对齐没解决，阶段 2 模型再准也是空中楼阁。

### 4. 人和工程的分工

每个阶段都有"人的部分"和"工程的部分"。人的部分（onboarding、词表 review、tier 标注质量审查）永远是瓶颈，工程优化解决不了。

---

## 各阶段所需人力

| 阶段 | 工程师人月 | 关键人 |
|---|---|---|
| 1 | 1 backend × 2 月 | Ziao + 周哥（策略） |
| 2 | 1 ML × 2 月 | Ziao（监督） |
| 3 | 1 ML × 3-4 月 | 需要懂 BERT/stacking 的工程师 |
| 4 | 1 ML 研究型 × 6 月 | 需要懂因果推断的人 |

阶段 1-2 用常规工程师；阶段 3-4 需要 ML 工程师。这是为什么建议**先稳定跑一年阶段 1+2，再决定是否走 3-4**。

---

## 当前进度

- [x] 阶段 0 · 设计 —— 文档奠基完成
- [ ] **阶段 1 · 描述性 anchor** —— 待启动（等待 [CURRENT_STATE.md](../CURRENT_STATE.md) 任务 #1-4 完成）
- [ ] 阶段 2 · 判别式分类
- [ ] 阶段 3 · 语义融合
- [ ] 阶段 4 · 因果评估
