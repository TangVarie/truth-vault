import type { Metadata } from "next";
import type { ReactNode } from "react";
import Link from "next/link";
import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { SESSION_COOKIE, verifySessionToken } from "@/lib/auth";
import { WB_COOKIE, isWorkbenchConfigured, verifyWorkbenchToken } from "@/lib/workbench-auth";
import {
  getWorkbenchData,
  isNotBuilt,
  type AccountRow,
  type BoostRow,
  type ContentCountRow,
  type ContentNoteRow,
  type ExposureRow,
  type Got,
  type ShadowRow,
  type StatusRow,
  type Watch24Row,
  type Watch72Row,
} from "@/lib/workbench-data";
import { consoleLabel } from "@/config/showcase";
import { BG, BORD, CORAL, INKC, MUTE, SAGE, Block, BoostChart, Empty, Table, css, fmt, pct, sans } from "./_components/ui";

/**
 * /console/workbench = 工作台 (W-63, D-169, docs/35)。影子期只给 owner 看：团队闸 + owner 闸，第二道口令没配就是 404。
 * 只读：不写库、不存标记、不调模型；没有按钮、没有输入框 (除了 owner 口令)。数据是每天一份的快照, 读 workbench.v_* 九个打过码的视图。
 */
export const metadata: Metadata = { robots: { index: false, follow: false }, title: "工作台 · 内部座舱" };
export const dynamic = "force-dynamic";

const LINE = 45;
const MIN_N = 20;

type Obj = Record<string, unknown> | null;
const n0 = (o: Obj, k: string): number => {
  const v = o?.[k];
  return typeof v === "number" ? v : Number(v ?? 0) || 0;
};
const word = (o: Obj): string => String(o?.status ?? "");

function bjToday(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai" }).format(new Date());
}
function bjTime(iso: string | null): string {
  if (!iso) return "不知道";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(new Date(iso));
}
function daysBetween(a: string, b: string): number {
  return Math.round((Date.parse(b) - Date.parse(a)) / 86400000);
}
/** 第一次配的时候最可能碰到的几种失败，各给一句人话 (docs/35 第 4 节)。别的只给代码。 */
const FAIL_HINT: Record<string, string> = {
  bad_url: "连接串读不了，多半是密码里有 / # ? @ % 这类字符。密码只用字母和数字，重设后改 Vercel 上的 WORKBENCH_DATABASE_URL",
  "28P01": "密码不对：tv_workbench_ro 还没设密码，或和 WORKBENCH_DATABASE_URL 里的不一样",
  "28000": "这个用户登录不了：看 tv_workbench_ro 建好没有、连接串里的用户名对不对",
  XX000: "连接池不认这个用户，多半是连接串里的用户名没写成 tv_workbench_ro.<项目 ref>（连接池事务模式，端口 6543）",
  CONNECT_TIMEOUT: "连不上数据库（超时）：看连接串的主机和端口（6543），和 Supabase 有没有开网络限制",
  ETIMEDOUT: "连不上数据库（超时）：看连接串的主机和端口（6543），和 Supabase 有没有开网络限制",
  ECONNREFUSED: "连不上数据库（被拒）：看连接串的主机和端口（6543）",
  ENOTFOUND: "连不上数据库（主机名找不到）：看连接串的主机",
  "3D000": "连接串里的库名不对，应该是 postgres",
  "42501": "没有读权限：SQL 可能只跑了一半，在 SQL editor 把 schemas/workbench_v1.sql 整份再跑一遍",
  "53300": "连接数满了（tv_workbench_ro 最多 5 个），过一会儿再刷新",
  "57014": "取数超时（超过 8 秒），过一会儿再刷新",
};
function failText(g: Got<unknown>): string {
  if (g.ok) return "";
  if (g.code === "no_url") return "取数没配：Vercel 上还没有 WORKBENCH_DATABASE_URL。";
  if (isNotBuilt(g.code)) return "还没建：owner 还没在 Supabase SQL editor 跑 schemas/workbench_v1.sql。";
  const hint = FAIL_HINT[g.code];
  return hint ? `取数失败：${hint}（代码 ${g.code}）。` : `取数失败（代码 ${g.code}）。`;
}
function rowsOf<T extends { project_id: string | null }>(g: Got<T>, pid: string): T[] {
  return g.ok ? g.rows.filter((r) => r.project_id === pid) : [];
}

