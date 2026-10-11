"""The migration agent.

Loop: ask the interpreter what is broken -> pick the file that explains the most
failures -> gather context (Entire Graph, Entire search, lessons so far) ->
patch -> verify against the import probe and the regression tests -> keep or
roll back -> write down what was learned.

The interpreter drives the work rather than a file list. A regex over the
source cannot tell which file is actually breaking the build; a traceback can.
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from . import obs
from .config import CONFIG
from .entire_cli import Entire
from .guard import check as guard_check
from .llm import Claude, LLMResult
from .metrics import FileResult, RunMetrics
from .prompts import LESSON_SYSTEM, MIGRATE_SYSTEM
from .target import ImportResult, Target

_FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)
_REDIRECT = re.compile(r"NO_CHANGE_NEEDED:\s*(\S+\.py)")

MAX_PICKS_PER_FILE = 4   # a file with several errors is revisited, but not forever


def _extract_code(text: str) -> str:
    """The migrated file from a fenced reply.

    Two failure modes pull in opposite directions, so neither a greedy nor a
    non-greedy fence match is right on its own:

      * stopping at the first closing fence truncates a file that contains ```
        inside a string - react.py holds a prompt with code blocks in it, and a
        correct 113-line answer was cut to 28;
      * running to the last closing fence swallows the prose and the extra
        block when the model appends an illustrative example.

    So build both candidates and keep the first that is valid Python. A
    truncated file does not parse; a file with prose glued on does not either.
    """
    lines = text.splitlines()
    opens = [i for i, ln in enumerate(lines)
             if ln.strip().startswith("```") and ln.strip() != "```"]
    closes = [i for i, ln in enumerate(lines) if ln.strip() == "```"]
    candidates = []
    if opens:
        first = opens[0]
        after = [c for c in closes if c > first]
        for stop in ([after[0]] if after else []) + ([after[-1]] if len(after) > 1 else []):
            candidates.append("\n".join(lines[first + 1:stop]))
        if not after:
            candidates.append("\n".join(lines[first + 1:]))
    match = _FENCE.search(text)
    if match:
        candidates.append(match.group(1))
    candidates.append(text)

    for candidate in candidates:
        body = candidate.rstrip() + "\n"
        try:
            ast.parse(body)
        except SyntaxError:
            continue
        return body
    return (candidates[0] if candidates else text).rstrip() + "\n"


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


