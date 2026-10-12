#!/usr/bin/env bash
# Prepare the repository Upshift migrates: steamship-core/python-client at the
# pinned commit, in its own virtualenv, with Pydantic v2 installed - the state a
# team is in right after upgrading.
#
#   bash scripts/setup_target.sh            # uses python3; PYTHON=python3.10 to choose
#
# The pin (3bcc5d7) is upstream 62b3f96 plus .entire/ only, on the fork
# romilp619/python-client. The fork also carries the agent's finished branch,
# upshift/verified, which scripts/verify_result.py measures.
set -euo pipefail
cd "$(dirname "$0")/.."
T=targets/python-client
PIN=3bcc5d794bf40ec29fba9d661791f691ee367c55
PY=${PYTHON:-python3}

if [ ! -d "$T/.git" ]; then
  echo "cloning the target ..."
  git clone --quiet https://github.com/romilp619/python-client "$T"
else
  git -C "$T" fetch --quiet origin
fi
git -C "$T" checkout --quiet --force -B upshift/pydantic-v2 "$PIN"

if [ ! -x "$T/.venv/bin/python" ]; then
  echo "creating $T/.venv with $($PY --version) ..."
  "$PY" -m venv "$T/.venv"
fi
pip="$T/.venv/bin/python -m pip"
echo "installing the target's own dependencies (a few minutes the first time) ..."
$pip install --quiet --upgrade pip
$pip install --quiet -r "$T/requirements.txt" -r "$T/requirements.dev.txt"
$pip install --quiet --no-deps -e "$T"
# Then upgrade to Pydantic v2 - this is the break Upshift repairs. pip will warn
# that steamship requires pydantic~=1.10.2: expected, that pin is the old code.
$pip install --quiet "pydantic==2.14.0" "bump-pydantic==0.8.0"
echo "(a pip warning that steamship requires pydantic~=1.10.2 is expected: that is the break Upshift repairs)"

echo "ready: $T at ${PIN:0:7}, pydantic $("$T/.venv/bin/python" -c 'import pydantic; print(pydantic.VERSION)')"
