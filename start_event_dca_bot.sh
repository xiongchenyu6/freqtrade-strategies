#!/usr/bin/env bash
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${FREQTRADE_PYTHON:-$PROJECT_DIR/../freqtrade/.venv/bin/python}"
cd "$PROJECT_DIR"
exec sops exec-env secrets.env \
    "$PYTHON strategies/event_dca_bot.py"
