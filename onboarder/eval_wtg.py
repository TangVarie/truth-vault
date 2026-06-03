"""onboarder/eval_wtg.py — WTG 金标准回归 eval(docs/16 §验收)。

⚠️ WTG 不是已确认的金标准 —— 只有【结构部分】定稿(见 WTG yaml 头注);direction /
阈值 / 合规仍是 [待确认] 草稿、未经策略 lead 确认。所以本 eval 【只】拿结构字段当
oracle,绝不断言草稿的判断值(否则 = 拿没人审的 agent 猜测当答案,codex PR#37 review)。
mappings/WTG_phase1.yaml 当【结构】回归基准:

  --check-golden (默认):金标准本身必须通过 vocab 校验(证明校验器 + 词表 + 金标准
                         三者自洽,现在就能跑)。
  --against <produced.yaml>:把 agent 重跑 WTG 产出的 yaml 与金标准做【结构对比】+
                         [待确认] 覆盖对比。

通过判据:结构 diff = 0 关键差异(schema_family / field_mapping 列集 / raw_extra
allowlist / tier 规则 / 阈值存在 / 方向名集合),且 produced 的 [待确认] 项 ⊇ 金标准。
完整"agent 重跑"接 core.run_onboarding(需中转站+飞书凭证)。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from . import vocab

GOLDEN = Path(__file__).resolve().parent.parent / "mappings" / "WTG_phase1.yaml"


def _load(path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _direction_names(mp: dict) -> set[str]:
    return set((mp.get("direction_decomposition") or {}).keys())


def compare_structural(produced: dict, golden: dict) -> dict[str, list[str]]:
    """结构对比 → {diffs: [...], ok: [...]}。"""
    diffs: list[str] = []
    ok: list[str] = []

    def cmp(label, a, b):
        (ok if a == b else diffs).append(
            f"{label}: {'一致' if a == b else f'producd={a!r} ≠ golden={b!r}'}"
        )

    cmp("schema_family", produced.get("schema_family"), golden.get("schema_family"))

    pf = set((produced.get("field_mapping") or {}).keys())
    gf = set((golden.get("field_mapping") or {}).keys())
    if pf == gf:
        ok.append(f"field_mapping 列集一致({len(gf)} 列)")
    else:
        diffs.append(f"field_mapping 漏列={sorted(gf - pf)} 多列={sorted(pf - gf)}")

    pr = set(produced.get("project_specific_fields_to_raw_extra", []) or [])
    gr = set(golden.get("project_specific_fields_to_raw_extra", []) or [])
    if pr == gr:
        ok.append(f"raw_extra allowlist 一致({len(gr)} 列)")
    else:
        diffs.append(f"raw_extra 漏={sorted(gr - pr)} 多={sorted(pr - gr)}")

    pn, gn = _direction_names(produced), _direction_names(golden)
    cmp("方向名集合", pn, gn)
    cmp("tier_extraction.source",
        (produced.get("tier_extraction") or {}).get("source"),
        (golden.get("tier_extraction") or {}).get("source"))
    for key in ("tier_thresholds",):
        (ok if produced.get(key) else diffs).append(
            f"{key} 存在" if produced.get(key) else f"{key} 缺失"
        )
    return {"diffs": diffs, "ok": ok}


def check_golden() -> int:
    mp = _load(GOLDEN)
    res = vocab.validate_mapping(mp)
    print(f"[check-golden] {GOLDEN.name}: errors={len(res['errors'])} pending={len(res['pending'])}")
    for e in res["errors"]:
        print("  ERROR:", e)
    if res["errors"]:
        print("FAIL:金标准没过 vocab 校验(词表/校验器/金标准 三者不自洽)")
        return 1
    print("PASS:金标准自洽,校验器可用。")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="WTG 金标准 eval")
    p.add_argument("--against", help="agent 重跑产出的 yaml,与金标准对比")
    args = p.parse_args()

    if not args.against:
        return check_golden()

    produced, golden = _load(args.against), _load(GOLDEN)
    rep = compare_structural(produced, golden)
    print("=== 结构对比 ===")
    for s in rep["ok"]:
        print("  ✓", s)
    for s in rep["diffs"]:
        print("  ✗", s)
    pen_p = set(vocab.validate_mapping(produced)["pending"])
    pen_g = set(vocab.validate_mapping(golden)["pending"])
    missing = pen_g - pen_p
    print(f"\n[待确认] 覆盖: produced={len(pen_p)} golden={len(pen_g)} 漏标={sorted(missing) or '无'}")
    passed = not rep["diffs"] and not missing
    print("\n=== " + ("PASS" if passed else "FAIL") + " ===")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
