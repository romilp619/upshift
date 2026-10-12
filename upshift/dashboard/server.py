"""Upshift dashboard server.

Drives the existing agent rather than reimplementing it: a run is
`python -m upshift run` in an isolated git worktree, writing the structured
event log from upshift.events. This process only starts it, tails the events,
and reads the run records back. Every number the UI shows comes from one of
those two sources.

    python -m upshift.dashboard --port 8080
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path

import yaml
from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from ..config import ROOT
from ..metrics import migration_status

WORKSPACES = ROOT / "workspaces"
RECORDS = WORKSPACES / "records"          # dashboard runs
EVIDENCE_RUNS = ROOT / "evidence" / "runs"  # curated submission evidence, read-only
STATE = WORKSPACES / "active.json"
STATIC = Path(__file__).resolve().parent / "static"

CONFIGS = {
    "no-entire": {
        "label": "Standard",
        "blurb": "The agent works from the interpreter's own errors and the file "
                 "contents. No Entire context.",
    },
    "graph": {
        "label": "Graph context",
        "blurb": "Adds Entire Graph: definitions, base classes and callers of the "
                 "models in the file. Measured on this benchmark: same result, "
                 "~27% more input.",
    },
    "graph+memory": {
        "label": "Graph + memory",
        "blurb": "Adds lessons carried between files and Entire search over repo "
                 "history. Measured on this benchmark: same result, ~87% more input.",
    },
}

STAGES = ["preparing", "codemod", "imports", "tests", "dependencies", "final"]
STAGE_LABEL = {
    "preparing": "Preparing", "codemod": "Applying codemod",
    "imports": "Repairing imports", "tests": "Repairing tests",
    "dependencies": "Updating dependencies", "final": "Final verification",
}

# Anything shaped like a credential never reaches the browser or a download.
_SECRETS = re.compile(
    r"(sk-ant-[A-Za-z0-9_\-]+|thk_live_[A-Za-z0-9_\-]+|gh[pousr]_[A-Za-z0-9]+|"
    r"github_pat_[A-Za-z0-9_]+|upshift_[A-Za-z0-9]{16,}|"
    r"(?i:bearer\s+|api[-_]?key[\"'\s:=]+)[A-Za-z0-9_\-\.]{16,})")


def redact(text: str) -> str:
    return _SECRETS.sub("[redacted]", text or "")


def _targets() -> dict:
    spec = yaml.safe_load((ROOT / "bench" / "repos.yaml").read_text())
    out = {}
    for t in spec["targets"]:
        base = t.get("baseline") or {}
        before = t.get("under_v2_before") or {}
        out[t["name"]] = {
            "name": t["name"], "url": t["url"], "commit": t["commit"],
            "migration": t.get("migration", "pydantic-v1-to-v2"),
            "dependency": "pydantic", "current": "~=1.10.2", "target": ">=2.9,<3",
            "modules_total": base.get("modules_total"),
            "green_tests": base.get("green_tests"),
            "start_modules": before.get("modules_importable"),
            "codemod": t.get("after_bump_pydantic") or {},
        }
    return out


# --------------------------------------------------------------------------
# run records
# --------------------------------------------------------------------------
def _read_record(path: Path) -> dict | None:
    try:
        rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    except (OSError, json.JSONDecodeError):
        return None
    summary = next((r for r in rows if r.get("type") == "summary"), None)
    files = [r for r in rows if r.get("type") == "file"]
    if summary is None and not files:
        return None
    saved = path.parent == EVIDENCE_RUNS
    if summary is None:
        # No summary: the process never finished. Distinct from "incomplete",
        # which means it finished with failures.
        summary = {"run_id": path.stem, "status": "interrupted",
                   "config_name": path.stem.rsplit("-", 2)[0],
                   "modules_importable": max((f.get("modules_importable") or 0 for f in files),
                                             default=0),
                   "green_tests": max((f.get("tests_passed") or 0 for f in files), default=0)}
    elif "status" not in summary:
        summary["status"] = migration_status(
            summary.get("modules_importable", 0), summary.get("modules_total", 0),
            summary.get("green_tests", 0), summary.get("green_total", 0),
            summary.get("failing_tests", 0))
    worked = [f for f in files if f.get("outcome") != "codemod"]
    return {
        "run_id": summary.get("run_id", path.stem),
        "status": summary.get("status"),
        "config": summary.get("config_name"),
        "target": summary.get("target_repo"),
        "modules_ok": summary.get("modules_importable"),
        "modules_total": summary.get("modules_total"),
        "tests_passed": summary.get("green_tests"),
        "tests_total": summary.get("green_total"),
        "failing_tests": summary.get("failing_tests"),
        "started_modules": summary.get("baseline_importable"),
        "duration_s": summary.get("duration_s"),
        "rollbacks": summary.get("total_rollbacks"),
        "files_migrated": sum(f.get("outcome") == "migrated" for f in worked),
        "files_worked": len(worked),
        "input_tokens": sum(f.get("input_tokens", 0) for f in files),
        "output_tokens": sum(f.get("output_tokens", 0) for f in files),
        "charged_usd": round(sum(f.get("cost_usd", 0) for f in files), 6),
        "model": summary.get("model"),
        "harness": summary.get("harness"),
        "target_commit": summary.get("target_commit"),
        "result_head": summary.get("result_head"),
        "branch": summary.get("branch"),
        "trace_id": summary.get("neatlogs_trace_id"),
        "saved": saved,
        "source": "evidence" if saved else "dashboard",
        "mtime": path.stat().st_mtime,
        "files": files,
    }


def _all_records() -> list[dict]:
    out = []
    for folder in (RECORDS, EVIDENCE_RUNS):
        if folder.exists():
            for p in sorted(folder.glob("*.jsonl")):
                rec = _read_record(p)
                if rec:
                    out.append(rec)
    out.sort(key=lambda r: r["mtime"], reverse=True)
    return out


def _find_record(run_id: str) -> dict | None:
    for folder in (RECORDS, EVIDENCE_RUNS):
        p = folder / f"{run_id}.jsonl"
        if p.exists():
            return _read_record(p)
    return None


# --------------------------------------------------------------------------
# active run
# --------------------------------------------------------------------------
class Run:
    """One agent subprocess and the files it writes."""

    def __init__(self, run_id: str, target: str, config: str):
        self.run_id, self.target, self.config = run_id, target, config
        self.dir = WORKSPACES / run_id
        self.events = self.dir / "events.jsonl"
        self.terminal = self.dir / "terminal.log"
        self.work = self.dir / "work"
        self.proc: subprocess.Popen | None = None
        self.started = time.time()
        self.cancelling = False

    def start(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        RECORDS.mkdir(parents=True, exist_ok=True)
        env = {**os.environ,
               "UPSHIFT_EVENTS": str(self.events),
               "UPSHIFT_RUNS_DIR": str(RECORDS),
               "PYTHONUNBUFFERED": "1"}
        self.proc = subprocess.Popen(
            [str(ROOT / ".venv/bin/python"), "-u", "-m", "upshift", "run",
             "--target", self.target, "--config", self.config,
             "--run-id", self.run_id, "--workdir", str(self.work),
             "--branch", f"upshift/run-{self.run_id}"],
            cwd=ROOT, env=env, stdout=self.terminal.open("w"),
            stderr=subprocess.STDOUT, start_new_session=True)
        STATE.write_text(json.dumps({"run_id": self.run_id, "target": self.target,
                                     "config": self.config, "pid": self.proc.pid,
                                     "started": self.started}))

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def cancel(self) -> None:
        """SIGTERM only. The agent catches it, discards any unverified edit and
        records the run as cancelled - a kill would leave a half-applied file."""
        if self.alive:
            self.cancelling = True
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)


ACTIVE: Run | None = None


def _adopt_existing() -> None:
    """After a server restart, re-attach to a run that is still going."""
    global ACTIVE
    if not STATE.exists():
        return
    try:
        saved = json.loads(STATE.read_text())
        os.kill(saved["pid"], 0)          # raises if gone
    except (OSError, ValueError, KeyError):
        return
    run = Run(saved["run_id"], saved["target"], saved["config"])
    run.started = saved.get("started", time.time())

    class _Attached:
        pid = saved["pid"]
        def poll(self):
            try:
                os.kill(self.pid, 0); return None
            except OSError:
                return 0
    run.proc = _Attached()
    ACTIVE = run


# --------------------------------------------------------------------------
# endpoints
# --------------------------------------------------------------------------
async def api_state(request):
    """Real connection status - each line is checked, not assumed."""
    def ok(cmd, **kw):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=8, **kw).returncode == 0
        except Exception:
            return False

    env = {k: bool(os.environ.get(k)) for k in ("ANTHROPIC_API_KEY", "NEATLOGS_API_KEY")}
    from ..config import CONFIG
    base = CONFIG.base_url or "https://api.anthropic.com"
    entire = ok(["entire", "auth", "status"],
                env={**os.environ, "ENTIRE_TOKEN_STORE": "file",
                     "PATH": f"{Path.home()}/.local/bin:" + os.environ.get("PATH", "")})
    targets = _targets()
    for name, t in targets.items():
        t["cloned"] = (ROOT / "targets" / name).exists()
    return JSONResponse({
        "agent": {"model": CONFIG.model, "endpoint": base,
                  "model_key": env["ANTHROPIC_API_KEY"]},
        "neatlogs": {"configured": env["NEATLOGS_API_KEY"]},
        "entire": {"logged_in": entire},
        "harness": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                  capture_output=True, text=True).stdout.strip(),
        "targets": targets,
        "configs": CONFIGS,
        "stages": [{"id": s, "label": STAGE_LABEL[s]} for s in STAGES],
        "active": ACTIVE.run_id if ACTIVE and ACTIVE.alive else None,
    })


async def api_start(request):
    global ACTIVE
    if ACTIVE and ACTIVE.alive:
        return JSONResponse({"error": "a run is already active",
                             "run_id": ACTIVE.run_id}, status_code=409)
    body = await request.json()
    target, config = body.get("target"), body.get("config")
    if target not in _targets():
        return JSONResponse({"error": f"unsupported repository {target!r}"}, status_code=400)
    if config not in CONFIGS:
        return JSONResponse({"error": f"unknown configuration {config!r}"}, status_code=400)
    from ..config import CONFIG
    if not CONFIG.anthropic_api_key:
        return JSONResponse({"error": "no model API key configured on the server"},
                            status_code=503)
    run_id = f"{config}-{time.strftime('%m%d-%H%M%S')}"
    ACTIVE = Run(run_id, target, config)
    ACTIVE.start()
    return JSONResponse({"run_id": run_id})


async def api_cancel(request):
    run_id = request.path_params["run_id"]
    if not (ACTIVE and ACTIVE.run_id == run_id and ACTIVE.alive):
        return JSONResponse({"error": "not the active run"}, status_code=409)
    ACTIVE.cancel()
    return JSONResponse({"cancelling": True})


async def api_events(request):
    """Resumable event stream. ?from=<seq> replays everything after that
    sequence number, so a refresh or a dropped connection loses nothing."""
    run_id = request.path_params["run_id"]
    run = ACTIVE if (ACTIVE and ACTIVE.run_id == run_id) else None
    path = (run.dir if run else WORKSPACES / run_id) / "events.jsonl"
    start_from = int(request.query_params.get("from", 0))

    async def stream():
        seen = start_from
        idle = 0
        while True:
            if await request.is_disconnected():
                return
            sent = False
            if path.exists():
                with path.open() as fh:
                    for line in fh:
                        try:
                            ev = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if ev.get("seq", 0) > seen:
                            seen = ev["seq"]
                            sent = True
                            yield {"id": str(seen), "event": "run",
                                   "data": json.dumps(ev, default=str)}
            finished = not (run and run.alive)
            if finished and not sent:
                yield {"event": "end", "data": json.dumps({"seq": seen})}
                return
            idle = 0 if sent else idle + 1
            await asyncio.sleep(0.25 if idle < 8 else 0.75)

    return EventSourceResponse(stream())


async def api_terminal(request):
    run_id = request.path_params["run_id"]
    path = WORKSPACES / run_id / "terminal.log"
    if not path.exists():
        return PlainTextResponse("", status_code=200)
    offset = int(request.query_params.get("from", 0))
    data = path.read_bytes()
    return JSONResponse({"text": redact(data[offset:].decode("utf-8", "replace")),
                         "offset": len(data)})


async def api_runs(request):
    return JSONResponse({"runs": [{k: v for k, v in r.items() if k != "files"}
                                  for r in _all_records()]})


async def api_run(request):
    rec = _find_record(request.path_params["run_id"])
    if not rec:
        return JSONResponse({"error": "no such run"}, status_code=404)
    run_dir = WORKSPACES / rec["run_id"]
    rec = dict(rec)
    rec["timeline"] = [f for f in rec.pop("files") if f.get("outcome") != "codemod"]
    rec["has_terminal"] = (run_dir / "terminal.log").exists()
    rec["has_events"] = (run_dir / "events.jsonl").exists()
    if (run_dir / "events.jsonl").exists():
        finals = [json.loads(l) for l in (run_dir / "events.jsonl").read_text().splitlines()
                  if '"final"' in l or '"cancelled"' in l]
        if finals:
            rec["final_event"] = finals[-1]
    return JSONResponse(rec)


async def api_diff(request):
    """The commit the agent made for one file, from the run's own worktree."""
    run_id = request.path_params["run_id"]
    sha = request.query_params.get("commit", "")
    work = WORKSPACES / run_id / "work"
    if not work.exists() or not re.fullmatch(r"[0-9a-f]{4,40}", sha):
        return PlainTextResponse("Not available", status_code=404)
    out = subprocess.run(["git", "show", "--format=%H%n%s%n", sha],
                         cwd=work, capture_output=True, text=True, timeout=20)
    if out.returncode != 0:
        return PlainTextResponse("Not available", status_code=404)
    return PlainTextResponse(redact(out.stdout[:200_000]))


