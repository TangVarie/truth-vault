-- ─────────────────────────────────────────────────────────────
-- security_revoke_anon_write_dash_views.sql
-- 纵深防御:撤掉 anon / authenticated 对 public.v_dash_* 看板视图的写权限。
--
-- 现状(2026-08 实测 kduysqedr):18 个 v_dash_* 视图全部对 anon / authenticated
-- 持有 DELETE,INSERT,REFERENCES,SELECT,TRIGGER,TRUNCATE,UPDATE —— 来自 Supabase
-- 建库时的 `ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO
-- anon, authenticated`,不是谁手动开的。
--
-- ⚠️ 现在【打不穿】,这是纵深防御不是补漏:
--    这 18 个视图全是聚合视图,information_schema.views 里
--    is_updatable = is_insertable_into = 'NO' —— PostgreSQL 在【重写阶段】就拒绝
--    (cannot insert into view ... 没有 INSTEAD OF 触发器),跟有没有权限无关。
--    所以今天拿着公开的 anon key 也写不进去。
--
-- 那为什么还要撤:这些视图是 security_invoker=false(SECURITY DEFINER 语义),
--    以 owner 身份跑、绕开底层 truth_vault 表的 RLS —— anon 能读到聚合数就是靠它。
--    哪天有人在 public 里加一个【单表直通】的 v_dash_xxx(那种视图 PG 会判定为
--    auto-updatable),它会自动继承同一套 default privileges,于是
--    "anon key 可写 → 经 SECURITY DEFINER 视图穿透 RLS 写进 truth_vault"。
--    此时不会有任何报错、也没有任何地方看得出来。先把权限收干净,断掉这条路径。
--
-- 这条路径【实测验证过】(PG 16, 本文件的 CI 步骤会复跑一遍):
--    CREATE VIEW v_dash_probe AS SELECT id, n FROM base;  -- 单表直通
--    → information_schema.views.is_insertable_into = 'YES'
--    → SET ROLE anon; INSERT INTO v_dash_probe ...        → INSERT 0 1, 行进了 base
--    跑完本文件后同一句                                    → ERROR: permission denied
--    而聚合视图(现有这 18 个)同样条件下是                   → ERROR: cannot insert into view
--                                                            (aggregate ... not automatically updatable)
--
-- 决策沿用 security_revoke_anon_write_public_tables.sql:不开 RLS、保留 SELECT
-- (看板服务端要读)、只撤写权限。service_role 不受影响 → 后端照常写。
--
-- ⚠️ 只对【运行时已存在】的 v_dash_* 生效。新增看板视图后请重跑本文件
--    (幂等、可反复跑)。没有改 ALTER DEFAULT PRIVILEGES —— 那会波及 public 下
--    所有未来的表,而 public 是与三生六部共享的 schema(dashboard/lib/supabase.ts:11
--    记了它 RLS-off 且 anon 可读),不该由本仓单方面改默认值。
--
-- 幂等 + 裸 PG / CI 安全:视图或角色不存在则跳过。REVOKE 本身幂等。
-- ─────────────────────────────────────────────────────────────

do $$
declare
  v text;
  r text;
  n int := 0;
  roles text[] := array['anon','authenticated'];
begin
  for v in
    select table_name
      from information_schema.views
     where table_schema = 'public'
       and table_name like 'v\_dash\_%'   -- \_ 转义:_ 在 LIKE 里是通配符
     order by table_name
  loop
    foreach r in array roles loop
      if exists (select 1 from pg_roles where rolname = r) then
        execute format(
          'revoke insert, update, delete, truncate on table public.%I from %I', v, r
        );
      end if;
    end loop;
    n := n + 1;
  end loop;
  raise notice 'revoked anon/authenticated writes on % v_dash_* view(s)', n;
end $$;
