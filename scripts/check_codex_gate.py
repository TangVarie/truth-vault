"""Offline CLI regressions for the review merge gate; no GitHub calls or credentials."""
from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from copy import deepcopy
from unittest.mock import patch

import codex_gate as gate

HEAD = "a" * 40
STATE = {"commit_sha": HEAD, "status": "completed", "has_unresolved_findings": False}


def comment(state=STATE, *, login=gate.CODEX, kind="Bot"):
    return {"user": {"login": login, "type": kind},
            "body": "<!-- codex-review-state:v1 " + json.dumps({"code_review": state}) + " -->"}


def run(pages, *, head=HEAD, fail=False):
    def request(repo, path):
        if fail:
            raise ValueError("invalid JSON response")
        if path.startswith("pulls/"):
            return {"head": {"sha": head}}
        return pages[int(path.rsplit("=", 1)[1]) - 1]
    output = io.StringIO()
    with patch.object(gate, "gh", side_effect=request), redirect_stdout(output):
        code = gate.main(["example/repo", "1"])
    return code, output.getvalue()


def main():
    cases = 0
    # The production false positive: completed + null used to exit 0 / PASS.
    for unknown in (None, "false", 0, [], {}):
        code, text = run([[comment({**STATE, "has_unresolved_findings": unknown})]])
        assert code == 2 and text.startswith("WAIT"), (unknown, code, text)
        cases += 1
    missing = deepcopy(STATE)
    missing.pop("has_unresolved_findings")
    assert run([[comment(missing)]])[0] == 2
    assert run([[comment()]])[0] == 0
    assert run([[comment({**STATE, "has_unresolved_findings": True})]])[0] == 1
    assert run([[comment({**STATE, "commit_sha": "b" * 40})]])[0] == 2
    assert run([[comment({**STATE, "status": "running"})]])[0] == 2
    assert run([[comment(login="someone-else")]])[0] == 2
    assert run([[comment(kind="User")]])[0] == 2
    assert run([[comment(None)]])[0] == 2
    assert run([[comment(), {**comment(), "body": "<!-- codex-review-state:v1 invalid -->"}]])[0] == 2
    assert run([[comment(), comment(login="someone-else")]])[0] == 0
    assert run([[{}] * 100, [comment()]])[0] == 0
    assert run([{"message": "API failed"}])[0] == 2
    assert run([[]], fail=True)[0] == 2
    assert run([[comment()]], head="")[0] == 2
    cases += 14
    print(f"review gate: {cases} offline cases passed (unknown findings never pass)")


if __name__ == "__main__":
    main()
