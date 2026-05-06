"""
Build Historical Sentiment Dataset

Fetches historical news headlines via Google News RSS (date-filtered),
runs them through Claude LLM for sentiment analysis, and produces a
daily sentiment CSV for backtesting.

Output: data/historical_sentiment.csv
    date, fng, llm_signal, llm_confidence, llm_action, kol_score, headline_count

Usage:
    python build_historical_sentiment.py --start 2023-01-01 --end 2026-04-01
"""

import csv
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("hist_sentiment")

ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DATA_DIR = Path(__file__).parent.parent / "data"

# Historical FnG
FNG_DATA = {}
_fng_path = DATA_DIR / "fng_history.csv"
if _fng_path.exists():
    with open(_fng_path) as f:
        for row in csv.DictReader(f):
            FNG_DATA[row["date"]] = int(row["value"])


# KOL names for detection
KOLS = ["trump", "musk", "elon", "saylor", "microstrategy", "blackrock",
        "sec", "gensler", "powell", "federal reserve", "cathie wood"]


def fetch_google_news_for_date(date_str: str) -> list[str]:
    """Fetch crypto news headlines from Google News for a specific date range."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    after = (dt - timedelta(days=1)).strftime("%Y-%m-%d")
    before = (dt + timedelta(days=1)).strftime("%Y-%m-%d")

    queries = [
        f"bitcoin OR crypto after:{after} before:{before}",
        f"bitcoin etf OR regulation after:{after} before:{before}",
    ]

    headlines = []
    for q in queries:
        try:
            url = f"https://news.google.com/rss/search?q={q.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en"
            resp = requests.get(url, timeout=15, headers={"User-Agent": "CryptoBot/1.0"})
            if resp.status_code != 200:
                continue
            root = ElementTree.fromstring(resp.content)
            for item in root.findall(".//item")[:15]:
                t = item.find("title")
                if t is not None and t.text:
                    headlines.append(t.text.strip())
            time.sleep(0.3)
        except Exception as e:
            logger.debug(f"Google News failed for {date_str}: {e}")

    return list(set(headlines))  # deduplicate


def detect_kol_mentions(headlines: list[str]) -> tuple[int, float]:
    """Count KOL mentions and compute simple score."""
    mentions = 0
    bull = bear = 0
    BULL_KW = ["buy", "support", "approve", "adopt", "bullish", "inflow", "reserve", "etf"]
    BEAR_KW = ["ban", "crash", "sue", "hack", "dump", "bearish", "outflow", "fraud"]

    for h in headlines:
        hl = h.lower()
        for kol in KOLS:
            if kol in hl:
                mentions += 1
                bull += sum(1 for k in BULL_KW if k in hl)
                bear += sum(1 for k in BEAR_KW if k in hl)
                break

    total = bull + bear
    score = (bull - bear) / total if total > 0 else 0.0
    return mentions, round(score, 3)


def _get_btc_price_for_date(date_str: str) -> float:
    """Get approximate BTC price for a historical date from local data."""
    try:
        import pandas as pd
        df = pd.read_feather(DATA_DIR / "binance" / "BTC_USDT-1d.feather")
        row = df[df["date"].dt.strftime("%Y-%m-%d") == date_str]
        if len(row) > 0:
            return float(row.iloc[0]["close"])
    except Exception:
        pass
    return 0


def _compute_mvrv_proxy(date_str: str) -> float:
    """Compute MVRV proxy (price / 365d avg) for a historical date."""
    try:
        import pandas as pd
        df = pd.read_feather(DATA_DIR / "binance" / "BTC_USDT-1d.feather")
        df["date_str"] = df["date"].dt.strftime("%Y-%m-%d")
        idx = df[df["date_str"] == date_str].index
        if len(idx) > 0 and idx[0] >= 365:
            i = idx[0]
            avg_365 = df["close"].iloc[i-365:i].mean()
            if avg_365 > 0:
                return float(df["close"].iloc[i] / avg_365)
    except Exception:
        pass
    return 1.0


def llm_analyze_day(date_str: str, headlines: list[str], fng: int) -> dict:
    """Use contrarian Claude to analyze a day's headlines."""
    if not ANTHROPIC_API_KEY or not headlines:
        return {"signal": "neutral", "confidence": 0, "action": "hold"}

    hl_text = "\n".join(f"- {h[:120]}" for h in headlines[:20])

    # Compute structural context
    btc_price = _get_btc_price_for_date(date_str)
    mvrv = _compute_mvrv_proxy(date_str)

    # Unanimity detection
    bull_kw = ["surge", "rally", "bull", "soar", "breakout", "ath", "record", "buy", "inflow"]
    bear_kw = ["crash", "plunge", "dump", "bear", "fear", "sell", "ban", "fraud", "hack"]
    bull_c = sum(1 for h in headlines for k in bull_kw if k in h.lower())
    bear_c = sum(1 for h in headlines for k in bear_kw if k in h.lower())
    total_c = bull_c + bear_c
    unanimity = abs(bull_c - bear_c) / total_c * 100 if total_c > 0 else 0
    dominant = "bullish" if bull_c > bear_c else "bearish" if bear_c > bull_c else "mixed"

    structural_ctx = ""
    if btc_price > 0:
        structural_ctx += f"\nBTC Price: ${btc_price:,.0f}"
    if mvrv != 1.0:
        structural_ctx += f"\nMVRV proxy: {mvrv:.2f} (>3.0=cycle top danger, <0.7=deep value)"
    structural_ctx += f"\nSentiment unanimity: {unanimity:.0f}% {dominant} ({bull_c} bull vs {bear_c} bear keywords)"

    prompt = f"""You are an elite CONTRARIAN crypto trader analyzing {date_str}.

Fear & Greed: {fng}
{structural_ctx}

Headlines:
{hl_text}

RULES (contrarian ONLY at extremes, follow trend in the middle):
- FnG > 80 → MUST say sell or hold. Euphoria = top. No exceptions.
- FnG 70-80 → cautious. Prefer hold over buy.
- FnG 30-70 → NORMAL. Follow the trend. If bullish, say buy. Don't overthink.
- FnG 20-30 → optimistic. Look for buy despite scary news.
- FnG < 20 → MUST say buy or strong_buy. Max panic = max opportunity.
- MVRV > 3.0 → cycle top → SELL regardless of news.
- MVRV < 0.7 → deep value → BUY regardless of news.
- Only set contrarian=true when your signal OPPOSES the majority of headlines AND FnG is extreme.

Respond ONLY with JSON:
{{"signal":"long" or "short" or "neutral","confidence":0.0 to 1.0,"action":"strong_buy" or "buy" or "hold" or "reduce" or "sell","contrarian":true or false}}"""

    try:
        resp = requests.post(
            f"{ANTHROPIC_BASE_URL}/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-5-20241022",
                "max_tokens": 100,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()["content"][0]["text"]
        match = re.search(r'\{[^}]+\}', raw)
        if match:
            return json.loads(match.group())
    except Exception as e:
        logger.warning(f"LLM failed for {date_str}: {e}")

    return {"signal": "neutral", "confidence": 0, "action": "hold", "contrarian": False}


def build_dataset(start_date: str, end_date: str, batch_days: int = 7):
    """
    Build historical sentiment dataset.
    Processes in weekly batches to reduce API calls.
    """
    output_path = DATA_DIR / "historical_sentiment.csv"

    # Load existing data to resume
    existing_dates = set()
    existing_rows = []
    if output_path.exists():
        with open(output_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_dates.add(row["date"])
                existing_rows.append(row)
        logger.info(f"Loaded {len(existing_dates)} existing dates, resuming...")

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    # Process week by week
    current = start
    new_rows = []
    batch_headlines = []
    batch_dates = []

    while current < end:
        date_str = current.strftime("%Y-%m-%d")

        if date_str in existing_dates:
            current += timedelta(days=1)
            continue

        fng = FNG_DATA.get(date_str, 50)

        # Fetch headlines for this day
        headlines = fetch_google_news_for_date(date_str)
        kol_mentions, kol_score = detect_kol_mentions(headlines)

        batch_headlines.append((date_str, headlines, fng))
        batch_dates.append(date_str)

        # Process batch every N days or at end
        if len(batch_headlines) >= batch_days or current + timedelta(days=1) >= end:
            logger.info(f"Processing batch: {batch_dates[0]} to {batch_dates[-1]} ({len(batch_headlines)} days)")

            for date_str, headlines, fng in batch_headlines:
                kol_mentions, kol_score = detect_kol_mentions(headlines)

                # LLM analysis
                llm = llm_analyze_day(date_str, headlines, fng)
                time.sleep(0.5)  # rate limit

                contrarian = llm.get("contrarian", False)
                row = {
                    "date": date_str,
                    "fng": fng,
                    "llm_signal": llm.get("signal", "neutral"),
                    "llm_confidence": llm.get("confidence", 0),
                    "llm_action": llm.get("action", "hold"),
                    "llm_contrarian": 1 if contrarian else 0,
                    "kol_mentions": kol_mentions,
                    "kol_score": kol_score,
                    "headline_count": len(headlines),
                }
                new_rows.append(row)
                c_flag = " CONTRARIAN" if contrarian else ""
                logger.info(
                    f"  {date_str}: FnG={fng} LLM={llm.get('signal','?')} "
                    f"({llm.get('confidence',0):.0%}) {llm.get('action','?')}{c_flag} KOL={kol_mentions}"
                )

            batch_headlines = []
            batch_dates = []

            # Save progress after each batch
            all_rows = existing_rows + new_rows
            all_rows.sort(key=lambda x: x["date"])
            with open(output_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "date", "fng", "llm_signal", "llm_confidence", "llm_action",
                    "llm_contrarian", "kol_mentions", "kol_score", "headline_count",
                ])
                writer.writeheader()
                writer.writerows(all_rows)
            logger.info(f"  Saved {len(all_rows)} total rows to {output_path}")

        current += timedelta(days=1)

    total = len(existing_rows) + len(new_rows)
    logger.info(f"Done! {total} days of sentiment data saved to {output_path}")
    return output_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2023-01-01")
    parser.add_argument("--end", default="2026-04-01")
    parser.add_argument("--batch", type=int, default=7)
    args = parser.parse_args()

    build_dataset(args.start, args.end, args.batch)
