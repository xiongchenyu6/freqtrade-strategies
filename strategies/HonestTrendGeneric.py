"""
HonestTrendGeneric — Cross-timeframe consistency test

Generic 2x EMA crossover strategy. Parameters controlled via JSON:
  - ema_fast: the fast EMA period
  - ema_slow: typically 2×fast
  - min_hold_minutes: minimum hold time in minutes (not candles)

Timeframe set via config_backtest_<tf>.json, strategy-agnostic.
"""

import csv
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import talib.abstract as ta
from pandas import DataFrame
from technical import qtpylib

from freqtrade.strategy import IStrategy, Trade, IntParameter, DecimalParameter

# Import risk manager from same directory
_STRAT_DIR = Path(__file__).parent
if str(_STRAT_DIR) not in sys.path:
    sys.path.insert(0, str(_STRAT_DIR))
from risk_manager import RiskManager  # noqa: E402
from kelly_sizer import (  # noqa: E402
    KellyStats,
    kelly_stake,
    latest_strategy_stats,
)

logger = logging.getLogger(__name__)

_RISK_STATE_FILE = Path(__file__).parent.parent / "risk_state.json"

FNG_DATA = {}
_fng_path = Path(__file__).parent.parent / "data" / "fng_history.csv"
if _fng_path.exists():
    with open(_fng_path) as f:
        for row in csv.DictReader(f):
            FNG_DATA[row["date"]] = int(row["value"])


