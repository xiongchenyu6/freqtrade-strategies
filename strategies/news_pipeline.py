"""
News-Driven Sentiment Pipeline

A standalone pipeline that:
1. Scrapes news from multiple free RSS sources
2. Fetches social sentiment (Fear & Greed, Reddit)
3. Analyzes headlines with LLM (Claude Haiku — cheap & fast)
4. Stores time-series sentiment scores to local JSON/SQLite
5. Can be scheduled via Deepnote/CamberCloud/cron

Designed to run independently from freqtrade. The strategy reads
the saved scores at trading time.

Usage:
    # Run once (e.g., from cron or scheduled notebook)
    python news_pipeline.py

    # Or import and use programmatically
    from news_pipeline import NewsPipeline
    pipeline = NewsPipeline(anthropic_api_key="sk-...")
    pipeline.run()
    print(pipeline.get_latest_report())
"""

import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("news_pipeline")

# ---------------------------------------------------------------------------
# Data directory — sits next to this file
# ---------------------------------------------------------------------------
DATA_DIR = Path(__file__).parent.parent / "sentiment_data"
DB_PATH = DATA_DIR / "sentiment.db"


class NewsPipeline:
    """End-to-end news sentiment pipeline."""

    RSS_FEEDS = {
        "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "cointelegraph": "https://cointelegraph.com/rss",
        "bitcoinmagazine": "https://bitcoinmagazine.com/feed",
    }

    def __init__(
        self,
        anthropic_api_key: Optional[str] = None,
        db_path: Optional[Path] = None,
    ):
        self.anthropic_api_key = anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.db_path = db_path or DB_PATH

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS headlines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    source TEXT NOT NULL,
                    title TEXT NOT NULL,
                    title_hash TEXT UNIQUE NOT NULL,
                    keyword_score REAL,
                    llm_score REAL,
                    llm_reason TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sentiment_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    fng_value INTEGER,
                    fng_classification TEXT,
                    keyword_sentiment REAL,
                    llm_sentiment REAL,
                    combined_score REAL,
                    signal TEXT,
                    headline_count INTEGER,
                    raw_json TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_snapshots_ts
                ON sentiment_snapshots(timestamp)
            """)

    # ------------------------------------------------------------------
    # Data Collection
    # ------------------------------------------------------------------
    def _fetch_rss(self, url: str, source: str) -> list[dict]:
        try:
            resp = requests.get(url, timeout=15, headers={
                "User-Agent": "FreqtradeBot/1.0",
            })
            resp.raise_for_status()
            root = ElementTree.fromstring(resp.content)

            items = []
            for item in root.findall(".//item")[:25]:
                title_el = item.find("title")
                pub_date_el = item.find("pubDate")
                if title_el is not None and title_el.text:
                    items.append({
                        "title": title_el.text.strip(),
                        "source": source,
                        "published": pub_date_el.text if pub_date_el is not None else "",
                    })
            logger.info(f"Fetched {len(items)} headlines from {source}")
            return items
        except Exception as e:
            logger.warning(f"Failed to fetch {source}: {e}")
            return []

    def _fetch_fear_greed(self) -> dict:
        try:
            resp = requests.get(
                "https://api.alternative.me/fng/?limit=7", timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            import numpy as np
            return {
                "value": int(data[0]["value"]),
                "classification": data[0]["value_classification"],
                "avg_7d": int(np.mean([int(d["value"]) for d in data])),
            }
        except Exception as e:
            logger.warning(f"Failed to fetch Fear & Greed: {e}")
            return {"value": 50, "classification": "Neutral", "avg_7d": 50}

    # ------------------------------------------------------------------
    # Sentiment Analysis
    # ------------------------------------------------------------------
    BULLISH_KW = [
        "surge", "soar", "rally", "bull", "breakout", "all-time high", "ath",
        "adoption", "institutional", "etf", "buy", "accumulate", "upgrade",
        "partnership", "billion", "record", "bullish", "recovery", "approval",
        "inflow", "demand",
    ]
    BEARISH_KW = [
        "crash", "plunge", "bear", "dump", "sell-off", "selloff", "ban",
        "hack", "exploit", "scam", "fraud", "sec", "lawsuit", "bankrupt",
        "collapse", "fear", "panic", "decline", "drop", "fall", "warning",
        "risk", "bubble", "outflow", "liquidat",
    ]

    def _keyword_score(self, title: str) -> float:
        t = title.lower()
        bull = sum(1 for kw in self.BULLISH_KW if kw in t)
        bear = sum(1 for kw in self.BEARISH_KW if kw in t)
        if bull + bear == 0:
            return 0.0
        return (bull - bear) / (bull + bear)

    def _llm_score_batch(self, headlines: list[dict]) -> list[dict]:
        """Use Claude Haiku to score a batch of headlines."""
        if not self.anthropic_api_key or not headlines:
            return [{"score": self._keyword_score(h["title"]), "reason": "keyword"} for h in headlines]

        titles_text = "\n".join(
            f"{i+1}. [{h['source']}] {h['title']}"
            for i, h in enumerate(headlines[:30])
        )

        prompt = f"""Score each crypto news headline for market sentiment.
