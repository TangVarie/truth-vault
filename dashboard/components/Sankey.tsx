/**
 * 真·桑基图(Sankey)—— 看板签名视觉。
 *
 * 4 列 6 节点,手工布局(数据量小没必要上 d3-sankey):
 *   飞书投放表 → ROC 数据中台 → { 智能分发引擎, AI 创作回流 } → { 三生六部, AI 内容工作台 }
 *
 * 河流(ribbon)用 cubic bezier 实心填充,粗细按 value 比例。河流上有流光脉冲沿 path 跑(activity = "在流"的活体感)。
 * 节点是粗矩形 bar(brutalist),不是发光圆圈。
 *
 * 颜色严格遵守编辑级纪律:只有一个点睛色 coral(`#E8765A`),其余靠浅色 ribbon 透明度区分。
 */
"use client";

type Node = { id: string; col: number; label: string; sub?: string; bar: number };
type Link = { from: string; to: string; value: number; accent?: boolean };

const W = 1100;
const H = 360;
const NODE_W = 14;
const COL_X = [80, 380, 680, 980]; // 4 列

/** ribbon 路径:从 (x1,y1) 到 (x2,y2) 一条 thickness=w 的弯曲带子(双 bezier 闭合)。 */
function ribbonPath(x1: number, y1: number, x2: number, y2: number, w: number) {
  const mid = (x1 + x2) / 2;
  const top1 = y1 - w / 2, top2 = y2 - w / 2;
  const bot1 = y1 + w / 2, bot2 = y2 + w / 2;
  return [
    `M ${x1} ${top1}`,
    `C ${mid} ${top1}, ${mid} ${top2}, ${x2} ${top2}`,
    `L ${x2} ${bot2}`,
    `C ${mid} ${bot2}, ${mid} ${bot1}, ${x1} ${bot1}`,
    "Z",
  ].join(" ");
}

/** 中线 path(供 animateMotion 跑流光) */
function midPath(x1: number, y1: number, x2: number, y2: number) {
  const mid = (x1 + x2) / 2;
  return `M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}`;
}

export default function Sankey({
  impressions,
  notes,
  baokuan,
  cards,
}: {
  impressions: number;
  notes: number;
  baokuan: number;
  cards: number;
}) {
  // 节点(bar 高度 = 视觉对齐,不是数据;数据靠 ribbon 粗细传达)
  const nodes: Node[] = [
    { id: "feishu", col: 0, label: "投放数据源", sub: "飞书全域", bar: 200 },
    { id: "roc",    col: 1, label: "ROC 数据中台", sub: `${notes.toLocaleString()} 内容资产`, bar: 240 },
    { id: "dist",   col: 2, label: "智能分发引擎", sub: `${baokuan} 验证级爆款`, bar: 140 },
    { id: "aw_in",  col: 2, label: "AI 创作回流",   sub: `${cards} 策略经验卡`, bar: 140 },
    { id: "ssll",   col: 3, label: "三生六部",     sub: "智能仿写引擎", bar: 140 },
    { id: "aw",     col: 3, label: "AI 内容工作台", sub: "autowriter",   bar: 140 },
  ];

  // 节点 y 中心
  const yOf: Record<string, number> = {
    feishu: H / 2,
    roc:    H / 2,
    dist:   120,
    aw_in:  240,
    ssll:   120,
    aw:     240,
  };

  const links: Link[] = [
    { from: "feishu", to: "roc",   value: 200, accent: true },
    { from: "roc",    to: "dist",  value: 90, accent: true  },
    { from: "roc",    to: "aw_in", value: 90  },
    { from: "dist",   to: "ssll",  value: 80, accent: true  },
    { from: "aw_in",  to: "aw",    value: 80  },
  ];

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full">
      <defs>
        <linearGradient id="sk-accent" x1="0" x2="1">
          <stop offset="0%"  stopColor="#E8765A" stopOpacity="0.85" />
          <stop offset="100%" stopColor="#E8765A" stopOpacity="0.35" />
        </linearGradient>
        <linearGradient id="sk-muted" x1="0" x2="1">
          <stop offset="0%"  stopColor="#3a4458" stopOpacity="0.7" />
          <stop offset="100%" stopColor="#3a4458" stopOpacity="0.25" />
        </linearGradient>
        <filter id="sk-glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="2" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* ribbons */}
      <g>
        {links.map((l, i) => {
          const fromN = nodes.find((n) => n.id === l.from)!;
          const toN = nodes.find((n) => n.id === l.to)!;
          const x1 = COL_X[fromN.col] + NODE_W;
          const x2 = COL_X[toN.col];
          const y1 = yOf[l.from];
          const y2 = yOf[l.to];
          const d = ribbonPath(x1, y1, x2, y2, l.value);
          const midD = midPath(x1, y1, x2, y2);
          return (
            <g key={i}>
              <path d={d} fill={l.accent ? "url(#sk-accent)" : "url(#sk-muted)"} />
              {/* 流光脉冲沿中线跑 */}
              <path id={`sk-mid-${i}`} d={midD} fill="none" stroke="none" />
              <circle r="3.2" fill="#fff" filter="url(#sk-glow)">
                <animateMotion dur={`${5 + i * 0.6}s`} begin={`${i * 0.7}s`} repeatCount="indefinite">
                  <mpath href={`#sk-mid-${i}`} />
                </animateMotion>
              </circle>
            </g>
          );
        })}
      </g>

      {/* nodes(粗矩形 bar)+ 标签 */}
      <g>
        {nodes.map((n) => {
          const x = COL_X[n.col];
          const y = yOf[n.id];
          const bar = n.bar;
          // 标签靠节点左/右排版(col 0/3 标外侧,col 1/2 标节点上方)
          const labelLeft = n.col === 3;
          const labelTop = n.col === 1 || n.col === 2;
          return (
            <g key={n.id}>
              <rect
                x={x}
                y={y - bar / 2}
                width={NODE_W}
                height={bar}
                rx="3"
                fill="#f3f4f6"
              />
              {labelTop ? (
                <>
                  <text
                    x={x + NODE_W / 2}
                    y={y - bar / 2 - 16}
                    textAnchor="middle"
                    fill="#fff"
                    style={{ fontSize: 14, fontWeight: 700 }}
                  >
                    {n.label}
                  </text>
                  {n.sub && (
                    <text
                      x={x + NODE_W / 2}
                      y={y - bar / 2 - 2}
                      textAnchor="middle"
                      fill="#94a3b8"
                      style={{ fontSize: 10 }}
                    >
                      {n.sub}
                    </text>
                  )}
                </>
              ) : labelLeft ? (
                <>
                  <text
                    x={x - 16}
                    y={y - 4}
                    textAnchor="end"
                    fill="#fff"
                    style={{ fontSize: 14, fontWeight: 700 }}
                  >
                    {n.label}
                  </text>
                  {n.sub && (
                    <text
                      x={x - 16}
                      y={y + 12}
                      textAnchor="end"
                      fill="#94a3b8"
                      style={{ fontSize: 10 }}
                    >
                      {n.sub}
                    </text>
                  )}
                </>
              ) : (
                <>
                  <text
                    x={x + NODE_W + 14}
                    y={y - 4}
                    fill="#fff"
                    style={{ fontSize: 14, fontWeight: 700 }}
                  >
                    {n.label}
                  </text>
                  {n.sub && (
                    <text
                      x={x + NODE_W + 14}
                      y={y + 12}
                      fill="#94a3b8"
                      style={{ fontSize: 10 }}
                    >
                      {n.sub}
                    </text>
                  )}
                </>
              )}
            </g>
          );
        })}
      </g>
    </svg>
  );
}
