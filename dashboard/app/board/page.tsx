import Link from "next/link";
import type { Metadata } from "next";
import { getDashboardData } from "@/lib/dashboard-data";
import { comma, PROJECT_LABEL } from "@/config/showcase";
import CountUp from "@/components/CountUp";
import GrowthCurve from "@/components/GrowthCurve";

/**
 * /board = 对外数据看板(公开、只读、纯结果)。
 * 只露成果与体量(曝光/资产/爆款/命中率/战绩),不露任何策略机理 —— 可直接发客户。
 * 机理挖掘只在登录后的 /console。
 */
export const metadata: Metadata = { title: "数据看板 · BYWOOD", description: "真实投放结果速览" };
export const dynamic = "force-dynamic";

const card = "rounded-3xl border border-white/[0.10] p-6";
const cardStyle = { background: "rgba(255,255,255,0.04)" } as const;

export default async function BoardPage() {
  const { o, projects, hits } = await getDashboardData();
  const hitRate = o.notes ? Math.round((o.baokuanReal / o.notes) * 1000) / 10 : 0;

  const stats: { label: string; value: number; sub?: string }[] = [
    { label: "战线", value: o.projects },
    { label: "内容资产", value: o.notes },
    { label: "验证级爆款", value: o.baokuanReal, sub: `命中率 ${hitRate}%` },
    { label: "策略经验卡", value: o.cards },
    { label: "结构化内核", value: o.essence },
  ];

  return (
    <main className="min-h-screen" style={{ background: "#0C0B10", color: "#e8e6e3" }}>
      <nav className="sticky top-0 z-40 border-b border-white/10" style={{ background: "rgba(12,11,16,0.82)", backdropFilter: "blur(8px)" }}>
        <div className="mx-auto flex max-w-[1100px] items-center justify-between px-5 py-3.5">
          <Link href="/" className="tag text-slate-400 transition hover:text-coral">← BYWOOD · ROC</Link>
          <span className="tag flex items-center gap-2 text-slate-300"><span className="dot" /> 公开数据看板</span>
        </div>
      </nav>

      <div className="mx-auto max-w-[1100px] px-5 pb-16 pt-6">
        {/* hero */}
        <section className={`${card} mb-4`} style={cardStyle}>
          <div className="flex flex-wrap items-end justify-between gap-6">
            <div>
              <span className="tag text-coral">真实投放结果 · 可查证</span>
              <h1 className="mt-2 text-white" style={{ fontSize: "clamp(28px,4vw,52px)", fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1 }}>
                真实结果,<span className="text-coral">摆出来</span>。
              </h1>
              <p className="mt-3 max-w-md text-sm text-slate-400">{o.projects} 条战线 · 累计内容曝光与验证级爆款,全部来自真实投放回流。</p>
            </div>
            <div className="text-right">
              <div className="num text-white" style={{ fontSize: "clamp(36px,5vw,76px)", fontWeight: 800, letterSpacing: "-0.035em", lineHeight: 0.9 }}>
                <CountUp value={o.impressions} format="cn" duration={2000} />
              </div>
              <div className="mini mt-1 text-slate-400">累计内容曝光 · CUMULATIVE IMPRESSIONS</div>
            </div>
          </div>
        </section>

        {/* stat grid */}
        <section className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
          {stats.map((s) => (
            <div key={s.label} className={card} style={cardStyle}>
              <div className="tag text-slate-500">{s.label}</div>
              <div className="num mt-2 text-coral" style={{ fontSize: "clamp(28px,2.6vw,42px)", fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 0.95 }}>
                <CountUp value={s.value} format="comma" duration={1500} />
              </div>
              {s.sub ? <div className="mini mt-1 text-slate-500">{s.sub}</div> : null}
            </div>
          ))}
        </section>

        {/* growth */}
        <section className={`${card} mt-4`} style={cardStyle}>
          <GrowthCurve total={o.impressions} />
        </section>

        {/* per-project */}
        <section className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {projects.map((p) => (
            <div key={p.project_id} className={card} style={cardStyle}>
              <div className="tag text-slate-500">{PROJECT_LABEL[p.project_id] ?? p.project_id}</div>
              <div className="num mt-2 text-coral" style={{ fontSize: "clamp(26px,2.4vw,40px)", lineHeight: 0.95, letterSpacing: "-0.03em", fontWeight: 800 }}>
                <CountUp value={p.impressions} format="cn" duration={1400} />
              </div>
              <div className="mini text-slate-500">累计曝光</div>
              <div className="mt-3 flex gap-4 text-[11px] text-slate-400">
                <span>{comma(p.notes)} 资产</span>
                <span>{comma(p.baokuan)} 爆款</span>
              </div>
            </div>
          ))}
        </section>

        {/* top hits — 只露 战线/互动/曝光,不露策略机理 */}
        {hits.length ? (
          <section className={`${card} mt-4`} style={cardStyle}>
            <div className="flex items-baseline justify-between">
              <h2 className="h2 text-white">Top 爆款</h2>
              <span className="tag text-slate-500">TOP HITS</span>
            </div>
            <div className="mt-4">
              <div className="mini mb-2 grid grid-cols-[36px_1fr_104px_104px] items-center gap-3 px-1 text-slate-500">
                <span>#</span><span>战线</span><span className="text-right">互动</span><span className="text-right">曝光</span>
              </div>
              {hits.slice(0, 5).map((h, i) => (
                <div key={i} className="grid grid-cols-[36px_1fr_104px_104px] items-center gap-3 border-t border-white/8 px-1 py-3">
                  <span className="num" style={{ color: h.rank === 1 ? "#E8765A" : "#94a3b8" }}>{h.rank}</span>
                  <span className="text-[13px] text-slate-200">{PROJECT_LABEL[h.project_id] ?? h.project_id}</span>
                  <span className="num text-right text-sm text-slate-200"><CountUp value={h.interactions} format="comma" duration={1200} /></span>
                  <span className="num text-right text-sm text-coral"><CountUp value={h.impressions} format="cn" duration={1300} /></span>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        <footer className="mt-10">
          <div className="hr-thin mb-4 opacity-40" />
          <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-600">
            <span>BYWOOD · ROC 增长智能中台 · 公开数据看板</span>
            <span>数据实时直连 · 结果可查证</span>
          </div>
        </footer>
      </div>
    </main>
  );
}
