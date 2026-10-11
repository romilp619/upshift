"""Tests for the telemetry cfo.ai reads over MCP.

Two bugs shipped here without anything noticing: cost_projection read a key
unit_economics no longer returned and raised KeyError on every call, and it
priced a repository as a per-file median times a guessed file count, which
overstated per-repo cost by ~60%. Every tool is now exercised directly and
over the real MCP protocol.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from upshift import mcp_server  # noqa: E402

SONNET = (2.0, 10.0)   # USD per 1M tokens, input / output


def _write_run(path: Path, run_id: str, steps: list[tuple[int, int]], complete=True) -> None:
    with path.open("w") as fh:
        for i, (inp, out) in enumerate(steps, 1):
            fh.write(json.dumps({"type": "file", "index": i, "path": f"src/m{i}.py",
                                 "outcome": "migrated", "attempts": 1, "rollbacks": 0,
                                 "input_tokens": inp, "output_tokens": out,
                                 "modules_importable": 199, "tests_passed": 62}) + "\n")
        if complete:
            fh.write(json.dumps({"type": "summary", "run_id": run_id, "config_name": "graph",
                                 "modules_importable": 199, "modules_total": 199,
                                 "green_tests": 62}) + "\n")


@pytest.fixture
def runs(tmp_path, monkeypatch):
    """Three complete runs with known totals, and one interrupted run."""
    _write_run(tmp_path / "a.jsonl", "a", [(100_000, 50_000)])                   # 0.70
    _write_run(tmp_path / "b.jsonl", "b", [(50_000, 20_000), (50_000, 20_000)])  # 0.60
    _write_run(tmp_path / "c.jsonl", "c", [(200_000, 100_000)])                  # 1.40
    _write_run(tmp_path / "d.jsonl", "d", [(9_000_000, 9_000_000)], complete=False)
    monkeypatch.setattr(mcp_server, "RUNS", tmp_path)
    return tmp_path


def _sonnet(inp, out):
    return inp / 1e6 * SONNET[0] + out / 1e6 * SONNET[1]


# --- cost_projection --------------------------------------------------------

def test_cost_projection_does_not_raise(runs):
    result = mcp_server.cost_projection(250, "claude-sonnet-5-5")
    assert "error" not in result, result


def test_per_repo_cost_is_median_of_complete_runs(runs):
    expected = sorted([_sonnet(100_000, 50_000), _sonnet(100_000, 40_000),
                       _sonnet(200_000, 100_000)])[1]
    got = mcp_server.cost_projection(1, "claude-sonnet-5-5")["cost_per_repo_usd"]
    assert got["median"] == pytest.approx(expected, abs=1e-4)
    assert got["min"] == pytest.approx(_sonnet(100_000, 40_000), abs=1e-4)
    assert got["max"] == pytest.approx(_sonnet(200_000, 100_000), abs=1e-4)


def test_interrupted_runs_are_excluded(runs):
    result = mcp_server.cost_projection(1, "claude-sonnet-5-5")
    assert result["completed_runs_measured"] == 3
    assert result["cost_per_repo_usd"]["max"] < 2.0   # the 18M-token partial run is ignored


def test_monthly_and_yearly_scale_consistently(runs):
    r = mcp_server.cost_projection(250, "claude-sonnet-5-5")
    per = r["cost_per_repo_usd"]["median"]
    assert r["inference_cost_per_month_usd"]["median"] == pytest.approx(per * 250, abs=0.01)
    assert r["inference_cost_per_year_usd"] == pytest.approx(
        r["inference_cost_per_month_usd"]["median"] * 12, abs=0.01)


def test_zero_volume_costs_nothing(runs):
    r = mcp_server.cost_projection(0, "claude-sonnet-5-5")
    assert r["inference_cost_per_month_usd"]["median"] == 0


def test_free_tier_is_zero(runs):
    r = mcp_server.cost_projection(100, "deepseek-v4.1-flash:free")
    assert r["cost_per_repo_usd"]["median"] == 0


def test_bad_inputs_return_errors_not_exceptions(runs):
    assert "error" in mcp_server.cost_projection(10, "gpt-nonexistent")
    assert "error" in mcp_server.cost_projection(-1, "claude-sonnet-5-5")


def test_no_runs_is_an_error_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "RUNS", tmp_path)
    assert "error" in mcp_server.cost_projection(10, "claude-sonnet-5-5")


# --- the other tools --------------------------------------------------------

def test_unit_economics_per_repo_matches_projection(runs):
    ue = mcp_server.unit_economics()
    cp = mcp_server.cost_projection(1, "claude-sonnet-5-5")
    assert ue["cost_per_repo_usd_measured"]["claude-sonnet-5-5"] == pytest.approx(
        cp["cost_per_repo_usd"]["median"], abs=1e-4)


def test_every_tool_runs_on_real_evidence():
    """Against the repo's actual evidence/runs - what cfo.ai sees today."""
    for name, call in [("unit_economics", mcp_server.unit_economics),
                       ("list_runs", mcp_server.list_runs),
                       ("migration_results", mcp_server.migration_results),
                       ("cost_projection", lambda: mcp_server.cost_projection(250))]:
        result = call()
        assert isinstance(result, dict), name
        assert "error" not in result, f"{name}: {result.get('error')}"


