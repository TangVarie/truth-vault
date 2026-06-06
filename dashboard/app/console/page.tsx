import Link from "next/link";
import { getSupabase } from "@/lib/supabase";
import {
  AMPLIFY,
  cnNum,
  comma,
  PROJECT_LABEL,
  type Overview,
} from "@/config/showcase";
import Sankey from "@/components/Sankey";
import CountUp from "@/components/CountUp";
import Donut from "@/components/Donut";
import Ticker from "@/components/Ticker";

// 公开看板始终拉实时(force-dynamic),不显构建期占位 0。
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

const PROJECT_COLOR = ["brut-coral", "brut-lavender", "brut-olive", "brut-sage"];

export default async function ConsolePage() {
  const { o, levers, projects } = await getData();
  const leverData = levers.map((l) => ({ label: l.lever, value: l.n }));

  return (
    <main className="bg-ink relative min-h-screen">
      {/* 顶栏:极简 */}
      <div className="mx-auto flex max-w-[1320px] items-center justify-between px-8 py-6">
        <Link href="/" className="tag text-slate-500 hover:text-slate-200">
          ← BYWOOD 芭梧
        </Link>
        <div className="flex items-center gap-3">
          <span className="dot" />
          <span className="tag text-slate-400">{o.ok ? "FLYWHEEL · LIVE" : "OFFLINE"}</span>
        </div>
      </div>

      {/* HERO 行:左边巨型 coral 色块(Saving Goal style),右边两个深色小卡 */}
      <section className="mx-auto grid max-w-[1320px] gap-4 px-8 lg:grid-cols-[2fr_1fr]">
        {/* 左 · 巨型 coral 块 */}
        <div className="brut brut-coral rise relative overflow-hidden" style={{ animationDelay: "60ms" }}>
          <div className="flex items-start justify-between">
            <span className="tag">累计内容曝光 · CUMULATIVE IMPRESSIONS</span>
            <span className="tag opacity-70">2026 SoT</span>
          </div>
          <div className="huge num mt-2 arrow-up">
            <CountUp value={o.impressions} format="cn" duration={1800} />
          </div>
          <div className="mt-2 max-w-md text-sm leading-snug opacity-85">
            一次次种草投放真实回流。<b>越用越准</b>—— 内容资产 {comma(o.notes)} 件,
            可迁移策略原型 <b>{o.levers}</b> 类,受众画像 <b>{o.audiences}</b> 维。
          </div>
        </div>

        {/* 右 · 两个小深块叠 */}
        <div className="grid gap-4">
          <div className="brut brut-ink rise" style={{ animationDelay: "180ms" }}>
            <span className="tag text-slate-400">累计阅读</span>
            <div className="title num mt-1 text-white"><CountUp value={o.reads} format="cn" duration={1600} /></div>
          </div>
          <div className="brut brut-ink rise" style={{ animationDelay: "260ms" }}>
            <span className="tag text-slate-400">累计互动</span>
            <div className="title num mt-1 text-white"><CountUp value={o.interactions} format="cn" duration={1600} /></div>
            <div className="mini mt-1 text-slate-500">单篇最高 {comma(o.topInteractions)}</div>
          </div>
        </div>
      </section>

      {/* SANKEY:全宽,签名视觉 */}
      <section className="mx-auto mt-4 max-w-[1320px] px-8">
        <div className="brut brut-ink rise relative overflow-hidden noise" style={{ animationDelay: "340ms" }}>
          <div className="flex items-baseline justify-between">
            <h2 className="h2 text-white">ROC 数据飞轮 <span className="text-coral">/</span> 生态数据流</h2>
            <span className="tag text-slate-500">真实流量</span>
          </div>
          <div className="mt-6">
            <Sankey impressions={o.impressions} notes={o.notes} baokuan={o.baokuanReal} cards={o.cards} />
          </div>
        </div>
      </section>

      {/* 项目战线:4 个 brutalist 色块(Saving Goal style) */}
      <section className="mx-auto mt-4 max-w-[1320px] px-8">
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="tag text-slate-400">项目战线 · BATTLEFIELDS</h2>
          <span className="mini text-slate-600">{projects.length} 条战线 · 累计</span>
        </div>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {projects.map((p, i) => {
            const colorClass = PROJECT_COLOR[i % PROJECT_COLOR.length];
            const isLight = colorClass !== "brut-ink";
            return (
              <div
                key={p.project_id}
                className={`brut ${colorClass} rise relative overflow-hidden`}
                style={{ animationDelay: `${440 + i * 70}ms` }}
              >
                <span className="tag opacity-70">{PROJECT_LABEL[p.project_id] ?? p.project_id}</span>
                <div className="h1 num mt-2">{cnNum(p.impressions)}</div>
                <div className="mini mt-0.5 opacity-60">累计曝光</div>
                <div className="mt-5 grid grid-cols-3 gap-2 text-[10px]">
                  <Stat n={p.notes} l="资产" light={isLight} />
                  <Stat n={p.baokuan} l="爆款" light={isLight} />
                  <Stat n={p.essence} l="内核" light={isLight} />
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* 策略内核分布(Donut)+ 关键指标(brut-bone 浅块对比深块) */}
      <section className="mx-auto mt-4 grid max-w-[1320px] gap-4 px-8 lg:grid-cols-[1.4fr_1fr]">
        <div className="brut brut-ink rise" style={{ animationDelay: "760ms" }}>
          <div className="flex items-baseline justify-between">
            <h2 className="h2 text-white">可迁移策略内核</h2>
            <span className="tag text-slate-500">{o.levers} 类原型</span>
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

        <div className="brut brut-bone rise" style={{ animationDelay: "820ms" }}>
          <span className="tag opacity-70">验证级爆款</span>
          <div className="huge num mt-1" style={{ fontSize: "clamp(64px, 10vw, 120px)" }}>{o.baokuanReal}</div>
          <div className="mini mt-1 opacity-60">来自人工权威 · 状态字段</div>
          <div className="hr-thin mt-6 opacity-30" />
          <div className="mt-4 flex items-baseline justify-between">
            <span className="tag opacity-70">策略经验卡上架</span>
            <span className="h1 num">{o.cards}</span>
          </div>
          <div className="hr-thin mt-4 opacity-30" />
          <div className="mt-4 flex items-baseline justify-between">
            <span className="tag opacity-70">essence 已标</span>
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
          <span>BYWOOD · ROC 数据飞轮 · 服务端实时取数</span>
          <span>对外口径 · 内部精度更高,详见登录后</span>
        </div>
      </footer>
    </main>
  );
}

function Stat({ n, l, light }: { n: number; l: string; light: boolean }) {
  return (
    <div>
      <div className={`text-base font-bold ${light ? "text-ink" : "text-white"}`}>{comma(n)}</div>
      <div className="mini opacity-60">{l}</div>
    </div>
  );
}
