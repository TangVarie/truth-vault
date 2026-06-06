"use client";

import { NODES, EDGES } from "@/config/flywheel";

/**
 * 飞轮活体图(docs/24 §A · 装逼核心):旋转环 + 节点 + 沿环流动的脉冲 + 中心大数。
 * 节点标签走下方 legend(避免 SVG 内中文挤叠);SVG 内只放发光节点 + 脉冲 + 中心 hub。
 * 节点/边来自 config/flywheel.ts(config 驱动:去中心化分发已预放 planned)。
 */
const SIZE = 360;
const C = SIZE / 2;
const R = 132; // 节点环半径

function nodePos(i: number, n: number) {
  const a = (i / n) * Math.PI * 2 - Math.PI / 2; // 从正上方顺时针
  return { x: C + R * Math.cos(a), y: C + R * Math.sin(a) };
}

export default function Flywheel({
  center,
  caption,
}: {
  center: number | string;
  caption: string;
}) {
  const n = NODES.length;
  const xy = NODES.map((_, i) => nodePos(i, n));
  const idx: Record<string, number> = {};
  NODES.forEach((node, i) => (idx[node.id] = i));

  // 给脉冲 animateMotion 用的整圆路径(从正上方起,顺时针一圈)
  const ringPath = `M ${C} ${C - R} A ${R} ${R} 0 1 1 ${C - 0.01} ${C - R}`;

  return (
    <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="mx-auto h-auto w-full max-w-[360px]">
      <defs>
        <radialGradient id="fwHub" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#1b4fd1" stopOpacity="0.55" />
          <stop offset="68%" stopColor="#0b1840" stopOpacity="0.35" />
          <stop offset="100%" stopColor="#070b18" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="fwRing" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#5eead4" />
          <stop offset="50%" stopColor="#1b4fd1" />
          <stop offset="100%" stopColor="#cc2128" />
        </linearGradient>
        <filter id="fwGlow" x="-60%" y="-60%" width="220%" height="220%">
          <feGaussianBlur stdDeviation="3" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* 节点间连线(飞轮内部数据流) */}
      <g stroke="#3b82f6" strokeOpacity="0.16" strokeWidth="1">
        {EDGES.map((e, i) => {
          const a = xy[idx[e.from]];
          const b = xy[idx[e.to]];
          if (!a || !b) return null;
          return (
            <line
              key={i}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              strokeDasharray={e.planned ? "2 6" : undefined}
            />
          );
        })}
      </g>

      {/* 旋转外环(飞轮本体):旋转虚线圆 → 虚线沿环跑 = 在转 */}
      <circle
        cx={C}
        cy={C}
        r={R}
        fill="none"
        stroke="url(#fwRing)"
        strokeOpacity="0.55"
        strokeWidth="2"
        strokeDasharray="3 9"
        strokeLinecap="round"
        className="animate-spin-slow"
        style={{ transformBox: "fill-box", transformOrigin: "center" }}
      />
      <circle
        cx={C}
        cy={C}
        r={R + 16}
        fill="none"
        stroke="#1b4fd1"
        strokeOpacity="0.18"
        strokeWidth="1"
        strokeDasharray="1 14"
        className="animate-spin-rev"
        style={{ transformBox: "fill-box", transformOrigin: "center" }}
      />

      {/* 流动脉冲:沿环跑(呼应"在转、在流") */}
      <path id="fwRingPath" d={ringPath} fill="none" stroke="none" />
      {[0, 2.34, 4.66].map((delay, i) => (
        <circle key={i} r="3.6" fill="#5eead4" filter="url(#fwGlow)">
          <animateMotion dur="7s" begin={`${delay}s`} repeatCount="indefinite">
            <mpath href="#fwRingPath" />
          </animateMotion>
        </circle>
      ))}

      {/* 中心 hub + 大数 */}
      <circle cx={C} cy={C} r="80" fill="url(#fwHub)" />
      <circle
        cx={C}
        cy={C}
        r="56"
        fill="#0b1226"
        stroke="#1b4fd1"
        strokeOpacity="0.45"
        strokeWidth="1"
      />
      <text
        x={C}
        y={C - 2}
        textAnchor="middle"
        fill="#ffffff"
        style={{ fontSize: 30, fontWeight: 800, letterSpacing: -0.5 }}
      >
        {center}
      </text>
      <text
        x={C}
        y={C + 20}
        textAnchor="middle"
        fill="#94a3b8"
        style={{ fontSize: 10, letterSpacing: 3 }}
      >
        {caption}
      </text>

      {/* 节点(发光小球;标签走下方 legend) */}
      {NODES.map((node, i) => {
        const p = xy[i];
        const planned = node.status === "planned";
        return (
          <g key={node.id}>
            {!planned && <circle cx={p.x} cy={p.y} r="9" fill="#5eead4" opacity="0.16" />}
            <circle
              cx={p.x}
              cy={p.y}
              r="5"
              fill={planned ? "#475569" : "#5eead4"}
              filter={planned ? undefined : "url(#fwGlow)"}
            >
              {!planned && (
                <animate
                  attributeName="opacity"
                  values="0.55;1;0.55"
                  dur="3s"
                  begin={`${i * 0.4}s`}
                  repeatCount="indefinite"
                />
              )}
            </circle>
          </g>
        );
      })}
    </svg>
  );
}
