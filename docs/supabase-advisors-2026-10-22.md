# Supabase 警告分诊 · 2026-10-22（S-13）

项目 `kduysqedrclrfevrxiie`。只读：advisor 快照（10-22 05:43 UTC）、catalog 查询、24 小时 edge 日志、四个仓（TV / aw / Jev / linkcheck）的代码。没有执行任何改动。

## 1. 结论

| 警告 | 数量 | 判断 | 动作 |
|---|---|---|---|
| `security_definer_view`（ERROR） | 18，全是 `public.v_dash_*` | 维持 D-101 的已接受例外，理由补正（见 §3） | 不改视图。旧 anon 随 S-12 停用后，泄露出去的那把就读不了 |
| 登录用户能读 5 张 ssll 表（advisor 没报） | 5 | 真暴露面，见 §2 | **现在关掉 Auth 注册**；`ssll_authenticated_read` 去不去 owner 定 |
| 10-30 public 授权变更（邮件） | — | 我们不用改任何东西 | 10-31 复查一次（§4） |
| `rls_enabled_no_policy`（INFO） | 32（9 autowriter + 23 truth_vault） | 有意设计：只给 service_role，anon / authenticated 没有任何表权限 | 不动 |
| `unindexed_foreign_keys`（INFO） | 3 | 都不在热路径上 | 不动 |
| `no_primary_key`（INFO） | 19 | 全是一次性备份 / 修复表 | 按 S-01 / S-02 到期删；S-01 两张今天到期 |
| `unused_index`（INFO） | 14 | 只有 autowriter 两个可以考虑删（§5 有前提） | 低优先级 |
| Auth 连接数固定 10（INFO） | 1 | 6 个用户，08-19 以后没人登录 | 不动 |

## 2. 登录用户能读什么

`public` 下 5 张 ssll 表都挂着 `ssll_authenticated_read`（`FOR SELECT TO authenticated USING (true)`），任何登录用户都能整表读：

- `reference_samples` 330 行：推给三省六部的爆款正文、评论、AI 分析；
- `stage_logs` 1,139 行，`outputs`、`projects`、`pipeline_runs`。

autowriter 的 11 张表也给 authenticated 开着，但 policy 按 `auth.uid()` 只放行本人的行，陌生账号读到 0 行。

这条 policy 是 D-101 为了「ssll 也许走登录会话」留的。10-22 的 edge 日志说明用不上它：

- 三省六部轮询 `pipeline_runs`（24 小时 19,833 次）带的是 service_role；
- 24 小时里没有一次 authenticated 请求；
- auth.users 6 个，最新建于 05-21，最后一次登录 08-19（Streamlit 10-16 已停）。

风险在于：旧 anon key 在已停的 Streamlit 的 Railway 变量里，按 S-12 算已泄露。如果 Auth 注册开着，拿它注册一个账号就能读上面这些表。

**建议**：

1. **现在**：Supabase 控制台 → Authentication → Sign In / Providers，关掉「Allow new users to sign up」。随时能开回来，现在没人用登录。
2. **owner 定**：去掉 `ssll_authenticated_read`。去掉以后登录用户读这 5 张表得 0 行，三省六部走 service_role 不受影响。在 SQL editor 跑：

```sql
BEGIN;
DO $$ DECLARE t TEXT; BEGIN
  FOREACH t IN ARRAY ARRAY['projects','pipeline_runs','stage_logs','outputs','reference_samples'] LOOP
    EXECUTE format('DROP POLICY IF EXISTS ssll_authenticated_read ON public.%I', t);
  END LOOP;
END $$;
COMMIT;
-- 回滚：对 5 张表各跑一次
--   CREATE POLICY ssll_authenticated_read ON public.<t> FOR SELECT TO authenticated USING (true);
```

日志巡检（每 3 小时）已加上：看注册 / 登录事件和 auth.users 数量，出现 authenticated 请求就报。

## 3. 18 个看板视图

- 定义在 `schemas/dashboard_views_v1…v6.sql`，owner 是 postgres，`security_invoker=false`。每个文件都显式 GRANT SELECT 给 anon / authenticated / service_role。
- 唯一的读者是 Vercel 上的 TV 看板：服务端用 anon key（UA `node`，成批读 18 个视图）。key 不进浏览器。
- anon 直接读不到任何底表：truth_vault 不给 anon USAGE，48 个关系里 anon 能 SELECT 的是 0 个。
- 视图里没有正文、标题、链接、账号名、评论。

