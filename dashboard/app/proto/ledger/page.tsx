import type { Metadata } from "next";
import { cnNum, comma, PROJECT_LABEL } from "@/config/showcase";
import { getProtoData } from "@/lib/proto";
import ProtoBack from "@/components/ProtoBack";

export const metadata: Metadata = { robots: { index: false, follow: false }, title: "数据编辑 · 原型" };
export const dynamic = "force-dynamic";

const INK = "#16150F";
const RULE = "rgba(22,21,15,0.16)";
const ACC = "#C0492F";
const PAPER = "#FAFAF7";
const MUTE = "#6b675c";
const sans = "var(--font-geist-sans)";
const mono = "var(--font-geist-mono)";

export default async function Ledger() {
  const d = await getProtoData();
  const maxImp = Math.max(...d.byProject.map((p) => p.impressions), 1);

  return (
    <main style={{ minHeight: "100vh", background: PAPER, color: INK, fontFamily: sans }}>
      <ProtoBack dark={false} />
      <div style={{ maxWidth: 1000, margin: "0 auto", padding: "0 22px" }}>
        <header style={{ borderBottom: `3px double ${INK}`, paddingTop: 40, paddingBottom: 14 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontFamily: mono, fontSize: 11, letterSpacing: "0.14em", textTransform: "uppercase", color: MUTE }}>
            <span>BYWOOD · ROC 增长成果报告</span><span>GROWTH LEDGER · 2026</span>
          </div>
          <h1 style={{ fontSize: "clamp(34px,5.5vw,72px)", fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1, margin: "18px 0 8px" }}>真实结果,逐行可查。</h1>
        </header>

        <section style={{ borderBottom: `1px solid ${RULE}`, padding: "26px 0", display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: 16 }}>
          <div>
            <div style={{ fontFamily: mono, fontSize: 11, letterSpacing: "0.14em", textTransform: "uppercase", color: MUTE }}>累计内容曝光</div>
            <div style={{ fontSize: "clamp(48px,9vw,120px)", fontWeight: 800, letterSpacing: "-0.04em", lineHeight: 0.9, marginTop: 6 }}>{cnNum(d.impressions)}</div>
          </div>
          <div style={{ textAlign: "right" }}>
            <Big k="战线" v={String(d.projects)} />
            <Big k="命中率" v={d.hitRate + "%"} acc />
            <Big k="验证级爆款" v={comma(d.baokuan)} />
          </div>
        </section>

        <section style={{ padding: "24px 0", borderBottom: `1px solid ${RULE}` }}>
          <SecTitle n="01" t="分战线成果" />
          <div style={{ marginTop: 14 }}>
            <LRow head four={false} cols={["战线", "内容资产", "验证级爆款", "累计曝光"]} />
            {d.byProject.map((p) => (
              <LRow key={p.id} four={false} bar={p.impressions / maxImp} cols={[PROJECT_LABEL[p.id] ?? p.id, comma(p.notes), comma(p.baokuan), cnNum(p.impressions)]} />
            ))}
          </div>
        </section>

        <section style={{ padding: "24px 0", borderBottom: `1px solid ${RULE}` }}>
          <SecTitle n="02" t="曝光分布" />
          <div style={{ marginTop: 18, display: "flex", alignItems: "flex-end", gap: 18, height: 200, borderBottom: `2px solid ${INK}`, position: "relative" }}>
            {[0.25, 0.5, 0.75, 1].map((g) => (
              <div key={g} style={{ position: "absolute", left: 0, right: 0, bottom: `${g * 100}%`, borderTop: `1px solid ${RULE}` }} />
            ))}
            {d.byProject.map((p) => (
              <div key={p.id} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", zIndex: 1 }}>
                <div style={{ fontFamily: mono, fontSize: 12, fontWeight: 700, marginBottom: 6 }}>{cnNum(p.impressions)}</div>
                <div style={{ width: "100%", maxWidth: 80, height: `${Math.max(4, (p.impressions / maxImp) * 160)}px`, background: ACC }} />
                <div style={{ fontFamily: mono, fontSize: 10, color: MUTE, marginTop: 8, textAlign: "center" }}>{PROJECT_LABEL[p.id] ?? p.id}</div>
              </div>
            ))}
          </div>
        </section>

        <section style={{ padding: "24px 0 72px" }}>
          <SecTitle n="03" t="Top 爆款" />
          <div style={{ marginTop: 14 }}>
            <LRow head four cols={["#", "战线", "互动", "曝光"]} />
            {d.hits.map((h) => (
              <LRow key={h.rank} four acc={h.rank === 1} cols={[String(h.rank), PROJECT_LABEL[h.project_id] ?? h.project_id, comma(h.interactions), cnNum(h.impressions)]} />
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}

function Big({ k, v, acc }: { k: string; v: string; acc?: boolean }) {
  return (
    <div style={{ marginBottom: 6 }}>
      <span style={{ color: MUTE, marginRight: 10, fontSize: 11, letterSpacing: "0.1em" }}>{k}</span>
      <span style={{ fontFamily: mono, fontWeight: 700, fontSize: 18, color: acc ? ACC : INK }}>{v}</span>
    </div>
  );
}
function SecTitle({ n, t }: { n: string; t: string }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
      <span style={{ fontFamily: mono, color: ACC, fontSize: 13 }}>{n}</span>
      <h2 style={{ fontWeight: 800, fontSize: 22, letterSpacing: "-0.01em" }}>{t}</h2>
    </div>
  );
}
function LRow({ cols, head, acc, bar, four }: { cols: string[]; head?: boolean; acc?: boolean; bar?: number; four: boolean }) {
  const grid = four ? "40px 1fr 110px 130px" : "1.4fr 1fr 1fr 1.3fr";
  const rightFrom = four ? 2 : 1;
  return (
    <div style={{ display: "grid", gridTemplateColumns: grid, gap: 12, padding: "11px 2px", borderBottom: `1px solid ${RULE}`, position: "relative", fontSize: head ? 11 : 14, fontFamily: head ? mono : undefined, letterSpacing: head ? "0.1em" : undefined, textTransform: head ? "uppercase" : "none", color: head ? MUTE : INK }}>
      {bar != null && !head ? <div style={{ position: "absolute", left: 0, bottom: 0, height: 2, width: `${bar * 100}%`, background: ACC }} /> : null}
      {cols.map((c, i) => (
        <span key={i} style={{ textAlign: i >= rightFrom ? "right" : "left", fontFamily: !head && i >= rightFrom ? mono : undefined, fontWeight: i === 0 && !head ? 700 : 400, color: acc && i === cols.length - 1 ? ACC : undefined }}>{c}</span>
      ))}
    </div>
  );
}
