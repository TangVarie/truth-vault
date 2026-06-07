"use client";

import { useEffect, useState } from "react";

/**
 * 系统解构(视觉解构,看板版 —— 偏"真实运行"而非"介绍怎么运行"):
 *  静态结构是蓝图式解构(① 爆款拆件 ② 大书库 ③ AI 管理员大脑 ④ 全国去中心化真人点阵 ⑤ 复利回流),
 *  叠加一套轻量拟真:解构层的结构件实时换批、库存实时入库、管理员实时判级(序号+命中率推进)、
 *  网络点阵活动扫掠、本会话发稿递增 —— 让它"在跑",不是一张说明图。
 */

const LIME = "#C6F24E", LAV = "#BFB9E6", CORAL = "#F2542D", MUTE = "#8A8F98";
const sans = "var(--font-geist-sans)", mono = "var(--font-geist-mono)";

// 受控词表(真实取值)—— 解构层实时换批用
const VEMO = ["焦虑撬动", "认同感建立", "好奇驱动", "虚荣撬动", "共鸣释放", "恐惧撬动"];
const VARCH = ["同辈比较", "自我形象维护", "时间流逝感", "身份认同", "健康焦虑", "经济焦虑"];
const VAUD = ["中年女性", "年轻女性", "宝妈", "学生党", "银发女性", "通用"];
const VFMT = ["情感叙事", "场景植入", "直给推荐", "横评对比", "教程攻略", "认知重构"];
const EK = ["情绪杠杆", "人性原型", "目标受众", "内容形态"];

