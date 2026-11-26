import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { SESSION_COOKIE, verifySessionToken } from "@/lib/auth";
import {
  WB_COOKIE,
  WB_COOKIE_PATH,
  WB_MAX_AGE,
  checkWorkbenchPassword,
  createWorkbenchToken,
  isWorkbenchConfigured,
} from "@/lib/workbench-auth";

/**
 * 收 owner 口令 (工作台第二道闸, docs/35 第 3.2 节)。proxy.ts 已经拦了 /console/*，这里再验一次团队会话。
 * WORKBENCH_PASSWORD 没配 → 404，不提示工作台存在。口令不对 → 回工作台页并带 ?wb=bad。
 */
export async function POST(req: Request) {
  if (!(await verifySessionToken((await cookies()).get(SESSION_COOKIE)?.value))) {
    return NextResponse.redirect(new URL("/login?next=%2Fconsole%2Fworkbench", req.url), 303);
  }
  if (!isWorkbenchConfigured()) return new NextResponse(null, { status: 404 });
  let pw = "";
  try {
    pw = String((await req.formData()).get("password") || "");
  } catch {
    return new NextResponse(null, { status: 400 });
  }
  if (!(await checkWorkbenchPassword(pw))) {
    return NextResponse.redirect(new URL("/console/workbench?wb=bad", req.url), 303);
  }
  const res = NextResponse.redirect(new URL("/console/workbench", req.url), 303);
  res.headers.set("Cache-Control", "no-store");
  res.cookies.set(WB_COOKIE, await createWorkbenchToken(), {
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: WB_COOKIE_PATH,
    maxAge: WB_MAX_AGE,
  });
  return res;
}
