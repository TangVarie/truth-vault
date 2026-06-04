# Truth Vault · 代码库全面审计(2026-06-04)

> 一次性全仓审计快照,供新会话 / 技术接手快速建立全局认知。
> 覆盖:框架 · 逻辑 · 功能实现 · 问题/风险 · PR 与交接。
> 方法:并行 agent 通读全部设计文档 + 三个代码模块逐行核查 + GitHub PR/CI/workflow 核对。
> 进度基线:Session #16+ · 唯一 open PR #40(本审计同时修了它的 3 条 Codex review)。

---

## 0. 定位与一句话状态

**Truth Vault** 是帆谷的私有数据基础设施:把每一次小红书种草投放的真实结果沉淀下来,
让"什么内容会爆、为什么"变成有数据支撑的事实判断,并把"真实爆款经验"注入到两个现存内容
生产系统(三省六部 `sanshengliubu` / 内容工作台 `autowriter`),形成数据飞轮。它**不生产内容**。

**一句话状态:基础设施与代码 100% 就绪,数据已进库(WTG 682 行),通道 1 第一条参考样本已"上架";
但整条飞轮从未端到端真正转过一圈** —— 消费侧(ssll 写稿真读样本 / autowriter 写稿真借经验卡)
还没在生产里跑过消费动作。系统正处在"发条上满、还没松手"的临界点。**纸面就绪度 ≫ 实际验证度**,
是全系统的统一特征。

---

## 1. 框架与技术栈

### 1.1 两套"分层"是项目宪法

**① 三层标注架构**(每条数据独立标三层,绝不混进一个字段):

| 层 | 含义 | 衰减半衰期 | 抓取方式 |
|---|---|---|---|
| Surface 表层 | 字面词汇、当代话术、热点引用 | 6–12 个月 | 代码计算 + LLM 闭集分类 |
| Essence 内核 | 情绪杠杆、人性原型 | 5+ 年 | **必须闭集词表** + LLM 标注 |
| Audience 受众 | 推断画像 + 蒲公英真实数据校准 | 2–3 年 | LLM 推断 + 真实数据 |

跨产品复用是飞轮复利来源:不同产品 Surface 不同,但 Essence/Audience 可直接迁移。

**② 四层系统架构**(判断权边界):

- **Layer 1 · Truth Vault Core**:只存数据 / 出 anchor / sync —— **严禁内容判断**(管家不做判断)
- **Layer 2 · Predictor**:LightGBM 按 intent 分轨出 P(爆)/风险分(阶段 2 启用)
- **Layer 3 · Persona/Critic/Human**:最终内容判断权
- **Layer 4 · Optimization**:据真实表现反推 prompt 方向

### 1.2 工程栈

- 数据库:共享 Supabase Postgres `kduysqedrclrfevrxiie`,三 schema 并存 `truth_vault`(14 表)/`autowriter`(5 表)/`public`(ssll)
- 服务:FastAPI(librarian、onboarder 两个 Railway 服务)
- LLM 入口:**中转站 / NewAPI 网关**(`ANTHROPIC_BASE_URL`)+ Anthropic prompt caching,默认 `claude-sonnet-4-6`
- 导入器:飞书 OpenAPI(REST)
- 调度:GitHub Actions(`daily-sync.yml` cron `0 2 * * *` + `onboard-table.yml` 按钮触发)
- 向量索引:pgvector(阶段 3 才启用)

### 1.3 部署拓扑与一个结构性约束

```
飞书多维表 → GitHub Actions(Daily TV sync, cron 02:00 UTC) → 共享 Supabase truth_vault.notes
   ├─ 通道1(push)→ public.reference_samples → ssll vibe_rewriter 检索注入
   └─ 通道2(pull)→ autowriter 写稿时调 Railway 馆员服务借"经验卡"
Railway: librarian 服务(/librarian) · onboarder 服务(/onboard)
```

> ⚠️ **结构性约束:GitHub Actions 海外 runner 连不上中转站**(TCP 握手层 `connect=0` 超时,
> 网络/路由层,非应用封禁;`gateway-probe.yml` 至今在探),而 Railway 能连。
> 这解释了几乎所有近期架构动作:librarian/onboarder 搬 Railway、daily-sync 变红、essence/curate 待搬 Railway。

---

## 2. 核心逻辑与数据流

### 2.1 主链路:飞书 → Truth Vault

`scripts/sync_feishu_notes_to_truth_vault.py`:读飞书表 → 按 `mappings/<project>.yaml` 映射 →
数值清洗 + 未声明字段隔离(quarantine,D-021)→ tier 抽取(规则引擎)→ 关联 account →
UPSERT 到 `truth_vault.notes`(幂等键 `note_id = {project}_{feishu_record}`)。

