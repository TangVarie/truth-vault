# 闸二 · 副题库 · 只数行数 · gate2-reader-2026-10-28

> 题库 `fq-v0.2-cand-reader` sha `9f2cf1c9e7de8a96115559ae1242207e66b20257b41443b2433c5fbf37d79254` (frozen) · 答案 run_tag `fqr-g2-sonnet55` · 模型题 reader_ask_form v1, invites_sharing v2 只认 `llm:claude-sonnet-5-5` · 代码特征 last_para_has_qmark v1 只认 `code:v1`
> 分层快照 (gate2.condition_snapshot): 主题库 `fq-v0.1` sha `ba0f570c47d5…` · run_tag `primary` · llm:claude-sonnet-5-5 · ending_asks_reader v1, asks_for_help v1 (别的抽取器的行不算, 本次快照外 4422 行)
> 名单: `../data-analysis/gate2-reader-holdout-2026-10-27.csv` 1227 篇 sha256 `c761364a9d9d4af4d0920fb36bb20df836150fa3b005236b360d27ba3584fd36` · `../data-analysis/gate2-reader-holdout-wave2-2026-10-28.csv` 18 篇 sha256 `8c434aad5f6d80d216a5bfbd82f4c3e4ff335803b23b829c43b5781d89e92c62`
> 合并名单 1,245 篇 · 名单 sha `32d6f88fefd08d84f12c91f3d805c2d469d855dcb2a8b8f31ba47623dd46ebc4` · note_id 逗号拼接 md5 `de6d85fc98882a6c3ed5083f54a00569` · 半区 holdout (D-129 换了 id、按 old_id 定半区的 18 篇)

## 名单与掉出去的

| 掉出去的原因 (补记 5; 一篇只归第一种) | 篇 | 明细 |
|---|---|---|
| 不在闸二口径里了 (删了 / 标签变了 / 没 essence / 正文 < 50 字) | 0 | — |
| 两道题有一道没有可用答案 (没行, 或 answer 为空但不是正文截断) | 1 | reader_ask_form: NULL (text_too_short) 1 |
| 两道分层题有一道没有答案 | 0 | — |
| **合计** | **1** | 容忍上限 37 篇 (名单 1,245 篇的 3%) |

正文截断记 NULL 的 (不算缺, 也不进分子分母): 0 · 进分析集 1,244 篇

## 覆盖

| 题 | 版本 | 抽取器 | 快照行 | 名单内的行 | 有答案 | NULL (原因) | 名单里没行 | 名单外的行 |
|---|---|---|---|---|---|---|---|---|
| `reader_ask_form` | v1 | llm:claude-sonnet-5-5 | 1245 | 1245 | 1244 | text_too_short 1 | 0 | 0 |
| `invites_sharing` | v2 | llm:claude-sonnet-5-5 | 1245 | 1245 | 1244 | text_too_short 1 | 0 | 0 |
| `last_para_has_qmark` | v1 | code:v1 | 1245 | 1245 | 1245 | 0 | 0 | 0 |
| `ending_asks_reader` | v1 | llm:claude-sonnet-5-5 | — | 1245 | 1245 | — | 0 | — |
| `asks_for_help` | v1 | llm:claude-sonnet-5-5 | — | 1245 | 1245 | — | 0 | — |

副题库 run_tag 下快照外的行 (别的 sha / 抽取器): 0

这一份只数行数和覆盖, 不是闸二的读: 没把答案和标签放在一起算过。
