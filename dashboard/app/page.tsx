import { getSupabase } from "@/lib/supabase";
import { NODES } from "@/config/flywheel";
import LivePresence from "@/components/LivePresence";

// ISR:每 60s 重新在服务端取数,给一点"实时"感(docs/24 §2)。
export const revalidate = 60;

type Overview = {
  projects: number;
  notes: number;
  baokuan: number;
  cards: number;
  librarian: number;
  ok: boolean;
};

async function getOverview(): Promise<Overview> {
  const sb = getSupabase();
  if (!sb) return { projects: 0, notes: 0, baokuan: 0, cards: 0, librarian: 0, ok: false };
  const tv = sb.schema("truth_vault");
  try {
    const count = async (q: any) => (await q).count ?? 0;
    const [projects, notes, baokuan, cards, librarian] = await Promise.all([
      count(tv.from("projects").select("*", { count: "exact", head: true })),
      count(tv.from("notes").select("*", { count: "exact", head: true })),
      count(
        tv
          .from("notes")
          .select("*", { count: "exact", head: true })
          .in("tier", ["爆", "大爆"])
          .eq("tier_source", "状态字段")
      ),
      count(tv.from("flywheel_lesson_annotations").select("*", { count: "exact", head: true })),
      count(tv.from("flywheel_librarian_cache").select("*", { count: "exact", head: true })),
    ]);
    return { projects, notes, baokuan, cards, librarian, ok: true };
  } catch {
    return { projects: 0, notes: 0, baokuan: 0, cards: 0, librarian: 0, ok: false };
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
        className={`inline-block h-2.5 w-2.5 rounded-full ${
          alive ? "bg-flywheel-accent" : "bg-slate-600"
        }`}
      />
      {name}
      {planned ? <span className="text-xs text-slate-500">规划中</span> : null}
    </div>
  );
}

export default async function Page() {
  const o = await getOverview();
  return (
    <main className="mx-auto max-w-5xl px-6 py-12">
      <header className="mb-10">
        <h1 className="text-2xl font-bold">飞轮总看板</h1>
        <p className="mt-1 text-slate-400">
          帆谷飞轮生态 · Truth Vault / autowriter / sanshengliubu 实时态势
        </p>
        {!o.ok && (
          <p className="mt-3 rounded-lg bg-flywheel-warn/10 px-4 py-2 text-sm text-flywheel-warn">
            ⚠️ 未连到 Supabase(本地/部署需配 <code>SUPABASE_URL</code> +{" "}
            <code>SUPABASE_SERVICE_ROLE_KEY</code>)。当前显示占位 0。
          </p>
        )}
      </header>

      {/* 头部大数(Phase 0:TV 真实聚合;Phase 2 起补 aw/ssll/通道) */}
      <section className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        <Metric label="项目" value={o.projects} />
        <Metric label="笔记" value={o.notes} />
        <Metric label="真爆款燃料" value={o.baokuan} hint="状态字段权威" />
        <Metric label="经验卡" value={o.cards} hint="书架已策展" />
        <Metric label="馆员借阅" value={o.librarian} hint="通道2 缓存行" />
      </section>

      {/* 系统"活着"灯(config 驱动,docs/24 §5.5;Phase 3 起接真实最近活动) */}
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

      {/* 实时"在线"卡(留好接口:去中心化 / 在线改稿人数;现在 stub→规划中) */}
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
