#!/usr/bin/env python3
"""Regression checks for truth-vault audit hardening fixes."""

from __future__ import annotations

import pathlib
import sys
import threading
import time
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def check_librarian_gate_bounded_and_recently_curated():
    from librarian import core as lc

    # 1. Naive ISO curated_at must be interpreted as UTC without TypeError
    now_ts = time.time()
    now_naive = datetime.fromtimestamp(now_ts, tz=timezone.utc).replace(tzinfo=None).isoformat()
    assert lc._recently_curated({"curated_at": now_naive}, now_ts) is True
    assert lc._recently_curated({"curated_at": "2020-01-01T00:00:00"}, now_ts) is False

    # 2. _gate_blocked must return within RETURN_GATE_WAIT_S even if _read_gate stalls
    orig_read = lc._read_gate
    orig_wait = lc.RETURN_GATE_WAIT_S
    with lc._GATE_LOCK:
        orig_state = dict(lc._GATE)
        orig_stats = dict(lc.GATE_STATS)
    # Cold state = the module's own initial _GATE; fail if core.py renames or adds keys so this test is updated with it.
    cold = {"at": None, "blocked": None, "thread": None, "started": 0.0, "late": None}
    assert set(cold) == set(orig_state), f"_GATE keys changed: {sorted(orig_state)}"
    stall_ev = threading.Event()
    reader = None
    try:
        with lc._GATE_LOCK:
            lc._GATE.update(cold)
        lc.RETURN_GATE_WAIT_S = 0.08
        # Same shape as the real _read_gate: ({note_id: reasons}, verdicts, unreadable).
        lc._read_gate = lambda _sb, _ids: (stall_ev.wait(2.0), ({}, 0, 0))[1]
        t0 = time.monotonic()
        res = lc._gate_blocked(object(), [{"source_note_id": "n1"}])
        elapsed = time.monotonic() - t0
        with lc._GATE_LOCK:
            reader = lc._GATE["thread"]
        assert res is None, f"expected None fail-open on cold timeout, got {res!r}"
        assert elapsed < 0.5, f"_gate_blocked stalled for {elapsed:.2f}s"
        assert reader is not None and reader.is_alive(), "the stalled read should still be running in the background"
        assert isinstance(lc.gate_health(), dict)
        assert isinstance(lc.vanished_health(), dict)
        assert isinstance(lc.paid_health(), dict)
        assert isinstance(lc.merge_health(), dict)
        # Let the late read land, then check _refresh_gate stored what the real shape gives.
        stall_ev.set()
        reader.join(2.0)
        assert not reader.is_alive(), "background gate read did not finish"
        with lc._GATE_LOCK:
            assert lc._GATE["blocked"] == {} and lc._GATE["thread"] is None, dict(lc._GATE)
            assert lc.GATE_STATS["read_ok"] is True and lc.GATE_STATS["verdicts"] == 0, dict(lc.GATE_STATS)
    finally:
        stall_ev.set()
        if reader is not None:
            reader.join(2.0)   # restore only after the background read has written back, or it overwrites the restore
        lc._read_gate = orig_read
        lc.RETURN_GATE_WAIT_S = orig_wait
        with lc._GATE_LOCK:
            lc._GATE.clear()
            lc._GATE.update(orig_state)
            lc.GATE_STATS.clear()
            lc.GATE_STATS.update(orig_stats)
    print("[PASS] librarian._gate_blocked bounded wait + _recently_curated UTC + merge_health")


def check_worker_project_validation():
    from worker import app as wapp
    from fastapi import HTTPException

    for ok_proj in ("TUGE", "XIWU_phase2", "NRT-01", "a.b"):
        assert wapp._validate_project(ok_proj) == ok_proj

    for bad_proj in ("", " ", "../etc", "a;rm", "a/b", "x" * 100):
        try:
            wapp._validate_project(bad_proj)
        except HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError(f"expected HTTPException 400 for {bad_proj!r}")
    print("[PASS] worker._validate_project")


