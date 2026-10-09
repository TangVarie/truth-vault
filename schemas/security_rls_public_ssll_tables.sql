-- B-22 (2026-10-08 架构审计) · 2026-10-09 已对生产 apply (D-101)。
-- public 下 5 张 ssll 表以前没开 RLS, 且 anon 有 SELECT: 任何拿着 anon key 的人都能经 PostgREST 把
-- reference_samples.post_body / cover_image_b64 / top_comments / ai_analysis、stage_logs.input_data /
-- output_data、outputs.prompt_system、projects.brief 整表拉走 (~1,512 行)。写权限 2026-08 已收
-- (security_revoke_anon_write_public_tables.sql), 这里收读。
--
-- 为什么不动 18 个 v_dash_* 视图: 它们是有意的 SECURITY DEFINER (dashboard_views_v1.sql 头部), 全是不可更新的
-- 聚合视图, anon 只有 SELECT; 看板 (Vercel, anon key) 只经它们读。改成 security_invoker 会让 anon 直接撞
-- truth_vault 的 RLS/无 USAGE → 看板全空。advisor 的 18 条 security_definer_view 记为已接受例外。
--
-- 为什么给 authenticated 留只读 policy: ssll (三生六部) 运行时用哪把 key 没查实 (仓不在本会话; 文档说
-- service_role, 它 BYPASSRLS 不受影响)。若它其实走 Supabase Auth 的登录会话 (authenticated), 不留这条
-- policy 它会静默读到 0 行。anon = 公网, 一律收。
--
-- 幂等; 回滚在文件末尾。
BEGIN;

ALTER TABLE public.projects          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pipeline_runs     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stage_logs        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.outputs           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reference_samples ENABLE ROW LEVEL SECURITY;

DO $$ DECLARE t TEXT; BEGIN
  FOREACH t IN ARRAY ARRAY['projects','pipeline_runs','stage_logs','outputs','reference_samples'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename=t AND policyname='ssll_authenticated_read') THEN
      EXECUTE format('CREATE POLICY ssll_authenticated_read ON public.%I FOR SELECT TO authenticated USING (true)', t);
    END IF;
  END LOOP;
END $$;

REVOKE SELECT, REFERENCES, TRIGGER
  ON public.projects, public.pipeline_runs, public.stage_logs, public.outputs, public.reference_samples
  FROM anon;

COMMIT;

-- 验证 (apply 后实测 2026-10-09):
--   SELECT relname, relrowsecurity FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind='r';  -- 5 行全 t
--   SET ROLE anon; SELECT count(*) FROM public.reference_samples;   -- 42501 permission denied
--   SET ROLE anon; SELECT notes FROM public.v_dash_overview;         -- 6300 (看板照常)
--   RESET ROLE;
--
-- 回滚:
--   ALTER TABLE public.<t> DISABLE ROW LEVEL SECURITY;  -- ×5
--   DROP POLICY ssll_authenticated_read ON public.<t>;  -- ×5
--   GRANT SELECT, REFERENCES, TRIGGER ON public.<t> TO anon;  -- ×5