class HonestTrendGeneric(IStrategy):

    INTERFACE_VERSION = 3
    can_short = False
    minimal_roi = {"0": 100}
    stoploss = -0.99
    use_exit_signal = True
    process_only_new_candles = True
    startup_candle_count = 2500  # enough for EMA up to ~2200
    timeframe = "15m"  # overridden by config

    # Structural params — NOT hyperoptable. Tested 2026-04-21: making adx/min_hold
    # optimizable improved in-sample but pushed out-of-sample DD from 15.5% → 24.8%
    # (above our 20% kill-switch). See docs/HYPEROPT_PYRAMID_TUNING.md "Rejected experiment".
    ema_fast = IntParameter(10, 2200, default=72, space="buy", optimize=False)
    ema_slow = IntParameter(20, 4400, default=144, space="buy", optimize=False)
    adx_threshold = IntParameter(10, 35, default=18, space="buy", optimize=False)
    min_hold_minutes = IntParameter(60, 2880, default=720, space="buy", optimize=False)

    FNG_BLOCK = 80

    # ---- Pyramid winners (adopted 2026-04-21, see docs/EXPERIMENTS_DCA_AND_PYRAMID.md) ----
    # Backtest 2017-08 → 2026-04 showed +41% absolute profit vs single-entry at lower max DD.
    # Requires in config:
    #   "position_adjustment_enable": true
    #   "max_entry_position_adjustment": 2
    position_adjustment_enable = True
    max_entry_position_adjustment = 2

    # Hyperoptable — defaults tuned via hyperopt 100 epochs on 2022-2024 BTC+ETH 15m
    # using HonestHyperOptLoss (Calmar-weighted, DD-penalized).
    # Walk-forward validated: 5/8 windows 2017-2026, incl. out-of-sample W1/W8 both improved.
    pyramid_1_trigger     = DecimalParameter(0.03, 0.10, default=0.08, decimals=2, space="buy", optimize=True)
    pyramid_2_trigger     = DecimalParameter(0.08, 0.20, default=0.10, decimals=2, space="buy", optimize=True)
    pyramid_1_stake_ratio = DecimalParameter(0.30, 1.00, default=0.80, decimals=1, space="buy", optimize=True)
    pyramid_2_stake_ratio = DecimalParameter(0.20, 0.80, default=0.80, decimals=1, space="buy", optimize=True)

    order_types = {
        "entry": "limit", "exit": "limit",
        "stoploss": "market", "stoploss_on_exchange": True,
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ef, es = self.ema_fast.value, self.ema_slow.value
        dataframe[f"ema_{ef}"] = ta.EMA(dataframe, timeperiod=ef)
        dataframe[f"ema_{es}"] = ta.EMA(dataframe, timeperiod=es)
        dataframe["adx"] = ta.ADX(dataframe)
        dataframe["plus_di"] = ta.PLUS_DI(dataframe)
        dataframe["minus_di"] = ta.MINUS_DI(dataframe)

        # Volume SMA scaled to 1 day of candles
        tf_minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}.get(self.timeframe, 15)
        vol_window = max(1, 1440 // tf_minutes)
        dataframe["volume_sma"] = ta.SMA(dataframe["volume"], timeperiod=vol_window)

        dataframe["fng"] = dataframe["date"].apply(
            lambda x: FNG_DATA.get(x.strftime("%Y-%m-%d"), 50)
        )
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ef = f"ema_{self.ema_fast.value}"
        es = f"ema_{self.ema_slow.value}"

        dataframe.loc[
            (qtpylib.crossed_above(dataframe[ef], dataframe[es]))
            & (dataframe["plus_di"] > dataframe["minus_di"])
            & (dataframe["adx"] > self.adx_threshold.value)
            & (dataframe["volume"] > dataframe["volume_sma"])
            & (dataframe["fng"] < self.FNG_BLOCK)
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "trend")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ef = f"ema_{self.ema_fast.value}"
        es = f"ema_{self.ema_slow.value}"

        dataframe.loc[
            (qtpylib.crossed_below(dataframe[ef], dataframe[es]))
            & (dataframe["volume"] > 0),
            ["exit_long", "exit_tag"],
        ] = (1, "trend_exit")
        return dataframe

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float,
                            rate: float, time_in_force: str, current_time: datetime,
                            entry_tag: Optional[str], side: str, **kwargs) -> bool:
        """Consult risk manager before allowing entry (live only)."""
        if self.dp.runmode.value not in ("live", "dry_run"):
            return True
        try:
            rm = RiskManager(_RISK_STATE_FILE)
            allowed, reason = rm.can_enter()
            if not allowed:
                logger.warning(f"BLOCKED entry {pair}: risk state = {reason}")
                return False
        except Exception as e:
            logger.error(f"Risk manager error (fail-safe: allow): {e}")
        return True

    def confirm_trade_exit(self, pair: str, trade: Trade, order_type: str,
                           amount: float, rate: float, time_in_force: str,
                           exit_reason: str, current_time: datetime, **kwargs) -> bool:
        if exit_reason in ("force_exit", "stoploss"):
            return True
        minutes = (current_time - trade.open_date).total_seconds() / 60
        if minutes < self.min_hold_minutes.value:
            return False
        return True

    # Cached Kelly stats — loaded once per process from the latest backtest zip
    # for this concrete strategy class. None means "no usable backtest data yet,
    # fall back to proposed_stake". We refresh once per bot_loop_start so a
    # mid-session re-backtest can update sizing without restart.
    _kelly_stats: Optional[KellyStats] = None
    _kelly_stats_loaded: bool = False

    def bot_loop_start(self, current_time: datetime, **kwargs) -> None:
        # Lazy-load stats once, then refresh on subsequent loops only if the
        # backtest_results folder has new entries (cheap mtime check).
        if not self._kelly_stats_loaded:
            self._kelly_stats = latest_strategy_stats(self.__class__.__name__)
            self._kelly_stats_loaded = True
            if self._kelly_stats is None:
                logger.info("Kelly: no backtest stats found, using proposed_stake")
            else:
                s = self._kelly_stats
                logger.info(
                    "Kelly: loaded stats p=%.3f b=%.2f n=%d f_half=%.4f",
                    s.win_rate, s.payoff_ratio, s.n_trades, s.half_kelly_clamped(),
                )

    def custom_stake_amount(self, pair: str, current_time: datetime,
                            current_rate: float, proposed_stake: float,
                            min_stake: Optional[float], max_stake: float,
                            leverage: float, entry_tag: Optional[str],
                            side: str, **kwargs) -> float:
        # Equity in stake currency. wallets is None during backtest replay of
        # the very first candle, hence the try/except.
        equity = 0.0
        try:
            equity = float(self.wallets.get_total_stake_amount())
        except Exception:
            equity = 0.0

        return kelly_stake(
            equity=equity,
            stats=self._kelly_stats,
            proposed_stake=proposed_stake,
            max_stake=max_stake,
        )

    class HyperOpt:
        """Nested HyperOpt class. Freqtrade looks here for generate_estimator."""

        @staticmethod
        def generate_estimator(dimensions, **kwargs):
            """CmaEs sampler — faster convergence for continuous params than NSGAIII.

            CmaEs (Covariance Matrix Adaptation) is built for continuous optimization
            and typically converges 2-3× faster on smooth loss landscapes.
            """
            from optuna.samplers import CmaEsSampler
            return CmaEsSampler(
                seed=kwargs.get("random_state", 42),
                n_startup_trials=10,
            )

    def adjust_trade_position(self, trade: Trade, current_time: datetime,
                              current_rate: float, current_profit: float,
                              min_stake: Optional[float], max_stake: float,
                              current_entry_rate: float, current_exit_rate: float,
                              current_entry_profit: float, current_exit_profit: float,
                              **kwargs) -> Optional[float]:
        """Pyramid on winners only. Never on losers (no martingale)."""
        t1 = self.pyramid_1_trigger.value
        t2 = self.pyramid_2_trigger.value
        r1 = self.pyramid_1_stake_ratio.value
        r2 = self.pyramid_2_stake_ratio.value

        # Hard rule: don't add to losers
        if current_profit < t1:
            return None

        entries = trade.nr_of_successful_entries
        if entries >= 3:  # initial + 2 pyramids max
            return None

        initial_stake = trade.orders[0].stake_amount
        if entries == 1 and current_profit >= t1:
            stake = initial_stake * r1
        elif entries == 2 and current_profit >= t2:
            stake = initial_stake * r2
        else:
            return None

        if min_stake is not None:
            stake = max(min_stake, stake)
        stake = min(max_stake, stake)
        return stake
