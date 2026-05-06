"""
Zyte Cloud Results Fetcher

Pulls scraped data from Zyte Scrapy Cloud and feeds it into
the sentiment pipeline. Designed to be called from news_pipeline.py
or as a standalone script.

Usage:
    python zyte_cloud_fetcher.py                  # fetch & display
    python zyte_cloud_fetcher.py --trigger-run    # trigger new spider runs first

Requires: ZYTE_API_KEY env var (or pass directly)
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger("zyte_cloud")

ZYTE_API_KEY = os.environ.get("ZYTE_API_KEY", "")
PROJECT_ID = os.environ.get("ZYTE_PROJECT_ID", "858078")

SPIDERS = {
    "crypto_news": 1,      # spider slot 1
    "reddit_sentiment": 2,  # spider slot 2
    "trending_coins": 3,    # spider slot 3
}


class ZyteCloudFetcher:
    """Fetch and parse results from Zyte Scrapy Cloud."""

    def __init__(self, api_key: str = ZYTE_API_KEY, project: str = PROJECT_ID):
        self.api_key = api_key
        self.project = project
        self.auth = (self.api_key, "")

    def trigger_spiders(self) -> dict[str, str]:
        """Trigger all spiders to run. Returns {spider_name: job_id}."""
        jobs = {}
        for spider_name in SPIDERS:
            try:
                resp = requests.post(
                    "https://app.scrapinghub.com/api/schedule.json",
                    auth=self.auth,
                    data={
                        "project": self.project,
                        "spider": spider_name,
                        "add_tag": "auto",
                        "priority": 2,
                        "units": 1,
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                result = resp.json()
                jobs[spider_name] = result.get("jobid", "")
                logger.info(f"Triggered {spider_name}: job={jobs[spider_name]}")
            except Exception as e:
                logger.warning(f"Failed to trigger {spider_name}: {e}")
        return jobs

    def get_latest_job(self, spider_name: str) -> Optional[str]:
        """Get the latest finished job ID for a spider."""
        try:
            resp = requests.get(
                "https://app.scrapinghub.com/api/jobs/list.json",
                auth=self.auth,
                params={
                    "project": self.project,
                    "spider": spider_name,
                    "state": "finished",
                    "count": 1,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            jobs = data.get("jobs", [])
            if jobs:
                return jobs[0].get("id", "")
        except Exception as e:
            logger.warning(f"Failed to get latest job for {spider_name}: {e}")
        return None

    def fetch_items(self, job_id: str, count: int = 200) -> list[dict]:
        """Fetch items from a completed job."""
        if not job_id:
            return []
        try:
            resp = requests.get(
                f"https://storage.scrapinghub.com/items/{job_id}",
                auth=self.auth,
                params={"format": "json", "count": count},
                timeout=30,
            )
            resp.raise_for_status()
            text = resp.text.strip()
            if not text:
                return []
            # Zyte returns JSON array
            if text.startswith("["):
                return json.loads(text)
            # Fallback: newline-delimited JSON
            return [json.loads(line) for line in text.split("\n") if line]
        except Exception as e:
            logger.warning(f"Failed to fetch items for {job_id}: {e}")
            return []

    def fetch_all(self) -> dict:
        """
        Fetch latest results from all spiders.

        Returns:
            {
                "headlines": [...],
                "reddit_posts": [...],
                "trending_coins": [...],
                "fear_greed": [...],
                "reddit_sentiment": float,
                "trending_symbols": [str],
            }
        """
        result = {
            "headlines": [],
            "reddit_posts": [],
            "trending_coins": [],
            "fear_greed": [],
            "reddit_sentiment": 0.0,
            "trending_symbols": [],
        }

        # Crypto news
        job_id = self.get_latest_job("crypto_news")
        if job_id:
            items = self.fetch_items(job_id)
            result["headlines"] = [
                i for i in items if "title" in i and "source" in i
            ]
            logger.info(f"Fetched {len(result['headlines'])} headlines from Zyte")

        # Reddit
        job_id = self.get_latest_job("reddit_sentiment")
        if job_id:
            items = self.fetch_items(job_id)
            result["reddit_posts"] = [i for i in items if "subreddit" in i]

            # Compute Reddit sentiment
            BULL = ["bullish", "moon", "buy", "pump", "green", "rally", "ath", "accumulate", "hodl"]
            BEAR = ["bearish", "crash", "dump", "sell", "red", "scam", "fear", "ban", "hack", "rug"]
            bull = bear = 0
            for p in result["reddit_posts"]:
                t = p.get("title", "").lower()
                bull += sum(1 for kw in BULL if kw in t)
                bear += sum(1 for kw in BEAR if kw in t)
            total = bull + bear
            result["reddit_sentiment"] = (bull - bear) / total if total > 0 else 0.0
            logger.info(
                f"Fetched {len(result['reddit_posts'])} reddit posts, "
                f"sentiment={result['reddit_sentiment']:.2f}"
            )

        # Trending coins + Fear & Greed
        job_id = self.get_latest_job("trending_coins")
        if job_id:
            items = self.fetch_items(job_id)
            result["trending_coins"] = [i for i in items if "symbol" in i]
            result["fear_greed"] = [i for i in items if "classification" in i and "symbol" not in i]
            result["trending_symbols"] = [c["symbol"] for c in result["trending_coins"][:10]]
            logger.info(
                f"Fetched {len(result['trending_coins'])} trending coins, "
                f"{len(result['fear_greed'])} FnG entries"
            )

        return result

    def get_summary(self) -> str:
        """Human-readable summary of Zyte Cloud data."""
        data = self.fetch_all()

        trending = ", ".join(data["trending_symbols"][:8]) or "n/a"
        fng = data["fear_greed"][0] if data["fear_greed"] else {}
        fng_str = f"{fng.get('value', '?')} ({fng.get('classification', '?')})"

        # Top Reddit posts by score
        top_reddit = sorted(data["reddit_posts"], key=lambda x: x.get("score", 0), reverse=True)[:5]

        lines = [
            "=== Zyte Cloud Data Summary ===",
            f"Headlines:       {len(data['headlines'])} from 5 sources",
            f"Reddit posts:    {len(data['reddit_posts'])} from 5 subreddits",
            f"Reddit sentiment:{data['reddit_sentiment']:+.2f}",
            f"Fear & Greed:    {fng_str}",
            f"Trending:        {trending}",
            "",
            "Top Reddit posts:",
        ]
        for p in top_reddit:
            lines.append(f"  [{p.get('subreddit', '?'):15s}] ↑{p.get('score', 0):5d} | {p.get('title', '')[:70]}")

        return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument("--trigger-run", action="store_true", help="Trigger new spider runs")
    args = parser.parse_args()

    fetcher = ZyteCloudFetcher()

    if args.trigger_run:
        print("Triggering spider runs...")
        jobs = fetcher.trigger_spiders()
        for name, jid in jobs.items():
            print(f"  {name}: {jid}")
        print("\nSpiders running. Results will be available in 1-2 minutes.")
    else:
        print(fetcher.get_summary())
