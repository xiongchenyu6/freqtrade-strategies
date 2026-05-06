#!/usr/bin/env bash
# Full sentiment pipeline via sops exec-env
# Runs via systemd timer every 4 hours

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${FREQTRADE_PYTHON:-$PROJECT_DIR/../freqtrade/.venv/bin/python}"
LOG="$PROJECT_DIR/logs/pipeline.log"

exec >> "$LOG" 2>&1
echo ""
echo "=========================================="
echo "Pipeline run: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "=========================================="

# Run everything inside sops exec-env — all secrets auto-injected
sops exec-env "$PROJECT_DIR/secrets.env" '
ZYTE_KEY="$ZYTE_API_KEY"
PYTHON="'"$PYTHON"'"
PROJECT_DIR="'"$PROJECT_DIR"'"

# 1. Trigger Zyte Cloud spiders
echo "[1/4] Triggering Zyte Cloud spiders..."
for spider in crypto_news reddit_sentiment trending_coins; do
    result=$(curl -s -u "$ZYTE_KEY:" \
        -d "project=$ZYTE_PROJECT_ID&spider=$spider&priority=2&units=1" \
        "https://app.scrapinghub.com/api/schedule.json" || echo "failed")
    echo "  $spider: $result"
done

# 2. Trigger Deepnote notebook
echo "[2/4] Triggering Deepnote notebook..."
dn_status=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
    -H "Authorization: Bearer $DEEPNOTE_API_KEY" \
    "https://api.deepnote.com/v1/projects/$DEEPNOTE_PROJECT_ID/notebooks/$DEEPNOTE_NOTEBOOK_ID/execute" || echo "failed")
echo "  Deepnote: HTTP $dn_status"

# 3. Wait for Zyte spiders
echo "[3/4] Waiting 90s for Zyte spiders..."
sleep 90

# 4. Run local pipeline
echo "[4/4] Running local sentiment pipeline..."
cd "$PROJECT_DIR/strategies"
$PYTHON news_pipeline.py
'

echo "Pipeline complete."
