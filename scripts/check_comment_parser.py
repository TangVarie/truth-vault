"""
check_comment_parser.py —— 随贴评论解析器的单测 (原 ci.yml 内联的 6 条 + D-085 的同行切分 / 【…】标签)。

    cd scripts && python check_comment_parser.py

D-085 之前这 6 条内联在 ci.yml 的 heredoc 里; 要加用例, 而 ci.yml 离体积棘轮只剩约 1 KB, 按 D-075
挪进来, ci.yml 只留一行调用。原 6 条一字未改 (CASES_BASE)。

守得住什么:
  · 原 6 条: 行首编号 / 贴主前缀 / 竖线分隔 / 裸行 / 编号残行 / 全角冒号。
  · Pattern A 同一行写了好几条 (「 7. … 8. …」, judge 仓 33 条样本里 4 条) → 切开; 编号要连号、要接得上
    行首编号, 否则整行不切 (一条评论里的「1、便宜 2、好用」不切); 「2.5 元」这种小数不切。
  · 【素人评论】【贴主回复】【素人回复】等运营标签: 剥掉, 并据此定 comment_role (贴主回复 → 贴主);
    认不出的【…】原样留着; 标签后的冒号不再被当成「名字: 内容」切掉。
  · 反证: 同样的文本只按换行切 (改之前的做法) 就只有一条 —— 用例真的依赖二次切分。
  · 切法变了之后的迁移形状 (write_comments + 假库): 旧的并行行 / 带标签的旧行被记进 vanished_log、
    kind = parser_change, 不删; 新切出的行以新 id 插入; 运营真删的那条是 source_removed。
  · 整条 note 源被清空 / 新切法下整条解析不出来 (collect_cleared_vanished): 它的每条已入库评论也进 vanished_log,
    带 note_cleared; --vanished-out 在对账之后才写, 名单里有它们。
挡不住什么:
  · 没有行首编号的一行里, 正文自带从 2 起的连号列举 (「有三点：1、便宜 2、好用 3、方便」) 仍会被切开。
  · 编号 ≥ 100 的行 (同行切分只认 1–2 位编号) 不切。
  · 标签写在编号前面 (【素人评论】7. …) 不认。
"""

from __future__ import annotations

import sys

import sync_comments_from_raw_extra as M
from sync_comments_from_raw_extra import parse_comment_text

# ── 原 ci.yml「Comment parser unit tests」那 6 条, 原样 ──
CASES_BASE = [
    ("1. 用户A: 第一条\n2. 用户B: 第二条",
     [("素人", "第一条"), ("素人", "第二条")]),
    ("贴主: 谢谢姐妹\n素人小红: 好用吗",
     [("贴主", "谢谢姐妹"), ("素人", "好用吗")]),
    ("用户A | 第一条\n用户B | 第二条",
     [("素人", "第一条"), ("素人", "第二条")]),
    ("好用\n不好用",
     [("素人", "好用"), ("素人", "不好用")]),
    ("\n1.\n用户: 内容\n\n",
     [("素人", "内容")]),
    ("贴主:感谢",
     [("贴主", "感谢")]),
]

# ── D-085 ──
MERGED = ("6. 同款细心妈！我给娃吃啥药之前都得自己先尝一口味道。 7. 这个喷头设计确实比以前那种老式的要舒服很多。"
          " 8. 娃怕喷鼻子主要是怕那种冲鼻子的感觉，温和一点他们就不抗拒了。 9. 微微低头往外侧喷对吧？今晚回家就试试新姿势。")