def check_feishu_media_401_retry():
    import feishu_media

    class _FakeClient:
        def __init__(self):
            self._token = "stale-tok"
            self._token_expires_at = 9999999999
            self.calls = 0

        def _ensure_token(self):
            self.calls += 1
            if self._token is None:
                self._token = "fresh-tok"
                self._token_expires_at = 9999999999
            return self._token

    class _Resp:
        def __init__(self, status, chunks=()):
            self.status_code = status
            self._chunks = chunks

        def iter_content(self, _n):
            return iter(self._chunks)

        def close(self):
            pass

    seen_auth = []

    def _fake_get(url, *, headers, params, stream, timeout):
        seen_auth.append(headers["Authorization"])
        if len(seen_auth) == 1:
            return _Resp(401)
        return _Resp(200, [b"PNGDATA"])

    cli = _FakeClient()
    data = feishu_media.download(cli, {"file_token": "tok_abc123"}, max_bytes=1024, http_get=_fake_get)
    assert data == b"PNGDATA"
    assert seen_auth == ["Bearer stale-tok", "Bearer fresh-tok"]
    print("[PASS] feishu_media.download 401 token refresh retry")


def check_linkcheck_comment_chunking_keeps_parent_before_reply():
    import sync_comments_from_raw_extra as sc

    batches = []

    class _FakeTbl:
        def upsert(self, rows, **_k):
            batches.append(list(rows))
            return self

        def delete(self):
            return self

        def in_(self, *_a):
            return self

        def execute(self):
            return None

    class _FakeSB:
        def schema(self, _s):
            return self

        def table(self, _t):
            return _FakeTbl()

    # Fill first 499 rows in note A, then note B with reply listed BEFORE parent
    note_a = [{"comment_id": f"a_{i}", "parent_comment_id": None, "comment_order": i} for i in range(499)]
    note_b = [
        {"comment_id": "b_reply", "parent_comment_id": "b_parent", "comment_order": 2},
        {"comment_id": "b_parent", "parent_comment_id": None, "comment_order": 1},
    ]
    plans = [{"upserts": note_a, "deletes": []}, {"upserts": note_b, "deletes": []}]
    up, dl = sc.apply_linkcheck_plans(_FakeSB(), plans, dry_run=False)
    assert up == 501 and dl == 0
    assert len(batches) == 2
    assert len(batches[0]) == 499
    assert [r["comment_id"] for r in batches[1]] == ["b_parent", "b_reply"]
    print("[PASS] sync_comments_from_raw_extra.apply_linkcheck_plans FK-safe chunking")


def check_static_sql_and_redaction_guards():
    sql = (ROOT / "scripts" / "verify_supabase_state.sql").read_text(encoding="utf-8")
    assert "regexp_replace(a.subject_id, ':p[0-9]+$', '')" in sql

    mask_src = (ROOT / "scripts" / "mask_external_names.py").read_text(encoding="utf-8")
    assert "raw[:120]" not in mask_src

    showcase = (ROOT / "dashboard" / "config" / "showcase.ts").read_text(encoding="utf-8")
    assert "ω" in showcase

    login = (ROOT / "dashboard" / "app" / "api" / "auth" / "login" / "route.ts").read_text(encoding="utf-8")
    assert "status: 400" in login
    print("[PASS] static SQL, stdout redaction, dashboard Greek alphabet & login 400 checks")


