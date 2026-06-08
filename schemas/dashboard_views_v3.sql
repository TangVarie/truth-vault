-- dashboard_views_v3.sql · 看板 v3 数据层(docs/24 + v5 编辑级)
--
-- 在 v2 基础上追加:
--   1) v_dash_matrix    —— 策略 × 受众 共振矩阵(给热力图)
--   2) v_dash_top_hits  —— Top 爆款拆解榜(只暴露 project/lever/指标,绝不暴露 title/body 防泄)
--
-- 仍是 public 只读安全聚合;security_invoker=false 以 owner 身份读 RLS-on 的 truth_vault;
-- GRANT 包 IF EXISTS(裸 PG / CI 无 Supabase 角色)。已 apply prod。

create or replace view public.v_dash_matrix
  with (security_invoker = false) as
select n.emotional_lever as lever, a as audience, count(*) as n
from truth_vault.notes n, lateral unnest(n.target_audience) a
where n.emotional_lever is not null and n.emotional_lever <> ''
  and a is not null and a <> ''
group by 1, 2;

comment on view public.v_dash_matrix is '看板:策略 × 受众 共振矩阵(注 target_audience 是 text[],需 unnest)。';

create or replace view public.v_dash_top_hits
  with (security_invoker = false) as
select
  row_number() over (order by interactions desc nulls last) as rank,
  project_id,
  emotional_lever as lever,
  tier,
  interactions,
  reads,
  impressions
from truth_vault.notes
where tier in ('爆','大爆') and tier_source = '状态字段'
  -- 伪爆贴(synthetic=true)不进 Top 爆款拆解榜 —— 状态标爆但源头无可测曝光, 不可验证。
  and (data_quality_flags->>'synthetic') is distinct from 'true'
  and interactions is not null
order by interactions desc nulls last
limit 8;

comment on view public.v_dash_top_hits is '看板:Top 爆款拆解榜(只暴露 project/lever/指标,不取 title/body 防泄)。';

do $$
declare v text; r text;
begin
  foreach v in array array['v_dash_matrix','v_dash_top_hits'] loop
    foreach r in array array['anon','authenticated','service_role'] loop
      if exists (select 1 from pg_roles where rolname = r) then
        execute format('grant select on public.%I to %I', v, r);
      end if;
    end loop;
  end loop;
end $$;
