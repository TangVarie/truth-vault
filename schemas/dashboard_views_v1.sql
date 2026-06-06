-- dashboard_views_v1.sql · 飞轮总看板 · 公开聚合视图(docs/24 §3)
--
-- 为什么需要它(安全 + 架构):
--   1. `truth_vault.*` 表都 RLS-on 且无策略 → anon/authenticated 读不到任何行。
--      看板若直接用 service_role 连 truth_vault,等于把"全库钥匙"放上一个对外网站,是雷。
--   2. 正解(docs/24 §3):在已暴露的 `public` schema 建**只读聚合视图**,**只吐安全大数**(count),
--      视图以 owner(postgres)身份读 truth_vault(security_invoker=false 故能跨过 RLS 算聚合),
--      再 GRANT SELECT 给 anon —— 前端用**最小权限 anon key、服务端**只 select 这个视图。
--      anon 拿不到 truth_vault/autowriter 原始行,只看得到聚合数;前端薄、看板逻辑沉在这。
--
-- ⚠️ 视图是 security_invoker=false(=以视图属主权限读底表),这是**有意**的:它只对外暴露聚合,
--    不暴露任何明细行。Supabase 安全 linter 可能把它标成 "security definer view",此处可接受。
--
-- 幂等:create or replace。改了请同步 apply 到 prod(MCP apply_migration / SQL editor)。

create or replace view public.v_dash_overview
  with (security_invoker = false) as
select
  (select count(*) from truth_vault.projects)                                   as projects,
  (select count(*) from truth_vault.notes)                                      as notes,
  (select count(*) from truth_vault.notes
     where tier in ('爆','大爆'))                                               as baokuan_all,
  (select count(*) from truth_vault.notes
     where tier in ('爆','大爆') and tier_source = '状态字段')                  as baokuan_real,
  (select count(*) from truth_vault.flywheel_lesson_annotations)                as cards,
  (select count(*) from truth_vault.v_flywheel_lesson_cards)                    as borrowable_cards,
  (select count(*) from truth_vault.flywheel_librarian_cache)                   as librarian,
  (select count(*) from truth_vault.notes
     where inferred_audience_profile is not null)                              as essence_done,
  (select count(*) from truth_vault.notes
     where audience_inferred_at is not null)                                   as audience_tracked,
  now()                                                                         as as_of;

comment on view public.v_dash_overview is
  '飞轮总看板公开聚合(docs/24 §3):只吐安全大数,供前端 anon 服务端 select。security_invoker=false 以读 RLS-on 的 truth_vault。';

grant select on public.v_dash_overview to anon, authenticated, service_role;
