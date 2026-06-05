import { createClient } from "@supabase/supabase-js";

/**
 * 服务端 Supabase 客户端(只在 Server Components / Route Handlers 里用)。
 * ⚠️ service_role key 永远不进浏览器 —— 本文件只被服务端 import。
 * 共享库:同一个 Supabase 里有 truth_vault / autowriter / public 三个 schema,
 * 用 .schema("...") 切换。详见 docs/24-dashboard-plan.md §3。
 */
export function getSupabase() {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return null;
  return createClient(url, key, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}
