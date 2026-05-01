#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
exec python -m uvicorn backend.main:app --host "${MTGMASTER_HOST:-127.0.0.1}" --port "${MTGMASTER_PORT:-8765}" "$@"
