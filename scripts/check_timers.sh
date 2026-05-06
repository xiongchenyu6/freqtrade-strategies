#!/usr/bin/env bash
# Quick health check for all crypto-* systemd user services.
# Shows: last run, status, any recent failures.
#
# Usage: ./scripts/check_timers.sh

set -euo pipefail

SERVICES=(
    crypto-alerts
    crypto-daily-report
    crypto-pipeline
    crypto-reactor
    crypto-risk-monitor
    crypto-walkforward
)

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "TIMER SCHEDULE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
systemctl --user list-timers --all 2>/dev/null \
    | grep -E "crypto|NEXT|^$" \
    | head -20
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "SERVICE HEALTH (last 7 days)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
for svc in "${SERVICES[@]}"; do
    state=$(systemctl --user show -p ActiveState "$svc.service" 2>/dev/null | cut -d= -f2)
    result=$(systemctl --user show -p Result "$svc.service" 2>/dev/null | cut -d= -f2)
    last=$(systemctl --user show -p ExecMainExitTimestamp "$svc.service" 2>/dev/null | cut -d= -f2-)
    last=${last:-never}

    fails=$(journalctl --user -u "$svc.service" --since "7 days ago" --no-pager 2>/dev/null \
        | grep -cE "FAILURE|Failed with result|Failed to start" || true)

    # color by state
    if [[ "$state" == "active" ]]; then
        mark="▶ "
    elif [[ "$result" == "success" && "$fails" -eq 0 ]]; then
        mark="✓ "
    elif [[ "$fails" -gt 0 ]]; then
        mark="✗ "
    else
        mark="· "
    fi

    printf "%s %-24s state=%-10s result=%-8s fails=%-3d last=%s\n" \
        "$mark" "$svc" "$state" "$result" "$fails" "$last"
done
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "RECENT ERRORS (crypto-*, last 3 days)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
for svc in "${SERVICES[@]}"; do
    errs=$(journalctl --user -u "$svc.service" --since "3 days ago" --no-pager 2>/dev/null \
        | grep -iE "error|failed|No such file|traceback" \
        | grep -v "Health check" \
        | tail -3 || true)
    if [[ -n "$errs" ]]; then
        echo "[$svc]"
        echo "$errs" | sed 's/^/  /'
        echo ""
    fi
done
