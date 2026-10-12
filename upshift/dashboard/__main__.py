"""Run the dashboard: python -m upshift.dashboard --port 8080"""
from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(prog="upshift.dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    print(f"Upshift dashboard -> http://{args.host}:{args.port}", flush=True)
    uvicorn.run("upshift.dashboard.server:app", host=args.host, port=args.port,
                reload=args.reload, log_level="warning")


if __name__ == "__main__":
    main()
