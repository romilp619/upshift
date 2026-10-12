#!/usr/bin/env python3
"""Measure Upshift's result yourself. No API key, no model call.

Imports every module of the target and runs its 62 regression tests, using the
same probe the agent is judged by, on two commits:

  start   the pinned commit under Pydantic v2 - what a team has after upgrading
  result  upshift/verified on github.com/romilp619/python-client - the agent's
          finished migration

    bash scripts/setup_target.sh        # once
    python scripts/verify_result.py

Expected: start 31/199 modules, 0 tests; result 199/199 modules, 62/62 tests.
Afterwards the target is left on the pinned commit, ready for an agent run.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from upshift.cli import _load_target  # noqa: E402

PIN = "3bcc5d794bf40ec29fba9d661791f691ee367c55"


def measure(target, ref, label):
    subprocess.run(["git", "checkout", "--quiet", "--force", "--detach", ref], cwd=target.path, check=True)
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=target.path,
                          capture_output=True, text=True).stdout.strip()
    print(f"\n{label}  ({ref}, {head})  measuring ...", flush=True)
    imports = target.import_check()
    tests = target.run_green()
    print(f"  modules importable: {imports.ok}/{imports.total}")
    print(f"  regression tests:   {tests.passed}/{target.green_expected or 62} passing")
    return imports, tests


def main():
    target = _load_target("python-client")
    if not (target.path / ".venv" / "bin" / "python").exists():
        sys.exit("run `bash scripts/setup_target.sh` first")
    subprocess.run(["git", "fetch", "--quiet", "origin"], cwd=target.path, check=True)
    try:
        s_imp, s_tests = measure(target, PIN, "start ")
        r_imp, r_tests = measure(target, "origin/upshift/verified", "result")
    finally:
        subprocess.run(["git", "checkout", "--quiet", "--force", "-B", "upshift/pydantic-v2", PIN],
                       cwd=target.path, check=True)
    ok = r_imp.ok == r_imp.total and r_tests.passed >= (target.green_expected or 62)
    print(f"\nmodules {s_imp.ok}/{s_imp.total} -> {r_imp.ok}/{r_imp.total}, "
          f"tests {s_tests.passed} -> {r_tests.passed}: {'VERIFIED' if ok else 'NOT reproduced'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
