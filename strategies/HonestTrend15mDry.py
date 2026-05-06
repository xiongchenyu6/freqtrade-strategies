"""
HonestTrend15mDry — 15m dry-run parallel validator

Same logic as 1m live, but at 15m timeframe. Runs in parallel dry-run to:
  - Compare live vs dry-run fills (slippage/latency sanity check)
  - Get second opinion on regime changes
  - Provide robustness if 1m fails

Params scaled to 15m:
  - EMA 94/139 (same ~24h/35h signal duration)
  - ADX > 18
  - Min hold 12h (720 min)
"""

from HonestTrendGeneric import HonestTrendGeneric
from freqtrade.strategy import IntParameter


class HonestTrend15mDry(HonestTrendGeneric):
    timeframe = "15m"
    startup_candle_count = 500

    ema_fast = IntParameter(10, 400, default=94, space="buy", optimize=False)
    ema_slow = IntParameter(20, 500, default=139, space="buy", optimize=False)
    adx_threshold = IntParameter(10, 35, default=18, space="buy", optimize=False)
    min_hold_minutes = IntParameter(60, 2880, default=720, space="buy", optimize=False)
