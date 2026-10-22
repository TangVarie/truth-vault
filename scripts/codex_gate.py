"""Require a completed Codex review of the current PR head with an explicit clean result.

Usage: python scripts/codex_gate.py owner/repo PR
PASS / WAIT / FINDINGS exit with 0 / 2 / 1. CI and unresolved review threads are separate checks.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys

CODEX = "chatgpt-codex-connector[bot]"


def gh(repo: str, path: str):
    result = subprocess.run(
        ["curl", "--fail", "--silent", "--show-error", "--max-time", "30", "-H",
         "Accept: application/vnd.github+json", f"https://api.github.com/repos/{repo}/{path}"],
        check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print("WAIT usage: python scripts/codex_gate.py owner/repo PR")
        return 2
    repo, pr = argv
    try:
        head = gh(repo, f"pulls/{pr}")["head"]["sha"]
        if not isinstance(head, str) or not head:
            raise ValueError("missing head")
        state, page = None, 1
        while True:
            comments = gh(repo, f"issues/{pr}/comments?per_page=100&page={page}")
            if not isinstance(comments, list):
                raise ValueError("comments response is not a list")
            for comment in comments:
                user = comment.get("user") or {}
                if user.get("login") != CODEX or user.get("type") != "Bot":
                    continue
                body = comment.get("body") or ""
                if "codex-review-state:v1" not in body:
                    continue
                # A malformed newer summary must not leave an older clean summary in force.
                state = None
                match = re.search(r"codex-review-state:v1 (\{.*?\}) -->", body)
                if match:
                    try:
                        candidate = json.loads(match.group(1)).get("code_review")
                        if isinstance(candidate, dict):
                            state = candidate
                    except (ValueError, TypeError, AttributeError):
                        pass
            if len(comments) < 100:
                break
            page += 1
    except (subprocess.SubprocessError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(f"WAIT could not verify GitHub review state ({type(exc).__name__})")
        return 2
    if not state:
        print(f"WAIT no valid Codex summary yet (head {head[:7]})")
        return 2
    if state.get("commit_sha") != head or state.get("status") != "completed":
        print(f"WAIT Codex reviewed {str(state.get('commit_sha'))[:7]} "
              f"status={state.get('status')}, head is {head[:7]}")
        return 2
    unresolved = state.get("has_unresolved_findings")
    if unresolved is True:
        print(f"FINDINGS on head {head[:7]}: fix and re-run review")
        return 1
    if unresolved is not False:
        print(f"WAIT Codex completed head {head[:7]}, but findings state is unknown")
        return 2
    print(f"PASS Codex reviewed head {head[:7]}, no unresolved findings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
