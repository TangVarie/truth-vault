"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { BRAND } from "@/config/brand";

/**
 * 落地页 v4 编辑级 —— 同 /console 一套 DNA(brutalist 色块 + 极端字阶 + 唯一 coral 点睛色)。
 * 信息源 config/brand.ts(公司名片);设计语言走 Saving Goal / TransGlobal 编辑级,
 * 不再用旋转 spinner / 全屏 glow。两入口:进入公众看板(coral,主)/ 登录(轮廓 ghost,占位)。
 */

const stagger = {
  hidden: {},
  show: { transition: { staggerChildren: 0.08, delayChildren: 0.1 } },
};
const rise = {
  hidden: { opacity: 0, y: 22 },
  show: { opacity: 1, y: 0, transition: { duration: 0.7, ease: [0.22, 1, 0.36, 1] } },
};

export default function Landing() {
  return (
    <main className="bg-landing relative min-h-screen overflow-hidden">
      {/* 顶栏 */}
      <div className="mx-auto flex max-w-[1320px] items-center justify-between px-8 py-6">
        <span className="tag text-slate-300">§ {BRAND.studio}</span>
        <span className="tag hidden text-slate-500 sm:block">{BRAND.taglineEn}</span>
      </div>

      <motion.section
        variants={stagger}
        initial="hidden"
        animate="show"
        className="mx-auto max-w-[1320px] px-8 pt-10"
      >
        {/* 品牌大字(编辑级,顶满) */}
        <motion.div variants={rise}>
          <div className="title text-coral">{BRAND.nameCn}</div>
          <h1 className="huge mt-2 text-white">{BRAND.name}</h1>
          <div className="tag mt-4 text-slate-400">{BRAND.tagline} · {BRAND.taglineEn}</div>
        </motion.div>

        {/* headline + what */}
        <motion.div variants={rise} className="mt-14 grid gap-10 lg:grid-cols-[1.4fr_1fr]">
          <h2 className="title text-white">
            从策略到执行到效果<br />
            一站式 <span className="text-coral">{BRAND.headlineAccent}</span>。
          </h2>
          <p className="self-end text-base leading-relaxed text-slate-300">
            {BRAND.whatWeDo}
          </p>
        </motion.div>

        {/* 增长链路 —— brutalist 三色块(心智 → 决策 → 复利)*/}
        <motion.div variants={rise} className="mt-16">
          <div className="tag mb-4 text-slate-500">GROWTH LINK · 增长链路</div>
          <div className="grid gap-4 sm:grid-cols-3">
            {/* 01 · 心智 / sage(浅) */}
            <div className="brut brut-sage relative overflow-hidden">
              <span className="tag opacity-60">01 / {BRAND.growthLink[0].en}</span>
              <div className="title mt-3">{BRAND.growthLink[0].cn}</div>
              <div className="mt-3 text-sm opacity-75">{BRAND.growthLink[0].sub}</div>
            </div>
            {/* 02 · 决策 / lavender */}
            <div className="brut brut-lavender relative overflow-hidden">
              <span className="tag opacity-60">02 / {BRAND.growthLink[1].en}</span>
              <div className="title mt-3">{BRAND.growthLink[1].cn}</div>
              <div className="mt-3 text-sm opacity-75">{BRAND.growthLink[1].sub}</div>
            </div>
            {/* 03 · 复利 / coral(主) */}
            <div className="brut brut-coral relative overflow-hidden">
              <span className="tag opacity-70">03 / {BRAND.growthLink[2].en}</span>
              <div className="title mt-3">{BRAND.growthLink[2].cn}</div>
              <div className="mt-3 text-sm opacity-80">{BRAND.growthLink[2].sub}</div>
            </div>
          </div>
        </motion.div>

        {/* 扶摇 ROC —— 三步编辑式陈列 */}
        <motion.div variants={rise} className="mt-16">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div>
              <span className="tag text-slate-500">METHODOLOGY</span>
              <h3 className="h1 mt-1 text-white">{BRAND.roc.title}</h3>
            </div>
            <span className="mini text-slate-500">{BRAND.roc.note}</span>
          </div>
          <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-400">
            {BRAND.roc.subtitle}
          </p>
          <div className="mt-6 grid gap-4 sm:grid-cols-3">
            {BRAND.roc.steps.map((s, i) => (
              <div key={s.k} className="brut brut-carbon relative">
                <div className="flex items-center gap-4">
                  <span className="title text-coral">{s.k}</span>
                  <div>
                    <div className="tag text-slate-400">{`0${i + 1}`} / {s.name}</div>
                    <div className="h2 mt-1 text-white">{s.act}</div>
                  </div>
                </div>
                <p className="mt-4 text-sm leading-relaxed text-slate-400">{s.detail}</p>
              </div>
            ))}
          </div>
        </motion.div>

        {/* 为什么是我们 —— 三段陈述 */}
        <motion.div variants={rise} className="mt-16">
          <div className="tag mb-4 text-slate-500">WHY US</div>
          <div className="grid gap-8 sm:grid-cols-3">
            {BRAND.whyUs.map((w) => (
              <div key={w.t}>
                <div className="h2 text-white">{w.h}</div>
                <div className="tag mt-1 text-coral">{w.t}</div>
                <p className="mt-3 text-sm leading-relaxed text-slate-400">{w.d}</p>
              </div>
            ))}
          </div>
        </motion.div>

        {/* footer line + 入口 */}
        <motion.div variants={rise} className="mt-20">
          <div className="title text-white">
            {BRAND.footerLead}<span className="text-coral">{BRAND.footerAccent}</span>
          </div>
          <div className="mt-10 flex flex-wrap items-stretch gap-4">
            <Link
              href="/console"
              className="brut brut-coral inline-flex items-center gap-3 px-7 py-5 text-base font-bold transition hover:brightness-105"
              style={{ borderRadius: 999 }}
            >
              进入公众看板 →
            </Link>
            <button
              type="button"
              title="内部页 · 即将开放(Phase 3 接 auth)"
              className="inline-flex items-center gap-2 rounded-full border border-white/15 px-7 py-5 text-base font-medium text-slate-200 transition hover:border-white/35"
            >
              登录 <span className="tag text-slate-500">内部 · 即将开放</span>
            </button>
          </div>
        </motion.div>

        <motion.div variants={rise} className="mt-16">
          <div className="hr-thin opacity-40" />
          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-500">
            <span>全域阵地 · {BRAND.fields}</span>
            <span>BYWOOD STUDIO · 体系化增长服务商</span>
          </div>
        </motion.div>
        <div className="h-16" />
      </motion.section>
    </main>
  );
}
