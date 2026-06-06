"use client";

import { TICKER_EVENTS } from "@/config/showcase";

/**
 * 横向无缝滚动活动流(.marquee)。对外"活着在动"的播报条 —— 编辑级排版,coral 圆点。
 */
export default function Ticker() {
  const items = [...TICKER_EVENTS, ...TICKER_EVENTS];
  return (
    <div className="relative overflow-hidden border-y border-white/10 py-3">
      <div className="marquee flex w-max gap-12 whitespace-nowrap">
        {items.map((e, i) => (
          <span key={i} className="tag flex items-center gap-2 text-slate-400">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-coral" />
            {e}
          </span>
        ))}
      </div>
      <div className="pointer-events-none absolute inset-y-0 left-0 w-20 bg-gradient-to-r from-ink to-transparent" />
      <div className="pointer-events-none absolute inset-y-0 right-0 w-20 bg-gradient-to-l from-ink to-transparent" />
    </div>
  );
}
