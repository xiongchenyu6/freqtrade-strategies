"""Writes Nautilus position open/close events to quant.nautilus_trades (TimescaleDB), which
the dashboard reads via api.nautilus_trades. Plain helper (not an Actor) — strategies call it
from on_position_opened / on_position_changed / on_position_closed, because position events
route to the owning strategy.

Connection: TIMESCALE_URL env (sops-provided). All DB errors are swallowed + logged — a DB
hiccup must NEVER break trading. Disabled (no-op) if TIMESCALE_URL is unset (e.g. backtest).
"""

from __future__ import annotations

import os

from nautilus_trader.model.enums import PositionSide


class TradeLedger:
    def __init__(self, environment: str | None = None, logger=None):
        self._url = os.environ.get("TIMESCALE_URL")
        self._env = environment or os.environ.get("NAUTILUS_ENV", "testnet")
        self._log = logger
        self._conn = None

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    def _cursor(self):
        import psycopg2  # imported lazily so backtests don't need it

        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self._url)
            self._conn.autocommit = True
        return self._conn.cursor()

    def _warn(self, msg):
        if self._log:
            self._log.warning(msg)

    def record_open(self, e) -> None:
        if not self.enabled:
            return
        try:
            iid = str(e.instrument_id)
            with self._cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO quant.nautilus_trades
                      (trader_id, position_id, strategy, instrument, venue, environment,
                       is_short, open_date, open_rate, quantity)
                    VALUES (%s,%s,%s,%s,%s,%s,%s, to_timestamp(%s/1e9), %s, %s)
                    ON CONFLICT (trader_id, position_id, open_date) DO UPDATE
                      SET quantity = EXCLUDED.quantity, open_rate = EXCLUDED.open_rate,
                          synced_at = now()
                    """,
                    (str(e.trader_id), str(e.position_id), str(e.strategy_id), iid,
                     iid.split(".")[-1], self._env, e.side == PositionSide.SHORT,
                     int(e.ts_opened), float(e.avg_px_open), float(e.quantity)),
                )
        except Exception as ex:  # never break trading on a DB error
            self._warn(f"TradeLedger.record_open failed: {ex!r}")

    def record_close(self, e) -> None:
        if not self.enabled:
            return
        try:
            with self._cursor() as cur:
                cur.execute(
                    """
                    UPDATE quant.nautilus_trades
                       SET close_date = to_timestamp(%s/1e9), close_rate = %s,
                           realized_pnl = %s, profit_pct = %s, exit_reason = %s, synced_at = now()
                     WHERE trader_id = %s AND position_id = %s
                    """,
                    (int(e.ts_closed), float(e.avg_px_close), float(e.realized_pnl),
                     float(e.realized_return), "signal", str(e.trader_id), str(e.position_id)),
                )
        except Exception as ex:
            self._warn(f"TradeLedger.record_close failed: {ex!r}")
