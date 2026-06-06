-- ─────────────────────────────────────────────────────────────
-- dashboard_views_v6_timeseries.sql
-- 看板真实时间序列 + 投放热力(对外可公开:只露体量/结果,无策略机理)。
-- 全部从 truth_vault.notes.publish_time 真列聚合;security_invoker=false 以属主读底表。
-- ─────────────────────────────────────────────────────────────

-- 月度时间序列:发布量 / 曝光 / 爆款 + 累计曝光(真实,含战役期起伏)
create or replace view public.v_dash_monthly with (security_invoker = false) as
with m as (
  select
    date_trunc('month', publish_time)                       as mon,
    count(*)                                                as notes,
    coalesce(sum(impressions), 0)::bigint                   as impressions,
    count(*) filter (where tier in ('爆','大爆'))            as hits
  from truth_vault.notes
  where publish_time is not null
  group by 1
)
select
  to_char(mon, 'YYYY-MM')                                   as ym,
  notes, impressions, hits,
  sum(impressions) over (order by mon)::bigint              as cum_impressions
from m
order by mon;
comment on view public.v_dash_monthly is '看板:月度发布量/曝光/爆款 + 累计曝光(真实时间序列)。';

-- 投放热力:月 × 周几 的发布计数(真实节奏)
create or replace view public.v_dash_pub_activity with (security_invoker = false) as
select
  to_char(date_trunc('month', publish_time), 'YYYY-MM')    as ym,
  extract(isodow from publish_time)::int                   as dow,
  count(*)                                                 as n
from truth_vault.notes
where publish_time is not null
group by 1, 2
order by 1, 2;
comment on view public.v_dash_pub_activity is '看板:月×周几 发布热力(真实投放节奏)。';

-- GRANT(包 IF EXISTS;裸 PG / CI 无这些角色)
do $$
declare v text; r text;
begin
  foreach v in array array['v_dash_monthly','v_dash_pub_activity'] loop
    foreach r in array array['anon','authenticated','service_role'] loop
      if exists (select 1 from pg_roles where rolname = r) then
        execute format('grant select on public.%I to %I', v, r);
      end if;
    end loop;
  end loop;
end $$;
