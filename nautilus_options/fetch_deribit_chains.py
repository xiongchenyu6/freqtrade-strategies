"""Fetch monthly Deribit BTC option-chain opening snapshots from the Tardis.dev FREE tier
(first-of-month, no API key). Streams the gz and stops after a short window so we pull only
~tens of MB instead of the full ~1.9 GB/day file.

Writes one compact CSV per month to data/deribit_chains/<YYYY-MM>.csv with the columns the
CSP backtest needs (BTC puts only).

Usage:
  python fetch_deribit_chains.py 2024-01            # one month
  python fetch_deribit_chains.py 2019-04 2026-05    # inclusive range (1st of each month)
"""

from __future__ import annotations

import csv
import gzip
import subprocess
import sys
from pathlib import Path

_OUT = Path(__file__).resolve().parent.parent / "data" / "deribit_chains"
WINDOW_US = 30 * 60 * 1_000_000  # keep the first 30 min → one opening snapshot
KEEP = ["symbol", "strike_price", "expiration", "bid_price", "ask_price", "mark_price",
        "mark_iv", "delta", "open_interest", "underlying_price", "timestamp"]


def _url(year: int, month: int) -> str:
    return f"https://datasets.tardis.dev/v1/deribit/options_chain/{year:04d}/{month:02d}/01/OPTIONS.csv.gz"


def fetch_month(year: int, month: int) -> int:
    out = _OUT / f"{year:04d}-{month:02d}.csv"
    if out.exists():
        print(f"{year}-{month:02d}: exists, skip")
        return sum(1 for _ in open(out)) - 1
    curl = subprocess.Popen(
        ["/run/current-system/sw/bin/curl", "-s", "--max-time", "120", _url(year, month)],
        stdout=subprocess.PIPE,
    )
    seen: dict[str, dict] = {}
    first_ts = None
    try:
        with gzip.GzipFile(fileobj=curl.stdout) as gz:
            header = gz.readline().decode().strip().split(",")
            idx = {c: header.index(c) for c in KEEP if c in header}
            for raw in gz:
                row = raw.decode().split(",")
                try:
                    ts = int(row[idx["timestamp"]])
                except (ValueError, IndexError):
                    continue
                if first_ts is None:
                    first_ts = ts
                if ts - first_ts > WINDOW_US:
                    break
                sym = row[idx["symbol"]]
                # BTC puts only
                if not sym.startswith("BTC-") or not sym.endswith("-P"):
                    continue
                if sym not in seen:
                    seen[sym] = {c: row[idx[c]] for c in idx}
    finally:
        curl.stdout.close()
        curl.terminate()

    if not seen:
        print(f"{year}-{month:02d}: NO DATA (month may be missing on free tier)")
        return 0
    cols = [c for c in KEEP if c in next(iter(seen.values()))]
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in seen.values():
            w.writerow(r)
    print(f"{year}-{month:02d}: {len(seen)} BTC puts -> {out.name}")
    return len(seen)


def _months(a: str, b: str):
    ay, am = map(int, a.split("-"))
    by, bm = map(int, b.split("-"))
    y, m = ay, am
    while (y, m) <= (by, bm):
        yield y, m
        m += 1
        if m > 12:
            y, m = y + 1, 1


def main(argv: list[str]) -> int:
    _OUT.mkdir(parents=True, exist_ok=True)
    if len(argv) == 1:
        y, m = map(int, argv[0].split("-"))
        fetch_month(y, m)
    elif len(argv) == 2:
        for y, m in _months(argv[0], argv[1]):
            try:
                fetch_month(y, m)
            except Exception as e:
                print(f"{y}-{m:02d}: ERROR {e!r}")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
