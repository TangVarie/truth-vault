/**
 * 工作台的第二道闸：只给 owner (W-63, D-169, docs/35 第 3.2 节)。
 *
 * 团队闸 (lib/auth.ts 的 tv_session) 拿团队口令就能进；工作台影子期只给 owner 看，所以再加一道：
 * - 口令在 WORKBENCH_PASSWORD (只配 Production)。没配 → 工作台这一页 notFound()，不提示它存在。
 * - cookie tv_wb = `<到期毫秒>.<HMAC>`，7 天，httpOnly、secure、lax，path 是 /console
 *   (这样 /console 首页才知道要不要显示工作台入口；别的路径带不上它)。
 * - 签名的钥匙里有 WORKBENCH_PASSWORD，签的消息带 `wb:` 前缀：知道团队口令、拿到团队会话，都签不出这个 cookie；
 *   owner 换了口令，旧的 tv_wb 一起失效。tv_session 的格式不动，谁都不会被踢下线。
 *
 * 只用 Web Crypto，和 lib/auth.ts 一样。
 */
const enc = new TextEncoder();

export const WB_COOKIE = "tv_wb";
export const WB_COOKIE_PATH = "/console";
export const WB_MAX_AGE = 60 * 60 * 24 * 7; // 7 天

/** 第二道口令配没配。没配 → 工作台这一页当不存在。 */
export function isWorkbenchConfigured(): boolean {
  return !!process.env.WORKBENCH_PASSWORD;
}

function key(): string {
  return `wb\u0000${process.env.WORKBENCH_PASSWORD || ""}\u0000${process.env.AUTH_SECRET || ""}`;
}

async function hmacHex(msg: string): Promise<string> {
  const k = await crypto.subtle.importKey("raw", enc.encode(key()), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", k, enc.encode(msg));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function createWorkbenchToken(): Promise<string> {
  const exp = String(Date.now() + WB_MAX_AGE * 1000);
  return `${exp}.${await hmacHex("wb:" + exp)}`;
}

export async function verifyWorkbenchToken(token?: string | null): Promise<boolean> {
  if (!token || !isWorkbenchConfigured()) return false;
  const dot = token.lastIndexOf(".");
  if (dot < 0) return false;
  const exp = token.slice(0, dot);
  const sig = token.slice(dot + 1);
  const expMs = Number(exp);
  if (!Number.isFinite(expMs) || Date.now() > expMs) return false;
  return safeEqual(sig, await hmacHex("wb:" + exp));
}

/** 常数时间比对 owner 口令 (比两边的 HMAC 摘要)。 */
export async function checkWorkbenchPassword(pw: string): Promise<boolean> {
  const real = process.env.WORKBENCH_PASSWORD || "";
  if (!real || !pw) return false;
  return safeEqual(await hmacHex("pw:" + pw), await hmacHex("pw:" + real));
}
