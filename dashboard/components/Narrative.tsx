"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { motion, useScroll, useMotionValueEvent } from "framer-motion";
import type { DashData } from "@/lib/data";
import { BRAND } from "@/config/brand";
import {
  cnNum, comma, AI_DIMS, ARCHETYPES,
  derivedAiInferences, derivedStrategySpace, derivedTransferPaths,
  PROJECT_LABEL,
} from "@/config/showcase";
import Sankey from "./Sankey";
import Heatmap from "./Heatmap";
import GrowthCurve from "./GrowthCurve";
import Leaderboard from "./Leaderboard";
import Donut from "./Donut";
import CountUp from "./CountUp";
import Reveal from "./Reveal";
import Ticker from "./Ticker";

const PROJECT_COLOR = ["brut-coral", "brut-lavender", "brut-olive", "brut-sage"];

export default function Narrative({ data }: { data: DashData }) {
  const { o, levers, projects, matrix, hits } = data;
  const leverData = levers.map((l) => ({ label: l.lever, value: l.n }));

  const aiInf = derivedAiInferences(o.notes);
  const space = derivedStrategySpace(o.levers, o.audiences);
  const paths = derivedTransferPaths(o.projects);

  const levOrder = Array.from(new Set(matrix.map((m) => m.lever))).sort(
    (a, b) => sum(matrix, "lever", b) - sum(matrix, "lever", a)
  );
  const audOrder = Array.from(new Set(matrix.map((m) => m.audience))).sort(
    (a, b) => sum(matrix, "audience", b) - sum(matrix, "audience", a)
  );

  return (
    <main className="bg-ink relative">
      {/* 固定顶栏 */}
      <nav className="fixed inset-x-0 top-0 z-50 border-b border-white/5 bg-ink/70 backdrop-blur-md">
        <div className="mx-auto flex max-w-[1320px] items-center justify-between px-8 py-4">
          <span className="text-sm font-bold tracking-tight text-white">
            BYWOOD <span className="text-coral">·</span> 芭梧
          </span>
          <div className="hidden items-center gap-8 sm:flex">
            <a href="#growth" className="tag text-slate-400 transition hover:text-white">数据</a>
            <a href="#method" className="tag text-slate-400 transition hover:text-white">飞轮</a>
            <a href="#proof" className="tag text-slate-400 transition hover:text-white">战绩</a>
            <Link href="/console" className="tag text-coral transition hover:brightness-110">实时看板 →</Link>
          </div>
        </div>
      </nav>

      {/* ── 00 · HERO ── */}
      <section className="screen relative mx-auto max-w-[1320px] px-8 pt-20">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
        >
          <div className="tag text-coral">{BRAND.studio} · {BRAND.taglineEn}</div>
          <h1 className="huge mt-5 text-white">BYWOOD</h1>
          <h2 className="title mt-4 max-w-4xl text-white">
            把每一次投放的真实结果,<br />炼成 <span className="text-coral">越用越强</span> 的增长复利。
          </h2>
          <p className="mt-7 max-w-xl text-base leading-relaxed text-slate-400 sm:text-lg">
            {BRAND.whatWeDo}
          </p>
          {/* live 大数 chips */}
          <div className="mt-10 flex flex-wrap gap-x-10 gap-y-4">
            <HeroStat label="累计内容曝光" value={o.impressions} fmt="cn" />
            <HeroStat label="内容资产" value={o.notes} fmt="comma" />
            <HeroStat label="验证级爆款" value={o.baokuanReal} fmt="comma" />
          </div>
        </motion.div>
        <div className="scroll-hint absolute inset-x-0 bottom-8 text-center text-sm text-slate-500">
          向下滚 · 看飞轮如何转 ↓
        </div>
      </section>

      {/* ── 01 · 越用越准 ── */}
      <section id="growth" className="screen mx-auto max-w-[1320px] px-8">
        <Reveal><div className="tag text-slate-500">01 — 越用越准</div></Reveal>
        <Reveal delay={0.05}>
          <div className="huge mt-4 text-coral arrow-up">
            <CountUp value={o.impressions} format="cn" duration={2200} />
          </div>
          <div className="tag mt-3 text-slate-400">累计内容曝光 · 全域 5 阵地</div>
        </Reveal>
        <Reveal delay={0.1} className="mt-12 brut brut-ink">
          <GrowthCurve total={o.impressions} />
        </Reveal>
        <Reveal delay={0.05} className="mt-6 grid gap-4 sm:grid-cols-3">
          <MiniStat label="累计阅读" value={o.reads} fmt="cn" />
          <MiniStat label="累计互动" value={o.interactions} fmt="cn" sub={`单篇最高 ${comma(o.topInteractions)}`} />
          <MiniStat label="AI 推理深度" value={aiInf} fmt="comma" sub={`${AI_DIMS} 维 × ${comma(o.notes)} 资产`} />
        </Reveal>
      </section>

      {/* ── 02 · 数据飞轮(sticky scrub)── */}
      <FlywheelAct o={o} />

      {/* ── 03 · 策略 × 受众共振 ── */}
      <section id="resonance" className="screen mx-auto max-w-[1320px] px-8">
        <Reveal>
          <div className="tag text-slate-500">03 — 策略 × 受众共振</div>
          <h2 className="title mt-3 text-white">哪种钩子,<span className="text-coral">撬动哪群人</span></h2>
          <p className="mt-4 max-w-xl text-base text-slate-400">
            {o.levers} 类可迁移策略原型 × {o.audiences} 维受众画像 ={" "}
            <b className="text-white">{comma(space)}</b> 种策略组合空间。深色 → coral 表共振强度。
          </p>
        </Reveal>
        <Reveal delay={0.1} className="mt-8 brut brut-ink">
          <Heatmap cells={matrix} levers={levOrder} audiences={audOrder} />
        </Reveal>
        <Reveal delay={0.1} className="mt-4 brut brut-ink">
          {leverData.length ? (
            <Donut data={leverData} centerTop={String(o.levers)} centerSub="策略原型" />
          ) : null}
        </Reveal>
      </section>

      {/* ── 04 · 战绩 ── */}
      <section id="proof" className="screen mx-auto max-w-[1320px] px-8">
        <Reveal>
          <div className="tag text-slate-500">04 — 战绩</div>
          <h2 className="title mt-3 text-white">
            单篇最高 <span className="text-coral">{comma(o.topInteractions)}</span> 互动
          </h2>
        </Reveal>
        <Reveal delay={0.1} className="mt-8 brut brut-ink">
          <Leaderboard hits={hits} />
        </Reveal>
        <Reveal delay={0.05} className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
          {projects.map((p, i) => (
            <div key={p.project_id} className={`brut ${PROJECT_COLOR[i % PROJECT_COLOR.length]} relative overflow-hidden`}>
              <span className="tag opacity-70">{PROJECT_LABEL[p.project_id] ?? p.project_id}</span>
              <div className="h1 num mt-2"><CountUp value={p.impressions} format="cn" duration={1500} /></div>
              <div className="mini mt-0.5 opacity-60">累计曝光</div>
              <div className="mt-5 grid grid-cols-3 gap-2 text-[10px]">
                <StatMini n={p.notes} l="资产" />
                <StatMini n={p.baokuan} l="爆款" />
                <StatMini n={p.essence} l="解析" />
              </div>
            </div>
          ))}
        </Reveal>
      </section>

      {/* ── 05 · 方法论 + CTA ── */}
      <section id="method" className="screen mx-auto max-w-[1320px] px-8 text-center">
        <Reveal className="mx-auto max-w-3xl">
          <div className="tag text-slate-500">扶摇 ROC · {BRAND.roc.note}</div>
          <h2 className="title mt-4 text-white">
            {BRAND.footerLead}<span className="text-coral">{BRAND.footerAccent}</span>
          </h2>
          <p className="mt-6 text-base leading-relaxed text-slate-400">{BRAND.roc.subtitle}</p>
          <div className="mt-12 flex flex-wrap items-center justify-center gap-4">
            <Link href="/console" className="brut brut-coral inline-flex items-center gap-2 px-8 py-5 text-base font-bold" style={{ borderRadius: 999 }}>
              进入实时控制台 →
            </Link>
            <button type="button" title="内部页 · 即将开放" className="rounded-full border border-white/15 px-8 py-5 text-base font-medium text-slate-200 transition hover:border-white/35">
              登录 <span className="tag text-slate-500">内部</span>
            </button>
          </div>
        </Reveal>
      </section>

      <div className="mx-auto max-w-[1320px] px-8 pb-10">
        <Ticker />
        <div className="hr-thin mb-4 mt-8 opacity-40" />
        <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-600">
          <span>BYWOOD 芭梧 · 体系化增长服务商</span>
          <span>全域阵地 · {BRAND.fields}</span>
        </div>
      </div>
    </main>
  );
}

