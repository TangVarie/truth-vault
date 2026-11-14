-- public 业务表的 fresh-install 安全基线。
-- 2026-11-14 外部评审 F07：不再创建 ssll_authenticated_read 全局读策略。
-- 旧库升级请用 security_revoke_authenticated_ssll_read.sql；本文件重跑也会移除该旧策略。
-- service_role 的表级授权与 BYPASSRLS 保持原样，18 个 public.v_dash_* 接口不动。
-- authenticated 如有真正需求，须另建按项目/工作区授权的策略；身份有效不等于能读全部客户。
-- 部署前先按 docs/security-authenticated-read-removal.md 核实消费者，不在这里连接生产。
BEGIN;

ALTER TABLE public.projects          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pipeline_runs     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stage_logs        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.outputs           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reference_samples ENABLE ROW LEVEL SECURITY;

DO $$ DECLARE t TEXT; BEGIN
  FOREACH t IN ARRAY ARRAY['projects','pipeline_runs','stage_logs','outputs','reference_samples'] LOOP
    EXECUTE format('DROP POLICY IF EXISTS ssll_authenticated_read ON public.%I', t);
  END LOOP;
END $$;

REVOKE SELECT, REFERENCES, TRIGGER
  ON public.projects, public.pipeline_runs, public.stage_logs, public.outputs, public.reference_samples
  FROM anon;

COMMIT;