function navPill(): React.CSSProperties {
  return { border: "1.5px solid rgba(255,255,255,0.18)", borderRadius: 999, padding: "5px 14px", fontSize: 12.5, fontWeight: 600, color: "#fff", textDecoration: "none", background: "transparent", cursor: "pointer" };
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <main style={{ minHeight: "100vh", background: BG, color: "#fff", fontFamily: sans }}>
      <style dangerouslySetInnerHTML={{ __html: css }} />
      <div style={{ position: "sticky", top: 0, zIndex: 40, background: "rgba(10,10,11,0.85)", backdropFilter: "blur(8px)", borderBottom: `1px solid ${BORD}`, marginBottom: 8 }}>
        <div style={{ maxWidth: 1280, margin: "0 auto", padding: "12px 20px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <Link href="/console" style={{ fontWeight: 800, fontSize: 17, color: "#fff", textDecoration: "none" }}>BYWOOD <span style={{ color: "#6b7280" }}>· 工作台</span></Link>
          <div style={{ display: "flex", gap: 8 }}>
            <Link href="/console" style={navPill()}>回座舱</Link>
            <form action="/api/auth/logout" method="POST"><button type="submit" style={navPill()}>登出</button></form>
          </div>
        </div>
      </div>
      <div className="wb">{children}</div>
    </main>
  );
}

function Unlock({ bad }: { bad: boolean }) {
  return (
    <Shell>
      <section className="wb-sec" style={{ maxWidth: 420 }}>
        <h2>工作台</h2>
        <p className="wb-sub">影子期只给 owner 看。请输入 owner 口令。</p>
        <form method="POST" action="/console/workbench/unlock" style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 10 }}>
          <input type="password" name="password" required autoComplete="current-password" placeholder="owner 口令"
            style={{ borderRadius: 12, border: `1px solid ${BORD}`, background: "rgba(0,0,0,0.3)", color: "#fff", padding: "10px 12px", fontSize: 14 }} />
          <button type="submit" style={{ borderRadius: 12, border: 0, background: CORAL, color: INKC, padding: "10px 12px", fontWeight: 700, fontSize: 14, cursor: "pointer" }}>进入</button>
        </form>
        {bad && <p className="wb-mute" style={{ color: CORAL }}>口令不对。</p>}
      </section>
    </Shell>
  );
}

// ── 块 1 ─────────────────────────────────────────────────────────────
function Accounts({ st, got }: { st: StatusRow; got: Got<AccountRow> }) {
  const b = st.b1;
  const rows = rowsOf(got, st.project_id as string);
  const left = n0(b, "tier2_recent") - n0(b, "tier2_listed");
  return (
    <Block title="1 · 账号底子" lead="账号底子的信号，不保证这个号发什么都会爆。一档：这个号在本项目有一篇 ≥7 天前发、定级为爆或大爆的帖；二档：在同平台的其他项目有。">
      <p className="wb-mute">
        一档 {n0(b, "tier1")} 个（全列）；二档 {n0(b, "tier2")} 个，其中近 90 天发过帖的 {n0(b, "tier2_recent")} 个，列了 {n0(b, "tier2_listed")} 个
        {left > 0 ? `，还有 ${left} 个没列` : ""}；降档 {n0(b, "downgrade")} 个（本项目发过、定级过、一篇没爆过，只给个数）。
        近 30 天本项目有 {n0(b, "new_acct_posts_30d")} 篇是新号发的，新号没有底子可看；{n0(b, "no_acct_posts_30d")} 篇没有账号。
      </p>
      <p className="wb-mute">依据（W-64）：一档的号再发，过评论线 19.3% 对 8.5%，但只有 3 个项目撑着；二档 9.3% 对 6.7%，16 个项目里 13 个同向。比例是一群号的，不是哪一个号自己的。</p>
      {!got.ok ? <Empty>{failText(got)}</Empty> : rows.length === 0 ? <Empty>{word(b) || "本项目没有一档、二档的号"}</Empty> : (
        <Table
          head={["档", "账号码", "名字提示", "本项目 发 / 定级 / 爆", "别的项目爆过", "本项目最近一次发帖", "备注"]}
          rows={rows.map((r) => [
            r.tier,
            <span key="c" className="code">{r.account_code}</span>,
            r.name_hint,
            <span key="n" className="code">{`${r.posts_here} / ${r.graded_here} / ${r.hits_here}`}</span>,
            r.other_hit ? "有" : "—",
            r.last_post_here ?? "本项目还没发过",
            [r.downgrade ? "本项目发过，没爆过" : "", r.code_clash ? "码撞了" : ""].filter(Boolean).join("；") || "—",
          ])}
        />
      )}
    </Block>
  );
}

