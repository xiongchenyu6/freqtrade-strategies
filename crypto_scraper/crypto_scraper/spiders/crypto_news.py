"""
Spider 1: Crypto News Headlines

Scrapes RSS feeds from major crypto news outlets.
Outputs headline items with source and timestamp.
"""

import scrapy
from datetime import datetime, timezone
from crypto_scraper.items import HeadlineItem


class CryptoNewsSpider(scrapy.Spider):
    name = "crypto_news"

    RSS_FEEDS = {
        "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "cointelegraph": "https://cointelegraph.com/rss",
        "bitcoinmagazine": "https://bitcoinmagazine.com/feed",
        "theblock": "https://www.theblock.co/rss.xml",
        "decrypt": "https://decrypt.co/feed",
    }

    def start_requests(self):
        for source, url in self.RSS_FEEDS.items():
            yield scrapy.Request(
                url,
                callback=self.parse_rss,
                cb_kwargs={"source": source},
                errback=self.handle_error,
            )

    def parse_rss(self, response, source):
        now = datetime.now(timezone.utc).isoformat()
        items = response.xpath("//item")

        for item in items[:25]:
            title = item.xpath("title/text()").get("").strip()
            link = item.xpath("link/text()").get("")
            pub_date = item.xpath("pubDate/text()").get("")

            if title:
                yield HeadlineItem(
                    source=source,
                    title=title,
                    url=link,
                    published=pub_date,
                    scraped_at=now,
                )

    def handle_error(self, failure):
        self.logger.warning(f"Request failed: {failure.request.url} — {failure.value}")
