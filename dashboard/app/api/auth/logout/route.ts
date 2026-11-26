import { NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/lib/auth";
import { WB_COOKIE, WB_COOKIE_PATH } from "@/lib/workbench-auth";

export async function POST(req: Request) {
  const res = NextResponse.redirect(new URL("/", req.url), 303);
  res.cookies.set(SESSION_COOKIE, "", { httpOnly: true, secure: true, sameSite: "lax", path: "/", maxAge: 0 });
  // 工作台的 owner 闸 (docs/35 第 3.2 节) 一起清掉; path 要和设的时候一样
  res.cookies.set(WB_COOKIE, "", { httpOnly: true, secure: true, sameSite: "lax", path: WB_COOKIE_PATH, maxAge: 0 });
  return res;
}
