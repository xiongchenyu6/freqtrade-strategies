"""
Shared Sentiment Database — Supabase

All platforms (local, Deepnote, CamberCloud) write sentiment data here.
Freqtrade reads from here. Single source of truth.

Setup:
  1. Go to https://supabase.com → New Project (free)
  2. Run the SQL below in SQL Editor to create tables
  3. Get URL + anon key from Settings → API
  4. Set env vars: SUPABASE_URL, SUPABASE_KEY

SQL to create tables (run in Supabase SQL Editor):

    CREATE TABLE sentiment_snapshots (
        id BIGSERIAL PRIMARY KEY,
        timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        source TEXT NOT NULL DEFAULT 'local',
        combined_score REAL NOT NULL,
        signal TEXT NOT NULL,
        fng_value INTEGER,
        fng_classification TEXT,
        keyword_sentiment REAL,
        kol_score REAL,
        kol_mentions INTEGER,
        market_score REAL,
        btc_price REAL,
        btc_24h_change REAL,
        headline_count INTEGER,
        raw_json JSONB
    );

    CREATE TABLE kol_events (
        id BIGSERIAL PRIMARY KEY,
        timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        kol TEXT NOT NULL,
        sentiment TEXT NOT NULL,
        score REAL NOT NULL,
        title TEXT NOT NULL,
        source TEXT
    );

    CREATE TABLE headlines (
        id BIGSERIAL PRIMARY KEY,
        timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        source TEXT NOT NULL,
        title TEXT NOT NULL,
        keyword_score REAL,
        llm_score REAL
    );

    -- Index for fast queries
    CREATE INDEX idx_snapshots_ts ON sentiment_snapshots(timestamp DESC);
    CREATE INDEX idx_kol_ts ON kol_events(timestamp DESC);
    CREATE INDEX idx_kol_name ON kol_events(kol, timestamp DESC);

    -- Enable Row Level Security (required by Supabase)
    ALTER TABLE sentiment_snapshots ENABLE ROW LEVEL SECURITY;
    ALTER TABLE kol_events ENABLE ROW LEVEL SECURITY;
    ALTER TABLE headlines ENABLE ROW LEVEL SECURITY;

    -- Allow anon key to read/write (for our bot)
    CREATE POLICY "Allow all" ON sentiment_snapshots FOR ALL USING (true) WITH CHECK (true);
    CREATE POLICY "Allow all" ON kol_events FOR ALL USING (true) WITH CHECK (true);
    CREATE POLICY "Allow all" ON headlines FOR ALL USING (true) WITH CHECK (true);

Usage:
    from sentiment_db import SentimentDB
    db = SentimentDB()
    db.push_snapshot(result_dict)
    latest = db.get_latest()
    history = db.get_history(hours=24)
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("sentiment_db")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")


class SentimentDB:
    """Read/write sentiment data to Supabase."""

    def __init__(self, url: str = SUPABASE_URL, key: str = SUPABASE_KEY):
        self.url = url
        self.key = key
        self._client = None

    @property
    def client(self):
        if self._client is None:
            if not self.url or not self.key:
                raise ValueError(
                    "SUPABASE_URL and SUPABASE_KEY must be set. "
                    "Get them from https://supabase.com → Project → Settings → API"
                )
            from supabase import create_client
            self._client = create_client(self.url, self.key)
        return self._client

    @property
    def available(self) -> bool:
        return bool(self.url and self.key)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------
    def push_snapshot(self, data: dict, source: str = "local") -> bool:
        """Push a sentiment snapshot to the database."""
        try:
            row = {
                "source": source,
                "combined_score": data.get("combined_score", 0),
                "signal": data.get("signal", "neutral"),
                "fng_value": data.get("fng_value"),
                "fng_classification": data.get("fng_classification"),
                "keyword_sentiment": data.get("keyword_sentiment"),
                "kol_score": data.get("kol_score"),
                "kol_mentions": data.get("kol_mentions"),
                "market_score": data.get("market_score"),
                "btc_price": data.get("btc_price"),
                "btc_24h_change": data.get("btc_24h_change"),
                "headline_count": data.get("headline_count"),
                "raw_json": data,
            }
            self.client.table("sentiment_snapshots").insert(row).execute()
            logger.info(f"Pushed snapshot: score={data.get('combined_score')}, source={source}")
            return True
        except Exception as e:
            logger.warning(f"Failed to push snapshot: {e}")
            return False

    def push_kol_events(self, mentions: list[dict]) -> bool:
        """Push KOL mention events to the database."""
        if not mentions:
            return True
        try:
            rows = [
                {
                    "kol": m.get("kol", "unknown"),
                    "sentiment": m.get("sentiment", "neutral"),
                    "score": m.get("score", 0),
                    "title": m.get("title", "")[:500],
                    "source": m.get("source", ""),
                }
                for m in mentions
                if abs(m.get("score", 0)) > 0.1  # only significant mentions
            ]
            if rows:
                self.client.table("kol_events").insert(rows).execute()
                logger.info(f"Pushed {len(rows)} KOL events")
            return True
        except Exception as e:
            logger.warning(f"Failed to push KOL events: {e}")
            return False

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------
    def get_latest(self) -> Optional[dict]:
        """Get the most recent sentiment snapshot."""
        try:
            result = (
                self.client.table("sentiment_snapshots")
                .select("*")
                .order("timestamp", desc=True)
                .limit(1)
                .execute()
            )
            if result.data:
                return result.data[0]
        except Exception as e:
            logger.warning(f"Failed to get latest: {e}")
        return None

    def get_history(self, hours: int = 24) -> list[dict]:
        """Get sentiment history for the last N hours."""
        try:
            from datetime import timedelta
            since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
            result = (
                self.client.table("sentiment_snapshots")
                .select("timestamp,combined_score,signal,fng_value,btc_price,kol_score,source")
                .gte("timestamp", since)
                .order("timestamp", desc=True)
                .execute()
            )
            return result.data or []
        except Exception as e:
            logger.warning(f"Failed to get history: {e}")
            return []

    def get_kol_events(self, kol: str = None, hours: int = 24) -> list[dict]:
        """Get recent KOL events, optionally filtered by KOL name."""
        try:
            from datetime import timedelta
            since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
            query = (
                self.client.table("kol_events")
                .select("*")
                .gte("timestamp", since)
                .order("timestamp", desc=True)
            )
            if kol:
                query = query.eq("kol", kol)
            result = query.execute()
            return result.data or []
        except Exception as e:
            logger.warning(f"Failed to get KOL events: {e}")
            return []

    def get_kol_summary(self, hours: int = 24) -> dict:
        """Get KOL activity summary — who's saying what."""
        events = self.get_kol_events(hours=hours)
        summary = {}
        for e in events:
            kol = e["kol"]
            if kol not in summary:
                summary[kol] = {"bullish": 0, "bearish": 0, "neutral": 0, "total": 0}
            summary[kol][e["sentiment"]] += 1
            summary[kol]["total"] += 1
        return summary


