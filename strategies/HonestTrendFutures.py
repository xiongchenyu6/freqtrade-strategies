"""
HonestTrendFutures — futures variant of HonestTrendGeneric with short support.

Extends base class with:
  - can_short = True (enables short signals)
  - Mirror short entry/exit: crossed_below + minus_di > plus_di + adx > threshold
  - FnG short filter: block shorts when FnG > 70 (don't short euphoria)
  - Real stoploss (-8%): futures can't run stoploss=-0.99 like spot
  - Leverage: 1x default (no liquidation risk, pure directional alpha)

Phase B — see docs/HYPEROPT_PYRAMID_TUNING.md future section.
"""

import logging
from datetime import datetime
from typing import Optional

from pandas import DataFrame
from technical import qtpylib

from HonestTrendGeneric import HonestTrendGeneric
from freqtrade.strategy import IntParameter

logger = logging.getLogger(__name__)


class HonestTrendFutures(HonestTrendGeneric):
    can_short = True
    stoploss = -0.08  # hard stop; overrides base -0.99 (spot-only)

    # Entry gate for shorts: FnG above this → skip (don't short euphoria)
    FNG_SHORT_BLOCK = 70

    timeframe = "15m"
    startup_candle_count = 500

    ema_fast = IntParameter(10, 400, default=94, space="buy", optimize=False)
    ema_slow = IntParameter(20, 500, default=139, space="buy", optimize=False)
    adx_threshold = IntParameter(10, 35, default=18, space="buy", optimize=False)
    min_hold_minutes = IntParameter(60, 2880, default=720, space="buy", optimize=False)

    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: Optional[str],
                 side: str, **kwargs) -> float:
        return 1.0

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_entry_trend(dataframe, metadata)

        ef = f"ema_{self.ema_fast.value}"
        es = f"ema_{self.ema_slow.value}"

        dataframe.loc[
            (qtpylib.crossed_below(dataframe[ef], dataframe[es]))
            & (dataframe["minus_di"] > dataframe["plus_di"])
            & (dataframe["adx"] > self.adx_threshold.value)
            & (dataframe["volume"] > dataframe["volume_sma"])
            & (dataframe["fng"] < self.FNG_SHORT_BLOCK)
            & (dataframe["volume"] > 0),
            ["enter_short", "enter_tag"],
        ] = (1, "trend_short")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_exit_trend(dataframe, metadata)

        ef = f"ema_{self.ema_fast.value}"
        es = f"ema_{self.ema_slow.value}"

        dataframe.loc[
            (qtpylib.crossed_above(dataframe[ef], dataframe[es]))
            & (dataframe["volume"] > 0),
            ["exit_short", "exit_tag"],
        ] = (1, "trend_short_exit")
        return dataframe
