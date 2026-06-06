import type { Metadata } from "next";
import { cnNum, comma, PROJECT_LABEL } from "@/config/showcase";
import { getProtoData, areaPath } from "@/lib/proto";
import ProtoBack from "@/components/ProtoBack";

export const metadata: Metadata = { robots: { index: false, follow: false }, title: "编辑奢华 · 原型" };
export const dynamic = "force-dynamic";

const PAPER = "#F5F1E8";
const INK = "#15130F";
const BRASS = "#B08D57";
const CORAL = "#E8765A";
const MUTE = "#8A7F6D";
const fr = "var(--font-fraunces)";
const body = "var(--font-hanken)";
const mono = "var(--font-geist-mono)";

export default async function EditorialProto() {
  const d = await getProtoData();
  const { line } = areaPath(d.growth, 800, 120, 3);

  return (
    <main style={{ minHeight: "100vh", background: PAPER, color: INK, fontFamily: body }}>
      <ProtoBack dark={false} />
      <div style={{ maxWidth: 980, margin: "0 auto", padding: "0 24px" }}>
        <div style={{ fontFamily: mono, fontSize: 11, letterSpacing: "0.2em", textTransform: "uppercase", color: MUTE, paddingTop: 40 }}>BYWOOD 芭梧 · AI 内容增长中台</div>
        <div style={{ height: 1, background: BRASS, maxWidth: 120, margin: "16px 0 28px" }} />
        <h1 style={{ fontFamily: fr, fontSize: "clamp(40px,8vw,104px)", fontWeight: 430, lineHeight: 0.98, letterSpacing: "-0.02em", maxWidth: 820 }}>
          把每一次投放,变成越投越准的<span style={{ textDecoration: "underline", textDecorationColor: CORAL, textDecorationStyle: "double", textUnderlineOffset: 8 }}>策略复利</span>。
        </h1>
        <p style={{ fontSize: 19, color: "#3D3A34", marginTop: 24, maxWidth: 560, lineHeight: 1.55 }}>{d.projects} 条战线,真实投放结果实时回流,结构化策略库持续沉淀 —— 合作越久,命中率越高。</p>

        <section style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 24, margin: "48px 0", borderTop: `1px solid ${BRASS}`, paddingTop: 32 }}>
          <Num k="累计曝光" v={cnNum(d.impressions)} />
          <Num k="内容资产" v={comma(d.notes)} />
          <Num k="验证级爆款" v={comma(d.baokuan)} sub={`命中率 ${d.hitRate}%`} />
        </section>

        <section style={{ borderTop: "1px solid rgba(22,19,15,0.14)", paddingTop: 28 }}>
          <div style={{ fontFamily: mono, fontSize: 11, letterSpacing: "0.2em", color: MUTE, textTransform: "uppercase", marginBottom: 12 }}>复利累计曲线 · 先缓后陡</div>
          <svg viewBox="0 0 800 120" width="100%" height="120" preserveAspectRatio="none">
            <path d={line} fill="none" stroke={CORAL} strokeWidth="1.5" />
          </svg>
        </section>

        <section style={{ borderTop: `1px solid ${BRASS}`, paddingTop: 32, marginTop: 32 }}>
          <div style={{ fontFamily: mono, fontSize: 11, letterSpacing: "0.2em", color: MUTE, textTransform: "uppercase", marginBottom: 20 }}>分战线 · 战绩</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))", gap: 28 }}>
            {d.byProject.map((p) => (
              <div key={p.id}>
                <div style={{ fontFamily: mono, fontSize: 11, color: MUTE, letterSpacing: "0.08em" }}>{PROJECT_LABEL[p.id] ?? p.id}</div>
                <div style={{ fontFamily: fr, fontSize: "clamp(32px,4vw,52px)", fontWeight: 430, lineHeight: 1, marginTop: 8 }}>{cnNum(p.impressions)}</div>
                <div style={{ fontSize: 13, color: "#3D3A34", marginTop: 8 }}>{comma(p.notes)} 资产 · {comma(p.baokuan)} 爆款</div>
              </div>
            ))}
          </div>
        </section>

        <section style={{ borderTop: `1px solid ${BRASS}`, paddingTop: 32, margin: "32px 0 72px" }}>
          <div style={{ fontFamily: mono, fontSize: 11, letterSpacing: "0.2em", color: MUTE, textTransform: "uppercase", marginBottom: 16 }}>Top 爆款</div>
          {d.hits.map((h) => (
            <div key={h.rank} style={{ display: "grid", gridTemplateColumns: "40px 1fr 110px 130px", gap: 12, alignItems: "baseline", padding: "14px 0", borderBottom: "1px solid rgba(22,19,15,0.14)" }}>
              <span style={{ fontFamily: fr, fontSize: 22, color: h.rank === 1 ? CORAL : MUTE }}>{h.rank}</span>
              <span style={{ fontSize: 15 }}>{PROJECT_LABEL[h.project_id] ?? h.project_id}</span>
              <span style={{ fontFamily: mono, textAlign: "right", fontSize: 14 }}>{comma(h.interactions)}</span>
              <span style={{ fontFamily: mono, textAlign: "right", fontSize: 14, color: CORAL }}>{cnNum(h.impressions)}</span>
            </div>
          ))}
        </section>
      </div>
    </main>
  );
}

function Num({ k, v, sub }: { k: string; v: string; sub?: string }) {
  return (
    <div>
      <div style={{ fontFamily: fr, fontSize: "clamp(30px,4vw,52px)", fontWeight: 430, lineHeight: 1 }}>{v}</div>
      <div style={{ fontFamily: mono, fontSize: 11, letterSpacing: "0.1em", color: MUTE, textTransform: "uppercase", marginTop: 8 }}>{k}</div>
      {sub ? <div style={{ fontSize: 13, color: "#3D3A34", marginTop: 2 }}>{sub}</div> : null}
    </div>
  );
}
