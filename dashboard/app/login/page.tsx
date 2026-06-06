import type { Metadata } from "next";
import { isAuthConfigured } from "@/lib/auth";

export const metadata: Metadata = { robots: { index: false, follow: false }, title: "登录 · 内部座舱" };
export const dynamic = "force-dynamic";

function sanitizeNext(n?: string): string {
  if (!n || !n.startsWith("/") || n.startsWith("//")) return "/console";
  return n;
}

export default function LoginPage({ searchParams }: { searchParams: { next?: string; error?: string } }) {
  const next = sanitizeNext(searchParams?.next);
  const configured = isAuthConfigured();

  return (
    <main className="flex min-h-screen items-center justify-center px-5" style={{ background: "#0C0B10", color: "#e8e6e3" }}>
      <div className="w-full max-w-sm rounded-3xl border border-white/10 p-8" style={{ background: "rgba(255,255,255,0.04)" }}>
        <span className="tag text-coral">内部座舱 · RESTRICTED</span>
        <h1 className="mt-2 text-white" style={{ fontSize: 26, fontWeight: 800, letterSpacing: "-0.02em" }}>团队登录</h1>
        <p className="mini mt-1 text-slate-500">内部版含策略机理,仅限团队访问。</p>

        <form method="POST" action="/api/auth/login" className="mt-6 space-y-3">
          <input type="hidden" name="next" value={next} />
          <input
            type="password"
            name="password"
            autoFocus
            required
            placeholder="团队口令"
            autoComplete="current-password"
            className="w-full rounded-xl border border-white/10 bg-black/30 px-4 py-3 text-sm text-white outline-none placeholder:text-slate-600 focus:border-coral"
          />
          <button
            type="submit"
            className="w-full rounded-xl px-4 py-3 text-sm font-semibold text-white transition"
            style={{ background: "#E8765A" }}
          >
            进入 →
          </button>
        </form>

        {searchParams?.error ? (
          <p className="mini mt-3" style={{ color: "#E8765A" }}>口令不正确,请重试。</p>
        ) : null}
        {!configured ? (
          <p className="mini mt-3 text-slate-500">⚠️ 尚未配置访问口令:请在 Vercel 项目环境变量里设 <span className="num text-slate-300">DASHBOARD_PASSWORD</span>(Production)。</p>
        ) : null}

        <a href="/" className="mini mt-6 inline-block text-slate-500 transition hover:text-slate-300">← 返回公开首页</a>
      </div>
    </main>
  );
}
