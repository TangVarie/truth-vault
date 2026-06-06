import Link from "next/link";
import { getDashboardData } from "@/lib/dashboard-data";
import {
  AI_DIMS,
  ARCHETYPES,
  cnNum,
  comma,
  derivedAiInferences,
  derivedStrategySpace,
  derivedTransferPaths,
  PROJECT_LABEL,
} from "@/config/showcase";
import NeuralBloom from "@/components/NeuralBloom";
import Sankey from "@/components/Sankey";
import CountUp from "@/components/CountUp";
import Donut from "@/components/Donut";
import Ticker from "@/components/Ticker";
import Heatmap from "@/components/Heatmap";
import GrowthCurve from "@/components/GrowthCurve";
import Leaderboard from "@/components/Leaderboard";
import Sparkline from "@/components/Sparkline";

/**
 * /console = 暗色座舱(活体版)。hero = 活体飞轮 Neural Bloom(整座生态作为一个会生长的生命体)
 * + 前瞻"体征"指标(动量/蓄势待爆/命中率/情绪光谱),不再是一排倒计数。
 * 与 / 编辑级纸面"同一个生命体、反语法":这里霓虹暗底,那里墨线纸面。
 */
export const dynamic = "force-dynamic";

const PROJECT_COLOR = ["brut-coral", "brut-lavender", "brut-olive", "brut-sage"];

