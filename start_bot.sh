#!/usr/bin/env bash
# Start freqtrade bot with secrets from sops exec-env
#
# Usage:
#   ./start_bot.sh                    # start dry-run SentimentTrend
#   ./start_bot.sh --stop             # stop the bot
#   ./start_bot.sh --status           # show status

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${FREQTRADE_PYTHON:-$PROJECT_DIR/../freqtrade/.venv/bin/python}"
CONFIG="$PROJECT_DIR/configs/config_dryrun_honest15m.json"
DB="sqlite:///$(realpath "$PROJECT_DIR")/tradesv3_honest.sqlite"
LOG="$PROJECT_DIR/logs/honest_bot.log"
PIDFILE="$PROJECT_DIR/logs/bot.pid"
# NixOS: native libs not on default path — add gcc lib for rapidjson/TA-Lib
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:/nix/store/dcb4bsy8fcn51bw0qp3vwx8q0rzpghd5-gcc-15.2.0-lib/lib"
# NixOS: ensure sops is on PATH
export PATH="/nix/store/rnfkl6rwi7qdclqfx1vphagbq72rhhl2-sops-3.12.2/bin:$PATH"

case "${1:-start}" in
    --stop)
        if [ -f "$PIDFILE" ]; then
            PID=$(cat "$PIDFILE")
            kill "$PID" 2>/dev/null && echo "Bot stopped (PID $PID)" || echo "Bot not running"
            rm -f "$PIDFILE"
        else
            pkill -f "freqtrade trade" 2>/dev/null && echo "Bot stopped" || echo "Bot not running"
        fi
        exit 0
        ;;
    --status)
        if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
            echo "Bot running: PID $(cat "$PIDFILE")"
            curl -s http://127.0.0.1:8080/api/v1/ping 2>/dev/null || echo "API not responding"
        else
            echo "Bot not running"
        fi
        exit 0
        ;;
esac

# Check not already running
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "Bot already running (PID $(cat "$PIDFILE"))."
    exit 1
fi

# Export secrets — prefer pre-decrypted runtime file (for servers without GPG key),
# fall back to sops exec-env for local dev.
echo "Loading secrets and starting bot..."

RUNTIME_ENV="$PROJECT_DIR/.secrets_runtime.env"
if [ -f "$RUNTIME_ENV" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$RUNTIME_ENV"
    set +a
else
    sops exec-env "$PROJECT_DIR/secrets.env" \
        'env | grep -E "^(SUPABASE_|ZYTE_|TELEGRAM_|DEEPNOTE_)"' \
        > /tmp/crypto_bot_env 2>/dev/null
    set -a
    source /tmp/crypto_bot_env
    set +a
    rm -f /tmp/crypto_bot_env
fi

# Run from freqtrade source dir (editable install requires it)
FREQTRADE_DIR="${FREQTRADE_DIR:-$PROJECT_DIR/../freqtrade}"

cd "$FREQTRADE_DIR"
nohup "$PYTHON" -m freqtrade trade \
    --user-data-dir "$PROJECT_DIR" \
    -c "$CONFIG" \
    --db-url "$DB" \
    > "$LOG" 2>&1 &

BOT_PID=$!
echo "$BOT_PID" > "$PIDFILE"
echo "Bot started: PID=$BOT_PID"
echo "Log: tail -f $LOG"
echo "UI: http://localhost:8080"
echo "Stop: ./start_bot.sh --stop"
