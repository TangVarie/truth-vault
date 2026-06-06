import type { Metadata } from "next";
import { cnNum, comma, PROJECT_LABEL } from "@/config/showcase";
import { getProtoData, areaPath } from "@/lib/proto";
import ProtoBack from "@/components/ProtoBack";
import Sankey from "@/components/Sankey";
import CountUp from "@/components/CountUp";

export const metadata: Metadata = { robots: { index: false, follow: false }, title: "情报终端·张力版 · 原型" };
export const dynamic = "force-dynamic";

const SIG = "#36F1CD";
const SIG2 = "#9EFF00";
const BORD = "rgba(255,255,255,0.10)";
const MUTE = "#8A93A0";
const mono = "var(--font-geist-mono)";

const css = `
@keyframes tx-marq{0%{transform:translateX(0)}100%{transform:translateX(-50%)}}
@keyframes tx-pulse{0%,100%{opacity:.35;transform:scale(.85)}50%{opacity:1;transform:scale(1.2)}}
@keyframes tx-draw{to{stroke-dashoffset:0}}
@keyframes tx-bloom{0%,100%{opacity:.45}50%{opacity:.9}}
.tx-line{stroke-dasharray:1500;stroke-dashoffset:1500;animation:tx-draw 2.6s cubic-bezier(.22,1,.36,1) .2s forwards}
.tx-dot{animation:tx-pulse 1.8s ease-in-out infinite}
.tx-panel{border:1px solid ${BORD};background:linear-gradient(180deg,rgba(255,255,255,.045),rgba(255,255,255,.012));box-shadow:0 0 50px -28px ${SIG}}
.tx-num{text-shadow:0 0 24px ${SIG}66}
`;

