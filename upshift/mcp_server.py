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


def _expected_green(target: str) -> int:
    """Regression-test denominator for a target, from bench/repos.yaml.
    Older run summaries did not record it."""
    try:
        import yaml
        spec = yaml.safe_load((ROOT / "bench" / "repos.yaml").read_text())
        for t in spec.get("targets", []):
            if t.get("name") == target:
                return int(t.get("baseline", {}).get("green_tests", 0))
    except Exception:
        pass
    return 0


def _finished_runs() -> list[dict]:
    """Every run that wrote a summary, classified by outcome.

    A summary only means the process finished. Counting every finished run as
    a migration put eight incomplete runs into the cost sample beside three
    successful ones. Status comes from the summary when it records one; older
    summaries are classified from their counts against the target's
    regression-test denominator.
    """
    from .metrics import migration_status
    runs = []
    for path in sorted(glob.glob(str(RUNS / "*.jsonl"))):
        rows = [json.loads(line) for line in open(path)]
        summary = next((r for r in rows if r.get("type") == "summary"), None)
        if summary is None:
            continue                      # interrupted: never finished
        files = [r for r in rows if r.get("type") == "file"]
        green_total = summary.get("green_total") or _expected_green(summary.get("target_repo", ""))
        status = summary.get("status") or migration_status(
            summary.get("modules_importable", 0), summary.get("modules_total", 0),
            summary.get("green_tests", 0), green_total, summary.get("failing_tests", 0))
        runs.append({
            "run_id": Path(path).stem,
            "config": summary.get("config_name"),
            "status": status,
            "modules": f"{summary.get('modules_importable')}/{summary.get('modules_total')}",
            "green_tests": f"{summary.get('green_tests')}/{green_total or '?'}",
            "harness": summary.get("harness", "not recorded"),
            "steps": len(files),
            "input_tokens": sum(r.get("input_tokens", 0) for r in files),
            "output_tokens": sum(r.get("output_tokens", 0) for r in files),
        })
    return runs


def _spread(values: list[float]) -> dict | None:
    if not values:
        return None
    return {"median": round(_median(values), 4), "min": round(min(values), 4),
            "max": round(max(values), 4), "n": len(values)}


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
        # Per-repository cost from runs that actually migrated the repository.
        # An incomplete run stopped with tests still failing; its cost is real
        # spend but not the price of a migration.
        "cost_per_successful_migration_usd": {
            m: _spread([_cost(r["input_tokens"], r["output_tokens"], m)
                        for r in _finished_runs() if r["status"] == "complete"])
            for m in MODELS
        },
        "migrations": {
            "successful": sum(r["status"] == "complete" for r in _finished_runs()),
            "incomplete": sum(r["status"] != "complete" for r in _finished_runs()),
        },
        "caveats": [
            f"Per-file figures cover {n} distinct files. Per-repository figures come "
            f"only from successful migrations; see cost_projection for the success "
            f"rate and the cost of incomplete runs.",
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
    runs = _finished_runs()
    return {
        "runs": [{k: r[k] for k in ("run_id", "config", "status", "modules",
                                    "green_tests", "harness", "steps")} for r in runs],
        "count": len(runs),
        "successful": sum(r["status"] == "complete" for r in runs),
        "incomplete": sum(r["status"] != "complete" for r in runs),
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
    """Inference cost for a volume of migrations, split by outcome.

    Earlier versions counted every finished run as a migrated repository. A
    finished run can stop with tests still failing, so the sample mixed three
    successful migrations with eight incomplete ones. Successful and
    incomplete runs are now reported separately, with the success rate, and
    two monthly figures: the cost if every run succeeds, and the cost at the
    observed success rate, where failed attempts are paid for too.
    """
    if model not in MODELS:
        return {"error": f"unknown model {model!r}", "known": sorted(MODELS)}
    if repos_per_month < 0:
        return {"error": "repos_per_month must be >= 0"}
    runs = _finished_runs()
    if not runs:
        return {"error": "no finished runs recorded yet"}

    cost = {r["run_id"]: _cost(r["input_tokens"], r["output_tokens"], model) for r in runs}
    ok = [r for r in runs if r["status"] == "complete"]
    bad = [r for r in runs if r["status"] != "complete"]
    success = _spread([cost[r["run_id"]] for r in ok])
    incomplete = _spread([cost[r["run_id"]] for r in bad])
    total = sum(cost.values())
    per_success_all_in = total / len(ok) if ok else None

    def month(per):
        return None if per is None else round(per * repos_per_month, 2)

    return {
        "model": model,
        "repos_per_month": repos_per_month,
        "runs_finished": len(runs),
        "successful_migrations": len(ok),
        "incomplete_migrations": len(bad),
        "success_rate": round(len(ok) / len(runs), 3),
        "cost_per_successful_migration_usd": success,
        "cost_per_incomplete_run_usd": incomplete,
        "cost_per_success_including_failed_attempts_usd":
            None if per_success_all_in is None else round(per_success_all_in, 4),
        "inference_cost_per_month_usd": {
            "if_every_run_succeeds": month(success["median"]) if success else None,
            "at_observed_success_rate": month(per_success_all_in),
        },
        "inference_cost_per_year_usd": {
            "if_every_run_succeeds": None if not success else round(month(success["median"]) * 12, 2),
            "at_observed_success_rate":
                None if per_success_all_in is None else round(month(per_success_all_in) * 12, 2),
        },
        "caveats": [
            "A successful migration imports every module and fails no regression test.",
            "The observed success rate mixes harness versions: incomplete runs predate "
            "fixes that later runs had. Treat it as conservative, and the sample as small.",
            "Runs used a free tier; costs are measured tokens at list price, not invoices.",
        ],
        "excludes": "CI compute, Entire and neatlogs subscription tiers, salaries",
    }


@server.tool(
    description=(
        "What the agent delivers that the official codemod does not. "
        "This is the value side of the pricing argument."
    )
)
def migration_results() -> dict:
    """What the agent delivers, and how often.

    This used to report the best importable-module count across all runs -
    199/199 - which every run reached, including the eight that still had
    failing tests. The value claim is a working repository, so report how many
    runs produced one.
    """
    runs = _finished_runs()
    ok = [r for r in runs if r["status"] == "complete"]
    return {
        "target": "steamship-core/python-client",
        "modules_total": CODEMOD_BASELINE["modules_total"],
        "codemod_baseline": CODEMOD_BASELINE,
        "upshift": {
            "runs_finished": len(runs),
            "successful_migrations": len(ok),
            "success_rate": round(len(ok) / len(runs), 3) if runs else None,
            "successful_result": (
                {"modules": ok[-1]["modules"], "green_tests": ok[-1]["green_tests"]}
                if ok else None),
            "incomplete_results": sorted({r["green_tests"] for r in runs
                                          if r["status"] != "complete"}),
        },
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
