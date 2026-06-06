"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";
import { motion, useScroll, useTransform, type MotionValue } from "framer-motion";
import {
  AI_DIMS,
  ARCHETYPES,
  cnNum,
  comma,
  derivedAiInferences,
  derivedStrategySpace,
  PROJECT_LABEL,
  PROJECT_SHORT,
  TICKER_EVENTS,
} from "@/config/showcase";
import type { DashboardData, Matrix as MatrixT } from "@/lib/dashboard-data";
import SmoothScroll from "@/components/SmoothScroll";
import Reveal from "@/components/Reveal";
import CountUp from "@/components/CountUp";
import EditorialFlywheel from "@/components/EditorialFlywheel";
import EditorialCurve from "@/components/EditorialCurve";

/**
 * 「Bone & Ink」编辑级落地页(方向 A)。
 * 暖纸底 + Fraunces 衬线 + 巨号数字(取代图表卡)+ 黄铜发丝线 + 双下划线强调 + Lenis 平滑滚动。
 * 与 /console 暗色座舱"同数据、反语法"。数据来自服务端 getDashboardData。
 */

const ease = [0.22, 1, 0.36, 1] as const;
const stagger = { hidden: {}, show: { transition: { staggerChildren: 0.1, delayChildren: 0.05 } } };
const rise = { hidden: { opacity: 0, y: 24 }, show: { opacity: 1, y: 0, transition: { duration: 0.85, ease } } };

