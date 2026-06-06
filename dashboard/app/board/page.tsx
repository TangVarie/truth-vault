import Link from "next/link";
import type { Metadata } from "next";
import { cnNum, comma, PROJECT_LABEL } from "@/config/showcase";
import { getDashboardData } from "@/lib/dashboard-data";
import CountUp from "@/components/CountUp";
import LiveMonitor from "@/components/LiveMonitor";

/**
 * /board = 对外数据看板(公开、只读)。BOLD BLOCKS 设计体系 · 全部真实数据。
 * 口径:强调「战役组合 + 峰值」(不讲会下滑的时间线)。颜色 = 战线(语义化)。
 * 仅露体量/结果,无任何策略机理。
 */
export const metadata: Metadata = { title: "数据看板 · BYWOOD", description: "真实投放结果速览" };
export const dynamic = "force-dynamic";

const BG = "#0A0A0B", PANEL = "#141416", BORD = "rgba(255,255,255,0.08)";
const SAGE = "#DDE6D6", OLIVE = "#B0A41C", LAV = "#BFB9E6", CORAL = "#F2542D", LIME = "#C6F24E", INKC = "#0E0E0E", MUTE = "#8A8F98";
const FRONT = [CORAL, OLIVE, LAV, LIME]; // 4 条战线的语义色
const sans = "var(--font-geist-sans)", mono = "var(--font-geist-mono)";

