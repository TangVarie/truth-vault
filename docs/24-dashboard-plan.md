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

### A. 全局态势 / Hero(公开 · 装逼核心 · **更动态 / 更多数据**)
- **飞轮活体图(动态)**:节点=系统&服务,边=数据流;**数据流沿边流动的脉冲动画**(每发生一次 sync/借卡/生成 → 一道光沿对应边跑),节点按"最近活动"明暗呼吸。一眼"它在转、在流"。用 framer-motion / SVG path 动画。
- **大数 + 计数动画 + 趋势**:不只是静态总数,还有**速度/近况**——今日新增笔记、本周新爆款、今日馆员借阅、生成吞吐;每个大数配 **sparkline 迷你趋势**(count-up 动画)。
- **实时活动流(ticker / feed)**:滚动播报最近事件——"刚刚 · aw 为某项目借了 5 张经验卡"、"NRT_3 同步 25 爆款"、"daily-sync 绿"。让人感觉**活的、在动**。
- **"在线"实时卡(留接口)**:如"**当前在线改稿 N 人**"——现在是 stub,**去中心化分发上线后从同一接口接真数据**(见 §5.5)。
- **"活着"指示灯**:每服务/通道一盏(绿=近活/黄=偏慢/灰=静默)+ "近 1 小时 X 个事件"。
- **专业级观感**:深色 + 渐变 + 动效 + 好排版 + 响应式,适合投屏/对外展示。

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

## 5.5 扩展性 / 留好接口(关键:为去中心化 + 实时指标预留)

诉求:公开页要能**后期插入新数据源/新指标**——比如去中心化分发上线后,看"**当前线上同时多少人在改稿**"。
所以看板**不写死**,而是 **config + 适配器(adapter)驱动**,加新东西 = 加一条注册,不动核心。三个接口:

1. **指标适配器 `MetricAdapter`**(`dashboard/lib/metrics/types.ts`):每块数据 = 一个 adapter(`id / label / scope:"public"|"internal" / fetch() / realtime?`)。`fetch()` 服务端取数,**来源任意**:Supabase 任一 schema、外部 API、**未来去中心化节点上报**。加新指标 = 注册一个 adapter。`scope` 控制公开/内部(公开页只渲染 `scope:"public"` 的)。
2. **飞轮图配置 `FlywheelNode/Edge`**(`dashboard/config/flywheel.ts`):节点/边是**配置**,不是硬编码。**去中心化分发 = 加一个 `status:"planned"` 的节点**(已预放),上线后改 `live` + 绑定 adapter 即出现在活体图里。
3. **实时信号接口 `/api/live/presence`**(`dashboard/app/api/live/presence/route.ts`):**现在是 stub**(返回 `online:0, source:"stub"`),前端"在线改稿"卡显示"规划中"。未来"线上同时多少人改稿"从这里出,实现择一:**Supabase Realtime presence**(改稿会话加 presence)/ **heartbeat 表**(改稿端每 N 秒上报)/ **去中心化节点上报**。**前端组件 + API 契约现在就留好,接数据时不动 UI。**

> 一句话:**"加未来模块"= 注册一个 adapter + 改一行 config + 把 stub API 换成真数据源**,核心和 UI 不动。去中心化/实时在线人数就是按这套接进来。

---

## 6. 分阶段落地

| Phase | 目标 | 产出 | 你需要给 |
|---|---|---|---|
| **0 · 骨架(本 PR)** | 仓里有个能部署的 Next.js 站 + **扩展性接口先留好** | `dashboard/`(overview 页查 TV 真实大数 + **adapter 类型 / 飞轮 config / stub 实时接口 `/api/live/presence`**)+ 本计划 | — |
| **1 · 上线 MVP** | **有一个能打开的网址** | 部署到 Vercel + 配 Supabase env;overview 页跑通 | Vercel 账号接入 + Supabase URL/key |
| **2 · 各系统面板** | TV/通道/aw/ssll 详细卡 + 图表 + 聚合视图 | `schemas/dashboard_views_*.sql` + 各面板 | — |
| **3 · 装逼级(动态)** | 飞轮活体图**流动动画** + 计数动画 + sparkline 趋势 + **实时活动 ticker** + 实时在线卡接真数据 + 公开/内部分离 + 美化 | framer-motion hero + activity feed + 接 Realtime/heartbeat + auth-gate | 选 auth + 实时源 |
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

## 9. 接力(开新窗口从这里直接继续)⭐

**已完成(Phase 0,在 PR #69,未合并)**:
- 本计划 `docs/24` + `dashboard/` 骨架(Next.js14 + Tailwind + 服务端查 Supabase)。
- overview 页**已查 TV 真实大数**(项目 4 / 笔记 2478 / 真爆款 96 / 经验卡 87 / 馆员借阅)+ 系统活着灯(config 驱动)。
- **扩展接口已留成代码**:`lib/metrics/types.ts`(MetricAdapter/FlywheelNode/LiveSignal)· `config/flywheel.ts`(节点边,去中心化预放 `planned`)· `app/api/live/presence/route.ts`(实时在线 stub)· `components/LivePresence.tsx`(轮询实时卡)。

**关键上下文(新窗口必读)**:
- 三系统(aw/tv/ssll)**共用一个 Supabase**:`kduysqedrclrfevrxiie`,schema 分别 `autowriter` / `truth_vault` / `public`。一个连接照见全生态。
- 看板 = **config + adapter 驱动**:加新数据源/新指标 = 注册 adapter + 改一行 config + 换 stub 数据源,核心/UI 不动(§5.5)。
- "**在线同时多少人改稿**"等去中心化实时指标:`/api/live/presence` 接口 + `LivePresence` 组件已就位(现 stub→"规划中");接真数据 = 把 stub 换成 Supabase Realtime presence / heartbeat 表 / 节点上报,**前端不动**。
- 本地跑:`cd dashboard && npm install && cp .env.example .env.local`(填 Supabase URL/key)`&& npm run dev`。

**待拍板(见 §8,已给默认)**:① 托管 Vercel ② 公开页露多少 ③ 位置 `truth-vault/dashboard/` vs 独立仓 ④ 内部页 auth。

**下一步三选一**:
1. **部署上线 MVP**(最快见网址)→ 需:接入 Vercel 账号 + Supabase `SERVICE_ROLE_KEY`(配进 Vercel env)。有 Vercel MCP 可代部署。
2. **写 Phase 2 聚合视图**(`truth-vault/schemas/dashboard_views_*.sql`:aw/ssll/通道真实数据)→ 部署后满屏数据。
3. **Phase 3 装逼级动效**(飞轮流动动画 framer-motion + 活动 ticker + 实时卡接真数据)。

**装逼级动效(framer-motion / SVG path 动画)= Phase 3**,Phase 0 骨架先把数据接口和结构搭好、部署 MVP 保持轻。

---

_本计划 2026-06-05。本 PR(#69)落 Phase 0(骨架 + 计划 + 扩展接口);Phase 1 上线需接入 Vercel + 给 Supabase key。_
