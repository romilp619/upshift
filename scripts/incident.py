#!/usr/bin/env python3
"""Print the ignored-redirect incident: the failing run beside the fixed one.

Reads the recorded per-file steps from evidence/runs/. Nothing is computed at
display time; these are the numbers written while the runs happened.
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUNS = ROOT / "evidence" / "runs"

BEFORE = "graph-1011-1356-94de"   # redirects dropped in the test phase
AFTER = "graph-1011-1454-6bde"    # the same run after commit eb61d4a


def steps(run_id):
    rows = [json.loads(l) for l in (RUNS / f"{run_id}.jsonl").read_text().splitlines() if l.strip()]
    return [r for r in rows if r.get("type") == "file"]


def show(run_id, title, tail=0):
    rows = steps(run_id)
    redirects = [r for r in rows if r["outcome"] == "redirect"]
    print(f"\n{title}")
    print(f"  run {run_id}   {len(rows) - 1} file steps   {len(redirects)} redirects")
    print()
    for r in rows[-tail:] if tail else rows:
        path = r.get("path", "")
        name = path.split("/")[-1] if "/" in path else path
        note = r.get("error", "")
        if r["outcome"] == "redirect":
            note = "-> " + note.replace("root cause is in ", "").split("/")[-1]
        print(f"  {r['index']:>3}  {r['outcome']:<9} modules={r.get('modules_importable', 0):>3} "
              f"tests={r.get('tests_passed', 0):>2}  {name:<42} {note}")


show(BEFORE, "BEFORE  redirects honoured while fixing imports, dropped while fixing tests", tail=8)
print("\n       Four different files all name the same root cause. Each redirect row")
print("       is a model call that produced no edit: modules=0 tests=0. The agent")
print("       reaches plugin_output.py on its last step and stops at 56/62.")

show(AFTER, "AFTER  commit eb61d4a - redirects followed in both phases", tail=8)
print("\n       7 redirects -> 1. 29 file steps -> 23. 56/62 tests -> 62/62.")
print()
