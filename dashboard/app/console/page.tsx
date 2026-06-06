import Link from "next/link";
import { getSupabase } from "@/lib/supabase";
import { NODES } from "@/config/flywheel";
import Flywheel from "@/components/Flywheel";
import LivePresence from "@/components/LivePresence";

// 公开看板始终在服务端拉实时大数(force-dynamic):保证数字永远是真值,
// 不会在部署后短暂显示构建时占位 0。视图查询很轻(单次聚合)。docs/24 §2。
export const dynamic = "force-dynamic";

type Overview = {
  projects: number;
  notes: number;
  baokuan: number;
  cards: number;
  librarian: number;
  essence: number;
  ok: boolean;
};

const EMPTY: Overview = {
  projects: 0, notes: 0, baokuan: 0, cards: 0, librarian: 0, essence: 0, ok: false,
};

async function getOverview(): Promise<Overview> {
  const sb = getSupabase();
  if (!sb) return EMPTY;
  try {
    // 只读 public 的安全聚合视图(docs/24 §3):一行大数,不直接碰 truth_vault 原始表。
    const { data, error } = await sb.from("v_dash_overview").select("*").single();
    if (error || !data) return EMPTY;
    return {
      projects: data.projects ?? 0,
      notes: data.notes ?? 0,
      baokuan: data.baokuan_real ?? 0,
      cards: data.cards ?? 0,
      librarian: data.librarian ?? 0,
      essence: data.essence_done ?? 0,
      ok: true,
    };
  } catch {
    return EMPTY;
  }
}

function fmt(n: number) {
  return n.toLocaleString("en-US");
}

function Metric({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <div className="group relative overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-b from-white/[0.07] to-white/[0.015] p-5 transition hover:-translate-y-0.5 hover:border-flywheel-accent/40">
      <div className="pointer-events-none absolute -right-6 -top-8 h-20 w-20 rounded-full bg-flywheel-accent/10 blur-2xl transition group-hover:bg-flywheel-accent/20" />
      <div className="text-xs uppercase tracking-wider text-slate-400">{label}</div>
      <div className="mt-2 text-4xl font-bold tabular-nums text-flywheel-accent drop-shadow-[0_0_12px_rgba(94,234,212,0.25)]">
        {value}
      </div>
      {hint ? <div className="mt-1 text-xs text-slate-500">{hint}</div> : null}
    </div>
  );
}

function NodePill({ label, alive, planned }: { label: string; alive: boolean; planned?: boolean }) {
  return (
    <div className="glass flex items-center gap-2 rounded-full px-4 py-2 text-sm text-slate-200">
      <span
        className={`inline-block h-2.5 w-2.5 rounded-full ${
          alive
            ? "bg-flywheel-accent shadow-[0_0_8px_2px_rgba(94,234,212,0.55)] animate-pulse"
            : "bg-slate-600"
        }`}
      />
      {label}
      {planned ? <span className="text-xs text-slate-500">规划中</span> : null}
    </div>
  );
}

export default async function ConsolePage() {
  const o = await getOverview();
  return (
    <main className="mx-auto max-w-6xl px-6 py-12">
      <header className="mb-8">
        <Link href="/" className="text-xs text-slate-500 transition hover:text-slate-300">
          ← 返回开篇
        </Link>
        <h1 className="mt-2 text-3xl font-bold text-white">飞轮总看板 · 公众版</h1>
        <p className="mt-1 text-slate-400">
          帆谷飞轮生态 · Truth Vault / autowriter / sanshengliubu 实时态势
        </p>
        {!o.ok && (
          <p className="mt-3 inline-block rounded-lg bg-flywheel-warn/10 px-4 py-2 text-sm text-flywheel-warn">
            ⚠️ 未连到 Supabase(部署需配 <code>SUPABASE_URL</code> + <code>SUPABASE_ANON_KEY</code>)。当前显示占位 0。
          </p>
        )}
      </header>

      {/* 飞轮活体图 + 标语 */}
      <section className="glass grid-bg relative mb-10 grid items-center gap-6 overflow-hidden rounded-3xl p-6 sm:p-8 lg:grid-cols-[1.05fr_1fr]">
        <div className="relative">
          <Flywheel center={o.ok ? fmt(o.notes) : "—"} caption="笔记入库" />
        </div>
        <div className="relative">
          <div className="inline-flex items-center gap-2 rounded-full border border-flywheel-accent/30 bg-flywheel-accent/10 px-3 py-1 text-xs font-medium text-flywheel-accent">
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-flywheel-accent" />
            {o.ok ? "飞轮在转" : "离线"}
          </div>
          <h2 className="mt-4 text-2xl font-bold leading-snug text-white sm:text-3xl">
            发得越多 → 库越准 → <span className="text-glow text-flywheel-accent">命中越高</span>
          </h2>
          <p className="mt-3 max-w-md text-sm leading-relaxed text-slate-400">
            把每一次种草投放的真实结果沉淀成可迁移的爆款经验,回流给生产系统——
            <span className="text-slate-300">越用越强的数据飞轮</span>。
          </p>
          <div className="mt-6 flex flex-wrap gap-6">
            <div>
              <div className="text-2xl font-bold tabular-nums text-white">{o.ok ? o.projects : "—"}</div>
              <div className="text-xs text-slate-500">项目</div>
            </div>
            <div>
              <div className="text-2xl font-bold tabular-nums text-white">{o.ok ? o.baokuan : "—"}</div>
              <div className="text-xs text-slate-500">真爆款燃料</div>
            </div>
            <div>
              <div className="text-2xl font-bold tabular-nums text-white">{o.ok ? o.cards : "—"}</div>
              <div className="text-xs text-slate-500">经验卡上架</div>
            </div>
          </div>
        </div>
      </section>

      {/* 大数矩阵 */}
      <section className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        <Metric label="项目" value={o.ok ? o.projects : 0} />
        <Metric label="笔记" value={o.ok ? fmt(o.notes) : 0} />
        <Metric label="真爆款燃料" value={o.ok ? o.baokuan : 0} hint="状态字段权威" />
        <Metric label="经验卡" value={o.ok ? o.cards : 0} hint="书架已策展" />
        <Metric label="essence 已标" value={o.ok ? fmt(o.essence) : 0} hint="穿越周期内核" />
        <Metric label="馆员借阅" value={o.ok ? o.librarian : 0} hint="通道2 缓存行" />
      </section>

      {/* 系统 / 节点 */}
      <section className="mt-10">
        <h2 className="mb-3 text-sm font-medium uppercase tracking-wider text-slate-400">系统 / 节点</h2>
        <div className="flex flex-wrap gap-3">
          {NODES.map((n) => (
            <NodePill
              key={n.id}
              label={n.label}
              alive={n.status === "live" && o.ok}
              planned={n.status === "planned"}
            />
          ))}
        </div>
      </section>

      {/* 实时 */}
      <section className="mt-10">
        <h2 className="mb-3 text-sm font-medium uppercase tracking-wider text-slate-400">实时</h2>
        <LivePresence />
      </section>

      <footer className="mt-16 text-xs text-slate-600">
        Phase 0 骨架 · 设计见 <code>docs/24-dashboard-plan.md</code> · 服务端实时取数
      </footer>
    </main>
  );
}
