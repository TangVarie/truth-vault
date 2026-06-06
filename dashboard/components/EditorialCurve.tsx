"use client";

import { useEffect, useRef, useState } from "react";
import { cumulativeSeries } from "@/config/showcase";

/**
 * 编辑级复利曲线(Bone & Ink):墨线描绘 + 极淡 coral 面积 + 黄铜末点。
 * 进场描线(strokeDashoffset)。配 Reveal mountOnView 使用 = 滚到才描。
 */
export default function EditorialCurve({ total }: { total: number }) {
  const W = 1100;
  const H = 300;
  const padT = 16;
  const padB = 22;
  const series = cumulativeSeries(total, 30);
  const max = series[series.length - 1] || 1;
  const step = W / (series.length - 1);
  const points = series.map((v, i) => [i * step, padT + (1 - v / max) * (H - padT - padB)] as [number, number]);
  const line = points.reduce((acc, [x, y], i) => {
    if (i === 0) return `M ${x} ${y}`;
    const [px, py] = points[i - 1];
    const cx = (px + x) / 2;
    return acc + ` C ${cx} ${py}, ${cx} ${y}, ${x} ${y}`;
  }, "");
  const area = line + ` L ${W} ${H - padB} L 0 ${H - padB} Z`;

  const [len, setLen] = useState<number | null>(null);
  const ref = useRef<SVGPathElement>(null);
  useEffect(() => {
    if (ref.current) setLen(ref.current.getTotalLength());
  }, []);

  const last = points[points.length - 1];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full" style={{ overflow: "visible" }}>
      <defs>
        <linearGradient id="ec-area" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#E8765A" stopOpacity="0.16" />
          <stop offset="100%" stopColor="#E8765A" stopOpacity="0" />
        </linearGradient>
      </defs>
      {[0.25, 0.5, 0.75].map((p, i) => (
        <line key={i} x1={0} x2={W} y1={padT + (H - padT - padB) * p} y2={padT + (H - padT - padB) * p} stroke="rgba(20,17,15,0.07)" strokeWidth={1} />
      ))}
      <path d={area} fill="url(#ec-area)" />
      <path
        ref={ref}
        d={line}
        fill="none"
        stroke="#14110F"
        strokeWidth={2}
        strokeLinecap="round"
        style={{ strokeDasharray: len ?? undefined, strokeDashoffset: len ?? undefined }}
        className={len ? "ed-draw" : undefined}
      />
      <circle cx={last[0]} cy={last[1]} r="5" fill="#E8765A">
        <animate attributeName="r" values="5;7.5;5" dur="2.4s" repeatCount="indefinite" />
      </circle>
    </svg>
  );
}
