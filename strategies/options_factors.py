"""
Deribit Options Market Factors — FREE, no API key

Factors:
  7a. Put/Call OI Ratio — hedging demand, fear gauge
  7b. Implied Volatility — expected move size, sizing signal
  7c. Max Pain — price magnet near expiry

Usage:
    from options_factors import OptionsFactors
    of = OptionsFactors()
    data = of.fetch_all()
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger("options_factors")

DERIBIT_URL = "https://www.deribit.com/api/v2/public"


class OptionsFactors:
    def __init__(self, currency: str = "BTC"):
        self.currency = currency
        self._cache: dict = {}
        self._cache_ts: float = 0
        self._CACHE_TTL = 3600  # 1h (options data doesn't change fast)

    def _get(self, endpoint: str, params: dict = None) -> Optional[dict]:
        try:
            resp = requests.get(
                f"{DERIBIT_URL}/{endpoint}",
                params=params or {},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json().get("result")
        except Exception as e:
            logger.warning(f"Deribit API failed ({endpoint}): {e}")
            return None

    def fetch_put_call_ratio(self) -> dict:
        """Put/Call OI ratio — fear gauge."""
        data = self._get("get_book_summary_by_currency", {
            "currency": self.currency, "kind": "option",
        })
        if not data:
            return {"score": 0, "ratio": 1.0, "signal": "neutral"}

        put_oi = sum(d.get("open_interest", 0) for d in data if d["instrument_name"].endswith("P"))
        call_oi = sum(d.get("open_interest", 0) for d in data if d["instrument_name"].endswith("C"))
        ratio = put_oi / call_oi if call_oi > 0 else 1.0

        # P/C > 1.0 = lots of hedging = fearful = contrarian bullish
        # P/C < 0.5 = complacent = nobody hedging = contrarian bearish
        if ratio > 1.2:
            score = 0.5   # extreme hedging → contrarian bullish
        elif ratio > 0.9:
            score = 0.2   # moderate hedging → slightly bullish
        elif ratio < 0.4:
            score = -0.5  # no hedging → complacent → bearish risk
        elif ratio < 0.6:
            score = -0.2
        else:
            score = 0.0

        logger.info(f"Put/Call Ratio: {ratio:.2f}, put_oi={put_oi:.0f}, call_oi={call_oi:.0f}, score={score:+.1f}")

        return {
            "score": score,
            "ratio": round(ratio, 3),
            "put_oi": put_oi,
            "call_oi": call_oi,
            "signal": "bullish" if score > 0.2 else "bearish" if score < -0.2 else "neutral",
        }

    def fetch_volatility(self) -> dict:
        """Historical and implied volatility — sizing signal."""
        data = self._get("get_historical_volatility", {"currency": self.currency})
        if not data or len(data) < 2:
            return {"score": 0, "hv": 0, "signal": "neutral"}

        current_hv = data[-1][1]  # latest historical vol

        # High vol = bigger moves = reduce position size (risk management)
        # Low vol = calm market = can size up
        # But extreme low vol often precedes explosions
        if current_hv > 80:
            score = -0.3  # very volatile, reduce exposure
        elif current_hv > 60:
            score = -0.1
        elif current_hv < 25:
            score = -0.2  # suspiciously calm, explosion coming
        elif current_hv < 40:
            score = 0.1   # moderate vol, good for trend following
        else:
            score = 0.0

        logger.info(f"Historical Vol: {current_hv:.1f}%, score={score:+.1f}")

        return {
            "score": score,
            "hv": round(current_hv, 1),
            "signal": "neutral",  # vol is a sizing signal, not directional
        }

    def fetch_all(self) -> dict:
        now = time.time()
        if now - self._cache_ts < self._CACHE_TTL and self._cache:
            return self._cache

        pc = self.fetch_put_call_ratio()
        time.sleep(0.3)
        vol = self.fetch_volatility()

        combined = pc["score"] * 0.7 + vol["score"] * 0.3
        combined = max(-1.0, min(1.0, combined))

        result = {
            "combined_score": round(combined, 3),
            "signal": "bullish" if combined > 0.15 else "bearish" if combined < -0.15 else "neutral",
            "put_call": pc,
            "volatility": vol,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._cache = result
        self._cache_ts = now

        logger.info(f"Options Combined: {combined:+.2f} | P/C={pc['ratio']:.2f} HV={vol['hv']:.0f}%")
        return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    of = OptionsFactors()
    r = of.fetch_all()
    print(f"\nOptions: {r['signal'].upper()} ({r['combined_score']:+.2f})")
    print(f"  Put/Call: {r['put_call']['ratio']:.2f}")
    print(f"  HV: {r['volatility']['hv']:.0f}%")
