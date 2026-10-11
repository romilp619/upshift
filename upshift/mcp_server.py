"""MCP server exposing Upshift's financial telemetry to cfo.ai.

cfo.ai is an MCP client, so the integration runs this way round: the agent
publishes what each migration actually cost, and Ari queries it directly
instead of being handed a stale CSV.

Everything served here is measured - token counts come from the
neatlogs-instrumented runs in evidence/runs/, not from estimates.

    python -m upshift.mcp_server --port 8787
"""
from __future__ import annotations

import argparse
import glob
import hmac
import json
import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from .config import ROOT

RUNS = ROOT / "evidence" / "runs"

# USD per 1M tokens (input, output).
MODELS = {
    "deepseek-v4.1-flash:free": (0.0, 0.0),
    "deepseek-v4.1-flash": (0.28, 0.42),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
}

# Measured on steamship-core/python-client - see bench/baseline-python-client.md
CODEMOD_BASELINE = {
    "tool": "bump-pydantic",
    "files_changed": 11,
    "modules_importable": 31,
    "modules_importable_before_codemod": 31,
    "modules_total": 199,
    "green_tests": 0,
}

server = MCPServer(
    name="upshift-telemetry",
    instructions=(
        "Financial telemetry for Upshift, an autonomous code-migration agent. "
        "Use these tools to ground pricing, margin and runway work in measured "
        "cost per migration rather than estimates."
    ),
)


def _load() -> tuple[list[dict], list[dict]]:
    files, summaries = [], []
    for path in sorted(glob.glob(str(RUNS / "*.jsonl"))):
        run_id = Path(path).stem
        for line in open(path):
            record = json.loads(line)
            record["run_id"] = record.get("run_id", run_id)
            (files if record.get("type") == "file" else summaries).append(record)
    return files, summaries


def _completed_runs() -> list[dict]:
    """Per-run token totals for runs that finished (wrote a summary)."""
    runs = []
    for path in sorted(glob.glob(str(RUNS / "*.jsonl"))):
        rows = [json.loads(line) for line in open(path)]
        if not any(r.get("type") == "summary" for r in rows):
            continue
        files = [r for r in rows if r.get("type") == "file"]
        runs.append({
            "run_id": Path(path).stem,
            "steps": len(files),
            "input_tokens": sum(r.get("input_tokens", 0) for r in files),
            "output_tokens": sum(r.get("output_tokens", 0) for r in files),
        })
    return runs


def _median(values: list[float]) -> float:
    values = sorted(values)
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def _cost(inp: float, out: float, model: str) -> float:
    rate_in, rate_out = MODELS.get(model, MODELS["claude-opus-5-5"])
    return round(inp / 1e6 * rate_in + out / 1e6 * rate_out, 6)


@server.tool(description="Measured cost to migrate one source file, across every candidate model.")
def unit_economics() -> dict:
    """Reports median alongside mean.

    Token use per file is heavily skewed - one 10.8k-output file against six
    under 1.4k - so a mean over a handful of files is not a defensible unit
    cost. Repeated files across runs are also counted once, since re-migrating
    the same file is not a second sample.
    """
    files, _ = _load()
    billable = [f for f in files if f["outcome"] in ("migrated", "no-change")]
    if not billable:
        return {"error": "no runs recorded yet"}

    # Latest observation per distinct file.
    distinct: dict[str, dict] = {}
    for f in billable:
        distinct[f["path"]] = f
    rows = list(distinct.values())
    n = len(rows)

    def _median(values: list[float]) -> float:
        values = sorted(values)
        mid = len(values) // 2
        return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2

    ins = [f["input_tokens"] for f in rows]
    outs = [f["output_tokens"] for f in rows]
    mean_in, mean_out = sum(ins) / n, sum(outs) / n
    med_in, med_out = _median(ins), _median(outs)

    return {
        "distinct_files_measured": n,
        "observations": len(billable),
        "input_tokens_per_file": {"median": round(med_in), "mean": round(mean_in)},
        "output_tokens_per_file": {"median": round(med_out), "mean": round(mean_out),
                                   "max": max(outs)},
        "cost_per_file_usd_median": {m: _cost(med_in, med_out, m) for m in MODELS},
        "cost_per_file_usd_mean": {m: _cost(mean_in, mean_out, m) for m in MODELS},
        # A completed run IS one repository migrated, so per-repo cost is
        # measured directly rather than per-file cost times a guessed file
        # count. The guess (198, then 54) overstated it by roughly 60%.
        "cost_per_repo_usd_measured": {
            m: round(_median([_cost(r["input_tokens"], r["output_tokens"], m)
                              for r in _completed_runs()]), 4) if _completed_runs() else None
            for m in MODELS
        },
        "completed_runs_measured": len(_completed_runs()),
        "caveats": [
            f"Per-file figures cover {n} distinct files; per-repo figures come from "
            f"{len(_completed_runs())} complete runs and need no file-count assumption.",
            "Distribution is skewed: one file used 10779 output tokens, the rest under 1400. "
            "Prefer the median for unit cost and the mean only for worst-case budgeting.",
            "All recorded runs used the free model, so these are token counts priced at "
            "list rates, not invoices. No model other than deepseek-v4.1-flash has been "
            "measured for migration quality.",
            "Excludes CI compute, Entire/neatlogs subscriptions, failed-attempt retries "
            "and human review.",
        ],
    }


@server.tool(description="Every migration run recorded, with outcome counts and cost.")
def list_runs() -> dict:
    _, summaries = _load()
    return {
        "runs": [
            {
                "run_id": s.get("run_id"),
                "config": s.get("config_name"),
                "target": s.get("target_repo"),
                "files_total": s.get("files_total"),
                "files_migrated": s.get("files_migrated"),
                "files_quarantined": s.get("files_quarantined"),
                "modules_importable": s.get("modules_importable"),
                "rollbacks": s.get("total_rollbacks"),
                "duration_s": s.get("duration_s"),
            }
            for s in summaries
        ],
        "count": len(summaries),
    }


