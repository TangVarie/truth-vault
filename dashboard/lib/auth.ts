/**
 * 共享团队口令登录 —— 会话签名 / 校验。
 *
 * 只用 Web Crypto(crypto.subtle),Edge(middleware)与 Node(route handler)双运行时通用,
 * 不依赖 Buffer / node:crypto。会话 cookie = `<expEpochMs>.<hmacHex>`,
 * HMAC-SHA256(secret, expEpochMs)。secret 优先 AUTH_SECRET,缺省回退 DASHBOARD_PASSWORD。
 *
 * fail-closed:未配置 DASHBOARD_PASSWORD → 一律拒绝(/console 进不去,直到设了口令)。
 */
const enc = new TextEncoder();

export const SESSION_COOKIE = "tv_session";
export const SESSION_MAX_AGE = 60 * 60 * 24 * 7; // 7 天

function secret(): string {
  return process.env.AUTH_SECRET || process.env.DASHBOARD_PASSWORD || "";
}

/** 是否已配置访问口令(未配则登录恒失败,前端给提示)。 */
export function isAuthConfigured(): boolean {
  return !!process.env.DASHBOARD_PASSWORD;
}

async function hmacHex(msg: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(secret()),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(msg));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function createSessionToken(): Promise<string> {
  const exp = String(Date.now() + SESSION_MAX_AGE * 1000);
  return `${exp}.${await hmacHex(exp)}`;
}

export async function verifySessionToken(token?: string | null): Promise<boolean> {
  // fail-closed:口令未配(即便 AUTH_SECRET 还在)→ 拒绝所有会话,移除口令即锁死座舱
  if (!token || !isAuthConfigured() || !secret()) return false;
  const dot = token.lastIndexOf(".");
  if (dot < 0) return false;
  const exp = token.slice(0, dot);
  const sig = token.slice(dot + 1);
  const expMs = Number(exp);
  if (!Number.isFinite(expMs) || Date.now() > expMs) return false;
  return safeEqual(sig, await hmacHex(exp));
}

/** 常数时间比对口令(比较两侧 HMAC 摘要,避免长度/早退泄漏)。 */
export async function checkPassword(pw: string): Promise<boolean> {
  const real = process.env.DASHBOARD_PASSWORD || "";
  if (!real || !pw) return false;
  return safeEqual(await hmacHex("pw:" + pw), await hmacHex("pw:" + real));
}
