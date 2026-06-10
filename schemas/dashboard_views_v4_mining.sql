-- dashboard_views_v4_mining.sql · 看板「深度挖掘」数据层(docs/24)
-- 把 truth_vault.notes 的真实规律挖出来:情绪杠杆命中率 / 效价×强度矩阵 / 人性原型 / 意图 / tier 漏斗。
-- 仍是 public 只读安全聚合:只吐 类别标签 + count/rate,绝不吐 title/body/account 等明细。
-- security_invoker=false:以 owner 读 RLS-on 的 truth_vault;create or replace 幂等。
--
-- 伪爆贴(data_quality_flags.synthetic=true)= 人工刷的假指标(笔记状态含「关注」)或状态标爆但无可测曝光,
-- 指标不可信 → 【最高优先级规则:一律不算爆款】。下列所有「爆/大爆」命中计数都剔除 synthetic,
-- 【不分 tier_source】(状态字段 / 数值推断都剔)—— 因为数值推断建立在(可能造假的)互动量上,
-- 一条既标「关注」又因高(刷出来的)互动被推断成爆的帖必须排除(2026-06-10 用户拍板)。
-- 非爆 tier(趴/预备/风控)的 synthetic 行不受影响,照常计入规模/分布。

-- 1) 情绪杠杆表现(命中率排行 + 漏斗)—— 揭示"最常用 ≠ 最有效"
create or replace view public.v_dash_lever_perf with (security_invoker = false) as
select
  emotional_lever                                                      as lever,
  count(*)                                                             as n,
  count(*) filter (where tier in ('爆','大爆') and (data_quality_flags->>'synthetic') is distinct from 'true')                        as hits,
  round(100.0 * count(*) filter (where tier in ('爆','大爆') and (data_quality_flags->>'synthetic') is distinct from 'true') / count(*), 1) as hit_rate,
  round(avg(interactions))::int                                        as avg_inter
from truth_vault.notes
where emotional_lever is not null and emotional_lever <> ''
group by emotional_lever
having count(*) >= 5
order by hit_rate desc;
comment on view public.v_dash_lever_perf is '看板深挖:情绪杠杆命中率/平均互动(n>=5;剔伪爆贴)。';

-- 2) 效价 × 强度 命中矩阵 —— 高强度负面 = 爆款引擎
create or replace view public.v_dash_valence_matrix with (security_invoker = false) as
select
  emotional_valence                                                    as valence,
  emotional_intensity                                                  as intensity,
  count(*)                                                             as n,
  count(*) filter (where tier in ('爆','大爆') and (data_quality_flags->>'synthetic') is distinct from 'true')                        as hits,
  round(100.0 * count(*) filter (where tier in ('爆','大爆') and (data_quality_flags->>'synthetic') is distinct from 'true') / count(*), 1) as hit_rate,
  round(avg(interactions))::int                                        as avg_inter
from truth_vault.notes
where emotional_valence is not null and emotional_intensity is not null
group by emotional_valence, emotional_intensity;
comment on view public.v_dash_valence_matrix is '看板深挖:情绪效价×强度 命中矩阵(剔伪爆贴)。';

-- 3) 人性原型表现(target_audience/archetype 数组 unnest)—— 焦虑系原型胜出
create or replace view public.v_dash_archetype_perf with (security_invoker = false) as
select
  a                                                                    as archetype,
  count(*)                                                             as n,
  count(*) filter (where n.tier in ('爆','大爆') and (n.data_quality_flags->>'synthetic') is distinct from 'true')                      as hits,
  round(100.0 * count(*) filter (where n.tier in ('爆','大爆') and (n.data_quality_flags->>'synthetic') is distinct from 'true') / count(*), 1) as hit_rate,
  round(avg(n.interactions))::int                                      as avg_inter
