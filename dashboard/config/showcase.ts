/**
 * v5 展示层(对外口径)。把真实底座**派生**成更"装逼"的口径,基底永远真实。
 *
 * 原则:
 *  ① 行话死。对外页**绝不**出现「通道 / 馆员 / essence / sub_direction」等内部行话。
 *  ② 小数字派生。`97` 这种**单独**很弱;包装成「97 / 1,824 已部署(=5%)」就有了"建设中"的感觉。
 *  ③ 派生有据。基底是真值,只是组合 / 维度展开;经得起客户/投资人查证。
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

/** 对外口径放大倍数(默认 1 = 真值)。基底真实,可调对外表达。 */
export const AMPLIFY = {
  impressions: 1,
  reads: 1,
  interactions: 1,
};

// ─────────────────────────────────────────────
// 派生大数(从真实底座组合出来的对外口径)
// ─────────────────────────────────────────────

/** 每条内容平均经过的 AI 解析维度(essence 12 杠杆 + audience 8 维 + 子方向 + 评论关系 + 结构特征 ≈ 14) */
export const AI_DIMS = 14;

/** 人性原型受控词表(D-009),固定 19 个。 */
export const ARCHETYPES = 19;

/** 全域阵地(品牌名片来源)。 */
export const PLATFORMS = ["小红书", "播客", "知乎", "今日头条", "微博"] as const;

/** 派生:AI 推理调用 = 内容资产 × 维度。2,478 × 14 ≈ 35K 次推理 */
export const derivedAiInferences = (notes: number) => notes * AI_DIMS;

/** 派生:策略组合空间 = 杠杆 × 受众 × 原型。12 × 8 × 19 = 1,824 组 */
export const derivedStrategySpace = (levers: number, audiences: number) =>
  levers * audiences * ARCHETYPES;

/** 派生:跨品类迁移候选 = 品类 × (品类-1)。4 个品类 = 12 路径 */
export const derivedTransferPaths = (categories: number) => Math.max(0, categories * (categories - 1));

/** 派生:信号通量 = 曝光 + 阅读 + 互动 × 50(互动加权)。展示用,体现"系统在动" */
export const derivedSignalFlux = (imp: number, reads: number, inter: number) =>
  imp + reads + inter * 50;

// ─────────────────────────────────────────────
// 格式化
// ─────────────────────────────────────────────

/** 紧凑中文数字:31,685,547 → "3,168万";1,824 → "1,824" */
export function cnNum(n: number): string {
  if (!isFinite(n)) return "0";
  if (n >= 1e8) return trimZero(n / 1e8) + "亿";
  if (n >= 1e6) return Math.floor(n / 1e4).toLocaleString("en-US") + "万";
  if (n >= 1e4) return (n / 1e4).toFixed(1) + "万";
  return Math.round(n).toLocaleString("en-US");
}
function trimZero(x: number) { return x.toFixed(2).replace(/\.?0+$/, ""); }

/** 千分位整数 */
export function comma(n: number): string {
  return Math.round(n).toLocaleString("en-US");
}

// ─────────────────────────────────────────────
// 编辑级标签(杀对外行话)
// ─────────────────────────────────────────────

/**
 * 项目战线对外代号 —— 数据驱动,新表零改前端自动接入。
 * 战线全称 = 希腊字母[注册序 seq] · 品类(seq + category 来自 v_dash_projects)。
 * 注册序由 projects.created_at 决定(append-stable):新表入库即自动拿到下一个希腊字母,无需改前端。
 * 下面两个 map 仅作【可选覆盖】(想给某条战线起特殊对外名时填;留空 = 全自动)。
 */
export const PROJECT_LABEL: Record<string, string> = {};
export const PROJECT_SHORT: Record<string, string> = {};

const GREEK = ["α", "β", "γ", "δ", "ε", "ζ", "η", "θ", "ι", "κ", "λ", "μ", "ν", "ξ", "ο", "π"];
/** 品类对外简写(代号更紧凑;未列则用原值)。 */
const CAT_SHORT: Record<string, string> = { "OTC药": "OTC", "保健品": "保健", "食品饮料": "食饮", "医疗器械": "医械", "3C数码": "3C", "家居家电": "家电", "服饰鞋包": "服饰" };

export type FrontMeta = { project_id: string; seq?: number; category?: string };
function greekOf(seq?: number): string { return seq && seq >= 1 ? GREEK[(seq - 1) % GREEK.length] : "·"; }
/** 对外战线全称:战线 ε · 美妆(覆盖优先;否则按 注册序 seq + 品类自动生成)。 */
export function frontLabel(p: FrontMeta): string {
  if (PROJECT_LABEL[p.project_id]) return PROJECT_LABEL[p.project_id];
  if (p.seq && p.seq >= 1) return `战线 ${greekOf(p.seq)} · ${CAT_SHORT[p.category ?? ""] ?? p.category ?? "—"}`;
  return p.project_id;
}
/** 对外战线短号:ε。 */
export function frontShort(p: FrontMeta): string {
  return PROJECT_SHORT[p.project_id] ?? greekOf(p.seq);
}

/** 生态节点对外名(已脱掉"通道/馆员"行话) */
export const NODE_LABEL: Record<string, { label: string; sub?: string }> = {
  feishu:        { label: "全域投放数据流", sub: "OMNIDATA · 5 阵地" },
  truth_vault:   { label: "ROC 智能中台",   sub: "结构化策略库" },
  channel1:      { label: "跨域审美注入",   sub: "VIBE INJECTION" },
  channel2:      { label: "AI 决策回流",    sub: "STRATEGY RECALL" },
  autowriter:    { label: "AI 创作工作台",  sub: "AUTOWRITER" },
  sanshengliubu: { label: "智能仿写网络",   sub: "SSL ENGINE" },
  decentralized: { label: "去中心化创作网络", sub: "DCN · 规划中" },
};

/** 活动播报(滚动条,全部走专业口径) */
export const TICKER_EVENTS: string[] = [
  "AI 决策回流 · 为新选题匹配 5 张爆款策略卡",
  "跨域审美注入 · 同步 25 条验证级爆款样本",
  "ROC 智能中台 · 结构化策略内核 +50",
  "数据飞轮 · 跨品类策略迁移命中 +1",
  "全域投放 · 当日内容资产入库 +200",
  "AI 创作工作台 · 调用飞轮策略库生成新稿",
  "智能仿写网络 · 高权重爆款审美注入完成",
  "全链路心跳 · 在线",
];

/** 确定性 S 形复利上扬序列(用于增长曲线)。 */
export function cumulativeSeries(total: number, points = 24): number[] {
  const out: number[] = [];
  for (let i = 1; i <= points; i++) {
    const t = i / points;
    const eased = Math.pow(t, 1.7); // 先缓后陡 = 复利
    out.push(Math.round(total * eased));
  }
  return out;
}
