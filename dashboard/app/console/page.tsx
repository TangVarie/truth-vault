import Link from "next/link";
import { getSupabase } from "@/lib/supabase";
import { NODES } from "@/config/flywheel";
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

function Metric({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <div className="rounded-2xl bg-flywheel-card border border-white/5 p-6">
      <div className="text-sm text-slate-400">{label}</div>
      <div className="mt-2 text-4xl font-semibold text-flywheel-accent tabular-nums">{value}</div>
      {hint ? <div className="mt-1 text-xs text-slate-500">{hint}</div> : null}
    </div>
  );
}

function SystemDot({ name, alive, planned }: { name: string; alive: boolean; planned?: boolean }) {
  return (
    <div className="flex items-center gap-2 rounded-full bg-white/5 px-4 py-2 text-sm">
      <span
        className={`inline-block h-2.5 w-2.5 rounded-full ${alive ? "bg-flywheel-accent" : "bg-slate-600"}`}
      />
      {name}
      {planned ? <span className="text-xs text-slate-500">规划中</span> : null}
    </div>
  );
}

export default async function ConsolePage() {
  const o = await getOverview();
  return (
    <main className="mx-auto max-w-5xl px-6 py-12">
      <header className="mb-10">
        <Link href="/" className="text-xs text-slate-500 hover:text-slate-300">
          ← 返回开篇
        </Link>
        <h1 className="mt-2 text-2xl font-bold">飞轮总看板 · 公众版</h1>
        <p className="mt-1 text-slate-400">
          帆谷飞轮生态 · Truth Vault / autowriter / sanshengliubu 实时态势
        </p>
        {!o.ok && (
          <p className="mt-3 rounded-lg bg-flywheel-warn/10 px-4 py-2 text-sm text-flywheel-warn">
            ⚠️ 未连到 Supabase(部署需配 <code>SUPABASE_URL</code> + <code>SUPABASE_SERVICE_ROLE_KEY</code>)。当前显示占位 0。
          </p>
        )}
      </header>

      <section className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        <Metric label="项目" value={o.projects} />
        <Metric label="笔记" value={o.notes} />
        <Metric label="真爆款燃料" value={o.baokuan} hint="状态字段权威" />
        <Metric label="经验卡" value={o.cards} hint="书架已策展" />
        <Metric label="essence 已标" value={o.essence} hint="穿越周期内核" />
        <Metric label="馆员借阅" value={o.librarian} hint="通道2 缓存行" />
      </section>

      <section className="mt-10">
        <h2 className="mb-3 text-sm font-medium text-slate-400">系统 / 节点</h2>
        <div className="flex flex-wrap gap-3">
          {NODES.map((n) => (
            <SystemDot
              key={n.id}
              name={n.label}
              alive={n.status === "live" && o.ok}
              planned={n.status === "planned"}
            />
          ))}
        </div>
      </section>

      <section className="mt-10">
        <h2 className="mb-3 text-sm font-medium text-slate-400">实时</h2>
        <LivePresence />
      </section>

      <footer className="mt-16 text-xs text-slate-600">
        Phase 0 骨架 · 设计见 <code>docs/24-dashboard-plan.md</code> · 服务端 ISR 60s
      </footer>
    </main>
  );
}
