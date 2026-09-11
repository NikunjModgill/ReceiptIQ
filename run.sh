#!/usr/bin/env bash
# One-shot setup + start for ReceiptIQ. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if [ ! -x .venv/bin/python ]; then
  echo "▸ creating virtualenv (.venv)"
  if command -v uv >/dev/null 2>&1; then
    uv venv --seed .venv --python "$PY"
  else
    "$PY" -m venv .venv
  fi
fi

echo "▸ installing dependencies"
if command -v uv >/dev/null 2>&1; then
  uv pip install --python .venv/bin/python -q -r requirements.txt
else
  .venv/bin/pip install -q -r requirements.txt
fi

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
echo "▸ starting ReceiptIQ on http://localhost:${PORT}  (API docs: /docs)"
exec .venv/bin/uvicorn backend.app.main:app --host "$HOST" --port "$PORT" "$@"
