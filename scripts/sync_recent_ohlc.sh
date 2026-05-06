#!/usr/bin/env bash
# Pull recent klines from Binance and load them into TimescaleDB.
#
# Two-step pipeline:
#   1. `freqtrade download-data` fetches the last N days of 1m candles for the
#      pairs we display on the site, writing freqtrade-flavored feather files
#      under user_data/data/binance/.
#   2. `sync_feather_to_timescale.py` COPYs only the *new* rows (incremental
#      from max(ts) per pair/tf) into the `quant.ohlc` hypertable, then
#      refreshes the 15m / 1h / 1d continuous aggregates.
#
# Run on a 15-30 minute timer to keep ohlc_15m_recent / ohlc_1h_recent /
# public_ohlc_1d / etc. fresh enough for the chart UI without thrashing.
#
# Usage:
#   scripts/sync_recent_ohlc.sh              # fetch last 3 days, default pairs
#   DAYS=7 scripts/sync_recent_ohlc.sh
#   PAIRS="BTC/USDT ETH/USDT" scripts/sync_recent_ohlc.sh

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FREQTRADE_DIR="$PROJECT_DIR/../freqtrade"
PYTHON="${FREQTRADE_PYTHON:-$FREQTRADE_DIR/.venv/bin/python}"

# How many days of recent data to (re)download. download-data is idempotent —
# it only overwrites the same range — so a 3-day window covers brief gaps and
# still finishes in seconds.
DAYS="${DAYS:-3}"

# Pairs we want fresh in the chart UI. Keep small — every extra pair adds a
# round of HTTP requests to Binance.
PAIRS="${PAIRS:-BTC/USDT ETH/USDT BNB/USDT SOL/USDT}"

# Timeframe must be 1m — the continuous aggregates derive 15m/1h/1d from it.
TIMEFRAME="${TIMEFRAME:-1m}"

DATADIR="$PROJECT_DIR/user_data/data/binance"
mkdir -p "$DATADIR"

cd "$FREQTRADE_DIR"

echo "[ohlc-sync] $(date -Iseconds) — downloading last ${DAYS}d of ${TIMEFRAME} for: ${PAIRS}"

"$PYTHON" -m freqtrade download-data \
    --exchange binance \
    --pairs $PAIRS \
    --timeframes "$TIMEFRAME" \
    --days "$DAYS" \
    --datadir "$DATADIR" \
    --data-format-ohlcv feather \
    --logfile - \
    >/dev/null

echo "[ohlc-sync] $(date -Iseconds) — feather files updated, syncing to TimescaleDB"

cd "$PROJECT_DIR"

# sync_feather_to_timescale.py needs TIMESCALE_URL — pull from sops.
sops exec-env secrets.env \
    "$PYTHON scripts/sync_feather_to_timescale.py --pairs $PAIRS"

echo "[ohlc-sync] $(date -Iseconds) — done"
