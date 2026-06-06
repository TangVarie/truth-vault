import Link from "next/link";
import { getDashboardData } from "@/lib/dashboard-data";
import {
  AI_DIMS,
  ARCHETYPES,
  comma,
  derivedAiInferences,
  derivedStrategySpace,
  derivedTransferPaths,
  PROJECT_LABEL,
} from "@/config/showcase";
import Mining from "@/components/Mining";
import ByFront from "@/components/ByFront";
import SystemStatus from "@/components/SystemStatus";
import Sankey from "@/components/Sankey";
import CountUp from "@/components/CountUp";
import Donut from "@/components/Donut";
import Ticker from "@/components/Ticker";
import Heatmap from "@/components/Heatmap";
import GrowthCurve from "@/components/GrowthCurve";
import Leaderboard from "@/components/Leaderboard";
import Sparkline from "@/components/Sparkline";

/**
 * /console = 暗色座舱「态势仪表」—— 一套语言贯穿全局(深暖黑 + coral 点睛 + 细发丝),克制统一。
 * 不再有生成式画布(神经花已弃)。前瞻"体征"指标 + 真·数据 viz,可控、可靠。
 */
export const dynamic = "force-dynamic";

export default async function ConsolePage() {
  const data = await getDashboardData();
  const { o, levers, projects, matrix, hits } = data;
  const leverData = levers.map((l) => ({ label: l.lever, value: l.n }));

  const aiInferences = derivedAiInferences(o.notes);
  const strategySpace = derivedStrategySpace(o.levers, o.audiences);
  const transferPaths = derivedTransferPaths(o.projects);

  // 体征(前瞻"物理"口径,基底真实)
  const momentum = o.notes ? Math.round(o.interactions / o.notes) : 0;
  const igniting = Math.max(0, o.essence - o.baokuanReal);
  const hitRate = o.notes ? Math.round((o.baokuanReal / o.notes) * 1000) / 10 : 0;

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
    <main id="top" className="relative min-h-screen" style={{ background: "#0C0B10", color: "#e8e6e3" }}>
      <nav className="sticky top-0 z-40 border-b border-white/10" style={{ background: "rgba(12,11,16,0.82)", backdropFilter: "blur(8px)" }}>
        <div className="mx-auto flex max-w-[1440px] items-center justify-between px-5 py-3.5">
          <Link href="/" className="tag text-slate-400 transition hover:text-coral">← BYWOOD · ROC</Link>
          <div className="hidden items-center gap-1 rounded-full border border-white/8 bg-white/[0.03] p-1 lg:flex">
            <Tab href="#top" active>态势</Tab>
            <Tab href="#flow">数据流</Tab>
            <Tab href="#resonance">共振</Tab>
            <Tab href="#record">战绩</Tab>
          </div>
          <span className="hidden items-center gap-2 rounded-full border border-white/10 px-3 py-1.5 sm:flex">
            <span className="dot" />
            <span className="tag text-slate-300">全链路在线</span>
          </span>
        </div>
      </nav>

      <div className="mx-auto max-w-[1440px] px-5 pb-16 pt-5">
        {/* ── 态势 hero:标题 + 飞轮核心 + 前瞻体征(无画布)── */}
        <Cell className="mb-4" glow>
          <div className="flex flex-wrap items-end justify-between gap-6">
            <div>
              <span className="tag text-coral">飞轮态势 · LIVE SYSTEM</span>
              <h1 className="mt-2 text-white" style={{ fontSize: "clamp(30px,4.2vw,58px)", fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1 }}>
                实时全链路,<span className="text-coral">越用越强</span>。
              </h1>
              <p className="mt-3 max-w-md text-sm text-slate-400">{o.projects} 条战线 · 投放真实结果实时回流 · 结构化策略库持续沉淀。</p>
            </div>
            <div className="text-right">
              <div className="num text-white" style={{ fontSize: "clamp(40px,5vw,84px)", fontWeight: 800, letterSpacing: "-0.035em", lineHeight: 0.9 }}>
                <CountUp value={o.impressions} format="cn" duration={2000} />
              </div>
              <div className="mini mt-1 text-slate-400">累计内容曝光 · CUMULATIVE IMPRESSIONS</div>
            </div>
          </div>
          <div className="mt-7 grid grid-cols-2 gap-x-6 gap-y-5 border-t border-white/8 pt-6 sm:grid-cols-4">
            <Vital label="飞轮动量" value={momentum} sub="每资产带动互动" />
            <Vital label="蓄势待爆" value={igniting} sub="已解析 · 待引爆候选" />
            <Vital label="验证级命中率" value={hitRate} suffix="%" sub="爆款 / 内容资产" />
            <Vital label="情绪光谱" value={o.levers} sub="活跃策略杠杆" />
          </div>
        </Cell>

        {/* ── 深度挖掘:什么在驱动爆款(真实规律,非大数展示)── */}
        <Mining data={data} />

        {/* ── 分战线下钻:同一套方法,每条线结果天差地别 ── */}
        <ByFront data={data} />

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          <Readout label="已部署 AI 决策" value={o.cards} sub="策略经验卡 · 实时调用注入" seed={3} className="lg:col-span-3" />
          <Readout label="策略组合空间" value={strategySpace} sub={`${o.levers}×${o.audiences}×${ARCHETYPES} 维`} seed={5} className="lg:col-span-3" />
          <Readout label="跨品类迁移路径" value={transferPaths} sub={`${o.projects} 战线 · 双向`} seed={11} className="lg:col-span-3" />
          <Readout label="结构化策略内核" value={o.essence} sub="已解析受众画像" seed={13} className="lg:col-span-3" />

          <Cell id="flow" className="lg:col-span-12" glow>
            <div className="flex items-baseline justify-between">
              <h2 className="h2 text-white">生态数据流 <span className="text-coral">/</span> FLYWHEEL STREAM</h2>
              <span className="tag text-slate-500">接口状态 · 实时直连</span>
            </div>
            <div className="mt-5">
              <SystemStatus pulse={data.pulse} />
            </div>
            <div className="mt-6 border-t border-white/8 pt-6">
              <Sankey impressions={o.impressions} notes={o.notes} baokuan={o.baokuanReal} cards={o.cards} />
            </div>
          </Cell>

          <Cell className="lg:col-span-5">
            <GrowthCurve total={o.impressions} />
          </Cell>
          <Cell className="lg:col-span-4">
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
          </Cell>
          <Readout label="AI 推理深度" value={aiInferences} sub={`${AI_DIMS} 维 × ${comma(o.notes)} 资产`} seed={7} className="lg:col-span-3" />

          <Cell id="resonance" className="lg:col-span-7">
            <div className="flex items-baseline justify-between">
              <h2 className="h2 text-white">策略 × 受众 · 共振矩阵</h2>
              <span className="tag text-slate-500">RESONANCE</span>
            </div>
            <p className="mini mt-1 text-slate-500">深 → coral 表共振强度;描边格 = Top 3 命中区</p>
            <div className="mt-5">
              <Heatmap cells={matrix} levers={levOrder} audiences={audOrder} />
            </div>
          </Cell>
          <Cell id="record" className="lg:col-span-5">
            <div className="flex items-baseline justify-between">
              <h2 className="h2 text-white">Top 爆款拆解</h2>
              <span className="tag text-slate-500">TOP HITS</span>
            </div>
            <p className="mini mt-1 text-slate-500">单篇最高 {comma(o.topInteractions)} 互动</p>
            <div className="mt-4">
              <Leaderboard hits={hits} />
            </div>
          </Cell>

          {projects.map((p, i) => (
            <Cell key={p.project_id} className="lg:col-span-3">
              <div className="flex items-center justify-between">
                <span className="tag text-slate-500">{PROJECT_LABEL[p.project_id] ?? p.project_id}</span>
                <span className="tag text-slate-600">α{i + 1}</span>
              </div>
              <div className="num mt-2 text-coral" style={{ fontSize: "clamp(30px,2.6vw,46px)", lineHeight: 0.95, letterSpacing: "-0.03em", fontWeight: 800 }}>
                <CountUp value={p.impressions} format="cn" duration={1400 + i * 100} />
              </div>
              <div className="mini text-slate-500">累计曝光</div>
              <div className="mt-3 flex gap-4 text-[11px] text-slate-400">
                <span>{comma(p.notes)} 资产</span>
                <span>{comma(p.baokuan)} 爆款</span>
                <span>{comma(p.essence)} 解析</span>
              </div>
              <div className="mt-3 -mb-1"><Sparkline color="#E8765A" seed={20 + i} /></div>
            </Cell>
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

function Cell({ children, className = "", id, glow = false }: { children: React.ReactNode; className?: string; id?: string; glow?: boolean }) {
  return (
    <section
      id={id}
      className={`rounded-3xl border border-white/[0.10] p-6 ${className}`}
      style={{ background: glow ? "radial-gradient(680px 220px at 28% 0%, rgba(232,118,90,0.09), transparent 70%), rgba(255,255,255,0.04)" : "rgba(255,255,255,0.04)" }}
    >
      {children}
    </section>
  );
}

function Readout({ label, value, sub, seed, className = "" }: { label: string; value: number; sub?: string; seed?: number; className?: string }) {
  return (
    <Cell className={className}>
      <div className="tag text-slate-500">{label}</div>
      <div className="num mt-2 text-coral" style={{ fontSize: "clamp(34px,3.2vw,56px)", fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 0.95 }}>
        <CountUp value={value} format="comma" duration={1500} />
      </div>
      {sub && <div className="mini mt-1 text-slate-500">{sub}</div>}
      {seed != null && <div className="mt-4 -mb-1"><Sparkline color="#E8765A" seed={seed} /></div>}
    </Cell>
  );
}

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
      <div className="num text-white" style={{ fontSize: "clamp(26px,2.4vw,40px)", fontWeight: 800, letterSpacing: "-0.025em", lineHeight: 1 }}>
        <CountUp value={value} format="comma" duration={1600} />
        {suffix && <span style={{ fontSize: "0.5em", fontWeight: 700 }} className="ml-0.5 text-coral">{suffix}</span>}
      </div>
      <div className="mini mt-1 text-slate-500">{sub}</div>
    </div>
  );
}
