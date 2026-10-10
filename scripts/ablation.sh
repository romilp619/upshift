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
