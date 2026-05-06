"""
News Sentiment Analyzer Module

Fetches crypto news from multiple free sources and optionally
uses LLM (Claude) to analyze sentiment. Can be imported by any strategy.

Usage in strategy:
    from news_sentiment import NewsSentimentAnalyzer

    class MyStrategy(IStrategy):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.sentiment = NewsSentimentAnalyzer(
                anthropic_api_key="sk-...",  # optional, for LLM analysis
            )

        def bot_loop_start(self, current_time, **kwargs):
            self.sentiment.refresh()

        def populate_entry_trend(self, dataframe, metadata):
            score = self.sentiment.get_score()  # -1.0 to 1.0
            ...
"""

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional
from xml.etree import ElementTree

import requests

logger = logging.getLogger(__name__)


class NewsSentimentAnalyzer:
    """
    Multi-source crypto news sentiment analyzer.

    Sources (all free, no API key needed):
    1. CoinDesk RSS
    2. CoinTelegraph RSS
    3. Bitcoin Magazine RSS
    4. Fear & Greed Index

    Optional (needs API key):
    5. Claude API for headline sentiment analysis
    """

    # RSS feeds - free, no auth needed
    RSS_FEEDS = {
        "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "cointelegraph": "https://cointelegraph.com/rss",
        "bitcoinmagazine": "https://bitcoinmagazine.com/feed",
    }

    BULLISH_KEYWORDS = [
        "surge", "soar", "rally", "bull", "breakout", "all-time high", "ath",
        "adoption", "institutional", "etf approved", "buy", "accumulate",
        "upgrade", "partnership", "billion", "trillion", "record",
        "bullish", "moon", "pump", "green", "recovery",
    ]

    BEARISH_KEYWORDS = [
        "crash", "plunge", "bear", "dump", "sell-off", "selloff",
        "ban", "regulate", "hack", "exploit", "scam", "fraud",
        "sec", "lawsuit", "investigation", "bankrupt", "collapse",
        "fear", "panic", "red", "decline", "drop", "fall", "loss",
        "warning", "risk", "bubble", "ponzi",
    ]

    def __init__(
        self,
        anthropic_api_key: Optional[str] = None,
        cache_ttl: int = 1800,  # 30 min cache
    ):
        self.anthropic_api_key = anthropic_api_key
        self.cache_ttl = cache_ttl

        self._headlines_cache: list[dict] = []
        self._score_cache: float = 0.0
        self._cache_ts: float = 0
        self._seen_hashes: set = set()

    def refresh(self) -> None:
        """Refresh news data from all sources."""
        now = time.time()
        if now - self._cache_ts < self.cache_ttl:
            return

        headlines = []
        for name, url in self.RSS_FEEDS.items():
            try:
                items = self._fetch_rss(url, name)
                headlines.extend(items)
            except Exception as e:
                logger.warning(f"Failed to fetch {name} RSS: {e}")

        if not headlines:
            logger.warning("No headlines fetched from any source")
            return

        # Deduplicate by title hash
        unique = []
        for h in headlines:
            h_hash = hashlib.md5(h["title"].lower().encode()).hexdigest()
            if h_hash not in self._seen_hashes:
                self._seen_hashes.add(h_hash)
                unique.append(h)

        # Keep last 200 unique headlines
        self._headlines_cache = (unique + self._headlines_cache)[:200]

        # Score headlines
        if self.anthropic_api_key:
            self._score_cache = self._score_with_llm(self._headlines_cache[:20])
        else:
            self._score_cache = self._score_with_keywords(self._headlines_cache[:50])

        self._cache_ts = now
        logger.info(
            f"News sentiment: {self._score_cache:.2f} "
            f"({len(self._headlines_cache)} headlines, "
            f"{len(unique)} new)"
        )

    def get_score(self) -> float:
        """
        Returns sentiment score from -1.0 (extreme bearish) to 1.0 (extreme bullish).
        0.0 is neutral.
        """
        return self._score_cache

    def get_signal(self) -> str:
        """Returns human-readable signal: bullish / bearish / neutral."""
        score = self._score_cache
        if score > 0.3:
            return "bullish"
        elif score < -0.3:
            return "bearish"
        return "neutral"

    def get_recent_headlines(self, n: int = 10) -> list[str]:
        """Returns the N most recent headlines."""
        return [h["title"] for h in self._headlines_cache[:n]]

    def _fetch_rss(self, url: str, source: str) -> list[dict]:
        """Parse RSS feed and extract headlines."""
        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "FreqtradeBot/1.0",
        })
        resp.raise_for_status()

        root = ElementTree.fromstring(resp.content)

        items = []
        # Standard RSS format
        for item in root.findall(".//item")[:20]:
            title_el = item.find("title")
            pub_date_el = item.find("pubDate")

            if title_el is not None and title_el.text:
                items.append({
                    "title": title_el.text.strip(),
                    "source": source,
                    "published": pub_date_el.text if pub_date_el is not None else "",
                })

        logger.debug(f"Fetched {len(items)} headlines from {source}")
        return items

    def _score_with_keywords(self, headlines: list[dict]) -> float:
        """
        Simple keyword-based sentiment scoring.
        Fast, free, no API needed. Surprisingly effective for crypto news.
        """
        if not headlines:
            return 0.0

        total_score = 0.0
        scored_count = 0

        for h in headlines:
            title_lower = h["title"].lower()
            bull_count = sum(1 for kw in self.BULLISH_KEYWORDS if kw in title_lower)
            bear_count = sum(1 for kw in self.BEARISH_KEYWORDS if kw in title_lower)

            if bull_count > 0 or bear_count > 0:
                # Normalize to [-1, 1]
                score = (bull_count - bear_count) / max(bull_count + bear_count, 1)
                total_score += score
                scored_count += 1

        if scored_count == 0:
            return 0.0

        # Average score, clamped to [-1, 1]
        avg = total_score / scored_count
        return max(-1.0, min(1.0, avg))

    def _score_with_llm(self, headlines: list[dict]) -> float:
        """
        Use Claude to analyze headline sentiment.
        More accurate but costs API credits.
        """
        if not self.anthropic_api_key or not headlines:
            return self._score_with_keywords(headlines)

        titles = "\n".join(
            f"- [{h['source']}] {h['title']}" for h in headlines[:20]
        )

        prompt = f"""Analyze these crypto news headlines and rate the overall market sentiment.

Headlines:
{titles}

Rate the overall sentiment as a single number from -1.0 (extremely bearish) to 1.0 (extremely bullish).
Consider: Is the news cycle positive or negative? Are there major risks or catalysts?

Respond with ONLY a JSON object: {{"score": <number>, "reason": "<one sentence>"}}"""

        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 100,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=30,
            )
            resp.raise_for_status()
            content = resp.json()["content"][0]["text"]

            # Parse JSON from response
            match = re.search(r'\{[^}]+\}', content)
            if match:
                result = json.loads(match.group())
                score = float(result["score"])
                reason = result.get("reason", "")
                logger.info(f"LLM sentiment: {score:.2f} — {reason}")
                return max(-1.0, min(1.0, score))

        except Exception as e:
            logger.warning(f"LLM sentiment analysis failed: {e}")

        # Fallback to keyword scoring
        return self._score_with_keywords(headlines)
