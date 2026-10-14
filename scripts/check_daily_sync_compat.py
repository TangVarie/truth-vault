"""Offline regressions for the 2026-10-13/14 daily-sync failures."""
import copy
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import annotate_essence_pass as a
import sync_feishu_notes_to_truth_vault as s
from _common import load_mapping


GOOD = {"essence": {
    "emotional_lever": "焦虑撬动", "emotional_valence": "negative",
    "emotional_intensity": "high", "human_truth_archetype": ["健康焦虑"],
    "trend_dependencies": ["通用"], "content_format": "情感叙事",
}, "audience": {}}


def check_spx_metrics():
    mapping = load_mapping("SPX_phase1")
    for value in (0, 605, "1,234"):
        note, metric, undeclared = s.transform_row(mapping, "synthetic-record", {
            "笔记内容": "【标题】合成测试【正文】仅用于离线字段映射测试。",
            "互动数": value,
            "曝光量": 2000,
            "阅读量": 1500,
            "实时数据.评论数": 12,
        })
        expected = int(str(value).replace(",", ""))
        assert note["interactions"] == metric["interactions"] == expected
        assert "互动数" not in undeclared
        assert note["comments_count"] == 12  # tier still uses comments, not interactions
    assert a.validate_essence(GOOD) == []


def check_invalid_shapes_retry():
    invalid = [[], [GOOD], "text", 3, True, {}, {"essence": []},
               {"essence": "text"}, {"essence": None}]
    for field in ("emotional_lever", "emotional_valence", "emotional_intensity",
                  "content_format", "human_truth_archetype", "trend_dependencies"):
        for bad in ([{}], {"bad": "shape"}):
            payload = copy.deepcopy(GOOD)
            payload["essence"][field] = bad
            invalid.append(payload)
    for payload in invalid:
        assert a.validate_essence(payload), payload
        with patch.object(a, "call_claude", side_effect=[json.dumps(payload), json.dumps(GOOD)]) as call:
            parsed, errors, _, retried = a._annotate_with_retry("synthetic", "fake")
            assert parsed == GOOD and errors == [] and retried and call.call_count == 2
    # Malformed JSON on attempt one, structurally invalid JSON on the retry.
    with patch.object(a, "call_claude", side_effect=["not-json", "[]"]):
        parsed, errors, _, retried = a._annotate_with_retry("synthetic", "fake")
        assert parsed is None and errors and retried


def check_failed_note_does_not_stop_batch():
    with tempfile.TemporaryDirectory() as tmp:
        queue = Path(tmp) / "failed.jsonl"
        notes = [{"note_id": n, "project_id": "synthetic", "projects": {}}
                 for n in ("N1", "N2")]
        with (patch.object(sys, "argv", ["check", "synthetic", "--qps", "0",
                                         "--failed-queue", str(queue)]),
              patch.dict(a.os.environ, {"ANTHROPIC_API_KEY": "fake-not-used"}),
              patch.object(a, "load_mapping", return_value={}),
              patch.object(a, "get_supabase_client", return_value=object()),
              patch.object(a, "fetch_unannotated_notes", return_value=notes),
              patch.object(a, "build_mode_a_prompt", return_value=("system", "user")),
              patch.object(a, "call_claude", side_effect=["[]", '{"essence":[]}', json.dumps(GOOD)]) as calls,
              patch.object(a, "write_essence_back") as writes):
            assert a.main() == 0
        assert calls.call_count == 3
        assert writes.call_count == 1 and writes.call_args.args[1] == "N2"
        failed = [json.loads(line) for line in queue.read_text().splitlines()]
        assert len(failed) == 1 and failed[0]["note_id"] == "N1"
        assert "essence must be a JSON object" in failed[0]["errors"]


if __name__ == "__main__":
    check_spx_metrics()
    check_invalid_shapes_retry()
    check_failed_note_does_not_stop_batch()
    print("Daily sync compatibility: renamed metric → notes + snapshot; malformed JSON → retry/queue; batch continues. OK")
