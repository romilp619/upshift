"""Tests for the telemetry cfo.ai reads over MCP.

Three bugs shipped here without a test noticing:

  * cost_projection read a key unit_economics no longer returned, and raised
    KeyError on every call;
  * it priced a repository as a per-file median times a guessed file count;
  * it treated every run that wrote a summary as a migrated repository. A
    summary means the process finished, not that the migration succeeded -
    eight of eleven finished runs still had failing tests.

The fixture below deliberately mixes outcomes. The previous one made every
synthetic run a success, which is how the third bug got through.
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from upshift import mcp_server  # noqa: E402
from upshift.metrics import FileResult, RunMetrics, migration_status  # noqa: E402

SONNET = (2.0, 10.0)   # USD per 1M tokens, input / output


def _sonnet(inp, out):
    return inp / 1e6 * SONNET[0] + out / 1e6 * SONNET[1]


def _write_run(path: Path, steps, *, summary: dict | None) -> None:
    with path.open("w") as fh:
        for i, (inp, out) in enumerate(steps, 1):
            fh.write(json.dumps({"type": "file", "index": i, "path": f"src/m{i}.py",
                                 "outcome": "migrated", "attempts": 1, "rollbacks": 0,
                                 "input_tokens": inp, "output_tokens": out}) + "\n")
        if summary is not None:
            fh.write(json.dumps({"type": "summary", "config_name": "graph",
                                 "target_repo": "python-client",
                                 "modules_total": 199, **summary}) + "\n")


COMPLETE = {"modules_importable": 199, "green_tests": 62, "green_total": 62,
            "failing_tests": 0, "status": "complete"}


@pytest.fixture
def runs(tmp_path, monkeypatch):
    # two successful migrations
    _write_run(tmp_path / "ok1.jsonl", [(100_000, 50_000)], summary=COMPLETE)      # $0.70
    _write_run(tmp_path / "ok2.jsonl", [(200_000, 100_000)], summary=COMPLETE)     # $1.40
    # finished, wrote a summary, but a test still fails - the regression case
    _write_run(tmp_path / "fail_new.jsonl", [(50_000, 20_000)], summary={
        "modules_importable": 199, "green_tests": 61, "green_total": 62,
        "failing_tests": 1, "status": "incomplete"})                               # $0.30
    # an older summary with no status field: classified from its counts against
    # the target's denominator (62, from bench/repos.yaml)
    _write_run(tmp_path / "fail_legacy.jsonl", [(30_000, 10_000)], summary={
        "modules_importable": 199, "green_tests": 56})                             # $0.16
    # interrupted: never wrote a summary
    _write_run(tmp_path / "interrupted.jsonl", [(9_000_000, 9_000_000)], summary=None)
    monkeypatch.setattr(mcp_server, "RUNS", tmp_path)
    return tmp_path


# --- the regression the user asked for --------------------------------------

def test_run_with_summary_but_failing_tests_is_incomplete(runs):
    by_id = {r["run_id"]: r for r in mcp_server._finished_runs()}
    assert by_id["fail_new"]["status"] == "incomplete"
    assert by_id["fail_legacy"]["status"] == "incomplete"
    assert by_id["ok1"]["status"] == "complete"


def test_summary_writer_marks_failing_tests_incomplete(tmp_path, monkeypatch):
    """At the source: a run that finishes with a failing test must not be
    written as complete, whatever else it achieved."""
    import upshift.metrics as metrics
    monkeypatch.setattr(metrics, "ROOT", tmp_path)
    m = RunMetrics(run_id="x", config_name="graph", target_repo="python-client")
    m.record(FileResult(index=1, path="src/a.py", outcome="migrated"))
    m.finish(suite_pass_rate=0.98, modules_importable=199, modules_total=199,
             green_tests=61, green_total=62, failing_tests=1, baseline_importable=31)
    summary = [json.loads(l) for l in m.path.read_text().splitlines()][-1]
    assert summary["status"] == "incomplete"
    assert summary["failing_tests"] == 1
    assert summary["harness"]                      # which code produced it


@pytest.mark.parametrize("modules,total,green,gtotal,failing,expected", [
    (199, 199, 62, 62, 0, "complete"),
    (199, 199, 61, 62, 1, "incomplete"),   # summary written, a test still fails
    (199, 199, 61, 62, 0, "incomplete"),   # short of the denominator
    (198, 199, 62, 62, 0, "incomplete"),   # a module still fails to import
    (199, 199, 0, 0, 0, "incomplete"),     # no tests ran at all
])
def test_migration_status_rules(modules, total, green, gtotal, failing, expected):
    assert migration_status(modules, total, green, gtotal, failing) == expected


# --- cost_projection --------------------------------------------------------

def test_counts_and_success_rate(runs):
    r = mcp_server.cost_projection(1, "claude-sonnet-5-5")
    assert r["runs_finished"] == 4                 # interrupted excluded
    assert r["successful_migrations"] == 2
    assert r["incomplete_migrations"] == 2
    assert r["success_rate"] == 0.5


def test_successful_cost_excludes_incomplete_runs(runs):
    r = mcp_server.cost_projection(1, "claude-sonnet-5-5")
    ok = r["cost_per_successful_migration_usd"]
    assert ok["n"] == 2
    assert ok["min"] == pytest.approx(_sonnet(100_000, 50_000), abs=1e-4)
    assert ok["max"] == pytest.approx(_sonnet(200_000, 100_000), abs=1e-4)
    bad = r["cost_per_incomplete_run_usd"]
    assert bad["n"] == 2
    assert bad["max"] == pytest.approx(_sonnet(50_000, 20_000), abs=1e-4)


def test_cost_per_success_pays_for_failed_attempts(runs):
    r = mcp_server.cost_projection(1, "claude-sonnet-5-5")
    total = (_sonnet(100_000, 50_000) + _sonnet(200_000, 100_000)
             + _sonnet(50_000, 20_000) + _sonnet(30_000, 10_000))
    assert r["cost_per_success_including_failed_attempts_usd"] == pytest.approx(total / 2, abs=1e-4)


def test_two_monthly_figures(runs):
    r = mcp_server.cost_projection(250, "claude-sonnet-5-5")
    month = r["inference_cost_per_month_usd"]
    assert month["if_every_run_succeeds"] == pytest.approx(
        r["cost_per_successful_migration_usd"]["median"] * 250, abs=0.01)
    assert month["at_observed_success_rate"] == pytest.approx(
        r["cost_per_success_including_failed_attempts_usd"] * 250, abs=0.01)
    assert month["at_observed_success_rate"] > month["if_every_run_succeeds"]


def test_no_successes_reports_none_not_a_crash(tmp_path, monkeypatch):
    _write_run(tmp_path / "f.jsonl", [(10_000, 10_000)], summary={
        "modules_importable": 199, "green_tests": 61, "green_total": 62,
        "failing_tests": 1, "status": "incomplete"})
    monkeypatch.setattr(mcp_server, "RUNS", tmp_path)
    r = mcp_server.cost_projection(10, "claude-sonnet-5-5")
    assert r["successful_migrations"] == 0
    assert r["cost_per_successful_migration_usd"] is None
    assert r["inference_cost_per_month_usd"]["at_observed_success_rate"] is None


def test_zero_volume_and_free_tier(runs):
    assert mcp_server.cost_projection(0, "claude-sonnet-5-5")[
        "inference_cost_per_month_usd"]["if_every_run_succeeds"] == 0
    assert mcp_server.cost_projection(5, "deepseek-v4.1-flash:free")[
        "cost_per_successful_migration_usd"]["median"] == 0


def test_bad_inputs_return_errors_not_exceptions(runs):
    assert "error" in mcp_server.cost_projection(10, "gpt-nonexistent")
    assert "error" in mcp_server.cost_projection(-1, "claude-sonnet-5-5")


def test_no_runs_is_an_error_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "RUNS", tmp_path)
    assert "error" in mcp_server.cost_projection(10, "claude-sonnet-5-5")


# --- the other tools agree --------------------------------------------------

def test_all_tools_agree_on_outcomes(runs):
    cp = mcp_server.cost_projection(1, "claude-sonnet-5-5")
    ue = mcp_server.unit_economics()
    lr = mcp_server.list_runs()
    mr = mcp_server.migration_results()["upshift"]
    assert ue["migrations"] == {"successful": 2, "incomplete": 2}
    assert (lr["successful"], lr["incomplete"]) == (2, 2)
    assert mr["successful_migrations"] == cp["successful_migrations"] == 2
    assert ue["cost_per_successful_migration_usd"]["claude-sonnet-5-5"]["median"] == \
        pytest.approx(cp["cost_per_successful_migration_usd"]["median"], abs=1e-4)


def test_migration_results_does_not_report_an_incomplete_run_as_the_result(runs):
    mr = mcp_server.migration_results()["upshift"]
    assert mr["successful_result"]["green_tests"] == "62/62"
    assert "61/62" in mr["incomplete_results"]


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
    import urllib.error
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
            body, status = resp.read().decode(), resp.status
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
    assert {t["name"] for t in msg["result"]["tools"]} == {
        "unit_economics", "list_runs", "run_detail", "cost_projection", "migration_results"}


@pytest.mark.parametrize("tool,args", [
    ("unit_economics", {}),
    ("list_runs", {}),
    ("migration_results", {}),
    ("cost_projection", {"repos_per_month": 250, "model": "claude-sonnet-5-5"}),
    ("cost_projection", {}),
    # cfo.ai may have cached an earlier schema that still had files_per_repo
    ("cost_projection", {"repos_per_month": 250, "files_per_repo": 54}),
])
def test_protocol_tool_call_succeeds(server, tool, args):
    port, key = server
    status, msg = _rpc(port, key, "tools/call", {"name": tool, "arguments": args})
    assert status == 200
    assert msg["result"].get("isError") is not True, msg["result"]
    assert "error" not in json.loads(msg["result"]["content"][0]["text"])


def test_protocol_cost_projection_separates_outcomes(server):
    port, key = server
    _, msg = _rpc(port, key, "tools/call", {"name": "cost_projection",
                                           "arguments": {"repos_per_month": 250}})
    payload = json.loads(msg["result"]["content"][0]["text"])
    assert payload["successful_migrations"] + payload["incomplete_migrations"] == \
        payload["runs_finished"]
    assert set(payload["inference_cost_per_month_usd"]) == {
        "if_every_run_succeeds", "at_observed_success_rate"}
