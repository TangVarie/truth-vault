"""
sync_comments_from_raw_extra.py
═══════════════════════════════════════════════════════════════════════════

Parses comment text that sync_feishu_notes_to_truth_vault.py stored in
notes.raw_extra._comment_text and ._comment_text_persona, and writes
truth_vault.comments rows.

The Feishu cell "随贴评论" is a free-text block that operators paste in.
There's no canonical line format, so this script supports the two patterns
we've actually seen in NUC_phase1 data:

  Pattern A (numbered lines, NUC_1 default):
    1. 用户A: 第一条评论
    2. 用户B: 回复用户A的评论
    3. 用户C: 第三条

  Pattern A 同一行写了好几条 (D-085): 运营把「 7. … 8. … 9. …」接在同一行里。
    原来只按换行切, 这种会并成一条 (judge 仓抽的 33 条样本里有 4 条是这样)。现在每一行再按
    (?<=\\S)\\s+(?=\\d{1,2}[.、](?!\\d)\\s*\\S) 二次切 —— 见 _split_inline_items: 编号必须
    连号 (且接得上行首编号), 否则整行不切; (?!\\d) 挡「2.5 元」这种小数。

  Pattern B (separator-delimited block):
    用户A | 第一条
    用户B | 第二条

Hierarchy reconstruction (parent_comment_id) is NOT inferred from text
patterns — it requires LLM analysis (D-022 / Q21). This script writes a
FLAT comments table (all parent_comment_id NULL); LLM楼层重建 is a Sprint 2
follow-up. comment_role defaults to '素人' unless the operator prefixed
"贴主:" / "运营:", or (D-085) wrote an operator tag like 【贴主回复】/【素人评论】/
【素人回复】 in front of the comment: the tag is stripped from content and decides
comment_role (贴主… → '贴主', 素人… → '素人', 运营/客服… → '运营', 路人… → '路人').
Unknown 【…】 tags are left in the text untouched.

⚠️ D-085 一次性清理 (改了切法 / 剥了前缀之后, 【下一次同步】之后要 owner 做一次):
  切法变了, 已入库的「并成一条」的旧行和带【…】前缀的旧行按 (role, content) 配不上新切出来的行 ——
  新行以新 id 插入, 旧行按本脚本「只报不删」的口径留在库里 (日志里记成「找不到了」)。不清的话
  同一篇的评论会有新旧两份, judge 回填评论时两份都判、按篇统计评论构成会重复。清法:
    1. 同步跑过之后 (夜跑 daily-sync 或手动), 对每个有随贴评论的项目:
         python sync_comments_from_raw_extra.py <项目> --dry-run --vanished-out vanished_<项目>.jsonl
       dry-run 只读不写; jsonl 每行一条「库里有、源里找不到」的评论, kind = parser_change 的是本次
       切法 / 前缀改动造成的旧行 (它的内容按新规则会被切开或剥掉前缀), source_removed 是运营真删了的。
    2. 人看一遍 parser_change 那批, 按 comment_id 删掉 (DELETE FROM truth_vault.comments WHERE comment_id IN (…))。
       comments.parent_comment_id 是 ON DELETE SET NULL: 挂在旧行下面的楼层会断, 要楼层就重跑楼层重建。
    3. judge 若已经给这些旧行判过分 (note_feature_answers.subject_type = 'comment'), 同一批 comment_id
       的账本行一起删; scripts/verify_supabase_state.sql #85 会把悬空的 comment 账本行数出来。
       最好第 2 步做完再跑 judge 的评论回填。

What it does
  - For each note where notes.raw_extra._comment_text is present
  - Skip if truth_vault.comments already has rows for that note (idempotent)
  - Parse line-by-line, write comments rows
  - comment_id is deterministic: f"{note_id}_c{ordinal}"
    so reruns produce the same IDs (idempotent at the row level too)

⚠️ Limitations
  - Doesn't reconstruct parent/child structure
  - Doesn't extract pinned_comment (that's a separate notes.pinned_comment col)
  - Doesn't infer blue keyword matches (Sprint 2)
  - Doesn't handle truncation / mid-line line breaks
  - This is a "minimum viable comments table" so ssll's vibe_rewriter has
    SOME comment evidence to work with. Full reconstruction needs LLM pass.
  - ⚠️ _comment_text_persona semantic risk: this script currently treats it
    as additional comment text and concatenates with _comment_text. NUC_phase1
    sample data confirms this is correct (operator pastes a second comment
    block under the same column). If a future project uses _comment_text_persona
    to mean "evaluator/persona-of-commenter labels" instead (a different
    semantic), those values would land in comments.content and corrupt the
    flat comments table. Confirm column semantics with the project's onboarding
    sheet BEFORE running on a new project; for now, NUC_phase1 / NRT_* are OK.

第二个来源: 巡查工具 (linkcheck) 看到的评论区第一页 (十三件事第 2 件, D-155, 2026-11-15)
  上面说的都是运营自己贴的「随贴评论」。巡查工具每轮还把帖子评论区第一页写进飞书两格, 夜跑同步原样收在
  notes.raw_extra (顶层或 _undeclared) 里, 以前没人读:
    · 「评论区快照」  给人看的一段文字: 「序号. [标记 · 标记] 昵称: 正文」, 每条截到 40 字 (截了以「…」结尾), 最多 8 条,
                     放不下的记一行「…（还有 N 条未显示）」, 一条都没有是「（暂无评论）」。
    · 「评论区明细」  同一页的一行 JSON (linkcheck 11-15 加的列, 老表要点一次「补齐缺的列」才有): 每条带平台评论 ID、
                     发布时刻、作者 / 置顶 / 赞数、命中评论关键词没有、楼中楼的父评论 ID、截到 200 字的正文。
  这条路把它们也写成 comments 行, 和运营贴的行靠 comments.source 分开 (schemas/notes_v1_27_*.sql):
    运营贴的 = source 为空; 快照拆出来的 = linkcheck_digest; 明细读出来的 = linkcheck_records。
  · 一篇两格都有 → 只用明细, 这一篇原来的快照行删掉; 只有快照 → 用快照。
  · 快照行: id 按 (角色, 正文) 算 ({note_id}_lcd…), 重跑不变; 快照变了 → 这一篇的快照行换成新的一套 (不在新快照里的删掉,
    新出现的插入), 运营贴的行一行不碰。昵称、IP 属地在入库前剥掉, 不落库。
  · 明细行: id 用平台评论 ID ({note_id}_lcr…; 上游没给 ID 的按正文算, {note_id}_lcn…)。看到过的留着, 不因为后来掉出
    第一页就删; 同一条的正文 / 角色 / 置顶 / 命中变了就更新。
  · 作者标记 → comment_role = 贴主; 其余 = 路人 (明细里作者标记这一轮不可信时 = 未知)。
    已经记成贴主的明细行, 后来某一轮作者标记不可信也不降成未知 (降了就会被数成读者评论)。
  · 命中这一行「评论关键词」的 (快照里带「命中」标记的那条, 以及正文里出现任一关键词的; 明细里 k = 1 的) 写
    is_scripted = true: 多半是我们自己铺的, 数读者评论时要拿掉。没命中的留空, 不写 false。
  · is_truncated: 正文被截过 (快照 40 字 / 明细 200 字)。
  · observed_at: 明细行 = JSON 里的 t; 快照行 = 这一篇的「最近检查时间」, 只在「巡查状态」= 正常 时填 (巡查失败的
    轮次也会推进「最近检查时间」, 那时快照还是上一轮的)。
    在巡查没成功的那一轮入库的行时刻是空的; 之后哪一轮巡查正常了、这一行还在, 就补上那一轮的时刻 (只补这一次)。
  · 运营贴的那条路的配对和「找不到了」对账只看 source 为空的行, 巡查来的行不参与、不会被报成「源里没了」。
  · v1.27 没跑 (comments 没有 source 这一列): 整条路不走, 行为和以前一模一样, 带快照的项目打一行 warning。
  挡不住什么: 快照截到 40 字, 关键词落在 40 字之后的铺评认不出; 关了昵称落库的表, 正文里自带「xx: 」会被当成昵称
  剥掉开头; 只有第一页 (小红书 10 条 / 抖音 20 条, 快照最多 8 条); 没有「评论关键词」的行分不出铺评。

Usage:
    python sync_comments_from_raw_extra.py NUC_phase1
    python sync_comments_from_raw_extra.py NUC_phase1 --dry-run --limit 5
    python sync_comments_from_raw_extra.py NUC_phase1 --dry-run --vanished-out vanished.jsonl   # D-085 清理用
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from typing import Iterator, Optional

from _common import (
    fetch_all_pages,
    get_supabase_client,
    load_mapping,
    setup_logger,
    skip_on_demand_on_cron,
    warn_missing_migration_once,
    _is_missing_column_error,
    _iso_now,
)


logger = setup_logger("sync_comments")


# Roles operators sometimes prefix into a comment line. Anything else
# defaults to '素人'.
ROLE_PREFIXES = {
    "贴主": "贴主",
    "原帖作者": "贴主",
    "运营": "运营",
    "客服": "运营",
}

# 运营写在评论前面的【…】标签 (D-085): 【素人评论】【贴主回复】【素人回复】…
# 标签是运营自己标的「这条是谁说的」, 比默认的 '素人' 准: 剥掉并拿它定 comment_role。
# 只认这几种身份词 (+ 可选的 评论/回复); 别的【…】(【置顶】【图】之类) 不认、原样留在正文里。
_BRACKET_ROLES = {"贴主": "贴主", "原帖作者": "贴主", "楼主": "贴主",
                  "素人": "素人", "路人": "路人", "运营": "运营", "客服": "运营"}
_BRACKET_ROLE_RE = re.compile(r"^【(贴主|原帖作者|楼主|素人|路人|运营|客服)(?:评论|回复)?】\s*")

# Pattern A 同一行写了好几条 (D-085): 在「非空白 + 空白 + 编号 + [.、]」处二次切。
# (?!\d) 挡小数 ("只要 2.5 元")。切点只是候选, 由 _split_inline_items 按连号再判一次。
_INLINE_ITEM_RE = re.compile(r"(?<=\S)\s+(?=\d{1,2}[.、](?!\d)\s*\S)")
_ITEM_NO_RE = re.compile(r"\(?(\d{1,2})\)?[.、](?!\d)")   # 行首编号同样不认小数 (「1.5 倍」不是第 1 条)


def _split_inline_items(line: str) -> list[str]:
    """一行 → 一条或多条评论文本。

    只有候选切点上的编号【连号】(n, n+1, n+2…), 且行首也有编号时第一个候选正好接上它 (行首 6 →
    候选从 7 起), 才整行按候选切开; 否则整行原样返回 (宁可不切, 也不把一条评论里的「1、便宜
    2、好用」切成三条 —— 切错的代价是评论身份全换, 见模块头的 D-085 清理)。"""
    cuts = [m.end() for m in _INLINE_ITEM_RE.finditer(line)]
    if not cuts:
        return [line]
    nums = [int(_ITEM_NO_RE.match(line, c).group(1)) for c in cuts]
    lead = _ITEM_NO_RE.match(line.lstrip())
    start = int(lead.group(1)) + 1 if lead else nums[0]
    if nums != list(range(start, start + len(nums))):
        return [line]
    bounds = [0] + cuts + [len(line)]
    return [line[a:b].strip() for a, b in zip(bounds, bounds[1:]) if line[a:b].strip()]


def _changed_by_d085(content: str) -> bool:
    """这条已入库的评论, 按 D-085 的新规则会不会被切开或剥掉前缀 (清理时区分「切法变了」和「运营删了」)。"""
    s = (content or "").strip()
    return len(_split_inline_items(s)) > 1 or bool(_BRACKET_ROLE_RE.match(s))


def _parse_comment_line(line: str) -> Optional[tuple[str, str]]:
    """Extract (role, content) from a single comment line.

    Returns None if the line is blank / pure whitespace / pure number.
    Recognized shapes:
        "1. 用户A: hello"           → ('素人', 'hello')         [strips number + name]
        "贴主: thanks"               → ('贴主', 'thanks')
        "用户A | hello"              → ('素人', 'hello')
        "hello"                      → ('素人', 'hello')
        "1. 【贴主回复】谢谢"          → ('贴主', '谢谢')           [D-085: 标签定角色, 不再拆名字]
    """
    s = line.strip()
    if not s:
        return None
    if re.fullmatch(r"\d+[.、]?", s):
        return None  # numbering remnant

    # Strip leading "1. " / "1、" / "(1)"
    s = re.sub(r"^\(?\d+\)?[.、]\s*", "", s)

    # 运营标签【贴主回复】等 (D-085): 标签说了是谁, 后面整段就是正文 —— 不再走下面的
    # 「名字: 内容」拆法 (正文里的冒号会被当成名字切掉)。
    m = _BRACKET_ROLE_RE.match(s)
    if m:
        content = s[m.end():].strip()
        return (_BRACKET_ROLES[m.group(1)], content) if content else None

    # Pipe separator (Pattern B)
    if "|" in s:
        before, after = s.split("|", 1)
        content = after.strip()
        # check role prefix on the name part
        name_part = before.strip()
        for prefix, role in ROLE_PREFIXES.items():
            if name_part.startswith(prefix):
                return role, content
        return "素人", content

    # Colon separator (Pattern A)
    m = re.match(r"^([^:：]{1,20})[:：]\s*(.+)$", s)
    if m:
        name_part, content = m.group(1).strip(), m.group(2).strip()
        for prefix, role in ROLE_PREFIXES.items():
            if name_part.startswith(prefix):
                return role, content
        if content:
            return "素人", content

    # Bare line, no role / no name
    return "素人", s


def parse_comment_text(text: str) -> Iterator[tuple[str, str]]:
    """Yield (role, content) for each parseable comment in a comment block.

    先按换行切, 每行再按 _split_inline_items 二次切 (D-085: 「 7. … 8. …」写在同一行)。"""
    if not text:
        return
    for line in text.splitlines():
        for item in _split_inline_items(line):
            parsed = _parse_comment_line(item)
            if parsed is not None:
                yield parsed


# ════════════════════════════════════════════════════════════════════
# 第二个来源: 巡查工具看到的评论区第一页 (D-155; 说明在模块头)
# ════════════════════════════════════════════════════════════════════
SOURCE_DIGEST = "linkcheck_digest"       # 「评论区快照」那段文字拆出来的
SOURCE_RECORDS = "linkcheck_records"     # 「评论区明细」那一行 JSON 读出来的
LINKCHECK_SOURCES = (SOURCE_DIGEST, SOURCE_RECORDS)
DIGEST_COL, RECORDS_COL = "评论区快照", "评论区明细"
CHECKED_COL, STATUS_COL, KEYWORDS_COL = "最近检查时间", "巡查状态", "评论关键词"
STATUS_OK = "正常"
DIGEST_TEXT_CHARS = 40                   # linkcheck DigestFormat.per_comment_chars: 超了截到 39 字 + 「…」
RECORDS_VERSION = 1
LINEAGE_COLS = ("source", "is_truncated", "observed_at")
LINEAGE_MIGRATION = "schemas/notes_v1_27_reader_comments_observations.sql"
_BASE_COMMENT_COLS = "comment_id, note_id, content, comment_role, comment_order"
_LINEAGE_COMMENT_COLS = (_BASE_COMMENT_COLS + ", is_pinned, is_scripted, parent_comment_id, comment_time, "
                         + ", ".join(LINEAGE_COLS))
# main 读完项目的已入库评论之后置位: True = 库里有 source 这一列, existing_comments 要把巡查来的行滤掉。
_LINEAGE_SUPPORTED: list[bool] = []

_DIGEST_LINE_RE = re.compile(r"^\s*(\d{1,3})\. (.*)$")
_DIGEST_MORE_RE = re.compile(r"^\s*…（还有 \d+ 条未显示）\s*$")
_DIGEST_EMPTY_RE = re.compile(r"^\s*（(?:暂无评论|接口报评论数 \d+，但评论区一条都看不到).*$")
_DIGEST_MARKS_RE = re.compile(r"^\[([^\[\]]*)\] ")
_MARK_HIT_RE = re.compile(r"^命中「(.*)」$")
_MARK_KNOWN_RE = re.compile(r"^(?:最新|置顶|作者|回复(?:「.*」)?|\d+赞)$")
_MARK_IP_RE = re.compile(r"^[一-鿿]{2,10}$")     # IP 属地: 只会是最后一个标记
_NICK_RE = re.compile(r"^(.{1,40}?): (.*)$")
_HIGHLIGHT_RE = re.compile(r"#([^#\[\]]+?)\[搜索高亮\]#")   # 小红书蓝词标记: 「#词[搜索高亮]#」 → 「词」
_UPSTREAM_ID_RE = re.compile(r"^[0-9A-Za-z_-]{1,64}$")
_MS_MIN, _MS_MAX = 946684800000, 4102444800000           # 2000-01-01 … 2100-01-01, 同 v1.22 / v1.27 的 SQL


def _raw_cell(raw: dict, col: str):
    """raw_extra 里的一格: 顶层有值用顶层, 顶层空才看 _undeclared (mapping 没声明这一列时 sync 把它收在那里)。"""
    v = raw.get(col)
    if v in (None, "", []):
        und = raw.get("_undeclared")
        v = und.get(col) if isinstance(und, dict) else None
    return v


def _cell_text(v) -> str:
    """飞书文本格可能是字符串, 也可能是 [{text, type}, …] 分段: 拼成一个字符串。别的类型 = 空。"""
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        return v.get("text") if isinstance(v.get("text"), str) else ""
    if isinstance(v, list):
        return "".join(_cell_text(x) for x in v if isinstance(x, (str, dict)))
    return ""


def _ms_to_iso(v, *, tz: bool) -> Optional[str]:
    """毫秒时间戳 → UTC ISO 串 (tz=True 带 +00:00, 给 TIMESTAMPTZ 列; False 不带, 给无时区列)。不像时间戳的 = None。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not (_MS_MIN <= v <= _MS_MAX):
        return None
    import datetime as _dt
    t = _dt.datetime.fromtimestamp(v / 1000.0, tz=_dt.timezone.utc).replace(microsecond=0)
    return t.isoformat() if tz else t.replace(tzinfo=None).isoformat()


