import type { Metadata } from "next";
import { cnNum, comma, PROJECT_LABEL } from "@/config/showcase";
import { getProtoData, areaPath } from "@/lib/proto";
import ProtoBack from "@/components/ProtoBack";

export const metadata: Metadata = { robots: { index: false, follow: false }, title: "蓝图网格 · 原型" };
export const dynamic = "force-dynamic";

const HAIR = "#E4E4E7";
const INK = "#0A0A0A";
const ACC = "#E8765A";
const mono = "var(--font-geist-mono)";

export default async function Blueprint() {
  const d = await getProtoData();
  const { line, area } = areaPath(d.growth, 640, 150, 4);
  const maxImp = Math.max(...d.byProject.map((p) => p.impressions), 1);
  const stats = [
    { k: "累计曝光", v: cnNum(d.impressions) },
    { k: "内容资产", v: comma(d.notes) },
    { k: "验证级爆款", v: comma(d.baokuan) },
    { k: "命中率", v: d.hitRate + "%" },
    { k: "策略卡", v: comma(d.cards) },
    { k: "结构化内核", v: comma(d.essence) },
  ];

  return (
    <main style={{ minHeight: "100vh", background: "#fff", color: INK, fontFamily: "var(--font-geist-sans)" }}>
      <ProtoBack dark={false} />
      <div style={{ position: "sticky", top: 0, zIndex: 10, borderBottom: `1px solid ${HAIR}`, background: "rgba(255,255,255,0.82)", backdropFilter: "blur(8px)" }}>
        <div style={{ maxWidth: 1080, margin: "0 auto", padding: "14px 20px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontWeight: 700, letterSpacing: "-0.01em" }}>BYWOOD <span style={{ color: "#9ca3af" }}>/ ROC</span></span>
          <span style={{ fontFamily: mono, fontSize: 11, letterSpacing: "0.18em", color: "#9ca3af" }}>BLUEPRINT</span>
        </div>
      </div>

      <section style={{ borderBottom: `1px solid ${HAIR}`, backgroundImage: `linear-gradient(${HAIR} 1px,transparent 1px),linear-gradient(90deg,${HAIR} 1px,transparent 1px)`, backgroundSize: "36px 36px" }}>
        <div style={{ maxWidth: 1080, margin: "0 auto", padding: "72px 20px", background: "linear-gradient(180deg,rgba(255,255,255,0.35),rgba(255,255,255,0.92))" }}>
          <span style={{ fontFamily: mono, fontSize: 11, letterSpacing: "0.18em", textTransform: "uppercase", color: ACC }}>AI 内容增长中台</span>
          <h1 style={{ fontSize: "clamp(34px,5.2vw,68px)", fontWeight: 800, letterSpacing: "-0.04em", lineHeight: 1.02, margin: "14px 0 0", maxWidth: 760 }}>
            把每一次投放,<br />变成越投越准的<span style={{ color: ACC }}>策略复利</span>。
          </h1>
          <p style={{ color: "#52525b", marginTop: 18, maxWidth: 540, fontSize: 16 }}>{d.projects} 条战线 · 真实投放结果实时回流 · 结构化策略库持续沉淀。</p>
          <div style={{ display: "flex", gap: 32, marginTop: 34, flexWrap: "wrap" }}>
            {stats.slice(0, 3).map((s) => (
              <div key={s.k}>
                <div style={{ fontFamily: mono, fontSize: "clamp(26px,3vw,40px)", fontWeight: 700, letterSpacing: "-0.02em" }}>{s.v}</div>
                <div style={{ fontFamily: mono, fontSize: 11, letterSpacing: "0.14em", textTransform: "uppercase", color: "#9ca3af", marginTop: 4 }}>{s.k}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <div style={{ maxWidth: 1080, margin: "0 auto", padding: "0 20px" }}>
        <section style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", borderLeft: `1px solid ${HAIR}` }}>
          {stats.map((s) => (
            <div key={s.k} style={{ padding: "22px 20px", borderRight: `1px solid ${HAIR}`, borderBottom: `1px solid ${HAIR}` }}>
              <div style={{ fontFamily: mono, fontSize: 11, letterSpacing: "0.14em", textTransform: "uppercase", color: "#9ca3af" }}>{s.k}</div>
              <div style={{ fontFamily: mono, fontSize: 28, fontWeight: 700, letterSpacing: "-0.02em", marginTop: 8 }}>{s.v}</div>
            </div>
          ))}
        </section>

        <section style={{ padding: "28px 0", borderBottom: `1px solid ${HAIR}` }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 14 }}>
            <h2 style={{ fontWeight: 700, fontSize: 18, letterSpacing: "-0.01em" }}>累计曝光 · 复利上扬</h2>
            <span style={{ fontFamily: mono, fontSize: 11, letterSpacing: "0.14em", color: "#9ca3af" }}>CUMULATIVE</span>
          </div>
          <svg viewBox="0 0 640 150" width="100%" height="150" preserveAspectRatio="none">
            <path d={area} fill={ACC} fillOpacity="0.08" />
            <path d={line} fill="none" stroke={ACC} strokeWidth="2" />
          </svg>
        </section>

        <section style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))", borderLeft: `1px solid ${HAIR}` }}>
          {d.byProject.map((p) => (
            <div key={p.id} style={{ padding: "20px", borderRight: `1px solid ${HAIR}`, borderBottom: `1px solid ${HAIR}` }}>
              <div style={{ fontFamily: mono, fontSize: 11, letterSpacing: "0.12em", color: "#9ca3af" }}>{PROJECT_LABEL[p.id] ?? p.id}</div>
              <div style={{ fontFamily: mono, fontSize: 26, fontWeight: 700, marginTop: 8 }}>{cnNum(p.impressions)}</div>
              <div style={{ height: 4, background: "#f1f1f3", marginTop: 12, borderRadius: 2 }}>
                <div style={{ width: `${Math.max(4, (p.impressions / maxImp) * 100)}%`, height: "100%", background: ACC, borderRadius: 2 }} />
              </div>
              <div style={{ fontFamily: mono, fontSize: 11, color: "#71717a", marginTop: 10 }}>{comma(p.notes)} 资产 · {comma(p.baokuan)} 爆款</div>
            </div>
          ))}
        </section>

        <section style={{ padding: "28px 0 72px" }}>
          <h2 style={{ fontWeight: 700, fontSize: 18, marginBottom: 14 }}>Top 爆款</h2>
          <Row head cols={["#", "战线", "互动", "曝光"]} />
          {d.hits.map((h) => (
            <Row key={h.rank} acc={h.rank === 1} cols={[String(h.rank), PROJECT_LABEL[h.project_id] ?? h.project_id, comma(h.interactions), cnNum(h.impressions)]} />
          ))}
        </section>
      </div>
    </main>
  );
}

function Row({ cols, head, acc }: { cols: string[]; head?: boolean; acc?: boolean }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "40px 1fr 120px 120px", gap: 12, padding: "12px 4px", borderBottom: `1px solid ${HAIR}` }}>
      <span style={{ fontFamily: mono, fontSize: 13, color: acc ? ACC : "#9ca3af" }}>{cols[0]}</span>
      <span style={{ fontSize: 14, color: head ? "#9ca3af" : INK }}>{cols[1]}</span>
      <span style={{ textAlign: "right", fontFamily: mono, fontSize: 14, color: head ? "#9ca3af" : INK }}>{cols[2]}</span>
      <span style={{ textAlign: "right", fontFamily: mono, fontSize: 14, color: acc ? ACC : head ? "#9ca3af" : INK }}>{cols[3]}</span>
    </div>
  );
}
