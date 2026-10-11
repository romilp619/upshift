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
        frames = [fr.filename for fr in traceback.extract_tb(e.__traceback__)]
        bad.append({{"module": name, "err": f"{{type(e).__name__}}: {{e}}"[:300],
                     "tb": tb[:1500] + "\\n...\\n" + tb[-1000:], "frames": frames}})
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

    @staticmethod
    def frames_of(failure: dict) -> list:
        """Stack frame filenames. Stored structurally by the probe because a
        PydanticUserError embeds the whole offending value - one was a
        multi-kilobyte prompt string - and truncating the text dropped every
        frame, leaving nothing to blame."""
        if failure.get("frames"):
            return list(failure["frames"])
        return re.findall(r'File "([^"]+\.py)", line \d+', failure.get("tb", ""))

    def blame(self, repo: "Path") -> dict:
        """repo-relative file -> the failures whose traceback ends inside it.

        The deepest in-repo frame is where the interpreter actually gave up, so
        it is the best single guess at which file to edit. Ranking files by how
        many failing modules they account for fixes the biggest unlock first.
        """
        out: dict = {}
        for failure in self.failures or []:
            deepest = ""
            for path in self.frames_of(failure):
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
                ["git", "checkout", "--quiet", "--force", "-B", self.branch, self.commit],
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
        self.ensure_entire()

    def ensure_entire(self) -> None:
        """Make sure Entire is still enabled after a reset.

        An earlier reset deleted .entire/ - it had been committed on the work
        branch, so `reset --hard <pin>` removed it as a tracked file - and Entire
        silently reported the repo as "not set up" mid-run. The pin now carries
        .entire/ itself; this restores it from bench/entire/ if it ever goes.
        """
        from .config import ROOT
        dot = self.path / ".entire"
        src = ROOT / "bench" / "entire"
        if (dot / "settings.json").exists() or not src.exists():
            return
        import shutil
        shutil.copytree(src, dot, dirs_exist_ok=True)

    # --- discovery -------------------------------------------------------
    def run_green(self, timeout: int = 300) -> "TestResult":
        """Only the tests that pass offline under v1. The rest need the hosted
        API and would read as regressions that have nothing to do with us."""
        return self.run_tests(only=self.green_tests or None, timeout=timeout)

    def run_green_detailed(self, timeout: int = 300) -> tuple["TestResult", list]:
        """Green subset plus one record per failing test or collection error,
        with a native traceback so failures can be blamed on a source file."""
        import tempfile
        import xml.etree.ElementTree as ET
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as fh:
            report = fh.name
        result = self.run_tests(only=self.green_tests or None, timeout=timeout,
                                extra=["--tb=native", f"--junitxml={report}"])
        failures = []
        try:
            root = ET.parse(report).getroot()
            for case in root.iter("testcase"):
                for kind in ("failure", "error"):
                    el = case.find(kind)
                    if el is None:
                        continue
                    node = case.get("classname", "") + ("::" + case.get("name") if case.get("name") else "")
                    text = el.text or ""
                    # The exception and its detail lines, minus pydantic's doc links.
                    lines = [ln.strip() for ln in text.strip().splitlines()
                             if ln.strip() and "errors.pydantic.dev" not in ln]
                    start = next((i for i in range(len(lines) - 1, -1, -1)
                                  if re.match(r"^[\w.]+(Error|Exception)\b", lines[i])), None)
                    detail = " | ".join(lines[start:start + 6]) if start is not None else \
                        (lines[-1] if lines else el.get("message", ""))
                    failures.append({
                        "module": node,
                        "err": detail[:400],
                        "tb": text[:1500] + "\n...\n" + text[-1500:],
                        "frames": re.findall(r'File "([^"]+\.py)", line \d+', text),
                    })
        except (ET.ParseError, FileNotFoundError):
            pass
        finally:
            Path(report).unlink(missing_ok=True)
        return result, failures

    def blame_tests(self, failures: list) -> dict:
        """src file -> failing tests it most likely explains.

        A "Field required" ValidationError is raised inside the shared base
        model's __init__, so the deepest src frame points at base/model.py while
        the fix belongs in the model that declared the field. Find that model's
        class definition first; fall back to the deepest src frame.
        """
        out: dict = {}
        src = self.path / "src"
        for failure in failures:
            text = failure.get("tb", "") + "\n" + failure.get("err", "")
            target = ""
            m = re.search(r"validation errors? for (\w+)", text)
            if m:
                hit = subprocess.run(
                    ["git", "grep", "-l", "-E", rf"^class {m.group(1)}\b", "--", "src"],
                    cwd=self.path, capture_output=True, text=True,
                ).stdout.split()
                target = hit[0] if hit else ""
            if not target:
                for raw in ImportResult.frames_of(failure):
                    path = Path(raw)
                    try:
                        rel = path.resolve().relative_to(src.resolve().parent)
                    except ValueError:
                        continue
                    if str(rel).startswith("src/"):
                        target = str(rel)
            if not target:
                # Only the test file is on the stack - e.g. `assert a == b` on two
                # serialised models. The culprit is named in the message: resolve
                # the first class it mentions that src/ defines.
                for name in dict.fromkeys(re.findall(r"\b([A-Z][A-Za-z0-9]{3,})\(", text)):
                    hit = subprocess.run(
                        ["git", "grep", "-l", "-E", rf"^class {name}\b", "--", "src"],
                        cwd=self.path, capture_output=True, text=True,
                    ).stdout.split()
                    if hit:
                        target = hit[0]
                        break
            if target:
                out.setdefault(target, []).append(failure)
        return out

    def dependency_pins(self, package: str) -> list[tuple[str, int, str]]:
        """(file, line number, text) for every declared pin of `package`.

        Migrating the code is not migrating the project: pyproject.toml here
        sources its dependencies from requirements.txt, so leaving the old pin
        means a fresh install pulls the version the code no longer supports and
        fails on import. The import probe cannot see this - the venv already
        has the new version - which is why it took an external reviewer to
        notice.
        """
        hits = []
        for name in ("requirements.txt", "requirements.dev.txt", "pyproject.toml", "setup.py"):
            path = self.path / name
            if not path.exists():
                continue
            for number, line in enumerate(path.read_text().splitlines(), 1):
                stripped = line.strip().strip('"\',')
                if re.match(rf"^{re.escape(package)}\s*[<>=~!]", stripped):
                    hits.append((name, number, stripped))
        return hits

    def restore_file(self, rel: str) -> None:
        subprocess.run(["git", "checkout", "HEAD", "--", rel], cwd=self.path,
                       capture_output=True)

    def commit_changes(self, message: str) -> str:
        """Named to avoid the dataclass field `commit`, the pinned SHA."""
        # Only paths that exist: `git add` exits 128 on an unmatched pathspec
        # and stages nothing, so naming setup.py in a repo without one silently
        # dropped every commit in a run.
        paths = [n for n in ("src", "requirements.txt", "requirements.dev.txt",
                             "pyproject.toml", "setup.py", "setup.cfg")
                 if (self.path / n).exists()]
        subprocess.run(["git", "add", "-A", "--", *paths],
                       cwd=self.path, capture_output=True, check=False)
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
    def run_tests(self, only: list[str] | None = None, timeout: int = 300,
                  extra: list[str] | None = None) -> TestResult:
        cmd = list(self.test_cmd or ["python", "-m", "pytest", "-q", "--no-header", "-p", "no:randomly"])
        # By default pytest aborts the whole session on any collection error, so
        # one broken test module reported all 62 tests as 0 passed.
        cmd.append("--continue-on-collection-errors")
        cmd.extend(extra or [])
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
