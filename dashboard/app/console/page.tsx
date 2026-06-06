import Link from "next/link";
import { getSupabase } from "@/lib/supabase";
import {
  AMPLIFY,
  AI_DIMS,
  ARCHETYPES,
  cnNum,
  comma,
  derivedAiInferences,
  derivedStrategySpace,
  derivedTransferPaths,
  PROJECT_LABEL,
  PROJECT_SHORT,
  type Overview,
} from "@/config/showcase";
import Sankey from "@/components/Sankey";
import CountUp from "@/components/CountUp";
import Donut from "@/components/Donut";
import Ticker from "@/components/Ticker";
import Heatmap from "@/components/Heatmap";
import GrowthCurve from "@/components/GrowthCurve";
import Leaderboard, { type TopHit } from "@/components/Leaderboard";

export const dynamic = "force-dynamic";

type Lever = { lever: string; n: number };
type Project = { project_id: string; notes: number; baokuan: number; essence: number; impressions: number };
type Matrix = { lever: string; audience: string; n: number };

const EMPTY: Overview = {
  projects: 0, notes: 0, baokuanReal: 0, cards: 0, librarian: 0, essence: 0,
  impressions: 0, reads: 0, interactions: 0, topInteractions: 0, levers: 0, audiences: 0, ok: false,
};

async function getData() {
  const sb = getSupabase();
  if (!sb) return { o: EMPTY, levers: [] as Lever[], projects: [] as Project[], matrix: [] as Matrix[], hits: [] as TopHit[] };
  try {
    const [ov, lv, pj, mx, th] = await Promise.all([
      sb.from("v_dash_overview").select("*").single(),
      sb.from("v_dash_levers").select("*").limit(12),
      sb.from("v_dash_projects").select("*"),
      sb.from("v_dash_matrix").select("*"),
      sb.from("v_dash_top_hits").select("*"),
    ]);
    const d: any = ov.data;
    if (!d) return { o: EMPTY, levers: [] as Lever[], projects: [] as Project[], matrix: [] as Matrix[], hits: [] as TopHit[] };
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
    return {
      o,
      levers: (lv.data as Lever[]) ?? [],
      projects: (pj.data as Project[]) ?? [],
      matrix: (mx.data as Matrix[]) ?? [],
      hits: (th.data as TopHit[]) ?? [],
    };
  } catch {
    return { o: EMPTY, levers: [] as Lever[], projects: [] as Project[], matrix: [] as Matrix[], hits: [] as TopHit[] };
  }
}

const PROJECT_COLOR = ["brut-coral", "brut-lavender", "brut-olive", "brut-sage"];