// ── 块 2 ─────────────────────────────────────────────────────────────
function Content({ st, counts, notes }: { st: StatusRow; counts: Got<ContentCountRow>; notes: Got<ContentNoteRow> }) {
  const b = st.b2;
  const pid = st.project_id as string;
  const all = rowsOf(counts, pid);
  const shown = all.filter((r) => r.n_flag > 0);
  // 已标的帖里一篇都没有的写法不列；一篇都没标的写法另说「都没标」，不说成「没有」
  const none = all.filter((r) => r.n_flag === 0 && r.n_noflag > 0);
  const allUnl = all.filter((r) => r.n_flag === 0 && r.n_noflag === 0);
  const list = rowsOf(notes, pid);
  const both = (r: ContentCountRow, yes: boolean) => {
    const n = yes ? r.n_flag : r.n_noflag;
    const g = yes ? r.graded_flag : r.graded_noflag, h = yes ? r.hits_flag : r.hits_noflag;
    const k = yes ? r.expo_known_flag : r.expo_known_noflag, e = yes ? r.expo_hi_flag : r.expo_hi_noflag;
    const expo = `曝光知道的 ${k} 篇里过中位数 ${e} 篇`;
    return r.scope === "只看曝光" ? `${n} 篇；${expo}` : `${n} 篇；已定级 ${g} 篇里爆 ${h} 篇；${expo}`;
  };
  return (
    <Block title="2 · 写法提示" lead="提示，不是门槛。没标的帖写「没标」，不当成「没有这种写法」。内容只能说明有没有资格，不说明会不会爆。">
      <p className="wb-mute">
        本项目 ≥7 天前发、已定级的帖 {n0(b, "graded_7d")} 篇，其中爆 {n0(b, "hits_7d")} 个。
        {n0(b, "hits_7d") < 10 ? "项目内的爆太少，下表只看计数，不算倍数。" : "下表只给计数，倍数看最后一列 W-64 的。"}
        下表的「爆」数的是定级为爆或大爆（≥7 天前发、已定级的帖），和影子核对里的「过评论线」（满 7 天那天评论数 ≥{LINE} 条）不是一个数；
        「曝光过中位数」只数 ≥14 天前发的帖。
      </p>
      {n0(b, "body_empty") > 0 && (
        <p className="wb-mute">
          本项目有 {n0(b, "body_empty")} 篇抽特征那一次正文是空的（正文后来才补、还没重抽；近 14 天 {n0(b, "body_empty_14d")} 篇）。
          这几篇的品牌位置、产品角色、求助式、功效承诺都按没标算，不算「不提品牌」。
        </p>
      )}
      {!counts.ok ? <Empty>{failText(counts)}</Empty> : shown.length === 0 ? <Empty>本项目没有一篇带这八种写法（或都没标）。</Empty> : (
        <Table
          head={["写法", "加分 / 减分", "有这写法", "没有", "没标", "W-64（跨项目）"]}
          rows={shown.map((r) => [r.hint, r.side, both(r, true), both(r, false), `${r.n_unlabeled} 篇`, <span key="w" style={{ whiteSpace: "normal" }}>{r.w64}</span>])}
        />
      )}
      {none.length > 0 && (
        <p className="wb-mute">本项目已标的帖里一篇都没有的写法不列：{none.map((r) => `${r.hint}（没标 ${r.n_unlabeled} 篇）`).join("、")}。</p>
      )}
      {allUnl.length > 0 && <p className="wb-mute">本项目的帖都没标、看不出有没有的写法：{allUnl.map((r) => r.hint).join("、")}。</p>}
      <h4>近 14 天每篇</h4>
      {word(b) === "多数帖没标" && (
        <p className="wb-mute">多数帖没标：近 14 天 {n0(b, "notes_14d")} 篇里 {n0(b, "notes_14d_all_unlabeled")} 篇六维全没标。</p>
      )}
      {!notes.ok ? <Empty>{failText(notes)}</Empty> : list.length === 0 ? <Empty>近 14 天没帖。</Empty> : (
        <Table
          head={["帖码", "账号码", "发布日期", "加分写法", "减分写法（只看曝光）", "没标"]}
          rows={list.map((r) => [
            <span key="n" className="code">{r.note_code}</span>,
            <span key="a" className="code">{r.account_code ?? "没有账号"}</span>,
            r.publish_day,
            r.plus_hints.length ? r.plus_hints.map((h) => <span key={h} className="wb-tag">{h}</span>) : "—",
            r.minus_hints.length ? r.minus_hints.map((h) => <span key={h} className="wb-tag">{h}</span>) : "—",
            r.unlabeled.length ? `${r.body_empty ? "抽特征时正文是空的：" : ""}${r.unlabeled.join("、")}` : "—",
          ])}
        />
      )}
    </Block>
  );
}

