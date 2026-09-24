"""
check_compliance_words.py —— 守卫 9 (D-084 B3): 禁词表的读法钉住口径, 反证都红。

    cd scripts && python check_compliance_words.py

守得住: 7 个词都在表里; 「最」只拦绝对化、时间/方位用法放行; 「第一」放行序数; 100% 的全角/中文写法;
  命中位置正确; find_hits 与 sql_regex 在同一批句子上结论一致 (Python re 与 PG 正则同语义, 本地用 re 模拟 PG);
  反证: 把例外表清空 → 「最近」被拦; 把 aliases 去掉 → 「百分百」漏网。
挡不住: 见 compliance_words.py 顶部。
"""

from __future__ import annotations

import copy
import re
import sys

import compliance_words as cw

W = cw.load_words()
assert W["version"] == "fw-v1" and W["scope"] == "global"
assert [e["match"] for e in W["words"]] == ["最", "第一", "100%", "根治", "治愈", "空窗", "绝对"], "7 个词, 顺序照 owner 给的"

CASES = [
    # (文本, 期望命中的主词列表)
    ("这是最好的选择", ["最"]),
    ("最近很火, 最后一次, 最终还是买了, 最初不信", []),
    ("最有效的方法就是最安全的", ["最", "最"]),
    ("第一次跑半马, 第一天就废了", []),
    ("国产第一品牌, 销量第一", ["第一", "第一"]),          # 「第一」在句末 (后面是标点/没有字) 也算
    ("有效率 100%", ["100%"]),
    ("百分百有效, １００％放心", ["100%", "100%"]),
    ("一个月根治, 彻底治愈", ["根治", "治愈"]),
    ("就业空窗期", ["空窗"]),
    ("绝对不会复发", ["绝对"]),
    ("我最", ["最"]),                                        # 末尾省略写法, 宁可多报
    ("", []),
]
for text, want in CASES:
    got = [h.word for h in cw.find_hits(text, W)]
    assert got == want, f"{text!r}: 期望 {want}, 实得 {got}"
# 位置与片段
h = cw.find_hits("这是最好的选择", W)[0]
assert h.at == 2 and h.text == "最好", h

# find_hits 与 sql_regex 同语义 (本地用 re 模拟 PG 的 ~ 运算: 有没有匹配)
rx = cw.sql_regex(W)
for text, want in CASES:
    for word, pattern in rx.items():
        assert bool(re.search(pattern, text)) == (word in want), f"sql_regex[{word}] 与 find_hits 在 {text!r} 上不一致"

# 反证 1: 例外表清空 → 「最近」被拦 (证明例外表真的在生效)
W1 = copy.deepcopy(W)
for e in W1["words"]:
    e.pop("except_followed_by", None)
assert [h.word for h in cw.find_hits("最近很火", W1)] == ["最"], "反证失败: 例外表没生效"
# 反证 2: aliases 去掉 → 「百分百」漏网
W2 = copy.deepcopy(W)
for e in W2["words"]:
    e.pop("aliases", None)
assert cw.find_hits("百分百有效", W2) == [], "反证失败: aliases 没生效"
# 反证 3: 表里少一个词 → 那个词漏网
W3 = copy.deepcopy(W); W3["words"] = [e for e in W3["words"] if e["match"] != "根治"]
assert cw.find_hits("一个月根治", W3) == []

print("✓ 守卫 9 (D-084 B3): 7 个禁词、「最」「第一」的例外、全角/中文 100%、位置、SQL 同语义; 三条反证都红")
