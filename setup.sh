#!/usr/bin/env bash
# One-time setup. Re-run any time to update dependencies.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3.12}"
command -v "$PYTHON" >/dev/null || PYTHON=python3

if ! command -v ffmpeg >/dev/null; then
  echo "ffmpeg is missing. Install it with:  brew install ffmpeg"
  exit 1
fi

[ -d .venv ] || "$PYTHON" -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

if [ "${1:-}" = "--with-whisper" ]; then
  echo "Installing offline transcription (a few hundred MB)…"
  .venv/bin/pip install --quiet -r requirements-whisper.txt
fi

echo "Done. Start it with:  ./run.sh"
