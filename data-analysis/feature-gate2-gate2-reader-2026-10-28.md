# 闸二 · 副题库 fq-v0.2-cand-reader · gate2-reader-2026-10-28

<!-- gate2-secondary bank_sha256=9f2cf1c9e7de8a96115559ae1242207e66b20257b41443b2433c5fbf37d79254 combined_manifest_sha256=32d6f88fefd08d84f12c91f3d805c2d469d855dcb2a8b8f31ba47623dd46ebc4 void=0 -->

> 题库 `fq-v0.2-cand-reader` sha `9f2cf1c9e7de8a96115559ae1242207e66b20257b41443b2433c5fbf37d79254` (frozen) · 答案 run_tag `fqr-g2-sonnet55` · 模型题 reader_ask_form v1, invites_sharing v2 只认 `llm:claude-sonnet-5-5` · 代码特征 last_para_has_qmark v1 只认 `code:v1`
> 分层快照 (gate2.condition_snapshot): 主题库 `fq-v0.1` sha `ba0f570c47d5…` · run_tag `primary` · llm:claude-sonnet-5-5 · ending_asks_reader v1, asks_for_help v1 (别的抽取器的行不算, 本次快照外 4422 行)
> 名单: `../data-analysis/gate2-reader-holdout-2026-10-27.csv` 1227 篇 sha256 `c761364a9d9d4af4d0920fb36bb20df836150fa3b005236b360d27ba3584fd36` · `../data-analysis/gate2-reader-holdout-wave2-2026-10-28.csv` 18 篇 sha256 `8c434aad5f6d80d216a5bfbd82f4c3e4ff335803b23b829c43b5781d89e92c62`
> 合并名单 1,245 篇 · 名单 sha `32d6f88fefd08d84f12c91f3d805c2d469d855dcb2a8b8f31ba47623dd46ebc4` · note_id 逗号拼接 md5 `de6d85fc98882a6c3ed5083f54a00569` · 半区 holdout (D-129 换了 id、按 old_id 定半区的 18 篇)
> 分析集 1,244 篇 (正例 139) · 大项目 (名单里、口径内爆 ≥ 20): NRT_phase2 23, NRT_phase3 23, NUC_phase1 42
> 判据: 确认族两行 BH q ≤ 0.1 · 支持 ≥ 30 · 有支持的大项目 ≥ 3、最多 1 个反向 (合并 2×2 +0.5) · 账号先验再分层后 OR 变化 ≤ 30% · MH 的层 = 项目 × ending_asks_reader × asks_for_help
> 账号先验档 (分析集): 无记录 626 · 低于基线 331 · 不低于 287 · 标签和名单写死时不同的 0 篇 (按现在的算) · 项目变了的 0 篇 (按现在的项目分层, 补记 4)

## 结论

**没有发现: 两行都没过 (reader_ask_form=挑一个+说自己的 reversed, invites_sharing=是 no_signal)。 C2 读出「样本不够」或不显著: invites_sharing 模型偏宽 (闸一 A 判「是」23 篇里 9 篇参考是「否」), 「是」组里混着约四成参考的「否」, 效应往 1 拉 (D-128 闸一结论第 2 点)。**

## 确认族 (BH 只在这两行里做)

| 行 | 预注册 | 状态 | OR | 95% CI | p | q | 大项目同向/有支持 | 大项目分层内方向 (只报告) | 支持 / 基数 | 先验分层 OR | 只按项目 OR | 不分层 OR | 说明 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `reader_ask_form` 挑一个+说自己的 | + | **reversed** | 0.53 | 0.30–0.95 | 0.033 | 0.065 | 2/3 | NRT_phase2 -, NRT_phase3 -, NUC_phase1 - | 149 / 536 | 0.55 | 0.49 | 0.69 | 显著但与预注册方向 + 相反 · OR 0.53 [0.30, 0.95] · q=0.065 · 大项目 2/3 同向, 支持 149 篇 |
| `invites_sharing` 是 | + | **no_signal** | 0.57 | 0.29–1.12 | 0.101 | 0.101 | 2/3 | NRT_phase2 -, NRT_phase3 +, NUC_phase1 - | 108 / 1244 | 0.55 | 0.75 | 1.55 | 95% 区间跨 1 · OR 0.57 [0.29, 1.12] · q=0.101 · 大项目 2/3 同向, 支持 108 篇 |

## 只报告 (不判状态、不进 BH、不下发)

| 题 | 取值 | 比较基数 | 预注册 | OR | 95% CI | p | 支持 / 基数 | 大项目 >1/<1 (合并 2×2) | 大项目分层内方向 | 只按项目 OR | 不分层 OR |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `reader_ask_form` | 挑一个 | 其余提问类型 (剔掉 contrast_base_excludes) | + | 0.80 | 0.33–1.95 | 0.620 | 47 / 536 | 1/2 of 3 | NRT_phase2 ?, NRT_phase3 -, NUC_phase1 - | 0.95 | 0.89 |
| `reader_ask_form` | 说自己的 | 其余提问类型 (剔掉 contrast_base_excludes) | + | 0.45 | 0.22–0.93 | 0.031 | 102 / 536 | 1/2 of 3 | NRT_phase2 -, NRT_phase3 -, NUC_phase1 - | 0.40 | 0.64 |
| `reader_ask_form` | 求推荐 | 其余提问类型 (剔掉 contrast_base_excludes) | ? | 1.01 | 0.47–2.17 | 0.980 | 107 / 536 | 1/1 of 2 | NRT_phase3 +, NUC_phase1 - | 0.98 | 0.66 |
| `reader_ask_form` | 找同类 | 其余提问类型 (剔掉 contrast_base_excludes) | ? | 1.61 | 0.46–5.60 | 0.455 | 22 / 536 | 3/0 of 3 | NRT_phase2 +, NRT_phase3 ?, NUC_phase1 ? | 1.73 | 1.30 |
| `reader_ask_form` | 求解答 | 其余提问类型 (剔掉 contrast_base_excludes) | - | 1.55 | 0.93–2.56 | 0.091 | 258 / 536 | 2/1 of 3 | NRT_phase2 +, NRT_phase3 +, NUC_phase1 + | 1.64 | 1.63 |
| `reader_ask_form` | 没问读者 | 全部 (阳性对照) | - | 0.47 | 0.19–1.16 | 0.101 | 708 / 1244 | 1/2 of 3 | NRT_phase2 -, NRT_phase3 ?, NUC_phase1 + | 0.40 | 0.25 |
| `last_para_has_qmark` | 是 | 全部 | ? | 1.00 | 0.51–1.93 | 0.994 | 462 / 1244 | 2/1 of 3 | NRT_phase2 +, NRT_phase3 +, NUC_phase1 - | 1.56 | 2.74 |

