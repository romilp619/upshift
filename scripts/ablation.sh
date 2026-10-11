#!/usr/bin/env bash
# Run the three ablation arms in sequence on the same pinned target.
# Each arm resets the target to the pin, so they cannot run in parallel.
# Console output is kept in evidence/logs/ - it is part of the evidence.
set -u
cd "$(dirname "$0")/.."
mkdir -p evidence/logs
progress=evidence/logs/ablation-progress.txt
for cfg in no-entire graph graph+memory; do
  echo "=== $cfg start $(date '+%F %T') ===" >> "$progress"
  timeout 10800 .venv/bin/python -u -m upshift run --target python-client \
      --config "$cfg" --max-iterations 150 2>&1 \
    | grep --line-buffered -vE "neatlogs - (INFO|DEBUG)|ended span|UserWarning|warnings\.warn|validate_by_name|allow_population|Registered package" \
    > "evidence/logs/run-$cfg.log"
  grep -E "^final|^done" "evidence/logs/run-$cfg.log" >> "$progress"
done
echo "=== ALL DONE $(date '+%F %T') ===" >> "$progress"

# Record which runs form this pass, so the README compares arms from one
# harness version rather than whichever run of each arm happens to be newest.
.venv/bin/python - "$progress" <<'PY2'
import json, re, sys, pathlib
text = pathlib.Path(sys.argv[1]).read_text()
start = re.search(r"=== no-entire start (\S+ \S+)", text)
ids = dict(re.findall(r"=== (\S+) start .*?\ndone -> .*/(\S+)\.jsonl", text, flags=re.S))
model = next((l.split("=", 1)[1] for l in pathlib.Path(".env").read_text().splitlines()
              if l.startswith("UPSHIFT_MODEL=")), "unknown")
pathlib.Path("evidence/ablation.json").write_text(json.dumps({
    "note": "The three arms of one ablation pass, run back to back on the same harness.",
    "model": model, "pass_started": start.group(1) if start else None, "runs": ids,
}, indent=2) + "\n")
PY2
