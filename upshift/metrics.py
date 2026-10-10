"""Per-file metrics, appended as JSONL so a crashed run still has evidence."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import ROOT


@dataclass
class FileResult:
    index: int                  # order within the run (drives the learning curve)
    path: str
    outcome: str                # migrated | quarantined | skipped
    attempts: int = 0
    steps: int = 0              # LLM turns + tool calls
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    rollbacks: int = 0
    brain_facts_recalled: int = 0
    brain_facts_written: int = 0
    duration_s: float = 0.0
    modules_importable: int = 0   # headline metric, after this file
    tests_passed: int = 0
    error: str = ""


@dataclass
class RunMetrics:
    run_id: str
    config_name: str            # baseline | no-entire | graph | graph+brain
    target_repo: str
    started_at: float = field(default_factory=time.time)
    files: list[FileResult] = field(default_factory=list)

    @property
    def path(self) -> Path:
        return ROOT / "evidence" / "runs" / f"{self.run_id}.jsonl"

    def record(self, result: FileResult) -> None:
        self.files.append(result)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as fh:
            fh.write(json.dumps({"type": "file", **asdict(result)}) + "\n")

    def finish(self, suite_pass_rate: float, note: str = "",
               modules_importable: int = 0, modules_total: int = 0,
               green_tests: int = 0, baseline_importable: int = 0) -> None:
        summary = {
            "type": "summary",
            "run_id": self.run_id,
            "config_name": self.config_name,
            "target_repo": self.target_repo,
            "files_total": len(self.files),
            "files_migrated": sum(f.outcome == "migrated" for f in self.files),
            "files_quarantined": sum(f.outcome == "quarantined" for f in self.files),
            "files_no_change": sum(f.outcome == "no-change" for f in self.files),
            "suite_pass_rate": suite_pass_rate,
            # The number the whole submission turns on: bump-pydantic scores 0/198.
            "modules_importable": modules_importable,
            "modules_total": modules_total,
            "baseline_importable": baseline_importable,
            "green_tests": green_tests,
            "total_cost_usd": round(sum(f.cost_usd for f in self.files), 4),
            "total_rollbacks": sum(f.rollbacks for f in self.files),
            "duration_s": round(time.time() - self.started_at, 1),
            "note": note,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as fh:
            fh.write(json.dumps(summary) + "\n")
