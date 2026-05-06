#!/usr/bin/env bash
# Startup helper for HonestTrend stack.
#
# Usage:
#   ./scripts/start_honest_trend.sh dryrun    # 15m dry-run (HonestTrend15mDry, port 8082, has Telegram)
#   ./scripts/start_honest_trend.sh mtf       # 1m MTF dry-run (HonestTrend1mMTF, port 8083, no Telegram)
#   ./scripts/start_honest_trend.sh futures   # 15m futures L+S dry-run (HonestTrendFutures, port 8084, has Telegram)
#   ./scripts/start_honest_trend.sh live      # 1m live (REAL MONEY — requires Binance keys in SOPS)
#   ./scripts/start_honest_trend.sh both      # dryrun + mtf in parallel
#   ./scripts/start_honest_trend.sh all       # dryrun + mtf + futures in parallel
#
# Prerequisites:
#   - risk_monitor timer already enabled (systemctl --user enable --now crypto-risk-monitor.timer)
#   - For `live`: Binance API keys must exist under binance.api_key / binance.api_secret in secrets.yaml
#
# This script does NOT run bots under systemd — they run as long-lived processes
# you manage manually (or wrap them in another systemd unit later).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STRAT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
FREQTRADE_DIR="${FREQTRADE_DIR:-$STRAT_DIR/../freqtrade}"
SECRETS="$STRAT_DIR/secrets.env"
LOG_DIR="$STRAT_DIR/logs"
mkdir -p "$LOG_DIR"

MODE="${1:-}"

if [[ -z "$MODE" ]]; then
    echo "usage: $0 [dryrun|live|both]"
    exit 1
fi

start_dryrun() {
    local log="$LOG_DIR/honest15m_dryrun_$(date +%Y%m%d_%H%M%S).log"
    echo ">> Starting HonestTrend15mDry (DRY-RUN, port 8082)..."
    echo ">> Log: $log"
    cd "$FREQTRADE_DIR"
    # Detach properly: setsid + nohup + disown, redirect outside SOPS command
    sops exec-env "$SECRETS" \
      'FREQTRADE__TELEGRAM__TOKEN=$TELEGRAM_BOT_TOKEN \
       FREQTRADE__TELEGRAM__CHAT_ID=$TELEGRAM_CHAT_ID \
       setsid nohup python -m freqtrade trade \
         --config '"'$STRAT_DIR/configs/config_dryrun_honest15m.json'"' \
         --userdir '"'$STRAT_DIR/user_data'"' \
         --strategy-path '"'$STRAT_DIR/strategies'"' \
         --db-url '"'sqlite:///$STRAT_DIR/user_data/tradesv3_honest15m_dryrun.sqlite'"'' \
      > "$log" 2>&1 &
    disown
    sleep 2
    echo ">> Running. Tail log with: tail -f $log"
}

start_mtf() {
    local log="$LOG_DIR/honest1mmtf_dryrun_$(date +%Y%m%d_%H%M%S).log"
    echo ">> Starting HonestTrend1mMTF (DRY-RUN, port 8083, no Telegram)..."
    echo ">> Log: $log"
    cd "$FREQTRADE_DIR"
    # No Telegram override — config has enabled=false to avoid polling conflict
    sops exec-env "$SECRETS" \
      'setsid nohup python -m freqtrade trade \
         --config '"'$STRAT_DIR/configs/config_dryrun_honest1mmtf.json'"' \
         --userdir '"'$STRAT_DIR/user_data'"' \
         --strategy-path '"'$STRAT_DIR/strategies'"' \
         --db-url '"'sqlite:///$STRAT_DIR/user_data/tradesv3_honest1mmtf_dryrun.sqlite'"'' \
      > "$log" 2>&1 &
    disown
    sleep 2
    echo ">> Running. Tail log with: tail -f $log"
}

start_futures() {
    local log="$LOG_DIR/honestfutures15m_dryrun_$(date +%Y%m%d_%H%M%S).log"
    echo ">> Starting HonestTrendFutures (DRY-RUN, port 8084, futures L+S)..."
    echo ">> Log: $log"
    cd "$FREQTRADE_DIR"
    sops exec-env "$SECRETS" \
      'FREQTRADE__TELEGRAM__TOKEN=$TELEGRAM_BOT_TOKEN \
       FREQTRADE__TELEGRAM__CHAT_ID=$TELEGRAM_CHAT_ID \
       setsid nohup python -m freqtrade trade \
         --config '"'$STRAT_DIR/configs/config_dryrun_honestfutures15m.json'"' \
         --userdir '"'$STRAT_DIR/user_data'"' \
         --strategy-path '"'$STRAT_DIR/strategies'"' \
         --db-url '"'sqlite:///$STRAT_DIR/user_data/tradesv3_honestfutures15m_dryrun.sqlite'"'' \
      > "$log" 2>&1 &
    disown
    sleep 2
    echo ">> Running. Tail log with: tail -f $log"
}

start_live() {
    local log="$LOG_DIR/honest1m_live_$(date +%Y%m%d_%H%M%S).log"
    echo ">> Starting HonestTrend1mLive (LIVE, port 8081) — REAL MONEY"
    echo ">> Log: $log"

    # Safety check: require binance keys in SOPS env
    if ! sops -d "$SECRETS" 2>/dev/null | grep -q "^BINANCE_API_KEY="; then
        echo "!! ERROR: no BINANCE_API_KEY in SOPS secrets.env"
        echo "!! Add before running live:"
        echo "     BINANCE_API_KEY=<your binance key>"
        echo "     BINANCE_API_SECRET=<your binance secret>"
        echo "   Then: sops $SECRETS"
        exit 2
    fi

    # Also require risk state is ACTIVE
    local status
    status=$(python "$STRAT_DIR/scripts/risk_monitor.py" status | awk '/^Status:/ {print $2}')
    if [[ "$status" != "ACTIVE" ]]; then
        echo "!! ERROR: risk state is $status, not ACTIVE"
        echo "   Run: python scripts/risk_monitor.py reset --note 'pre-live start'"
        exit 3
    fi

    cd "$FREQTRADE_DIR"
    sops exec-env "$SECRETS" \
      'FREQTRADE__EXCHANGE__KEY=$BINANCE_API_KEY \
       FREQTRADE__EXCHANGE__SECRET=$BINANCE_API_SECRET \
       FREQTRADE__TELEGRAM__TOKEN=$TELEGRAM_BOT_TOKEN \
       FREQTRADE__TELEGRAM__CHAT_ID=$TELEGRAM_CHAT_ID \
       setsid nohup python -m freqtrade trade \
         --config '"'$STRAT_DIR/configs/config_live_honest1m.json'"' \
         --userdir '"'$STRAT_DIR/user_data'"' \
         --strategy-path '"'$STRAT_DIR/strategies'"' \
         --db-url '"'sqlite:///$STRAT_DIR/user_data/tradesv3_honest1m.sqlite'"'' \
      > "$log" 2>&1 &
    disown
    sleep 2
    echo ">> Running. Tail log with: tail -f $log"
}

case "$MODE" in
    dryrun)  start_dryrun ;;
    mtf)     start_mtf ;;
    futures) start_futures ;;
    live)    start_live ;;
    both)    start_dryrun; start_mtf ;;
    all)     start_dryrun; start_mtf; start_futures ;;
    *)       echo "unknown mode: $MODE"; exit 1 ;;
esac
