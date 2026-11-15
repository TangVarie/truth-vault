#!/usr/bin/env node
/**
 * 对外页面用词检查：公开首页 `/` 和对外看板 `/board` 上不许出现内部叫法
 * (规则写在 config/showcase.ts 开头「行话死」)。内部座舱 /console 不查，它保留内部叫法。
 *
 * 两层，都不联网、不连数据库：
 *  1. 源码层(总是跑)：从 app/layout.tsx、app/page.tsx、app/board/page.tsx 出发，沿 import 找到它们
 *     用到的 app/、components/、config/ 下的文件，只看「会被显示的字」—— 字符串、模板字符串、
 *     JSX 里的文字；注释、变量名、字段名不算。lib/ 是服务端取数代码(视图名、字段名只在服务器上)，
 *     不在这一层查，交给第 2 层按实际发出去的内容查。
 *  2. 成品层(有 .next 构建产物时跑；加 --rendered 则没有构建产物就算失败)：起一个本机临时服务，
 *     取 `/` 和 `/board` 实际发给浏览器的 HTML，以及这两页引用的全部脚本，逐个查。
 *     不配数据库时页面走空数据兜底，照样能查到所有写死的字和组件脚本。
 *
 * 用法：npm run check:public          (先 npm run build 才有成品层)
 *       node scripts/check-public-wording.mjs --rendered
 *       node scripts/check-public-wording.mjs --source-only   (只跑源码层；package.json 的 prebuild 用它，
 *         所以每次 npm run build(包括 Vercel 上)都会先查一遍，查到就不构建。这里不能跑成品层：
 *         构建前 .next 里是上一次的旧产物，查它会把刚改好的源码也拦住)
 *       npm run test:check              (这个检查自己的测试：scripts/check-public-wording.test.mjs)
 * 退出码：0 通过；1 查到内部叫法；2 检查自己没跑成。
 */
import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

// --root=<目录> 只给测试用：拿一个临时目录当看板根目录查
const rootArg = process.argv.find((a) => a.startsWith("--root="));
const ROOT = rootArg ? path.resolve(rootArg.slice("--root=".length)) : path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);

/** 不许出现在对外页面上的内部叫法(不分大小写)。加词只改这里。 */
const BANNED = [
  "ssll", "autowriter", "馆员", "essence", "通道", "sub_direction", "子方向",
  // 仓库名 / 系统代号(带空格的写法和中文名是这些名字实际当显示标签用的样子，见 config/flywheel.ts)
  // 注意：不要加 "jev" 这种三个字母的短词——成品层查的是整份 HTML 和压缩后的脚本，里面有每次构建随机生成的
  // 构建号和压缩后的变量名，三个字母碰巧撞上就会误报，构建时好时坏。完整的仓库名 jevforcoentent 已在表里。
  "truth_vault", "truth-vault", "truthvault", "truth vault", "sanshengliubu", "三生六部", "deskcore", "jevforcoentent", "linkcheck", "librarian",
  // 库表 / 视图名
  "v_dash_", "reference_samples", "lesson_cards", "draft_snapshots", "metric_snapshots", "audit_log",
];
const PUBLIC_ENTRIES = ["app/layout.tsx", "app/page.tsx", "app/board/page.tsx"];
const PUBLIC_ROUTES = ["/", "/board"];
const SOURCE_DIRS = ["app/", "components/", "config/"];

const hits = (text) => { const low = text.toLowerCase(); return BANNED.filter((w) => low.includes(w.toLowerCase())); };
const clip = (s) => s.replace(/\s+/g, " ").trim().slice(0, 60);

// ── 1. 源码层 ──
function resolveImport(fromFile, spec) {
  let base;
  if (spec.startsWith("@/")) base = path.join(ROOT, spec.slice(2));
  else if (spec.startsWith(".")) base = path.resolve(path.dirname(fromFile), spec);
  else return null; // 第三方包
  for (const cand of [base, `${base}.tsx`, `${base}.ts`, path.join(base, "index.tsx"), path.join(base, "index.ts")]) {
    if (existsSync(cand) && /\.tsx?$/.test(cand)) return cand;
  }
  return null;
}

