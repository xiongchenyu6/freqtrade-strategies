#!/usr/bin/env bash
# Start live trading bot with secrets from SOPS
#
# Usage:
#   ./start_live.sh              # start live bot
#   ./start_live.sh --dry-run    # start in dry-run mode (same config, simulated)
#   ./start_live.sh --stop       # stop the bot gracefully
#
# PREREQUISITES:
#   1. Binance API key/secret in secrets.yaml (sops encrypted)
#   2. At least 2 months of dry-run data showing strategy works
#   3. Review the pre-flight checklist in docs/IMPLEMENTATION_PLAN.md

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Override via FREQTRADE_PYTHON env var if your venv lives elsewhere
PYTHON="${FREQTRADE_PYTHON:-$PROJECT_DIR/../freqtrade/.venv/bin/python}"
CONFIG="$PROJECT_DIR/configs/config_live.json"
DB="sqlite:///$PROJECT_DIR/tradesv3_live.sqlite"
LOG="$PROJECT_DIR/logs/live_bot.log"

# --- Stop mode ---
if [[ "${1:-}" == "--stop" ]]; then
    echo "Stopping live bot..."
    PID=$(pgrep -f "freqtrade trade.*config_live" || true)
    if [[ -n "$PID" ]]; then
        kill "$PID"
        echo "Bot stopped (PID $PID)"
    else
        echo "Bot not running"
    fi
    exit 0
fi

# --- Safety check ---
if pgrep -f "freqtrade trade.*config_live" > /dev/null 2>&1; then
    echo "ERROR: Live bot is already running!"
    echo "Use ./start_live.sh --stop first"
    exit 1
fi

# --- Load secrets from SOPS ---
echo "Loading secrets from SOPS..."
SECRETS=$(sops decrypt "$PROJECT_DIR/secrets.yaml" 2>/dev/null)
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to decrypt secrets.yaml"
    exit 1
fi

export SUPABASE_URL=$(echo "$SECRETS" | $PYTHON -c "import sys,yaml; d=yaml.safe_load(sys.stdin); print(d['supabase']['url'])")
export SUPABASE_KEY=$(echo "$SECRETS" | $PYTHON -c "import sys,yaml; d=yaml.safe_load(sys.stdin); print(d['supabase']['publishable_key'])")
TELEGRAM_TOKEN=$(echo "$SECRETS" | $PYTHON -c "import sys,yaml; d=yaml.safe_load(sys.stdin); print(d['telegram']['bot_token'])")
TELEGRAM_CHAT=$(echo "$SECRETS" | $PYTHON -c "import sys,yaml; d=yaml.safe_load(sys.stdin); print(d['telegram']['chat_id'])")

# Binance API keys (must be added to secrets.yaml first)
BINANCE_KEY=$(echo "$SECRETS" | $PYTHON -c "import sys,yaml; d=yaml.safe_load(sys.stdin); print(d.get('binance', {}).get('api_key', ''))" 2>/dev/null)
BINANCE_SECRET=$(echo "$SECRETS" | $PYTHON -c "import sys,yaml; d=yaml.safe_load(sys.stdin); print(d.get('binance', {}).get('api_secret', ''))" 2>/dev/null)

if [[ -z "$BINANCE_KEY" || -z "$BINANCE_SECRET" ]]; then
    echo "ERROR: Binance API keys not found in secrets.yaml"
    echo ""
    echo "Add to secrets.yaml (via sops edit):"
    echo "  binance:"
    echo "    api_key: your_binance_api_key"
    echo "    api_secret: your_binance_api_secret"
    echo ""
    echo "Binance API key requirements:"
    echo "  - Enable: Spot Trading"
    echo "  - Disable: Withdrawals, Futures, Margin"
    echo "  - Restrict to your IP address"
    exit 1
fi

# --- Inject secrets into config via temp file ---
TEMP_CONFIG=$(mktemp)
$PYTHON -c "
import json, sys
with open('$CONFIG') as f:
    cfg = json.load(f)

cfg['exchange']['key'] = '$BINANCE_KEY'
cfg['exchange']['secret'] = '$BINANCE_SECRET'
cfg['telegram']['token'] = '$TELEGRAM_TOKEN'
cfg['telegram']['chat_id'] = '$TELEGRAM_CHAT'
cfg['api_server']['jwt_secret_key'] = 'live_$(date +%s)'
cfg['api_server']['username'] = 'freqtrader'
cfg['api_server']['password'] = 'live_$(date +%s | md5sum | head -c8)'

# Override to dry-run if requested
if '--dry-run' in sys.argv:
    cfg['dry_run'] = True
    cfg['dry_run_wallet'] = 10000
    cfg['bot_name'] = 'SentimentTrend-DRYTEST'

json.dump(cfg, open('$TEMP_CONFIG', 'w'), indent=2)
" "$@"

# --- Safety confirmation for live mode ---
DRY_RUN=$($PYTHON -c "import json; print(json.load(open('$TEMP_CONFIG'))['dry_run'])")
if [[ "$DRY_RUN" == "False" ]]; then
    echo ""
    echo "======================================"
    echo "  WARNING: LIVE TRADING MODE"
    echo "  Real money will be used!"
    echo "======================================"
    echo ""
    echo "Strategy: SentimentTrend V2"
    echo "Exchange: Binance Spot"
    echo "Max positions: 5"
    echo ""
    read -p "Type 'CONFIRM' to start live trading: " confirm
    if [[ "$confirm" != "CONFIRM" ]]; then
        echo "Aborted."
        rm -f "$TEMP_CONFIG"
        exit 1
    fi
fi

# --- Start bot ---
echo "Starting bot..."
nohup $PYTHON -m freqtrade trade \
    --user-data-dir "$PROJECT_DIR" \
    -c "$TEMP_CONFIG" \
    --db-url "$DB" \
    > "$LOG" 2>&1 &

BOT_PID=$!
echo "Bot started: PID=$BOT_PID"
echo "Log: tail -f $LOG"
echo ""

# Clean up temp config after bot reads it (wait a bit)
sleep 5
rm -f "$TEMP_CONFIG"

echo "Temp config cleaned. Secrets only in memory."
echo "Stop: ./start_live.sh --stop"
