# 飞轮总看板 · Flywheel Dashboard

帆谷飞轮生态(**Truth Vault / autowriter / sanshengliubu** + 未来去中心化)的在线状态看板。
两个用途:**对外装逼**(让人一眼看到飞轮活着、在转、有护城河)+ **对内自监测**(哪条管道卡了/红了)。

> 完整设计与分阶段计划见 **[`../docs/24-dashboard-plan.md`](../docs/24-dashboard-plan.md)**。本目录是 **Phase 0 骨架**。

## 路由
- `/` — **公开首页**:BYWOOD 芭梧 品牌与方法论 + 极简战绩 + 两个入口(数据看板免登录 / 团队登录)。
- `/board` — **对外数据看板**(免登录):公开展示口径的聚合数。
- `/console` — **内部座舱**(要登录):真实口径 + 策略机理。登录闸有两道:`middleware.ts` 拦一次,`app/console/page.tsx` 在页面自己的服务端代码里再验一次会话(2026-11-15 加,不再只靠中间件)。
- `/login`、`/api/auth/*` — 团队口令登录 / 退出。
- `/api/live/presence` — 实时"在线"信号(stub)。
- `/robots.txt` — 全站 Disallow(见下「对外页面的规矩」)。

## 技术栈
Next.js 14(App Router)· React · TypeScript · Tailwind · `@supabase/supabase-js`(**服务端**查库)· 部署 Vercel。

## 本地跑
```bash
cd dashboard
npm install
cp .env.example .env.local   # 填 SUPABASE_URL + SUPABASE_ANON_KEY(看板只读聚合视图, 用 anon 够了; 见下「安全」)
npm run dev                  # http://localhost:3000
```

## 数据来源
三系统**共用一个 Supabase**(`kduysqedrclrfevrxiie`),不同 schema:`truth_vault` / `autowriter` / `public`。
看板服务端用 `lib/supabase.ts` 连库,用 `.schema("...")` 切换。Phase 2 起在 `truth-vault/schemas/dashboard_views_*.sql`
建只读聚合视图,前端只 `select` 干净视图。

## 部署到 Vercel(Phase 1)
1. Vercel → **New Project** → 连 GitHub repo `TangVarie/truth-vault`。
2. **Root Directory** 设为 `dashboard`(关键:从子目录部署)。
3. **Environment Variables** 配 `SUPABASE_URL` + `SUPABASE_ANON_KEY`(`lib/supabase.ts` 优先读 anon;历史上配过的 `SUPABASE_SERVICE_ROLE_KEY` 仍兼容,但看板不需要它——2026-10-08 审计 B-12:Vercel 上若还挂着 service_role,换成 anon 后把 service_role 从 Vercel 删掉,少一个轮换点)。
4. Deploy → 得到 `*.vercel.app` 网址。

## 自定义域名(Phase 4)
Vercel 项目 → **Settings → Domains** → 加域名 → 按提示配一条 DNS(CNAME)。后期随时换/加。

## 安全
- key(anon 或兼容的 service_role)**只在服务端**(Server Components)使用,**绝不进浏览器、绝不提交进 git**。看板只 `select` GRANT 给 anon 的 `public.v_dash_*` 聚合视图,**anon key 就够**;service_role 能读写三个 schema 的一切,放在看板上是多余的爆炸半径。谁持有哪把 key 见 `RISKS.md` R-032 矩阵。
- 公开页只渲染安全聚合数;内部 drill-down/队列/失败 后续走登录(Vercel 密码保护或 Supabase Auth)。

## 对外页面的规矩(2026-11-15)
1. **不出现内部叫法。** `/` 和 `/board` 上不许有 ssll、autowriter、馆员、essence、通道、sub_direction,也不许有仓库名、库表名(规则原文在 `config/showcase.ts` 开头)。`/console` 是内部页,保留内部叫法。
   `components/LiveMonitor.tsx` 两边共用且是客户端组件,文件里写的字会进公开页的脚本包,所以它自带的是对外说法,内部叫法由 `/console` 页面传进去。
   检查:`npm run build && npm run check:public`(脚本 `scripts/check-public-wording.mjs`;不联网、不连库。先查源码里会显示的字,再起一个本机临时服务,查 `/`、`/board` 实际发出的 HTML 和脚本)。要加禁用词,改脚本里的 `BANNED`。
   不用记得手动跑:`package.json` 里的 `prebuild` 会在每次 `npm run build` 之前先跑源码那一层(Vercel 部署走的也是 `npm run build`),查到内部叫法构建就失败、不会发出去。成品那一层(HTML 和脚本)仍要构建完手动跑上面那条命令。检查自己的测试:`npm run test:check`。
2. **不进搜索引擎。** 三处同一个决定:`app/layout.tsx` 的 robots 元信息(每条路由都有 noindex, nofollow)、`app/robots.ts`(robots.txt 全站 Disallow)、`next.config.mjs` 的 `X-Robots-Tag` 响应头(Vercel 预览域名也带)。
3. **依赖。** `npm audit fix`(不加 `--force`)能修的已修,只动了 `package-lock.json`。`npm audit --omit=dev` 还剩两条(2026-11-15 实跑),都挂在 Next 14 上:14.2.35 是 14 这条线的最后一版,后面公布的问题没有 14.x 补丁。
   - `next` 那条(critical,底下 26 个公告):升到 Next 15.5.29 以上就清掉(15 这条线的补丁版,需同时升 React 19)。
   - `postcss` 那条(high):是 Next 自己带的那份旧 postcss(8.4.31),15.5.29 带的还是这一版,要到 Next 16 才换新。所以只升到 15.5.29 之后 `npm audit` 还会剩这一条;它说的是处理别人给的 CSS 时的问题,本看板只在构建时处理自己的 CSS。
   - `npm audit fix --force` 会直接跳到 Next 16,两条都清,但改动更多(中间件要改名、`next lint` 没了)。两种都是大版本升级,另排。

   按代码推断、未实测:本看板没有用图片组件、Server Actions、rewrites,公布的问题里多数走不到(Vercel 平台自己的图片优化那部分没有核实);走得到的主要是服务端组件的拒绝服务类和中间件跳转被缓存那一条(后者已给跳转加了 `Cache-Control: no-store`,且 `/console` 现在页面内再验一次会话)。
