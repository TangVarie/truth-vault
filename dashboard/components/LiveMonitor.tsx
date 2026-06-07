"use client";

import { useEffect, useRef, useState } from "react";

/**
 * 实时监测条 —— 拟真模拟,不是范围随机:
 *  · 左栏端口 = 真实状态值(props,源自真 pulse/overview)
 *  · 一套吞吐模型驱动全部"活"的量:平滑双正弦吞吐(条/分,ebb/flow)→ 累积已解析条数
 *    → 结构化解析进度沿真值缓慢爬升(会话内有上限,不暴涨)→ 待解析篇数随之递减
 *  · 事件流 = 每"完成一条"按序号生成(第 N 篇 ✓ / 判级 / 回流…),内容随序号推进,不重复空转
 * 唯一"模拟"的是这套处理节奏;核心总数(曝光/爆款/经验卡)在别处都是真值。
 */

const MUTE = "#8A8F98", BORD = "rgba(255,255,255,0.08)", LIME = "#C6F24E", LAV = "#BFB9E6", CORAL = "#F2542D";
const mono = "var(--font-geist-mono)";

export type Port = { name: string; color: string; val: string };
type Ev = { id: number; name: string; line: string; color: string };

const TIERS = ["趴", "趴", "趴", "预备", "爆"];
// 确定性伪随机(按序号),让事件类型分布稳定但不重复
function frac(n: number) { return ((n * 9301 + 49297) % 233280) / 233280; }
function makeEvent(id: number, seq: number): Ev {
  const r = frac(seq);
  if (r < 0.70) return { id, name: "essence 解析", line: `第 ${seq.toLocaleString()} 篇 ✓`, color: LAV };
  if (r < 0.82) return { id, name: "命中检测", line: `判级 · ${TIERS[seq % TIERS.length]}`, color: CORAL };
  if (r < 0.90) return { id, name: "ssll 回流", line: "爆款入库 +1", color: LIME };
  if (r < 0.96) return { id, name: "指标快照", line: "采集窗口 · 同步", color: LIME };
  return { id, name: "autowriter·馆员", line: `借阅经验卡 ×${2 + (seq % 4)}`, color: LIME };
}

export default function LiveMonitor({ ports, annotated, notes, online, total }: { ports: Port[]; annotated: number; notes: number; online: number; total: number }) {
  const base = notes > 0 ? (annotated / notes) * 100 : 0;
  const ceiling = Math.min(100, base + 3.2);          // 会话内进度上限(拟真:追到近实时边再持平)
  const ceilCount = Math.round((ceiling / 100) * notes);
  const seed: Ev[] = ports.slice(0, 5).map((p, i) => ({ id: -i - 1, name: p.name, line: p.val, color: p.color }));

  const [evs, setEvs] = useState<Ev[]>(seed);
  const [clock, setClock] = useState("--:--:--");
  const [rate, setRate] = useState(15);
  const [pct, setPct] = useState(Math.round(base * 10) / 10);
  const [done, setDone] = useState(annotated);

  const acc = useRef(0);
  const last = useRef(0);
  const start = useRef(0);
  const eid = useRef(1);

  useEffect(() => {
    start.current = Date.now(); last.current = Date.now(); acc.current = 0;
    const tickClock = () => setClock(new Date().toLocaleTimeString("zh-CN", { hour12: false }));
    tickClock();
    const c = setInterval(tickClock, 1000);
    const sim = setInterval(() => {
      const now = Date.now();
      const dt = Math.min(2, (now - last.current) / 1000); last.current = now;
      const t = (now - start.current) / 1000;
      // 平滑吞吐(条/分):双正弦 ebb/flow,而非每次范围随机
      const r = 15 + 3.6 * Math.sin(t * 0.08) + 1.9 * Math.sin(t * 0.31 + 1.3);
      setRate(Math.round(r));
      const before = Math.floor(acc.current);
      acc.current += (r / 60) * dt;                    // 条/分 → 条/秒 累积
      const after = Math.floor(acc.current);
      const annot = Math.min(ceilCount, annotated + acc.current);
      setPct(Math.round((annot / notes) * 1000) / 10);
      setDone(Math.round(annot));
      if (after > before) {
        const add: Ev[] = [];
        for (let s = before + 1; s <= after; s++) add.unshift(makeEvent(eid.current++, annotated + s));
        setEvs((prev) => [...add, ...prev].slice(0, 5));
      }
    }, 850);
    return () => { clearInterval(c); clearInterval(sim); };
  }, [annotated, notes, ceilCount]);

  const remaining = Math.max(0, notes - done);

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
        {/* 事件流:每完成一条按序号生成 */}
        <div className="lm-mid" style={{ borderLeft: `1px solid ${BORD}`, borderRight: `1px solid ${BORD}`, paddingLeft: 18, paddingRight: 18 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10.5, color: MUTE, fontFamily: mono, letterSpacing: "0.1em", marginBottom: 12 }}><span suppressHydrationWarning>实时事件流 · 吞吐 ≈{rate} 条/分</span><span style={{ color: LIME }} suppressHydrationWarning>{clock}</span></div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {evs.map((e, i) => (
              <div key={e.id} className={i === 0 ? "lm-in" : undefined} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12.5, fontFamily: mono, opacity: 1 - i * 0.16 }}>
                <span style={{ width: 6, height: 6, borderRadius: 99, background: e.color, flexShrink: 0 }} />
                <span style={{ color: "#cfd3da", minWidth: 92, flexShrink: 0 }}>{e.name}</span>
                <span style={{ color: "#aeb4bd", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.line}</span>
                <span style={{ color: e.color, opacity: 0.9, flexShrink: 0 }}>✓</span>
              </div>
            ))}
          </div>
        </div>
        {/* 计数:真值锚 + 拟真推进 */}
        <div>
          <div style={{ fontSize: 10.5, color: MUTE, fontFamily: mono, letterSpacing: "0.12em", marginBottom: 12 }}>实时 · LIVE</div>
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 24, fontWeight: 800, fontFamily: mono, color: "#fff", letterSpacing: "-0.02em" }} suppressHydrationWarning>{pct.toFixed(1)}%</div>
            <div style={{ position: "relative", height: 5, background: "rgba(255,255,255,0.08)", borderRadius: 999, marginTop: 6, overflow: "hidden" }}>
              <div style={{ width: `${pct}%`, height: "100%", background: LIME, borderRadius: 999, transition: "width .8s cubic-bezier(.22,1,.36,1)" }} />
              <div className="lm-shim" style={{ position: "absolute", inset: 0, width: "38%", background: "linear-gradient(90deg,transparent,rgba(255,255,255,0.3),transparent)" }} />
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: MUTE, marginTop: 5 }}><span className="lm-dot" style={{ width: 5, height: 5, borderRadius: 99, background: LIME }} /><span suppressHydrationWarning>结构化解析 · 待 {remaining.toLocaleString()} 篇</span></div>
          </div>
          <div><div style={{ fontSize: 24, fontWeight: 800, fontFamily: mono, color: LIME, letterSpacing: "-0.02em" }}>{online}<span style={{ color: MUTE, fontSize: 15 }}>/{total}</span></div><div style={{ fontSize: 11, color: MUTE, marginTop: 2 }}>端口在线</div></div>
        </div>
      </div>
    </>
  );
}
