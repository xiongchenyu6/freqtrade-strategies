#!/usr/bin/env python3
"""
Monthly Walk-Forward Re-validation

Re-runs backtest on the most recent data to detect edge decay.
Runs 4 rolling windows of ~6 months each. If fewer than 2 recent windows
are profitable, the edge is likely gone → send alert.

Triggered monthly via systemd timer. Does NOT modify risk state directly
(that's monitor's job). Just reports.
"""

import json
import logging
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "strategies"))

from telegram_alerts import send_telegram  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger("walk_forward_check")

STRATEGY = "HonestTrend1mLive"
CONFIG = PROJECT_DIR / "configs" / "backtest" / "config_backtest_1m.json"
DATADIR = PROJECT_DIR / "user_data" / "data"
STRATPATH = PROJECT_DIR / "strategies"
RESULTS_DIR = PROJECT_DIR / "walk_forward_history"
RESULTS_DIR.mkdir(exist_ok=True)


def rolling_windows(today: datetime, window_days: int = 180, n: int = 4) -> list[tuple[str, str, str]]:
    """Returns [(label, start_str, end_str), ...] for N trailing windows."""
    windows = []
    end = today
    for i in range(n):
        start = end - timedelta(days=window_days)
        label = f"W{n-i}"
        windows.append(
            (label, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
        )
        end = start
    return list(reversed(windows))  # chronological


def run_backtest(start: str, end: str) -> dict | None:
    cmd = [
        "python", "-m", "freqtrade", "backtesting",
        "--strategy", STRATEGY,
        "--config", str(CONFIG),
        "--datadir", str(DATADIR),
        "--strategy-path", str(STRATPATH),
        "--timerange", f"{start}-{end}",
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        logger.error("Backtest timeout")
        return None

    for line in out.stdout.splitlines():
        if STRATEGY in line and "│" in line:
            # Parse the summary row: │ Strategy │ Trades │ AvgP% │ TotP USDT │ TotP% │ ...
            parts = [p.strip() for p in line.split("│") if p.strip()]
            if len(parts) >= 5:
                try:
                    return {
                        "trades": int(parts[1]),
                        "avg_profit_pct": float(parts[2]),
                        "tot_profit_usdt": float(parts[3]),
                        "tot_profit_pct": float(parts[4]),
                    }
                except (ValueError, IndexError):
                    continue
    return None


def main() -> int:
    today = datetime.now(timezone.utc)
    windows = rolling_windows(today, window_days=180, n=4)
    results = []

    for label, start, end in windows:
        logger.info(f"Running {label}: {start} to {end}")
        r = run_backtest(start, end)
        if r is None:
            logger.warning(f"{label} failed, skipping")
            results.append({"label": label, "start": start, "end": end,
                           "trades": 0, "tot_profit_pct": 0.0, "status": "failed"})
            continue
        r["label"] = label
        r["start"] = start
        r["end"] = end
        r["status"] = "ok"
        results.append(r)
        logger.info(f"  {label}: {r['trades']} trades, {r['tot_profit_pct']:+.2f}%")

    ok = [r for r in results if r["status"] == "ok"]
    positive = sum(1 for r in ok if r["tot_profit_pct"] > 0)
    n_windows = len(ok)

    # Save history
    history_file = RESULTS_DIR / f"walkforward_{today.strftime('%Y%m%d')}.json"
    with open(history_file, "w") as f:
        json.dump({"run_date": today.isoformat(), "results": results}, f, indent=2)

    # Build report
    lines = [f"📊 *Walk-Forward Check* ({today.strftime('%Y-%m-%d')})"]
    lines.append(f"Strategy: {STRATEGY}")
    lines.append("")
    for r in results:
        sym = "✓" if r.get("tot_profit_pct", 0) > 0 else "✗"
        lines.append(
            f"{sym} {r['label']} ({r['start']}→{r['end']}): "
            f"{r.get('trades',0)}t, {r.get('tot_profit_pct',0):+.2f}%"
        )
    lines.append("")
    lines.append(f"Profitable windows: {positive}/{n_windows}")

    alert_level = "info"
    if n_windows > 0 and positive / n_windows < 0.5:
        lines.append("⚠️ EDGE DEGRADING: <50% windows profitable")
        alert_level = "warn"
    if n_windows > 0 and positive == 0:
        lines.append("🚨 EDGE DEAD: 0 windows profitable. Consider retiring.")
        alert_level = "critical"

    msg = "\n".join(lines)
    print(msg)

    if alert_level != "info":
        try:
            send_telegram(msg)
        except Exception as e:
            logger.error(f"Telegram alert failed: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
