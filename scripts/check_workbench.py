#!/usr/bin/env python3
"""工作台 v0 的静态守卫 (W-63, D-169, docs/35-workbench.md)。不连库、不联网、不跑 Node; 只读仓里的文件。
库那一半 (权限、五块、影子核对、打码在真 Postgres 上对不对) 在 ci.yml 的 sql job: scripts/check_workbench_pg.sql。

  §1  规则常量: schemas/workbench_v1.sql 里函数的常量一个不多一个不少、值和这里钉的一样; 每一个在 docs/35 里都有对应的原话
      (≥7 天前、≥45 条、≥20 篇、mid_rank ≥ 0.9、第 90 百分位、近 5 / 8 / 14 / 30 天、≥96 小时、18 点以后、前 3 天到当天、90 天、50 个)
  §2  三条发布前提示、八种写法 (名字和加分 / 减分) 在 SQL 和 docs/35 第 2.2、2.4 节一致; 每种写法抄的 W-64 「x/y 项目同向」在文档那一行里
  §3  权限的写法: SQL 不碰 public schema; 不 GRANT 给 anon / authenticated / PUBLIC; 函数 SECURITY DEFINER + search_path 为空 +
      单独 REVOKE ... FROM PUBLIC; EXECUTE 只给 service_role; 九个 v_* 视图正好九个、全在 GRANT SELECT ... TO tv_workbench_ro 里;
      角色建成不带密码; 视图都是 security_invoker = false
  §4  看板: 取数文件第一行 import "server-only"、prepare: false、只读 workbench.v_* 而且和 SQL 的九个视图一致;
      工作台的文件里没有 "use client"、不引对外合成层 / AMPLIFY / getDashboardData / components/;
      页面 force-dynamic、noindex、先验团队会话再验 owner 会话再取数、没配 WORKBENCH_PASSWORD 就 notFound();
      owner cookie 签名带 wb: 前缀、钥匙里有 WORKBENCH_PASSWORD、httpOnly + secure; 登出也清它; /console 首页只在 owner 会话有效时给入口;
      整个看板没有 NEXT_PUBLIC_; postgres 依赖钉死版本; 页头写着「爆」是一条评论数线、里面有铺评
      建 postgres 客户端包在 try 里 (连接串解析失败时错误对象带着整条连接串, 不许往上抛进日志)
  §5  不能说的话: 工作台页面和组件的字里, 和 SQL 里会显示到页面上的中文字串 (状态词、写法、W-64 原话、影子核对的「看什么」;
      注释和 COMMENT ON 不算) 里, 没有 docs/35 第 2 节「不能说」的那些话 (固定的几句否定说法除外), 也没有 AUC、OR、value 这种词
  §6  CI 和文档接上了: ci.yml 的 sql job 跑这份 SQL 两遍 + 夹具, python job 跑本脚本和设密码脚本的自检; docs/00 的索引里有 docs/35;
      OPEN-ITEMS 的 W-63 有 11-25 v0 那一行; docs/35 第 4 节让 owner 用设密码脚本 (不在 SQL editor 写明文)

反证 (改坏之后必须变红):
  ① SQL 里 c_min_prior 改成 10 / 文档里所有「不到 20 篇」改成「不到 10 篇」                     → §1
  ② SQL 里加一个常量不写进这里 / 删一个                                                     → §1
  ③ 写法表里把「功效承诺」改成加分                                                          → §2
  ④ 加一句 GRANT SELECT ON workbench.v_status TO anon / 去掉函数的 REVOKE ... FROM PUBLIC     → §3
  ⑤ 新加一个 v_* 视图不进 GRANT / 不进看板的 WB_VIEWS                                       → §3 / §4
  ⑥ 取数文件去掉 import "server-only" / 页面先取数再验会话 / 给工作台组件加 "use client"     → §4
  ⑦ 页面上写「这个号会爆」「加热这篇」/ SQL 的「看什么」写回「（value = 项目内 AUC）」               → §5
  ⑧ 取数文件把 postgres(url, ...) 挪出 try                                                    → §4
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SQL = ROOT / "schemas" / "workbench_v1.sql"
PG_FIXTURE = ROOT / "scripts" / "check_workbench_pg.sql"
DOC = ROOT / "docs" / "35-workbench.md"
INDEX = ROOT / "docs" / "00-START-HERE.md"
OPEN_ITEMS = ROOT / "OPEN-ITEMS.md"
CI = ROOT / ".github" / "workflows" / "ci.yml"
DASH = ROOT / "dashboard"
DATA_TS = DASH / "lib" / "workbench-data.ts"
AUTH_TS = DASH / "lib" / "workbench-auth.ts"
PAGE = DASH / "app" / "console" / "workbench" / "page.tsx"
UNLOCK = DASH / "app" / "console" / "workbench" / "unlock" / "route.ts"
ROLE_PW = ROOT / "scripts" / "workbench_role_password.py"
WB_DIR = DASH / "app" / "console" / "workbench"
CONSOLE = DASH / "app" / "console" / "page.tsx"
LOGOUT = DASH / "app" / "api" / "auth" / "logout" / "route.ts"
PKG = DASH / "package.json"

# §1 规则常量: 名字 → (值, docs/35 里必须有的原话)
CONSTANTS: dict[str, tuple[str, list[str]]] = {
    "c_rule_version":   ("'wb-v1'", ["`wb-v1`"]),
    "c_active_days":    ("30", ["近 30 天（含今天）有北京发布日期的帖"]),
    "c_hit_lag_days":   ("7", ["≥7 天前发、已定级为爆或大爆", "过评论线只数 ≥7 天前发、已定级的帖"]),
    "c_tier2_days":     ("90", ["列近 90 天在任何项目发过帖的"]),
    "c_tier2_max":      ("50", ["最多 50 个"]),
    "c_line_comments":  ("45", ["评论数 ≥45 条（含铺评）"]),
    "c_expo_lag_days":  ("14", ["曝光只数 ≥14 天前发的帖"]),
    "c_notes_days":     ("14", ["近 14 天每篇帖", "近 14 天发的帖，每篇看三条"]),
    "c_watch24_days":   ("5", ["近 5 天（含今天）发、有 24h 快照的帖"]),
    "c_min_prior":      ("20", ["本项目更早的帖不到 20 篇"]),
    "c_mid_rank":       ("0.9", ["`mid_rank ≥ 0.9`（本项目前 10%）进清单"]),
    "c_p90":            ("0.9", ["第 90 百分位另记，只作参考"]),
    "c_watch72_days":   ("8", ["近 8 天（含今天）发"]),
    "c_min_hours72":    ("96", ["快照在日期戳后 ≥96 小时拍"]),
    "c_evening_hour":   ("18", ["北京时间 18 点以后发"]),
    "c_same_acct_days": ("3", ["另一篇的北京日期在本篇前 3 天到当天之间"]),
    "c_boost_days":     ("30", ["近 30 天投过流的事件"]),
    "c_keep_days":      ("90", ["删 90 天前的快照"]),
}
HINTS3 = ["晚上发", "周末发", "同号 3 天内连发"]
WRITING = {  # 写法 → 加分 / 减分 (docs/35 第 2.2 节那张表)
    "正文不提品牌": "加分", "产品不出场": "加分", "负面痛点基调": "加分", "求助式写法": "加分",
    "产品当主角": "减分", "产品当解决方案": "减分", "功效承诺": "减分", "场景植入": "减分",
}
VIEWS = ["v_status", "v_accounts", "v_content_counts", "v_content_notes", "v_watch_24h", "v_watch_72h",
         "v_exposure_hints", "v_boost_curves", "v_shadow_check"]
# §5 docs/35 第 2 节「不能说」里的话。页面上只许出现在下面几句固定的否定说法里。
BANNED_WORDS = ["会爆", "用这个号", "推荐号", "好号", "差号", "必须这样写", "这篇写错了", "加热这篇", "投这篇",
                "真实读者在涨", "限流", "被风控", "被平台压了", "投了有用", "投了没用", "该不该投", "几点投", "投哪篇最划算",
                "流量异常", "建议这样做", "AUC"]
# 只在 SQL 会显示到页面上的中文字串里查 (tsx 里 value 是代码里的字段名, 不查)
SQL_DISPLAY_BANNED = [r"(?<![A-Za-z_])value(?![A-Za-z_])", r"(?<![A-Za-z_])OR(?![A-Za-z_])", r"mid_rank", r"P90"]
ALLOWED_SENTENCES = [
    "不保证这个号发什么都会爆",
    "不说明真实读者在涨",
    "不说明会不会爆",
    "现在没有检验过的流量异常规则",
    "页面上不写「建议这样做」",
]
HIT_LINE = "「爆」实际上是一条评论数线"

problems: list[str] = []


def fail(msg: str) -> None:
    problems.append(msg)


def strip_sql_comments(text: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in text.splitlines())


def read(p: Path) -> str:
    if not p.exists():
        fail(f"{p.relative_to(ROOT)} 不在")
        return ""
    return p.read_text(encoding="utf-8")


def check_constants(sql: str, doc: str) -> None:
    got = dict(re.findall(r"^\s*(c_[a-z0-9_]+)\s+CONSTANT\s+\w+\s*:=\s*([^;]+);", sql, flags=re.M))
    got = {k: v.strip() for k, v in got.items()}
    if set(got) != set(CONSTANTS):
        fail(f"§1 SQL 里的规则常量和这里钉的不一样: 多 {sorted(set(got) - set(CONSTANTS))} 少 {sorted(set(CONSTANTS) - set(got))}")
    for name, (want, phrases) in CONSTANTS.items():
        if name in got and got[name] != want:
            fail(f"§1 {name} 是 {got[name]}, 钉的是 {want} (改规则要升 c_rule_version、改文档、改这里)")
        for ph in phrases:
            if ph not in doc:
                fail(f"§1 docs/35 里找不到「{ph}」({name} = {want} 的原话)")
    # 状态词里的数字跟着常量走, 不写死
    if "本项目更早的帖不到 %s 篇" not in sql or "本项目更早的帖不到 20 篇" in strip_sql_comments(sql):
        fail("§1 「本项目更早的帖不到 N 篇」要用 format(..., c_min_prior), 不写死 20")


def check_hints(sql: str, doc: str) -> None:
    for h in HINTS3:
        if f"| {h} |" not in doc:
            fail(f"§2 docs/35 第 2.4 节的表里没有「{h}」")
        if f"'{h}'" not in sql:
            fail(f"§2 SQL 里没有提示「{h}」")
    rows = re.findall(r"\(\d+, '([^']+)',\s*'(加分|减分)',\s*'[^']+',\s*'([^']+)'", sql)
    got = {h: side for h, side, _ in rows}
    if got != WRITING:
        fail(f"§2 SQL 的八种写法和加分 / 减分不对: {got}")
    for h, side, w64 in rows:
        m = re.search(rf"^\| {re.escape(h)} \| {side} \|(.*)$", doc, flags=re.M)
        if not m:
            fail(f"§2 docs/35 第 2.2 节的表里没有「{h} | {side}」这一行")
            continue
        frac = re.search(r"(\d+/\d+) 项目同向", w64)
        if not frac or frac.group(1) not in m.group(1):
            fail(f"§2 「{h}」SQL 抄的 W-64 同向项目数 {frac.group(1) if frac else '?'} 在文档那一行里找不到")


def check_grants(sql: str) -> None:
    code = strip_sql_comments(sql)
    if re.search(r"\bpublic\.", code, flags=re.I):
        fail("§3 workbench_v1.sql 碰了 public schema (public 的默认权限会把新对象给 anon)")
    for m in re.finditer(r"GRANT\s+[^;]*?\bTO\s+([^;]+);", code, flags=re.I | re.S):
        to = m.group(1).lower()
        if re.search(r"\b(anon|authenticated|public)\b", to):
            fail(f"§3 有一句 GRANT 给了 anon / authenticated / PUBLIC: {m.group(0)[:120]}")
    if "SECURITY DEFINER" not in code or "SET search_path = ''" not in code:
        fail("§3 快照函数要 SECURITY DEFINER 而且 SET search_path = ''")
    if "REVOKE ALL ON FUNCTION truth_vault.workbench_take_snapshot(DATE) FROM PUBLIC;" not in code:
        fail("§3 快照函数没有单独 REVOKE ... FROM PUBLIC (函数的 PUBLIC EXECUTE 是内置默认)")
    execs = re.findall(r"GRANT\s+EXECUTE\s+ON\s+FUNCTION\s+[^;]+?\bTO\s+(\w+)", code, flags=re.I)
    if execs != ["service_role"]:
        fail(f"§3 快照函数的 EXECUTE 只许给 service_role, 实际: {execs}")
    views = re.findall(r"CREATE OR REPLACE VIEW workbench\.(v_\w+) WITH \(security_invoker = false\)", code)
    all_views = re.findall(r"CREATE (?:OR REPLACE )?VIEW\s+workbench\.(\w+)", code)
    if sorted(views) != sorted(VIEWS) or sorted(all_views) != sorted(VIEWS):
        fail(f"§3 workbench 的视图应该正好是这九个、都写明 security_invoker = false: {sorted(all_views)}")
    g = re.search(r"GRANT SELECT ON ([^;]+?)\s+TO tv_workbench_ro;", code, flags=re.S)
    granted = sorted(re.findall(r"workbench\.(v_\w+)", g.group(1))) if g else []
    if granted != sorted(VIEWS):
        fail(f"§3 GRANT SELECT ... TO tv_workbench_ro 应该正好是九个视图: {granted}")
    if re.search(r"\bPASSWORD\b", code):
        fail("§3 SQL 里出现了 PASSWORD: 角色建成不带密码, owner 在 SQL editor 里自己设")
    if not re.search(r"CREATE ROLE tv_workbench_ro LOGIN NOINHERIT", code):
        fail("§3 tv_workbench_ro 要 LOGIN NOINHERIT")
    if re.search(r"GRANT\s+\w+\s+TO\s+tv_workbench_ro|GRANT\s+tv_workbench_ro\b|GRANT\s[^;]*\bauthenticator\b", code):
        fail("§3 tv_workbench_ro 不许进任何角色 (尤其 authenticator)")
    if re.search(r"GRANT\s+USAGE\s+ON\s+SCHEMA\s+truth_vault", code, flags=re.I):
        fail("§3 不许给 truth_vault 的 USAGE")


def _ts_strings(text: str) -> str:
    """tsx 里会显示的字: 字符串、模板字符串和 JSX 文字。粗取: 去掉注释后整段文本。"""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"(^|[^:])//[^\n]*", r"\1", text)
    return text


def check_dashboard(sql: str) -> None:
    data = read(DATA_TS)
    auth = read(AUTH_TS)
    page = read(PAGE)
    unlock = read(UNLOCK)
    console = read(CONSOLE)
    logout = read(LOGOUT)
    if not data.startswith('import "server-only";'):
        fail('§4 lib/workbench-data.ts 第一行要是 import "server-only";')
    if "prepare: false" not in data:
        fail("§4 连接池事务模式要 prepare: false")
    m = re.search(r"WB_VIEWS = \[(.*?)\] as const", data, flags=re.S)
    ts_views = re.findall(r'"(v_\w+)"', m.group(1)) if m else []
    if sorted(ts_views) != sorted(VIEWS):
        fail(f"§4 WB_VIEWS 和 SQL 的九个视图不一致: {ts_views}")
    if re.search(r"truth_vault|SUPABASE_SERVICE_ROLE_KEY|SUPABASE_ANON_KEY", _ts_strings(data)):
        fail("§4 工作台取数只许读 workbench.v_*, 不碰 truth_vault、不用 Supabase 的 key")
    if not re.search(r"workbench\.\$\{view\}", data):
        fail("§4 取数要按 WB_VIEWS 里写死的视图名读 workbench.${view}")
    if re.search(r"console\.(log|info|warn|error)\([^)]*rows", data):
        fail("§4 日志里不许打行内容")
    if not re.search(r"try\s*\{\s*client = postgres\(", data) or re.search(r"catch\s*\(", data[data.find("function db("):data.find("function day(")]):
        fail("§4 建 postgres 客户端要包在 try 里, catch 不绑定错误对象 (它带着整条连接串, 含密码)")
    wb_files = [p for p in WB_DIR.rglob("*") if p.suffix in (".ts", ".tsx")] + [DATA_TS, AUTH_TS]
    for p in wb_files:
        t = _ts_strings(p.read_text(encoding="utf-8"))  # 注释里提到这些名字不算
        rel = p.relative_to(ROOT)
        if re.search(r"""^\s*["']use client["']""", t, flags=re.M):
            fail(f"§4 {rel} 是客户端组件: 工作台的行数据不许进浏览器脚本")
        for bad in ("public-board-adjustments", "applyPublicBoardAdjustments", "AMPLIFY", "getDashboardData", "@/components/"):
            if bad in t:
                fail(f"§4 {rel} 引了 {bad}")
    if 'export const dynamic = "force-dynamic"' not in page or "index: false" not in page:
        fail("§4 页面要 force-dynamic、robots noindex")
    body = page[page.find("export default async function"):]
    order = [body.find(k) for k in ("verifySessionToken(", "isWorkbenchConfigured()", "verifyWorkbenchToken(", "getWorkbenchData(")]
    if min(order) < 0 or order != sorted(order):
        fail("§4 页面要先验团队会话、再看口令配没配、再验 owner 会话, 最后才取数")
    if "notFound()" not in body:
        fail("§4 没配 WORKBENCH_PASSWORD 时页面要 notFound()")
    if HIT_LINE not in page or "铺的评论" not in page:
        fail(f"§4 页头要写「{HIT_LINE}」, 并说里面有我们铺的评论")
    if '"wb:" + exp' not in auth or "WORKBENCH_PASSWORD" not in auth:
        fail("§4 owner cookie 签的消息要带 wb: 前缀, 钥匙里要有 WORKBENCH_PASSWORD")
    if not all(k in unlock for k in ("httpOnly: true", "secure: true", "verifySessionToken(", "isWorkbenchConfigured()")):
        fail("§4 收 owner 口令的路由要验团队会话、没配就 404、cookie httpOnly + secure")
    if "WB_COOKIE" not in logout:
        fail("§4 登出要一起清掉 owner cookie")
    if "verifyWorkbenchToken(" not in console or '"/console/workbench"' not in console:
        fail("§4 /console 首页的工作台入口要在 owner 会话有效时才显示")
    for p in DASH.rglob("*"):
        if p.suffix in (".ts", ".tsx", ".mjs", ".js") and "node_modules" not in p.parts and ".next" not in p.parts:
            if "NEXT_PUBLIC_" in p.read_text(encoding="utf-8", errors="ignore"):
                fail(f"§4 {p.relative_to(ROOT)} 里有 NEXT_PUBLIC_ (变量会进浏览器)")
    pkg = read(PKG)
    m = re.search(r'"postgres":\s*"([^"]+)"', pkg)
    if not m or not re.fullmatch(r"\d+\.\d+\.\d+", m.group(1)):
        fail("§4 postgres 依赖要钉死版本 (不带 ^ / ~)")


def sql_display_literals(sql: str) -> list[str]:
    """SQL 里会显示到页面上的字串: 去掉注释和 COMMENT ON ... IS '...' 之后, 带中文的单引号字串。"""
    code = strip_sql_comments(sql)
    code = re.sub(r"COMMENT ON .*?\bIS\s+(?:'(?:[^']|'')*'\s*)+;", "", code, flags=re.S)
    return [lit for lit in re.findall(r"'((?:[^']|'')*)'", code) if re.search(r"[\u4e00-\u9fff]", lit)]


def check_wording(sql: str) -> None:
    for p in sorted(WB_DIR.rglob("*.tsx")):
        t = _ts_strings(p.read_text(encoding="utf-8"))
        for s in ALLOWED_SENTENCES:
            t = t.replace(s, "")
        for w in BANNED_WORDS:
            if w in t:
                fail(f"§5 {p.relative_to(ROOT)} 里出现「{w}」(docs/35 第 2 节不能说)")
    lits = sql_display_literals(sql)
    if len(lits) < 30:
        fail(f"§5 SQL 里带中文的字串只取到 {len(lits)} 个, 取法坏了")
    for lit in lits:
        t = lit
        for s in ALLOWED_SENTENCES:
            t = t.replace(s, "")
        for w in BANNED_WORDS:
            if w in t:
                fail(f"§5 SQL 字串「{lit[:40]}」里出现「{w}」(会显示到页面上)")
        for pat in SQL_DISPLAY_BANNED:
            if re.search(pat, t):
                fail(f"§5 SQL 字串「{lit[:40]}」里有英文字段名或统计词 ({pat}), 页面上要写人话")


def check_wiring() -> None:
    ci = read(CI)
    sql_job = ci[ci.find("\n  sql:"):ci.find("\n  yaml:")]
    if sql_job.count("psql -v ON_ERROR_STOP=1 -q -f schemas/workbench_v1.sql") < 2:
        fail("§6 ci.yml 的 sql job 要把 workbench_v1.sql 跑两遍 (幂等)")
    if "scripts/check_workbench_pg.sql" not in sql_job:
        fail("§6 ci.yml 的 sql job 要跑 scripts/check_workbench_pg.sql")
    py_job = ci[ci.find("\n  python:"):ci.find("\n  sql:")]
    if "check_workbench.py" not in py_job:
        fail("§6 ci.yml 的 python job 要跑 check_workbench.py")
    if "workbench_role_password.py --selftest" not in py_job or not ROLE_PW.exists():
        fail("§6 ci.yml 的 python job 要跑 workbench_role_password.py --selftest")
    doc = read(DOC)
    if "scripts/workbench_role_password.py" not in doc or "log_statement" not in doc or "只用字母和数字" not in doc:
        fail("§6 docs/35 要让 owner 用 scripts/workbench_role_password.py 设密码、写明 log_statement 的原因、密码只用字母和数字")
    if "| `35-workbench` |" not in read(INDEX):
        fail("§6 docs/00-START-HERE.md 的索引里没有 docs/35")
    oi = read(OPEN_ITEMS)
    row = next((ln for ln in oi.splitlines() if ln.startswith("| W-63 |")), "")
    if "11-25 v0" not in row:
        fail("§6 OPEN-ITEMS 的 W-63 那一行要有 11-25 v0 的进度和 owner 要跑什么")
    if not PG_FIXTURE.exists():
        fail("§6 scripts/check_workbench_pg.sql 不在")


def main() -> int:
    sql = read(SQL)
    doc = read(DOC)
    check_constants(sql, doc)
    check_hints(sql, doc)
    check_grants(sql)
    check_dashboard(sql)
    check_wording(sql)
    check_wiring()
    if problems:
        print("check_workbench: 红")
        for p in problems:
            print("  ✗ " + p)
        return 1
    print(f"check_workbench: 过 (规则常量 {len(CONSTANTS)} 个和 docs/35 一致; 八种写法、三条提示; 权限写法; 九个视图; 看板两道闸和取数; "
          f"不能说的话, 含 SQL 里 {len(sql_display_literals(sql))} 个会显示的中文字串)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
