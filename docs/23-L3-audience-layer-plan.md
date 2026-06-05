# 23 · L3 受众层落地方案(2026-06-05 摸底)

> **目的**:把"设计齐全、代码空"的 L3 受众层(`audience_inferred = 0`)从图纸变成能跑的东西。
> 本文 = **现状实查 + 与 [docs/07](07-audience-data.md) 设计的差距 + 分阶段落地方案(按"现在能不能跑"排序)**。
>
> 配套:受众设计 [docs/07](07-audience-data.md) · 决策 [D-008](../DECISIONS.md#d-008)(必须有 audience 层)/
> [D-013](../DECISIONS.md#d-013)(target vs inferred 不符打 flag) · 当前状态 [docs/22](22-handover-2026-06-05-onboarding-hardened.md)。

---

## 1. 现状实查(2026-06-05,prod)

| 字段 | 有值数 / 2478 | 说明 |
|---|---|---|
| `target_audience`(人工,飞书方向) | **1532** | onboarding 拆方向时定的策略意图 |
| `inferred_audience_profile`(LLM 推断) | **1042** | ⭐ **essence pass 顺带产出的**(`write_essence_back` 写 `audience`);demographic 闭集 + psychographic 自由文本 + confidence,**满的、质量不错** |
| `audience_inferred_at`(L3 标记) | **0** | ⚠️ 推断是 essence 的"副产品",**从没被当成一等 L3 工件追踪** |
| `actual_audience_data`(真实) | 245(其中**仅 ~26-130 有真实年龄/性别分布**) | ⚠️ **关键约束**:这 245 是从飞书「观众分析」列解析的,**大部分是 `性别分布：无;年龄分布：无`(只有阅读时长)** —— 真实蒲公英 age/gender/city **基本没拉进来** |
| `audience_calibrations` 表 | **存在但空** | schema 早建好(`notes_v1_2.sql:532`),没代码填 |

**一句话现状**:**推断这一半已经在跑(1042 条满 profile);真实数据这一半基本是空的(观众分析列大多「无」)。** 所以"L3 落地"不是从零写推断,而是:① 把已有推断**用起来**(对照人工标 / 当一等工件追踪);② **去把真实蒲公英数据真的拉进来**,校准闭环才有料。

---

## 2. 与 docs/07 设计的差距

docs/07 设计的完整 L3 = **推断 + 真实数据接入 + 校准闭环 + 不符 flag + 准确率监控**。逐项对差距:

| docs/07 设计 | 现状 | 缺口 |
|---|---|---|
| LLM 推断 `inferred_audience_profile` | ✅ 已有(essence 副产品,1042) | 缺"一等工件"追踪(`audience_inferred_at`)+ 可选独立 pass |
| 蒲公英真实数据接入 | ⚠️ 部分(观众分析解析,但大多「无」)| **真实 age/gender/city 没拉进来**(ops/数据缺口,docs/07 任务#4 账号清单) |
| 校准闭环(inferred vs actual) | ❌ 表空、无代码 | 整段缺;**且被上面的数据缺口卡住**(没真实分布就没法校准) |
| D-013 不符 flag(target vs inferred) | ❌ 无 | 整段缺;**但不依赖真实数据,现在就能跑** |
| 准确率监控(按品类) | ❌ 无 | 缺(依赖校准闭环出数) |

---

## 3. 落地方案(按"现在能不能跑"分阶段)

### Phase 1 · 受众不符检测(D-013)—— 现在就能跑、纯代码、立刻有数据质量价值 ⭐

**为什么先做**:**不需要真实蒲公英数据**(只比 人工 `target_audience` vs LLM `inferred_audience_profile`),**688 条**现在就有这两者。直接兑现 L3 最实在的效果——**抓人工标错的受众**(D-013 真实案例:NRT_3「男性自发」爆款里实为女性视角)。

**做什么**:
- 新脚本 `scripts/audience_disagreement_flag.py`:扫 `target_audience` ∩ `inferred_audience_profile` 都有的笔记,比对关键维度(gender_skew 是否冲突、age_band 是否 overlap),把不符写进 `notes.data_quality_flags`(如 `{"audience_disagreement": {"level":"high|medium", "target":..., "inferred":...}}`),不覆盖 essence。
- 一个视图 `v_audience_disagreement_review`:high/medium flag 的笔记 + 摘要,给运营复审。
- 顺带:**把 `audience_inferred_at` 补上**(凡 `inferred_audience_profile` 非空、且本轮跑过比对 → 写时间戳),让 L3 从"essence 副产品"升级成被追踪的一等层(`audience_inferred` 从 0 起来)。

**验收**:跑完出"X 条 high / Y 条 medium 不符",抽查几条确认确实是人工标偏了(而非 LLM 错)。**纯代码,1 天内可出。**

### Phase 2 · 把真实蒲公英数据真的拉进来 —— ops + 数据(校准闭环的前提)

**为什么是瓶颈**:观众分析列大多「无」→ 校准没料。要么(a)运营在蒲公英后台**真导出** age/gender/city 回填飞书「观众分析」列(走现有 `parse_audience_analysis` 解析路径),要么(b)单独的 CSV 上传/中转。

**做什么**(docs/07 方式 A/C):
- 先做 **docs/07 任务 #4 账号清单**:哪些项目/账号有蒲公英权限、能拉哪些字段(先挑最完整的项目,如 NRT/NUC)。
- 选一条回填路径:飞书「观众分析」列填真实分布(最省,复用现有解析)或 `/upload-pugongying` CSV。
- **验证**:回填后 `actual_audience_data` 里 `性别分布/年龄分布` 不再是「无」,`has_distribution_keys` 涨上来。

**注**:这步主要是**运营/数据动作**,不是写代码。没有它,Phase 3 校准跑了也是空。

### Phase 3 · 校准闭环 + 准确率监控 —— 代码现成可写,价值随 Phase 2 数据解锁

**做什么**(docs/07 §校准闭环算法已写好):
- 新脚本 `scripts/calibrate_audience.py`:对 `inferred + actual(有真实分布)` 都有的笔记,跑 age/gender/city 的 majority 归类对比 → 写 `audience_calibrations` 表(表已存在)。
- 视图 `v_audience_inference_accuracy`:按品类算 age/gender/city 推断准确率(docs/07 目标:age≥70% / gender≥85% / city≥60%)。
- 低于阈值的品类 → 反馈去优化推断 prompt / 重标。

**验收**:出"LLM 受众推断准确率 = age _% / gender _% / city _%,哪些品类差"。**先在现有 ~26-130 条有真实分布的笔记上跑一版**(量小但能验证管道 + 给个初步信号),Phase 2 补数据后准确率才有统计意义。

### Phase 4 · 下游价值兑现(喂飞轮 + L2)

- **独立 L3 推断 pass**(可选升级):现在推断是 essence 副产品(已 Mode A、performance-blind,符合 D-017,够用)。若要更高质量,用 `prompts/audience_inferrer.md` 起独立 pass、保持 label-leakage 隔离。
- **受众感知的馆员检索**:馆员 borrow 经验卡从 `platform+category` 升级到**按受众画像匹配**("对 30-39 形象焦虑女性有效的爆款经验")—— 跨产品迁移的真正精准化。
- **喂 L2**:`受众 × essence` 交互特征(`30-39 女性 + 焦虑撬动 + 情感叙事 = 高爆概率`)是 L2 预测的关键输入。

---

## 4. 不变量 / 注意

1. **label leakage(D-017/D-028)**:受众推断**不能看 performance**(tier/互动量)。现状推断走 essence Mode A(performance-blind),已合规;独立 L3 pass 若做,必须保持同样隔离。
2. **真实数据隔离**:`actual_audience_data` 按 project_id + RLS 隔离;跨客户聚合是阶段 3+,现在不做(docs/07 §合规)。
3. **校准只能校 age/gender/city 三项**(蒲公英只给这三);psychographic(pain/aspiration/value)只能靠 LLM、无真实对照(docs/07 §字段对齐)。
4. **不强制 LLM 覆盖人工**:不符只 flag、人工做最终判断(D-013 Rejected)。

---

## 5. 优先级建议

| Phase | 性质 | 依赖 | 价值 | 建议 |
|---|---|---|---|---|
| **1 · 不符 flag** | 纯代码 | 无(688 条现成) | 数据质量护栏,立刻 | **先做** |
| 2 · 拉真实数据 | ops/数据 | 蒲公英权限 | 解锁校准 | 并行推进(运营) |
| 3 · 校准闭环 | 代码 | Phase 2 数据 | 推断准确率体检 | 代码可先写,数据到了出数 |
| 4 · 下游(馆员/L2) | 代码+设计 | 1-3 | 跨产品精准迁移 + L2 输入 | 路线图后段 |

**核心判断**:**Phase 1 现在就做(便宜、立刻有质量价值、把 `audience_inferred` 从 0 拉起来);Phase 3 的校准闭环价值真正取决于 Phase 2 能不能把真实蒲公英数据拉进来 —— 这是个 ops 瓶颈,不是代码瓶颈。** 别一上来写校准代码却发现没数据可校。

---

_本方案摸底于 2026-06-05。落地从 Phase 1(受众不符检测,纯代码、688 条可跑)起步;校准闭环的前提是先把真实蒲公英 age/gender/city 拉进来(Phase 2,ops)。_
