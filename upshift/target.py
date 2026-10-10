"""Target repository: clone, discover pydantic files, run tests."""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .config import ROOT

TARGETS_DIR = ROOT / "targets"

_PYDANTIC_HINT = re.compile(r"\b(from|import)\s+pydantic\b|\bBaseModel\b|\bvalidator\b")

# pytest's own summary line, e.g. "=== 12 failed, 103 passed, 2 skipped in 4.11s ==="
_SUMMARY = re.compile(r"(\d+)\s+(passed|failed|error|errors|skipped|xfailed|xpassed)")


@dataclass
class TestResult:
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration_s: float = 0.0
    timed_out: bool = False
    raw_tail: str = ""

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.errors

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def green(self) -> bool:
        return self.failed == 0 and self.errors == 0 and not self.timed_out and self.passed > 0


@dataclass
class Target:
    name: str
    url: str
    commit: str = ""
    test_cmd: list[str] = None
    venv: Path = None

    @property
    def path(self) -> Path:
        return TARGETS_DIR / self.name

    # --- lifecycle -------------------------------------------------------
    def clone(self, fresh: bool = False) -> Path:
        if fresh and self.path.exists():
            shutil.rmtree(self.path)
        if not self.path.exists():
            TARGETS_DIR.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["git", "clone", "--quiet", self.url, str(self.path)], check=True
            )
        if self.commit:
            subprocess.run(
                ["git", "checkout", "--quiet", self.commit], cwd=self.path, check=True
            )
        return self.path

    def reset(self) -> None:
        """Return the working tree to the pinned commit - used between configs."""
        subprocess.run(["git", "reset", "--hard", "--quiet"], cwd=self.path, check=True)
        subprocess.run(["git", "clean", "-qfd"], cwd=self.path, check=True)

    # --- discovery -------------------------------------------------------
    def pydantic_files(self) -> list[Path]:
        hits = []
        for py in sorted(self.path.rglob("*.py")):
            rel = py.relative_to(self.path)
            if any(part in {".git", ".venv", "venv", "build", "dist"} for part in rel.parts):
                continue
            try:
                if _PYDANTIC_HINT.search(py.read_text(errors="ignore")):
                    hits.append(rel)
            except OSError:
                continue
        return hits

    # --- verification ----------------------------------------------------
    def run_tests(self, only: list[str] | None = None, timeout: int = 300) -> TestResult:
        cmd = list(self.test_cmd or ["python", "-m", "pytest", "-q", "--no-header", "-p", "no:randomly"])
        if only:
            cmd += [str(p) for p in only]
        start = time.time()
        try:
            proc = subprocess.run(
                cmd, cwd=self.path, capture_output=True, text=True, timeout=timeout
            )
            out = (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired as exc:
            tail = (exc.stdout or b"").decode(errors="ignore")[-2000:]
            return TestResult(timed_out=True, duration_s=time.time() - start, raw_tail=tail)

        result = TestResult(duration_s=round(time.time() - start, 2), raw_tail=out[-2000:])
        for count, kind in _SUMMARY.findall(out):
            n = int(count)
            if kind == "passed":
                result.passed = n
            elif kind == "failed":
                result.failed = n
            elif kind.startswith("error"):
                result.errors = n
            elif kind == "skipped":
                result.skipped = n
        return result
