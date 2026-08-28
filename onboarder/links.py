"""onboarder/links.py — 飞书链接解析 + 批量清单解析(纯标准库,不联网)。

为什么单独一个模块:运营手里**只有浏览器地址栏里的那条链接**,没人记得 app_token /
table_id 长什么样。原来的入口(CLI / workflow_dispatch)要求先把这两个 id 抠出来 ——
那一步是人肉的、每次都要做、且抠错了要跑完一整轮飞书扫描才发现。这里把它变成确定性代码。

三件事,都不联网(联网那半在 clients / core:wiki 节点解析、列表选表):
  · parse_feishu_url  : 一条链接 → {host, kind, token, table_id, view_id}
  · safe_project_id   : project_id 会当**文件名**用(mappings/<id>.yaml)→ 必须先消毒
  · parse_batch_spec  : 一段多行/分号清单 → 逐条 {project_id, url|app_token+table_id}

⚠️ /base/ 与 /wiki/ **一视同仁**:两者的 token 都直接当 app_token 用,解析路径完全相同
   (kind 只作为信息回报,core 不据此分叉)。飞书的多维表 API 现在两种 token 都收。
   万一某张表的 token 不能直接用, core 在**第一次取字段失败之后**才去换一次 obj_token
   重试 —— 成功路径上零额外调用。

⚠️ 另两种"看着能跑、其实是另一回事"的,这里显式拦掉,不猜:
  · larksuite.com  —— 国际版 Lark,API 主机是 open.larksuite.com,而本仓客户端固定
                      open.feishu.cn。不拦的话表现为"这张表不存在"。
  · 没有 ?table=   —— 多表 base 的链接省略 table 时是**歧义**,不是缺省。由 core 去
                      列表:只有一张就用它,多张就把候选报出来让人选。
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

# project_id 会拼成 mappings/<id>.yaml 落盘, 且来自 workflow_dispatch 输入(不可信)。
# 闭集式白名单 —— 不是"过滤掉危险字符", 是"只允许这些字符"(黑名单永远漏)。
_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

# 飞书各类 token 的字符集(base/wiki/table/view 都是这个形状)
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# 已知的飞书主机后缀(国内版)。larksuite 是国际版, API 主机不同 —— 单独报错。
_FEISHU_HOSTS = (".feishu.cn", ".feishu.net")
_LARK_HOSTS = (".larksuite.com", ".larkoffice.com")


class LinkError(ValueError):
    """链接/清单解析失败 —— 消息直接给人看, 所以写清楚"错在哪、该怎么改"。"""


def safe_project_id(value: str) -> str:
    """校验 project_id 可以安全地当文件名用, 返回原值;不合法则抛 LinkError。

    ⚠️ 这是**路径穿越闸**, 不只是格式校验。project_id 来自 workflow_dispatch 的
    自由文本输入, 随后被拼成 ``Path(out_dir) / f"{project_id}.yaml"`` 落盘并 git add。
    ``../../.github/workflows/ci`` 这种值会把草稿写到仓库任意位置 —— 而这条流水线
    是自动 commit + push 的, 没有人在中间看一眼。
    """
    pid = (value or "").strip()
    if not pid:
        raise LinkError("project_id 是空的")
    if not _PROJECT_ID_RE.match(pid):
        raise LinkError(
            f"project_id {pid!r} 不合法 —— 只允许字母/数字/下划线/点/连字符, "
            "且以字母或数字开头(它会当文件名用:mappings/<project_id>.yaml)"
        )
    # 白名单已经排除了 / 和 \, 但 "..'" 这类纯点串仍能通过上面的正则(如 "..")
    # —— 它们当文件名是合法字符, 当路径却是父目录。显式再挡一次。
    if set(pid) <= {".", "-", "_"}:
        raise LinkError(f"project_id {pid!r} 不合法 —— 不能只由 . - _ 组成")
    return pid


def _clean_token(raw: str | None, *, label: str, expect_prefix: str = "") -> str | None:
    if raw is None:
        return None
    tok = unquote(raw).strip()
    if not tok:
        return None
    if not _TOKEN_RE.match(tok):
        raise LinkError(f"{label} {tok!r} 不像飞书 id(只应含字母/数字/下划线/连字符)")
    if expect_prefix and not tok.startswith(expect_prefix):
        # 不硬拒:飞书改过 token 形态(bascn… → A2sy… 无前缀),硬拒会让工具先于飞书过时。
        # 但要出声 —— 把 view_id 当 table_id 粘进来是最常见的手滑。
        print(f"⚠️  {label} {tok!r} 没有预期的 {expect_prefix!r} 前缀 —— 确认没粘错?")
    return tok


def parse_feishu_url(url: str) -> dict[str, Any]:
    """一条飞书多维表链接 → {host, kind, token, table_id, view_id}。

    kind: "base"(/base/<app_token>) 或 "wiki"(/wiki/<node_token>, 需再换 obj_token)。
    识别的形态:
        https://x.feishu.cn/base/<app_token>?table=<tbl>&view=<vew>
        https://x.feishu.cn/base/<app_token>/<table_id>
        https://x.feishu.cn/wiki/<node_token>?table=<tbl>
    """
    raw = (url or "").strip().strip("<>\"'")
    if not raw:
        raise LinkError("链接是空的")
    if "://" not in raw:
        raw = "https://" + raw

    parts = urlsplit(raw)
    host = (parts.hostname or "").lower()
    if not host:
        raise LinkError(f"解析不出主机名:{url!r}")

    if any(host.endswith(h) for h in _LARK_HOSTS):
        raise LinkError(
            f"{host} 是国际版 Lark —— 它的 API 主机是 open.larksuite.com,"
            "而本仓客户端(onboarder/clients.py)固定 open.feishu.cn。"
            "接国际版表需要先改客户端主机,不要直接跑(否则表现为「这张表不存在」)。"
        )
    if not any(host.endswith(h) for h in _FEISHU_HOSTS):
        raise LinkError(f"{host} 不是飞书域名 —— 只认 *.feishu.cn / *.feishu.net")

    segs = [s for s in parts.path.split("/") if s]
    kind = ""
    token = ""
    path_table = None
    for i, seg in enumerate(segs):
        if seg in ("base", "wiki"):
            kind = seg
            if i + 1 < len(segs):
                token = segs[i + 1]
            # /base/<app_token>/<table_id> 这种路径形态
            if i + 2 < len(segs) and segs[i + 2].startswith("tbl"):
                path_table = segs[i + 2]
            break
    if not kind or not token:
        raise LinkError(
            f"链接里找不到 /base/<app_token> 或 /wiki/<node_token> 段:{url!r}"
        )

    q = parse_qs(parts.query)
    table_id = _clean_token(
        (q.get("table") or [None])[0] or path_table, label="table_id", expect_prefix="tbl"
    )
    view_id = _clean_token((q.get("view") or [None])[0], label="view_id", expect_prefix="vew")
    token = _clean_token(token, label=("wiki node_token" if kind == "wiki" else "app_token"))

    return {"host": host, "kind": kind, "token": token,
            "table_id": table_id, "view_id": view_id}


# ── 批量清单 ────────────────────────────────────────────────────────────────
#
# 分隔符的取舍:workflow_dispatch 的 string 输入在 GitHub UI 上是**单行**文本框 ——
# 敲不进换行。所以条目分隔必须同时支持换行(文件/本地跑)和分号(网页按钮粘一行)。
_ENTRY_SPLIT = re.compile(r"[;\n]+")
_COMMENT = re.compile(r"(^|\s)#.*$")


def _strip_comment(line: str) -> str:
    # 只在行首或空白之后剥 # —— URL 里的 #fragment 不该被当注释吃掉
    return _COMMENT.sub("", line).strip()


def parse_batch_spec(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """批量清单文本 → (entries, errors)。**不**在第一条错就抛 —— 一次把所有问题报全。

    每条一张表,列用 | 分隔(也接受全角 ｜):
        TXQ_phase2 | https://x.feishu.cn/base/App?table=tblA        # 链接式
        TXQ_phase2 | https://x.feishu.cn/base/App?table=tblA | 50   # + 样本行数
        OKM_phase2 | AppToken | tblB                                # id 式
        OKM_phase2 | AppToken | tblB | 50

    第 2 列含 "://" 即判为链接式(此时第 3 列是 sample_n);否则为 id 式。
    """
    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: dict[str, int] = {}

    for lineno, chunk in enumerate(_ENTRY_SPLIT.split(text or ""), start=1):
        line = _strip_comment(chunk.replace("｜", "|"))
        if not line:
            continue
        cols = [c.strip() for c in line.split("|")]
        cols = [c for c in cols if c != ""]
        if len(cols) < 2:
            errors.append(
                f"第 {lineno} 条 {line!r}:至少要 2 列 —— "
                "「project_id | 飞书链接」或「project_id | app_token | table_id」"
            )
            continue

        try:
            pid = safe_project_id(cols[0])
        except LinkError as exc:
            errors.append(f"第 {lineno} 条:{exc}")
            continue

        # 同一批里重名 = 后一条静默覆盖前一条的产出。宁可整批不跑。
        if pid in seen:
            errors.append(f"第 {lineno} 条:project_id {pid!r} 与第 {seen[pid]} 条重复")
            continue
        seen[pid] = lineno

        entry: dict[str, Any] = {"project_id": pid, "url": None,
                                 "app_token": None, "table_id": None, "sample_n": None}
        rest = cols[1:]
        try:
            if "://" in rest[0] or rest[0].lower().startswith("www."):
                entry["url"] = rest[0]
                parse_feishu_url(rest[0])          # 早失败:清单阶段就把坏链接报出来
                tail = rest[1:]
            else:
                if len(rest) < 2:
                    raise LinkError(
                        "id 式要 3 列(project_id | app_token | table_id);"
                        "只给一条链接的话请用链接式"
                    )
                entry["app_token"] = _clean_token(rest[0], label="app_token")
                entry["table_id"] = _clean_token(rest[1], label="table_id", expect_prefix="tbl")
                tail = rest[2:]
            if tail:
                if not tail[0].isdigit():
                    raise LinkError(f"样本行数 {tail[0]!r} 不是数字")
                entry["sample_n"] = int(tail[0])
        except LinkError as exc:
            errors.append(f"第 {lineno} 条({pid}):{exc}")
            continue

        entries.append(entry)

    if not entries and not errors:
        errors.append("清单是空的 —— 一行一张表:「project_id | 飞书链接」")
    return entries, errors