def _norm(text: str) -> str:
    """同 linkcheck analyze._normalize: 去空白、去标点、统一大小写, 只做宽松的包含匹配。"""
    return re.sub(r"[\s\W_]+", "", text or "").lower()


def seed_needles(cell) -> list[str]:
    """「评论关键词」那一格 → 归一化之后的词。拆法同 linkcheck 的 read_keywords (两边拆得不一样, 铺评就认不全):

    列表先当多选取选项 (纯字符串, 或带 name 的选项对象); 取不到 (文本列的富文本分段 [{text, type}, …]) 再把分段
    拼成一整段, 和纯字符串一样按 顿号 / 逗号 / 分号 / 换行 拆。不按空格拆 (带空格的词组是一个词)。"""
    words: list[str] = []
    if isinstance(cell, list):
        for x in cell:
            if isinstance(x, str):
                words.append(x)
            elif isinstance(x, dict) and x.get("name"):
                words.append(str(x["name"]))
    if not words:
        words = re.split(r"[、,，;；\n]+", _cell_text(cell))
    return [n for n in (_norm(w) for w in words) if n]


def _strip_highlight(text: str) -> str:
    return _HIGHLIGHT_RE.sub(lambda m: m.group(1).strip(), text)


def _marks_ok(parts: list[str]) -> bool:
    """方括号里是不是 linkcheck 排的标记段 (而不是评论正文自己带的 [笑哭R] 这种表情)。"""
    for i, p in enumerate(parts):
        if _MARK_HIT_RE.match(p) or _MARK_KNOWN_RE.match(p):
            continue
        if i == len(parts) - 1 and _MARK_IP_RE.match(p):
            continue
        return False
    return bool(parts)


