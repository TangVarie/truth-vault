import "server-only";
import postgres from "postgres";

/**
 * 工作台取数 (W-63, D-169, docs/35 第 3 节)。只在服务端跑：上面那行 server-only，客户端组件一引用它构建就失败。
 *
 * - 身份：WORKBENCH_DATABASE_URL 里的 tv_workbench_ro (只读角色，只能读 workbench.v_* 九个打过码的视图)。
 *   走 Supabase 连接池的事务模式，所以 prepare: false。不用 anon key、不用 service_role。
 * - 不复用 lib/dashboard-data.ts 的 getDashboardData()：它把出错吞成 0、乘 AMPLIFY，还被公开页共用。
 *   这里每个视图单独取，出错就记「取数失败」和一个短代码，页面照样画别的块。
 * - 日志只记视图名和错误码，不打行内容 (Vercel 的运行日志团队都看得到，而且会留存)。
 * - 连接串解析失败时 postgres.js 同步抛 TypeError，错误对象的 input 里是整条连接串 (含密码)。所以建客户端包在 try 里，
 *   出错只回 bad_url，错误对象一个字都不记、不往上抛 (往上抛会被 Next 整个打进运行日志)。
 * - ssl: "require" = 走 TLS 加密，但不校验服务器证书 (postgres.js 的 require 就是这样)。要校验得配 Supabase 的 CA，v0 不做 (docs/35 第 3.2 节)。
 */

export const WB_VIEWS = [
  "v_status",
  "v_accounts",
  "v_content_counts",
  "v_content_notes",
  "v_watch_24h",
  "v_watch_72h",
  "v_exposure_hints",
  "v_boost_curves",
  "v_shadow_check",
] as const;
export type WbView = (typeof WB_VIEWS)[number];

export type Got<T> = { ok: true; rows: T[] } | { ok: false; code: string };

export type StatusRow = {
  day: string;
  taken_at: string;
  rule_version: string;
  n_days: number;
  first_day: string;
  seq: number | null;
  project_id: string | null;
  platform: string | null;
  posts_30d: number | null;
  last_post_day: string | null;
  data_as_of: string | null;
  median_impressions: number | null;
  b1: Record<string, unknown> | null;
  b2: Record<string, unknown> | null;
  b3a: Record<string, unknown> | null;
  b3b: Record<string, unknown> | null;
  b4: Record<string, unknown> | null;
  b5: Record<string, unknown> | null;
};
export type AccountRow = {
  project_id: string; account_code: string; name_hint: string; tier: string; downgrade: boolean;
  posts_here: number; graded_here: number; hits_here: number; other_hit: boolean; last_post_here: string | null;
  seq: number; code_clash: boolean;
};
export type ContentCountRow = {
  project_id: string; seq: number; hint: string; side: string; scope: string; w64: string;
  n_flag: number; n_noflag: number; n_unlabeled: number;
  graded_flag: number; hits_flag: number; graded_noflag: number; hits_noflag: number;
  expo_known_flag: number; expo_hi_flag: number; expo_known_noflag: number; expo_hi_noflag: number;
};
export type ContentNoteRow = {
  project_id: string; note_code: string; account_code: string | null; publish_day: string;
  plus_hints: string[]; minus_hints: string[]; unlabeled: string[]; body_empty: boolean;
};
export type Watch24Row = {
  project_id: string; note_code: string; account_code: string | null; publish_day: string;
  hours_24h: number | null; comments_24h: number | null; n_prior: number | null; p90_prior: number | null;
  mid_rank: number | null; status: string; comments_now: number | null; over_line_now: boolean | null; seeded_known: number;
};
export type Watch72Row = {
  project_id: string; note_code: string; account_code: string | null; publish_day: string;
  hours_72h: number | null; impressions_72h: number | null; reads_72h: number | null; ctr_72h: number | null;
  median_impressions: number | null; rank_in_project: number; n_prior: number | null; mid_rank: number | null;
  impressions_now: number | null;
};
export type ExposureRow = {
  project_id: string; note_code: string; account_code: string | null; publish_day: string;
  hour_bj: number | null; hour_status: string; evening: boolean | null; weekend: boolean | null; same_acct_3d: boolean | null;
  impressions_now: number | null; median_impressions: number | null;
};
export type BoostRow = {
  project_id: string; event_code: string; note_code: string; boost_date: string; publish_day: string | null;
  days_after_publish: number | null; seeded_on_maintain: number | null;
  comments_base: number | null; comments_base_status: string | null;
  comments_d0: number | null; comments_d0_status: string | null;
  comments_d1: number | null; comments_d1_status: string | null;
  comments_d3: number | null; comments_d3_status: string | null;
  comments_d7: number | null; comments_d7_status: string | null;
  impressions_base: number | null; impressions_base_status: string | null;
  impressions_d7: number | null; impressions_d7_status: string | null;
  reads_base: number | null; reads_base_status: string | null;
  reads_d7: number | null; reads_d7_status: string | null;
};
export type ShadowRow = { block: string; rule_version: string; grp: string; measure: string; n: number; n_yes: number; value: number | null };

export type WorkbenchData = {
  configured: boolean;
  status: Got<StatusRow>;
  accounts: Got<AccountRow>;
  contentCounts: Got<ContentCountRow>;
  contentNotes: Got<ContentNoteRow>;
  watch24: Got<Watch24Row>;
  watch72: Got<Watch72Row>;
  exposure: Got<ExposureRow>;
  boost: Got<BoostRow>;
  shadow: Got<ShadowRow>;
};

