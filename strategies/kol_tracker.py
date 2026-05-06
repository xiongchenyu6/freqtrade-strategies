"""
KOL (Key Opinion Leader) Impact Tracker

Detects mentions of high-impact individuals in news headlines and
assigns amplified sentiment scores. A single Trump tweet about
crypto can move BTC 5-10%, so these signals deserve heavy weighting.

Strategy:
  1. Scan all collected headlines for KOL name mentions
  2. When detected, analyze the context (bullish/bearish for crypto)
  3. Assign amplified score (KOL mentions get 3x weight)
  4. Track KOL activity frequency (sudden spike = something is happening)

Data sources:
  - Existing RSS headlines (CoinDesk, CoinTelegraph, etc.)
  - Zyte Cloud scraped headlines (TheBlock, Decrypt, etc.)
  - Google News RSS (free, covers mainstream media too)

No API key needed.
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

logger = logging.getLogger("kol_tracker")


# ---------------------------------------------------------------------------
# KOL Database — who moves crypto markets
# ---------------------------------------------------------------------------
KOLS = {
    # Politicians
    "trump": {
        "names": ["trump", "donald trump", "president trump"],
        "impact": 1.0,  # maximum impact
        "context": "president",
        "bullish_phrases": [
            "bitcoin reserve", "strategic reserve", "crypto friendly",
            "support crypto", "digital assets", "pro-crypto",
            "executive order", "bitcoin stockpile", "crypto capital",
            "embrace crypto", "love bitcoin", "deregulat",
        ],
        "bearish_phrases": [
            "ban crypto", "regulate crypto", "crackdown", "tariff",
            "trade war", "china", "sanctions",
        ],
    },

    # Tech leaders
    "musk": {
        "names": ["elon musk", "musk", "tesla"],
        "impact": 0.9,
        "context": "tech_ceo",
        "bullish_phrases": [
            "bitcoin", "doge", "accept crypto", "pay with",
            "diamond hands", "to the moon", "buy", "hold",
            "tesla bitcoin", "spacex", "xpayments",
        ],
        "bearish_phrases": [
            "sell", "dump", "suspend", "energy concern",
            "stop accepting", "scam",
        ],
    },

    # Crypto native
    "saylor": {
        "names": ["michael saylor", "saylor", "microstrategy", "strategy"],
        "impact": 0.7,
        "context": "btc_whale",
        "bullish_phrases": [
            "buy bitcoin", "purchased", "acquired", "billion",
            "accumulate", "strategy buys", "add more",
        ],
        "bearish_phrases": [
            "sell", "liquidate", "margin call", "debt",
        ],
    },

    # Finance
    "blackrock": {
        "names": ["blackrock", "larry fink", "ishares", "ibit"],
        "impact": 0.8,
        "context": "institution",
        "bullish_phrases": [
            "etf", "bitcoin etf", "inflow", "filing", "approve",
            "tokeniz", "digital asset", "allocat",
        ],
        "bearish_phrases": [
            "outflow", "redeem", "withdraw", "concern",
        ],
    },

    # Regulators
    "sec": {
        "names": ["sec", "gensler", "securities and exchange"],
        "impact": 0.7,
        "context": "regulator",
        "bullish_phrases": [
            "approve", "clarity", "framework", "safe harbor",
            "not a security", "dismiss", "withdraw",
        ],
        "bearish_phrases": [
            "sue", "lawsuit", "enforcement", "fraud", "charge",
            "violation", "unregistered", "ponzi", "fine",
        ],
    },

    # Fed
    "fed": {
        "names": ["federal reserve", "jerome powell", "powell", "the fed"],
        "impact": 0.6,
        "context": "central_bank",
        "bullish_phrases": [
            "rate cut", "dovish", "pause", "pivot", "easing",
            "lower rates", "inject", "liquidity",
        ],
        "bearish_phrases": [
            "rate hike", "hawkish", "tighten", "inflation",
            "higher for longer", "restrictive",
        ],
    },

    # Other impactful
    "cathie_wood": {
        "names": ["cathie wood", "ark invest", "arkk"],
        "impact": 0.5,
        "context": "fund_manager",
        "bullish_phrases": ["buy", "bullish", "million", "target", "accumulate"],
        "bearish_phrases": ["sell", "reduce", "concern"],
    },

    "vitalik": {
        "names": ["vitalik", "buterin"],
        "impact": 0.5,
        "context": "eth_founder",
        "bullish_phrases": ["upgrade", "scaling", "adoption", "roadmap", "progress"],
        "bearish_phrases": ["concern", "delay", "vulnerability", "sell"],
    },
}


# Google News RSS — free, covers mainstream media KOL mentions
GOOGLE_NEWS_FEEDS = [
    "https://news.google.com/rss/search?q=trump+bitcoin+OR+crypto&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=elon+musk+bitcoin+OR+crypto+OR+doge&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=bitcoin+etf+OR+blackrock+OR+SEC&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=federal+reserve+rate+crypto+bitcoin&hl=en-US&gl=US&ceid=US:en",
]


class KOLTracker:
    """Track KOL mentions and their impact on crypto sentiment."""

    def __init__(self):
        self._cache: dict = {}
        self._cache_ts: float = 0
        self._CACHE_TTL = 1800  # 30 min

    def fetch_google_news(self) -> list[dict]:
        """Fetch KOL-related headlines from Google News RSS."""
        headlines = []
        for url in GOOGLE_NEWS_FEEDS:
            try:
                resp = requests.get(
                    url, timeout=15,
                    headers={"User-Agent": "FreqtradeBot/1.0"},
                )
                if resp.status_code != 200:
                    continue
                root = ElementTree.fromstring(resp.content)
                for item in root.findall(".//item")[:15]:
                    title_el = item.find("title")
                    pub_el = item.find("pubDate")
                    link_el = item.find("link")
                    if title_el is not None and title_el.text:
                        headlines.append({
                            "title": title_el.text.strip(),
                            "source": "google_news",
                            "published": pub_el.text if pub_el is not None else "",
                            "link": link_el.text.strip() if link_el is not None and link_el.text else "",
                        })
                time.sleep(0.5)
            except Exception as e:
                logger.debug(f"Google News RSS failed for {url[:60]}: {e}")

        logger.info(f"Google News: fetched {len(headlines)} KOL-related headlines")
        return headlines

    def analyze_headlines(self, headlines: list[dict]) -> dict:
        """
        Scan headlines for KOL mentions and score their impact.

        Returns:
            {
                "score": float,         # -1.0 to 1.0
                "signal": str,
                "kol_mentions": [...],   # detected KOL mentions with context
                "alert_level": str,      # "none" / "watch" / "urgent"
            }
        """
        kol_mentions = []
        total_score = 0.0
        total_weight = 0.0

        for h in headlines:
            title_lower = h["title"].lower()

            for kol_id, kol in KOLS.items():
                # Check if any KOL name appears in headline
                matched_name = None
                for name in kol["names"]:
                    if name in title_lower:
                        matched_name = name
                        break

                if not matched_name:
                    continue

                # Determine sentiment from context
                bull_count = sum(1 for p in kol["bullish_phrases"] if p in title_lower)
                bear_count = sum(1 for p in kol["bearish_phrases"] if p in title_lower)

                # Symmetric scoring: normalize by total keyword matches
                total_kw = bull_count + bear_count
                if total_kw > 0:
                    # Score from -1 to +1 based on ratio, no base offset
                    raw_score = (bull_count - bear_count) / total_kw
                    sentiment = "bullish" if raw_score > 0.1 else "bearish" if raw_score < -0.1 else "neutral"
                else:
                    sentiment = "neutral"
                    raw_score = 0.0

                # Apply KOL impact multiplier
                weighted_score = raw_score * kol["impact"]

                mention = {
                    "kol": kol_id,
                    "matched": matched_name,
                    "title": h["title"],
                    "sentiment": sentiment,
                    "score": round(weighted_score, 2),
                    "source": h.get("source", "unknown"),
                    "link": h.get("link", ""),
                    "published": h.get("published", ""),
                }
                kol_mentions.append(mention)

                total_score += weighted_score
                total_weight += kol["impact"]

        # Normalize
        if total_weight > 0:
            score = total_score / total_weight
        else:
            score = 0.0
        score = max(-1.0, min(1.0, score))

        # Alert level
        high_impact = [m for m in kol_mentions if abs(m["score"]) > 0.3]
        if len(high_impact) >= 3:
            alert = "urgent"
        elif len(high_impact) >= 1:
            alert = "watch"
        else:
            alert = "none"

        signal = "bullish" if score > 0.15 else "bearish" if score < -0.15 else "neutral"

        return {
            "score": round(score, 3),
            "signal": signal,
            "kol_mentions": kol_mentions,
            "mention_count": len(kol_mentions),
            "alert_level": alert,
            "high_impact_count": len(high_impact),
        }

    def run(self, extra_headlines: list[dict] = None) -> dict:
        """
        Full KOL tracking run.
        1. Fetch Google News KOL headlines
        2. Combine with any extra headlines (from pipeline)
        3. Analyze and score
        """
        now = time.time()
        if now - self._cache_ts < self._CACHE_TTL and self._cache:
            return self._cache

        # Collect headlines
        headlines = self.fetch_google_news()
        if extra_headlines:
            headlines.extend(extra_headlines)

        result = self.analyze_headlines(headlines)
        result["headline_count"] = len(headlines)
        result["timestamp"] = datetime.now(timezone.utc).isoformat()

        self._cache = result
        self._cache_ts = now

        if result["mention_count"] > 0:
            logger.info(
                f"KOL Tracker: {result['mention_count']} mentions, "
                f"score={result['score']:+.2f}, alert={result['alert_level']}"
            )
            for m in result["kol_mentions"][:5]:
                logger.info(f"  [{m['kol']:12s}] {m['sentiment']:8s} {m['score']:+.2f} | {m['title'][:80]}")

        return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    tracker = KOLTracker()
    result = tracker.run()

    print(f"\n{'='*60}")
    print(f"  KOL Impact Tracker")
    print(f"  Score: {result['score']:+.2f} ({result['signal']})")
    print(f"  Alert: {result['alert_level']} | Mentions: {result['mention_count']}")
    print(f"{'='*60}")

    if result["kol_mentions"]:
        print(f"\n  Detected mentions:")
        for m in result["kol_mentions"]:
            icon = "🟢" if m["sentiment"] == "bullish" else "🔴" if m["sentiment"] == "bearish" else "⚪"
            print(f"  {icon} [{m['kol']:12s}] {m['score']:+.2f} | {m['title'][:70]}")
    else:
        print("\n  No KOL mentions detected in recent news.")