class MigrationAgent:
    def __init__(
        self,
        target: Target,
        config_name: str = "graph+memory",
        use_graph: bool = True,
        use_memory: bool = True,
    ):
        self.target = target
        self.config_name = config_name
        self.use_graph = use_graph
        self.use_memory = use_memory
        self.entire = Entire(repo=target.path, use_graph=use_graph, use_search=use_memory)
        self.llm = Claude()
        self.run_id = f"{config_name}-{time.strftime('%m%d-%H%M')}-{uuid.uuid4().hex[:4]}"
        self.metrics = RunMetrics(
            run_id=self.run_id, config_name=config_name, target_repo=target.name
        )
        self.lessons: list[str] = []
        self.picks: dict[str, int] = {}
        self.redirects: list[str] = []
        self.attempted: dict[str, tuple] = {}   # file -> error signature last tried
        self.best_imports = 0
        self.best_tests = 0

    # --- instrumented tools ---------------------------------------------
    @obs.span(kind="TOOL", tool_name="import_check")
    def _import_check(self) -> ImportResult:
        return self.target.import_check()

    @obs.span(kind="TOOL", tool_name="run_green_tests")
    def _run_green(self):
        return self.target.run_green(timeout=300)

    @obs.span(kind="TOOL", tool_name="run_green_tests_detailed")
    def _run_green_detailed(self):
        return self.target.run_green_detailed(timeout=300)

    @obs.span(kind="RETRIEVER", tool_name="entire_graph_search")
    def _graph_search(self, query: str) -> str:
        return self.entire.graph_search(query)

    @obs.span(kind="RETRIEVER", tool_name="entire_search")
    def _entire_search(self, query: str) -> list[dict]:
        return self.entire.search(query)

    @obs.span(kind="TOOL", tool_name="codemod")
    def _codemod(self) -> int:
        """bump-pydantic first: it does the mechanical renames for free and the
        agent spends its budget on what a codemod cannot infer."""
        exe = self.target.path / ".venv" / "bin" / "bump-pydantic"
        cmd = [str(exe) if exe.exists() else (shutil.which("bump-pydantic") or "bump-pydantic"),
               "src"]
        subprocess.run(cmd, cwd=self.target.path, capture_output=True, text=True, timeout=1800)
        changed = subprocess.run(["git", "diff", "--name-only"], cwd=self.target.path,
                                 capture_output=True, text=True).stdout.split()
        if changed:
            self.target.commit_changes("codemod: bump-pydantic\n\nMechanical v1->v2 renames. "
                               "Upshift finishes what this cannot infer.")
        return len(changed)

    # --- context ---------------------------------------------------------
    def _context_for(self, rel: str, errors: str) -> tuple[str, int]:
        parts, recalled = [], 0
        if self.use_graph:
            graph = self._graph_search(f"definition, base classes and callers of models in {rel}")
            if graph.strip():
                parts.append(f"## Related code (Entire Graph)\n{graph.strip()[:3000]}")
        if self.use_memory:
            if self.lessons:
                parts.append("## Conventions already learned in this repository\n"
                             + "\n".join(f"- {x}" for x in self.lessons[-12:]))
                recalled += len(self.lessons[-12:])
            last_line = errors.strip().splitlines()[-1] if errors.strip() else ""
            hits = self._entire_search(f"pydantic {last_line[:120]} {Path(rel).stem}")
            if hits:
                lines = [f"- {h.get('date', '')[:10]} {h.get('title', '')} ({h.get('id', '')[:8]})"
                         for h in hits]
                parts.append("## Related history in this repo (Entire search)\n" + "\n".join(lines))
                recalled += len(hits)
        return "\n\n".join(parts), recalled

    @staticmethod
    def _errors_for(failures: list[dict], limit: int = 3) -> str:
        """Distinct error messages, plus one traceback tail for orientation."""
        seen, msgs = set(), []
        for f in failures:
            msg = f.get("err", "").splitlines()[0] if f.get("err") else ""
            if msg not in seen:
                seen.add(msg)
                msgs.append(f"{f['module']}: {f.get('err', '')}")
            if len(msgs) >= limit:
                break
        tail = (failures[0].get("tb", "") if failures else "")[-1500:]
        return ("\n".join(msgs) + "\n\nTraceback (tail):\n" + tail).strip()

    def _build_prompt(self, rel: str, original: str, context: str, hint: str,
                      errors: str, blamed: int) -> str:
        chunks = [
            f"# File to fix: {rel}",
            # Without the error the model sees a plausible file, finds nothing
            # wrong and hands it back unchanged. It goes in the first attempt.
            f"## The interpreter is failing in this file ({blamed} modules affected)\n"
            f"```\n{errors}\n```",
        ]
        if context:
            chunks.append(context)
        if hint:
            chunks.append(f"## Your previous attempt was rolled back\n{hint}")
        chunks.append(f"## Current contents of {rel}\n```python\n{original}```")
        return "\n\n".join(chunks)

    # --- one file ----------------------------------------------------------
    def migrate_file(self, rel: str, index: int, before: ImportResult,
                     errors: str | None = None, affected: int | None = None) -> FileResult:
        """One gate for both phases. A patch is kept if it raises importable
        modules, removes import failures blamed on this file, or makes tests
        pass that did not before - and never if importable modules or passing
        tests fall. Import-clean is not the same as working: a v1 Optional field
        with no default is required in v2, so everything imports and then breaks
        the moment the model is constructed. Only the tests see that."""
        started = time.time()
        abs_path = self.target.path / rel
        original = abs_path.read_text()
        result = FileResult(index=index, path=rel, outcome="quarantined")
        blame_before = before.blame(self.target.path).get(rel, [])
        tests_before = self.best_tests
        if errors is None:
            errors = self._errors_for(blame_before)
        if affected is None:
            affected = len(blame_before)

        with obs.trace(f"migrate:{rel}", kind="AGENT", file=rel, index=index):
            context, result.memory_recalled = self._context_for(rel, errors)
            hint = ""
            for attempt in range(1, CONFIG.max_attempts_per_file + 1):
                result.attempts = attempt
                prompt = self._build_prompt(rel, original, context, hint, errors, affected)
                llm: LLMResult = self.llm.ask(MIGRATE_SYSTEM, prompt)
                self._account(result, llm)

                if llm.stop_reason == "max_tokens":
                    # A reply cut at the cap is a truncated file, not a bad
                    # edit. Retrying blind wastes the attempt, so say so.
                    hint = ("Your previous reply hit the output limit and was "
                            "truncated. Return the complete file and nothing "
                            "else - no explanation, no second example block.")
                    result.rollbacks += 1
                    continue

                redirect = _REDIRECT.search(llm.text)
                if redirect and redirect.group(1) == rel:
                    # Pointing at the file it is already editing is not a
                    # redirect; it means "the fix is here" - so make it.
                    hint = (f"You said the root cause is in {rel}. That is this "
                            "file: fix it here and return the complete file.")
                    result.rollbacks += 1
                    continue
                if redirect and (self.target.path / redirect.group(1)).exists():
                    result.outcome = "redirect"
                    result.error = f"root cause is in {redirect.group(1)}"
                    self.redirects.append(redirect.group(1))
                    break

                migrated = _extract_code(llm.text)
                if migrated.strip() == original.strip():
                    result.outcome = "no-change"
                    break

                ok, why = guard_check(original, migrated)
                if not ok:
                    hint = f"The guard rejected it: {why}. Return the complete file."
                    result.rollbacks += 1
                    continue

                abs_path.write_text(migrated)
                after = self._import_check()
                blame_after = after.blame(self.target.path).get(rel, [])

                if after.ok < before.ok:
                    hint = (f"Importable modules fell {before.ok} -> {after.ok}. "
                            f"First new failure: {after.first_failing_module}: {after.first_error}")
                    result.rollbacks += 1
                    self.target.restore_file(rel)
                    continue

                tests, test_failures = self._run_green_detailed()
                if tests.passed < tests_before:
                    broken = "\n".join(f"{f['module']}: {f['err']}" for f in test_failures[:3])
                    hint = (f"Passing regression tests fell {tests_before} -> {tests.passed}.\n"
                            f"{broken}")
                    result.rollbacks += 1
                    self.target.restore_file(rel)
                    continue

                progressed = (after.ok > before.ok
                              or len(blame_after) < len(blame_before)
                              or tests.passed > tests_before)
                if not progressed:
                    mine = self.target.blame_tests(test_failures).get(rel, [])
                    still = (self._errors_for(blame_after, limit=2) if blame_after
                             else "\n".join(f"{f['module']}: {f['err']}" for f in mine[:2])
                             or after.first_error)
                    hint = f"No progress: the same failures remain.\nCurrent error:\n{still}"
                    result.rollbacks += 1
                    self.target.restore_file(rel)
                    continue

                result.outcome = "migrated"
                result.modules_importable = after.ok
                result.tests_passed = tests.passed
                self.best_imports = max(self.best_imports, after.ok)
                self.best_tests = max(self.best_tests, tests.passed)
                lesson = self._learn(rel, original, migrated, result)
                body = f"Modules importable: {before.ok} -> {after.ok}. Tests passing: {tests.passed}."
                if lesson:
                    body += f"\n\nUpshift-Lesson: {lesson}"
                self.target.commit_changes(f"upshift: migrate {rel} to pydantic v2\n\n{body}")
                break

        if result.outcome != "migrated":
            self.target.restore_file(rel)
        result.duration_s = round(time.time() - started, 2)
        self.metrics.record(result)
        return result

    def _learn(self, rel, original, migrated, result) -> str:
        """One repo-specific convention, carried into later prompts and written
        into the commit so Entire search can recall it on a future run."""
        if not self.use_memory:
            return ""
        prompt = (f"File: {rel}\nAttempts needed: {result.attempts}\n\n"
                  f"## Before\n```python\n{original[:4000]}```\n\n"
                  f"## After\n```python\n{migrated[:4000]}```")
        llm = self.llm.ask(LESSON_SYSTEM, prompt, effort="low", max_tokens=1000)
        self._account(result, llm)
        fact = (_extract_json(llm.text).get("fact") or "").strip()
        if fact:
            self.lessons.append(fact)
            result.memory_written += 1
        return fact

    @staticmethod
    def _account(result: FileResult, llm: LLMResult) -> None:
        result.steps += 1
        result.input_tokens += llm.input_tokens + llm.cache_read_tokens
        result.output_tokens += llm.output_tokens
        result.cost_usd = round(result.cost_usd + llm.cost_usd, 6)

    # --- run --------------------------------------------------------------
    def _pick(self, probe: ImportResult) -> str | None:
        """Redirects first (the agent said where the cause is), then the file
        that accounts for the most failing modules."""
        while self.redirects:
            rel = self.redirects.pop(0)
            if self.picks.get(rel, 0) < MAX_PICKS_PER_FILE:
                return rel
        ranked = sorted(probe.blame(self.target.path).items(), key=lambda kv: -len(kv[1]))
        for rel, _ in ranked:
            if self.picks.get(rel, 0) < MAX_PICKS_PER_FILE:
                return rel
        return None

    @obs.span(kind="TOOL", tool_name="bump_dependency_pins")
    def _bump_pins(self, package: str = "pydantic", wanted: str = ">=2.9,<3") -> int:
        """Migrate the project, not just the code.

        An Entire trail runner flagged this on a finished migration: every file
        used v2 APIs while requirements.txt still declared pydantic~=1.10.2, and
        pyproject.toml takes its dependencies from there - so a fresh install
        would pull v1 and fail on import. The import probe cannot catch it,
        because the venv it probes already has v2 installed.
        """
        import re as _re
        changed = []
        for name, _, text in self.target.dependency_pins(package):
            if text.startswith(f"{package}{wanted}"):
                continue
            path = self.target.path / name
            body = path.read_text()
            new = _re.sub(rf"^(\s*[\"']?){_re.escape(package)}\s*[<>=~!][^\"'\n]*",
                          rf"\g<1>{package}{wanted}", body, flags=_re.M)
            if new != body:
                path.write_text(new)
                changed.append(name)
        if changed:
            self.target.commit_changes(
                f"upshift: pin {package}{wanted}\n\n"
                f"The code is migrated; {', '.join(changed)} still declared the old "
                f"version, so a fresh install would pull it and fail on import."
            )
            print(f"pins: updated {', '.join(changed)}", flush=True)
        return len(changed)

    def _print(self, index: int, phase: str, rel: str, result: FileResult,
               probe: ImportResult) -> None:
        tag = {"migrated": "ok  ", "no-change": "same", "redirect": "->  ",
               "quarantined": "QUAR"}[result.outcome]
        shown = result.modules_importable or probe.ok
        tests = result.tests_passed if result.outcome == "migrated" else self.best_tests
        print(f"[{index:>3}] {phase} {tag} {rel:56s} imports={shown:>3}/{probe.total} "
              f"tests={tests:>2} att={result.attempts} rb={result.rollbacks} "
              f"{result.duration_s}s {result.error}", flush=True)

    def run(self, max_iterations: int = 150, codemod_first: bool = True) -> RunMetrics:
        with obs.trace(f"upshift-run:{self.config_name}", kind="WORKFLOW",
                       config=self.config_name, target=self.target.name):
            start = self._import_check()
            print(f"start: {start.ok}/{start.total} modules importable", flush=True)
            if codemod_first:
                changed = self._codemod()
                after = self._import_check()
                self.metrics.record(FileResult(index=0, path="(bump-pydantic)", outcome="codemod",
                                               modules_importable=after.ok, attempts=changed))
                print(f"codemod: {changed} files changed -> {after.ok}/{after.total}", flush=True)
            self.best_tests = self._run_green().passed

            index = 0
            while index < max_iterations:
                probe = self._import_check()
                self.best_imports = max(self.best_imports, probe.ok)
                if probe.bad == 0:
                    print("all modules import", flush=True)
                    break
                rel = self._pick(probe)
                if rel is None:
                    print("no file left that can be moved", flush=True)
                    break
                index += 1
                self.picks[rel] = self.picks.get(rel, 0) + 1
                result = self.migrate_file(rel, index, probe)
                self._print(index, "import", rel, result, probe)

            # Phase 2. Import-clean is not working: v2 makes implicitly-optional
            # fields required, so models import and then fail on construction.
            # Now the regression tests drive: blame each failing test on the
            # model or source file behind it and fix the largest group first.
            self.picks.clear()
            while index < max_iterations:
                tests, failures = self._run_green_detailed()
                self.best_tests = max(self.best_tests, tests.passed)
                if not failures:
                    print("all regression tests pass", flush=True)
                    break
                blame = self.target.blame_tests(failures)
                ranked = sorted(blame.items(), key=lambda kv: -len(kv[1]))

                # Follow redirects first. The agent answers NO_CHANGE_NEEDED
                # with the file holding the root cause, and that file often is
                # not blamed for any failing test itself - the error surfaces
                # in its subclasses. Ranking by blame alone drops the answer:
                # one run redirected to plugin_output.py four times and only
                # fixed it when it happened to surface in the ranking.
                rel = mine = None
                while self.redirects:
                    candidate = self.redirects.pop(0)
                    if not (self.target.path / candidate).exists():
                        continue
                    if self.picks.get(candidate, 0) >= MAX_PICKS_PER_FILE:
                        continue
                    rel = candidate
                    # Give it the failures of whoever pointed here when it has
                    # none of its own, so the prompt still carries an error.
                    mine = blame.get(candidate) or [f for fs in blame.values() for f in fs][:4]
                    break

                if rel is None:
                    pick = next(((r, f) for r, f in ranked
                                 if self.picks.get(r, 0) < MAX_PICKS_PER_FILE), None)
                    if pick is None:
                        print("no test failure left that can be moved", flush=True)
                        break
                    rel, mine = pick
                # A file that quarantines on an unchanged error will quarantine
                # again: same file, same failures, same prompt. Re-picking it
                # cost ~45 minutes on plugin/capabilities.py in one run. Retry
                # only while the error it is blamed for keeps changing.
                signature = tuple(sorted(f["err"][:120] for f in mine))
                if self.attempted.get(rel) == signature:
                    self.picks[rel] = MAX_PICKS_PER_FILE
                    continue
                self.attempted[rel] = signature
                index += 1
                self.picks[rel] = self.picks.get(rel, 0) + 1
                errors = "\n".join(f"{f['module']}: {f['err']}" for f in mine[:4])
                errors += "\n\nTraceback (tail):\n" + mine[0].get("tb", "")[-1500:]
                probe = self._import_check()
                result = self.migrate_file(rel, index, probe, errors=errors, affected=len(mine))
                self._print(index, "tests ", rel, result, probe)
                if result.outcome == "migrated":
                    # The error landscape just changed, so signatures recorded
                    # against other files are stale. Let them be retried.
                    self.attempted = {rel: self.attempted.get(rel)}
                    self.picks = {rel: self.picks.get(rel, 1)}

            self._bump_pins()

            final = self._import_check()
            tests, remaining = self._run_green_detailed()
            self.metrics.finish(
                suite_pass_rate=round(tests.pass_rate, 4),
                modules_importable=final.ok,
                modules_total=final.total,
                green_tests=tests.passed,
                baseline_importable=start.ok,
            )
            print(f"\nfinal: {final.ok}/{final.total} modules importable, "
                  f"{tests.passed} green tests passing", flush=True)
            if final.bad or remaining:
                # Say plainly what is still broken. "done" on the next line
                # refers to the run finishing, not to the migration succeeding.
                print(f"INCOMPLETE - {final.bad} module(s) still fail to import, "
                      f"{len(remaining)} test(s) still failing:", flush=True)
                for f in (final.failures or [])[:5]:
                    print(f"  import  {f['module']}: {f['err'].splitlines()[0][:100]}", flush=True)
                for f in remaining[:8]:
                    print(f"  test    {f['module']}: {f['err'].splitlines()[0][:100]}", flush=True)
                print("  these need a human, or another pass with more iterations", flush=True)
            else:
                print("COMPLETE - every module imports and every regression test passes",
                      flush=True)
        self.unresolved = remaining
        return self.metrics
