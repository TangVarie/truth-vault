# G-11 · 结构题层级与半衰期复评（2026-10-12）

复评结论：保留既有 surface 分类与暂定30个月半衰期；本轮证据不足以把18道结构题整体提升到 essence、增设结构档或把30个月称为估计值。只评估层级建议，不改冻结题库、方向、摘要或下发范围。

来源：D-107 / gate2-20261010；冻结题库摘要 `ba0f570c47d594ca4dad571c5a9f5d06da51861b041ba364c3a915220b985ddd`；单项报告与55行账本产物（`feature-gate2-gate2-20261010.md` / `.rows.json`）。组合未过L2，不妨碍单项复评，但不能拿单项通过解释组合已过。

18道 surface 题中：asks_for_help / ending_asks_reader 有正向 validated 信号；efficacy_promise 为负向 validated，但永不下发。turning_point 与预设方向相反（reversed）；其余7道 no_signal、7道闸一未过（unreliable）。同一题的多种取值不能当成多道独立题。

| 题 | 层级 / 暂定月数 | 本轮取值与状态 | 大项目同向 / 有支持 |
|---|---|---|---|
| `title_is_question` | surface / 30 | 是=no_signal | 是: 4/5 |
| `opening_type` | surface / 30 | 具体事件=unreliable；身份自述=unreliable；观点断言=unreliable；提问=unreliable；数据事实=unreliable；感叹情绪=unreliable；其他=unreliable | 具体事件: 3/5；身份自述: 3/5；观点断言: 1/5；提问: 2/5；数据事实: 2/5；感叹情绪: 2/4；其他: 3/4 |
| `has_specific_time` | surface / 30 | 是=unreliable | 是: 1/5 |
| `has_specific_place` | surface / 30 | 是=unreliable | 是: 2/5 |
| `has_direct_quote` | surface / 30 | 是=no_signal | 是: 3/5 |
| `has_body_sensation` | surface / 30 | 是=unreliable | 是: 4/5 |
| `ending_asks_reader` | surface / 30 | 是=validated | 是: 4/5 |
| `invites_sharing` | surface / 30 | 是=unreliable | 是: 3/5 |
| `asks_for_help` | surface / 30 | 是=validated | 是: 5/5 |
| `withholds_product_name` | surface / 30 | 是=no_signal | 是: 4/4 |
| `divisive_claim` | surface / 30 | 是=unreliable | 是: 3/5 |
| `product_role` | surface / 30 | 主角=unreliable；解决方案=unreliable；顺带一提=unreliable；只暗示=unreliable；未出现=unreliable | 主角: 5/5；解决方案: 5/5；顺带一提: 2/5；只暗示: 3/4；未出现: 5/5 |
| `efficacy_promise` | surface / 30 | 是=validated | 是: 4/5 |
| `narrator_identity` | surface / 30 | 是=no_signal | 是: 1/5 |
| `own_experience` | surface / 30 | 是=no_signal | 是: 4/5 |
| `comparison_group` | surface / 30 | 是=no_signal | 是: 2/5 |
| `calls_out_reader_group` | surface / 30 | 是=no_signal | 是: 3/5 |
| `turning_point` | surface / 30 | 是=reversed | 是: 4/5 |

**跨项目稳定性与时间稳定性分开解释。** 结构题只有3/18道包含 validated 取值，另外多道方向跨项目不稳或抽取本身不可靠，不支持统一提高层级。即使5/5项目同向，也只是当期横截面可迁移，不能从中推算时间衰减。judged_by_others / negative_outcome_happened 的 essence/60仍来自语义层原则，分别 no_signal / unreliable，本轮不以显著性改写这两题的语义层级。

**30个月目前没有时间估计。** 本次闸二没有按月份重复观测同一特征的效应，没有足够跨期窗口、置信区间或控制项目/账号/品类漂移的衰减拟合。不能根据截面OR或项目同向比例给出新的半衰期数字。

下一次季度闸二：保持题库/标签口径，预注册按发布时间划分的时间窗口与最低支持量；先检查每窗标签覆盖和抽取可靠性，再对通过项报告项目控制后的效应与置信区间。累积跨期窗口后才拟合衰减率/半衰期；样本不足时明确记“不可估计”。当前30个月仅继续作为检索权重的既有工程先验。若以后改层级/半衰期元数据，需重新冻结摘要、记决策、同步vendor，避免当前题库摘要失配。

G-11的本轮工程复评完成；时间实证与调整仍需未来数据，不另造“已经验证30个月”的结论。