export default async function ConsolePage() {
  const data = await getDashboardData();
  const { o, levers, projects, matrix, hits } = data;
  const leverData = levers.map((l) => ({ label: l.lever, value: l.n }));

  const aiInferences = derivedAiInferences(o.notes);
  const strategySpace = derivedStrategySpace(o.levers, o.audiences);
  const transferPaths = derivedTransferPaths(o.projects);

  // 体征(前瞻"物理"口径,基底真实)
  const momentum = o.notes ? Math.round(o.interactions / o.notes) : 0; // 每资产带动互动
  const igniting = Math.max(0, o.essence - o.baokuanReal); // 已解析、待引爆候选
  const hitRate = o.notes ? Math.round((o.baokuanReal / o.notes) * 1000) / 10 : 0; // 验证级命中率 %

  const levOrder = Array.from(new Set(matrix.map((m) => m.lever))).sort(
    (a, b) =>
      matrix.filter((m) => m.lever === b).reduce((s, m) => s + m.n, 0) -
      matrix.filter((m) => m.lever === a).reduce((s, m) => s + m.n, 0)
  );
  const audOrder = Array.from(new Set(matrix.map((m) => m.audience))).sort(
    (a, b) =>
      matrix.filter((m) => m.audience === b).reduce((s, m) => s + m.n, 0) -
      matrix.filter((m) => m.audience === a).reduce((s, m) => s + m.n, 0)
  );

  return (
    <main id="top" className="bg-ink relative min-h-screen">
      {/* ── 顶部 pill 导航 ── */}
      <nav className="sticky top-0 z-40 border-b border-white/8 bg-[#0a0a0f]/80 backdrop-blur">
        <div className="mx-auto flex max-w-[1440px] items-center justify-between px-5 py-3.5">
          <Link href="/" className="tag text-slate-400 transition hover:text-coral">← BYWOOD · ROC</Link>
          <div className="hidden items-center gap-1 rounded-full border border-white/8 bg-white/[0.03] p-1 lg:flex">
            <Tab href="#top" active>活体</Tab>
            <Tab href="#flow">数据流</Tab>
            <Tab href="#resonance">共振</Tab>
            <Tab href="#record">战绩</Tab>
          </div>
          <span className="hidden items-center gap-2 rounded-full border border-white/10 px-3 py-1.5 sm:flex">
            <span className="dot" />
            <span className="tag text-slate-300">实时生长</span>
          </span>
        </div>
      </nav>

      <div className="mx-auto max-w-[1440px] px-5 pb-16 pt-5">
        {/* ── 活体飞轮 hero ── */}
        <section className="relative mb-4 overflow-hidden rounded-[28px] border border-white/8" style={{ background: "#07060a" }}>
          <NeuralBloom data={data} theme="neon" className="h-[440px] w-full sm:h-[560px]" />
          <div className="pointer-events-none absolute inset-x-0 top-0 h-28" style={{ background: "linear-gradient(to bottom, rgba(7,6,10,0.85), transparent)" }} />
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-2/3" style={{ background: "linear-gradient(to top, rgba(7,6,10,0.92), rgba(7,6,10,0.2) 55%, transparent)" }} />

          <div className="absolute inset-0 flex flex-col justify-between p-6 sm:p-8">
            <div className="flex items-start justify-between gap-4">
              <div>
                <span className="tag text-coral">活体飞轮 · LIVING FLYWHEEL</span>
                <h1 className="mt-2 max-w-xl font-black text-white" style={{ fontSize: "clamp(24px,3vw,42px)", lineHeight: 1.04, letterSpacing: "-0.02em" }}>
                  整座生态,作为一个<br className="hidden sm:block" />会生长的生命体。
                </h1>
              </div>
              <div className="text-right">
                <div className="num text-white" style={{ fontSize: "clamp(28px,3vw,48px)", fontWeight: 900, letterSpacing: "-0.03em" }}>
                  <CountUp value={o.notes} format="cn" duration={2000} />
                </div>
                <div className="mini text-slate-400">内容资产 · 飞轮核心</div>
              </div>
            </div>

            {/* 体征:前瞻物理口径 */}
            <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
              <Vital label="飞轮动量" value={momentum} sub="每资产带动互动" />
              <Vital label="蓄势待爆" value={igniting} sub="已解析 · 待引爆候选" />
              <Vital label="验证级命中率" value={hitRate} suffix="%" sub="爆款 / 内容资产" />
              <Vital label="情绪光谱" value={o.levers} sub="活跃策略杠杆" />
            </div>
          </div>
        </section>

        {/* ── 12 列 bento ── */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          {/* KPI 粗色块 */}
          <KpiBlock color="brut-coral" label="已部署 AI 决策" value={o.cards} sub="策略经验卡 · 实时调用注入" seed={3} className="lg:col-span-3" />
          <KpiBlock color="brut-lavender" label="策略组合空间" value={strategySpace} sub={`${o.levers}×${o.audiences}×${ARCHETYPES} 维`} seed={5} className="lg:col-span-3" />
          <KpiBlock color="brut-olive" label="跨品类迁移路径" value={transferPaths} sub={`${o.projects} 战线 · 双向`} seed={11} className="lg:col-span-3" />
          <KpiBlock color="brut-bone" label="结构化策略内核" value={o.essence} sub="已解析受众画像 · 沉淀策略库" seed={13} className="lg:col-span-3" />

          {/* SUMMARY:曲线 + donut + AI推理 */}
          <section className="brut brut-ink rise relative overflow-hidden lg:col-span-5">
            <GrowthCurve total={o.impressions} />
          </section>
          <section className="brut brut-ink rise lg:col-span-4">
            <div className="flex items-baseline justify-between">
              <h2 className="h2 text-white">策略原型分布</h2>
              <span className="tag text-slate-500">{o.levers} 类</span>
            </div>
            <div className="mt-5">
              {leverData.length ? (
                <Donut data={leverData} centerTop={String(o.levers)} centerSub="策略原型" />
              ) : (
                <div className="flex h-36 items-center text-sm text-slate-500">—</div>
              )}
            </div>
          </section>
          <KpiBlock color="brut-carbon" label="AI 推理深度" value={aiInferences} sub={`${AI_DIMS} 维 × ${comma(o.notes)} 内容资产`} seed={7} dark className="lg:col-span-3" />

          {/* Sankey 数据流明细 */}
          <section id="flow" className="brut noise rise relative overflow-hidden lg:col-span-12" style={{ background: "radial-gradient(680px 220px at 28% 0%, rgba(232,118,90,0.10), transparent 70%), #121219", border: "1px solid rgba(255,255,255,0.08)" }}>
            <div className="flex items-baseline justify-between">
              <h2 className="h2 text-white">生态数据流 <span className="text-coral">/</span> FLYWHEEL STREAM</h2>
              <span className="tag flex items-center gap-2 text-slate-400"><span className="dot" /> 实时</span>
            </div>
            <div className="mt-6">
              <Sankey impressions={o.impressions} notes={o.notes} baokuan={o.baokuanReal} cards={o.cards} />
            </div>
          </section>

          {/* 共振 + 战绩 */}
          <section id="resonance" className="brut brut-ink rise lg:col-span-7">
            <div className="flex items-baseline justify-between">
              <h2 className="h2 text-white">策略 × 受众 · 共振矩阵</h2>
              <span className="tag text-slate-500">RESONANCE</span>
            </div>
            <p className="mini mt-1 text-slate-500">深 → coral 表共振强度;描边格 = Top 3 命中区</p>
            <div className="mt-5">
              <Heatmap cells={matrix} levers={levOrder} audiences={audOrder} />
            </div>
          </section>
          <section id="record" className="brut brut-ink rise lg:col-span-5">
            <div className="flex items-baseline justify-between">
              <h2 className="h2 text-white">Top 爆款拆解</h2>
              <span className="tag text-slate-500">TOP HITS</span>
            </div>
            <p className="mini mt-1 text-slate-500">单篇最高 {comma(o.topInteractions)} 互动</p>
            <div className="mt-4">
              <Leaderboard hits={hits} />
            </div>
          </section>

          {/* 4 战线色块(带 sparkline) */}
          {projects.map((p, i) => (
            <section key={p.project_id} className={`brut ${PROJECT_COLOR[i % PROJECT_COLOR.length]} rise relative overflow-hidden lg:col-span-3`}>
              <span className="tag opacity-70">{PROJECT_LABEL[p.project_id] ?? p.project_id}</span>
              <div className="num mt-2" style={{ fontSize: "clamp(34px,3vw,52px)", lineHeight: 0.9, letterSpacing: "-0.03em", fontWeight: 900 }}>
                <CountUp value={p.impressions} format="cn" duration={1400 + i * 100} />
              </div>
              <div className="mini opacity-60">累计曝光</div>
              <div className="mt-4 grid grid-cols-3 gap-2 text-[10px]">
                <MiniStat n={p.notes} l="资产" />
                <MiniStat n={p.baokuan} l="爆款" />
                <MiniStat n={p.essence} l="解析" />
              </div>
              <div className="mt-4 -mb-2"><Sparkline color="#14110F" seed={20 + i} /></div>
            </section>
          ))}

          <div className="lg:col-span-12">
            <Ticker />
          </div>
        </div>

        <footer className="mt-10">
          <div className="hr-thin mb-4 opacity-40" />
          <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-600">
            <span>BYWOOD · ROC 增长智能中台</span>
            <span>实时全链路 · 数据飞轮 · 越用越强</span>
          </div>
        </footer>
      </div>
    </main>
  );
}

/* ── helpers ── */
function Tab({ href, children, active = false }: { href: string; children: React.ReactNode; active?: boolean }) {
  return (
    <a href={href} className={`tag rounded-full px-4 py-1.5 transition ${active ? "bg-white/10 text-white" : "text-slate-400 hover:text-slate-200"}`}>
      {children}
    </a>
  );
}

function Vital({ label, value, sub, suffix }: { label: string; value: number; sub: string; suffix?: string }) {
  return (
    <div>
      <div className="tag text-slate-400">{label}</div>
      <div className="num text-white" style={{ fontSize: "clamp(26px,2.4vw,40px)", fontWeight: 900, letterSpacing: "-0.025em", lineHeight: 1 }}>
        <CountUp value={value} format="comma" duration={1600} />
        {suffix && <span style={{ fontSize: "0.5em", fontWeight: 700 }} className="ml-0.5 text-coral">{suffix}</span>}
      </div>
      <div className="mini mt-1 text-slate-500">{sub}</div>
    </div>
  );
}

function KpiBlock({
  color,
  label,
  value,
  sub,
  seed,
  dark = false,
  className = "",
}: {
  color: string;
  label: string;
  value: number;
  sub?: string;
  seed: number;
  dark?: boolean;
  className?: string;
}) {
  return (
    <section className={`brut ${color} rise relative overflow-hidden ${className}`}>
      <span className="tag opacity-70">{label}</span>
      <div className="num mt-2" style={{ fontSize: "clamp(38px,4vw,72px)", lineHeight: 0.9, letterSpacing: "-0.035em", fontWeight: 900 }}>
        <CountUp value={value} format="comma" duration={1500} />
      </div>
      {sub && <div className="mini mt-1 opacity-60">{sub}</div>}
      <div className="mt-4 -mb-2"><Sparkline color={dark ? "#E8765A" : "#14110F"} seed={seed} /></div>
    </section>
  );
}

function MiniStat({ n, l }: { n: number; l: string }) {
  return (
    <div>
      <div className="text-base font-bold text-ink">{comma(n)}</div>
      <div className="mini opacity-60">{l}</div>
    </div>
  );
}