CASES_D085 = [
    # 同一行 6–9 四条 → 四条
    (MERGED,
     [("素人", "同款细心妈！我给娃吃啥药之前都得自己先尝一口味道。"),
      ("素人", "这个喷头设计确实比以前那种老式的要舒服很多。"),
      ("素人", "娃怕喷鼻子主要是怕那种冲鼻子的感觉，温和一点他们就不抗拒了。"),
      ("素人", "微微低头往外侧喷对吧？今晚回家就试试新姿势。")]),
    # 行首没编号 (前一行带过来的), 同行 7–8 连号 → 切; 顿号编号也认
    ("5. 挂个专家号确实有用\n那个海盐水洗鼻哭得像家暴现场。 7、我也是！纯纯浪费钱。 8、听劝了姐妹",
     [("素人", "挂个专家号确实有用"), ("素人", "那个海盐水洗鼻哭得像家暴现场。"),
      ("素人", "我也是！纯纯浪费钱。"), ("素人", "听劝了姐妹")]),
    # 一条评论里的列举: 行首 5, 里面 2、3 接不上 → 整行不切
    ("5. 有三点：1、便宜 2、好用 3、方便",
     [("素人", "1、便宜 2、好用 3、方便")]),       # (「有三点：」被当名字切掉是原来就有的冒号拆法, 不在本次范围)
    # 小数不切 (第二条没有行首编号、2.5 / 3.5 又恰好「连号」—— 只有 (?!\d) 挡得住它)
    ("3. 只要 2.5 元 真香 12.5 也行\n便宜的 2.5 元 贵的 3.5 元",
     [("素人", "只要 2.5 元 真香 12.5 也行"), ("素人", "便宜的 2.5 元 贵的 3.5 元")]),
    # 跳号不切 (7 之后是 9)
    ("6. 甲 7. 乙 9. 丙",
     [("素人", "甲 7. 乙 9. 丙")]),
    # 运营标签定角色, 且剥掉
    ("1. 【素人评论】放心，完全不痛！\n2. 【贴主回复】真的不会扎破皮吗？\n3. 【素人回复】不会的：针尖极细",
     [("素人", "放心，完全不痛！"), ("贴主", "真的不会扎破皮吗？"), ("素人", "不会的：针尖极细")]),
    ("【贴主回复】谢谢姐妹", [("贴主", "谢谢姐妹")]),
    ("【运营】已私信", [("运营", "已私信")]),
    # 同行 + 标签一起
    ("1. 【素人评论】好用 2. 【贴主回复】谢谢 3. 【路人】路过",
     [("素人", "好用"), ("贴主", "谢谢"), ("路人", "路过")]),
    # 认不出的标签不动; 只有标签没内容的行跳过
    ("【置顶】欢迎来问\n【贴主回复】", [("素人", "【置顶】欢迎来问")]),
]


def check_cases() -> None:
    failed = []
    for i, (text, expected) in enumerate(CASES_BASE + CASES_D085, 1):
        actual = list(parse_comment_text(text))
        if actual != expected:
            failed.append(i)
            print(f"  case {i}: FAIL\n    expected: {expected}\n    got:      {actual}")
        else:
            print(f"  case {i}: ok")
    if failed:
        raise SystemExit(f"\n{len(failed)} parser test(s) failed: {failed}")
    # 反证: 只按换行切 (改之前) 这行就只有一条 —— 用例靠的确实是二次切分
    old = [M._parse_comment_line(ln) for ln in MERGED.splitlines()]
    assert len([x for x in old if x]) == 1 and len(list(parse_comment_text(MERGED))) == 4
    # 反证: 标签不认的话贴主回复会落成素人、正文带着【贴主回复】
    assert M._BRACKET_ROLE_RE.match("【贴主回复】x") and not M._BRACKET_ROLE_RE.match("【置顶】x")
    print(f"  ✓ {len(CASES_BASE)} 条原用例 + {len(CASES_D085)} 条 D-085 用例全过; 只按换行切会并成 1 条 (反证)")


class _FakeSB:
    """与 ci.yml COR-013 那步同一个假件的最小版: select 按 comment_order 排, insert 按主键去重。"""

    def __init__(self, rows=()):
        self.rows = [dict(r) for r in rows]
        self._op = None

    def schema(self, _): return self
    def table(self, _): return self
    def select(self, *a): self._op = "select"; self._rng = None; return self
    def eq(self, k, v): self._eq = (k, v); return self
    def order(self, col): return self
    def range(self, a, b): self._rng = (a, b); return self
    def update(self, patch): self._op = "update"; self._patch = patch; return self

    def insert(self, rows):
        ids = {r["comment_id"] for r in self.rows}
        for r in rows:
            assert r["comment_id"] not in ids, f"主键冲突 {r['comment_id']}"
            ids.add(r["comment_id"])
        self.rows.extend(rows)
        self._op = "insert"
        return self

    def execute(self):
        if self._op == "select":
            data = sorted((dict(r) for r in self.rows), key=lambda r: r.get("comment_id") or "")
            if self._rng is not None:
                data = data[self._rng[0]:self._rng[1] + 1]
            return type("R", (), {"data": data})()
        if self._op == "update":
            for r in self.rows:
                if r["comment_id"] == self._eq[1]:
                    r.update(self._patch)
        return type("R", (), {"data": self.rows})()


