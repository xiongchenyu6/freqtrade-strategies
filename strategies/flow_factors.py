"""
Capital Flow Factors — Stablecoin Supply + ETF Flows

Factor 5: Stablecoin mint/burn (DefiLlama, free)
Factor 6: BTC ETF flows (news-based, via LLM extraction)

Both track money entering/leaving the crypto ecosystem.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger("flow_factors")


class StablecoinFactor:
    """Track USDT/USDC supply changes — new money entering crypto."""

    STABLECOINS = {
        1: "USDT",
        2: "USDC",
    }

    def __init__(self):
        self._cache = {}
        self._cache_ts = 0

    def fetch(self) -> dict:
        now = time.time()
        if now - self._cache_ts < 3600 and self._cache:
            return self._cache

        total_change = 0
        details = {}

        for sid, name in self.STABLECOINS.items():
            try:
                resp = requests.get(
                    f"https://stablecoins.llama.fi/stablecoincharts/all?stablecoin={sid}",
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()

                if len(data) < 8:
                    continue

                current = data[-1]["totalCirculating"]["peggedUSD"]
                week_ago = data[-7]["totalCirculating"]["peggedUSD"]
                month_ago = data[-30]["totalCirculating"]["peggedUSD"] if len(data) > 30 else week_ago

                week_chg = (current - week_ago) / week_ago * 100
                month_chg = (current - month_ago) / month_ago * 100

                details[name] = {
                    "supply_b": round(current / 1e9, 1),
                    "week_change_pct": round(week_chg, 2),
                    "month_change_pct": round(month_chg, 2),
                }
                total_change += week_chg

                time.sleep(0.3)
            except Exception as e:
                logger.warning(f"Stablecoin {name} failed: {e}")

        # Score: supply growing = money coming in = bullish
        avg_change = total_change / len(self.STABLECOINS) if self.STABLECOINS else 0

        if avg_change > 1.0:
            score = 0.5
        elif avg_change > 0.3:
            score = 0.2
        elif avg_change < -1.0:
            score = -0.5
        elif avg_change < -0.3:
            score = -0.2
        else:
            score = 0.0

        logger.info(f"Stablecoins: avg_week_chg={avg_change:+.2f}%, score={score:+.1f}")

        result = {
            "score": round(score, 3),
            "signal": "bullish" if score > 0.15 else "bearish" if score < -0.15 else "neutral",
            "avg_week_change_pct": round(avg_change, 2),
            "details": details,
        }
        self._cache = result
        self._cache_ts = now
        return result


class ETFFlowFactor:
    """
    Track BTC ETF flows via news headlines.
    Uses Google News RSS to detect inflow/outflow patterns.
    """

    def fetch(self) -> dict:
        try:
            from xml.etree import ElementTree
            resp = requests.get(
                "https://news.google.com/rss/search?q=bitcoin+etf+inflow+OR+outflow&hl=en-US&gl=US&ceid=US:en",
                timeout=15,
                headers={"User-Agent": "CryptoBot/1.0"},
            )
            if resp.status_code != 200:
                return {"score": 0, "signal": "neutral", "headlines": []}

            root = ElementTree.fromstring(resp.content)
            headlines = []
            for item in root.findall(".//item")[:15]:
                t = item.find("title")
                if t is not None and t.text:
                    headlines.append(t.text.strip())

            # Keyword analysis
            inflow_kw = ["inflow", "inflows", "bought", "buying", "accumulate", "record", "billion"]
            outflow_kw = ["outflow", "outflows", "sold", "selling", "redeem", "withdraw"]

            inflow_count = sum(1 for h in headlines for k in inflow_kw if k in h.lower())
            outflow_count = sum(1 for h in headlines for k in outflow_kw if k in h.lower())

            total = inflow_count + outflow_count
            if total > 0:
                score = (inflow_count - outflow_count) / total
            else:
                score = 0.0

            score = max(-1.0, min(1.0, score * 0.7))  # dampen

            logger.info(
                f"ETF Flow: inflow_mentions={inflow_count}, outflow={outflow_count}, "
                f"score={score:+.2f}, headlines={len(headlines)}"
            )

            return {
                "score": round(score, 3),
                "signal": "bullish" if score > 0.15 else "bearish" if score < -0.15 else "neutral",
                "inflow_mentions": inflow_count,
                "outflow_mentions": outflow_count,
                "headline_count": len(headlines),
            }
        except Exception as e:
            logger.warning(f"ETF flow fetch failed: {e}")
            return {"score": 0, "signal": "neutral"}


def fetch_all_flows() -> dict:
    """Fetch stablecoin + ETF flow factors."""
    stable = StablecoinFactor().fetch()
    time.sleep(0.5)
    etf = ETFFlowFactor().fetch()

    combined = stable["score"] * 0.5 + etf["score"] * 0.5
    combined = max(-1.0, min(1.0, combined))

    logger.info(f"Flows Combined: {combined:+.2f} | Stables={stable['score']:+.1f} ETF={etf['score']:+.1f}")

    return {
        "combined_score": round(combined, 3),
        "signal": "bullish" if combined > 0.15 else "bearish" if combined < -0.15 else "neutral",
        "stablecoin": stable,
        "etf": etf,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    r = fetch_all_flows()
    print(f"\nFlows: {r['signal'].upper()} ({r['combined_score']:+.2f})")
    for name, d in r["stablecoin"].get("details", {}).items():
        print(f"  {name}: ${d['supply_b']}B (week {d['week_change_pct']:+.1f}%)")
    print(f"  ETF: inflow={r['etf'].get('inflow_mentions',0)} outflow={r['etf'].get('outflow_mentions',0)}")
