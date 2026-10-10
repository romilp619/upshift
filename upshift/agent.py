"""The migration agent: plan -> migrate -> verify -> recover -> remember."""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

from . import obs
from .config import CONFIG
from .entire_cli import Entire, GitCheckpoint
from .guard import check as guard_check
from .llm import Claude, LLMResult
from .metrics import FileResult, RunMetrics
from .prompts import DIAGNOSE_SYSTEM, LESSON_SYSTEM, MIGRATE_SYSTEM
from .target import Target

_FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


def _extract_code(text: str) -> str:
    match = _FENCE.search(text)
    return (match.group(1) if match else text).rstrip() + "\n"


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
        config_name: str = "graph+brain",
        use_graph: bool = True,
        use_brain: bool = True,
        use_checkpoints: bool = True,
    ):
        self.target = target
        self.config_name = config_name
        self.entire = Entire(
            repo=target.path,
            use_graph=use_graph,
            use_brain=use_brain,
            use_checkpoints=use_checkpoints,
        )
        self.git = GitCheckpoint(repo=target.path)
        self.llm = Claude()
        self.run_id = f"{config_name}-{time.strftime('%m%d-%H%M')}-{uuid.uuid4().hex[:4]}"
        self.metrics = RunMetrics(
            run_id=self.run_id, config_name=config_name, target_repo=target.name
        )

    # --- instrumented tools ---------------------------------------------
    @obs.span(kind="RETRIEVER", tool_name="entire_graph_search")
    def _graph_search(self, query: str) -> str:
        return self.entire.graph_search(query)

    @obs.span(kind="RETRIEVER", tool_name="entire_brain_brief")
    def _brain_brief(self, task: str) -> str:
        return self.entire.brain_brief(task)

    @obs.span(kind="TOOL", tool_name="entire_brain_remember")
    def _brain_remember(self, fact: str, scope: str) -> bool:
        return self.entire.brain_remember(fact, scope or ".")

    @obs.span(kind="TOOL", tool_name="run_tests")
    def _run_tests(self, only=None, timeout: int = 300):
        return self.target.run_tests(only=only, timeout=timeout)

    # --- per-file work ---------------------------------------------------
    def _context_for(self, rel: Path) -> tuple[str, int]:
        """Gather Brain decisions + Graph blast radius for one file."""
        parts, recalled = [], 0
        brief = self._brain_brief(f"migrate {rel} from pydantic v1 to v2")
        if brief.strip():
            parts.append(f"## What this repository already decided\n{brief.strip()}")
            recalled = brief.count("\n") + 1
        graph = self._graph_search(f"callers and shared state of {rel}")
        if graph.strip():
            parts.append(f"## Related code (Entire Graph)\n{graph.strip()}")
        return "\n\n".join(parts), recalled

    def migrate_file(self, rel: Path, index: int) -> FileResult:
        started = time.time()
        abs_path = self.target.path / rel
        original = abs_path.read_text()
        result = FileResult(index=index, path=str(rel), outcome="quarantined")

        with obs.trace(f"migrate:{rel}", kind="AGENT", file=str(rel), index=index):
            context, result.brain_facts_recalled = self._context_for(rel)
            savepoint = self.git.save()
            hint = ""

            for attempt in range(1, CONFIG.max_attempts_per_file + 1):
                result.attempts = attempt
                prompt = self._build_prompt(rel, original, context, hint)
                llm: LLMResult = self.llm.ask(MIGRATE_SYSTEM, prompt)
                self._account(result, llm)

                migrated = _extract_code(llm.text)
                ok, why = guard_check(original, migrated)
                if not ok:
                    hint = f"Your previous patch was REJECTED by the guard: {why}. Fix it properly."
                    result.rollbacks += 1
                    self.git.restore(savepoint)
                    continue

                abs_path.write_text(migrated)
                tests = self._run_tests(timeout=300)

                if tests.green or (tests.failed == 0 and tests.errors == 0):
                    result.outcome = "migrated"
                    self._learn(rel, original, migrated, result)
                    break

                # failed: let the agent decide what to do next
                decision = self._diagnose(rel, migrated, tests.raw_tail, attempt, result)
                result.rollbacks += 1
                self.git.restore(savepoint)

                action = decision.get("action", "retry")
                if action == "quarantine":
                    result.error = decision.get("reason", "agent quarantined the file")
                    break
                if action == "need_context":
                    extra = self._graph_search(decision.get("hint", str(rel)))
                    if extra.strip():
                        context += f"\n\n## Additional context\n{extra.strip()}"
                hint = decision.get("hint", "") or f"Tests failed:\n{tests.raw_tail[-1200:]}"

        result.duration_s = round(time.time() - started, 2)
        self.metrics.record(result)
        return result

    # --- helpers ----------------------------------------------------------
    def _build_prompt(self, rel: Path, original: str, context: str, hint: str) -> str:
        chunks = [f"# File to migrate: {rel}"]
        if context:
            chunks.append(context)
        if hint:
            chunks.append(f"## Previous attempt failed\n{hint}")
        chunks.append(f"## Current contents of {rel}\n```python\n{original}```")
        return "\n\n".join(chunks)

    @obs.span(kind="CHAIN", tool_name="diagnose_failure")
    def _diagnose(self, rel, migrated, test_output, attempt, result) -> dict:
        prompt = (
            f"File: {rel}\nAttempt {attempt} of {CONFIG.max_attempts_per_file}\n\n"
            f"## Test output\n{test_output[-3000:]}\n\n"
            f"## The patch that failed\n```python\n{migrated[:6000]}```"
        )
        llm = self.llm.ask(DIAGNOSE_SYSTEM, prompt, effort="medium", max_tokens=2000)
        self._account(result, llm)
        return _extract_json(llm.text)

    @obs.span(kind="CHAIN", tool_name="extract_lesson")
    def _learn(self, rel, original, migrated, result) -> None:
        """Write what we learned about THIS repo into Entire Brain."""
        if not self.entire.use_brain:
            return
        prompt = (
            f"File: {rel}\nAttempts needed: {result.attempts}\n\n"
            f"## Before\n```python\n{original[:4000]}```\n\n"
            f"## After\n```python\n{migrated[:4000]}```"
        )
        llm = self.llm.ask(LESSON_SYSTEM, prompt, effort="low", max_tokens=1000)
        self._account(result, llm)
        lesson = _extract_json(llm.text)
        fact = (lesson.get("fact") or "").strip()
        if fact and self._brain_remember(fact, lesson.get("scope", ".")):
            result.brain_facts_written += 1

    @staticmethod
    def _account(result: FileResult, llm: LLMResult) -> None:
        result.steps += 1
        result.input_tokens += llm.input_tokens + llm.cache_read_tokens
        result.output_tokens += llm.output_tokens
        result.cost_usd = round(result.cost_usd + llm.cost_usd, 6)

    # --- run --------------------------------------------------------------
    def run(self, files: list[Path], commit_each: bool = True) -> RunMetrics:
        with obs.trace(f"upshift-run:{self.config_name}", kind="WORKFLOW",
                       config=self.config_name, target=self.target.name):
            for index, rel in enumerate(files, start=1):
                result = self.migrate_file(rel, index)
                status = "ok " if result.outcome == "migrated" else "QUAR"
                print(
                    f"[{index:>3}/{len(files)}] {status} {rel} "
                    f"steps={result.steps} rollbacks={result.rollbacks} "
                    f"${result.cost_usd:.4f} {result.duration_s}s"
                )
                if result.outcome == "migrated" and commit_each:
                    self.git.commit(f"upshift: migrate {rel} to pydantic v2")
                if index % CONFIG.full_suite_every == 0:
                    suite = self._run_tests(timeout=600)
                    print(f"      full suite: {suite.passed}p/{suite.failed}f/{suite.errors}e")

            final = self._run_tests(timeout=900)
            self.metrics.finish(suite_pass_rate=round(final.pass_rate, 4))
        return self.metrics
