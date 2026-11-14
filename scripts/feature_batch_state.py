#!/usr/bin/env python3
"""Classify worker output for the features-sync shell loop; never relax failures.

Only a batch whose healthy notes succeeded and whose sole failure is an existing
recovery backlog may continue. A final project alert still makes the run red.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys

COUNTERS = ('ok', 'failed', 'systemic_failed', 'hygiene_failed', 'model_no_valid',
            'retry_deferred', 'retry_quarantined', 'gateway_filtered')


def classify(payload, curl_rc: str, http_code: str, batch: int) -> tuple[str, int, int, int]:
    other = ('other', 0, 0, 0)
    if (curl_rc != '0' or http_code != '200' or not isinstance(payload, dict)
            or payload.get('ok') is not False or type(payload.get('returncode')) is not int or payload.get('returncode') != 1
            or payload.get('timed_out')):
        return other
    tail = payload.get('stdout_tail')
    if not isinstance(tail, str):
        return other
    matches = re.findall(r'Done:\s*(\{[^\n]*\})\s*$', tail, re.M)
    if not matches:
        return other
    try:
        stats = json.loads(matches[-1])
    except (TypeError, ValueError):
        return other
    if not isinstance(stats, dict) or not all(type(stats.get(k)) is int and stats[k] >= 0 for k in COUNTERS):
        return other
    ok, deferred, quarantined = (stats[k] for k in ('ok', 'retry_deferred', 'retry_quarantined'))
    if stats['model_no_valid']:
        return ('model_invalid', ok, deferred, quarantined)
    if (stats['failed'] or stats['systemic_failed'] or stats['hygiene_failed'] or stats['gateway_filtered']
            or ok > batch or not (deferred or quarantined)):
        return other
    return ('recovery_progress' if ok else 'recovery_only', ok, deferred, quarantined)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        payload = json.loads(Path(args[0]).read_text())
        state = classify(payload, args[1], args[2], int(args[3]))
    except (OSError, ValueError, IndexError):
        state = ('other', 0, 0, 0)
    print(*state)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
