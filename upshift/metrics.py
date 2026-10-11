"""Per-file metrics, appended as JSONL so a crashed run still has evidence."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import ROOT


def migration_status(modules_importable: int, modules_total: int,
                     green_tests: int, green_total: int, failing_tests: int = 0) -> str:
    """"complete" only when every module imports and no regression test fails."""
    if not modules_total or modules_importable < modules_total:
        return "incomplete"
    if failing_tests or not green_total or green_tests < green_total:
        return "incomplete"
    return "complete"


def harness_version() -> str:
    """The Upshift commit that produced a run, marked dirty if uncommitted.

    Two of the first three successful runs used a fix that was not committed
    until after they finished, so their results could not be tied to code.
    """
    import subprocess
    root = Path(__file__).resolve().parent.parent
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root,
                         capture_output=True, text=True).stdout.strip() or "unknown"
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "upshift"], cwd=root,
                           capture_output=True, text=True).stdout.strip()
    return f"{sha}-dirty" if dirty else sha


@dataclass
class FileResult:
    index: int                  # order within the run (drives the learning curve)
    path: str
    outcome: str                # migrated | no-change | redirect | quarantined | codemod
    attempts: int = 0
    steps: int = 0              # LLM turns + tool calls
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    rollbacks: int = 0
    memory_recalled: int = 0    # lessons + entire search hits in the prompt
    memory_written: int = 0
    duration_s: float = 0.0
    modules_importable: int = 0   # headline metric, after this file
    tests_passed: int = 0
    error: str = ""


@dataclass
class RunMetrics:
    run_id: str
    config_name: str            # no-entire | graph | graph+memory
    target_repo: str
    started_at: float = field(default_factory=time.time)
    files: list[FileResult] = field(default_factory=list)

    @property
    def path(self) -> Path:
        # Dashboard runs write elsewhere so the curated evidence - and every
        # figure computed from it - does not change behind the submission.
        import os
        base = Path(os.environ["UPSHIFT_RUNS_DIR"]) if os.environ.get("UPSHIFT_RUNS_DIR") \
            else ROOT / "evidence" / "runs"
        return base / f"{self.run_id}.jsonl"

    def record(self, result: FileResult) -> None:
        self.files.append(result)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as fh:
            fh.write(json.dumps({"type": "file", **asdict(result)}) + "\n")

    def finish(self, suite_pass_rate: float, note: str = "",
               modules_importable: int = 0, modules_total: int = 0,
               green_tests: int = 0, baseline_importable: int = 0,
               green_total: int = 0, failing_tests: int = 0,
               status_override: str = "", **extra) -> None:
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
            # The number the submission turns on: bump-pydantic leaves it at 31/199.
            "modules_importable": modules_importable,
            "modules_total": modules_total,
            "baseline_importable": baseline_importable,
            "green_tests": green_tests,
            "green_total": green_total,
            "failing_tests": failing_tests,
            # A summary means the process finished, not that the migration did.
            # Only a run that imports every module and fails no regression test
            # is a successful migration.
            "status": status_override or migration_status(
                modules_importable, modules_total, green_tests, green_total, failing_tests),
            "harness": harness_version(),
            "total_cost_usd": round(sum(f.cost_usd for f in self.files), 4),
            "total_rollbacks": sum(f.rollbacks for f in self.files),
            "duration_s": round(time.time() - self.started_at, 1),
            "note": note,
            **extra,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as fh:
            fh.write(json.dumps(summary) + "\n")
