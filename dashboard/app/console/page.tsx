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
import Sankey from "@/components/Sankey";
import CountUp from "@/components/CountUp";
import Donut from "@/components/Donut";
import Ticker from "@/components/Ticker";
import Heatmap from "@/components/Heatmap";
import GrowthCurve from "@/components/GrowthCurve";
import Leaderboard from "@/components/Leaderboard";
import Sparkline from "@/components/Sparkline";

/**
 * /console = 暗色座舱(bento 版)。参考:Saving Goal 粗色块 + Home Assistant Sankey hero/bento/sparkline。
 * 与 / 编辑级纸面"同数据、反语法":这里密集、暗、bold,数据viz 全留在暗格,大数走粗色块。
 */
export const dynamic = "force-dynamic";

const PROJECT_COLOR = ["brut-coral", "brut-lavender", "brut-olive", "brut-sage"];
const SANKEY_BG =
  "radial-gradient(680px 220px at 28% 0%, rgba(232,118,90,0.10), transparent 70%), #121219";

export default async function ConsolePage() {
  const { o, levers, projects, matrix, hits } = await getDashboardData();
  const leverData = levers.map((l) => ({ label: l.lever, value: l.n }));

  const aiInferences = derivedAiInferences(o.notes);
  const strategySpace = derivedStrategySpace(o.levers, o.audiences);
  const transferPaths = derivedTransferPaths(o.projects);
  const barMax = Math.max(o.reads, o.interactions, o.topInteractions, 1);

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
          <div className="flex items-center gap-4">
            <Link href="/" className="tag text-slate-400 transition hover:text-coral">← BYWOOD · ROC</Link>
          </div>
          <div className="hidden items-center gap-1 rounded-full border border-white/8 bg-white/[0.03] p-1 lg:flex">
            <Tab href="#top" active>总览</Tab>
            <Tab href="#flow">数据流</Tab>
            <Tab href="#resonance">共振</Tab>
            <Tab href="#record">战绩</Tab>
          </div>
          <div className="flex items-center gap-2">
            <span className="hidden items-center gap-2 rounded-full border border-white/10 px-3 py-1.5 sm:flex">
              <span className="dot" />
              <span className="tag text-slate-300">全链路在线</span>
            </span>
          </div>
        </div>
      </nav>

      <div className="mx-auto max-w-[1440px] px-5 pb-16 pt-6">
        {/* ── 标题行 + 右侧 chip 大数(Home Assistant 风) ── */}
        <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="huge text-white" style={{ fontSize: "clamp(40px,6vw,76px)" }}>飞轮态势</h1>
            <p className="mt-1 text-sm text-slate-400">{o.projects} 条战线 · 全链路实时回流 · 越用越强</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Chip label="项目" value={comma(o.projects)} />
            <Chip label="验证级爆款" value={comma(o.baokuanReal)} />
            <Chip label="经验卡" value={comma(o.cards)} />
          </div>
        </header>

        {/* ── 12 列 bento ── */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          {/* HERO:sage 大块(Saving Goal 风:巨号 + 周/日 + 进度条)*/}
          <section className="brut brut-sage rise relative overflow-hidden lg:col-span-8">
            <div className="flex items-start justify-between">
              <span className="tag opacity-70">累计内容曝光 · CUMULATIVE IMPRESSIONS</span>
              <Seg />
            </div>
            <div className="huge num arrow-up mt-2 text-ink">
              <CountUp value={o.impressions} format="cn" duration={1900} />
            </div>
            <div className="mt-6 grid gap-2.5">
              <Bar label="累计阅读" value={o.reads} max={barMax} />
              <Bar label="累计互动" value={o.interactions} max={barMax} />
              <Bar label="单篇最高" value={o.topInteractions} max={barMax} />
            </div>
          </section>

          {/* 右列:coral 经验卡 + lavender 策略组合 */}
          <div className="grid gap-4 lg:col-span-4">
            <KpiBlock color="brut-coral" label="已部署 AI 决策" value={o.cards} sub="策略经验卡 · 实时调用注入" seed={3} dark />
            <KpiBlock color="brut-lavender" label="策略组合空间" value={strategySpace} sub={`${o.levers}×${o.audiences}×${ARCHETYPES} 维`} seed={5} dark />
          </div>

          {/* SANKEY hero(数据 art 中心,带辉光底)*/}
          <section id="flow" className="brut noise rise relative overflow-hidden lg:col-span-12" style={{ background: SANKEY_BG, border: "1px solid rgba(255,255,255,0.08)" }}>
            <div className="flex items-baseline justify-between">
              <h2 className="h2 text-white">生态数据流 <span className="text-coral">/</span> FLYWHEEL STREAM</h2>
              <span className="tag flex items-center gap-2 text-slate-400"><span className="dot" /> 实时</span>
            </div>
            <div className="mt-6">
              <Sankey impressions={o.impressions} notes={o.notes} baokuan={o.baokuanReal} cards={o.cards} />
            </div>
          </section>

          {/* SUMMARY bento:GrowthCurve + Donut + AI推理 */}
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
          <KpiBlock color="brut-ink" label="AI 推理深度" value={aiInferences} sub={`${AI_DIMS} 维 × ${comma(o.notes)} 内容资产`} seed={7} dark className="lg:col-span-3" />

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

          {/* 派生大数色块 */}
          <KpiBlock color="brut-olive" label="跨品类迁移路径" value={transferPaths} sub={`${o.projects} 战线 · 双向`} seed={11} className="lg:col-span-4" />
          <KpiBlock color="brut-bone" label="结构化策略内核" value={o.essence} sub="已解析受众画像 · 沉淀策略库" seed={13} className="lg:col-span-4" />
          <KpiBlock color="brut-carbon" label="受众画像维度" value={o.audiences} sub={`${o.levers} 杠杆 × ${ARCHETYPES} 人性原型`} seed={17} dark className="lg:col-span-4" />

          {/* 战略矩阵:4 战线色块(带 sparkline) */}
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

          {/* 活动播报 */}
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

function Chip({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-2.5 rounded-2xl border border-white/8 bg-white/[0.03] px-4 py-2.5">
      <span className="h1 num text-white" style={{ fontSize: 24 }}>{value}</span>
      <span className="tag text-slate-500">{label}</span>
    </div>
  );
}

function Seg() {
  return (
    <div className="flex items-center gap-0.5 rounded-full bg-ink/10 p-0.5 text-[10px] font-bold">
      <span className="rounded-full bg-ink px-3 py-1 text-paper">周</span>
      <span className="px-3 py-1 text-ink/60">日</span>
    </div>
  );
}

function Bar({ label, value, max }: { label: string; value: number; max: number }) {
  const w = Math.max(5, Math.round((value / max) * 100));
  return (
    <div className="flex items-center gap-3">
      <span className="tag w-16 shrink-0 opacity-70">{label}</span>
      <span className="relative h-2 flex-1 overflow-hidden rounded-full" style={{ background: "rgba(20,17,15,0.16)" }}>
        <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${w}%`, background: "#14110F" }} />
      </span>
      <span className="num w-20 shrink-0 text-right text-sm font-bold text-ink">{cnNum(value)}</span>
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
