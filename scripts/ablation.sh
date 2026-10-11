#!/usr/bin/env bash
# Run the three ablation arms in sequence against the same pinned target.
#
# Guarantees, because an ablation is only meaningful if they hold:
#   - one code version: refuses to start if upshift/ has uncommitted changes,
#     and aborts if HEAD moves while the pass is running;
#   - one model: read once and passed to every arm explicitly;
#   - one starting point: every arm resets the target to the same pinned commit;
#   - nothing overwritten: logs go to a new evidence/ablations/<pass>/ directory;
#   - the comparison (evidence/ablation.json) is replaced only after all three
#     arms finish and each has written a summary. A failed pass leaves the
#     previous comparison in place.
set -u
cd "$(dirname "$0")/.."

if [ -n "$(git status --porcelain -- upshift scripts bench)" ]; then
  echo "refusing to start: uncommitted changes under upshift/, scripts/ or bench/" >&2
  git status --short -- upshift scripts bench >&2
  exit 2
fi

COMMIT=$(git rev-parse --short HEAD)
MODEL=$(grep -E '^UPSHIFT_MODEL=' .env | cut -d= -f2-)
PIN=$(.venv/bin/python -c "import yaml;print(yaml.safe_load(open('bench/repos.yaml'))['targets'][0]['commit'])")
PASS="$(date '+%Y%m%d-%H%M')-${COMMIT}"
DIR="evidence/ablations/${PASS}"
mkdir -p "$DIR"
progress="$DIR/progress.txt"

{
  echo "pass     ${PASS}"
  echo "commit   ${COMMIT}"
  echo "model    ${MODEL}"
  echo "pin      ${PIN}"
} | tee "$progress"

for cfg in no-entire graph graph+memory; do
  if [ "$(git rev-parse --short HEAD)" != "$COMMIT" ]; then
    echo "ABORT: HEAD moved from ${COMMIT} during the pass" | tee -a "$progress" >&2
    exit 3
  fi
  echo "=== $cfg start $(date '+%F %T') ===" | tee -a "$progress"
  UPSHIFT_MODEL="$MODEL" timeout 10800 .venv/bin/python -u -m upshift run \
      --target python-client --config "$cfg" --max-iterations 150 2>&1 \
    | grep --line-buffered -vE "neatlogs - (INFO|DEBUG)|ended span|UserWarning|warnings\.warn|validate_by_name|allow_population|Registered package" \
    > "$DIR/run-$cfg.log"
  grep -E "^final|^COMPLETE|^INCOMPLETE|^run record" "$DIR/run-$cfg.log" | tee -a "$progress"
done
echo "=== ALL DONE $(date '+%F %T') ===" | tee -a "$progress"

# Write this pass's manifest, and only then make it the current comparison.
.venv/bin/python - "$DIR" "$COMMIT" "$MODEL" "$PIN" <<'PY'
import json, pathlib, re, shutil, sys
d, commit, model, pin = pathlib.Path(sys.argv[1]), *sys.argv[2:5]
runs, missing = {}, []
for cfg in ("no-entire", "graph", "graph+memory"):
    log = (d / f"run-{cfg}.log").read_text() if (d / f"run-{cfg}.log").exists() else ""
    m = re.search(r"run record -> \S*/evidence/runs/(\S+)\.jsonl", log)
    if not m:
        missing.append(cfg)
        continue
    path = pathlib.Path("evidence/runs") / f"{m.group(1)}.jsonl"
    summary = next((json.loads(l) for l in path.read_text().splitlines()
                    if json.loads(l).get("type") == "summary"), None)
    if summary is None:
        missing.append(cfg)
        continue
    runs[cfg] = m.group(1)
    if summary.get("harness") != commit:
        sys.exit(f"{cfg} recorded harness {summary.get('harness')!r}, expected {commit!r}")
manifest = {
    "note": "The three arms of one ablation pass, run back to back on the same "
            "commit, model, starting repository and test suite.",
    "pass": d.name, "commit": commit, "model": model, "target_pin": pin,
    "runs": runs,
}
(d / "ablation.json").write_text(json.dumps(manifest, indent=2) + "\n")
if missing:
    sys.exit(f"pass incomplete, comparison NOT updated - no finished run for: {', '.join(missing)}")
current = pathlib.Path("evidence/ablation.json")
import os
if current.exists() and json.loads(current.read_text()).get("final") \
        and os.environ.get("ABLATION_REPLACE_FINAL") != "1":
    # The submitted comparison is frozen. A new pass still records its own
    # manifest under evidence/ablations/, but does not replace the final one.
    sys.exit(f"evidence/ablation.json is marked final - this pass is kept at "
             f"{d}/ablation.json and the comparison was NOT replaced. "
             f"Set ABLATION_REPLACE_FINAL=1 to replace it deliberately.")
if current.exists():
    old = json.loads(current.read_text())
    keep = pathlib.Path("evidence/ablations") / f"{old.get('pass', 'pass-2026-10-11-1119')}.json"
    if not keep.exists():
        shutil.copy(current, keep)
shutil.copy(d / "ablation.json", current)
print(f"comparison updated -> evidence/ablation.json ({d.name})")
PY
