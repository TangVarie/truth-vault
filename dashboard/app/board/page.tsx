import Link from "next/link";
import { Fragment } from "react";
import type { Metadata } from "next";
import { cnNum, comma, PROJECT_LABEL } from "@/config/showcase";
import { getDashboardData } from "@/lib/dashboard-data";
import { areaPath } from "@/lib/proto";
import CountUp from "@/components/CountUp";

/**
 * /board = 对外数据看板(公开、只读)。BOLD BLOCKS 设计体系 · 全部真实数据。
 * 只露体量/结果(曝光/资产/爆款/命中率/月度趋势/投放热力/Top 爆款),无任何策略机理。
 */
export const metadata: Metadata = { title: "数据看板 · BYWOOD", description: "真实投放结果速览" };
export const dynamic = "force-dynamic";

const BG = "#0A0A0B", PANEL = "#141416", BORD = "rgba(255,255,255,0.08)";
const SAGE = "#DDE6D6", OLIVE = "#B0A41C", LAV = "#BFB9E6", CORAL = "#F2542D", LIME = "#C6F24E", INKC = "#0E0E0E", MUTE = "#8A8F98";
const sans = "var(--font-geist-sans)", mono = "var(--font-geist-mono)";

const css = `
.bb-wrap{max-width:1280px;margin:0 auto;padding:18px 20px 64px}
.bb-grid{display:grid;grid-template-columns:repeat(12,1fr);gap:16px;align-items:stretch}
.bb-grid>*{min-width:0}
.s12{grid-column:span 12}.s8{grid-column:span 8}.s7{grid-column:span 7}.s5{grid-column:span 5}.s4{grid-column:span 4}.s3{grid-column:span 3}.s2{grid-column:span 2}
.bb-card{border-radius:28px;padding:24px 26px;display:flex;flex-direction:column}
.bb-tile{background:${PANEL};border:1px solid ${BORD};border-radius:18px;padding:14px 16px}
@media(max-width:920px){.bb-grid{grid-template-columns:repeat(6,1fr)}.s8,.s7{grid-column:span 6}.s5,.s4,.s3{grid-column:span 3}.s2{grid-column:span 2}}
@media(max-width:560px){.bb-grid{grid-template-columns:repeat(2,1fr);gap:12px}.s12,.s8,.s7,.s5,.s4,.s3,.s2{grid-column:span 2}.bb-card{padding:20px}}
@keyframes bb-grow{from{transform:scaleY(0)}to{transform:scaleY(1)}}
@keyframes bb-pulse{0%,100%{opacity:.4;transform:scale(.85)}50%{opacity:1;transform:scale(1.2)}}
@keyframes bb-breathe{0%,100%{opacity:.65}50%{opacity:1}}
@keyframes bb-marq{0%{transform:translateX(0)}100%{transform:translateX(-50%)}}
.bb-bar{transform-origin:bottom;animation:bb-grow .9s cubic-bezier(.22,1,.36,1) both}
.bb-dot{animation:bb-pulse 1.8s ease-in-out infinite}
.bb-streams{animation:bb-breathe 6s ease-in-out infinite}
`;

function streamPaths(n: number, W: number, H: number) {
  const fx = W * 0.5, fy = H * 1.04, top = (t: number) => H * 0.16 + Math.sin(t * 9) * H * 0.06 + Math.cos(t * 17) * H * 0.025;
  return Array.from({ length: n }, (_, i) => {
    const t = i / (n - 1), x = t * W, y0 = top(t);
    return `M ${x.toFixed(1)} ${y0.toFixed(1)} C ${x.toFixed(1)} ${(y0 + H * 0.34).toFixed(1)}, ${(fx + (x - fx) * 0.14).toFixed(1)} ${(fy - H * 0.4).toFixed(1)}, ${fx.toFixed(1)} ${fy.toFixed(1)}`;
  });
}
function Pill({ children, dark = false }: { children: React.ReactNode; dark?: boolean }) {
  return <span style={{ display: "inline-flex", alignItems: "center", gap: 7, border: `1.5px solid ${dark ? "rgba(255,255,255,0.22)" : "rgba(0,0,0,0.45)"}`, color: dark ? "#fff" : INKC, borderRadius: 999, padding: "6px 14px", fontSize: 12.5, fontWeight: 600, alignSelf: "flex-start" }}>{children}</span>;
}
function tsFmt(s: string | null | undefined): string {
  if (!s) return "—";
  const [date = "", time = ""] = s.replace("T", " ").split(/[ .]/);
  return date.length >= 10 && time.length >= 5 ? `${date.slice(5)} ${time.slice(0, 5)}` : "—";
}
const DOW = ["一", "二", "三", "四", "五", "六", "日"];

