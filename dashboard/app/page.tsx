"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { BRAND } from "@/config/brand";

/**
 * 开篇视效 / 落地页(docs/24 §A-intro)。BYWOOD 芭梧 品牌动态介绍 +
 * 两个入口:进入公众看板(免登录)/ 登录(内部,待开放)。
 * 信息取自公司名片 PDF;设计=动态编排(framer-motion 入场 + 发光旋转飞轮 + 浮动光斑)。
 */

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.1, delayChildren: 0.12 } },
};
const item = {
  hidden: { opacity: 0, y: 18 },
  show: { opacity: 1, y: 0, transition: { duration: 0.7, ease: [0.22, 1, 0.36, 1] } },
};

function HeroBackdrop() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      {/* 旋转发光环(呼应"数据飞轮·越用越强") */}
      <div className="absolute inset-0 flex items-center justify-center">
        <svg
          className="ring-glow animate-spin-slow opacity-60"
          width="860"
          height="860"
          viewBox="0 0 860 860"
        >
          <defs>
            <linearGradient id="hr" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#5eead4" />
              <stop offset="50%" stopColor="#1b4fd1" />
              <stop offset="100%" stopColor="#cc2128" />
            </linearGradient>
          </defs>
          <circle cx="430" cy="430" r="412" fill="none" stroke="url(#hr)" strokeOpacity="0.4" strokeWidth="1.5" strokeDasharray="2 16" />
          <circle cx="430" cy="430" r="336" fill="none" stroke="#1b4fd1" strokeOpacity="0.22" strokeWidth="1" strokeDasharray="1 20" />
        </svg>
      </div>
      <div className="absolute inset-0 flex items-center justify-center">
        <svg className="animate-spin-rev opacity-40" width="580" height="580" viewBox="0 0 580 580">
          <circle cx="290" cy="290" r="272" fill="none" stroke="#5eead4" strokeOpacity="0.28" strokeWidth="1.2" strokeDasharray="48 28" />
        </svg>
      </div>
      {/* 浮动光斑 */}
      <div className="absolute left-[11%] top-[20%] h-44 w-44 rounded-full bg-bywood-blue/20 blur-3xl animate-float" />
      <div
        className="absolute right-[12%] bottom-[16%] h-52 w-52 rounded-full bg-flywheel-accent/10 blur-3xl animate-float"
        style={{ animationDelay: "1.6s" }}
      />
    </div>
  );
}

export default function Landing() {
  return (
    <main className="bywood-bg grid-bg animate-gradient relative min-h-screen overflow-hidden">
      <HeroBackdrop />

      {/* 顶栏 */}
      <div className="relative mx-auto flex max-w-6xl items-center justify-between px-6 py-6 text-xs tracking-widest text-slate-400">
        <span className="font-medium">§ {BRAND.studio}</span>
        <span className="hidden sm:block">
          {BRAND.tagline} · {BRAND.taglineEn}
        </span>
      </div>

      <motion.section
        variants={container}
        initial="hidden"
        animate="show"
        className="relative mx-auto flex max-w-4xl flex-col items-center px-6 pb-24 pt-12 text-center"
      >
        {/* 品牌 */}
        <motion.div variants={item} className="flex items-end gap-4">
          <span className="text-glow text-6xl font-black tracking-tight text-white sm:text-8xl">
            {BRAND.name}
          </span>
          <span className="mb-2 text-3xl font-bold text-bywood-blue sm:text-4xl">{BRAND.nameCn}</span>
        </motion.div>
        <motion.div variants={item} className="mt-3 text-xs tracking-[0.4em] text-slate-400 sm:text-sm">
          {BRAND.taglineEn}
        </motion.div>

        {/* headline */}
        <motion.h1
          variants={item}
          className="mt-9 text-3xl font-bold leading-snug text-white sm:text-5xl"
        >
          {BRAND.headlineLead}
          <span className="text-bywood-red">{BRAND.headlineAccent}</span>。
        </motion.h1>
        <motion.p
          variants={item}
          className="mt-5 max-w-2xl text-sm leading-relaxed text-slate-400 sm:text-base"
        >
          {BRAND.whatWeDo}
        </motion.p>

        {/* 增长链路:心智 → 决策 → 复利 */}
        <motion.div variants={item} className="mt-12 flex flex-wrap items-center justify-center gap-3">
          {BRAND.growthLink.map((g, i) => (
            <div key={g.id} className="flex items-center gap-3">
              <div className="glass rounded-2xl px-5 py-3 text-left transition hover:-translate-y-0.5 hover:border-bywood-blue/40">
                <div className="flex items-baseline gap-2">
                  <span className="text-xl font-bold text-white">{g.cn}</span>
                  <span className="text-[10px] tracking-widest text-slate-500">{g.en}</span>
                </div>
                <div className="mt-0.5 text-xs text-slate-400">{g.sub}</div>
              </div>
              {i < BRAND.growthLink.length - 1 && (
                <span className="text-lg text-bywood-blue">→</span>
              )}
            </div>
          ))}
        </motion.div>

        {/* 扶摇 ROC */}
        <motion.div
          variants={item}
          className="mt-9 w-full max-w-2xl rounded-3xl border border-bywood-blue/30 bg-bywood-blue/10 p-6 backdrop-blur"
        >
          <div className="mb-4 flex items-center justify-between">
            <span className="text-lg font-semibold text-white">{BRAND.roc.title}</span>
            <span className="text-xs tracking-widest text-slate-400">{BRAND.roc.note}</span>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            {BRAND.roc.steps.map((s) => (
              <div key={s.k} className="rounded-2xl bg-black/25 p-4 text-left">
                <div className="flex items-center gap-2">
                  <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-bywood-blue text-sm font-bold text-white shadow-[0_0_14px_rgba(27,79,209,0.6)]">
                    {s.k}
                  </span>
                  <span className="text-sm font-medium text-white">{s.act}</span>
                </div>
                <div className="mt-1.5 text-[11px] text-slate-400">{s.name}</div>
              </div>
            ))}
          </div>
        </motion.div>

        {/* tagline */}
        <motion.div variants={item} className="mt-12 text-2xl font-bold text-white sm:text-3xl">
          {BRAND.footerLead}
          <span className="text-glow text-bywood-blue">{BRAND.footerAccent}</span>
        </motion.div>

        {/* 入口 */}
        <motion.div variants={item} className="mt-10 flex flex-wrap items-center justify-center gap-4">
          <Link
            href="/console"
            className="group rounded-full bg-white px-8 py-3.5 text-sm font-semibold text-bywood-navy shadow-[0_0_30px_rgba(94,234,212,0.25)] transition hover:bg-flywheel-accent hover:shadow-[0_0_40px_rgba(94,234,212,0.5)]"
          >
            进入公众看板{" "}
            <span className="inline-block transition group-hover:translate-x-1">→</span>
          </Link>
          <button
            type="button"
            title="内部页 · 即将开放(Phase 3 接 auth)"
            className="rounded-full border border-white/20 px-8 py-3.5 text-sm font-medium text-slate-300 transition hover:border-white/40"
          >
            登录 <span className="text-slate-500">（内部 · 即将开放）</span>
          </button>
        </motion.div>

        <motion.div variants={item} className="mt-9 text-xs text-slate-500">
          全域阵地 · {BRAND.fields}
        </motion.div>
      </motion.section>
    </main>
  );
}
