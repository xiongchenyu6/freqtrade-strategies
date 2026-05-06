#!/usr/bin/env python3
"""
Risk Monitor — daily driver for the risk manager

Runs via systemd user timer (e.g. every 4 hours or daily).

What it does:
  1. Reads live/dry-run trades from Freqtrade SQLite DB
  2. Computes equity curve, current drawdown, rolling PF
  3. Updates risk_state.json via RiskManager
  4. On state transitions, sends Telegram alert
  5. CLI: pause/retire/reset/status

Usage:
  python scripts/risk_monitor.py              # normal daily run (update state)
  python scripts/risk_monitor.py status       # print current state
  python scripts/risk_monitor.py pause        # manually pause
  python scripts/risk_monitor.py retire       # manually retire
  python scripts/risk_monitor.py reset        # manually reset to ACTIVE
"""

import argparse
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "strategies"))

from risk_manager import RiskManager  # noqa: E402
from telegram_alerts import send_telegram  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger("risk_monitor")

STATE_FILE = PROJECT_DIR / "risk_state.json"

# Freqtrade live DB locations. Probed in order; first existing wins.
DB_CANDIDATES = [
    PROJECT_DIR / "user_data" / "tradesv3_honest1m.sqlite",
    PROJECT_DIR / "user_data" / "tradesv3.sqlite",
    PROJECT_DIR / "user_data" / "tradesv3_honest15m_dryrun.sqlite",
    PROJECT_DIR / "user_data" / "tradesv3.dryrun.sqlite",
    Path.home() / "freqtrade_data" / "tradesv3.sqlite",
]

# Rolling window for PF computation: last N closed trades
PF_ROLLING_WINDOW = 50


def locate_db() -> Path | None:
    for p in DB_CANDIDATES:
        if p.exists():
            return p
    return None


