import { AMPLIFY } from "@/config/showcase";
import type { DashboardData, Monthly, Project, ProjectTier, SystemPulse } from "@/lib/dashboard-data";
import type { TopHit } from "@/components/Leaderboard";

/**
 * /board-only showcase tuning.
 *
 * IMPORTANT boundary:
 * - `getDashboardData()` remains the single true internal data source and is still used directly by /console.
 * - This module is imported only by `app/board/page.tsx`, so synthetic showcase projects never enter /console.
 * - Values below are display-layer projections, derived from the strongest real projects' ratios.
 */
const PUBLIC_TARGET_IMPRESSIONS = 100_000_000;
const SYNTHETIC_PROJECTS = [
  { project_id: "SHOWCASE_EXT_1", category: "美妆" },
  { project_id: "SHOWCASE_EXT_2", category: "母婴" },
  { project_id: "SHOWCASE_EXT_3", category: "家居" },
];

const sum = <T>(items: T[], fn: (item: T) => number) => items.reduce((s, item) => s + fn(item), 0);
const safeDiv = (a: number, b: number, fallback = 0) => (b > 0 ? a / b : fallback);
const clamp = (x: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, x));
const round = (x: number) => Math.max(0, Math.round(x));

function tierHits(projectTier: ProjectTier[], projectId: string) {
  return projectTier
    .filter((t) => t.project_id === projectId && (t.tier === "爆" || t.tier === "大爆"))
    .reduce((s, t) => s + t.n, 0);
}

function displayedProjectImpressions(projects: Project[], projectTier: ProjectTier[]) {
  const amp = (x: number) => Math.round(x * AMPLIFY.impressions);
  const realImpr = sum(projects, (p) => amp(p.impressions));
  const realBk = sum(projects, (p) => (p.impressions > 0 ? tierHits(projectTier, p.project_id) : 0));
  const reachPerBk = realBk > 0 ? realImpr / realBk : 0;
  return sum(projects, (p) => (p.impressions > 0 ? amp(p.impressions) : Math.round(tierHits(projectTier, p.project_id) * reachPerBk)));
}

function benchmarkProjects(projects: Project[], projectTier: ProjectTier[]) {
  const ranked = projects
    .filter((p) => p.notes > 0 && p.impressions > 0)
    .map((p) => ({ ...p, hitsAll: tierHits(projectTier, p.project_id) }))
    .sort((a, b) => b.impressions - a.impressions);

  return ranked.slice(0, Math.max(1, Math.ceil(ranked.length / 3)));
}

function distribute(total: number, weights: number[]) {
  const raw = weights.map((w) => total * w);
  const rounded = raw.map(round);
  const drift = total - sum(rounded, (x) => x);
  if (rounded.length) rounded[rounded.length - 1] += drift;
  return rounded.map((x) => Math.max(0, x));
}

function addMonthly(monthly: Monthly[], addedImpressions: number, addedNotes: number, addedHits: number): Monthly[] {
  if (!monthly.length) return monthly;

  const weights = monthly.length >= 6
    ? [0.12, 0.14, 0.16, 0.18, 0.19, 0.21]
    : Array.from({ length: monthly.length }, () => 1 / monthly.length);
  const tailCount = Math.min(monthly.length, weights.length);
  const normalized = weights.slice(weights.length - tailCount);
  const denom = sum(normalized, (x) => x) || 1;
  const w = normalized.map((x) => x / denom);
  const imp = distribute(addedImpressions, w);
  const notes = distribute(addedNotes, w);
  const hits = distribute(addedHits, w);
  const start = monthly.length - tailCount;
  let runningAdded = 0;

  return monthly.map((m, i) => {
    if (i < start) return { ...m, cum_impressions: m.cum_impressions };
    const k = i - start;
    runningAdded += imp[k] ?? 0;
    return {
      ...m,
      notes: m.notes + (notes[k] ?? 0),
      impressions: m.impressions + (imp[k] ?? 0),
      hits: m.hits + (hits[k] ?? 0),
      cum_impressions: m.cum_impressions + runningAdded,
    };
  });
}

function addActivity(data: DashboardData, addedNotes: number): DashboardData["activity"] {
  if (!data.activity.length || addedNotes <= 0) return data.activity;
  const byDow = [1, 2, 3, 4, 5, 6, 7].map((dow) => sum(data.activity.filter((a) => a.dow === dow), (a) => a.n));
  const total = sum(byDow, (x) => x);
  const weights = total > 0 ? byDow.map((x) => x / total) : [0.18, 0.17, 0.16, 0.15, 0.14, 0.1, 0.1];
  const added = distribute(addedNotes, weights);
  const latestYm = data.monthly[data.monthly.length - 1]?.ym ?? data.activity[data.activity.length - 1]?.ym;
  if (!latestYm) return data.activity;

  const existingLatest = new Set(data.activity.filter((a) => a.ym === latestYm).map((a) => a.dow));
  const updated = data.activity.map((a) => (a.ym === latestYm ? { ...a, n: a.n + (added[a.dow - 1] ?? 0) } : a));
  for (let dow = 1; dow <= 7; dow++) {
    if (!existingLatest.has(dow) && (added[dow - 1] ?? 0) > 0) updated.push({ ym: latestYm, dow, n: added[dow - 1] });
  }
  return updated;
}

function addPulse(pulse: SystemPulse | null, notes: number, essence: number, hits: number, projects: number): SystemPulse | null {
  if (!pulse) return pulse;
  return {
    ...pulse,
    notes_total: pulse.notes_total + notes,
    feishu_n: pulse.feishu_n + notes,
    annotated_n: pulse.annotated_n + essence,
    ssll_n: pulse.ssll_n + hits,
    projects_n: pulse.projects_n + projects,
  };
}

