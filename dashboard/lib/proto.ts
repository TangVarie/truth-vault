import { getDashboardData } from "@/lib/dashboard-data";

/** 原型对比共用:从真库取"对外可公开"的成果子集 + 一条确定性增长曲线。 */
export type ProtoProject = { id: string; impressions: number; notes: number; baokuan: number };
export type ProtoHit = { rank: number; project_id: string; interactions: number; impressions: number };
export type ProtoData = {
  impressions: number; notes: number; baokuan: number; cards: number; essence: number;
  projects: number; levers: number; audiences: number; topInteractions: number; hitRate: number;
  byProject: ProtoProject[]; hits: ProtoHit[]; growth: number[];
};

export async function getProtoData(): Promise<ProtoData> {
  const { o, projects, hits } = await getDashboardData();
  const hitRate = o.notes ? Math.round((o.baokuanReal / o.notes) * 1000) / 10 : 0;
  return {
    impressions: o.impressions, notes: o.notes, baokuan: o.baokuanReal, cards: o.cards, essence: o.essence,
    projects: o.projects, levers: o.levers, audiences: o.audiences, topInteractions: o.topInteractions, hitRate,
    byProject: projects.map((p) => ({ id: p.project_id, impressions: p.impressions, notes: p.notes, baokuan: p.baokuan })),
    hits: hits.slice(0, 6).map((h) => ({ rank: h.rank, project_id: h.project_id, interactions: h.interactions, impressions: h.impressions })),
    growth: growthSeries(40),
  };
}

/** 确定性 S 形上扬(0..1),各原型自绘曲线用,口径一致。 */
export function growthSeries(n = 40): number[] {
  const out: number[] = [];
  for (let i = 0; i < n; i++) { const t = i / (n - 1); out.push(Math.pow(t, 1.9) * 0.82 + t * 0.18); }
  return out;
}

/** 由 0..1 序列生成 SVG line/area path(viewBox 坐标)。 */
export function areaPath(series: number[], w: number, h: number, pad = 3): { line: string; area: string } {
  const n = series.length;
  const X = (i: number) => pad + (i / (n - 1)) * (w - pad * 2);
  const Y = (v: number) => h - pad - v * (h - pad * 2);
  const line = series.map((v, i) => `${i === 0 ? "M" : "L"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
  const area = `${line} L${X(n - 1).toFixed(1)},${(h - pad).toFixed(1)} L${X(0).toFixed(1)},${(h - pad).toFixed(1)} Z`;
  return { line, area };
}