D-101 的理由要补一句：视图虽然没有正文，但有

- 18 个项目代号；
- 各项目真实的曝光、篇数、爆款数；
- Top 8 爆贴的精确互动数；
- 真实总曝光（对外 /board 用的是合成的展示数）。

这个仓是公开的，`dashboard/config/showcase.ts` 写着代号到品牌名的对应。所以拿到 anon key 的人能读到的是「哪个品牌、真实数据多少」。

为什么还是不改：

- 改成 `security_invoker=true`，看板会静默变空。要让它恢复，得把 truth_vault 的 6 张表（notes、projects、flywheel_lesson_annotations、flywheel_librarian_cache、audit_log、metric_snapshots）、视图 `truth_vault.v_flywheel_lesson_cards`（`v_dash_overview` 的 borrowable_cards 读它）和 `public.pipeline_runs` 开给 anon，比现在差得多。
- anon key 只在 Vercel 服务端。泄露的那份是旧 anon（随 Streamlit 在 Railway 上），S-12 恢复后第 7 步停用旧版密钥就作废了。看板换成新的 `sb_publishable_` 以后，只存在 Vercel 里。
- 再要收紧的话，有两条路：给看板建一个只读这 18 个视图的数据库角色、服务端直连读；或者看板改用一把 `sb_secret_`（与 D-101 不放 service_role 的取舍相反）。现在都不做，S-12 之后再看。

## 4. 10-30 public 授权变更

Supabase 邮件：10-30 起，在 `public` 新建的表不再自动授权给 anon / authenticated / service_role，已有对象不变。邮件只说了表；Supabase 文档里对应的 SQL 还会收 postgres 在 public 新建的函数 EXECUTE、序列 USAGE / SELECT，视图走表的默认权限、同样受影响，而且表只收 SELECT / INSERT / UPDATE / DELETE。10-30 实际收了哪些，以 10-31 复查为准。

- 我们现在 public 里的 23 个对象（5 张 ssll 表 + 18 个看板视图）都保留现有授权。public 里没有函数、序列和物化视图。
- 四个仓都不会在 public 新建对象：看板视图的 SQL 文件自带 GRANT（重建也覆盖）；TV CI 跑在普通 Postgres 16 上；没有 Supabase CLI 配置、`db reset`，也没有预览分支。
- truth_vault、autowriter 不受影响：truth_vault 自己有给 service_role 的默认授权，autowriter 每个迁移都显式 GRANT，CI 也查这一点。Jev 只读写 truth_vault；linkcheck 不用 Supabase。
- 要记住的三件事：
  - `sanshengliubu-patches/004_jobs_table.sql`、`005_multi_tenant_workspaces.sql` 会在 public 新建表，却没有表级 GRANT。这两个文件从没跑过；真要跑，先补 GRANT（README 已注明）。
  - 三省六部自己以后在 public 建表，要自己 GRANT（S-06）。
  - 预览分支会重放生产记录在案的迁移，现在就重放不通（没有哪条记录在案的迁移建了那 5 张 ssll 表）；10-30 之后，06-07～06-10 那 5 条看板视图迁移没有 GRANT（06-06 最早的 v1～v3 三条有），其中 11 个视图第一次就是在这几条里建的，重放出来 anon 读不到；`v_dash_system_pulse`、`v_dash_pub_activity` 连迁移记录都没有，重放根本建不出来。重放出来的看板会静默缺数据。不开预览分支就没事。
- **10-31 复查**：public 的默认授权确实变了；23 个对象的授权没变；看板照常有数。

## 5. autowriter 两个没用的索引

- `draft_fp_embedding_idx`：27 MB。查重那一路有意绕开它（aw `migrations/004_deskcore_check_pushdown.sql:22-33`），但同一段注释写了「索引留着不动」，留给将来「找相似选题」这类能容忍近似的功能。现在没有代码用它。真要删，先跟 aw 确认不做这类功能，并在 aw 加一条 DROP 迁移、改掉 `000_baseline.sql`、`001_deskcore.sql` 里的 CREATE INDEX 和 004 的注释。
- `versions_embedding_idx`：`versions.embedding` 8,476 行里 0 行非空。

删了能省空间、少一点写入开销，不急。其余 12 个没用的索引里，4 个盖着外键（删了会冒出新的「外键没索引」提示），剩下的很小，或在空表、ssll 的表上。
