#!/usr/bin/env python3
"""Convert Binance Vision CSV dumps to Freqtrade feather format.

Reads:  data_bulk/<SYMBOL>/<TIMEFRAME>/*.csv
Writes: user_data/data/binance/<BASE>_<QUOTE>-<TIMEFRAME>.feather
        (merged with existing feather on overlapping dates, union kept)

Usage:  scripts/binance_vision_to_feather.py BTCUSDT 1m
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

QUOTES = ("USDT", "USDC", "FDUSD", "BUSD", "TUSD", "BTC", "ETH", "BNB")
COLS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "qav", "trades", "tbav", "tqav", "ignore",
]


def split_pair(symbol: str) -> tuple[str, str]:
    for q in QUOTES:
        if symbol.endswith(q):
            return symbol[: -len(q)], q
    raise SystemExit(f"Unknown quote currency in symbol: {symbol}")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: binance_vision_to_feather.py SYMBOL TIMEFRAME")

    symbol, timeframe = sys.argv[1], sys.argv[2]
    base, quote = split_pair(symbol)

    project_dir = Path(__file__).resolve().parent.parent
    stage_dir = project_dir / "data_bulk" / symbol / timeframe
    out_dir = project_dir / "user_data" / "data" / "binance"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{base}_{quote}-{timeframe}.feather"

    csvs = sorted(stage_dir.glob(f"{symbol}-{timeframe}-*.csv"))
    if not csvs:
        raise SystemExit(f"No CSVs in {stage_dir}")

    print(f"Reading {len(csvs)} CSV files from {stage_dir} …")
    frames = []
    for f in csvs:
        # Binance CSVs sometimes have a header row (newer files), sometimes not.
        # Detect by peeking at first byte.
        with f.open("rb") as fh:
            first = fh.read(1)
        header = 0 if first in (b"o", b"O") else None
        df = pd.read_csv(f, header=header, names=COLS)
        # open_time can be ms (13 digits) or us (16 digits); normalise to ms
        if df["open_time"].iloc[0] > 10**14:
            df["open_time"] = df["open_time"] // 1000
        df["date"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        frames.append(df[["date", "open", "high", "low", "close", "volume"]])

    new_df = pd.concat(frames, ignore_index=True)
    new_df = (
        new_df.sort_values("date")
        .drop_duplicates(subset="date", keep="last")
        .reset_index(drop=True)
    )

    if out_file.exists():
        old = pd.read_feather(out_file)
        # Ensure tz-aware on both sides
        if old["date"].dt.tz is None:
            old["date"] = old["date"].dt.tz_localize("UTC")
        merged = pd.concat([old, new_df], ignore_index=True)
        merged = (
            merged.sort_values("date")
            .drop_duplicates(subset="date", keep="last")
            .reset_index(drop=True)
        )
        print(f"Merged with existing {out_file.name}: {len(old):,} + {len(new_df):,} → {len(merged):,}")
    else:
        merged = new_df
        print(f"New feather: {len(merged):,} rows")

    # Enforce dtypes freqtrade expects
    for col in ("open", "high", "low", "close", "volume"):
        merged[col] = merged[col].astype("float64")

    merged.to_feather(out_file)
    print(
        f"Wrote {out_file}\n"
        f"  rows:  {len(merged):,}\n"
        f"  range: {merged['date'].min()} → {merged['date'].max()}"
    )


if __name__ == "__main__":
    main()