export default async function ConsolePage() {
  const { o, levers, projects, matrix, hits } = await getData();
  const leverData = levers.map((l) => ({ label: l.lever, value: l.n }));

  // 派生大数(对外口径,基底真实)
  const aiInferences  = derivedAiInferences(o.notes);          // 内容资产 × 14 维 ≈ 35K
  const strategySpace = derivedStrategySpace(o.levers, o.audiences); // 12 × 8 × 19 = 1,824
  const transferPaths = derivedTransferPaths(o.projects);      // 4×3 = 12 路径

  // Heatmap 行列序:取真数据出现的全集(行 = 真实出现过的 levers,降序;列 = audiences,固定顺序)
  const levOrder = Array.from(new Set(matrix.map((m) => m.lever))).sort(
    (a, b) => matrix.filter((m) => m.lever === b).reduce((s, m) => s + m.n, 0)
            - matrix.filter((m) => m.lever === a).reduce((s, m) => s + m.n, 0)
  );
  const audOrder = Array.from(new Set(matrix.map((m) => m.audience))).sort(
    (a, b) => matrix.filter((m) => m.audience === b).reduce((s, m) => s + m.n, 0)
            - matrix.filter((m) => m.audience === a).reduce((s, m) => s + m.n, 0)
  );

  return (
    <main className="bg-ink relative min-h-screen">
      {/* 顶栏 */}
      <div className="mx-auto flex max-w-[1320px] items-center justify-between px-8 py-6">
        <Link href="/" className="tag text-slate-500 hover:text-slate-200">
          ← BYWOOD · ROC
        </Link>
        <div className="flex items-center gap-3">
          <span className="dot" />
          <span className="tag text-slate-400">AI · 全链路在线</span>
        </div>
      </div>

      {/* HERO:左 coral 巨块 + 右 3 个深块叠(累计阅读/累计互动/AI 推理) */}
      <section className="mx-auto grid max-w-[1320px] gap-4 px-8 lg:grid-cols-[2fr_1fr]">
        <div className="brut brut-coral rise relative overflow-hidden" style={{ animationDelay: "60ms" }}>
          <div className="flex items-start justify-between">
            <span className="tag">累计内容曝光 · CUMULATIVE IMPRESSIONS</span>
            <span className="tag opacity-70">LIVE</span>
          </div>
          <div className="huge num mt-2 arrow-up">
            <CountUp value={o.impressions} format="cn" duration={1800} />
          </div>
          <div className="mt-2 max-w-md text-sm leading-snug opacity-85">
            投放真实结果实时回流。<b>越用越准</b>—— 结构化策略库已沉淀,
            可迁移策略原型 <b><CountUp value={o.levers} format="comma" duration={1000} /></b> 类,
            受众画像 <b><CountUp value={o.audiences} format="comma" duration={1000} /></b> 维,
            全域阵地 <b>5</b> 端。
          </div>
        </div>

        <div className="grid gap-4">
          <div className="brut brut-ink rise" style={{ animationDelay: "180ms" }}>
            <span className="tag text-slate-400">累计阅读</span>
            <div className="title num mt-1 text-white"><CountUp value={o.reads} format="cn" duration={1500} /></div>
          </div>
          <div className="brut brut-ink rise" style={{ animationDelay: "260ms" }}>
            <span className="tag text-slate-400">累计互动</span>
            <div className="title num mt-1 text-white"><CountUp value={o.interactions} format="cn" duration={1500} /></div>
            <div className="mini mt-1 text-slate-500">单篇最高 {comma(o.topInteractions)}</div>
          </div>
        </div>
      </section>

      {/* 第二行 KPI:派生大数(AI 推理深度 / 策略组合空间 / 跨品类迁移) */}
      <section className="mx-auto mt-4 grid max-w-[1320px] gap-4 px-8 sm:grid-cols-3">
        <div className="brut brut-ink rise" style={{ animationDelay: "340ms" }}>
          <span className="tag text-slate-400">AI 推理深度</span>
          <div className="h1 num mt-1 text-white"><CountUp value={aiInferences} format="comma" duration={1700} /></div>
          <div className="mini mt-1 text-slate-500">{AI_DIMS} 维 × {o.notes.toLocaleString()} 内容资产</div>
        </div>
        <div className="brut brut-ink rise" style={{ animationDelay: "400ms" }}>
          <span className="tag text-slate-400">策略组合空间</span>
          <div className="h1 num mt-1 text-white"><CountUp value={strategySpace} format="comma" duration={1700} /></div>
          <div className="mini mt-1 text-slate-500">
            {o.levers} 杠杆 × {o.audiences} 受众 × {ARCHETYPES} 人性原型
          </div>
        </div>
        <div className="brut brut-ink rise" style={{ animationDelay: "460ms" }}>
          <span className="tag text-slate-400">跨品类迁移路径</span>
          <div className="h1 num mt-1 text-white"><CountUp value={transferPaths} format="comma" duration={1500} /></div>
          <div className="mini mt-1 text-slate-500">{o.projects} 战线 · 双向</div>
        </div>
      </section>

      {/* 复利增长曲线 —— 全宽签名视图 */}
      <section className="mx-auto mt-4 max-w-[1320px] px-8">
        <div className="brut brut-ink rise relative overflow-hidden" style={{ animationDelay: "520ms" }}>
          <GrowthCurve total={o.impressions} />
        </div>
      </section>

      {/* SANKEY:生态数据流 */}
      <section className="mx-auto mt-4 max-w-[1320px] px-8">
        <div className="brut brut-ink rise relative overflow-hidden noise" style={{ animationDelay: "600ms" }}>
          <div className="flex items-baseline justify-between">
            <h2 className="h2 text-white">生态数据流 <span className="text-coral">/</span> FLYWHEEL STREAM</h2>
            <span className="tag text-slate-500">实时</span>
          </div>
          <div className="mt-6">
            <Sankey impressions={o.impressions} notes={o.notes} baokuan={o.baokuanReal} cards={o.cards} />
          </div>
        </div>
      </section>

      {/* 共振矩阵 + Top 爆款拆解 */}
      <section className="mx-auto mt-4 grid max-w-[1320px] gap-4 px-8 lg:grid-cols-[1.2fr_1fr]">
        <div className="brut brut-ink rise" style={{ animationDelay: "680ms" }}>
          <div className="flex items-baseline justify-between">
            <h2 className="h2 text-white">策略 × 受众 · 共振矩阵</h2>
            <span className="tag text-slate-500">RESONANCE</span>
          </div>
          <p className="mini mt-1 text-slate-500">深色 → coral 表共振强度;高亮格 = Top 3 命中区</p>
          <div className="mt-5">
            <Heatmap cells={matrix} levers={levOrder} audiences={audOrder} />
          </div>
        </div>
        <div className="brut brut-ink rise" style={{ animationDelay: "740ms" }}>
          <div className="flex items-baseline justify-between">
            <h2 className="h2 text-white">Top 爆款拆解</h2>
            <span className="tag text-slate-500">TOP HITS</span>
          </div>
          <p className="mini mt-1 text-slate-500">单篇最高 14,422 互动 · 361.7 万曝光</p>
          <div className="mt-4">
            <Leaderboard hits={hits} />
          </div>
        </div>
      </section>

      {/* 战略矩阵:4 个战线 brutalist 色块 */}
      <section className="mx-auto mt-4 max-w-[1320px] px-8">
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="tag text-slate-400">战略矩阵 · STRATEGIC PORTFOLIO</h2>
          <span className="mini text-slate-600">{projects.length} 条战线 · 累计</span>
        </div>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {projects.map((p, i) => {
            const colorClass = PROJECT_COLOR[i % PROJECT_COLOR.length];
            return (
              <div key={p.project_id} className={`brut ${colorClass} rise relative overflow-hidden`} style={{ animationDelay: `${800 + i * 70}ms` }}>
                <span className="tag opacity-70">{PROJECT_LABEL[p.project_id] ?? p.project_id}</span>
                <div className="h1 num mt-2">
                  <CountUp value={p.impressions} format="cn" duration={1500 + i * 100} />
                </div>
                <div className="mini mt-0.5 opacity-60">累计曝光</div>
                <div className="mt-5 grid grid-cols-3 gap-2 text-[10px]">
                  <Stat n={p.notes} l="资产" />
                  <Stat n={p.baokuan} l="爆款" />
                  <Stat n={p.essence} l="解析" />
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* 策略原型分布 donut + bone block */}
      <section className="mx-auto mt-4 grid max-w-[1320px] gap-4 px-8 lg:grid-cols-[1.4fr_1fr]">
        <div className="brut brut-ink rise" style={{ animationDelay: "1100ms" }}>
          <div className="flex items-baseline justify-between">
            <h2 className="h2 text-white">可迁移策略原型</h2>
            <span className="tag text-slate-500">{o.levers} 类</span>
          </div>
          <p className="mini mt-1 text-slate-500">穿越周期 · 不衰减的爆款驱动机制</p>
          <div className="mt-5">
            {leverData.length ? (
              <Donut data={leverData} centerTop={String(o.levers)} centerSub="策略原型" />
            ) : (
              <div className="flex h-36 items-center text-sm text-slate-500">—</div>
            )}
          </div>
        </div>

        <div className="brut brut-bone rise" style={{ animationDelay: "1160ms" }}>
          <span className="tag opacity-70">已部署 AI 决策</span>
          <div className="huge num mt-1" style={{ fontSize: "clamp(60px, 9vw, 110px)" }}>
            <CountUp value={o.cards} format="comma" duration={1400} />
          </div>
          <div className="mini mt-1 opacity-60">策略经验卡 · 实时调用注入</div>
          <div className="hr-thin mt-6 opacity-30" />
          <div className="mt-4 flex items-baseline justify-between">
            <span className="tag opacity-70">验证级爆款</span>
            <span className="h1 num"><CountUp value={o.baokuanReal} format="comma" duration={1200} /></span>
          </div>
          <div className="hr-thin mt-4 opacity-30" />
          <div className="mt-4 flex items-baseline justify-between">
            <span className="tag opacity-70">已结构化策略内核</span>
            <span className="h1 num"><CountUp value={o.essence} format="comma" duration={1200} /></span>
          </div>
        </div>
      </section>

      {/* 活动播报(底部) */}
      <section className="mx-auto mt-6 max-w-[1320px] px-8">
        <Ticker />
      </section>

      <footer className="mx-auto mt-12 max-w-[1320px] px-8 pb-12">
        <div className="hr-thin mb-4 opacity-40" />
        <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-600">
          <span>BYWOOD · ROC 增长智能中台</span>
          <span>实时全链路 · 数据飞轮 · 越用越强</span>
        </div>
      </footer>
    </main>
  );
}

function Stat({ n, l }: { n: number; l: string }) {
  return (
    <div>
      <div className="text-base font-bold text-ink">{comma(n)}</div>
      <div className="mini opacity-60">{l}</div>
    </div>
  );
}
