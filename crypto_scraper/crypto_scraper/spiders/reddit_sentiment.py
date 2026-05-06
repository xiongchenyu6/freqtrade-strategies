"""
Spider 2: Reddit Crypto Sentiment

Scrapes hot posts from crypto subreddits.
Uses old.reddit.com HTML parsing as fallback since JSON API
gets blocked on datacenter IPs.
"""

import scrapy
from datetime import datetime, timezone
from crypto_scraper.items import RedditPostItem


class RedditSentimentSpider(scrapy.Spider):
    name = "reddit_sentiment"

    SUBREDDITS = ["bitcoin", "cryptocurrency", "ethtrader", "solana", "defi"]

    custom_settings = {
        "DOWNLOAD_DELAY": 3,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "DEFAULT_REQUEST_HEADERS": {
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        },
    }

    def start_requests(self):
        for sub in self.SUBREDDITS:
            yield scrapy.Request(
                f"https://old.reddit.com/r/{sub}/hot/",
                callback=self.parse_subreddit,
                cb_kwargs={"subreddit": sub},
                errback=self.handle_error,
                dont_filter=True,
            )

    def parse_subreddit(self, response, subreddit):
        now = datetime.now(timezone.utc).isoformat()

        # old.reddit.com HTML structure
        posts = response.css("div.thing.link:not(.stickied)")

        for post in posts[:25]:
            title = post.css("a.title::text").get("").strip()
            score_text = post.css("div.score.unvoted::attr(title)").get("0")
            comments_text = post.css("a.comments::text").get("0 comments")
            permalink = post.css("a.comments::attr(href)").get("")

            try:
                score = int(score_text)
            except (ValueError, TypeError):
                score = 0

            try:
                num_comments = int(comments_text.split()[0])
            except (ValueError, IndexError):
                num_comments = 0

            if title:
                yield RedditPostItem(
                    subreddit=subreddit,
                    title=title,
                    score=score,
                    num_comments=num_comments,
                    upvote_ratio=0.0,
                    created_utc=0,
                    url=permalink,
                    scraped_at=now,
                )

    def handle_error(self, failure):
        self.logger.warning(f"Request failed: {failure.request.url} — {failure.value}")
