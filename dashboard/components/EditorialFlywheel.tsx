"use client";

import { NODE_LABEL } from "@/config/showcase";

/**
 * 编辑级飞轮(Bone & Ink 招牌母题):细墨线环 + 黄铜慢转虚线 + coral 流动脉冲 + 中心 hub 巨号。
 * 不是看板那种发光暗块,而是纸上的一张优雅图解(墨线 + 一个 coral 点睛 + mono 标签)。
 */
const SIZE = 600;
const C = SIZE / 2;
const R = 196;
const ORDER = ["feishu", "truth_vault", "channel1", "sanshengliubu", "autowriter", "channel2"];

function pos(i: number, n: number) {
  const a = (i / n) * Math.PI * 2 - Math.PI / 2;
  return { x: C + R * Math.cos(a), y: C + R * Math.sin(a) };
}

export default function EditorialFlywheel({ center, caption }: { center: string; caption: string }) {
  const n = ORDER.length;
  const pts = ORDER.map((_, i) => pos(i, n));
  const ring = `M ${C} ${C - R} A ${R} ${R} 0 1 1 ${C - 0.01} ${C - R}`;
  return (
    <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="mx-auto block h-auto w-full max-w-[540px]" style={{ overflow: "visible" }}>
      {/* 内部数据流(细墨弦) */}
      <g stroke="rgba(20,17,15,0.12)" strokeWidth="1">
        {pts.map((p, i) => {
          const q = pts[(i + 1) % n];
          return <line key={i} x1={p.x} y1={p.y} x2={q.x} y2={q.y} />;
        })}
      </g>

      {/* 飞轮环:细墨线 + 黄铜极慢转虚线(在转) */}
      <circle cx={C} cy={C} r={R} fill="none" stroke="rgba(20,17,15,0.22)" strokeWidth="1.25" />
      <circle
        cx={C}
        cy={C}
        r={R}
        fill="none"
        stroke="#B89B6A"
        strokeOpacity="0.55"
        strokeWidth="1"
        strokeDasharray="2 13"
        className="animate-spin-slow"
        style={{ transformBox: "fill-box", transformOrigin: "center" }}
      />

      {/* coral 流动脉冲沿环跑(在流) */}
      <path id="edRing" d={ring} fill="none" stroke="none" />
      {[0, 2.7, 5.4].map((d, i) => (
        <circle key={i} r="4.5" fill="#E8765A">
          <animateMotion dur="8s" begin={`${d}s`} repeatCount="indefinite">
            <mpath href="#edRing" />
          </animateMotion>
        </circle>
      ))}

      {/* 节点 + mono 标签 */}
      {ORDER.map((id, i) => {
        const p = pts[i];
        const cfg = NODE_LABEL[id] ?? { label: id };
        const active = id === "truth_vault";
        const right = p.x >= C - 1;
        return (
          <g key={id}>
            {active && <circle cx={p.x} cy={p.y} r="13" fill="none" stroke="#E8765A" strokeOpacity="0.4" />}
            <circle cx={p.x} cy={p.y} r={active ? 6.5 : 4.5} fill={active ? "#E8765A" : "#14110F"} />
            <text
              className="mn"
              x={right ? p.x + 15 : p.x - 15}
              y={p.y + 4}
              textAnchor={right ? "start" : "end"}
              fill="#3D3A34"
              style={{ fontSize: 12.5, letterSpacing: 0.3 }}
            >
              {cfg.label}
            </text>
          </g>
        );
      })}

      {/* 中心 hub:纸底 + 细墨圈 + Fraunces 巨号 */}
      <circle cx={C} cy={C} r="90" fill="#F3EEE6" stroke="rgba(20,17,15,0.16)" />
      <text className="fr" x={C} y={C - 2} textAnchor="middle" fill="#14110F" style={{ fontSize: 56, fontWeight: 500, letterSpacing: -1 }}>
        {center}
      </text>
      <text className="mn" x={C} y={C + 28} textAnchor="middle" fill="#8A7F6D" style={{ fontSize: 11, letterSpacing: 3 }}>
        {caption}
      </text>
    </svg>
  );
}
