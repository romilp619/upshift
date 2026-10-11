#!/usr/bin/env python3
"""Replace the README placeholders with measured results.

Run after an ablation completes. Idempotent in the sense that it rewrites from
README.template.md if present, so re-running with newer runs is safe.
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from upshift import report  # noqa: E402

RUNS = ROOT / "evidence" / "runs"
ARMS = ("no-entire", "graph", "graph+memory")


def latest(config: str) -> str | None:
    """Most recent COMPLETED run for an arm.

    A run writes its summary only when it finishes, so an in-flight arm has
    none. Without this check the script happily wrote a half-finished 183/199
    into the README while the run was still going.
    """
    hits = sorted(RUNS.glob(f"{config}-*.jsonl"), key=lambda p: p.stat().st_mtime)
    for path in reversed(hits):
        _, summary = report.load(path.stem)
        if summary and summary.get("status") != "interrupted":
            return path.stem
    return None


def main() -> int:
    runs = [r for r in (latest(a) for a in ARMS) if r]
    missing = [a for a in ARMS if not latest(a)]
    if not runs:
        print("no completed runs in evidence/runs/ - is the ablation still going?",
              file=sys.stderr)
        return 1
    if missing:
        print(f"warning: no completed run for {', '.join(missing)}", file=sys.stderr)

    # The headline comes from a run that actually completed the migration.
    # Taking the best figure from each column across all runs would let
    # 199/199 from one run sit beside 62/62 from another.
    ok = [r for r in runs if report.load(r)[1].get("status") == "complete"]
    source = ok[-1] if ok else runs[-1]
    headline = report.load(source)[1]
    best_modules = headline.get("modules_importable", 0)
    best_tests = headline.get("green_tests", 0)

    src = ROOT / "README.template.md"
    readme = ROOT / "README.md"
    text = (src if src.exists() else readme).read_text()
    if not src.exists():
        src.write_text(text)   # first run: keep the placeholder version

    total = report.load(runs[0])[1].get("modules_total", 199) or 199
    text = text.replace("RESULT_MODULES", f"**{best_modules} / {total}**")
    text = text.replace("RESULT_TESTS", f"**{best_tests} / 62**")
    # The ablation compares arms from ONE pass. Picking the newest run of each
    # arm mixed a fixed-harness `graph` run with old-harness runs of the other
    # two - a comparison between agent versions presented as an ablation.
    manifest = ROOT / "evidence" / "ablation.json"
    if manifest.exists():
        arms = json.loads(manifest.read_text())["runs"]
        ablation_runs = [arms[a] for a in ARMS if a in arms]
    else:
        ablation_runs = runs
    text = text.replace("ABLATION_TABLE", report.ablation(ablation_runs))

    # Success rate over every finished run, not only the ablation pass.
    finished = [p.stem for p in RUNS.glob("*.jsonl")
                if report.load(p.stem)[1].get("status") not in (None, "interrupted")]
    complete = [r for r in finished if report.load(r)[1].get("status") == "complete"]
    text = text.replace("RESULT_RATE",
        f"{len(complete)} of {len(finished)} finished runs completed the migration "
        f"({len(complete) / len(finished):.0%})" if finished else "no finished runs")
    readme.write_text(text)
    print(f"README filled from: {', '.join(runs)}")
    print(f"  modules {best_modules}/{total}, green tests {best_tests}/62")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
