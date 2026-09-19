# 28 · 内容特征层（草案）：给每篇笔记问一组能指着原文回答的小问题

> **状态**：草案，供讨论（2026-09-19）。**没改任何代码，没动库。** 附录里的 SQL 只在本地 Postgres 16 上用合成数据跑过（按 CI 顺序套完 v1_2 → v1_12 后迁移连跑两遍、统计口径和 statsmodels 逐位对过），没碰生产。落 PR 时又独立复核了一遍：附录 A 连跑两遍通过；§11 第 5 条的 (a)(b)(c) 用边界行复现。迁移文件定稿前不落 `schemas/`（CI 要求每个 `notes_v1_*.sql` 进首次部署清单）。
>
> **一句话**：给每篇笔记问约 20 道闭集小问题（第一句怎么开头、有没有具体时间、结尾有没有问读者……），答案当 Layer 1 的事实存下来。只有过了三道闸（测得准 / 有区分度 / 对新笔记也成立）的特征，才进 L2 打分、经验卡和写作台。
>
> **配套**：决策草案 D-065 · 问题库 [`prompts/feature_questions_v0_1.yaml`](../prompts/feature_questions_v0_1.yaml) · 依据 [l2-feasibility](../data-analysis/l2-feasibility.md) §2 / §3 / §8 · [signal-definitions](../data-analysis/signal-definitions.md) §〇 / §一 / §八 · [D-004](../DECISIONS.md#d-004) · D-017 / D-028 / D-060 / D-062 / D-063 / D-064 · [R-001 / R-003 / R-007](99-rejected-ideas.md)
>
> **怎么读**：赶时间只读 §0 和 §11。改题看 §4 + 问题库文件。写代码前读 §5、§6 和附录。

---

## 0. 一页读完

- **做什么**：20 道「能指着原文回答」的是非题 / 选择题，加 8 个代码直接算的特征、3 个占位题，对全库 5,949 篇笔记（以后也对写作台草稿）各问一遍。答案存事实层，不做判断。D-004 给管家定的工具集里本来就有 `extract_features`，这是把它补上。
- **为什么**：
  ① 内容里有信号（负面撬动在 NUC、NRT_2 项目内爆率是其他的 4–6 倍），但现在四个 essence 标签的留一项目 AUC 停在 0.635，正文字符特征更低（0.606）；l2-feasibility §8.5 自己的结论就是下一步该让 LLM 抽「发布前可得的结构化特征」。
  ② D-062 之后判爆只看评论数，词表里却没有一个字段描述「这篇怎么让人想评论」。
  ③ 经验卡只从爆款里提炼，从没和趴贴对照过。
  ④ 写作台需要能照做、能检查的话。
- **能指望什么**：排雷更准（最差那一档判得更准）；经验卡上的规律有「爆 vs 趴」的对照证据；写作台拿到能照做、能核对的指令；结案报告有数据版的爆款公式。**不能指望选爆**——决定爆没爆的一大块不在文字里（R-001），投流历史上也没记。
- **三道闸**：闸一·测得准（重测、人工核、证据片段硬闸）→ 闸二·有区分度（判据先写死，项目内比较，有反证）→ 闸三·对冻结日之后的新笔记也成立。**没过闸的特征只留在事实层，不进 L2、不进写作台。**
- **前置**：写作台要真的在借书（D-063 复核时 30 天 82 个 batch、713 个版本，馆员只收到 8 个 brief）；标题要拿得到（下面第 4 件）。
- **成本**：全库一遍约 4,300 万输入 token、300 万输出 token；便宜档模型几百元量级，Sonnet 档一两千元量级（以网关实价为准）。夜跑只跑增量。
- **写的过程中查出来的五件事**（前三件和特征层无关，现在就能动）：
  1. 书架准入没挡「铺评工单」爆贴。途鸽 45 条爆贴里 33 条靠铺评过线，互动中位 7，可能正在书架上当经验卡教写作台。修法一行（§7.2）。
  2. l2 正例口径有漏洞：`raw_extra` 或 `tier_source` 为 NULL 的干净爆款会被静默排除；l2-feasibility §8.6 的 SQL 比 signal-definitions §八 少了 synthetic 闸，「伪500评」这类行会被当成正例。三处本地都已复现，附了生产影响查询（§11 第 5 条）。
  3. 「砍掉最低 20% 只丢 10% 爆款」那张分档表是 9/15 在清洗前的标签上算的。当闸三基线之前要先用清洗后的口径重算（§6.3）。
  4. 大部分表拿不到标题：`title` 列基本是空的，各表文案结构不一样，要逐表登记切法；登记之前标题类题一律记空，不猜（§3 第 4 条、§11 第 2 条）。
  5. 馆员缓存：加「已验证规律」缓存块时，`library_version()` 必须并入闸二的轮次，否则规律更新了缓存也不会失效（§7.1）。
- **要讨论、要拍板的 10 件事**：§11。

---

## 1. 为什么现在做

### 1.1 内容里有信号，但现在的四个标签抓得不稳

| 事实 | 数 | 出处 |
|---|---|---|
| 负面撬动 vs 其他，项目内爆率 | NUC 19.9% vs 5.0%（4.0×）；NRT_2 19.0% vs 3.3%（5.8×） | l2-feasibility §2 |
| 留一项目加权 AUC：只用 essence 四个标签 | 0.635 | §8.2（清洗后、中位秩） |
| 只用正文字符二元组 / 两者合并 | 0.606 / 0.610 | §8.2 |
| 按分数砍掉最低 20% | 少发 19.9%，只丢 10.0% 的爆款 | §3（9/15 在清洗前的标签上算的，§6.3 要求重算） |

两件事放一起看：**内容确实有关系，但现有特征只抓到了一部分。** essence 是一次调用同时判 lever、原型、强度、形式、受众，都是整体印象；字符特征学的是字面，跨项目迁移不稳（SPX 上是 0.322）。§8.5 原话的意思是：字符二元组学不到「这是个提问帖」「这是在制造对立」这种结构，真正值得试的是让 LLM 从正文抽发布前可得的结构化特征，再进同一套验证。本文就是那个实验的设计。

### 1.2 判爆看评论数，特征里却没有「评论机制」

D-062 之后：爆 = 评论数 ≥ 50，大爆 ≥ 100，全项目统一。可受控词表 v0.2 描述的是情绪和原型，只有 `content_format = 提问求助` 一个值沾到「让人留言」。结尾有没有直接问读者、有没有请读者讲自己的经历、有没有故意不说产品名让人来问、有没有抛出会引起分歧的判断，这些都没有字段。**标签量的是评论，特征里没有评论机制，这是最直接的缺口。**

### 1.3 经验卡只看赢家

- 策展 pass 只处理已验证的爆款（`prompts/flywheel_curator.md`），`why_it_worked` 是对赢家的事后解释。被写成「为什么爆」的手法，完全可能在趴贴里一样常见，**现在没有任何机制去查。**
- 书架排序 `rank_score` 里有一项 `COALESCE(personal_bao_rate, 0.3) × 0.3`（最新定义在 `notes_v1_10`）。`personal_bao_rate` 来自 `v_top_performing_accounts`：该账号所有 tier 非空笔记里爆 / 大爆的比例，**包含这张卡自己，用的是未清洗的 tier**；发帖不足 5 篇的账号取默认 0.3。于是「账号本来就容易爆」的卡排在前面——而那恰恰是内容功劳最说不清的卡。

特征跑在全部笔记（爆和趴都有）之后，这两件事都能被检验：卡上的手法在趴贴里多不多；这条爆款比它账号的基线多爆了多少。

### 1.4 写作台需要能照做、能检查的话

「第一句写一件已经发生的具体事，带上时间或人物」，写作台能照做，TV 也能查它做没做到；「使用恐惧撬动」两样都难。R-007 允许模型层给「置信度 + 特征对比」，不允许给改写建议（改写永远是生成层和评判层的事）——**原子特征正好就是「特征对比」要用的语言。**

### 1.5 位置早就留好了

- D-004：管家的工具集是 `query_db` + `compute_stats` + `extract_features`，并写明特征抽取用 LLM、但锁在闭集标签上。
- `notes_v1_2.sql` §12 建了 `truth_vault.note_features`（`title_len` / `body_len` / `opener_type` / `has_specific_scene` / `has_dialogue` / `ai_smell_score` 等），标着「阶段 1 末期启用」。**仓库里没有任何脚本写它。**

所以这不是新方向，是一个一直空着的位置。

---

## 2. 它是什么、不是什么

### 2.1 定位

- **是**：Layer 1 的事实标注。每道题都能指着原文回答，闭集，Mode A 盲标（D-017 / D-028：不看任何表现数据）。
- **不是**：不回答「好不好 / 会不会爆」（那是 Layer 2，而且要过闸）；不给改写建议（R-007）；不替代 essence；不读评论、控评、铺评、投流（signal-definitions §一：干预类信号多数是后验泄漏）。
- **打分放哪**：D-004 的管家没有 `score`。打分器是 Layer 2 的独立模块，写自己的表 `content_scores`，不在标注 pass 里。

### 2.2 和 essence 的关系

essence 回答「这篇打动了人的什么」（情绪杠杆、人性原型）；原子特征回答「这篇是怎么写的」（开头、细节、互动设计、产品露出）。两者并存，还能互相核对：

- 词表规定「恐惧 = 具体、已发生、有对象」。`emotional_lever = 恐惧撬动` 的行，`negative_outcome_happened` 或 `judged_by_others` 应该大多为「是」；对不上的比例，就是 essence 在这条边界上的噪声。
- `content_format = 提问求助` 应该和 `asks_for_help = 是` 高度一致。
- `intent = conversion` 应该对上 `product_role ∈ {主角, 解决方案}`。

这些只报告、不当闸（§6.1）。

### 2.3 一个例子（示意，不是库里的笔记）

> 标题：戒烟第 30 天，我终于敢去相亲了
> 正文：上个月相亲，对方坐下两分钟就问我：「你是不是抽烟啊？」我当场脸就红了。回家把烟盒扔了，决定这次来真的。头两周半夜嘴里发苦，靠嚼口香糖熬过去。现在 30 天了，同事说我气色好多了。你们戒烟第几天了？

| 题 | 答 | 证据（原文片段） |
|---|---|---|
| `opening_type` | 具体事件 | 不需要（就是第一句） |
| `has_specific_time` | 是 | 上个月相亲 |
| `has_direct_quote` | 是 | 你是不是抽烟啊 |
| `judged_by_others` | 是 | 对方坐下两分钟就问我 |
| `has_body_sensation` | 是 | 半夜嘴里发苦 |
| `turning_point` | 是 | 回家把烟盒扔了，决定这次来真的 |
| `ending_asks_reader` | 是 | 你们戒烟第几天了？ |
| `narrator_identity` | 否 | — |
| `product_role` | 未出现 | — |

假如将来 `ending_asks_reader = 是` 过了闸二，下游会看到两样东西（x、y 是占位）：

- 经验卡上：「命中已验证规律：结尾直接问读者（5 个大项目 4 个同向，项目内爆率 x% vs y%）」
- 写作台某篇草稿没有这一项时的特征对比：「这稿结尾没有问读者；本项目爆款里 x% 有，趴贴里 y% 有」。只陈述对比，不说「建议改成……」。

### 2.4 能指望什么、不能指望什么

| 能指望 | 不能指望 |
|---|---|
| 最差那一档判得更准（排雷） | 挑中爆款：顶档本来就不单调（l2-feasibility §3） |
| 经验卡上的规律有「爆 vs 趴」的对照证据 | 解释「好内容为什么没爆」：没有投流数据，看不到曝光机会 |
| 写作台拿到能照做、能核对的指令 | 用单个项目的数据学规律：正例太少（l2-feasibility §4①） |
| 结案报告里有数据版的爆款公式 | 对客户报「P(爆)」 |

实话说，AUC 能涨几个点就不错。闸二要做的就是把这个预期证实或推翻。

---

## 3. 前置条件

1. **写作台要真的在借书。** D-063 复核时，30 天里写作台 82 个 batch、713 个版本，馆员只收到 8 个 brief。管子不通，书架上的卡再好，对写作台也是零。验收看夜跑里 `check_librarian_traffic.py` 那盏灯（[docs/27](27-autowriter-librarian-relink-2026-09-17.md)）。特征层管的是「借到的东西好不好」，管子通不通是另一件事，两件事都要做。
2. **标签口径不另起炉灶。** 正负例沿用 l2-feasibility §8.6 的 `d`，落成视图 `truth_vault.v_l2_labels`，作为口径的唯一住处（附录 A）。l2 的 SQL、特征对比、闸三都只读它。这个口径有四处已知问题，处理顺序见 §11 第 5 条。
3. **投流不挡路，但要开始记。** l2-feasibility §8.5 说投流缺失比正文特征更卡脖子，这话对：它卡的是天花板，没有曝光机会的数据，解释不了好内容为什么没爆。但它不挡闸一、闸二。两件事并行：运营从现在开始记三列（维护情况 / 维护时间 / 维护效果），用在 §8；特征层按闸推进。投流是起量后的干预，和控评一样，**永远不当特征**。
4. **标题要拿得到。** `notes.title` 基本是空的（§8.2：13 行），正文都在 `raw_content`。各表结构不一样：TGV 有独立的「笔记标题」列；SPX 是【标题】+【正文】结构；其余表是一整段文案，第一行是不是标题要逐表抽 20 条看。切不出标题的项目，标题类题目（`title_is_question`、`title_len_bucket`、`title_has_digit`、`brand_in_title`）一律记 NULL，不猜。切法建议登记进 mapping（§11 第 2 条）。
5. **写作台版本对照只作辅助。** D-064 之后 404 条笔记对上了写作台版本，但语义是「写作台里对应的版本」，不是「生成来源」（约 208 条 `lag_days < 0`，发布后才补进写作台）。所以写作台侧的效果主要靠闸三的「入库即打分」来验（§7.3）。

---

## 4. 问题库

文件：[`prompts/feature_questions_v0_1.yaml`](../prompts/feature_questions_v0_1.yaml)。下面是摘要，逐题的定义、边界、正反例、预注册方向都在文件里。

### 4.1 出题六条规矩

1. **一题只问一件事**。想问两件就拆开，组合放在代码里。
2. **能指着原文回答**。答「是」必须能从原文抄出一小段做证据。
3. **闭集**。bool 只答 是 / 否；choice 只从选项里选（R-003）。
4. **只用发布前就有的东西**。只看标题和正文（D-017 / D-028）。
5. **边界写清楚**。yes_if / no_if 各给例子；把握不准的情况写进 no_if。
6. **方向先写下来**。每题的 `hypothesis`（+ / − / ?）在闸二跑之前冻结，跑完不许回头改。l2-feasibility §8.3「看完留出结果再剔 SPX」就是判据后定的教训。

### 4.2 题目一览

| 家族 | 题（id） | 为什么放 |
|---|---|---|
| 开头 | `title_is_question`、`opening_type`（具体事件 / 身份自述 / 观点断言 / 提问 / 数据事实 / 感叹情绪 / 其他） | 读者第一眼决定停不停 |
| 具体性 | `has_specific_time`、`has_specific_place`、`has_direct_quote`、`has_body_sensation` | 真实感的来源，写作台最容易照做 |
| 评论诱导 | `ending_asks_reader`、`invites_sharing`、`asks_for_help`、`withholds_product_name`、`divisive_claim` | 判爆口径就是评论数 |
| 身份代入 | `narrator_identity`、`own_experience`、`comparison_group`、`calls_out_reader_group` | 读者能不能对上号；也是客户追问「TA 到底是谁」的证据 |
| 冲突转折 | `turning_point`、`judged_by_others`、`negative_outcome_happened` | 把负面撬动拆成能照着写的场面；能反过来核对 essence |
| 产品露出 | `product_role`（主角 / 解决方案 / 顺带一提 / 只暗示 / 未出现）、`efficacy_promise` | 看爆款是不是拿品牌露出换的；把 intent（只覆盖 2,303 / 5,949 条）补到每一条 |
| 代码算（8 个） | 正文 / 标题字数分档、标题含数字、问号数、表情数、话题数、标题含品牌词、品牌词首次出现位置 | 控制变量 + 粗版对照，不花模型钱 |
| 占位（3 个） | `placebo_rand_1..3`：按 note_id 哈希随机生成 | 反证。它们如果被判显著且稳定，整轮作废 |

两条特殊规定：

- **`efficacy_promise`（效果承诺）的 `aw_instruction` 是 `never`**。它是合规观察项，将来就算和爆款正相关，也绝不下发给写作台。
- **`withholds_product_name`、`divisive_claim` 过了闸也要和 `product_role` 一起看**。标签是评论数，飞轮天然会奖励钓鱼帖和争议帖；有产品露出这一族，才看得出爆款率是不是拿品牌露出换来的。

### 4.3 版本、冻结、分层

- 每题有 `version`，改题干或边界就 +1；旧版本答案保留、不覆盖，**分析时不混用版本**。
- 整个文件有 `bank_version`（`fq-v0.1`）。闸二预注册那天把 `status` 改成 `frozen`、记下文件 sha256；之后改任何一题都要升 `version` 并记 DECISIONS。写作台要用就原样 vendor 本文件并记校验和，不手抄（D-041 对词表的纪律）。
- 三层原则（README 原则 2）：每题声明 `layer`。18 题暂标 `surface`、半衰期 30 个月（同「时代语言范式」档）；`judged_by_others`、`negative_outcome_happened` 标 `essence`、60 个月。**结构类题该放哪一档要 owner 定**（§11 第 3 条）。

### 4.4 和 `note_features` 的分工（建议）

- **数值原值进 `note_features` 的现有列**：`title_len` / `body_len` / `hashtag_count` / `mention_count`。
- **分档值和模型答案都进新长表 `note_feature_answers`**：一题一行、带版本。宽表每改一题就要一次迁移，也没法让两个版本并存对比；长表加题、退题都不动表结构。
- `note_features` 里的 `opener_type` / `title_hook_type` / `has_specific_scene` / `has_dialogue` / `compliance_red_flags` / `ai_smell_score` 六列**不用**，加 COMMENT 标注已被问题库取代，不删。

---

## 5. 抽取 pass

### 5.1 流程

```
notes（或写作台新版本）
   │  代码先切片: 标题 / 正文第一句 / 正文最后一段 / 正文（≤1,500 字）
   ▼
scripts/annotate_feature_pass.py ── Mode A 防泄漏检查（复用 D-028 那两道）
   │  按 call_groups 调用: 一次一组、同组 ≤ 4 题
   │  校验: 答案在闭集里？证据是原文子串？ 不过 → 重问一次 → 仍不过记 NULL + 原因
   ▼
truth_vault.note_feature_answers（Layer 1 事实）
   │
   ├─→ v_feature_contrast → 闸二 → feature_validation（每个特征值的结论）
   └─→ 打分器（Layer 2，独立模块）→ content_scores → 闸三 / 写作台影子打分
```

运行环境同 essence：GitHub 海外 runner 连不上网关，所以 LLM 调用放 Railway worker，加一个端点 `/annotate-features`（和 `/annotate-essence` 同一套鉴权、同一个每脚本互斥锁）。daily-sync 在 essence 那步之后加一步增量；全库回填走手动 workflow（仿 `backfill-essence.yml`）。

### 5.2 防泄漏

照搬 `annotate_essence_pass.build_mode_a_prompt` 的两道检查：模板里不许有表现类占位符（`TEMPLATE_LEAK_PLACEHOLDERS`）；项目上下文里不许出现 tier、曝光、互动这类关键词（`PERFORMANCE_KEYWORDS`）。输入只有切好的几段文字，不给 tier、指标、评论、干预列。CI 守卫断行为不断源码（D-051）。

### 5.3 为什么分组问，以及证据片段这道硬闸

**晕轮效应**：一次让模型答二三十道题，它会先形成「这篇写得好 / 不好」的整体印象，再按印象去答细节。拿这种答案做特征对比，会冒出一堆假相关——看起来很多特征都和爆有关，其实都是同一个整体印象。

所以题目按输入片段和主题分成 6 组（`call_groups`），**一次调用只问一组、同组最多 4 题，不同组绝不合并**。闸一会在 300 篇上比「分组问」和「每题单问」，一致率低于 0.90 的题改成单问。

**证据片段硬闸**：答「是」（choice 题选了实质选项）必须附上原文里的原样片段，不超过 30 字。代码去掉空白后做子串校验，对不上就重问一次，仍对不上记 NULL、`invalid_reason = 'evidence_not_found'`。这一步不靠模型自觉，**专门防「凭印象答是」**，人工抽查时也一眼能核。

**「否」不能来自被截断的片段**（codex review on #134）：`body` / `full` 截到 1,500 字后，题目问的仍是「全文有没有」，模型只看了前缀。特征出现在后面的，会被记成「否」而不是「不知道」，证据校验对假阴性无能为力。所以片段被截断时，scope 为 `body` / `full` 的题答「否」一律记 NULL、`invalid_reason = 'span_truncated'`；答「是」照常（证据在前缀里就成立）。今天这条是防御：生产 6,163 篇正文最长 1,013 字，没有一篇会被截，但写作台草稿和以后的表不保证。

### 5.4 模型看到的是什么（骨架）

```
你在给一条小红书笔记做事实标注。只回答下面几道题，每题只看题目指定的那一段。
不要评价这条笔记好不好，也不要猜它的数据表现。

【正文】{body}

1. has_specific_time · 看【正文】· 正文里有没有具体的时间点或时长？
   算「是」：能定位到某一天、某一时刻，或给出一段具体时长。例：上周三 / 凌晨两点 / 戒烟第 17 天
   算「否」：只有模糊时间。例：以前 / 最近 / 很久了
2. ……（同组其余题）

只输出 JSON：
{"answers":[{"id":"has_specific_time","answer":"是","evidence":"戒烟第17天"}, ...]}
答「是」时 evidence 必须从指定那一段原样抄，不超过 30 字；答「否」时留空。
```

- 只放本组题目用得到的那几段，不把四段都塞进去。无关的内容越多，答得越不准。
- 指令和题目放 system 块走 prompt caching（同 essence 的做法），每条笔记只有正文那部分不缓存。

### 5.5 存储（DDL 见附录 A）

| 对象 | 层 | 管什么 |
|---|---|---|
| `note_feature_answers` | Layer 1 | 每篇 × 每题 × 版本 × 抽取器 × 轮次一行。`subject_type` 区分笔记和写作台版本；`run_tag = 'primary'` 才进分析，`retest-*` / `gate1-*` 只给闸一 |
| `feature_validation` | 闸二产物 | 每个特征值一行：状态、合并优势比、置信区间、BH 校正后的 q 值、大项目同向个数、一句人话 summary |
| `content_scores` | Layer 2 | 冻结打分器给笔记 / 草稿的分数和项目内分位；`shadow` 标记影子期 |
| `v_l2_labels` | 口径 | 正负例的唯一住处 |
| `v_feature_contrast` | 闸二输入 | 每个项目 × 每个特征值的 2×2 计数 |

不建跨 schema 外键（同 D-064，`subject_id` 可能指写作台版本），悬空检查加进 `scripts/verify_supabase_state.sql`。

### 5.6 成本

全库 5,949 篇、6 组、每组一次调用：输入约 **4,300 万 token**，输出约 **300 万 token**（假设：指令约 450 token、正文约 420 token、每组题目约 320 token、每次输出约 90 token；未算缓存）。全部改成每题单问，输入约 1.17 亿 token。按便宜档模型大约几百元，Sonnet 档一两千元，以网关实价为准。夜跑只跑增量，可以忽略。

### 5.7 用哪个模型：这一期用普通大模型，Jev 留作可替换的抽取器

Jev 是 TypeSafe AI 2026-09-15 发布的判断型模型：输入一段文本和一组闭集问题，每题独立给出带校准概率的选项，不生成文字。**问题的形状（闭集、逐题独立、要概率）正是它的主场，但这一期卡住我们的，不是它擅长的东西：**

| | 普通大模型 | Jev |
|---|---|---|
| 证据片段硬闸（§5.3） | 能原样抄原文，代码直接做子串校验 | 不生成文字，抄不了。变通办法是代码先把正文切成句，让它选「哪一句」，要另测 |
| v0.1 改题 | 能说出为什么这样答；闸一和人工对不上时，看得出是题出坏了还是读偏了 | 只有概率，分不出这两种情况 |
| 最难的几题（反问 vs 真提问、暗示产品、会引起争议、已发生 vs 担心） | 语用判断是强项 | 官方写明的短板：偏字面、怕多层推理；中文不是主力语言，官方建议自测 |
| 逐题独立（防晕轮） | 分组 + 闸一的「分组 vs 单问」检验，最坏退到每题单问 | 天生如此 |
| 校准概率 | 没有（多次采样能凑，但贵） | 有，这是它真正独有的 |
| 成本、速度 | 全库一遍几百元到一两千元 | 更便宜更快，但在这个量级不改变任何决定 |
| 能不能用 | 走现有网关 | 服务在美国，条款面向美国用户，大陆主体能否开通没确认 |

所以闸一只比网关里的便宜档和 essence 现在用的 Sonnet 档，**过线的最便宜那个胜出**。表结构已经给 Jev 留了位置：`extractor` 区分抽取器，`prob` 存概率，换它只是多一个抽取器，旧答案按抽取器分开保存、不混用。

三种情况再把它拉进闸一对比：问题库冻结之后（不再需要靠解释改题）；量级变了（比如给每条评论分意图——几万条短文本、闭集、概率有用——或者在写作台编辑器里实时检查）；开通和条款问题确认了。

---

## 6. 三道闸

**没过闸的特征只留在事实层**：可以查、可以在报告里当描述用，但不进 L2、不进经验卡的「已验证规律」、不进写作台。

### 6.1 闸一 · 测得准

**样本**：5 个大项目（清洗后正例 ≥ 20：NUC、NRT_2、NRT_3、OKMAN、SPX）各抽 30 条爆款（不足 30 全取）+ 30 条趴，约 300 篇，固定随机种子，名单存档。其中 100 篇（每项目 10 爆 + 10 趴）人工逐题标，另挑 50 篇让第二个人再标一遍。

| 检查 | 通过线（提议） |
|---|---|
| 同一模型跑两遍，每题一致率 | ≥ 0.90 |
| 模型 vs 人工，每题一致率 | ≥ 0.85，且 Cohen's κ（扣掉碰巧一致之后的一致程度）≥ 0.60 |
| 人 vs 人（50 篇） | κ ≥ 0.60。**人和人都对不上的题，是题出坏了，先改题** |
| 证据片段无效率 | ≤ 3% |
| 分组问 vs 单题问 | 一致率 ≥ 0.90，否则该题改单问 |
| 标题切法 | 每个项目抽 20 条看 `raw_content` 结构，登记切法 |

过不了的题：改题干（版本 +1）重测，或者删掉。附带产出 §2.2 那几组 essence 互证的对不上比例（只报告，不当闸）。

产出：`data-analysis/feature-gate1-<日期>.md`。

### 6.2 闸二 · 有区分度（判据先写死）

**数据**：与 l2-feasibility §8.2 同一批行——读 `v_l2_labels`，有 essence、正文 ≥ 50 字。正例 = 清洗后的爆 / 大爆，负例 = 趴；评估中、参考、风控等不进。

**单个特征值怎么判**：每个项目一张 2×2 表（有这个特征值 / 没有 × 爆 / 趴），然后看四条：

1. **按项目分层合并的优势比**（Mantel–Haenszel）。意思是「在同一个项目里比，有这个特征的，爆的几率是没有的几倍」。只在项目内比，所以不怕各项目的爆率本身差很多。附录 B.1 的 SQL 已经和 statsmodels 的 `StratifiedTable` 对过，点估计和 95% 置信区间逐位一致。
2. **多重比较校正**。一轮要测几十个特征值，按 5% 的门槛，纯靠运气也会冒出一两个「显著」，所以用 Benjamini–Hochberg 校正（q ≤ 0.10）。占位题算在同一个校正家族里，一视同仁；bool 题只算「是」那一行（「否」是它的倒数）。
3. **大项目逐个看方向**。正例 ≥ 20 的项目（动态算，不写死名单）里，最多只允许一个方向相反；现在是 5 个大项目，也就是至少 4 个同向。单个项目只有 20–40 个正例时方向本身会抖，所以不要求全部同向。这条是故意偏严的：**宁可漏掉弱规律，也不把噪声喂给写作台。**
4. **加控制后不变**。再按「项目 × 账号先验爆率」分层重算一遍。账号先验只用该账号**更早发布**的、已清洗标签的笔记，至少 3 篇才算，分三档：无记录 / 低于项目基线 / 不低于项目基线。方向变了、或者点估计变化超过 30%，标 `confounded`，多半是账号的功劳。

| 状态 | 条件 |
|---|---|
| `validated` | 四条全过，且方向与预注册一致 |
| `reversed` | 显著，但和预注册的 + / − 相反。**不自动用**，拿来讨论 |
| `no_signal` | 合并优势比的 95% 置信区间跨 1 |
| `confounded` | 第 4 条不过 |
| `unreliable` | 闸一没过 |
| `insufficient` | 有这个取值的笔记不足 30 条，或大项目不足 3 个 |

预注册方向是「?」的特征：第 3 条的「同向」指与合并优势比同向；四条都过也只标 `validated`，并在 summary 里注明「新发现，方向未预设」，owner 看过再下发。

**组合进不进 L2**：在 l2-feasibility 的留一项目 SQL 里加一类 `Q:` 特征，同一批行、同一个最笨的打分器（特征对数几率的平均），三方对比「只 essence / 只原子题 / 合并」（附录 B.3）。进 L2 的条件：

- 合并比只 essence 的加权 AUC 高 ≥ 0.02，**且**按项目分层自助抽样 1,000 次、差值的 95% 置信区间下界 > 0；
- 最低 20% 那一档的爆率，不高于「只 essence」打分器的最低 20%。

为什么要看配对差值，不能只看两个 AUC：本地合成数据（136 个正例）上，把标签在项目内打乱 5 次，加权 AUC 在 0.42–0.53 之间跳。真实数据正例多一倍，噪声小一些，但 0.01–0.02 的差单独看仍然说明不了什么。

**反证（先跑；过了才看正式结果）**：

- 3 个占位题在任一方向上都不许同时满足第 1–3 条（它们的预注册方向是 0，这里不看方向一致与否，只看会不会被判「显著且稳定」）；
- 项目内置换标签跑 20 次，加权 AUC 平均落在 0.47–0.53，且没有一次超过真实那一跑（附录 B.4）；
- 附录 B.1 的 SQL 与 statsmodels 对数一致。

**预注册**：跑之前把问题库改成 `frozen`、记下 sha256 和当轮的抽取器集合（附录 B.3 的 `:sha` / `:extractors`，就是这一跑的快照），本节的判据数字写进 DECISIONS。产出：`data-analysis/feature-gate2-<日期>.md`，加上 `feature_validation` 各行。

### 6.3 闸三 · 对新笔记也成立

历史数据里时间和项目完全共线（l2-feasibility §4③），分不清「规律失效了」还是「换了个客户」。唯一的办法是往前看：

1. **冻结**打分器（权重、切点、`bank_version` 合成一个版本号），记下冻结日。
2. 冻结日之后发布的每条笔记，入库时只凭文本打分，写进 `content_scores`。
3. 等这些笔记落到 爆 / 大爆 / 趴（评估中不算），比两档的爆率（附录 C）。

| 通过线（提议） | 需要的样本 |
|---|---|
| 最低 20% 的爆率 ≤ 其余 80% 的 0.6 倍，且单侧两比例检验 p < 0.05 | 约 1,540 篇新笔记（最低档约 310 篇），按现在的入库速度一到两个月 |

l2-feasibility §3 的历史数是最低档 3.38%、其余四档平均 7.58%，约 0.45 倍——但那是 9/15 在清洗前的标签上算的。**P2 要先用 `v_l2_labels` 重算这张分档表作为闸三的基线**，0.6 倍这条线届时按重算结果复核。

**闸三不依赖特征层**：现有的 essence 打分器今天就可以冻结、开始入库打分。等特征层过了闸二，再用「essence + 特征」的版本开第二条。这样「排雷值不值得做」这件事本身，不用等特征层。

---

## 7. 接进飞轮（只接过了闸的）

### 7.1 经验卡与馆员

1. **卡上标出命中的已验证规律**：`v_flywheel_lesson_cards` 加一列 `validated_hits TEXT[]`，内容是这张卡的源笔记命中了哪些 `validated` 的特征值（答案表 join 最新一轮 `feature_validation`）。`why_it_worked` 照旧保留，旁边多一行有对照证据的事实。
2. **馆员多一个缓存块「已验证规律」**，每条一句人话，取自 `feature_validation.summary`。`ROLE_TASK_INSTR` 加一句：优先借命中已验证规律的卡，`borrow_what` 里写明借的是哪一条。
   ⚠️ `library_version()` 现在由候选数、最新策展时间、月份桶、候选 ID 摘要四项组成，规律更新时这四项可能一项都不变。**必须把 `gate2_run` 并进去**，否则规律换了、馆员缓存不会失效。
3. **`rank_score` 的账号项**（§11 第 7 条）：把 `COALESCE(personal_bao_rate, 0.3) × 0.3` 换成 `0.3 × (1 − 收缩后的账号先验)`。账号先验只用这条笔记**之前**的清洗后标签，按 m = 10 向项目基线收缩：`(之前的爆款数 + 10 × 项目基线) / (之前的笔记数 + 10)`。意思是：弱账号爆出来的那条，更能说明内容本身的功劳，排前面。

### 7.2 顺手发现：书架准入没挡「铺评工单」（建议先单独修）

书架准入（`notes_v1_10` 的 `eligible`）挡了 `数值推断` 和 synthetic 的爆 / 大爆，**但没挡 D-060 的「铺评工单」这一路**。signal-definitions 的口径是这一路要剔出 L2 正例：途鸽 45 条爆贴里 33 条是靠铺评跨过 50 条评论线的，互动中位 7。书架上却可能正拿它们当经验卡教写作台。修法是 `eligible` 加一条（本地已验证能编译）：

```sql
AND NOT (COALESCE(n.data_quality_flags -> 'comment_maintained_routes', '[]'::jsonb) ? '铺评工单'
         AND n.tier = ANY (ARRAY['爆', '大爆']))
```

读的是引擎写好的 `comment_maintained_routes`（它同时认顶层列和 `_undeclared`，D-060），不在视图里再写一遍列名判据。

### 7.3 写作台草稿：先影子，再放闸

- **影子期**（闸三进行中）：写作台每个新版本跑同一套题（`subject_type = 'aw_version'`，正文从哪列取以 aw 仓为准），冻结打分器给出项目内分位，写 `content_scores`（`shadow = true`），**只记不用**。每周看一个数：各项目写作台草稿落在历史最低 20% 的比例——这本身就是写作台出稿质量的一个诊断。
- **放闸后**（闸三通过）：给写作台 item 写 `prepublish_evaluations`：
  - `evaluator_type = 'model'`，`evaluator_id = 'tv-scorer:<版本>'`；
  - 最低 20% 的 `decision` 用 `revise`（还是 `reject`，待拍板），其余 `pass`；
  - `reasoning` 写特征对比（R-007 允许的形式）；`score_json` 放 `version_id`、分数、分位、打分器版本、缺了哪些已验证特征；
  - 最低档 `pred_tier_class = '趴'`，其余 NULL。
- 三个实现上的坑：
  - `model` 类型每个 item 可以有多行，不受 `idx_tv_evals_aw_item_evaluator_uniq` 限制（`notes_v1_11` 只把唯一性扩到 human / rule_based / unverified）。
  - `actual_tier` 现在没有任何脚本回填。D-064 之后可以回填，但**必须对到版本**：用 `notes.source_autowriter_version_id = score_json->>'version_id'` 匹配，只给被发布的那个版本的 `model` 行写 `actual_tier`；同一个 item 的其他版本（没发出去的草稿）留 NULL。只按 `source_autowriter_item_id` 回填会把发布结果记到该 item 的每一个版本上，版本级校准整体被污染（codex review on #134）。对照语义仍是「对应版本」，不是「生成来源」。
  - 现有 `v_evaluator_calibration` 只统计 `was_correct` 非空的行，`pass` 行（`pred_tier_class` 为 NULL）会被滤掉。**不改旧视图**，校准统一用附录 C 那种「分位 × 实际标签」的查询。
- **TV 不拦发布。** 放不放、改不改，由第 3 层（写作台选稿、人）决定。

### 7.4 探索比例

建议写作台 10%–20% 的 batch **随机**不注入已验证规律，并在 batch 元数据里记下来。三个理由：飞轮只喂自己验证过的东西，就只会反复学已经在做的事；规律什么时候失效，只有留着没照做的那部分才看得出来；它也正好是 §8 那个 A/B 的对照组。随机必须在 batch 级做，要和写作台一起定（§11 第 8 条）。

### 7.5 结案报告与看板

- 结案报告：项目内的特征对比表（每个特征值：有 / 没有 × 条数、爆款数、爆率），**带条数**，不能只报比例——单项目样本小，比例会骗人。客户（比如雷诺考特）追问的「爆款公式 + 分类爆率」，给的就是这张表。
- 看板：仿 `v_dash_format_perf` 加一个 `v_dash_feature_perf`（n ≥ 30，剔伪爆贴）。

---

## 8. 怎么算有用

| 要证明的 | 需要的样本 | 大概多久 |
|---|---|---|
| 闸一：题问得准 | 约 300 篇，其中 100 篇人工、50 篇双人 | 一周内 |
| 闸二：特征有区分度 | 现有历史：约 4,800 条有标签、正文 ≥ 50 字；清洗后正例 294（§8.2 的加权 AUC 用到 269） | 回填后一两天 |
| 闸三：排雷对新笔记也成立 | 约 1,540 篇新笔记（最低档约 310 篇） | 按入库速度一到两个月 |
| 写作台照规律写，爆率从 7% 提到 9% | 每组约 2,900 篇，随机分组，每篇能追溯到写作台 batch | 一个季度以上 |
| 投流后的增长能不能被分数预测 | 等运营三列攒起来 | 待定 |

所以**前两个月的验收只看排雷，不看爆率提升。** 投流数据攒起来以后，「投流后的增长」是比「自然爆没爆」更干净的标签：它量的是给了曝光之后内容本身的潜力。

---

## 9. 风险

| 风险 | 会怎样 | 怎么防 |
|---|---|---|
| 写作台照着规律写，越写越像 | 规律失效；模仿表层还可能招平台风控（R-001） | 只下发结构层的规律，不下发字面；探索比例；每季度重跑闸二 |
| 标签是评论数 | 飞轮奖励钓鱼帖、争议帖，品牌露出变少 | 产品露出族必须一起看；`efficacy_promise` 永不下发 |
| 正例少、特征多 | 学到噪声 | 预注册 + 项目分层 + BH 校正 + 大项目同向 + 占位题反证 |
| 时间 ≈ 项目 | 分不清规律失效还是换了客户 | 闸三只看冻结日之后的新笔记 |
| 换模型、改题 | 前后答案不可比 | 按版本、按抽取器分开存；换模型先重跑闸一 |
| 抖音 | LNKT 只有 1 个正例；抖音行的文案可能继承自上一行（D-052） | 照样抽特征；1 个正例在项目分层合并里几乎没有权重，不影响闸二 |
| 封面、图文 / 视频 | 库里没有封面，也没有图文 / 视频字段 | 已知盲区，本期不做 |
| 模型凭印象答「是」 | 特征虚高 | 证据片段硬闸 + 人工抽查 |

---

## 10. 分阶段

| 阶段 | 做什么 | 过了什么才进下一步 | 估时 |
|---|---|---|---|
| P0（现在就能做，和特征层无关） | 写作台恢复借书（aw 仓，docs/27）；书架挡铺评工单（§7.2）；冻结现有 essence 打分器、开闸三 | — | 各自独立 |
| P1 | 按本次讨论改完问题库；迁移 `notes_v1_13`、`annotate_feature_pass.py`、worker 端点、CI 守卫；闸一 | 闸一 | 约一周 |
| P2 | 全库回填；重算 §3 分档表作闸三基线；冻结问题库、写死判据；闸二；出报告；决定进不进 L2 | 闸二 | 约一周 |
| P3 | 冻结「essence + 特征」打分器开闸三第二条；写作台草稿影子打分 | 闸三 | 一到两个月（等数据） |
| P4 | 经验卡的已验证规律、馆员缓存块、`rank_score` 改法；写作台 `prepublish_evaluations` 的 model 行；探索比例 | 持续监控 | — |
| P5 | 投流三列攒起来以后：自然 / 投流分开看，「投流后增长」当第二标签 | — | 待定 |

---

## 11. 要讨论、要拍板的

1. **问题库 20 题怎么增删改。** 重点看评论诱导那 5 题和产品露出族。`efficacy_promise` 永不下发这条是否认可。
2. **标题怎么拿。** 建议 mapping 加可选键 `title_extraction`（`column` / `bracket_markers` / `first_line` / `none`），每表抽 20 条核实后登记；`none` 的项目，标题类题一律记 NULL。
3. **结构类题归哪层、半衰期多少。** 建议先放 `surface`、30 个月（同「时代语言范式」档）。另设一个「结构」档等于改 README 原则 2，由 owner 定。
4. **`note_features` 的分工。** 建议数值原值进 `note_features`，分档值和模型答案进长表；六个 LLM 列加 COMMENT 标注不用、不删。
5. **`v_l2_labels` 的口径。** 建议 v1 **逐字照搬** l2-feasibility §8.6 的 `d`，先复现 0.635、确认管道对得上；再单独一个 PR 修下面四处，并出一份新旧口径的差异报告：
   - (a) `NOT (raw_extra ? … OR raw_extra ? …)` 在 `raw_extra` 为 NULL 时整体求值为 NULL，这条干净爆款会被**静默排除**（本地已复现）；
   - (b) `tier_source <> '数值推断'` 对 `tier_source` 为 NULL 的行同理（本地已复现）；
   - (c) §8.6 的 SQL 比 signal-definitions §八 少了 ②（synthetic 闸）：形如「伪500评」的 synthetic 行不含「伪爆」二字，会被当成正例（本地已复现）；
   - (d) 铺评工单改读引擎写的 `comment_maintained_routes`，不再只看顶层列名。

   上线前先在生产跑一次，看这四处各影响多少条：
   ```sql
   SELECT count(*) AS 爆款行,
          count(*) FILTER (WHERE raw_extra IS NULL)   AS a_raw_extra为空,
          count(*) FILTER (WHERE tier_source IS NULL) AS b_tier_source为空,
          count(*) FILTER (WHERE data_quality_flags->>'synthetic' = 'true'
                             AND COALESCE(raw_extra->>'_tier_source_raw', '') NOT LIKE '%伪爆%') AS c_synthetic漏网,
          count(*) FILTER (WHERE COALESCE(data_quality_flags->'comment_maintained_routes', '[]'::jsonb) ? '铺评工单'
                             AND NOT (COALESCE(raw_extra, '{}'::jsonb) ? '维护评论50条'
                                      OR COALESCE(raw_extra, '{}'::jsonb) ? '评论铺设情况')) AS d_只有引擎认出的铺评工单
   FROM truth_vault.notes
   WHERE tier IN ('爆', '大爆');
   ```
6. **闸二的数认不认。** 单个特征：合并优势比 95% 置信区间不跨 1 + BH q ≤ 0.10 + 大项目最多一个反向 + 加控制后不变。组合进 L2：+0.02 且配对自助置信区间下界 > 0。
7. **`rank_score` 的账号项换不换**（§7.1 第 3 条）。换了会改变书架前排是哪些卡。
8. **写作台侧三件事**，要和 aw 维护者一起定：影子期看什么；放闸后最低档用 `revise` 还是 `reject`；探索比例 10%–20%、batch 级随机、记在哪。
9. **闸一比哪几个模型。** 建议只比网关便宜档和 Sonnet 档；Jev 等问题库冻结后再比（理由见 §5.7）。
10. **书架挡铺评工单**（§7.2）：和特征层无关，建议先单独修。

### 11.1 拍板记录（2026-09-19，D-065 续）

| # | 结论 | 谁定的 |
|---|---|---|
| 1 | 题目**先不动**，闸一是改题的机制；`efficacy_promise` 永不下发**认可**。写作台指令里「客户不允许 / 已在做」的，问运营（ops-request-2026-09-19 Q4） | owner 授权 Claude 判；业务部分问运营 |
| 2 | **由数据定，不问运营**。17 张表实查：TGV 用独立 `title` 列（130/144）；其余 16 张文案里带标记，两种写法：`【标题】…【正文】…`（RIO / WTG / SPX / LNKT / OKMAN / XIWU / ANSHEN / HATHERINE / BJS / TUGE / TXQ）和 `标题：…\n正文：…`（NRT_2 / NRT_3 / NUC / HXZ_QD / HXZ_FB，冒号有全角半角）。mapping 加 `title_extraction: column \| markers \| none`，`markers` 一个解析器认两种写法，都切不出来才记 NULL | Claude |
| 3 | 先 `surface`、30 个月；不改 README 原则 2。闸二跑完看结构类题跨项目稳不稳定再议 | Claude |
| 4 | 数值原值进 `note_features` 现有列，分档值和模型答案进 `note_feature_answers`；六个 LLM 列加 COMMENT 不删 | Claude |
| 5 | **已做**：`v_l2_labels`（D-067，#136，生产已 apply）。附录 A 里的定义由它取代 | 完成 |
| 6 | 单特征四条判据**认**；组合进 L2 的 +0.02 和自助下界 > 0 **认**。**闸三线从 0.6 改 0.5**：清洗后口径重算的基线是最低档 2.23% vs 其余 6.93%（0.32 倍，见 l2-labels-v1-vs-v2 §四），0.6 太松 | Claude |
| 7 | **换**成「超出账号基线」（§7.1 第 3 条），放 P4；换完把书架前 20 张前后对照贴进 DECISIONS | Claude |
| 8 | 影子期每周看「各项目草稿落在历史最低 20% 的比例」；最低档用 `revise`，TV 不拦发布（R-007）；探索比例 **15%**、batch 级随机、记在 batch 元数据。前提是借书管子先通（docs/27） | Claude；标记怎么呈现给选稿的人，问 aw 维护者 |
| 9 | 只比网关便宜档和 Sonnet 档，过线的最便宜者胜出；Jev 不进这一期 | Claude |
| 10 | **已做**：书架（D-066，#135）+ 通道 1（D-068，#138），生产已 apply / 合并后夜跑自愈 | 完成 |

问运营的六件（品牌词写法、客户禁止的写法、禁词清单、铺评完成勾选框、维护情况列的用法、人工标注人手）见 `data-analysis/ops-request-2026-09-19.md`。

---

## 12. 本期不做

- 不做自由文本特征（R-003），不做 embedding 检索当主查询（R-001）。
- 不训练直接读正文的模型：正例不够（l2-feasibility §5③），字符特征已证伪（§8.2）。
- 不给改写建议（R-007）；排雷分只在内部用，不对客户报「P(爆)」。
- 不把评论、控评、铺评、置顶、投流当特征（signal-definitions §一）。
- 不在本期搭 L2 在线服务（l2-feasibility §7 的结论：先把排雷变成运营的默认动作，收益大于先搭预测服务）。
- 不改 essence 词表。

---

## 附录 A · 迁移草稿 `schemas/notes_v1_13_content_features.sql`

本地验证做过的事：Postgres 16（与 CI 同版本）按 CI 顺序套完 v1_2 → v1_12 后，本文件连跑两遍无报错；`feature_validation.status` 的 CHECK 会拒绝非法值；`v_l2_labels` 用合成数据逐类核过——伪爆、铺评工单、数值推断、互动低于趴中位都被剔除；`raw_extra` 为 NULL、`tier_source` 为 NULL 的干净爆款被误剔，synthetic「伪500评」被误收（即 §11 第 5 条的 a、b、c），`v_feature_contrast` 的分母正确排除了无效答案。

定稿后要同步：`scripts/README.md` 的部署清单；CI 的 SQL apply job（两遍幂等 + sanity check）。

```sql
-- ════════════════════════════════════════════════════════════════════
-- truth_vault v1.13（草稿）· 内容特征层（docs/28 · D-065 草案）
-- ════════════════════════════════════════════════════════════════════
-- 三张表 + 两个视图, 全部幂等（IF NOT EXISTS / OR REPLACE）, CI 连跑两遍。
--   note_feature_answers  Layer 1 · 原子问题的答案（事实, 不是判断; D-004 extract_features）
--   feature_validation    闸二结论 · 每个特征值一行（validated / no_signal / reversed / ...）
--   content_scores        Layer 2 · 打分器输出（D-004: 管家没有 score, 所以不在 Layer 1）
--   v_l2_labels           L2 正例/负例口径的【唯一住处】（逐字沿用 l2-feasibility §8.6 的 d）
--   v_feature_contrast    每个项目 × 每个特征值的 2×2 计数, 闸二的输入
-- 不建跨 schema 外键: subject_id 可能指 autowriter.versions（同 D-064 的做法, 悬空靠
-- verify_supabase_state.sql 查）。
-- ════════════════════════════════════════════════════════════════════

-- 1. 原子问题答案 ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS truth_vault.note_feature_answers (
    subject_type     TEXT NOT NULL CHECK (subject_type IN ('note', 'aw_version')),
    subject_id       TEXT NOT NULL,   -- note → notes.note_id; aw_version → autowriter.versions.id::text
    question_id      TEXT NOT NULL,   -- 问题库里的 id
    question_version INT  NOT NULL,   -- 改题 = 版本 +1, 旧答案保留不覆盖
    bank_version     TEXT NOT NULL,   -- 'fq-v0.1'
    bank_sha256      TEXT NOT NULL,   -- 跑的时候对问题库文件算的校验和（同 D-041 的纪律）
    extractor        TEXT NOT NULL,   -- 'code:v1' / 'llm:<模型>' / 'jev:<模型>' / 'human:<人>'
    run_tag          TEXT NOT NULL DEFAULT 'primary',  -- 只有 primary 进分析; retest-* / gate1-* 只给闸一
    answer           TEXT,            -- 闭集取值; NULL = 无效, 原因见 invalid_reason
    evidence         TEXT,            -- 答「是」时引用的原文片段; 代码校验它必须是原文子串
    prob             REAL,            -- 有概率才填（Jev / 多次采样的一致率）, 否则 NULL
    invalid_reason   TEXT,            -- evidence_not_found / out_of_vocab / text_too_short / ...
    extracted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (subject_type, subject_id, question_id, question_version, extractor, run_tag)
);
CREATE INDEX IF NOT EXISTS idx_tv_nfa_question
    ON truth_vault.note_feature_answers (question_id, question_version, answer);
ALTER TABLE truth_vault.note_feature_answers ENABLE ROW LEVEL SECURITY;

-- 2. 闸二结论 ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS truth_vault.feature_validation (
    question_id           TEXT NOT NULL,
    question_version      INT  NOT NULL,
    answer                TEXT NOT NULL,  -- bool 题只登记「是」; choice 题每个取值一行
    bank_version          TEXT NOT NULL,
    gate2_run             TEXT NOT NULL,  -- 'gate2-2026-10-xx'
    status                TEXT NOT NULL CHECK (status IN
                              ('validated',     -- 过了闸二全部判据
                               'no_signal',     -- 置信区间跨 1
                               'reversed',      -- 显著, 但和预注册方向相反: 不自动用, 拿来讨论
                               'confounded',    -- 加上账号先验分层后方向变了或效应缩了 30% 以上
                               'unreliable',    -- 闸一没过（测不准）
                               'insufficient')),-- 有这个取值的笔记 < 30 条, 或大项目 < 3 个
    hypothesis            TEXT CHECK (hypothesis IN ('+', '-', '?', '0')),  -- 预注册方向（'0' = 占位题）
    mh_odds_ratio         REAL,           -- 按项目分层合并的优势比
    ci_low                REAL,
    ci_high               REAL,
    q_value               REAL,           -- BH 校正后
    big_projects_same_dir INT,            -- 大项目里与预注册方向一致的个数
    big_projects_n        INT,
    summary               TEXT,           -- 给人读的一句话, 如「5 个项目 4 个同向, 项目内爆率 9.1% vs 5.2%」
    decided_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (question_id, question_version, answer, gate2_run)
);
ALTER TABLE truth_vault.feature_validation ENABLE ROW LEVEL SECURITY;

-- 3. 打分器输出（Layer 2）───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS truth_vault.content_scores (
    subject_type    TEXT NOT NULL CHECK (subject_type IN ('note', 'aw_version')),
    subject_id      TEXT NOT NULL,
    project_id      TEXT NOT NULL,
    scorer_version  TEXT NOT NULL,        -- 冻结的打分器: 权重快照 + bank_version + 切点
    score           REAL NOT NULL,
    pct_in_project  REAL CHECK (pct_in_project >= 0 AND pct_in_project <= 1),  -- 0 = 最差
    cutpoints       TEXT NOT NULL CHECK (cutpoints IN ('project', 'pooled')),  -- 新项目没历史就用全库
    shadow          BOOLEAN NOT NULL DEFAULT TRUE,   -- 影子期只记不用
    scored_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (subject_type, subject_id, scorer_version)
);
ALTER TABLE truth_vault.content_scores ENABLE ROW LEVEL SECURITY;

-- 4. 标签口径的唯一住处 ─────────────────────────────────────────────
-- ⚠️ 逐字沿用 l2-feasibility §8.6 的 d（只去掉「有 essence、正文 ≥50 字」这两条行过滤,
--    那是实验的取数条件, 不是口径）, 目的是先复现 0.635、确认管道对得上。
--    四处已知问题【故意没顺手改】, 放到 v2 单独一个 PR 修并出差异报告（docs/28 §11 第 5 条）:
--    (a) raw_extra 为 NULL 时, NOT (raw_extra ? … OR raw_extra ? …) 整体为 NULL → 干净爆款被静默排除;
--    (b) tier_source <> '数值推断' 对 tier_source 为 NULL 的行同理;
--    (c) §8.6 的 SQL 比 signal-definitions §八 少了 ②（synthetic 闸）: 形如「伪500评」的
--        synthetic 行不含「伪爆」二字, 会被当成正例;
--    (d) 铺评工单只看 raw_extra 顶层键; D-060 引擎写的 comment_maintained_routes 也认 _undeclared。
CREATE OR REPLACE VIEW truth_vault.v_l2_labels AS
WITH pa AS (
    SELECT project_id, percentile_disc(0.5) WITHIN GROUP (ORDER BY interactions) AS pm
    FROM truth_vault.notes
    WHERE tier = '趴' AND interactions IS NOT NULL
    GROUP BY 1
)
SELECT n.note_id, n.project_id, n.account_id, n.publish_time, n.platform,
       CASE WHEN n.tier IN ('爆', '大爆') THEN 1 ELSE 0 END AS y
FROM truth_vault.notes n
LEFT JOIN pa USING (project_id)
WHERE n.tier = '趴'
   OR ( n.tier IN ('爆', '大爆')
        AND COALESCE(n.raw_extra->>'_tier_source_raw', '') NOT LIKE '%伪爆%'
        AND NOT (n.raw_extra ? '维护评论50条' OR n.raw_extra ? '评论铺设情况')
        AND n.tier_source <> '数值推断'
        AND NOT (n.interactions IS NOT NULL AND pa.pm IS NOT NULL
                 AND n.interactions <= pa.pm) );

-- 5. 闸二输入: 每个项目 × 每个特征值的 2×2 ─────────────────────────
-- a = 有这个特征值且爆  b = 有且趴  c = 没有且爆  d = 没有且趴
-- 「没有」= 同一道题答了别的值; 答案无效（NULL）的行不进分母。
CREATE OR REPLACE VIEW truth_vault.v_feature_contrast AS
WITH ans AS (
    SELECT a.subject_id AS note_id, a.question_id, a.question_version,
           a.bank_version, a.extractor, a.answer
    FROM truth_vault.note_feature_answers a
    WHERE a.subject_type = 'note' AND a.run_tag = 'primary' AND a.answer IS NOT NULL
), lab AS (
    SELECT l.note_id, l.project_id, l.y, ans.question_id, ans.question_version,
           ans.bank_version, ans.extractor, ans.answer
    FROM truth_vault.v_l2_labels l
    JOIN ans USING (note_id)
), vals AS (
    SELECT DISTINCT question_id, question_version, bank_version, extractor, answer AS value
    FROM lab
)
SELECT l.project_id, v.question_id, v.question_version, v.bank_version, v.extractor, v.value,
       count(*) FILTER (WHERE l.answer =  v.value AND l.y = 1) AS a,
       count(*) FILTER (WHERE l.answer =  v.value AND l.y = 0) AS b,
       count(*) FILTER (WHERE l.answer <> v.value AND l.y = 1) AS c,
       count(*) FILTER (WHERE l.answer <> v.value AND l.y = 0) AS d
FROM vals v
JOIN lab l USING (question_id, question_version, bank_version, extractor)
GROUP BY 1, 2, 3, 4, 5, 6;
```

---

## 附录 B · 闸二 SQL（都在本地合成数据上跑通）

### B.1 单个特征值：项目分层合并优势比 + 95% 置信区间

点估计是 Mantel–Haenszel，区间用 Robins–Breslow–Greenland 方差。合成数据上与 statsmodels `StratifiedTable` 逐位一致（例：`ending_asks_reader = 是`，OR 2.477，CI 1.738–3.530）。BH 校正要 p 值，放 Python 里用 statsmodels 算，SQL 只出 2×2 和区间。

```sql
WITH t AS (
    SELECT question_id, question_version, bank_version, extractor, value,
           a::float8 a, b::float8 b, c::float8 c, d::float8 d, (a + b + c + d)::float8 n
    FROM truth_vault.v_feature_contrast
    WHERE a + b + c + d > 1
), s AS (
    SELECT question_id, question_version, bank_version, extractor, value,
           sum(a * d / n) sr, sum(b * c / n) ss,
           sum(((a + d) / n) * (a * d / n))                                pr,
           sum(((a + d) / n) * (b * c / n) + ((b + c) / n) * (a * d / n))  ps_qr,
           sum(((b + c) / n) * (b * c / n))                                qs,
           count(*) strata
    FROM t GROUP BY 1, 2, 3, 4, 5
)
SELECT question_id, value, strata,
       round((sr / ss)::numeric, 3) AS mh_or,
       round(exp(ln(sr / ss) - 1.959964 * sqrt(pr / (2 * sr * sr) + ps_qr / (2 * sr * ss) + qs / (2 * ss * ss)))::numeric, 3) AS ci_low,
       round(exp(ln(sr / ss) + 1.959964 * sqrt(pr / (2 * sr * sr) + ps_qr / (2 * sr * ss) + qs / (2 * ss * ss)))::numeric, 3) AS ci_high
FROM s
WHERE sr > 0 AND ss > 0
ORDER BY question_id, value;
```

### B.2 大项目逐个看方向

```sql
-- 正例 ≥ 20 的项目算「大项目」（动态算, 不写死名单）; 每个大项目的优势比加 0.5 平滑, 只看方向
-- 两条纪律 (codex review on #134):
--   · 只数【这个取值真的出现过】的项目 (a + b > 0)。否则一个只在 3 个项目里出现的取值,
--     在另外 2 个项目里 a = b = 0, 平滑后的方向只由该项目 趴 多还是 爆 多决定 —— 几乎总是
--     「OR > 1」, 会假装 5 个项目同向。big_projects_n 因此是「有支持的大项目数」, 不足 3 个
--     → 状态 insufficient (§6.2)。
--   · 按快照五键分组 (question_version / bank_version / extractor 都在 GROUP BY 里)。只按
--     question_id + value 分组, 两个抽取器就会把 5 个项目数成 10 个。
WITH big AS (
    SELECT project_id FROM truth_vault.v_l2_labels GROUP BY 1 HAVING sum(y) >= 20
)
SELECT c.question_id, c.question_version, c.bank_version, c.extractor, c.value,
       count(*)                                                                      AS big_projects_n,   -- 只数有支持的
       count(*) FILTER (WHERE (c.a + 0.5) * (c.d + 0.5) > (c.b + 0.5) * (c.c + 0.5)) AS n_or_above_1,
       count(*) FILTER (WHERE (c.a + 0.5) * (c.d + 0.5) < (c.b + 0.5) * (c.c + 0.5)) AS n_or_below_1
FROM truth_vault.v_feature_contrast c
JOIN big USING (project_id)
WHERE c.a + c.b > 0                          -- 这个取值在该项目里至少出现过一次
GROUP BY 1, 2, 3, 4, 5
ORDER BY 1, 2, 3, 4, 5;
```

### B.3 组合对比：只 essence / 只原子题 / 合并（留一项目 + 中位秩 AUC）

与 l2-feasibility §8.6 同一个打分器，只把 `text` 那一类换成 `q`。

**先钉死快照，再算**（codex review on #134）：同一题可能被另一个模型重抽、或升过版本，新旧行都是 `run_tag = 'primary'`、同一个 `bank_version`。只按 bank 过滤会把它们混成一个特征集：重复答案被加倍计权，冲突答案让一篇笔记同时带两个互斥特征，AUC 就不可信。所以闸二的每一跑绑定一个快照：`bank_sha256`（文件校验和，任一题升版本它就变，等于钉住了全部 `question_version`）+ 抽取器集合（代码特征 `code:v1` 加当轮那一个 LLM 抽取器）。跑之前先查唯一性，不为空就不许跑：

```sql
-- 快照内 (笔记, 题) 必须唯一; :sha / :extractors 同下面那一跑
SELECT subject_id, question_id, count(*)
FROM truth_vault.note_feature_answers
WHERE subject_type = 'note' AND run_tag = 'primary'
  AND bank_sha256 = :sha AND extractor = ANY (:extractors)
GROUP BY 1, 2 HAVING count(*) > 1;
```

用法：`psql -v sha="'<bank_sha256>'" -v extractors="ARRAY['code:v1','llm:<模型>']" -f …`。附录 B.1 / B.2 读的 `v_feature_contrast` 已按 `question_version / bank_version / extractor` 分组，取当轮快照那几行即可。

```sql
WITH d AS (
    SELECT l.note_id, l.project_id, l.y,
           n.emotional_lever el, n.content_format cf, n.human_truth_archetype ar, n.target_audience ta
    FROM truth_vault.v_l2_labels l
    JOIN truth_vault.notes n USING (note_id)
    WHERE n.emotional_lever IS NOT NULL
      AND n.raw_content IS NOT NULL AND length(n.raw_content) >= 50
), f AS (
    SELECT note_id, 'L:' || el feat, 'tag' kind FROM d
    UNION ALL SELECT note_id, 'F:' || cf, 'tag' FROM d WHERE cf IS NOT NULL
    UNION ALL SELECT note_id, 'A:' || x, 'tag' FROM d, unnest(ar) x
    UNION ALL SELECT note_id, 'U:' || x, 'tag' FROM d, unnest(ta) x
    UNION ALL
    SELECT a.subject_id, 'Q:' || a.question_id || '=' || a.answer, 'q'
    FROM truth_vault.note_feature_answers a
    JOIN d ON d.note_id = a.subject_id
    WHERE a.subject_type = 'note' AND a.run_tag = 'primary'
      AND a.bank_sha256 = :sha                       -- 钉住问题库快照 (= 全部 question_version)
      AND a.extractor = ANY (:extractors)            -- 钉住抽取器集合 (code:v1 + 当轮那一个 LLM)
      AND a.answer IS NOT NULL
      AND a.question_id NOT LIKE 'placebo%'          -- 占位题只进反证那一跑, 不进正式对比
), va(v) AS (VALUES ('tag'), ('q'), ('both')),
fv AS (SELECT va.v, f.note_id, f.feat FROM va JOIN f ON (va.v = 'both' OR va.v = f.kind)),
projs AS (SELECT DISTINCT project_id FROM d),
lo AS (
    SELECT fv.v, p.project_id tp, fv.feat,
           ln((count(*) FILTER (WHERE d.y = 1) + 1.0) / (count(*) FILTER (WHERE d.y = 0) + 1.0)) w
    FROM projs p JOIN d ON d.project_id <> p.project_id
         JOIN fv ON fv.note_id = d.note_id
    GROUP BY 1, 2, 3
), sc AS (
    SELECT fv.v, d.note_id, d.project_id, d.y, avg(lo.w) s
    FROM d JOIN fv ON fv.note_id = d.note_id
           JOIN lo ON lo.v = fv.v AND lo.tp = d.project_id AND lo.feat = fv.feat
    GROUP BY 1, 2, 3, 4
), r AS (
    SELECT v, project_id, y,
           rank() OVER (PARTITION BY v, project_id ORDER BY s)
             + (count(*) OVER (PARTITION BY v, project_id, s) - 1) / 2.0 AS mrk
    FROM sc
), a AS (
    SELECT v, project_id, count(*) FILTER (WHERE y = 1) pos,
      ((sum(mrk) FILTER (WHERE y = 1)
        - count(*) FILTER (WHERE y = 1) * (count(*) FILTER (WHERE y = 1) + 1) / 2.0)
       / NULLIF(count(*) FILTER (WHERE y = 1)::numeric * count(*) FILTER (WHERE y = 0), 0)) auc
    FROM r GROUP BY 1, 2
)
SELECT project_id, max(pos) pos,
       round(max(auc) FILTER (WHERE v = 'tag'), 3)  auc_essence,
       round(max(auc) FILTER (WHERE v = 'q'), 3)    auc_原子题,
       round(max(auc) FILTER (WHERE v = 'both'), 3) auc_合并
FROM a GROUP BY 1 HAVING max(pos) >= 5
UNION ALL
SELECT '【按正例加权】', sum(pos) FILTER (WHERE v = 'tag'),
       round(sum(auc * pos) FILTER (WHERE v = 'tag')  / sum(pos) FILTER (WHERE v = 'tag'), 3),
       round(sum(auc * pos) FILTER (WHERE v = 'q')    / sum(pos) FILTER (WHERE v = 'q'), 3),
       round(sum(auc * pos) FILTER (WHERE v = 'both') / sum(pos) FILTER (WHERE v = 'both'), 3)
FROM a WHERE pos >= 5
ORDER BY 1;
```

配对自助抽样（差值的置信区间）不在 SQL 里做：把 `sc` 的打分结果导出，Python 按项目分层有放回抽笔记 1,000 次，每次算「合并 − 只 essence」的加权 AUC 差。

### B.4 置换反证

把 B.3 开头的 `WITH d AS (` 改成 `WITH d0 AS (`，再把紧跟在它后面的那一行 `), f AS (` 整行换成下面这段，其余原样。`:seed` 换 20 个值各跑一次（`psql -v seed="'1'" …`）。

```sql
), shuf AS (   -- 项目内置换标签（:seed 决定怎么换）, 特征不动
    SELECT d0.*, row_number() OVER (PARTITION BY project_id ORDER BY note_id) rn,
           row_number() OVER (PARTITION BY project_id ORDER BY md5(note_id || :seed)) rn2
    FROM d0
), d AS (
    SELECT x.note_id, x.project_id, yy.y, x.el, x.cf, x.ar, x.ta
    FROM shuf x JOIN shuf yy ON yy.project_id = x.project_id AND yy.rn2 = x.rn
), f AS (
```

合成数据上（136 个正例，一个真信号、一个弱信号、一个随机特征）：真实一跑加权 AUC 为 essence 0.550 / 原子题 0.589 / 合并 0.631；5 次置换为 0.42–0.53。

---

## 附录 C · 闸三 SQL

```sql
-- 只看【冻结日之后发布】的笔记, 用冻结的打分器分两档比爆率
-- :scorer 打分器版本, :freeze 冻结日
SELECT CASE WHEN s.pct_in_project < 0.2 THEN '最低 20%' ELSE '其余 80%' END AS 档,
       count(*)                          AS n,
       sum(l.y)                          AS 爆,
       round(100.0 * avg(l.y), 2)        AS 爆率_pct
FROM truth_vault.content_scores s
JOIN truth_vault.v_l2_labels l ON l.note_id = s.subject_id
JOIN truth_vault.notes n       ON n.note_id = s.subject_id
WHERE s.subject_type = 'note'
  AND s.scorer_version = :scorer
  AND n.publish_time >= :freeze
GROUP BY 1
ORDER BY 1;
```

---

## 附录 D · 样本量怎么算的

两比例检验，双侧 α = 0.05，把握度 0.8：

n₁ = [ z₀.₉₇₅ · √( p̄q̄ (1 + 1/k) ) + z₀.₈ · √( p₁q₁ + p₂q₂ / k ) ]² / (p₁ − p₂)²，其中 n₂ = k · n₁，p̄ = (p₁ + k·p₂) / (1 + k)。

| 用在哪 | 假设 | 结果 |
|---|---|---|
| 闸三 | 两组 1 : 4；p₁ = 3.38%（最低档）、p₂ = 7.58%（其余四档平均），取自 l2-feasibility §3 | 最低档约 310、其余约 1,230，合计约 1,540 |
| 写作台 A/B | 两组等量；7% vs 9% | 每组约 2,890 |

闸三的判定用单侧检验，样本量按双侧算，偏保守。

闸三的数要在 P2 用清洗后的口径重算 §3 分档表之后复核。

---

## 附录 E · 定稿后要同步的地方

**文档**：DECISIONS.md 追加 D-065 定稿版；docs/00-START-HERE.md §9 索引加一行；README 的文档导航、「现在在哪」；CURRENT_STATE.md；scripts/README.md 部署清单加 `notes_v1_13`；worker/README.md 端点表加 `/annotate-features`；docs/05 加一段说明问题库和受控词表的关系（问题库不属于词表，但守同样的版本纪律）。

**CI 守卫（计划）**：断行为不断源码（D-051），每条都配反证，写了分支就要有用例走进去。

| # | 守什么 | 反证（改坏之后必须变红） |
|---|---|---|
| 1 | 问题库结构：id 唯一；每题在且只在一个 call_group；组 ≤ 4 题；bool 题有正反例；choice 题的 hypothesis 键与选项一致；冻结后 sha256 不变 | 删掉一题的组归属；改一个选项名 |
| 2 | Mode A 防泄漏：渲染出的 prompt 没有表现类占位符和关键词 | 往项目上下文里塞「互动数」 |
| 3 | 证据硬闸：证据不是原文子串 → NULL + `evidence_not_found`；答案不在闭集 → `out_of_vocab` | 去掉子串校验 |
| 4 | 分组：同一次调用里只出现一个组的题 | 把两个组合并成一次调用 |
| 5 | 占位题：答案由 note_id 确定地生成；闸二正式对比的 SQL 里 placebo 过滤还在 | 占位答案改用随机数；删掉过滤 |
| 6 | `library_version()` 随 `gate2_run` 变化 | 版本串里去掉 `gate2_run` |
| 7 | `efficacy_promise` 永不出现在下发给写作台的规律列表里 | 把它标成 validated 后看下发列表 |
