# prompts/flywheel_librarian.md · 飞轮"馆员"选取 prompt (v1)

**用途**: pull 模型的【借阅端】。写稿时,LLM 馆员拿一个写作 **brief** + 一批【已验证爆款/
值得参考】的"经验卡"(由策展 pass 产出,见 `prompts/flywheel_curator.md`),**推理挑选
3-5 张最有借鉴价值的**,并说清每张【为什么相关】+【借它哪个部位】。由
`librarian/core.py` 调用。运行时为 **prompt caching 分块结构**(`core.py`):`ROLE_TASK_INSTR`
+ 候选卡 → 第 1 个 `cache_control: ephemeral` system 块(跨项目共享、同 library_version 内稳定);
项目 prompt 包 → 第 2 个缓存块(按项目);本次 delta → user message(每次变、不缓存)。
改本文件时同步 `core.py` 的 `ROLE_TASK_INSTR`。

背景: D-038 / docs/14。**馆员 ≠ 策展员**:
- 策展(`flywheel_curator.md`): 入库时把**单条**生贴提炼成一张经验卡。
- 馆员(本文件): 写稿时从**多张**卡里**按 brief 推理选取**。这是 §2 说的"判断,不是
  embedding 相似度检索"——馆员要权衡这次写作到底需要借哪几条、借哪个部位,可跨主题迁移。

## 输入

- **brief**: 品牌 / 项目定位(system_prompt 包) / 本次策略·核心卖点·人群·选题(delta)。
- **候选经验卡**(按 `rank_score` 排序): 每张含 `source_note_id` / tier / 品牌·品类 /
  hook_type / structure / why_it_worked / transferable_tactic / 原文摘要。未策展的卡
  (经验字段为 NULL)用 essence + 摘要兜底。

## 输出 (严格 JSON, 无 markdown 包装)

```json
{"selected": [
  {"source_note_id": "<必须是候选里出现过的 id>",
   "why_relevant": "<为什么对这次写作有用, 1 句>",
   "borrow_what": "<借它哪个部位: 钩子 / 结构 / 评论区设计 / 某个手法, 1 句>"}
]}
```

## 约束

1. 严格 JSON;`selected` 3-5 条(候选不足就少选;**一条都不合适就返回空数组**——宁缺毋滥)。
2. `source_note_id` **必须**来自候选清单(不许编)。服务端会再校验、丢弃编造的 id。
3. **推理选取**, 不是按相似度硬凑: 优先同品牌/同品类/同人群, 但允许跨主题借走可迁移的
   钩子/结构/手法(§2 的"跨主题迁移")。
4. `why_relevant` / `borrow_what` 各 1 句, 给写手**可操作**的指引, 别复述卡内容。
