import type { Metadata } from "next";
import { cnNum, comma, PROJECT_LABEL } from "@/config/showcase";
import { getProtoData, areaPath } from "@/lib/proto";
import ProtoBack from "@/components/ProtoBack";

export const metadata: Metadata = { robots: { index: false, follow: false }, title: "情报终端 · 原型" };
export const dynamic = "force-dynamic";

const SIG = "#9EFF00";
const GRID = "rgba(255,255,255,0.05)";
const BORD = "rgba(255,255,255,0.10)";
const MUTE = "#8A93A0";
const mono = "var(--font-geist-mono)";

export default async function Terminal() {
  const d = await getProtoData();
  const { line } = areaPath(d.growth, 900, 90, 3);
  const maxImp = Math.max(...d.byProject.map((p) => p.impressions), 1);
  const panels = [
    { k: "IMPRESSIONS", v: cnNum(d.impressions), s: "曝光", up: "+12.4%" },
    { k: "NOTES", v: comma(d.notes), s: "资产", up: "+3.1%" },
    { k: "HITS 爆款", v: comma(d.baokuan), s: "爆款", up: "+5" },
    { k: "HIT-RATE", v: d.hitRate + "%", s: "命中率", up: "" },
    { k: "CARDS", v: comma(d.cards), s: "策略卡", up: "" },
    { k: "ESSENCE", v: comma(d.essence), s: "内核", up: "" },
  ];

  return (
    <main style={{ minHeight: "100vh", background: "#0A0A0B", color: "#C8CDD2", fontFamily: mono, backgroundImage: `linear-gradient(${GRID} 1px,transparent 1px),linear-gradient(90deg,${GRID} 1px,transparent 1px)`, backgroundSize: "28px 28px" }}>
      <ProtoBack />
      <div style={{ borderBottom: `1px solid ${BORD}`, padding: "10px 16px", display: "flex", gap: 16, alignItems: "center", fontSize: 12, background: "rgba(0,0,0,0.45)" }}>
        <span style={{ color: "#fff", fontWeight: 700 }}>BYWOOD//ROC</span>
        <span style={{ color: MUTE }}>FLYWHEEL</span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, color: SIG }}><span style={{ width: 7, height: 7, borderRadius: 99, background: SIG, boxShadow: `0 0 8px ${SIG}` }} />LIVE</span>
        <span style={{ marginLeft: "auto", color: MUTE }}>{d.projects} FRONTS · {comma(d.audiences)} AUD · {comma(d.levers)} LEVERS</span>
      </div>

      <div style={{ maxWidth: 1180, margin: "0 auto", padding: 16 }}>
        <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fit,minmax(170px,1fr))" }}>
          {panels.map((p) => (
            <div key={p.k} style={{ border: `1px solid ${BORD}`, background: "rgba(255,255,255,0.025)", padding: "12px 14px" }}>
              <div style={{ fontSize: 10, letterSpacing: "0.14em", color: MUTE }}>{p.k}</div>
              <div style={{ fontSize: 30, color: SIG, fontWeight: 500, letterSpacing: "-0.02em", marginTop: 6, lineHeight: 1 }}>{p.v}</div>
              <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8, fontSize: 11, color: MUTE }}>
                <span>{p.s}</span>{p.up ? <span style={{ color: SIG }}>▲ {p.up}</span> : null}
              </div>
            </div>
          ))}
        </div>

        <div style={{ border: `1px solid ${BORD}`, background: "rgba(255,255,255,0.025)", marginTop: 10, padding: "12px 14px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: MUTE }}><span>CUM. IMPRESSIONS</span><span style={{ color: SIG }}>{cnNum(d.impressions)}</span></div>
          <svg viewBox="0 0 900 90" width="100%" height="80" preserveAspectRatio="none" style={{ marginTop: 8 }}>
            <path d={line} fill="none" stroke={SIG} strokeWidth="1.5" />
          </svg>
        </div>

        <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fit,minmax(280px,1fr))", marginTop: 10 }}>
          <div style={{ border: `1px solid ${BORD}`, background: "rgba(255,255,255,0.025)", padding: "12px 14px" }}>
            <div style={{ fontSize: 10, letterSpacing: "0.14em", color: MUTE, marginBottom: 10 }}>FRONTS · 分战线</div>
            {d.byProject.map((p) => (
              <div key={p.id} style={{ marginBottom: 10 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}><span>{PROJECT_LABEL[p.id] ?? p.id}</span><span style={{ color: SIG }}>{cnNum(p.impressions)}</span></div>
                <div style={{ height: 3, background: "rgba(255,255,255,0.08)", marginTop: 5 }}><div style={{ width: `${Math.max(3, (p.impressions / maxImp) * 100)}%`, height: "100%", background: SIG }} /></div>
              </div>
            ))}
          </div>
          <div style={{ border: `1px solid ${BORD}`, background: "rgba(255,255,255,0.025)", padding: "12px 14px" }}>
            <div style={{ fontSize: 10, letterSpacing: "0.14em", color: MUTE, marginBottom: 10 }}>TOP HITS · 爆款</div>
            <div style={{ display: "grid", gridTemplateColumns: "24px 1fr 64px 64px", gap: 8, fontSize: 10, color: MUTE, paddingBottom: 6 }}>
              <span>#</span><span>FRONT</span><span style={{ textAlign: "right" }}>INTER</span><span style={{ textAlign: "right" }}>IMPR</span>
            </div>
            {d.hits.map((h) => (
              <div key={h.rank} style={{ display: "grid", gridTemplateColumns: "24px 1fr 64px 64px", gap: 8, fontSize: 12, padding: "6px 0", borderTop: `1px solid ${BORD}` }}>
                <span style={{ color: h.rank === 1 ? SIG : MUTE }}>{h.rank}</span>
                <span>{PROJECT_LABEL[h.project_id] ?? h.project_id}</span>
                <span style={{ textAlign: "right" }}>{comma(h.interactions)}</span>
                <span style={{ textAlign: "right", color: SIG }}>{cnNum(h.impressions)}</span>
              </div>
            ))}
          </div>
        </div>

        <div style={{ border: `1px solid ${BORD}`, marginTop: 10, padding: "8px 14px", fontSize: 11, color: MUTE, display: "flex", gap: 18, flexWrap: "wrap" }}>
          <span style={{ color: SIG }}>● SYNC OK</span><span>飞书 ✓</span><span>ssll ✓ 97 回流</span><span style={{ color: "#F5A623" }}>autowriter ◌ 待流</span><span>指标采集 06-06 05:59</span><span>essence {comma(d.essence)}/{comma(d.notes)}</span>
        </div>
      </div>
    </main>
  );
}