def check_migration_shape() -> None:
    """改切法之后第一次同步长什么样: 旧行留着并被点名 (parser_change), 新行插入, 不删。"""
    note, proj = "p_note1", "p"
    old = [  # 老解析器写进库的三行: 一条正常、一条并行、一条带标签被当成素人
        {"comment_id": "p_note1_c1", "content": "挂个专家号确实有用", "comment_role": "素人", "comment_order": 1},
        {"comment_id": "p_note1_c2", "content": MERGED[3:], "comment_role": "素人", "comment_order": 2},
        {"comment_id": "p_note1_c3", "content": "【贴主回复】真的不会扎破皮吗？", "comment_role": "素人", "comment_order": 3},
        {"comment_id": "p_note1_c4", "content": "运营后来删掉的一条", "comment_role": "素人", "comment_order": 4},
    ]
    src = "5. 挂个专家号确实有用\n" + MERGED + "\n10. 【贴主回复】真的不会扎破皮吗？"
    parsed = list(parse_comment_text(src))
    assert len(parsed) == 6, parsed
    sb = _FakeSB(old)
    log: list[dict] = []
    n = M.write_comments(sb, note, proj, parsed, dry_run=False, vanished_log=log)
    assert n == 5, f"应插 5 条新行 (4 条拆开的 + 1 条去了标签的), 实际 {n}"
    assert len(sb.rows) == 9, "旧行一条都不该删"
    kinds = {v["comment_id"]: v["kind"] for v in log}
    assert kinds == {"p_note1_c2": "parser_change", "p_note1_c3": "parser_change", "p_note1_c4": "source_removed"}, kinds
    assert next(r for r in sb.rows if r["content"] == "真的不会扎破皮吗？")["comment_role"] == "贴主"
    # 不带 vanished_log 照旧能跑 (COR-013 那步的调用形状), 且重跑是 no-op
    assert M.write_comments(sb, note, proj, parsed, dry_run=False) == 0
    # dry-run 也收集得到 (清理就是靠 --dry-run --vanished-out 拿名单)
    log2: list[dict] = []
    M.write_comments(sb, note, proj, parsed, dry_run=True, vanished_log=log2)
    assert {v["comment_id"] for v in log2} == set(kinds), log2
    print("  ✓ 迁移形状: 新切出的 5 条插入、旧的 4 条一条不删; 并行行 / 带标签的旧行记 parser_change, 运营删的记 source_removed; dry-run 同样收得到")


class _FilterSB(_FakeSB):
    """select 时按 eq 过滤 (对账要按 project 查、按 note 取已有行)。"""

    def select(self, *a):
        self._eq = None
        return super().select(*a)

    def execute(self):
        if self._op == "select" and self._eq is not None:
            k, v = self._eq
            keep, self.rows = self.rows, [r for r in self.rows if r.get(k) == v]
            try:
                return super().execute()
            finally:
                self.rows = keep
        return super().execute()


def check_cleared_notes_in_vanished() -> None:
    """整条 note 被清空 / 新切法下整条解析不出来: 它的每一条已入库评论都要进 vanished 名单 (codex review on #161)。"""
    rows = [
        {"comment_id": "p_a_c1", "note_id": "p_a", "project_id": "p", "content": "还在源里的一条", "comment_role": "素人", "comment_order": 1},
        {"comment_id": "p_b_c1", "note_id": "p_b", "project_id": "p", "content": "运营清空了源", "comment_role": "素人", "comment_order": 1},
        {"comment_id": "p_b_c2", "note_id": "p_b", "project_id": "p", "content": "【贴主回复】带标签的旧行", "comment_role": "素人", "comment_order": 2},
        {"comment_id": "p_c_c1", "note_id": "p_c", "project_id": "p", "content": "源还在但解析不出来", "comment_role": "素人", "comment_order": 1},
        {"comment_id": "q_x_c1", "note_id": "q_x", "project_id": "q", "content": "别的项目", "comment_role": "素人", "comment_order": 1},
    ]
    sb = _FilterSB(rows)
    log: list[dict] = []
    M.collect_cleared_vanished(sb, ["p_b", "p_c"], unparseable={"p_c"}, vanished_log=log)
    got = {(v["comment_id"], v["kind"], v["note_cleared"]) for v in log}
    assert got == {("p_b_c1", "source_removed", "source_empty"), ("p_b_c2", "parser_change", "source_empty"),
                   ("p_c_c1", "source_removed", "unparseable")}, got
    assert len(sb.rows) == 5, "只收集, 一行都不删"
    print("  ✓ 整条清空 / 整条解析不出来的 note: 每条已入库评论都进 vanished 名单 (带 note_cleared), 别的 note 不混进来, 不删")


def main() -> int:
    check_cases()
    check_migration_shape()
    check_cleared_notes_in_vanished()
    print("✓ 评论解析器 (原 6 条 + D-085): 全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
