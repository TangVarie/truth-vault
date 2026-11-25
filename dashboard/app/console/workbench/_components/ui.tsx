import type { ReactNode } from "react";
import { comma } from "@/config/showcase";

/**
 * 工作台自己的小组件 (docs/35 第 3.2、5 节)。全是服务端组件：没有 "use client"，行数据不进任何客户端脚本。
 * 颜色和断点照 /console (app/console/page.tsx)。
 */

export const BG = "#0A0A0B";
export const PANEL = "#141416";
export const BORD = "rgba(255,255,255,0.08)";
export const MUTE = "#8A8F98";
export const CORAL = "#F2542D";
export const LIME = "#C6F24E";
export const LAV = "#BFB9E6";
export const SAGE = "#DDE6D6";
export const INKC = "#0E0E0E";
export const mono = "var(--font-geist-mono)";
export const sans = "var(--font-geist-sans)";

export const css = `
.wb{max-width:1280px;margin:0 auto;padding:0 20px 64px}
.wb-sec{background:${PANEL};border:1px solid ${BORD};border-radius:20px;padding:18px 20px;margin-top:16px}
.wb-blk{border-top:1px solid ${BORD};padding-top:14px;margin-top:14px}
.wb-blk:first-of-type{border-top:0;margin-top:6px}
.wb h2{font-size:22px;font-weight:800;letter-spacing:-0.02em}
.wb h3{font-size:16px;font-weight:800}
.wb h4{font-size:13.5px;font-weight:700;margin-top:12px}
.wb-sub{font-size:12.5px;color:#cfd3da;margin-top:4px;line-height:1.6}
.wb-mute{font-size:12px;color:${MUTE};margin-top:6px;line-height:1.6}
.wb-tw{overflow-x:auto;margin-top:10px;-webkit-overflow-scrolling:touch}
.wb table{border-collapse:collapse;font-size:12.5px;min-width:100%}
.wb th{font-weight:600;color:${MUTE};text-align:left;padding:6px 10px;border-bottom:1px solid ${BORD};white-space:nowrap}
.wb td{padding:6px 10px;border-bottom:1px solid rgba(255,255,255,0.04);vertical-align:top;white-space:nowrap}
.wb td.wrap{white-space:normal;min-width:160px}
.wb .num{font-family:${mono};text-align:right}
.wb .code{font-family:${mono};font-size:12px;color:#e8e6e3}
.wb-empty{font-size:12.5px;color:${MUTE};border:1px dashed ${BORD};border-radius:12px;padding:10px 12px;margin-top:10px}
.wb-tag{display:inline-block;border:1px solid rgba(255,255,255,0.18);border-radius:999px;padding:1px 8px;font-size:11.5px;margin:0 4px 2px 0}
.wb-toc{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.wb-toc a{border:1.5px solid rgba(255,255,255,0.18);border-radius:999px;padding:4px 12px;font-size:12.5px;color:#fff;text-decoration:none}
.wb-curves{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;margin-top:10px}
.wb-curve{border:1px solid ${BORD};border-radius:14px;padding:10px 12px}
.wb-anchor{scroll-margin-top:74px}
@media(max-width:560px){.wb{padding:0 16px 48px}.wb-sec{padding:14px 14px}.wb h2{font-size:19px}}
`;

export function fmt(n: number | null | undefined): string {
  return n == null ? "缺" : comma(n);
}

export function pct(a: number, b: number): string {
  return b > 0 ? `${Math.round((a / b) * 100)}%` : "—";
}

export function Block({ id, title, lead, children }: { id?: string; title: string; lead: ReactNode; children: ReactNode }) {
  return (
    <section id={id} className="wb-blk wb-anchor">
      <h3>{title}</h3>
      <p className="wb-sub">{lead}</p>
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="wb-empty">{children}</div>;
}

export function Table({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <div className="wb-tw">
      <table>
        <thead>
          <tr>{head.map((h) => <th key={h}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** 投流前后的评论数：基线 / 当天 / 第 1、3、7 天。缺的点断开、不画，不补 0。 */
export function BoostChart({ points }: { points: { label: string; at: number; v: number | null }[] }) {
  const W = 260, H = 92, PL = 8, PR = 8, PT = 10, PB = 26;
  const known = points.filter((p) => p.v != null).map((p) => p.v as number);
  const lo = known.length ? Math.min(...known) : 0;
  const hi = known.length ? Math.max(...known) : 1;
  const span = hi - lo || 1;
  const minAt = Math.min(...points.map((p) => p.at));
  const maxAt = Math.max(...points.map((p) => p.at));
  const x = (at: number) => PL + ((at - minAt) / (maxAt - minAt || 1)) * (W - PL - PR);
  const y = (v: number) => PT + (1 - (v - lo) / span) * (H - PT - PB);
  const segs: string[] = [];
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i];
    if (a.v != null && b.v != null) segs.push(`M${x(a.at).toFixed(1)},${y(a.v).toFixed(1)}L${x(b.at).toFixed(1)},${y(b.v).toFixed(1)}`);
  }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="投流前后的评论数">
      <line x1={PL} x2={W - PR} y1={H - PB} y2={H - PB} stroke={BORD} />
      {segs.length > 0 && <path d={segs.join("")} fill="none" stroke={LIME} strokeWidth={2} />}
      {points.map((p) => (
        <g key={p.label}>
          {p.v != null ? (
            <>
              <circle cx={x(p.at)} cy={y(p.v)} r={3} fill={LIME} />
              <text x={x(p.at)} y={y(p.v) - 5} fontSize={9} fill="#e8e6e3" textAnchor="middle" fontFamily={mono}>{comma(p.v)}</text>
            </>
          ) : (
            <text x={x(p.at)} y={H - PB - 4} fontSize={9} fill={MUTE} textAnchor="middle">缺</text>
          )}
          <text x={x(p.at)} y={H - 8} fontSize={9} fill={MUTE} textAnchor="middle">{p.label}</text>
        </g>
      ))}
    </svg>
  );
}
