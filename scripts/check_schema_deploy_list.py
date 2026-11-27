#!/usr/bin/env python3
"""CI 守卫: schemas/ 下每一份 .sql 都登记在部署清单里, 并且在 ci.yml 的 sql job 里真跑过 (S-09 / 审计 C-16)。

原来是 ci.yml 里的一段内联检查 (codex review on #130), 只管 notes_v1_*.sql。
2026-11-25 挪到这里 (D-075: 守卫放 scripts/, ci.yml 只留一行调用), 并放宽到 schemas/*.sql:
看板视图 dashboard_views_* 和权限补丁 security_* 以前不在任何清单里, 新装的库会漏跑。

清单在 scripts/README.md「第一次部署」:
  Step 0  = 同步之前必须跑的迁移 (notes_v1_*; 漏了 preflight 会拒绝同步)
  Step 0b = 看板视图、工作台和安全补丁 (不是同步的前置), 按 ci.yml sql job 的先后顺序列
不在两张清单里的, 写进下面的 NOT_LISTED, 并写明理由。

  §1 每份 schemas/*.sql 只在一处: Step 0、Step 0b、NOT_LISTED 三选一
  §2 清单里没有盘上不存在的文件; NOT_LISTED 里没有已经不存在的文件
  §3 每份 schemas/*.sql 在 ci.yml sql job 里至少被一条 psql 命令用 `-f schemas/<文件>` 跑过, 否则写进 NOT_IN_CI 并写明理由。
     只认真的 psql 命令: shell 注释里的、echo 之类别的命令的参数、heredoc 正文里的都不算。
  §4 Step 0b 的先后顺序 = ci.yml sql job 第一次跑它们的先后顺序

挡不住的:
  · 生产上到底跑没跑。这里只管「清单全、CI 跑过」; 生产以 verify_supabase_state.sql 的读数为准 (#105–#107 管 Step 0b)。
  · Step 0 内部的先后顺序 (CI 的顺序和 Step 0 不完全一样, 依赖写在每一行的说明里)。
  · autowriter-migrations/ 和 sanshengliubu-patches/ (不在 schemas/ 下)。

用法:
    python check_schema_deploy_list.py             # 查本仓, 再跑一遍反证 (CI 就这一行)
    python check_schema_deploy_list.py --selftest  # 只跑反证: 改坏清单之后必须红
退出码: 0 = 全过; 1 = 不过。
"""
from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

# 不在 Step 0 / Step 0b 里的文件, 必须显式登记并写明理由 —— 不许静默跳过。
NOT_LISTED = {
    "notes_v1_2_cross_schema_views.sql": "D-029 (notes_v1_2.sql 末尾部署步骤第 4 步): 要等 ssll / autowriter 两个 schema 就绪, 不是 sync 的前置",
}
# 不在 ci.yml sql job 里跑的文件, 同样要写明理由。今天没有。
NOT_IN_CI: dict[str, str] = {}

STEP0 = re.compile(r"# Step 0 ·.*?(?=\n# Step 0b)", re.S)
STEP0B = re.compile(r"# Step 0b ·.*?(?=\n# Step 1)", re.S)
LISTED = re.compile(r"schemas/([A-Za-z0-9_]+\.sql)")
SCHEMA_FILE = re.compile(r"schemas/([A-Za-z0-9_]+\.sql)")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
CMD_SEP = {";", ";;", "&&", "||", "|", "&", "(", ")", "|&"}
SHELL_KW = {"if", "then", "elif", "else", "fi", "do", "done", "while", "until", "!", "{", "}", "time"}


def sql_job_text(ci_text: str) -> str:
    wf = yaml.safe_load(ci_text)
    steps = (wf.get("jobs") or {}).get("sql", {}).get("steps") or []
    return "\n".join(str(s.get("run") or "") for s in steps)


