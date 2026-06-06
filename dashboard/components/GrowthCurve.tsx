"use client";

import { useEffect, useRef, useState } from "react";
import { useInView } from "framer-motion";
import { cnNum, cumulativeSeries } from "@/config/showcase";

/**
 * 复利增长曲线 —— 滚到视口才描线 + 面积渐入 + 大数 count-up。
 * (scrollytelling:动效绑定滚动,不在 mount 全放完。)
 */
export default function GrowthCurve({ total }: { total: number }) {
  const W = 1100, H = 240, padT = 14, padB = 20;
  const series = cumulativeSeries(total, 28);
  const max = series[series.length - 1] || 1;
  const step = W / (series.length - 1);
  const points = series.map((v, i) => [i * step, padT + (1 - v / max) * (H - padT - padB)] as [number, number]);
  const linePath = points.reduce((acc, [x, y], i) => {
    if (i === 0) return `M ${x} ${y}`;
    const [px, py] = points[i - 1];
    const cx = (px + x) / 2;
    return acc + ` C ${cx} ${py}, ${cx} ${y}, ${x} ${y}`;
  }, "");
  const areaPath = linePath + ` L ${(series.length - 1) * step} ${H - padB} L 0 ${H - padB} Z`;

  const wrapRef = useRef<HTMLDivElement>(null);
  const inView = useInView(wrapRef, { once: true, margin: "0px 0px -15% 0px" });

  const pathRef = useRef<SVGPathElement>(null);
  const [len, setLen] = useState<number | null>(null);
  useEffect(() => { if (pathRef.current) setLen(pathRef.current.getTotalLength()); }, []);

  const [shown, setShown] = useState(0);
  const started = useRef(false);
  useEffect(() => {
    if (!inView || started.current) return;
    started.current = true;
    const start = performance.now(), dur = 2200;
    const tick = (t: number) => {
      const p = Math.min(1, (t - start) / dur);
      const e = 1 - Math.pow(1 - p, 3);
      setShown(total * e);
      if (p < 1) requestAnimationFrame(tick); else setShown(total);
    };
    requestAnimationFrame(tick);
  }, [inView, total]);

  const lastPt = points[points.length - 1];

  return (
    <div ref={wrapRef}>
      <div className="mb-1 flex items-end justify-between">
        <div>
          <span className="tag text-slate-500">复利累计 · CUMULATIVE GROWTH</span>
          <div className="huge text-coral arrow-up" style={{ fontSize: "clamp(56px, 9vw, 120px)" }}>
            {cnNum(shown)}
          </div>
        </div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full">
        <defs>
          <linearGradient id="gc-area" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#E8765A" stopOpacity="0.5" />
            <stop offset="100%" stopColor="#E8765A" stopOpacity="0.0" />
          </linearGradient>
          <filter id="gc-glow" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="3" result="b" />
            <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>
        {[0.25, 0.5, 0.75].map((p, i) => (
          <line key={i} x1={0} x2={W} y1={padT + (H - padT - padB) * p} y2={padT + (H - padT - padB) * p}
            stroke="rgba(255,255,255,0.05)" strokeWidth={1} />
        ))}
        <path d={areaPath} fill="url(#gc-area)" style={{ opacity: inView ? 0.95 : 0, transition: "opacity 1.2s ease 0.3s" }} />
        <path
          ref={pathRef}
          d={linePath}
          fill="none"
          stroke="#E8765A"
          strokeWidth={2.5}
          strokeLinecap="round"
          style={{
            strokeDasharray: len ?? undefined,
            strokeDashoffset: inView ? 0 : (len ?? undefined),
            transition: len ? "stroke-dashoffset 1.9s cubic-bezier(.22,1,.36,1)" : undefined,
          }}
          filter="url(#gc-glow)"
        />
        {lastPt && (
          <circle cx={lastPt[0]} cy={lastPt[1]} r={5} fill="#fff" filter="url(#gc-glow)"
            style={{ opacity: inView ? 1 : 0, transition: "opacity .4s ease 1.6s" }}>
            <animate attributeName="r" values="5;7;5" dur="2.2s" repeatCount="indefinite" />
          </circle>
        )}
      </svg>
    </div>
  );
}
