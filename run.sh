#!/usr/bin/env bash
# Start the local server and open it in your browser.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"
[ -d .venv ] || { echo "Run ./setup.sh first."; exit 1; }

echo "Transcript Study → http://localhost:$PORT"
( sleep 1.5; command -v open >/dev/null && open "http://localhost:$PORT" ) &
exec .venv/bin/uvicorn app:app --app-dir backend --host 127.0.0.1 --port "$PORT"