@server.tool(description="Per-file detail for one run: tokens, attempts, rollbacks, duration.")
def run_detail(run_id: str) -> dict:
    files, _ = _load()
    rows = [f for f in files if f.get("run_id") == run_id]
    if not rows:
        return {"error": f"no run {run_id!r}", "available": sorted({f['run_id'] for f in files})}
    return {"run_id": run_id, "files": rows}


@server.tool(
    description=(
        "Project monthly inference cost for a given volume of migrations. "
        "Use for gross-margin and runway modelling."
    )
)
def cost_projection(
    repos_per_month: int = 100,
    model: str = "claude-sonnet-5-5",
) -> dict:
    """Monthly and yearly inference cost for a volume of migrations.

    Per-repo cost is the measured token use of complete runs priced at list
    rate - each complete run migrated one whole repository. Two bugs fixed:
    this read a key ("cost_per_file_usd") that no longer existed and raised
    KeyError on every call; and it multiplied a per-file median by an assumed
    54 files, which overstated per-repo cost by about 60% against the runs.
    """
    if model not in MODELS:
        return {"error": f"unknown model {model!r}", "known": sorted(MODELS)}
    if repos_per_month < 0:
        return {"error": "repos_per_month must be >= 0"}
    runs = _completed_runs()
    if not runs:
        return {"error": "no completed runs recorded yet"}
    per_repo = [_cost(r["input_tokens"], r["output_tokens"], model) for r in runs]
    median, low, high = _median(per_repo), min(per_repo), max(per_repo)

    def month(per: float) -> float:
        return round(per * repos_per_month, 2)

    return {
        "model": model,
        "repos_per_month": repos_per_month,
        "completed_runs_measured": len(runs),
        "cost_per_repo_usd": {"median": round(median, 4),
                              "min": round(low, 4), "max": round(high, 4)},
        "inference_cost_per_month_usd": {"median": month(median),
                                         "min": month(low), "max": month(high)},
        "inference_cost_per_year_usd": round(month(median) * 12, 2),
        "basis": "measured token use of complete runs at list price; "
                 "runs used a free tier, so these are not invoices",
        "excludes": "CI compute, Entire and neatlogs subscription tiers, salaries",
    }


@server.tool(
    description=(
        "What the agent delivers that the official codemod does not. "
        "This is the value side of the pricing argument."
    )
)
def migration_results() -> dict:
    _, summaries = _load()
    best = max((s.get("modules_importable", 0) for s in summaries), default=0)
    return {
        "target": "steamship-core/python-client",
        "modules_total": CODEMOD_BASELINE["modules_total"],
        "codemod_baseline": CODEMOD_BASELINE,
        "upshift_modules_importable": best,
        "customer_alternative_cost_usd": {
            "contractor_quote": "low five figures",
            "in_house_engineer": "1600-4000 (2-5 days at ~$100/hr loaded)",
        },
        "note": (
            "bump-pydantic exits successfully and changes 11 files but gains "
            "zero importable modules (31/199 before and after) - it cannot "
            "infer types for un-annotated class attributes."
        ),
    }


class ApiKeyMiddleware:
    """Minimal bearer/API-key gate.

    cfo.ai will not attach to an unauthenticated server: it probes for OAuth
    discovery first (/.well-known/oauth-*, /register) and refuses the
    connection when that 404s. It does offer an "API key header" mode, so a
    shared secret is enough - and it stops the tunnel being an open endpoint.

    The header name is not fixed by the spec, so accept the ones clients
    actually send.
    """

    HEADERS = (b"x-api-key", b"api-key", b"authorization", b"x-mcp-api-key")

    def __init__(self, app, api_key: str):
        self.app = app
        self.api_key = api_key

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        supplied = ""
        for name in self.HEADERS:
            raw = headers.get(name)
            if raw:
                supplied = raw.decode().removeprefix("Bearer ").removeprefix("bearer ").strip()
                break
        if not hmac.compare_digest(supplied, self.api_key):
            body = json.dumps({"error": "unauthorized: supply the API key"}).encode()
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


def main() -> None:
    parser = argparse.ArgumentParser(prog="upshift.mcp_server")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--stdio", action="store_true", help="stdio instead of HTTP")
    parser.add_argument(
        "--allow-host", action="append", default=[],
        help="extra Host header to accept, e.g. a tunnel domain (repeatable)",
    )
    parser.add_argument(
        "--api-key", default=os.environ.get("UPSHIFT_MCP_API_KEY", ""),
        help="shared secret clients must send; required for any public tunnel",
    )
    args = parser.parse_args()
    if args.stdio:
        server.run(transport="stdio")
        return

    # cfo.ai is a hosted client reaching us through a tunnel, so it will not
    # hold a session and its Host header is not localhost. MCP blocks unknown
    # Hosts by default (DNS-rebinding protection) - allow the tunnel explicitly.
    security = None
    if args.allow_host:
        from mcp.server.transport_security import TransportSecuritySettings
        security = TransportSecuritySettings(
            allowed_hosts=["127.0.0.1", "localhost", f"127.0.0.1:{args.port}", *args.allow_host],
            allowed_origins=["*"],
        )

    if not args.api_key:
        server.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
            stateless_http=True,
            transport_security=security,
        )
        return

    # Authenticated: build the ASGI app so we can wrap it, and serve it ourselves.
    import uvicorn

    app = ApiKeyMiddleware(
        server.streamable_http_app(
            stateless_http=True,
            transport_security=security,
            host=args.host,
        ),
        args.api_key,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