from truth_vault.notes n, lateral unnest(n.human_truth_archetype) a
where n.human_truth_archetype is not null
group by a
having count(*) >= 5
order by hit_rate desc;
comment on view public.v_dash_archetype_perf is '看板深挖:人性原型命中率(n>=5;剔伪爆贴)。';

-- 4) 意图表现 —— 种草(traffic)出爆款,转化(conversion)不出
create or replace view public.v_dash_intent_perf with (security_invoker = false) as
select
  intent,
  count(*)                                                             as n,
  count(*) filter (where tier in ('爆','大爆') and (data_quality_flags->>'synthetic') is distinct from 'true')                        as hits,
  round(100.0 * count(*) filter (where tier in ('爆','大爆') and (data_quality_flags->>'synthetic') is distinct from 'true') / count(*), 1) as hit_rate,
  round(avg(read_rate)::numeric, 4)                                    as read_rate,
  round(avg(interaction_rate)::numeric, 4)                             as inter_rate
from truth_vault.notes
where intent is not null
group by intent
order by n desc;
comment on view public.v_dash_intent_perf is '看板深挖:意图(种草/转化)命中率+漏斗率(剔伪爆贴)。';

-- 5) tier 漏斗 —— 趴→预备→爆→大爆,read_rate 随层级抬升、曝光指数级放大
--    伪爆贴(假指标)不进【爆/大爆】层,以免污染各层均值;synthetic 的非爆行照常计入。
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
  and not (tier in ('爆','大爆') and (data_quality_flags->>'synthetic') is not distinct from 'true')
group by tier;
comment on view public.v_dash_tier_funnel is '看板深挖:tier 漏斗(各层曝光/读完率/互动;伪爆贴不进爆层)。';

-- 6) 分战线表现(规模+命中)—— 对齐既有公开口径:只露 project_id + 品类,不露品牌/产品名
create or replace view public.v_dash_project_perf with (security_invoker = false) as
select
  n.project_id,
  p.category,
  p.platform,
  count(n.note_id)                                                     as notes,
  count(*) filter (where n.tier in ('爆','大爆')
    and (n.data_quality_flags->>'synthetic') is distinct from 'true') as hits,
  round(100.0 * count(*) filter (where n.tier in ('爆','大爆')
    and (n.data_quality_flags->>'synthetic') is distinct from 'true') / nullif(count(n.note_id), 0), 1) as hit_rate,
  round(avg(n.impressions))::int                                       as avg_imp,
  coalesce(sum(n.impressions), 0)::bigint                              as total_imp,
  count(*) filter (where n.emotional_lever is not null and n.emotional_lever <> '') as essence
from truth_vault.notes n
join truth_vault.projects p on p.project_id = n.project_id
group by n.project_id, p.category, p.platform;
comment on view public.v_dash_project_perf is '看板深挖:分战线规模/命中率/总触达(不露品牌;剔伪爆贴)。';

-- 7) 分战线 tier 构成 —— 各线各自的爆款金字塔(随真数据/新增战线自动扩展)
create or replace view public.v_dash_project_tier with (security_invoker = false) as
select project_id, tier, count(*) as n
from truth_vault.notes
where tier in ('趴','预备','爆','大爆','风控')
  -- 伪爆贴(synthetic=true = 假指标/不可验证)【最高优先级】不进爆款金字塔的【爆/大爆】层,
  -- 不分 tier_source(状态字段 / 数值推断都剔);非爆 tier 的 synthetic 行照常计入。
  and not (tier in ('爆','大爆')
           and (data_quality_flags->>'synthetic') is not distinct from 'true')
group by project_id, tier;
comment on view public.v_dash_project_tier is '看板深挖:分战线 tier 构成(伪爆贴不进爆层)。';

