import { comma } from "@/config/showcase";
import type { DashboardData } from "@/lib/dashboard-data";

/**
 * 「分战线 · BY FRONT」—— 把规律拆到每条战线:规模、命中率、总触达、tier 构成金字塔。
 * 揭示真实差距(本数据里 4 条线命中率相差 ~17×,且篇数最多的一条恰恰最不出爆款)。
 * 纯展示(服务端)· 只露 project_id + 品类,不露品牌(对齐既有公开口径)。
 * 留口子:遍历真库现有的 project / tier,新增战线或层级会自动出现(表实时更新)。
 */

const card = "rounded-3xl border border-white/[0.10] p-6";
const cardStyle = { background: "rgba(255,255,255,0.04)" } as const;

const TIER_ORDER = ["趴", "风控", "预备", "爆", "大爆"];
const TIER_COLOR: Record<string, string> = {
  趴: "rgba(255,255,255,0.10)",
  风控: "rgba(255,255,255,0.22)",
  预备: "rgba(232,118,90,0.30)",
  爆: "rgba(232,118,90,0.62)",
  大爆: "#E8765A",
};

function cnShort(n: number): string {
  if (n >= 1e8) return (n / 1e8).toFixed(1) + "亿";
  if (n >= 1e4) return (n / 1e4).toFixed(n >= 1e6 ? 0 : 1) + "万";
  return comma(n);
}

export default function ByFront({ data }: { data: DashboardData }) {
  const { projectPerf, projectTier } = data;
  if (!projectPerf.length) return null;

  const rows = [...projectPerf].sort((a, b) => b.hit_rate - a.hit_rate);
  const maxHit = Math.max(...rows.map((r) => r.hit_rate), 1);
  const withHits = rows.filter((r) => r.notes > 0);
  const best = withHits.reduce((a, b) => (b.hit_rate > a.hit_rate ? b : a), withHits[0]);
  const worst = withHits.reduce((a, b) => (b.hit_rate < a.hit_rate ? b : a), withHits[0]);
  const mostNotes = rows.reduce((a, b) => (b.notes > a.notes ? b : a), rows[0]);
  const ratio = worst.hit_rate > 0 ? Math.round(best.hit_rate / worst.hit_rate) : null;

  const tierByProj = new Map<string, Record<string, number>>();
  for (const t of projectTier) {
    const m = tierByProj.get(t.project_id) ?? {};
    m[t.tier] = t.n;
    tierByProj.set(t.project_id, m);
  }

  return (
    <section className="mb-4">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <span className="tag text-coral">分战线 · BY FRONT</span>
          <h2 className="mt-1 font-bold text-white" style={{ fontSize: "clamp(24px,3vw,40px)", letterSpacing: "-0.02em" }}>
            同一套方法,每条线的结果天差地别。
          </h2>
        </div>
        <span className="mini max-w-md text-slate-500">
          {rows.length} 条战线 · 仅露 project_id + 品类 · 命中率 = 爆+大爆 / 该线全部
        </span>
      </div>

      {/* 动态差距洞察 */}
      <div className={`${card} mb-4`} style={{ background: "radial-gradient(900px 200px at 20% 0%, rgba(232,118,90,0.12), transparent 70%), rgba(255,255,255,0.04)" }}>
        <span className="tag text-slate-400">战线差距 · THE SPREAD</span>
        <p className="mt-3 text-white" style={{ fontSize: "clamp(17px,2vw,26px)", lineHeight: 1.45, letterSpacing: "-0.01em" }}>
          「<span className="text-coral">{best.project_id}</span>」({best.category})命中{" "}
          <span className="num font-bold text-coral">{best.hit_rate}%</span>,而「<span className="text-slate-300">{worst.project_id}</span>」({worst.category})仅{" "}
          <span className="num font-bold text-slate-300">{worst.hit_rate}%</span>
          {ratio ? <> —— 相差 <span className="num font-bold text-coral">{ratio}×</span></> : null}。
          {worst.project_id === mostNotes.project_id ? (
            <span className="text-slate-400"> 而它,恰恰是你投得最多的一条线({comma(mostNotes.notes)} 篇)。</span>
          ) : null}
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {rows.map((r) => {
          const tiers = tierByProj.get(r.project_id) ?? {};
          const tierTotal = TIER_ORDER.reduce((s, t) => s + (tiers[t] ?? 0), 0) || 1;
          const intensity = 0.42 + 0.58 * (r.hit_rate / maxHit);
          const hitColor = `rgba(232,118,90,${intensity.toFixed(3)})`;
          return (
            <div key={r.project_id} className={card} style={cardStyle}>
              <div className="flex items-center justify-between gap-2">
                <span className="num truncate text-sm font-medium text-slate-200" title={r.project_id}>{r.project_id}</span>
                <span className="mini shrink-0 rounded-full px-2 py-0.5 text-slate-300" style={{ background: "rgba(255,255,255,0.07)" }}>{r.category}</span>
              </div>

              <div className="mt-5 flex items-baseline gap-2">
                <span className="num font-bold" style={{ fontSize: "clamp(30px,3.4vw,48px)", lineHeight: 1, letterSpacing: "-0.03em", color: hitColor }}>{r.hit_rate}%</span>
                <span className="mini text-slate-500">命中率</span>
              </div>
              <div className="mini mt-1 text-slate-600">{comma(r.hits)} 爆款 / {comma(r.notes)} 篇</div>

              {/* tier 构成金字塔 */}
              <div className="mt-4 flex h-2 overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,0.05)" }}>
                {TIER_ORDER.map((t) => {
                  const w = ((tiers[t] ?? 0) / tierTotal) * 100;
                  if (w <= 0) return null;
                  return <span key={t} style={{ width: `${w}%`, background: TIER_COLOR[t] }} title={`${t}: ${tiers[t]}`} />;
                })}
              </div>

              <div className="mt-4 grid grid-cols-2 gap-2 border-t border-white/[0.08] pt-3">
                <div>
                  <div className="num text-sm font-semibold text-slate-200">{cnShort(r.total_imp)}</div>
                  <div className="mini text-slate-600">总触达</div>
                </div>
                <div>
                  <div className="num text-sm font-semibold text-slate-200">{cnShort(r.avg_imp)}</div>
                  <div className="mini text-slate-600">篇均曝光</div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* 生命周期留口子:时序数据成熟后自动点亮 */}
      <div className={`${card} mt-4`} style={{ ...cardStyle, borderStyle: "dashed" }}>
        <div className="flex items-center gap-2">
          <span className="tag text-slate-500">爆款生命周期 · LIFECYCLE</span>
          <span className="mini rounded-full px-2 py-0.5 text-slate-500" style={{ background: "rgba(255,255,255,0.06)" }}>待时序数据</span>
        </div>
        <p className="mini mt-2 max-w-2xl text-slate-500">
          诚实留口:当前 metric_snapshots 多为单次终值、早期窗口(2h/24h/72h)未覆盖爆款,
          画"点火曲线"会是虚构的纵向队列。一旦早期追踪补齐,这里将自动渲染 爆款 vs 趴 的真实成长轨迹。
        </p>
      </div>
    </section>
  );
}
