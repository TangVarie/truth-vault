"use client";

import { useEffect, useRef, useState } from "react";
import { useInView } from "framer-motion";
import { cnNum, comma } from "@/config/showcase";

/**
 * 数字滚动计数 —— **滚到视口才开始涨**(useInView),不是 mount 全放。
 * 这是"动效活起来"的核心:每个数字在被滚到时才从 0 涨上来。
 * format: "cn"(中文紧凑万/亿) | "comma"(千分位)。
 */
export default function CountUp({
  value,
  duration = 1600,
  format = "comma",
}: {
  value: number;
  duration?: number;
  format?: "cn" | "comma";
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "0px 0px -12% 0px" });
  const [n, setN] = useState(0);
  const started = useRef(false);

  useEffect(() => {
    if (!inView || started.current) return;
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
  }, [inView, value, duration]);

  const fmt = format === "cn" ? cnNum : comma;
  return <span ref={ref} className="tabular-nums">{fmt(n)}</span>;
}
