-- dashboard_views_v4_mining.sql · 看板「深度挖掘」数据层(docs/24)
-- 把 truth_vault.notes 的真实规律挖出来:情绪杠杆命中率 / 效价×强度矩阵 / 人性原型 / 意图 / tier 漏斗。
-- 仍是 public 只读安全聚合:只吐 类别标签 + count/rate,绝不吐 title/body/account 等明细。
-- security_invoker=false:以 owner 读 RLS-on 的 truth_vault;create or replace 幂等。

-- 1) 情绪杠杆表现(命中率排行 + 漏斗)—— 揭示"最常用 ≠ 最有效"
create or replace view public.v_dash_lever_perf with (security_invoker = false) as
select
  emotional_lever                                                      as lever,
  count(*)                                                             as n,
  count(*) filter (where tier in ('爆','大爆'))                        as hits,
  round(100.0 * count(*) filter (where tier in ('爆','大爆')) / count(*), 1) as hit_rate,
  round(avg(interactions))::int                                        as avg_inter
from truth_vault.notes
where emotional_lever is not null and emotional_lever <> ''
group by emotional_lever
having count(*) >= 5
order by hit_rate desc;
comment on view public.v_dash_lever_perf is '看板深挖:情绪杠杆命中率/平均互动(n>=5)。';

-- 2) 效价 × 强度 命中矩阵 —— 高强度负面 = 爆款引擎
create or replace view public.v_dash_valence_matrix with (security_invoker = false) as
select
  emotional_valence                                                    as valence,
  emotional_intensity                                                  as intensity,
  count(*)                                                             as n,
  count(*) filter (where tier in ('爆','大爆'))                        as hits,
  round(100.0 * count(*) filter (where tier in ('爆','大爆')) / count(*), 1) as hit_rate,
  round(avg(interactions))::int                                        as avg_inter
from truth_vault.notes
where emotional_valence is not null and emotional_intensity is not null
group by emotional_valence, emotional_intensity;
comment on view public.v_dash_valence_matrix is '看板深挖:情绪效价×强度 命中矩阵。';

-- 3) 人性原型表现(target_audience/archetype 数组 unnest)—— 焦虑系原型胜出
create or replace view public.v_dash_archetype_perf with (security_invoker = false) as
select
  a                                                                    as archetype,
  count(*)                                                             as n,
  count(*) filter (where n.tier in ('爆','大爆'))                      as hits,
  round(100.0 * count(*) filter (where n.tier in ('爆','大爆')) / count(*), 1) as hit_rate,
  round(avg(n.interactions))::int                                      as avg_inter
from truth_vault.notes n, lateral unnest(n.human_truth_archetype) a
where n.human_truth_archetype is not null
group by a
having count(*) >= 5
order by hit_rate desc;
comment on view public.v_dash_archetype_perf is '看板深挖:人性原型命中率(n>=5)。';

-- 4) 意图表现 —— 种草(traffic)出爆款,转化(conversion)不出
create or replace view public.v_dash_intent_perf with (security_invoker = false) as
select
  intent,
  count(*)                                                             as n,
  count(*) filter (where tier in ('爆','大爆'))                        as hits,
  round(100.0 * count(*) filter (where tier in ('爆','大爆')) / count(*), 1) as hit_rate,
  round(avg(read_rate)::numeric, 4)                                    as read_rate,
  round(avg(interaction_rate)::numeric, 4)                             as inter_rate
from truth_vault.notes
where intent is not null
group by intent
order by n desc;
comment on view public.v_dash_intent_perf is '看板深挖:意图(种草/转化)命中率+漏斗率。';

-- 5) tier 漏斗 —— 趴→预备→爆→大爆,read_rate 随层级抬升、曝光指数级放大
create or replace view public.v_dash_tier_funnel with (security_invoker = false) as
select
  tier,
  count(*)                                                             as n,
  round(avg(impressions))::int                                         as avg_imp,
  round(avg(read_rate)::numeric, 4)                                    as read_rate,
  round(avg(interaction_rate)::numeric, 4)                             as inter_rate,
  round(avg(interactions))::int                                        as avg_inter,
  max(interactions)                                                    as max_inter
from truth_vault.notes
where tier in ('趴','预备','爆','大爆')
group by tier;
comment on view public.v_dash_tier_funnel is '看板深挖:tier 漏斗(各层曝光/读完率/互动)。';

-- 6) 分战线表现(规模+命中)—— 对齐既有公开口径:只露 project_id + 品类,不露品牌/产品名
create or replace view public.v_dash_project_perf with (security_invoker = false) as
select
  n.project_id,
  p.category,
  p.platform,
  count(n.note_id)                                                     as notes,
  count(*) filter (where n.tier in ('爆','大爆'))                      as hits,
  round(100.0 * count(*) filter (where n.tier in ('爆','大爆')) / nullif(count(n.note_id), 0), 1) as hit_rate,
  round(avg(n.impressions))::int                                       as avg_imp,
  coalesce(sum(n.impressions), 0)::bigint                              as total_imp,
  count(*) filter (where n.emotional_lever is not null and n.emotional_lever <> '') as essence
from truth_vault.notes n
join truth_vault.projects p on p.project_id = n.project_id
group by n.project_id, p.category, p.platform;
comment on view public.v_dash_project_perf is '看板深挖:分战线规模/命中率/总触达(不露品牌)。';

-- 7) 分战线 tier 构成 —— 各线各自的爆款金字塔(随真数据/新增战线自动扩展)
create or replace view public.v_dash_project_tier with (security_invoker = false) as
select project_id, tier, count(*) as n
from truth_vault.notes
where tier in ('趴','预备','爆','大爆','风控')
group by project_id, tier;
comment on view public.v_dash_project_tier is '看板深挖:分战线 tier 构成。';

-- GRANT(包 IF EXISTS;裸 PG / CI 无这些角色,对齐 notes_v1_2.sql 约定)
do $$
declare v text; r text;
begin
  foreach v in array array['v_dash_lever_perf','v_dash_valence_matrix','v_dash_archetype_perf','v_dash_intent_perf','v_dash_tier_funnel','v_dash_project_perf','v_dash_project_tier'] loop
    foreach r in array array['anon','authenticated','service_role'] loop
      if exists (select 1 from pg_roles where rolname = r) then
        execute format('grant select on public.%I to %I', v, r);
      end if;
    end loop;
  end loop;
end $$;
