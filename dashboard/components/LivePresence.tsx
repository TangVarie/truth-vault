"use client";

import { useEffect, useState } from "react";
import type { LiveSignal } from "@/lib/metrics/types";

/**
 * 实时"在线"卡(docs/24 §5.5 留好接口)。每 5s 轮询 /api/live/presence。
 * 现在后端是 stub(source:"stub")→ 显示"规划中";去中心化上线后后端换真数据,本组件不动。
 */
export default function LivePresence() {
  const [signals, setSignals] = useState<LiveSignal[] | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await fetch("/api/live/presence", { cache: "no-store" });
        const j = await r.json();
        if (alive) setSignals(j.signals ?? []);
      } catch {
        /* 实时卡取数失败不影响其它面板 */
      }
    };
    tick();
    const t = setInterval(tick, 5000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  return (
    <div className="flex flex-wrap gap-3">
      {(signals ?? [{ id: "live.editors", label: "在线改稿人数", online: 0, source: "stub" }]).map(
        (s) => {
          const planned = s.source === "stub";
          return (
            <div
              key={s.id}
              className="rounded-2xl bg-flywheel-card border border-white/5 px-5 py-4"
            >
              <div className="flex items-center gap-2 text-sm text-slate-400">
                <span
                  className={`inline-block h-2 w-2 rounded-full ${
                    planned ? "bg-slate-600" : "bg-flywheel-accent animate-pulse"
                  }`}
                />
                {s.label}
              </div>
              <div className="mt-1 text-2xl font-semibold tabular-nums">
                {planned ? <span className="text-slate-500 text-base">规划中</span> : s.online}
              </div>
            </div>
          );
        }
      )}
    </div>
  );
}
