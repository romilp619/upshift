"""Thin wrappers over the Entire CLI.

Design note: Entire is enabled inside the TARGET repo, not this one. Graph indexes the
target's code, Brain remembers the target's conventions, and checkpoints link each
migration commit to the agent session that produced it. That is also why we reset the
target with `git checkout` between runs instead of re-cloning -- re-cloning would throw
away the `.entire/` memory we are trying to measure.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

ENTIRE = shutil.which("entire") or str(Path.home() / ".local/bin/entire")


@dataclass
class CmdResult:
    ok: bool
    stdout: str
    stderr: str

    def __bool__(self) -> bool:
        return self.ok


def _run(args: list[str], cwd: Path, timeout: int = 120) -> CmdResult:
    try:
        proc = subprocess.run(
            [ENTIRE, *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return CmdResult(proc.returncode == 0, proc.stdout.strip(), proc.stderr.strip())
    except FileNotFoundError:
        return CmdResult(False, "", "entire CLI not found on PATH")
    except subprocess.TimeoutExpired:
        return CmdResult(False, "", f"entire {' '.join(args)} timed out after {timeout}s")


class Entire:
    """Everything the agent is allowed to ask Entire for."""

    def __init__(self, repo: Path, use_graph: bool = True, use_brain: bool = True):
        self.repo = Path(repo)
        self.use_graph = use_graph
        self.use_brain = use_brain
        self.graph_queries = 0
        self.facts_recalled = 0
        self.facts_written = 0

    # --- one-time setup -------------------------------------------------
    def setup(self, agent: str = "claude-code") -> dict[str, CmdResult]:
        steps = {
            "enable": _run(["enable", "-y", "--agent", agent], self.repo, 180),
            "graph_install": _run(["plugin", "install", "graph"], self.repo, 300),
            "graph_index": _run(["graph", "index"], self.repo, 600),
            "brain_setup": _run(["brain", "setup"], self.repo, 600),
        }
        return steps

    def status(self) -> str:
        return _run(["brain", "status"], self.repo).stdout

    def graph_stats(self) -> str:
        """Entire's own estimate of tokens saved vs grep. Goes straight in the report."""
        return _run(["graph", "stats"], self.repo, 180).stdout

    # --- graph: where to look -------------------------------------------
    def graph_search(self, query: str) -> str:
        if not self.use_graph:
            return ""
        self.graph_queries += 1
        res = _run(["graph", "search", query], self.repo, 120)
        return res.stdout if res.ok else ""

    # --- brain: what we already learned about THIS repo -------------------
    def brief(self, task: str) -> str:
        if not self.use_brain:
            return ""
        res = _run(["brain", "brief", task], self.repo, 180)
        if res.ok and res.stdout:
            self.facts_recalled += 1
        return res.stdout if res.ok else ""

    def recall(self, search: str) -> str:
        if not self.use_brain:
            return ""
        res = _run(["brain", "recall", search], self.repo, 120)
        if res.ok and res.stdout:
            self.facts_recalled += 1
        return res.stdout if res.ok else ""

    def remember(self, fact: str, path: str = ".") -> bool:
        """The whole point of the project: a lesson learned on file 3 helps file 180."""
        if not self.use_brain:
            return False
        res = _run(["brain", "remember", fact, "--path", path], self.repo, 120)
        if res.ok:
            self.facts_written += 1
        return res.ok

    # --- checkpoints: how to undo ----------------------------------------
    def checkpoint_list(self) -> str:
        return _run(["checkpoint", "list"], self.repo, 120).stdout

    def checkpoint_count(self) -> int:
        out = self.checkpoint_list()
        return sum(1 for line in out.splitlines() if line.strip() and not line.startswith(("ID", "-")))

    def reset_counters(self) -> None:
        self.graph_queries = 0
        self.facts_recalled = 0
        self.facts_written = 0
