-- 收回登录用户 (authenticated) 对 public 下 5 张三省六部表的读权限 (十三件事第 11 件, D-154 / S-16; owner 2026-11-15 定了做)。
--
-- 现状 (2026-11-16 只读核过): 这 5 张表开着 RLS, 匿名 (anon) 早就读不到 (security_rls_public_ssll_tables.sql, 2026-10-09);
-- 但各留着一条 ssll_authenticated_read 策略 (FOR SELECT TO authenticated USING (true)), 任何登录账号都能整表读
-- (reference_samples 里是爆款正文和评论)。当时留它是因为没查实三省六部用哪把 key; 后来查实它走 service_role
-- (不受 RLS 管), 仓里也没有任何代码靠这条策略。auth.users 6 个, 最后一次登录 2026-08-19, 没人在用登录。
--
-- 这份 SQL 做两件事, 都只收不放:
--   ① 删掉 5 张表上的 ssll_authenticated_read 策略 —— 登录账号读这 5 张表得 0 行;
--   ② 把 authenticated 在这 5 张表上的 SELECT / REFERENCES / TRIGGER 授权也收掉 —— 以后哪怕有人误加一条策略, 也读不到。
-- 不动的: service_role (三省六部、TV 的脚本) 照常读写; 看板走的 18 个 v_dash_* 视图不在这 5 张表里, 照常。
--
-- 怎么跑: owner 在 Supabase SQL editor 整份跑一次。可以重跑 (DROP POLICY IF EXISTS; REVOKE 重复执行不报错)。
-- 另请在控制台关掉注册入口 (Authentication → Sign In / Providers → 关「Allow new users to sign up」): 两样一起才算关上。
BEGIN;

DO $$ DECLARE t TEXT; BEGIN
  FOREACH t IN ARRAY ARRAY['projects','pipeline_runs','stage_logs','outputs','reference_samples'] LOOP
    IF to_regclass(format('public.%I', t)) IS NOT NULL THEN
      EXECUTE format('DROP POLICY IF EXISTS ssll_authenticated_read ON public.%I', t);
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        EXECUTE format('REVOKE SELECT, REFERENCES, TRIGGER ON public.%I FROM authenticated', t);
      END IF;
    END IF;
  END LOOP;
END $$;

COMMIT;

-- 验证 (跑完之后):
--   SELECT tablename, policyname FROM pg_policies WHERE schemaname='public' AND policyname='ssll_authenticated_read';  -- 0 行
--   SELECT table_name, privilege_type FROM information_schema.role_table_grants
--    WHERE table_schema='public' AND grantee='authenticated'
--      AND table_name IN ('projects','pipeline_runs','stage_logs','outputs','reference_samples');                      -- 0 行
--
-- 回滚 (对 5 张表各跑一次):
--   GRANT SELECT ON public.<t> TO authenticated;
--   CREATE POLICY ssll_authenticated_read ON public.<t> FOR SELECT TO authenticated USING (true);