export default async function TerminalX() {
  const d = await getProtoData();
  const { line } = areaPath(d.growth, 900, 90, 4);
  const maxImp = Math.max(...d.byProject.map((p) => p.impressions), 1);
  const panels = [
    { k: "NOTES", v: d.notes, s: "内容资产" },
    { k: "HITS 爆款", v: d.baokuan, s: "验证级" },
    { k: "HIT-RATE", v: d.hitRate, s: "命中率" },
    { k: "CARDS", v: d.cards, s: "策略卡" },
    { k: "ESSENCE", v: d.essence, s: "内核" },
    { k: "AUD", v: d.audiences, s: "受众维度" },
  ];

  return (
    <main style={{ minHeight: "100vh", background: "#06070A", color: "#C8CDD2", fontFamily: mono, position: "relative", overflow: "hidden" }}>
      <style dangerouslySetInnerHTML={{ __html: css }} />
      <ProtoBack />
      <div style={{ position: "absolute", top: -160, left: -120, width: 560, height: 560, background: `radial-gradient(circle,${SIG}22,transparent 70%)`, filter: "blur(20px)", animation: "tx-bloom 7s ease-in-out infinite", pointerEvents: "none" }} />
      <div style={{ position: "absolute", top: 120, right: -140, width: 520, height: 520, background: "radial-gradient(circle,#E8765A26,transparent 70%)", filter: "blur(20px)", animation: "tx-bloom 9s ease-in-out infinite", pointerEvents: "none" }} />
      <div style={{ position: "absolute", inset: 0, backgroundImage: "linear-gradient(rgba(255,255,255,0.045) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,0.045) 1px,transparent 1px)", backgroundSize: "30px 30px", pointerEvents: "none", WebkitMaskImage: "radial-gradient(circle at 50% 26%,#000,transparent 92%)", maskImage: "radial-gradient(circle at 50% 26%,#000,transparent 92%)" }} />

      <div style={{ position: "relative", maxWidth: 1180, margin: "0 auto", padding: "0 16px" }}>
        <div style={{ display: "flex", gap: 16, alignItems: "center", fontSize: 12, padding: "14px 4px", borderBottom: `1px solid ${BORD}` }}>
          <span style={{ color: "#fff", fontWeight: 700, letterSpacing: "0.04em" }}>BYWOOD//ROC</span>
          <span style={{ color: MUTE }}>FLYWHEEL INTELLIGENCE</span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6, color: SIG }}><span className="tx-dot" style={{ width: 8, height: 8, borderRadius: 99, background: SIG, boxShadow: `0 0 12px ${SIG}` }} />LIVE</span>
          <span style={{ marginLeft: "auto", color: MUTE }}>{d.projects} FRONTS · {comma(d.audiences)} AUD · {comma(d.levers)} LEVERS</span>
        </div>

        <section style={{ padding: "36px 0 8px" }}>
          <div style={{ fontSize: 11, letterSpacing: "0.22em", color: MUTE, textTransform: "uppercase" }}>累计内容曝光 · CUMULATIVE IMPRESSIONS</div>
          <div className="tx-num" style={{ fontSize: "clamp(56px,12vw,150px)", fontWeight: 600, color: SIG, letterSpacing: "-0.03em", lineHeight: 0.92, marginTop: 4 }}>
            <CountUp value={d.impressions} format="cn" duration={2200} />
          </div>
        </section>

        <section className="tx-panel" style={{ borderRadius: 14, padding: "14px 16px 6px", marginTop: 8 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, letterSpacing: "0.16em", color: MUTE, textTransform: "uppercase" }}><span>全链路数据流 // FLYWHEEL STREAM</span><span style={{ color: SIG }}>● 实时回流</span></div>
          <Sankey impressions={d.impressions} notes={d.notes} baokuan={d.baokuan} cards={d.cards} />
        </section>

        <section style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fit,minmax(165px,1fr))", marginTop: 10 }}>
          {panels.map((p) => (
            <div key={p.k} className="tx-panel" style={{ borderRadius: 12, padding: 14, position: "relative", overflow: "hidden" }}>
              <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2, background: `linear-gradient(90deg,${SIG},transparent)` }} />
              <div style={{ fontSize: 10, letterSpacing: "0.14em", color: MUTE }}>{p.k}</div>
              <div className="tx-num" style={{ fontSize: 34, color: SIG, fontWeight: 600, letterSpacing: "-0.02em", lineHeight: 1, marginTop: 8 }}>
                {p.k === "HIT-RATE" ? <>{d.hitRate}<span style={{ fontSize: "0.5em" }}>%</span></> : <CountUp value={p.v} format="comma" duration={1600} />}
              </div>
              <div style={{ fontSize: 11, color: MUTE, marginTop: 8 }}>{p.s}</div>
            </div>
          ))}
        </section>

        <section className="tx-panel" style={{ borderRadius: 12, padding: "14px 16px", marginTop: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: MUTE }}><span>CUM. IMPRESSIONS · 复利上扬</span><span style={{ color: SIG }}>{cnNum(d.impressions)}</span></div>
          <svg viewBox="0 0 900 90" width="100%" height="84" preserveAspectRatio="none" style={{ marginTop: 8, filter: `drop-shadow(0 0 6px ${SIG}88)` }}>
            <path className="tx-line" d={line} fill="none" stroke={SIG} strokeWidth="2" />
          </svg>
        </section>

        <section style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fit,minmax(280px,1fr))", marginTop: 10 }}>
          <div className="tx-panel" style={{ borderRadius: 12, padding: "14px 16px" }}>
            <div style={{ fontSize: 10, letterSpacing: "0.14em", color: MUTE, marginBottom: 12 }}>FRONTS · 分战线</div>
            {d.byProject.map((p) => (
              <div key={p.id} style={{ marginBottom: 11 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}><span>{PROJECT_LABEL[p.id] ?? p.id}</span><span style={{ color: SIG }}>{cnNum(p.impressions)}</span></div>
                <div style={{ height: 4, background: "rgba(255,255,255,0.07)", marginTop: 5, borderRadius: 2, overflow: "hidden" }}><div style={{ width: `${Math.max(3, (p.impressions / maxImp) * 100)}%`, height: "100%", background: `linear-gradient(90deg,${SIG2},${SIG})`, boxShadow: `0 0 10px ${SIG}` }} /></div>
              </div>
            ))}
          </div>
          <div className="tx-panel" style={{ borderRadius: 12, padding: "14px 16px" }}>
            <div style={{ fontSize: 10, letterSpacing: "0.14em", color: MUTE, marginBottom: 10 }}>TOP HITS · 爆款</div>
            {d.hits.map((h) => (
              <div key={h.rank} style={{ display: "grid", gridTemplateColumns: "24px 1fr 70px 70px", gap: 8, fontSize: 12, padding: "7px 0", borderTop: `1px solid ${BORD}` }}>
                <span style={{ color: h.rank === 1 ? SIG : MUTE }}>{h.rank}</span>
                <span>{PROJECT_LABEL[h.project_id] ?? h.project_id}</span>
                <span style={{ textAlign: "right" }}>{comma(h.interactions)}</span>
                <span style={{ textAlign: "right", color: SIG }}>{cnNum(h.impressions)}</span>
              </div>
            ))}
          </div>
        </section>

        <section style={{ marginTop: 10, marginBottom: 32, border: `1px solid ${BORD}`, borderRadius: 10, overflow: "hidden", background: "rgba(255,255,255,0.02)" }}>
          <div style={{ display: "flex", width: "max-content", animation: "tx-marq 26s linear infinite", fontSize: 11, color: MUTE, padding: "9px 0" }}>
            {[0, 1].map((rep) => (
              <div key={rep} style={{ display: "flex", gap: 26, paddingLeft: 26 }}>
                <span style={{ color: SIG }}>● SYNC OK</span><span>飞书投放表 ✓ {comma(d.notes)} 接入</span><span style={{ color: SIG }}>ssll ✓ 97 回流</span><span style={{ color: "#F5A623" }}>autowriter ◌ 待流</span><span>指标采集 06-06 05:59</span><span>essence {comma(d.essence)}/{comma(d.notes)}</span><span style={{ color: SIG }}>命中率 {d.hitRate}%</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
