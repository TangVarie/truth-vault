/**
 * 对外页面用词检查(check-public-wording.mjs)自己的测试。跑法：npm run test:check
 * 每个用例在系统临时目录里搭一个最小的假看板，让检查脚本拿它当根目录(--root=)，看退出码和输出。
 * 不联网、不连库、不需要构建产物。
 */
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SCRIPT = path.join(HERE, "check-public-wording.mjs");

/** files: { "相对路径": "内容" }；layout / 首页 / board 三个入口没给就补一个干净的。 */
function run(files, args = ["--source-only"]) {
  const root = mkdtempSync(path.join(os.tmpdir(), "public-wording-"));
  try {
    const all = {
      "app/layout.tsx": `export default function L({ children }: { children: unknown }) { return children; }\n`,
      "app/page.tsx": `export default function P() { return <main>内容资产</main>; }\n`,
      "app/board/page.tsx": `export default function B() { return <main>看板</main>; }\n`,
      ...files,
    };
    for (const [rel, body] of Object.entries(all)) {
      if (body === undefined) continue;
      const abs = path.join(root, rel);
      mkdirSync(path.dirname(abs), { recursive: true });
      writeFileSync(abs, body);
    }
    const r = spawnSync(process.execPath, [SCRIPT, `--root=${root}`, ...args], { encoding: "utf8" });
    return { code: r.status, out: r.stdout + r.stderr };
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

test("干净的公开页通过", () => {
  const r = run({});
  assert.equal(r.code, 0, r.out);
  assert.match(r.out, /源码层：通过/);
});

test("--source-only 不跑成品层(哪怕有构建产物)", () => {
  const r = run({ ".next/BUILD_ID": "stale" });
  assert.equal(r.code, 0, r.out);
  assert.match(r.out, /成品层：不跑/);
});

for (const [name, word] of [
  ["带空格的仓库名", "Truth Vault"],
  ["中文系统名", "三生六部"],
  ["连字符仓库名", "truth-vault"],
  ["内部代号", "SSLL"],
  ["内部角色名", "馆员"],
  ["库表名", "lesson_cards"],
]) {
  test(`公开页文字里有${name}「${word}」→ 失败`, () => {
    const r = run({ "app/board/page.tsx": `export default function B() { return <main>来自 ${word} 的数据</main>; }\n` });
    assert.equal(r.code, 1, r.out);
    assert.ok(r.out.includes("app/board/page.tsx:1"), r.out);
  });
}

test("公开页 import 进来的配置文件里的显示标签也查(config/flywheel.ts 那种写法)", () => {
  const r = run({
    "config/nodes.ts": `export const NODES = [{ id: "a", label: "Truth Vault" }, { id: "b", label: "三生六部" }];\n`,
    "app/board/page.tsx": `import { NODES } from "@/config/nodes";\nexport default function B() { return <main>{NODES[0].label}</main>; }\n`,
  });
  assert.equal(r.code, 1, r.out);
  assert.ok(r.out.includes("config/nodes.ts:1"), r.out);
  assert.ok(r.out.includes("truth vault") && r.out.includes("三生六部"), r.out);
});

test("没被公开页用到的文件、注释、内部页不算", () => {
  const r = run({
    "config/unused.ts": `export const X = "Truth Vault";\n`,
    "app/console/page.tsx": `export default function C() { return <main>馆员 ssll</main>; }\n`,
    "app/page.tsx": `// 三生六部 只是注释\nexport default function P() { return <main>内容资产</main>; }\n`,
  });
  assert.equal(r.code, 0, r.out);
});

test("入口文件缺失 → 退出码 2(检查没跑成，不是通过)", () => {
  const r = run({ "app/board/page.tsx": undefined });
  assert.equal(r.code, 2, r.out);
});

test("--rendered 和 --source-only 一起用 → 退出码 2", () => {
  const r = run({}, ["--rendered", "--source-only"]);
  assert.equal(r.code, 2, r.out);
});

test("package.json 的 prebuild 挂着源码层检查(每次构建都跑)", () => {
  const pkg = JSON.parse(readFileSync(path.join(HERE, "..", "package.json"), "utf8"));
  assert.equal(pkg.scripts.prebuild, "node scripts/check-public-wording.mjs --source-only");
  assert.equal(pkg.scripts.build, "next build");
});
