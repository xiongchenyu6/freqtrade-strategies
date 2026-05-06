"""
Spider 3: CoinGecko Trending + Fear & Greed Index

Scrapes:
- CoinGecko trending coins (what's getting attention)
- Fear & Greed Index (market temperature)
"""

import json
import scrapy
from datetime import datetime, timezone
from crypto_scraper.items import TrendingCoinItem, FearGreedItem


class TrendingCoinsSpider(scrapy.Spider):
    name = "trending_coins"

    custom_settings = {
        "DOWNLOAD_DELAY": 1,
        "DEFAULT_REQUEST_HEADERS": {
            "Accept": "application/json",
        },
    }

    def start_requests(self):
        # CoinGecko trending
        yield scrapy.Request(
            "https://api.coingecko.com/api/v3/search/trending",
            callback=self.parse_trending,
            errback=self.handle_error,
        )

        # Fear & Greed Index
        yield scrapy.Request(
            "https://api.alternative.me/fng/?limit=7",
            callback=self.parse_fng,
            errback=self.handle_error,
        )

    def parse_trending(self, response):
        now = datetime.now(timezone.utc).isoformat()

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            self.logger.warning("Failed to parse CoinGecko trending")
            return

        for item in data.get("coins", []):
            coin = item.get("item", {})
            price_data = coin.get("data", {})
            price_change = price_data.get("price_change_percentage_24h", {})

            yield TrendingCoinItem(
                name=coin.get("name", ""),
                symbol=coin.get("symbol", ""),
                market_cap_rank=coin.get("market_cap_rank", 0),
                price_change_24h=price_change.get("usd", 0) if isinstance(price_change, dict) else 0,
                thumb=coin.get("thumb", ""),
                scraped_at=now,
            )

    def parse_fng(self, response):
        now = datetime.now(timezone.utc).isoformat()

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            self.logger.warning("Failed to parse Fear & Greed")
            return

        for entry in data.get("data", []):
            yield FearGreedItem(
                value=int(entry.get("value", 50)),
                classification=entry.get("value_classification", "Neutral"),
                timestamp=entry.get("timestamp", ""),
                scraped_at=now,
            )

    def handle_error(self, failure):
        self.logger.warning(f"Request failed: {failure.request.url} — {failure.value}")
