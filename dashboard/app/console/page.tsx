import type { Metadata } from "next";
import Link from "next/link";
import { getDashboardData } from "@/lib/dashboard-data";
import { cnNum, comma, PROJECT_LABEL } from "@/config/showcase";
import CountUp from "@/components/CountUp";
import LiveMonitor from "@/components/LiveMonitor";

/** /console = 内部座舱(登录后)· BOLD BLOCKS · 含策略机理。数据全来自真库聚合视图。 */
export const metadata: Metadata = { robots: { index: false, follow: false }, title: "内部座舱 · BYWOOD" };
export const dynamic = "force-dynamic";

const BG = "#0A0A0B", PANEL = "#141416", BORD = "rgba(255,255,255,0.08)";
const SAGE = "#DDE6D6", OLIVE = "#B0A41C", LAV = "#BFB9E6", CORAL = "#F2542D", LIME = "#C6F24E", INKC = "#0E0E0E", MUTE = "#8A8F98";
const FRONT = [CORAL, OLIVE, LAV, LIME];
const sans = "var(--font-geist-sans)", mono = "var(--font-geist-mono)";
const VAL: Record<string, string> = { negative: "负向", positive: "正向", neutral: "中性", mixed: "复合" };
const INT: Record<string, string> = { high: "高强度", medium: "中强度", mid: "中强度", low: "低强度" };

const css = `
.cw{max-width:1280px;margin:0 auto;padding:0 20px 56px}
.cg{display:grid;grid-template-columns:repeat(12,1fr);gap:16px;align-items:stretch}
.cg>*{min-width:0}
.s12{grid-column:span 12}.s8{grid-column:span 8}.s6{grid-column:span 6}.s4{grid-column:span 4}.s3{grid-column:span 3}
.cc{border-radius:24px;padding:22px 24px;display:flex;flex-direction:column}
.ct{background:${PANEL};border:1px solid ${BORD};border-radius:20px;padding:18px 20px}
.canchor{scroll-margin-top:74px}
@media(max-width:920px){.cg{grid-template-columns:repeat(6,1fr)}.s12,.s8{grid-column:span 6}.s6{grid-column:span 6}.s4,.s3{grid-column:span 3}}
@media(max-width:560px){.cg{grid-template-columns:repeat(2,1fr);gap:12px}.s12,.s8,.s6,.s4,.s3{grid-column:span 2}}
@keyframes c-grow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
.c-bar{transform-origin:left;animation:c-grow .9s cubic-bezier(.22,1,.36,1) both}
`;

