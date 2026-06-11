#!/usr/bin/env bash
# Watchdog for quant-equity: the Nautilus IB adapter wedges permanently after the
# Gateway's daily auto-restart (23:59 ET) — "Client failed to initialize; connection
# timeout" loops forever (observed: 537 consecutive attempts). A service restart
# reconnects instantly. This probe restarts the node when the journal shows a recent
# failure streak. Runs every 10 min via quant-equity-watchdog.timer, so a midnight
# wedge self-heals hours before the US open (21:30 SGT).
set -euo pipefail
FAILS=$(journalctl --user -u quant-equity --since "-7 minutes" --no-pager 2>/dev/null \
  | grep -c "Client failed to initialize" || true)
if [ "${FAILS:-0}" -ge 3 ]; then
  echo "quant-equity wedged (${FAILS} init failures in 7m) — restarting"
  systemctl --user restart quant-equity
else
  echo "ok (${FAILS:-0} failures in window)"
fi
