/**
 * 看板扩展性接口(docs/24 §5.5)。看板 = config + adapter 驱动:
 * 加新数据源/新指标 = 注册一个 adapter + 改一行 config,核心和 UI 不动。
 * 去中心化分发 / "在线改稿人数" 等未来实时指标就按这套接进来。
 */

export type MetricKind = "count" | "rate" | "percent" | "live";
export type Scope = "public" | "internal";

export interface MetricValue {
  value: number | string;
  hint?: string;
  trend?: number[]; // 可选 sparkline 序列
  asOf?: string; // 数据时间(ISO)
}

/** 一块数据。fetch() 服务端取数,来源任意:Supabase 任一 schema / 外部 API / 未来去中心化节点。 */
export interface MetricAdapter {
  id: string;
  label: string;
  kind: MetricKind;
  scope: Scope; // 公开页只渲染 scope:"public"
  fetch: () => Promise<MetricValue>;
  realtime?: boolean; // true = 走实时通道(见 /api/live),如"在线改稿人数"
}

/** 飞轮活体图节点/边(config 驱动 → 加未来模块 = 加一条 config)。 */
export type SystemId =
  | "feishu"
  | "truth_vault"
  | "channel1"
  | "channel2"
  | "autowriter"
  | "sanshengliubu"
  | "decentralized";

export interface FlywheelNode {
  id: SystemId;
  label: string;
  status: "live" | "planned"; // planned = 占位(如去中心化分发)
  metrics?: string[]; // 关联的 MetricAdapter id
}

export interface FlywheelEdge {
  from: SystemId;
  to: SystemId;
  label: string; // 如 "通道1 push" / "通道2 pull"
  planned?: boolean;
}

/** 实时信号(未来:去中心化分发 / 在线改稿人数)。/api/live/presence 返回这个。 */
export interface LiveSignal {
  id: string;
  label: string;
  online: number;
  source: "supabase_presence" | "heartbeat" | "decentralized" | "stub";
}
