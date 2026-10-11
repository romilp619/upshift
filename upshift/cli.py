"""Upshift entrypoints:  python -m upshift <command>"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

from . import obs, report
from .agent import MigrationAgent
from .config import CONFIG, ROOT
from .entire_cli import Entire
from .target import Target

REPOS = ROOT / "bench" / "repos.yaml"


def _load_target(name: str) -> Target:
    spec = yaml.safe_load(REPOS.read_text())["targets"]
    match = next((t for t in spec if t["name"] == name), None)
    if match is None:
        sys.exit(f"unknown target '{name}'. known: {[t['name'] for t in spec]}")
    return Target(
        name=match["name"], url=match["url"],
        commit=match.get("commit", ""), test_cmd=match.get("test_cmd"),
        green_tests=match.get("green_tests_subset"),
    )


def cmd_setup(args):
    target = _load_target(args.target)
    target.clone(fresh=args.fresh)
    print(f"cloned -> {target.path}")
    entire = Entire(repo=target.path)
    entire.enable()
    print("entire enabled")
    entire.graph_index()
    print("graph indexed")
    files = target.pydantic_files()
    print(f"{len(files)} files touch pydantic")
    result = target.run_tests(timeout=600)
    print(f"suite: {result.passed}p/{result.failed}f/{result.errors}e in {result.duration_s}s")
    if result.duration_s > 60:
        print("WARNING: suite is slower than 60s - this target will cost you the weekend")


def cmd_baseline(args):
    """The number to beat: what the official codemod achieves on its own.

    Measured the same way the agent is judged - every module imported from a
    fresh interpreter, plus the offline regression subset - so the comparison
    in the README is like for like.
    """
    target = _load_target(args.target)
    target.clone()
    target.reset()

    def measure(label):
        imports = target.import_check()
        tests = target.run_green()
        print(f"{label:28s} modules {imports.ok}/{imports.total}   green tests {tests.passed}")
        return imports, tests

    before_i, before_t = measure("v2, untouched")
    exe = target.path / ".venv" / "bin" / "bump-pydantic"
    subprocess.run([str(exe) if exe.exists() else "bump-pydantic", "src"],
                   cwd=target.path, capture_output=True, text=True, timeout=1800)
    changed = subprocess.run(["git", "diff", "--name-only"], cwd=target.path,
                             capture_output=True, text=True).stdout.split()
    after_i, after_t = measure(f"v2 + bump-pydantic ({len(changed)} files)")

    out = ROOT / "bench" / f"baseline-{target.name}.txt"
    out.write_text(
        f"target={target.name}\ncommit={target.commit}\n"
        f"untouched_modules={before_i.ok}/{before_i.total}\nuntouched_green_tests={before_t.passed}\n"
        f"codemod_files_changed={len(changed)}\n"
        f"codemod_modules={after_i.ok}/{after_i.total}\ncodemod_green_tests={after_t.passed}\n"
    )
    print(f"saved -> {out}")
    target.reset()


def cmd_run(args):
    missing = CONFIG.missing()
    if missing:
        sys.exit(f"missing env: {', '.join(missing)} (put them in .env)")
    target = _load_target(args.target)
    target.clone()
    target.reset()

    flags = {
        "no-entire":    dict(use_graph=False, use_memory=False),
        "graph":        dict(use_graph=True,  use_memory=False),
        "graph+memory": dict(use_graph=True,  use_memory=True),
    }[args.config]

    obs.init(workflow_name="upshift", tags=[args.config, target.name])
    agent = MigrationAgent(target, config_name=args.config, **flags)
    print(f"run {agent.run_id}: config={args.config}", flush=True)
    try:
        metrics = agent.run(max_iterations=args.max_iterations,
                            codemod_first=not args.no_codemod)
    finally:
        obs.flush()
    print(f"\ndone -> {metrics.path}")


def cmd_report(args):
    runs = args.runs or report.list_runs()
    if not runs:
        sys.exit("no runs yet")
    print("## Ablation\n")
    print(report.ablation(runs))
    # The curve only means anything for an arm that actually carries memory.
    curve_run = next((r for r in reversed(runs) if r.startswith("graph+memory")), runs[-1])
    print(f"\n## Learning curve ({curve_run})\n")
    print(report.curve_table(curve_run))


def main():
    parser = argparse.ArgumentParser(prog="upshift")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("setup", help="clone target, enable Entire, index Graph")
    p.add_argument("--target", required=True)
    p.add_argument("--fresh", action="store_true")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("baseline", help="run bump-pydantic alone - the number to beat")
    p.add_argument("--target", required=True)
    p.set_defaults(func=cmd_baseline)

    p = sub.add_parser("run", help="run the migration agent")
    p.add_argument("--target", required=True)
    p.add_argument("--config", default="graph+memory",
                   choices=["no-entire", "graph", "graph+memory"])
    p.add_argument("--max-iterations", type=int, default=150)
    p.add_argument("--no-codemod", action="store_true",
                   help="skip the bump-pydantic pre-pass")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("report", help="print the evidence tables")
    p.add_argument("--runs", nargs="*")
    p.set_defaults(func=cmd_report)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