def fetch_trades(db_path: Path) -> list[dict]:
    """Returns list of closed trades, oldest first."""
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        cur = con.execute(
            """
            SELECT open_date, close_date, close_profit, close_profit_abs, stake_amount
            FROM trades
            WHERE is_open = 0 AND close_date IS NOT NULL
            ORDER BY close_date ASC
            """
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        con.close()


def fetch_initial_balance(db_path: Path) -> float | None:
    """Pull starting balance from any open trade + wallet history if available."""
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.execute(
            "SELECT MIN(stake_amount) FROM trades WHERE stake_amount IS NOT NULL"
        )
        row = cur.fetchone()
        # Best proxy: assume initial equity = first stake * 10 (fallback)
        # Better: caller passes it via env/config.
        return None
    finally:
        con.close()


def compute_metrics(trades: list[dict], initial_equity: float) -> dict:
    """Compute equity curve, peak, DD, rolling PF."""
    equity = initial_equity
    peak = initial_equity
    max_dd = 0.0

    for t in trades:
        equity += float(t["close_profit_abs"] or 0.0)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    # Rolling PF over last N trades
    recent = trades[-PF_ROLLING_WINDOW:]
    wins = sum(float(t["close_profit_abs"] or 0.0)
               for t in recent if float(t["close_profit_abs"] or 0.0) > 0)
    losses = -sum(float(t["close_profit_abs"] or 0.0)
                  for t in recent if float(t["close_profit_abs"] or 0.0) < 0)
    pf = wins / losses if losses > 0 else 0.0

    first_close = trades[0]["close_date"] if trades else None
    if first_close:
        first_dt = datetime.fromisoformat(first_close.replace("Z", "+00:00"))
        live_days = (datetime.now(timezone.utc) - first_dt).days
    else:
        live_days = 0

    return {
        "equity": equity,
        "peak_equity": peak,
        "current_dd_pct": (peak - equity) / peak if peak > 0 else 0.0,
        "max_dd_pct": max_dd,
        "total_trades": len(trades),
        "rolling_pf": pf,
        "live_days": live_days,
    }


def run_monitor(initial_equity: float) -> int:
    db = locate_db()
    if not db:
        logger.info("No live DB yet — bot not started. Monitor idle.")
        # Still touch the state file so it exists
        RiskManager(STATE_FILE).save()
        return 0

    logger.info(f"Using DB: {db}")
    trades = fetch_trades(db)
    logger.info(f"Closed trades: {len(trades)}")

    metrics = compute_metrics(trades, initial_equity)
    logger.info(
        f"equity={metrics['equity']:.2f} "
        f"dd={metrics['current_dd_pct']*100:.2f}% "
        f"PF={metrics['rolling_pf']:.2f} "
        f"trades={metrics['total_trades']} days={metrics['live_days']}"
    )

    rm = RiskManager(STATE_FILE)
    msg_equity = rm.update_equity(metrics["equity"])
    msg_metrics = rm.update_metrics(
        metrics["total_trades"], metrics["rolling_pf"], metrics["live_days"]
    )
    rm.save()

    for msg in (msg_equity, msg_metrics):
        if msg:
            alert = f"🚨 *Risk State Change*\n\n{msg}\n\n" \
                    f"Equity: {metrics['equity']:.0f} USDT\n" \
                    f"DD: {metrics['current_dd_pct']*100:.2f}%\n" \
                    f"PF (last 50): {metrics['rolling_pf']:.2f}\n" \
                    f"Trades: {metrics['total_trades']} | Days: {metrics['live_days']}"
            logger.warning(msg)
            try:
                send_telegram(alert)
            except Exception as e:
                logger.error(f"Telegram alert failed: {e}")

    return 0


def cmd_status() -> int:
    rm = RiskManager(STATE_FILE)
    s = rm.state
    print(f"Status:       {s.status}")
    print(f"Reason:       {s.status_reason}")
    print(f"Since:        {s.status_since}")
    print(f"Start date:   {s.start_date}")
    print(f"Equity:       {s.current_equity:.2f} (peak {s.peak_equity:.2f})")
    print(f"Drawdown:     {s.current_dd_pct*100:.2f}%")
    print(f"Trades:       {s.total_trades} over {s.live_days} days")
    print(f"Rolling PF:   {s.rolling_pf:.2f}")
    return 0


def cmd_pause(note: str) -> int:
    rm = RiskManager(STATE_FILE)
    msg = rm.manual_pause(note)
    rm.save()
    print(msg)
    try:
        send_telegram(f"⏸ *Manual PAUSE*\n{msg}")
    except Exception:
        pass
    return 0


def cmd_retire(note: str) -> int:
    rm = RiskManager(STATE_FILE)
    msg = rm.manual_retire(note)
    rm.save()
    print(msg)
    try:
        send_telegram(f"🛑 *Manual RETIRE*\n{msg}")
    except Exception:
        pass
    return 0


def cmd_reset(note: str) -> int:
    rm = RiskManager(STATE_FILE)
    msg = rm.manual_reset(note)
    rm.save()
    print(msg)
    try:
        send_telegram(f"✅ *Manual RESET to ACTIVE*\n{msg}")
    except Exception:
        pass
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")

    run = sub.add_parser("run", help="update state from live DB (default)")
    run.add_argument("--initial-equity", type=float, default=10000.0,
                     help="starting capital for equity curve (default 10000)")

    sub.add_parser("status", help="print current state")

    for name, helptxt in [
        ("pause", "manually pause entries"),
        ("retire", "manually retire strategy"),
        ("reset", "reset to ACTIVE"),
    ]:
        p = sub.add_parser(name, help=helptxt)
        p.add_argument("--note", default="", help="reason note")

    args = ap.parse_args()

    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "pause":
        return cmd_pause(args.note)
    if args.cmd == "retire":
        return cmd_retire(args.note)
    if args.cmd == "reset":
        return cmd_reset(args.note)

    # Default: run monitor
    initial = getattr(args, "initial_equity", 10000.0)
    return run_monitor(initial)


if __name__ == "__main__":
    sys.exit(main())
