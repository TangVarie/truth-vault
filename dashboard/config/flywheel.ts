import type { FlywheelNode, FlywheelEdge } from "@/lib/metrics/types";

/**
 * 飞轮活体图配置(docs/24 §5.5)。加未来模块 = 在这里加一项 node/edge。
 * 去中心化分发已预放为 status:"planned";上线后改 "live" + 绑定 adapter 即出现在图里。
 */
export const NODES: FlywheelNode[] = [
  { id: "feishu", label: "飞书投放表", status: "live" },
  {
    id: "truth_vault",
    label: "Truth Vault",
    status: "live",
    metrics: ["tv.projects", "tv.notes", "tv.baokuan", "tv.cards"],
  },
  { id: "channel1", label: "通道1 · ssll push", status: "live" },
  { id: "channel2", label: "通道2 · 馆员 pull", status: "live", metrics: ["ch2.borrows"] },
  { id: "autowriter", label: "autowriter", status: "live" },
  { id: "sanshengliubu", label: "三生六部", status: "live" },
  // ⬇️ 留好接口:去中心化分发(在线改稿人数等实时指标从这接入)
  { id: "decentralized", label: "去中心化分发", status: "planned", metrics: ["live.editors"] },
];

export const EDGES: FlywheelEdge[] = [
  { from: "feishu", to: "truth_vault", label: "sync" },
  { from: "truth_vault", to: "channel1", label: "push 爆款" },
  { from: "truth_vault", to: "channel2", label: "策展经验卡" },
  { from: "channel1", to: "sanshengliubu", label: "reference_samples" },
  { from: "channel2", to: "autowriter", label: "借卡注入" },
  { from: "decentralized", to: "autowriter", label: "(未来)", planned: true },
];
