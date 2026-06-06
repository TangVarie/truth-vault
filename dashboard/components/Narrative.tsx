"use client";

import Link from "next/link";
import { useRef } from "react";
import { motion, useScroll, useTransform, type MotionValue } from "framer-motion";
import { BRAND } from "@/config/brand";
import {
  AI_DIMS,
  ARCHETYPES,
  comma,
  derivedAiInferences,
  derivedStrategySpace,
  PROJECT_LABEL,
  type Overview,
} from "@/config/showcase";
import type { DashboardData, Matrix } from "@/lib/dashboard-data";
import Reveal from "@/components/Reveal";
import CountUp from "@/components/CountUp";
import Sankey from "@/components/Sankey";
import GrowthCurve from "@/components/GrowthCurve";
import Heatmap from "@/components/Heatmap";
import Leaderboard from "@/components/Leaderboard";
import Ticker from "@/components/Ticker";

/**
 * v6 · 滚动数据叙事站。每一幕兑现「一个大想法 + 一个重磅数据视觉」,动效全部绑定滚动:
 *  00 品牌 manifesto → 01 越用越准(曝光大数 + 复利曲线) → 02 数据飞轮(sticky 钉住 Sankey)
 *  → 03 策略×受众共振(热力图) → 04 战绩(Top 榜 + 战线) → 05 落到看板(CTA → /console)。
 * 数据来自服务端 getDashboardData(与 /console 同一份真值);所有重磅视觉复用既有组件。
 */

const ease = [0.22, 1, 0.36, 1] as const;
const stagger = { hidden: {}, show: { transition: { staggerChildren: 0.09, delayChildren: 0.08 } } };
const rise = { hidden: { opacity: 0, y: 26 }, show: { opacity: 1, y: 0, transition: { duration: 0.8, ease } } };
const PROJECT_COLOR = ["brut-coral", "brut-lavender", "brut-olive", "brut-sage"];