def parse_digest(text: str, needles: Optional[list[str]] = None) -> Optional[list[dict]]:
    """「评论区快照」那段文字 → 一条评论一个 dict (role / content / is_pinned / is_truncated / seeded / likes)。

    回 None = 这段文字不是认得的格式 (一行编号行、一行占位都没有): 调用方不动这一篇已有的行。
    回 []   = 认得, 评论区是空的 (「（暂无评论）」/ 「接口报评论数 N，但评论区一条都看不到」)。
    昵称和 IP 属地在这里剥掉, 不出现在返回值里。「…（还有 N 条未显示）」那一行跳过。
    """
    out: list[dict] = []
    recognised = False
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        if _DIGEST_EMPTY_RE.match(line) or _DIGEST_MORE_RE.match(line):
            recognised = True
            continue
        m = _DIGEST_LINE_RE.match(line)
        if not m:
            continue
        recognised = True
        body = m.group(2)
        marks: list[str] = []
        mm = _DIGEST_MARKS_RE.match(body)
        if mm and _marks_ok(mm.group(1).split(" · ")):
            marks = mm.group(1).split(" · ")
            body = body[mm.end():]
        nm = _NICK_RE.match(body)
        if nm:
            body = nm.group(2)
        elif re.fullmatch(r".{1,40}:", body.rstrip()):
            body = ""                       # 「昵称: 」后面是空的 (纯图片评论), 行尾空格被飞书吃掉了
        content = body.strip()
        if not content:
            continue
        truncated = content.endswith("…") and len(content) == DIGEST_TEXT_CHARS
        content = _strip_highlight(content)
        likes = next((int(p[:-1]) for p in marks if re.fullmatch(r"\d+赞", p)), None)
        seeded = any(_MARK_HIT_RE.match(p) for p in marks) or (
            bool(needles) and any(n in _norm(content) for n in needles))
        out.append({
            "role": "贴主" if "作者" in marks else "路人",
            "content": content,
            "is_pinned": "置顶" in marks,
            "is_truncated": truncated,
            "seeded": seeded,
            "likes": likes,
            "upstream_id": "", "parent_upstream_id": "", "comment_time": None,
        })
    return out if recognised else None


