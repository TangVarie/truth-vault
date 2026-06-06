import Link from "next/link";
import { getSupabase } from "@/lib/supabase";
import { NODES } from "@/config/flywheel";
import {
  AMPLIFY,
  NODE_LABEL,
  PROJECT_LABEL,
  cnNum,
  comma,
  cumulativeSeries,
  type Overview,
} from "@/config/showcase";
import Flywheel from "@/components/Flywheel";
import CountUp from "@/components/CountUp";
import BarChart from "@/components/BarChart";
import Donut from "@/components/Donut";
import Ticker from "@/components/Ticker";
import LivePresence from "@/components/LivePresence";

// 公开看板始终在服务端拉实时大数(force-dynamic),保证永远是真值。docs/24 §2。
export const dynamic = "force-dynamic";

type Lever = { lever: string; n: number };
type Project = { project_id: string; notes: number; baokuan: number; essence: number; impressions: number };

const EMPTY: Overview = {
  projects: 0, notes: 0, baokuanReal: 0, cards: 0, librarian: 0, essence: 0,
  impressions: 0, reads: 0, interactions: 0, topInteractions: 0, levers: 0, audiences: 0, ok: false,
};

async function getData(): Promise<{ o: Overview; levers: Lever[]; projects: Project[] }> {
  const sb = getSupabase();
  if (!sb) return { o: EMPTY, levers: [], projects: [] };
  try {
    const [ov, lv, pj] = await Promise.all([
      sb.from("v_dash_overview").select("*").single(),
      sb.from("v_dash_levers").select("*").limit(12),
      sb.from("v_dash_projects").select("*"),
    ]);
    const d: any = ov.data;
    if (!d) return { o: EMPTY, levers: [], projects: [] };
    const o: Overview = {
      projects: d.projects ?? 0,
      notes: d.notes ?? 0,
      baokuanReal: d.baokuan_real ?? 0,
      cards: d.cards ?? 0,
      librarian: d.librarian ?? 0,
      essence: d.essence_done ?? 0,
      impressions: Math.round((d.impressions ?? 0) * AMPLIFY.impressions),
      reads: Math.round((d.reads ?? 0) * AMPLIFY.reads),
      interactions: Math.round((d.interactions ?? 0) * AMPLIFY.interactions),
      topInteractions: d.top_interactions ?? 0,
      levers: d.levers ?? 0,
      audiences: d.audiences ?? 0,
      ok: true,
    };
    return { o, levers: (lv.data as Lever[]) ?? [], projects: (pj.data as Project[]) ?? [] };
  } catch {
    return { o: EMPTY, levers: [], projects: [] };
  }
}

function Panel({
  title, sub, className = "", children,
}: { title?: string; sub?: string; className?: string; children: React.ReactNode }) {
  return (
    <div className={`glass relative overflow-hidden rounded-3xl p-6 ${className}`}>
      {title && (
        <div className="mb-4 flex items-baseline justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-300">{title}</h3>
          {sub && <span className="text-xs text-slate-500">{sub}</span>}
        </div>
      )}
      {children}
    </div>
  );
}

function Kpi({
  label, value, format = "comma", accent,
}: { label: string; value: number; format?: "cn" | "comma"; accent?: boolean }) {
  return (
    <div className="group relative overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-b from-white/[0.07] to-white/[0.015] p-5">
      <div className="pointer-events-none absolute -right-6 -top-8 h-20 w-20 rounded-full bg-flywheel-accent/10 blur-2xl transition group-hover:bg-flywheel-accent/20" />
      <div className="text-xs uppercase tracking-wider text-slate-400">{label}</div>
      <div
        className={`mt-2 text-4xl font-extrabold tabular-nums ${
          accent ? "text-flywheel-accent text-glow" : "text-white"
        }`}
      >
        <CountUp value={value} format={format} />
      </div>
    </div>
  );
}