# ---------------------------------------------------------------------------
# Convenience: use REST API directly (no Python SDK needed)
# Works from any language/platform with just curl
# ---------------------------------------------------------------------------
def push_via_rest(data: dict, source: str = "local") -> bool:
    """
    Push sentiment data using pure REST API.
    Works from shell scripts, Deepnote, CamberCloud — anywhere with curl.

    Example curl command:
        curl -X POST 'https://YOUR_PROJECT.supabase.co/rest/v1/sentiment_snapshots' \
          -H 'apikey: YOUR_ANON_KEY' \
          -H 'Content-Type: application/json' \
          -d '{"combined_score": -0.06, "signal": "neutral", "source": "camber", ...}'
    """
    import requests
    try:
        row = {
            "source": source,
            "combined_score": data.get("combined_score", 0),
            "signal": data.get("signal", "neutral"),
            "fng_value": data.get("fng_value"),
            "fng_classification": data.get("fng_classification"),
            "kol_score": data.get("kol_score"),
            "kol_mentions": data.get("kol_mentions"),
            "btc_price": data.get("btc_price"),
            "headline_count": data.get("headline_count"),
            "raw_json": data,
        }
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/sentiment_snapshots",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json=row,
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.warning(f"REST push failed: {e}")
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    if not SUPABASE_URL:
        print("Supabase not configured yet.\n")
        print("Setup steps:")
        print("1. Go to https://supabase.com → New Project (free)")
        print("2. Go to SQL Editor, paste the CREATE TABLE SQL from this file's docstring")
        print("3. Go to Settings → API, copy:")
        print("   - Project URL → export SUPABASE_URL='https://xxx.supabase.co'")
        print("   - anon/public key → export SUPABASE_KEY='eyJ...'")
        print("4. Run this script again to test")
    else:
        db = SentimentDB()
        latest = db.get_latest()
        if latest:
            print(f"Latest: score={latest['combined_score']}, signal={latest['signal']}, source={latest['source']}")
        else:
            print("No data yet. Run the pipeline to push data.")
