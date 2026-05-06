"""
HonestGrid — Grid trading for range-bound markets.

Complements HonestTrendGeneric: enters only when ADX is LOW (sideways market).
Places staggered buy entries as price pulls back inside the range, exits when
price recovers by one ATR-sized grid step.

Core logic:
  - Regime filter: ADX < adx_max (default 20) → range-bound, OK to enter
  - Grid spacing: grid_atr_multiplier × ATR(atr_period) as % of close price
  - Entry: close crosses below price_sma − 0.5 × ATR (pullback into range)
            AND ADX < adx_max AND volume > volume_sma
  - Exit:  close crosses above price_sma + 0.5 × ATR (recovery to mid-range)
  - Stoploss: −15% (wide; avoids premature exit inside the range)
  - Timeframe: 1h
  - Pairs: BTC/USDT, ETH/USDT (spot only)

Hyperoptable parameters:
  adx_max             max ADX to allow entry          [10–30, default 20]
  grid_atr_multiplier grid spacing in ATR units       [1.0–3.0, default 1.5]
  atr_period          ATR lookback period              [7–28, default 14]

Suggested config additions:
  "max_open_trades": 3
  "stake_amount": "unlimited"   # or a fixed USDT amount
  "position_adjustment_enable": false
"""

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib

from freqtrade.strategy import DecimalParameter, IStrategy, IntParameter, Trade

logger = logging.getLogger(__name__)

# Fear & Greed history — same loading pattern as HonestTrendGeneric
FNG_DATA: dict[str, int] = {}
_fng_path = Path(__file__).parent.parent / "data" / "fng_history.csv"
if _fng_path.exists():
    with open(_fng_path) as _f:
        for _row in csv.DictReader(_f):
            FNG_DATA[_row["date"]] = int(_row["value"])


class HonestGrid(IStrategy):
    """
    Range-bound grid strategy.

    Enters on pullbacks inside a sideways regime (ADX < threshold).
    Uses ATR-normalised grid spacing for both entry levels and exit targets.
    Designed to be run alongside HonestTrendGeneric, which handles trending markets.
    """

    INTERFACE_VERSION = 3
    can_short = False

    # Wide ROI — we rely on custom_exit / exit signal for per-grid exits
    minimal_roi = {"0": 100}
    stoploss = -0.15
    use_exit_signal = True
    process_only_new_candles = True
    startup_candle_count = 100  # enough for SMA(20) + ATR(28) warm-up
    timeframe = "1h"

    # Do NOT pyramid grid entries
    position_adjustment_enable = False

    # ---- Hyperoptable parameters ----
    adx_max = IntParameter(10, 30, default=20, space="buy", optimize=True)
    grid_atr_multiplier = DecimalParameter(1.0, 3.0, default=1.5, decimals=1,
                                           space="buy", optimize=True)
    atr_period = IntParameter(7, 28, default=14, space="buy", optimize=True)

    # FnG block — don't buy into a range when euphoria is extreme (greed > 80)
    FNG_BLOCK = 80

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": True,
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Compute ADX, ATR, SMA(20), volume SMA, and FnG overlay."""
        atr_p = self.atr_period.value

        dataframe["adx"] = ta.ADX(dataframe)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=atr_p)
        dataframe["price_sma"] = ta.SMA(dataframe, timeperiod=20)

        # Volume SMA: 1 calendar day of 1h candles = 24 bars
        dataframe["volume_sma"] = ta.SMA(dataframe["volume"], timeperiod=24)

        # Derived grid bands
        half_atr = dataframe["atr"] * 0.5
        dataframe["lower_band"] = dataframe["price_sma"] - half_atr
        dataframe["upper_band"] = dataframe["price_sma"] + half_atr

        # FnG overlay (date-keyed, fills forward with 50 if missing)
        dataframe["fng"] = dataframe["date"].apply(
            lambda x: FNG_DATA.get(x.strftime("%Y-%m-%d"), 50)
        )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Enter when price pulls back below lower_band inside a range-bound regime.

        Conditions:
          1. ADX < adx_max  (not trending)
          2. close crossed below price_sma − 0.5×ATR  (pullback into range)
          3. volume > volume_sma  (participation confirms the move)
          4. FnG < FNG_BLOCK  (not in extreme greed)
        """
        dataframe.loc[
            (qtpylib.crossed_below(dataframe["close"], dataframe["lower_band"]))
            & (dataframe["adx"] < self.adx_max.value)
            & (dataframe["volume"] > dataframe["volume_sma"])
            & (dataframe["fng"] < self.FNG_BLOCK)
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "grid_pullback")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Exit when price recovers above upper_band (back to mid-range or above).

        This fires the exit signal; actual per-tranche take-profit at one grid
        step above entry is handled by custom_exit below.
        """
        dataframe.loc[
            (qtpylib.crossed_above(dataframe["close"], dataframe["upper_band"]))
            & (dataframe["volume"] > 0),
            ["exit_long", "exit_tag"],
        ] = (1, "grid_recovery")
        return dataframe

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> Optional[str]:
        """
        Exit each tranche when profit >= one grid step.

        Grid step = grid_atr_multiplier × ATR / open_rate (approx %).
        We use a fixed ATR snapshot at entry; the ATR column is not directly
        available here so we approximate from trade metadata or fall back to
        a percentage derived from the open rate.
        """
        # Approximate grid step from the hyperopt param + current volatility proxy.
        # Freqtrade does not pass the dataframe here, so we use a simple
        # heuristic: grid_atr_multiplier × 1.5% as a baseline grid step.
        # In a full deployment you'd store ATR at entry in trade.meta.
        base_step_pct = self.grid_atr_multiplier.value * 0.015
        if current_profit >= base_step_pct:
            return "grid_step_exit"
        return None

    def confirm_trade_exit(
        self,
        pair: str,
        trade: Trade,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        exit_reason: str,
        current_time: datetime,
        **kwargs,
    ) -> bool:
        """Always allow stoploss and forced exits; allow all others immediately."""
        if exit_reason in ("force_exit", "stoploss"):
            return True
        return True