def parse_records(text: str) -> Optional[dict]:
    """「评论区明细」那一行 JSON → {"observed_at": ISO 或 None, "rows": [...]} (rows 的键同 parse_digest, 多了平台 ID)。

    回 None = 不是认得的格式 (不是 JSON / 版本不是 1 / c 不是列表): 调用方退回去用快照。
    正文为空的条目跳过; 同一个平台 ID 出现两次只留第一次。
    """
    try:
        obj = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(obj, dict) or obj.get("v") != RECORDS_VERSION or not isinstance(obj.get("c"), list):
        return None
    author_ok, rows, seen = obj.get("ar") == 1, [], set()
    for e in obj["c"]:
        if not isinstance(e, dict) or not isinstance(e.get("x"), str):
            continue
        content = _strip_highlight(e["x"]).strip()
        if not content:
            continue
        up = e.get("id") if isinstance(e.get("id"), str) and _UPSTREAM_ID_RE.match(e.get("id") or "") else ""
        if up:
            if up in seen:
                continue
            seen.add(up)
        parent = e.get("r") if isinstance(e.get("r"), str) and _UPSTREAM_ID_RE.match(e.get("r") or "") else ""
        likes = e.get("l")
        rows.append({
            "role": "贴主" if e.get("a") == 1 else ("路人" if author_ok else "未知"),
            "content": content,
            "is_pinned": e.get("p") == 1,
            "is_truncated": e.get("tr") == 1,
            "seeded": e.get("k") == 1,
            "likes": likes if isinstance(likes, int) and not isinstance(likes, bool) else None,
            "upstream_id": up, "parent_upstream_id": parent,
            "comment_time": _ms_to_iso(e.get("ts"), tz=False),
        })
    return {"observed_at": _ms_to_iso(obj.get("t"), tz=True), "rows": rows}


def has_linkcheck_cells(raw: dict) -> bool:
    return bool(_cell_text(_raw_cell(raw, RECORDS_COL)).strip() or _cell_text(_raw_cell(raw, DIGEST_COL)).strip())


def is_linkcheck_comment_id(comment_id: str, note_id: str) -> bool:
    """巡查来的行的 id 都是 {note_id}_lc…; 运营贴的行是 {note_id}_c… / {note_id}_h…, 撞不上。"""
    return (comment_id or "").startswith(f"{note_id}_lc")


def _lc_hash(role: str, content: str) -> str:
    return hashlib.sha256("\u0000".join(_content_key(role, content)).encode("utf-8")).hexdigest()[:12]


_LC_MATERIAL = ("content", "comment_role", "is_pinned", "is_scripted", "is_truncated", "parent_comment_id")


def plan_linkcheck_rows(note: dict, existing: list[dict]) -> dict:
    """一篇 note: 巡查来的行该写成什么样。纯函数, 不碰库。

    existing = 这一篇已入库的、source 是 linkcheck_* 的行。回:
      source   这次用的哪个来源 (None = 这一篇没有能用的格子, 或认不出, 什么都不动)
      upserts  要插入 / 更新的整行 (id 已在库里且内容没变的不在里面)
      deletes  要删的 comment_id
      note     一句话的原因 (认不出 / 明细认不出退回快照 …), 没有就是空串
    """
    raw = note.get("raw_extra") or {}
    note_id, project_id = note["note_id"], note["project_id"]
    plan = {"source": None, "upserts": [], "deletes": [], "note": ""}
    rec_text = _cell_text(_raw_cell(raw, RECORDS_COL)).strip()
    dig_text = _cell_text(_raw_cell(raw, DIGEST_COL)).strip()
    by_id = {r["comment_id"]: r for r in existing}
    old_digest = [r["comment_id"] for r in existing if r.get("source") == SOURCE_DIGEST]
    has_records_rows = any(r.get("source") == SOURCE_RECORDS for r in existing)

    parsed_rec = parse_records(rec_text) if rec_text else None
    if rec_text and parsed_rec is None:
        plan["note"] = "「评论区明细」认不出 (不是 v1 的 JSON), 退回去用快照"
    if parsed_rec is not None:
        source, rows, observed_at = SOURCE_RECORDS, parsed_rec["rows"], parsed_rec["observed_at"]
    else:
        if not dig_text:
            return plan
        if has_records_rows:
            # 这一篇已经有按平台 ID 入库的行, 现在明细那一格空了 / 坏了: 不再往上叠一套快照行 (同一批评论会变两份)
            plan["note"] = plan["note"] or "这一篇已有明细行、这次没有明细, 快照不叠上去"
            return plan
        rows = parse_digest(dig_text, seed_needles(_raw_cell(raw, KEYWORDS_COL)))
        if rows is None:
            plan["note"] = "「评论区快照」认不出 (没有编号行也没有占位行), 这一篇已有的行不动"
            return plan
        source = SOURCE_DIGEST
        status = _cell_text(_raw_cell(raw, STATUS_COL)).strip()
        observed_at = _ms_to_iso(_raw_cell(raw, CHECKED_COL), tz=True) if status == STATUS_OK else None
    plan["source"] = source

    # id: 明细有平台 ID 的用它; 其余按 (角色, 正文) 算, 同一页里重复的按第几次出现编号 (重跑不变)
    nth: dict[tuple[str, str], int] = {}
    ids: list[str] = []
    for r in rows:
        if r["upstream_id"]:
            ids.append(f"{note_id}_lcr{r['upstream_id']}")
            continue
        prefix = "lcd" if source == SOURCE_DIGEST else "lcn"
        if r["role"] == "未知":
            # 没有平台 ID 的行, id 是按 (角色, 正文) 算的。这一轮作者标记不可信、角色成了「未知」, 而库里同一句话
            # 以前是按「贴主」入的库: 认回那一行 (id 和角色都沿用), 不另起一行 —— 另起的话库里就有两份,
            # 「未知」那一份还会过了「不是贴主」那道筛被数成读者评论。
            akey = _content_key("贴主", r["content"])
            alt = f"{note_id}_{prefix}{_lc_hash('贴主', r['content'])}_{nth.get(akey, 0) + 1}"
            if alt in by_id and (by_id[alt].get("comment_role") == "贴主"):
                r = dict(r, role="贴主")
                rows[len(ids)] = r
        key = _content_key(r["role"], r["content"])
        nth[key] = nth.get(key, 0) + 1
        ids.append(f"{note_id}_{prefix}{_lc_hash(r['role'], r['content'])}_{nth[key]}")
    known = set(ids) | set(by_id)

    for order, (cid, r) in enumerate(zip(ids, rows), start=1):
        parent = f"{note_id}_lcr{r['parent_upstream_id']}" if r["parent_upstream_id"] else None
        if parent not in known or parent == cid:
            parent = None                    # 父评论不在这一页也不在库里: 外键指不过去, 留空
        extra = {k: v for k, v in (("likes", r["likes"]), ("platform_comment_id", r["upstream_id"] or None)) if v is not None}
        row = {
            "comment_id": cid, "note_id": note_id, "project_id": project_id,
            "content": r["content"], "comment_role": r["role"], "comment_order": order,
            "parent_comment_id": parent, "comment_time": r["comment_time"],
            "is_scripted": True if r["seeded"] else None,
            "is_pinned": bool(r["is_pinned"]), "is_displayed": True,
            "source": source, "is_truncated": bool(r["is_truncated"]), "observed_at": observed_at,
            "raw_extra": extra or None,
        }
        old = by_id.get(cid)
        if old is not None and old.get("comment_role") == "贴主" and row["comment_role"] == "未知":
            # 以前某一轮确认过这条是作者自己发的, 这一轮只是作者标记不可信 (备用通道 / 没拿到作者账号): 不降成未知 ——
            # 降了它就过了「不是贴主」那道筛, 被数成读者评论, 而且每次通道来回切都要把这一篇的行重写一遍。
            row["comment_role"] = "贴主"
        if old is not None and old.get("source") == source and all(old.get(k) == row[k] for k in _LC_MATERIAL) \
                and (source == SOURCE_RECORDS or old.get("comment_order") == order) \
                and not (old.get("observed_at") is None and row["observed_at"] is not None):
            # 库里已经是这样: 不重写 (observed_at 留第一次读到它的那一刻)。例外: 库里的时刻是空的 (这一行是在巡查没成功
            # 的那一轮入库的), 这一轮拿得准 → 往下走, 补上这一次, 之后不再动。
            continue
        if old is not None and row["comment_time"] is None:
            row["comment_time"] = old.get("comment_time")   # 这一轮没带发表时间: 以前记下的还是对的, 不拿空值盖掉
        if old is not None and row["observed_at"] is None:
            row["observed_at"] = old.get("observed_at")     # 这一轮拿不准时刻: 不拿空值盖掉以前记下的
        plan["upserts"].append(row)

    if source == SOURCE_DIGEST:
        keep = set(ids)
        plan["deletes"] = [c for c in old_digest if c not in keep]      # 快照变了: 不在新快照里的快照行删掉
    else:
        plan["deletes"] = old_digest                                    # 有明细了: 这一篇的快照行整套让位
    return plan