export default function Narrative({ data }: { data: DashboardData }) {
  const { o, projects, matrix, hits } = data;
  const aiInferences = derivedAiInferences(o.notes);
  const strategySpace = derivedStrategySpace(o.levers, o.audiences);

  // Heatmap 行列序(同 /console 口径:按真实共振总量降序)
  const levOrder = uniqSortBy(matrix, "lever");
  const audOrder = uniqSortBy(matrix, "audience");

  return (
    <main className="relative">
      <SceneBg />
      <TopNav />

      {/* ── 00 · 品牌 manifesto(首屏,kinetic 入场)── */}
      <section className="scene relative flex min-h-screen flex-col justify-center px-8">
        <motion.div
          variants={stagger}
          initial="hidden"
          animate="show"
          className="mx-auto w-full max-w-[1100px]"
        >
          <motion.div variants={rise} className="tag text-coral">
            § {BRAND.studio}
          </motion.div>
          <motion.h1 variants={rise} className="huge mt-3 text-white">
            {BRAND.name}
          </motion.h1>
          <motion.div variants={rise} className="title mt-1 text-coral">
            {BRAND.nameCn}
          </motion.div>
          <motion.p
            variants={rise}
            className="mt-8 max-w-2xl text-lg leading-relaxed text-slate-300 sm:text-xl"
          >
            把策略,变成<span className="font-semibold text-white">越用越准</span>的增长复利。
            <br />
            一套结构化飞轮,照见从投放到决策到复利的每一环。
          </motion.p>
          <motion.div variants={rise} className="mt-10 flex flex-wrap items-center gap-x-4 gap-y-2">
            <span className="tag text-slate-400">{BRAND.tagline}</span>
            <span className="hidden text-slate-600 sm:inline">·</span>
            <span className="tag text-slate-500">{BRAND.fields}</span>
          </motion.div>
        </motion.div>
        <ScrollCue />
      </section>

      {/* ── 01 · 越用越准 ── */}
      <section className="scene flex min-h-screen flex-col justify-center px-8 py-24">
        <div className="mx-auto w-full max-w-[1100px]">
          <Reveal className="tag text-slate-500">01 / 越用越准 · COMPOUNDING</Reveal>
          <Reveal delay={60}>
            <h2 className="title mt-3 text-white">越用越准。</h2>
          </Reveal>
          <Reveal delay={120} className="mt-12">
            <div className="tag text-slate-500">累计内容曝光 · CUMULATIVE IMPRESSIONS</div>
            <div className="huge num arrow-up mt-2 text-coral">
              <CountUp value={o.impressions} format="cn" duration={2000} />
            </div>
            <p className="mt-6 max-w-2xl text-base leading-relaxed text-slate-300">
              投放真实结果实时回流。结构化策略库已沉淀可迁移策略原型{" "}
              <b className="text-white"><CountUp value={o.levers} duration={1000} /></b> 类、受众画像{" "}
              <b className="text-white"><CountUp value={o.audiences} duration={1000} /></b> 维,全域阵地{" "}
              <b className="text-white">5</b> 端 —— 合作越久,命中率越高。
            </p>
          </Reveal>
          <Reveal delay={120} mountOnView className="mt-12 min-h-[360px]">
            <div className="brut brut-ink relative overflow-hidden">
              <GrowthCurve total={o.impressions} />
            </div>
          </Reveal>
        </div>
      </section>

      {/* ── 02 · 数据飞轮(sticky 钉住)── */}
      <FlywheelScene o={o} />

      {/* ── 03 · 策略 × 受众 · 共振矩阵 ── */}
      <section className="scene flex min-h-screen flex-col justify-center px-8 py-24">
        <div className="mx-auto w-full max-w-[1100px]">
          <Reveal className="tag text-slate-500">03 / 策略 × 受众 · 共振矩阵</Reveal>
          <Reveal delay={60}>
            <h2 className="title mt-3 text-white">
              命中,是<span className="text-coral">共振</span>出来的。
            </h2>
          </Reveal>
          <div className="mt-10 grid gap-4 sm:grid-cols-2">
            <Reveal className="brut brut-ink">
              <Stat label="策略组合空间" value={strategySpace} sub={`${o.levers} 杠杆 × ${o.audiences} 受众 × ${ARCHETYPES} 人性原型`} />
            </Reveal>
            <Reveal delay={80} className="brut brut-ink">
              <Stat label="AI 推理深度" value={aiInferences} sub={`${AI_DIMS} 维 × ${comma(o.notes)} 内容资产`} />
            </Reveal>
          </div>
          <Reveal delay={80} mountOnView className="mt-6 min-h-[420px]">
            <div className="brut brut-ink">
              <p className="mini text-slate-500">深色 → coral 表共振强度;高亮格 = Top 命中区</p>
              <div className="mt-5">
                <Heatmap cells={matrix} levers={levOrder} audiences={audOrder} />
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ── 04 · 战绩 ── */}
      <section className="scene flex min-h-screen flex-col justify-center px-8 py-24">
        <div className="mx-auto w-full max-w-[1100px]">
          <Reveal className="tag text-slate-500">04 / 战绩 · TRACK RECORD</Reveal>
          <Reveal delay={60}>
            <h2 className="title mt-3 text-white">
              真实结果,<span className="text-coral">可查证</span>。
            </h2>
          </Reveal>

          <Reveal delay={80} className="mt-10">
            <div className="brut brut-ink">
              <div className="flex items-baseline justify-between">
                <h3 className="h2 text-white">Top 爆款拆解</h3>
                <span className="tag text-slate-500">TOP HITS</span>
              </div>
              <p className="mini mt-1 text-slate-500">单篇最高 {comma(o.topInteractions)} 互动</p>
              <div className="mt-4">
                <Leaderboard hits={hits} />
              </div>
            </div>
          </Reveal>

          <div className="mt-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
            {projects.map((p, i) => (
              <Reveal
                key={p.project_id}
                delay={i * 70}
                className={`brut ${PROJECT_COLOR[i % PROJECT_COLOR.length]} relative overflow-hidden`}
              >
                <span className="tag opacity-70">{PROJECT_LABEL[p.project_id] ?? p.project_id}</span>
                <div className="h1 num mt-2">
                  <CountUp value={p.impressions} format="cn" duration={1500 + i * 100} />
                </div>
                <div className="mini mt-0.5 opacity-60">累计曝光</div>
                <div className="mt-5 grid grid-cols-3 gap-2 text-[10px]">
                  <MiniStat n={p.notes} l="资产" />
                  <MiniStat n={p.baokuan} l="爆款" />
                  <MiniStat n={p.essence} l="解析" />
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ── 05 · 落到看板(CTA)── */}
      <section className="scene flex min-h-screen flex-col justify-center px-8 py-24">
        <div className="mx-auto w-full max-w-[1100px]">
          <Reveal className="tag text-slate-500">05 / 实时态势 · LIVE</Reveal>
          <Reveal delay={60}>
            <h2 className="title mt-3 text-white">
              实时态势,
              <br />
              照见整座<span className="text-coral">飞轮</span>。
            </h2>
          </Reveal>

          <Reveal delay={100} className="mt-12 grid grid-cols-2 gap-4 sm:grid-cols-4">
            <LiveStat label="战线" value={o.projects} />
            <LiveStat label="验证级爆款" value={o.baokuanReal} />
            <LiveStat label="策略经验卡" value={o.cards} />
            <LiveStat label="结构化内核" value={o.essence} />
          </Reveal>

          <Reveal delay={140} className="mt-12 flex flex-wrap items-stretch gap-4">
            <Link
              href="/console"
              className="brut brut-coral inline-flex items-center gap-3 px-7 py-5 text-base font-bold transition hover:brightness-105"
              style={{ borderRadius: 999 }}
            >
              进入公众看板 →
            </Link>
            <button
              type="button"
              title="内部页 · 即将开放(接 auth)"
              className="inline-flex items-center gap-2 rounded-full border border-white/15 px-7 py-5 text-base font-medium text-slate-200 transition hover:border-white/35"
            >
              登录 <span className="tag text-slate-500">内部 · 即将开放</span>
            </button>
          </Reveal>

          <div className="mt-16">
            <Ticker />
          </div>

          <footer className="mt-12">
            <div className="hr-thin mb-4 opacity-40" />
            <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-600">
              <span>BYWOOD · ROC 增长智能中台</span>
              <span>实时全链路 · 数据飞轮 · 越用越强</span>
            </div>
          </footer>
        </div>
      </section>
    </main>
  );
}

/* ── 02 · sticky 钉住的飞轮场(scrollytelling 灵魂动作)── */
function FlywheelScene({ o }: { o: Overview }) {
  const ref = useRef<HTMLElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end end"] });
  const steps = [
    "全域投放数据实时回流 ROC 智能中台,内容资产持续结构化。",
    "验证级爆款 → 跨域审美注入,高权重样本同步智能仿写网络。",
    "AI 决策回流 → 创作工作台借卡注入,命中即沉淀为策略经验卡。",
  ];
  return (
    <section ref={ref} className="relative h-[240vh]">
      <div className="sticky top-0 flex h-screen flex-col justify-center px-8">
        <div className="mx-auto w-full max-w-[1100px]">
          <span className="tag text-slate-500">02 / 数据飞轮 · FLYWHEEL STREAM</span>
          <h2 className="title mt-3 text-white">
            一个连接,<span className="text-coral">照见整座生态</span>。
          </h2>
          <div className="brut brut-ink noise relative mt-8 overflow-hidden">
            <Sankey impressions={o.impressions} notes={o.notes} baokuan={o.baokuanReal} cards={o.cards} />
          </div>
          {/* 滚动进度线 */}
          <motion.div style={{ scaleX: scrollYProgress }} className="mt-6 h-px origin-left bg-coral" />
          {/* 随滚动逐步点亮的解说 */}
          <div className="mt-6 grid gap-4 sm:grid-cols-3">
            {steps.map((s, i) => (
              <Step key={i} progress={scrollYProgress} i={i} total={steps.length} text={s} />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function Step({
  progress,
  i,
  total,
  text,
}: {
  progress: MotionValue<number>;
  i: number;
  total: number;
  text: string;
}) {
  const a = i / total;
  const b = (i + 1) / total;
  const opacity = useTransform(progress, [a - 0.08, a + 0.02, b, b + 0.06], [0.25, 1, 1, 0.4]);
  return (
    <motion.div style={{ opacity }} className="border-t border-white/10 pt-3">
      <div className="tag text-coral">0{i + 1}</div>
      <p className="mt-2 text-sm leading-relaxed text-slate-300">{text}</p>
    </motion.div>
  );
}

function TopNav() {
  return (
    <div className="pointer-events-none fixed inset-x-0 top-0 z-40">
      <div className="mx-auto flex max-w-[1100px] items-center justify-between px-8 py-6">
        <span className="tag text-slate-300">BYWOOD · ROC</span>
        <Link href="/console" className="tag pointer-events-auto text-slate-400 transition hover:text-coral">
          进入控制台 →
        </Link>
      </div>
    </div>
  );
}

function ScrollCue() {
  return (
    <div className="absolute inset-x-0 bottom-10 flex justify-center">
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1.1 }}
        className="flex flex-col items-center gap-2 text-slate-500"
      >
        <span className="tag">向下滚动</span>
        <motion.span
          animate={{ y: [0, 8, 0] }}
          transition={{ duration: 1.8, repeat: Infinity, ease: "easeInOut" }}
          className="text-coral"
        >
          ↓
        </motion.span>
      </motion.div>
    </div>
  );
}

function SceneBg() {
  return <div aria-hidden className="bg-landing grid-bg pointer-events-none fixed inset-0 -z-10" />;
}

function Stat({ label, value, sub }: { label: string; value: number; sub: string }) {
  return (
    <>
      <div className="tag text-slate-400">{label}</div>
      <div className="h1 num mt-1 text-white">
        <CountUp value={value} duration={1700} />
      </div>
      <div className="mini mt-1 text-slate-500">{sub}</div>
    </>
  );
}

function LiveStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="brut brut-ink">
      <div className="tag text-slate-400">{label}</div>
      <div className="h1 num mt-1 text-coral">
        <CountUp value={value} duration={1400} />
      </div>
    </div>
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

function uniqSortBy(m: Matrix[], key: "lever" | "audience"): string[] {
  const total = (v: string) => m.filter((x) => x[key] === v).reduce((s, x) => s + x.n, 0);
  return Array.from(new Set(m.map((x) => x[key]))).sort((a, b) => total(b) - total(a));
}