def test_run_detail_unknown_id_is_an_error(runs):
    assert "error" in mcp_server.run_detail("does-not-exist")


# --- over the wire, the way cfo.ai calls it ---------------------------------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _rpc(port, key, method, params, ident=1):
    import urllib.request
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/mcp",
        data=json.dumps({"jsonrpc": "2.0", "id": ident, "method": method,
                         "params": params}).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream",
                 **({"X-API-Key": key} if key else {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode()
            status = resp.status
    except urllib.error.HTTPError as exc:
        return exc.code, None
    for line in body.splitlines():
        line = line.removeprefix("data: ").strip()
        if line.startswith("{"):
            return status, json.loads(line)
    return status, None


@pytest.fixture(scope="module")
def server():
    port, key = _free_port(), "test-key-not-secret"
    proc = subprocess.Popen(
        [sys.executable, "-m", "upshift.mcp_server", "--port", str(port), "--api-key", key],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                break
        time.sleep(0.2)
    yield port, key
    proc.terminate()
    proc.wait(timeout=10)


def test_protocol_rejects_missing_key(server):
    port, _ = server
    status, _ = _rpc(port, None, "tools/list", {})
    assert status == 401


def test_protocol_lists_all_five_tools(server):
    port, key = server
    status, msg = _rpc(port, key, "tools/list", {})
    assert status == 200
    names = {t["name"] for t in msg["result"]["tools"]}
    assert names == {"unit_economics", "list_runs", "run_detail",
                     "cost_projection", "migration_results"}


@pytest.mark.parametrize("tool,args", [
    ("unit_economics", {}),
    ("list_runs", {}),
    ("migration_results", {}),
    ("cost_projection", {"repos_per_month": 250, "model": "claude-sonnet-5-5"}),
    ("cost_projection", {}),
])
def test_protocol_tool_call_succeeds(server, tool, args):
    port, key = server
    status, msg = _rpc(port, key, "tools/call", {"name": tool, "arguments": args})
    assert status == 200
    result = msg["result"]
    assert result.get("isError") is not True, result
    payload = json.loads(result["content"][0]["text"])
    assert "error" not in payload, payload


def test_protocol_accepts_the_old_schema(server):
    """cfo.ai may have cached the earlier schema, which had files_per_repo.
    A stale argument must not turn into a failed tool call."""
    port, key = server
    status, msg = _rpc(port, key, "tools/call", {"name": "cost_projection", "arguments": {
        "repos_per_month": 250, "files_per_repo": 54, "model": "claude-sonnet-5-5"}})
    assert status == 200
    assert msg["result"].get("isError") is not True, msg["result"]
