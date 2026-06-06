"use client";

// v4 编辑级 palette:coral 为主,其余取自 brutalist 色板(沉静、不抢戏)
const PALETTE = [
  "#E8765A", "#A6A2D8", "#C8D4B8", "#9A9750", "#EFE9DC", "#3a4458",
  "#C9523A", "#7a7a96", "#a8b598", "#cbb56a", "#d6cdb8", "#5a677d",
];

/**
 * 多段环形图(SVG dasharray 定位 + .donut-in 进场)。中心放总量/标题,右侧图例。
 */
export default function Donut({
  data,
  centerTop,
  centerSub,
}: {
  data: { label: string; value: number }[];
  centerTop?: string;
  centerSub?: string;
}) {
  const total = data.reduce((s, d) => s + d.value, 0) || 1;
  const R = 60;
  const C = 2 * Math.PI * R;
  let acc = 0;
  const slices = data.map((d, i) => {
    const frac = d.value / total;
    const seg = {
      color: PALETTE[i % PALETTE.length],
      dash: frac * C,
      offset: -acc * C,
      label: d.label,
      pct: Math.round(frac * 100),
    };
    acc += frac;
    return seg;
  });

  return (
    <div className="flex items-center gap-5">
      <svg viewBox="0 0 160 160" className="donut-in h-36 w-36 shrink-0">
        <g transform="rotate(-90 80 80)">
          {slices.map((s, i) => (
            <circle
              key={i}
              cx="80"
              cy="80"
              r={R}
              fill="none"
              stroke={s.color}
              strokeWidth="16"
              strokeDasharray={`${s.dash} ${C - s.dash}`}
              strokeDashoffset={s.offset}
            />
          ))}
        </g>
        {centerTop && (
          <text x="80" y="76" textAnchor="middle" fill="#fff" style={{ fontSize: 22, fontWeight: 800 }}>
            {centerTop}
          </text>
        )}
        {centerSub && (
          <text x="80" y="94" textAnchor="middle" fill="#94a3b8" style={{ fontSize: 9, letterSpacing: 1 }}>
            {centerSub}
          </text>
        )}
      </svg>
      <div className="grid flex-1 grid-cols-1 gap-1.5 text-xs sm:grid-cols-2">
        {data.slice(0, 8).map((d, i) => (
          <div key={i} className="flex items-center gap-2 text-slate-300">
            <span className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: PALETTE[i % PALETTE.length] }} />
            <span className="truncate">{d.label}</span>
            <span className="ml-auto tabular-nums text-slate-500">{Math.round((d.value / total) * 100)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}
