#!/usr/bin/env python3
"""
Sync freqtrade feather OHLCV files → TimescaleDB hypertable `quant.ohlc`.

Only 1m files are loaded (the continuous aggregates build 15m/1h/1d from 1m).
Incremental: each run only loads candles with ts > max(ts) already in DB.

Usage:
  sops exec-env secrets.env 'python scripts/sync_feather_to_timescale.py'
  sops exec-env secrets.env 'python scripts/sync_feather_to_timescale.py --full'
  sops exec-env secrets.env 'python scripts/sync_feather_to_timescale.py --pairs BTC/USDT ETH/USDT'

Env:
  TIMESCALE_URL   postgres://... (required)
  TIMESCALE_SCHEMA  default 'quant'
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import psycopg2


PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR    = PROJECT_DIR / "user_data" / "data" / "binance"
SCHEMA      = os.environ.get("TIMESCALE_SCHEMA", "quant")
DB_URL      = os.environ.get("TIMESCALE_URL")


def connect():
    if not DB_URL:
        sys.exit("TIMESCALE_URL not set (try: sops exec-env secrets.env ...)")
    return psycopg2.connect(DB_URL)


def pair_from_filename(p: Path) -> str:
    # BTC_USDT-1m.feather → BTC/USDT
    stem = p.stem.replace(f"-1m", "")
    base, quote = stem.split("_", 1)
    return f"{base}/{quote}"


def existing_max_ts(cur, pair: str, tf: str):
    cur.execute(
        f"SELECT max(ts) FROM {SCHEMA}.ohlc WHERE pair=%s AND tf=%s",
        (pair, tf),
    )
    return cur.fetchone()[0]


def load_feather(path: Path) -> pd.DataFrame:
    df = pd.read_feather(path)
    df = df[["date", "open", "high", "low", "close", "volume"]].copy()
    df["date"] = pd.to_datetime(df["date"], utc=True)
    return df


def copy_rows(conn, pair: str, tf: str, df: pd.DataFrame, batch_size: int = 500_000):
    """Efficient bulk COPY; auto-chunks."""
    if df.empty:
        return 0
    total = 0
    for i in range(0, len(df), batch_size):
        chunk = df.iloc[i:i + batch_size]
        buf = io.StringIO()
        for _, r in chunk.iterrows():
            buf.write(
                f"{pair}\t{tf}\t{r['date'].isoformat()}\t"
                f"{r['open']}\t{r['high']}\t{r['low']}\t"
                f"{r['close']}\t{r['volume']}\n"
            )
        buf.seek(0)
        with conn.cursor() as cur:
            # copy_from chokes on schema-qualified table names; use copy_expert
            cur.copy_expert(
                f"COPY {SCHEMA}.ohlc (pair, tf, ts, open, high, low, close, volume) "
                f"FROM STDIN WITH (FORMAT text, DELIMITER E'\\t')",
                buf,
            )
        conn.commit()
        total += len(chunk)
        print(f"    chunk {i // batch_size + 1}: +{len(chunk):,} rows "
              f"(cum {total:,}/{len(df):,})")
    return total


def sync_pair(conn, feather_path: Path, full: bool, tf: str = "1m") -> int:
    pair = pair_from_filename(feather_path)
    df = load_feather(feather_path)
    if df.empty:
        print(f"  {pair}: feather empty")
        return 0

    with conn.cursor() as cur:
        cutoff = None if full else existing_max_ts(cur, pair, tf)

    if cutoff:
        df = df[df["date"] > cutoff]
        mode = f"incremental (from {cutoff})"
    else:
        mode = "full load"

    if df.empty:
        print(f"  {pair:<12} {tf}  {mode:<30}  already current, 0 rows")
        return 0

    print(f"  {pair:<12} {tf}  {mode:<30}  loading {len(df):,} rows "
          f"({df['date'].min()} → {df['date'].max()})")
    n = copy_rows(conn, pair, tf, df)
    return n


def refresh_aggregates(conn):
    """Force full refresh of continuous aggregates after bulk load.

    `refresh_continuous_aggregate` is a TimescaleDB procedure that must
    run *outside* a transaction. psycopg2 starts an implicit txn for any
    cursor execute by default, so we use a fresh connection in autocommit
    mode rather than fighting the existing one's state.
    """
    # Re-use the same DSN as the parent connection.
    conn.commit()
    fresh = psycopg2.connect(DB_URL)
    fresh.autocommit = True
    try:
        with fresh.cursor() as cur:
            for view in ("ohlc_15m", "ohlc_1h", "ohlc_1d"):
                print(f"  refreshing {SCHEMA}.{view} …")
                cur.execute(
                    f"CALL refresh_continuous_aggregate('{SCHEMA}.{view}', NULL, NULL)"
                )
    finally:
        fresh.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true",
                    help="Ignore DB state; reload all rows (idempotent, but slow).")
    ap.add_argument("--pairs", nargs="*",
                    help="Only sync these pairs (e.g. BTC/USDT). Default: all 1m feathers.")
    ap.add_argument("--no-refresh", action="store_true",
                    help="Skip refreshing continuous aggregates (faster for multi-run).")
    args = ap.parse_args()

    pairs_filter = None
    if args.pairs:
        pairs_filter = set(p.upper().replace("/", "_") for p in args.pairs)

    feathers = sorted(DATA_DIR.glob("*_USDT-1m.feather"))
    if pairs_filter:
        feathers = [f for f in feathers
                    if any(f.stem.startswith(pf) for pf in pairs_filter)]

    if not feathers:
        sys.exit(f"no 1m feather files under {DATA_DIR}")

    print(f"syncing {len(feathers)} file(s) → {SCHEMA}.ohlc")
    url = urlparse(DB_URL)
    print(f"target: {url.hostname}:{url.port}/{url.path.lstrip('/')} (schema={SCHEMA})")

    t0 = time.time()
    total = 0
    with connect() as conn:
        for f in feathers:
            total += sync_pair(conn, f, full=args.full)

        if not args.no_refresh and total > 0:
            print("\nrefreshing continuous aggregates (15m / 1h / 1d)…")
            refresh_aggregates(conn)

    print(f"\n✓ total inserted: {total:,} rows in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
