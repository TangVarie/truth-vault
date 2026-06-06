"use client";

/**
 * 策略 × 受众 共振矩阵热力图 —— 编辑级深度视图。
 *
 * 横轴 = audiences,纵轴 = levers,每格颜色深浅 = 该组合下的真实笔记数。
 * 色阶:深底 → coral(高密度 = 命中"共振区")。空格 = 深 ink。
 *
 * 进场:整格 .heat-cell 错位淡入(stagger);最高 3 格自带 dot 高亮。
 */

type Cell = { lever: string; audience: string; n: number };

export default function Heatmap({
  cells,
  levers,
  audiences,
}: {
  cells: Cell[];
  levers: string[]; // 行序
  audiences: string[]; // 列序
}) {
  if (cells.length === 0) return <div className="text-sm text-slate-500">—</div>;

  // 索引
  const idx = new Map<string, number>();
  cells.forEach((c) => idx.set(`${c.lever}|${c.audience}`, c.n));

  const max = Math.max(1, ...cells.map((c) => c.n));

  // 高亮 top 3 单元格
  const top3 = [...cells].sort((a, b) => b.n - a.n).slice(0, 3);
  const topSet = new Set(top3.map((c) => `${c.lever}|${c.audience}`));

  const cellSize = 38; // px
  const gap = 4;

  return (
    <div className="overflow-x-auto">
      <div style={{ minWidth: audiences.length * (cellSize + gap) + 140 }}>
        {/* 顶部列标签 */}
        <div className="flex" style={{ paddingLeft: 120 }}>
          {audiences.map((a) => (
            <div
              key={a}
              className="mini truncate text-slate-500"
              style={{ width: cellSize + gap, textAlign: "center" }}
              title={a}
            >
              {a}
            </div>
          ))}
        </div>
        {/* 行 */}
        {levers.map((lev, ri) => (
          <div key={lev} className="flex items-center" style={{ marginTop: gap }}>
            <div
              className="mini truncate pr-3 text-right text-slate-300"
              style={{ width: 120 }}
              title={lev}
            >
              {lev}
            </div>
            {audiences.map((aud, ci) => {
              const key = `${lev}|${aud}`;
              const n = idx.get(key) ?? 0;
              const ratio = n / max; // 0..1
              // 颜色:从透明(无)→ coral
              const isTop = topSet.has(key);
              const bg = n === 0
                ? "rgba(255,255,255,0.03)"
                : `rgba(232,118,90,${0.12 + ratio * 0.78})`;
              const ring = isTop ? "0 0 0 1px rgba(255,255,255,0.55)" : "none";
              return (
                <div
                  key={aud}
                  className="heat-cell relative"
                  style={{
                    width: cellSize,
                    height: cellSize,
                    marginLeft: ci === 0 ? 0 : gap,
                    borderRadius: 8,
                    background: bg,
                    boxShadow: ring,
                    animationDelay: `${(ri * audiences.length + ci) * 8}ms`,
                  }}
                  title={`${lev} × ${aud}: ${n}`}
                >
                  {n > 0 && (
                    <div
                      className="absolute inset-0 flex items-center justify-center text-[10px] font-bold"
                      style={{ color: ratio > 0.5 ? "#0a0a0f" : "rgba(255,255,255,0.85)" }}
                    >
                      {n}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ))}

        {/* 色阶 legend */}
        <div className="mt-5 flex items-center gap-3">
          <span className="mini text-slate-500">低共振</span>
          <div className="h-2 w-40 rounded-full" style={{
            background: "linear-gradient(90deg, rgba(232,118,90,0.12), rgba(232,118,90,0.9))"
          }} />
          <span className="mini text-slate-500">高共振</span>
          <span className="mini ml-auto text-slate-600">最高 {max} 篇</span>
        </div>
      </div>
    </div>
  );
}
