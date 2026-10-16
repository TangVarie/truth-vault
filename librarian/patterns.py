"""librarian/patterns.py — 闸二「已验证规律」下发给馆员 (P4; D-116, docs/28 §7.1 / §7.4)。

规律从哪来: prompts/desk_delivery_v1.json —— 闸二结论之上的人工批准层 (冻结题库外)。这里只读它, 不改。
馆员拿它做三件事 (都只在【不是探索臂】时):
  1. system 第一块里多一段「已验证规律」: 每条一句可照做的话 + 证据, 告诉模型同样合适时优先借命中规律的卡;
  2. 冷路径给进了 shortlist 的卡算「命中了哪几条」(note_feature_answers 里这张卡的源笔记的答案), 渲染进卡面、
     随选中的卡一起回给调用方 (validated_hits);
  3. 响应里带 patterns (规律原文), 写作台照着给写手看。
探索臂 (brief.explore = true; 写作台 15% 的批次, docs/28 §7.4): 三件都不做, 缓存键也分开 —— 对照组要的就是
「没被规律影响过」的那部分。

fail-closed: 文件读不了 / gate2_run 和库里最新一轮闸二对不上 → 整份不下发 (宁可少给, 不给过期的规律)。
fail-open: 算命中时查库失败 → 这次卡上不标命中, 规律段照给, 不阻塞选卡。
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("flywheel_librarian")

DELIVERY_PATH = Path(__file__).resolve().parent.parent / "prompts" / "desk_delivery_v1.json"
_PAGE = 1000
_ID_CHUNK = 100

_cache: dict = {}


def load_delivery(path: Path = DELIVERY_PATH) -> Optional[dict]:
    """读批准层; 读不了 → None (fail-closed)。按路径缓存在进程里: 文件随部署走, 不会在进程内变。"""
    key = str(path)
    if key in _cache:
        return _cache[key]
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(d.get("patterns"), list) or not d.get("gate2_run") or not d.get("bank_sha256"):
            raise ValueError("缺 patterns / gate2_run / bank_sha256")
    except Exception:  # noqa: BLE001
        logger.warning("已验证规律批准层读不了 (%s), 本次不下发", path, exc_info=True)
        d = None
    _cache[key] = d
    return d


def delivery_digest(d: dict) -> str:
    core = {k: d.get(k) for k in ("version", "gate2_run", "bank_sha256", "extractors", "patterns", "suppressed")}
    return hashlib.sha256(json.dumps(core, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:10]


def active_delivery(latest_gate2_run: Optional[str], *, explore: bool,
                    path: Path = DELIVERY_PATH) -> Optional[dict]:
    """这次请求要不要下发、下发哪份。探索臂 / 没有闸二结论 / 批准层是旧一轮的 → None。"""
    if explore:
        return None
    d = load_delivery(path)
    if d is None or not latest_gate2_run:
        return None
    if d["gate2_run"] != latest_gate2_run:
        logger.warning("批准层是 %s 的, 库里最新一轮闸二是 %s —— 规律不下发, 等批准层按新一轮重过 (D-116)",
                       d["gate2_run"], latest_gate2_run)
        return None
    return d


def question_ids(d: dict) -> list[str]:
    qs: set[str] = set()
    for p in d["patterns"]:
        f = p.get("follow") or {}
        for q, _ in (f.get("any_of") or []) + (f.get("none_of") or []) + (f.get("skip_if") or []):
            qs.add(q)
        qs.update(f.get("requires") or [])
    return sorted(qs)


def card_hits(answers: dict[str, dict[str, str]], d: dict) -> dict[str, list[str]]:
    """{note_id: {question_id: answer}} → {note_id: [命中的规律 id]}, 按批准层里的顺序。
    any_of: 有其中任一取值就算; none_of: requires 的题都答过、且一个都没有才算 (requires 没答过不能当「做到了」)。
    skip_if: 有其中任一取值的卡不是这条规律的例子, 不算命中 —— 「品牌别硬插」不能落到根本没露品牌的卡上, 否则规律臂
    会偏着借不提品牌的卡, 等于把 owner 压着的「未出现」从后门下发了 (codex review on #195)。"""
    out: dict[str, list[str]] = {}
    for nid, ans in answers.items():
        hit = []
        for p in d["patterns"]:
            f = p.get("follow") or {}
            if any(ans.get(q) == a for q, a in f.get("skip_if") or []):
                continue
            if f.get("any_of"):
                ok = any(ans.get(q) == a for q, a in f["any_of"])
            else:
                # 只要求 requires 里的题答过: brand_in_title 这类题没标题时记 NULL, 没标题就不可能「品牌进标题」
                ok = all(q in ans for q in f.get("requires") or []) and \
                    not any(ans.get(q) == a for q, a in f.get("none_of") or [])
            if ok:
                hit.append(p["id"])
        if hit:
            out[nid] = hit
    return out


def fetch_answers(sb, note_ids: list[str], d: dict) -> dict[str, dict[str, str]]:
    """note_feature_answers 里这些笔记、这些题、闸二那份快照 (primary × bank_sha × 两个抽取器) 的答案。
    NULL 答案不算答过。"""
    qids = question_ids(d)
    extractors = sorted(set((d.get("extractors") or {}).values()))
    out: dict[str, dict[str, str]] = {}
    ids = sorted({str(i) for i in note_ids if i})
    for i in range(0, len(ids), _ID_CHUNK):
        chunk = ids[i:i + _ID_CHUNK]
        start = 0
        while True:
            rows = (
                sb.schema("truth_vault").table("note_feature_answers")
                .select("subject_id, question_id, answer")
                .eq("subject_type", "note").eq("run_tag", "primary").eq("bank_sha256", d["bank_sha256"])
                .in_("extractor", extractors).in_("question_id", qids).in_("subject_id", chunk)
                .order("subject_id").order("question_id").order("extractor")
                .range(start, start + _PAGE - 1).execute()
            ).data or []
            for r in rows:
                if r.get("answer") is not None:
                    out.setdefault(str(r["subject_id"]), {})[r["question_id"]] = str(r["answer"])
            if len(rows) < _PAGE:
                break
            start += _PAGE
    return out


def labels(d: dict) -> dict[str, str]:
    return {p["id"]: p["label"] for p in d["patterns"]}


def render_block(d: dict) -> str:
    lines = ["═══ 已验证规律 (闸二: 在我们自己的历史笔记里、同一项目内对照过; 是提示, 不是硬规则) ═══"]
    for p in d["patterns"]:
        lines.append(f"- 【{p['label']}】{p['instruction']}（{p['evidence']}）")
    lines.append("用法: 候选卡下面标了「命中已验证规律」的, 同样合适时优先借; 借了的话 borrow_what 里写明借的是哪一条规律。"
                 "不要为了凑规律去借不相关的卡。")
    return "\n".join(lines)


def public_patterns(d: Optional[dict]) -> list[dict]:
    if not d:
        return []
    return [{"id": p["id"], "label": p["label"], "instruction": p["instruction"], "evidence": p["evidence"]}
            for p in d["patterns"]]
