#!/usr/bin/env bash
# Runs the Telegram alerts pass with secrets.env loaded (sops), so TIMESCALE_URL is
# available — the daily report's Nautilus P&L and check_dca_triggers both query the DB.
# The rename crypto-*→quant-* dropped the original sops-env wrapper; this restores it.
# Inner command is a single quoted string so `sops exec-env` doesn't eat the --all flag.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${FREQTRADE_PYTHON:-$PROJECT_DIR/.venv-bots/bin/python}"
cd "$PROJECT_DIR"
exec sops exec-env secrets.env \
    "$PYTHON strategies/telegram_alerts.py --all"
