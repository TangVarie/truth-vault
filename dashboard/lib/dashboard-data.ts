import { getSupabase } from "@/lib/supabase";
import { AMPLIFY, type Overview } from "@/config/showcase";
import type { TopHit } from "@/components/Leaderboard";

/**
 * 看板唯一数据源(docs/24 §3):服务端只读 public 安全聚合视图(只吐大数/类别+rate,不吐明细)。
 * `/`(滚动叙事站)与 `/console`(座舱)复用同一份真数据。
 * v4:加入「深度挖掘」视图(情绪杠杆/效价×强度/人性原型/意图/tier 漏斗)。
 */

export type Lever = { lever: string; n: number };
export type Project = { project_id: string; notes: number; baokuan: number; essence: number; impressions: number };
export type Matrix = { lever: string; audience: string; n: number };

export type LeverPerf = { lever: string; n: number; hits: number; hit_rate: number; avg_inter: number };
export type ValenceCell = { valence: string; intensity: string; n: number; hits: number; hit_rate: number; avg_inter: number };
export type ArchetypePerf = { archetype: string; n: number; hits: number; hit_rate: number; avg_inter: number };
export type IntentPerf = { intent: string; n: number; hits: number; hit_rate: number; read_rate: number; inter_rate: number };
export type TierFunnel = { tier: string; n: number; avg_imp: number; read_rate: number; inter_rate: number; avg_inter: number; max_inter: number };
export type ProjectPerf = { project_id: string; category: string; notes: number; hits: number; hit_rate: number; avg_imp: number; total_imp: number; essence: number };
export type ProjectTier = { project_id: string; tier: string; n: number };
export type AudiencePerf = { audience: string; n: number; hits: number; hit_rate: number; avg_inter: number };
export type FormatPerf = { fmt: string; n: number; hits: number; hit_rate: number; avg_inter: number };
export type ReachConcentration = { total_notes: number; total_imp: number; top1_share: number; top5_share: number; top10_share: number; hit_reach_share: number; hit_note_pct: number };
export type SystemPulse = {
  notes_total: number; last_update: string | null; last_ingest: string | null;
  feishu_n: number; annotated_n: number; annotated_last: string | null;
  ssll_n: number; ssll_last: string | null; aw_n: number; aw_last: string | null;
  accounts_n: number; snaps_n: number; snaps_last: string | null;
  audit_n: number; audit_last: string | null; projects_n: number;
  pipeline_runs_n: number; server_now: string | null;
};

export type DashboardData = {
  o: Overview;
  levers: Lever[];
  projects: Project[];
  matrix: Matrix[];
  hits: TopHit[];
  leverPerf: LeverPerf[];
  valence: ValenceCell[];
  archetypes: ArchetypePerf[];
  intent: IntentPerf[];
  funnel: TierFunnel[];
  projectPerf: ProjectPerf[];
  projectTier: ProjectTier[];
  audience: AudiencePerf[];
  formats: FormatPerf[];
  reach: ReachConcentration | null;
  pulse: SystemPulse | null;
};

const EMPTY: Overview = {
  projects: 0, notes: 0, baokuanReal: 0, cards: 0, librarian: 0, essence: 0,
  impressions: 0, reads: 0, interactions: 0, topInteractions: 0, levers: 0, audiences: 0, ok: false,
};
const EMPTY_DATA: DashboardData = {
  o: EMPTY, levers: [], projects: [], matrix: [], hits: [],
  leverPerf: [], valence: [], archetypes: [], intent: [], funnel: [], projectPerf: [], projectTier: [],
  audience: [], formats: [], reach: null, pulse: null,
};

const num = (x: unknown) => (x == null ? 0 : Number(x));

