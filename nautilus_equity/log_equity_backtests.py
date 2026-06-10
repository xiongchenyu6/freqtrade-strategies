"""Run HonestTrendEquity on the REAL IB catalog and log honest results to the dashboard DB.

Populates `quant.nautilus_backtests` (asset_class='equity') so the web home page has a real
US-equity backtest leaderboard to show. Numbers are whatever the strategy actually does on the
real adjusted bars — we don't curate winners or inflate (the leg is a plain trend follower).

Idempotent: deletes prior equity backtest rows, then re-inserts, so re-running refreshes.

Run:  TIMESCALE_URL=postgres://quant:...@db.panda.qzz.io/api \
        nautilus_equity/.venv/bin/python nautilus_equity/log_equity_backtests.py
(or rely on ~/.config/quant/backtest-runner.env which already has TIMESCALE_URL).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2
from nautilus_trader.persistence.catalog import ParquetDataCatalog

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from grid_honest_equity_real import run_one  # noqa: E402

_CATALOG = _HERE / "catalog"
_PERIOD_START = "2023-06-12"
_PERIOD_END = "2026-06-08"

# Curated, honest set: the two configs we actually reason about — a daily 20/50 trend
# (most active) and the 1-HOUR 50/100 that the LIVE paper engine runs. One row per asset.
_CONFIGS = [
    ("1-DAY", "1-DAY-LAST-EXTERNAL", 252, "20/50", 20, 50),
    ("1-HOUR", "1-HOUR-LAST-EXTERNAL", 1638, "50/100", 50, 100),
]
_ASSETS = [("NVDA", "NASDAQ"), ("AMD", "NASDAQ"), ("QQQ", "NASDAQ")]


def _dsn() -> str:
    url = os.environ.get("TIMESCALE_URL")
    if not url:
        env = Path.home() / ".config" / "quant" / "backtest-runner.env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("TIMESCALE_URL="):
                    url = line.split("=", 1)[1].strip()
                    break
    if not url:
        raise SystemExit("TIMESCALE_URL not set (env or ~/.config/quant/backtest-runner.env)")
    return url


def main() -> int:
    if not _CATALOG.exists():
        print(f"catalog not found: {_CATALOG}", file=sys.stderr)
        return 2
    catalog = ParquetDataCatalog(str(_CATALOG))

    rows = []
    for tf_label, suffix, ppy, pair_label, ef, es in _CONFIGS:
        for symbol, venue in _ASSETS:
            r = run_one(catalog, symbol, venue, ef, es, suffix, ppy)
            tf = "1d" if tf_label == "1-DAY" else "1h"
            calmar = None if r["calmar"] == float("inf") else round(r["calmar"], 2)
            rows.append({
                "asset_class": "equity",
                "strategy": "HonestTrendEquity",
                "label": f"{symbol} {tf} EMA {pair_label}",
                "instruments": [f"{symbol}.{venue}"],
                "timeframe": tf,
                "period_start": _PERIOD_START,
                "period_end": _PERIOD_END,
                "environment": "backtest",
                # `exits` = closed round trips; entries that are still open aren't counted as trades.
                "total_trades": r["exits"],
                "total_profit_pct": round(r["ret_pct"], 2),
                "max_drawdown_pct": round(-r["mdd_pct"], 2),  # stored negative (matches crypto rows)
                "calmar": calmar,
                "sharpe": round(r["sharpe"], 2),
                "params": '{"ema_fast": %d, "ema_slow": %d, "adx_threshold": 18.0, "stop_loss_pct": 0.08}' % (ef, es),
            })
            print(f"  {rows[-1]['label']:<18} ret={r['ret_pct']:+7.2f}%  maxDD={r['mdd_pct']:5.2f}%  "
                  f"Sharpe={r['sharpe']:.2f}  Calmar={calmar}  trades={r['exits']}")

    conn = psycopg2.connect(_dsn())
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            # Refresh prior equity rows when we have DELETE (migration 016). If the grant
            # isn't applied yet, fall back to insert-only when the table has no equity rows
            # — keeps the seed idempotent without the privilege.
            try:
                cur.execute("SAVEPOINT del")
                cur.execute("DELETE FROM quant.nautilus_backtests WHERE asset_class='equity'")
                cur.execute("RELEASE SAVEPOINT del")
            except psycopg2.errors.InsufficientPrivilege:
                cur.execute("ROLLBACK TO SAVEPOINT del")
                cur.execute("SELECT count(*) FROM quant.nautilus_backtests WHERE asset_class='equity'")
                if cur.fetchone()[0] > 0:
                    print("equity rows already present and no DELETE grant — skipping (apply migration 016 to refresh)")
                    conn.rollback()
                    return 0
            for r in rows:
                cur.execute(
                    """INSERT INTO quant.nautilus_backtests
                       (asset_class, strategy, label, instruments, timeframe, period_start,
                        period_end, environment, total_trades, total_profit_pct, max_drawdown_pct,
                        calmar, sharpe, params)
                       VALUES (%(asset_class)s,%(strategy)s,%(label)s,%(instruments)s,%(timeframe)s,
                        %(period_start)s,%(period_end)s,%(environment)s,%(total_trades)s,
                        %(total_profit_pct)s,%(max_drawdown_pct)s,%(calmar)s,%(sharpe)s,%(params)s::jsonb)""",
                    r,
                )
        conn.commit()
        print(f"\ninserted {len(rows)} equity backtest rows into quant.nautilus_backtests")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
