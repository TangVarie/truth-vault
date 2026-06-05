# 飞轮总看板 · Flywheel Dashboard

帆谷飞轮生态(**Truth Vault / autowriter / sanshengliubu** + 未来去中心化)的在线状态看板。
两个用途:**对外装逼**(让人一眼看到飞轮活着、在转、有护城河)+ **对内自监测**(哪条管道卡了/红了)。

> 完整设计与分阶段计划见 **[`../docs/24-dashboard-plan.md`](../docs/24-dashboard-plan.md)**。本目录是 **Phase 0 骨架**:
> 一个 Next.js(App Router)站 + 一个 overview 页,服务端查共享 Supabase 的 Truth Vault 真实大数。

## 技术栈
Next.js 14(App Router)· React · TypeScript · Tailwind · `@supabase/supabase-js`(**服务端**查库)· 部署 Vercel。

## 本地跑
```bash
cd dashboard
npm install
cp .env.example .env.local   # 填 SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY
npm run dev                  # http://localhost:3000
```

## 数据来源
三系统**共用一个 Supabase**(`kduysqedrclrfevrxiie`),不同 schema:`truth_vault` / `autowriter` / `public`。
看板服务端用 `lib/supabase.ts` 连库,用 `.schema("...")` 切换。Phase 2 起在 `truth-vault/schemas/dashboard_views_*.sql`
建只读聚合视图,前端只 `select` 干净视图。

## 部署到 Vercel(Phase 1)
1. Vercel → **New Project** → 连 GitHub repo `TangVarie/truth-vault`。
2. **Root Directory** 设为 `dashboard`(关键:从子目录部署)。
3. **Environment Variables** 配 `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`(service_role,只服务端用)。
4. Deploy → 得到 `*.vercel.app` 网址。

## 自定义域名(Phase 4)
Vercel 项目 → **Settings → Domains** → 加域名 → 按提示配一条 DNS(CNAME)。后期随时换/加。

## 安全
- `SUPABASE_SERVICE_ROLE_KEY` **只在服务端**(Server Components)使用,**绝不进浏览器、绝不提交进 git**。
- 公开页只渲染安全聚合数;内部 drill-down/队列/失败 后续走登录(Vercel 密码保护或 Supabase Auth)。