export async function getDashboardData(): Promise<DashboardData> {
  const sb = getSupabase();
  if (!sb) return EMPTY_DATA;
  try {
    const [ov, lv, pj, mx, th, lp, vm, ar, it, tf, pp, pt, aud, fp, rc, ps] = await Promise.all([
      sb.from("v_dash_overview").select("*").single(),
      sb.from("v_dash_levers").select("*").limit(12),
      sb.from("v_dash_projects").select("*"),
      sb.from("v_dash_matrix").select("*"),
      sb.from("v_dash_top_hits").select("*"),
      sb.from("v_dash_lever_perf").select("*"),
      sb.from("v_dash_valence_matrix").select("*"),
      sb.from("v_dash_archetype_perf").select("*"),
      sb.from("v_dash_intent_perf").select("*"),
      sb.from("v_dash_tier_funnel").select("*"),
      sb.from("v_dash_project_perf").select("*"),
      sb.from("v_dash_project_tier").select("*"),
      sb.from("v_dash_audience_perf").select("*"),
      sb.from("v_dash_format_perf").select("*"),
      sb.from("v_dash_reach_concentration").select("*"),
      sb.from("v_dash_system_pulse").select("*"),
    ]);
    const d: any = ov.data;
    if (!d) return EMPTY_DATA;
    const o: Overview = {
      projects: d.projects ?? 0,
      notes: d.notes ?? 0,
      baokuanReal: d.baokuan_real ?? 0,
      cards: d.cards ?? 0,
      librarian: d.librarian ?? 0,
      essence: d.essence_done ?? 0,
      impressions: Math.round((d.impressions ?? 0) * AMPLIFY.impressions),
      reads: Math.round((d.reads ?? 0) * AMPLIFY.reads),
      interactions: Math.round((d.interactions ?? 0) * AMPLIFY.interactions),
      topInteractions: d.top_interactions ?? 0,
      levers: d.levers ?? 0,
      audiences: d.audiences ?? 0,
      ok: true,
    };
    return {
      o,
      levers: (lv.data as Lever[]) ?? [],
      projects: (pj.data as Project[]) ?? [],
      matrix: (mx.data as Matrix[]) ?? [],
      hits: (th.data as TopHit[]) ?? [],
      leverPerf: ((lp.data as any[]) ?? []).map((r) => ({ lever: r.lever, n: num(r.n), hits: num(r.hits), hit_rate: num(r.hit_rate), avg_inter: num(r.avg_inter) })),
      valence: ((vm.data as any[]) ?? []).map((r) => ({ valence: r.valence, intensity: r.intensity, n: num(r.n), hits: num(r.hits), hit_rate: num(r.hit_rate), avg_inter: num(r.avg_inter) })),
      archetypes: ((ar.data as any[]) ?? []).map((r) => ({ archetype: r.archetype, n: num(r.n), hits: num(r.hits), hit_rate: num(r.hit_rate), avg_inter: num(r.avg_inter) })),
      intent: ((it.data as any[]) ?? []).map((r) => ({ intent: r.intent, n: num(r.n), hits: num(r.hits), hit_rate: num(r.hit_rate), read_rate: num(r.read_rate), inter_rate: num(r.inter_rate) })),
      funnel: ((tf.data as any[]) ?? []).map((r) => ({ tier: r.tier, n: num(r.n), avg_imp: num(r.avg_imp), read_rate: num(r.read_rate), inter_rate: num(r.inter_rate), avg_inter: num(r.avg_inter), max_inter: num(r.max_inter) })),
      projectPerf: ((pp.data as any[]) ?? []).map((r) => ({ project_id: r.project_id, category: r.category, notes: num(r.notes), hits: num(r.hits), hit_rate: num(r.hit_rate), avg_imp: Math.round(num(r.avg_imp) * AMPLIFY.impressions), total_imp: Math.round(num(r.total_imp) * AMPLIFY.impressions), essence: num(r.essence) })),
      projectTier: ((pt.data as any[]) ?? []).map((r) => ({ project_id: r.project_id, tier: r.tier, n: num(r.n) })),
      audience: ((aud.data as any[]) ?? []).map((r) => ({ audience: r.audience, n: num(r.n), hits: num(r.hits), hit_rate: num(r.hit_rate), avg_inter: num(r.avg_inter) })),
      formats: ((fp.data as any[]) ?? []).map((r) => ({ fmt: r.fmt, n: num(r.n), hits: num(r.hits), hit_rate: num(r.hit_rate), avg_inter: num(r.avg_inter) })),
      reach: (() => {
        const r = (rc.data as any[])?.[0];
        return r ? { total_notes: num(r.total_notes), total_imp: Math.round(num(r.total_imp) * AMPLIFY.impressions), top1_share: num(r.top1_share), top5_share: num(r.top5_share), top10_share: num(r.top10_share), hit_reach_share: num(r.hit_reach_share), hit_note_pct: num(r.hit_note_pct) } : null;
      })(),
      pulse: (() => {
        const r = (ps.data as any[])?.[0];
        return r
          ? {
              notes_total: num(r.notes_total), last_update: r.last_update ?? null, last_ingest: r.last_ingest ?? null,
              feishu_n: num(r.feishu_n), annotated_n: num(r.annotated_n), annotated_last: r.annotated_last ?? null,
              ssll_n: num(r.ssll_n), ssll_last: r.ssll_last ?? null, aw_n: num(r.aw_n), aw_last: r.aw_last ?? null,
              accounts_n: num(r.accounts_n), snaps_n: num(r.snaps_n), snaps_last: r.snaps_last ?? null,
              audit_n: num(r.audit_n), audit_last: r.audit_last ?? null, projects_n: num(r.projects_n),
              pipeline_runs_n: num(r.pipeline_runs_n), server_now: r.server_now ?? null,
            }
          : null;
      })(),
    };
  } catch {
    return EMPTY_DATA;
  }
}
