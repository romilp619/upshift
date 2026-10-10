"""Entire Trails: submit the agent's work for review and act on what comes back.

A Trail ties a branch to Entire's review surface. Runners -- the per-repo
evaluators (risk, confidence, drift, security, review) created by
`entire runner setup` -- score every push and publish findings.

That matters here because it is verification the agent did not write. Our own
gate (modules importable + the 62-test regression subset) is a gate we chose;
Runner findings are an independent reviewer judging the same diff. The migration
loop treats an unresolved finding exactly like a failing test: fix it, or the
batch is not done.

Everything degrades to a no-op if Trails is not enabled, so `use_trails=False`
is a valid ablation arm rather than a crash.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


def _run(args: list[str], cwd: Path, timeout: int = 180) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["entire", *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout
        )
        return proc.returncode, proc.stdout, proc.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)


@dataclass
class Finding:
    id: str
    title: str
    severity: str
    runner: str
    body: str
    has_suggestion: bool

    @property
    def blocking(self) -> bool:
        return self.severity.lower() in {"high", "critical", "error", "blocker"}

    def __str__(self) -> str:
        return f"[{self.severity}] {self.runner}: {self.title}"


@dataclass
class Trails:
    repo: Path
    enabled: bool = True
    # counters the metrics layer reads back out
    created: int = 0
    findings_seen: int = 0
    findings_resolved: int = 0
    suggestions_applied: int = 0
    _branch: str = field(default="", init=False)

    # --- setup -----------------------------------------------------------
    def runner_setup(self, agent: str = "claude-code") -> bool:
        """Create .entire/runners/*.json. Run once per repo, then commit them."""
        if not self.enabled:
            return False
        code, _, _ = _run(["runner", "setup", "-y", "--agent", agent], self.repo, timeout=900)
        return code == 0

    def available(self) -> bool:
        """Trails is behind a feature flag - check before relying on it."""
        if not self.enabled:
            return False
        code, _, _ = _run(["trail", "list", "--status", "any"], self.repo, timeout=60)
        return code == 0

    # --- lifecycle --------------------------------------------------------
    def create(self, title: str, branch: str, body: str = "", base: str = "") -> bool:
        if not self.enabled:
            return False
        args = ["trail", "create", "--title", title, "--branch", branch]
        if body:
            args += ["--body", body]
        if base:
            args += ["--base", base]
        args += ["--type", "task", "--priority", "medium"]
        code, _, _ = _run(args, self.repo, timeout=300)
        if code == 0:
            self.created += 1
            self._branch = branch
        return code == 0

    def push(self, branch: str) -> bool:
        """Runners only evaluate what has been pushed."""
        code = subprocess.run(
            ["git", "push", "-u", "origin", branch],
            cwd=str(self.repo), capture_output=True, text=True,
        ).returncode
        return code == 0

    # --- findings: the part the agent reacts to ---------------------------
    def findings(self, branch: str = "") -> list[Finding]:
        if not self.enabled:
            return []
        args = ["trail", "finding", "list", "--json", "--freshness", "current"]
        if branch or self._branch:
            args += ["--branch", branch or self._branch]
        code, out, _ = _run(args, self.repo, timeout=180)
        if code != 0 or not out.strip():
            return []
        try:
            payload = json.loads(out)
        except json.JSONDecodeError:
            return []
        rows = payload if isinstance(payload, list) else payload.get("findings", [])
        found = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            found.append(
                Finding(
                    id=str(row.get("id") or row.get("number") or ""),
                    title=row.get("title") or row.get("summary") or "",
                    severity=str(row.get("severity") or row.get("level") or "info"),
                    runner=str(row.get("runner") or row.get("source") or "runner"),
                    body=row.get("body") or row.get("description") or "",
                    has_suggestion=bool(row.get("suggestion") or row.get("diff")),
                )
            )
        self.findings_seen += len(found)
        return found

    def apply_suggestion(self, finding_id: str) -> bool:
        """Some findings ship a unified diff; taking it is cheaper than re-deriving."""
        if not self.enabled:
            return False
        code, _, _ = _run(["trail", "finding", "apply", finding_id], self.repo)
        if code == 0:
            self.suggestions_applied += 1
        return code == 0

    def resolve(self, finding_id: str, note: str = "") -> bool:
        if not self.enabled:
            return False
        args = ["trail", "finding", "resolve", finding_id]
        if note:
            args += ["--body", note]
        code, _, _ = _run(args, self.repo)
        if code == 0:
            self.findings_resolved += 1
        return code == 0

    def blocking_findings(self, branch: str = "") -> list[Finding]:
        return [f for f in self.findings(branch) if f.blocking]

    # --- evidence ---------------------------------------------------------
    def show_json(self, branch: str = "") -> dict:
        if not self.enabled:
            return {}
        args = ["trail", "show", "--json"]
        if branch or self._branch:
            args += ["--branch", branch or self._branch]
        code, out, _ = _run(args, self.repo)
        if code != 0 or not out.strip():
            return {}
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return {}

    def stats(self) -> dict:
        return {
            "trails_created": self.created,
            "findings_seen": self.findings_seen,
            "findings_resolved": self.findings_resolved,
            "suggestions_applied": self.suggestions_applied,
        }
