"""Fetch CBOE VIX daily history from Yahoo Finance into data/vix_history.csv
(columns: date,value) — the equity sentiment series for the regime gate (FNG→VIX).

VIX is the equity analog of crypto Fear & Greed: high VIX = panic/high volatility.
The HonestTrendEquity regime gate uses it as `block_above` (don't open new trend longs
during a high-volatility panic regime). Operator can tune the threshold (default 30).

stdlib only (urllib) — no extra deps. Run:
  nautilus_equity/.venv/bin/python nautilus_equity/fetch_vix.py
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path

_OUT = Path(__file__).resolve().parent.parent / "data" / "vix_history.csv"
_URL = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?range=15y&interval=1d"


def _curl() -> str:
    # urllib lacks a CA bundle in the Nix env; curl ships its own and works.
    return shutil.which("curl") or "/run/current-system/sw/bin/curl"


def fetch() -> list[tuple[str, float]]:
    out = subprocess.run(
        [_curl(), "-s", "--max-time", "30", "-A", "Mozilla/5.0", _URL],
        capture_output=True, text=True, check=True,
    ).stdout
    payload = json.loads(out)
    result = payload["chart"]["result"][0]
    ts = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]
    rows: list[tuple[str, float]] = []
    for t, c in zip(ts, closes):
        if c is None:
            continue
        d = dt.datetime.fromtimestamp(t, tz=dt.timezone.utc).strftime("%Y-%m-%d")
        rows.append((d, round(float(c), 2)))
    return rows


def main() -> int:
    rows = fetch()
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(_OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "value"])
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {_OUT}")
    if rows:
        print(f"range: {rows[0][0]} -> {rows[-1][0]}  (last VIX {rows[-1][1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
