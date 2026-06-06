-- ─────────────────────────────────────────────────────────────
-- dashboard_views_v5_pulse.sql
-- 系统脉搏 / 接口状态监控 —— 全部从真实列派生,无写死状态。
-- 看板「实时」的底气:每个状态灯都对应一个真实信号(同步时间戳 / 计数)。
-- 单行视图,前端据此渲染数据新鲜度 + 各接口/板块 live/idle/planned。
-- security_invoker=false:以视图属主身份读 truth_vault(anon 不直连底表)。
-- ─────────────────────────────────────────────────────────────

create or replace view public.v_dash_system_pulse with (security_invoker = false) as
select
  (select count(*)                  from truth_vault.notes)                                        as notes_total,
  (select max(updated_at)           from truth_vault.notes)                                        as last_update,
  (select max(ingested_at)          from truth_vault.notes)                                        as last_ingest,
  (select count(*)                  from truth_vault.notes where feishu_record_id is not null)     as feishu_n,
  (select count(*)                  from truth_vault.notes where essence_annotated_at is not null) as annotated_n,
  (select max(essence_annotated_at) from truth_vault.notes)                                        as annotated_last,
  (select count(*)                  from truth_vault.notes where synced_to_ssll_at is not null)    as ssll_n,
  (select max(synced_to_ssll_at)    from truth_vault.notes)                                        as ssll_last,
  (select count(*)                  from truth_vault.notes where synced_to_aw_at is not null)      as aw_n,
  (select max(synced_to_aw_at)      from truth_vault.notes)                                        as aw_last,
  (select count(distinct account_id) from truth_vault.notes)                                       as accounts_n,
  (select count(*)                  from truth_vault.metric_snapshots)                             as snaps_n,
  (select max(collected_at)         from truth_vault.metric_snapshots)                             as snaps_last,
  (select count(*)                  from truth_vault.audit_log)                                     as audit_n,
  (select max(occurred_at)          from truth_vault.audit_log)                                     as audit_last,
  (select count(*)                  from truth_vault.projects)                                      as projects_n,
  (select count(*)                  from public.pipeline_runs)                                      as pipeline_runs_n,
  now()                                                                                             as server_now;
comment on view public.v_dash_system_pulse is '看板系统脉搏:数据新鲜度 + 各接口/板块真实同步状态(单行)。';

-- GRANT(包 IF EXISTS;裸 PG / CI 无这些角色,对齐 notes_v1_2.sql 约定)
do $$
declare r text;
begin
  foreach r in array array['anon','authenticated','service_role'] loop
    if exists (select 1 from pg_roles where rolname = r) then
      execute format('grant select on public.v_dash_system_pulse to %I', r);
    end if;
  end loop;
end $$;
