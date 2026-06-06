import Link from "next/link";
import type { Metadata } from "next";
import { cnNum, comma, PROJECT_LABEL } from "@/config/showcase";
import { getProtoData, growthSeries } from "@/lib/proto";
import ProtoBack from "@/components/ProtoBack";
import CountUp from "@/components/CountUp";

export const metadata: Metadata = { robots: { index: false, follow: false }, title: "BOLD BLOCKS · 原型" };
export const dynamic = "force-dynamic";

const BG = "#0A0A0B";
const SAGE = "#DDE6D6";
const OLIVE = "#B0A41C";
const LAV = "#BFB9E6";
const CORAL = "#F2542D";
const LIME = "#C6F24E";
const INKC = "#0E0E0E";
const sans = "var(--font-geist-sans)";

const css = `@keyframes bb-grow{from{transform:scaleY(0)}to{transform:scaleY(1)}}.bb-bar{transform-origin:bottom;animation:bb-grow .9s cubic-bezier(.22,1,.36,1) both}`;

function Pill({ children, on = false }: { children: React.ReactNode; on?: boolean }) {
  return <span style={{ display: "inline-flex", alignItems: "center", gap: 8, border: `1.5px solid ${on ? "transparent" : "rgba(0,0,0,0.5)"}`, background: on ? INKC : "transparent", color: on ? "#fff" : INKC, borderRadius: 999, padding: "7px 16px", fontSize: 13, fontWeight: 600 }}>{children}</span>;
}

