#!/usr/bin/env bash
# Run the API (reload) and the Vite dev server together; Ctrl-C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=".venv/bin/python"
[ -x "$PY" ] || { echo "No .venv found. Run: make setup" >&2; exit 1; }
trap 'kill 0' INT TERM EXIT
"$PY" -m eventshock --reload --port 8000 &
(cd web && npm run dev) &
wait
