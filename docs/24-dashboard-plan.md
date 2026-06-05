# 24 · 飞轮总看板(Flywheel Dashboard)落地计划

> **一句话**:做一个**在线网站**(不是本地脚本),实时照见 **autowriter / Truth Vault / sanshengliubu(及未来去中心化)
> 各板块、各通道、各环节的状态**。两个用途:**对外装逼**(让人一眼看到"这套飞轮活着、在转、有护城河")+
> **对内自监测**(哪条管道卡了、什么在流、哪里红了)。
>
> 本文 = 愿景 + 技术选型 + 数据来源 + 看板内容设计 + 安全 + 分阶段落地 + 部署/域名。配套当前状态见 [docs/22](22-handover-2026-06-05-onboarding-hardened.md)。

---

## 1. 两个用途,一个网站

| 用途 | 受众 | 内容取向 | 访问 |
|---|---|---|---|
| **对外装逼** | 客户 / 投资人 / 合作方 | 漂亮、动感、聚合大数 + "飞轮活着"的可视化;**不露敏感运营细节** | **公开**(自定义域名) |
| **对内自监测** | 你 / 运营 / 维护者 | 各系统/通道/环节的健康、待办队列、最近失败、drill-down | **登录后**(auth-gate) |

→ 同一个站,**两层视图**:公开"态势 hero"页(安全聚合数)+ 登录后"运维"页(细节)。

---

## 2. 技术选型(为什么这套 = 满足"在线服务网站 + 后期自定义域名")

| 决定 | 选 | 为什么 |
|---|---|---|
| 托管 | **Vercel** | 真·托管在线服务;**自定义域名一键加**(Settings→Domains + DNS,免费);连 GitHub 自动部署;有现成 MCP 可代部署 |
| 框架 | **Next.js(App Router)+ React + TypeScript + Tailwind** | 看板标配;Server Components 在**服务端**查库(密钥不进浏览器);SSR/ISR 易做实时感 |
| 数据 | **共享 Supabase**(`kduysqedrclrfevrxiie`) | ⭐ aw/tv/ssll **同一个库、不同 schema**(`autowriter` / `truth_vault` / `public`)——**一个连接照见整个生态** |
| 图表 | recharts / 轻量 SVG | 趋势 + 飞轮活体图 |
| 刷新 | ISR(每 30-60s 重验)或前端轮询;进阶 Supabase Realtime | "活着"的实时感 |

**自定义域名**:Vercel 项目建好后,Settings → Domains 加你的域名(如 `console.fanvalley.xxx`)→ 按提示配一条 DNS CNAME 即可,**后期随时换/加**。

---

## 3. 数据从哪来(关键架构)

三系统共用一个 Supabase,**在 TV 这边建一组只读"看板聚合视图"**(`schemas/dashboard_views_v*.sql`),前端只 `select` 干净视图,不写散落 SQL:

```
飞书(4 项目) → truth_vault(入库/essence/策展/馆员) ─通道1 push→ public(ssll reference_samples / pipeline)
                                                   └通道2 pull→ autowriter(items/版本/正负例/借卡注入)
去中心化(未来) → 预留板块
```

聚合视图(初版构想,落地时按真实列校准):
- `v_dash_overview` — 全局大数(项目/笔记/真爆款/经验卡/馆员借阅累计/essence 进度)。
- `v_dash_tv_projects` — 每项目:笔记/爆款/essence drain/sync_interval/最近 sync。
- `v_dash_channels` — 通道1(synced/pending baokuan、reference_samples)、通道2(馆员调用数、借出卡、缓存命中、最近借阅)。
- `v_dash_aw` — items/batches、正负例池(positive/negative)、最近生成、飞轮注入命中。
- `v_dash_ssll` — reference_samples 数、pipeline 最近运行。
- `v_dash_health` — 各服务/通道"最近活动时间"+ 待标 essence / 待策展 / 最近失败(给"活着"灯 + 告警)。

> 好处:看板逻辑沉在 SQL 视图(在仓里、可 review),前端薄;换前端/加页面都不动数据层。

---

## 4. 看板内容设计(我帮你想的——板块/通道/环节/状态)

### A. 全局态势 / Hero(公开 · 装逼核心)
- **飞轮活体图**:节点=系统&服务(飞书/TV/通道1/通道2/ssll/aw/去中心化占位),边=数据流;边/节点带**"最近活动脉冲"**(最近 N 分钟有动 → 发光/绿)。一眼"它在转"。
- **头部大数**(滚动/计数动画):项目数 · 总笔记 · **真爆款燃料** · 经验卡 · **馆员累计借阅** · essence 标注进度条。
- **"活着"指示灯**:每个服务/通道一盏(绿=近活/黄=偏慢/灰=静默)。

