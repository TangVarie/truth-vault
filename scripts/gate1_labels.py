"""
gate1_labels.py
═══════════════════════════════════════════════════════════════════════════

闸一三个脚本共用的题目短标签 (question_id → 表头 / 报告里的中文短名)。

单独放一个【零依赖】模块: build_gate1_human_sheets.py / ingest_gate1_answers.py 顶层 import
openpyxl (不在 scripts/requirements.txt 里, 只在做表 / 收表的机器上装); gate1_agreement.py
只算数, 装完 requirements 就该能跑 —— 它以前从 build_gate1_human_sheets 拿 SHORT, 于是连
--print-sql 都要先装 openpyxl (codex review on #154)。标签的唯一来源在这里, 别的地方别抄。
"""

from __future__ import annotations

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
