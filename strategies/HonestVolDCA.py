"""
HonestVolDCA — Volatility-regime DCA with ATR-normalised position sizing.

Enhancement of the SUSTAIN/CAPITUL DCA concept as a freqtrade IStrategy.
Enters on significant price drawdown (close drops > drawdown_threshold below
its SMA) and sizes the stake inversely to current volatility:

  Low vol  (ATR/close < 0.02) → controlled dip → full stake (1.0×)
  Normal   (ATR/close 0.02–0.04)               → 0.7× stake
  High vol (ATR/close > 0.04) → panic selling  → 0.5× stake

Rationale: buying in panic-vol environments is still worthwhile but riskier;
size down to preserve dry powder for deeper drawdowns.

Entry conditions:
  1. close < SMA(sma_period) × (1 − drawdown_threshold)  (distress signal)
  2. FnG < 75  (do not buy into greed-driven drops, which are just corrections)

Exit:
  minimal_roi = {"0": profit_target}  (default 15% — long-term bag flip)
  Stoploss: −99% (spot accumulation; hold through drawdowns)

Timeframe: 1d (daily candles for stability — avoids noise entries)
Pairs:     BTC/USDT, ETH/USDT, SOL/USDT
Max open trades: 2

Hyperoptable parameters:
  drawdown_threshold   % below SMA to trigger entry     [0.05–0.20, default 0.08]
  profit_target        minimal_roi target pct            [0.08–0.30, default 0.15]
  sma_period           SMA lookback in days              [10–30,     default 20]

Config suggestions:
  "max_open_trades": 2
  "stake_amount": "unlimited"
  "position_adjustment_enable": false
  "timeframe": "1d"
"""

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import talib.abstract as ta
from pandas import DataFrame

from freqtrade.strategy import DecimalParameter, IStrategy, IntParameter, Trade

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fear & Greed history — same loading pattern as HonestTrendGeneric
# ---------------------------------------------------------------------------
FNG_DATA: dict[str, int] = {}
_fng_path = Path(__file__).parent.parent / "data" / "fng_history.csv"
if _fng_path.exists():
    with open(_fng_path) as _f:
        for _row in csv.DictReader(_f):
            FNG_DATA[_row["date"]] = int(_row["value"])


class HonestVolDCA(IStrategy):
    """
    Volatility-normalised DCA entry strategy.

    Accumulates BTC/ETH/SOL during significant drawdowns while scaling stake
    size down when volatility is already elevated — buying more when the dip
    is controlled, less when the market is in outright panic.
    """

    INTERFACE_VERSION = 3
    can_short = False

    # Exit via minimal_roi only; set dynamically in __init__ from hyperopt param
    minimal_roi = {"0": 0.15}
    stoploss = -0.99  # spot accumulation — hold through drawdowns
    use_exit_signal = False
    process_only_new_candles = True
    startup_candle_count = 60  # 60 daily candles covers SMA(30) + ATR warm-up
    timeframe = "1d"

    position_adjustment_enable = False

    # ---- Hyperoptable parameters ----
    drawdown_threshold = DecimalParameter(0.05, 0.20, default=0.08, decimals=2,
                                          space="buy", optimize=True)
    profit_target = DecimalParameter(0.08, 0.30, default=0.15, decimals=2,
                                     space="sell", optimize=True)
    sma_period = IntParameter(10, 30, default=20, space="buy", optimize=True)

    # FnG gate: do not enter when market is greedy (> 75)
    FNG_BLOCK = 75

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,  # spot only; no exchange stoploss needed
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    def __init__(self, config: dict) -> None:
        """Apply profit_target hyperopt param to minimal_roi at init time."""
        super().__init__(config)
        # Sync minimal_roi with the hyperopt-tuned profit_target.
        # During hyperopt freqtrade evaluates __init__ per trial, so this is safe.
        self.minimal_roi = {"0": self.profit_target.value}

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Compute SMA, ATR, ATR ratio, and FnG overlay."""
        sma_p = self.sma_period.value

        dataframe["price_sma"] = ta.SMA(dataframe, timeperiod=sma_p)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)

        # atr_ratio: normalised volatility (ATR as fraction of close price)
        dataframe["atr_ratio"] = dataframe["atr"] / dataframe["close"].replace(0, float("nan"))

        # Entry trigger level: SMA × (1 − drawdown_threshold)
        dataframe["entry_level"] = dataframe["price_sma"] * (1.0 - self.drawdown_threshold.value)

        # FnG overlay — fills missing dates with neutral value 50
        dataframe["fng"] = dataframe["date"].apply(
            lambda x: FNG_DATA.get(x.strftime("%Y-%m-%d"), 50)
        )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        Enter when close drops more than drawdown_threshold below its SMA,
        provided FnG is not in extreme greed territory.

        Conditions:
          1. close < price_sma × (1 − drawdown_threshold)
          2. fng < FNG_BLOCK
          3. volume > 0  (data sanity)
        """
        dataframe.loc[
            (dataframe["close"] < dataframe["entry_level"])
            & (dataframe["fng"] < self.FNG_BLOCK)
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "vol_dca")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Exit is driven by minimal_roi only; no signal exit needed."""
        return dataframe

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: Optional[float],
        max_stake: float,
        leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        """
        Scale stake inversely to current ATR ratio (volatility).

        ATR ratio buckets:
          < 0.02   low vol, controlled dip   → 1.0× (full stake)
          0.02–0.04 normal vol               → 0.7×
          > 0.04   high vol, panic           → 0.5×

        Falls back to proposed_stake if dataframe is unavailable (e.g. backtesting
        warm-up candles).

        :param pair: trading pair
        :param current_time: current UTC datetime
        :param current_rate: current close price
        :param proposed_stake: stake amount from config / wallet
        :param min_stake: exchange minimum stake
        :param max_stake: maximum allowed stake
        :param leverage: leverage (always 1 for spot)
        :param entry_tag: tag from populate_entry_trend
        :param side: "long" (always for this strategy)
        :return: adjusted stake amount
        """
        multiplier = 1.0
        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe is not None and not dataframe.empty:
                last = dataframe.iloc[-1]
                atr_ratio: float = float(last.get("atr_ratio", 0.03))
                if atr_ratio < 0.02:
                    multiplier = 1.0   # low vol
                elif atr_ratio <= 0.04:
                    multiplier = 0.7   # normal vol
                else:
                    multiplier = 0.5   # high vol / panic
                logger.debug(
                    f"custom_stake {pair}: atr_ratio={atr_ratio:.4f}  multiplier={multiplier:.1f}x"
                )
        except Exception as exc:
            logger.warning(f"custom_stake_amount lookup failed for {pair}: {exc}")

        stake = proposed_stake * multiplier
        if min_stake is not None:
            stake = max(min_stake, stake)
        stake = min(max_stake, stake)
        return stake

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: datetime,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> bool:
        """
        Allow entry in all runmodes.

        For live/dry_run, an additional FnG real-time check could be inserted
        here (similar to HonestTrendGeneric's risk_manager hook).  Kept simple
        for now — the FnG check in populate_entry_trend already filters.
        """
        return True
