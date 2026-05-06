"""HonestTrend15mProtections — HonestTrend15mDry + protections only (no custom_stoploss)."""
from HonestTrendGeneric import HonestTrendGeneric
from freqtrade.strategy import IntParameter


class HonestTrend15mProtections(HonestTrendGeneric):
    timeframe = "15m"
    startup_candle_count = 500

    ema_fast = IntParameter(10, 400, default=94, space="buy", optimize=False)
    ema_slow = IntParameter(20, 500, default=139, space="buy", optimize=False)
    adx_threshold = IntParameter(10, 35, default=18, space="buy", optimize=False)
    min_hold_minutes = IntParameter(60, 2880, default=720, space="buy", optimize=False)

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 8},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 96,
                "trade_limit": 3,
                "stop_duration_candles": 48,
                "only_per_pair": True,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 288,
                "trade_limit": 5,
                "stop_duration_candles": 96,
                "max_allowed_drawdown": 0.10,
            },
        ]
