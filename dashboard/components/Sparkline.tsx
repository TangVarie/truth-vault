/**
 * 轻量 sparkline(座舱卡片纹理 · Home Assistant 风)。无时序数据时按 seed 生成一条
 * 平滑、温和上扬的确定性曲线 —— 纯视觉纹理(趋势整体向上),非精确读数。纯 SVG,可服务端渲染。
 */
export default function Sparkline({
  color = "#E8765A",
  seed = 1,
  up = true,
  className = "h-9 w-full",
}: {
  color?: string;
  seed?: number;
  up?: boolean;
  className?: string;
}) {
  const W = 120;
  const H = 36;
  const n = 18;
  const pts: [number, number][] = Array.from({ length: n }, (_, i) => {
    const t = i / (n - 1);
    const noise = Math.sin(i * 1.7 + seed * 3) * 0.16 + Math.sin(i * 0.6 + seed * 1.3) * 0.1;
    const trend = up ? t * 0.62 : 0.42;
    const v = Math.min(1, Math.max(0, 0.2 + trend + noise * 0.5));
    return [t * W, H - v * (H - 6) - 3];
  });
  const line = pts.reduce((acc, [x, y], i) => {
    if (i === 0) return `M ${x} ${y}`;
    const [px, py] = pts[i - 1];
    const cx = (px + x) / 2;
    return acc + ` C ${cx} ${py}, ${cx} ${y}, ${x} ${y}`;
  }, "");
  const area = line + ` L ${W} ${H} L 0 ${H} Z`;
  const gid = `sp-${seed}-${up ? 1 : 0}`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className={className}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.32" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gid})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