type Row = { label: string; n: number; rate: number };
function HitList({ title, sub, items, color, className }: { title: string; sub: string; items: Row[]; color: string; className: string }) {
  const max = Math.max(...items.map((i) => i.rate), 1);
  return (
    <section className={`${className} ct`}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}><h3 style={{ fontSize: 16, fontWeight: 800 }}>{title}</h3><span style={{ fontSize: 10.5, color: MUTE, fontFamily: mono }}>命中率</span></div>
      <p style={{ fontSize: 11.5, color: MUTE, marginTop: 4, marginBottom: 14 }}>{sub}</p>
      <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
        {items.slice(0, 7).map((it, i) => (
          <div key={it.label} style={{ display: "grid", gridTemplateColumns: "78px 1fr 42px", gap: 10, alignItems: "center" }}>
            <span style={{ fontSize: 12, color: "#cfd3da", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={it.label}>{it.label}</span>
            <span style={{ height: 8, background: "rgba(255,255,255,0.06)", borderRadius: 999, overflow: "hidden" }}><span className="c-bar" style={{ display: "block", height: "100%", width: `${Math.max(3, (it.rate / max) * 100)}%`, background: color, borderRadius: 999, animationDelay: `${i * 0.05}s` }} /></span>
            <span style={{ fontFamily: mono, fontSize: 12, fontWeight: 700, textAlign: "right" }}>{it.rate}%</span>
          </div>
        ))}
      </div>
    </section>
  );
}
function navPill(): React.CSSProperties { return { border: "1.5px solid rgba(255,255,255,0.18)", borderRadius: 999, padding: "5px 14px", fontSize: 12.5, fontWeight: 600, color: "#fff", textDecoration: "none" }; }

export default async function ConsolePage() {
  const d = await getDashboardData();
  const { o, matrix, valence, leverPerf, archetypes, audience, formats, reach, intent, funnel, projectPerf, pulse } = d;
  const hitRate = o.notes ? Math.round((o.baokuanReal / o.notes) * 1000) / 10 : 0;

  const byUse = [...leverPerf].sort((a, b) => b.n - a.n)[0];
  const byEff = [...leverPerf].filter((l) => l.n >= 20).sort((a, b) => b.hit_rate - a.hit_rate)[0] ?? leverPerf[0];

  const tot = (k: "lever" | "audience", v: string) => matrix.filter((m) => m[k] === v).reduce((s, m) => s + m.n, 0);
  const levOrder = Array.from(new Set(matrix.map((m) => m.lever))).sort((a, b) => tot("lever", b) - tot("lever", a)).slice(0, 8);
  const audOrder = Array.from(new Set(matrix.map((m) => m.audience))).sort((a, b) => tot("audience", b) - tot("audience", a)).slice(0, 7);
  const mIdx = new Map(matrix.map((m) => [`${m.lever}|${m.audience}`, m.n]));
  const mMax = Math.max(...matrix.map((m) => m.n), 1);
  const valOrder = Array.from(new Set(valence.map((v) => v.valence)));
  const intOrder = Array.from(new Set(valence.map((v) => v.intensity)));
  const vIdx = new Map(valence.map((v) => [`${v.valence}|${v.intensity}`, v]));
  const vMax = Math.max(...valence.map((v) => v.hit_rate), 1);

  const livePorts = [
    { name: "飞书投放表", color: LIME, val: `已接入 ${comma(pulse?.feishu_n ?? o.notes)} 条` },
    { name: "ssll 资产库", color: LIME, val: `已回流 ${comma(pulse?.ssll_n ?? 0)} 条` },
    { name: "指标快照", color: LIME, val: `${comma(pulse?.snaps_n ?? 0)} 快照` },
    { name: "essence 解析", color: LAV, val: `已标注 ${comma(pulse?.annotated_n ?? o.essence)}/${comma(o.notes)}` },
    { name: "命中检测", color: CORAL, val: `${comma(o.baokuanReal)} 爆款判级` },
    { name: "autowriter · 馆员", color: LIME, val: `${comma(o.cards)} 经验卡可借` },
  ];
  const annoPct = o.notes ? Math.round(((pulse?.annotated_n ?? o.essence) / o.notes) * 100) : 0;
  const onlinePorts = [pulse?.feishu_n, pulse?.ssll_n, pulse?.snaps_n, pulse?.annotated_n, o.baokuanReal, o.cards].filter((x) => (x ?? 0) > 0).length;
  const vitals = [
    { k: "命中率", v: hitRate + "%" }, { k: "内容资产", v: comma(o.notes) }, { k: "验证级爆款", v: comma(o.baokuanReal) },
    { k: "情绪杠杆", v: comma(o.levers) }, { k: "受众维度", v: comma(o.audiences) },
  ];
  const loop = [
    { t: "真实投放", c: CORAL }, { t: "结果回流", c: OLIVE }, { t: "爆款策展", c: LAV },
    { t: "馆员借阅", c: LIME }, { t: "反哺创作", c: CORAL }, { t: "命中率↑", c: OLIVE },
  ];

  return (
    <main style={{ minHeight: "100vh", background: BG, color: "#fff", fontFamily: sans }}>
      <style dangerouslySetInnerHTML={{ __html: css }} />
      {/* sticky nav + 分区锚点 */}
      <div style={{ position: "sticky", top: 0, zIndex: 40, background: "rgba(10,10,11,0.85)", backdropFilter: "blur(8px)", borderBottom: `1px solid ${BORD}`, marginBottom: 16 }}>
        <div style={{ maxWidth: 1280, margin: "0 auto", padding: "12px 20px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <Link href="/" style={{ fontWeight: 800, fontSize: 17, color: "#fff", textDecoration: "none" }}>BYWOOD <span style={{ color: "#6b7280" }}>· ROC 座舱</span></Link>
            <div style={{ display: "flex", gap: 6 }}>{[["#态势", "态势"], ["#机制", "机制"], ["#挖掘", "挖掘"], ["#战线", "战线"]].map(([h, t]) => <a key={h} href={h} style={{ fontSize: 12.5, fontWeight: 600, color: MUTE, textDecoration: "none", padding: "4px 9px" }}>{t}</a>)}</div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <Link href="/board" style={navPill()}>数据看板</Link>
            <form action="/api/auth/logout" method="POST"><button type="submit" style={{ ...navPill(), background: "transparent", cursor: "pointer" }}>登出</button></form>
          </div>
        </div>
      </div>

      <div className="cw">
        <div className="cg">
          {/* ── 态势 ── */}
          <section id="态势" className="s12 cc canchor" style={{ background: SAGE, color: INKC }}>
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-end", justifyContent: "space-between", gap: 24 }}>
              <div>
                <span style={{ display: "inline-flex", border: "1.5px solid rgba(0,0,0,0.4)", borderRadius: 999, padding: "6px 14px", fontSize: 12.5, fontWeight: 600 }}>态势 · 飞轮总览 · RESTRICTED</span>
                <div style={{ fontWeight: 800, letterSpacing: "-0.045em", lineHeight: 0.86, fontSize: "clamp(46px,7vw,104px)", marginTop: 16 }}><CountUp value={o.impressions} format="cn" duration={2000} /></div>
                <div style={{ fontSize: 13, fontWeight: 600, opacity: 0.6, marginTop: 6 }}>累计内容曝光 · {o.projects} 条战线</div>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(96px,1fr))", gap: "16px 22px", maxWidth: 520 }}>
                {vitals.map((v) => <div key={v.k}><div style={{ fontSize: "clamp(22px,2.2vw,32px)", fontWeight: 800, letterSpacing: "-0.02em" }}>{v.v}</div><div style={{ fontFamily: mono, fontSize: 10.5, opacity: 0.55, marginTop: 4 }}>{v.k}</div></div>)}
              </div>
            </div>
          </section>
          <section className="s12 ct" style={{ padding: "18px 22px" }}><LiveMonitor ports={livePorts} progress={annoPct} online={onlinePorts} total={7} /></section>

          {/* ── 机制:飞轮 / 馆员 / 去中心化 ── */}
          <section id="机制" className="s12 cc canchor" style={{ background: PANEL, border: `1px solid ${BORD}` }}>
            <span style={{ display: "inline-flex", border: `1.5px solid ${BORD}`, borderRadius: 999, padding: "6px 14px", fontSize: 12.5, fontWeight: 600, color: "#fff", alignSelf: "flex-start" }}>飞轮机制 · 越用越强</span>
            <h2 style={{ fontSize: "clamp(24px,3vw,40px)", fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1.12, marginTop: 14 }}>数据是数据。机制,是<span style={{ color: CORAL }}>另一种力量</span>。</h2>
            <p style={{ fontSize: 14, lineHeight: 1.65, color: "#aeb4bd", marginTop: 10, maxWidth: 720 }}>真实结果回流 → 爆款被策展进库 → 写稿时 LLM 馆员按 brief 来「借」最匹配的经验 → 反哺创作。被筛掉的内容也成训练素材。体系越用越准,而不是靠堆人头。</p>
            <div style={{ display: "grid", gridTemplateColumns: "minmax(0,320px) minmax(0,1fr)", gap: 22, marginTop: 18, alignItems: "center" }}>
              {/* 飞轮环(轨道脉冲)*/}
              <svg viewBox="0 0 320 320" width="100%" style={{ maxWidth: 320, margin: "0 auto" }}>
                <defs><radialGradient id="fw-core"><stop offset="0%" stopColor={CORAL} stopOpacity="0.55" /><stop offset="100%" stopColor={CORAL} stopOpacity="0" /></radialGradient></defs>
                <circle cx="160" cy="160" r="112" fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth="1.5" strokeDasharray="3 6" />
                <circle cx="160" cy="160" r="46" fill="url(#fw-core)" />
                <text x="160" y="156" textAnchor="middle" style={{ fontSize: 16, fontWeight: 800, fill: "#fff" }}>飞轮</text>
                <text x="160" y="173" textAnchor="middle" style={{ fontSize: 9, fill: MUTE, fontFamily: mono, letterSpacing: "0.12em" }}>COMPOUND</text>
                {loop.map((n, i) => {
                  const a = (-90 + i * 60) * Math.PI / 180;
                  const x = 160 + 112 * Math.cos(a), y = 160 + 112 * Math.sin(a);
                  const lx = 160 + 140 * Math.cos(a), ly = 160 + 140 * Math.sin(a);
                  const anc = Math.abs(Math.cos(a)) < 0.35 ? "middle" : Math.cos(a) > 0 ? "start" : "end";
                  return (<g key={n.t}><circle cx={x} cy={y} r="6" fill={n.c} /><text x={lx} y={ly + 3} textAnchor={anc} style={{ fontSize: 11, fontWeight: 600, fill: "#cfd3da" }}>{n.t}</text></g>);
                })}
                <circle cx="160" cy="48" r="5" fill={LIME} style={{ filter: `drop-shadow(0 0 6px ${LIME})` }}><animateTransform attributeName="transform" type="rotate" from="0 160 160" to="360 160 160" dur="6s" repeatCount="indefinite" /></circle>
                <circle cx="160" cy="48" r="3" fill="#fff"><animateTransform attributeName="transform" type="rotate" from="150 160 160" to="510 160 160" dur="6s" repeatCount="indefinite" /></circle>
              </svg>
              {/* 馆员 + 去中心化 */}
              <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                <div style={{ border: `1px solid rgba(198,242,78,0.3)`, borderRadius: 16, padding: "16px 18px", background: "rgba(198,242,78,0.05)" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><span style={{ fontSize: 15, fontWeight: 800 }}>📚 馆员模式 · 已上线</span><span style={{ fontFamily: mono, fontSize: 20, fontWeight: 800, color: LIME }}>{comma(o.cards)}</span></div>
                  <p style={{ fontSize: 12.5, color: "#aeb4bd", marginTop: 8, lineHeight: 1.6 }}>不把爆款硬塞给写手 —— <b style={{ color: "#fff" }}>{comma(o.cards)} 条</b>策展经验卡进库,LLM 馆员写稿时按 brief 来借最匹配的。合作越久、库越厚、命中越高。</p>
                </div>
                <div style={{ border: `1px dashed ${BORD}`, borderRadius: 16, padding: "16px 18px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><span style={{ fontSize: 15, fontWeight: 800 }}>🌐 去中心化分发 · 规划中</span><span style={{ fontFamily: mono, fontSize: 10.5, color: MUTE, border: `1px solid ${BORD}`, borderRadius: 999, padding: "2px 8px" }}>ROADMAP</span></div>
                  <p style={{ fontSize: 12.5, color: "#aeb4bd", marginTop: 8, lineHeight: 1.6 }}>一份策略,由全国不同真人节点各自表达 —— 一百个真实声音,不是一百篇同质内容。分发去中心化,占位更难被复制。</p>
                  <svg viewBox="0 0 240 60" width="100%" height="50" style={{ marginTop: 8 }} aria-hidden>
                    {[0, 1, 2, 3, 4, 5, 6].map((i) => { const x = 22 + i * 32.6, y = i % 2 ? 16 : 44; return (<g key={i}><line x1="120" y1="30" x2={x} y2={y} stroke="rgba(255,255,255,0.12)" strokeDasharray="2 3" /><circle cx={x} cy={y} r="4" fill={i === 3 ? CORAL : "#5b606b"}><animate attributeName="opacity" values="0.35;1;0.35" dur={`${2 + i * 0.3}s`} repeatCount="indefinite" /></circle></g>); })}
                    <circle cx="120" cy="30" r="7" fill={CORAL} />
                  </svg>
                </div>
              </div>
            </div>
          </section>

          {/* ── 挖掘 ── */}
          <div id="挖掘" className="s12 canchor" style={{ height: 0 }} />
          {byUse && byEff && (
            <section className="s12 cc" style={{ background: CORAL, color: INKC }}>
              <span style={{ display: "inline-flex", border: "1.5px solid rgba(0,0,0,0.4)", borderRadius: 999, padding: "6px 14px", fontSize: 12.5, fontWeight: 600, alignSelf: "flex-start" }}>核心洞察 · WHY IT HITS</span>
              <p style={{ fontSize: "clamp(18px,2.2vw,28px)", fontWeight: 700, lineHeight: 1.4, marginTop: 16, maxWidth: 980 }}>最常用的「{byUse.lever}」用了 <b>{comma(byUse.n)}</b> 篇,命中仅 <b>{byUse.hit_rate}%</b>;而「{byEff.lever}」命中 <b>{byEff.hit_rate}%</b> —— 你投得最多的,往往不是最有效的。</p>
            </section>
          )}
          <HitList className="s6" title="情绪杠杆 · 命中率" sub="高强度负面/羞耻系胜出,泛共鸣不出" color={CORAL} items={leverPerf.map((l) => ({ label: l.lever, n: l.n, rate: l.hit_rate }))} />
          <HitList className="s6" title="人性原型 · 命中率" sub="焦虑/冲突系胜出" color={LAV} items={archetypes.map((a) => ({ label: a.archetype, n: a.n, rate: a.hit_rate }))} />
          <HitList className="s4" title="受众 · 命中率" sub="具体共情受众胜出,通用是黑洞" color={OLIVE} items={audience.map((a) => ({ label: a.audience, n: a.n, rate: a.hit_rate }))} />
          <HitList className="s4" title="内容形态 · 命中率" sub="情感叙事赢,直给推销不出" color={LIME} items={formats.map((f) => ({ label: f.fmt, n: f.n, rate: f.hit_rate }))} />
          {reach && (
            <section className="s4 ct">
              <h3 style={{ fontSize: 16, fontWeight: 800 }}>触达集中度</h3><p style={{ fontSize: 11.5, color: MUTE, marginTop: 4 }}>爆款即一切 · 二八之上</p>
              <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginTop: 14 }}><span style={{ fontSize: "clamp(34px,4vw,52px)", fontWeight: 800, color: CORAL, letterSpacing: "-0.03em" }}>{reach.hit_reach_share}%</span><span style={{ fontSize: 12, color: MUTE }}>的触达<br />来自 {reach.hit_note_pct}% 爆款</span></div>
              <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 8 }}>
                {[{ l: "Top 1% 内容", v: reach.top1_share }, { l: "Top 5% 内容", v: reach.top5_share }, { l: `爆+大爆 ${reach.hit_note_pct}%`, v: reach.hit_reach_share }].map((r) => (
                  <div key={r.l} style={{ display: "grid", gridTemplateColumns: "92px 1fr 42px", gap: 8, alignItems: "center" }}><span style={{ fontSize: 11, color: "#cfd3da" }}>{r.l}</span><span style={{ height: 8, background: "rgba(255,255,255,0.06)", borderRadius: 999 }}><span style={{ display: "block", height: "100%", width: `${Math.min(100, r.v)}%`, background: CORAL, borderRadius: 999 }} /></span><span style={{ fontFamily: mono, fontSize: 12, fontWeight: 700, textAlign: "right" }}>{r.v}%</span></div>
                ))}
              </div>
            </section>
          )}
          {/* 共振矩阵 */}
          {levOrder.length > 0 && (
            <section className="s8 ct">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}><h3 style={{ fontSize: 16, fontWeight: 800 }}>策略 × 受众 · 共振矩阵</h3><span style={{ fontSize: 10.5, color: MUTE, fontFamily: mono }}>深 = 该组合内容多</span></div>
              <div style={{ overflowX: "auto", marginTop: 14 }}>
                <div style={{ minWidth: 460 }}>
                  <div style={{ display: "grid", gridTemplateColumns: `92px repeat(${audOrder.length},1fr)`, gap: 4 }}>
                    <span />
                    {audOrder.map((a) => <span key={a} title={a} style={{ fontSize: 9.5, color: MUTE, textAlign: "center", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a}</span>)}
                    {levOrder.map((lev) => (
                      <Cells key={lev} lev={lev} audOrder={audOrder} mIdx={mIdx} mMax={mMax} />
                    ))}
                  </div>
                </div>
              </div>
            </section>
          )}
          {/* 效价 × 强度 */}
          {valOrder.length > 0 && (
            <section className="s4 ct">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}><h3 style={{ fontSize: 16, fontWeight: 800 }}>效价 × 强度</h3><span style={{ fontSize: 10.5, color: MUTE, fontFamily: mono }}>命中率</span></div>
              <div style={{ display: "grid", gridTemplateColumns: `64px repeat(${intOrder.length},1fr)`, gap: 5, marginTop: 14 }}>
                <span />
                {intOrder.map((it) => <span key={it} style={{ fontSize: 10, color: MUTE, textAlign: "center" }}>{INT[it] ?? it}</span>)}
                {valOrder.map((va) => (
                  <Fragmentish key={va} va={va} intOrder={intOrder} vIdx={vIdx} vMax={vMax} />
                ))}
              </div>
            </section>
          )}
          {/* 意图 + tier 漏斗 */}
          <section className="s6 ct">
            <h3 style={{ fontSize: 16, fontWeight: 800 }}>意图分野</h3><p style={{ fontSize: 11.5, color: MUTE, marginTop: 4, marginBottom: 14 }}>种草出爆款,转化几乎不出</p>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {intent.map((it) => (
                <div key={it.intent} style={{ display: "grid", gridTemplateColumns: "84px 1fr 74px", gap: 10, alignItems: "center" }}><span style={{ fontSize: 13, color: "#cfd3da" }}>{it.intent === "traffic" ? "种草 traffic" : it.intent === "conversion" ? "转化 conversion" : it.intent}</span><span style={{ height: 10, background: "rgba(255,255,255,0.06)", borderRadius: 999 }}><span style={{ display: "block", height: "100%", width: `${Math.max(2, Math.min(100, it.hit_rate * 8))}%`, background: LIME, borderRadius: 999 }} /></span><span style={{ fontFamily: mono, fontSize: 11.5, textAlign: "right" }}>{it.hit_rate}% · {comma(it.n)}</span></div>
              ))}
            </div>
          </section>
          <section className="s6 ct">
            <h3 style={{ fontSize: 16, fontWeight: 800 }}>爆款漏斗 · tier</h3><p style={{ fontSize: 11.5, color: MUTE, marginTop: 4, marginBottom: 14 }}>层级越高,读完率/互动率/篇均曝光越高</p>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {funnel.map((f) => (
                <div key={f.tier} style={{ display: "grid", gridTemplateColumns: "60px 1fr 90px", gap: 10, alignItems: "center" }}><span style={{ fontSize: 13, color: "#cfd3da" }}>{f.tier}</span><span style={{ fontFamily: mono, fontSize: 11, color: MUTE }}>读完 {f.read_rate}% · 互动 {f.inter_rate}%</span><span style={{ fontFamily: mono, fontSize: 12, color: CORAL, textAlign: "right" }}>{cnNum(f.avg_imp)}</span></div>
              ))}
            </div>
          </section>

          {/* ── 战线 ── */}
          <div id="战线" className="s12 canchor" style={{ height: 0 }} />
          {projectPerf.slice(0, 4).map((p, i) => (
            <section key={p.project_id} className="s3 cc" style={{ background: FRONT[i % 4], color: INKC, justifyContent: "space-between", minHeight: 150 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}><span style={{ fontSize: 13, fontWeight: 700 }}>{PROJECT_LABEL[p.project_id] ?? p.project_id}</span><span style={{ fontSize: 11, opacity: 0.6 }}>{p.category}</span></div>
              <div style={{ marginTop: 12 }}><div style={{ fontSize: "clamp(30px,3vw,44px)", fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 0.9 }}>{p.hit_rate}%</div><div style={{ fontSize: 12, fontWeight: 600, opacity: 0.6, marginTop: 3 }}>命中率</div></div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, fontWeight: 600, marginTop: 12 }}><span>{comma(p.notes)} 资产</span><span>{cnNum(p.total_imp)} 曝光</span></div>
            </section>
          ))}
        </div>
      </div>
    </main>
  );
}