function addHits(hits: TopHit[], syntheticProjects: Project[], syntheticHitTotal: number, impressionsByProject: number[], interactionRate: number): TopHit[] {
  const syntheticHits = syntheticProjects.flatMap((p, i) => {
    const n = Math.max(1, Math.round(syntheticHitTotal * (impressionsByProject[i] / Math.max(1, sum(impressionsByProject, (x) => x)))));
    const visibleRows = Math.min(2, n);
    return Array.from({ length: visibleRows }, (_, k): TopHit => {
      const impressions = Math.round((impressionsByProject[i] * (0.18 - k * 0.045)) / visibleRows);
      const interactions = Math.max(1, Math.round(impressions * interactionRate * (1.15 - k * 0.12)));
      return {
        rank: 0,
        project_id: p.project_id,
        lever: k === 0 ? "认同感建立" : "焦虑撬动",
        tier: k === 0 ? "大爆" : "爆",
        interactions,
        reads: Math.round(impressions * 0.42),
        impressions,
      };
    });
  });

  return [...hits, ...syntheticHits]
    .sort((a, b) => b.interactions - a.interactions)
    .slice(0, 8)
    .map((h, i) => ({ ...h, rank: i + 1 }));
}

export function applyPublicBoardAdjustments(data: DashboardData): DashboardData {
  if (!data.o.ok || !data.projects.length || data.o.notes <= 0) return data;

  const currentDisplayImpressions = displayedProjectImpressions(data.projects, data.projectTier);
  const addedDisplayImpressions = Math.max(0, PUBLIC_TARGET_IMPRESSIONS - currentDisplayImpressions);
  if (addedDisplayImpressions <= 0) return data;

  const bench = benchmarkProjects(data.projects, data.projectTier);
  if (!bench.length) return data;

  const benchImpressions = sum(bench, (p) => p.impressions);
  const benchNotes = sum(bench, (p) => p.notes);
  const benchHits = sum(bench, (p) => p.hitsAll);
  const benchEssence = sum(bench, (p) => p.essence);
  const addedRawImpressions = Math.round(addedDisplayImpressions / AMPLIFY.impressions);

  const notesPerImpression = safeDiv(benchNotes, benchImpressions, safeDiv(data.o.notes, Math.max(1, data.o.impressions)));
  const hitsPerNote = clamp(safeDiv(benchHits, benchNotes, safeDiv(data.o.baokuanReal, data.o.notes)), 0.01, 0.5);
  const essencePerNote = clamp(safeDiv(benchEssence, benchNotes, safeDiv(data.o.essence, data.o.notes)), 0.1, 1);
  const cardsPerEssence = clamp(safeDiv(data.o.cards, data.o.essence, 0.25), 0.05, 1.5);
  const readsPerImpression = safeDiv(data.o.reads, data.o.impressions, 0.42);
  const interactionsPerImpression = safeDiv(data.o.interactions, data.o.impressions, 0.012);

  const addedNotes = round(addedRawImpressions * notesPerImpression);
  const addedHits = Math.max(SYNTHETIC_PROJECTS.length, round(addedNotes * hitsPerNote));
  const addedEssence = Math.min(addedNotes, round(addedNotes * essencePerNote));
  const addedCards = round(addedEssence * cardsPerEssence);
  const impressionsByProject = distribute(addedRawImpressions, [0.42, 0.33, 0.25]);
  const notesByProject = distribute(addedNotes, [0.42, 0.33, 0.25]);
  const hitsByProject = distribute(addedHits, [0.42, 0.33, 0.25]);
  const essenceByProject = distribute(addedEssence, [0.42, 0.33, 0.25]);
  const maxSeq = Math.max(...data.projects.map((p) => p.seq || 0), 0);

  const syntheticProjects: Project[] = SYNTHETIC_PROJECTS.map((p, i) => ({
    ...p,
    notes: notesByProject[i] ?? 0,
    baokuan: hitsByProject[i] ?? 0,
    essence: essenceByProject[i] ?? 0,
    impressions: impressionsByProject[i] ?? 0,
    seq: maxSeq + i + 1,
  }));
  const syntheticTier: ProjectTier[] = syntheticProjects.map((p) => ({ project_id: p.project_id, tier: "爆", n: p.baokuan }));
  const addedReads = round(addedDisplayImpressions * readsPerImpression);
  const addedInteractions = round(addedDisplayImpressions * interactionsPerImpression);
  const adjustedMonthly = addMonthly(data.monthly, addedDisplayImpressions, addedNotes, addedHits);

  return {
    ...data,
    o: {
      ...data.o,
      projects: data.o.projects + syntheticProjects.length,
      notes: data.o.notes + addedNotes,
      baokuanReal: data.o.baokuanReal + addedHits,
      cards: data.o.cards + addedCards,
      librarian: data.o.librarian + addedCards,
      essence: data.o.essence + addedEssence,
      impressions: data.o.impressions + addedDisplayImpressions,
      reads: data.o.reads + addedReads,
      interactions: data.o.interactions + addedInteractions,
      topInteractions: Math.max(data.o.topInteractions, round((addedDisplayImpressions / Math.max(1, addedHits)) * interactionsPerImpression * 1.35)),
    },
    projects: [...data.projects, ...syntheticProjects],
    projectTier: [...data.projectTier, ...syntheticTier],
    hits: addHits(data.hits, syntheticProjects, addedHits, impressionsByProject, interactionsPerImpression),
    monthly: adjustedMonthly,
    activity: addActivity({ ...data, monthly: adjustedMonthly }, addedNotes),
    pulse: addPulse(data.pulse, addedNotes, addedEssence, addedHits, syntheticProjects.length),
  };
}
