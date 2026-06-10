#!/usr/bin/env bash
# Runs the user-signal evaluator with secrets.env loaded (sops) — TIMESCALE_URL only;
# it touches no exchange keys (public market data). Mirrors start_alert_dispatcher.sh.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${FREQTRADE_PYTHON:-$PROJECT_DIR/.venv-bots/bin/python}"
cd "$PROJECT_DIR"
exec sops exec-env secrets.env \
    "$PYTHON strategies/signal_evaluator.py"
