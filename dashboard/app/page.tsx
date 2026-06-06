import Link from "next/link";
import { getDashboardData } from "@/lib/dashboard-data";
import { cnNum, comma } from "@/config/showcase";

/**
 * `/` = 公开首页(品牌 + 方法论)。BOLD BLOCKS 设计体系。
 * 内容取自 BYWOOD 名片/方法论(身份 → 增长链路 → 典型问题 → 扶摇 ROC → 为什么越久越值钱)。
 * 不重复座舱/看板的数据明细(只放极简战绩证明 + 入口)。
 */
export const dynamic = "force-dynamic";

const BG = "#0A0A0B", PANEL = "#141416", BORD = "rgba(255,255,255,0.08)";
const SAGE = "#DDE6D6", OLIVE = "#B0A41C", LAV = "#BFB9E6", CORAL = "#F2542D", LIME = "#C6F24E", INKC = "#0E0E0E", MUTE = "#8A8F98";
const sans = "var(--font-geist-sans)", mono = "var(--font-geist-mono)";

function Eyebrow({ children }: { children: React.ReactNode }) {
  return <div style={{ fontFamily: mono, fontSize: 11, letterSpacing: "0.18em", textTransform: "uppercase", color: MUTE }}>{children}</div>;
}
function Pill({ children, dark = false }: { children: React.ReactNode; dark?: boolean }) {
  return <span style={{ display: "inline-flex", alignItems: "center", gap: 7, border: `1.5px solid ${dark ? "rgba(255,255,255,0.22)" : "rgba(0,0,0,0.45)"}`, color: dark ? "#fff" : INKC, borderRadius: 999, padding: "7px 16px", fontSize: 13, fontWeight: 600 }}>{children}</span>;
}

const LINK = [
  { k: "心智", e: "MIND", d: "内容种草 / 建立心智", n: "01", c: SAGE },
  { k: "决策", e: "DEMAND", d: "搜索承接 / 完成决策", n: "02", c: LAV },
  { k: "复利", e: "COMPOUND", d: "数据飞轮 / 持续复利", n: "03", c: CORAL },
];
const SOLVE = [
  { t: "新品类没人懂", d: "市场无认知基础 —— 从零建立话题、定义认知入口。", c: CORAL },
  { t: "敏感品类没法投", d: "达人不敢接、审核严、投流过不了,传统打法失效。", c: OLIVE },
  { t: "投完留不住", d: "项目结束声量归零,钱花了没有积累。", c: LAV },
  { t: "被种草不下单", d: "验证时信息空白或被竞品占据,临门一脚踢空。", c: LIME },
];
const ROC = [
  { k: "R", t: "关键词工程", h: "建立内容根据地", d: "设计关键词矩阵 → 素人高密度发布 → 推动平台识别为热门话题(「蓝词」)", c: CORAL },
  { k: "O", t: "场景化引爆", h: "让用户主动来搜", d: "产品植入真实生活场景,制造好奇与讨论欲 —— 关键词从「被植入」变「被讨论」", c: OLIVE },
  { k: "C", t: "承接转化", h: "从触达到说服", d: "无论用户从哪条路径来验证,都进入内容充分、口碑正向、链路闭环的品牌生态", c: LIME },
];
const WHY = [
  { t: "生产体系", hl: "不靠堆人头", d: "一套自研架构改写「产能＝人力」的等式。同一信息由全国不同真人各自表达 —— 一百个真实声音,不是一百篇同质内容。", c: SAGE },
  { t: "数据飞轮", hl: "越用越强", d: "体系不是静态的。被筛掉的内容成为训练素材反哺生产,效果数据沉淀为专属策略库 —— 合作越久,命中率越高。", c: LAV },
  { t: "资产累积", hl: "不是消耗型", d: "每轮新增优质内容为上一轮占位加固。不是投完就没的广告费,是越久越值钱的品牌壁垒。", c: CORAL },
];

