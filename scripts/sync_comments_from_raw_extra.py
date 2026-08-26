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

  Pattern B (separator-delimited block):
    用户A | 第一条
    用户B | 第二条

Hierarchy reconstruction (parent_comment_id) is NOT inferred from text
patterns — it requires LLM analysis (D-022 / Q21). This script writes a
FLAT comments table (all parent_comment_id NULL); LLM楼层重建 is a Sprint 2
follow-up. comment_role defaults to '素人' unless the operator prefixed
"贴主:" / "运营:".

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


def _parse_comment_line(line: str) -> Optional[tuple[str, str]]:
    """Extract (role, content) from a single comment line.

    Returns None if the line is blank / pure whitespace / pure number.
    Recognized shapes:
        "1. 用户A: hello"           → ('素人', 'hello')         [strips number + name]
        "贴主: thanks"               → ('贴主', 'thanks')
        "用户A | hello"              → ('素人', 'hello')
        "hello"                      → ('素人', 'hello')
    """
    s = line.strip()
    if not s:
        return None
    if re.fullmatch(r"\d+[.、]?", s):
        return None  # numbering remnant

    # Strip leading "1. " / "1、" / "(1)"
    s = re.sub(r"^\(?\d+\)?[.、]\s*", "", s)

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
    """Yield (role, content) for each parseable line in a comment block."""
    if not text:
        return
    for line in text.splitlines():
        parsed = _parse_comment_line(line)
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
) -> int:
    """Insert flat (no parent) comment rows. Returns count actually written.

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project_id")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    sb = get_supabase_client()
    notes = fetch_notes_with_comments_text(sb, args.project_id)
    if args.limit:
        notes = notes[: args.limit]
    logger.info("Found %d notes with raw_extra._comment_text(_persona) for %s",
                len(notes), args.project_id)

    stats = {"notes_processed": 0, "comments_written": 0, "skipped_empty": 0,
             "notes_source_cleared": 0}
    covered: set[str] = set()
    for note in notes:
        raw = note.get("raw_extra") or {}
        text_main = raw.get("_comment_text") or ""
        text_persona = raw.get("_comment_text_persona") or ""
        combined = "\n".join([text_main, text_persona]).strip()
        parsed = list(parse_comment_text(combined))
        if not parsed:
            stats["skipped_empty"] += 1
            continue
        covered.add(note["note_id"])
        written = write_comments(
            sb, note["note_id"], note["project_id"], parsed, args.dry_run
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
    #
    # ⚠️ 带 --limit 时不做这个对账 —— 那时 covered 本来就是不完整的, 拿它比会把
    #    没轮到处理的 note 全report成"源被清空了"。同 COR-011 的口径: 部分扫描
    #    不产出对账结论。
    if args.limit:
        logger.info("带 --limit, 跳过「源被清空」对账(本次覆盖不完整, 比了会误报)")
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

    logger.info("Done: %s", json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