// ── 块 3 ─────────────────────────────────────────────────────────────
function Watch({ st, w24, w72 }: { st: StatusRow; w24: Got<Watch24Row>; w72: Got<Watch72Row> }) {
  const a = st.b3a, b = st.b3b;
  const pid = st.project_id as string;
  const listed = rowsOf(w24, pid).filter((r) => r.status === "进清单");
  const ranked = rowsOf(w72, pid);
  const p90 = a?.p90_now == null ? null : Number(a.p90_now);
  const line = a?.line_now == null ? null : Number(a.line_now);
  return (
    <Block title="3 · 值得盯的帖" lead="观察清单，不是加热建议。清单里的高评论有一部分是我们自己铺的，进清单只说明这篇在往评论线走，不说明真实读者在涨。">
      <h4>3a · 24 小时评论数</h4>
      <p className="wb-mute">
        近 5 天 {n0(a, "recent_notes")} 篇，有 24h 快照 {n0(a, "candidates")} 篇（没有 24h 快照 {n0(a, "no_24h")} 篇
        {n0(a, "cc_null") ? `，24h 没记评论数 ${n0(a, "cc_null")} 篇` : ""}），进清单 {n0(a, "listed")} 篇。
        规则：24h 评论数在本项目更早的帖里排进前 10%（一样多的算一半），本项目更早的帖要有 {MIN_N} 篇以上。
        {line == null
          ? `本项目更早的帖只有 ${n0(a, "prior_now")} 篇有 24h 评论数，不到 ${MIN_N} 篇，没有线。`
          : `按今天本项目更早的 ${n0(a, "prior_now")} 篇算，24h 至少 ${line} 条评论才进清单；每篇是和它自己发布日之前的帖比，线会差一点。`}
        {p90 != null && line != null
          ? `W-64 原写的线是第 90 百分位，今天约 ${Math.round(p90)} 条；这里改成按排名划，见 docs/35 第 2.3 节，要 owner 定。`
          : ""}
      </p>
      <p className="wb-mute">进清单的帖里约两成过评论线，约五篇里四篇不会过（W-64：20–26%）。「24h」快照约在日期戳后 16 小时拍。</p>
      {!w24.ok ? <Empty>{failText(w24)}</Empty> : listed.length === 0 ? <Empty>{word(a) || "近 5 天没有帖进清单"}</Empty> : (
        <Table
          head={["帖码", "账号码", "发布日期", "24h 评论数", "在本项目的位置", "现在评论数", `现在过没过 ${LINE} 条`, "已知铺评条数（发出时间不明）"]}
          rows={listed.map((r) => [
            <span key="n" className="code">{r.note_code}</span>,
            <span key="a" className="code">{r.account_code ?? "没有账号"}</span>,
            r.publish_day,
            <span key="c" className="num">{fmt(r.comments_24h)}</span>,
            r.mid_rank == null ? "—" : `前 ${Math.max(1, Math.round((1 - r.mid_rank) * 100))}%`,
            <span key="m" className="num">{fmt(r.comments_now)}</span>,
            r.over_line_now == null ? "不知道" : r.over_line_now ? "过了" : "没过",
            <span key="s" className="num">{r.seeded_known}</span>,
          ])}
        />
      )}
      <h4>3b · 第 4–5 天的曝光（快照标着 72h）</h4>
      <p className="wb-mute">
        近 8 天 {n0(b, "recent_notes")} 篇，有「72h」快照 {n0(b, "with_72h")} 篇；不到 96 小时拍的丢掉 {n0(b, "too_early")} 个，没有曝光的 {n0(b, "no_impressions")} 个，
        已经过了本项目曝光中位数的 {n0(b, "above_median")} 个不排。只说曝光，不说爆：W-64 里按这个排，之后曝光过中位数的排序能力约 0.81（0.5 是瞎猜）。
      </p>
      {!w72.ok ? <Empty>{failText(w72)}</Empty> : ranked.length === 0 ? <Empty>{word(b) || "近 8 天没帖"}</Empty> : (
        <Table
          head={["排名", "帖码", "账号码", "发布日期", "第 4–5 天的曝光（快照标着 72h）", "阅读", "点击率", "快照在第几小时", "现在曝光（新帖还在涨）", "本项目曝光中位数"]}
          rows={ranked.map((r) => [
            r.rank_in_project,
            <span key="n" className="code">{r.note_code}</span>,
            <span key="a" className="code">{r.account_code ?? "没有账号"}</span>,
            r.publish_day,
            <span key="i" className="num">{fmt(r.impressions_72h)}</span>,
            <span key="r" className="num">{fmt(r.reads_72h)}</span>,
            r.ctr_72h == null ? "缺" : `${(r.ctr_72h * 100).toFixed(1)}%`,
            r.hours_72h ?? "缺",
            <span key="w" className="num">{fmt(r.impressions_now)}</span>,
            <span key="m" className="num">{fmt(r.median_impressions)}</span>,
          ])}
        />
      )}
    </Block>
  );
}

