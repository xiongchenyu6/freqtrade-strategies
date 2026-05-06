BOT_NAME = "crypto_scraper"

SPIDER_MODULES = ["crypto_scraper.spiders"]
NEWSPIDER_MODULE = "crypto_scraper.spiders"

# Obey robots.txt
ROBOTSTXT_OBEY = False

# Be polite
CONCURRENT_REQUESTS = 4
DOWNLOAD_DELAY = 1
RANDOMIZE_DOWNLOAD_DELAY = True

# Retry
RETRY_TIMES = 3
RETRY_HTTP_CODES = [429, 500, 502, 503, 504]

USER_AGENT = "CryptoSentimentBot/1.0 (+https://github.com/freqtrade)"

DEFAULT_REQUEST_HEADERS = {
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# Output
FEED_EXPORT_ENCODING = "utf-8"

REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
