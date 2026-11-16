#!/usr/bin/env bash
# Start the API, the read-only server and the web app. Ports: GENSTAGE_API_PORT (8780), GENSTAGE_READONLY_PORT (8781),
# GENSTAGE_WEB_PORT (4280), or the options of scripts/start.py. Run ./install.sh once first.
set -euo pipefail
cd "$(dirname "$0")/server"
if [ ! -d .venv ]; then echo "Not installed yet. Run ./install.sh first." >&2; exit 1; fi
exec uv run --no-sync python ../scripts/start.py "$@"