_LC_DELETE_CHUNK, _LC_WRITE_CHUNK = 100, 500


def apply_linkcheck_plans(sb, plans: list[dict], dry_run: bool) -> tuple[int, int]:
    """把一个项目的计划写进库: 先删、再插入 / 更新 (整项目攒成几批, 不是一篇一次请求)。回 (写了几行, 删了几行)。

    只碰 id 是 {note_id}_lc… 的行: 删的是计划里点了名的 id, 写的是 upsert (主键冲突就更新那一行)。
    任何一批失败都直接抛 (同 write_comments 的口径: 写失败 = 这次同步失败), 下一晚重跑会按库里的现状重新对一遍。"""
    deletes = [c for p in plans for c in p["deletes"]]
    upserts = [r for p in plans for r in p["upserts"]]
    if dry_run:
        if deletes or upserts:
            logger.info("[dry-run] 巡查来的评论: would upsert %d 行, delete %d 行", len(upserts), len(deletes))
        return len(upserts), len(deletes)
    tbl = lambda: sb.schema("truth_vault").table("comments")  # noqa: E731
    for i in range(0, len(deletes), _LC_DELETE_CHUNK):
        tbl().delete().in_("comment_id", deletes[i:i + _LC_DELETE_CHUNK]).execute()
    # 一级评论先于它下面的回复 (plan 里就是这个顺序); 分批也按这个顺序, 父行总是先到
    for i in range(0, len(upserts), _LC_WRITE_CHUNK):
        tbl().upsert(upserts[i:i + _LC_WRITE_CHUNK], on_conflict="comment_id").execute()
    return len(upserts), len(deletes)


def _sorted_comment_rows(rows: list[dict]) -> list[dict]:
    rows.sort(key=lambda r: (r.get("comment_order") is None,
                             r.get("comment_order") or 0,
                             r.get("comment_id") or ""))
    return rows


def fetch_project_comments_by_source(sb, project_id: str) -> tuple[dict[str, list[dict]], dict[str, list[dict]], bool]:
    """整个项目已入库的评论, 一次读, 分成两份: (运营贴的 by note, 巡查来的 by note, 库里有没有 source 这一列)。

    为什么每项目读一次 (2026-10-08 审计 A-07, D-092; 原 fetch_project_comments): 以前 write_comments 对**每一篇**调一次
    existing_comments —— fetch_all_pages 以空页终止, 一篇至少 2 次 HTTP, 再加重排 / 插入; 17 个 mapping 全在循环里, 每晚
    2.5–3k 篇、约 1 s 一篇, 随库线性涨。改成每项目读一次 (几页), 逐篇在内存里配对。翻页靠 fetch_all_pages: 一个项目的
    评论轻松过千, 裸 execute 会被 db-max-rows 钳到 1000。

    先带着 v1.27 的三列读; 库里没有这三列 (PostgREST 回「没有这一列」) → 按老的列再读一次, 全部算运营贴的 (那时
    库里也不可能有巡查来的行)。别的错照抛。每组按 comment_order 稳定排序 (同 existing_comments 的口径)。"""
    def read(cols: str) -> list[dict]:
        q = sb.schema("truth_vault").table("comments").select(cols).eq("project_id", project_id)
        return list(fetch_all_pages(q, order_by="comment_id"))
    try:
        rows, supported = read(_LINEAGE_COMMENT_COLS), True
    except Exception as exc:  # noqa: BLE001 —— 只吞「没有这一列」
        if not _is_missing_column_error(exc, LINEAGE_COLS):
            raise
        rows, supported = read(_BASE_COMMENT_COLS), False
    ops: dict[str, list[dict]] = {}
    lcs: dict[str, list[dict]] = {}
    for r in rows:
        (lcs if r.get("source") in LINKCHECK_SOURCES else ops).setdefault(r["note_id"], []).append(r)
    for group in list(ops.values()) + list(lcs.values()):
        _sorted_comment_rows(group)
    return ops, lcs, supported


def fetch_project_notes(sb, project_id: str) -> list[dict]:
    """项目里 raw_extra 不为空的 note (一次读, 翻页); 两个来源各自在内存里挑。"""
    q = (
        sb.schema("truth_vault")
        .table("notes")
        .select("note_id, project_id, raw_extra")
        .eq("project_id", project_id)
        .not_.is_("raw_extra", None)
    )
    return [r for r in fetch_all_pages(q, order_by="note_id") if isinstance(r.get("raw_extra"), dict)]


