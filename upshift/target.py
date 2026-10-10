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
import importlib, json, os, sys, traceback
# Enumerate modules from the filesystem, not pkgutil.walk_packages. walk_packages
# only swallows ImportError: any other exception in a package __init__ - a
# PydanticUserError, say - terminates the whole walk, so one broken subpackage
# reported the entire package as 0 importable while most of it loaded fine.
root = os.path.join("src", "{pkg}") if os.path.isdir(os.path.join("src", "{pkg}")) else "{pkg}"
base = os.path.dirname(root)
if base and base not in sys.path:
    sys.path.insert(0, base)
names = []
for dirpath, _, filenames in os.walk(root):
    for fn in sorted(filenames):
        if not fn.endswith(".py"):
            continue
        rel = os.path.relpath(os.path.join(dirpath, fn), base or ".")[:-3]
        mod = rel.replace(os.sep, ".")
        if mod.endswith(".__init__"):
            mod = mod[: -len(".__init__")]
        names.append(mod)
ok, bad = [], []
for name in sorted(set(names)):
    try:
        importlib.import_module(name)
        ok.append(name)
    except BaseException as e:
        tb = traceback.format_exc()
        bad.append({{"module": name, "err": f"{{type(e).__name__}}: {{e}}"[:300], "tb": tb[-2500:]}})
print("UPSHIFT_IMPORTS " + json.dumps({{"ok": len(ok), "bad": len(bad), "failures": bad}}))
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

    def blame(self, repo: "Path") -> dict:
        """repo-relative file -> the failures whose traceback ends inside it.

        The deepest in-repo frame is where the interpreter actually gave up, so
        it is the best single guess at which file to edit. Ranking files by how
        many failing modules they account for fixes the biggest unlock first.
        """
        out: dict = {}
        for failure in self.failures or []:
            tb = failure.get("tb", "")
            deepest = ""
            for match in re.finditer(r'File "([^"]+\.py)", line \d+', tb):
                path = match.group(1)
                if "/site-packages/" in path or "<" in path:
                    continue
                try:
                    deepest = str(Path(path).resolve().relative_to(Path(repo).resolve()))
                except ValueError:
                    continue
            if deepest:
                out.setdefault(deepest, []).append(failure)
        return out

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
    branch: str = "upshift/pydantic-v2"   # Trails are per-branch
    green_tests: list = None              # offline-passing subset: the regression guard

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
            # Check the pin out as a branch, not a bare commit. A detached HEAD
            # cannot carry a Trail, and Entire reports the branch as "HEAD".
            subprocess.run(
                ["git", "checkout", "--quiet", "-B", self.branch, self.commit],
                cwd=self.path, check=True,
            )
        return self.path

    def reset(self, to: str = "") -> None:
        """Return the working tree to the pinned commit - used between configs.

        Keeps .entire/ : that is the Graph index and checkpoint state we are
        trying to measure the effect of, and re-cloning would discard it.
        """
        subprocess.run(
            ["git", "reset", "--hard", "--quiet", to or self.commit or "HEAD"],
            cwd=self.path, check=True,
        )
        subprocess.run(
            ["git", "clean", "-qfd", "--exclude=.entire", "--exclude=.venv"],
            cwd=self.path, check=True,
        )

    # --- discovery -------------------------------------------------------
    def run_green(self, timeout: int = 300) -> "TestResult":
        """Only the tests that pass offline under v1. The rest need the hosted
        API and would read as regressions that have nothing to do with us."""
        return self.run_tests(only=self.green_tests or None, timeout=timeout)

    def restore_file(self, rel: str) -> None:
        subprocess.run(["git", "checkout", "HEAD", "--", rel], cwd=self.path,
                       capture_output=True)

    def commit_changes(self, message: str) -> str:
        """Named to avoid the dataclass field `commit`, the pinned SHA."""
        subprocess.run(["git", "add", "-A", "--", "src"], cwd=self.path, capture_output=True)
        subprocess.run(["git", "-c", "user.name=Upshift", "-c", "user.email=upshift@users.noreply.github.com",
                        "commit", "--no-verify", "-q", "-m", message],
                       cwd=self.path, capture_output=True)
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=self.path,
                              capture_output=True, text=True).stdout.strip()

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
                first_tb = d["failures"][0].get("tb", "") if d["failures"] else ""
                return ImportResult(ok=d["ok"], bad=d["bad"], failures=d["failures"],
                                    traceback=first_tb or combined)
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
