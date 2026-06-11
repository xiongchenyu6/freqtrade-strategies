#!/usr/bin/env bash
# Daily Telegram report with secrets.env loaded (sops) — TELEGRAM_BOT_TOKEN for the send,
# TIMESCALE_URL for the Nautilus P&L + Growth sections. The unit previously ran the script
# bare (no sops), which silently skipped the send ("Telegram not configured").
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${FREQTRADE_PYTHON:-$PROJECT_DIR/.venv-bots/bin/python}"
cd "$PROJECT_DIR"
exec sops exec-env secrets.env \
    "$PYTHON strategies/telegram_alerts.py --daily"
