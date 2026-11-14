-- F07 · 增量撤销不按项目隔离的 authenticated 全局读策略。
-- 仅这五张表、仅旧策略名；不收 service_role 权限，不改 public.v_dash_*。
-- RLS 必须开启：只删 policy 而 RLS 关闭时并不能收读。其它合法的窄策略保留。
-- 幂等；要求五张表存在，缺表应报错而不是假称已修复。
-- 部署前核调用者与授权，见 docs/security-authenticated-read-removal.md。
BEGIN;

DO $$ DECLARE t TEXT; BEGIN
  FOREACH t IN ARRAY ARRAY['projects','pipeline_runs','stage_logs','outputs','reference_samples'] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS ssll_authenticated_read ON public.%I', t);
  END LOOP;
END $$;

COMMIT;
