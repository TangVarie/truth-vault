import { NextResponse } from "next/server";
import { checkPassword, createSessionToken, SESSION_COOKIE, SESSION_MAX_AGE } from "@/lib/auth";

function sanitizeNext(n: string): string {
  if (!n || !n.startsWith("/") || n.startsWith("//")) return "/console";
  return n;
}

export async function POST(req: Request) {
  const form = await req.formData();
  const pw = String(form.get("password") || "");
  const next = sanitizeNext(String(form.get("next") || "/console"));

  if (!(await checkPassword(pw))) {
    return NextResponse.redirect(new URL(`/login?error=1&next=${encodeURIComponent(next)}`, req.url), 303);
  }

  const res = NextResponse.redirect(new URL(next, req.url), 303);
  res.cookies.set(SESSION_COOKIE, await createSessionToken(), {
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: "/",
    maxAge: SESSION_MAX_AGE,
  });
  return res;
}