async def api_report(request):
    """A self-contained record of the run, for download."""
    rec = _find_record(request.path_params["run_id"])
    if not rec:
        return JSONResponse({"error": "no such run"}, status_code=404)
    run_dir = WORKSPACES / rec["run_id"]
    report = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "run": {k: v for k, v in rec.items() if k != "files"},
        "timeline": [f for f in rec["files"] if f.get("outcome") != "codemod"],
        "cost_note": "charged_usd is what the model provider recorded. The estimates "
                     "below price the measured tokens at public list rates for other "
                     "models; they are not invoices.",
        "estimates_usd": _estimates(rec["input_tokens"], rec["output_tokens"]),
        "test_scope": "The selected offline regression suite only. Integration tests "
                      "that need the hosted Steamship API were not executed and their "
                      "status is unknown.",
    }
    if (run_dir / "events.jsonl").exists():
        report["events"] = [json.loads(l) for l in
                            (run_dir / "events.jsonl").read_text().splitlines() if l.strip()]
    body = redact(json.dumps(report, indent=2, default=str))
    return PlainTextResponse(body, media_type="application/json", headers={
        "Content-Disposition": f'attachment; filename="upshift-{rec["run_id"]}.json"'})


def _estimates(inp: int, out: int) -> dict:
    prices = {"claude-haiku-5.5": (0.10, 0.50), "claude-sonnet-5.5": (2.0, 10.0),
              "claude-opus-5.5": (4.0, 20.0)}
    return {m: round(inp / 1e6 * a + out / 1e6 * b, 4) for m, (a, b) in prices.items()}


