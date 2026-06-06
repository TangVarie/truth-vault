"use client";

import { useEffect, useRef, useState } from "react";
import { cnNum, cumulativeSeries } from "@/config/showcase";

/**
 * 复利增长曲线 —— SVG path 描线 + 面积填充。
 *
 * 进场:0.0s 立线条 strokeDasharray 描线 + 面积渐入 + 当前点跑到末尾。
 * 上方标数字 count-up 涨到 total。x 轴标记 4 个时间点(起 / Q1 / Q2 / 今)。
 */
export default function GrowthCurve({ total }: { total: number }) {
  // 静态 viewBox(响应式宽高保持)
  const W = 1100;
  const H = 220;
  const padL = 0, padR = 0, padT = 12, padB = 18;

  const series = cumulativeSeries(total, 28);
  const max = series[series.length - 1] || 1;
  const step = (W - padL - padR) / (series.length - 1);

  const points = series.map((v, i) => {
    const x = padL + i * step;
    const y = padT + (1 - v / max) * (H - padT - padB);
    return [x, y] as [number, number];
  });

  // 平滑 path(cardinal-like:每段加中点控制点)
  const linePath = points.reduce((acc, [x, y], i) => {
    if (i === 0) return `M ${x} ${y}`;
    const [px, py] = points[i - 1];
    const cx = (px + x) / 2;
    return acc + ` C ${cx} ${py}, ${cx} ${y}, ${x} ${y}`;
  }, "");
  const areaPath = linePath + ` L ${padL + (series.length - 1) * step} ${H - padB} L ${padL} ${H - padB} Z`;

  // 描线长度动效
  const [len, setLen] = useState<number | null>(null);
  const pathRef = useRef<SVGPathElement>(null);
  useEffect(() => {
    if (pathRef.current) {
      const l = pathRef.current.getTotalLength();
      setLen(l);
    }
  }, []);

  // count-up
  const [shown, setShown] = useState(0);
  useEffect(() => {
    const start = performance.now();
    const dur = 2200;
    const step = (t: number) => {
      const p = Math.min(1, (t - start) / dur);
      const eased = 1 - Math.pow(1 - p, 3);
      setShown(total * eased);
      if (p < 1) requestAnimationFrame(step);
      else setShown(total);
    };
    const id = requestAnimationFrame(step);
    return () => cancelAnimationFrame(id);
  }, [total]);

  return (
    <div>
      <div className="mb-1 flex items-end justify-between">
        <div>
          <span className="tag text-slate-500">复利累计 · CUMULATIVE GROWTH</span>
          <div className="huge text-coral arrow-up" style={{ fontSize: "clamp(56px, 9vw, 110px)" }}>
            {cnNum(shown)}
          </div>
        </div>
        <div className="mini text-slate-500">— · — · — · 今</div>
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full">
        <defs>
          <linearGradient id="gc-area" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#E8765A" stopOpacity="0.55" />
            <stop offset="100%" stopColor="#E8765A" stopOpacity="0.0" />
          </linearGradient>
          <filter id="gc-glow" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="3" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* 横向 hairline 网格(4 条) */}
        {[0.2, 0.4, 0.6, 0.8].map((p, i) => (
          <line
            key={i}
            x1={0} x2={W}
            y1={padT + (H - padT - padB) * p}
            y2={padT + (H - padT - padB) * p}
            stroke="rgba(255,255,255,0.05)"
            strokeWidth={1}
          />
        ))}

        {/* 面积 */}
        <path d={areaPath} fill="url(#gc-area)" style={{ opacity: 0.95 }}>
          <animate attributeName="opacity" from="0" to="0.95" dur="1.2s" fill="freeze" />
        </path>

        {/* 线 */}
        <path
          ref={pathRef}
          d={linePath}
          fill="none"
          stroke="#E8765A"
          strokeWidth={2.5}
          strokeLinecap="round"
          style={{
            strokeDasharray: len ?? undefined,
            strokeDashoffset: len ?? undefined,
            animation: len ? `dash 1.8s cubic-bezier(.22,1,.36,1) forwards` : undefined,
          }}
          filter="url(#gc-glow)"
        />

        {/* 末端点 + 脉冲 */}
        <circle
          cx={points[points.length - 1][0]}
          cy={points[points.length - 1][1]}
          r={5}
          fill="#fff"
          filter="url(#gc-glow)"
        >
          <animate attributeName="r" values="5;7;5" dur="2.2s" repeatCount="indefinite" />
        </circle>

        <style>{`@keyframes dash { to { stroke-dashoffset: 0; } }`}</style>
      </svg>
    </div>
  );
}
