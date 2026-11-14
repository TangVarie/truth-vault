-- Shared role assertions for check_ssll_authenticated_read.sql; synthetic scratch DB only.
SET ROLE authenticated;
SELECT (sum(n) = 1) AS only_scoped_row_visible FROM (
  SELECT count(*) n FROM public.projects UNION ALL SELECT count(*) FROM public.pipeline_runs
  UNION ALL SELECT count(*) FROM public.stage_logs UNION ALL SELECT count(*) FROM public.outputs
  UNION ALL SELECT count(*) FROM public.reference_samples
) counts \gset
SELECT (n = 2) AS authenticated_dashboard_unchanged FROM public.v_dash_security_probe \gset
RESET ROLE;
\if :only_scoped_row_visible
\else
  \echo 'authenticated can still read cross-project rows'
  SELECT 1 / 0; -- ON_ERROR_STOP must fail on PostgreSQL 16 too
\endif
\if :authenticated_dashboard_unchanged
\else
  \echo 'authenticated dashboard changed'
  SELECT 1 / 0; -- ON_ERROR_STOP must fail on PostgreSQL 16 too
\endif

SET ROLE service_role;
SELECT (sum(n) = 6) AS service_unchanged FROM (
  SELECT count(*) n FROM public.projects UNION ALL SELECT count(*) FROM public.pipeline_runs
  UNION ALL SELECT count(*) FROM public.stage_logs UNION ALL SELECT count(*) FROM public.outputs
  UNION ALL SELECT count(*) FROM public.reference_samples
) counts \gset
RESET ROLE;
\if :service_unchanged
\else
  \echo 'service_role access changed'
  SELECT 1 / 0; -- ON_ERROR_STOP must fail on PostgreSQL 16 too
\endif
SET ROLE anon;
SELECT (n = 2) AS anon_dashboard_unchanged FROM public.v_dash_security_probe \gset
RESET ROLE;
\if :anon_dashboard_unchanged
\else
  \echo 'anon dashboard access changed'
  SELECT 1 / 0; -- ON_ERROR_STOP must fail on PostgreSQL 16 too
\endif
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = 'public' AND policyname = 'ssll_authenticated_read') THEN
    RAISE EXCEPTION 'global policy survived';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = 'public' AND policyname = 'existing_project_scoped') THEN
    RAISE EXCEPTION 'unrelated scoped policy was removed';
  END IF;
END $$;
\echo 'OK: global reads removed; scoped policy, service_role and dashboard preserved; reruns safe'
