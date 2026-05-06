"""
Santiment On-Chain + Social Factors (Factor 16, upgraded from optional to active)

Metrics available on free tier (1-year lookback, up to ~1 month ago):
  - social_volume_total: social media mentions (FOMO detector)
  - dev_activity: GitHub commits (fundamental health)
  - daily_active_addresses: network usage
  - exchange_inflow/outflow: accumulation vs distribution
  - mvrv_usd: Market Value to Realized Value (overvalued/undervalued)

Requires: SANTIMENT_API_KEY env var
"""

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

logger = logging.getLogger("santiment")

SANTIMENT_API_KEY = os.environ.get("SANTIMENT_API_KEY", "")
GRAPHQL_URL = "https://api.santiment.net/graphql"


class SantimentFactors:
    def __init__(self, api_key: str = SANTIMENT_API_KEY):
        self.api_key = api_key
        self._cache = {}
        self._cache_ts = 0
        self._CACHE_TTL = 3600

    def _query(self, metric: str, slug: str = "bitcoin", days_back: int = 30) -> Optional[list]:
        if not self.api_key:
            return None

        # Free tier: can only query up to ~1 month ago
        to_dt = datetime.now(timezone.utc) - timedelta(days=30)
        from_dt = to_dt - timedelta(days=days_back)

        query = """
        {
          getMetric(metric: "%s") {
            timeseriesData(
              slug: "%s"
              from: "%s"
              to: "%s"
              interval: "1d"
            ) { datetime value }
          }
        }
        """ % (metric, slug, from_dt.strftime("%Y-%m-%dT00:00:00Z"), to_dt.strftime("%Y-%m-%dT00:00:00Z"))

        try:
            resp = requests.post(
                GRAPHQL_URL,
                headers={"Authorization": f"Apikey {self.api_key}"},
                json={"query": query},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", {}).get("getMetric", {}).get("timeseriesData")
        except Exception as e:
            logger.warning(f"Santiment {metric} failed: {e}")
            return None

    def fetch_exchange_flows(self) -> dict:
        """BTC exchange inflow vs outflow — the real accumulation signal."""
        inflow = self._query("exchange_inflow", days_back=14)
        time.sleep(0.3)
        outflow = self._query("exchange_outflow", days_back=14)

        if not inflow or not outflow:
            return {"score": 0, "signal": "neutral"}

        avg_in = sum(d["value"] for d in inflow[-7:]) / 7
        avg_out = sum(d["value"] for d in outflow[-7:]) / 7

        # Net flow: negative = outflow dominant = accumulation = bullish
        net_ratio = (avg_in - avg_out) / max(avg_in, 1)

        if net_ratio < -0.1:
            score = 0.5   # strong outflow = accumulation
        elif net_ratio < -0.03:
            score = 0.2
        elif net_ratio > 0.1:
            score = -0.5  # strong inflow = selling pressure
        elif net_ratio > 0.03:
            score = -0.2
        else:
            score = 0.0

        logger.info(f"Exchange Flows: in={avg_in:.0f}, out={avg_out:.0f}, net_ratio={net_ratio:+.2f}, score={score:+.1f}")

        return {
            "score": score,
            "avg_inflow": round(avg_in),
            "avg_outflow": round(avg_out),
            "net_ratio": round(net_ratio, 3),
            "signal": "bullish" if score > 0.2 else "bearish" if score < -0.2 else "neutral",
        }

    def fetch_social_volume(self) -> dict:
        """Social media mention volume — contrarian FOMO detector."""
        data = self._query("social_volume_total", days_back=30)
        if not data or len(data) < 14:
            return {"score": 0, "signal": "neutral"}

        recent_avg = sum(d["value"] for d in data[-7:]) / 7
        older_avg = sum(d["value"] for d in data[-14:-7]) / 7

        # Rising social volume = retail attention = contrarian caution
        if older_avg == 0:
            change = 0
        else:
            change = (recent_avg - older_avg) / older_avg

        if change > 0.5:
            score = -0.3  # social volume exploding = FOMO = contrarian bearish
        elif change > 0.2:
            score = -0.1
        elif change < -0.3:
            score = 0.2   # social volume dying = apathy = contrarian bullish
        else:
            score = 0.0

        logger.info(f"Social Volume: recent={recent_avg:.0f}, change={change:+.0%}, score={score:+.1f}")

        return {
            "score": score,
            "recent_avg": round(recent_avg),
            "change_pct": round(change * 100, 1),
            "signal": "bullish" if score > 0.1 else "bearish" if score < -0.1 else "neutral",
        }

    def fetch_dev_activity(self) -> dict:
        """Developer activity — fundamental health signal."""
        data = self._query("dev_activity", days_back=30)
        if not data or len(data) < 14:
            return {"score": 0, "signal": "neutral"}

        recent_avg = sum(d["value"] for d in data[-7:]) / 7
        older_avg = sum(d["value"] for d in data[-14:-7]) / 7

        if older_avg == 0:
            change = 0
        else:
            change = (recent_avg - older_avg) / older_avg

        # Rising dev activity = builders building = long-term bullish
        if change > 0.2:
            score = 0.2
        elif change < -0.3:
            score = -0.1  # declining activity is mildly negative
        else:
            score = 0.0

        logger.info(f"Dev Activity: recent={recent_avg:.0f}, change={change:+.0%}, score={score:+.1f}")

        return {
            "score": score,
            "recent_avg": round(recent_avg),
            "change_pct": round(change * 100, 1),
            "signal": "bullish" if score > 0 else "neutral",
        }

    def fetch_all(self) -> dict:
        now = time.time()
        if now - self._cache_ts < self._CACHE_TTL and self._cache:
            return self._cache

        if not self.api_key:
            logger.debug("SANTIMENT_API_KEY not set")
            return {"combined_score": 0, "signal": "neutral", "source": "santiment"}

        flows = self.fetch_exchange_flows()
        time.sleep(0.5)
        social = self.fetch_social_volume()
        time.sleep(0.5)
        dev = self.fetch_dev_activity()

        # Exchange flows are the strongest signal
        combined = flows["score"] * 0.50 + social["score"] * 0.30 + dev["score"] * 0.20
        combined = max(-1.0, min(1.0, combined))

        result = {
            "combined_score": round(combined, 3),
            "signal": "bullish" if combined > 0.15 else "bearish" if combined < -0.15 else "neutral",
            "exchange_flows": flows,
            "social_volume": social,
            "dev_activity": dev,
            "source": "santiment",
        }

        self._cache = result
        self._cache_ts = now

        logger.info(
            f"Santiment Combined: {combined:+.2f} | "
            f"Flows={flows['score']:+.1f} Social={social['score']:+.1f} Dev={dev['score']:+.1f}"
        )

        return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sf = SantimentFactors()
    r = sf.fetch_all()
    print(f"\nSantiment: {r['signal'].upper()} ({r['combined_score']:+.2f})")
    if "exchange_flows" in r:
        ef = r["exchange_flows"]
        print(f"  Exchange: in={ef.get('avg_inflow',0)} out={ef.get('avg_outflow',0)} ({ef['signal']})")
    if "social_volume" in r:
        print(f"  Social: {r['social_volume'].get('recent_avg',0)} mentions ({r['social_volume']['signal']})")
    if "dev_activity" in r:
        print(f"  Dev: {r['dev_activity'].get('recent_avg',0)} commits ({r['dev_activity']['signal']})")