const css = `
.bb-wrap{max-width:1280px;margin:0 auto;padding:18px 20px 56px}
.bb-grid{display:grid;grid-template-columns:repeat(12,1fr);gap:16px;align-items:stretch}
.bb-grid>*{min-width:0}
.s12{grid-column:span 12}.s8{grid-column:span 8}.s4{grid-column:span 4}.s3{grid-column:span 3}.s2{grid-column:span 2}
.bb-card{border-radius:28px;padding:24px 26px;display:flex;flex-direction:column}
.bb-tile{background:${PANEL};border:1px solid ${BORD};border-radius:20px;padding:18px 20px}
@media(max-width:920px){.bb-grid{grid-template-columns:repeat(6,1fr)}.s8{grid-column:span 6}.s4{grid-column:span 3}.s3{grid-column:span 3}.s2{grid-column:span 2}}
@media(max-width:560px){.bb-grid{grid-template-columns:repeat(2,1fr);gap:12px}.s12,.s8,.s4,.s3,.s2{grid-column:span 2}.bb-card{padding:20px}}
@keyframes bb-grow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
@keyframes bb-growy{from{transform:scaleY(0)}to{transform:scaleY(1)}}
@keyframes bb-pulse{0%,100%{opacity:.4;transform:scale(.85)}50%{opacity:1;transform:scale(1.2)}}
@keyframes bb-breathe{0%,100%{opacity:.65}50%{opacity:1}}
@keyframes bb-marq{0%{transform:translateX(0)}100%{transform:translateX(-50%)}}
.bb-seg{transform-origin:left;animation:bb-grow 1s cubic-bezier(.22,1,.36,1) both}
.bb-bar{transform-origin:bottom;animation:bb-growy .9s cubic-bezier(.22,1,.36,1) both}
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
  return <span style={{ display: "inline-flex", alignItems: "center", gap: 7, border: `1.5px solid ${dark ? "rgba(255,255,255,0.22)" : "rgba(0,0,0,0.42)"}`, color: dark ? "#fff" : INKC, borderRadius: 999, padding: "6px 14px", fontSize: 12.5, fontWeight: 600, alignSelf: "flex-start" }}>{children}</span>;
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
  const fronts = [...projects].sort((a, b) => b.impressions - a.impressions);
  const totalImp = fronts.reduce((s, p) => s + p.impressions, 0) || 1;
  const zero = { ym: "", impressions: 0, hits: 0, notes: 0, cum_impressions: 0 };
  const peakImp = monthly.reduce((m, x) => (x.impressions > m.impressions ? x : m), monthly[0] ?? zero);
  const peakHits = monthly.reduce((m, x) => (x.hits > m.hits ? x : m), monthly[0] ?? zero);
  const dow = [1, 2, 3, 4, 5, 6, 7].map((dw) => activity.filter((a) => a.dow === dw).reduce((s, a) => s + a.n, 0));
  const dowMax = Math.max(...dow, 1);
  const streams = streamPaths(72, 440, 360);
  const months = monthly.map((m) => m.ym);
  const span = months.length ? `${months[0]?.replace("-", ".")} – ${months[months.length - 1]?.replace("-", ".")}` : "";
  const ymFmt = (ym: string) => ym.replace("-", ".");
  const records = [
    { k: "单月最高曝光", v: cnNum(peakImp.impressions), s: ymFmt(peakImp.ym) },
    { k: "单篇最高互动", v: comma(o.topInteractions), s: "全周期" },
    { k: "峰值月爆款", v: String(peakHits.hits), s: ymFmt(peakHits.ym) },
  ];
  const totals = [
    { k: "内容资产", v: o.notes, fmt: "comma" as const },
    { k: "验证级爆款", v: o.baokuanReal, fmt: "comma" as const },
    { k: "策略经验卡", v: o.cards, fmt: "comma" as const },
    { k: "结构化内核", v: o.essence, fmt: "comma" as const },
    { k: "受众维度", v: o.audiences, fmt: "comma" as const },
    { k: "情绪杠杆", v: o.levers, fmt: "comma" as const },
  ];
  // 实时监测条:左栏端口/右栏计数全部真实(源自 pulse + overview)
  const livePorts = [
    { name: "飞书投放表", color: LIME, val: `已接入 ${comma(pulse?.feishu_n ?? o.notes)} 条` },
    { name: "ssll 资产库", color: LIME, val: `已回流 ${comma(pulse?.ssll_n ?? 0)} 条` },
    { name: "指标快照", color: LIME, val: `${comma(pulse?.snaps_n ?? 0)} 快照` },
    { name: "essence 解析", color: LAV, val: `已标注 ${comma(pulse?.annotated_n ?? o.essence)}/${comma(o.notes)}` },
    { name: "命中检测", color: CORAL, val: `${comma(o.baokuanReal)} 爆款判级` },
    { name: "autowriter", color: "#F5A623", val: "已接 · 待流" },
    { name: "内部座舱", color: LIME, val: `${comma(o.cards)} 策略卡` },
  ];
  const annoPct = o.notes ? Math.round(((pulse?.annotated_n ?? o.essence) / o.notes) * 100) : 0;
  const onlinePorts = [pulse?.feishu_n, pulse?.ssll_n, pulse?.snaps_n, pulse?.annotated_n, o.baokuanReal, o.cards].filter((x) => (x ?? 0) > 0).length;

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
          {/* ── hero(s8):巨号 + 战线构成堆叠条 ── + 汇聚流(s4) ── */}
          <section className="s8 bb-card" style={{ background: SAGE, color: INKC, justifyContent: "space-between" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><Pill>真实投放结果 · {o.projects} 条战线</Pill><span style={{ fontSize: 12, fontWeight: 600, opacity: 0.55 }}>{span}</span></div>
            <div style={{ marginTop: 18 }}>
              <div style={{ fontWeight: 800, letterSpacing: "-0.045em", lineHeight: 0.84, fontSize: "clamp(50px,8vw,120px)" }}><CountUp value={o.impressions} format="cn" duration={2200} /></div>
              <div style={{ fontSize: 13, fontWeight: 600, opacity: 0.62, marginTop: 6 }}>累计内容曝光 · 由 {o.projects} 条战线共同构成</div>
            </div>
            <div style={{ marginTop: 20 }}>
              <div style={{ display: "flex", height: 16, borderRadius: 999, overflow: "hidden", gap: 2 }}>
                {fronts.map((p, i) => <div key={p.project_id} className="bb-seg" style={{ width: `${Math.max(2, (p.impressions / totalImp) * 100)}%`, background: FRONT[i % 4], animationDelay: `${i * 0.12}s` }} />)}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 18px", marginTop: 12 }}>
                {fronts.map((p, i) => (
                  <span key={p.project_id} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12.5, fontWeight: 600 }}>
                    <span style={{ width: 9, height: 9, borderRadius: 3, background: FRONT[i % 4] }} />{PROJECT_LABEL[p.project_id] ?? p.project_id}<span style={{ opacity: 0.55 }}>{Math.round((p.impressions / totalImp) * 100)}%</span>
                  </span>
                ))}
              </div>
            </div>
          </section>

          <section className="s4 bb-card" style={{ background: "#0E0F12", border: `1px solid ${BORD}`, padding: "20px 22px", overflow: "hidden" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><Pill dark>全域数据汇聚</Pill><span style={{ fontSize: 11, color: CORAL, fontFamily: mono }}>● 实时</span></div>
            <div style={{ position: "relative", flex: 1, minHeight: 190, marginTop: 10 }}>
              <svg viewBox="0 0 440 360" width="100%" height="100%" preserveAspectRatio="none" className="bb-streams" style={{ position: "absolute", inset: 0 }}>
                <defs><linearGradient id="bb-st" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#F4A65C" stopOpacity="0" /><stop offset="35%" stopColor="#F4A65C" stopOpacity="0.5" /><stop offset="100%" stopColor="#F2542D" stopOpacity="0.92" /></linearGradient></defs>
                {streams.map((p, i) => <path key={i} id={`bbs-${i}`} d={p} fill="none" stroke="url(#bb-st)" strokeWidth="0.8" opacity="0.5" />)}
                {[5, 16, 28, 40, 52, 64].map((idx, k) => (
                  <circle key={`p${k}`} r="1.9" fill="#FBD08A">
                    <animateMotion dur={`${3 + k * 0.4}s`} begin={`${k * 0.45}s`} repeatCount="indefinite"><mpath href={`#bbs-${idx}`} /></animateMotion>
                  </circle>
                ))}
              </svg>
              <div style={{ position: "absolute", left: 0, bottom: 0 }}><div style={{ fontSize: 30, fontWeight: 800, letterSpacing: "-0.03em" }}>{comma(o.notes)}</div><div style={{ fontSize: 11, color: MUTE, fontFamily: mono }}>内容资产 → 收束 {comma(o.baokuanReal)} 爆款</div></div>
            </div>
          </section>

          {/* ── 按战线分段:4 个语义色块卡(s3 each)── */}
          {fronts.map((p, i) => (
            <section key={p.project_id} className="s3 bb-card" style={{ background: FRONT[i % 4], color: INKC, justifyContent: "space-between", minHeight: 168 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}><Pill>{PROJECT_LABEL[p.project_id] ?? p.project_id}</Pill><span style={{ fontSize: 11, fontWeight: 700, opacity: 0.6 }}>α{i + 1}</span></div>
              <div style={{ marginTop: 14 }}>
                <div style={{ fontWeight: 800, letterSpacing: "-0.04em", lineHeight: 0.9, fontSize: "clamp(32px,3.4vw,48px)" }}>{cnNum(p.impressions)}</div>
                <div style={{ fontSize: 12, fontWeight: 600, opacity: 0.6, marginTop: 4 }}>累计曝光</div>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5, fontWeight: 600, marginTop: 14 }}><span>{comma(p.notes)} 资产</span><span>{comma(p.baokuan)} 爆款</span></div>
            </section>
          ))}

          {/* ── 实时监测条(对外动效层:端口脉冲 + 事件流 + 跳动计数)── */}
          <section className="s12 bb-tile" style={{ padding: "18px 22px" }}>
            <LiveMonitor ports={livePorts} progress={annoPct} online={onlinePorts} total={7} />
          </section>

          {/* ── 战役期峰值(s8) + 投放节奏 周几(s4)── */}
          <section className="s8 bb-tile" style={{ justifyContent: "space-between" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}><Pill dark>战役期峰值 · PEAKS</Pill><span style={{ fontSize: 11, color: MUTE, fontFamily: mono }}>真实战绩天花板</span></div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 14 }}>
              {records.map((r, i) => (
                <div key={r.k} style={{ borderLeft: i ? `1px solid ${BORD}` : "none", paddingLeft: i ? 18 : 0 }}>
                  <div style={{ fontSize: 11.5, color: MUTE, fontFamily: mono, letterSpacing: "0.06em" }}>{r.k}</div>
                  <div style={{ fontSize: "clamp(30px,3.6vw,52px)", fontWeight: 800, letterSpacing: "-0.035em", color: CORAL, marginTop: 8, lineHeight: 1 }}>{r.v}</div>
                  <div style={{ fontSize: 11.5, color: MUTE, marginTop: 6, fontFamily: mono }}>{r.s}</div>
                </div>
              ))}
            </div>
          </section>

          <section className="s4 bb-tile" style={{ justifyContent: "space-between" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><Pill dark>投放节奏</Pill><span style={{ fontSize: 11, color: MUTE, fontFamily: mono }}>周一 → 周日</span></div>
            <div style={{ display: "flex", alignItems: "flex-end", gap: 8, height: 90, marginTop: 16 }}>
              {dow.map((n, i) => (
                <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "flex-end", height: "100%" }}>
                  <div className="bb-bar" style={{ width: "100%", maxWidth: 22, height: `${Math.max(4, (n / dowMax) * 72)}px`, background: LIME, borderRadius: 4, animationDelay: `${i * 0.05}s` }} />
                  <div style={{ fontSize: 10, color: MUTE, marginTop: 6, fontFamily: mono }}>{DOW[i]}</div>
                </div>
              ))}
            </div>
          </section>

          {/* ── Top 爆款明细(s12,满宽)── */}
          <section className="s12 bb-tile">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}><Pill dark>Top 爆款 · 明细</Pill><span style={{ fontSize: 11, color: MUTE, fontFamily: mono }}>共 {comma(o.baokuanReal)} 条 · 单篇最高 {comma(o.topInteractions)} 互动</span></div>
            <div style={{ display: "grid", gridTemplateColumns: "44px 1fr 130px 150px 70px", gap: 12, fontSize: 10.5, color: MUTE, fontFamily: mono, letterSpacing: "0.08em", paddingBottom: 8, borderBottom: `1px solid ${BORD}` }}><span>#</span><span>战线</span><span style={{ textAlign: "right" }}>互动</span><span style={{ textAlign: "right" }}>曝光</span><span style={{ textAlign: "right" }}>态</span></div>
            {hits.slice(0, 8).map((h, i) => (
              <div key={i} style={{ display: "grid", gridTemplateColumns: "44px 1fr 130px 150px 70px", gap: 12, alignItems: "center", padding: "11px 0", borderBottom: `1px solid ${BORD}`, fontSize: 14.5 }}>
                <span style={{ fontWeight: 800, color: h.rank === 1 ? CORAL : "#fff" }}>{h.rank}</span>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{PROJECT_LABEL[h.project_id] ?? h.project_id}</span>
                <span style={{ textAlign: "right", fontFamily: mono }}>{comma(h.interactions)}</span>
                <span style={{ textAlign: "right", fontFamily: mono, color: CORAL }}>{cnNum(h.impressions)}</span>
                <span style={{ textAlign: "right" }}><span style={{ fontSize: 11, fontWeight: 700, color: LIME, border: `1px solid ${LIME}66`, borderRadius: 999, padding: "2px 9px" }}>爆</span></span>
              </div>
            ))}
          </section>

          {/* ── 总量条(6×s2)── */}
          {totals.map((t) => (
            <div key={t.k} className="s2 bb-tile" style={{ padding: "14px 16px" }}>
              <div style={{ fontSize: 11, color: MUTE, fontFamily: mono, letterSpacing: "0.06em" }}>{t.k}</div>
              <div style={{ fontSize: 26, fontWeight: 800, letterSpacing: "-0.03em", marginTop: 6 }}><CountUp value={t.v} format={t.fmt} duration={1500} /></div>
            </div>
          ))}

          {/* ── 全域阵地 + 尤其擅长 ── */}
          <section className="s12 bb-tile" style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 14 }}>
            <div>
              <div style={{ fontFamily: mono, fontSize: 11, letterSpacing: "0.14em", color: MUTE, marginBottom: 10 }}>全域阵地 · CHANNELS</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {["小红书", "播客", "知乎", "今日头条", "微博"].map((c, i) => (
                  <span key={c} style={{ display: "inline-flex", alignItems: "center", gap: 7, border: `1px solid ${BORD}`, borderRadius: 999, padding: "7px 14px", fontSize: 13, fontWeight: 600 }}><span style={{ width: 7, height: 7, borderRadius: 99, background: i === 0 ? LIME : "#5b606b" }} />{c}</span>
                ))}
              </div>
            </div>
            <div style={{ fontSize: 12.5, color: MUTE, maxWidth: 320, lineHeight: 1.6 }}>尤其擅长 · 传统投放受限、达人接广受制的品类</div>
          </section>

          {/* ── 跑马灯(s12)── */}
          <section className="s12 bb-tile" style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ display: "flex", width: "max-content", animation: "bb-marq 28s linear infinite", fontSize: 11.5, color: MUTE, fontFamily: mono, padding: "10px 0" }}>
              {[0, 1].map((r) => <div key={r} style={{ display: "flex", gap: 26, paddingLeft: 26 }}><span style={{ color: LIME }}>● 数据实时直连</span><span>累计曝光 {cnNum(o.impressions)}</span><span>命中率 {hitRate}%</span><span>{comma(o.baokuanReal)} 验证级爆款</span><span>{comma(o.notes)} 内容资产</span><span>{o.projects} 条战线</span><span>单月峰值 {cnNum(peakImp.impressions)}</span></div>)}
            </div>
          </section>
          {/* ── 对外 CTA / 合作 ── */}
          <section className="s12 bb-card" style={{ background: LIME, color: INKC, padding: "clamp(26px,4vw,44px)" }}>
            <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", alignItems: "flex-end", gap: 20 }}>
              <div>
                <div style={{ fontFamily: mono, fontSize: 11, letterSpacing: "0.16em", opacity: 0.6 }}>LET&apos;S TALK</div>
                <h2 style={{ fontSize: "clamp(26px,3.4vw,46px)", fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1.06, marginTop: 8 }}>把你的品类,做成下一个<br />可查证的真实战绩。</h2>
              </div>
              <Link href="/" style={{ background: INKC, color: "#fff", borderRadius: 999, padding: "13px 28px", fontSize: 15, fontWeight: 700, textDecoration: "none" }}>预约策略咨询 →</Link>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "8px 12px", marginTop: 22, fontSize: 13, fontWeight: 600 }}>
              {["策略定制", "内容生产", "分发执行", "效果复盘"].map((s, i) => (
                <span key={s} style={{ display: "inline-flex", alignItems: "center", gap: 12 }}>{i > 0 ? <span style={{ opacity: 0.4 }}>→</span> : null}<span style={{ background: "rgba(14,14,14,0.1)", borderRadius: 999, padding: "6px 14px" }}>{s}</span></span>
              ))}
              <span style={{ fontFamily: mono, fontSize: 12, opacity: 0.6, marginLeft: 4 }}>全链路交付 · 每轮独立验收</span>
            </div>
          </section>
        </div>

        <footer style={{ marginTop: 26, display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8, fontSize: 11, color: "#5b606b" }}>
          <span>BYWOOD · ROC 增长智能中台 · 公开数据看板</span><span>数据实时直连 · 结果可查证</span>
        </footer>
      </div>
    </main>
  );
}
