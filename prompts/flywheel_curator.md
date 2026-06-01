# prompts/flywheel_curator.md · 飞轮经验卡策展 prompt (v1)

**用途**: 把已验证的真实爆款(爆/大爆/参考)提炼成"经验卡"——供 pull 模型的 LLM 馆员
借阅时用的、可【迁移】的写作经验。由 `scripts/curate_flywheel_lessons.py` 调用,产出写入
`truth_vault.flywheel_lesson_annotations`(schema 见 `schemas/notes_v1_4_flywheel_lesson_cards.sql`)。

背景: D-038 / docs/14(通道2 改 pull)。管家(本 pass)入库时把生贴消化成带索引的经验卡,
馆员写稿时按 brief 推理挑选哪几条、借哪个部位。

## ⚠️ 为什么单独一个 prompt(不并进 essence_annotator.md)

- `essence_annotator.md` 是 **Mode A · performance-BLIND**(D-028):标注时**绝不**能看到
  tier / 互动量,防结果信号泄漏污染"盲标"特征。
- 本 prompt **恰恰相反**:它**只处理已知爆款**,任务就是**解释"它为什么爆"**(posthoc /
  success_pattern,对应 D-017 的 explanation 模式)。performance-aware 是本 pass 的前提。
- **正因如此两者必须分文件**:把 performance-aware 的策展塞进 essence_annotator.md 会
  直接破坏 D-028 的盲标隔离。**切勿合并。**(这覆盖 docs/14 §6.4 早期"扩 essence_annotator"
  的措辞——当时没考虑到 D-028 冲突。)

## 输入

- 笔记: 正文片段(策展库视图的 `raw_excerpt`,默认前 600 字)
- 已知上下文(本 pass 可见,因为是已验证爆款): tier、品牌/品类、已标 essence
  (emotional_lever / target_audience)

## 输出 (严格 JSON,无 markdown 包装,4 个 key 都必填非空)

```json
{
  "hook_type": "钩子类型(短语,便于馆员按类型检索): 痛点共鸣 / 反差 / 福利 / 悬念 / 身份认同 / 场景代入 / 信息差 …",
  "structure": "结构骨架(1-2 句): 开场怎么抓 → 正文怎么铺 → 转折/高潮 → CTA → 评论区怎么设计",
  "why_it_worked": "为什么爆(1-2 句): 最核心、且可迁移的那条原因(不是复述内容)",
  "transferable_tactic": "可直接借走的具体手法(1 句): 别的产品/选题也能套用的那一招"
}
```

## 约束

1. 严格 JSON,4 个 key 都必填、都是非空字符串。
2. `why_it_worked` / `transferable_tactic` 必须**可迁移**——写成别的笔记也能借的经验,
   不要只复述这条的内容。
3. 简洁:每个字段 1-2 句,别写小作文(馆员要快速扫读 + 拼进 system prompt)。
4. `hook_type` 用短语,便于馆员按类型检索/迁移。

## 运行时模板

实际 API 调用用的模板在 `scripts/curate_flywheel_lessons.py:CURATOR_PROMPT_TEMPLATE`,
应与本文件保持一致(本文件是 canonical/可读版 + rationale)。改其一时同步另一个。
