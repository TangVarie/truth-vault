-- 只在空的一次性本地/CI数据库执行；不要在生产数据库运行本测试。
-- psql -v ON_ERROR_STOP=1 -f scripts/check_ssll_authenticated_read.sql
-- 使用真实 Postgres 角色/RLS，先证明旧策略会广读，再验增量、幂等和fresh基线。
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public' AND c.relname IN
               ('projects','pipeline_runs','stage_logs','outputs','reference_samples')) THEN
    RAISE EXCEPTION 'security test requires an empty disposable database';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN CREATE ROLE anon; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN CREATE ROLE authenticated; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN CREATE ROLE service_role BYPASSRLS; END IF;
  IF NOT (SELECT rolbypassrls FROM pg_roles WHERE rolname = 'service_role') THEN
    RAISE EXCEPTION 'test service_role must have BYPASSRLS';
  END IF;
END $$;
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
CREATE TABLE public.projects (value text);
CREATE TABLE public.pipeline_runs (value text);
CREATE TABLE public.stage_logs (value text);
CREATE TABLE public.outputs (value text);
CREATE TABLE public.reference_samples (value text);
DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['projects','pipeline_runs','stage_logs','outputs','reference_samples'] LOOP
    EXECUTE format('INSERT INTO public.%I VALUES (''secret'')', t);
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('GRANT SELECT ON public.%I TO authenticated, service_role', t);
    EXECUTE format('CREATE POLICY ssll_authenticated_read ON public.%I FOR SELECT TO authenticated USING (true)', t);
  END LOOP;
END $$;
INSERT INTO public.projects VALUES ('visible');
CREATE POLICY existing_project_scoped ON public.projects FOR SELECT TO authenticated USING (value = 'visible');
CREATE VIEW public.v_dash_security_probe WITH (security_invoker = false) AS SELECT count(*) AS n FROM public.projects;
GRANT SELECT ON public.v_dash_security_probe TO anon, authenticated, service_role;

SET ROLE authenticated;
SELECT (sum(n) = 6) AS old_policy_reads_all FROM (
  SELECT count(*) n FROM public.projects UNION ALL SELECT count(*) FROM public.pipeline_runs
  UNION ALL SELECT count(*) FROM public.stage_logs UNION ALL SELECT count(*) FROM public.outputs
  UNION ALL SELECT count(*) FROM public.reference_samples
) counts \gset
RESET ROLE;
\if :old_policy_reads_all
\else
  \echo 'old policy precondition failed'
  SELECT 1 / 0; -- ON_ERROR_STOP must fail on PostgreSQL 16 too
\endif

-- 即使某表 RLS 被关过，增量也必须恢复保护，不能只删一个不起作用的 policy。
ALTER TABLE public.reference_samples DISABLE ROW LEVEL SECURITY;
\ir ../schemas/security_revoke_authenticated_ssll_read.sql
\ir ../schemas/security_revoke_authenticated_ssll_read.sql
\ir check_ssll_authenticated_read_access.sql

-- 独立验证 fresh 基线：重新造回旧策略，不能让前面的增量替它遮住缺陷。
DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['projects','pipeline_runs','stage_logs','outputs','reference_samples'] LOOP
    EXECUTE format('CREATE POLICY ssll_authenticated_read ON public.%I FOR SELECT TO authenticated USING (true)', t);
  END LOOP;
END $$;
\ir ../schemas/security_rls_public_ssll_tables.sql
\ir ../schemas/security_rls_public_ssll_tables.sql
\ir check_ssll_authenticated_read_access.sql
