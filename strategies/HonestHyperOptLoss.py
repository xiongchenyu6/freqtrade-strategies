"""HonestHyperOptLoss — custom hyperopt loss tailored to HonestTrend.

Philosophy:
  - REJECT any params that produce max DD > 20% (our kill-switch threshold)
  - MAXIMIZE Calmar ratio (return / max DD) — the right metric for trend strategies
  - PENALIZE when DD > 15% via soft penalty (kicks in before hard cutoff)
  - FLOOR on trade count (>= 50) — avoid hyperopt picking params with ~5 trades that look great

Returns: lower = better. Return -Calmar so lower is better.
"""
import os
from datetime import datetime
from math import nan

from pandas import DataFrame

from freqtrade.optimize.hyperopt import IHyperOptLoss


# Override via env var for timeframe-specific tuning
# (1m strategies with slow EMAs produce fewer trades per year)
MIN_TRADES = int(os.environ.get("HONEST_MIN_TRADES", "50"))
HARD_DD_CUTOFF = float(os.environ.get("HONEST_HARD_DD_CUTOFF", "0.20"))
SOFT_DD_KICK_IN = float(os.environ.get("HONEST_SOFT_DD_KICK_IN", "0.15"))


class HonestHyperOptLoss(IHyperOptLoss):
    @staticmethod
    def hyperopt_loss_function(
        results: DataFrame,
        trade_count: int,
        min_date: datetime,
        max_date: datetime,
        config: dict,
        processed: dict,
        backtest_stats: dict,
        starting_balance: float,
        **kwargs,
    ) -> float:
        # Reject low-trade-count results (hyperopt might pick edge cases)
        if trade_count < MIN_TRADES:
            return 999.0

        total_profit = results["profit_abs"].sum()
        if total_profit <= 0:
            return 99.0  # clearly losing, but better than zero-trade nan

        # Max drawdown from backtest_stats (preferred) or compute from results
        max_dd = 0.0
        if backtest_stats and "max_drawdown_account" in backtest_stats:
            max_dd = abs(backtest_stats["max_drawdown_account"])
        else:
            # Fallback: compute equity curve max DD
            r = results.sort_values("close_date").copy()
            r["equity"] = starting_balance + r["profit_abs"].cumsum()
            r["peak"] = r["equity"].cummax()
            r["dd"] = (r["equity"] - r["peak"]) / r["peak"]
            max_dd = abs(r["dd"].min()) if len(r) else 0.0

        # Hard cutoff
        if max_dd > HARD_DD_CUTOFF:
            return 100.0 + max_dd * 10  # progressively worse the higher DD

        # Calmar = return% / max_dd%
        return_pct = total_profit / starting_balance
        calmar = return_pct / max(max_dd, 0.01)

        # Soft DD penalty: 1.0 at DD=15%, 2.0 at DD=20%
        if max_dd > SOFT_DD_KICK_IN:
            penalty = 1.0 + (max_dd - SOFT_DD_KICK_IN) * 20
            calmar = calmar / penalty

        # Return negative Calmar (hyperopt minimizes)
        return -calmar
