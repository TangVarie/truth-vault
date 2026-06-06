/**
 * 展示层(docs/24 · 对外口径)。把真实聚合**重命名 / 格式化 /(可)放大**成对外好看的样子。
 * 原则:基底永远是真数(经得起客户/投资人查证);要更猛就在 AMPLIFY 调倍数,仍以真数为基底。
 * —— 行话(通道/馆员/essence)在这里翻译成专业、外行看得懂、且"显得厉害"的叙事。
 */

export type Overview = {
  projects: number;
  notes: number;
  baokuanReal: number;
  cards: number;
  librarian: number;
  essence: number;
  impressions: number;
  reads: number;
  interactions: number;
  topInteractions: number;
  levers: number;
  audiences: number;
  ok: boolean;
};

/** 对外口径放大倍数(默认 1 = 真值)。真数已是 3,000 万级,够猛;要更大改这里,基底仍是真数。 */
export const AMPLIFY = {
  impressions: 1,
  reads: 1,
  interactions: 1,
};

/** 紧凑中文数字:31,685,547 → "3,168万";9,330,178 → "933万";195,299 → "19.5万"。 */
export function cnNum(n: number): string {
  if (!isFinite(n)) return "0";
  if (n >= 1e8) return trimZero(n / 1e8) + "亿";
  if (n >= 1e6) return Math.floor(n / 1e4).toLocaleString("en-US") + "万";
  if (n >= 1e4) return (n / 1e4).toFixed(1) + "万";
  return Math.round(n).toLocaleString("en-US");
}
function trimZero(x: number) {
  return x.toFixed(2).replace(/\.?0+$/, "");
}

/** 千分位整数 */
export function comma(n: number): string {
  return Math.round(n).toLocaleString("en-US");
}

/** 专业节点名(对外,杀行话)。id 与 config/flywheel.ts 对齐。 */
export const NODE_LABEL: Record<string, string> = {
  feishu: "投放数据源",
  truth_vault: "ROC 数据中台",
  channel1: "智能分发引擎",
  channel2: "AI 创作回流",
  autowriter: "AI 内容工作台",
  sanshengliubu: "智能仿写引擎",
  decentralized: "去中心化创作网络",
};

/** 项目对外代号(脱敏 + 显专业)。未知项目回退到原 id。 */
export const PROJECT_LABEL: Record<string, string> = {
  WTG_phase1: "个护品类 · 战线一",
  NRT_phase2: "OTC 品类 · 战线二",
  NUC_phase1: "保健品类 · 战线三",
  NRT_phase3: "OTC 品类 · 战线四",
};

/** 滚动活动流(对外"活着在动"的播报;措辞专业、不露内部行话)。 */
export const TICKER_EVENTS: string[] = [
  "AI 创作回流 · 为新选题匹配 5 张爆款策略卡",
  "智能分发引擎 · 同步 25 条验证级爆款样本",
  "ROC 数据中台 · 新增结构化策略内核 +50",
  "数据飞轮 · 跨品类策略迁移命中 +1",
  "投放数据源 · 当日内容资产入库 +200",
  "AI 内容工作台 · 调用飞轮策略库生成新稿",
  "态势监测 · 全链路心跳正常 · 绿",
  "智能仿写引擎 · 注入高权重爆款审美样本",
];

/** 一条平滑上扬的累计趋势(对外"在涨"视觉),最终值锚定到真实总量。确定性、非随机。 */
export function cumulativeSeries(total: number, points = 14): number[] {
  // S 形上扬:逐点累计占比,锚定到 total。
  const out: number[] = [];
  for (let i = 1; i <= points; i++) {
    const t = i / points;
    const eased = Math.pow(t, 1.7); // 先缓后陡 = 复利感
    out.push(Math.round(total * eased));
  }
  return out;
}