def has_operator_comment_text(raw: dict) -> bool:
    return bool(raw.get("_comment_text") or raw.get("_comment_text_persona"))


def fetch_notes_with_comments_text(sb, project_id: str) -> list[dict]:
    """Pull notes whose raw_extra has _comment_text but no comments rows yet."""
    q = (
        sb.schema("truth_vault")
        .table("notes")
        .select("note_id, project_id, raw_extra")
        .eq("project_id", project_id)
        .not_.is_("raw_extra", None)
    )
    rows = fetch_all_pages(q, order_by="note_id")
    # Filter client-side for the two raw_extra keys (PostgREST JSON
    # path filters on `not.is null` over deep paths is awkward).
    return [
        r for r in rows
        if isinstance(r.get("raw_extra"), dict) and has_operator_comment_text(r["raw_extra"])
    ]


def existing_comments(sb, note_id: str) -> list[dict]:
    """这条 note 已经存下来的评论(带内容), 按 comment_order 稳定排序。

    ⚠️ 原来这里只取 ``comment_id`` 的集合, 而配对是**按位置**做的 ——
    见 write_comments 的说明, 那正是 COR-013 的根因。要按内容配对就必须
    把内容读回来。

    ⚠️ **必须翻页。** PostgREST 的 ``db-max-rows`` 默认 1000, 裸 ``.execute()``
    会被服务端**静默钳到 1000** —— 一条爆款笔记的评论轻松过千。被钳掉的那些行
    在这里"不存在", 于是它们对应的评论会被当成新评论去 mint id; 而 id 是内容
    寻址的, mint 出来的正好就是那几行**已经占着的主键** → insert 抛 PK 冲突,
    这条 note 的同步就此断掉。顺带 vanished 那份报告也会把它们全列成"消失了"。

    本文件 17 行之前的 ``fetch_notes_with_comments_text`` 已经在用
    ``fetch_all_pages``(它的 docstring 专门讲了这个 1000 的零余量), 同一个文件
    里两种口径才是真正危险的地方。
    """
    # v1.27 之后库里还有巡查工具来的行 (source = linkcheck_*): 它们不参与运营这条路的配对和对账, 这里滤掉。
    # 只有 main 确认过库里有 source 这一列才多选它; 老调用 (不经 main) 和没迁移的库照原样读。
    lineage = _LINEAGE_SUPPORTED == [True]
    q = (
        sb.schema("truth_vault")
        .table("comments")
        .select("comment_id, content, comment_role, comment_order" + (", source" if lineage else ""))
        .eq("note_id", note_id)
    )
    rows = [r for r in fetch_all_pages(q, order_by="comment_id") if r.get("source") not in LINKCHECK_SOURCES]
    rows.sort(key=lambda r: (r.get("comment_order") is None,
                             r.get("comment_order") or 0,
                             r.get("comment_id") or ""))
    return rows


def _content_key(role: str, content: str) -> tuple[str, str]:
    """配对用的键。两端空白归一 —— 运营重新粘贴时行尾空格经常会变。"""
    return ((role or "").strip(), (content or "").strip())


def _minted_id(note_id: str, role: str, content: str, nth: int) -> str:
    """给**新**评论造一个内容寻址的 id。

    ``nth`` 区分同一条 (role, content) 的多次出现 —— 运营粘贴的文本里
    "好用""+1"这种一模一样的评论很常见, 光靠内容哈希会撞。

    ⚠️ 前缀刻意是 ``_h`` 而不是 ``_c``: 老行是 ``{note_id}_c{ordinal}``,
    两套必须不可能撞上。老行**不会**被改名(见 write_comments), 所以这里只管
    新造的。
    """
    h = hashlib.sha256("\u0000".join(_content_key(role, content)).encode("utf-8"))
    return f"{note_id}_h{h.hexdigest()[:12]}_{nth}"


def _next_free_id(note_id: str, role: str, content: str, taken: set[str]) -> str:
    """挑一个**还没被占**的 nth。

    ⚠️ 不能拿"这是源里第几次出现"当 nth。中间那条被硬删之后就会撞:
    ``_1/_2/_3`` 都在, 有人删掉 ``_2``, 而源里仍是三次出现 —— 配对认领
    ``_1`` 和 ``_3``(仅存的两行), 第三次出现算出 nth=3, mint 出来正好是
    **已经被认领的** ``_3`` → 整批 insert 撞主键失败, 那条缺的反而补不回来。
    实测复现: ``PK 冲突: n1_h9c0bc1c36c11_3``。(codex review)

    改成"往上找第一个空位": 只看 id 占没占, 与源里的位置无关。``taken`` 要
    同时包含**库里已有的**和**本次已经 mint 的**。
    """
    nth = 1
    while True:
        cid = _minted_id(note_id, role, content, nth)
        if cid not in taken:
            return cid
        nth += 1


