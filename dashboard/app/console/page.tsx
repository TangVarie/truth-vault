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
 * /console = 暗色座舱「活体仪表」—— 一套语言贯穿全局(深暖黑 + coral 点睛 + 细发丝),
 * 而非"活体花 + 一堆彩色砖"。bloom 是沉浸式 hero(中心生长、四周渐隐),其余面板全部克制统一。
 * 与 / 编辑级纸面"同一个生命体、反语法"。
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
    <main id="top" className="relative min-h-screen" style={{ background: "#07060a", color: "#e8e6e3" }}>
      {/* ── 顶部 pill 导航 ── */}
      <nav className="sticky top-0 z-40 border-b border-white/8" style={{ background: "rgba(7,6,10,0.82)", backdropFilter: "blur(8px)" }}>
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
        {/* ── 活体飞轮 hero(沉浸式:中心生长、四周渐隐)── */}
        <section className="relative mb-5 overflow-hidden rounded-[28px] border border-white/[0.06]">
          <NeuralBloom data={data} theme="neon" className="h-[460px] w-full sm:h-[620px]" />
          {/* 暗角聚焦 + 上/下渐隐,保证文字可读 */}
          <div className="pointer-events-none absolute inset-0" style={{ background: "radial-gradient(120% 90% at 50% 46%, transparent 38%, rgba(7,6,10,0.55) 78%, rgba(7,6,10,0.95) 100%)" }} />
          <div className="pointer-events-none absolute inset-x-0 top-0 h-28" style={{ background: "linear-gradient(to bottom, rgba(7,6,10,0.8), transparent)" }} />
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-2/5" style={{ background: "linear-gradient(to top, rgba(7,6,10,0.92), transparent)" }} />

          <div className="absolute inset-0 flex flex-col justify-between p-6 sm:p-9">
            <div className="flex items-start justify-between gap-4">
              <div>
                <span className="tag text-coral">活体飞轮 · LIVING FLYWHEEL</span>
                <h1 className="mt-2 max-w-md font-light text-white" style={{ fontSize: "clamp(22px,2.6vw,38px)", lineHeight: 1.1, letterSpacing: "-0.015em" }}>
                  整座生态,作为一个会生长的生命体
                </h1>
              </div>
              <div className="text-right">
                <div className="num text-white" style={{ fontSize: "clamp(26px,2.8vw,44px)", fontWeight: 800, letterSpacing: "-0.03em" }}>
                  <CountUp value={o.notes} format="cn" duration={2000} />
                </div>
                <div className="mini text-slate-400">内容资产 · 飞轮核心</div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
              <Vital label="飞轮动量" value={momentum} sub="每资产带动互动" />
              <Vital label="蓄势待爆" value={igniting} sub="已解析 · 待引爆候选" />
              <Vital label="验证级命中率" value={hitRate} suffix="%" sub="爆款 / 内容资产" />
              <Vital label="情绪光谱" value={o.levers} sub="活跃策略杠杆" />
            </div>
          </div>
        </section>

        {/* ── 统一克制网格(一套语言)── */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          <Readout label="已部署 AI 决策" value={o.cards} sub="策略经验卡 · 实时调用注入" seed={3} className="lg:col-span-3" />
          <Readout label="策略组合空间" value={strategySpace} sub={`${o.levers}×${o.audiences}×${ARCHETYPES} 维`} seed={5} className="lg:col-span-3" />
          <Readout label="跨品类迁移路径" value={transferPaths} sub={`${o.projects} 战线 · 双向`} seed={11} className="lg:col-span-3" />
          <Readout label="结构化策略内核" value={o.essence} sub="已解析受众画像" seed={13} className="lg:col-span-3" />

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

          <Cell id="flow" className="lg:col-span-12" glow>
            <div className="flex items-baseline justify-between">
              <h2 className="h2 text-white">生态数据流 <span className="text-coral">/</span> FLYWHEEL STREAM</h2>
              <span className="tag flex items-center gap-2 text-slate-400"><span className="dot" /> 实时</span>
            </div>
            <div className="mt-6">
              <Sankey impressions={o.impressions} notes={o.notes} baokuan={o.baokuanReal} cards={o.cards} />
            </div>
          </Cell>

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

          {/* 4 战线:同一套克制读数(不再彩色砖) */}
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

/* ── 统一的克制单元(一套语言)── */
function Cell({ children, className = "", id, glow = false }: { children: React.ReactNode; className?: string; id?: string; glow?: boolean }) {
  return (
    <section
      id={id}
      className={`rounded-3xl border border-white/[0.07] p-6 ${className}`}
      style={{ background: glow ? "radial-gradient(680px 220px at 28% 0%, rgba(232,118,90,0.08), transparent 70%), rgba(255,255,255,0.02)" : "rgba(255,255,255,0.02)" }}
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
