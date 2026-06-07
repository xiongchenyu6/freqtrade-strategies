"""Fear-driven buy-the-dip accumulation strategy for NautilusTrader.

This is the crypto half of the migration: per the project philosophy, crypto is now
**pure accumulation, not speculation** — accumulate BTC over the long run, buy harder
when the crowd panics, and NEVER sell (no stoploss on spot; long-term BTC bull thesis).

Mirrors the existing Event/Smart DCA daemon's idea on the unified Nautilus engine:
  - base DCA: a fixed buy every `interval_bars` (e.g. weekly on daily bars)
  - fear boost: extra multiple when Fear & Greed <= fear_threshold (extreme fear)
  - dip boost:  extra multiple when price is >= dip_threshold below the recent high

mode='naive' disables both boosts → a plain fixed-interval DCA, for A/B comparison.
"""

from __future__ import annotations

from collections import deque

from nautilus_trader.config import StrategyConfig
from nautilus_trader.core.datetime import unix_nanos_to_dt
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

from crypto_data import FngSeries


class AccumulatorConfig(StrategyConfig, frozen=True):
    instrument_id: str
    bar_type: BarType
    base_buy_usd: float = 500.0
    interval_bars: int = 7  # weekly on daily bars
    mode: str = "smart"  # 'smart' | 'naive'
    # fear boost
    fear_threshold: int = 25  # FNG <= this ⇒ extreme fear
    fear_multiplier: float = 3.0  # buy this many extra base units on extreme fear
    deep_fear_threshold: int = 15
    deep_fear_multiplier: float = 5.0
    # dip boost (independent of fear)
    dip_lookback: int = 30  # bars for the recent high
    dip_threshold: float = 0.20  # 20% below recent high
    dip_multiplier: float = 2.0


class Accumulator(Strategy):
    def __init__(self, config: AccumulatorConfig):
        super().__init__(config)
        self.iid = InstrumentId.from_str(config.instrument_id)
        self.fng = FngSeries()
        self._highs: deque[float] = deque(maxlen=config.dip_lookback)
        self._bar_i = -1
        # accounting (from fills)
        self.invested_usd = 0.0
        self.coin_qty = 0.0
        self.buys = 0
        self.fear_buys = 0
        self.dip_buys = 0
        self.last_price = 0.0

    def on_start(self):
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar):
        self._bar_i += 1
        self.last_price = float(bar.close)
        self._highs.append(float(bar.high))

        # Scheduled buy only on interval boundaries.
        if self._bar_i % self.config.interval_bars != 0:
            return

        units = 1.0  # multiples of base_buy_usd
        if self.config.mode == "smart":
            when = unix_nanos_to_dt(bar.ts_event)
            fng = self.fng.value_on(when)
            if fng <= self.config.deep_fear_threshold:
                units += self.config.deep_fear_multiplier
                self.fear_buys += 1
            elif fng <= self.config.fear_threshold:
                units += self.config.fear_multiplier
                self.fear_buys += 1
            # dip boost (stacks with fear)
            if len(self._highs) == self.config.dip_lookback:
                recent_high = max(self._highs)
                if recent_high > 0 and float(bar.close) <= recent_high * (1 - self.config.dip_threshold):
                    units += self.config.dip_multiplier
                    self.dip_buys += 1

        self._buy(bar, units * self.config.base_buy_usd)

    def _buy(self, bar: Bar, usd: float):
        instrument = self.cache.instrument(self.iid)
        if instrument is None or usd <= 0:
            return
        qty = usd / float(bar.close)
        q = instrument.make_qty(qty)
        if float(q) <= 0:
            return
        self.submit_order(self.order_factory.market(self.iid, OrderSide.BUY, q))

    def on_order_filled(self, event):
        # Accurate accounting from actual fills.
        px = float(event.last_px)
        qty = float(event.last_qty)
        self.invested_usd += px * qty
        self.coin_qty += qty
        self.buys += 1

    # ----- reporting -----
    def avg_cost(self) -> float:
        return self.invested_usd / self.coin_qty if self.coin_qty > 0 else 0.0

    def final_value(self) -> float:
        return self.coin_qty * self.last_price

    def roi(self) -> float:
        return (self.final_value() / self.invested_usd - 1.0) if self.invested_usd > 0 else 0.0
