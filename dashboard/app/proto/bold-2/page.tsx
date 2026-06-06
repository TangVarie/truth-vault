import Link from "next/link";
import type { Metadata } from "next";
import { cnNum, comma, PROJECT_LABEL } from "@/config/showcase";
import { getProtoData, growthSeries, areaPath } from "@/lib/proto";
import ProtoBack from "@/components/ProtoBack";
import CountUp from "@/components/CountUp";

export const metadata: Metadata = { robots: { index: false, follow: false }, title: "BOLD BLOCKS 融合版 · 原型" };
export const dynamic = "force-dynamic";

const BG = "#0A0A0B";
const PANEL = "#141416";
const BORD = "rgba(255,255,255,0.08)";
const SAGE = "#DDE6D6";
const OLIVE = "#B0A41C";
const LAV = "#BFB9E6";
const CORAL = "#F2542D";
const LIME = "#C6F24E";
const INKC = "#0E0E0E";
const MUTE = "#8A8F98";
const sans = "var(--font-geist-sans)";
const mono = "var(--font-geist-mono)";

// 12 栅格 bento + 响应式 + 动效
const css = `
.b2-wrap{max-width:1280px;margin:0 auto;padding:18px 20px 64px}
.b2-grid{display:grid;grid-template-columns:repeat(12,1fr);gap:16px;align-items:stretch}
.b2-grid>*{min-width:0}
.s12{grid-column:span 12}.s8{grid-column:span 8}.s7{grid-column:span 7}.s5{grid-column:span 5}.s4{grid-column:span 4}.s3{grid-column:span 3}.s2{grid-column:span 2}
.card{border-radius:28px;padding:24px 26px;display:flex;flex-direction:column}
.tile{background:${PANEL};border:1px solid ${BORD};border-radius:18px;padding:14px 16px}
@media(max-width:920px){.b2-grid{grid-template-columns:repeat(6,1fr)}.s8,.s7{grid-column:span 6}.s5,.s4,.s3{grid-column:span 3}.s2{grid-column:span 2}}
@media(max-width:560px){.b2-grid{grid-template-columns:repeat(2,1fr);gap:12px}.s12,.s8,.s7,.s5,.s4,.s3,.s2{grid-column:span 2}.card{padding:20px}}
@keyframes b2-grow{from{transform:scaleY(0)}to{transform:scaleY(1)}}
@keyframes b2-pulse{0%,100%{opacity:.4;transform:scale(.85)}50%{opacity:1;transform:scale(1.2)}}
@keyframes b2-breathe{0%,100%{opacity:.65}50%{opacity:1}}
@keyframes b2-marq{0%{transform:translateX(0)}100%{transform:translateX(-50%)}}
.b2-bar{transform-origin:bottom;animation:b2-grow .9s cubic-bezier(.22,1,.36,1) both}
.b2-dot{animation:b2-pulse 1.8s ease-in-out infinite}
.b2-streams{animation:b2-breathe 6s ease-in-out infinite}
`;

function streamPaths(n: number, W: number, H: number) {
  const fx = W * 0.5, fy = H * 1.04;
  const lines: string[] = [];
  const topY = (t: number) => H * 0.16 + Math.sin(t * 9) * H * 0.06 + Math.cos(t * 17) * H * 0.025;
  for (let i = 0; i < n; i++) {
    const t = i / (n - 1);
    const x = t * W, y0 = topY(t);
    const c1x = x, c1y = y0 + H * 0.34, c2x = fx + (x - fx) * 0.14, c2y = fy - H * 0.4;
    lines.push(`M ${x.toFixed(1)} ${y0.toFixed(1)} C ${c1x.toFixed(1)} ${c1y.toFixed(1)}, ${c2x.toFixed(1)} ${c2y.toFixed(1)}, ${fx.toFixed(1)} ${fy.toFixed(1)}`);
  }
  return lines;
}

function Pill({ children, dark = false }: { children: React.ReactNode; dark?: boolean }) {
  return <span style={{ display: "inline-flex", alignItems: "center", gap: 7, border: `1.5px solid ${dark ? "rgba(255,255,255,0.22)" : "rgba(0,0,0,0.45)"}`, color: dark ? "#fff" : INKC, borderRadius: 999, padding: "6px 14px", fontSize: 12.5, fontWeight: 600, alignSelf: "flex-start" }}>{children}</span>;
}

