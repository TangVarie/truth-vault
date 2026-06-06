"use client";

/**
 * 进场生长的条形图(纯 CSS .bar-grow,从底部长起 + stagger)。
 * 高亮 accentIndex 那根。值用对外口径,标签短。
 */
export default function BarChart({
  data,
  accentIndex,
  height = 160,
}: {
  data: { label: string; value: number }[];
  accentIndex?: number;
  height?: number;
}) {
  const max = Math.max(...data.map((d) => d.value), 1);
  return (
    <div className="flex items-end gap-1.5" style={{ height }}>
      {data.map((d, i) => {
        const accent = i === accentIndex;
        return (
          <div key={i} className="group flex flex-1 flex-col items-center justify-end">
            <div
              className="w-full rounded-t-md bar-grow"
              style={{
                height: `${Math.max(2, (d.value / max) * 100)}%`,
                background: accent
                  ? "linear-gradient(180deg,#5eead4,#1b4fd1)"
                  : "linear-gradient(180deg,rgba(94,234,212,0.45),rgba(27,79,209,0.18))",
                boxShadow: accent ? "0 0 16px rgba(94,234,212,0.45)" : undefined,
                animationDelay: `${i * 55}ms`,
              }}
              title={`${d.label}: ${d.value.toLocaleString("en-US")}`}
            />
            <div className="mt-1.5 truncate text-[9px] text-slate-500">{d.label}</div>
          </div>
        );
      })}
    </div>
  );
}
