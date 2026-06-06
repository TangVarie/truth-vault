"use client";

import { PROJECT_SHORT } from "@/config/showcase";
import CountUp from "./CountUp";

export type TopHit = {
  rank: number;
  project_id: string;
  lever: string | null;
  tier: string;
  interactions: number;
  reads: number;
  impressions: number;
};

/**
 * Top 爆款拆解榜 —— 编辑级排版。
 *
 * 每行:rank · 战线 chip(α/β/γ/δ)· 杠杆 chip(若无 → "AI 解析中")· 互动 / 阅读 / 曝光 三列大数。
 * 数据来自 public.v_dash_top_hits(只有 project/lever/指标,绝不暴露 title/body)。
 */
export default function Leaderboard({ hits }: { hits: TopHit[] }) {
  if (!hits.length) return <div className="text-sm text-slate-500">—</div>;
  return (
    <div className="space-y-2">
      {/* 表头 */}
      <div className="mini grid grid-cols-[40px_56px_1fr_90px_90px_90px] items-center gap-3 px-3 pb-2 text-slate-500">
        <span>#</span>
        <span>战线</span>
        <span>策略原型</span>
        <span className="text-right">互动</span>
        <span className="text-right">阅读</span>
        <span className="text-right">曝光</span>
      </div>
      {hits.slice(0, 6).map((h, i) => {
        const isTop = h.rank === 1;
        return (
          <div
            key={i}
            className={`rise grid grid-cols-[40px_56px_1fr_90px_90px_90px] items-center gap-3 rounded-2xl border px-3 py-3 transition hover:-translate-y-0.5 ${
              isTop
                ? "border-coral/40 bg-coral/10"
                : "border-white/8 bg-white/[0.02] hover:bg-white/[0.04]"
            }`}
            style={{ animationDelay: `${i * 80}ms` }}
          >
            <span className={`h2 num ${isTop ? "text-coral" : "text-slate-400"}`}>{h.rank}</span>
            <span className="inline-flex h-7 w-9 items-center justify-center rounded-md bg-white/8 text-sm font-bold text-white">
              {PROJECT_SHORT[h.project_id] ?? "·"}
            </span>
            <span className="flex items-center gap-2 text-sm">
              {h.lever ? (
                <span className="rounded-full bg-coral/15 px-3 py-1 text-xs font-medium text-coral">
                  {h.lever}
                </span>
              ) : (
                <span className="rounded-full border border-white/10 px-3 py-1 text-xs text-slate-500">
                  AI 解析中
                </span>
              )}
              <span className="tag text-slate-500">{h.tier}</span>
            </span>
            <span className="num text-right text-base font-bold text-white">
              <CountUp value={h.interactions} format="comma" duration={1200 + i * 100} />
            </span>
            <span className="num text-right text-base font-bold text-white">
              <CountUp value={h.reads} format="cn" duration={1300 + i * 100} />
            </span>
            <span className="num text-right text-base font-bold text-coral">
              <CountUp value={h.impressions} format="cn" duration={1400 + i * 100} />
            </span>
          </div>
        );
      })}
    </div>
  );
}