export default async function Bold2() {
  const d = await getProtoData();
  const bars = growthSeries(28);
  const barMax = Math.max(...bars);
  const spark = areaPath(growthSeries(14), 100, 30, 2).line;
  const streams = streamPaths(72, 440, 360);
  const gaugeFrac = Math.min(d.hitRate / 10, 1);
  const C = 2 * Math.PI * 52;
  const heat = Array.from({ length: 35 }, (_, i) => (Math.sin(i * 2.3) + Math.cos(i * 1.7) + 2) / 4);
  const tiles = [
    { k: "曝光", v: d.impressions, fmt: "cn" as const, up: "+12.4%" },
    { k: "资产", v: d.notes, fmt: "comma" as const, up: "+3.1%" },
    { k: "爆款", v: d.baokuan, fmt: "comma" as const, up: "+5" },
    { k: "经验卡", v: d.cards, fmt: "comma" as const, up: "+2" },
    { k: "内核", v: d.essence, fmt: "comma" as const, up: "" },
    { k: "受众维度", v: d.audiences, fmt: "comma" as const, up: "" },
  ];
  const status = [
    { t: "飞书投放表", s: `${comma(d.notes)} 接入`, c: LIME, live: true },
    { t: "ssll 回流", s: "97 条", c: LIME, live: true },
    { t: "指标快照", s: "06-06 实时", c: LIME, live: true },
    { t: "autowriter", s: "待流", c: "#F5A623", live: false },
  ];

  return (
    <main style={{ minHeight: "100vh", background: BG, color: "#fff", fontFamily: sans }}>
      <style dangerouslySetInnerHTML={{ __html: css }} />
      <ProtoBack />
      <div className="b2-wrap">
        {/* nav */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ fontWeight: 800, fontSize: 18, letterSpacing: "-0.01em" }}>BYWOOD <span style={{ color: "#6b7280" }}>· ROC</span></span>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 12, color: LIME, border: `1px solid ${BORD}`, borderRadius: 999, padding: "5px 12px" }}><span className="b2-dot" style={{ width: 7, height: 7, borderRadius: 99, background: LIME, boxShadow: `0 0 10px ${LIME}` }} />LIVE · 更新于 06-06 06:46</span>
          </div>
          <div style={{ display: "flex", gap: 8 }}>{["数据看板", "战线", "EN"].map((t) => <span key={t} style={{ border: "1.5px solid rgba(255,255,255,0.22)", borderRadius: 999, padding: "6px 14px", fontSize: 12.5, fontWeight: 600 }}>{t}</span>)}</div>
        </div>

        <div className="b2-grid">
          {/* ── 行1:主导 hero(s8) + 汇聚流(s4,等高拉伸)── */}
          <section className="s8 card" style={{ background: SAGE, color: INKC, justifyContent: "space-between" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <Pill>增长态势</Pill>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: 12, fontWeight: 600 }}>实时回流<span style={{ display: "inline-flex", alignItems: "center", background: INKC, color: "#fff", borderRadius: 999, padding: "3px 5px", gap: 5 }}>OFF<span style={{ background: LIME, color: INKC, borderRadius: 999, padding: "2px 8px" }}>ON</span></span></span>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-end", justifyContent: "space-between", gap: 24, marginTop: 28 }}>
              <div style={{ flex: "1 1 220px", maxWidth: 320 }}>
                {[{ k: "本周", w: 62 }, { k: "本月", w: 84 }, { k: "全年", w: 73 }].map((p) => (
                  <div key={p.k} style={{ marginBottom: 14 }}>
                    <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 6 }}>{p.k}</div>
                    <div style={{ height: 6, background: "rgba(14,14,14,0.12)", borderRadius: 999 }}><div style={{ width: `${p.w}%`, height: "100%", background: INKC, borderRadius: 999 }} /></div>
                  </div>
                ))}
              </div>
              <div style={{ textAlign: "right" }}>
                <div style={{ fontWeight: 800, letterSpacing: "-0.045em", lineHeight: 0.84, fontSize: "clamp(52px,7.5vw,128px)" }}><CountUp value={d.impressions} format="cn" duration={2200} /></div>
                <div style={{ fontSize: 13, fontWeight: 600, opacity: 0.66, marginTop: 6 }}>累计内容曝光 · 跨 {d.projects} 条战线</div>
              </div>
            </div>
          </section>

          <section className="s4 card" style={{ background: "#0E0F12", border: `1px solid ${BORD}`, padding: "20px 22px", overflow: "hidden" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><Pill dark>全域数据汇聚</Pill><span style={{ fontSize: 11, color: CORAL, fontFamily: mono }}>● 实时</span></div>
            <div style={{ position: "relative", flex: 1, minHeight: 200, marginTop: 10 }}>
              <svg viewBox="0 0 440 360" width="100%" height="100%" preserveAspectRatio="none" className="b2-streams" style={{ position: "absolute", inset: 0 }}>
                <defs><linearGradient id="b2-st" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#F4A65C" stopOpacity="0" /><stop offset="35%" stopColor="#F4A65C" stopOpacity="0.5" /><stop offset="100%" stopColor="#F2542D" stopOpacity="0.92" /></linearGradient></defs>
                {streams.map((p, i) => <path key={i} d={p} fill="none" stroke="url(#b2-st)" strokeWidth="0.8" opacity="0.5" />)}
              </svg>
              <div style={{ position: "absolute", left: 0, bottom: 0 }}><div style={{ fontSize: 30, fontWeight: 800, letterSpacing: "-0.03em" }}>{comma(d.notes)}</div><div style={{ fontSize: 11, color: MUTE, fontFamily: mono }}>内容资产 → 收束 {comma(d.baokuan)} 爆款</div></div>
            </div>
          </section>

          {/* ── 行2:KPI 瓦片 ×6(s2 each)── */}
          {tiles.map((t) => (
            <div key={t.k} className="s2 tile">
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: MUTE, fontFamily: mono, letterSpacing: "0.06em" }}><span>{t.k}</span>{t.up ? <span style={{ color: LIME }}>▲{t.up}</span> : null}</div>
              <div style={{ fontSize: 25, fontWeight: 800, letterSpacing: "-0.03em", marginTop: 7 }}><CountUp value={t.v} format={t.fmt} duration={1500} /></div>
              <svg viewBox="0 0 100 30" width="100%" height="20" preserveAspectRatio="none" style={{ marginTop: 6 }}><path d={spark} fill="none" stroke={LIME} strokeWidth="1.5" opacity="0.8" /></svg>
            </div>
          ))}

          {/* ── 行3:增长(s5) · 命中仪表(s3) · 活动热力(s4)── */}
          <section className="s5 card" style={{ background: OLIVE, color: INKC, justifyContent: "space-between" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><Pill>增长 Growth</Pill><span style={{ display: "inline-flex", background: INKC, borderRadius: 999, padding: 3 }}><span style={{ color: "rgba(255,255,255,0.6)", fontSize: 11, padding: "3px 9px" }}>周</span><span style={{ background: "#fff", color: INKC, borderRadius: 999, fontSize: 11, fontWeight: 700, padding: "3px 9px" }}>日</span></span></div>
            <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 130, marginTop: 22 }}>{bars.map((v, i) => <div key={i} className="b2-bar" style={{ flex: 1, height: `${Math.max(4, (v / barMax) * 130)}px`, background: INKC, borderRadius: 2, animationDelay: `${i * 0.02}s` }} />)}</div>
          </section>

          <section className="s3 card" style={{ background: LAV, color: INKC, justifyContent: "space-between" }}>
            <Pill>命中 Engagement</Pill>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", marginTop: 12 }}>
              <svg width="150" height="150" viewBox="0 0 124 124">
                <circle cx="62" cy="62" r="52" fill="none" stroke="rgba(14,14,14,0.14)" strokeWidth="13" />
                <circle cx="62" cy="62" r="52" fill="none" stroke={INKC} strokeWidth="13" strokeLinecap="round" transform="rotate(-90 62 62)" style={{ strokeDasharray: `${(gaugeFrac * C).toFixed(1)} ${C.toFixed(1)}` }} />
                <text x="62" y="58" textAnchor="middle" style={{ fontSize: 30, fontWeight: 800, fill: INKC, fontFamily: sans }}>{d.hitRate}%</text>
                <text x="62" y="76" textAnchor="middle" style={{ fontSize: 9, fill: "rgba(14,14,14,0.6)", fontFamily: mono, letterSpacing: "0.1em" }}>命中率</text>
              </svg>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, fontWeight: 600 }}><span>爆款 {comma(d.baokuan)}</span><span style={{ opacity: 0.6 }}>解析 {comma(d.essence)}</span></div>
          </section>

          <section className="s4 card" style={{ background: CORAL, color: INKC, justifyContent: "space-between" }}>
            <Pill>活动热力</Pill>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(7,1fr)", gap: 6, marginTop: 16 }}>{heat.map((v, i) => <div key={i} style={{ aspectRatio: "1", borderRadius: 6, background: `rgba(14,14,14,${(0.1 + v * 0.74).toFixed(2)})` }} />)}</div>
            <div style={{ fontSize: 12, fontWeight: 600, marginTop: 14, opacity: 0.8 }}>近 5 周投放 · 越深越密</div>
          </section>

          {/* ── 行4:Top 爆款表(s7) + 分战线列表(s5)── */}
          <section className="s7 tile" style={{ padding: "18px 20px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}><Pill dark>Top 爆款 · 明细</Pill><span style={{ fontSize: 11, color: MUTE, fontFamily: mono }}>共 {comma(d.baokuan)} 条</span></div>
            <div style={{ display: "grid", gridTemplateColumns: "40px 1fr 96px 110px 60px", gap: 10, fontSize: 10.5, color: MUTE, fontFamily: mono, letterSpacing: "0.08em", textTransform: "uppercase", paddingBottom: 8, borderBottom: `1px solid ${BORD}` }}><span>#</span><span>战线</span><span style={{ textAlign: "right" }}>互动</span><span style={{ textAlign: "right" }}>曝光</span><span style={{ textAlign: "right" }}>态</span></div>
            {d.hits.map((h) => (
              <div key={h.rank} style={{ display: "grid", gridTemplateColumns: "40px 1fr 96px 110px 60px", gap: 10, alignItems: "center", padding: "10px 0", borderBottom: `1px solid ${BORD}`, fontSize: 14 }}>
                <span style={{ fontWeight: 800, color: h.rank === 1 ? CORAL : "#fff" }}>{h.rank}</span>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{PROJECT_LABEL[h.project_id] ?? h.project_id}</span>
                <span style={{ textAlign: "right", fontFamily: mono }}>{comma(h.interactions)}</span>
                <span style={{ textAlign: "right", fontFamily: mono, color: CORAL }}>{cnNum(h.impressions)}</span>
                <span style={{ textAlign: "right" }}><span style={{ fontSize: 11, fontWeight: 700, color: LIME, border: `1px solid ${LIME}66`, borderRadius: 999, padding: "2px 8px" }}>爆</span></span>
              </div>
            ))}
          </section>

          <section className="s5 tile" style={{ padding: "18px 20px", justifyContent: "space-between" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}><Pill dark>分战线 · Fronts</Pill><Link href="/console" style={{ fontSize: 12, color: LIME, textDecoration: "none", fontWeight: 600 }}>座舱 →</Link></div>
            {d.byProject.map((p, i) => {
              const op = [1, 0.74, 0.5, 0.36, 0.3][i] ?? 0.3;
              return (
                <div key={p.id} style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 14, padding: "9px 0", borderTop: i ? `1px solid ${BORD}` : "none", opacity: op }}>
                  <span style={{ fontWeight: 700, letterSpacing: "-0.02em", fontSize: "clamp(20px,2.2vw,32px)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{PROJECT_LABEL[p.id] ?? p.id}</span>
                  <span style={{ fontWeight: 700, letterSpacing: "-0.02em", fontSize: "clamp(18px,2vw,28px)", whiteSpace: "nowrap" }}>{cnNum(p.impressions)}</span>
                </div>
              );
            })}
          </section>

          {/* ── 行5:接口状态 ×4(s3 each)── */}
          {status.map((s) => (
            <div key={s.t} className="s3 tile" style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span className={s.live ? "b2-dot" : undefined} style={{ width: 9, height: 9, borderRadius: 99, background: s.c, boxShadow: s.live ? `0 0 10px ${s.c}` : "none", flexShrink: 0 }} />
              <div style={{ minWidth: 0 }}><div style={{ fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.t}</div><div style={{ fontSize: 11, color: MUTE, fontFamily: mono }}>{s.s}</div></div>
            </div>
          ))}

          {/* ── 跑马灯(s12)── */}
          <section className="s12 tile" style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ display: "flex", width: "max-content", animation: "b2-marq 26s linear infinite", fontSize: 11.5, color: MUTE, fontFamily: mono, padding: "10px 0" }}>
              {[0, 1].map((r) => <div key={r} style={{ display: "flex", gap: 26, paddingLeft: 26 }}><span style={{ color: LIME }}>● SYNC OK</span><span>累计曝光 {cnNum(d.impressions)}</span><span>命中率 {d.hitRate}%</span><span>{comma(d.baokuan)} 验证级爆款</span><span style={{ color: LIME }}>ssll 97 回流</span><span style={{ color: "#F5A623" }}>autowriter 待流</span><span>essence {comma(d.essence)}/{comma(d.notes)}</span></div>)}
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
