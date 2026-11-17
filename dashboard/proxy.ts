import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { SESSION_COOKIE, verifySessionToken } from "@/lib/auth";

/**
 * 登录闸:仅保护内部座舱 /console。无有效会话 → 跳 /login(带 next 回跳)。
 * 公开首页 / 与对外数据看板 /board 不受影响。
 *
 * Next 16 起这个文件叫 proxy.ts、函数叫 proxy(原 middleware.ts / middleware,官方 codemod 改的名,逻辑没动)。
 * 运行时从 Edge 变成 Node(proxy 不能选 Edge);lib/auth.ts 只用 Web Crypto,两边都能跑。
 */
export async function proxy(req: NextRequest) {
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  if (await verifySessionToken(token)) return NextResponse.next();

  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.search = `?next=${encodeURIComponent(req.nextUrl.pathname)}`;
  const res = NextResponse.redirect(url);
  // 这个跳转取决于访问者有没有登录，不许任何缓存层存下来再发给别人
  res.headers.set("Cache-Control", "no-store");
  return res;
}

export const config = { matcher: ["/console", "/console/:path*"] };
