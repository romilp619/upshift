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


_IMPORT_PROBE = """
import importlib, pkgutil, json, sys
import {pkg}
ok, bad = [], []
for m in pkgutil.walk_packages({pkg}.__path__, "{pkg}."):
    try:
        importlib.import_module(m.name)
        ok.append(m.name)
    except Exception as e:
        bad.append({{"module": m.name, "err": f"{{type(e).__name__}}: {{e}}"[:300]}})
print("UPSHIFT_IMPORTS " + json.dumps({{"ok": len(ok), "bad": len(bad), "failures": bad[:5]}}))
"""


@dataclass
class ImportResult:
    """How many modules import cleanly. The primary gate: pydantic v2 rejects v1
    models at class-creation time, so this measures migration directly - and it
    still works when the package is too broken for pytest to collect."""
    ok: int = 0
    bad: int = 0
    failures: list = None
    crashed: bool = False
    traceback: str = ""

    @property
    def total(self) -> int:
        return self.ok + self.bad

    @property
    def first_error(self) -> str:
        return (self.failures or [{}])[0].get("err", "") if self.failures else ""

    @property
    def first_failing_module(self) -> str:
        return (self.failures or [{}])[0].get("module", "") if self.failures else ""

    def blocking_file(self, repo: "Path") -> str:
        """The source file the interpreter died in, repo-relative.

        Working alphabetically is wasteful: one un-migrated model at the top of
        the import graph hides every module behind it. The traceback already
        names the file to fix, so follow it instead of guessing.
        """
        best = ""
        for match in re.finditer(r'File "([^"]+\.py)", line \d+', self.traceback):
            path = match.group(1)
            if "/site-packages/" in path or "<" in path:
                continue
            try:
                rel = Path(path).resolve().relative_to(Path(repo).resolve())
            except ValueError:
                continue
            best = str(rel)      # deepest frame inside the repo wins
        return best


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
    def next_blocking_file(self) -> str:
        """Repo-relative path of the file currently breaking the import chain."""
        return self.import_check().blocking_file(self.path)

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

    def import_check(self, package: str = "steamship", timeout: int = 300) -> ImportResult:
        """Primary gate. Runs in a fresh isolated interpreter so no module cache
        hides a failure, and -I keeps the target's cwd off sys.path."""
        python = str(self.path / ".venv" / "bin" / "python")
        if not Path(python).exists():
            python = "python3"
        try:
            proc = subprocess.run(
                [python, "-I", "-c", _IMPORT_PROBE.format(pkg=package)],
                cwd=str(self.path), capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return ImportResult(crashed=True)
        combined = (proc.stdout or "") + (proc.stderr or "")
        for line in (proc.stdout or "").splitlines():
            if line.startswith("UPSHIFT_IMPORTS "):
                import json as _json
                d = _json.loads(line[len("UPSHIFT_IMPORTS "):])
                return ImportResult(ok=d["ok"], bad=d["bad"], failures=d["failures"],
                                    traceback=combined)
        # Probe never printed: the package failed at the top-level import.
        tail = combined.strip().splitlines()
        err = tail[-1] if tail else "import failed before probe"
        return ImportResult(ok=0, bad=0, crashed=True, traceback=combined,
                            failures=[{"module": package, "err": err[:300]}])

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
