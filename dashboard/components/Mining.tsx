import { comma } from "@/config/showcase";
import type { DashboardData } from "@/lib/dashboard-data";

/**
 * 「深度挖掘 · WHY IT HITS」—— 从真实数据挖出"什么在驱动爆款"的底层规律,而非展示大数。
 * 情绪杠杆命中率排行(最常用≠最有效)· 效价×强度引擎矩阵 · 意图分野 · tier 漏斗。
 * 纯展示(服务端),座舱暗色语言。数据来自 public 安全聚合视图(v_dash_*_perf / matrix / funnel)。
 */

const VAL: Record<string, string> = { negative: "负面", neutral: "中性", positive: "正面" };
const INT: Record<string, string> = { low: "低强度", medium: "中强度", high: "高强度" };
const VAL_ORDER = ["negative", "neutral", "positive"];
const INT_ORDER = ["low", "medium", "high"];

const card = "rounded-3xl border border-white/[0.10] p-6";
const cardStyle = { background: "rgba(255,255,255,0.04)" } as const;

export default function Mining({ data }: { data: DashboardData }) {
  const { leverPerf, valence, archetypes, intent, funnel } = data;
  if (!leverPerf.length && !valence.length) {
    return null; // 无数据(本地未配 env)时不渲染
  }

  const mostUsed = leverPerf.reduce((a, b) => (b.n > a.n ? b : a), leverPerf[0]);
  const best = leverPerf.reduce((a, b) => (b.hit_rate > a.hit_rate ? b : a), leverPerf[0]);
  const ratio = mostUsed.hit_rate > 0 ? Math.round(best.hit_rate / mostUsed.hit_rate) : null;
  const maxRate = Math.max(...leverPerf.map((l) => l.hit_rate), 1);

  const valMax = Math.max(...valence.map((v) => v.hit_rate), 1);
  const valGet = (vv: string, ii: string) => valence.find((c) => c.valence === vv && c.intensity === ii);
  const valTop = valence.reduce((a, b) => (b.hit_rate > (a?.hit_rate ?? -1) ? b : a), valence[0]);

  const traffic = intent.find((i) => i.intent === "traffic");
  const conversion = intent.find((i) => i.intent === "conversion");

  const tierOrder = ["趴", "预备", "爆", "大爆"];
  const fsorted = tierOrder.map((t) => funnel.find((f) => f.tier === t)).filter(Boolean) as DashboardData["funnel"];
  const maxReadRate = Math.max(...fsorted.map((f) => f.read_rate), 0.35);

  const topArche = archetypes.slice(0, 8);
  const archeMax = Math.max(...topArche.map((a) => a.hit_rate), 1);

  return (
    <section className="mb-4">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <span className="tag text-coral">深度挖掘 · WHY IT HITS</span>
          <h2 className="mt-1 font-bold text-white" style={{ fontSize: "clamp(24px,3vw,40px)", letterSpacing: "-0.02em" }}>
            什么,真正在驱动爆款。
          </h2>
        </div>
        <span className="mini max-w-md text-slate-500">
          基于 {comma(data.o.essence || 1192)} 篇已结构化解析内容 · 命中率 = 爆+大爆 / 该维度全部
        </span>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        {/* 洞察 callout(动态:最常用 vs 最有效)*/}
        <div className={`${card} lg:col-span-12`} style={{ background: "radial-gradient(900px 200px at 20% 0%, rgba(232,118,90,0.12), transparent 70%), rgba(255,255,255,0.04)" }}>
          <span className="tag text-slate-400">核心洞察 · THE PARADOX</span>
          <p className="mt-3 text-white" style={{ fontSize: "clamp(18px,2.2vw,28px)", lineHeight: 1.45, letterSpacing: "-0.01em" }}>
            你押注最多的杠杆「<span className="text-slate-300">{mostUsed.lever}</span>」(<span className="num">{comma(mostUsed.n)}</span> 篇)命中率仅{" "}
            <span className="num font-bold text-slate-300">{mostUsed.hit_rate}%</span>;而「<span className="text-coral">{best.lever}</span>」(<span className="num">{comma(best.n)}</span> 篇)命中{" "}
            <span className="num font-bold text-coral">{best.hit_rate}%</span>
            {ratio ? <> —— 高 <span className="num font-bold text-coral">{ratio}×</span></> : null}。
            <span className="text-slate-400">最常用的打法,恰恰不是最赢的打法。</span>
          </p>
        </div>

        {/* 情绪杠杆命中率排行 */}
        <div className={`${card} lg:col-span-7`} style={cardStyle}>
          <div className="flex items-baseline justify-between">
            <h3 className="h2 text-white">情绪杠杆 · 命中率排行</h3>
            <span className="tag text-slate-500">EMOTIONAL LEVER</span>
          </div>
          <div className="mt-5 space-y-2.5">
            {leverPerf.map((l) => {
              const isBest = l.lever === best.lever;
              const isMost = l.lever === mostUsed.lever;
              return (
                <div key={l.lever} className="grid grid-cols-[92px_1fr_64px] items-center gap-3">
                  <span className="mini truncate text-slate-300" title={l.lever}>{l.lever}</span>
                  <span className="relative h-2.5 overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,0.06)" }}>
                    <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${Math.max(2, (l.hit_rate / maxRate) * 100)}%`, background: isBest ? "#E8765A" : "rgba(232,118,90,0.5)" }} />
                  </span>
                  <span className="num text-right text-sm font-bold" style={{ color: isBest ? "#E8765A" : "#cbd5e1" }}>{l.hit_rate}%</span>
                  <span />
                  <span className="mini -mt-1 text-slate-600">
                    {comma(l.n)} 篇 · 均 {comma(l.avg_inter)} 互动
                    {isMost ? <span className="ml-2 rounded-full bg-white/10 px-2 py-0.5 text-[10px] text-slate-300">押注最多</span> : null}
                    {isBest ? <span className="ml-2 rounded-full px-2 py-0.5 text-[10px]" style={{ background: "rgba(232,118,90,0.18)", color: "#E8765A" }}>最高命中</span> : null}
                  </span>
                  <span />
                </div>
              );
            })}
          </div>
        </div>

        {/* 效价 × 强度 引擎矩阵 */}
        <div className={`${card} lg:col-span-5`} style={cardStyle}>
          <div className="flex items-baseline justify-between">
            <h3 className="h2 text-white">情绪引擎 · 效价 × 强度</h3>
            <span className="tag text-slate-500">ENGINE</span>
          </div>
          <p className="mini mt-1 text-slate-500">命中率热力 · 高亮 = 最强引擎</p>
          <div className="mt-5">
            <div className="grid grid-cols-[52px_1fr_1fr_1fr] gap-1.5">
              <span />
              {INT_ORDER.map((ii) => (
                <span key={ii} className="mini text-center text-slate-500">{INT[ii]}</span>
              ))}
              {VAL_ORDER.map((vv) => (
                <ValRow key={vv} vv={vv} valGet={valGet} valMax={valMax} top={valTop} />
              ))}
            </div>
            <div className="mt-4 text-sm" style={{ color: "#cbd5e1" }}>
              <span className="text-coral">{INT[valTop?.intensity ?? "high"]}{VAL[valTop?.valence ?? "negative"]}</span> 是最强引擎 ——
              命中 <span className="num font-bold text-coral">{valTop?.hit_rate}%</span> · 均 {comma(valTop?.avg_inter ?? 0)} 互动。
            </div>
          </div>
        </div>

        {/* 意图分野 */}
        <div className={`${card} lg:col-span-4`} style={cardStyle}>
          <h3 className="h2 text-white">意图分野</h3>
          <p className="mini mt-1 text-slate-500">种草出爆款,转化负责承接</p>
          <div className="mt-5 space-y-4">
            <IntentRow label="种草 · TRAFFIC" p={traffic} accent />
            <IntentRow label="转化 · CONVERSION" p={conversion} />
          </div>
        </div>

        {/* tier 漏斗 */}
        <div className={`${card} lg:col-span-4`} style={cardStyle}>
          <h3 className="h2 text-white">爆款漏斗 · 读完率抬升</h3>
          <p className="mini mt-1 text-slate-500">越往上,读完率越高、曝光指数级放大</p>
          <div className="mt-5 space-y-3">
            {fsorted.map((f) => (
              <div key={f.tier} className="grid grid-cols-[40px_1fr_78px] items-center gap-3">
                <span className="mini text-slate-300">{f.tier}</span>
                <span className="relative h-2.5 overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,0.06)" }}>
                  <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${Math.max(4, (f.read_rate / maxReadRate) * 100)}%`, background: f.tier === "大爆" || f.tier === "爆" ? "#E8765A" : "rgba(232,118,90,0.45)" }} />
                </span>
                <span className="num text-right text-xs text-slate-400">读完 {Math.round(f.read_rate * 100)}%</span>
                <span />
                <span className="mini -mt-1 text-slate-600">{f.n} 篇 · 均曝光 {cnShort(f.avg_imp)}</span>
                <span />
              </div>
            ))}
          </div>
        </div>

        {/* 人性原型 top */}
        <div className={`${card} lg:col-span-4`} style={cardStyle}>
          <h3 className="h2 text-white">人性原型 · Top 命中</h3>
          <p className="mini mt-1 text-slate-500">焦虑/冲突系胜出</p>
          <div className="mt-5 space-y-2">
            {topArche.map((a) => (
              <div key={a.archetype} className="grid grid-cols-[88px_1fr_44px] items-center gap-2.5">
                <span className="mini truncate text-slate-300" title={a.archetype}>{a.archetype}</span>
                <span className="relative h-2 overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,0.06)" }}>
                  <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${Math.max(3, (a.hit_rate / archeMax) * 100)}%`, background: "rgba(232,118,90,0.6)" }} />
                </span>
                <span className="num text-right text-xs font-bold text-slate-200">{a.hit_rate}%</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function ValRow({
  vv,
  valGet,
  valMax,
  top,
}: {
  vv: string;
  valGet: (vv: string, ii: string) => DashboardData["valence"][number] | undefined;
  valMax: number;
  top?: DashboardData["valence"][number];
}) {
  return (
    <>
      <span className="mini flex items-center justify-end pr-1 text-slate-400">{VAL[vv]}</span>
      {INT_ORDER.map((ii) => {
        const c = valGet(vv, ii);
        const rate = c?.hit_rate ?? 0;
        const isTop = top && c && top.valence === vv && top.intensity === ii;
        return (
          <div
            key={ii}
            className="relative flex h-12 items-center justify-center rounded-lg"
            style={{
              background: c ? `rgba(232,118,90,${0.08 + (rate / valMax) * 0.82})` : "rgba(255,255,255,0.03)",
              boxShadow: isTop ? "0 0 0 1.5px #fff" : "none",
            }}
            title={c ? `${VAL[vv]}·${INT[ii]}: ${rate}% (${c.n}篇)` : "—"}
          >
            {c ? (
              <span className="num text-sm font-bold" style={{ color: rate / valMax > 0.5 ? "#0a0a0f" : "#e2e8f0" }}>{rate}%</span>
            ) : (
              <span className="mini text-slate-600">—</span>
            )}
          </div>
        );
      })}
    </>
  );
}

function IntentRow({ label, p, accent = false }: { label: string; p?: DashboardData["intent"][number]; accent?: boolean }) {
  return (
    <div>
      <div className="tag text-slate-400">{label}</div>
      <div className="mt-1 flex items-baseline gap-3">
        <span className="num font-bold" style={{ fontSize: "clamp(28px,3vw,44px)", color: accent ? "#E8765A" : "#cbd5e1", letterSpacing: "-0.03em" }}>{p?.hit_rate ?? 0}%</span>
        <span className="mini text-slate-500">命中率 · {comma(p?.n ?? 0)} 篇</span>
      </div>
      <div className="mini mt-1 text-slate-600">读完率 {Math.round((p?.read_rate ?? 0) * 100)}% · 互动率 {((p?.inter_rate ?? 0) * 100).toFixed(1)}%</div>
    </div>
  );
}

function cnShort(n: number): string {
  if (n >= 1e4) return (n / 1e4).toFixed(n >= 1e5 ? 0 : 1) + "万";
  return comma(n);
}
