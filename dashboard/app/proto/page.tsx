import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = { robots: { index: false, follow: false }, title: "设计原型对比 · BYWOOD" };

const protos = [
  { href: "/proto/bold-2", name: "⭐ BOLD BLOCKS · 融合版", ref: "Saving Goal 骨架 + Sci-Am 流 + AI-BL/TransGlobal 密度 + 实时", accent: "#F2542D", bg: "#0A0A0B", fg: "#C6F24E", desc: "骨架+血肉:色卡巨号 + 橙色汇聚流数据艺术 + KPI瓦片/活动热力/数据表 + 实时脉冲" },
  { href: "/proto/bold", name: "BOLD BLOCKS · 骨架版", ref: "Saving Goal ①", accent: "#F2542D", bg: "#0A0A0B", fg: "#DDE6D6", desc: "纯骨架(对照):色卡 + 巨号 + 渐隐列表" },
  { href: "/proto/terminal-x", name: "⚡ 情报终端 · 张力版", ref: "Bloomberg/Grafana + 辉光/数据流/动效", accent: "#36F1CD", bg: "#06070A", fg: "#36F1CD", desc: "深底辉光 + 桑基数据流 hero + 巨号发光数字 + 跑马灯(强视觉张力)" },
  { href: "/proto/ledger-x", name: "⚡ 数据编辑 · 张力版", ref: "Pentagram/IBM + 巨号/多色/动效", accent: "#E2402A", bg: "#F4F1E9", fg: "#15140E", desc: "超大数字 + 多色粗柱生长 + 重磅双线排版(强视觉张力)" },
  { href: "/proto/terminal", name: "情报终端 · 基础版", ref: "Bloomberg / Grafana / Tremor", accent: "#9EFF00", bg: "#0A0A0B", fg: "#c8cdd2", desc: "深底密集面板 + 状态灯(克制对照版)" },
  { href: "/proto/ledger", name: "数据编辑 · 基础版", ref: "Pentagram / IBM / Deloitte", accent: "#C0492F", bg: "#FAFAF7", fg: "#16150f", desc: "粗体排版 + 账本网格(克制对照版)" },
  { href: "/proto/blueprint", name: "蓝图网格 · Blueprint", ref: "Vercel / Linear / Stripe", accent: "#E8765A", bg: "#ffffff", fg: "#0a0a0a", desc: "高对比单色 + 网格肌理 + 等宽数字" },
  { href: "/proto/editorial", name: "编辑奢华 · Editorial", ref: "Anthropic / Stripe Press", accent: "#B08D57", bg: "#F5F1E8", fg: "#15130f", desc: "暖纸 + 衬线巨标 + 大留白" },
];

export default function ProtoIndex() {
  return (
    <main style={{ minHeight: "100vh", background: "#0C0B10", color: "#e8e6e3", fontFamily: "var(--font-geist-sans)" }}>
      <div style={{ maxWidth: 980, margin: "0 auto", padding: "48px 20px 64px" }}>
        <span className="tag" style={{ color: "#E8765A" }}>设计体系原型 · PROTOTYPES</span>
        <h1 style={{ fontSize: "clamp(28px,4vw,46px)", fontWeight: 800, letterSpacing: "-0.03em", margin: "8px 0 6px" }}>同一份真数据,四套设计语言</h1>
        <p className="mini" style={{ color: "#94a3b8", marginBottom: 28 }}>逐个点开对比 —— 选定后我把胜出那套铺满 首页 / 数据看板 / 内部座舱 三界面。</p>
        <div style={{ display: "grid", gap: 14, gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))" }}>
          {protos.map((p) => (
            <Link key={p.href} href={p.href} style={{ display: "block", borderRadius: 18, overflow: "hidden", border: "1px solid rgba(255,255,255,0.1)", textDecoration: "none", color: "inherit" }}>
              <div style={{ height: 92, background: p.bg, display: "flex", alignItems: "center", justifyContent: "center" }}>
                <span style={{ color: p.fg, fontWeight: 800, letterSpacing: "-0.02em" }}>{p.name.split(" · ")[0]}</span>
                <span style={{ width: 10, height: 10, borderRadius: 99, background: p.accent, marginLeft: 10 }} />
              </div>
              <div style={{ padding: "14px 16px", background: "rgba(255,255,255,0.04)" }}>
                <div style={{ fontWeight: 700, fontSize: 14 }}>{p.name}</div>
                <div className="mini" style={{ color: "#8A93A0", margin: "2px 0 8px" }}>{p.ref}</div>
                <div className="mini" style={{ color: "#aeb4bd", lineHeight: 1.5 }}>{p.desc}</div>
                <div className="tag" style={{ color: p.accent, marginTop: 10 }}>打开 →</div>
              </div>
            </Link>
          ))}
        </div>
      </div>
    </main>
  );
}
