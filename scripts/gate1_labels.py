"""
gate1_labels.py
═══════════════════════════════════════════════════════════════════════════

闸一三个脚本共用的题目短标签 (question_id → 表头 / 报告里的中文短名)。

单独放一个【零依赖】模块: build_gate1_human_sheets.py 顶层 import openpyxl、ingest_gate1_answers.py
读 xlsx 时 import 它 (不在 scripts/requirements.txt 里, 只在做表 / 收表的机器上装); gate1_agreement.py
只算数, 装完 requirements 就该能跑 —— 它以前从 build_gate1_human_sheets 拿 SHORT, 于是连
--print-sql 都要先装 openpyxl (codex review on #154)。标签的唯一来源在这里, 别的地方别抄。

名单 CSV 的 skipped_questions (灰格题号) 怎么拼、怎么拆也放在这里 (D-085): 以前生成器用 "|" 拼、
收表脚本用 "," 拆, 只有一个灰格的篇碰巧没事; NUC_phase1_recv46LaDAdFFc 有 11 个灰格, 拆出来是一整串
"opening_type|has_specific_time|…" —— 两个方向的校验都失效, Jev 在这 11 格里填的答案原样入了库。
写和读只许走 join_skipped / split_skipped 这一对。
"""

from __future__ import annotations

import re

SKIPPED_SEP = "|"                       # 名单里写的分隔符 (与 2026-09-28 那份名单一致)
_SKIPPED_SPLIT = re.compile(r"[|,]")    # 读的时候 "|" 与旧写法 "," 都认


def join_skipped(qids) -> str:
    """灰格题号 → 名单 CSV 里 skipped_questions 那一格。"""
    qids = [str(q).strip() for q in qids]
    bad = [q for q in qids if not q or _SKIPPED_SPLIT.search(q)]
    if bad:
        raise ValueError(f"题号里不能是空的或带分隔符: {bad}")
    return SKIPPED_SEP.join(qids)


def split_skipped(cell) -> list[str]:
    """名单 CSV 的 skipped_questions 那一格 → 题号列表 (保序去重; 空格子 → [])。"""
    out = [x.strip() for x in _SKIPPED_SPLIT.split(str(cell or ""))]
    return list(dict.fromkeys(x for x in out if x))

SHORT: dict[str, str] = {
    "title_is_question": "标题是问句",
    "opening_type": "第一句类型",
    "has_specific_time": "具体时间",
    "has_specific_place": "具体地点或场合",
    "has_direct_quote": "别人说的原话",
    "has_body_sensation": "具体身体感受",
    "ending_asks_reader": "结尾问读者",
    "invites_sharing": "请读者讲经历",
    "asks_for_help": "整篇在求助",
    "withholds_product_name": "故意不说名字",
    "divisive_claim": "会有人反对的判断",
    "product_role": "产品角色",
    "efficacy_promise": "效果承诺",
    "narrator_identity": "交代身份",
    "own_experience": "亲身经历",
    "comparison_group": "拿别人对照",
    "calls_out_reader_group": "点名某类读者",
    "turning_point": "前后转折",
    "judged_by_others": "被人评价",
    "negative_outcome_happened": "已发生的坏结果",
}
