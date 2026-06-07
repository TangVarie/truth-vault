-- dashboard_views_v2.sql · 看板 v3 数据层(docs/24)。在 v1 基础上追加"撑场面"的真·大数 +
-- 情绪杠杆分布 + 项目维度,供前端富面板用。仍是 public 只读安全聚合(只吐 count/sum,不吐明细)。
-- 依赖 v1(public.v_dash_overview 已存在);本文件 create or replace,幂等。

-- 1) 扩展总览:追加 累计曝光/阅读/互动(真·大数,3,000 万级)+ 杠杆/受众基数。
--    create or replace 在末尾追加新列(保持 v1 既有列名/顺序不变)。
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
  now()                                                                         as as_of,
  -- v2 追加(真·大数 + 维度基数):
  (select coalesce(sum(impressions),0) from truth_vault.notes)                  as impressions,
  (select coalesce(sum(reads),0)       from truth_vault.notes)                  as reads,
  (select coalesce(sum(interactions),0) from truth_vault.notes)                 as interactions,
  (select coalesce(max(interactions),0) from truth_vault.notes)                 as top_interactions,
  (select count(distinct emotional_lever) from truth_vault.notes
     where emotional_lever is not null and emotional_lever <> '')               as levers,
  (select count(distinct a) from truth_vault.notes n,
     lateral unnest(n.target_audience) a where a <> '')                         as audiences;

comment on view public.v_dash_overview is
  '飞轮总看板公开聚合(docs/24):安全大数(含累计曝光/阅读/互动 真·大数)。security_invoker=false 读 RLS-on 的 truth_vault。';

-- 2) 情绪杠杆 Top 分布(给环形/条形图)
create or replace view public.v_dash_levers
  with (security_invoker = false) as
select emotional_lever as lever, count(*) as n
from truth_vault.notes
where emotional_lever is not null and emotional_lever <> ''
group by emotional_lever
order by count(*) desc;

comment on view public.v_dash_levers is '看板:情绪杠杆分布(可迁移策略内核占比)。';

-- 3) 项目维度(给项目卡):笔记/爆款/策略内核/曝光 + 品类 + 战线序号(注册序,前端据此自动生成对外代号)
--    seq = 按 projects.created_at 的注册序(append-stable);前端 战线 = 希腊字母[seq] · 品类,
--    新表入库即自动获得下一个代号,无需改前端。
create or replace view public.v_dash_projects
  with (security_invoker = false) as
with ranked as (
  select project_id, category,
         (row_number() over (order by created_at))::int as seq
  from truth_vault.projects
)
select
  n.project_id,
  count(*)                                                                       as notes,
  count(*) filter (where n.tier in ('爆','大爆') and n.tier_source = '状态字段')  as baokuan,
  count(*) filter (where n.inferred_audience_profile is not null)                as essence,
  coalesce(sum(n.impressions),0)                                                 as impressions,
  r.category                                                                     as category,
  r.seq                                                                          as seq
from truth_vault.notes n
join ranked r on r.project_id = n.project_id
group by n.project_id, r.category, r.seq
order by count(*) desc;

comment on view public.v_dash_projects is '看板:项目维度(笔记/验证级爆款/策略内核/曝光/品类/战线序号 seq)。';

-- 4) GRANT 给 Supabase 角色,包 IF EXISTS(裸 PG / CI 无这些角色;对齐 notes_v1_2.sql 约定)
do $$
declare
  v text;
  r text;
begin
  foreach v in array array['v_dash_overview','v_dash_levers','v_dash_projects'] loop
    foreach r in array array['anon','authenticated','service_role'] loop
      if exists (select 1 from pg_roles where rolname = r) then
        execute format('grant select on public.%I to %I', v, r);
      end if;
    end loop;
  end loop;
end $$;