export default function Editorial({ data }: { data: DashboardData }) {
  const { o, projects, matrix, hits } = data;
  const aiInferences = derivedAiInferences(o.notes);
  const strategySpace = derivedStrategySpace(o.levers, o.audiences);
  const levOrder = uniqSortBy(matrix, "lever");
  const audOrder = uniqSortBy(matrix, "audience");

  // 暖纸底铺到 overscroll(并切到 light 配色),离开页面还原
  useEffect(() => {
    const body = document.body.style.background;
    const scheme = document.documentElement.style.colorScheme;
    document.body.style.background = "#F3EEE6";
    document.documentElement.style.colorScheme = "light";
    return () => {
      document.body.style.background = body;
      document.documentElement.style.colorScheme = scheme;
    };
  }, []);

  return (
    <SmoothScroll>
      <div className="editorial relative min-h-screen">
        <div className="grain" aria-hidden />
        <Nav />

        {/* ── 00 · 品牌 manifesto ── */}
        <section className="scene relative flex min-h-screen flex-col justify-center px-8">
          <motion.div variants={stagger} initial="hidden" animate="show" className="mx-auto w-full max-w-[1180px]">
            <motion.div variants={rise} className="ed-eyebrow">§ BYWOOD STUDIO · 体系化增长服务商</motion.div>
            <motion.div variants={rise} className="rule-brass mt-4 max-w-[120px]" />
            <motion.h1 variants={rise} className="ed-wordmark fr mt-8" style={{ color: "#14110F" }}>
              BYWOOD
            </motion.h1>
            <motion.div
              variants={rise}
              className="cjk mt-1"
              style={{ color: "#7A2E22", fontSize: "clamp(30px,6vw,68px)", fontWeight: 500, letterSpacing: "0.06em", lineHeight: 1 }}
            >
              芭梧
            </motion.div>
            <motion.h2 variants={rise} className="ed-title fr mt-10 max-w-3xl" style={{ color: "#14110F" }}>
              把策略,变成<span className="u2">越用越准</span>的增长复利。
            </motion.h2>
            <motion.p variants={rise} className="ed-lead mt-6 max-w-2xl" style={{ color: "#3D3A34" }}>
              一套结构化飞轮,照见从投放到决策到复利的每一环。
            </motion.p>
            <motion.div variants={rise} className="mn mt-10 flex flex-wrap items-center gap-x-4 gap-y-2" style={{ fontSize: 12, color: "#8A7F6D", letterSpacing: "0.08em" }}>
              <span>全域阵地 · 小红书 / 播客 / 知乎 / 头条 / 微博</span>
            </motion.div>
          </motion.div>
          <ScrollCue />
        </section>

        {/* ── 01 · 越用越准 ── */}
        <section className="scene flex min-h-screen flex-col justify-center px-8 py-28">
          <div className="mx-auto w-full max-w-[1180px]">
            <Reveal className="ed-eyebrow">01 — 越用越准 / COMPOUNDING</Reveal>
            <Reveal delay={60}>
              <h2 className="ed-title fr mt-4" style={{ color: "#14110F" }}>越用越准。</h2>
            </Reveal>
            <Reveal delay={120} className="mt-14">
              <div className="ed-numeral fr" style={{ color: "#E8765A" }}>
                <CountUp value={o.impressions} format="cn" duration={2200} />
              </div>
              <div className="mn mt-3" style={{ fontSize: 13, color: "#8A7F6D", letterSpacing: "0.06em" }}>
                ↑ 累计内容曝光 · CUMULATIVE IMPRESSIONS
              </div>
              <p className="ed-lead mt-6 max-w-2xl" style={{ color: "#3D3A34" }}>
                投放真实结果实时回流。结构化策略库已沉淀可迁移策略原型{" "}
                <b style={{ color: "#14110F" }}><CountUp value={o.levers} duration={1000} /></b> 类、受众画像{" "}
                <b style={{ color: "#14110F" }}><CountUp value={o.audiences} duration={1000} /></b> 维 —— <span className="u2">合作越久,命中率越高</span>。
              </p>
            </Reveal>
            <Reveal delay={120} mountOnView className="mt-16 min-h-[320px]">
              <div className="mn mb-3" style={{ fontSize: 11, color: "#8A7F6D", letterSpacing: "0.2em" }}>复利累计曲线 · 先缓后陡</div>
              <EditorialCurve total={o.impressions} />
            </Reveal>
          </div>
        </section>

        {/* ── 02 · 数据飞轮(sticky 钉住)── */}
        <FlywheelScene o={o} />

        {/* ── 03 · 策略 × 受众 共振 ── */}
        <section className="scene flex min-h-screen flex-col justify-center px-8 py-28">
          <div className="mx-auto w-full max-w-[1180px]">
            <Reveal className="ed-eyebrow">03 — 策略 × 受众 / RESONANCE</Reveal>
            <Reveal delay={60}>
              <h2 className="ed-title fr mt-4" style={{ color: "#14110F" }}>
                命中,是<span className="u2">共振</span>出来的。
              </h2>
            </Reveal>
            <div className="rule-ink mt-12 grid gap-10 pt-10 sm:grid-cols-2">
              <Reveal>
                <BigStat value={strategySpace} label="策略组合空间" sub={`${o.levers} 杠杆 × ${o.audiences} 受众 × ${ARCHETYPES} 人性原型`} />
              </Reveal>
              <Reveal delay={80}>
                <BigStat value={aiInferences} label="AI 推理深度" sub={`${AI_DIMS} 维 × ${comma(o.notes)} 内容资产`} />
              </Reveal>
            </div>
            <Reveal delay={80} mountOnView className="mt-14 min-h-[300px]">
              <div className="mn mb-4" style={{ fontSize: 11, color: "#8A7F6D", letterSpacing: "0.2em" }}>
                深 → coral 表共振强度 · 描边格 = Top 3 命中区
              </div>
              <Matrix cells={matrix} levers={levOrder} audiences={audOrder} />
            </Reveal>
          </div>
        </section>

        {/* ── 04 · 战绩 ── */}
        <section className="scene flex min-h-screen flex-col justify-center px-8 py-28">
          <div className="mx-auto w-full max-w-[1180px]">
            <Reveal className="ed-eyebrow">04 — 战绩 / TRACK RECORD</Reveal>
            <Reveal delay={60}>
              <h2 className="ed-title fr mt-4" style={{ color: "#14110F" }}>
                真实结果,<span className="u2">可查证</span>。
              </h2>
            </Reveal>

            <Reveal delay={80} className="mt-12">
              <Leaderboard hits={hits} topInteractions={o.topInteractions} />
            </Reveal>

            <div className="rule-ink mt-14 grid grid-cols-2 gap-x-8 gap-y-10 pt-10 lg:grid-cols-4">
              {projects.map((p, i) => (
                <Reveal key={p.project_id} delay={i * 70}>
                  <div className="mn" style={{ fontSize: 11, color: "#8A7F6D", letterSpacing: "0.1em" }}>
                    {PROJECT_LABEL[p.project_id] ?? p.project_id}
                  </div>
                  <div className="ed-numeral fr mt-2" style={{ color: "#14110F", fontSize: "clamp(40px,5vw,72px)" }}>
                    <CountUp value={p.impressions} format="cn" duration={1500 + i * 100} />
                  </div>
                  <div className="ed-mini mt-1" style={{ color: "#8A7F6D" }}>累计曝光</div>
                  <div className="mn mt-5 flex gap-5" style={{ fontSize: 11, color: "#3D3A34" }}>
                    <span>{comma(p.notes)} 资产</span>
                    <span>{comma(p.baokuan)} 爆款</span>
                    <span>{comma(p.essence)} 解析</span>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        {/* ── 05 · 落到看板(门后即座舱)── */}
        <section className="scene flex min-h-screen flex-col justify-center px-8 py-28">
          <div className="mx-auto w-full max-w-[1180px]">
            <Reveal className="ed-eyebrow">05 — 实时态势 / LIVE</Reveal>
            <Reveal delay={60}>
              <h2 className="ed-title fr mt-4" style={{ color: "#14110F" }}>
                实时态势,<br />照见整座<span className="u2">飞轮</span>。
              </h2>
            </Reveal>

            <Reveal delay={100} className="rule-ink mt-12 grid grid-cols-2 gap-x-8 gap-y-8 pt-10 sm:grid-cols-4">
              <SmallStat value={o.projects} label="战线" />
              <SmallStat value={o.baokuanReal} label="验证级爆款" />
              <SmallStat value={o.cards} label="策略经验卡" />
              <SmallStat value={o.essence} label="结构化内核" />
            </Reveal>

            {/* 门:纸上的一块暗色座舱预览 → 进入 /console */}
            <Reveal delay={140} className="mt-16 flex flex-col items-start gap-6 sm:flex-row sm:items-stretch">
              <Link
                href="/console"
                className="group relative block w-full overflow-hidden rounded-2xl sm:max-w-[420px]"
                style={{ background: "#0a0a0f", border: "1px solid rgba(20,17,15,0.18)" }}
              >
                <div className="grid-bg pointer-events-none absolute inset-0 opacity-60" />
                <div className="relative px-7 py-8">
                  <div className="flex items-center gap-2">
                    <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: "#E8765A" }} />
                    <span className="mn" style={{ fontSize: 11, color: "#9aa0aa", letterSpacing: "0.18em" }}>公众看板 · LIVE</span>
                  </div>
                  <div className="fr mt-6" style={{ color: "#f3f4f6", fontSize: 30, fontWeight: 500, letterSpacing: "-0.01em" }}>
                    进入控制台 →
                  </div>
                  <div className="mn mt-2" style={{ fontSize: 12, color: "#6b7280" }}>密集实时看板 · 暗色座舱</div>
                </div>
              </Link>

              <div className="flex flex-col justify-center gap-3">
                <button type="button" title="内部页 · 即将开放(接 auth)" className="btn-ghost px-7 py-4 text-left text-base font-medium" style={{ color: "#14110F" }}>
                  登录 <span className="mn ml-1" style={{ fontSize: 11, color: "#8A7F6D" }}>内部 · 即将开放</span>
                </button>
                <p className="ed-mini max-w-[260px]" style={{ color: "#8A7F6D" }}>
                  这是品牌的门面;真正的机器,在门后的座舱里持续运转。
                </p>
              </div>
            </Reveal>

            <div className="mt-16">
              <EditorialTicker />
            </div>

            <footer className="rule-brass mt-12 pt-5">
              <div className="mn flex flex-wrap items-center justify-between gap-2" style={{ fontSize: 11, color: "#8A7F6D" }}>
                <span>BYWOOD 芭梧 · ROC 增长智能中台</span>
                <span>实时全链路 · 数据飞轮 · 越用越强</span>
              </div>
            </footer>
          </div>
        </section>
      </div>
    </SmoothScroll>
  );
}

/* ── 02 · sticky 钉住的飞轮场 ── */
function FlywheelScene({ o }: { o: DashboardData["o"] }) {
  const ref = useRef<HTMLElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end end"] });
  const steps = [
    "全域投放数据实时回流 ROC 智能中台,内容资产持续结构化。",
    "验证级爆款 → 跨域审美注入,高权重样本同步智能仿写网络。",
    "AI 决策回流 → 创作工作台借卡注入,命中即沉淀为策略经验卡。",
  ];
  return (
    <section ref={ref} className="relative h-[280vh]">
      <div className="sticky top-0 flex h-screen flex-col justify-center px-8">
        <div className="mx-auto grid w-full max-w-[1180px] items-center gap-12 lg:grid-cols-[1fr_360px]">
          <div>
            <span className="ed-eyebrow">02 — 数据飞轮 / FLYWHEEL</span>
            <h2 className="ed-title fr mt-4" style={{ color: "#14110F" }}>
              一个连接,<br />照见<span className="u2">整座生态</span>。
            </h2>
            <div className="mt-10">
              <EditorialFlywheel center={cnNum(o.notes)} caption="内容资产" />
            </div>
          </div>
          <div>
            <motion.div style={{ scaleX: scrollYProgress }} className="mb-8 h-px origin-left" aria-hidden>
              <div style={{ height: 1, background: "#B89B6A", width: "100%" }} />
            </motion.div>
            <div className="grid gap-7">
              {steps.map((s, i) => (
                <Step key={i} progress={scrollYProgress} i={i} total={steps.length} text={s} />
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function Step({ progress, i, total, text }: { progress: MotionValue<number>; i: number; total: number; text: string }) {
  const a = i / total;
  const b = (i + 1) / total;
  const opacity = useTransform(progress, [a - 0.1, a + 0.02, b, b + 0.06], [0.25, 1, 1, 0.45]);
  return (
    <motion.div style={{ opacity }} className="rule-ink pt-4">
      <div className="mn" style={{ fontSize: 12, color: "#E8765A", letterSpacing: "0.1em" }}>0{i + 1}</div>
      <p className="mt-2 text-[15px] leading-relaxed" style={{ color: "#3D3A34" }}>{text}</p>
    </motion.div>
  );
}

/* ── Top 爆款编辑级榜单(墨发丝线、Fraunces 数字)── */
function Leaderboard({ hits, topInteractions }: { hits: DashboardData["hits"]; topInteractions: number }) {
  if (!hits.length) {
    return <div className="ed-mini" style={{ color: "#8A7F6D" }}>Top 爆款数据准备中 —</div>;
  }
  return (
    <div>
      <div className="mn mb-3 grid grid-cols-[36px_52px_1fr_92px_92px] items-center gap-3 px-1" style={{ fontSize: 10.5, color: "#8A7F6D", letterSpacing: "0.12em" }}>
        <span>#</span>
        <span>战线</span>
        <span>策略原型</span>
        <span className="text-right">互动</span>
        <span className="text-right">曝光</span>
      </div>
      {hits.slice(0, 6).map((h, i) => (
        <div
          key={i}
          className="rule-ink grid grid-cols-[36px_52px_1fr_92px_92px] items-center gap-3 px-1 py-4"
        >
          <span className="fr" style={{ fontSize: 22, color: h.rank === 1 ? "#E8765A" : "#8A7F6D", fontWeight: 500 }}>{h.rank}</span>
          <span className="mn inline-flex h-7 w-9 items-center justify-center rounded-md" style={{ background: "rgba(20,17,15,0.06)", fontSize: 13, color: "#14110F" }}>
            {PROJECT_SHORT[h.project_id] ?? "·"}
          </span>
          <span className="flex items-center gap-2">
            {h.lever ? (
              <span className="rounded-full px-3 py-1 text-xs" style={{ background: "rgba(232,118,90,0.12)", color: "#7A2E22" }}>{h.lever}</span>
            ) : (
              <span className="mn rounded-full px-3 py-1" style={{ fontSize: 10.5, border: "1px solid rgba(20,17,15,0.15)", color: "#8A7F6D" }}>AI 解析中</span>
            )}
          </span>
          <span className="fr text-right" style={{ fontSize: 18, color: "#14110F" }}>
            <CountUp value={h.interactions} format="comma" duration={1200 + i * 100} />
          </span>
          <span className="fr text-right" style={{ fontSize: 18, color: "#E8765A" }}>
            <CountUp value={h.impressions} format="cn" duration={1300 + i * 100} />
          </span>
        </div>
      ))}
      <div className="mn mt-3" style={{ fontSize: 11, color: "#8A7F6D" }}>单篇最高 {comma(topInteractions)} 互动</div>
    </div>
  );
}

/* ── 编辑级共振矩阵(纸上 coral 浓淡)── */
function Matrix({ cells, levers, audiences }: { cells: MatrixT[]; levers: string[]; audiences: string[] }) {
  if (!cells.length) return <div className="ed-mini" style={{ color: "#8A7F6D" }}>共振矩阵数据准备中 —</div>;
  const idx = new Map<string, number>();
  cells.forEach((c) => idx.set(`${c.lever}|${c.audience}`, c.n));
  const max = Math.max(1, ...cells.map((c) => c.n));
  const top = new Set([...cells].sort((a, b) => b.n - a.n).slice(0, 3).map((c) => `${c.lever}|${c.audience}`));
  const cs = 34;
  const gap = 4;
  return (
    <div className="overflow-x-auto">
      <div style={{ minWidth: audiences.length * (cs + gap) + 130 }}>
        <div className="flex" style={{ paddingLeft: 118 }}>
          {audiences.map((a) => (
            <div key={a} className="mn truncate" style={{ width: cs + gap, textAlign: "center", fontSize: 10, color: "#8A7F6D" }} title={a}>{a}</div>
          ))}
        </div>
        {levers.map((lev) => (
          <div key={lev} className="flex items-center" style={{ marginTop: gap }}>
            <div className="mn truncate pr-3 text-right" style={{ width: 118, fontSize: 11, color: "#3D3A34" }} title={lev}>{lev}</div>
            {audiences.map((aud, ci) => {
              const key = `${lev}|${aud}`;
              const n = idx.get(key) ?? 0;
              const ratio = n / max;
              const isTop = top.has(key);
              return (
                <div
                  key={aud}
                  className="relative"
                  style={{
                    width: cs,
                    height: cs,
                    marginLeft: ci === 0 ? 0 : gap,
                    borderRadius: 7,
                    background: n === 0 ? "rgba(20,17,15,0.04)" : `rgba(232,118,90,${0.1 + ratio * 0.82})`,
                    boxShadow: isTop ? "0 0 0 1.5px #14110F" : "none",
                  }}
                  title={`${lev} × ${aud}: ${n}`}
                >
                  {n > 0 && (
                    <div className="absolute inset-0 flex items-center justify-center" style={{ fontSize: 10, fontWeight: 700, color: ratio > 0.5 ? "#F3EEE6" : "#7A2E22" }}>{n}</div>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── 编辑级横向活动流(纸底 · coral 圆点)── */
function EditorialTicker() {
  const items = [...TICKER_EVENTS, ...TICKER_EVENTS];
  return (
    <div className="rule-ink relative overflow-hidden py-3" style={{ borderBottom: "1px solid rgba(20,17,15,0.14)" }}>
      <div className="marquee flex w-max gap-12 whitespace-nowrap">
        {items.map((e, i) => (
          <span key={i} className="mn flex items-center gap-2" style={{ fontSize: 11, color: "#8A7F6D", letterSpacing: "0.06em" }}>
            <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: "#E8765A" }} />
            {e}
          </span>
        ))}
      </div>
    </div>
  );
}

function Nav() {
  return (
    <div className="pointer-events-none fixed inset-x-0 top-0 z-40">
      <div className="mx-auto flex max-w-[1180px] items-center justify-between px-8 py-6">
        <span className="mn" style={{ fontSize: 12, color: "#14110F", letterSpacing: "0.1em" }}>BYWOOD · ROC</span>
        <Link href="/console" className="mn pointer-events-auto" style={{ fontSize: 12, color: "#8A7F6D", letterSpacing: "0.08em" }}>
          进入控制台 →
        </Link>
      </div>
    </div>
  );
}

function ScrollCue() {
  return (
    <div className="absolute inset-x-0 bottom-10 z-10 flex justify-center">
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 1.1 }} className="flex flex-col items-center gap-2" style={{ color: "#8A7F6D" }}>
        <span className="ed-eyebrow">向下滚动</span>
        <motion.span animate={{ y: [0, 8, 0] }} transition={{ duration: 1.8, repeat: Infinity, ease: "easeInOut" }} style={{ color: "#E8765A" }}>↓</motion.span>
      </motion.div>
    </div>
  );
}

function BigStat({ value, label, sub }: { value: number; label: string; sub: string }) {
  return (
    <div>
      <div className="ed-numeral fr" style={{ color: "#14110F", fontSize: "clamp(48px,7vw,104px)" }}>
        <CountUp value={value} duration={1800} />
      </div>
      <div className="mn mt-2" style={{ fontSize: 12, color: "#8A7F6D", letterSpacing: "0.1em" }}>{label}</div>
      <div className="ed-mini mt-1" style={{ color: "#3D3A34" }}>{sub}</div>
    </div>
  );
}

function SmallStat({ value, label }: { value: number; label: string }) {
  return (
    <div>
      <div className="fr" style={{ color: "#E8765A", fontSize: "clamp(34px,4.5vw,60px)", fontWeight: 480, lineHeight: 1 }}>
        <CountUp value={value} duration={1400} />
      </div>
      <div className="mn mt-2" style={{ fontSize: 11, color: "#8A7F6D", letterSpacing: "0.1em" }}>{label}</div>
    </div>
  );
}

function uniqSortBy(m: MatrixT[], key: "lever" | "audience"): string[] {
  const total = (v: string) => m.filter((x) => x[key] === v).reduce((s, x) => s + x.n, 0);
  return Array.from(new Set(m.map((x) => x[key]))).sort((a, b) => total(b) - total(a));
}
