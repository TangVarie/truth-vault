"use client";

import { useEffect, useRef, useState } from "react";

/**
 * 实时监测条 —— wall-clock 拟真,不是会话内回放、也不是范围随机:
 *  · 一个 live `done`(= 真值 annotated + 在途量)同时驱动【左栏 essence 端口 / 中栏事件流头部 /
 *    右栏进度%·待篇数】→ 三栏永远口径一致(修"左侧和中间对不上")。
 *  · 在途量 = inflight(Date.now()):纯 wall-clock 函数(双正弦, 1~2.5h 周期), 封顶 cap(真值上方
 *    窄带)→ 不同时刻打开看到不同进度(修"每次打开都一样"), 又始终贴近真值不发散。
 *  · done 单调棘轮(进度条不回退);事件流按吞吐节拍出:done 前进时出 essence「第 N 篇✓」,
 *    追平在途后出非计数活动事件(判级/回流/快照/馆员)→ 视觉常活但 essence 序号不暴冲。
 * 唯一"模拟"的是处理节奏与在途量;核心总数(曝光/爆款/经验卡)在别处都是真值。
 */

const MUTE = "#8A8F98", BORD = "rgba(255,255,255,0.08)", LIME = "#C6F24E", LAV = "#BFB9E6", CORAL = "#F2542D";
const mono = "var(--font-geist-mono)";

export type Port = { name: string; color: string; val: string };
type Ev = { id: number; name: string; line: string; color: string };

const TIERS = ["趴", "趴", "趴", "预备", "爆"];
// 确定性伪随机(按序号),让事件类型分布稳定但不重复
function frac(n: number) { const x = ((n * 9301 + 49297) % 233280) / 233280; return x < 0 ? x + 1 : x; }
// 锚定到真实 essence 序号的混合事件(seed/前进时用):多数 essence「第 N 篇」, 夹杂其它流水
function makeEvent(id: number, seq: number): Ev {
  const r = frac(seq);
  if (r < 0.70) return { id, name: "essence 解析", line: `第 ${seq.toLocaleString()} 篇 ✓`, color: LAV };
  if (r < 0.82) return { id, name: "命中检测", line: `判级 · ${TIERS[seq % TIERS.length]}`, color: CORAL };
  if (r < 0.90) return { id, name: "ssll 回流", line: "爆款入库 +1", color: LIME };
  if (r < 0.96) return { id, name: "指标快照", line: "采集窗口 · 同步", color: LIME };
  return { id, name: "autowriter·馆员", line: `借阅经验卡 ×${2 + (seq % 4)}`, color: LIME };
}
// 非计数活动事件(已追平在途量时用):保持事件流"活"但不推进 essence 序号
function activityEvent(id: number, seed: number): Ev {
  const r = frac(seed);
  if (r < 0.34) return { id, name: "命中检测", line: `判级 · ${TIERS[seed % TIERS.length]}`, color: CORAL };
  if (r < 0.62) return { id, name: "ssll 回流", line: "爆款入库 +1", color: LIME };
  if (r < 0.83) return { id, name: "指标快照", line: "采集窗口 · 同步", color: LIME };
  return { id, name: "autowriter·馆员", line: `借阅经验卡 ×${2 + (seed % 4)}`, color: LIME };
}
// 按头部序号生成 5 条可见事件:真实完成项(seq≥1)→ essence「第 N 篇」; 不足的槽位 → 活动事件兜底。
// 绝不把缺失槽位夹成「第 1 篇」凭空捏造完成项 —— 空表 / 冷启动 / Supabase 不可用时保持诚实(PR#93 review)。
function buildVisible(headSeq: number): Ev[] {
  return Array.from({ length: 5 }, (_, k) => {
    const seq = headSeq - k;
    return seq >= 1 ? makeEvent(-k - 1, seq) : activityEvent(-k - 1, 31 * (k + 1) + 7);
  });
}

