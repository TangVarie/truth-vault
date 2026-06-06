"use client";

import { useEffect, useRef, useState } from "react";
import { cnNum, comma } from "@/config/showcase";

/**
 * 数字滚动计数(easeOutCubic)。
 * v6:改为**滚进视口才开始**(IntersectionObserver)—— 滚到哪、数字才在哪涨,
 * 不再进页一次性放完(修「动效是死的」)。format 用字符串(Server→Client 不能传函数);
 * 尊重 prefers-reduced-motion(直接落终值)。
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
  const ref = useRef<HTMLSpanElement>(null);
  const started = useRef(false);

  useEffect(() => {
    const el = ref.current;
    const run = () => {
      if (started.current) return;
      started.current = true;
      const start = performance.now();
      const tick = (t: number) => {
        const p = Math.min(1, (t - start) / duration);
        const eased = 1 - Math.pow(1 - p, 3);
        setN(value * eased);
        if (p < 1) requestAnimationFrame(tick);
        else setN(value);
      };
      requestAnimationFrame(tick);
    };

    const reduce =
      typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      started.current = true;
      setN(value);
      return;
    }
    if (!el || typeof IntersectionObserver === "undefined") {
      run();
      return;
    }
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => { if (e.isIntersecting) { run(); io.disconnect(); } }),
      { threshold: 0.25 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [value, duration]);

  const fmt = format === "cn" ? cnNum : comma;
  return <span ref={ref} className="tabular-nums">{fmt(n)}</span>;
}
