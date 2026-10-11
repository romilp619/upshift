"""Turn run JSONL into the evidence table judges can check."""
from __future__ import annotations

import json
from pathlib import Path

from .config import ROOT

RUNS = ROOT / "evidence" / "runs"


def _expected_green(target: str) -> int:
    from .mcp_server import _expected_green as expected
    return expected(target)


def load(run_id: str) -> tuple[list[dict], dict]:
    """Summary line plus file records.

    A run only writes its summary when it finishes, so an interrupted run has
    none and every headline number read as 0. Derive what we can from the file
    records instead, and mark the run incomplete rather than reporting zeros.
    """
    path = RUNS / f"{run_id}.jsonl"
    files, summary = [], {}
    for line in path.read_text().splitlines():
        record = json.loads(line)
        (files.append(record) if record.get("type") == "file" else summary.update(record))
    if summary and "status" not in summary:
        # Older summaries predate the status field; classify from their counts.
        from .metrics import migration_status
        total = summary.get("green_total") or _expected_green(summary.get("target_repo", ""))
        summary["status"] = migration_status(
            summary.get("modules_importable", 0), summary.get("modules_total", 0),
            summary.get("green_tests", 0), total, summary.get("failing_tests", 0))
    if not summary and files:
        done = [f for f in files if f["outcome"] == "migrated"]
        summary = {
            "config_name": run_id.rsplit("-", 2)[0],
            # No summary: the process never finished. That is "interrupted",
            # distinct from "incomplete", which finished with failures.
            "status": "interrupted",
            "files_total": len({f["path"] for f in files}),
            "files_migrated": len({f["path"] for f in done}),
            "modules_importable": max((f.get("modules_importable", 0) for f in files), default=0),
            "green_tests": max((f.get("tests_passed", 0) for f in files), default=0),
            "modules_total": 199,
            "total_rollbacks": sum(f.get("rollbacks", 0) for f in files),
        }
    return files, summary


def _per_file(files: list[dict]) -> dict:
    done = [f for f in files if f["outcome"] == "migrated"]
    if not done:
        return {"steps": 0.0, "cost": 0.0, "n": 0}
    return {
        "steps": round(sum(f["steps"] for f in done) / len(done), 1),
        "cost": round(sum(f["cost_usd"] for f in done) / len(done), 4),
        "n": len(done),
    }


def learning_curve(files: list[dict], bucket: int = 10) -> list[dict]:
    """Cost and steps per file over time - the memory effect, as a curve."""
    done = [f for f in files if f["outcome"] == "migrated"]
    rows = []
    for start in range(0, len(done), bucket):
        chunk = done[start:start + bucket]
        if not chunk:
            continue
        rows.append({
            "files": f"{start + 1}-{start + len(chunk)}",
            "steps": round(sum(c["steps"] for c in chunk) / len(chunk), 1),
            "cost": round(sum(c["cost_usd"] for c in chunk) / len(chunk), 4),
            "recalled": round(sum(c.get("memory_recalled", c.get("brain_facts_recalled", 0)) for c in chunk) / len(chunk), 1),
        })
    return rows


def ablation(run_ids: list[str]) -> str:
    lines = [
        "| Config | Outcome | Modules importable | Green tests | Files migrated | LLM calls/file | Actual cost/file | Rollbacks |",
        "|---|---|---|---|---|---|---|---|",
        "| v2, untouched | - | 31 / 199 | 0 | - | - | - | - |",
        "| `bump-pydantic` (codemod alone) | incomplete | **31 / 199** | 0 | 11 changed | - | $0 | - |",
    ]
    for run_id in run_ids:
        files, summary = load(run_id)
        stats = _per_file(files)
        label = summary.get("config_name", run_id)
        outcome = summary.get("status", "?")
        lines.append(
            f"| {label} "
            f"| {'**complete**' if outcome == 'complete' else outcome} "
            f"| **{summary.get('modules_importable', 0)} / "
            f"{summary.get('modules_total', 0) or 199}** "
            f"| {summary.get('green_tests', 0)} "
            # Count from file records, excluding the codemod pre-pass, which is
            # recorded as a file entry but is not a file the agent worked on.
            f"| {sum(f['outcome'] == 'migrated' for f in files)}/"
            f"{sum(f['outcome'] != 'codemod' for f in files)} "
            f"| {stats['steps']} "
            f"| ${stats['cost']:.4f} "
            f"| {summary.get('total_rollbacks', 0)} |"
        )
    statuses = [load(r)[1].get("status") for r in run_ids]
    finished = [x for x in statuses if x != "interrupted"]
    if finished:
        ok = finished.count("complete")
        lines.append("")
        lines.append(f"Outcome across these runs: **{ok} of {len(finished)} complete** "
                     f"({ok / len(finished):.0%}). A run is complete only when every module "
                     f"imports and no regression test fails; finishing is not the same as "
                     f"migrating.")
    return "\n".join(lines)


def curve_table(run_id: str) -> str:
    files, _ = load(run_id)
    lines = ["| Files | Steps/file | Cost/file | Memory items recalled |", "|---|---|---|---|"]
    for row in learning_curve(files):
        lines.append(
            f"| {row['files']} | {row['steps']} | ${row['cost']:.4f} | {row['recalled']} |"
        )
    return "\n".join(lines)


def list_runs() -> list[str]:
    return sorted(p.stem for p in RUNS.glob("*.jsonl"))
