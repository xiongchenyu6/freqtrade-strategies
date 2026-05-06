#!/usr/bin/env bash
# Bulk-download historical klines from https://data.binance.vision (public dumps).
#
# Faster and more reliable than ccxt REST for long timeranges (no rate limits,
# official CHECKSUM verification).
#
# Usage:
#   scripts/download_bulk_binance.sh SYMBOL TIMEFRAME [FROM_YYYY-MM] [TO_YYYY-MM]
#
# Examples:
#   scripts/download_bulk_binance.sh BTCUSDT 1m 2017-08
#   scripts/download_bulk_binance.sh ETHUSDT 1h 2020-01 2024-12
#
# Output:
#   data_bulk/<SYMBOL>/<TIMEFRAME>/*.csv      (raw extracted CSVs)
#   user_data/data/binance/<BASE>_<QUOTE>-<TF>.feather   (freqtrade-ready)

set -euo pipefail

SYMBOL="${1:?Usage: $0 SYMBOL TIMEFRAME [FROM_YYYY-MM] [TO_YYYY-MM]}"
TIMEFRAME="${2:?Usage: $0 SYMBOL TIMEFRAME [FROM_YYYY-MM] [TO_YYYY-MM]}"
FROM="${3:-2017-08}"
TO="${4:-$(date -u +%Y-%m)}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
STAGE_DIR="$PROJECT_DIR/data_bulk/$SYMBOL/$TIMEFRAME"
BASE_URL="https://data.binance.vision/data/spot/monthly/klines/$SYMBOL/$TIMEFRAME"

mkdir -p "$STAGE_DIR"

# Iterate months FROM..TO
y_from=${FROM%-*}; m_from=$((10#${FROM#*-}))
y_to=${TO%-*};   m_to=$((10#${TO#*-}))

y=$y_from; m=$m_from
downloaded=0
skipped=0
missing=0

while : ; do
    ym=$(printf "%d-%02d" "$y" "$m")
    fname="${SYMBOL}-${TIMEFRAME}-${ym}"
    zipfile="$STAGE_DIR/${fname}.zip"
    cksfile="$STAGE_DIR/${fname}.zip.CHECKSUM"
    csvfile="$STAGE_DIR/${fname}.csv"

    if [[ -f "$csvfile" ]]; then
        skipped=$((skipped + 1))
    else
        if curl -fsSL --max-time 120 -o "$zipfile" "$BASE_URL/${fname}.zip" 2>/dev/null; then
            curl -fsSL --max-time 30 -o "$cksfile" "$BASE_URL/${fname}.zip.CHECKSUM" 2>/dev/null || true
            if [[ -s "$cksfile" ]]; then
                if ! (cd "$STAGE_DIR" && sha256sum -c "${fname}.zip.CHECKSUM" >/dev/null 2>&1); then
                    echo "[$ym] CHECKSUM MISMATCH — aborting" >&2
                    exit 3
                fi
            fi
            unzip -qo "$zipfile" -d "$STAGE_DIR"
            rm -f "$zipfile" "$cksfile"
            downloaded=$((downloaded + 1))
            echo "[$ym] ok"
        else
            # Monthly not archived yet (current month) — fall back to daily dumps
            rm -f "$zipfile"
            daily_base="https://data.binance.vision/data/spot/daily/klines/$SYMBOL/$TIMEFRAME"
            daily_ok=0; daily_miss=0
            for dd in $(seq -f "%02g" 1 31); do
                dname="${SYMBOL}-${TIMEFRAME}-${ym}-${dd}"
                dzip="$STAGE_DIR/${dname}.zip"
                dcks="$STAGE_DIR/${dname}.zip.CHECKSUM"
                dcsv="$STAGE_DIR/${dname}.csv"
                [[ -f "$dcsv" ]] && continue
                if curl -fsSL --max-time 60 -o "$dzip" "$daily_base/${dname}.zip" 2>/dev/null; then
                    curl -fsSL --max-time 15 -o "$dcks" "$daily_base/${dname}.zip.CHECKSUM" 2>/dev/null || true
                    if [[ -s "$dcks" ]]; then
                        if ! (cd "$STAGE_DIR" && sha256sum -c "${dname}.zip.CHECKSUM" >/dev/null 2>&1); then
                            echo "[$ym-$dd] CHECKSUM MISMATCH" >&2
                            exit 3
                        fi
                    fi
                    unzip -qo "$dzip" -d "$STAGE_DIR"
                    rm -f "$dzip" "$dcks"
                    daily_ok=$((daily_ok + 1))
                else
                    rm -f "$dzip"
                    daily_miss=$((daily_miss + 1))
                fi
            done
            if [[ $daily_ok -gt 0 ]]; then
                echo "[$ym] monthly missing, fell back to daily: $daily_ok days"
                downloaded=$((downloaded + 1))
            else
                missing=$((missing + 1))
                echo "[$ym] not available (no monthly or daily)"
            fi
        fi
    fi

    # Advance month
    if [[ $y -eq $y_to && $m -eq $m_to ]]; then break; fi
    m=$((m + 1))
    if [[ $m -gt 12 ]]; then m=1; y=$((y + 1)); fi
done

echo ""
echo "Downloaded: $downloaded   Already had: $skipped   Missing: $missing"
echo ""
echo "Converting to freqtrade feather..."
python "$SCRIPT_DIR/binance_vision_to_feather.py" "$SYMBOL" "$TIMEFRAME"
