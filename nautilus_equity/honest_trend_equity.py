"""HonestTrend ported from freqtrade (vectorized pandas) to NautilusTrader
(event-driven, incremental indicators).

Stage 2: faithful indicator/logic port.
Stage 3: equity realities — exchange-side protective stops (gap-safe), regular-trading-
         hours gating, and a pluggable regime gate replacing the crypto FNG filter.

Faithful port of strategies/HonestTrendGeneric.py. The mapping, and where work was
actually required:

  freqtrade (vectorized)                     Nautilus (incremental)            cost
  -----------------------------------------  --------------------------------  ------
  ta.EMA(fast) / ta.EMA(slow)                ExponentialMovingAverage          free (built-in)
  ta.PLUS_DI / ta.MINUS_DI                   DirectionalMovement .pos / .neg   free (built-in)
  ta.ADX                                     NOT built in → Wilder-smoothed DX  built here
  ta.SMA(volume)                             NOT built in for volume → manual   built here
  qtpylib.crossed_above/below               track previous fast/slow state     built here
  dataframe["fng"]                           crypto-only → RegimeGate (VIX/...)  regime_gate.py
  order_types stoploss_on_exchange=True      exchange-side STOP_MARKET order     built here (Stage 3)
  (implicit 24/7)                            RTH gating for equities             built here (Stage 3)
  confirm_trade_exit min_hold_minutes        track entry bar, gate in on_bar    built here
  adjust_trade_position (pyramid winners)    unrealized-profit checks in on_bar built here
  custom_stake_amount (Kelly)                kelly_stake(...) reused UNCHANGED  free (reused)
"""

from __future__ import annotations

import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from nautilus_trader.config import StrategyConfig
from nautilus_trader.core.datetime import unix_nanos_to_dt
from nautilus_trader.indicators import (
    DirectionalMovement,
    ExponentialMovingAverage,
    SimpleMovingAverage,
    WilderMovingAverage,
)
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

