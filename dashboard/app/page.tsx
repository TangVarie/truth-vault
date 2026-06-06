"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { BRAND } from "@/config/brand";

/**
 * 开篇视效 / 落地页(docs/24 §A-intro)。BYWOOD 芭梧 品牌动态介绍 +
 * 两个入口:进入公众看板(免登录)/ 登录(内部,待开放)。
 * 信息取自公司名片 PDF;设计=动态编排(framer-motion 入场 + 旋转飞轮)。
 */

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.11, delayChildren: 0.15 } },
};
const item = {
  hidden: { opacity: 0, y: 18 },
  show: { opacity: 1, y: 0, transition: { duration: 0.7, ease: [0.22, 1, 0.36, 1] } },
};

function FlywheelRings() {
  // 背景旋转飞轮(呼应"数据飞轮·越用越强")
  return (
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center overflow-hidden">
      <svg className="animate-spin-slow opacity-[0.13]" width="900" height="900" viewBox="0 0 900 900">
        <circle cx="450" cy="450" r="430" fill="none" stroke="#1b4fd1" strokeWidth="1.5" strokeDasharray="2 14" />
        <circle cx="450" cy="450" r="360" fill="none" stroke="#5eead4" strokeWidth="1" strokeDasharray="1 22" />
      </svg>
      <svg className="absolute animate-spin-rev opacity-[0.10]" width="640" height="640" viewBox="0 0 640 640">
        <circle cx="320" cy="320" r="300" fill="none" stroke="#1b4fd1" strokeWidth="1.5" strokeDasharray="60 30" />
      </svg>
    </div>
  );
}

export default function Landing() {
  return (
    <main className="bywood-bg animate-gradient relative min-h-screen overflow-hidden">
      <FlywheelRings />

      {/* 顶栏 */}
      <div className="relative mx-auto flex max-w-6xl items-center justify-between px-6 py-6 text-xs tracking-widest text-slate-400">
        <span>§ {BRAND.studio}</span>
        <span>{BRAND.tagline} · {BRAND.taglineEn}</span>
      </div>

      <motion.section
        variants={container}
        initial="hidden"
        animate="show"
        className="relative mx-auto flex max-w-4xl flex-col items-center px-6 pb-20 pt-10 text-center"
      >
        {/* 品牌 */}
        <motion.div variants={item} className="flex items-end gap-4">
          <span className="text-6xl font-black tracking-tight text-white sm:text-7xl">{BRAND.name}</span>
          <span className="mb-2 text-3xl font-bold text-bywood-blue sm:text-4xl">{BRAND.nameCn}</span>
        </motion.div>
        <motion.div variants={item} className="mt-2 text-sm tracking-[0.3em] text-slate-400">
          {BRAND.taglineEn}
        </motion.div>

        {/* headline */}
        <motion.h1 variants={item} className="mt-8 text-3xl font-bold leading-snug text-white sm:text-4xl">
          {BRAND.headlineLead}
          <span className="text-bywood-red">{BRAND.headlineAccent}</span>。
        </motion.h1>
        <motion.p variants={item} className="mt-4 max-w-2xl text-sm leading-relaxed text-slate-400">
          {BRAND.whatWeDo}
        </motion.p>

        {/* 增长链路:心智 → 决策 → 复利 */}
        <motion.div variants={item} className="mt-10 flex flex-wrap items-center justify-center gap-3">
          {BRAND.growthLink.map((g, i) => (
            <div key={g.id} className="flex items-center gap-3">
              <div className="rounded-2xl border border-white/10 bg-white/5 px-5 py-3 text-left">
                <div className="flex items-baseline gap-2">
                  <span className="text-xl font-bold text-white">{g.cn}</span>
                  <span className="text-[10px] tracking-widest text-slate-500">{g.en}</span>
                </div>
                <div className="mt-0.5 text-xs text-slate-400">{g.sub}</div>
              </div>
              {i < BRAND.growthLink.length - 1 && <span className="text-bywood-blue">→</span>}
            </div>
          ))}
        </motion.div>

        {/* 扶摇 ROC 紧凑条 */}
        <motion.div variants={item} className="mt-8 w-full max-w-2xl rounded-2xl border border-bywood-blue/30 bg-bywood-blue/10 p-5">
          <div className="mb-3 flex items-center justify-between">
            <span className="text-lg font-semibold text-white">{BRAND.roc.title}</span>
            <span className="text-xs tracking-widest text-slate-400">{BRAND.roc.note}</span>
          </div>
          <div className="grid gap-2 sm:grid-cols-3">
            {BRAND.roc.steps.map((s) => (
              <div key={s.k} className="rounded-xl bg-black/20 p-3 text-left">
                <div className="flex items-center gap-2">
                  <span className="flex h-6 w-6 items-center justify-center rounded-md bg-bywood-blue text-xs font-bold text-white">
                    {s.k}
                  </span>
                  <span className="text-sm font-medium text-white">{s.act}</span>
                </div>
                <div className="mt-1 text-[11px] text-slate-400">{s.name}</div>
              </div>
            ))}
          </div>
        </motion.div>

        {/* tagline */}
        <motion.div variants={item} className="mt-10 text-2xl font-bold text-white sm:text-3xl">
          {BRAND.footerLead}
          <span className="text-bywood-blue">{BRAND.footerAccent}</span>
        </motion.div>

        {/* 入口 */}
        <motion.div variants={item} className="mt-9 flex flex-wrap items-center justify-center gap-4">
          <Link
            href="/console"
            className="group rounded-full bg-white px-7 py-3 text-sm font-semibold text-bywood-navy transition hover:bg-bywood-accent"
          >
            进入公众看板 <span className="transition group-hover:translate-x-1 inline-block">→</span>
          </Link>
          <button
            type="button"
            title="内部页 · 即将开放(Phase 3 接 auth)"
            className="rounded-full border border-white/20 px-7 py-3 text-sm font-medium text-slate-300 transition hover:border-white/40"
          >
            登录 <span className="text-slate-500">（内部 · 即将开放）</span>
          </button>
        </motion.div>

        <motion.div variants={item} className="mt-8 text-xs text-slate-500">
          全域阵地 · {BRAND.fields}
        </motion.div>
      </motion.section>
    </main>
  );
}
