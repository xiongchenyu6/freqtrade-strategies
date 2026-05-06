#!/usr/bin/env bash
# Dashboard HTTP server launcher — used by crypto-dashboard.service
# Sources SOPS secrets so md_http_server can connect to TimescaleDB.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${FREQTRADE_PYTHON:-$PROJECT_DIR/../freqtrade/.venv/bin/python}"
cd "$PROJECT_DIR"
exec sops exec-env secrets.env \
    "$PYTHON scripts/md_http_server.py --bind 127.0.0.1 --port 3001"
