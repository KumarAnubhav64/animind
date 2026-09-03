#!/usr/bin/env bash
# Start the AniMind backend with hot-reload.
# Uses a Python startup script that properly excludes the media/ directory
# from uvicorn's file watcher (the --reload-exclude CLI flag doesn't reliably
# filter nested paths with watchfiles).
set -euo pipefail
cd "$(dirname "$0")"
exec uv run python run_dev.py
