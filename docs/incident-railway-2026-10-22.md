# Railway 环境变量泄露 · 2026-10-21/22（S-12）

本文档只记密钥的**名字**和**存放位置**，不写任何值。生产只读核查截至 2026-10-22 06:45 UTC。

## 1. 发生了什么

- Railway 于 10-21 发布安全公告：第三方可能访问了客户的加密环境变量，其中一部分被解密。公告原文是 "an unauthorized third party may have accessed encrypted environment variables and, for some of them, obtained the decrypted contents"。来源：[blog](https://blog.railway.com/p/security-disclosure-wednesday-october-21st)、[status](https://status.railway.com/incident/QH8L8B3E)。
- Railway 已经替用户做了这些处理：
  - 作废全部 Railway API token（10-22 04:17 UTC）；
  - 作废 GitHub 连接 token（要重新连接 GitHub，否则不能从 GitHub 部署）；
  - 轮换 bucket 凭据（我们没用 bucket）。
- 构建 / 部署全平台暂停。10-22 03:32 UTC 起只恢复了 Enterprise，其他档位没有 ETA。
- **变量要重新部署才会生效**，所以在恢复之前，Railway 上的服务改了变量也用不上新值。
- Railway 说攻击者的目标是 AI 推理服务的 key，并已通知上游服务商主动作废。没有列出是哪几家，不能假定我们的 key 已经被作废。
- **owner 10-22 决定**：等 Railway 官方通知，暂停期间不改 Railway 上的任何东西。

## 2. 我们放在 Railway 上的服务

| 仓 | Railway 服务 | 说明 |
|---|---|---|
| autowriter | deskcore web、tv-sync cron（项目 8d2ffc90…） | tv-sync 的变量引用 deskcore 的变量。**10-21 14:00 UTC 那一轮 tv-sync 没跑**（Supabase 日志里没有它的请求），W-23 补算还没做 |
| autowriter | 已停用的 Streamlit 工作台（10-16 停） | 服务没删，变量还在，也算泄露 |
| truth-vault | tv-worker、librarian、onboarder | 看板在 Vercel，不在 Railway |
| JevforCoentent | judge | |
| linkcheck | 巡查 cron（每 5 分钟）、监控面板 | 独立的 Railway 项目 |
| 三省六部 | 轮询服务（不在本仓，`public.pipeline_runs`，约 2 万次 / 天） | 用的是同一把 service_role，自己还有 Kimi/Moonshot、DeepSeek、SocialDataX，可能还有中转站 token |

## 3. 密钥清单与换法

### 3.1 第三方签发的密钥

在各自后台作废旧的、生成新的。

| 密钥 | 存放位置 | 在哪换 | 旧的作废后、Railway 恢复前会断什么 |
|---|---|---|---|
| `SUPABASE_SERVICE_ROLE_KEY`（旧版 HS256 JWT，2026-04-02 签发，所有持有者共用这一把） | **Railway**：TV tv-worker、librarian（onboarder 不用，删掉即可）；aw deskcore（tv-sync 引用它）；Jev judge；三省六部；可能还在已停的 Streamlit 上。**GitHub**：TV 的 7 个 workflow、Jev 的 3 个 workflow。**Vercel**：可能残留旧副本。另有运维机上的 .env | Supabase → API Keys：每组新建一把 `sb_secret_`，各处换完后在 Legacy API keys 里 Disable（可撤回）。代码不用改，`sb_secret_` 放在 Bearer 头里也能用 | 写作台全停；judge 写不了结果（评分照常）；tv-worker 特征抽取停；馆员没缓存时选不出卡；三省六部停；看板（旧 anon 和它一起失效，看板先改用 `sb_publishable_`） |
| 中转站 Anthropic token（TV 用的是 `tbtk.asia`） | TV GitHub secret；TV tv-worker、librarian、onboarder；Jev judge 编规则；三省六部（可能）；已停的 Streamlit（用的是旧中转站 `vip.aipro.love`） | 中转站后台 → 令牌管理，按用途各建一个 | tv-worker 特征抽取；馆员没缓存时；Jev 编规则（目前没有调用方） |
| Google Gemini key | aw deskcore | AI Studio / Google Cloud | 标题语义查重退回规则查重，不挡写作。恢复后要补 reembed |
| TypeSafe key | Jev judge；Jev GitHub secret | TypeSafe 控制台 | 写手的 Jev 参考分和评论工具「没判成」，稿件照常存档 |
| Moonshot key（judge 上若有） | Jev judge | platform.moonshot.cn | 只影响编规则 |
| 飞书应用 App Secret（TV） | TV GitHub secret（daily-sync、preflight 用）；onboarder | open.feishu.cn → 凭证 → 重置 | GitHub secret 换好之前，夜跑 daily-sync 的飞书入库和 preflight 都会失败：重置后几分钟内就更新 GitHub secret，并避开夜跑时段（约 07:30–08:30 UTC）。换好后只剩 onboarder 断。先比对 App ID 是否和 linkcheck 是同一个应用 |
| 飞书应用 App Secret（linkcheck） | linkcheck cron 和面板；linkcheck GitHub secret | 同上 | 巡查停（表数据不受损） |
| TikHub、SocialDataX | linkcheck cron 和面板；linkcheck GitHub secret；Jev GitHub secret `TIKHUB_API_KEY`（10-26 周一的外部语料任务要用）；三省六部（SocialDataX） | 各自后台 | 巡查停或改走更贵的通道 |
| 飞书群机器人 webhook | 已停的 Streamlit | 群设置 → 机器人 → 重置 | 无 |

### 3.2 我们自己生成的内部钥匙

这些钥匙只在 Railway 的进程里，Railway 恢复前没法作废。

| 钥匙 | 两端 |
|---|---|
| `DESKCORE_KEYS`（3 位写手） | deskcore ↔ 写手各自的 MCP 设置（新钥匙不经过 AI） |
| `JUDGE_API_KEY`（judge 管理钥匙） | judge ↔ deskcore（三省六部的 /judge 影子跑可能也持有） |
| `JUDGE_WRITER_API_KEYS` | judge ↔ 运维机 .mcp.json（可以先追加新钥匙再删旧的） |
| `LIBRARIAN_API_KEY` | librarian ↔ deskcore（已停的 Streamlit 也有一份） |
| `WORKER_API_KEY` | tv-worker ↔ TV GitHub secret |
| `ONBOARDER_API_KEY` | onboarder ↔ TV GitHub secret |
| `PANEL_PASSWORD` / `PANEL_SECRET` | linkcheck 面板 |
| Railway token | linkcheck 面板上的 token、运维用的 token：已被 Railway 统一作废，暂不新建 |

## 4. 怎么做（按 owner 10-22 的决定）

### 4.1 现在

- 不改 Railway 上的任何东西，等官方通知。
- **新密钥不要在恢复部署前填进 Railway**：被入侵的就是 Railway 的变量存储，提前填进去可能再被读走。
- Supabase 采用方案乙：旧版 service_role 先不停用，每 3 小时巡检一次日志（定时任务「Supabase 日志巡检」）。发现对不上的来源就立刻 Disable 旧版密钥（方案甲）。
- 巡检基线（10-13 → 10-22 06:45 UTC），service_role 只来自以下来源：
  - Railway 208.77.246.x（tv-worker、三省六部、特征写入）；
  - Railway 152.55.188.x（librarian、judge）；
  - Google LLC 35.186.x（deskcore，supabase-py 2.30.0）；
  - Azure（GitHub Actions，每一波都对得上某次 workflow）。

  anon 只来自 Vercel（AWS 香港，只 GET `v_dash_*`）。没有陌生来源，没有 DDL 异常，没有新角色或新用户。
- 如果 Railway 来邮件说我们在受影响名单里，不等了，直接走方案甲。

### 4.2 Railway 恢复部署时，按这个顺序

1. 重新连接 GitHub。逐个服务核对 Settings → Source（aw 的 deskcore 和 tv-sync 是 `claude/xhs-content-workstation-BSEuH`，TV 和 Jev 是 `main`）。看 Audit log。
2. 核对变量有没有被篡改：
   - 地址类变量要指向原来的地址：`JUDGE_URL`、`LIBRARIAN_URL`、`ANTHROPIC_BASE_URL`、`GOOGLE_BASE_URL`、`TYPESAFE_BASE_URL`、`TIKHUB_BASE(_URL)`、`SUPABASE_URL`；
   - `*_ALLOW_ANONYMOUS`、`JUDGE_MOCK`、`ALLOW_UNSAFE_ENDPOINT_OVERRIDE` 都没有被设上；
   - `DESKCORE_KEYS` 还是 3 把。
3. 第三方后台换新密钥（3.1 表），新值填进 Railway、GitHub Secrets、Vercel。Supabase 每组一把 `sb_secret_`，看板改用 `sb_publishable_`。
4. 内部钥匙（3.2 表）生成新值，两端一起填。
5. 依次部署：judge → librarian → tv-worker → onboarder → deskcore（顺带把 aw 的 7ec8c48 上线）→ tv-sync → linkcheck。每个服务部署后核对 `/health`（onboarder 看 `/health`，再手动跑一次 onboard-table 起草一张已接过的表，确认新的 `ONBOARDER_API_KEY`、飞书密钥和中转站 token 都生效）。
6. Supabase 停用旧版 JWT 密钥。确认日志里不再有旧密钥的流量。
7. 把新的 DESKCORE 钥匙发给 3 位写手，各自改 MCP 设置。
8. 删掉 aw 已停用的 Streamlit 服务。
9. 恢复后先确认 tv-sync 真的跑起来了（W-23 那 147 条补算），再按[接手执行书](handoff-2026-10-22-next-owner.md) A–D 推进 #117。

### 4.3 不在我们仓库里、也要处理的

- **三省六部**：Railway 上的 AI 密钥和 SocialDataX 由它的维护者自己作废重建；Supabase 那把 key 跟着 4.2 第 3 步换。
- **GitHub 组织**：检查 Railway GitHub App 能访问哪些仓库、有什么权限，翻一遍组织的审计日志。
- **旧 Supabase 项目 `vnbcytilakkxojhgzeqr`**：如果还开着就暂停。已停的 Streamlit 里可能存着它的 key。

## 5. 这份清单挡不住什么

- **日志干净不等于密钥没被拿走。** 它在作废前一直有效。
- **直连数据库看不到。** Supabase 没开连接日志，只能靠 DDL 日志、`audit_log` 和 `pg_stat_activity` 的快照来判断。
- **有几处我们看不到实际配置**，清单是从代码和文档推出来的：
  - Railway 上实际设了哪些变量（我们没有 Railway 身份）；
  - GitHub Secrets 和 Vercel 的变量列表（代理返回 403）。
