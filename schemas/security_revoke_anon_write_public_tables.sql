-- ─────────────────────────────────────────────────────────────
-- security_revoke_anon_write_public_tables.sql
-- 防篡改:撤掉 anon / authenticated 对若干 public.* 表的写权限。
--
-- 背景:看板客户端内嵌的 anon key 是公开的。这些 public 表 RLS 关闭,
-- 默认 anon/authenticated 可读写 → 任何拿到 anon key 的人都能改库。
-- 决策(用户):不开 RLS、保留读权限(不影响现有读取方),仅撤写权限。
-- service_role 不受影响(只 REVOKE anon/authenticated)→ 后端 app 照常写。
--
-- 幂等 + 裸 PG / CI 安全:表或角色不存在则跳过。REVOKE 本身幂等。
-- ─────────────────────────────────────────────────────────────

do $$
declare
  t text;
  r text;
  tbls  text[] := array['reference_samples','projects','outputs','pipeline_runs','stage_logs'];
  roles text[] := array['anon','authenticated'];
begin
  foreach t in array tbls loop
    if to_regclass('public.' || t) is not null then
      foreach r in array roles loop
        if exists (select 1 from pg_roles where rolname = r) then
          execute format('revoke insert, update, delete, truncate on table public.%I from %I', t, r);
        end if;
      end loop;
    end if;
  end loop;
end $$;
