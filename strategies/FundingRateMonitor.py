"""
FundingRateMonitor — Perpetual funding rate daemon for BTC and ETH.

Background daemon that polls Binance Futures funding rates every 15 minutes,
annualizes the rate, and writes signal rows into the TimescaleDB table
``quant.event_dca_triggers`` when thresholds are crossed. These signals are
picked up by the dashboard's /signals feed.

Signal types:
  FUNDING_HIGH   funding_rate_apr  > FUNDING_HIGH_APR_THRESHOLD (default 50%)
                 Very high cost for longs; longs may unwind → bearish short-term.
  FUNDING_NEG    funding_rate_apr  < FUNDING_NEG_APR_THRESHOLD  (default -10%)
                 Shorts paying longs; rare → historically bullish signal.

Annualisation:
  funding_rate_apr = latest_rate × 3 × 365
  (Binance perpetuals settle every 8 h → 3 settlements per day × 365 days)

Cooldown: 12 h between same-type, same-symbol writes to avoid duplicate rows.

Usage:
  sops exec-env secrets.env 'python strategies/FundingRateMonitor.py'
  sops exec-env secrets.env 'python strategies/FundingRateMonitor.py --self-test'

Environment variables:
  TIMESCALE_URL                 required  psycopg2 DSN or postgres:// URL
  FUNDING_POLL_INTERVAL         seconds between polls (default 900 = 15 min)
  FUNDING_HIGH_APR_THRESHOLD    float, default 0.5  (= 50 % annualised)
  FUNDING_NEG_APR_THRESHOLD     float, default -0.10 (= -10 % annualised)
"""
from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import psycopg2
import psycopg2.extras
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("funding_monitor")

# ---------------------------------------------------------------------------
# Config from environment
# ---------------------------------------------------------------------------
TIMESCALE_URL: str = os.environ.get("TIMESCALE_URL", "")
POLL_INTERVAL: int = int(os.environ.get("FUNDING_POLL_INTERVAL", "900"))
HIGH_APR_THRESHOLD: float = float(os.environ.get("FUNDING_HIGH_APR_THRESHOLD", "0.5"))
NEG_APR_THRESHOLD: float = float(os.environ.get("FUNDING_NEG_APR_THRESHOLD", "-0.10"))

COOLDOWN_SECONDS: int = 12 * 3600  # 12 h between same-kind + same-symbol inserts

# Symbols to monitor (Binance Futures notation)
SYMBOLS = ["BTCUSDT", "ETHUSDT"]

# Binance Futures REST
BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"

# Timescale schema / table
SCHEMA = os.environ.get("TIMESCALE_SCHEMA", "quant")
TABLE = f"{SCHEMA}.event_dca_triggers"


# ---------------------------------------------------------------------------
# Funding rate fetcher
# ---------------------------------------------------------------------------

