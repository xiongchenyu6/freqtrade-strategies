"""
HonestTrend1mLive — 1m live deployment variant of HonestTrendGeneric

Fixed params (validated in Stage 1-3):
  - EMA 1410/2085 (~24h fast / 35h slow, ratio 1.48x)
  - ADX > 18
  - Min hold 24h (1440 min)
  - Walk-forward 4/4 positive
  - Risk manager wired (pauses at 15% DD, retires at 20% DD)
"""

from HonestTrendGeneric import HonestTrendGeneric
from freqtrade.strategy import IntParameter


class HonestTrend1mLive(HonestTrendGeneric):
    timeframe = "1m"
    startup_candle_count = 2500

    ema_fast = IntParameter(10, 2200, default=1410, space="buy", optimize=False)
    ema_slow = IntParameter(20, 4400, default=2085, space="buy", optimize=False)
    adx_threshold = IntParameter(10, 35, default=18, space="buy", optimize=False)
    min_hold_minutes = IntParameter(60, 2880, default=1440, space="buy", optimize=False)