export default async function Bold() {
  const d = await getProtoData();
  const bars = growthSeries(26);
  const barMax = Math.max(...bars);
  const prog = [
    { k: "本周", w: 62 },
    { k: "本月", w: 84 },
    { k: "全年", w: 73 },
  ];

  return (
    <main style={{ minHeight: "100vh", background: BG, color: "#fff", fontFamily: sans }}>
      <style dangerouslySetInnerHTML={{ __html: css }} />
      <ProtoBack />
      <div style={{ maxWidth: 1180, margin: "0 auto", padding: "20px 16px 64px" }}>
        {/* top bar */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
          <div style={{ fontWeight: 800, fontSize: 19, letterSpacing: "-0.01em" }}>BYWOOD <span style={{ color: "#6b7280" }}>· ROC</span></div>
          <div style={{ display: "flex", gap: 8 }}>
            {["数据看板", "战线", "EN"].map((t) => (
              <span key={t} style={{ border: "1.5px solid rgba(255,255,255,0.25)", borderRadius: 999, padding: "7px 16px", fontSize: 13, fontWeight: 600 }}>{t}</span>
            ))}
          </div>
        </div>

        {/* HERO sage card */}
        <section style={{ background: SAGE, color: INKC, borderRadius: 30, padding: "26px 30px", marginBottom: 14 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <Pill>增长态势</Pill>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: 12, fontWeight: 600, letterSpacing: "0.08em" }}>实时回流
              <span style={{ display: "inline-flex", alignItems: "center", background: INKC, color: "#fff", borderRadius: 999, padding: "4px 6px", gap: 6 }}>OFF<span style={{ background: LIME, color: INKC, borderRadius: 999, padding: "2px 8px" }}>ON</span></span>
            </span>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-end", justifyContent: "space-between", gap: 24, marginTop: 22 }}>
            <div style={{ flex: "1 1 320px", maxWidth: 460 }}>
              {prog.map((p) => (
                <div key={p.k} style={{ marginBottom: 16 }}>
                  <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 6 }}>{p.k}</div>
                  <div style={{ height: 6, background: "rgba(14,14,14,0.12)", borderRadius: 999 }}>
                    <div style={{ width: `${p.w}%`, height: "100%", background: INKC, borderRadius: 999 }} />
                  </div>
                </div>
              ))}
            </div>
            <div style={{ textAlign: "right" }}>
              <div style={{ fontWeight: 800, letterSpacing: "-0.045em", lineHeight: 0.86, fontSize: "clamp(58px,11vw,150px)" }}>
                <CountUp value={d.impressions} format="cn" duration={2200} />
              </div>
              <div style={{ fontSize: 13, fontWeight: 600, letterSpacing: "0.06em", marginTop: 6, opacity: 0.7 }}>累计内容曝光 · 跨 {d.projects} 条战线</div>
            </div>
          </div>
        </section>

        {/* 3 color cards */}
        <section style={{ display: "grid", gap: 14, gridTemplateColumns: "repeat(auto-fit,minmax(280px,1fr))", marginBottom: 14 }}>
          {/* OLIVE growth */}
          <div style={{ background: OLIVE, color: INKC, borderRadius: 30, padding: "24px 26px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <Pill>增长 Growth</Pill>
              <span style={{ display: "inline-flex", background: INKC, borderRadius: 999, padding: 3 }}><span style={{ color: "rgba(255,255,255,0.6)", fontSize: 12, padding: "4px 10px" }}>周</span><span style={{ background: "#fff", color: INKC, borderRadius: 999, fontSize: 12, fontWeight: 700, padding: "4px 10px" }}>日</span></span>
            </div>
            <p style={{ fontSize: 14, lineHeight: 1.45, marginTop: 14, maxWidth: 280 }}>基于平均互动率,AI 测算的曝光增长轨迹。</p>
            <div style={{ position: "relative", marginTop: 18 }}>
              <span style={{ position: "absolute", right: 8, top: -6, background: INKC, color: "#fff", borderRadius: 8, fontSize: 12, fontWeight: 700, padding: "3px 8px" }}>峰值 {comma(d.topInteractions)}</span>
              <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 130, marginTop: 18 }}>
                {bars.map((v, i) => (
                  <div key={i} className="bb-bar" style={{ flex: 1, height: `${Math.max(4, (v / barMax) * 130)}px`, background: INKC, borderRadius: 2, animationDelay: `${i * 0.02}s` }} />
                ))}
              </div>
            </div>
          </div>

          {/* LAVENDER hit-rate */}
          <div style={{ background: LAV, color: INKC, borderRadius: 30, padding: "24px 26px" }}>
            <Pill>命中 Engagement</Pill>
            <div style={{ fontWeight: 800, letterSpacing: "-0.03em", fontSize: "clamp(40px,6vw,64px)", marginTop: 14, lineHeight: 1 }}>{d.hitRate}%</div>
            <div style={{ fontSize: 14, opacity: 0.7, marginTop: 2 }}>验证级爆款命中率</div>
            <div style={{ display: "flex", height: 64, borderRadius: 12, overflow: "hidden", marginTop: 18, background: "rgba(14,14,14,0.12)" }}>
              <div style={{ width: "62%", background: INKC }} />
              <div style={{ width: "38%", background: "rgba(14,14,14,0.28)" }} />
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, fontWeight: 600, marginTop: 8 }}>
              <span>验证级爆款 {comma(d.baokuan)}</span><span style={{ opacity: 0.6 }}>解析 {comma(d.essence)}</span>
            </div>
          </div>

          {/* CORAL capability list */}
          <div style={{ background: CORAL, color: INKC, borderRadius: 30, padding: "24px 26px", display: "flex", flexDirection: "column" }}>
            <Pill>资产 · 能力</Pill>
            <div style={{ marginTop: 14, flex: 1 }}>
              {[
                { g: "◆", k: "策略经验卡", v: comma(d.cards) },
                { g: "❖", k: "结构化内核", v: comma(d.essence) },
                { g: "◇", k: "受众维度", v: comma(d.audiences) },
                { g: "✦", k: "情绪杠杆", v: comma(d.levers) },
              ].map((r) => (
                <div key={r.k} style={{ display: "flex", alignItems: "center", gap: 12, padding: "9px 0", fontSize: 17, fontWeight: 600 }}>
                  <span style={{ fontSize: 14 }}>{r.g}</span><span style={{ flex: 1 }}>{r.k}</span><span style={{ fontWeight: 800 }}>{r.v}</span>
                </div>
              ))}
            </div>
            <Link href="/console" style={{ textDecoration: "none", textAlign: "center", background: INKC, color: "#fff", borderRadius: 999, padding: "12px", fontSize: 14, fontWeight: 700, marginTop: 10 }}>进入内部座舱 →</Link>
          </div>
        </section>

        {/* big fading list */}
        <section>
          <div style={{ marginBottom: 8 }}><span style={{ border: "1.5px solid rgba(255,255,255,0.25)", borderRadius: 999, padding: "7px 16px", fontSize: 13, fontWeight: 600 }}>分战线 · Fronts</span></div>
          {d.byProject.map((p, i) => {
            const op = [1, 0.8, 0.58, 0.4, 0.3][i] ?? 0.3;
            return (
              <div key={p.id} style={{ display: "grid", gridTemplateColumns: "1fr auto auto", alignItems: "baseline", gap: 16, padding: "10px 0", borderTop: i ? "1px solid rgba(255,255,255,0.08)" : "none", opacity: op }}>
                <span style={{ fontWeight: 700, letterSpacing: "-0.02em", fontSize: "clamp(28px,4.4vw,56px)" }}>{PROJECT_LABEL[p.id] ?? p.id}</span>
                <span style={{ fontSize: 13, color: "#9aa0aa", justifySelf: "end", minWidth: 120, textAlign: "right" }}>{comma(p.notes)} 资产 · {comma(p.baokuan)} 爆款</span>
                <span style={{ fontWeight: 700, letterSpacing: "-0.02em", fontSize: "clamp(26px,3.6vw,46px)", justifySelf: "end", minWidth: 150, textAlign: "right" }}>{cnNum(p.impressions)}</span>
              </div>
            );
          })}
        </section>
      </div>
    </main>
  );
}