# Reuse the Kelly sizer verbatim from the freqtrade strategies dir.
_HERE = Path(__file__).resolve().parent
_STRATS = _HERE.parent / "strategies"
_CRYPTO = _HERE.parent / "nautilus_crypto"  # trade_ledger lives here (shared by both engines)
for _p in (str(_HERE), str(_STRATS), str(_CRYPTO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from kelly_sizer import KellyStats, kelly_stake  # noqa: E402
from regime_gate import RegimeGate  # noqa: E402

# Persist fills / closed positions to quant.nautilus_trades with asset_class='equity'
# (mirrors the crypto Accumulator/Donchian). A missing module or unset TIMESCALE_URL
# makes the ledger a no-op (e.g. backtests), so this never affects trading. In the
# deployed nur app trade_ledger.py is copied flat alongside this file, so the import
# resolves there too.
try:
    from trade_ledger import TradeLedger
except ImportError:
    TradeLedger = None

_NY = ZoneInfo("America/New_York")


class HonestTrendEquityConfig(StrategyConfig, frozen=True):
    instrument_id: str
    bar_type: BarType
    ema_fast: int = 72
    ema_slow: int = 144
    adx_period: int = 14
    adx_threshold: float = 18.0
    vol_window: int = 20
    risk_frac: float = 0.10  # proposed fraction of equity per first entry (pre-Kelly)
    min_hold_bars: int = 1
    # Pyramid-on-winners (mirrors HonestTrendGeneric defaults)
    pyramid_1_trigger: float = 0.08
    pyramid_2_trigger: float = 0.10
    pyramid_1_stake_ratio: float = 0.80
    pyramid_2_stake_ratio: float = 0.80
    # ---- Stage 3: equity realities ----
    stop_loss_pct: float = 0.0  # 0 disables the protective stop; e.g. 0.08 = -8% from avg
    rth_only: bool = False  # gate entries to US regular trading hours (intraday bars)
    regime_csv: str | None = None  # FNG→VIX replacement; None = gate disabled
    regime_threshold: float = 80.0
    regime_mode: str = "block_above"
    # ---- Stage 4: multi-currency live (IB) ----
    # IB reports the account in ONE base-currency balance (e.g. SGD), but the stock is
    # quoted in USD. When the account has no balance entry in the instrument's quote
    # currency, fall back to the base-currency balance and convert with this FX rate,
    # expressed as QUOTE units per 1 BASE unit (e.g. base SGD, quote USD → ~0.74).
    # Default 1.0 = no conversion: correct whenever base == quote (all backtests use a
    # USD base account, so their behaviour is unchanged).
    quote_per_base_fx: float = 1.0


class HonestTrendEquity(Strategy):
    def __init__(self, config: HonestTrendEquityConfig):
        super().__init__(config)
        self.iid = InstrumentId.from_str(config.instrument_id)
        self.fast = ExponentialMovingAverage(config.ema_fast)
        self.slow = ExponentialMovingAverage(config.ema_slow)
        self.dm = DirectionalMovement(config.adx_period)
        self.adx = WilderMovingAverage(config.adx_period)  # ADX = Wilder MA of DX
        self.vol_sma = SimpleMovingAverage(config.vol_window)

        self._prev_fast: float | None = None
        self._prev_slow: float | None = None

        # Position bookkeeping
        self._entry_bar: int | None = None
        self._entry_count = 0
        self._initial_shares = 0  # shares of the first leg; pyramids size off this
        self._shares = 0  # total open shares (incl. pyramids)
        self._cost = 0.0  # total cost basis
        self._bar_i = -1

        self.regime = RegimeGate(
            csv_path=config.regime_csv,
            threshold=config.regime_threshold,
            mode=config.regime_mode,
        )

        self._kelly_stats: KellyStats | None = None

        self.entries = 0
        self.exits = 0
        self.pyramids = 0
        self.stops_placed = 0
        self.stop_exits = 0

        # Live persistence to quant.nautilus_trades (no-op in backtests / when
        # TIMESCALE_URL is unset). asset_class='equity' segregates the IB engine
        # from the crypto engines in the shared table.
        self._ledger = TradeLedger(asset_class="equity") if TradeLedger else None

    # ----- persistence (live only; ledger is a no-op otherwise) -----
    def on_position_opened(self, event):
        if self._ledger:
            self._ledger.record_open(event)

    def on_position_changed(self, event):
        # Pyramids grow the same position — upsert the updated qty / avg price.
        if self._ledger:
            self._ledger.record_open(event)

    def on_position_closed(self, event):
        # Fires for both signal exits and exchange-side stop fills.
        if self._ledger:
            self._ledger.record_close(event)

    # ----- lifecycle -----
    def on_start(self):
        self.register_indicator_for_bars(self.config.bar_type, self.fast)
        self.register_indicator_for_bars(self.config.bar_type, self.slow)
        self.register_indicator_for_bars(self.config.bar_type, self.dm)
        self.subscribe_bars(self.config.bar_type)

    def on_stop(self):
        self.cancel_all_orders(self.iid)
        self.close_all_positions(self.iid)

    # ----- core loop -----
    def on_bar(self, bar: Bar):
        self._bar_i += 1

        # Derived indicators (not registerable): update now that DM is current.
        if self.dm.initialized:
            pos, neg = self.dm.pos, self.dm.neg
            denom = pos + neg
            dx = 100.0 * abs(pos - neg) / denom if denom > 0 else 0.0
            self.adx.update_raw(dx)
        self.vol_sma.update_raw(float(bar.volume))

        # Detect a stop-out (exchange-side stop filled → position now flat).
        if self._entry_count > 0 and self.portfolio.is_flat(self.iid):
            self.stop_exits += 1
            self._reset_position_state()

        ready = (
            self.fast.initialized
            and self.slow.initialized
            and self.dm.initialized
            and self.adx.initialized
            and self.vol_sma.initialized
        )
        if not ready:
            self._remember_emas()
            return

        crossed_up = (
            self._prev_fast is not None
            and self._prev_fast <= self._prev_slow
            and self.fast.value > self.slow.value
        )
        crossed_down = (
            self._prev_fast is not None
            and self._prev_fast >= self._prev_slow
            and self.fast.value < self.slow.value
        )

        instrument = self.cache.instrument(self.iid)
        in_pos = self.portfolio.is_net_long(self.iid)

        if not in_pos:
            when = unix_nanos_to_dt(bar.ts_event)
            if (
                crossed_up
                and self.dm.pos > self.dm.neg
                and self.adx.value > self.config.adx_threshold
                and float(bar.volume) > self.vol_sma.value
                and float(bar.volume) > 0
                and self._rth_ok(when)
                and self.regime.allow(when.to_pydatetime() if hasattr(when, "to_pydatetime") else when)
            ):
                self._enter(bar, instrument)
        else:
            held = self._bar_i - (self._entry_bar or self._bar_i)
            if crossed_down and held >= self.config.min_hold_bars:
                self.cancel_all_orders(self.iid)  # remove protective stop
                self.close_all_positions(self.iid)
                self.exits += 1
                self._reset_position_state()
            else:
                self._maybe_pyramid(bar, instrument)

        self._remember_emas()

    # ----- helpers -----
    def _remember_emas(self):
        if self.fast.initialized and self.slow.initialized:
            self._prev_fast = self.fast.value
            self._prev_slow = self.slow.value

    def _rth_ok(self, when) -> bool:
        if not self.config.rth_only:
            return True
        t = when.astimezone(_NY)
        if t.weekday() >= 5:  # Sat/Sun
            return False
        mins = t.hour * 60 + t.minute
        return 9 * 60 + 30 <= mins < 16 * 60  # 09:30–16:00 ET

    def _equity_usd(self, instrument) -> float:
        # Equity expressed in the instrument's QUOTE currency (USD for these equities,
        # USDT for crypto spot) — that is the currency `stake_usd / price` divides in.
        account = self.portfolio.account(instrument.venue)
        if account is None:
            return 0.0
        quote_ccy = instrument.quote_currency
        bal = account.balance_total(quote_ccy)
        if bal is not None:
            return float(bal)
        # Multi-currency live (IB): the account holds no balance in the quote currency
        # (it reports a single base-currency figure, e.g. SGD NetLiquidation). Fall back
        # to the base balance and convert to the quote currency via the configured FX
        # rate. Without this, balance_total(USD) is None → equity 0 → the strategy would
        # silently never enter on an SGD/EUR/etc. base account.
        base_bal = account.balance_total()  # base-currency total (default arg)
        if base_bal is None:
            return 0.0
        return float(base_bal) * self.config.quote_per_base_fx

    def _avg_entry(self) -> float | None:
        return self._cost / self._shares if self._shares > 0 else None

    def _enter(self, bar: Bar, instrument):
        equity = self._equity_usd(instrument)
        if equity <= 0:
            return
        stake_usd = kelly_stake(
            equity=equity,
            stats=self._kelly_stats,
            proposed_stake=equity * self.config.risk_frac,
            max_stake=equity,
        )
        shares = int(stake_usd / float(bar.close))
        if shares < 1:
            return
        self.submit_order(
            self.order_factory.market(self.iid, OrderSide.BUY, instrument.make_qty(shares))
        )
        self.entries += 1
        self._entry_bar = self._bar_i
        self._entry_count = 1
        self._initial_shares = shares
        self._shares = shares
        self._cost = shares * float(bar.close)
        self._place_stop(instrument)

    def _maybe_pyramid(self, bar: Bar, instrument):
        """Add to winners only — never to losers (no martingale). Max 2 pyramids."""
        avg = self._avg_entry()
        if avg is None or self._entry_count >= 3:
            return
        profit = (float(bar.close) - avg) / avg
        c = self.config
        if self._entry_count == 1 and profit >= c.pyramid_1_trigger:
            ratio = c.pyramid_1_stake_ratio
        elif self._entry_count == 2 and profit >= c.pyramid_2_trigger:
            ratio = c.pyramid_2_stake_ratio
        else:
            return
        # Pyramid sizes off the initial leg (mirrors HonestTrendGeneric: ratio × initial).
        shares = max(1, int(self._initial_shares * ratio))
        self.submit_order(
            self.order_factory.market(self.iid, OrderSide.BUY, instrument.make_qty(shares))
        )
        self._entry_count += 1
        self.pyramids += 1
        self._shares += shares
        self._cost += shares * float(bar.close)
        # Re-place the protective stop for the new, larger position at the new avg.
        self.cancel_all_orders(self.iid)
        self._place_stop(instrument)

    def _place_stop(self, instrument):
        if self.config.stop_loss_pct <= 0 or self._shares < 1:
            return
        avg = self._avg_entry()
        if avg is None:
            return
        stop_price = avg * (1.0 - self.config.stop_loss_pct)
        order = self.order_factory.stop_market(
            instrument_id=self.iid,
            order_side=OrderSide.SELL,
            quantity=instrument.make_qty(self._shares),
            trigger_price=instrument.make_price(stop_price),
            reduce_only=True,
        )
        self.submit_order(order)
        self.stops_placed += 1

    def _reset_position_state(self):
        self._entry_bar = None
        self._entry_count = 0
        self._initial_shares = 0
        self._shares = 0
        self._cost = 0.0