def _psql_files(line: str) -> list[str]:
    """一行 shell 里, 每条 psql 命令用 -f / --file 跑的 schemas/*.sql。注释、别的命令的参数不算。"""
    lex = shlex.shlex(line, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = "#"
    try:
        toks = list(lex)
    except ValueError:          # 引号没配对 (跨行的字符串): 这一行不认, 宁可让 §3 红
        return []
    out: list[str] = []
    start, is_psql, prev = True, False, ""
    for t in toks:
        if t in CMD_SEP:
            start, is_psql, prev = True, False, ""
            continue
        if start:
            if t in SHELL_KW or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", t):
                continue        # if / then / ! / VAR=x 这些之后才是命令名
            start, is_psql, prev = False, t.rsplit("/", 1)[-1] == "psql", t
            continue
        if is_psql:
            arg = t if prev == "-f" else t[2:] if t.startswith("-f") else t[7:] if t.startswith("--file=") else ""
            m = SCHEMA_FILE.fullmatch(arg)
            if m:
                out.append(m.group(1))
        prev = t
    return out


def applied_files(run_text: str) -> list[str]:
    """sql job 里真被 psql -f 跑过的 schemas/*.sql, 按出现先后 (可重复)。heredoc 正文整段跳过; 行尾 \\ 续行先拼起来。"""
    out: list[str] = []
    end_tag, buf = None, ""
    for raw in run_text.splitlines():
        if end_tag is not None:
            if raw.strip() == end_tag:
                end_tag = None
            continue
        line = buf + raw
        if line.rstrip().endswith("\\"):
            buf = line.rstrip()[:-1] + " "
            continue
        buf = ""
        m = HEREDOC.search(line)
        if m:
            end_tag = m.group(2)
        out += _psql_files(line)
    return out


def check(files: list[str], readme: str, ci_text: str,
          not_listed: dict[str, str], not_in_ci: dict[str, str]) -> list[str]:
    fails: list[str] = []
    m0, m0b = STEP0.search(readme), STEP0B.search(readme)
    if not m0 or not m0b:
        return ["scripts/README.md 里找不到「# Step 0 ·」…「# Step 0b ·」…「# Step 1」这几段, 清单格式变了?"]
    step0 = LISTED.findall(m0.group(0))
    step0b = LISTED.findall(m0b.group(0))
    on_disk = set(files)

    # §1 每份只在一处
    for f in files:
        where = [name for name, ok in (("Step 0", f in step0), ("Step 0b", f in step0b),
                                       ("NOT_LISTED", f in not_listed)) if ok]
        if not where:
            fails.append(f"§1 {f} 不在 Step 0 / Step 0b 里, 也没登记进 NOT_LISTED")
        elif len(where) > 1:
            fails.append(f"§1 {f} 同时在 {' 和 '.join(where)} 里, 只能在一处")
    for name, seq in (("Step 0", step0), ("Step 0b", step0b)):
        dup = sorted({f for f in seq if seq.count(f) > 1})
        if dup:
            fails.append(f"§1 {name} 里重复列了 {dup}")

    # §2 幽灵条目
    ghosts = sorted((set(step0) | set(step0b)) - on_disk)
    if ghosts:
        fails.append(f"§2 清单里列了盘上不存在的文件: {ghosts}")
    stale = sorted(f for f in list(not_listed) + list(not_in_ci) if f not in on_disk)
    if stale:
        fails.append(f"§2 NOT_LISTED / NOT_IN_CI 里登记的文件已经不在了: {stale}")

    # §3 CI 真跑过
    sql = sql_job_text(ci_text)
    applied = applied_files(sql)
    for f in files:
        if f not in applied and f not in not_in_ci:
            fails.append(f"§3 {f} 没在 ci.yml 的 sql job 里跑过 (要有一行 `psql ... -f schemas/{f}`, 或者写进 NOT_IN_CI)")
        if f in applied and f in not_in_ci:
            fails.append(f"§3 {f} 登记成不在 CI 跑, 可 sql job 里跑了; 把 NOT_IN_CI 那一条删掉")

    # §4 Step 0b 的顺序 = CI 第一次跑的顺序
    first = {}
    for i, f in enumerate(applied):
        first.setdefault(f, i)
    in_ci = [f for f in step0b if f in first]
    if in_ci != sorted(in_ci, key=first.__getitem__):
        fails.append("§4 Step 0b 的先后顺序和 ci.yml sql job 不一样: 清单 "
                     f"{in_ci} / CI {sorted(in_ci, key=first.__getitem__)}")
    return fails


def _real() -> tuple[list[str], str, str]:
    files = sorted(p.name for p in (ROOT / "schemas").glob("*.sql"))
    readme = (ROOT / "scripts" / "README.md").read_text(encoding="utf-8")
    ci_text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    return files, readme, ci_text


def selftest() -> int:
    files, readme, ci_text = _real()
    base = check(files, readme, ci_text, NOT_LISTED, NOT_IN_CI)
    if base:
        print("❌ selftest: 本仓本身就不过, 先修本仓:\n  " + "\n  ".join(base))
        return 1
    m0b = STEP0B.search(readme).group(0)
    dv1 = "#   - schemas/dashboard_views_v1.sql"
    dv1_line = next(ln for ln in m0b.splitlines() if ln.startswith(dv1))
    v12 = "notes_v1_12_comment_tier.sql"
    cases = {
        "Step 0b 删掉 dashboard_views_v1 那一行": (
            files, readme.replace(dv1_line + "\n", "", 1), ci_text, NOT_LISTED, NOT_IN_CI, "§1"),
        "清单里列一份不存在的文件": (
            files, readme.replace(dv1_line, dv1_line + "\n#   - schemas/dashboard_views_v9_ghost.sql", 1),
            ci_text, NOT_LISTED, NOT_IN_CI, "§2"),
        "已列在 Step 0 的文件又登记进 NOT_LISTED": (
            files, readme, ci_text, {**NOT_LISTED, v12: "反证"}, NOT_IN_CI, "§1"),
        "schemas/ 下多了一份 sql job 没跑的文件": (
            files + ["security_ci_never_applied.sql"],
            readme.replace(dv1_line, dv1_line + "\n#   - schemas/security_ci_never_applied.sql", 1),
            ci_text, NOT_LISTED, NOT_IN_CI, "§3"),
        "Step 0b 里两行调了顺序": (
            files, _swap_first_two(readme, m0b), ci_text, NOT_LISTED, NOT_IN_CI, "§4"),
    }
    # 新文件登记在 Step 0b 末尾, 往 sql job 最后一条 psql -f 后面塞几行: 只有真的 psql 命令才算跑过
    new = "security_ci_never_applied.sql"
    files_n, readme_n = files + [new], _append_step0b(readme, m0b, new)
    inject = {
        "正控: sql job 里真有一条 psql -f 新文件": ([f"psql -v ON_ERROR_STOP=1 -q -f schemas/{new}"], None),
        "-f schemas/新文件 只写在 shell 注释里": ([f"# psql -v ON_ERROR_STOP=1 -f schemas/{new}"], "§3"),
        "-f schemas/新文件 是 echo 的参数 (含行尾注释)": (
            [f"echo skip # -f schemas/{new}", f"echo psql -f schemas/{new}"], "§3"),
        "-f schemas/新文件 在 heredoc 正文里": (["python3 - <<'PY'", f"print('psql -f schemas/{new}')", "PY"], "§3"),
    }
    for name, (lines, sec) in inject.items():
        cases[name] = (files_n, readme_n, _inject_sql_job(ci_text, lines), NOT_LISTED, NOT_IN_CI, sec)
    bad = 0
    for name, (f, r, c, nl, nc, sec) in cases.items():
        got = check(f, r, c, nl, nc)
        if sec is None:
            if got:
                print(f"  ❌ 正控不该红: {name} (实际 {got})")
                bad += 1
            else:
                print(f"  ✓ 正控是绿的: {name}")
        elif not any(x.startswith(sec) for x in got):
            print(f"  ❌ 反证没红: {name} (期望 {sec}, 实际 {got})")
            bad += 1
        else:
            print(f"  ✓ 反证红了: {name} ({sec})")
    if bad:
        return 1
    print(f"✅ schema 部署清单 selftest: {len(cases) - 1} 条反证都红了, 1 条正控是绿的")
    return 0


def _append_step0b(readme: str, m0b: str, name: str) -> str:
    last = [ln for ln in m0b.splitlines() if LISTED.search(ln) and ln.startswith("#   - ")][-1]
    return readme.replace(m0b, m0b.replace(last, last + f"\n#   - schemas/{name}", 1), 1)


def _inject_sql_job(ci_text: str, lines: list[str]) -> str:
    """在 sql job 最后一条写在 `run: |` 块里的 `psql … -f schemas/…` 那一行后面, 用同样的缩进插几行。
    单行的 `run: psql …` 跳过: 插在它后面的行缩进会带上 `run: `, 成了同一步里第二个 run 键 (批 3 整合时撞到)。"""
    sql = sql_job_text(ci_text)
    for last in reversed([ln.strip() for ln in sql.splitlines() if _psql_files(ln)]):
        pos = ci_text.rfind(last)
        indent = ci_text[ci_text.rfind("\n", 0, pos) + 1:pos]
        if not indent.strip():
            break
    else:
        raise SystemExit("selftest: sql job 里没有一条写在 run: | 块里的 psql -f schemas/…, 插不进反证")
    end = ci_text.find("\n", pos)
    return ci_text[:end] + "".join(f"\n{indent}{x}" for x in lines) + ci_text[end:]


def _swap_first_two(readme: str, m0b: str) -> str:
    lines = m0b.splitlines()
    idx = [i for i, ln in enumerate(lines) if LISTED.search(ln) and ln.startswith("#   - ")][:2]
    lines[idx[0]], lines[idx[1]] = lines[idx[1]], lines[idx[0]]
    return readme.replace(m0b, "\n".join(lines), 1)


def main() -> int:
    if "--selftest" in sys.argv[1:]:
        return selftest()
    files, readme, ci_text = _real()
    fails = check(files, readme, ci_text, NOT_LISTED, NOT_IN_CI)
    for f in fails:
        print("  ❌", f)
    if fails:
        print(f"❌ schema 部署清单: {len(fails)} 条不过 (scripts/README.md Step 0 / Step 0b, 或 ci.yml sql job)")
        return 1
    for f, why in NOT_LISTED.items():
        print(f"  {f}: 不在 Step 0 / 0b (已登记: {why})")
    m0b = STEP0B.search(readme).group(0)
    print(f"  ✓ schemas/ 下 {len(files)} 份 .sql 都已登记 (Step 0b {len(LISTED.findall(m0b))} 份, 顺序同 CI), "
          "且都在 ci.yml sql job 里跑过")
    return selftest()   # 反证每次都跑 (CI 只调一行)


if __name__ == "__main__":
    sys.exit(main())