### B. Truth Vault 面板(内部)
- 4 项目卡:笔记/爆款/essence drain 进度条/`sync_interval`/最近 sync 时间。
- 数据质量:quarantine 数、(未来)受众不符 flag(L3)。
- cron 健康:最近 `Daily TV sync` 绿/红 + 时间。

### C. 通道面板(内部 + 部分公开)
- **通道1(→ssll)**:baokuan synced/pending、`reference_samples` 总数、最近 push。
- **通道2(→aw)**:馆员调用次数、借出卡数、缓存命中率、最近借阅的项目/时间(= §2 我们刚拉通的那条)。

### D. autowriter 面板(内部)
- items/batches、**正例/负例池**(positive/negative 数)、最近生成、**飞轮注入命中**(借了几张经验卡)。

### E. sanshengliubu 面板(内部)
- `reference_samples`、pipeline 最近运行、vibe_rewriter 是否在用 DB 样本(R-022)。

### F. 去中心化(占位)
- 先放"规划中"卡,预留未来模块接入位。

### G. (内部)管道/告警
- essence 待标、curate 待策展、最近失败的 run、stuck 检测(卡住的队列/超时)。

---

## 5. 安全(必须做对)

1. **Supabase service_role key 只在服务端**(Next.js Server Components / API routes),**绝不进浏览器**。公开页只渲染服务端算好的安全聚合数。
2. **公开 vs 内部分离**:公开页 = 安全聚合(项目数/燃料/活着信号);内部页(drill-down/原始计数/队列/失败)**走登录**——方案:Vercel 密码保护 或 共享口令 或 Supabase Auth(先用最简单的,后期升 Auth)。
3. **客户数据隔离**:涉及具体投放/受众的细节归内部页;公开页不露单客户敏感数。

---

## 6. 分阶段落地

| Phase | 目标 | 产出 | 你需要给 |
|---|---|---|---|
| **0 · 骨架(本 PR)** | 仓里有个能部署的 Next.js 站 | `dashboard/`(Next.js 骨架 + 一个 overview 页查 TV 真实大数)+ 本计划 | — |
| **1 · 上线 MVP** | **有一个能打开的网址** | 部署到 Vercel + 配 Supabase env;overview 页跑通 | Vercel 账号接入 + Supabase URL/key |
| **2 · 各系统面板** | TV/通道/aw/ssll 详细卡 + 图表 + 聚合视图 | `schemas/dashboard_views_*.sql` + 各面板 | — |
| **3 · 装逼级** | 飞轮活体图 + 动画 + 公开/内部分离 + 美化 | hero 可视化 + auth-gate | 选 auth 方式 |
| **4 · 域名 + 去中心化位** | 自定义域名 + 未来模块占位 + 告警/趋势 | Vercel 加域名 + 占位 + 历史趋势表 | 你的域名 |

---

## 7. 仓库位置 + 部署 + 域名

- **位置**:放 `truth-vault/dashboard/`(TV 是数据基础设施 hub,看板是其上的"视图层";共用 Supabase 连接)。**Vercel 支持从子目录部署**(Root Directory 设 `dashboard`)。后期若要独立成站,可抽出单独仓。
- **部署**:Vercel → New Project → 连 `TangVarie/truth-vault`、Root Directory=`dashboard` → 配 env(`SUPABASE_URL`、`SUPABASE_SERVICE_ROLE_KEY`)→ 自动构建上线。我有 Vercel MCP,可在你接入账号后代部署。
- **域名**:Vercel 项目 Settings → Domains → 加域名 → 配 DNS。后期一键换。

---

## 8. 待你拍板的几个点(我已给默认,确认或改)

1. **托管 = Vercel**(默认,最契合"在线网站 + 自定义域名")—— ✅/换?
2. **公开页露多少**:默认只露安全聚合(项目数/燃料/经验卡/活着信号),单客户细节归内部登录页 —— OK?
3. **位置 = `truth-vault/dashboard/`**(默认)还是要**独立新仓**(需把 autowriter 之外的仓加进 scope / 新建仓)?
4. **内部页 auth**:先用 Vercel 密码保护(最省),后期升 Supabase Auth —— OK?

---

_本计划 2026-06-05。本 PR 落 Phase 0(骨架 + 计划);Phase 1 上线需你接入 Vercel + 给 Supabase key。_