For each headline, give a score from -1.0 (very bearish) to 1.0 (very bullish).
0.0 = neutral/irrelevant.

Headlines:
{titles_text}

Respond with ONLY a JSON array:
[{{"n": 1, "s": 0.5, "r": "one word reason"}}, ...]

Be concise. s = score, r = reason."""

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
                    "max_tokens": 1500,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=30,
            )
            resp.raise_for_status()
            content = resp.json()["content"][0]["text"]

            match = re.search(r'\[.*\]', content, re.DOTALL)
            if match:
                results = json.loads(match.group())
                return [
                    {"score": float(r.get("s", 0)), "reason": r.get("r", "")}
                    for r in results
                ]
        except Exception as e:
            logger.warning(f"LLM scoring failed: {e}")

        return [{"score": self._keyword_score(h["title"]), "reason": "keyword-fallback"} for h in headlines]

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------
    def run(self) -> dict:
        """Execute the full pipeline. Returns the snapshot."""
        now = datetime.now(timezone.utc).isoformat()
        logger.info("=== Starting news pipeline ===")

        # 1. Collect headlines from RSS + Zyte Cloud
        all_headlines = []
        for name, url in self.RSS_FEEDS.items():
            all_headlines.extend(self._fetch_rss(url, name))

        # 1b. Pull headlines & Reddit data from Zyte Cloud
        zyte_cloud_data = {}
        try:
            from zyte_cloud_fetcher import ZyteCloudFetcher
            fetcher = ZyteCloudFetcher()
            zyte_cloud_data = fetcher.fetch_all()

            # Merge Zyte Cloud headlines into our list
            for h in zyte_cloud_data.get("headlines", []):
                all_headlines.append({
                    "title": h.get("title", ""),
                    "source": f"zyte_{h.get('source', 'unknown')}",
                    "published": h.get("published", ""),
                })
            logger.info(
                f"Zyte Cloud: +{len(zyte_cloud_data.get('headlines', []))} headlines, "
                f"reddit_sentiment={zyte_cloud_data.get('reddit_sentiment', 0):.2f}, "
                f"trending={zyte_cloud_data.get('trending_symbols', [])}"
            )
        except ImportError:
            logger.debug("zyte_cloud_fetcher not available")
        except Exception as e:
            logger.warning(f"Zyte Cloud fetch failed: {e}")

        # 2. Deduplicate and store
        new_headlines = []
        with sqlite3.connect(self.db_path) as conn:
            for h in all_headlines:
                h_hash = hashlib.sha256(h["title"].lower().strip().encode()).hexdigest()[:16]
                existing = conn.execute(
                    "SELECT 1 FROM headlines WHERE title_hash = ?", (h_hash,)
                ).fetchone()
                if not existing:
                    kw_score = self._keyword_score(h["title"])
                    conn.execute(
                        "INSERT INTO headlines (timestamp, source, title, title_hash, keyword_score) VALUES (?, ?, ?, ?, ?)",
                        (now, h["source"], h["title"], h_hash, kw_score),
                    )
                    h["keyword_score"] = kw_score
                    new_headlines.append(h)

        logger.info(f"New headlines: {len(new_headlines)} / {len(all_headlines)} total")

        # 3. LLM analysis on new headlines
        llm_results = []
        if new_headlines and self.anthropic_api_key:
            llm_results = self._llm_score_batch(new_headlines)
            with sqlite3.connect(self.db_path) as conn:
                for h, lr in zip(new_headlines, llm_results):
                    h_hash = hashlib.sha256(h["title"].lower().strip().encode()).hexdigest()[:16]
                    conn.execute(
                        "UPDATE headlines SET llm_score = ?, llm_reason = ? WHERE title_hash = ?",
                        (lr["score"], lr["reason"], h_hash),
                    )

        # 4. Compute aggregate scores
        with sqlite3.connect(self.db_path) as conn:
            # Last 24h keyword scores
            rows = conn.execute("""
                SELECT keyword_score, llm_score FROM headlines
                WHERE timestamp >= datetime('now', '-24 hours')
                ORDER BY id DESC LIMIT 100
            """).fetchall()
            # Fallback if no recent data
            if not rows:
                rows = conn.execute("""
                    SELECT keyword_score, llm_score FROM headlines
                    ORDER BY id DESC LIMIT 50
                """).fetchall()

        kw_scores = [r[0] for r in rows if r[0] is not None]
        llm_scores = [r[1] for r in rows if r[1] is not None]

        import numpy as np
        keyword_sentiment = float(np.mean(kw_scores)) if kw_scores else 0.0
        llm_sentiment = float(np.mean(llm_scores)) if llm_scores else keyword_sentiment

        # 5. Fear & Greed
        fng = self._fetch_fear_greed()

        # 5b. Reddit sentiment from Zyte Cloud
        zyte_score = 0.0
        zyte_data = zyte_cloud_data
        if zyte_cloud_data:
            reddit_s = zyte_cloud_data.get("reddit_sentiment", 0.0)
            zyte_score = reddit_s
            logger.info(f"Zyte Cloud reddit_sentiment={reddit_s:.2f}")

        # 5c. External sources: CryptoPanic, Glassnode, Twitter
        ext_score = 0.0
        ext_data = {}
        try:
            from external_sources import fetch_all_external
            ext_data = fetch_all_external()
            ext_score = ext_data.get("combined_score", 0.0)
            logger.info(
                f"External sources: score={ext_score:.2f}, "
                f"active={ext_data.get('active_sources', 0)}, "
                f"signal={ext_data.get('signal', 'n/a')}"
            )
        except ImportError:
            logger.debug("external_sources not available")
        except Exception as e:
            logger.warning(f"External sources failed: {e}")

        # 5d. Binance Futures factors (funding rate, OI, L/S, taker)
        futures_score = 0.0
        futures_data = {}
        try:
            from futures_factors import FuturesFactors
            ff = FuturesFactors()
            futures_data = ff.fetch_all()
            futures_score = futures_data.get("combined_score", 0.0)
            logger.info(f"Futures: score={futures_score:+.2f}, signal={futures_data.get('signal', '?')}")
        except ImportError:
            logger.debug("futures_factors not available")
        except Exception as e:
            logger.warning(f"Futures factors failed: {e}")

        # 5e. Deribit Options factors (put/call ratio, volatility)
        options_score = 0.0
        options_data = {}
        try:
            from options_factors import OptionsFactors
            of = OptionsFactors()
            options_data = of.fetch_all()
            options_score = options_data.get("combined_score", 0.0)
            logger.info(f"Options: score={options_score:+.2f}, P/C={options_data.get('put_call',{}).get('ratio',0):.2f}")
        except ImportError:
            logger.debug("options_factors not available")
        except Exception as e:
            logger.warning(f"Options factors failed: {e}")

        # 5f. Capital flow factors (stablecoin supply + ETF flows)
        flow_score = 0.0
        flow_data = {}
        try:
            from flow_factors import fetch_all_flows
            flow_data = fetch_all_flows()
            flow_score = flow_data.get("combined_score", 0.0)
            logger.info(f"Flows: score={flow_score:+.2f}, signal={flow_data.get('signal', '?')}")
        except ImportError:
            logger.debug("flow_factors not available")
        except Exception as e:
            logger.warning(f"Flow factors failed: {e}")

        # 5g. On-chain + cross-market factors
        onchain_score = 0.0
        onchain_data = {}
        try:
            from onchain_macro_factors import fetch_all_onchain_macro
            onchain_data = fetch_all_onchain_macro()
            onchain_score = onchain_data.get("combined_score", 0.0)
            logger.info(f"OnChain+Macro: score={onchain_score:+.2f}")
        except ImportError:
            logger.debug("onchain_macro_factors not available")
        except Exception as e:
            logger.warning(f"OnChain+Macro failed: {e}")

        # 5h. Santiment on-chain + social (exchange flows, social volume, dev activity)
        santiment_score = 0.0
        santiment_data = {}
        try:
            from santiment_factors import SantimentFactors
            sf = SantimentFactors()
            santiment_data = sf.fetch_all()
            santiment_score = santiment_data.get("combined_score", 0.0)
            logger.info(f"Santiment: score={santiment_score:+.2f}")
        except ImportError:
            logger.debug("santiment_factors not available")
        except Exception as e:
            logger.warning(f"Santiment failed: {e}")

        # 5i. BTC Cycle-specific factors (halving, MVRV, Pi Cycle, 200W MA)
        btc_cycle_score = 0.0
        btc_cycle_data = {}
        try:
            from btc_cycle_factors import BTCCycleFactors
            import requests as _req
            bf = BTCCycleFactors()
            # Get BTC price data for technical indicators
            _r1 = _req.get("https://api.binance.com/api/v3/klines",
                params={"symbol": "BTCUSDT", "interval": "1d", "limit": 400}, timeout=15)
            _closes_d = [float(k[4]) for k in _r1.json()]
            _r2 = _req.get("https://api.binance.com/api/v3/klines",
                params={"symbol": "BTCUSDT", "interval": "1w", "limit": 250}, timeout=15)
            _closes_w = [float(k[4]) for k in _r2.json()]
            btc_cycle_data = bf.fetch_all(_closes_d, _closes_w, _closes_d[-1])
            btc_cycle_score = btc_cycle_data.get("combined_score", 0.0)
            logger.info(f"BTC Cycle: score={btc_cycle_score:+.2f}, signal={btc_cycle_data.get('signal', '?')}")
        except ImportError:
            logger.debug("btc_cycle_factors not available")
        except Exception as e:
            logger.warning(f"BTC Cycle factors failed: {e}")

        # 5j. KOL Tracker (Trump, Musk, Saylor, BlackRock, Fed, SEC)
        kol_score = 0.0
        kol_data = {}
        try:
            from kol_tracker import KOLTracker
            tracker = KOLTracker()
            kol_data = tracker.run(extra_headlines=all_headlines)
            kol_score = kol_data.get("score", 0.0)
            logger.info(
                f"KOL Tracker: score={kol_score:.2f}, "
                f"mentions={kol_data.get('mention_count', 0)}, "
                f"alert={kol_data.get('alert_level', 'none')}"
            )
        except ImportError:
            logger.debug("kol_tracker not available")
        except Exception as e:
            logger.warning(f"KOL tracker failed: {e}")

        # 5e. LLM Signal — Claude analyzes everything and gives direction
        llm_signal_data = {}
        try:
            from llm_signal import LLMSignalEngine
            engine = LLMSignalEngine()
            top_headlines = [h["title"] for h in new_headlines[:20]] or [h["title"] for h in all_headlines[:20]]
            # Pass ALL structural data to LLM for contrarian analysis
            llm_market_data = {
                "btc_price": ext_data.get("sources", {}).get("coingecko", {}).get("data", {}).get("btc_price", 0),
                "btc_24h": ext_data.get("sources", {}).get("coingecko", {}).get("data", {}).get("btc_24h_change", 0),
                "fng_value": fng["value"],
                "fng_classification": fng["classification"],
                "tvl_week_chg": ext_data.get("sources", {}).get("defillama", {}).get("data", {}).get("tvl_week_change_pct", 0),
                # Structural data for contrarian reasoning
                "mvrv": btc_cycle_data.get("factors", {}).get("mvrv", {}).get("value"),
                "power_law_ratio": btc_cycle_data.get("factors", {}).get("power_law", {}).get("ratio"),
                "halving_phase": btc_cycle_data.get("factors", {}).get("halving", {}).get("phase"),
                "halving_position": btc_cycle_data.get("factors", {}).get("halving", {}).get("position"),
                "futures_funding": futures_data.get("funding", {}).get("rate"),
                "futures_ls_ratio": futures_data.get("long_short", {}).get("retail_ratio"),
            }
            llm_signal_data = engine.analyze(
                headlines=top_headlines,
                kol_mentions=kol_data.get("kol_mentions", []),
                market_data=llm_market_data,
            )
            logger.info(
                f"LLM Signal: {llm_signal_data.get('signal', '?')} "
                f"({llm_signal_data.get('confidence', 0):.0%}) "
                f"action={llm_signal_data.get('action', '?')}"
            )
        except ImportError:
            logger.debug("llm_signal not available")
        except Exception as e:
            logger.warning(f"LLM signal failed: {e}")

        # 6. Combined score: weighted average of all signals
        # FnG normalized to [-1, 1]
        fng_normalized = (fng["value"] - 50) / 50  # 0→-1, 50→0, 100→1

        # Build weighted components — KOL gets highest weight when active
        components = [("fng", fng_normalized, 0.20)]

        if llm_scores:
            components.append(("llm_news", llm_sentiment, 0.10))
        components.append(("kw_news", keyword_sentiment, 0.10))

        if zyte_score != 0:
            components.append(("reddit", zyte_score, 0.10))
        if ext_score != 0:
            components.append(("external", ext_score, 0.15))
        if kol_score != 0:
            components.append(("kol", kol_score, 0.25))
        if futures_score != 0:
            components.append(("futures", futures_score, 0.20))
        if options_score != 0:
            components.append(("options", options_score, 0.05))
        if flow_score != 0:
            components.append(("flows", flow_score, 0.10))
        if onchain_score != 0:
            components.append(("onchain_macro", onchain_score, 0.05))
        if santiment_score != 0:
            components.append(("santiment", santiment_score, 0.08))
        if btc_cycle_score != 0:
            components.append(("btc_cycle", btc_cycle_score, 0.12))

        total_weight = sum(w for _, _, w in components)
        combined = sum(v * w for _, v, w in components) / total_weight

        combined = max(-1.0, min(1.0, combined))

        # Signal
        if combined > 0.3:
            signal = "bullish"
        elif combined < -0.3:
            signal = "bearish"
        else:
            signal = "neutral"

        snapshot = {
            "timestamp": now,
            "fng_value": fng["value"],
            "fng_classification": fng["classification"],
            "keyword_sentiment": round(keyword_sentiment, 3),
            "llm_sentiment": round(llm_sentiment, 3),
            "zyte_score": round(zyte_score, 3),
            "combined_score": round(combined, 3),
            "signal": signal,
            "headline_count": len(all_headlines),
            "new_headline_count": len(new_headlines),
            "reddit_sentiment": zyte_data.get("reddit", {}).get("sentiment_score", 0),
            "trending_coins": [
                c["symbol"] for c in zyte_data.get("trending", {}).get("trending_coins", [])[:5]
            ],
            "whale_flow": zyte_data.get("whales", {}).get("net_exchange_flow", "unknown"),
            "ext_score": round(ext_score, 3),
            "ext_cryptopanic": ext_data.get("sources", {}).get("cryptopanic", {}).get("score", 0),
            "ext_glassnode": ext_data.get("sources", {}).get("glassnode", {}).get("score", 0),
            "ext_twitter": ext_data.get("sources", {}).get("twitter", {}).get("score", 0),
            "ext_mvrv": ext_data.get("sources", {}).get("glassnode", {}).get("data", {}).get("mvrv"),
            "kol_score": round(kol_score, 3),
            "kol_mentions": kol_data.get("mention_count", 0),
            "kol_alert": kol_data.get("alert_level", "none"),
            "kol_top": [
                f"{m['kol']}:{m['sentiment']}" for m in kol_data.get("kol_mentions", [])
                if abs(m.get("score", 0)) > 0.3
            ][:5],
            "llm_signal": llm_signal_data.get("signal", "neutral"),
            "llm_confidence": llm_signal_data.get("confidence", 0),
            "llm_action": llm_signal_data.get("action", "hold"),
            "llm_reasoning": llm_signal_data.get("reasoning", "")[:200],
            "llm_key_factors": llm_signal_data.get("key_factors", []),
            "llm_contrarian": llm_signal_data.get("contrarian_flag", False),
            "llm_crowd": llm_signal_data.get("crowd_sentiment", "neutral"),
            "llm_unanimity": llm_signal_data.get("unanimity_pct", 0),
            "futures_score": round(futures_score, 3),
            "futures_funding": futures_data.get("funding", {}).get("rate", 0),
            "futures_oi_change": futures_data.get("open_interest", {}).get("oi_change_7d", 0),
            "futures_ls_ratio": futures_data.get("long_short", {}).get("retail_ratio", 0),
            "futures_taker": futures_data.get("taker", {}).get("ratio", 0),
            "options_score": round(options_score, 3),
            "options_pc_ratio": options_data.get("put_call", {}).get("ratio", 0),
            "options_hv": options_data.get("volatility", {}).get("hv", 0),
            "flow_score": round(flow_score, 3),
            "stablecoin_week_chg": flow_data.get("stablecoin", {}).get("avg_week_change_pct", 0),
            "etf_inflow_mentions": flow_data.get("etf", {}).get("inflow_mentions", 0),
            "etf_outflow_mentions": flow_data.get("etf", {}).get("outflow_mentions", 0),
            "onchain_score": round(onchain_score, 3),
            "btc_nasdaq_corr": onchain_data.get("cross_market", {}).get("correlations", {}).get("nasdaq", 0),
            "btc_tx_24h": onchain_data.get("onchain", {}).get("network", {}).get("tx_24h", 0),
            "miner_hr_change": onchain_data.get("onchain", {}).get("miner", {}).get("hashrate_change_2w", 0),
            "santiment_score": round(santiment_score, 3),
            "santiment_exchange_net": santiment_data.get("exchange_flows", {}).get("net_ratio", 0),
            "santiment_social_vol": santiment_data.get("social_volume", {}).get("recent_avg", 0),
            "btc_cycle_score": round(btc_cycle_score, 3),
            "btc_halving_phase": btc_cycle_data.get("factors", {}).get("halving", {}).get("phase", "unknown"),
            "btc_halving_position": btc_cycle_data.get("factors", {}).get("halving", {}).get("position", 0),
            "btc_mvrv": btc_cycle_data.get("factors", {}).get("mvrv", {}).get("value", 0),
            "btc_realized_price": btc_cycle_data.get("factors", {}).get("realized_price", {}).get("value", 0),
            "btc_pi_cycle_triggered": btc_cycle_data.get("factors", {}).get("pi_cycle", {}).get("triggered", False),
            "btc_200w_ma_dist": btc_cycle_data.get("factors", {}).get("200w_ma", {}).get("distance_pct", 0),
        }

        # 7. Save snapshot
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO sentiment_snapshots
                (timestamp, fng_value, fng_classification, keyword_sentiment,
                 llm_sentiment, combined_score, signal, headline_count, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (now, fng["value"], fng["classification"], keyword_sentiment,
                 llm_sentiment, combined, signal, len(all_headlines),
                 json.dumps(snapshot)),
            )

        # 8. Save latest to JSON (for freqtrade to read)
        latest_path = DATA_DIR / "latest_sentiment.json"
        with open(latest_path, "w") as f:
            json.dump(snapshot, f, indent=2)

        # 9. Push to Supabase (shared database for all platforms)
        try:
            from sentiment_db import SentimentDB
            db = SentimentDB()
            if db.available:
                db.push_snapshot(snapshot, source="local")
                db.push_kol_events(kol_data.get("kol_mentions", []))
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"Supabase push failed: {e}")

        logger.info(
            f"=== Pipeline complete === "
            f"Combined: {combined:.2f} ({signal}) | "
            f"FnG: {fng['value']} | KW: {keyword_sentiment:.2f} | "
            f"LLM: {llm_sentiment:.2f}"
        )

        return snapshot

    def get_latest_report(self) -> str:
        """Human-readable report of latest sentiment."""
        try:
            latest_path = DATA_DIR / "latest_sentiment.json"
            with open(latest_path) as f:
                s = json.loads(f.read())
        except FileNotFoundError:
            return "No sentiment data available. Run pipeline first."

        bars = "█" * int(abs(s["combined_score"]) * 20)
        direction = "📈" if s["combined_score"] > 0 else "📉" if s["combined_score"] < 0 else "➡️"

        trending = ", ".join(s.get("trending_coins", [])) or "n/a"
        whale = s.get("whale_flow", "n/a")
        reddit = s.get("reddit_sentiment", 0)
        zyte = s.get("zyte_score", 0)

        return f"""
