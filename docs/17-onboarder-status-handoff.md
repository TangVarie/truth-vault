# 接表系统(onboarder)· 状态与决策交接

> 写于 2026-06-04,供**新会话 / 技术接手**续作。
> 接表 = 飞书投放表 → `mappings/<project>.yaml` 草稿(给策略 lead 审,人审 PR 才进库)。
> 设计文档见 [docs/16-onboarding-agent.md](16-onboarding-agent.md);代码在 `onboarder/`。

---

## TL;DR(30 秒)

- 接表系统**已端到端跑通**:GitHub 按钮 → Railway → 出草稿 PR(WTG 测试真跑 `HTTP 200` 成功)。
- 架构:**确定性取数 + 单次 Anthropic 调用**(非 agent);因 **GitHub Actions 连不上中转站**,LLM 调用放在 **Railway**,GitHub 只做触发 + git/PR。
- 目标是**齐全功能,不要半成品**。还差几步(见 §7 待办):PR#40 的 3 处修正 + 合 main、草稿写 sync_config、sync 多选拆分、essence/curate 搬 Railway。

---

## 1. 架构(怎么跑的)

```
GitHub「Run workflow」按钮(填 project_id / app_token / table_id)
   │  HTTPS,带 X-Onboarder-Key 对暗号
   ▼
Railway · onboarder 服务(onboarder/app.py, FastAPI /onboard)
   │  · ANTHROPIC_BASE_URL/KEY 调中转站(单次非流式)
   │  · FEISHU_APP_ID/SECRET 拉飞书:list_fields(权威列+选项) + N 行样本 + 全表 distinct
   │  · 读 mappings/*.yaml + docs/03 标准映射 + 词表(corpus)起草
   │  返回 {mapping_yaml, review_brief, errors, uncovered, pending, is_error}
   ▼
GitHub Action 写文件 → 推 onboarder/draft-<id> 分支 → 打印开 PR 链接(校验门:is_error 则 run 变红)
```

**为什么 LLM 放 Railway**:实测 GitHub Actions(海外 runner IP)**到中转站 TCP 连不通**(`connect=0`,网络层);Railway(与 librarian 同环境)连得上。见 §6。

核心代码:`onboarder/core.py:draft()`(取数+一次调用+校验,CLI 和端点共用);`clients.py:call_anthropic`(走中转站);`vocab.py`(受控词表+校验);`corpus.py`(语料);`eval_wtg.py`(对金标准回归)。

---

## 2. 已定决策

| 决策 | 内容 | 原因 |
|---|---|---|
| 不用 agent-sdk | 改 librarian 同款**单次 Anthropic 调用** | CLI+进程内 MCP 那条路太脆;任务本就是"取数→一次推理" |
| 部署方案 A | Railway 跑 LLM,GitHub 只触发+git/PR | GitHub 连不上中转站,Railway 连得上 |
| 方向多选 = B 风格 | 只建基础方向 + `sub_directions`,组合行由 sync 拆 | 干净好维护(但 sync 拆分待做,见 §7-A) |
| WTG 是测试表 | 有人工金标准 `mappings/WTG_phase1.yaml`;draft PR **不 merge** | 验证系统用,非真接表 |
| essence/curate | 暂休眠;**要齐全飞轮时搬 Railway** | GitHub 连不上网关 + 数据/消费侧未就绪 |

---

## 3. 当前状态(代码 / PR / 部署)

