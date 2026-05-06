"""
HonestTrend1mMTF — 1m strategy with 4h regime filter

Adds a single new entry rule on top of HonestTrendGeneric:
  - Only enter long if the 4h timeframe is in a confirmed uptrend
    (4h EMA fast > 4h EMA slow on the most recent closed 4h candle)

This is a "regime gate", not a consensus signal. Stage 2 showed 1h-as-trigger
fails, but 4h-as-filter is a different mechanism: we still enter on 1m
signals, but skip them entirely if the macro tape is bearish.

Default 4h EMA: 96/288 = 16d / 48d (matches retired HonestTrend4h champion).
"""

from datetime import datetime
from typing import Optional

import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib

from freqtrade.strategy import IntParameter, merge_informative_pair, Trade

from HonestTrendGeneric import HonestTrendGeneric


class HonestTrend1mMTF(HonestTrendGeneric):
    timeframe = "1m"
    startup_candle_count = 2500  # for 1m EMA 2085

    # 1m signal params (same as HonestTrend1mLive)
    ema_fast = IntParameter(10, 2200, default=1410, space="buy", optimize=False)
    ema_slow = IntParameter(20, 4400, default=2085, space="buy", optimize=False)
    adx_threshold = IntParameter(10, 35, default=18, space="buy", optimize=False)
    min_hold_minutes = IntParameter(60, 2880, default=1440, space="buy", optimize=False)

    # 4h regime gate params
    regime_tf = "4h"
    regime_ema_fast = IntParameter(20, 200, default=96, space="buy", optimize=False)  # 16d
    regime_ema_slow = IntParameter(100, 500, default=288, space="buy", optimize=False)  # 48d

    def informative_pairs(self):
        # Pull 4h candles for every traded pair
        pairs = self.dp.current_whitelist() if self.dp else []
        return [(p, self.regime_tf) for p in pairs]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 1) Base 1m indicators (delegates to parent class)
        dataframe = super().populate_indicators(dataframe, metadata)

        # 2) Pull 4h informative dataframe and merge in regime status
        if self.dp is None:
            dataframe["regime_up"] = True
            return dataframe

        try:
            inf = self.dp.get_pair_dataframe(metadata["pair"], self.regime_tf)
        except Exception:
            inf = None

        if inf is None or len(inf) < self.regime_ema_slow.value + 5:
            dataframe["regime_up"] = False
            return dataframe

        ef = self.regime_ema_fast.value
        es = self.regime_ema_slow.value
        inf = inf.copy()
        inf[f"regime_ema_{ef}"] = ta.EMA(inf, timeperiod=ef)
        inf[f"regime_ema_{es}"] = ta.EMA(inf, timeperiod=es)
        inf["regime_up"] = inf[f"regime_ema_{ef}"] > inf[f"regime_ema_{es}"]
        # Keep only what we need, drop OHLCV from informative to avoid name clashes
        inf = inf[["date", "regime_up", f"regime_ema_{ef}", f"regime_ema_{es}"]]

        dataframe = merge_informative_pair(
            dataframe, inf, self.timeframe, self.regime_tf, ffill=True
        )
        # After merge_informative_pair, columns get suffix _4h
        dataframe["regime_up"] = dataframe[f"regime_up_{self.regime_tf}"].fillna(False)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Apply the parent's 6 base rules first
        dataframe = super().populate_entry_trend(dataframe, metadata)

        # Gate: only allow entries where 4h regime is up.
        # We OVERWRITE enter_long to 0 wherever regime_up is False.
        if "regime_up" in dataframe.columns:
            dataframe.loc[~dataframe["regime_up"], "enter_long"] = 0
            # Tag the surviving entries
            dataframe.loc[
                (dataframe["enter_long"] == 1) & (dataframe["regime_up"]),
                "enter_tag"
            ] = "trend_mtf"
        return dataframe
