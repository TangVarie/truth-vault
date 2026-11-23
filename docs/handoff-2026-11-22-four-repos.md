# 四库交接 · 2026-11-22

> 快照时间：**2026-11-22 约 10:30 UTC**。上一个会话（标题「多库联动进度评估」）到这里停手，由 owner 新开的会话接手**整个项目**。本文是接手入口：先读完本文，再读 [OPEN-ITEMS](../OPEN-ITEMS.md) 顶部、第 0 节、第 8 节。本文和更早的交接文档（[10-22 执行书](handoff-2026-10-22-next-owner.md)、[HANDOFF.md](../HANDOFF.md) 里 10-21 / 10-15 那几节、aw 和 Jev 的 HANDOFF.md）冲突时，以本文为准；任何「线上现在是什么」都要动手前重新核。11-23 约 02:30 UTC 补了一次：11-22 那晚首图是 0 篇，没有「用量拆开」那一行（6.1）；第二轮复审的改动也在这一版里。

## 0. 先记住：这个项目是四个库

四个都是 `TangVarie` 名下的**公开**仓库。少接一个，就会漏掉一段链路。

| 库 | 简称 | 管什么 | 默认分支（PR 开到这里） | 跑在哪 | 合并之后会发生什么 |
|---|---|---|---|---|---|
| [TangVarie/truth-vault](https://github.com/TangVarie/truth-vault) | TV | 数据库房：飞书投放表每晚同步进 Supabase；评论、essence、内容特征、首图问卷；闸一 / 二 / 三；经验卡书架；馆员；看板。**四个库共用的待办、决定、交接都在这里** | `main` | GitHub Actions 定时任务；Railway 三个服务（librarian、worker、onboarder）；Vercel 看板（`dashboard/`） | Railway 三个服务、Vercel 看板自动重新部署；定时任务只认 `main` 上的 workflow 文件 |
| [TangVarie/autowriter](https://github.com/TangVarie/autowriter) | aw | 写手用的写作台 deskcore（FastAPI + MCP）：发牌、借卡、存稿查重、拼交付稿、查规则、评论工具；每晚 tv-sync 把已发的帖对回写作台 | **`claude/xhs-content-workstation-BSEuH`**（远端**没有** `main`） | Railway：deskcore 服务；tv-sync 是同仓的另一个 cron 服务，`0 14 * * *` UTC | 写作台重新部署。改了协议（`deskcore/protocol.md` 或 skill 头）就要每个写手重导一次 skill |
| [TangVarie/JevforCoentent](https://github.com/TangVarie/JevforCoentent) | Jev | 判定服务：参考分、项目规则检查（`/judge_draft`、`/compile_rules`）、评论题；外部语料（TikHub 搜索 → 打标 → 写进 TV） | `main` | Railway 服务 `judge`；Actions：external-corpus 周一、周四 03:07 UTC（实际 10:40–11:30 才起跑） | **判定服务重启**，只改文档也一样（没配 watch paths）；config 里的 YAML 写坏了服务就起不来 |
| [TangVarie/linkcheck](https://github.com/TangVarie/linkcheck) | linkcheck | 已发帖巡查：链接还在不在、限流、评论数、置顶和第一页评论、负面词 / 竞品词，写回飞书巡查表；面板（加表、逐表参数、余额、日报、搜索可见试跑） | `main`（没有分支保护） | Railway：cron 服务（每 5 分钟 `queue && sweep`，Restart Policy 必须是 Never）+ 面板服务 | 两个 Railway 服务都重新部署，下一轮 cron 就是新代码在花钱 |

**一条主链**：飞书投放表 → TV 夜跑入库（事实、评论、essence、特征、首图）→ 经验卡书架 → 馆员把卡借给 aw → 写手在写作台（WorkBuddy 或 DSH 桌面插件）写稿 → aw 存档、查重、拼交付稿，调 Jev 出参考分和规则检查（**只提示，不挡交付**）→ 写手贴飞书 → aw 的 tv-sync 每晚把版本和人改过的地方对回来。linkcheck 在旁边巡查已发的帖，写回飞书；TV 夜跑再把这些列读进库（`truth_vault.comments` 里 `source` 以 `linkcheck_` 开头的是巡查看到的读者评论，D-155；口径在 [docs/09](09-system-integration.md) 的 linkcheck 一节）。

**四个库之间共用、改的时候要一起改的东西**

- 同一个 Supabase 项目 `kduysqedrclrfevrxiie`（schema `truth_vault` / `autowriter` / `public`）。TV、aw、Jev 都读写；linkcheck 不连库，状态全在飞书。
- 中转站切换：TV 根目录 `relay_failover.py`、aw 根目录 `relay_failover.py`、Jev 的 `judge/relay.py` 三份逐字相同，改就三个库一起改。
- 正则闸：Jev 的 `judge/rules.py` 照搬 aw 的 validator，两边 pattern 都限 300 字，用 Jev 的 `tests/test_regex_parity.py` 对拍。
- 题库：Jev 的 `banks/vendor/` 是 TV 题库和切片器的原样副本，`SHA256SUMS` 钉住，只能从 TV 整份重新 vendor。
- TikHub：Jev（Actions secret `TIKHUB_API_KEY`）和 linkcheck（Railway 变量）共用一个账户；**TV 里没有 TikHub 钥匙**。
- 合并闸门 `scripts/codex_gate.py` 在 TV，四个库合并都用它（第 4 节）。
- 待办只有一份：TV 的 `OPEN-ITEMS.md`（四个库统一）；决定只有一份：TV 的 `DECISIONS.md`。aw、Jev、linkcheck 里没有各自的待办清单。

## 1. 新会话怎么接上四个库

1. 对四个库逐个调用 `add_repo`（owner `TangVarie`；repo `truth-vault`、`autowriter`、`JevforCoentent`、`linkcheck`；要推代码就用 access `push`），按返回的命令克隆，再 `register_repo_root`。**四个都接上之前不要开始做事。** 建议的克隆位置：`/home/user/truth-vault`、`/home/user/autowriter`、`/home/user/jevforcoentent`、`/home/user/linkcheck`。
2. 每个库 `git fetch origin`，从**各自的默认分支**拉出你这个会话的开发分支（aw 从 `origin/claude/xhs-content-workstation-BSEuH` 拉，不是本地那条同名分支，本地那条可能很旧）。上一个会话的分支 `claude/zen-johnson-m2f14s` 在 aw、Jev、linkcheck 里已全部合进默认分支；TV 那条要等交接 PR TangVarie/truth-vault#303 合并。不用接着用它，也**不要往它推**。核法：`git diff origin/<默认分支>...origin/claude/zen-johnson-m2f14s`（**三个点**，应当为空）。两个点的写法在 aw、linkcheck 会列出一大串改动，那是默认分支后来又往前走了（aw#174–#176、linkcheck#87–#90），不是没合；`git log` 也会列出早已 squash 进去的旧提交，别被骗。TV 先看 #303 的状态：
   - 是 merged：squash 合并不挪合并基点，三个点只有在上一个会话把 main 合回 zen 之后才是空的（第 4 节第 8 步）。要是还列出 #303 那几个文件，就是合回那一步没做，内容已经在 main 上了，不用管。
   - 还开着：本文、`scripts/ci_local.py`、D-162 的「11-22 再补（owner）」都还不在 main 上，先从 `origin/claude/zen-johnson-m2f14s` 读，并告诉 owner。#303 不用改就照第 4 节第 4–9 步合掉（它是 draft：转 ready、等 Codex、`codex_gate.py` PASS、看 features-sync、squash），第 8 步不做；要改就照 D-153 的做法把改动搬到自己的开发分支新开 PR，#303 关掉时留一句指向新 PR。
3. 装本地环境，跑一遍各库的检查（第 5 节），确认起点是绿的。
4. 会话需要两个连接器：Supabase（只读用）、Vercel（看部署和日志）。GitHub 用 MCP 工具；本环境 `gh` 的 GraphQL 被代理拦了，要用 `gh api repos/...` 走 REST。
5. 把第 6.1 节首图那件事的提醒排上（`send_later`）。上一个会话排的提醒已经撤了；`list_triggers` 里另有三条已停用的「Re-check autowriter PR 174 / 175 / 176」，是别的会话的，别动。

## 2. 每个库先读什么

**TV**
1. `OPEN-ITEMS.md`：顶部横幅（最新在最上）、第 0 节「按时间」、第 8 节「你要做的」。规矩在开头：凡是「后做 / 等 X / owner 待定」的事，同一个 PR 里在这里加一行；关一行要有证据（查询、run id、PR 号），挪到「已关」，不删行。
2. `CURRENT_STATE.md` 的「2026-11-13 现状」一节（往里加行时，在标题括号里补一句「MM-DD 补…」）。
3. `DECISIONS.md`：只追加不修改；最新是 D-162，下一个号是 D-163；后续补充写成同一条下面的「**MM-DD 补（工程 / owner）**：」。
4. `docs/00-START-HERE.md` §2、§3、§6、§7。注意：§3.4、§7 第 1 条说「模型调用都在 Railway」已过时：D-100 起 essence 和书架策展从 GitHub runner 直接调中转站，只有特征层还走 Railway worker。
5. 首图：`docs/34-first-image-pass.md` 第 12、13 节（第 13 节是换 fi-v0.3 的步骤）。
6. 按需：`docs/29-lights-registry.md`（每盏灯谁看、多久看、红了谁管）、`docs/12-daily-sync-troubleshooting.md`、`scripts/README.md`、`docs/09-system-integration.md`。
7. `HANDOFF.md` 里只有「owner 定的规矩，接手照办」那一小节还有效，其余是 10 月的历史。那一小节和本文第 3 节冲突时以第 3 节为准，其中「密钥只在对话里给」已作废：不在对话里要密钥。

**aw**
1. `README.md`（四份 requirements 各管什么）。
2. `docs/deskcore.md`：设计和对接的唯一真源。§3.x 按时间排，最新到 §3.37 client_mark；§4 部署和环境变量表；§5 踩过的坑。
3. `docs/deskcore-runbook.md`：§6.5 协议升版怎么发（发版顺序见第 7 节）。注意 §1.2（说 019 / 020 没跑）和 §1.16（说回流闸默认关）已过时：019、020 都跑了，仓库根目录 `config.py` 里回流闸默认是开（`RETURN_GATE_ENFORCE_DEFAULT = "1"`，aw#163）。
4. `migrations/README.md`：每个迁移不跑会怎样的唯一真源。
5. `clients/dsh-plugin/README.md`、`clients/dsh-plugin-compat-021/README.md`、`clients/dsh-plugin-index/README.md`、`docs/dsh-pilot-step1.md`。
6. `HANDOFF.md` 停在 10-22，只有 11-17「客户端标记」那一行是新的；以本文为准。

**Jev**
1. `README.md`：所有环境变量、数据出境和暗题、`/compile_rules` 契约、备用中转站、外部语料怎么控量。注意它「三个仓库怎么接」那一节写的是 TV、aw、sanshengliubu，漏了 linkcheck。
2. `docs/cover-pilot-2026-11-18.md` 的「结果」一节（I-35 的最终结果）。`HANDOFF.md` 最上面那节写着「还没跑」，已过时，11-18 已经跑完。
3. `docs/comment-tools-rollout-2026-10-12.md` 开头 11-03 和 10-16 两节（评论线现行口径）；`docs/audit-fixes-2026-11-14.md`；`fixtures/README.md`；`docs/01-how-jev-is-used.md`。
4. `.github/workflows/external-corpus.yml`、`cover-pilot.yml` 里的中文注释就是操作说明。

**linkcheck**
1. `README.md`，尤其 §四「防止写坏表的五处设计」（必读）。
2. `.env.example`：所有环境变量和默认值的权威说明。
3. `docs/待验证清单.md`（⚠️ 是推断、✅ 是实测）、`docs/Railway上线手册.md`（§5.4 cron、§5.6b 面板）、`docs/面板.md`、`docs/表结构.md`、`docs/搜索可见试跑.md`、`docs/日报与工作台.md`、`docs/运营手册.md`。
4. 仓库没有 HANDOFF.md，也没有 CLAUDE.md；自带一个 skill `.claude/skills/unslop`（改面板 UI 时用）。

## 3. owner 定的规矩（长期有效，接手照办）

**怎么做决定**

- owner 10-16：「所有决定你帮我判断」（D-119）。工程能判的自己判，判完在 DECISIONS 记一条，写清是工程定的、owner 可以否决。
- 只有这几类要 owner 点头：**花钱**的（模型调用超出已批的数、TikHub、任何付费服务，哪怕几毛钱）；**对外**的（发消息、找运营 / 写手 / 客户）；**不可逆**的（删表、删数据、停服务、删一次性认领 tag）；**换写手用的模型**。问的时候给建议、给钱数、给不做的代价，一次问完。
- owner 已经拍过板的不再问（例：W-42 不要再问）。
- 写手、运营不加活：写作台永远不挡交付；不让写手「归档」；出了问题不怪写手。要写手重导 skill 的协议改动，只有值得每个写手重装一次才做，小改攒着（客户端中性的那批协议措辞就在攒）。
- 跟 owner 汇报用中文、说人话：先说结论，再说要 owner 做什么；没有就明说「你不用做什么」。不用内部缩写和英文术语糊弄过去。

**四个库都是公开的**

- 不进 GitHub（代码、测试、文档、提交信息、PR、评论、Actions 日志和产物都算）：密钥的值、客户的帖子 / 评论原文、真实昵称、竞品名、写手 user_id、完整 UUID、客户规则的原文、稿子正文、表的 app_token 或带 token 的链接、余额绝对值。只写计数、写死的词、合成的例子。
- 密钥只按名字、长度、末 4 位提，不复述值；**不在对话里向 owner 要密钥**，缺钥匙就用环境的凭据配置让 owner 自己填。
- 不记、不存、不回显看板的查看链接、Vercel 分享链接、`_vercel_share` 令牌。
- 提交和 PR：只用会话给的署名 trailer；标题、正文、代码注释里不写模型名。

**数据库**

- Supabase：会话里的工具**只用 SELECT**（`note_feature_answers` 按 `subject_id` 查，不是 `note_id`）。要写库就写成 SQL 文件（一份迁移一个文件，整份可重跑，尽量全是加法），对话里也贴一份，owner 自己在 SQL editor 跑；跑完工程只读回查。
- 写生产库先建备份表；备份表不删（D-136）。隔离表只有人能改（D-053）。不伪造人工标注、`accepted_by`；AI 参考答案不能标成人工金标。
- 代码要在「SQL 还没跑」的库上也能跑（缺表缺列就跳过、报一行），不加必填的环境变量（D-153）。

**合并和部署**

- 每个 PR 都过 Codex 和 CI（第 4 节）。Codex 回「额度用完」就别合，告诉 owner。
- **TV 合并前先看当天的 features-sync：在排队或在跑就不合。** 它最长 240 分钟一直在用 Railway worker，这时合进 main 会让 worker 半路重新部署（`worker/railway.json` 没有 watch paths）。定时是 12:47 UTC，可 GitHub 排队漂移之后，11 月实际都在约 17:50–22:45 UTC 起跑（11-09 跑到 23:20）。以前会话间约定的「12:47–16:47 UTC 不合」照旧守，但它挡不住漂移后的那一趟：当天那趟没跑完之前，约 16:00–23:30 UTC 都别合。核法分两条（定时那一趟起跑之前 API 里根本没有它，「没在排队」说明不了什么；手动点过的一趟也会冒充「今天的」）：
  - `curl -s 'https://api.github.com/repos/TangVarie/truth-vault/actions/workflows/features-sync.yml/runs?event=schedule&per_page=1'`：最新的定时那一趟要是**今天（UTC）的**、`status` 是 `completed`。不是今天的，16:00–23:30 UTC 都不合。
  - `curl -s 'https://api.github.com/repos/TangVarie/truth-vault/actions/workflows/features-sync.yml/runs?per_page=3'`：不管哪种触发，都不能有 `queued` 或 `in_progress`。
- 不 force-push；不 rebase 别人的分支；只往会话指定的开发分支推。
- 不让 Codex 往 `codex/audit-fixes-20261114` 这类分支推代码；Jev 的 `codex/audit-fixes-20261114`（#34，已关）不要复活，它会把 owner 否决过的 hard_ambiguous 加回来（owner 11-04 定的是宁严勿松）。
- Jev、aw、linkcheck 合进默认分支都会重启 Railway 服务；纯文档改动不值得单独为它重启，攒到下一次有代码的 PR 一起上。
- 实质性的改动用多路并行的 workflow 做，合并前做一轮对抗复审（owner 叫它 ultracode）。

## 4. 合并流程（四个库一样）

1. 推到开发分支，开 **draft** PR，订阅 PR 动态（`subscribe_pr_activity`）。
2. 在 PR 上评论 `@codex review`（评论结尾带 Claude Code 的署名尾巴）。Codex 机器人是 `chatgpt-codex-connector[bot]`。
3. 有意见：修、在那条 thread 上回、推、再 `@codex review`。可选的意见回一句、能顺手改就带进下一次推送。
4. Codex 干净、CI 绿：把 PR 转成 ready（`update_pull_request` draft=false）。转 ready 会触发 Codex 再审一次（「Draft marked ready」），**等它审完**。
5. 在 TV 的克隆里跑：`python3 scripts/codex_gate.py TangVarie/<repo> <PR号>`。输出 `PASS`（退出码 0）才行；`FINDINGS`（1）要修；`WAIT`（2）是还没审完、head 变了、或者读不到，**WAIT 不算过**。它用不带登录的 curl 读公开仓（每小时 60 次）。
6. 再核：CI 在当前 head 上全绿、没有未解决的 review thread、没有冲突。
7. squash 合并：带 `expectedHeadSha`，并且**显式给 `commit_message`**（不给的话，开发分支上的旧提交会全被塞进合并信息）。TV 先确认当天的 features-sync 没在排队或在跑（第 3 节）。
8. 取消订阅；把默认分支合回开发分支并推（`git fetch origin <默认分支> && git merge --no-edit origin/<默认分支> && git push`）。
9. 合完核部署：Railway 每次部署都会在 GitHub 留一条 deployment（creator `railway-app[bot]`，environment 是 ` / production`，前面有个空格）。不带登录就能查（和 codex_gate 共用每小时 60 次）：`curl -s 'https://api.github.com/repos/TangVarie/<repo>/deployments?environment=%20%2F%20production&per_page=5'`，找 `sha` 等于合并提交的那条，再读它的 `statuses_url`，要有 `success`。四个库都这么核。另外：
   - aw 再核 `https://autowriter-production.up.railway.app/health` 的 `build.commit`（合并提交前 12 位）和 `build.protocol_version`。
   - TV 一次合并只有一条 Railway deployment，librarian、worker、onboarder 分不开；它们的 `/health` 不报提交号（librarian 是 `https://truth-vault-production.up.railway.app/health`）。看板用 Vercel 连接器看 production 部署（TV 的 deployments 列表里也混着 `vercel[bot]` 的 Preview / Production，所以要带 environment 过滤）。
   - Jev 的 `/health`（`https://judge-production-601c.up.railway.app/health`，**要带 `-601c`**，不带的是另一个服务）只证明服务起来了：`version` 一直是 0.1.0，`policy_sha256` 只在改了 `config/data_policy.yaml` 时才变。
   - linkcheck 免口令的只有面板的 `/healthz`（回 `ok`）。会话没有 Railway 和飞书的权限，看不到 cron 日志；动了花钱路径的 PR，合之前和 owner 约好由 owner 在 Railway 看下一轮 cron。

## 5. 本地环境和检查命令

四个库 CI 都是 Python 3.11；本机默认 3.13 也能跑绿，但别用 3.12 以后才有的语法；要和 CI 完全一致就用 `/usr/bin/python3.11`（本机有 `uv`）。每个库各建一个 venv。上一个会话的 venv 和草稿目录不会带过来。

**TV**（11-22 实跑：python 108/108、yaml 4/4 是 `scripts/ci_local.py` 在本 PR 上跑的；sql 60/60 是在 7312ede 上手动照 sql job 跑的）
- 环境：`pip install -r scripts/requirements.lock pyyaml fastapi 'httpx<0.28' starlette uvicorn`（`scripts/requirements-first-image.txt` 只给两个首图 workflow 用）。
- 照 CI 跑一遍：`python scripts/ci_local.py <TV 的 git 克隆> [--job python|yaml] [--out 结果.json]`。必须是 git 克隆（`check_gate1_review.py` 要 `git check-ignore`），不能是 `git archive` 出来的目录。
- sql job 要一个临时的 Postgres 16（`/usr/lib/postgresql/16/bin`），数据库名必须是 `tv_ci`（`check_first_image_pg.py` 等只认 `tv_ci` / `tv_repair` / `tv_full_ci`）；`PGHOST=localhost PGPORT=5433 PGUSER=postgres PGPASSWORD=postgres PGDATABASE=tv_ci`，从仓库根目录依次跑 ci.yml 里 `sql` job 的每个 `run:`（跳过 apt-get）。先跑 `scripts/bootstrap_ci_supabase_roles.sql`，每份 `schemas/*.sql` 跑两次证明可重跑。
- 单项：`python3 scripts/check_system_map.py`、`python3 scripts/check_codex_gate.py`、`cd scripts && python3 check_first_image_pass.py`（10 节）。
- 看板：`cd dashboard && npm ci && npm run typecheck && npm run test:check && node scripts/check-public-wording.mjs --source-only`（完整构建要拉 Google Fonts，离线会失败；ci.yml 里没有看板的 job）。

**aw**（11-22 在默认分支 `ef7d531` 上、Python 3.11、装全依赖实跑：5027 passed / 1 skipped / 7 xfailed；唯一的 skip 是 `tests/test_generation_service.py` 在浅克隆里取不到旧提交）
- 环境：`pip install -r requirements.lock -r requirements-dev.txt -r deskcore/requirements.txt httpx`。不用设 PYTHONPATH，`tests/conftest.py` 会处理。要是跑出来约 4764 passed / 34 skipped、skip 原因是 could not import fastapi / mcp，就是没装 `deskcore/requirements.txt`；CI 第二遍装全之后，日志里出现 "could not import" 会判红。
- `python -m pytest tests/ -q -ra`；`python -m deskcore.cli selftest`；`python -m deskcore.cli sync-skill --check`（要输出协议一致，现在是 `6f23eba491fd`）；`python3.11 -m compileall -q app.py *.py deskcore/`。
- Node（本机 v22，不用装依赖）：`node --test clients/dsh-plugin/test/*.test.js`、`clients/dsh-plugin-compat-021/test/*.test.js`、`clients/dsh-plugin-index/test/*.test.js`（最后这组要完整 git 历史）。
- `tests/sql_parity_check.py` 要活的 Postgres，CI 单独跑。

**Jev**（11-22 在 main 上实跑：1045 passed）
- `pip install -r requirements.txt pytest && sha256sum -c banks/vendor/SHA256SUMS && python -m pytest -q && python -m py_compile scripts/*.py judge/*.py`。
- 本地起服务：`JUDGE_MOCK=1 JUDGE_ALLOW_ANONYMOUS=1 uvicorn judge.api:app --port 8080`（mock 下写库请求一律拒）。
- 不花钱的演练：`python3 scripts/external_corpus.py --dry-run`；cover pilot 的 `rehearse` 模式。

**linkcheck**（11-22 在 main 上实跑：2408 passed）
- 只用标准库，不用 pip install（`requirements.txt` 故意是空的，Railway 靠它认 Python，别删）。
- `python3 -m unittest discover -s tests -t .`；`python3 -m compileall -q cli.py xhsearch tools tests`。PATH 里要有 node（`/opt/node22/bin`），否则跳过 12 个浏览器脚本检查。建议 `env -i PATH=/opt/node22/bin:/usr/bin:/bin HOME=<草稿目录> python3 -m unittest ...`，免得本机的 FEISHU_ / TIKHUB_ 变量串进来。
- 测试输出里的「❌ .env 里有看不懂的行」之类是测试故意造的，不算失败。
- 不花钱的命令：`doctor`、`estimate`、`search-trial --dry-run`、`search-trial --report-only`。花钱的：`sweep`、`queue`、`row`（`row` 无视冷却）、`search-trial` 真跑、`tools/probe_channel.py`。本地没有 `.env`，也不要建。

## 6. 正在做的事和要按时做的事

这一节是 11-22 的快照，之后以 OPEN-ITEMS 为准。条目号（I- / W- / J- / G- / L- / F- / S- / AU-）都在 OPEN-ITEMS 里。

### 6.1 从 11-23 晚起：首图换 fi-v0.3（I-38、D-162；owner 11-22 已同意，最多约 3.5 元）

11-22 那晚（run 45071004146）是 0 篇、0 次调用，没有「用量拆开」那一行。下面说的「这一晚」都指从 11-23 起第一个有这一行的晚上。

- **现状**：攒证据攒到「说了没有字又抄出了字」6 篇，都是同一个项目的随手拍产品照；记了 `packaging_like` 的 3 篇全是纯英文（多半是包装上的英文名）。owner 11-22 回「同意」，重问的钱最多约 3.5 元。
- **第 1 步（每晚读）**：First image sync（cron `37 15 * * *`，实际 21:05–23:50 UTC 才起跑，11-16 是 23:49）从 TV#302 合并起把输入、输出 token 分开记。读它的 Summary：`status`、`partial_void`、`no_text_void`（含 `script:*`、`packaging_like:*`）和新的「用量拆开」那一行。提醒自己排（`send_later`，约 23:50 UTC）；醒来时当晚那一趟还没跑完，就再排 60 分钟后看，**别手动点**（手动真跑另有一份每晚上限，会多花钱）。
  - **为什么贵还不知道**：11-20 那晚每次调用的输入当量约 5,388 token，前几晚约 1,500，图一样大（768×1024）。输入当量 = 输入 + 5×输出，输入涨和输出涨都会让它变大，光看总数分不出来。11-09 有过先例：代码和模型都没变，中转站每次调用记的输入 token 大了约 5 倍（OPEN-ITEMS S-14：OKMAN essence 约 9.9k，11-08 约 1.7k），缓存关着却记了 cache_write / cache_read，输出照旧约 640，结论是中转站那边变了。首图 Summary 的「输入」已经把 cache_write、cache_read 加进去了（`scripts/first_image.py` 的 settle），看不出缓存那部分。
  - **和别的任务比**：拿 daily-sync 的 job 日志，essence 看 `Done:` 行里的 `prompt_cache`（calls / input / cache_write / cache_read / output），遮名字看「用量: 调用 … 输入 … 输出」那一行；同一个项目按每次调用比 11-08～11-21 这几晚。essence 走了备用站的那几晚每次只记约 1 个输入 token，不能拿来比：看同一行 `Done:` 里的 `relay`，`backup_ok` 大于 0 就是有调用走了备用站（`relay summary:` 那一行不带 `relay: ` 前缀，进不了 job 日志，搜不到，见 docs/12 §8）。遮名字走备用站时用量照常记全，可以比（S-14）。
  - **要是每次调用的输出变得很长，或者输入涨了、而 essence / 遮名字每次调用的输入也一起涨了，先用中文告诉 owner，再换。**
  - **可能读不到**：没有新帖的晚上（11-21、11-22 都是 0 次调用）Summary 里是「这一晚要做的帖：0 篇」，没有「用量拆开」那一行；调用了但中转站一次用量都没回报（「没拿到用量、按预留记的」次数等于调用次数）也没有这一行。那不等于「没变贵」：别开换版 PR（第 2 步只读的 SELECT 可以先做，但合换版 PR 之前要再跑一遍计数和配对那两条：中间几晚新做的帖也是 fi-v0.2，重问会把它们删掉），提醒顺延到下一晚约 23:50 UTC，等第一个有这一行的晚上再判。手动点一趟也没用：手动拿到的候选和定时那一趟一样（经验卡的帖、11-16 以后入库还没做的、首图换了的、题库版本不同的、到了重试时间的）。从 11-22 算起连着三晚都读不到（也就是 11-24 那晚还没有），就用中文告诉 owner，建议换上之后看第一晚的「用量拆开」（每晚 token 上限写死在代码里，超了当晚就停）。
- **第 2 步**：照 `docs/34` 第 13 节先只读：SELECT 记下 fi-v0.2 闭集答案的计数（重问会删掉旧的行，之后就查不到了）；数 `note_first_image` 里 `bank_version='fi-v0.2'` 做完了几篇；按这个数重算调用次数和钱（11-22 的数：72 篇、462 次调用，最多 504）。`docs/34` 第 12、13 节里写的「超过约 0.84 元先问」是 11-18 的线，已被 D-162「11-22 再补（owner）」换成约 3.5 元。
  - 再按篇存一份配对：D-162 换版后要比「同一批说了没有字的封面」前后中了几篇，重问删掉 fi-v0.2 的行之后就拼不回来了。只读查 `truth_vault.note_feature_answers` 里 `run_tag = 'img-primary' and bank_version = 'fi-v0.2'` 的 `img_text_amount`（答案是 `无效:inconsistent:no_text_but_transcribed` 就是中了第一条）和 `img_main_text`（只看有没有答案、无效原因，**抄下来的字不查**），按 `subject_id` 排好。结果不进仓、不进日志（完整 note_id 也不进）；草稿目录不跨会话，判的时候已是好几晚以后，所以至少留在会话对话里；要更稳就写一份 `create table truth_vault.backup_fi_v02_text_pairs_<YYYYMMDD> as …` 的 SQL 给 owner 在合并换版 PR 之前跑（照已有的备份表惯例，判完再说删不删）。
- **第 3 步**：没超过约 3.5 元就开换版 PR：`scripts/first_image_pass.py` 的 `BANK_PATH` 指到 `prompts/first_image_questions_v0_3.yaml`、`BANK_VERSION` 改成 `fi-v0.3`（两行一起改）；`scripts/check_first_image_pass.py` 第 1、3、7、9、10 节；`scripts/check_first_image_pg.py` B 段两处；`docs/34` 第 3、6 节的表；顺手把 `docs/34` 第 13 节里 0.84 元那句改成指向 D-162 的 3.5 元。不用跑 SQL。合并前先确认 features-sync 没在排队或在跑（第 3 节）。超过约 3.5 元就带着新的数回去问 owner。
- **换上之后**：每晚两道上限，40 张图和 750,000 输入当量 token（`NIGHTLY_MAX_WEIGHTED`，约 0.97 元），先到哪道停哪道；一张图开始之前要放得下它 7 次调用的预留（约 75,000，`PassBudget.take_image`），所以已花到约 675,000 就不再开新图。按前几晚每次约 1,500，40 张那道先到，72 篇分 2 晚；按 11-20 每次约 5,388，token 那道先到，一晚只做得了约 18 张，462 次调用要约 4 晚。要几晚取两者里大的那个：调用数 × 每次调用输入当量 ÷ 约 675,000，和篇数 ÷ 40，都往上取整，再加上这几晚的新帖；调用数、篇数用第 2 步数的，每次的当量用第 1 步读到的。写进换版 PR 和 I-38。按 D-162 判改没改好：同一批说了没有字的封面里第一条规则还中几篇、第二条规则涨没涨（涨了就退回）；要等最后一晚做完才能比。连带：写作台的封面参考那一句（aw#171，deskcore.md §3.36）读 `v_first_image_features`，重问完之前 fi-v0.2 的行读出来是 `usable = false`，那一句这几晚一直没有。
- 每晚的计数攒着，在下一个文档 PR 里记进 I-38。

### 6.2 交接时还开着、不是上一个会话开的 PR：四个「审计加固」

11-22 05:46 UTC 用 owner 的账号在四个库各开了一个，分支都是 `audit/hardening-2026-11-21`，标题都是「Audit hardening 11-21」。交接时四个都是 CI 绿、Codex 没意见、没有冲突、没合并。谁在推它们不知道；OPEN-ITEMS 和 DECISIONS 里都还没有记录。

- [TangVarie/truth-vault#301](https://github.com/TangVarie/truth-vault/pull/301)：馆员回流闸的刷新改成有界等待、加锁；worker 校验项目参数；飞书媒体 401 重试；评论父子行的写入顺序；日志脱敏；看板登录表单坏了回 400；新加的 `scripts/check_audit_hardening.py` **没接进 ci.yml**。合并会让 Railway 的 librarian、worker 和 Vercel 看板重新部署；它也改了 GitHub 夜跑直接从 main 跑的脚本，下一趟就是新代码：daily-sync 的 essence 写回（`annotate_essence_pass.py`：写库异常从只接 RuntimeError 改成全接，只跳这一篇、记 systemic，没加重试。这正是 OPEN-ITEMS S-14 ① 记着「只盯、先不修」的那处，合之前按 S-14 ① 原来的打算对一下，合了在 S-14 记一笔）、评论父子行分批（`sync_comments_from_raw_extra.py`）、遮名字的日志（`mask_external_names.py`）、首图下载（`feishu_media.py`：401 换 token 重试一次，`first_image_pass.py` 直接调它）。这些不动提示词和 token 记账，但最好等 6.1 那一晚的首图读完再合，免得那一晚的下载计数混进新代码。合完除了部署，再看下一趟 daily-sync（essence 的 `Done:` 行、comments 那一步）和 First image sync。回流闸那一改的后果：馆员每次重启后第一次读闸要是超过 4 秒，那一次借卡不过回流闸（D-156 默认开），`read_errors` 还会加一；合完等写作台借过一次卡，看馆员 `/health` 的 `select.return_gate`（`read_ok`、`read_errors`）。
- [TangVarie/autowriter#177](https://github.com/TangVarie/autowriter/pull/177)：MCP `allowed_origins`、日志里屏蔽 `DESKCORE_API_KEY`、`DESKCORE_VIEW_SECRET` 和 `DESKCORE_KEYS` 里的每一把钥匙、客户端加锁、UTC 排序、馆员连接和读取分开超时。`allowed_origins` 那一改线上不起作用：`DESKCORE_ALLOWED_HOSTS` 没配（`/health` 回 `mcp_allowed_hosts` 是「不校验」），MCP 的 Host / Origin 校验整个关着；就算以后配上，这一改也只会多放行，挡不住写手。真正会变的：`/health` 的 `librarian.configured` 要 `LIBRARIAN_URL` 和 `LIBRARIAN_API_KEY` 都配了才是 true（合并后核一眼还是不是 true）；馆员连接超时封顶 3 秒；比 `extracted_at` 改用 UTC 时间。不动协议，没有迁移。
- [TangVarie/JevforCoentent#40](https://github.com/TangVarie/JevforCoentent/pull/40)：行为会变：未知的 `subject_type` 回 422（允许 note、comment、external_note、aw_version、ssll_sample）；hard_rules 里写了暗题题号回 422；模板填充改成单遍替换；修改单定义的措辞变了；判定那一步（`apply_evidence`）不认非 dict 的答案、bool 选项和非有限或 bool 的概率；`interpret()` 的 noul 判断改了；内部 MCP 传 `banks=[]` 不再自动换默认题库，`comment_repair_plan_for` 的 `passed` 也改了。合并会重启判定服务。
- [TangVarie/linkcheck#91](https://github.com/TangVarie/linkcheck/pull/91)：动了判定和花钱的路径：熔断作废时 STATUS_OK 的行也清掉耦合列和蓝词账；TikHub 小红书详情只有 `data==[]` 或 `note_list==[]` 才判失效，形状不对改判传输错误、交给备胎；余额拒收 bool / NaN / Inf；试跑租约只在 `kind==run` 时算自己的；面板 `/api/queue` 同时校验表和 base。合并后下一轮 cron 就是新代码在花钱。

**建议的做法**（照 D-153 的先例：外面推来的审查分支，合并前逐条独立复核，和 owner 定过的规矩冲突的拿掉）：每个 PR 读 diff、在本地跑全量检查、对照第 3 节的规矩和本节点到的风险。

- 这四条分支不是本会话的：按第 3 节，不往 `audit/hardening-2026-11-21` 推，也不让 Codex 往上推。
- **照原样合的**：它们不是 draft，交接时 `codex_gate.py` 四个都是 PASS，走第 4 节第 5–7 步和第 9 步（要收 PR 动态就先订阅，合完取消；第 8 步的合回、推送不做，分支不是本会话的。TV 先确认 features-sync 没在跑；aw、Jev 避开写手在用的北京白天；linkcheck 先和 owner 约好看下一轮 cron）。head 变了才要再 `@codex review`。
- **要拿掉或改一处的**：照 D-153 的实际做法（TV#282 `codex/audit-fixes-20261114` 关掉不合，复核改好的版本从 Claude 自己的开发分支开 TV#283 合进去），把要留的改动搬到自己的开发分支，新开 PR，走第 4 节全流程；新 PR 正文写清从哪个 PR 来、留了什么、拿掉了什么、为什么；原 PR 关掉时留一句指向新 PR。
- 合完在 TV 的 DECISIONS 记一条（跨仓的决定都记在 TV），写上原 PR 和新 PR 的号。四个 PR 之间有没有部署顺序要求还没核（推测没有）。

**最近别的会话合过的**：aw#174–#176（DSH 插件给 Intel Mac 的 0.2.1 兼容版，真机上的复测在等 owner）、linkcheck#87–#90（处置底稿导出、面板按 BYWOOD 设计系统 v6.1 / v6.3 换样式）。动 DSH 插件或 linkcheck 面板之前，先看这两条线有没有新的 PR，别撞上。

### 6.3 已经过期、还没做的读数（工程自己做，做完把结果告诉 owner，不用 owner 拍板）

- **11-20 那一行**（OPEN-ITEMS 第 0 节）：L-07（写作台第二批上线满四周，判接住率走向，按三支照实报：在动 / 不动且是写作台稿改的 / 不动且在别处写的；只拿北京日同口径的周比，换版之后的周单独标；docs/32 §4）；J-15 软规则标定（剔掉 11-11 那 15 行误报，加 11-12 硬规则命中的 SQL 仿算，记着 11-13 结尾规则改过，W-56）；W-26（按项目看稿长、段数，定要不要重议「按段判」）；AU-F13（patterns 臂里 `flywheel_patterns_shown` 为 null 的批占多少）；W-53 排在标定之后。取数时按 `params.client_mark` 把 owner 自己在 DSH 上试的批次分开（owner 说过 DSH 先只有 owner 自己在试；deskcore.md §3.37）。
- **11-16 周一周检**一项结果都没进清单：W-42、W-51、F-14、L-03、W-33、AU-F07、I-27、S-14、F-04 的 `select_ms`、G-03 每周进度、D-152 的 `/skill-versions` 和两项重数、W-56。原因：那次定时检查 11-16 跑完了，但推分支被拒（403：那个定时任务的环境里 truth-vault 没有写权限），结果只发到了 owner 的通知里。
- **合并后「第一晚」没收尾的**：D-155 / v1_27（owner 11-16 跑了）的 ②③⑤：`source` 分布、`v_note_observations`、verify 那几条；D-154 第一晚：馆员 `/health` 的 `select.vanished`、daily-sync 的 retract summary。`select.*` 是进程里的计数，TV 每次合并都会重启馆员、清成 null，写作台借一次卡才重新读出来；`long_gone` / `in_grace` 也可以直接只读查 `truth_vault.v_notes_vanished`。
- **写作台下一场**那几行（第 0 节）：旧版 skill 还在不在用（不用 key：用 Supabase 只读跑 aw `docs/deskcore.md` §3.8 末尾注释为「写手手上的 skill」的那条 SQL，`autowriter.batch_metrics` 里 tool_call 行的 `meta->>'skill'` 按天数，每次调用落一行，重新部署不清零；「存档那一行的三小块」那条里的 `skill_versions` 只是存档那一刻对进程内 24 小时计数拍的快照，和 `/skill-versions` 同源，部署后清零，只作参考。两个数的都是调用或「身份 × 版本」，D-136 之后大家共用一个团队身份，**分不出还剩几个写手没重导**，只能说旧版最近还有没有人在用。不用去要钥匙）；「查了重没发牌」「查了重没存」的重数；W-56 结尾那条规则重编了没有；W-45、W-33、W-28、W-07、W-38。

### 6.4 在等 owner 或运营的（照 OPEN-ITEMS 第 8 节，别重复问）

- 写手重导 skill（协议 `6f23eba491fd`，D-152）：owner 让写手说一次「更新技能/bywood-writing-desk」再开新对话；导没导完工程用上面「写手手上的 skill」那条 SQL 只读看旧版最近还有没有人在用（分不出人数，见 6.3）。
- W-45：要 owner 去问写手开场有没有看到「这个项目现在怎么样」那一句。W-57：owner 不说就不动。
- I-32 搜索可见试跑（linkcheck 面板上点）：第 0 步是 Railway 面板服务的变量里加 TikHub 钥匙（做没做未核）；运营在项目表 `搜索关键词` 列填词；owner 先空跑，再跑第一轮（最多 ¥3.24），总上限 ¥20。还没有任何结果。
- I-26：运营给西屋911gt 在 linkcheck 登记表填「蓝词排除词」；填完之后的核对是工程的事。
- DSH 客户端标记（aw deskcore.md §3.37）：owner 下次在 DSH 里用写作台时，在测试项目上新开一场、调一次 `open_project`，工程再跑 §3.37 的第四条 SQL。认出来不是 `dsh_plugin` 就改 `deskcore/clientmark.py`，历史用第五条 SQL 的 CASE 重读，不回写库。
- I-35（全量封面约 16 元，还要在 TV 加 TikHub 钥匙）、I-36、I-37：都先放着，等经验卡的封面那一行真要做时再带着数问 owner。
- F-18：闸二判定规则改不改，owner 在 2027-01-02 前定；工程先在只读的一趟上比出哪些结论会动。
- aw 迁移 021、022：会话没有库的 service_role 凭据，`python -m deskcore.cli doctor` 跑不了，也不要去要钥匙。用 Supabase 连接器只读查：021 的函数 `select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'autowriter' and p.proname = 'deskcore_save_style_cas';`、021 的触发器 `select count(*) from pg_trigger where tgrelid = 'autowriter.user_calibration_notes'::regclass and tgname = 'deskcore_user_calib_updated_at' and not tgisinternal;`、022 `select count(*) from information_schema.columns where table_schema = 'autowriter' and table_name = 'draft_snapshots' and column_name = 'lesson_exposure';`。是 0 就是没跑，把 `migrations/021_style_distillation_cas.sql` / `022_lesson_exposure.sql` 给 owner 在 SQL editor 跑（不跑也不坏），跑完再用同样的 SELECT 回查。
- 每周一的定时检查推不了 TV（它的环境里 truth-vault 没有写权限），也没挂 Supabase / GitHub 连接器，依赖线上的条目它都会写「未核」。owner 知道，不用再问。要看它写了什么：`list_triggers` 找「OPEN-ITEMS weekly review」的 `last_run.session_id`，再用 `list_events`（kinds `assistant`、`result`）读它最后的回复，按需补进 OPEN-ITEMS。

### 6.5 定了日子的

| 时间（UTC） | 事 |
|---|---|
| 每晚（约 21–23 点） | 首图夜跑；11-22 那晚 0 篇，从 11-23 起等第一个有「用量拆开」的晚上（6.1） |
| 每周一 01:47 | 定时任务「OPEN-ITEMS weekly review」（每次开新会话；提示词 11-22 已改成四个库）。11-23 那次跑的时候 #303 还没合，main 上没有本文；它写了什么照 6.4 最后一条读 |
| 11-23 周一、11-26 周四（实际约 10:40–11:30） | Jev external-corpus：看 job 状态、写库那一步、TV daily-sync 的外部语料新鲜度灯 |
| 12-15 | G-03 复核落档速度 |
| 2027-01-02 | G-18 季度找新特征第一次定时跑；手动重跑季度闸二（`gate2-run.yml`，G-12）；删帖回算的代码到时候加（D-149）；之前 owner 要定 F-18 |
| 约 2027-01-13 | W-46、W-47 发牌 v2 的 10 周读数 |
| 约 2027 年 1 月上中旬 | 闸三第一次读数（G-03；主判据不变，并排报 D-137、D-146、D-149 那三样） |
| 2027-04-02 | G-19 副题库按原措辞再读一次 |

### 6.6 文档里已经过时、下一个文档 PR 顺手清的

- OPEN-ITEMS：W-59（aw#162 11-15 已合并，核过就关）；I-29 和第 8 节里「要你跑 v1_28」（首图 11-16 起每晚在写库）；I-30、I-31 和第 8 节里「要你跑 v1_27」（owner 11-16 跑了）；linkcheck「补齐缺的列」（owner 说各表都点了）；第 0 节里已经做完的旧行（D-155 第一晚、D-154 第一晚、回流闸头三晚三行，核完挪到「0 的旧行」）。DSH 插件那条线（aw#164–#176）只记在 aw 的文档里，OPEN-ITEMS 里还没有对应的条目。
- aw：HANDOFF.md 停在 10-22；runbook §1.2、§1.16 过时（见第 2 节）。
- Jev：HANDOFF.md 顶部那节说 cover pilot「还没跑」；README 的三库一节漏了 linkcheck。
- linkcheck：README 里「1000+ 个测试」已是 2408 个。
- aw、Jev、linkcheck 的纯文档改动都会触发 Railway 重新部署，攒到有代码的 PR 一起上。

### 6.7 只盯、等触发的

W-56（下一次 `check_rules` 之后核新的题）、AU-F07、W-33、W-28、S-14、F-04、F-14（第二周到 11-30）。协议里客户端中性的那批措辞攒着，等下一次值得写手重导的协议改动一起上。

## 7. 每个库要注意的地方

**TV**
- `ci.yml` 现在约 497.7 KB，守卫卡在 505,000 字节；到 516,314 字节 GitHub 会直接 startup_failure（0 个 job、没有日志、CI 整个不跑）。**不要往 ci.yml 里加内联逻辑**，新守卫写成 `scripts/check_*.py`，ci.yml 里只留一行调用。
- heredoc 棘轮：ci.yml 里 `<<'PY'` 的个数必须**等于** `CI_HEREDOC_CAP = 69`（`scripts/check_system_map.py` G2）；挪走一块也会红，要在同一个 PR 里把上限调下来；往上调要 DECISIONS 记一条。
- 加定时 workflow 要进 `sync-watchdog.yml` 的 WATCHED；加 `*_CHECK_DONE rc=` 灯要在 `docs/29` 登记；新的 `schemas/notes_v1_NN` 要进 `scripts/README.md` Step 0 和 sql job（跑两次）；`docs/00` §3 地图里的 `tv:` / `script:` / `wf:` 改名要同 PR 改图。
- 定时任务只从 main 跑，GitHub 排队常晚几个小时（daily-sync 实际 08–11 UTC，首图 21–23 UTC），没到点没跑不算坏。手动触发 daily-sync 会把没验证过的 on_demand 项目也同步，**别为了「补跑」手动点**；它的 `project` 输入要写全名（如 `NRT_phase2`），写短名什么都不做还显示绿。首图手动触发默认 `dry_run=true`。
- 定时任务（UTC）：daily-sync `17 2 * * *`；features-sync `47 12 * * *`；first-image-sync `37 15 * * *`（每晚最多 40 张图、约 0.97 元封顶，写死在代码里；要停就在 Actions 里把它 Disable）；sync-watchdog `41 23 * * *`；feature-discovery 每季度，第一次 2027-01-02。**TV 里没有 tv-sync**，那是 aw 的 Railway cron。
- 首图问卷每晚读的是 fi-v0.2（`scripts/first_image_pass.py` 的 `BANK_PATH` / `BANK_VERSION`）；fi-v0.3（`prompts/first_image_questions_v0_3.yaml`）备好了、还没换。

**aw**
- 默认分支名嵌在插件索引地址和 skill 升级提醒里，**改名会让写手那边全部失效**。
- 改 `deskcore/protocol.md` 或 `skills/bywood-writing-desk/SKILL.md` 标记行以上的头，协议版本号（sha256 前 12 位）就变，WorkBuddy 写手就得重导 skill。能写进 `deskcore/tools.py` docstring 的口径就写那里（部署即生效）。改了 protocol.md 必须 `sync-skill` 并两个文件一起提交。
- 协议发版顺序（runbook §6.5）：改完 `sync-skill` + `--check` → 按需在 `deskcore/skillcheck.py` 的 WHATS_NEW 加一行 → docs/deskcore.md 加一节 → CI 绿合并 → **等 `/health` 的 `build.commit` 和 `protocol_version` 都变成新值**，才通知写手在 WorkBuddy 里说「更新技能/bywood-writing-desk」并开新对话 → 一两天后用 §3.8 末尾「写手手上的 skill」那条 SQL 只读看旧版 skill 最近还有没有人在用（或带 key 查 `GET /skill-versions`；都分不出人数，见 6.3）。DSH 插件每 30 分钟自己取一次协议，不用重导。
- 服务端改工具名、`project_id`、`get_protocol` 回包字段或鉴权头之前，先改两个插件包（正常版和 compat-021）各发一版，两边的写手都升上去了再改服务端。
  - 正常版发版：改 `clients/dsh-plugin` 提版本号合并 → `node clients/dsh-plugin-index/release.mjs <40 位合并提交号>` → 第二个 PR 合并 index.json。
  - 两个包共用的文件要在**同一个 PR** 里一起改：`index.js`、`client.js`、`cordis.patch.yml`、`icon.svg`、`docs/`、`test/desk.test.js` 必须和正常版逐字节相同，`lib/desk.js` 只许差两句「配完要重启」（compat-021 的 `test/branch.test.js`，CI 每个 PR 都跑），只改正常版 CI 就红。只有 `lib/plugin.js` 和预设要手工搬（见它 README 的维护一节）。
  - compat-021（Intel Mac、DSH 0.2.1）**不在插件索引里**，`release.mjs` 只认 `clients/dsh-plugin`：改动进 `clients/dsh-plugin-compat-021` → 提它 package.json 的版本号 → `node --test clients/dsh-plugin-compat-021/test/*.test.js` → 合并 → 把新的安装地址 `git+https://github.com/TangVarie/autowriter.git#<40 位合并提交号>&path:/clients/dsh-plugin-compat-021` 交给 owner，由 owner 转给 Intel Mac 的写手（会话不直接找写手）：在插件页重新添加（包名相同，会替换旧的），⌘Q 完全退出 DSH 再打开，用 `/desk-status` 确认。这些写手不会收到升级提示。
- deskcore 里不许有任何 LLM 调用（CI 用 AST 钉住）；不许新增 fail-open 工具（ci.yml 的 `SAFE_OK` 钉死了四个）；新迁移的文件名要同时写进 docs/deskcore.md、migrations/README.md、runbook（`test_migration_doctor` 会查）；迁移都是人工跑。
- CI 第一轮 pytest 没装 fastapi / mcp，新的 HTTP / MCP 用例要 `pytest.importorskip`；第二轮装全后日志里出现 "could not import" 就判红。
- `/health` 永远 200，`ok=true` 不代表业务链路健康。迁移 021、022 在生产跑没跑过不确定，会话里没有库的凭据、`doctor` 跑不了，用第 6.4 节那三条 SELECT 经 Supabase 连接器只读核；两个都能降级，不跑也不坏。

**Jev**
- 正确的生产地址带 `-601c`。`/health` 的 `policy_sha256` 要和本地 `sha256sum config/data_policy.yaml` 对上。
- 应急开关：Railway 变量 `JUDGE_COMMENT_TOOLS_ENABLED=0` 让两个评论端点立刻回 503（写作台如实说「没判成」）；`RELAY_FORCE=primary|backup` 指定中转站。改 Railway 变量会触发重新部署。
- external-corpus 手动触发**真花钱**（TikHub + Jev 供应商，一次最坏约 4.48 美元、硬上限 6 美元）；`fresh_state=true` 只在删了一批外部帖要重抓时用；改它的 cron 会让两个测试变红；加品类要同时在 TV 的 `prompts/external_shelf_v1.json` 补同名一行；预算不能低于 dry-run 算出的最坏花费。
- 两个一次性认领 tag（`comment-gate-d112-run-claimed`、`cover-pilot-i35-run-claimed`）都已用掉，删 tag 等于重新授权一次付费运行，没有 owner 的话不删。
- `comment_reader_v0.6` 冻结不改；改题干或定义要升 `bank_version` 并重跑金标；暗题的题号和答案永远不进给写手看的输出；`data_policy.yaml` 里的 `"*"` 必须带引号。
- 账本写库 `write=true` 可能只写了一半，调用方要看 `write_error`，别只看 200。

**linkcheck**
- 付费执行者只能有 Railway cron 一个：不要取消 `refresh.yml` 里定时那几行的注释；面板服务不能配 Cron，Start Command 里不能出现 `queue` 或 `sweep`；cron 服务的 Restart Policy 必须是 Never（否则失败后反复重启、循环烧钱）；`runlock` 是文件锁，跨容器拦不住。
- 只用标准库；`panel.py` 不准 import providers 或 runner（AST 测试钉着）。面板里会花钱的只有搜索试跑（`trial.py`）和 DeepSeek 日报草稿（`report_ai.py`）。
- 机器只动七个标签词，人工标签不碰；「风控中」「疑似限流」只加不减；任何失败路径都不清空数据列；没变化就不写。抖音一律不判置顶。
- TikHub 对失败的调用和传错的 ID 照样扣费；`MAX_YUAN_PER_RUN` 是唯一的硬上限；搜索试跑上限 280 次 / ¥20 写死在代码里。
- 飞书注册表 base 里的「巡检留痕」「面板设置」是机器自己的记录：不改名、不改列、不删 `trial.search.*` 开头的行（删了试跑的账就清零）。
- 改面板样子要过 `tests/test_design.py`（仓库里有一份 BYWOOD 设计 token 副本，要和设计系统同步）；改了标题文字要重出字体子集（`tools/build_panel_fonts.py`，要 fontTools）；改完看渲染截图。
- 仓库名 linkcheck、包名 `xhsearch/` 都是历史遗留，别改；`coze-legacy` 分支 README 里还链接着，别删。
- 不提交：`.env`、`exports/` 下的 CSV（有评论正文）、`~/.linkcheck/search-trial` 的 state（有别人笔记的 ID）、`probe_endpoint_raw.json`。

## 8. 交接时顺手做了的事

- TV#302 合并（277727f）：首图 Summary 起把中转站回报的输入、输出 token 分开记。
- 本 PR（TangVarie/truth-vault#303）：本文；`docs/34` 第 13 节第 5 步注明 0.84 元的线已换成 3.5 元；`scripts/ci_local.py`（照 ci.yml 在本地跑 python / yaml 两个 job，进了 CI 的编译列表）；OPEN-ITEMS 标题和 CURRENT_STATE 改成四个库；HANDOFF.md、docs/00 顶部指向本文；D-162 / I-38 记下 owner 11-22 的「同意」。
- 每周一的「OPEN-ITEMS weekly review」定时任务的提示词改成四个库（加了 linkcheck）。
- 11-23 补：第二轮独立复审的改动（features-sync 核法、zen 分支的核法、备用站怎么认、几晚怎么算、skill 读数分不出人数、compat-021 同 PR 同步、TV#301 回流闸、I-38 那句「多半是输出变长了」改成还分不出）。
- 上一个会话排的首图读数提醒（原定 11-22 23:50 UTC 唤醒旧会话）已删，改由新会话自己排（第 6.1 节）。
