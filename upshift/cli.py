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
    entire.brain_setup()
    print("brain ready")
    files = target.pydantic_files()
    print(f"{len(files)} files touch pydantic")
    result = target.run_tests(timeout=600)
    print(f"suite: {result.passed}p/{result.failed}f/{result.errors}e in {result.duration_s}s")
    if result.duration_s > 60:
        print("WARNING: suite is slower than 60s - this target will cost you the weekend")


def cmd_baseline(args):
    """The number to beat: what the official codemod achieves alone."""
    target = _load_target(args.target)
    target.clone()
    target.reset()
    before = target.run_tests(timeout=600)
    files = target.pydantic_files()
    proc = subprocess.run(
        ["bump-pydantic", "."], cwd=target.path, capture_output=True, text=True, timeout=1800
    )
    after = target.run_tests(timeout=600)
    print(f"files touching pydantic : {len(files)}")
    print(f"before : {before.passed}p/{before.failed}f/{before.errors}e  ({before.pass_rate:.1%})")
    print(f"after  : {after.passed}p/{after.failed}f/{after.errors}e  ({after.pass_rate:.1%})")
    print(f"bump-pydantic exit={proc.returncode}")
    out = ROOT / "bench" / f"baseline-{target.name}.txt"
    out.write_text(
        f"target={target.name}\nfiles={len(files)}\n"
        f"before_pass_rate={before.pass_rate:.4f}\nafter_pass_rate={after.pass_rate:.4f}\n"
        f"before={before.passed}p/{before.failed}f/{before.errors}e\n"
        f"after={after.passed}p/{after.failed}f/{after.errors}e\n"
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
        "no-entire":   dict(use_graph=False, use_brain=False, use_checkpoints=False),
        "graph":       dict(use_graph=True,  use_brain=False, use_checkpoints=False),
        "graph+ckpt":  dict(use_graph=True,  use_brain=False, use_checkpoints=True),
        "graph+brain": dict(use_graph=True,  use_brain=True,  use_checkpoints=True),
    }[args.config]

    obs.init(workflow_name="upshift", tags=[args.config, target.name])
    agent = MigrationAgent(target, config_name=args.config, **flags)
    files = target.pydantic_files()[: args.limit] if args.limit else target.pydantic_files()
    print(f"run {agent.run_id}: {len(files)} files, config={args.config}")
    try:
        metrics = agent.run(files)
    finally:
        obs.flush()
    print(f"\ndone -> {metrics.path}")


def cmd_report(args):
    runs = args.runs or report.list_runs()
    if not runs:
        sys.exit("no runs yet")
    print("## Ablation\n")
    print(report.ablation(runs))
    print("\n## Learning curve (last run)\n")
    print(report.curve_table(runs[-1]))


def main():
    parser = argparse.ArgumentParser(prog="upshift")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("setup", help="clone target, enable Entire, index graph, build brain")
    p.add_argument("--target", required=True)
    p.add_argument("--fresh", action="store_true")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("baseline", help="run bump-pydantic alone - the number to beat")
    p.add_argument("--target", required=True)
    p.set_defaults(func=cmd_baseline)

    p = sub.add_parser("run", help="run the migration agent")
    p.add_argument("--target", required=True)
    p.add_argument("--config", default="graph+brain",
                   choices=["no-entire", "graph", "graph+ckpt", "graph+brain"])
    p.add_argument("--limit", type=int, default=0)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("report", help="print the evidence tables")
    p.add_argument("--runs", nargs="*")
    p.set_defaults(func=cmd_report)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