def write_comments(
    sb,
    note_id: str,
    project_id: str,
    parsed: list[tuple[str, str]],
    dry_run: bool,
    vanished_log: Optional[list[dict]] = None,
    existing: Optional[list[dict]] = None,
) -> int:
    """Insert flat (no parent) comment rows. Returns count actually written.

    vanished_log (D-085): 给了就把本条 note「库里有、源里找不到」的行逐条追加进去 (含 kind:
    parser_change = 按新切法会被切开 / 剥前缀的旧行, source_removed = 其余)。只收集, 不删。

    existing (D-092): 这条 note 已入库的、运营贴的评论(fetch_project_comments_by_source 按项目读一次之后分给每篇的那一份)。
    不传就按 note 读一次 —— 老调用形状(ci COR-013 那步 / check_comment_parser)不变。

    ── 为什么按内容配对而不是按位置(跨库审计 2026-08-24 COR-013)──────────

    原来 ``comment_id = f"{note_id}_c{ordinal}"``, ordinal 是这条评论在**本次
    解析结果里的下标**, 且只 insert 不更新。源是运营手工粘贴的自由文本, 没有
    任何原生 comment id, 所以"第几条"就成了唯一身份。

    运营在**头部插一条**新评论, 后果实测如下(源 [A,B] → [X,A,B]):

        第一轮: _c1=A, _c2=B
        第二轮: _c1 已存在 → 跳过(X 就此丢失)
                _c2 已存在 → 跳过
                _c3 = B    → 当成新评论插进去

    也就是: **新评论静默丢失、旧评论被写成两条、每条的 comment_order 全错**。
    而随后的 LLM 楼层重建会基于这些行写 parent_comment_id —— 层级建在错的
    数据上, 之后再也没人对得回来。

    改成按 (role, content) 配对:
      · 能配上已有行 → **复用它原来的 comment_id**, 只在位置变了时更新
        comment_order。绝不改名 —— comments.parent_comment_id 是自引用外键,
        改名等于把已经重建好的楼层全打断;
      · 配不上 → 造一个内容寻址的新 id 插进去;
      · 已有行没被配上 → 说明它从源里消失了, **只报数不删**(见下)。

    ⚠️ **没有做软删**。comments 表没有 is_deleted / deleted_at 列, 加列是
       独立的一次 schema 迁移; 而且"从源里消失"要不要等于"删除"取决于运营
       的实际用法(粘贴时截断了一段 vs 真的删了评论), 那是产品判断。这次只
       把它数出来、log 出来, 让它从"完全看不见"变成"看得见"。集合对账那条
       在审计里是 COR-011, 单独处理。
    """
    if not parsed:
        return 0

    # ⚠️ dry-run 也要**真的读**已有行。读是没有副作用的, 而 dry-run 的全部价值
    #    就是"预览真跑会发生什么"。原来这里强行置空, 于是 dry-run 把每一条都算成
    #    新增: 已经同步过的 note 会报一堆并不会发生的 insert, 而重排和"从源里消失"
    #    这两份新增的报告在 dry-run 下**永远为空**。预览失真比没有预览更坏 ——
    #    人会照着它下判断。(codex review)
    rows = existing if existing is not None else existing_comments(sb, note_id)

    # (role, content) → 还没被认领的已有 id, 按 comment_order 排。同一段内容
    # 重复出现时先来先认领, 顺序稳定。
    available: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        available.setdefault(_content_key(r.get("comment_role", ""),
                                          r.get("content", "")), []).append(r)

    # 已经被占用的 id: 库里**全部**已有行 + 本次已经 mint 的。给 _next_free_id
    # 用 —— 只看"占没占", 不看"源里第几次出现"。
    taken: set[str] = {r["comment_id"] for r in rows}

    to_insert: list[dict] = []
    reorders: list[tuple[str, int]] = []      # (comment_id, 新的 comment_order)
    claimed: set[str] = set()

    for ordinal, (role, content) in enumerate(parsed, start=1):
        key = _content_key(role, content)

        pool = available.get(key) or []
        if pool:
            row = pool.pop(0)
            claimed.add(row["comment_id"])
            if row.get("comment_order") != ordinal:
                reorders.append((row["comment_id"], ordinal))
            continue

        new_id = _next_free_id(note_id, role, content, taken)
        taken.add(new_id)
        to_insert.append({
            "comment_id": new_id,
            "note_id": note_id,
            "project_id": project_id,
            "content": content,
            "comment_role": role,
            "comment_order": ordinal,
            "parent_comment_id": None,
            # leave: comment_intent, is_scripted, comment_type — LLM pass fills
            "is_pinned": False,
            "is_displayed": True,
            "created_at": _iso_now(),
        })

    vanished = [r for r in rows if r["comment_id"] not in claimed]
    if vanished:
        # 只报不删 —— 见 docstring。但**必须**看得见: 原来这种行是完全静默的。
        logger.warning(
            "note=%s 有 %d 条已入库的评论在本次源文本里找不到了(未删除, 仅报告): %s",
            note_id, len(vanished),
            [r["comment_id"] for r in vanished[:5]],
        )
        if vanished_log is not None:
            for r in vanished:
                vanished_log.append({
                    "note_id": note_id, "comment_id": r["comment_id"],
                    "comment_role": r.get("comment_role"), "content": r.get("content"),
                    "kind": "parser_change" if _changed_by_d085(r.get("content") or "") else "source_removed",
                })

    if dry_run:
        if to_insert:
            logger.info("[dry-run] would insert %d comments for %s "
                        "(first: role=%s, content=%r)",
                        len(to_insert), note_id,
                        to_insert[0]["comment_role"],
                        to_insert[0]["content"][:60])
        if reorders:
            logger.info("[dry-run] would fix comment_order on %d existing rows",
                        len(reorders))
        return len(to_insert)

    # 位置变了的先更新 —— 它不影响 comment_id, 但 comment_order 是楼层重建和
    # 展示的依据, 留着旧值等于留着一份错的顺序。
    #
    # ⚠️ 更新失败**必须让整次运行失败**。原来这里只 logger.exception 就接着往下
    #    插新行, 函数照常返回成功 —— 而 daily-sync 只看退出码, 于是: 新行进了库、
    #    旧行留着错的(甚至重复的) comment_order、工作流全绿、没有任何人被通知。
    #    这正是本轮审计 COR-008(指标写失败不计进 exit code)同一个形状, 只是换了
    #    个脚本。(codex review)
    #
    #    先把所有的都试一遍再抛: 一次瞬时错误不该掩盖后面还有多少条也失败了,
    #    日志里要看得到全貌。
    failed_reorders: list[str] = []
    for comment_id, new_order in reorders:
        try:
            (
                sb.schema("truth_vault")
                .table("comments")
                .update({"comment_order": new_order})
                .eq("comment_id", comment_id)
                .execute()
            )
        except Exception:
            logger.exception("comment_order 更新失败 comment_id=%s", comment_id)
            failed_reorders.append(comment_id)
    if failed_reorders:
        raise RuntimeError(
            f"note={note_id}: {len(failed_reorders)}/{len(reorders)} 条 comment_order "
            f"没更新成功 {failed_reorders[:5]} —— 这些行的顺序现在是错的, "
            "楼层重建会建在错的顺序上。本次同步按失败处理, 不再插入新行。")

    if not to_insert:
        return 0
    (
        sb.schema("truth_vault")
        .table("comments")
        .insert(to_insert)
        .execute()
    )
    return len(to_insert)