- **main**:onboarder 主体已并入(PR #38)。可用版本:Railway 端点 + GitHub 按钮 workflow(`.github/workflows/onboard-table.yml`)+ 探针(`gateway-probe.yml`)。
- **分支 `claude/youthful-wright-21rlG`**:领先 main **2 个 commit**(未进 main):
  - `ff19982` 没意图列别造 intent_mapping
  - `e7ee3d5` docs/03 标准字段映射喂进 corpus
  - 本交接文档(docs/17)也在这分支。
- **PR #38**:已 merge ✅
- **PR #39**:WTG 测试草稿 → **不 merge,用完关闭**(WTG 留金标准)
- **PR #40**:polish(intent+corpus)→ **有 3 条 Codex review 必须先修**(见 §7-0)再合
- **Railway**:onboarder 服务已部署、跑通(WTG 测试 200)。Config file 指 `/onboarder/railway.json`。
- **daily-sync**:🔴 红 —— `essence_sync`/`curate_sync` 失败(详见 §6)

---

## 4. 配置 / 密钥地图(**别再混**)

> 两种 key:`ANTHROPIC_API_KEY`=中转站 key(决定通道/group,503 跟它有关);`ONBOARDER_API_KEY`=GitHub↔Railway 对暗号(跟 LLM 无关)。

**🟩 Railway · onboarder 服务**(接表就靠它):
- `ANTHROPIC_BASE_URL` + `ANTHROPIC_API_KEY` ← **能跑通的那条通道**(tdyun.ai + 对的 key;别用 claude-kiro 组那把)
- `FEISHU_APP_ID` + `FEISHU_APP_SECRET`
- `ONBOARDER_API_KEY`(自定口令)
- 可选 `ONBOARDER_MODEL`(默认 claude-sonnet-4-6;若通道模型名不同就填它认的)

**⬛ GitHub repo secrets**:
- `ONBOARDER_URL`(Railway 域名)、`ONBOARDER_API_KEY`(=Railway 那个)
- `ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL`:**接表不用** —— 但现存着,导致 daily-sync 红(见 §6/§7);建议删或随 essence/curate 迁 Railway 一起解决

**🟦 别碰**:Railway · librarian 服务的变量(另一个独立 app)。

---

## 5. WTG 测试草稿质量(PR #39)

- 结构 **~95% 对金标准**:schema_family ✓、方向名(B 风格)✓、tier_extraction.source ✓、阈值存在 ✓、`[待确认]` 覆盖 ✓、校验 0 error / 0 漏列。
- 已知差距(`eval_wtg --against` 给的):4 列被塞 raw_extra(应是 typed):`爆帖置顶评论→pinned_comment`、`数据回收情况→data_quality_status`、`观众分析→_audience_raw`、`笔记状态→synthetic`。前 3 由 corpus 修复覆盖(§7-0 注意分家族条件);`笔记状态` 是 WTG 独有。
- 判断项待人审:`贴全面时代`(实为竞品**全棉时代**,agent 把"棉"看成"面")、阈值偏高(P99≈46 但设 100)、方向六少了 月子/差旅/经期 sub。

---

## 6. 踩过的坑(别再 debug)

1. **GitHub Actions 连不上中转站**:海外 runner IP → tdyun.ai,`curl connect=0` 超时(TCP 握不上手)。**网络/路由层,非应用层封禁**(网关方说不封 GitHub 也没用,SYN 被国际线路丢)。本机/Railway 能连。→ 所以 LLM 调用必须放 Railway。
2. **中转站 503 `no available channel for model X under group claude-kiro`**:你这把 **key 的分组**没有跑该模型的可用通道(kiro 转卖通道常挂)。**跟代码无关**;换一把别的组的 key、或换通道、或换通道认的模型名。
3. **中转站是 NewAPI**:Anthropic SDK 自动补 `/v1/messages`(对的;503≠404,路径没问题)。
4. **daily-sync 为何由绿变红**:`essence_sync`/`curate_sync` gate 在 `ANTHROPIC_API_KEY != ''`。之前 GitHub 没设这 key → 两步 **skip**(绿);后来设了 → 两步**真跑** → 连不上网关 → 红。**"之前能跑"= 被跳过,不是真成功。**

---

## 7. 待办 —— 到"齐全功能"的路径(用户明确:不要半成品)

### 0. 先修 PR #40 的 3 条 review,再合 main(否则给 Railway 喂了"太一刀切"的提示)
> ✅ **已修复(2026-06-04,本分支 `claude/tender-volta-B1jOg`)**:三条提示已条件化。核对 `transform_row` 真实行为确认:`_audience_raw` 在 `sync_feishu_notes_to_truth_vault.py:348` 无条件 `consumed`(parse=None 即丢数据);`_note_for_tier` 仅 `tier_source=="备注字段"` 才消费(否则落 `raw_extra` 合成键);`intent_override`(:310)对确定性方向直接赋 `note["intent"]`。另核实 NRT_phase2/3 用 `intent_override` 但**同时有 intent 列**,WTG 无意图列且 intent 留空 —— 故"无列→造 intent_override"无先例。改动见 `onboarder/core.py` intent 段 + `onboarder/corpus.py` STANDARD_FIELD_MAP(备注/观众分析/发布笔记 三行)。

Codex 指出我那两个 polish 的标准映射提示**没分家族/格式**,会带偏:
- **备注**:仅 **C 家族** tier 源(→`_note_for_tier`);**A/B 家族**通常只是运营备注 → 进 `project_specific_fields_to_raw_extra`(按原列名,保可追溯)。标准映射提示要**条件化**,别一刀切成 `_note_for_tier`。
- **观众分析**:仅 **WTG 那种可解析的半结构化文本** → `_audience_raw`;**空 / 非该格式(如 NUC)** → raw_extra。否则 `transform_row` 吃掉 `_audience_raw` 却 parse 出 None → 列既没解析也没留 raw_extra,**丢数据**。
- **intent**:没意图列时 **intent 留空**(金标准 WTG 就是 null)——别造 `intent_mapping`,**也别强行 `intent_override`**(否则 sync 会按方向给 intent 赋值,等于无源造数据)。当前 `ff19982` 的"改用 intent_override"**要改成"留空,除非项目有先例"**。
> 修完 → 合 main → Railway 自动重部署 → 真跑才用上这些修正。

### A. sync 多选方向拆分(改生产 sync,channel-1)
`scripts/sync_feishu_notes_to_truth_vault.py:transform_row` 对 `_direction_key(raw_dir)` 做**精确 `.get()`**:
- 多选组合(如「方向三 / 方向六」)匹配不上 → combo 行拿不到 direction 字段;
- 带 `sub_directions` 的方向,sync **跳过父级字段提升**,annotate pass 只拷 content_format/audience/pain/product_focus,**不拷 intent_override** → 方向三 conversion 丢。
→ 要加"拆多选 → 各基础方向分别套用"+ "决定多方向时各字段怎么合并(content_format 单值怎么取、audience 是否并集)"。**设计决策 + 生产代码,单独仔细做。**

### B. 草稿写 sync_config(小改进)
现在草稿 `sync_config.feishu_app_token/table_id = null` → daily cron 遍历 `mappings/*.yaml` 会**跳过**该项目。workflow 手上就有这俩值(用户输入)→ 让 onboarder/workflow 把它们**写进草稿 sync_config**。

### C. polish 合 main(= §7-0 修完后的合并动作)

### D. essence/curate 搬 Railway(齐全飞轮)
> 🟡 **代码已就绪(2026-06-04,本分支)· 待部署**:新增 `worker/` 服务(FastAPI,subprocess 跑现有
> `scripts/annotate_essence_pass.py` / `curate_flywheel_lessons.py`,不重写逻辑),`worker/railway.json` 就绪;
> `daily-sync.yml` 的 essence/curate 两步已改为 **curl 调 worker**、gate 在 `WORKER_URL != ''`。
> **剩部署动作**:Railway 新建第三个 service(Config file 指 `/worker/railway.json`)+ 配 env(见 `worker/README`),
> GitHub 加 secret `WORKER_URL`/`WORKER_API_KEY`。部署完 essence/curate 才真跑(prod 现状 0 标注 / 0 经验卡)。

essence(给笔记打 essence 层:情绪杠杆/原型/人群)+ curate(爆款→经验卡→喂 librarian 书架,供 autowriter/ssll 写稿借阅)。原因 GitHub 连不上网关跑不了 → 搬 Railway(像 onboarder/librarian)。

### E. daily-sync 变绿
> ✅ **根治路径已落地(代码侧)**:gate 从 `env.ANTHROPIC_API_KEY != ''` 改为 `env.WORKER_URL != ''`,
> 且 `ANTHROPIC_*`/`ESSENCE_MODEL` 已从 GitHub env 移除。**未配 `WORKER_URL` → essence/curate 优雅跳过(绿)**;
> 配了 worker → 真跑(LLM 在 Railway,GitHub 不再连网关,不会再因此变红)。配完 worker 后可删 GitHub 的 `ANTHROPIC_API_KEY`。

### F. 关闭 PR #39(测试用完)

---

## 8. 关键文件速查

| 路径 | 作用 |
|---|---|
| `onboarder/core.py` | `draft()` 核心 + SYSTEM_PROMPT(分工/词表/输出契约) |
| `onboarder/clients.py` | 飞书(REST,镜像 scripts FeishuClient)+ Anthropic(中转站)+ Supabase |
| `onboarder/vocab.py` | 受控词表闭集 + `validate_mapping`(词表 + D-021 列覆盖) |
| `onboarder/corpus.py` | 历史 mapping + 家族指纹 + `STANDARD_FIELD_MAP`(docs/03 标准映射) |
| `onboarder/app.py` | Railway FastAPI 端点 `/onboard`、`/health` |
| `onboarder/eval_wtg.py` | 对金标准结构回归 |
| `onboarder/railway.json` | Railway onboarder service 配置(Config file 指它) |
| `.github/workflows/onboard-table.yml` | 按钮 → 调 Railway → 推草稿分支 |
| `.github/workflows/gateway-probe.yml` | 一次性:从 GitHub 探中转站可达性 |
| `mappings/WTG_phase1.yaml` | WTG 人工金标准(eval 基准;别被测试草稿覆盖) |
| `docs/16-onboarding-agent.md` | 设计文档 |

---

## 给新会话的一句话起手

> "接着 `docs/17` 的待办做:先修 PR #40 的 3 条 review(备注/观众分析分家族、intent 留空)合 main,再做 sync 多选拆分(§7-A)、草稿写 sync_config(§7-B),最后把 essence/curate 搬 Railway(§7-D)。配置见 §4,坑见 §6。我要齐全功能。"
