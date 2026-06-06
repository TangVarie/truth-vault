"use client";

import { useEffect, useMemo, useRef } from "react";
import { createNoise3D } from "simplex-noise";
import { buildBloomSpec, type BloomSpec } from "@/lib/bloom-spec";
import type { DashboardData } from "@/lib/dashboard-data";

/**
 * 「活体飞轮 · Neural Bloom」—— 把整个内容资产渲染成一团会生长、会呼吸、会复利的生命体。
 * 递归有机分枝(战线→枝 · 笔记→细丝 · 爆款→亮点 · 情绪杠杆→色相光谱)+ simplex 噪声 ember 流场。
 * theme: neon(暗底霓虹·座舱) / ink(纸底墨线·编辑落地)。确定性、SSR 安全、尊重 prefers-reduced-motion。
 */

type Theme = "neon" | "ink";
type Seg = { x1: number; y1: number; x2: number; y2: number; w: number; hue: number; rev: number };
type Node = { x: number; y: number; r: number; hue: number };
type Ember = { x: number; y: number; vx: number; vy: number; hue: number };

const TAU = Math.PI * 2;

const THEMES = {
  neon: { bg: [7, 6, 10] as [number, number, number], fade: 0.12, comp: "lighter" as GlobalCompositeOperation, light: 62, sat: 92, inkStroke: false, node: "255,255,255", ember: 0.9 },
  ink: { bg: [243, 238, 230] as [number, number, number], fade: 0.16, comp: "source-over" as GlobalCompositeOperation, light: 18, sat: 55, inkStroke: true, node: "232,118,90", ember: 0.45 },
};

