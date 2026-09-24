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

Usage:
    python sync_comments_from_raw_extra.py NUC_phase1
    python sync_comments_from_raw_extra.py NUC_phase1 --dry-run --limit 5
    python sync_comments_from_raw_extra.py NUC_phase1 --dry-run --vanished-out vanished.jsonl   # D-085 清理用
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from typing import Iterator, Optional

from _common import (
    fetch_all_pages,
    get_supabase_client,
    setup_logger,
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
        if isinstance(r.get("raw_extra"), dict)
        and (r["raw_extra"].get("_comment_text") or r["raw_extra"].get("_comment_text_persona"))
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
    q = (
        sb.schema("truth_vault")
        .table("comments")
        .select("comment_id, content, comment_role, comment_order")
        .eq("note_id", note_id)
    )
    rows = list(fetch_all_pages(q, order_by="comment_id"))
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
) -> int:
    """Insert flat (no parent) comment rows. Returns count actually written.

    vanished_log (D-085): 给了就把本条 note「库里有、源里找不到」的行逐条追加进去 (含 kind:
    parser_change = 按新切法会被切开 / 剥前缀的旧行, source_removed = 其余)。只收集, 不删。

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
    rows = existing_comments(sb, note_id)

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

    sb = get_supabase_client()
    notes = fetch_notes_with_comments_text(sb, args.project_id)
    if args.limit:
        notes = notes[: args.limit]
    logger.info("Found %d notes with raw_extra._comment_text(_persona) for %s",
                len(notes), args.project_id)

    stats = {"notes_processed": 0, "comments_written": 0, "skipped_empty": 0,
             "notes_source_cleared": 0, "vanished_parser_change": 0, "vanished_other": 0}
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
            vanished_log=vanished_log,
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
            q = (
                sb.schema("truth_vault")
                .table("comments")
                .select("note_id")
                .eq("project_id", args.project_id)
            )
            with_rows = {r["note_id"] for r in fetch_all_pages(q, order_by="note_id")}
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
