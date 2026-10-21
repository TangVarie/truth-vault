"""Merge gate: Codex must have finished reviewing the PR's CURRENT head.
usage: python codex_gate.py owner/repo PR  -> prints PASS / WAIT / FINDINGS and exits 0 only on PASS.
PASS  = the Codex summary comment says code_review.commit_sha == head sha, status completed, has_unresolved_findings false.
Only the summary posted by the Codex GitHub App counts: anyone who can comment could paste the same marker.
"""
import json, re, subprocess, sys
repo, pr = sys.argv[1], sys.argv[2]
CODEX = "chatgpt-codex-connector[bot]"      # GitHub reserves the [bot] suffix for Apps, so a person cannot take this login
def gh(path):
    out = subprocess.run(["curl", "-s", "-H", "Accept: application/vnd.github+json",
                          f"https://api.github.com/repos/{repo}/{path}"], capture_output=True, text=True).stdout
    return json.loads(out)
head = gh(f"pulls/{pr}")["head"]["sha"]
state, page = None, 1
while True:
    comments = gh(f"issues/{pr}/comments?per_page=100&page={page}")
    for c in comments:
        user = c.get("user") or {}
        if user.get("login") != CODEX or user.get("type") != "Bot":
            continue
        m = re.search(r"codex-review-state:v1 (\{.*?\}) -->", c.get("body") or "")
        if m:
            state = json.loads(m.group(1))["code_review"]
    if len(comments) < 100:
        break
    page += 1
if not state:
    print(f"WAIT no Codex summary yet (head {head[:7]})"); sys.exit(2)
if state.get("commit_sha") != head or state.get("status") != "completed":
    print(f"WAIT Codex reviewed {str(state.get('commit_sha'))[:7]} status={state.get('status')}, head is {head[:7]}"); sys.exit(2)
if state.get("has_unresolved_findings"):
    print(f"FINDINGS on head {head[:7]}: fix, push, comment '@codex review', re-run gate"); sys.exit(1)
print(f"PASS Codex reviewed head {head[:7]}, no unresolved findings"); sys.exit(0)
