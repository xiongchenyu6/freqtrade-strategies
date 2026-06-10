#!/usr/bin/env bash
# Runs the user-facing Telegram alert dispatcher with secrets.env loaded (sops):
# TELEGRAM_BOT_TOKEN + TIMESCALE_URL both come from secrets.env. Mirrors
# start_telegram_alerts.sh. Inner command is a single quoted string so
# `sops exec-env` doesn't eat flags.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${FREQTRADE_PYTHON:-$PROJECT_DIR/.venv-bots/bin/python}"
cd "$PROJECT_DIR"
exec sops exec-env secrets.env \
    "$PYTHON strategies/alert_dispatcher.py"
