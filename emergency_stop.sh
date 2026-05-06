#!/usr/bin/env bash
# EMERGENCY STOP — kills bot + closes all positions + alerts Telegram
#
# Usage:
#   ./emergency_stop.sh          # stop everything
#   ./emergency_stop.sh --keep   # stop bot but DON'T close positions
#
# This script is for BLACK SWAN events: flash crashes, exchange hacks,
# regulatory news, or any situation where you need to exit immediately.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${FREQTRADE_PYTHON:-$PROJECT_DIR/../freqtrade/.venv/bin/python}"

echo "============================================"
echo "  EMERGENCY STOP"
echo "  $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "============================================"

# 1. Kill ALL freqtrade processes immediately
echo "[1/4] Killing all freqtrade processes..."
pkill -f "freqtrade trade" 2>/dev/null && echo "  Bot processes killed" || echo "  No bot running"

# 2. Stop all timers (prevent auto-restart)
echo "[2/4] Disabling automation timers..."
systemctl --user stop crypto-pipeline.timer 2>/dev/null || true
systemctl --user stop crypto-alerts.timer 2>/dev/null || true
systemctl --user stop crypto-daily-report.timer 2>/dev/null || true
echo "  Timers stopped"

# 3. Close all open positions via Freqtrade API (if bot was running)
if [[ "${1:-}" != "--keep" ]]; then
    echo "[3/4] Attempting to close open positions..."
    echo "  NOTE: Bot is already killed. Positions remain open on exchange."
    echo "  To close manually:"
    echo "    - Go to Binance → Spot → Open Orders → Cancel All"
    echo "    - Market sell any positions you want to exit"
    echo ""
    echo "  Or restart bot briefly to close:"
    echo "    python -m freqtrade trade ... &"
    echo "    # In Telegram: /forceexit all"
    echo "    # Then kill again"
else
    echo "[3/4] Keeping positions open (--keep flag)"
fi

# 4. Send Telegram alert
echo "[4/4] Sending Telegram alert..."
SECRETS=$(sops decrypt "$PROJECT_DIR/secrets.yaml" 2>/dev/null || echo "")
if [[ -n "$SECRETS" ]]; then
    TOKEN=$($PYTHON -c "import sys,yaml; d=yaml.safe_load(sys.stdin); print(d['telegram']['bot_token'])" <<< "$SECRETS" 2>/dev/null || echo "")
    CHAT=$($PYTHON -c "import sys,yaml; d=yaml.safe_load(sys.stdin); print(d['telegram']['chat_id'])" <<< "$SECRETS" 2>/dev/null || echo "")
    if [[ -n "$TOKEN" && -n "$CHAT" ]]; then
        curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
            -d chat_id="$CHAT" \
            -d parse_mode="Markdown" \
            -d text="*EMERGENCY STOP* 🚨

Bot killed, timers disabled.
Time: $(date -u '+%Y-%m-%d %H:%M:%S UTC')

Action required:
- Check exchange for open positions
- Investigate the issue
- Re-enable with: \`systemctl --user start crypto-pipeline.timer crypto-alerts.timer\`
- Restart bot: \`./start_live.sh\`" > /dev/null 2>&1
        echo "  Telegram alert sent"
    fi
fi

echo ""
echo "============================================"
echo "  ALL STOPPED"
echo "============================================"
echo ""
echo "To resume normal operation:"
echo "  1. Fix the issue"
echo "  2. systemctl --user start crypto-pipeline.timer crypto-alerts.timer crypto-daily-report.timer"
echo "  3. ./start_live.sh  (or dry-run config)"
