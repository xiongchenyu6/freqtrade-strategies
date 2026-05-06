"""
External Data Sources for Crypto Sentiment — ALL FREE, NO API KEY NEEDED

Sources:
1. CoinGecko      — BTC dominance, market cap trend, community data
2. DefiLlama      — DeFi TVL trend (risk-on/off gauge)
3. Mempool.space   — Bitcoin mempool/fees (network demand)
4. Blockchain.com  — Hash rate, transaction volume (network health)
5. Google Trends   — "bitcoin" search interest (retail FOMO detector)

Each source returns:
    {"score": float, "signal": str, "data": dict, "source": str}
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger("external_sources")


# ---------------------------------------------------------------------------
# 1. CoinGecko — Market Structure + Social
# ---------------------------------------------------------------------------
class CoinGeckoSource:
    """
    Free, no key needed. 30 calls/min.
    Signals:
      - BTC dominance rising = risk-off (bearish alts)
      - BTC 24h change direction
      - Market cap trend
    """

    def fetch(self) -> dict:
        try:
            # Global market data
            resp = requests.get(
                "https://api.coingecko.com/api/v3/global",
                timeout=15,
            )
            resp.raise_for_status()
            g = resp.json()["data"]

            btc_dom = g["market_cap_percentage"]["btc"]
            mcap_change_24h = g.get("market_cap_change_percentage_24h_usd", 0)

            # BTC specific
            time.sleep(1)  # rate limit
            resp2 = requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={
                    "ids": "bitcoin",
                    "vs_currencies": "usd",
                    "include_24hr_change": "true",
                    "include_market_cap": "true",
                },
                timeout=15,
            )
            resp2.raise_for_status()
            btc = resp2.json()["bitcoin"]
            btc_change = btc.get("usd_24h_change", 0)

            # Score: based on market momentum
            score = 0.0
            if mcap_change_24h > 3:
                score += 0.4
            elif mcap_change_24h > 1:
                score += 0.2
            elif mcap_change_24h < -3:
                score -= 0.4
            elif mcap_change_24h < -1:
                score -= 0.2

            if btc_change > 5:
                score += 0.3
            elif btc_change < -5:
                score -= 0.3

            score = max(-1.0, min(1.0, score))

            logger.info(
                f"CoinGecko: BTC={btc.get('usd',0):.0f}, "
                f"24h={btc_change:.1f}%, dom={btc_dom:.1f}%, "
                f"mcap_chg={mcap_change_24h:.1f}%"
            )

            return {
                "score": round(score, 3),
                "signal": "bullish" if score > 0.2 else "bearish" if score < -0.2 else "neutral",
                "data": {
                    "btc_price": btc.get("usd", 0),
                    "btc_24h_change": round(btc_change, 2),
                    "btc_dominance": round(btc_dom, 1),
                    "total_mcap_change_24h": round(mcap_change_24h, 2),
                },
                "source": "coingecko",
            }
        except Exception as e:
            logger.warning(f"CoinGecko failed: {e}")
            return {"score": 0, "signal": "neutral", "data": {}, "source": "coingecko"}


# ---------------------------------------------------------------------------
# 2. DefiLlama — DeFi TVL Trend
# ---------------------------------------------------------------------------
class DefiLlamaSource:
    """
    Completely free, no key, no rate limit.
    DeFi TVL rising = risk-on (bullish), falling = risk-off (bearish).
    Stablecoin market cap is a liquidity indicator.
    """

    def fetch(self) -> dict:
        try:
            # Current + historical TVL
            resp = requests.get("https://api.llama.fi/v2/historicalChainTvl", timeout=15)
            resp.raise_for_status()
            tvl_data = resp.json()

            if len(tvl_data) < 8:
                return {"score": 0, "signal": "neutral", "data": {}, "source": "defillama"}

            current_tvl = tvl_data[-1]["tvl"]
            week_ago_tvl = tvl_data[-8]["tvl"]
            month_ago_tvl = tvl_data[-31]["tvl"] if len(tvl_data) > 31 else week_ago_tvl

            week_change = (current_tvl - week_ago_tvl) / week_ago_tvl * 100
            month_change = (current_tvl - month_ago_tvl) / month_ago_tvl * 100

            # Stablecoin market cap
            time.sleep(0.5)
            resp2 = requests.get("https://stablecoins.llama.fi/stablecoins?includePrices=false", timeout=15)
            resp2.raise_for_status()
            stables = resp2.json()
            total_stable_mcap = sum(
                s.get("circulating", {}).get("peggedUSD", 0)
                for s in stables.get("peggedAssets", [])
            )

            # Score
            score = 0.0
            if week_change > 5:
                score += 0.4
            elif week_change > 2:
                score += 0.2
            elif week_change < -5:
                score -= 0.4
            elif week_change < -2:
                score -= 0.2

            if month_change > 10:
                score += 0.3
            elif month_change < -10:
                score -= 0.3

            score = max(-1.0, min(1.0, score))

            logger.info(
                f"DefiLlama: TVL={current_tvl/1e9:.1f}B, "
                f"week={week_change:+.1f}%, month={month_change:+.1f}%, "
                f"stables={total_stable_mcap/1e9:.1f}B"
            )

            return {
                "score": round(score, 3),
                "signal": "bullish" if score > 0.2 else "bearish" if score < -0.2 else "neutral",
                "data": {
                    "tvl_billion": round(current_tvl / 1e9, 1),
                    "tvl_week_change_pct": round(week_change, 1),
                    "tvl_month_change_pct": round(month_change, 1),
                    "stablecoin_mcap_billion": round(total_stable_mcap / 1e9, 1),
                },
                "source": "defillama",
            }
        except Exception as e:
            logger.warning(f"DefiLlama failed: {e}")
            return {"score": 0, "signal": "neutral", "data": {}, "source": "defillama"}


# ---------------------------------------------------------------------------
# 3. Mempool.space — Bitcoin Network Demand
# ---------------------------------------------------------------------------
class MempoolSource:
    """
    Completely free, no key.
    High fees = high demand = bullish network activity.
    Low fees = quiet network.
    Also: difficulty adjustment trend.
    """

    def fetch(self) -> dict:
        try:
            # Recommended fees
            resp = requests.get("https://mempool.space/api/v1/fees/recommended", timeout=10)
            resp.raise_for_status()
            fees = resp.json()

            # Hashrate (difficulty adjustment)
            time.sleep(0.5)
            resp2 = requests.get("https://mempool.space/api/v1/mining/hashrate/1m", timeout=10)
            resp2.raise_for_status()
            hr_data = resp2.json()

            current_hr = hr_data.get("currentHashrate", 0)
            difficulty = hr_data.get("currentDifficulty", 0)

            # Hashrate history for trend
            hashrates = hr_data.get("hashrates", [])
            if len(hashrates) >= 2:
                recent_hr = hashrates[-1].get("avgHashrate", 0)
                older_hr = hashrates[0].get("avgHashrate", 1)
                hr_trend = (recent_hr - older_hr) / older_hr * 100
            else:
                hr_trend = 0

            fastest_fee = fees.get("fastestFee", 1)

            # Score: high fees + rising hashrate = healthy network
            score = 0.0
            if fastest_fee > 50:
                score += 0.3  # very high demand
            elif fastest_fee > 20:
                score += 0.15
            # Low fees aren't necessarily bearish, just quiet

            if hr_trend > 5:
                score += 0.2  # miners bullish
            elif hr_trend < -5:
                score -= 0.2  # miners capitulating

            score = max(-1.0, min(1.0, score))

            logger.info(
                f"Mempool: fee={fastest_fee} sat/vB, "
                f"hashrate_trend={hr_trend:+.1f}%"
            )

            return {
                "score": round(score, 3),
                "signal": "bullish" if score > 0.2 else "bearish" if score < -0.2 else "neutral",
                "data": {
                    "fastest_fee_sat": fastest_fee,
                    "hashrate_trend_pct": round(hr_trend, 1),
                    "difficulty": difficulty,
                },
                "source": "mempool",
            }
        except Exception as e:
            logger.warning(f"Mempool failed: {e}")
            return {"score": 0, "signal": "neutral", "data": {}, "source": "mempool"}


# ---------------------------------------------------------------------------
# 4. Google Trends — Retail Interest
# ---------------------------------------------------------------------------
class GoogleTrendsSource:
    """
    Uses Google Trends via unofficial API.
    "bitcoin" search interest spike = retail FOMO (contrarian bearish at peaks).
    Search interest bottom = retail apathy (contrarian bullish).
    """

    def fetch(self) -> dict:
        try:
            # Use SerpAPI-like free endpoint or pytrends
            # Fallback: CoinGecko search trending as proxy
            resp = requests.get(
                "https://api.coingecko.com/api/v3/search/trending",
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            coins = data.get("coins", [])
            # If BTC is trending on CoinGecko = high retail interest
            btc_trending = any(
                c.get("item", {}).get("symbol", "").upper() == "BTC"
                for c in coins
            )

            # Check if mostly memecoins trending (FOMO indicator)
            meme_keywords = ["doge", "pepe", "shib", "meme", "inu", "moon", "elon", "baby"]
            meme_count = sum(
                1 for c in coins
                if any(kw in c.get("item", {}).get("name", "").lower() for kw in meme_keywords)
            )
            meme_ratio = meme_count / len(coins) if coins else 0

            trending_symbols = [c.get("item", {}).get("symbol", "") for c in coins[:10]]

            # High meme ratio = euphoria (contrarian bearish)
            # BTC trending = mainstream attention
            score = 0.0
            if meme_ratio > 0.5:
                score -= 0.3  # too much meme speculation
            elif meme_ratio > 0.3:
                score -= 0.1

            if btc_trending:
                score += 0.1  # some mainstream interest is fine

            score = max(-1.0, min(1.0, score))

            logger.info(
                f"Trends: {len(coins)} trending, "
                f"meme_ratio={meme_ratio:.0%}, "
                f"symbols={trending_symbols[:5]}"
            )

            return {
                "score": round(score, 3),
                "signal": "bullish" if score > 0.2 else "bearish" if score < -0.2 else "neutral",
                "data": {
                    "trending_coins": trending_symbols,
                    "meme_ratio": round(meme_ratio, 2),
                    "btc_trending": btc_trending,
                    "trending_count": len(coins),
                },
                "source": "trends",
            }
        except Exception as e:
            logger.warning(f"Trends failed: {e}")
            return {"score": 0, "signal": "neutral", "data": {}, "source": "trends"}


# ---------------------------------------------------------------------------
# Unified fetcher
# ---------------------------------------------------------------------------
def fetch_all_external() -> dict:
    """Fetch all free external sources. No API keys needed."""
    results = {}
    scores = []

    sources = [
        ("coingecko", CoinGeckoSource, 0.35),   # market structure, most reliable
        ("defillama", DefiLlamaSource, 0.25),    # DeFi risk-on/off
        ("mempool", MempoolSource, 0.20),        # Bitcoin network health
        ("trends", GoogleTrendsSource, 0.20),    # retail sentiment
    ]

    for name, cls, weight in sources:
        try:
            source = cls()
            result = source.fetch()
            results[name] = result
            scores.append((result["score"], weight))
            time.sleep(0.5)  # be polite between sources
        except Exception as e:
            logger.warning(f"{name} failed: {e}")
            results[name] = {"score": 0, "signal": "neutral", "data": {}, "source": name}

    # Weighted average
    if scores:
        total_weight = sum(w for _, w in scores)
        combined = sum(s * w for s, w in scores) / total_weight
    else:
        combined = 0.0

    combined = max(-1.0, min(1.0, combined))

    return {
        "combined_score": round(combined, 3),
        "signal": "bullish" if combined > 0.2 else "bearish" if combined < -0.2 else "neutral",
        "sources": results,
        "active_sources": len([s for s, _ in scores if s != 0]),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = fetch_all_external()

    print(f"\n{'='*55}")
    print(f"  External Sources — Combined: {result['combined_score']:+.2f} ({result['signal']})")
    print(f"  Active sources: {result['active_sources']}/4")
    print(f"{'='*55}")

    for name, data in result["sources"].items():
        print(f"\n  [{name:12s}] score={data['score']:+.2f}  {data['signal']}")
        for k, v in data.get("data", {}).items():
            if not isinstance(v, (list, dict)):
                print(f"    {k}: {v}")
