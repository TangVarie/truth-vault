"""
check_system_map.py
═══════════════════════════════════════════════════════════════════════════

三件事，都是【止血】性质的，不是功能：只读，不碰库，不联网。

  G1  数据流向图里点名的东西必须还在盘上(docs/00-START-HERE.md §3)
  G2  ci.yml 里的内联 heredoc 块数只许降不许升(棘轮)
  G3  每盏打哨兵行的夜跑灯必须在登记册里(docs/29-lights-registry.md)

⚠️ **这三条各自挡得住什么、挡不住什么，写在下面每一节里。一个说不清自己边界的
守卫，用的人会高估它。**

2026-09-21 起因(D-075)：owner 说"越来越接近屎山"。量下来不是屎山 —— 边界干净、
注释异常好、没有改一处炸三处的耦合。真正的病是**地图缺失**：
"哪条路写哪张表"没有任何单一权威来源，于是每次动手都得重新考古(那天一个上午
去生产库考古了三次)。这个脚本守的就是那张新画的地图。

用法:
    python check_system_map.py            # 三条都跑
    python check_system_map.py --only g1  # 只跑一条(写反证时用)

退出码: 0 = 全过; 1 = 至少一条不过。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAP_DOC = ROOT / "docs" / "00-START-HERE.md"
LIGHTS_DOC = ROOT / "docs" / "29-lights-registry.md"
CI = ROOT / ".github" / "workflows" / "ci.yml"

# G2 的棘轮基线。2026-09-21 实测 ci.yml 里 79 个内联 heredoc 块。
# ⚠️ 这个数【只许往下调】。要加新守卫就写成 scripts/ 里的脚本, ci.yml 里只留调用
#    —— 那样不增加 heredoc 块数, 这条闸不会挡你。
CI_HEREDOC_CAP = 79
HEREDOC = "<<'PY'"


# ══════════════════════════════════════════════════════════════════════
# 盘上真值
# ══════════════════════════════════════════════════════════════════════

def _tv_tables_and_views() -> set[str]:
    """从 schemas/*.sql 里解析出 truth_vault 的表和视图名。

    ⚠️ 用【建表语句】而不是连库: CI 的 python job 没有库, 而且这条守卫要在最便宜
    的环境里就能跑。代价是"迁移写了但没 apply 到生产"它看不出来 —— 那是
    assert_db_schema_ready() 的活, 不是这里的。
    """
    out: set[str] = set()
    pat = re.compile(
        r'create\s+(?:table|(?:or\s+replace\s+)?view)\s+'
        r'(?:if\s+not\s+exists\s+)?(?:truth_vault\.)?"?([a-z_][a-z0-9_]*)"?',
        re.I)
    for f in sorted((ROOT / "schemas").glob("*.sql")):
        out |= set(pat.findall(f.read_text(encoding="utf-8", errors="ignore")))
    return out


def _scripts() -> set[str]:
    return {p.name for p in (ROOT / "scripts").glob("*.py")}


def _workflows() -> set[str]:
    return {p.name for p in (ROOT / ".github" / "workflows").glob("*.yml")}


# ══════════════════════════════════════════════════════════════════════
# G1 · 图里点名的东西必须还在
# ══════════════════════════════════════════════════════════════════════
#
# 挡得住: 表/视图改名或删掉、脚本删掉或改名、workflow 改名 —— 而图没跟着改。
#
# 挡【不】住: 语义漂移。图说"A 喂 B"而代码改成了"A 喂 C", 两个名字都还在盘上,
#   这条一声不吭。它保证的只是【图里没有已经不存在的东西】, 不是【图是对的】。
#
# ⚠️ 为什么只扫带 <!-- map-guard --> 标记的 mermaid 块, 不扫全文:
#   2026-09-21 先写了个扫全文猜标识符的版本, 当场自证会误报 ——
#     · `sync_feishu_notes_to_truth_vault.py` 里的 `truth_vault.py` 被当成表名;
#     · 文档里提到 autowriter 仓的 `core.py` / `app.py`, 本仓盘上当然没有。
#   一个会误报的守卫比没有守卫更糟(它会被人关掉, 然后真问题也没人管了)。
#   所以改成【只认显式前缀】: 图里写 `tv:notes` 才查, 写散文不查。

TOKEN = re.compile(r'\b(tv|script|wf):([A-Za-z_][A-Za-z0-9_.-]*)')


def _guarded_blocks(text: str) -> list[str]:
    """带 <!-- map-guard --> 标记的 mermaid 代码块。"""
    out = []
    for m in re.finditer(r'<!--\s*map-guard\s*-->\s*```mermaid\n(.*?)```',
                         text, re.S):
        out.append(m.group(1))
    return out


def check_map(verbose: bool = True) -> list[str]:
    problems: list[str] = []
    if not MAP_DOC.exists():
        return [f"{MAP_DOC.relative_to(ROOT)} 不在了 —— 数据流向图是这仓唯一的活地图"]

    text = MAP_DOC.read_text(encoding="utf-8")
    blocks = _guarded_blocks(text)
    if not blocks:
        # 图被删了 / 标记被拿掉了 = 守卫变成空转。这本身就是要报的事。
        return [f"{MAP_DOC.relative_to(ROOT)} 里没有带 <!-- map-guard --> 的 mermaid 块 "
                "—— 图没了或者标记被拿掉了, 这条守卫正在空转"]

    tables, scripts, wfs = _tv_tables_and_views(), _scripts(), _workflows()
    seen = 0
    for blk in blocks:
        for kind, name in TOKEN.findall(blk):
            seen += 1
            if kind == "tv" and name not in tables:
                problems.append(
                    f"图里写着 tv:{name}, 但 schemas/*.sql 里没有这张表/视图")
            elif kind == "script" and name not in scripts:
                problems.append(
                    f"图里写着 script:{name}, 但 scripts/ 下没有这个文件")
            elif kind == "wf" and name not in wfs:
                problems.append(
                    f"图里写着 wf:{name}, 但 .github/workflows/ 下没有这个文件")
    if verbose:
        print(f"  G1 图里 {len(blocks)} 个受守块 / 点名 {seen} 处 "
              f"(盘上: {len(tables)} 表视图 · {len(scripts)} 脚本 · {len(wfs)} workflow)")
    return problems


# ══════════════════════════════════════════════════════════════════════
# G2 · ci.yml 的内联 heredoc 棘轮
# ══════════════════════════════════════════════════════════════════════
#
# 为什么钉【块数】而不是行数: 病灶是"守卫逻辑内联在 YAML 里", 不是"文件长"。
#   钉行数会把正常的改注释、加一行调用都挡掉 —— 那种闸会被人拆掉(D-053)。
#   钉块数则精确对应那条规矩: 新守卫写成 scripts/ 里的脚本, ci.yml 只留调用。
#   照规矩做, 块数不变, 这条闸根本不会挡你。
#
# 为什么值得钉: ci.yml 7,713 行 / 79 个内联块, GitHub 【整份解析】。
#   本仓已经发生过一次: 一个 ${{ }} 占位符写错 → 整份被拒 → 0 个 job / 0 秒,
#   而本地 yaml.safe_load 看不出来。守卫机器自己是最大的那个单点。
#
# 挡【不】住: 别的 workflow 里新增内联块, 以及把一个 200 行的块塞成 400 行。
#   它只管 ci.yml 的块数不再增长。

def check_ci_ratchet(verbose: bool = True) -> list[str]:
    if not CI.exists():
        return [".github/workflows/ci.yml 不在了"]
    n = CI.read_text(encoding="utf-8").count(HEREDOC)
    if verbose:
        print(f"  G2 ci.yml 内联 heredoc {n} 块 (棘轮上限 {CI_HEREDOC_CAP})")
    if n > CI_HEREDOC_CAP:
        return [
            f"ci.yml 的内联 heredoc 从 {CI_HEREDOC_CAP} 涨到了 {n} 块。"
            "新守卫请写成 scripts/ 里的脚本, ci.yml 里只留一行调用 —— "
            "那样块数不变, 这条闸不会挡你。"
            "真要内联(比如它就是在测 YAML 本身), 把本文件的 CI_HEREDOC_CAP 调上去, "
            "并在 DECISIONS.md 里说清为什么这一块必须内联。"]
    if n < CI_HEREDOC_CAP:
        # 有人把内联块抽出去了 —— 好事, 但棘轮要跟着收紧, 否则白抽。
        return [
            f"ci.yml 的内联 heredoc 降到了 {n} 块(棘轮还停在 {CI_HEREDOC_CAP})。"
            f"把本文件的 CI_HEREDOC_CAP 改成 {n}, 把这次的成果锁住 —— "
            "不锁的话下一个人能不声不响地加回来。"]
    return []


# ══════════════════════════════════════════════════════════════════════
# G3 · 每盏灯必须在登记册里
# ══════════════════════════════════════════════════════════════════════
#
# 规矩(docs/29): 加灯之前先回答"谁看、多久看、红了谁负责"。答不上来就别加。
# 这条把那个规矩变成可执行的: 打了哨兵行 = 是一盏夜跑灯 = 必须在册。
#
# 挡【不】住: 登记册里那三个答案是不是【真的】。写"owner 每周看一次"而没人真看,
#   这条照样绿。它挡的是"悄悄加一盏没人认领的灯", 不是"认领了但没履行"。

SENTINEL = re.compile(r'\b([A-Z][A-Z0-9_]*_CHECK_DONE)\s+rc=')


def check_lights(verbose: bool = True) -> list[str]:
    if not LIGHTS_DOC.exists():
        return [f"{LIGHTS_DOC.relative_to(ROOT)} 不在了 —— 灯登记册是 D-075 那条规矩的载体"]
    registry = LIGHTS_DOC.read_text(encoding="utf-8")
    if "<!-- lights-registry -->" not in registry:
        return [f"{LIGHTS_DOC.relative_to(ROOT)} 里没有 <!-- lights-registry --> 标记 "
                "—— 登记表被删了或者改了形状, 这条守卫正在空转"]

    problems: list[str] = []
    found = 0
    for f in sorted((ROOT / "scripts").glob("*.py")):
        if f.name == Path(__file__).name:
            continue
        for name in sorted(set(SENTINEL.findall(f.read_text(encoding="utf-8", errors="ignore")))):
            found += 1
            if name not in registry:
                problems.append(
                    f"{f.name} 打了哨兵行 {name}(= 一盏夜跑灯), 但它不在 "
                    f"docs/29-lights-registry.md 里。"
                    "先回答『谁看 · 多久看一次 · 红了谁负责』, 答案写进登记表; "
                    "答不上来就别加这盏灯。")
            elif f.name not in registry:
                problems.append(
                    f"{name} 在登记册里, 但脚本名 {f.name} 不在 —— "
                    "多半是脚本改名了而登记册没跟上。")
    if verbose:
        print(f"  G3 扫到 {found} 盏打哨兵行的灯")
    return problems


# ══════════════════════════════════════════════════════════════════════

CHECKS = {"g1": ("数据流向图", check_map),
          "g2": ("ci.yml 内联棘轮", check_ci_ratchet),
          "g3": ("灯登记册", check_lights)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=sorted(CHECKS), default=None,
                    help="只跑一条(写反证时用)")
    args = ap.parse_args()

    keys = [args.only] if args.only else list(CHECKS)
    all_problems: list[tuple[str, str]] = []
    for k in keys:
        label, fn = CHECKS[k]
        for p in fn():
            all_problems.append((k.upper(), p))

    if all_problems:
        print()
        for k, p in all_problems:
            print(f"❌ {k}: {p}")
        print(f"\n{len(all_problems)} 条不过。")
        return 1
    print(f"\n✅ {len(keys)} 条全过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
