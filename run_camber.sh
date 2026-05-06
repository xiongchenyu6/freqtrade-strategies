#!/usr/bin/env bash
# Run crypto sentiment pipeline on CamberCloud
#
# Usage:
#   ./run_camber.sh           # submit job and show status
#   ./run_camber.sh --logs    # show logs of latest job
#   ./run_camber.sh --watch   # submit and wait for results

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CAMBER_USER="${CAMBER_USER:?Set CAMBER_USER env var (your CamberCloud username)}"
STASH_PATH="stash://${CAMBER_USER}/crypto-pipeline"
PIPELINE_LOCAL="$PROJECT_DIR/notebooks/deepnote_pipeline.py"

# Always upload latest code
echo "[1/3] Uploading latest pipeline code..."
camber stash cp "$PIPELINE_LOCAL" "$STASH_PATH/pipeline.py" 2>&1 | tail -1

# Submit job
echo "[2/3] Submitting job to CamberCloud..."
OUTPUT=$(camber job create \
  --engine base \
  --size xxsmall \
  --path "$STASH_PATH/" \
  --cmd "pip install requests numpy -q && python pipeline.py" 2>&1)

JOB_ID=$(echo "$OUTPUT" | grep "Job ID:" | awk '{print $3}')
echo "  Job ID: $JOB_ID"
echo "  Status: Submitted"

if [[ "${1:-}" == "--watch" ]]; then
    echo "[3/3] Waiting for completion..."
    while true; do
        STATUS=$(camber job get "$JOB_ID" 2>&1 | grep "Status:" | awk '{print $2}')
        echo "  Status: $STATUS ($(date '+%H:%M:%S'))"
        if [[ "$STATUS" == "COMPLETED" ]] || [[ "$STATUS" == "FAILED" ]]; then
            break
        fi
        sleep 15
    done
    echo ""
    echo "=== Job Logs ==="
    camber job logs "$JOB_ID" 2>&1
elif [[ "${1:-}" == "--logs" ]]; then
    # Show logs of most recent job
    LATEST=$(camber job list 2>&1 | grep -o '[0-9]*' | head -1)
    echo "Showing logs for job $LATEST:"
    camber job logs "$LATEST" 2>&1
else
    echo ""
    echo "Check status:  camber job get $JOB_ID"
    echo "View logs:     camber job logs $JOB_ID"
    echo "Or run:        ./run_camber.sh --watch"
fi
