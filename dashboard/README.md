# 飞轮总看板 · Flywheel Dashboard

帆谷飞轮生态(**Truth Vault / autowriter / sanshengliubu** + 未来去中心化)的在线状态看板。
两个用途:**对外装逼**(让人一眼看到飞轮活着、在转、有护城河)+ **对内自监测**(哪条管道卡了/红了)。

> 完整设计与分阶段计划见 **[`../docs/24-dashboard-plan.md`](../docs/24-dashboard-plan.md)**。本目录是 **Phase 0 骨架**。

## 路由
- `/` — **公开首页**:BYWOOD 芭梧 品牌与方法论 + 极简战绩 + 两个入口(数据看板免登录 / 团队登录)。
- `/board` — **对外数据看板**(免登录):公开展示口径的聚合数。
- `/console` — **内部座舱**(要登录):真实口径 + 策略机理。登录闸有两道:`proxy.ts`(Next 16 之前叫 `middleware.ts`,2026-11-17 改名,逻辑没动)拦一次,`app/console/page.tsx` 在页面自己的服务端代码里再验一次会话(2026-11-15 加,不再只靠这一层)。
- `/login`、`/api/auth/*` — 团队口令登录 / 退出。
- `/api/live/presence` — 实时"在线"信号(stub)。
- `/robots.txt` — 全站 Disallow(见下「对外页面的规矩」)。

## 技术栈
Next.js 16(App Router,构建默认 Turbopack)· React 19 · TypeScript · Tailwind 3 · `@supabase/supabase-js`(**服务端**查库)· 部署 Vercel。

- Node 至少 20.9(Next 16 的要求)。`package.json` 没写 `engines`,用的是 Vercel 项目设置里的 Node 版本;本机核过的是 Node 22。
- 构建时要从 Google Fonts 取两种字体(`app/layout.tsx` 的 Fraunces、Hanken Grotesk),连不上外网的机器上 `npm run build` 会失败;Vercel 上有网,不受影响。
- 没有 lint:Next 16 去掉了 `next lint`,看板之前也从没配过 ESLint(那条命令只会弹出配置问答),所以 `lint` 脚本删了。类型检查用 `npm run typecheck`。

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
3. **依赖。** 2026-11-17 升到 Next 16.4.6 + React 19.3.1(S-17)。升完 `npm audit --omit=dev` 0 条,`npm audit`(连开发依赖)也是 0 条。升之前(11-15 那次 `npm audit fix` 之后)还剩两条,都挂在 Next 14 上:`next` 那条(critical,11-17 升级前实跑底下 25 个公告,14.2.35 是 14 这条线的最后一版、没有补丁)和 Next 自己带的旧 `postcss` 那条(high,4 个公告,受影响的是 8.5.22 及以下;Next 16.4.6 带的是 8.5.23)。
   升级照 Next 15、16 的官方升级指南做,改的地方:`cookies()`、`searchParams` 改成先 `await`(官方 codemod `next-async-request-api`);`middleware.ts` 改名 `proxy.ts`、函数改名 `proxy`(codemod `middleware-to-proxy`),运行时从 Edge 变成 Node(proxy 不能选 Edge;`lib/auth.ts` 只用 Web Crypto,两边都能跑,升级前后签的会话互认);`app/layout.tsx` 的 `<html>` 加 `data-scroll-behavior="smooth"`(Next 16 换页时默认不再临时关掉平滑滚动,加这个才和以前一样直接跳到顶);`tsconfig.json` 两处是 Next 16 构建时要求的(`jsx: react-jsx`、多 include `.next/dev/types`)。另加了 `app/not-found.tsx`(404 页),页面上的字和样式照抄 Next 自带的那一版,只为把升级带来的两处变化改回去:浏览器标签上的标题(Next 16 下自带 404 页的标题排到了站点标题后面,标签显示成站点标题,现在改回 `404: This page could not be found.`);直接访问 `/_not-found` 或 `/%62oard` 这种编码过的地址时 404 页带 `Cache-Control: s-maxage=31536000`(Next 16 把 404 页做成了静态页,前面要是有共享缓存能存一年,现在改回每次现做、`private, no-store`;代价是 404 页不再是构建好的静态页,每次由服务端现做,看板访问量小,不在意)。
   升级前后在本机各起一份(`next start`)、不连真库对比过,另用两份假的聚合视图数据(一份低于对外展示的下限、一份高于)各比一次。看板自己的路由:`/`、`/board`、`/login`(各种 `next`、`error`)、登录后的 `/console`、`/api/*`、`/robots.txt`、404 页,状态码、`Cache-Control`、`X-Robots-Tag` 一样,`/`、`/board` 上对外展示层算出来的数一样,页面上的字逐字一样;404 页的 HTML 里少了一个原来就不显示的第二个 `<title>`(站点标题)。截图(1280、390 两种宽度,冻住动画)逐像素一样,只差一个走秒的时钟。
   和升级前不一样的地方,都是 Next 16 自己的,都不带登录后才有的数据和内部叫法,`X-Robots-Tag` 照样在:
   - `/console` 没登录时跳登录页的 `Location` 从带域名的绝对地址变成 `/login?next=…` 这样的相对地址(浏览器照样跳,`Cache-Control: no-store` 还在)。`Vary` 头多了一项。
   - 登录闸管得更宽:`/console.rsc`、`/console.segments/…`、`/%63onsole`、`/console%2F`、`/./console` 这类地址以前直接 404,现在也被 `proxy.ts` 拦下、跳登录页(`no-store`)。
   - 带 `RSC: 1` 请求头、地址上没有 `_rsc` 参数的请求,以前直接回页面数据(`private, no-store`),现在先 307 跳到带 `?_rsc` 的同一地址(Next 防缓存串数据的做法,这个跳转不带 `Cache-Control`,按 HTTP 规矩 307 默认不缓存)。浏览器里正常换页总是带 `_rsc`,不受影响。
   - `/_global-error`(Next 16 自带的出错页地址):以前 404、`private, no-store`;现在 500、`Cache-Control: s-maxage=31536000`,内容是 Next 自带的「500: This page couldn't load」,没有 robots 元信息。页面固定、不含任何数据,没有链接指向它;Vercel 上会不会对外提供这个地址没核过。页面真出错时(比如下面那个 `next` 写两遍)还是 500 + `private, no-store`,和以前一样。
   - 带着有效会话发 `OPTIONS /console`:以前照样回整页(200),现在回 400、空内容。
   客户端换页时页面不再复用 30 秒内的旧数据(Next 15 起的默认),对实时看板只会更新鲜。
   顺带发现一个升级前就有的小毛病:`/login?next=/a&next=/b`(`next` 写两遍)会 500,因为 `app/login/page.tsx` 的 `sanitizeNext` 只认字符串。升级前后一样,不漏数据、不跳走,这次没改(S-17 只管升级、行为不变)。
