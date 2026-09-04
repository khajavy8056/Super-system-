#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../backend"
exec .venv/bin/python -m pytest tests/ -q "$@"
