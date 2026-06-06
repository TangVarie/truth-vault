import { createClient } from "@supabase/supabase-js";

/**
 * 服务端 Supabase 客户端(只在 Server Components / Route Handlers 里用)。
 *
 * 看板**只读** public.v_dash_overview 这一个安全聚合视图(只吐大数、不吐明细),
 * 所以用**最小权限 anon key** 即可 —— anon 读不到 truth_vault / autowriter 的原始行
 * (那些表 RLS-on 无策略),只能 select 我们 GRANT 给它的聚合视图。详见 docs/24 §3 / §5。
 *
 * ⚠️ key 只在服务端用,绝不进浏览器、绝不提交进 git。
 * ⚠️ 本共享库的 `public` schema(三生六部)当前 RLS-off 且 anon 可读 —— 故 anon key 仍属敏感、
 *    勿外泄;看板只在服务端拿它读聚合视图,不把 key 发给前端。
 */
export function getSupabase() {
  const url = process.env.SUPABASE_URL;
  // 优先最小权限 anon key;兼容历史上配过的 service_role。
  const key = process.env.SUPABASE_ANON_KEY ?? process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return null;
  return createClient(url, key, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}
