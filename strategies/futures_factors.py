"""
Binance Futures Market Factors — FREE, no API key needed

Factors:
  1. Funding Rate — extreme negative = squeeze coming, extreme positive = correction risk
  2. Open Interest — OI+price divergence reveals hidden positioning
  3. Long/Short Ratio — contrarian signal (retail is usually wrong)
  4. Taker Buy/Sell — who is aggressively buying vs selling

Usage:
    from futures_factors import FuturesFactors
    ff = FuturesFactors()
    data = ff.fetch_all()
    print(data["combined_score"], data["signal"])
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger("futures_factors")

BASE_URL = "https://fapi.binance.com"


class FuturesFactors:
    """Fetch and score Binance Futures market microstructure data."""

    def __init__(self, symbol: str = "BTCUSDT"):
        self.symbol = symbol
        self._cache: dict = {}
        self._cache_ts: float = 0
        self._CACHE_TTL = 900  # 15 min

    def _get(self, path: str, params: dict = None) -> Optional[list]:
        try:
            resp = requests.get(
                f"{BASE_URL}{path}",
                params=params or {},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"Binance Futures API failed ({path}): {e}")
            return None

    # ------------------------------------------------------------------
    # Factor 1: Funding Rate
    # ------------------------------------------------------------------
    def fetch_funding_rate(self) -> dict:
        """
        Funding rate: paid every 8h between longs and shorts.
        Extreme negative = shorts pay longs = shorts overcrowded = squeeze.
        Extreme positive = longs pay shorts = longs overleveraged = dump risk.
        """
        data = self._get("/fapi/v1/fundingRate", {
            "symbol": self.symbol, "limit": 10,
        })
        if not data:
            return {"score": 0, "rate": 0, "signal": "neutral"}

        current_rate = float(data[-1]["fundingRate"])
        # Average of last 3 funding periods (24h)
        avg_rate = sum(float(d["fundingRate"]) for d in data[-3:]) / 3

        # Scoring: contrarian
        if avg_rate < -0.0005:
            score = 0.8   # very negative = strong squeeze potential
        elif avg_rate < -0.0001:
            score = 0.4   # moderately negative = bullish lean
        elif avg_rate > 0.001:
            score = -0.8  # very positive = overleveraged longs
        elif avg_rate > 0.0003:
            score = -0.4  # moderately positive = caution
        else:
            score = 0.0   # neutral

        logger.info(
            f"Funding Rate: current={current_rate:.6f}, "
            f"24h_avg={avg_rate:.6f}, score={score:+.1f}"
        )

        return {
            "score": score,
            "rate": current_rate,
            "avg_24h": avg_rate,
            "signal": "bullish" if score > 0.2 else "bearish" if score < -0.2 else "neutral",
        }

    # ------------------------------------------------------------------
    # Factor 2: Open Interest
    # ------------------------------------------------------------------
    def fetch_open_interest(self) -> dict:
        """
        Open Interest trend vs price trend.
        OI↑ + Price↑ = genuine trend (new money entering)
        OI↑ + Price↓ = shorts building (bearish pressure)
        OI↓ + Price↑ = short covering (weak rally)
        OI↓ + Price↓ = capitulation (potential bottom)
        """
        data = self._get("/futures/data/openInterestHist", {
            "symbol": self.symbol, "period": "1d", "limit": 14,
        })
        if not data or len(data) < 7:
            return {"score": 0, "signal": "neutral"}

        # OI change over 7 days
        oi_now = float(data[-1]["sumOpenInterest"])
        oi_7d = float(data[-7]["sumOpenInterest"])
        oi_change = (oi_now - oi_7d) / oi_7d

        # Price change (use sumOpenInterestValue as proxy)
        val_now = float(data[-1]["sumOpenInterestValue"])
        val_7d = float(data[-7]["sumOpenInterestValue"])
        price_proxy_change = (val_now / oi_now) / (val_7d / oi_7d) - 1

        # Score based on OI-price regime
        if oi_change > 0.05 and price_proxy_change > 0:
            score = 0.5   # OI up + price up = strong trend
        elif oi_change > 0.05 and price_proxy_change < 0:
            score = -0.5  # OI up + price down = bearish buildup
        elif oi_change < -0.05 and price_proxy_change > 0:
            score = 0.2   # OI down + price up = weak rally (short covering)
        elif oi_change < -0.05 and price_proxy_change < 0:
            score = 0.3   # OI down + price down = capitulation (bottom watch)
        else:
            score = 0.0

        logger.info(
            f"Open Interest: OI_chg={oi_change:+.1%}, "
            f"price_proxy_chg={price_proxy_change:+.1%}, score={score:+.1f}"
        )

        return {
            "score": score,
            "oi_change_7d": round(oi_change, 4),
            "oi_current": oi_now,
            "signal": "bullish" if score > 0.2 else "bearish" if score < -0.2 else "neutral",
        }

    # ------------------------------------------------------------------
    # Factor 3: Long/Short Ratio (Contrarian)
    # ------------------------------------------------------------------
    def fetch_long_short_ratio(self) -> dict:
        """
        Retail vs top trader positioning.
        Retail usually wrong at extremes → contrarian signal.
        """
        # Global (retail) ratio
        retail = self._get("/futures/data/globalLongShortAccountRatio", {
            "symbol": self.symbol, "period": "1d", "limit": 7,
        })
        # Top traders ratio
        top = self._get("/futures/data/topLongShortPositionRatio", {
            "symbol": self.symbol, "period": "1d", "limit": 7,
        })

        if not retail:
            return {"score": 0, "signal": "neutral"}

        retail_ratio = float(retail[-1]["longShortRatio"])
        top_ratio = float(top[-1]["longShortRatio"]) if top else 1.0

        # Contrarian scoring on retail
        if retail_ratio > 2.0:
            score = -0.6  # retail heavily long → bearish
        elif retail_ratio > 1.5:
            score = -0.3  # retail leaning long → slightly bearish
        elif retail_ratio < 0.5:
            score = 0.6   # retail heavily short → bullish
        elif retail_ratio < 0.7:
            score = 0.3   # retail leaning short → slightly bullish
        else:
            score = 0.0

        # Bonus: if top traders disagree with retail → stronger signal
        if top:
            divergence = top_ratio - retail_ratio
            if abs(divergence) > 0.5:
                # Top traders are smarter; follow them
                score += 0.2 if top_ratio > retail_ratio else -0.2

        score = max(-1.0, min(1.0, score))

        logger.info(
            f"L/S Ratio: retail={retail_ratio:.2f}, "
            f"top={top_ratio:.2f}, score={score:+.1f}"
        )

        return {
            "score": round(score, 3),
            "retail_ratio": retail_ratio,
            "top_ratio": top_ratio,
            "signal": "bullish" if score > 0.2 else "bearish" if score < -0.2 else "neutral",
        }

    # ------------------------------------------------------------------
    # Factor 4: Taker Buy/Sell Volume Ratio
    # ------------------------------------------------------------------
    def fetch_taker_ratio(self) -> dict:
        """
        Who is aggressively executing? Takers hit the orderbook.
        Ratio > 1 = buyers aggressive. Ratio < 1 = sellers aggressive.
        Trend matters more than absolute.
        """
        data = self._get("/futures/data/takerlongshortRatio", {
            "symbol": self.symbol, "period": "1d", "limit": 7,
        })
        if not data:
            return {"score": 0, "signal": "neutral"}

        current = float(data[-1]["buySellRatio"])
        avg_7d = sum(float(d["buySellRatio"]) for d in data) / len(data)
        trend = current - avg_7d  # positive = buyers gaining, negative = sellers gaining

        # Scoring
        if current > 1.15:
            score = 0.5
        elif current > 1.05:
            score = 0.2
        elif current < 0.85:
            score = -0.5
        elif current < 0.95:
            score = -0.2
        else:
            score = 0.0

        # Add trend component
        score += max(-0.3, min(0.3, trend * 3))
        score = max(-1.0, min(1.0, score))

        logger.info(
            f"Taker Ratio: current={current:.3f}, "
            f"7d_avg={avg_7d:.3f}, trend={trend:+.3f}, score={score:+.1f}"
        )

        return {
            "score": round(score, 3),
            "ratio": current,
            "avg_7d": round(avg_7d, 3),
            "trend": round(trend, 4),
            "signal": "bullish" if score > 0.2 else "bearish" if score < -0.2 else "neutral",
        }

    # ------------------------------------------------------------------
    # Combined
    # ------------------------------------------------------------------
    def fetch_all(self) -> dict:
        """Fetch all 4 futures factors and combine."""
        now = time.time()
        if now - self._cache_ts < self._CACHE_TTL and self._cache:
            return self._cache

        funding = self.fetch_funding_rate()
        time.sleep(0.2)
        oi = self.fetch_open_interest()
        time.sleep(0.2)
        ls = self.fetch_long_short_ratio()
        time.sleep(0.2)
        taker = self.fetch_taker_ratio()

        # Weighted combination
        weights = {
            "funding": 0.35,  # strongest signal
            "oi": 0.25,
            "long_short": 0.25,
            "taker": 0.15,
        }

        combined = (
            funding["score"] * weights["funding"]
            + oi["score"] * weights["oi"]
            + ls["score"] * weights["long_short"]
            + taker["score"] * weights["taker"]
        )
        combined = max(-1.0, min(1.0, combined))

        result = {
            "combined_score": round(combined, 3),
            "signal": "bullish" if combined > 0.15 else "bearish" if combined < -0.15 else "neutral",
            "funding": funding,
            "open_interest": oi,
            "long_short": ls,
            "taker": taker,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._cache = result
        self._cache_ts = now

        logger.info(
            f"Futures Combined: {combined:+.2f} ({result['signal']}) | "
            f"FR={funding['score']:+.1f} OI={oi['score']:+.1f} "
            f"LS={ls['score']:+.1f} TK={taker['score']:+.1f}"
        )

        return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ff = FuturesFactors()
    result = ff.fetch_all()

    print(f"\n{'='*55}")
    print(f"  Binance Futures Factors — {result['signal'].upper()}")
    print(f"  Combined: {result['combined_score']:+.2f}")
    print(f"{'='*55}")
    print(f"  Funding Rate:  {result['funding']['score']:+.2f}  (rate={result['funding']['rate']:.6f})")
    print(f"  Open Interest: {result['open_interest']['score']:+.2f}  (OI 7d chg={result['open_interest'].get('oi_change_7d', 0):+.1%})")
    print(f"  Long/Short:    {result['long_short']['score']:+.2f}  (retail={result['long_short'].get('retail_ratio', 0):.2f})")
    print(f"  Taker Ratio:   {result['taker']['score']:+.2f}  (ratio={result['taker'].get('ratio', 0):.3f})")
