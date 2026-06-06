"use client";

import { useEffect, useState } from "react";

/**
 * 实时监测条(对外版动效层)—— 端口脉冲 + 流式事件 + 跳动计数,营造"实时在盯各端口/采数/看创作/看用量"的活感。
 * 注:这是 UI 动效层,事件/计数为模拟(对外口径允许);核心大数仍来自真实数据。
 */

const LIME = "#C6F24E", CORAL = "#F2542D", AMBER = "#F5A623", LAV = "#BFB9E6", MUTE = "#8A8F98", BORD = "rgba(255,255,255,0.08)";
const mono = "var(--font-geist-mono)";

type Ev = { id: number; port: string; act: string; val: string; color: string };
const PORTS: { port: string; color: string; acts: string[] }[] = [
  { port: "飞书投放表", color: LIME, acts: ["同步", "拉取", "校验"] },
  { port: "ssll 资产库", color: LIME, acts: ["回流", "写入", "索引"] },
  { port: "autowriter", color: AMBER, acts: ["生成中", "出稿", "送审"] },
  { port: "指标快照", color: LIME, acts: ["采集", "回写", "对齐"] },
  { port: "essence 解析", color: LAV, acts: ["标注", "抽取", "校准"] },
  { port: "命中检测", color: CORAL, acts: ["扫描", "判级", "标爆"] },
  { port: "内部座舱", color: LIME, acts: ["调用策略卡", "下钻", "导出"] },
];
function rnd<T>(a: T[]): T { return a[Math.floor(Math.random() * a.length)]; }
function mkEv(id: number): Ev {
  const p = rnd(PORTS), act = rnd(p.acts);
  const val = act === "生成中" ? "✎" : act === "扫描" ? "◷" : "+" + (1 + Math.floor(Math.random() * 24));
  return { id, port: p.port, act, val, color: p.color };
}
// 确定性种子(SSR 与首帧一致 → 无 hydration mismatch)
const SEED: Ev[] = [
  { id: 0, port: "飞书投放表", act: "同步", val: "+12", color: LIME },
  { id: -1, port: "命中检测", act: "标爆", val: "+1", color: CORAL },
  { id: -2, port: "autowriter", act: "生成中", val: "✎", color: AMBER },
  { id: -3, port: "指标快照", act: "采集", val: "+8", color: LIME },
  { id: -4, port: "essence 解析", act: "标注", val: "+5", color: LAV },
];

export default function LiveMonitor({ daily = 84, online = 6 }: { daily?: number; online?: number }) {
  const [evs, setEvs] = useState<Ev[]>(SEED);
  const [clock, setClock] = useState("--:--:--");
  const [proc, setProc] = useState(daily);
  const [on, setOn] = useState(online);

  useEffect(() => {
    let id = 1;
    const tick = () => setClock(new Date().toLocaleTimeString("zh-CN", { hour12: false }));
    tick();
    const c = setInterval(tick, 1000);
    const f = setInterval(() => { const e = mkEv(id++); setEvs((p) => [e, ...p].slice(0, 5)); setProc((x) => x + 1 + Math.floor(Math.random() * 3)); }, 1700);
    const o = setInterval(() => setOn((x) => Math.min(7, Math.max(4, x + (Math.random() < 0.5 ? -1 : 1)))), 3400);
    return () => { clearInterval(c); clearInterval(f); clearInterval(o); };
  }, []);

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: `
        .lm-grid{display:grid;grid-template-columns:minmax(0,200px) minmax(0,1fr) minmax(0,190px);gap:18px}
        @media(max-width:720px){.lm-grid{grid-template-columns:1fr;gap:14px}.lm-grid>.lm-mid{border-left:none;border-right:none;padding-left:0;padding-right:0}}
        @keyframes lm-dot{0%,100%{opacity:.5;transform:scale(.82)}50%{opacity:1;transform:scale(1.2)}}
        @keyframes lm-wig{0%,100%{height:28%}50%{height:100%}}
        @keyframes lm-in{from{opacity:0;transform:translateY(-7px)}to{opacity:1;transform:translateY(0)}}
        .lm-dot{animation:lm-dot 1.6s ease-in-out infinite}
        .lm-in{animation:lm-in .42s cubic-bezier(.22,1,.36,1)}
        .lm-bar{animation:lm-wig 1.1s ease-in-out infinite}
      ` }} />
      <div className="lm-grid">
        {/* ports */}
        <div>
          <div style={{ fontSize: 10.5, color: MUTE, fontFamily: mono, letterSpacing: "0.12em", marginBottom: 12 }}>端口 · PORTS</div>
          {PORTS.slice(0, 5).map((p, i) => (
            <div key={p.port} style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 0", fontSize: 12 }}>
              <span className="lm-dot" style={{ width: 7, height: 7, borderRadius: 99, background: p.color, boxShadow: `0 0 8px ${p.color}`, animationDelay: `${i * 0.3}s`, flexShrink: 0 }} />
              <span style={{ flex: 1, color: "#cfd3da", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.port}</span>
              <span style={{ width: 28, height: 12, display: "inline-flex", alignItems: "flex-end", gap: 2, flexShrink: 0 }}>
                {[0, 1, 2, 3].map((b) => <span key={b} className="lm-bar" style={{ flex: 1, height: "50%", background: p.color, opacity: 0.7, borderRadius: 1, animationDelay: `${b * 0.13 + i * 0.1}s` }} />)}
              </span>
            </div>
          ))}
        </div>
        {/* feed */}
        <div className="lm-mid" style={{ borderLeft: `1px solid ${BORD}`, borderRight: `1px solid ${BORD}`, paddingLeft: 18, paddingRight: 18 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10.5, color: MUTE, fontFamily: mono, letterSpacing: "0.12em", marginBottom: 12 }}><span>实时事件流 · LIVE FEED</span><span style={{ color: LIME }} suppressHydrationWarning>{clock}</span></div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {evs.map((e, i) => (
              <div key={e.id} className={i === 0 ? "lm-in" : undefined} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12.5, fontFamily: mono, opacity: 1 - i * 0.16 }}>
                <span style={{ width: 6, height: 6, borderRadius: 99, background: e.color, flexShrink: 0 }} />
                <span style={{ color: "#cfd3da", minWidth: 92 }}>{e.port}</span>
                <span style={{ color: MUTE, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.act}</span>
                <span style={{ color: e.color, fontWeight: 700 }}>{e.val}</span>
              </div>
            ))}
          </div>
        </div>
        {/* counters */}
        <div>
          <div style={{ fontSize: 10.5, color: MUTE, fontFamily: mono, letterSpacing: "0.12em", marginBottom: 12 }}>实时 · LIVE</div>
          <div style={{ marginBottom: 14 }}><div style={{ fontSize: 24, fontWeight: 800, fontFamily: mono, color: "#fff", letterSpacing: "-0.02em" }} suppressHydrationWarning>{proc.toLocaleString()}</div><div style={{ fontSize: 11, color: MUTE, marginTop: 2 }}>今日处理事件</div></div>
          <div><div style={{ fontSize: 24, fontWeight: 800, fontFamily: mono, color: LIME, letterSpacing: "-0.02em" }} suppressHydrationWarning>{on}</div><div style={{ fontSize: 11, color: MUTE, marginTop: 2 }}>在线监测端口</div></div>
        </div>
      </div>
    </>
  );
}