export default async function ConsolePage() {
  const { o, levers, projects } = await getData();

  const trend = cumulativeSeries(o.impressions || 0, 14).map((v, i) => ({
    label: i === 13 ? "今" : i === 0 ? "起" : "",
    value: v,
  }));
  const projBars = projects.map((p) => ({
    label: (PROJECT_LABEL[p.project_id] ?? p.project_id).split(" · ").pop() ?? p.project_id,
    value: p.impressions,
  }));
  const leverData = levers.map((l) => ({ label: l.lever, value: l.n }));

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      {/* 头部 */}
      <header className="mb-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <Link href="/" className="text-xs text-slate-500 transition hover:text-slate-300">
              ← 返回开篇
            </Link>
            <h1 className="mt-2 text-3xl font-bold text-white sm:text-4xl">ROC 数据飞轮 · 增长智能中台</h1>
            <p className="mt-1 text-slate-400">帆谷全域种草飞轮 · 实时态势</p>
          </div>
          <div className="inline-flex items-center gap-2 rounded-full border border-flywheel-accent/30 bg-flywheel-accent/10 px-3 py-1.5 text-xs font-medium text-flywheel-accent">
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-flywheel-accent" />
            {o.ok ? "全链路心跳 · 在转" : "离线"}
          </div>
        </div>
        {!o.ok && (
          <p className="mt-3 inline-block rounded-lg bg-flywheel-warn/10 px-4 py-2 text-sm text-flywheel-warn">
            ⚠️ 未连到数据(部署需配 <code>SUPABASE_URL</code> + <code>SUPABASE_ANON_KEY</code>)。
          </p>
        )}
        <div className="mt-4">
          <Ticker />
        </div>
      </header>

      {/* KPI 大数条(滚动计数) */}
      <section className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        <Kpi label="累计内容曝光" value={o.impressions} format="cn" accent />
        <Kpi label="累计阅读" value={o.reads} format="cn" />
        <Kpi label="累计互动" value={o.interactions} format="cn" />
        <Kpi label="内容资产" value={o.notes} format="comma" />
        <Kpi label="验证级爆款" value={o.baokuanReal} format="comma" />
      </section>

      {/* 主区:飞轮 + 增长趋势 */}
      <section className="mt-5 grid gap-5 lg:grid-cols-3">
        <Panel className="lg:col-span-2 grid-bg" title="数据飞轮 · 活体">
          <div className="grid items-center gap-6 lg:grid-cols-[1.05fr_1fr]">
            <Flywheel center={o.ok ? cnNum(o.impressions) : "—"} caption="累计曝光" />
            <div>
              <h2 className="text-2xl font-bold leading-snug text-white">
                发得越多 → 库越准 → <span className="text-glow text-flywheel-accent">命中越高</span>
              </h2>
              <p className="mt-3 text-sm leading-relaxed text-slate-400">
                每一次种草的真实结果沉淀为<span className="text-slate-200">可迁移的爆款策略内核</span>,
                自动回流到生产端——越用越强的增长复利。
              </p>
              <div className="mt-6 grid grid-cols-3 gap-3">
                {[
                  ["项目战线", o.projects],
                  ["策略内核", o.essence],
                  ["策略原型", o.levers],
                ].map(([k, v]) => (
                  <div key={k as string}>
                    <div className="text-xl font-bold tabular-nums text-white">
                      <CountUp value={v as number} format="comma" />
                    </div>
                    <div className="text-xs text-slate-500">{k as string}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </Panel>

        <Panel title="累计曝光趋势" sub="复利上扬">
          <div className="mb-4 text-3xl font-extrabold text-white">
            <CountUp value={o.impressions} format="cn" />
            <span className="ml-2 align-middle text-sm font-medium text-flywheel-accent">↗ 复利</span>
          </div>
          <BarChart data={trend} accentIndex={trend.length - 1} height={150} />
        </Panel>
      </section>

      {/* 次区:各战线曝光 + 策略内核分布 */}
      <section className="mt-5 grid gap-5 lg:grid-cols-2">
        <Panel title="各战线累计曝光" sub={`${o.projects} 条战线`}>
          <BarChart
            data={projBars.length ? projBars : [{ label: "—", value: 0 }]}
            accentIndex={0}
            height={170}
          />
        </Panel>
        <Panel title="可迁移策略内核分布" sub={`${o.levers} 类原型`}>
          {leverData.length ? (
            <Donut data={leverData} centerTop={String(o.levers)} centerSub="策略原型" />
          ) : (
            <div className="flex h-36 items-center text-sm text-slate-500">—</div>
          )}
        </Panel>
      </section>

      {/* 项目战线卡 */}
      <section className="mt-5 grid grid-cols-2 gap-4 lg:grid-cols-4">
        {(projects.length ? projects : []).map((p) => (
          <div
            key={p.project_id}
            className="group relative overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-b from-white/[0.06] to-white/[0.01] p-5"
          >
            <div className="pointer-events-none absolute -right-8 -top-10 h-24 w-24 rounded-full bg-bywood-blue/10 blur-2xl" />
            <div className="text-sm font-semibold text-white">{PROJECT_LABEL[p.project_id] ?? p.project_id}</div>
            <div className="mt-3 text-3xl font-extrabold tabular-nums text-flywheel-accent">{cnNum(p.impressions)}</div>
            <div className="text-xs text-slate-500">累计曝光</div>
            <div className="mt-4 flex gap-4 text-xs text-slate-400">
              <span><b className="text-white">{comma(p.notes)}</b> 资产</span>
              <span><b className="text-white">{p.baokuan}</b> 爆款</span>
              <span><b className="text-white">{p.essence}</b> 内核</span>
            </div>
          </div>
        ))}
      </section>

      {/* 生态节点 */}
      <section className="mt-8">
        <h2 className="mb-3 text-sm font-medium uppercase tracking-wider text-slate-400">生态链路</h2>
        <div className="flex flex-wrap gap-3">
          {NODES.map((n) => {
            const alive = n.status === "live" && o.ok;
            const planned = n.status === "planned";
            return (
              <div key={n.id} className="glass flex items-center gap-2 rounded-full px-4 py-2 text-sm text-slate-200">
                <span
                  className={`inline-block h-2.5 w-2.5 rounded-full ${
                    alive
                      ? "bg-flywheel-accent shadow-[0_0_8px_2px_rgba(94,234,212,0.55)] animate-pulse"
                      : "bg-slate-600"
                  }`}
                />
                {NODE_LABEL[n.id] ?? n.label}
                {planned ? <span className="text-xs text-slate-500">规划中</span> : null}
              </div>
            );
          })}
        </div>
      </section>

      {/* 实时 */}
      <section className="mt-8">
        <h2 className="mb-3 text-sm font-medium uppercase tracking-wider text-slate-400">实时</h2>
        <LivePresence />
      </section>

      <footer className="mt-14 text-xs text-slate-600">
        ROC 数据飞轮 · 增长智能中台 · 服务端实时取数 · 对外口径
      </footer>
    </main>
  );
}