function Cells({ lev, audOrder, mIdx, mMax }: { lev: string; audOrder: string[]; mIdx: Map<string, number>; mMax: number }) {
  return (
    <>
      <span style={{ fontSize: 11, color: "#cfd3da", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "flex", alignItems: "center" }} title={lev}>{lev}</span>
      {audOrder.map((a) => {
        const n = mIdx.get(`${lev}|${a}`) ?? 0;
        const r = n / mMax;
        return <span key={a} title={`${lev} × ${a}: ${n}`} style={{ aspectRatio: "1", borderRadius: 5, background: n === 0 ? "rgba(255,255,255,0.03)" : `rgba(242,84,45,${(0.12 + r * 0.8).toFixed(2)})`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9.5, fontWeight: 700, color: r > 0.5 ? "#0E0E0E" : "#cfd3da" }}>{n || ""}</span>;
      })}
    </>
  );
}
function Fragmentish({ va, intOrder, vIdx, vMax }: { va: string; intOrder: string[]; vIdx: Map<string, { hit_rate: number; n: number }>; vMax: number }) {
  return (
    <>
      <span style={{ fontSize: 11, color: "#cfd3da", display: "flex", alignItems: "center" }}>{VAL[va] ?? va}</span>
      {intOrder.map((it) => {
        const cell = vIdx.get(`${va}|${it}`);
        const rate = cell?.hit_rate ?? 0;
        const r = rate / vMax;
        return <span key={it} title={`${VAL[va] ?? va} · ${INT[it] ?? it}: ${rate}%`} style={{ aspectRatio: "1.4", borderRadius: 6, background: rate === 0 ? "rgba(255,255,255,0.03)" : `rgba(242,84,45,${(0.12 + r * 0.8).toFixed(2)})`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, color: r > 0.5 ? "#0E0E0E" : "#cfd3da" }}>{rate ? rate + "%" : ""}</span>;
      })}
    </>
  );
}
