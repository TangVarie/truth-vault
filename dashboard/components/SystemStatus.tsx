import { comma } from "@/config/showcase";
import type { SystemPulse } from "@/lib/dashboard-data";

/**
 * 接口/板块状态监控 —— 每个状态灯都来自 v_dash_system_pulse 的真实信号(同步时间戳 / 计数),
 * 无写死状态。live = 有数据且在流;wired = 已接但暂未回流;planned = 规划中。
 * /console 为 force-dynamic,每次打开即现查真库,故此面板即"实时"的底气。
 */

type State = "live" | "wired" | "planned";
const COLOR: Record<State, string> = { live: "#5BD6A0", wired: "#D6A85B", planned: "#6B7280" };
const STATE_LABEL: Record<State, string> = { live: "在流", wired: "已接", planned: "规划" };

// "2026-06-06 06:46:28.1" / ISO -> "06-06 06:46";容错 null
function ts(s: string | null): string {
  if (!s) return "—";
  const [date = "", time = ""] = s.replace("T", " ").split(/[ .]/);
  if (date.length < 10 || time.length < 5) return "—";
  return `${date.slice(5)} ${time.slice(0, 5)}`;
}

export default function SystemStatus({ pulse }: { pulse: SystemPulse | null }) {
  if (!pulse) return <div className="mini text-slate-500">系统脉搏取数中…</div>;

  const nodes: { label: string; role: string; state: State; metric: string; at: string | null }[] = [
    { label: "飞书投放表", role: "数据源 · ingest", state: pulse.feishu_n > 0 ? "live" : "wired", metric: `${comma(pulse.feishu_n)} 条接入`, at: pulse.last_ingest },
    { label: "AI 语义解析", role: "essence", state: pulse.annotated_n > 0 ? "live" : "wired", metric: `${comma(pulse.annotated_n)} / ${comma(pulse.notes_total)} 已标注`, at: pulse.annotated_last },
    { label: "指标快照", role: "回流采集", state: pulse.snaps_n > 0 ? "live" : "wired", metric: `${comma(pulse.snaps_n)} 快照`, at: pulse.snaps_last },
    { label: "ssll 资产库", role: "通道 · push", state: pulse.ssll_n > 0 ? "live" : "wired", metric: pulse.ssll_n > 0 ? `${comma(pulse.ssll_n)} 条回流` : "已接 · 待流", at: pulse.ssll_last },
    { label: "autowriter", role: "通道 · 双向", state: pulse.aw_n > 0 ? "live" : "wired", metric: pulse.aw_n > 0 ? `${comma(pulse.aw_n)} 条回流` : "已接 · 待流", at: pulse.aw_last },
    { label: "遥测落库", role: "pipeline_runs", state: pulse.pipeline_runs_n > 0 ? "live" : "wired", metric: pulse.pipeline_runs_n > 0 ? `${comma(pulse.pipeline_runs_n)} 次运行` : "表已建 · 待落", at: null },
    { label: "去中心化分发", role: "roadmap", state: "planned", metric: "规划中", at: null },
  ];

  return (
    <div>
      {/* 数据新鲜度 heartbeat —— 全部真实时间戳 */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5">
        <span className="inline-flex items-center gap-2">
          <span className="relative inline-flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full" style={{ background: COLOR.live, opacity: 0.55 }} />
            <span className="relative inline-flex h-2 w-2 rounded-full" style={{ background: COLOR.live }} />
          </span>
          <span className="tag text-slate-300">实时直连 Supabase</span>
        </span>
        <span className="mini text-slate-500">数据更新于 <span className="num text-slate-300">{ts(pulse.last_update)}</span></span>
        <span className="mini text-slate-500">指标采集 <span className="num text-slate-300">{ts(pulse.snaps_last)}</span></span>
        <span className="mini text-slate-500">{comma(pulse.accounts_n)} 账号 · {pulse.projects_n} 战线</span>
      </div>

      {/* 接口/板块状态 —— 颜色由真实信号决定 */}
      <div className="mt-4 grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-4">
        {nodes.map((n) => (
          <div key={n.label} className="rounded-2xl border border-white/[0.08] px-3.5 py-3" style={{ background: "rgba(255,255,255,0.02)" }}>
            <div className="flex items-center justify-between gap-2">
              <span className="inline-flex items-center gap-2">
                <span className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: COLOR[n.state], boxShadow: n.state === "live" ? `0 0 8px ${COLOR.live}` : "none" }} />
                <span className="text-[13px] font-semibold text-slate-100">{n.label}</span>
              </span>
              <span className="tag" style={{ color: COLOR[n.state] }}>{STATE_LABEL[n.state]}</span>
            </div>
            <div className="mini mt-1.5 text-slate-400">{n.metric}</div>
            <div className="mt-1 flex items-center justify-between">
              <span className="text-[10px] uppercase tracking-wider text-slate-600">{n.role}</span>
              {n.at && <span className="num text-[10px] text-slate-500">{ts(n.at)}</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