def check_essence_write_back_failure_not_called_retried():
    """TV#301 made essence write-back skip just the failing post with no retry (S-14 ①).
    The closing line must not say those were retried (S-18 ①); the workflows grep it by '有 N 条失败'."""
    import io
    import json
    import logging
    import os
    import re
    import tempfile
    from unittest.mock import patch

    import annotate_essence_pass as ess

    msg = ess._partial_failure_message
    only_write = msg({"ok": 2, "failed_after_retry": 1, "validation_failed": 0}, 1)
    assert "写回失败 1 条, 只跳这一篇、不重试" in only_write, only_write
    assert "重试一次" not in only_write and "退避重试" not in only_write, only_write
    mixed = msg({"ok": 5, "failed_after_retry": 4, "validation_failed": 1, "gateway_filtered": 1,
                 "systemic_failed": 2}, 1)
    assert "essence 有 4 条失败" in mixed and "ok=5" in mixed, mixed
    assert "校验类 1 条, 已带纠错提示重试一次" in mixed, mixed
    assert "模型调用出错 2 条" in mixed and "写回失败 1 条, 只跳这一篇、不重试" in mixed, mixed
    no_write = msg({"ok": 3, "failed_after_retry": 2, "validation_failed": 2}, 0)
    assert "写回失败" not in no_write and "模型调用出错" not in no_write, no_write
    for line in (only_write, mixed, no_write):
        assert "已各重试一次" not in line and re.search("有 [0-9]+ 条失败", line), line

    # main() end to end: the model answers fine, one write-back raises once -> skipped, not retried, rc 0
    good = json.dumps({"essence": {"emotional_lever": "焦虑撬动", "emotional_valence": "negative",
                                   "emotional_intensity": "high", "human_truth_archetype": ["健康焦虑"],
                                   "trend_dependencies": ["通用"], "content_format": "情感叙事"}, "audience": {}})
    assert ess.validate_essence(json.loads(good)) == [], "fixture must pass the vocab check"
    notes = [{"note_id": f"P_{i}", "project_id": "P", "title": f"t{i}", "body": f"b{i}",
              "raw_content": f"【标题】t{i}\n【正文】b{i}", "hashtags": [], "intent": "种草",
              "target_blue_keywords": ["推车"], "raw_extra": {"_direction_raw": "带娃出行"},
              "projects": {"brand": "某牌", "product": "推车"}} for i in range(3)]
    writes = []

    def write(_sb, note_id, *_a, **_k):
        writes.append(note_id)
        if note_id == "P_1":
            raise RuntimeError("fake 520")

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    ess.logger.addHandler(handler)
    try:
        with tempfile.TemporaryDirectory() as td, \
                patch.object(sys, "argv", ["x", "P", "--qps", "0", "--pass", "new", "--limit", "15",
                                           "--failed-queue", f"{td}/q.jsonl"]), \
                patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake"}), \
                patch.object(ess, "load_mapping", return_value={}), \
                patch.object(ess, "get_supabase_client", return_value=object()), \
                patch.object(ess, "fetch_unannotated_notes", return_value=notes), \
                patch.object(ess, "get_sub_directions_for_note", return_value=None), \
                patch.object(ess, "write_essence_back", side_effect=write), \
                patch.object(ess, "call_claude", side_effect=lambda p, m, *, cached_system=None: good):
            rc = ess.main()
    finally:
        ess.logger.removeHandler(handler)
    log = buf.getvalue()
    assert rc == 0 and writes == ["P_0", "P_1", "P_2"], (rc, writes)
    line = next((ln for ln in log.splitlines() if re.search("有 [0-9]+ 条失败", ln)), "")
    assert "essence 有 1 条失败" in line and "写回失败 1 条, 只跳这一篇、不重试" in line, log[-600:]
    assert "重试一次" not in line and "退避重试" not in line, line
    print("[PASS] essence closing line: write-back failures are not called retried")


if __name__ == "__main__":
    check_librarian_gate_bounded_and_recently_curated()
    check_worker_project_validation()
    check_feishu_media_401_retry()
    check_linkcheck_comment_chunking_keeps_parent_before_reply()
    check_static_sql_and_redaction_guards()
    check_essence_write_back_failure_not_called_retried()
    print("ALL truth-vault audit hardening checks PASSED")
