"""Donchian channel breakout — the recent-regime-validated crypto trend strategy.

Research (STRATEGY_LEADERBOARD.md): on out-of-sample recent data, Donchian breakout keeps a
positive edge (ETH+BTC+SOL 1h, 168/72: +22.6% / Sharpe 2.20 / -10% maxDD) where the older
EMA-cross had decayed to a negative Sharpe. One strategy instance per instrument; the live
TradingNode runs several. Backtest=live: the same class runs in both.

Entry: close breaks above the highest high of the last `entry_lb` bars.
Exit:  close breaks below the lowest low of the last `exit_lb` bars.
Sizing: `risk_frac` of total account equity (quote currency), spot, no leverage, no pyramid.
"""

from __future__ import annotations

from collections import deque
from datetime import timedelta

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy


class DonchianBreakoutConfig(StrategyConfig, frozen=True):
    instrument_id: str
    bar_type: BarType
    entry_lb: int = 168   # ~7 days on 1h — breakout lookback
    exit_lb: int = 72     # ~3 days on 1h — exit (trailing low) lookback
    risk_frac: float = 0.0667  # ~3 instruments × 6.67% ≈ 20% total deployed


class DonchianBreakout(Strategy):
    def __init__(self, config: DonchianBreakoutConfig):
        super().__init__(config)
        self.iid = InstrumentId.from_str(config.instrument_id)
        self._hi: deque[float] = deque(maxlen=config.entry_lb)
        self._lo: deque[float] = deque(maxlen=config.exit_lb)
        self.entries = 0
        self.exits = 0

    def on_start(self):
        self.subscribe_bars(self.config.bar_type)
        # Warm the channel from history so live trading starts immediately instead of
        # idling ~entry_lb bars. Safe for Donchian because the channel is max/min over a
        # rolling window — order-insensitive, so historical/live interleaving can't corrupt
        # it (unlike a cumulative EMA). No-op in backtest (no historical data client).
        try:
            need = self.config.entry_lb + self.config.exit_lb + 10
            self.request_bars(
                self.config.bar_type,
                start=self.clock.utc_now() - timedelta(hours=need),
            )
        except Exception as e:  # never let warmup break startup
            self.log.warning(f"warmup request_bars skipped: {e!r}")

    def on_historical_data(self, data):
        # Feed warmup bars into the channel deques (do NOT trade on history).
        # Live delivers one bar per call (BinanceBar); backtest delivers a list — handle both,
        # and use duck-typing (hasattr) since adapter bar subtypes aren't isinstance(Bar).
        bars = data if isinstance(data, (list, tuple)) else [data]
        for d in bars:
            if hasattr(d, "high") and hasattr(d, "low"):
                self._hi.append(float(d.high))
                self._lo.append(float(d.low))

    def on_stop(self):
        self.close_all_positions(self.iid)

    def on_bar(self, bar: Bar):
        close = float(bar.close)
        hi_full = len(self._hi) == self.config.entry_lb
        lo_full = len(self._lo) == self.config.exit_lb
        breakout = hi_full and close > max(self._hi)
        breakdown = lo_full and close < min(self._lo)

        instrument = self.cache.instrument(self.iid)
        if not self.portfolio.is_net_long(self.iid):
            if breakout and instrument is not None:
                self._enter(close, instrument)
        elif breakdown:
            self.close_all_positions(self.iid)
            self.exits += 1

        # Append AFTER the decision so the current bar isn't in its own lookback window.
        self._hi.append(float(bar.high))
        self._lo.append(float(bar.low))

    def _enter(self, close: float, instrument):
        account = self.portfolio.account(instrument.venue)
        if account is None:
            return
        bal = account.balance_total(instrument.quote_currency)
        equity = float(bal) if bal is not None else 0.0
        if equity <= 0:
            return
        qty = (equity * self.config.risk_frac) / close
        q = instrument.make_qty(qty)
        if float(q) <= 0:
            return
        self.submit_order(self.order_factory.market(self.iid, OrderSide.BUY, q))
        self.entries += 1