// ── 块 4 ─────────────────────────────────────────────────────────────
function Exposure({ st, got }: { st: StatusRow; got: Got<ExposureRow> }) {
  const b = st.b4;
  const hit = rowsOf(got, st.project_id as string).filter((r) => r.evening || r.weekend || r.same_acct_3d);
  const which = (r: ExposureRow) => [r.evening ? "晚上发" : "", r.weekend ? "周末发" : "", r.same_acct_3d ? "同号 3 天内连发" : ""].filter(Boolean);
  return (
    <Block title="4 · 曝光提示" lead="现在没有检验过的流量异常规则。这里只有三条发布前就知道的提示，只说曝光，不说爆。">
      <p className="wb-mute">
        近 14 天 {n0(b, "notes_14d")} 篇：北京时间 18 点以后发 {n0(b, "evening")} 篇，周末发 {n0(b, "weekend")} 篇，同号 3 天内连发 {n0(b, "same_acct_3d")} 篇。
        不知道几点发 {n0(b, "hour_unknown")} 篇（其中笔记 ID 的日期和记录的日期对不上 {n0(b, "date_mismatch")} 篇，这些也不算周末）；没有账号 {n0(b, "no_account")} 篇。
      </p>
      <p className="wb-mute">W-64（曝光过本项目中位数的机会）：晚上发约 0.63 倍，周末发约 0.69 倍（同周内比约 0.79 倍），同号 3 天内连发约 0.74 倍。三条对爆都没有显著作用。</p>
      {!got.ok ? <Empty>{failText(got)}</Empty> : hit.length === 0 ? <Empty>{word(b) || "近 14 天三条都没触发"}</Empty> : (
        <Table
          head={["帖码", "账号码", "发布日期", "中了哪条", "几点发（北京）", "现在曝光 / 本项目中位数（新帖还在涨）"]}
          rows={hit.map((r) => [
            <span key="n" className="code">{r.note_code}</span>,
            <span key="a" className="code">{r.account_code ?? "没有账号"}</span>,
            r.publish_day,
            which(r).map((h) => <span key={h} className="wb-tag">{h}</span>),
            r.hour_bj == null ? (r.hour_status === "日期对不上" ? "日期对不上" : "不知道几点发") : `${r.hour_bj} 点`,
            <span key="i" className="num">{`${fmt(r.impressions_now)} / ${fmt(r.median_impressions)}`}</span>,
          ])}
        />
      )}
    </Block>
  );
}