function checkSource() {
  const ts = require("typescript");
  const problems = [];
  const seen = new Set();
  const queue = PUBLIC_ENTRIES.map((p) => path.join(ROOT, p));
  for (const entry of queue) if (!existsSync(entry)) throw new Error(`找不到公开页面入口 ${path.relative(ROOT, entry)}`);
  while (queue.length) {
    const file = queue.pop();
    if (seen.has(file)) continue;
    seen.add(file);
    const rel = path.relative(ROOT, file).split(path.sep).join("/");
    const sf = ts.createSourceFile(file, readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    const scan = SOURCE_DIRS.some((d) => rel.startsWith(d));
    const visit = (node) => {
      if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) {
        if (!(ts.isImportDeclaration(node) && node.importClause?.isTypeOnly)) {
          const target = resolveImport(file, node.moduleSpecifier.text);
          if (target) queue.push(target);
        }
        return; // import 路径本身不是显示文字
      }
      if (scan) {
        const shown = ts.isStringLiteralLike(node) || ts.isJsxText(node) || node.kind === ts.SyntaxKind.TemplateHead
          || node.kind === ts.SyntaxKind.TemplateMiddle || node.kind === ts.SyntaxKind.TemplateTail;
        if (shown) {
          const text = ts.isJsxText(node) ? node.getText(sf) : node.text;
          const bad = hits(text);
          if (bad.length) {
            const { line } = sf.getLineAndCharacterOfPosition(node.getStart(sf));
            problems.push(`${rel}:${line + 1} 出现 ${bad.join(" / ")} ← 「${clip(text)}」`);
          }
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(sf);
  }
  return { problems, files: [...seen].map((f) => path.relative(ROOT, f).split(path.sep).join("/")).sort() };
}

// ── 2. 成品层 ──
function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.once("error", reject);
    srv.listen(0, "127.0.0.1", () => { const { port } = srv.address(); srv.close(() => resolve(port)); });
  });
}

async function checkRendered() {
  const port = await freePort();
  const nextBin = require.resolve("next/dist/bin/next");
  // 故意把数据库地址清空：检查不连任何库，页面走空数据兜底
  const env = { ...process.env, PORT: String(port), SUPABASE_URL: "", SUPABASE_ANON_KEY: "", SUPABASE_SERVICE_ROLE_KEY: "", NEXT_TELEMETRY_DISABLED: "1" };
  const child = spawn(process.execPath, [nextBin, "start", "-H", "127.0.0.1", "-p", String(port)], { cwd: ROOT, env, stdio: ["ignore", "pipe", "pipe"] });
  let log = "";
  child.stdout.on("data", (b) => { log += b; });
  child.stderr.on("data", (b) => { log += b; });
  const base = `http://127.0.0.1:${port}`;
  const problems = [];
  let scripts = 0;
  try {
    let up = false;
    for (let i = 0; i < 100 && !up; i++) {
      if (child.exitCode !== null) throw new Error(`临时服务没起来：\n${log.slice(-800)}`);
      try { await fetch(`${base}/robots.txt`); up = true; } catch { await new Promise((r) => setTimeout(r, 200)); }
    }
    if (!up) throw new Error(`临时服务 20 秒内没起来：\n${log.slice(-800)}`);
    const seenJs = new Set();
    for (const route of PUBLIC_ROUTES) {
      const res = await fetch(base + route, { redirect: "manual" });
      if (res.status !== 200) throw new Error(`${route} 返回 ${res.status}，查不了`);
      const html = await res.text();
      for (const w of hits(html)) problems.push(`${route} 发出的 HTML 里出现 ${w}`);
      for (const m of html.matchAll(/\/_next\/static\/[^"'\\ )<>]+?\.js/g)) seenJs.add(m[0]);
    }
    for (const js of seenJs) {
      const res = await fetch(base + js);
      if (res.status !== 200) continue;
      scripts++;
      const body = await res.text();
      for (const w of hits(body)) {
        const at = body.toLowerCase().indexOf(w.toLowerCase());
        problems.push(`公开页引用的脚本 ${js} 里出现 ${w} ← 「${clip(body.slice(Math.max(0, at - 20), at + 40))}」`);
      }
    }
  } finally {
    child.kill("SIGTERM");
  }
  return { problems, scripts };
}

// ── 主流程 ──
const requireRendered = process.argv.includes("--rendered");
const sourceOnly = process.argv.includes("--source-only");
if (requireRendered && sourceOnly) { console.error("--rendered 和 --source-only 不能一起用"); process.exit(2); }
let failed = false;
try {
  const src = checkSource();
  if (src.problems.length) { failed = true; console.error(`源码层：${src.problems.length} 处内部叫法`); for (const p of src.problems) console.error("  " + p); }
  else console.log(`源码层：通过（查了 ${src.files.length} 个文件的显示文字）`);

  if (sourceOnly) {
    console.log("成品层：不跑（--source-only）");
  } else if (existsSync(path.join(ROOT, ".next", "BUILD_ID"))) {
    const out = await checkRendered();
    if (out.problems.length) { failed = true; console.error(`成品层：${out.problems.length} 处内部叫法`); for (const p of out.problems) console.error("  " + p); }
    else console.log(`成品层：通过（${PUBLIC_ROUTES.join("、")} 的 HTML + ${out.scripts} 个脚本）`);
  } else if (requireRendered) {
    console.error("成品层：没有 .next 构建产物，先跑 npm run build");
    process.exit(2);
  } else {
    console.log("成品层：跳过（没有 .next 构建产物；先 npm run build 再跑就会查）");
  }
} catch (e) {
  console.error(`检查没跑成：${e?.message ?? e}`);
  process.exit(2);
}
process.exit(failed ? 1 : 0);