-- 8) 受众命中率(target_audience 数组 unnest)—— "通用/泛人群"是命中黑洞,具体共情受众胜出
create or replace view public.v_dash_audience_perf with (security_invoker = false) as
select
  a                                                                    as audience,
  count(*)                                                             as n,
  count(*) filter (where n.tier in ('爆','大爆')
    and (n.data_quality_flags->>'synthetic') is distinct from 'true') as hits,
  round(100.0 * count(*) filter (where n.tier in ('爆','大爆')
    and (n.data_quality_flags->>'synthetic') is distinct from 'true') / count(*), 1) as hit_rate,
  round(avg(n.interactions))::int                                      as avg_inter
from truth_vault.notes n, lateral unnest(n.target_audience) a
where n.target_audience is not null
group by a
having count(*) >= 10
order by hit_rate desc;
comment on view public.v_dash_audience_perf is '看板深挖:受众命中率(n>=10;剔伪爆贴)。';

-- 9) 内容形态命中率 —— 情感叙事出爆款,直给推荐/横评对比不出
create or replace view public.v_dash_format_perf with (security_invoker = false) as
select
  content_format                                                       as fmt,
  count(*)                                                             as n,
  count(*) filter (where tier in ('爆','大爆')
    and (data_quality_flags->>'synthetic') is distinct from 'true') as hits,
  round(100.0 * count(*) filter (where tier in ('爆','大爆')
    and (data_quality_flags->>'synthetic') is distinct from 'true') / count(*), 1) as hit_rate,
  round(avg(interactions))::int                                        as avg_inter
from truth_vault.notes
where content_format is not null and content_format <> ''
group by content_format
having count(*) >= 10
order by hit_rate desc;
comment on view public.v_dash_format_perf is '看板深挖:内容形态命中率(n>=10;剔伪爆贴)。';

-- 10) 触达集中度(幂律)—— 不到 4% 的爆款吃掉七成以上触达;单行
--     伪爆贴(假指标)不计入爆款触达占比 hit_reach_share / hit_note_pct(分母 total 仍为全部 impressions>0)。
create or replace view public.v_dash_reach_concentration with (security_invoker = false) as
with base as (
  select impressions, tier, data_quality_flags from truth_vault.notes where impressions is not null and impressions > 0
),
ranked as (
  select impressions, tier, data_quality_flags,
    ntile(100) over (order by impressions desc) as pct,
    sum(impressions) over ()                    as total,
    count(*) over ()                            as cnt
  from base
)
select
  max(cnt)                                                             as total_notes,
  max(total)::bigint                                                   as total_imp,
  round(100.0 * sum(impressions) filter (where pct <= 1) / max(total), 1)  as top1_share,
  round(100.0 * sum(impressions) filter (where pct <= 5) / max(total), 1)  as top5_share,
  round(100.0 * sum(impressions) filter (where pct <= 10) / max(total), 1) as top10_share,
  round(100.0 * sum(impressions) filter (where tier in ('爆','大爆') and (data_quality_flags->>'synthetic') is distinct from 'true') / max(total), 1) as hit_reach_share,
  round(100.0 * count(*) filter (where tier in ('爆','大爆') and (data_quality_flags->>'synthetic') is distinct from 'true') / max(cnt), 2) as hit_note_pct
from ranked;
comment on view public.v_dash_reach_concentration is '看板深挖:触达幂律(top1/5/10% 与爆款的触达占比;剔伪爆贴)。';

-- GRANT(包 IF EXISTS;裸 PG / CI 无这些角色,对齐 notes_v1_2.sql 约定)
do $$
declare v text; r text;
begin
  foreach v in array array['v_dash_lever_perf','v_dash_valence_matrix','v_dash_archetype_perf','v_dash_intent_perf','v_dash_tier_funnel','v_dash_project_perf','v_dash_project_tier','v_dash_audience_perf','v_dash_format_perf','v_dash_reach_concentration'] loop
    foreach r in array array['anon','authenticated','service_role'] loop
      if exists (select 1 from pg_roles where rolname = r) then
        execute format('grant select on public.%I to %I', v, r);
      end if;
    end loop;
  end loop;
end $$;