function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => { a = (a + 0x6d2b79f5) >>> 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
type LatNode = { x: number; y: number; r: number; kind: 0 | 1 | 2 };
function libraryBars() {
  const r = mulberry32(7);
  return Array.from({ length: 20 }, (_, i) => ({ h: 30 + Math.round(r() * 108), lime: i % 6 === 3 }));
}
function latticeNodes(): LatNode[] {
  const r = mulberry32(99);
  const X0 = 812, X1 = 1150, Y0 = 158, Y1 = 386, step = 25;
  const cx = (X0 + X1) / 2, cy = (Y0 + Y1) / 2, maxd = Math.hypot(X1 - cx, Y1 - cy);
  const out: LatNode[] = [];
  for (let y = Y0; y <= Y1; y += step) {
    for (let x = X0; x <= X1; x += step) {
      const jx = x + (r() - 0.5) * 9, jy = y + (r() - 0.5) * 9;
      const dens = 1 - Math.hypot(jx - cx, jy - cy) / maxd;
      if (r() > 0.24 + dens * 0.58) continue;
      const k = r();
      const kind: 0 | 1 | 2 = jx > X1 - 54 && k > 0.6 ? 2 : k > 0.92 ? 1 : 0;
      out.push({ x: jx, y: jy, r: kind === 2 ? 3 : kind === 1 ? 2.4 : 1.5, kind });
    }
  }
  return out;
}
const LIB = libraryBars();
const LAT = latticeNodes();

export default function SystemDeconstruct({ cards, hitRate, notes }: { cards: number; hitRate: number; notes: number }) {
  const [chips, setChips] = useState([VEMO[0], VARCH[0], VAUD[0], VFMT[0]]);
  const [stock, setStock] = useState(cards);
  const [seq, setSeq] = useState(notes);
  const [hit, setHit] = useState(Math.round(hitRate * 10) / 10);
  const [posts, setPosts] = useState(0);
  const [sweep, setSweep] = useState(0);

  useEffect(() => {
    let t = 0, ck = 0;
    const id = setInterval(() => {
      t += 1;
      setSweep(t);
      setSeq((s) => s + 1 + (t % 3 === 0 ? 1 : 0));
      setHit(Math.round((hitRate + 1.3 * Math.sin(t * 0.21)) * 10) / 10);
      if (t % 3 === 0) setPosts((p) => p + 1);
      if (t % 13 === 6) setStock((c) => c + 1);
      if (t % 5 === 0) { ck += 1; setChips([VEMO[ck % VEMO.length], VARCH[(ck * 2 + 1) % VARCH.length], VAUD[(ck * 3) % VAUD.length], VFMT[(ck * 5 + 2) % VFMT.length]]); }
    }, 1100);
    return () => clearInterval(id);
  }, [hitRate]);

  const gain = stock - cards;

  return (
    <section className="s12 bb-tile" style={{ padding: "22px 26px 16px" }}>
      <style dangerouslySetInnerHTML={{ __html: `@keyframes sd-pulse{0%,100%{opacity:.5;transform:scale(.85)}50%{opacity:1;transform:scale(1.2)}}` }} />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 7, border: "1.5px solid rgba(255,255,255,0.22)", color: "#fff", borderRadius: 999, padding: "6px 14px", fontSize: 12.5, fontWeight: 600 }}>核心机制 · 解构</span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: 11.5, color: LIME, fontFamily: mono }}><span style={{ width: 7, height: 7, borderRadius: 99, background: LIME, boxShadow: `0 0 10px ${LIME}`, animation: "sd-pulse 1.6s ease-in-out infinite" }} />双引擎 · 一个 AI 管理员 · 实时运行</span>
      </div>
      <svg viewBox="0 0 1200 500" width="100%" style={{ display: "block", marginTop: 6 }} role="img" aria-label="系统解构实时运行:爆款解构成经验卡进入大书库, AI 管理员实时判级修正, 调度去中心化全国真人网络, 新爆款复利回流">
        <defs>
          <radialGradient id="sx-admin"><stop offset="0%" stopColor={LAV} stopOpacity="0.85" /><stop offset="100%" stopColor={LAV} stopOpacity="0" /></radialGradient>
          <filter id="sx-glow" x="-300%" y="-300%" width="700%" height="700%"><feGaussianBlur stdDeviation="2.2" /></filter>
        </defs>

        {/* 蓝图标题块 */}
        <text x="40" y="32" style={{ fontSize: 13, fontWeight: 800, fill: "#fff", fontFamily: sans, letterSpacing: "0.04em" }}>系统解构</text>
        <text x="40" y="47" style={{ fontSize: 9, fill: MUTE, fontFamily: mono, letterSpacing: "0.16em" }}>TWO ENGINES · ONE BRAIN · LIVE</text>
        <line x1="40" y1="56" x2="1160" y2="56" stroke="rgba(255,255,255,0.08)" />

        {/* ① 解构:爆款 → 结构件(实时换批) */}
        <circle cx="74" cy="92" r="9" fill="none" stroke={CORAL} strokeWidth="1.2" /><text x="74" y="95.5" textAnchor="middle" style={{ fontSize: 10, fontWeight: 700, fill: CORAL, fontFamily: mono }}>1</text>
        <text x="92" y="96" style={{ fontSize: 11, fontWeight: 700, fill: "#fff", fontFamily: sans }}>解构</text>
        <text x="125" y="96" style={{ fontSize: 9, fill: LIME, fontFamily: mono }} suppressHydrationWarning>● 解构中 · 第 {(seq + 1).toLocaleString()} 篇</text>
        <rect x="70" y="116" width="152" height="40" rx="9" fill="rgba(255,255,255,0.05)" stroke="rgba(255,255,255,0.18)" />
        <text x="82" y="133" style={{ fontSize: 9.5, fill: "#cfd3da", fontFamily: mono }}>一条验证级爆款</text>
        <rect x="82" y="140" width="116" height="2" rx="1" fill="rgba(255,255,255,0.16)" /><rect x="82" y="145" width="78" height="2" rx="1" fill="rgba(255,255,255,0.10)" />
        {EK.map((k, i) => { const y = 190 + i * 48; return (
          <g key={`es${i}`}>
            <line x1="146" y1="156" x2="80" y2={y + 16} stroke={MUTE} strokeWidth="0.7" opacity="0.28" />
            <rect x="78" y={y} width="150" height="32" rx="7" fill="rgba(255,255,255,0.04)" stroke="rgba(255,255,255,0.10)" />
            <text x="90" y={y + 20} style={{ fontSize: 9.5, fill: MUTE, fontFamily: mono }}>{k}</text>
            <rect x="160" y={y + 7} width="60" height="18" rx="9" fill="rgba(198,242,78,0.12)" />
            <text x="190" y={y + 19.5} textAnchor="middle" style={{ fontSize: 9.5, fill: LIME, fontFamily: sans }} suppressHydrationWarning>{chips[i]}</text>
          </g>
        ); })}

        {/* ② 大书库(实时入库) */}
        <circle cx="300" cy="92" r="9" fill="none" stroke={LIME} strokeWidth="1.2" /><text x="300" y="95.5" textAnchor="middle" style={{ fontSize: 10, fontWeight: 700, fill: LIME, fontFamily: mono }}>2</text>
        <text x="318" y="96" style={{ fontSize: 11, fontWeight: 700, fill: "#fff", fontFamily: sans }} suppressHydrationWarning>大书库 · 经验卡 {stock.toLocaleString()}</text>
        {[210, 258, 306].map((y, k) => <line key={`f${k}`} x1="228" y1={y} x2="300" y2="350" stroke={MUTE} strokeWidth="0.7" opacity="0.22" />)}
        {LIB.map((b, i) => { const x = 300 + i * 8.4; return <rect key={`lb${i}`} x={x} y={360 - b.h} width="7" height={b.h} rx="1.5" fill={b.lime ? LIME : "rgba(255,255,255,0.14)"} opacity={b.lime ? 0.9 : 0.7} />; })}
        <line x1="296" y1="361" x2="476" y2="361" stroke="rgba(255,255,255,0.14)" />
        {gain > 0 ? <text x="386" y="378" textAnchor="middle" style={{ fontSize: 9, fill: LIME, fontFamily: mono }} suppressHydrationWarning>本会话入库 +{gain}</text> : null}

        {/* 借阅:库 → 管理员 */}
        <path id="sx-borrow" d="M476 250 L540 250" fill="none" stroke={LIME} strokeWidth="1" opacity="0.5" />
        <circle r="2" fill={LIME}><animateMotion dur="2.8s" repeatCount="indefinite"><mpath href="#sx-borrow" /></animateMotion></circle>
        <text x="508" y="242" textAnchor="middle" style={{ fontSize: 9, fill: LIME, fontFamily: mono }}>借阅</text>

        {/* ③ AI 管理员(大脑,实时判级) */}
        <circle cx="600" cy="166" r="9" fill="none" stroke={LAV} strokeWidth="1.2" /><text x="600" y="169.5" textAnchor="middle" style={{ fontSize: 10, fontWeight: 700, fill: LAV, fontFamily: mono }}>3</text>
        <circle cx="600" cy="250" r="62" fill="none" stroke={LAV} strokeWidth="1" opacity="0.16" />
        <circle cx="600" cy="250" r="46" fill="none" stroke={LAV} strokeWidth="1" opacity="0.3" />
        <circle cx="600" cy="250" r="30" fill="url(#sx-admin)" opacity="0.5" />
        <circle cx="600" cy="250" r="30" fill="none" stroke={LAV} strokeWidth="1.3" opacity="0.7" />
        <circle cx="600" cy="250" r="30" fill="none" stroke={LAV} strokeWidth="1"><animate attributeName="r" values="30;64" dur="3.6s" repeatCount="indefinite" /><animate attributeName="opacity" values="0.55;0" dur="3.6s" repeatCount="indefinite" /></circle>
        <rect x="590" y="240" width="20" height="20" rx="3" transform="rotate(45 600 250)" fill="#141416" stroke="#fff" strokeWidth="1.3" />
        <circle cx="600" cy="250" r="3.2" fill="#fff" />
        <text x="600" y="334" textAnchor="middle" style={{ fontSize: 12.5, fontWeight: 800, fill: "#fff", fontFamily: sans }}>AI 管理员</text>
        <text x="600" y="350" textAnchor="middle" style={{ fontSize: 9.5, fill: LAV, fontFamily: mono }} suppressHydrationWarning>判级中 · 第 {seq.toLocaleString()} 篇 · 命中 {hit.toFixed(1)}%</text>

        {/* 调度 ⇄ 判级:管理员 ↔ 网络 */}
        <path id="sx-disp" d="M662 244 L808 244" fill="none" stroke={LAV} strokeWidth="1" opacity="0.45" />
        <circle r="2" fill={LAV}><animateMotion dur="3s" repeatCount="indefinite"><mpath href="#sx-disp" /></animateMotion></circle>
        <text x="735" y="236" textAnchor="middle" style={{ fontSize: 9, fill: LAV, fontFamily: mono }}>调度 →</text>
        <path id="sx-chk" d="M808 258 L662 258" fill="none" stroke="rgba(255,255,255,0.16)" strokeWidth="1" strokeDasharray="3 4" />
        <circle r="2" fill={CORAL}><animateMotion dur="3.4s" repeatCount="indefinite"><mpath href="#sx-chk" /></animateMotion></circle>
        <text x="735" y="272" textAnchor="middle" style={{ fontSize: 9, fill: MUTE, fontFamily: mono }}>← 检查效果 · 判级</text>

        {/* ④ 去中心化 · 全国真人网络(活动扫掠 + 本会话发稿) */}
        <circle cx="820" cy="92" r="9" fill="none" stroke={CORAL} strokeWidth="1.2" /><text x="820" y="95.5" textAnchor="middle" style={{ fontSize: 10, fontWeight: 700, fill: CORAL, fontFamily: mono }}>4</text>
        <text x="838" y="92" style={{ fontSize: 11, fontWeight: 700, fill: "#fff", fontFamily: sans }}>去中心化 · 全国真人网络</text>
        <text x="838" y="108" style={{ fontSize: 9, fill: LIME, fontFamily: mono }} suppressHydrationWarning>● 实时修稿发稿 · 本会话 +{posts}</text>
        {LAT.filter((n) => n.x < 884).slice(0, 7).map((n, i) => <line key={`df${i}`} x1="808" y1="250" x2={n.x} y2={n.y} stroke={LAV} strokeWidth="0.6" opacity="0.16" />)}
        {LAT.map((n, i) => {
          const lit = (i * 3 + sweep) % 19 < 2;
          const fill = n.kind === 2 ? CORAL : lit || n.kind === 1 ? LIME : "#565b66";
          return <circle key={`ln${i}`} cx={n.x} cy={n.y} r={lit ? n.r + 0.5 : n.r} fill={fill} opacity={n.kind === 0 && !lit ? 0.5 : 1} filter={n.kind || lit ? "url(#sx-glow)" : undefined} style={{ transition: "fill .5s, r .5s" }} />;
        })}
        {LAT.filter((n) => n.kind === 2).map((n, i) => <circle key={`lc${i}`} cx={n.x} cy={n.y} r={n.r * 0.58} fill={CORAL} />)}
        <text x="1150" y="148" textAnchor="end" style={{ fontSize: 9.5, fill: CORAL, fontFamily: mono }}>新爆款结晶 →</text>

        {/* ⑤ 复利回流 */}
        <path id="sx-loop" d="M 1128 388 C 1090 466, 560 478, 360 360" fill="none" stroke="rgba(255,255,255,0.14)" strokeWidth="1.2" strokeDasharray="3 5" />
        <circle r="3" fill={CORAL}><animateMotion dur="6s" repeatCount="indefinite"><mpath href="#sx-loop" /></animateMotion></circle>
        <circle cx="576" cy="470" r="9" fill="none" stroke={LIME} strokeWidth="1.2" /><text x="576" y="473.5" textAnchor="middle" style={{ fontSize: 10, fontWeight: 700, fill: LIME, fontFamily: mono }}>5</text>
        <text x="598" y="474" style={{ fontSize: 10, fontWeight: 600, fill: "#cfd3da", fontFamily: mono }}>新爆款 · 复利回流 · 越用越准 ↺</text>
      </svg>
    </section>
  );
}
