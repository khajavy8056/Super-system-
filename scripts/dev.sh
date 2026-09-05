#!/usr/bin/env bash
# Development server (serves the API + web panel on one origin).
set -euo pipefail
cd "$(dirname "$0")/../backend"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
.venv/bin/pip install -q -r requirements.txt
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --reload