function mulberry(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function buildTree(spec: BloomSpec, W: number, H: number) {
  const cx = W / 2;
  const cy = H * 0.52;
  const maxR = Math.min(W, H) * 0.46;
  const segs: Seg[] = [];
  for (const b of spec.branches) {
    const rnd = mulberry(b.seed);
    const depthMax = 5 + Math.round(b.weight * 2);
    const grow = (x: number, y: number, ang: number, len: number, w: number, depth: number) => {
      if (depth > depthMax || len < 6 || segs.length > 3600) return;
      const x2 = x + Math.cos(ang) * len;
      const y2 = y + Math.sin(ang) * len;
      segs.push({ x1: x, y1: y, x2, y2, w, hue: b.hue + (rnd() - 0.5) * 26, rev: Math.min(1, Math.hypot(x2 - cx, y2 - cy) / maxR) });
      const nChild = depth < 2 ? 3 : rnd() < 0.5 ? 2 : 3;
      const spread = 0.5 + rnd() * 0.45;
      for (let i = 0; i < nChild; i++) {
        const t = i / (nChild - 1) - 0.5;
        const na = ang + t * spread + (rnd() - 0.5) * 0.32;
        grow(x2, y2, na, len * (0.72 + rnd() * 0.12), w * 0.7, depth + 1);
      }
    };
    grow(cx, cy, b.angle, (maxR / 5) * (0.7 + b.weight * 0.6), 2.2 + b.weight * 2.6, 0);
  }
  // 亮点(爆款):在外缘 tip 上挑 totalBright 个
  const r2 = mulberry(spec.seed ^ 0x9e3779b9);
  const tips = segs.filter((s) => s.rev > 0.5);
  const nodes: Node[] = [];
  const nb = Math.min(64, Math.max(spec.totalBright, 6));
  for (let i = 0; i < nb && tips.length; i++) {
    const s = tips[Math.floor(r2() * tips.length)];
    nodes.push({ x: s.x2, y: s.y2, r: 2.2 + r2() * 2.8, hue: s.hue });
  }
  return { segs, nodes, cx, cy, maxR };
}

export default function NeuralBloom({
  data,
  theme = "neon",
  className = "",
}: {
  data: DashboardData;
  theme?: Theme;
  className?: string;
}) {
  const spec = useMemo<BloomSpec>(() => buildBloomSpec(data), [data]);
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const wrap = wrapRef.current;
    const canvas = canvasRef.current;
    if (!wrap || !canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const T = THEMES[theme];
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const noise = createNoise3D(mulberry(spec.seed ^ 0x1234));

    let W = 0;
    let H = 0;
    let dpr = 1;
    let tree = buildTree(spec, 1, 1);
    let off: HTMLCanvasElement | null = null;
    let embers: Ember[] = [];
    let raf = 0;
    let start = 0;

    const renderOffscreen = () => {
      off = document.createElement("canvas");
      off.width = Math.max(1, Math.floor(W * dpr));
      off.height = Math.max(1, Math.floor(H * dpr));
      const o = off.getContext("2d");
      if (!o) return;
      o.scale(dpr, dpr);
      o.globalCompositeOperation = T.comp;
      o.lineCap = "round";
      for (const s of tree.segs) {
        const a = 0.5 - s.rev * 0.28;
        o.strokeStyle = T.inkStroke ? `rgba(20,17,15,${(a * 0.85).toFixed(3)})` : `hsla(${s.hue}, ${T.sat}%, ${T.light}%, ${a.toFixed(3)})`;
        o.lineWidth = s.w;
        o.beginPath();
        o.moveTo(s.x1, s.y1);
        o.lineTo(s.x2, s.y2);
        o.stroke();
      }
      for (const n of tree.nodes) {
        const g = o.createRadialGradient(n.x, n.y, 0, n.x, n.y, n.r * 5);
        if (T.inkStroke) {
          g.addColorStop(0, "rgba(232,118,90,0.95)");
          g.addColorStop(0.4, "rgba(232,118,90,0.35)");
          g.addColorStop(1, "rgba(232,118,90,0)");
        } else {
          g.addColorStop(0, "rgba(255,255,255,0.95)");
          g.addColorStop(0.3, `hsla(${n.hue},95%,65%,0.6)`);
          g.addColorStop(1, `hsla(${n.hue},95%,55%,0)`);
        }
        o.fillStyle = g;
        o.beginPath();
        o.arc(n.x, n.y, n.r * 5, 0, TAU);
        o.fill();
      }
    };

    const setup = () => {
      const rect = wrap.getBoundingClientRect();
      W = Math.max(1, rect.width);
      H = Math.max(1, rect.height);
      dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = Math.floor(W * dpr);
      canvas.height = Math.floor(H * dpr);
      canvas.style.width = `${W}px`;
      canvas.style.height = `${H}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      tree = buildTree(spec, W, H);
      renderOffscreen();
      const count = Math.min(360, Math.max(80, Math.round((W * H) / 5200)));
      const er = mulberry(spec.seed ^ 0x55aa);
      embers = Array.from({ length: count }, () => ({
        x: er() * W,
        y: er() * H,
        vx: 0,
        vy: 0,
        hue: spec.hues[Math.floor(er() * spec.hues.length)],
      }));
      ctx.globalCompositeOperation = "source-over";
      ctx.fillStyle = `rgb(${T.bg[0]},${T.bg[1]},${T.bg[2]})`;
      ctx.fillRect(0, 0, W, H);
    };

    const drawTree = (grow: number, breath: number) => {
      if (!off) return;
      ctx.save();
      ctx.beginPath();
      ctx.arc(tree.cx, tree.cy, grow * tree.maxR * 1.3, 0, TAU);
      ctx.clip();
      ctx.translate(tree.cx, tree.cy);
      ctx.scale(breath, breath);
      ctx.translate(-tree.cx, -tree.cy);
      ctx.drawImage(off, 0, 0, W, H);
      ctx.restore();
    };

    const drawEmbers = (t: number) => {
      ctx.globalCompositeOperation = T.comp;
      for (const e of embers) {
        const ang = noise(e.x * 0.0017, e.y * 0.0017, t * 0.00007) * TAU * 2;
        e.vx = e.vx * 0.95 + Math.cos(ang) * 0.07;
        e.vy = e.vy * 0.95 + Math.sin(ang) * 0.07;
        e.x += e.vx;
        e.y += e.vy;
        if (e.x < 0) e.x += W;
        else if (e.x > W) e.x -= W;
        if (e.y < 0) e.y += H;
        else if (e.y > H) e.y -= H;
        ctx.fillStyle = T.inkStroke ? `rgba(232,118,90,${0.5 * T.ember})` : `hsla(${e.hue},95%,68%,${T.ember})`;
        ctx.beginPath();
        ctx.arc(e.x, e.y, T.inkStroke ? 0.9 : 1.2, 0, TAU);
        ctx.fill();
      }
      ctx.globalCompositeOperation = "source-over";
    };

    const frame = (now: number) => {
      if (!start) start = now;
      const t = now - start;
      ctx.globalCompositeOperation = "source-over";
      ctx.fillStyle = `rgba(${T.bg[0]},${T.bg[1]},${T.bg[2]},${T.fade})`;
      ctx.fillRect(0, 0, W, H);
      const grow = easeOut(Math.min(1, t / 2600));
      const breath = 1 + Math.sin(t / 2300) * 0.012;
      drawTree(grow, breath);
      drawEmbers(t);
      raf = requestAnimationFrame(frame);
    };

    setup();
    if (reduce) {
      drawTree(1, 1);
      drawEmbers(0);
    } else {
      raf = requestAnimationFrame(frame);
    }

    let resizeTimer: ReturnType<typeof setTimeout>;
    const onResize = () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        cancelAnimationFrame(raf);
        start = 0;
        setup();
        if (reduce) {
          drawTree(1, 1);
          drawEmbers(0);
        } else {
          raf = requestAnimationFrame(frame);
        }
      }, 220);
    };
    const ro = new ResizeObserver(onResize);
    ro.observe(wrap);

    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(resizeTimer);
      ro.disconnect();
    };
  }, [spec, theme]);

  return (
    <div ref={wrapRef} className={`relative ${className}`} aria-hidden>
      <canvas ref={canvasRef} className="block h-full w-full" />
    </div>
  );
}

function easeOut(p: number) {
  return 1 - Math.pow(1 - p, 3);
}