export default async function BoardPage() {
  const { o, projects, hits, monthly, activity, pulse } = await getDashboardData();
  const hitRate = o.notes ? Math.round((o.baokuanReal / o.notes) * 1000) / 10 : 0;
  const totalImp = projects.reduce((s, p) => s + p.impressions, 0) || 1;
  const topFronts = [...projects].sort((a, b) => b.impressions - a.impressions).slice(0, 3).map((p) => ({ name: PROJECT_LABEL[p.project_id] ?? p.project_id, pct: Math.round((p.impressions / totalImp) * 100) }));
  const mNotesMax = Math.max(...monthly.map((m) => m.notes), 1);
  const maxCum = Math.max(...monthly.map((m) => m.cum_impressions), 1);
  const cumLine = monthly.length > 1 ? areaPath(monthly.map((m) => m.cum_impressions / maxCum), 900, 120, 4) : { line: "", area: "" };
  const streams = streamPaths(72, 440, 360);
  const C = 2 * Math.PI * 52;
  const gaugeFrac = Math.min(hitRate / 10, 1);
  const actMax = Math.max(...activity.map((a) => a.n), 1);
  const actMap = new Map(activity.map((a) => [`${a.ym}-${a.dow}`, a.n]));
  const months = monthly.map((m) => m.ym);
  const tiles = [
    { k: "累计曝光", v: o.impressions, fmt: "cn" as const, sub: `跨 ${o.projects} 条战线` },
    { k: "内容资产", v: o.notes, fmt: "comma" as const, sub: "已发布" },
    { k: "验证级爆款", v: o.baokuanReal, fmt: "comma" as const, sub: `命中率 ${hitRate}%` },
    { k: "策略经验卡", v: o.cards, fmt: "comma" as const, sub: "已沉淀" },
    { k: "结构化内核", v: o.essence, fmt: "comma" as const, sub: "AI 解析" },
    { k: "受众维度", v: o.audiences, fmt: "comma" as const, sub: "画像维度" },
  ];

  return (
    <main style={{ minHeight: "100vh", background: BG, color: "#fff", fontFamily: sans }}>
      <style dangerouslySetInnerHTML={{ __html: css }} />
      <div className="bb-wrap">
        {/* nav */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <Link href="/" style={{ fontWeight: 800, fontSize: 18, letterSpacing: "-0.01em", color: "#fff", textDecoration: "none" }}>BYWOOD <span style={{ color: "#6b7280" }}>· ROC</span></Link>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 12, color: LIME, border: `1px solid ${BORD}`, borderRadius: 999, padding: "5px 12px" }}><span className="bb-dot" style={{ width: 7, height: 7, borderRadius: 99, background: LIME, boxShadow: `0 0 10px ${LIME}` }} />LIVE · 更新于 {tsFmt(pulse?.last_update)}</span>
          </div>
          <div style={{ display: "flex", gap: 8 }}><span style={{ border: "1.5px solid rgba(255,255,255,0.22)", borderRadius: 999, padding: "6px 14px", fontSize: 12.5, fontWeight: 600 }}>数据看板</span><Link href="/console" style={{ border: "1.5px solid rgba(255,255,255,0.22)", borderRadius: 999, padding: "6px 14px", fontSize: 12.5, fontWeight: 600, color: "#fff", textDecoration: "none" }}>团队登录</Link></div>
        </div>

        <div className="bb-grid">
          {/* hero (s8) + streams (s4) */}
          <section className="s8 bb-card" style={{ background: SAGE, color: INKC, justifyContent: "space-between" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><Pill>真实投放结果 · 可查证</Pill><span style={{ fontSize: 12, fontWeight: 600, opacity: 0.6 }}>{months[0]?.replace("-", ".")} – {months[months.length - 1]?.replace("-", ".")}</span></div>
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-end", justifyContent: "space-between", gap: 24, marginTop: 24 }}>
              <div style={{ flex: "1 1 240px", maxWidth: 340 }}>
                {topFronts.map((f) => (
                  <div key={f.name} style={{ marginBottom: 13 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13.5, fontWeight: 600, marginBottom: 5 }}><span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.name}</span><span>{f.pct}%</span></div>
                    <div style={{ height: 6, background: "rgba(14,14,14,0.12)", borderRadius: 999 }}><div style={{ width: `${Math.max(3, f.pct)}%`, height: "100%", background: INKC, borderRadius: 999 }} /></div>
                  </div>
                ))}
                <div style={{ fontSize: 11.5, opacity: 0.55, marginTop: 2 }}>头部战线曝光占比</div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div style={{ fontWeight: 800, letterSpacing: "-0.045em", lineHeight: 0.84, fontSize: "clamp(52px,7.5vw,128px)" }}><CountUp value={o.impressions} format="cn" duration={2200} /></div>
                <div style={{ fontSize: 13, fontWeight: 600, opacity: 0.66, marginTop: 6 }}>累计内容曝光 · CUMULATIVE IMPRESSIONS</div>
              </div>
            </div>
          </section>

          <section className="s4 bb-card" style={{ background: "#0E0F12", border: `1px solid ${BORD}`, padding: "20px 22px", overflow: "hidden" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><Pill dark>全域数据汇聚</Pill><span style={{ fontSize: 11, color: CORAL, fontFamily: mono }}>● 实时</span></div>
            <div style={{ position: "relative", flex: 1, minHeight: 200, marginTop: 10 }}>
              <svg viewBox="0 0 440 360" width="100%" height="100%" preserveAspectRatio="none" className="bb-streams" style={{ position: "absolute", inset: 0 }}>
                <defs><linearGradient id="bb-st" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#F4A65C" stopOpacity="0" /><stop offset="35%" stopColor="#F4A65C" stopOpacity="0.5" /><stop offset="100%" stopColor="#F2542D" stopOpacity="0.92" /></linearGradient></defs>
                {streams.map((p, i) => <path key={i} d={p} fill="none" stroke="url(#bb-st)" strokeWidth="0.8" opacity="0.5" />)}
              </svg>
              <div style={{ position: "absolute", left: 0, bottom: 0 }}><div style={{ fontSize: 30, fontWeight: 800, letterSpacing: "-0.03em" }}>{comma(o.notes)}</div><div style={{ fontSize: 11, color: MUTE, fontFamily: mono }}>内容资产 → 收束 {comma(o.baokuanReal)} 爆款</div></div>
            </div>
          </section>

          {/* KPI tiles ×6 */}
          {tiles.map((t) => (
            <div key={t.k} className="s2 bb-tile">
              <div style={{ fontSize: 11, color: MUTE, fontFamily: mono, letterSpacing: "0.06em" }}>{t.k}</div>
              <div style={{ fontSize: 25, fontWeight: 800, letterSpacing: "-0.03em", marginTop: 7 }}><CountUp value={t.v} format={t.fmt} duration={1500} /></div>
              <div style={{ fontSize: 11, color: MUTE, marginTop: 4 }}>{t.sub}</div>
            </div>
          ))}

          {/* monthly bars (s5) + gauge (s3) + heatmap (s4) */}
          <section className="s5 bb-card" style={{ background: OLIVE, color: INKC, justifyContent: "space-between" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><Pill>月度发布量</Pill><span style={{ fontSize: 11.5, fontWeight: 600, opacity: 0.6 }}>{monthly.length} 个月</span></div>
            <div style={{ display: "flex", alignItems: "flex-end", gap: 8, height: 140, marginTop: 20 }}>
              {monthly.map((m, i) => (
                <div key={m.ym} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "flex-end", height: "100%" }}>
                  <div style={{ fontSize: 10, fontWeight: 700, marginBottom: 4, fontFamily: mono }}>{m.notes}</div>
                  <div className="bb-bar" style={{ width: "70%", maxWidth: 26, height: `${Math.max(4, (m.notes / mNotesMax) * 104)}px`, background: INKC, borderRadius: 3, animationDelay: `${i * 0.05}s` }} />
                  <div style={{ fontSize: 9.5, color: "rgba(14,14,14,0.6)", marginTop: 6, fontFamily: mono }}>{m.ym.slice(2)}</div>
                </div>
              ))}
            </div>
          </section>

          <section className="s3 bb-card" style={{ background: LAV, color: INKC, justifyContent: "space-between" }}>
            <Pill>命中率</Pill>
            <div style={{ display: "flex", justifyContent: "center", marginTop: 10 }}>
              <svg width="150" height="150" viewBox="0 0 124 124">
                <circle cx="62" cy="62" r="52" fill="none" stroke="rgba(14,14,14,0.14)" strokeWidth="13" />
                <circle cx="62" cy="62" r="52" fill="none" stroke={INKC} strokeWidth="13" strokeLinecap="round" transform="rotate(-90 62 62)" style={{ strokeDasharray: `${(gaugeFrac * C).toFixed(1)} ${C.toFixed(1)}` }} />
                <text x="62" y="58" textAnchor="middle" style={{ fontSize: 30, fontWeight: 800, fill: INKC, fontFamily: sans }}>{hitRate}%</text>
                <text x="62" y="76" textAnchor="middle" style={{ fontSize: 9, fill: "rgba(14,14,14,0.6)", fontFamily: mono, letterSpacing: "0.1em" }}>验证级</text>
              </svg>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, fontWeight: 600 }}><span>爆款 {comma(o.baokuanReal)}</span><span style={{ opacity: 0.6 }}>解析 {comma(o.essence)}</span></div>
          </section>

          <section className="s4 bb-card" style={{ background: CORAL, color: INKC, justifyContent: "space-between" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><Pill>投放热力</Pill><span style={{ fontSize: 11, fontWeight: 600, opacity: 0.7 }}>月 × 周几</span></div>
            <div style={{ marginTop: 14 }}>
              <div style={{ display: "grid", gridTemplateColumns: "34px repeat(7,1fr)", gap: 4, alignItems: "center" }}>
                <span />{DOW.map((dn) => <span key={dn} style={{ fontSize: 9, textAlign: "center", opacity: 0.6, fontFamily: mono }}>{dn}</span>)}
                {months.map((ym) => (
                  <Fragment key={ym}>
                    <span style={{ fontSize: 9.5, fontFamily: mono, opacity: 0.7 }}>{ym.slice(2)}</span>
                    {[1, 2, 3, 4, 5, 6, 7].map((dw) => {
                      const v = (actMap.get(`${ym}-${dw}`) ?? 0) / actMax;
                      return <span key={ym + dw} style={{ aspectRatio: "1", borderRadius: 4, background: `rgba(14,14,14,${(0.08 + v * 0.78).toFixed(2)})` }} />;
                    })}
                  </Fragment>
                ))}
              </div>
            </div>
            <div style={{ fontSize: 11.5, fontWeight: 600, marginTop: 12, opacity: 0.75 }}>工作日为主 · 越深越密</div>
          </section>

          {/* cumulative curve (s12) */}
          <section className="s12 bb-tile" style={{ padding: "18px 22px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><Pill dark>累计曝光 · 真实轨迹</Pill><span style={{ fontSize: 12, color: CORAL, fontFamily: mono }}>{cnNum(o.impressions)}</span></div>
            <svg viewBox="0 0 900 120" width="100%" height="110" preserveAspectRatio="none" style={{ marginTop: 10 }}>
              <path d={cumLine.area} fill={CORAL} fillOpacity="0.08" /><path d={cumLine.line} fill="none" stroke={CORAL} strokeWidth="2" />
            </svg>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: MUTE, fontFamily: mono, marginTop: 2 }}><span>{months[0]?.replace("-", ".")}</span><span>{months[months.length - 1]?.replace("-", ".")}</span></div>
          </section>

          {/* top hits table (s7) + fronts list (s5) */}
          <section className="s7 bb-tile" style={{ padding: "18px 20px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}><Pill dark>Top 爆款 · 明细</Pill><span style={{ fontSize: 11, color: MUTE, fontFamily: mono }}>共 {comma(o.baokuanReal)} 条</span></div>
            <div style={{ display: "grid", gridTemplateColumns: "40px 1fr 96px 110px 56px", gap: 10, fontSize: 10.5, color: MUTE, fontFamily: mono, letterSpacing: "0.08em", paddingBottom: 8, borderBottom: `1px solid ${BORD}` }}><span>#</span><span>战线</span><span style={{ textAlign: "right" }}>互动</span><span style={{ textAlign: "right" }}>曝光</span><span style={{ textAlign: "right" }}>态</span></div>
            {hits.slice(0, 6).map((h, i) => (
              <div key={i} style={{ display: "grid", gridTemplateColumns: "40px 1fr 96px 110px 56px", gap: 10, alignItems: "center", padding: "10px 0", borderBottom: `1px solid ${BORD}`, fontSize: 14 }}>
                <span style={{ fontWeight: 800, color: h.rank === 1 ? CORAL : "#fff" }}>{h.rank}</span>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{PROJECT_LABEL[h.project_id] ?? h.project_id}</span>
                <span style={{ textAlign: "right", fontFamily: mono }}>{comma(h.interactions)}</span>
                <span style={{ textAlign: "right", fontFamily: mono, color: CORAL }}>{cnNum(h.impressions)}</span>
                <span style={{ textAlign: "right" }}><span style={{ fontSize: 11, fontWeight: 700, color: LIME, border: `1px solid ${LIME}66`, borderRadius: 999, padding: "2px 8px" }}>爆</span></span>
              </div>
            ))}
          </section>

          <section className="s5 bb-tile" style={{ padding: "18px 20px", justifyContent: "space-between" }}>
            <Pill dark>分战线 · Fronts</Pill>
            {[...projects].sort((a, b) => b.impressions - a.impressions).map((p, i) => {
              const op = [1, 0.74, 0.5, 0.36, 0.3][i] ?? 0.3;
              return (
                <div key={p.project_id} style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 14, padding: "9px 0", borderTop: i ? `1px solid ${BORD}` : "none", opacity: op }}>
                  <span style={{ fontWeight: 700, letterSpacing: "-0.02em", fontSize: "clamp(20px,2.2vw,32px)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{PROJECT_LABEL[p.project_id] ?? p.project_id}</span>
                  <span style={{ fontWeight: 700, letterSpacing: "-0.02em", fontSize: "clamp(18px,2vw,28px)", whiteSpace: "nowrap" }}>{cnNum(p.impressions)}</span>
                </div>
              );
            })}
          </section>

          {/* marquee (s12) */}
          <section className="s12 bb-tile" style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ display: "flex", width: "max-content", animation: "bb-marq 28s linear infinite", fontSize: 11.5, color: MUTE, fontFamily: mono, padding: "10px 0" }}>
              {[0, 1].map((r) => <div key={r} style={{ display: "flex", gap: 26, paddingLeft: 26 }}><span style={{ color: LIME }}>● 数据实时直连</span><span>累计曝光 {cnNum(o.impressions)}</span><span>命中率 {hitRate}%</span><span>{comma(o.baokuanReal)} 验证级爆款</span><span>{comma(o.notes)} 内容资产</span><span>{o.projects} 条战线</span><span>{comma(o.essence)} 结构化内核</span></div>)}
            </div>
          </section>
        </div>

        <footer style={{ marginTop: 28, display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8, fontSize: 11, color: "#5b606b" }}>
          <span>BYWOOD · ROC 增长智能中台 · 公开数据看板</span><span>数据实时直连 · 结果可查证</span>
        </footer>
      </div>
    </main>
  );
}
