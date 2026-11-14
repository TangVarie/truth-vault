#!/usr/bin/env python3
"""Classify one worker /annotate-features response for the workflow shell loops (D-153).

Prints `<state> <ok> <deferred> <quarantined> <invalid>`:

  model_invalid  this batch asked the model and at least one note got no valid answer at
                 all. A NEW failure of this run: the caller reports it red and never
                 re-sends the same chunk (the note is already in the recovery queue).
  backlog        the batch itself succeeded; the Done line also reports standing recovery
                 backlog (waiting / quarantined notes). Warning only, never red.
  other          anything else (plain success, transport failure, old worker without the
                 counters, malformed output): the caller's existing handling applies.

Never raises and never relaxes a failure: an unreadable response is `other`.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys

COUNTERS = ('ok', 'model_no_valid', 'retry_deferred', 'retry_quarantined')
OTHER = ('other', 0, 0, 0, 0)


def classify(payload, curl_rc: str, http_code: str) -> tuple[str, int, int, int, int]:
    if curl_rc != '0' or http_code != '200' or not isinstance(payload, dict) or payload.get('timed_out'):
        return OTHER
    tail = payload.get('stdout_tail')
    if not isinstance(tail, str):
        return OTHER
    matches = re.findall(r'Done:\s*(\{[^\n]*\})\s*$', tail, re.M)
    if not matches:
        return OTHER
    try:
        stats = json.loads(matches[-1])
    except (TypeError, ValueError):
        return OTHER
    if not isinstance(stats, dict) or not all(type(stats.get(k)) is int and stats[k] >= 0 for k in COUNTERS):
        return OTHER
    ok, invalid, deferred, quarantined = (stats[k] for k in COUNTERS)
    if invalid:
        return ('model_invalid', ok, deferred, quarantined, invalid)
    if payload.get('ok') is True and (deferred or quarantined):
        return ('backlog', ok, deferred, quarantined, 0)
    return ('other', ok, deferred, quarantined, 0)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        payload = json.loads(Path(args[0]).read_text())
        state = classify(payload, args[1], args[2])
    except (OSError, ValueError, IndexError):
        state = OTHER
    print(*state)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
