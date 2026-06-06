"use client";

import { useEffect, useRef, useState } from "react";
import { cnNum, comma } from "@/config/showcase";

/**
 * 数字滚动计数(easeOutCubic),进场从 0 涨到目标值。
 * format 是字符串而不是函数 —— 因为 Server Components 不能往 Client Components 传函数;
 * 用 "cn"(中文紧凑万/亿) 或 "comma"(千分位),在 client 端内部决定怎么格式化。
 */
export default function CountUp({
  value,
  duration = 1500,
  format = "comma",
}: {
  value: number;
  duration?: number;
  format?: "cn" | "comma";
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

  const fmt = format === "cn" ? cnNum : comma;
  return <span className="tabular-nums">{fmt(n)}</span>;
}
