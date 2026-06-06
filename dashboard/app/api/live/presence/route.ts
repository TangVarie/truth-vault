import { NextResponse } from "next/server";
import type { LiveSignal } from "@/lib/metrics/types";

export const dynamic = "force-dynamic"; // 实时,不缓存

/**
 * 实时"在线"信号接口(docs/24 §5.5)。
 * ⚠️ 现在是 stub —— 去中心化分发上线后,"线上同时多少人改稿"从这里出。
 * 实现择一:
 *   - Supabase Realtime presence(改稿会话加 presence channel)
 *   - heartbeat 表(改稿端每 N 秒上报 last_seen,这里按窗口 count)
 *   - 去中心化节点上报
 * 前端组件 + 本契约现在就留好,接真数据时不动 UI。
 */
export async function GET() {
  const signals: LiveSignal[] = [
    { id: "live.editors", label: "在线改稿人数", online: 0, source: "stub" },
  ];
  return NextResponse.json({
    signals,
    note: "stub — 去中心化分发上线后接入(docs/24 §5.5)",
    asOf: new Date().toISOString(),
  });
}
