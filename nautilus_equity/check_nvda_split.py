"""Data-integrity check: NVDA 2024 10-for-1 split (effective 2024-06-10).

IB historical STK bars (whatToShow=TRADES) are split/dividend back-adjusted, so a
correctly-loaded series should be CONTINUOUS across the split date — no ~10x jump.
This prints the NVDA daily closes around 2024-06-06..2024-06-12 with adjacent-day
close ratios and states the verdict.

Run:  nautilus_equity/.venv/bin/python nautilus_equity/check_nvda_split.py
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from nautilus_trader.core.datetime import unix_nanos_to_dt
from nautilus_trader.persistence.catalog import ParquetDataCatalog

_HERE = Path(__file__).resolve().parent
_CATALOG = _HERE / "catalog"
_SPLIT_DATE = dt.date(2024, 6, 10)


def main() -> int:
    catalog = ParquetDataCatalog(str(_CATALOG))
    bars = catalog.bars(bar_types=["NVDA.NASDAQ-1-DAY-LAST-EXTERNAL"])

    rows = []
    for b in bars:
        d = unix_nanos_to_dt(b.ts_event).date()
        if dt.date(2024, 6, 4) <= d <= dt.date(2024, 6, 14):
            rows.append((d, float(b.close)))
    rows.sort(key=lambda r: r[0])

    print("=" * 64)
    print("  NVDA 10:1 split data-integrity check (split effective 2024-06-10)")
    print("=" * 64)
    print(f"{'date':<12} {'weekday':<10} {'close':>10} {'ratio vs prev':>16}")
    print("-" * 52)

    max_ratio = 0.0
    prev = None
    for d, close in rows:
        if prev is None:
            ratio_str = "    --"
        else:
            ratio = close / prev
            max_ratio = max(max_ratio, ratio, 1.0 / ratio)
            ratio_str = f"{ratio:>10.4f}"
            mark = ""
            if ratio > 3.0 or ratio < (1 / 3.0):
                mark = "  <-- SPLIT JUMP!"
            ratio_str += mark
        flag = "  <== split date" if d == _SPLIT_DATE else ""
        print(f"{d!s:<12} {d.strftime('%A'):<10} {close:>10.2f} {ratio_str}{flag}")
        prev = close

    print("-" * 52)
    print(f"max adjacent-day move in window: {max_ratio:.4f}x")
    adjusted = max_ratio < 2.0  # any real ~10x split jump would dwarf this
    if adjusted:
        print("VERDICT: SPLIT-ADJUSTED & CONTINUOUS. No ~10x discontinuity across")
        print("         2024-06-10; adjacent closes move within normal daily range.")
    else:
        print("VERDICT: NOT ADJUSTED — a large discontinuity (~10x or ~0.1x) is")
        print("         present across the split date. Series is RAW, not back-adjusted.")
    return 0 if adjusted else 1


if __name__ == "__main__":
    raise SystemExit(main())
