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

Usage:
    python sync_comments_from_raw_extra.py NUC_phase1
    python sync_comments_from_raw_extra.py NUC_phase1 --dry-run --limit 5
"""

from __future__ import annotations

import argparse
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
    rows = fetch_all_pages(q)
    # Filter client-side for the two raw_extra keys (PostgREST JSON
    # path filters on `not.is null` over deep paths is awkward).
    return [
        r for r in rows
        if isinstance(r.get("raw_extra"), dict)
        and (r["raw_extra"].get("_comment_text") or r["raw_extra"].get("_comment_text_persona"))
    ]


def existing_comment_ids(sb, note_id: str) -> set[str]:
    res = (
        sb.schema("truth_vault")
        .table("comments")
        .select("comment_id")
        .eq("note_id", note_id)
        .execute()
    )
    return {r["comment_id"] for r in (res.data or [])}


def write_comments(
    sb,
    note_id: str,
    project_id: str,
    parsed: list[tuple[str, str]],
    dry_run: bool,
) -> int:
    """Insert flat (no parent) comment rows. Returns count actually written."""
    if not parsed:
        return 0
    existing = set() if dry_run else existing_comment_ids(sb, note_id)
    to_insert = []
    for ordinal, (role, content) in enumerate(parsed, start=1):
        comment_id = f"{note_id}_c{ordinal}"
        if comment_id in existing:
            continue
        to_insert.append({
            "comment_id": comment_id,
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
    if not to_insert:
        return 0
    if dry_run:
        logger.info("[dry-run] would insert %d comments for %s "
                    "(first: role=%s, content=%r)",
                    len(to_insert), note_id,
                    to_insert[0]["comment_role"],
                    to_insert[0]["content"][:60])
        return len(to_insert)
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

    stats = {"notes_processed": 0, "comments_written": 0, "skipped_empty": 0}
    for note in notes:
        raw = note.get("raw_extra") or {}
        text_main = raw.get("_comment_text") or ""
        text_persona = raw.get("_comment_text_persona") or ""
        combined = "\n".join([text_main, text_persona]).strip()
        parsed = list(parse_comment_text(combined))
        if not parsed:
            stats["skipped_empty"] += 1
            continue
        written = write_comments(
            sb, note["note_id"], note["project_id"], parsed, args.dry_run
        )
        stats["notes_processed"] += 1
        stats["comments_written"] += written

    logger.info("Done: %s", json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