def fetch_latest_funding_rate(symbol: str) -> Optional[float]:
    """
    Fetch the most recent funding rate for *symbol* from Binance Futures.

    :param symbol: e.g. ``"BTCUSDT"``
    :return: raw funding rate float (e.g. 0.0001), or None on error.
    """
    try:
        resp = requests.get(
            BINANCE_FUNDING_URL,
            params={"symbol": symbol, "limit": 1},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data:
            logger.warning(f"Empty funding rate response for {symbol}")
            return None
        return float(data[0]["fundingRate"])
    except Exception as exc:
        logger.warning(f"Failed to fetch funding rate for {symbol}: {exc}")
        return None


def fetch_current_price(symbol: str) -> Optional[float]:
    """
    Fetch the current mark price for *symbol* from Binance Futures.

    :param symbol: e.g. ``"BTCUSDT"``
    :return: mark price float or None on error.
    """
    try:
        resp = requests.get(
            "https://fapi.binance.com/fapi/v1/premiumIndex",
            params={"symbol": symbol},
            timeout=10,
        )
        resp.raise_for_status()
        return float(resp.json()["markPrice"])
    except Exception as exc:
        logger.warning(f"Failed to fetch mark price for {symbol}: {exc}")
        return None


def annualize(rate: float) -> float:
    """
    Annualise a single Binance 8-h funding rate to APR.

    :param rate: raw per-period funding rate (e.g. 0.0001)
    :return: APR as a decimal (e.g. 0.1095 = ~10.95 %)
    """
    return rate * 3 * 365


# ---------------------------------------------------------------------------
# Cooldown tracker (in-process dict; restarts reset it — acceptable for daemon)
# ---------------------------------------------------------------------------

_last_written: dict[tuple[str, str], float] = {}


def _is_on_cooldown(symbol: str, kind: str, now: float) -> bool:
    key = (symbol, kind)
    last = _last_written.get(key, 0.0)
    return (now - last) < COOLDOWN_SECONDS


def _mark_written(symbol: str, kind: str, now: float) -> None:
    _last_written[(symbol, kind)] = now


# ---------------------------------------------------------------------------
# Database writer
# ---------------------------------------------------------------------------

def _connect() -> psycopg2.extensions.connection:
    if not TIMESCALE_URL:
        raise RuntimeError("TIMESCALE_URL is not set")
    return psycopg2.connect(TIMESCALE_URL)


def write_signal(
    ts: datetime,
    symbol: str,
    kind: str,
    apr: float,
    price: float,
) -> None:
    """
    Insert one funding signal row into ``quant.event_dca_triggers``.

    :param ts:     UTC timestamp of the signal
    :param symbol: e.g. "BTCUSDT"
    :param kind:   "FUNDING_HIGH" or "FUNDING_NEG"
    :param apr:    annualised funding rate (decimal)
    :param price:  mark price at time of signal
    """
    severity = abs(apr)
    mode = "funding_monitor"
    logger.info(
        f"Writing signal {kind} for {symbol}  APR={apr:+.1%}  price={price:,.0f}"
    )
    try:
        conn = _connect()
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {TABLE}
                  (ts, kind, price, severity, fng, amount_usdt, mode)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ts) DO NOTHING
                """,
                (ts, f"{kind}:{symbol}", price, severity, None, 0.0, mode),
            )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.error(f"DB write failed for {kind}/{symbol}: {exc}")


# ---------------------------------------------------------------------------
# Core poll logic
# ---------------------------------------------------------------------------

def poll_once(dry_run: bool = False) -> list[dict]:
    """
    Poll all symbols once, evaluate thresholds, write signals if triggered.

    :param dry_run: if True, log what would be written but do not write to DB.
    :return: list of triggered event dicts (for self-test output / logging).
    """
    now = datetime.now(timezone.utc)
    now_ts = now.timestamp()
    triggered: list[dict] = []

    for symbol in SYMBOLS:
        rate = fetch_latest_funding_rate(symbol)
        if rate is None:
            continue
        apr = annualize(rate)
        price = fetch_current_price(symbol) or 0.0

        logger.info(
            f"{symbol}  rate={rate:+.6f}  APR={apr:+.1%}  price={price:,.2f}"
        )

        kind: Optional[str] = None
        if apr > HIGH_APR_THRESHOLD:
            kind = "FUNDING_HIGH"
        elif apr < NEG_APR_THRESHOLD:
            kind = "FUNDING_NEG"

        if kind is None:
            continue

        if _is_on_cooldown(symbol, kind, now_ts):
            remaining_h = (
                COOLDOWN_SECONDS - (now_ts - _last_written.get((symbol, kind), 0))
            ) / 3600
            logger.info(
                f"COOLDOWN: {kind}/{symbol} — {remaining_h:.1f}h until next write"
            )
            continue

        event = {
            "ts": now.isoformat(),
            "symbol": symbol,
            "kind": kind,
            "apr": apr,
            "price": price,
        }
        triggered.append(event)

        if dry_run:
            logger.info(f"[DRY-RUN] would write: {event}")
        else:
            write_signal(now, symbol, kind, apr, price)
            _mark_written(symbol, kind, now_ts)

    return triggered


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def self_test() -> None:
    """Print current funding rates and threshold evaluation, then exit."""
    print("=== FundingRateMonitor self-test ===")
    print(f"TIMESCALE_URL:           {'SET' if TIMESCALE_URL else 'NOT SET'}")
    print(f"POLL_INTERVAL:           {POLL_INTERVAL}s")
    print(f"FUNDING_HIGH_APR:        APR > {HIGH_APR_THRESHOLD:+.1%}")
    print(f"FUNDING_NEG_APR:         APR < {NEG_APR_THRESHOLD:+.1%}")
    print(f"COOLDOWN:                {COOLDOWN_SECONDS // 3600}h")
    print()

    for symbol in SYMBOLS:
        rate = fetch_latest_funding_rate(symbol)
        price = fetch_current_price(symbol)
        if rate is None:
            print(f"  {symbol}: fetch failed")
            continue
        apr = annualize(rate)
        print(f"  {symbol}:")
        print(f"    raw_rate = {rate:+.8f}")
        print(f"    APR      = {apr:+.2%}")
        print(f"    price    = {price:,.2f}" if price else "    price    = N/A")

        if apr > HIGH_APR_THRESHOLD:
            print(f"    --> WOULD TRIGGER FUNDING_HIGH  (APR {apr:+.1%} > {HIGH_APR_THRESHOLD:+.1%})")
        elif apr < NEG_APR_THRESHOLD:
            print(f"    --> WOULD TRIGGER FUNDING_NEG   (APR {apr:+.1%} < {NEG_APR_THRESHOLD:+.1%})")
        else:
            print(f"    --> no trigger")
        print()


# ---------------------------------------------------------------------------
# Main daemon loop
# ---------------------------------------------------------------------------

def run_daemon() -> None:
    """Run the polling daemon indefinitely."""
    logger.info(
        f"FundingRateMonitor starting  "
        f"poll={POLL_INTERVAL}s  "
        f"high={HIGH_APR_THRESHOLD:+.1%}  "
        f"neg={NEG_APR_THRESHOLD:+.1%}  "
        f"cooldown={COOLDOWN_SECONDS // 3600}h"
    )
    if not TIMESCALE_URL:
        logger.error("TIMESCALE_URL is not set — signals cannot be written. Exiting.")
        return

    while True:
        try:
            triggered = poll_once()
            if triggered:
                logger.warning(
                    f"Signals written: {[e['kind'] + '/' + e['symbol'] for e in triggered]}"
                )
        except Exception as exc:
            logger.error(f"Unhandled error in poll loop: {exc}")

        logger.debug(f"Sleeping {POLL_INTERVAL}s until next poll")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Binance perpetual funding rate monitor — writes signals to TimescaleDB"
    )
    ap.add_argument(
        "--self-test",
        action="store_true",
        help="Print current rates and threshold evaluation, then exit.",
    )
    args = ap.parse_args()

    if args.self_test:
        self_test()
    else:
        try:
            run_daemon()
        except KeyboardInterrupt:
            logger.info("FundingRateMonitor stopped by user")