async def api_evidence(request):
    """Real artefacts only. Anything absent is reported as not available."""
    def doc(rel, title, note):
        p = ROOT / rel
        return {"title": title, "path": rel, "note": note, "available": p.exists(),
                "bytes": p.stat().st_size if p.exists() else None}

    records = _all_records()
    traced = [r for r in records if r.get("trace_id")]
    trail = ROOT / "evidence" / "RECOVERY.md"
    ablation = ROOT / "evidence" / "ablation.json"
    return JSONResponse({
        "migration_records": {
            "available": bool(records),
            "total": len(records),
            "complete": sum(r["status"] == "complete" for r in records),
            "evidence_dir": str(EVIDENCE_RUNS.relative_to(ROOT)),
            "ablation": json.loads(ablation.read_text()) if ablation.exists() else None,
        },
        "test_reports": [doc("bench/baseline-python-client.md", "Baseline measurement",
                             "How the codemod and the agent were measured"),
                         doc("bench/bump-pydantic.patch", "Codemod diff",
                             "What bump-pydantic alone changes"),
                         doc("evidence/RECOVERY.md", "Failure and recovery",
                             "Rollbacks, the Trails finding, clean-room verification")],
        "neatlogs": {
            "configured": bool(os.environ.get("NEATLOGS_API_KEY")),
            "console": "https://app.neatlogs.com",
            "runs_with_trace": [{"run_id": r["run_id"], "trace_id": r["trace_id"]}
                                for r in traced],
            "note": "neatlogs has no public per-trace URL scheme documented, so these "
                    "are trace ids to search for in the console, not links.",
        },
        "entire": {
            "trail": "https://entire.io/gh/romilp619/python-client/trails/1",
            "finding": "High severity: code migrated to pydantic v2 while "
                       "requirements.txt still pinned v1. Resolved; the agent now "
                       "updates dependency pins itself.",
            "available": trail.exists(),
        },
        "business": doc("BUSINESS.md", "Business analysis (cfo.ai)",
                        "Pricing and cost, built from this agent's telemetry over MCP"),
    })


async def index(request):
    return FileResponse(STATIC / "index.html")


routes = [
    Route("/api/state", api_state),
    Route("/api/runs", api_runs),
    Route("/api/runs", api_start, methods=["POST"]),
    Route("/api/runs/{run_id}", api_run),
    Route("/api/runs/{run_id}/events", api_events),
    Route("/api/runs/{run_id}/terminal", api_terminal),
    Route("/api/runs/{run_id}/cancel", api_cancel, methods=["POST"]),
    Route("/api/runs/{run_id}/diff", api_diff),
    Route("/api/runs/{run_id}/report", api_report),
    Route("/api/evidence", api_evidence),
    Route("/", index),
    Mount("/static", StaticFiles(directory=str(STATIC)), name="static"),
]

@contextlib.asynccontextmanager
async def lifespan(app):
    _adopt_existing()          # re-attach to a run that outlived a server restart
    yield


app = Starlette(routes=routes, lifespan=lifespan)
