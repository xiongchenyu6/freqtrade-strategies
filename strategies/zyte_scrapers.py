"""
Zyte-Powered Data Scrapers for Crypto Sentiment

Uses Zyte API to scrape sources that RSS can't reach:
1. Reddit r/bitcoin, r/cryptocurrency — retail sentiment
2. CoinGecko trending coins — momentum/hype detection
3. Whale Alert — large BTC/ETH transfers
4. Crypto Twitter/X — KOL sentiment (via nitter or search)

Requires: ZYTE_API_KEY environment variable
Docs: https://docs.zyte.com/zyte-api/get-started.html

Usage:
    scraper = ZyteCryptoScraper(api_key="your_key")
    reddit_data = scraper.scrape_reddit()
    trending = scraper.scrape_coingecko_trending()
    whales = scraper.scrape_whale_transactions()
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger("zyte_scrapers")


class ZyteCryptoScraper:
    """Scrape crypto sentiment data via Zyte API."""

    ZYTE_API_URL = "https://api.zyte.com/v1/extract"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ZYTE_API_KEY", "")
        if not self.api_key:
            logger.warning("No ZYTE_API_KEY set. Scrapers will be disabled.")

    def _zyte_request(self, url: str, use_browser: bool = False) -> Optional[str]:
        """Make a request through Zyte API."""
        if not self.api_key:
            return None

        payload = {
            "url": url,
            "httpResponseBody": True,
        }
        if use_browser:
            payload["browserHtml"] = True
            del payload["httpResponseBody"]

        try:
            resp = requests.post(
                self.ZYTE_API_URL,
                auth=(self.api_key, ""),
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()

            if use_browser:
                return data.get("browserHtml", "")
            else:
                import base64
                body = data.get("httpResponseBody", "")
                return base64.b64decode(body).decode("utf-8", errors="replace")

        except Exception as e:
            logger.warning(f"Zyte request failed for {url}: {e}")
            return None

    # ------------------------------------------------------------------
    # Reddit Scraper
    # ------------------------------------------------------------------
    def scrape_reddit(self, subreddits: list[str] = None) -> dict:
        """
        Scrape Reddit crypto subreddits for sentiment.
        Uses old.reddit.com (lighter, easier to parse).

        Returns:
            {
                "posts": [{"title": ..., "score": ..., "comments": ...}],
                "sentiment_score": float,  # -1 to 1
                "hot_topics": [str],
            }
        """
        if subreddits is None:
            subreddits = ["bitcoin", "cryptocurrency"]

        all_posts = []
        for sub in subreddits:
            # Use Reddit's JSON API (no auth needed, rate limited)
            url = f"https://www.reddit.com/r/{sub}/hot.json?limit=25"
            html = self._zyte_request(url)
            if not html:
                continue

            try:
                data = json.loads(html)
                for post in data.get("data", {}).get("children", []):
                    pd = post.get("data", {})
                    all_posts.append({
                        "title": pd.get("title", ""),
                        "score": pd.get("score", 0),
                        "comments": pd.get("num_comments", 0),
                        "subreddit": sub,
                        "upvote_ratio": pd.get("upvote_ratio", 0.5),
                        "created_utc": pd.get("created_utc", 0),
                    })
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to parse r/{sub}: {e}")

        if not all_posts:
            return {"posts": [], "sentiment_score": 0.0, "hot_topics": []}

        # Simple sentiment: keyword analysis on titles
        bull_count = 0
        bear_count = 0
        BULL = ["bullish", "moon", "buy", "pump", "green", "rally", "ath", "adoption", "accumulate"]
        BEAR = ["bearish", "crash", "dump", "sell", "red", "scam", "fear", "ban", "hack"]

        for p in all_posts:
            t = p["title"].lower()
            bull_count += sum(1 for kw in BULL if kw in t)
            bear_count += sum(1 for kw in BEAR if kw in t)

        total = bull_count + bear_count
        sentiment = (bull_count - bear_count) / total if total > 0 else 0.0

        # Hot topics: most upvoted post titles
        sorted_posts = sorted(all_posts, key=lambda x: x["score"], reverse=True)
        hot_topics = [p["title"][:100] for p in sorted_posts[:5]]

        logger.info(f"Reddit: {len(all_posts)} posts, sentiment={sentiment:.2f}")
        return {
            "posts": all_posts,
            "sentiment_score": sentiment,
            "hot_topics": hot_topics,
        }

    # ------------------------------------------------------------------
    # CoinGecko Trending
    # ------------------------------------------------------------------
    def scrape_coingecko_trending(self) -> dict:
        """
        Scrape CoinGecko trending coins.
        Useful for detecting hype cycles and momentum shifts.

        Returns:
            {
                "trending_coins": [{"name": ..., "symbol": ..., "market_cap_rank": ...}],
                "categories_trending": [str],
            }
        """
        # CoinGecko has a free API for trending
        url = "https://api.coingecko.com/api/v3/search/trending"
        html = self._zyte_request(url)
        if not html:
            # Fallback: direct request (CoinGecko free API)
            try:
                resp = requests.get(url, timeout=10)
                resp.raise_for_status()
                html = resp.text
            except Exception:
                return {"trending_coins": [], "categories_trending": []}

        try:
            data = json.loads(html)
            coins = []
            for item in data.get("coins", []):
                coin = item.get("item", {})
                coins.append({
                    "name": coin.get("name", ""),
                    "symbol": coin.get("symbol", ""),
                    "market_cap_rank": coin.get("market_cap_rank", 0),
                    "price_change_24h": coin.get("data", {}).get(
                        "price_change_percentage_24h", {}
                    ).get("usd", 0),
                })

            categories = [
                cat.get("name", "")
                for cat in data.get("categories", [])[:5]
            ]

            logger.info(f"CoinGecko trending: {len(coins)} coins")
            return {
                "trending_coins": coins,
                "categories_trending": categories,
            }
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse CoinGecko trending: {e}")
            return {"trending_coins": [], "categories_trending": []}

    # ------------------------------------------------------------------
    # Whale Alert (large transactions)
    # ------------------------------------------------------------------
    def scrape_whale_transactions(self) -> dict:
        """
        Scrape recent whale transactions from whale-alert.io.
        Large exchange inflows = potential sell pressure.
        Large exchange outflows = accumulation signal.

        Returns:
            {
                "transactions": [{"amount": ..., "from": ..., "to": ..., "coin": ...}],
                "net_exchange_flow": str,  # "inflow" or "outflow"
                "signal": str,
            }
        """
        url = "https://whale-alert.io/"
        html = self._zyte_request(url, use_browser=True)
        if not html:
            return {"transactions": [], "net_exchange_flow": "unknown", "signal": "neutral"}

        # Parse whale transactions from HTML
        transactions = []
        exchange_in = 0
        exchange_out = 0

        # Look for transaction patterns in the HTML
        # Whale Alert shows: "X BTC transferred from Exchange to Unknown"
        import re
        tx_patterns = re.findall(
            r'(\d[\d,.]+)\s*(BTC|ETH|USDT|USDC)\s*.*?(from|to)\s*(unknown|exchange)',
            html.lower(),
        )

        for amount_str, coin, direction, entity in tx_patterns[:20]:
            try:
                amount = float(amount_str.replace(",", ""))
            except ValueError:
                continue

            if coin in ("btc", "eth"):
                if direction == "to" and entity == "exchange":
                    exchange_in += amount
                elif direction == "from" and entity == "exchange":
                    exchange_out += amount

                transactions.append({
                    "amount": amount,
                    "coin": coin.upper(),
                    "direction": f"{direction} {entity}",
                })

        if exchange_in > exchange_out * 1.5:
            flow = "inflow"
            signal = "bearish"  # coins moving to exchange = potential selling
        elif exchange_out > exchange_in * 1.5:
            flow = "outflow"
            signal = "bullish"  # coins leaving exchange = accumulation
        else:
            flow = "balanced"
            signal = "neutral"

        logger.info(f"Whale Alert: {len(transactions)} txs, flow={flow}")
        return {
            "transactions": transactions,
            "net_exchange_flow": flow,
            "signal": signal,
        }

    # ------------------------------------------------------------------
    # Aggregate all sources
    # ------------------------------------------------------------------
    def scrape_all(self) -> dict:
        """Run all scrapers and return combined result."""
        reddit = self.scrape_reddit()
        trending = self.scrape_coingecko_trending()
        whales = self.scrape_whale_transactions()

        # Combine signals
        signals = []
        if reddit["sentiment_score"] != 0:
            signals.append(("reddit", reddit["sentiment_score"]))
        if whales["signal"] == "bullish":
            signals.append(("whales", 0.5))
        elif whales["signal"] == "bearish":
            signals.append(("whales", -0.5))

        combined = sum(s[1] for s in signals) / len(signals) if signals else 0.0

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reddit": reddit,
            "trending": trending,
            "whales": whales,
            "combined_score": round(combined, 3),
            "sources_active": len(signals),
        }