「只按项目」= 不分 ending_asks_reader / asks_for_help 的层 (主题库的分法); 「不分层」= 全部并成一张 2×2。两者和上面分层的 OR 差得多时, 是分层题在混杂 (辛普森那种), 以分层的为准。

## 敏感性重跑 (只报告): 剔掉记过置顶 / 控评 / 铺评 / 投流的 98 篇, 再加一层 body_len_bucket

剔的依据: `notes.data_quality_flags.comment_maintained_routes` 非空 (铺评工单 / 起量后干预 / 铺评未跨线)、`data_quality_flags.paid_promoted = true`、`notes.pinned_comment` 非空。命中: 投流 7, 维护:起量后干预 10, 维护:铺评工单 17, 维护:铺评未跨线 2, 置顶 65

| 行 | OR | 95% CI | p | 支持 / 基数 |
|---|---|---|---|---|
| `reader_ask_form` 挑一个+说自己的 | 0.70 | 0.28–1.75 | 0.447 | 136 / 477 |
| `invites_sharing` 是 | 0.22 | 0.04–1.09 | 0.064 | 95 / 1146 |

## 反证 (占位题, 不在 BH 家族里)

3 道占位题按主题库定义从 note_id 现算, 同一份名单、同样分层。报警 = 支持 ≥ 30 且有支持的大项目 ≥ 3、区间不跨 1、原始 p ≤ 0.0167 (三道合起来 5%)、大项目最多一个反向, 四条同时满足 (补记 2)。

| 占位题 | OR | 95% CI | 原始 p | 支持 | 大项目 >1/<1 (合并 2×2) | 报警 |
|---|---|---|---|---|---|---|
| `placebo_rand_1` | 1.07 | 0.71–1.61 | 0.738 | 606 | 1/2 of 3 | — |
| `placebo_rand_2` | 1.34 | 0.89–2.02 | 0.165 | 663 | 1/2 of 3 | — |
| `placebo_rand_3` | 0.96 | 0.64–1.44 | 0.827 | 631 | 2/1 of 3 | — |

过: 没有一道占位题报警。

## 掉出去的与覆盖

| 掉出去的原因 (补记 5; 一篇只归第一种) | 篇 | 明细 |
|---|---|---|
| 不在闸二口径里了 (删了 / 标签变了 / 没 essence / 正文 < 50 字) | 0 | — |
| 两道题有一道没有可用答案 (没行, 或 answer 为空但不是正文截断) | 1 | reader_ask_form: NULL (text_too_short) 1 |
| 两道分层题有一道没有答案 | 0 | — |
| **合计** | **1** | 容忍上限 37 篇 (名单 1,245 篇的 3%) |

正文截断记 NULL 的 (不算缺, 也不进分子分母): 0 · 进分析集 1,244 篇

| 题 | 版本 | 抽取器 | 快照行 | 名单内的行 | 有答案 | NULL (原因) | 名单里没行 | 名单外的行 |
|---|---|---|---|---|---|---|---|---|
| `reader_ask_form` | v1 | llm:claude-sonnet-5-5 | 1245 | 1245 | 1244 | text_too_short 1 | 0 | 0 |
| `invites_sharing` | v2 | llm:claude-sonnet-5-5 | 1245 | 1245 | 1244 | text_too_short 1 | 0 | 0 |
| `last_para_has_qmark` | v1 | code:v1 | 1245 | 1245 | 1245 | 0 | 0 | 0 |
| `ending_asks_reader` | v1 | llm:claude-sonnet-5-5 | — | 1245 | 1245 | — | 0 | — |
| `asks_for_help` | v1 | llm:claude-sonnet-5-5 | — | 1245 | 1245 | — | 0 | — |

副题库 run_tag 下快照外的行 (别的 sha / 抽取器): 0

## 读的时候要记着的两点 (D-128 闸一结论, 不改判定)

1. reader_ask_form 按 C1 两组看, A 和参考跨组的错判两个方向差不多 (3 对 4); 错判和爆不相关时效应只会往 1 拉, 偏保守。
2. invites_sharing 模型偏宽: 参考「是」16 篇, A 判「是」23 篇, 其中 9 篇参考是「否」 —— C2 的「是」组里混着约四成参考的「否」。

## 不写

- 副题库的结果永远不写 `feature_validation` (D-128): 馆员取全表最新的一次闸二、不分题库, 写进去写作台的规律下发会整体断掉。结论只进这份报告和 DECISIONS。