export default function LiveMonitor({ ports, annotated, notes, online, total, live = true }: { ports: Port[]; annotated: number; notes: number; online: number; total: number; live?: boolean }) {
  const base = notes > 0 ? (annotated / notes) * 100 : 0;
  const remaining0 = Math.max(0, notes - annotated);
  // 在途带宽 cap —— 内外严格分离的关键开关:
  //  · live=false(对内座舱)→ 0:不模拟在途量, done 恒 = 真实 annotated, 全部真实快照、不动。
  //  · live=true (对外看板)→ 真值上方 ≤48 篇且 ≤annotated 的窄带(放大"变动幅度":不同时刻打开差异更明显),
  //    annotated=0 仍为 0(空表/冷启动绝不凭空造完成项)。
  const cap = live ? Math.min(remaining0, 48, annotated) : 0;

  // SSR 安全初值(纯 props 真值锚, 与服务端一致 → 无 hydration mismatch);wall-clock 推进只在 effect 里。
  const seed: Ev[] = buildVisible(annotated);

  const [evs, setEvs] = useState<Ev[]>(seed);
  const [clock, setClock] = useState("--:--:--");
  const [rate, setRate] = useState(16);
  const [pct, setPct] = useState(Math.round(base * 10) / 10);
  const [done, setDone] = useState(annotated);

  const head = useRef(annotated);
  const eid = useRef(1);

  useEffect(() => {
    const tickClock = () => setClock(new Date().toLocaleTimeString("zh-CN", { hour12: false }));
    tickClock();
    const c = setInterval(tickClock, 1000);

    // ── 对内座舱(live=false):全部真实快照 —— done = 真实 annotated, 进度/待篇/事件流全用真值,
    //    不跑任何模拟、不推进、不造在途量。时钟照走(真实当前时间)。 ──
    if (!live) {
      head.current = annotated;
      setEvs(buildVisible(annotated));
      setDone(annotated);
      setPct(notes > 0 ? Math.round((annotated / notes) * 1000) / 10 : 0);
      return () => clearInterval(c);
    }

    // ── 对外看板(live=true):wall-clock 拟真。在途量 = 纯 wall-clock 函数 → [0, cap],
    //    双正弦(~69min / ~152min 周期)全天平滑起伏 → 不同时刻打开看到不同进度。 ──
    const inflightAt = (sec: number) => {
      const u = 0.5 + 0.34 * Math.sin(sec * 0.00152) + 0.16 * Math.sin(sec * 0.00069 + 2.1);
      return cap * Math.min(1, Math.max(0, u));
    };

    const t0 = Date.now() / 1000;
    head.current = Math.min(notes, annotated + Math.round(inflightAt(t0)));
    setEvs(buildVisible(head.current));
    setDone(head.current);
    setPct(notes > 0 ? Math.round((head.current / notes) * 1000) / 10 : 0);

    let acc = 0;
    let lastT = Date.now();
    const sim = setInterval(() => {
      const now = Date.now(), nowSec = now / 1000;
      const dt = Math.min(2, (now - lastT) / 1000); lastT = now;
      // 吞吐(条/分):双正弦 ebb/flow + 更大摆幅(放大"变动幅度"),相位挂 wall-clock → 每次打开节奏不同
      const r = 18 + 5.5 * Math.sin(nowSec * 0.08) + 2.6 * Math.sin(nowSec * 0.031 + 1.3);
      setRate(Math.round(r));
      acc += (r / 60) * dt;                                   // 条/分 → 条/秒 累积(总流水节拍)
      const target = Math.min(notes, annotated + Math.round(inflightAt(nowSec)));  // wall-clock 在途目标
      let n = 0;
      while (acc >= 1 && n < 4) {                             // 每 tick 至多吐几条,防积压暴冲
        acc -= 1; n++;
        if (head.current < target) {                         // done 棘轮前进 → essence 完成事件
          head.current += 1;
          const h = head.current;
          setEvs((prev) => [{ id: eid.current++, name: "essence 解析", line: `第 ${h.toLocaleString()} 篇 ✓`, color: LAV }, ...prev].slice(0, 5));
        } else {                                             // 已追平在途量 → 非计数活动事件(流仍在动)
          setEvs((prev) => [activityEvent(eid.current++, Math.floor(nowSec) + n), ...prev].slice(0, 5));
        }
      }
      if (n > 0) { setDone(head.current); setPct(notes > 0 ? Math.round((head.current / notes) * 1000) / 10 : 0); }
    }, 1200);

    return () => { clearInterval(c); clearInterval(sim); };
  }, [annotated, notes, cap, live]);

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
        {/* 端口:真实状态值(essence 端口跟随 live done, 与中/右栏同源一致) */}
        <div>
          <div style={{ fontSize: 10.5, color: MUTE, fontFamily: mono, letterSpacing: "0.12em", marginBottom: 12 }}>端口 · PORTS</div>
          {ports.slice(0, 5).map((p, i) => {
            const val = p.name === "essence 解析" ? `已标注 ${done.toLocaleString()}/${notes.toLocaleString()}` : p.val;
            return (
              <div key={p.name} style={{ display: "flex", alignItems: "center", gap: 9, padding: "5px 0", fontSize: 12 }}>
                <span className="lm-dot" style={{ width: 7, height: 7, borderRadius: 99, background: p.color, boxShadow: `0 0 8px ${p.color}`, animationDelay: `${i * 0.3}s`, flexShrink: 0 }} />
                <span style={{ width: 74, color: "#cfd3da", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flexShrink: 0 }}>{p.name}</span>
                <span suppressHydrationWarning style={{ flex: 1, color: MUTE, fontFamily: mono, fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{val}</span>
                <span style={{ width: 24, height: 12, display: "inline-flex", alignItems: "flex-end", gap: 2, flexShrink: 0 }}>
                  {[0, 1, 2, 3].map((b) => <span key={b} className="lm-bar" style={{ flex: 1, height: "50%", background: p.color, opacity: 0.7, borderRadius: 1, animationDelay: `${b * 0.13 + i * 0.1}s` }} />)}
                </span>
              </div>
            );
          })}
        </div>
        {/* 事件流:每完成一条按序号生成 */}
        <div className="lm-mid" style={{ borderLeft: `1px solid ${BORD}`, borderRight: `1px solid ${BORD}`, paddingLeft: 18, paddingRight: 18 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10.5, color: MUTE, fontFamily: mono, letterSpacing: "0.1em", marginBottom: 12 }}><span suppressHydrationWarning>{live ? `实时事件流 · 吞吐 ≈${rate} 条/分` : "近期标注 · 真实快照"}</span><span style={{ color: LIME }} suppressHydrationWarning>{clock}</span></div>
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
        {/* 计数:真值锚 + wall-clock 在途推进(与左/中同源) */}
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
