import type { DashboardData } from "@/lib/dashboard-data";

/**
 * 「活体飞轮 · Neural Bloom」数据→生长模型。
 * 把真实数据映射成一团"会生长的神经花"的生长参数 —— 算法无关:任何有机生长渲染器
 * (空间殖民/L-system/力导向/分形分枝)都能消费这份 spec。
 *   战线 → 主枝 · 笔记 → 细丝 · 爆款 → 亮点 · 情绪杠杆 → 色相光谱 · 复利 S 曲线 → 生长时间轴
 * 确定性(mulberry32 + 固定种子):SSR/client 一致、可复现。
 */

function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export type BloomBranch = {
  id: string;
  label: string;
  angle: number; // 主枝出射角(弧度)
  weight: number; // 0..1 相对粗细/长度(按曝光)
  filaments: number; // 该枝细丝数(按笔记)
  bright: number; // 亮点数(按爆款)
  hue: number; // 色相(情绪光谱)
  seed: number;
};

export type BloomSpec = {
  core: number; // 中心大数(内容资产)
  branches: BloomBranch[];
  totalFilaments: number;
  totalBright: number;
  hues: number[]; // 情绪杠杆光谱(色相数组)
  stages: number[]; // 复利生长 S 曲线(0..1),供时间轴 scrub
  seed: number;
};

const SEED = 20260606;

/** 细丝总数随笔记量增长但封顶(性能) */
function clampFilaments(notes: number) {
  return Math.min(900, Math.max(140, Math.round(notes * 0.4)));
}

export function buildBloomSpec(data: DashboardData): BloomSpec {
  const { o, projects } = data;
  const r = rng(SEED);

  // 无数据(本地/未配 env)时给一组合理默认枝,保证 bloom 仍可渲染
  const base =
    projects.length > 0
      ? projects
      : Array.from({ length: 4 }, (_, i) => ({
          project_id: `战线 ${i + 1}`,
          notes: 90 + i * 30,
          baokuan: 5 + i * 2,
          essence: 40,
          impressions: 1200 + i * 600,
        }));

  const notesTotal = Math.max(1, base.reduce((s, p) => s + p.notes, 0));
  const impTotal = Math.max(1, base.reduce((s, p) => s + p.impressions, 0));
  const filamentBudget = clampFilaments(o.notes || notesTotal);

  // 情绪杠杆 → 色相光谱(Neurones 彩虹;暖橙 18° → 冷品红 318°,留出 coral 主调)
  const nHue = Math.max(5, Math.min(12, base.length * 2));
  const hues = Array.from({ length: nHue }, (_, i) => (18 + (i / nHue) * 300) % 360);

  const branches: BloomBranch[] = base.map((p, i) => {
    const angle = (i / base.length) * Math.PI * 2 - Math.PI / 2 + (r() - 0.5) * 0.45;
    const weight = 0.4 + 0.6 * (p.impressions / impTotal);
    const filaments = Math.max(10, Math.round((p.notes / notesTotal) * filamentBudget));
    const bright = Math.max(1, Math.round(p.baokuan));
    return {
      id: p.project_id,
      label: p.project_id,
      angle,
      weight,
      filaments,
      bright,
      hue: hues[(i * 2) % hues.length],
      seed: Math.floor(r() * 1e9),
    };
  });

  // 复利 S 生长曲线(先缓后陡),供时间轴 scrub:stage[t] = 已长出的比例
  const stages = Array.from({ length: 28 }, (_, i) => Math.pow((i + 1) / 28, 1.7));

  return {
    core: o.notes || notesTotal,
    branches,
    totalFilaments: filamentBudget,
    totalBright: o.baokuanReal || base.reduce((s, p) => s + p.baokuan, 0),
    hues,
    stages,
    seed: SEED,
  };
}