function sum(rows: { lever: string; audience: string; n: number }[], key: "lever" | "audience", val: string) {
  return rows.filter((r) => r[key] === val).reduce((s, r) => s + r.n, 0);
}

function HeroStat({ label, value, fmt }: { label: string; value: number; fmt: "cn" | "comma" }) {
  return (
    <div>
      <div className="h1 num text-white"><CountUp value={value} format={fmt} duration={1800} /></div>
      <div className="tag mt-1 text-slate-500">{label}</div>
    </div>
  );
}

function MiniStat({ label, value, fmt, sub }: { label: string; value: number; fmt: "cn" | "comma"; sub?: string }) {
  return (
    <div className="brut brut-ink">
      <span className="tag text-slate-400">{label}</span>
      <div className="title num mt-1 text-white"><CountUp value={value} format={fmt} duration={1600} /></div>
      {sub && <div className="mini mt-1 text-slate-500">{sub}</div>}
    </div>
  );
}

function StatMini({ n, l }: { n: number; l: string }) {
  return (
    <div>
      <div className="text-base font-bold text-ink">{comma(n)}</div>
      <div className="mini opacity-60">{l}</div>
    </div>
  );
}

/** 02 幕:Sankey 钉住,4 步解说随滚动高亮(framer useScroll 驱动) */
function FlywheelAct({ o }: { o: DashData["o"] }) {
  const ref = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end end"] });
  const steps = [
    { k: "全域投放数据流", d: "5 大阵地的真实投放结果持续汇入。" },
    { k: "ROC 智能中台", d: `每条内容经 ${AI_DIMS} 维 AI 解析,沉淀为结构化策略库。` },
    { k: "跨域审美注入 · AI 决策回流", d: "验证级爆款经验,实时回流两个生产端。" },
    { k: "越用越强", d: "发得越多 → 库越准 → 命中越高 → 再发。飞轮自转。" },
  ];
  const [step, setStep] = useState(0);
  useMotionValueEvent(scrollYProgress, "change", (v) => {
    const i = Math.min(steps.length - 1, Math.max(0, Math.floor(v * steps.length)));
    setStep(i);
  });

  return (
    <section ref={ref} className="relative" style={{ height: `${steps.length * 75}vh` }}>
      <div className="sticky top-0 flex h-screen flex-col justify-center">
        <div className="mx-auto w-full max-w-[1320px] px-8">
          <div className="tag text-slate-500">02 — 数据飞轮</div>
          <h2 className="title mt-3 text-white">生态数据流 <span className="text-coral">/</span> FLYWHEEL</h2>
          <div className="mt-6 brut brut-ink noise relative overflow-hidden">
            <Sankey impressions={o.impressions} notes={o.notes} baokuan={o.baokuanReal} cards={o.cards} />
          </div>
          <div className="mt-6 grid gap-3 sm:grid-cols-4">
            {steps.map((s, i) => (
              <div key={i} className="transition-opacity duration-500" style={{ opacity: i === step ? 1 : 0.28 }}>
                <div className="flex items-center gap-2">
                  <span className={`text-sm font-bold ${i === step ? "text-coral" : "text-white"}`}>0{i + 1}</span>
                  <span className="text-sm font-bold text-white">{s.k}</span>
                </div>
                <div className="mini mt-1 text-slate-400">{s.d}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
