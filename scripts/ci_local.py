"""Run the `run:` steps of .github/workflows/ci.yml locally and report pass/fail per step.

Usage (from anywhere; REPO must be a git clone, check_gate1_review needs `git check-ignore`):
    python scripts/ci_local.py REPO [--job python|yaml] [--out results.json]

- Runs each `run:` step of the chosen job with `bash -e -o pipefail`, in the step's
  working-directory, with GITHUB_STEP_SUMMARY / GITHUB_OUTPUT / GITHUB_ENV sent to /dev/null.
- Skips steps that only install dependencies: install scripts/requirements.lock (plus pyyaml,
  fastapi, 'httpx<0.28', starlette, uvicorn) into the interpreter running this file first.
  Steps that pip-install inline and then test are run as they are.
- The `sql` job needs a throwaway Postgres 16 and a database named tv_ci; it is not run here
  (see docs/handoff-2026-11-22-four-repos.md section 5).
- Prints "<ok> ok / <total>" and exits 1 if any step failed. Needs no secrets; the inline
  pip installs need PyPI. Some steps write scratch files under RUNNER_TEMP (default /tmp).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

import yaml


def _install_only(cmd: str) -> bool:
    """True for a step that only installs dependencies (pip lines plus shell if/else around them)."""
    lines = [ln.strip() for ln in cmd.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    shell = ("if ", "else", "fi", "then")
    return bool(lines) and all("pip install" in ln or ln.startswith(shell) for ln in lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--job", default="python", choices=["python", "yaml"])
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    repo = os.path.abspath(args.repo)
    with open(os.path.join(repo, ".github/workflows/ci.yml"), encoding="utf-8") as fh:
        wf = yaml.safe_load(fh)
    job = wf["jobs"][args.job]
    wdef = ((job.get("defaults") or {}).get("run") or {}).get("working-directory")
    results = []
    for i, step in enumerate(job.get("steps", [])):
        cmd = step.get("run")
        if not cmd:
            continue
        name = step.get("name") or cmd.splitlines()[0][:60]
        if _install_only(cmd):
            continue
        env = dict(os.environ)
        for k, v in {**(wf.get("env") or {}), **(job.get("env") or {}), **(step.get("env") or {})}.items():
            env[k] = str(v)
        if "PYTHONPATH" not in {**(job.get("env") or {}), **(step.get("env") or {})}:
            env.pop("PYTHONPATH", None)  # CI sets none; a local one would hide import errors
        env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env.get("PATH", "")
        env["GITHUB_WORKSPACE"] = repo
        env.setdefault("RUNNER_TEMP", "/tmp")
        for k in ("GITHUB_STEP_SUMMARY", "GITHUB_OUTPUT", "GITHUB_ENV"):
            env[k] = "/dev/null"
        wd = step.get("working-directory") or wdef
        cwd = os.path.join(repo, wd) if wd else repo
        try:
            p = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", cmd], cwd=cwd, env=env,
                               capture_output=True, text=True, timeout=600)
            rc, tail = p.returncode, (p.stdout + p.stderr)[-1500:]
        except subprocess.TimeoutExpired:
            rc, tail = 124, "TIMEOUT"
        results.append({"i": i, "name": name, "rc": rc, "tail": tail})
        if rc:
            print(f"FAIL [{i}] {name} rc={rc}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=1)
    ok = sum(r["rc"] == 0 for r in results)
    print(ok, "ok /", len(results))
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
