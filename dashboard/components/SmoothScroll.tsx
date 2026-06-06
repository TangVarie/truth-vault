"use client";

import { ReactLenis } from "lenis/react";
import { useEffect, useState } from "react";

/**
 * Lenis 平滑滚动(惯性"加重感"是高级感的最大杠杆;研究:darkroomengineering/lenis)。
 * 只在编辑级落地页用,/console 保持原生滚动(密集看板要快速扫读)。
 * 尊重 prefers-reduced-motion:直接退回原生滚动,不加平滑。
 */
export default function SmoothScroll({ children }: { children: React.ReactNode }) {
  const [reduce, setReduce] = useState(false);
  useEffect(() => {
    setReduce(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false);
  }, []);
  if (reduce) return <>{children}</>;
  return (
    <ReactLenis root options={{ lerp: 0.1, smoothWheel: true, syncTouch: false }}>
      {children}
    </ReactLenis>
  );
}
