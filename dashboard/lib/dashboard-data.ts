import { getSupabase } from "@/lib/supabase";
import { AMPLIFY, type Overview } from "@/config/showcase";
import type { TopHit } from "@/components/Leaderboard";

/**
 * 看板唯一数据源(docs/24 §3):服务端只读 public 安全聚合视图(只吐大数、不吐明细)。
 * `/`(滚动叙事站)与 `/console`(密集看板)**复用同一份真数据,不重复造**。
 */

export type Lever = { lever: string; n: number };
export type Project = { project_id: string; notes: number; baokuan: number; essence: number; impressions: number };
export type Matrix = { lever: string; audience: string; n: number };
export type DashboardData = {
  o: Overview;
  levers: Lever[];
  projects: Project[];
  matrix: Matrix[];
  hits: TopHit[];
};

const EMPTY: Overview = {
  projects: 0, notes: 0, baokuanReal: 0, cards: 0, librarian: 0, essence: 0,
  impressions: 0, reads: 0, interactions: 0, topInteractions: 0, levers: 0, audiences: 0, ok: false,
};
const EMPTY_DATA: DashboardData = { o: EMPTY, levers: [], projects: [], matrix: [], hits: [] };

export async function getDashboardData(): Promise<DashboardData> {
  const sb = getSupabase();
  if (!sb) return EMPTY_DATA;
  try {
    const [ov, lv, pj, mx, th] = await Promise.all([
      sb.from("v_dash_overview").select("*").single(),
      sb.from("v_dash_levers").select("*").limit(12),
      sb.from("v_dash_projects").select("*"),
      sb.from("v_dash_matrix").select("*"),
      sb.from("v_dash_top_hits").select("*"),
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
    };
  } catch {
    return EMPTY_DATA;
  }
}