export default async function Page() {
  const { o } = await getDashboardData();
  const hitRate = o.notes ? Math.round((o.baokuanReal / o.notes) * 1000) / 10 : 0;
  const proof = [
    { k: "累计内容曝光", v: cnNum(o.impressions) },
    { k: "内容资产", v: comma(o.notes) },
    { k: "验证级爆款", v: comma(o.baokuanReal) },
    { k: "命中率", v: hitRate + "%" },
  ];

  return (
    <main style={{ minHeight: "100vh", background: BG, color: "#fff", fontFamily: sans }}>
      <div style={{ maxWidth: 1180, margin: "0 auto", padding: "18px 20px 64px" }}>
        {/* nav */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
          <span style={{ fontWeight: 800, fontSize: 19, letterSpacing: "-0.01em" }}>BYWOOD <span style={{ color: "#6b7280" }}>芭梧</span></span>
          <div style={{ display: "flex", gap: 8 }}>
            <Link href="/board" style={{ border: "1.5px solid rgba(255,255,255,0.22)", borderRadius: 999, padding: "7px 16px", fontSize: 13, fontWeight: 600, color: "#fff", textDecoration: "none" }}>数据看板</Link>
            <Link href="/console" style={{ border: "1.5px solid rgba(255,255,255,0.22)", borderRadius: 999, padding: "7px 16px", fontSize: 13, fontWeight: 600, color: "#fff", textDecoration: "none" }}>团队登录</Link>
          </div>
        </div>

        {/* ── 身份 hero(sage 大卡)── */}
        <section style={{ background: SAGE, color: INKC, borderRadius: 30, padding: "clamp(28px,4vw,52px)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
            <Pill>体系化增长服务商 · SYSTEMATIC GROWTH</Pill>
            <span style={{ fontFamily: mono, fontSize: 11, letterSpacing: "0.16em", opacity: 0.5 }}>WHAT WE DO</span>
          </div>
          <h1 style={{ fontSize: "clamp(34px,6vw,80px)", fontWeight: 800, letterSpacing: "-0.04em", lineHeight: 1.02, marginTop: 22, maxWidth: 900 }}>
            从策略到执行到效果,<br />一站式 <span style={{ color: CORAL }}>增长服务</span>。
          </h1>
          <p style={{ fontSize: "clamp(15px,1.5vw,18px)", lineHeight: 1.6, marginTop: 20, maxWidth: 620, opacity: 0.82 }}>
            把策略翻译成可滚动执行、可独立交付、可累积加固的增长动作 —— 解决新品教育、品类占位、口碑建设、搜索拦截。
          </p>
          <div style={{ display: "flex", gap: 12, marginTop: 28, flexWrap: "wrap" }}>
            <Link href="/board" style={{ background: INKC, color: "#fff", borderRadius: 999, padding: "13px 26px", fontSize: 15, fontWeight: 700, textDecoration: "none" }}>查看真实战绩 →</Link>
            <span style={{ display: "inline-flex", alignItems: "center", fontSize: 13, fontWeight: 600, opacity: 0.6 }}>全域阵地 · 小红书 / 播客 / 知乎 / 今日头条 / 微博</span>
          </div>
          {/* 极简战绩证明 */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(120px,1fr))", gap: 18, marginTop: 32, borderTop: "1px solid rgba(14,14,14,0.14)", paddingTop: 24 }}>
            {proof.map((p) => (
              <div key={p.k}><div style={{ fontSize: "clamp(24px,2.6vw,38px)", fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1 }}>{p.v}</div><div style={{ fontFamily: mono, fontSize: 11, letterSpacing: "0.08em", opacity: 0.55, marginTop: 6 }}>{p.k}</div></div>
            ))}
          </div>
        </section>

        {/* ── 增长链路:心智 → 决策 → 复利 ── */}
        <section style={{ marginTop: 40 }}>
          <Eyebrow>GROWTH LINK · 增长链路(我们的增长逻辑)</Eyebrow>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))", gap: 16, marginTop: 16 }}>
            {LINK.map((s) => (
              <div key={s.k} style={{ background: s.c, color: INKC, borderRadius: 24, padding: "24px 26px", minHeight: 150, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}><span style={{ fontWeight: 800, fontSize: "clamp(28px,3vw,40px)", letterSpacing: "-0.02em" }}>{s.k} <span style={{ fontFamily: mono, fontSize: 13, fontWeight: 600, opacity: 0.5 }}>{s.e}</span></span><span style={{ fontFamily: mono, fontSize: 13, opacity: 0.5 }}>{s.n}</span></div>
                <div style={{ fontSize: 15, fontWeight: 600, marginTop: 20, opacity: 0.82 }}>{s.d}</div>
              </div>
            ))}
          </div>
        </section>

        {/* ── 我们解决的典型问题 ── */}
        <section style={{ marginTop: 40 }}>
          <Eyebrow>WE SOLVE · 我们解决的典型问题</Eyebrow>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))", gap: 16, marginTop: 16 }}>
            {SOLVE.map((s) => (
              <div key={s.t} style={{ background: PANEL, border: `1px solid ${BORD}`, borderRadius: 20, padding: "22px 24px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 12 }}><span style={{ width: 10, height: 10, borderRadius: 3, background: s.c }} /><span style={{ fontSize: 18, fontWeight: 800, letterSpacing: "-0.01em" }}>{s.t}</span></div>
                <p style={{ fontSize: 14, lineHeight: 1.6, color: "#aeb4bd" }}>{s.d}</p>
              </div>
            ))}
          </div>
          <div style={{ fontFamily: mono, fontSize: 12, color: MUTE, marginTop: 16 }}>尤其擅长 · 传统投放受限 / 达人接广受制的品类</div>
        </section>

        {/* ── 扶摇 ROC 方法论 ── */}
        <section style={{ marginTop: 40, background: PANEL, border: `1px solid ${BORD}`, borderRadius: 30, padding: "clamp(28px,4vw,48px)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: 12 }}>
            <div><Eyebrow>核心方法论 · OUR METHOD</Eyebrow><h2 style={{ fontSize: "clamp(40px,6vw,80px)", fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1, marginTop: 10 }}>扶摇 <span style={{ color: LIME }}>ROC</span></h2></div>
            <p style={{ fontSize: 14, lineHeight: 1.6, color: "#aeb4bd", maxWidth: 360 }}>自研体系化执行框架 —— 围绕品牌目标设计策略、滚动执行,<b style={{ color: "#fff" }}>三步为一轮、每轮递进</b>。</p>
          </div>
          <div style={{ marginTop: 28 }}>
            {ROC.map((r, i) => (
              <div key={r.k} style={{ display: "grid", gridTemplateColumns: "60px 150px 1fr", gap: "16px", alignItems: "center", padding: "20px 0", borderTop: i ? `1px solid ${BORD}` : "none" }}>
                <span style={{ fontSize: "clamp(34px,4vw,52px)", fontWeight: 800, color: r.c, lineHeight: 1 }}>{r.k}</span>
                <div><div style={{ fontSize: 16, fontWeight: 700 }}>{r.t}</div><div style={{ fontFamily: mono, fontSize: 12, color: MUTE, marginTop: 3 }}>{r.h} →</div></div>
                <p style={{ fontSize: 14, lineHeight: 1.6, color: "#aeb4bd" }}>{r.d}</p>
              </div>
            ))}
          </div>
        </section>

        {/* ── 为什么越久越值钱 ── */}
        <section style={{ marginTop: 40 }}>
          <Eyebrow>WHY US · 为什么越久越值钱</Eyebrow>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(260px,1fr))", gap: 16, marginTop: 16 }}>
            {WHY.map((w) => (
              <div key={w.t} style={{ background: w.c, color: INKC, borderRadius: 24, padding: "24px 26px" }}>
                <div style={{ fontSize: 20, fontWeight: 800, letterSpacing: "-0.01em" }}>{w.t} · <span style={{ color: w.c === LAV ? "#5b3fb0" : w.c === SAGE ? "#2f6b4a" : "#7a1f12" }}>{w.hl}</span></div>
                <p style={{ fontSize: 14, lineHeight: 1.65, marginTop: 12, opacity: 0.85 }}>{w.d}</p>
              </div>
            ))}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "8px 28px", marginTop: 18, fontFamily: mono, fontSize: 12, color: MUTE }}>
            <span><span style={{ color: "#fff" }}>交付</span> · 每轮独立交付验收:效果指标 + 资产指标双口径,写进合同</span>
            <span><span style={{ color: "#fff" }}>合作</span> · 策略定制 → 内容生产 → 分发执行 → 效果复盘,全链路交付</span>
          </div>
        </section>

        {/* ── 收尾 slogan ── */}
        <section style={{ marginTop: 44, marginBottom: 12 }}>
          <h2 style={{ fontSize: "clamp(34px,6.5vw,90px)", fontWeight: 800, letterSpacing: "-0.04em", lineHeight: 1.02 }}>
            不是堆人头,<span style={{ color: CORAL }}>是结构性复利。</span>
          </h2>
          <div style={{ display: "flex", gap: 12, marginTop: 28, flexWrap: "wrap" }}>
            <Link href="/board" style={{ background: LIME, color: INKC, borderRadius: 999, padding: "13px 26px", fontSize: 15, fontWeight: 700, textDecoration: "none" }}>查看数据看板 →</Link>
            <Link href="/console" style={{ border: "1.5px solid rgba(255,255,255,0.25)", color: "#fff", borderRadius: 999, padding: "13px 26px", fontSize: 15, fontWeight: 700, textDecoration: "none" }}>团队登录</Link>
          </div>
        </section>

        <footer style={{ marginTop: 36, borderTop: `1px solid ${BORD}`, paddingTop: 18, display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8, fontFamily: mono, fontSize: 11, color: "#5b606b" }}>
          <span>BYWOOD 芭梧 · 体系化增长服务商</span><span>ROC · 三步为一轮 · 越用越强</span>
        </footer>
      </div>
    </main>
  );
}
