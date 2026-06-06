"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

/**
 * 滚动揭示原语(v6 滚动叙事核心)。IntersectionObserver 驱动:元素滚进视口才淡入上移。
 *  - `mountOnView`:进视口前**不挂载** children(给"进场即一次性放完"的组件——GrowthCurve / Heatmap——
 *    用,这样它们的描线/错位动画**滚到才触发**;配 className 上的 min-h 预留高度,避免跳动)。
 *  - 尊重 prefers-reduced-motion:直接显示,不动。
 */
export default function Reveal({
  children,
  className = "",
  delay = 0,
  y = 28,
  once = true,
  mountOnView = false,
}: {
  children: ReactNode;
  className?: string;
  delay?: number;
  y?: number;
  once?: boolean;
  mountOnView?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduce || typeof IntersectionObserver === "undefined") {
      setShown(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) =>
        entries.forEach((e) => {
          if (e.isIntersecting) {
            setShown(true);
            if (once) io.disconnect();
          } else if (!once) {
            setShown(false);
          }
        }),
      { threshold: 0.15, rootMargin: "0px 0px -10% 0px" }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [once]);

  return (
    <div
      ref={ref}
      className={className}
      style={{
        opacity: shown ? 1 : 0,
        transform: shown ? "none" : `translateY(${y}px)`,
        transition: `opacity .8s cubic-bezier(.22,1,.36,1) ${delay}ms, transform .8s cubic-bezier(.22,1,.36,1) ${delay}ms`,
        willChange: "opacity, transform",
      }}
    >
      {mountOnView ? (shown ? children : null) : children}
    </div>
  );
}
