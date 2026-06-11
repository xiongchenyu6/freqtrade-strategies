"""Collects the /market dashboard's upstream data into quant.market_snapshots.

Binance blocks Cloudflare Workers egress AND mainland-CN browsers, so the dashboard
cannot fetch api.binance.com / fapi.binance.com itself. This box can. Every run grabs
the RAW payloads the web's marketData.ts needs (weekly klines, funding, OI, FNG,
long/short + taker ratios) per asset and upserts one jsonb doc per asset; the web app
computes its indicators from OUR API instead of the blocked origins.

Runs via quant-market-collector.timer (every 30 min). Read-only public endpoints, no keys.
Env: TIMESCALE_URL (sops).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import psycopg2
import requests

ASSETS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}


def log(m: str) -> None:
    print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {m}", flush=True)


def get(url: str):
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.json()


def collect(symbol: str) -> dict:
    """Raw upstream payloads, keys mirror what web/marketData.ts consumes."""
    out: dict = {}
    sources = {
        "klines_1w": f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1w&limit=220",
        "funding": f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&limit=7",
        "open_interest": f"https://fapi.binance.com/fapi/v1/openInterest?symbol={symbol}",
        "long_short": f"https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol={symbol}&period=1h&limit=48",
        "taker_ratio": f"https://fapi.binance.com/futures/data/takerlongshortRatio?symbol={symbol}&period=1h&limit=48",
        "top_long_short": f"https://fapi.binance.com/futures/data/topLongShortAccountRatio?symbol={symbol}&period=1h&limit=1",
    }
    for key, url in sources.items():
        try:
            out[key] = get(url)
        except Exception as e:
            log(f"{symbol} {key} failed: {e!r}")
            out[key] = None
    try:
        out["fng"] = get("https://api.alternative.me/fng/?limit=30")
    except Exception as e:
        log(f"fng failed: {e!r}")
        out["fng"] = None
    return out


def main() -> int:
    dsn = os.environ.get("TIMESCALE_URL", "")
    if not dsn:
        print("TIMESCALE_URL required", file=sys.stderr)
        return 2
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    ok = 0
    for asset, symbol in ASSETS.items():
        payload = collect(symbol)
        # Require at least the weekly klines (the page's backbone) to overwrite.
        if not payload.get("klines_1w"):
            log(f"{asset}: klines missing — keeping previous snapshot")
            continue
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO quant.market_snapshots (asset, ts, payload)
                   VALUES (%s, now(), %s)
                   ON CONFLICT (asset) DO UPDATE SET ts = now(), payload = EXCLUDED.payload""",
                (asset, json.dumps(payload)),
            )
        ok += 1
        log(f"{asset}: snapshot stored ({len(json.dumps(payload))} bytes)")
    conn.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
