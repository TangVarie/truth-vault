"use client";

import { useEffect, useRef, useState } from "react";

/**
 * 数字滚动计数(easeOutCubic),进场从 0 涨到目标值。让大数"涨上来"= 动效。
 * format 可把数值实时格式化(如紧凑万/亿)。
 */
export default function CountUp({
  value,
  duration = 1500,
  format,
}: {
  value: number;
  duration?: number;
  format?: (n: number) => string;
}) {
  const [n, setN] = useState(0);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const start = performance.now();
    const step = (t: number) => {
      const p = Math.min(1, (t - start) / duration);
      const eased = 1 - Math.pow(1 - p, 3);
      setN(value * eased);
      if (p < 1) requestAnimationFrame(step);
      else setN(value);
    };
    const id = requestAnimationFrame(step);
    return () => cancelAnimationFrame(id);
  }, [value, duration]);

  const fmt = format ?? ((x: number) => Math.round(x).toLocaleString("en-US"));
  return <span className="tabular-nums">{fmt(n)}</span>;
}