// ── 块 5 ─────────────────────────────────────────────────────────────
/** v_paid_boost_evidence 的状态词 (v1.22) → 人话。认不出的写「缺」。 */
const BOOST_MISS: Record<string, string> = {
  "missing:not_due": "还没到那天",
  "missing:before_history": "那时库里还没开始记这篇",
  "missing:no_reading_before_boost": "投流前没有读数",
  "missing:no_full_sync_that_day": "那天没跑完整同步",
  "missing:value_null": "那天快照里没有这个数",
  "missing:value_not_numeric": "那天记的不是数字",
  "missing:no_rescreenshot": "投流后没换过截图，这个数没更新",
};
const missWhy = (s: string | null): string => (s && BOOST_MISS[s]) || "缺";
function Boost({ st, got }: { st: StatusRow; got: Got<BoostRow> }) {
  const rows = rowsOf(got, st.project_id as string);
  const miss = (label: string, v: number | null, s: string | null) => (v == null ? `${label}（${missWhy(s)}）` : "");
  const val = (v: number | null, s: string | null) => (v == null ? `缺（${missWhy(s)}）` : fmt(v));
  return (
    <Block title="5 · 投流前后" lead="只画投流前后的数，不给效果结论。评论数里有铺评，图下写明维护时铺了几条。缺的点断开，不补 0。">
      {!got.ok ? <Empty>{failText(got)}</Empty> : rows.length === 0 ? <Empty>{word(st.b5) || "近 30 天没有投流记录"}</Empty> : (
        <div className="wb-curves">
          {rows.map((r) => {
            const missing = [
              miss("基线", r.comments_base, r.comments_base_status), miss("当天", r.comments_d0, r.comments_d0_status),
              miss("第 1 天", r.comments_d1, r.comments_d1_status), miss("第 3 天", r.comments_d3, r.comments_d3_status),
              miss("第 7 天", r.comments_d7, r.comments_d7_status),
            ].filter(Boolean);
            return (
              <div key={r.event_code} className="wb-curve">
                <div className="wb-mute" style={{ marginTop: 0 }}>帖码 <span className="code">{r.note_code}</span> · 事件码 <span className="code">{r.event_code}</span> · 评论数</div>
                <BoostChart points={[
                  { label: "基线", at: -1, v: r.comments_base }, { label: "当天", at: 0, v: r.comments_d0 },
                  { label: "第 1 天", at: 1, v: r.comments_d1 }, { label: "第 3 天", at: 3, v: r.comments_d3 },
                  { label: "第 7 天", at: 7, v: r.comments_d7 },
                ]} />
                <p className="wb-mute">
                  投流日 {r.boost_date}；发布日 {r.publish_day ?? "不知道"}；发布后第 {r.days_after_publish ?? "?"} 天投。
                  {r.seeded_on_maintain == null ? "维护时铺了几条评论：不知道。" : `维护时铺了 ${r.seeded_on_maintain} 条评论。`}
                </p>
                <p className="wb-mute">
                  曝光：投流前 {val(r.impressions_base, r.impressions_base_status)}，第 7 天 {val(r.impressions_d7, r.impressions_d7_status)}；
                  阅读：投流前 {val(r.reads_base, r.reads_base_status)}，第 7 天 {val(r.reads_d7, r.reads_d7_status)}。
                </p>
                {missing.length > 0 && <p className="wb-mute">评论数缺的点：{missing.join("，")}</p>}
              </div>
            );
          })}
        </div>
      )}
    </Block>
  );
}

