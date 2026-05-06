import scrapy


class HeadlineItem(scrapy.Item):
    source = scrapy.Field()
    title = scrapy.Field()
    url = scrapy.Field()
    published = scrapy.Field()
    scraped_at = scrapy.Field()


class RedditPostItem(scrapy.Item):
    subreddit = scrapy.Field()
    title = scrapy.Field()
    score = scrapy.Field()
    num_comments = scrapy.Field()
    upvote_ratio = scrapy.Field()
    created_utc = scrapy.Field()
    url = scrapy.Field()
    scraped_at = scrapy.Field()


class TrendingCoinItem(scrapy.Item):
    name = scrapy.Field()
    symbol = scrapy.Field()
    market_cap_rank = scrapy.Field()
    price_change_24h = scrapy.Field()
    thumb = scrapy.Field()
    scraped_at = scrapy.Field()


class FearGreedItem(scrapy.Item):
    value = scrapy.Field()
    classification = scrapy.Field()
    timestamp = scrapy.Field()
    scraped_at = scrapy.Field()
