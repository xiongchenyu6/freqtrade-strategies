"""Standalone Binance OHLCV downloader (ccxt) — the freqtrade-free replacement for
`freqtrade download-data`. Writes the same feather layout Nautilus backtests read:
user_data/data/binance/<BASE>_<QUOTE>-<TF>.feather with columns date,open,high,low,close,volume.

Usage:
  python download_binance.py BTC/USDT ETH/USDT --timeframes 1h 1d --since 2017-08-01
Runs on .venv-bots (ccxt) — no freqtrade dependency.
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import ccxt
import pandas as pd

_OUT = Path(__file__).resolve().parent.parent / "user_data" / "data" / "binance"
_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000,
       "4h": 14_400_000, "1d": 86_400_000, "1w": 604_800_000}


def fetch(ex, symbol: str, tf: str, since_ms: int) -> pd.DataFrame:
    step = _MS[tf]
    rows: list = []
    cur = since_ms
    now = ex.milliseconds()
    while cur < now:
        batch = ex.fetch_ohlcv(symbol, timeframe=tf, since=cur, limit=1000)
        if not batch:
            break
        rows += batch
        cur = batch[-1][0] + step
        if len(batch) < 1000:
            break
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"]).drop_duplicates("ts")
    df["date"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df[["date", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pairs", nargs="+")
    ap.add_argument("--timeframes", nargs="+", default=["1h", "1d"])
    ap.add_argument("--since", default="2017-08-01")
    a = ap.parse_args()
    since_ms = int(dt.datetime.fromisoformat(a.since).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    ex = ccxt.binance({"enableRateLimit": True})
    _OUT.mkdir(parents=True, exist_ok=True)
    for pair in a.pairs:
        for tf in a.timeframes:
            df = fetch(ex, pair, tf, since_ms)
            if df.empty:
                print(f"{pair} {tf}: no data")
                continue
            out = _OUT / f"{pair.replace('/', '_')}-{tf}.feather"
            df.to_feather(out)
            print(f"{pair} {tf}: {len(df)} rows → {out.name} ({df['date'].min().date()}→{df['date'].max().date()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
