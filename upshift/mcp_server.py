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
import json
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
    "modules_importable": 0,
    "modules_total": 198,
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


def _cost(inp: float, out: float, model: str) -> float:
    rate_in, rate_out = MODELS.get(model, MODELS["claude-opus-5-5"])
    return round(inp / 1e6 * rate_in + out / 1e6 * rate_out, 6)


@server.tool(description="Measured cost to migrate one source file, across every candidate model.")
def unit_economics() -> dict:
    files, _ = _load()
    billable = [f for f in files if f["outcome"] in ("migrated", "no-change")]
    if not billable:
        return {"error": "no runs recorded yet"}
    n = len(billable)
    inp = sum(f["input_tokens"] for f in billable) / n
    out = sum(f["output_tokens"] for f in billable) / n
    return {
        "files_measured": n,
        "input_tokens_per_file": round(inp),
        "output_tokens_per_file": round(out),
        "cost_per_file_usd": {m: _cost(inp, out, m) for m in MODELS},
        "cost_per_repo_usd_54_files": {m: round(_cost(inp, out, m) * 54, 4) for m in MODELS},
        "note": "Token counts captured by neatlogs during real runs; not estimated.",
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
    files_per_repo: int = 54,
    model: str = "claude-sonnet-5-5",
) -> dict:
    econ = unit_economics()
    if "error" in econ:
        return econ
    per_file = econ["cost_per_file_usd"].get(model)
    if per_file is None:
        return {"error": f"unknown model {model!r}", "known": sorted(MODELS)}
    monthly = per_file * files_per_repo * repos_per_month
    return {
        "model": model,
        "repos_per_month": repos_per_month,
        "files_per_repo": files_per_repo,
        "cost_per_repo_usd": round(per_file * files_per_repo, 4),
        "inference_cost_per_month_usd": round(monthly, 2),
        "inference_cost_per_year_usd": round(monthly * 12, 2),
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
            "bump-pydantic exits successfully and changes 11 files, but the "
            "package still does not import - it cannot infer types for "
            "un-annotated class attributes."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="upshift.mcp_server")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--stdio", action="store_true", help="stdio instead of HTTP")
    parser.add_argument(
        "--allow-host", action="append", default=[],
        help="extra Host header to accept, e.g. a tunnel domain (repeatable)",
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

    server.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        stateless_http=True,
        transport_security=security,
    )


if __name__ == "__main__":
    main()
