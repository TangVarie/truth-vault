"""
check_system_map.py
═══════════════════════════════════════════════════════════════════════════

三件事，都是【止血】性质的，不是功能：只读，不碰库，不联网。

  G1  数据流向图里点名的东西必须还在盘上(docs/00-START-HERE.md §3)
  G2  ci.yml 里的内联 heredoc 块数只许降不许升(棘轮)
  G3  每盏打哨兵行的夜跑灯必须在登记册里(docs/29-lights-registry.md)
  G4  features-sync 的每请求篇数与它注释里那句实测记录必须对得上

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

import yaml

ROOT = Path(__file__).resolve().parent.parent
MAP_DOC = ROOT / "docs" / "00-START-HERE.md"
LIGHTS_DOC = ROOT / "docs" / "29-lights-registry.md"
CI = ROOT / ".github" / "workflows" / "ci.yml"
FEATURES_WF = ROOT / ".github" / "workflows" / "features-sync.yml"

# G2 的棘轮基线。2026-09-21 实测 ci.yml 里 79 个内联 heredoc 块。
# ⚠️ 这个数【只许往下调】。要加新守卫就写成 scripts/ 里的脚本, ci.yml 里只留调用
#    —— 那样不增加 heredoc 块数, 这条闸不会挡你。
CI_HEREDOC_CAP = 78
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

# ══════════════════════════════════════════════════════════════════════
# G4 · features-sync 的批大小必须和它注释里那句实测记录一致
# ══════════════════════════════════════════════════════════════════════
#
# 2026-09-21 run #2 的教训: 那一步的注释写着"6 篇 ≈ 36-48 次调用 < Railway 边缘
# 5min"。这句话曾经是对的, 后来语料变长、每批涨到 4m43s-5m02s, 第四批撞破 5 分钟
# 回 502; 而 502 只切断边缘连接, worker 还在后台握着 ingest 锁 —— 后面 8 个项目
# 全部 409。那一轮跑了 20 分钟只成 24 篇, job 却报 success(409/502 都算 transient)。
#
# 也就是说: **一句过期的安全假设, 让这一步假绿了整整一轮**。D-073 那次 timeout
# 裸奔几个月, 起因是同一种东西 —— 注释里的数字和代码里的数字漂开了。
#
# 这条钉的就是那个漂开: 注释里的"N 篇 ≈ ..."必须等于 FEAT_REQ_MAX=N。
#
# 挡【不】住: 注释里那句话本身对不对。3 篇哪天也变慢到破 5 分钟, 这条照样绿 ——
#   它保证的是"代码和注释说的是同一个数", 不是"这个数是安全的"。真安全边界只有
#   实测能给, 所以注释里要求写的是【实测记录】而不是估算。

REQ_MAX = re.compile(r'^\s*FEAT_REQ_MAX=(\d+)', re.M)
REQ_DOC = re.compile(r'【每请求篇数 = (\d+)】')


def check_features_batch(verbose: bool = True) -> list[str]:
    if not FEATURES_WF.exists():
        return ["features-sync.yml 不在了"]
    t = FEATURES_WF.read_text(encoding="utf-8")
    code = REQ_MAX.findall(t)
    doc = REQ_DOC.findall(t)
    if len(code) != 1:
        return [f"features-sync.yml 里 FEAT_REQ_MAX 出现 {len(code)} 次(应为 1) "
                "—— 这条守卫认不出该钉哪个"]
    if len(doc) != 1:
        return ["features-sync.yml 的注释里找不到「【每请求篇数 = N】」那句实测记录 "
                "(或出现了多次)。那句话是这条守卫的另一半, 删了它这条就空转了 —— "
                "而上一次假绿的起因正是注释与代码漂开。"]
    if verbose:
        print(f"  G4 features-sync 每请求 {code[0]} 篇 (注释记的 {doc[0]} 篇)")
    if code[0] != doc[0]:
        return [f"features-sync.yml: FEAT_REQ_MAX={code[0]}, 但注释里那句实测记录写的是 "
                f"{doc[0]} 篇。改了批大小就要把实测记录一起改 —— "
                "一句过期的安全假设让这一步假绿过整整一轮(2026-09-21 run #2)。"]
    return []


# ══════════════════════════════════════════════════════════════════════

# ── G5: 投流/维护三列永不映指标列 (A13, 2026-09-22)────────────────────────────
# 运营 2026-09-22 确认:「维护效果」填的是【投流前后的曝光量差额】, 投流之后「曝光量」
# 那一列也会被改成投流后的新数字。两件事合起来, 最容易犯的错是把「维护效果」或
# 「维护时间」映到 impressions / reads / interactions / comments_count ——
# 一旦映了, 投流的人工干预量会直接变成这条帖的自然指标, 而且【从数据上看不出来】
# (两个数字长得一模一样)。
# 今天没有任何一份 mapping 这么映, 这条是【前向】守卫: 新表按 _template 抄过去的时候
# 很容易顺手把三列升成 typed。
# ⚠️ 挡不住什么(D-051):
#   · 挡不住运营在飞书那一端把投流后的数字填回「曝光量」—— 那是 metric_snapshots
#     的历史快照去对账的事(投流日期写在「维护情况」的 9/15🍟 值里)。
#   · 挡不住把三列映到【别的】typed 列(比如 raw 文本列), 只钉住这四个指标列。
#   · 只看 field_mapping 的 value, 不看 computed_fields。
_PROMO_COLS = ("维护情况", "维护时间", "维护效果")
_METRIC_COLS = ("impressions", "reads", "interactions", "comments_count",
                "likes", "saves", "shares")


def check_promo_not_metric(verbose: bool = True) -> list[str]:
    problems: list[str] = []
    n_declared = 0
    for f in sorted(ROOT.glob("mappings/*.yaml")):
        m = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        fm = m.get("field_mapping") or {}
        allow = set(m.get("project_specific_fields_to_raw_extra") or [])
        for col in _PROMO_COLS:
            if col in allow:
                n_declared += 1
            tgt = fm.get(col)
            if tgt in _METRIC_COLS:
                problems.append(
                    f"{f.name}: field_mapping 把「{col}」映到了 {tgt} —— "
                    f"这一列装的是投流的人工干预量, 映进指标列之后就再也分不出来了。"
                    f"它只能进 project_specific_fields_to_raw_extra。")
    if verbose:
        print(f"  G5 投流三列零指标映射 (三列共在 {n_declared} 处声明进 raw_extra)")
    return problems


# ══════════════════════════════════════════════════════════════════════
# G6 · ci.yml 的【体积】棘轮
# ══════════════════════════════════════════════════════════════════════
#
# 2026-09-22 撞出来的硬闸, 不是风格问题:
#   511,110 字节 → CI 正常跑
#   516,314 字节 → GitHub **startup_failure**: 0 个 job、瞬间红、日志里什么都没有,
#                  运行列表里连 workflow 名都显示不出来(退成文件路径 .github/workflows/ci.yml)。
# 也就是说超限之后【整个 CI 不跑】, 而表面看只是"红了一下"。这是最难查的一类红。
# G2 数的是 heredoc 块【数】, 挡不住"块数不变但每块越写越长"—— 这次就是这么超的
# (只加了一个步骤里的 14 条断言 + 注释)。所以要再加一把尺子量字节。
#
# 挡【不】住:
#   · 挡不住别的 workflow 文件超限(只量 ci.yml)。
#   · 上限是【经验值】不是 GitHub 文档值 —— 我只知道 511,110 能跑、516,314 不能。
#     所以卡在 505,000: 比已知能跑的还低 6KB, 留一点余量, 且逼着新守卫往 scripts/ 走。
#   · 挡不住"把内容挪进 scripts/ 但那个脚本本身是空跑"。那是各自反证的事。
CI_BYTES_CAP = 505_000


def check_ci_size(verbose: bool = True) -> list[str]:
    if not CI.exists():
        return [".github/workflows/ci.yml 不在了"]
    n = len(CI.read_bytes())
    if verbose:
        print(f"  G6 ci.yml {n:,} 字节 (上限 {CI_BYTES_CAP:,}; 实测 516,314 会 startup_failure)")
    if n > CI_BYTES_CAP:
        return [
            f"ci.yml 涨到 {n:,} 字节, 超过 {CI_BYTES_CAP:,}。"
            "实测 516,314 字节时 GitHub 直接 startup_failure —— 0 个 job, 整个 CI 不跑, "
            "而且日志里看不出原因。把新加的内联块抽成 scripts/ 里的脚本, "
            "ci.yml 只留一行调用(D-075)。"]
    return []


CHECKS = {"g1": ("数据流向图", check_map),
          "g2": ("ci.yml 内联棘轮", check_ci_ratchet),
          "g3": ("灯登记册", check_lights),
          "g4": ("features 批大小与实测记录", check_features_batch),
          "g5": ("投流三列不得映指标列", check_promo_not_metric),
          "g6": ("ci.yml 体积棘轮", check_ci_size)}





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