// ── 影子核对 ─────────────────────────────────────────────────────────
const SHADOW_ORDER = ["1", "2", "3a", "3b", "4", "5"];
const MEASURE_ORDER = ["满 7 天过评论线", "已定级为爆", "满 14 天曝光过中位数", "其中有投流记录", "其中有投流或新铺评", "满 8 天这个点有数"];
const SHADOW_TITLES: Record<string, string> = {
  "1": "块 1 · 发帖号在发布前一份快照里的档",
  "2": "块 2 · 每种写法 有 / 没有 / 没标",
  "3a": "块 3a · 24 小时评论数（W-64：进清单的过线比例约 20–26%）",
  "3b": "块 3b · 第 4–5 天的曝光（说明那一列的排序能力：0.5 是瞎猜，W-64 约 0.81）",
  "4": "块 4 · 三条发布前提示",
  "5": "块 5 · 投流前后的数据全不全（只核数据，不核效果）",
};
function Shadow({ got, st }: { got: Got<ShadowRow>; st: StatusRow | undefined }) {
  const rows = got.ok ? got.rows : [];
  const blocks = SHADOW_ORDER;
  const mo = (m: string) => {
    const i = MEASURE_ORDER.findIndex((x) => m.startsWith(x));
    return (i < 0 ? 99 : i) + (m.includes("晚记") ? 0.5 : 0);
  };
  return (
    <section id="shadow" className="wb-sec wb-anchor">
      <h2>影子核对</h2>
      <p className="wb-sub">
        全部项目合在一起，只有计数。每篇帖在同一块只算第一次出现那天。「过评论线」= 发布满 7 天那天评论数 ≥{LINE} 条（含铺评）；
        「曝光过中位数」= 满 14 天那天曝光高于本项目当天的中位数。结果还不知道的不算进篇数。篇数不到 {MIN_N} 写「数不够，不下结论」。
        影子期有投流记录或新铺评的帖另数一行：照清单去推的那篇，是被我们自己推过线的。
        满了之后晚 2 天以上才记的（多是第一份快照那天补记的），数是晚几天的，「看什么」带「晚记」单独一行。
        「已定级为爆」只数定级为爆、大爆、趴的帖，没定级的不算进篇数。
      </p>
      {st && <p className="wb-mute">影子期从 {st.first_day} 起，共 {st.n_days} 份快照。</p>}
      {!got.ok ? <Empty>{failText(got)}</Empty> : rows.length === 0 ? <Empty>还没有能核的结果（帖要发布满 7 天）。</Empty> : blocks.map((b) => {
        const inBlock = rows.filter((r) => r.block === b);
        const gi = (g: string) => inBlock.findIndex((r) => r.grp === g);
        const part = [...inBlock].sort((x, y) => gi(x.grp) - gi(y.grp) || mo(x.measure) - mo(y.measure));
        if (part.length === 0) return <div key={b}><h4>{SHADOW_TITLES[b]}</h4><Empty>还没有。</Empty></div>;
        return (
          <div key={b}>
            <h4>{SHADOW_TITLES[b]}</h4>
            <Table
              head={["组", "看什么", "篇数", "是", "占比", "说明"]}
              rows={part.map((r) => [
                r.grp, r.measure, <span key="n" className="num">{r.n}</span>, <span key="y" className="num">{r.n_yes}</span>, pct(r.n_yes, r.n),
                [r.n < MIN_N ? "数不够，不下结论" : "", r.value != null ? `排序能力 ${r.value}` : "", r.rule_version !== "wb-v1" ? `规则 ${r.rule_version}` : ""].filter(Boolean).join("；") || "—",
              ])}
            />
          </div>
        );
      })}
    </section>
  );
}

