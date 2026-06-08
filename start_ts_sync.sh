#!/usr/bin/env bash
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${FREQTRADE_PYTHON:-$PROJECT_DIR/.venv-bots/bin/python}"
cd "$PROJECT_DIR"
exec sops exec-env secrets.env \
    "$PYTHON scripts/sync_local_state_to_timescale.py --quiet"
