"""Turn run JSONL into the evidence table judges can check."""
from __future__ import annotations

import json
from pathlib import Path

from .config import ROOT

RUNS = ROOT / "evidence" / "runs"


def load(run_id: str) -> tuple[list[dict], dict]:
    path = RUNS / f"{run_id}.jsonl"
    files, summary = [], {}
    for line in path.read_text().splitlines():
        record = json.loads(line)
        (files.append(record) if record.get("type") == "file" else summary.update(record))
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
    """Cost and steps per file over time - the Brain effect, as a curve."""
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
        "| Config | Modules importable | Green tests | Files migrated | Steps/file | Cost/file | Rollbacks |",
        "|---|---|---|---|---|---|---|",
        "| `bump-pydantic` (codemod alone) | **0 / 198** | 0 | 11 changed | - | $0 | - |",
    ]
    for run_id in run_ids:
        files, summary = load(run_id)
        stats = _per_file(files)
        lines.append(
            f"| {summary.get('config_name', run_id)} "
            f"| **{summary.get('modules_importable', 0)} / "
            f"{summary.get('modules_total', 0) or 198}** "
            f"| {summary.get('green_tests', 0)} "
            f"| {summary.get('files_migrated', 0)}/{summary.get('files_total', 0)} "
            f"| {stats['steps']} "
            f"| ${stats['cost']:.4f} "
            f"| {summary.get('total_rollbacks', 0)} |"
        )
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