def collect_cleared_vanished(sb, cleared: list, unparseable: set, vanished_log: list) -> None:
    """库里有评论、但本次一条都没解析出来的 note → 它的每条已入库评论逐条追加进 vanished_log。

    每行带 note_cleared = source_empty(两个源字段都空, fetch 时就被滤掉了)或 unparseable(字段非空、
    按现在的切法一条都解析不出来); kind 的口径同 write_comments (parser_change / source_removed)。只收集, 不删。"""
    for note_id in cleared:
        why = "unparseable" if note_id in unparseable else "source_empty"
        for r in existing_comments(sb, note_id):
            vanished_log.append({
                "note_id": note_id, "comment_id": r["comment_id"],
                "comment_role": r.get("comment_role"), "content": r.get("content"),
                "kind": "parser_change" if _changed_by_d085(r.get("content") or "") else "source_removed",
                "note_cleared": why,
            })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project_id")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--vanished-out", default="",
                        help="把「库里有、源里找不到」的评论逐条写成 jsonl (D-085 一次性清理用; 只写文件, 不删库)")
    args = parser.parse_args()

    # ── 夜跑跳过 on_demand 项目 (D-047 的闸以前只在入库 / essence / curate 三步生效; 评论步是裸循环, 审计 A-07, D-092)
    # 最重的随贴评论块(NUC / NRT / HXZ 的素人评论)恰恰都在 on_demand 项目里, 内容从不变, 每晚全量重解析一遍。
    # 判据与 sync_feishu 同一份: TV_SCHEDULED_RUN=true 且 sync_interval=on_demand 才跳; 手动 / 本地照跑。
    sync_interval = ((load_mapping(args.project_id).get("sync_config") or {}).get("sync_interval"))
    if skip_on_demand_on_cron(sync_interval, os.environ.get("TV_SCHEDULED_RUN") == "true"):
        logger.info("%s 是 on_demand 项目, 定时跑跳过评论步(手动 Run workflow / 本地跑不跳)", args.project_id)
        return 0

    sb = get_supabase_client()
    # note 每项目读一次, 两个来源各自挑 (运营贴的随贴评论 / 巡查工具看到的评论区第一页, D-155)。
    all_notes = fetch_project_notes(sb, args.project_id)
    notes = [r for r in all_notes if has_operator_comment_text(r["raw_extra"])]
    lc_notes = [r for r in all_notes if has_linkcheck_cells(r["raw_extra"])]
    if args.limit:
        notes = notes[: args.limit]
        lc_notes = lc_notes[: args.limit]
    logger.info("Found %d notes with raw_extra._comment_text(_persona) for %s",
                len(notes), args.project_id)
    # 已入库评论每项目读一次、按 note 分组, 逐篇在内存里配对 (D-092; 以前每篇读一次, ≥2 次 HTTP/篇)。
    # by_note 只有运营贴的行; 巡查来的行 (source = linkcheck_*) 单独一份, 不进下面的配对和「找不到了」对账。
    by_note, lc_by_note, lineage = fetch_project_comments_by_source(sb, args.project_id)
    _LINEAGE_SUPPORTED[:] = [lineage]

    stats = {"notes_processed": 0, "comments_written": 0, "skipped_empty": 0,
             "notes_source_cleared": 0, "vanished_parser_change": 0, "vanished_other": 0,
             "reader_notes": 0, "reader_rows_written": 0, "reader_rows_deleted": 0, "reader_unreadable": 0}
    covered: set[str] = set()
    unparseable: set[str] = set()         # 源字段非空、但一条都解析不出来的 note
    vanished_log: list[dict] = []
    for note in notes:
        raw = note.get("raw_extra") or {}
        text_main = raw.get("_comment_text") or ""
        text_persona = raw.get("_comment_text_persona") or ""
        combined = "\n".join([text_main, text_persona]).strip()
        parsed = list(parse_comment_text(combined))
        if not parsed:
            stats["skipped_empty"] += 1
            unparseable.add(note["note_id"])
            continue
        covered.add(note["note_id"])
        written = write_comments(
            sb, note["note_id"], note["project_id"], parsed, args.dry_run,
            vanished_log=vanished_log, existing=by_note.get(note["note_id"], []),
        )
        stats["notes_processed"] += 1
        stats["comments_written"] += written

    # ── 整块源文本被清空的 note ────────────────────────────────────────────
    # write_comments 里的 vanished 报告只看得见**部分**消失: 它是拿本次解析结果
    # 去比已有行的。运营把两个源字段整个清空时, 这条 note 会被
    # fetch_notes_with_comments_text 直接滤掉(它要求至少有一个字段非空), 而
    # write_comments 对空解析又是早返回 —— 于是**整条 note 的评论全部留在库里,
    # 一句话都不会说**。恰恰是"全清"这种最该被看见的情况完全隐身。(codex review)
    #
    # 只报不删, 口径同 write_comments: comments 表没有软删列, 而"源里没了"要不要
    # 等于"删除"是产品判断(粘贴时截断了 vs 真的删了)。这里只让它可见。
    # D-085 起这些 note 的每一条已入库评论也进 vanished_log (带 note_cleared), 所以
    # --vanished-out 的名单要等对账做完才写 —— 以前先写文件、后对账, 整条清空 / 新切法下
    # 整条解析不出来的 note 在名单里一行都没有, 清理时拿不到这些 id (codex review on #161)。
    #
    # ⚠️ 带 --limit 时不做这个对账 —— 那时 covered 本来就是不完整的, 拿它比会把
    #    没轮到处理的 note 全report成"源被清空了"。同 COR-011 的口径: 部分扫描
    #    不产出对账结论。
    if args.limit:
        logger.info("带 --limit, 跳过「源被清空」对账(本次覆盖不完整, 比了会误报); "
                    "--vanished-out 的名单里也就没有整条被清空的 note")
    else:
        try:
            # 哪些 note 库里有评论: 开头那次项目级读已经拿到了, 不再查第二遍 (D-092)
            with_rows = set(by_note)
            cleared = sorted(with_rows - covered)
            collect_cleared_vanished(sb, cleared, unparseable, vanished_log)
            stats["notes_source_cleared"] = len(cleared)
            if cleared:
                logger.warning(
                    "%d 条 note 库里有评论、但本次源文本里一条都解析不出来"
                    "(未删除, 仅报告): %s", len(cleared), cleared[:5])
        except Exception:
            # 对账失败不该把同步判失败 —— 它是**附加的**可见性, 不是这个脚本的
            # 主职责。但也不能静默: 报出来, 并在 stats 里留 -1 标明"这次没算成"。
            logger.exception("「源被清空」对账查询失败")
            stats["notes_source_cleared"] = -1

    # ── 巡查工具看到的评论区第一页 (D-155) ────────────────────────────────────────
    # 和上面那条路互不相干: 只读 / 只写 source = linkcheck_* 的行。库里没有 source 这一列 (v1.27 没跑) 就整段不走。
    if lc_notes and not lineage:
        warn_missing_migration_once(
            "comments.source",
            f"{args.project_id}: {len(lc_notes)} 篇带巡查工具的评论区快照 / 明细, 但 truth_vault.comments 还没有 source / "
            f"is_truncated / observed_at 三列 (owner 在 SQL editor 跑 {LINEAGE_MIGRATION} 之前都是这样): 这次只解析运营贴的"
            "随贴评论, 和以前一样; 读者评论不入库。", log=logger)
    elif lc_notes:
        plans = [plan_linkcheck_rows(n, lc_by_note.get(n["note_id"], [])) for n in lc_notes]
        for n, p in zip(lc_notes, plans):
            if p["note"]:
                stats["reader_unreadable"] += 1
                logger.warning("note=%s %s", n["note_id"], p["note"])
        stats["reader_notes"] = sum(1 for p in plans if p["source"])
        stats["reader_rows_written"], stats["reader_rows_deleted"] = apply_linkcheck_plans(sb, plans, args.dry_run)

    # D-085: 按来由分开数。parser_change 是改了切法 / 剥了【…】前缀之后配不上的旧行, 同步之后要 owner
    # 清一次 (见模块头); source_removed 是运营在源里删了的。都只报不删。
    stats["vanished_parser_change"] = sum(1 for v in vanished_log if v["kind"] == "parser_change")
    stats["vanished_other"] = len(vanished_log) - stats["vanished_parser_change"]
    if stats["vanished_parser_change"]:
        logger.warning("%d 条旧评论是 D-085 改切法 / 剥前缀之后配不上的 (未删除); 清理见模块头 "
                       "「D-085 一次性清理」, 用 --dry-run --vanished-out 拿全名单",
                       stats["vanished_parser_change"])
    if args.vanished_out:
        with open(args.vanished_out, "w", encoding="utf-8") as f:
            for v in vanished_log:
                f.write(json.dumps(v, ensure_ascii=False) + "\n")
        logger.info("vanished 名单 %d 行 → %s", len(vanished_log), args.vanished_out)

    logger.info("Done: %s", json.dumps(stats, ensure_ascii=False))
    # 对账没算成(-1)要非零: 它是"源被清空的 note 全部隐身"这种最该被看见的情况唯一的出口,
    # 以前 return 0 → daily-sync 那步绿、看门狗绿, 对账挂了没有任何人知道 (审计 A-07, D-092)。
    return 0 if stats["notes_source_cleared"] >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