type Sql = ReturnType<typeof postgres>;
let client: Sql | null = null;

/** 拿客户端。没配连接串 → no_url；连接串解析不了 → bad_url (常见：密码里有没编码的 / # ? % 这类字符)。 */
function db(): { sql: Sql } | { code: "no_url" | "bad_url" } {
  const url = process.env.WORKBENCH_DATABASE_URL;
  if (!url) return { code: "no_url" };
  if (!client) {
    try {
      client = postgres(url, {
        prepare: false, // 连接池事务模式不支持预编译
        max: 1,
        idle_timeout: 20,
        connect_timeout: 10,
        ssl: /[?&]sslmode=disable(&|$)/.test(url) ? false : "require",
        onnotice: () => {},
        connection: { application_name: "tv-workbench" },
      });
    } catch {
      // 不绑定、不记错误对象：它带着整条连接串
      console.error("[workbench] bad_url");
      return { code: "bad_url" };
    }
  }
  return { sql: client };
}

/** 日期列统一成 YYYY-MM-DD 字符串；时间戳列统一成 ISO 字符串。 */
function day(v: unknown): string | null {
  if (v == null) return null;
  if (v instanceof Date) return v.toISOString().slice(0, 10);
  return String(v).slice(0, 10);
}
function ts(v: unknown): string | null {
  if (v == null) return null;
  if (v instanceof Date) return v.toISOString();
  return String(v);
}
/** numeric / bigint 列 postgres.js 给的是字符串；NULL 照旧是 null (缺的就是缺，不当 0)。 */
function num(v: unknown): number | null {
  if (v == null) return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

const DATE_COLS = new Set(["day", "first_day", "last_post_day", "last_post_here", "publish_day", "boost_date"]);
const TS_COLS = new Set(["taken_at", "data_as_of"]);
const TEXT_COLS = new Set([
  "rule_version", "project_id", "platform", "account_code", "name_hint", "tier", "hint", "side", "scope", "w64",
  "note_code", "status", "hour_status", "event_code", "block", "grp", "measure",
]);

function normalize(row: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(row)) {
    if (DATE_COLS.has(k)) out[k] = day(v);
    else if (TS_COLS.has(k)) out[k] = ts(v);
    else if (TEXT_COLS.has(k) || k.endsWith("_status")) out[k] = v == null ? null : String(v);
    else if (typeof v === "boolean" || Array.isArray(v) || (v !== null && typeof v === "object")) out[k] = v;
    else out[k] = num(v);
  }
  return out;
}

function errCode(e: unknown): string {
  const c = (e as { code?: unknown } | null)?.code;
  return typeof c === "string" && c ? c.slice(0, 32) : "conn";
}

/** 这几个代码说明 SQL 还没跑 (schema 或视图不在)。页面写「还没建」。 */
export function isNotBuilt(code: string): boolean {
  return code === "42P01" || code === "3F000";
}

async function read<T>(sql: Sql, view: WbView, order: string): Promise<Got<T>> {
  try {
    // 视图名和排序都是上面写死的，不来自请求
    const rows = await sql.unsafe(`select * from workbench.${view} order by ${order}`);
    return { ok: true, rows: rows.map((r) => normalize(r as Record<string, unknown>) as T) };
  } catch (e) {
    const code = errCode(e);
    console.error(`[workbench] ${view} ${code}`);
    return { ok: false, code };
  }
}

export async function getWorkbenchData(): Promise<WorkbenchData> {
  const c = db();
  if ("code" in c) {
    const off = { ok: false as const, code: c.code };
    return {
      configured: c.code !== "no_url", status: off, accounts: off, contentCounts: off, contentNotes: off,
      watch24: off, watch72: off, exposure: off, boost: off, shadow: off,
    };
  }
  const sql = c.sql;
  const status = await read<StatusRow>(sql, "v_status", "seq nulls last");
  if (!status.ok) {
    // 连不上 / 没建 / 没权限：别的视图不用再试一遍
    const same = { ok: false as const, code: status.code };
    return {
      configured: true, status, accounts: same, contentCounts: same, contentNotes: same,
      watch24: same, watch72: same, exposure: same, boost: same, shadow: same,
    };
  }
  return {
    configured: true,
    status,
    accounts: await read<AccountRow>(sql, "v_accounts", "project_id, seq"),
    contentCounts: await read<ContentCountRow>(sql, "v_content_counts", "project_id, seq"),
    contentNotes: await read<ContentNoteRow>(sql, "v_content_notes", "project_id, publish_day desc, note_code"),
    watch24: await read<Watch24Row>(sql, "v_watch_24h", "project_id, comments_24h desc nulls last, publish_day desc, note_code"),
    watch72: await read<Watch72Row>(sql, "v_watch_72h", "project_id, rank_in_project"),
    exposure: await read<ExposureRow>(sql, "v_exposure_hints", "project_id, publish_day desc, note_code"),
    boost: await read<BoostRow>(sql, "v_boost_curves", "project_id, boost_date desc, event_code"),
    shadow: await read<ShadowRow>(sql, "v_shadow_check", "block, rule_version, grp, measure"),
  };
}
