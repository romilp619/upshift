"""Thin wrappers over the Entire CLI: Graph, Brain, Checkpoints.

Every call is best-effort: if Entire is unavailable the agent degrades to a
plain migration run, which is exactly the `no-entire` ablation config.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


def _env() -> dict:
    """WSL, containers and CI have no org.freedesktop.secrets keyring, so the
    Entire CLI cannot read back a token it stored there. Force the file store
    for every subprocess rather than relying on the caller's shell."""
    env = os.environ.copy()
    env.setdefault("ENTIRE_TOKEN_STORE", "file")
    return env


class EntireError(RuntimeError):
    pass


def _run(args: list[str], cwd: Path, timeout: int = 120) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["entire", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_env(),
    )
    return proc.returncode, proc.stdout, proc.stderr


@dataclass
class Entire:
    repo: Path
    use_graph: bool = True
    use_brain: bool = True
    use_checkpoints: bool = True

    # --- setup -----------------------------------------------------------
    def enable(self, agent: str = "claude-code") -> None:
        _run(["enable", "-y", "--agent", agent], self.repo)

    def graph_index(self) -> str:
        if not self.use_graph:
            return ""
        _, out, _ = _run(["graph", "index"], self.repo, timeout=900)
        return out

    def brain_setup(self) -> str:
        if not self.use_brain:
            return ""
        _, out, _ = _run(["brain", "setup"], self.repo, timeout=900)
        return out

    # --- read ------------------------------------------------------------
    def graph_search(self, query: str) -> str:
        """Ranked source regions for a plain-language task description."""
        if not self.use_graph:
            return ""
        code, out, err = _run(["graph", "search", query], self.repo)
        return out if code == 0 else ""

    def brain_brief(self, task: str) -> str:
        """Context Brain has gathered for this task, including past decisions."""
        if not self.use_brain:
            return ""
        code, out, err = _run(["brain", "brief", task], self.repo)
        return out if code == 0 else ""

    def brain_recall(self, search: str) -> str:
        if not self.use_brain:
            return ""
        code, out, err = _run(["brain", "recall", search], self.repo)
        return out if code == 0 else ""

    def search(self, query: str, limit: int = 3) -> list[dict]:
        """Hybrid semantic + keyword search over this repo's checkpoints,
        sessions and commits. `--compact` is the shape Entire documents for
        agents. This is the recall half of the agent's memory: Brain is not in
        CLI 0.11.4, but the repo's own history - including earlier Upshift
        commits that carry the lessons they learned - is searchable here."""
        if not self.use_brain:
            return []
        code, out, _ = _run(["search", query, "--json", "--compact"], self.repo, timeout=60)
        if code != 0 or not out.strip():
            return []
        try:
            rows = json.loads(out).get("results", [])
        except (json.JSONDecodeError, AttributeError):
            return []
        return [r for r in rows if isinstance(r, dict)][:limit]

    # --- write -----------------------------------------------------------
    def brain_remember(self, fact: str, path: str = ".") -> bool:
        """Persist a convention learned about THIS repo, for later files."""
        if not self.use_brain:
            return False
        code, _, _ = _run(["brain", "remember", fact, "--path", path], self.repo)
        return code == 0

    def graph_stats(self) -> str:
        code, out, _ = _run(["graph", "stats"], self.repo)
        return out if code == 0 else ""

    def checkpoint_list(self) -> str:
        code, out, _ = _run(["checkpoint", "list"], self.repo)
        return out if code == 0 else ""


@dataclass
class GitCheckpoint:
    """Git-level save/restore used alongside Entire checkpoints.

    Entire records WHY a change happened (session + checkpoint metadata);
    this gives us the mechanical undo the verifier needs between attempts.
    """
    repo: Path

    def save(self) -> str:
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True, capture_output=True)
        proc = subprocess.run(
            ["git", "stash", "create"], cwd=self.repo, capture_output=True, text=True, check=True
        )
        return proc.stdout.strip()

    def restore(self, ref: str) -> None:
        if not ref:
            subprocess.run(["git", "checkout", "--", "."], cwd=self.repo, capture_output=True)
            return
        subprocess.run(["git", "checkout", ref, "--", "."], cwd=self.repo, capture_output=True)

    def commit(self, message: str) -> None:
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", message, "--no-verify"],
            cwd=self.repo, capture_output=True,
        )
