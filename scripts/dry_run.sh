#!/usr/bin/env bash
# Offline dry-run using samples/ (no network required).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
  .venv/bin/pip install -e .
fi
# shellcheck disable=SC1091
source .venv/bin/activate
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
python -m tw_etf_pages dry-run "$@"
echo "Open: ${ROOT}/site/index.html"