╔════════════════════════════════════════════╗
║       Crypto Sentiment Dashboard          ║
╠════════════════════════════════════════════╣
║ Time:       {s['timestamp'][:19]}         ║
║ Signal:     {direction} {s['signal'].upper():10s}                 ║
║ Score:      {s['combined_score']:+.2f} {bars:20s}     ║
╠════════════════════════════════════════════╣
║ Fear & Greed:   {s['fng_value']:3d} ({s['fng_classification']:15s})    ║
║ News (KW):      {s['keyword_sentiment']:+.2f}                        ║
║ News (LLM):     {s['llm_sentiment']:+.2f}                        ║
║ Reddit:         {reddit:+.2f}                        ║
║ Zyte combined:  {zyte:+.2f}                        ║
║ Whale flow:     {whale:15s}                ║
║ Trending:       {trending:27s} ║
║ Headlines:      {s['headline_count']:3d} ({s['new_headline_count']} new)                ║
╚════════════════════════════════════════════╝
"""

    def get_history(self, hours: int = 24) -> list[dict]:
        """Get sentiment history for the last N hours."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("""
                SELECT timestamp, combined_score, signal, fng_value
                FROM sentiment_snapshots
                ORDER BY id DESC
                LIMIT ?
            """, (hours,)).fetchall()
        return [
            {"timestamp": r[0], "score": r[1], "signal": r[2], "fng": r[3]}
            for r in rows
        ]


# ---------------------------------------------------------------------------
# CLI entry point — run from cron / scheduled notebook
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Crypto News Sentiment Pipeline")
    parser.add_argument("--api-key", help="Anthropic API key for LLM analysis")
    parser.add_argument("--report", action="store_true", help="Show latest report")
    args = parser.parse_args()

    pipeline = NewsPipeline(anthropic_api_key=args.api_key)

    if args.report:
        print(pipeline.get_latest_report())
    else:
        result = pipeline.run()
        print(pipeline.get_latest_report())
