"""
compliance_words.py —— 全局禁词表 (prompts/forbidden_words_v1.yaml) 的唯一读法。D-084 B3。

    from compliance_words import find_hits
    find_hits("这是最好的选择, 最近很火")   → [Hit(word='最', at=2, text='最好')]

    python compliance_words.py --text "…"        # 打印命中
    python compliance_words.py --sql-regex        # 每个词一条 PostgreSQL 正则 (量生产命中面用)

口径 (与 yaml 一致, 守卫 9 钉着):
  · match 是原样子串; except_followed_by 里的字紧跟其后时不算 (「最近」不算, 「最好」算)。
  · 词在文本末尾、后面没有字 → 算 (「这个最」也是绝对化的省略写法, 宁可多报)。
  · aliases 与 match 同规则。
  · 命中位置按字符下标, 供人核对。不做分词, 不猜语义 —— 只是子串 + 例外表。
挡不住什么: 「最」+ 例外字开头的绝对化 (「最上乘」会被「上」放行); 拆开写的 (「最 好」); 同义改写 (「顶级」)。
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

WORDS_PATH = Path(__file__).resolve().parent.parent / "prompts" / "forbidden_words_v1.yaml"


@dataclass(frozen=True)
class Hit:
    word: str        # yaml 里的 match (别名命中也归到主词)
    at: int          # 字符下标
    text: str        # 命中处的原样片段 (词 + 后一个字, 方便人看)


def load_words(path: Path | str = WORDS_PATH) -> dict:
    raw = Path(path).read_bytes()
    data = yaml.safe_load(raw)
    data["_sha256"] = hashlib.sha256(raw).hexdigest()
    return data


def _compile(entry: dict) -> list[tuple[str, re.Pattern]]:
    forms = [entry["match"]] + list(entry.get("aliases") or [])
    exc = entry.get("except_followed_by") or []
    tail = f"(?![{''.join(re.escape(c) for c in exc)}])" if exc else ""
    return [(entry["match"], re.compile(re.escape(f) + tail)) for f in forms]


def find_hits(text: str, words: dict | None = None) -> list[Hit]:
    words = words or load_words()
    hits: list[Hit] = []
    for entry in words["words"]:
        for word, pat in _compile(entry):
            for m in pat.finditer(text or ""):
                hits.append(Hit(word=word, at=m.start(), text=text[m.start(): m.end() + 1]))
    return sorted(hits, key=lambda h: (h.at, h.word))


def sql_regex(words: dict | None = None) -> dict[str, str]:
    """每个词一条 PostgreSQL 正则 (~ 运算符用), 语义同 find_hits: 别名用 |, 例外用负向前瞻。"""
    words = words or load_words()
    out = {}
    for entry in words["words"]:
        forms = [entry["match"]] + list(entry.get("aliases") or [])
        exc = entry.get("except_followed_by") or []
        alt = "(" + "|".join(re.escape(f) for f in forms) + ")"
        tail = f"(?![{''.join(exc)}])" if exc else ""
        out[entry["match"]] = alt + tail
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--text", default=None)
    ap.add_argument("--file", type=Path, default=None)
    ap.add_argument("--sql-regex", action="store_true")
    args = ap.parse_args()
    words = load_words()
    if args.sql_regex:
        for w, rx in sql_regex(words).items():
            print(f"{w}\t{rx}")
        return 0
    text = args.text if args.text is not None else (args.file.read_text(encoding="utf-8") if args.file else sys.stdin.read())
    hits = find_hits(text, words)
    for h in hits:
        print(f"{h.at}\t{h.word}\t{h.text}")
    print(f"{len(hits)} hits · 禁词表 {words['version']} sha {words['_sha256'][:12]}")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
