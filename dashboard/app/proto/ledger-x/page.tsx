import type { Metadata } from "next";
import { cnNum, comma, PROJECT_LABEL } from "@/config/showcase";
import { getProtoData } from "@/lib/proto";
import ProtoBack from "@/components/ProtoBack";
import CountUp from "@/components/CountUp";

export const metadata: Metadata = { robots: { index: false, follow: false }, title: "数据编辑·张力版 · 原型" };
export const dynamic = "force-dynamic";

const INK = "#15140E";
const PAPER = "#F4F1E9";
const RED = "#E2402A";
const BLUE = "#1D4ED8";
const OCHRE = "#E8A317";
const sans = "var(--font-geist-sans)";
const mono = "var(--font-geist-mono)";
const PAL = [RED, BLUE, OCHRE, INK];

const css = `@keyframes lx-grow{from{transform:scaleY(0)}to{transform:scaleY(1)}}.lx-bar{transform-origin:bottom;animation:lx-grow 1s cubic-bezier(.22,1,.36,1) both}`;

export default async function LedgerX() {
  const d = await getProtoData();
  const maxImp = Math.max(...d.byProject.map((p) => p.impressions), 1);
  const total = d.byProject.reduce((s, p) => s + p.impressions, 0) || 1;
  const kpis = [
    { k: "内容资产", v: d.notes, c: INK },
    { k: "验证级爆款", v: d.baokuan, c: RED },
    { k: "策略经验卡", v: d.cards, c: BLUE },
    { k: "结构化内核", v: d.essence, c: OCHRE },
  ];

  return (
    <main style={{ minHeight: "100vh", background: PAPER, color: INK, fontFamily: sans }}>
      <style dangerouslySetInnerHTML={{ __html: css }} />
      <ProtoBack dark={false} />
      <div style={{ maxWidth: 1040, margin: "0 auto", padding: "0 22px" }}>
        <header style={{ borderBottom: `6px solid ${INK}`, paddingTop: 40, paddingBottom: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontFamily: mono, fontSize: 11, letterSpacing: "0.16em", textTransform: "uppercase", color: "#6b675c" }}>
            <span>BYWOOD · ROC 增长成果报告</span><span>GROWTH LEDGER / 2026</span>
          </div>
        </header>

        <section style={{ borderBottom: `2px solid ${INK}`, padding: "6px 0 18px" }}>
          <div style={{ fontSize: "clamp(64px,17vw,230px)", fontWeight: 800, letterSpacing: "-0.05em", lineHeight: 0.82, color: INK }}>
            <CountUp value={d.impressions} format="cn" duration={2200} />
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: 10, marginTop: 8 }}>
            <span style={{ fontFamily: mono, fontSize: 13, letterSpacing: "0.14em", textTransform: "uppercase", color: "#6b675c" }}>累计内容曝光 · 跨 {d.projects} 条战线</span>
            <span style={{ fontWeight: 800, fontSize: 22, color: RED }}>命中率 {d.hitRate}%</span>
          </div>
        </section>

        <section style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", borderBottom: `2px solid ${INK}` }}>
          {kpis.map((s, i) => (
            <div key={s.k} style={{ padding: "20px 18px", borderRight: i < kpis.length - 1 ? "1px solid rgba(21,20,14,0.18)" : undefined }}>
              <div style={{ fontFamily: mono, fontSize: 11, letterSpacing: "0.12em", textTransform: "uppercase", color: "#6b675c" }}>{s.k}</div>
              <div style={{ fontSize: "clamp(30px,4vw,52px)", fontWeight: 800, letterSpacing: "-0.03em", color: s.c, marginTop: 6, lineHeight: 1 }}><CountUp value={s.v} format="comma" duration={1500} /></div>
            </div>
          ))}
        </section>

        <section style={{ padding: "30px 0", borderBottom: `2px solid ${INK}` }}>
          <h2 style={{ fontWeight: 800, fontSize: 24, letterSpacing: "-0.01em" }}>分战线曝光分布</h2>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 20, height: 280, marginTop: 24 }}>
            {d.byProject.map((p, i) => (
              <div key={p.id} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center" }}>
                <div style={{ fontFamily: mono, fontWeight: 800, fontSize: "clamp(13px,1.5vw,18px)", marginBottom: 8 }}>{cnNum(p.impressions)}</div>
                <div className="lx-bar" style={{ width: "100%", maxWidth: 120, height: `${Math.max(6, (p.impressions / maxImp) * 230)}px`, background: PAL[i % PAL.length], animationDelay: `${i * 0.12}s` }} />
                <div style={{ fontFamily: mono, fontSize: 11, color: "#6b675c", marginTop: 10, textAlign: "center" }}>{PROJECT_LABEL[p.id] ?? p.id}</div>
                <div style={{ fontFamily: mono, fontSize: 10, color: "#9a958a" }}>{Math.round((p.impressions / total) * 100)}%</div>
              </div>
            ))}
          </div>
        </section>

        <section style={{ padding: "26px 0 72px" }}>
          <h2 style={{ fontWeight: 800, fontSize: 24, marginBottom: 14 }}>Top 爆款</h2>
          <div style={{ display: "grid", gridTemplateColumns: "56px 1fr 130px 150px", gap: 12, fontFamily: mono, fontSize: 11, letterSpacing: "0.1em", textTransform: "uppercase", color: "#6b675c", paddingBottom: 8, borderBottom: `2px solid ${INK}` }}>
            <span>#</span><span>战线</span><span style={{ textAlign: "right" }}>互动</span><span style={{ textAlign: "right" }}>曝光</span>
          </div>
          {d.hits.map((h) => (
            <div key={h.rank} style={{ display: "grid", gridTemplateColumns: "56px 1fr 130px 150px", gap: 12, alignItems: "baseline", padding: "14px 0", borderBottom: "1px solid rgba(21,20,14,0.16)" }}>
              <span style={{ fontWeight: 800, fontSize: 28, color: h.rank === 1 ? RED : INK, letterSpacing: "-0.03em" }}>{h.rank}</span>
              <span style={{ fontSize: 16, fontWeight: 600 }}>{PROJECT_LABEL[h.project_id] ?? h.project_id}</span>
              <span style={{ fontFamily: mono, textAlign: "right", fontSize: 15 }}>{comma(h.interactions)}</span>
              <span style={{ fontFamily: mono, textAlign: "right", fontSize: 15, fontWeight: 700, color: RED }}>{cnNum(h.impressions)}</span>
            </div>
          ))}
        </section>
      </div>
    </main>
  );
}