export default async function WorkbenchPage(props: { searchParams: Promise<{ wb?: string | string[] }> }) {
  // 第一道：团队会话 (proxy.ts 拦过一次，这里再验)。第二道：owner 会话。都过了才取数。
  const jar = await cookies();
  if (!(await verifySessionToken(jar.get(SESSION_COOKIE)?.value))) redirect("/login?next=%2Fconsole%2Fworkbench");
  if (!isWorkbenchConfigured()) notFound();
  if (!(await verifyWorkbenchToken(jar.get(WB_COOKIE)?.value))) {
    const sp = await props.searchParams;
    return <Unlock bad={sp?.wb === "bad"} />;
  }

  const d = await getWorkbenchData();
  const today = bjToday();
  const run = d.status.ok ? d.status.rows[0] : undefined;
  const projects = d.status.ok ? d.status.rows.filter((r) => r.project_id) : [];
  const age = run ? daysBetween(run.day, today) : 0;

  return (
    <Shell>
      <section className="wb-sec" style={{ background: SAGE, color: INKC, border: 0 }}>
        <h2>工作台（影子期，只给 owner 看）</h2>
        <p style={{ fontSize: 13, marginTop: 6, lineHeight: 1.6 }}>
          今天 {today}（北京）。
          {run ? <>快照 {bjTime(run.taken_at)}（北京），规则 {run.rule_version}。{age > 0 && <b> 快照是 {age} 天前的。</b>}</> : null}
        </p>
        <p style={{ fontSize: 14, fontWeight: 700, marginTop: 10, lineHeight: 1.6 }}>
          「爆」实际上是一条评论数线：最终评论 ≥{LINE} 条，里面有我们自己铺的评论。下面说的「过评论线」都这样读。
        </p>
        <p style={{ fontSize: 12.5, marginTop: 6, opacity: 0.7 }}>这一页只读：每天一份快照，不写库、不调模型。页面上不写「建议这样做」。</p>
      </section>

      {!d.status.ok ? (
        <section className="wb-sec"><Empty>{failText(d.status)}</Empty></section>
      ) : !run ? (
        <section className="wb-sec"><Empty>还没有快照：SQL 已经跑了，但还没拍过一次 (select truth_vault.workbench_take_snapshot();)。</Empty></section>
      ) : projects.length === 0 ? (
        <section className="wb-sec"><Empty>快照里没有活跃项目（近 30 天没有一个项目有帖）。</Empty></section>
      ) : (
        <>
          <nav className="wb-toc" aria-label="项目">
            {projects.map((p) => {
              const idle = p.last_post_day ? daysBetween(p.last_post_day, today) : null;
              return (
                <a key={p.project_id} href={`#p-${p.project_id}`}>
                  {p.project_id}{idle != null && idle >= 3 ? ` · ${idle} 天没发帖` : ""}
                </a>
              );
            })}
            <a href="#shadow">影子核对</a>
          </nav>
          {projects.map((p) => {
            const pid = p.project_id as string;
            const idle = p.last_post_day ? daysBetween(p.last_post_day, today) : null;
            return (
              <section key={pid} id={`p-${pid}`} className="wb-sec wb-anchor">
                <h2>{pid} <span style={{ color: MUTE, fontSize: 15, fontWeight: 600 }}>{consoleLabel({ project_id: pid })}</span></h2>
                <p className="wb-mute">
                  近 30 天 {p.posts_30d ?? 0} 篇；最近一篇 {p.last_post_day ?? "—"}{idle != null && idle >= 3 ? `（${idle} 天没发帖）` : ""}；
                  数据截至 {p.data_as_of ? `${bjTime(p.data_as_of)}（最近一次跑完的同步）` : "不知道（没有跑完的同步记录）"}；本项目曝光中位数 {fmt(p.median_impressions)}。
                </p>
                <Accounts st={p} got={d.accounts} />
                <Content st={p} counts={d.contentCounts} notes={d.contentNotes} />
                <Watch st={p} w24={d.watch24} w72={d.watch72} />
                <Exposure st={p} got={d.exposure} />
                <Boost st={p} got={d.boost} />
              </section>
            );
          })}
          <Shadow got={d.shadow} st={run} />
        </>
      )}
    </Shell>
  );
}
