"""Pluggable regime / sentiment gate — the equity replacement for HonestTrend's
crypto Fear & Greed (FNG) entry filter.

freqtrade HonestTrendGeneric blocked entries when FNG >= 80 (don't buy into extreme
greed). Equities have no FNG; the analogous signals are VIX, put/call ratio, or the
CNN Fear & Greed Index. The *semantics* (which signal, which direction, what threshold)
are a deliberate decision left to the operator — so this gate is fully configurable and
**disabled by default** (no CSV ⇒ always allow), never silently blocking.

CSV format (same shape as data/fng_history.csv): header `date,value`, date `YYYY-MM-DD`.
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path


class RegimeGate:
    def __init__(
        self,
        csv_path: str | None = None,
        threshold: float = 80.0,
        mode: str = "block_above",  # 'block_above' | 'block_below'
        default_value: float = 50.0,
    ):
        if mode not in ("block_above", "block_below"):
            raise ValueError(f"mode must be block_above|block_below, got {mode!r}")
        self.threshold = threshold
        self.mode = mode
        self.default_value = default_value
        self._data: dict[str, float] = {}
        self.enabled = bool(csv_path)
        if csv_path:
            p = Path(csv_path)
            if not p.exists():
                raise FileNotFoundError(f"regime CSV not found: {p}")
            with open(p) as f:
                for row in csv.DictReader(f):
                    self._data[row["date"]] = float(row["value"])

    def value_on(self, when: dt.datetime | dt.date) -> float:
        key = when.strftime("%Y-%m-%d")
        return self._data.get(key, self.default_value)

    def allow(self, when: dt.datetime | dt.date) -> bool:
        """True if an entry is permitted under the current regime."""
        if not self.enabled:
            return True
        v = self.value_on(when)
        if self.mode == "block_above":
            return v < self.threshold
        return v > self.threshold
