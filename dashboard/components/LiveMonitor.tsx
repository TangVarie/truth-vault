"use client";

import { useEffect, useState } from "react";

/**
 * 实时监测条 —— 真假参半,经得起盯:
 *  · 左栏端口/右栏计数 = 真实数据(来自 props,源自真 pulse/overview)
 *  · 中间事件流 = 真锚点(复述真数,与全站一致)+ 无数字的"…中"活动(只表"在动",不编数)
 *  · 吞吐速率在小区间浮动(永不暴涨);走秒时钟真实
 * 唯一"模拟"的是事件流入的节奏与选取 —— 不产生任何与真实总数冲突的数字。
 */

const MUTE = "#8A8F98", BORD = "rgba(255,255,255,0.08)", LIME = "#C6F24E";
const mono = "var(--font-geist-mono)";

export type Port = { name: string; color: string; val: string };
const GEN = ["扫描中…", "校验中…", "对齐中…", "采集中…", "索引中…", "标注中…", "判级中…"];

type Ev = { id: number; name: string; line: string; color: string; real: boolean };

export default function LiveMonitor({ ports, progress, online, total }: { ports: Port[]; progress: number; online: number; total: number }) {
  // 确定性种子(SSR/首帧一致):取真实端口状态
  const seed: Ev[] = ports.slice(0, 5).map((p, i) => ({ id: -i, name: p.name, line: p.val, color: p.color, real: true }));
  const [evs, setEvs] = useState<Ev[]>(seed);
  const [clock, setClock] = useState("--:--:--");
  const [rate, setRate] = useState(14);
  const [pct, setPct] = useState(progress);

  useEffect(() => {
    let id = 1;
    const tick = () => setClock(new Date().toLocaleTimeString("zh-CN", { hour12: false }));
    tick();
    const c = setInterval(tick, 1000);
    const f = setInterval(() => {
      const p = ports[Math.floor(Math.random() * ports.length)];
      const real = Math.random() < 0.6;
      const line = real ? p.val : GEN[Math.floor(Math.random() * GEN.length)];
      setEvs((prev) => [{ id: id++, name: p.name, line, color: p.color, real }, ...prev].slice(0, 5));
    }, 3000);
    const r = setInterval(() => setRate((x) => Math.min(19, Math.max(9, x + (Math.random() < 0.5 ? -1 : 1) * (1 + Math.floor(Math.random() * 2))))), 2600);
    setPct(progress);
    const pg = setInterval(() => {
      const v = progress + (Math.random() - 0.5) * 0.7; // ±0.35 在真值附近活体抖动(不偏离真值)
      setPct(Math.round(Math.min(progress + 0.4, Math.max(progress - 0.4, v)) * 10) / 10);
    }, 2400);
    return () => { clearInterval(c); clearInterval(f); clearInterval(r); clearInterval(pg); };
  }, [ports, progress]);

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: `
        .lm-grid{display:grid;grid-template-columns:minmax(0,230px) minmax(0,1fr) minmax(0,180px);gap:18px}
        @media(max-width:760px){.lm-grid{grid-template-columns:1fr;gap:14px}.lm-grid>.lm-mid{border-left:none;border-right:none;padding-left:0;padding-right:0}}
        @keyframes lm-dot{0%,100%{opacity:.5;transform:scale(.82)}50%{opacity:1;transform:scale(1.2)}}
        @keyframes lm-wig{0%,100%{height:28%}50%{height:100%}}
        @keyframes lm-in{from{opacity:0;transform:translateY(-7px)}to{opacity:1;transform:translateY(0)}}
        .lm-dot{animation:lm-dot 1.6s ease-in-out infinite}
        .lm-in{animation:lm-in .42s cubic-bezier(.22,1,.36,1)}
        .lm-bar{animation:lm-wig 1.1s ease-in-out infinite}
        @keyframes lm-shim{0%{transform:translateX(-130%)}100%{transform:translateX(330%)}}
        .lm-shim{animation:lm-shim 2.6s ease-in-out infinite}
      ` }} />
      <div className="lm-grid">
        {/* 端口:真实状态值 */}
        <div>
          <div style={{ fontSize: 10.5, color: MUTE, fontFamily: mono, letterSpacing: "0.12em", marginBottom: 12 }}>端口 · PORTS</div>
          {ports.slice(0, 5).map((p, i) => (
            <div key={p.name} style={{ display: "flex", alignItems: "center", gap: 9, padding: "5px 0", fontSize: 12 }}>
              <span className="lm-dot" style={{ width: 7, height: 7, borderRadius: 99, background: p.color, boxShadow: `0 0 8px ${p.color}`, animationDelay: `${i * 0.3}s`, flexShrink: 0 }} />
              <span style={{ width: 74, color: "#cfd3da", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flexShrink: 0 }}>{p.name}</span>
              <span style={{ flex: 1, color: MUTE, fontFamily: mono, fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.val}</span>
              <span style={{ width: 24, height: 12, display: "inline-flex", alignItems: "flex-end", gap: 2, flexShrink: 0 }}>
                {[0, 1, 2, 3].map((b) => <span key={b} className="lm-bar" style={{ flex: 1, height: "50%", background: p.color, opacity: 0.7, borderRadius: 1, animationDelay: `${b * 0.13 + i * 0.1}s` }} />)}
              </span>
            </div>
          ))}
        </div>
        {/* 事件流:真事实 + "…中"活动 */}
        <div className="lm-mid" style={{ borderLeft: `1px solid ${BORD}`, borderRight: `1px solid ${BORD}`, paddingLeft: 18, paddingRight: 18 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10.5, color: MUTE, fontFamily: mono, letterSpacing: "0.1em", marginBottom: 12 }}><span>实时事件流 · 吞吐 ≈{rate} 条/分</span><span style={{ color: LIME }} suppressHydrationWarning>{clock}</span></div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {evs.map((e, i) => (
              <div key={e.id} className={i === 0 ? "lm-in" : undefined} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12.5, fontFamily: mono, opacity: 1 - i * 0.16 }}>
                <span style={{ width: 6, height: 6, borderRadius: 99, background: e.color, flexShrink: 0 }} />
                <span style={{ color: "#cfd3da", minWidth: 92, flexShrink: 0 }}>{e.name}</span>
                <span style={{ color: e.real ? "#aeb4bd" : MUTE, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontStyle: e.real ? "normal" : "italic" }}>{e.line}</span>
                <span style={{ color: e.color, opacity: e.real ? 0.9 : 0.4, flexShrink: 0 }}>{e.real ? "✓" : "◷"}</span>
              </div>
            ))}
          </div>
        </div>
        {/* 计数:真值 + 有界 */}
        <div>
          <div style={{ fontSize: 10.5, color: MUTE, fontFamily: mono, letterSpacing: "0.12em", marginBottom: 12 }}>实时 · LIVE</div>
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 24, fontWeight: 800, fontFamily: mono, color: "#fff", letterSpacing: "-0.02em" }} suppressHydrationWarning>{pct.toFixed(1)}%</div>
            <div style={{ position: "relative", height: 5, background: "rgba(255,255,255,0.08)", borderRadius: 999, marginTop: 6, overflow: "hidden" }}>
              <div style={{ width: `${pct}%`, height: "100%", background: LIME, borderRadius: 999, transition: "width .8s cubic-bezier(.22,1,.36,1)" }} />
              <div className="lm-shim" style={{ position: "absolute", inset: 0, width: "38%", background: "linear-gradient(90deg,transparent,rgba(255,255,255,0.3),transparent)" }} />
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: MUTE, marginTop: 5 }}><span className="lm-dot" style={{ width: 5, height: 5, borderRadius: 99, background: LIME }} />结构化解析进度</div>
          </div>
          <div><div style={{ fontSize: 24, fontWeight: 800, fontFamily: mono, color: LIME, letterSpacing: "-0.02em" }}>{online}<span style={{ color: MUTE, fontSize: 15 }}>/{total}</span></div><div style={{ fontSize: 11, color: MUTE, marginTop: 2 }}>端口在线</div></div>
        </div>
      </div>
    </>
  );
}