**关键设计:sync 阶段绝不调 LLM**。Essence/Audience 标注延迟到独立 pass
(`annotate_essence_pass.py`),防 label leakage(D-017/D-028):prompt 物理拆成
Mode A(盲标,无表现数据)/ Mode B(事后解释,可看 tier)。

### 2.2 集成模式的三代演化(全项目最重要的逻辑线)

| 代 | 模式 | 为什么改 |
|---|---|---|
| D-023(已废) | TV 暴露 HTTP REST API 让三系统主动调 | 过度设计 |
| D-024 | **双通道直接 INSERT(push)**,推到现存系统已有注入点 | 现存系统比预期成熟,改造最小化 |
| D-038(最新) | **通道 2 改 pull + LLM 馆员**:autowriter 写稿时主动借阅 | push 的预路由复杂度太高;ssll 本就天生 pull |

**通道 1(push,仍 D-024)** TV → `public.reference_samples`:Filter `tier ∈ (爆/大爆/参考)` 且
`tier_source != 数值推断`;幂等键 `source_truth_vault_note_id`;注入点 ssll `vibe_rewriter` 按 `platform+category` 检索。

**通道 2(pull,D-038)** autowriter 写稿 → 调馆员:`curate_flywheel_lessons.py` 把合格爆款提炼成
"经验卡"写 `flywheel_lesson_annotations` → 视图 `v_flywheel_lesson_cards`(TV 当书架)→ autowriter 带 brief
调 `/librarian` → 馆员查缓存/按 brief LLM 选卡 → 注入 autowriter system prompt 的 P2 会话层。
**通道 2 的 push 脚本已退役(PR #36)**,历史脚本保留备查。

---

## 3. 模块盘点与代码级核查

### 3.1 `scripts/` 主数据管线(生产成熟)

主链路 [1 飞书→TV]→[2 →ssll] 生产成熟,幂等扎实(确定性主键 + 多层并发恢复:先查→插入→抓
23505 当成功 + `fetch_all_pages` 绕 PostgREST 1000 行截断),失败可见(cron 邮件 + `check_flywheel_health`)。

**代码级发现:**
- 🔴 **README 数据流图整体过期**:仍把已退役的通道 2(autowriter push)当活跃 [3];
  `daily-sync.yml:184-186` 已退役它。照 README 部署的人会去跑废弃的 917 行脚本
  (`preview_injection_candidates.py` 仍 import 它的 `apply_diversity_filter`,所以删不掉)。
- 🟠 评论楼层结构全 NULL:`parent_comment_id` 恒 NULL 且没保留平台原始评论 ID;`annotate_comment_threading.py`(Sprint 2,不在 cron)只能软推断。
- 🟠 `_comment_text_persona` 语义假设无代码护栏(若某项目用它表示"评论者画像"而非"第二段评论文本"会污染 `comments.content`)。
- 🟠 metric 时序回收未实现:`window_label` 从单次 `publish_time` 启发式推断,不是真多窗口采集。
- 🟡 `utcnow()` 已 deprecated(`sync_feishu:448`,naive,目前与 `_iso_now` 约定一致故正确但脆弱)。
- 🟡 三处技术债靠注释约束、无测试:① 运行时 prompt 模板 vs `prompts/*.md` 双份维护;
  ② essence 词表硬编码三处(Python set / schema CHECK / docs05);③ `call_claude` 已被第三个脚本 import,注释说"该提到 `_common`"但债没还。
- 观察:脚本里 2026-05-21/22 的 P0/P1/P2 audit 修复注释**密度极高** → 这是个易静默失败、靠 audit 兜底的系统,
  可靠性强依赖 `check_flywheel_health` 的 Check 2(用 ssll 的 `r022_flywheel_audit` 命中率验证"写稿真用了 DB 样本",是**唯一的真闭环检查**)。

`_common.py`(737 行)是复用核心:强制 service_role client(挡 publishable/anon)、`load_mapping`
(含 `tier_extraction.source` 闭集校验)、`fetch_all_pages`、飞书值清洗全家桶、FK 前置 upsert、
D-021 quarantine、`mask_secrets`。注意飞书分页/JWT 在 `sync_feishu` 的 `FeishuClient` 而非 `_common`。

### 3.2 `librarian/` 馆员服务(通道 2 核心,已上线 Railway)

FastAPI `POST /librarian`:brief → 读 `v_flywheel_lesson_cards` + 查 `flywheel_librarian_cache` →
命中跳过 LLM,否则单次非流式调 Anthropic(中转站 + prompt caching,system 分块:稳定卡片块 +
项目块 + 每次变的 delta)→ 返回选中经验卡。降级铁律:任何错误返回 `{"selected":[]}` 不阻塞写稿。

**代码级发现:**(工程完成度高,无 TODO/FIXME,无功能 bug,但有"文档/SQL 声称 ≠ 代码实际")
- 🟠 **缓存 prune(TTL/LRU)从未实现**:`notes_v1_5.sql` 与 `core.py` docstring 都说"定期清理",索引也建了,但全仓无任何 prune 脚本/cron。
- 🟠 **`v1.4 + v1.5` schema 是否已 apply 到 prod 口径不一**:PR #30 body 说"已 apply",但 `librarian/README` / `docs/14` 仍写"待建/部分已建" → 需连库核实(视图/表不存在则服务起不来)。
- 🟡 `library_version` 命名不一致:docs/SQL 写 `max(updated_at)`,但视图只导出 `curated_at`、代码读 `curated_at`(逻辑自洽,文档误导)。
- 🟡 降级把所有异常吞成 `[]`:`core.py` 的 `except Exception: return []` **不记日志** → 真 bug 被静默吞掉,排障盲区。
- 🟡 刻意的代码重复:`librarian/clients.py` 故意不复用 `scripts/_common`(为 Railway 独立部署)→ 两套 client 各自维护。
- 现状:书架近乎空库(只 1 张 synthetic 参考卡、`is_curated=false`)→ 服务当前实质是 no-op。

### 3.3 `onboarder/` 接表 agent(当前活跃开发 = PR #40)

把过去手搓的"飞书表 → `mappings/<project>.yaml`"定稿成可复制流水线。架构 = 确定性取数
(`list_fields` + N 行样本 + 全表 distinct)+ 单次 Anthropic 调用 + 校验门(词表闭集 + D-021 全列覆盖)。
判断权(方向/阈值/合规)全标 `[待确认]` 留给策略 lead 人审。GitHub 按钮触发 → Railway 跑 LLM →
推 `onboarder/draft-<id>` 分支 → 给开 PR 链接。

**代码级发现:**(离线可跑 `eval_wtg` PASS / `--dry-run` OK;**端到端真连飞书+中转站在仓库里无成功记录**)
- 🟠 **eval 的 `[待确认]` 覆盖断言形同虚设**(`eval_wtg.py:105`):`validate_mapping(WTG)` 的 `pending=[]`
  —— 因为金标准方向值填的是合法词表值(`直给推荐`/`通用`),`[待确认]` 只在 YAML 注释里、validator 看不见 →
  `pen_g - pen_p` 恒空,任何产出都过 → 起不到保护作用。
- 🟠 **`distinct_values` 把多选单元格当组合字符串**(`clients.py:153`,`[方向三,方向六]→'方向三 / 方向六'`)→
  报给 LLM 的是组合值而非各基础方向独立计数,把"拆组合"负担压回 LLM,与"确定性取数"初衷矛盾;
  只出现在组合里的稀有基础方向真实频次对 LLM 不可见。
- 🟡 **无 prompt caching**(全包无 `cache_control`)→ corpus 把全部历史 mapping 全文常驻、每次重发,
  实际成本显著高于 docs/16 §额度 预期(对比 librarian 已实现 caching)。
- 🟡 **超时链可能爆 `--max-time 220`**:全表 distinct 扫描 + `max_tokens=16000` LLM,大表(NRT 21 方向)可能超时,**且超时后草稿全丢、无断点续传**。
- 🟡 `max_tokens` 不一致(`call_anthropic` 默认 8000 vs `core.draft` 显式 16000)、`sample_n` 输入校验薄弱(非数字→非法 JSON→500)。
- 半成品:sync 侧多选拆解未实现(= §3.1 同一个洞,即使草稿正确,真导入多选行行为目前缺);`agent_runs` 记录/Streamlit UI 规划态。

> **本次审计已修复 PR #40 的 3 条 Codex review**(详见 §6 与 `docs/17` §7-0)。

---

## 4. 关键决策与走过的弯路

决策日志 D-001 ~ D-038(append-only)。最影响架构的几条:

- **D-003**:飞书"方向"单字段混 3–4 维 → 拆成 `content_format/target_audience/user_pain_point/product_focus/intent`
- **D-012 ⭐**:**按 intent 分轨训练**(流量帖 vs 产品直推规律不同,混训污染模型)
- **D-017/D-028 ⭐**:essence 标注**双模式物理隔离**防 label leakage
- **D-024 → D-038 ⭐**:集成 HTTP API → 双通道直插 → 通道 2 改 pull+馆员
- **D-026**:回流分级(飞书 notes 必回 / autowriter 只回负例 / ssll 跳过)

被否弯路(docs/99,R-001~R-012)最重要两条:
- **RAG 作主检索被否**:爆帖与趴帖字面相似度 >0.85,真实爆因在文案外(账号流量/时段/评论引爆)
- **单层 surface schema 被否**:6–12 个月失效,历史回标一致性会崩 →"取上得中"

---

## 5. 问题、风险与技术债(分级)

### 🔴 P0
1. **系统从未端到端真转一圈**:数据进库 + 通道 1 上架 1 条参考,但消费侧 Check 2 = 0
   (ssll/aw 没在生产消费过)。R-022 代码层确认解决,但生产实跑验证 = 0。
2. **GitHub Actions 连不上中转站 → daily-sync 当前红**:essence/curate 配了 key 就真跑、连不上网关。
   临时解:删 GitHub `ANTHROPIC_API_KEY` 回到 skip→绿;根治:essence/curate 搬 Railway。

### 🟠 P1
3. **tier_source 人工补录不持久**:`UPDATE ... tier_source='人工补录'` 会被下次飞书 ingest 覆盖回 `数值推断`,
   笔记又被闸挡。唯一持久正路:飞书源头"流量状态"列标"爆贴/参考"。
4. **sync 多选方向拆分未做**:`transform_row` 精确 `.get()`,多选组合匹配不上 → 丢 direction 字段。改生产 sync,单独仔细做。
5. **README 数据流图过期**(退役通道 2 仍标活跃)+ `v1.4/v1.5` 是否已上 prod 需核实。

### 🟡 其它
- Anthropic 预算无硬上限(靠 `--limit 50` 软上限);schema drift 靠人同步五处、无强制门禁;
  草稿 `sync_config=null` → daily cron 跳过该项目;librarian 缓存 prune 未实现 / 降级不记日志;
  onboarder eval `[待确认]` 断言失效 / 无 prompt caching;两把 key(`ANTHROPIC_API_KEY` vs `ONBOARDER_API_KEY`)别混。

---

## 6. PR 现状与交接

**唯一 open PR #40**(onboarder polish):CI 6 项全绿,mergeable clean。**阻塞 = 3 条 Codex P2 review**:

| review | 文件 | 问题 | 本次修法 |
|---|---|---|---|
| 备注非 tier 源 | `corpus.py` | 一刀切 `备注→_note_for_tier`;A/B 家族备注 tier 来自状态列时,会以合成键落 raw_extra,丢原列名可追溯性 | 条件化:仅 C 家族映 `_note_for_tier`,A/B 按原列名进 raw_extra |
| 观众分析不可解析 | `corpus.py` | 一刀切 `观众分析→_audience_raw`;`transform_row:348` 无条件消费、parse=None 即丢数据 | 条件化:仅 WTG 可解析格式映 `_audience_raw`,空/非该格式按原列名进 raw_extra |
| 无意图列强造 intent | `core.py` | `ff19982` 让无意图列时用 `intent_override`;`transform_row:310` 会按方向赋 intent = 无源造数据 | 改为 intent 留空(WTG 金标准 null),`intent_override` 只在有先例时人审拍板 |

> 核实依据:NRT_phase2/3 用 `intent_override` 但**同时有 intent 列**;WTG 无意图列且 intent 留空 ——
> "无列→造 intent_override"无先例。core.py 的 tier 段(50–52)本就正确,故 review 1 是 corpus-only 修复。

**交接路径**(docs/17 §7,按依赖+ROI):
0. ✅ 修 PR #40 的 3 条 review(本次完成)
1. essence/curate 搬 Railway(解 daily-sync 红 + 解锁三层标注)
2. 跑一次真实消费验证(运营标真爆款 + 触发 ssll/aw 写稿,看 Check 2 从 0→正)
3. sync 多选方向拆解
4. 改 README 数据流图 + 核实 v1.4/v1.5 上 prod
5. 草稿写 sync_config、librarian 缓存 prune、onboarder eval 断言修正、降级路径加日志

---

## 7. 总体评估

策略思考极成熟、工程执行扎实、但**尚未点火**。文档/决策质量顶尖(D-001~D-038 可追溯 + RISKS 登记 +
每个 PR 详尽 body + 专门交接文档),刻意避开 RAG/单层 schema 陷阱。核心矛盾不是"哪里写错",
而是"它从来没真转过一圈"。下一个里程碑不是写更多代码,而是**让它真转一圈**:
essence 搬 Railway → ssll/aw 真消费一次 → `check_flywheel_health` 的 Check 2 从 0 变正。

> 本审计为某一时点快照;后续以 `CURRENT_STATE.md` / `DECISIONS.md` / `RISKS.md` 的最新追加为准。
