"use client";

import { TICKER_EVENTS } from "@/config/showcase";

/**
 * 横向无缝滚动活动流(.marquee)。对外"活着在动"的播报条。
 * 列表复制一份做无缝循环;措辞走专业口径(showcase.TICKER_EVENTS)。
 */
export default function Ticker() {
  const items = [...TICKER_EVENTS, ...TICKER_EVENTS];
  return (
    <div className="relative overflow-hidden rounded-full border border-white/10 bg-white/[0.03] py-2">
      <div className="marquee flex w-max gap-10 whitespace-nowrap">
        {items.map((e, i) => (
          <span key={i} className="flex items-center gap-2 text-xs text-slate-400">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-flywheel-accent" />
            {e}
          </span>
        ))}
      </div>
      {/* 两侧渐隐遮罩 */}
      <div className="pointer-events-none absolute inset-y-0 left-0 w-16 bg-gradient-to-r from-[#0a0e1a] to-transparent" />
      <div className="pointer-events-none absolute inset-y-0 right-0 w-16 bg-gradient-to-l from-[#0a0e1a] to-transparent" />
    </div>
  );
}
